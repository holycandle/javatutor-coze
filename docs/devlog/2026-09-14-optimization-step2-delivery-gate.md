# 2026-09-14 优化第二步交付形态门闩（`answer_gate`）— 实施记录

> 审查：`docs/reviews/2026-09-14-optimization-step2-marker-nondeterminism-review.md`
> 计划：`docs/plan/2026-09-14-optimization-step2-delivery-gate-plan.md`（Task 1–8）
> 上游：`docs/plan/2026-09-14-fix-concept-intent-and-optimization-loop-plan.md`（D1 判别器 + Task 7 前端标记）

交付边界：到**离线全绿**为止（L1–L5 + 前端 vitest + `npm run build`）。**不含**重新发布 agent。
按计划 §3，**线上 N=10 验收未做**，见 §4.2。

---

## 1. 症状与根因

### 1.1 症状（审查 §1，线上复现）

用户反馈「选完优化方向后，agent 还是不断给优化方向让我选，不给代码」——即带 `【优化第二步】`
标记的提问拿到了 `kind:"options"` 方案卡而不是 `kind:"replace"` 整份代码。

性质是**间歇**的：审查在同一字面提问上连测 10 次，**1 次 options / 9 次 replace**（成功时块形态全对）。

### 1.2 排除项（审查已做，本件不再重复）

- **不是「未重发」**：痕迹里的批次三键与 `git log -S` 都指向同一提交 `12e3f4b`。
- **不是意图识别当触发器**：ablation 2 次均得到 `replace`。
- **不是标记没生效**：判别器本身工作正常（9/10 走对了分支）。

### 1.3 根因（结构性）

**全链路没有任何环节检查「带标记的提问是否拿到了 replace」。** 唯一约束是
`prompting/optimization.py` 的一段自然语言 + `MAIN_FEWSHOTS` 里一条与本例几乎逐字相同的样本
——即一条**祈使句而非门闩**。提示词条款是概率性的，1/10 的违背落在这个概率里。

⇒ 修法不是「把提示词写得更凶」（那只是把 1/10 变成 1/50，无法判定何时算修好），而是
**把判据做成代码**：与 `guard`/`verify` 同源的治理层，不合规就拒绝该终答并回灌重提案。

---

## 2. 做了什么

### 2.1 新模块 `harness/answer_gate.py`（核心）

三个纯函数 + 一个节点，不调 LLM、不做 IO：

| 符号 | 职责 |
|---|---|
| `step2_applies(question)` | 只认一个判据：`lstrip` 后以 `STEP2_MARKER`（**从 `prompting/optimization.py` 导入**）起头 |
| `check_step2_answer(question, answer) -> GateVerdict` | 纯判据，返回 `passed` / `violated(reason)` / `not_applicable` |
| `answer_gate_node(state)` | 放行 / 回灌重提案 / 预算耗尽记 `violated` |
| `route_after_answer_gate(state)` | `retry → "propose"`，其余 → `"critic"` |

**合规定义**：终答里**恰好一个** `【编辑建议】` 块，且 `kind == "replace"`、`code` 非空字符串、
`code` 不含 `...` 省略占位、块里不含 `options` 字段。

两处关键实现选择：

1. **块 JSON 用 `json.JSONDecoder().raw_decode` 平衡解析**，不用正则/非贪婪——Java 代码里有 `{`/`}`，
   非贪婪会在第一个嵌套 `}` 处截断，把**合规**的 `replace` 误判成违规（既有 `_strip_leaked_json` 同法）。
2. **省略占位判定带 varargs 例外**：`_ELISION = (?<![A-Za-z0-9_\]>])\.\.\.`——
   `String... args` 是 Java 里 `...` 唯一合法的用途，前一个字符是标识符，故不判违规。

### 2.2 回灌通道是 `HumanMessage`（Bug A 红线）

`answer_gate_node` 在违规且预算未耗尽时返回：

```python
{"answer": "", "tool_rounds": rounds + 1,
 "agent_messages": [..., _retry_message(...)],       # HumanMessage
 "answer_gate_decision": {"verdict": "retry", ...}}
```

- **清空 `answer`**：不清的话被拒的终答会被 `build_final` 当兜底答案交付
  （`revised_answer or answer`），而这一轮的意义正是「这一版不算数」。
- **绝不写 `AIMessage`**：`propose` 终答轮的 Bug A 教训（`docs/devlog/2026-09-14-fix-fetch-context-and-duplicate-answer.md`）
  ——`stream_mode="messages"` 会把节点返回键里的非 chunk `AIMessage` 转成 `answer` delta，
  经前端纯累加后与 `build_final` 的终答合成「正文重复两遍」。故回灌只走 `HumanMessage`，
  被拒终答既不进 `agent_messages` 也不以任何 `AIMessage` 形式回流（用例
  `test_node_retries_and_clears_the_rejected_answer` 显式断言）。
- **不写 `step_records`**：那记的是「逐动作的观察」，门闩没执行任何动作。

### 2.3 共享轮次预算（与 `guard` 同一笔账）

门闩的 retry 分支 `tool_rounds += 1`，与 `guard_node` 入口同记一笔。设 `g` = `guard` 进入次数、
`r` = 门闩重试次数，则 **`g + r <= MAX_ROUNDS = 3`**；`main_agent` 访问次数 `<= MAX_ROUNDS + 1 = 4`
（第 4 次即收束轮）由结构保证。

**收束轮之后不再重试**：`rounds >= MAX_ROUNDS` 时 `propose` 永不产出 `Action`，
再来一轮只会多花一跳 ⇒ 门闩直接记 `violated`、按收束策略交付。

**图跳数联合界**（spec §4.3）：

```
6 个前置 + main_agent(1+g+r) + guard g + run_tools g + answer_gate(r+1) + 5 个后置
= 13 + 3g + 2r  ≤ 22  （g + r <= 3，最大在 g=3, r=0）  < 25（LangGraph 默认 recursion_limit）
```

⚠ **这里改了一个既有判据**，原因必须留档：`tests/test_harness_termination.py` 原来断言
`6 + (MAX_ROUNDS+1) + MAX_ROUNDS + MAX_ROUNDS + 5 = 21`（朴素地把各节点最大值相加）。
加入 `answer_gate` 后这种加法得出的 `25` **不可达**——取满 `guard=3` 就取不到 `answer_gate=4`，
两者受同一预算约束。所以测试改为按**联合界**遍历 `g`，断言 `worst == 22`，
并在 docstring 里写明「不要照着朴素上界 25 改，那是假警报」。

### 2.4 图接线（`graph.py`）

```
main_agent ─(answer)→ answer_gate ─(pass / violated / not_applicable)→ critic → revise → verify → …
    │                     │
 (action)            (retry：终答形态不合规)
    ↓                     ↑
  guard ─(allow)→ run_tools ─┘（回 main_agent）
```

- `_route_after_propose`：`"guard" if proposed_action else "answer_gate"`。
- 新增节点 `answer_gate`；节点数 **11 → 15**。
- `guard` 仍是唯一的 HITL 暂停点（门闩不暂停，只回灌）。

### 2.5 状态与痕迹

- `state.answer_gate_decision`（`{"verdict", "reason", "retries"}`，与 `guard_decision` 同形）。
  `verdict` 取 `passed` / `violated` / `not_applicable` 及**瞬态** `retry`（终态不会停在它上面）。
- `decision_trace` 增两键（由上述字段派生，不另存一份）：
  `optimize_step2_gate`（缺省 `not_applicable`）与 `optimize_step2_retries`（缺省 `0`）。

### 2.6 意图误判修正（审查 §3.2，采纳选项②）

`conservative_intent` 里 `DATA_QUERY_KEYWORDS` 含「变量」，而第二步提问的黑名单文案由前端模板拼出、
**必含**「命名中间变量」这类字样 ⇒ 第二步提问被稳定判成 `data_query`。

代价不只是痕迹记错：`build_context_node` 会据此注入 `data_query` 的角色与输出契约
（「在哪一步、哪一行、哪个变量」，长度 3–6 句），与「交付整份 replace 代码」**直接竞争**。

修法：**提问以 `STEP2_MARKER` 起头时一律不取 `data_query`**，归 `other`
（本类提问没有专属角色段，`other` 的引导无害）。判定放在 `DEBUG_KEYWORDS` 之后、
`DATA_QUERY_KEYWORDS` 之前——硬性 debug 信号优先级不变。

> 审查已定性：这条耦合是**真缺陷但非本次触发条件**（ablation 2 次均 replace），故修它不改症状，
> 属于「顺手把已经证明是错的判据改对」。

### 2.7 改动清单

| 文件 | 改动 |
|---|---|
| `src/graphs/javatutor/harness/answer_gate.py` | **新增**：判据 + 节点 + 路由 |
| `src/graphs/javatutor/graph.py` | 接线（节点 + 两条条件边 + 路由函数改名分支）与拓扑 docstring |
| `src/graphs/javatutor/state.py` | 新增 `answer_gate_decision` |
| `src/graphs/javatutor/nodes.py` | `build_final` 增两键 |
| `src/graphs/javatutor/intent_rules.py` | 第二步标记不取 `data_query` |
| `tests/test_answer_gate.py` | **新增**：21 例（纯判据 11 / 节点 6 / 图级 4） |
| `tests/test_harness_termination.py` | 联合界 + 病态第二步模型终止用例 |
| `tests/test_intent_rules.py` | 3 例（不取 data_query / 不压过硬 debug / 只认句首） |
| `tests/test_graph.py` / `tests/test_build_final.py` | 节点存在性 / 痕迹缺省值 |
| `docs/spec/2026-09-11-…` §4.2 / §4.3 / §4.9 / §5.1 / §7 | 拓扑、联合界、新门闩节、影响面、验收 |
| `docs/spec/2026-09-10-…code-optimization.md` §4.3 / §8 / §9 / §10 / §11 | 门闩条款、N=10 判据、用例、风险、登记 |
| `docs/spec/2026-08-10-…interface.md` | 痕迹 schema 增两键 + 字段表两行 |
| `docs/agent-collaboration-guide.md` | 流程图 / 四步表 / 信息分层表 / 节点表 / 状态字段 / 痕迹两键 |
| `docs/dev-eval-guide.md` | 新增「交付形态门闩怎么看」 |
| `docs/plan/2026-09-14-fix-concept-intent-…-plan.md` | 验收 3/5 与端到端取证口径按审查修正 |
| `AGENT.md` | 登记本计划 + 本记录 |

---

## 3. 验证

### 3.1 全绿

| 门槛 | 命令 | 结果 |
|---|---|---|
| L1 | `uv run pytest tests/ -q` | **511 passed**（基线 484，+27） |
| L2.5 | `uv run pytest tests/test_eval_component.py -v` | 5 passed |
| L3 | `PYTHONPATH=src … build_agent().builder.compile()` | `ok` |
| L4 | 本地 HTTP 冒烟 | **SKIP**（需本地 PostgreSQL 与模型端点） |
| L5 | 两条外壳回归命令 | **无输出**（外壳未动） |
| 前端 | `npx vitest run` | 33 files / **445 passed**（未改前端，纯回归） |
| 前端 | `npm run build` | built ok |

> `uv run python tools/eval_cli.py component` 在本仓 CLI 路径下 `pass_rate = 0.8`，
> 唯一失败项是 `c05`（rag 类型，CLI 未传 `rag_search`）——**既有状态**，与本次改动无关
> （`intent` 用例 c01/c02 均 ok）；L2.5 的门槛命令是上面那条 pytest。

### 3.2 验收项对照（计划 §3）

| 验收 | 结果 |
|---|---|
| 判据：合规 `replace` 放行 | ✅ `test_compliant_replace_passes` |
| 判据：五种违规形状各自被拦 | ✅ options / 两块 / `kind` 缺失 / `code` 空 / `code` 含 `...` |
| 判据：varargs 不误判 | ✅ `test_varargs_is_not_an_elision` |
| 非标记提问不受影响 | ✅ `not_applicable` 且**不改** `answer`（不比不花额外跳） |
| 失败回灌（FakeModel 产 options → 被拒 → 改产 replace） | ✅ `test_rejected_options_card_is_retried_until_replace`（`main_calls == 2`、`retries == 1`、可见产物里**无**被拒那一版） |
| 耗尽（一直产 options） | ✅ `test_step2_options_only_model_terminates_within_budget`（`tool_rounds == 3`、`gate == "violated"`、无 `GraphRecursionError`） |
| **端到端产物断言** | ✅ `test_trace_keys_reach_the_user_visible_answer` 断言的是 `build_final` 拼出的 `answer` 文本（含 `"optimize_step2_gate":"passed"`），不止 trace 字典 |
| 联合界 | ✅ `worst == 22 < 25` |
| 意图修正 | ✅ `tests/test_intent_rules.py` 三例 |

**线上判据（N=10）未做**：见 §4.2。

---

## 4. 与计划的偏差与遗留

### 4.1 偏差（3 处，均有依据）

1. **计划 Task 1/2 的用例组织与取词按执行时的实际形状落定**：计划写的是类式分组
   （`TestStep2Predicate` / `TestAnswerGateNode`）与 `verdict == "pass"`；实际落成模块级函数，
   取词用 `"passed"`——与 `guard_decision` 的既有词汇、以及同步改过的 spec §4.9 / §5.1 /
   接口 spec 字段表保持一致（同一取值在多份文档里必须同字，否则消费方要处理两种拼写）。计划文件已就地标注该修正，
   不留在文档里误导后续读者。产物断言用例名落成 `test_trace_keys_reach_the_user_visible_answer`。
2. **计划 Task 5 的「探针工具复用第三份字面量」未按原样执行**：审查 §3.3 指出探针里曾有第三个
   `【优化第二步】` 字面量副本（漏了标记），已改为从 `prompting/optimization.py` 导入。
   门闩模块同样**只导入不复制** `STEP2_MARKER`；而 `EDIT_MARKER`（`【编辑建议】`）沿用既有两处
   （`nodes` / `critic`）的本地副本惯例，并加进那条守漂移断言
   （`test_edit_marker_matches_the_other_two_copies`）——不 import 节点层，因为 `harness/` 是引擎层。
3. **计划未预见「朴素上界 25 变成不可达」**：执行时发现既有终止性测试的加法在加入 `answer_gate` 后
   不再可达，遂把测试改为联合界（§2.3）。这是**收紧判据**而非放宽：新断言 `worst == 22`
   与在 `g + r <= 3` 下逐点遍历，比原来那条更贴近真实可达集合。另：计划 Task 6 写 `retries >= 1`，
   实际断言 `retries == MAX_ROUNDS`（更强，且能钉住「预算真的被吃满而不是溢出」）。

### 4.2 遗留（**需知悉**）

1. **线上 N=10 验收未做**（计划 §3 的 Task 8）：判据要求「同一字面第二步提问连测 10 次全部
   `replace`」。这必须在**重发 agent 之后**才有意义，本件不重发 ⇒ 现状是**离线全绿、线上未验证**。
   重发后按 `docs/dev-eval-guide.md` §6 读 `optimize_step2_gate` / `optimize_step2_retries`。
   注意：10 次里有 1–2 次 `passed` 带 `retries == 1` 也算**通过**——门闩兜住并交付了 `replace`，
   这正是修法的目的；只有 `violated` 才是「用户拿到的不是整份代码」。
2. **门闩只判形态，不判语义**：`kind == "replace"` + `code` 非空完整 ≠ 代码真的只改了所选方向。
   后者仍属提示层（spec §4.3 已写明「形态可判、语义不可判」），与既有
   `comprehensive` 不校验代码的口径一致。
3. **文档债（既有，本次未扩）**：`docs/spec/2026-08-10-coze-agent-interface.md` §3 的 trace schema
   示例早于本批改动，缺 `retrieval` / `reasoning` / `reasoning_truncated` / `verification` 四键
   （字段表里有，示例 JSON 里没有）。本次只登记了自己的两个键，**没有顺手补齐**——
   那是独立的一次 schema 示例同步，混进来会让本件的 diff 难以审查。

---

## 5. 回滚

门闩是一个**新增节点 + 一条条件边**，回滚单位即「把 `main_agent` 的终答分支指回 `critic` 并摘掉
`answer_gate`」——`answer_gate.py` 与 `state.answer_gate_decision` 可整文件/整字段删除，
痕迹两键会退回缺省 `not_applicable` / `0`（老消费方忽略即可）。
意图修正是**独立一处**（`intent_rules.py` 四行），可单独回滚。

---

## 6. 与既有红线的对照

| 红线 | 本件是否触碰 |
|---|---|
| 外壳（`.coze`/`scripts/`/`src/main.py`/`src/storage/`/`src/utils/`） | ❌ 未改（L5 无输出） |
| Java 后端 | ❌ 未改 |
| 前端 | ❌ 未改（445 passed 纯回归） |
| 新依赖 / `pyproject.toml` / `uv.lock` | ❌ 未引入 |
| 既有 `decision_trace` 键语义 | ❌ 未改；两键为**纯增量** |
| 三种末尾结构化块的契约 | ❌ 未改（门闩只是**读**【编辑建议】块） |
| `agent_messages` 的 ReAct 轨迹语义 | ❌ 未改；回灌走 `HumanMessage`，不冒充 AI 轨迹 |
| `state.messages` 入站契约 | ❌ 未改（门闩不碰 `messages`） |
| 被拒内容不得进用户可见产物 | ✅ 显式守卫（清空 `answer` + 不写 `AIMessage` + 产物级断言） |
