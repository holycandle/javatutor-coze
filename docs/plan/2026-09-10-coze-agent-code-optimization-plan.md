# 执行计划：Coze Agent 代码优化（优化卡 + 报错预填）

> 执行依据：`docs/spec/2026-09-10-coze-agent-code-optimization.md`（决策 D1–D11 见该文档 §2，本文不再复述理由）。
> **跨两仓**：`javatutor-coze`（agent prompt）+ `javatutor`（Vue 前端）。后端**无需改动**。
> 本计划在 coze 仓的 `docs/plan/` 下，前端文件以 `javatutor/frontend/...` 标全路径。

## 0. 全局约束（务必遵守）

- **不做任何 git 操作**（不 `git add`/`commit`/`push`/`stash`/`checkout`/`branch`）。读 `git status`/`git diff` 可以。
- 前端**不触碰** `javatutor/frontend/src/backup-20260807/`（备份副本）。
- **向后兼容是硬要求**：`kind` 缺失或 `kind:"patch"` 时，解析/卡片/apply/undo 行为必须与现状**完全一致**。
  改前先跑一遍基线：`npm test`（前端 249 用例）+ `uv run pytest -q`（coze 217 用例）。
- 保持现有命名/风格（前端 ESM + `defineStore`；coze 中文 docstring、`_` 私有函数）。
- 每次改动先写测试（`editSuggestion.test.js` 已覆盖大量解析边界，新用例照其风格追加）。

### 0.1 两处与 spec §7.1 的实现偏差（本计划已定，实施后回改 spec）

| 偏差 | spec 原文 | 本计划 | 理由 |
|---|---|---|---|
| **B1** | 「`EditSuggestionCard.vue` 按 `plan.kind` 渲染三分支」 | **新建 `OptimizationCard.vue`**，`EditSuggestionCard.vue` **不动** | 共享的是**块通道**（mark/解析/剥离/apply-undo 原语），不是组件。新建组件让 patch 路径零回归风险，且 options/replace 的 UI 与 diff 卡差别很大。 |
| **B2** | 未指定 apply 实现 | **整文件替换 = 一条 `old_string` 为「当前全文」的 edit**，直接复用 `applyAiEdits` | `planEdits` 在全文唯一匹配 → `status:'ok'` → `executeEdits` 覆盖全文，**天然是一个 undo 单元**，`undoToken` 语义原样可用（D10 的「Monaco undo 优先」白送）。 |

> B2 的边界：编辑器为空（`old_string` 为空串）时 `planEdits` 返回 `not-found`（[editSuggestion.js:136-137](../../../javatutor/frontend/src/utils/editSuggestion.js)），
> 此时退回 `restoreCode(candidate)` 直接写入。

---

## 1. 改动清单

| # | 仓 | 文件 | 改动 |
|---|---|---|---|
| 1 | 前端 | `javatutor/frontend/src/utils/editSuggestion.js` | 解析 `kind`（`options`/`replace`）；返回值增 `plan`；导出 `GOALS` 与 prompt 模板 |
| 2 | 前端 | `javatutor/frontend/src/utils/editSuggestion.test.js` | 新增解析/降级用例；`空输入安全` 用例补 `plan:null` |
| 3 | 前端 | `javatutor/frontend/src/components/OptimizationCard.vue` | **新建**：options 卡 / replace 卡（门禁状态 + 应用 + 撤销） |
| 4 | 前端 | `javatutor/frontend/src/components/AiTutorPanel.vue` | 渲染 `OptimizationCard`；`chatInput` 提升为 `store.chatDraft` |
| 5 | 前端 | `javatutor/frontend/src/stores/player.js` | `applyCandidateRun`；`lastRunError`；`chatDraft`；`askGoalOptimization` |
| 6 | 前端 | `javatutor/frontend/src/components/SingleFileShell.vue` | provide `restoreCode` |
| 7 | 前端 | `javatutor/frontend/src/components/MultiFileShell.vue` | provide `restoreCode`；按 `target` 替换文件 + 切到该文件 |
| 8 | 前端 | `javatutor/frontend/src/components/ConsoleOutput.vue` | 报错入口（只预填） |
| 9 | coze | `src/graphs/javatutor/prompting/optimization.py` | **新建** `render_optimization_guidance()` |
| 10 | coze | `src/graphs/javatutor/main_agent.py` | `_main_system_prompt()` 注入优化引导 |
| 11 | coze | `src/graphs/javatutor/prompts.py` | `SYSTEM_PROMPT_CRITIC` / `SYSTEM_PROMPT_REVISE` 允许并保留新块 |
| 12 | coze | `src/graphs/javatutor/prompting/main_fewshots.py` | 两步式样例 2 条 |
| 13 | coze | `tests/test_optimization_guidance.py` | **新建**：引导 + few-shot 守卫 |
| 14 | 两仓 | `docs/devlog/2026-09-10-coze-agent-code-optimization.md` | 实施记录 |

---

# Phase A — 前端：契约与解析

## Task 1：`editSuggestion.js` — 解析 `kind`（**测试先行**）

先加测试（`editSuggestion.test.js`）：

```js
it('解析 kind=options 方案卡', () => {
  const raw = '可优化点如下\n\n【编辑建议】\n{"kind":"options","target":"Solution.java","options":[{"goal":"performance","label":"以性能为先","detail":"用哈希表"},{"goal":"readability"}]}\n\n【决策痕迹】\n{}'
  const { body, edits, plan } = parseAssistantMessage(raw)
  expect(body).toBe('可优化点如下')
  expect(edits).toHaveLength(0)
  expect(plan.kind).toBe('options')
  expect(plan.target).toBe('Solution.java')
  expect(plan.options).toHaveLength(2)
  expect(plan.options[0]).toMatchObject({ goal: 'performance', label: '以性能为先', detail: '用哈希表' })
  expect(plan.options[1].label).toBe('可读性')   // label 缺省 → 中文规范名
})

it('解析 kind=replace 整文件覆盖', () => {
  const raw = '改动如下\n\n【编辑建议】\n{"kind":"replace","target":"Solution.java","goal":"performance","rationale":"换成哈希表","code":"public class Solution {}"}\n\n【决策痕迹】\n{}'
  const { body, edits, plan } = parseAssistantMessage(raw)
  expect(body).toBe('改动如下')
  expect(edits).toHaveLength(0)
  expect(plan).toMatchObject({ kind: 'replace', target: 'Solution.java', goal: 'performance' })
  expect(plan.code).toBe('public class Solution {}')
})

it('goal 不在闭集 → 该项丢弃；全部非法 → 整块按正文', () => {
  const bad = '前\n\n【编辑建议】\n{"kind":"options","options":[{"goal":"whatever"}]}\n\n【决策痕迹】\n{}'
  const { body, plan } = parseAssistantMessage(bad)
  expect(plan).toBeNull()
  expect(body).toContain('【编辑建议】')
})

it('replace 的 code 为空 → 整块按正文', () => {
  const bad = '前\n\n【编辑建议】\n{"kind":"replace","code":"   "}\n\n【决策痕迹】\n{}'
  const { body, plan } = parseAssistantMessage(bad)
  expect(plan).toBeNull()
  expect(body).toContain('【编辑建议】')
})

it('kind 非法 → 按 patch 处理（与现状一致）', () => {
  const raw = '前\n\n【编辑建议】\n{"kind":"nonsense","edits":[{"old_string":"a","new_string":"b"}]}\n\n【决策痕迹】\n{}'
  const { edits, plan } = parseAssistantMessage(raw)
  expect(edits).toHaveLength(1)   // 非法 kind 回落 patch 分支
  expect(plan).toBeNull()
})
```

实现（顶部加常量 + 归一化函数）：

```js
// goal 闭集：中文规范名（与 spec §4.4 一致；前端据此渲染 label 与拼提问）
export const GOALS = {
  performance: '性能', readability: '可读性', memory: '内存',
  style: '规范', correctness: '正确性',
}

// 点击目标选项时拼出的提问（确定、可日志，不由模型自由发挥）
export function buildGoalPrompt(goal, detail) {
  const name = GOALS[goal] || goal
  const tail = detail ? `，具体要求：${detail}` : ''
  return `以「${name}」为优先优化当前代码${tail}。请给出优化后的完整代码。`
}

// 归一化非 patch 的编辑建议块；不合法返回 null（调用方回退为正文）
function normalizePlan(parsed) {
  const kind = typeof parsed?.kind === 'string' ? parsed.kind : 'patch'
  if (kind === 'options') {
    const options = (Array.isArray(parsed.options) ? parsed.options : [])
      .filter((o) => o && typeof o.goal === 'string' && GOALS[o.goal])
      .slice(0, 3)
      .map((o) => ({
        goal: o.goal,
        label: typeof o.label === 'string' && o.label ? o.label : GOALS[o.goal],
        detail: typeof o.detail === 'string' ? o.detail : '',
      }))
    if (!options.length) return null
    return { kind: 'options', target: typeof parsed.target === 'string' ? parsed.target : '', options }
  }
  if (kind === 'replace') {
    const code = typeof parsed.code === 'string' ? parsed.code : ''
    if (!code.trim()) return null
    return {
      kind: 'replace',
      target: typeof parsed.target === 'string' ? parsed.target : '',
      goal: typeof parsed.goal === 'string' && GOALS[parsed.goal] ? parsed.goal : '',
      rationale: typeof parsed.rationale === 'string' ? parsed.rationale : '',
      code,
    }
  }
  return null   // patch / 非法 kind → 走既有 edits 分支
}
```

`extractStructBlocks` 改动（**只动 EDIT_MARK 分支**，`nav` 与剥离循环不变）：

```js
function extractStructBlocks(body) {
  let text = body
  const edits = []
  const nav = { views: [] }
  let plan = null
  // ...（循环体不变）
      const parsed = JSON.parse(jsonStr)
      if (bestMark === NAV_MARK) {
        /* 现状不变 */
      } else {
        const p = normalizePlan(parsed)
        if (p) { plan = p; usable = true }
        else {
          /* 现状的 edits 分支原样保留 */
        }
      }
  // ...
  return { body: collapseBlankLines(text.trimEnd()), edits, nav, plan }
}
```

`parseAssistantMessage` 的 JSDoc 返回值补 `plan`；**空输入安全**用例改为
`expect(parseAssistantMessage('')).toEqual({ body: '', edits: [], nav: { views: [] }, plan: null })`。

> 注意：`plan` 非空时该块的 `edits` 必须为空——不要同时走两个分支。

## Task 2：新建 `OptimizationCard.vue`

放在 assistant 气泡内 `EditSuggestionCard` 旁，样式参考现有卡片（`--mono`/`--accent`/`--border` 变量）。

**props**：`plan`（`options` | `replace`）。
**inject**：`applyAiEdits`、`undoAiEdits`、`restoreCode`（Task 6/7 提供）。
**本地 state**：`gate`（`idle | running | ok | fail`）、`gateError`、`snapshot`、`applyResult`、`undoError`。

**`options` 分支**：每个 option 一个按钮（`label` + `detail` 小字），点击：

```js
function choose(o) { store.askGoalOptimization(o.goal, o.detail, props.plan.target) }
```
（`askGoalOptimization` 见 Task 5。）

**`replace` 分支**：挂载即跑门禁（Task 3 的 `gateCandidate`），渲染：

- 标题（目标中文名）+ `rationale`；
- 门禁状态：`running` → 「校验中…」；`fail` → 错误原文 + 「应用」**禁用**；`ok` → 「校验通过」+「应用」可用；
- 应用成功后：「已应用」+ **撤销**按钮。

**应用**（B2 的合成 edit）：

```js
function apply() {
  const target = props.plan.target
  const current = currentCodeOf(target)        // 单文件=store.code；多文件=该文件 .code
  snapshot.value = current                     // 覆盖前快照（D10 回退用）
  const res = applyAiEdits?.([{
    title: '代码优化', explanation: props.plan.rationale,
    old_string: current, new_string: props.plan.code,
  }])
  if (!res || res.applied === 0) {             // 编辑器为空等情况
    restoreCode?.(props.plan.code, target)
    undoToken.value = null
  } else {
    undoToken.value = res.undoToken
  }
  store.applyCandidateRun(gateSnapshot.value)  // D7：右侧刷成候选运行结果
  applied.value = true
}
```

**撤销**（D10 二者结合）：

```js
function undo() {
  if (undoToken.value != null && undoAiEdits?.(undoToken.value)) { applied.value = false; return }
  if (!confirm('代码已改动，撤销将丢弃此后的编辑，确定撤销吗？')) return
  restoreCode?.(snapshot.value, props.plan.target)
  store.restorePreviousRun()   // 见 Task 5：右侧回到覆盖前快照
  applied.value = false
}
```

## Task 3：门禁（在卡片内直接 fetch，**不复用 `runCode`**）

> **关键**：`runCode` 会置 `store.isLoading`（全局「运行中…」遮罩）与 `store.error`（红色 toast），
> 还会**清空 `chatMessages`**（[player.js:91-127](../../../javatutor/frontend/src/stores/player.js)）。门禁必须绕开它。

```js
async function gateCandidate(code, target) {
  gate.value = 'running'
  try {
    const isMulti = store.mode === 'multi' && target
    const res = await fetch(isMulti ? '/api/run/project' : '/api/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(isMulti
        ? { files: store.multiState.files.map((f) => f.name === target ? { ...f, code } : f) }
        : { code }),
    })
    const data = await res.json()
    if (data.code === 200 || data.success) { gate.value = 'ok'; gateSnapshot.value = data }
    else { gate.value = 'fail'; gateError.value = data.error || data.msg || '未知错误' }
  } catch (e) { gate.value = 'fail'; gateError.value = e.message || '校验请求失败' }
}
```

- 门禁**不消耗 agent token**、不影响会话状态。
- 若 `store.testMode` 为真，单文件门禁需带 `{ mode:'test', testCases: store.testCases }`（与 `runCode` 一致）。

## Task 4：`AiTutorPanel.vue`

1. `import OptimizationCard from './OptimizationCard.vue'`。
2. 气泡内（[AiTutorPanel.vue:58-65](../../../javatutor/frontend/src/components/AiTutorPanel.vue)）`EditSuggestionCard` 旁加：
   ```html
   <OptimizationCard
     v-if="parsedMessages[i].plan && !store.isExplaining"
     :plan="parsedMessages[i].plan"
   />
   ```
3. `parsedMessages`（:184-188）fallback 对象补 `plan: null`（parseAssistantMessage 已返回 plan，map 分支不用改）。
4. **`chatInput` 提升到 store**：删 `const chatInput = ref('')`，`v-model="chatInput"` → `v-model="store.chatDraft"`，
   `sendChat` 里 `chatInput.value` → `store.chatDraft`，发送后 `store.chatDraft = ''`。
   发送按钮 `:disabled` 里的 `!chatInput.trim()` → `!store.chatDraft.trim()`。
   > 这是「预填」能落地的前提（Task 8 的按钮写 `store.chatDraft`）。

## Task 5：`player.js`

1. **state**：新增 `chatDraft: ''`、`lastRunError: null`、`previousRun: null`。
2. **`lastRunError` 写入**（**不得**被 `GlobalStatus` 清掉）：
   - `runCode` / `runProject` 的 `catch` 里：`this.lastRunError = { message: e.message || '网络请求失败', code, mode: this.testMode ? 'test' : 'run' }`；
   - `applyRunResult` 的 `else` 分支（[:178-180](../../../javatutor/frontend/src/stores/player.js)）同样写 `lastRunError`；
   - `applyRunResult` 成功分支里 `this.lastRunError = null`（下次成功运行自动清）。
   - `GlobalStatus.vue` **不改**（它清的是 `store.error`）。
3. **`applyCandidateRun(snapshot)`**（**不清会话**，D7）：

   ```js
   /** 用「候选代码」的运行结果刷新右侧面板；与 applyRunResult 的关键区别：不重置会话状态。 */
   applyCandidateRun(data) {
     this.previousRun = { steps: this.steps, output: this.output, runId: this.runId, currentStep: this.currentStep }
     this.steps = data.data || data.steps || []
     this.runId = data.runId
     this.output = data.output || ''
     this.currentStep = 0
     if (data.methodName) this.methodName = data.methodName
     if (data.methodSignature) this.methodSignature = data.methodSignature
     this.cfViewStack = []
     this.requestAnalysis()
     this.requestControlFlow()
     // 注意：不碰 chatMessages / explainHistory / activeAiTab / explainError
   },
   restorePreviousRun() { /* 用 previousRun 回填上述字段并重跑 requestAnalysis/requestControlFlow */ },
   ```
   > `previousRun` 记录「覆盖前」的展示状态，供撤销回退（D10）。若为 `null` 则跳过。
4. **`askGoalOptimization(goal, detail, target)`**：

   ```js
   async askGoalOptimization(goal, detail, target) {
     let q = buildGoalPrompt(goal, detail)
     if (this.mode === 'multi' && target) q += `（目标文件：${target}）`
     await this.askQuestion(q)   // 复用既有发送入口（player.js:203）
   },
   ```
   （`buildGoalPrompt` 从 `../utils/editSuggestion.js` import。）

**测试先行**（`stores/__tests__/` 新增 `player-optimization.test.js`）：
- `applyCandidateRun` **不清** `chatMessages`/`activeAiTab`/`explainHistory`（这是本任务最易回归的点）；
- `applyCandidateRun` + `restorePreviousRun` 往返后 `steps`/`output` 回到原值；
- `runCode` 失败 → `lastRunError` 有值；再次成功运行 → 清空；
- `askGoalOptimization` 拼出的问题含中文目标名与 `detail`（spy `askQuestion`）。

## Task 6 / 7：`SingleFileShell.vue` / `MultiFileShell.vue`

两者都在 `provide('applyAiEdits'...)` 旁（[SingleFileShell.vue:255-256](../../../javatutor/frontend/src/components/SingleFileShell.vue)）加：

```js
// 覆盖前快照回退（撤销兜底）：直接写编辑器内容
provide('restoreCode', (code) => editorRef.value?.setCode(code))
```

**多文件额外**（`MultiFileShell.vue`）：

```js
provide('restoreCode', (code, target) => {
  const idx = store.multiState.files.findIndex((f) => f.name === target)
  if (idx < 0) return
  store.multiState.files[idx].code = code
  store.multiState.activeFileIndex = idx      // 切到该文件，用户能看到变化
})
```

- 应用优化后同样需要**切到 target 文件**（否则用户看不到改动）：在 `apply()` 成功后对多文件调 `store.multiState.activeFileIndex = idx`。
- 编辑器加载依赖既有的 `[activeFileIndex, activeCode]` watcher（[MultiFileShell.vue:281-297](../../../javatutor/frontend/src/components/MultiFileShell.vue)）与 `activeCode` watcher（:322）——**改 `files[i].code` 即会触发 `setCode`**。
  实现时**必须验证**：target 为当前激活文件时，watcher 不会用编辑器旧内容把新代码覆盖回去（`oldIdx === newIdx` 分支应跳过保存）。
- **`target` 找不到**（spec §4.5）：不覆盖、卡片显示「目标文件不存在」并禁用「应用」——**不得**静默落到当前激活文件。

## Task 8：`ConsoleOutput.vue` — 报错入口（只预填）

`ConsoleOutput` 被 `SingleFileShell` 与 `MultiFileShell` **共用**（一处改动两处生效）。

在 header 下、`console-body` 之上加：

```html
<div v-if="store.lastRunError" class="console-error-bar">
  <span class="console-error-text">运行出错</span>
  <button class="console-error-btn" @click="prefillFix">让 agent 帮我看看</button>
</div>
```

```js
function prefillFix() {
  const msg = store.lastRunError?.message || ''
  store.chatDraft = `我的代码运行报错了，请帮我看看怎么修正：\n${msg}`
  // 只预填，不发送（D9）；不自动附导航卡
}
```

- 入口**常驻**（直到下次成功运行清 `lastRunError`），**不挂在** 6 秒即逝的 `GlobalStatus` toast 上。
- `ConsoleOutput.vue` 的 `collapsed` 折叠不应藏掉该入口（放在 header 外，或折叠时仍显示）。

---

# Phase B — coze：引导与守卫

## Task 9：新建 `prompting/optimization.py`

照 `prompting/panels.py` 的风格（中文 docstring、模块级常量）：

```python
"""代码优化引导：两步式（先方案后代码）+ kind 闭集 + goal 闭集。

与 render_nav_guidance() 同期注入 _main_system_prompt()（走 SystemMessage，不被 compress 截断）。
决策依据见 docs/spec/2026-09-10-coze-agent-code-optimization.md。
"""

GOALS = {
    "performance": "性能", "readability": "可读性", "memory": "内存",
    "style": "规范", "correctness": "正确性",
}


def render_optimization_guidance() -> str:
    goals = "/".join(f"{k}({v})" for k, v in GOALS.items())
    return f"""## 代码优化（两步式，不得一步到位）

当用户要求优化代码，或代码报错需要修正时，**分两步交付**：

**第一步：只给方案，不给代码。**
正文说明有哪些可优化点、各自代价，末尾附（`【决策痕迹】` 之前）：
【编辑建议】
{{"kind":"options","target":"<文件名；多文件必填>","options":[{{"goal":"performance","label":"以性能为先","detail":"用哈希表把嵌套循环降为 O(n)"}},{{"goal":"readability","label":"以可读性为先","detail":"拆分长方法并命名中间变量"}}]}}
- options 取 2–3 项；goal **只能**取：{goals}；detail 写针对这段代码的具体手段。
- **本步正文与块内都不得出现优化后的代码。**
- 用户已指明目标（如「优化性能」）时同样先出方案卡（只列该目标），保持交互一致。

**第二步：用户选定目标后才给完整代码。**
【编辑建议】
{{"kind":"replace","target":"<文件名>","goal":"<用户选定的目标>","rationale":"<一到两句：改了什么、为什么>","code":"<该文件完整代码>"}}
- code 必须是**完整、可独立编译**的该文件全文：不得省略、不得用 `...` 占位、不得只给片段或 diff。
- goal 必须等于用户选定的那个目标。
- 块之后不要再写任何正文。

**局部修改不适用两步式**：若只需改动少量既有代码（不换写法），仍用既有 patch 形态
（`{{"edits":[{{"title","old_string","new_string","explanation"}}]}}`），不要用 replace。
"""
```

## Task 10：`main_agent.py` 注入

`_main_system_prompt()`（[:22-28](../../src/graphs/javatutor/main_agent.py)）在 `render_usage_guide()` 后追加
`render_optimization_guidance()`；import 同步加。**顺序**：nav → algo catalog → usage → optimization → ui_map → few-shot。

## Task 11：`prompts.py` critic / revise

- `SYSTEM_PROMPT_CRITIC` 末尾「只返回 JSON。」**之前**加：
  ```
  判断正文时忽略【编辑建议】结构化块（含 kind=options/replace）；不得因 kind 取值或 code 内容判失败。
  仅在以下情况记轻微问题（不判失败）：kind 非法、options 的 goal 不在闭集、options 为空、replace 的 code 明显不完整。
  ```
- `SYSTEM_PROMPT_REVISE` 的「保留结构化块」一句扩展为：
  ```
  若原回答含【视角导航】/【编辑建议】结构化块（含 kind=options/replace），请**原样保留**（除非评审标记其非法）。
  ```

## Task 12：`main_fewshots.py` 增加两步式样例

在 `MAIN_FEW_SHOTS` 末尾追加两条（每条前置已有的 `MARKER`）：

```
【示例】问：帮我优化一下这段代码
答：这段代码有两处可优化：① 内层线性查找可用哈希表降为 O(1)；② 变量命名可以更清晰。
【编辑建议】
{"kind":"options","target":"Solution.java","options":[{"goal":"performance","label":"以性能为先","detail":"用哈希表把嵌套循环降为 O(n)"},{"goal":"readability","label":"以可读性为先","detail":"拆分长方法并命名中间变量"}]}
```
```
【示例】问：（用户选定「以性能为先」后）以「性能」为优先优化当前代码，具体要求：用哈希表把嵌套循环降为 O(n)。请给出优化后的完整代码。
答：把内层线性查找换成哈希表，整体由 O(n²) 降为 O(n)。
【编辑建议】
{"kind":"replace","target":"Solution.java","goal":"performance","rationale":"内层线性查找改为哈希表，整体由 O(n²) 降为 O(n)。","code":"import java.util.*;\n\npublic class Solution {\n    public int[] solve(int[] nums) {\n        Map<Integer,Integer> seen = new HashMap<>();\n        for (int i = 0; i < nums.length; i++) seen.put(nums[i], i);\n        return nums;\n    }\n}\n"}
```

> 示例里的代码仅示意（`MARKER` 已声明需替换为真实数据）；**必须保持 JSON 合法**（守卫测试会 parse）。

## Task 13：`tests/test_optimization_guidance.py`（新建）

照 `tests/test_panel_sync.py` 风格（同一 import 约定：`from graphs.javatutor.prompting.optimization import ...`）：

```python
from graphs.javatutor.prompting.optimization import GOALS, render_optimization_guidance
from graphs.javatutor.prompting.main_fewshots import get_main_few_shots

def test_optimization_guidance_lists_goal_enum():
    text = render_optimization_guidance()
    for goal in GOALS:
        assert goal in text

def test_optimization_guidance_twostep_and_kinds():
    text = render_optimization_guidance()
    assert "第一步" in text and "第二步" in text
    assert "kind" in text and "replace" in text and "options" in text
    assert "完整" in text          # 要求整份代码完整

def test_main_fewshots_optimization_samples_valid():
    joined = "\n".join(get_main_few_shots())
    assert '"kind":"options"' in joined and '"kind":"replace"' in joined
    # 每个样本里的 JSON 块都能 parse，且 options 的 goal 全部落在闭集
    ...

def test_main_system_prompt_injects_optimization():
    from graphs.javatutor.main_agent import _main_system_prompt
    assert "代码优化" in _main_system_prompt()
```

> **既有守卫兼容性（务必先看）**：`tests/test_panel_sync.py:148` 的 `test_main_few_shots_valid` 已有断言
> `len(shots) >= 3`、样本含 `subTab/categoryId/anchorId`/「测试模式」/「不附导航卡」、
> 且**含 `【视角导航】` 的样本其后必须紧跟 `{`**。新增的两条优化样本只含 `【编辑建议】`（该循环会跳过），
> 且 `len(shots)` 只增不减——**理论上不受影响，但必须实跑确认**。
> 另：新样本的 `【编辑建议】` 块必须是样本**最后内容**（块后不得再有正文），与 spec 的放置规则一致。

---

# Phase C — 验证

## Task 14：跑测试 + devlog

- 前端：`cd javatutor/frontend && npm test` 全绿（含新增用例）。
- coze：`uv run pytest -q` 全绿（含新增守卫）。
- 写 `docs/devlog/2026-09-10-coze-agent-code-optimization.md`（改动文件 + 测试结果 + 已知偏差 B1/B2）。

## 验证清单（按序）

1. **基线对照**：改动前的 `npm test` / `uv run pytest -q` 数字记下来，改动后不得下降。
2. **解析回归**：`kind` 缺失 / `kind:"patch"` 行为与现状逐条一致（`editSuggestion.test.js` 既有用例全绿）。
3. **手验（`npm run dev`，单文件）**：
   1. 跑一段可优化代码 → 问「帮我优化一下」→ 回答附**方案卡**（2–3 个目标），**无代码**；
   2. 点「以性能为先」→ 消息列表出现模板提问 → 第 2 轮回答附 **replace 卡**；
   3. 卡片显示「校验中…」→「校验通过」→ 点「应用」→ 编辑器被整份替换、右侧面板刷新为候选运行结果；
   4. 点「撤销」（未编辑）→ 精确回滚；再应用一次 → **手打一个字符** → 点「撤销」→ 出现确认提示 → 确认后回退到覆盖前。
4. **门禁反例**：手工构造一个 `code` 编译不过的 replace 块（可在 devtools 里改 store 或临时改 mock）→ 卡片应显示错误且「应用」禁用。
5. **报错预填**：写一段编译不过的代码 → 运行 → 控制台面板出现入口（**等 10 秒仍在**）→ 点击 → agent 输入框被预填、**未发送**；可编辑后手动发送。
6. **多文件**：多文件项目 → 优化 `target` 指定的文件 → 应用后切到该文件且内容被替换；构造 `target` 不存在的块 → 卡片提示且禁用应用。
7. **降级不崩**：`kind` 非法、`options` 为空、`code` 为空 → 块按正文展示，无卡片、无报错。

## 遗留 / 注意事项

- **coze 侧改动需重新发布 agent 才生效**；前端 `npm run dev` 热载即可。
- **门禁只能验「能跑」**（spec §6.1 已知局限）：候选可能「能跑但语义被改」，用前后对比（输出/步数）部分补偿，不做自动语义等价判定。
- **快照撤销会丢弃用户此后的编辑**：UI 必须显式确认（Task 2 的 `confirm`），文案固定为「将丢弃此后的编辑」。
- **快照回退用 `editor.setValue`（`setCode`）**：Monaco 的 `setValue` 可能重置该 model 的 undo 栈，
  即回退后 Ctrl+Z 未必能退回「优化后」那一版。实现时**实测一次**；若确实如此，在确认文案里一并说明（有确认框兜底，可接受）。
- **长文件整份 JSON 转义**（D11）：失败表现是「不出卡」而非崩溃；若线上失败率高，再补「围栏回退解析」（spec §10）。
- **`lastRunError` 生命周期**：目前只在「下次成功运行」时清。若用户反复看同一错误，入口会一直在——如需可加手动关闭。
- **与队友 harness 人在回路对接**：`plan.options` 的 `{goal,label,detail}` 与 `buildGoalPrompt` 是稳定接口，harness 以「用户选项」取代卡片时应直接复用它，不要另起一套。
- spec §7.1 已按 §0.1 的 B1/B2 同步（新建组件 + 合成整文件 edit），两份文档一致，实施时以本计划为准。
