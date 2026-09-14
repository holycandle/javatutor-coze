"""评审与修订节点。"""

import difflib
import json
import os
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from graphs.javatutor.prompts import SYSTEM_PROMPT_CRITIC, SYSTEM_PROMPT_REVISE

# 结构化块标记。**与 `nodes.py::_STRUCTURED_MARKERS` 必须逐字一致**
# （`tests/test_critic.py::test_structured_markers_match_nodes` 钉住）——这里不直接 import
# 是为了不让评审模块拖进整个 nodes 模块。
_STRUCTURED_MARKERS = ("【决策痕迹】", "【编辑建议】", "【视角导航】")

# G1 相似度下限（题旨漂移闸）。低于它且评审未标 `blocking` ⇒ 回退原答。
SIMILARITY_FLOOR = 0.5

# 仓库根（src/graphs/javatutor/critic.py → 上溯三层）。运行时开关的配置就在这里。
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "agent_llm_config.json"


def _config_path() -> Path:
    """配置文件位置：`COZE_WORKSPACE_PATH` 优先，缺省用仓库根。"""
    root = os.environ.get("COZE_WORKSPACE_PATH")
    if root:
        return Path(root) / "config" / "agent_llm_config.json"
    return _DEFAULT_CONFIG_PATH


def _runtime_flag(name: str, default):
    """读 `config/agent_llm_config.json` 的 `config` 段开关。

    文件缺失 / JSON 坏 / 段或键缺失 / 类型与默认值不符 ⇒ 一律回落 `default`：
    本地测试与旧部署都不会因缺配置而炸，也不会因配置写错而静默改变行为。
    """
    try:
        with open(_config_path(), encoding="utf-8") as f:
            data = json.load(f)
        value = (data.get("config") or {}).get(name, default)
    except Exception:
        return default
    return value if isinstance(value, type(default)) else default


def _resolve_model(model):
    """优先用传入的 model，否则从 LangGraph configurable 中取 chat_model。

    使用 langgraph.config.get_config（非 langchain_core.runnables.get_runnable_config）。
    """
    if model is not None:
        return model
    try:
        from langgraph.config import get_config

        return get_config().get("configurable", {}).get("chat_model")
    except Exception:
        return None


def _invoke(messages, model):
    """调用 LLM，优先用注入的 model（测试），否则用原始 HTTP 调用。"""
    resolved = _resolve_model(model)
    if resolved is not None:
        return resolved.invoke(messages)
    from graphs.javatutor.llm import llm_complete

    raw = llm_complete(
        messages=messages,
        temperature=0.1,
        max_completion_tokens=800,
    )
    from langchain_core.messages import AIMessage

    return AIMessage(content=raw)


def _parse_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _as_bool(value) -> bool:
    """兼容布尔值与字符串：'true'/'false' 均按文本解析，避免 bool('false') 误判为通过。"""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _facts(state) -> str:
    from graphs.javatutor.prompting.contexts import build_facts_block

    return build_facts_block(state)


def _validate_issues(raw_issues, answer: str, facts: str) -> list[dict]:
    """CD-3 quote-or-drop：意见必须给出**可核实**的出处，否则机械丢弃。

    `answer_span` 须为候选回答的子串、`fact` 须为事实依据块的子串（去首尾空白后 `in`）。
    字符串数组（旧格式）与缺字段的对象都没有出处可言 ⇒ 丢弃。

    为什么必须这样做：无出处的意见既无法被反驳、也无法被精确修订，却足以换来一次全文重写
    （四轮归档里评审拦下 33 条，其中 11 条 Judge 判 correct）。
    """
    valid: list[dict] = []
    for item in raw_issues if isinstance(raw_issues, list) else []:
        if not isinstance(item, dict):
            continue
        span = str(item.get("answer_span") or "").strip()
        fact = str(item.get("fact") or "").strip()
        if not span or not fact:
            continue
        if span not in answer or fact not in facts:
            continue
        valid.append(item)
    return valid


def _critique(answer: str, facts: str, model) -> tuple[bool, list[dict], bool]:
    """跑一次评审。返回 `(是否通过, 有效意见, 是否跳过)`。

    `critic_node`（首评）与 G4 二次评审共用——**同一份提示词、同一套出校验收**，
    两处各写一遍必然漂移。模型异常或输出不可解析 ⇒ 跳过并按通过处理（fail-open）。
    """
    messages = [
        SystemMessage(content=SYSTEM_PROMPT_CRITIC),
        HumanMessage(content=f"候选回答：\n{answer}\n\n事实依据：\n{facts}"),
    ]
    try:
        parsed = _parse_json(_invoke(messages, model).content)
    except Exception:
        return True, [], True
    if parsed is None:
        return True, [], True
    issues = _validate_issues(parsed.get("issues"), answer, facts)
    # 判失败需要**两个**条件同时成立：模型判 pass=false，且留下至少一条给出处的意见。
    # 有效意见为空 ⇒ 判通过（fail-open）：模型判失败却给不出任何可核实的出处时，
    # 「没有可核实的意见」比「信一个核实不上的意见」更安全。
    failed = (not _as_bool(parsed.get("pass", False))) and bool(issues)
    return not failed, issues, False


def critic_node(state, model=None) -> dict[str, Any]:
    # 上下文不可用时的固定降级文案是确定性输出，不进入评审/修订的 LLM 循环。
    if state.get("fetch_context_failed") and not state.get("has_steps"):
        return {"critic_passed": True, "critic_feedback": "", "critic_skipped": True}
    answer = state.get("revised_answer") or state.get("answer") or ""
    passed, issues, skipped = _critique(answer, _facts(state), model)
    if skipped:
        return {"critic_passed": True, "critic_feedback": "", "critic_skipped": True}
    return {
        "critic_passed": passed,
        "critic_feedback": json.dumps(issues, ensure_ascii=False),
        "critic_skipped": False,
    }


_EDIT_SUGGESTION_MARKER = "【编辑建议】"


def _split_edit_block(answer: str) -> tuple[str, str]:
    """把【编辑建议】块从回答末尾拆出，返回 (正文, 编辑块)。

    编辑建议块是前端机械应用（Monaco executeEdits）的契约数据；
    修订节点用「不要 JSON」的提示词重写回答时会把它丢掉，这里先拆出暂存。
    """
    idx = answer.find(_EDIT_SUGGESTION_MARKER)
    if idx == -1:
        return answer, ""
    return answer[:idx].rstrip(), answer[idx:].strip()


def _parse_issues(feedback) -> list[dict]:
    """把 `critic_feedback` 解析成**意见对象**列表；非对象项与坏 JSON 一律丢弃。

    兼容旧格式（字符串数组）：字符串不是可核实的意见，返回空列表 ⇒ 不产生 `blocking` 豁免。
    """
    try:
        data = json.loads(feedback or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _has_blocking(feedback) -> bool:
    """是否存在 `blocking: true` 的意见（CD-3：确需大改时由评审显式承担）。"""
    return any(_as_bool(item.get("blocking")) for item in _parse_issues(feedback))


def _similarity(a: str, b: str) -> float:
    """两段文本的相似度（`difflib` 比值，0–1）。空串对：两者都空算 1.0，否则 0.0。"""
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _accepted(original_body: str, new_body: str, edit_block: str, feedback) -> tuple[bool, str]:
    """修订稿验收闸（CD-1 的 G1 / G2）。返回 `(是否采纳, 回退原因)`。

    `reason ∈ {"", "similarity", "nav_block", "edit_block"}`。
    G3（引用不劣化）/ G4（二次评审）在 `revise_node` 里另做——它们需要 state 与 model。

    顺序：先查块保全（结构性丢失是**确定**缺陷），再查相似度（启发式）。
    `blocking` 意见豁免 G1：确需大改的场景由评审显式承担，不能被相似度闸堵死。
    """
    if edit_block:
        # 暂存块由调用方逐字拼回 ⇒ 最终文本里应**恰好**出现一次。多于一次说明模型自己又产出了
        # 一个【编辑建议】块（提示词明令「不要 JSON」），两个块会互相冲突 ⇒ 判不通过。
        if new_body.count(_EDIT_SUGGESTION_MARKER) != 1 or edit_block not in new_body:
            return False, "edit_block"
    for marker in _STRUCTURED_MARKERS:
        if marker in original_body and marker not in new_body:
            return False, "nav_block"
    if not _has_blocking(feedback) and _similarity(original_body, new_body) < SIMILARITY_FLOOR:
        return False, "similarity"
    return True, ""


def _grounding_violations(sample, text: str) -> int:
    """确定性反幻觉核对：回答里的步骤号 / 行号 / 堆对象 id 有多少条不存在（G3）。

    与评估侧 `verify_grounding` **同源**，不改它的任何语义。样本无 `steps` 时不可用 ⇒ 返回 0
    （无步骤可核对不是「有违规」）；核对器本身异常同样返回 0，让闸门 fail-open。
    """
    from graphs.javatutor.verification import verify_grounding

    try:
        return int(verify_grounding(sample, text or "")["violations"])
    except Exception:
        return 0


def revise_node(state, model=None) -> dict[str, Any]:
    answer = state.get("answer") or ""
    if state.get("critic_passed") or state.get("revised"):
        return {
            "revised_answer": answer,
            "revised": False,
            "revise_skipped": False,
            "revise_outcome": "skipped",
        }
    # CD-5 advisory：只观察不改写——评审结论照常写进痕迹，答案原样返回。
    # 认不出的取值（拼错 / 大小写不对）一律按 enforce，避免写错配置静默关掉修订闸。
    if _runtime_flag("critic_mode", "enforce") == "advisory":
        return {"revised_answer": answer, "revised": False, "revise_outcome": "skipped"}
    # 编辑建议块不参与「不要 JSON」的重写：拆出暂存，修订后原样拼回，确保前端始终收到。
    body, edit_block = _split_edit_block(answer)
    facts = _facts(state)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT_REVISE),
        HumanMessage(
            content=(
                f"原回答：\n{body}\n\n评审意见：\n{state.get('critic_feedback', '')}\n\n"
                f"事实依据：\n{facts}"
            )
        ),
    ]
    try:
        raw = _invoke(messages, model).content
    except Exception:
        return {
            "revised_answer": answer,
            "revised": False,
            "revise_skipped": True,
            "revise_outcome": "skipped",
        }
    if edit_block:
        raw = raw.rstrip() + "\n\n" + edit_block
    ok, reason = _accepted(body, raw, edit_block, state.get("critic_feedback", ""))
    recheck_ran = recheck_passed = False
    if ok:
        # G3：修订**不得让引用变差**（原答不违规、修订稿凭空多出「第 99 步」是典型形状）。
        if _grounding_violations(state, raw) > _grounding_violations(state, body):
            ok, reason = False, "grounding"
        # G4：前三道闸都过后再过一次评审。评审模型正是要拦的东西——一次误判换一次改写的
        # 通道已被 G1–G3 收窄，但 G1–G3 只管「是不是还是原来的回答」，管不了「改完还是错的」。
        elif _runtime_flag("critic_recheck", True):
            recheck_ran = True
            recheck_passed, _issues, _skipped = _critique(raw, facts, model)
            if not recheck_passed:
                ok, reason = False, "recheck"
    if not ok:
        # 回退原答：修订永不使答案在这些维度上变差，最坏等于「没改」。
        out = {
            "revised_answer": answer,
            "revised": False,
            "revise_skipped": False,
            "revise_outcome": "reverted",
            "revise_revert_reason": reason,
        }
    else:
        out = {
            "revised_answer": raw,
            "revised": True,
            "revise_skipped": False,
            "revise_outcome": "accepted",
        }
    if recheck_ran:
        # 没跑过的闸不该报告结果——「未跑」与「跑过但没过」必须分得开。
        out["revise_recheck_passed"] = recheck_passed
    return out
