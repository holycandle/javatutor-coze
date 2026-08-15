"""LLM-as-Judge：按 judge_prompt.md 对端到端回答评分。

默认使用独立的 DeepSeek 端点（环境变量 JUDGE_API_URL / JUDGE_API_KEY / JUDGE_MODEL），
不经过 Coze integration 端点；密钥只在环境变量或本地 .env 中提供，不写入代码。
"""

import json
import os
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

JUDGE_PROMPT = Path(__file__).resolve().parents[1] / "judge_prompt.md"


def load_judge_prompt() -> str:
    return JUDGE_PROMPT.read_text(encoding="utf-8")


def build_judge_messages(sample: dict, answer: str) -> list:
    facts = "\n".join(sample.get("expected_facts", []))
    return [
        SystemMessage(content=load_judge_prompt()),
        HumanMessage(content=f"考题：\n{sample.get('payload', {})}\n\n期望事实：\n{facts}\n\nAgent 回答：\n{answer}"),
    ]


def parse_judge_output(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "score" not in data:
        return None
    return data


def _messages_to_openai(messages) -> list[dict[str, str]]:
    role_map = {"system": "system", "human": "user", "ai": "assistant"}
    result = []
    for msg in messages:
        role = role_map.get(msg.type, "user")
        content = msg.content
        if isinstance(content, list):
            texts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            content = "\n".join(texts)
        result.append({"role": role, "content": str(content)})
    return result


def judge_complete(messages) -> str:
    """调用 DeepSeek 兼容 chat completions 接口返回完整文本。"""
    import httpx

    api_url = os.getenv("JUDGE_API_URL", "https://api.deepseek.com").rstrip("/")
    api_key = os.getenv("JUDGE_API_KEY", "")
    model = os.getenv("JUDGE_MODEL", "deepseek-chat")
    if not api_key:
        raise RuntimeError("JUDGE_API_KEY 未配置，请在本地 .env 中填写 DeepSeek Key")
    payload = {
        "model": model,
        "messages": _messages_to_openai(messages),
        "temperature": 0.1,
        "max_tokens": 500,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    resp = httpx.post(f"{api_url}/chat/completions", json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def judge_answer(sample: dict, answer: str, model=None) -> dict[str, Any]:
    try:
        if model is not None:
            raw = model.invoke(build_judge_messages(sample, answer)).content
        else:
            raw = judge_complete(build_judge_messages(sample, answer))
        parsed = parse_judge_output(raw)
        if parsed is None:
            return {"id": sample.get("id"), "judge_parse_error": True}
        return {"id": sample.get("id"), **parsed}
    except Exception as exc:
        return {"id": sample.get("id"), "judge_parse_error": True, "error": str(exc)}
