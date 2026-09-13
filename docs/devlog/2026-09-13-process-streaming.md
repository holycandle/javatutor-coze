# 2026-09-13 过程式输出（阶段与工具调用实时可见）— 实施记录

> 设计：`docs/spec/2026-09-13-process-streaming-design.md`
> 计划：`docs/plan/2026-09-13-process-streaming-plan.md`（Task 1–8）
>
> 用户诉求原文：「既然可以实现过程式的输出工具调用痕迹，那么能否把 rag、思考内容等稍微
> 渲染一下也过程式输出，而不是让用户等很久，最后全塞进下面的折叠板中」。

**跨两仓**：coze `javatutor-coze`（Task 1–5）+ 前端 `javatutor/frontend`（Task 6–7）。

交付边界：到**离线全绿**为止（L1–L5 + 前端 vitest）。**不含**重新发布 agent。

## 1. 做了什么

### 1.1 一句话

业务节点把**已发生的事实**（阶段、工具调用）包成 HTML 注释**哨兵**放进返回值的
`messages` 键，借既有 `stream_mode="messages"` 通道流出 → Java 代理原样转发
（`event:chunk`）→ 前端**渲染前**拦下转为实时进度 UI。

**零外壳、零 Java、零协议变更、零新依赖、零图结构变更。**

### 1.2 哨兵格式

```
\n<!--jt:process {"kind":"stage","text":"正在分析问题…"}-->\n
```

HTML 注释是**降级安全**的关键取舍：老前端不拦它，`marked.parse` 也渲染为不可见，
最坏情况是「没有进度条」而不是「界面一堆乱码」。

| kind | 语义 | 负载 |
|---|---|---|
| `stage` | 覆盖式（界面只显示最新一条） | `{"kind":"stage","text":"..."}` |
| `tool` | 追加式（一条一个工具，进过程日志） | `{"kind":"tool","tool":"...","args":{...},"status":"ok","latency_ms":120.5}` |

`kind` 是**开放集合**：将来加 `reasoning` / `retrieval` 不必改协议。

### 1.3 三个发射点（**不新增图节点**）

| 节点 | 哨兵 | 为什么位置成立 |
|---|---|---|
| `retrieve_knowledge` | `stage:"已检索知识库：命中 N 条"`（N = `retrieval_debug["kept"]`） | 描述**已完成**的动作 |
| `build_context` | `stage:"正在分析问题…"` | 其下一个节点即 `main_agent`（首次 LLM 调用） |
| `run_tools` | 每个 observation 一条 `tool` 事件 + 末尾一条 `stage:"证据已就绪，正在生成回答…"` | 前者描述已完成；后者**前瞻**——其后的路径确实只剩 propose/critic/revise/verify/final |

降级分支（检索不可用）发 `"知识库检索不可用，已用通用知识回答"`——与
`decisionTrace.js` 既有文案一致。

**其余一律用「已完成」式描述**：宁可写「已检索知识库：命中 0 条」，也不写「正在检索…」
（它会在检索**结束后**才出现）。

### 1.4 状态卫生（本设计最主要的风险面，两道防线）

`state.messages` 是**入站契约**也是 **checkpointer 持久化字段**，
`build_context_node` 读它的历史当对话上下文。哨兵不清理会跨请求累积。

1. **authoritative —— `build_final` 清理**：新增 `state["process_event_ids"]`,
   发射时登记哨兵 `id`（形如 `jt-proc-{request_started_at}-{seq}`），
   `build_final` 用 `RemoveMessage(id=...)` 精确清除，随后把字段重置为 `[]`。
2. **defensive —— `build_context_node` 过滤**：取历史时跳过
   `additional_kwargs["jt_process"] is True` 的消息。即使防线 1 因 LangGraph 版本差异失效，
   跨请求污染也不会发生。

**已核无需改动**：`save_session` 不读 `state.messages`。

### 1.5 前端

| 文件 | 改动 |
|---|---|
| `src/utils/processEvents.js`（新建） | `extractProcessEvents(text) -> {clean, events}` + `applyProcessEvents(state, events)` |
| `src/stores/player.js` | 新增 `liveStage` / `liveTools`；`onChunk` **增量**解析；提问开头与 `finally` 重置 |
| `src/components/AiTutorPanel.vue` | 流式末条渲染 `clean` 文本；`chat-stage` 复用为实时进度（stage 一行 + 工具逐行小字） |
| `src/utils/decisionTrace.js` | `splitDecisionTrace` 的 `body` 再过一次 `extractProcessEvents`（终态不漏） |

### 1.6 改动清单

coze：

- `src/graphs/javatutor/process_events.py`（**新建**）：`build_process_event` /
  `parse_process_events` / `process_message` / `with_process_events` / `PROCESS_KWARG`。
  纯 stdlib + `langchain_core.messages`，**不 import 任何图内模块**（可脱离图单测）。
- `src/graphs/javatutor/state.py`：`process_event_ids: list[str]`。
- `src/graphs/javatutor/nodes.py`：`retrieve_knowledge` / `build_context_node` 发射；
  `build_context_node` 历史过滤；`build_final` 清理。
- `src/graphs/javatutor/harness/tools_node.py`：`run_tools_node` 发射。
- `docs/agent-collaboration-guide.md`：新增「过程哨兵」小节 + 节点表 / 状态字段表同步。

前端：上表 4 个文件 + `markdown.test.js` / `decisionTrace.test.js` 追加用例。

## 2. 关键实现发现（都是实测踩出来的，不是推演）

### 2.1 **同批哨兵 id 重复 → 静默丢事件**（严重）

`with_process_events` 起初在 `process_message` 内部用
`len(state.get("process_event_ids") or [])` 当序号。**同一次发射的多条事件各自算出同一个
id**，`add_messages` 按 id 去重只留最后一条——`run_tools` 的 3 条事件实测只剩 1 条。

改为由调用方显式传 `seq = len(existing) + i`。这类 bug **单测抓不到**
（构造函数返回的每条消息单看都正确），只有端到端观察事件条数才暴露。

### 2.2 `renderMarkdown` 是**丢弃**哨兵，不是包成注释（计划偏差）

spec §3.1 预期「老前端渲染为 `<!-- -->`（浏览器不可见）」。
实测 `frontend/src/utils/markdown.js` 用的是自定义 marked renderer，
`html() { return '' }` —— 哨兵**直接被丢掉**。结论比 spec 预期更强（降级更安全），
但机制不同，故记偏差。

**连带的坑**：marked 的 HTML 块规则会吞掉注释**之后的整行剩余部分**。
因此 `build_process_event` 在两端的 `\n` 是**承重的**，不是装饰——
少了它，一个与正文粘连的哨兵会把同一行的正文一起吃掉。
`markdown.test.js` 有一条用例专门钉住这个行为。

### 2.3 `stream_mode="messages"` 也流 `agent_messages`（既有泄露，非本件引入）

写红线用例时发现：`main_agent` 的**提案 JSON**（`agent_messages` 里的 `AIMessage`）
也会作为 `answer` delta 流到客户端。用 `git diff --name-only | grep -c propose` 核对
`propose.py` 未被本件改动 → **既有行为**，与本设计无关。

处置：不掩盖、不顺手改（超出本计划边界）。拆成两条用例——
`test_client_stream_never_names_a_denied_tool_in_a_sentinel`（窄口径：只查哨兵 delta，
红线）与 `test_proposal_json_delta_reaches_client_and_predates_sentinels`（钉住既有行为，
留待后续单独评估）。**此发现需上报用户。**

**review 2026-09-13 §1 把它从「遗留」升级为「用户报告的那个 bug」，并补全了机制**：
LangGraph `stream_mode="messages"` 会把节点返回值里**所有键**的消息对象都转出（不只
`messages` 键）；SDK 侧**只**过滤 `langgraph_node == "tools"`，其余任何非 chunk 的
`AIMessage`（content 非空）**一律**转成 `answer`、`finish=True`，无节点白名单
（`SystemMessage`/`HumanMessage` 无对应分支被丢弃，所以系统提示词没泄露）。
前端 `player.js` 纯累加（无分隔符、无重置），`AiTutorPanel.vue` 的 `streamText` **只剥哨兵**
→ 提案 JSON 与标题粘连成 `}}###`。**修复超出本两件边界，见 §5。**

同时更正一条既有认知：`tests/test_harness_loop.py` 与 `build_final` 的 docstring 曾写
「提案 delta 会被终答整体顶掉」「确保客户端只看到最终回答」——**不成立**，
前端没有任何「顶掉」逻辑（review §1.3）。**review 处置时已一并改写**这两处 docstring，
并顺手更正了另外三处同源误述（`process_events.py` 模块 docstring、
`agent-collaboration-guide.md`、`2026-09-13-rag-observability-and-trace-process-design.md` §2.4），
全部保留「原文已证伪」的留痕式标注——见 §5.4。

### 2.4 前端 SSE 解析器的 flush 时序

`stores/player.js::_runChat` 只在**遇到下一条 `event:` 行或流结束时**才把累积的 `data:`
交给 `onChunk`（空行分支是 no-op）；且 SSE 规范要求 chunk 内每个换行拆成独立 `data:` 行。
写测试时按这两点复现时序，否则断言永远「差一条」。

### 2.5 SDK 转换路径已实测（先证后建）

在动手前核实了平台 SDK 的转换路径
（`.venv/.../coze_coding_utils/helper/agent_helper.py`）：
`:312-318` 的 `AIMessage` 分支把整条 content 作为 `answer` 消息、`finish=True` 下发——
哨兵走的正是这条；且 `message_end` 仍最后到达，流不会被提前终止。
验证用的是**全链路** `agent_iter_server_messages`，不是裸 `.stream()`。

## 3. 验证

### 3.1 全绿

| 门 | 结果 |
|---|---|
| coze `uv run pytest tests/ -q` | **407 passed**（基线 368，+39） |
| 前端 `npx vitest run` | **431 passed / 32 files**（基线 390 / 29 files；+41 / +3 files，含 review 处置新增的 16 例） |
| 前端 `npm run build` | ok |
| 依赖锁 | `pyproject.toml` / `uv.lock` / `package.json` 均未改动 |
| `dist/` | gitignored，未入库 |

新增测试文件：coze `tests/test_process_events.py`（13）、`tests/test_nodes.py`（8，Plan B）；
前端 `src/utils/processEvents.test.js`（11）、`src/stores/__tests__/player-live-progress.test.js`（8）、
`src/utils/stripLeadingToolJson.test.js`（16，review 处置）。

### 3.2 验收项对照（spec §5）

| # | 验收项 | 取证 | 结果 |
|---|---|---|---|
| 1 | 生成期间可见 4 类进度 | **待联调实测**（见 3.4） | ⏳ |
| 2 | 实时区与折叠区工具集合一致 | `player-live-progress.test.js` 终态一致性用例 | ✅ |
| 3 | 老前端 + 新 Agent：哨兵不可见 | `markdown.test.js` 3 例 | ✅（机制是丢弃，见 2.2） |
| 4 | 新前端 + 老 Agent：行为不变 | `player-live-progress.test.js` L4 用例 | ✅ |
| 5 | `state.messages` 无哨兵残留 | `test_harness_loop.py` 三条（含同 thread 二次请求）+ `test_graph.py` RemoveMessage 靶向 | ✅ |
| 6 | 被拒工具名不入用户可见产物 | `test_harness_loop.py` 端到端红线（`agent_iter_server_messages` 全链路） | ❌ **既有违规**（见 4.2 与 review §1） |
| 7 | 导航 / 编辑建议块不回归 | 既有用例（未改这两条路径） | ✅ |
| 8 | 双侧全绿 | 见 3.1 | ✅ |

**红线取证纪律**：#5 与 #6 都以**端到端产物**取证（全链路 SDK 流 / checkpointer 复用同一
`thread_id` 的第二次请求），不只停在函数返回值层。

**但 #6 的结论是 ❌，且这是我初稿的过失。** 全链路 SSE 流里**确实含**被拒工具名
（`no_such_tool`）——它沿**既有**通道（`main_agent` 的提案 JSON）流出，与本件新引入的
哨兵通道无关。我写红线用例时发现该泄露后，把用例**收窄**成「只查哨兵 delta」并记为 ✅，
而 spec §5-6 的判据是「**任何**用户可见产物」「**最终 SSE 文本流不含**」。
**收窄后的通过不等于原判据通过**——这是一次假绿，review §1.4 指出，本处更正。
哨兵通道**自身**的红线是守住的（`test_client_stream_never_names_a_denied_tool_in_a_sentinel`
有效，`run_tools_node` 确实只从 `observations` 取、不从 `proposed_action` 取）。

### 3.3 本地规约门槛（L1–L5）

| 门 | 结果 |
|---|---|
| L1 | pass |
| L2（coze 单测） | 407 passed |
| L2.5 | 2 passed |
| L3（前端构建 / 测试） | ok / 431 passed |
| L4（coze 本地 HTTP 冒烟） | **SKIP** |
| L5（外壳检查） | **0 命中** ✅ |

### 3.4 首屏时间线对照（**after 列为推演，非实测**）

改动前的实测基线（spec §1.1，2026-09-13 联调）：一次 data_query 提问约 **18s**，
这 18s 内界面**只有一条静态文案**「正在分析代码并生成回答…」（Java 代理在
`message_start` 时写死），结束后所有过程信息**一次性**出现在底部【执行过程】折叠区。

| 时刻 | 改动前 | 改动后（按发射点位置推演） |
|---|---|---|
| t≈0 | 「正在分析代码并生成回答…」 | 「正在分析代码并生成回答…」（Java 写死，不变） |
| t≈0+（RAG 后） | 同上（无变化） | `已检索知识库：命中 N 条` |
| t≈0+（上下文组装后） | 同上（无变化） | `正在分析问题…` |
| 每轮工具执行后 | 同上（无变化） | 每个工具一行（`step_facts` / `fetch_execution_context` …） |
| t≈末轮起 | 同上（无变化） | `证据已就绪，正在生成回答…` |
| t≈18s | 一次性全塞进折叠区 | 折叠区接管，实时区随 `isExplaining=false` 清空 |

**诚实标注**：改动后这一列是**由发射点在图中的位置推导**的，**不是**一次真实联调的实测——
L4 未跑（见 3.3、4.2），无模型端点故无法在本地复现 18s 全链路。
真正的实测要等**重新发布 agent + 联调窗口**。spec §5-1 因此在本件标记为 ⏳。

## 4. 与计划的偏差与遗留

### 4.1 偏差（4 处）

1. **`renderMarkdown` 丢弃而非包裹哨兵**（见 2.2）——机制不同、结论更强，
   且暴露了「哨兵两侧 `\n` 承重」这条非显然约束，已加用例钉住。
2. **`build_context_node` 的防御过滤放在了 `with_process_events` 之外**：
   计划把它描述为「循环里 `continue`」，实现上等价（先过滤 `prior` 再切片 `[-5:]`），
   但顺序有别——**必须先按标记过滤、再取 `[-5:]`**，否则被跳过的哨兵会占掉历史槽位。
3. **前端实时区渲染成两行块而非单行**：`chat-stage` 原本是 `align-items: center` 的单行，
   加入工具列表后改为 `flex-start` + `.chat-stage-body` 容器。视觉向后兼容，
   但 CSS 有新增规则（计划只写了「复用样式」）。
4. **测试文件名**：计划写 `stores/player.test.js` 追加，实际新建
   `stores/__tests__/player-live-progress.test.js`——既有 `player.test.js` 无此目录，
   且实时进度是独立关注点，新文件更好定位。

### 4.2 遗留

- **L4 未跑（高风险留白）**：需要模型端点 + PostgreSQL，且会发起外部调用，
  故本件标记 SKIP 交由用户决定。**这意味着「首屏真的能看到进度」尚未在真实链路上验证过**
  ——单测覆盖了每一段（哨兵生成、流出、解析、渲染），但没有一次端到端的真实 18s 观测。
- **长尾覆盖粒度粗**：末轮 `propose` + `critic` + `revise` 三段 LLM 调用只有
  `证据已就绪，正在生成回答…` 一行盖住。要更细只能引入 token 级流式
  （需重开 2026-08-11 的泄露面评估）。
- **`reasoning` 恒空是结构性的**：propose 轮必须是纯 JSON，剥掉后 `content` 为空串。
  协议 `kind` 已留位，待 proposal 形态变化后另议。
- **RAG 明细流式留位**：生产侧 `sources` 恒空、根因未定案（等 round-5）。
  本期只发 `命中 N 条`——命中 0 就显示 0，不粉饰。
- **既有提案 JSON 泄露（review 已升级为 P1——它正是用户报告的那个 bug）**（见 2.3）：
  `main_agent` 的提案 JSON 会作为 `answer` delta 流到客户端，早于哨兵，
  且前端是**纯累加**（`player.js` 的 `.text += t`，无分隔符、无重置），
  于是用户看到 `{"tool": "..."}}### 当前这一步的执行内容` 这样的粘连——
  **`}}###` 的粘连不是模型少打了换行，是 `+=` 本身不插分隔符**。
  剥离函数作用在 `state["answer"]`（`nodes.py:685`），**够不到流**，所以 Plan B 修不到它。
  非本件引入（`propose.py` 未被本件触碰），**待单独处理**——见 §5 处置 3。
- **终答在客户端流里下发两次（review P2，同根因）**：`main_agent` 的终答 AIMessage 与
  `final` 的 AIMessage 都被转成 `answer`，前端纯累加后表现为「草稿 + 终稿」两段。
  既有行为，与本条同一处修复点。
- **发布**：本件交付到离线全绿为止；Coze agent 需**重新发布**后才在部署侧可见。

### 4.3 明确不做（spec §3.6，复核后仍不做）

流 `reasoning` / 流 RAG 候选明细 / token 级流式 / 改 Java 代理 / 改外壳 /
新增图节点——理由见 spec，本件执行中未发现需要翻案的证据。

---

## 5. review 处置（`docs/reviews/2026-09-13-process-streaming-and-strip-leading-tool-json-review.md`）

**结论采纳**：哨兵这件实现质量高（§6 的 4 处偏差复核**全部判为改进**），
但「回答裸 JSON 剥离」**没有达成目标**——根因不在模型复述 JSON，而在既有通道。

### 5.1 处置清单

| # | 级别 | 处置 | 落点 |
|---|---|---|---|
| 1 | P1 | **已修复**（用户选定「最小修复」方案） | 前端 `editSuggestion.js::stripLeadingToolJson` + 3 个渲染路径接入 |
| 2 | P1 | **已更正**：本文 §3.2 #6 由 ✅ 改 ❌，并说明是**既有**违规、非本件引入 | 本 devlog §2.3 / §3.2 / §4.2 |
| 3 | P2 | **未修**（最小修复不覆盖，用户明确选择）；已用测试**钉住**，留作后续回归靶 | 前端 `stripLeadingToolJson.test.js` + coze `test_harness_loop.py` |
| 4 | P3 | **已加注释**：`run_tools` 节点名与 SDK `tools` 过滤器的隐式耦合 | `harness/tools_node.py` |
| 5 | P3 | **已改措辞**：「哨兵不跨 chunk」由断言改为**假定**，并写明降级后果与联调排查线索 | `stores/player.js` |
| 附 | — | **已回填 spec §3.1**：`renderMarkdown` 实为**丢弃**哨兵；标注两侧 `\n` 承重 | `docs/spec/…-process-streaming-design.md` |

### 5.2 P1 修复：为什么落在前端

review §1.2 的机制复核**完全正确**，且我复现确认：

- LangGraph `stream_mode="messages"` 转出节点返回值里**所有键**的消息（不只 `messages`）；
- SDK **只**过滤 `langgraph_node == "tools"`，其余非 chunk 的 `AIMessage` 一律转成
  `answer`（`SystemMessage`/`HumanMessage` 无分支，被丢弃——故系统提示词未泄露）；
- 前端 `player.js` **纯累加**（`text += t`，不插分隔符、无重置）；
- coze 侧 `_strip_leaked_json` 作用点是 `nodes.py:685` 的 `state["answer"]`，**够不到流**。

**实测复现（端到端产物，非推演）**：跑真实图 + SDK 全链路，把 deltas 累加后剥哨兵，
得到与用户截图**同形**的 `{"tool": "step_facts", …}}### 当前这一步的执行内容`——
`}}###` 的粘连**不是**模型少打了换行，是 `+=` 本身不插分隔符。

修复：前端新增 `stripLeadingToolJson(text)`，**循环**剥掉开头的裸工具 JSON
（多轮提案有多段，剥掉第一段后第二段会新暴露），判别收在 `tool` 键上
（与 harness `parse_action` **同口径**，也保证【视角导航】的 `{"views":[…]}` 与
【编辑建议】块不被误伤）。接入三处：`parseAssistantMessage`（覆盖终态与历史消息渲染）、
`splitDecisionTrace`、`AiTutorPanel` 的流式 `streamText`，另加 `player.js` 的返修路径。

**验证（端到端产物层）**：

| 项 | 结果 |
|---|---|
| 真实流复现症状 | ✅ `}}###` 粘连复现（`test_harness_loop.py` ②） |
| 真实流修复后正文 | ✅ 剥掉 1 段前导 JSON；正文以 `###` 开头；无裸 JSON、无哨兵 |
| 纯函数单测 | ✅ `stripLeadingToolJson.test.js` 16 例 |
| 恒等性 | ✅ 纯正文一字不变；数组 / 无 `tool` 键对象 / 残缺 JSON 一律不碰 |
| 透传契约 | ✅ 【视角导航】/【编辑建议】解析不回归 |

### 5.3 P2 未修，但已钉住（**需知悉**）

用户选定「最小修复」方案，P2（终答下发两次：`propose` 的终答 AIMessage + `build_final`
的 answer 各一次，纯累加后表现为「草稿 + 终稿」两段）**仍然存在**。
两条测试**故意钉住当前行为**，并在注释里指明「修 P2 时本条应失败并改写」：
coze `test_proposal_json_delta_reaches_client_and_predates_sentinels`（③）
与前端 `stripLeadingToolJson.test.js`（P2 遗留用例）。

> 意味着：用户的**原始症状**（顶端裸 JSON + 标题不换行）已消除；
> 但回答底部**仍可能出现重复的两段正文**。这是已知且有测试锚定的残留。

### 5.4 与 review §1.3 相关的**假前提**已全部更正（5 处）

「提案 delta 会被终答**顶掉**」「`build_final` 是唯一流式输出」这个前提散落在 5 处，
均**不成立**，全部以「原文已证伪」的留痕式标注改写（不删原文，保留可追溯）：

| # | 位置 | 原文误述 |
|---|---|---|
| 1 | `tests/test_harness_loop.py` 该用例 docstring | 「提案 delta 会被它整体顶掉」 |
| 2 | `nodes.py::build_final` docstring | 「确保客户端只看到最终回答，不泄露中间 LLM 调用内容」 |
| 3 | `process_events.py` 模块 docstring | 「只有 `build_final` 这么做……一个字节都出不到客户端」 |
| 4 | `docs/agent-collaboration-guide.md` 哨兵小节 | 「该模式只转发 `messages` 键里的消息」 |
| 5 | `2026-09-13-rag-observability-and-trace-process-design.md` §2.4 | 「`build_final` 是唯一流式输出节点，中间内容不会外泄」 |

**未改**：`player.js` 的纯累加逻辑本身——它是 P2 的修复点，改动面较大，
不在「最小修复」范围内（见 §5.3）。

### 5.5 本节的自我检讨

我把红线用例**收窄**成「只查哨兵 delta」后记为 ✅，是**方法论错误**：
spec §5-6 的判据是「**任何**用户可见产物」，收窄后的通过**不等于**原判据通过。
这与 review 2026-09-13（RAG 件）教训同源——**红线类结论必须以端到端产物取证，
且不得擅自收窄判据**。本次修复即按该纪律取证（§5.2）。
