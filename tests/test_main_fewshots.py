"""主 Agent few-shot 样本的形状守卫。

样本是 agent 实际模仿的锚点：样本里全是「当前第几步」的形态，模型就会把任何问题都
答成当前步。计划 2026-09-14 的根因 2 指出 MAIN_FEW_SHOTS 共 7 条、概念类 **0** 条，
本文件钉住「必须有概念类样本，且它不带步骤锚点」。
"""

from graphs.javatutor.prompting.main_fewshots import get_main_few_shots

# 步骤锚点字样：概念类样本出现任何一个，都会把模型往「当前步」拉。
_STEP_ANCHORS = ("当前执行位置", "当前步骤", "当前行", "第 2 步", "第2步", "step_facts")


def _concept_shots() -> list[str]:
    return [s for s in get_main_few_shots() if "原理是什么" in s]


def test_has_a_concept_shot():
    assert _concept_shots(), "MAIN_FEW_SHOTS 缺少概念类示例（概念题会被拉向当前步）"


def test_concept_shot_has_no_step_anchor():
    for shot in _concept_shots():
        for anchor in _STEP_ANCHORS:
            assert anchor not in shot, f"概念类样本不得出现步骤锚点「{anchor}」"


def test_every_shot_keeps_the_marker():
    """样本必须逐条带「仅示意」标记，避免模型照抄示例数值。"""
    for shot in get_main_few_shots():
        assert "示例" in shot
