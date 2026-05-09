"""
v2 工作流（纯 Python，无 LangGraph）

  Step 0  排盘 tool（确定性）
  Step 1  多模型并行做格局 + 用神候选
  Step 1.5 整合候选清单
  Step 2  单模型基于 tool 的大运/流年表 → 解读 + 前事对照
  Step 3  对每条 conflict 做短 prompt 仲裁；必要时仅重跑 Step 2 一次
  Step 4  写最终报告并落盘

核心约束：
- 干支永远以 tool 为准；模型不排盘
- 出现"前事 ↔ 用神 ↔ 流年解释"冲突时不回退到 Round 1，
  而是按仲裁结论局部更新（用神 / 该年解读 / 追问 / 低置信度）
"""

from typing import List, Dict, Any, Tuple
from datetime import datetime
import json
import os

from openrouter_client import call_json_openrouter, call_openrouter
from config import (
    MODEL_GPT,
    MODEL_GEMINI,
    MODEL_QWEN,
    MODEL_DEEPSEEK,
    DEFAULT_CONSENSUS_MODEL,
    DEFAULT_FINAL_MODEL,
)
from tools.paipan import (
    compute_chart,
    chart_natal_only,
    liunian_for_year_range,
    liunian_for_years,
)
from prompts import (
    ROUND1_SYSTEM,
    build_round1_prompt,
    ROUND1_MERGE_SYSTEM,
    build_round1_merge_prompt,
    ROUND2_SYSTEM,
    build_round2_prompt,
    RECONCILE_SYSTEM,
    build_reconcile_prompt,
    FINAL_SYSTEM,
    build_final_prompt,
    FOLLOWUP_SYSTEM,
    build_followup_user_prompt,
)


def _agents() -> List[Dict[str, str]]:
    return [
        {
            "name": "GPT",
            "model": MODEL_GPT,
            "style": "格局派为主：先辨月令、格局、用神、相神，再用旺衰校验。",
        },
        {
            "name": "GEMINI",
            "model": MODEL_GEMINI,
            "style": "旺衰扶抑、调候、流通为主线，反过来检验格局是否成立。",
        },
        {
            "name": "QWEN",
            "model": MODEL_QWEN,
            "style": "细节核查：透干藏干、冲合刑害、清浊纯杂；侧重发现别人遗漏的反例。",
        },
        {
            "name": "DEEPSEEK",
            "model": MODEL_DEEPSEEK,
            "style": "整合派：综合两套方法论，输出更稳健的候选。",
        },
    ]


def _save_json(obj: Any, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _save_text(text: str, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------- Step 1: Round 1 多模型 ----------------

def run_round1(
    natal_chart: Dict[str, Any],
    events: List[Dict[str, Any]],
    api_key: str,
    agents: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    outputs = []
    for agent in agents:
        print(f"[Round 1] {agent['name']} ({agent['model']}) ...")
        res = call_json_openrouter(
            model=agent["model"],
            api_key=api_key,
            messages=[
                {"role": "system", "content": ROUND1_SYSTEM},
                {"role": "user", "content": build_round1_prompt(natal_chart, events, agent["style"])},
            ],
            temperature=0,
        )
        res["_speaker"] = agent["name"]
        res["_model"] = agent["model"]
        outputs.append(res)
    return outputs


def merge_round1(
    natal_chart: Dict[str, Any],
    events: List[Dict[str, Any]],
    round1_outputs: List[Dict[str, Any]],
    api_key: str,
    model: str,
) -> Dict[str, Any]:
    print(f"[Round 1 Merge] {model} ...")
    return call_json_openrouter(
        model=model,
        api_key=api_key,
        messages=[
            {"role": "system", "content": ROUND1_MERGE_SYSTEM},
            {"role": "user", "content": build_round1_merge_prompt(natal_chart, events, round1_outputs)},
        ],
        temperature=0,
    )


# ---------------- Step 2: Round 2 大运/流年解读 + 前事对照 ----------------

def run_round2(
    chart: Dict[str, Any],
    events: List[Dict[str, Any]],
    round1_consensus: Dict[str, Any],
    dayun_table: List[Dict[str, Any]],
    liunian_table: List[Dict[str, Any]],
    api_key: str,
    model: str,
) -> Dict[str, Any]:
    print(f"[Round 2] {model} ...")
    return call_json_openrouter(
        model=model,
        api_key=api_key,
        messages=[
            {"role": "system", "content": ROUND2_SYSTEM},
            {
                "role": "user",
                "content": build_round2_prompt(
                    chart, events, round1_consensus, dayun_table, liunian_table
                ),
            },
        ],
        temperature=0,
    )


# ---------------- Step 3: 仲裁冲突 ----------------

def reconcile_one(
    chart: Dict[str, Any],
    events: List[Dict[str, Any]],
    round1_consensus: Dict[str, Any],
    round2_result: Dict[str, Any],
    conflict: Dict[str, Any],
    api_key: str,
    model: str,
) -> Dict[str, Any]:
    summary = (conflict.get("summary") or "")[:40]
    print(f"[Reconcile] {summary!r} via {model}")
    return call_json_openrouter(
        model=model,
        api_key=api_key,
        messages=[
            {"role": "system", "content": RECONCILE_SYSTEM},
            {
                "role": "user",
                "content": build_reconcile_prompt(
                    chart, events, round1_consensus, round2_result, conflict
                ),
            },
        ],
        temperature=0,
    )


def apply_reconcile_patch(
    round1_consensus: Dict[str, Any],
    round2_result: Dict[str, Any],
    patch: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
    """
    返回 (新 consensus, 新 round2, need_rerun_round2)。
    need_rerun_round2 仅在用神被修改时为 True。
    """
    resolution = patch.get("resolution", "")
    need_rerun = False

    if resolution == "update_use_gods" and patch.get("updated_use_gods_candidates"):
        round1_consensus = dict(round1_consensus)
        round1_consensus["use_gods_candidates"] = patch["updated_use_gods_candidates"]
        if patch.get("new_primary_hypothesis_id"):
            round1_consensus["primary_hypothesis_id"] = patch["new_primary_hypothesis_id"]
        round1_consensus.setdefault("revision_log", []).append(
            patch.get("rationale", "用神候选被前事修正")
        )
        need_rerun = True

    elif resolution == "patch_year_interpretation":
        py = patch.get("year_interpretation_patch") or {}
        if py.get("year"):
            round2_result = dict(round2_result)
            kyl = list(round2_result.get("key_year_interpretations", []) or [])
            replaced = False
            for i, item in enumerate(kyl):
                if item.get("year") == py["year"]:
                    item = dict(item)
                    item["interpretation"] = py.get(
                        "new_interpretation", item.get("interpretation")
                    )
                    item["patched"] = True
                    kyl[i] = item
                    replaced = True
                    break
            if not replaced:
                kyl.append(
                    {
                        "year": py["year"],
                        "interpretation": py.get("new_interpretation", ""),
                        "patched": True,
                    }
                )
            round2_result["key_year_interpretations"] = kyl

    elif resolution == "needs_user_clarification":
        round2_result = dict(round2_result)
        round2_result.setdefault("needs_user_clarification", []).extend(
            patch.get("questions_to_user", []) or []
        )

    elif resolution == "accept_as_low_confidence":
        round2_result = dict(round2_result)
        note = patch.get("low_confidence_note", "")
        if note:
            round2_result.setdefault("low_confidence_notes", []).append(note)

    return round1_consensus, round2_result, need_rerun


# ---------------- Step 4: 终稿 ----------------

def write_final(
    chart: Dict[str, Any],
    events: List[Dict[str, Any]],
    round1_consensus: Dict[str, Any],
    round2_result: Dict[str, Any],
    reconcile_log: List[Dict[str, Any]],
    api_key: str,
    model: str,
    focus_questions: List[str] | None = None,
) -> str:
    print(f"[Final] {model} ...")
    return call_openrouter(
        model=model,
        api_key=api_key,
        messages=[
            {"role": "system", "content": FINAL_SYSTEM},
            {
                "role": "user",
                "content": build_final_prompt(
                    chart, events, round1_consensus, round2_result, reconcile_log, focus_questions
                ),
            },
        ],
        temperature=0,
    )


def answer_followup(
    chart: Dict[str, Any],
    events: List[Dict[str, Any]],
    round1_consensus: Dict[str, Any],
    round2_result: Dict[str, Any],
    reconcile_log: List[Dict[str, Any]],
    final_report: str,
    prior_turns: List[Dict[str, Any]],
    user_question: str,
    api_key: str,
    model: str,
) -> str:
    """基于已有分析材料回答追问（单次调用，上下文打包在用户消息内）。"""
    print(f"[Follow-up] {model} ...")
    return call_openrouter(
        model=model,
        api_key=api_key,
        messages=[
            {"role": "system", "content": FOLLOWUP_SYSTEM},
            {
                "role": "user",
                "content": build_followup_user_prompt(
                    chart,
                    events,
                    round1_consensus,
                    round2_result,
                    reconcile_log,
                    final_report,
                    prior_turns,
                    user_question,
                ),
            },
        ],
        temperature=0.2,
    )


# ---------------- 主入口 ----------------

def run_fortune(
    birth: Dict[str, int],
    gender,
    events: List[Dict[str, Any]],
    api_key: str,
    output_dir: str = "results_v2",
    consensus_model: str = DEFAULT_CONSENSUS_MODEL,
    round2_model: str = DEFAULT_CONSENSUS_MODEL,
    reconcile_model: str = DEFAULT_CONSENSUS_MODEL,
    final_model: str = DEFAULT_FINAL_MODEL,
    focus_questions: List[str] | None = None,
    max_reconcile_iters: int = 2,
    extra_year_window: int = 15,
) -> Dict[str, Any]:
    """
    birth   : {"year":1999,"month":3,"day":15,"hour":10,"minute":30}
    gender  : "男"/"女" 或 1/0
    events  : [{"event":"...","year":2020,"feeling":"凶|吉|动|平"}, ...]
    """
    # Step 0：排盘
    chart = compute_chart(
        birth["year"],
        birth["month"],
        birth["day"],
        birth.get("hour", 12),
        birth.get("minute", 0),
        gender,
    )
    natal_chart = chart_natal_only(chart)

    event_years = [e["year"] for e in events if isinstance(e.get("year"), int)]
    today = datetime.now().year
    start_y = min(event_years) if event_years else today
    end_y = today + extra_year_window
    liunian_table = liunian_for_year_range(start_y, end_y, chart)
    extra = liunian_for_years(
        [y for y in event_years if y < start_y or y > end_y], chart
    )
    if extra:
        liunian_table = sorted(
            {(x["year"]): x for x in liunian_table + extra}.values(),
            key=lambda x: x["year"],
        )
    dayun_table = chart["da_yun"]

    _save_json(
        {"chart": chart, "events": events, "liunian_table": liunian_table},
        os.path.join(output_dir, "step0_inputs.json"),
    )

    # Step 1：多模型 → 候选
    agents = _agents()
    round1_outputs = run_round1(natal_chart, events, api_key, agents)
    _save_json(round1_outputs, os.path.join(output_dir, "step1_round1_raw.json"))

    round1_consensus = merge_round1(
        natal_chart, events, round1_outputs, api_key, consensus_model
    )
    _save_json(
        round1_consensus, os.path.join(output_dir, "step1_round1_consensus.json")
    )

    # Step 2：解读 + 前事对照
    round2_result = run_round2(
        chart, events, round1_consensus, dayun_table, liunian_table, api_key, round2_model
    )
    _save_json(round2_result, os.path.join(output_dir, "step2_round2.json"))

    # Step 3：仲裁冲突
    reconcile_log: List[Dict[str, Any]] = []
    iter_used = 0
    conflicts = list(round2_result.get("conflicts", []) or [])
    while conflicts and iter_used < max_reconcile_iters:
        # 本轮内逐条仲裁；任一条触发用神修正就重跑 Round 2，跳出本轮
        rerun_triggered = False
        for conflict in conflicts:
            patch = reconcile_one(
                chart,
                events,
                round1_consensus,
                round2_result,
                conflict,
                api_key,
                reconcile_model,
            )
            reconcile_log.append({"iter": iter_used, "conflict": conflict, "patch": patch})
            round1_consensus, round2_result, need_rerun = apply_reconcile_patch(
                round1_consensus, round2_result, patch
            )
            if need_rerun:
                round2_result = run_round2(
                    chart,
                    events,
                    round1_consensus,
                    dayun_table,
                    liunian_table,
                    api_key,
                    round2_model,
                )
                rerun_triggered = True
                break

        iter_used += 1
        # 用神被改 → 用新 Round 2 的 conflicts；否则本轮已逐条处理完，结束
        conflicts = (
            list(round2_result.get("conflicts", []) or []) if rerun_triggered else []
        )

    _save_json(
        {
            "reconcile_log": reconcile_log,
            "iters_used": iter_used,
            "final_round1": round1_consensus,
            "final_round2": round2_result,
        },
        os.path.join(output_dir, "step3_reconcile.json"),
    )

    # Step 4：终稿
    report = write_final(
        chart,
        events,
        round1_consensus,
        round2_result,
        reconcile_log,
        api_key,
        final_model,
        focus_questions,
    )
    _save_text(report, os.path.join(output_dir, "final_report.md"))

    return {
        "chart": chart,
        "round1_consensus": round1_consensus,
        "round2_result": round2_result,
        "reconcile_log": reconcile_log,
        "focus_questions": focus_questions or [],
        "final_report": report,
        "output_dir": output_dir,
    }
