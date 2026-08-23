"""Task 6: GSSC 上下文构建器测试."""

from graphs.javatutor.context_builder import build_context, gather, select, structure


STATE = {
    "user_question": "HashMap 原理",
    "source_code": "public class A {}",
    "has_steps": True,
    "current_step_index": 1,
    "current_line": 4,
    "steps_count": 2,
    "analysis_result": {"complexity": {"time": "O(1)"}},
    "retrieved_chunks": [{"source": "知识库: HashMap", "content": "基于哈希表", "score": 0.9}],
}


def test_gather_includes_all_sources():
    packets = gather(STATE, history=[{"role": "user", "content": "你好"}], memories=[{"content": "上次分析", "importance": 0.85, "created_at": 1}])
    sections = [p.metadata.get("section") for p in packets]
    assert "Task" in sections
    assert "Evidence" in sections
    assert "Memory" in sections
    assert "Context" in sections


def test_select_respects_budget():
    packets = gather(STATE, history=[], memories=[])
    chosen = select(packets, STATE["user_question"], max_tokens=200)
    assert chosen
    assert sum(p.token_count for p in chosen) <= 200 * 0.8 + max(p.token_count for p in chosen)


def test_structure_has_sections():
    packets = gather(STATE, history=[], memories=[])
    text = structure(select(packets, STATE["user_question"]), system_instructions="你是助教")
    assert "[Role & Policies]" in text
    assert "[Evidence]" in text


def test_build_context_returns_compressed_text():
    text = build_context(STATE, history=[], memories=[], system_instructions="你是助教", max_tokens=500)
    assert "HashMap" in text


def test_gather_includes_current_step_position():
    packets = gather(STATE, history=[], memories=[])
    combined = "\n".join(p.content for p in packets)
    assert "当前执行位置" in combined
    assert "当前步骤索引: 1" in combined
    assert "总步骤数: 2" in combined


def test_gather_includes_run_context_memory():
    state = {
        **STATE,
        "run_context_memory": {
            "run_id": "run-1",
            "code_hash": "abc123",
            "steps_count": 2,
            "current_step_index": 1,
            "current_line": 4,
            "algorithm_tags": ["遍历"],
        },
    }
    packets = gather(state, history=[], memories=[])
    combined = "\n".join(p.content for p in packets)
    assert "运行上下文摘要" in combined
    assert "code_hash" in combined
