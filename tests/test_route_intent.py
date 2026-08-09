"""Task 2: route_intent 节点单元测试."""

import pytest

from graphs.javatutor.nodes import route_intent


class TestRouteIntent:
    """意图路由测试套件: 7 个用例覆盖所有分支."""

    def test_compile_error_shortcut(self):
        """有 compile_error → debug（短路，不走关键词）."""
        state = {
            "user_question": "你好",
            "has_error": True,
            "compile_error": "error: ';' expected",
        }
        result = route_intent(state)
        assert result["intent"] == "debug"

    def test_debug_keyword(self):
        """调试类关键词 → 由于 Phase 1 无 debug 关键词路由，匹配 data_query 的'为什么'关键词."""
        state = {
            "user_question": "为什么程序报错",
            "has_error": False,
            "compile_error": "",
        }
        result = route_intent(state)
        # Phase 1: compile_error 为空时，'为什么'匹配 data_query 关键词
        assert result["intent"] == "data_query"

    def test_data_query_pattern(self):
        """数据查询类关键词 → data_query."""
        state = {
            "user_question": "为什么第2步 arr 变成了 [3, 5, 8, 1]？",
            "has_error": False,
            "compile_error": "",
        }
        result = route_intent(state)
        assert result["intent"] == "data_query"

    def test_concept_pattern(self):
        """算法原理类关键词 → concept."""
        state = {
            "user_question": "冒泡排序的时间复杂度是多少？",
            "has_error": False,
            "compile_error": "",
        }
        result = route_intent(state)
        assert result["intent"] == "concept"

    def test_animate_keyword_guides_button(self):
        """动画演示类关键词 → animate_guide（引导用户点击按钮）."""
        state = {
            "user_question": "能给我演示一下排序的过程吗？",
            "has_error": False,
            "compile_error": "",
        }
        result = route_intent(state)
        assert result["intent"] == "animate_guide"

    def test_animate_explicit_intent(self):
        """显式 intent: animate → animate."""
        state = {
            "user_question": "",
            "has_error": False,
            "compile_error": "",
            "intent": "animate",
        }
        result = route_intent(state)
        assert result["intent"] == "animate"

    def test_other_fallback(self):
        """无法归类 → other."""
        state = {
            "user_question": "你好呀",
            "has_error": False,
            "compile_error": "",
        }
        result = route_intent(state)
        assert result["intent"] == "other"

    def test_empty_question_fallback(self):
        """空问题 → other."""
        state = {
            "user_question": "",
            "has_error": False,
            "compile_error": "",
        }
        result = route_intent(state)
        assert result["intent"] == "other"

    # ── 显式 intent 测试（Phase 2: analyze 专家） ──

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
        """显式 intent 覆盖关键词匹配."""
        state = {
            "user_question": "为什么 arr[0] 变了",
            "has_error": False,
            "compile_error": "",
            "intent": "concept",
        }
        result = route_intent(state)
        assert result["intent"] == "concept"
