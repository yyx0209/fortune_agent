MODEL_GPT = "openai/gpt-5.5"
MODEL_GEMINI = "google/gemini-2.5-pro"
MODEL_CLAUDE_OPUS = "anthropic/claude-opus-4.7"
MODEL_QWEN = "qwen/qwen3-235b-a22b-2507"
MODEL_DEEPSEEK = "deepseek/deepseek-v4-pro"

DEFAULT_CONSENSUS_MODEL = MODEL_GPT
DEFAULT_FINAL_MODEL = MODEL_CLAUDE_OPUS
DEFAULT_ROUNDS = 2
DEFAULT_OUTPUT_DEBATE_DOCX = "results/bazi_debate.docx"
DEFAULT_OUTPUT_RESULT_DOCX = "results/bazi_result.docx"


SCORE_DIMENSIONS = [
    "原生家庭/父母支持",
    "学业能力",
    "事业发展",
    "财运",
    "婚恋/亲密关系",
    "子女",
    "健康稳定性",
    "贵人运",
    "综合人生顺遂度",
]