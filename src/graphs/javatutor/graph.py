"""JavaTutor 图工作流 — 深化版流程图构建.

链路:
    parse_context → context_compaction → route_intent
    → [analyze | animate | animate_guide] → END（确定性直达）
    → retrieve_knowledge → [data_query | concept | debug | other]
    → critic → revise → build_final → END
"""

from langgraph.graph import END, StateGraph

from graphs.javatutor.nodes import (
    analyze_node,
    animate_guide_node,
    animate_node,
    build_final,
    context_compaction,
    concept_node,
    data_query_node,
    debug_node,
    other_node,
    parse_context,
    retrieve_knowledge,
    route_intent,
)
from graphs.javatutor.critic import critic_node, revise_node
from graphs.javatutor.state import JavaTutorState


def _route_to_expert(state: JavaTutorState) -> str:
    """route_intent 后的条件路由: 确定性直达 or 进入 RAG 检索链路."""
    intent = state.get("intent", "other")
    if intent in ("analyze", "animate", "animate_guide"):
        return intent
    return "retrieve_knowledge"


def _route_after_retrieval(state: JavaTutorState) -> str:
    """retrieve_knowledge 后的条件路由: 分发到文本专家."""
    intent = state.get("intent", "other")
    return intent if intent in ("data_query", "concept", "debug", "other") else "other"


def build_flow_graph() -> StateGraph:
    """构建 JavaTutor 深化版对话流程图."""
    graph = StateGraph(state_schema=JavaTutorState)

    # 注册节点
    graph.add_node("parse_context", parse_context)
    graph.add_node("context_compaction", context_compaction)
    graph.add_node("route_intent", route_intent)
    graph.add_node("retrieve_knowledge", retrieve_knowledge)
    graph.add_node("data_query", data_query_node)
    graph.add_node("concept", concept_node)
    graph.add_node("debug", debug_node)
    graph.add_node("other", other_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("animate", animate_node)
    graph.add_node("animate_guide", animate_guide_node)
    graph.add_node("critic", critic_node)
    graph.add_node("revise", revise_node)
    graph.add_node("final", build_final)

    # 设置入口
    graph.set_entry_point("parse_context")

    # parse_context → context_compaction → route_intent
    graph.add_edge("parse_context", "context_compaction")
    graph.add_edge("context_compaction", "route_intent")

    # route_intent 条件路由: 确定性直达 or RAG 检索链路
    graph.add_conditional_edges(
        source="route_intent",
        path=_route_to_expert,
        path_map={
            "analyze": "analyze",
            "animate": "animate",
            "animate_guide": "animate_guide",
            "retrieve_knowledge": "retrieve_knowledge",
        },
    )

    # 确定性直达节点 → END
    for direct in ("analyze", "animate", "animate_guide"):
        graph.add_edge(direct, END)

    # retrieve_knowledge → 文本专家
    graph.add_conditional_edges(
        source="retrieve_knowledge",
        path=_route_after_retrieval,
        path_map={
            "data_query": "data_query",
            "concept": "concept",
            "debug": "debug",
            "other": "other",
        },
    )

    # 文本专家 → critic → revise → final → END
    for expert in ("data_query", "concept", "debug", "other"):
        graph.add_edge(expert, "critic")
    graph.add_edge("critic", "revise")
    graph.add_edge("revise", "final")
    graph.add_edge("final", END)

    return graph
