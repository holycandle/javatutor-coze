"""代码优化引导守卫：两步式约束、kind/goal 闭集、few-shot 样本 JSON 合法。

改动引导块或 few-shot 样本后，本文件兜底「agent 一步到位给代码」与「样本 JSON 坏掉」两类回归。
规格见 docs/spec/2026-09-10-coze-agent-code-optimization.md。
"""

import json
import re
from pathlib import Path

import pytest

from graphs.javatutor.prompting.main_fewshots import get_main_few_shots
from graphs.javatutor.prompting.optimization import GOALS, render_optimization_guidance


def _repo_root() -> Path:
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    raise FileNotFoundError("未找到仓库根（pyproject.toml）")


# 前端 utils/editSuggestion.js 的 GOALS 字面量（闭集真实来源，同 test_panel_sync 的跨仓读法）
FRONTEND_EDIT_SUGGESTION = (
    _repo_root() / ".." / "javatutor" / "frontend" / "src" / "utils" / "editSuggestion.js"
)


def _frontend_goals() -> dict:
    """从后端仓库直接读前端 GOALS——闭集是跨仓契约，手抄副本自证不了漂移。"""
    source = FRONTEND_EDIT_SUGGESTION.read_text(encoding="utf-8")
    block = re.search(r"export const GOALS = \{(.*?)\}", source, re.S)
    assert block, "前端 editSuggestion.js 未找到 `export const GOALS = {...}` 字面量"
    return dict(re.findall(r"""(\w+)\s*:\s*['"]([^'"]*)['"]""", block.group(1)))


def test_goal_enum_matches_frontend():
    """goal 闭集是跨仓契约：coze 引导与前端 label 必须完全一致。

    前端单方面增删 goal 时，前端会静默丢弃该 option（整块按正文展示、无报错），
    所以这条必须真的读前端文件，而不是比对手抄副本。
    """
    if not FRONTEND_EDIT_SUGGESTION.exists():
        pytest.skip("前端 editSuggestion.js 不存在，跳过跨仓比对")
    assert _frontend_goals(), "前端 GOALS 解析为空，检查字面量格式"
    assert GOALS == _frontend_goals()


def test_optimization_guidance_lists_goal_enum():
    text = render_optimization_guidance()
    for goal in GOALS:
        assert goal in text


def test_optimization_guidance_twostep_and_kinds():
    """两步式：第一步只给 options（不得给代码），第二步才给 replace 整份代码。"""
    text = render_optimization_guidance()
    assert "第一步" in text and "第二步" in text
    assert '"kind":"options"' in text
    assert '"kind":"replace"' in text
    assert "不得出现优化后的代码" in text
    # code 必须是完整可编译的整份文件，不许占位省略
    assert "完整" in text
    assert "占位" in text


def test_optimization_guidance_requires_target_for_multi():
    text = render_optimization_guidance()
    assert "多文件模式必填" in text


def test_optimization_guidance_keeps_patch_path():
    """局部修改仍走 patch 形态，不被 replace 取代。"""
    text = render_optimization_guidance()
    assert "old_string" in text and "new_string" in text
    assert "每答最多一个【编辑建议】块" in text


def _extract_block_json(sample: str) -> dict:
    """取出样本中【编辑建议】块后的 JSON（块必须是样本最后内容）。"""
    assert "【编辑建议】" in sample
    after = sample.split("【编辑建议】")[1].strip()
    assert after.startswith("{"), "【编辑建议】块后不应再有正文"
    return json.loads(after)


def test_main_fewshots_optimization_samples_valid():
    shots = get_main_few_shots()
    joined = "\n".join(shots)
    assert '"kind":"options"' in joined
    assert '"kind":"replace"' in joined

    kinds = []
    for s in shots:
        if "【编辑建议】" not in s:
            continue
        parsed = _extract_block_json(s)  # JSON 不合法会直接抛错
        kinds.append(parsed["kind"])
        if parsed["kind"] == "options":
            assert parsed["options"], "options 不得为空"
            assert len(parsed["options"]) <= 3
            for o in parsed["options"]:
                assert o["goal"] in GOALS, "options 的 goal 必须落在闭集内"
            assert "code" not in parsed, "第一步方案卡不得含代码"
        else:
            assert parsed["kind"] == "replace"
            assert parsed["goal"] in GOALS
            assert parsed["target"], "replace 必须给出 target"
            code = parsed["code"]
            assert code.strip(), "replace 的 code 不得为空"
            assert "..." not in code, "code 不得用省略号占位"
            assert "class Solution" in code

    assert sorted(set(kinds)) == ["options", "replace"]


def test_main_system_prompt_injects_optimization():
    from graphs.javatutor.main_agent import _main_system_prompt

    prompt = _main_system_prompt()
    assert "代码优化" in prompt
    assert "render_optimization_guidance" not in prompt  # 注入的是渲染结果，不是函数名
    assert '"kind":"options"' in prompt


@pytest.mark.parametrize("block", ["【编辑建议】", "【视角导航】"])
def test_critic_and_revise_prompts_cover_struct_blocks(block):
    """critic 不得因 kind 判失败；revise 必须原样保留结构化块。"""
    from graphs.javatutor.prompts import SYSTEM_PROMPT_CRITIC, SYSTEM_PROMPT_REVISE

    assert block in SYSTEM_PROMPT_CRITIC
    assert block in SYSTEM_PROMPT_REVISE
    assert "kind" in SYSTEM_PROMPT_CRITIC
    assert "原样保留" in SYSTEM_PROMPT_REVISE
