# 优化方向绑定 + 对话时间线 Review

> 对应 plan：`docs/plan/2026-09-10-coze-agent-optimization-goal-binding-and-error-entry-fix-plan.md`（F1–F5）、
> `docs/plan/2026-09-10-coze-agent-run-timeline-plan.md`（T1–T7）
> 对应 devlog：`docs/devlog/2026-09-10-coze-agent-optimization-goal-binding-fix.md`、
> `docs/devlog/2026-09-10-coze-agent-run-timeline.md`
> 审查日期：2026-09-10（跨仓：`javatutor/frontend` + `javatutor-coze`）

## 结论

两份计划均已落地，**双端全绿，可合并**：前端 28 文件 / 340 用例、coze 229 通过、`npm run build` 无 SFC 编译告警、
`sync_panel_manifest.py` exit=0、后端未改动。

逐条比对实现与计划后，**两处「计划本身写错、实现改对了」的偏差（B1 快照过期、B3 `restoreSource` 缺失守卫）
判断成立且必要**；契约（模板措辞、goal 闭集、块形态）在前端、引导、few-shot、守卫测试四处逐字一致。
报错入口的单入口收敛干净，`watch(error)` 与「同文判据」的时序也是对的（见下）。

发现 1 个中危、2 个低危、2 个文档/边角问题，**均不阻断合并**：

- **R1（中）**：回退后**新**提问的问答会被折叠区吞掉——`foldFromIndex` 没有上界，回退之后追加的消息全部落在折叠区。
- **R2（低）**：`_runOpts` 是 store 级临时字段，两次运行重叠时 `silent` 会串味（计划里的「显式入参」方案免疫）。
- **R3（低）**：`isRunError` 的分流**实际恒为真**（`store.error` 只有运行路径会写），`TRANSIENT_ERROR_MS` 分支是死代码，
  devlog §4 声称的「网络抖动仍 6 秒淡出」不成立。
- **R4（低，文档）**：devlog §7 / plan D8 的「对话按模式分区」「跨模式回退 UI 不可达」两条已不成立。
- **R5（极低）**：`restoreSource` 用 `!cp.code` 判空，空文件快照会被静默拒绝。

## 验证（全绿）

| 项 | 结果 |
|---|---|
| 前端 `npx vitest run` | ✅ 28 文件 / 340 用例（plan 1 基线 25/295 → 26/312；plan 2 +28 → 28/340） |
| coze `uv run pytest -q` | ✅ 229 通过（基线 226，+3 守卫） |
| `npm run build` | ✅ 通过，无 SFC 编译告警（`v-if` + `v-show` 同元素合法，无 warning） |
| `scripts/sync_panel_manifest.py` | ✅ exit=0，无 drift |
| 后端 `javatutor/backend` | ✅ 未改动；plan 2 亦未触碰 coze 任何文件 |

## 关键一致性核对（比的是实现两处，不是只看测试绿）

- **白名单/黑名单取数不对称，且不对称得对**：白名单取**勾选项**的 `label`/`detail`，黑名单只取**同一张卡**的未选项
  （`OptimizationCard.submit()` 的 `sel`/`rest` 同源于 `props.plan.options`）。卡外方向不进黑名单，
  因此不会拼出「不要做正确性优化」这类荒谬约束——这正是 plan §4 的意图，实现无误。
- **模板措辞四处同款**：`只做「X」方向的优化` / `不要顺带做其他方向的改动（例如：…）` 同时出现在
  ①[前端模板](frontend/src/utils/editSuggestion.js)、②引导段、③few-shot 第 2 轮样例、④`test_optimization_guidance.py` 的断言里。
  ④ 里断言的是**整句** `不要顺带做其他方向的改动（例如：`，不是半句引用——这条是「agent 认不认得出用户提问模板」的唯一保险，写法正确。
- **goal 闭集是真跨仓读**：`test_goal_enum_matches_frontend` 从 `../javatutor/frontend/src/utils/editSuggestion.js`
  正则提取字面量后逐字比较（review R3 的修法），本次新增 `comprehensive` 后该测试仍绿 = 两侧同步无误；
  另有 `set(CARD_GOALS) | {"comprehensive"} == set(GOALS)` 保证方案卡闭集不漏不多。
- **多文件三步替换确实规避了 D6**：逐行核对 `MultiFileShell.vue` 的 watcher——
  `oldIdx >= 0 && oldIdx < files.length` 才保存；第 1 步 `activeFileIndex = -1` 时 `activeCode` 为 `null`
  （computed 显式 `idx < 0 → null`），第 2 步整体替换后下标仍为 `-1`（key 不变、不触发），
  第 3 步 `oldIdx === -1` → **跳过保存**、仅 `setCode` 载入新内容。三步的必要性成立。
- **分割线是真实消息 + 折叠走 `v-show`**：`chatMessages` 只有追加、无过滤/重排，
  `OptimizationCard` 的 `v-if`（依赖 `i !== length - 1`）与挂载状态因此不受影响；`TimelineDivider` 自身也套了 `v-show`
  （回退点**之后**的分割线同属折叠区），语义正确。
- **报错入口单入口收敛干净**：`ConsoleOutput.vue` 的模板块、`shortError` computed、`prefillFix()` 与 `.console-error-*`
  样式全部移除、无残留引用；`store.lastRunError` 状态本身保留（`GlobalStatus` 在用）。
- **同文判据的时序是对的**（易错点）：`watch(error)` 默认 pre-flush，`error` 与 `lastRunError` 是同步连续赋值，
  回调执行时读到的已是**新**的 `lastRunError`。若有人日后把该 watch 改成 `flush: 'sync'`，判据会读到旧值而失效——建议加一行注释锁住。
- **`visibleError` 常驻不会挡操作**：`.global-error` 是 `position: fixed` 的小条（`max-width: 92%`、高度自适应），
  不是全屏遮罩，常驻不影响点击。

## 偏差确认（6 项，均成立）

| # | 偏差 | 判断 |
|---|---|---|
| B1（timeline） | 计划写 `timeline.shift()` + `oldest.expired = true`；实现改为**只丢最旧活跃记录的代码快照**，记录留在数组 | ✅ **实现纠正了计划的 bug**。`shift()` 已把对象移出数组，标记落在一个被丢弃的对象上；而分割线要靠 `cp.id → cp` 才能渲染「记录已过期」并置灰按钮，记录被移走那条分割线就渲染不出来（`TimelineDivider` 的 `v-if="cp"`）。计划 Task 3 的两条断言本身也自相矛盾（「最旧一条 `expired === true`」与「`length` 仍为 MAX」不可兼得），实现取的一版正确，代价（数组不设硬上限）已记入 devlog §7。 |
| B2 | `TimelineDivider.cp` 由 `required: true` 改为 `default: null` + 取不到不渲染 | ✅ 合理。`cpOf()` 找不到时为 `null`，`required` 只会刷警告并不阻止抛错，`v-if="cp"` 才是真正的防线。 |
| B3 | `restoreSource` 由「可选链 + `ok === false` 才返回」改为「先 `if (!restoreSource) return`，再 `await`」 | ✅ **必要**。按计划写法，拿不到通道时会「只重跑、不回写代码」→ 编辑器旧代码 + 右栏新结果，**正是本功能要消灭的错配**；且多文件的 `restoreSource` 是 async，不 `await` 会在文件替换前就发起重跑。 |
| B4 | 折叠占位由「下标 `=== foldFromIndex` 的条目之后」改为「在 `foldFromIndex` 处那条分割线内部渲染」 | ✅ 语义等价（分割线即该下标的条目，且自身不折叠），少改一处 `v-if` 链。 |
| B5 | `silent` 的清理时机由「成功分支末尾」改为 `finally` | ✅ **必要**。失败/异常路径不清会让 `silent` 泄漏到下一次真实运行 → 那次**不建点**，正是最难排查的静默丢失。 |
| B6 | 除新增 `player-timeline.test.js` 外，另改 `player-optimization.test.js` 一处断言 | ✅ 合理且更明确：`applyCandidateRun` 现在会追加分割线，原断言 `chatMessages.length === 2` 必挂；改为「原两条仍在 + 末尾是 divider」，保住了「不清会话状态」这一被测语义。 |

## 发现的问题

### R1（中）回退后**新**提问的问答会被折叠区吞掉 —— 待修

- **位置**：`utils/timeline.js:47-61`（`foldStartIndex`/`isFolded`/`foldedCount`）、`player.js:327`（`revertToCheckpoint` 只设起点不设终点）、
  `player.js:406`（`askQuestion` 不碰 `foldFromIndex`）、`AiTutorPanel.vue:52`（普通消息 `v-show="!isFoldedIndex(i)"`）。
- **现状**：`foldFromIndex` 是**无上界**的——`isFolded(i) = i >= foldFromIndex + 1`。回退后用户**再次提问**，
  `askQuestion` 把 user/assistant 两条 push 到数组末尾，下标必然 `> foldFromIndex` → 一并被折叠。
  已用纯函数实测确认：`foldFromIndex = 2` 时，下标 5、6（回退后的新问答）`isFolded === true`。
- **影响**：用户回退到 #1 → 输入框提问 → **看不到自己的问题，也看不到回答**（只有 `chat-stage` 状态文字在折叠区之外，还能动），
  必须点一次「展开」才恢复。而 T3 折叠的初衷是「不让**关于已不存在的代码**的问答干扰阅读」**——回退之后的新问答恰恰是关于当前（已回退）代码的**，
  把它折叠起来与设计意图相反。触发路径很自然（回退→对着回退后的代码提问），不是极端构造。
- **建议**：给折叠加终点，而不是去掉折叠——`revertToCheckpoint` 里多存一个 `foldTo = this.chatMessages.length - 1`
  （回退时刻的最后一条），`isFolded(i)` 改为 `i > foldFromIndex && i <= foldTo`、`foldedCount = foldTo - foldFromIndex`，
  「展开」同时清两个字段。改动集中在 `utils/timeline.js` 三个纯函数 + 一处调用，现有用例按新签名补参数即可。
  最小替代方案：在 `askQuestion` 开头 `this.foldFromIndex = null`（等价于自动展开），一行但会丢掉折叠意图。

### R2（低）`_runOpts` 是 store 级临时字段，运行重叠时会串味

- **位置**：`player.js:124/154`、`player.js:170/195`、`player.js:215`。
- **现状**：`silent` 通过 `this._runOpts` 在 `runCode`/`runProject` 与 `applyRunResult` 之间传递。
  第一次运行的响应若在第二次运行**已写入 `_runOpts` 之后**才被处理，`applyRunResult` 读到的就是第二次的 `silent`：
  真实运行**不建点**、回退的静默重跑反而**建点并清掉折叠**。可行路径：运行中（`isLoading`）点某个历史分割线的「回退到此」——
  运行按钮有 `:disabled="store.isLoading"`，但 `TimelineDivider` 的按钮**没有** disable。
- **影响**：偶发、难复现的「多出一条记录点 / 少一条 / 折叠莫名解除」。不致命，但属于「最难排查」那类。
- **建议**：改用计划里的**选项 A**——`applyRunResult(data, opts)` 显式入参，两处调用点传各自的 opts，临时字段删掉；
  或在回退按钮上加 `:disabled="store.isLoading"`（治标，但成本一行）。

### R3（低）`isRunError` 的分流实际恒为真，6 秒分支是死代码（且 devlog §4 的说法不成立）

- **位置**：`utils/errorEntry.js:12-22`、`player.js`（`this.error` 的写入点）。
- **现状**：全仓 `store.error` 的写入点只有 4 处：`runCode`/`runProject` 开场置 `null`、两处 catch、
  `applyRunResult` 失败分支（另有 `resetMultiRun` 置 `null`）——**AI 流错误走的是 `explainError`，从不写 `store.error`**。
  也就是说 toast 能显示的每一条错误都同时写了 `lastRunError` 且同文 → `shouldAutoDismiss` 恒返回 `false`，
  `TRANSIENT_ERROR_MS` 与那个 `setTimeout` 永远走不到。
- **影响**：功能上没错（运行类错误常驻正是 F4 要的），但 devlog §4 的「后者仍 6 秒淡出（否则一次网络抖动会留下常驻弹窗）」
  **说反了**：`runCode` 的 catch 是对 `fetch` 的，网络抖动**正是**运行类错误 → 会留下常驻弹窗，恰是它声称要避免的情况。
  另外这段分流代码现在是无收益的复杂度。
- **建议**：二选一并同步文档——①删掉 `shouldAutoDismiss`/`TRANSIENT_ERROR_MS`（承认「错误 toast 一律常驻」）；
  或 ②把「网络异常」划出运行类错误（如 catch 里不写 `lastRunError`，或给 `lastRunError` 加 `transient: true`），
  让分流真的起作用。倾向 ②：`Failed to fetch` 对用户没有可操作性，不该钉在屏幕上。

### R4（低，文档）「对话按模式分区」「跨模式回退不可达」两条已不成立

- **位置**：devlog（timeline）§7 第 2、3 条；plan D8。
- **现状**：这两条的前提是「单文件↔多文件各自持有自己的 `chatMessages` 数组」，而该前提依赖
  **运行时的 `this.chatMessages = []`（整个替换数组）**。本次把这个替换去掉了，`switchMode` 的
  `captureSingleSnapshot` 存的又是**同一个数组引用**（`player.js:673`），于是：
  单文件 → 多文件 → 单文件回到的是**同一个数组**，多文件期间的对话留在里面 —— 一条连续对话，不再是分区。
- **影响**：行为本身**无害**（甚至更好：跨模式回退的 `chatIndex` 因此语义一致，`switchMode` 的防御分支变可达且正确）。
  问题是文档与实际不符，后续按文档推理会跑偏（比如为了「跨模式」另加提示，其实不需要）。
- **建议**：把 §7 第 2、3 条改写为「运行不再替换 `chatMessages` 数组，因此跨模式实际是**同一条对话**；
  跨模式回退可达且 `chatIndex` 一致」，并在手验清单补一条「多文件运行 → 切回单文件 → 对话仍在，且多文件记录点可回退」。

### R5（极低）`restoreSource` 用 `!cp.code` 判空

- **位置**：`SingleFileShell.vue`（`if (!cp?.code) return false`）。
- **现状**：判据把「快照是空字符串」与「快照不存在」混为一谈。空文件（或运行前代码为空）的记录点会被静默拒绝回退，
  且调用方只看到「点了没反应」。
- **建议**：`if (typeof cp?.code !== 'string') return false`；多文件那条已是 `Array.isArray(cp?.files)`，无需改。

## 建议

- **R1 值得修**（中危且触发路径自然，修法局部）；R2 一行即可堵住；R3/R4 属文档与死代码，顺手做；R5 可选。
- 不阻断合并。**发布前必做**（三份清单合并执行）：
  1. coze 侧改动需**重新发布 agent**（引导与 few-shot 都在 agent 侧）——否则 F1–F3 全不生效；
  2. `npm run dev` 手验：方向绑定的 8 条 + 时间线的 8 条（尤其时间线第 2 条多文件回退、第 6 条「文件数变化」的回归点、
     方向绑定第 5 条「10 秒后弹窗仍在」）；
  3. 手验中**必测**一条本次清单没覆盖的组合：**回退后直接提问**（R1 的复现路径），以及**切模式后回看对话**（R4 的新行为）。

## 文档登记

- plan：`docs/plan/2026-09-10-coze-agent-optimization-goal-binding-and-error-entry-fix-plan.md`、`docs/plan/2026-09-10-coze-agent-run-timeline-plan.md`
- devlog：`docs/devlog/2026-09-10-coze-agent-optimization-goal-binding-fix.md`、`docs/devlog/2026-09-10-coze-agent-run-timeline.md`
- spec：`docs/spec/2026-09-10-coze-agent-code-optimization.md`（§2 D4/D5、§3 前提表、§4.1–§4.4、§5、§7.1/§7.2、§8、§10）、
  `docs/spec/2026-08-10-coze-agent-interface.md` §2.2（goal 闭集补 `comprehensive`）——均已按 plan Task 12 同步，逐条核对无误。
- 时间线功能**未单开 spec**（决策完整记录在 plan §1），符合 plan Task 7。
- 若采纳 R1 的「折叠带终点」改法，需同步 devlog（timeline）§4 的折叠描述、`utils/timeline.js` 的 16 条用例签名与 plan §1 T3/T7。
