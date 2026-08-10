"""共享 LLM 客户端工厂，避免 intent.py ↔ nodes.py 循环导入。"""

import json
import os

from coze_coding_dev_sdk import LLMClient, Config, LLMConfig as SDKLLMConfig
from coze_coding_utils.log.write_log import request_context
from coze_coding_utils.runtime_ctx.context import new_context

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
