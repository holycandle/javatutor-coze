# 2026-08-17 Judge 解析修复与 Round-2 评估计划

> 执行仓库：`javatutor-coze`（分支 `feat/agent-architecture-improve`）+ `JavaTutor`（部署用）
> 执行方式：交给 Claude Code 按本计划逐任务执行。

## 背景

2026-08-17 已跑完第一轮完整评估（`eval/archive/2026-08-17/round-1/`）：

- 组件级：intent_accuracy 1.0、citation_accuracy 1.0、critic_recall 1.0、rag_hit_at_3 0.0（本地 mock 空检索，符合预期）、pass_rate 0.8。
- 端到端：31 条黄金集回答完成；Judge 仅 6 条成功解析（25 条 `judge_parse_error: true`）；avg_score 3.75、grounding 3.5、task_success_rate 0.33、tool_call_accuracy 0.48、avg_latency 16.6s、avg_token_usage 1550。

当前结论不可靠：Judge 解析成功率只有 6/31，需要先修解析再重判。

## 根因

`eval/runner/judge.py`：

- `parse_judge_output` 只接受“整体是 JSON 或整体被代码块包裹”的文本；DeepSeek 一旦在 JSON 前后附加解释文字就解析失败。
- 未保存原始 Judge 输出，失败时看不到模型到底回了什么，难以调试。
- 无重试机制。

`eval/judge_prompt.md` 要求“只返回 JSON”，但未禁止 markdown 代码块，也未约束“不要附加解释”。

## Task 0: 每轮生成 Markdown 报告

**Files:**
- Modify: `eval/runner/report.py`
- Modify: `tests/test_report.py`（若无则新建）

### Step 1: 扩展 report.py

在写 `summary.json` 的同时生成 `report.md`，内容包含：

- 头部：`date`、`commit`、`model`、`round`。
- 组件级指标表。
- 端到端指标表：`avg_score`、`grounding_avg`、`tool_call_accuracy`、`task_success_rate`、`avg_latency`、`avg_token_usage`。
- `diff_vs_previous` 表。
- badcase 列表：`judged.jsonl` 中 `score <= 2` 或 `grounding <= 2` 的条目，含 `id`、`judgement`、`reason`、回答前 300 字。

保留 `summary.json` 作为机器可读层，`report.md` 仅供人读。

### Step 2: 测试

`tests/test_report.py` 断言：

- `report.md` 存在且包含 `e2e` 与 `badcase` 关键段。
- 无 judged 数据时不崩溃、生成空报告。

Run：`uv run pytest tests/test_report.py -q`。

## Task 1: 加固 Judge 解析

**Files:**
- Modify: `javatutor-coze/eval/runner/judge.py`
- Modify: `javatutor-coze/eval/judge_prompt.md`
- Modify: `javatutor-coze/tests/test_judge.py`（若无则新建）

### Step 1: 容错解析

`parse_judge_output` 改为：

1. 去除首尾空白与 markdown 代码块（```` ```json ```` / ```` ``` ````）。
2. 在剩余文本中取第一个 `{` 到最后一个 `}` 的子串再 `json.loads`。
3. `score` 接受数字或数字字符串；`scores` 缺失时补默认 0；`judgement` 非枚举值时归为 `incorrect`。
4. 全部失败返回 `None`。

### Step 2: 保存原始输出

`judge_answer` 无论成败都把 `raw_judge_output` 写入返回 dict，便于排查。

### Step 3: 单次重试

解析失败时以 `temperature=0` 重试一次；仍失败才标记 `judge_parse_error: true`。

### Step 4: Prompt 约束

`judge_prompt.md` 追加：

```text
禁止使用 markdown 代码块，禁止在 JSON 前后添加任何解释文字。
```

### Step 5: 测试

`tests/test_judge.py` 覆盖：纯 JSON、fenced JSON、前置解释 + JSON、JSON + 尾部解释、数字字符串 score、非法输出返回 None。

Run：`uv run pytest tests/test_judge.py -q`。

## Task 2: 重判 Round-1

- [ ] **Step 1: 重跑 Judge**

`javatutor-coze`：

```bash
uv run python tools/eval_cli.py --round-dir eval/archive/2026-08-17/round-1 judge
```

Expected：`judge_parse_error` 明显下降；`judged.jsonl` 保留 `raw_judge_output`。

- [ ] **Step 2: 重出报告**

```bash
uv run python tools/eval_cli.py --round-dir eval/archive/2026-08-17/round-1 report
```

Expected：`summary.json` 的 e2e.total 接近 31，score/grounding 可信任。

- [ ] **Step 3: 记录结论**

把修复前后对比写入该轮 devlog 或 `docs/reviews/2026-08-17-judge-parser-fix-review.md`。

## Task 3: 部署最新提示词并跑 Round-2

- [ ] **Step 1: 部署**

部署 `javatutor-coze` 最新代码（含“data_query 必须先调用 step_facts”提示词与 `latency_ms` 修复）。

- [ ] **Step 2: 跑 Round-2**

```bash
uv run python tools/eval_cli.py --round-dir eval/archive/2026-08-17/round-2 e2e
uv run python tools/eval_cli.py --round-dir eval/archive/2026-08-17/round-2 judge
uv run python tools/eval_cli.py --round-dir eval/archive/2026-08-17/round-2 report
```

Expected：tool_call_accuracy 显著高于 0.48；avg_latency 记录为有效值；grounding 不低于 3.0。

- [ ] **Step 3: 对比**

检查 `summary.json` 的 `diff_vs_previous`；若 grounding 下降超过 0.5 或均分下降超过 0.3，按评估门槛标记阻塞。

## Task 4: 回归与文档

- [ ] `uv run pytest -q` 全绿。
- [ ] 更新 `AGENT.md` 登记本计划与相关 devlog/review。
- [ ] 提交前检查无硬编码密钥；提交按用户约定执行。

## Self-Review

### Spec Coverage

| 需求 | 对应任务 |
|---|---|
| Judge 解析可靠 | Task 1 |
| Round-1 重判 | Task 2 |
| 最新提示词 Round-2 对比 | Task 3 |
| 回归与文档 | Task 4 |

### Placeholder Scan

计划无 `TBD`、`TODO`；所有代码块完整。
