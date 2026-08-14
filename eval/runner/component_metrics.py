"""组件级确定性指标（本地，不依赖 LLM/DB）。"""

import json
from pathlib import Path
from typing import Callable

from graphs.javatutor.intent_rules import conservative_intent, fact_matches


def load_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _safe(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def run_component_cases(
    cases: list[dict],
    intent_fn: Callable = conservative_intent,
    fact_check: Callable = fact_matches,
    rag_search: Callable | None = None,
) -> dict:
    results = []
    intent_total = intent_hit = 0
    citation_total = citation_hit = 0
    critic_expected = critic_flagged = 0
    rag_total = rag_hit = 0

    for case in cases:
        ctype = case.get("type")
        if ctype == "intent":
            intent_total += 1
            got = intent_fn(case["input"].get("user_question", ""), case["input"].get("compile_error", ""))
            ok = got == case.get("expected")
            intent_hit += int(ok)
            results.append({"type": ctype, "id": case.get("id", ""), "ok": ok, "expected": case.get("expected"), "actual": got})
        elif ctype == "citation":
            citation_total += 1
            ok = all(fact_check(f, case.get("answer", "")) for f in case.get("expected_facts", []))
            citation_hit += int(ok)
            results.append({"type": ctype, "id": case.get("id", ""), "ok": ok})
        elif ctype == "critic":
            flagged = not all(fact_check(f, case.get("answer", "")) for f in case.get("expected_facts", []))
            if case.get("expect_fail"):
                critic_expected += 1
                critic_flagged += int(flagged)
            results.append({"type": ctype, "id": case.get("id", ""), "ok": flagged == case.get("expect_fail")})
        elif ctype == "rag":
            rag_total += 1
            ok = False
            if rag_search is not None:
                sources = rag_search(case["input"].get("query", ""))
                ok = any(s in sources for s in case.get("expected_sources", []))
            rag_hit += int(ok)
            results.append({"type": ctype, "id": case.get("id", ""), "ok": ok})

    pass_total = len(results)
    pass_rate = _safe(sum(1 for r in results if r["ok"]), pass_total)
    return {
        "intent_accuracy": _safe(intent_hit, intent_total),
        "citation_accuracy": _safe(citation_hit, citation_total),
        "critic_recall": _safe(critic_flagged, critic_expected),
        "rag_hit_at_3": _safe(rag_hit, rag_total),
        "pass_rate": pass_rate,
        "results": results,
    }
