"""端到端 runner：Coze 平台执行黄金集并产出回答。"""

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage


def run_sample(agent, sample: dict) -> dict[str, Any]:
    payload = sample["payload"]
    initial = {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]}
    result = agent.invoke(initial)
    ai_msgs = [m for m in result.get("messages", []) if getattr(m, "type", "") == "ai"]
    content = ai_msgs[-1].content if ai_msgs else ""
    return {"id": sample.get("id"), "answer": content, "decision_trace": result.get("decision_trace", {})}


def run_golden_set(samples: list[dict], agent=None, out_path: str | Path | None = None) -> list[dict]:
    if agent is None:
        from agents.agent import build_agent

        agent = build_agent().builder.compile()
    outputs = [run_sample(agent, s) for s in samples if s.get("judge_priority")]
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in outputs), encoding="utf-8")
    return outputs
