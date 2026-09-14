# 2026-09-14 评审-修订子系统优化 — 实施记录

> 设计：`docs/spec/2026-09-14-critic-revise-optimization-design.md`（CD-1 … CD-6）
> 计划：`docs/plan/2026-09-14-critic-revise-optimization-plan.md`（Task 0–8）
> 契约同步：`docs/agent-collaboration-guide.md`（`【决策痕迹】` 段）、`docs/spec/2026-08-10-coze-agent-interface.md`（痕迹 schema）、
> `docs/spec/2026-08-10-coze-agent-deepening-design.md`（D-02 / D-10 / D-14 / §5 / §6）、`docs/dev-eval-guide.md`（评审与 Judge 一致性）

**跨仓**：仅 coze `javatutor-coze`，**无前端改动**。后端未改动。

交付范围：Task 0–7（离线全绿）。**Task 8（端到端取证）须先重发 agent，本件不做——线上未验证。**

## 1. 做了什么

四轮归档里评审拦下 33 条，其中 **11 条 Judge 判 `correct`（误杀 33%）**，而修订是**不可回滚**的
整段重写——于是「评审很鸡肋，总把较正确的答案改得答非所问」在机制上成立：一次误判 = 一次不可撤销的重写。
本件从两侧收口：

1. **让修订不可能把答案改差**：新增四道验收闸（G1 相似度 / G2 结构块保全 / G3 引用不劣化 / G4 二次评审），
   任一不过即回退原答（最坏等于「没改」）。
2. **让评审少误杀、又能拦真错**：意见必须给出处（给不出机械丢弃）；引用类规则改为**仅在该类引用出现时才核对**
   （概念题没有步骤可引，旧表把它当漏引）；格式检查降为轻微问题；补唯一重要的一条「是否正面回答了学生问题」。
3. **让损失面可控**：`critic_mode` 一行配置即可切到 `advisory`（评审照跑照记痕迹但不触发修订）。
4. **让效果可度量**：痕迹暴露 `critic_issues` / `revise_outcome` / `revise_revert_reason`；
   `summary.json` 增 `critic_fail_rate` 与 `critic_agree_with_judge`。

## 2. 决策与落点

| # | 落点 | 说明 |
|---|---|---|
| 1 | `_accepted`（新增，critic.py） | G1+G2 的纯函数验收闸，返回 `(是否采纳, 原因)` |
| 2 | `_critique`（新增） | 首评与 G4 二次评审**共用**一次评审调用，避免两处提示词漂移 |
| 3 | `_grounding_violations`（新增） | G3：调 `verification.verify_grounding` 比较修订前后违规数，**不改 verify_node 任何语义** |
| 4 | `_validate_issues`（新增） | CD-3 quote-or-drop：`answer_span` 须为回答子串、`fact` 须为事实块子串 |
| 5 | `_config_path` / `_runtime_flag`（新增） | 读 `config/agent_llm_config.json`，**读失败/键缺失/类型不符一律回落默认** |
| 6 | `critic_node` | 判失败 = 模型 `pass=false` **且**留下至少一条有效意见；无有效意见 ⇒ 判通过（fail-open） |
| 7 | `build_facts_block` 增「问题类型」行 | concept ⇒「概念讲解（本题没有可引的执行步骤证据）」；`intent` 缺失 ⇒ 不加行 |
| 8 | `build_final` 增三键 | `critic_issues`（截 300 字）/ `revise_outcome` / `revise_revert_reason` |
| 9 | `eval/runner/critic_agreement.py`（新建） | 评审×Judge 交叉表**单一实现**，CLI 与 summary 共用 |
| 10 | `tools/critic_audit.py`（新建） | 离线复跑设计 §1.2 交叉表，只读归档、零额度消耗 |

## 3. 改动清单

### 3.1 coze

| 文件 | 改动 |
|---|---|
| `src/graphs/javatutor/critic.py` | 新增 `_config_path` / `_runtime_flag` / `_critique` / `_grounding_violations` / `_validate_issues` / `_parse_issues` / `_has_blocking` / `_similarity` / `_accepted`；`critic_node` / `revise_node` 改写为过闸版本；`revise_node` 四条返回路径全部带 `revise_outcome` |
| `src/graphs/javatutor/prompts.py` | `SYSTEM_PROMPT_CRITIC` 整体改写（出处硬要求 / 引用条件化 / 正面回答 / 第二步否决权 / 格式降级 + 无 `step_facts` 代码块豁免）；`SYSTEM_PROMPT_REVISE` 改最小编辑；顺带修掉「核查五类引用」却列 6 条的措辞 |
| `src/graphs/javatutor/prompting/contexts.py` | `build_facts_block` 增「问题类型」行 + `_INTENT_LABELS` |
| `src/graphs/javatutor/nodes.py` | 新增 `_critic_issues`；`build_final` 的 trace 增三键 |
| `src/graphs/javatutor/state.py` | 新增 `revise_outcome` / `revise_revert_reason` / `revise_recheck_passed`；`revised` docstring 收窄为「被采纳」 |
| `config/agent_llm_config.json` | `config` 段增 `critic_mode: "enforce"`、`critic_recheck: true` |
| `eval/runner/critic_agreement.py`（新建） | `load_judged` / `aggregate_critic_agreement` / `format_audit_table` |
| `tools/critic_audit.py`（新建） | argparse CLI（`paths` / `--json`） |
| `eval/runner/component_metrics.py` | 新增 `critic_agreement_metrics`（复用上表聚合） |
| `eval/runner/report.py` | `summarize` 并入评审一致性指标；`_E2E_METRIC_ORDER` 增 `critic_fail_rate`；报告增「评审 × Judge 一致性」节 |
| `tests/test_critic.py` | +26（G1/G2/G3/G4 各道闸、quote-or-drop 四种形状、advisory、配置回落、提示词断言、结构化块元组守漂移） |
| `tests/test_contexts.py` | +3（问题类型行：concept / data_query / 缺失不加行） |
| `tests/test_build_final.py` | +5（三键缺省、有效意见、截断、回退原因、坏 JSON 容错；含**端到端产物**断言） |
| `tests/test_eval_component.py` | +3（空样本同形状、四格交叉表、summary 接线） |
| `tests/test_graph.py` / `tests/test_harness_loop.py` | 既有评审失败用例改为「带出处的对象意见」 |

### 3.2 文档

| 文件 | 改动 |
|---|---|
| `docs/spec/2026-08-10-coze-agent-deepening-design.md` | D-02 改「修订后须过验收闸」；D-10 补「意见必须给出处 + 按意图分流 + 格式不判失败」；D-14 增 advisory 显式形态；§5 评审输出换 CD-3 schema；§6 增回退与 advisory 两行 |
| `docs/spec/2026-08-10-coze-agent-interface.md` | 决策痕迹 schema 与字段表增 `critic_issues` / `revise_outcome` / `revise_revert_reason`，并把 `revised` 的语义收窄写明 |
| `docs/agent-collaboration-guide.md` | 输入输出段增「评审三键」+ `revised` 语义收窄说明 |
| `docs/dev-eval-guide.md` | 新增「评审与 Judge 的一致性怎么看」一节（两个口径的定义差异 + `tools/critic_audit.py` 用法 + 判读要点） |
| `docs/plan/2026-09-14-fix-concept-intent-and-optimization-loop-plan.md` | §1 D5/D6 标「已被本文取代 / 收编」；Task 5 / Task 8 标「不再单独执行」 |

## 4. 计划偏差与计划漏列

### 4.1 **CD-2 在两份计划里都没有对应 Task**（设计有、计划漏）

设计的 CD-2（`SYSTEM_PROMPT_REVISE` 从「自由重写」改为「最小编辑」）**没有任何 Task 承载它**，
而计划 §2 声称与设计的验收项对齐——这是计划的一处漏列。本次**按设计依据一并实现**
（落在 Task 3 的同一段提示词改动里），新增 `test_revise_prompt_is_a_minimal_edit` 钉住。

为什么必须补：只收回滚闸不改提示词，修订仍会按「自由重写」的口径产出大改稿，
然后在 G1 被判回退——结果是「修订必然回退」，闸门形同白跑一次 LLM 调用。

### 4.2 语义变更用例比计划列出的**多两个**

计划 §1 Task 1 表列了 4 个既有用例需要改（相似度过低会落进回退分支）。
实际执行时另有 2 个用例因 **CD-3** 而失效：

| 用例 | 原断言 | 改法 |
|---|---|---|
| `test_critic_fails_with_issues` | 断言字符串数组意见被判失败 | 改用带出处的对象意见（`_VALID_ISSUE`）——字符串意见在新口径下**必然被丢弃** |
| `test_critic_string_false_is_not_pass` | 同上（该用例的真实意图是测 `_as_bool("false")`） | 同上；给一条可核实意见，否则「无有效意见 ⇒ 通过」会盖掉它要测的东西 |

两个用例的**原意都保留**（`_as_bool` 的语义、评审失败路径），只是换了意见的载体。

### 4.3 其余实现选择

| 选择 | 理由 |
|---|---|
| `_runtime_flag` **每次调用都读盘**、不缓存 | 单次请求最多读 1–2 次小 JSON；换来的是测试能 monkeypatch `_config_path` 真跑读盘分支（缓存就测不到回落逻辑） |
| `revise_recheck_passed` **只在二次评审真的跑过时出现** | 「没跑」与「跑过但没过」必须分得开，否则消费方会把 `false` 当「答案有问题」 |
| `critic_issues` 从 `critic_feedback` 反序列化，不新增 state 键 | 保持「评审结论只有一个存放处」，避免两份数据分叉 |
| `_STRUCTURED_MARKERS` 在 critic.py 保留本地副本 | 不把整个 nodes 模块拖进评审模块；用 `test_structured_markers_match_nodes` 钉逐字相等 |
| 一致性指标算在 `component_metrics.py`，却并入 **`e2e`** | 输入是端到端判分记录（`judged`），放 `e2e` 才是它描述的对象；`component` 段现有 `critic_recall` 是样本文件口径，同名易混 |
| `critic_recheck` 默认 **true** | G1–G3 只管「是不是还是原来的回答」，管不了「改完还是错的」；代价是触发修订的请求多 1 次 LLM 调用（实测触发率 21.8%） |
| **`PROMPT_VERSION` 未递增** | 遵循仓库既有实践（详见 `docs/devlog/2026-09-14-fix-fetch-context-and-duplicate-answer.md` §7.5，结论未变）；本次同样改了 `prompts.py` / `contexts.py`，同样不递增 |

## 5. 门槛与验证结果

| 门槛 | 结果 |
|---|---|
| coze `uv run pytest tests/ -q` | **484 passed**（基线 431） |
| `uv run python tools/critic_audit.py eval/archive` | 与设计 §1.2 **逐格一致**：n=124 / 拦 33 / 修订 27；precision 22/33 = 66.7%；recall 10/22 = 45.5%；tp=22 fp=11 fn=12；按意图 `debug 14(5) / data_query 13(3) / other 5(2) / concept 1(1)` |
| 前端 `npx vitest run` | 445 passed / 33 files（本件无前端改动） |
| 前端 `npm run build` | ok |
| L5 外壳回归（两条命令） | **均无输出**（`.coze` / `scripts/` / `src/main.py` / `src/storage/` / `src/utils/` 未动） |
| L4 本地 HTTP 冒烟 | SKIP（同前几轮） |

**端到端产物取证**（红线纪律）：`critic_issues` 是新进用户可见产物的字段，
故断言不止于 `decision_trace` 字典，而是同时钉住 `build_final` 的 `answer` 文本里确实出现
`"critic_issues"` 与该条意见的 `claim`（`test_trace_exposes_validated_critic_issues`）。

## 6. 线上未验证（明确）

- **Task 8 （端到端取证）未做**：须先重发 coze agent 才生效。**线上未验证。**
- 重发后须按计划 §3 补一轮评估，并**附加**本设计的自证指标：修订回退率与
  `critic_agree_with_judge` 必须有数（这正是 CD-6 的目的）——离线门槛只是必要条件。
- 本组对话不发布、不跑远程评估（每次真实运行消耗 Coze 侧额度）。
- 待观察的预期变化：`critic_fail_rate` 应下降（减少误杀），`precision` 应上升（拦下的更可能真有问题）；
  若 `revise_rate` 随之下降而 `avg_score` 不降，即「少改但没改差」，符合设计意图。
