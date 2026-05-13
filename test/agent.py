import os
import json
import requests
from typing import Dict, Any, List
from dotenv import load_dotenv
load_dotenv()




def call_openrouter(model: str, api_key: str, messages: List[Dict[str, str]], timeout: int = 120) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # 可选，但 OpenRouter 官方建议带上
        "HTTP-Referer": "https://localhost",
        "X-Title": "ziwei-debate",
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
    }

    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected OpenRouter response: {json.dumps(data, ensure_ascii=False)[:1000]}") from e


def debate_ziwei(
    prompt: str,
    model_a: str,
    model_b: str,
    api_key: str,
    rounds: int = 5,
) -> Dict[str, Any]:
    """
    两个模型轮流辩论，每轮：
    1) 指出对方逻辑问题
    2) 提出自己的看法
    最后输出总结
    """
    conversation_history: List[Dict[str, Any]] = []

    system_a = (
        "你是一位严谨的八字命理分析师。"
        "每次发言都必须先指出对方上一轮分析中的具体逻辑问题，再给出你自己的判断。"
        "不要空泛评价，必须引用命盘中的具体宫位、主星、辅星、四化或限运信息。"
    )

    system_b = (
        "你是一位擅长辩证分析的八字命理分析师。"
        "每次发言都必须先指出对方上一轮分析中的具体逻辑漏洞或证据不足之处，再提出你自己的完整看法。"
        "不要重复对方原话，必须基于命盘细节展开。"
    )

    last_response = None
    current_model = model_a
    current_name = "Agent A"

    for round_num in range(1, rounds + 1):
        if round_num == 1:
            user_prompt = f"""
以下是八字与分析任务。

命盘与任务：
{prompt}

请先给出你的首轮分析。要求：
1. 先提出你的核心结论
2. 给出依据
3. 明确你最看重的3个命盘信号
"""
        else:
            user_prompt = f"""
以下是八字与分析任务：
{prompt}

对方上一轮的观点如下：
{last_response}

请你完成本轮发言，要求：
1. 明确指出对方至少2个逻辑问题或证据不足之处
2. 提出你自己的判断
3. 必须引用命盘具体信息
4. 结构清晰，避免空话
"""

        messages = [
            {
                "role": "system",
                "content": system_a if current_name == "Agent A" else system_b,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ]

        response = call_openrouter(
            model=current_model,
            api_key=api_key,
            messages=messages,
        )

        conversation_history.append(
            {
                "round": round_num,
                "speaker": current_name,
                "model": current_model,
                "response": response,
            }
        )

        last_response = response

        # 切换说话人
        if current_name == "Agent A":
            current_name = "Agent B"
            current_model = model_b
        else:
            current_name = "Agent A"
            current_model = model_a

    summary_prompt = "基于以下辩论记录，输出一份最终综合报告。\n\n"
    for record in conversation_history:
        summary_prompt += (
            f"第 {record['round']} 轮 - {record['speaker']} ({record['model']}):\n"
            f"{record['response']}\n\n"
        )

    summary_prompt += """
请输出最终报告，结构如下：
1. 双方共识
2. 主要分歧
3. 哪一方论证更严谨，为什么
4. 对命主的综合判断（健康、学业、事业、财运、感情、人际）
5. 关键时间段与注意事项
6. 建议
7. 免责声明：仅供研究或娱乐
"""

    summary = call_openrouter(
        model=model_a,  # 也可以单独指定一个 summary model
        api_key=api_key,
        messages=[
            {
                "role": "system",
                "content": "你是中立的总结者，擅长整合多方辩论并输出结构化报告。",
            },
            {
                "role": "user",
                "content": summary_prompt,
            },
        ],
    )

    return {
        "conversation": conversation_history,
        "summary": summary,
    }


if __name__ == "__main__":

    input = "丙子，甲午，癸未，己卯"
    
    bazi_prompt = f"""
    请分析以下八字：

        要求：结构清晰、逻辑驱动、避免玄学化表达。

        八字：
        {input}
    """

    model_a = "openai/gpt-4o"
    model_b = "anthropic/claude-opus-4.6"

    # api_key = os.getenv("OPENROUTER_API_KEY")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("请先设置 .env 文件中的 OPENROUTER_API_KEY")

    result = debate_ziwei(
        prompt=bazi_prompt,
        model_a=model_a,
        model_b=model_b,
        api_key=api_key,
        rounds=5,
    )

    print("=== 辩论记录 ===")
    for record in result["conversation"]:
        print(f"Round {record['round']} - {record['speaker']} ({record['model']}):\n{record['response']}\n")

    print("=== 总结报告 ===")
    print(result["summary"])