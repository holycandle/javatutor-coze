"""JavaTutor 图工作流节点.

包含: parse_context / route_intent / 4个专家 / animate(占位) / final.
"""

import json
import os
import re
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from coze_coding_dev_sdk import Config, LLMClient
from coze_coding_utils.log.write_log import request_context
from coze_coding_utils.runtime_ctx.context import default_headers, new_context

from .prompts import (
    SYSTEM_PROMPT_CONCEPT,
    SYSTEM_PROMPT_DATA_QUERY,
    SYSTEM_PROMPT_DEBUG,
    SYSTEM_PROMPT_OTHER,
)
from .state import JavaTutorState

if TYPE_CHECKING:
    from langchain_core.language_models.chat_base import BaseChatModel

LLM_CONFIG = "config/agent_llm_config.json"

# === 1. parse_context 节点 ===

ANIMATE_PLACEHOLDER = "动画功能正在开发中，敬请期待。"


def parse_context(state: JavaTutorState) -> dict:
    """解析 JSON 消息，提取关键字段到 state.

    支持两种调用方式:
    - LangGraph 节点调用: state 包含 messages，读取最后一条消息的 JSON
    - 测试直接调用: state 为 dict 或 str，直接解析 JSON
    """
    # 方式1: 直接传入 JSON 字符串
    if isinstance(state, str):
        content = state
        # 测试直接调用时 messages 为空列表
        messages = []
    # 方式2: 直接传入 dict
    elif isinstance(state, dict) and "messages" not in state:
        return _parse_json_dict(state)
    # 方式3: LangGraph 节点，读取 messages[-1].content
    else:
        messages: list = state.get("messages", [])
        if not messages:
            raise ValueError("messages 为空，无法解析上下文")
        last_msg = messages[-1]
        content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    return _parse_json_str(content)


def _parse_json_dict(data: dict) -> dict:
    """解析已解析为 dict 的 JSON 数据."""
    steps: list = data.get("steps", [])
    steps_count = len(steps)
    current_step_index = data.get("current_step_index", -1)
    current_variables: dict = {}
    current_line = 0
    if steps and 0 <= current_step_index < steps_count:
        current_step = steps[current_step_index]
        current_variables = current_step.get("variables", {})
        current_line = current_step.get("line", 0)

    compile_error = data.get("compile_error", "")
    has_error = bool(compile_error and compile_error.strip())

    return {
        "source_code": data.get("source_code", ""),
        "steps": steps,
        "steps_json": json.dumps(steps, ensure_ascii=False),
        "steps_count": steps_count,
        "has_steps": steps_count > 0,
        "current_step_index": current_step_index,
        "current_line": current_line,
        "current_variables": current_variables,
        "user_question": data.get("user_question", ""),
        "user_id": data.get("user_id", ""),
        "compile_error": compile_error,
        "has_error": has_error,
    }


def _parse_json_str(content: str | list) -> dict:
    """解析 JSON 字符串内容.
    
    支持 content 为 str 或 list（Coze 平台可能将消息包装为 list）。
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


# === 2. route_intent 节点 ===

DATA_QUERY_PATTERNS = [
    r"为什么",
    r"怎么变",
    r"此时",
    r"第[一二两三四五六七八九十百千万\\d]+步",
    r"变量",
    r"值是",
    r"变成",
    r"交换",
]

CONCEPT_PATTERNS = [
    r"是什么",
    r"原理",
    r"时间复杂度",
    r"空间复杂度",
    r"为什么.*排序",
    r"算法",
    r"思路",
    r"怎么实现",
    r"如何实现",
]

DEBUG_PATTERNS = [
    r"报错",
    r"错误",
    r"异常",
    r"编译不过",
    r"怎么改",
    r"如何修复",
    r"不对",
    r"有问题",
    r"cannot find symbol",
    r"exception",
]

ANIMATE_PATTERNS = [
    r"动画",
    r"可视化",
    r"演示",
    r"动态展示",
]


def route_intent(state: JavaTutorState) -> dict:
    """意图路由节点.

    优先判断 has_error（短路 debug），
    否则通过关键词匹配推断用户意图。
    """
    user_question: str = state.get("user_question", "")
    has_error: bool = state.get("has_error", False)
    has_steps: bool = state.get("has_steps", False)

    q = user_question

    # 短路: 有编译错误 → debug
    if has_error:
        return {"intent": "debug"}

    # 调试类关键词 → debug
    if _matches_any(q, DEBUG_PATTERNS):
        return {"intent": "debug"}

    # 动画类关键词 → animate
    if _matches_any(q, ANIMATE_PATTERNS):
        return {"intent": "animate"}

    # 数据查询类关键词 → data_query
    if _matches_any(q, DATA_QUERY_PATTERNS):
        return {"intent": "data_query"}

    # 概念原理类关键词 → concept
    if _matches_any(q, CONCEPT_PATTERNS):
        return {"intent": "concept"}

    # 无法归类 → other
    return {"intent": "other"}


def _matches_any(text: str, patterns: list[str]) -> bool:
    """判断文本是否匹配任意一个正则模式."""
    for p in patterns:
        if re.search(p, text):
            return True
    return False


# === 3. 专家节点 ===

def _get_chat_model():
    """创建 Coze LLMClient，每次调用新建实例以支持热加载配置.

    使用 coze_coding_dev_sdk 的 LLMClient，自动处理 SSE 响应解析.
    """
    config_path = os.path.join(
        os.getenv("COZE_WORKSPACE_PATH", "/workspace/projects"), LLM_CONFIG
    )
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    api_key = os.getenv("COZE_WORKLOAD_IDENTITY_API_KEY")
    base_url = os.getenv("COZE_INTEGRATION_MODEL_BASE_URL")
    ctx = request_context.get() or new_context(method="_get_chat_model")

    base_config = Config(api_key=api_key, base_url=base_url, timeout=600)
    return LLMClient(config=base_config, ctx=ctx)


def _build_expert_messages(state: JavaTutorState, expert: str) -> list:
    """为指定专家构建 system + user 消息列表."""
    source_code = state.get("source_code", "")
    user_question = state.get("user_question", "")
    steps_json = state.get("steps_json", "")
    steps_count = state.get("steps_count", 0)
    current_variables = state.get("current_variables", {})
    current_step_index = state.get("current_step_index", -1)
    compile_error = state.get("compile_error", "")

    prompt_map = {
        "data_query": SYSTEM_PROMPT_DATA_QUERY,
        "concept": SYSTEM_PROMPT_CONCEPT,
        "debug": SYSTEM_PROMPT_DEBUG,
        "other": SYSTEM_PROMPT_OTHER,
    }
    system_prompt = prompt_map.get(expert, SYSTEM_PROMPT_OTHER)

    context_parts = [f"用户问题: {user_question}", f"源代码:\n{source_code}"]

    if expert in ("data_query", "concept", "debug"):
        context_parts.append(f"执行步骤数: {steps_count} 步")
        context_parts.append(f"步骤详情(JSON):\n{steps_json}")

    if expert == "data_query" and current_variables:
        context_parts.append(
            f"当前步骤变量快照 (step {current_step_index}): {current_variables}"
        )

    # data_query 场景下 current_variables 已经是 str 格式（如 "[3, 5, 8, 1]"）
    # 确保格式化一致
    if expert == "data_query" and current_variables:
        if not isinstance(current_variables, str):
            import json as _json

            current_variables = str(
                _json.dumps(current_variables, ensure_ascii=False)
            )

    if expert == "debug" and compile_error:
        context_parts.append(f"编译/运行时错误:\n{compile_error}")

    context = "\n\n".join(context_parts)

    return [
        SystemMessage(content=system_prompt),
        HumanMessage(content=context),
    ]


def _run_expert(
    state: JavaTutorState, expert: str, model: "BaseChatModel | None" = None
) -> dict:
    """调用 LLM 生成专家回答，支持测试注入 FakeModel."""
    ctx = request_context.get() or new_context(method=f"_run_expert_{expert}")

    if model is None:
        model = _get_chat_model()

    messages = _build_expert_messages(state, expert)

    # 根据模型类型选择调用方式
    if hasattr(model, "invoke") and hasattr(model, "responses"):
        # FakeListLLM: 直接调用
        response = model.invoke(messages)
    else:
        # LLMClient: 使用 keyword 参数
        config_path = os.path.join(
            os.getenv("COZE_WORKSPACE_PATH", "/workspace/projects"), LLM_CONFIG
        )
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        extra_headers = default_headers(ctx) if default_headers(ctx) else None
        response = model.invoke(
            messages=messages,
            model=cfg["config"].get("model", "doubao-seed-2-0-lite-260215"),
            temperature=cfg["config"].get("temperature", 0.7),
            top_p=cfg["config"].get("top_p", 0.9),
            max_completion_tokens=cfg["config"].get("max_completion_tokens", 10000),
            extra_headers=extra_headers,
        )

    return {"answer": response.content if hasattr(response, "content") else str(response)}


def data_query_node(state: JavaTutorState, model: "BaseChatModel | None" = None) -> dict:
    """data_query 专家: 回答执行数据相关问题."""
    return _run_expert(state, "data_query", model=model)


def concept_node(state: JavaTutorState, model: "BaseChatModel | None" = None) -> dict:
    """concept 专家: 讲解算法原理."""
    return _run_expert(state, "concept", model=model)


def debug_node(state: JavaTutorState, model: "BaseChatModel | None" = None) -> dict:
    """debug 专家: 修复编译/运行时错误."""
    return _run_expert(state, "debug", model=model)


def other_node(state: JavaTutorState, model: "BaseChatModel | None" = None) -> dict:
    """other 专家: 通用兜底."""
    return _run_expert(state, "other", model=model)


def animate_node(state: JavaTutorState) -> dict:
    """animate 专家: Phase 1 占位，后续接入 SVG 生成器."""
    return {"answer": ANIMATE_PLACEHOLDER}


# === 4. final 节点 ===

def build_final(state: JavaTutorState) -> dict:
    """最终节点: 保留历史消息，追加 AIMessage."""
    answer = state.get("answer", "抱歉，我无法回答这个问题。")
    existing_messages: list = list(state.get("messages", []))
    return {
        "messages": existing_messages + [
            AIMessage(
                content=answer,
                additional_kwargs={
                    "intent": state.get("intent", "other"),
                },
            )
        ]
    }
