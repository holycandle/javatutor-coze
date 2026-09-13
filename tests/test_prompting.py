import importlib

from graphs.javatutor.prompting import versions
from graphs.javatutor.prompting.contracts import get_contract
from graphs.javatutor.prompting.fewshots import get_few_shots
from graphs.javatutor.prompting.glossary import build_glossary_block
from graphs.javatutor.prompts import SYSTEM_PROMPT_MAIN_AGENT


def test_main_agent_prompt_forbids_inline_tool_json():
    """主 Agent 提示词必须明令工具 JSON 独占一条消息。

    这是 ``_strip_leaked_json`` 规则 0 的**上游**约束（规则 0 只是兜底）：模型走
    「工具 JSON + 散文」这条路时 ``parse_action`` 返回 ``None``，那一轮的工具
    **根本没有被调用**——若发生在第一轮，回答会缺证据，比渲染问题更严重。
    """
    assert "工具调用 JSON 必须独占一条消息" in SYSTEM_PROMPT_MAIN_AGENT
    assert "回答正文中不得出现工具调用 JSON" in SYSTEM_PROMPT_MAIN_AGENT


def test_main_agent_prompt_keeps_tool_call_examples():
    """只加约束、不删示例：示例是模型学会工具协议的依据，删了工具调用率会下降。

    见 docs/devlog/2026-09-08-raise-fetch-tool-call-rate.md。
    """
    assert '"tool": "fetch_execution_context", "args": {}' in SYSTEM_PROMPT_MAIN_AGENT
    assert '"tool": "step_facts", "args": {"step_index": 1, "line": 4}' in SYSTEM_PROMPT_MAIN_AGENT


def test_prompt_version_defined():
    assert versions.PROMPT_VERSION.startswith("2026-08-13")


def test_all_prompting_modules_share_version():
    for name in ("glossary", "contexts", "fewshots", "contracts"):
        module = importlib.import_module(f"graphs.javatutor.prompting.{name}")
        assert module.PROMPT_VERSION == versions.PROMPT_VERSION


def test_glossary_block_contains_domain_terms():
    block = build_glossary_block()
    assert "TraceEngine" in block
    assert "变量快照" in block
    assert "堆对象" in block
    assert "栈帧" in block
    assert "控制流" in block


def test_few_shots_max_two_and_marked():
    for intent in ("data_query", "concept", "debug", "other"):
        shots = get_few_shots(intent)
        assert 0 < len(shots) <= 2
        for shot in shots:
            assert "示例" in shot


def test_contracts_require_grounding():
    assert "哪一步" in get_contract("data_query")
    assert "行号" in get_contract("debug")
    assert "源代码" in get_contract("concept")


def test_no_animation_prompt_constant():
    """动画相关提示词常量已移除."""
    import graphs.javatutor.prompts as prompts

    assert not hasattr(prompts, "SYSTEM_PROMPT_ANIMATE")
    assert not hasattr(prompts, "ANIMATE_GUIDE_MESSAGE")
