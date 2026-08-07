"""Task 3: 专家节点单元测试.

使用 FakeModel 注入验证:
1. 各节点返回 answer 字段
2. animate 占位返回正确文本
3. 消息结构正确（system + user）
4. _run_expert 支持 model 参数注入
"""

import json
import pytest

from langchain_core.language_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from graphs.javatutor.nodes import (
    animate_node,
    concept_node,
    data_query_node,
    debug_node,
    other_node,
)
from graphs.javatutor.prompts import (
    SYSTEM_PROMPT_CONCEPT,
    SYSTEM_PROMPT_DATA_QUERY,
    SYSTEM_PROMPT_DEBUG,
    SYSTEM_PROMPT_OTHER,
)


class FakeExpertLLM(FakeListChatModel):
    """注入专家 LLM，返回固定前缀以区分专家."""

    response_prefix: str = "Expert response: "

    def __init__(self, expert_name: str, **kwargs):
        responses = [f"[{expert_name}] 分析中，请稍候..."]
        super().__init__(responses=responses, **kwargs)
        self.response_prefix = f"[{expert_name}] "


def _build_fake_model(expert_name: str) -> FakeExpertLLM:
    return FakeExpertLLM(expert_name)


# === 基础测试状态 ===

BASE_STATE = {
    "source_code": "public class BubbleSort {\n    public static void main(String[] args) {\n        int[] arr = {5, 3, 8, 1};\n    }\n}",
    "steps": [
        {
            "step": 0,
            "line": 3,
            "variables": {"arr": "[5, 3, 8, 1]"},
            "heap": {},
            "stackFrames": [],
            "output": None,
        },
        {
            "step": 1,
            "line": 4,
            "variables": {"arr": "[3, 5, 8, 1]"},
            "heap": {},
            "stackFrames": [],
            "output": None,
        },
    ],
    "steps_json": json.dumps(
        [
            {"step": 0, "variables": {"arr": "[5, 3, 8, 1]"}},
            {"step": 1, "variables": {"arr": "[3, 5, 8, 1]"}},
        ],
        ensure_ascii=False,
    ),
    "steps_count": 2,
    "has_steps": True,
    "current_step_index": 1,
    "current_line": 4,
    "current_variables": {"arr": "[3, 5, 8, 1]"},
    "user_question": "为什么第2步 arr 变了？",
    "user_id": "test-user-001",
    "compile_error": "",
    "has_error": False,
    "intent": "",
    "answer": "",
}


class TestExpertNodes:
    """专家节点测试套件."""

    def test_data_query_returns_answer(self):
        """data_query 节点返回包含 answer 的 dict."""
        state = {**BASE_STATE, "user_question": "为什么第2步 arr 变了？"}
        result = data_query_node(state, model=_build_fake_model("data_query"))

        assert "answer" in result
        assert "[data_query]" in result["answer"]

    def test_concept_returns_answer(self):
        """concept 节点返回包含 answer 的 dict."""
        state = {**BASE_STATE, "user_question": "冒泡排序是什么原理？"}
        result = concept_node(state, model=_build_fake_model("concept"))

        assert "answer" in result
        assert "[concept]" in result["answer"]

    def test_debug_with_error(self):
        """debug 节点使用 compile_error 上下文."""
        state = {
            **BASE_STATE,
            "compile_error": "error: ';' expected at line 5",
            "has_error": True,
            "user_question": "为什么编译报错？",
        }
        result = debug_node(state, model=_build_fake_model("debug"))

        assert "answer" in result
        assert "[debug]" in result["answer"]

    def test_other_fallback(self):
        """other 节点兜底返回."""
        state = {**BASE_STATE, "user_question": "你好！"}
        result = other_node(state, model=_build_fake_model("other"))

        assert "answer" in result
        assert "[other]" in result["answer"]

    def test_animate_placeholder(self):
        """animate 节点 Phase 1 返回占位文本."""
        state = {**BASE_STATE, "user_question": "能演示一下吗？"}
        result = animate_node(state)

        assert "answer" in result
        assert "【功能待开发】" in result["answer"]
        # 不调用 LLM，直接返回占位文本
        assert "动画生成" in result["answer"]

    def test_run_expert_accepts_model_param(self):
        """_run_expert 接受 model 参数注入 FakeModel."""
        from graphs.javatutor.nodes import _run_expert

        state = {**BASE_STATE, "user_question": "测试"}
        result = _run_expert(state, "concept", model=_build_fake_model("concept"))

        assert "answer" in result
        assert "[concept]" in result["answer"]

    def test_build_expert_messages_structure(self):
        """验证专家消息构建: system + user."""
        from graphs.javatutor.nodes import _build_expert_messages

        messages = _build_expert_messages(BASE_STATE, "debug")

        assert len(messages) >= 2
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)
        # system prompt 包含专家角色定义
        assert SYSTEM_PROMPT_DEBUG[:20] in messages[0].content
