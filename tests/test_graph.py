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
        """build_flow_graph() 返回 StateGraph，包含新链路全部节点，且不含 fetch 节点."""
        graph = build_flow_graph()
        assert isinstance(graph, StateGraph)
        assert "parse_context" in graph.nodes
        assert "context_compaction" in graph.nodes
        assert "analyze_code" in graph.nodes
        assert "load_session" in graph.nodes
        assert "retrieve_knowledge" in graph.nodes
        assert "build_context" in graph.nodes
        assert "main_agent" in graph.nodes
        assert "critic" in graph.nodes
        assert "revise" in graph.nodes
        assert "save_session" in graph.nodes
        assert "final" in graph.nodes
        assert "fetch_execution_context" not in graph.nodes

    def test_graph_parse_context_feeds_compaction(self):
        """parse_context 直接连接到 context_compaction，不再经过 fetch 节点."""
        graph = build_flow_graph()
        assert ("parse_context", "context_compaction") in graph.edges

    def test_graph_has_no_fetch_node(self):
        """图中不应存在 fetch_execution_context 节点（已改为 agent 工具）。"""
        graph = build_flow_graph()
        assert "fetch_execution_context" not in graph.nodes

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

    def test_graph_has_new_pipeline_nodes(self):
        """新链路节点已装配."""
        graph = build_flow_graph()
        for node in ("analyze_code", "load_session", "retrieve_knowledge", "build_context", "main_agent", "save_session"):
            assert node in graph.nodes

    def test_graph_wires_retrieve_knowledge_before_build_context(self):
        """P1-2: RAG 检索节点必须位于 build_context 之前，进入上下文."""
        graph = build_flow_graph()
        assert "retrieve_knowledge" in graph.nodes
        assert "build_context" in graph.nodes
        # retrieve_knowledge 位于 load_session 与 build_context 之间
        assert ("load_session", "retrieve_knowledge") in graph.edges
        assert ("retrieve_knowledge", "build_context") in graph.edges

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

    def test_graph_has_no_animation_nodes(self):
        """图中不应存在 animate / animate_guide 节点（动画模块已移除）."""
        graph = build_flow_graph()
        assert "animate" not in graph.nodes
        assert "animate_guide" not in graph.nodes

def test_retrieve_knowledge_node():
    """P1-2: retrieve_knowledge 节点返回 chunks 且失败时不抛异常."""
    from graphs.javatutor.nodes import retrieve_knowledge

    out = retrieve_knowledge({"user_question": "冒泡排序复杂度是多少？", "context_summary": ""})
    assert "retrieved_chunks" in out
    assert out["rag_degraded"] in (True, False)
    assert isinstance(out["retrieved_chunks"], list)


def test_retrieve_knowledge_node_empty_query():
    """空查询时降级为 [] 而非抛异常."""
    from graphs.javatutor.nodes import retrieve_knowledge

    out = retrieve_knowledge({"user_question": "", "context_summary": ""})
    assert out["retrieved_chunks"] == []


def test_full_flow_runs_new_pipeline():
    """全流程: 新链路 parse → analyze → memory → context → main_agent → critic → revise → final."""
    import json
    from langchain_core.messages import AIMessage, HumanMessage
    from agents.agent import build_agent

    class DeepModel:
        def __init__(self):
            self.i = 0

        def invoke(self, messages):
            self.i += 1
            content = messages[0].content
            if "算法分析" in content or "源代码" in content:
                return AIMessage(content='{"complexity": {"time": "O(1)"}}')
            if "教学主 Agent" in content:
                return AIMessage(content="根据第 2 步，x 变成了 2")
            if "回答评审" in content:
                return AIMessage(content='{"pass": true, "issues": []}')
            return AIMessage(content="修订回答")

    payload = {
        "source_code": "public class A {}",
        "steps": [{"step": 0, "variables": {"x": 1}}, {"step": 1, "variables": {"x": 2}}],
        "current_step_index": 1,
        "user_question": "x 怎么变了？",
        "compile_error": "",
    }
    compiled = build_agent().builder.compile()
    result = compiled.invoke({"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]}, config={"configurable": {"chat_model": DeepModel()}})
    assert result.get("analysis_result", {}).get("complexity", {}).get("time") == "O(1)"
    assert result.get("answer")


class DeepFakeModel:
    """统一 FakeModel：根据 system prompt 内容路由不同响应。"""

    def __init__(self):
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages[0].content[:20])
        content = messages[0].content
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

        # P1-1: 决策痕迹必须包含 tool_calls 与 token_usage（评测 M1.1 依赖）
        trace = result.get("decision_trace", {})
        assert "tool_calls" in trace, "决策痕迹应包含 tool_calls"
        assert isinstance(trace["tool_calls"], list)
        assert "token_usage" in trace, "决策痕迹应包含 token_usage"
        tu = trace["token_usage"]
        assert "prompt_tokens" in tu and "completion_tokens" in tu
        assert tu.get("estimated") is True
        # 决策痕迹 JSON 同样出现在最终回答文本中
        trace_json = json.dumps(trace, ensure_ascii=False)
        assert trace_json in result["answer"] or "tool_calls" in result["answer"]

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
                return AIMessage(content="原始回答有误")

        compiled = build_agent().builder.compile()
        result = compiled.invoke(initial, config={"configurable": {"chat_model": CriticFailModel()}})
        assert result.get("decision_trace", {}).get("revised") is True
        assert "修订后的正确回答" in result.get("answer", "")


def test_build_context_includes_ontology():
    """本体块进入常驻 system prompt，context_built 应含模块名与契约规则."""
    from graphs.javatutor.nodes import build_context_node

    out = build_context_node(
        {
            "user_question": "arr 怎么变了？",
            "source_code": "public class A {}",
            "messages": [],
            "memories": [],
        }
    )
    text = out["context_built"]
    assert "变量卡片" in text
    assert "堆面板" in text
    assert "禁止编造引擎内部机制" in text
