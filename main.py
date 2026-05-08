"""
v2 入口示例。运行：
    python -m v2.main

依赖：
    pip install -r requirements.txt
"""

import os

import dotenv

from workflow import run_fortune

dotenv.load_dotenv()


def main():
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("请先设置 OPENROUTER_API_KEY 环境变量")

    # 公历出生时刻 + 性别（用于 tool 排盘，不要直接给八字）
    birth = {"year": 1999, "month": 2, "day": 9, "hour": 10, "minute": 30}
    gender = "女"

    # 用户的三条已发生之事；尽量带年份
    events = [
        {"event": "考上理想大学", "year": 2017, "feeling": "吉"},
        {"event": "职场中接触到新的项目，工作内容发生变化", "year": 2025, "feeling": "动"},
        {"event": "学业面对很大挑战，贵人运薄弱", "year": 2020, "feeling": "凶"},
    ]

    result = run_fortune(
        birth=birth,
        gender=gender,
        events=events,
        api_key=api_key,
    )

    print("\n=== 输出目录 ===")
    print(result["output_dir"])
    print("\n=== 最终报告（节选） ===")
    print(result["final_report"][:1500])


if __name__ == "__main__":
    main()
