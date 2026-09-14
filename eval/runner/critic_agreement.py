"""评审 × Judge 一致性聚合（只读，确定性，不依赖 LLM/DB）。

**单一实现**：`tools/critic_audit.py`（离线复跑设计 §1.2 的交叉表）与
`eval/runner/component_metrics.py`（评估 summary）都调这里，避免两套口径分叉。

口径（设计 `docs/spec/2026-09-14-critic-revise-optimization-design.md` §1.2）：

- **被拦** = 决策痕迹 `critic_passed is False`。
- **precision** = 被拦且 Judge **判非 `correct`** / 被拦。
  分子含 `partially_correct`——那是「确实有问题」的答案，拦对了。
  设计 §1.2 的 `22/33`（67%）即此。
- **recall** = 被拦且 Judge **判 `incorrect`** / Judge 判 `incorrect` 的总数。
  分母**只算 `incorrect`**：`partially_correct` 是本项目「可用」的口径，不算「本该拦」。
  设计 §1.2 的 `10/22`（45%）即此。

两个口径的「正例」定义刻意不同（precision 用「非 correct」，recall 用「incorrect」），
所以两者不可互相推导；`tp/fp/fn` 与两个分母一并返回，便于逐格复核。
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

# Judge 判定词表（`judged.jsonl` 的 `judgement` 字段）。`correct` 是唯一「无问题」档。
JUDGE_CORRECT = "correct"
JUDGE_INCORRECT = "incorrect"


def load_judged(paths) -> list[dict]:
    """读任意数量的 `judged.jsonl`（文件或目录）；目录会递归找 `judged.jsonl`。

    目录名会记进 `_round` 供按轮次拆分。解析失败的单行跳过——归档是历史产物，
    本模块只做只读统计，不因一行坏数据整体失败。
    """
    out: list[dict] = []
    for raw in paths:
        p = Path(raw)
        files = sorted(p.rglob("judged.jsonl")) if p.is_dir() else [p]
        for f in files:
            if not f.exists():
                continue
            round_name = f.parent.name if p.is_dir() else ""
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if round_name:
                    rec["_round"] = round_name
                out.append(rec)
    return out


def _empty() -> dict:
    return {
        "n": 0,
        "critic_failed": 0,
        "revised": 0,
        "critic_fail_rate": 0.0,
        "revise_rate": 0.0,
        "critic_agree_with_judge": {
            "precision": 0.0, "precision_num": 0, "precision_den": 0,
            "recall": 0.0, "recall_num": 0, "recall_den": 0,
            "tp": 0, "fp": 0, "fn": 0, "n": 0,
        },
        "by_intent": {},
        "by_round": {},
    }


def aggregate_critic_agreement(records: list[dict]) -> dict:
    """把 `judged.jsonl` 记录聚合成设计 §1.2 的交叉表（含 `critic_fail_rate` 与一致性指标）。

    无记录时返回全零的同一形状，消费方不必为「没归档」单开分支。
    """
    if not records:
        return _empty()

    n = len(records)
    failed = revised = 0
    flagged_non_correct = flagged_incorrect = all_incorrect = 0
    by_intent: dict[str, Counter] = defaultdict(Counter)
    by_round: dict[str, Counter] = defaultdict(Counter)

    for rec in records:
        trace = rec.get("decision_trace") or {}
        judgement = rec.get("judgement")
        round_name = rec.get("_round") or ""
        critic_failed = trace.get("critic_passed") is False

        if judgement == JUDGE_INCORRECT:
            all_incorrect += 1
        if critic_failed:
            failed += 1
            if judgement != JUDGE_CORRECT:
                flagged_non_correct += 1
            if judgement == JUDGE_INCORRECT:
                flagged_incorrect += 1
            by_intent[trace.get("intent") or "?"][judgement] += 1
        if trace.get("revised"):
            revised += 1

        if round_name:
            by_round[round_name]["n"] += 1
            by_round[round_name]["failed"] += int(critic_failed)
            by_round[round_name]["revised"] += int(bool(trace.get("revised")))
            by_round[round_name]["correct_but_failed"] += int(
                critic_failed and judgement == JUDGE_CORRECT
            )

    return {
        "n": n,
        "critic_failed": failed,
        "revised": revised,
        "critic_fail_rate": round(failed / n, 4),
        "revise_rate": round(revised / n, 4),
        "critic_agree_with_judge": {
            "precision": round(flagged_non_correct / failed, 4) if failed else 0.0,
            "precision_num": flagged_non_correct,
            "precision_den": failed,
            "recall": round(flagged_incorrect / all_incorrect, 4) if all_incorrect else 0.0,
            "recall_num": flagged_incorrect,
            "recall_den": all_incorrect,
            "tp": flagged_non_correct,
            "fp": failed - flagged_non_correct,
            "fn": all_incorrect - flagged_incorrect,
            "n": failed,
        },
        # 按意图拆「被拦」：`{intent: {judgement: n}}`，设计 §1.2 的 `debug 14(5)` 即
        # `by_intent["debug"]` 全部之和 14、其中 `correct` 5。
        "by_intent": {k: dict(v) for k, v in by_intent.items()},
        "by_round": {k: dict(v) for k, v in by_round.items()},
    }


def format_audit_table(agg: dict) -> str:
    """人读交叉表（`tools/critic_audit.py` 的 CLI 打印，也便于把结论粘进文档）。"""
    if not agg.get("n"):
        return "（无样本：未找到任何 judged.jsonl）"

    a = agg["critic_agree_with_judge"]
    lines = [
        f"样本 n={agg['n']}",
        f"评审判失败 {agg['critic_failed']}（{agg['critic_fail_rate']:.1%}）"
        f" / 触发修订 {agg['revised']}（{agg['revise_rate']:.1%}）",
        "",
        "评审 × Judge 一致性：",
        f"  precision {a['precision_num']}/{a['precision_den']} = {a['precision']:.1%}"
        f"（被拦且 Judge 判非 correct）",
        f"  recall    {a['recall_num']}/{a['recall_den']} = {a['recall']:.1%}"
        f"（分母只算 Judge 判 incorrect）",
        f"  tp={a['tp']}（拦对）fp={a['fp']}（误杀）fn={a['fn']}（漏拦）",
        "",
        "按意图拆被拦样本（括号内为其中 Judge 判 correct 的误杀数）：",
    ]
    for intent, dist in sorted(agg["by_intent"].items(), key=lambda kv: -sum(kv[1].values())):
        lines.append(f"  {intent}: {sum(dist.values())}（{dist.get(JUDGE_CORRECT, 0)}）")
    if agg.get("by_round"):
        lines += ["", "按轮次："]
        for rnd, d in sorted(agg["by_round"].items()):
            lines.append(
                f"  {rnd}: n={d.get('n', 0)} 拦={d.get('failed', 0)} "
                f"修订={d.get('revised', 0)} 误杀={d.get('correct_but_failed', 0)}"
            )
    return "\n".join(lines)
