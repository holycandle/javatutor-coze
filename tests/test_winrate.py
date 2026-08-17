from langchain_core.messages import AIMessage

from eval.runner.winrate import compare_pair, compute_winrate


class FakeModel:
    def __init__(self, content):
        self.content = content

    def invoke(self, messages):
        return AIMessage(content=self.content)


def test_compare_pair():
    sample = {"id": "q01", "payload": {"user_question": "为什么 x 变了？"}, "expected_facts": ["x=1"]}
    out = compare_pair(sample, "版本 A 回答", "版本 B 回答", model=FakeModel('{"winner": "a", "reason": "更准"}'))
    assert out["winner"] == "a"


def test_compute_winrate():
    comparisons = [{"winner": "a"}, {"winner": "a"}, {"winner": "b"}, {"winner": "tie"}]
    metrics = compute_winrate(comparisons)
    assert metrics["total"] == 4
    assert metrics["win_rate"] == 0.5
    assert metrics["loss_rate"] == 0.25
    assert metrics["tie_rate"] == 0.25
