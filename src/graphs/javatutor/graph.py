"""JavaTutor 图工作流 — 流程图构建."""

from typing import Literal

from langgraph.graph import END, StateGraph

from graphs.javatutor.nodes import (
    analyze_node,
    animate_node,
    concept_node,
    data_query_node,
    debug_node,
    other_node,
    parse_context,
    route_intent,
)
from graphs.javatutor.state import JavaTutorState


def _route_to_expert(state: JavaTutorState) -> Literal["data_query", "concept", "debug", "animate", "analyze", "other"]:
    """条件路由: 根据 intent 返回目标专家节点名."""
    intent: str = state.get("intent", "other")
    node_map = {
        "data_query": "data_query",
        "concept": "concept",
        "debug": "debug",
        "animate": "animate",
        "analyze": "analyze",
        "other": "other",
    }
    return node_map.get(intent, "other")


def build_flow_graph() -> StateGraph:
    """构建 JavaTutor 对话流程图.

    节点:
        parse_context  →  解析 JSON 消息
        route_intent  →  意图识别
        data_query    →  执行数据专家
        concept       →  概念讲解专家
        debug         →  错误修复专家
        animate       →  动画生成（Phase 1 占位）
        other         →  通用兜底专家
        final         →  构建 AIMessage

    边:
        parse_context → route_intent
        route_intent  → [data_query | concept | debug | animate | other] (条件路由)
        [各专家]       → final
        final         → END
    """
    graph = StateGraph(state_schema=JavaTutorState)

    # 注册节点
    graph.add_node("parse_context", parse_context)
    graph.add_node("route_intent", route_intent)
    graph.add_node("data_query", data_query_node)
    graph.add_node("concept", concept_node)
    graph.add_node("debug", debug_node)
    graph.add_node("animate", animate_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("other", other_node)

    # 设置入口
    graph.set_entry_point("parse_context")

    # parse_context → route_intent
    graph.add_edge("parse_context", "route_intent")

    # 条件路由: route_intent → 专家节点
    graph.add_conditional_edges(
        source="route_intent",
        path=_route_to_expert,
        path_map={
            "data_query": "data_query",
            "concept": "concept",
            "debug": "debug",
            "animate": "animate",
            "analyze": "analyze",
            "other": "other",
        },
    )

    # 专家节点 → 结束（专家节点直接返回 AIMessage，build_final 已移除）
    for node in ["data_query", "concept", "debug", "animate", "analyze", "other"]:
        graph.add_edge(node, END)

    return graph
