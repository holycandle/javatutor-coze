"""从 JavaTutor 后端按 run_id 获取运行上下文。"""

import hashlib
import json
import os
import time
from typing import Any

import httpx

TOOL_SCHEMA = {
    "name": "fetch_execution_context",
    "description": "从 JavaTutor 后端获取指定 run_id 的源代码、执行步骤和当前执行位置",
    "parameters": {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
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


def _failure(error: str, latency_ms: float) -> dict[str, Any]:
    return {
        "fetch_context_failed": True,
        "fetch_context_error": error,
        "fetch_context_latency_ms": latency_ms,
        "fallback_reason": f"fetch_execution_context failed: {error}",
    }


def fetch_execution_context(state: dict, run_id: str | None = None) -> dict[str, Any]:
    """从 JavaTutor 后端获取运行上下文，返回状态更新字典。"""
    started = time.perf_counter()
    resolved_run_id = run_id if run_id is not None else state.get("run_id")
    base_url = os.getenv("JAVATUTOR_EXECUTION_CONTEXT_URL", "").rstrip("/")
    token = os.getenv("JAVATUTOR_AGENT_TOKEN", "")

    if not resolved_run_id:
        return _failure("run_id 为空", 0.0)
    if not base_url:
        return _failure("JAVATUTOR_EXECUTION_CONTEXT_URL 未配置", 0.0)
    if not token:
        return _failure("JAVATUTOR_AGENT_TOKEN 未配置", 0.0)

    headers = {"Accept": "application/json", "X-Agent-Token": token}
    try:
        response = httpx.get(f"{base_url}/{resolved_run_id}", headers=headers, timeout=3.0)
        if response.status_code != 200:
            latency = round((time.perf_counter() - started) * 1000, 1)
            return _failure(f"HTTP {response.status_code}", latency)
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        latency = round((time.perf_counter() - started) * 1000, 1)
        return _failure(type(exc).__name__, latency)

    source_code = data.get("source_code")
    steps = data.get("steps")
    if source_code is None or steps is None:
        latency = round((time.perf_counter() - started) * 1000, 1)
        return _failure("响应缺少 source_code 或 steps", latency)
    if not isinstance(steps, list):
        latency = round((time.perf_counter() - started) * 1000, 1)
        return _failure("steps 不是数组", latency)

    current_step_index = data.get("current_step_index", 0)
    current_line = data.get("current_line", 1)
    current_variables = _current_variables(steps, current_step_index)
    latency = round((time.perf_counter() - started) * 1000, 1)

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
        "compile_error": data.get("compile_error", ""),
        "has_error": bool((data.get("compile_error") or "").strip()),
        "algorithm_tags": data.get("algorithm_tags") or [],
        "fetch_context_failed": False,
        "fetch_context_error": "",
        "fetch_context_latency_ms": latency,
        "run_context_memory": {
            "run_id": resolved_run_id,
            "code_hash": hashlib.sha256(source_code.encode("utf-8")).hexdigest(),
            "steps_count": len(steps),
            "current_step_index": current_step_index,
            "current_line": current_line,
            "algorithm_tags": data.get("algorithm_tags") or [],
        },
    }
