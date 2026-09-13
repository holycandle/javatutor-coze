import json
from pathlib import Path

from eval.runner.report import (
    collect_changes_since,
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


def test_resolve_previous_summary_cross_date_falls_back(tmp_path):
    """跨日期对比：当前轮同日期无 round-{n-1} 时，回退到更早日期的最近一轮。"""
    prev = tmp_path / "2026-08-17" / "round-1"
    prev.mkdir(parents=True, exist_ok=True)
    (prev / "summary.json").write_text('{"e2e": {"avg_score": 3.5}}', encoding="utf-8")
    cur = tmp_path / "2026-09-6" / "round-2"
    cur.mkdir(parents=True, exist_ok=True)
    (cur / "summary.json").write_text('{"e2e": {"avg_score": 4.0}}', encoding="utf-8")
    # 应命中更早日期 round-1，而不是「无上一轮」；且排除当前轮自身的 summary
    result = resolve_previous_summary(cur)
    assert result == {"e2e": {"avg_score": 3.5}}


def test_resolve_previous_summary_skips_future_rounds(tmp_path):
    """后面的轮次（如 round-3）不作为上一轮；只取严格早于当前轮次的最近一轮。"""
    p1 = tmp_path / "2026-08-17" / "round-1"
    p1.mkdir(parents=True, exist_ok=True)
    (p1 / "summary.json").write_text('{"e2e": {"avg_score": 3.5}}', encoding="utf-8")
    p3 = tmp_path / "2026-09-6" / "round-3"
    p3.mkdir(parents=True, exist_ok=True)
    (p3 / "summary.json").write_text('{"e2e": {"avg_score": 5.0}}', encoding="utf-8")
    cur = tmp_path / "2026-09-6" / "round-2"
    cur.mkdir(parents=True, exist_ok=True)
    result = resolve_previous_summary(cur)
    assert result == {"e2e": {"avg_score": 3.5}}


# ── Agent 更新与变化（collect_changes_since，来自 docs/devlog/） ───────────────


def test_collect_changes_since_filters_by_prev_round(tmp_path, monkeypatch):
    """只收上一轮日期之后、当前轮日期之前的 devlog；评测关键词归 eval_changes。"""
    from eval.runner import report as report_mod

    monkeypatch.setattr(report_mod, "ROOT", tmp_path)
    devlog = tmp_path / "docs" / "devlog"
    devlog.mkdir(parents=True, exist_ok=True)
    # 上一轮 = 2026-08-17 round-1；当前轮 = 2026-09-6 round-2
    (devlog / "2026-08-17-some-agent-change.md").write_text("# 08-17 旧改动\n", encoding="utf-8")  # 区间前，排除
    (devlog / "2026-08-30-fetch-execution-context-as-tool.md").write_text("# fetch 工具化\n", encoding="utf-8")
    (devlog / "2026-09-06-golden-set-follow-tool-library.md").write_text("# 金样本校准\n", encoding="utf-8")
    cur = tmp_path / "eval" / "archive" / "2026-09-6" / "round-2"
    prev = tmp_path / "eval" / "archive" / "2026-08-17" / "round-1"
    prev.mkdir(parents=True, exist_ok=True)
    (prev / "summary.json").write_text('{"e2e": {}}', encoding="utf-8")
    cur.mkdir(parents=True, exist_ok=True)

    result = collect_changes_since(cur)
    assert result["since"] == "2026-08-17 round-1"
    titles = [t.split(" ", 1)[1] for t in result["agent_changes"]]
    assert "fetch 工具化" in titles
    assert "08-17 旧改动" not in titles
    assert any("金样本校准" in t for t in result["eval_changes"])


def test_collect_changes_since_no_previous_lists_all(tmp_path, monkeypatch):
    """无上一轮时列出项目开始以来的全部日志（首轮看到完整变更史）。"""
    from eval.runner import report as report_mod

    monkeypatch.setattr(report_mod, "ROOT", tmp_path)
    devlog = tmp_path / "docs" / "devlog"
    devlog.mkdir(parents=True, exist_ok=True)
    (devlog / "2026-08-07-phase1.md").write_text("# Phase 1\n", encoding="utf-8")
    (devlog / "2026-08-30-fetch-execution-context-as-tool.md").write_text("# fetch 工具化\n", encoding="utf-8")
    cur = tmp_path / "eval" / "archive" / "2026-09-6" / "round-2"
    cur.mkdir(parents=True, exist_ok=True)

    result = collect_changes_since(cur)
    assert result["since"] is None
    assert len(result["agent_changes"]) + len(result["eval_changes"]) == 2


def test_collect_changes_since_classifies_by_filename_keyword(tmp_path, monkeypatch):
    """文件名关键词粗分：eval/judge/golden/grounding 等归评测侧，其余归 Agent 侧。"""
    from eval.runner import report as report_mod

    monkeypatch.setattr(report_mod, "ROOT", tmp_path)
    devlog = tmp_path / "docs" / "devlog"
    devlog.mkdir(parents=True, exist_ok=True)
    (devlog / "2026-08-24-grounding-verifier.md").write_text("# Grounding 核对器\n", encoding="utf-8")  # grounding → 评测侧
    (devlog / "2026-08-25-knowledge-base-correction.md").write_text("# 知识库核对\n", encoding="utf-8")  # 语料变更 → Agent 侧
    (devlog / "2026-08-29-memory-retrieval.md").write_text("# 记忆检索\n", encoding="utf-8")  # Agent 侧
    cur = tmp_path / "eval" / "archive" / "2026-09-6" / "round-2"
    cur.mkdir(parents=True, exist_ok=True)

    result = collect_changes_since(cur)
    assert any("Grounding 核对器" in t for t in result["eval_changes"])
    assert any("知识库核对" in t for t in result["agent_changes"])
    assert any("记忆检索" in t for t in result["agent_changes"])


def test_write_report_renders_changes_section(tmp_path):
    """summary 带 changes 时，report.md 渲染「Agent 更新与变化」节。"""
    round_dir = _make_round(tmp_path)
    summary = {
        "e2e": {"avg_score": 4.0, "total": 1},
        "component": {},
        "diff_vs_previous": {},
        "changes": {
            "since": "2026-08-17 round-1",
            "agent_changes": ["2026-08-30 fetch_execution_context 工具化"],
            "eval_changes": ["2026-09-06 金样本校准"],
        },
    }
    judged = [{"id": "q01", "score": 4, "judgement": "correct", "scores": {"grounding": 4}, "answer": "A"}]
    write_report(round_dir, summary, judged, [], [])
    md = (round_dir / "report.md").read_text(encoding="utf-8")
    assert "Agent 更新与变化" in md
    assert "自 2026-08-17 round-1 以来" in md
    assert "fetch_execution_context 工具化" in md
    assert "金样本校准" in md
    assert "Agent 侧" in md and "评测侧" in md


# ── 各工具调用情况（compute_per_tool_metrics） ────────────────────────────────


def test_per_tool_metrics_exact_match_basic():
    from eval.runner.report import compute_per_tool_metrics

    samples = [
        {"id": "q01", "expected_tool_calls": [{"tool": "step_facts", "args": {"step_index": 1}}]},
        {"id": "q02", "expected_tool_calls": [{"tool": "step_facts", "args": {"step_index": 1}}]},
    ]
    outputs = [
        {"id": "q01", "decision_trace": {"tool_calls": [{"tool": "step_facts", "args": {"step_index": 1}}]}},
        {"id": "q02", "decision_trace": {"tool_calls": [{"tool": "step_facts", "args": {"step_index": 2}}]}},
    ]
    m = compute_per_tool_metrics(outputs, samples)
    assert m["step_facts"]["expected"] == 2
    assert m["step_facts"]["called"] == 2
    assert m["step_facts"]["correct"] == 1
    assert m["step_facts"]["accuracy"] == 0.5
    assert m["step_facts"]["unexpected"] == 0


def test_per_tool_metrics_unexpected_tool_surfaces():
    """未期望却实际调用的工具（如 fetch_execution_context）应作为误用浮出，而非被总率掩盖。"""
    from eval.runner.report import compute_per_tool_metrics

    samples = [
        {"id": "q01", "expected_tool_calls": [{"tool": "step_facts", "args": {"step_index": 1}}]},
    ]
    outputs = [
        {
            "id": "q01",
            "decision_trace": {
                "tool_calls": [
                    {"tool": "step_facts", "args": {"step_index": 1}},
                    {"tool": "fetch_execution_context", "args": {"run_id": "r1"}},
                ]
            },
        }
    ]
    m = compute_per_tool_metrics(outputs, samples)
    # fetch_execution_context 出现在结果里（自动推导），expected=0 但被调用 → 误用信号
    assert m["fetch_execution_context"]["expected"] == 0
    assert m["fetch_execution_context"]["called"] == 1
    assert m["fetch_execution_context"]["accuracy"] is None
    assert m["fetch_execution_context"]["unexpected"] == 1
    # step_facts 仍按精确匹配计
    assert m["step_facts"]["correct"] == 1


def test_per_tool_metrics_iterates_by_id_not_order():
    """样本与输出按 id 关联，不应依赖其顺序。输出缺 decision_trace 时按未调用计。"""
    from eval.runner.report import compute_per_tool_metrics

    samples = [
        {"id": "b", "expected_tool_calls": [{"tool": "step_facts", "args": {"step_index": 1}}]},
        {"id": "a", "expected_tool_calls": [{"tool": "step_facts", "args": {"step_index": 1}}]},
    ]
    outputs = [
        {"id": "a", "decision_trace": {"tool_calls": [{"tool": "step_facts", "args": {"step_index": 1}}]}},
        {"id": "b"},  # 无 decision_trace → 视为未调用
    ]
    m = compute_per_tool_metrics(outputs, samples)
    assert m["step_facts"]["correct"] == 1
    assert m["step_facts"]["called"] == 1
    assert m["step_facts"]["expected"] == 2


def test_per_tool_metrics_fetch_first_sequence_counted():
    """新标准：需要执行证据的样本应先 fetch_execution_context 再 step_facts；
    工具调用顺序不影响命中，fetch 不再被误判为「误用」。"""
    from eval.runner.report import compute_per_tool_metrics

    samples = [
        {
            "id": "q01",
            "expected_tool_calls": [
                {"tool": "fetch_execution_context", "args": {}},
                {"tool": "step_facts", "args": {"step_index": 1, "line": 4}},
            ],
        },
    ]
    outputs = [
        {
            "id": "q01",
            "decision_trace": {
                "tool_calls": [
                    {"tool": "step_facts", "args": {"step_index": 1, "line": 4}},  # 顺序与期望不同
                    {"tool": "fetch_execution_context", "args": {}},
                ]
            },
        },
    ]
    m = compute_per_tool_metrics(outputs, samples)
    assert m["fetch_execution_context"]["expected"] == 1
    assert m["fetch_execution_context"]["called"] == 1
    assert m["fetch_execution_context"]["correct"] == 1
    assert m["fetch_execution_context"]["accuracy"] == 1.0
    assert m["fetch_execution_context"]["unexpected"] == 0
    assert m["step_facts"]["correct"] == 1
    assert m["step_facts"]["unexpected"] == 0


def test_per_tool_metrics_missing_fetch_surfaces_as_low_accuracy():
    """期望 fetch 却没调用：fetch 准确率下降（而非误用），暴露「先读上下文」缺口。"""
    from eval.runner.report import compute_per_tool_metrics

    samples = [
        {
            "id": "q01",
            "expected_tool_calls": [
                {"tool": "fetch_execution_context", "args": {}},
                {"tool": "step_facts", "args": {"step_index": 1, "line": 4}},
            ],
        },
    ]
    outputs = [
        {"id": "q01", "decision_trace": {"tool_calls": [{"tool": "step_facts", "args": {"step_index": 1, "line": 4}}]}},
    ]
    m = compute_per_tool_metrics(outputs, samples)
    assert m["fetch_execution_context"]["expected"] == 1
    assert m["fetch_execution_context"]["called"] == 0
    assert m["fetch_execution_context"]["accuracy"] == 0.0
    assert m["fetch_execution_context"]["unexpected"] == 0
    assert m["step_facts"]["correct"] == 1


# ── 检索指标接线（e2e 内出现四档 RAG 指标，防「指标烂了无人知」）─────────────


def test_report_wires_retrieval_metrics_into_extended():
    """cmd_report 的 extended 组装必须并入 compute_retrieval_metrics。

    `tools/` 无 `__init__.py`（非包），按路径加载模块。
    `cmd_report` 需真实归档才能端到端跑，故此处只断言源码层面确实调用了该函数。
    """
    import importlib.util
    import inspect
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("eval_cli_under_test", root / "tools" / "eval_cli.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    src = inspect.getsource(cli.cmd_report)
    assert "compute_retrieval_metrics" in src


def test_retrieval_metrics_values_match_direct_call():
    from eval.runner.retrieval_metrics import compute_retrieval_metrics

    samples = [
        {"id": "q01", "expected_sources": ["知识库: A"]},
        {"id": "q02", "expected_sources": ["知识库: B"]},
        {"id": "q03"},  # 无 expected_sources → 不计入分母
    ]
    outputs = [
        {"id": "q01", "decision_trace": {"sources": [{"source": "知识库: A", "score": 0.9}]}},
        {"id": "q02", "decision_trace": {"sources": [{"source": "知识库: C", "score": 0.9}]}},
        {"id": "q03", "decision_trace": {"sources": [{"source": "知识库: A", "score": 0.9}]}},
    ]
    metrics = compute_retrieval_metrics(outputs, samples)
    assert metrics["total"] == 2, "无 expected_sources 的样本不计入分母"
    # MRR 只对命中项求均值（q01 命中 rank 1 → 1.0），hit@k 才对全体分母取率
    assert metrics["mrr"] == 1.0
    assert metrics["hit_at_1"] == 0.5
    assert metrics["hit_at_3"] == 0.5
    assert metrics["hit_at_5"] == 0.5


def test_report_does_not_clobber_e2e_total_with_retrieval_denominator():
    """检索分母 (expected_sources 条数) 不得覆盖 e2e 的样本数 total。

    两个 `total` 同名不同义：e2e 的是判分样本数（judgement 非兜底），检索的是
    声明了 `expected_sources` 的样本数。直接 `extended.update(...)` 会用后者盖掉前者
    （实测把 31 改成 17），而 `total` 是 `_E2E_METRIC_ORDER` 首位指标且被合入门槛读取。
    """
    import importlib.util
    import inspect
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("eval_cli_under_test", root / "tools" / "eval_cli.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    src = inspect.getsource(cli.cmd_report)
    # 检索结果的 `total` 在并入 extended 前必须改名，否则覆盖 e2e["total"]。
    assert 'retrieval["retrieval_total"] = retrieval.pop("total")' in src
    assert "extended.update(compute_retrieval_metrics" not in src, "不得把检索 total 直接并进 e2e"
