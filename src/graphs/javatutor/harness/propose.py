"""提案节点：一次 LLM 调用，产出「提案（Action）」或「终答（answer）」。

这是真 ReAct 的 reasoning 侧：每轮把**累积的** ``agent_messages`` 原样交给模型，
模型能看到自己上一轮的提案原文，而不是每轮重建一个只有 system + context 的对话。

轮次用尽时进入**收束模式**（spec §4.4）：该模式永不产出 Action，
因此「图一定终止」由结构保证，而不是靠提示词祈愿。
"""

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from graphs.javatutor.harness.contracts import ParseError, parse_action
from graphs.javatutor.harness.guard import MAX_ROUNDS
from graphs.javatutor.prompts import SYSTEM_PROMPT_MAIN_AGENT
from graphs.javatutor.prompting.intent_guidance import render_intent_guidance
from graphs.javatutor.prompting.main_fewshots import get_main_few_shots
from graphs.javatutor.prompting.optimization import render_optimization_guidance
from graphs.javatutor.prompting.panels import (
    render_algo_catalog,
    render_nav_guidance,
    render_run_mode_guide,
    render_ui_map,
    render_usage_guide,
)

LLM_UNAVAILABLE_ANSWER = "抱歉，回答生成服务暂时不可用，请稍后重试。"
GIVE_UP_ANSWER = "抱歉，我暂时无法回答这个问题。"

CONVERGENCE_INSTRUCTION = (
    "[收束轮] 工具轮次预算已用尽。请立刻基于上文已获得的证据直接给出最终回答，"
    "不要再输出任何工具调用 JSON。若证据不足以回答，请明确说明「还缺什么」而不是猜测。"
)

CONVERGENCE_PREFIX = "（工具轮次预算已用尽，以下为已获得的执行证据）"


def _main_system_prompt(intent: str = "") -> str:
    """主 Agent 系统提示 = 模板 + 运行时注入的导航引导 / 算法目录 / 使用指南 / 优化引导 / 运行模式判读 / 面板图 / 意图引导 / few-shot（随 manifest 联动）。

    ``intent`` 为 concept / debug / other 时在 few-shot 之前追加「本轮问题类型」段；
    ``data_query`` 与空串**不追加**，保证既有基线逐字不变
    （见 ``prompting/intent_guidance.py`` 的模块 docstring）。
    """
    few = "\n\n".join(get_main_few_shots())
    guidance = render_intent_guidance(intent)
    intent_part = f"{guidance}\n\n" if guidance else ""
    return (
        f"{SYSTEM_PROMPT_MAIN_AGENT}\n\n{render_nav_guidance()}\n\n{render_algo_catalog()}\n\n"
        f"{render_usage_guide()}\n\n{render_optimization_guidance()}\n\n{render_run_mode_guide()}\n\n"
        f"{render_ui_map()}\n\n{intent_part}## 回答示例\n{few}"
    )


def _resolve_model(model):
    """优先用传入的 model，否则从 LangGraph configurable 中取 chat_model."""
    if model is not None:
        return model
    try:
        from langgraph.config import get_config

        return get_config().get("configurable", {}).get("chat_model")
    except Exception:
        return None


def _invoke(messages, model):
    resolved = _resolve_model(model)
    if resolved is not None:
        return resolved.invoke(messages)
    from graphs.javatutor.llm import llm_complete

    raw = llm_complete(messages, temperature=0.5, max_completion_tokens=2000)
    return AIMessage(content=raw)


def _convergence_answer(state: dict) -> str:
    """收束轮兜底：把已到手的成功观察交付出去，而不是丢掉证据给一句道歉。"""
    evidence = [
        r.get("summary", "")
        for r in (state.get("step_records") or [])
        if r.get("status") == "ok" and r.get("summary")
    ]
    if not evidence:
        return GIVE_UP_ANSWER
    return CONVERGENCE_PREFIX + "\n" + "\n".join(evidence)


def propose(state, model=None) -> dict[str, Any]:
    """一次 LLM 调用：产出提案(Action) 或终答(answer)。收束模式下永不产出 Action。"""
    rounds = int(state.get("tool_rounds", 0) or 0)
    history = list(state.get("agent_messages") or [])
    if not history:
        history = [
            SystemMessage(content=_main_system_prompt(state.get("intent", ""))),
            HumanMessage(content=f"{state.get('context_built', '')}\n\n[当前轮次] 1/{MAX_ROUNDS}"),
        ]

    converging = rounds >= MAX_ROUNDS
    messages = (
        history + [HumanMessage(content=CONVERGENCE_INSTRUCTION)] if converging else history
    )

    try:
        resp = _invoke(messages, model).content
    except Exception:
        return {"answer": LLM_UNAVAILABLE_ANSWER, "agent_messages": history, "proposed_action": {}}

    if not isinstance(resp, str):
        resp = str(resp)

    # 终答轮 / 收束轮**不**把模型原文写进 ``agent_messages``（2026-09-14 联调 Bug A）。
    # 该轮之后图一定不再回到 propose（``_route_after_propose`` 把无 action 的轮次导向
    # critic），这条 ``AIMessage`` 对后续推理无用；但 ``stream_mode="messages"`` 会把
    # ``agent_messages`` 一并转出，平台 SDK 将其转成 ``answer`` delta，与 ``build_final``
    # 下发的终答在前端纯累加后表现为「正文重复两遍」。
    # ``agent_messages`` 无 reducer（返回即替换），故返回 ``history`` 即等价于「不追加」。
    if converging:
        parsed = parse_action(resp)
        answer = _convergence_answer(state) if parsed is not None else resp
        return {"answer": answer, "agent_messages": history, "proposed_action": {}}

    action = parse_action(resp)
    if action is None:
        return {"answer": resp, "agent_messages": history, "proposed_action": {}}

    # 提案轮（含 ParseError）仍须追加：模型要看到自己上一轮的提案原文，才有因果链。
    out_messages = history + [AIMessage(content=resp)]
    if isinstance(action, ParseError):
        return {
            "proposed_action": {"tool": action.tool, "parse_error": action.reason, "raw": action.raw},
            "agent_messages": out_messages,
        }
    return {
        "proposed_action": {"tool": action.tool, "args": action.args, "raw": action.raw},
        "agent_messages": out_messages,
    }
