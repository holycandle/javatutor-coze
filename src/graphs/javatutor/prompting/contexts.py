"""按意图构建专家上下文的模块。上下文数据只能来自 state。"""

import json
from typing import Any

from graphs.javatutor.prompting.versions import PROMPT_VERSION


def _current_line_text(state: dict[str, Any]) -> str:
    source = state.get("source_code", "")
    line = state.get("current_line")
    try:
        idx = int(line) - 1
        lines = source.splitlines()
        if 0 <= idx < len(lines):
            return lines[idx].strip()
    except (TypeError, ValueError):
        pass
    return "(行号超出范围)"


def _step_snapshot(state: dict[str, Any]) -> str:
    steps = state.get("steps") or []
    index = state.get("current_step_index", 0)
    try:
        idx = int(index)
        step = steps[idx]
    except (IndexError, TypeError, ValueError):
        return "### 当前步骤\n（该步骤数据不可用）"
    lines = [f"### 当前步骤（第 {idx + 1} 步，行 {step.get('line', '')}）"]
    lines.append(f"- 行代码：`{_current_line_text(state)}`")
    lines.append(f"- 变量快照：```json\n{json.dumps(step.get('variables', {}), ensure_ascii=False, indent=2)}\n```")
    heap = step.get("heap", {})
    lines.append(f"- 堆对象：```json\n{json.dumps(heap, ensure_ascii=False, indent=2) if heap else '（该步骤无堆数据）'}\n```")
    frames = step.get("stackFrames", [])
    lines.append(f"- 栈帧：```json\n{json.dumps(frames, ensure_ascii=False, indent=2) if frames else '（该步骤无栈帧）'}\n```")
    output = step.get("output")
    lines.append(f"- 输出：`{output if output is not None else '（无输出）'}`")
    return "\n".join(lines)


def _adjacent_diff(state: dict[str, Any]) -> str:
    steps = state.get("steps") or []
    index = state.get("current_step_index", 0)
    try:
        idx = int(index)
        prev = steps[idx - 1]
        cur = steps[idx]
    except (IndexError, TypeError, ValueError):
        return ""
    prev_vars = prev.get("variables", {})
    cur_vars = cur.get("variables", {})
    changes = []
    for key in sorted(set(prev_vars) | set(cur_vars)):
        if prev_vars.get(key) != cur_vars.get(key):
            changes.append(
                f"- {key}: {json.dumps(prev_vars.get(key), ensure_ascii=False)} → "
                f"{json.dumps(cur_vars.get(key), ensure_ascii=False)}"
            )
    return "### 与上一步对比\n" + "\n".join(changes) if changes else ""


def _method_context(state: dict[str, Any]) -> str:
    parts = []
    if state.get("method_name"):
        parts.append(f"- 方法名: {state.get('method_name')}")
    if state.get("method_signature"):
        parts.append(f"- 方法签名: {state.get('method_signature')}")
    tags = state.get("algorithm_tags") or []
    if tags:
        parts.append(f"- 算法标签: {', '.join(tags)}")
    return "\n".join(parts)


def _rag_block(state: dict[str, Any]) -> str:
    chunks = state.get("retrieved_chunks") or []
    if not chunks:
        return ""
    refs = "\n".join(f"- {c['source']}: {c['content'][:200]}" for c in chunks)
    return f"### 知识库参考\n{refs}\n回答中如引用知识库内容，必须标注「参考知识库：来源名」。"


def _base_context(state: dict[str, Any]) -> list[str]:
    parts = [
        f"### 用户问题\n{state.get('user_question', '')}",
        f"\n### 源代码\n```java\n{state.get('source_code', '')}\n```",
    ]
    if state.get("has_steps"):
        parts.append("\n" + _step_snapshot(state))
        diff = _adjacent_diff(state)
        if diff:
            parts.append("\n" + diff)
    method = _method_context(state)
    if method:
        parts.append("\n### 方法上下文\n" + method)
    return parts


def _with_rag(parts: list[str], state: dict[str, Any]) -> str:
    rag = _rag_block(state)
    if rag:
        parts.append("\n" + rag)
    return "\n".join(parts)


def build_data_query_context(state: dict[str, Any]) -> str:
    return _with_rag(_base_context(state), state)


def build_concept_context(state: dict[str, Any]) -> str:
    return _with_rag(_base_context(state), state)


def build_debug_context(state: dict[str, Any]) -> str:
    parts = _base_context(state)
    parts.append(f"\n### 编译错误\n{state.get('compile_error', '')}")
    return _with_rag(parts, state)


def build_other_context(state: dict[str, Any]) -> str:
    return _with_rag(_base_context(state), state)


def build_facts_block(state: dict[str, Any]) -> str:
    lines = [
        f"学生问题：{state.get('user_question', '')}",
        f"编译错误：{state.get('compile_error', '')}",
    ]
    if state.get("has_steps"):
        lines.append(_step_snapshot(state))
    method = _method_context(state)
    if method:
        lines.append("\n### 方法上下文\n" + method)
    return _with_rag(lines, state)
