# 视角导航修复（联调 bug）+ 面板知识单一事实源同步（2026-09-08）

> 一句话：联调发现 3 处导航错误，根因是本体 UI 面板描述过时 + 与导航清单两套词汇 + 导航 schema 太粗。本轮修复导航正确性，并把前端 `ui-panel-manifest.json` 立为**单一事实源**，由脚本/测试兜底「前端改了、coze 本体/提示词没用」。

## 1. 背景与根因

2026-09-07 初版视角导航已落地（`prompts.py`/`editSuggestion.js`/`NavSuggestionCard.vue`/`AiTutorPanel.vue`/`player.js`/`MultiFileShell.vue`）。联调跑单文件+多文件复测，发现 3 个导航错误：

- **P1「算法模板在哪里」→ 点到 agent**：本体 `ai_panel` 仍写旧「三个分页：解说/复杂度/算法」，与实际「解说/分析」两页不符；agent 摸不准该指哪个面板。
- **P2「内存状态在哪里看」→ 点到堆**：本体用 `heap_panel`/`variable_panel`/`stack_panel`/`algo_viz_panel` 等 id，与导航用的 `variables`/`datastructure`/`algorithm`/`tutor` 不一致，agent 对不上号。
- **P3「树的相关算法知识」→ 点到 agent / 无反应**：导航 schema 只支持 `panel`+`sub`，表达不了「算法库→子页/分类锚点」；`navigateTo('tutor',...)` 改的是右侧内嵌面板，浮动面板无反应。

根因（联调结论）：主 agent 其实能拿到本体（`build_context_node` 的 `[Role & Policies]` 段含本体块），但**本体过时** + **两套词汇** + **schema 太粗**，加上 CRITIC 把非法 panel 只当轻微问题放行。

## 2. 修复：Part A 导航正确性

- **A1 本体校准**（`assets/knowledge/javatutor_domain_ontology.json`）：
  - `ai_panel.function` 改为「含两个分页：解说（自由问答）、分析（复杂度 + 算法/数据结构标签）」，删除「算法」独立分页表述。
  - `variable_panel`/`heap_panel`/`stack_panel` 统一标注属「内存状态」面板子区域（原先写「内存监控」）。
- **A2 注入「UI 面板导航图」+ 禁止 `tutor` 当目标**：
  - 新增 `src/graphs/javatutor/prompting/panels.py`：`load_manifest`（读 coze 副本）/`render_nav_guidance`（生成 `【视角导航】` 指引）/`render_ui_map`（生成「UI 面板导航图」）/`MODULE_PANELS`（本体模块 id ↔ panel id 映射）。
  - `prompts.py` 的 `SYSTEM_PROMPT_MAIN_AGENT` **删掉硬编码导航块**，改为在 `main_agent.py` 运行时拼装 `模板 + render_nav_guidance() + render_ui_map()`。
  - 新增规则：`tutor` 仅当想看 agent 的解说/分析时用；「去哪看 X」指向内容面板。
  - `SYSTEM_PROMPT_CRITIC`：非法 panel/sub/algo 由「轻微问题」改为**中等问题**（可判失败），提高拦截力度。
- **A3 扩展 schema 支持算法库精确定位**：
  - `【视角导航】` 新增 `algo` 字段（`panel:"algorithm"`）：`{"subTab":"knowledge|template","categoryId":"tree","anchorId":"..."}`。
  - 前端 `player.js` `navigateTo(panel, sub, algo)`：`panel='algorithm'` 且带 `algo` 时切 `algoSubTab` 子页 + 带 `categoryId` 走 `openTutorial`。
  - `editSuggestion.js` 解析 `nav.views[].algo`；`NavSuggestionCard` 点击传 `v.algo`；`AlgoTab` 改用 `store.algoSubTab`（从本地 ref 提升到 store，供导航定位）。
- **A4 韧性修复**：`NavSuggestionCard` 按 `store.mode` 用 manifest 白名单裁剪；`navigateTo` 的 `sub`/`algo` 白名单校验（复习 review P2/P3）。

## 3. 修复：Part B 前端单一事实源

- **B1 新建** `javatutor/frontend/src/constants/ui-panel-manifest.json`：`version`/`modes`/`groups`/`panels`（id/name/group/subTabs/content/navHints/mode）/`algorithmLibrary`。**以后改任何面板/标签必须先改它**。
- **B2 消费**：新建 `uiPanelManifest.js`（`panelById`/`allowedPanels(mode)`/`panelsForMode`/`groupOfPanel`/`defaultPanelOfGroup`/`algoSubTabs`）；`player.js` 白名单、`SingleFileShell`/`MultiFileShell` 的 `GROUP_OF_TAB`/`GROUP_DEFAULT_TAB`、`NavSuggestionCard` 过滤全部改从 manifest 读。
- **B3 测试**：`ui-panel-manifest.test.js`（vitest）断言 manifest 内部自洽 + 与 player 白名单一致 + 可 JSON 序列化。

## 4. 修复：Part C coze 自动生成 + 守卫

- **C1** `assets/knowledge/ui-panel-manifest.json`：coze 副本（本组已同步一致）。
- **C2** `prompting/panels.py`：见 A2。
- **C3** `scripts/sync_panel_manifest.py`：读前端 manifest → 比对/覆盖 coze 副本；校验本体 `modules` 与 manifest/`MODULE_PANELS` 一致；drift 退出非 0。
- **C4** `tests/test_panel_sync.py`（coze）：coze 副本=前端 manifest、本体结构一致、导航引导覆盖全部 panel、无「三分页」残留、`tutor` 不指向内容 navHints。

## 5. 测试

- 前端 `vitest`：**23 文件 / 245 测试全绿**（新增 `ui-panel-manifest.test.js` 8 断言 + `navigateTo` algo 3 用例 + `editSuggestion` algo 2 用例）。
- coze `pytest`：**211 测试全绿**（新增 `test_panel_sync.py` 7 用例）；`scripts/sync_panel_manifest.py` 无 drift（EXIT=0）。

### 5.1 review 加固（2026-09-08 review 后落地）

按 `docs/reviews/2026-09-08-coze-agent-view-navigation-fix-review.md` 的 P4–P8 顺手处理（不阻断发布）：

- **P4 术语统一**：`MemoryPanel.vue` 面板头「内存监控」→「内存状态」，与 manifest/本体/导航卡/tab 按钮一致。
- **P5 导航图标注**：`render_ui_map()` 对 multi-only 面板标注「（多文件专属）」，单文件语境下不再误导 agent 提议多文件面板。
- **P6 控制台不映射导航**：`MODULE_PANELS` 的 `console_panel` 改为 `None`（非独立导航目标）+ 注释。
- **P7 死代码**：`render_nav_guidance()` 改用 `sub_tabs` 变量拼 `algo.subTab` 合法取值，不再硬编码 `knowledge|template`。
- **P8 顺序注释**：`navigateTo` 注明「带 `categoryId` 时 `openTutorial` 会把 `algoSubTab` 重置回 knowledge」的预期顺序。

## 6. 待执行 / 注意

- coze 侧改动需**重新发布 agent**（`prompts.py`/`main_agent.py`/本体/panels.py 变更）+ 前端 `npm run dev` 热载才生效。
- `main_agent.py` 改为 `_main_system_prompt()` 运行时拼装；`build_context_node` 的 `build_system_prompt("other")` 与之独立，互不影响。
- 只改 `ui-panel-manifest.json` **结构**字段即可让提示词/本体结构联动；本体内容字段（`function`/`data_field`/`common_confusions`）仍人工维护，落在 `test_panel_sync.py` 校验。
- 冒泡排序→「插入排序」误判队友在修，本计划不处理。

## 7. 涉及文件

- 前端（`javatutor/frontend`）：`src/constants/ui-panel-manifest.json`（新）、`src/constants/uiPanelManifest.js`（新）、`src/constants/ui-panel-manifest.test.js`（新）、`src/stores/player.js`、`src/utils/editSuggestion.js`、`src/components/NavSuggestionCard.vue`、`src/components/right-tabs/AlgoTab.vue`、`src/components/SingleFileShell.vue`、`src/components/MultiFileShell.vue`、`tests`。
- coze（`javatutor-coze`）：`src/graphs/javatutor/prompting/panels.py`（新）、`src/graphs/javatutor/prompts.py`、`src/graphs/javatutor/main_agent.py`、`assets/knowledge/ui-panel-manifest.json`（新）、`assets/knowledge/javatutor_domain_ontology.json`、`scripts/sync_panel_manifest.py`（新）、`tests/test_panel_sync.py`（新）。
- 规约：`docs/spec/2026-09-07-coze-agent-view-navigation.md` §3.1.1/§9、`docs/agent-collaboration-guide.md`。
