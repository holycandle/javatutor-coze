# 2026-09-14 联调修复：概念题被当「当前步」作答 + 优化第二步不出代码

> 报告人：联调测试（用户）
> 症状原文：
> 1. 「当我询问算法知识时，agent 总是会回答当前步的内容，尽管意图识别也已判定为概念讲解。并且，此类回答往往评审未通过而被修订。」
> 2. 「当我选择优化方向后，agent 并不给出可直接应用的代码，而是不断重复思考给出优化方向让我选择，却不给出代码。」
>
> 涉及仓：`javatutor-coze`（主）+ `JavaTutor/frontend`（第二步提问标记）
> 与前一份计划的关系：`docs/plan/2026-09-14-fix-fetch-context-and-duplicate-answer-plan.md` 的 Bug A/B 已执行完毕；
> 本文续用 **Bug C**（概念题）与 **Bug D**（优化循环）两个编号，互不重叠。

---

## 0. 症状与取证

**取证方式**：对**已部署智能体**实跑（走本仓既有 remote 通道 `eval/runner/e2e_remote.chat_remote`），
共 5 次请求；命令与产物见 §0.3。与上一份计划不同，这次两个 bug **都在线上复现过**，
唯一没复现出来的那一半已在 §0.1 明确标注。

### 0.1 Bug C — 概念题被当「当前步」作答 / 概念回答被评审误杀

**实测 1（**复现**「此类回答往往评审未通过而被修订」）**

payload = 迪杰斯特拉实现的 Java 源码 + 3 条步骤（当前步 = 第 1 步，行号 3 ≈ 截图里的 `int n = 5; // 节点数`）
+ `algorithm_tags: ["迪杰斯特拉算法"]` + `run_mode: "default"`，提问 `请解释「迪杰斯特拉算法」这个算法/数据结构。`

痕迹：

```json
{"intent": "concept", "critic_passed": false, "revised": true, "fetch_context_failed": false,
 "tool_calls": [{"tool": "fetch_execution_context", "args": {}, "result": "...\"code_chars\": 707..."}]}
```

⇒ 概念题**确实**被判失败并触发修订（`revised: true`，用户看到的是修订后的版本）。报告的**后半句成立**。

**实测 2（**未复现**「总是回答当前步的内容」）**

同形 payload（不带 `algorithm_tags` / `run_mode`）得到的是**正确的概念讲解**：
先给定义（单源最短路径、非负边权）、再给核心思想、适用边界，末尾附 `【视角导航】`，
且 `critic_passed: true`。

⇒ 「概念题 → 答成当前步」**本地没有复现**。但下面三条结构性缺陷都指向同一处，且都是硬事实。

**根因 1（决定性，静态穷举）：意图分类的产物在作答路径上没有任何消费者**

```bash
grep -rn "intent" src/graphs/javatutor/ | grep -v "test\|trace\|#"   # 功能性使用只有两处
# src/graphs/javatutor/graph.py:43     intent == "analyze" → END
# src/graphs/javatutor/nodes.py:792    写进【决策痕迹】
```

- `_main_system_prompt()`（`harness/propose.py:38`）**不收 state**，主 Agent 系统提示里没有任何意图位。
- `gather()`（`context_builder.py:66`）不注入意图，`structure()` 的 `[Task]` 段只有用户问题。
- `build_context_node`（`nodes.py:874`）把 `system_instructions` **硬编码为 `build_system_prompt("other")`**。

⇒ harness 重构（图内真环）之后，原「按意图选专家」的一整套资产整体成为**孤儿**：
`SYSTEM_PROMPT_CONCEPT`、`CONTRACTS["concept"]`、`get_few_shots("concept")`、`build_concept_context`
仍留在仓库里，但**当前图不路由到专家节点**（`nodes.py:185` 自带说明「兼容层，新图链路已不再路由到专家节点」）。

**「尽管意图识别也已判定为概念讲解」——这句话在系统里确实不产生任何效果，与症状完全一致。**

**根因 2：上下文与提示两层合力，把任何问题都往「当前步」拉**

- `### 当前执行位置`（`context_builder.py:121-131`）对**每一道题**都注入，`relevance_score=0.9`，落 `[Evidence]` 段。
- 主 Agent 系统提示（`prompts.py:115-144`）开篇就是「上下文只提供当前执行位置…」，
  唯一的 `## 调用示例` 三步式全部围绕「第 2 步」。
- `MAIN_FEW_SHOTS` 共 7 条：4 条锚定步骤或优化，**概念类示例 0 条**（`prompting/main_fewshots.py`）。

**根因 3：评审的核对表是为 `data_query` 写的，且不知道意图**

`SYSTEM_PROMPT_CRITIC`（`prompts.py:96-109`）的 6 条核对（步骤号 / 行号 / 变量值 / 堆 id / 输出 /
代码行 vs `step_facts.line_text`）全部预设「回答里应有步骤级引用」；
事实块 `build_facts_block`（`prompting/contexts.py:124`）也只给「当前步骤」快照 + 运行模式。
概念题回答没有 `step_facts` 事实可核（`step_memories` 为空），规则 6 与规则 1 只能空转 → 判失败 → 修订。
**修订提示词（`SYSTEM_PROMPT_REVISE`）同样不知道意图**，只会「根据评审意见修正」，
而事实依据里塞满了「当前步骤」，于是修订方向天然被拉向当前步 —— 这正是用户看到的现象的一种合理解释，
但**本地未取到「修订前 vs 修订后」的对照**（线上只回传终态），故在 Task 0 里请联调侧补一条证据。

### 0.2 Bug D — 优化第二步不出代码（**已端到端复现**）

**实测 3（第 1 轮，正常）**：提问 `帮我优化一下这段代码。` →

```text
这段代码当前使用暴力枚举实现，时间复杂度为 O(n²)…请选择你想要优先优化的方向。
【编辑建议】
{"kind":"options","target":"Solution.java","options":[
  {"goal":"performance","label":"以性能为先","detail":"用哈希表记录每个元素第一次出现的下标…"},
  {"goal":"readability","label":"以可读性为先","detail":"补充注释和空行…"}]}
```

**实测 4（第 2 轮，**复现**）**：把实测 3 自己的 options **按前端 `buildGoalPrompt` 同构拼出第二步提问**
（含白名单「只做「以性能为先」方向的优化」、黑名单「不要顺带做其他方向的改动（例如：…）」、
结尾「请给出优化后的完整代码。」），再次请求同一 payload →

```text
这段代码实现的是找到每个元素在数组中第一次出现的下标…请选择你需要优化的方向：
【编辑建议】
{"kind": "options","target":"Solution.java","options":[ …与上一轮**同样的两项**… ]}
```

⇒ **又给了一张一模一样的方案卡，一行代码都没有。** 用户点第二次仍会出卡 ⇒ 死循环，
与报告「不断重复思考给出优化方向让我选择，却不给出代码」**逐字吻合**。
两轮 `critic_passed` 均为 `true`，即**没有任何环节拦截它**。

**根因（规格级）：两步式没有任何判别器。**

- spec `2026-09-10-coze-agent-code-optimization.md` §4.3 line 109 明确要求：
  「若用户提问已含明确目标（『帮我优化性能』），agent **仍先出方案卡**（只给该目标一项或两项），保持交互一致。」
- 而第二步提问的形状**恰恰就是**「已含明确目标」（「只做「以性能为先」方向的优化」）。
  ⇒ **同一形状的输入被要求走两条不同分支**，模型无法判别。
- `prompting/optimization.py:44` 把这条落成了硬条目（「用户已指明目标…时同样先出方案卡，保持交互一致」），
  与同文件「第二步的方向约束（硬要求）」**直接冲突**。这是规格缺陷在提示词里的落地，不是模型不听话。

**加重 1：跨轮事实不可靠地可观测。** 聊天请求不带历史（见 `coze-chat-request-is-stateless` 教训）；
会话工作记忆只留上一答**前 200 字**（`nodes.py:906`），而 `options` 块在回答**末尾**——
「上一轮已经给过方案卡」这件事基本读不到。⇒ 判别器只能由**前端写进提问**。

**加重 2：评审被明文禁止检查这件事。** `SYSTEM_PROMPT_CRITIC`：
「【编辑建议】块的校验：忽略其 `kind` 取值（patch/options/replace）与 code 内容本身，
**不得因 `kind` 为 options/replace 或代码风格判失败**。」⇒ 第二道防线主动失效（实测两轮都 `true`）。

**附带（可独立修，实测旁证）**：`conservative_intent` 的「第」字误命中——
第二步提问里的「第一次出现」含「第」，于是痕迹里 `intent` 被记成 `data_query`。
已核：32 条 golden 样本**无一暴露**此误判（无「第 X 步/行」以外的「第」字形）。

### 0.3 取证命令与产物（可复跑）

取证脚本已**入库**为 `tools/probe_concept_and_optimization.py`（走评估系统的既有 remote 通道
`eval/runner/e2e_remote.chat_remote`，凭据取 `.env` 的 `COZE_API_URL` / `COZE_API_TOKEN` / `COZE_PROJECT_ID`）：

```bash
uv run python tools/probe_concept_and_optimization.py --dry-run   # 只看构造出的 payload，不发请求
uv run python tools/probe_concept_and_optimization.py --out probe.json   # 真实打 3 次请求
```

报告 `concept` / `opt-step1` / `opt-step2` 三组结果；`opt-step2` 的提问是**用 `opt-step1` 自己返回的
`options`** 按前端 `buildGoalPrompt` 拼出的（脚本内实现已逐字对齐
`frontend/src/utils/editSuggestion.test.js:238-266` 的三条期望串）。

两处**诚实标注**：

1. 实测 4 的第二步提问是**用实测 3 自己的 options 拼的**（与前端模板同构且逐字相同），不是用户原话；
   用户原话在截图与痕迹之外不可得。
2. 实测 2 未能复现「回答当前步」，故**不能**声称已找到该症状的充分触发条件；
   本文的修复针对的是已被证明的「意图不生效 + 上下文无差别锚定步骤 + 评审无意图门」这三条结构性缺陷。

**注意**：每次真实运行都会消耗 Coze 侧模型额度；`opt-step2` 依赖 `opt-step1` 的返回，不可单独跑。

---

## 1. 修复方案（设计决策）

| # | 决策 | 理由 |
|---|---|---|
| **D1** | **给优化第二步加显式标记**：前端提问以 `【优化第二步】` 起头；「第二步」的触发条件从「措辞像已指明目标」改为**标记**；`optimization.py` 删除与之冲突的那一条 | 无状态 + options 块在回答末尾 ⇒ 提问本身是**唯一**可靠判别器；标记延续 spec 已有的「确定、可日志」原则，且**向后兼容**（旧前端不发标记 ⇒ 行为与今天一致） |
| **D2** | **把意图接进作答路径**：`propose` 按 intent 渲染「本轮问题类型」段（concept 题：直接讲解概念本身、不围绕当前执行位置作答、默认不调 `step_facts`） | 根因 1。让「已判定为概念讲解」真正生效。空/`data_query` 时**不追加**，保证既有基线逐字不变 |
| **D3** | **概念题不注入 `### 当前执行位置`**（`gather()` 按 intent 门控）；`### 项目结构` 保留 | 根因 2。该块是症状的直接锚点；概念题可从代码 + 知识作答，不需要「第几步/第几行」。保留项目结构是为了让 `file` 参数可定位 |
| **D4** | **`build_context_node` 的 `system_instructions` 由硬编码 `"other"` 改为按 intent** | 根因 1 的同一处。恢复按意图的输出契约（如 `CONTRACTS["concept"]` 的「先给核心定义…禁止脱离本次代码空谈教材内容」）。用 `build_system_prompt(intent)` 而非只取契约，以免丢掉其携带的**领域词汇/领域本体**块 |
| **D5** | **评审加意图门**：事实块增「问题类型」行；concept 题**不得**因未引用步骤数据/代码行而判失败 | 根因 3。直接对应「此类回答往往评审未通过而被修订」。**⇒ 已被 `docs/spec/2026-09-14-critic-revise-optimization-design.md` CD-4 取代，本计划的 Task 5 不再单独执行** |
| **D6** | **评审在「带第二步标记」时获得否决权**：把现「不得因 `kind` 判失败」收窄为「非第二步不得因 `kind` 判失败」；带标记却给 `options`/空 `code` ⇒ 判失败 | 加重 2。给两步式补第二道防线。**⇒ 已收编进同一 spec 的 CD-4 第 4 条，本计划的 Task 8 不再单独执行**（同一段提示词不得并行改）。**⇒ 2026-09-14 复审追加：该否决权是提示词条款，实测仍会偶发失效**（同一字面提问 10 次里 1 次回落成方案卡），故由确定性门闩兜底，见 `docs/plan/2026-09-14-optimization-step2-delivery-gate-plan.md` |
| **D7** | `conservative_intent` 的「第」改为要求 `第 N 步/行` 形状 | 误判污染痕迹与检索指标；golden 样本零暴露，改动安全 |

**明确不做**（避免将来重复论证）：

- 不改外壳 / Java 代理 / SSE 协议；不引入跨轮服务端状态——判别器写在提问里。
- 不改「无标记时先出方案卡」这一既有产品决策（spec §4.3 line 107/109 的前半句仍然有效）。
- 不重开 `options` 卡的交互形态（多选/提交制维持现状）。
- 不重排 `[Role & Policies]` 里的角色身份（`build_system_prompt` 同时带角色句与词汇/本体块，
  两者耦合是**既有**状态，本次只把 `"other"` 换成真实 intent；拆分是后续独立议题）。

---

## 2. Tasks（TDD：每条先写失败用例）

### Task 0（取证，**不阻塞其余 Task**）：取一条现场证据

请联调侧复现一次概念题，从痕迹与回答里抓这四项：

1. `intent` 是否为 `concept`；
2. `critic_passed` 与 `revised`（实测 1 的形状：`false` / `true`）；
3. 可见回答**修订前后是否不同**（需在浏览器 Network 里取一次原始 SSE 首帧，或临时关掉 `revise` 对照）；
4. 同一会话里此前是否问过「当前这一步」类问题（工作记忆是否把话题锚在步骤上）。

用途：区分症状主因是**模型漂移**还是**修订改坏**。Task 1–5 针对的都是已确认的结构性缺陷，
无论 Task 0 结果如何都要修；若 Task 0 显示「漂移」为主，则 D3 就是主修；若显示「修订改坏」，
则 D5 之外还要单独审 `SYSTEM_PROMPT_REVISE` 的事实依据构成（本计划不含该改动）。

---

### Task 1（coze）：意图接入作答路径（D2）

**失败用例**（新建 `tests/test_intent_guidance.py`）：

- `test_concept_gets_concept_guidance`：`_main_system_prompt("concept")` 含「概念讲解」与
  「不要围绕当前执行位置」字样，且含「默认不要调用 `step_facts`」。
- `test_data_query_prompt_unchanged`：`_main_system_prompt("data_query")` 与 `_main_system_prompt("")`
  **逐字相同**（回归保护：既有基线不受扰动）。

**实现**：

- 新建 `src/graphs/javatutor/prompting/intent_guidance.py::render_intent_guidance(intent)`，
  仅对 `concept` / `debug` / `other` 返回段（`data_query` 与空串返回 `""`）。
- `harness/propose.py::_main_system_prompt(intent: str = "")` 在 few-shot 之前插入该段；
  `propose()` 传 `state.get("intent", "")`。
- `main_agent.py` 的 `_main_system_prompt` 再导出保持不变（默认参数保住无参调用）。

**影响面**：`tests/test_optimization_guidance.py:234`、`tests/test_run_mode_context.py:103` 以无参调用 ⇒ 不受影响。

---

### Task 2（coze）：概念题不注入当前执行位置（D3）

**失败用例**（`tests/test_context_builder.py` 追加）：

- `test_concept_omits_position_packet`：`intent="concept"` ⇒ 上下文**不含** `### 当前执行位置`。
- `test_data_query_keeps_position_packet`：`intent="data_query"` ⇒ 仍含（钉住既有行为）。

**实现**：`gather()` 里 `has_position` 增加 `state.get("intent") != "concept"` 条件。

> ⚠ 该分支会**收紧**概念题的上下文。执行时必须确认既有概念类断言/评估样本不依赖该块，
> 并全量跑 `uv run pytest tests/ -q` 逐条核对。

---

### Task 3（coze）：按意图给输出契约（D4）

**失败用例**（`tests/test_graph.py` 或 `test_context_builder.py`）：

- `test_build_context_node_uses_intent_contract`：intent=`concept` 时，
  `build_context_node` 传给 `build_context` 的 `system_instructions` 含 `CONTRACTS["concept"]` 的首句；
  intent 缺失时为 `"other"`。

**实现**：`nodes.py:874` → `build_system_prompt(state.get("intent") or "other")`。

**为什么用 `build_system_prompt` 而不是 `get_contract`**：前者同时携带**领域词汇**与**领域本体**块
（`prompts.py:159-165`），只取契约会让这两块从上下文中消失，属计划外损失。

---

### Task 4（coze）：补一条「概念」few-shot（根因 2 余项）

**失败用例**（`tests/test_main_fewshots.py`，或并入既有 few-shot 用例）：

- `get_main_few_shots()` 至少含 1 条概念类示例；
- 该示例文本**不含**「当前执行位置」「第 N 步」「当前行」等步骤锚点字样。

**实现**：`prompting/main_fewshots.py` 增 1 条——
问「X 算法的原理是什么」→ 答「先给定义/核心思想/适用边界/复杂度，结合本项目代码指一句」，
**不取步骤证据、不附步骤引用**。样本仍带 `MARKER`（数值仅示意）。

---

### Task 5（coze）：评审意图门（D5）—— **不再单独执行，改由 `2026-09-14-critic-revise-optimization-plan.md` Task 3 落地**

> 本 Task 的全部内容（事实块增「问题类型」行 + `SYSTEM_PROMPT_CRITIC` 增 concept 免罚条款）已并入
> 评审表整体改写（该计划 CD-4）。此处保留原文仅为追溯，执行时**跳过**，以免同一段提示词被改两遍。

**失败用例**（`tests/test_contexts_facts.py` 或 `test_critic.py` 追加）：

- `test_facts_block_states_intent`：`build_facts_block` 含「问题类型」行并在 `concept` 时标为「概念讲解」。
- `test_critic_prompt_has_concept_exemption`：`SYSTEM_PROMPT_CRITIC` 含条款——
  `concept` 且 `step_facts` 为空时，**不得**因「未引用步骤号/行号/变量值/代码行」判失败。

**实现**：`prompting/contexts.py::build_facts_block` 增一行（沿用既有「缺失即不加行」的口径，
`intent` 缺失时不加，零行为变化）；`prompts.py::SYSTEM_PROMPT_CRITIC` 增一条免罚条款。

---

### Task 6（coze）：两步式判别器（D1，Bug D 主体）

**失败用例**（`tests/test_optimization_guidance.py` 追加 + 改写）：

- `test_step2_marker_is_the_discriminator`：引导段含 `【优化第二步】` 字样，
  且含「提问带该标记时必须交付 `kind:"replace"` 完整代码，禁止再出 `options`」。
- `test_no_contradicting_bullet`：引导段**不再含**「用户已指明目标…同样先出方案卡」这条冲突条目。
- `test_few_shots_step2_questions_carry_marker`：`MAIN_FEW_SHOTS` 里两条第二步示例的**提问文本**
  以 `【优化第二步】` 起头（与前端模板一致，否则 few-shot 教的是另一种形状）。

**实现**：

- `prompting/optimization.py`：
  - 第一步条目改为「**提问里没有第二步标记时**：只给方案卡」（把「用户已指明目标」这一判别依据删掉）；
  - 第二步段开头加「**提问以 `【优化第二步】` 起头时**：直接交付 `replace`，不得再出方案卡」；
  - 保留既有的方向白/黑名单硬约束与候选返修段。
- `prompting/main_fewshots.py`：两条第二步示例提问前加 `【优化第二步】`。

---

### Task 7（前端）：第二步提问带标记（D1）

**失败用例**（`frontend/src/utils/editSuggestion.test.js`）：

- `buildGoalPrompt(单方向, 排除项)` 与 `buildGoalPrompt(多方向, 排除项)` 的返回值**均以 `【优化第二步】` 起头**；
- 空选择仍返回 `''`。

**实现**：`editSuggestion.js::buildGoalPrompt` 加固定前缀常量；同步更新
`editSuggestion.test.js:238-266` 与 `stores/__tests__/player-optimization.test.js:213/224/233` 的期望串。

> 与 spec 的关系：§4.4 的模板要同步加前缀（Task 10），否则文档与实现不一致。

---

### Task 8（coze）：评审对第二步的否决权（D6）—— **不再单独执行，改由 `2026-09-14-critic-revise-optimization-plan.md` Task 3 落地**

> 同上：本条与 concept 免罚条款改的是**同一段** `SYSTEM_PROMPT_CRITIC`，合并进评审表改写一次完成。
> 执行时**跳过**本 Task，只保留其失败用例的意图（带 `【优化第二步】` 却给 `options`/空 `code` ⇒ 判失败），
> 该用例在优化计划的 Task 3 中重建。

**失败用例**（`tests/test_prompts.py` 或既有 critic 用例）：

- `SYSTEM_PROMPT_CRITIC` 含第二步条款：提问带 `【优化第二步】` 却给出 `kind:"options"`、
  或 `replace` 的 `code` 为空/含 `...` 占位 ⇒ **判失败**；
- 原「不得因 `kind` 为 options/replace 判失败」被限定为「非第二步时不得因 `kind` 判失败」。

**实现**：改写 `SYSTEM_PROMPT_CRITIC` 中【编辑建议】块校验那一段。

---

### Task 9（coze）：意图关键字修正（D7）

**失败用例**（`tests/test_intent_rules.py` 追加）：

- `conservative_intent("只做「以性能为先」方向的优化，具体要求：用哈希表记录每个元素第一次出现的下标。")`
  **不**返回 `data_query`；
- 既有 `conservative_intent("为什么第 2 步 arr[1] 变了？") == "data_query"` 保持通过。

**实现**：`intent_rules.py` 的 `DATA_QUERY_KEYWORDS` 里「第」/「步」改为形状匹配
（`第\s*\d+\s*步` / `第\s*\d+\s*行`），沿用 `_WORD_BOUNDED` 的既有做法。

---

### Task 10：文档同步

| 文档 | 改什么 |
|---|---|
| `docs/spec/2026-09-10-coze-agent-code-optimization.md` | §4.3 增「判别器 = 第二步标记」；§4.4 模板加 `【优化第二步】`；§4.2 增 `replace` 的评审门 |
| `docs/spec/2026-08-10-coze-agent-interface.md` | 增记：`intent` 影响输出契约与评审门；优化第二步提问带标记 |
| `docs/agent-collaboration-guide.md` | 若「处理流程 / 意图」相关表提及按意图作答，同步为「意图进入主 Agent 提示与评审事实」 |
| `AGENT.md` | 登记本计划 + 对应 devlog / review |

---

## 3. 验收标准

1. **概念题不再以步骤作答**：`intent=concept` 时，可见回答不以「当前执行位置 / 第 N 步 / 当前行」为主语，
   且上下文里**没有** `### 当前执行位置`（D2 + D3）。
2. **概念题不再被评审误杀**：`intent=concept` 时 `critic_passed` 不再因「未引用步骤数据」为 `false`
   （D5；实测 1 的 `false/true` 形状应消失）。
3. **优化第二步必给代码**：带 `【优化第二步】` 标记的提问，回答含 `kind:"replace"` 且 `code` 为完整文件全文，
   **不出现** `kind:"options"`。**判据（2026-09-14 复审修正）**：单次通过不构成证据——同一字面提问**连续 10 次**全部交付 `replace`
   （线上实测基线为 10 次里 1 次回落），且 `decision_trace.optimize_step2_gate` 全部为 `passed` 或 `violated`
   而**不为**「门闩不存在」。离线侧由 `tests/test_answer_gate.py` 的失败回灌用例兜住（D1 + 确定性门闩）。
4. **无标记时行为不变**：「帮我优化一下这段代码」/「优化性能」仍出方案卡（D1 的兼容边界）。
5. **第二道防线生效**：带标记却给 `options`/空 `code` ⇒ 终答被**确定性门闩**拒绝并回灌重提案
   （`tests/test_answer_gate.py::test_rejected_options_card_is_retried_until_replace`，离线、不依赖模型）；
   评审侧的提示词否决权（D6）仍保留，但**不再是唯一防线**。
6. **意图误判修正**：优化类提问不再落 `data_query`（D7）。
7. **不回归既有红线**：哨兵顺序与过程式输出、被拒工具名不入用户可见产物、导航/编辑建议块不回归、
   fetch 摘要仍含 `file` / `file_source` / `code_chars`。

---

## 4. 验证命令与门槛

```bash
# coze（本次实测基线：431 passed）
cd javatutor-coze && uv run pytest tests/ -q

# 前端（上手先实测基线；本仓最近记录为 444 passed / 33 files）
cd JavaTutor/frontend && npx vitest run && npm run build
```

**端到端取证（本计划以此取证）**：`uv run python tools/probe_concept_and_optimization.py --out probe.json`，
确认 ① 概念题的 `critic_passed` 形状改变且上下文不再含位置块；
② B1→B2 序列中 `opt-step2` 返回 `replace` 而非 `options`。

> **2026-09-14 复审修正（单次通过不作数）**：② 必须把同一条 B2 提问**重复 N=10 次**，10 次全为 `replace`
> 才算通过——原判据只跑了 1 次，恰好落在成功的那 9/10 里，掩盖了 1/10 的回落。
> 逐次的裁决与重试次数看 `decision_trace.optimize_step2_gate` / `optimize_step2_retries`（读法见
> `docs/dev-eval-guide.md` §6）。门闩本身的行为已由离线用例固定，故 N=10 验的是「模型行为 + 门闩兜底」的合成结果，
> 门闩失效（`violated`）也算可接受结果之一**但必须可见**，不得再被当成通过。

**评估门槛**：本次改动触及作答路径（提示词/上下文）与评审 ⇒ 须在**重发 agent 后**补一轮端到端评估，
判据沿用既有门槛（Judge 均分下降 ≤ 0.3 且 Grounding 下降 ≤ 0.5）。
未重发则离线门槛全绿即可，但须在 devlog 里注明「**线上未验证**」（与上一份计划同一口径）。

---

## 5. 风险与回滚

| 风险 | 影响 | 处置 |
|---|---|---|
| Task 2 概念题不再注入位置块 | 被判成 `concept` 却真需要「当前步」的问法（如「当前这行为什么这么写」）会缺信息 | 提示词引导：需要时用 `file` 参数取代码；若出现回归，退化为「降 relevance + 明写规则」而不删块 |
| Task 3 换契约身份 | 上下文 `[Role & Policies]` 从「通用助手」变「概念专家」，与主 Agent 身份并存 | 两段角色并存是**既有**状态（今天已是「主 Agent 提示 + other 角色」）；本次只换 intent。**不**因 identity 并存判失败（避免造出新幻觉判据） |
| Task 6/7 标志位 | 旧前端不发标记 ⇒ 退化为现状（第二次仍出卡） | 标记是**纯增量**：无标记时行为与今天完全一致，两侧可分别上线 |
| Task 7 模板变更 | 历史日志/回放里的提问形状变化 | 只影响新增提问；golden 集不含优化样本，评估基线不受影响 |
| Task 8 评审收权 | 评审变严可能提高 `revise` 频率 | 只对**带标记**的第二步生效，作用域极窄；若真的误判，`revise` 保留编辑块（`critic.py:114`）不会丢交付物 |

**回滚单位**：Bug C（Task 1–4）与 Bug D（Task 6–7）**完全独立**，任一可单独回滚；Task 9 独立。
（评审侧改动按 `2026-09-14-critic-revise-optimization-plan.md` 自己的回滚单位计。）

---

## 6. 执行顺序建议

```
Task 0（取证，可与其余并行）
Task 9                                    # 意图关键字，独立、最小
Task 1 → Task 2 → Task 3 → Task 4         # Bug C：同一链路，串行（提示词 → 上下文 → 契约/few-shot）
Task 6 → Task 7                           # Bug D：coze 引导段 → 前端标记
Task 10                                   # 文档
```

**评审侧改动（原 Task 5 / Task 8）不在本计划内**：统一由
`docs/plan/2026-09-14-critic-revise-optimization-plan.md` 的 Task 3（评审表整体改写）落地。
两份计划的评审改动**不得并行**；本计划先落 Task 1–4 / 6–7，评审表改写再动手。
