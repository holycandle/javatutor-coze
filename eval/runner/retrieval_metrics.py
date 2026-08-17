"""RAG 检索指标：MRR 与 hit@k。

输入：端到端 outputs（每条含 decision_trace.sources）与黄金样本（expected_sources）。
输出：mrr / hit_at_1 / hit_at_3 / hit_at_5 / total。
"""

from typing import Any


def compute_retrieval_metrics(
    outputs: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    top_k: int = 5,
) -> dict[str, Any]:
    by_id = {s["id"]: s for s in samples}
    mrr_scores: list[float] = []
    hits = {1: 0, 3: 0, 5: 0}
    total = 0
    for out in outputs:
        sample = by_id.get(out.get("id"), {})
        expected = sample.get("expected_sources") or []
        if not expected:
            continue
        sources = [s.get("source") for s in (out.get("decision_trace") or {}).get("sources", [])]
        total += 1
        rank = None
        for idx, source in enumerate(sources[:top_k], start=1):
            if source in expected:
                rank = idx
                break
        if rank:
            mrr_scores.append(1.0 / rank)
            for k in hits:
                if rank <= k:
                    hits[k] += 1
    return {
        "mrr": round(sum(mrr_scores) / len(mrr_scores), 4) if mrr_scores else 0.0,
        "hit_at_1": round(hits[1] / total, 4) if total else 0.0,
        "hit_at_3": round(hits[3] / total, 4) if total else 0.0,
        "hit_at_5": round(hits[5] / total, 4) if total else 0.0,
        "total": total,
    }
