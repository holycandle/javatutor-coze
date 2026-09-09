# 视角导航 + 「分析」页合并 计划 Review

> 对应 plan：`docs/plan/2026-09-07-coze-agent-view-navigation-plan.md`
> 审查日期：2026-09-07

## 结论

计划整体可执行、与现有数据流一致，同意进入执行。发现 **2 项低危韧性缺口**（建议修复后落地），
另有 **1 项疑似高风险项经复核确认非问题（已排除）**。其余关键路径均已验证正确。

## 关键路径验证（通过）

| 项 | 结论 |
|---|---|
| `【视角导航】` 块不被 `_strip_leaked_json` 剥离 | ✅ 只匹配 `intent`/`pass`/`tool` 开头 JSON，`{"views":...}` 透传 |
| `parseAssistantMessage` 语义保持 | ✅ 新 `extractStructBlocks`（从最后一块往前剥）兼容既有「JSON 损坏→正文」「edits 空→正文」「缺字段过滤」「空输入」用例 |
| `splitDecisionTrace` 复用不引入环形依赖 | ✅ `editSuggestion.js` 不 import `decisionTrace.js` |
| `multiRightTab`/`switchMultiRightTab` 死代码 | ✅ 仅存在于 `player.js:59,505`，替换安全；`MultiFileShell.vue` 用本地 `multiTab` ref（:142），需提升到 store |
| 卡片渲染位置（疑似崩溃项） | ✅ **已排除** —— 见下 |
| `navigateTo` 走 `switchRightTab`/`switchMultiTab` 白名单 | ✅ 两 action 均含白名单，非法 panel 不会误切到不存在页 |

## 疑似高风险项：已排除（非 bug）

**卡片位于 assistant-only `v-else` 内，用户消息不会触发 `nav` 越界。**

- **初判**：`parsedMessages` 的非 assistant（用户消息）分支返回 `{ body, edits }` 无 `nav`，而
  `v-if="parsedMessages[i].nav.views.length"` 会对用户消息 `undefined.views` 抛 `TypeError`。
- **复核**：`AiTutorPanel.vue` 模板中用户消息走 `v-if="m.role === 'user'"`（:46），assistant 走 `v-else`（:47-67）；
  NavSuggestionCard 位于 `v-else` 内（:62-65），**仅对 assistant 消息求值**。用户消息不进入该分支，故不会访问 `nav`。
- **结论**：原作者（plan）「`parsedMessages` 无需改动」表述正确，**不必**给用户消息分支补 `nav`。

> 注：审查期间曾尝试在 plan 里给 `parsedMessages` 用户分支补 `nav: {views:[]}`，复核确认非必需，已撤回 plan 相关改动。
> 若未来把卡片移到 `v-for` 层级或 chat-body 外层（脱离 assistant `v-else`），则需补上，此处仅记录。

## 需修复项

### P2（低危，建议执行前修）：`NavSuggestionCard` 按当前模式过滤 panel，避免死按钮

- **位置**：plan Task 7 `NavSuggestionCard.vue` script。
- **问题**：`extractStructBlocks` 仅按 `typeof panel === 'string'` 过滤，未按当前 `store.mode` 白名单校验。
  单文件模式下若 agent 违规发出多文件 panel（如 `callgraph`/`classdiagram`/`structure`），卡片仍渲染按钮，
  点击后 `navigateTo` → `switchRightTab('callgraph')` 因不在 `['variables','flow','datastructure','algorithm','tutor']`
  白名单而静默空操作——「点开无反应」的死按钮。
- **建议修复**（组件内按 mode 裁剪，模板改用 `visible`）：
```js
const SINGLE = ['variables','flow','datastructure','algorithm','tutor']
const MULTI  = ['variables','flow','datastructure','callgraph','classdiagram','structure','algorithm','tutor']
const visible = computed(() => (props.views || []).filter(v => (store.mode === 'multi' ? MULTI : SINGLE).includes(v.panel)))
```

### P3（低危，建议执行前修）：`navigateTo` 对 `sub` 加白名单，避免 agent 面板空白

- **位置**：plan Task 9 `player.js` `navigateTo`。
- **问题**：`if (panel === 'tutor' && sub) this.activeAiTab = sub` 未校验 `sub` 取值。若 agent 发出
  `sub: "bogus"`，`activeAiTab` 变成既非 `'explain'` 也非 `'analysis'` 的值，`AiTutorPanel` 两层 `v-if`
  均不命中 → agent 面板正文空白。
- **建议修复**：
```js
if (panel === 'tutor' && ['analysis', 'explain'].includes(sub)) this.activeAiTab = sub
```

## 建议处理方式

- 两项均为「LLM 违反 prompt 约束」的韧性防御，非必然触发的构造性缺陷。
- 执行组按当前 plan 落地时，建议在写 `NavSuggestionCard.vue` / `player.js` 时把上述两处防护一并带上（开销极小）。
- 其余路径无需改动，可直接按 plan 落地。是否采纳 P2/P3 由执行组/负责人决定，本文档只记录审查结论。

## 文档登记

- 对应 plan：`docs/plan/2026-09-07-coze-agent-view-navigation-plan.md`（本次审查**未直接改动 plan**，结论以本文档为准）
- 关联 spec：`docs/spec/2026-09-07-coze-agent-view-navigation.md`
