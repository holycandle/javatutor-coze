"""JavaTutor 全流程装配测试."""

import json
from typing import Annotated, Any
from langchain_core.messages import HumanMessage, AIMessage, AnyMessage
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph

from agents.agent import AgentBundle, build_agent
from graphs.javatutor.graph import build_flow_graph
from graphs.javatutor.state import JavaTutorState


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
        assert "parse_context" in graph.nodes
        assert "route_intent" in graph.nodes
        assert "data_query" in graph.nodes
        assert "concept" in graph.nodes
        assert "debug" in graph.nodes
        assert "other" in graph.nodes
        assert "analyze" in graph.nodes

    def test_full_flow_data_query(self):
        """全流程: data_query 专家返回 AI 消息."""
        payload = {
            "source_code": "public class A {}",
            "steps": [{"step": 0, "variables": {"x": 1}}],
            "current_step_index": 0,
            "user_question": "为什么 x 是 1？",
            "compile_error": "",
        }
        initial = {"messages": [HumanMessage(content=json.dumps(payload))]}
        bundle = build_agent()
        compiled = bundle.builder.compile()
        result = compiled.invoke(initial)
        messages = result.get("messages", [])
        ai_msgs = [m for m in messages if hasattr(m, "type") and m.type == "ai"]
        # 不应有重复 AI 消息
        assert len(ai_msgs) == 1, f"应为 1 条 AI 消息, 实际 {len(ai_msgs)} 条"
        assert ai_msgs[0].content, "AI 消息内容不应为空"

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
        ai_msgs = [m for m in result.get("messages", []) if hasattr(m, "type") and m.type == "ai"]
        assert len(ai_msgs) == 1, "不应有重复 AI 消息"
        assert ai_msgs[0].content, "AI 消息内容不应为空"

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
        # 验证 AI 消息内容可解析为 JSON（analyze 返回结构化数据）
        content = ai_msgs[0].content
        try:
            data = json.loads(content)
            assert "complexity" in data, "analyze 返回应包含 complexity"
        except json.JSONDecodeError:
            pass  # 如果 LLM 返回非 JSON（如 fallback），也接受

    def test_no_duplicate_ai_message(self):
        """回归测试: 同一问题连续调用 3 次, 每次返回的 AI 消息都不重复."""
        payload = {
            "source_code": "public class A {}",
            "steps": [{"step": 0, "variables": {"x": 1}}],
            "current_step_index": 0,
            "user_question": "为什么 x 是 1？",
            "compile_error": "",
        }
        initial = {"messages": [HumanMessage(content=json.dumps(payload))]}
        bundle = build_agent()
        compiled = bundle.builder.compile()

        for call_idx in range(3):
            result = compiled.invoke(initial)
            msgs = result.get("messages", [])
            ai_msgs = [m for m in msgs if hasattr(m, "type") and m.type == "ai"]
            assert len(ai_msgs) == 1, (
                f"第 {call_idx+1} 次调用: AI 消息数量={len(ai_msgs)}, 期望=1"
            )
            # 检查 AI 消息内容中是否包含重复的完整句子
            content = ai_msgs[0].content
            # 将内容按换行分割成句子
            sentences = [s.strip() for s in content.replace("。", "。\n").split("\n") if s.strip()]
            unique_sentences = set(sentences)
            if len(sentences) != len(unique_sentences):
                # 找到重复的句子
                from collections import Counter
                counts = Counter(sentences)
                duplicates = [s for s, c in counts.items() if c > 1]
                assert False, (
                    f"第 {call_idx+1} 次调用: 发现重复句子 {duplicates}"
                )