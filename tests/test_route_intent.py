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

    def test_animate_pattern(self):
        """动画演示类关键词 → Phase 1 无动画路由，回退到 other."""
        state = {
            "user_question": "能给我演示一下排序的过程吗？",
            "has_error": False,
            "compile_error": "",
        }
        result = route_intent(state)
        # Phase 1: 无 animate 关键词匹配，回退到 other
        assert result["intent"] == "other"

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
