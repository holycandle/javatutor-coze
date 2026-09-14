"""JavaTutor 图工作流 — 多工具 + 上下文工程版.

链路:
    parse_context → context_compaction → analyze_code
      ├─ intent=analyze ────────────────────────────────────────────→ END
      └─ continue → load_session → retrieve_knowledge → build_context
                         ┌──────────────────────┐
                         ↓                      │
                     main_agent ─(answer)→ answer_gate ─(pass)→ critic → revise → verify
                         │                     │                              │
                      (action)              (retry: 终答形态不合规)      save_session → final → END
                         ↓                     ↑
                       guard ─(allow)─→ run_tools ──────┘
                         │              (回 main_agent)
                         └──(deny)──→ 回 main_agent

`main_agent`（提案）/ `guard`（治理）/ `run_tools`（执行）构成图内真环；
`answer_gate`（终答形态门闩）与 `guard` 同属治理层，是环外的第二个回提案入口；
`guard` 是唯一的暂停点（HITL 中断）。轮次预算与终止性证明见
`docs/spec/2026-09-11-agent-harness-react-loop-design.md` §4.3，门闩见 §4.9。
"""

from langgraph.graph import END, StateGraph

from graphs.javatutor.analyze import analyze_code_node
from graphs.javatutor.critic import critic_node, revise_node
from graphs.javatutor.harness.answer_gate import answer_gate_node, route_after_answer_gate
from graphs.javatutor.harness.guard_node import guard_node
from graphs.javatutor.harness.tools_node import run_tools_node
from graphs.javatutor.main_agent import main_agent_node
from graphs.javatutor.nodes import (
    build_context_node,
    build_final,
    context_compaction,
    load_session,
    parse_context,
    retrieve_knowledge,
    save_session,
    verify_node,
)
from graphs.javatutor.state import JavaTutorState


def _route_after_analyze(state: JavaTutorState) -> str:
    return "direct" if state.get("intent") == "analyze" else "continue"


def _route_after_propose(state: JavaTutorState) -> str:
    """手里有提案 → 去门闩；否则是终答 → 去过形态门闩再评审。

    判据用**本轮刚写入的** ``proposed_action``，不用 ``answer``：后者会持久化，
    将来挂上 checkpointer 后同一 thread 复用时会带着旧 ``answer`` 重入环。
    """
    return "guard" if state.get("proposed_action") else "answer_gate"


def _route_after_guard(state: JavaTutorState) -> str:
    """放行 → 执行；被拒 → 回提案节点自我修正。

    ``P4-resolved`` 也是 allow：用户在中断里选的文件名已经补进原提案，
    该提案可以直接执行（原提案的 ``file`` 本来就是唯一不可判定的那一项）。
    """
    decision = state.get("guard_decision") or {}
    return "tools" if decision.get("verdict") == "allow" else "propose"


def build_flow_graph() -> StateGraph:
    graph = StateGraph(state_schema=JavaTutorState)
    graph.add_node("parse_context", parse_context)
    graph.add_node("context_compaction", context_compaction)
    graph.add_node("analyze_code", analyze_code_node)
    graph.add_node("load_session", load_session)
    graph.add_node("retrieve_knowledge", retrieve_knowledge)
    graph.add_node("build_context", build_context_node)
    graph.add_node("main_agent", main_agent_node)
    graph.add_node("answer_gate", answer_gate_node)
    graph.add_node("guard", guard_node)
    graph.add_node("run_tools", run_tools_node)
    graph.add_node("critic", critic_node)
    graph.add_node("revise", revise_node)
    graph.add_node("verify", verify_node)
    graph.add_node("save_session", save_session)
    graph.add_node("final", build_final)

    graph.set_entry_point("parse_context")
    graph.add_edge("parse_context", "context_compaction")
    graph.add_edge("context_compaction", "analyze_code")
    # intent=analyze 直达返回结构化 JSON；否则进入后续问答链路
    graph.add_conditional_edges("analyze_code", _route_after_analyze, {"direct": END, "continue": "load_session"})
    graph.add_edge("load_session", "retrieve_knowledge")
    graph.add_edge("retrieve_knowledge", "build_context")
    graph.add_edge("build_context", "main_agent")
    # 图内真环：提案 → 门闩 → 执行 → 回提案
    graph.add_conditional_edges(
        "main_agent", _route_after_propose, {"answer_gate": "answer_gate", "guard": "guard"}
    )
    # 终答形态门闩：不合规就回提案节点重出终答（也消耗轮次预算，见 spec §4.9）
    graph.add_conditional_edges(
        "answer_gate", route_after_answer_gate, {"critic": "critic", "propose": "main_agent"}
    )
    graph.add_conditional_edges("guard", _route_after_guard, {"tools": "run_tools", "propose": "main_agent"})
    graph.add_edge("run_tools", "main_agent")
    graph.add_edge("critic", "revise")
    graph.add_edge("revise", "verify")
    graph.add_edge("verify", "save_session")
    graph.add_edge("save_session", "final")
    graph.add_edge("final", END)
    return graph
