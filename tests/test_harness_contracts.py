"""动作契约测试：提案 / 裁决 / 观察三种结构，以及它们的解析与渲染。"""

from graphs.javatutor.harness.contracts import (
    Action,
    GuardDecision,
    Observation,
    ParseError,
    parse_action,
    render_observation,
)


class TestParseAction:
    def test_parses_tool_and_args(self):
        a = parse_action('{"tool":"step_facts","args":{"step_index":1}}')
        assert a == Action(tool="step_facts", args={"step_index": 1}, raw='{"tool":"step_facts","args":{"step_index":1}}')

    def test_args_defaults_to_empty_dict(self):
        a = parse_action('{"tool":"step_facts"}')
        assert isinstance(a, Action)
        assert a.args == {}

    def test_null_args_is_empty_dict(self):
        a = parse_action('{"tool":"step_facts","args":null}')
        assert isinstance(a, Action)
        assert a.args == {}

    def test_non_dict_args_is_parse_error_not_silent_empty(self):
        """取消静默 `{}`：模型给了字典以外的 args，必须显式说出来。"""
        out = parse_action('{"tool":"step_facts","args":"oops"}')
        assert not isinstance(out, Action)
        assert isinstance(out, ParseError)
        assert out.reason

    def test_prose_is_not_a_proposal(self):
        """散文本就是终答，不是「解析失败」。"""
        assert parse_action("随便一段散文") is None

    def test_missing_tool_is_not_a_proposal(self):
        assert parse_action('{"args":{}}') is None

    def test_malformed_json_is_not_a_proposal(self):
        assert parse_action('{"tool":') is None


class TestRenderObservation:
    def test_ok_renders_summary_verbatim(self):
        obs = Observation(
            tool="step_facts",
            args={},
            status="ok",
            policy="P0",
            summary="\n\n[step_facts 结果：第 2 步]",
            payload={},
            latency_ms=1.0,
            truncated=False,
        )
        assert render_observation(obs) == obs.summary

    def test_non_ok_keeps_reason_visible(self):
        """模型下一轮要能看见「为什么没执行」，否则只会重复同一个错。"""
        obs = Observation(
            tool="no_such_tool",
            args={},
            status="denied",
            policy="P1",
            summary="工具 no_such_tool 不在注册表中，可用：step_facts / fetch_execution_context",
            payload={},
            latency_ms=0.0,
            truncated=False,
        )
        text = render_observation(obs)
        assert "未执行" in text
        assert "P1" in text
        assert "no_such_tool" in text
        assert "step_facts" in text


def test_guard_decision_is_data_not_prose():
    d = GuardDecision(verdict="deny", policy="P2", reason="未知键 bogus_key", options=[])
    assert d.verdict == "deny"
    assert d.policy == "P2"
    assert d.options == []
