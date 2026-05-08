import os

import dotenv

from workflow import run_bazi_debate

dotenv.load_dotenv()


def main():
    bazi_prompt = """
请分析以下八字，并重点关注：命局结构、原声家庭、性格、事业、财运、感情、子女、健康、贵人运，以及未来阶段性提醒。
请尽量给出稳健结论，不要夸张断语。

基本信息：
- 性别：女
- 四柱：己卯 丙寅 壬辰 乙巳
"""

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("请先设置 OPENROUTER_API_KEY 环境变量")

    result = run_bazi_debate(
        bazi_prompt=bazi_prompt,
        api_key=api_key,
    )

    # print("文档已输出到：", result["docx_debate_path"], result["docx_result_path"])
    # print("最终共识：", result["running_consensus"])
    # print("最终评分：", result["final_scores"])
    # print("最终报告：\n", result["summary"])


if __name__ == "__main__":
    main()
