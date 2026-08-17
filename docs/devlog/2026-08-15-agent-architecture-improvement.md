# 2026-08-15 Agent 架构改进实现记录

> 对应 plan：`docs/plan/2026-08-14-agent-architecture-improvement-plan.md`
> 对应 spec：`docs/spec/2026-08-14-agent-architecture-improvement-design.md`

## 目标

把 JavaTutor Coze 智能体重构为「外层教学 Agent + 评审 Agent，内层工具循环」的多工具架构，并集成 GSSC 上下文工程、会话工作记忆、项目知识 RAG；移除 SVG 动画生成模块。

新图链路：`parse_context → context_compaction → analyze_code（确定性）→ load_session → build_context（GSSC）→ main_agent（step_facts 工具循环 ≤3 轮）→ critic → revise → save_session → build_final`；显式 `intent=analyze` 直达返回结构化 JSON。

## 改动清单

### Task 1：移除 SVG 动画模块

- 删除 `src/learning/animation.py`、`assets/svg_templates/`、`tests/test_animation.py`、`tests/fixtures/animation_data.json`。
- `nodes.py`：移除 `learning.animation` import、`animate_node` / `animate_guide_node` 定义、`ANIMATE_GUIDE_MESSAGE` import；`route_intent` 显式 intent 列表剔除 `animate` / `animate_guide`。
- `prompts.py`：移除 `ANIMATE_GUIDE_MESSAGE`；`SYSTEM_PROMPT_INTENT` 移除 `animate_guide` 类别。
- `graph.py`：移除 animate 节点注册、边与路由；`_route_to_expert` 仅保留 analyze 直达。
- `state.py`：移除 `svg_text` 字段；`algorithm_tags` 注释去动画化。
- `intent.py`：`VALID_INTENTS` 移除 `animate_guide`。
- 测试：`test_expert_nodes.py` 移除 3 个动画用例；`test_graph.py` 移除 2 个动画流程用例与节点断言；`test_route_intent.py` 移除 `test_explicit_intent_animate`；新增 `test_graph_has_no_animation_nodes`、`test_no_animation_prompt_constant`。

### Task 2：parse_context 保守意图派生

- `nodes.py`：`_parse_json_dict` 中显式 intent（`data_query|concept|debug|analyze|other`）优先，否则用 `conservative_intent(user_question, compile_error)` 派生（复用评估系统基准模块）。
- 新增 `test_parse_context_derives_conservative_intent`、`test_parse_context_explicit_intent_wins`。

### Task 3：analyze_code 确定性节点

- 新增 `src/graphs/javatutor/analyze.py`：`analyze_code_node(state, model=None)`，有 `source_code` 必执行，返回 `analysis_result`；`intent=analyze` 时另返回 `messages`（纯 JSON）。
- `state.py` 追加 `analysis_result` / `memories` / `context_built` / `tool_rounds` 字段。

### Task 4：step_facts 工具

- 新增 `src/tools/step_facts.py`：`step_facts(state, step_index=None, line=None)` + `TOOL_SCHEMA`；返回指定步骤的原始证据（variables/heap/stackFrames/output/line_text）与相邻步骤程序化 diff，不调用 LLM。

### Task 5：会话工作记忆

- 新增 `src/learning/memory.py`：`MemoryStore` 抽象、`DictMemoryStore`、`PostgresMemoryStore`（`session_memories` 表，TTL 60min，capacity 50，importance 0-1）、`get_memory_store()`（Postgres 优先，失败兜底 Dict）。
- `nodes.py` 追加 `load_session` / `save_session` 节点。

### Task 6：GSSC ContextBuilder

- 新增 `src/graphs/javatutor/context_builder.py`：Gather-Select-Structure-Compress 四阶段；`estimate_tokens` / `jaccard` / `recency` / `ContextPacket` / `gather` / `select` / `structure` / `compress` / `build_context`。

### Task 7：主 Agent 工具循环

- `prompts.py` 追加 `SYSTEM_PROMPT_MAIN_AGENT`。
- 新增 `src/graphs/javatutor/main_agent.py`：`main_agent_node` 解析式工具调用，最多 3 轮，返回 `answer` / `tool_rounds` / `tool_calls`。

### Task 8：图装配与集成

- 重写 `src/graphs/javatutor/graph.py` 为新链路；`intent=analyze` 直达返回 JSON。
- `nodes.py` 追加 `build_context_node`（GSSC 构建）。

### Task 9：项目知识语料与全量回归

- 新增 `assets/knowledge/javatutor_project.json`（产品能力 / Agent 边界 / 动画引导 / 复杂度分析 4 条目）。
- `AGENT.md` 状态表更新 + 本 devlog 登记。

## 与 plan 的差异（含理由）

1. **未执行提交**（plan 各任务 Step 5）。遵循用户指示「以后不要主动做 git 相关工作，除非明确指示」，所有改动保留在工作区由用户提交。
2. **Task 8：`intent=analyze` 直达路由到 `END` 而非 `final`**。spec 要求「直接返回结构化 JSON」；若经 `build_final` 会追加第二条 AI 消息与「抱歉」兜底文本，破坏既有 `test_full_flow_analyze` 的「恰好 1 条纯 JSON AI 消息」契约。直达 END 使 analyze_code 返回的 JSON 消息成为唯一输出。
3. **Task 3：`analyze_code_node` 失败兜底返回完整 JSON 骨架**（`_FALLBACK_ANALYSIS`），而非空 `{}`。对齐旧 `analyze_node` 的降级行为：LLM 不可用时 `intent=analyze` 仍能返回可解析、含 complexity 的 JSON。
4. **Task 7：`main_agent_node` 捕获 `_invoke` 异常并返回降级回答**，对齐 `_run_expert` / `critic_node` 的既有降级模式；否则无注入模型的全流程测试会因 `llm_complete` 读取不到本地配置直接抛异常。
5. **Task 3/7：`analyze.py` / `main_agent.py` 的 `_invoke` 增加 `_resolve_model`**，从 `langgraph.config.get_config().configurable.chat_model` 拉取注入模型。plan 原代码仅接受显式 `model` 参数，导致图中调用 `analyze_code_node(state)` 时永远拿不到 `configurable.chat_model`，集成测试 `analysis_result` 落入兜底。
6. **Task 5：`DictMemoryStore.add()` 未传 `ttl_seconds` 时改用 `self._ttl_seconds`**。plan 原代码 `add()` 默认参数硬编码 `DEFAULT_TTL_SECONDS`，导致 `DictMemoryStore(ttl_seconds=1)` 的过期测试失败（存储级 TTL 失效）。

## 验证结果

| 门槛 | 命令 | 结果 |
|---|---|---|
| L1 依赖锁 | `uv sync --frozen` | ✅ 135 包已同步 |
| L2 全量测试 | `uv run pytest tests/ -q` | ✅ 95 passed |
| L2.5 组件评估 | `uv run pytest tests/test_eval_component.py -v` | ✅ pass_rate=1.0 |
| L3 离线构建 | `build_agent().builder.compile()` | ✅ 输出 `ok` |
| L4 HTTP 冒烟 | — | ⏭️ 跳过（本地无模型端点） |
| L5 外壳回归 | shell 路径 grep | ✅ 无外壳文件改动 |

测试数量变化：基线 115 → 95（移除动画与 LLM 意图相关用例，新增各任务新用例；review 修复后净变化见下节）。

## 遗留与注意

- `nodes.py` 中 `retrieve_knowledge`、专家节点（`data_query_node` 等）已不在图中主链路；`retrieve_knowledge` 已在新图接入，专家节点作为兼容层保留定义以支撑其单元测试。
- `get_memory_store()` 在无本地 PostgreSQL 时返回 `DictMemoryStore`，Postgres 持久化仅在平台部署环境生效。
- 项目知识语料入库需运行 `tools/seed_knowledge.py`（RAG 指南见 `docs/rag-knowledge-guide.md`）。

## Review 修复（2026-08-15）

> 依据：`docs/reviews/2026-08-15-agent-architecture-improve-review.md`（2 P1 / 2 P2 / 2 P3）。

### P1-1：决策痕迹补 tool_calls / token_usage

- `state.py` 追加 `tool_calls: list` 与 `token_usage: dict` 字段。
- `nodes.py` 新增 `_estimate_token_usage(state)`（复用 `estimate_tokens`，`estimated=true`）。
- `build_final` 的 trace 写入 `tool_calls` 与 `token_usage`，对齐接口契约决策痕迹 schema。
- 测试：`test_full_flow_generate_review_revise_trace` 新增断言（trace 含 `tool_calls` / `token_usage` / `estimated`）。

### P1-2：新图接入 RAG（retrieve_knowledge）

- `graph.py` 注册 `retrieve_knowledge` 节点，链路改为 `load_session → retrieve_knowledge → build_context`。
- `build_context → gather` 已消费 `state.retrieved_chunks`，RAG 结果进入上下文。
- 测试：新增 `test_retrieve_knowledge_node`、`test_retrieve_knowledge_node_empty_query`、`test_graph_wires_retrieve_knowledge_before_build_context`；结构测试断言 `retrieve_knowledge` 节点。

### P2-1：对话历史注入 ContextBuilder

- `build_context_node` 从 `state.messages[:-1][-5:]` 提取最近 5 条历史（content 为 list 时先抽取 text），传给 `build_context(history=...)`。

### P2-2：清理 LLM 意图死代码

- 删除 `src/graphs/javatutor/intent.py`（`classify_intent`）、`SYSTEM_PROMPT_INTENT`、`nodes.py` 的 `route_intent` / `_is_compile_error_debug`。
- 删除 `tests/test_route_intent.py`（9 用例）与 `tests/test_intent.py`（4 用例）。
- 清理 `tests/test_graph.py` 中 `DeepFakeModel` / `CriticFailModel` 的死「意图分类器」分支。
- `llm.py` 模块 docstring 移除对已删 `intent.py` 的引用。

### P3-1：主 Agent 工具调用参数校验

- `main_agent_node` 中 `step_facts(state, **args)` 包 `try/except TypeError`：未知键/非法参数返回结构化 error 而非中断循环。
- 未知工具名追加 `[工具 X 不可用，请直接回答]` 继续循环，不再把工具 JSON 当作最终回答；循环结束仍无回答时兜底「抱歉」。
- 测试：新增 `test_main_agent_invalid_args_returns_error_not_crash`、`test_main_agent_unknown_tool_not_leaked_as_answer`。

### P3-2：save_session 存修订后回答

- `save_session` 改为 `state.get("revised_answer") or state.get("answer") or ""`，修订值优先入库。

### 复验

| 门槛 | 结果 |
|---|---|
| L1 `uv sync --frozen` | ✅ 135 包 |
| L2 `uv run pytest tests/ -q` | ✅ 95 passed（102 − 13 删除 + 6 新增） |
| L2.5 `test_eval_component.py` | ✅ pass_rate=1.0 |
| L3 离线构建 | ✅ 输出 `ok` |
| L5 外壳回归 | ✅ 无外壳文件改动 |
