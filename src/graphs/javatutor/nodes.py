"""JavaTutor Agent 节点实现.

包含: parse_context, 专家节点（兼容层）, retrieve_knowledge, build_context, load/save_session, build_final
"""

import json
import logging
import re
from typing import Literal, Any

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.language_models import BaseChatModel
from langgraph.types import Send

from graphs.javatutor.llm import llm_complete as _llm_complete

from graphs.javatutor.state import JavaTutorState
from graphs.javatutor.prompts import (
    SYSTEM_PROMPT_ANALYZE,
    build_system_prompt,
)
from graphs.javatutor.intent_rules import conservative_intent
from graphs.javatutor.prompting.contexts import (
    build_concept_context,
    build_data_query_context,
    build_debug_context,
    build_other_context,
)
from graphs.javatutor.prompting.fewshots import get_few_shots

# ── 去重后处理 & Markdown 规整 ──────────────────────────────────────────────────


def _deduplicate_answer(text: str) -> str:
    """检测文本后半段是否与前半段重复，是则截断到前半段。"""
    if len(text) < 60:
        return text
    mid = len(text) // 2
    first_half = text[:mid]
    second_half = text[mid:]
    # 取后半段开头 30 字符（去空格后），看是否出现在前半段结尾附近
    probe = second_half[:30].strip()
    if not probe:
        return text
    # 在前半段最后 200 字符中搜索 probe
    tail = first_half[-200:]
    if probe in tail:
        # 找到 probe 在 tail 中的位置，截断到 probe 开始处
        idx = tail.find(probe)
        return text[:mid - 200 + idx].rstrip()
    return text


def _normalize_md(text: str) -> str:
    """强制规整 Markdown 格式，确保标题/分隔线/代码块/列表能被正确渲染。

    处理规则（不依赖模型自觉）：
    1. 「###」后无空格 → 补空格
    2. 代码块围栏后紧跟代码 → 围栏后插换行
    3. 「---」与文字粘连 → 前后插换行
    """
    # 1. 标题标记后无空格 → 补空格
    #   匹配行首或换行后的 #、##、### 等，后跟非空格非#非换行字符
    text = re.sub(r'(^|\n)(#{1,6})(?=[^\s#\n])', r'\1\2 ', text)

    # 2. 代码块围栏后紧跟非换行内容 → 围栏后插换行
    #   匹配 ``` 或 ```java 等围栏，后跟非换行字符
    text = re.sub(r'(```\w*)([^\n])', r'\1\n\2', text)

    # 3. 分隔线 --- 与文字粘连 → 前后插换行
    #   行内 --- 两侧有非换行字符 → 在 --- 前后插换行
    text = re.sub(r'([^\n])(---)([^\n])', r'\1\n\2\n\3', text)

    return text


# ── 1. 解析节点 ────────────────────────────────────────────────────────────────


def _parse_json_str(content: str | list) -> dict:
    """解析 JSON 字符串内容.

    支持 content 为 str 或 list（Coze 平台可能将消息包装为 list）.
    """
    # 处理 list 类型 content（如 Coze 平台包装的 [{"type": "text", "text": "..."}]）
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        content = "\n".join(texts)

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"无法解析 JSON: {e}") from e

    return _parse_json_dict(data)


def _parse_json_dict(data: dict) -> dict:
    """从已解析的 dict 中提取字段，返回状态更新."""
    source_code = data.get("source_code", "")
    steps = data.get("steps", [])
    current_step_index = data.get("current_step_index", 0)
    current_line = data.get("current_line", 1)
    user_question = data.get("user_question", "")
    user_id = data.get("user_id", "")
    compile_error = data.get("compile_error", "")
    intent = data.get("intent", "")
    algorithm_tags = data.get("algorithm_tags") or []

    # 提取当前步骤的变量快照
    current_variables = {}
    if steps and isinstance(steps, list) and 0 <= current_step_index < len(steps):
        current_variables = steps[current_step_index].get("variables", {})

    return {
        "source_code": source_code,
        "steps": steps,
        "steps_json": json.dumps(steps, ensure_ascii=False),
        "steps_count": len(steps),
        "has_steps": len(steps) > 0,
        "current_step_index": current_step_index,
        "current_line": current_line,
        "current_variables": current_variables,
        "user_question": user_question,
        "user_id": user_id,
        "compile_error": compile_error,
        "has_error": bool(compile_error and compile_error.strip()),
        "intent": (
            intent
            if intent in ("data_query", "concept", "debug", "analyze", "other")
            else conservative_intent(user_question, compile_error)
        ),
        "algorithm_tags": algorithm_tags,
    }


def parse_context(state: JavaTutorState) -> dict:
    """解析上下文节点: 从消息中提取后端 JSON 数据."""
    if isinstance(state, str):
        content = state
    elif isinstance(state, dict) and "messages" not in state:
        return _parse_json_dict(state)
    else:
        messages: list = state.get("messages", [])
        last_msg = messages[-1]
        content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    return _parse_json_str(content)


# ── 2. 专家节点（兼容层，新图链路已不再路由到专家节点） ─────────────────────────


def _build_expert_messages(state: JavaTutorState, expert: str) -> list:
    """构建专家消息: system = 角色+词汇+契约; human = 上下文+示例."""
    context_builders = {
        "data_query": build_data_query_context,
        "concept": build_concept_context,
        "debug": build_debug_context,
        "other": build_other_context,
    }
    system_prompt = build_system_prompt(expert)
    context = context_builders.get(expert, build_other_context)(state)
    examples = get_few_shots(expert)
    human = context
    if examples:
        human += "\n\n## 示例\n" + "\n\n".join(examples)
    return [SystemMessage(content=system_prompt), HumanMessage(content=human)]


def _run_expert(
    state: JavaTutorState, expert: str, model: "BaseChatModel | None" = None
) -> dict:
    """调用 LLM 执行专家回答.

    Args:
        state: 当前状态
        expert: 专家名称
        model: 可选的 ChatOpenAI 实例（测试时注入 FakeModel）
    """
    messages = _build_expert_messages(state, expert)
    labels = {"data_query": "数据追问", "concept": "概念讲解", "debug": "错误诊断", "other": "通用助手"}

    try:
        resolved = _resolve_model(model)
        if resolved is not None:
            response = resolved.invoke(messages)
            answer = response.content
        else:
            answer = _llm_complete(
                messages=messages,
                temperature=0.7,
                max_completion_tokens=10000,
            )
    except Exception as exc:
        logger = logging.getLogger(__name__)
        logger.warning("Expert LLM call failed (%s), using fallback", exc)
        answer = "抱歉，回答生成服务暂时不可用，请稍后重试。"

    answer = _normalize_md(_deduplicate_answer(answer))
    return {"answer": f"【{labels.get(expert, '通用助手')}】{answer}"}


def data_query_node(state: JavaTutorState, model: "BaseChatModel | None" = None) -> dict:
    """data_query 专家: 分析执行数据，解释变量变化."""
    return _run_expert(state, "data_query", model=model)


def concept_node(state: JavaTutorState, model: "BaseChatModel | None" = None) -> dict:
    """concept 专家: 讲解算法概念与原理."""
    return _run_expert(state, "concept", model=model)


def debug_node(state: JavaTutorState, model: "BaseChatModel | None" = None) -> dict:
    """debug 专家: 分析编译错误，给出修复方案."""
    return _run_expert(state, "debug", model=model)


def other_node(state: JavaTutorState, model: "BaseChatModel | None" = None) -> dict:
    """other 专家: 通用兜底."""
    return _run_expert(state, "other", model=model)


def _build_analyze_messages(source_code: str, steps_json: str) -> list:
    """构建分析专家的消息列表（固定模板，不依赖 user_question）。"""
    from langchain_core.messages import SystemMessage, HumanMessage
    return [
        SystemMessage(content=SYSTEM_PROMPT_ANALYZE),
        HumanMessage(content=f"源代码:\n```java\n{source_code}\n```\n\n步骤快照:\n{steps_json}"),
    ]


def analyze_node(state: JavaTutorState, model: "BaseChatModel | None" = None) -> dict:
    """analyze 专家: 分析代码复杂度 + 算法/数据结构标签，返回结构化 JSON.

    由前端自动触发（intent='analyze'），不依赖 user_question。
    使用固定模板 + 低温度确保 JSON 输出稳定。
    """
    try:
        source_code = state.get("source_code", "")
        steps_json = state.get("steps_json", "[]")
        logger = logging.getLogger(__name__)

        if model is not None:
            # 测试模式: 使用注入的 FakeModel
            response = model.invoke(_build_analyze_messages(source_code, steps_json))
            raw = response.content if hasattr(response, "content") else str(response)
        else:
            # 生产模式: 使用原始 HTTP 调用（绕过 stream_mode=messages）
            raw = _llm_complete(
                messages=_build_analyze_messages(source_code, steps_json),
                temperature=0.1,
                max_completion_tokens=10000,
            )
        if not isinstance(raw, str):
            raw = str(raw)

        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        # 验证是否为合法 JSON
        json.loads(raw)
        return {"messages": [AIMessage(content=_deduplicate_answer(raw))]}
    except Exception as exc:
        logger.warning("analyze_node JSON parse failed, using fallback: %s", exc)
        return {"messages": [AIMessage(content=json.dumps({
            "complexity": {"time": "未知", "timeExplanation": "分析失败", "space": "未知", "spaceExplanation": "分析失败"},
            "algorithms": [],
            "dataStructures": [],
        }, ensure_ascii=False))]}


# ── 4. 深化链路节点 ────────────────────────────────────────────────────────────


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


def context_compaction(state: JavaTutorState) -> dict:
    """上下文压缩节点：steps 过长时窗口截取 + 摘要。"""
    from graphs.javatutor.compaction import compact_steps

    return compact_steps(state.get("steps") or [], state.get("current_step_index", 0))


def retrieve_knowledge(state: JavaTutorState) -> dict:
    """RAG 检索节点：查询知识库，失败时降级放行。"""
    from learning.knowledge import search_chunks

    try:
        query = f"{state.get('user_question', '')} {state.get('context_summary', '')}".strip()
        chunks = search_chunks(query)
        return {"retrieved_chunks": chunks, "rag_degraded": False}
    except Exception:
        return {"retrieved_chunks": [], "rag_degraded": True}


def _estimate_token_usage(state: JavaTutorState) -> dict:
    """估算本次回答的 token 消耗（estimated=true，用于评测成本）。"""
    try:
        from graphs.javatutor.context_builder import estimate_tokens

        answer = state.get("revised_answer") or state.get("answer") or ""
        prompt_src = f"{state.get('user_question', '')}\n{state.get('context_built', '')}"
        return {
            "prompt_tokens": estimate_tokens(prompt_src),
            "completion_tokens": estimate_tokens(answer),
            "estimated": True,
        }
    except Exception:
        return {"prompt_tokens": 0, "completion_tokens": 0, "estimated": True}


def _strip_leaked_json(text: str) -> str:
    """移除回答正文中泄露的意图/评审 JSON 片段。

    目标模式：
    - 开头的 {"intent":...,"confidence":...}
    - 任意位置的 {"pass":...,"issues":[...]}
    这些来自中间 LLM 调用，不应出现在最终回答中。
    """
    import re as _re

    # 1. 移除开头的意图 JSON（可能被 markdown 代码块包裹）
    text = _re.sub(
        r'^\s*(?:```(?:json)?\s*)?\{\s*"intent"\s*:.*?\}\s*(?:```\s*)?',
        '',
        text,
        flags=_re.DOTALL,
    ).lstrip()

    # 2. 移除任意位置的评审 JSON
    text = _re.sub(
        r'(?:```(?:json)?\s*)?\{\s*"pass"\s*:.*?\}\s*(?:```\s*)?',
        '',
        text,
        flags=_re.DOTALL,
    )

    # 3. 清理多余空行
    text = _re.sub(r'\n{3,}', '\n\n', text).strip()
    # 4. 移除结尾的工具调用 JSON（模型未执行工具时可能直接输出）
    text = _re.sub(r'\n*\s*\{\s*"tool"\s*:.*?\}\s*$', '', text, flags=_re.DOTALL)
    return text


def build_final(state: JavaTutorState) -> dict:
    """最终输出节点：拼接回答 + 决策痕迹。

    返回 {"messages": [AIMessage(content=...)]} 作为唯一流式输出，
    确保客户端只看到最终回答（含决策痕迹），不泄露中间 LLM 调用内容。
    """
    answer = state.get("revised_answer") or state.get("answer") or "抱歉，我暂时无法回答这个问题。"
    answer = _normalize_md(answer)
    answer = _strip_leaked_json(answer)

    trace = {
        "intent": state.get("intent", "other"),
        "confidence": round(float(state.get("intent_confidence", 0.0)), 2),
        "sources": [
            {"source": c["source"], "score": c.get("score", 0.0)}
            for c in (state.get("retrieved_chunks") or [])
        ],
        "critic_passed": state.get("critic_passed", True),
        "revised": state.get("revised", False),
        "fallback_reason": state.get("fallback_reason", ""),
        "rag_degraded": state.get("rag_degraded", False),
        "critic_skipped": state.get("critic_skipped", False),
        "revise_skipped": state.get("revise_skipped", False),
        "compaction_mode": state.get("compaction_mode", "none"),
        "tool_calls": state.get("tool_calls") or [],
        "token_usage": _estimate_token_usage(state),
    }
    trace_json = json.dumps(trace, ensure_ascii=False, separators=(",", ":"))
    content = f"{answer}\n\n【决策痕迹】\n{trace_json}"
    return {"messages": [AIMessage(content=content)], "answer": content, "decision_trace": trace}


# ── 5. 上下文构建节点 ───────────────────────────────────────────────────────────


def build_context_node(state: JavaTutorState) -> dict:
    from graphs.javatutor.context_builder import build_context
    from graphs.javatutor.prompts import build_system_prompt

    # 对话历史：取当前请求之前的最近 5 条消息（当前请求已被解析进 state 字段，排除避免重复）
    history = []
    messages = state.get("messages") or []
    for msg in messages[:-1][-5:]:
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            parts = [
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            content = "\n".join(parts)
        history.append({"role": getattr(msg, "type", "user"), "content": str(content)[:200]})

    text = build_context(
        state,
        history=history,
        memories=state.get("memories") or [],
        system_instructions=build_system_prompt("other"),
    )
    return {"context_built": text}


# ── 6. 会话工作记忆节点 ─────────────────────────────────────────────────────────


def load_session(state: JavaTutorState) -> dict:
    session_id = state.get("user_id", "")
    if not session_id:
        return {"memories": []}
    try:
        from learning.memory import get_memory_store

        return {"memories": get_memory_store().search(session_id, limit=5)}
    except Exception:
        return {"memories": []}


def save_session(state: JavaTutorState) -> dict:
    session_id = state.get("user_id", "")
    answer = state.get("revised_answer") or state.get("answer") or ""
    if not session_id or not answer:
        return {}
    try:
        from learning.memory import get_memory_store

        store = get_memory_store()
        store.add(session_id, f"问答：{state.get('user_question', '')} → {answer[:200]}", importance=0.5)
        analysis = state.get("analysis_result")
        if analysis:
            import json

            store.add(session_id, "上次分析：" + json.dumps(analysis, ensure_ascii=False)[:500], importance=0.85)
        for memory in (state.get("step_memories") or [])[-5:]:
            store.add(
                session_id,
                f"步骤查询：第 {memory.get('step_index')} 步 -> {memory.get('content', '')[:400]}",
                importance=float(memory.get("importance", 0.8)),
            )
    except Exception:
        pass
    return {}
