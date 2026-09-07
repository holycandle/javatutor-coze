# Coze Agent 视角导航 + 「分析」页合并（规格）

> 状态：**spec 阶段**（本文档为实施方案，供执行组落地）。
> 关联：
> - 消息契约补充见 [2026-08-10-coze-agent-interface.md](./2026-08-10-coze-agent-interface.md)（新增「视角导航」块）。
> - 信息分层原则见 [2026-08-29-memory-retrieval-context-engineering-design.md](./2026-08-29-memory-retrieval-context-engineering-design.md)。
> - 前端仓库：`javatutor`；coze 仓库：`javatutor-coze`（本文档两仓都涉及）。

## 1. Context（为什么做）

Coze agent 目前只有 2 个工具（`step_facts`、`fetch_execution_context`），且只能以文字回答。用户往往不知道
JavaTutor 现有的分析结果（内存状态、流程、数据结构、复杂度/算法标签、多文件的 UML）藏在哪个面板里。
为让 agent 与网页应用深度融合，我们让 agent 在回答中**输出结构化导航指令**，前端把它渲染成可点击卡片，
用户一点即跳到对应面板。这既能补 agent 工具不足，又能把 agent 的思考与 JavaTutor 的既有分析结果结合。

配套改动：把 agent 面板内「复杂度」「算法」两个子 tab 合并为一页「分析」——两块内容占比都不大，
合并后导航目标更清晰（`analysis`）。

## 2. 已收敛的决策（/grilling 结论）

- **架构**：后端透传（0a）。agent 只能读回答，不可能直接操控网页；真实模式 = agent 输出结构化指令 →
  后端既有 SSE 流式透传 → 前端解析并执行。前端**永不直连 coze**。
- **形态**：导航是**输出指令**（回答里附卡片），**不是** agent 的工具。
- **本阶段范围**：纯导航 + 泛泛概览。**不做**数据工具、**不做**分析结果推送、**不做**「agent 调后端生成」。
  分析结果由前端跑完代码后自动分析（`applyRunResult → requestAnalysis`），agent 只负责把用户导航过去。
- **冲突收敛原则**：以用户点击为准（点导航卡就切过去；右下角算法教程 toast 只当提示，两者不同时刻触发）。
- **算法误判**（冒泡排序被误判为「插入排序」）：队友在修，本阶段不处理。

## 3. 指令契约：`【视角导航】` 块

沿用 `【编辑建议】` 同款「文末 JSON 块」通道。主 agent 在回答正文之后、`【决策痕迹】` 之前追加：

```text
正文...

【视角导航】
{"views":[{"panel":"tutor","sub":"analysis","label":"分析"}]}
```

### 3.1 Schema

- `views`：数组，0–3 项；多余裁剪。每项：
  - `panel`（必填）：面板白名单 id（见 §4）。
  - `sub`（可选）：仅 `panel:"tutor"` 时有效——`"analysis"` | `"explain"`。
  - `label`（可选）：卡片展示文本；缺省用 panel 的中文规范名（见 §4）。
- 放置：与正文空一行分隔，紧邻 `【决策痕迹】` 之前。前端先按 `【决策痕迹】` 切分（现有
  `splitDecisionTrace`），再在 body 里剥掉 `【视角导航】` / `【编辑建议】`。
- 无可用面板时整块省略，**不要**发空壳块。最多一个 `【视角导航】` 块/条回答。

### 3.2 与 `【决策痕迹】`/`【编辑建议】` 的关系

- 顺序：正文 → `【编辑建议】`（如有，agent 编辑代码时才出现）→ `【视角导航】`（如有）→ `【决策痕迹】`。
  三者都是「末尾结构化块」，前端按各自的 mark 剥离子渲染，release 前不落入 markdown 正文。
- `【视角导航】` 与 `【编辑建议】` 互不依赖，可同时出现或各自单独出现。

## 4. 面板白名单

### 4.1 单文件模式（`store.rightTab`，见 `javatutor/frontend/src/components/SingleFileShell.vue`）

| panel | 规范名 | 顶层组 |
|---|---|---|
| `variables` | 内存状态 | observe |
| `flow` | 流程 | observe |
| `datastructure` | 数据结构 | observe |
| `algorithm` | 算法库 | learn |
| `tutor` | agent | ask（`sub`=analysis/explain） |

### 4.2 多文件模式（右侧 pane 标签，见 `javatutor/frontend/src/components/MultiFileShell.vue`）

单文件全部 5 个 + 以下 3 个（均在 observe 组）：

| panel | 规范名 |
|---|---|
| `callgraph` | 调用关系 |
| `classdiagram` | 类图 |
| `structure` | 结构 |

`tutor` 的 sub 不变（`analysis`/`explain`）。前端按当前 `store.mode` 决定接受哪些 panel；非法 panel 忽略。

## 5. 改动清单

### 5.1 coze 侧（`javatutor-coze/src`）

1. **`graphs/javatutor/prompts.py`**
   - `SYSTEM_PROMPT_MAIN_AGENT`（~:111）追加「可导航面板清单 + 何时附 `【视角导航】` 卡片」：
     - 列出 §4 白名单（单/多文件两组）与规范名。
     - 规则：当某个面板能帮用户**直接定位到相关分析**时才附卡片；通常 1 个、最多 3 个；只放一个块；
       `sub` 仅供 `tutor`；不要为了导航而发消息，导航要融入回答。
     - 给出 §3 示例块格式。
   - `SYSTEM_PROMPT_CRITIC`（~:96）加一行：判断正文时**忽略** `【视角导航】`/`【编辑建议】` 结构化块；
     可校验 `panel` 是否在白名单、`sub` 是否仅用于 `tutor`，非法只算轻微问题（不判失败）。
   - `SYSTEM_PROMPT_REVISE`（~:108）加一行：修订时**保留**原回答的结构化块（`【视角导航】`/`【编辑建议】`），
     除非评审标记其非法。
2. **`graphs/javatutor/nodes.py`**（`build_final` ~:412）
   - 主 agent 产出 `state["answer"]`；`build_final` 在 answer 后追加 `【决策痕迹】`。
   - 已验证 `_strip_leaked_json`（~:358）只匹配 `intent`/`pass`/`tool` 开头 JSON，`{"views":...}` 不会被误删。
   - **仅建议、非必须**：在 `_strip_leaked_json` 或 `build_final` 加一条注释，说明 `【视角导航】` 块是受控指令、
     不可剥离。

### 5.2 前端（`javatutor/frontend/src`）

1. **合并「分析」页** — `components/AiTutorPanel.vue`
   - `tabs`（~:231）改为：`[{id:'explain',label:'解说'},{id:'analysis',label:'分析'}]`。
   - 把 `complexity` 块（~:113-134）与 `algorithm` 块（~:137-167）合并为**一个** `analysis` 块：复杂度卡片在上、
     算法/数据结构标签组在下，共用一个 `isAnalyzing`/`analysisError`/空态提示。
   - 保留 `explainTag`（点标签 → `activeAiTab='explain'`）。
   - `activeAiTab` 取值变为 `explain`|`analysis`；`stores/player.js` 的 `switchAiTab` 无需改。
2. **导航解析工具** — `utils/editSuggestion.js`
   - 新增 `NAV_MARK = '\n【视角导航】'`；`parseAssistantMessage` 返回增加 `nav` 字段
     （`{body, edits, nav}`，`nav = {views:[...]}`）。解析失败时块按正文展示。
   - 更新 `utils/editSuggestion.test.js`。
3. **剥离结构化块，避免 JSON 以正文显示** — `utils/decisionTrace.js`
   - `splitDecisionTrace` 在按 `【决策痕迹】` 切分得到 `body` 后，再剥掉 body 末尾的
     `【编辑建议】`/`【视角导航】` 块（取二者中最早出现的标记，从那里截断）。这同时修复了
     `【编辑建议】` 目前会以原始 JSON 渲染到 markdown 正文的既有隐患。
   - 更新 `utils/decisionTrace.test.js`。
4. **导航卡片组件** — 新建 `components/NavSuggestionCard.vue`
   - 参考 `components/EditSuggestionCard.vue`：每个 view 渲染一个按钮，文本取 `label` 或 panel 规范名；
     点击调用 `store.navigateTo(panel, sub)`。
5. **渲染导航卡片** — `components/AiTutorPanel.vue`
   - `parsedMessages` computed 由 `parseAssistantMessage` 返回 `nav`。
   - 在 assistant 气泡里 `EditSuggestionCard` 旁（~:58-61）加
     `<NavSuggestionCard v-if="parsedMessages[i].nav.views.length && !store.isExplaining" .../>`。
6. **导航动作** — `stores/player.js`
   - 新增 `navigateTo(panel, sub)`：
     - 单文件：`switchRightTab(panel)`；`panel==='tutor' && sub` 时设 `activeAiTab=sub`。
     - 多文件：设 `store.multiTab = panel`（见下）；`panel==='tutor' && sub` 时设 `activeAiTab=sub`。
   - **关键：多文件右侧标签目前是 `components/MultiFileShell.vue` 本地 `multiTab` ref（~:142），不是 store 状态**；
     store 里的 `multiRightTab`/`switchMultiRightTab`（`player.js` ~:59,505）是死代码且白名单不一致。
     为让导航能进多文件模式并消除死代码，**把 `multiTab` 提升到 store**：
     - store 新增状态 `multiTab:'datastructure'`（替换/停用 `multiRightTab`），
       `switchMultiRightTab` 白名单改为
       `['variables','flow','datastructure','callgraph','classdiagram','structure','algorithm','tutor']`。
     - `components/MultiFileShell.vue` 删除本地 `const multiTab = ref('datastructure')`，改用 `store.multiTab`；
       `switchTab`/`switchGroup`/`rightGroup` computed 同步改用 `store.multiTab`。
   - `activeAiTab` 是全局的，故内嵌与浮动面板会一起切——已知、可接受。

## 6. 验收标准

1. 单文件模式跑代码后，在 agent 问「把内存状态/分析打开」等，回答尾部含 `【视角导航】` 块，前端渲染出可点击卡片，
   点击后右侧 INSPECT 切到对应面板（含 `tutor`+`analysis` 子 tab）。
2. 多文件模式同理，可导航到 `callgraph`/`classdiagram`/`structure`。
3. `【视角导航】`/`【编辑建议】` 块不会以裸 JSON 出现在 markdown 正文。
4. agent 面板合并后为「解说 | 分析」两个子 tab；复杂度卡片 + 算法/数据结构标签都在「分析」页。
5. 非法 `panel`/`sub` 被忽略不报错；无导航块时行为与现状一致。

## 7. 测试

- 前端：`editSuggestion.test.js`（nav 解析/失败回退）、`decisionTrace.test.js`（块剥离）、
  `AiTutorPanel`/卡片相关、`player` 的 `navigateTo`（单/多文件）用例。
- coze：`pytest` 图/主 agent 相关用例（prompt 变更不破坏现有契约）；跑通一次 L2 coze 单测。

## 8. 备注

- 不触碰 `javatutor/frontend/src/backup-20260807/AiTutorPanel.vue`（备份副本，含同款 tab 结构）。
- 右下角算法教程 toast（`AlgoTutorialToast`）本阶段不改，仅确认「以用户点击为准」。
