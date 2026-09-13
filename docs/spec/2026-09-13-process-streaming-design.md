# 设计规格：过程式输出（阶段与工具调用实时可见）

> 依据：2026-09-13 联调实测。用户诉求原文：**「既然可以实现过程式的输出工具调用痕迹，
> 那么能否把 rag、思考内容等稍微渲染一下也过程式输出，而不是让用户等很久，最后全塞进下面的折叠板中」**。
> 本文档为设计侧产出，执行见 `docs/plan/2026-09-13-process-streaming-plan.md`。
> 一句话：**不引入 token 级流式、不改外壳、不改 Java 代理**，用「流中哨兵」让业务节点把
> 已发生的事实即时推到界面上。

## 1. 背景

### 1.1 现象

一次 data_query 提问耗时约 18s。这 18s 内界面只有一条**静态**文案
「正在分析代码并生成回答…」（由 Java 代理在 `message_start` 时写死），
结束后所有过程信息一次性出现在回答底部的【执行过程】折叠区。

时间都花在哪：RAG 检索 + N 轮 `propose`（LLM）+ `guard` + `run_tools` + 末轮 `propose`（LLM）
+ `critic`（LLM）+ `revise`（LLM）+ 组装。**每一段都是黑箱。**

### 1.2 用户诉求的边界

用户点名要「rag」与「思考内容」。**实测这两样当前都拿不出可用内容**，这是本设计必须
正面回答的前提（见 §3.6）：

- `reasoning` 在生产下**恒为空串**——propose 轮必须是纯 JSON，`parse_action` 严格解析，
  `_strip_tool_json` 剥掉 JSON 后不剩东西（已记档于
  `docs/reviews/2026-09-13-rag-observability-and-trace-process-review.md` §4）。
  流它 = 流出一串空行，比不流更糟。
- RAG 生产侧 `sources` **恒空**，四轮检索指标全 0，根因未定案（等 round-5）。

所以本设计**只流真实存在的事实**：阶段、工具调用、（末尾的）前瞻提示。
不流空内容，不为已知缺陷做粉饰。

---

## 2. 现状机制（写方案前必须确认的事实，均已核实）

### 2.1 只有一路流：`stream_mode="messages"`

平台外壳 `src/main.py`（**禁止修改**）经平台 SDK `AgentStreamRunner.astream`
固定使用 `stream_mode="messages"`（`.venv/.../helper/stream_runner.py`）。

> **2026-09-13 review 更正（原文已证伪，留痕）**：本节初稿写「该模式**只转发节点返回值
> `messages` 键里的消息**，聊天路径上 `build_final` 是**唯一**这样做的节点，
> propose / guard / run_tools / critic / revise **一个字节都出不到客户端**」——**三处都不成立**。
>
> **实测（review 2026-09-13 §1.1）**：`stream_mode="messages"` 会把节点返回值里**所有键**的
> 消息对象一起转出，**不只** `messages` 键。`agent_messages` 走 `add_messages` reducer，
> 故 propose / guard / run_tools 的消息**本来就在流上**：raw stream 里 `node=main_agent`
> 依次转出 `SystemMessage` / `HumanMessage` / `AIMessage`，`node=guard` 转出 `HumanMessage`。
> 平台 SDK（`agent_helper.py::_item_to_server_messages`）**只**过滤
> `langgraph_node == "tools"`，其余任何**非 chunk 的 `AIMessage`（content 非空）一律转成
> `answer` 且 `finish=True`**，无节点白名单；`SystemMessage` / `HumanMessage` 无对应分支被丢弃
> （这也是系统提示词与 guard 观察文本**没有**泄露的原因）。
>
> **推论（本设计的定位因此需要重新表述）**：
> 1. 这些节点的产出**并非「出不到客户端」**，而是**以原始形态（提案 JSON / 观察文本）
>    混进 `answer` 累加流**——这**正是**用户报告的那个 bug（见 review §1）；
> 2. 哨兵方案**依然成立且已实测有效**（五条哨兵按序抵达客户端）：它真正解决的问题不是
>    「打开一条不存在的通道」，而是**给过程事实一个可渲染的表示**，
>    并让前端能在渲染前把非同类的原生产出（提案 JSON）剥掉；
> 3. 因此 §3.3 的红线纪律要**扩大适用范围**：不只哨兵不得含被拒工具名，
>    **既有通道（`agent_messages` 的提案 delta）本身就是一条泄露路径**，
>    其根治不在本设计边界内（见 §6 遗留）。

`state.py:180-184` 对此有明确规定：

> `agent_messages` 是主 Agent 循环的累积消息序列……与 `messages` 分开：
> `messages` 是入站契约（`parse_context` 读其最后一条，平台 `stream_mode="messages"`
> 与它耦合），**不能被循环过程污染**。

**哨兵方案必须同时满足这两个看似矛盾的要求**：借用 `messages` 出流，
但不得污染入站契约。§3.4 是本设计的主要风险面，正面处理它。

### 2.2 中间 LLM 调用是**非流式**的

`src/graphs/javatutor/llm.py` 顶部注释自述：`llm_complete()` 走**原始 HTTP 调用，
绕过 ChatOpenAI，不会被 `stream_mode="messages"` 拦截`。这是 2026-08-11 泄露事故的修复产物
（`docs/devlog/2026-08-11-stream-fix.md`：意图分类/专家回答/评审/修订的 token 曾被全量转发）。

**推论（对本设计极为关键）**：propose / critic / revise 的产出都是**一次性**返回，
全链路**不存在 token 级流式**。因此「过程式输出」能做到的是
**「在 LLM 调用的间隙把已发生的事实推出去」**，而不是「边想边说」。

### 2.3 事件出口被 Java 代理收窄

前端**不直连** Coze。链路：

```
浏览器 POST /api/ai/chat
  → Java CozeAIController.chat()（SseEmitter）
  → Java CozeService.streamExplain()（HTTP 打 Coze v3 Chat API）
  → Coze 平台 SSE
```

Java 侧**只转发三种**：`answer`（→ `event:chunk`）、`message_start`（→ `event:stage`）、
`error`（→ `event:error`）。**其余类型静默丢弃。**

平台 SDK 其实已定义 `thinking` / `tool_request` / `tool_response`（`messages/server.py`），
但：
- `tool_request` 只在 `AIMessage.tool_calls`（LangChain 原生工具调用）非空时自动产生，
  而本仓 harness 是**自己解析 content 里的 JSON**，从不设 `.tool_calls`；
- 即便产生，Java 也会丢掉。

**走那条路必须改 Java 代理。** 本设计选择不改。

### 2.4 结论：唯一不碰外壳、不碰 Java 的出口

> 让**业务节点**把**哨兵消息**放进返回值的 `messages` 键，它作为普通 `type:answer` delta
> 流出 → Java 原样转发（`event:chunk`）→ 前端在**渲染前**拦下并转为进度 UI。

改动面 = coze 业务代码 + 前端。**零外壳、零 Java、零协议变更。**

---

## 3. 设计方案

### 3.1 哨兵格式

```
\n<!--jt:process {json}-->\n
```

- **HTML 注释**是关键取舍：即使前端**未**拦截（老前端 + 新 Agent），`marked.parse`
  也会把它渲染为不可见。**降级安全**——最坏情况是「没进度条」，而不是「界面上一堆乱码」。
  > **2026-09-13 实现回填（review §3 同意）**：机制比本节初稿的预期**更强**。
  > `frontend/src/utils/markdown.js::renderMarkdown` **不是**裸 `marked.parse(text)`，
  > 而是自定义 renderer，其 `html()` 返回空串——哨兵是**被直接丢弃**，而非「包成注释后不可见」。
  > 连带一条**非显然约束**：marked 的 HTML 块规则会吞掉注释**之后同一行的剩余部分**，
  > 故 `build_process_event` 返回串**两端**的 `\n` 是**承重**的（缺了它，
  > 与正文粘连的哨兵会把同行正文一起吃掉）。`markdown.test.js` 有专门用例钉住。
- 与既有三种末尾块（`【决策痕迹】`/`【编辑建议】`/`【视角导航】`）**性质不同**：
  哨兵是**流中**（inline）事件，一条回答里可有多个；
  它是**节点自己产生**的独立消息，**不参与** `_strip_structured_blocks`
  （那个函数在 `revised_answer`/`answer` 上工作，哨兵从不进入这两个字段）。

**事件 schema**（本期两种）：

```jsonc
// 覆盖式：界面只显示最新一条
{"kind":"stage","text":"正在分析问题…"}

// 追加式：进入过程日志，一条一个工具
{"kind":"tool","tool":"step_facts","args":{"step_index":4,"line":10},
 "status":"ok","latency_ms":120.5}
```

`kind` 为**开放集合**：将来新增 `reasoning` / `retrieval` 不必改协议（见 §3.6）。

### 3.2 发射点（**不新增图节点**）

图结构（`src/graphs/javatutor/graph.py:83-98`）：

```
parse_context → context_compaction → analyze_code →(route)→ load_session
  → retrieve_knowledge → build_context → main_agent ⇄ guard/run_tools
  → critic → revise → verify → save_session → final → END
```

| 节点 | 哨兵 | 位置是否成立 |
|---|---|---|
| `build_context` | `stage:"正在分析问题…"` | 其下一个节点即 `main_agent`（首次 LLM 调用）✓ |
| `retrieve_knowledge` | `stage:"已检索知识库：命中 N 条"` | 描述**已完成**的动作（N = `retrieval_debug["kept"]`）✓ |
| `run_tools` | 每个 observation 一条 `tool` 事件；**末尾**追加一条 `stage:"证据已就绪，正在生成回答…"` | 前者描述已完成；后者前瞻——其后的路径确实只剩 propose/critic/revise/verify/final ✓ |

**为什么不新增 `announce` 节点**：图节点的返回值在**节点体执行完毕之后**才流出，
所以「正在 X」式的前瞻文案只有放在 `run_tools` 末尾才成立（那里确实是长尾的起点）。
为每个 LLM 调用前置一个 announce 节点能拿到更细的粒度，但代价是**图结构变更**
（需同步 `docs/agent-collaboration-guide.md`、影响终止性论证的既有测试），
收益只是多几行低信息量的「思考中…」。**本期不做。**

**其余一律用「已完成」式描述**——不说假话。宁可写「已检索知识库：命中 0 条」，
也不写「正在检索…」（它会在检索**结束后**才出现）。

### 3.3 红线：被拒工具名不得入哨兵

哨兵走的是**用户可见通道**，与 `【决策痕迹】` 同级。因此：

- `tool` 事件的来源**必须**是 `run_tools` 里**真正执行过**的 observation
  （即 `step_records` 的同一份数据），**不得**来自 `state["proposed_action"]`
  ——后者可能含被门闩拒绝的提案（P1 未知工具 / P2 参数非法）。
- 沿用 `build_reasoning` 的既有纪律：`executed_tools` 白名单
  （`nodes.py:626-631` 从 `step_records` 里 `status == "ok"` 派生）。
- **`_redact_denied_tools` 罩不到哨兵**（它只作用于拼进 `answer` 的 trace JSON 段）。
  所以过滤必须在**发射点**做，不能指望兜底。这一点必须写进实现注释，
  否则将来有人会以为有第二道防线。
- **验证方式**（红线取证纪律）：端到端跑一次「模型提出未知工具」的畸形输入，
  断言最终 SSE 文本流里不含该工具名——不是断言哨兵构造函数。

### 3.4 状态卫生（本设计最主要的风险）

`state.messages` 是**入站契约**，且是 **checkpointer 的持久化字段**。
`build_context_node`（`nodes.py:684-700`）读 `state.messages[:-1][-5:]` 当对话历史。
哨兵若不清理，会**跨请求累积**，污染后续请求的上下文与 token 预算。

两道防线：

1. **authoritative —— `build_final` 清理**
   新增 `state["process_event_ids"]: list[str]`，发射哨兵时记录其 `id`
   （哨兵构造时**显式指定** id，形如 `jt-proc-{request_id}-{n}`，不依赖自动生成）。
   `build_final` 的返回值里带上对应的 `RemoveMessage(id=...)`：

   ```python
   return {"messages": [*removals, AIMessage(content=content)], ...}
   ```

   `RemoveMessage` **不是** `AIMessage`/`ToolMessage`，平台 SDK 的消息转换器会忽略它，
   不会额外下发；而哨兵本身**已经流出去了**（流是随节点执行产生的，清理发生在其后）。

2. **defensive —— `build_context_node` 过滤**
   取历史时按 `additional_kwargs.get("jt_process")` 跳过哨兵。
   即使防线 1 因 LangGraph 版本差异失效，跨请求污染也不会发生。

哨兵消息统一带 `additional_kwargs={"jt_process": True}` 作为可判别标记。

**已核无需改动**：`save_session`（`nodes.py:726-749`）只读 `answer` / `analysis_result` /
`step_memories`，**不读 `state.messages`**。

### 3.5 前端

| 文件 | 改动 |
|---|---|
| `src/utils/processEvents.js`（新建） | `extractProcessEvents(text) -> {clean, events}`：抽出所有哨兵、返回剥净文本与事件数组。单条 JSON 解析失败**丢弃该条**（不抛错，也不把哨兵留在 `clean` 里） |
| `src/stores/player.js` | `onChunk` 里**增量**解析：维护 `liveStage`（最新一条 stage，覆盖式）与 `liveTools`（tool 事件数组，追加式）。**不做每 chunk 全量重解析**（O(n²)） |
| `src/components/AiTutorPanel.vue` | ① 流式中的最后一条（`:67` 的 `renderMarkdown(m.text)`）改为渲染 `clean` 后的文本；② 复用既有 `chat-stage` 的样式与位置（`:88-91`）渲染实时进度：stage 覆盖显示、tool 事件逐行小字；③ 生成结束后清空实时区（信息由既有 `DecisionTracePanel` 的【执行过程】折叠区接管，数据来自 `decision_trace`） |
| `src/utils/decisionTrace.js` | `splitDecisionTrace` 得到的 `body` 再过一次 `extractProcessEvents`，保证终态也不漏出哨兵 |

**终态一致性**：实时区与【执行过程】折叠区是**同一份事实的两种呈现**，
数据来源不同（实时区来自流中的哨兵；折叠区来自 `decision_trace`），
所以**必须写一条回归**：一次带工具调用的提问，两边列出的工具集合一致
（`stage` 行不参与比较——折叠区没有 stage 概念）。

### 3.6 本期明确不做

| 项 | 理由 |
|---|---|
| 流 `reasoning`（思考内容） | propose 轮是纯 JSON，剥掉后 `content` **恒为空串**。流它等于流空行。**协议留位**（`kind` 开放），待 proposal 形态变化后另议 |
| 流 RAG 候选明细 | 生产侧 `sources` 恒空、根因未定案（等 round-5）。本期只发 `stage:"已检索知识库：命中 N 条"`——命中 0 就显示 0，不粉饰 |
| token 级流式 | `llm_complete` 是非流式；改它等于**重开 2026-08-11 的泄露面**，须单独评估 |
| 改 Java 代理 | 需要转发 `thinking`/`tool_request`/`tool_response`；本设计用哨兵绕开 |
| 改外壳 `src/main.py` | AGENT.md 禁止；哨兵路线完全不需要 |
| 新增图节点 | 见 §3.2 |

---

## 4. 影响面

| 层 | 文件 | 改动性质 |
|---|---|---|
| 工具 | `src/graphs/javatutor/process_events.py`（**新建**） | 哨兵构造与解析，纯函数，可脱离图单测 |
| 图 | `src/graphs/javatutor/nodes.py` | `build_context` / `retrieve_knowledge` / `build_final` 发射与清理哨兵；`build_context` 历史过滤 |
| 图 | `src/graphs/javatutor/harness/tools_node.py` | `run_tools` 发射 `tool` / `stage` 哨兵 |
| 状态 | `src/graphs/javatutor/state.py` | 新增 `process_event_ids: list[str]` |
| 前端 | `frontend/src/utils/processEvents.js`（新建）、`stores/player.js`、`components/AiTutorPanel.vue`、`utils/decisionTrace.js` | 拦截 + 实时进度 UI + 终态清理 |
| 契约 | `docs/agent-collaboration-guide.md` | 新增「过程哨兵」段落（**必须**，见 AGENT.md 规约） |

**不改**：外壳、Java 后端、`decision_trace` 的既有键与语义、
三种末尾结构化块的契约、`agent_messages` 的 ReAct 轨迹语义、图结构（节点与边）。

---

## 5. 验收标准

1. **可见**：一次触发 ≥1 次工具调用的提问，生成期间界面依次出现
   `正在分析问题…` → `已检索知识库：命中 N 条` → 每个工具一行 → `证据已就绪，正在生成回答…`。
2. **终态收敛**：回答结束后实时区清空，信息并入【执行过程】折叠区；
   两边的工具集合一致（§3.5）。
3. **降级安全（老前端 + 新 Agent）**：哨兵不可见，回答正文与现状一致。
4. **向后兼容（新前端 + 老 Agent，无哨兵）**：行为与现状**完全一致**，无空进度条。
5. **状态卫生**：`final` 之后 `state.messages` 不含哨兵；
   连续两次请求，第二次的 `build_context` 历史里不含哨兵。
6. **红线**：端到端跑一次「提出未知工具」的畸形输入，最终 SSE 文本流**不含**该工具名。

   > **2026-09-13 review 状态更新（判据保持不变，当前**未达标**）**：实测全链路 SSE 流里
   > **确实含**被拒工具名——它沿**既有**通道（`main_agent` 的提案 JSON，见 §2.1 更正）流出，
   > 与哨兵通道无关。**哨兵通道自身的红线是守住的**（`run_tools` 只从 `observations` 派生）。
   > 哨兵件交付时把用例收窄成「只查哨兵 delta」而记为通过，属**假绿**，已在
   > `docs/devlog/2026-09-13-process-streaming.md` §3.2 #6 改 ❌ 并说明。
   > 本条**不降级**：既有通道的根治（提案不随流下发）不在本设计边界内，见 §6。
7. **既有契约不回归**：`【视角导航】`/`【编辑建议】` 块正常渲染；
   `decision_trace` 既有键与语义不变。
8. **全绿**：`uv run pytest tests/ -q`（基线 368）与
   `cd javatutor/frontend && npx vitest run`（基线 390 / 29 files）。

---

## 6. 遗留

- **长尾覆盖粒度粗**：末轮 `propose` + `critic` + `revise` 三段 LLM 调用只有
  `证据已就绪，正在生成回答…` 一行盖住。要更细只能引入 token 级流式（需重开泄露面评估）。
- **`reasoning` 恒空是结构性的**，非本设计能解决（§3.6）。
- **RAG 阶段的语义待 round-5**：根因定案后，若检索恢复，可把
  「已检索知识库：命中 N 条」升级为带候选来源的行；协议无需变更。
- **实时区与折叠区的 stage 不对等**（折叠区无 stage 概念）是**有意**的：
  stage 是过程性提示，不构成「决策痕迹」的一部分，不写入 `decision_trace`。
