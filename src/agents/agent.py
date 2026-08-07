"""JavaTutor Coze Agent — build_agent 入口.

返回 AgentBundle，暴露 .builder 供 Coze 平台 lifespan 调用 .compile().
"""

from agents.agent_bundle import AgentBundle
from graphs.javatutor.graph import build_flow_graph


def build_agent(ctx=None) -> AgentBundle:
    """构建 JavaTutor 对话智能体.

    Returns:
        AgentBundle: 包含 builder（未编译的 StateGraph），
                     平台 lifespan 调用 builder.compile() 后得到可执行图。
    """
    builder = build_flow_graph()
    return AgentBundle(builder=builder)
