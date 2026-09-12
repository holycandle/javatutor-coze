# 执行计划：优化候选门禁失败后自动返修（功能）

> 依据：2026-09-12 联调反馈「优化代码若错误则直接报错，更好的做法是不是重复生成直到正确」+ 同日 `/grilling` 收敛（§1 即决策记录）。
> **跨两仓**：前端 `javatutor/frontend` + coze `javatutor-coze`。后端**无需改动**。
> 关联：`docs/spec/2026-09-10-coze-agent-code-optimization.md`（本计划**部分改写**其 §6.1、§7.1，见 Task 12）；
> `docs/plan/2026-09-12-coze-agent-test-mode-context-fix-plan.md`（同批联调的姊妹件；两件共用 `stores/player.js` 的 `_runChat`/`buildChatBody` 抽取，见 §0 依赖说明）。
> 前置实现：`docs/devlog/2026-09-10-coze-agent-code-optimization.md`；时间线见 `docs/devlog/2026-09-10-coze-agent-run-timeline.md`。

## 0. 全局约束（务必遵守）

- **不做任何 git 操作**（不 `git add`/`commit`/`push`/`stash`/`checkout`/`branch`）。读 `git status`/`diff` 可以。
- 前端**不触碰** `javatutor/frontend/src/backup-20260807/`（备份副本）。
- 基线（改动前先跑一遍确认）：前端 `npm test` = **29 文件 / 351 用例**；coze `uv run pytest -q` = **311 通过**。（本机实测 2026-09-12。）
- **向后兼容是硬要求**：`kind` 缺失 / `kind:"patch"` / `kind:"options"` 三条路径**零行为变化**；`replace` 块的**块形态（JSON schema）不变**——本计划只改「失败之后」，不改「失败之前的任何一步」。
- **不新增消息、不新增记录点**：返修只重写**最后一条 assistant 消息的 `text`**，`chatMessages.length` 不变、`timeline` 不变。这是时间线 `chatPoint.chatIndex` 语义（下标即折叠边界）的前提，不得破坏。
- 新增纯函数一律放 `utils/` 并配 vitest 用例（本仓**无 DOM 测试环境**，组件逻辑只能手验——请把可抽的判定都抽出来）。
- 保持现有命名/风格（前端 ESM + `defineStore`；coze 中文 docstring、`_` 私有函数、守卫测试放 `tests/`）。
- **不做**：不引入手动「再试一次」按钮；不重试 `patch`/`options` 卡；不在返修里改 `goal`/`target`；不新增 agent 工具。

### 0.1 依赖与执行顺序

- 本计划 Task 1 从 `askQuestion` 抽出 `buildChatBody()` / `_runChat({ question, sink })`。姊妹件（测试模式修复）的 Task 1 在同一函数上**追加两个字段**。
- **先执行者落抽取，后执行者按已抽取形态接续**——两件的这一处不是冲突改动，但必须按此顺序落地，否则后一件会基于旧函数体重写。

## 1. 已收敛的决策

| # | 决策 | 说明 |
|---|---|---|
| **F1** | 门禁失败后**前端自动重生成**候选代码，**最多 2 次** | 次数 = **额外生成次数**，即最多 3 版候选（原有 1 + 返修 2）。耗尽后回到现状：显示错误原文 + 「应用」禁用。 |
| **F2** | 新候选**原地替换旧卡片**，不新增气泡 | 重写该条 assistant 消息的 `text`（因此卡片是「同一张、代码变了」），对话里只留最终一版。 |
| **F3** | 只在**最新一条 assistant 消息**上自动返修 | 旧卡的失败**不**触发返修（理由见 §0.1 D9/D10）。旧卡行为 = 现状。 |
| **F4** | 只对**运行失败**返修，**传输失败**不返修 | fetch 抛异常 / HTTP ≥ 400 = 链路问题，重生成一版同样验不了 → 只重跑门禁，不烧返修次数。 |
| **F5** | 返修未产出可用 `replace` 块时**丢弃该次返修结果**，保留失败卡片 | 「自动返修」若拿不到候选，不得销毁用户已看到的证据（错误原文 + 候选代码）。 |

---

## 2. 改动清单

| # | 仓 | 文件 | 改动 |
|---|---|---|---|
| 1 | 前端 | `javatutor/frontend/src/utils/optimization.js` | 新增 `MAX_OPT_RETRY` / `classifyGateFailure` / `nextRetry` / `buildRetryPrompt` / `retryLabel` |
| 2 | 前端 | `javatutor/frontend/src/utils/optimization.test.js` | 上述纯函数用例（**测试先行**） |
| 3 | 前端 | `javatutor/frontend/src/stores/player.js` | 抽 `buildChatBody` / `_runChat`；新增 `optRepair` 状态 + `requestOptimizationRetry` + 消息字段 `optRev` |
| 4 | 前端 | `javatutor/frontend/src/components/OptimizationCard.vue` | 新增 `msgIndex` / `rev` / `repair` 三个 prop；门禁失败分流；返修态文案；`rev` 变更重跑门禁 |
| 5 | 前端 | `javatutor/frontend/src/components/AiTutorPanel.vue` | 传 `:msg-index` / `:rev` / `:repair` |
| 6 | coze | `src/graphs/javatutor/prompting/optimization.py` | 新增「候选返修」引导段 |
| 7 | coze | `tests/test_optimization_guidance.py` | 守卫：返修引导存在、与前端模板关键短语对齐 |
| 8 | 两仓 | `docs/devlog/2026-09-12-coze-agent-optimization-gate-retry.md` | **新建**实施记录 |
| 9 | coze | `docs/spec/2026-09-10-coze-agent-code-optimization.md` | 同步 §6.1（门禁失败分支）与 §7.1（前端清单） |

### 0.1 诊断（为什么这么改；已核实，勿再重开）

**问题「门禁失败即死路」的成因：**

| # | 事实 | 位置 |
|---|---|---|
| D1 | 门禁失败只做两件事：`gate='fail'` + `gateError=<原文>`；`canApply` 要求 `gate==='ok'`，于是「应用」永久禁用。**没有任何重生成路径。** | `OptimizationCard.vue:129-134`、`:150-172`、`:47-48`、`:51` |
| D2 | 门禁是**纯前端**动作，不经过 agent（spec §6.1 明文），所以「再生成一版」必须由前端**主动发起一次提问**。 | `docs/spec/2026-09-10-coze-agent-code-optimization.md` §6.1 |
| D3 | 提问体里 `code: this.code` 是**用户当前编辑器里的代码**，**不是**候选代码；候选只存在于 `props.plan.code`。故返修提问必须把候选代码**内联进问题文本**，不能指望 `source_code`。 | `player.js:429-440` |
| D4 | 卡片的 `props.plan` 来自 `parsedMessages` computed，**每次重算都产生新对象**；`watch(() => props.plan)` 会在流式期间被反复触发。可靠信号是**原始类型**（`plan.code`）或**显式计数器**。 | `AiTutorPanel.vue` `parsedMessages` |
| D5 | 卡片折叠必须 `v-show`、消息 `:key="i"`：`v-if` 卸载卡片会**重跑门禁**并丢 `applied`/`undoToken`（既有决策 D7）。反过来，**卸载再挂载 = 门禁自动重跑**，这可以被利用，但不能依赖（返修期间用户会看不到卡片）。 | `AiTutorPanel.vue` 注释；`OptimizationCard.vue:onMounted` |
| D6 | `runGate()` 的 `catch` 与「响应 `success:false`」**共用同一个 `gate='fail'`**，无法区分「代码跑不过」与「网络/服务不可用」。不区分就会在断网时把 2 次返修额度全烧光。 | `OptimizationCard.vue:169-172` |
| D7 | `readGateResponse` 只在 `code===200 || success` 时判 ok；编译/运行失败由后端以 **HTTP 200 + `success:false`** 返回，故「HTTP ≥ 400」可安全用作传输失败判据。 | `utils/optimization.js::readGateResponse` |
| D8 | 返修必须复用提问体的上下文（`steps` / `runId` / `files` / 测试模式…），否则 agent 看到的是缺上下文的孤岛提问。 | `player.js:420-445` |
| D9 | 时间线记录点记的是 `chatIndex = chatMessages.length`（**下标即折叠边界**，其后消息被折叠），`revertToCheckpoint` 按下标截断。 | `player.js:277-286`、`:328` |
| D10 | 由此：重写**最后一条**消息落在「最新记录点之后」的当前段内，对时间线无副作用；重写更早的消息则是在**改写已被记录点覆盖的历史**。故必须限定 F3。 | 同上 |

结论：**「失败 → 自动再生成一次提问」必须由 store 承载**（卡片会被卸载、次数上限必须抗重挂载），
**且次数上限只能由 store 持有**；卡片只负责「发现失败 → 上报」。

---

# Phase A — 前端纯逻辑（测试先行）

## Task 1：`utils/optimization.js` 新增纯函数

在文件末尾追加（保持现有导出不动）：

```js
/** 门禁失败后的自动返修次数上限（**额外**生成次数，故最多 3 版候选）。 */
export const MAX_OPT_RETRY = 2

/**
 * 区分门禁失败的两种性质（D6）。
 * @param {{ thrown?: boolean, httpStatus?: number }} s
 *   thrown=true  → fetch 抛异常（断网/服务未起）；httpStatus ≥ 400 → 服务端链路失败
 * @returns {'transport'|'run'} 只有 'run' 才值得让 agent 重生成
 */
export function classifyGateFailure({ thrown = false, httpStatus = 0 } = {}) {
  if (thrown) return 'transport'
  return httpStatus >= 400 ? 'transport' : 'run'
}

/**
 * 返修决策（F1/F3/F4/F5 的唯一判定点，纯函数）。
 * @param {{ attempt: number, kind: 'run'|'transport', applied: boolean,
 *           targetBlocked: boolean, isLatest: boolean, hasCode: boolean }} s
 * @returns {{ action: 'retry'|'regate'|'stop', attempt: number, max: number }}
 *   retry  = 发起返修提问（attempt 为**本次**序号，从 1 起）
 *   regate = 只重跑门禁（传输失败）
 *   stop   = 保持现状（显示错误 + 禁用应用）
 */
export function nextRetry({ attempt, kind, applied, targetBlocked, isLatest, hasCode }) {
  const stop = { action: 'stop', attempt, max: MAX_OPT_RETRY }
  if (applied || targetBlocked || !isLatest || !hasCode) return stop
  if (kind === 'transport') return { action: 'regate', attempt, max: MAX_OPT_RETRY }
  if (attempt >= MAX_OPT_RETRY) return stop
  return { action: 'retry', attempt: attempt + 1, max: MAX_OPT_RETRY }
}

/** 返修中的卡片文案。 */
export function retryLabel(attempt, max = MAX_OPT_RETRY) {
  return `校验未通过，正在自动修正 ${attempt}/${max}…`
}

/** 返修提问（D3：候选代码必须内联；D8：目标与方向必须写明，避免 agent 改错方向）。 */
export function buildRetryPrompt({ plan = {}, gateError = '', goalLabel = '', attempt, max = MAX_OPT_RETRY }) {
  const target = plan.target || '（当前文件）'
  return [
    `上一版优化代码没有通过编译/运行校验（第 ${attempt}/${max} 次自动修正），请修正后重新给出完整代码。`,
    '',
    `[目标] 方向：${goalLabel || plan.goal || '（未指明）'}；目标文件：${target}`,
    '[校验错误]',
    gateError || '（未提供）',
    '[上一版候选代码]',
    '```java',
    plan.code || '',
    '```',
    '',
    '要求：只输出一版修正后的完整代码（同一个【编辑建议】块，kind:"replace"，goal 与 target 保持不变），',
    '必须能编译并正常运行；不要只解释错误，也不要改动优化方向，不要新增其它块。',
  ].join('\n')
}
```

### 测试（`optimization.test.js`，**先写**）

覆盖：`classifyGateFailure`（thrown / 500 / 200+success:false → 'run'）；
`nextRetry` 全分支（正常第 1 次 → `retry/1`；第 2 次 → `retry/2`；`attempt=2` → `stop`；
`applied` / `targetBlocked` / `!isLatest` / `!hasCode` → `stop`；`kind='transport'` → `regate` 且**不**递增）；
`retryLabel` 文案；`buildRetryPrompt` 含错误原文、候选全文、goal、target，且 `plan.code` 为空时不抛异常。

---

# Phase B — 前端 store 与组件

## Task 2：`stores/player.js` — 抽 `buildChatBody` / `_runChat`

**目标**：让「发一次提问 + 流式收文本」可复用且**可指定落点**，不改变 `askQuestion` 对外行为。

- 新增 `buildChatBody(question)`：把 `askQuestion` 里 `JSON.stringify({...})` 的内容整段搬进来（`player.js:429-445`），返回 body 对象。
- 新增 `async _runChat({ question, onChunk, signal })`：负责 `http('/api/ai/chat')` + SSE 解析 + 逐事件回调 `onChunk(text)` / `onStage` / `onError`。把现有 `:446-500` 的解析循环整体搬入。
- `askQuestion(question)` 改为：
  - 保持首部（abort 旧的 `explainAbortController`、trim 校验、`isExplaining=true`、push 两条消息、`assistantIdx`）与尾部（`isExplaining=false`、错误处理）**原样**；
  - 中间改为 `await this._runChat({ question: q, signal: this.explainAbortController.signal, onChunk: (t) => { this.chatMessages[assistantIdx].text += t } , onError: ..., onStage: ... })`。
- **回归红线**：`askQuestion` 的对外可观测行为（消息条数、`isExplaining` 时序、`explainError` / `explainStage` 写入、abort 语义）必须一字不变。手验：正常问答、中途 abort、上游 `error` 事件三条路径。

## Task 3：`stores/player.js` — `optRepair` 与 `requestOptimizationRetry`

新增 state：

```js
optRepair: null,   // null | { msgIndex: number, attempt: number, max: number }
```

新增 action（伪码，判定全部走 `nextRetry`）：

```js
/**
 * 优化卡门禁失败上报 → 决定是否自动返修（F1–F5；上限由 store 持有，抗卡片重挂载）。
 * 只重写**最后一条 assistant 消息**的 text，不新增消息、不新增记录点（§0 硬约束）。
 * applied / targetBlocked 由卡片如实传入——二者本可「按构造恒为 false」，但**不得**在 store 里
 * 写死：判定必须全部走 nextRetry，否则纯函数的守卫就成了死代码（何况 gate 在 `rev` 变更时会重跑）。
 */
async requestOptimizationRetry(msgIndex, { gateError, kind, plan, goalLabel, applied, targetBlocked }) {
  const idx = Number(msgIndex)
  const msg = this.chatMessages[idx]
  const isLatest = idx === this.chatMessages.length - 1 && !!msg && msg.role === 'assistant'
  const hasCode = !!(plan && plan.code)
  const attempt = (msg && msg.optAttempt) || 0
  if (this.optRepair) return                       // 已有返修在飞 → 不重入
  const d = nextRetry({ attempt, kind, applied, targetBlocked, isLatest, hasCode })
  if (d.action === 'regate') { this.optRegateNonce += 1; return }   // 传输失败：让卡片重跑门禁
  if (d.action === 'stop') return
  msg.optAttempt = d.attempt
  this.optRepair = { msgIndex: idx, attempt: d.attempt, max: d.max }
  try {
    let buf = ''
    await this._runChat({
      question: buildRetryPrompt({ plan, gateError, goalLabel, attempt: d.attempt, max: d.max }),
      signal: (this.optAbortController = new AbortController()).signal,
      onChunk: (t) => { buf += t },
      onStage: () => {},
      onError: (m) => { this.explainError = m },
    })
    if (!hasUsableReplace(buf)) return             // F5：拿不到候选 → 保留失败卡片
    msg.text = buf                                  // F2：原地替换
    msg.optRev = (msg.optRev || 0) + 1              // 通知卡片重跑门禁
  } catch (e) {
    /* 保持失败卡片，不重试 */
  } finally {
    this.optRepair = null
    this.optAbortController = null
  }
}
```

- `hasUsableReplace(text)` 用**既有解析器**判定（`utils/editSuggestion.js::parseAssistantMessage(text).plan` 存在且 `kind === 'replace'`），不另写一套块解析。
- `askQuestion` 首部追加 `this.optAbortController?.abort()`：用户手动提问**抢占**自动返修（语义：用户优先）。被抢占时 `optAttempt` **不退还**（次数按「生成」计数，见 §1 F1），须在 devlog 写明。
- 新增 `optRegateNonce: 0`（见 Task 4 的 `regate` 通路）。

## Task 4：`OptimizationCard.vue` — 三个新 prop + 失败分流

- props 追加：`msgIndex: { type: Number, default: -1 }`、`rev: { type: Number, default: 0 }`、`repair: { type: Object, default: null }`。
- `runGate()` 改造（D6/F4）：catch 分支与 `res.ok === false` 分支分别调用
  `store.requestOptimizationRetry(props.msgIndex, { gateError, kind: classifyGateFailure({...}), plan: props.plan, goalLabel: goalLabel.value, applied: applied.value, targetBlocked: targetBlocked.value })`；
  OK 分支与 `success:false` 分支维持现状（写 `gate`/`gateError`/`gateSnapshot`）。
  - `thrown: true` 来自 catch；`httpStatus: res.status` 来自响应。
  - **顺序**：先按现状写 `gate='fail'` + `gateError`，再上报 store（保证上报失败也不影响画面）。
- 返修态渲染：模板 `gate === 'fail'` 那一行改为

  ```html
  <div v-else-if="repair" class="oc-gate">{{ retryLabel(repair.attempt, repair.max) }}</div>
  <div v-else-if="gate === 'fail'" class="oc-error">校验未通过：{{ gateError }}</div>
  ```

  并把 `gate` 的显示优先级调到 `repair` 之后（`repair` 非空时显示返修态，不显示错误原文——错误原文此刻已在上一条返修提问里）。
- 变更侦听（D4/D5）：新增

  ```js
  watch(() => [props.rev, store.optRegateNonce], () => {
    if (isOptions.value || targetBlocked.value || applied.value || props.repair) return
    runGate()
  })
  ```

  **不 watch `props.plan`**（对象身份每次重算都变）。`onMounted` 的既有逻辑保留（首次进入照旧跑门禁）。
- `apply()` / `undo()` / 快照语义**一行不改**；返修只发生在 `applied === false`（`nextRetry` 已用 `applied` 兜底）。

## Task 5：`AiTutorPanel.vue` — 传参

```html
<OptimizationCard
  v-if="parsedMessages[i].plan && (i !== store.chatMessages.length - 1 || !store.isExplaining)"
  :plan="parsedMessages[i].plan"
  :msg-index="i"
  :rev="store.chatMessages[i].optRev || 0"
  :repair="store.optRepair && store.optRepair.msgIndex === i ? store.optRepair : null"
/>
```

- `:rev` / `:repair` 直接从 `store.chatMessages[i]` / `store.optRepair` 取（**不**经 `parsedMessages`），避免 computed 身份抖动。
- `v-show` / `:key="i"` 的既有约束**不动**。

---

# Phase C — coze：返修引导与守卫

## Task 6：`prompting/optimization.py` 新增「候选返修」段

在 `render_optimization_guidance()` 返回文本的**第二步之后**追加（与前端 `buildRetryPrompt` 的短语对齐）：

```
**候选返修（上一版代码没过校验时）**
用户提问里带「上一版优化代码没有通过编译/运行校验」并给出【校验错误】与【上一版候选代码】时，
**不要只解释错误、也不要再给方案卡**：直接重新交付一版 `kind:"replace"` 块。
- `goal` 与 `target` 必须与上一版**保持一致**（返修不是重新选方向的机会）。
- 修正范围**仅限**让代码能编译/运行通过；不得顺手改变优化方向或做其它改动。
- `code` 仍是完整、可独立编译的该文件全文。
- 若判断错误无法在不改方向的前提下修好，则只给正文说明原因，**不要**给 replace 块。
```

> 最后一条对应前端 F5：拿不到 `replace` 块时前端会保留失败卡片，用户仍能看到错误原文。

## Task 7：`tests/test_optimization_guidance.py` 守卫

- 断言引导文本含「候选返修」「kind:\"replace\"」「goal」「target」「保持一致」等关键短语。
- 断言该段**未**要求先给 `options`（返修路径不得回退到两步式的第一步）。
- 断言与前端 `buildRetryPrompt` 的关键标记（「上一版优化代码没有通过编译/运行校验」「上一版候选代码」）**互为字面包含**：coze 侧测试硬编码这两个短语，前端 `optimization.test.js` 也断言模板含它们——一端改字必须另一端红。

---

# Phase D — 验证

## Task 8：跑测试 + devlog

- 前端：`cd javatutor/frontend && npm test`（期望 351 + 新增用例数，0 失败）。
- coze：`cd javatutor-coze && uv run pytest tests/ -q`（期望 311 + 新增，0 失败）。
- devlog：`docs/devlog/2026-09-12-coze-agent-optimization-gate-retry.md`（改动清单、决策 F1–F5、偏差、测试数、已知局限、手验清单）。

## Task 9：文档同步（**必须**，否则 spec 与实现再次脱节）

- `docs/spec/2026-09-10-coze-agent-code-optimization.md`
  - **§6.1 门禁**：把「`success !== true` → 显示错误原文 + 「应用」禁用」改写为
    「`success !== true` → 显示错误原文；**若该卡是最新一条 assistant 消息**，自动发起返修提问（上限 2 次，
    见 `docs/plan/2026-09-12-coze-agent-optimization-gate-retry-plan.md`）；耗尽/非最新/传输失败 → 保持禁用」，
    并补一句「返修不新增消息、不新增记录点（重写该条 `text`）」。
  - **§7.1 前端清单**：新增 `utils/optimization.js` 的 5 个纯函数、`OptimizationCard` 的 3 个 prop、store 的 `optRepair`。
- `docs/spec/2026-08-10-coze-agent-interface.md`：**无需改动**（本件不动 coze 请求/响应契约）。

## 手验清单（`npm run dev`；coze 侧需**重新发布 agent**）

1. 提问「优化这段代码」→ 方案卡 → 勾 1 项提交 → 得到 `replace` 卡。
2. **构造一次失败**：让 agent 产出一版有编译错的候选（例如临时把引导改成「务必留一个未初始化变量」或直接手改卡片的 `plan.code` 为 `int x; x+1;` 后再刷新）。
   - 卡片应显示「校验未通过，正在自动修正 1/2…」→ 随后卡片原地变成新代码并显示「校验通过」，「应用」可用。
   - **对话里不新增气泡**；输入框可继续用；返修期间发新提问 → 返修被抢占、卡片保留失败态。
3. **耗尽**：连续两版都错 → 第 3 版仍错 → 显示错误原文 + 「应用」禁用（现状行为）。
4. **传输失败**：停掉后端 → 卡片失败 → **不**发起返修提问（`chatMessages.length` 不变）→ 恢复后端后重跑门禁成功。
5. **旧卡不返修**：用第 1 步的失败卡再跑一次代码，让它变成非最新消息 → 不再自动返修。
6. **回归**：`patch` 卡（局部修改）与方案卡行为一字未变；应用/撤销/时间线记录点全部照旧。

## 遗留 / 注意事项

- **次数语义**：上限按「生成次数」计。被用户提问抢占的那一次**不退还**。若线上反馈额度太紧，再考虑「按结果计次」——需先有数据。
- **成本**：每张失败卡最多多消耗 2 次完整 agent 往返（含 RAG）。属有意代价。
- **不覆盖**：本件不解决「门禁能跑但偷改语义」（spec §6.1 已列为已知局限），也不给用户手动触发返修的按钮。
- **姊妹件**：`docs/plan/2026-09-12-coze-agent-test-mode-context-fix-plan.md`（测试模式误诊）与本件同批联调，
  两件在 `stores/player.js` 的 `buildChatBody` 上有顺序依赖（§0.1）。
