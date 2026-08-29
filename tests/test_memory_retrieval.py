"""记忆检索上下文工程测试：memory_relevance 与 gather 相关性打分。"""

from graphs.javatutor.context_builder import gather, memory_relevance


def test_memory_relevance_ranks_relevant_higher():
    relevant = memory_relevance("用户想问 HashMap 哈希冲突的处理方式", 0.5, "HashMap 原理")
    irrelevant = memory_relevance("用户上次问冒泡排序的时间复杂度", 0.5, "HashMap 原理")
    assert relevant > irrelevant


def test_memory_relevance_importance_floor_keeps_high_importance():
    low = memory_relevance("完全不相关的句子 ABC", 0.0, "HashMap 原理")
    high = memory_relevance("完全不相关的句子 ABC", 1.0, "HashMap 原理")
    assert high > low


def test_memory_relevance_empty_query_does_not_crash():
    score = memory_relevance("content", 0.5, "")
    assert score >= 0.0


STATE = {
    "user_question": "HashMap 原理",
    "source_code": "public class A {}",
    "has_steps": True,
    "current_step_index": 1,
    "current_line": 4,
    "steps_count": 2,
}


def test_gather_scores_memory_by_query_relevance():
    memories = [
        {"content": "用户问 HashMap 哈希冲突", "importance": 0.4, "created_at": 1},
        {"content": "用户问冒泡排序的时间复杂度", "importance": 0.9, "created_at": 2},
    ]
    packets = gather(STATE, history=[], memories=memories)
    memory_packets = [p for p in packets if p.metadata.get("section") == "Memory"]
    assert len(memory_packets) == 2
    by_content = {p.content: p.relevance_score for p in memory_packets}
    assert by_content["用户问 HashMap 哈希冲突"] > by_content["用户问冒泡排序的时间复杂度"]


def test_gather_memory_packets_still_include_importance_section():
    packets = gather(STATE, history=[], memories=[{"content": "c", "importance": 0.8, "created_at": 1}])
    memory_packets = [p for p in packets if p.metadata.get("section") == "Memory"]
    assert len(memory_packets) == 1
    assert memory_packets[0].content == "c"


from graphs.javatutor import nodes


def test_load_session_requests_ten_candidates(monkeypatch):
    class FakeStore:
        def search(self, session_id, limit=10, min_importance=0.0):
            self.captured_limit = limit
            return []

    store = FakeStore()
    monkeypatch.setattr("learning.memory.get_memory_store", lambda: store)

    out = nodes.load_session({"user_id": "session-1"})
    assert store.captured_limit == 10
    assert out == {"memories": []}
