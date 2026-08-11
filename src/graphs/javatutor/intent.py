"""LLM 意图分类器，替代关键词匹配。"""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from graphs.javatutor.prompts import SYSTEM_PROMPT_INTENT

VALID_INTENTS = {"data_query", "concept", "debug", "animate_guide", "other"}
CONFIDENCE_THRESHOLD = 0.6


def _resolve_model(model):
    """优先用传入的 model，否则从 LangGraph configurable 中取 chat_model。"""
    if model is not None:
        return model
    try:
        from langgraph.config import get_config

        return get_config().get("configurable", {}).get("chat_model")
    except Exception:
        return None


def _parse_output(raw: str) -> dict[str, Any] | None:
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
    if not isinstance(data, dict):
        return None
    intent = data.get("intent")
    if intent not in VALID_INTENTS:
        return None
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return {"intent": intent, "confidence": confidence, "reason": str(data.get("reason", ""))}


def classify_intent(question: str, model=None) -> dict[str, Any]:
    messages = [
        SystemMessage(content=SYSTEM_PROMPT_INTENT),
        HumanMessage(content=question),
    ]
    resolved = _resolve_model(model)
    if resolved is not None:
        response = resolved.invoke(messages)
        raw = response.content
    else:
        from graphs.javatutor.llm import llm_complete

        raw = llm_complete(
            messages=messages,
            temperature=0.1,
            max_completion_tokens=200,
        )
    parsed = _parse_output(raw)
    if parsed is None:
        return {"intent": "other", "confidence": 0.0, "reason": "分类输出非法"}
    if parsed["confidence"] < CONFIDENCE_THRESHOLD:
        return {"intent": "other", "confidence": parsed["confidence"], "reason": "低置信度"}
    return parsed
