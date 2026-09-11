"""治理门闩：把「工具能不能执行」从提示词变成可测的裁决。

``decide(action, state) -> GuardDecision`` 是纯函数——**不抛异常、不读环境变量、不做 IO**，
所以每条策略都能被单元测试钉住。判定顺序 P3（预算）→ P1（白名单）→ P2（参数）→
P4（歧义）→ P5（重复）→ allow/P0，见
``docs/spec/2026-09-11-agent-harness-react-loop-design.md`` §4.5。

P4 只产出 ``needs_decision``；「HITL 关闭时降级为 deny」由 ``guard_node`` 决定——
那取决于运行环境，不属于这个纯函数。
"""

from graphs.javatutor.harness.contracts import Action, GuardDecision, ParseError
from graphs.javatutor.harness.registry import TOOLS, validate_args
from tools.fetch_execution_context import match_file_key

MAX_ROUNDS = 3

# P5 的提示文本：与 2026-09-02 起的既有文案一字不差，只有一处定义。
REPEAT_STEP_NUDGE = "这一步的证据已在上文「step_facts 结果」中给出，请直接基于该证据回答用户问题，不要重复查询同一步骤。"


def round_marker(tool_rounds: int) -> str:
    """追加给模型的轮次锚点：标的是「下一次 propose 是第几轮」。"""
    return f"[当前轮次] {int(tool_rounds or 0) + 1}/{MAX_ROUNDS}"


def decide(action: Action | ParseError, state: dict) -> GuardDecision:
    """对一个提案给出裁决。"""
    # P3 轮次预算兜底：正常路径不可达（收束轮不再产出 Action），仅作结构兜底。
    if int(state.get("tool_rounds", 0) or 0) >= MAX_ROUNDS:
        return GuardDecision(
            verdict="deny",
            policy="P3",
            reason="轮次预算已用尽，请直接基于已获得的证据作答。",
            options=[],
        )

    tool = action.tool

    # P1 工具白名单
    if tool not in TOOLS:
        return GuardDecision(
            verdict="deny",
            policy="P1",
            reason=(
                f"工具 {tool} 不在注册表中；可用工具："
                f"{' / '.join(sorted(TOOLS))}。请改用其中一个，或直接回答。"
            ),
            options=[],
        )

    # P2 参数结构校验（单一事实源 = 工具的 TOOL_SCHEMA）
    if isinstance(action, ParseError):
        return GuardDecision(
            verdict="deny", policy="P2", reason=f"参数不合法：{action.reason}", options=[]
        )
    problems = validate_args(action.tool, action.args)
    if problems:
        return GuardDecision(
            verdict="deny",
            policy="P2",
            reason="参数不合法：" + "；".join(problems),
            options=[],
        )

    # P4 文件名歧义：只在多文件且按既有口径都匹配不到时才需要人来选
    files = state.get("files") or {}
    if action.tool == "fetch_execution_context":
        wanted = action.args.get("file")
        if wanted and len(files) > 1 and match_file_key(files, wanted) is None:
            options = sorted(files.keys())[:8]
            return GuardDecision(
                verdict="needs_decision",
                policy="P4",
                reason=(
                    f"项目里有多个文件，但找不到 {wanted}。可选文件：{'、'.join(options)}。"
                    "请用其中某个文件名重新提出读取请求。"
                ),
                options=options,
            )

    # P5 重复步骤：刻意保持 allow（该行为是评测基线的一部分），只做标记与提示
    if tool == "step_facts" and action.args.get("step_index") in (
        state.get("served_step_indices") or []
    ):
        return GuardDecision(
            verdict="allow",
            policy="P5",
            reason=REPEAT_STEP_NUDGE,
            options=[],
        )

    return GuardDecision(verdict="allow", policy="P0", reason="", options=[])
