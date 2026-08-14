import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_jsonl(name):
    path = ROOT / "eval" / "samples" / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_golden_set_schema():
    rows = _load_jsonl("golden_set.jsonl")
    assert len(rows) >= 5
    for row in rows:
        assert row["id"]
        assert row["bucket"] in ("data_query", "concept", "debug", "other", "analyze", "edge")
        assert isinstance(row["payload"], dict)
        assert row["expected_intent"]
        assert isinstance(row["expected_facts"], list)
        assert isinstance(row["judge_priority"], bool)


def test_component_cases_schema():
    rows = _load_jsonl("component_cases.jsonl")
    assert len(rows) >= 4
    for row in rows:
        assert row["type"] in ("intent", "citation", "critic", "rag")
        assert isinstance(row["input"], dict)
