# 2026-09-11 Agent Harness 工程执行 Review

> 审查对象：javatutor-coze `feat/harness-react-loop`（未提交工作区，基于 `e4185c0`）
> 对应设计：`docs/spec/2026-09-11-agent-harness-react-loop-design.md`
> 对应计划：`docs/plan/2026-09-11-agent-harness-react-loop-plan.md`
> 实现记录：`docs/devlog/2026-09-11-agent-harness-react-loop.md`

## 结论

主体落地度高：图内真环（`main_agent` → `guard` → `run_tools` → `main_agent`）、统一动作契约、治理门闩 P0–P5、
收束轮、HITL 内核、grounding 接进运行时、测试迁移（12 → 1，行为一条不减下行）均已到位，L1–L5 门槛全部复现通过。

发现 **1 个 P1 / 1 个 P2 / 3 个 P3**。P1 是 spec §5.2 明列红线的偏离，需先决策（保留并改 spec，或回退）再合入；
P2 是 HITL 内核在「预算最后一轮」的边界缺陷（当前默认关，线上无影响，但 §6 落地即会踩到）；其余不阻塞。

## Findings

### P1-1：`fetch_context_failed` 的写入侧变更偏离 spec §5.2 明列红线，并移动 `critic_skipped` 这个评测可见指标

**位置**：`src/graphs/javatutor/harness/render.py:60-72` ↔ `src/graphs/javatutor/critic.py:73`；
红线出处 `docs/spec/2026-09-11-agent-harness-react-loop-design.md:264`。

证据链：

1. spec §5.2「必须不变的行为（回归红线）」第 4 条：**「降级路径：`fetch_context_failed` + 无 steps → `critic_skipped` 不变」**。
2. HEAD 版 `main_agent.py::_handle_fetch` 的失败分支**只返回渲染文本**，不写任何 state 键；
   因此在这条路径上 `fetch_context_failed` 始终为 falsy，`critic_node:73` 的降级分支**不会**因主 Agent 的显式 fetch 失败而触发。
3. 本次 `render.py` 失败分支改为写入 `fetch_context_failed=True` / `fetch_context_latency_ms` / `fetch_context_error`。
4. 结果：当「模型显式 fetch 失败」且「入站 payload 无 steps」时（`has_steps` 由 `nodes.py:140` 依 `len(steps) > 0` 写入），
   critic 由「跑一轮 LLM 评审」变为「跳过评审（`critic_skipped=True`）」。

devlog 的偏差 #4 只说明了「把丢掉的键补上」，**没有说明它会改变 critic 的触发条件**，也没提这是一条红线的偏离。
`critic_skipped` 是评测在看的指标（devlog 自己在「评估对比」一节列为重点指标），而合入门槛是「与上一轮均分对比」——
这是一个会移动该指标的变更，spec 未登记。

**建议（二选一，作者定）**：

- **(a) 保留新行为 + 改 spec（倾向此项）**：语义上「没有证据时不必让 LLM 评审」更正确。
  把该条从 §5.2 移到 §5.1「必须改变的行为」，并在 Task 15 的 e2e 对比里写明预期 `critic_skipped` 上升。
  注意 AGENT.md 要求「设计变更先更新 spec，再更新 plan，最后执行」，本次属执行后补记，spec 里应注明。
- **(b) 回退**：失败分支只返回渲染文本（保持 HEAD 语义），把「补键」拆成显式登记的独立变更。

### P2-1：HITL 在「预算最后一轮」恢复时，用户的选择被静默丢弃

**位置**：`src/graphs/javatutor/harness/guard_node.py:69-87` + `harness/propose.py:90-106` + `graph.py:51-60`。

证据链（逐步）：

1. `guard_node` 进入即 `rounds = tool_rounds + 1`（`:54`），无论是否 `interrupt`。
2. 第 3 次进入时 P4 命中 → `interrupt(...)`；用户 `resume` 后该节点重新执行完，返回 `tool_rounds=3`、
   `guard_decision = allow/P4-resumed`。
3. `_route_after_guard` 对 `P4-resumed` 明确路由回 `propose`（`graph.py:58`），其注释为「让模型用用户选的名字重提」。
4. `propose` 中 `converging = rounds >= MAX_ROUNDS` → `3 >= 3` 为真 → **收束模式**，永不产出 Action。
5. 于是回灌观察里那句「用户选择了 X。请用该文件名重新调用 `fetch_execution_context` 读取」
   指向一个模型在结构上无法完成的动作——用户的选择被丢弃。

**为什么现有测试没抓到**：`tests/test_harness_hitl.py::test_hitl_pauses_on_ambiguous_file_and_resumes` 只在**第 1 轮**触发歧义
（resume 后 `tool_rounds=1`，远未收束）；`test_guard_hitl_on_interrupts_and_never_executes_the_wrong_proposal` 直接调 `guard_node`，
看不到后续 `propose` 的收束判定。**第 1/2 轮正常，只有第 3 轮坏**。

**严重度**：`COZE_AGENT_HITL` 未设即关，当前线上无影响；但它是本轮交付物 HITL 内核的一部分，
spec §6 落地（挂 checkpointer + `/resume`）后即会踩到。

**建议（二选一）**：

- **(a) 推荐**：`P4-resumed` 不再回 `propose`，而由门闩**用用户给的文件名补全原提案**并放行到 `run_tools`
  （新增 `policy="P4-resolved"`，`_route_after_guard` 按 allow 处理）。
  理由：模型提的工具与参数都合法，唯一不可判定的就是 `file` 该取哪个文件；由人来补全这个值正是门闩的职责，
  不违反「模型决策 / 门闩治理 / 工具执行」三层——门闩没有替模型选工具，只是替人补齐了自己发起的问题的答案。
  终止性不受影响（轮次已计、工具执行一次、回 `propose`）。
- **(b)** 允许 resume 少记一轮（以 `MAX_ROUNDS + 1` 兜底）。缺点：破坏「guard 进入次数 ≤ 3」的终止性上界，
  且人可以反复触发 interrupt/resume ping-pong，需额外加护栏。

无论选哪种，都应补一条边界用例：**在第 3 轮触发 P4 → `resume` → 断言用户选择真的被用上（`tool_calls` 里出现该文件名）**。

### P3-1：`registry.TOOLS[*]["fn"]` 是死数据，执行派发另有一份事实源

**位置**：`src/graphs/javatutor/harness/registry.py:14-17` ↔ `harness/tools_node.py:84-152`。

`TOOLS` 每个工具都带 `"fn"`，但全仓只有 `registry.py` 自身与 `tests/test_harness_registry.py:18-19` 引用它；
真正的派发是 `run_tools_node` 里硬编码的 `if tool == "step_facts" / elif tool == "fetch_execution_context" / else P0-unknown-dispatch`。
于是「有哪些工具」存在两份事实源：注册表（治理侧 P1 用它判白名单）与派发分支；`else` 分支只能把漂移变响，防不了漂移。

**建议**：删掉 `fn`；或（更好）让派发从注册表取 `entry["fn"]`，使 `else` 分支永不触发。

### P3-2：devlog 的「改动前基线」数字对不上且自相矛盾

**位置**：`docs/devlog/2026-09-11-agent-harness-react-loop.md:86`。

原文 `309 passed`（改动前基线 `264 collected = 253 passed + 11 失败，全绿`）有三处问题：

1. 「253 passed + 11 失败」与「全绿」自相矛盾。
2. 数字对不上：本次新增 7 个测试文件共 **89** 条用例（10 / 8 / 15 / 10 / 36 / 6 / 4，已逐一实测），
   `test_main_agent.py` 由 12 条减为 1 条（-11），净增 **78** → 基线应为 **231**，不是 264。
   旁证：`git grep -c "def test_" HEAD -- tests/` 求和为 **230**（其中 `test_main_agent.py` 12 条），
   worktree 为 306 条（collected 309，差额来自 `test_graph_round_marker_tracks_next_propose` 的 3 参数化）。
3. 本机全量复跑为 **309 passed / 0 failed**，无法复现那「11 失败」。

**建议**：把基线改成「命令 + 提交 + 结果」的可复现三元组，或直接去掉该数字。

### P3-3：`guard_node` 的 `action is None` 分支违反本模块自己声明的不变量

**位置**：`src/graphs/javatutor/harness/guard_node.py:56-61`。

模块 docstring 声明「`deny` / `invalid_args` 写一条可读观察回灌给模型，
`tool_calls` 不新增」，但这条 deny 既不 `_append` 观察、也不清 `proposed_action`。
今天路由保证走不到（`propose` 要么给终答、要么给提案），但它是唯一一条「拒绝了却不让模型知道」的路径。

**建议**：与其它 deny 分支对齐（写观察 + 清提案），或显式断言不可达。

### P3-4：零散项

- `harness/propose.py:91` 的 `history + [HumanMessage(...)] if converging else history` 语义正确
  （`+` 优先级高于三元），但可读性差；建议加括号或拆行。
- `nodes.py::_strip_structured_blocks` 取「全文最早出现的标记」截断：若正文本身出现「【编辑建议】」四个字
  （例如在解释该功能），其后正文会一并被切出核对范围。方向保守（少核对而非误报），可接受；
  建议在 docstring 里点明这一取舍。
- `graph.py:46-48` 的 `_route_after_propose` 以**持久化**的 `state["answer"]` 作路由键。
  当前无 checkpointer 的线上路径安全（`answer` 只在环的终止分支写入）；但 spec §6 落地 checkpointer 后，
  同一 thread 若被复用会带着旧 `answer` 重入环。建议在落地 §6 时改为「本轮有 `proposed_action` 就去 guard」这类局部判据。

## 验证（独立复跑）

| 项 | 命令 | 结果 |
|---|---|---|
| L1 依赖锁 | `uv sync --frozen` | Checked 135 packages，无变更 |
| L2 全量单测 | `uv run pytest tests/ -q` | **309 passed**（与 devlog 一致） |
| L2.5 组件评估 | `uv run pytest tests/test_eval_component.py -v` | 1 passed（内部 `pass_rate == 1.0`） |
| L3 离线构建 | `PYTHONPATH=src uv run python -c "from agents.agent import build_agent; build_agent().builder.compile()"` | `ok`（降级 `MemorySaver`） |
| L5 外壳回归 | `git status --short -- .coze scripts src/main.py src/storage src/utils`；`-- pyproject.toml uv.lock` | **均空**：外壳零 diff、无新增依赖 |
| grounding 口径 | `uv run pytest tests/test_grounding.py -q`；`git status -- tests/test_grounding.py` | 9 passed；文件未改一字 |
| 终止性预算 | `tests/test_harness_termination.py` + 读 `coze_coding_utils/async_tasks/config.py` | 最坏路径 21；sync 端点用库默认 25（21 < 25 ✓），async 端点 `RECURSION_LIMIT` 默认 100 ✓ |
| L4 本地 HTTP 冒烟 | — | **认可 SKIP**：`ls src/graphs/` 确无 `graph.py`（只有 `__init__.py` / `javatutor` / `nodes`），`src/main.py` 的 lifespan 必然 `ModuleNotFoundError`；devlog 的等价替代证明（`build_agent()` 全链路跑通）可接受 |

同时复核通过、未成 finding 的点：

- **测试迁移一条不减**：HEAD `test_main_agent.py` 的 12 条（11 移 + 1 留）在 `test_harness_loop.py` / `test_main_agent.py` 中逐条对上。
- **4 处计划偏差理由成立**：尤其偏差 #2（P3 用「进入前」计数）确实与「3 轮工具真的执行」的既有基线一致，
  且有 `test_guard_grants_the_last_budgeted_round` 与终止性用例双重锁定。
- **prompt 未被改动**：`_main_system_prompt` 与 HEAD 逐字一致；`[当前轮次] N/3` 标记的变化在 spec §4.8（`:234`/`:239`）有据。
- **`agent-collaboration-guide.md` 已按规约同步**：流程图、节点表、信息分层、state 字段、「agent 怎么用工具」均已更新。
- 新增文件全部落在允许目录（`src/graphs/`、`src/tools/`、`tests/`、`docs/`），未越界。

## 遗留

- ~~P1-1 与 P2-1 需作者决策后处理；其中 P2-1 建议在 spec §6（外壳改造）落地前修完，否则 HITL 一开就是坏路径。~~
- devlog 的「评估对比（Task 15）」仍待执行：重新发布 agent → 跑本轮 Judge → 与上一轮均分对比（门槛：均分下降 > 0.3 或
  Grounding 下降 > 0.5 禁止合入）。P1-1 若选保留新行为，该对比需把 `critic_skipped` 上升列为**预期**而非异常。
- 前端对 `decision_trace.verification` 的消费未确认；按接口契约属加字段，不破坏既有消费方。

## 处理结果（2026-09-11，执行组）

5 个 finding 全部已处理，复跑 `uv run pytest tests/ -q` → **311 passed, 0 failed**（原 309 + 1 条 HITL 末轮边界用例
+ 1 条 registry 同源用例）。外壳与依赖仍零 diff。

| Finding | 处置 | 落点 |
|---|---|---|
| P1-1 | 采纳 (a)：保留新行为，把该条从 spec §5.2 移到 §5.1 并注明「执行后补记」 | `docs/spec/2026-09-11-…-design.md` §5.1/§5.2；devlog「评估对比」写明 `critic_skipped` 上升属预期 |
| P2-1 | 采纳 (a)：`policy="P4-resolved"`，门闩用用户选的文件名补全原提案后放行到 `run_tools`；`_route_after_guard` 简化为「verdict == allow → tools」 | `harness/guard_node.py`、`graph.py`；新增边界用例 `test_hitl_resolves_ambiguity_on_the_last_budgeted_round` |
| P3-1 | 删掉死字段 `fn`；`tools_node` 用 `_DISPATCHED` 与 `TOOLS` 键做 **import 期同源断言**（未采纳「派发从注册表取 fn」——两个工具的执行后处理各不相同，硬塞进注册表会把执行逻辑挪进治理层） | `harness/registry.py`、`harness/tools_node.py`、`tests/test_harness_registry.py` |
| P3-2 | devlog 基线换成可复现三元组；实测基线 **231**（230 个测试函数 + 1 组二参数化 @ `e4185c0`） | `docs/devlog/2026-09-11-…md` |
| P3-3 | `action is None` 分支补齐观察 + 清空提案，policy 标 `P0-no-action` | `harness/guard_node.py` |
| P3-4 | 三元表达式加括号；`_strip_structured_blocks` docstring 点明取舍；`_route_after_propose` 改判 **本轮刚写入**的 `proposed_action`（原用持久化的 `answer`） | `harness/propose.py`、`nodes.py`、`graph.py` |

P3-1 与 P3-4 第三项各采取了一条与建议不同的路径，理由见上表与 devlog「Review 后修复」一节。
