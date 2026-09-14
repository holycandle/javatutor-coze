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

# 前端 utils/optimization.js 的 buildRetryPrompt（返修提问模板，跨仓握手见下方两个标记）
FRONTEND_OPTIMIZATION = (
    _repo_root() / ".." / "javatutor" / "frontend" / "src" / "utils" / "optimization.js"
)

# 返修提问的两个握手标记：coze 引导据此认出返修提问，前端 buildRetryPrompt 据此写出该提问。
# 两侧测试各自硬编码这两个短语——任何一端改字，另一端必须红。
RETRY_MARK_HEADER = "上一版优化代码没有通过编译/运行校验"
RETRY_MARK_CANDIDATE = "上一版候选代码"

# 第二步标记：**唯一**的「这是第二步提问」判别器，前端 buildGoalPrompt 写进提问、
# coze 引导据此认出。同样两侧硬编码字面量（跨仓握手）。
STEP2_MARKER_LITERAL = "【优化第二步】"


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


def test_goal_enum_includes_comprehensive():
    """comprehensive 只用于第二步 replace；方案卡不得产出它（否则成无法再拆的选项）。"""
    assert GOALS["comprehensive"] == "综合"
    assert len(GOALS) == 6
    from graphs.javatutor.prompting.optimization import CARD_GOALS

    assert "comprehensive" not in CARD_GOALS
    assert set(CARD_GOALS) | {"comprehensive"} == set(GOALS)


def test_guidance_states_hard_direction_constraint():
    """第二步方向硬约束：白名单只做所列、黑名单不得顺手改、多方向记 comprehensive。

    这三条是「用户在方案卡上勾了什么，代码里就只改什么」的唯一保险；引导丢了它们，
    agent 会退回「顺手全优化」——正是 F1–F3 要修的行为。
    """
    text = render_optimization_guidance()
    assert "只做所列方向" in text
    assert "不得改造" in text
    assert "不得顺手改" in text
    assert "不要顺带做" in text
    assert "comprehensive" in text
    assert "rationale" in text
    # 引导里的白名单表述必须与前端模板同款，否则 agent 认不出用户提问里的约束
    assert "只做" in text and "不要顺带做其他方向的改动" in text


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
                assert o["goal"] != "comprehensive", "comprehensive 只用于第二步 replace"
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


def test_fewshots_second_round_states_exclusions():
    """第二步样例必须示范「白名单 + 黑名单」两种提问形态，且多方向记 comprehensive。

    样例是 agent 实际模仿的锚点：只改引导不改样例，agent 仍会照旧样例把用户没勾的方向一起改。
    """
    replace_goals = []
    for s in get_main_few_shots():
        if "【编辑建议】" not in s:
            continue
        parsed = _extract_block_json(s)
        if parsed["kind"] != "replace":
            continue
        replace_goals.append(parsed["goal"])
        question = s.split("【编辑建议】")[0]
        assert "只做" in question, "第二步样例的提问必须是「只做…」模板"
        assert "不要顺带做其他方向的改动" in question or "只做以下方向" in question, (
            "第二步样例必须示范黑名单（单方向）或多方向白名单"
        )

    assert "comprehensive" in replace_goals, "缺少多方向样例（goal=comprehensive）"
    assert len([g for g in replace_goals if g != "comprehensive"]) >= 1, "缺少单方向样例"
    # 单方向样例的黑名单必须与引导同款措辞
    joined = "\n".join(get_main_few_shots())
    assert "不要顺带做其他方向的改动（例如：" in joined


def test_step2_marker_is_the_discriminator():
    """判别器只有一个：提问是否以【优化第二步】起头（计划 2026-09-14 D1）。

    旧判别依据「措辞像已指明目标」与第二步提问形状**直接冲突**——同形输入被要求走两条分支，
    模型无法判别，实测表现为「再给一次一模一样的方案卡、一行代码都没有」的死循环。
    """
    text = render_optimization_guidance()
    assert STEP2_MARKER_LITERAL in text
    assert "判别器只有一个" in text
    # 标记存在 ⇒ 交付 replace、禁止再出方案卡
    assert "禁止再出 `options`" in text


def test_step2_marker_matches_frontend_literal():
    """标记是**跨仓握手字面量**：前端 `buildGoalPrompt` 写什么，coze 才认得什么。

    一侧改字另一侧静默失配（agent 退回「再给一张方案卡」），所以这里真的读前端文件比对。
    """
    from graphs.javatutor.prompting.optimization import STEP2_MARKER

    assert STEP2_MARKER == STEP2_MARKER_LITERAL
    if not FRONTEND_EDIT_SUGGESTION.exists():
        pytest.skip("前端 editSuggestion.js 不存在，跳过跨仓比对")
    frontend = FRONTEND_EDIT_SUGGESTION.read_text(encoding="utf-8")
    assert f"export const STEP2_MARKER = '{STEP2_MARKER_LITERAL}'" in frontend, (
        "前端 editSuggestion.js 的 STEP2_MARKER 与 coze 引导不再一致"
    )
    assert "return `${STEP2_MARKER}" in frontend, "前端 buildGoalPrompt 未把标记写进提问开头"


def test_no_contradicting_bullet():
    """旧判别依据那条冲突条目必须消失（保留它 = 保留 Bug D）。"""
    text = render_optimization_guidance()
    assert "用户已指明目标" not in text
    assert "同样先出方案卡" not in text
    # 但「无标记时先出方案卡」这一既有产品决策**保留**，只是改用标记表述
    assert "没有标记就是第一步" in text


def test_few_shots_step2_questions_carry_marker():
    """两条第二步示例的**提问文本**必须与前端模板同形（否则 few-shot 教的是另一种形状）。"""
    marked = 0
    for s in get_main_few_shots():
        if "【编辑建议】" not in s or '"kind":"replace"' not in s:
            continue
        assert f"问：{STEP2_MARKER_LITERAL}" in s, "第二步示例的提问必须以【优化第二步】起头"
        assert "只做" in s.split("【编辑建议】")[0]
        marked += 1
    assert marked == 2, f"第二步示例应为 2 条（单方向 + 多方向），实际 {marked}"


def _retry_section() -> str:
    """取出「候选返修」段本体（到「局部修改不适用两步式」为止，避免尾段其它措辞干扰断言）。"""
    text = render_optimization_guidance()
    assert "**候选返修" in text, "引导缺少「候选返修」段"
    section = text.split("**候选返修", 1)[1]
    return section.split("**局部修改不适用两步式**", 1)[0]


def test_guidance_has_retry_section():
    """门禁失败后前端会重发提问，coze 必须认得并照办（否则 agent 只解释错误、不给代码）。"""
    text = render_optimization_guidance()
    assert "候选返修" in text
    assert "保持一致" in text
    section = _retry_section()
    assert 'kind:"replace"' in section
    assert "goal" in section and "target" in section


def test_retry_section_is_replace_only_not_a_second_twostep():
    """返修不得回退到两步式的第一步：不提 options、不提「第一步」。"""
    section = _retry_section()
    assert "options" not in section
    assert "第一步" not in section


def test_retry_section_allows_refusing_without_a_block():
    """前端 F5：拿不到 replace 块时保留失败卡片——故 coze 侧必须允许「只说明原因、不给块」。"""
    section = _retry_section()
    assert "不要" in section and "replace 块" in section


def test_retry_markers_match_frontend_template():
    """返修提问的两个标记必须与前端 `buildRetryPrompt` 逐字一致（跨仓字面包含）。

    前端模板写什么，agent 才认得什么；引导读什么，agent 才照做什么。
    一侧改字另一侧静默失配（agent 退回「只解释错误」），所以这里真的读前端文件比对。
    """
    text = render_optimization_guidance()
    assert RETRY_MARK_HEADER in text
    assert RETRY_MARK_CANDIDATE in text
    if not FRONTEND_OPTIMIZATION.exists():
        pytest.skip("前端 optimization.js 不存在，跳过跨仓比对")
    frontend = FRONTEND_OPTIMIZATION.read_text(encoding="utf-8")
    assert RETRY_MARK_HEADER in frontend, "前端 buildRetryPrompt 的标记与 coze 引导不再一致"
    assert RETRY_MARK_CANDIDATE in frontend, "前端 buildRetryPrompt 的标记与 coze 引导不再一致"
    assert 'kind:"replace"' in frontend, "前端返修提问未要求 replace 块"


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
