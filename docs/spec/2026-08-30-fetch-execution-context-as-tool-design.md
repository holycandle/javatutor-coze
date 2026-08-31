# 让 fetch_execution_context 成为 agent 自由调用的读取工具（设计）

> 一句话：把「确定性 graph 节点 + 启动时注入代码」改为「**agent 按需调用的读取工具**」。工具把读到的执行上下文**暂存进 graph state**，不再在构建初始上下文时把整段代码塞进 prompt；默认可读主入口代码，`file` / `start_line` / `end_line` 参数为多文件与长代码预留。

## 1. 背景与要解决的问题

上一份设计（`docs/spec/2026-08-23-execution-context-fetch-design.md`）把执行数据从 Coze 入站消息里移除，改为由确定性的 `fetch_execution_context` graph 节点在启动时拉取并注入。运行中暴露两类问题：

1. **代码注入过重 / 时机错误**：无论用户问题是否需要代码，节点都在启动时把整段代码拉进上下文，违背「信息分层原则」（整体代码按需由工具读取，而不是强制预注入）。
2. **工具记录缺失 + 拿不到代码**：主 Agent 工具循环只 dispatch `step_facts`，`fetch_execution_context` 是 graph 节点而非模型可选工具；一旦该节点在运行期失败（后端快照 30 分钟 TTL、重启丢失、跨实例），`state.source_code` 为空，agent 对代码完全无感知，且决策痕迹里看不到这次读取。

用户诉求（译文）：去掉该节点，但保留「读取代码」的能力——**读到的代码不要直接塞进 prompt，先暂存**，后续可集成多文件读取，由 agent 自由调用。

## 2. 设计原则

1. **整体代码由 agent 决定何时读**：`fetch_execution_context` 作为主 Agent 工具循环里的一个 LLM 工具，agent 需要代码/执行上下文时才调用。
2. **读到的结果先落 state，再决定是否进模型**：工具把完整执行上下文写入 `state.fetched_context`（暂存区），并同步修复 `source_code` / `steps` / 当前位置等标准字段（供 `step_facts`、`analyze_code_node`、真实代码行号复用）。是否把某段代码展示给模型，由上下文工程（GSSC select）或 agent 的主动读取决定，不再强制注入。
3. **单步证据仍是 JIT**：`step_facts` 继续作为主 Agent 唯一按需的单步证据工具，且依赖的 `steps` / `source_code` 由读取工具先落进 state。
4. **兼容 & 降级**：后端快照取不到时，工具返回结构化错误，agent 引导用户重新运行代码，而不是静默输出无代码的回答。
5. **为多文件预留接缝**：工具 schema 预留 `file`、`start_line`、`end_line`，本次只实现单入口/整段读取，多文件读取留到后续。

## 3. 与信息分层原则的对应

| 数据类别 | 获取方式 | 说明 |
|---|---|---|
| 知识 / RAG | 上下文工程预取（`retrieve_knowledge` → `gather`） | 不变 |
| 会话记忆 | 上下文工程预取（`load_session` → `gather`） | 不变 |
| **整体代码（执行上下文）** | **agent 按需调用的读取工具**（`fetch_execution_context`） | **本次改动**：读→存 state→按需展示 |
| 单步执行证据 | JIT 工具（`step_facts`） | 不变 |

> 明确**不做**：把代码塞回每次启动强制注入；把 `step_facts` 改成预注入；把 `search_knowledge` 暴露为工具。

## 4. 工具设计（`src/tools/fetch_execution_context.py`）

### 4.1 行为

同一函数，两种可调用路径；工具模式下返回「给模型看的结果 + 写进 state 的暂存」。失败时绝不抛异常，返回结构化错误。

- **读取来源**：**纯 state 读取**。从 `state` 里的 `source_code` / `steps` / `current_step_index` / `current_line` 读取（来自入站 payload，永远新鲜）。**不再发 HTTP、不依赖后端快照 TTL。** `run_id`/`file` 参数仅占位预留（本次无多文件结构）。
  - 选择依据：方案 A 恢复完整 envelope 后，`fetch_execution_context` 的正常路径即有真实数据；留下 HTTP 回退只是重新引入后端内存快照的脆弱性，无实际收益。
- **暂存（写 state）**：把读取结果写入 `state.fetched_context`，同时更新标准字段 `source_code`、`steps`、`steps_json`、`steps_count`、`has_steps`、`current_step_index`、`current_line`、`current_variables`、`compile_error`、`has_error`、`algorithm_tags`（供 `step_facts` / `analyze_code_node` / 真实行号解析使用）。更新 `toggle` 标志 `fetch_context_failed=False`、`fetch_context_latency_ms`、`fetch_context_error=""`。
- **返回给模型**：一段可读的紧凑结果，含 `run_id`、`file`、`code`（本次读取的代码文本）、`steps_count`、`current_step_index`、`current_line`、`algorithm_tags`、`stored: true`。
  - `code` 是 agent 主动读取时**唯一**希望看到的内容；不读则不出现，因此满足「不直接塞进初始 prompt」。
- **失败**：返回 `{"error": "<可读原因>", "fetch_context_failed": true, ...}`，不写坏 state。

### 4.2 schema（对被调度的 LLM 可见，`run_id` 缺省用 state 值，多文件/长代码参数已预留）

```python
TOOL_SCHEMA = {
    "name": "fetch_execution_context",
    "description": (
        "读取本次运行的执行上下文（源代码、执行步骤、当前执行位置）。"
        "读取结果会暂存到状态，供后续推理与单步查询复用；"
        "回答需要代码或执行证据的问题前应先调用本工具。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "run_id": {"type": "string", "description": "可选，默认使用当前上下文的 run_id"},
            "file": {"type": "string", "description": "预留：多文件模式下要读取的文件名，缺省读取主入口/当前代码"},
            "start_line": {"type": "integer", "description": "预留：只读取该行开始的代码片段"},
            "end_line": {"type": "integer", "description": "预留：只读取到该行"},
        },
    },
}
```

## 5. 主 Agent 工具循环改动（`src/graphs/javatutor/main_agent.py`）

- 增加 `fetch_execution_context` 分支，与 `step_facts` 并列：

```python
fetched_context = state.get("fetched_context") or {}

# ... 在 while 循环内，tool["tool"] 判断处：
if tool["tool"] == "fetch_execution_context":
    args = tool.get("args") if isinstance(tool.get("args"), dict) else {}
    tool_calls.append({"tool": "fetch_execution_context", "args": args})
    try:
        result = fetch_execution_context(state, **args)
    except TypeError as exc:
        result = {"error": f"fetch_execution_context 参数非法: {exc}"}
    if result.get("error"):
        context += f"\n\n[fetch_execution_context 失败]\n{result['error']}"
    else:
        # 暂存：合并进 state（通过节点返回值写回），供 step_facts 与后续复用
        fetched_context = merge_fetched(state, fetched_context, result)
        # 给模型看紧凑摘要（含本次读取的 code）
        digest = {k: result[k] for k in ("file", "steps_count", "current_step_index",
                                          "current_line", "algorithm_tags") if k in result}
        context += f"\n\n[fetch_execution_context 结果]\n{json.dumps({'stored': True, **digest}, ensure_ascii=False)}"
elif tool["tool"] == "step_facts":
    ...
```

- 主 Agent 的返回值里把 `fetched_context` 及被修复的标准字段一并写回 state（LangGraph 会把返回的键 merge 进状态），并保留 `tool_calls` 记录（决策痕迹中即可看到本次读取）。

## 6. 上下文工程改动（`src/graphs/javatutor/context_builder.py`）

`gather()` 不再无条件注入整段源代码。改由**读取工具写回 `state.fetched_context.source_code`** 后，按相关性 `select` 决定是否/如何展示。基础改动：

- 把 `### 源代码` 包从无条件注入，改为「仅当 `state.fetched_context` 存在且包含 `source_code`（或 `state.source_code` 非空且当前 intent 明确需要代码）时才注入」。默认不注入整段。
- 保留 `### 当前执行位置` 包（来自 `fetched_context` / payload 的 `current_step_index`、`current_line`、`steps_count`），这是轻量且有价值的。

## 7. 状态字段改动（`src/graphs/javatutor/state.py`）

新增：

```python
fetched_context: dict
"""读取工具暂存的执行上下文快照：run_id / source_code / steps / current_step_index /
current_line / compile_error / algorithm_tags / code_hash / fetched_at / fetch_context_latency_ms."""
```

复用/保留：`fetch_context_failed`、`fetch_context_latency_ms`、`fetch_context_error`、`run_context_memory`（现由读取工具维护，仍禁止存放完整代码与 steps）。

## 8. Graph 改动（`src/graphs/javatutor/graph.py`）

- 删除 `fetch_execution_context_node` 节点与对应边。
- 链路恢复为：

```text
parse_context → context_compaction → analyze_code
→ [direct(intent=analyze)] → END
→ load_session → retrieve_knowledge → build_context → main_agent → critic → revise → save_session → final
```

- 图 docstring 同步（当前 docstring 本就未提 fetch 节点，改为与真实链路一致）。

## 9. 入站消息 / 后端 envelope 改动（`CozeService.java`）— 已选方案 A

**已定（方案 A）：恢复完整 envelope。** `buildAgentPayload` 带 runId 时**不要**提前只发控制字段，仍携带 `source_code`、`steps`、`current_step_index`、`current_line`。

- 理由：代码在 state 里永远新鲜（来自入站 payload）；读取工具优先读 state（不发 HTTP、不依赖 30 分钟内存快照）；`analyze_code_node`、`context_compaction`、`step_facts` 均有真实数据。
- 代价：入站消息体积回到 08-23 之前（代码 + steps 随每次提问发送）。但「envelope 携带 ≠ 模型看到」——模型是否看到由上下文工程 select 与 agent 主动读取决定，满足「不强制注入模型」。
- 后端需重新构建/部署 JavaTutor。

> **已被否决的备选 — 方案 B（保留 minimal envelope，不碰后端）**：读取工具只能从后端快照读；`analyze_code_node` 在无代码时降级为 `None`；`step_facts` 需 agent 先读工具拿 `steps` 才能工作；后端内存快照 TTL/重启的独立风险仍在。因脆弱且违背「信息分层」，不予采用。

## 10. 决策痕迹与前端

- 工具记录：`main_agent` 把 `fetch_execution_context` 写进 `tool_calls`（与 `step_facts` 并列），前端 `formatToolCall` 对非 `step_facts` 工具走通用分支，渲染为 `调用 fetch_execution_context：run_id=...`，**无需改前端**。
- `build_final` 里原「主动补记 fetch 工具」的逻辑（`nodes.py` 414-419 行）可移除或保留（若保留需判断是否已在 `tool_calls` 中，避免重复）。建议移除——工具记录现在由 `main_agent` 真实产生。

## 11. 测试策略

### 单元 / 工具测试（`tests/test_fetch_execution_context.py`）

- 纯 state 读取：state 有 `source_code` / `steps` 时直接返回并写 `fetched_context`（`stored=True`）。
- 无 `source_code` / `steps` 时返回 `{"error": ...}` 且不写坏 state。
- `start_line` / `end_line` 行切片正确。
- schema 含 `run_id` / `file` / `start_line` / `end_line`。
- 工具模块不 import `httpx` / `os`（确认无 HTTP/环境变量依赖）。
- `run_context_memory` 不含完整 `source_code` / `steps`。

### 主 Agent 工具循环测试（`tests/test_main_agent.py`）

- dispatch `fetch_execution_context` 后返回 `tool_calls` 记录、`fetched_context` 合并进 state、`context` 追加摘要。
- dispatch `step_facts` 依赖已写入的 `steps`；未读工具时 `step_facts` 参数非法给结构化错误，不中断循环。

### 行为 / 回归

- 初始 prompt 不再包含整段代码（`gather` 不注入 `### 源代码`，除非显式需要）。
- graph 不再含 `fetch_execution_context_node`（`test_graph.py` 更新）。
- 决策痕迹 `tool_calls` 含 `fetch_execution_context`。

## 12. 部署差异提示

- 本次改动全部在 **Coze agent 逻辑**（`javatutor-coze`），**必须在 Coze 平台重新发布 agent** 才生效；后端 `CozeService.java` 若恢复完整 envelope 也需重新构建/部署 JavaTutor。

## 13. 不做（边界）

- 不引入 `search_knowledge` / `MemoryTool` / `read_code` 作为额外工具。
- 不预注入整段代码（除非下游显式需要，如 `analyze_code_node` 独立分支仍按旧逻辑用 `source_code`）。
- 不在此轮实现多文件 `file` 的实际读取逻辑（仅 schema 预留）。
