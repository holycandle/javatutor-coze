"""统一动作契约：提案（Action）/ 治理裁决（GuardDecision）/ 观察（Observation）。

这一层只做「结构」，不做判断：
- ``parse_action`` 把模型输出解析成 Action，解析不了就明确说为什么（ParseError），
  不再把非法的 ``args`` 静默兜成 ``{}``；
- ``GuardDecision`` 是 ``harness.guard`` 的返回值，把治理结论从提示词变成数据；
- ``Observation`` 是每个动作的落地记录（原则⑦的 StepRecord），
  ``render_observation`` 负责把它渲染回模型可读的文本。
"""

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Action:
    """模型提出的一个工具调用（尚未经治理校验）。"""

    tool: str
    args: dict
    raw: str


@dataclass(frozen=True)
class GuardDecision:
    """治理门闩的裁决结果。"""

    verdict: str  # "allow" | "deny" | "needs_decision"
    policy: str  # 触发策略编号（P0/P1/...）
    reason: str  # 给模型或用户读的一句话
    options: list  # needs_decision 时的可选项，其余为空


@dataclass(frozen=True)
class Observation:
    """一次动作的最终落地形态。"""

    tool: str
    args: dict
    status: str  # "ok" | "error" | "denied" | "invalid_args"
    policy: str
    summary: str  # 渲染给模型的文本
    payload: dict  # 结构化原始数据
    latency_ms: float
    truncated: bool


@dataclass(frozen=True)
class ParseError:
    """模型确实想调工具，但输出的结构让人没法执行。"""

    reason: str
    raw: str = ""
    tool: str = ""  # 能识别出来的工具名（可能为空），供门闩判白名单


def parse_action(raw: str) -> Action | None | ParseError:
    """解析模型输出。

    返回 ``None`` 表示「这不是工具提案」（散文即终答）；返回 ``ParseError``
    表示「是提案但没法执行」，两者区别对下游很重要。
    """
    text = (raw or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get("tool"):
        return None
    tool = data["tool"]
    if not isinstance(tool, str):
        return ParseError(f"tool 必须是字符串，收到 {type(tool).__name__}", text, str(tool))
    args = data.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return ParseError(f"args 必须是对象，收到 {type(args).__name__}", text, tool)
    return Action(tool=tool, args=args, raw=text)


def render_observation(obs: Observation) -> str:
    """把观察渲染成追加进 agent_messages 的文本。

    失败（deny/invalid_args/error）必须把原因带出去——否则模型下一轮只会重复同一个错。
    """
    if obs.status == "ok":
        return obs.summary
    return f"\n\n[{obs.tool} 未执行：{obs.policy}]\n{obs.summary}"


def observation_to_dict(obs: Observation) -> dict[str, Any]:
    """Observation → dict，便于放进 state（TypedDict 只合并 dict）。"""
    return {
        "tool": obs.tool,
        "args": obs.args,
        "status": obs.status,
        "policy": obs.policy,
        "summary": obs.summary,
        "payload": obs.payload,
        "latency_ms": obs.latency_ms,
        "truncated": obs.truncated,
    }


def action_from_state(state: dict) -> Action | ParseError | None:
    """把 state 里的 ``proposed_action``（dict 形态）还原成契约对象。

    state 必须能被序列化（含 checkpointer 的 checkpoint），所以提案在 state 里存 dict，
    到治理节点再还原成 dataclass。
    """
    proposal = state.get("proposed_action") or {}
    if not proposal:
        return None
    if proposal.get("parse_error"):
        return ParseError(
            reason=proposal["parse_error"],
            raw=proposal.get("raw", ""),
            tool=proposal.get("tool", ""),
        )
    return Action(
        tool=proposal.get("tool", ""),
        args=proposal.get("args") or {},
        raw=proposal.get("raw", ""),
    )
