# 2026-09-13 回答裸 JSON 剥离 + 过程式输出 — 执行审查

> 审查对象：`javatutor-coze` 工作区 + `javatutor/frontend` 工作区；后端与外壳未改动
> 对应计划：`docs/plan/2026-09-13-strip-answer-leading-tool-json-plan.md`、`docs/plan/2026-09-13-process-streaming-plan.md`
> 对应设计：`docs/spec/2026-09-13-process-streaming-design.md`
> 实现记录：`docs/devlog/2026-09-13-strip-answer-leading-tool-json.md`、`docs/devlog/2026-09-13-process-streaming.md`

## 结论

**过程式输出（哨兵）这一件实现质量高**：独立复跑 coze **407 passed** / 前端 **415 passed / 31 files**，
与 devlog 数字全部吻合；4 处计划偏差**都是改进**，其中「规则 1b」补的是**我计划自身代码片段的漏洞**
（见 §3）。哨兵通道经真实图 + SDK 全链路实测**按正确顺序流出**（阶段 → 工具 → 前瞻 → 终答）。

**但「回答裸 JSON 剥离」这一件没有达成目标。** 用户报告的症状（「回答顶端的工具调用痕迹是裸 json，
结尾也没有换行」）的**可复现主因不是**模型在终答里复述 JSON，**而是既有的「提案 JSON 随 `answer`
delta 流出 + 前端纯累加」**。剥离函数作用在 `state["answer"]`（`nodes.py:685`），**够不到流**。
连带 devlog §3.2 把红线验收 #6 标成 ✅ 属**假绿**——全链路 SSE 流里确实含被拒工具名。

- **1 P1**：报告 bug 根因未命中 + 红线验收假绿
- **1 P2**：终答在客户端流里下发两次（同根因）
- **2 P3**：节点名与 SDK 过滤器的隐式耦合、哨兵解析的跨 chunk 假定

---

## 独立复现的验证（非引用 devlog）

| 项 | 命令 / 方法 | 结果 |
|---|---|---|
| coze | `uv run pytest tests/ -q` | **407 passed**（基线 368，与 devlog 一致） |
| 前端 | `cd javatutor/frontend && npx vitest run` | **415 passed / 31 files**（基线 390/29，一致） |
| 报告 bug 端到端复现 | 真实图 + `agent_iter_server_messages` 全链路 + 模拟前端累加（§1.1） | **复现出与截图同形的产物** |
| 生产链路核对 | `src/main.py:161` → `stream_runner.py:76-77` | 与复现所用路径**同一条** |
| 哨兵出流顺序 | 同上全链路，逐 delta 打印 | `知识库不可用` → `正在分析问题…` → 2 条 `tool` → `证据已就绪…` → 终答 ✅ |
| 依赖锁 | `pyproject.toml` / `uv.lock` / `package.json` | 未改动 |

---

## 1. P1：报告 bug 的根因未命中，且红线验收假绿

### 1.1 机制（每一环都实测过，非推演）

1. `propose()` 把模型**原始输出**（提案 JSON）放进 `AIMessage` 塞进 `agent_messages`：
   `propose.py:104` → `out_messages = history + [AIMessage(content=resp)]`。
2. LangGraph `stream_mode="messages"` **会把节点返回值里所有键的消息对象都转出**，不只 `messages` 键。
   实测 raw stream：`node=main_agent` 依次转出 `SystemMessage` / `HumanMessage` / `AIMessage`；
   `node=guard` 转出 `HumanMessage`。（`agent_messages` 走 `add_messages` reducer，故在内。）
3. 平台 SDK `agent_helper.py::_item_to_server_messages` **只**过滤 `langgraph_node == "tools"`；
   其余任何**非 chunk 的 `AIMessage`（content 非空）一律转成 `answer` 且 `finish=True`**，无节点白名单。
   `SystemMessage` / `HumanMessage` 无对应分支，被丢弃——所以系统提示词与 guard 观察文本**没有**泄露。
4. 前端 `player.js:521` 是**纯累加**：`this.chatMessages[assistantIdx].text += t`，
   **无分隔符、无重置**（全文唯一一处 `.text =` 在 `:454`，是门禁返修路径）。
5. `AiTutorPanel.vue:67` 渲染 `renderMarkdown(streamText(m.text))`，而 `streamText` **只剥哨兵**。

复现产物（真实图 + SDK 全链路 + 步骤 4/5 的客户端处理）：

```text
{"tool": "step_facts", "args": {"step_index": 1}}### 当前这一步的执行内容\n\nx 从 1 变成了 2。…
```

与截图里的 `{"tool": "fetch_execution_context", "args": {"file": "Main.java"}}### 当前这一步的执行内容`
**同形同因**：`}}###` 的粘连**不是**模型少打了个换行，而是 `+=` 本身不插分隔符。

### 1.2 为什么剥离修不到

`_strip_leaked_json` 的唯一调用点是 `nodes.py:685`，作用对象是 `state["answer"]` / `revised_answer`。
而上述 JSON **从不进入 `state["answer"]`**——它是 `main_agent` 的中间 AIMessage，**直接走在流上**。
所以规则 0 / 1b 写得再对，也清不掉客户端实际渲染的那一份。

> 剥离本身实现无误（平衡解析、`obj.get("tool")` 判别、补分隔换行、规则 1b），只是**作用域不覆盖症状来源**。

### 1.3 「会被顶掉」这个前提不成立

`tests/test_harness_loop.py` 的 docstring 写：

> 真正的用户可见产物是 ``build_final`` 的完整回答（**提案 delta 会被它整体顶掉**）

**不成立。** 前端没有任何「顶掉」逻辑（§1.1 第 4 步）。`build_final` 只是**再追加**一条含终答 + 痕迹的
`answer`，前面的提案 delta 原样留在累加结果里。同一误解也写在 `build_final` 的既有 docstring 里
（「确保客户端只看到最终回答…不泄露中间 LLM 调用内容」）——从 SDK 行为看，这句**一直**不成立。

### 1.4 连带：验收 #6 假绿

spec §5-6 的判据是「被拒工具名不入**任何用户可见产物**」「最终 SSE 文本流**不含**该工具名」。
实测（含执行方自己那条 `test_proposal_json_delta_reaches_client_and_predates_sentinels`）
**流里就是含** `no_such_tool`。执行方把红线用例收窄成「只查哨兵 delta」后记为 ✅，
但 spec 的判据是**全流**。devlog §3.2 的 #6 ✅ 应改为 ❌ 并注明是**既有**违规。

> 公允地说：**哨兵通道自身的红线是守住的**（`test_client_stream_never_names_a_denied_tool_in_a_sentinel`
> 有效，且 `run_tools_node` 确实只从 `observations` 取、不从 `proposed_action` 取）。
> 问题**全部**在既有通道，不在本件新引入的通道。

### 1.5 建议

作为**独立一件**处理（不在本两件边界内）：

- **最小修复**：前端渲染路径在剥完哨兵后，再跑一次「开头的工具 JSON」剥离（等价 `_strip_leaked_json` 规则 0）。
  因哨兵已被剥净，提案 JSON 会**正好落在正文开头**，规则 0 即可命中，成本极低。
- **治本**：让提案不随流下发（`agent_messages` 是必需 state，需另想办法），或前端在收到含
  `【决策痕迹】` 的终态消息时**以其为准整体替换**累加文本（同时解决 §2）。
- 无论选哪条，都必须按**红线取证纪律**以**全链路流**取证，不能用 `state["answer"]` 代替。

---

## 2. P2：终答在客户端流里下发两次（同根因）

`main_agent` 的**终答** AIMessage 与 `final` 的 AIMessage 都会被转成 `answer`。
实测 deltas 末两条内容重复。生产表现为：`critic`/`revise` 未改写正文时用户看到**完全相同的两段**；
改写时看到「草稿 + 终稿」两段依次渲染。

既有行为、非本两件引入，但**用户可见**，且与 §1 是**同一处修复点**。

---

## 3. 计划偏差复核（4 处，均为改进）

| # | 偏差 | 复核 |
|---|---|---|
| 1 | `_strip_leading_tool_json` 提为具名函数，并在规则 1 之后再调一次（**规则 1b**） | **实现优于计划。** 我计划 §2 的代码片段只在规则 1 前调一次，而计划**自己的**用例 #6（`{"intent":…}\n\n{"tool":…}\n\n正文`）要求规则 1 之后再调一次——**执行方发现并补上了我计划自身的漏洞**，注释也写清了原因。✅ |
| 2 | 哨兵 `id` 显式化，`seq` 由调用方给（`with_process_events` 用 `len(existing)+i`） | **真 bug 的正确处置。** 起初在 `process_message` 内部用 `len(process_event_ids)` 自增，同批事件各自算出**同一 id**，`add_messages` 按 id 去重**静默丢事件**（实测 3 条只剩 1 条）。这类 bug 单测抓不到，只有端到端数事件才暴露。✅ |
| 3 | `_escape_terminator` 转义负载内 `-->` | 防解析正则提前截断；构造侧与前端解析侧口径一致。✅ |
| 4 | 前端新建 `stores/__tests__/player-live-progress.test.js` 而非追加 `player.test.js`；实时区由单行改两行块 | 结构更清晰、视觉向后兼容。✅ |

另核实：`renderMarkdown` 对哨兵是**丢弃**（`html() { return '' }`）而非 spec §3.1 预期的「包成注释」。
结论比预期更强（降级更安全），且暴露「哨兵两侧 `\n` 承重」这条非显然约束并已加用例钉住。**同意**，
spec §3.1 的措辞可回填。

---

## 4. P3

### P3-1：节点名与 SDK 过滤器的隐式耦合

SDK 的过滤器是 `if meta["langgraph_node"] == "tools": return []`（注释自述
「prevent internal model outputs from leaking as answers」），针对的是 LangGraph 标准 ReAct 的 `tools` 节点名。
本仓节点注册为 **`"run_tools"`**（`graph.py:75`），**恰好不匹配**——所以哨兵能出流（特性成立），
但也意味着：**一旦有人把节点改名成 `tools`，`run_tools` 的全部哨兵会被 SDK 静默吞掉**，
表现为「进度条停在『正在分析问题…』」，且不会有任何报错。
建议在 `run_tools_node` 的注释里写明这条外部约束。

### P3-2：哨兵解析假定「不跨 chunk 切开」

前端按 chunk 独立解析哨兵，注释断言「哨兵是单条完整消息…不会跨 chunk 被切开」。
该断言依赖 Java 代理不做分片转发——**超出本仓控制面**。
降级后果可接受（哨兵是 HTML 注释，`marked` 的 `html()` 返回空串，最坏是丢一条进度而非漏出乱码），
但断言本身应改为「假定」，并在联调时留意。

---

## 5. 遗留复核（与两份 devlog 一致）

- **L4 SKIP / 首屏未实测**：devlog §3.4 已诚实标注「改动后的时间线是推演，非实测」。**同意**该标注——
  且需与 §1 合并看：**真机联调前，用户实际看到的首屏仍会带提案 JSON**。
- **Task 9（重发 agent）未做**：部署侧现在既看不到哨兵、也看不到剥离。两份 devlog 的 ✅ 都只对**离线**成立。
- **`reasoning` 恒空 / RAG 明细留位**：结构性，同意不做。
- **既有提案 JSON 泄露**：devlog §2.3 记为「此发现需上报用户」并留待单独评估——**处理方式正确**。
  本审查的 §1 是把这条遗留**升级**为「它正是用户报告的那个 bug」，不是指控隐瞒；
  devlog 的诚实性没有问题，**问题在于 devlog §3.2 误把收窄后的用例当作 spec #6 已通过**。

---

## 6. 处置清单

| # | 级别 | 事项 | 建议动作 |
|---|---|---|---|
| 1 | P1 | 报告 bug 根因未命中（提案 delta 前置 + 前端纯累加） | 单独出计划；前端渲染路径补「开头工具 JSON 剥离」或终态整体替换 |
| 2 | P1 | spec §5-6 红线假绿（全流含被拒工具名） | devlog §3.2 #6 由 ✅ 改 ❌，注明是**既有**违规、非本件引入 |
| 3 | P2 | 终答下发两次（草稿 + 终稿） | 与 #1 同一处修复 |
| 4 | P3 | 节点名 `run_tools` 与 SDK `tools` 过滤器的隐式耦合 | 在 `run_tools_node` 注释写明该外部约束 |
| 5 | P3 | 「哨兵不跨 chunk」是假定而非保证 | 措辞由断言改为「假定」，联调时留意 |
