"""意图引导段注入主 Agent 系统提示（计划 2026-09-14 D2）。

根因：意图分类的产物在作答路径上没有任何消费者（`_main_system_prompt` 不收 state），
于是「意图识别已判定为概念讲解」在系统里不产生任何效果。
"""

from graphs.javatutor.harness.propose import _main_system_prompt
from graphs.javatutor.prompting.intent_guidance import render_intent_guidance


def test_concept_gets_concept_guidance():
    prompt = _main_system_prompt("concept")
    assert "概念讲解" in prompt
    assert "不要围绕当前执行位置" in prompt
    assert "默认不要调用 `step_facts`" in prompt


def test_data_query_prompt_unchanged():
    """回归保护：data_query / 空意图不追加任何段，既有基线逐字不变。"""
    assert _main_system_prompt("data_query") == _main_system_prompt("")


def test_debug_and_other_get_their_own_guidance():
    assert "错误诊断" in _main_system_prompt("debug")
    assert "通用提问" in _main_system_prompt("other")
    # 未知意图不得抛错，也不得凭空造段
    assert _main_system_prompt("未定义意图") == _main_system_prompt("")


def test_render_intent_guidance_scope():
    assert render_intent_guidance("data_query") == ""
    assert render_intent_guidance("") == ""
    assert render_intent_guidance(None) == ""
    assert render_intent_guidance("concept")
