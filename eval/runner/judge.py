"""LLM-as-Judge：按 judge_prompt.md 对端到端回答评分。"""

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

JUDGE_PROMPT = Path(__file__).resolve().parents[1] / "judge_prompt.md"


def load_judge_prompt() -> str:
    return JUDGE_PROMPT.read_text(encoding="utf-8")


def build_judge_messages(sample: dict, answer: str) -> list:
    facts = "\n".join(sample.get("expected_facts", []))
    return [
        SystemMessage(content=load_judge_prompt()),
        HumanMessage(content=f"考题：\n{sample.get('payload', {})}\n\n期望事实：\n{facts}\n\nAgent 回答：\n{answer}"),
    ]


def parse_judge_output(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "score" not in data:
        return None
    return data


def judge_answer(sample: dict, answer: str, model=None) -> dict[str, Any]:
    try:
        if model is not None:
            raw = model.invoke(build_judge_messages(sample, answer)).content
        else:
            from graphs.javatutor.llm import llm_complete

            raw = llm_complete(build_judge_messages(sample, answer), temperature=0.1, max_completion_tokens=500)
        parsed = parse_judge_output(raw)
        if parsed is None:
            return {"id": sample.get("id"), "judge_parse_error": True}
        return {"id": sample.get("id"), **parsed}
    except Exception as exc:
        return {"id": sample.get("id"), "judge_parse_error": True, "error": str(exc)}
