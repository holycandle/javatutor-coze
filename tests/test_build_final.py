"""build_final 代码引用清理与决策痕迹测试。"""

import time

from graphs.javatutor.nodes import _normalize_md, _sanitize_code_quotes, build_final


def test_normalize_md_keeps_truncated_fence_intact():
    raw = "```jav\na\nint n = arr.length;\n```"
    assert "```jav" in _normalize_md(raw)


def test_sanitize_normalizes_truncated_java_language():
    raw = "```jav\nint n = arr.length;\n```"
    cleaned = _sanitize_code_quotes(raw)
    assert cleaned == "```java\nint n = arr.length;\n```"


def test_sanitize_removes_stray_single_char_line():
    raw = "```jav\na\nint n = arr.length;\n```"
    cleaned = _sanitize_code_quotes(raw)
    assert "```java\nint n = arr.length;" in cleaned
    assert "\na\n" not in cleaned


def test_sanitize_keeps_normal_code_block():
    raw = "```java\nint n = arr.length;\n```"
    assert _sanitize_code_quotes(raw) == raw


def test_build_final_applies_sanitizer_and_trace():
    state = {
        "answer": "当前执行到第 4 行：\n```jav\na\nint n = arr.length;\n```",
        "intent": "data_query",
        "intent_confidence": 1.0,
        "revised": False,
        "critic_passed": True,
        "fallback_reason": "",
        "rag_degraded": False,
        "critic_skipped": False,
        "revise_skipped": False,
        "compaction_mode": "none",
        "tool_calls": [{"tool": "step_facts", "args": {"step_index": 1, "line": 4}}],
        "retrieved_chunks": [],
    }
    out = build_final(state)
    content = out["messages"][0].content
    assert "```java\nint n = arr.length;" in content
    assert "【决策痕迹】" in content
    assert "step_facts" in content
    assert isinstance(out["decision_trace"]["latency_ms"], (int, float))
    assert out["decision_trace"]["latency_ms"] >= 0


def test_latency_ms_uses_request_started_at():
    """request_started_at 已声明进 schema 并被持久化后，latency_ms 应为正数而非恒为 0。"""
    state = {
        "request_started_at": time.time() - 1.5,
        "intent": "data_query",
        "intent_confidence": 0.9,
        "revised": False,
        "critic_passed": True,
        "retrieved_chunks": [],
    }
    out = build_final(state)
    latency = out["decision_trace"]["latency_ms"]
    assert isinstance(latency, (int, float))
    assert latency > 0, f"latency_ms 应为正数，实际 {latency}"


def test_build_final_trace_includes_fetch_metrics():
    state = {
        "answer": "回答",
        "run_id": "run-1",
        "fetch_context_failed": False,
        "fetch_context_latency_ms": 12.3,
        "fetch_context_error": "",
        "intent": "data_query",
        "retrieved_chunks": [],
        "tool_calls": [],
    }
    out = build_final(state)
    trace = out["decision_trace"]
    assert trace["run_id"] == "run-1"
    assert trace["fetch_context_failed"] is False
    assert trace["fetch_context_latency_ms"] == 12.3
    assert trace["fetch_context_error"] == ""


def test_build_final_preserves_tool_calls_without_injecting_fetch():
    """有 run_id 时也不再手动补记 fetch_execution_context；tool_calls 由 main_agent 真实产生。"""
    state = {
        "answer": "回答",
        "run_id": "run-1",
        "fetch_context_failed": False,
        "fetch_context_latency_ms": 12.3,
        "intent": "data_query",
        "retrieved_chunks": [],
        "tool_calls": [{"tool": "step_facts", "args": {"step_index": 0, "line": 1}}],
    }
    out = build_final(state)
    trace = out["decision_trace"]
    assert trace["tool_calls"] == [{"tool": "step_facts", "args": {"step_index": 0, "line": 1}}]


def test_build_final_no_run_id_does_not_record_fetch_tool():
    """无 run_id 时不记录 fetch_execution_context，保留原有的 LLM 工具调用。"""
    state = {
        "answer": "回答",
        "intent": "data_query",
        "retrieved_chunks": [],
        "tool_calls": [{"tool": "step_facts", "args": {"step_index": 1}}],
    }
    out = build_final(state)
    tools = out["decision_trace"]["tool_calls"]
    assert tools == [{"tool": "step_facts", "args": {"step_index": 1}}]


# ── 新增三键：retrieval / reasoning / sources 增强 ────────────────────────────


def _debug_state(**overrides):
    state = {
        "answer": "回答",
        "intent": "concept",
        "retrieved_chunks": [],
        "retrieval_debug": {
            "query": "HashMap 的 get 原理",
            "top_k": 3,
            "threshold": 0.3,
            "candidates": [
                {
                    "source": "知识库: HashMap.get",
                    "chunk_index": 0,
                    "content": "HashMap.get\n关键词: hash",
                    "score": 0.28,
                    "kept": False,
                }
            ],
            "best_score": 0.28,
            "kept": 0,
        },
    }
    state.update(overrides)
    return state


def test_build_final_trace_includes_retrieval():
    trace = build_final(_debug_state())["decision_trace"]
    retrieval = trace["retrieval"]
    for key in ("query", "top_k", "threshold", "candidates", "best_score", "kept"):
        assert key in retrieval, f"retrieval 缺 {key}"
    candidate = retrieval["candidates"][0]
    for key in ("source", "chunk_index", "score", "preview", "kept"):
        assert key in candidate, f"candidate 缺 {key}"
    assert "content" not in candidate, "候选不该带完整 content（体积）"
    assert candidate["preview"].startswith("HashMap.get")


def test_retrieval_candidate_preview_truncated_flag():
    long_content = "x" * 400
    state = _debug_state()
    state["retrieval_debug"]["candidates"][0]["content"] = long_content
    candidate = build_final(state)["decision_trace"]["retrieval"]["candidates"][0]
    assert len(candidate["preview"]) == 300
    assert candidate["truncated"] is True


def test_retrieval_kept_zero_does_not_degrade():
    """核心诊断信号：有候选但 kept==0 时 rag_degraded 仍为 False。"""
    trace = build_final(_debug_state())["decision_trace"]
    assert trace["rag_degraded"] is False
    assert trace["retrieval"]["kept"] == 0


def test_build_final_trace_includes_reasoning():
    from langchain_core.messages import AIMessage, HumanMessage

    state = _debug_state(
        agent_messages=[
            AIMessage(content='{"tool":"fetch_execution_context","args":{}}'),
            HumanMessage(content="观察"),
            AIMessage(content="想法B"),
        ],
        # 只有真的执行过的工具名才进 reasoning.tool_calls
        step_records=[{"tool": "fetch_execution_context", "status": "ok"}],
    )
    trace = build_final(state)["decision_trace"]
    assert len(trace["reasoning"]) == 2
    assert trace["reasoning"][0]["tool_calls"] == ["fetch_execution_context"]
    # 提案轮的原始 JSON 不进 content（不得泄露红线）
    assert "fetch_execution_context" not in trace["reasoning"][0]["content"]
    assert trace["reasoning"][1]["content"] == "想法B"
    assert trace["reasoning_truncated"] is False


def test_build_final_denied_tool_not_in_reasoning():
    """被拒的提案不进 reasoning.tool_calls（与 tool_calls 同口径，守护不得泄露红线）。"""
    from langchain_core.messages import AIMessage

    state = _debug_state(
        agent_messages=[AIMessage(content='{"tool":"no_such_tool","args":{}}')],
        step_records=[{"tool": "no_such_tool", "status": "denied"}],
    )
    trace = build_final(state)["decision_trace"]
    assert trace["reasoning"][0]["tool_calls"] == []


def test_build_final_reasoning_truncated_flag():
    from langchain_core.messages import AIMessage

    state = _debug_state(agent_messages=[AIMessage(content="x" * 2000)])
    trace = build_final(state)["decision_trace"]
    assert trace["reasoning_truncated"] is True
    assert len(trace["reasoning"][0]["content"]) == 1200


def test_build_final_defaults_when_state_missing_keys():
    """缺 retrieval_debug / agent_messages 时两个键恒存在（消费方可无条件读）。"""
    state = {"answer": "回答", "intent": "other", "retrieved_chunks": []}
    trace = build_final(state)["decision_trace"]
    assert trace["retrieval"] == {"candidates": [], "best_score": 0.0, "kept": 0}
    assert trace["reasoning"] == []
    assert trace["reasoning_truncated"] is False


def test_sources_gains_new_keys_without_changing_existing():
    """sources 只增键：source / score 不变，新增 chunk_index / content_preview。"""
    state = {
        "answer": "回答",
        "intent": "concept",
        "retrieved_chunks": [
            {"source": "知识库: A", "chunk_index": 2, "content": "内容A", "score": 0.81}
        ],
    }
    sources = build_final(state)["decision_trace"]["sources"]
    assert sources[0]["source"] == "知识库: A"
    assert sources[0]["score"] == 0.81
    assert sources[0]["chunk_index"] == 2
    assert sources[0]["content_preview"] == "内容A"


def test_redact_denied_tools_replaces_name_in_trace_json():
    from graphs.javatutor.nodes import _redact_denied_tools

    out = _redact_denied_tools('{"tool":"no_such_tool","other":1}', {"no_such_tool"})
    assert "no_such_tool" not in out
    assert '"other":1' in out


def test_redact_denied_tools_ignores_empty_names():
    """空串不得参与替换——它匹配一切，会把整个 JSON 打成筛子。"""
    from graphs.javatutor.nodes import _redact_denied_tools

    src = '{"tool":"step_facts","args":{}}'
    assert _redact_denied_tools(src, {""}) == src


def test_build_final_redacts_denied_tool_name_from_answer():
    """终局兜底：被拒工具名不得出现在拼进 answer 的 trace 段里。

    即便 ``build_reasoning`` 的逐条剥离被将来某个新分支绕过，这一道仍守住
    「回答里不出现被拒工具名」。``decision_trace``（结构化）保留真值，只有 answer 文本剔除。
    """
    from langchain_core.messages import AIMessage

    state = _debug_state(
        agent_messages=[AIMessage(content='{"tool":"no_such_tool","args":[1,2]}')],
        step_records=[{"tool": "no_such_tool", "status": "invalid_args"}],
    )
    out = build_final(state)
    assert "no_such_tool" not in out["answer"]
    assert "【决策痕迹】" in out["answer"]
    # 结构化 trace 不被改写：剔除只作用于用户可见文本
    assert out["decision_trace"]["reasoning"][0]["content"] == ""


# === CD-6 可观测性：评审意见与修订结局进痕迹 ===


def test_trace_has_critic_issues_defaults():
    """缺省：没有评审反馈时 `critic_issues` 是空列表（不是缺键、不是字符串）。"""
    trace = build_final(_debug_state())["decision_trace"]
    assert trace["critic_issues"] == []
    assert trace["revise_outcome"] == "skipped"
    assert trace["revise_revert_reason"] == ""


def test_trace_exposes_validated_critic_issues():
    """痕迹里的意见必须与流水线实际据以行动的**同一份**（`critic_feedback`）逐字对得上。"""
    import json

    feedback = json.dumps(
        [{"claim": "变量值 8 与数据不符", "answer_span": "arr[1] 变成了 8",
          "fact": "学生问题：为什么 arr 变了？", "blocking": True}],
        ensure_ascii=False,
    )
    out = build_final(_debug_state(critic_passed=False, critic_feedback=feedback))
    trace = out["decision_trace"]
    assert trace["critic_issues"][0]["claim"] == "变量值 8 与数据不符"
    assert trace["critic_issues"][0]["answer_span"] == "arr[1] 变成了 8"
    assert trace["critic_issues"][0]["blocking"] is True
    # 端到端产物：痕迹 JSON 是拼进 answer 的，字段必须真的出现在**用户可见文本**里
    assert '"critic_issues"' in out["answer"]
    assert "变量值 8 与数据不符" in out["answer"]


def test_trace_truncates_long_critic_spans():
    """痕迹随回答进客户端，逐字带上整段原答会把痕迹撑成回答的几倍大 ⇒ 截断。"""
    import json

    from graphs.javatutor.nodes import _PREVIEW_CHARS

    long_text = "甲" * (_PREVIEW_CHARS * 3)
    feedback = json.dumps(
        [{"claim": long_text, "answer_span": long_text, "fact": long_text}], ensure_ascii=False
    )
    issue = build_final(_debug_state(critic_feedback=feedback))["decision_trace"]["critic_issues"][0]
    assert len(issue["claim"]) == _PREVIEW_CHARS
    assert len(issue["answer_span"]) == _PREVIEW_CHARS


def test_trace_records_revert_reason():
    state = _debug_state(revised=False, revise_outcome="reverted", revise_revert_reason="similarity")
    trace = build_final(state)["decision_trace"]
    assert trace["revise_outcome"] == "reverted"
    assert trace["revise_revert_reason"] == "similarity"


def test_trace_tolerates_bad_critic_feedback():
    """`critic_feedback` 是 LLM 出的字符串，坏 JSON 不得让 build_final 崩。"""
    trace = build_final(_debug_state(critic_feedback="{ 不是 JSON"))["decision_trace"]
    assert trace["critic_issues"] == []
