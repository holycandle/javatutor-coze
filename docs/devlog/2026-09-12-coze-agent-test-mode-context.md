# 2026-09-12 测试模式误诊修复 — 实施记录

> 计划：`docs/plan/2026-09-12-coze-agent-test-mode-context-fix-plan.md`
> 契约：`docs/spec/2026-08-10-coze-agent-interface.md`（§1 请求契约同步）
> 规格：`docs/spec/2026-09-10-coze-agent-code-optimization.md`（§5 报错入口预填文本同步）
> 姊妹件（同批联调）：`docs/plan/2026-09-12-coze-agent-optimization-gate-retry-plan.md` / `docs/devlog/2026-09-12-coze-agent-optimization-gate-retry.md`

**跨仓**：前端 `javatutor/frontend` + 后端 `javatutor/backend`（payload 透传）+ coze `javatutor-coze`。

## 1. 做了什么

联调反馈：**测试模式下用户没输入用例时，agent 把「没有 main / 找不到符号」误诊成代码错**。

成因链（计划 §0.1 D1–D10 已核实）：前端 `testMode` 是派生值（`cases.length > 0`），
**没保存用例 ⇒ 仍以默认模式提交**，而 agent 拿到的提问里**只有错误原文**（`buildFixPrompt`），
既不知道这次是哪种模式（事实），也不知道两种模式对代码的要求不同（语义）。**缺的是事实与知识，不是推理能力。**

本件两半都补：

- **事实**：前端**每次**提问都带 `mode` / `testCaseCount` → 后端透传为 `run_mode` / `test_case_count`
  → coze 落 state → 确定性注入 `### 运行模式` 上下文 packet + 评审核对用的 facts 块一行。
- **语义**：coze 侧「知识 + 引导」双补——本体 `user_guides["测试模式"]` 写激活条件与注释类抽取规则（经 `render_usage_guide()` 进**主 Agent** 系统提示）；
  新增「运行模式判读」引导段进主 Agent 系统提示（**诊断启发式，不进本体**）。

## 2. 决策（计划 §1 F1–F4）

| # | 决策 | 落点 |
|---|---|---|
| F1 | 前端把「本次运行是什么模式」**随每次提问**送出 | `player.js::buildChatBody` 的 `mode` / `testCaseCount` |
| F2 | 报错入口预填文本增 `[运行环境]` 事实块；**语义仍留在 coze** | `utils/errorEntry.js::buildFixPrompt` + `runEnvLines`（纯事实） |
| F3 | coze 侧知识 + 引导双补，且**分工不重叠** | 本体 `user_guides`（知识，只经 `render_usage_guide()` 进主 Agent）/ `panels.py::render_run_mode_guide`（引导、只给主 Agent） |
| F4 | 运行模式作**确定性上下文**注入，不靠模型翻 state | `context_builder` packet + `contexts.build_facts_block` 一行 |

## 3. 改动清单

### 3.1 前端（`javatutor/frontend`）

| 文件 | 改动 |
|---|---|
| `src/stores/player.js` | `buildChatBody(question)` 增 `mode: this.testMode ? 'test' : 'default'` 与 `testCaseCount: this.testCases.length`（**缺省即显式送 `'default'`**，使 coze 能区分「默认模式」与「旧客户端没带」）；`/api/run` 的 body 一行未动 |
| `src/utils/errorEntry.js` | `buildFixPrompt(message, ctx)` 增 `[运行环境]` 块；新增纯函数 `runEnvLines(ctx)`（只陈述事实行，ctx 缺失 ⇒ 退化旧行为） |
| `src/utils/errorEntry.test.js` | 本文件用例 7 → **13**（+6：旧签名退化 1 / 单文件默认模式 1 / 多文件测试模式 1 / 字段部分缺失 1 / 不写运行语义 1 / `runEnvLines` 4 合 3） |
| `src/components/GlobalStatus.vue` | `prefillFix()` 传 ctx（`mode` / `fileCount` / `entryFile` / `testMode` / `testCaseCount`），其余逻辑一行不动 |

### 3.2 后端（`javatutor/backend`）

| 文件 | 改动 |
|---|---|
| `src/test/.../service/CozeServicePayloadTest.java` | 抽 `build(runId, runMode, testCaseCount)` 辅助；用例 3 → **6**（+3：test 分支、default 且计数 0 **不得省略**、`runMode` 空 ⇒ 两键都不得出现） |
| `src/main/.../service/CozeService.java` | `buildAgentPayload` / `streamExplain` 各增 `runMode` / `testCaseCount` 两参；新增 `addRunMode(...)`，在 **runId 分支与 legacy 分支都调用**；两个非 chat 的 `blockingExplain*` 传 `null, 0` |
| `src/main/.../model/ExplainRequest.java` | 新增 `testCaseCount`（`mode` 已有） |
| `src/main/.../controller/CozeAIController.java` | `chat` 的 `streamExplain(...)` 末尾追加 `request.getMode(), request.getTestCaseCount()` |

### 3.3 coze（`javatutor-coze`）

| 文件 | 改动 |
|---|---|
| `src/graphs/javatutor/state.py` | 新增 `run_mode: str`（`"test"｜"default"｜""`）与 `test_case_count: int`，中文 docstring 写明来源与「缺失 = 模式未知，不得当成 default」 |
| `src/graphs/javatutor/nodes.py` | `_parse_json_dict` 读两键写进返回 dict（**不改任何既有键**）；`test_case_count` 解析失败退 0 |
| `src/graphs/javatutor/context_builder.py` | `gather()` 在 `### 当前执行位置` 之后、Memory 之前，仅当 `run_mode` 非空时注入 `### 运行模式` packet（score 0.9 / Evidence） |
| `src/graphs/javatutor/prompting/panels.py` | 新增 `render_run_mode_guide()`（三情形判读 + 三条规则 + 事实来源优先级，见偏差 #5） |
| `src/graphs/javatutor/harness/propose.py` | `_main_system_prompt()` 在 `render_optimization_guidance()` 之后接入 `render_run_mode_guide()` |
| `src/graphs/javatutor/prompting/contexts.py` | `build_facts_block` 在 `编译错误：` 之后增「运行模式：」一行（缺失则跳过） |
| `assets/knowledge/javatutor_domain_ontology.json` | **只改** `user_guides["测试模式"]`：第 3 步补「必须≥1 条用例」、追加「块注释里的类只在测试模式被抽取」、`note` 对比两种模式对代码的要求 |
| `tests/test_run_mode_context.py` | **新建**，12 用例（见 §5） |

## 4. 与计划的偏差（5 处）

### 偏差 #1（须纠正既有记录）：后端基线是 **123**，不是 124

计划 §0 要求「后端先跑一遍记录通过数」。此前 `docs/devlog/2026-09-12-coze-agent-optimization-gate-retry.md`
写的是 124——**那是 `grep -c "@Test"` 的数**，而 `ExecutionSnapshotControllerTest.java:20` 的
`@TestPropertySource` 也含 `@Test` 子串，**多数了 1 个**。

**处置**：以 surefire 汇总行为准（本次改动前 = 123），并在姊妹件 devlog 与 `AGENT.md` 一并改正。
计数口径：**只信 `Tests run:` 汇总行，或用 `grep -h "@Test$\|@Test("`**。

### 偏差 #2：`buildFixPrompt` 的强调用**纯文本**，不用 `**`

计划 Task 2 §「`[[ ]]` 高亮标记」明确把此事留待确认：「若前端 markdown 不认 `**`，改用纯文本……以现有 markdown 渲染器为准确认后再定」。

已确认：该文本落在**草稿 textarea**（`focusChatWithDraft`）与**用户气泡**（`{{ m.text }}`，转义后渲染）——
**两处都不走 markdown**，`**` 会原样显示成星号。故写成纯文本
「默认模式（测试模式未激活：已保存用例 0 条）」（含义靠括号承载，不靠字号）。

### 偏差 #3：引导段守卫断言拆成两段

计划 Task 11 要求守卫断言引导段含「不得据此断言代码有语法/逻辑错误」，但计划 Task 8 自己给的文案是
`**不得**据此断言代码有语法/逻辑错误`——**粗体标记把该短语切断**，逐字子串并不存在。

**处置**：不改引导文案（加粗是计划意图），改断言为「`不得`」+「`据此断言代码有语法/逻辑错误`」两段，
并在用例内注明原因。红线本身仍被锁死（删掉 `不得` 或改掉后半句都会红）。

### 偏差 #4：新用例 8 → **12**

计划 Task 11 的表格是 8 行，但每行都含「有 / 无」两侧（如「packet 出现」与「packet 缺失」）。
实际落地把它拆成独立用例（存在与缺失各自可定位失败点），并补了 2 条计划未列但由本件引入的边界：
`test_case_count` 非数字不抛异常、`### 运行模式` packet 能穿过 `structure()` 进 `[Evidence]` 段
（**只断言 `gather()` 会漏掉分段过滤**——packet 进不了 Evidence 段等于没注入）。

### 偏差 #5（重要）：引导段把「事实来源」写清，并区分两个来源的权威性

计划 Task 8 的引导文案通篇只说「**运行环境**」——但那是**前端预填块**的名字（`[运行环境]`），
而本件 F4 的权威事实通道是 coze 侧注入的 **`### 运行模式` 上下文 packet**。
照原文落地会有两个后果：

1. 自由问答（非报错入口）**没有** `[运行环境]` 块，但有 `### 运行模式` packet ——
   规则里「『运行环境』缺失（旧客户端）时不要臆测模式」会**误命中**，让模型对明明已知的模式改口说「不确定」，
   正好废掉 F4「不靠模型自己去 state 里翻」的设计意图；
2. 反过来，用户点了报错入口拿到预填文本、**又在发送前改了用例**时，预填块里的模式已过期，
   而 packet 是同一次请求现取的 —— 两者冲突时必须有明确优先级。

**处置**：文案改为「模式事实有两个来源，**以系统注入的 `### 运行模式` 上下文为准**；
`[运行环境]` 块由报错入口预填、写于点击那一刻，可能过期；**两者都没有**才算模式未知」。
语义与计划一致（三情形判读、两条红线逐字保留），只是把「读哪个」写明并定出优先级。
守卫同步加一条：引导段必须含 `### 运行模式` 这个 packet 名——**一侧改名而漏另一侧，模型就找不到事实来源**。

## 5. 验证

| 项 | 命令 | 结果 |
|---|---|---|
| 前端基线（改动前） | `cd javatutor/frontend && npm test` | 29 文件 / **351** 用例通过 |
| 前端（改动后） | 同上 | 29 文件 / **376** 用例通过（+25：本件 +6，姊妹件 +19） |
| 后端基线（改动前） | `cd javatutor/backend && mvn test` | **123** 通过 / 0 失败（口径见偏差 #1） |
| 后端（改动后） | 同上 | **126** 通过 / 0 失败，`BUILD SUCCESS`（+3） |
| coze 基线（改动前） | `cd javatutor-coze && uv run pytest -q` | **311** passed |
| coze（改动后） | `uv run pytest tests/ -q` | **327** passed（+16：本件 +12，姊妹件 +4） |

## 6. 已知局限

- **根因的另一半未修**（计划「遗留」原文）：用户在测试面板里但**没保存用例**时，前端仍**静默**按默认模式运行。
  本件只是让 agent 能**正确解释**，没有消除「用户以为在测试模式、实际不是」的落差。
  运行前拦截（面板展开但用例为 0 时提示）是可选后续，**本件不做**。
- **模式事实只在提问那一刻取值**：用户改了用例再提问，模式随之变化（符合预期）；历史对话里的旧提问仍带旧模式，属正常。
- **两个事实来源可能短暂不一致**（偏差 #5）：报错入口预填的 `[运行环境]` 块写于**点击那一刻**，
  而 `### 运行模式` packet 写于**发送那一刻**。用户在两动作之间改了用例，预填文本就过期了。
  引导段已定优先级（**以 packet 为准**），但用户若**手改**预填文本里的模式，agent 会照 packet 纠正他——这是有意行为。
- **`extractCommentedClasses` 只认块注释**：行注释（`// public class TreeNode`）不抽取——本体与引导文案都写「块注释」，
  不要读成「注释里的类都会抽取」。
- **`run_mode` 缺失 = 模式未知**：coze 侧不注入任何 packet、不加 facts 行，引导段也明确要求「不要臆测模式」。
  三种状态（`test` / `default` / `""`）在 `state.py` 有显式语义，**不得**把 `""` 归到 `default`。
- **本职的取舍（review P3-1 订正过）**：按计划原文，本体 `user_guides` 该条目「同时被主 Agent 与 Judge 消费」，
  但**这不成立**——`build_judge_grounding_block()` 只读 `field_schema` + `modules`，不含 `user_guides`；
  该条目的唯一消费者是 `panels.py::render_usage_guide()`（唯一调用点 `propose.py::_main_system_prompt()`，**只给主 Agent**）。
  取舍本身不变（知识进本体、判读启发式留系统提示），只是理由要换成「知识 vs 诊断口径」而不是「一侧 vs 另一侧」。
  **真正要紧的是反过来的推论**：Judge 侧唯一能看到运行模式事实的通道是 `contexts.build_facts_block()` 的那一行——
  若后人以为「Judge 读本体」，就可能觉得删掉 facts 行也无妨，那才会让评审把「当前是默认模式」判成幻觉。

## 7. 手验清单（`npm run dev`；coze 侧需**重新发布 agent**）

1. **复现原 bug**：单文件粘贴 `class Solution` + 注释里的 `public class TreeNode { ... }`，**不输入任何用例**，点「运行」→ 失败。
2. 点全局红色弹窗的报错入口 → 草稿应含 `[运行环境]` + 「默认模式（测试模式未激活：已保存用例 0 条）」→ 发送。
3. agent 回答应**指出「当前是默认模式、测试模式未激活」并给出激活办法**（在「测试」面板输入用例 → 保存），
   **不得**据此断言代码有语法/逻辑错误。
4. 同一份代码在「测试」面板输入 1 条用例并保存 → 再点「运行」→ 成功（后端抽取注释类）。
   再走一次报错入口 → 草稿应显示「测试模式（已保存用例 1 条）」。
5. **多文件**：多文件模式报错 → 草稿含「多文件（N 个文件，主入口 X）」。
6. **回归**：不带模式的自由问答（非报错入口）行为与现状一致（coze 侧「运行环境」缺失 → 不臆测模式）。

## 8. review 处理（`docs/reviews/2026-09-12-coze-agent-optimization-retry-and-test-mode-review.md`）

review 共 1 P2 / 6 P3，均**不阻塞合并**。属本件的 3 项处置如下：

| # | 结论 | 处置 |
|---|---|---|
| P3-1 | 「本体 `user_guides` 同时被 Judge 消费」**不成立**（`build_judge_grounding_block()` 只读 `field_schema` + `modules`） | 三处措辞已改（本文件 §2 F3 行、§6 末条、`panels.py::render_run_mode_guide` docstring、`tests/test_run_mode_context.py` 分节注释），计划 F3 行加「执行后补记」订正。**取舍不变**，理由换成「领域知识 vs 诊断口径」；并记下反向推论：Judge 侧唯一能看到运行模式事实的通道是 `build_facts_block` 那一行 |
| P3-5 | 本体测试模式条目把「块注释抽取」写了两遍（`steps[4]` 与 `note`），而 `render_usage_guide()` 把两者都拼进系统提示 | 机制留在 `steps`（操作口径）、`note` 只留判断口径（两模式要求对比 + 「既定行为，不是编译错误」）；守卫加 `assert "public class" not in note` 锁死不再复写 |
| P3-4 | spec §8.3 / §9 / §11 未随实现同步 | §11 登记本件的 plan/devlog/review；§9 补 `tests/test_run_mode_context.py` 与返修守卫两处位置（与姊妹件共用一次改动） |

- 本件**无新增用例**：review 处理新增的 7 条全在姊妹件的 `player-optimization.test.js`（返修状态机）。
  处理后的三仓数（含姊妹件）：前端 `npm test` = 29 文件 / **383**；coze `uv run pytest tests/ -q` = **327**；后端 `mvn test` = **126**。
- **未涉及**：P2-1 / P3-2 / P3-3 / P3-6 全在优化卡侧，处置见 `docs/devlog/2026-09-12-coze-agent-optimization-gate-retry.md` §8。
