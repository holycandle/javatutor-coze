# 实施计划：Agent Harness 工程（图内真环 + 治理门闩 + HITL 内核）

> 依据：`docs/spec/2026-09-11-agent-harness-react-loop-design.md`（本计划是其 TDD 落地；决策编号 D1–D9 与该 spec 一致）。
> 交付边界（D8）：**到离线全绿为止**（L1–L5 + L2.5）；「重新发布 agent + e2e + Judge/Grounding 对比归档」见 §Task 15，由执行组在合入窗口完成。
> 分工（D1）：本文档由设计侧产出，执行由执行组完成。

## 0. 全局约束（务必遵守）

- **不做任何 git 操作**（不 `git add`/`commit`/`push`/`stash`/`checkout`/`branch`/`merge`）。读 `git log`/`git status`/`git diff` 可以。
- **外壳一个字节都不改**：`.coze`、`scripts/`、`src/main.py`、`src/storage/`、`src/utils/`。
  本次**新增** `guard`/`run_tools`/`verify` 需要挂 checkpointer 与 `/resume`——**全部记入 spec §6 请求清单，本 plan 不做**。
- **`build_agent(ctx=None)` 必须保留且暴露 `.builder`，不得在 `build_agent` 内 compile**（`docs/local-dev-convention.md` 硬约束）。
- 禁止 `from src.xxx import`；业务代码只允许新增到 `src/agents/`、`src/graphs/`、`src/learning/`、`src/tools/`、`tools/`、`assets/`、`config/`、`tests/`、`docs/`。
- **不引入新依赖**（`jsonschema` 不装），不改 `pyproject.toml`/`uv.lock`。
- 基线（改动前先跑一遍记数）：`uv run pytest -q` 应全绿；`uv run pytest tests/test_eval_component.py -v` 应 `pass_rate=1.0`。
- 开工前先对账队友分支：`git log --oneline origin/harness -5`（PR #14 改过 `critic.py::revise_node` 的编辑块逻辑，与本 plan 的改动面不相交，但要确认没有新改动落到 `main_agent.py`/`graph.py`）。

---

## Task 1：`verification.py` 上提 + `eval` 侧 re-export（D7）

**先改测试不动测试**：`tests/test_grounding.py` 一字不改，它继续 `from eval.runner.grounding import ...`。

1. 新建 `src/graphs/javatutor/verification.py`：把 [eval/runner/grounding.py](../../eval/runner/grounding.py) 的
   `STEP_REF`/`LINE_REF`/`HEAP_ID`/`_extract_ints`/`_payload`/`verify_grounding`/`_safe`/`compute_grounding_verify`
   **逐字搬过来**（含模块 docstring），只把 docstring 的第一句改成「确定性 grounding 核对器（业务侧实现，供运行时与评估共用一个口径）」。

2. `eval/runner/grounding.py` 全文替换为 re-export（**保留原模块路径，`eval/runner/report.py` 等既有导入不受影响**）：

   ```python
   """确定性 grounding 核对器（实现已上提到业务目录，此处仅 re-export 以保持既有导入路径）。"""

   from graphs.javatutor.verification import (  # noqa: F401
       compute_grounding_verify,
       verify_grounding,
   )
   ```

   > 该导入形式与 `eval/runner/component_metrics.py` 既有的 `from graphs.javatutor.intent_rules import ...` 同构，
   > 依赖 `pyproject.toml` 的 `[tool.pytest.ini_options] pythonpath = ["src", "."]`。

**验证**：`uv run pytest tests/test_grounding.py tests/test_eval_component.py -v` 全绿（应有零用例改动）。

---

## Task 2：动作契约 `harness/contracts.py`

**先写测试** `tests/test_harness_contracts.py`（新建）：

- `parse_action('{"tool":"step_facts","args":{"step_index":1}}')` → `Action(tool="step_facts", args={"step_index":1})`。
- `parse_action('{"tool":"step_facts"}')` → `args == {}`（缺省合法）。
- `parse_action('{"tool":"step_facts","args":"oops"}')` → **不是** `Action`，返回带 `parse_error` 的结果（对应 spec §4.1：取消静默 `{}`）。
- `parse_action("随便一段散文")` → `None`（不是提案，直接当终答）。
- `parse_action('{"args":{}}')` → `None`（无 `tool`）。
- `Observation(...)` 构造后 `render_observation(obs)` 返回 `summary`；`status != "ok"` 时渲染文本**必须含** `reason`/`error` 关键词（保证模型看得见失败原因）。

**实现** `src/graphs/javatutor/harness/__init__.py`（空）与 `harness/contracts.py`：

```python
@dataclass(frozen=True)
class Action:      tool: str; args: dict; raw: str
@dataclass(frozen=True)
class GuardDecision: verdict: str; policy: str; reason: str; options: list
@dataclass(frozen=True)
class Observation: tool: str; args: dict; status: str; policy: str; summary: str; payload: dict; latency_ms: float; truncated: bool
```

- `parse_action(raw) -> Action | None | ParseError`：JSON 解析失败或无 `tool` → `None`；
  `tool` 非空但 `args` 存在且非 dict → `ParseError(reason=...)`；`args` 缺省 → `{}`。
- `render_observation(obs) -> str`：`"ok"` 返回 `summary`；其余返回 `f"\\n\\n[{obs.tool} 未执行：{obs.policy}]\\n{obs.summary}"`（deny/invalid_args/error 都带得出原因）。

**同时迁移渲染器**：把 `_format_step_facts`（[main_agent.py:63-99](../../src/graphs/javatutor/main_agent.py)）与
`_handle_fetch` 的**渲染部分**（[:102-142](../../src/graphs/javatutor/main_agent.py)）移入 `harness/render.py`（纯函数，签名逐字不变），
`main_agent.py` 里保留 `from graphs.javatutor.harness.render import _format_step_facts, _handle_fetch  # noqa: F401`
（`tests/test_main_agent.py::test_format_step_facts_is_clean_labeled_text` 仍按原路径导入，**该用例不改**）。

---

## Task 3：工具注册表与参数校验 `harness/registry.py`

**先写测试** `tests/test_harness_registry.py`（并入 `test_harness_contracts.py` 亦可，二选一，别两处都有）：

- `TOOLS` 的键 == `{"fetch_execution_context", "step_facts"}`，且 `TOOLS["step_facts"]["schema"] is step_facts.TOOL_SCHEMA`（**同一对象引用**，证明单一事实源）。
- `validate_args("step_facts", {"step_index": 1})` → `[]`（无问题）。
- `validate_args("step_facts", {"bogus_key": 1})` → 含 `"bogus_key"` 的问题描述。
- `validate_args("step_facts", {"step_index": "1"})` → 类型问题（`string` 给了 `integer`）。
- `validate_args("step_facts", {"step_index": True})` → 类型问题（**`bool` 不算 `int`**）。
- `validate_args("fetch_execution_context", {"file": "A.java", "start_line": 3})` → `[]`。

**实现**：`TOOLS` 由两个工具模块的 `TOOL_SCHEMA` **引用构建**；`validate_args(tool, args)` 读 `schema["parameters"]["properties"]`
做「未知键 + type-name」校验（`integer`→`int and not bool`，`string`→`str`），返回问题列表（空列表 == 通过）。

> 不引入 `jsonschema`；不实现 `required`/`range`（当前两个工具的 schema 都没有这两项，等真有了再加）。

---

## Task 4：治理门闩 `harness/guard.py`

**先写测试** `tests/test_harness_guard.py`（新建）——逐条锁 P1–P5：

| 用例 | 输入 | 期望 |
|---|---|---|
| P1 未知工具 | `Action("no_such_tool", {}, ...)` | `verdict="deny"`, `policy="P1"`, `reason` 含 `step_facts` 与 `fetch_execution_context` |
| P2 未知键 | `Action("step_facts", {"bogus_key":1}, ...)` | `verdict="deny"`, `policy="P2"`, `reason` 含 `bogus_key` |
| P2 类型错 | `Action("step_facts", {"step_index":"1"}, ...)` | `deny` / `P2` |
| P3 预算兜底 | `state={"tool_rounds": 3}` + 任意合法 action | `deny` / `P3` |
| P4 歧义文件名（HITL 关） | `files={"Main.java":..,"Helper.java":..}`、`Action("fetch_execution_context",{"file":"Mian.java"},...)` | `verdict="deny"`, `policy="P4"`, `reason` 列出 `Main.java`/`Helper.java` |
| P4 单文件不触发 | `files={"Main.java":..}`、同样的错文件名 | `verdict="allow"`（单文件无歧义） |
| P4 大小写/ basename 命中 | `files={"Main.java":..}`、`file="main.java"` | `allow` |
| P5 重复步骤 | `state={"served_step_indices":[1]}`、`Action("step_facts",{"step_index":1})` | `verdict="allow"`, `policy="P5"` |
| 正常放行 | `Action("fetch_execution_context", {"file":"Main.java"})` 且 files 有它 | `verdict="allow"`, `policy="P0"`（无特殊策略命中） |

**实现** `decide(action, state) -> GuardDecision`（纯函数，**不抛异常、不读环境变量**）：

- 判定顺序：P3（预算）→ P1（白名单）→ P2（参数）→ P4（歧义）→ P5（重复，仅标记 allow）→ `allow/P0`。
- P4 的 `needs_decision` 与否**不在本模块决定**（本模块只产出 `needs_decision`），
  「HITL 关时降级成 deny」由 `guard_node` 依 `hitl_enabled()` 完成（§Task 6）——**保持 `decide` 可测且无副作用**。
- `state["files"]` 匹配口径与 `fetch_execution_context` 内部一致：精确 → 忽略大小写 → basename；
  实现时**从 `tools/fetch_execution_context.py` 抽出同名匹配函数复用**（若其中已有等价私有函数，改为复用它，**不要**写第二份匹配逻辑）。
- `options` 取值：`sorted(state["files"].keys())[:8]`。

---

## Task 5：HITL 开关 `harness/hitl.py`

**先写测试** `tests/test_harness_hitl.py`（前半部，单元）：

- 默认（未设环境变量）`hitl_enabled()` 为 `False`。
- `monkeypatch.setenv("COZE_AGENT_HITL", "1")` → `True`；`"0"`/空串/`"no"` → `False`。
- `hitl_brief(decision)` 返回含「需要你确认」+ `decision.options` 的可读文本（这是 `interrupt()` 的 value，也是未来 SSE 事件的载荷）。

**实现**：`hitl_enabled()` 读 `os.getenv("COZE_AGENT_HITL", "0")`；
`hitl_brief(decision) -> dict` 返回 `{"question": decision.reason, "options": decision.options}`。

> 默认关是**硬要求**（spec §5.3）：线上没有 resume 通道，默认开启会让提问永久挂起。

---

## Task 6：`main_agent` 改为提案节点 + 收束轮（含 `guard`/`run_tools` 节点）

这是本次最大的一块，按 6a → 6c 分三步、每步自带测试。

### 6a. `harness/propose.py`：提案与收束共用的一次调用

**先写测试** `tests/test_harness_loop.py`（新建，承接 `tests/test_main_agent.py` 的迁移，见 Task 12）：

- 累积序列：`RecordingModel` 收到第 2 次调用时，`messages` 里**能看到第 1 次的 `AIMessage` 提案原文**
  （这是「真 ReAct」的判据，也是本次最该被锁住的一条）。
- `messages[0]` 是 `SystemMessage`；`messages[1].content` 含 `context_built`；末条 `HumanMessage` 含 `[当前轮次] 2/3`。
- 收束模式（`state["tool_rounds"] >= 3`）：末条 `HumanMessage` 含「收束轮」字样；
  模型返回工具 JSON 时 `answer` **不含** `"tool"` 且非空（确定性收束文案兜底）；
  模型返回散文时 `answer == 散文`。
- 收束模式且 `step_records` 为空：`answer` 非空（沿用兜底文案）。

**实现** `harness/propose.py`：

```python
def propose(state, model=None) -> dict:
    """一次 LLM 调用：产出提案(Action) 或终答(answer)。收束模式下永不产出 Action。"""
```

- 消息组装见 spec §4.8；`_invoke`/`_resolve_model` 从 `main_agent.py` 移入本模块（**同一实现**，含 `llm_complete` 兜底路径）。
- `main_agent_node(state, model=None)` 保留为 `propose` 的薄包装（同名同签名），
  返回 `{"agent_messages": [...], "answer"? , "tool_calls"?: ...}` 语义见下：
  - 产出终答 → `{"answer": ..., "agent_messages": [...]}`；
  - 产出提案 → `{"proposed_action": {...}, "agent_messages": [...]}`（**不写 `answer`**）；
  - 收束模式 → 恒 `{"answer": ..., "agent_messages": [...]}`。
- `proposed_action` 用 dict（便于 state 合并与 trace）；解析失败（散文）即终答。

### 6b. `harness/tools_node.py`：执行与观察

**先写测试**（并入 `tests/test_harness_loop.py`）：

- `step_facts` 前自动前置一次 `fetch_execution_context`：`tool_calls == [fetch, step_facts]`，
  且 `step_records[0]["policy"] == "P0-auto-fetch"`、`step_records[0]` **不占用轮次**（`tool_rounds` 不变）。
- 成功观察：`step_records[-1]["status"] == "ok"`，`payload` 含 `diff`，`latency_ms` 是数字，`summary` 含「第 2 步（step_index=1）」。
- 越界/工具内部异常：`status == "error"`，`step_memories` 不新增（保住既有「失败不写记忆」语义）。
- `fetch_execution_context` 成功时，`fetched_context`/`run_id`/`source_code` 等既有 state 更新**照旧回灌**。

**实现** `run_tools_node(state, model=None) -> dict`：

- 入参 `state["proposed_action"]`；先按需执行 auto-fetch（**经 `decide()` 但绕过轮次计数**，见 spec §4.2 注），
  再执行提案动作；两者各产一条 `Observation`。
- 观察**渲染文本**追加进 `agent_messages`（`HumanMessage`）；结构化观察追加进 `step_records`。
- 回灌 `tool_calls`（沿用现有形状，`step_facts` 那条仍带截断 `result`——评测 M1.1 与决策痕迹都依赖）、`step_memories`（importance 0.8、最多 5 条）、
  `fetched_context` 等既有 `fetched_state_updates`（迁移时**逐键对齐** [main_agent.py:112-135](../../src/graphs/javatutor/main_agent.py)，不要漏键）。
- 清空 `proposed_action`（置 `{}`），避免下一轮复用陈旧提案。

### 6c. `harness/guard_node.py`：门闩节点（含 HITL 暂停点）

**先写测试**（并入 `tests/test_harness_guard.py`）：

- `guard_node` 入口必 `tool_rounds += 1`（`state` 无该键时从 0 起）。
- `allow` → 返回 `{"guard_decision": {...}}`，**不写**观察。
- `deny` → 追加 `Observation(status="denied")` 到 `step_records` 与 `agent_messages`，`tool_calls` **不新增**。
- `needs_decision` 且 HITL **关** → 降级为 `deny`（`policy` 保留 `P4`，`reason` 含可选文件）。
- `needs_decision` 且 HITL **开** → 调用 `interrupt(...)`（用 `monkeypatch` 把 `hitl.interrupt` 换成记录器，
  断言 value 等于 `hitl_brief(decision)`；单元测试不依赖 checkpointer）。

**实现** `guard_node(state) -> dict`：

```python
def guard_node(state):
    rounds = int(state.get("tool_rounds", 0)) + 1
    action = parse_action_from_state(state)
    decision = decide(action, {**state, "tool_rounds": rounds})
    if decision.verdict == "needs_decision" and hitl_enabled():
        answer = interrupt(hitl_brief(decision))         # 暂停点；恢复值即用户选择
        decision = GuardDecision("allow", "P4-resumed", f"用户选择：{answer}", [])
        # 把用户选择写成观察，回灌给模型（而不是替模型执行）
    ...
    return {"tool_rounds": rounds, "guard_decision": asdict(decision), **obs_updates}
```

- 恢复值（用户选的文件名）**不直接执行工具**，而是作为 `Observation(status="ok")` 的 `summary` 注入
  （`payload={"user_choice": ...}`），让模型在下一轮用正确的参数重提——保持「模型决策/门闩治理/工具执行」三层不互相越权。
- `needs_decision` 且 HITL 关 → `deny`（reason 带可选文件），走同一条 deny 路径。

> **执行后修订（2026-09-11，review P2-1）**：上面「恢复值不直接执行、让模型重提」的做法在
> **最后一轮预算**会丢用户的选择——`propose` 此时已进入收束模式（`rounds >= MAX_ROUNDS`），
> 永不产出 Action，那句「请用该文件名重新调用」指向一个模型结构上做不到的动作。
> 现改为 `policy="P4-resolved"`：门闩用用户选的文件名**补全原提案的 `file`** 后放行到 `run_tools`
> （原提案的工具与其它参数本来就合法，唯一不可判定的就是 `file`）。`_route_after_guard` 相应简化为
> 「verdict == allow → tools」。spec §5.1 已同步；边界用例见
> `tests/test_harness_hitl.py::test_hitl_resolves_ambiguity_on_the_last_budgeted_round`。

---

## Task 7：图接线（`graph.py`）

**先改测试** `tests/test_graph.py`：

- `test_build_flow_graph_structure` 增加 `guard`/`run_tools`/`verify` 三个 `in graph.nodes` 断言（既有断言**一个不删**）。
- 新增 `test_graph_has_react_cycle_edge`：`assert ("run_tools", "main_agent") in graph.edges`。
- 新增 `test_graph_verify_before_save_session`：`assert ("verify", "save_session") in graph.edges` 且 `("revise","save_session") not in graph.edges`。
- 既有 `test_graph_has_no_fetch_node`（`fetch_execution_context not in graph.nodes`）**保持**——工具化语义不变。

**实现** `src/graphs/javatutor/graph.py`：按 spec §4.2 加 3 个节点、2 组条件边、改 1 条无条件边。
模块 docstring 的链路图同步更新（这是**图上可读性的唯一文档**，别留旧链路）。

---

## Task 8：`verify` 节点 + `decision_trace` 增量（D4）

**先写测试** `tests/test_verify_node.py`（新建）：

- 有 steps、回答引用 `第 99 步` → `verification["applicable"] is True`、`violations >= 1`、`hallucinated` 非空。
- 无 steps → `applicable is False`、`grounding_ok is True`（**不判罚**）。
- 回答正文里的 `【编辑建议】` JSON 内含 `h1` 字样时**不产生**堆对象误报（证明结构化块已被剥离）。
- `verification` 出现在 `decision_trace` 中，且既有键（`intent`/`critic_passed`/`tool_calls`/`token_usage`）仍在。

**实现**：

1. `src/graphs/javatutor/nodes.py`：
   - 新增 `verify_node(state) -> {"verification": result}`（三条逻辑见 spec §4.7）。
   - 抽出（或复用）结构化块剥离函数，把 `【决策痕迹】`/`【编辑建议】`/`【视角导航】` 从待核对文本里去掉。
   - `build_final` 的 `trace` dict 增加 `"verification": state.get("verification") or {}`——
     **只增不改**，既有键顺序与语义不动。
2. `state.py` 新增字段（`total=False`，纯追加）：
   `agent_messages: list`、`proposed_action: dict`、`guard_decision: dict`、`step_records: list`、`verification: dict`、`fetched_injected: bool`。

**回归**：`uv run pytest tests/test_graph.py -k trace -v` 与
`tests/test_build_final.py` 必须全绿（`test_full_flow_generate_review_revise_trace` 是本次的主要回归哨兵）。

---

## Task 9：HITL 离线端到端（D6，本次的核心证明）

**先写测试** `tests/test_harness_hitl.py`（后半部）：

```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
```

1. `monkeypatch.setenv("COZE_AGENT_HITL", "1")`；`graph = build_flow_graph().compile(checkpointer=MemorySaver())`。
2. payload 带**多文件**（`files={"Main.java": ..., "Helper.java": ...}`）+ 一个路由模型
   （对 `教学主 Agent` 的系统提示返回 `{"tool":"fetch_execution_context","args":{"file":"Mian.java"}}`，其余分支返回散文）。
3. `cfg = {"configurable": {"thread_id": "t1", "chat_model": model}, "recursion_limit": 40}`
   → `first = graph.invoke(initial, cfg)` → 断言 `"__interrupt__" in first`，
   且 `first["__interrupt__"][0].value["options"]` 含 `Main.java` 与 `Helper.java`（**用户看得见可选项**）。
4. `second = graph.invoke(Command(resume="Main.java"), cfg)` → 断言收敛：`second["answer"]` 非空、
   `__interrupt__` 不再出现、`step_records` 中存在 `payload["user_choice"] == "Main.java"` 的记录。
5. 反例（HITL 关，即默认）：同样 payload **不产生** `__interrupt__`，直接得到 `deny` 观察，`answer` 非空。

> 该用例同时证明三件事：内核可用、暂停点有可选项供人选择、恢复值与模型上下文真的接上了。
> `chat_model` 需要按「系统提示含 `教学主 Agent`」路由（沿用 `test_graph.py::DeepModel` 的写法）。

---

## Task 10：终止性与递归预算（spec §4.3）

**先写测试** `tests/test_harness_termination.py`（新建）：

- **病态模型**：对主 Agent 分支**连续 10 次**都返回 `{"tool":"step_facts","args":{"step_index":1}}`。
  跑完整图（`recursion_limit` 用**默认值**，即不传）：
  - 不抛 `GraphRecursionError`；
  - `tool_rounds == 3`；
  - `answer` 非空且 `"tool" not in answer`（收束轮兜底，不把 JSON 当答案）。
- **预算算术**：断言 `MAX_ROUNDS == 3`，并在测试里注释写清
  `6 + 4 + 3 + 3 + 5 = 21 < 25`（前缀/主Agent/门闩/工具/后缀）——**将来加节点时必须改这条注释并重算**。
- **未知工具 spam**：第 1 轮提未知工具（被 P1 拒），第 2 轮起正常 → 图正常收敛、`tool_calls` 不含被拒工具。

---

## Task 11：迁移 `tests/test_main_agent.py`（12 个用例 → 图级）

现状 12 个用例全部直接调 `main_agent_node(STATE, model=model)`——**该入口已不再是循环**，必须迁移。
迁移原则：**锁住的「行为」一条都不许丢**，只换驱动方式（图级 + 路由模型）。

| 原用例 | 去向 | 断言要求（行为不变） |
|---|---|---|
| `test_format_step_facts_is_clean_labeled_text` | **留在 `test_main_agent.py`** | 一字不改（纯函数，路径已 re-export） |
| `test_main_agent_direct_answer` | `test_harness_loop.py` | 一轮即答；`tool_rounds == 1` |
| `test_main_agent_calls_step_facts_then_answers` | 同上 | `tool_calls[0]=fetch`、`[1]=step_facts`、`result` 键在 |
| `test_step_facts_auto_fetches_first` | 同上 | `tools[0]=="fetch_execution_context"` |
| `test_main_agent_records_step_memories` | 同上 | 1 条、`importance==0.8`、含 `diff` |
| `test_main_agent_tool_error_does_not_record_memory` | 同上 | `step_memories==[]`、`answer` 非空 |
| `test_main_agent_repeat_same_step_gets_answer_nudge` | 同上 | 「不要重复查询同一步骤」出现在**下一轮**给模型的消息里 |
| `test_main_agent_dispatches_fetch_execution_context` | 同上 | `fetched_context["run_id"]=="r1"` |
| `test_main_agent_fetch_failure_appends_error_and_continues` | 同上 | `answer` 非空、`fetch_context_failed is True` |
| `test_main_agent_stops_after_three_rounds` | 同上 | `tool_rounds == 3`（**并新增**断言：answer 是收束轮文本，不再是兜底道歉） |
| `test_main_agent_unknown_tool_not_leaked_as_answer` | 同上，**改写** | 未知工具 → `deny`；`step_records` 有 `status=="denied"`；`tool_calls` 不含它；answer 不含 JSON |
| `test_main_agent_invalid_args_returns_error_not_crash` | 同上，**改写** | 未知键 → `deny`/`P2`（`status=="invalid_args"`），**不再**出现 `step_facts 参数非法: ... TypeError` 文案；不抛异常 |

图级用例的统一写法：

```python
class RouterModel:
    """按系统提示路由：主 Agent 分支按脚本返回，其余分支返回散文。"""
    def __init__(self, main_scripts): ...
    def invoke(self, messages): ...
```

- **不要**为测试在业务代码里留注入后门；`configurable.chat_model` 是既有且唯一的注入点。
- 迁移完成后 `tests/test_main_agent.py` 只保留纯函数用例并改名注释为「纯渲染器测试」。

---

## Task 12：同步协作指南（AGENT.md 登记规则的强制项）

`docs/agent-collaboration-guide.md` 是图结构/节点/输入输出的**单一事实源**，本次图**新增 3 节点 + 1 个环**，必须同步：

1. 「处理流程图」改为 spec §4.2 的图（含环与 `analyze` 短路）。
2. 节点表新增 `guard`/`run_tools`/`verify` 三行（职责、输入、输出、是否调用 LLM）。
3. 「信息分层原则」表补一行：**治理决策（allow/deny/needs_decision）属门闩层，不是提示词**。
4. 「输入输出 contract」补新增 state 字段（`agent_messages`/`step_records`/`guard_decision`/`verification`）。
5. 上手三件事里「agent 怎么用工具」的描述更新为「提案 → 门闩 → 执行 → 观察」。

`AGENT.md`：把本 spec/plan 登记到「规约与文档索引」表，并在「当前执行状态」表加两行
（`Harness 工程 spec | 已定稿`、`Harness 工程 plan | 待执行`）。

---

## Task 13：实施记录

新建 `docs/devlog/2026-09-11-agent-harness-react-loop.md`：改动清单、D1–D9 落地对照、
与计划的偏差、测试数（前后对比）、**已知局限**（HITL 线上默认关、`recursion_limit` 余量 4、
前端对新 trace 字段未确认）、手验/离线验证结果。并在 `AGENT.md` 登记。

---

## 验证（本地全绿门槛，逐条给命令）

```bash
# L1 依赖一致
uv sync --frozen

# L2 全量单测（本 plan 会新增约 6 个测试文件、改写 2 个）
uv run pytest tests/ -v

# L2.5 组件级评估（pass_rate 必须 == 1.0）——本次改动命中 prompt/工具，按 §5 为强制项
uv run pytest tests/test_eval_component.py -v

# L3 离线构建（build_agent 不 compile）
PYTHONPATH=src uv run python -c "from agents.agent import build_agent; g = build_agent().builder.compile(); print('ok')"

# L4 本地 HTTP 冒烟（按 docs/local-dev-convention.md 的既有起服务方式跑一次问答；
#    重点看：answer 非空、【决策痕迹】在、decision_trace 含 verification）
# L5 外壳回归：.coze / scripts/ / src/main.py / src/storage/ / src/utils/ 零 diff
git status --short
```

**额外的定向验证**：

```bash
uv run pytest tests/test_grounding.py tests/test_eval_component.py -q       # 核对器口径未变（Task 1）
uv run pytest tests/test_graph.py -k "trace or cycle or verify" -v          # 图与 trace 回归
uv run pytest tests/test_harness_termination.py -v                          # 默认 recursion_limit 下不炸
uv run pytest tests/test_harness_hitl.py -v                                 # 中断→恢复
```

---

## Task 14：手工确认清单（离线可做）

1. 造一个「模型一直提工具」的模型跑完整图 → 观察 `answer` 是收束文案（含已获证据），**不是**道歉。
2. 造「未知工具」提案 → `decision_trace.tool_calls` 里**没有**它，`step_records` 里有 `denied` 记录。
3. 造多文件 + 错文件名：HITL 关 → 直接 `deny`（reason 列出可选文件）；HITL 开 + `MemorySaver` → 中断并可恢复。
4. 无 steps 的 payload（纯概念问题）→ `verification.applicable is False`，评价不受影响。
5. 反复跑同一问题两次，观察主 Agent 第 2 轮消息里**真的有第 1 轮的 `AIMessage`**（真 ReAct 的手工确认）。

---

## Task 15：合入窗口的交付步骤（执行组做，本 plan 的最后一环）

> 以下**不属于本次离线交付**（D8），但按 `local-dev-convention.md` §5 是**合入的强制前提**：

1. **重新发布 agent**：合入后按既有部署流程「重新发布 agent」让 Coze 侧生效（仅改本地代码不生效）。
2. **端到端评估**：跑本轮 Judge，并与**上一轮**均分对比。门槛：**均分下降 > 0.3 或 Grounding 下降 > 0.5 禁止合入**。
   重点看的指标：`tool_calls` 准确率、fetch 调用率、`grounding_verify_*`（本次新接入运行时的口径应与离线一致）、`critic_skipped` 占比。
3. **归档**：对比结果写入 `docs/devlog/2026-09-11-agent-harness-react-loop.md` 的「评估对比」一节（含两轮均分与逐项指标）。
4. **回归抽查**：线上真实提问 3 例（单文件/多文件/带编译错误），确认 `【决策痕迹】` 与 `【编辑建议】` 块未被本次改造破坏。
5. **HITL 保持关闭**：在 §6 外壳请求清单落地（checkpointer + `/resume`）之前，**不要**在生产设置 `COZE_AGENT_HITL`。

---

## 遗留 / 注意事项

- **HITL 线上不可用是已知且刻意的**：内核已离线证明，但没有 checkpointer 与 `/resume`，
  线上开启会让提问永久挂起。开关默认关是安全边界，不是未完成项。清单见 spec §6。
- **`recursion_limit` 余量只有 4**（21 vs 25）：将来**任何**新增节点/轮次都必须重算 Task 10 的注释并保留余量；
  若必须扩容，优先把 `/run`、`/stream_run` 的 `recursion_limit` 显式提高（属外壳，走 §6 流程）。
- **每轮 `agent_messages` 累积**：4 轮上限内可接受；若未来 `MAX_ROUNDS` 上调，需重新评估上下文体量。
- **`verification` 不参与路由**（D4）：本次只做「可观测的客观门闩」。若评估显示它能有效预测幻觉，
  下一轮再谈「`violations > 0` 时是否触发 `revise`」——**那是一次独立的、需要评测支撑的改动**。
- **前端对 `decision_trace` 新字段的渲染未确认**（spec §4.7）：若前端把未知键兜底渲染成噪声，
  在 `javatutor` 仓另开纯前端小改动。
- **与队友 `zzmleslie` 的 `harness` 分支**：开工与合入前各对账一次 `git log origin/harness`；
  若其改动进入 `main_agent.py`/`graph.py`，先与设计侧重新对齐再动手。
