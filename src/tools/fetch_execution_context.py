"""从当前 state 读取执行上下文的读取工具（纯 state 读取，不发 HTTP）。

Phase 2：激活多文件读取。``file`` 参数命中 ``state.files`` 时读取对应文件内容；
缺省读取主入口。读到的完整执行上下文写入 ``state.fetched_context`` 暂存，
同时修复标准字段供 ``step_facts`` / ``analyze_code_node`` / 真实行号解析复用。
``run_id`` / ``start_line`` / ``end_line`` 保留；`file` 本轮激活。
"""

import hashlib
import json
import time
from typing import Any

TOOL_SCHEMA = {
    "name": "fetch_execution_context",
    "description": (
        "读取本次运行的执行上下文（源代码、执行步骤、当前执行位置）。"
        "支持用 file 参数读取项目中的某个文件；读取结果会暂存到状态，供后续推理与单步查询复用；"
        "回答需要代码或执行证据的问题前应先调用本工具。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "run_id": {"type": "string", "description": "可选，默认使用当前上下文的 run_id"},
            "file": {"type": "string", "description": "可选：项目中要读取的文件名（支持精确/忽略大小写/basename 匹配），缺省读取主入口"},
            "start_line": {"type": "integer", "description": "预留：只读取该行开始的代码片段"},
            "end_line": {"type": "integer", "description": "预留：只读取到该行"},
        },
    },
}


def normalize_files(raw) -> dict[str, str]:
    """把 payload 的 ``files`` 归一化为 {name: code}。

    兼容三种形态：
    - dict: {"App.java": "code"}
    - list[{name, code}]
    - list[{path, code}]
    """
    result: dict[str, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, str):
                result[str(k)] = v
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("path")
            code = item.get("code")
            if name and isinstance(code, str):
                result[str(name)] = code
    return result


def _basename(path: str) -> str:
    """取路径最后一段文件名（不依赖 os，保持工具模块无环境依赖）。"""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _current_variables(steps: list[dict], current_step_index: int) -> dict:
    try:
        idx = int(current_step_index)
        if 0 <= idx < len(steps):
            return steps[idx].get("variables", {}) or {}
    except (TypeError, ValueError):
        pass
    return {}


def _step_file(state: dict, current_step_index: int) -> str:
    steps = state.get("steps") or []
    try:
        idx = int(current_step_index)
        if 0 <= idx < len(steps):
            return steps[idx].get("file", "") or ""
    except (TypeError, ValueError):
        pass
    return ""


def _resolve_code(state: dict, file=None) -> tuple[str, str, dict]:
    """返回 (code, file_name, error_or_empty)。

    file 为空 -> 主入口：优先 state.entry_file（若在 files 中），否则 state.source_code；
    file 命中 state.files（精确/忽略大小写/basename） -> 该文件 code；
    未命中 -> error。
    """
    files = state.get("files") or {}
    if file:
        key = None
        if file in files:
            key = file
        else:
            lower_input = _basename(str(file)).lower()
            for name in files:
                if name.lower() == str(file).lower() or _basename(name).lower() == lower_input:
                    key = name
                    break
        if key is None:
            return "", str(file), {
                "error": f"文件不存在：{file}（项目结构中的文件：{sorted(files)}）",
                "fetch_context_failed": True,
                "fetch_context_latency_ms": 0.0,
            }
        return files[key], key, {}
    entry = state.get("entry_file") or ""
    if entry and entry in files:
        return files[entry], entry, {}
    return state.get("source_code", ""), "", {}


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
    steps = state.get("steps") or []
    code, file_name, err = _resolve_code(state, file)
    if err:
        return err
    if not code and not steps:
        return {
            "error": "当前没有可用的执行上下文（源代码/步骤缺失），请重新运行代码后再提问。",
            "fetch_context_failed": True,
            "fetch_context_latency_ms": 0.0,
        }
    code = _slice(code, start_line, end_line)
    source_code = state.get("source_code", "")
    current_step_index = state.get("current_step_index", 0)
    current_line = state.get("current_line", 1)
    current_variables = _current_variables(steps, current_step_index)
    current_step_file = _step_file(state, current_step_index)
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
        "file": file_name,
        "code": code,
        "current_step_file": current_step_file,
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
            "current_step_file": current_step_file,
            "project_files": sorted((state.get("files") or {}).keys()),
        },
        "run_context_memory": {
            "run_id": resolved_run_id,
            "code_hash": hashlib.sha256(source_code.encode("utf-8")).hexdigest(),
            "steps_count": len(steps),
            "current_step_index": current_step_index,
            "current_line": current_line,
            "algorithm_tags": state.get("algorithm_tags") or [],
            "files_count": len(state.get("files") or {}),
        },
    }
