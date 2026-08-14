"""评估汇总与前后对比。"""

import json
from pathlib import Path

from graphs.javatutor.intent_rules import fact_matches


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


def _safe(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def _tool_call_ok(expected: list, actual: list) -> bool:
    expected = expected or []
    actual = actual or []
    if len(expected) != len(actual):
        return False

    def norm(calls):
        return sorted((c.get("tool"), json.dumps(c.get("args", {}), sort_keys=True)) for c in calls)

    return norm(expected) == norm(actual)


def compute_extended_metrics(outputs: list[dict], samples: list[dict], judged: list[dict]) -> dict:
    """M1.1 扩展指标：tool_call_accuracy / task_success_rate / avg_latency / avg_token_usage。

    调用方在端到端跑完后，将返回值与 ``summarize()`` 结果的 ``e2e`` 字典合并：
    ``summary["e2e"].update(compute_extended_metrics(outputs, samples, judged))``。
    """
    by_id = {s["id"]: s for s in samples}
    tc_total = tc_ok = 0
    latency: list[float] = []
    tokens: list[int] = []
    for out in outputs:
        sample = by_id.get(out.get("id"), {})
        expected = sample.get("expected_tool_calls")
        if expected is not None:
            tc_total += 1
            tc_ok += int(_tool_call_ok(expected, (out.get("decision_trace") or {}).get("tool_calls")))
        if out.get("latency") is not None:
            latency.append(out["latency"])
        usage = (out.get("decision_trace") or {}).get("token_usage") or {}
        if usage:
            tokens.append(int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0)))
    task_total = task_ok = 0
    for j in judged:
        if j.get("judge_parse_error"):
            continue
        sample = by_id.get(j.get("id"), {})
        out = next((o for o in outputs if o.get("id") == j.get("id")), {})
        facts_ok = all(fact_matches(f, out.get("answer", "")) for f in sample.get("expected_facts", []))
        task_total += 1
        task_ok += int(j.get("judgement") == "correct" and facts_ok)
    return {
        "tool_call_accuracy": _safe(tc_ok, tc_total),
        "task_success_rate": _safe(task_ok, task_total),
        "avg_latency": round(sum(latency) / len(latency), 3) if latency else 0.0,
        "avg_token_usage": round(sum(tokens) / len(tokens), 1) if tokens else 0,
    }
