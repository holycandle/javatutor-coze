"""从当前 state 读取执行上下文的读取工具（纯 state 读取，不发 HTTP）。

Phase 2：激活多文件读取。``file`` 参数命中 ``state.files`` 时读取对应文件内容；
缺省按 ``_resolve_code`` 的固定顺序兜底（显式 file → entry_file → current_step_file
→ files 唯一项 → source_code → **结构化失败**）。读到的完整执行上下文写入
``state.fetched_context`` 暂存，同时修复标准字段供 ``step_facts`` /
``analyze_code_node`` / 真实行号解析复用。
``run_id`` / ``start_line`` / ``end_line`` 保留；`file` 本轮激活。

自描述（2026-09-14 联调修复 D2）：成功回包必带 ``file`` 与 ``file_source``，让模型与
决策痕迹都能读出「这次到底拿到了哪个文件、走的是哪条兜底」；**任何解析不到源码
（含切行后为空）的路径一律结构化失败**，不再有「``fetch_context_failed=False`` 但
``code=""``」这种静默成功——报告症状「调用了 fetch 却每轮都说缺少源码」正源于此。
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


def match_file_key(files: dict, file) -> str | None:
    """在 ``files`` 中按「精确 → 忽略大小写 → basename（忽略大小写）」匹配文件名。

    未命中返回 ``None``。运行时治理门闩（``harness/guard.py`` 的 P4）与本工具共用这一份口径，
    避免出现「门闩认为歧义、工具却能解析」这类分叉。
    """
    if not file:
        return None
    if file in files:
        return file
    lower_input = _basename(str(file)).lower()
    for name in files:
        if name.lower() == str(file).lower() or _basename(name).lower() == lower_input:
            return name
    return None


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


def _no_source_error(files: dict, file_source: str = "") -> dict[str, Any]:
    """源码解析不到时的结构化失败（**禁止「成功但空」**，见 2026-09-14 修复计划 D2）。

    错误文本必须自带可执行的下一步：点名候选文件，模型才知道该用哪个 ``file`` 重取。
    """
    candidates = sorted(files) if files else []
    return {
        "error": (
            f"未能取到源码（解析来源：{file_source or '未能解析'}；候选文件：{candidates}）。"
            "请用 file 参数指定要读的文件名。"
        ),
        "fetch_context_failed": True,
        "fetch_context_latency_ms": 0.0,
    }


def _resolve_code(state: dict, file=None) -> tuple[str, str, str, dict]:
    """按固定顺序解析要返回的源码，返回 ``(code, file_name, file_source, error_or_empty)``。

    解析顺序（第一条命中即停；2026-09-14 修复计划 D3）：

    1. 显式 ``file``（精确 / 忽略大小写 / basename）——契约不变，显式请求永远优先；
    2. ``entry_file``（主入口）——契约不变，仍是「默认读主入口」；
    3. ``current_step_file``（当前执行步所在文件）——**新增兜底**，语义最贴近「用户正在看的那一步」；
    4. ``files`` 唯一项——项目只有一个文件时它就是答案；
    5. ``source_code``（单文件 / 激活文件）；
    6. 以上皆不成立 → **结构化失败**（不再静默返回空串）。

    ``file_source`` 是新增的自描述字段：模型与决策痕迹都必须能区分
    「取到了哪个文件」与「取到的是哪条兜底」，否则只能笼统地说「没有源码」。

    特例：``files`` 为空（单文件 payload）而模型传了 ``file`` 时，仍按既有语义回退
    ``source_code``（``file_source="source_code"``），不报「文件不存在」。
    """
    files = state.get("files") or {}
    source_code = state.get("source_code") or ""

    if file:
        key = match_file_key(files, file)
        if key is not None:
            return files[key], key, "explicit", {}
        if not files and source_code:
            return source_code, str(file), "source_code", {}
        return "", str(file), "explicit", {
            "error": f"文件不存在：{file}（项目结构中的文件：{sorted(files)}）",
            "fetch_context_failed": True,
            "fetch_context_latency_ms": 0.0,
        }

    entry = state.get("entry_file") or ""
    if entry:
        key = match_file_key(files, entry)
        if key is not None:
            return files[key], key, "entry_file", {}

    step_file = _step_file(state, state.get("current_step_index", 0)) or state.get(
        "current_step_file"
    ) or ""
    if step_file:
        key = match_file_key(files, step_file)
        if key is not None:
            return files[key], key, "current_step_file", {}

    if len(files) == 1:
        only = next(iter(files))
        return files[only], only, "only_file", {}

    if source_code:
        return source_code, "", "source_code", {}

    return "", "", "", _no_source_error(files)


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
    code, file_name, file_source, err = _resolve_code(state, file)
    if err:
        return err
    # 「禁止成功但空」：解析到空串一律结构化失败（过去 `not code and not steps` 会把它
    # 当成功返回，模型只能笼统地说「没有源码」，而痕迹里却是一次绿色调用）。
    if not code:
        return _no_source_error(state.get("files") or {}, file_source)
    sliced = _slice(code, start_line, end_line)
    # 行范围切出空串同样是「成功但空」：如实报出行范围，而不是回一份空 code。
    if not sliced:
        return {
            "error": (
                f"指定行范围为空：{file_name or '(未命名)'} 只有 {len(code.splitlines())} 行，"
                f"请求的是 {start_line}–{end_line} 行。请去掉行范围或改用有效行号重新读取。"
            ),
            "fetch_context_failed": True,
            "fetch_context_latency_ms": 0.0,
        }
    code = sliced
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
        "file_source": file_source,
        "code_chars": len(code),
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
