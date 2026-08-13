from langchain_core.messages import AIMessage

from graphs.javatutor.critic import critic_node, revise_node
from graphs.javatutor.prompting.contexts import build_facts_block


class FakeModel:
    def __init__(self, content):
        self.content = content

    def invoke(self, messages):
        return AIMessage(content=self.content)


BASE = {
    "answer": "根据第 2 步，arr[1] 变成了 8",
    "current_variables": {"arr": [3, 5, 1]},
    "compile_error": "",
    "steps_json": '[{"step": 1, "variables": {"arr": [3, 5, 1]}}]',
    "user_question": "为什么 arr 变了？",
    "retrieved_chunks": [],
}


def test_critic_passes():
    out = critic_node(BASE, FakeModel('{"pass": true, "issues": []}'))
    assert out["critic_passed"] is True


def test_critic_fails_with_issues():
    out = critic_node(BASE, FakeModel('{"pass": false, "issues": ["变量值 8 与数据不符"]}'))
    assert out["critic_passed"] is False
    assert "变量值" in out["critic_feedback"]


def test_critic_skips_on_bad_output():
    out = critic_node(BASE, FakeModel("not json"))
    assert out["critic_passed"] is True
    assert out["critic_skipped"] is True


def test_revise_returns_revised():
    out = revise_node(BASE, FakeModel("根据第 2 步，arr[1] 变成了 5"))
    assert out["revised"] is True
    assert out["revised_answer"] == "根据第 2 步，arr[1] 变成了 5"


def test_facts_include_heap_stack_output():
    state = {
        **BASE,
        "has_steps": True,
        "steps": [
            {"step": 1, "line": 3, "variables": {"arr": [3, 5, 1]}, "heap": {"h1": {"type": "Object"}}, "stackFrames": [{"method": "main"}], "output": "out"}
        ],
        "current_step_index": 0,
        "current_line": 3,
        "source_code": "public class A {\n    void run() {\n        int x = 1;\n    }\n}",
    }
    facts = build_facts_block(state)
    assert "堆对象" in facts
    assert "栈帧" in facts
    assert "输出" in facts
    assert "int x = 1" in facts
