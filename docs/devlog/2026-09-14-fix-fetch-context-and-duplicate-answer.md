# 2026-09-14 联调修复：fetch 取不到源码 + 回答重复两遍 — 实施记录

> 计划：`docs/plan/2026-09-14-fix-fetch-context-and-duplicate-answer-plan.md`（Task 0–8）
> 报告：2026-09-14 联调测试（用户）
>
> 症状原文：
> 1.「测试多个问题，决策痕迹显示调用了 fetch_execution_context，但是 agent 多轮思考均说缺少 main.java 的源代码信息」
> 2.「回答正文会重复两遍」

**跨两仓**：coze `javatutor-coze`（Task 1–5、8）+ 前端 `JavaTutor/frontend`（Task 6–7）。

交付边界：到**离线全绿**为止（L1–L5 + 前端 vitest + `npm run build`）。**不含**重新发布 agent。
按计划 §4，**线上未验证**的表述见 §4.2。

---

## 1. 两个症状与根因

### 1.1 Bug A — 回答正文重复两遍（根因确定，已端到端复现）

`propose` 每轮把模型**原始输出**写成 `AIMessage` 追加进 `agent_messages`，
而 **`stream_mode="messages"` 会把节点返回值里所有键的消息一起转出**（不只 `messages`），
平台 SDK `agent_helper.py::_item_to_server_messages` **只**过滤 `langgraph_node == "tools"`，
于是终答轮的这条 `AIMessage` 被转成 `answer` delta；前端 `player.js` 是**纯累加**
（`text += t`，无分隔符、无重置），`build_final` 又下发一次终答 → 正文出现两遍。

计划 §0.1 的复现产物（真实图 + 平台 SDK 全链路）已确认 deltas 中第 6 条
（`main_agent` 终答轮）与第 7 条（`build_final`）内容相同。

### 1.2 Bug B — fetch 调了却「没有源码」（未能复现用户那一例；五条缺陷各自独立确认）

计划 §0.2 逐条确认的五条：

1. 前端 `multiState.entryFile` **从未被赋值** —— 提问体里的 `entryFile` 恒为空串；
2. `_resolve_code` 在 `entry_file` 为空时**静默回落到 `source_code`** 且 `file` 恒为空串
   —— 多文件下 `source_code` 是当前活动文件，模型既不知拿到了什么，也无法自证拿到 Main.java；
3. `files` 非空 + `entry_file` 空时走「有 steps 无 code」路径，**「成功但空」无任何信号**
   —— 决策痕迹里那是一次**绿色**调用；
4. `guard` P4 的阈值是 `len(files) > 1` —— 单文件项目里写错文件名会漏到工具层吃硬错误
   `文件不存在：…`，而非得到可重试的拒绝理由；
5. `switchMode('single')` 不清 `multiState.files` —— 切回单文件后提问体仍带残留项目文件。

---

## 2. 做了什么

### 2.1 Bug A 根治（D1 / Task 5，`harness/propose.py`）

`propose` **只在产出提案**（`Action` / `ParseError`）时才把 `AIMessage` 追加进
`agent_messages`；**终答轮与收束轮不再追加**。

安全性论证（已核）：`_route_after_propose` 为
`"guard" if state.get("proposed_action") else "critic"` —— 无 action 的轮次**一定不再回到
propose**，这条消息对后续推理无用；终答本身经 `state["answer"]` 流向 `build_final`，不丢信息。
`agent_messages` 无 reducer（返回即替换），故返回 `history` 等价于「不追加」。

连带口径变化：`decision_trace.reasoning` 少一条（终答不再算「工具调用之间的思考」），
已写进 `docs/spec/2026-08-10-coze-agent-interface.md` 与
`docs/spec/2026-09-13-rag-observability-and-trace-process-design.md` §3.3。

**提案轮的提案 JSON 仍然随流下发**（它是 ReAct 轨迹的承载体，前端 `stripLeadingToolJson`
在渲染前剥净）—— 这是**有意保留**（计划 §1「明确不做」，D5 决定不新增前端重复处理）。

### 2.2 fetch 自描述 + 有序解析 + 取消「成功但空」（D2 / D3 / Task 1–2）

`_resolve_code` 改为**六级解析顺序**（第一条命中即停），并返回 `(code, file, file_source, err)`：

| # | 来源 | `file_source` |
|---|---|---|
| 1 | 显式 `file`（精确 / 忽略大小写 / basename，走 `match_file_key`） | `explicit` |
| 2 | `entry_file` | `entry_file` |
| 3 | `current_step_file`（新增兜底） | `current_step_file` |
| 4 | `files` 唯一项（新增兜底） | `only_file` |
| 5 | `source_code` | `source_code` |
| 6 | 以上皆不成立 | 结构化失败 |

- **成功回包必带** `file` / `file_source` / `code_chars`（观察文本与 `tool_calls[].result` 同形）；
- **取消「成功但空」**：新增 `_no_source_error()`，任何取不到源码的路径（含行范围切出空串）
  一律返回 `fetch_context_failed=true` + 列出候选文件名的 `error`；
- 不变式（验收判据 2）：**`fetch_context_failed == False` ⇒ `code_chars > 0`**。

### 2.3 P4 判据补洞（Task 3，`harness/guard.py`）

判据由 `len(files) > 1` 改为「**按 `match_file_key`（与 fetch 工具同源）匹配不到**」——
与项目有几个文件无关。同源口径保证「门闩认为歧义、工具却能解析」的分歧不会出现。

### 2.4 提示词（Task 4，`prompts.py`）

`SYSTEM_PROMPT_MAIN_AGENT`：
- 读 `[fetch_execution_context 结果]` 时**先看** `file` / `file_source` / `code_chars` 三字段，
  若 `file` 不是要的那个或 `code_chars == 0`，**不要凭它作答**，按 `### 项目结构` 的文件名重取；
- 返回 `[fetch_execution_context 失败]` 时**不许**说「上下文里没有源代码」这类含糊话，
  按错误文本里列出的候选文件名重取，取不到就如实转述错误、不编造源码；
- `file` 参数说明由「默认读取主入口」改为「不传 `file` 时默认读主入口（主入口缺失时按兜底顺序解析）」；
- 示例区**只加一句文字**（不加新 JSON 片段）——避免再给模型一份可逐字回显的 JSON。

### 2.5 前端接线（D4 / Task 6–7）

`frontend/src/stores/player.js`：
- `multiState` 新增 `entryFile`；`buildChatBody` 的 `entryFile` 由恒空串改为
  `multi ? (this.multiState.entryFile || '') : ''`；
- 新增 `refreshEntryFile()`：由 `entry.class` 派生 `<Class>.java` 按 basename 匹配
  `files[].name`；匹配不到时扫描 `public static void main` 所在文件。
  在 `analyzeProject` 成功、`runProject` 成功（`applyRunResult` 之后）各调一次；
  `clearMultiFiles` 重置为 `''`；
- `buildChatBody` 按 `this.mode` **裁剪 payload**：单文件模式发
  `files: []` + `entryFile: ''`，多文件模式发全部 —— **不动 `multiState.files`**，
  故切回多文件仍能恢复项目（计划 §5 风险表推荐的分支）。

### 2.6 文档同步（Task 8）

| 文档 | 改了什么 |
|---|---|
| `docs/spec/2026-08-23-execution-context-fetch-design.md` | 新增 §5.6：六级解析顺序表、自描述字段、「禁止成功但空」与不变式、收紧既有行为的 ⚠ |
| `docs/spec/2026-08-10-coze-agent-interface.md` | `tool_calls` 行补 fetch 带 `result`；新增 2026-09-14 note（`file`/`file_source`/`code_chars` + 取消「成功但空」） |
| `docs/spec/2026-09-13-process-streaming-design.md` | §2.1 补「2026-09-14 状态更新」：重复正文根因已修在源头，流上只剩 `build_final` 一份正文 |
| `docs/spec/2026-09-13-rag-observability-and-trace-process-design.md` | §3.3 补口径变化 note：`reasoning` 少一条及其为何是更正确的语义 |
| `docs/agent-collaboration-guide.md` | 信息分层表下新增 fetch 回包自描述 blockquote；门闩 P4 判据；`tool_calls` 的 `result` 口径 |
| `AGENT.md` | 计划行由「已定稿」改「已执行」+ 新增 devlog 索引行 |

### 2.7 改动清单

| 层 | 文件 | 性质 |
|---|---|---|
| 工具 | `src/tools/fetch_execution_context.py` | `_resolve_code` 六级解析 + `_no_source_error` + 自描述字段 |
| Harness | `src/graphs/javatutor/harness/propose.py` | 终答/收束轮不入 `agent_messages` |
| Harness | `src/graphs/javatutor/harness/guard.py` | P4 判据改 `match_file_key` |
| Harness | `src/graphs/javatutor/harness/render.py` | fetch 观测与 `tool_calls[].result` 带 `file`/`file_source`/`code_chars`（**计划外**，见 §4.1.4） |
| 提示词 | `src/graphs/javatutor/prompts.py` | 三段读观测/失败处置/兜底说明 |
| 前端 | `frontend/src/stores/player.js` | `entryFile` 接线 + `refreshEntryFile` + 按模式裁剪 payload |
| 测试 | `tests/test_fetch_execution_context.py`、`tests/test_harness_guard.py`、`tests/test_harness_loop.py`、`tests/test_prompting.py` | 新增/改写见 §3.1 |
| 前端测试 | `frontend/src/stores/__tests__/player-entry-file.test.js`（新）、`player-mode.test.js` | 6 + 3 条 |

**未改**：外壳（`.coze`/`scripts/`/`src/main.py`/`src/storage/`/`src/utils/`）、Java 后端、
`pyproject.toml`/`uv.lock`/`package.json`、图结构（`graph.py` 未动）、`decision_trace` 既有键与语义、
三种末尾结构化块的契约、`agent_messages` 的 ReAct 轨迹语义、`frontend/src/backup-20260807/`。

---

## 3. 验证

### 3.1 全绿

| 项 | 基线 | 结果 |
|---|---|---|
| coze `uv run pytest tests/ -q` | 407 | **424 passed** |
| 前端 `npx vitest run` | 431 passed / 32 files | **440 passed / 33 files** |
| 前端 `npm run build` | — | ok |

新增/改写的关键用例：

- **红线（Bug A，端到端）**`test_client_stream_gets_the_answer_exactly_once`：
  真实图 + `agent_iter_server_messages` 全链路，deltas 累加并剥哨兵后，
  正文串恰好 1 次、`【决策痕迹】` 恰好 1 次、正文体里特征句恰好 1 次。
  同时保留 `test_proposal_json_delta_reaches_client_and_predates_sentinels`
  的前两条断言（提案 JSON 仍在流上、`}}###` 粘连仍在，故前端 `stripLeadingToolJson` 仍必需）。
- **不变式（Bug B 主判据）**`test_successful_fetch_always_has_nonempty_code_chars`
  （4 个 state 参数化）、`test_fetch_multi_file_without_entry_does_not_silently_return_empty`、
  `test_fetch_empty_only_file_is_structured_failure`、`test_fetch_out_of_range_slice_is_structured_failure`。
- **自描述**`test_fetch_reports_file_and_source`、`test_fetch_reports_entry_file_source`；
  **兜底顺序**`test_fetch_falls_back_to_current_step_file`、`test_fetch_uses_only_file_when_single`、
  `test_fetch_explicit_file_wins`、`test_entry_file_beats_current_step_file`、
  `test_entry_file_matches_by_basename`。
- **P4**`test_single_file_miss_also_needs_decision`（**反转**了旧的
  `test_single_file_never_ambiguous`）。
- **`agent_messages`**`test_terminal_answer_does_not_enter_agent_messages`、
  `test_convergence_round_does_not_enter_agent_messages`、
  `test_proposal_round_still_enters_agent_messages`；
  `test_graph_agent_messages_alternate_roles` 期望由 5 条改 4 条。
- **痕迹可诊断**`test_fetch_tool_call_records_its_result_in_the_trace`。
- **提示词**`test_main_agent_prompt_teaches_fetch_observation_fields`。
- **前端**`player-entry-file.test.js` 6 条 + `player-mode.test.js` 3 条（按模式裁剪）。

按计划 §5 风险表第 1 行的要求，**逐条核对了被 Task 1「收紧」影响的既有用例**：
全量回归确认**没有任何既有用例依赖「成功但空」**；被迫改写的用例只有 D3/Task 3 的语义变更
（`test_default_reads_main_entry` 由单文件 state 改为 2 文件 state，以继续覆盖
`source_code` 兜底；`test_single_file_never_ambiguous` 被反转）与 Task 5 的断言同步。

### 3.2 验收项对照（计划 §3）

| # | 验收项 | 结论 |
|---|---|---|
| 1 | 正文只出现一次（端到端红线） | ✅ `test_client_stream_gets_the_answer_exactly_once` |
| 2 | 不再有「成功但空」（`failed == False ⇒ code_chars > 0`） | ✅ 参数化用例 4 个 state |
| 3 | 自描述（拿到哪个文件 / 多长 / 哪条兜底） | ✅ 成功回包与 `tool_calls[].result` 同形 |
| 4 | 单文件项目不合规文件名走 P4 而非硬错误 | ✅ `test_single_file_miss_also_needs_decision` |
| 5 | 多文件无 `entry_file` 时按兜底顺序取到源码 | ✅ 五条顺序用例 |
| 6 | 前端切回单文件后 payload 不带残留 | ✅ `player-mode.test.js`（`multiState.files` 保留） |
| 7 | 两侧全绿且不回归既有红线 | ✅ 哨兵顺序、被拒工具名不入用户可见产物、导航/编辑建议块均未回归 |

### 3.3 本地规约门槛（L1–L5）

| 门槛 | 结果 |
|---|---|
| L1 `uv sync --frozen` | ok |
| L2 全量测试 | 424 passed |
| L2.5 组件级评估 | 2 passed |
| L3 离线构建 | `ok` |
| L4 本地 HTTP 冒烟 | **SKIP**（无本地模型端点 + PostgreSQL） |
| L5 外壳回归 | 两仓均 **0 命中** |

---

## 4. 与计划的偏差与遗留

### 4.1 偏差（3 处）+ 计划外改进（1 处）

1. **Task 6 的 `data.entry` 假设不成立（计划事实性错误）**。计划写
   `this.multiState.entryFile = data.entry || ''`，但 `ProjectAnalysisService.java:41-44` 返回的是
   `{"class": ..., "method": ...}` **对象**，照抄会把对象塞进 `entryFile`。
   改为由 `entry.class` 派生 `<Class>.java` 并 basename 匹配。另核 `/api/run/project` 的
   `RunResponse` **没有** `entry` 字段，故不存在第二个写入点。
2. **Task 6 的触发点不足**。`analyzeProject()` 只在用户打开 Flow/Class/Structure 面板
   （`FlowDiagramPanel.vue:201-205` 的 `onMounted`）或点它的按钮时才跑，`projectAnalysis`
   不是可靠唯一来源 → 补 `public static void main` 扫描兜底。
3. **计划指名的测试文件不存在**。计划写 `tests/test_guard.py`，实际是
   `tests/test_harness_guard.py`（`tests/test_guard.py` 从未存在）。
4. **（计划外改进）`tool_calls[].result` 给 fetch 也写值**。计划 Task 0 要求联调侧读
   `tool_calls[0].result` 定案，但此前 fetch 的记录**不写 `result`**（`step_facts` 一直有），
   该指令无法执行 → 在 `render.py::_handle_fetch` 里补：成功写
   `{"stored": true, file, file_source, code_chars, steps_count, ...}` 摘要、失败写
   `{"stored": false, "error": ...}`，**两条路径都是合法 JSON**（细节与踩到的坑见 §6）。
   摘要里**不含 `code`**（源码只进 observation 文本）。

### 4.2 遗留（**需知悉**）

1. **Task 0 现场证据仍未取到**（计划 §6 列为可与其余 Task 并行、不阻塞）。
   需要联调侧在**复现当时**的决策痕迹里回读三样：
   ① `tool_calls[0].result`（fetch 那条，是否含 `"code": ""`）；
   ② `reasoning[*].content` 里 `[fetch_execution_context 结果]` 整行的 `file` 字段是否为空串；
   ③ 当时前端处于单文件还是多文件模式、`### 项目结构` 是否非空。
   **本修复按「五条缺陷各自独立确认」推进，未等待该证据**；证据到位后应回头核对是否还有第六条。
2. **线上未验证**。L4 本地 HTTP 冒烟 SKIP（无本地模型端点 + PostgreSQL），
   且**未重新发布 agent**、未跑端到端评估。
   按计划 §4：本修复**改变终答的流式行为**，重发后须补一轮端到端评估，确认
   **Judge 均分下降 ≤ 0.3 且 Grounding 下降 ≤ 0.5**；未重发期间线上表现**未知**。
3. **Bug B 用户那一例未在本地复现**。五条缺陷是各自独立确认的**候选成因**，
   没有用户当时的 `run_id` / payload 做逐字比对。
4. **`reasoning` 少一条是预期内的口径变化**，若评测侧有断言依赖「末条 = 终答」需同步改
   （本次已核 coze 侧用例，无此依赖）。
5. **RAG 检索在生产侧恒空**（四轮检索指标全 0）与本件**无关**，仍待 round-5 定案。

---

## 5. 回滚

按计划 §5，**Task 5（Bug A）与 Task 1–4（Bug B）互相独立**，任一可单独回滚：

- Task 5 回滚 = 恢复 `propose` 无条件追加 `AIMessage`（正文重复会复现）；
- Task 1–4 回滚 = 撤销 fetch 的有序解析/自描述/结构化失败与 P4 判据（需同时回滚前端 Task 6：
  否则 `entryFile` 已接线、fetch 却仍静默回落）；
- Task 6–7 是前端独立提交，可单独回滚（**D3 的 coze 兜底保证老前端也对**，D1 是纯 coze 侧）。

---

## 6. 追加：执行过程区不显示文件名（2026-09-14 联调反馈）

**反馈**：联调侧截图显示【执行过程】只有一行「调用 fetch_execution_context」，
并指出「之前确实会显示 Main.java，但现在没了」。

**排查结论（逐条已核，**不是**前端回归）**：

1. 前端 `formatToolCall`（`decisionTrace.js`）**从未**从 `result` 渲染 fetch 的文件名——
   它只渲染 `args` 里的标量参数（fetch 无专用分支，只有 `step_facts` 有）。
   所以「显示 Main.java」只能来自 **`args.file`**，即**模型自己显式传了 `file`**。
2. 自动前置的那次 fetch（`tools_node.py` 的 `_run_fetch(state, {})`）`args` 恒为 `{}`；
   模型不传 `file` 的调用同样是空 → 两种情况下都只能显示裸行。
3. 部署侧提示词给的**正是空 args 示例**：`prompts.py` 里
   `{"tool": "fetch_execution_context", "args": {}}` 出现两次（一处是「必须先调用」的范例，
   一处是三步调用示例的第 1 轮），模型照抄的概率很高 → 裸行是常态。
4. 因此「显示 Main.java」取决于**模型的临场选择**（提示词只在多文件提问时引导传 `file`），
   同一问题两次跑出不同痕迹是可能的。

**根因**：痕迹只反映**模型想读什么**（`args`），不反映**实际读到了什么**（`result`）。
这是 Bug B 可诊断性缺口在用户可见面上的残留——Task 1 把 `result` 补上了，但没人渲染它。

**改动（纯前端）**：`decisionTrace.js` 新增 `fetch_execution_context` 分支与
`FILE_SOURCE_LABELS` 映射（`explicit`/`entry_file`/`current_step_file`/`only_file`/`source_code`），
从 `result` 渲染 `file` / `file_source` / `code_chars`：

```
调用 fetch_execution_context → Main.java（主入口），3160 字
调用 fetch_execution_context：file=Util.java → Util.java（显式指定），88 字
调用 fetch_execution_context → 单文件兜底，20 字          # file 为空串时只报来源
调用 fetch_execution_context → 失败：未能取到源码（…）      # 长错误截 60 字
```

`result` 缺失（老 agent）或解析失败时**保持裸行**——向后兼容，不回归。
`args` 的标量参数仍照旧渲染（模型显式传 `file` 时两者都在，互为印证）。

**连带修掉一个自己引入的缺陷（coze 侧，§4.1.4 的追加改动）**：先前给 fetch 写的
`call["result"] = json.dumps(payload)[:300]` 里**带着整份 `code`**，而 `payload` 因此远超
300 字，`[:300]` 把 JSON **断在字符串中间**——实测
`json.loads` 报 `Unterminated string starting at column 180`。
后果是前端 `JSON.parse` 必失败、`fetchStatus` 返回空串，**上面这个渲染分支永远走不到**，
用户看到的仍是裸行（等于白改）。两处修正：

1. **成功路径的摘要不放 `code`**（源码只进 observation 文本给模型看；痕迹里 `code_chars`
   已足够说明「取了多长」）；
2. **失败路径也改成 JSON**（`{"stored": false, "error": <截 120 字的错误>}`）——
   先截错误串**再** dump，保证 dump 出来一定是合法 JSON；反过来先 dump 再截必然截断。
   两条路径由此与 `step_facts` 的 `result` 同形（消费方统一 `json.loads`）。

这正是「红线取证纪律」要防的那类假绿：**只看函数返回值会以为「字段加上了」，
必须走到端到端产物（这里是 `tool_calls[].result` 能不能被 `json.loads`）才算数。**

**验证**：

- coze：`test_fetch_tool_call_records_its_result_in_the_trace` 改为**直接 `json.loads`**
  两条路径的 `result`（不合法即抛），并断言摘要里没有 `code`；全量 **424 passed**。
- 前端：`npx vitest run` 440 → **444 passed / 33 files**。其中两条用例的 `result`
  是**从 coze 真实产物原样粘贴**的（不是手写形状），契约一改就红。
- `npm run build` ok。

**依赖与遗留**：

- 需 **coze 侧重发** `result` 才存在；未重发期间前端行为与现状**一字不差**（老 agent 无 `result`）。
- 实时进度区（哨兵）的 fetch 行**仍只有 `args`**（哨兵事件 schema 未带 `file`）——
  **有意不动**：该区是瞬时的、生成结束即清空，终态折叠区才是留档；
  若将来也要显示，需扩哨兵事件 schema（`kind` 为开放集合，加字段不破协议）。

