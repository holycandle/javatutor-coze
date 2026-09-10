# 功能计划：对话时间线（运行不清空对话 + 记录点回退）

> 依据：2026-09-10 联调提出「重新执行代码会清空对话，不利于回顾，参考 Claude 的对话设计」+ 同日 `/grilling` 收敛（§1 为决策记录）。
> **纯前端功能**（`javatutor/frontend`）：coze 与后端**均无需改动**（理由见 §0.1 D1/D2）。
> 关联：`docs/spec/2026-09-10-coze-agent-code-optimization.md`（优化卡的 apply/undo 通道会被复用，见 Task 6）；`docs/devlog/2026-09-10-coze-agent-code-optimization.md`（前置实现）。

## 0. 全局约束（务必遵守）

- **不做任何 git 操作**（不 `git add`/`commit`/`push`/`stash`/`checkout`/`branch`）。读 `git status`/`git diff` 可以。
- 前端**不触碰** `javatutor/frontend/src/backup-20260807/`（备份副本，含同名 `AiTutorPanel.vue`）。
- 基线（改动前先跑一遍确认）：前端 `npx vitest run` = **25 文件 / 291 用例**；coze `uv run pytest -q` = **226 通过**（本计划不应改动 coze 任何文件）。
- 本仓**无 DOM 测试环境**：所有可抽的判定（摘要文案、折叠边界、索引收敛）一律抽成 `utils/timeline.js` 的纯函数并配 vitest；组件行为靠手验清单。
- **不要顺手改 `sessionId` / 记忆策略 / 后端**（见 §0.1 D2）。

### 0.1 关键前提（已核实，勿再重开）

| # | 事实 | 位置 | 影响 |
|---|---|---|---|
| **D1** | `/api/ai/chat` 的请求体**不含任何对话历史**（只发 `code`/`runId`/`step`/`steps`/`variables._explainTopic`/`files`/`entryFile`）。 | `CozeAIController.chat`、`player.js:298-313` | **「不清空对话」是纯 UI 行为**：不增加 agent token、不改变 agent 行为。本功能的收益是给人的（回顾/时间线），不是给模型的。 |
| **D2** | `sessionId = Integer.toHexString(request.getCode().hashCode())`，即**代码哈希**。 | `CozeAIController.chat` | agent 侧记忆已按代码版本分区；代码一变就换区。**不要**为了「保留上下文」去动它。 |
| **D3** | `runCode`/`runProject` 开场会清空 `chatMessages`，同时清 `explainError`/`analysisData`/`svgText` 并把 `activeAiTab` 复位为 `explain`。 | `player.js:96-115`、`player.js:138-155` | 只**去掉** `chatMessages` 的清空；其余保留（它们描述「当前代码」的分析结果，代码变了本就该失效）。 |
| **D4** | `explainHistory` 是**死状态**：全仓只有写入与清空，**没有任何读取点**（读取点只在 `backup-20260807/App.vue`）。 | `grep -rn explainHistory` | 清理时不要被它误导；删除它需同步 `player-optimization.test.js`（该用例断言它被保留），列为**可选**清理。 |
| **D5** | 编辑器的代码恢复通道目前只有**单文件**语义：`restoreCode(code)`（单文件）/ `restoreCode(code, target)`（多文件里的**一个**文件）。 | `SingleFileShell.vue`、`MultiFileShell.vue` | 整项目回退**缺通道** → 本计划新增统一通道 `restoreSource(cp)`（Task 5）。 |
| **D6** | 多文件切换文件的 watcher 会**先保存旧文件**：`oldIdx !== newIdx` 时把编辑器当前内容写回 `files[oldIdx].code`。 | `MultiFileShell.vue:302-319` | **整项目替换后直接改 `activeFileIndex` 会被这个 watcher 用陈旧内容覆写复原的快照** → 必须走 `-1 → 替换 → 目标索引` 的三步（Task 5 有具体序列）。 |
| **D7** | `OptimizationCard` 的 `v-if` 依赖真实下标（`i !== store.chatMessages.length - 1`），且历史卡**必须保持挂载**（否则门禁重跑、`applied`/`undoToken` 丢失）。 | `AiTutorPanel.vue:63`；2026-09-10 devlog §4 | 折叠**必须用 `v-show`（或 `display:none`）而非 `v-if`**，且 `v-for` 的**真实下标不能变**（不得引入「过滤后的数组」）→ Task 4 的具体做法。 |
| **D8** | `switchMode` 会用 `restoreSingleSnapshot` 把 `chatMessages` 换成单文件模式的旧快照（多文件模式不捕获对话）。 | `player.js:532-559` | 「对话时间线」天然是**按模式分区**的。**本计划不改**这一既有怪癖，但记录点必须带 `mode`（Task 1），回退跨模式时自动切模式。 |

## 1. 已收敛的决策

| # | 决策 | 理由 / 边界 |
|---|---|---|
| **T1** | **成功运行**与**应用优化**各创建一个「记录点」 | 「应用优化」会改代码但不走 `/api/run`（用的是门禁那次的运行结果），不建点就会在时间线上留下「代码已变、无线索」的空档。导入文件/加载算法**不单独建点**（噪声大），归入下一次运行。 |
| **T2** | 记录点 = **代码快照 + 摘要**，**不保存运行结果**（steps/内存快照） | `steps` 每步含变量/堆/栈帧，50 步可能几百 KB，存 N 条会吃内存。Java 执行确定 → **回退时重跑一次**即可复现，且保证「编辑器代码 ↔ 右栏面板」永远同源。代价：多一次往返、步骤位置回到第 1 步（已接受）。 |
| **T3** | 回退 = **代码 + 运行结果回滚**，其后的对话**折叠保留、可展开** | 不丢内容；也不会让「关于已不存在的代码」的问答干扰阅读。折叠用一个 `foldFromIndex` 单值表达。 |
| **T4** | 时间线**仅内存**，刷新即清 | 与现状一致（对话本来也不跨刷新保留）；无 localStorage 配额与版本兼容负担。 |
| **T5** | 记录点带 `mode`；回退时若模式不同则**自动切模式** | 单/多文件的代码结构不同，快照必须在对应结构里恢复（`switchMode` 已经会保留各模式的状态）。 |
| **T6** | **回退后的那次重跑不建新记录点**（`silent`），**下一次真实的成功运行会清掉折叠** | 回退在时间线上就是「回到第 k 点」，不是新版本；用户继续往前走时恢复正常线性阅读。 |
| **T7** | 折叠只影响**渲染**（`v-show`），**不删除、不重排** `chatMessages` | 保住优化卡的挂载状态（D7）；「展开」是纯 UI 开关。 |

---

## 2. 改动清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `javatutor/frontend/src/utils/timeline.js` | **新建**：`buildCheckpointLabel` / `isFolded` / `foldedCount` / `clampActiveIndex` / `REVERT_CONFIRM` / `MAX_TIMELINE` |
| 2 | `javatutor/frontend/src/utils/timeline.test.js` | **新建**：上述纯函数用例 |
| 3 | `javatutor/frontend/src/stores/player.js` | `timeline`/`timelineSeq`/`foldFromIndex` 状态；`pushCheckpoint`；`revertToCheckpoint`；`runCode`/`runProject` 去掉清空对话并支持 `{silent}`；`applyCandidateRun` 接 `meta` 并建点 |
| 4 | `javatutor/frontend/src/stores/__tests__/player-timeline.test.js` | **新建**：建点时机 / 失败不建点 / 折叠与展开 / silent 不建点 |
| 5 | `javatutor/frontend/src/components/TimelineDivider.vue` | **新建**：分割线 + 摘要 + 「回退到此」+ 折叠占位与「展开」 |
| 6 | `javatutor/frontend/src/components/SingleFileShell.vue` | provide `restoreSource(cp)` |
| 7 | `javatutor/frontend/src/components/MultiFileShell.vue` | provide `restoreSource(cp)`（三步替换，见 D6） |
| 8 | `javatutor/frontend/src/components/AiTutorPanel.vue` | 渲染 `role:'divider'` 与折叠占位（真实下标不变） |
| 9 | `javatutor/frontend/src/components/OptimizationCard.vue` | 调用 `applyCandidateRun` 时带上 `meta`（供记录点摘要） |
| 10 | `javatutor/frontend/src/utils/optimization.js` | `SNAPSHOT_UNDO_CONFIRM` 旁新增 `REVERT_CONFIRM`（或统一放 `timeline.js`，二选一，别两处都有） |
| 11 | `docs/devlog/2026-09-10-coze-agent-run-timeline.md` | **新建**实施记录 |

---

## Task 1：`utils/timeline.js`（**测试先行**）

```js
export const MAX_TIMELINE = 30
/** 回退前的确认文案：明示会覆盖当前编辑器内容并重跑 */
export const REVERT_CONFIRM = '回退会覆盖当前编辑器内容，并把右侧刷新为那次运行的结果（其后对话将折叠保留）。确定回退吗？'

/** 记录点摘要：分割线上那一行「简短的新代码信息记录」。 */
export function buildCheckpointLabel({
  seq, kind, mode, time, methodName, entryFile, fileCount,
  code, steps, output, goalLabel, target,
}) {
  const head = `#${seq}`
  const when = time || ''
  if (kind === 'optimize') {
    const what = goalLabel ? `已应用优化（${goalLabel}）` : '已应用优化'
    return [head, what, target, when].filter(Boolean).join(' · ')
  }
  if (mode === 'multi') {
    const entry = fileCount ? `项目 ${fileCount} 文件${entryFile ? `（入口 ${entryFile}）` : ''}` : '项目'
    const n = Array.isArray(steps) ? `${steps.length} 步` : ''
    const out = shortOutput(output)
    return [head, entry, when, n, out].filter(Boolean).join(' · ')
  }
  const lines = typeof code === 'string' && code ? `${code.split('\n').length} 行` : ''
  const n = Array.isArray(steps) ? `${steps.length} 步` : ''
  return [head, methodName || '', when, lines, n, shortOutput(output)].filter(Boolean).join(' · ')
}

/** 输出首行，截断 20 字（空输出返回 ''）。 */
function shortOutput(output) {
  const first = String(output || '').split('\n').find((l) => l.trim()) || ''
  if (!first) return ''
  const cut = first.trim().slice(0, 20)
  return `输出 "${cut}${first.trim().length > 20 ? '…' : ''}"`
}

/** 折叠边界：返回 [start, end) 的起始下标；未折叠返回 -1。 */
export function foldStartIndex(foldFromIndex) {
  return typeof foldFromIndex === 'number' && foldFromIndex >= 0 ? foldFromIndex + 1 : -1
}
export function isFolded(index, foldFromIndex) {
  const start = foldStartIndex(foldFromIndex)
  return start >= 0 && index >= start
}
export function foldedCount(total, foldFromIndex) {
  const start = foldStartIndex(foldFromIndex)
  return start < 0 ? 0 : Math.max(0, total - start)
}

/** 回退时把激活文件下标收敛到合法范围（文件数可能已变）。 */
export function clampActiveIndex(index, fileCount) {
  if (!fileCount) return -1
  const i = Number.isInteger(index) ? index : 0
  return Math.max(0, Math.min(i, fileCount - 1))
}
```

用例：单文件摘要有 `methodName`/行数/步数/输出；多文件摘要含「项目 N 文件」与入口；`kind:'optimize'` 摘要含目标；空输出/无 steps 不产生空段（`· ·` 不得出现）；`isFolded` 边界（`foldFromIndex >= total` 时 `foldedCount === 0`）；`clampActiveIndex(9, 3) === 2`、`(3, 0) === -1`。

## Task 2：`player.js` — 状态与建点

```js
timeline: [],        // [{ id, seq, kind:'run'|'optimize', label, mode, chatIndex, time, code?, files?, activeFileIndex?, goalLabel?, target? }]
timelineSeq: 0,
foldFromIndex: null, // 折叠起点：> 此下标的 chatMessages 折叠（T3/T7）；null = 不折叠
```

```js
/** 记录点：捕获当前代码快照（深拷贝——files[i].code 会被就地改写）。 */
pushCheckpoint({ kind = 'run', steps, output, goalLabel = '', target = '', mode = this.mode }) {
  const seq = ++this.timelineSeq
  const time = new Date().toLocaleTimeString('zh-CN', { hour12: false }).slice(0, 5)
  const cp = {
    id: `cp-${seq}`, seq, kind, mode, time,
    chatIndex: this.chatMessages.length,
    goalLabel, target,
  }
  if (mode === 'multi') {
    cp.files = this.multiState.files.map((f) => ({ name: f.name, code: f.code }))
    cp.activeFileIndex = this.multiState.activeFileIndex
  } else {
    cp.code = this.code || ''
  }
  cp.label = buildCheckpointLabel({
    seq, kind, mode, time, goalLabel, target,
    methodName: this.methodName, entryFile: this.multiState.entryFile,
    fileCount: this.multiState.files.length, code: cp.code, steps, output,
  })
  // 超上限：丢最旧的**代码快照**，分割线保留但按钮置灰（见 Task 5）
  if (this.timeline.length >= MAX_TIMELINE) {
    const oldest = this.timeline.shift()
    oldest.expired = true
    delete oldest.code
    delete oldest.files
  }
  this.timeline.push(cp)
  // 分割线：新增**真实**消息（role:'divider'），不触碰既有下标语义（D7）
  this.chatMessages.push({ role: 'divider', text: cp.label, checkpointId: cp.id })
  return cp
}
```

接入点：

1. **`runCode(code, opts = {})` / `runProject(opts = {})`**：
   - **删除** `this.chatMessages = []`（D3 的唯一目标改动）；其余清理保留。
   - 把 `opts` 透传到 `applyRunResult`（新增第二参 `opts`），或用一个临时标记字段 `this._runOpts`。**推荐后者**（`applyRunResult` 被两处调用，签名改动面更小）：
     ```js
     this._runOpts = { silent: !!opts.silent }
     ```
     并在成功分支末尾 `this._runOpts = null`。
2. **`applyRunResult(data, opts)`** 成功分支末尾：
   ```js
   if (!opts?.silent) {
     this.foldFromIndex = null            // T6：真实的成功运行恢复正常线性阅读
     this.pushCheckpoint({ kind: 'run', steps: data.data || data.steps, output: data.output })
   }
   ```
   **失败分支不建点、不插分割线**（用户选的是「成功运行」）。
3. **`applyCandidateRun(data, code, meta = {})`**：现有实现返回快照（review R2 已修）→ 在末尾追加
   ```js
   this.foldFromIndex = null
   this.pushCheckpoint({ kind: 'optimize', steps: data.data || data.steps, output: data.output,
                         goalLabel: meta.goalLabel || '', target: meta.target || '' })
   ```
   `OptimizationCard.apply()` 调用处改为 `store.applyCandidateRun(gateSnapshot.value || {}, code, { goalLabel: goalLabel.value, target: props.plan.target })`（`goalLabel` 已在卡片里存在）。
4. **`revertToCheckpoint(cp)`**（异步）：
   ```js
   async revertToCheckpoint(cp) {
     if (!cp) return false
     this.foldFromIndex = cp.chatIndex
     if (cp.mode !== this.mode) this.switchMode(cp.mode)
     if (cp.mode === 'multi') await this.runProject({ silent: true })
     else await this.runCode(cp.code, { silent: true })
     return true
   }
   ```
   > 代码本身由调用方（`TimelineDivider` 经 `restoreSource`）先写回，本方法只管「折叠 + 重跑」。
   > `cp.expired`（超出上限被丢快照）时**不得**调用本方法 —— 由组件置灰按钮。
   > **已知代价**：`runCode` 会把 `currentStep` 复位为 0（T2 已接受）。

## Task 3：`stores/__tests__/player-timeline.test.js`（**新建**）

按 `player-optimization.test.js` 的写法（`mockFetch` + `/api/run/project` 先于 `/api/run` 匹配）：

- 成功运行 → `chatMessages` **未被清空**，末尾多一条 `role:'divider'`，`timeline.length === 1`，`tl[0].kind === 'run'`，`chatIndex === 运行前的消息数`。
- 失败运行（`{code:400,error}`）→ `timeline` 不变、`chatMessages` 不新增 divider、`lastRunError` 有值。
- `applyCandidateRun(..., {goalLabel:'性能'})` → `timeline` 多一条 `kind:'optimize'` 且 `label` 含「性能」。
- `revertToCheckpoint(cp)` → `foldFromIndex === cp.chatIndex`；且因 `silent`，`timeline.length` **不增加**。
- 折叠后一次真实的成功运行 → `foldFromIndex === null`。
- 超过 `MAX_TIMELINE` → 最旧一条 `expired === true` 且 `code`/`files` 已删、`timeline.length` 仍为 `MAX_TIMELINE`。

## Task 4：`AiTutorPanel.vue` — 渲染分割线与折叠（**下标语义不可变**）

模板 `v-for` 改为 `<template v-for="(m, i) in store.chatMessages" :key="i">`，内部：
- `role === 'divider'` → `<TimelineDivider :cp="cpOf(i)" :folded-count="i === store.foldFromIndex ? foldedCount(...) : 0" />`
- `role === 'user' | 'assistant'` → 现有 `.chat-msg` 模板块**原样不动**，只把最外层 `v-if` 补上折叠判断：
  ```html
  <div v-show="!isFolded(i)" class="chat-msg" :class="m.role">
  ```
  **必须 `v-show`**（D7）：`v-if` 会在折叠时卸载优化卡，展开后门禁重跑、`applied`/`undoToken` 丢失。
- 折叠占位（「以下 N 条对话基于更新后的代码，已折叠 [展开]」）渲染在下标 `=== store.foldFromIndex` 的那一条之后（即 `i === store.foldFromIndex` 的分割线组件内部，由 `folded-count > 0` 触发），**不新增/不重排消息**。
- `parsedMessages` 的 `role !== 'assistant'` 回退分支保持 `{ body, edits: [], nav: { views: [] }, plan: null }`（divider 不走解析）。
- 自动滚动的 watcher 以 `role:text.length` 为键 → divider 文本非空即可自然触发，无需改（**不要**把 divider 的 `text` 留空）。
- `isFolded(i)` / `foldedCount` / `cpOf(i)`（`store.timeline.find(t => t.id === m.checkpointId)`）从 `utils/timeline.js` 引入或就地包装。

## Task 5：`TimelineDivider.vue` + 两个 Shell 的 `restoreSource`

**`TimelineDivider.vue`（新建）**：

```js
const store = usePlayerStore()
const props = defineProps({ cp: { type: Object, required: true }, foldedCount: { type: Number, default: 0 } })
const restoreSource = inject('restoreSource', null)

async function revert() {
  if (props.cp.expired) return
  if (typeof window !== 'undefined' && typeof window.confirm === 'function'
    && !window.confirm(REVERT_CONFIRM)) return
  const ok = restoreSource?.(props.cp)          // 先把代码写回编辑器/文件
  if (ok === false) return
  await store.revertToCheckpoint(props.cp)      // 折叠 + 静默重跑
}
```

渲染：一条横向分割线 + `cp.label` + `[回退到此]`（`cp.expired` 时置灰并显示「记录已过期」）+（`foldedCount > 0` 时）「以下 {{ foldedCount }} 条对话已折叠 [展开]」（`@click="store.foldFromIndex = null"`）。

**`SingleFileShell.vue`**：

```js
provide('restoreSource', (cp) => {
  if (!cp?.code) return false
  editorRef.value?.setCode(cp.code)
  return true
})
```

**`MultiFileShell.vue`**（**必须按三步走**，否则被 D6 的 watcher 用陈旧内容覆写）：

```js
provide('restoreSource', async (cp) => {
  if (!Array.isArray(cp?.files)) return false
  // 1) 先置 -1：让 watcher 把旧内容保存进「即将被丢弃的旧数组」（oldIdx 一定 >= 0，但写入目标马上被替换）
  store.multiState.activeFileIndex = -1
  await nextTick()
  // 2) 整项目替换（深拷贝，避免与记录点共享引用）
  store.multiState.files = cp.files.map((f) => ({ name: f.name, code: f.code }))
  // 3) 收敛激活下标（文件数可能已变）→ watcher 此时 oldIdx === -1，跳过保存，仅 setCode 载入
  store.multiState.activeFileIndex = clampActiveIndex(cp.activeFileIndex, store.multiState.files.length)
  await nextTick()
  return true
})
```

> 单文件模式下 `MultiFileShell` 未挂载、多文件模式下 `SingleFileShell` 未挂载，因此两个 `provide` 不会冲突。

## Task 6：与优化卡的交互（不要破坏既有语义）

- `applyCandidateRun` 建点后，**卡片的撤销仍然可用**：撤销会把代码与右栏回填，但时间线上那一条「已应用优化」记录点不会被移除（它是事实记录）。请在手验清单里核对「撤销后时间线仍显示该记录点」是可接受的（若不可接受，后续再补「撤销时移除该点」——本计划**不做**，避免 undo/时间线两套状态互相扰动）。
- 撤销后 `foldFromIndex` 不变（撤销不改变折叠）。
- **`applyCandidateRun` 依旧不重置会话状态**（review R2 的既有约束），本计划只在其末尾追加建点。

## Task 7：文档

- `docs/devlog/2026-09-10-coze-agent-run-timeline.md`：改动清单、决策 T1–T7、与计划的偏差、测试数、已知局限（T2 的步骤复位、D8 的模式分区、40+ 条消息时的 DOM 体量）、手验清单。
- 本功能**不单开 spec**（决策已完整记录在本计划 §1）；若后续要固化成契约（例如给队友的 harness 复用「记录点」结构），再补 `docs/spec/2026-09-10-coze-agent-run-timeline.md`。
- 若实现改了 `AiTutorPanel` 的消息渲染契约（`role` 取值新增 `divider`），在 `docs/agent-collaboration-guide.md` **无需**改动（该文档描述的是 coze 图结构/输入输出，不涉及前端消息 role）——**不要**顺手改它。

---

## 验证

```bash
cd javatutor/frontend && npx vitest run     # ≥291 + 新增用例，全绿
cd javatutor/frontend && npm run build      # SFC 编译无误
cd javatutor-coze && uv run pytest -q       # 应保持 226（本计划不应动 coze）
```

## 手验清单（`npm run dev`）

1. 运行代码 → 问两个问题 → **再次运行**（改了代码）→ 对话窗口**不再清空**，新运行处出现分割线 `#2 · <方法名/项目> · 14:05 · N 行 · M 步 · 输出 "…"`。
2. 分割线上点「回退到此」→ 确认框 → 编辑器代码回到那次运行的内容（单文件与多文件各测一次），右栏刷新为那次运行的结果（步数/输出一致）。
3. 回退后：其后对话折叠成一行「以下 N 条对话已折叠」，点「展开」全部恢复且**历史优化卡状态未丢**（应用过的卡仍显示「已应用」而不是重新校验）。
4. 回退本身**不新增**记录点（时间线条数不变）；随后跑一次新代码 → 折叠自动解除、新增一条记录点。
5. 应用一次优化 → 出现 `#N · 已应用优化（性能）· Main.java · …` 记录点；点它的「回退到此」能回到优化前的代码。
6. 多文件：回退到「只有 2 个文件」的记录点（先删/加过文件）→ 文件列表整体恢复、编辑器载入正确、**不发生内容被覆盖成回退前编辑内容的错乱**（D6 的回归点）。
7. 失败运行（编译错误）→ **不建记录点、不插分割线**，红色弹窗照旧（与另一份修复计划的 F4 一起验）。
8. 造 31 次成功运行 → 最旧一条显示「记录已过期」且按钮置灰，其余可正常回退。

## 遗留 / 注意事项

- **`currentStep` 复位为 0**（T2 的代价）：回退后用户需自己重新定位到感兴趣的那一步。若不可接受，后续再评估「随记录点存 steps」（内存换体验）。
- **模式分区的对话**（D8）：多文件 ↔ 单文件来回切会各自保留自己的对话（既有行为），时间线因此也是分区的；**本计划不改**。
- **`switchMode` 在回退中会被调用**（T5）：`switchMode` 会把当前模式的快照存进 `singleState`，因此回退不会丢另一个模式的对话。若实测发现有状态被覆盖，退路是「跨模式回退时提示用户先手动切模式」。
- **DOM 体量**：对话只增不减（仅内存），超长会话下 `chat-body` 的节点数会增长。若实测卡顿，后续给「已折叠区」加虚拟化；**本计划不做**。
- **`explainHistory`（D4）**：可顺带删除（含 `player-optimization.test.js` 的两处断言），但**非必需**，不要为它扩大改动面。
