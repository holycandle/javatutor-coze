# 开发日志：fetch_execution_context 改为 agent 自由调用的读取工具（2026-08-30）

> 执行依据：`docs/spec/2026-08-30-fetch-execution-context-as-tool-design.md` + `docs/plan/2026-08-30-fetch-execution-context-as-tool-plan.md`。

## 原因

上一版（2026-08-23）把执行上下文作为**确定性 graph 节点**在启动时向后端拉取并强制注入，运行中暴露两类问题：

1. **代码注入过重 / 时机错误**：无论用户问题是否需要代码，节点都在启动时把整段代码拉进上下文，违背「信息分层原则」。
2. **工具记录缺失 + 拿不到代码**：`fetch_execution_context` 是 graph 节点而非模型可选工具；一旦该节点在运行期失败（后端快照 30 分钟 TTL、重启丢失、跨实例），`state.source_code` 为空，agent 对代码完全无感知，且决策痕迹里看不到这次读取。

本次改为：去掉该节点，把「读取代码」的能力交给主 Agent 工具循环里的 LLM 工具，**读到的代码先暂存 state，不直接塞进 prompt**。

## 改动

- **`fetch_execution_context` 重构为纯 state 读取工具**（`src/tools/fetch_execution_context.py`）：
  - 删除 `httpx` / `os` / 后端 HTTP 分支；不再读 `JAVATUTOR_EXECUTION_CONTEXT_URL` / `JAVATUTOR_AGENT_TOKEN`。
  - 从入站 state 的 `source_code` / `steps` / `current_step_index` / `current_line` 读取（永远新鲜）。
  - 读到的完整执行上下文写入 `state.fetched_context` 暂存，并修复 `source_code` / `steps` / `steps_json` / `steps_count` / `has_steps` / `current_step_index` / `current_line` / `current_variables` / `compile_error` / `has_error` / `algorithm_tags` 等标准字段，供 `step_facts` / `analyze_code_node` / 真实行号解析复用。
  - 返回给模型一段紧凑结果（`run_id` / `code` / `steps_count` / 当前位置 / `algorithm_tags` / `stored: true`）。
  - schema 预留 `file` / `start_line` / `end_line`（本轮只实现单入口/整段读取）。
  - 失败时返回结构化错误，不抛异常、不写坏 state。
- **主 Agent 工具循环 dispatch**（`src/graphs/javatutor/main_agent.py`）：新增 `fetch_execution_context` 分支，与 `step_facts` 并列；结果合并回 state（`fetched_context` 等）并记录进 `tool_calls`；移除早期降级守卫 `fetch_context_failed and not has_steps` 的早退分支。
- **graph 移除 fetch 节点**（`src/graphs/javatutor/graph.py`）：删除 `fetch_execution_context_node` 节点与边，链路恢复为 `parse_context → context_compaction → analyze_code → …`。删除 `src/graphs/javatutor/fetch_context.py`。
- **上下文工程**（`src/graphs/javatutor/context_builder.py`）：`gather()` 不再无条件注入 `### 源代码`，改为仅当 `state.fetched_context` 含非空 `source_code` 时才注入。
- **系统提示**（`src/graphs/javatutor/prompts.py`）：`SYSTEM_PROMPT_MAIN_AGENT` 增加 `fetch_execution_context` 使用引导。
- **build_final**（`src/graphs/javatutor/nodes.py`）：移除按 `run_id` 手工补记 fetch 工具的逻辑；`tool_calls` 现由 `main_agent` 真实产生。
- **`.env.example`**：删除 `JAVATUTOR_EXECUTION_CONTEXT_URL`、`JAVATUTOR_AGENT_TOKEN`。
- **state**（`src/graphs/javatutor/state.py`）：新增 `fetched_context: dict` 字段。
- **测试**：重写 `test_fetch_execution_context.py`（去掉 HTTP mock）、新增 `test_state.py`、更新 `test_main_agent.py` / `test_graph.py` / `test_build_final.py` / `test_context_builder.py`；删除 `test_fetch_context_node.py`（针对已删节点）。

## 验证结果

- L1 依赖锁：`uv sync --frozen` 通过，无锁文件变化。
- L2 全量单测：`uv run pytest -q` 全绿（159 passed）。
- L3 离线构建：`build_flow_graph().compile()` 成功，节点列表不含 `fetch_execution_context`。
- L5 外壳约束：未改 `src/main.py` / `scripts/` / `.coze` / `src/storage` / `src/utils` / `learning/memory.py` / `pyproject.toml`；未做任何 git 操作；`fetch_execution_context.py` 无 `httpx` / `os` import。

## 遗留 / 注意事项

- 本次改动后在 Coze 平台**必须重新发布 agent** 才生效。
- 后端需同步恢复完整 envelope（见 javatutor 仓 `docs/plan/2026-08-30-execution-context-envelope-token-plan.md`），让 `source_code` / `steps` 进入入站 state。
- `file` 多文件读取仅 schema 预留，本轮未实现；多文件需后端/模型支持多文件结构后另做。
- 决策痕迹里 `fetch_execution_context` 记录由 `main_agent` 真实产生，前端 `formatToolCall` 走通用分支，无需改前端。
- 坚持「信息分层原则」，本次未新引入 `search_knowledge` / MemoryTool。
