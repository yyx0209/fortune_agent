import json
from config import SCORE_DIMENSIONS


def build_score_schema_example() -> dict:
    return {
        dim: {
            "score": 5,
            "reason": "一句依据"
        }
        for dim in SCORE_DIMENSIONS
    }


def get_system_prompt(style_note: str = "") -> str:
    base = """
你是一位专业的八字命理分析师，综合采用子平格局法与旺衰扶抑法进行分析。

你的分析原则：
1. 先以月令、格局、用神、相神、病药、清浊纯杂为主线，判断命局结构是否成立，以及整体层次与主要矛盾。特别注意从格的判断，如符合从格，进一步判断真从、假从，以及具体的从格类型。
2. 同时结合日主旺衰、五行强弱、寒暖燥湿、扶抑流通，校验格局判断是否稳固，并补充对喜忌、应事和现实表现的理解。
3. 分析时应兼顾“格局”与“旺衰”两套逻辑：
   - 不能只用身强身弱替代格局判断；
   - 也不能只谈格局而忽略五行力量失衡、调候失宜或流通受阻；
   - 若两套方法出现差异，需要明确指出差异点，并给出你认为更稳健的综合判断。
4. 每次发言必须：
   - 先指出上一位分析者至少2个逻辑问题、证据不足点或概念混淆点；
   - 再提出你自己的分析框架与结论；
   - 在能够达成共识时，尽量达成共识，并优先保留证据更强、争议更小的判断。
5. 结论必须具体明确，避免泛泛而谈，例如不要只说“命不错”或“注意健康”，而要尽量说明：
   - 好在什么方面、程度如何；
   - 风险主要落在哪些方面；
   - 是结构性优势、阶段性优势，还是仅在特定条件下成立；
   - 如可量化，请尽量量化。

评分要求（必须严格遵守）：
1. 每个维度必须给出 1–10 的整数评分；
2. 不允许输出区间或小数；
3. 评分表示命主在人群中的相对位置。

评分标准如下：
- 1–2分：显著低于大多数人（后10%）
- 3–4分：低于平均
- 5分：接近平均水平
- 6–7分：高于平均
- 8–9分：明显高于大多数人（前20%）
- 10分：极少数顶级水平（前5%以内）

评分策略：
1. 每个评分必须附带一句简洁的命理依据，且必须引用具体八字信息；
2. 评分应同时参考格局高低、旺衰平衡、五行流通、用忌得失，以及对应十神在现实层面的可兑现程度；
3. 请参照评分标准；
4. 若某项结论强依赖大运流年，而不是命局本身，要明确说明“命局基础分”和“运势修正方向”。
""".strip()

    if style_note:
        base += f"\n\n你的表达风格与分析侧重：{style_note}"
    return base


def build_first_speaker_prompt(bazi_prompt: str) -> str:
    schema = {
        "core_claims": ["3-6条核心判断"],
        "critique_of_previous": [],
        "evidence": ["至少3条证据，必须引用原命局信息"],
        "tentative_consensus": ["你认为其他分析者也大概率会接受的低争议结论"],
        "uncertainties": ["若有证据不足，请写出"],
        "scores": build_score_schema_example(),
        "full_response": "给用户看的完整本轮分析"
    }
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2)

    return f"""
以下是用户提供的八字分析任务与原始信息：

{bazi_prompt}

你是本场第一个发言的分析者。
重要：请严格输出合法 JSON，不要包含任何 JSON 之外的解释文字。
格式如下：
{schema_text}

要求：
1. 先做你的首轮判断；
2. 全程使用子平格局派结合旺衰派逻辑；
3. 分数必须表示“命主在普通人群中的相对位置”；
4. 尽量给低争议、可共识的结论。

你的输出必须满足：
1. 只输出 JSON
2. 第一字符必须是左花括号
3. 最后一字符必须是右花括号
4. 不允许出现 ``` 或 markdown
""".strip()


def build_next_speaker_prompt(
    bazi_prompt: str,
    prior_consensus: str,
    latest_consensus_summary: str,
    current_round_summary: str,
    unresolved: str,
    next_focus: str,
    last_speaker: str,
    last_message_text: str,
) -> str:
    schema = {
        "core_claims": ["3-6条核心判断"],
        "critique_of_previous": ["至少2条具体逻辑问题"],
        "evidence": ["至少3条证据，必须引用原命局信息"],
        "tentative_consensus": ["你认为可达成共识的低争议结论"],
        "uncertainties": ["若有证据不足，请写出"],
        "scores": build_score_schema_example(),
        "full_response": "给用户看的完整本轮分析"
    }
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2)

    return f"""
以下是用户提供的八字分析任务与原始信息：

{bazi_prompt}

当前已形成的稳定共识：
{prior_consensus}

上一轮共识摘要：
{latest_consensus_summary}

本轮截至目前的累计摘要：
{current_round_summary}

当前未解决分歧：
{unresolved}

本轮建议优先讨论焦点：
{next_focus}

上一位分析者（{last_speaker}）刚刚的发言如下：
{last_message_text}

重要：请严格输出合法 JSON，不要包含任何 JSON 之外的解释文字。
格式如下：
{schema_text}

要求：
1. 必须先批评，再陈述自己的观点；
2. 批评要具体，不能只说“对方不严谨”；
3. 若你同意对方某部分，请明确写出；
4. 仍以子平格局派结合旺衰派为方法；
5. 你既要回应上一位分析者，也要参考“本轮截至目前的累计摘要”，避免误读更早发言；
6. 如果上一位分析者对更早发言者有误解，你应明确指出；
7. 尽量往共识收敛，而不是无谓制造新分歧。

你的输出必须满足：
1. 只输出 JSON
2. 第一字符必须是左花括号
3. 最后一字符必须是右花括号
4. 不允许出现 ``` 或 markdown
""".strip()


def build_consensus_prompt(
    bazi_prompt: str,
    current_round: int,
    prior_consensus: list[str],
    prior_unresolved: list[str],
    debate_text: str,
) -> str:
    schema = {
        "round_summary": "本轮总结",
        "agreed_points": ["本轮新增或强化的共识，尽量具体"],
        "still_unresolved": ["仍未解决的关键分歧，最多3条"],
        "next_focus": ["下一轮最值得继续讨论的问题，最多3条"],
        "confidence_level": "低/中/高",
        "consensus_scores": build_score_schema_example(),
        "consensus_note": "说明为什么这些点适合作为对用户输出的稳健结论"
    }
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2)

    return f"""
你现在是“共识整合员”，目标不是继续争论，而是降低不确定性，尽量形成稳健结论。

用户原始八字任务：
{bazi_prompt}

上一阶段累计共识：
{json.dumps(prior_consensus, ensure_ascii=False)}

上一阶段未解决分歧：
{json.dumps(prior_unresolved, ensure_ascii=False)}

以下是第 {current_round} 轮的全部发言：
{debate_text}

重要：请严格输出合法 JSON，不要包含任何 JSON 之外的解释文字。
格式如下：
{schema_text}

要求：
1. 优先保留双方都能接受、证据较强的结论；
2. 每个分项都给出共识分数；
3. 如双方分数不同，请取更稳健的中间值，而不是极端值；
4. 只有当证据强、跨模型重复出现且争议较小，才把结论纳入 agreed_points；
5. 若某个点只是本轮新提出但证据仍弱，应放入 still_unresolved，而不是过早升级为长期共识；
6. 最终目标是为用户生成低不确定性的报告。

你的输出必须满足：
1. 只输出 JSON
2. 第一字符必须是左花括号
3. 最后一字符必须是右花括号
4. 不允许出现 ``` 或 markdown
""".strip()


def build_final_report_prompt(
    bazi_prompt: str,
    transcript_text: str,
    consensus_text: str,
    running_consensus: list[str],
    final_scores: dict,
    unresolved_points: list[str],
) -> str:
    return f"""
以下是用户的八字原始信息与问题：
{bazi_prompt}

以下是完整多轮讨论过程：
{transcript_text}

以下是每轮共识整合结果：
{consensus_text}

累计形成的最终共识：
{json.dumps(running_consensus, ensure_ascii=False)}

最终共识评分：
{json.dumps(final_scores, ensure_ascii=False)}

剩余未解分歧：
{json.dumps(unresolved_points, ensure_ascii=False)}

请写一份“面向用户的最终八字报告”，要求：
1. 使用子平格局派结合旺衰派框架；注意从格判断是否成立，并结合旺衰、五行流通、用忌得失进行校验和补充；
2. 尽量基于共识输出，只在必要处简短提示仍存在的小分歧；
3. 报告中必须包含“命主人群位置评分表（满分10分）”；
4. 评分表必须包含：
   - 原生家庭/父母支持
   - 学业能力
   - 事业发展
   - 财运
   - 婚恋/亲密关系
   - 子女
   - 健康稳定性
   - 贵人运
   - 综合人生顺遂度
5. 每个分数后都要有一句解释；
6. 风格：专业、具体、明确；
7. 最后一段附上“仅供研究或娱乐参考”。

请直接输出最终报告正文，不要 JSON。
""".strip()