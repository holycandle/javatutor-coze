"""Task 7: 主 Agent 工具循环测试."""

from langchain_core.messages import AIMessage

from graphs.javatutor.main_agent import _format_step_facts, main_agent_node


def test_format_step_facts_is_clean_labeled_text():
    """step_facts 结果应渲染为可读文本并用 1-based 步骤标签，避免模型解析原始 JSON。"""
    result = {
        "error": "",
        "evidence": {
            "variables": {"arr": [3, 5, 8], "n": 3, "i": 0, "j": 0, "temp": 5},
            "heap": {},
            "stackFrames": [{"method": "main"}],
            "output": None,
            "line": 9,
            "line_text": "arr[j] = arr[j+1];",
        },
        "diff": [{"key": "arr", "before": [5, 3, 8], "after": [3, 5, 8]}],
    }
    text = _format_step_facts({"step_index": 6}, result)
    # 关键：带 0-based 提示的 1-based 标签，与用户/回答的「第 7 步」对齐
    assert "第 7 步（step_index=6）" in text
    assert "变量" in text
    assert "[3, 5, 8]" in text
    assert "arr[j] = arr[j+1];" in text
    # 明确给出 diff，模型可直接读「这一步做了什么」，不必再反复试探
    assert "arr" in text and "[5, 3, 8] → [3, 5, 8]" in text


def test_main_agent_repeat_same_step_gets_answer_nudge():
    """同一步骤被再次查询时，应向模型注入「请直接作答」提示，打断重复试探。"""
    model = RecordingModel(
        [
            '{"tool": "step_facts", "args": {"step_index": 1}}',
            '{"tool": "step_facts", "args": {"step_index": 1}}',
            "根据第 2 步，x 变成了 2",
        ]
    )
    out = main_agent_node(STATE, model=model)
    assert out["tool_rounds"] == 3
    # 第二次查询同一步骤后，提示在下一轮消息中出现（打断重复试探）
    last_human = model.seen[-1][-1].content
    assert "不要重复查询同一步骤" in last_human
    # 证据文本应带 1-based 标签
    assert "第 2 步（step_index=1）" in last_human
    assert "x 变成了 2" in out["answer"]


class SequenceModel:
    def __init__(self, responses):
        self.responses = list(responses)

    def invoke(self, messages):
        return AIMessage(content=self.responses.pop(0))


class FakeModel:
    """每次调用都返回同一固定内容（用于单轮即终止/重复调用的场景）。"""

    def __init__(self, content):
        self.content = content

    def invoke(self, messages):
        return AIMessage(content=self.content)


STATE = {
    "context_built": "[Evidence]\n步骤数据",
    "steps": [
        {"step": 0, "line": 3, "variables": {"x": 1}},
        {"step": 1, "line": 3, "variables": {"x": 2}},
    ],
    "current_step_index": 1,
}


class RecordingModel:
    """记录每次收到的 messages（用于断言 model 上下文内容）。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.seen = []

    def invoke(self, messages):
        self.seen.append(messages)
        return AIMessage(content=self.responses.pop(0))


def test_main_agent_calls_step_facts_then_answers():
    model = SequenceModel(['{"tool": "step_facts", "args": {"step_index": 1}}', "根据第 2 步，x 变成了 2"])
    out = main_agent_node(STATE, model=model)
    assert out["tool_rounds"] == 2
    assert out["tool_calls"][0]["tool"] == "step_facts"
    assert out["tool_calls"][0]["args"] == {"step_index": 1}
    assert "result" in out["tool_calls"][0]  # 返回值被截断记录，供决策痕迹诊断
    assert "x 变成了 2" in out["answer"]


def test_main_agent_direct_answer():
    out = main_agent_node(STATE, model=SequenceModel(["直接回答"]))
    assert out["tool_rounds"] == 1
    assert out["answer"] == "直接回答"


def test_main_agent_stops_after_three_rounds():
    model = SequenceModel(['{"tool": "step_facts", "args": {}}'] * 5)
    out = main_agent_node(STATE, model=model)
    assert out["tool_rounds"] == 3


def test_main_agent_records_step_memories():
    model = SequenceModel(['{"tool": "step_facts", "args": {"step_index": 1}}', "根据第 2 步，x 变成了 2"])
    out = main_agent_node(STATE, model=model)
    assert len(out["step_memories"]) == 1
    assert out["step_memories"][0]["importance"] == 0.8
    assert "diff" in out["step_memories"][0]["content"]


def test_main_agent_tool_error_does_not_record_memory():
    model = SequenceModel(['{"tool": "step_facts", "args": {"step_index": 99}}', "无法查询，但上下文有分析结果"])
    out = main_agent_node(STATE, model=model)
    assert out["step_memories"] == []
    # 3 轮全是工具调用、无最终回答时兜底
    assert out["answer"]


def test_main_agent_invalid_args_returns_error_not_crash():
    """step_facts 收到未知键时返回结构化 error，而非抛 TypeError."""
    model = SequenceModel(['{"tool": "step_facts", "args": {"bogus_key": 1}}', "根据第 1 步回答"])
    out = main_agent_node(STATE, model=model)
    assert "error" in out["answer"] or out["answer"]
    assert out["tool_rounds"] == 2
    assert out["tool_calls"][0]["tool"] == "step_facts"


def test_main_agent_unknown_tool_not_leaked_as_answer():
    """未知工具名追加兜底提示继续循环，而非把工具 JSON 当最终回答."""
    model = SequenceModel(
        ['{"tool": "no_such_tool", "args": {}}', '{"tool": "no_such_tool", "args": {}}', "最终直接回答"]
    )
    out = main_agent_node(STATE, model=model)
    assert out["tool_rounds"] == 3
    assert out["tool_calls"] == [
        {"tool": "no_such_tool", "args": {}},
        {"tool": "no_such_tool", "args": {}},
    ]
    assert "最终直接回答" in out["answer"]
    # JSON 工具调用不应出现在最终回答里
    assert "no_such_tool" not in out["answer"]


def test_main_agent_dispatches_fetch_execution_context():
    model = SequenceModel(
        ['{"tool": "fetch_execution_context", "args": {"run_id": "r1"}}', "已读取代码"]
    )
    state = {
        "run_id": "r1",
        "source_code": "public class A {}",
        "steps": [{"step_index": 0, "variables": {"x": 1}}],
        "current_step_index": 0,
        "current_line": 1,
        "context_built": "context",
    }
    out = main_agent_node(state, model=model)
    assert any(tc["tool"] == "fetch_execution_context" for tc in out["tool_calls"])
    assert out["fetched_context"]["run_id"] == "r1"


def test_main_agent_fetch_failure_appends_error_and_continues():
    out = main_agent_node(
        {"run_id": "", "source_code": "", "steps": [], "context_built": "c"},
        model=FakeModel('{"tool": "fetch_execution_context", "args": {}}'),
    )
    assert out["answer"]
