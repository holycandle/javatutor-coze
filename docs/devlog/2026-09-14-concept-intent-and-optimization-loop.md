# 2026-09-14 联调修复：概念题意图接入作答路径 + 优化第二步判别器 — 实施记录

> 计划：`docs/plan/2026-09-14-fix-concept-intent-and-optimization-loop-plan.md`（Task 0–10）
> 契约同步：`docs/spec/2026-09-10-coze-agent-code-optimization.md`（§4.2 / §4.3 / §4.4 / §8 / §9 / §10 / §11）、
> `docs/spec/2026-08-10-coze-agent-interface.md`（`intent` 下游影响 + `【优化第二步】` 标记）、`docs/agent-collaboration-guide.md`

**跨仓**：coze `javatutor-coze` + 前端 `JavaTutor/frontend`。后端未改动。

交付范围：Task 9 / 1 / 2 / 3 / 4 / 6 / 7 / 10（离线全绿）。
**Task 5 / Task 8 已按计划 §6 不再单独执行**——它们的改动落在 `SYSTEM_PROMPT_CRITIC` 同一段，
统一由 `docs/plan/2026-09-14-critic-revise-optimization-plan.md` Task 3 落地
（本组对话两件一起做了，见 `docs/devlog/2026-09-14-critic-revise-optimization.md`）。

## 1. 两个 bug 与它们的取证状态（**不对称，必须分开说**）

### Bug C：概念题被当「当前步」作答 / 概念回答被评审误杀

- **复现的一半**（实测 1，线上）：`intent=concept` 却 `critic_passed: false` + `revised: true`
  ⇒ 「此类回答往往评审未通过而被修订」成立。
- **未复现的一半**（实测 2）：本地**没有**复现出「总是回答当前步的内容」。
  故本件**不声称**找到了该症状的充分触发条件；修法依据是下面三条**结构性缺陷**（都是硬事实，
  不是推测）：`intent` 的产物在作答路径上**没有任何消费者**——
  1. `harness/propose.py::_main_system_prompt` 不收 `intent`（概念角色段无从生效）；
  2. `context_builder.gather()` 无条件注入 `### 当前执行位置`（概念题也在告诉模型「你现在在第 N 步」）；
  3. `nodes.py::build_context_node` 硬编码 `"other"` 传契约（概念题拿到 `other` 契约与 `other` 角色）。

  三条都指向同一处：判定「这是概念题」之后，**没有任何环节据此改变提示或上下文**。
- 第 4 条结构性缺陷在评审侧（概念题没有步骤可引，旧评审表却把「未引用步骤数据」当漏引）
  ⇒ 由评审优化计划 Task 3 落地。

### Bug D：优化第二步不出代码（**已端到端复现**）

实测 4：把实测 3 自己产出的 options **按前端 `buildGoalPrompt` 同构拼出第二步提问**，agent 仍返回
方案卡而非完整代码——即 §4.3 要求的「用户已指明目标则直接给代码」从未生效。

**根因是判别器冲突**：两步式**没有判别器**。spec §4.3 的判别依据是「用户是否已指明目标」，
而第二步提问的**形状恰好就是**「已指明目标」（它由第一步的 options 拼成）；
同一形状的输入被要求走两条相反的分支。修法 = 用一个**显式标记**做判别器，
不再从提问语义里猜。

## 2. 决策与落点

| # | 落点 | 说明 |
|---|---|---|
| 1 | `intent_guidance.render_intent_guidance(intent)`（新建） | 仅 `concept` / `debug` / `other` 返回段；**`data_query` 与空串返回 `""`**（既有基线逐字不变，有回归用例钉住） |
| 2 | `_main_system_prompt(intent="")` | few-shot 之前插入引导段；`propose()` 传 `state.get("intent", "")`；默认参数保住既有无参调用 |
| 3 | `gather()` 的 `has_position` | 增 `intent != "concept"` 条件（概念题不再收到「当前执行位置」包） |
| 4 | `build_context_node` | `system_instructions` 改 `build_system_prompt(intent or "other")`——用 `build_system_prompt` 而非 `get_contract`，因为它同时带**领域词汇**与**领域本体**块，只取契约会让这两块从上下文消失 |
| 5 | `main_fewshots.py` 增概念样例 | 含「不取步骤证据、不附步骤引用」的示范；样本内**不得出现任何步骤锚点** |
| 6 | `DATA_QUERY_KEYWORDS` 的「第」 | 改形状匹配 `第\s*\d+\s*步` / `第\s*\d+\s*行`（此前「第」单字出现即判 data_query，把「以性能为先」这类提问误分类） |
| 7 | `prompting/optimization.py` | 第一步条目改「**提问里没有第二步标记时**只给方案卡」（删掉「用户已指明目标」这一判别依据）；新增「提问以 `【优化第二步】` 起头时直接交付 `replace`，不得再出方案卡」；两条第二步 few-shot 的**提问文本**也加标记 |
| 8 | 前端 `editSuggestion.js::STEP2_MARKER` | `buildGoalPrompt` 输出以 `【优化第二步】` 起头；空选择仍返回 `''`（**不得只发一个光标记**） |

## 3. 改动清单

### 3.1 coze

| 文件 | 改动 |
|---|---|
| `src/graphs/javatutor/prompting/intent_guidance.py`（新建） | `render_intent_guidance(intent)` |
| `src/graphs/javatutor/harness/propose.py` | `_main_system_prompt(intent="")` + `propose()` 传 intent |
| `src/graphs/javatutor/context_builder.py` | `gather()` 的 `has_position` 增意图条件 |
| `src/graphs/javatutor/nodes.py` | `build_context_node` 改用 `build_system_prompt(intent or "other")` |
| `src/graphs/javatutor/prompting/main_fewshots.py` | 增 1 条概念类示例（无步骤锚点）；两条第二步示例提问加标记 |
| `src/graphs/javatutor/prompting/optimization.py` | 判别器改显式标记（见上表 #7） |
| `src/graphs/javatutor/intent_rules.py` | `DATA_QUERY_KEYWORDS` 的「第」「步」「行」改形状匹配 |
| `tests/test_intent_guidance.py`（新建） | 4 用例（concept 引导段 / data_query 与空串逐字相同 / 无参兼容） |
| `tests/test_main_fewshots.py`（新建） | 3 用例（含概念样例 / 无步骤锚点 / 既有样例不回归） |
| `tests/test_context_builder.py` / `tests/test_intent_rules.py` / `tests/test_optimization_guidance.py` | 分别 +14 / +16 / +55 行（位置包门控、关键字形状、判别器与 few-shot 标记、跨仓字面量比对） |

### 3.2 前端（`JavaTutor/frontend`）

| 文件 | 改动 |
|---|---|
| `src/utils/editSuggestion.js` | 导出 `STEP2_MARKER = '【优化第二步】'`；`buildGoalPrompt` 以此为前缀 |
| `src/utils/editSuggestion.test.js` | +1 用例（标记必须在提问**开头**）；3 处期望串加前缀；空选择用例增「不含标记」断言 |
| `src/stores/__tests__/player-optimization.test.js` | 2 处期望串加前缀 |

### 3.3 文档

| 文件 | 改动 |
|---|---|
| `docs/spec/2026-09-10-coze-agent-code-optimization.md` | §4.2 评审门；§4.3 改写为标记判别器（含「不得并行」警示）；§4.4 模板加前缀 + 「无勾选不发」；§8 验收；§9 跨仓断言；§10 风险行改「已确认为真实故障」；§11 新增 2026-09-14 条目 |
| `docs/spec/2026-08-10-coze-agent-interface.md` | 新增「**`intent` 的下游影响**」表（系统提示 / 上下文 packet / 契约 / 评审口径四项）；§2.2 增 `STEP2_MARKER` 条目 |
| `docs/agent-collaboration-guide.md` | 输入输出段增 `intent` 会改变上下文与评审口径一条 |
| `docs/plan/2026-09-14-fix-concept-intent-and-optimization-loop-plan.md` | §1 D5/D6 标「被取代 / 收编」；Task 5 / Task 8 标「不再单独执行」 |

## 4. 计划偏差与自证

1. **跨仓握手用「两侧硬编码同一字面量 + 各自断言对方文件」**。`【优化第二步】` 在 coze 与前端
   各写一遍，两边测试互相读对方文件比对（`test_step2_marker_matches_frontend_literal`
   读 `editSuggestion.js`，前端用例反向钉住字面量）。理由：没有任何共享来源可以跨仓引用，
   而静默漂移的代价是判别器失效（回到本次的 bug）。
2. **`test_concept_shot_has_no_step_anchor` 先失败，改的是样本不是用例**。我写的概念样例在括注里
   提了一句 `step_facts`。该用例是对的：概念样本里出现步骤锚点，既会把模型拉回当前步，
   又会把「我查了什么」这种元叙述教进用户可见正文。⇒ 删掉括注，并在样本旁写明这条约束的两点危害。
3. **第二次触碰 `frontend/src/utils/editSuggestion.js` 的期望串**：`buildGoalPrompt` 的前缀一旦加上，
   所有既有 `toBe` 期望串都要跟着改（含 store 层用例）。这是「握手字面量」的必然代价，
   已在 spec §9 记为跨仓断言清单。
4. **`build_system_prompt` 而非 `get_contract`**（计划原文给了两种可能）：见上表 #4，
   用后者会让领域词汇与本体块从上下文中消失，属计划外损失。

## 5. 门槛与验证结果

| 门槛 | 结果 |
|---|---|
| coze `uv run pytest tests/ -q` | 本件完成时 **447 passed**；与评审优化计划合并后当前 **484 passed** |
| 前端 `npx vitest run` | **445 passed / 33 files**（基线 444，本件 +1） |
| 前端 `npm run build` | ok |
| L5 外壳回归（两条命令） | **均无输出** |
| L4 本地 HTTP 冒烟 | SKIP（同前几轮） |

## 6. 未验证与待办（明确）

- **Task 0 的现场证据仍待联调侧**：请按计划 §0.2 末尾的四项清单复现一次概念题，抓四项——
  `intent`、`critic_passed`/`revised`（实测 1 的形状是 `false`/`true`）、回答里是否出现步骤引用、
  以及上下文里是否含「### 当前执行位置」（取证命令与产物见 §0.3）。**这一步不是走形式**：实测 2 没复现出「答成当前步」，
  若联调侧也复现不出，则本件对 Bug C 的修法是**按结构性缺陷做的预防**，
  而不是对已确认触发条件的修复——两者在验收口径上不同，不应混为一谈。
- **线上未验证**：两处改动都须重发 agent 才生效（coze 侧重发提示词；前端需重新构建部署）。
  重发后应能看到：概念题 `critic_passed` 不再无端为 `false`；第二步提问的返回里出现完整 `replace` 代码。
- 本组对话不发布、不跑远程评估（每次真实运行消耗 Coze 侧额度）。
