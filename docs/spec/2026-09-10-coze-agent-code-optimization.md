# Coze Agent 代码优化（优化卡 + 报错预填）规格

> 状态：**spec 阶段**（本文档为实施方案，供执行组落地）。
> 来源：2026-09-10 `/grilling` 会话收敛结论。
> 关联：
> - 消息契约：[2026-08-10-coze-agent-interface.md](./2026-08-10-coze-agent-interface.md)（本 spec 为其新增「编辑建议块扩展」）。
> - 结构化块先例：[2026-09-07-coze-agent-view-navigation.md](./2026-09-07-coze-agent-view-navigation.md)（视角导航块，同为「输出指令」形态）。
> - 前端仓库：`javatutor`；coze 仓库：`javatutor-coze`；后端仓库：`javatutor/backend`（本 spec 两仓 + 后端都涉及）。

## 1. Context（为什么做）

用户希望 agent 不止「解释代码」，还能**改进代码**：根据用户需求给出优化方案，用户点击即把优化后的代码加载到左侧编辑器，并**随时撤销**。
同时，当用户代码**报错**时，希望就地在错误提示旁提供一个入口，把「含错误的提问」交给 agent，让 agent 给出修正方案。

该模块未来可能接入队友开发的 **harness 人在回路**：届时「卡片」形态会被「用户选项」取代。因此本设计的核心要求之一是
**载荷与呈现分离**——卡片只是当前这一版 presentation，数据契约必须能原样变成一组用户选项。

## 2. 已收敛的决策（/grilling 结论）

| # | 决策 | 理由 |
|---|---|---|
| D1 | **不是工具，是输出指令**（回答里附结构化块） | 架构上不可能做工具：agent 无写入通道（后端透传、前端渲染）；工具在本系统语义 = **只读取执行证据**（`step_facts`/`fetch_execution_context`），且未知工具在 `main_agent` 直接落「不可用」分支（[main_agent.py:210-213](../../src/graphs/javatutor/main_agent.py)）。 |
| D2 | **优化 = 整文件替换**（区别于 `【编辑建议】` 的局部 patch），带目标与理由 | 大重构下 `old_string` 定位脆弱；整文件重写适用于「换写法」而非「补几行」。 |
| D3 | **复用 `【编辑建议】` 块，加 `kind` 判别**，不新开块 | 一份 mark / 一个解析器 / 一套 apply-undo 通道；避免第二套块契约（本周刚修过「agent 连一个末尾块都守不稳」的裸 JSON bug）。 |
| D4 | **两步式：第一步给「方案卡 = 目标选项」，点击某目标才生成代码** | 把最贵、最易坏的一步（整份代码生成）推迟到用户明确选择之后；同时天然贴合 HITL 的「用户选项」。 |
| D5 | **`goal` = 闭集枚举 + 可选 `detail`**；点击时的 prompt 由**前端模板拼** | 确定、可测、可日志、可拦截；`detail` 保留「针对这段代码的具体手段」。 |
| D6 | **门禁 = 候选先经 `/api/run` 跑通才允许应用** | 整文件覆盖没有任何结构检查（不像 patch 有 not-found/ambiguous/conflict 跳过）；门禁是同一次运行同时产出「前后对比」与「覆盖后右侧刷新」的数据源。 |
| D7 | **覆盖后用门禁那次运行结果刷新右侧** | 否则编辑器是新代码、右侧面板仍是旧运行，教学场景严重误导。 |
| D8 | **块必带 `target` 文件名**（单文件模式缺省为当前文件） | 多文件下必须明确覆盖哪个文件；缺省会覆盖错文件。 |
| D9 | **报错入口 = 只预填，用户确认再发**（不是自动转发） | 教学工具不该剥夺学生自己思考的机会；成本与节奏由用户控。**注意：这是「代写提问」，不是「直接转发」**。 |
| D10 | **撤销 = Monaco undo 优先 + 快照回退** | 现有 token 语义「一打字即失效」，对「一键换掉整个文件」这个高风险动作过于致命。 |
| D11 | **第二步的整份代码走 JSON 字符串**（沿用现有链路） | 与 patch 同构、解析器零改动；门禁天然兜底（转义坏→JSON 解析失败→回退正文；截断→编译不过→拦截）。 |

## 3. 关键前提（只读勘测结论，已核实）

落地前请先确认这些事实，它们决定了改动面：

| 事实 | 位置 | 对本 spec 的影响 |
|---|---|---|
| `【编辑建议】` 块现有形态为 `{"edits":[{"title","explanation","old_string","new_string"}]}`，解析器要求 `old_string` 非空字符串 | [editSuggestion.js:96-106](../../../javatutor/frontend/src/utils/editSuggestion.js) | `kind:"replace"` 没有 `old_string`，需在解析器里按 `kind` 分支，**不能**沿用现有过滤条件。 |
| `applyAiEdits` 用 `executeEdits` 批量应用（单 undo 单元），返回 `undoToken`；`undoAiEdits` 仅当 `model.getVersionId() === undoToken` 时生效 | [Editor.vue:311-350](../../../javatutor/frontend/src/components/Editor.vue) | 整文件覆盖应实现为「覆盖全文区间的 `executeEdits`」以复用 undo 栈；token 失效时走快照回退（D10）。 |
| `applyRunResult` 会**重置会话状态**（`chatMessages=[]`、`explainHistory={}`、`activeAiTab='explain'`、清 analysis 等） | [player.js:166-181](../../../javatutor/frontend/src/stores/player.js) | **不能**直接复用它刷新右侧，否则会清空聊天与导航状态。需新增一个只更新运行结果的变体（见 §7.1）。 |
| `store.error` 由 `GlobalStatus.vue` 承载，**6 秒自动消失并置 `store.error = null`** | [GlobalStatus.vue](../../../javatutor/frontend/src/components/GlobalStatus.vue) | 报错入口**不能**挂在这个 toast 上（按钮只有 6 秒寿命 + 状态被删）。 |
| 聊天输入草稿 `chatInput` 是 `AiTutorPanel.vue` 的**局部 ref**；发送走 `store.askQuestion(q)` 并清空草稿 | [AiTutorPanel.vue:91,206-211](../../../javatutor/frontend/src/components/AiTutorPanel.vue) | 「预填」需把草稿**提升到 store**（`store.chatDraft`），否则 `ConsoleOutput` 写的字进不了输入框；「点击目标发起新一轮」可直接复用 `store.askQuestion()`。 |
| `/api/ai/chat` 把 `compileError` **硬编码为 `null`** | [CozeAIController.java:82](../../../javatutor/backend/src/main/java/com/javatutor/controller/CozeAIController.java) | 本 spec 的预填方案**绕开**它（错误文本进 `user_question`）。记录在案：compile_error 通道目前并未真正启用。 |
| `/api/run` 总是编译**并执行**（5s 超时），`RunResponse` 只有单一 `error` 字符串，**不区分**编译错/运行错/超时/沙箱拦截 | [RunController.java:509-555](../../../javatutor/backend/src/main/java/com/javatutor/controller/RunController.java) | 门禁无法只验「编译通过」，故 D6 定为「能跑通」；候选被真跑一次。 |
| `source_code` 每次调用都会发给 agent | [CozeService.java:69,80](../../../javatutor/backend/src/main/java/com/javatutor/service/CozeService.java) | agent 本来就拿得到源码，**不需要新工具**去读代码。 |

## 4. 指令契约：`【编辑建议】` 块扩展

`【编辑建议】` 块新增顶层 `kind` 字段，默认 `"patch"`（向后兼容）：

| kind | 用途 | 载荷 |
|---|---|---|
| `patch`（默认，**不变**） | 局部替换 | `{"edits":[{"title","explanation","old_string","new_string"}]}` |
| `options` | **方案卡**：候选优化目标 | `{"kind":"options","target":"...","options":[{"goal","label","detail"}]}` |
| `replace` | **整文件覆盖** | `{"kind":"replace","target":"...","goal":"...","rationale":"...","code":"<整份新代码>"}` |

放置规则与既有块一致：正文 → `【编辑建议】`（如有）→ `【视角导航】`（如有）→ `【决策痕迹】`；与正文空一行分隔；
**每答最多一个 `【编辑建议】` 块**；`options` 与 `replace` 不同时出现（一个是提方案、一个是交付）。

### 4.1 `kind:"options"`（方案卡）

```json
{"kind":"options","target":"Solution.java","options":[
  {"goal":"performance","label":"以性能为先","detail":"用哈希表把嵌套循环降为 O(n)"},
  {"goal":"readability","label":"以可读性为先","detail":"拆分长方法、给中间变量命名"}
]}
```

- `options`：2–3 项；`goal` 必须是 §4.4 闭集；`label` 卡片文本；`detail` 可选，具体手段。
- **本块不含任何代码**。点某个选项 = 前端按 §4.4 模板拼一条提问并**发起新一轮对话**（等价于用户自己问了那句话）。

### 4.2 `kind:"replace"`（整文件覆盖）

```json
{"kind":"replace","target":"Solution.java","goal":"performance",
 "rationale":"把内层线性查找换成哈希表，整体由 O(n²) 降为 O(n)。",
 "code":"import java.util.*;\n\npublic class Solution {\n  ...\n}\n"}
```

- `code`：**完整、可独立编译**的该文件全文；不得省略、不得用 `...` 占位。
- `target`：目标文件名（见 §4.5）；必须与 `kind:"options"` 那一轮一致。
- `goal`：应等于用户点选的那个 goal（保证「点的什么、给的就是什么」）。
- `rationale`：一到两句，说明改了什么、为什么。

### 4.3 两步时序

```text
用户：帮我优化一下这段代码
  └─ 第 1 轮回答：正文（说明可优化点）+ 【编辑建议】{"kind":"options",...}   ← 不出代码
      └─ 用户点击「以性能为先」
          └─ 前端发新提问：「以 性能 为优先优化当前代码，具体要求：用哈希表把嵌套循环降为 O(n)」
              └─ 第 2 轮回答：正文（说明改动）+ 【编辑建议】{"kind":"replace",...}
                  └─ 前端自动跑门禁 → 通过 → 「应用」可用
                      └─ 用户点「应用」→ 覆盖编辑器 + 右侧刷新为候选运行结果 + 出现「撤销」
```

- **第 1 轮只提方案，绝不带代码**；**第 2 轮才交付代码**。
- 用户显式请求（「帮我优化一下」）同样走两步——方案卡即目标选择器，点一下即生成，不再多一次点击。
- 若用户提问已含明确目标（「帮我优化性能」），agent **仍先出方案卡**（只给该目标一项或两项），保持交互一致。

### 4.4 `goal` 闭集与点击 prompt

闭集（`goal` 合法取值 / 前端规范名）：

| goal | 中文名 |
|---|---|
| `performance` | 性能 |
| `readability` | 可读性 |
| `memory` | 内存 |
| `style` | 规范 |
| `correctness` | 正确性 |

- 前端按模板拼提问（确定、可日志）：
  `以「{中文名}」为优先优化当前代码` + （有 `detail` 时）`，具体要求：{detail}` + `。请给出优化后的完整代码。`
- 非闭集取值 → 该 option 丢弃；`options` 全部非法 → 整块按正文展示（不崩、不出卡）。

### 4.5 `target`

- 多文件模式：**必填**，取 `multiState.files` 中的文件名。
- 单文件模式：可省略，缺省为当前单文件。
- `target` 在 `multiState.files` 中找不到：**不覆盖**，卡片显示「目标文件不存在」并禁用应用（不得静默覆盖当前激活文件）。

### 4.6 兼容与降级

- 无 `kind` 或 `kind:"patch"` → 完全走现有逻辑（**必须零行为变化**）。
- `kind` 非法 / `code` 为空 / `options` 为空 → 整块按正文展示（复用现有 `usable` 回退语义，[editSuggestion.js:69-114](../../../javatutor/frontend/src/utils/editSuggestion.js)）。
- 解析失败一律不抛异常、不崩。

## 5. 报错入口（预填，D9）

- **入口位置**：控制台面板（`ConsoleOutput.vue`），不是 6 秒即逝的 `GlobalStatus` toast。
- **错误文本持久化**：`runCode`/`runProject` 失败时除 `store.error` 外，另写 `store.lastRunError = { message: 错误原文 }`；
  `GlobalStatus` 清 `store.error` 时**不得**清 `lastRunError`。控制台据此渲染入口（可多次复用，直到下次运行）。
  - 只留 `message`：早期版本还带 `code`/`mode`，但**无人消费**，且 `code` 在多文件下取的是 `store.code`（激活文件）而非整个项目、
    语义片面；将来若要「把代码一并附给 agent」，应走 Shell 的 `getCode` 而不是这个字段（见 review R5）。
- **点击行为（只预填 + 切到 agent 面板）**：把下列文本写入 agent 输入框草稿，**不发送**：
  ```text
  我的代码运行报错了，请帮我看看怎么修正：
  <错误原文>
  ```
  入口渲染在「内存状态」pane，而输入框在「agent」pane —— 两个 pane 由互斥的 `v-show` 控制、从不同时可见，
  故必须同时 `navigateTo('tutor')`，否则点击后画面毫无变化、草稿落在看不见的面板里（见 review R1）。
  用户可编辑后再自行发送。
- **不做**：不自动发送、不自动附导航卡、不在报错时替用户决定优化目标。

## 6. 门禁与撤销

### 6.1 门禁（D6）

- 收到 `kind:"replace"` 块后，前端**自动**把候选代码送去跑一次：
  - 单文件：`POST /api/run`，body `{code: <候选>}`（test 模式带 `mode:'test'` + `testCases`）。
  - 多文件：`POST /api/run/project`，body `{files: <全部文件，其中 target 替换为候选>}`。
- `success !== true`（含编译错、运行异常、超时、沙箱拦截）→ 卡片显示错误原文，**「应用」禁用**。
- `success === true` → 「应用」可用；**该次运行结果同时缓存为「覆盖后」快照**（供 §6.2 与 D7 使用）。
- 门禁是**前端**动作，不经过 agent、不消耗 agent token。
- **局限（已知并接受）**：门禁只能验「能不能跑」，验不了「有没有偷改语义」。前后对比展示是对用户的部分补偿。

### 6.2 应用与撤销（D10）

**应用**：
- 实现为**覆盖全文区间的 `executeEdits`**（而非 `setCode`），以复用 Monaco undo 栈与 `undoToken`，使整次覆盖是**一个撤销单元**。
- 多文件模式：替换 `multiState.files[i].code` 并刷新编辑器。
- 应用后：右侧面板刷成「覆盖后」快照（§7.1），并展示前后对比（输出/步数变化）。

**撤销**：
1. **优先** Monaco undo：`undoAiEdits(token)` 成功 → 精确回滚，右侧恢复为覆盖前快照。
2. **回退** 快照还原：token 失效（用户已编辑）→ 用卡片持有的**覆盖前代码快照**整体还原，并在按钮上明示
   **「将丢弃此后的编辑」**（需用户确认）。
- 快照在收到 `replace` 块时即捕获，避免应用时机与快照时机错位。
- **运行快照由卡片自持，不存 store 单槽**（见 review R2）：`applyCandidateRun` 返回它记录的「覆盖前」右侧快照，
  卡片存为 `appliedRunSnapshot`，撤销时 `restorePreviousRun(该快照)` 显式回传。
  单槽在「连续应用两张卡、再依次撤销」时会只剩最后一次的快照 → 编辑器回退到 A 前、右栏却回填 B 后的运行结果，
  且 `store.code` 与编辑器内容不符（后续提问发给 agent 的 `source_code` 跟着错）。

## 7. 改动清单

### 7.1 前端（`javatutor/frontend`）

1. **解析** — `src/utils/editSuggestion.js`
   - `extractStructBlocks` 按 `parsed.kind` 分支：`patch`（现状）/ `options` / `replace`。
   - `parseAssistantMessage` 返回值扩展为 `{ body, edits, nav, plan }`：
     `plan = { kind:'options', target, options:[{goal,label,detail}] }`
     ｜ `{ kind:'replace', target, goal, rationale, code }` ｜ `null`。
   - 每个 `kind` 各自的 `usable` 判定（§4.6）；非法一律回退正文。
   - 更新 `src/utils/editSuggestion.test.js`。
2. **卡片** — **新建** `src/components/OptimizationCard.vue`（`EditSuggestionCard.vue` **不改**，patch 路径零回归）
   - `options` 分支：渲染目标选项按钮，点击调 `store.askGoalOptimization(goal, detail, target)`。
   - `replace` 分支：渲染目标/理由 + 门禁状态 + 应用/撤销。
   - 共享的仍是**块通道**与其 apply/undo 原语（`applyAiEdits`/`undoAiEdits`），不是组件。
   - **整文件覆盖的实现 = 一条 `old_string` 为「当前全文」的 edit**，直接复用 `applyAiEdits`：
     `planEdits` 全文唯一匹配 → `ok` → `executeEdits` 覆盖全文，**天然是单个 undo 单元**，`undoToken` 语义原样可用。
     编辑器为空时 `planEdits` 返回 `not-found`，退回 `restoreCode(candidate)` 直接写入。
3. **动作** — `src/stores/player.js`
   - 新增 `applyCandidateRun(snapshot)`：**只**更新 `steps`/`output`/`runId`/`currentStep`/`methodName`/`methodSignature`
     并触发 `requestAnalysis`/`requestControlFlow`；**不得**清 `chatMessages`/`explainHistory`/`activeAiTab`
     （这是与 `applyRunResult` 的关键区别，见前提表）。
   - 新增 `lastRunError` 状态；`runCode`/`runProject` 失败时写入。
   - 新增「按 goal 拼提问并发送」：模板拼好后直接调 `store.askQuestion(模板文本)`（复用既有发送入口）。
   - 把 `AiTutorPanel.vue` 的局部 `chatInput` 提升为 `store.chatDraft`（`v-model="store.chatDraft"`），`sendChat` 发送后清空。
4. **报错入口** — `src/components/ConsoleOutput.vue`
   - `lastRunError` 存在时渲染入口按钮；点击**只**写 `store.chatDraft = <错误文本 + 请求修正>`，**不发送**。
5. **多文件** — `src/components/MultiFileShell.vue` / `SingleFileShell.vue`
   - 按文件名替换 `multiState.files[i].code` 并切到该文件（`activeFileIndex`）。
   - 两者新增 `provide('restoreCode', ...)`，供卡片在撤销兜底时直接写入编辑器/文件内容。

### 7.2 coze（`javatutor-coze`）

1. **`prompting/panels.py` 或新 `prompting/optimization.py`** — 新增 `render_optimization_guidance()`：
   - `【编辑建议】` 的 `kind` 闭集（`patch`/`options`/`replace`）与各自形态；
   - **两步式**：第一轮只给 `options`（2–3 项、闭集 goal），**不得**在同一轮给代码；用户选定目标后第二轮才给 `replace`；
   - `goal` 闭集表；`replace` 的 `code` 必须是**完整可编译**的整份文件（不得占位省略）；
   - 与「报错修正」的关系：报错场景同理——先给修正方案选项，选定后给整份代码；
   - `target` 规则（多文件必填）。
2. **`main_agent.py`** — `_main_system_prompt()` 注入 `render_optimization_guidance()`（走 SystemMessage，不被 compress 截断）。
3. **`prompts.py`**
   - `SYSTEM_PROMPT_CRITIC`：评审正文时**忽略** `【编辑建议】` 的结构化块；不得因 `kind:"options"`/`"replace"` 判失败。
   - `SYSTEM_PROMPT_REVISE`：修订时**保留**结构化块（除非评审明确标记非法）。
4. **`prompting/main_fewshots.py`** — 新增样例：
   - 第 1 轮：问「帮我优化一下」→ 只给 `options` 方案卡（无代码）；
   - 第 2 轮：选定 `performance` → 给 `replace` 整份代码 + `rationale`。
5. **守卫测试** — `tests/`：引导块含 goal 闭集、两步式约束；few-shot 样本 JSON 合法、`options` 的 goal 全部落在闭集内。

### 7.3 后端（`javatutor/backend`）

- **本 spec 无需改动**（报错走预填 → `user_question`；门禁复用既有 `/api/run`、`/api/run/project`）。
- 记录在案（**不在本次范围**）：`CozeAIController` 的 `compileError` 恒为 `null`，若后续要「agent 原生感知编译错误」需另行打通。

## 8. 验收标准

1. 「帮我优化一下」→ 第 1 轮回答**附方案卡**（2–3 个闭集目标选项），**正文与块内均无优化代码**。
2. 点「以性能为先」→ 前端发出模板提问（可在消息列表看到），第 2 轮回答附 `kind:"replace"` 块。
3. **门禁**：候选跑不通 → 卡片显示错误、「应用」禁用；跑通 → 「应用」可用。
4. 点「应用」→ 编辑器被覆盖为候选代码（**一个撤销单元**），右侧面板刷新为候选运行结果，前后对比可见。
5. **撤销**：未编辑时 → 精确回滚；已编辑时 → 提示「将丢弃此后的编辑」并快照还原。
6. **报错**：运行失败后，控制台面板出现入口且**不会 6 秒消失**；点击**只预填不发送**；用户可编辑后发送。
7. **多文件**：`target` 指定文件被覆盖；`target` 不存在 → 不覆盖、禁用应用、明确提示。
8. **兼容**：无 `kind`/`kind:"patch"` 行为与现状**完全一致**；`kind` 非法、`code` 空、`options` 空 → 块按正文展示，不崩。
9. `【编辑建议】`/`【视角导航】` 仍不会以裸 JSON 出现在正文（沿用 2026-09-09 的剥离逻辑）。

## 9. 测试

- **前端**：`editSuggestion.test.js`（`options`/`replace` 解析、`usable` 回退、`patch` 回归）、卡片三分支渲染、
  `applyCandidateRun` 不清会话、整文件覆盖的 apply/undo（含 token 失效回退快照）、多文件 target 替换、
  `npm test` 全绿。
- **coze**：`uv run pytest -q` 全量；新增引导/few-shot 守卫（goal 闭集、两步式、`code` 完整性要求）。
- **手验**：`npm run dev` 跑验收 1–8（含报错预填与多文件）。

## 10. 风险 / 待确认

- **门禁验不了语义偷改**（仅「能跑」）：已接受；用前后对比（输出/步数）部分补偿。
- **长文件下整份代码的 JSON 转义失败率**（D11）：失败表现是「没有卡片」，不会崩；若线上失败率高，再补「围栏回退解析」。
- **`applyRunResult` 会话重置陷阱**（前提表）：必须新增独立变体，否则应用一次优化会清空整个聊天记录。
- **快照撤销会丢弃用户此后的编辑**：需 UI 明示并确认。
- **critic/revise 可能不认新块**：prompt 与测试都要覆盖；否则出现「方案卡被修订掉」。
- **`lastRunError` 的生命周期**（何时清）：建议下次成功运行或用户手动关闭时清。
- **HITL 对接点**：`option` 结构 `{goal,label,detail}` + 前端 prompt 模板需保持稳定，供 harness 以「用户选项」直接复用。

## 11. 文档登记

- 接口契约：`docs/spec/2026-08-10-coze-agent-interface.md` 增「编辑建议块扩展（kind）」小节（§2.2）。
- 本 spec：`docs/spec/2026-09-10-coze-agent-code-optimization.md`。
- 若图结构/节点输入输出有变，同步 `docs/agent-collaboration-guide.md`。
- 实现后补 `docs/devlog/2026-09-10-coze-agent-code-optimization.md` 与 review。
