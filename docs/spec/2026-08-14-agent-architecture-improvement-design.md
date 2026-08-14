# Agent 架构改进设计（多工具 + 上下文工程 + 工作记忆）

## 1. Goal

把 JavaTutor Coze 智能体从“多角色专家 + 流水线”重构为“外层教学 Agent + 评审 Agent，内层工具循环”的多工具架构，并引入 GSSC 上下文工程、会话工作记忆、项目知识 RAG；移除 SVG 动画生成模块。重构顺序在评估系统落地之后执行，每轮改动用评估系统对比。

## 2. Scope

### In Scope

- 多工具架构：教学主 Agent + 评审 Agent，内层工具循环。
- 工具 M1：`step_facts`（原始证据 + 程序化 diff，模型可选）、`analyze_code`（确定性前置节点）。
- 移除 SVG 动画生成模块与 `animate` / `animate_guide` 节点。
- 保守意图规则 + 显式 intent，作为 ContextBuilder 优先级信号（非路由）。
- GSSC ContextBuilder：Gather / Select / Structure / Compress。
- 工作记忆：Postgres `session_memories`，TTL / 容量 / 重要性。
- 项目知识 RAG：同表额外 top-3 检索。
- 评审-修订保留，Critic 复用同一份构建后的上下文；决策痕迹保留。

### Out of Scope

- SFT / LoRA 微调（后续独立项目）。
- 跨会话长期记忆（仅会话级工作记忆）。
- Plan-Execute 规划分支。
- 模型端点的 `tool_calls` 原生能力验证（若支持则启用，否则用解析式伪工具）。

## 3. Decisions

- **D-01**：采用“外层教学 Agent + 评审 Agent，内层工具循环”架构（方案 B）。
- **D-02**：四个专家节点（data_query/concept/debug/other）删除，能力并入主 Agent 行为、工具与上下文。
- **D-03**：M1 工具集 = `step_facts` + `analyze_code`。
- **D-04**：`step_facts` 返回原始证据（指定步骤的 variables/heap/stackFrames/output/行文本）+ 程序化 diff 摘要，不调用 LLM；由主 Agent 决定是否调用。
- **D-05**：`analyze_code` 为确定性前置节点，消息含 `source_code` 时必定执行；结果写入工作记忆。
- **D-06**：后续问答通过工作记忆注入上一次 `analyze_code` 结果。
- **D-07**：移除 SVG 动画生成模块，删除 `src/learning/animation.py`、`assets/svg_templates/`、`animate_node`、`animate_guide_node`、`SYSTEM_PROMPT_ANIMATE`、动画相关测试与图边。
- **D-08**：动画/演示关键词由主 Agent 结合项目知识 RAG 解释前端「算法可视化」能力；效果不佳时退回固定引导文本（方案 C，fallback B）。
- **D-09**：意图识别 = 保守关键词 + 显式 intent，不使用 LLM 分类；结果仅作为 ContextBuilder 优先级信号，不决定路由。
- **D-10**：工作记忆存储于 Postgres `session_memories`；TTL 60 分钟、容量 50 条、importance 0-1。
- **D-11**：`analyze_code` 结果 importance 0.85 自动写入；每轮问答摘要 importance 0.5 自动写入。
- **D-12**：`session_id` 采用后端已传的 `user_id` 字段（最小改动）；缺失时跳过读写。
- **D-13**：ContextBuilder 每次专家生成前构建一次，Critic 复用同一份上下文。
- **D-14**：Gather 源 = 系统指令 + 项目知识 RAG top-3 + Java 语料 RAG + 工作记忆 + 执行数据 + 最近 5 轮对话。
- **D-15**：Select 评分 = 相关性×0.7 + 新近性×0.3，贪心填充 token 预算。
- **D-16**：Structure 固定分区 `[Role&Policies][Task][Evidence][Memory][Context][Output]`。
- **D-17**：Compress 超预算按分区截断或摘要，标注 `[...已压缩...]`。
- **D-18**：项目知识 RAG 使用同一向量表，`source` 标记“知识库: JavaTutor项目”，每次文本问答额外检索 top-3。
- **D-19**：主 Agent 工具循环最多 3 轮；中间 LLM 调用一律使用 `llm_complete()`，避免流式泄露。
- **D-20**：评审五类核查（步骤号、行号、变量值、堆 id、输出）与决策痕迹保留。
- **D-21**：`build_agent()` / `AgentBundle` 契约不变。

## 4. Architecture

```text
parse_context
  → context_compaction（steps 窗口 + 摘要）
  → analyze_code（确定性：有 source_code 必跑，结果写工作记忆）
  → load_session（读工作记忆）
  → build_context（GSSC 一次构建）
  → main_agent（工具循环：step_facts 按需调用，最多 3 轮）
  → critic（复用 build_context 输出）
  → revise
  → save_session（写问答摘要）
  → build_final（答案 + 决策痕迹）
```

显式 `intent=analyze` 仍触发 `analyze_code` 并直接返回结构化 JSON（前端按钮入口）。

### Components

| 组件 | 职责 |
|---|---|
| `main_agent` | 工具循环主 Agent：理解问题、调用 step_facts、组织回答 |
| `critic_node` / `revise_node` | 五类事实核查与单轮修订 |
| `analyze_code` | 确定性分析节点：复杂度 + 算法/数据结构标签 |
| `step_facts` | 工具：按步骤/行返回原始证据 + 程序化 diff |
| `working_memory` | Postgres 会话记忆读写 |
| `context_builder` | GSSC：收集、筛选、结构化、压缩 |
| `project_knowledge` | 项目知识语料 + RAG |
| `intent_rules` | 保守意图规则（复用评估系统基准模块） |

## 5. Data Contracts

### 5.1 step_facts 工具

输入：

```json
{"step_index": 1, "line": 4}
```

输出：

```json
{
  "evidence": {"variables": {}, "heap": {}, "stackFrames": [], "output": null, "line_text": "..."},
  "diff": [{"key": "arr", "before": [5, 3, 1], "after": [3, 5, 1]}],
  "error": ""
}
```

### 5.2 analyze_code 输出

```json
{
  "complexity": {"time": "O(n)", "timeExplanation": "...", "space": "O(1)", "spaceExplanation": "..."},
  "algorithms": [{"name": "冒泡排序", "category": "排序"}],
  "dataStructures": [{"name": "数组", "category": "数组"}]
}
```

### 5.3 session_memories 表

```sql
CREATE TABLE IF NOT EXISTS session_memories (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    content TEXT NOT NULL,
    memory_type VARCHAR(16) NOT NULL DEFAULT 'working',
    importance DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_memories_session
    ON session_memories (session_id, expires_at);
```

### 5.4 ContextPacket

```python
{"content": str, "timestamp": float, "token_count": int, "relevance_score": float, "metadata": dict}
```

### 5.5 项目知识语料

`assets/knowledge/javatutor_project.json`，条目含 `title / keywords / category / explanation / example / source / retrieved_at`，`source` 统一为“知识库: JavaTutor项目”。

## 6. Error Handling

- 工具调用失败：`step_facts` 返回 `error` 字段，主 Agent 继续回答，不中断。
- 工作记忆不可用（DB 失败）：跳过读写，`memory_degraded=true` 写入决策痕迹。
- RAG 降级：检索失败返回空，`rag_degraded=true`。
- 评审/修订失败：沿用现有降级（`critic_skipped` / `revise_skipped`）。
- `analyze_code` 失败：不写记忆，主 Agent 继续。
- 工具循环达到 3 轮：以当前结果回答，决策痕迹记录 `tool_rounds=3`。

## 7. Testing & Acceptance

### Tests

- `step_facts` 工具测试：越界、字符串变量、diff 正确性。
- `analyze_code` 确定性触发测试：有/无 source_code。
- 工作记忆测试：写入、TTL 过期、容量淘汰、importance 排序。
- ContextBuilder 测试：Gather 源齐全、预算竞争、分区结构、压缩兜底。
- 主 Agent 工具循环测试：FakeModel 模拟工具调用、上限轮数、失败降级。
- 全流程回归：既有 parse/compaction/critic/revise/trace 不回归。

### Acceptance

1. 有 `source_code` 的消息必定触发 `analyze_code`，结果在下一次问答上下文可见。
2. 主 Agent 可调用 `step_facts` 并正确引用返回证据。
3. 动画关键词不再返回 SVG，而是结合项目知识 RAG 说明前端能力。
4. ContextBuilder 输出固定分区且满足 token 预算。
5. 工作记忆按 TTL/容量/重要性生效，`user_id` 隔离。
6. 评估系统指标（意图准确率、引用准确率、Judge 均分）不因重构下降。

## 8. 与评估系统的关系

- 本重构的每次改动必须跑评估系统（组件级本地 + 端到端 Coze），对比上一轮。
- 意图准确率按保守规则评测（复用 `intent_rules.py`）。
- 引用准确率按 `fact_matches` + `step_facts` 证据核查。
- 重构前后各产出一轮存档，作为是否合入的依据。

## 9. Related Docs

- [评估系统设计](./2026-08-14-agent-eval-system-design.md)
- [评估系统实施计划](../plan/2026-08-14-agent-eval-system-plan.md)
- [本地开发规约](../local-dev-convention.md)
