# 对话时间线（运行不清空对话 + 记录点回退）（2026-09-10）

> 一句话：重新运行代码**不再清空对话**，每次成功运行/应用优化在对话里落一条**时间线分割线**（记录点），
> 点「回退到此」即可把编辑器代码与右侧面板一并退回那次运行，其后的对话**折叠保留、可展开**。

执行依据：`docs/plan/2026-09-10-coze-agent-run-timeline-plan.md`（决策 T1–T7）。
纯前端功能：**coze 与后端均未改动**（`uv run pytest -q` 仍 229，Plan 2 未触碰 coze 任何文件）。

## 1. 背景

「重新执行代码会把对话清空，不利于回顾」——`runCode`/`runProject` 开场就把 `chatMessages = []` 抹掉。
`/api/ai/chat` 本身**不携带任何对话历史**（`sessionId` 还是代码哈希），所以「保留对话」是**纯 UI 行为**：
不增加 agent token、不改变 agent 行为，收益完全给用户（回顾 / 时间线）。

## 2. 决策（T1–T7，见 plan §1）

| # | 决策 |
|---|---|
| **T1** | **成功运行**与**应用优化**各建一个记录点（导入文件/加载算法不单独建点，归入下一次运行） |
| **T2** | 记录点 = **代码快照 + 摘要**，**不存运行结果**；回退时**重跑复现**，保证「编辑器代码 ↔ 右栏面板」永远同源 |
| **T3** | 回退 = 代码 + 运行结果回滚，其后的对话**折叠保留、可展开**（单值 `foldFromIndex` 表达） |
| **T4** | 时间线**仅内存**，刷新即清（与对话现状一致，无配额/版本负担） |
| **T5** | 记录点带 `mode`；回退时模式不同则**自动切模式** |
| **T6** | 回退触发的那次重跑**不建新记录点**（`silent`）；下一次真实的成功运行会清掉折叠 |
| **T7** | 折叠只影响**渲染**（`v-show`），**不删除、不重排** `chatMessages`（保住优化卡的挂载状态） |

## 3. 改动清单（均在 `javatutor/frontend`）

| 文件 | 改动 |
|---|---|
| `src/utils/timeline.js` | **新建**：`buildCheckpointLabel`（含 `shortOutput` 私有）/`foldStartIndex`/`isFolded`/`foldedCount`/`clampActiveIndex`/`REVERT_CONFIRM`/`MAX_TIMELINE` |
| `src/utils/timeline.test.js` | **新建**：16 条（摘要四形态、空段不出现、截断、折叠边界、下标收敛、常量） |
| `src/stores/player.js` | 新增 `timeline` / `timelineSeq` / `foldFromIndex` / `_runOpts` 状态；新增 `pushCheckpoint` / `revertToCheckpoint`；`runCode`/`runProject` **去掉 `chatMessages = []`**、接 `{silent}`；`applyRunResult` 成功分支建点；`applyCandidateRun(data, code, meta)` 建优化点 |
| `src/stores/__tests__/player-timeline.test.js` | **新建**：12 条（建点时机 / 失败不建点 / 多文件快照与深拷贝 / 优化点 / 折叠与展开 / 上限过期 / 跨模式回退） |
| `src/components/TimelineDivider.vue` | **新建**：分割线 + 摘要 + 「回退到此」（过期置灰）+ 折叠提示与「展开」 |
| `src/components/SingleFileShell.vue` | provide `restoreSource(cp)`（`setCode`） |
| `src/components/MultiFileShell.vue` | provide `restoreSource(cp)`（**-1 → 整项目替换 → 目标下标** 三步） |
| `src/components/AiTutorPanel.vue` | `v-for` 改 `<template v-for>` 双分支：`role:'divider'` → `TimelineDivider`；普通消息外层补 `v-show`；新增 `cpOf` / `isFoldedIndex` |
| `src/components/OptimizationCard.vue` | `applyCandidateRun` 调用补 `meta`（`goalLabel` / `target`） |
| `src/stores/__tests__/player-optimization.test.js` | 「不清会话」用例改为「原两条仍在 + 末尾多一条 divider」（本计划的预期副作用） |

## 4. 关键实现点

- **分割线是真实消息**（`{ role:'divider', text: label, checkpointId }`），**不引入「过滤后的数组」**：
  `OptimizationCard` 的 `v-if` 依赖真实下标（`i !== chatMessages.length - 1`），一过滤就会打乱挂载状态。
- **折叠一律 `v-show`**：`v-if` 会在折叠时卸载优化卡 → 展开后门禁重跑、`applied`/`undoToken` 丢失（2026-09-10 devlog §4 已踩过）。
  分割线自身也套 `v-show`——回退点**之后**的分割线（更晚的运行）同属折叠区。
- **记录点快照是深拷贝**：`files[i].code` 会被就地改写（门禁/撤销/文件切换都会写），共享引用会让「历史记录点」随时间变形。
- **多文件回退的三步**（D6）：`activeFileIndex = -1` → `await nextTick()` → 整项目替换 → 收敛下标 → `await nextTick()`。
  中间那步是为了让文件切换 watcher 的 `oldIdx` 落到 `-1`（跳过「保存旧文件」），否则它会用回退**前**的编辑器内容覆写刚恢复的快照。
- **`_runOpts` 在 `finally` 里清**（plan 写的是「成功分支末尾」）：失败/异常路径不清的话，`silent` 会泄漏到下一次真实运行，
  让那次运行**不建点**——正是最难排查的那类静默丢失。
- **应用优化也建点**（T1）：它改代码但用的是门禁那次的运行结果、不走 `/api/run`，不建点会在时间线上留一个「代码已变、无线索」的空档。

## 5. 与计划的偏差

| # | 计划原文 | 实际实现 | 理由 |
|---|---|---|---|
| B1 | `if (timeline.length >= MAX_TIMELINE) { const oldest = this.timeline.shift(); oldest.expired = true; delete oldest.code }` | 取**最旧的活跃记录**标 `expired` 并删快照，**记录留在数组里**；`MAX_TIMELINE` 约束的是「带快照的记录数」 | 计划给的写法有 bug：`shift()` 已把记录移出数组，标记落在一个被丢弃的对象上。而分割线要靠 `cp.id → cp` 才能渲染「记录已过期」并把按钮置灰——记录被移走就取不到 cp。计划 Task 3 的用例（「最旧一条 `expired === true`」+「`length` 仍为 MAX」）本身也自相矛盾；实现取「只丢快照」这一版，代价是 `timeline` 数组随运行次数增长（每条只剩几十字节的 label），已在已知局限记录。 |
| B2 | `TimelineDivider.cp: { type: Object, required: true }` | `default: null` + 取不到时不渲染 | 防 Vue 的 required prop 警告；`cpOf` 找不到记录点时不至于抛错。 |
| B3 | `const ok = restoreSource?.(cp); if (ok === false) return` | 先 `if (!restoreSource) return`，再 `await restoreSource(cp)` | inject 为空时按计划会「只重跑、不回写代码」→ 编辑器旧代码 + 右栏新结果，正是本功能要消灭的错配；另外多文件的 `restoreSource` 是 async，必须 `await`。 |
| B4 | 「折叠占位渲染在下标 `=== foldFromIndex` 的那一条**之后**」 | 由该下标处的 `TimelineDivider` 内部渲染（`foldedCount > 0` 时） | 语义等价（分割线即该下标的条目），少改一处 `v-if` 链。 |
| B5 | `applyRunResult(data, opts)` 或临时字段二选一 | 取临时字段 `_runOpts`，但清空时机放 `finally` | 见 §4；`applyRunResult` 的签名与两处调用点零改动。 |
| B6 | 仅新增 `player-timeline.test.js` | 另改 `player-optimization.test.js` 一处断言 | `applyCandidateRun` 现在会追加分割线，「不清会话」用例的 `chatMessages.length` 由 2 变 3——断言改为「原两条仍在 + 末尾是 divider」，语义不变而更明确。 |

## 6. 测试

| 项 | 结果 |
|---|---|
| 前端 `npx vitest run` | ✅ **28 文件 / 340 用例**（改动前 26 / 312，本计划 +28） |
| `npm run build` | ✅ 通过（新增 SFC 编译无误） |
| coze `uv run pytest -q` | ✅ 229（**未改动 coze 任何文件**，与 Plan 1 一致） |
| `scripts/sync_panel_manifest.py` | ✅ exit=0，无 drift |

## 7. 已知局限

- **回退后 `currentStep` 复位为 0**（T2 的代价）：用户需自己重新定位到感兴趣的那一步。若不可接受，后续再评估「随记录点存 steps」（内存换体验）。
- **模式的对话分区**（D8）：`switchMode` 会把 `chatMessages` 换成单文件模式的旧快照（多文件不捕获对话），
  因此时间线天然是**按模式分区**的——多文件 ↔ 单文件来回切会各自保留自己的对话。**本计划未改这一既有怪癖**。
- **跨模式回退在 UI 上不可达，`switchMode` 只是防御**：分割线是消息数组里的条目，只在**它所属模式的对话**里渲染
  （多文件的记录点落在多文件的消息数组里，切到单文件时那份数组已不在 `chatMessages` 中 → 点不到）。
  真被走到（多文件目标、且当前 `chatMessages` 是单文件的活跃数组）时，`foldFromIndex` 的语义会对不上数组——
  退路是「跨模式回退时提示用户先手动切模式」。
- **DOM 体量**：对话只增不减（仅内存），超长会话下 `chat-body` 节点数会增长。若实测卡顿，可给「已折叠区」加虚拟化（本计划不做）。
- **`timeline` 数组无硬上限**：超 `MAX_TIMELINE` 只丢快照，记录（label + 元数据）保留，好让历史分割线仍能渲染「记录已过期」（偏差 B1）。
- **撤销优化不会移除对应记录点**（Task 6）：它是「应用过」这一事实的记录。撤销后时间线仍显示该点——本计划**不做**移除，避免 undo 与时间线两套状态互相扰动。
- **`explainHistory` 仍是死状态**（D4）：全仓只有写入与清空、没有读取点。本计划**未删**（非必需，避免扩大改动面）。

## 8. 手验清单（`npm run dev`）

1. 运行代码 → 问两个问题 → **再次运行**（改了代码）→ 对话窗口**不再清空**，新运行处出现分割线
   `#2 · <方法名/项目> · 14:05 · N 行 · M 步 · 输出 "…"`。
2. 分割线上点「回退到此」→ 确认框 → 编辑器代码回到那次运行的内容（单文件与多文件各测一次），右栏刷新为那次运行的结果（步数/输出一致）。
3. 回退后：其后对话折叠成一行「以下 N 条对话已折叠」，点「展开」全部恢复且**历史优化卡状态未丢**（应用过的卡仍显示「已应用」，不重新校验）。
4. 回退本身**不新增**记录点（时间线条数不变）；随后跑一次新代码 → 折叠自动解除、新增一条记录点。
5. 应用一次优化 → 出现 `#N · 已应用优化（性能）· Main.java · …` 记录点；点它的「回退到此」能回到优化前的代码。
6. 多文件：回退到「只有 2 个文件」的记录点（先删/加过文件）→ 文件列表整体恢复、编辑器载入正确、
   **不发生内容被覆盖成回退前编辑内容的错乱**（D6 的回归点）。
7. 失败运行（编译错误）→ **不建记录点、不插分割线**，红色弹窗照旧（与方向绑定计划的 F4 一起验）。
8. 造 31 次成功运行 → 最旧一条显示「记录已过期」且按钮置灰，其余可正常回退。

## 9. 文档登记

- 计划：`docs/plan/2026-09-10-coze-agent-run-timeline-plan.md`（决策完整记录于此，**本功能不单开 spec**）
- 前置 devlog：`docs/devlog/2026-09-10-coze-agent-code-optimization.md`（优化卡的 apply/undo 通道）
- 同期 devlog：`docs/devlog/2026-09-10-coze-agent-optimization-goal-binding-fix.md`（方向绑定 + 报错入口全局化）
- `docs/agent-collaboration-guide.md` **未改**（它描述 coze 图结构与输入输出，不涉及前端消息 role）
