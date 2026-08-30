"""从当前 state 读取执行上下文的读取工具（纯 state 读取，不发 HTTP）。

本次重构：不再依赖后端 HTTP 快照，改为从入站 state 的 ``source_code`` / ``steps`` /
``current_step_index`` / ``current_line`` 读取（永远新鲜）。读到的完整执行上下文写入
``state.fetched_context`` 暂存，同时修复标准字段供 ``step_facts`` / ``analyze_code_node`` /
真实行号解析复用。``run_id`` / ``file`` / ``start_line`` / ``end_line`` 参数为多文件与长代码
预留，本轮只实现单入口/整段读取。
"""

import hashlib
import json
import time
from typing import Any

TOOL_SCHEMA = {
    "name": "fetch_execution_context",
    "description": (
        "读取本次运行的执行上下文（源代码、执行步骤、当前执行位置）。"
        "读取结果会暂存到状态，供后续推理与单步查询复用；"
        "回答需要代码或执行证据的问题前应先调用本工具。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "run_id": {"type": "string", "description": "可选，默认使用当前上下文的 run_id"},
            "file": {"type": "string", "description": "预留：多文件模式下要读取的文件名，缺省读取主入口/当前代码"},
            "start_line": {"type": "integer", "description": "预留：只读取该行开始的代码片段"},
            "end_line": {"type": "integer", "description": "预留：只读取到该行"},
        },
    },
}


def _current_variables(steps: list[dict], current_step_index: int) -> dict:
    try:
        idx = int(current_step_index)
        if 0 <= idx < len(steps):
            return steps[idx].get("variables", {}) or {}
    except (TypeError, ValueError):
        pass
    return {}


def _slice(source: str, start_line=None, end_line=None) -> str:
    """1-based 行切片；未指定则返回整段代码。"""
    if start_line is None and end_line is None:
        return source
    lines = source.splitlines()
    s = int(start_line) - 1 if start_line is not None else 0
    e = int(end_line) if end_line is not None else len(lines)
    s = max(0, s)
    e = min(len(lines), e)
    return "\n".join(lines[s:e])


def fetch_execution_context(
    state: dict, run_id=None, file=None, start_line=None, end_line=None
) -> dict[str, Any]:
    """从 state 读取执行上下文，返回给模型看的结果 + 写进 state 的暂存。

    失败时绝不抛异常，返回结构化错误，且不写坏 state。
    """
    resolved_run_id = run_id or state.get("run_id", "")
    source_code = state.get("source_code", "")
    steps = state.get("steps") or []
    if not source_code and not steps:
        return {
            "error": "当前没有可用的执行上下文（源代码/步骤缺失），请重新运行代码后再提问。",
            "fetch_context_failed": True,
            "fetch_context_latency_ms": 0.0,
        }
    code = _slice(source_code, start_line, end_line)
    current_step_index = state.get("current_step_index", 0)
    current_line = state.get("current_line", 1)
    current_variables = _current_variables(steps, current_step_index)
    latency = 0.0
    return {
        "run_id": resolved_run_id,
        "source_code": source_code,
        "steps": steps,
        "steps_json": json.dumps(steps, ensure_ascii=False),
        "steps_count": len(steps),
        "has_steps": bool(steps),
        "current_step_index": current_step_index,
        "current_line": current_line,
        "current_variables": current_variables,
        "compile_error": state.get("compile_error", ""),
        "has_error": bool((state.get("compile_error") or "").strip()),
        "algorithm_tags": state.get("algorithm_tags") or [],
        "fetch_context_failed": False,
        "fetch_context_error": "",
        "fetch_context_latency_ms": latency,
        "stored": True,
        "fetched_from_state": True,
        "code": code,
        "fetched_context": {
            "run_id": resolved_run_id,
            "source_code": source_code,
            "steps": steps,
            "steps_count": len(steps),
            "current_step_index": current_step_index,
            "current_line": current_line,
            "compile_error": state.get("compile_error", ""),
            "algorithm_tags": state.get("algorithm_tags") or [],
            "code_hash": hashlib.sha256(source_code.encode("utf-8")).hexdigest(),
            "fetched_at": time.time(),
            "fetch_context_latency_ms": latency,
        },
        "run_context_memory": {
            "run_id": resolved_run_id,
            "code_hash": hashlib.sha256(source_code.encode("utf-8")).hexdigest(),
            "steps_count": len(steps),
            "current_step_index": current_step_index,
            "current_line": current_line,
            "algorithm_tags": state.get("algorithm_tags") or [],
        },
    }
