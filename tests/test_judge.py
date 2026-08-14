from langchain_core.messages import AIMessage

from eval.runner.judge import build_judge_messages, judge_answer, parse_judge_output


class FakeModel:
    def invoke(self, messages):
        return AIMessage(content='{"score": 4.5, "judgement": "correct", "scores": {"relevance": 5, "grounding": 4, "pollution": 5, "correctness": 4}, "reason": "ok"}')


def test_build_judge_messages():
    messages = build_judge_messages({"payload": {}, "expected_facts": ["step=2"]}, "回答")
    assert messages[0].type == "system"
    assert "step=2" in messages[1].content


def test_parse_judge_output_valid():
    data = parse_judge_output('{"score": 4, "judgement": "correct"}')
    assert data["score"] == 4


def test_parse_judge_output_invalid():
    assert parse_judge_output("not json") is None


def test_judge_answer_marks_parse_error():
    out = judge_answer({"id": "q01"}, "回答", model=FakeModel())
    assert out["score"] == 4.5
