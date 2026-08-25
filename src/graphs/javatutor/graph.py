"""JavaTutor 图工作流 — 多工具 + 上下文工程版.

链路:
    parse_context → context_compaction → analyze_code
    → [direct（intent=analyze）] → END
    → load_session → retrieve_knowledge（RAG）→ build_context（GSSC）
    → main_agent（step_facts 工具循环）→ critic → revise → save_session → final → END
"""

from langgraph.graph import END, StateGraph

from graphs.javatutor.analyze import analyze_code_node
from graphs.javatutor.critic import critic_node, revise_node
from graphs.javatutor.fetch_context import fetch_execution_context_node
from graphs.javatutor.main_agent import main_agent_node
from graphs.javatutor.nodes import (
    build_context_node,
    build_final,
    context_compaction,
    load_session,
    parse_context,
    retrieve_knowledge,
    save_session,
)
from graphs.javatutor.state import JavaTutorState


def _route_after_analyze(state: JavaTutorState) -> str:
    return "direct" if state.get("intent") == "analyze" else "continue"


def build_flow_graph() -> StateGraph:
    graph = StateGraph(state_schema=JavaTutorState)
    graph.add_node("parse_context", parse_context)
    graph.add_node("fetch_execution_context", fetch_execution_context_node)
    graph.add_node("context_compaction", context_compaction)
    graph.add_node("analyze_code", analyze_code_node)
    graph.add_node("load_session", load_session)
    graph.add_node("retrieve_knowledge", retrieve_knowledge)
    graph.add_node("build_context", build_context_node)
    graph.add_node("main_agent", main_agent_node)
    graph.add_node("critic", critic_node)
    graph.add_node("revise", revise_node)
    graph.add_node("save_session", save_session)
    graph.add_node("final", build_final)

    graph.set_entry_point("parse_context")
    graph.add_edge("parse_context", "fetch_execution_context")
    graph.add_edge("fetch_execution_context", "context_compaction")
    graph.add_edge("context_compaction", "analyze_code")
    # intent=analyze 直达返回结构化 JSON；否则进入后续问答链路
    graph.add_conditional_edges("analyze_code", _route_after_analyze, {"direct": END, "continue": "load_session"})
    graph.add_edge("load_session", "retrieve_knowledge")
    graph.add_edge("retrieve_knowledge", "build_context")
    graph.add_edge("build_context", "main_agent")
    graph.add_edge("main_agent", "critic")
    graph.add_edge("critic", "revise")
    graph.add_edge("revise", "save_session")
    graph.add_edge("save_session", "final")
    graph.add_edge("final", END)
    return graph
