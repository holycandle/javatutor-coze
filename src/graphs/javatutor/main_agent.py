"""主 Agent 工具循环：解析式工具调用，最多 3 轮。"""

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from graphs.javatutor.prompts import SYSTEM_PROMPT_MAIN_AGENT
from tools.step_facts import step_facts

MAX_ROUNDS = 3


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

    raw = llm_complete(messages, temperature=0.5, max_completion_tokens=2000)
    return AIMessage(content=raw)


def _parse_tool(raw: str) -> dict | None:
    text = (raw or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and data.get("tool") else None


def main_agent_node(state, model=None) -> dict[str, Any]:
    context = state.get("context_built", "")
    rounds = 0
    answer = ""
    tool_calls = []
    while rounds < MAX_ROUNDS:
        rounds += 1
        messages = [
            SystemMessage(content=SYSTEM_PROMPT_MAIN_AGENT),
            HumanMessage(content=f"{context}\n\n[当前轮次] {rounds}"),
        ]
        try:
            resp = _invoke(messages, model).content
        except Exception:
            answer = "抱歉，回答生成服务暂时不可用，请稍后重试。"
            break
        tool = _parse_tool(resp)
        if tool is None:
            answer = resp
            break
        if tool["tool"] == "step_facts":
            args = tool.get("args") if isinstance(tool.get("args"), dict) else {}
            tool_calls.append({"tool": "step_facts", "args": args})
            try:
                result = step_facts(state, **args)
            except TypeError as exc:
                # 参数含未知键或非法类型时给出结构化错误，而不是中断循环
                result = {"error": f"step_facts 参数非法: {exc}", "evidence": {}, "diff": []}
            context += f"\n\n[step_facts 结果]\n{json.dumps(result, ensure_ascii=False)}"
        else:
            # 未知工具：提示不可用，继续让主 Agent 直接回答，而不是把 JSON 当最终答案
            tool_calls.append({"tool": tool["tool"], "args": tool.get("args", {})})
            context += f"\n\n[工具 {tool['tool']} 不可用，请直接回答]"
    if not answer:
        answer = "抱歉，我暂时无法回答这个问题。"
    return {"answer": answer, "tool_rounds": rounds, "tool_calls": tool_calls}
