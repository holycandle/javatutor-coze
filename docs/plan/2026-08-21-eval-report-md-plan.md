# 2026-08-21 评估报告 Markdown 生成计划

> 执行仓库：`javatutor-coze`
> 执行方式：交给 Claude Code 按本计划逐任务执行。
> 范围：只做 Markdown 报告生成；不重跑 judge/report，不跑 round-2（等积分到账）。

## 背景

评估结果目前只有机器可读的 `summary.json`，缺一份给人看/做汇报的 Markdown 报告。DevAgent 的做法是 JSONL（原始）+ Markdown（人读）两层，我们补齐后者。

## 目标

`report` 命令在写 `summary.json` 的同时生成同目录 `report.md`：

- 轮次元信息：date、round、模型、commit。
- 组件级指标表。
- 端到端指标表：avg_score / grounding_avg / correct/partially/incorrect / tool_call_accuracy / task_success_rate / avg_latency / avg_token_usage / judge_fallback_rate / empty_output_rate。
- `diff_vs_previous` 表。
- badcase 列表：judged 中 `judge_fallback=true`、`score<=2` 或 `grounding<=2` 的条目，含 id、judgement、reason、回答前 300 字。

保持 `summary.json` 不变，`report.md` 只作人读层。

## Task 1: report.py 增加 Markdown 写入

**Files:**
- Modify: `eval/runner/report.py`

- [ ] **Step 1: 新增 `write_report`**

函数签名：

```python
def write_report(path, summary, judged, outputs, samples, model="unknown", commit="unknown"):
    """在 summary.json 同目录写 report.md（人读报告）。"""
```

内容与上文「目标」一致。日期/轮次从 `path`（round 目录）推断。

- [ ] **Step 2: 保留 summary**

不修改 `write_summary`；`report` 命令同时调用两个写入函数。

## Task 2: eval_cli 接入

**Files:**
- Modify: `tools/eval_cli.py`

- [ ] **Step 1: cmd_report 调用 write_report**

在 `cmd_report` 写 `summary.json` 后调用 `write_report`，传入 judged、outputs、samples。

## Task 3: 测试

**Files:**
- Modify: `tests/test_eval_report.py`

- [ ] **Step 1: 覆盖断言**

- 有 judged 时 `report.md` 存在且含「e2e」「badcase」段落。
- 含 `judge_fallback` 时出现兜底条目。
- 无 judged 时生成空报告、不崩溃。

Run：`uv run pytest tests/test_eval_report.py -q`。

## Task 4: 文档

- [ ] `AGENT.md` 登记本计划。
- [ ] 完成后写 devlog `docs/devlog/2026-08-21-eval-report-md.md` 并登记。
- [ ] 不主动提交（遵循用户 git 约束）。

## Self-Review

### Spec Coverage

| 需求 | 对应任务 |
|---|---|
| Markdown 报告生成 | Task 1、Task 2 |
| 测试 | Task 3 |
| 文档登记 | Task 4 |

### Placeholder Scan

计划无 `TBD`、`TODO`；所有代码块完整。
