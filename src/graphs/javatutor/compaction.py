"""steps 上下文压缩：超过阈值时输出窗口 + 摘要 + 变量轨迹。"""

import json
from typing import Any

DEFAULT_THRESHOLD = 200
DEFAULT_WINDOW = 30


def _build_summary(steps: list[dict]) -> str:
    seen = []
    for step in steps:
        variables = step.get("variables") or {}
        for key in ("arr", "array", "nums", "list"):
            if key in variables:
                value = variables[key]
                if value not in seen:
                    seen.append(value)
                break
    return f"共 {len(steps)} 步；最近数组形态: {seen[-5:]}"


def compact_steps(
    steps: list[dict],
    current_step_index: int = 0,
    threshold: int = DEFAULT_THRESHOLD,
    window: int = DEFAULT_WINDOW,
) -> dict[str, Any]:
    count = len(steps)
    if count <= threshold:
        return {
            "steps_json": json.dumps(steps, ensure_ascii=False),
            "context_summary": "",
            "compaction_mode": "none",
        }
    try:
        index = int(current_step_index) if current_step_index is not None else count - 1
        index = max(0, min(index, count - 1))
        start = max(0, min(index - window // 2, count - window))
        window_steps = steps[start:start + window]
        return {
            "steps_json": json.dumps(window_steps, ensure_ascii=False),
            "context_summary": _build_summary(steps),
            "compaction_mode": "windowed",
        }
    except Exception:
        return {
            "steps_json": json.dumps(steps[:threshold], ensure_ascii=False),
            "context_summary": "",
            "compaction_mode": "truncated",
        }
