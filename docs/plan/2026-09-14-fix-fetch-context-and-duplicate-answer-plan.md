# 2026-09-14 联调修复：fetch 调了却「没有源码」+ 回答正文重复两遍

> 报告人：联调测试（用户）
> 症状原文：
> 1. 「测试多个问题，决策痕迹显示调用了 fetch_execution_context，但是 agent 多轮思考均说缺少 main.java 的源代码信息」
> 2. 「回答正文会重复两遍」
>
> 涉及仓：`javatutor-coze`（智能体）+ `JavaTutor/frontend`（前端）+ `JavaTutor/backend`（仅透传，预计不改）
> 本文所有「已实测」结论均在本地复跑过，命令见各节。

---

## 0. 症状与取证

### 0.1 Bug A — 回答正文重复两遍（**已端到端复现，根因确定**）

**复现命令（真实图 + 平台 SDK 全链路，非函数级）**

```bash
cat > /tmp/probe_dup.py <<'PY'
# 用 RouterModel 驱动 build_flow_graph().stream(stream_mode="messages")，
# 再经 coze_coding_utils.helper.agent_helper.agent_iter_server_messages 转客户端消息
# 脚本：第 1 轮 propose step_facts，第 2 轮 propose 终答「根据第 2 步，x 变成了 2。」
PY
uv run python /tmp/probe_dup.py
```

**实测 deltas**

| # | delta | 来源节点 |
|---|---|---|
| 0–1 | 两条 `stage` 哨兵 | `retrieve_knowledge` / `build_context` |
| 2 | `{"tool": "step_facts", "args": {"step_index": 1}}` | `main_agent` 提案轮 |
| 3–5 | 两条 `tool` + 一条收尾 `stage` 哨兵 | `run_tools` |
| 6 | `根据第 2 步，x 变成了 2。` | **`main_agent` 终答轮** |
| 7 | `根据第 2 步，x 变成了 2。\n\n【决策痕迹】…` | **`build_final`** |

前端纯累加后正文出现**两次**（实测 `clean.count(终答) == 2`，第 3 次计数来自痕迹里的 `reasoning`）。

**机制（每一环都已确认）**

1. `propose()` 把模型**原始输出**写成 `AIMessage` 追加进 `agent_messages`
   —— 终答轮与收束轮同路径：`harness/propose.py:104`、`:110`、`:114`。
2. LangGraph `stream_mode="messages"` 会把节点返回值里**所有键**的消息对象一起转出（不只 `messages`），
   `agent_messages` 因此在内。
3. 平台 SDK `coze_coding_utils/helper/agent_helper.py::_item_to_server_messages` **只**过滤
   `langgraph_node == "tools"`；其余任何**非 chunk 的 `AIMessage`（content 非空）一律转成 `answer`**，无节点白名单。
4. 前端 `frontend/src/stores/player.js` 是**纯累加**（`text += t`，无分隔符、无重置）。
5. `build_final`（`nodes.py`）再下发一次终答 + 痕迹。

⇒ 这是 **review 2026-09-13 的 P2**（当时用户选定「最小修复」故未修，已用测试钉住），
本次联调确认它是**用户可见的真 bug**，不再是理论残留。

### 0.2 Bug B — fetch 调了却「没有源码」（**未能复现该用户那一例；定位到五条各自独立确认的缺陷**）

**取证 1（前端，静态）**：`multiState.entryFile` 在整个 `frontend/src` 中**只有读、没有任何写**。

```bash
cd JavaTutor/frontend && grep -rn "entryFile\s*[:=]" src/ --include=*.js --include=*.vue | grep -v '\.test\.js'
# → 3 处全是读取（GlobalStatus.vue:63 / player.js:321 / player.js:576），0 处写入；
#   multiState 的默认值（player.js:96-104）里也没有这个键。
```

⇒ `entry_file` **从未被发送**给后端（`buildChatBody` 里 `this.multiState.entryFile || ''` 恒为 `''`），
`CozeService.addFiles` 的 `entryFile` 分支从未生效。

**取证 2（coze，静态）**：`tools/fetch_execution_context.py:120-123` 的 `_resolve_code`，
`entry_file` 为空时**直接返回 `state["source_code"]`，并给出 `file: ""`**：

```python
entry = state.get("entry_file") or ""
if entry and entry in files:
    return files[entry], entry, {}
return state.get("source_code", ""), "", {}      # ← file 恒为 ""
```

**取证 3（coze，实测）**：多文件 payload（`files` 非空、`entry_file` 空、`source_code` 空）下调用 fetch：

```bash
uv run python /tmp/probe2.py
# --- multi-file, files present, entry_file EMPTY
#    error: None
#    fetch_context_failed: False
#    file: ''   len(code): 0        ← 成功标记 + 空代码
```

⇒ **「成功但空」没有任何信号**。模型看到观测里的 `"code": ""`，只能回答「没有获取到完整源代码」；
而决策痕迹里这是一次**绿色**的工具调用——与报告症状**逐字吻合**。

**取证 4（coze，静态）**：`harness/guard.py:70` 的 P4 判据是 `len(files) > 1`。
`files` 恰好 1 个文件时，不存在的 `file` 名会被**放行**到工具层，返回硬错误 `文件不存在：…`
（而 `len(files) > 1` 时同样的输入会得到可重试的 `needs_decision`）。

**取证 5（前端，静态）**：`switchMode('single')`（`player.js:836-843`）**不清空** `multiState.files`。
从多文件切回单文件后，`buildChatBody` 仍把**残留的项目文件**与 `entryFile` 一起发送，
`### 项目结构` 会列出与当前编辑代码无关的文件。

**合成症状**：模型按提示词的规范示例调用 `{"tool":"fetch_execution_context","args":{}}`
（`prompts.py:118` 与示例 `:133` 都这么教），在 `entry_file` 恒空时拿到的是 `source_code`
（多文件下 = **当前活动文件**）且观测里 `file` 恒为 `""` —— 模型**无法知道自己拿到了什么**，
也无法自证拿到了 Main.java，于是每一轮都说「缺少 Main.java 的源代码」，而痕迹里调用是成功的。

> **诚实标注**：本地没有该用户的 `run_id` 与 payload，故**没有**复现他那一次的确切链路；
> 上面五条**各自都单独实测/静态确认过**，合起来能唯一解释报告的症状，但「哪一条是他那一例的主因」
> 需要一条现场证据定案（见 Task 0）。

---

## 1. 修复方案（设计决策）

| # | 决策 | 理由 |
|---|---|---|
| **D1** | **Bug A 修在 coze 侧**：`propose` 只在**产出提案**（Action / ParseError）时才把 `AIMessage` 追加进 `agent_messages`；**终答轮与收束轮不追加** | 终答轮之后图一定不再回到 `propose`（`_route_after_propose` 把无 action 的轮次导向 `critic`），该 `AIMessage` 对后续推理**无用**，却是流上重复正文的**唯一**来源。修在源头 ⇒ 客户端只收到 `build_final` 一次终答 |
| **D2** | **fetch 必须「自描述 + 失败得响亮」**：解析结果永远带出 `file` 与 `file_source`；解析到空代码或解析不到 → **结构化失败**，不再有「成功但空」 | 「静默成功」违反本仓「失败是数据不是异常」的既有原则（工具层本就该给结构化错误）；模型与痕迹必须能区分「取到了空的」与「取到了」 |
| **D3** | **入口解析顺序**：显式 `file` → `entry_file` → `current_step_file`（当前步所在文件）→ `files` 唯一项 → `source_code` → 失败 | 契约**向后兼容**（仍以「显式 file → 主入口」为先），只把「解析不到就静默返回 source_code」换成**有序兜底 + 明示来源**。`current_step_file` 是新增兜底，语义最贴近「用户正在看的这一步」 |
| **D4** | **前端补齐 + 切断残留**：把 `multiState.entryFile` 真正写通（来源 `projectAnalysis.entry`）；`switchMode('single')` 清空 `multiState.files` | 取证 1 与取证 5 是前端侧的两处**状态未闭环**，不改则 coze 侧兜底再好也在跟错误输入搏斗 |
| **D5** | **不改前端渲染路径的重复处理** | D1 后流上只剩一份正文；前端再叠一层「终态整体替换」会变成双保险掩盖问题（且改动面大）。保留既有 `stripLeadingToolJson` 不动 |

**明确不做**（避免将来重复论证）：

- 不顺手改「提案 JSON 仍随流下发」——`agent_messages` 里的提案必须留在流上（它是 ReAct 轨迹的承载体），
  前端 `editSuggestion.js::stripLeadingToolJson` 已在渲染前剥净。
- 不改平台外壳 / Java 代理 / SSE 协议。
- 不重开 token 级流式。

---

## 2. Tasks（TDD：每条先写失败用例）

### Task 0（**先证后修，不阻塞其余 Task**）：取一条现场证据定案

请联调侧复现一次原问题，从回答末尾的 `【决策痕迹】` 里抓这三项：

1. `tool_calls[0].result`（fetch 那一条）—— 是否含 `"code": ""`；
2. `reasoning[*].content` 里 `[fetch_execution_context 结果]` 整行 —— `file` 字段是否为空串；
3. 提问时前端处于**单文件**还是**多文件**模式，以及 `### 项目结构` 是否非空。

预期：D2/D3 修完后，第 1、2 项**不可能**再同时出现「成功 + 空」。
Task 1–7 针对的都是**已独立确认**的缺陷，无论 Task 0 结果如何都必须修。

---

### Task 1（coze）：fetch 结果自描述 + 禁止「成功但空」

**失败用例**（`tests/test_fetch_execution_context.py` 追加）：

- `test_fetch_multi_file_without_entry_does_not_silently_return_empty`：
  `files` 非空、`entry_file` 空、`source_code` 空 → **必须**返回
  `fetch_context_failed=True` 且 `error` 里含候选文件名列表。
- `test_fetch_reports_file_and_source`：单文件 payload → `file == ""`、
  `file_source == "source_code"`、`code_chars == len(code)`。
- `test_fetch_reports_entry_file_source`：`entry_file` 命中 → `file == "Main.java"`、`file_source == "entry_file"`。

**实现**（`tools/fetch_execution_context.py`）：

- `_resolve_code` 返回 `(code, file_name, file_source, err)`。
- 成功回包新增 `file_source`（`explicit` / `entry_file` / `current_step_file` / `only_file` / `source_code`）
  与 `code_chars: int`。
- 把 `if not code and not steps:` 改为 **`if not code:`** —— 解析不到源码一律结构化失败：

  ```python
  return {
      "error": f"未能取到源码（解析来源：{file_source}；候选文件：{sorted(files)}）。"
               f"请用 file 参数指定要读的文件名。",
      "fetch_context_failed": True,
      "fetch_context_latency_ms": 0.0,
  }
  ```

**渲染**（`harness/render.py::_handle_fetch`）：`digest` 增加 `file_source` 与 `code_chars`，
使模型**一眼**能读出自证信息：

```json
{"stored": true, "file": "Main.java", "file_source": "entry_file", "code_chars": 412, ...}
```

> ⚠ 该改动会**收紧**既有行为：过去「有 steps 无 code」算成功，现在算失败。
> 执行时须全量跑 `uv run pytest tests/ -q`，逐条核对被影响的既有用例是否本就依赖「静默成功」。

---

### Task 2（coze）：入口解析顺序（决策 D3）

**失败用例**：

- `test_fetch_falls_back_to_current_step_file`：`files` 非空、`entry_file` 空、
  `current_step_file == "Util.java"` → 返回 `Util.java` 的代码，`file_source == "current_step_file"`。
- `test_fetch_uses_only_file_when_single`：`files` 只有 1 项、`entry_file` 空 → 返回该文件，`file_source == "only_file"`。
- `test_fetch_explicit_file_wins`：显式 `file` 与 `entry_file` 同时存在且不同 → 取显式那个，`file_source == "explicit"`。

**实现**（`tools/fetch_execution_context.py::_resolve_code`）：按 D3 的顺序改写，并在每一条返回路径上标注来源。
`entry_file` 仍优先于 `current_step_file`（保持既有契约「默认读主入口」）。

---

### Task 3（coze）：P4 阈值补洞

**失败用例**（`tests/test_guard.py` 追加）：

- `test_p4_fires_with_single_file`：`files` 恰 1 项、`file` 名不匹配 → `verdict == "needs_decision"`（HITL 关时 `deny`）。

**实现**（`harness/guard.py:70`）：`len(files) > 1` → `len(files) >= 1`。
理由：P4 要拦的是「请求的文件按既有口径找不到」，与项目有几个文件无关；
`len(files) > 1` 这条额外条件只会把单文件项目**漏**到工具层去吃硬错误。

---

### Task 4（coze）：提示词告知「怎么读观测、拿不到怎么办」

**用例**：`tests/test_prompts.py`（或既有 prompt 用例）断言
`SYSTEM_PROMPT_MAIN_AGENT` 含 `file_source` 与 `code_chars` 字样。

**实现**（`prompts.py:115-140`）：

- 明确：`[fetch_execution_context 结果]` 里的 **`file` 字段告诉你这次拿到了哪个文件**，
  `code_chars` 是字符数；**若 `file` 不是你需要的文件，用 `file` 参数重新取**。
- 明确：返回 `[fetch_execution_context 失败]` 时**不要**说「上下文没有源代码」这类含糊话，
  要么按错误里的候选文件重取，要么如实转述错误。
- 第 123 行的「默认读取主入口」按 D3 的兜底顺序改写一句话（主入口缺失时读当前步所在文件）。
- `### 示例`（:128-139）保持三步式不变（它是本仓评测基线的一部分），只补一句「若第 1 轮返回的是别的文件，改用 file 参数重取」。

---

### Task 5（coze）：终答不再进 `agent_messages`（Bug A 主体，决策 D1）

**失败用例**（`tests/test_harness_loop.py` 追加 + 改写）：

- 新增 `test_terminal_answer_does_not_enter_agent_messages`：终答轮后
  `agent_messages` 长度**不变**。
- 新增红线（端到端、经 SDK 全链路）：`test_client_stream_gets_the_answer_exactly_once` ——
  把 deltas 累加、剥哨兵后，正文**只出现一次**，且 `【决策痕迹】` 只出现一次。
- **改写**既有钉住 P2 的用例：`test_proposal_json_delta_reaches_client_and_predates_sentinels`
  的注释与断言（它原本故意钉住「终答下发两次」的现状）。
- **改写** `tests/test_harness_loop.py:131`（`out["agent_messages"][-1].content == "直接回答"`）
  与 `:292` 的角色交替用例 —— 终答轮不再追加后，末条不再是终答。
- **复核** `tests/test_build_reasoning.py`：`build_reasoning` 从 `agent_messages` 提取「工具调用之间的 AI 思考」，
  终答轮不再入列后，`reasoning` 少一条——**这是更正确的语义**（终答不是「思考片段」），
  但须逐条确认既有断言并在 spec 里记明口径变化。

**实现**（`harness/propose.py`）：

```python
# 终答轮 / 收束轮：不把终答写进 agent_messages。
# 理由：该轮之后图一定不再回到 propose，这条 AIMessage 对后续推理无用，
# 却会作为 answer delta 流到客户端，与 build_final 的终答构成重复正文。
if converging:
    ...
    return {"answer": answer, "agent_messages": history, "proposed_action": {}}

action = parse_action(resp)
if action is None:
    return {"answer": resp, "agent_messages": history, "proposed_action": {}}
# 提案轮（含 ParseError）仍须追加：模型要看到自己上一轮的提案原文，才有因果链
out_messages = history + [AIMessage(content=resp)]
```

> ⚠ `agent_messages` **无 reducer（返回即替换）**，返回 `history` 即等价于「不追加」，语义正确。

---

### Task 6（前端）：把 `entryFile` 写通

**失败用例**（`frontend/src/stores/__tests__/player-entry-file.test.js` 新建）：

- 项目分析成功后 `multiState.entryFile === projectAnalysis.entry`。
- `buildChatBody()` 的 `entryFile` 随之非空。

**实现**（`frontend/src/stores/player.js`）：

- `multiState` 默认值补 `entryFile: ''`（当前连键都没有）。
- `analyzeProject()` 成功分支：`this.multiState.entryFile = data.entry || ''`。
- 若 `/api/run/project` 的响应也带 `entry`，在 `runProject` 成功分支一并写入（执行时确认响应字段名）。

> 与 D3 的关系：这是**前端补齐**（让 payload 正确），D3 是 **coze 兜底**（老客户端也对）。
> 两者都要做——只做 D3 则 `### 项目结构` 与解析口径仍可能不一致。

---

### Task 7（前端）：切换模式时切断残留

**失败用例**：

- `switchMode('single')` 后 `multiState.files.length === 0`。
- 单文件模式下 `buildChatBody().files.length === 0`。

**实现**（`player.js::switchMode`）：切到 `single` 时调用既有 `clearMultiFiles()`（不要新写清理逻辑），
并按需保留/丢弃 `multiState.entryFile`——**执行时定夺**：若确认「切回多文件要能恢复上次项目」，
则改为在 `buildChatBody` 里按 `this.mode` 决定是否携带 `files`/`entryFile`（更小侵入）。
**推荐后者**：模式是发送侧的事实，按模式裁剪 payload 比销毁状态更安全。

---

### Task 8：文档同步

| 文档 | 改什么 |
|---|---|
| `docs/spec/2026-09-13-process-streaming-design.md` | §2.4 的「假前提」段补一条：终答轮不再入 `agent_messages` 后，**流上只剩 `build_final` 一份正文**（P2 已修） |
| `docs/spec/2026-08-10-coze-agent-interface.md` | 决策痕迹 `reasoning` 的口径变化（终答轮不再作为 reasoning 条目）+ fetch 观测新增 `file_source` / `code_chars` |
| `docs/spec/2026-08-23-execution-context-fetch-design.md` | `_resolve_code` 的新解析顺序与「禁止成功但空」 |
| `docs/agent-collaboration-guide.md` | 工具表补 `file_source` 口径；「状态字段」表若动到则同步 |
| `AGENT.md` | 登记本计划 + 对应 devlog / review |

---

## 3. 验收标准

1. **正文只出现一次**：端到端红线用例通过——deltas 累加、剥哨兵后，正文串**恰好出现 1 次**，
   `【决策痕迹】` 恰好 1 次（Bug A）。
2. **不再有「成功但空」**：任何 `fetch_context_failed == False` 的返回都满足 `code_chars > 0`（Bug B 主判据）。
3. **自描述**：每次成功的 fetch 观测都能读出「拿到了哪个文件、多长、来源是哪条兜底」（Bug B 可诊断性）。
4. **单文件项目不合规文件名不再吃硬错误**：走 P4，得到可重试的拒绝理由。
5. **多文件无 `entry_file` 时仍能取到源码**：按 `current_step_file` → 唯一文件 → `source_code` 兜底，
   且 `file_source` 如实标注。
6. 前端切回单文件后，chat payload 不带残留项目文件。
7. 两侧全绿，且**不回归**既有红线：哨兵顺序、被拒工具名不入用户可见产物、导航/编辑建议块不回归。

---

## 4. 验证命令与门槛

```bash
# coze
cd javatutor-coze && uv run pytest tests/ -q            # 基线 407，应 +N 全绿
# 前端
cd JavaTutor/frontend && npx vitest run                 # 基线 431 passed / 32 files
cd JavaTutor/frontend && npm run build
```

- 提交门槛按 `docs/local-dev-convention.md` L1–L5；
- 评估门槛：本修复**改变终答的流式行为**，须在重发 agent 后补一轮端到端评估，
  确认 Judge 均分下降 ≤ 0.3 且 Grounding 下降 ≤ 0.5（若未重发，则离线门槛全绿即可，但须在 devlog 里注明「线上未验证」）。

---

## 5. 风险与回滚

| 风险 | 影响 | 处置 |
|---|---|---|
| Task 1 收紧「成功但空」→ 失败 | 过去算成功的调用现在算失败，可能改变既有评测样本表现 | 全量回归 + 抽一条历史样本人工比对；若某类 payload 本就不带源码，改为在 fetch 失败文案里**明说**（模型据此如实告知而非编造） |
| Task 5 终答不入 `agent_messages` → `reasoning` 少一条 | 决策痕迹的 `reasoning` 变短 | 视为**更正确**的语义并写进 spec；若评测侧有断言依赖，同步改 |
| Task 7 清空 `multiState.files` 破坏「切回多文件恢复项目」 | 用户体感数据丢失 | 推荐走「按 `this.mode` 裁剪 payload」分支，不动状态 |
| 前端改动未重发即上线 | 前后端版本错配 | D3 的 coze 兜底保证老前端也对；D1 是纯 coze 侧 |

回滚单位：Task 5（Bug A）与 Task 1–4（Bug B）**互相独立**，任一可单独回滚。

---

## 6. 执行顺序建议

```
Task 0（取证，可与其余并行）
Task 1 → Task 2 → Task 3 → Task 4        # coze 侧 Bug B，同一文件族，串行
Task 5                                    # coze 侧 Bug A，独立
Task 6 → Task 7                           # 前端
Task 8                                    # 文档
```
