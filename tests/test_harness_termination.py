"""终止性证明：图内真环一定停，且停在默认 ``recursion_limit``（25）以内。

spec §4.3 的算术（每格是一步，``g`` = guard 进入次数、``r`` = answer_gate 重试次数，
``g + r <= MAX_ROUNDS``）：
    6 个前置节点 + main_agent(1+g+r) + guard g + run_tools g + answer_gate(r+1) + 5 个后置节点
    = 13 + 3g + 2r ≤ **22** < 25

``tool_rounds`` 的口径是「**共享**轮次预算的消耗」——`guard` 与 `answer_gate` 在各自
「非放行即回灌」的分支上都记一笔；直接作答时为 0。
收束轮（``tool_rounds >= MAX_ROUNDS``）永不产出 Action——终止由结构保证，不靠提示词祈愿。
"""

import json

from langchain_core.messages import AIMessage, HumanMessage

from graphs.javatutor.graph import build_flow_graph
from graphs.javatutor.harness.guard import MAX_ROUNDS
from graphs.javatutor.harness.propose import CONVERGENCE_PREFIX
from graphs.javatutor.prompting.optimization import STEP2_MARKER
from graphs.javatutor.prompts import (
    SYSTEM_PROMPT_ANALYZE,
    SYSTEM_PROMPT_CRITIC,
    SYSTEM_PROMPT_MAIN_AGENT,
    SYSTEM_PROMPT_REVISE,
)

STEP_FACTS_JSON = '{"tool": "step_facts", "args": {"step_index": 1}}'
UNKNOWN_TOOL_JSON = '{"tool": "no_such_tool", "args": {}}'
# 第二步提问下最坏的那一种终答：方案卡（门闩会拒绝并回灌）
OPTIONS_ANSWER = (
    "请选择你要优化的方向。\n【编辑建议】\n"
    '{"kind":"options","target":"A.java","options":[{"goal":"performance","label":"以性能为先"}]}'
)


class SpamModel:
    """病态模型：不管问几轮都只会吐同一个工具提案。"""

    def __init__(self, main_script, analyses=True):
        self.main_script = main_script
        self.main_calls = 0
        self.analyses = analyses

    def invoke(self, messages):
        system = messages[0].content or ""
        if system.startswith(SYSTEM_PROMPT_ANALYZE):
            return AIMessage(content='{"complexity": {"time": "O(1)"}}')
        if system.startswith(SYSTEM_PROMPT_MAIN_AGENT):
            self.main_calls += 1
            return AIMessage(content=self.main_script)
        if system.startswith(SYSTEM_PROMPT_CRITIC):
            return AIMessage(content='{"pass": true, "issues": []}')
        if system.startswith(SYSTEM_PROMPT_REVISE):
            return AIMessage(content="修订后的回答")
        raise AssertionError(f"未路由的 system prompt: {system[:40]}")


def _payload() -> dict:
    return {
        "source_code": "public class A { void f() { int x = 1; } }",
        "steps": [
            {"step": 0, "line": 3, "variables": {"x": 1}},
            {"step": 1, "line": 4, "variables": {"x": 2}},
        ],
        "current_step_index": 1,
        "current_line": 4,
        "user_question": "x 怎么变了？",
        "compile_error": "",
    }


def _run(payload_over=None):
    """不加 recursion_limit、不设 recursion_limit 上限——用 LangGraph 默认值当守卫。"""
    model = SpamModel(STEP_FACTS_JSON)
    payload = _payload()
    payload.update(payload_over or {})
    compiled = build_flow_graph().compile()
    out = compiled.invoke(
        {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]},
        config={"configurable": {"chat_model": model}},
    )
    return out, model


def test_budget_arithmetic_fits_default_recursion_limit():
    """把 spec §4.3 的算术钉在测试里：改 MAX_ROUNDS 先看它还成不成立。

    `answer_gate` 与 `guard` **共享**同一个轮次预算（``g + r <= MAX_ROUNDS``），
    所以**不能**再把各节点最大值直接相加——`6+4+3+3+4+5 = 25` 是个**不可达的假上界**
    （取满 `guard=3` 就取不到 `answer_gate=4`），照着它改会得到「余量 0」的假警报。
    """
    assert MAX_ROUNDS == 3
    pre_nodes, post_nodes = 6, 5

    def hops(guard_visits: int, gate_retries: int) -> int:
        return (
            pre_nodes
            + (1 + guard_visits + gate_retries)  # main_agent：首次 + 每次回环
            + guard_visits
            + guard_visits  # run_tools 至多与 guard 同数
            + (gate_retries + 1)  # answer_gate：每次终答都过一次
            + post_nodes
        )

    worst = max(hops(g, MAX_ROUNDS - g) for g in range(MAX_ROUNDS + 1))
    assert worst == 22  # 最大在 g=3, r=0
    assert worst < 25  # LangGraph 默认 recursion_limit


def test_pathological_model_terminates_within_budget():
    """10 次工具提案：既不 GraphRecursionError，也不泄漏工具 JSON 当回答。"""
    out, model = _run()

    assert out["tool_rounds"] == MAX_ROUNDS
    # 门闩轮次上界 ⇒ main_agent 至多 4 次、run_tools 至多 3 次
    assert model.main_calls == MAX_ROUNDS + 1
    executed = [
        r for r in out["step_records"] if r["tool"] == "step_facts" and r["status"] == "ok"
    ]
    assert len(executed) == MAX_ROUNDS  # 预算真的给满 3 轮，没有被 P3 顺手吃掉一轮
    # 自动前置 fetch 只做一次（P0-auto-fetch 不占轮次）
    assert len([r for r in out["step_records"] if r["policy"] == "P0-auto-fetch"]) == 1

    assert out["answer"]
    # 收束轮交付既定证据，而不是把模型的工具 JSON 当终答
    assert CONVERGENCE_PREFIX in out["answer"]
    assert not out["answer"].lstrip().startswith("{")


def test_unknown_tool_spam_never_reaches_execution():
    """被 P1 拒的提案不进 tool_calls；预算耗尽后仍给出确定性终答。"""
    model = SpamModel(UNKNOWN_TOOL_JSON)
    compiled = build_flow_graph().compile()
    out = compiled.invoke(
        {"messages": [HumanMessage(content=json.dumps(_payload(), ensure_ascii=False))]},
        config={"configurable": {"chat_model": model}},
    )

    assert out["tool_rounds"] == MAX_ROUNDS
    assert model.main_calls == MAX_ROUNDS + 1
    assert not out.get("tool_calls")
    assert [r["policy"] for r in out["step_records"]] == ["P1"] * MAX_ROUNDS
    assert out["answer"]
    assert "no_such_tool" not in out["answer"]


def test_parse_error_proposal_never_leaks_tool_name_into_answer():
    """``args`` 非对象（``ParseError``）的提案同样不得把工具名带进 answer。

    ``ParseError`` 是模型真实的畸形输出（P2 参数结构校验就是为它存在），
    ``propose.py`` / ``guard.py`` 都专门处理它，属设计内的常见路径。
    ``tool_calls`` 侧早已堵住，但它曾从 ``reasoning[].content`` 侧泄露——
    trace 是拼进 answer 的，故这条同时守住两条路径。

    用**合法白名单工具**配非法 ``args``，才能真正走到 P2（未知工具会先被 P1 拦下）。
    """
    model = SpamModel('{"tool": "step_facts", "args": [1, 2]}')  # args 是数组，非对象
    compiled = build_flow_graph().compile()
    out = compiled.invoke(
        {"messages": [HumanMessage(content=json.dumps(_payload(), ensure_ascii=False))]},
        config={"configurable": {"chat_model": model}},
    )

    assert [r["policy"] for r in out["step_records"]] == ["P2"] * MAX_ROUNDS
    assert out["answer"]
    assert "step_facts" not in out["answer"]
    assert all(
        "step_facts" not in r["content"] for r in out["decision_trace"]["reasoning"]
    )


def test_direct_answer_never_enters_the_loop():
    """无需工具的问题：guard/run_tools 一次都不进（不白花轮次）。"""
    model = SpamModel("直接回答就好")  # 散文，parse_action 返回 None
    compiled = build_flow_graph().compile()
    out = compiled.invoke(
        {"messages": [HumanMessage(content=json.dumps(_payload(), ensure_ascii=False))]},
        config={"configurable": {"chat_model": model}},
    )

    assert model.main_calls == 1
    assert out.get("tool_rounds", 0) == 0
    assert not out.get("step_records")
    assert "直接回答就好" in out["answer"]


def test_step2_options_only_model_terminates_within_budget():
    """病态第二步模型：不管问几轮都只给方案卡。门闩的回灌必须**受预算约束**地停。

    这是 spec §4.9 的回灌路径 + §4.3 的联合界的端到端守卫（不设 recursion_limit，
    让默认值 25 真的当一次守卫）。
    """
    model = SpamModel(OPTIONS_ANSWER)
    compiled = build_flow_graph().compile()
    question = f"{STEP2_MARKER}只做「以性能为先」方向的优化。请给出优化后的完整代码。"
    out = compiled.invoke(
        {
            "messages": [
                HumanMessage(
                    content=json.dumps({**_payload(), "user_question": question}, ensure_ascii=False)
                )
            ]
        },
        config={"configurable": {"chat_model": model}},
    )

    assert model.main_calls == MAX_ROUNDS + 1  # 回灌 3 次后进收束轮，不再多花一跳
    assert out["tool_rounds"] == MAX_ROUNDS  # 共享预算真的被门闩吃满，而不是溢出
    assert out["decision_trace"]["optimize_step2_gate"] == "violated"
    assert out["decision_trace"]["optimize_step2_retries"] == MAX_ROUNDS
    assert out["answer"]  # 轮次用尽后仍按收束策略交付，不是空答
