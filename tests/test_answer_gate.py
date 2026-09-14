"""终答形态门闩（`answer_gate`）的判据、节点与图级行为。

来源：`docs/reviews/2026-09-14-optimization-step2-marker-nondeterminism-review.md`——
带 `【优化第二步】` 标记的提问线上仍有 1/10 回落成方案卡，因为全链路没有任何环节**检查**这件事。
本件把判据做成代码（spec §4.9）：判据是纯函数，节点只做「放行 / 回灌重提案 / 记 violated」三件事。
"""

import json

from langchain_core.messages import AIMessage, HumanMessage

from graphs.javatutor.graph import build_flow_graph
from graphs.javatutor.harness.answer_gate import (
    EDIT_MARKER,
    answer_gate_node,
    check_step2_answer,
    route_after_answer_gate,
    step2_applies,
)
from graphs.javatutor.harness.guard import MAX_ROUNDS
from graphs.javatutor.prompting.optimization import STEP2_MARKER
from graphs.javatutor.prompts import (
    SYSTEM_PROMPT_ANALYZE,
    SYSTEM_PROMPT_CRITIC,
    SYSTEM_PROMPT_MAIN_AGENT,
    SYSTEM_PROMPT_REVISE,
)

# 前端 `buildGoalPrompt` 的模板形状（逐字同形，含会命中 `DATA_QUERY_KEYWORDS` 的黑名单文案）
STEP2_QUESTION = (
    f"{STEP2_MARKER}只做「以性能为先」方向的优化，具体要求：用哈希表把嵌套循环降为 O(n)。"
    "不要顺带做其他方向的改动（例如：「以可读性为先」：拆分长方法并命名中间变量）。"
    "请给出优化后的完整代码。"
)

# 代码里带 `{`/`}`——判据必须平衡解析，否则会在第一个嵌套 `}` 处截断并误判为违规
_CODE = "class Solution {\n    void f(int[] arr) {\n        int n = arr.length;\n    }\n}"
REPLACE_ANSWER = "把内层线性查找换成哈希表，整体由 O(n²) 降为 O(n)。\n" + EDIT_MARKER + "\n" + json.dumps(
    {
        "kind": "replace",
        "target": "Solution.java",
        "goal": "performance",
        "rationale": "用哈希表替换线性查找",
        "code": _CODE,
    },
    ensure_ascii=False,
)
OPTIONS_ANSWER = "请选择你要优化的方向。\n" + EDIT_MARKER + "\n" + json.dumps(
    {
        "kind": "options",
        "target": "Solution.java",
        "options": [
            {"goal": "performance", "label": "以性能为先"},
            {"goal": "readability", "label": "以可读性为先"},
        ],
    },
    ensure_ascii=False,
)


def _block(**fields) -> str:
    return "正文。" + EDIT_MARKER + "\n" + json.dumps(fields, ensure_ascii=False)


class ScriptedModel:
    """主 Agent 按调用序号取脚本；其余节点固定应答（不参与断言）。"""

    def __init__(self, main_script):
        self.main_script = list(main_script)
        self.main_calls = 0

    def invoke(self, messages):
        system = messages[0].content or ""
        if system.startswith(SYSTEM_PROMPT_ANALYZE):
            return AIMessage(content='{"complexity": {"time": "O(n)"}}')
        if system.startswith(SYSTEM_PROMPT_MAIN_AGENT):
            self.main_calls += 1
            return AIMessage(content=self.main_script[min(self.main_calls - 1, len(self.main_script) - 1)])
        if system.startswith(SYSTEM_PROMPT_CRITIC):
            return AIMessage(content='{"pass": true, "issues": []}')
        if system.startswith(SYSTEM_PROMPT_REVISE):
            return AIMessage(content="修订后的回答")
        raise AssertionError(f"未路由的 system prompt: {system[:40]}")


def _run(main_script, user_question=STEP2_QUESTION):
    payload = {
        "source_code": _CODE,
        "steps": [{"step": 0, "line": 1, "variables": {"arr": [1, 2]}}],
        "current_step_index": 0,
        "current_line": 1,
        "user_question": user_question,
        "compile_error": "",
    }
    model = ScriptedModel(main_script)
    compiled = build_flow_graph().compile()
    out = compiled.invoke(
        {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]},
        config={"configurable": {"chat_model": model}},
    )
    return out, model


# ── 纯判据 ────────────────────────────────────────────────────────────────────


def test_applies_only_when_question_starts_with_marker():
    assert step2_applies(STEP2_QUESTION)
    assert step2_applies("  " + STEP2_QUESTION)  # 前导空白容忍
    assert not step2_applies("帮我优化一下这段代码")
    assert not step2_applies("帮我优化性能")
    # 标记在句中（用户只是在问这个标记是什么）⇒ 不是第二步
    assert not step2_applies(f"怎么理解 {STEP2_MARKER} 这个标记？")


def test_compliant_replace_passes():
    verdict = check_step2_answer(STEP2_QUESTION, REPLACE_ANSWER)
    assert verdict.verdict == "passed"
    assert verdict.reason == ""


def test_options_card_is_violated():
    verdict = check_step2_answer(STEP2_QUESTION, OPTIONS_ANSWER)
    assert verdict.verdict == "violated"
    assert "options" in verdict.reason


def test_two_edit_blocks_is_violated():
    verdict = check_step2_answer(STEP2_QUESTION, REPLACE_ANSWER + "\n" + REPLACE_ANSWER)
    assert verdict.verdict == "violated"
    assert "恰好一个" in verdict.reason


def test_missing_block_is_violated():
    verdict = check_step2_answer(STEP2_QUESTION, "这段代码可以优化性能。")
    assert verdict.verdict == "violated"


def test_missing_kind_is_violated():
    verdict = check_step2_answer(STEP2_QUESTION, _block(target="A.java", code=_CODE))
    assert verdict.verdict == "violated"
    assert "kind" in verdict.reason


def test_empty_code_is_violated():
    verdict = check_step2_answer(
        STEP2_QUESTION, _block(kind="replace", target="A.java", code="   ")
    )
    assert verdict.verdict == "violated"
    assert "code" in verdict.reason


def test_elided_code_is_violated():
    verdict = check_step2_answer(
        STEP2_QUESTION,
        _block(kind="replace", target="A.java", code="class A {\n    // ... 其余同上\n}"),
    )
    assert verdict.verdict == "violated"
    assert "省略占位" in verdict.reason


def test_varargs_is_not_an_elision():
    """`String... args` 的前一个字符是标识符 ⇒ 不是省略占位（`...` 在 Java 里唯一的合法用途）。"""
    verdict = check_step2_answer(
        STEP2_QUESTION,
        _block(
            kind="replace",
            target="A.java",
            code="class A {\n    static void main(String... args) { }\n}",
        ),
    )
    assert verdict.verdict == "passed"


def test_not_applicable_for_non_step2_question():
    verdict = check_step2_answer("帮我优化一下这段代码", OPTIONS_ANSWER)
    assert verdict.verdict == "not_applicable"


def test_edit_marker_matches_the_other_two_copies():
    """第三份副本必须与既有两处逐字一致（那两处之间已有同名的守漂移用例）。"""
    from graphs.javatutor import nodes
    from graphs.javatutor.critic import _STRUCTURED_MARKERS

    assert nodes._STRUCTURED_MARKERS == _STRUCTURED_MARKERS
    assert EDIT_MARKER in nodes._STRUCTURED_MARKERS


# ── 节点 ──────────────────────────────────────────────────────────────────────


def _state(**over) -> dict:
    base = {"user_question": STEP2_QUESTION, "answer": REPLACE_ANSWER, "tool_rounds": 0}
    base.update(over)
    return base


def test_node_passes_without_touching_the_answer():
    out = answer_gate_node(_state())
    assert out["answer_gate_decision"]["verdict"] == "passed"
    assert "answer" not in out
    assert "agent_messages" not in out


def test_node_retries_and_clears_the_rejected_answer():
    out = answer_gate_node(_state(answer=OPTIONS_ANSWER))
    assert out["answer_gate_decision"]["verdict"] == "retry"
    assert out["answer"] == ""  # 被拒终答不算数
    assert out["tool_rounds"] == 1  # 与 guard 共享同一次轮次预算
    msg = out["agent_messages"][-1]
    assert isinstance(msg, HumanMessage)
    assert "replace" in msg.content
    # Bug A 红线：被拒终答不得以任何形式回流 agent_messages
    assert not any(isinstance(m, AIMessage) for m in out["agent_messages"])
    assert "请选择你要优化的方向" not in msg.content


def test_node_retry_counter_accumulates():
    out = answer_gate_node(
        _state(
            answer=OPTIONS_ANSWER,
            answer_gate_decision={"verdict": "retry", "reason": "x", "retries": 2},
        )
    )
    assert out["answer_gate_decision"]["retries"] == 3


def test_node_does_not_retry_once_budget_is_exhausted():
    """收束轮之后重试无意义（该轮永不产出 Action），按收束策略交付并如实记 violated。"""
    out = answer_gate_node(_state(answer=OPTIONS_ANSWER, tool_rounds=MAX_ROUNDS))
    assert out["answer_gate_decision"]["verdict"] == "violated"
    assert "answer" not in out
    assert "agent_messages" not in out
    assert "tool_rounds" not in out


def test_node_not_applicable_for_ordinary_question():
    out = answer_gate_node(_state(user_question="帮我优化一下这段代码"))
    assert out["answer_gate_decision"]["verdict"] == "not_applicable"
    assert "answer" not in out


def test_route_after_answer_gate():
    assert route_after_answer_gate({"answer_gate_decision": {"verdict": "retry"}}) == "propose"
    for verdict in ("passed", "violated", "not_applicable"):
        assert route_after_answer_gate({"answer_gate_decision": {"verdict": verdict}}) == "critic"
    assert route_after_answer_gate({}) == "critic"


# ── 图级 ──────────────────────────────────────────────────────────────────────


def test_rejected_options_card_is_retried_until_replace():
    """门闩的失败回灌用例：第一次给方案卡 → 打回重提案 → 第二次交付 replace。"""
    out, model = _run([OPTIONS_ANSWER, REPLACE_ANSWER])

    assert model.main_calls == 2  # 真的重提案了一次，而不是直接交付方案卡
    assert out["tool_rounds"] == 1  # 重试确实吃了一次共享预算
    assert out["decision_trace"]["optimize_step2_gate"] == "passed"
    assert out["decision_trace"]["optimize_step2_retries"] == 1
    # 用户可见产物里不得留下被拒的那一版（「还是让我选方向」的症状）
    assert "请选择你要优化的方向" not in out["answer"]


def test_compliant_first_answer_needs_no_retry():
    out, model = _run([REPLACE_ANSWER])
    assert model.main_calls == 1
    assert out.get("tool_rounds", 0) == 0
    assert out["decision_trace"]["optimize_step2_gate"] == "passed"
    assert out["decision_trace"]["optimize_step2_retries"] == 0


def test_ordinary_question_is_not_gated():
    """非标记提问不得被动到：既不放行失败，也不多花一跳。"""
    out, model = _run(["直接回答就好"], user_question="x 怎么变了？")
    assert model.main_calls == 1
    assert out["decision_trace"]["optimize_step2_gate"] == "not_applicable"
    assert out["decision_trace"]["optimize_step2_retries"] == 0


def test_trace_keys_reach_the_user_visible_answer():
    """红线纪律：断言的是 `build_final` 拼出来的 answer 文本，不止是 trace 字典。"""
    out, _ = _run([OPTIONS_ANSWER, REPLACE_ANSWER])
    assert '"optimize_step2_gate":"passed"' in out["answer"]
    assert '"optimize_step2_retries":1' in out["answer"]
