from langchain_core.messages import AIMessage

from graphs.javatutor.intent import classify_intent


class FakeModel:
    def __init__(self, content):
        self.content = content

    def invoke(self, messages):
        assert messages[0].type == "system"
        return AIMessage(content=self.content)


def test_classify_valid():
    out = classify_intent("为什么 arr 变了", FakeModel('{"intent":"data_query","confidence":0.9,"reason":"追问变量"}'))
    assert out["intent"] == "data_query"
    assert out["confidence"] == 0.9


def test_classify_low_confidence_falls_back():
    out = classify_intent("随便问问", FakeModel('{"intent":"concept","confidence":0.3,"reason":"不确定"}'))
    assert out["intent"] == "other"
    assert out["reason"] == "低置信度"


def test_classify_invalid_json_falls_back():
    out = classify_intent("你好", FakeModel("not json"))
    assert out["intent"] == "other"
    assert out["reason"] == "分类输出非法"


def test_classify_markdown_fence_stripped():
    out = classify_intent("讲讲 HashMap", FakeModel('```json\n{"intent":"concept","confidence":0.8,"reason":"概念"}```'))
    assert out["intent"] == "concept"
