"""评审与修订节点。"""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from graphs.javatutor.prompts import SYSTEM_PROMPT_CRITIC, SYSTEM_PROMPT_REVISE


def _resolve_model(model):
    """优先用传入的 model，否则从 LangGraph configurable 中取 chat_model。

    使用 langgraph.config.get_config（非 langchain_core.runnables.get_runnable_config）。
    """
    if model is not None:
        return model
    try:
        from langgraph.config import get_config

        return get_config().get("configurable", {}).get("chat_model")
    except Exception:
        return None


def _invoke(messages, model):
    """调用 LLM，优先用注入的 model（测试），否则用原始 HTTP 调用。"""
    resolved = _resolve_model(model)
    if resolved is not None:
        return resolved.invoke(messages)
    from graphs.javatutor.llm import llm_complete

    raw = llm_complete(
        messages=messages,
        temperature=0.1,
        max_completion_tokens=800,
    )
    from langchain_core.messages import AIMessage

    return AIMessage(content=raw)


def _parse_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _as_bool(value) -> bool:
    """兼容布尔值与字符串：'true'/'false' 均按文本解析，避免 bool('false') 误判为通过。"""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _facts(state) -> str:
    from graphs.javatutor.prompting.contexts import build_facts_block

    return build_facts_block(state)


def critic_node(state, model=None) -> dict[str, Any]:
    # 上下文不可用时的固定降级文案是确定性输出，不进入评审/修订的 LLM 循环。
    if state.get("fetch_context_failed") and not state.get("has_steps"):
        return {"critic_passed": True, "critic_feedback": "", "critic_skipped": True}
    answer = state.get("revised_answer") or state.get("answer") or ""
    messages = [
        SystemMessage(content=SYSTEM_PROMPT_CRITIC),
        HumanMessage(content=f"候选回答：\n{answer}\n\n事实依据：\n{_facts(state)}"),
    ]
    try:
        parsed = _parse_json(_invoke(messages, model).content)
        if parsed is None:
            return {"critic_passed": True, "critic_feedback": "", "critic_skipped": True}
        issues = parsed.get("issues", []) if isinstance(parsed.get("issues"), list) else []
        return {
            "critic_passed": _as_bool(parsed.get("pass", False)),
            "critic_feedback": json.dumps(issues, ensure_ascii=False),
            "critic_skipped": False,
        }
    except Exception:
        return {"critic_passed": True, "critic_feedback": "", "critic_skipped": True}


def revise_node(state, model=None) -> dict[str, Any]:
    answer = state.get("answer") or ""
    if state.get("critic_passed") or state.get("revised"):
        return {"revised_answer": answer, "revised": False, "revise_skipped": False}
    messages = [
        SystemMessage(content=SYSTEM_PROMPT_REVISE),
        HumanMessage(
            content=(
                f"原回答：\n{answer}\n\n评审意见：\n{state.get('critic_feedback', '')}\n\n"
                f"事实依据：\n{_facts(state)}"
            )
        ),
    ]
    try:
        raw = _invoke(messages, model).content
        return {"revised_answer": raw, "revised": True, "revise_skipped": False}
    except Exception:
        return {"revised_answer": answer, "revised": False, "revise_skipped": True}
