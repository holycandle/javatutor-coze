# Coze Agent 视角导航 + 「分析」页合并（2026-09-07）

> 一句话：agent 现在能在回答末尾输出 `【视角导航】` 结构化指令块，前端把它渲染成可点击卡片，用户一点即跳到对应分析面板；同时把 agent 面板内的「复杂度」「算法」两个子 tab 合并为一页「分析」。

## 1. 背景

Coze agent 只有 `step_facts`、`fetch_execution_context` 两个工具，且只能以文字回答。用户往往不知道 JavaTutor 现有的分析结果（内存状态、流程、数据结构、复杂度/算法标签、多文件的 UML）藏在哪个面板里。为此让 agent 在回答中**输出结构化导航指令**，前端渲染成卡片，用户一点即跳到对应面板——既补 agent 工具不足，又让 agent 的思考与 JavaTutor 既有分析结合。

配套改动：agent 面板内「复杂度」「算法」两个子 tab 合并为一页「分析」——两块内容占比都不大，合并后导航目标更清晰（`analysis`）。

## 2. 规约（已收敛的决策）

设计见 `docs/spec/2026-09-07-coze-agent-view-navigation.md`，执行见 `docs/plan/2026-09-07-coze-agent-view-navigation-plan.md`。关键点：

- **形态**：导航是**输出指令**（回答里附卡片），**不是** agent 的工具。后端透传（0a），前端解析并执行；前端**永不直连 coze**。
- **通道**：沿用 `【编辑建议】` 同款「文末 JSON 块」通道，独立 `【视角导航】` 块，不塞进 `【决策痕迹】`。
- **Schema**：`{"views":[{"panel":...,"sub":...,"label":...}]}`；`views` 0–3 项，多余裁剪；`sub` 仅 `panel:"tutor"` 时用（`analysis`/`explain`）；无可用面板时整块省略，最多一个块/条回答。
- **白名单**：单文件 `variables/flow/datastructure/algorithm/tutor+sub`；多文件额外加 `callgraph/classdiagram/structure`。
- **本阶段范围**：纯导航 + 泛泛概览。不做数据工具、不做分析结果推送；分析结果由前端跑完代码后 `applyRunResult → requestAnalysis` 自动产生。

## 3. 实现

### 3.1 coze 侧（`javatutor-coze/src`）

- **`graphs/javatutor/prompts.py`**
  - `SYSTEM_PROMPT_MAIN_AGENT`：追加可导航面板清单（单/多文件两组）与规范名，以及「何时附 `【视角导航】` 卡片」的规则（通常 1 个、最多 3 个、`sub` 仅供 `tutor`、不要为了导航而发消息）。
  - `SYSTEM_PROMPT_CRITIC`：判断正文时**忽略** `【视角导航】`/`【编辑建议】` 结构化块；可校验 `panel` 白名单、`sub` 是否仅用于 `tutor`，非法只算轻微问题（不判失败）。
  - `SYSTEM_PROMPT_REVISE`：修订时**保留**原回答的结构化块，除非评审标记其非法。
- **`graphs/javatutor/nodes.py`** `build_final`：在 `_strip_leaked_json` 注释里补充说明 `【视角导航】` 是受控指令、不可剥离（防回归提示）。已确认 `_strip_leaked_json` 只匹配 `intent`/`pass`/`tool` 开头 JSON，`{"views":...}` 不会被误删。

### 3.2 前端（`javatutor/frontend/src`）

- **`utils/editSuggestion.js`**：`parseAssistantMessage` 返回改为 `{body, edits, nav}`；新增 `NAV_MARK` 与 `extractStructBlocks` 助手，从「最后一块」开始剥结构化块，能同时处理「导航在编辑前/后」两种顺序；`edits`/`views` 可用项为空的块按正文保留并停止（不静默丢弃）。
- **`utils/decisionTrace.js`**：`splitDecisionTrace` 复用 `parseAssistantMessage(body).body` 剥掉 `【编辑建议】`/`【视角导航】` 块，避免裸 JSON 进 markdown 正文（顺带修复了 `【编辑建议】` 之前以原始 JSON 渲染的既有隐患）。
- **`components/NavSuggestionCard.vue`**（新建）：每个 view 渲染一个按钮，文本取 `label` 或 panel 规范名，点击 `store.navigateTo(panel, sub)`。
- **`components/AiTutorPanel.vue`**：`tabs` 改为 `[解说, 分析]` 两个子 tab；把原 `complexity` 块与 `algorithm` 块合并为一个 `analysis` 块（复杂度卡在上、算法/数据结构标签组在下，共用一个 `isAnalyzing`/`analysisError`/空态）；assistant 气泡 `EditSuggestionCard` 旁新增 `<NavSuggestionCard>`，`parsedMessages` 由 `parseAssistantMessage` 返回 `nav`。
- **`stores/player.js`**：`multiRightTab`/`switchMultiRightTab`（死代码、白名单不一致）替换为 `multiTab`/`switchMultiTab`，白名单扩为 `['variables','flow','datastructure','callgraph','classdiagram','structure','algorithm','tutor']`；新增 `navigateTo(panel, sub)` 动作（单文件走 `switchRightTab`，多文件走 `switchMultiTab`；`panel==='tutor' && sub` 时设 `activeAiTab=sub`）。
- **`components/MultiFileShell.vue`**：删除本地 `const multiTab = ref('datastructure')`，模板/`switchTab`/`switchGroup`/`rightGroup` computed 全部改用 `store.multiTab`（打通多文件导航，消除死代码）。

## 4. 测试

- 前端 `vitest`：**22 个文件 / 230 个测试全绿**。新增/更新：
  - `editSuggestion.test.js`：`空输入安全` 更新为含 `nav`；新增导航解析/JSON 损坏回退/空 views 回退/最多 3 个/编辑+导航共存用例。
  - `decisionTrace.test.js`：新增剥掉 `【编辑建议】`/`【视角导航】` 块、避免裸 JSON 用例。
  - `stores/__tests__/player-righttab.test.js`：新增 `multiTab` 默认/切换/非法 tab，以及 `navigateTo` 单文件/多文件/tutor+sub/非法 panel 用例。
- coze `pytest`：**204 个测试全绿**（prompt 变更不破坏既有契约）；1 个 Pydantic 弃用警告（无关）。

## 5. 注意事项 / 遗留

- **需重新发布 coze agent**（prompt 变更）+ 前端 `npm run dev` 热载才生效。
- `navigateTo` 在「浮动 AI 面板」与「右侧内嵌 AI 面板」都会因 `activeAiTab` 全局一起切换——已知、可接受。
- 冒泡排序被误判为「插入排序」：队友在修，本阶段不处理。
- 右下角算法教程 toast 本阶段不改，仅确认「以用户点击为准」。

## 6. 涉及文件

- coze：`src/graphs/javatutor/prompts.py`、`src/graphs/javatutor/nodes.py`
- 前端：`src/utils/editSuggestion.js`、`src/utils/decisionTrace.js`、`src/components/NavSuggestionCard.vue`（新建）、`src/components/AiTutorPanel.vue`、`src/stores/player.js`、`src/components/MultiFileShell.vue`、对应 3 个测试文件
- 文档：`docs/spec/2026-09-07-coze-agent-view-navigation.md`、`docs/plan/2026-09-07-coze-agent-view-navigation-plan.md`
