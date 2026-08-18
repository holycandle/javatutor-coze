from langchain_core.messages import AIMessage

from eval.runner import judge as judge_module
from eval.runner.judge import build_judge_messages, judge_answer, parse_judge_output


class FakeModel:
    def invoke(self, messages):
        return AIMessage(content='{"score": 4.5, "judgement": "correct", "scores": {"relevance": 5, "grounding": 4, "pollution": 5, "correctness": 4}, "reason": "ok"}')


def test_build_judge_messages():
    messages = build_judge_messages({"payload": {}, "expected_facts": ["step=2"]}, "回答")
    assert messages[0].type == "system"
    assert "step=2" in messages[1].content


# ── parse_judge_output 容错解析 ───────────────────────────────────────────────


def test_parse_judge_output_pure_json():
    data = parse_judge_output('{"score": 4, "judgement": "correct"}')
    assert data["score"] == 4
    assert data["judgement"] == "correct"


def test_parse_judge_output_fenced_json():
    data = parse_judge_output('```json\n{"score": 3, "judgement": "partially_correct"}\n```')
    assert data["score"] == 3
    assert data["judgement"] == "partially_correct"


def test_parse_judge_output_preamble_before_json():
    data = parse_judge_output('好的，根据评审结果：\n{"score": 2, "judgement": "incorrect", "reason": "未引用真实步骤"}')
    assert data["score"] == 2
    assert data["judgement"] == "incorrect"


def test_parse_judge_output_trailing_explanation():
    data = parse_judge_output('{"score": 5, "judgement": "correct"} 以上是我的评审意见。')
    assert data["score"] == 5


def test_parse_judge_output_numeric_string_score():
    data = parse_judge_output('{"score": "4.5", "judgement": "correct", "scores": {"grounding": 4}}')
    assert data["score"] == 4.5
    # scores 缺失的维度补默认 0
    assert data["scores"]["relevance"] == 0
    assert data["scores"]["pollution"] == 0
    assert data["scores"]["correctness"] == 0


def test_parse_judge_output_non_enum_judgement_forced_incorrect():
    data = parse_judge_output('{"score": 3, "judgement": "半对半错"}')
    assert data["judgement"] == "incorrect"
    # judgement 缺失同样归 incorrect
    data2 = parse_judge_output('{"score": 3}')
    assert data2["judgement"] == "incorrect"
    # scores 整体缺失补默认 0
    assert data2["scores"]["grounding"] == 0


def test_parse_judge_output_invalid_returns_none():
    assert parse_judge_output("not json") is None
    assert parse_judge_output("") is None
    assert parse_judge_output("```json\nno object here\n```") is None
    assert parse_judge_output("完全没有任何 JSON") is None


def test_parse_judge_output_clamps_out_of_range_score():
    """score / scores 各维超 [0,5] 范围被 clamp."""
    data = parse_judge_output('{"score": 9, "judgement": "correct", "scores": {"relevance": 7, "grounding": -3, "pollution": 4, "correctness": 5}}')
    assert data["score"] == 5.0
    assert data["scores"]["relevance"] == 5.0
    assert data["scores"]["grounding"] == 0.0
    assert data["scores"]["pollution"] == 4.0
    assert data["scores"]["correctness"] == 5.0


def test_parse_judge_output_missing_required_shape_normalized():
    """字段缺失（无 scores/无 reason/无 judgement）被归一化而非 None."""
    data = parse_judge_output('{"score": 2.5}')
    assert data["score"] == 2.5
    assert data["judgement"] == "incorrect"
    assert data["scores"] == {"relevance": 0, "grounding": 0, "pollution": 0, "correctness": 0}
    assert data["reason"] == ""


# ── judge_answer：原始输出保存 + 单次重试 ─────────────────────────────────────


def test_judge_answer_success():
    out = judge_answer({"id": "q01"}, "回答", model=FakeModel())
    assert out["score"] == 4.5
    assert "raw_judge_output" in out
    assert "score" in out["raw_judge_output"]
    assert "judge_parse_error" not in out


class RetryModel:
    """第一次返回不可解析文本，第二次返回合法 JSON。"""

    def __init__(self):
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="抱歉，我无法给出评分，原因如下……")
        return AIMessage(content='{"score": 3.5, "judgement": "partially_correct", "scores": {"grounding": 4}, "reason": "重试后成功"}')


def test_judge_answer_retries_once_on_parse_failure():
    model = RetryModel()
    out = judge_answer({"id": "q02"}, "回答", model=model)
    assert model.calls == 2, "解析失败应重试一次"
    assert out["score"] == 3.5
    assert "judge_parse_error" not in out
    # 原始输出保留最终成功的那次，便于核对
    assert "重试后成功" in out["raw_judge_output"]


def test_judge_answer_falls_back_when_parse_never_succeeds():
    class AlwaysBad:
        def invoke(self, messages):
            return AIMessage(content="没有 JSON 的输出")

    out = judge_answer({"id": "q03"}, "回答", model=AlwaysBad())
    assert out["judge_fallback"] is True
    assert out["score"] == 0.0
    assert out["judgement"] == "incorrect"
    assert "raw_judge_output" in out
    assert out["raw_judge_output"] == "没有 JSON 的输出"


def test_judge_answer_real_call_retries_with_temperature_zero(monkeypatch):
    """真实调用路径：首次 temperature=0.1 失败，重试 temperature=0.0."""
    seen = []
    sleeps = []
    monkeypatch.setattr(judge_module.time, "sleep", lambda s: sleeps.append(s))

    def fake_complete(messages, temperature=0.1):
        seen.append(temperature)
        if len(seen) == 1:
            return "无法解析"
        return '{"score": 4, "judgement": "correct", "scores": {"grounding": 5}, "reason": "ok"}'

    monkeypatch.setattr(judge_module, "judge_complete", fake_complete)
    out = judge_answer({"id": "q04"}, "回答")
    assert seen == [0.1, 0.0]
    assert sleeps == [1.0]
    assert out["score"] == 4
    assert out["raw_judge_output"] == '{"score": 4, "judgement": "correct", "scores": {"grounding": 5}, "reason": "ok"}'
    assert out["attempts"] == 2


class AlwaysEmptyModel:
    def invoke(self, messages):
        return AIMessage(content="")


def test_judge_answer_marks_empty_output_after_three_attempts():
    """空返回重试满 3 次：标记 empty_output + judge_fallback."""
    model = AlwaysEmptyModel()
    out = judge_answer({"id": "q05"}, "回答", model=model)
    assert out["attempts"] == 3
    assert out["judge_fallback"] is True
    assert out["empty_output"] is True
    assert out["score"] == 0.0
    assert out["raw_judge_output"] == ""


def test_judge_answer_real_call_three_attempts_with_backoff(monkeypatch):
    """真实调用路径：空返回重试 3 次，退避递增，仍失败标 judge_fallback."""
    seen, sleeps = [], []
    monkeypatch.setattr(judge_module.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(judge_module, "judge_complete", lambda messages, temperature=0.1: seen.append(temperature) or "")
    out = judge_answer({"id": "q06"}, "回答")
    assert seen == [0.1, 0.0, 0.0]
    assert sleeps == [1.0, 2.0]
    assert out["attempts"] == 3
    assert out["judge_fallback"] is True
    assert out["empty_output"] is True
