# 2026-08-18 Judge 结构化输出与兜底率指标计划

> 执行仓库：`javatutor-coze`
> 执行方式：交给 Claude Code 按本计划逐任务执行。

## 背景

Judge 已具备 JSON mode、容错提取、重试与确定性兜底。但兜底仍是“隐身在 incorrect 里”，不易发现解析质量退化；同时 `response_format=json_object` 只约束“是 JSON”，不约束字段/枚举。

目标：

1. 从结构上减少 Judge 解析失败。
2. 把 `judge_fallback_rate` / `empty_output_rate` 显式化，进入 report。

## Task 1: Judge 输出结构化加固

**Files:**
- Modify: `eval/runner/judge.py`
- Modify: `eval/judge_prompt.md`

- [ ] **Step 1: 尽量启用 JSON Schema**

`judge_complete` 的 `response_format` 优先使用：

```python
{"type": "json_schema", "json_schema": {
    "name": "judge_result",
    "schema": {
        "type": "object",
        "properties": {
            "score": {"type": "number", "minimum": 0, "maximum": 5},
            "judgement": {"type": "string", "enum": ["correct", "partially_correct", "incorrect"]},
            "scores": {
                "type": "object",
                "properties": {
                    "relevance": {"type": "number", "minimum": 0, "maximum": 5},
                    "grounding": {"type": "number", "minimum": 0, "maximum": 5},
                    "pollution": {"type": "number", "minimum": 0, "maximum": 5},
                    "correctness": {"type": "number", "minimum": 0, "maximum": 5}
                },
                "required": ["relevance", "grounding", "pollution", "correctness"]
            },
            "reason": {"type": "string"}
        },
        "required": ["score", "judgement", "scores", "reason"]
    }
}}
```

若 `JUDGE_API_URL` 不支持 `json_schema`，则回退到 `json_object`，并由 `_normalize_parsed` 继续做字段校验。

- [ ] **Step 2: 保留容错与兜底**

不删除 `_strip_fences` / `_extract_json_object` / 重试 / `judge_fallback`；它们作为第二道保险。

- [ ] **Step 3: 测试**

`tests/test_judge.py` 增加 shape 校验用例：字段缺失、枚举非法、score 超范围均被归一化。

## Task 2: Report 增加兜底率指标

**Files:**
- Modify: `eval/runner/report.py`
- Modify: `tests/test_eval_report.py`

- [ ] **Step 1: summarize 统计**

在 `e2e` 中增加：

```python
"judge_fallback_rate": _safe(sum(1 for j in judged if j.get("judge_fallback")), len(judged)),
"empty_output_rate": _safe(sum(1 for j in judged if j.get("empty_output")), len(judged)),
```

- [ ] **Step 2: 测试**

断言含 fallback 行时两个指标正确计算。

## Task 3: 重判 Round-1 并出报告

```bash
uv run python tools/eval_cli.py --round-dir eval/archive/2026-08-17/round-1 judge
uv run python tools/eval_cli.py --round-dir eval/archive/2026-08-17/round-1 report
```

Expected：`judge_fallback_rate` 接近 0；若仍大于 0，按 `raw_judge_output` 归因。

## Task 4: 人工复核接入导出

**Files:**
- Modify: `tools/export_training_data.py`

- [ ] **Step 1: 过滤 rejected**

读取 `round_dir/human_review.jsonl`；SFT/DPO 导出跳过 `verdict == "reject"` 的样本。

- [ ] **Step 2: README 提示**

输出 README 注明“已按 human_review 过滤 reject”。

## 验证

- `uv run pytest -q` 全绿。
- 更新 `AGENT.md` 登记本计划。

## Self-Review

### Spec Coverage

| 需求 | 对应任务 |
|---|---|
| Judge 结构化输出 | Task 1 |
| 兜底率指标 | Task 2 |
| Round-1 重判 | Task 3 |
| 人工复核生效 | Task 4 |

### Placeholder Scan

计划无 `TBD`、`TODO`；所有代码块完整。
