from unittest.mock import MagicMock, patch

from eval.runner.e2e_remote import chat_remote, parse_decision_trace


def test_parse_decision_trace_extracts_new_fields():
    text = '回答\n\n【决策痕迹】\n{"tool_calls":[{"tool":"step_facts","args":{"step_index":1}}],"token_usage":{"prompt_tokens":100,"completion_tokens":50,"estimated":true}}'
    trace = parse_decision_trace(text)
    assert trace["tool_calls"][0]["tool"] == "step_facts"
    assert trace["tool_calls"][0]["args"]["step_index"] == 1
    assert trace["token_usage"]["completion_tokens"] == 50
    assert trace["token_usage"]["estimated"] is True


def test_chat_remote_concatenates_sse_chunks():
    chunks = [
        "event: message\n",
        'data: {"type":"message_start","session_id":"q01"}\n',
        "",
        "event: message\n",
        'data: {"type":"answer","content":{"answer":"第"}}\n',
        "",
        "event: message\n",
        'data: {"type":"answer","content":{"answer":"2 步 arr[1]=5"}}\n',
        "",
        "event: message\n",
        'data: {"type":"message_end","session_id":"q01"}\n',
        "",
        'data: [DONE]\n',
    ]
    mock_stream = MagicMock()
    resp = MagicMock()
    resp.iter_lines.return_value = chunks
    mock_stream.__enter__.return_value = resp
    with patch("eval.runner.e2e_remote.httpx.stream", return_value=mock_stream):
        out = chat_remote({"id": "q01", "payload": {"user_question": "为什么"}}, "http://api", "token", "pid")
    assert out["id"] == "q01"
    assert out["answer"] == "第2 步 arr[1]=5"
    assert out["latency"] >= 0
    assert out["decision_trace"] is None
