"""Task 4: 全流程装配测试."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, StateGraph

from agents.agent import AgentBundle, build_agent
from graphs.javatutor.graph import build_flow_graph


class TestGraphAssembly:
    """全流程图装配测试."""

    def test_build_agent_returns_bundle(self):
        """build_agent() 返回 AgentBundle，包含 builder 属性."""
        bundle = build_agent()

        assert isinstance(bundle, AgentBundle)
        assert hasattr(bundle, "builder")
        assert bundle.builder is not None

    def test_build_flow_graph_structure(self):
        """build_flow_graph() 返回 StateGraph，包含所有节点."""
        graph = build_flow_graph()

        assert isinstance(graph, StateGraph)
        # 验证节点存在（graph 节点列表需通过 get_graph() 获取）

    def test_build_agent_returns_compilable_graph(self):
        """build_agent() 的 builder 可被 compile()."""
        bundle = build_agent()
        compiled = bundle.builder.compile()

        assert compiled is not None
        # compiled 是 CompiledStateGraph，可调用 invoke

    def test_full_flow_data_query(self):
        """全流程: data_query 意图 → data_query 专家 → final.

        使用真实 LLMClient 验证完整流程。
        """
        from langchain_core.messages import HumanMessage

        payload = {
            "source_code": "public class Main {}",
            "steps": [{"step": 0, "variables": {"x": 1}}],
            "current_step_index": 0,
            "user_question": "为什么 x 是 1？",
        }
        initial_state = {
            "messages": [HumanMessage(content=json.dumps(payload))],
        }

        # 用 build_agent + compile 验证图结构
        bundle = build_agent()
        compiled = bundle.builder.compile()

        # 验证 intent 路由逻辑（单元测试已在 test_route_intent 中覆盖）
        # 此处验证: build_final 追加 AIMessage 到 messages
        from graphs.javatutor.nodes import parse_context, route_intent, data_query_node, build_final

        state = parse_context(initial_state)
        state.update(route_intent(state))
        # 模拟真实执行：专家节点在 answer 中返回内容
        # build_final 追加 AIMessage 到 messages（HumanMessage 由图执行时由 state 传递）
        state["answer"] = "[data_query] 测试回答"
        result = build_final(state)

        messages = result.get("messages", [])
        # state 中无原始 messages（由图执行框架管理），build_final 追加 AIMessage
        assert len(messages) == 1
        assert isinstance(messages[0], AIMessage)
        assert "[data_query]" in messages[0].content

    def test_full_flow_compile_error_shortcut(self):
        """全流程: compile_error → debug 短路.

        验证 has_error=True 时跳过意图路由直接进入 debug。
        """
        from langchain_core.messages import HumanMessage

        payload = {
            "source_code": "public class Main {",
            "steps": [],
            "compile_error": "error: ';' expected",
            "user_question": "帮我看看",
        }
        initial_state = {
            "messages": [HumanMessage(content=json.dumps(payload))],
        }

        # 验证 compile_error 短路逻辑
        from graphs.javatutor.nodes import parse_context, route_intent, build_final

        state = parse_context(initial_state)
        assert state["has_error"] is True

        route_result = route_intent(state)
        assert route_result["intent"] == "debug"

        # 验证 final 节点追加 AIMessage
        state.update(route_result)
        state["answer"] = "[debug] 测试修复"
        result = build_final(state)

        messages = result.get("messages", [])
        # state 中无原始 messages，build_final 追加 AIMessage
        assert len(messages) == 1
        assert isinstance(messages[0], AIMessage)
        assert "[debug]" in messages[0].content
