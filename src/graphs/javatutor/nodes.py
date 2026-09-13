"""JavaTutor Agent 节点实现.

包含: parse_context, 专家节点（兼容层）, retrieve_knowledge, build_context, load/save_session, build_final
"""

import json
import logging
import re
import time
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
from graphs.javatutor.verification import verify_grounding

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
    #   只拆「围栏 + 同行内容」的情况；围栏后已是换行（含 ```jav 截断）保持原样，
    #   避免把 ```jav 拆成 ```ja + v 导致单字符残留
    def _fix_fence_line(match):
        fence = match.group(1)
        rest = match.group(2).strip()
        if not rest:
            return match.group(0)
        return fence + "\n" + rest

    text = re.sub(r'^(```\w*)(.*)$', _fix_fence_line, text, flags=re.MULTILINE)

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
    from tools.fetch_execution_context import normalize_files

    source_code = data.get("source_code", "")
    steps = data.get("steps", [])
    current_step_index = data.get("current_step_index", 0)
    current_line = data.get("current_line", 1)
    user_question = data.get("user_question", "")
    run_id = data.get("run_id", "")
    session_id = data.get("session_id", data.get("user_id", ""))
    compile_error = data.get("compile_error", "")
    intent = data.get("intent", "")
    algorithm_tags = data.get("algorithm_tags") or []
    files = normalize_files(data.get("files"))
    entry_file = str(data.get("entry_file") or "")
    # 运行模式事实（前端报、后端透传）。缺失为空串 = 模式未知，不得当成 default（见 state.py）。
    run_mode = str(data.get("run_mode") or "")
    try:
        test_case_count = int(data.get("test_case_count") or 0)
    except (TypeError, ValueError):
        test_case_count = 0

    # 提取当前步骤的变量快照 + 当前步所在文件
    current_variables = {}
    current_step_file = ""
    if steps and isinstance(steps, list) and 0 <= current_step_index < len(steps):
        current_variables = steps[current_step_index].get("variables", {})
        current_step_file = steps[current_step_index].get("file", "") or ""

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
        "user_id": session_id,
        "run_id": run_id,
        "compile_error": compile_error,
        "has_error": bool(compile_error and compile_error.strip()),
        "intent": (
            intent
            if intent in ("data_query", "concept", "debug", "analyze", "other")
            else conservative_intent(user_question, compile_error)
        ),
        "algorithm_tags": algorithm_tags,
        "files": files,
        "entry_file": entry_file,
        "run_mode": run_mode,
        "test_case_count": test_case_count,
        "current_step_file": current_step_file,
        "fallback_reason": "",
        "request_started_at": time.time(),
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
    """RAG 检索节点：查询知识库，失败时降级放行。

    成功分支同时写两个字段：

    - ``retrieved_chunks``：越阈值的结果（**语义与消费方一律不变**）；
    - ``retrieval_debug``：全量候选与阈值判定（诊断用，含被滤掉的候选）。

    只做**一次**检索（`search_chunks_debug`），越阈值结果由 ``candidates`` 派生——
    复用同一份 ``_raw_rows``，两条路径的召回阶段完全一致（见 ``tests/test_knowledge.py``
    的等价性守卫）。省下的是一次 embedding 往返。

    ``rag_degraded`` 只表示**后端失败**。检索成功但 0 条越阈值时仍为 ``False``——
    那是「检索成功但无匹配」，与「检索故障」是两回事，混同会让诊断信号失真。
    """
    from learning.knowledge import search_chunks_debug

    try:
        query = f"{state.get('user_question', '')} {state.get('context_summary', '')}".strip()
        debug = search_chunks_debug(query)
        chunks = [
            {
                "source": c["source"],
                "chunk_index": c["chunk_index"],
                "content": c["content"],
                "score": c["score"],
            }
            for c in debug["candidates"]
            if c["kept"]
        ]
        return {"retrieved_chunks": chunks, "retrieval_debug": debug, "rag_degraded": False}
    except Exception:
        return {
            "retrieved_chunks": [],
            "retrieval_debug": {"candidates": []},
            "rag_degraded": True,
        }


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

    注意：【视角导航】块（{"views":[...]}）是受控输出指令，不以 intent/pass/tool 开头，
    不会被本函数剥离，前后端依赖其原样透传。见 docs/spec/2026-09-07-coze-agent-view-navigation.md。
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


def _redact_denied_tools(trace_json: str, denied: set[str]) -> str:
    """兜底出口：从 trace JSON 里剔除被拒工具名（红线在 ``build_final`` 的最后一道）。

    ``build_reasoning`` 已逐条剥离提案原文，但那是「每条路径都记得剥离」式的防御——
    将来若新增分支（或模型换一种畸形输出），后门会重新打开。这里在**拼进 answer 之前**
    对 trace JSON 段做一次终局剔除：``denied`` 由调用方从 ``step_records`` 的
    ``status != "ok"`` 派生（被拒工具的权威记录），替换为占位串。

    只作用于 trace JSON 段（终答正文由 ``_strip_leaked_json`` 管），所以正文里作为普通词
    出现的同名 token 不受影响。
    """
    for name in denied:
        if name:
            trace_json = trace_json.replace(f'"{name}"', '"[已拒绝]"')
    return trace_json


def _sanitize_code_quotes(text: str) -> str:
    """清理模型引用代码行时的常见残留。

    实测模型会输出 ```jav（java 截断）以及代码块内多余的单字符行（如 a），
    这里做确定性兜底：归一 java 语言标签，删除代码块开头的单字符残留行。
    """
    import re as _re

    text = _re.sub(r'```j(?:av[a-z]*)?\b', '```java', text, flags=_re.IGNORECASE)

    lines = text.split('\n')
    out = []
    in_code = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code = not in_code
            out.append(line)
            continue
        if in_code and len(out) > 0 and out[-1].strip().startswith('```'):
            if _re.fullmatch(r'[A-Za-z0-9_]\s*', line):
                continue
        out.append(line)
    return '\n'.join(out)


_STRUCTURED_MARKERS = ("【决策痕迹】", "【编辑建议】", "【视角导航】")


def _strip_structured_blocks(text: str) -> str:
    """剥掉结构化块（决策痕迹 / 编辑建议 / 视角导航），只留回答正文。

    这些块的 JSON 里含代码片段与行号样数字（如堆对象 `h1`、代码里的数字），
    不剥会给 grounding 核对器造出假阳性。三个块都紧贴回答末尾，取最早出现的标记截断即可。

    取舍：若**正文本身**提到「【编辑建议】」这四个字（例如在解释这个功能），
    其后正文会一并被切出核对范围。方向是保守的（少核对，而不是误判为幻觉），
    代价可接受；要收紧就得先解析出块的起止边界，不值得。
    """
    if not text:
        return ""
    cut = len(text)
    for marker in _STRUCTURED_MARKERS:
        pos = text.find(marker)
        if pos != -1:
            cut = min(cut, pos)
    return text[:cut].rstrip()


def verify_node(state: JavaTutorState) -> dict:
    """确定性 grounding 核对（原则⑤）：核对最终交付文本的引用真实性。

    **只记录、不参与路由**（D4）：拒绝结束会在真实教学场景把可用回答变成不可用。
    它与 LLM 评审互补——`critic_skipped=True` 时，这是唯一还站着的客观证据。
    """
    body = _strip_structured_blocks(state.get("revised_answer") or state.get("answer") or "")
    result = verify_grounding(
        {
            "payload": {
                "steps": state.get("steps") or [],
                "source_code": state.get("source_code") or "",
            }
        },
        body,
    )
    return {"verification": result}


def build_reasoning(
    messages: list, max_chars: int = 1200, executed_tools: set | None = None
) -> tuple[list[dict], bool]:
    """从 ``agent_messages`` 提取 AI 中间思考（按序），返回 ``(reasoning, truncated)``。

    ``agent_messages`` 本就是完整 ReAct 轨迹（``propose`` 每轮追加模型原始输出，
    ``run_tools`` 追加一条合并观察），所以这里只需按序 filter 出 ``AIMessage``。

    - ``round`` 用 AI 消息的出现序号（0-based）；
    - ``tool_calls`` 复用 ``harness.contracts.parse_action`` 解析该轮输出里的工具名，
      但**只保留 ``executed_tools`` 里的名字**——被拒（P1 未知工具 / P2 参数非法）的提案
      **不得出现在痕迹里**：``tool_calls`` 不含被拒工具、回答里也不得出现其名字，
      这是设计红线（spec §4.7 与 ``tests/test_harness_loop.py`` /
      ``tests/test_harness_termination.py`` 锁死）。解析不出或未执行一律归 ``[]``；
    - 每条 ``content`` 按 ``max_chars`` 截断，任一条超长即置 ``truncated=True``
      （**显式截断**，不做静默裁剪）。

    被解析为**提案**的那一轮（``Action`` 或 ``ParseError`` 皆然），``content`` 剥掉工具
    JSON 负载——工具名已由结构化 ``tool_calls`` 承载，原始 JSON 不进用户可见痕迹。
    ``ParseError``（``args`` 不是对象等）同样是提案且携带 ``tool``，若只堵 ``Action`` 分支，
    其原文会随 ``content`` 拼进 answer，等于从 ``content`` 侧开后门泄露被拒工具名。
    散文轮次（``parse_action`` 返回 ``None``）原样保留。

    只吃 ``messages``（``executed_tools`` 由调用方从 ``step_records`` 派生），不读 state，可脱离图单测。
    """
    from langchain_core.messages import AIMessage

    from graphs.javatutor.harness.contracts import Action, ParseError, parse_action

    allowed = executed_tools or set()
    reasoning: list[dict] = []
    truncated = False
    for msg in messages or []:
        if not isinstance(msg, AIMessage):
            continue
        raw = msg.content if isinstance(msg.content, str) else str(msg.content)
        parsed = parse_action(raw)
        if isinstance(parsed, Action):
            content = _strip_tool_json(raw)
            tool_calls = [parsed.tool] if parsed.tool in allowed else []
        elif isinstance(parsed, ParseError):
            content = _strip_tool_json(raw)
            tool_calls = []
        else:
            content = raw
            tool_calls = []
        if len(content) > max_chars:
            content = content[:max_chars]
            truncated = True
        reasoning.append({"round": len(reasoning), "content": content, "tool_calls": tool_calls})
    return reasoning, truncated


def _strip_tool_json(text: str) -> str:
    """从一条模型输出里剥掉工具提案 JSON，只留周边散文。

    提案通常整条就是 JSON（``{"tool":...,"args":...}``），剥离后多为空串——这是**有意**的：
    工具名已由结构化 ``tool_calls`` 承载，原始 JSON 不进用户可见的痕迹（见 ``build_reasoning``）。
    """
    try:
        data = json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return text
    if isinstance(data, dict) and data.get("tool"):
        return ""
    return text


_PREVIEW_CHARS = 300


def _build_retrieval(debug: dict | None) -> dict:
    """把 state 的 ``retrieval_debug`` 转成 trace 的 ``retrieval``（含预览截断）。

    检索层不做表现层决策：原始候选带的是完整 ``content``，截断与 ``truncated``
    标志在这里加。缺 ``retrieval_debug`` 时返回恒存在的空壳，便于消费方无条件读。
    """
    if not debug:
        return {"candidates": [], "best_score": 0.0, "kept": 0}
    candidates = []
    for c in debug.get("candidates") or []:
        content = str(c.get("content", ""))
        candidates.append(
            {
                "source": c.get("source", ""),
                "chunk_index": c.get("chunk_index", 0),
                "score": c.get("score", 0.0),
                "preview": content[:_PREVIEW_CHARS],
                "truncated": len(content) > _PREVIEW_CHARS,
                "kept": bool(c.get("kept", False)),
            }
        )
    return {
        "query": debug.get("query", ""),
        "top_k": debug.get("top_k", 0),
        "threshold": debug.get("threshold", 0.0),
        "candidates": candidates,
        "best_score": debug.get("best_score", 0.0),
        "kept": debug.get("kept", 0),
    }


def build_final(state: JavaTutorState) -> dict:
    """最终输出节点：拼接回答 + 决策痕迹。

    返回 {"messages": [AIMessage(content=...)]} 作为唯一流式输出，
    确保客户端只看到最终回答（含决策痕迹），不泄露中间 LLM 调用内容。
    """
    answer = state.get("revised_answer") or state.get("answer") or "抱歉，我暂时无法回答这个问题。"
    answer = _normalize_md(answer)
    answer = _sanitize_code_quotes(answer)
    answer = _strip_leaked_json(answer)

    run_id = state.get("run_id", "")
    # fetch_execution_context 已作为主 Agent 工具循环的 LLM 工具调用真实产生，无需在此补记。
    tool_calls = state.get("tool_calls") or []
    # 只有**真的执行了**的工具名才允许进 reasoning.tool_calls（被拒提案不得泄露，见函数 docstring）
    executed_tools = {
        r.get("tool")
        for r in (state.get("step_records") or [])
        if r.get("status") == "ok" and r.get("tool")
    }
    reasoning, reasoning_truncated = build_reasoning(
        state.get("agent_messages") or [], executed_tools=executed_tools
    )

    trace = {
        "run_id": run_id,
        "fetch_context_failed": state.get("fetch_context_failed", False),
        "fetch_context_latency_ms": state.get("fetch_context_latency_ms", 0.0),
        "fetch_context_error": state.get("fetch_context_error", ""),
        "intent": state.get("intent", "other"),
        "latency_ms": round((time.time() - float(state.get("request_started_at", time.time()))) * 1000, 1),
        "confidence": round(float(state.get("intent_confidence", 0.0)), 2),
        # sources 只增键（retrieval_metrics.py 依赖 source / score 的既有语义）
        "sources": [
            {
                "source": c["source"],
                "score": c.get("score", 0.0),
                "chunk_index": c.get("chunk_index", 0),
                "content_preview": str(c.get("content", ""))[:_PREVIEW_CHARS],
            }
            for c in (state.get("retrieved_chunks") or [])
        ],
        "retrieval": _build_retrieval(state.get("retrieval_debug")),
        "reasoning": reasoning,
        "reasoning_truncated": reasoning_truncated,
        "critic_passed": state.get("critic_passed", True),
        "revised": state.get("revised", False),
        "fallback_reason": state.get("fallback_reason", ""),
        "rag_degraded": state.get("rag_degraded", False),
        "critic_skipped": state.get("critic_skipped", False),
        "revise_skipped": state.get("revise_skipped", False),
        "compaction_mode": state.get("compaction_mode", "none"),
        "tool_calls": tool_calls,
        "token_usage": _estimate_token_usage(state),
        "verification": state.get("verification") or {},
    }
    trace_json = json.dumps(trace, ensure_ascii=False, separators=(",", ":"))
    # 终局红线兜底：被拒工具名（step_records 里 status != "ok" 的权威记录）不得出现在
    # 拼进 answer 的 trace 段里。逐条剥离之外再设一道，防未来新分支重开后门。
    denied_tools = {
        r.get("tool")
        for r in (state.get("step_records") or [])
        if r.get("status") != "ok" and r.get("tool")
    }
    trace_json = _redact_denied_tools(trace_json, denied_tools)
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

        return {"memories": get_memory_store().search(session_id, limit=10)}
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
