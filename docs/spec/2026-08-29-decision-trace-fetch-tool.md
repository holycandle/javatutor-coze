# 决策痕迹记录 fetch_execution_context 工具调用设计

> 一句话：`fetch_execution_context` 是**确定性 graph 节点**，不进主 Agent 的 LLM 工具循环，所以它天然不会出现在 `tool_calls` 里；本设计在 `build_final` 里主动把它记录进 `tool_calls`，**前提是 Coze agent 重新发布后才生效**。

## 1. 背景与现象

用户反馈 bug：决策痕迹中「调用的工具」列表里**看不到 `fetch_execution_context`**，只有 `step_facts`。例如：

```
调用 step_facts：查询第 2 步，行 4
```

但这次问答明明走了按 `run_id` 拉取执行上下文的链路（回答用到了 `arr` 长度、第 2 步变量等执行数据）。期望痕迹里能看到「拉取执行上下文」这一次调用。

## 2. 根因分析

`fetch_execution_context` 在 `src/graphs/javatutor/graph.py` 里是**确定性 graph 节点**，而不是一个挂在主 Agent 上的 LLM 工具：

- 设计文档（`docs/spec/2026-08-23-execution-context-fetch-design.md` §6）原文：「新增 graph 节点 `fetch_execution_context_node`，确定性调用 `fetch_execution_context`，**不在主 Agent 工具循环中暴露为模型可选工具**。」
- 主 Agent 工具循环只 dispatch 一个 `step_facts`（`src/graphs/javatutor/main_agent.py`，`if tool["tool"] == "step_facts"`）。
- `tool_calls`（出现在 `build_final` 的 decision_trace 里）**只记录 LLM 工具循环里被调用的工具**。

因此 `fetch_execution_context` 作为一个确定性节点，**从不经过工具循环**，也就不会写进 `tool_calls`。这与设计一致——它不是「模型可选的工具」，而是「管线必跑的确定性拉取」。

## 3. 修复方案（已提交）

在 `src/graphs/javatutor/nodes.py` 的 `build_final`（第 414-419 行）里，当存在 `run_id` 时主动把这次确定性拉取补进 `tool_calls` 首位：

```python
run_id = state.get("run_id", "")
# fetch_execution_context 是确定性 graph 节点（非 LLM 工具调用），其调用不进入主 Agent 的
# tool_calls。这里主动记录，让决策痕迹里能看到这次拉取发生了。
tool_calls = state.get("tool_calls") or []
if run_id:
    tool_calls = [{"tool": "fetch_execution_context", "args": {"run_id": run_id}}, *tool_calls]
```

对应决策痕迹输出变为：

```json
"tool_calls": [
  {"tool": "fetch_execution_context", "args": {"run_id": "3f8a2c0d-..."}},
  {"tool": "step_facts", "args": {"step_index": 1, "line": 4}}
]
```

前端 `formatToolCall`（`frontend/src/utils/decisionTrace.js`）对非 `step_facts` 工具走通用分支，会渲染为 `调用 fetch_execution_context：run_id=...`，**无需改前端**。

已随提交 `aa30ea6`（coze 仓）落地，并补了测试：
- `tests/test_build_final.py::test_build_final_records_fetch_execution_context_in_tool_calls`
- `tests/test_build_final.py::test_build_final_no_run_id_does_not_record_fetch_tool`

协作指南「输入输出」也已同步说明此事。

## 4. 为何「部署了最新版」却仍不显示（关键）

这是本次 bug 排查最容易踩的坑：**部署 ≠ 一个仓库**。本修复涉及两个独立部署单元：

| 部署单元 | 仓库 | 修复是否在此 | 如何生效 |
|---|---|---|---|
| JavaTutor 后端 + 前端 | `Curse-strickland/javatutor` | 本 bug **不在**这里 | 常规构建/部署 |
| **Coze agent 逻辑** | `holycandle/javatutor-coze` | **是**（`nodes.py` 的 `build_final`） | **必须在 Coze 平台重新发布 agent** |

前端能正常渲染决策痕迹（`AiTutorPanel.vue` / `decisionTrace.js`）说明 JavaTutor 前端已部署；但 `tool_calls` 是否包含 `fetch_execution_context` 取决于 **`javatutor-coze` 的 graph 代码**是否被 Coze 侧重新发布。若 agent 只是旧版在跑，`build_final` 仍执行旧逻辑，自然看不到。

## 5. 部署与验证清单

以下任一情形即说明发布的是旧版 agent：

- [ ] 在 Coze 平台重新发布（重新训练/发布）`javatutor-coze` 的 agent。
- [ ] 重新发布后，用一处带 `run_id` 的提问触发问答。
- [ ] 检查决策痕迹第一条工具行是否为 `调用 fetch_execution_context：run_id=...`。
- [ ] 若仍只有 `step_facts`：确认该问答确实是走 `fetch_execution_context` 拉取（而非旧 payload 直传），且 `build_final` 能读到 `run_id`（`run_id` 为空时本设计不记录，属边界——但那种情况下 fetch 也无法工作，回答不会带出执行数据）。

## 6. 设计说明：为何「记录」而非「暴露为 LLM 工具」

有人会问：干脆把 `fetch_execution_context` 也挂成主 Agent 工具得了，它自然就进 `tool_calls` 了。**不做**，理由：

1. **执行上下文是事实基础**，应由管线确定性获取，不能由 LLM 决定「要不要拉、何时拉」——否则模型可能跳过，或问出误导性子查询。
2. 拉取结果（源码、steps、当前步）本来就是上下文工程的**预加载**输入，不是按需变化的证据，和 `step_facts` 的 JIT 定位不同（见「信息分层原则」）。
3. 若暴露成工具，`step_memories`、工具循环轮次、评审边界都会变复杂；用「痕迹记录」在**不改变运行时行为**的前提下满足可观测性，改动最小。

所以结论：**`fetch_execution_context` 的调用信息以「决策痕迹记录」形式呈现，而不是以「模型可选工具」形式暴露。** 这一原则要在协作指南里维持。
