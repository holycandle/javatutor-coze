# Coze Agent 视角导航 健壮性修复（裸 JSON / 算法库细化 / 非面板流程知识）Plan

> 审查/复核自：`docs/reviews/2026-09-08-coze-agent-view-navigation-fix-review.md`（P1–P3 联调用例已过）。
> 本 plan 针对 2026-09-09 联调新报的 3 处问题。对应 spec：`docs/spec/2026-09-07-coze-agent-view-navigation.md` §3.1.1 / §9。

## 一、问题（2026-09-09 联调）

| # | 现象 | 截图 |
|---|---|---|
| 1 | 「后序遍历的知识在哪看」的回答把 `【视角导航】` 的**原始 JSON 渲染进了正文**，卡无效 | 图 P1 |
| 2 | 「算法库的细化标签」粒度只到「算法库」，无法定位到「算法库-算法知识-树（堆）」等更细分类/锚点 | 图 P1 主体 |
| 3 | 「怎么打开测试模式」agent 称「没有测试模式入口」，并**误加导航卡**（查看内存变量/查看执行流程）；实际应直接给操作步骤 | 图 P2 |

## 二、根因

### 问题 1：结构块被当作正文（前端解析脆弱）
`frontend/src/utils/editSuggestion.js` 的 `extractStructBlocks` 假设结构块是**正文最后一段**：
```
const jsonText = text.slice(bestIdx + bestMark.length).trim()   // 标记之后的全部
const parsed = JSON.parse(jsonText)
```
当 agent 在块**之后**又写了正文（P1 里块后跟了「我已经明确回答了…」），`trim()` 后的切片仍含尾部文字 →
`JSON.parse` 抛错 → `usable=false` → 块未剥离、按正文渲染，于是裸 JSON 上屏。

**本质**：解析依赖「块在末尾」的约定，而对 agent 输出不作防御；块位置略有偏移即失败。

### 问题 2：算法库无法细化（schema 耦合 + 缺目录 + 示例 anchorId 错误）
- **schema 耦合**：P1 中 agent 输出 `{"panel":"algorithm","sub":"knowledge","categoryId":"tree","anchorId":"post-order-traversal"}`——
  `sub`/`categoryId`/`anchorId` 在**顶层**，而契约要求放进 `algo:{subTab,categoryId,anchorId}`。前端 `normalizeAlgo(v.algo)` 见 `v.algo` 为
  undefined → 丢弃全部定位 → 只落到「算法库」默认（knowledge，无分类）。这正是「只到算法库」的直接原因。
- **缺目录**：agent 只被告知示例 `categoryId:"tree"`，不知道 7 个分类与各分类锚点的**合法 id 全集**，无法可靠挑中树/堆等。
- **示例 anchorId 错误**：spec §3.1.1 示例用 `anchorId:"post-order-traversal"`，但算法知识页的锚点 id 是**中文全称**
  （`algo-knowledge/index.json` 里 `{id:"后序遍历"}`，title 才是「后序」）。按示例生成会导致 `scrollToAnchor` 找不到元素（不崩，定位失败）。
- **manifest 里 `algorithmLibrary.categories` 是死数据且不全**：`ui-panel-manifest.json` 的 `categories` 只列 5 类、无锚点，
  且前端代码（`uiPanelManifest.js`）只消费 `subTabs`，coze `panels.py` 也只读 `subTabs`。真实目录在 `frontend/src/assets/algo-knowledge/index.json`。

### 问题 3：导航边界不清晰 + 测试模式缺知识（内核不是「是否流程问题」）
- **根因**：agent 没有清晰的**导航边界**——它不知道自己「只能」用固定那 8 块面板导航，更不知道「测试模式」这类主题**根本不在可导航集合里**。
  于是面对「怎么打开测试模式」时，它从能想到的面板里**硬凑**（查看内存变量 / 查看执行流程），而不是正确地「无卡、只给步骤」。
  所以问题不在「它能否识别这是流程问题」，而在**边界本身没立清楚**；「流程问题不附卡」只是边界清晰后的自然推论，不应对单例过拟合。
- **缺知识**：本体只描述 INSPECT 面板/字段映射，**没有「运行 / 测试模式 / 查看输出」的使用流程**，主 Agent 拿不到该知识，于是断言「没有测试模式入口」——
  但前端明确有测试模式（`TestCasePanel.vue`、`store.testMode`、`runCode` 带 `mode:'test'`）。

## 三、修复方案

### A. 前端（javatutor/frontend）

**A1. 结构块改为「平衡 JSON 提取」，与块后正文解耦**（修问题 1）
`src/utils/editSuggestion.js` 用 `parseJsonAt` 定位标记后紧邻 JSON 值的起止，只 `JSON.parse` 该子串；块后正文原样保留在 body。
```js
// 从 text[start]（跳过空白）找平衡的 {…}/[…]；返回 [end, jsonStr]；找不到返回 null。
function parseJsonAt(text, start) {
  while (start < text.length && /\s/.test(text[start])) start++
  const open = text[start]
  const close = open === '{' ? '}' : open === '[' ? ']' : null
  if (!close) return null
  let depth = 0, inStr = false, esc = false
  for (let i = start; i < text.length; i++) {
    const ch = text[i]
    if (inStr) { if (esc) esc = false; else if (ch === '\\') esc = true; else if (ch === '"') inStr = false; continue }
    if (ch === '"') { inStr = true; continue }
    if (ch === open) depth++
    else if (ch === close) { depth--; if (depth === 0) return [i + 1, text.slice(start, i + 1)] }
  }
  return null
}
```
`extractStructBlocks` 改为：收集**所有**结构块标记（`【编辑建议】`/`【视角导航】`）的位置，**从后往前**逐块用 `parseJsonAt` 尝试；
解析成功且产出 ≥1 可用项则移除该段（`markIdx → jsonEnd`），否则保留。处理完做 `trim()` + 折叠 3 连空行。

**A2. 算法库宽松归一化：回收顶层 `sub/subTab/categoryId/anchorId`**（修问题 2 的 schema 耦合）
把 `.map(v => …)` 抽成 `normalizeView(v)`：先 `normalizeAlgo(v.algo)`；若 `panel==='algorithm'` 且缺 `algo`，
再用顶层字段拼回（`subTab = v.subTab ?? (ALGO_SUB_TABS.includes(v.sub) ? v.sub : undefined)`，+`categoryId`/`anchorId`）。
```js
function normalizeView(v) {
  const panel = v.panel
  let algo = normalizeAlgo(v.algo)
  if (!algo && panel === 'algorithm') {
    const subTab = v.subTab ?? (ALGO_SUB_TABS.includes(v.sub) ? v.sub : undefined)
    algo = normalizeAlgo({ subTab, categoryId: v.categoryId, anchorId: v.anchorId })
  }
  return { panel, sub: typeof v.sub === 'string' ? v.sub : undefined, algo,
           label: typeof v.label === 'string' && v.label ? v.label : '' }
}
```
（`navigateTo`/`NavSuggestionCard` 无需改动——`sub` 对非 tutor 本就忽略，`algo` 被回收后即走 `openTutorial` 精确路径。）

**A3. 测试**：`editSuggestion.test.js` 增——① 块后跟正文仍能剥离并产出 nav；② `panel=algorithm` 顶层 `sub`+`categoryId`+`anchorId` 被回收为
`algo`；③ 双重 `【决策痕迹】`/`【编辑建议】`+`【视角导航】` 混排仍正确。`decisionTrace.test.js` 同步纳管块剥离用例。

### B. coze（javatutor-coze）

**B1. 注入「算法知识目录」**（修问题 2 缺目录 + 示例错 anchorId）
- 单一事实源 = `frontend/src/assets/algo-knowledge/index.json`；新增同步 `x → coze `assets/knowledge/algo-knowledge-index.json`。
- `prompting/panels.py` 新增 `render_algo_catalog()`（lru_cache 读副本），产出分类+锚点 id 清单（含「树（堆）」→ categoryId `tree`，
  锚点 id 为中文全称：前序遍历/中序遍历/…/优先队列）。
- `_main_system_prompt()` 注入 `render_nav_guidance() + render_algo_catalog() + render_ui_map()`。
- 修正 nav 引导里 algo 示例：`{"subTab":"knowledge","categoryId":"tree","anchorId":"后序遍历"}`（用真实中文锚点 id）。

**B2. 注入「使用流程指南」**（修问题 3 缺知识：让 agent 知道测试模式「存在且如何用」）
- 在 `javatutor_domain_ontology.json` 增加顶层 `"user_guides"` 数组（topic + steps + note），覆盖：运行代码（点运行）、
  **测试模式**（粘贴含 `class Solution` 的代码 → 点「测试」展开 `TestCasePanel` → 逐行/文本输入用例 → 保存激活测试模式 → 运行）、
  `System.out` → 控制台面板、单步播放、复杂度/标签在「分析」页。
- 新增 `render_usage_guide()`（读 ontology 的 `user_guides`），注入 `_main_system_prompt()`（走 SystemMessage，永不被 compress 截断）。
- 导航侧规则见 B3（边界），此处不再单独重复「流程问题不附卡」，避免对测试模式单例过拟合。

**B3. 立清「导航边界」+ 块放置（核心；修问题 1 裸 JSON / 问题 3 随意导航）**
- `render_nav_guidance()` 把**可导航集合写成闭集**，并作为**首要原则**：
  - 「可导航目标**只有且仅有**：`variables` / `flow` / `datastructure` / `algorithm` / `tutor`（单文件）+ `callgraph` / `classdiagram` / `structure`（多文件）；
    算法库可通过 `algo:{subTab,categoryId,anchorId}` 细分。」
  - 「**除上述之外不存在任何导航目标**：测试模式、运行代码、输入用例、文件管理、设置等『操作/流程』主题**对应不到任何面板，不可附卡**，直接给操作步骤。」
  - 「只有当用户想**直接看某个面板里已有的分析/可视化**时才值得附 1 张卡；否则整块省略。不要为了导航而导航、不要用无关面板硬凑。」
- 追加放置规则：「`【视角导航】` 追加在回答**末尾**，紧邻 `【决策痕迹】` 之前；块后不要再写任何正文。」（与现有一致保留）
- 前置不变：「`sub` 仅 `panel:"tutor"`、`algo` 仅 `panel:"algorithm"`。」
- 关键：以**边界**为主导——「流程问题不附卡」只是边界的**自然推论**，不作为独立启发式规则（那会过拟合单例）。

**B4. 守卫测试**：`tests/test_panel_sync.py`（coze）新增——`algo-knowledge-index.json` 副本与前端一致、`render_algo_catalog` 含全部
categoryId 且锚点 id 非空、`user_guides` 覆盖「测试模式/运行」。`scripts/sync_panel_manifest.py` 增 algo 目录的校验/`--sync`。

**B5. 主 Agent 集中式 few-shot 注入（提升结构契约遵循度 / 回答准确率）**
- **现状**：`prompting/fewshots.py`（`FEW_SHOTS` + `get_few_shots`）是集中式 few-shot 库，但只被**旧专家节点**
  `_build_expert_messages`（nodes.py:179）消费；当前图（`build_context → main_agent → critic → …`）**不路由到专家节点**，
  主 Agent 不含可审查的 few-shot，仅 `SYSTEM_PROMPT_MAIN_AGENT` 里一段硬编码 `## 调用示例`（prompts.py:126）。
- **做法**：把主 Agent 专用示例注入 `_main_system_prompt()`（走 SystemMessage，**永不被 compress 截断**）。
  新增 `prompting/main_fewshots.py`（或扩展现有 `fewshots.py` 加 `MAIN_FEW_SHOTS`）集中存放，便于开发者审查/增删。
- **示例内容**（围绕「导航边界」+ 通用结构契约）：
  - `【视角导航】` 放**末尾**、块后不追加正文；`panel/sub/algo` 正确形态（`algo:{subTab,categoryId,anchorId}` 仅用于 `panel:"algorithm"`；`sub` 仅 `panel:"tutor"`）。
  - **边界样例**：问「算法模板在哪」→ 附 `{"panel":"algorithm","algo":{"subTab":"template"}}`；问「怎么打开测试模式」→ **不附卡**、只给「测试用例→保存→运行→控制台看输出」步骤（因为测试模式不属于可导航面板）。
  - 回答必须引用真实 step/line/变量，不编造。
- **价值**：把「提升 agent 回答准确率」变成**可审查、可迭代**的手段——开发者改一处文件即可让主 Agent 的契约行为变稳，
  后续新问题可复用样例增扩；这是相对 SFT 更轻、可回退的准确率提升路径。

### C. 清理死数据（可选，顺手）
`ui-panel-manifest.json` 的 `algorithmLibrary.categories`（5 类、无锚点、前端/coze 均未消费）为不全的重复副本，建议**删除**，改由 B1 的
algo 目录脚本统一维护，避免两面漂移。

## 四、验收标准

- P1：回答尾含 `【视角导航】` + 块后正文 → 前端渲染出可点击卡、正文无裸 JSON；点击定位算法库-算法知识-树（堆）。
- P2：问「树/堆的算法知识在哪」定位到 `算法库-算法知识-树（堆）`；问「快速排序」定位到 `排序-快排`；非法 categoryId/anchorId 不崩、落到默认。
- P3：问「怎么打开测试模式」给出**分步操作**（测试用例→保存→运行→控制台看输出），**不附**导航卡——因测试模式**无对应面板、不在可导航集合**，而非因为「它是流程问题」。
- 无导航块的回答与现状一致；`【编辑建议】` 也不会再以裸 JSON 上屏。
- **few-shot 生效**：`MAIN_FEW_SHOTS` 注入主 Agent 系统提示（`_main_system_prompt`），样本含合法 `panel/sub/algo` 与「边界：非面板主题不附卡」形态；
  开发者改一处文件即可稳定主 Agent 契约行为、提升回答准确率。

## 五、测试

- 前端：`editSuggestion.test.js` / `decisionTrace.test.js` 新增用例（见 A3），`npm test` 全绿。
- coze：`uv run pytest -q` 全量 + `test_panel_sync.py` 新增守卫；新增 `test_main_fewshots.py`（或并入）验证 `MAIN_FEW_SHOTS` 注入、
  样本含合法 `panel/sub/algo` 形态、不出现裸结构块；`sync_panel_manifest.py` 无 drift。
- 手验：`npm run dev` 跑 P1/P2/P3 三用例。

## 六、风险 / 待确认

- **agent 输出仍可能偶尔放错结构**：解析健壮性兜底是主修复；引导收紧是辅助。两者都做。
- **`render_usage_guide` 文案**：测试模式步骤以 `TestCasePanel.vue` / `SingleFileShell.vue`（"测试"切换、运行按钮）为准，需开发时对照 UI 核对。
- **是否删 manifest 的 `categories`**：待开发时确认无其它消费点后再删，避免与 B1 冲突。

## 七、文档登记

- 对应 spec：`docs/spec/2026-09-07-coze-agent-view-navigation.md`（§3.1.1 示例锚点 id 更正 + §9 同步规约增 algo 目录同步）。
- 前置 review：`docs/reviews/2026-09-08-coze-agent-view-navigation-fix-review.md`。
- 本 plan：`docs/plan/2026-09-09-coze-agent-view-navigation-robustness-fix-plan.md`。
