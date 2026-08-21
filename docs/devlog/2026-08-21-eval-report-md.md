# 2026-08-21 评估报告 Markdown 生成

## 改动内容

执行计划 `docs/plan/2026-08-21-eval-report-md-plan.md`，为评测补一份人读 Markdown 报告（原只有机器可读 `summary.json`）。

1. **`eval/runner/report.py`** 新增 `write_report(path, summary, judged, outputs, samples, model="unknown", commit="unknown")` 与辅助 `_collect_badcases`：
   - 轮次元信息：日期/轮次从 round 目录推断，模型/commit 默认 `unknown`。
   - 组件级指标表、端到端指标表（按 `_E2E_METRIC_ORDER` 输出）、`diff_vs_previous` 表。
   - badcase 列表：判定 `judge_fallback`、`score<=2` 或 `grounding<=2`，含 id/judgement/reason/回答前 300 字，并标注兜底/空输出标记。

2. **`tools/eval_cli.py`** 的 `cmd_report` 在写 `summary.json` 后调用 `write_report`，打印 `report -> <path>`。

3. **`tests/test_eval_report.py`** 新增 3 个测试：报告含「端到端指标」「Badcase」段落、fallback 条目含兜底标记、无 judged 时不崩溃。

## 验证结果

- 全量测试 `uv run pytest -q` → **133 passed**（新增 3）。
- 端到端实跑：`report` 命令在 `eval/archive/2026-08-17/round-1/` 生成 `report.md`，含 12 条 badcase（其中 q12/q15 正确标注 judge_fallback + empty_output）。

## 遗留问题

- 模型/commit 元信息默认 `unknown`（`cmd_report` 不涉及被测模型名与 git commit，未来可由 `e2e` 阶段写入 answers 元数据后回填）。
- `diff_vs_previous` 依赖 `_round_number` 计算上一轮目录，`round-1` 会指向自身导致 diff 恒 0；属既有逻辑，不在本计划范围。
- badcase 判定用 `grounding<=2` 会纳入部分 `score=3.0` 但 grounding 偏低的条目（如 q04/q24），符合计划定义。
