# 2026-08-23 Execution Context Fetch

## 改动内容

执行计划 `docs/plan/2026-08-23-execution-context-fetch-plan.md`，把执行上下文从「入站消息携带」改为「Coze 侧按 run_id 确定性获取」。

1. **入站 envelope 解析**（`state.py` + `nodes.py`）
   - `JavaTutorState` 新增 `run_id` / `fetch_context_failed` / `fetch_context_latency_ms` / `fetch_context_error` / `run_context_memory`。
   - `_parse_json_dict` 新 envelope：`run_id` 直接读；`user_id` 由 `session_id`（回退旧 `user_id`）映射；旧 payload 兼容不变。

2. **fetch_execution_context 工具**（新增 `src/tools/fetch_execution_context.py`）
   - 按 `run_id` GET `{JAVATUTOR_EXECUTION_CONTEXT_URL}/{run_id}`，带 `X-Agent-Token`，超时 3 秒。
   - 成功返回完整执行数据 + `run_context_memory` 紧凑摘要（code_hash/steps_count/当前索引/行号/算法标签，不含 source_code 与 steps）。
   - 失败（run_id 空/无环境变量/非 200/超时/非法 JSON/缺字段）返回 `fetch_context_failed=True` + readable error + `fallback_reason`。

3. **确定性 graph 节点**（新增 `src/graphs/javatutor/fetch_context.py` + 改 `graph.py`）
   - 链路改为 `parse_context → fetch_execution_context → context_compaction`；节点置于主 Agent 工具循环之外，不作为模型可选工具。
   - 旧 payload（has_steps + source_code）时 fetch 失败不清空 fallback_reason，保留旧上下文。

4. **主 Agent 降级 + 运行摘要注入**（`main_agent.py` + `context_builder.py`）
   - `main_agent_node`：`fetch_context_failed and not has_steps` 时直接输出固定降级文案「当前暂时无法获取这次代码运行的执行上下文，请重新运行代码后再提问。」
   - `gather` 注入 `run_context_memory` 到 Memory section（relevance 0.85）。

5. **决策痕迹**（`nodes.py` build_final）：trace 增加 `run_id` / `fetch_context_failed` / `fetch_context_latency_ms` / `fetch_context_error`。

## 计划外修复（Task 6 暴露的集成缺陷）

计划 Task 6 的失败路径测试暴露：降级文案在 main_agent 正确产出后，被 critic/revise 的 LLM 循环覆盖成模型回答。根因是评审 prompt 含「源代码」字样，demo 模型误命中 complexity 分支。这反映真实设计缺陷：**固定降级文案是确定性输出，不应进入评审/修订的 LLM 循环**。

在 `critic_node` 开头对降级情形（`fetch_context_failed and not has_steps`）短路：`critic_passed=True` + `critic_skipped=True`，让降级文案不经评审直达 build_final。

## 验证结果

- 全量测试 `uv run pytest -q` → **148 passed**（原 133 + 15 新增）。
- L1 依赖锁 `uv sync --frozen` → 无变化（135 packages）。
- L3 离线构建 `build_agent().builder.compile()` → ok。
- L5 外壳回归：改动仅 `src/graphs/`、`src/tools/`、`tests/`，未碰 `src/main.py`/`scripts/`/`.coze`/`src/storage/`/`src/utils/`。

## 遗留问题

- `JAVATUTOR_EXECUTION_CONTEXT_URL` / `JAVATUTOR_AGENT_TOKEN` 需在部署环境配置；本地未配置时 fetch 恒失败降级（旧 payload 仍可用）。
- 端到端真机验证（JavaTutor 本地跑代码后 Coze 侧凭 run_id 获取并回答）需后端接口就绪后执行，属 spec 第 9 节 e2e 范畴。
- 旧 payload 兼容路径保留，但新部署应按新 envelope 发送（仅 run_id/session_id/user_question/intent/compile_error）。
