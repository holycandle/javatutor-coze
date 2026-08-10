"""Task 2 + Task 6: route_intent 节点单元测试."""

import pytest

from langchain_core.messages import AIMessage

from graphs.javatutor.nodes import route_intent


class FakeClassifierModel:
    """模拟 LLM 分类器，根据 system prompt 内容返回不同分类。"""

    def __init__(self, intent="concept", confidence=0.9, reason="概念问题"):
        self._response = json_module_dumps(intent, confidence, reason)

    def invoke(self, messages):
        return AIMessage(content=self._response)


def json_module_dumps(intent, confidence, reason):
    import json
    return json.dumps({"intent": intent, "confidence": confidence, "reason": reason})


class TestRouteIntent:
    """意图路由测试套件."""

    def test_compile_error_shortcut(self):
        """有 compile_error → debug（短路，不走 LLM 分类）."""
        state = {
            "user_question": "你好",
            "has_error": True,
            "compile_error": "error: ';' expected",
        }
        result = route_intent(state)
        assert result["intent"] == "debug"
        assert result["intent_confidence"] == 1.0

    def test_explicit_intent_analyze(self):
        """显式 intent: analyze → analyze."""
        state = {
            "user_question": "请分析复杂度",
            "has_error": False,
            "compile_error": "",
            "intent": "analyze",
        }
        result = route_intent(state)
        assert result["intent"] == "analyze"

    def test_explicit_intent_overrides_compile_error(self):
        """显式 intent 优先级高于 compile_error（后端主动指定）."""
        state = {
            "user_question": "",
            "has_error": True,
            "compile_error": "error: ';' expected",
            "intent": "analyze",
        }
        result = route_intent(state)
        assert result["intent"] == "analyze"

    def test_explicit_intent_overrides_keyword(self):
        """显式 intent 覆盖 LLM 分类."""
        state = {
            "user_question": "为什么 arr[0] 变了",
            "has_error": False,
            "compile_error": "",
            "intent": "concept",
        }
        result = route_intent(state)
        assert result["intent"] == "concept"

    def test_explicit_intent_animate(self):
        """显式 intent: animate → animate."""
        state = {
            "user_question": "",
            "has_error": False,
            "compile_error": "",
            "intent": "animate",
        }
        result = route_intent(state)
        assert result["intent"] == "animate"

    # ── Task 6: LLM 分类测试 ──

    def test_route_intent_uses_llm_classifier(self):
        """非显式 intent、无 compile_error → 调用 LLM 分类器."""
        state = {"user_question": "讲讲 HashMap", "compile_error": "", "intent": ""}
        out = route_intent(state, model=FakeClassifierModel(intent="concept", confidence=0.9))
        assert out["intent"] == "concept"
        assert out["intent_confidence"] == 0.9

    def test_route_intent_llm_classifies_data_query(self):
        """LLM 分类 → data_query."""
        state = {"user_question": "为什么 arr 变了", "compile_error": "", "intent": ""}
        out = route_intent(state, model=FakeClassifierModel(intent="data_query", confidence=0.85))
        assert out["intent"] == "data_query"

    def test_route_intent_llm_low_confidence_falls_back(self):
        """LLM 低置信度 → other."""
        state = {"user_question": "随便问问", "compile_error": "", "intent": ""}
        out = route_intent(state, model=FakeClassifierModel(intent="concept", confidence=0.3))
        assert out["intent"] == "other"
        assert out["fallback_reason"] == "低置信度"

    def test_route_intent_explicit_wins_over_llm(self):
        """显式 intent 优先于 LLM 分类（即使有 compile_error）."""
        state = {"user_question": "为什么 arr 变了", "compile_error": "error", "intent": "analyze"}
        out = route_intent(state)
        assert out["intent"] == "analyze"
