"""评估汇总与前后对比。"""

import json
from pathlib import Path


def load_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarize(judged: list[dict], component: dict | None = None) -> dict:
    parsed = [j for j in judged if not j.get("judge_parse_error")]
    total = len(parsed)
    avg_score = round(sum(j.get("score", 0) for j in parsed) / total, 4) if total else 0.0
    grounding = [j.get("scores", {}).get("grounding", 0) for j in parsed]
    grounding_avg = round(sum(grounding) / len(grounding), 4) if grounding else 0.0
    return {
        "e2e": {
            "avg_score": avg_score,
            "grounding_avg": grounding_avg,
            "total": total,
            "correct": sum(1 for j in parsed if j.get("judgement") == "correct"),
            "partially_correct": sum(1 for j in parsed if j.get("judgement") == "partially_correct"),
            "incorrect": sum(1 for j in parsed if j.get("judgement") == "incorrect"),
        },
        "component": component or {},
        "diff_vs_previous": {},
    }


def diff(previous: dict, current: dict) -> dict:
    prev_e2e = previous.get("e2e", {})
    cur_e2e = current.get("e2e", {})
    return {
        "avg_score": round(cur_e2e.get("avg_score", 0) - prev_e2e.get("avg_score", 0), 4),
        "grounding_avg": round(cur_e2e.get("grounding_avg", 0) - prev_e2e.get("grounding_avg", 0), 4),
        "component_pass_rate": round(
            current.get("component", {}).get("pass_rate", 0) - previous.get("component", {}).get("pass_rate", 0), 4
        ),
    }


def write_summary(path, summary) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
