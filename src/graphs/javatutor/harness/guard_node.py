"""门闩节点：图上唯一的暂停点。

- 每次进入必 `tool_rounds += 1`（轮次预算的唯一记账处，见 spec §4.3）；
- ``allow`` 放行到执行节点，自己只写裁决；
- ``deny`` / ``invalid_args`` 写一条可读观察回灌给模型，``tool_calls`` 不新增
  （没执行过的工具不该出现在「实际调用」记录里）；
- ``needs_decision`` 且 HITL 开启时 ``interrupt()`` 暂停；恢复值用来**补全原提案**里
  唯一不可判定的那个值（文件名），补齐后放行给执行节点——门闩没有替模型选工具，
  只是替人回答了自己发起的问题。未开启时降级为 ``deny``。
"""

from dataclasses import asdict

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from graphs.javatutor.harness.contracts import (
    GuardDecision,
    Observation,
    action_from_state,
    observation_to_dict,
    render_observation,
)
from graphs.javatutor.harness.guard import decide, round_marker
from graphs.javatutor.harness.hitl import hitl_brief, hitl_enabled


def _observation(tool, args, status, policy, summary, payload) -> Observation:
    return Observation(
        tool=tool,
        args=args,
        status=status,
        policy=policy,
        summary=summary,
        payload=payload,
        latency_ms=0.0,
        truncated=False,
    )


def _append(state, observation: Observation, rounds: int) -> dict:
    """把观察同时写进 step_records（结构化）与 agent_messages（给模型）。

    轮次锚点用**本节点刚算出的** ``rounds``（state 里还是进入前的旧值）。
    """
    marker = round_marker(rounds)
    return {
        "step_records": list(state.get("step_records") or []) + [observation_to_dict(observation)],
        "agent_messages": list(state.get("agent_messages") or [])
        + [HumanMessage(content=f"{render_observation(observation)}\n\n{marker}")],
    }


def guard_node(state) -> dict:
    rounds = int(state.get("tool_rounds", 0) or 0) + 1
    action = action_from_state(state)
    if action is None:
        # 路由保证走不到这里（propose 要么给终答、要么给提案），但与其它 deny 分支对齐：
        # 唯一的例外不该是「拒绝了却不让模型知道原因」。
        return {
            "tool_rounds": rounds,
            "guard_decision": asdict(GuardDecision("deny", "P0-no-action", "没有可执行的提案。", [])),
            **_append(
                state,
                _observation(
                    "",
                    {},
                    "denied",
                    "P0-no-action",
                    "没有可执行的提案。请直接作答，或给出{\"tool\": ..., \"args\": ...}形式的工具调用。",
                    {},
                ),
                rounds,
            ),
            "proposed_action": {},
        }

    # decide 看到的是**进入前**的计数：第 1/2/3 次进入都放行（正好 3 轮工具，与
    # 历史循环 ``while rounds < MAX_ROUNDS`` 一致），P3 只拦正常路径不可达的第 4 次进入。
    decision = decide(action, state)
    tool = getattr(action, "tool", "")
    args = getattr(action, "args", None) or {}

    if decision.verdict == "needs_decision":
        if hitl_enabled():
            choice = interrupt(hitl_brief(decision))
            args = {**args, "file": choice}
            # 不写 agent_messages：证据由 run_tools 的观察给出。若这里也追加一条，
            # 就会和紧随其后的执行观察连成两条同角色的 HumanMessage。
            resolved = _observation(
                tool,
                args,
                "ok",
                "P4-resolved",
                f"用户从候选文件中选择了 {choice}，已用该文件名继续读取。",
                {"user_choice": choice},
            )
            return {
                "tool_rounds": rounds,
                "guard_decision": asdict(
                    GuardDecision("allow", "P4-resolved", f"用户选择：{choice}", [])
                ),
                "step_records": list(state.get("step_records") or [])
                + [observation_to_dict(resolved)],
                # 补齐原提案（只改 file），放行到执行节点——避免 resume 回 propose 后
                # 正好撞上收束轮、让用户的选择被静默丢弃。
                "proposed_action": {"tool": tool, "args": args},
            }
        # HITL 默认关（线上没有 resume 通道）：降级为 deny，让模型据 reason 自我修正
        decision = GuardDecision("deny", decision.policy, decision.reason, decision.options)

    if decision.verdict == "allow":
        return {"tool_rounds": rounds, "guard_decision": asdict(decision)}

    denied = _observation(
        tool,
        args,
        "invalid_args" if decision.policy == "P2" else "denied",
        decision.policy,
        decision.reason,
        {},
    )
    return {
        "tool_rounds": rounds,
        "guard_decision": asdict(decision),
        **_append(state, denied, rounds),
        "proposed_action": {},
    }
