# AGENT.md — 项目协作与规约索引

> 本文件是 `javatutor-coze`（Coze 侧智能体项目）的规约/文档总索引。新增任何规约、spec、plan、devlog 时，必须在本文件登记。

## 仓库定位

- Coze 侧智能体项目，部署时由 Coze 平台拉取远程仓库执行。
- 协作分工：设计由 Codex 产出（spec → plan），执行由 Claude Code 完成；本地仓库为唯一代码事实来源。
- 所有本地开发行为遵守 `docs/local-dev-convention.md`。

## 当前执行状态

| 文档 | 状态 |
|---|---|
| 本地开发规约 v1.2 | 生效 |
| 评估系统 spec | 已执行 |
| 评估系统 plan | 已执行 |
| 架构改进 spec | 已评审 |
| 架构改进 plan | 已执行 |
| 执行上下文拉取 spec | 已执行 |
| 执行上下文拉取 plan | 已执行 |
| 执行上下文作为工具 spec | 已执行 |
| 执行上下文作为工具 plan | 已执行 |

## 规约与文档索引

| 类别 | 文件 | 说明 |
|---|---|---|
| 开发规约 | `docs/local-dev-convention.md` | 外壳契约、环境一致性、验证门槛、部署规约 |
| 接口契约 | `docs/spec/2026-08-10-coze-agent-interface.md` | 前后端与 Coze 的消息/决策痕迹契约 |
| 深化设计 | `docs/spec/2026-08-10-coze-agent-deepening-design.md` | 既有深化链路设计 |
| 评估系统设计 | `docs/spec/2026-08-14-agent-eval-system-design.md` | 双轨评估系统设计 |
| 评估系统计划 | `docs/plan/2026-08-14-agent-eval-system-plan.md` | 评估系统 TDD 实施计划 |
| Judge 修复计划 | `docs/plan/2026-08-17-judge-parser-fix-and-round2-plan.md` | Judge 解析修复与 Round-2 评估计划 |
| Judge 结构化输出计划 | `docs/plan/2026-08-18-judge-structured-output-and-fallback-rate-plan.md` | JSON Schema 约束 + 兜底率指标 + 人工复核接入导出 |
| 评估报告 MD 计划 | `docs/plan/2026-08-21-eval-report-md-plan.md` | 每轮生成人读 Markdown 报告 |
| 领域本体计划 | `docs/plan/2026-08-19-javatutor-domain-ontology-plan.md` | JavaTutor 结构化领域本体（模块/字段映射/契约规则） |
| 领域本体 review | `docs/reviews/2026-08-20-javatutor-domain-ontology-review.md` | 领域本体执行审查（1 P2 / 2 P3 已修复） |
| 评估报告 MD review | `docs/reviews/2026-08-21-eval-report-md-review.md` | Markdown 报告生成审查（2 P3） |
| 执行上下文获取设计 | `docs/spec/2026-08-23-execution-context-fetch-design.md` | 入站只带 run_id，Coze 侧确定性获取执行上下文 |
| 执行上下文获取计划 | `docs/plan/2026-08-23-execution-context-fetch-plan.md` | fetch_execution_context 工具 + graph 节点 + 降级 |
| 架构改进设计 | `docs/spec/2026-08-14-agent-architecture-improvement-design.md` | 多工具 + 上下文工程 + 工作记忆设计 |
| 架构改进计划 | `docs/plan/2026-08-14-agent-architecture-improvement-plan.md` | 架构改进 TDD 实施计划 |
| 执行上下文拉取设计 | `docs/spec/2026-08-23-execution-context-fetch-design.md` | 后端快照按 `run_id` 拉取与 Coze 侧 `fetch_execution_context` 设计 |
| 执行上下文拉取计划 | `docs/plan/2026-08-23-execution-context-fetch-plan.md` | 引用式拉取执行上下文 TDD 实施计划 |
| RAG 指南 | `docs/rag-knowledge-guide.md` | 语料格式与灌库说明 |
| 评估指南 | `docs/dev-eval-guide.md` | 开发者如何跑评估、解读结果与导出微调数据 |
| 协作指南 | `docs/agent-collaboration-guide.md` | 新人上手：处理流程图与各阶段职责 |
| 实现记录 | `docs/devlog/YYYY-MM-DD-<topic>.md` | 每次实现变更的流水记录 |
| 评估系统实现 | `docs/devlog/2026-08-14-agent-eval-system.md` | 双轨评估系统实现记录 |
| 评估系统 review | `docs/reviews/2026-08-14-eval-system-review.md` | 评估系统首轮审查 |
| 评估系统 M1.1 review | `docs/reviews/2026-08-14-eval-system-m11-review.md` | remote mode 与扩展指标审查 |
| 架构改进实现 | `docs/devlog/2026-08-15-agent-architecture-improvement.md` | 多工具架构重构实现记录 |
| 架构改进 review | `docs/reviews/2026-08-15-agent-architecture-improve-review.md` | 架构改进首轮审查（2 P1 / 2 P2 / 2 P3 已修复） |
| Judge 修复 review | `docs/reviews/2026-08-17-judge-parser-fix-review.md` | Judge 解析加固 + Round-1 重判（发现空返回主因） |
| Judge 结构化输出实现 | `docs/devlog/2026-08-18-judge-structured-output.md` | JSON Schema 回退 + 兜底率指标 + 人工复核接入导出（121 passed） |
| 领域本体实现 | `docs/devlog/2026-08-19-javatutor-domain-ontology.md` | 结构化本体 + 常驻层/Judge 注入（129 passed） |
| 评估报告 MD 实现 | `docs/devlog/2026-08-21-eval-report-md.md` | report.md 人读报告生成（133 passed） |
| 执行上下文获取实现 | `docs/devlog/2026-08-23-execution-context-fetch.md` | fetch 工具 + 确定性节点 + 降级（148 passed） |
<<<<<<< HEAD
| round-1 diff 修复 | `docs/devlog/2026-08-24-fix-round1-self-diff.md` | 修复首轮 report 与自身对比（137 passed） |
| grounding 核对器 | `docs/devlog/2026-08-24-grounding-verifier.md` | 确定性反幻觉结构核对（147 passed） |
=======
| 执行上下文作为工具设计 | `docs/spec/2026-08-30-fetch-execution-context-as-tool-design.md` | fetch_execution_context 改为 agent 按需调用的纯 state 读取工具 |
| 执行上下文作为工具计划 | `docs/plan/2026-08-30-fetch-execution-context-as-tool-plan.md` | 纯 state 读取工具 TDD 实施计划 |
| 执行上下文作为工具实现 | `docs/devlog/2026-08-30-fetch-execution-context-as-tool.md` | 工具化重构，纯 state 读取（159 passed） |
| 多文件项目理解设计 | `docs/spec/2026-08-30-multifile-whole-project-design.md` | 概览+按需读：恒注入项目结构概览 + 主入口，其他文件按需读 |
| 多文件项目理解计划 | `docs/plan/2026-08-30-multifile-whole-project-plan.md` | 多文件读取 TDD 实施计划 |
| 多文件项目理解实现 | `docs/devlog/2026-08-30-multifile-whole-project.md` | file 参数激活 + 概览注入 + step_facts 按当前步文件（171 passed） |
>>>>>>> feat/fetch-execution-context-as-tool
| 知识库核对 | `docs/devlog/2026-08-25-knowledge-base-correction.md` | 领域本体核对修正 + 项目知识扩充（134 passed） |

## 文档规范

1. 新规约：放 `docs/` 或仓库根，并在本文件登记。
2. 新设计：`docs/spec/YYYY-MM-DD-<topic>-design.md`。
3. 新计划：`docs/plan/YYYY-MM-DD-<topic>-plan.md`，TDD 格式。
4. 实现记录：`docs/devlog/YYYY-MM-DD-<topic>.md`。
5. 文件统一 UTF-8；文件名只允许字母、数字、下划线、短横线。
6. 文档内容不得出现 `TBD` / `TODO` 占位；未定的内容先定方案再写。
7. Review 内容除非过短（少于一条有效结论），必须撰写 review 日志到 `docs/reviews/YYYY-MM-DD-<topic>-review.md`，并在本文件登记。
7. 完成完整新功能或修复重大 bug 后，必须撰写开发日志 `docs/devlog/YYYY-MM-DD-<topic>.md`，记录改动内容、验证结果与遗留问题；开发日志随功能一起提交，并在本文件登记。

## 协作规则（摘要）

- 不修改外壳：`.coze`、`scripts/`、`src/main.py`、`src/storage/`、`src/utils/`。
- 业务代码只允许新增到：`src/agents/`、`src/graphs/`、`src/learning/`、`src/tools/`、`tools/`、`assets/`、`config/`、`tests/`、`docs/`。
- 提交前必须通过本地规约 L1-L5 与评估系统门槛。
- 设计变更先更新对应 spec，再更新 plan，最后执行；所有变更都要在评估系统留档。
