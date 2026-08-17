from eval.runner.retrieval_metrics import compute_retrieval_metrics


def test_mrr_and_hit_at_k():
    outputs = [
        {"id": "q01", "decision_trace": {"sources": [{"source": "知识库: Arrays.sort"}, {"source": "知识库: HashMap"}]}},
        {"id": "q02", "decision_trace": {"sources": [{"source": "知识库: HashMap"}]}},
    ]
    samples = [
        {"id": "q01", "expected_sources": ["知识库: HashMap"]},
        {"id": "q02", "expected_sources": ["知识库: HashMap"]},
    ]
    metrics = compute_retrieval_metrics(outputs, samples)
    assert metrics["total"] == 2
    assert metrics["mrr"] == 0.75
    assert metrics["hit_at_1"] == 0.5
    assert metrics["hit_at_3"] == 1.0
    assert metrics["hit_at_5"] == 1.0
