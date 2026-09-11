"""执行节点：把门闩放行的提案真正执行，并把结果变成结构化观察。

产物有两份，同一份数据两种形态：
- **给模型的**：渲染文本（复用既有渲染器，不新写文案）追加进 ``agent_messages``；
- **给系统/评测的**：``Observation`` 追加进 ``step_records``（原则⑦的 StepRecord）。

执行节点不做任何治理判断——它只处理已经被 ``guard`` 放行的提案。
"""

import json
import time

from langchain_core.messages import HumanMessage

from graphs.javatutor.harness.contracts import Observation, observation_to_dict, render_observation
from graphs.javatutor.harness.guard import REPEAT_STEP_NUDGE, round_marker
from graphs.javatutor.harness.registry import TOOLS
from graphs.javatutor.harness.render import _format_step_facts, _handle_fetch
from tools.step_facts import step_facts

# 治理侧白名单（``registry.TOOLS``）与本节点的派发分支必须同源：漂移在 import 期就炸，
# 而不是等线上出现「门闩放行了、执行节点却没有分支」的静默 error 观察。
_DISPATCHED = {"fetch_execution_context", "step_facts"}
assert _DISPATCHED == set(TOOLS), "run_tools 的派发分支与 registry.TOOLS 不同步"


def _observation(tool, args, status, policy, summary, payload, latency_ms) -> Observation:
    return Observation(
        tool=tool,
        args=args,
        status=status,
        policy=policy,
        summary=summary,
        payload=payload,
        latency_ms=latency_ms,
        truncated=False,
    )


def _run_fetch(state, args):
    """执行一次 fetch。返回 (渲染文本, state 回灌, tool_calls 记录, 是否失败)。

    ``calls`` / ``updates`` 是本次调用的**局部**容器，这样 ``fetch_context_failed``
    的有无精确对应当次调用，不会被上一轮的结果污染。
    """
    calls: list = []
    updates: dict = {}
    text = _handle_fetch(calls, updates, state, args)
    return text, updates, calls, bool(updates.get("fetch_context_failed", True))


def _fetch_payload(updates: dict) -> dict:
    keys = ("run_id", "steps_count", "current_step_index", "current_line", "algorithm_tags")
    return {k: updates[k] for k in keys if k in updates}


def run_tools_node(state, model=None) -> dict:
    """执行 ``state["proposed_action"]``，必要时先自动前置一次 fetch。"""
    proposal = state.get("proposed_action") or {}
    decision = state.get("guard_decision") or {}
    tool = proposal.get("tool", "")
    args = proposal.get("args") or {}

    fetched_injected = bool(state.get("fetched_injected"))
    served = list(state.get("served_step_indices") or [])
    tool_calls: list = []
    observations: list[Observation] = []
    memories: list = []
    fetched_updates: dict = {}

    # 自动前置 fetch：查单步证据前先把执行上下文读进 state。
    # 它经 decide 的既有语义放行、且**不占用轮次**（见 spec §4.2 注）。
    if tool == "step_facts" and not fetched_injected:
        text, updates, calls, failed = _run_fetch(state, {})
        tool_calls.extend(calls)
        fetched_updates.update(updates)
        fetched_injected = True
        observations.append(
            _observation(
                "fetch_execution_context",
                {},
                "error" if failed else "ok",
                "P0-auto-fetch",
                text,
                _fetch_payload(updates),
                float(updates.get("fetch_context_latency_ms", 0.0) or 0.0),
            )
        )

    if tool == "step_facts":
        started = time.perf_counter()
        try:
            result = step_facts(state, **args)
        except TypeError as exc:
            # 参数含未知键或非法类型：给出结构化错误，而不是中断循环。
            # （正常路径已由门闩 P2 拦下，这里只兜底。）
            result = {"error": f"step_facts 参数非法: {exc}", "evidence": {}, "diff": []}
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        # 记录参数 + 返回值（截断）供决策痕迹诊断：能看清是越界报错还是返回了证据
        tool_calls.append(
            {"tool": "step_facts", "args": args, "result": json.dumps(result, ensure_ascii=False)[:300]}
        )
        text = _format_step_facts(args, result)
        ok = not result.get("error")
        if ok:
            memories.append(
                {
                    "step_index": args.get("step_index", state.get("current_step_index", 0)),
                    "content": json.dumps(result, ensure_ascii=False)[:600],
                    "importance": 0.8,
                }
            )
            idx = args.get("step_index")
            if idx is not None and idx not in served:
                served.append(idx)
            if decision.get("policy") == "P5":
                # 同一步骤再次被查询：证据已在上文给出，明确要求直接作答。
                text += "\n\n[提示] " + REPEAT_STEP_NUDGE
        observations.append(
            _observation(
                "step_facts",
                args,
                "ok" if ok else "error",
                decision.get("policy", ""),
                text,
                result,
                latency_ms,
            )
        )
    elif tool == "fetch_execution_context":
        text, updates, calls, failed = _run_fetch(state, args)
        tool_calls.extend(calls)
        fetched_updates.update(updates)
        fetched_injected = True
        observations.append(
            _observation(
                "fetch_execution_context",
                args,
                "error" if failed else "ok",
                decision.get("policy", ""),
                text,
                _fetch_payload(updates),
                float(updates.get("fetch_context_latency_ms", 0.0) or 0.0),
            )
        )
    else:
        # 注册表里出现了执行节点没有分支的工具：宁可报错也不要静默空转
        observations.append(
            _observation(
                tool,
                args,
                "error",
                "P0-unknown-dispatch",
                f"工具 {tool} 没有执行分支（注册表与执行节点不同步）。",
                {},
                0.0,
            )
        )

    marker = round_marker(state.get("tool_rounds", 0))
    # 一次执行的多个观察合并成**一条** HumanMessage：agent_messages 保持
    # System→Human→AI→Human→AI… 的严格交替（连续两条同角色消息对聊天 API 不友好，
    # 而「自动前置 fetch + step_facts」是常态，会稳定产出两条）。
    messages = [
        HumanMessage(content="\n".join(f"{render_observation(o)}\n\n{marker}" for o in observations))
    ]

    return {
        "tool_calls": list(state.get("tool_calls") or []) + tool_calls,
        "step_records": list(state.get("step_records") or [])
        + [observation_to_dict(o) for o in observations],
        "step_memories": (list(state.get("step_memories") or []) + memories)[-5:],
        "agent_messages": list(state.get("agent_messages") or []) + messages,
        "proposed_action": {},
        "fetched_injected": fetched_injected,
        "served_step_indices": served,
        **fetched_updates,
    }
