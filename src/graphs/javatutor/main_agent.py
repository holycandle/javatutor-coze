"""主 Agent 工具循环：解析式工具调用，最多 3 轮。"""

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from graphs.javatutor.prompts import SYSTEM_PROMPT_MAIN_AGENT
from graphs.javatutor.prompting.panels import render_nav_guidance, render_ui_map
from tools.fetch_execution_context import fetch_execution_context
from tools.step_facts import step_facts

MAX_ROUNDS = 3


def _main_system_prompt() -> str:
    """主 Agent 系统提示 = 模板 + 运行时注入的【视角导航】引导与「UI 面板导航图」（随 manifest 联动）。"""
    return f"{SYSTEM_PROMPT_MAIN_AGENT}\n\n{render_nav_guidance()}\n\n{render_ui_map()}"


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


def _format_step_facts(args: dict, result: dict) -> str:
    """把 step_facts 返回值渲染成主 Agent 可直接读的证据文本（而非让模型解析原始 JSON）。

    工具返回的 step_index 是 0-based；这里统一带出「第 N 步（step_index=x）」标签，
    避免模型在上下文里把证据误对应到别的步骤。若 evidence 存在但模型仍未作答，
    该文本也能让模型一眼读出「这一步做了什么」，不再反复试探 step_facts。
    """
    if result.get("error"):
        return f"\n\n[step_facts 结果]\n错误：{result['error']}"
    idx = args.get("step_index")
    try:
        label = f"第 {int(idx) + 1} 步（step_index={int(idx)}）"
    except (TypeError, ValueError):
        label = "当前步"
    ev = result.get("evidence") or {}
    lines = [f"\n\n[step_facts 结果：{label}]"]
    lines.append(f"- 变量：{json.dumps(ev.get('variables', {}), ensure_ascii=False)}")
    heap = ev.get("heap")
    lines.append(f"- 堆：{json.dumps(heap, ensure_ascii=False) if heap else '（无堆数据）'}")
    frames = ev.get("stackFrames")
    lines.append(f"- 栈帧：{json.dumps(frames, ensure_ascii=False) if frames else '（无栈帧）'}")
    output = ev.get("output")
    lines.append(f"- 输出：`{output if output is not None else '（无输出）'}`")
    line = ev.get("line")
    if line is not None:
        lines.append(f"- 行号 {line}：`{ev.get('line_text', '')}`")
    else:
        lines.append(f"- 行代码：`{ev.get('line_text', '')}`")
    diff = result.get("diff") or []
    if diff:
        lines.append("- 与上一步对比：")
        for item in diff:
            if isinstance(item, dict):
                lines.append(f"  - {item.get('key', '?')}: {item.get('before', '?')} → {item.get('after', '?')}")
            else:
                lines.append(f"  - {item}")
    return "\n".join(lines)


def _handle_fetch(tool_calls, fetched_state_updates, state, args) -> str:
    """dispatch fetch_execution_context：暂存执行上下文，返回追加到 context 的文本。"""
    tool_calls.append({"tool": "fetch_execution_context", "args": args})
    try:
        result = fetch_execution_context(state, **args)
    except TypeError as exc:
        result = {"error": f"fetch_execution_context 参数非法: {exc}", "fetch_context_failed": True}
    if result.get("error"):
        return f"\n\n[fetch_execution_context 失败]\n{result['error']}"
    fetched_ctx = result.get("fetched_context") or {}
    updates = {
        "fetched_context": fetched_ctx,
        "run_id": result.get("run_id", state.get("run_id", "")),
        "fetch_context_failed": False,
        "fetch_context_latency_ms": result.get("fetch_context_latency_ms", 0.0),
        "fetch_context_error": "",
        "run_context_memory": result.get("run_context_memory"),
    }
    for k in (
        "source_code",
        "steps",
        "steps_json",
        "steps_count",
        "has_steps",
        "current_step_index",
        "current_line",
        "current_variables",
        "compile_error",
        "has_error",
        "algorithm_tags",
    ):
        if k in result:
            updates[k] = result[k]
    fetched_state_updates.update(updates)
    digest = {
        k: result.get(k)
        for k in ("file", "steps_count", "current_step_index", "current_line", "algorithm_tags")
        if k in result
    }
    payload = {"stored": True, **digest, "code": result.get("code", "")}
    return f"\n\n[fetch_execution_context 结果]\n{json.dumps(payload, ensure_ascii=False)}"


def main_agent_node(state, model=None) -> dict[str, Any]:
    context = state.get("context_built", "")
    rounds = 0
    answer = ""
    tool_calls = []
    step_memories = []
    fetched_state_updates = {}
    served_step_indices: set = set()
    while rounds < MAX_ROUNDS:
        rounds += 1
        messages = [
            SystemMessage(content=_main_system_prompt()),
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
        if tool["tool"] == "fetch_execution_context":
            args = tool.get("args") if isinstance(tool.get("args"), dict) else {}
            context += _handle_fetch(tool_calls, fetched_state_updates, state, args)
        elif tool["tool"] == "step_facts":
            args = tool.get("args") if isinstance(tool.get("args"), dict) else {}
            try:
                result = step_facts(state, **args)
            except TypeError as exc:
                # 参数含未知键或非法类型时给出结构化错误，而不是中断循环
                result = {"error": f"step_facts 参数非法: {exc}", "evidence": {}, "diff": []}
            # 记录参数 + 返回值（截断）供决策痕迹诊断：能看清是越界报错还是返回了证据
            tool_calls.append(
                {"tool": "step_facts", "args": args, "result": json.dumps(result, ensure_ascii=False)[:300]}
            )
            if not result.get("error"):
                step_memories.append(
                    {
                        "step_index": args.get("step_index", state.get("current_step_index", 0)),
                        "content": json.dumps(result, ensure_ascii=False)[:600],
                        "importance": 0.8,
                    }
                )
                step_memories = step_memories[-5:]
            if not result.get("error") and args.get("step_index") is not None:
                idx_key = args.get("step_index")
                if idx_key in served_step_indices:
                    # 同一步骤再次被查询：证据已在上文给出，明确要求直接作答，避免反复试探。
                    context += _format_step_facts(args, result)
                    context += (
                        "\n\n[提示] 这一步的证据已在上文「step_facts 结果」中给出，"
                        "请直接基于该证据回答用户问题，不要重复查询同一步骤。"
                    )
                else:
                    served_step_indices.add(idx_key)
                    context += _format_step_facts(args, result)
            else:
                context += _format_step_facts(args, result)
        else:
            # 未知工具：提示不可用，继续让主 Agent 直接回答，而不是把 JSON 当最终答案
            tool_calls.append({"tool": tool["tool"], "args": tool.get("args", {})})
            context += f"\n\n[工具 {tool['tool']} 不可用，请直接回答]"
    if not answer:
        answer = "抱歉，我暂时无法回答这个问题。"
    return {
        "answer": answer,
        "tool_rounds": rounds,
        "tool_calls": tool_calls,
        "step_memories": step_memories,
        **fetched_state_updates,
    }
