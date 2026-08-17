"""Task 3: analyze_code 确定性前置节点测试."""

from langchain_core.messages import AIMessage

from graphs.javatutor.analyze import analyze_code_node


class FakeModel:
    def __init__(self, content):
        self.content = content

    def invoke(self, messages):
        return AIMessage(content=self.content)


def test_analyze_runs_when_source_code_present():
    state = {"source_code": "public class A {}", "intent": ""}
    out = analyze_code_node(state, model=FakeModel('{"complexity": {"time": "O(1)"}, "algorithms": [], "dataStructures": []}'))
    assert out["analysis_result"]["complexity"]["time"] == "O(1)"


def test_analyze_skips_without_source_code():
    out = analyze_code_node({"source_code": "", "intent": ""})
    assert out["analysis_result"] is None


def test_analyze_explicit_returns_message():
    state = {"source_code": "public class A {}", "intent": "analyze"}
    out = analyze_code_node(state, model=FakeModel('{"complexity": {"time": "O(1)"}}'))
    assert out["messages"][0].content.startswith("{")
