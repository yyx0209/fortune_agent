import requests
from typing import Dict, Any


def test_openrouter_model(
    model: str,
    query: str,
    api_key: str,
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Test whether an OpenRouter model can return a valid response.

    Args:
        model (str): model name, e.g. "openai/gpt-4o"
        query (str): input prompt
        api_key (str): OpenRouter API key
        timeout (int): request timeout (seconds)

    Returns:
        dict:
            {
                "success": bool,
                "response": str or None,
                "error": str or None,
                "latency": float
            }
    """
    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # optional but recommended
        "HTTP-Referer": "https://your-app.com",
        "X-Title": "model-test"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": query}
        ]
    }

    try:
        import time
        start = time.time()

        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        latency = time.time() - start

        # HTTP层错误
        if response.status_code != 200:
            return {
                "success": False,
                "response": None,
                "error": f"HTTP {response.status_code}: {response.text}",
                "latency": latency,
            }

        data = response.json()

        # 解析模型输出
        content = data["choices"][0]["message"]["content"]

        # 基础有效性校验（防空返回）
        if not content or not content.strip():
            return {
                "success": False,
                "response": None,
                "error": "Empty response from model",
                "latency": latency,
            }

        return {
            "success": True,
            "response": content,
            "error": None,
            "latency": latency,
        }

    except Exception as e:
        return {
            "success": False,
            "response": None,
            "error": str(e),
            "latency": None,
        }
    

if __name__ == "__main__":
    API_KEY = "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"

    result = test_openrouter_model(
        model="claude-opus-4.6",
        query="Explain ROI vs spend trade-off briefly.",
        api_key=API_KEY
    )

    print(result['response'])

# openai/gpt-4o
# google/gemini-2.5-pro
# anthropic/claude-opus-4.6
# qwen/qwen-2.5-72b-instruct
# qwen/qwen3-max-thinking
# deepseek/deepseek-v3.2