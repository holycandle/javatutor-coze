# 2026-09-14 评审-修订子系统优化计划

> 设计依据：`docs/spec/2026-09-14-critic-revise-optimization-design.md`（决策 CD-1 … CD-6）
> 触发：联调反馈「评审专家很鸡肋，总是把本来较为正确的答案改得答非所问」
> 涉及仓：`javatutor-coze`（**无前端改动**）
> 实测基线：coze `uv run pytest tests/ -q` = **431 passed**（2026-09-14）

---

## 0. 取证工具与基线（Task 0，不阻塞其余 Task）

新增 `tools/critic_audit.py`：对任意归档目录重算「评审 × Judge」交叉表，让 §1.2 的数字**任何人可复跑**。

```bash
uv run python tools/critic_audit.py eval/archive                  # 全部轮次汇总
uv run python tools/critic_audit.py eval/archive/2026-09-13       # 单轮
```

期望输出（与设计 §1.2 逐格一致）：`critic_failed 33 / revised 27 / of which judge=correct 11`，
按意图拆 `debug 14(5) / data_query 13(3) / other 5(2) / concept 1(1)`，`precision 22/33`、`recall 10/22`。

> 该工具只读归档，不发任何请求、不消耗模型额度。

---

## 1. Tasks（TDD：每条先写失败用例）

### Task 1（coze）：修订回滚闸 G1 / G2（CD-1，**最高价值，先做**）

**失败用例**（`tests/test_critic.py` 追加）：

- `test_low_similarity_rewrite_is_reverted`：原正文为一段较长回答、修订稿是**另一主题**的短文 ⇒
  `revised` 为 `False`、`revise_outcome == "reverted"`、`revise_revert_reason` 含 `similarity`，
  且 `revised_answer` 等于**原回答**。
- `test_blocking_issue_exempts_similarity_gate`：`critic_feedback` 里含 `"blocking": true` 的意见 ⇒
  低相似度重写**被采纳**（`revised` 为 `True`）。
- `test_revision_dropping_nav_block_is_reverted`：原回答含 `【视角导航】`、修订稿没有 ⇒
  回退并记 `revise_revert_reason` 含 `nav`。

**实现**（`src/graphs/javatutor/critic.py`）：

- 新增 `_similarity(a, b) -> float`：`difflib.SequenceMatcher(None, a, b).ratio()`。
- 新增 `_accepted(original_body, new_body, edit_block, feedback) -> tuple[bool, str]`：
  - **G2 结构块保全**：`_STRUCTURED_MARKERS`（从 `nodes.py` 复用或在本模块定义同一元组）里，
    原正文出现过的块在修订稿中必须仍在；【编辑建议】另需与暂存块**字节一致**；
  - **G1 相似度**：`_similarity(original_body, new_body) >= 0.5`；`critic_feedback` 里存在
    `"blocking": true` 的意见时**跳过 G1**；
  - 返回 `(ok, reason)`，`reason ∈ {"", "similarity", "nav_block", "edit_block"}`。
- `revise_node` 在成功调用 LLM 后过 `_accepted`；不过则返回
  `{"revised_answer": answer, "revised": False, "revise_outcome": "reverted", "revise_revert_reason": reason}`。
- `revise_node` 的三条既有 return 分支补 `revise_outcome`：
  `"skipped"`（评审通过 / 异常回退）。
- `src/graphs/javatutor/state.py`：增 `revise_outcome: str`、`revise_revert_reason: str`。

**⚠ 语义变更（执行时必须一并改，不是回归）**：`revised` 的含义从「修订节点跑过」收窄为
**「修订稿被采纳」**。以下 4 个既有用例的 fake 修订稿与原答相似度过低，会落进回退分支，
需按「用例意图」二选一改：给 fake 评审意见加 `"blocking": true`，或把 fake 修订稿改成与原答高相似度的文本。

| 用例 | 现断言 | 改法 |
|---|---|---|
| `tests/test_critic.py::test_revise_preserves_edit_suggestion_block` | `revised is True` | 原答正文仅一句、修订稿为「已修正的正文」⇒ 低相似度。给 `critic_feedback` 加 `blocking: true` |
| `tests/test_critic.py::test_revise_without_edit_block_keeps_prose_only` | `revised_answer == "修订后的回答"` | 同上（或把 fake 改成高相似度文本） |
| `tests/test_graph.py::test_deep_flow_critic_fails_triggers_revise` | `revised is True` | `CriticFailModel` 的 issues 加 `blocking: true` |
| `tests/test_harness_loop.py::test_graph_critic_failure_routes_through_revise` | `revised is True` | `RouterModel(critic_pass=False)` 的 issues 加 `blocking: true` |

保留一条「低相似度被回退」的新用例覆盖回退路径本身，避免「把闸门迁就成永远通过」。

---

### Task 2（coze）：评审意见必须给出处（CD-3）

**失败用例**（`tests/test_critic.py` 追加）：

- `test_issue_without_span_is_dropped`：评审返回
  `{"pass": false, "issues": [{"claim": "步骤号错", "answer_span": "这句话不在回答里", "fact": "…"}]}` ⇒
  `critic_passed is True`（该条被丢弃、无有效意见 ⇒ 通过）。
- `test_issue_with_valid_span_fails`：`answer_span` 为回答子串且 `fact` 为事实块子串 ⇒
  `critic_passed is False` 且 `critic_issues` 含该条。
- `test_legacy_string_issues_are_dropped`：issues 为字符串数组（旧格式）⇒ 全部丢弃 ⇒ 通过。

**实现**：

- `critic_node`：解析后逐条校验 `answer_span in answer`、`fact in facts_block`（去首尾空白）；
  不通过即丢弃。有效意见为空 ⇒ `critic_passed=True`、`critic_issues=[]`。
- `critic_feedback` 序列化为**有效意见的对象数组**（`json.dumps`，`ensure_ascii=False`），
  供 Task 1 的 `blocking` 判读与 Task 4 的修订提示使用。
- 保留 `_as_bool` 语义（`"false"` 字符串仍判失败）。

---

### Task 3（coze）：评审表按意图分流 + 格式检查出局 + 补「正面回答」条（CD-4）

> **本 Task 取代** `docs/plan/2026-09-14-fix-concept-intent-and-optimization-loop-plan.md` 的 Task 5（D5），
> 并**收编**其 Task 8（D6）。该计划的这两个 Task 不再单独执行。

**失败用例**：

- `tests/test_prompting.py`（或既有 prompt 用例）：
  - `SYSTEM_PROMPT_CRITIC` 含「仅当回答中**出现**该引用时才核对」的条件化条款；
  - 含「不得因回答未引用步骤数据判失败」；
  - 含「回答是否正面回答了学生问题」条款；
  - 含「`【优化第二步】` ⇒ `options` 或空 `code` 判失败」，且原「不得因 `kind` 判失败」被限定为
    「**非**第二步时」；
  - 代码块语言标签 / 单字符行 / 与 `line_text` 一致性的检查被标为**轻微问题、不判失败**，
    且**无对应 `step_facts` 的代码块一律豁免**。
- `tests/test_contexts_facts.py`：`build_facts_block` 含「问题类型」行，`concept` 时标为「概念讲解」；
  `intent` 缺失时不加行（零行为变化，钉住既有样本）。
- `tests/test_critic.py::test_concept_answer_with_illustrative_java_block_passes`：
  事实依据无 `step_facts`、回答含示意性 `java` 代码块 ⇒ 不再因格式判失败（对应归档 `q17`）。

**实现**：

- `src/graphs/javatutor/prompts.py::SYSTEM_PROMPT_CRITIC` 整体改写（保留输出 JSON 契约与
  「只返回 JSON」约束）；顺带修掉「核查五类引用」却列 6 条的措辞。
- `src/graphs/javatutor/prompting/contexts.py::build_facts_block` 增「问题类型」一行（缺失不加）。

---

### Task 4（coze）：引用不劣化闸 G3 + 二次评审闸 G4（CD-1 续）

**失败用例**（`tests/test_critic.py` 追加）：

- `test_revision_introducing_hallucination_is_reverted`：修订稿引用「第 99 步」（steps 只有 3 步）、
  原答无违规引用 ⇒ 回退，`revise_revert_reason` 含 `grounding`。
- `test_revision_failing_recheck_is_reverted`：注入的 model 第 2 次评审调用返回
  `{"pass": false, …}`（带有效出处）⇒ 回退，`revise_revert_reason` 含 `recheck`。
- `test_recheck_disabled_by_config`：配置关闭 G4 ⇒ 第二次评审不调用（用调用计数断言）。

**实现**：

- 抽出 `_critique(answer, facts, model) -> tuple[bool, list[dict], bool]`（`pass / 有效意见 / skipped`），
  `critic_node` 与 G4 共用，避免两处提示词漂移。
- G3：用 `graphs.javatutor.verification.verify_grounding`（与 `verify_node` 同源）比较
  `violations(修订正文) <= violations(原正文)`；**不改 `verify_node` 的任何语义**。
- G4：仅当 G1–G3 通过才跑；结果记 `revise_recheck_passed: bool`（`state.py` 增字段）。

---

### Task 5（coze）：advisory 模式开关（CD-5）

**失败用例**（`tests/test_critic.py`）：

- `test_advisory_mode_does_not_revise`：`critic_mode="advisory"` 且评审判失败 ⇒
  `revised is False`、`revise_outcome == "skipped"`，但 `critic_passed`/`critic_issues` **照常写入**。
- `test_default_mode_is_enforce`：配置缺失 / 读不到文件 ⇒ 默认 `enforce`（钉住向后兼容）。

**实现**：

- `config/agent_llm_config.json` 的 `config` 增 `"critic_mode": "enforce"` 与 `"critic_recheck": true`。
- `critic.py::_runtime_flag(name, default)`：先取 `COZE_WORKSPACE_PATH`（缺省用仓库根）下的配置文件，
  **读失败或键缺失一律回落默认值**（本地测试与旧部署都不会因缺配置而炸）。
- `revise_node` 在 `advisory` 下直接返回 `{"revised_answer": answer, "revised": False, "revise_outcome": "skipped"}`。

---

### Task 6（coze + eval）：可观测性（CD-6）

**失败用例**：

- `tests/test_build_final.py`：决策痕迹含 `critic_issues`（截断到既有 `_PREVIEW_CHARS` 量级）、
  `revise_outcome`、`revise_revert_reason`；默认值分别为 `[]` / `"skipped"` / `""`。
- `tests/test_eval_component.py`：summary 增 `critic_fail_rate` 与
  `critic_agree_with_judge`（含 `precision` / `recall` / `n`），无归档时优雅缺省。

**实现**：

- `nodes.py:808-817` 附近补三个 trace 字段。
- `eval/runner/component_metrics.py` 增评审一致性指标；`eval/runner/report.py` 同步落到人读报告；
  聚合函数与 Task 0 的 `tools/critic_audit.py` **共用同一实现**（避免两套口径分叉）。

---

### Task 7：文档同步

| 文档 | 改什么 |
|---|---|
| `docs/spec/2026-08-10-coze-agent-deepening-design.md` | D-02 改「修订后须过验收闸」；D-10 补「意见必须给出处 + 按意图分流 + 格式不判失败」；§5「评审输出」JSON 换 CD-3 schema；§6 增 advisory 为 D-14 的显式形态 |
| `docs/plan/2026-09-14-fix-concept-intent-and-optimization-loop-plan.md` | §1 的 D5 行标「被本文取代」、D6 行标「收编进本文 CD-4」；Task 5 / Task 8 标「不再单独执行」 |
| `docs/spec/2026-08-10-coze-agent-interface.md` | 决策痕迹字段表增 `critic_issues` / `revise_outcome` / `revise_revert_reason` |
| `docs/dev-eval-guide.md` | 增「评审与 Judge 一致性指标怎么看」一节（含 `tools/critic_audit.py` 用法） |
| `AGENT.md` | 登记本 spec / plan 与后续 devlog / review |

---

### Task 8：端到端取证（**须重发 agent 后**）

扩 `tools/probe_concept_and_optimization.py` 的报告字段，或在 `--out` 产物里确认：

1. 概念题（`algorithm_tags` + `run_mode` 的迪杰斯特拉用例）：`critic_passed` 不再为 `false`，
   或即便为 `false` 也不采纳修订（`revise_outcome="reverted"`）；
2. 任一触发修订的用例：`revise_outcome` 与 `revise_revert_reason` 出现在痕迹里；
3. `kind:"options"` 的编辑块在修订后**字节一致**（G2 的可观测形式）。

未重发则本 Task SKIP，并在 devlog 里注明「**线上未验证**」（与既有两份计划同一口径）。

---

## 2. 验收标准

对齐设计 §4 的 8 条，其中端到端可验的是：

1. 低相似度 / 丢块 / 引入幻觉引用的修订稿**均被回退**，痕迹可见（G1–G3）。
2. 只有带出处的意见能触发修订；无出处意见 ⇒ 判通过。
3. 概念题含示意性 `java` 代码块不再因格式判失败（对应 `q17`）。
4. `blocking` 意见可豁免相似度闸（确需大改的通道未被堵死）。
5. `advisory` 开关下修订次数为 0，评审结论仍入痕迹。
6. `tools/critic_audit.py` 输出的交叉表与设计 §1.2 逐格一致。
7. `431 passed` 基线不回归；计划 A 的 Bug C/D 用例不受影响。

---

## 3. 验证命令与门槛

```bash
# coze（基线 431 passed，2026-09-14 实测）
cd javatutor-coze && uv run pytest tests/ -q

# 离线指标（只读归档，不消耗额度）
uv run python tools/critic_audit.py eval/archive
```

**评估门槛**：本改动触及评审-修订路径 ⇒ 重发后须补一轮端到端评估，判据沿用既有门槛
（Judge 均分下降 ≤ 0.3 且 Grounding 下降 ≤ 0.5），并**附加**本设计的自证指标：
修订回退率与 `critic_agree_with_judge` 必须有数（这正是 CD-6 的目的）。

---

## 4. 风险与回滚

见设计 §6。执行侧需要额外的两点注意：

| 注意 | 说明 |
|---|---|
| Task 1 会改变 `revised` 的语义 | 4 个既有用例须同步改（§1 Task 1 表），否则会被误判为回归；改前先在 review 里确认这是**有意的语义收窄** |
| Task 4 的 G4 增加 1 次 LLM 调用 | 仅触发修订的请求（实测 21.8%）；`critic_recheck=false` 可关，关后仍有 G1–G3 |

**回滚单位**：Task 1 / 2 / 3 / 4 / 5 各自独立；CD-5 的配置开关是**一行止损**
（线上出问题时把 `critic_mode` 改成 `advisory` 即回到「不修订」）。

---

## 5. 执行顺序建议

```
Task 0（审计工具，可与其余并行）
Task 1（回滚闸 G1/G2）              # 最高价值：先让修订不可能变差
Task 2（意见必须给出处）             # 减少触发源
Task 3（评审表分流 + 正面回答条）    # 减少误杀 + 让它有能力拦答非所问
Task 4（G3/G4）                     # 补齐剩余两道闸
Task 5（advisory 开关）             # 止损面
Task 6（痕迹 + 指标）               # 让效果可度量
Task 7（文档）
Task 8（端到端取证，须重发）
```
