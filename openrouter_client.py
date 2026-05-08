import requests
from typing import List, Dict, Any
import json

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

def call_openrouter(
    model: str,
    api_key: str,
    messages: List[Dict[str, str]],
    timeout: int = 180,
    temperature: float = 0.6,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://localhost",
        "X-Title": "bazi-consensus-debate",
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    resp = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(
            f"Unexpected OpenRouter response: {json.dumps(data, ensure_ascii=False)[:1000]}"
        ) from e


def call_json_openrouter(
    model: str,
    api_key: str,
    messages: List[Dict[str, str]],
    timeout: int = 180,
    temperature: float = 0.5,
) -> Dict[str, Any]:
    """
    要求模型输出 JSON；失败时做一次简单提取。
    """
    raw = call_openrouter(
        model=model,
        api_key=api_key,
        messages=messages,
        timeout=timeout,
        temperature=temperature,
    )

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 尝试截取最外层 JSON
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Model did not return valid JSON:\n{raw[:1200]}")