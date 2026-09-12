"""观察渲染器：把工具返回值渲染成主 Agent 可直接读的证据文本。

从 ``main_agent.py`` 原样迁出（签名不变），原位置保留 re-export 以免既有导入悬空。
``_handle_fetch`` 兼做「执行 + 渲染」，是 fetch 的便捷封装；
需要结构化结果的调用方（``harness/tools_node.py``）传本地临时 ``tool_calls`` /
``fetched_state_updates`` 容器进来即可，避免为了拿 payload 再写第二份执行逻辑。
"""

import json

from tools.fetch_execution_context import fetch_execution_context


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
        # 失败也要落进 state：``critic_node`` 靠 ``fetch_context_failed`` 决定是否
        # 跳过 LLM 评审，``decision_trace`` 也靠它和 ``fetch_context_error`` 把失败讲清楚。
        fetched_state_updates.update(
            {
                "fetch_context_failed": True,
                "fetch_context_latency_ms": float(
                    result.get("fetch_context_latency_ms", 0.0) or 0.0
                ),
                "fetch_context_error": str(result["error"]),
            }
        )
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
