"""fetch_execution_context 确定性 graph 节点。"""

from tools.fetch_execution_context import fetch_execution_context


def fetch_execution_context_node(state: dict) -> dict:
    result = fetch_execution_context(state, state.get("run_id"))
    # 旧 payload 已提供完整执行数据时，fetch 失败也不触发固定降级文案。
    if (
        result.get("fetch_context_failed")
        and state.get("has_steps")
        and (state.get("source_code") or "").strip()
    ):
        result["fallback_reason"] = ""
    return result
