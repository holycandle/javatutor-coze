"""测试模式上下文修复：payload → state → packet → 评审核对 → 引导 → 本体。

覆盖 2026-09-12 联调反馈「测试模式下 agent 误诊」的两半修复：
**事实**（本次运行是哪种模式，前端报、后端透传）与**语义**（两种模式各要求什么，只在本仓知识里）。
`run_mode` / `test_case_count` 缺失时必须退化成改动前的行为（不注入、不报错）。
"""

from graphs.javatutor.context_builder import gather, structure
from graphs.javatutor.harness.propose import _main_system_prompt
from graphs.javatutor.nodes import _parse_json_dict
from graphs.javatutor.prompting.contexts import build_facts_block
from graphs.javatutor.prompting.ontology import load_ontology
from graphs.javatutor.prompting.panels import render_run_mode_guide

RUN_MODE_HEADER = "### 运行模式"
GUIDE_FIRST_LINE = "## 运行模式判读（判错会直接误诊）"


def _packets_text(state: dict) -> str:
    """把 gather 的 packets 拼成可断言文本（含各 packet 标题行）。"""
    return "\n\n".join(p.content for p in gather(state, history=[], memories=[]))


# ── 1. payload → state ────────────────────────────────────────────────────────


def test_parse_json_dict_maps_run_mode_and_count():
    state = _parse_json_dict({"user_question": "为什么报错？", "run_mode": "test", "test_case_count": 2})
    assert state["run_mode"] == "test"
    assert state["test_case_count"] == 2


def test_parse_json_dict_defaults_when_run_mode_missing():
    """旧客户端不带两个键 ⇒ 模式为空串（模式未知），计数为 0；不得当成 default。"""
    state = _parse_json_dict({"user_question": "为什么报错？"})
    assert state["run_mode"] == ""
    assert state["test_case_count"] == 0


def test_parse_json_dict_tolerates_bad_count():
    state = _parse_json_dict({"run_mode": "default", "test_case_count": "x"})
    assert state["test_case_count"] == 0


# ── 2. context_builder packet ─────────────────────────────────────────────────


def test_gather_injects_run_mode_packet():
    text = _packets_text({"user_question": "为什么报错？", "run_mode": "test", "test_case_count": 2})
    assert RUN_MODE_HEADER in text
    assert "测试模式（已保存用例 2 条）" in text


def test_gather_omits_run_mode_packet_when_missing():
    """向后兼容：没有 run_mode 时不注入任何运行模式上下文。"""
    assert RUN_MODE_HEADER not in _packets_text({"user_question": "为什么报错？"})


def test_gather_default_mode_wording():
    text = _packets_text({"user_question": "为什么报错？", "run_mode": "default", "test_case_count": 0})
    assert "测试模式未激活" in text
    assert "已保存用例 0 条" in text


def test_run_mode_packet_survives_structure():
    """packet 需进入 Evidence 段（0.9 分）才真的会随 context_built 出去。"""
    text = structure(gather({"user_question": "为什么报错？", "run_mode": "default"}, history=[], memories=[]))
    assert "[Evidence]" in text
    assert RUN_MODE_HEADER in text


# ── 3. 评审核对用的 facts 块 ───────────────────────────────────────────────────


def test_build_facts_block_adds_run_mode_line():
    block = build_facts_block({"user_question": "为什么报错？", "run_mode": "test", "test_case_count": 1})
    assert "运行模式：测试模式（用例 1 条）" in block


def test_build_facts_block_omits_run_mode_line_when_missing():
    assert "运行模式：" not in build_facts_block({"user_question": "为什么报错？"})


# ── 4. 引导段 ─────────────────────────────────────────────────────────────────


def test_render_run_mode_guide_covers_both_modes_and_rules():
    guide = render_run_mode_guide()
    assert GUIDE_FIRST_LINE in guide
    # 引导段与 packet 的名字互为引用：一侧改名而漏另一侧，模型就找不到事实来源
    assert RUN_MODE_HEADER in guide
    # 三种判读情形：默认模式 / 测试模式 / 模式未知
    assert "默认模式" in guide and "测试模式" in guide and "不要臆测模式" in guide
    # 诊断红线：不得把「没进测试模式」误诊为代码错
    # （引导原文为 `**不得**据此断言…`，粗体标记插在中间，故分两段断言）
    assert "不得" in guide
    assert "据此断言代码有语法/逻辑错误" in guide
    assert "补一个 main" in guide


def test_main_system_prompt_includes_run_mode_guide():
    """接线守卫：引导段写好了但没接进系统提示 = 白写。"""
    assert GUIDE_FIRST_LINE in _main_system_prompt()


# ── 5. 本体（知识侧：只经 render_usage_guide() 进主 Agent 系统提示） ─────────────


def test_ontology_test_mode_guide_records_activation_and_extraction():
    guides = {g["topic"]: g for g in load_ontology()["user_guides"]}
    entry = guides["测试模式"]
    steps = "\n".join(entry["steps"])
    # steps = 操作口径：激活条件 + 抽取规则
    assert "必须≥1 条用例" in steps
    assert "块注释" in steps and "抽取" in steps
    # note = 判断口径：两模式的要求对比 + 「既定行为不是编译错误」
    note = entry["note"]
    assert "默认模式需要入口类/main" in note
    assert "既定行为" in note and "不是编译错误" in note
    # 抽取机制只在 steps 说一遍（review P3-5：render_usage_guide 会把 steps 与 note 都拼进提示词）
    assert "public class" not in note
