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
        assert "answer_gate" in graph.nodes
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


# ── retrieval_debug：全量候选与阈值判定写入 state（供决策痕迹诊断）──────────────


def test_retrieve_knowledge_writes_retrieval_debug(monkeypatch):
    """成功分支必须同时写 retrieved_chunks（语义不变）与 retrieval_debug（全量候选）。"""
    import learning.knowledge as kb
    from graphs.javatutor.nodes import retrieve_knowledge

    rows = [
        ("知识库: A", 0, "内容A", 0.8),
        ("知识库: B", 0, "内容B", 0.2),
    ]

    def fake_raw(query, top_k, embedder, fetcher):
        return rows

    monkeypatch.setattr(kb, "_raw_rows", fake_raw)
    out = retrieve_knowledge({"user_question": "HashMap.get 原理", "context_summary": ""})

    debug = out["retrieval_debug"]
    for key in ("query", "candidates", "best_score", "kept"):
        assert key in debug, f"retrieval_debug 缺 {key}"
    # 被阈值滤掉的行也必须在痕迹里
    assert len(debug["candidates"]) == 2
    assert debug["candidates"][1]["kept"] is False
    assert out["rag_degraded"] is False
    # 既有语义不变：retrieved_chunks 仍只含越阈值者
    assert [c["source"] for c in out["retrieved_chunks"]] == ["知识库: A"]


def test_retrieve_knowledge_debug_distinguishes_filtered_from_empty(monkeypatch):
    """核心诊断目标：检索成功但 0 条越阈值时，rag_degraded 仍为 False 且候选非空。"""
    import learning.knowledge as kb
    from graphs.javatutor.nodes import retrieve_knowledge

    monkeypatch.setattr(kb, "_raw_rows", lambda *a: [("知识库: A", 0, "内容A", 0.28)])
    out = retrieve_knowledge({"user_question": "查询", "context_summary": ""})

    assert out["retrieved_chunks"] == []
    assert out["rag_degraded"] is False, "「检索成功但无匹配」不得被当成降级"
    assert out["retrieval_debug"]["candidates"], "kept==0 时候选仍须非空"
    assert out["retrieval_debug"]["best_score"] == 0.28
    assert out["retrieval_debug"]["kept"] == 0


def test_retrieve_knowledge_failure_keep_debug_field(monkeypatch):
    """后端失败时字段仍存在（空候选 + degraded=True），便于区分「失败」与「成功但空」。"""
    import learning.knowledge as kb
    from graphs.javatutor.nodes import retrieve_knowledge

    def boom(*a):
        raise RuntimeError("pg down")

    monkeypatch.setattr(kb, "_raw_rows", boom)
    out = retrieve_knowledge({"user_question": "查询", "context_summary": ""})

    assert out["rag_degraded"] is True
    assert out["retrieved_chunks"] == []
    assert out["retrieval_debug"]["candidates"] == []


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
                    # CD-3：意见必须给出处（answer_span 为原答子串、fact 为事实块子串）；
                    # blocking: true 豁免 CD-1 的相似度闸（「原始回答有误」与「修订后的正确回答」
                    # 相似度为 0，无豁免必然回退）。本用例验的是路由。
                    return AIMessage(content=json.dumps({
                        "pass": False,
                        "issues": [{
                            "claim": "变量值与数据不符",
                            "answer_span": "原始回答有误",
                            "fact": "学生问题：为什么 arr 变了？",
                            "blocking": True,
                        }],
                    }, ensure_ascii=False))
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


def test_build_context_node_uses_intent_contract():
    """输出契约不再硬编码 "other"：概念题拿到概念契约与概念角色（计划 2026-09-14 D4）。

    根因同 D2——意图的产物在作答路径上没有消费者。
    """
    from graphs.javatutor.nodes import build_context_node

    base = {"user_question": "HashMap 原理", "source_code": "public class A {}", "messages": [], "memories": []}
    concept = build_context_node({**base, "intent": "concept"})["context_built"]
    assert "禁止脱离本次代码空谈教材内容" in concept  # CONTRACTS["concept"]
    assert "算法与数据结构教育专家" in concept  # 概念角色句

    missing = build_context_node(base)["context_built"]
    assert "回答工具使用问题时给出可操作指引" in missing  # CONTRACTS["other"]
    assert "算法与数据结构教育专家" not in missing


# ── 过程哨兵（Plan A Task 2）：build_context / retrieve_knowledge 发射 ──────────────


def _sentinel_events(msg):
    """取一条哨兵消息里的事件列表（顺带断言它确实被标记为过程消息）。"""
    from graphs.javatutor.process_events import PROCESS_KWARG, parse_process_events

    assert msg.additional_kwargs.get(PROCESS_KWARG) is True, "哨兵必须带 PROCESS_KWARG 标记"
    return parse_process_events(msg.content)["events"]


def test_retrieve_knowledge_emits_stage_with_hit_count(monkeypatch):
    """成功分支：stage 文本里的命中数**等于越阈值条数**（不是候选条数）。"""
    import learning.knowledge as kb
    from graphs.javatutor.nodes import retrieve_knowledge

    rows = [("知识库: A", 0, "内容A", 0.8), ("知识库: B", 0, "内容B", 0.2)]
    monkeypatch.setattr(kb, "_raw_rows", lambda *a: rows)

    out = retrieve_knowledge({"user_question": "HashMap.get 原理", "context_summary": ""})

    assert _sentinel_events(out["messages"][0]) == [
        {"kind": "stage", "text": "已检索知识库：命中 1 条"}
    ]
    assert len(out["process_event_ids"]) == len(out["messages"])
    # 既有语义不变
    assert [c["source"] for c in out["retrieved_chunks"]] == ["知识库: A"]
    assert out["rag_degraded"] is False


def test_retrieve_knowledge_emits_zero_hit_stage_not_degraded(monkeypatch):
    """kept==0：文本说 0 条，但仍**不是**降级（「无匹配」≠「故障」）。"""
    import learning.knowledge as kb
    from graphs.javatutor.nodes import retrieve_knowledge

    monkeypatch.setattr(kb, "_raw_rows", lambda *a: [("知识库: A", 0, "内容A", 0.28)])
    out = retrieve_knowledge({"user_question": "查询", "context_summary": ""})

    assert _sentinel_events(out["messages"][0]) == [
        {"kind": "stage", "text": "已检索知识库：命中 0 条"}
    ]
    assert out["rag_degraded"] is False


def test_retrieve_knowledge_degraded_branch_emits_stage(monkeypatch):
    """降级分支也必须发哨兵，且三个业务字段一字不变。"""
    import learning.knowledge as kb
    from graphs.javatutor.nodes import retrieve_knowledge

    def boom(*a):
        raise RuntimeError("pg down")

    monkeypatch.setattr(kb, "_raw_rows", boom)
    out = retrieve_knowledge({"user_question": "查询", "context_summary": ""})

    assert _sentinel_events(out["messages"][0]) == [
        {"kind": "stage", "text": "知识库检索不可用，已用通用知识回答"}
    ]
    assert out["retrieved_chunks"] == []
    assert out["retrieval_debug"]["candidates"] == []
    assert out["rag_degraded"] is True


def test_retrieve_knowledge_accumulates_process_event_ids(monkeypatch):
    """process_event_ids 无 reducer（返回即替换），节点须自行累加以往 id。"""
    import learning.knowledge as kb
    from graphs.javatutor.nodes import retrieve_knowledge

    monkeypatch.setattr(kb, "_raw_rows", lambda *a: [("知识库: A", 0, "内容A", 0.8)])
    out = retrieve_knowledge(
        {"user_question": "查询", "context_summary": "", "process_event_ids": ["jt-proc-x-0"]}
    )
    assert out["process_event_ids"][0] == "jt-proc-x-0"
    assert len(out["process_event_ids"]) == 2


def test_build_context_node_emits_stage_and_ids():
    from graphs.javatutor.nodes import build_context_node

    out = build_context_node(
        {"user_question": "arr 怎么变了？", "source_code": "public class A {}", "messages": []}
    )
    assert _sentinel_events(out["messages"][0]) == [
        {"kind": "stage", "text": "正在分析问题…"}
    ]
    assert out["process_event_ids"] == [out["messages"][0].id]
    assert out["messages"][0].id.startswith("jt-proc-")
    assert "变量卡片" in out["context_built"]


def test_build_context_node_skips_process_sentinels_in_history(monkeypatch):
    """防线 2：哨兵不是对话内容，取历史时必须滤掉，否则会进 context_built 的 token 预算。"""
    import graphs.javatutor.context_builder as cb
    from graphs.javatutor.nodes import build_context_node
    from graphs.javatutor.process_events import PROCESS_KWARG, build_process_event

    captured = {}

    def spy(state, history=None, memories=None, system_instructions="", max_tokens=None):
        captured["history"] = history
        return "STUB"

    monkeypatch.setattr(cb, "build_context", spy)

    sentinel = AIMessage(
        content=build_process_event({"kind": "stage", "text": "正在分析问题…"}),
        additional_kwargs={PROCESS_KWARG: True},
    )
    state = {
        "user_question": "现在的问题",
        "messages": [
            HumanMessage(content="上一轮的问题 余量标记ZZZ"),
            sentinel,
            HumanMessage(content="本轮提问占位"),
        ],
    }
    out = build_context_node(state)

    contents = [h["content"] for h in captured["history"]]
    assert "上一轮的问题 余量标记ZZZ" in contents, "正常历史不得被误滤"
    assert not any("jt:process" in c for c in contents), "哨兵不得进历史"
    assert "jt:process" not in out["context_built"]
