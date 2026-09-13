"""图内真环的行为测试：提案(propose) → 门闩(guard) → 执行(run_tools) → 回提案。

本文件是 ``tests/test_main_agent.py`` 的迁移归处：原先那些用例直接调
``main_agent_node``（自己 while 循环），循环契约化进图之后该入口不再是循环，
所以驱动方式换成**图级**（``build_flow_graph().compile()`` + 路由模型），
锁住的行为一条不减。``test_main_agent.py`` 只留纯渲染器用例。

模型注入只用既有且唯一的注入点 ``configurable.chat_model``，业务代码里不留后门。
"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import graphs.javatutor.harness.guard_node as guard_node_module
from graphs.javatutor.graph import build_flow_graph
from graphs.javatutor.harness.guard import MAX_ROUNDS
from graphs.javatutor.harness.guard_node import guard_node
from graphs.javatutor.harness.propose import (
    CONVERGENCE_INSTRUCTION,
    CONVERGENCE_PREFIX,
    LLM_UNAVAILABLE_ANSWER,
    propose,
)
from graphs.javatutor.harness.tools_node import run_tools_node
from graphs.javatutor.prompts import (
    SYSTEM_PROMPT_ANALYZE,
    SYSTEM_PROMPT_CRITIC,
    SYSTEM_PROMPT_MAIN_AGENT,
    SYSTEM_PROMPT_REVISE,
)

_ANALYSIS_JSON = json.dumps(
    {"complexity": {"time": "O(1)"}, "algorithms": [], "dataStructures": []},
    ensure_ascii=False,
)

STEPS = [
    {"step": 0, "line": 3, "variables": {"x": 1}},
    {"step": 1, "line": 4, "variables": {"x": 2}},
]


class RouterModel:
    """按 system prompt 路由的图级测试模型。

    analyze / main_agent / critic / revise 在图上串行执行且 model 是同一个，
    所以必须比 system prompt 而不是比调用序号。
    """

    def __init__(self, main_scripts, critic_pass=True):
        self.scripts = list(main_scripts)
        self.critic_pass = critic_pass
        self.main_seen: list[list] = []

    def invoke(self, messages):
        system = messages[0].content or ""
        if system.startswith(SYSTEM_PROMPT_ANALYZE):
            return AIMessage(content=_ANALYSIS_JSON)
        if system.startswith(SYSTEM_PROMPT_MAIN_AGENT):
            self.main_seen.append(list(messages))
            nxt = self.scripts.pop(0) if self.scripts else "没有更多脚本了"
            return AIMessage(content=nxt)
        if system.startswith(SYSTEM_PROMPT_CRITIC):
            return AIMessage(
                content=json.dumps({"pass": self.critic_pass, "issues": []}, ensure_ascii=False)
            )
        if system.startswith(SYSTEM_PROMPT_REVISE):
            return AIMessage(content="修订后的回答")
        raise AssertionError(f"未路由的 system prompt: {system[:40]}")


class RecordingModel:
    """记录每次收到的 messages（断言模型上下文内容用）。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.seen: list[list] = []

    def invoke(self, messages):
        self.seen.append(list(messages))
        return AIMessage(content=self.responses.pop(0))


def _payload(**over) -> dict:
    base = {
        "source_code": "public class A { void f() { int x = 1; } }",
        "steps": STEPS,
        "current_step_index": 1,
        "current_line": 4,
        "user_question": "x 怎么变了？",
        "compile_error": "",
    }
    base.update(over)
    return base


def _run(scripts, **over):
    """跑完整图（含 critic/revise/verify/final），返回 (终态, 模型)。

    **不设 recursion_limit**：让默认值（25）在每次运行里真的当一次守卫。
    """
    model = RouterModel(scripts)
    compiled = build_flow_graph().compile()
    payload = _payload(**over)
    out = compiled.invoke(
        {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]},
        config={"configurable": {"chat_model": model}},
    )
    return out, model


# ── propose（reasoning 侧） ────────────────────────────────────────────────────


STATE = {"context_built": "[Evidence]\n步骤数据", "steps": STEPS, "current_step_index": 1}


def test_propose_seeds_system_prompt_and_context_on_first_call():
    model = RecordingModel(["直接回答"])
    out = propose(STATE, model=model)

    sent = model.seen[0]
    assert isinstance(sent[0], SystemMessage)
    assert "教学主 Agent" in sent[0].content
    assert STATE["context_built"] in sent[1].content
    assert f"[当前轮次] 1/{MAX_ROUNDS}" in sent[1].content
    assert out["answer"] == "直接回答"
    assert out["proposed_action"] == {}


def test_terminal_answer_does_not_enter_agent_messages():
    """终答轮不把模型原文写进 ``agent_messages``（2026-09-14 联调 Bug A 的修复点）。

    该轮之后图一定不再回到 propose（``_route_after_propose`` 把无 action 的轮次导向
    critic），这条 ``AIMessage`` 对后续推理无用；而 ``stream_mode="messages"`` 会把它
    转成 ``answer`` delta，与 ``build_final`` 的终答构成**重复正文**。
    """
    state = dict(
        STATE,
        agent_messages=[SystemMessage(content="sys"), HumanMessage(content="ctx")],
    )
    out = propose(state, model=RecordingModel(["直接回答"]))
    assert out["answer"] == "直接回答"
    assert len(out["agent_messages"]) == 2, "终答轮不得追加 AIMessage"
    assert [type(m).__name__ for m in out["agent_messages"]] == ["SystemMessage", "HumanMessage"]


def test_convergence_round_does_not_enter_agent_messages():
    state = dict(
        STATE,
        tool_rounds=MAX_ROUNDS,
        agent_messages=[SystemMessage(content="sys"), HumanMessage(content="ctx")],
    )
    out = propose(state, model=RecordingModel(["随便说点什么"]))
    assert out["answer"]
    assert len(out["agent_messages"]) == 2


def test_proposal_round_still_enters_agent_messages():
    """提案轮**必须**追加：模型要看到自己上一轮的提案原文，才有因果链（真 ReAct）。"""
    state = dict(
        STATE,
        agent_messages=[SystemMessage(content="sys"), HumanMessage(content="ctx")],
    )
    out = propose(state, model=RecordingModel(['{"tool": "step_facts", "args": {"step_index": 1}}']))
    assert len(out["agent_messages"]) == 3
    assert out["agent_messages"][-1].content == '{"tool": "step_facts", "args": {"step_index": 1}}'


def test_propose_sees_its_own_previous_proposal():
    """真 ReAct 的核心：第二轮看到的是**累积**轨迹，而不是重建的 system+context。"""
    state = dict(
        STATE,
        agent_messages=[
            SystemMessage(content="sys"),
            HumanMessage(content="ctx"),
            AIMessage(content='{"tool": "step_facts", "args": {"step_index": 1}}'),
        ],
    )
    model = RecordingModel(["根据第 2 步回答"])
    propose(state, model=model)

    sent = model.seen[0]
    assert [type(m).__name__ for m in sent] == ["SystemMessage", "HumanMessage", "AIMessage"]
    assert sent[2].content == '{"tool": "step_facts", "args": {"step_index": 1}}'
    # 非收束轮不加收束指令
    assert sent[-1] is sent[2]


def test_propose_returns_action_dict_and_no_answer():
    model = RecordingModel(['{"tool": "step_facts", "args": {"step_index": 1}}'])
    out = propose(STATE, model=model)
    assert "answer" not in out
    assert out["proposed_action"] == {
        "tool": "step_facts",
        "args": {"step_index": 1},
        "raw": '{"tool": "step_facts", "args": {"step_index": 1}}',
    }


def test_propose_keeps_parse_error_explicit():
    """args 不是对象：不能静默兜成 {}（那是把非法提案当合法提案执行）。"""
    model = RecordingModel(['{"tool": "step_facts", "args": "oops"}'])
    out = propose(STATE, model=model)
    assert out["proposed_action"]["tool"] == "step_facts"
    assert out["proposed_action"]["parse_error"]


def test_propose_convergence_round_never_proposes_action():
    """终止性的结构保证：轮次用尽后即便模型硬输出工具 JSON，也只当终答。"""
    model = RecordingModel(['{"tool": "step_facts", "args": {"step_index": 1}}'])
    out = propose(dict(STATE, tool_rounds=MAX_ROUNDS), model=model)

    assert CONVERGENCE_INSTRUCTION in model.seen[0][-1].content
    assert out["answer"]
    assert "tool" not in out["answer"]
    assert out["proposed_action"] == {}


def test_propose_convergence_delivers_evidence_instead_of_apology():
    state = dict(
        STATE,
        tool_rounds=MAX_ROUNDS,
        step_records=[{"status": "ok", "summary": "[step_facts 结果：第 2 步] x=2"}],
    )
    out = propose(state, model=RecordingModel(['{"tool": "step_facts", "args": {}}']))
    assert CONVERGENCE_PREFIX in out["answer"]
    assert "[step_facts 结果：第 2 步] x=2" in out["answer"]
    assert '"tool"' not in out["answer"]


def test_propose_llm_failure_degrades_to_answer():
    class Boom:
        def invoke(self, messages):
            raise RuntimeError("boom")

    out = propose(STATE, model=Boom())
    assert out["answer"] == LLM_UNAVAILABLE_ANSWER
    assert out["proposed_action"] == {}


# ── run_tools（执行侧） ───────────────────────────────────────────────────────


def test_run_tools_auto_fetches_without_round_cost():
    """查单步证据前自动前置 fetch：不占轮次（不写 tool_rounds）。"""
    out = run_tools_node(
        dict(
            STATE,
            source_code="public class A { void f() { int x = 1; } }",
            run_id="r1",
            proposed_action={"tool": "step_facts", "args": {"step_index": 1}},
            guard_decision={"policy": "P0"},
        )
    )
    assert [tc["tool"] for tc in out["tool_calls"]] == ["fetch_execution_context", "step_facts"]
    assert out["step_records"][0]["policy"] == "P0-auto-fetch"
    assert out["fetched_injected"] is True
    assert "tool_rounds" not in out


def test_run_tools_records_ok_observation_and_memory():
    out = run_tools_node(
        dict(
            STATE,
            source_code="public class A { void f() { int x = 1; } }",
            proposed_action={"tool": "step_facts", "args": {"step_index": 1}},
            guard_decision={"policy": "P0"},
        )
    )
    record = [r for r in out["step_records"] if r["tool"] == "step_facts"][0]
    assert record["status"] == "ok"
    assert record["payload"]["diff"] == [{"key": "x", "before": 1, "after": 2}]
    assert record["latency_ms"] >= 0.0
    assert out["served_step_indices"] == [1]

    assert len(out["step_memories"]) == 1
    assert out["step_memories"][0]["importance"] == 0.8
    assert "diff" in out["step_memories"][0]["content"]


def test_run_tools_error_records_observation_but_no_memory():
    out = run_tools_node(
        dict(
            STATE,
            source_code="public class A {}",
            proposed_action={"tool": "step_facts", "args": {"step_index": 99}},
            guard_decision={"policy": "P0"},
        )
    )
    record = [r for r in out["step_records"] if r["tool"] == "step_facts"][0]
    assert record["status"] == "error"
    assert out["step_memories"] == []
    assert out["served_step_indices"] == []


def test_run_tools_appends_p5_nudge_on_repeat():
    out = run_tools_node(
        dict(
            STATE,
            source_code="public class A {}",
            proposed_action={"tool": "step_facts", "args": {"step_index": 1}},
            guard_decision={"policy": "P5"},
        )
    )
    last = out["agent_messages"][-1].content
    assert "不要重复查询同一步骤" in last
    assert f"[当前轮次] 1/{MAX_ROUNDS}" in last


def test_run_tools_merges_observations_into_one_message():
    """一次执行的多个观察合并成一条 HumanMessage：轨迹保持严格角色交替。"""
    out = run_tools_node(
        dict(
            STATE,
            source_code="public class A { void f() { int x = 1; } }",
            proposed_action={"tool": "step_facts", "args": {"step_index": 1}},
            guard_decision={"policy": "P0"},
        )
    )
    assert len(out["step_records"]) == 2  # auto-fetch + step_facts
    assert len(out["agent_messages"]) == 1
    content = out["agent_messages"][0].content
    assert "[fetch_execution_context 结果]" in content
    assert "[step_facts 结果：第 2 步（step_index=1）]" in content


def test_graph_agent_messages_alternate_roles():
    """真 ReAct 轨迹：System → Human → AI → Human…，无连续同角色消息。

    终答轮不再追加（2026-09-14 Bug A）：末条是 run_tools 的观察，而非终答。
    """
    out, _ = _run(
        ['{"tool": "step_facts", "args": {"step_index": 1}}', "根据第 2 步，x 变成了 2"]
    )
    kinds = [type(m).__name__ for m in out["agent_messages"]]
    assert kinds == ["SystemMessage", "HumanMessage", "AIMessage", "HumanMessage"]


def test_run_tools_unknown_dispatch_is_error_not_silent_noop():
    out = run_tools_node({"proposed_action": {"tool": "ghost", "args": {}}, "guard_decision": {}})
    assert out["step_records"][0]["status"] == "error"
    assert out["step_records"][0]["policy"] == "P0-unknown-dispatch"
    assert out["tool_calls"] == []


# ── guard（治理侧） ──────────────────────────────────────────────────────────

MULTI_FILE_PROPOSAL = {
    "tool": "fetch_execution_context",
    "args": {"file": "Mian.java"},
}
MULTI_FILE_STATE = {"files": {"Main.java": "class Main {}", "Helper.java": "class Helper {}"}}


def test_guard_increments_rounds_and_allows_without_observation():
    out = guard_node({"proposed_action": {"tool": "step_facts", "args": {"step_index": 1}}})
    assert out["tool_rounds"] == 1
    assert out["guard_decision"]["verdict"] == "allow"
    assert out["guard_decision"]["policy"] == "P0"
    # 放行不写观察、不动 agent_messages、不新增 tool_calls
    assert "step_records" not in out
    assert "agent_messages" not in out
    assert "tool_calls" not in out


def test_guard_deny_appends_observation_and_never_records_a_tool_call():
    out = guard_node({"proposed_action": {"tool": "no_such_tool", "args": {}}})
    assert out["guard_decision"]["verdict"] == "deny"
    assert out["guard_decision"]["policy"] == "P1"
    assert out["step_records"][0]["status"] == "denied"
    assert out["proposed_action"] == {}
    assert "tool_calls" not in out
    # 拒绝原因必须能回到模型眼前，否则下一轮只会重复同一个错
    assert "no_such_tool" in out["agent_messages"][-1].content
    assert f"[当前轮次] 2/{MAX_ROUNDS}" in out["agent_messages"][-1].content


def test_guard_invalid_args_marked_as_invalid_args():
    out = guard_node({"proposed_action": {"tool": "step_facts", "args": {"bogus": 1}}})
    assert out["step_records"][0]["status"] == "invalid_args"
    assert out["step_records"][0]["policy"] == "P2"


def test_guard_p3_still_counts_the_round():
    out = guard_node(
        {
            "tool_rounds": MAX_ROUNDS,
            "proposed_action": {"tool": "step_facts", "args": {"step_index": 1}},
        }
    )
    assert out["guard_decision"]["policy"] == "P3"
    assert out["tool_rounds"] == MAX_ROUNDS + 1


def test_guard_grants_the_last_budgeted_round():
    """P3 只拦第 4 次进入：第 3 次（state.tool_rounds=2）必须放行，否则白丢一轮预算。"""
    out = guard_node(
        {
            "tool_rounds": MAX_ROUNDS - 1,
            "proposed_action": {"tool": "step_facts", "args": {"step_index": 1}},
        }
    )
    assert out["guard_decision"]["verdict"] == "allow"
    assert out["tool_rounds"] == MAX_ROUNDS


def test_guard_hitl_off_degrades_needs_decision_to_deny(monkeypatch):
    """线上没 resume 通道：默认关，且必须降级成 deny 而不是静默执行。"""
    monkeypatch.delenv("COZE_AGENT_HITL", raising=False)
    out = guard_node(dict(MULTI_FILE_STATE, proposed_action=MULTI_FILE_PROPOSAL))
    assert out["guard_decision"]["verdict"] == "deny"
    assert out["guard_decision"]["policy"] == "P4"
    assert out["step_records"][0]["status"] == "denied"


def test_guard_hitl_on_resolves_the_proposal_and_allows(monkeypatch):
    """恢复值补全原提案的 file 后放行：错文件名被替换，正确文件名进入执行。"""
    seen = []
    monkeypatch.setattr(guard_node_module, "hitl_enabled", lambda: True)
    monkeypatch.setattr(
        guard_node_module,
        "interrupt",
        lambda payload: seen.append(payload) or "Main.java",
    )
    out = guard_node(dict(MULTI_FILE_STATE, proposed_action=MULTI_FILE_PROPOSAL))

    assert seen[0]["options"] == ["Helper.java", "Main.java"]
    assert "Mian.java" in seen[0]["question"]
    assert out["guard_decision"]["verdict"] == "allow"
    assert out["guard_decision"]["policy"] == "P4-resolved"
    assert out["step_records"][0]["payload"]["user_choice"] == "Main.java"
    # 原提案（错文件名）被补全后放行到执行节点，而不是让模型重提
    assert out["proposed_action"] == {
        "tool": "fetch_execution_context",
        "args": {"file": "Main.java"},
    }
    # 只有结构化记录，没有追加 agent_messages——证据由 run_tools 的观察给出，
    # 这里再追加一条会与紧随其后的执行观察连成两条同角色消息
    assert "agent_messages" not in out


# ── 图级行为（迁移自 tests/test_main_agent.py） ──────────────────────────────


def test_graph_step_facts_then_answer():
    out, model = _run(
        ['{"tool": "step_facts", "args": {"step_index": 1}}', "根据第 2 步，x 变成了 2"]
    )
    assert out["tool_rounds"] == 1
    assert [tc["tool"] for tc in out["tool_calls"]] == ["fetch_execution_context", "step_facts"]
    assert out["tool_calls"][1]["args"] == {"step_index": 1}
    assert "result" in out["tool_calls"][1]  # 返回值截断入痕，供诊断
    assert "x 变成了 2" in out["answer"]
    assert "【决策痕迹】" in out["answer"]
    assert len(model.main_seen) == 2


def test_graph_direct_answer_costs_no_round():
    """直接作答不经过门闩 → tool_rounds 为 0（spec §4.3：只有门闩记账）。"""
    out, model = _run(["直接回答"])
    assert out.get("tool_rounds", 0) == 0
    assert "直接回答" in out["answer"]
    assert "【决策痕迹】" in out["answer"]
    assert len(model.main_seen) == 1


def test_graph_stops_after_three_guard_rounds():
    out, model = _run(['{"tool": "step_facts", "args": {}}'] * 5)
    assert out["tool_rounds"] == MAX_ROUNDS
    # 门闩轮次上界 ⇒ main_agent 至多 MAX_ROUNDS + 1 次访问
    assert len(model.main_seen) == MAX_ROUNDS + 1
    # 预算给满：3 次 step_facts 真的执行了（P3 是正常路径不可达的兜底）
    executed = [
        r for r in out["step_records"] if r["tool"] == "step_facts" and r["status"] == "ok"
    ]
    assert len(executed) == MAX_ROUNDS
    assert out["answer"]


def test_graph_records_step_memories():
    out, _ = _run(
        ['{"tool": "step_facts", "args": {"step_index": 1}}', "根据第 2 步，x 变成了 2"]
    )
    assert len(out["step_memories"]) == 1
    assert out["step_memories"][0]["importance"] == 0.8
    assert "diff" in out["step_memories"][0]["content"]


def test_graph_tool_error_does_not_record_memory():
    out, _ = _run(
        ['{"tool": "step_facts", "args": {"step_index": 99}}', "无法查询，但上下文有分析结果"]
    )
    assert not out.get("step_memories")
    assert out["answer"]


def test_graph_repeat_same_step_gets_answer_nudge():
    """同一步骤被再次查询 → 注入「请直接作答」提示，打断重复试探。"""
    out, model = _run(
        [
            '{"tool": "step_facts", "args": {"step_index": 1}}',
            '{"tool": "step_facts", "args": {"step_index": 1}}',
            "根据第 2 步，x 变成了 2",
        ]
    )
    assert out["tool_rounds"] == 2
    nudged = model.main_seen[-1][-1].content
    assert "不要重复查询同一步骤" in nudged
    # 证据带 1-based 标签，与用户口吻的「第 2 步」对齐
    assert "第 2 步（step_index=1）" in nudged
    assert "x 变成了 2" in out["answer"]


def test_graph_invalid_args_denied_before_execution():
    """未知参数在门闩层被拦下（spec §4.5 P2）：不执行、不崩、模型仍能作答。"""
    out, _ = _run(['{"tool": "step_facts", "args": {"bogus_key": 1}}', "根据第 1 步回答"])
    assert not out.get("tool_calls")
    assert out["tool_rounds"] == 1
    record = [r for r in out["step_records"] if r["tool"] == "step_facts"][0]
    assert record["status"] == "invalid_args"
    assert record["policy"] == "P2"
    assert "根据第 1 步回答" in out["answer"]


def test_graph_unknown_tool_is_never_leaked_as_answer():
    """未知工具被拒后继续循环，而不是把工具 JSON 当最终回答。"""
    out, _ = _run(
        ['{"tool": "no_such_tool", "args": {}}', '{"tool": "no_such_tool", "args": {}}', "最终直接回答"]
    )
    assert out["tool_rounds"] == 2
    assert not out.get("tool_calls")
    assert "最终直接回答" in out["answer"]
    assert "no_such_tool" not in out["answer"]


def test_graph_dispatches_explicit_fetch():
    out, _ = _run(
        ['{"tool": "fetch_execution_context", "args": {"run_id": "r1"}}', "已读取代码"],
        run_id="r1",
    )
    assert any(tc["tool"] == "fetch_execution_context" for tc in out["tool_calls"])
    assert out["fetched_context"]["run_id"] == "r1"


def test_graph_auto_fetches_before_step_facts():
    out, _ = _run(
        ['{"tool": "step_facts", "args": {"step_index": 1}}', "根据第 2 步，x 变成了 2"],
        run_id="r1",
    )
    tools = [tc["tool"] for tc in out["tool_calls"]]
    assert tools[0] == "fetch_execution_context"
    assert tools[1] == "step_facts"
    assert out["fetched_context"]["run_id"] == "r1"


def test_graph_fetch_failure_is_observation_not_crash():
    """fetch 失败：结构化观察回灌 + 循环继续，最终仍有回答（不会崩、不会空答）。"""
    out, _ = _run(
        ['{"tool": "fetch_execution_context", "args": {}}'] * 4,
        source_code="",
        steps=[],
    )
    assert out["answer"]
    assert out["tool_rounds"] == MAX_ROUNDS
    assert out["fetch_context_failed"] is True
    assert out["fetch_context_error"]
    errors = [
        r
        for r in out["step_records"]
        if r["tool"] == "fetch_execution_context" and r["status"] == "error"
    ]
    assert errors
    # 收束轮无成功证据 → 明确的「暂时无法回答」，而不是泄漏工具 JSON
    assert "抱歉" in out["answer"]


def test_graph_critic_failure_routes_through_revise():
    """回归：真环接上 critic/revise/verify 之后，修订链仍原样工作。"""
    model = RouterModel(
        [
            '{"tool": "step_facts", "args": {"step_index": 1}}',
            "原始回答有误",
        ],
        critic_pass=False,
    )
    compiled = build_flow_graph().compile()
    out = compiled.invoke(
        {"messages": [HumanMessage(content=json.dumps(_payload(), ensure_ascii=False))]},
        config={"configurable": {"chat_model": model}},
    )
    assert out["decision_trace"]["critic_passed"] is False
    assert out["decision_trace"]["revised"] is True
    assert "修订后的回答" in out["answer"]
    assert "verification" in out["decision_trace"]


@pytest.mark.parametrize("tool_rounds", [0, 1, 2])
def test_graph_round_marker_tracks_next_propose(tool_rounds):
    """轮次锚点标的是「下一次 propose 是第几轮」，与 MAX_ROUNDS 同源。"""
    from graphs.javatutor.harness.guard import round_marker

    assert round_marker(tool_rounds) == f"[当前轮次] {tool_rounds + 1}/{MAX_ROUNDS}"


# ── 过程哨兵（Plan A Task 3）：run_tools 的 tool 事件 ─────────────────────────────


def _sentinel_events(messages):
    """从一批哨兵消息里取出事件（顺带断言每条都带过程标记）。"""
    from graphs.javatutor.process_events import PROCESS_KWARG, parse_process_events

    events = []
    for m in messages:
        assert m.additional_kwargs.get(PROCESS_KWARG) is True, "哨兵必须带 PROCESS_KWARG 标记"
        events.extend(parse_process_events(m.content)["events"])
    return events


def test_run_tools_emits_tool_event_per_observation():
    """自动前置 fetch + step_facts ⇒ 两条 tool 事件，外加一条收尾 stage。"""
    out = run_tools_node(
        dict(
            STATE,
            source_code="public class A { void f() { int x = 1; } }",
            run_id="r1",
            proposed_action={"tool": "step_facts", "args": {"step_index": 1}},
            guard_decision={"policy": "P0"},
        )
    )
    events = _sentinel_events(out["messages"])

    tools = [e for e in events if e["kind"] == "tool"]
    assert [e["tool"] for e in tools] == ["fetch_execution_context", "step_facts"]
    assert events[-1] == {"kind": "stage", "text": "证据已就绪，正在生成回答…"}
    assert len(out["process_event_ids"]) == len(out["messages"]) == len(events)


def test_run_tools_tool_events_mirror_step_records():
    """事件与 step_records 同源（都派生自 observations），不掺入「提案」的信息。

    提案是「打算做」，观察是「已经做了」：门闩改写或自动前置 fetch 时两者会分叉，
    故逐字对齐 step_records 才说明事件反映的是**实际执行**。
    """
    out = run_tools_node(
        dict(
            STATE,
            source_code="public class A { void f() { int x = 1; } }",
            run_id="r1",
            proposed_action={"tool": "step_facts", "args": {"step_index": 1}},
            guard_decision={"policy": "P0"},
        )
    )
    tools = [e for e in _sentinel_events(out["messages"]) if e["kind"] == "tool"]
    assert [(e["tool"], e["args"], e["status"]) for e in tools] == [
        (r["tool"], r["args"], r["status"]) for r in out["step_records"]
    ]


def test_run_tools_still_emits_stage_when_no_observation_succeeded():
    """执行失败也要给用户一个「在动」的信号，而不是干等。"""
    out = run_tools_node(
        dict(
            STATE,
            source_code="public class A {}",
            proposed_action={"tool": "step_facts", "args": {"step_index": 99}},
            guard_decision={"policy": "P0"},
        )
    )
    events = _sentinel_events(out["messages"])
    assert [e["status"] for e in events if e["kind"] == "tool"] == ["ok", "error"]
    assert events[-1]["kind"] == "stage"


def _client_stream(scripts):
    """跑完整图并**经 SDK 的转客户端消息路径**，返回客户端看到的 ServerMessage 列表。

    这是端到端取证：不过这一层就不算「进了用户可见产物」。
    """
    from coze_coding_utils.helper.agent_helper import agent_iter_server_messages

    model = RouterModel(scripts)
    compiled = build_flow_graph().compile()
    items = compiled.stream(
        {"messages": [HumanMessage(content=json.dumps(_payload(), ensure_ascii=False))]},
        config={"configurable": {"chat_model": model}},
        stream_mode="messages",
    )
    return list(
        agent_iter_server_messages(
            items,
            session_id="s",
            query_msg_id="q",
            local_msg_id="l",
            run_id="r",
            log_id="g",
        )
    )


def _answer_deltas(server_msgs):
    out = []
    for sm in server_msgs:
        content = sm.content
        text = getattr(content, "answer", None)
        if text:
            out.append(text)
    return out


def test_sentinels_and_answer_reach_the_client_in_order():
    """红线（端到端）：五条哨兵按序抵达客户端，且 message_end 仍在最后。"""
    from graphs.javatutor.process_events import parse_process_events

    msgs = _client_stream(
        ['{"tool": "step_facts", "args": {"step_index": 1}}', "根据第 2 步，x 变成了 2"]
    )
    deltas = _answer_deltas(msgs)

    events = []
    for text in deltas:
        events.extend(parse_process_events(text)["events"])
    kinds = [(e["kind"], e.get("tool") or e["text"]) for e in events]
    assert kinds == [
        ("stage", "知识库检索不可用，已用通用知识回答"),
        ("stage", "正在分析问题…"),
        ("tool", "fetch_execution_context"),
        ("tool", "step_facts"),
        ("stage", "证据已就绪，正在生成回答…"),
    ]
    # 哨兵之后才是正文；收尾消息未被哨兵挤掉
    assert any("x 变成了 2" in t for t in deltas)
    assert msgs[-1].type == "message_end"
    assert msgs[-1].content.message_end.code == "0"


def test_client_stream_never_names_a_denied_tool_in_a_sentinel():
    """红线（端到端）：**哨兵** delta 里不得出现被门闩拒绝的工具名。

    哨兵绕开了 ``build_final`` 的 ``_redact_denied_tools``（它只清洗 answer 主体），
    故这里的清白完全靠「被拒提案根本到不了 run_tools」这一不变式——本测试就是它的守卫。

    注意范围：只断言**哨兵**，不含 ``main_agent`` 提案本身。提案 JSON 早就以 answer
    delta 的形式流到客户端（见下一条测试），那是既有行为、不属于本设计引入的通道。
    """
    from graphs.javatutor.process_events import parse_process_events

    msgs = _client_stream(['{"tool": "no_such_tool", "args": {}}'] * 3)
    sentinel_events = []
    for text in _answer_deltas(msgs):
        # 提案 delta 也会被 parse 扫到事件，故只挑真带哨兵标记的那些
        if "<!--jt:process" in text:
            sentinel_events.extend(parse_process_events(text)["events"])

    assert sentinel_events, "本轮应至少有一条哨兵（否则断言空转）"
    assert all("no_such_tool" not in json.dumps(e, ensure_ascii=False) for e in sentinel_events)


def test_proposal_json_delta_reaches_client_and_predates_sentinels():
    """**记录既有事实**（非本设计引入）：``main_agent`` 的提案 JSON 以 answer delta 流给客户端。

    LangGraph 的 ``stream_mode="messages"`` 会把 ``agent_messages`` 里的消息一并转出（不只
    ``messages`` 键），平台 SDK 只过滤 ``langgraph_node == "tools"``，其余非 chunk 的
    ``AIMessage`` 一律转成 ``answer``。被拒工具的提案因此出现在 delta 里。

    .. warning::
       本测试初版曾断言「提案 delta 会被 ``build_final`` 的整体回答**顶掉**」——**该前提已被证伪**
       （review 2026-09-13 §1.3）：前端 ``player.js`` 是**纯累加**（``text += t``，不插分隔符、
       无重置），全仓没有任何「顶掉」逻辑。故提案 JSON 会**留在**用户看到的正文里，
       并与紧随的正文**粘连**成 ``}}###`` ——这正是用户报告的那个 bug（**既有**，非本两件引入）。
       前端修复见 ``stripLeadingToolJson``。

    2026-09-14 更新：**终答**不再由 ``propose`` 下发（Bug A 修复），本测试因此只保留
    「提案 JSON 这条既有通道仍然在」的现状记录；「正文只出现一次」由
    ``test_client_stream_gets_the_answer_exactly_once`` 单独作红线取证。
    """
    msgs = _client_stream(
        [
            '{"tool": "step_facts", "args": {"step_index": 1}}',
            "### 当前这一步的执行内容\n\nx 从 1 变成了 2。",
        ]
    )
    deltas = _answer_deltas(msgs)

    # ① 提案 JSON 确实以 answer delta 下发
    assert any('{"tool": "step_facts"' in t for t in deltas)

    # ② 复刻前端「纯累加 + 剥哨兵」，**粘连症状**在真实产物上复现（与用户截图同形）
    from graphs.javatutor.process_events import parse_process_events

    clean = parse_process_events("".join(deltas))["clean"]
    assert clean.startswith(
        '{"tool": "step_facts", "args": {"step_index": 1}}### 当前这一步的执行内容'
    )

    # ③ 门闩红线的**终态**仍然成立：被拒工具名不进 ``answer``（``_redact_denied_tools`` 管住）
    out, _ = _run(['{"tool": "no_such_tool", "args": {}}'] * 5)

    assert [r["policy"] for r in out["step_records"]] == ["P1"] * MAX_ROUNDS
    assert "no_such_tool" not in out["answer"]


def test_client_stream_gets_the_answer_exactly_once():
    """**红线（端到端）**：正文与 ``【决策痕迹】`` 在客户端流里各只出现**一次**。

    全程走平台 SDK 的转客户端消息路径（``agent_iter_server_messages``），把 deltas 按前端
    的方式**纯累加**、再剥哨兵——即用户实际收到的那串字节。

    2026-09-14 联调 Bug A：``propose`` 的终答轮与 ``build_final`` 各下发一次，
    纯累加后用户看到「草稿 + 终稿」两段重复正文。
    """
    from graphs.javatutor.process_events import parse_process_events

    answer = "### 当前这一步的执行内容\n\nx 从 1 变成了 2。"
    msgs = _client_stream(['{"tool": "step_facts", "args": {"step_index": 1}}', answer])
    clean = parse_process_events("".join(_answer_deltas(msgs)))["clean"]

    assert clean.count("### 当前这一步的执行内容") == 1
    assert clean.count("【决策痕迹】") == 1
    # 正文只此一处，且不在痕迹段里重复（痕迹的 reasoning 里本就可能含终答文本）
    body = clean.split("\n\n【决策痕迹】\n")[0]
    assert body.count("x 从 1 变成了 2") == 1


def test_fetch_tool_call_records_its_result_in_the_trace():
    """决策痕迹里 fetch 不再是一次无信息的绿调用（2026-09-14 Bug B 可诊断性）。

    与 ``step_facts`` 的 ``result`` 同形：**两条路径都必须是合法 JSON**（消费方统一
    ``json.loads``——前端【执行过程】区据此把文件名与失败原因渲染到行上）。失败记错误、
    成功记自描述摘要，且**摘要里不放整份源码**（放了会被 300 字截断成不可解析的串）。
    """
    out, _ = _run(['{"tool": "step_facts", "args": {"step_index": 1}}', "根据第 2 步回答"])
    fetch = [tc for tc in out["tool_calls"] if tc["tool"] == "fetch_execution_context"][0]
    ok = json.loads(fetch["result"])  # 不合法就抛异常——这是本用例的重点
    assert ok["stored"] is True
    assert ok["file_source"] == "source_code"
    assert ok["code_chars"] > 0
    assert "code" not in ok

    failed, _ = _run(
        ['{"tool": "fetch_execution_context", "args": {}}'] * 4, source_code="", steps=[]
    )
    fetch = [tc for tc in failed["tool_calls"] if tc["tool"] == "fetch_execution_context"][0]
    bad = json.loads(fetch["result"])
    assert bad["stored"] is False
    assert "未能取到源码" in bad["error"]


# ── 过程哨兵（Plan A Task 4）：build_final 清理 ───────────────────────────────────


def test_final_state_carries_no_process_sentinel():
    """哨兵是流中产物：流出去了，但**不得留在终态**（messages 是入站契约 + 持久化字段）。"""
    out, _ = _run(
        ['{"tool": "step_facts", "args": {"step_index": 1}}', "根据第 2 步，x 变成了 2"]
    )
    leaked = [m for m in out["messages"] if "jt:process" in str(getattr(m, "content", ""))]
    assert leaked == []
    assert out.get("process_event_ids") == []


def test_sentinels_flow_and_are_cleaned_in_the_same_run():
    """同一轮里「流上有」与「终态无」同时成立——这是本设计的核心取舍，两条都要证。"""
    msgs = _client_stream(
        ['{"tool": "step_facts", "args": {"step_index": 1}}', "根据第 2 步，x 变成了 2"]
    )
    assert any("<!--jt:process" in t for t in _answer_deltas(msgs)), "流上必须有哨兵"

    out, _ = _run(
        ['{"tool": "step_facts", "args": {"step_index": 1}}', "根据第 2 步，x 变成了 2"]
    )
    assert not any("jt:process" in str(m.content) for m in out["messages"]), "终态必须没有哨兵"


def test_second_request_on_same_thread_never_sees_first_request_sentinels():
    """连续性守卫：同 thread 的第二轮不得看到上一轮的哨兵（否则跨请求累积）。"""
    from langgraph.checkpoint.memory import InMemorySaver

    compiled = build_flow_graph().compile(checkpointer=InMemorySaver())
    model = RouterModel(
        [
            '{"tool": "step_facts", "args": {"step_index": 1}}',
            "第一轮答案",
            "第二轮答案",
        ]
    )
    cfg = {"configurable": {"chat_model": model, "thread_id": "thread-sentinel"}}

    first = compiled.invoke(
        {"messages": [HumanMessage(content=json.dumps(_payload(), ensure_ascii=False))]}, config=cfg
    )
    assert "jt:process" not in str([m.content for m in first["messages"]])
    # 哨兵本轮确实发过（否则上面的断言是空转）
    assert [r["tool"] for r in first["step_records"]] == ["fetch_execution_context", "step_facts"]

    second = compiled.invoke(
        {"messages": [HumanMessage(content=json.dumps(_payload(), ensure_ascii=False))]},
        config=cfg,
    )
    leaked = [m for m in second["messages"] if "jt:process" in str(getattr(m, "content", ""))]
    assert leaked == [], "上一轮的哨兵不得跨请求留在 checkpointer 里"


def test_remove_message_targets_only_registered_sentinel_ids():
    """清理按登记 id 精确进行：正文消息（含最终回答）不得被误删。"""
    out, _ = _run(["直接回答"])
    contents = [str(m.content) for m in out["messages"]]
    assert any("直接回答" in c and "【决策痕迹】" in c for c in contents), "最终回答必须还在"
    assert out.get("process_event_ids") == []
