import json
from pathlib import Path

from eval.runner.report import (
    diff,
    resolve_commit,
    resolve_model,
    resolve_previous_summary,
    summarize,
    write_report,
    write_summary,
)


def test_summarize_computes_metrics():
    judged = [
        {"id": "q01", "score": 5, "judgement": "correct", "scores": {"grounding": 5}},
        {"id": "q02", "score": 3, "judgement": "partially_correct", "scores": {"grounding": 3}},
        {"id": "q03", "judge_fallback": True, "score": 0, "judgement": "incorrect"},
    ]
    summary = summarize(judged, component={"pass_rate": 0.9})
    assert summary["e2e"]["total"] == 2
    assert summary["e2e"]["avg_score"] == 4.0
    assert summary["e2e"]["grounding_avg"] == 4.0
    assert summary["component"]["pass_rate"] == 0.9


def test_summarize_computes_fallback_rates():
    judged = [
        {"id": "q01", "score": 5, "judgement": "correct", "scores": {"grounding": 5}},
        {"id": "q02", "judge_fallback": True, "score": 0, "judgement": "incorrect", "empty_output": True},
        {"id": "q03", "judge_fallback": True, "score": 0, "judgement": "incorrect"},
        {"id": "q04", "score": 4, "judgement": "correct", "scores": {"grounding": 4}},
    ]
    summary = summarize(judged)
    # 2 条兜底 / 4 条总数；其中 1 条空输出
    assert summary["e2e"]["judge_fallback_rate"] == 0.5
    assert summary["e2e"]["empty_output_rate"] == 0.25
    # 兜底样本不计入 avg_score（只算 q01/q04）
    assert summary["e2e"]["total"] == 2
    assert summary["e2e"]["avg_score"] == 4.5


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


def test_summarize_merges_extended():
    judged = [{"id": "q01", "score": 5, "judgement": "correct", "scores": {"grounding": 5}}]
    extended = {"tool_call_accuracy": 1.0, "avg_latency": 2.0}
    summary = summarize(judged, component={"pass_rate": 0.9}, extended=extended)
    assert summary["e2e"]["tool_call_accuracy"] == 1.0
    assert summary["e2e"]["avg_latency"] == 2.0
    assert summary["e2e"]["avg_score"] == 5.0


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
    assert m["token_usage_sample_count"] == 1


# ── write_report（report.md 人读报告） ─────────────────────────────────────────


def _make_round(tmp_path):
    round_dir = tmp_path / "2026-08-17" / "round-1"
    round_dir.mkdir(parents=True, exist_ok=True)
    return round_dir


def test_write_report_writes_md_with_sections(tmp_path):
    round_dir = _make_round(tmp_path)
    summary = {
        "e2e": {
            "avg_score": 4.0,
            "grounding_avg": 4.0,
            "total": 2,
            "correct": 1,
            "partially_correct": 1,
            "incorrect": 0,
            "judge_fallback_rate": 0.0,
            "empty_output_rate": 0.0,
        },
        "component": {},
        "diff_vs_previous": {"avg_score": 0.1, "grounding_avg": 0.2, "component_pass_rate": 0.0},
    }
    judged = [
        {"id": "q01", "score": 5, "judgement": "correct", "scores": {"grounding": 5}, "answer": "回答A"},
        {"id": "q02", "score": 3, "judgement": "partially_correct", "scores": {"grounding": 3}, "answer": "回答B"},
    ]
    path = write_report(round_dir, summary, judged, [], [])
    assert path == str(round_dir / "report.md")
    md = (round_dir / "report.md").read_text(encoding="utf-8")
    assert "端到端指标" in md
    assert "Badcase" in md
    assert "avg_score" in md


def test_write_report_includes_grounding_verify_metrics(tmp_path):
    round_dir = _make_round(tmp_path)
    summary = {
        "e2e": {
            "avg_score": 4.0,
            "total": 2,
            "grounding_verify_applicable": 2,
            "grounding_verify_checked": 4,
            "grounding_verify_violations": 1,
            "grounding_verify_accuracy": 0.5,
        },
        "component": {},
        "diff_vs_previous": {},
    }
    path = write_report(round_dir, summary, [], [], [])
    md = (round_dir / "report.md").read_text(encoding="utf-8")
    assert "grounding_verify_applicable" in md
    assert "grounding_verify_accuracy" in md


def test_write_report_includes_fallback_badcase(tmp_path):
    round_dir = _make_round(tmp_path)
    summary = {"e2e": {"avg_score": 5.0, "total": 1}, "component": {}, "diff_vs_previous": {}}
    judged = [
        {"id": "q01", "score": 5, "judgement": "correct", "scores": {"grounding": 5}, "answer": "正常"},
        {
            "id": "q02",
            "score": 0,
            "judgement": "incorrect",
            "scores": {"grounding": 0},
            "answer": "兜底回答",
            "reason": "judge output unparseable",
            "judge_fallback": True,
            "empty_output": True,
        },
    ]
    write_report(round_dir, summary, judged, [], [])
    md = (round_dir / "report.md").read_text(encoding="utf-8")
    assert "q02" in md
    assert "judge_fallback" in md
    assert "兜底回答" in md


def test_write_report_empty_judged_no_crash(tmp_path):
    round_dir = _make_round(tmp_path)
    summary = {"e2e": {"total": 0}, "component": {}, "diff_vs_previous": {}}
    path = write_report(round_dir, summary, [], [], [])
    md = (round_dir / "report.md").read_text(encoding="utf-8")
    assert "（无 badcase）" in md


def test_resolve_model_and_commit(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agent_llm_config.json").write_text('{"config": {"model": "m1"}}', encoding="utf-8")
    assert resolve_model(tmp_path) == "m1"
    assert resolve_model(tmp_path / "missing") == "unknown"
    # 非 git 目录回退 unknown
    assert resolve_commit(tmp_path) == "unknown"


def test_resolve_previous_summary_first_round_returns_none(tmp_path):
    round_dir = tmp_path / "2026-08-17" / "round-1"
    round_dir.mkdir(parents=True, exist_ok=True)
    assert resolve_previous_summary(round_dir) is None


def test_resolve_previous_summary_second_round_reads_prev(tmp_path):
    archive = tmp_path / "2026-08-17"
    prev = archive / "round-1"
    prev.mkdir(parents=True, exist_ok=True)
    (prev / "summary.json").write_text('{"e2e": {"avg_score": 4.0}}', encoding="utf-8")
    result = resolve_previous_summary(archive / "round-2")
    assert result == {"e2e": {"avg_score": 4.0}}


def test_resolve_previous_summary_missing_prev_returns_none(tmp_path):
    round_dir = tmp_path / "2026-08-17" / "round-3"
    round_dir.mkdir(parents=True, exist_ok=True)
    assert resolve_previous_summary(round_dir) is None
