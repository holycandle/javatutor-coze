"""确定性 grounding 核对器（业务侧实现，供运行时与评估共用一个口径）。

与 ``intent_rules.fact_matches`` 互补：
- ``fact_matches`` 正向检查「期望事实是否出现在回答里」；
- 本核对器反向检查「回答里的步骤号 / 行号 / 堆对象 id 引用是否在 steps 数据中真实存在」，
  即反幻觉核对，直接对应领域本体 ``data_contract_rules`` 的第 1、2 条。

仅当样本提供非空 ``steps`` 时 applicable；变量值的语义对错（如把 arr[1]=3 解释成 5）
不在此范围，仍由 Judge 的语义 grounding 负责。
"""

import re
from typing import Any

STEP_REF = re.compile(r"第\s*(\d+)\s*步")
LINE_REF = re.compile(r"第\s*(\d+)\s*行")
# 堆对象 id 约定形如 h1 / h2（见 steps[i].heap 的 key）
HEAP_ID = re.compile(r"\bh(\d+)\b")


def _extract_ints(pattern: re.Pattern, text: str) -> list[int]:
    return [int(m.group(1)) for m in pattern.finditer(text or "")]


def _payload(sample: dict[str, Any]) -> dict[str, Any]:
    """兼容 sample 为黄金集条目（含 payload）或直接为 payload 两种形状。"""
    p = sample.get("payload")
    return p if isinstance(p, dict) else sample


def verify_grounding(sample: dict[str, Any], answer: str) -> dict[str, Any]:
    """核对单个样本回答的引用真实性（结构引用反幻觉）。

    返回结构化结果：applicable / checked / violations / hallucinated / step_refs /
    line_refs / heap_refs / grounding_ok。无 steps 时 applicable=False，不判罚。
    """
    payload = _payload(sample)
    steps = payload.get("steps") or []
    if not steps:
        return {
            "applicable": False,
            "checked": 0,
            "violations": 0,
            "hallucinated": [],
            "step_refs": [],
            "line_refs": [],
            "heap_refs": [],
            "grounding_ok": True,
        }

    source_lines = len((payload.get("source_code") or "").splitlines())
    heap_keys: set[str] = set()
    legal_lines: set[int] = set()
    for s in steps:
        heap_keys.update((s.get("heap") or {}).keys())
        if s.get("line") is not None:
            try:
                legal_lines.add(int(s["line"]))
            except (TypeError, ValueError):
                pass

    step_refs: list[dict] = []
    line_refs: list[dict] = []
    heap_refs: list[dict] = []
    hallucinated: list[str] = []

    max_step = len(steps)  # 展示 +1 后合法步数范围 1..len(steps)
    for n in _extract_ints(STEP_REF, answer):
        ok = 1 <= n <= max_step
        step_refs.append({"value": n, "ok": ok})
        if not ok:
            hallucinated.append(f"步骤 {n} 超出 steps 范围 1..{max_step}")

    # 行号合法性对照 steps 数据的 line 字段集合（源码在样本中可能被压缩为单行，
    # 物理行数不可靠）；steps 未提供 line 字段时不对行号核对。
    if legal_lines:
        for n in _extract_ints(LINE_REF, answer):
            ok = n in legal_lines
            line_refs.append({"value": n, "ok": ok})
            if not ok:
                hallucinated.append(f"行号 {n} 不在步骤数据 line 集合 {sorted(legal_lines)} 中")

    # 仅当样本确有堆数据时核对堆对象 id，避免把源码变量名 h1 误判为堆引用
    if heap_keys:
        for n in _extract_ints(HEAP_ID, answer):
            ok = f"h{n}" in heap_keys
            heap_refs.append({"value": f"h{n}", "ok": ok})
            if not ok:
                hallucinated.append(f"堆对象 h{n} 不在 heap 快照 {sorted(heap_keys)} 中")

    checked = len(step_refs) + len(line_refs) + len(heap_refs)
    violations = len(hallucinated)
    return {
        "applicable": True,
        "checked": checked,
        "violations": violations,
        "hallucinated": hallucinated,
        "step_refs": step_refs,
        "line_refs": line_refs,
        "heap_refs": heap_refs,
        "grounding_ok": violations == 0,
    }


def _safe(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def compute_grounding_verify(outputs: list[dict], samples: list[dict]) -> dict[str, Any]:
    """聚合确定性 grounding 核对指标，供 report 与 Judge grounding 交叉对照。

    accuracy = 无违规样本数 / applicable 样本数（applicable 指样本含非空 steps）。
    """
    by_id = {s["id"]: s for s in samples}
    applicable = clean_samples = violations = checked = 0
    for out in outputs:
        sample = by_id.get(out.get("id"), {})
        result = verify_grounding(sample, out.get("answer", ""))
        if result["applicable"]:
            applicable += 1
            checked += result["checked"]
            if result["violations"] == 0:
                clean_samples += 1
            else:
                violations += result["violations"]
    return {
        "grounding_verify_applicable": applicable,
        "grounding_verify_checked": checked,
        "grounding_verify_violations": violations,
        "grounding_verify_accuracy": _safe(clean_samples, applicable),
    }
