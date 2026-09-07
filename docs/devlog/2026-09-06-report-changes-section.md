# 评估报告加入「Agent 更新与变化」节（2026-09-06）

> 一句话：report 现在自动汇总「上一轮 → 本轮」之间的开发日志（docs/devlog/），在报告开头分「Agent 侧 / 评测侧」列出，让读者先知道这轮测的是什么版本，再看指标。

## 1. 背景

round-2 与 round-1 相隔三周，期间 agent 经历了领域本体、execution context fetch、记忆检索、fetch 工具化、多文件理解等大量改动，但 report 只给指标 diff（`avg_score -0.52`），读者不知道**为什么**指标变了——是 agent 退步了，还是这轮测的是行为完全不同的新版本。

## 2. 实现

### 2.1 变更采集（`eval/runner/report.py::collect_changes_since`）

- 区间：上一轮日期（严格大于其日期部分）→ 本轮日期；**无上一轮时列出项目开始以来的全部日志**（首轮本就该看到完整变更史）。
- 来源：`docs/devlog/*.md`，取 `# ` 标题行 + 文件名日期（两种日志头格式都兼容）。
- 分类：文件名 + 标题关键词粗分：
  - 评测侧：`eval`（**词边界**匹配）/ `judge` / `golden` / `sample` / `grounding` / `知识库`，或标题含「评估/评测/Judge/golden」。
  - 其余归 Agent 侧（图结构 / 节点 / 工具 / 提示词 / RAG）。
- 写入 `summary.json` 的 `changes` 字段（`since` / `agent_changes` / `eval_changes`）。

### 2.2 渲染（`write_report`）

报告头部（日期/轮次/模型/commit 之后、指标之前）新增：

```markdown
## Agent 更新与变化（自 2026-08-17 round-1 以来）

**Agent 侧**（图结构 / 节点 / 工具 / 提示词 / RAG）
- 2026-08-30 开发日志：fetch_execution_context 改为 agent 自由调用的读取工具（2026-08-30）
...

**评测侧**（样本 / 评测器 / 报告）
- 2026-09-06 评测黄金样本未跟随新工具库 / RAG 的修复（2026-09-06）
```

### 2.3 接线（`tools/eval_cli.py::cmd_report`）

`summary["changes"] = collect_changes_since(args.round_dir)`。

## 3. 踩坑记录：子串误分类

第一版用 `"eval" in name` 粗匹配，真实日志一跑就翻车：**`2026-08-29-memory-retrieval-context-engineering.md` 里的 "retrieval" 包含子串 "eval"**（r-e-t-r-i-e-**v-a-l**），被误判为评测侧。改为 `(?:^|[-_])eval(?:[-_]|$)` 词边界匹配。测试 `test_collect_changes_since_classifies_by_filename_keyword` 锁定该行为。

另一处：`2026-08-24-fix-round1-self-diff.md`（修评估报告 bug）文件名无关键词但标题含「评估报告」，靠标题关键词补上。这两个真实案例都验证过分类正确。

## 4. round-2 实际效果

```
## Agent 更新与变化（自 2026-08-17 round-1 以来）
Agent 侧：8 条（领域本体 / Execution Context Fetch / 知识库扩充 / 记忆检索 / fetch 工具化 / 多文件 / 非当前步修复 ×2）
评测侧：5 条（Judge 结构化输出 / 评估报告 MD / round1 自比对修复 / Grounding 核对器 / 金样本校准）
```

读者一眼可见：这轮 -0.52 的 avg_score 背后是 13 条变更——agent 行为已大幅演进（新增自由读取工具、多文件支持），且金样本也随之校准过。

## 5. 涉及文件

- `eval/runner/report.py`（`collect_changes_since` / `_iter_round_dirs` / `_devlog_title`；`write_report` 渲染变更节）
- `tools/eval_cli.py`（`cmd_report` 接线 `changes`）
- `tests/test_eval_report.py`（+4 测试：区间过滤 / 无上一轮全量 / 关键词分类 / report 渲染）
- `eval/archive/2026-09-6/round-2/{summary.json,report.md}`（重新生成）
