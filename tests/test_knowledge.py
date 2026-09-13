from learning.knowledge import _entry_text, chunk_text, search_chunks, search_chunks_debug


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


def test_search_chunks_propagates_backend_error():
    """embedding / 查询后端失败时应向上抛，而非静默吞掉返回 []。

    之前内部 try/except 吞掉异常，导致 retrieve_knowledge 的 except（rag_degraded=True）
    永远是死代码，RAG 故障被静默掩盖。改为抛出后可正确触发降级信号。
    """

    def bad_embed(texts):
        raise RuntimeError("embedding unavailable")

    try:
        search_chunks("查询", embedder=bad_embed)
        assert False, "应向上抛出异常，让 retrieve_knowledge 置 rag_degraded=True"
    except RuntimeError:
        pass


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


# ── search_chunks_debug（诊断用：带回被阈值滤掉的候选）────────────────────────


def _fake_embed(texts):
    return [[1.0]]


def _fake_fetch_two_rows(vector, top_k):
    return [
        ("知识库: A", 0, "内容A", 0.8),
        ("知识库: B", 0, "内容B", 0.2),
    ]


def test_search_chunks_debug_returns_all_candidates_with_kept_flag():
    """低分候选也必须带回——否则「没召回到」与「召回到但被阈值滤掉」不可区分。"""
    result = search_chunks_debug(
        "查询", top_k=3, threshold=0.5, embedder=_fake_embed, fetcher=_fake_fetch_two_rows
    )
    assert len(result["candidates"]) == 2
    assert result["candidates"][0]["kept"] is True
    assert result["candidates"][1]["kept"] is False
    assert result["kept"] == 1
    assert result["best_score"] == 0.8
    assert result["threshold"] == 0.5
    assert result["query"] == "查询"
    assert result["top_k"] == 3


def test_search_chunks_debug_candidate_fields():
    result = search_chunks_debug(
        "查询", threshold=0.5, embedder=_fake_embed, fetcher=_fake_fetch_two_rows
    )
    first = result["candidates"][0]
    assert first["source"] == "知识库: A"
    assert first["chunk_index"] == 0
    assert first["score"] == 0.8
    assert first["content"] == "内容A"


def test_search_chunks_debug_empty_query():
    result = search_chunks_debug("")
    assert result["candidates"] == []
    assert result["best_score"] == 0.0
    assert result["kept"] == 0


def test_search_chunks_debug_equivalence_with_search_chunks():
    """两条路径不得漂移：kept 数与被保留的 source 集合必须一致。"""
    debug = search_chunks_debug(
        "查询", threshold=0.5, embedder=_fake_embed, fetcher=_fake_fetch_two_rows
    )
    plain = search_chunks(
        "查询", threshold=0.5, embedder=_fake_embed, fetcher=_fake_fetch_two_rows
    )
    assert debug["kept"] == len(plain)
    assert {c["source"] for c in debug["candidates"] if c["kept"]} == {c["source"] for c in plain}


def test_search_chunks_debug_best_score_takes_max_not_first():
    """``best_score`` 必须是候选**最高分**，不得依赖 fetcher 的返回顺序。

    真实 fetcher 的 SQL 按距离升序，首条恰是最近邻，故「取首条」眼下也正确——
    但那把诊断结论偷偷绑在了排序不变量上：换 fetcher 或加次级排序，
    ``best_score`` 会静默变成「第一条」而非「最高分」，据此误判阈值是否过高。
    """

    def reversed_fetch(vector, top_k):
        # 与 _fake_fetch_two_rows 同集合，但顺序颠倒（首条是低分）
        return [
            ("知识库: B", 0, "内容B", 0.2),
            ("知识库: A", 0, "内容A", 0.8),
        ]

    result = search_chunks_debug(
        "查询", top_k=3, threshold=0.5, embedder=_fake_embed, fetcher=reversed_fetch
    )
    assert result["best_score"] == 0.8
    assert result["kept"] == 1


def test_search_chunks_debug_propagates_backend_error():
    """与 search_chunks 同口径：后端失败向上抛，不吞成空候选。"""

    def bad_embed(texts):
        raise RuntimeError("embedding unavailable")

    try:
        search_chunks_debug("查询", embedder=bad_embed)
        assert False, "应向上抛出异常"
    except RuntimeError:
        pass
