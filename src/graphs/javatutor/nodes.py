"""JavaTutor Agent 节点实现.

包含: parse_context, route_intent, 专家节点, build_final
"""

import json
import logging
import os
import re
from typing import Literal, Any

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.language_models import BaseChatModel
from langgraph.types import Send

from coze_coding_utils.log.write_log import request_context
from coze_coding_utils.runtime_ctx.context import default_headers, new_context
from coze_coding_dev_sdk import LLMClient, Config, LLMConfig as SDKLLMConfig

from graphs.javatutor.state import JavaTutorState
from graphs.javatutor.prompts import (
    SYSTEM_PROMPT_DATA_QUERY,
    SYSTEM_PROMPT_CONCEPT,
    SYSTEM_PROMPT_DEBUG,
    ANIMATE_GUIDE_MESSAGE,
    SYSTEM_PROMPT_OTHER,
    SYSTEM_PROMPT_ANALYZE,
)

from learning.animation import build_animation_svg, classify_algorithm

# ── 模型配置 ──────────────────────────────────────────────────────────────────

LLM_CONFIG_PATH = "config/agent_llm_config.json"


def _get_chat_model() -> LLMClient:
    """热加载配置并创建 LLMClient 实例（单例）."""
    workspace_path = os.getenv("COZE_WORKSPACE_PATH", "/workspace/projects")
    config_path = os.path.join(workspace_path, LLM_CONFIG_PATH)

    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)

    api_key = os.getenv("COZE_WORKLOAD_IDENTITY_API_KEY")
    base_url = os.getenv("COZE_INTEGRATION_MODEL_BASE_URL")

    base_config = Config(
        api_key=api_key,
        base_url=base_url,
        timeout=cfg["config"].get("timeout", 600),
    )
    llm_config = SDKLLMConfig(
        model=cfg["config"].get("model", "doubao-seed-2-0-lite-260215"),
        temperature=cfg["config"].get("temperature", 0.7),
        top_p=cfg["config"].get("top_p", 0.9),
        max_completion_tokens=cfg["config"].get("max_completion_tokens", 10000),
        streaming=False,
    )
    ctx = request_context.get() or new_context(method="_get_chat_model")
    client = LLMClient(config=base_config, ctx=ctx)
    return client, llm_config


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
        "intent": intent,
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


# ── 2. 意图路由节点 ────────────────────────────────────────────────────────────


def _is_compile_error_debug(state: JavaTutorState) -> bool:
    """compile_error 非空 → debug 短路."""
    return bool(state.get("compile_error", "").strip())


def route_intent(state: JavaTutorState) -> dict:
    """意图路由节点: 判断用户意图，并短路 debug.

    路由规则:
    1. 显式 intent 字段（来自后端）→ 直接采用
    2. compile_error 非空 → debug
    3. 其余基于 user_question 关键词判断
    """
    # 规则 1: 显式 intent（后端直接指定，如 "analyze"）
    explicit_intent = state.get("intent", "").strip()
    if explicit_intent in ("data_query", "concept", "debug", "animate", "other", "analyze"):
        return {"intent": explicit_intent}

    # 规则 2: compile_error 短路
    if _is_compile_error_debug(state):
        return {"intent": "debug"}

    question = state.get("user_question", "").lower()

    # 规则 2: 关键词匹配
    # 数据追问: 变量值、执行过程、步骤
    data_query_keywords = ["为什么", "怎么", "如何", "arr", "变量", "值", "步骤", "结果", "输出"]
    # 概念讲解: 算法、原理、复杂度、定义
    concept_keywords = ["是什么", "算法", "复杂度", "概念", "原理", "定义", "时间", "空间", "o(", "大o"]

    if any(kw in question for kw in data_query_keywords):
        return {"intent": "data_query"}
    if any(kw in question for kw in concept_keywords):
        return {"intent": "concept"}

    # 动画关键词 → animate_guide 引导文案
    if any(kw in question for kw in ("动画", "演示", "可视化", "播放")):
        return {"intent": "animate_guide"}

    # 兜底: other
    return {"intent": "other"}


# ── 3. 专家节点 ────────────────────────────────────────────────────────────────


def _build_expert_messages(state: JavaTutorState, expert: str) -> list:
    """构建专家节点的消息列表: 系统提示词 + 上下文."""
    prompts = {
        "data_query": SYSTEM_PROMPT_DATA_QUERY,
        "concept": SYSTEM_PROMPT_CONCEPT,
        "debug": SYSTEM_PROMPT_DEBUG,
        "other": SYSTEM_PROMPT_OTHER,
    }
    system_prompt = prompts.get(expert, SYSTEM_PROMPT_OTHER)

    # 构建上下文
    compile_error = state.get("compile_error", "")
    context_parts = [
        f"### 用户问题\n{state.get('user_question', '')}",
        f"\n### 源代码\n```java\n{state.get('source_code', '')}\n```",
    ]
    if state.get("has_steps"):
        context_parts.append(
            f"\n### 当前步骤 (第 {state.get('current_step_index', 0) + 1} 步)\n"
            f"- 当前行号: {state.get('current_line', '')}\n"
            f"- 变量快照: {json.dumps(state.get('current_variables', {}), ensure_ascii=False, indent=2)}"
        )
    if compile_error:
        context_parts.append(f"\n### 编译错误\n{compile_error}")

    context = "\n".join(context_parts)

    return [SystemMessage(content=system_prompt), HumanMessage(content=context)]


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

    if model is not None:
        # 测试模式: 使用注入的 FakeModel
        response = model.invoke(messages)
        answer = response.content
    else:
        # 生产模式: 使用 LLMClient
        client, llm_config = _get_chat_model()
        response = client.invoke(
            messages=messages,
            model=llm_config.model,
            temperature=llm_config.temperature or 0.7,
            top_p=llm_config.top_p or 0.9,
            max_completion_tokens=llm_config.max_completion_tokens or 10000,
        )
        answer = response.content

    answer = _normalize_md(_deduplicate_answer(answer))
    labels = {"data_query": "数据追问", "concept": "概念讲解", "debug": "错误诊断", "other": "通用助手"}
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
            # 生产模式: 使用 LLMClient
            client, llm_config = _get_chat_model()
            ctx = request_context.get() or new_context(method="analyze_node")
            client = LLMClient(config=client.config, ctx=ctx)

            response = client.invoke(
                messages=_build_analyze_messages(source_code, steps_json),
                model=llm_config.model,
                temperature=llm_config.temperature,
                top_p=llm_config.top_p,
                max_completion_tokens=llm_config.max_completion_tokens,
            )
            raw = response.content if hasattr(response, "content") else str(response)

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


def animate_node(state: JavaTutorState) -> dict:
    """animate 专家: 基于 steps 生成纯 SVG 动画消息."""
    steps = state.get("steps") or []
    if not steps:
        return {"messages": [AIMessage(content="请先运行代码，再点击「生成动画」按钮。")], "svg_text": ""}
    algorithm_tag = classify_algorithm(state.get("source_code", ""))
    svg_text = build_animation_svg(steps, algorithm_tag)
    return {"messages": [AIMessage(content=svg_text)], "svg_text": svg_text}


def animate_guide_node(state: JavaTutorState) -> dict:
    """聊天中请求动画时的固定引导，不调用 LLM."""
    return {"messages": [AIMessage(content=ANIMATE_GUIDE_MESSAGE)]}