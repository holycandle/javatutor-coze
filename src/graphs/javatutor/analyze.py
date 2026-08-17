"""analyze_code 确定性前置节点。"""

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from graphs.javatutor.prompts import SYSTEM_PROMPT_ANALYZE

_FALLBACK_ANALYSIS = {
    "complexity": {"time": "未知", "timeExplanation": "分析服务暂不可用", "space": "未知", "spaceExplanation": "分析服务暂不可用"},
    "algorithms": [],
    "dataStructures": [],
}


def _parse_analysis(raw: str) -> dict | None:
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
    return data if isinstance(data, dict) else None


def _resolve_model(model):
    """优先用传入的 model，否则从 LangGraph configurable 中取 chat_model."""
    if model is not None:
        return model
    try:
        from langgraph.config import get_config

        return get_config().get("configurable", {}).get("chat_model")
    except Exception:
        return None


def _invoke(messages, model):
    resolved = _resolve_model(model)
    if resolved is not None:
        return resolved.invoke(messages)
    from graphs.javatutor.llm import llm_complete

    raw = llm_complete(messages, temperature=0.1, max_completion_tokens=2000)
    return AIMessage(content=raw)


def analyze_code_node(state, model=None) -> dict[str, Any]:
    source_code = state.get("source_code", "")
    if not source_code:
        return {"analysis_result": None}
    messages = [
        SystemMessage(content=SYSTEM_PROMPT_ANALYZE),
        HumanMessage(content=f"源代码:\n```java\n{source_code}\n```"),
    ]
    parsed = None
    try:
        raw = _invoke(messages, model).content
        parsed = _parse_analysis(raw)
    except Exception:
        parsed = None
    result = parsed or _FALLBACK_ANALYSIS
    if state.get("intent") == "analyze":
        return {"analysis_result": result, "messages": [AIMessage(content=json.dumps(result, ensure_ascii=False))]}
    return {"analysis_result": result}
