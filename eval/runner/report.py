"""评估汇总与前后对比。"""

import json
import subprocess
from pathlib import Path

from graphs.javatutor.intent_rules import fact_matches

ROOT = Path(__file__).resolve().parents[2]


def resolve_model(root: Path | None = None) -> str:
    """从 config/agent_llm_config.json 读取模型名，失败回退 unknown。"""
    cfg = (root or ROOT) / "config" / "agent_llm_config.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        return str((data.get("config") or {}).get("model", "unknown") or "unknown")
    except Exception:
        return "unknown"


def resolve_commit(root: Path | None = None) -> str:
    """读取当前仓库短 commit，失败回退 unknown。"""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root or ROOT), "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip() or "unknown"
    except Exception:
        return "unknown"


def load_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarize(judged: list[dict], component: dict | None = None, extended: dict | None = None) -> dict:
    # 兜底样本（judge_fallback）有 score=0/incorrect，但 avg_score/grounding 只统计有效评分样本；
    # judge_fallback_rate / empty_output_rate 用全部样本作分母，显式化解析退化比例。
    parsed = [j for j in judged if not j.get("judge_fallback")]
    total = len(parsed)
    avg_score = round(sum(j.get("score", 0) for j in parsed) / total, 4) if total else 0.0
    grounding = [j.get("scores", {}).get("grounding", 0) for j in parsed]
    grounding_avg = round(sum(grounding) / len(grounding), 4) if grounding else 0.0
    e2e = {
        "avg_score": avg_score,
        "grounding_avg": grounding_avg,
        "total": total,
        "correct": sum(1 for j in parsed if j.get("judgement") == "correct"),
        "partially_correct": sum(1 for j in parsed if j.get("judgement") == "partially_correct"),
        "incorrect": sum(1 for j in parsed if j.get("judgement") == "incorrect"),
        "judge_fallback_rate": _safe(sum(1 for j in judged if j.get("judge_fallback")), len(judged)),
        "empty_output_rate": _safe(sum(1 for j in judged if j.get("empty_output")), len(judged)),
    }
    if extended:
        e2e.update(extended)
    return {
        "e2e": e2e,
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


def _round_key(round_dir: Path) -> tuple | None:
    """返回用于时间序排序的 (year, month, day, round_n)；目录名不合规时返回 None。

    直接按字符串排序日期会因「2026-9-6 / 2026-10-5」这类非补零月份错序，
    故解析为整数元组再比较（一次比较即可兼顾日期与轮次）。
    """
    try:
        n = int(round_dir.name.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return None
    date_parts = round_dir.parent.name.split("-")
    if len(date_parts) != 3:
        return None
    try:
        y, m, d = (int(p) for p in date_parts)
    except ValueError:
        return None
    return (y, m, d, n)


def resolve_previous_summary(round_dir: Path) -> dict | None:
    """解析上一轮 summary.json；无上一轮时返回 None。

    上一轮 = 按时间序（日期 + round-n）严格早于当前轮次的**最近**一轮：
    - 同一日期下若有 round-{n-1}，自然命中；
    - 否则回退到更早日期的最近一轮（支持跨日期对比，如 09-6/round-2 对比 08-17/round-1）。
    自动排除当前轮次自身的 summary.json（report 可能已写过）。
    """
    current_key = _round_key(round_dir)
    if current_key is None:
        return None
    archive = round_dir.parent.parent
    best_key = None
    best_path: Path | None = None
    for summary_path in archive.glob("*/round-*/summary.json"):
        cand_key = _round_key(summary_path.parent)
        if cand_key is None or cand_key >= current_key:
            continue
        if best_key is None or cand_key > best_key:
            best_key = cand_key
            best_path = summary_path
    if best_path is None:
        return None
    try:
        return json.loads(best_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_summary(path, summary) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


_E2E_METRIC_ORDER = (
    "total",
    "avg_score",
    "grounding_avg",
    "correct",
    "partially_correct",
    "incorrect",
    "tool_call_accuracy",
    "task_success_rate",
    "avg_latency",
    "avg_token_usage",
    "judge_fallback_rate",
    "empty_output_rate",
    "grounding_verify_applicable",
    "grounding_verify_checked",
    "grounding_verify_violations",
    "grounding_verify_accuracy",
)


def _collect_badcases(judged: list[dict], outputs_by_id: dict) -> list[dict]:
    """收集 badcase：judge_fallback、score<=2 或 grounding<=2 的条目。"""
    out = []
    for j in judged:
        grounding = (j.get("scores") or {}).get("grounding", 0)
        if not (j.get("judge_fallback") or j.get("score", 0) <= 2 or grounding <= 2):
            continue
        answer = j.get("answer") or outputs_by_id.get(j.get("id"), {}).get("answer", "")
        out.append(
            {
                "id": j.get("id", ""),
                "score": j.get("score", 0),
                "judgement": j.get("judgement", ""),
                "reason": j.get("reason", ""),
                "answer": answer,
                "judge_fallback": bool(j.get("judge_fallback")),
                "empty_output": bool(j.get("empty_output")),
            }
        )
    return out


def write_report(path, summary, judged, outputs, samples, model="unknown", commit="unknown") -> str:
    """在 summary.json 同目录写 report.md（人读报告）。

    日期/轮次从 path（round 目录）推断；只作人读层，不改 summary.json。
    """
    round_dir = Path(path)
    date = round_dir.parent.name
    round_name = round_dir.name
    e2e = summary.get("e2e", {})
    component = summary.get("component", {}) or {}
    diff_vs = summary.get("diff_vs_previous", {}) or {}

    lines = [
        f"# 评估报告 {date} {round_name}",
        "",
        f"- 日期：{date}",
        f"- 轮次：{round_name}",
        f"- 模型：{model}",
        f"- commit：{commit}",
        "",
        "## 组件级指标",
        "",
    ]
    if component:
        lines += ["| 指标 | 值 |", "|---|---|"]
        lines += [f"| {key} | {value} |" for key, value in component.items()]
    else:
        lines.append("（本轮未运行组件评测）")

    lines += ["", "## 端到端指标", "", "| 指标 | 值 |", "|---|---|"]
    for key in _E2E_METRIC_ORDER:
        if key in e2e:
            lines.append(f"| {key} | {e2e[key]} |")

    tool_by_tool = e2e.get("tool_call_by_tool") or {}
    if tool_by_tool:
        lines += [
            "",
            "## 各工具调用情况",
            "",
            "| 工具 | 期望样本 | 实际调用 | 正确 | 准确率 | 误用(未期望却调用) |",
            "|---|---|---|---|---|---|",
        ]
        for t, m in tool_by_tool.items():
            acc = m["accuracy"] if m["accuracy"] is not None else "-"
            lines.append(f"| {t} | {m['expected']} | {m['called']} | {m['correct']} | {acc} | {m['unexpected']} |")

    lines += ["", "## 与上一轮对比", ""]
    if diff_vs:
        lines += ["| 指标 | diff |", "|---|---|"]
        lines += [f"| {key} | {value} |" for key, value in diff_vs.items()]
    else:
        lines.append("（无上一轮数据）")

    lines += ["", "## Badcase", ""]
    badcases = _collect_badcases(judged, {o.get("id"): o for o in outputs})
    if badcases:
        for i, b in enumerate(badcases, 1):
            lines.append(f"### {i}. {b['id']} — {b['judgement']} (score={b['score']})")
            lines.append("")
            if b["reason"]:
                lines.append(f"- 理由：{b['reason']}")
            if b["judge_fallback"]:
                lines.append("- 标记：judge_fallback（兜底）")
            if b["empty_output"]:
                lines.append("- 标记：empty_output（空输出）")
            lines.append(f"- 回答：{b['answer'][:300]}")
            lines.append("")
    else:
        lines.append("（无 badcase）")

    report_path = round_dir / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return str(report_path)


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

    返回值与 ``summarize(..., extended=...)`` 合并进 summary 的 ``e2e`` 字典；
    ``token_usage_sample_count`` 用于标明 avg_token_usage 的实际样本分母。
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
        if j.get("judge_fallback"):
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
        "token_usage_sample_count": len(tokens),
    }


def _sample_actual_calls(out: dict | None) -> list[dict]:
    if not out:
        return []
    return (out.get("decision_trace") or {}).get("tool_calls") or []


def _tool_call_args(tool_calls: list[dict], tool: str) -> list[str]:
    """取出某工具的所有调用，归一为 args 的排序 JSON 列表（忽略 result/顺序）。"""
    return sorted(
        json.dumps(c.get("args", {}), sort_keys=True) for c in tool_calls if c.get("tool") == tool
    )


def compute_per_tool_metrics(outputs: list[dict], samples: list[dict]) -> dict:
    """按工具拆分调用情况。工具集合自动从「期望 ∪ 实际」推导，新增工具无需改动此函数。

    对每个工具 t（只统计声明了 expected_tool_calls 的样本）：
      expected   —— 期望调用 t 的样本数
      called     —— 实际调用 t 的样本数
      correct    —— 期望 t 的样本中，t 的实际调用（按 args）与期望调用完全一致
      accuracy   —— correct/expected（expected==0 时为 None，避免误导）
      unexpected —— 未期望却实际调用 t 的样本数（误用信号，例如 fetch_execution_context）
    """
    by_id = {s["id"]: s for s in samples}
    outs_by_id = {o.get("id"): o for o in outputs}
    tools: set[str] = set()
    for s in samples:
        for c in (s.get("expected_tool_calls") or []):
            tools.add(c.get("tool"))
    for o in outputs:
        for c in _sample_actual_calls(o):
            tools.add(c.get("tool"))

    result: dict[str, dict] = {}
    for t in sorted(tools):
        expected = correct = called = unexpected = 0
        for sid, s in by_id.items():
            exp = s.get("expected_tool_calls")
            if exp is None:
                continue  # 未声明期望工具的样本不参与，避免把正常调用误判为误用
            actual = _sample_actual_calls(outs_by_id.get(sid))
            norm_act = _tool_call_args(actual, t)
            exp_t = [c for c in exp if c.get("tool") == t]
            if norm_act:
                called += 1
            if exp_t:
                expected += 1
                if norm_act == _tool_call_args(exp, t):
                    correct += 1
            elif norm_act:
                unexpected += 1
        result[t] = {
            "expected": expected,
            "called": called,
            "correct": correct,
            "accuracy": round(correct / expected, 4) if expected else None,
            "unexpected": unexpected,
        }
    return result
