import importlib

from graphs.javatutor.prompting import versions
from graphs.javatutor.prompting.contracts import get_contract
from graphs.javatutor.prompting.fewshots import get_few_shots
from graphs.javatutor.prompting.glossary import build_glossary_block


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
