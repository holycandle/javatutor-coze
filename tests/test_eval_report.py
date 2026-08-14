import json
from pathlib import Path

from eval.runner.report import diff, summarize, write_summary


def test_summarize_computes_metrics():
    judged = [
        {"id": "q01", "score": 5, "judgement": "correct", "scores": {"grounding": 5}},
        {"id": "q02", "score": 3, "judgement": "partially_correct", "scores": {"grounding": 3}},
        {"id": "q03", "judge_parse_error": True},
    ]
    summary = summarize(judged, component={"pass_rate": 0.9})
    assert summary["e2e"]["total"] == 2
    assert summary["e2e"]["avg_score"] == 4.0
    assert summary["e2e"]["grounding_avg"] == 4.0
    assert summary["component"]["pass_rate"] == 0.9


def test_diff_between_rounds():
    prev = {"e2e": {"avg_score": 4.0, "grounding_avg": 4.0}, "component": {"pass_rate": 0.8}}
    cur = {"e2e": {"avg_score": 4.3, "grounding_avg": 4.2}, "component": {"pass_rate": 0.9}}
    d = diff(prev, cur)
    assert d["avg_score"] == 0.3
    assert d["component_pass_rate"] == 0.1


def test_write_summary(tmp_path):
    path = tmp_path / "summary.json"
    write_summary(str(path), {"e2e": {}})
    assert json.loads(path.read_text(encoding="utf-8")) == {"e2e": {}}


def test_compute_extended_metrics():
    from eval.runner.report import compute_extended_metrics

    outputs = [
        {
            "id": "q01",
            "answer": "第 2 步 arr[1]=5",
            "latency": 2.0,
            "decision_trace": {
                "tool_calls": [{"tool": "step_facts", "args": {"step_index": 1}}],
                "token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "estimated": True},
            },
        }
    ]
    samples = [
        {"id": "q01", "expected_tool_calls": [{"tool": "step_facts", "args": {"step_index": 1}}], "expected_facts": ["step=2", "arr[1]=5"]}
    ]
    judged = [{"id": "q01", "judgement": "correct"}]
    m = compute_extended_metrics(outputs, samples, judged)
    assert m["tool_call_accuracy"] == 1.0
    assert m["task_success_rate"] == 1.0
    assert m["avg_latency"] == 2.0
    assert m["avg_token_usage"] == 150
