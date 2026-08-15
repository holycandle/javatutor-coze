"""Win Rate：新旧版本成对对比（LLM 裁判）。

输入：同一黄金样本的两个版本回答（A=旧版，B=新版）。
输出：每样本 winner(a/b/tie) + reason；聚合 win_rate / loss_rate / tie_rate。
"""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from eval.runner.judge import judge_complete

WINRATE_PROMPT = """你是版本对比裁判。对同一道题的两个回答判断哪个更好。
只返回 JSON：{"winner": "a"|"b"|"tie", "reason": "一句话"}
评分标准：相关性、事实准确性（必须基于真实数据）、grounding、无上下文污染。"""


def _facts(sample: dict) -> str:
    return "\n".join(sample.get("expected_facts", []))


def build_winrate_messages(sample: dict, answer_a: str, answer_b: str) -> list:
    return [
        SystemMessage(content=WINRATE_PROMPT),
        HumanMessage(
            content=(
                f"考题：\n{sample.get('payload', {})}\n\n期望事实：\n{_facts(sample)}\n\n"
                f"版本 A：\n{answer_a}\n\n版本 B：\n{answer_b}"
            )
        ),
    ]


def parse_winrate(raw: str) -> dict | None:
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
    return data if isinstance(data, dict) else None


def compare_pair(sample: dict, answer_a: str, answer_b: str, model=None) -> dict[str, Any]:
    try:
        messages = build_winrate_messages(sample, answer_a, answer_b)
        if model is not None:
            raw = model.invoke(messages).content
        else:
            raw = judge_complete(messages)
        data = parse_winrate(raw)
        winner = data.get("winner") if data else "tie"
        if winner not in ("a", "b", "tie"):
            winner = "tie"
        return {"id": sample.get("id"), "winner": winner, "reason": (data or {}).get("reason", "")}
    except Exception as exc:
        return {"id": sample.get("id"), "winner": "tie", "reason": f"parse error: {exc}"}


def compute_winrate(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(comparisons)
    wins = sum(1 for c in comparisons if c.get("winner") == "a")
    losses = sum(1 for c in comparisons if c.get("winner") == "b")
    ties = total - wins - losses
    return {
        "total": total,
        "win_rate": round(wins / total, 4) if total else 0.0,
        "loss_rate": round(losses / total, 4) if total else 0.0,
        "tie_rate": round(ties / total, 4) if total else 0.0,
    }
