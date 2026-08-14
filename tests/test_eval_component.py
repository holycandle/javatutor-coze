from pathlib import Path

from eval.runner.component_metrics import load_jsonl, run_component_cases

ROOT = Path(__file__).resolve().parents[1]


def _stub_rag(query):
    return ["知识库: HashMap"]


def test_run_component_cases_on_sample_file():
    cases = load_jsonl(ROOT / "eval" / "samples" / "component_cases.jsonl")
    result = run_component_cases(cases, rag_search=_stub_rag)
    assert result["intent_accuracy"] == 1.0
    assert result["citation_accuracy"] == 1.0
    assert result["critic_recall"] == 1.0
    assert result["rag_hit_at_3"] == 1.0
    assert result["pass_rate"] == 1.0
