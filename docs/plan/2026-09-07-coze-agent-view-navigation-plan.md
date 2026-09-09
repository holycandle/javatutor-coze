# 执行计划：Coze Agent 视角导航 + 「分析」页合并

> 执行依据：`docs/spec/2026-09-07-coze-agent-view-navigation.md`。
> **已选定方案 A**：导航用独立 `【视角导航】` 文末 JSON 块（复用 `【编辑建议】` 通道），不塞进 `【决策痕迹】`。
> **跨两仓**：`javatutor-coze`（agent prompt）+ `javatutor`（Vue 前端）。本计划在 coze 仓的 `docs/plan/` 下，前端文件
> 以 `javatutor/frontend/...` 标全路径。

## 0. 全局约束（务必遵守）

- **不做任何 git 操作**（不 `git add`/`commit`/`push`/`stash`/`checkout`/`branch`）。读 `git status`/`git diff` 可以。
- **只修改下列文件**。coze 侧不要动 `src/main.py`、`scripts/`、`.coze/`、`src/storage/`、`src/utils/`、`learning/`、`pyproject.toml`。
- 前端 **不触碰** `javatutor/frontend/src/backup-20260807/`（备份副本）。
- 保持现有命名/风格（前端 ESM + `defineStore`；coze 中文 docstring、`_` 私有函数）。
- 写 devlog 到 `javatutor-coze/docs/devlog/2026-09-07-coze-agent-view-navigation.md`（说明已规约+待执行）。

## 1. 改动清单

| # | 仓 | 文件 | 改动 |
|---|---|---|---|
| 1 | coze | `src/graphs/javatutor/prompts.py` | `SYSTEM_PROMPT_MAIN_AGENT` 增加 `【视角导航】` 引导（面板清单 + 何时附卡片） |
| 2 | coze | `src/graphs/javatutor/prompts.py` | `SYSTEM_PROMPT_CRITIC` 忽略结构化块；可校验 panel/sub |
| 3 | coze | `src/graphs/javatutor/prompts.py` | `SYSTEM_PROMPT_REVISE` 保留结构化块 |
| 4 | coze | `src/graphs/javatutor/nodes.py` | `build_final` 加一行注释说明 `【视角导航】` 为受控指令（可选、防剥离） |
| 5 | 前端 | `javatutor/frontend/src/utils/editSuggestion.js` | `parseAssistantMessage` 返回 `{body, edits, nav}`；新增 `【视角导航】` 解析 + `NAV_MARK` |
| 6 | 前端 | `javatutor/frontend/src/utils/decisionTrace.js` | `splitDecisionTrace` 复用 `parseAssistantMessage` 剥掉定向块，避免裸 JSON 进正文 |
| 7 | 前端 | `javatutor/frontend/src/components/NavSuggestionCard.vue` | **新建**：每个 view 一个按钮，点击 `store.navigateTo(panel, sub)` |
| 8 | 前端 | `javatutor/frontend/src/components/AiTutorPanel.vue` | 合并「复杂度+算法→分析」；渲染 NavSuggestionCard；`tabs` 改两 tab |
| 9 | 前端 | `javatutor/frontend/src/stores/player.js` | 删 `multiRightTab`/`switchMultiRightTab`，改 `multiTab`/`switchMultiTab`；新增 `navigateTo` |
| 10 | 前端 | `javatutor/frontend/src/components/MultiFileShell.vue` | 本地 `multiTab` ref → `store.multiTab` 接入（打通多文件导航） |
| 11 | 前端 | 测试 | `editSuggestion.test.js`、`decisionTrace.test.js`、`stores/__tests__/player-righttab.test.js`、`player-mode.test.js` 增补/更新 |
| 12 | 前端 | `javatutor/frontend/src/components/` | `EditSuggestionCard.vue` 仅作参考，不改 |

---

## Task 1：coze — `SYSTEM_PROMPT_MAIN_AGENT` 加导航指令

`javatutor-coze/src/graphs/javatutor/prompts.py`，在 `SYSTEM_PROMPT_MAIN_AGENT`（:123）结尾补一段。建议在 `123` 行「禁止仅凭上下文变量快照直接断言变量值」后追加：

```
当回答有助于用户定位到某个面板时，可在回答末尾（【决策痕迹】之前）追加一个「视角导航块」，前端会渲染成可点击卡片：
【视角导航】
{"views":[{"panel":"tutor","sub":"analysis","label":"分析"}]}

规则：
- panel 取值（单文件）：variables(内存状态)/flow(流程)/datastructure(数据结构)/algorithm(算法库)/tutor(agent)；
- 多文件项目额外支持：callgraph(调用关系)/classdiagram(类图)/structure(结构)；
- sub 仅当 panel 为 tutor 时使用：analysis(分析)/explain(解说)；其他 panel 不要带 sub；
- 仅当某面板能帮用户直接看到相关分析时才附卡，通常 1 个、最多 3 个；
- 每个回答最多一个【视角导航】块；没有合适面板时整个省略，不要发空壳块；
- 导航要融入回答，不要为了导航而发消息。
```

## Task 2：coze — `SYSTEM_PROMPT_CRITIC` 忽略结构化块

`SYSTEM_PROMPT_CRITIC`（:96-106）在末尾「只返回 JSON。」前补一行：

```
判断正文时忽略【视角导航】/【编辑建议】结构化块；可校验【视角导航】的 panel 是否在白名单、sub 是否仅用于 tutor，非法只算轻微问题（不判失败）。
```

## Task 3：coze — `SYSTEM_PROMPT_REVISE` 保留结构化块

`SYSTEM_PROMPT_REVISE`（:108-109）改为：

```
你是回答修订者。根据评审意见修正原回答，保留正确的部分，修正错误引用。
若原回答含【视角导航】/【编辑建议】结构化块，请原样保留（除非评审标记其非法）。
直接输出修订后的完整回答，不要 JSON、不要解释。
```

## Task 4：coze — `build_final` 注释（可选）

`javatutor-coze/src/graphs/javatutor/nodes.py` `build_final`（:412）的 `_strip_leaked_json` 已确认不匹配 `{"views":...}`。在 `_strip_leaked_json`（:358）函数 docstring 或 `build_final` 加一行注释：

```python
# 注意：【视角导航】块（{"views":[...]}）是受控输出指令，不以 intent/pass/tool 开头，
# 不会被本函数剥离，前后端依赖其原样透传。见 docs/spec/2026-09-07-coze-agent-view-navigation.md。
```

非必须，仅作防回归提示。验证：`uv run pytest -q` 仍全绿。

---

## Task 5：前端 — `editSuggestion.js` 解析 `【视角导航】`

**测试先行**：`javatutor/frontend/src/utils/editSuggestion.test.js`（vitest）。既有用例多数解构 `{body, edits}`，不受 `nav` 影响；仅 `空输入安全` 的 `toEqual({ body:'', edits:[] })` 需改为含 `nav`。新增用例：

```js
it('解析视角导航块', () => {
  const raw = '如下\n\n【视角导航】\n{"views":[{"panel":"tutor","sub":"analysis","label":"分析"}]}\n\n【决策痕迹】\n{}'
  const { body, edits, nav } = parseAssistantMessage(raw)
  expect(body).toBe('如下')
  expect(nav.views).toHaveLength(1)
  expect(nav.views[0]).toMatchObject({ panel: 'tutor', sub: 'analysis', label: '分析' })
})

it('导航块 JSON 损坏 → 整块按正文展示', () => {
  const raw = '如下\n\n【视角导航】\n{not json}\n\n【决策痕迹】\n{}'
  const { body, nav } = parseAssistantMessage(raw)
  expect(body).toContain('【视角导航】')
  expect(nav.views).toEqual([])
})

it('导航无有效 views（空数组）→ 整块按正文展示', () => {
  const raw = '如下\n\n【视角导航】\n{"views":[]}\n\n【决策痕迹】\n{}'
  const { body, nav } = parseAssistantMessage(raw)
  expect(body).toContain('【视角导航】')
  expect(nav.views).toEqual([])
})

it('最多保留 3 个 view，过滤缺 panel 项', () => {
  const raw = '如下\n\n【视角导航】\n{"views":[{"panel":"flow"},{"panel":"variables"},{"panel":"tutor","sub":"explain"},{"panel":"datastructure"},{"label":"x"}]}\n\n【决策痕迹】\n{}'
  const { nav } = parseAssistantMessage(raw)
  expect(nav.views).toHaveLength(3)
})

it('编辑建议 + 视角导航同时存在 → 都解析且正文干净', () => {
  const raw = '建议如下\n\n【编辑建议】\n{"edits":[{"old_string":"a","new_string":"b"}]}\n\n【视角导航】\n{"views":[{"panel":"variables"}]}\n\n【决策痕迹】\n{}'
  const { body, edits, nav } = parseAssistantMessage(raw)
  expect(body).toBe('建议如下')
  expect(edits).toHaveLength(1)
  expect(nav.views).toHaveLength(1)
  expect(nav.views[0].panel).toBe('variables')
})
```

**实现**：`javatutor/frontend/src/utils/editSuggestion.js` 重写 `parseAssistantMessage`（其余不变，保留 `planEdits`、`TRACE_MARK`、`EDIT_MARK`）：

```js
const NAV_MARK = '\n【视角导航】'
const STRUCT_MARKS = [EDIT_MARK, NAV_MARK]

// 剥掉 body（已去掉【决策痕迹】）末尾的结构化指令块。为兼容既有语义：
// 从「最后一块」开始：只剥「解析成功且产出 ≥1 个可用项」的块；可用项为空的块按正文保留并停止。
// 这样「编辑建议 JSON 合法但 edits 空」与「导航 views 空」都回退为正文，不静默丢弃。
function extractStructBlocks(body) {
  let text = body
  const edits = []
  const nav = { views: [] }
  let guard = 0
  while (guard++ < 20) {
    let bestMark = null
    let bestIdx = -1
    for (const m of STRUCT_MARKS) {
      const idx = text.lastIndexOf(m)
      if (idx !== -1 && idx > bestIdx) { bestMark = m; bestIdx = idx }
    }
    if (!bestMark) break
    const jsonText = text.slice(bestIdx + bestMark.length).trim()
    let usable = false
    try {
      const parsed = JSON.parse(jsonText)
      if (bestMark === NAV_MARK) {
        const views = (Array.isArray(parsed?.views) ? parsed.views : [])
          .filter((v) => v && typeof v.panel === 'string')
          .slice(0, 3)
          .map((v) => ({
            panel: v.panel,
            sub: typeof v.sub === 'string' ? v.sub : undefined,
            label: typeof v.label === 'string' && v.label ? v.label : '',
          }))
        if (views.length) { nav.views = views; usable = true }
      } else {
        const list = (Array.isArray(parsed?.edits) ? parsed.edits : [])
          .filter((e) => e && typeof e.old_string === 'string' && e.old_string.length > 0 && typeof e.new_string === 'string')
          .map((e) => ({
            title: typeof e.title === 'string' && e.title ? e.title : '代码修改',
            explanation: typeof e.explanation === 'string' ? e.explanation : '',
            old_string: e.old_string,
            new_string: e.new_string,
          }))
        if (list.length) { edits.push(...list); usable = true }
      }
    } catch { /* JSON 解析失败 → 整块按正文展示 */ }
    if (!usable) break
    text = text.slice(0, bestIdx).trimEnd()
  }
  return { body: text.trimEnd(), edits, nav }
}

export function parseAssistantMessage(raw) {
  const text = String(raw || '')
  const traceIdx = text.lastIndexOf(TRACE_MARK)
  const body = traceIdx === -1 ? text : text.slice(0, traceIdx)
  return extractStructBlocks(body)
}
```

> 说明：`extractStructBlocks` 从「最后一块」开始剥，能同时处理「导航在编辑前/后」两种顺序；返回的 `body` 已不含任何结构化块。既有 `编辑建议 JSON 损坏→按正文`、`edits 空→按正文` 语义保持不变（`usable=false` 时 break 且不剥）。更新 `空输入安全` 用例为 `expect(parseAssistantMessage('')).toEqual({ body: '', edits: [], nav: { views: [] } })`。

## Task 6：前端 — `decisionTrace.js` 剥离结构化块

**测试先行**：`javatutor/frontend/src/utils/decisionTrace.test.js` 在 `splitDecisionTrace` describe 增补：

```js
it('剥掉正文末尾的【编辑建议】/【视角导航】块，避免裸 JSON 渲染', () => {
  const text = '正文\n\n【编辑建议】\n{"edits":[{"old_string":"a","new_string":"b"}]}\n\n【视角导航】\n{"views":[{"panel":"variables"}]}\n\n【决策痕迹】\n{"intent":"debug"}'
  const result = splitDecisionTrace(text)
  expect(result.body).toBe('正文')
  expect(result.trace.intent).toBe('debug')
})
```

**实现**：`javatutor/frontend/src/utils/decisionTrace.js` 顶部 `import { parseAssistantMessage } from './editSuggestion.js'`；`splitDecisionTrace` 改为：

```js
export function splitDecisionTrace(text) {
  if (typeof text !== 'string') return { body: text, trace: null }
  const marker = '\n【决策痕迹】\n'
  const idx = text.lastIndexOf(marker)
  if (idx < 0) return { body: text, trace: null }
  const body = text.slice(0, idx).trimEnd()
  const raw = text.slice(idx + marker.length).trim()
  try {
    const trace = JSON.parse(raw)
    // 剥掉 body 末尾的结构化指令块，避免【编辑建议】/【视角导航】以裸 JSON 渲染进正文
    return { body: parseAssistantMessage(body).body, trace }
  } catch {
    return { body: text, trace: null }
  }
}
```

> 无环形依赖（`editSuggestion.js` 不 import `decisionTrace.js`）。查现有 `decisionTrace.test.js` 的 `body` 断言：`'正文'`、`'普通回答'` 均不含结构化块，不受影响。

## Task 7：前端 — 新建 `NavSuggestionCard.vue`

`javatutor/frontend/src/components/NavSuggestionCard.vue`（参考 `EditSuggestionCard.vue` 样式，成块卡片）：

```vue
<template>
  <div class="nav-card">
    <div class="nav-head">前往</div>
    <div class="nav-list">
      <button v-for="v in views" :key="v.panel + (v.sub || '')" class="nav-btn" @click="go(v)">
        {{ label(v) }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { usePlayerStore } from '../stores/player'

const props = defineProps({
  views: { type: Array, default: () => [] },
})
const store = usePlayerStore()

const PANEL_LABELS = {
  variables: '内存状态', flow: '流程', datastructure: '数据结构', algorithm: '算法库',
  tutor: 'agent', callgraph: '调用关系', classdiagram: '类图', structure: '结构',
}
function label(v) { return v.label || PANEL_LABELS[v.panel] || v.panel }
function go(v) { store.navigateTo(v.panel, v.sub) }
</script>

<style scoped>
.nav-card { margin-top: 6px; padding: 8px 10px; border: 1px solid var(--border); background: var(--code-bg); }
.nav-head { font-family: var(--mono); font-size: 11px; color: var(--text-muted); margin-bottom: 6px; }
.nav-list { display: flex; flex-wrap: wrap; gap: 6px; }
.nav-btn { padding: 4px 10px; border: 1px solid var(--accent-border); background: var(--accent-bg); color: var(--primary); font-size: 12px; cursor: pointer; }
.nav-btn:hover { box-shadow: 0 4px 12px var(--accent-bg); }
</style>
```

## Task 8：前端 — `AiTutorPanel.vue` 合并「分析」页 + 渲染导航卡片

`javatutor/frontend/src/components/AiTutorPanel.vue`：

1. `import NavSuggestionCard from './NavSuggestionCard.vue'`。
2. `tabs`（:231-235）改为：
   ```js
   const tabs = [
     { id: 'explain', label: '解说' },
     { id: 'analysis', label: '分析' },
   ]
   ```
3. 把 `complexity` 块（:113-134）与 `algorithm` 块（:137-167）合并为**一个** `analysis` 块（顶层 `v-if="store.activeAiTab === 'analysis'"`），复杂度卡片在上、算法/数据结构标签组在下，共用 `isAnalyzing`/`analysisError`/空态提示：
   ```html
   <div v-if="store.activeAiTab === 'analysis'" class="ai-body">
     <div v-if="store.isAnalyzing" class="ai-loading"><span class="ai-loading-dot" />分析中…</div>
     <div v-else-if="store.analysisError" class="ai-error">{{ store.analysisError }}</div>
     <template v-else-if="store.analysisData?.complexity || store.analysisData?.algorithms || store.analysisData?.dataStructures">
       <div v-if="store.analysisData?.complexity" class="complexity-view">
         <div class="complexity-row">
           <div class="complexity-card"><div class="complexity-label">时间复杂度</div><div class="complexity-value">{{ store.analysisData.complexity.time }}</div><div class="complexity-desc">{{ store.analysisData.complexity.timeExplanation }}</div></div>
           <div class="complexity-card"><div class="complexity-label">空间复杂度</div><div class="complexity-value">{{ store.analysisData.complexity.space }}</div><div class="complexity-desc">{{ store.analysisData.complexity.spaceExplanation }}</div></div>
         </div>
       </div>
       <div v-if="store.analysisData?.algorithms?.length" class="tag-group">
         <div class="tag-group-label">算法</div>
         <div class="tag-row"><button v-for="algo in store.analysisData.algorithms" :key="algo.name" class="ai-tag" :class="tagClass(algo.category)" @click="explainTag(algo.name)" title="点击查看详细解说">{{ algo.name }}</button></div>
       </div>
       <div v-if="store.analysisData?.dataStructures?.length" class="tag-group">
         <div class="tag-group-label">数据结构</div>
         <div class="tag-row"><button v-for="ds in store.analysisData.dataStructures" :key="ds.name" class="ai-tag" :class="tagClass(ds.category)" @click="explainTag(ds.name)" title="点击查看详细解说">{{ ds.name }}</button></div>
       </div>
     </template>
     <div v-else class="ai-hint">运行代码后自动分析。</div>
   </div>
   ```
   （删除原 `complexity`/`algorithm` 两个 `v-if` 块。）`explainTag`（:285）与 `tagClass` 保留。
4. 在 assistant 气泡 `EditSuggestionCard` 旁（:58-61）加导航卡片：
   ```html
   <NavSuggestionCard v-if="parsedMessages[i].nav.views.length && !store.isExplaining" :views="parsedMessages[i].nav.views" />
   ```
   `parsedMessages` computed（:189-193）已由 `parseAssistantMessage` 返回 `nav`——其返回值现在含 `nav`，无需改该 computed。

## Task 9：前端 — `player.js` 导航动作 + 多文件 tab 上台

`javatutor/frontend/src/stores/player.js`：

1. state `multiRightTab: 'variables'`（:59）→ 改为 `multiTab: 'datastructure'`。
2. `switchMultiRightTab`（:505-508）→ 替换为：
   ```js
   switchMultiTab(tab) {
     const allowed = ['variables', 'flow', 'datastructure', 'callgraph', 'classdiagram', 'structure', 'algorithm', 'tutor']
     if (allowed.includes(tab)) this.multiTab = tab
   },
   ```
3. 新增 `navigateTo` action：
   ```js
   navigateTo(panel, sub) {
     if (panel === 'tutor' && sub) this.activeAiTab = sub
     if (this.mode === 'multi') {
       this.switchMultiTab(panel)
     } else {
       this.switchRightTab(panel)
     }
   },
   ```
   > `switchRightTab` 已含白名单 `['variables','flow','datastructure','algorithm','tutor']`；`activeAiTab` 是全局的，内嵌与浮动面板一起切——已知、可接受。

**测试先行**：`javatutor/frontend/src/stores/__tests__/player-righttab.test.js` 增补：

```js
it('navigateTo 单文件切 rightTab（含 panel=tutor 设 sub）', () => {
  const s = usePlayerStore()
  s.navigateTo('tutor', 'analysis')
  expect(s.rightTab).toBe('tutor')
  expect(s.activeAiTab).toBe('analysis')
  s.navigateTo('variables')
  expect(s.rightTab).toBe('variables')
})

it('navigateTo 多文件走 multiTab', () => {
  const s = usePlayerStore()
  s.mode = 'multi'
  s.navigateTo('callgraph')
  expect(s.multiTab).toBe('callgraph')
})
```

## Task 10：前端 — `MultiFileShell.vue` 接入 store.multiTab

`javatutor/frontend/src/components/MultiFileShell.vue`：

1. 删 `const multiTab = ref('datastructure')`（:142）。
2. 模板里所有 `multiTab` → `store.multiTab`（:67-106 的 `:class`/`v-show`）。
3. `switchTab(tab)`（:159-161）→ `store.switchMultiTab(tab)`。
4. `rightGroup` computed（:155）→ `GROUP_OF_TAB[store.multiTab] || 'observe'`。
5. `switchGroup`（:156-158）→ `if (rightGroup.value !== group) store.switchMultiTab(GROUP_DEFAULT_TAB[group])`。

> `rightGroup`、`GROUP_OF_TAB`、`GROUP_DEFAULT_TAB` 保留；`reactive` 不再需要该 ref。若 `ref` 仍被其它处用到（如 `right-card-body` 的 `body-fill`），统一改 `store.multiTab`。

## Task 11：前端 — 测试汇总

- `editSuggestion.test.js`：更新 `空输入安全`；新增 Task 5 的解析/回退/多块用例。
- `decisionTrace.test.js`：新增 Task 6 的剥离用例。
- `stores/__tests__/player-righttab.test.js`：新增 Task 9 用例。`player-mode.test.js` 无需改（`switchMultiTab` 不涉 mode）。
- `stores/__tests__/player-mode.test.js` 若引用 `multiRightTab` 需同步（当前未见，改前 grep 确认 `multiRightTab`/`switchMultiRightTab` 无其它引用）。

## Task 12：前端 — 跑测试 + devlog

- 前端：在 `javatutor/frontend` 下 `npm run test`（vitest）全绿。
- coze：`uv run pytest -q` 全绿（prompt 变更不破坏契约）。

---

## 验证清单（按序）

1. **前端单测**：`javatutor/frontend` `npm run test` 全绿（含新增用例）。
2. **coze 单测**：`javatutor-coze` `uv run pytest -q` 全绿。
3. **手验（dev）**：`npm run dev` 单文件跑冒泡/插入排序 → agent 问「把分析打开」→ 回答尾部出现 `【视角导航】` 卡片 → 点「分析」切到 agent 面板「分析」页；点「内存状态」切到 Observe/内存状态。
4. **多文件手验**：多文件项目进 agent，问「看类图」→ 卡片指向 `classdiagram`，点击后右侧切到类图。
5. **无回归**：既有 `【决策痕迹】`、`【编辑建议】` 行为不变；结构化块不呈裸 JSON；`dist` 相关不涉及（跑 dev）。

## 遗留 / 注意事项

- 本次改动后 **coze 侧需重新发布 agent** 才生效（prompt 变更）+ 前端 `npm run dev` 热载。
- `navigateTo` 在「浮动 AI 面板」与「右侧内嵌 AI 面板」都会因 `activeAiTab` 全局一起切换——已知、可接受。
- 冒泡排序→「插入排序」误判队友在修，本计划不处理。
- 右下角算法教程 toast 仅确认「以用户点击为准」，本计划不改。
- `【视角导航】` 块在 `build_final` 中不会被 `_strip_leaked_json` 误删（已验证只匹配 `intent`/`pass`/`tool` 开头 JSON）。
