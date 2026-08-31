"""step_facts 工具：返回指定步骤/行的原始证据与程序化 diff，不调用 LLM。

Phase 2：多文件下按「当前执行步」所在文件取行号代码，行号不再随用户切换的激活文件漂移。
"""

from typing import Any

TOOL_SCHEMA = {
    "name": "step_facts",
    "description": "查询指定步骤/行的原始执行证据与相邻步骤变化",
    "parameters": {
        "type": "object",
        "properties": {"step_index": {"type": "integer"}, "line": {"type": "integer"}},
    },
}


def _line_text(code: str, line, fallback_line=None) -> str:
    """取某行文本。line 为 None/0/非法时回退到 fallback_line（该步真实行号），避免误判越界。"""
    candidate = line if line not in (None, 0, "0", "") else fallback_line
    try:
        idx = int(candidate if candidate is not None else 1) - 1
        lines = code.splitlines()
        if 0 <= idx < len(lines):
            return lines[idx].strip()
    except (TypeError, ValueError):
        pass
    return "(行号超出范围)"


def _evidence_source(state, file=None) -> tuple[str, str]:
    """返回 (file_name, code)。定位只认「当前执行步」所在文件（current_step_file / state.files）。

    用户/前端切换到的激活文件（source_code）不参与定位。
    显式 file 参数优先，其次当前执行步文件，最后回退 source_code。
    """
    candidate = file or state.get("current_step_file") or ""
    files = state.get("files") or {}
    if candidate and candidate in files:
        return candidate, files[candidate]
    return "", state.get("source_code", "")


def step_facts(state, step_index=None, line=None, file=None) -> dict[str, Any]:
    steps = state.get("steps") or []
    if step_index is None and line is None:
        step_index = state.get("current_step_index", 0)
    try:
        idx = int(step_index)
        step = steps[idx]
    except (IndexError, TypeError, ValueError):
        count = len(steps)
        hint = ""
        # 用户口吻的「第 N 步」常是 1-based（展示序），工具用 0-based step_index=N-1。
        # 越界时若 N-1 落在合法区间，给出换算建议，帮 agent 自纠。
        if isinstance(step_index, int) and step_index > 0 and step_index - 1 < count:
            hint = f"若你指的第 {step_index} 步是展示序（1-based），应传 step_index={step_index - 1}"
        else:
            hint = "可用范围请以 steps_count 为准"
        return {
            "error": f"step_index {step_index} 不在可用范围（0..{count - 1}，共 {count} 步）。{hint}",
            "steps_count": count,
            "current_step_index": state.get("current_step_index", 0),
            "evidence": {},
            "diff": [],
        }

    file_name, code = _evidence_source(state, file=file)
    evidence = {
        "variables": step.get("variables", {}),
        "heap": step.get("heap", {}),
        "stackFrames": step.get("stackFrames", []),
        "output": step.get("output"),
        "file": file_name,
        "line_text": _line_text(code, line, fallback_line=step.get("line", 1)),
    }
    diff = []
    if idx > 0:
        prev_vars = steps[idx - 1].get("variables", {})
        cur_vars = step.get("variables", {})
        for key in sorted(set(prev_vars) | set(cur_vars)):
            if prev_vars.get(key) != cur_vars.get(key):
                diff.append({"key": key, "before": prev_vars.get(key), "after": cur_vars.get(key)})
    return {"error": "", "evidence": evidence, "diff": diff}
