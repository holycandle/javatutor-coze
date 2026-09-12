"""主 Agent 节点（兼容层）。

原本写在这里的 `while rounds < MAX_ROUNDS` 工具循环已契约化为**图内真环**：
`propose`（提案）→ `guard`（治理）→ `run_tools`（执行）→ 回 `propose`。
见 ``docs/spec/2026-09-11-agent-harness-react-loop-design.md``。

本模块保留原路径的名字，避免既有导入悬空：
``main_agent_node``（薄包装）、``_main_system_prompt``、``MAX_ROUNDS``、两个渲染器。
"""

from graphs.javatutor.harness.guard import MAX_ROUNDS  # noqa: F401
from graphs.javatutor.harness.propose import (  # noqa: F401
    _invoke,
    _main_system_prompt,
    _resolve_model,
    propose,
)
from graphs.javatutor.harness.render import _format_step_facts, _handle_fetch  # noqa: F401


def main_agent_node(state, model=None) -> dict:
    """图上的 `main_agent` 节点：只产出一轮提案或终答，不再自己循环。"""
    return propose(state, model=model)
