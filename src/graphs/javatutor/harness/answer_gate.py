"""终答形态门闩：把「第二步必须交付 replace 完整代码」从提示词变成可测的判据。

来源：`docs/reviews/2026-09-14-optimization-step2-marker-nondeterminism-review.md`。
带 ``【优化第二步】`` 标记的提问，线上同一字面连测 10 次里仍有 1 次回落成 ``options`` 方案卡
（用户可见症状 = 「还是让我选方向、一行代码都没有」）。原因是全链路**没有环节检查**这件事——
唯一约束是系统提示的一段自然语言加一条 few-shot，**模型可违背**。

``check_step2_answer`` 是纯函数——不调 LLM、不读环境变量、不做 IO，只看两个字符串，
所以每种违规形状都能被单元测试钉住；判据只认**形态**（``kind`` / ``code`` 完整性），不认**语义**
（代码是否真的只改了所选方向——形态可判、语义不可判，后者仍属提示层）。

门闩在图上位于 ``main_agent`` 的终答分支与 ``critic`` 之间（spec §4.9），
违规时拒绝该终答、回灌一条错误观察并回 ``main_agent`` 重提案；重试**消耗同一次轮次预算**
（``tool_rounds += 1``，与 ``guard`` 同记一笔），故重试次数天然受 ``MAX_ROUNDS`` 约束。
"""

import json
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage

from graphs.javatutor.harness.guard import MAX_ROUNDS, round_marker
from graphs.javatutor.prompting.optimization import STEP2_MARKER

# 与 ``nodes._STRUCTURED_MARKERS`` / ``critic._STRUCTURED_MARKERS`` 的副本必须逐字一致
# （不 import 那两个模块：harness 是引擎层，不该依赖节点层；漂移由 tests/test_answer_gate.py 钉住）。
EDIT_MARKER = "【编辑建议】"

# 代码省略占位。**varargs 例外**：`String... args` 的前一个字符是标识符（或 `>` / `]`），
# 不判违规；其余位置的 `...`（独行 `...`、`// ...`、`/* ... */`）都是「省略既有代码」的信号。
_ELISION = re.compile(r"(?<![A-Za-z0-9_\]>])\.\.\.")

# 回灌给模型的观察文本。模型只看到这一条，所以必须说清「要什么」与「不要再做什么」。
_RETRY_SUMMARY = (
    "第二步必须交付 `kind:\"replace\"` 的完整代码，但你这一版的【编辑建议】块不是合规的 replace 形态"
    "（{reason}）。请立刻重出终答：把【编辑建议】块改成 "
    '{{"kind":"replace","target":"<文件名>","goal":"<用户选定的那个 goal>","rationale":"...","code":"<该文件完整代码>"}}，'
    "code 必须是完整可独立编译的文件全文、不得用 `...` 占位。"
    "**不要**再给 `options` 方案卡，也不要再让用户选一次方向——用户已经选过了。"
)


@dataclass(frozen=True)
class GateVerdict:
    """终答形态门闩的裁决。``verdict`` ∈ passed | violated | not_applicable。"""

    verdict: str
    reason: str


def step2_applies(user_question: str) -> bool:
    """提问是否属于「第二步」——判据只有一个：``lstrip`` 后以标记起头。

    与 ``prompting/optimization.py`` 的判别器**同源同判据**（那边写给模型看，这边写给代码判）。
    前端模板保证标记恒在提问最前；这里的 ``lstrip`` 只是容忍前导空白，不放过正文里的提及
    （「怎么理解【优化第二步】这个标记」这类提问不适用门闩）。
    """
    return (user_question or "").lstrip().startswith(STEP2_MARKER)


def _edit_block_obj(answer: str) -> tuple[dict | None, str]:
    """取出回答里那个唯一的【编辑建议】块的 JSON，返回 ``(obj, 失败原因)``。

    必须**平衡解析**：Java 代码里有 ``{``/``}``，正则/非贪婪匹配会在第一个嵌套 ``}`` 处截断，
    把合规的 replace 误判成违规（``_strip_leaked_json`` 用同一手法，同一理由）。
    """
    if answer.count(EDIT_MARKER) != 1:
        return None, f"必须恰好一个 {EDIT_MARKER} 块，实际 {answer.count(EDIT_MARKER)} 个"
    start = answer.find("{", answer.find(EDIT_MARKER))
    if start < 0:
        return None, f"{EDIT_MARKER} 块后没有 JSON 负载"
    try:
        obj, _ = json.JSONDecoder().raw_decode(answer[start:])
    except ValueError:
        return None, f"{EDIT_MARKER} 块的 JSON 无法解析"
    if not isinstance(obj, dict):
        return None, f"{EDIT_MARKER} 块的 JSON 负载不是对象"
    return obj, ""


def check_step2_answer(user_question: str, answer: str) -> GateVerdict:
    """第二步提问的终答形态裁决。纯函数，见模块 docstring。"""
    if not step2_applies(user_question):
        return GateVerdict("not_applicable", "")
    obj, failure = _edit_block_obj(answer or "")
    if obj is None:
        return GateVerdict("violated", failure)
    if obj.get("options"):
        return GateVerdict("violated", "块里带了 `options` 字段（方案卡），第二步不得让用户再选方向")
    if obj.get("kind") != "replace":
        return GateVerdict("violated", f'`kind` 是 {obj.get("kind")!r}，第二步必须是 "replace"')
    code = obj.get("code")
    if not isinstance(code, str) or not code.strip():
        return GateVerdict("violated", "`code` 为空或不是字符串")
    if _ELISION.search(code):
        return GateVerdict("violated", "`code` 里含 `...` 省略占位，必须交付完整文件全文")
    return GateVerdict("passed", "")


def _retry_message(text: str, rounds: int) -> HumanMessage:
    """回灌通道是 ``HumanMessage``，**绝不能**是 ``AIMessage``。

    ``propose`` 终答轮的 Bug A 教训（2026-09-14 联调）：``stream_mode="messages"`` 会把节点返回
    键里的非 chunk ``AIMessage`` 转成 ``answer`` delta 流出，被前端纯累加后与 ``build_final``
    的终答合成「正文重复两遍」。被拒的终答因此既不进 ``agent_messages``，也不以任何
    ``AIMessage`` 形式回灌，只留一段可读的观察文本。
    """
    return HumanMessage(content=f"\n\n[第二步交付形态未通过]\n{text}\n\n{round_marker(rounds)}")


def answer_gate_node(state) -> dict:
    """终答形态门闩。不写 ``step_records``——它记的是「逐动作的观察」，而门闩没执行任何动作。"""
    rounds = int(state.get("tool_rounds", 0) or 0)
    previous = state.get("answer_gate_decision") or {}
    retries = int(previous.get("retries", 0) or 0)
    decision = check_step2_answer(state.get("user_question", ""), state.get("answer", ""))

    if decision.verdict != "violated":
        return {
            "answer_gate_decision": {"verdict": decision.verdict, "reason": "", "retries": retries}
        }

    # 收束轮（tool_rounds >= MAX_ROUNDS）之后重试无意义：该模式下 propose 永不产出 Action，
    # 再来一轮只会多花一跳。此时按已定收束策略交付，并如实记 violated。
    if rounds >= MAX_ROUNDS:
        return {
            "answer_gate_decision": {"verdict": "violated", "reason": decision.reason, "retries": retries}
        }

    rounds += 1
    return {
        # 清空被拒的终答：不清的话它会被 build_final 当兜底答案交付（`revised_answer or answer`），
        # 而这一轮的意义正是「这一版不算数」。
        "answer": "",
        "tool_rounds": rounds,
        "agent_messages": list(state.get("agent_messages") or [])
        + [_retry_message(_RETRY_SUMMARY.format(reason=decision.reason), rounds)],
        "answer_gate_decision": {"verdict": "retry", "reason": decision.reason, "retries": retries + 1},
    }


def route_after_answer_gate(state) -> str:
    """``retry`` → 回提案节点重出终答；其余（passed / violated / not_applicable）→ 照常评审。"""
    decision = state.get("answer_gate_decision") or {}
    return "propose" if decision.get("verdict") == "retry" else "critic"
