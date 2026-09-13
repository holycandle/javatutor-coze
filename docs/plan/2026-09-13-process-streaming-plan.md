# 实施计划：过程式输出（阶段与工具调用实时可见）

> 依据：`docs/spec/2026-09-13-process-streaming-design.md`（本计划是其 TDD 落地）。
> 分工：设计侧产出本文档，执行由执行组完成。
> 交付边界：到离线全绿为止（L1–L5 + 前端 vitest）。**不含**重新发布 agent（发布由合入窗口处理）。
> 本计划**跨两仓**：`javatutor-coze`（Task 1–5）与 `javatutor/frontend`（Task 6–7）。

## 0. 全局约束（务必遵守）

- **不做任何 git 操作**（不 `git add`/`commit`/`push`/`stash`/`checkout`/`branch`/`merge`）。
  读 `git log`/`git status`/`git diff` 可以。
- **外壳一个字节都不改**：`.coze`、`scripts/`、`src/main.py`、`src/storage/`、`src/utils/`。
- **不改 Java 后端**（本设计刻意绕开它）。
- **不引入新依赖**，不改 `pyproject.toml`/`uv.lock`/`package.json`。
- **不改图结构**：不新增、不删除、不重接任何节点与边（`graph.py` 不动）。
- **不改既有语义**：`decision_trace` 的既有键、三种末尾结构化块（`【决策痕迹】`/`【编辑建议】`/
  `【视角导航】`）的契约、`agent_messages` 的 ReAct 轨迹语义、`state.messages` 作为入站契约的角色。
- 基线（改动前先跑一遍记数）：
  - coze：`uv run pytest tests/ -q` 应 **368 passed**（本机 2026-09-13 实测）；
  - 前端：`cd javatutor/frontend && npx vitest run` 应 **390 passed / 29 files**。
- **红线取证纪律**（`docs/reviews/2026-09-13-rag-observability-and-trace-process-review.md` §1.4）：
  「什么会进用户可见产物」的断言必须以**端到端产物**取证，不在函数层下结论。
  本计划有**两条**红线需要用此法验证：被拒工具名（Task 4）、哨兵不外泄（Task 8）。
- 不触碰 `javatutor/frontend/src/backup-20260807/`。
- 开工前对账队友分支：确认没有新改动落到 `nodes.py::build_final` /
  `harness/tools_node.py::run_tools_node`（本计划的改动面）。

---

## Task 1：哨兵构造与解析（纯函数层）

**先写测试** `tests/test_process_events.py`（新建）：

- `build_process_event({"kind":"stage","text":"正在分析问题…"})` →
  返回的字符串以 `\n<!--jt:process ` 开头、以 `-->\n` 结尾，且**内含**可 `json.loads` 的负载。
- `build_process_event` 对中文与 `ensure_ascii=False` 的处理：负载里能直接看到中文
  （断言 `"正在" in out`）。
- `parse_process_events(text)` 往返：`parse(build(ev))["events"] == [ev]`，且
  `clean == ""`（哨兵被完全剥净）。
- 混合文本：`"正文A" + build(ev1) + "正文B" + build(ev2)` →
  `clean == "正文A正文B"`、`events == [ev1, ev2]`。
- **畸形哨兵**：`\n<!--jt:process {bad json}-->\n` →
  不抛错、`events == []`、**且该段不出现在 `clean` 里**（不能把哨兵当正文漏出去）。
- **无哨兵**：纯正文原样返回，`events == []`。
- **判别标记**：`build_process_event` 返回值供 `additional_kwargs` 使用的常量
  `PROCESS_KWARG = "jt_process"` 已导出（Task 3 依赖）。

**实现** `src/graphs/javatutor/process_events.py`（新建）：
- `PROCESS_MARK_PREFIX` / `PROCESS_MARK_SUFFIX` 常量；
- `build_process_event(event: dict) -> str`；
- `parse_process_events(text: str) -> dict[str, Any]`（返回 `{"clean": str, "events": list}`）；
- `PROCESS_KWARG = "jt_process"`。

**约束**：**不 import 任何图内模块**（保持可脱离图单测），只用 stdlib。

**验证**：`uv run pytest tests/test_process_events.py -q` 全绿。

---

## Task 2：状态字段 + `build_context` / `retrieve_knowledge` 发射

**先写测试** `tests/test_graph.py`（追加）：

- 走一次完整图调用，断言 `out["messages"]` 中**存在**带 `additional_kwargs[PROCESS_KWARG] is True`
  的消息，且其中至少一条的负载 `kind == "stage"`、`text` 含 `命中`。
- 断言该 stage 事件的文本里含**真实命中数**：把 `retrieval_debug["kept"]` 与文本里的数字对齐
  （构造一个 `kept == 0` 的桩，断言文本含 `命中 0 条`）。
- **入站契约守卫**：断言 `build_context_node` 取历史时**跳过**哨兵——
  构造一个 `state.messages` 里预先含一条哨兵的输入，断言产出的 `context_built`
  **不含**该哨兵文本片段。

**实现**：
1. `src/graphs/javatutor/state.py`：新增
   ```python
   process_event_ids: list[str]
   """本请求发射的过程哨兵消息 id，供 build_final 用 RemoveMessage 清理。"""
   ```
2. `src/graphs/javatutor/nodes.py::build_context_node`：
   - 取历史（`:691` 的 `state.get("messages")` 循环）时，`continue` 跳过
     `getattr(msg, "additional_kwargs", {}).get(PROCESS_KWARG)` 为真的消息；
   - 在返回 dict 里追加一条 `stage:"正在分析问题…"` 哨兵与它的 id。
3. `src/graphs/javatutor/nodes.py::retrieve_knowledge`：成功与降级**两条分支都要**追加
   `stage` 哨兵，文本为 `f"已检索知识库：命中 {kept} 条"`；降级分支文本用
   `"知识库检索不可用，已用通用知识回答"`（与 `decisionTrace.js` 既有文案一致）。

**注意**：`retrieve_knowledge` 现在要返回 `messages` 键，**不得**改动
`retrieved_chunks` / `retrieval_debug` / `rag_degraded` 的既有返回值。

**验证**：`uv run pytest tests/test_graph.py -q` 全绿。

---

## Task 3：`run_tools` 发射工具事件（**红线所在**）

**先写测试** `tests/test_harness_loop.py`（追加）：

- 一次 `step_facts` 执行后，返回 dict 的 `messages` 里含哨兵，负载 `kind == "tool"`、
  `tool == "step_facts"`、`status == "ok"`、`args` 与 `step_records` 一致、`latency_ms` 为数字。
- **每条 observation 一条事件**：自动前置 fetch + step_facts 的常态路径 →
  事件数 == `len(step_records 增量)`（即 2 条：`fetch_execution_context` + `step_facts`）。
- **末条是前瞻 stage**：最后一条哨兵 `kind == "stage"` 且文本含 `正在生成回答`。
- **红线（端到端）**：
  1. 用既有 `SpamModel` 桩让模型提出 `no_such_tool`（含 4 种畸形提案变体，
     与 `tests/test_harness_loop.py:495` / `tests/test_harness_termination.py:120` 同源）；
  2. 跑**完整图**，取**最终 SSE 可下发文本**（= `build_final` 返回的 `messages` 里
     所有 `AIMessage.content` 顺序拼接 —— 这等价于客户端看到的流）；
  3. 断言 `"no_such_tool" not in` 该文本。
  **不得**只断言哨兵构造函数不接收被拒工具就下结论——红线必须在最终产物上取证。

**实现** `src/graphs/javatutor/harness/tools_node.py::run_tools_node`：
- 从 `observations`（**本节点真正执行的**）构造 `tool` 事件：
  `{"kind":"tool","tool":o.tool,"args":o.args,"status":o.status,"latency_ms":o.latency_ms}`；
- 末尾追加一条 `stage:"证据已就绪，正在生成回答…"`；
- 把这些哨兵包成 `AIMessage(content=..., id=..., additional_kwargs={PROCESS_KWARG: True})`
  追加进返回值的 `messages`（**与既有 `agent_messages` 的追加并行，互不影响**）；
- 返回 dict 追加 `process_event_ids`。
- **注释必须写明**：`_redact_denied_tools` 只罩 `answer` 里的 trace JSON 段，
  **罩不到哨兵**，所以过滤只能在这里做——防止将来有人误以为有第二道防线。

**验证**：
```
uv run pytest tests/test_harness_loop.py tests/test_harness_termination.py -q
```

---

## Task 4：`build_final` 清理哨兵（状态卫生）

**先写测试** `tests/test_graph.py`（追加）：

- 一次完整图调用后，`out["messages"]` 里**不含**任何带 `PROCESS_KWARG` 标记的消息
  （哨兵已在 `final` 被 `RemoveMessage` 清掉）。
- **连续性守卫**：同一 thread 连续两次调用，第二次的输入 `messages` 里不含哨兵
  （用 checkpointer 复用同一 `thread_id`，断言第二次 `context_built` 不含哨兵文本）。
- **哨兵确实流出过**：断言 `final` 节点**之前**的某次节点返回值里有哨兵
  （防止「清理把发射也一起干掉」这种静默失效）。

**实现** `src/graphs/javatutor/nodes.py::build_final`（`:612-678`）：
- 从 `state.get("process_event_ids")` 构造 `RemoveMessage(id=...)`；
- 返回值改为 `{"messages": [*removals, AIMessage(content=content)], ...}`。
- 注释说明：`RemoveMessage` 不是 `AIMessage`/`ToolMessage`，平台 SDK 的消息转换器会忽略它，
  不会额外下发；而哨兵在节点执行期间**已经流出**，清理发生在其后。

**验证**：`uv run pytest tests/ -q` 全绿（基线 368）。

---

## Task 5：coze 侧文档同步

- `docs/agent-collaboration-guide.md`：新增「过程哨兵」小节——格式、
  两个 `kind`、三个发射点、**红线（只用已执行的 observation）**、
  **状态卫生（RemoveMessage + 历史过滤两道防线）**。
  这是 AGENT.md 规约的硬要求（「改动图结构/节点/输入输出时同步更新」）。
- `AGENT.md`：登记本 spec / plan / review / devlog 四行。

**验证**：人工核对 `agent-collaboration-guide.md` 的节点表与 `state.py` 字段表已更新。

---

## Task 6：前端哨兵解析（纯函数层）

**先写测试** `javatutor/frontend/src/utils/processEvents.test.js`（新建）：
- `extractProcessEvents(text)` 往返、混合、畸形 JSON、无哨兵四类用例，
  与 Task 1 的 coze 侧测试**同构**（同格式两份实现，靠测试对齐）。
- 断言畸形哨兵**既不进 events 也不留在 clean**。

**实现** `javatutor/frontend/src/utils/processEvents.js`（新建）：
`extractProcessEvents(text) -> { clean, events }`。
**约束**：不用正则的 `.*?` 跨大括号贪心陷阱——哨兵负载是单行 JSON，用
`/<!--jt:process (.+?)-->/g` 即可（负载内不含 `-->`，由 Task 1 的构造保证）。

**验证**：`npx vitest run src/utils/processEvents.test.js`。

---

## Task 7：前端实时进度 UI

**先写测试**：
- `stores/player.test.js`（追加）：喂一串含哨兵的 chunk，断言 `liveStage` 为**最后一条** stage、
  `liveTools` 按序累积；流结束（或重新提问）后两者**清空**。
- `utils/decisionTrace.test.js`（追加）：`splitDecisionTrace` 的 `body` **不含**哨兵文本
  （终态不漏）。

**实现**：
1. `stores/player.js`：
   - 新增状态 `liveStage: ''`、`liveTools: []`；
   - `askQuestion` 的 `onChunk`（`:508`）改为**增量**处理：把 chunk 追加到 `m.text` 的同时，
     用 `extractProcessEvents` 抽取本 chunk 内的事件并更新 `liveStage` / `liveTools`；
     **不做每 chunk 全量重解析**（O(n²)）；
   - `askQuestion` 开头（`:494-497`）与 `finally`（`:516-519`）里重置这两个字段。
2. `components/AiTutorPanel.vue`：
   - 流式中的最后一条（`:67`）改为渲染 `clean` 后的文本；
   - 复用 `chat-stage` 的样式与位置（`:88-91`）渲染实时进度：
     `liveStage` 覆盖显示为一行，`liveTools` 逐行小字在其下；
   - 生成结束后实时区随 `isExplaining === false` 自然隐藏（信息由
     `DecisionTracePanel` 的【执行过程】折叠区接管）。
3. `utils/decisionTrace.js`：`splitDecisionTrace` 的 `body` 再过一次 `extractProcessEvents`。

**终态一致性回归（必须）**：一次带工具调用的提问，断言实时区列出的工具集合
与【执行过程】折叠区（`trace.tool_calls`）**一致**（`stage` 行不参与比较）。

**验证**：`cd javatutor/frontend && npx vitest run`（基线 390 passed / 29 files）。

---

## Task 8：端到端验收（L1–L5）

按 spec §5 逐条过：

| # | 验收项 | 取证方式 |
|---|---|---|
| 1 | 生成期间可见 4 类进度 | 手工：跑一次带工具调用的提问，录屏/截图 |
| 2 | 实时区与折叠区工具集合一致 | Task 7 的回归用例 |
| 3 | 老前端 + 新 Agent：哨兵不可见 | 构造含哨兵的文本过 `renderMarkdown`，断言输出 HTML 里哨兵被 `<!-- -->` 包裹（浏览器不可见） |
| 4 | 新前端 + 老 Agent：行为不变 | `liveStage === ''`、`liveTools === []` 时不渲染任何新 UI |
| 5 | `state.messages` 无哨兵残留 | Task 4 的两条用例 |
| 6 | 被拒工具名不入任何用户可见产物 | Task 3 的端到端红线用例 |
| 7 | 导航/编辑建议块不回归 | 既有用例 + 手工核对一次 |
| 8 | 双侧全绿 | `uv run pytest tests/ -q`（368）+ `npx vitest run`（390） |

L1–L5 本地规约门槛按 `docs/local-dev-convention.md` 执行；
**L5 外壳检查必须为 0 命中**（本计划不动外壳，若命中说明越界了）。

**交付物**：实现记录 `docs/devlog/2026-09-13-process-streaming.md`，记录改动内容、
验证结果（含首屏实测的 18s 时间线对照）、遗留问题。

---

## 9. 任务依赖与建议顺序

```
Task 1 ──┬── Task 2 ──┐
         └── Task 3 ──┼── Task 4 ── Task 5
                     │
Task 6 ── Task 7 ─────┴── Task 8
```

Task 1 与 Task 6 是纯函数层，可并行；Task 2/3 依赖 Task 1；
Task 4 依赖 Task 2/3（要先有 id 才能清）；Task 7 依赖 Task 6。
**Task 4 完成前不要手工联调**——否则哨兵会污染 checkpointer，看起来像「上下文错乱」，
排查成本很高。

---

## 10. 遗留与后续

- **长尾粒度**：末轮 propose + critic + revise 只有一行前瞻文案盖住（spec §6）。
- **`reasoning` 流式留位**：协议 `kind` 开放，待 proposal 形态变化后另议。
- **RAG 明细流式留位**：等 round-5 根因定案；协议无需变更，只换文案内容。
- **发布**：本计划交付到离线全绿为止；Coze agent 需**重新发布**后才在部署侧可见
  （与 `docs/plan/2026-09-13-rag-observability-and-trace-process-plan.md` Task 9 同窗口处理）。
