from learning.knowledge import _entry_text, chunk_text, search_chunks


def test_chunk_text_creates_overlapping_chunks():
    chunks = chunk_text("0123456789", "知识库: 测试", chunk_size=5, overlap=2)
    assert len(chunks) >= 2
    assert chunks[0]["source"] == "知识库: 测试"
    assert chunks[0]["chunk_index"] == 0


def test_search_filters_by_threshold_and_top_k():
    def fake_embed(texts):
        return [[1.0]]

    def fake_fetch(vector, top_k):
        return [
            ("知识库: A", 0, "内容A", 0.8),
            ("知识库: B", 0, "内容B", 0.2),
        ]

    result = search_chunks("查询", top_k=3, threshold=0.5, embedder=fake_embed, fetcher=fake_fetch)
    assert len(result) == 1
    assert result[0]["source"] == "知识库: A"


def test_search_empty_query():
    assert search_chunks("") == []


def test_entry_text_includes_rich_fields():
    entry = {
        "title": "Arrays.sort",
        "keywords": ["arrays", "sort"],
        "category": "数组",
        "explanation": "对数组升序排序。",
        "complexity": "O(n log n)",
        "example": "Arrays.sort(a);",
    }
    text = _entry_text(entry)
    assert "Arrays.sort" in text
    assert "关键词: arrays, sort" in text
    assert "类别: 数组" in text
    assert "复杂度: O(n log n)" in text
    assert "示例: Arrays.sort(a);" in text
