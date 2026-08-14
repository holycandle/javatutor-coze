# 评估系统 Review 日志

> 审查对象：`eval/` 评估系统实现
> 审查日期：2026-08-14
> 审查方式：代码阅读 + 本地测试执行

## 结论

评估系统实现与 spec/plan 一致，相关测试全部通过；当前可运行的评测为组件级（本地），端到端评测需在 Coze 平台执行。

## 验证结果

```text
uv run pytest tests/test_eval_component.py tests/test_eval_report.py tests/test_judge.py tests/test_samples_schema.py tests/test_intent_rules.py -v
=> 16 passed
```

样本集：`golden_set.jsonl` 6 条、`component_cases.jsonl` 5 条，Schema 校验通过。

## 发现

### P2：缺少统一 CLI 入口

- `component_metrics.py`、`e2e_runner.py`、`judge.py`、`report.py` 只有函数，没有可执行入口。
- 组件评测目前只能通过 pytest 或内联 Python 触发；端到端评测需要额外驱动脚本。
- 建议：后续在 `tools/`（非外壳 `scripts/`）增加 `eval_cli.py`，提供 `component / e2e / judge / report` 子命令。

### P2：critic_recall 是确定性代理而非真实 Critic

- `run_component_cases` 的 `critic` 用例用 `fact_matches` 判断回答是否缺失/错配硬事实，不等价于评审 LLM 的拦截能力。
- 作为组件级指标可接受，但报告与文档需明确标注“代理指标”。

### P2：黄金集规模不足

- 当前 6 条，低于 spec 目标 30-50 条。
- 建议在端到端基线建立前扩充到 30+ 条，覆盖 data_query/concept/debug/other/analyze/edge。

### P3：端到端评测依赖环境

- `e2e_runner.run_golden_set()` 依赖真实模型与数据库，本地暂不可跑；需在 Coze 平台执行后再用 `report.summarize()` 汇总。

## 当前可运行的评测与命令

### 组件级（本地）

```bash
cd javatutor-coze
uv run pytest tests/test_eval_component.py -v
```

全量评估相关测试：

```bash
uv run pytest tests/test_eval_component.py tests/test_eval_report.py tests/test_judge.py tests/test_samples_schema.py tests/test_intent_rules.py -v
```

### 端到端（Coze 平台）

- 在 Coze 平台执行 `eval/runner/e2e_runner.py` 的 `run_golden_set()` 产出回答；
- 再执行 `eval/runner/judge.py` 的 `judge_answer()` 逐条打分；
- 最后用 `eval/runner/report.py` 的 `summarize()` / `write_summary()` 归档。

## 后续行动

- 扩充黄金集至 30+ 条。
- 增加 `tools/eval_cli.py` CLI。
- 端到端首轮基线在 Coze 平台跑通后归档 `eval/archive/`。
