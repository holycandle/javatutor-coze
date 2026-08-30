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


def test_build_final_records_fetch_execution_context_in_tool_calls():
    """有 run_id 时，fetch_execution_context 应记录进决策痕迹的 tool_calls（排在最前）。"""
    state = {
        "answer": "回答",
        "run_id": "run-1",
        "fetch_context_failed": False,
        "fetch_context_latency_ms": 12.3,
        "intent": "data_query",
        "retrieved_chunks": [],
        "tool_calls": [],
    }
    out = build_final(state)
    trace = out["decision_trace"]
    assert trace["tool_calls"][0]["tool"] == "fetch_execution_context"
    assert trace["tool_calls"][0]["args"]["run_id"] == "run-1"


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
