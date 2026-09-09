# 执行计划：视角导航修复（联调 bug）+ 面板知识单一事实源同步

> 执行依据：`docs/spec/2026-09-07-coze-agent-view-navigation.md`（含新增 §3.1.1 `algo` 字段、§9 UI 面板结构同步规约）。
> 前情：2026-09-07 初版已落地（`prompts.py`/`editSuggestion.js`/`NavSuggestionCard.vue`/`AiTutorPanel.vue`/`player.js`/`MultiFileShell.vue`）。
> 联调发现 3 个导航错误 + 本体过时/不一致。**本计划修导航正确性 + 建立「前端 manifest 单一事实源 → 自动同步 coze」机制。**
> **跨两仓**：`javatutor-coze`（agent prompt + 本体）+ `javatutor`（Vue 前端）。前端文件以 `javatutor/frontend/...` 标全路径。

## 0. 全局约束（务必遵守）

- **不做任何 git 操作**（不 `git add`/`commit`/`push`/`stash`/`checkout`/`branch`）。
- 只修改下列文件。coze 侧不触碰 `scripts/`（新增脚本除外）、`src/utils/`、`src/storage/`、`learning/`、`pyproject.toml`、`.coze/`。
- 前端 **不触碰** `javatutor/frontend/src/backup-20260807/`。
- 保持现有命名/风格（前端 ESM + `defineStore`；coze 中文 docstring、`_` 私有函数）。
- 写 devlog 到 `javatutor-coze/docs/devlog/2026-09-08-coze-agent-view-navigation-fix.md`（说明根因 + 已修 + 待执行）。

## 0.1 根因（联调结论，供执行组参照）

- **主 agent 能拿到本体**：`build_context_node`（`nodes.py:460-484`）用 `build_system_prompt("other")` 构造 `context_built`，
  其 `[Role & Policies]` 段含「领域本体」块（`prompts.py:155-156`），且该段是 `structure` 输出的第一段、压缩优先保留（`context_builder.py:166-179`）。
  主 agent 的 HumanMessage 即 `context_built`（`main_agent.py:139`）。→ 本体**并非**未注入。
- **真正问题**：本体里的 UI 面板描述**过时 + 与导航清单两套词汇**。
  - `ai_panel`（`assets/knowledge/javatutor_domain_ontology.json` `modules`）：`"含三个分页：解说、复杂度、算法"`——**旧结构**；
    前端已合并为「解说/分析」两页（`AiTutorPanel.vue:227-228`）。→ P3「AI 讲解面板→算法标签页」由此而来。
  - 本体 id（`variable_panel`/`heap_panel`/`stack_panel`/`algo_viz_panel`/`ai_panel`）与导航 id（`variables`/`flow`/`datastructure`/`algorithm`/`tutor`）**不一致**，
    且缺 `datastructure`/`algorithm` 模块。→ P3「算法可视化面板」、P2 堆→数据结构、P1 算法模板→AI 讲解。
- **导航 schema 太粗**：只支持 `panel`+`sub`(tutor)，表达不了「算法库→模板子页/树(堆)分类锚点」。前端已有
  `openTutorial(categoryId, anchorId)`（`player.js:633-636`）+ `AlgoKnowledgeHeader` 监听 `knowledgeNav.nonce` 定位可复用。
- **`tutor` 指向 agent 自身**：single-file 下 agent 面板有内嵌（`SingleFileShell.vue:105`）与浮动（`SingleFileShell.vue:123`）两实例。
  用户看卡时人就在 agent 面板，`navigateTo('tutor', ...)` 改的是右侧内嵌面板，浮动面板无反应 → 「点击无反应」。
- **批评者太宽容**：`prompts.py:106` 让 CRITIC 把非法 panel/sub 只算「轻微问题」，而三处错误都用了白名单内 panel，被放行。

---

## Part A：修复导航正确性（三步）

### A1. 修正本体过时/不一致（结构以 manifest 为准）
> 按「前端源+自动生成」决策，本体的 UI 结构字段应由 manifest 同步（见 Part C），此处只做**过渡性校准 + 保留内容字段**。

- `assets/knowledge/javatutor_domain_ontology.json` 的 `modules`：
  - `ai_panel`：`name` 改「AI 讲解面板」，`function` 改「含两个分页：解说（自由问答）、分析（时间复杂度/空间复杂度 + 算法/数据结构标签）」。删除「算法」独立分页表述。
  - 修正 `variable_panel`/`heap_panel`/`stack_panel`：明确都属「内存监控（内存状态）」面板的子区域，非独立面板；`function` 措辞保持。
  - 若缺 `datastructure`/`algorithm` 面板模块，由 `sync_panel_manifest.py` 从 manifest 生成（见 C3），本步骤不手写重复结构。

### A2. 给主 agent 注入准确「UI 面板导航图」+ 禁止 `tutor` 当「去哪看 X」目标

- 新增 `javatutor-coze/src/graphs/javatutor/prompting/panels.py`：
  - `load_manifest()`：读 `assets/knowledge/ui-panel-manifest.json`（coze 副本）。
  - `render_nav_guidance()`：生成 `SYSTEM_PROMPT_MAIN_AGENT` 中的 `【视角导航】` 指引段（替换现有硬编码块 `prompts.py:127-137`）。
  - `render_ui_map()`：生成「UI 面板导航图」——每个面板 `id / 组 / 展示什么 / 用户问什么时该导航到哪`，从 manifest `panels[].content` 与 `navHints` 派生。
- `prompts.py` 的 `SYSTEM_PROMPT_MAIN_AGENT` 末尾改为拼接 `render_nav_guidance() + render_ui_map()`；
  **新增规则**：「`tutor` 仅当想让用户看 agent 的分析/解说时用；`去哪看 X` 应指向**内容面板**（variables/flow/datastructure/algorithm/…），不要指向 `tutor`（用户已在 agent 面板）」。
- `SYSTEM_PROMPT_CRITIC`（`prompts.py:106`）：改为「`panel` 必须为 manifest 白名单、`sub` 仅限 `analysis`/`explain`、`algo` 仅限 `algorithm` 且 `subTab`∈{knowledge,template}`；非法按**中等问题**处理（可判失败）」——提高拦截力度。
- 注意 `main_agent.py:139` 用 `SYSTEM_PROMPT_MAIN_AGENT` 常量，需改成**运行时拼装**（`SYSTEM_PROMPT_MAIN_AGENT` 作为模板，取其值再用 `render_nav_guidance()+render_ui_map()` 注入）。`main_agent.py` 与 `build_context_node`（`nodes.py:482` 用 `build_system_prompt("other")`）分离，互不影响。

### A3. 扩展 `【视角导航】` schema 支持算法库精确定位

- 协约见 spec §3.1.1。前端 `stores/player.js` `navigateTo(panel, sub, algo)` 扩展：
  ```js
  navigateTo(panel, sub, algo) {
    if (panel === 'tutor' && ['analysis', 'explain'].includes(sub)) this.activeAiTab = sub
    if (this.mode === 'multi') this.switchMultiTab(panel)
    else this.switchRightTab(panel)
    if (panel === 'algorithm' && algo) {
      if (algo.subTab === 'template') this.algoTemplateTab = true       // 或改为切 AlgoTab 子页
      if (algo.categoryId) this.openTutorial(algo.categoryId, algo.anchorId ?? null)
    }
  }
  ```
  `openTutorial`（`player.js:633-636`）已含 `switchRightTab('algorithm')`，但会落到「算法知识」子页；
  若要「算法模板」子页，需另加一个状态/动作（见 A4 / Part B 的 manifest 消费）。
- 前端 `editSuggestion.js` `parseAssistantMessage`：`nav.views[]` 解析 `algo` 字段（`{subTab, categoryId, anchorId}`），缺省 undefined。
- `NavSuggestionCard.vue`：按钮 `@click="store.navigateTo(v.panel, v.sub, v.algo)"`。

### A4. 前端两处韧性修复（来自 review P2/P3，一并带上）

- `NavSuggestionCard.vue`：按 `store.mode` 过滤 `views`（单 5 面板 / 多 8 面板），`visible` computed 用 manifest 白名单裁剪；
  模板 `v-for="v in visible"`。避免「单文件下 agent 违规发多文件 panel → 死按钮」。
- `stores/player.js` `navigateTo`：`sub` 白名单 `['analysis','explain']`；`algo` 仅 `panel==='algorithm'` 生效。

---

## Part B：前端单一事实源 manifest（防复发）

### B1. 新建 `javatutor/frontend/src/constants/ui-panel-manifest.json`

集中定义（结构随 spec §9.1）：
```json
{
  "version": "1.0.0",
  "modes": ["single", "multi"],
  "groups": { "observe": ["variables","flow","datastructure","callgraph","classdiagram","structure"],
              "learn": ["algorithm"], "ask": ["tutor"] },
  "panels": {
    "variables": { "name": "内存状态", "group": "observe", "content": "栈区+堆区（调用栈、局部变量、堆对象）",
                   "navHints": ["内存状态","变量","栈","堆","内存监控"] },
    "flow":      { "name": "流程", "group": "observe", "content": "控制流/流程图" },
    "datastructure": { "name": "数据结构", "group": "observe", "content": "树/堆、数组、链表、排序、字符串匹配、图等可视化" },
    "algorithm": { "name": "算法库", "group": "learn", "subTabs": ["knowledge","template"],
                   "content": "算法知识分类 + 算法模板",
                   "navHints": ["算法模板","算法知识","树算法","排序算法"] },
    "tutor":     { "name": "agent", "group": "ask", "subTabs": ["explain","analysis"],
                   "content": "解说 + 分析（复杂度/算法标签）",
                   "navHints": ["为什么","讲解","分析","复杂度","时间复杂"] },
    "callgraph": { "name": "调用关系", "group": "observe", "content": "多文件调用关系图", "mode": "multi" },
    "classdiagram": { "name": "类图", "group": "observe", "content": "多文件类图", "mode": "multi" },
    "structure": { "name": "结构", "group": "observe", "content": "多文件项目结构", "mode": "multi" }
  },
  "algorithmLibrary": { "subTabs": ["knowledge","template"],
                        "categories": { "tree":"树","sorting":"排序","graph":"图","linked-list":"链表","search-and-find":"查找" } }
}
```

### B2. 前端三处改从 manifest 读

- `stores/player.js`：`switchRightTab`/`switchMultiTab` 白名单、`navigateTo` 的 `sub`/`algo` 校验、`openTutorial` 目标表 → 从 manifest 派生。
  （`activeAiTab`/`multiTab` 等状态不变。）
- `SingleFileShell.vue`：`GROUP_OF_TAB`/`GROUP_DEFAULT_TAB`（:242-249）→ 由 manifest `groups` 派生。
- `MultiFileShell.vue`：右侧 pane 标签（:67-106 的 `:class`/`v-show`）+ `switchGroup`/`rightGroup` → 由 manifest 派生。
- 新建 `javatutor/frontend/src/constants/uiPanelManifest.js`：导出 `PANEL_MANIFEST` 及辅助函数（`panelById`/`panelsForMode(mode)`/`groupOfPanel`/`allowedPanels(mode)`），供组件/store 引用。

### B3. 新建 `javatutor/frontend/src/constants/ui-panel-manifest.test.js`（vitest，进前端 CI）

- manifest 内部自洽：`groups`/`panels`/`subTabs` 引用合法、`mode:"multi"` 面板只在 multi 组、单/多面板并集 = 白名单。
- 与 `player.js` 白名单/分组映射一致（断言 `switchRightTab` 白名单 == `panelsForMode('single')` 等）。
- `PANEL_MANIFEST` 可 JSON 序列化（`JSON.stringify` 不抛，供 coze 脚本/校验用）。

---

## Part C：coze 自动生成 + 守卫测试

### C1. coze 副本 `javatutor-coze/assets/knowledge/ui-panel-manifest.json`

由 `sync_panel_manifest.py` 从前端 manifest **生成/同步**（提交在 coze 仓，供 `panels.py` 读取；不在 CI 依赖前端路径）。

### C2. `javatutor-coze/src/graphs/javatutor/prompting/panels.py`

- `load_manifest()`：读 coze 副本（`lru_cache`）。
- `render_nav_guidance()`/`render_ui_map()`：从 manifest 生成 agent 提示词块（见 A2）。
- 同时导出 `MODULE_PANELS`（panel id ↔ 本体 `modules` id 的映射，如 `variable_panel→variables`/`heap_panel→variables`/`algo_viz_panel→datastructure`），供 C4 校验本体。

### C3. 新建 `javatutor-coze/scripts/sync_panel_manifest.py`

- 读前端 `../javatutor/frontend/src/constants/ui-panel-manifest.json`（相对仓库根）。
- 生成/比对：① coze 副本；② 本体 `modules` 的 UI 结构字段（`id`/`name`/子页）与 manifest 一致；不一致则报错并给出 diff。
- 退出码：drift 时非 0，便于接入 `uv run pytest` 或手动调用。

### C4. 新建 `javatutor-coze/tests/test_panel_sync.py`（`uv run pytest` 本地跑）

- 断言 ① coze 副本 = 前端 manifest（路径可达时，用 `scripts/sync_panel_manifest.py` 的比对逻辑）；否则只做内部自洽。
- 断言 ② 本体 `modules` 的 UI 面板 `id`/`name`/`function` 的子页表述与 manifest/`MODULE_PANELS` 一致。
- 断言 ③ `render_nav_guidance()` 产出的 panel 集合 == manifest 白名单；`sub`/`algo` 合法取值。
- 断言 ④ **无旧「三分页」残留**：`ai_panel.function` 不含「复杂度」「算法」作为独立分页，只含「解说/分析」。
- 断言 ⑤ 提示词里 `tutor` 不指向「去哪看 X」的 navHints（防 P1/P3 类错误回归）。

---

## Part D：规约登记 + 验证

### D1. 登记

- `docs/spec/2026-09-07-coze-agent-view-navigation.md` 已含 §3.1.1 + §9 规约（本计划配套）。
- `docs/agent-collaboration-guide.md`：补一条规约（见 spec §9.4 变更守则）。

### D2. 验证清单（按序）

1. **coze 单测**：`javatutor-coze` `uv run pytest -q` 全绿（含 `test_panel_sync.py`、既有 `test_ontology.py`/`test_prompting.py`/`test_main_agent.py`）。
2. **前端单测**：`javatutor/frontend` `npm run test` 全绿（含 `ui-panel-manifest.test.js`、既有 `editSuggestion.test.js`/`decisionTrace.test.js`/store 用例）。
3. **同步检查**：`uv run python scripts/sync_panel_manifest.py` 无 drift、无 diff。
4. **手验（dev）**：`javatutor/frontend` `npm run dev` 单文件跑一遍，复测三个用例：
   - 「算法模板在哪里」→ 卡片按钮指向「算法库-算法模板」，点击切到 LEARN-算法库-算法模板页。
   - 「内存状态在哪里看」→ 一张卡（或合并）指向「内存状态」，点击切到 OBSERVE-内存状态（栈+堆同页）。
   - 「树的相关算法知识」→ 卡片指向「算法库-树(堆)」+ 文字引用「OBSERVE-数据结构页」「ASK-分析页」，点击切到对应面板。
5. **无回归**：既有 `【决策痕迹】`/`【编辑建议】` 行为不变；结构化块不呈裸 JSON；`dist` 不涉及（跑 dev）。

## 遗留 / 注意事项

- coze 侧改动需**重新发布 agent** 才生效；前端 `npm run dev` 热载。
- `main_agent.py` 改用运行时拼装 `SYSTEM_PROMPT_MAIN_AGENT` 后，`test_main_agent.py` 相关断言需同步（若断言了系统提示词原文）。
- 只改 `ui-panel-manifest.json` 的**结构**字段即可让提示词/本体结构联动；本体内容字段（function/data_field/common_confusions）仍人工维护，落在 `test_panel_sync.py` 校验。
- 冒泡排序→「插入排序」误判队友在修，本计划不处理。
