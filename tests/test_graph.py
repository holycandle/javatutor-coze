"""JavaTutor 全流程装配测试."""

import json
import re
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph

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
        """build_flow_graph() 返回 StateGraph，包含所有节点（含深化节点）."""
        graph = build_flow_graph()
        assert isinstance(graph, StateGraph)
        assert "parse_context" in graph.nodes
        assert "context_compaction" in graph.nodes
        assert "route_intent" in graph.nodes
        assert "retrieve_knowledge" in graph.nodes
        assert "data_query" in graph.nodes
        assert "concept" in graph.nodes
        assert "debug" in graph.nodes
        assert "animate" in graph.nodes
        assert "animate_guide" in graph.nodes
        assert "other" in graph.nodes
        assert "analyze" in graph.nodes
        assert "critic" in graph.nodes
        assert "revise" in graph.nodes
        assert "final" in graph.nodes

    def test_full_flow_compile_error(self):
        """全流程: compile_error 非空时路由到 debug 专家."""
        payload = {
            "source_code": "public class A {",
            "steps": [],
            "current_step_index": 0,
            "user_question": "为什么报错？",
            "compile_error": "Syntax error, insert '}'",
        }
        initial = {"messages": [HumanMessage(content=json.dumps(payload))]}
        bundle = build_agent()
        compiled = bundle.builder.compile()
        result = compiled.invoke(initial)
        assert result.get("intent") == "debug", f"期望 intent=debug, 实际={result.get('intent')}"
        assert result.get("answer"), "answer 不应为空"

    def test_full_flow_analyze(self):
        """全流程: intent=analyze 时路由到 analyze 专家, 返回结构化 JSON."""
        payload = {
            "source_code": "public class BubbleSort { public static void sort(int[] arr) { for (int i = 0; i < arr.length; i++) { for (int j = 0; j < arr.length - i - 1; j++) { if (arr[j] > arr[j + 1]) { int tmp = arr[j]; arr[j] = arr[j + 1]; arr[j + 1] = tmp; } } } } }",
            "steps": [],
            "current_step_index": 0,
            "user_question": "",
            "compile_error": "",
            "intent": "analyze",
        }
        initial = {"messages": [HumanMessage(content=json.dumps(payload))]}
        bundle = build_agent()
        compiled = bundle.builder.compile()
        result = compiled.invoke(initial)
        assert result.get("intent") == "analyze", f"期望 intent=analyze, 实际={result.get('intent')}"
        ai_msgs = [m for m in result.get("messages", []) if hasattr(m, "type") and m.type == "ai"]
        assert len(ai_msgs) == 1, "不应有重复 AI 消息"
        content = ai_msgs[0].content
        try:
            data = json.loads(content)
            assert "complexity" in data, "analyze 返回应包含 complexity"
        except json.JSONDecodeError:
            pass

    def test_full_flow_animate_explicit(self):
        """全流程: intent=animate 时路由到 animate 专家, 返回 SVG."""
        payload = {
            "source_code": "public class BubbleSort {}",
            "steps": [{"step": 0, "variables": {"arr": [5, 3, 1]}}, {"step": 1, "variables": {"arr": [3, 5, 1]}}],
            "current_step_index": 1,
            "user_question": "",
            "compile_error": "",
            "intent": "animate",
        }
        initial = {"messages": [HumanMessage(content=json.dumps(payload))]}
        compiled = build_agent().builder.compile()
        result = compiled.invoke(initial)
        ai_msgs = [m for m in result.get("messages", []) if hasattr(m, "type") and m.type == "ai"]
        assert ai_msgs, "应有 AI 消息"
        assert ai_msgs[-1].content.startswith("<svg"), "animate 应返回纯 SVG"
        assert "<animate" in ai_msgs[-1].content, "SVG 应包含动画"
        assert result.get("svg_text", "").startswith("<svg"), "svg_text 应为 SVG"

    def test_full_flow_animate_guide_explicit(self):
        """全流程: 显式 intent=animate_guide 返回引导文案."""
        payload = {
            "source_code": "public class BubbleSort {}",
            "steps": [{"step": 0, "variables": {"arr": [5, 3, 1]}}],
            "current_step_index": 0,
            "user_question": "",
            "compile_error": "",
            "intent": "animate_guide",
        }
        initial = {"messages": [HumanMessage(content=json.dumps(payload))]}
        compiled = build_agent().builder.compile()
        result = compiled.invoke(initial)
        assert result.get("intent") == "animate_guide"
        ai_msgs = [m for m in result.get("messages", []) if hasattr(m, "type") and m.type == "ai"]
        assert ai_msgs and "生成动画" in ai_msgs[-1].content


class DeepFakeModel:
    """统一 FakeModel：根据 system prompt 内容路由不同响应。"""

    def __init__(self):
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages[0].content[:20])
        content = messages[0].content
        if "意图分类器" in content:
            return AIMessage(content='{"intent":"data_query","confidence":0.9,"reason":"追问变量"}')
        if "回答评审" in content:
            return AIMessage(content='{"pass": true, "issues": []}')
        if "回答修订者" in content:
            return AIMessage(content="修订后的回答")
        # 专家节点
        return AIMessage(content="根据第 2 步，arr[1] 变成了 5")


class TestDeepFlow:
    """深化链路集成测试。"""

    def test_full_flow_generate_review_revise_trace(self):
        """全流程: 生成 → 评审 → 修订 → 决策痕迹。"""
        payload = {
            "source_code": "public class A {}",
            "steps": [{"step": 1, "variables": {"arr": [3, 5, 1]}}],
            "current_step_index": 1,
            "user_question": "为什么 arr 变了？",
            "compile_error": "",
        }
        initial = {"messages": [HumanMessage(content=json.dumps(payload))]}
        compiled = build_agent().builder.compile()
        model = DeepFakeModel()
        result = compiled.invoke(initial, config={"configurable": {"chat_model": model}})

        # build_final 返回 answer（含决策痕迹）和 decision_trace
        assert "answer" in result, "应有 answer 字段"
        assert "【决策痕迹】" in result["answer"], "回答应包含决策痕迹"
        assert result.get("decision_trace", {}).get("intent") == "data_query"
        assert result.get("decision_trace", {}).get("critic_passed") is True

    def test_deep_flow_critic_fails_triggers_revise(self):
        """评审不通过时触发修订。"""
        payload = {
            "source_code": "public class A {}",
            "steps": [{"step": 1, "variables": {"arr": [3, 5, 1]}}],
            "current_step_index": 1,
            "user_question": "为什么 arr 变了？",
            "compile_error": "",
        }
        initial = {"messages": [HumanMessage(content=json.dumps(payload))]}

        class CriticFailModel(DeepFakeModel):
            def invoke(self, messages):
                content = messages[0].content
                if "回答评审" in content:
                    return AIMessage(content='{"pass": false, "issues": ["变量值与数据不符"]}')
                if "回答修订者" in content:
                    return AIMessage(content="修订后的正确回答")
                if "意图分类器" in content:
                    return AIMessage(content='{"intent":"data_query","confidence":0.9,"reason":"追问"}')
                return AIMessage(content="原始回答有误")

        compiled = build_agent().builder.compile()
        result = compiled.invoke(initial, config={"configurable": {"chat_model": CriticFailModel()}})
        assert result.get("decision_trace", {}).get("revised") is True
        assert "修订后的正确回答" in result.get("answer", "")
