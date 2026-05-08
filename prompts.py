"""
v2 prompts。流程：
  Round 1（多模型）：定格局 + 用神候选（不可自算大运/流年）
  Round 1 Merge   ：整合候选清单（不再辩论）
  Round 2         ：基于 tool 的大运/流年表做解读 + 前事对照
  Reconcile       ：仅处理单条冲突的短 prompt
  Final           ：写最终报告
"""

import json
from typing import List, Dict, Any


# ===================== Round 1：格局 + 用神候选 =====================

ROUND1_SYSTEM = """
你是一位严谨的八字分析师，使用子平格局派结合旺衰扶抑派分析命局。

本环节仅做"命局结构 + 用神方向"判断；大运/流年解读不在本轮。

要求：
1. 先辨月令、格局、用神、相神，再用旺衰、调候、流通校验；
2. 特别注意从格的判断，如是从格，需分辨真从、假从、从格具体类型等；
3. 若格局或用神有歧义，必须列出 2~3 个候选假设，禁止强行二选一；
4. 每个用神候选必须给出推理依据与置信度（low/mid/high）；
5. 严禁自行推算或引用任何大运、流年干支；
6. 用户提供的"前事"在本轮仅作弱先验，可参考但不要硬套，更不可据此倒推用神。
""".strip()


def build_round1_prompt(
    natal_chart: Dict[str, Any],
    events: List[Dict[str, Any]],
    style_hint: str = "",
) -> str:
    schema = {
        "pattern": "主张的格局",
        "pattern_alternatives": ["若有歧义，列1-2个候选格局"],
        "use_gods_hypotheses": [
            {
                "id": "H1",
                "use_god": "如：丙火",
                "auxiliary": "如：甲木为相",
                "rationale": "为什么这样取（必须引用具体干支/位置）",
                "confidence": "low|mid|high",
            }
        ],
        "main_contradictions": ["命局主要矛盾点"],
        "evidence": ["至少3条证据，必须引用具体干支/十神/位置"],
        "uncertainties": ["仍需补充信息或大运流年验证才能定论的点"],
        "full_response": "面向用户的本轮分析正文（不可包含大运/流年）",
    }
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2)

    return f"""
【排盘信息（确定性，由 tool 给出，仅四柱）】
{json.dumps(natal_chart, ensure_ascii=False, indent=2)}

【用户已发生之事（弱先验，本轮仅参考）】
{json.dumps(events, ensure_ascii=False, indent=2)}

【风格提示】
{style_hint or "（无）"}

请严格输出 JSON：
{schema_text}

只输出 JSON，第一字符是 '{{'，不要 markdown，不要解释文字。
""".strip()


# ===================== Round 1 Merge：整合候选 =====================

ROUND1_MERGE_SYSTEM = """
你是命局结论整合员，负责把多位分析者的格局/用神判断整合为一份候选清单。
不要继续辩论。多人指向同一用神则提高置信度；分歧则保留为候选。
""".strip()


def build_round1_merge_prompt(
    natal_chart: Dict[str, Any],
    events: List[Dict[str, Any]],
    round1_outputs: List[Dict[str, Any]],
) -> str:
    schema = {
        "pattern": "整合后的格局结论（含简短依据）",
        "pattern_confidence": "low|mid|high",
        "use_gods_candidates": [
            {
                "id": "H1",
                "use_god": "...",
                "auxiliary": "...",
                "rationale": "为何保留",
                "confidence": "low|mid|high",
                "supported_by": ["A", "B"],
            }
        ],
        "primary_hypothesis_id": "H1",
        "key_disputes": ["仍存在的关键分歧（最多3条）"],
        "open_questions_for_round2": ["希望第二轮通过大运/流年/前事去验证的问题"],
    }
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2)

    return f"""
【排盘（仅四柱）】
{json.dumps(natal_chart, ensure_ascii=False, indent=2)}

【已发生之事】
{json.dumps(events, ensure_ascii=False, indent=2)}

【各分析者的本轮输出】
{json.dumps(round1_outputs, ensure_ascii=False, indent=2)}

请严格输出 JSON：
{schema_text}

只输出 JSON，第一字符是 '{{'。
""".strip()


# ===================== Round 2：大运/流年解读 + 前事对照 =====================

ROUND2_SYSTEM = """
你是八字大运/流年解读员，必须严格遵守：

1. 大运、流年的干支以输入中的 dayun_table / liunian_table 为准；
   严禁自行推算、改写、补全任何干支；表里没有的年份不要谈。
2. 必须把每条用户"前事"对应到具体公历年份与干支，并判断与当前用神候选是否一致；
3. 若发现"前事 ↔ 用神 ↔ 流年解释"不一致，必须如实写入 conflicts，禁止粉饰；
4. 当存在多个用神候选时，优先用 primary_hypothesis 解释；同时在
   past_event_alignment 中标注哪个候选对该前事更吻合。
5. 评分必须按"普通人群百分位"严格映射，不可使用"保守中间分"敷衍。

百分位评分硬规则（必须执行）：
- 1分: P0-5
- 2分: P6-15
- 3分: P16-30
- 4分: P31-45
- 5分: P46-55
- 6分: P56-70
- 7分: P71-82
- 8分: P83-91
- 9分: P92-97
- 10分: P98-100

反集中化规则（必须执行）：
- 事业、财运、婚恋、健康、学业、贵人、子女、综合 8项中：
  1) 不允许超过 3 项使用同一分数；
  2) 5分+6分合计最多 4 项；
  3) 若证据不足，可标 low_confidence，但仍要给分并解释不确定来源。
""".strip()


def build_round2_prompt(
    chart: Dict[str, Any],
    events: List[Dict[str, Any]],
    round1_consensus: Dict[str, Any],
    dayun_table: List[Dict[str, Any]],
    liunian_table: List[Dict[str, Any]],
) -> str:
    schema = {
        "dayun_summaries": [
            {
                "index": 1,
                "ganzhi": "...",
                "year_range": "1995-2004",
                "trend": "...",
                "aspects": {
                    "事业": "...",
                    "财运": "...",
                    "婚恋": "...",
                    "健康": "...",
                    "学业": "...",
                    "贵人": "...",
                    "子女": "...",
                    "综合": "...",
                },
            }
        ],
        "key_year_interpretations": [
            {
                "year": 2020,
                "ganzhi": "...",
                "in_dayun_ganzhi": "...",
                "interpretation": "...",
                "salience": "high|mid|low",
            }
        ],
        "past_event_alignment": [
            {
                "event": "原文",
                "year": 2020,
                "year_ganzhi": "庚子",
                "in_dayun_ganzhi": "...",
                "best_fit_hypothesis_id": "H1",
                "consistency": "ok|conflict|insufficient_info",
                "explanation": "为何一致或冲突",
            }
        ],
        "conflicts": [
            {
                "summary": "一句话描述矛盾",
                "involved_event_index": 0,
                "current_primary_hypothesis_id": "H1",
                "competing_hypothesis_id": "H2 或 null",
                "needed_info": "如：该年具体月份/影响领域",
            }
        ],
        "future_focus": ["未来 5-10 年值得关注的大运/流年要点"],
        "scores": {
            "事业": {"score": 7, "percentile_range": "P71-82", "reason": "...", "confidence": "high|mid|low"},
            "财运": {"score": 4, "percentile_range": "P31-45", "reason": "...", "confidence": "high|mid|low"},
            "婚恋": {"score": 6, "percentile_range": "P56-70", "reason": "...", "confidence": "high|mid|low"},
            "健康": {"score": 5, "percentile_range": "P46-55", "reason": "...", "confidence": "high|mid|low"},
            "学业": {"score": 8, "percentile_range": "P83-91", "reason": "...", "confidence": "high|mid|low"},
            "贵人": {"score": 6, "percentile_range": "P56-70", "reason": "...", "confidence": "high|mid|low"},
            "子女": {"score": 5, "percentile_range": "P46-55", "reason": "...", "confidence": "high|mid|low"},
            "综合": {"score": 6, "percentile_range": "P56-70", "reason": "...", "confidence": "high|mid|low"},
        },
        "score_distribution_check": {
            "unique_scores_count": 0,
            "count_score_5_or_6": 0,
            "self_check_note": "自检是否满足反集中化规则"
        },
    }
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2)

    return f"""
【排盘（含四柱、起运）】
{json.dumps(chart, ensure_ascii=False, indent=2)}

【第一轮共识：格局 + 用神候选】
{json.dumps(round1_consensus, ensure_ascii=False, indent=2)}

【大运表（tool 给出，禁止修改）】
{json.dumps(dayun_table, ensure_ascii=False, indent=2)}

【相关流年表（tool 给出，禁止修改；表外年份不要谈）】
{json.dumps(liunian_table, ensure_ascii=False, indent=2)}

【用户已发生之事】
{json.dumps(events, ensure_ascii=False, indent=2)}

输出深度要求（必须满足）：
1. dayun_summaries 至少覆盖 4 个关键阶段（若数据不足则覆盖全部可用阶段）；
2. 每个阶段的 aspects 必须包含 8 个维度：事业/财运/婚恋/健康/学业/贵人/子女/综合；
3. key_year_interpretations 至少给出 6 个年份；
4. scores 必须包含上述 8 维度，且每项都要给 score + percentile_range + reason + confidence；
5. 必须填写 score_distribution_check，保证分数不集中在 5/6。

请严格输出 JSON：
{schema_text}

只输出 JSON，第一字符是 '{{'。
""".strip()


# ===================== Reconcile：单冲突短 prompt =====================

RECONCILE_SYSTEM = """
你是矛盾仲裁员。本次任务仅处理一个具体冲突，不要重写整篇报告，不要引入未提供的事实。

你只能在以下 4 种结论中选 1 个：
- update_use_gods             第一轮用神候选需要修正/重排（仅当前事强证据指向另一候选时）
- patch_year_interpretation   第一轮用神保留，仅修订第二轮对该年的解读
- needs_user_clarification    信息不足，列出向用户补问的问题
- accept_as_low_confidence    双方都讲得通且信息有限，按低置信度保留并说明
""".strip()


def build_reconcile_prompt(
    chart: Dict[str, Any],
    events: List[Dict[str, Any]],
    round1_consensus: Dict[str, Any],
    round2_result: Dict[str, Any],
    conflict: Dict[str, Any],
) -> str:
    idx = conflict.get("involved_event_index", -1)
    related_event = events[idx] if isinstance(idx, int) and 0 <= idx < len(events) else None
    related_align = [
        x for x in round2_result.get("past_event_alignment", []) or []
        if related_event and x.get("event") == related_event.get("event")
    ]

    schema = {
        "resolution": "update_use_gods|patch_year_interpretation|needs_user_clarification|accept_as_low_confidence",
        "rationale": "一段话说明为何选这个结论",
        "updated_use_gods_candidates": [
            {"id": "H1", "use_god": "...", "auxiliary": "...",
             "rationale": "...", "confidence": "low|mid|high"}
        ],
        "new_primary_hypothesis_id": "可选：若改用神请给出",
        "year_interpretation_patch": {"year": 0, "new_interpretation": ""},
        "questions_to_user": ["若信息不足，列出"],
        "low_confidence_note": "若双方都讲得通，写一段限定说明",
    }
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2)

    return f"""
【冲突摘要（仅处理这一个）】
{json.dumps(conflict, ensure_ascii=False, indent=2)}

【涉事原文】
{json.dumps(related_event, ensure_ascii=False, indent=2)}

【该事件已对齐的流年/大运（来自第二轮）】
{json.dumps(related_align, ensure_ascii=False, indent=2)}

【四柱】
{json.dumps(chart["natal"], ensure_ascii=False, indent=2)}

【当前用神候选】
primary={round1_consensus.get("primary_hypothesis_id")}
candidates={json.dumps(round1_consensus.get("use_gods_candidates", []), ensure_ascii=False, indent=2)}

请严格输出 JSON：
{schema_text}

只输出 JSON，第一字符是 '{{'。
""".strip()


# ===================== Final report =====================

FINAL_SYSTEM = """
你是一位面向用户写最终报告的八字整合分析师，擅长把多派与多步骤结论收敛为稳健叙事。
""".strip()


def build_final_prompt(
    chart: Dict[str, Any],
    events: List[Dict[str, Any]],
    round1_consensus: Dict[str, Any],
    round2_result: Dict[str, Any],
    reconcile_log: List[Dict[str, Any]],
    focus_questions: List[str] | None = None,
) -> str:
    focus_questions = [q for q in (focus_questions or []) if isinstance(q, str) and q.strip()][:3]
    return f"""
【排盘】
{json.dumps(chart, ensure_ascii=False, indent=2)}

【用户前事】
{json.dumps(events, ensure_ascii=False, indent=2)}

【第一轮（格局+用神）共识】
{json.dumps(round1_consensus, ensure_ascii=False, indent=2)}

【第二轮（大运+流年+前事对照）结果】
{json.dumps(round2_result, ensure_ascii=False, indent=2)}

【矛盾仲裁记录（如有）】
{json.dumps(reconcile_log, ensure_ascii=False, indent=2)}

【用户最关心的问题（至多3条，可能为空）】
{json.dumps(focus_questions, ensure_ascii=False, indent=2)}

请写一份"面向用户的最终八字报告"，要求：
1. 先交代命局结构与最终选定用神（说明是否经过前事修正）；
2. 大运分段评述要详细，不少于 4 个阶段；每阶段都要按 8 维度写：事业、财运、婚恋、健康、学业、贵人、子女、综合；
3. 重点流年评述不少于 6 个年份（优先覆盖前事年份与未来关键年份）；
4. 三条前事对照表（事 / 年 / 干支 / 一致性 / 说明）；
5. 命主人群位置评分与定位必须含 8 维度（事业、财运、婚恋、健康、学业、贵人、子女、综合），并使用二级标题逐项展开；每个维度都必须包含以下 7 项：
   - 分数（1-10）
   - 对应百分位区间（严格使用以下映射）
   - 人群定位（1-2 句，说明在普通人群中的大致层级）
   - 核心证据（至少 2 条，分别尽量来自：命局结构 + 大运/流年）
   - 优势与短板（各至少 1 条，不可只写优势）
   - 风险触发点（1-2 条，写清在什么阶段/条件下容易下滑）
   - 提升建议（2-3 条，要求具体可执行，避免空话）
   同时每个维度正文总长度不少于 120 字，不得只写成表格短句。
6. 严格百分位映射：
   - 1分=P0-5，2分=P6-15，3分=P16-30，4分=P31-45，5分=P46-55，
     6分=P56-70，7分=P71-82，8分=P83-91，9分=P92-97，10分=P98-100；
7. 分数分布去中心化：不允许大量堆在 5/6；
8. 在 8 维评分之后，单独给出"总体人生定位总结"（不少于 200 字），需说明：
   - 命主最可能的长期发展轨迹；
   - 最值得押注的 1-2 条主线；
   - 需要规避的 1-2 个系统性风险。
9. 新增一个二级标题板块："重点问题解答"。规则：
   - 若上方提供了用户问题，则按原问题逐条回答（Q1/Q2/Q3），不得遗漏；
   - 每个问题至少回答 120 字，且必须给出"时间窗口/触发条件/行动建议"三部分；
   - 回答必须引用前文命局或大运流年的判断，不能与前文矛盾。
   - 若未提供问题，则写"未提供重点问题，本节略"并给出 2 条可供用户补充的问题示例。
10. 最后给出未来 15 年阶段提醒；
11. 末尾附"仅供研究或娱乐参考"。

直接输出报告正文（可使用 Markdown 标题），不要 JSON。
""".strip()
