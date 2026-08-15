"""build_final 代码引用清理与决策痕迹测试。"""

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
