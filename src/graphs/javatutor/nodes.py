"""JavaTutor Agent 节点实现.

包含: parse_context, route_intent, 专家节点, build_final
"""

import json
import os
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
    SYSTEM_PROMPT_ANIMATE,
    SYSTEM_PROMPT_OTHER,
)

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
    1. compile_error 非空 → debug
    2. 其余基于 user_question 关键词判断
    """
    # 规则 1: compile_error 短路
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

    return {"answer": answer}


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


def animate_node(state: JavaTutorState) -> dict:
    """animate 专家: Phase 1 占位，后续接入 SVG 生成器."""
    return {"answer": SYSTEM_PROMPT_ANIMATE}


# === 4. final 节点 ===


def build_final(state: JavaTutorState) -> dict:
    """最终节点: 仅返回新 AIMessage，add_messages 自动合并到历史消息."""
    answer = state.get("answer", "抱歉，我无法回答这个问题。")
    return {
        "messages": [
            AIMessage(
                content=answer,
                additional_kwargs={
                    "intent": state.get("intent", "other"),
                },
            )
        ],
    }