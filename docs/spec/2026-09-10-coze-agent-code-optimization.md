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
| D4 | **两步式：第一步给「方案卡 = 目标选项」，用户勾选（可多选）并提交后才生成代码** | 把最贵、最易坏的一步（整份代码生成）推迟到用户明确选择之后；同时天然贴合 HITL 的「用户选项」。**2026-09-10 修订**：单选 → 多选（提交制），时序见 §4.3。 |
| D5 | **`goal` = 闭集枚举 + 可选 `detail`**；提交时的 prompt 由**前端模板拼**（白名单 + 黑名单） | 确定、可测、可日志、可拦截；`detail` 保留「针对这段代码的具体手段」。**2026-09-10 修订**：模板补黑名单（未勾选项），修「agent 顺手把没勾的方向也改了」。 |
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
| `store.error` 由 `GlobalStatus.vue` 承载，**6 秒自动消失并置 `store.error = null`**；它是唯一在所有模式/tab 下都可见的挂载点 | [GlobalStatus.vue](../../../javatutor/frontend/src/components/GlobalStatus.vue) | **2026-09-10 修订**：入口改挂在 `GlobalStatus`（原方案在控制台面板，用户常在别的 tab 看不到 → review R1）。配套去掉**运行类**错误的 6 秒自动消失（`isRunError`），否则按钮还是只有 6 秒寿命。 |
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

- `options`：2–3 项；`goal` 必须是 §4.4 闭集（**不含 `comprehensive`**）；`label` 卡片文本；`detail` 可选，具体手段。
- 每个 option 必须是**独立可组合**的一个方向：不要在一个 option 里塞多个方向，也不要写「既提升性能又改善可读性」——组合交给用户勾选。
- **本块不含任何代码**。前端把方案卡渲染为**多选**（点行切换勾选态，≥2 项时另有「全选」）；
  提交（不是点单行）时按 §4.4 模板拼一条提问并**发起新一轮对话**（等价于用户自己问了那句话）。
- 用户已在提问里指明目标（如「优化性能」）时**仍先出方案卡**（只列该目标一项），保持交互一致。

### 4.2 `kind:"replace"`（整文件覆盖）

```json
{"kind":"replace","target":"Solution.java","goal":"performance",
 "rationale":"把内层线性查找换成哈希表，整体由 O(n²) 降为 O(n)。",
 "code":"import java.util.*;\n\npublic class Solution {\n  ...\n}\n"}
```

- `code`：**完整、可独立编译**的该文件全文；不得省略、不得用 `...` 占位。
- `target`：目标文件名（见 §4.5）；必须与 `kind:"options"` 那一轮一致。
- `goal`：用户只勾 **1 个**方向时等于该 goal；勾 **≥2 个**时填 `comprehensive`（保证「点的什么、给的就是什么」，
  多方向下 `rationale` 需**分别**说明各方向各改了什么）。
- `rationale`：一到两句，说明改了什么、为什么。
- **方向硬约束**：只改用户勾选的方向；方案卡里**未勾选**的方向（提问中以「不要顺带做其他方向的改动（例如：…）」列出）
  一律不得改造——即使 agent 认为它们也能优化。可在正文提一句，但代码里不许动。
- **评审门（2026-09-14 增）**：第二步（`replace`）是**交付**，agent 不得被评审以「格式/引用不完整」为由打回。
  评审对 `replace` 的否决权**限于**「没答用户的问题」与「越出了所选方向」两类实质问题
  （见 `docs/spec/2026-08-10-coze-agent-deepening-design.md` D-02/D-10）。
  此前评审把「代码块里没有步骤引用」当缺陷，导致第二步的整份代码反复被要求修订、`replace` 块被改写。

### 4.3 两步时序

```text
用户：帮我优化一下这段代码
  └─ 第 1 轮回答：正文（说明可优化点）+ 【编辑建议】{"kind":"options",...}   ← 不出代码
      └─ 用户在方案卡上勾选（可多选）后点「提交」
          └─ 前端发新提问（§4.4 模板）：「【优化第二步】只做「以性能为先」方向的优化，具体要求：用哈希表把嵌套循环降为 O(n)。
             不要顺带做其他方向的改动（例如：「以可读性为先」：拆分长方法并命名中间变量）。请给出优化后的完整代码。」
              └─ 第 2 轮回答：正文（说明改动）+ 【编辑建议】{"kind":"replace",...}
                  └─ 前端自动跑门禁 → 通过 → 「应用」可用
                      └─ 用户点「应用」→ 覆盖编辑器 + 右侧刷新为候选运行结果 + 出现「撤销」
```

- **判别第二步的唯一依据：提问是否以 `【优化第二步】` 起头。**
  - 为什么要一个显式标记：`/api/ai/chat` **不带任何对话历史**（无状态），会话工作记忆只保留上一答**前 200 字**，
    而 `options` 块在回答**末尾** ⇒「上一轮已经给过方案卡」在服务端读不到。
  - 为什么不能靠措辞判别：第二步提问的形状（「只做「以性能为先」方向的优化」）**恰好就是**「已含明确目标」
    的形状，与「用户已指明目标仍先出方案卡」（下一条）**直接冲突**——同形输入被要求走两条分支，模型无法判别，
    实测表现为「再给一次一模一样的方案卡、一行代码都没有」的死循环。
  - 因此标记**必须由前端写进提问**；两侧字面量硬编码（coze `prompting/optimization.py::STEP2_MARKER`
    与前端 `utils/editSuggestion.js::STEP2_MARKER`），各配一条跨仓断言，任何一端改字另一端必须红。
- **第 1 轮只提方案，绝不带代码**；**第 2 轮才交付代码**。
- 用户显式请求（「帮我优化一下」）同样走两步——方案卡即多选目标选择器，**勾选 + 提交**后才生成
  （有意从早期的「点一下即生成」改为多选：单方向是一次点击，多方向不必再问一轮）。
- 若用户提问已含明确目标（「帮我优化性能」）但**不带 `【优化第二步】` 标记**，agent **仍先出方案卡**
  （只给该目标一项或两项），保持交互一致——判别只看标记，不看措辞。

### 4.4 `goal` 闭集与点击 prompt

闭集（`goal` 合法取值 / 前端规范名）：

| goal | 中文名 | 备注 |
|---|---|---|
| `performance` | 性能 | |
| `readability` | 可读性 | |
| `memory` | 内存 | |
| `style` | 规范 | |
| `correctness` | 正确性 | |
| `comprehensive` | 综合 | **仅第 2 轮 `replace` 使用**（用户勾了 ≥2 个方向时）；方案卡 `options` 不得产出 |

- 前端按模板拼提问（确定、可日志）——**一律以 `【优化第二步】` 起头**（判别器，见 §4.3），随后：
  - **单方向**（白名单 + 黑名单）：
    `只做「{中文名}」方向的优化` + （有 `detail` 时）`，具体要求：{detail}`
    + `。不要顺带做其他方向的改动（例如：{未勾选项逐条列出}）` + `。请给出优化后的完整代码。`
    （黑名单恒 = **同一张方案卡里未勾选**的项；全选时该项为空，模板不含黑名单句。）
  - **多方向**（勾了 ≥2 项，逐条列出，序号为 `①②③`）：
    `只做以下方向的优化：①「{名}」：{detail}；②「{名}」：{detail}` + 黑名单（同上，如有）
    + `。请给出优化后的完整代码。`
    （agent 应把 `goal` 记为 `comprehensive`。）
- 例（单方向）：`【优化第二步】只做「以性能为先」方向的优化，具体要求：用哈希表把嵌套循环降为 O(n)。请给出优化后的完整代码。`
- 名称取 `label || GOALS[goal]`；无勾选时不发送（**也不得只发一个光标记**）。
- 非闭集取值 → 该 option 丢弃；`options` 全部非法 → 整块按正文展示（不崩、不出卡）。
- 实现：前端 `utils/editSuggestion.js::buildGoalPrompt(selected, excluded)`（纯函数，配 vitest 用例；
  标记常量 `STEP2_MARKER` 与 coze 侧同名字面量互为跨仓握手）。

### 4.5 `target`

- 多文件模式：**必填**，取 `multiState.files` 中的文件名。
- 单文件模式：可省略，缺省为当前单文件。
- `target` 在 `multiState.files` 中找不到：**不覆盖**，卡片显示「目标文件不存在」并禁用应用（不得静默覆盖当前激活文件）。

### 4.6 兼容与降级

- 无 `kind` 或 `kind:"patch"` → 完全走现有逻辑（**必须零行为变化**）。
- `kind` 非法 / `code` 为空 / `options` 为空 → 整块按正文展示（复用现有 `usable` 回退语义，[editSuggestion.js:69-114](../../../javatutor/frontend/src/utils/editSuggestion.js)）。
- 解析失败一律不抛异常、不崩。

## 5. 报错入口（预填，D9）

- **入口位置**：**全局红色弹窗（`GlobalStatus.vue`）**——它是唯一在所有模式 / 所有 tab 下都可见的挂载点
  （控制台只在「内存状态」pane 里，用户通常正停在别的 tab 上看不到）。
- **错误文本持久化**：`runCode`/`runProject` 失败时除 `store.error` 外，另写 `store.lastRunError = { message: 错误原文 }`；
  `GlobalStatus` 清 `store.error` 时**不得**清 `lastRunError`。
  - 只留 `message`：早期版本还带 `code`/`mode`，但**无人消费**，且 `code` 在多文件下取的是 `store.code`（激活文件）而非整个项目、
    语义片面；将来若要「把代码一并附给 agent」，应走 Shell 的 `getCode` 而不是这个字段（见 review R5）。
- **运行类错误不再自动消失**：`store.error` 与 `store.lastRunError.message` 同文（`isRunError`）时，弹窗**常驻**，
  只能靠「用户点 `×`」或「下一次成功运行把 `store.error` 置 `null`」撤下；其余（非运行类）错误仍 6 秒自动消失（`TRANSIENT_ERROR_MS`）。
  - 判据见 `utils/errorEntry.js::isRunError / shouldAutoDismiss`（纯函数，配 vitest 用例）。
  - 点 `×` 时一并 `store.clearRunError()`，避免弹窗关了入口还在（单片残余状态）。
- **点击行为（只预填 + 切到 agent 面板 + 聚焦）**：把下列文本写入 agent 输入框草稿，**不发送**：
  ```text
  我的代码运行报错了，请帮我看看怎么修正：

  [运行环境]
  - 文件模式：多文件（3 个文件，主入口 Main.java）      ← 仅多文件时出现
  - 运行模式：默认模式（测试模式未激活：已保存用例 0 条）

  [错误原文]
  <错误原文>
  ```
  - `[运行环境]` 块由 `utils/errorEntry.js::runEnvLines(ctx)` 产出（`ctx` 缺省 ⇒ 整块省略，退化为旧文本）；
    首行与 `[错误原文]` 小节是稳定骨架。
  - **只陈述事实**（本次的模式 / 文件形态与计数），**不写任何 JavaTutor 运行语义**——
    「默认模式需要 main / 测试模式会抽取块注释里的类」由 coze 侧知识与引导给出（见
    [2026-09-12 测试模式误诊修复](../devlog/2026-09-12-coze-agent-test-mode-context.md) 的 F2）。
  - 强调用**纯文本**（括号承载含义）而非 `**`：该文本落在草稿 textarea 与转义渲染的用户气泡里，**两处都不走 markdown**。
  - 模式事实同时随**每次**提问走请求体（`run_mode` / `test_case_count`，见
    [2026-08-10-coze-agent-interface.md](./2026-08-10-coze-agent-interface.md) §1.1），不只在报错入口。
  输入框在「agent」pane，而用户可能停在任意 tab —— 故 `focusChatWithDraft()` 必须同时
  `navigateTo('tutor')` 并 `chatFocusNonce += 1`（`AiTutorPanel` 监听后 `focus()` + 光标移到末尾），
  否则点击后画面毫无变化、草稿落在看不见的面板里（见 review R1 / F5）。
  用户可编辑后再自行发送。
- **不做**：不自动发送、不自动附导航卡、不在报错时替用户决定优化目标。

## 6. 门禁与撤销

### 6.1 门禁（D6）

- 收到 `kind:"replace"` 块后，前端**自动**把候选代码送去跑一次：
  - 单文件：`POST /api/run`，body `{code: <候选>}`（test 模式带 `mode:'test'` + `testCases`）。
  - 多文件：`POST /api/run/project`，body `{files: <全部文件，其中 target 替换为候选>}`。
- `success !== true`（含编译错、运行异常、超时、沙箱拦截）→ 卡片显示错误原文，**「应用」禁用**；
  **若该卡是最新一条 assistant 消息**，自动发起返修提问（上限 2 次 ≈ 最多 3 版候选，
  见 `docs/plan/2026-09-12-coze-agent-optimization-gate-retry-plan.md`）；
  耗尽 / 非最新 / 传输失败 → 保持禁用（现状行为）。
- 返修**不新增消息、不新增记录点**：只重写该条 assistant 消息的 `text`（`chatMessages.length` 与 `timeline` 不变）。
  这是时间线 `chatPoint.chatIndex` 语义（下标即折叠边界）的前提，不得破坏。
- **传输失败**（fetch 抛异常 / HTTP ≥ 400，见 §6.2）不返修，只让卡片**自动重跑一次**门禁
  （重跑仍失败则保持现状）——链路不通时重生成一版同样验不了，不该烧返修额度。
- `success === true` → 「应用」可用；**该次运行结果同时缓存为「覆盖后」快照**（供 §6.3 与 D7 使用）。
- 门禁是**前端**动作，不经过 agent、不消耗 agent token。
- **局限（已知并接受）**：门禁只能验「能不能跑」，验不了「有没有偷改语义」。前后对比展示是对用户的部分补偿。

### 6.2 门禁失败分流与自动返修

门禁失败分两类，**判据只看传输层**：

| 类别 | 判据 | 处置 |
|---|---|---|
| 链路失败（transport） | `fetch` 抛异常，或 `res.status >= 400` | 不返修；让卡片**自动重跑一次**门禁 |
| 运行失败（run） | HTTP 200 且 `success !== true`（编译/运行失败） | 返修（上限 2 次） |

- 为什么必须分流：编译/运行失败由后端以 **HTTP 200 + `success:false`** 返回，故「HTTP ≥ 400」可安全用作链路失败判据；
  不区分就会在断网时把 2 次返修额度全烧光（D6）。
- **表中两条判据都可达**（review P3-2 复核：原疑「`httpStatus` 分支不可观察」**不成立**）：
  门禁刻意用**裸 `fetch`**（`OptimizationCard.vue::runGate`，不走 `utils/http.js`——后者在非 2xx 时先抛 `HTTP <status>`）。
  于是三种形态各有归属：非 2xx + JSON body（如 Spring 的 500）→ 走 `res.status` 判据；非 2xx + 非 JSON body
  （nginx 502 错误页）→ `res.json()` 抛异常 → 走 `thrown` 判据；2xx + `success:false` → 运行失败。三者分流一致。
- 返修提问由前端按模板拼（`utils/optimization.js::buildRetryPrompt`），**候选代码必须内联**：
  提问体里的 `code` 是用户编辑器里的代码、不是候选代码（候选只活在 `props.plan.code`），
  上下文（`steps`/`runId`/`files`…）则复用同一次提问的 body。
  模板首行的两个标记（「上一版优化代码没有通过编译/运行校验」「上一版候选代码」）与 coze 引导
  「候选返修」段**互为字面包含**，跨仓守卫见 `tests/test_optimization_guidance.py`。
- 返修结果**必须**含 `kind:"replace"` 块才落地（否则丢弃该次返修、保留失败卡片）：
  自动返修不得销毁用户已看到的证据（错误原文 + 候选代码）。
- 上限与「已自动重跑」闩由 store 持有，不放在卡片里——卡片会因折叠/重挂载丢失局部状态。
  重跑闩按消息加（门禁成功后解闩），否则「重跑 → 失败 → 重跑」会形成 fetch 风暴。
- 用户在返修期间手动提问 → **抢占**（abort 返修）；被抢占的那一次不退还次数（次数按「生成」计）。

### 6.3 应用与撤销（D10）

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
   - `options` 分支：**多选**（`selected` ref + 点行切换，≥2 项时「全选」）；提交时
     `store.askGoalOptimization(已勾选项, 同卡未勾选项, target)`，按钮文案按勾选数变化（0 项禁用）。
   - `replace` 分支：渲染目标/理由 + 门禁状态 + 应用/撤销。
   - 共享的仍是**块通道**与其 apply/undo 原语（`applyAiEdits`/`undoAiEdits`），不是组件。
   - **整文件覆盖的实现 = 一条 `old_string` 为「当前全文」的 edit**，直接复用 `applyAiEdits`：
     `planEdits` 全文唯一匹配 → `ok` → `executeEdits` 覆盖全文，**天然是单个 undo 单元**，`undoToken` 语义原样可用。
     编辑器为空时 `planEdits` 返回 `not-found`，退回 `restoreCode(candidate)` 直接写入。
3. **动作** — `src/stores/player.js`
   - 新增 `applyCandidateRun(snapshot)`：**只**更新 `steps`/`output`/`runId`/`currentStep`/`methodName`/`methodSignature`
     并触发 `requestAnalysis`/`requestControlFlow`；**不得**清 `chatMessages`/`explainHistory`/`activeAiTab`
     （这是与 `applyRunResult` 的关键区别，见前提表）。
   - 新增 `lastRunError` 状态；`runCode`/`runProject` 失败时写入；新增 `clearRunError()`。
   - 新增 `focusChatWithDraft(text)`（预填 + `navigateTo('tutor')` + `chatFocusNonce += 1`）与
     `askGoalOptimization(selected, excluded, target)`（模板拼好后直接调 `store.askQuestion(模板文本)`，复用既有发送入口）。
   - 把 `AiTutorPanel.vue` 的局部 `chatInput` 提升为 `store.chatDraft`（`v-model="store.chatDraft"`），`sendChat` 发送后清空。
4. **报错入口** — `src/components/GlobalStatus.vue`（`ConsoleOutput.vue` **不改**，见 F4 单入口）
   - `lastRunError` 存在时在红色弹窗里渲染入口按钮「让 agent 帮我看看」；点击调
     `store.focusChatWithDraft(buildFixPrompt(...))`（只预填 + 切面板 + 聚焦，**不发送**）。
   - 运行类错误不自动消失；点 `×` 时 `store.clearRunError()`。
   - 早期实现把入口放在控制台面板里，已被 F4 移除（控制台只在「内存状态」pane 可见）。
5. **多文件** — `src/components/MultiFileShell.vue` / `SingleFileShell.vue`
   - 按文件名替换 `multiState.files[i].code` 并切到该文件（`activeFileIndex`）。
   - 两者新增 `provide('restoreCode', ...)`，供卡片在撤销兜底时直接写入编辑器/文件内容。
6. **返修纯逻辑**（2026-09-12 补，见 `docs/plan/2026-09-12-coze-agent-optimization-gate-retry-plan.md`）
   — `src/utils/optimization.js` 新增导出：`MAX_OPT_RETRY`（=2）/ `classifyGateFailure` / `nextRetry` /
   `retryLabel` / `buildRetryPrompt` / `hasUsableReplace`，配 `src/utils/optimization.test.js` 用例。
   本仓**无 DOM 测试环境**，组件逻辑只能手验，故判定一律抽成纯函数。
7. **返修状态与接线**（同上）
   - `src/stores/player.js`：抽 `buildChatBody(question)` / `_runChat({question, onChunk, onStage, onError, signal})`
     （`askQuestion` 对外行为一字不变）；新增 `optRepair` / `optAbortController` / `optRegateNonce` 状态与
     `requestOptimizationRetry(msgIndex, {...})` / `notifyGateOk(msgIndex)` 动作。
   - `src/components/OptimizationCard.vue`：新增 `msgIndex` / `rev` / `repair` 三个 prop；门禁失败按 §6.2 分流上报；
     返修态文案优先于失败态；`watch(() => [rev, optRegateNonce])` 重跑门禁（**不** watch `props.plan`——对象身份每次重算都变）。
   - `src/components/AiTutorPanel.vue`：把 `:msg-index` / `:rev` / `:repair` 传给卡片
     （`rev` 与 `repair` 直接取自 `store.chatMessages[i]` / `store.optRepair`，不经 `parsedMessages`）。

### 7.2 coze（`javatutor-coze`）

1. **`prompting/panels.py` 或新 `prompting/optimization.py`** — 新增 `render_optimization_guidance()`：
   - `【编辑建议】` 的 `kind` 闭集（`patch`/`options`/`replace`）与各自形态；
   - **两步式**：第一轮只给 `options`（2–3 项、闭集 goal），**不得**在同一轮给代码；用户选定目标后第二轮才给 `replace`；
   - `goal` 闭集表（含 `comprehensive`，方案卡不得产出）；`replace` 的 `code` 必须是**完整可编译**的整份文件（不得占位省略）；
   - **第二步的方向硬约束**（F2/F3）：只做提问里列出的方向、未列出的不得顺手改、≥2 方向记 `comprehensive` 并逐项写 `rationale`；
   - 与「报错修正」的关系：报错场景同理——先给修正方案选项，选定后给整份代码；
   - **候选返修段**（2026-09-12 补，见 §6.2）：认出「上一版优化代码没有通过编译/运行校验」类提问，
     直接（不再给方案卡）重新交付一版 `kind:"replace"`，`goal`/`target` 与上一版保持一致，
     修正范围仅限让代码能编译/运行通过；无法在不改方向的前提下修好时只给正文、不给块；
   - `target` 规则（多文件必填）。
2. **`main_agent.py`** — `_main_system_prompt()` 注入 `render_optimization_guidance()`（走 SystemMessage，不被 compress 截断）。
3. **`prompts.py`**
   - `SYSTEM_PROMPT_CRITIC`：评审正文时**忽略** `【编辑建议】` 的结构化块；不得因 `kind:"options"`/`"replace"` 判失败。
   - `SYSTEM_PROMPT_REVISE`：修订时**保留**结构化块（除非评审明确标记非法）。
4. **`prompting/main_fewshots.py`** — 优化样例：
   - 第 1 轮：问「帮我优化一下」→ 只给 `options` 方案卡（无代码）；
   - 第 2 轮（单方向）：提问为 F2 模板（含「不要顺带做其他方向的改动（例如：…）」）→ 给 `replace` 整份代码 + `rationale`，`goal` = 该方向；
   - 第 2 轮（多方向）：提问逐条列出 ①② → `replace` 的 `goal: "comprehensive"`，`rationale` 分别说明两方向。
5. **守卫测试** — `tests/`：引导块含 goal 闭集、两步式约束、**方向硬约束**；few-shot 样本 JSON 合法、
   `options` 的 goal 全部落在闭集内（且不含 `comprehensive`）、第二步样例示范白名单/黑名单、存在多方向样例；
   返修段为 replace 专用（不得回退到两步式第一步），且与前端 `buildRetryPrompt` 的两个标记**互为字面包含**
   （跨仓读前端 `utils/optimization.js` 比对，见 `tests/test_optimization_guidance.py`）。

### 7.3 后端（`javatutor/backend`）

- **本 spec 无需改动**（报错走预填 → `user_question`；门禁复用既有 `/api/run`、`/api/run/project`）。
- 记录在案（**不在本次范围**）：`CozeAIController` 的 `compileError` 恒为 `null`，若后续要「agent 原生感知编译错误」需另行打通。

## 8. 验收标准

1. 「帮我优化一下」→ 第 1 轮回答**附方案卡**（2–3 个闭集目标选项），**正文与块内均无优化代码**。
2. 在方案卡上勾选（可多选）后提交 → 前端发出模板提问（可在消息列表看到，**以 `【优化第二步】` 起头**，含「只做…」+「不要顺带做其他方向的改动（例如：…）」），
   第 2 轮回答附 `kind:"replace"` 块，且**代码里只含所选方向的改动**（未选方向即便明显可优化也不得顺手改）；
   **第 2 轮不得再出 `options` 方案卡**（重复出卡 = 用户反复选择的死循环）。
3. **门禁**：候选跑不通 → 卡片显示错误、「应用」禁用；跑通 → 「应用」可用。
   失败后若该卡挂在**最新一条 assistant 消息**上，前端**自动返修**（最多 2 次额外生成、原地替换卡片、自动重跑门禁）；
   耗尽 / 非最新 / 传输失败 → 回到上面的现状行为（详见 §6.2）。
4. 点「应用」→ 编辑器被覆盖为候选代码（**一个撤销单元**），右侧面板刷新为候选运行结果，前后对比可见。
5. **撤销**：未编辑时 → 精确回滚；已编辑时 → 提示「将丢弃此后的编辑」并快照还原。
6. **报错**：运行失败后红色弹窗**常驻**（10 秒后仍在），含「让 agent 帮我看看」；
   停留任意 tab 点击 → 切到 agent 面板、输入框已预填、光标在末尾、**未发送**；点 `×` → 弹窗与入口一并消失；
   下一次成功运行 → 弹窗自动消失。
7. **多文件**：`target` 指定文件被覆盖；`target` 不存在 → 不覆盖、禁用应用、明确提示。
8. **兼容**：无 `kind`/`kind:"patch"` 行为与现状**完全一致**；`kind` 非法、`code` 空、`options` 空 → 块按正文展示，不崩。
9. `【编辑建议】`/`【视角导航】` 仍不会以裸 JSON 出现在正文（沿用 2026-09-09 的剥离逻辑）。

## 9. 测试

- **前端**：`editSuggestion.test.js`（`options`/`replace` 解析、`usable` 回退、`patch` 回归）、卡片三分支渲染、
  `applyCandidateRun` 不清会话、整文件覆盖的 apply/undo（含 token 失效回退快照）、多文件 target 替换、
  `optimization.test.js`（返修纯逻辑：`classifyGateFailure` / `nextRetry` / `buildRetryPrompt` / `hasUsableReplace`）、
  `stores/__tests__/player-optimization.test.js`（返修状态机：链路失败闩的终止性与解闩、重跑通知量**按消息**、
  上限耗尽后停止、飞行中不重入、被用户提问抢占的那一次不退还额度）、`npm test` 全绿。
- **coze**：`uv run pytest -q` 全量；新增引导/few-shot 守卫（goal 闭集、两步式、`code` 完整性要求、
  **第二步标记 `STEP2_MARKER` 与前端 `editSuggestion.js` 的 `export const STEP2_MARKER` 互为跨仓握手**、
  **第二步 few-shot 提问必须以该标记起头**、旧判别依据那条冲突条目已消失、
  候选返修段与前端 `buildRetryPrompt` 的两个标记**互为字面包含** → `tests/test_optimization_guidance.py`）；
  运行模式守卫（payload → state → packet → facts 块 → 引导 → 本体 → `tests/test_run_mode_context.py`）。
- **手验**：`npm run dev` 跑验收 1–8（含报错预填与多文件）；逐条清单见两份 2026-09-12 devlog。

## 10. 风险 / 待确认

- **门禁验不了语义偷改**（仅「能跑」）：已接受；用前后对比（输出/步数）部分补偿。
- **长文件下整份代码的 JSON 转义失败率**（D11）：失败表现是「没有卡片」，不会崩；若线上失败率高，再补「围栏回退解析」。
- **`applyRunResult` 会话重置陷阱**（前提表）：必须新增独立变体，否则应用一次优化会清空整个聊天记录。
- **快照撤销会丢弃用户此后的编辑**：需 UI 明示并确认。
- **critic/revise 可能不认新块**：prompt 与测试都要覆盖；否则出现「方案卡被修订掉」。
  **2026-09-14 更新**：已确认这是真实故障（不止是风险）——第二步 `replace` 的整份代码被评审以「格式/引用不完整」
  反复打回。修法见 `docs/spec/2026-08-10-coze-agent-deepening-design.md` D-02/D-10（评审对 `replace` 的否决权限于实质问题）。
- **`lastRunError` 的生命周期**（何时清）：**已定**——下次成功运行（`runCode`/`runProject` 开头置 `store.error = null`）或用户点 `×`（`clearRunError()`）时清。
- **方向约束是「提示层」而非「校验层」**：`comprehensive` 不校验代码真的只改了所列方向，只是把「多方向」记进 `replace.goal` 供展示与统计；
  真要强校验只能靠人工/评测（可观测性妥协，已接受）。
- **黑名单范围可控**：只列**同一张方案卡**的未勾选项。若日后出现「未选项里混入荒谬条目（如把明显 bug 归入某方向）」，再考虑只列 `label` 不列 `detail`。
- **HITL 对接点**：`option` 结构 `{goal,label,detail}` + 前端 prompt 模板需保持稳定，供 harness 以「用户选项」直接复用。

## 11. 文档登记

- 接口契约：`docs/spec/2026-08-10-coze-agent-interface.md` 增「编辑建议块扩展（kind）」（§2.2）
  与「运行模式字段（可选，仅 chat 路径）」（§1.1）。
- 本 spec：`docs/spec/2026-09-10-coze-agent-code-optimization.md`。
- 若图结构/节点输入输出有变，同步 `docs/agent-collaboration-guide.md`（2026-09-12 已同步输入侧的可选 `run_mode` / `test_case_count`）。
- 实现记录：
  - `docs/devlog/2026-09-10-coze-agent-code-optimization.md` 与本 spec 的 review（R1–R5）。
  - `docs/devlog/2026-08-30-multifile-whole-project.md`（多文件通道，`replace` 的 `target` 依赖它）。
- 2026-09-12 两件后续（同批联调，均由本 spec 派生）：
  - **门禁失败自动返修** — 计划 `docs/plan/2026-09-12-coze-agent-optimization-gate-retry-plan.md`
    / 记录 `docs/devlog/2026-09-12-coze-agent-optimization-gate-retry.md`（本 spec 新增 §6.2，同步 §6.1/§7.1/§7.2）。
  - **测试模式上下文** — 计划 `docs/plan/2026-09-12-coze-agent-test-mode-context-fix-plan.md`
    / 记录 `docs/devlog/2026-09-12-coze-agent-test-mode-context.md`（同步本 spec §5 报错入口的预填文本）。
  - 两件合并 review：`docs/reviews/2026-09-12-coze-agent-optimization-retry-and-test-mode-review.md`。
- 2026-09-14（联调修复，同批）：
  - **第二步判别器改显式标记** — 计划 `docs/plan/2026-09-14-fix-concept-intent-and-optimization-loop-plan.md`
    （D1–D3：标记 + 概念意图分流 + few-shot 补概念样本）。本 spec 同步 §4.2（评审门）/ §4.3（判别器）/ §4.4（模板）/
    §8（验收 2）/ §9（跨仓握手断言）/ §10（风险行）。
  - **评审-修订子系统优化** — 设计 `docs/spec/2026-09-14-critic-revise-optimization-design.md`
    / 计划 `docs/plan/2026-09-14-critic-revise-optimization-plan.md`（`replace` 的评审否决权收窄，即上条的评审侧实现）。
