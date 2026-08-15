# 架构改进 Review 日志

> 审查对象：`feat/agent-architecture-improve` 分支执行结果
> 审查日期：2026-08-15

## 结论

架构改进主体已落地，102 项测试全部通过；动画模块移除、analyze_code 确定性节点、step_facts 工具、GSSC ContextBuilder、工作记忆、主 Agent 工具循环均已实现。但存在 2 个 P1 级问题：决策痕迹未输出 `tool_calls`/`token_usage`，RAG 未接入新图链路。修复前不建议跑端到端评测。

## 验证结果

```text
uv run pytest tests/ -v
=> 102 passed, 1 warning
```

覆盖：analyze_code、step_facts、memory、context_builder、main_agent、graph 集成、既有回归。

## 发现

### P1：决策痕迹缺少 tool_calls / token_usage

- `main_agent_node` 已返回 `tool_calls`，`state.py` 未声明 `tool_calls` 字段，`build_final` 的 trace 也未写入 `tool_calls` / `token_usage`。
- 影响：评估系统 M1.1 的 `tool_call_accuracy` / `avg_token_usage` 无法从决策痕迹读取。
- 修复方向：`state.py` 增加 `tool_calls: list`；`build_final` 把 `tool_calls` 与 `token_usage`（可用 `estimate_tokens` 估算，`estimated=true`）写入 trace。

### P1：RAG 未接入新图链路

- `retrieve_knowledge` 节点仍存在，但新 `graph.py` 未注册该节点；`build_context_node` 也未触发检索。
- 影响：`retrieved_chunks` 恒为空，Java 语料 RAG 与项目知识 RAG（spec D-14 / D-18）都没有进入上下文，概念问答会退化。
- 修复方向：在 `build_context` 之前插入 `retrieve_knowledge` 节点（或由 `build_context_node` 内部调用检索）。

### P2：对话历史未接入 ContextBuilder

- `build_context_node` 传入 `history=[]`，spec D-14 要求最近 5 轮。
- 修复方向：从 `state.messages` 提取最近 5 轮转换为 history 结构。

### P2：LLM 意图分类死代码

- `route_intent`、`intent.py`、`SYSTEM_PROMPT_INTENT` 及其测试仍存在，但新图已不用；spec D-09 已改为保守规则。
- 影响：维护混淆，评估 `intent_accuracy` 可能产生歧义。
- 修复方向：删除死代码或明确标注为兼容层。

### P3：工具调用参数未校验

- `main_agent_node` 直接 `step_facts(state, **args)`；`args` 含未知键或非整数值时可能抛异常；未知工具名会当作最终回答。
- 修复方向：`step_facts` 调用包 `try/except`；未知工具输出兜底提示。

### P3：save_session 使用 answer 而非 revised_answer

- 记忆写入用的是 `state["answer"]`，修订后的 `revised_answer` 未入库。
- 修复方向：改为 `state.get("revised_answer") or state.get("answer")`。

## 修复优先级

1. P1：决策痕迹补 `tool_calls` / `token_usage`。
2. P1：新图接入 RAG（`retrieve_knowledge`）。
3. P2：对话历史注入 ContextBuilder。
4. P2：清理 LLM 意图死代码。
5. P3：工具参数校验与 save_session 修订值。

修复完成后需重跑全量测试，并执行评估系统组件级评测。

## 第二轮 Review（2026-08-15）

### 验证结果

```text
uv run pytest tests/ -q
=> 95 passed, 1 warning
```

测试数由 102 降至 95，原因：`tests/test_intent.py`、`tests/test_route_intent.py` 随 LLM 意图死代码一起删除，符合预期。

### 修复确认

| 上轮发现 | 状态 |
|---|---|
| P1 决策痕迹缺 tool_calls / token_usage | ✅ `state` 增加字段；`build_final` 写入 trace；`_estimate_token_usage` 估算 |
| P1 RAG 未接入新图 | ✅ `graph` 在 `load_session` 与 `build_context` 之间注册 `retrieve_knowledge` |
| P2 对话历史未注入 | ✅ `build_context_node` 从 `messages[:-1][-5:]` 提取最近 5 轮 |
| P2 LLM 意图死代码 | ✅ 删除 `intent.py`、`route_intent`、`SYSTEM_PROMPT_INTENT` 及对应测试 |
| P3 工具参数校验 | ✅ `step_facts` 调用包 `try/except`；未知工具追加提示并继续回答 |
| P3 save_session 未用 revised_answer | ✅ 已改为 `revised_answer or answer` |

### 遗留建议（P3，不阻塞）

- `search_chunks` 内部吞掉异常并返回空列表，`retrieve_knowledge` 的 `rag_degraded` 可能永远为 `False`；建议让检索失败显式抛异常或由节点自行判定。
- `token_usage` 为估算值（`estimated=true`），端到端报告中建议同时保留 `token_usage_sample_count` 口径说明。

### 结论

架构改进已满足 spec/plan 主要验收点，建议进入端到端评测首轮基线。

## 修复状态（2026-08-15）

| # | 级别 | 修复 |
|---|---|---|
| P1-1 | P1 | ✅ `state.py` 增 `tool_calls`/`token_usage` 字段；`build_final` trace 写入两者（`_estimate_token_usage` 估算，`estimated=true`） |
| P1-2 | P1 | ✅ `graph.py` 注册 `retrieve_knowledge` 于 `load_session → build_context` 之间；`gather` 消费 `retrieved_chunks` 进入上下文 |
| P2-1 | P2 | ✅ `build_context_node` 提取最近 5 条历史传入 `build_context(history=...)` |
| P2-2 | P2 | ✅ 删除 `intent.py` / `SYSTEM_PROMPT_INTENT` / `route_intent` 及相关测试（13 用例） |
| P3-1 | P3 | ✅ `step_facts` 调用包 `try/except`；未知工具兜底继续循环，不泄露 JSON |
| P3-2 | P3 | ✅ `save_session` 改存 `revised_answer or answer` |

复验：`uv run pytest tests/ -q` → 95 passed；L1/L2.5/L3/L5 全绿。实现细节见 `docs/devlog/2026-08-15-agent-architecture-improvement.md`「Review 修复」节。
