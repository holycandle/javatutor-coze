"""AgentBundle — 暴露 builder 给 Coze 平台 lifespan.

Coze 平台要求:
1. build_agent() 返回值必须包含 .builder 属性（StateGraph，未编译）
2. 平台 lifespan 调用 builder.compile() 后得到 CompiledStateGraph
3. 平台通过 checkpointer 实现多轮对话记忆
"""

from typing import TYPE_CHECKING

from storage.memory.memory_saver import get_memory_saver

if TYPE_CHECKING:
    from langgraph.graph import StateGraph


class AgentBundle:
    """Agent 容器，暴露 builder 供平台调用 compile()."""

    def __init__(self, builder: "StateGraph"):
        self.builder = builder
        self._checkpointer = get_memory_saver()

    def compile(self):
        """快捷方法: 直接编译并返回 CompiledStateGraph."""
        return self.builder.compile(checkpointer=self._checkpointer)
