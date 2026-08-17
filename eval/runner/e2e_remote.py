"""remote mode（M1.1 新增）：通过已部署智能体 Chat API 采集回答。"""

import json
import time
from pathlib import Path
from typing import Any

import httpx


def parse_decision_trace(text: str) -> dict[str, Any] | None:
    marker = "\n【决策痕迹】\n"
    idx = (text or "").rfind(marker)
    if idx < 0:
        return None
    raw = text[idx + len(marker):].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def chat_remote(
    sample: dict,
    api_url: str,
    token: str,
    project_id: str,
    timeout: int = 120,
) -> dict[str, Any]:
    payload = {
        "content": {"query": {"prompt": [{"type": "text", "content": {"text": json.dumps(sample["payload"], ensure_ascii=False)}}]}},
        "type": "query",
        "session_id": sample.get("id", ""),
        "project_id": project_id,
    }
    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    full: list[str] = []
    event = None
    with httpx.stream("POST", api_url, json=payload, headers=headers, timeout=timeout) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            line = (line or "").strip()
            if not line:
                continue
            if line.startswith("event: "):
                event = line[7:].strip()
                continue
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            if event == "message" and chunk.get("type") == "answer":
                content = chunk.get("content")
                if isinstance(content, dict):
                    full.append(content.get("answer", ""))
                elif isinstance(content, str):
                    full.append(content)
    latency = round(time.time() - start, 3)
    answer = "".join(full)
    return {"id": sample.get("id"), "answer": answer, "latency": latency, "decision_trace": parse_decision_trace(answer)}


def run_remote_golden_set(
    samples: list[dict],
    api_url: str,
    token: str,
    project_id: str,
    out_path: str | Path | None = None,
) -> list[dict]:
    outputs = [chat_remote(s, api_url, token, project_id) for s in samples if s.get("judge_priority")]
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in outputs), encoding="utf-8")
    return outputs
