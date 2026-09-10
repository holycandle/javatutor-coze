# 优化方向绑定（多选 + 硬约束）与报错入口全局化（2026-09-10）

> 一句话：把「用户在方案卡上选的方向」从**软偏好**变成**范围约束**——方案卡改**多选**、第 2 轮提问带**白名单 + 显式黑名单**、
> coze 引导新增「方向硬约束」段 + `comprehensive`；同时把报错入口从「只有内存状态 pane 可见的控制台」搬到**全局红色弹窗**并让运行类错误**不再自动消失**。

执行依据：`docs/plan/2026-09-10-coze-agent-optimization-goal-binding-and-error-entry-fix-plan.md`（决策 F1–F5）。
前置实现：`docs/devlog/2026-09-10-coze-agent-code-optimization.md`；review：`docs/reviews/2026-09-10-coze-agent-code-optimization-review.md`。

## 1. 背景与诊断

联调发现两处问题（诊断见 plan §0.1，此处只留结论）：

1. **「选了 A 却得到 A+B」是可预测的，不是随机**——第 2 轮提问模板是「以「X」为**优先**优化当前代码」，
   「优先」是软偏好而非范围；coze 引导也只要求「goal 必须等于用户选定」，**没有**「不得顺带做其他方向」。
   跨轮唯一载体是 coze 记忆（`save_session` 只存「问答 → 回答前 200 字」，第 1 轮末尾的 options JSON 基本落在截断之外），
   因此**约束必须由前端写进提问本身**，不能指望 agent 记得第 1 轮。
2. **报错入口在控制台面板里**——它属于「内存状态」pane，与 agent 面板互斥可见，用户停在别的 tab 时根本看不到入口。

另一半需求是**多选**：用户想同时要「性能 + 内存」时，旧卡点一个方向即发问，无法表达组合。

## 2. 决策（F1–F5，见 plan §1）

| # | 决策 | 说明 |
|---|---|---|
| **F1** | 方案卡改**多选勾选** | 每行一个方向，勾 ≥1 项后点提交。**取代**原 D4 的「一点即生成」——多选必然需要提交动作（有意变更）。 |
| **F2** | 第 2 轮提问 = **硬约束 + 显式排除未选项** | 白名单 = 所选项（用 `label`/`detail`）；黑名单 = **同一张方案卡里未被勾选**的项。只取同卡未选项，不罗列整个闭集（否则出现「不要做正确性优化」这种荒谬约束）。 |
| **F3** | 闭集新增 **`comprehensive`（综合）** | 勾 1 项 → `replace.goal` = 该项；勾 ≥2 项 → 提问逐条列出，`replace.goal` = `comprehensive` 且 `rationale` 逐项说明。方案卡 `options` **不产出**它。 |
| **F4** | 报错入口**搬到全局红色弹窗**，运行类错误**不再自动消失** | 可手动关闭；下次成功运行时随 `store.error = null` 一并消失。**控制台那份删除**（避免双入口）。 |
| **F5** | 点击 = 预填 + 切到 agent 面板 + **聚焦输入框**，**不发送** | 发送权仍在用户手里（延续 D9「代写提问」的语义）。 |

## 3. 改动清单

### A. 前端（`javatutor/frontend`）

| 文件 | 改动 |
|---|---|
| `src/utils/editSuggestion.js` | `GOALS` 加 `comprehensive`；`buildGoalPrompt(selected, excluded)` 换签名（白名单 + 黑名单 + `①②③` 逐条列出）；`optionName` = `label \|\| GOALS[goal] \|\| goal` |
| `src/utils/editSuggestion.test.js` | `describe('buildGoalPrompt')` 重写为 7 条（单项 / 单项+排除 / 多项 / 多项+排除 / 无 detail / 空选择 / `GOALS` key 序） |
| `src/utils/errorEntry.js` | **新建**：`isRunError(error, lastRunError)` / `shouldAutoDismiss()` / `TRANSIENT_ERROR_MS = 6000` / `buildFixPrompt(message)` |
| `src/utils/errorEntry.test.js` | **新建**：11 条（同文判运行类、不同文/空值否、分流、模板、时长常量） |
| `src/components/OptimizationCard.vue` | options 分支改多选（`selected` ref + 点行切换 + 勾选态方块 + 「全选」+ 按勾选数变化的提交按钮）；`submit()` 传（已勾选, 同卡未勾选, target） |
| `src/stores/player.js` | `askGoalOptimization(selected, excluded, target)` 改收数组；新增 `chatFocusNonce` / `focusChatWithDraft(text)` / `clearRunError()` |
| `src/components/GlobalStatus.vue` | 弹窗内加「让 agent 帮我看看」（`v-if="store.lastRunError"`）；`watch(error)` 按 `shouldAutoDismiss` 分流时长；`close()` 一并 `clearRunError()` |
| `src/components/ConsoleOutput.vue` | 移除入口（模板块 / `shortError` / `prefillFix()` / `.console-error-*` 样式），恢复为只渲染输出 |
| `src/components/AiTutorPanel.vue` | 输入框 `ref="inputRef"` + `isVisibleInstance` 判定 + `watch(chatFocusNonce)` → `focus()` + 光标移到末尾 |

### B. coze（`javatutor-coze`）

| 文件 | 改动 |
|---|---|
| `src/graphs/javatutor/prompting/optimization.py` | `GOALS` 加 `comprehensive`；新增 `CARD_GOALS`（闭集去掉 `comprehensive`，供方案卡用）；第一步补「独立可组合」约束；**新增「第二步的方向约束（硬要求）」段**（只做所列方向 / 未列入不得顺手改 / ≥2 方向记 `comprehensive`） |
| `src/graphs/javatutor/prompting/main_fewshots.py` | 第 2 轮样例提问换成**新模板形态**（含白名单 + 黑名单）；**新增多方向样例**（`goal: "comprehensive"`，`rationale` 逐项说明）；新增 `_REPLACE_MULTI_SAMPLE` |
| `tests/test_optimization_guidance.py` | 新增 `test_goal_enum_includes_comprehensive` / `test_guidance_states_hard_direction_constraint` / `test_fewshots_second_round_states_exclusions`；既有 `test_main_fewshots_optimization_samples_valid` 增加「方案卡不得含 `comprehensive`」断言 |

### C. 文档

- `docs/spec/2026-09-10-coze-agent-code-optimization.md`：§2 D4/D5 加修订说明、§3 前提表第 4 行改写、§4.1（多选 + 可组合）、§4.2（`comprehensive` 与方向硬约束）、§4.3（时序与提问模板）、§4.4（闭集表加行 + 双模板）、§5（入口到 `GlobalStatus` + 常驻判据）、§7.1（卡片/动作/入口）、§7.2（引导与样例）、§8（验收 2/6）、§10（生命周期已定 + 两条风险）。
- `docs/spec/2026-08-10-coze-agent-interface.md` §2.2：`goal` 闭集补 `comprehensive`，注明「多方向时使用」，并指向 spec §4.4。
- `docs/reviews/2026-09-10-coze-agent-code-optimization-review.md`：补「计划执行后」更新段——R1/R2 闭环，注明**问题 2 是 R1 的加强版、由本计划 F4 覆盖**，且 R1 的修复点（控制台入口）已随本计划删除。
- 后端 `javatutor/backend` **未改动**；`ui-panel-manifest.json` 未动（`sync_panel_manifest.py` exit=0，无 drift）。

## 4. 关键实现点

- **白名单与黑名单的取数不对称是有意的**：白名单用**勾选项**的 `label`/`detail`，黑名单只用**同一张卡**里**未勾选**的项。
  卡里没有的方向（哪怕明显可优化）不进黑名单——否则会拼出「不要做正确性优化」这类荒谬约束，反而误导 agent。
- **多选 + 提交后不再多一轮**：旧交互「点一个方向 → 立刻发问」在多选下无法成立，因此引入提交按钮；
  按钮文案随勾选数变化（0 项禁用 / 1 项「只优化「X」」/ ≥2 项「综合优化 N 个方向」），让用户提交前就看见 goal 会记成什么。
- **`comprehensive` 只在第 2 轮存在**：方案卡里它是一个「既不可执行又无法再拆分」的伪选项，
  所以 coze 侧用 `CARD_GOALS` 显式把它从第一步的可选值里剔除，守卫测试断言「options 里不得出现 `comprehensive`」。
- **运行类错误的判据是同文**：`runCode`/`runProject`/`applyRunResult` 失败时同时写 `store.error` 与 `store.lastRunError`，
  且两者同文，故 `isRunError` 用 `lastRunError.message === error` 就能把「运行错误」与「AI 流错误等」分流——
  前者常驻（用户要读、要点击），后者仍 6 秒淡出（否则一次网络抖动会留下常驻弹窗）。
- **单入口**：控制台那份入口连同 `shortError`/`prefillFix`/样式一并删除（`store.lastRunError` 状态本身保留，`GlobalStatus` 在用）。
- **聚焦要认实例**：`AiTutorPanel` 在单文件模式下可能同时挂载「内嵌」与「悬浮」两个实例，
  `isVisibleInstance` 按 `embedded` + 当前 tab 判定，只让可见的那个聚焦；`focus()` 后把光标移到末尾（`setSelectionRange`，不支持选区的 input 类型用 try/catch 兜底）。

## 5. 与计划的偏差

| # | 计划原文 | 实际实现 | 理由 |
|---|---|---|---|
| B1 | 守卫断言 `assert "不得改造" in text` | 同时断言 `不得改造` 与 `不得顺手改` | 引导原文两句都有，两条一起锁更稳。 |
| B2 | 引导段首句为「用户提问里已经写明「只做」哪些方向、以及「不要顺带做」哪些方向」 | 改为**逐字写出模板形态**（含「不要顺带做其他方向的改动（例如：…）」） | 守卫要求引导与前端的模板同款措辞；写成半句引用会让 agent 认不出用户提问里的完整句式。 |
| B3 | Task 11 的 `test_fewshots_second_round_states_exclusions` 只检查 replace 样例含两个短语之一 | 额外断言「存在 `comprehensive` 样例」与「存在单方向样例」 | 只查短语的话，删掉多方向样例仍会全绿——而多方向正是 F3 的核心。 |

计划未列、但顺手补齐：`test_optimization_guidance.py` 的 `test_optimization_guidance_lists_goal_enum` 自动覆盖了新 goal（遍历闭集断言出现在引导里）。

## 6. 测试

| 项 | 结果 |
|---|---|
| 前端 `npx vitest run` | ✅ **26 文件 / 312 用例**（改动前 25 / 295） |
| coze `uv run pytest -q` | ✅ **229 通过**（改动前 226，+3 守卫） |
| `npm run build` | ✅ 通过（SFC 编译无误） |
| `scripts/sync_panel_manifest.py` | ✅ exit=0，无 drift |
| 后端 | ✅ 未改动 |

> 基线说明：plan 写的是「前端 25 文件 / 291 用例」，实际起点是 **25 / 295**（review 的 R1–R5 修复已贡献 4 条），
> 本计划净增 **17 条**（`errorEntry.test.js` 11 条 + `editSuggestion.test.js` +4 + `player-optimization.test.js` +2）。

## 7. 已知局限

- **方向约束是「提示层」而非「校验层」**：`comprehensive` 只记录「多方向」这一事实，**不校验**代码真的只改了所列方向。
  真要强校验只能靠人工/评测（原 spec §10 的可观测性妥协，本次未变）。
- **第 2 轮的跨轮记忆仍不可靠**：本次靠「前端把约束写进提问」绕开它，**未**改 `sessionId`/记忆策略/后端；若将来要真正跨轮引用第 1 轮的方案卡，需另立计划。
- **黑名单依赖方案卡质量**：若 agent 把「修 bug」塞进某个方向的 `detail` 里，用户不勾它就会被显式禁止——范围可控（只列同卡未选项），真出问题再退化为只列 `label`。
- **coze 侧需重新发布 agent** 才生效（引导与 few-shot 都在 agent 侧）。

## 8. 手验清单（`npm run dev`；coze 需重新发布）

1. 问「可以优化吗」→ 方案卡出现 2–3 个方向，**可多选**（点行切换勾选态），未勾选时提交按钮禁用。
2. 勾**一个**方向提交 → 消息列表出现模板提问，含「只做「X」方向的优化」+「不要顺带做其他方向的改动（例如：「Y」：…）」。
3. 第 2 轮 replace 卡：目标显示该方向；**应用后的代码不含未选方向的改动**（对照第 1 轮 options 的 detail 逐条核）。
4. 勾**两个**方向提交 → 提问逐条列出 ①②；replace 卡目标显示「综合」，`rationale` 分别说明两个方向。
5. 构造运行失败（少个分号）→ **红色弹窗常驻**（10 秒后仍在），含「让 agent 帮我看看」。
6. 停在任意 tab（如流程/数据结构）点击该按钮 → 切到 agent 面板、输入框已预填、光标在末尾、**未发送**；点 `×` → 弹窗与入口一并消失。
7. 再跑一次能跑通的代码 → 弹窗自动消失。
8. 回归：`kind` 缺失 / `kind:"patch"` 的编辑建议卡行为与改动前**完全一致**；`replace` 卡门禁/应用/撤销不变。

## 9. 文档登记

- 计划：`docs/plan/2026-09-10-coze-agent-optimization-goal-binding-and-error-entry-fix-plan.md`
- 规格：`docs/spec/2026-09-10-coze-agent-code-optimization.md`（§4.1/§4.2/§4.3/§4.4/§5/§7/§8 已同步）、`docs/spec/2026-08-10-coze-agent-interface.md` §2.2
- Review：`docs/reviews/2026-09-10-coze-agent-code-optimization-review.md`（补「计划执行后」更新段）
- 前置 devlog：`docs/devlog/2026-09-10-coze-agent-code-optimization.md`
