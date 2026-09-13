import json
from pathlib import Path

from graphs.javatutor.intent_rules import conservative_intent

ROOT = Path(__file__).resolve().parents[1]


def _load_jsonl(name):
    path = ROOT / "eval" / "samples" / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_golden_set_schema():
    rows = _load_jsonl("golden_set.jsonl")
    assert len(rows) >= 10  # 至少 10 条带 expected_tool_calls，支撑 tool_call_accuracy 统计
    for row in rows:
        assert row["id"]
        assert row["bucket"] in ("data_query", "concept", "debug", "other", "analyze", "edge")
        assert isinstance(row["payload"], dict)
        assert row["expected_intent"]
        assert isinstance(row["expected_facts"], list)
        assert isinstance(row["expected_tool_calls"], list)
        assert isinstance(row["judge_priority"], bool)


def test_golden_set_expected_intent_matches_classifier():
    """`expected_intent` 必须等于**保守分类器的实际输出**（spec §5.1 的定义）。

    该字段此前无任何 runner 消费，于是可以长期与分类器脱节而无人发现——
    实测 q13–q18 五条 concept 样本都与分类器不符（其中两条是分类器自身的 `arr`
    子串误匹配 bug，已在 intent_rules 修掉）。这条守卫让该字段不再是「写着好看」。
    """
    rows = _load_jsonl("golden_set.jsonl")
    bad = []
    for row in rows:
        payload = row["payload"]
        # payload 显式声明 intent 时以它为准（analyze 路径即如此，见 nodes.parse_context）
        declared = payload.get("intent")
        actual = declared or conservative_intent(
            payload.get("user_question", ""), payload.get("compile_error", "")
        )
        if actual != row["expected_intent"]:
            bad.append(
                f"{row['id']}({row['bucket']}): expected={row['expected_intent']} actual={actual}"
                f" q={payload.get('user_question', '')[:40]}"
            )
    assert not bad, "expected_intent 与保守分类器不符：\n" + "\n".join(bad)


def test_component_cases_schema():
    rows = _load_jsonl("component_cases.jsonl")
    assert len(rows) >= 4
    for row in rows:
        assert row["type"] in ("intent", "citation", "critic", "rag")
        assert isinstance(row["input"], dict)
