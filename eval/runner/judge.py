"""LLM-as-Judge：按 judge_prompt.md 对端到端回答评分。

默认使用独立的 DeepSeek 端点（环境变量 JUDGE_API_URL / JUDGE_API_KEY / JUDGE_MODEL），
不经过 Coze integration 端点；密钥只在环境变量或本地 .env 中提供，不写入代码。
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from graphs.javatutor.prompting.ontology import build_judge_grounding_block

JUDGE_PROMPT = Path(__file__).resolve().parents[1] / "judge_prompt.md"
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.0

logger = logging.getLogger(__name__)


def load_judge_prompt() -> str:
    return JUDGE_PROMPT.read_text(encoding="utf-8")


def build_judge_messages(sample: dict, answer: str) -> list:
    facts = "\n".join(sample.get("expected_facts", []))
    return [
        SystemMessage(content=load_judge_prompt() + "\n\n" + build_judge_grounding_block()),
        HumanMessage(content=f"考题：\n{sample.get('payload', {})}\n\n期望事实：\n{facts}\n\nAgent 回答：\n{answer}"),
    ]


_VALID_JUDGEMENTS = {"correct", "partially_correct", "incorrect"}
_SCORE_KEYS = ("relevance", "grounding", "pollution", "correctness")

# 评分 JSON Schema：约束字段/枚举/范围，优先传给 API；不支持则回退 json_object。
_JUDGE_JSON_SCHEMA = {
    "name": "judge_result",
    "schema": {
        "type": "object",
        "properties": {
            "score": {"type": "number", "minimum": 0, "maximum": 5},
            "judgement": {"type": "string", "enum": ["correct", "partially_correct", "incorrect"]},
            "scores": {
                "type": "object",
                "properties": {
                    "relevance": {"type": "number", "minimum": 0, "maximum": 5},
                    "grounding": {"type": "number", "minimum": 0, "maximum": 5},
                    "pollution": {"type": "number", "minimum": 0, "maximum": 5},
                    "correctness": {"type": "number", "minimum": 0, "maximum": 5},
                },
                "required": ["relevance", "grounding", "pollution", "correctness"],
            },
            "reason": {"type": "string"},
        },
        "required": ["score", "judgement", "scores", "reason"],
    },
}


def _strip_fences(text: str) -> str:
    """去除 markdown 代码块围栏（```json / ```），保留内部内容。"""
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_object(text: str) -> str | None:
    """在剩余文本中取第一个 { 到最后一个 } 的子串。"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _coerce_score(value) -> float:
    """score 接受数字或数字字符串，失败返回 0.0，并 clamp 到 [0, 5]."""
    if isinstance(value, bool):
        return 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(5.0, v))


def _normalize_parsed(data: dict) -> dict[str, Any] | None:
    """字段归一化：score 数字串转数字并 clamp；scores 各维补默认/clamp；judgement 非枚举归 incorrect."""
    if not isinstance(data, dict) or "score" not in data:
        return None
    scores = data.get("scores")
    if not isinstance(scores, dict):
        scores = {}
    scores = {key: _coerce_score(scores.get(key)) for key in _SCORE_KEYS}
    judgement = data.get("judgement")
    if judgement not in _VALID_JUDGEMENTS:
        judgement = "incorrect"
    return {
        "score": _coerce_score(data.get("score")),
        "judgement": judgement,
        "scores": scores,
        "reason": str(data.get("reason", "")),
    }


def parse_judge_output(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    text = _strip_fences(text)
    # 先尝试整体解析；失败再取首个 { 到最后一个 } 的子串
    candidates = [text, _extract_json_object(text)]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(data, dict):
            return _normalize_parsed(data)
    return None


def _messages_to_openai(messages) -> list[dict[str, str]]:
    role_map = {"system": "system", "human": "user", "ai": "assistant"}
    result = []
    for msg in messages:
        role = role_map.get(msg.type, "user")
        content = msg.content
        if isinstance(content, list):
            texts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            content = "\n".join(texts)
        result.append({"role": role, "content": str(content)})
    return result


def judge_complete(messages, temperature: float = 0.1) -> str:
    """调用 DeepSeek 兼容 chat completions 接口返回完整文本。

    优先启用 json_schema（约束字段/枚举/范围）；若端点返回 4xx 表示不支持，
    则回退到 json_object（由 _normalize_parsed 继续做字段校验）。
    """
    import httpx

    api_url = os.getenv("JUDGE_API_URL", "https://api.deepseek.com").rstrip("/")
    api_key = os.getenv("JUDGE_API_KEY", "")
    model = os.getenv("JUDGE_MODEL", "deepseek-chat")
    if not api_key:
        raise RuntimeError("JUDGE_API_KEY 未配置，请在本地 .env 中填写 DeepSeek Key")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    base_payload = {
        "model": model,
        "messages": _messages_to_openai(messages),
        "temperature": temperature,
        "max_tokens": 500,
        "stream": False,
    }

    response_formats = [
        {"type": "json_schema", "json_schema": _JUDGE_JSON_SCHEMA},
        {"type": "json_object"},
    ]
    for response_format in response_formats:
        payload = {**base_payload, "response_format": response_format}
        resp = httpx.post(f"{api_url}/chat/completions", json=payload, headers=headers, timeout=60)
        if response_format["type"] == "json_schema" and 400 <= resp.status_code < 500:
            # 端点不支持 json_schema，回退 json_object 重试
            logger.warning("json_schema 不被端点支持（HTTP %s），回退 json_object", resp.status_code)
            continue
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    raise RuntimeError("judge_complete 未返回内容（json_schema/json_object 均失败）")


def _judge_once(sample: dict, answer: str, model=None, temperature: float = 0.1):
    """单次评分调用，返回 (raw, parsed, error)。"""
    try:
        if model is not None:
            raw = model.invoke(build_judge_messages(sample, answer)).content
        else:
            raw = judge_complete(build_judge_messages(sample, answer), temperature=temperature)
    except Exception as exc:
        return None, None, exc
    return raw, parse_judge_output(raw), None


def judge_answer(sample: dict, answer: str, model=None) -> dict[str, Any]:
    """评分单个样本：解析失败/空返回时以 temperature=0 重试，最多 MAX_ATTEMPTS 次。

    - 真实调用（model=None）每次重试间退避 RETRY_BACKOFF_SECONDS，缓解端点间歇性空返回。
    - 返回 dict 始终包含 raw_judge_output（最终一次尝试的模型原始输出，便于排查）。
    - 仍失败标记 judge_fallback；若最终输出为空串额外标记 empty_output 便于统计。
    """
    last_raw, last_parsed, last_error = None, None, None
    for attempt in range(MAX_ATTEMPTS):
        temperature = 0.1 if attempt == 0 else 0.0
        last_raw, last_parsed, last_error = _judge_once(
            sample, answer, model, temperature=temperature
        )
        if last_parsed is not None or last_error is not None:
            break
        # 解析失败：真实调用时退避后重试；注入 model 不 sleep
        if attempt < MAX_ATTEMPTS - 1 and model is None:
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
        logger.warning(
            "judge parse failed (attempt %d/%d, raw=%r) for id=%s",
            attempt + 1, MAX_ATTEMPTS, (last_raw or "")[:80], sample.get("id"),
        )

    out: dict[str, Any] = {
        "id": sample.get("id"),
        "raw_judge_output": last_raw,
        "attempts": attempt + 1,
    }
    if last_parsed is not None:
        out.update(last_parsed)
    else:
        # 确定性兜底：保证每条样本都有可解析分数，后续可按 raw 人工复核。
        out.update({
            "score": 0.0,
            "judgement": "incorrect",
            "scores": {"relevance": 0, "grounding": 0, "pollution": 0, "correctness": 0},
            "reason": "judge output unparseable",
            "judge_fallback": True,
        })
        if last_error is not None:
            out["error"] = str(last_error)
        if (last_raw or "").strip() == "":
            out["empty_output"] = True
    return out
