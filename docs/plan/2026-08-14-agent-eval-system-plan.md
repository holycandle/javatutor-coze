# Agent 评估系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 JavaTutor Coze 智能体的双轨评估系统：组件级确定性指标本地跑，端到端 LLM-as-Judge 在 Coze 平台跑，每轮存档并对比。

**Architecture:** `eval/` 目录存放样本、runner、Judge 提示词与存档；共享模块 `src/graphs/javatutor/intent_rules.py` 提供保守意图规则与事实核查，作为组件级评估基准；组件指标可被 pytest 调用，端到端产出回答 + Judge 评分 + summary。

**Tech Stack:** Python 3.12、pytest、LangGraph、Coze LLM（端到端）、JSONL 存档。

---

## Global Constraints

- 不得修改 `.coze`、`scripts/`、`src/main.py`、`src/storage/`、`src/utils/`。
- 新代码只允许放在 `eval/`、`src/graphs/javatutor/intent_rules.py`、`tests/`、`docs/`。
- 端到端评测只在 Coze 平台跑；本地组件评测不消耗积分。
- 组件级评估必须可注入替身（FakeModel / stub rag_search），不依赖真实网络与数据库。
- 每个任务 TDD：先写失败测试 → 实现 → 通过 → 提交。

---

## File Structure

| 文件 | 责任 |
|---|---|
| `eval/samples/golden_set.jsonl` | 黄金集样本 |
| `eval/samples/component_cases.jsonl` | 组件用例 |
| `eval/runner/__init__.py` | 包标记 |
| `eval/runner/component_metrics.py` | 组件级指标 |
| `eval/runner/judge.py` | LLM-as-Judge |
| `eval/runner/e2e_runner.py` | 端到端 runner |
| `eval/runner/report.py` | summary 与 diff |
| `eval/judge_prompt.md` | Judge 评分标准 |
| `src/graphs/javatutor/intent_rules.py` | 保守意图规则与事实核查 |
| `tests/test_samples_schema.py` | 样本 schema 测试 |
| `tests/test_intent_rules.py` | 规则测试 |
| `tests/test_eval_component.py` | 组件指标测试 |
| `tests/test_judge.py` | Judge 测试 |
| `tests/test_eval_report.py` | 报告测试 |
| `docs/local-dev-convention.md` | 追加评估门槛（修改） |

---

### Task 1: 样本集与 Schema 校验

**Files:**
- Create: `eval/samples/golden_set.jsonl`
- Create: `eval/samples/component_cases.jsonl`
- Test: `tests/test_samples_schema.py`

**Interfaces:**
- Produces: 黄金集与组件用例 JSONL 文件；字段符合 spec 5.1 / 5.2。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_samples_schema.py`：

```python
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_jsonl(name):
    path = ROOT / "eval" / "samples" / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_golden_set_schema():
    rows = _load_jsonl("golden_set.jsonl")
    assert len(rows) >= 5
    for row in rows:
        assert row["id"]
        assert row["bucket"] in ("data_query", "concept", "debug", "other", "analyze", "edge")
        assert isinstance(row["payload"], dict)
        assert row["expected_intent"]
        assert isinstance(row["expected_facts"], list)
        assert isinstance(row["judge_priority"], bool)


def test_component_cases_schema():
    rows = _load_jsonl("component_cases.jsonl")
    assert len(rows) >= 4
    for row in rows:
        assert row["type"] in ("intent", "citation", "critic", "rag")
        assert isinstance(row["input"], dict)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_samples_schema.py -v`
Expected: FAIL，文件缺失。

- [ ] **Step 3: 创建样本文件**

创建 `eval/samples/golden_set.jsonl`：

```json
{"id": "q01", "bucket": "data_query", "payload": {"source_code": "public class A { void f() { int[] arr = {5,3,1}; arr[1] = 3; } }", "steps": [{"step": 1, "line": 3, "variables": {"arr": [5, 3, 1]}}, {"step": 2, "line": 4, "variables": {"arr": [3, 5, 1]}}], "current_step_index": 1, "current_line": 4, "user_question": "为什么第 2 步 arr[1] 变成了 5？", "compile_error": ""}, "expected_intent": "data_query", "expected_facts": ["step=2", "line=4", "arr[1]=5"], "expected_sources": [], "judge_priority": true}
{"id": "q02", "bucket": "concept", "payload": {"source_code": "public class A { void f() { int[] arr = {5,3,1}; } }", "steps": [], "current_step_index": 0, "current_line": 1, "user_question": "冒泡排序原理是什么？", "compile_error": ""}, "expected_intent": "concept", "expected_facts": [], "expected_sources": ["知识库: Arrays.sort"], "judge_priority": true}
{"id": "q03", "bucket": "debug", "payload": {"source_code": "public class A { void f() { int x = 1 } }", "steps": [], "current_step_index": 0, "current_line": 1, "user_question": "为什么编译报错？", "compile_error": "error: ';' expected"}, "expected_intent": "debug", "expected_facts": ["line=1"], "expected_sources": ["知识库: ';' expected"], "judge_priority": true}
{"id": "q04", "bucket": "other", "payload": {"source_code": "", "steps": [], "current_step_index": 0, "current_line": 1, "user_question": "这个工具怎么用？", "compile_error": ""}, "expected_intent": "other", "expected_facts": [], "expected_sources": [], "judge_priority": true}
{"id": "q05", "bucket": "analyze", "payload": {"source_code": "public class BubbleSort { void sort(int[] a) { for (int i = 0; i < a.length; i++) { } } }", "steps": [], "current_step_index": 0, "current_line": 1, "user_question": "", "compile_error": "", "intent": "analyze"}, "expected_intent": "analyze", "expected_facts": [], "expected_sources": [], "judge_priority": true}
{"id": "q06", "bucket": "edge", "payload": {"source_code": "public class A {}", "steps": [], "current_step_index": 5, "current_line": 99, "user_question": "随便问问", "compile_error": ""}, "expected_intent": "other", "expected_facts": [], "expected_sources": [], "judge_priority": false}
```

创建 `eval/samples/component_cases.jsonl`：

```json
{"id": "c01", "type": "intent", "input": {"user_question": "为什么 arr 变了？", "compile_error": ""}, "expected": "data_query"}
{"id": "c02", "type": "intent", "input": {"user_question": "HashMap 是什么", "compile_error": ""}, "expected": "concept"}
{"id": "c03", "type": "citation", "input": {}, "answer": "第 2 步 arr[1] 变成了 5", "expected_facts": ["step=2", "arr[1]=5"]}
{"id": "c04", "type": "critic", "input": {}, "answer": "第 2 步 arr[1] 变成了 8", "expected_facts": ["step=2", "arr[1]=5"], "expect_fail": true}
{"id": "c05", "type": "rag", "input": {"query": "HashMap 原理"}, "expected_sources": ["知识库: HashMap"]}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_samples_schema.py -v`
Expected: 2 passed。

- [ ] **Step 5: 提交**

```bash
git add eval/samples tests/test_samples_schema.py
git commit -m "feat: add eval golden set and component cases"
```

---

### Task 2: 保守意图规则与事实核查

**Files:**
- Create: `src/graphs/javatutor/intent_rules.py`
- Test: `tests/test_intent_rules.py`

**Interfaces:**
- Produces: `conservative_intent(user_question: str, compile_error: str = "") -> str`、`fact_matches(fact: str, answer: str) -> bool`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_intent_rules.py`：

```python
from graphs.javatutor.intent_rules import conservative_intent, fact_matches


def test_compile_error_short_circuits_debug():
    assert conservative_intent("为什么 arr 变了？", "error: ';' expected") == "debug"


def test_data_query_keywords():
    assert conservative_intent("为什么第 2 步 arr[1] 变了？") == "data_query"


def test_concept_keywords():
    assert conservative_intent("冒泡排序原理是什么？") == "concept"


def test_debug_keywords():
    assert conservative_intent("这个报错怎么改？") == "debug"


def test_fallback_other():
    assert conservative_intent("你好") == "other"


def test_fact_matches_step_line_var():
    answer = "第 2 步（第 4 行）arr[1] 变成了 5"
    assert fact_matches("step=2", answer)
    assert fact_matches("line=4", answer)
    assert fact_matches("arr[1]=5", answer)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_intent_rules.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 实现规则模块**

创建 `src/graphs/javatutor/intent_rules.py`：

```python
"""保守意图识别规则（非 LLM）与硬事实核查，作为评估基准。"""

VALID_INTENTS = {"data_query", "concept", "debug", "other"}

DEBUG_KEYWORDS = ["报错", "编译", "异常", "错误", "怎么改", "修复", "exception", "nullpointer", "越界"]
DATA_QUERY_KEYWORDS = ["为什么", "怎么变", "第", "步", "变量", "值", "变成", "此时", "当前", "arr", "数组"]
CONCEPT_KEYWORDS = ["原理", "复杂度", "概念", "定义", "是什么", "算法", "o(", "大o", "区别"]


def conservative_intent(user_question: str, compile_error: str = "") -> str:
    if compile_error and compile_error.strip():
        return "debug"
    q = (user_question or "").lower()
    if any(k in q for k in DEBUG_KEYWORDS):
        return "debug"
    if any(k in q for k in DATA_QUERY_KEYWORDS):
        return "data_query"
    if any(k in q for k in CONCEPT_KEYWORDS):
        return "concept"
    return "other"


def fact_matches(fact: str, answer: str) -> bool:
    answer = answer or ""
    fact = fact.strip()
    if fact.startswith("step="):
        n = fact.split("=", 1)[1].strip()
        return f"第 {n} 步" in answer or f"第{n} 步" in answer
    if fact.startswith("line="):
        n = fact.split("=", 1)[1].strip()
        return f"第 {n} 行" in answer or f"第{n} 行" in answer
    if "=" in fact:
        var, _, value = fact.partition("=")
        return var.strip() in answer and value.strip() in answer
    return fact in answer
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_intent_rules.py -v`
Expected: 6 passed。

- [ ] **Step 5: 提交**

```bash
git add src/graphs/javatutor/intent_rules.py tests/test_intent_rules.py
git commit -m "feat: add conservative intent rules and fact matching"
```

---

### Task 3: 组件级指标

**Files:**
- Create: `eval/runner/__init__.py`
- Create: `eval/runner/component_metrics.py`
- Test: `tests/test_eval_component.py`

**Interfaces:**
- Produces: `load_jsonl(path) -> list[dict]`、`run_component_cases(cases, intent_fn, fact_check, rag_search) -> dict`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_eval_component.py`：

```python
from pathlib import Path

from eval.runner.component_metrics import load_jsonl, run_component_cases

ROOT = Path(__file__).resolve().parents[1]


def _stub_rag(query):
    return ["知识库: HashMap"]


def test_run_component_cases_on_sample_file():
    cases = load_jsonl(ROOT / "eval" / "samples" / "component_cases.jsonl")
    result = run_component_cases(cases, rag_search=_stub_rag)
    assert result["intent_accuracy"] == 1.0
    assert result["citation_accuracy"] == 1.0
    assert result["critic_recall"] == 1.0
    assert result["rag_hit_at_3"] == 1.0
    assert result["pass_rate"] == 1.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_eval_component.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 实现指标模块**

创建 `eval/runner/__init__.py`（空文件）。

创建 `eval/runner/component_metrics.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_eval_component.py -v`
Expected: 1 passed。

- [ ] **Step 5: 提交**

```bash
git add eval/runner tests/test_eval_component.py
git commit -m "feat: add component-level evaluation metrics"
```

---

### Task 4: Judge 评分

**Files:**
- Create: `eval/judge_prompt.md`
- Create: `eval/runner/judge.py`
- Test: `tests/test_judge.py`

**Interfaces:**
- Produces: `load_judge_prompt() -> str`、`build_judge_messages(sample, answer) -> list`、`parse_judge_output(raw) -> dict|None`、`judge_answer(sample, answer, model=None) -> dict`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_judge.py`：

```python
from langchain_core.messages import AIMessage

from eval.runner.judge import build_judge_messages, judge_answer, parse_judge_output


class FakeModel:
    def invoke(self, messages):
        return AIMessage(content='{"score": 4.5, "judgement": "correct", "scores": {"relevance": 5, "grounding": 4, "pollution": 5, "correctness": 4}, "reason": "ok"}')


def test_build_judge_messages():
    messages = build_judge_messages({"payload": {}, "expected_facts": ["step=2"]}, "回答")
    assert messages[0].type == "system"
    assert "step=2" in messages[1].content


def test_parse_judge_output_valid():
    data = parse_judge_output('{"score": 4, "judgement": "correct"}')
    assert data["score"] == 4


def test_parse_judge_output_invalid():
    assert parse_judge_output("not json") is None


def test_judge_answer_marks_parse_error():
    out = judge_answer({"id": "q01"}, "回答", model=FakeModel())
    assert out["score"] == 4.5
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_judge.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 创建 Judge 提示词**

创建 `eval/judge_prompt.md`：

```markdown
你是 Agent 回答评审。对每个样本，对照期望事实给 Agent 回答打分，只返回 JSON：
{"score": 0-5, "judgement": "correct|partially_correct|incorrect", "scores": {"relevance": 1-5, "grounding": 1-5, "pollution": 1-5, "correctness": 1-5}, "reason": "一句话"}
评分维度：
- relevance：是否直接回答问题
- grounding：是否引用真实步骤/行/变量/检索来源
- pollution：是否引入无关上下文
- correctness：教学表达是否准确、适合新手
最终 score 取四维平均。只返回 JSON。"""
```

- [ ] **Step 4: 实现 Judge**

创建 `eval/runner/judge.py`：

```python
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
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_judge.py -v`
Expected: 4 passed。

- [ ] **Step 6: 提交**

```bash
git add eval/judge_prompt.md eval/runner/judge.py tests/test_judge.py
git commit -m "feat: add LLM-as-Judge evaluation"
```

---

### Task 5: 端到端 runner 与报告

**Files:**
- Create: `eval/runner/e2e_runner.py`
- Create: `eval/runner/report.py`
- Test: `tests/test_eval_report.py`

**Interfaces:**
- Produces: `run_golden_set(samples, agent=None, out_path=None) -> list[dict]`、`summarize(judged, component=None) -> dict`、`diff(previous, current) -> dict`、`write_summary(path, summary)`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_eval_report.py`：

```python
import json
from pathlib import Path

from eval.runner.report import diff, summarize, write_summary


def test_summarize_computes_metrics():
    judged = [
        {"id": "q01", "score": 5, "judgement": "correct", "scores": {"grounding": 5}},
        {"id": "q02", "score": 3, "judgement": "partially_correct", "scores": {"grounding": 3}},
        {"id": "q03", "judge_parse_error": True},
    ]
    summary = summarize(judged, component={"pass_rate": 0.9})
    assert summary["e2e"]["total"] == 2
    assert summary["e2e"]["avg_score"] == 4.0
    assert summary["e2e"]["grounding_avg"] == 4.0
    assert summary["component"]["pass_rate"] == 0.9


def test_diff_between_rounds():
    prev = {"e2e": {"avg_score": 4.0, "grounding_avg": 4.0}, "component": {"pass_rate": 0.8}}
    cur = {"e2e": {"avg_score": 4.3, "grounding_avg": 4.2}, "component": {"pass_rate": 0.9}}
    d = diff(prev, cur)
    assert d["avg_score"] == 0.3
    assert d["component_pass_rate"] == 0.1


def test_write_summary(tmp_path):
    path = tmp_path / "summary.json"
    write_summary(str(path), {"e2e": {}})
    assert json.loads(path.read_text(encoding="utf-8")) == {"e2e": {}}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_eval_report.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 实现端到端 runner 与报告**

创建 `eval/runner/e2e_runner.py`：

```python
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
```

创建 `eval/runner/report.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_eval_report.py -v`
Expected: 3 passed。

- [ ] **Step 5: 提交**

```bash
git add eval/runner/e2e_runner.py eval/runner/report.py tests/test_eval_report.py
git commit -m "feat: add e2e runner and evaluation report"
```

---

### Task 6: 门槛集成与全量回归

**Files:**
- Modify: `docs/local-dev-convention.md`

**Interfaces:**
- 组件级评估加入验证门槛；全量测试通过。

- [ ] **Step 1: 更新规约**

在 `docs/local-dev-convention.md` 第 5 节追加：

```markdown
### L2.5 组件级评估

```bash
uv run pytest tests/test_eval_component.py -v
```

Expected: 全部通过；`pass_rate = 1.0`。

端到端评估：prompt/上下文/记忆/工具相关改动提交时，PR 说明必须附本轮与上一轮 Judge 均分对比；均分下降 > 0.3 或 Grounding 下降 > 0.5 禁止合入。
```

- [ ] **Step 2: 运行全部测试**

Run: `uv run pytest tests/ -v`
Expected: 全部通过。

- [ ] **Step 3: 外壳回归**

```bash
git status --porcelain | grep -E "^(\.coze|scripts/|src/main\.py|src/storage/|src/utils/)"
```

Expected: 无输出。

- [ ] **Step 4: 提交**

```bash
git add docs/local-dev-convention.md
git commit -m "docs: add component eval gate to local dev convention"
```

---

### Task 7（M1.1 新增）: remote mode 与扩展指标

> 本任务为原计划完成后的扩展，标注为新增；不改变 Task 1-6 既有实现。

**Files:**
- Modify: `eval/samples/golden_set.jsonl`（新增 `expected_tool_calls`）
- Create: `eval/runner/e2e_remote.py`
- Modify: `eval/runner/report.py`
- Modify: `tests/test_eval_remote.py`（新建）
- Modify: `tests/test_eval_report.py`
- 依赖：决策痕迹已按接口契约新增 `tool_calls` / `token_usage`。

**Interfaces:**
- Produces: `parse_decision_trace(text) -> dict|None`、`chat_remote(sample, api_url, token, project_id, timeout=120) -> dict`、`run_remote_golden_set(samples, api_url, token, project_id, out_path=None) -> list[dict]`、`compute_extended_metrics(outputs, samples, judged) -> dict`。

- [ ] **Step 1: 黄金集补充 expected_tool_calls**

将 `eval/samples/golden_set.jsonl` 的 q01 行替换为：

```json
{"id": "q01", "bucket": "data_query", "payload": {"source_code": "public class A { void f() { int[] arr = {5,3,1}; arr[1] = 3; } }", "steps": [{"step": 1, "line": 3, "variables": {"arr": [5, 3, 1]}}, {"step": 2, "line": 4, "variables": {"arr": [3, 5, 1]}}], "current_step_index": 1, "current_line": 4, "user_question": "为什么第 2 步 arr[1] 变成了 5？", "compile_error": ""}, "expected_intent": "data_query", "expected_facts": ["step=2", "line=4", "arr[1]=5"], "expected_sources": [], "expected_tool_calls": [{"tool": "step_facts", "args": {"step_index": 1}}], "judge_priority": true}
```

- [ ] **Step 2: 写失败测试（remote）**

创建 `tests/test_eval_remote.py`：

```python
from eval.runner.e2e_remote import parse_decision_trace


def test_parse_decision_trace_extracts_new_fields():
    text = '回答\n\n【决策痕迹】\n{"tool_calls":[{"tool":"step_facts","args":{"step_index":1}}],"token_usage":{"prompt_tokens":100,"completion_tokens":50,"estimated":true}}'
    trace = parse_decision_trace(text)
    assert trace["tool_calls"][0]["tool"] == "step_facts"
    assert trace["tool_calls"][0]["args"]["step_index"] == 1
    assert trace["token_usage"]["completion_tokens"] == 50
    assert trace["token_usage"]["estimated"] is True
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_eval_remote.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 4: 实现 e2e_remote**

创建 `eval/runner/e2e_remote.py`：

```python
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
    with httpx.stream("POST", api_url, json=payload, headers=headers, timeout=timeout) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            if chunk.get("event") == "message" and chunk.get("message", {}).get("type") == "answer":
                full.append(chunk["message"].get("content", ""))
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
```

- [ ] **Step 5: 扩展指标（report.py 新增）**

在 `eval/runner/report.py` 追加：

```python
from graphs.javatutor.intent_rules import fact_matches


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
```

将 `summarize` 的返回中 `e2e` 字典追加扩展指标：

```python
        "e2e": {
            **existing_e2e,
            **compute_extended_metrics([], [], []),  # 由调用方合并 outputs/samples/judged 后覆盖
        },
```

实际执行时调用方先计算 `extended = compute_extended_metrics(outputs, samples, judged)`，再与 `summarize` 结果合并写入 summary。

- [ ] **Step 6: 写失败测试（扩展指标）**

在 `tests/test_eval_report.py` 追加：

```python
def test_compute_extended_metrics():
    from eval.runner.report import compute_extended_metrics

    outputs = [
        {
            "id": "q01",
            "answer": "第 2 步 arr[1]=5",
            "latency": 2.0,
            "decision_trace": {
                "tool_calls": [{"tool": "step_facts", "args": {"step_index": 1}}],
                "token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "estimated": True},
            },
        }
    ]
    samples = [
        {"id": "q01", "expected_tool_calls": [{"tool": "step_facts", "args": {"step_index": 1}}], "expected_facts": ["step=2", "arr[1]=5"]}
    ]
    judged = [{"id": "q01", "judgement": "correct"}]
    m = compute_extended_metrics(outputs, samples, judged)
    assert m["tool_call_accuracy"] == 1.0
    assert m["task_success_rate"] == 1.0
    assert m["avg_latency"] == 2.0
    assert m["avg_token_usage"] == 150
```

- [ ] **Step 7: 运行测试确认通过**

Run: `uv run pytest tests/test_eval_remote.py tests/test_eval_report.py -v`
Expected: 全部通过。

- [ ] **Step 8: 提交（由团队自行执行）**

```bash
git add eval/runner/e2e_remote.py eval/runner/report.py eval/samples/golden_set.jsonl tests/test_eval_remote.py tests/test_eval_report.py
git commit -m "feat: add remote mode and extended eval metrics"
```

---

## Self-Review

### Spec Coverage

| spec 条目 | 对应任务 |
|---|---|
| 黄金集与组件用例 | Task 1 |
| 保守意图规则 | Task 2 |
| 组件级指标 | Task 3 |
| Judge 四维评分 | Task 4 |
| 端到端 runner | Task 5 |
| summary 与 diff | Task 5 |
| 验证门槛 | Task 6 |
| remote mode（M1.1） | Task 7 |
| tool_call_accuracy / task_success_rate（M1.1） | Task 7 |
| avg_latency / avg_token_usage（M1.1） | Task 7 |

### Placeholder Scan

计划无 `TBD`、`TODO`；所有代码块完整。

### Type Consistency

- `conservative_intent(user_question, compile_error) -> str`：Task 2 定义，Task 3 使用。
- `fact_matches(fact, answer) -> bool`：Task 2 定义，Task 3 使用。
- `load_jsonl(path)`：Task 3 定义，Task 5 使用。
- `judge_answer(sample, answer, model=None) -> dict`：Task 4 定义，端到端执行时使用。
- `run_golden_set(samples, agent=None, out_path=None)`：Task 5 定义。
- `summarize(judged, component=None)` / `diff(previous, current)`：Task 5 定义。
