# 执行计划：优化方向绑定（多选 + 硬约束）与报错入口全局化（修复）

> 依据：2026-09-10 联调发现的两处问题 + 同日 `/grilling` 收敛（§1 即决策记录）。
> **跨两仓**：前端 `javatutor/frontend` + coze `javatutor-coze`。后端**无需改动**。
> 关联：`docs/spec/2026-09-10-coze-agent-code-optimization.md`（本计划**部分改写**其 §4.1/§4.4/§5/§8，见 Task 14）。
> 前置实现：`docs/devlog/2026-09-10-coze-agent-code-optimization.md`；review 见 `docs/reviews/2026-09-10-coze-agent-code-optimization-review.md`。

## 0. 全局约束（务必遵守）

- **不做任何 git 操作**（不 `git add`/`commit`/`push`/`stash`/`checkout`/`branch`）。读 `git status`/`git diff` 可以。
- 前端**不触碰** `javatutor/frontend/src/backup-20260807/`（备份副本）。
- 基线（改动前先跑一遍确认）：前端 `npx vitest run` = **25 文件 / 291 用例**；coze `uv run pytest -q` = **226 通过**。
- **向后兼容是硬要求**：`kind` 缺失或 `kind:"patch"` 时行为与现状完全一致；`kind:"options"` 的**块形态（JSON schema）本计划不变**——「多选」是纯前端交互变化，agent 侧仍只需产出 2–3 个 option。
- 保持现有命名/风格（前端 ESM + `defineStore`；coze 中文 docstring、`_` 私有函数、守卫测试放 `tests/`）。
- 新增纯函数一律放 `utils/` 并配 vitest 用例（本仓**无 DOM 测试环境**，组件逻辑只能手验——请把可抽的判定都抽出来）。

### 0.1 诊断（为什么这么改；已核实，勿再重开）

**问题 1「选了 A 却得到 A+B」不是随机，是可预测的：**

| # | 事实 | 位置 |
|---|---|---|
| D1 | 第 2 轮提问**没有排他约束**：模板是「以「X」为**优先**优化当前代码」——「优先」是软偏好，不是范围。 | `utils/editSuggestion.js buildGoalPrompt` |
| D2 | guidance 只要求「goal 必须等于用户选定」，**没有**「只做该方向、不得顺带做其他方向」这一条。 | `prompting/optimization.py` |
| D3 | `/api/ai/chat` **不携带任何对话历史**；唯一的跨轮载体是 coze 记忆，而 `save_session` 存的是 `问答：<问题> → <回答前 200 字>`（第 1 轮那份 options JSON 在回答末尾，基本落在截断之外）。 | `CozeAIController.chat`；`nodes.py:511`、`nodes.py:497` |
| D4 | `sessionId = Integer.toHexString(code.hashCode())`（代码哈希）。第 1↔2 轮代码未变 → 同一 session，但记忆是被检索回来的、带截断的片段，**不保证原文**。 | `CozeAIController.chat` |
| D5 | 方案卡**自己握着第 1 轮的全部 options**（`props.plan.options`）→「显式排除未选项」前端做得到，不需要动后端/协议。 | `OptimizationCard.vue` |

结论：**只有「显式白名单 + 显式黑名单」能把选择变成约束**；「多选」解决的是另一半（用户无法表达组合）。两者一起改才闭环。

**问题 2「入口在控制台，用户可能不在该页」：**

| # | 事实 | 位置 |
|---|---|---|
| D6 | 入口在 `variables`（内存状态）pane 的控制台内，与 agent 面板（`tutor`）**互斥可见**。 | `SingleFileShell.vue:89-92`、`MultiFileShell.vue:84-87` |
| D7 | `GlobalStatus` 是 App.vue 级的 fixed 覆盖层（`top:64px; z-index:1100`），**任何页面都可见**，是唯一正确的挂载点。 | `App.vue:9`、`GlobalStatus.vue` |
| D8 | `watch(error)` 在 6 秒后**主动置 `store.error = null`**——「常驻」必须改这段定时逻辑。 | `GlobalStatus.vue:28-40` |
| D9 | 运行失败会**同时**写 `store.error` 与 `store.lastRunError`（且两者同文），可据此把「运行类错误」与「其它错误（AI 流错误等）」分流。 | `player.js:131/168/190` |

> 注：review 的 R1（点击后切面板）与 R2（快照卡片自持）**已修复并提交**（前端 `80f3136`），本计划只在其上追加 F5 的聚焦。

## 1. 已收敛的决策

| # | 决策 | 说明 |
|---|---|---|
| **F1** | 方案卡改**多选勾选** | 每行一个方向（沿用 `label`/`detail`），勾 ≥1 项后点提交按钮。**取代**原 D4 的「一点即生成」——多选必然需要一个提交动作，这是有意的行为变更。 |
| **F2** | 第 2 轮提问 = **硬约束 + 显式排除未选项** | 白名单 = 所选项（用其 `label`/`detail`），黑名单 = **同一张方案卡里未被勾选的选项**（逐条列 `label` + `detail`）。黑名单只取同一张卡的未选项，不罗列整个闭集（否则会出现「不要做正确性优化」这种荒谬约束）。 |
| **F3** | `GOALS` 闭集新增 **`comprehensive`（综合）** | 勾 1 项 → `replace.goal` = 该项；勾 ≥2 项 → 提问逐条列出各方向，agent 的 `replace.goal` 填 `comprehensive`。方案卡第 1 轮的 options **不产出** `comprehensive`（它只用于第 2 轮）。 |
| **F4** | 报错入口**搬到全局红色弹窗**，运行类错误**不再自动消失** | 可手动关闭；下次成功运行时随 `store.error = null` 一并消失。**控制台入口移除**（避免双入口）。 |
| **F5** | 点击 = 预填草稿 + 切到 agent 面板 + **聚焦输入框**，**不发送** | 发送权仍在用户手里（延续 D9「代写提问」的语义）。 |

---

## 2. 改动清单

| # | 仓 | 文件 | 改动 |
|---|---|---|---|
| 1 | 前端 | `javatutor/frontend/src/utils/editSuggestion.js` | `GOALS` 加 `comprehensive`；`buildGoalPrompt` 改签名（所选 + 未选） |
| 2 | 前端 | `javatutor/frontend/src/utils/editSuggestion.test.js` | 新模板用例（单项/多项/排除项/无 detail/无未选项/空） |
| 3 | 前端 | `javatutor/frontend/src/components/OptimizationCard.vue` | options 分支改多选（勾选态 + 提交按钮） |
| 4 | 前端 | `javatutor/frontend/src/stores/player.js` | `askGoalOptimization` 改收数组；新增 `chatFocusNonce` / `focusChatWithDraft` / `clearRunError` |
| 5 | 前端 | `javatutor/frontend/src/utils/errorEntry.js` | **新建**：`isRunError()` 等纯函数 |
| 6 | 前端 | `javatutor/frontend/src/utils/errorEntry.test.js` | **新建** |
| 7 | 前端 | `javatutor/frontend/src/components/GlobalStatus.vue` | 入口按钮 + 时长分流 |
| 8 | 前端 | `javatutor/frontend/src/components/ConsoleOutput.vue` | **移除** `console-error-bar` |
| 9 | 前端 | `javatutor/frontend/src/components/AiTutorPanel.vue` | 输入框 `ref` + 聚焦 watcher |
| 10 | coze | `src/graphs/javatutor/prompting/optimization.py` | 加「方向硬约束」段 + `comprehensive` 说明 |
| 11 | coze | `src/graphs/javatutor/prompting/main_fewshots.py` | 更新第 2 轮样例（含排除项）+ 新增多方向样例 |
| 12 | coze | `tests/test_optimization_guidance.py` | 守卫：硬约束文案、`comprehensive` 在闭集、样例合法 |
| 13 | 两仓 | `docs/devlog/2026-09-10-coze-agent-optimization-goal-binding-fix.md` | **新建**实施记录 |
| 14 | coze | `docs/spec/2026-09-10-coze-agent-code-optimization.md` | 同步 §4.1/§4.4/§5/§8 与 `docs/spec/2026-08-10-coze-agent-interface.md` §2.2 |

---

# Phase A — 前端：方向绑定

## Task 1：`utils/editSuggestion.js`（**测试先行**）

先加测试（`editSuggestion.test.js`，替换现有 `describe('buildGoalPrompt')` 三条用例）：

```js
describe('buildGoalPrompt（F1/F2/F3）', () => {
  const P = { goal: 'performance', label: '以性能为先', detail: '用哈希表把嵌套循环降为 O(n)' }
  const M = { goal: 'memory', label: '以空间优化为先', detail: '用左右边界索引限定原数组范围' }

  it('单项：只做该方向', () => {
    expect(buildGoalPrompt([P])).toBe(
      '只做「以性能为先」方向的优化，具体要求：用哈希表把嵌套循环降为 O(n)。请给出优化后的完整代码。',
    )
  })

  it('单项 + 排除未选项（同一张卡的其它 option）', () => {
    expect(buildGoalPrompt([P], [M])).toBe(
      '只做「以性能为先」方向的优化，具体要求：用哈希表把嵌套循环降为 O(n)。'
      + '不要顺带做其他方向的改动（例如：「以空间优化为先」：用左右边界索引限定原数组范围）。'
      + '请给出优化后的完整代码。',
    )
  })

  it('多项：逐条列出（勾 ≥2 项 → goal 记 comprehensive）', () => {
    expect(buildGoalPrompt([P, M])).toBe(
      '只做以下方向的优化：①「以性能为先」：用哈希表把嵌套循环降为 O(n)；'
      + '②「以空间优化为先」：用左右边界索引限定原数组范围。'
      + '请给出优化后的完整代码。',
    )
  })

  it('多项 + 排除未选项', () => {
    const R = { goal: 'readability', label: '以可读性为先', detail: '' }
    expect(buildGoalPrompt([P, M], [R])).toContain('不要顺带做其他方向的改动（例如：「以可读性为先」）')
  })

  it('无 detail / label 缺省回落中文规范名', () => {
    expect(buildGoalPrompt([{ goal: 'style', label: '' }])).toContain('只做「规范」方向的优化')
    expect(buildGoalPrompt([{ goal: 'style', label: '' }])).not.toContain('具体要求')
  })

  it('空选择 → 空串（调用方不得发送）', () => {
    expect(buildGoalPrompt([])).toBe('')
  })

  it('GOALS 含 comprehensive（与 coze 侧闭集一致）', () => {
    expect(Object.keys(GOALS)).toEqual([
      'performance', 'readability', 'memory', 'style', 'correctness', 'comprehensive',
    ])
  })
})
```

实现：

```js
export const GOALS = {
  performance: '性能',
  readability: '可读性',
  memory: '内存',
  style: '规范',
  correctness: '正确性',
  comprehensive: '综合',   // F3：仅用于第 2 轮 replace 的 goal（勾 ≥2 个方向时）
}

const ONE = ['①', '②', '③']   // 顺带支持 3 项（options 上限为 3）

/**
 * 拼「选定优化方向」后的第 2 轮提问（F2：白名单 + 黑名单）。
 * @param {Array<{goal,label,detail}>} selected 已勾选的方向（≥1 项）
 * @param {Array<{goal,label,detail}>} [excluded] 同一张方案卡里未被勾选的选项
 * @returns {string} 空选择时返回 ''
 */
export function buildGoalPrompt(selected, excluded = []) {
  const list = Array.isArray(selected) ? selected.filter(Boolean) : []
  if (!list.length) return ''
  const name = (o) => o.label || GOALS[o.goal] || o.goal

  let head
  if (list.length === 1) {
    const o = list[0]
    head = `只做「${name(o)}」方向的优化` + (o.detail ? `，具体要求：${o.detail}` : '')
  } else {
    const items = list
      .map((o, i) => `${ONE[i]}「${name(o)}」${o.detail ? `：${o.detail}` : ''}`)
      .join('；')
    head = `只做以下方向的优化：${items}`
  }

  const bad = (Array.isArray(excluded) ? excluded : []).filter(Boolean)
  const tail = bad.length
    ? `。不要顺带做其他方向的改动（例如：${bad.map((o) => `「${name(o)}」${o.detail ? `：${o.detail}` : ''}`).join('；')}）`
    : ''

  return `${head}${tail}。请给出优化后的完整代码。`
}
```

> `normalizePlan` 的 options 分支**不改**（`comprehensive` 进了闭集后，agent 万一在 options 里用它也只会被当成一个普通标签，无害）。
> `replace` 分支**不改**（`comprehensive` 自动通过 `GOALS[parsed.goal]` 校验）。

## Task 2：`OptimizationCard.vue` — options 分支改多选

- 新增局部状态 `const selected = ref([])`（存 goal 字符串数组）。
- 每个 option 渲染成**可勾选行**：`<button class="oc-option" :class="{ checked: selected.includes(o.goal) }" @click="toggle(o)">`，行内左侧加一个方框（勾选态显示 `✓`），沿用现有 `oc-option-label` / `oc-option-detail` 样式。
- 底部提交按钮：`<button class="oc-btn oc-apply" :disabled="store.isExplaining || !selected.length" @click="submit">{{ submitLabel }}</button>`，
  `submitLabel = {0:'请先勾选方向',1:'只优化「X」',2:'综合优化 2 个方向'}[…]`（0/1/≥2 三态；≥2 时显示项数）。再给一个「全选」小按钮（可选，成本极低）。
- `submit()`：
  ```js
  function submit() {
    const sel = props.plan.options.filter((o) => selected.value.includes(o.goal))
    const rest = props.plan.options.filter((o) => !selected.value.includes(o.goal))
    store.askGoalOptimization(sel, rest, props.plan.target)
  }
  ```
- **不改** replace 分支、门禁、apply、undo、`onMounted`。

## Task 3：`stores/player.js` — `askGoalOptimization` 改签名

```js
/**
 * 优化卡「方案卡」提交：按所选方向（F2 白名单）+ 未选项（F2 黑名单）拼提问并发起新一轮对话。
 * @param {Array<{goal,label,detail}>} selected 已勾选方向（≥1）
 * @param {Array<{goal,label,detail}>} excluded 同一张卡的未选项
 */
async askGoalOptimization(selected, excluded, target) {
  const q = buildGoalPrompt(selected, excluded)
  if (!q) return
  const suffix = this.mode === 'multi' && target ? `（目标文件：${target}）` : ''
  await this.askQuestion(`${q}${suffix}`)
}
```

同步改 `stores/__tests__/player-optimization.test.js` 的两条 `askGoalOptimization` 用例（新签名 + 新文案，含多文件后缀用例）。

## Task 4：`utils/errorEntry.js`（**新建**，纯函数）

```js
/** 判断 toast 上的这条错误是否为「运行类错误」（同时写进了 lastRunError，且同文）。 */
export function isRunError(error, lastRunError) {
  return !!lastRunError && !!error && lastRunError.message === error
}

/** 运行类错误常驻（入口可点），其它错误 6 秒自动消失。 */
export const TRANSIENT_ERROR_MS = 6000
export function shouldAutoDismiss(error, lastRunError) {
  return !isRunError(error, lastRunError)
}

/** 报错入口要预填的提问文本（只预填、不发送）。 */
export function buildFixPrompt(message) {
  return `我的代码运行报错了，请帮我看看怎么修正：\n${message || ''}`
}
```

用例覆盖：同文 → `true`；`lastRunError` 为空 → `false`；文本不同（AI 流错误）→ `false`；`null` 双方 → `false`；`buildFixPrompt` 文案与空 message。

## Task 5：`GlobalStatus.vue` — 入口搬到全局弹窗（F4/F5）

- `.error-inner` 内、`×` 左侧加按钮，**仅当 `store.lastRunError` 存在**时渲染：
  `<button class="fix-btn" @click="prefillFix">让 agent 帮我看看</button>`
- 定时逻辑改为（`isRunError` 从 `utils/errorEntry.js` 引入）：
  ```js
  watch(error, (val) => {
    if (!val) { visibleError.value = false; if (timer) { clearTimeout(timer); timer = null } return }
    visibleError.value = true
    if (timer) { clearTimeout(timer); timer = null }
    // 运行类错误常驻：直到手动关闭（close）或下次运行把 store.error 置空
    if (!shouldAutoDismiss(val, store.lastRunError)) return
    timer = setTimeout(() => { visibleError.value = false; store.error = null; timer = null }, TRANSIENT_ERROR_MS)
  })
  ```
- `close()` 追加 `store.clearRunError()`（关闭即撤下入口；再次运行失败会重新出现）。
- 样式：`.fix-btn` 沿用控制台那个按钮的观感（`--accent-bg` 底 + `--accent-border` 边 + mono 小字），不要新增配色体系。
- **`store.error` 的既有语义不变**（成功运行会在 `runCode`/`runProject` 开头置 `null`，弹窗随之消失）。

## Task 6：`player.js` — `clearRunError` / `focusChatWithDraft` / `chatFocusNonce`

```js
chatFocusNonce: 0,          // state：+1 即请求 agent 输入框聚焦（跨组件，参照 store.knowledgeNav 的先例）

/** 解析后入口：预填草稿 + 切到 agent 面板 + 请求聚焦（F5，均不发送）。 */
focusChatWithDraft(text) {
  this.chatDraft = text
  this.navigateTo('tutor')
  this.chatFocusNonce += 1
},

/** 手动关闭报错弹窗时一并撤下入口。 */
clearRunError() {
  this.lastRunError = null
},
```

## Task 7：`ConsoleOutput.vue` — 移除入口（F4 单入口）

- 删除 `.console-error-bar` 模板块、`shortError` computed、`prefillFix()` 及对应样式。
- **保留** `store.lastRunError` 状态本身（GlobalStatus 在用）；`ConsoleOutput.vue` 恢复为只渲染输出。

## Task 8：`AiTutorPanel.vue` — 聚焦

```js
const inputRef = ref(null)

/** 只有当前可见的那一个实例才聚焦（单文件模式下内嵌 + 悬浮可能同时挂载）。 */
const isVisibleInstance = computed(() =>
  props.embedded
    ? (store.mode === 'multi' ? store.multiTab === 'tutor' : store.rightTab === 'tutor')
    : store.explainExpanded,
)

watch(() => store.chatFocusNonce, async () => {
  await nextTick()
  if (isVisibleInstance.value) inputRef.value?.focus()
})
```

模板 `<input ref="inputRef" v-model="store.chatDraft" …>`。
调用点改为 `store.focusChatWithDraft(buildFixPrompt(store.lastRunError?.message))`（GlobalStatus 内）。

---

# Phase B — coze：引导与守卫

## Task 9：`prompting/optimization.py`

1. `GOALS` 加 `"comprehensive": "综合"`，并在 docstring 注明「comprehensive 仅用于第二步 replace 的 goal」。
2. **第一步**段追加两行约束：
   - `options 的 goal 只取下列 5 个方向（不含 comprehensive）：{5 个方向}`；
   - `每个 option 必须是一个**独立可组合**的方向，不要在一个 option 里塞进多个方向`（组合交给用户勾选）。
3. **新增「第二步的方向约束（硬要求）」段**（原文照抄，测试按此断言）：

```text
**第二步的方向约束（硬要求）**
用户提问里已经写明「只做」哪些方向、以及「不要顺带做」哪些方向——那是用户在方案卡上勾选的结果：
- **只做所列方向**；未列入的方向一律不得改造，即使你认为它们也能优化，也不得顺手改（可在正文里提一句「另外还有 X 可优化」，但代码里不许动）。
- 用户列了 **≥2 个方向**时，`goal` 填 `comprehensive`，并在 `rationale` 里**分别**说明每个方向各改了什么。
- 用户只列 **1 个方向**时，`goal` 填该方向，且不得混入其它方向的改动。
```

## Task 10：`prompting/main_fewshots.py`

- **改**现有第 2 轮样例：`question` 换成新模板形态（含「只做…」+「不要顺带做其他方向的改动（例如：…）」），`answer` 的 replace 块 `goal` 保持 `performance`，`rationale` 与「只做性能」一致。
- **新增**一条多方向样例：question 为「只做以下方向的优化：①「以性能为先」…；②「以空间优化为先」…」，answer 的 replace 块 `goal: "comprehensive"`，`rationale` 分别说明两个方向。
- 沿用 `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` 生成块；**块必须是回答的最后内容**（`tests/test_panel_sync.py::test_main_few_shots_valid` 与 `test_optimization_guidance.py::_extract_block_json` 都依赖这一点）。
- 不要动既有导航样例（`subTab`/`categoryId`/`anchorId`/「测试模式」/「不附导航卡」等断言仍在 `test_panel_sync.py` 里生效）。

## Task 11：`tests/test_optimization_guidance.py` 守卫

新增（沿用现有 `FRONTEND_GOALS` 与 `_extract_block_json` 的写法）：

```python
def test_guidance_states_hard_direction_constraint():
    text = render_optimization_guidance()
    assert "只做所列方向" in text
    assert "不得改造" in text
    assert "comprehensive" in text

def test_goal_enum_includes_comprehensive():
    assert GOALS["comprehensive"] == "综合"
    assert len(GOALS) == 6

def test_fewshots_second_round_states_exclusions():
    for shot in get_main_few_shots():
        if "【编辑建议】" in shot and '"kind":"replace"' in shot:
            assert "不要顺带做其他方向的改动" in shot or "只做以下方向" in shot
```

并让既有 `test_main_fewshots_optimization_samples_valid` 覆盖新增的多方向样例（`goal == "comprehensive"` 时必须通过闭集校验）。

## Task 12：文档同步（**必须**，否则 spec 与实现再次脱节）

- `docs/spec/2026-09-10-coze-agent-code-optimization.md`：
  - §4.1 `options`：补「前端渲染为**多选**，勾选后提交；提交时按 F2 拼提问」。
  - §4.4：闭集表加一行 `comprehensive` | 综合 | **仅第 2 轮 replace 使用（勾 ≥2 方向）**；模板替换为 F2 的新模板（白名单 + 黑名单 + 逐条列出）。
  - §5：入口位置从「控制台面板」改为「**全局红色弹窗（`GlobalStatus`）**，运行类错误不再 6 秒自动消失，可手动关闭」；点击行为补「切到 agent 面板 + 聚焦」。
  - §8 验收 6 改写成「任意页面运行失败 → 红色弹窗常驻含入口 → 点击后切到 agent 面板、输入框已预填且聚焦、未发送」。
- `docs/spec/2026-08-10-coze-agent-interface.md` §2.2：`goal` 闭集补 `comprehensive`，并注明「第 2 轮多方向时使用」。
- `docs/reviews/2026-09-10-coze-agent-code-optimization-review.md`：R1/R2 标注**已修复**（前端 `80f3136`），并注明「问题 2 是 R1 的加强版，已由本计划 F4 覆盖」。

---

# Phase C — 验证

## Task 13：跑测试 + devlog

```bash
cd javatutor/frontend && npx vitest run          # 期望 ≥291 + 新增用例，全绿
cd javatutor-coze && uv run pytest -q            # 期望 ≥226 + 新增守卫
cd javatutor-coze && python scripts/sync_panel_manifest.py   # exit=0（本计划不动 manifest）
cd javatutor/frontend && npm run build           # SFC 编译无误
```

devlog：`docs/devlog/2026-09-10-coze-agent-optimization-goal-binding-fix.md`（改动清单、决策 F1–F5、偏差、测试数、已知局限、手验清单）。

## 手验清单（`npm run dev`；coze 侧需**重新发布 agent**）

1. 问「可以优化吗」→ 方案卡出现 2–3 个方向，**可多选**（点行切换勾选态），未勾选时提交按钮禁用。
2. 勾**一个**方向提交 → 消息列表出现模板提问，正文含「只做「X」方向的优化」+「不要顺带做其他方向的改动（例如：「Y」：…）」。
3. 第 2 轮回答的 replace 卡：`目标` 显示该方向；**应用后的代码不包含未选方向的改动**（对照第 1 轮 options 的 detail 逐条核）。
4. 勾**两个**方向提交 → 提问逐条列出①②；第 2 轮 replace 卡 `目标` 显示「综合」，`rationale` 分别说明两个方向。
5. 构造一次运行失败（少个分号）→ **红色弹窗常驻**，10 秒后仍在，含「让 agent 帮我看看」。
6. 停留任意 tab（如流程/数据结构）点击该按钮 → 切到 agent 面板、输入框已预填、光标在末尾、**未发送**；点弹窗 `×` → 弹窗与入口消失。
7. 再跑一次成功的代码 → 弹窗自动消失。
8. 回归：`kind` 缺失 / `kind:"patch"` 的编辑建议卡行为与改动前**完全一致**；`replace` 卡门禁/应用/撤销不变。

## 遗留 / 注意事项

- **方案卡从「一点即生成」变成「勾选 + 提交」**（有意变更，已在 F1 记录；spec §4.3 时序图的那句「点一下即生成，不再多一次点击」需在 Task 12 一并改掉）。
- **`comprehensive` 是可观测性妥协**：它不校验代码真的覆盖了所列方向，只是把「多方向」记进 `replace.goal` 供展示与统计。若将来要强校验，只能靠人工/评测。
- **coze 记忆仍是第 2 轮的次要来源**（`nodes.py:511` 的 200 字截断）：本计划让前端把约束写进提问，**不依赖**记忆，因此不要顺手去改记忆策略。
- 若评审认为「未选项里出现荒谬条目（如把明显 bug 归入某方向）」有风险：黑名单只列**同一张方案卡的未选项**，范围可控；真出问题再考虑只列 `label` 不列 `detail`。
