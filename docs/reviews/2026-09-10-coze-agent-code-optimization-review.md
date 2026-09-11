# Coze Agent 代码优化（优化卡 + 报错预填）Review

> 对应 spec：`docs/spec/2026-09-10-coze-agent-code-optimization.md`
> 对应 plan：`docs/plan/2026-09-10-coze-agent-code-optimization-plan.md`
> 实现 devlog：`docs/devlog/2026-09-10-coze-agent-code-optimization.md`
> 审查日期：2026-09-10（跨仓：`javatutor/frontend` + `javatutor-coze`）

## 结论

实现与 spec/plan 一致，**双端全绿，可合并**；后端按设计零改动。三处计划外偏差（B3 多文件一律走快照、纯函数单测替代组件单测、优化卡 `v-if` 放宽）均已核对，**理由成立且优于原计划**，其中 `v-if` 放宽避开了一个必然触发的重挂陷阱。

未发现阻断性问题。**R1、R2 已在 review 后当日修复并提交**（前端 `80f3136`，详见下）；其余为守卫强度与测试覆盖的加固建议。手验清单 8 条与 coze 侧重新发布仍待执行。

> **更新（2026-09-10 联调后）**：R1 已修（`prefillFix()` 追加 `store.navigateTo('tutor')`）、R2 已修（运行快照改为**卡片自持**：`applyCandidateRun` 返回快照，`restorePreviousRun(prev)` 显式入参，`previousRun` 单槽状态删除）。联调另发现两处新问题并已收敛为独立计划：
> ① 方案卡**单选** + 提问用「以 X 为**优先**」（软措辞）导致「选的方向不约束产出」→ `docs/plan/2026-09-10-coze-agent-optimization-goal-binding-and-error-entry-fix-plan.md`（F1–F3，多选 + 硬约束 + 显式排除未选项）；
> ② R1 只解决了「点了看不到反馈」，未解决「在别的页面看不到入口」→ 同计划 F4（入口搬到全局红色弹窗并常驻）。
> 另新增功能计划：`docs/plan/2026-09-10-coze-agent-run-timeline-plan.md`（运行不清空对话 + 记录点回退）。

> **更新（2026-09-10 计划执行后）**：上述两份计划已落地，本 review 的 R1/R2 由此闭环——
> **问题 ② 是 R1 的加强版**（R1 只解决「点了看不到反馈」，本计划 F4 解决「在别的页面看不到入口」）：
> 入口整体搬到常驻的全局红色弹窗（`GlobalStatus.vue`），控制台那份删除（单入口），并让**运行类**错误不再 6 秒自动消失。
> 前端登录点从 `ConsoleOutput` 迁到 `GlobalStatus`，即 review 时所在的位置已不存在，R1 的修复点随代码一起删除了。
> 实现记录见 `docs/devlog/2026-09-10-coze-agent-optimization-goal-binding-fix.md`。

## 验证（全绿）

| 项 | 结果 |
|---|---|
| 前端 `npx vitest run` | ✅ 25 文件 / 291 用例（基线 23/249，+2 文件 +42 用例） |
| coze `uv run pytest -q` | ✅ 226 通过（基线 217，+9） |
| `npm run build` | ✅ 通过（SFC 编译无误，devlog 记录） |
| `scripts/sync_panel_manifest.py` | ✅ exit=0，无 drift（本次未动 manifest） |
| 后端 `javatutor/backend` | ✅ 未改动（符合 spec §7.3） |

关键一致性核对（逐条比对实现两处，而非只看测试绿）：

- **门禁判定与真实运行路径同源**：`utils/optimization.js readGateResponse` 的成功条件 `data.code === 200 || data.success` 与 `stores/player.js:176 applyRunResult` **逐字一致** → 不存在「门禁说通过、点应用后却报错」的口径分裂。这是本设计最容易踩的坑，实现正确。
- **`applyCandidateRun` 确实不清会话**：`chatMessages`/`explainHistory`/`activeAiTab`/`explainError` 全未触碰（对照 `applyRunResult` 的 :104-111、:146-148 重置段），并由 `player-optimization.test.js` 断言锁定。
- **多文件 watcher 路径**：`splitter` 两侧均验证——target 为激活文件时 `activeFileIndex` 不变但 `activeCode` 变化 → watcher 触发且 `oldIdx === newIdx` 跳过保存 → `setCode` 载入候选；target 为其他文件时 `restoreCode` 先写 `files[i].code` 再切 `activeFileIndex` → 旧文件被保存、新文件被载入。两条路径都通。
- **`chatDraft` 提升彻底**：`AiTutorPanel.vue` 的局部 `chatInput` 已完全移除（无残留引用），`v-model` / `:disabled` / `sendChat` 三处统一走 store。
- **报错入口不挂 toast**：`console-error-bar` 位于 `ConsoleOutput.vue` 折叠切换之外，折叠时仍可见（对应 spec §5 的「不得 6 秒消失」）；`GlobalStatus` 未改动、`lastRunError` 不被它清除。

## 与 plan 的一致性（通过）

- **契约扩展**：`【编辑建议】` 加顶层 `kind`，`patch` 缺省向后兼容；`extractStructBlocks` 按 `kind` 分支，`plan` 非空时该块 `edits` 必为空（有专门用例）；非法 kind 回落 patch、非法 options 项丢弃、`options` 全非法/`code` 空 → 整块按正文。**§4.6 的降级语义逐条落实。**
- **两步式**：coze `render_optimization_guidance()` 明确「本步正文与块内都不得出现优化后的代码」、`goal` 闭集、`code` 不得 `...` 占位、`options` 与 `replace` 不同时出现；few-shot 给出第 1 轮（options）/ 第 2 轮（replace）两条样例，JSON 由 `json.dumps` 生成以保证转义正确。critic/revise 的「忽略结构化块 / 原样保留」两条防误伤规则均已加。
- **闭集与模板**：`buildGoalPrompt` 输出 `以「性能」为优先优化当前代码，具体要求：…。请给出优化后的完整代码。` 与 spec §4.4 模板逐字一致；多文件追加 `（目标文件：X）`。
- **`target` 三态**：`resolveTarget` 的 `ok` / `missing-required` / `not-found` 覆盖 spec §4.5，「多文件缺 target 不得静默落到激活文件」有专门用例。
- **报错入口只预填不发送**：`prefillFix()` 仅写 `store.chatDraft`，无发送调用。草稿模板与 spec §5 一致。
- **整文件覆盖 = 合成 edit**（plan §0.1 B2）：`applyAiEdits([{old_string: 当前全文, new_string: 候选}])` → `executeEdits` 单 undo 单元；`planEdits` 的空源码 `not-found` 与全文匹配两条边界均有新增用例。
- **文档登记**：接口契约 §2.2 新增（28 行）、`agent-collaboration-guide.md` 输出契约补 `【编辑建议】`、spec §7.1 已按 B1/B2 同步、devlog 齐备。

## 偏差确认（3 项，均成立）

| # | 偏差 | 判断 |
|---|---|---|
| B3 | 「Monaco undo 优先」在多文件降级为「一律快照」 | ✅ **正确**。Monaco 只持有当前激活文件，跨文件整份替换必须写 `files[i].code` 并触发 `setCode` 重载 → model 版本号必然变动 → 原 token 必然失效。做一次注定失败的 undo 尝试只会掩盖问题；spec D10 本就把「快照回退」列为合法路径。 |
| B1' | 卡片三分支单测 → `utils/optimization.js` 纯函数单测 | ✅ 合理。本仓无 `@vue/test-utils`/DOM 环境，把目标解析、门禁请求体、响应判定、应用方式抽成纯函数，恰好覆盖了风险最高的四处判定；`优化.test.js` 还断言了「不改动原 files（不就地变异）」这类易错细节。 |
| — | 优化卡 `v-if` 放宽为 `plan && (i !== last \|\| !isExplaining)` | ✅ **避坑**。原条件会在每次新提问（`isExplaining` 翻转）时卸载重挂全部历史优化卡 → 门禁重跑、`applied`/`undoToken` 丢失。patch 卡保持原条件，零回归。 |

## 发现的问题

### R1（中）- 报错入口点击后无任何可见反馈，且草稿落在不可见面板 —— ✅ 已修复（2026-09-10）

- **位置**：`ConsoleOutput.vue` `prefillFix()`；`SingleFileShell.vue:89-92`、`MultiFileShell.vue:84-87` 的 pane 划分。
- **现状**：`ConsoleOutput` 只在 `variables`（内存状态）pane 内渲染，而 agent 输入框在 `tutor`（Ask 组）pane —— 两个 pane 由互斥的 `v-show` 控制，**从不同时可见**。`prefillFix()` 只写 `store.chatDraft`，不切 tab、不聚焦（`input` 无 `ref`）。
- **影响**：用户点「让 agent 帮我看看」后画面毫无变化（草稿其实已写入，切到 Ask 才看得见）→ 交互闭环断开，功能形同失效。多文件模式没有浮动面板，必定如此；单文件模式的浮动面板默认收起，同样如此。
- **建议**：`prefillFix()` 末尾加一行 `store.navigateTo('tutor')`（该 action 已存在且两模式通用，见 `player.js:575`），或至少切到 agent 面板。spec §5 只规定了「只预填不发送」，未排除导航——补导航不违反「不替用户发送」。

### R2（中）- 多张优化卡依次撤销时，编辑器与右栏/`store.code` 错配 —— ✅ 已修复（2026-09-10）

- **位置**：`player.js:201-206 applyCandidateRun`（`previousRun` 为**单槽**）、`player.js:223 restorePreviousRun`、`OptimizationCard.vue:161/169/182`。
- **现状**：`previousRun` 是 store 级单槽，每次 `applyCandidateRun` 覆写。卡片 A 应用后（`previousRun = A 前`）再应用卡片 B（`previousRun` 被覆写为 `B 前 ≈ A 后`）；此后撤销卡片 A 时，`undoToken_A` 已因 B 的 `executeEdits` 失效 → 走快照路径 → `restoreCode(snapshot_A = A 前的代码)` + `restorePreviousRun()`（回填的是 **A 之后**的 steps/code）。
- **影响**：编辑器显示的是 A 前的代码，右侧面板显示的却是 A 之后那次运行的结果；且 `store.code` 停在 A 后 → **后续提问发给 agent 的 `source_code` 与编辑器内容不符**。触发路径很自然（先按性能优化、再按可读性优化、然后依次后悔），并非极端构造。
- **建议**：让运行快照像代码快照一样**由卡片自持**（对称即可消除单槽问题）——`applyCandidateRun` 返回它记录的 `previousRun`，卡片存为 `appliedRunSnapshot`，撤销时 `store.restorePreviousRun(该快照)`。改动约 4 行，且顺带修好 Monaco undo 路径上的同类错配。

### R3（低）- 跨仓 goal 闭集守卫实为第三份硬编码副本，挡不住前端单方面改动

- **位置**：`tests/test_optimization_guidance.py:15-26`。
- **现状**：`FRONTEND_GOALS` 是手抄的字面量，`test_goal_enum_matches_frontend` 只比较 **coze `GOALS` ↔ 这份副本**，从未读前端文件。前端把 `GOALS` 改成（例如）多一项 `concurrency`，本测试仍全绿。
- **影响**：闭集不一致的表现是**静默降级**——前端丢弃全部 option → 整块按正文显示裸 JSON 风格的文本，用户看到方案卡凭空消失，无任何报错。这正是本仓反复修过的那类「协议漂移」。
- **建议**：本仓已有现成先例——`tests/test_panel_sync.py:33-47` 直接从 `../javatutor/frontend/src/constants/ui-panel-manifest.json` 读前端文件做逐字比较。按同法从 `editSuggestion.js` 提取 `GOALS` 比较即可；更彻底的做法是把 goal 闭集并入 `ui-panel-manifest.json`，交由 `scripts/sync_panel_manifest.py` 单向同步（与视角导航的单一事实源一致）。

### R4（低）- `OptimizationCard` 状态机与 `window.confirm` 分支无自动化覆盖

- **位置**：`OptimizationCard.vue:73-79, 88, 134-185`。
- **现状**：`gate` / `canApply` / `applied` 的状态流转只靠手验清单第 3–5 条；`undo()` 的 `window.confirm` 分支无任何自动测试（纯函数套件无法表达）。devlog 已如实说明并给出理由。
- **影响**：可接受（风险最高的判定已抽入已测的纯函数），但「撤销」这个高风险动作恰好是覆盖最薄的一环。
- **建议**：把 `canApply` 这类组合判定再抽一层纯函数（如 `canApply({ targetBlocked, gate, applied })`）纳入现有单测；`confirm` 分支保留手验，但在清单中明确标注「必测」。

### R5（极低）- `lastRunError.code` / `.mode` 目前无消费者

- **位置**：`player.js:131, 168, 190`；`ConsoleOutput.vue prefillFix()`。
- **现状**：字段按 spec §5 保留（错误原文 + 代码 + 是否 test 模式），但 `prefillFix()` 只取 `message`；测试断言了字段存在，却无人证明其语义正确（例如多文件 `runProject` 的 catch 写入的是 `this.code`，即**激活文件**而非整个项目）。
- **建议**：若短期不用，注明用途或删掉；若打算「把代码一并附给 agent」，需先修正多文件下的语义（当前值对多文件是片面的）。

## 建议

- ~~R1 / R2 建议发布前处理~~ → **均已修复**（`80f3136`）。R1 只覆盖了「点了看不到反馈」，未覆盖「在别的页面看不到入口」，后者由新计划 F4 接手。
- R3 值得顺手做（守卫强度问题，成本约 10 行）；R4/R5 可选。
- 不阻断合并。**发布前必做**：① `npm run dev` 手验 devlog §6 清单 1–8（尤其第 4 条撤销的两种路径、第 6 条报错入口「等 10 秒仍在」）；② coze 侧改动需**重新发布 agent** 才生效。

## 文档登记

- 对应 spec：`docs/spec/2026-09-10-coze-agent-code-optimization.md`；对应 plan：`docs/plan/2026-09-10-coze-agent-code-optimization-plan.md`。
- 实现 devlog：`docs/devlog/2026-09-10-coze-agent-code-optimization.md`。
- 接口契约：`docs/spec/2026-08-10-coze-agent-interface.md` §2.2（本功能新增）。
- 若采纳 R2 的快照自持改法，需同步 devlog §3/§4 的 `previousRun` 描述与 `player-optimization.test.js`。
