# 2026-09-14 优化第二步交付形态门闩（确定性 `answer_gate`）— TDD 实施计划

> 触发：联调侧反馈「**原重复给出优化选项的问题仍未解决**」——
> 本批 `12e3f4b`（标记判别器）**已部署之后**的反馈。
> 审查：`docs/reviews/2026-09-14-optimization-step2-marker-nondeterminism-review.md`
> （结论：判别器方向对，但**落地形式是祈使句而非门闩** ⇒ 死循环从必然降级为偶发，未被消除）。
> 涉及仓：**仅 `javatutor-coze`**。前端不动（标记已在前端，本次不改字面量）、后端不动、外壳不动。
> 关联 spec：`docs/spec/2026-09-11-agent-harness-react-loop-design.md` §4.9（新增）/
> §4.2 / §4.3 / §5.1 / §7；`docs/spec/2026-09-10-coze-agent-code-optimization.md` §4.3 / §8 / §9 / §10 / §11。

---

## 0. 症状与根因（审查已取证，不再重复取证）

线上实测（审查 §2）：带 `【优化第二步】` 标记的提问，**同一字面 10 次里 1 次**返回
`kind:"options"` 方案卡、9 次返回 `kind:"replace"` 完整代码。成功时交付形态**全对**
（`goal="performance"`、`target="Solution.java"`、`code` 393–456 字符、无 `...`、无 `options`）。

**根因（结构性）**：全链路**没有任何环节检查**「带标记的提问是否拿到了 `replace`」。
唯一约束是两处**模型可违背**的东西——系统提示的一段自然语言条款，和一条与本例几乎逐字相同的 few-shot。
⇒ 与评审链路（`critic` 的 G1–G4 验收闸）对照：那边的判据是**代码**（相似度 / 块保全 / 引用不劣化），
所以「修订不可回滚」成立；这边的判据是**祈使句**，所以只能降概率。

**附带发现（真缺陷，非本次触发条件）**：第二步提问被 `conservative_intent` 判成 `data_query`
（`DATA_QUERY_KEYWORDS` 含「变量」，而第二步提问的**黑名单**文案必含「变量命名 / 中间变量」）。
本批 Task 3 把 `build_context_node` 从硬编码 `"other"` 改成 `build_system_prompt(intent)` 之后，
`intent` 从「只进痕迹」变成**真的会注入角色与输出契约**——`CONTRACTS["data_query"]`
（「必须回答：在哪一步、哪一行、哪个变量…长度 3-6 句」）与「交付整份 `replace` 代码」直接竞争。

---

## 1. 设计要点（先写清楚，再写用例）

1. **门闩是代码，不是提示词**：新增纯函数判据 + 图节点 `answer_gate`，位于终答分支
   `main_agent --(answer)--> answer_gate --> critic`。
2. **判据只吃字符串与 JSON，不看模型**：提问以 `STEP2_MARKER` 起头时，终答必须恰好一个
   【编辑建议】块且 `kind == "replace"`、`code` 非空、无 `...` 占位、无 `options` 字段。
3. **违规 = 拒绝该终答 + 回灌一条错误观察 + 回 `main_agent` 重提案**，
   并由门闩**消耗一次共享轮次预算**（`tool_rounds += 1`，与 `guard` 同记一笔）。
   - **绝不把被拒终答写进 `agent_messages`**（Bug A 教训：`AIMessage` 会随
     `stream_mode="messages"` 变成 `answer` delta，与 `build_final` 重复输出）。
     回灌通道是 `HumanMessage`（与 `guard_node._append` 同形）。
   - **`tool_rounds >= MAX_ROUNDS` 时不再重试**：收束模式永不产出 Action，重试无意义；
     此时记为 `violated` 并按已定收束策略交付。
4. **预算算术**（硬约束，`recursion_limit` 默认 25 且**在外壳里改不了**）：
   `g`（guard 次数）+ `r`（门闩重试次数）`≤ MAX_ROUNDS = 3`（**共享**），
   worst = `6 + (1+g+r) + g + g + (r+1) + 5 = 13 + 3g + 2r ≤ 22`（余量 ≥ 3）。
   **不得**写「各节点最大值相加」的朴素上界（那会给 25 的假警报，见 harness spec §4.3）。
5. **记痕**：`decision_trace` 增 `optimize_step2_gate`（`passed` / `violated` / `not_applicable`）与
   `optimize_step2_retries`；`state` 只增一个键 `answer_gate_decision`（与 `guard_decision` 同形）。
6. **不做**：不改前端标记、不改【编辑建议】块协议、不改两步式产品形态；
   门闩**不覆盖**「候选返修」形状的提问（`prompting/optimization.py` 明确允许那一形状下只给正文说明）。

---

## 2. 交付范围

| # | 文件 | 动作 |
|---|---|---|
| 1 | `src/graphs/javatutor/harness/answer_gate.py` | 新建：`STEP2_APPLIES` 判据 + `check_step2_answer` + `answer_gate_node` + `route_after_answer_gate` |
| 2 | `src/graphs/javatutor/graph.py` | 加节点 `answer_gate`、改 `_route_after_propose` 的 `critic` 目标、加条件边、更新模块 docstring 拓扑图 |
| 3 | `src/graphs/javatutor/state.py` | 新增 `answer_gate_decision: dict` |
| 4 | `src/graphs/javatutor/nodes.py` | `build_final` 的 trace 增两键 |
| 5 | `src/graphs/javatutor/intent_rules.py` | 第二步标记前置：不得判成 `data_query` |
| 6 | `tests/test_answer_gate.py` | 新建（判据 8 + 节点 5 + 图级 3 + 产物 1） |
| 7 | `tests/test_harness_termination.py` | 预算算术改联合界 + 病态第二步模型用例 |
| 8 | `tests/test_graph.py` | 节点名/边断言补 `answer_gate` |
| 9 | `tests/test_intent_rules.py` | +3（标记提问 / 真实线上文案 / debug 硬信号优先） |
| 10 | `tests/test_build_final.py` | +1（两键缺省形状） |
| 11 | 文档 | 两份 spec（已改）/ 协作指南 / 接口契约痕迹 schema / dev-eval 指南 / devlog / AGENT.md |

**L5 红线**：`.coze`、`scripts/`、`src/main.py`、`src/storage/`、`src/utils/` 一个字节都不改。

---

## 3. 端到端验收判据（本件计划自用，取代原 Task 8 的「1 次通过」）

1. **离线**：`uv run pytest tests/ -q` 全绿（含下述新用例）。
2. **门闩失败回灌用例**（FakeModel 故意产 `options`，随后改产 `replace`）：终答为 `replace`，
   `optimize_step2_gate == "passed"` 且 `optimize_step2_retries >= 1`。
3. **耗尽用例**（FakeModel 一直产 `options`）：不抛 `GraphRecursionError`，
   `optimize_step2_gate == "violated"`，`tool_rounds <= MAX_ROUNDS`，`answer` 非空。
4. **端到端产物**（红线纪律）：断言的是 `build_final` 产出的 **`answer` 文本**里含
   `"optimize_step2_gate"`，而不是只在函数返回值/字典层断言。
5. **线上（须先重发 agent，本组对话不做）**：同一第二步提问 **连测 N=10 全部 `replace`**。
   本组不发布、不跑远程（每次真实运行消耗 Coze 侧额度）——本条**留待合入窗口**。

---

## 4. Task 分解（TDD：先写用例 → 红 → 实现 → 绿）

### Task 1 — 纯判据（`harness/answer_gate.py`）

- 先写 `tests/test_answer_gate.py::TestStep2Predicate`：
  1. 合规 `replace` 块 → `verdict == "passed"`（**执行时修正**：取值沿用 `guard_decision` 词汇，
     与 spec §4.9 / §5.1 / 接口 spec 字段表一致；原稿写作 `"pass"`）；
  2. `options` 块 → `violated`（reason 提到 `options`）；
  3. 两个【编辑建议】块 → `violated`；
  4. 无块（纯正文）→ `violated`；
  5. `kind` 缺失 → `violated`；
  6. `code` 为空串 → `violated`；
  7. `code` 含 `...` 占位 → `violated`；
  8. 非标记提问（含「帮我优化性能」这种已含目标的）→ `not_applicable`，且**不改动** `answer`；
  9. 标记不在开头（`好，【优化第二步】…`）→ 由 `lstrip` 决定；**按起头判定**，不命中即 `not_applicable`。
- 断言块 JSON **平衡解析**（把 Java 代码里带 `{`/`}` 的真实片段塞进 `code`，不得误判）。
- 实现：`STEP2_MARKER` 从 `prompting.optimization` **导入**（不落第三份字面量）；
  `【编辑建议】` 字面量在本模块留副本并配**漂移断言**（与 `critic` 的副本逐字相等）。

### Task 2 — 节点与路由

- 先写 `TestAnswerGateNode`：
  - 放行：返回 `answer_gate_decision.verdict == "passed"`，**不返回 `answer` 键**（不覆盖终答）；
  - 回灌：返回 `answer=""`、`tool_rounds == 进入前 + 1`、`agent_messages` 末尾是一条
    **`HumanMessage`**（不是 `AIMessage`）、且不含被拒终答的正文（防 Bug A 重复）；
  - 耗尽：进入前 `tool_rounds == MAX_ROUNDS` 时 → `verdict == "violated"`，**不 +1、不回灌、不改 `answer`**；
  - `not_applicable`：非标记提问 → 直接 pass 形状。
- `route_after_answer_gate`：`retry` → `"propose"`；其余 → `"critic"`。

### Task 3 — 接线（state / graph）

- `state.py` 新增 `answer_gate_decision: dict`（docstring 写明与 `guard_decision` 同形及两键派生关系）。
- `graph.py`：`add_node("answer_gate", answer_gate_node)`；
  `_route_after_propose` 的终答分支改 `"answer_gate"`（**判据仍是本轮 `proposed_action`**，理由见原 docstring）；
  新增 `add_conditional_edges("answer_gate", route_after_answer_gate, {"critic": "critic", "propose": "main_agent"})`；
  模块 docstring 的 ASCII 拓扑图同步。
- `tests/test_graph.py` 补 `assert "answer_gate" in graph.nodes` 与边断言。

### Task 4 — 痕迹两键

- 先写 `tests/test_build_final.py` 用例：无门闩记录时两键为 `"not_applicable"` / `0`（缺省形状稳定，
  既有消费方不会取到 `None`）。
- `build_final` 的 `trace` 增 `optimize_step2_gate` / `optimize_step2_retries`，由 `answer_gate_decision` 派生。
- **产物断言**（红线）：`tests/test_answer_gate.py::test_trace_reaches_user_visible_answer` 跑一次真图，
  在 `result["answer"]`（拼好的终态文本）里断言两键出现。

### Task 5 — 意图修正（`intent_rules.py`）

- 先写 `tests/test_intent_rules.py` 三条：
  1. `【优化第二步】只做「以性能为先」方向的优化…不要顺带做其他方向的改动（例如：「以可读性为先」：拆分长方法并命名中间变量）。请给出优化后的完整代码。` → **不得**是 `data_query`；
  2. 线上真实产出的黑名单文案（「添加注释并改进变量命名」）→ 同上；
  3. `compile_error` 非空 / 含 `报错` 的第二步提问 → **仍是 `debug`**（硬信号优先级不变）。
- 实现：在 `compile_error` 与 `DEBUG_KEYWORDS` 判定**之后**、`DATA_QUERY_KEYWORDS` **之前**插入
  「提问以 `STEP2_MARKER` 起头 ⇒ `return "other"`」。理由：`CONTRACTS["other"]` 对第二步无害，
  而 `data_query` 的角色与输出契约与「交付整份代码」竞争（§0 附带发现）。

### Task 6 — 终止性与病态模型

- 改 `tests/test_harness_termination.py::test_budget_arithmetic_fits_default_recursion_limit`：
  按 harness spec §4.3 的**联合界**重写（遍历 `g + r <= MAX_ROUNDS` 取最大），断言 `worst == 22` 且 `< 25`；
  注释里写明「朴素相加的 25 是**不可达的假上界**」。
- 新增 `test_step2_options_only_model_terminates_within_budget`：FakeModel 在第二步提问下**永远**
  返回 `options` 块（不设 `recursion_limit`，让默认 25 当守卫），断言不抛 `GraphRecursionError`、
  `optimize_step2_gate == "violated"`、`tool_rounds <= MAX_ROUNDS`、`optimize_step2_retries >= 1`。
- 保留既有两条（`main_calls == MAX_ROUNDS + 1`、直答不进环）不动，确认新节点不改变它们。

### Task 7 — 文档同步（含跨件收口）

| 文件 | 改动 |
|---|---|
| `docs/spec/2026-09-11-agent-harness-react-loop-design.md` | 已改（§4.2 拓扑/边、§4.3 联合界、§4.9 新增、§5.1、§7） |
| `docs/spec/2026-09-10-coze-agent-code-optimization.md` | 已改（§4.3 门闩条款、§8 验收 2、§9 测试、§10 风险、§11 登记） |
| `docs/spec/2026-08-10-coze-agent-interface.md` | 痕迹 schema 与字段表增两键 |
| `docs/agent-collaboration-guide.md` | 流程图加 `answer_gate`；节点职责段补一条 |
| `docs/dev-eval-guide.md` | 「检索为空」旁增「第二步门闩怎么看」（`optimize_step2_gate` 的三种取值） |
| `docs/plan/2026-09-14-fix-concept-intent-and-optimization-loop-plan.md` | Task 8 的端到端判据按本文 §3 改写（N=10 + 回灌用例） |
| `docs/devlog/2026-09-14-optimization-step2-delivery-gate.md` | 新建实现记录 |
| `AGENT.md` | 登记本计划与 devlog；行 37/38 的「未修好」判决补记「已由确定性门闩收口（离线），线上待重发」 |

### Task 8 — 门槛

- `uv run pytest tests/ -q` 全绿；`L5` 两条外壳回归命令**无输出**；
  前端 `npx vitest run` 与 `npm run build` 复核（本件无前端改动，作为回归证据）。
- L4 本地 HTTP 冒烟：SKIP（同前几轮）。

---

## 5. 风险与不纳入

- **残余风险**：门闩连续 N 次都被违背时仍会交付 `options`（概率随重试指数下降但非零）。
  这是**已接受**的：痕迹里有 `violated`，不再静默；彻底消除需要「模型永不违背」或「代码侧强制改写终答」
  （后者等于由程序生成 Java 代码，不在范围内）。
- **不纳入**：把门闩扩展成「语义校验」（代码是否真的只改了所选方向）——形态可判、语义不可判，
  后者仍属提示层（spec §10 已写）。
- **不纳入**：返修形状的门闩（见 §1.6）。
- **不纳入**：改 `MAX_ROUNDS` 或图外 `recursion_limit`（前者动评测基线，后者属外壳）。
