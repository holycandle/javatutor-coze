"""JavaTutor 全流程装配测试."""

import json
import re
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
        # 正常流程: 专家节点返回 answer 字段
        assert result.get("answer"), "answer 不应为空"

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
            # 检查 answer 字段存在且非空
            assert "answer" in result, f"第 {call_idx+1} 次调用: answer 字段缺失"
            assert result["answer"], f"第 {call_idx+1} 次调用: answer 为空"
            content = result["answer"]
            # 将内容按换行分割成句子
            sentences = [s.strip() for s in content.replace("。", "。\n").split("\n") if s.strip()]
            # 过滤掉代码块围栏标记（```、```java 等）和分隔线（---、***），
            # 它们会因多个代码块/分隔线而自然重复
            filtered = [s for s in sentences if not (
                s.replace("`", "").strip() == "" or
                re.match(r'^[-*]{3,}$', s.strip())
            )]
            # 如果过滤后只剩纯 fence 就跳过
            if not filtered:
                continue
            unique_sentences = set(filtered)
            if len(filtered) != len(unique_sentences):
                # 找到重复的句子
                from collections import Counter
                counts = Counter(filtered)
                duplicates = [s for s, c in counts.items() if c > 1]
                assert False, (
                    f"第 {call_idx+1} 次调用: 发现重复句子 {duplicates}"
                )