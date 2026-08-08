"""Task 7: analyze_node 节点单元测试."""

import json
import pytest

from langchain_core.language_models import FakeListChatModel
from graphs.javatutor.nodes import analyze_node
from graphs.javatutor.prompts import SYSTEM_PROMPT_ANALYZE


def _build_fake_model(responses: list[str]) -> FakeListChatModel:
    return FakeListChatModel(responses=responses)


class TestAnalyzeNode:
    """analyze_node 测试套件: 3 个用例."""

    def test_analyze_bubble_sort(self):
        """冒泡排序分析 → 返回 JSON，包含复杂度、算法、数据结构."""
        state = {
            "source_code": "public class BubbleSort {\n    public static void sort(int[] arr) {\n        for (int i = 0; i < arr.length; i++) {\n            for (int j = 0; j < arr.length - i - 1; j++) {\n                if (arr[j] > arr[j + 1]) {\n                    int tmp = arr[j];\n                    arr[j] = arr[j + 1];\n                    arr[j + 1] = tmp;\n                }\n            }\n        }\n    }\n}",
            "steps": [{"step": 0, "line": 3, "variables": {"arr": [5, 3, 8, 1]}, "output": None}],
            "steps_json": '[{"step": 0, "line": 3, "variables": {"arr": [5, 3, 8, 1]}, "output": null}]',
            "steps_count": 1,
            "has_steps": True,
            "current_step_index": 0,
            "current_line": 3,
            "current_variables": {"arr": [5, 3, 8, 1]},
            "user_question": "",
            "user_id": "test-user-001",
            "compile_error": "",
            "has_error": False,
            "intent": "analyze",
        }
        fake_responses = [
            json.dumps({
                "complexity": {
                    "time": "O(n^2)",
                    "timeExplanation": "双重嵌套循环",
                    "space": "O(1)",
                    "spaceExplanation": "只用了常数个临时变量",
                },
                "algorithms": [{"name": "冒泡排序", "category": "排序"}],
                "dataStructures": [{"name": "数组", "category": "数组"}],
            })
        ]
        model = _build_fake_model(fake_responses)
        result = analyze_node(state, model=model)
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert result["messages"][0].type == "ai"
        answer = result["messages"][0].content

        # 解析 JSON 验证结构
        parsed = json.loads(answer)
        assert "complexity" in parsed
        assert "time" in parsed["complexity"]
        assert "algorithms" in parsed
        assert "dataStructures" in parsed

        # 验证内容
        assert "O(n^2)" in parsed["complexity"]["time"]
        assert parsed["algorithms"][0]["name"] == "冒泡排序"

    def test_analyze_prompt_contains_expected_sections(self):
        """SYSTEM_PROMPT_ANALYZE 包含必有的几个部分."""
        prompt = SYSTEM_PROMPT_ANALYZE
        assert "时间复杂度" in prompt
        assert "空间复杂度" in prompt
        assert "算法" in prompt
        assert "数据结构" in prompt
        assert "JSON" in prompt

    def test_analyze_malformed_json_fallback(self):
        """LLM 返回非 JSON → 兜底 JSON 字符串."""
        state = {
            "source_code": "int x = 1;",
            "steps": [],
            "steps_json": "[]",
            "steps_count": 0,
            "has_steps": False,
            "current_step_index": 0,
            "current_line": 1,
            "current_variables": {},
            "user_question": "",
            "user_id": "test-user-001",
            "compile_error": "",
            "has_error": False,
            "intent": "analyze",
        }
        # FakeListChatModel 返回非 JSON 文本
        model = _build_fake_model(["这不是 JSON 格式的文本"])
        result = analyze_node(state, model=model)
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert result["messages"][0].type == "ai"
        answer = result["messages"][0].content

        # 即使 LLM 返回非 JSON，兜底应生成可解析的 JSON
        parsed = json.loads(answer)
        assert "complexity" in parsed
        assert "algorithms" in parsed
        assert "dataStructures" in parsed