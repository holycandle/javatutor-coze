# 开发日志：Agent Harness 工程——图内真环 + 治理门闩 + HITL 内核（2026-09-11）

> 依据：`docs/spec/2026-09-11-agent-harness-react-loop-design.md`、
> `docs/plan/2026-09-11-agent-harness-react-loop-plan.md`。
> 一句话：把主 Agent 节点内部的 `while` 工具循环**契约化**成图上的真环，把治理从提示词变成可测的门闩，
> 把 grounding 核对器从离线评估接进运行时，并为 HITL 建好可离线证明的内核。

## 改动清单

**新增（业务）**

| 文件 | 内容 |
|---|---|
| `src/graphs/javatutor/verification.py` | 确定性 grounding 核对器（自 `eval/runner/grounding.py` 原样上提，口径不变） |
| `src/graphs/javatutor/harness/contracts.py` | `Action` / `GuardDecision` / `Observation` / `ParseError` + `parse_action` / `render_observation` / `action_from_state` |
| `src/graphs/javatutor/harness/render.py` | `_format_step_facts` / `_handle_fetch`（自 `main_agent.py` 原样迁出） |
| `src/graphs/javatutor/harness/registry.py` | 工具注册表（引用各工具 `TOOL_SCHEMA`）+ `validate_args`（未知键 / 类型名） |
| `src/graphs/javatutor/harness/guard.py` | `decide(action, state) -> GuardDecision` 纯函数 + `MAX_ROUNDS` + `round_marker` |
| `src/graphs/javatutor/harness/hitl.py` | `hitl_enabled()`（默认关）+ `hitl_brief()` |
| `src/graphs/javatutor/harness/propose.py` | 提案节点：累积消息序列、终答 / 提案分流、收束轮 |
| `src/graphs/javatutor/harness/tools_node.py` | 执行节点：自动前置 fetch、观察双形态、`step_memories` / `served_step_indices` |
| `src/graphs/javatutor/harness/guard_node.py` | 门闩节点：轮次记账、放行 / 拒绝、唯一暂停点 `interrupt()` |

**修改（业务）**

| 文件 | 内容 |
|---|---|
| `src/graphs/javatutor/graph.py` | 节点 11 → 14（`guard`/`run_tools`/`verify`），新增 2 条条件边 + 环 |
| `src/graphs/javatutor/main_agent.py` | 循环体移出，保留 `main_agent_node`（薄包装）与既有导入名 |
| `src/graphs/javatutor/nodes.py` | 新增 `verify_node` + `_strip_structured_blocks`；`decision_trace.verification` |
| `src/graphs/javatutor/state.py` | 新增 7 个字段（`agent_messages` / `proposed_action` / `guard_decision` / `step_records` / `served_step_indices` / `fetched_injected` / `verification`） |
| `src/tools/fetch_execution_context.py` | 抽出 `match_file_key`（门闩 P4 与工具共用一份匹配口径） |
| `eval/runner/grounding.py` | 改为 re-export（保持既有导入路径） |
| `tests/test_main_agent.py` | 12 → 1（只留纯渲染器用例），循环行为用例迁移到图级 |
| `docs/agent-collaboration-guide.md` | 流程图、节点表、信息分层、state 字段、"agent 怎么用工具" |
| `AGENT.md` | 登记 spec / plan / 本 devlog |

**新增（测试）**：`tests/test_harness_contracts.py`(10)、`test_harness_registry.py`(9)、
`test_harness_guard.py`(15)、`test_verify_node.py`(10)、`test_harness_loop.py`(36)、
`test_harness_hitl.py`(7)、`test_harness_termination.py`(4)。

## D1–D9 落地对照

| # | 决策 | 落地 |
|---|---|---|
| D1 | 只交付 spec + plan | spec/plan 已定稿并由本组执行（执行与设计分离，符合 AGENT.md 分工） |
| D2 | HITL 只建内核 + 离线证明 | `harness/hitl.py` + `tests/test_harness_hitl.py`（`MemorySaver` + `Command(resume=...)`），零跨仓改动 |
| D3 | 契约 + 门闩 + 观察结构化 + 收束轮 + 累积消息；不换 `bind_tools`，不做动态预算 | 全部落地；工具协议仍是文本 JSON，`llm_complete` 调用路径不变 |
| D4 | 验证门闩只记录、拒绝结束不做 | `verify_node` 写 `verification`，**不参与路由**；`verify → save_session` 无条件 |
| D5 | 循环落点 = 图内真环 | `main_agent` → `guard` → `run_tools` → `main_agent`（条件边 + 回边），节点内无 `while` |
| D6 | `interrupt()` + 离线 `Command(resume=...)` | `test_harness_hitl.py::test_hitl_pauses_on_ambiguous_file_and_resumes` 通过 |
| D7 | grounding 上提 + re-export，`tests/test_grounding.py` 不改 | `tests/test_grounding.py` 9 passed，未改一字 |
| D8 | 交付到离线全绿 | L1–L5 见下；e2e + Judge 对比留给合入窗口（Task 15） |
| D9 | 文本 JSON 工具协议 | `parse_action` 解析 `{"tool":..., "args":...}`，协议未变 |

## 与计划的偏差（4 处，均有理由）

1. **`tool_rounds` 的口径**：计划 Task 11 表写「直接作答 `tool_rounds == 1`」，本次实现为 **0**。
   依据 spec §4.3「轮次由门闩记账」——只有进入 `guard` 才 `+1`。计划的 1 是旧循环的「迭代次数」语义，
   与 §4.3 的终止性算术（`guard ≤ 3`、`run_tools ≤ 3`）不能同时成立，取 §4.3。
   `test_graph_direct_answer_costs_no_round` 锁住这一点。

2. **P3 用「进入前」的计数判定**：计划 Task 6c 写 `decide(action, {**state, "tool_rounds": rounds})`（自增后）。
   按字面实现会让**第 3 次**进入就命中 `rounds >= MAX_ROUNDS` → `run_tools` 只剩 2 次，
   比历史循环 `while rounds < MAX_ROUNDS`（3 次工具真的执行）少一轮，且 P3 变成正常路径可达。
   本次改为 `decide(action, state)`：第 1/2/3 次进入一律放行（3 轮工具给满），
   P3 只拦正常路径不可达的第 4 次——与 P3 自己的注释（「正常路径不可达，仅作结构兜底」）一致。
   锁定测试：`test_guard_grants_the_last_budgeted_round`、
   `test_harness_termination.py::test_pathological_model_terminates_within_budget`（断言恰好 3 次 `step_facts` 成功执行）。

3. **一次执行的多个观察合并成一条 `HumanMessage`**：计划/spec §4.8 的示例是「一条观察一条消息」。
   但「自动前置 fetch + step_facts」是常态，会稳定产出两条**连续 Human**。改为合并，
   `agent_messages` 保持严格角色交替（System→Human→AI→Human→AI…），对聊天 API 更稳、消息数更少。
   锁定测试：`test_run_tools_merges_observations_into_one_message`、`test_graph_agent_messages_alternate_roles`。

4. **fetch 失败落进 state**（把工具返回的 `fetch_context_failed` / `fetch_context_error` 补回 state）：
   `_handle_fetch` 的失败分支原先只返回渲染文本，键被丢掉。这条**动到了 spec §5.2 的回归红线**，
   已按 review P1-1 补记进 spec §5.1（详见下节「Review 后修复」）。

## Review 后修复（2026-09-11，`docs/reviews/2026-09-11-agent-harness-react-loop-review.md`）

审查结论为 1 P1 / 1 P2 / 3 P3，全部已处理：

**P1-1（红线偏离）→ 采纳 (a)：保留新行为 + 改 spec。** 核对确认 spec §5.2 那条红线描述的是
一条**改造前不可达**的路径——HEAD 的 `_handle_fetch` 失败分支只返回渲染文本、不写任何 state 键，
所以 `critic_node` 的 `fetch_context_failed and not has_steps` 短路自 2026-08-30 工具化以来从未触发。
本次补上失败态写入后该路径**首次真正生效**，语义正确（没拿到证据就不必让 LLM 评审）。
已把该条从 §5.2 移到 §5.1 并注明「执行后补记」；`critic_skipped` 的上升列为 Task 15 的**预期**指标变化。

**P2-1（HITL 末轮丢用户选择）→ 采纳 (a)：`P4-resolved`。** 旧实现在最后一轮预算触发 P4 时，
`resume` 回去正好撞上 `propose` 的收束模式（`rounds >= MAX_ROUNDS` 永不产出 Action），
用户的选择被静默丢弃。现改为门闩用用户选的文件名**补全原提案的 `file`** 后放行到 `run_tools`
（原提案的工具与其它参数本来就合法，唯一不可判定的就是 `file`）；
`_route_after_guard` 简化为「`verdict == allow` → tools」。
新增边界用例 `test_harness_hitl.py::test_hitl_resolves_ambiguity_on_the_last_budgeted_round`
（第 3 轮触发 P4 → resume → 断言用户选的文件名真的进了 `tool_calls`）。
P4-resolved 只写 `step_records` 不写 `agent_messages`——证据由 `run_tools` 的观察给出，
这里再追加一条会和紧随其后的执行观察连成两条同角色 HumanMessage。

**P3-1**：删掉 `registry.TOOLS[*]["fn"]`（死数据，会让人误以为派发走注册表）；
`tools_node` 用 `_DISPATCHED` 与 `TOOLS` 的键做 **import 期同源断言**，漂移变成启动即炸，
而不只是线上的 `P0-unknown-dispatch` 观察。

**P3-2**：本 devlog 原先的「264 collected = 253 passed + 11 失败，全绿」是错记（数字对不上且自相矛盾）。
已换成可复现的三元组（命令 + 提交 + 结果），见上表「L2 基线」。实测基线为 **231**。

**P3-3**：`guard_node` 的 `action is None` 分支补齐观察 + 清空提案，与其它 deny 分支对齐
（policy 标成 `P0-no-action`，与 `P0-unknown-dispatch` 同前缀约定）。今天路由保证走不到，但不该是唯一一条「拒绝了却不让模型知道」的路径。

**P3-4**：`propose.py` 的三元表达式加括号；`nodes.py::_strip_structured_blocks` 的 docstring 点明
「正文出现块标记会连带截断」这一取舍；`_route_after_propose` 的路由判据从**持久化**的 `answer`
改为**本轮刚写入**的 `proposed_action`（消除将来挂 checkpointer 后旧 `answer` 重入环的隐患）。

## 验证结果

| 门槛 | 命令 | 结果 |
|---|---|---|
| L1 依赖锁 | `uv sync --frozen` | 通过（Checked 135 packages，无变更） |
| L2 全量单测 | `uv run pytest tests/ -q` | **311 passed, 0 failed** |
| L2 基线（改动前） | `git grep -c "def test_" HEAD -- tests/` 求和 = 230 个测试函数（其中 `test_main_agent.py` 12），加 `test_optimization_guidance.py` 的 1 组二参数化 → **231 collected**（`e4185c0`） | 净增 **80**（7 个新文件 91 条 − `test_main_agent.py` 11 条） |
| L2.5 组件评估 | `uv run pytest tests/test_eval_component.py -v` | 1 passed（内部断言 `pass_rate == 1.0`） |
| L3 离线构建 | `PYTHONPATH=src uv run python -c "from agents.agent import build_agent; g = build_agent().builder.compile(); print('ok')"` | `ok`（本地无 PG，按既有约定降级 `MemorySaver`） |
| L4 本地 HTTP 冒烟 | `scripts/http_run.sh -p 5000` + curl | **SKIP**（原因见下） |
| L5 外壳回归 | `git status --short` + 外壳路径 grep | 通过：`.coze` / `scripts/` / `src/main.py` / `src/storage/` / `src/utils/` 零 diff、零新增 |
| 定向：grounding 口径 | `uv run pytest tests/test_grounding.py -q` | 9 passed（未改一字） |
| 定向：终止性 | `uv run pytest tests/test_harness_termination.py -v` | 4 passed |
| 定向：HITL | `uv run pytest tests/test_harness_hitl.py -v` | 7 passed |

**L4 为什么 SKIP**：`src/main.py` 的 `lifespan` 固定 `graph_helper.get_graph_instance("graphs.graph")`，
而本工作副本里**不存在** `src/graphs/graph.py`（该模块是部署/打包侧产物，本地开发副本没有），
`curl /health` 直接 `ModuleNotFoundError: No module named 'graphs.graph'`、uvicorn 启动失败；
叠加 Windows 上 `Psycopg cannot use the 'ProactorEventLoop'`，本地 PG checkpointer 也起不来。
按 `docs/local-dev-convention.md` §5，未配置环境时 L4 可标记 SKIP，此处如实记录。

**L4 的等价替代（已执行）**：用真实入口 `agents.agent.build_agent()`（即平台 `lifespan` 调的同一个入口）
编译后直接跑一次完整问答，绕过 HTTP 外壳：

1. **真实模型路径**：模型端点在本环境不可达，`answer` 为 `LLM_UNAVAILABLE_ANSWER`，
   但图**完整跑通**：`intent=data_query` → `main_agent`（终答）→ `critic`（异常降级 `critic_skipped=true`）
   → `revise` → `verify` → `save_session` → `final`；`【决策痕迹】` 在，
   `decision_trace.verification` = `{applicable: true, checked: 0, violations: 0, grounding_ok: true}`。
2. **脚本模型路径**（`configurable.chat_model`，唯一注入点）：`tool_rounds=1`、`main_agent` 访问 2 次、
   `tool_calls = [fetch_execution_context(auto), step_facts]`、
   `step_records = [(fetch, ok, P0-auto-fetch), (step_facts, ok, P0)]`、
   `verification = {applicable: true, checked: 1, violations: 0, grounding_ok: true}`、
   `agent_messages = [System, Human, AI, Human, AI]`（严格交替）、
   `fetched_context.run_id == harness-smoke-3`、`answer` 首行是教学回答。

## 已知局限 / 注意事项

- **HITL 线上默认关是刻意的**：内核已离线证明，但线上没有 checkpointer 与 `/resume`
  （需改 `src/main.py`，属外壳，见 spec §6）。**在清单落地前不要在生产设置 `COZE_AGENT_HITL`**。
- **`recursion_limit` 的实际值比预想宽松**：plan 的「余量只有 4」是按 LangGraph 默认 25 算的；
  实测外壳（`coze_coding_utils/openai/handler.py` 与 `src/main.py` 的异步路径）**显式设成 100**。
  两者取严格者，`test_harness_termination.py` 仍按默认 25 断言（最坏路径 21），因此
  「新增节点/轮次必须重算预算」这条约束继续有效，但当前余量是 79 而非 4。
- **前端未确认 `decision_trace.verification` 的消费**：本次是**纯增量**键（既有键一个不动），
  按接口契约是加字段不破坏旧消费方；前端是否需要展示由后续决定。
- **`step_records` 未进 `decision_trace`**：本轮只落在 state / 返回结构里（体积考虑）。
  若评测或 B 端需要，按 spec §7 的口径再决定是否入痕。
- **每轮 `agent_messages` 累积**：4 轮上限内线性增长可接受；若未来上调 `MAX_ROUNDS` 需重新评估体量。
- **`verification` 不参与路由**（D4 刻意）：先收集一轮线上数据，再决定是否升级为判罚门闩。

## 评估对比（合入窗口执行，Task 15）

**待执行**：重新发布 agent → 跑本轮 Judge → 与上一轮均分对比 → 归档到本节。
门槛（`local-dev-convention.md` §5）：均分下降 > 0.3 或 Grounding 下降 > 0.5 **禁止合入**。
重点指标：`tool_calls` 准确率、fetch 调用率、`grounding_verify_*`（本次新接入运行时，应与离线口径一致）、
`critic_skipped` 占比。另需抽查线上真实提问 3 例（单文件 / 多文件 / 带编译错误），
确认 `【决策痕迹】` 与 `【编辑建议】` 块未被本次改造破坏。

**预期变化（不是异常）**：`critic_skipped` 会**上升**——「显式 fetch 失败 + 入站无 steps」这条路径
本次起才真正能触发 `critic` 的降级短路（P1-1，见 spec §5.1 的补记）。该路径命中率取决于
线上 `fetch_execution_context` 的失败率，与循环改造无关；对比时把它的**基线**当作上表读，不要当回归。
