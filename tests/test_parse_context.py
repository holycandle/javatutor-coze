"""Task 1: parse_context 节点单元测试."""

import json
import pytest

from graphs.javatutor.nodes import parse_context


class TestParseContext:
    """解析节点测试套件."""

    def test_parse_full_payload(self):
        """完整 payload 解析，所有字段正确提取."""
        with open("tests/fixtures/sample_payload.json", "r", encoding="utf-8") as f:
            raw = json.load(f)
        raw_str = json.dumps(raw)

        state = parse_context(raw_str)

        assert state["source_code"] == raw["source_code"]
        assert state["steps"] == raw["steps"]
        assert state["steps_count"] == 3
        assert state["has_steps"] is True
        assert state["current_step_index"] == 2
        assert state["current_variables"] == {"n": 4, "i": 0, "j": 1, "arr": "[3, 5, 8, 1]"}
        assert state["user_question"] == "为什么 arr[2] 还是 8？"
        assert state["user_id"] == "a3f2b1c4-5d6e-4f7a-8b9c-0d1e2f3a4b5c"
        assert state["compile_error"] == ""
        assert state["has_error"] is False

    def test_parse_empty_steps(self):
        """无 steps 时 has_steps 为 False."""
        raw = {
            "source_code": "public class Main {}",
            "steps": [],
            "user_question": "你好",
        }
        state = parse_context(json.dumps(raw))

        assert state["has_steps"] is False
        assert state["steps_count"] == 0

    def test_parse_compile_error(self):
        """compile_error 非空时 has_error 为 True."""
        raw = {
            "source_code": "public class Main {",
            "steps": [],
            "compile_error": "error: ';' expected",
            "user_question": "为什么报错",
        }
        state = parse_context(json.dumps(raw))

        assert state["has_error"] is True
        assert state["compile_error"] == "error: ';' expected"

    def test_parse_invalid_json(self):
        """非法 JSON 抛出 ValueError."""
        with pytest.raises(ValueError, match="JSON"):
            parse_context("not a json string {")

    def test_parse_missing_user_id(self):
        """user_id 缺失不报错，has_error 保持 False."""
        raw = {
            "source_code": "public class Main {}",
            "steps": [],
            "user_question": "hello",
        }
        state = parse_context(json.dumps(raw))

        assert state["user_id"] == ""
        assert state["has_error"] is False

    def test_parse_current_variables_extracted(self):
        """current_step_index 对应步骤的 variables 被正确提取."""
        raw = {
            "source_code": "class A {}",
            "steps": [
                {
                    "step": 0,
                    "line": 1,
                    "variables": {"a": 1},
                    "output": None,
                },
                {
                    "step": 1,
                    "line": 2,
                    "variables": {"b": 2},
                    "output": "hello",
                },
            ],
            "current_step_index": 1,
            "user_question": "b 是多少",
        }
        state = parse_context(json.dumps(raw))

        assert state["current_variables"] == {"b": 2}

    def test_parse_user_question_missing(self):
        """user_question 缺失时默认为空字符串，不报错."""
        raw = {
            "source_code": "public class Main {}",
            "steps": [],
        }
        state = parse_context(json.dumps(raw))

        assert state["user_question"] == ""

    def test_parse_steps_json_preserved(self):
        """steps_json 保留原始 JSON 字符串，供后续专家使用."""
        raw = {"source_code": "class A {}", "steps": [{"a": 1}]}
        raw_str = json.dumps(raw)

        state = parse_context(raw_str)

        assert state["steps_json"] == json.dumps(raw["steps"], ensure_ascii=False)


def test_parse_context_derives_conservative_intent():
    """无显式 intent 时，parse_context 用保守规则派生意图."""
    from langchain_core.messages import HumanMessage

    payload = {
        "source_code": "public class A {}",
        "steps": [],
        "current_step_index": 0,
        "current_line": 1,
        "user_question": "为什么 arr 变了？",
        "compile_error": "",
    }
    state = {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]}
    out = parse_context(state)
    assert out["intent"] == "data_query"


def test_parse_context_explicit_intent_wins():
    """显式 intent 优先，不走保守派生."""
    from langchain_core.messages import HumanMessage

    payload = {
        "source_code": "public class A {}",
        "steps": [],
        "user_question": "为什么 arr 变了？",
        "compile_error": "",
        "intent": "concept",
    }
    state = {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]}
    out = parse_context(state)
    assert out["intent"] == "concept"
