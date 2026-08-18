# Judge 解析修复 Review 日志

> 对应 plan：`docs/plan/2026-08-17-judge-parser-fix-and-round2-plan.md` Task 1-2
> 执行日期：2026-08-17

## 结论

Judge 解析问题已修复，Round-1 重判解析成功 **6/31 → 29/31**。修复分两步：

1. **容错解析**（Task 1）：容错 JSON 解析 + 原始输出保存 + Prompt 约束，6/31 → 12/31。
2. **重试升级**（Task 1 追加，用户确认配额充足）：空/截断输出重试最多 3 次 + 短退避 + `empty_output` 标记，12/31 → **29/31**。

最终 29 条可判结果才可信：**avg_score 3.40、grounding 2.79**。此前 12 条快照的 4.23/3.92 是「好解析的样本自我选择」造成的虚高——全量判定后数值显著回落，这是本修复最重要的收获。

## 修复内容

### Step A：容错解析（Task 1）

- `eval/runner/judge.py`：`parse_judge_output` 依次尝试「整体解析」与「取首个 `{` 到最后一个 `}` 子串解析」；`score` 接受数字/数字字符串；`scores` 缺失维度补默认 0；`judgement` 非枚举值归 `incorrect`。
- `judge_answer` 无论成败都写入 `raw_judge_output`。
- `eval/judge_prompt.md` 追加「禁止 markdown 代码块、禁止 JSON 前后解释文字」。
- `tests/test_judge.py` 4 → 12 用例。

### Step B：重试升级（追加）

- `MAX_ATTEMPTS = 3`；解析失败/空返回时以 `temperature=0` 重试，真实调用每次重试前退避 `RETRY_BACKOFF_SECONDS`（1s、2s）。
- 最终失败且输出为空串时额外标记 `empty_output: True`，便于统计 API 空返回。
- 记录 `attempts`（实际尝试次数），日志输出每次失败的原始片段。
- `tests/test_judge.py` 12 → 14 用例：空返回 3 次 + `empty_output` 标记、真实调用退避递增断言。

## 复验

| 项 | 结果 |
|---|---|
| `uv run pytest tests/test_judge.py -q` | ✅ 14 passed |
| `uv run pytest tests/ -q` | ✅ 118 passed |
| `uv run python tools/eval_cli.py judge --round-dir eval/archive/2026-08-17/round-1` | ✅ 31 条，`raw_judge_output` 全覆盖 |
| `uv run python tools/eval_cli.py report --round-dir eval/archive/2026-08-17/round-1` | ✅ summary.json 更新 |

## Round-1 重判对比（三次快照）

| 指标 | 修复前(6条) | 容错解析后(12条) | 重试升级后(29条) |
|---|---|---|---|
| 解析成功 | 6 / 31 | 12 / 31 | **29 / 31** |
| avg_score | 3.75 | 4.23 | **3.40** |
| grounding_avg | 3.5 | 3.92 | **2.79** |
| correct / partially / incorrect | 4 / 0 / 2 | 9 / 2 / 1 | 12 / 13 / 4 |
| task_success_rate | 0.33 | 0.42 | 0.24 |

attempts 分布：1 次成功 16 条、2 次成功 10 条、3 次成功 3 条 → **重试恢复了 17 条**（12 → 29）。

## 关键发现：失败主因是 API 空返回而非解析

`raw_judge_output` 让失败原因首次可见：

- 空返回随机散布（`EE.E.EEEEETEE...`），非连续限流块、与回答长度无相关性。
- 重试升级后仅剩 **2 条失败**：`q01`、`q26`，3 次尝试均为空返回（`empty_output=True`）——端点对这两条内容持续空响应，与解析无关。
- 结论：Round-1 历史「25/31 解析失败」绝大部分是 API 空返回，模型「JSON 前后附加解释文字」只是次要因素。

## 对 Round-2 的含义

- 29/31 的可判样本已足够支撑 tool_call_accuracy / grounding 统计，**Round-2 可直接开跑**。
- grounding 2.79 < 3.0，按 plan Task 3 门槛（grounding ≥ 3.0）视为待改进信号，Round-2 需观察是否回升。
- 若 Round-2 空返回复发，可在 `cmd_judge` 循环间复用现有退避，或对持续空返回的样本单独告警。

## 文档登记

- 本 review 已在 `AGENT.md` 登记。
- 对应 plan：`docs/plan/2026-08-17-judge-parser-fix-and-round2-plan.md`。
