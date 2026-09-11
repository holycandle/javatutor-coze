# Coze Agent 代码优化（优化卡 + 报错预填）（2026-09-10）

> 一句话：让 agent 不止「解释代码」还能**改进代码**——复用 `【编辑建议】` 块加 `kind` 判别，实现
> **两步式**（方案卡选目标 → 整文件覆盖）、**门禁**（候选先真跑一次才允许应用）、**可撤销**（Monaco undo 优先 + 快照回退），
> 并在控制台面板加一个**只预填不发送**的报错入口。

执行依据：`docs/plan/2026-09-10-coze-agent-code-optimization-plan.md`（决策 D1–D11 见 `docs/spec/2026-09-10-coze-agent-code-optimization.md` §2）。

## 1. 背景

`/grilling` 收敛出的关键判断：**优化不是工具，是输出指令**——agent 没有写入通道，未知工具在 `main_agent` 直接落「不可用」分支。
因此整条链路复用既有「文末结构化块」形态：一份 mark / 一个解析器 / 一套 apply-undo 通道。

## 2. 改动清单

### A. 前端（`javatutor/frontend`）

| 文件 | 改动 |
|---|---|
| `src/utils/editSuggestion.js` | 新增 `GOALS` 闭集、`buildGoalPrompt(goal, detail)`、`normalizePlan(parsed)`；`extractStructBlocks` 按 `kind` 分支（`patch` 现状 / `options` / `replace`），返回值增 `plan`；`parseAssistantMessage` JSDoc 同步 |
| `src/utils/optimization.js` | **新建**：`resolveTarget` / `buildGateRequest` / `readGateResponse` / `pickApplyMode` / `SNAPSHOT_UNDO_CONFIRM`（与组件分离，便于单测——本仓无 DOM 测试环境） |
| `src/components/OptimizationCard.vue` | **新建**：`options` 方案卡（点目标即发新一轮提问）、`replace` 卡（门禁状态 + 应用 + 撤销）。`EditSuggestionCard.vue` **不动**（patch 路径零回归） |
| `src/components/AiTutorPanel.vue` | 渲染 `OptimizationCard`；`chatInput` 局部 ref → `store.chatDraft`；`parsedMessages` 的用户消息回退补 `plan: null` |
| `src/stores/player.js` | 新增 `chatDraft` / `lastRunError` 状态；新增 `applyCandidateRun`（**返回**覆盖前运行快照）/ `restorePreviousRun(快照)` / `askGoalOptimization`；`runCode`/`runProject`/`applyRunResult` 写 `lastRunError`（成功分支清空） |
| `src/components/SingleFileShell.vue` | provide `getCode` / `restoreCode` |
| `src/components/MultiFileShell.vue` | provide `getCode(target)` / `restoreCode(code, target)`（按文件名读写 + 切到该文件） |
| `src/components/ConsoleOutput.vue` | 报错入口（常驻、折叠时仍在；点击只写 `store.chatDraft`） |

### B. coze（`javatutor-coze`）

| 文件 | 改动 |
|---|---|
| `src/graphs/javatutor/prompting/optimization.py` | **新建**：`GOALS` 闭集 + `render_optimization_guidance()`（两步式、kind 形态、`code` 完整性、`target` 规则、patch 不受影响） |
| `src/graphs/javatutor/main_agent.py` | `_main_system_prompt()` 注入 `render_optimization_guidance()`（顺序：nav → algo → usage → optimization → ui_map → few-shot） |
| `src/graphs/javatutor/prompts.py` | `SYSTEM_PROMPT_CRITIC`：忽略 `【编辑建议】` 的 kind 与 code，不得判失败；`SYSTEM_PROMPT_REVISE`：**原样保留**结构化块 |
| `src/graphs/javatutor/prompting/main_fewshots.py` | 增两步式样例 2 条（`options` / `replace`），JSON 用 `json.dumps` 生成以保证转义正确 |
| `tests/test_optimization_guidance.py` | **新建**：goal 闭集跨仓一致、两步式与 kind 约束、few-shot JSON 合法且 goal 落在闭集、主系统提示注入、critic/revise 覆盖 |

### C. 文档

- `docs/spec/2026-08-10-coze-agent-interface.md`：新增 §2.2「编辑建议块（kind）」。
- `docs/agent-collaboration-guide.md`：输出契约补 `【编辑建议】` 块（patch/options/replace）与协议指针。
- `docs/spec/2026-09-10-coze-agent-code-optimization.md` §7.1 已按 B1/B2 同步（新建组件 + 合成整文件 edit）。
- 后端 `javatutor/backend` **未改动**（报错走预填 → `user_question`；门禁复用既有 `/api/run`、`/api/run/project`）。

## 3. 关键实现点

- **整文件覆盖 = 一条 `old_string` 为「当前全文」的 edit**（plan §0.1 B2）：`planEdits` 全文唯一匹配 → `status:'ok'` →
  `executeEdits` 覆盖全文，**天然是单个 undo 单元**，`undoToken` 语义原样可用；编辑器为空时 `planEdits` 返回 `not-found`，退回 `restoreCode`。
- **门禁在卡片内直接 `fetch`**，绕开 `runCode`：后者会置全局 `isLoading`（「运行中…」遮罩）、写红色 toast，并**清空 `chatMessages`**。
- **`applyCandidateRun` 与 `applyRunResult` 的区别**：前者**不**重置会话状态（`chatMessages`/`explainHistory`/`activeAiTab`/`explainError` 全不动），
  否则应用一次优化会清空整个聊天记录；同时**返回**覆盖前的运行快照供撤销回退（见 §7 R2，快照由卡片自持，非 store 单槽）。
- **报错入口不挂 `GlobalStatus`**：那个 toast 6 秒自动消失并置 `store.error = null`；入口改挂控制台面板，`lastRunError` 只在下次成功运行时清。
  入口在「内存状态」pane、输入框在「agent」pane，两个 pane 互斥 → 点击时同步 `navigateTo('tutor')`（见 §7 R1）。
- **`getCode`/`restoreCode` 走 Shell**：编辑器内容才是权威来源（`store.code` 只在 run 时写入，可能落后于未保存编辑）。

## 4. 与计划的偏差（已定，spec/plan 以本节为准）

| # | 计划原文 | 实际实现 | 理由 |
|---|---|---|---|
| **B3** | 「撤销 = Monaco undo 优先 + 快照回退」（未区分模式） | **多文件一律走快照**（`pickApplyMode('multi') === 'snapshot'`），Monaco 全文覆盖只用于单文件 | 多文件下 Monaco 只持有**当前激活文件**：跨文件整份替换必须写 `files[i].code`，会触发 `setCode` 重载编辑器、model 版本号变动，undo 单元必然失效。与其做一次注定失败的 undo 尝试，不如直接走快照路径（spec D10 的「快照回退」本就在其列） |
| — | 「卡片三分支渲染」单测 | 改为 `utils/optimization.test.js` 的**纯函数单测**（目标解析/门禁请求体/响应判定/应用方式） | 本仓无 `@vue/test-utils`，无 DOM 测试环境；把有风险的分支判定抽成纯函数比引入组件测试依赖更贴合现状 |
| — | 卡片 `v-if="plan && !store.isExplaining"` | `v-if="plan && (i !== last \|\| !store.isExplaining)"` | 原条件会在每次新提问（`isExplaining` 翻转）时**卸载重挂**所有历史优化卡 → 门禁重跑、`applied`/`undoToken` 状态丢失。仅放宽优化卡，patch 卡保持原条件（零回归） |

## 5. 测试

| 套件 | 改动前 | 改动后 |
|---|---|---|
| 前端 `npm test` | 249 passed（23 files） | **295 passed（25 files）**（291 + review 处理的 4 条，见 §7） |
| coze `uv run pytest -q` | 217 passed | **226 passed** |
| `npm run build` | — | 通过（SFC 编译无误） |
| `scripts/sync_panel_manifest.py` | EXIT=0 | EXIT=0（本次未动 manifest，无 drift） |

新增用例要点：
- `editSuggestion.test.js`：`options`/`replace` 解析、非法 kind 回落 patch、`plan` 非空时 `edits` 为空、空输入含 `plan:null`、`buildGoalPrompt`。
- `optimization.test.js`：多文件 `target` 缺失 → `missing-required`、找不到 → `not-found`（不得静默落到激活文件）、门禁请求不改动原 `files`、`canApply` 组合判定（§7 R4）。
- `player-optimization.test.js`：`applyCandidateRun` **不清**会话状态、`restorePreviousRun` 往返、**两张卡依次应用再依次撤销各回各的快照**（§7 R2）、`lastRunError` 写/清、`askGoalOptimization` 模板拼提问。
- coze `test_optimization_guidance.py`：goal 闭集**真读前端文件**比对（§7 R3）、两步式与 kind 形态、few-shot 样本 JSON 合法且 `options` 的 goal 全在闭集。

## 6. 已知局限 / 待手验

- **门禁只能验「能跑」**（spec §6.1）：验不了「有没有偷改语义」，用前后对比（输出/步数）部分补偿，无自动语义等价判定。
- **多文件门禁可能漏掉「当前激活文件的未保存编辑」**：门禁用的是 `multiState.files`（切文件时保存），
  若用户正在编辑 A 文件而优化目标是 B，A 的未保存内容不参与门禁。影响面小（B 被替换、其余取已保存版本）。
- **长文件整份 JSON 转义失败率**（D11）：失败表现是「不出卡」，不会崩；若线上失败率高，再补「围栏回退解析」。
- **快照回退会丢弃用户此后的编辑**：已用 `confirm` 明示「将丢弃此后的编辑」；`editor.setValue` 可能重置 undo 栈，回退后 Ctrl+Z 未必能退回「优化后」那一版（有确认框兜底，可接受）。
- **`lastRunError` 生命周期**：只在下次成功运行时清；反复看同一错误时入口会一直在（如需可加手动关闭）。
- **发布前必做**：coze 侧改动需**重新发布 agent** 才生效；前端 `npm run dev` 热载即可。

### 手验清单（`npm run dev`）

1. 跑一段可优化代码 → 问「帮我优化一下」→ 回答附**方案卡**（2–3 个目标），正文与块内**无代码**。
2. 点「以性能为先」→ 消息列表出现模板提问 → 第 2 轮回答附 **replace 卡**（独立卡片，渲染在正文下方）。
3. 卡片「校验中…」→「校验通过」→ 点「应用」→ 编辑器整份替换、右侧面板刷新为候选运行结果。
4. **【必测·R4】** 点「撤销」（未编辑）→ 精确回滚；再应用一次 → **手打一个字符** → 点「撤销」→ 出现 **`window.confirm`** 提示
   → 取消（代码不变）→ 再点一次 → 确认后回退。这条是唯一未被自动化覆盖的高风险分支。
5. 门禁反例：构造 `code` 编译不过的 replace 块 → 卡片显示错误、「应用」禁用。
6. 报错预填：写编译不过的代码 → 运行 → 控制台面板出现入口（**等 10 秒仍在**）→ 点击 → **右栏自动切到「agent」**、
   输入框被预填、**未发送**（R1）。
7. 多文件：优化 `target` 指定的文件 → 应用后切到该文件且内容被替换；`target` 不存在 → 卡片提示且禁用应用。
8. 降级不崩：`kind` 非法、`options` 为空、`code` 为空 → 块按正文展示，无卡片、无报错。
9. 多张优化卡：先应用卡 A、再应用卡 B → 先撤销 B（右侧回到 A 后）→ 再撤销 A（右侧与编辑器都回到 A 前，**不能**停在 B 前）（R2）。

## 7. Review 处理（2026-09-10，`docs/reviews/2026-09-10-coze-agent-code-optimization-review.md`）

review 结论为不阻断合并，R1/R2 建议发布前处理。本轮 R1–R5 **全部处理**：

| # | 严重度 | 处理 | 落地 |
|---|---|---|---|
| **R1** | 中 | ✅ 修 | `ConsoleOutput.prefillFix()` 末尾加 `store.navigateTo('tutor')`。入口在「内存状态」pane、输入框在「agent」pane，两个 pane 互斥 `v-show`，不切 tab 则交互闭环断开（点了无任何可见反馈）。`tutor` 面板在 single/multi 均可用（manifest 未限 `mode`），两模式通用 |
| **R2** | 中 | ✅ 修 | 运行快照改为**卡片自持**：`applyCandidateRun` 返回它记录的快照（不再写 store 单槽 `previousRun`，该 state 字段一并删除），`restorePreviousRun(prev)` 改为显式入参，卡片存 `appliedRunSnapshot` 并在两条撤销路径（Monaco undo / 快照回退）都回传。原单槽在「连续应用两张卡再依次撤销」时会回填错位的运行结果，并使 `store.code` 与编辑器内容不符 |
| **R3** | 低 | ✅ 修 | `test_goal_enum_matches_frontend` 不再比对手抄副本 `FRONTEND_GOALS`（已删），改为按 `test_panel_sync.py` 的跨仓读法直接从 `../javatutor/frontend/src/utils/editSuggestion.js` 解析 `export const GOALS` 字面量；文件不存在时 `pytest.skip`。**未**采纳「把 goal 闭集并入 `ui-panel-manifest.json`」的彻底做法——闭集只有 5 项、改动面小，跨仓直读已能挡住静默降级 |
| **R4** | 低 | ✅ 修 | `canApply({targetBlocked, gate, applied})` 抽成 `utils/optimization.js` 纯函数、组件改为调用它，并补 4 条单测（门禁 idle/running/fail、目标被拦截、已应用）。`window.confirm` 分支保持手验，清单第 4 条已标注**【必测】** |
| **R5** | 极低 | ✅ 修（选「删」） | `lastRunError` 只留 `{ message }`：`code`/`mode` 无任何消费者，且多文件下 `code` 取的是 `store.code`（激活文件）而非整个项目、语义片面。若将来要把代码一并附给 agent，应走 Shell 的 `getCode`。spec §5 已同步 |

同步的文档：spec §5（`lastRunError` 形态 + 点击切面板）、spec §6.2（运行快照卡片自持及其理由）、本 devlog §2/§3/§5/§6。

验证：前端 **295 passed（25 files）**、coze **226 passed**、`npm run build` 通过。**仍未做**：`npm run dev` 手验清单 1–9、coze 侧重新发布 agent。
