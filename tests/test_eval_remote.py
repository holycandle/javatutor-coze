from eval.runner.e2e_remote import parse_decision_trace


def test_parse_decision_trace_extracts_new_fields():
    text = '回答\n\n【决策痕迹】\n{"tool_calls":[{"tool":"step_facts","args":{"step_index":1}}],"token_usage":{"prompt_tokens":100,"completion_tokens":50,"estimated":true}}'
    trace = parse_decision_trace(text)
    assert trace["tool_calls"][0]["tool"] == "step_facts"
    assert trace["tool_calls"][0]["args"]["step_index"] == 1
    assert trace["token_usage"]["completion_tokens"] == 50
    assert trace["token_usage"]["estimated"] is True
