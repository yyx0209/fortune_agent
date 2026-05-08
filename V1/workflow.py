from typing import TypedDict, List, Dict, Any, Literal, Optional

from langgraph.graph import StateGraph, START, END

from openrouter_client import call_json_openrouter, call_openrouter
from prompts import (
    get_system_prompt,
    build_first_speaker_prompt,
    build_next_speaker_prompt,
    build_consensus_prompt,
    build_final_report_prompt,
)
from build_doc import build_bazi_docx_files
from config import (
    MODEL_GPT,
    MODEL_GEMINI,
    MODEL_QWEN,
    MODEL_DEEPSEEK,
    DEFAULT_ROUNDS,
    DEFAULT_OUTPUT_DEBATE_DOCX,
    DEFAULT_OUTPUT_RESULT_DOCX,
)


def make_agent_configs(
    model_a: str = MODEL_GPT,
    model_b: str = MODEL_GEMINI,
    # model_c: str = MODEL_CLAUDE,
    model_d: str = MODEL_QWEN,
    model_e: str = MODEL_DEEPSEEK,
) -> List[Dict[str, str]]:
    return [
        {
            "name": "A",
            "model": model_a,
            "system_prompt": get_system_prompt(
                "偏结构化、结论清晰、证据优先。"
                "分析时以子平格局为主线，先辨月令、格局、用神、相神，再用旺衰作辅助校验。"
            ),
        },
        {
            "name": "B",
            "model": model_b,
            "system_prompt": get_system_prompt(
                "偏审慎、强调稳健结论。"
                "分析时以旺衰、扶抑、调候、流通为主线，再反过来检查格局判断是否真正成立。"
            ),
        },
        # {
        #     "name": "C",
        #     "model": model_c,
        #     "system_prompt": get_system_prompt(
        #         "偏整合、擅长收敛分歧。"
        #         "分析时同时综合子平格局与旺衰派，重点判断两套逻辑是否一致，并给出更稳健的综合结论。"
        #     ),
        # },
        {
            "name": "D",
            "model": model_d,
            "system_prompt": get_system_prompt(
                "偏细致、重视细节核查。"
                "分析时重点检查十神配置、透干藏干、冲合刑害、病药与清浊纯杂，用于审查前面结论是否有漏洞。"
            ),
        },
        {
            "name": "E",
            "model": model_e,
            "system_prompt": get_system_prompt(
                "偏实用、强调现实映射。"
                "分析时重点把格局与旺衰的综合判断映射到学业、事业、财运、婚恋、健康和阶段发展，输出更落地的解释。"
            ),
        },
    ]


def dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        x_norm = x.strip()
        if x_norm and x_norm not in seen:
            seen.add(x_norm)
            out.append(x_norm)
    return out


def format_latest_consensus_summary(consensus_history: List[Dict[str, Any]]) -> str:
    if not consensus_history:
        return "- 暂无（尚未形成上一轮共识摘要）"

    last = consensus_history[-1]
    summary = last.get("summary", "") or "无"
    agreed = last.get("agreed_points", []) or []
    unresolved = last.get("still_unresolved", []) or []
    focus = last.get("next_focus", []) or []
    confidence = last.get("confidence_level", "") or "未知"

    agreed_text = "\n".join([f"- {x}" for x in agreed]) or "- 无"
    unresolved_text = "\n".join([f"- {x}" for x in unresolved]) or "- 无"
    focus_text = "\n".join([f"- {x}" for x in focus]) or "- 无"

    return (
        f"上一轮总结：{summary}\n"
        f"上一轮新增/强化共识：\n{agreed_text}\n"
        f"上一轮仍未解决分歧：\n{unresolved_text}\n"
        f"上一轮建议继续讨论焦点：\n{focus_text}\n"
        f"上一轮信心等级：{confidence}"
    )


def format_current_round_summary(
    transcript: List[Dict[str, Any]],
    current_round: int,
) -> str:
    """
    给同一轮后续 speaker 看的“本轮截至目前累计摘要”。
    只压缩当前轮已发言者，不包含未来发言。
    """
    current_round_records = [x for x in transcript if x["round"] == current_round]

    if not current_round_records:
        return "- 暂无（你是本轮第一个发言者）"

    parts = []
    for rec in current_round_records:
        core_claims = rec.get("core_claims", []) or []
        evidence = rec.get("evidence", []) or []
        consensus = rec.get("tentative_consensus", []) or []

        core_text = "\n".join([f"  - {x}" for x in core_claims]) or "  - 无"
        evidence_text = "\n".join([f"  - {x}" for x in evidence[:3]]) or "  - 无"
        consensus_text = "\n".join([f"  - {x}" for x in consensus]) or "  - 无"

        parts.append(
            f"发言者：{rec.get('speaker', '')}\n"
            f"核心判断：\n{core_text}\n"
            f"主要证据：\n{evidence_text}\n"
            f"其提出的可共识结论：\n{consensus_text}"
        )

    return "\n\n".join(parts)


class BaziDebateState(TypedDict):
    bazi_prompt: str
    api_key: str
    consensus_model: str
    final_model: str

    agent_configs: List[Dict[str, str]]

    max_rounds: int
    current_round: int
    current_agent_idx: int

    transcript: List[Dict[str, Any]]
    consensus_history: List[Dict[str, Any]]
    running_consensus: List[str]
    unresolved_points: List[str]
    next_focus: List[str]

    last_speaker: str
    last_message_text: str

    final_scores: Dict[str, Any]
    final_report: str
    debate_docx_path: str
    result_docx_path: str


def speaker_node(state: BaziDebateState) -> Dict[str, Any]:
    print(f"Round {state['current_round']} - Agent {state['current_agent_idx']} speaking...")

    agent = state["agent_configs"][state["current_agent_idx"]]
    agent_name = agent["name"]

    prior_consensus = "\n".join([f"- {x}" for x in state["running_consensus"]]) or "- 暂无"
    latest_consensus_summary = format_latest_consensus_summary(state["consensus_history"])
    current_round_summary = format_current_round_summary(
        state["transcript"],
        state["current_round"],
    )
    unresolved = "\n".join([f"- {x}" for x in state["unresolved_points"]]) or "- 暂无"
    next_focus = "\n".join([f"- {x}" for x in state["next_focus"]]) or "- 暂无"

    is_first_message = len(state["transcript"]) == 0

    if is_first_message:
        user_prompt = build_first_speaker_prompt(state["bazi_prompt"])
    else:
        user_prompt = build_next_speaker_prompt(
            bazi_prompt=state["bazi_prompt"],
            prior_consensus=prior_consensus,
            latest_consensus_summary=latest_consensus_summary,
            current_round_summary=current_round_summary,
            unresolved=unresolved,
            next_focus=next_focus,
            last_speaker=state["last_speaker"],
            last_message_text=state["last_message_text"],
        )

    result = call_json_openrouter(
        model=agent["model"],
        api_key=state["api_key"],
        messages=[
            {"role": "system", "content": agent["system_prompt"]},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )

    record = {
        "round": state["current_round"],
        "agent_index": state["current_agent_idx"],
        "speaker": agent_name,
        "model": agent["model"],
        "raw_json": result,
        "full_response": result.get("full_response", ""),
        "core_claims": result.get("core_claims", []),
        "critique_of_previous": result.get("critique_of_previous", []),
        "evidence": result.get("evidence", []),
        "tentative_consensus": result.get("tentative_consensus", []),
        "uncertainties": result.get("uncertainties", []),
        "scores": result.get("scores", {}),
    }

    return {
        "transcript": state["transcript"] + [record],
        "last_speaker": agent_name,
        "last_message_text": result.get("full_response", ""),
    }


def route_after_speaker(state: BaziDebateState) -> Literal["next_agent", "consensus"]:
    if state["current_agent_idx"] < len(state["agent_configs"]) - 1:
        return "next_agent"
    return "consensus"


def next_agent_node(state: BaziDebateState) -> Dict[str, Any]:
    return {"current_agent_idx": state["current_agent_idx"] + 1}


def consensus_node(state: BaziDebateState) -> Dict[str, Any]:
    current_round = state["current_round"]
    current_round_records = [x for x in state["transcript"] if x["round"] == current_round]

    debate_text_parts = []
    for r in current_round_records:
        debate_text_parts.append(
            f"发言者：{r['speaker']}\n"
            f"核心判断：{r.get('core_claims', [])}\n"
            f"对前一位的批评：{r.get('critique_of_previous', [])}\n"
            f"证据：{r.get('evidence', [])}\n"
            f"可共识结论：{r.get('tentative_consensus', [])}\n"
            f"不确定点：{r.get('uncertainties', [])}\n"
            f"评分：{r.get('scores', {})}\n"
            f"完整发言：{r.get('full_response', '')}\n"
        )
    debate_text = "\n".join(debate_text_parts)

    prompt = build_consensus_prompt(
        bazi_prompt=state["bazi_prompt"],
        current_round=current_round,
        prior_consensus=state["running_consensus"],
        prior_unresolved=state["unresolved_points"],
        debate_text=debate_text,
    )

    result = call_json_openrouter(
        model=state["consensus_model"],
        api_key=state["api_key"],
        messages=[
            {
                "role": "system",
                "content": "你是审慎的八字报告整合员，专门负责收敛分歧、提炼低不确定性共识。",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0,
    )

    merged_consensus = dedupe_keep_order(
        state["running_consensus"] + result.get("agreed_points", [])
    )
    merged_unresolved = dedupe_keep_order(result.get("still_unresolved", []))
    merged_focus = dedupe_keep_order(result.get("next_focus", []))

    round_summary_record = {
        "round": current_round,
        "summary": result.get("round_summary", ""),
        "agreed_points": result.get("agreed_points", []),
        "still_unresolved": result.get("still_unresolved", []),
        "next_focus": result.get("next_focus", []),
        "confidence_level": result.get("confidence_level", ""),
        "consensus_note": result.get("consensus_note", ""),
        "consensus_scores": result.get("consensus_scores", {}),
    }

    return {
        "consensus_history": state["consensus_history"] + [round_summary_record],
        "running_consensus": merged_consensus,
        "unresolved_points": merged_unresolved,
        "next_focus": merged_focus,
        "final_scores": result.get("consensus_scores", state.get("final_scores", {})),
    }


def route_after_consensus(state: BaziDebateState) -> Literal["prepare_next_round", "final_report"]:
    if state["current_round"] < state["max_rounds"]:
        return "prepare_next_round"
    return "final_report"


def prepare_next_round_node(state: BaziDebateState) -> Dict[str, Any]:
    return {
        "current_round": state["current_round"] + 1,
        "current_agent_idx": 0,
    }


def final_report_node(state: BaziDebateState) -> Dict[str, Any]:
    transcript_text = "\n".join(
        [f"第{item['round']}轮 - {item['speaker']}：\n{item['full_response']}\n" for item in state["transcript"]]
    )

    consensus_text = "\n".join(
        [
            f"第{item['round']}轮共识总结：{item['summary']}\n"
            f"本轮共识：{item['agreed_points']}\n"
            f"未解分歧：{item['still_unresolved']}\n"
            for item in state["consensus_history"]
        ]
    )

    user_prompt = build_final_report_prompt(
        bazi_prompt=state["bazi_prompt"],
        transcript_text=transcript_text,
        consensus_text=consensus_text,
        running_consensus=state["running_consensus"],
        final_scores=state["final_scores"],
        unresolved_points=state["unresolved_points"],
    )

    final_report = call_openrouter(
        model=state["final_model"],
        api_key=state["api_key"],
        messages=[
            {
                "role": "system",
                "content": "你是一位面向用户写最终报告的八字整合分析师，擅长把多派争论收敛成稳健结论。",
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=0,
    )

    return {"final_report": final_report}


def write_docx_node(state: BaziDebateState) -> Dict[str, Any]:
    build_bazi_docx_files(
        debate_output_path=state["debate_docx_path"],
        result_output_path=state["result_docx_path"],
        source_prompt=state["bazi_prompt"],
        transcript=state["transcript"],
        consensus_history=state["consensus_history"],
        final_report=state["final_report"],
        running_consensus=state["running_consensus"],
        unresolved_points=state["unresolved_points"],
        final_scores=state["final_scores"],
    )
    return {}


def build_graph():
    graph = StateGraph(BaziDebateState)

    graph.add_node("speaker", speaker_node)
    graph.add_node("next_agent", next_agent_node)
    graph.add_node("consensus", consensus_node)
    graph.add_node("prepare_next_round", prepare_next_round_node)
    graph.add_node("final_report", final_report_node)
    graph.add_node("write_docx", write_docx_node)

    graph.add_edge(START, "speaker")

    graph.add_conditional_edges(
        "speaker",
        route_after_speaker,
        {
            "next_agent": "next_agent",
            "consensus": "consensus",
        },
    )
    graph.add_edge("next_agent", "speaker")

    graph.add_conditional_edges(
        "consensus",
        route_after_consensus,
        {
            "prepare_next_round": "prepare_next_round",
            "final_report": "final_report",
        },
    )
    graph.add_edge("prepare_next_round", "speaker")
    graph.add_edge("final_report", "write_docx")
    graph.add_edge("write_docx", END)

    return graph.compile()


def run_bazi_debate(
    bazi_prompt: str,
    api_key: str,
    model_a: str = MODEL_GPT,
    model_b: str = MODEL_GEMINI,
    # model_c: str = MODEL_CLAUDE,
    model_d: str = MODEL_QWEN,
    model_e: str = MODEL_DEEPSEEK,
    consensus_model: Optional[str] = None,
    final_model: Optional[str] = None,
    max_rounds: int = DEFAULT_ROUNDS,
    debate_docx_path: str = DEFAULT_OUTPUT_DEBATE_DOCX,
    result_docx_path: str = DEFAULT_OUTPUT_RESULT_DOCX,
) -> Dict[str, Any]:
    app = build_graph()

    state: BaziDebateState = {
        "bazi_prompt": bazi_prompt,
        "api_key": api_key,
        "consensus_model": consensus_model or model_a,
        "final_model": final_model or model_a,
        "agent_configs": make_agent_configs(
            model_a=model_a,
            model_b=model_b,
            model_d=model_d,
            model_e=model_e,
        ),
        "max_rounds": max_rounds,
        "current_round": 1,
        "current_agent_idx": 0,
        "transcript": [],
        "consensus_history": [],
        "running_consensus": [],
        "unresolved_points": [],
        "next_focus": [],
        "last_speaker": "",
        "last_message_text": "",
        "final_scores": {},
        "final_report": "",
        "debate_docx_path": debate_docx_path,
        "result_docx_path": result_docx_path,
    }

    result = app.invoke(state)

    return {
        "conversation": result["transcript"],
        "consensus_history": result["consensus_history"],
        "running_consensus": result["running_consensus"],
        "unresolved_points": result["unresolved_points"],
        "final_scores": result["final_scores"],
        "summary": result["final_report"],
        "docx_debate_path": result["debate_docx_path"],
        "docx_result_path": result["result_docx_path"],
    }