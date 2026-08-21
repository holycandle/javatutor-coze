# 2026-08-21 评估报告 Markdown 生成 Review

> 审查对象：javatutor-coze `feat/robust-eval-system`（已暂存）
> 对应计划：`docs/plan/2026-08-21-eval-report-md-plan.md`

## 结论

计划已按范围完成：`report` 命令现在会在 `summary.json` 同目录生成 `report.md`，包含轮次元信息、组件/e2e 指标表、与上一轮对比、badcase 列表；`summary.json` 保持不变。全量测试 133 passed。

发现 2 个 P3，不阻塞合入。

## Findings

### P3-1：model / commit 固定为 unknown

**位置**：`eval/runner/report.py` `write_report` 默认参数、`tools/eval_cli.py cmd_report`

`cmd_report` 调用 `write_report(...)` 时未传 `model` / `commit`，所以 `report.md` 里这两项恒为 `unknown`。计划目标要求记录模型与 commit。

建议：从 `config/agent_llm_config.json`（model）与 `git rev-parse --short HEAD`（commit）取真实值传入。

### P3-2：round-1 的 diff 是自身对比

**位置**：`tools/eval_cli.py cmd_report`

`prev_dir = round-{max(1, n-1)}`：当 `n=1` 时得到 `round-1`（自身），于是首轮 diff 全为 0，而不是“无上一轮数据”。`report.md` 因此显示错误的 `0.0`。

建议：`n<=1` 时跳过 diff，或让 `diff_vs_previous` 为空，由 `write_report` 走“（无上一轮数据）”分支。

## 验证

- `uv run pytest -q`：133 passed。
- 已生成 `eval/archive/2026-08-17/round-1/report.md`，并刷新 `summary.json`（`judge_fallback_rate=0.0645`、`empty_output_rate=0.0645`、`total=29`）。
- 本次 `report` 命令不消耗 Coze/DeepSeek 积分，符合“2、3 等积分”的边界。

## 遗留

- Round-1 重判与 Round-2 仍待积分到账后执行。
