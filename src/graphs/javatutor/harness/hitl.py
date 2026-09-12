"""HITL（human-in-the-loop）开关与提问载荷。

线上没有 resume 通道（见 spec §6 外壳请求清单），所以开关**默认关**是安全边界而非未完成项：
默认开启会让需要用户选择的提问永久挂起。``interrupt()`` 的 value 就是 ``hitl_brief()``
的返回值，将来透传到 SSE 时也是同一份载荷。
"""

import os

from graphs.javatutor.harness.contracts import GuardDecision


def hitl_enabled() -> bool:
    """读取运行时开关，默认关。"""
    return os.getenv("COZE_AGENT_HITL", "0").strip().lower() in ("1", "true", "yes", "on")


def hitl_brief(decision: GuardDecision) -> dict:
    """把裁决转成「要给用户看的问题 + 可选项」。"""
    return {
        "question": f"需要你确认：{decision.reason}",
        "options": list(decision.options),
    }
