"""build_reasoning：从 agent_messages 提取工具间 AI 思考片段（纯函数，不依赖图）。"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from graphs.javatutor.nodes import build_reasoning


def _messages():
    return [
        SystemMessage(content="系统提示"),
        HumanMessage(content="上下文"),
        AIMessage(content="想法A"),
        HumanMessage(content="观察"),
        AIMessage(content="想法B"),
    ]


def test_extracts_ai_messages_in_order():
    reasoning, truncated = build_reasoning(_messages())
    assert len(reasoning) == 2
    assert [r["round"] for r in reasoning] == [0, 1]
    assert [r["content"] for r in reasoning] == ["想法A", "想法B"]
    assert truncated is False


def test_tool_calls_extracted_from_action_json():
    messages = [
        AIMessage(content='{"tool":"step_facts","args":{"step_index":1}}'),
    ]
    reasoning, _ = build_reasoning(messages, executed_tools={"step_facts"})
    assert reasoning[0]["tool_calls"] == ["step_facts"]


def test_action_json_payload_not_copied_into_content():
    """被解析为提案的原始 JSON 不得进入 content——它是用户可见痕迹，且有「不得泄露」红线。"""
    reasoning, _ = build_reasoning(
        [AIMessage(content='{"tool":"no_such_tool","args":{}}')], executed_tools={"no_such_tool"}
    )
    assert reasoning[0]["tool_calls"] == ["no_such_tool"]
    assert "no_such_tool" not in reasoning[0]["content"]


def test_denied_tool_name_never_enters_reasoning():
    """被拒（P1/P2）的提案不得出现在痕迹里：tool_calls 归 []，名字也不得进 content。

    这是既有红线（spec §4.7；`tests/test_harness_loop.py` 与
    `tests/test_harness_termination.py` 断言 `answer` 不含被拒工具名）。
    """
    reasoning, _ = build_reasoning(
        [AIMessage(content='{"tool":"no_such_tool","args":{}}')], executed_tools=set()
    )
    assert reasoning[0]["tool_calls"] == []
    assert "no_such_tool" not in reasoning[0]["content"]


def test_executed_tools_defaults_to_empty():
    """未传 executed_tools 时一律不记工具名（保守：宁缺勿泄露）。"""
    reasoning, _ = build_reasoning([AIMessage(content='{"tool":"step_facts","args":{}}')])
    assert reasoning[0]["tool_calls"] == []


def test_prose_around_proposal_is_kept():
    """提案 JSON 是整条输出时 content 为空；散文包裹时散文保留。"""
    reasoning, _ = build_reasoning([AIMessage(content="我先看看证据\n再看别的")])
    assert reasoning[0]["content"] == "我先看看证据\n再看别的"
    assert reasoning[0]["tool_calls"] == []


def test_prose_answer_has_no_tool_calls():
    reasoning, _ = build_reasoning([AIMessage(content="直接作答")])
    assert reasoning[0]["tool_calls"] == []


def test_parse_error_strips_tool_json_from_content():
    """``ParseError``（args 非法）同样是**提案**且带工具名，原文必须剥离。

    此前这里只堵了 ``Action`` 分支（``args`` 是 dict），``ParseError`` 分支
    ``content = raw`` 会把 ``{"tool":"...","args":[...]}`` 原样留在痕迹里，
    而痕迹是拼进 answer 的——等于从 content 侧开后门泄露工具名。
    """
    reasoning, _ = build_reasoning([AIMessage(content='{"tool":"step_facts","args":"oops"}')])
    assert reasoning[0]["tool_calls"] == []
    assert "step_facts" not in reasoning[0]["content"]
    assert reasoning[0]["content"] == ""


def test_parse_error_with_non_string_tool_strips_content():
    """``tool`` 不是字符串也是 ``ParseError``，同样不得把原文带进 content。"""
    reasoning, _ = build_reasoning([AIMessage(content='{"tool":[1],"args":{}}')])
    assert reasoning[0]["tool_calls"] == []
    assert reasoning[0]["content"] == ""


def test_parse_error_without_tool_keeps_content():
    """``tool`` 为空/假值时 ``parse_action`` 归 ``None``（散文），原文保留——无泄露面。"""
    reasoning, _ = build_reasoning([AIMessage(content='{"tool":"","args":"oops"}')])
    assert reasoning[0]["tool_calls"] == []
    assert reasoning[0]["content"] == '{"tool":"","args":"oops"}'


def test_truncation_is_explicit():
    reasoning, truncated = build_reasoning([AIMessage(content="0123456789")], max_chars=5)
    assert reasoning[0]["content"] == "01234"
    assert truncated is True


def test_no_truncation_when_within_limit():
    reasoning, truncated = build_reasoning([AIMessage(content="短")], max_chars=5)
    assert reasoning[0]["content"] == "短"
    assert truncated is False


def test_truncated_true_if_any_round_overflows():
    messages = [AIMessage(content="短"), AIMessage(content="0123456789")]
    _, truncated = build_reasoning(messages, max_chars=5)
    assert truncated is True


def test_empty_input():
    assert build_reasoning([]) == ([], False)


def test_no_ai_messages():
    assert build_reasoning([SystemMessage(content="s"), HumanMessage(content="h")]) == ([], False)
