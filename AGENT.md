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
| 架构改进 spec | 已写，待评审 |
| 架构改进 plan | 已写，待执行 |

## 规约与文档索引

| 类别 | 文件 | 说明 |
|---|---|---|
| 开发规约 | `docs/local-dev-convention.md` | 外壳契约、环境一致性、验证门槛、部署规约 |
| 接口契约 | `docs/spec/2026-08-10-coze-agent-interface.md` | 前后端与 Coze 的消息/决策痕迹契约 |
| 深化设计 | `docs/spec/2026-08-10-coze-agent-deepening-design.md` | 既有深化链路设计 |
| 评估系统设计 | `docs/spec/2026-08-14-agent-eval-system-design.md` | 双轨评估系统设计 |
| 评估系统计划 | `docs/plan/2026-08-14-agent-eval-system-plan.md` | 评估系统 TDD 实施计划 |
| 架构改进设计 | `docs/spec/2026-08-14-agent-architecture-improvement-design.md` | 多工具 + 上下文工程 + 工作记忆设计 |
| 架构改进计划 | `docs/plan/2026-08-14-agent-architecture-improvement-plan.md` | 架构改进 TDD 实施计划 |
| RAG 指南 | `docs/rag-knowledge-guide.md` | 语料格式与灌库说明 |
| 实现记录 | `docs/devlog/YYYY-MM-DD-<topic>.md` | 每次实现变更的流水记录 |
| 评估系统实现 | `docs/devlog/2026-08-14-agent-eval-system.md` | 双轨评估系统实现记录 |

## 文档规范

1. 新规约：放 `docs/` 或仓库根，并在本文件登记。
2. 新设计：`docs/spec/YYYY-MM-DD-<topic>-design.md`。
3. 新计划：`docs/plan/YYYY-MM-DD-<topic>-plan.md`，TDD 格式。
4. 实现记录：`docs/devlog/YYYY-MM-DD-<topic>.md`。
5. 文件统一 UTF-8；文件名只允许字母、数字、下划线、短横线。
6. 文档内容不得出现 `TBD` / `TODO` 占位；未定的内容先定方案再写。
7. 完成完整新功能或修复重大 bug 后，必须撰写开发日志 `docs/devlog/YYYY-MM-DD-<topic>.md`，记录改动内容、验证结果与遗留问题；开发日志随功能一起提交，并在本文件登记。

## 协作规则（摘要）

- 不修改外壳：`.coze`、`scripts/`、`src/main.py`、`src/storage/`、`src/utils/`。
- 业务代码只允许新增到：`src/agents/`、`src/graphs/`、`src/learning/`、`src/tools/`、`tools/`、`assets/`、`config/`、`tests/`、`docs/`。
- 提交前必须通过本地规约 L1-L5 与评估系统门槛。
- 设计变更先更新对应 spec，再更新 plan，最后执行；所有变更都要在评估系统留档。
