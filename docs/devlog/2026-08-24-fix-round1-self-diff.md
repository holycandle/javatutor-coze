# 2026-08-24 修复首轮评估报告与自身对比

## 改动内容

执行 review `docs/reviews/2026-08-21-eval-report-md-review.md` 的 P3-2：`round-1` 的 `report` 命令会用 `round-{max(1, n-1)}` 指向自身，导致首轮 `diff_vs_previous` 恒为 0，而非「无上一轮数据」。

1. **`eval/runner/report.py`** 新增纯函数 `resolve_previous_summary(round_dir)`：
   - 解析轮次号 `n`，`n <= 1` 返回 `None`；
   - 上一轮 `summary.json` 不存在或读取失败返回 `None`；
   - 否则返回上一轮 summary 字典。

2. **`tools/eval_cli.py`** 的 `cmd_report` 改用 `resolve_previous_summary()`，仅在有上一轮数据时计算 `diff_vs_previous`；删除不再引用的 `_round_number`。

3. **`tests/test_eval_report.py`** 新增 3 个测试：首轮返回 None、第二轮正确读取上一轮、上一轮缺失返回 None。

## 验证结果

- 全量测试 `uv run pytest -q` → **137 passed**（新增 3）。
- `report` 命令实跑 `eval/archive/2026-08-17/round-1`：`diff_vs_previous` 为 `{}`，`report.md` 显示「（无上一轮数据）」。
- L5 外壳回归：无文件落入外壳路径。

## 遗留问题

- 无。P3-2 已闭合。
- 非标准轮次目录名（无法解析出 `n`）按首轮处理返回 `None`，与旧 `_round_number` 降级行为一致，属合理降级。
