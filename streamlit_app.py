"""
八字 Agent — Streamlit 网页版

启动：
    streamlit run streamlit_app.py

依赖（已加入 requirements.txt）：
    streamlit>=1.36
"""

import os
from datetime import datetime, date
from pathlib import Path

import dotenv
import streamlit as st

from openrouter_client import call_json_openrouter
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
)
from workflow import (
    _agents,
    _save_json,
    _save_text,
    merge_round1,
    run_round2,
    reconcile_one,
    apply_reconcile_patch,
    write_final,
    answer_followup,
)

dotenv.load_dotenv()

st.set_page_config(page_title="八字 Agent", layout="wide", page_icon="🪙")

# ============== 顶部 ==============

st.title("八字洞察引擎：先验盘，再验事，后定未来")
st.caption("精准排盘打底 + 多模型交叉验证 + 前事回验+ 分歧仲裁。让命理判断更稳、更准、更可解释。仅供研究 / 娱乐参考。")

MODEL_OPTIONS = [
    MODEL_GPT,
    MODEL_GEMINI,
    MODEL_QWEN,
    MODEL_DEEPSEEK,
]

MAX_FOLLOWUP_QUESTIONS = 5

# 结果区视图（替代 st.tabs，便于追问完成后停留在当前 tab）
RESULT_TAB_LABELS = [
    "📜 最终报告",
    "💬 追问",
    "🔮 排盘",
    "1️⃣ 第一轮",
    "2️⃣ 第二轮",
    "⚖️ 仲裁日志",
    "💾 下载",
]
RESULT_TAB_FOLLOWUP = 1

# ============== Sidebar：输入 ==============

with st.sidebar:
    st.header("输入")

    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        api_key = st.secrets.get("OPENROUTER_API_KEY", "")
    if api_key:
        st.success("已读取 OpenRouter API Key（.env 或 Streamlit secrets）")
    else:
        st.error("未发现 OPENROUTER_API_KEY（请配置 .env 或 Streamlit secrets）")

    st.subheader("出生信息（公历）")
    birth_date = st.date_input(
        "出生日期",
        value=None,
        min_value=date(1900, 1, 1),
        max_value=date.today(),
    )
    c_birth_h, c_birth_m = st.columns(2)
    with c_birth_h:
        birth_hour = st.number_input(
            "出生小时", min_value=0, max_value=23, value=None, step=1, placeholder="0-23"
        )
    with c_birth_m:
        birth_minute = st.number_input(
            "出生分钟", min_value=0, max_value=59, value=None, step=1, placeholder="0-59"
        )
    gender = st.selectbox("性别", ["女", "男"], index=None, placeholder="请选择")

    st.subheader("已发生之事（3条）")
    raw_events = []
    for i in range(3):
        with st.container(border=True):
            ev = st.text_input(
                f"事件 {i + 1}", key=f"ev_{i}", value="", placeholder="如：换工作"
            )
            c1, c2 = st.columns(2)
            with c1:
                yr_text = st.text_input(
                    "年份", key=f"yr_{i}", value="", placeholder="如：2023"
                )
            with c2:
                fl = st.selectbox(
                    "体感", ["吉", "凶", "动", "平"],
                    index=0,
                    key=f"fl_{i}",
                )
            year = int(yr_text) if yr_text.strip().isdigit() else None
            raw_events.append({"event": ev.strip(), "year": year, "feeling": fl})

    st.subheader("最关心的问题（至多3条）")
    raw_focus_questions = []
    for i in range(3):
        q = st.text_input(
            f"问题 {i + 1}",
            key=f"focus_q_{i}",
            value="",
            placeholder="如：我何时更适合跳槽/结婚/创业？",
        )
        raw_focus_questions.append(q.strip())

    st.subheader("报告称呼（可选）")
    report_salutation = st.text_input(
        "希望报告中如何称呼你（用于一级标题与开篇）",
        value="",
        key="report_salutation_input",
        placeholder="如：小林、张女士、命主本人；不填则用中性标题，不用日干+性别自拟头衔",
    )

    st.subheader("模型设置")
    consensus_model = st.selectbox(
        "整合 / 第二轮模型",
        options=MODEL_OPTIONS,
        index=MODEL_OPTIONS.index(DEFAULT_CONSENSUS_MODEL) if DEFAULT_CONSENSUS_MODEL in MODEL_OPTIONS else 0,
    )
    final_model = st.selectbox(
        "终稿模型",
        options=MODEL_OPTIONS,
        index=MODEL_OPTIONS.index(DEFAULT_FINAL_MODEL) if DEFAULT_FINAL_MODEL in MODEL_OPTIONS else 0,
    )
    max_reconcile = st.slider("最大仲裁轮数", 0, 3, 2)
    extra_year_window = st.slider("流年表覆盖到今年 +N 年", 0, 20, 15)

    run_btn = st.button("开始分析", type="primary", use_container_width=True)

# ============== Session state ==============

if "result" not in st.session_state:
    st.session_state["result"] = None
if "followup_turns" not in st.session_state:
    st.session_state["followup_turns"] = []
if "result_tab_idx" not in st.session_state:
    st.session_state["result_tab_idx"] = 0
if "followup_input_revision" not in st.session_state:
    st.session_state["followup_input_revision"] = 0

# ============== 执行 ==============

def _scalar_to_text(value):
    if value is None:
        return "`null`"
    if isinstance(value, bool):
        return "`true`" if value else "`false`"
    if isinstance(value, (int, float)):
        return f"`{value}`"
    text = str(value).replace("\n", "  \n")
    return text if text else "_空字符串_"


def _to_markdown(data):
    lines = []

    def walk(value, indent=0):
        pad = "  " * indent
        if isinstance(value, dict):
            if not value:
                lines.append(f"{pad}- _空对象_")
                return
            for k, v in value.items():
                if isinstance(v, (dict, list)):
                    lines.append(f"{pad}- **{k}**")
                    walk(v, indent + 1)
                else:
                    lines.append(f"{pad}- **{k}**: {_scalar_to_text(v)}")
        elif isinstance(value, list):
            if not value:
                lines.append(f"{pad}- _空列表_")
                return
            for i, item in enumerate(value, 1):
                if isinstance(item, (dict, list)):
                    lines.append(f"{pad}- **[{i}]**")
                    walk(item, indent + 1)
                else:
                    lines.append(f"{pad}- [{i}] {_scalar_to_text(item)}")
        else:
            lines.append(f"{pad}- {_scalar_to_text(value)}")

    walk(data)
    return "\n".join(lines)

def _call_one_agent(agent, natal_chart, events, api_key):
    res = call_json_openrouter(
        model=agent["model"],
        api_key=api_key,
        messages=[
            {"role": "system", "content": ROUND1_SYSTEM},
            {
                "role": "user",
                "content": build_round1_prompt(natal_chart, events, agent["style"]),
            },
        ],
        temperature=0,
    )
    res["_speaker"] = agent["name"]
    res["_model"] = agent["model"]
    return res


if run_btn:
    events = [e for e in raw_events if e["event"]]
    focus_questions = [q for q in raw_focus_questions if q]
    if not api_key:
        st.error("请先在 .env 中设置 OPENROUTER_API_KEY")
        st.stop()
    if birth_date is None or birth_hour is None or birth_minute is None or not gender:
        st.error("请完整填写出生日期、出生小时、出生分钟和性别")
        st.stop()
    if any(e["year"] is None for e in events):
        st.error("已填写的事件需要同时填写合法年份（4位数字）")
        st.stop()
    if not events:
        st.error("请至少填写一条已发生之事")
        st.stop()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("results_v2") / ts
    output_dir.mkdir(parents=True, exist_ok=True)
    st.toast(f"输出目录：{output_dir}", icon="📁")

    # ---- Step 0：排盘 ----
    with st.status("Step 0 — 排盘 tool", expanded=True) as s0:
        try:
            chart = compute_chart(
                birth_date.year, birth_date.month, birth_date.day,
                int(birth_hour), int(birth_minute), gender,
            )
        except Exception as e:
            s0.update(label="Step 0 — 排盘失败", state="error")
            st.exception(e)
            st.stop()
        natal_chart = chart_natal_only(chart)

        c1, c2 = st.columns(2)
        with c1:
            st.write("**四柱**")
            st.markdown(_to_markdown(chart["natal"]))
        with c2:
            st.write("**起运**")
            st.markdown(_to_markdown(chart["qi_yun"]))
        with st.expander("大运表"):
            st.markdown(_to_markdown(chart["da_yun"]))

        event_years = [e["year"] for e in events]
        today = datetime.now().year
        start_y = min(event_years)
        end_y = today + extra_year_window
        liunian_table = liunian_for_year_range(start_y, end_y, chart)
        extra = liunian_for_years(
            [y for y in event_years if y < start_y or y > end_y], chart
        )
        if extra:
            merged = {x["year"]: x for x in liunian_table + extra}
            liunian_table = sorted(merged.values(), key=lambda x: x["year"])

        with st.expander(f"流年表（{len(liunian_table)} 项）"):
            st.markdown(_to_markdown(liunian_table))

        _save_json(
            {"chart": chart, "events": events, "liunian_table": liunian_table},
            str(output_dir / "step0_inputs.json"),
        )
        s0.update(label="Step 0 — 排盘完成", state="complete")

    # ---- Step 1：多模型 + 整合 ----
    agents = _agents()
    round1_outputs = []
    with st.status(f"Step 1 — {len(agents)} 个模型确定格局 + 用神", expanded=True) as s1:
        for agent in agents:
            with st.spinner(f"{agent['name']} ({agent['model']}) 分析中..."):
                try:
                    res = _call_one_agent(agent, natal_chart, events, api_key)
                except Exception as e:
                    st.error(f"{agent['name']} 调用失败：{e}")
                    continue
                round1_outputs.append(res)
                pat = res.get("pattern", "?")
                hyps = ", ".join(
                    f"{h.get('id')}={h.get('use_god')}({h.get('confidence')})"
                    for h in res.get("use_gods_hypotheses", [])
                )
                st.write(f"✓ **{agent['name']}** 格局：{pat} ｜ 候选：{hyps}")

        if not round1_outputs:
            s1.update(label="Step 1 — 全部模型失败", state="error")
            st.stop()
        _save_json(round1_outputs, str(output_dir / "step1_round1_raw.json"))

        with st.spinner(f"整合（{consensus_model}）..."):
            round1_consensus = merge_round1(
                natal_chart, events, round1_outputs, api_key, consensus_model
            )
        _save_json(round1_consensus, str(output_dir / "step1_round1_consensus.json"))
        st.write(
            f"**主用神候选**：`{round1_consensus.get('primary_hypothesis_id')}` ｜ "
            f"格局：{round1_consensus.get('pattern', '?')} "
            f"({round1_consensus.get('pattern_confidence', '?')})"
        )
        with st.expander("整合后的用神候选"):
            st.markdown(_to_markdown(round1_consensus.get("use_gods_candidates", [])))
        s1.update(label="Step 1 — 完成", state="complete")

    # ---- Step 2：大运 / 流年 / 前事对照 ----
    with st.status("Step 2 — 大运·流年解读 + 前事对照", expanded=True) as s2:
        with st.spinner(f"解读中（{consensus_model}）..."):
            round2_result = run_round2(
                chart, events, round1_consensus,
                chart["da_yun"], liunian_table,
                api_key, consensus_model,
            )
        _save_json(round2_result, str(output_dir / "step2_round2.json"))

        n_conflicts = len(round2_result.get("conflicts", []) or [])
        st.write(
            f"前事对照 {len(round2_result.get('past_event_alignment', []) or [])} 条 ｜ "
            f"冲突 **{n_conflicts}** 条"
        )
        with st.expander("前事对照表"):
            st.markdown(_to_markdown(round2_result.get("past_event_alignment", [])))
        if n_conflicts:
            with st.expander("冲突列表"):
                st.markdown(_to_markdown(round2_result.get("conflicts", [])))
        s2.update(
            label=f"Step 2 — 完成（冲突 {n_conflicts} 条）",
            state="complete",
        )

    # ---- Step 3：仲裁 ----
    reconcile_log = []
    iter_used = 0
    conflicts = list(round2_result.get("conflicts", []) or [])
    with st.status("Step 3 — 矛盾仲裁", expanded=True) as s3:
        if not conflicts:
            st.info("无冲突，跳过")
        while conflicts and iter_used < max_reconcile:
            rerun_triggered = False
            for conflict in conflicts:
                summary = (conflict.get("summary") or "")[:40]
                with st.spinner(f"仲裁：{summary}"):
                    patch = reconcile_one(
                        chart, events, round1_consensus, round2_result,
                        conflict, api_key, consensus_model,
                    )
                reconcile_log.append(
                    {"iter": iter_used, "conflict": conflict, "patch": patch}
                )
                round1_consensus, round2_result, need_rerun = apply_reconcile_patch(
                    round1_consensus, round2_result, patch
                )
                st.write(
                    f"- `{patch.get('resolution')}` ｜ {patch.get('rationale', '')[:80]}"
                )
                if need_rerun:
                    with st.spinner("用神已修正 → 重跑 Round 2 ..."):
                        round2_result = run_round2(
                            chart, events, round1_consensus,
                            chart["da_yun"], liunian_table,
                            api_key, consensus_model,
                        )
                    rerun_triggered = True
                    break
            iter_used += 1
            conflicts = (
                list(round2_result.get("conflicts", []) or [])
                if rerun_triggered
                else []
            )

        _save_json(
            {
                "reconcile_log": reconcile_log,
                "iters_used": iter_used,
                "final_round1": round1_consensus,
                "final_round2": round2_result,
            },
            str(output_dir / "step3_reconcile.json"),
        )
        s3.update(
            label=f"Step 3 — 仲裁完成（{iter_used} 轮 / {len(reconcile_log)} 次）",
            state="complete",
        )

    # ---- Step 4：终稿 ----
    with st.status("Step 4 — 生成最终报告", expanded=True) as s4:
        with st.spinner(f"撰写中（{final_model}）..."):
            report = write_final(
                chart,
                events,
                round1_consensus,
                round2_result,
                reconcile_log,
                api_key,
                final_model,
                focus_questions,
                report_salutation=report_salutation.strip() or None,
            )
        _save_text(report, str(output_dir / "final_report.md"))
        s4.update(label="Step 4 — 完成", state="complete")

    st.session_state["result"] = {
        "chart": chart,
        "events": events,
        "focus_questions": focus_questions,
        "liunian_table": liunian_table,
        "round1_outputs": round1_outputs,
        "round1_consensus": round1_consensus,
        "round2_result": round2_result,
        "reconcile_log": reconcile_log,
        "final_report": report,
        "output_dir": str(output_dir),
        "final_model": final_model,
        "report_salutation": (report_salutation.strip() or None),
    }
    st.session_state["followup_turns"] = []
    st.session_state["result_tab_idx"] = 0
    st.session_state["followup_input_revision"] = 0
    st.toast("分析完成", icon="✅")

# ============== 结果展示 ==============

result = st.session_state.get("result")
if result:
    st.divider()

    nav_cols = st.columns(len(RESULT_TAB_LABELS))
    for ti, label in enumerate(RESULT_TAB_LABELS):
        active = st.session_state["result_tab_idx"] == ti
        if nav_cols[ti].button(
            label,
            key=f"result_nav_{ti}",
            use_container_width=True,
            type="primary" if active else "secondary",
        ):
            st.session_state["result_tab_idx"] = ti

    tab_idx = st.session_state["result_tab_idx"]
    if tab_idx < 0 or tab_idx >= len(RESULT_TAB_LABELS):
        tab_idx = 0
        st.session_state["result_tab_idx"] = 0

    if tab_idx == 0:
        st.markdown(result["final_report"])

    elif tab_idx == RESULT_TAB_FOLLOWUP:
        st.caption(
            "基于当前这一次分析的排盘、共识与报告作答；会调用 OpenRouter（消耗额度）。"
            f"同一报告最多追问 **{MAX_FOLLOWUP_QUESTIONS}** 次；重新「开始分析」后追问记录会清空。"
        )
        fm_default = result.get("final_model") or DEFAULT_FINAL_MODEL
        idx_fm = (
            MODEL_OPTIONS.index(fm_default)
            if fm_default in MODEL_OPTIONS
            else 0
        )
        follow_model = st.selectbox(
            "追问所用模型",
            options=MODEL_OPTIONS,
            index=idx_fm,
            key="followup_model_choice",
        )

        turns = st.session_state.get("followup_turns") or []
        followup_at_limit = len(turns) >= MAX_FOLLOWUP_QUESTIONS
        if followup_at_limit:
            st.warning(
                f"已达到本次分析的最大追问次数（{MAX_FOLLOWUP_QUESTIONS} 次）。"
                "可清空记录后重新开始追问，或重新跑一次完整分析。"
            )
        if turns:
            st.subheader("对话记录")
            for i, turn in enumerate(turns, 1):
                with st.container(border=True):
                    st.markdown(f"**追问 {i}**")
                    st.markdown(turn.get("question") or "")
                    st.markdown("**回答**")
                    st.markdown(turn.get("answer") or "")
        else:
            st.info("还没有追问。可以先在「📜 最终报告」分区看完结论，再在此输入问题。")

        _fq_rev = int(st.session_state.get("followup_input_revision", 0))
        fq = st.text_area(
            "输入追问（可多轮）",
            height=120,
            placeholder="例如：未来三年若有跳槽打算，哪些年份更值得争取？依据报告里哪一段？",
            key=f"followup_question_input_v{_fq_rev}",
        )
        c_f1, c_f2 = st.columns([1, 1])
        with c_f1:
            send_follow = st.button(
                "发送追问",
                type="primary",
                key="followup_send_btn",
                disabled=followup_at_limit,
            )
        with c_f2:
            if st.button("清空追问记录", key="followup_clear_btn"):
                st.session_state["followup_turns"] = []
                st.session_state["followup_input_revision"] = _fq_rev + 1
                st.rerun()

        if send_follow:
            qtext = (fq or "").strip()
            if not api_key:
                st.error("未配置 OPENROUTER_API_KEY，无法追问")
            elif len(turns) >= MAX_FOLLOWUP_QUESTIONS:
                st.warning(f"已达到最大追问次数（{MAX_FOLLOWUP_QUESTIONS} 次）")
            elif not qtext:
                st.warning("请先输入追问内容")
            else:
                try:
                    status_msg = (
                        f"🧠 **正在思考中** · 模型 `{follow_model}` 生成回答中，"
                        "可能需要数十秒。"
                    )
                    with st.status("🧠 正在思考中…", expanded=True) as thought:
                        st.markdown(status_msg)
                        st.caption(
                            "模型推理可能需要数十秒；页面仍在工作。若长时间无响应，多半是网络或 API 限流，可稍后重试。"
                        )
                        ans = answer_followup(
                            result["chart"],
                            result.get("events") or [],
                            result["round1_consensus"],
                            result["round2_result"],
                            result.get("reconcile_log") or [],
                            result["final_report"],
                            turns,
                            qtext,
                            api_key,
                            follow_model,
                        )
                        thought.update(label="✅ 回答已生成", state="complete")
                except Exception as e:
                    st.error(f"追问失败：{e}")
                else:
                    st.session_state.setdefault("followup_turns", []).append(
                        {"question": qtext, "answer": ans}
                    )
                    st.session_state["result_tab_idx"] = RESULT_TAB_FOLLOWUP
                    st.session_state["followup_input_revision"] = _fq_rev + 1
                    st.rerun()

    elif tab_idx == 2:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("四柱")
            st.markdown(_to_markdown(result["chart"]["natal"]))
            st.subheader("起运")
            st.markdown(_to_markdown(result["chart"]["qi_yun"]))
        with c2:
            st.subheader("大运")
            st.markdown(_to_markdown(result["chart"]["da_yun"]))

    elif tab_idx == 3:
        st.subheader("整合共识")
        st.markdown(_to_markdown(result["round1_consensus"]))
        st.subheader("各模型原始输出")
        for r in result["round1_outputs"]:
            with st.expander(f"{r.get('_speaker')} — {r.get('_model')}"):
                st.markdown(_to_markdown(r))

    elif tab_idx == 4:
        st.markdown(_to_markdown(result["round2_result"]))

    elif tab_idx == 5:
        if result["reconcile_log"]:
            st.markdown(_to_markdown(result["reconcile_log"]))
        else:
            st.info("无冲突，未触发仲裁")

    elif tab_idx == 6:
        out_dir = Path(result["output_dir"])
        st.write(f"输出目录：`{out_dir}`")
        markdown_exports = [
            (
                "step0_inputs.md",
                _to_markdown(
                    {
                        "chart": result["chart"],
                        "events": result.get("events", []),
                        "liunian_table": result.get("liunian_table", []),
                    }
                ),
            ),
            ("step1_round1_raw.md", _to_markdown(result["round1_outputs"])),
            ("step1_round1_consensus.md", _to_markdown(result["round1_consensus"])),
            ("step2_round2.md", _to_markdown(result["round2_result"])),
            ("step3_reconcile.md", _to_markdown(result["reconcile_log"])),
            ("final_report.md", result["final_report"]),
        ]
        for fname, content in markdown_exports:
            st.download_button(
                f"下载 {fname}",
                content.encode("utf-8"),
                file_name=fname,
                mime="text/markdown",
                key=f"dl_{fname}",
            )
else:
    st.info("👈 在左侧填写信息后，点击「开始分析」")
