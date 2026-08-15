"""共享 LLM 客户端工厂，避免节点模块 ↔ nodes.py 循环导入。

提供两种调用方式：
- get_chat_model(): 返回 LLMClient（内部使用 ChatOpenAI，会被 stream_mode=messages 拦截）
- llm_complete():   原始 HTTP 调用，绕过 ChatOpenAI，不会被 stream_mode=messages 拦截
"""

import json
import logging
import os
from typing import Any

import httpx
from langchain_core.messages import BaseMessage

from coze_coding_dev_sdk import LLMClient, Config, LLMConfig as SDKLLMConfig
from coze_coding_utils.log.write_log import request_context
from coze_coding_utils.runtime_ctx.context import default_headers, new_context

logger = logging.getLogger(__name__)

LLM_CONFIG_PATH = "config/agent_llm_config.json"


def get_chat_model() -> tuple[LLMClient, SDKLLMConfig]:
    """热加载配置并创建 LLMClient 实例。"""
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
    ctx = request_context.get() or new_context(method="get_chat_model")
    client = LLMClient(config=base_config, ctx=ctx)
    return client, llm_config


# ── 原始 HTTP LLM 调用（绕过 ChatOpenAI，不被 stream_mode=messages 拦截）────────


def _load_llm_settings() -> dict[str, Any]:
    """加载模型配置 + API 凭据，返回合并后的设置 dict。"""
    workspace_path = os.getenv("COZE_WORKSPACE_PATH", "/workspace/projects")
    config_path = os.path.join(workspace_path, LLM_CONFIG_PATH)
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    return {
        "model": cfg["config"].get("model", "doubao-seed-2-0-lite-260215"),
        "temperature": cfg["config"].get("temperature", 0.7),
        "top_p": cfg["config"].get("top_p", 0.9),
        "max_completion_tokens": cfg["config"].get("max_completion_tokens", 10000),
        "timeout": cfg["config"].get("timeout", 600),
        "thinking": cfg["config"].get("thinking", "disabled"),
    }


def _messages_to_openai(messages: list[BaseMessage]) -> list[dict[str, str]]:
    """将 LangChain 消息列表转为 OpenAI chat 格式。"""
    role_map = {"system": "system", "human": "user", "ai": "assistant"}
    result: list[dict[str, str]] = []
    for msg in messages:
        role = role_map.get(msg.type, "user")
        content = msg.content
        if isinstance(content, list):
            # 多模态 content — 提取纯文本
            texts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    texts.append(part.get("text", ""))
            content = "\n".join(texts)
        result.append({"role": role, "content": str(content)})
    return result


def llm_complete(
    messages: list[BaseMessage],
    *,
    temperature: float | None = None,
    max_completion_tokens: int | None = None,
) -> str:
    """原始 HTTP 调用 LLM，返回完整文本。

    与 LLMClient.invoke() 不同，此函数直接使用 httpx POST 到
    /chat/completions 端点，不创建 ChatOpenAI 实例，因此不会被
    LangGraph 的 stream_mode="messages" 拦截和流式转发。

    用于意图分类、评审、修订等中间 LLM 调用，确保其输出不会
    泄露到客户端流式输出中。
    """
    settings = _load_llm_settings()
    base_url = os.getenv("COZE_INTEGRATION_MODEL_BASE_URL", "")

    # 构建 headers（含上下文追踪）
    config = Config()
    headers = config.get_headers()
    ctx = request_context.get() or new_context(method="llm_complete")
    ctx_headers = default_headers(ctx)
    headers.update(ctx_headers)

    payload: dict[str, Any] = {
        "model": settings["model"],
        "messages": _messages_to_openai(messages),
        "stream": True,
        "temperature": temperature if temperature is not None else settings["temperature"],
        "top_p": settings["top_p"],
        "max_completion_tokens": max_completion_tokens or settings["max_completion_tokens"],
        "thinking": {"type": settings.get("thinking", "disabled")},
    }

    url = f"{base_url.rstrip('/')}/chat/completions"
    timeout = settings.get("timeout", 600)

    # API 始终返回 SSE 流式格式，需逐行解析
    full_content_parts: list[str] = []
    with httpx.stream("POST", url, json=payload, headers=headers, timeout=timeout) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                # 检测 SSE 错误响应（如积分不足）
                if "error" in chunk:
                    err = chunk["error"]
                    raise RuntimeError(
                        f"LLM API error: {err.get('code', 'unknown')} - {err.get('message', '')}"
                    )
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content_piece = delta.get("content")
                    if content_piece:
                        full_content_parts.append(content_piece)
            except (json.JSONDecodeError, IndexError, KeyError):
                continue

    result = "".join(full_content_parts)
    if not result:
        logger.warning("llm_complete returned empty content (model=%s)", settings["model"])
    return result
