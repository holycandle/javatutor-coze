from pathlib import Path

from eval.runner.component_metrics import load_jsonl, run_component_cases

ROOT = Path(__file__).resolve().parents[1]


def _stub_rag(query):
    """返回一条**真实存在**的 chunk 标签。

    这里曾经硬编码 `知识库: HashMap`——该标签在 seed_assets 打标签规则
    （`知识库: {entry.title}`）下并不存在，于是样本与桩一起错、断言恒绿但测不到真事。
    改为从 java_std.json 取真实 title，标签漂移时本用例会直接失败。
    """
    import json

    entries = json.loads((ROOT / "assets" / "knowledge" / "java_std.json").read_text(encoding="utf-8"))["entries"]
    titles = {e["title"] for e in entries}
    for want in ("HashMap.get", "HashMap.put", "HashMap.containsKey"):
        if want in titles:
            return f"知识库: {want}"
    raise AssertionError("java_std.json 缺少任何 HashMap 条目，样本标签需要重新校准")


def test_run_component_cases_on_sample_file():
    cases = load_jsonl(ROOT / "eval" / "samples" / "component_cases.jsonl")
    result = run_component_cases(cases, rag_search=_stub_rag)
    assert result["intent_accuracy"] == 1.0
    assert result["citation_accuracy"] == 1.0
    assert result["critic_recall"] == 1.0
    assert result["rag_hit_at_3"] == 1.0
    assert result["pass_rate"] == 1.0


def _legal_chunk_labels() -> set[str]:
    """按 seed_assets 的打标签规则（`知识库: {entry.title}`）算出所有合法 chunk 标签。

    JSON 语料以 `entries[].title` 打标签，见 src/learning/knowledge.py::seed_assets。
    """
    import json

    labels = set()
    for path in (ROOT / "assets" / "knowledge").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data.get("entries", []):
            labels.add(f"知识库: {entry.get('title', path.stem)}")
    return labels


def test_all_sample_rag_labels_are_real_chunks():
    """样本的 expected_sources 必须命中真实 chunk 标签，否则该指标结构性为 0。

    这条守卫是本用例的核心价值：`rag_hit_at_3` 依赖「标签字符串相等」，
    而标签由 `entry.title` 生成——语料改名而样本没跟，指标会静默变 0 且看起来像模型退化。
    component_cases 与 golden_set 一起校验（两者都声明了 expected_sources）。
    """
    legal = _legal_chunk_labels()
    assert legal, "没算出任何合法标签，语料目录可能不对"

    bad: list[str] = []
    for name in ("component_cases.jsonl", "golden_set.jsonl"):
        for row in load_jsonl(ROOT / "eval" / "samples" / name):
            for src in row.get("expected_sources") or []:
                if src not in legal:
                    bad.append(f"{name}:{row.get('id')} -> {src}")
    assert not bad, "以下 expected_sources 不是真实 chunk 标签：\n" + "\n".join(bad)



# === CD-6：评审 × Judge 一致性指标进 summary ===


def _judged_row(id_, judgement, critic_passed, revised=False):
    return {
        "id": id_,
        "judgement": judgement,
        "score": 3,
        "decision_trace": {"critic_passed": critic_passed, "revised": revised, "intent": "data_query"},
    }


def test_critic_agreement_metrics_empty_is_zero_shaped():
    """无归档 / 无样本 ⇒ 返回零值同形状（消费方不必为「没跑」单开分支）。"""
    from eval.runner.component_metrics import critic_agreement_metrics

    m = critic_agreement_metrics([])
    assert m["critic_fail_rate"] == 0.0
    assert m["critic_agree_with_judge"] == {"precision": 0.0, "recall": 0.0, "n": 0}


def test_critic_agreement_metrics_counts_full_cross_table():
    """四格都要对：拦对 / 误杀 / 漏拦 / 正确放过。"""
    from eval.runner.component_metrics import critic_agreement_metrics

    m = critic_agreement_metrics([
        _judged_row("a", "incorrect", False, revised=True),   # 拦对
        _judged_row("b", "partially_correct", False),          # 拦对（非 correct 即算）
        _judged_row("c", "correct", False),                    # 误杀
        _judged_row("d", "incorrect", True),                   # 漏拦
        _judged_row("e", "correct", True),                     # 正确放过
    ])
    assert m["critic_fail_rate"] == 0.6                      # 3/5
    assert m["critic_agree_with_judge"]["precision"] == round(2 / 3, 4)
    assert m["critic_agree_with_judge"]["recall"] == 0.5     # 拦对的 2 条里只有 1 条是 incorrect
    assert m["critic_agree_with_judge"]["n"] == 3            # 分母是被拦数


def test_summarize_wires_critic_metrics_into_e2e():
    """红线：指标必须真的落进 summary，而不只是函数算得对。"""
    from eval.runner.report import summarize

    summary = summarize([_judged_row("a", "incorrect", False, revised=True)])
    assert summary["e2e"]["critic_fail_rate"] == 1.0
    assert summary["e2e"]["critic_agree_with_judge"]["precision"] == 1.0
    assert summary["e2e"]["critic_agree_with_judge"]["n"] == 1
