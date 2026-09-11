# Agent Harness 工程（ReAct 循环契约化 + 治理门闩 + HITL 内核）规格

> 状态：**spec 阶段**（本文档为实施方案，供执行组落地）。
> 来源：2026-09-11 `/grill-me` 会话收敛结论。
> 参考：`Hello-Agents/13_Harness工程.md` 的 8 条原则；队友 `zzmleslie` 的 `harness` 分支 / PR #14（`coding-agent` / MiniGuard 同源思路）。
> 关联：
> - 协作分工与文档规范：[AGENT.md](../../AGENT.md)
> - 验证门槛与外壳契约：[docs/local-dev-convention.md](../local-dev-convention.md)
> - 图结构/节点/输入输出的单一事实源：[docs/agent-collaboration-guide.md](../agent-collaboration-guide.md)（本 spec 落地时必须同步该文档）
> - 既有深化链路：[2026-08-14-agent-architecture-improvement-design.md](./2026-08-14-agent-architecture-improvement-design.md)
> - 既有确定性核对器：[2026-08-24-grounding-verifier.md](../devlog/2026-08-24-grounding-verifier.md)（本次把它接进运行时）

## 1. Context（为什么做）

当前「ReAct 循环」并没有真正落在图结构上，而是被写死在 `main_agent_node` 的一个 `while rounds < MAX_ROUNDS` 里
（[main_agent.py:145-223](../../src/graphs/javatutor/main_agent.py)）。它带来四个具体问题：

1. **没有真 Reasoning 轨迹**：每一轮都**重建** `messages`（[main_agent.py:156-159](../../src/graphs/javatutor/main_agent.py)），
   模型看不到自己上一轮的提案，模型侧不存在「我因为 X 才去查 Y」的因果链。这既是可观测性缺口，也是「反复试探同一步骤」的成因之一。
2. **没有治理**：工具是否可执行完全由**提示词**决定。未知工具只得到一句文本提示
   （[main_agent.py:211-214](../../src/graphs/javatutor/main_agent.py)），参数非法被静默吞成 `{}`
   （[main_agent.py:170](../../src/graphs/javatutor/main_agent.py)、[:178](../../src/graphs/javatutor/main_agent.py)），
   `TOOL_SCHEMA` 在整个运行时**从未被用于校验**（全仓只在 [test_fetch_execution_context.py:27](../../tests/test_fetch_execution_context.py) 里被读过）。
3. **完成没有客观门闩**：唯一的完成检查是 LLM 评审（主观），且评审解析失败/异常时**放行**
   （[critic.py:82-83](../../src/graphs/javatutor/critic.py)、[:90-91](../../src/graphs/javatutor/critic.py)）。
   注意：该放行是**有标记的**（`critic_skipped=True`，进 `decision_trace`，前端有提示），不是静默通过——
   真正缺的是「跳过 LLM 评审时**没有任何确定性兜底**」。
   而确定性核对器**已经存在**（[eval/runner/grounding.py](../../eval/runner/grounding.py)，反幻觉核对：步骤号/行号/堆对象 id），
   却只跑在离线评测链路里。
4. **无法暂停**：没有中断/恢复语义。轮次用光时直接给一句兜底道歉
   （[main_agent.py:215-216](../../src/graphs/javatutor/main_agent.py)），已经拿到的证据全部作废。

本 spec 把上述四点收敛成一次改造：**把循环从节点内提到图内、把治理从提示词变成门闩、把完成检查从主观评审扩成「主观 + 客观」、把中断恢复做成本文可离线证明的内核。**

## 2. 现状差距（8 原则逐条核对，只读勘测结论）

| # | 原则 | 现状 | 证据 |
|---|---|---|---|
| ① | 决策与执行分离 | ⚠️ 有雏形 | LLM 只输出 JSON 提案，解析与执行在代码里；但提案与执行同处一个节点、共用局部变量，图上看不出这层分离 |
| ② | 统一动作契约 | ❌ 缺失 | 无 `Action`/`GuardDecision`/`Observation` 类型；观察是 `context +=` 拼接的字符串；`args` 非 dict 时静默变成 `{}` |
| ③ | 治理是门闩不是提示词 | ❌ 缺失 | 未知工具靠文本提示；无 allow/deny/needs_decision；`TOOL_SCHEMA` 未参与运行时 |
| ④ | 失败是数据不是异常 | ✅ 已有 | `TypeError` → 结构化 error（[main_agent.py:181-183](../../src/graphs/javatutor/main_agent.py)）；LLM 异常 → 降级文案（[:162-163](../../src/graphs/javatutor/main_agent.py)）；RAG 失败 → `rag_degraded` |
| ⑤ | 完成必须有客观验证门闩 | ⚠️ 只有主观 | LLM 评审 + 可跳过；确定性核对器存在但**未接运行时** |
| ⑥ | 状态机化支持暂停与恢复 | ❌ 缺失 | 无中断/恢复；轮次耗尽 → 兜底道歉 |
| ⑦ | 可观测性是一等公民 | ⚠️ 部分 | `tool_calls`/`decision_trace` 有；但没有逐动作的 StepRecord，且每轮重建 messages 丢掉了推理链 |
| ⑧ | 没有 LLM 也能测试 | ✅ 已有 | `SequenceModel`/`FakeModel`/`RecordingModel` 注入（[test_main_agent.py](../../tests/test_main_agent.py)）；图级 `DeepModel` 经 `configurable.chat_model` 注入（[test_graph.py](../../tests/test_graph.py)） |

**结论**：④⑧ 已经达标，本次**不重做**；②③⑥ 是纯缺口；①⑤⑦ 是补全而非新建。

## 3. 已收敛的决策（/grill-me 结论）

| # | 决策 | 理由 / 边界 |
|---|---|---|
| **D1** | 本次只交付 **spec + plan**，执行交给执行组 | AGENT.md 既有分工：设计由 Codex 产出（spec → plan），执行由 Claude Code 完成 |
| **D2** | HITL 只建**内核 + 离线证明**（零跨仓改动） | 真 HITL 的 `/resume` 端点必须落在 `src/main.py`，而外壳属**禁止修改**清单（AGENT.md「不修改外壳」）→ 本次做不了，也不是保守 |
| **D3** | 循环改造 = 契约 + 门闩 + 观察结构化 + 收束轮 + **累积消息序列（真 ReAct）**；**不换 `bind_tools`**；**不做动态预算门闩** | 现有 LLM 调用统一走 `llm_complete()` 绕过 `ChatOpenAI`（[llm.py](../../src/graphs/javatutor/llm.py)）；改 `bind_tools` 会把工具调用暴露给平台的 `stream_mode="messages"` 流式层，风险高、收益低。动态预算缺少可调依据，先固定常量 |
| **D4** | 验证门闩 = 修「跳过评审无兜底」+ **接确定性结构校验**；**不做**「校验不过拒绝结束」 | 拒绝结束会在真实教学场景把可用回答变成不可用；本次只做**记录 + 可观测**，不改变放行语义 |
| **D5** | 循环落点 = **图内真环**：`main_agent`（提案）→ `guard`（治理）→ `run_tools`（执行）→ 回 `main_agent`，条件边控轮数 | 图是唯一能表达「暂停/恢复/治理」的层；节点内 `while` 无法支持中断 |
| **D6** | HITL 内核形态 = `interrupt()` + 离线 `Command(resume=...)` 用例（`MemorySaver` 编译图证明中断→恢复） | 不依赖外壳即可证明内核正确；线上 resume 通道另附**外壳改造请求清单**（§6） |
| **D7** | grounding 纯逻辑**上提**到 `src/graphs/javatutor/verification.py`，`eval/runner/grounding.py` 改为 re-export，`tests/test_grounding.py` **不改** | 避免两套实现分叉；re-export 是既有惯例（`eval/runner/component_metrics.py` 已 `from graphs.javatutor.intent_rules import ...`） |
| **D8** | 交付边界 = spec/plan 到**离线全绿**（L1–L5 + L2.5）；「重新发布 agent + e2e + Judge/Grounding 对比归档」写进 plan 末尾由执行组在合入窗口做 | 端到端评测需线上凭证与环境，不属于本次可验证范围；但门槛本身是**强制项**（本次改动命中 prompt/工具，按 `local-dev-convention.md` §5 必须附均分对比） |
| **D9** | 工具协议**保持文本 JSON**（`{"tool":..., "args":...}`），不引入 `bind_tools` | 同 D3；且协议已在 [docs/spec/2026-08-10-coze-agent-interface.md](./2026-08-10-coze-agent-interface.md) 固化，前端/评测已依赖 |

## 4. 设计

### 4.1 统一动作契约（新增 `src/graphs/javatutor/harness/contracts.py`）

```python
@dataclass(frozen=True)
class Action:
    tool: str          # 提案的工具名（未校验）
    args: dict         # 必须是 dict；非 dict 在解析阶段即视为非法，不做静默兜底
    raw: str           # 模型原始输出，供诊断

@dataclass(frozen=True)
class GuardDecision:
    verdict: str       # "allow" | "deny" | "needs_decision"
    policy: str        # 触发策略编号，见 §4.5
    reason: str        # 给模型/用户读的一句话（deny 时会被注入观察）
    options: list[str] # needs_decision 时给用户的可选项（deny 时为空）

@dataclass(frozen=True)
class Observation:
    tool: str
    args: dict
    status: str        # "ok" | "error" | "denied" | "invalid_args"
    policy: str        # 与之关联的策略（无则 ""）
    summary: str       # 渲染给模型的文本（复用既有渲染器，见下）
    payload: dict      # 结构化原始数据（供 trace / 记忆 / 评估）
    latency_ms: float
    truncated: bool
```

- **`Action` 解析**（`harness/contracts.py::parse_action`）：沿用现有 `_parse_tool` 的 JSON 判定，但**要求 `args` 是 dict**；
  `{"tool":"x"}` → `args={}`；`{"tool":"x","args":"y"}` → 返回 `parse_error` 而不产出 `Action`（对应现状 [:170](../../src/graphs/javatutor/main_agent.py)、[:178](../../src/graphs/javatutor/main_agent.py) 的静默 `{}`，改为可观测的 `invalid_args`）。
- **`summary` 渲染**：**复用既有渲染器，不新写文案**——`step_facts` 用 `_format_step_facts()`（[main_agent.py:63-99](../../src/graphs/javatutor/main_agent.py)），
  `fetch_execution_context` 用 `_handle_fetch()` 的结果渲染（[:102-142](../../src/graphs/javatutor/main_agent.py)）。两处随本次改造迁移到 `harness/render.py`（纯函数，签名不变），原位置保留 re-export 以免测试悬空。
- **`Observation` 落 state**：新增状态字段 `step_records: list[dict]`（逐动作记录，Observation 的 dict 形态）。
  这是原则⑦的「StepRecord」，也是 B 端可观测与后续评估的数据源。

### 4.2 图拓扑：图内真环（改 `src/graphs/javatutor/graph.py`）

```
parse_context → context_compaction → analyze_code
  ├─ intent=analyze ─────────────────────────────────────────────→ END
  └─ continue → load_session → retrieve_knowledge → build_context
                     ┌──────────────────────┐
                     ↓                      │
                 main_agent ──(answer)──→ critic → revise → verify → save_session → final → END
                     │                                        ▲
                  (action)                                    │
                     ↓                                        │
                   guard ──(allow)──→ run_tools ───────────────┘
                     │                    (回 main_agent)
                     └──(deny / needs_decision)──→ 回 main_agent
```

新增 3 个节点：`guard`（治理，纯函数）、`run_tools`（执行，纯函数）、`verify`（客观核对，纯函数）。
节点数 11 → 14。边：

```python
graph.add_conditional_edges("main_agent", _route_after_propose, {"critic": "critic", "guard": "guard"})
graph.add_conditional_edges("guard", _route_after_guard, {"tools": "run_tools", "propose": "main_agent"})
graph.add_edge("run_tools", "main_agent")
graph.add_edge("verify", "save_session")        # 原 add_edge("revise", "save_session") 顺延
```

`_route_after_propose`：`state["answer"]` 非空 → `"critic"`；否则 → `"guard"`。
`_route_after_guard`：`allow` → `"tools"`；`deny` / `needs_decision`（含 HITL 恢复后）→ `"propose"`。

> **`guard` 是唯一的暂停点**：`needs_decision` 且 HITL 开启时，`guard_node` 内部调用 `interrupt()`，
> 恢复值（用户选择）被渲染成 `Observation(status="ok")` 注入回 `main_agent`，**不再单独设 `hitl` 节点**——
> 「门闩就是提问的地方」，少一个节点少一层间接。

### 4.3 轮次预算与终止性证明（**硬约束，必须由测试锁住**）

- `MAX_ROUNDS = 3` 语义**保持**「最多 3 次工具执行」，由 `guard_node` 入口 `tool_rounds += 1`（沿用既有字段名，避免状态重命名）。
- **收束轮不占用工具轮次**：`main_agent` 读到 `tool_rounds >= MAX_ROUNDS` 时进入**收束模式**（见 §4.4），
  该模式下**永不产出 `Action`**，因此「图一定终止」由结构保证，而不是靠提示词祈愿。
- 终止性证明（每次 `main_agent` 访问必消耗一个轮次或直接进入终结）：
  - `main_agent` 首次访问 `tool_rounds = 0`；此后每次回到 `main_agent` 都必然经过一次 `guard`，而 `guard` 必 `+1`。
  - 故 `main_agent` 访问次数 ≤ `MAX_ROUNDS + 1 = 4`（第 4 次即收束轮）；`guard` ≤ 3；`run_tools` ≤ 3。
  - 前缀 6 + `main_agent` 4 + `guard` 3 + `run_tools` 3 + 后缀 5 = **21**，低于 LangGraph 默认 `recursion_limit=25`（余量 4）。
  - 无需自环边、无需额外标志位：收束模式由 `tool_rounds` 直接判定（这也让「为什么第 4 次不能调工具」在图上是可读的）。
- **`recursion_limit` 现状**：仅 `/async_run` 显式设置，`/run`、`/stream_run` 走默认值——属外壳，本次不改，
  已列入 §6 外壳请求清单（建议显式设 40 并把本预算写进注释）。

### 4.4 收束轮（替代兜底道歉）

进入收束模式时，`main_agent` 的最后一轮消息追加一段确定性指令：

```
[收束轮] 工具轮次预算已用尽。请立刻基于上文已获得的证据直接给出最终回答，
不要再输出任何工具调用 JSON。若证据不足以回答，请明确说明「还缺什么」而不是猜测。
```

该轮**无条件产出 `answer`**：

1. 模型返回散文 → 直接作为 `answer`。
2. 模型**仍返回工具 JSON** → 丢弃 JSON，改用**确定性收束文案**：以 `step_records` 中已成功的观察渲染文本为正文，
   前置一行「（工具轮次预算已用尽，以下为已获得的执行证据）」。
3. `step_records` 为空（例如模型只提了被拒绝的动作）→ 沿用既有兜底文案（[main_agent.py:216](../../src/graphs/javatutor/main_agent.py)），
   保证 `answer` 恒非空。

> 收益：现状在轮次耗尽时**丢掉全部已获得的证据**并给一句道歉；收束轮把三轮回执的证据**保住并交付**。

### 4.5 治理策略表（`harness/guard.py`，纯函数 `decide(action, state) -> GuardDecision`）

| 策略 | 触发条件 | 裁决 | 依据 |
|---|---|---|---|
| **P1 工具白名单** | `action.tool` 不在注册表 | `deny`（reason 列出可用工具） | 注册表由 `TOOL_SCHEMA` 构建（§4.6），未知工具不再走「文本提示」分支 |
| **P2 参数结构校验** | `args` 含未知键 / 类型不符（如 `step_index` 非整数） | `deny`（reason 附 schema 允许的键与类型） | `TOOL_SCHEMA["parameters"]["properties"]`，**单一事实源** |
| **P3 轮次预算兜底** | 进入 `guard` 时 `tool_rounds >= MAX_ROUNDS` | `deny`（reason「轮次预算已用尽，请直接作答」） | 正常路径不可达（§4.3 已保证），仅作结构兜底 |
| **P4 文件名歧义** | 工具为 `fetch_execution_context`、`args.file` 非空、在 `state["files"]` 中按「精确 / 忽略大小写 / basename」三种方式**都匹配不到**，且 `len(state["files"]) > 1` | `needs_decision`：`options = 排序后的文件名（最多 8 个）`；**HITL 关闭时降级为 `deny`**（reason 列出可选文件） | `state["files"]` 由 `parse_context` 从 payload 归一化写入（[nodes.py:124](../../src/graphs/javatutor/nodes.py)、[:154](../../src/graphs/javatutor/nodes.py)），门闩时**已可用** |
| **P5 重复步骤** | `step_facts` 的 `step_index` 在本轮已查询过 | **`allow`**（观察文本追加既有「请直接作答，不要重复查询同一步骤」提示） | **刻意保持现状**：该行为是 2026-09-08 为抢回评测分数而加的（[devlog](../devlog/2026-09-08-raise-fetch-tool-call-rate.md)），改成 `deny` 会动评测基线 |

**原则④的落实**：门闩**永远返回决策**，不抛异常；`deny`/`invalid_args` 都是可读的 `Observation`，模型据此自我修正——
这是「失败是数据」从工具层扩展到治理层。

### 4.6 工具注册表（新增 `harness/registry.py`）

```python
TOOLS = {
    "fetch_execution_context": {"schema": fetch_TOOL_SCHEMA, "fn": fetch_execution_context},
    "step_facts": {"schema": step_facts_TOOL_SCHEMA, "fn": step_facts},
}
```

- **构建方式**：从各工具模块的 `TOOL_SCHEMA` 生成，**不另写一份**（避免与 [step_facts.py:8](../../src/tools/step_facts.py)、[fetch_execution_context.py:14](../../src/tools/fetch_execution_context.py) 分叉）。
- **参数校验**：`validate_args(tool, args)` 读 `parameters.properties[*].type` 做 **type-name 校验 + 未知键检查**（`integer`→`int` 且非 `bool`、`string`→`str`）。
  仅两个工具、约 20 行，**不引入 `jsonschema` 依赖**（避免 lockfile 变更面）。
  若后续工具数增长到需要完整 JSON Schema 语义，再单开一次改动引入依赖。
- **不使用 `bind_tools`**（D3/D9）：注册表只服务「校验 + 执行」，不参与 LLM 侧函数调用协议。

### 4.7 确定性完成门闩（原则⑤）

1. **上提**：`eval/runner/grounding.py` 的 `verify_grounding` / `compute_grounding_verify`（含 `STEP_REF`/`LINE_REF`/`HEAP_ID` 与 `_payload`）
   **原样**迁到 `src/graphs/javatutor/verification.py`；`eval/runner/grounding.py` 改为：

   ```python
   """确定性 grounding 核对器（实现已上提到业务目录，此处仅 re-export 以保持既有导入路径）。"""
   from graphs.javatutor.verification import compute_grounding_verify, verify_grounding  # noqa: F401
   ```

   `tests/test_grounding.py` 的 `from eval.runner.grounding import ...` **保持不变**，用例一字不改即应全绿。
2. **接进运行时**：新增 `verify` 节点（`revise` 之后、`save_session` 之前），**核对的是最终交付文本**：

   ```python
   def verify_node(state):
       body = _strip_structured_blocks(state.get("revised_answer") or state.get("answer") or "")
       result = verify_grounding({"payload": {"steps": state.get("steps") or [], "source_code": state.get("source_code") or ""}}, body)
       return {"verification": result}
   ```

   - **必须先剥掉结构化块**：`【编辑建议】`/`【视角导航】` 的 JSON 里含代码片段（可能出现 `h1` 之类的标识符、行号样数字），
     不剥会产生假阳性。复用既有剥离逻辑（`build_final` 前处理的同一套：`【决策痕迹】`/`【编辑建议】`/`【视角导航】`）。
   - **不改变放行语义**（D4）：`verification` 只写入 state 与 `decision_trace`，**不参与路由、不触发修订**。
   - **与评审跳过互补**：`critic_skipped=True` 时，`verification` 是唯一还站着的客观证据；
     `verification.applicable=False`（无 steps）时明确不判罚——与离线口径一致。
3. **可观测**：`decision_trace` 新增 `verification` 字段（`applicable/checked/violations/hallucinated` 四项），
   既有字段一个不动（`test_full_flow_generate_review_revise_trace` 与评测 M1.1 依赖既有键的**存在性**）。
   前端 `decisionTrace.js` 对未知键的行为需执行组**顺手确认**；若它把未知键兜底渲染成噪声，
   在 `javatutor` 仓另开一个纯前端小改动（**不在本 plan 内**）。

### 4.8 真 ReAct 消息序列（原则⑦）

- 新增状态字段 `agent_messages: list[AnyMessage]`（**不复用 `messages`**：`messages` 是入站契约，
  `parse_context` 依赖其最后一条，且平台 `stream_mode="messages"` 与它耦合）。
- 组装方式（替换现状 [:156-159](../../src/graphs/javatutor/main_agent.py) 的每轮重建）：

  ```python
  history = state.get("agent_messages") or [SystemMessage(content=_main_system_prompt()),
                                            HumanMessage(content=state.get("context_built", ""))]
  history = history + [HumanMessage(content=f"{rendered_observation}\n\n[当前轮次] {tool_rounds + 1}/{MAX_ROUNDS}")]
  ```

  即：`main_agent` 追加**自己的提案**（`AIMessage`，原样保留模型输出以便自我纠错），
  `guard`/`run_tools` 追加**观察**（`HumanMessage`，渲染文本 + 轮次标记）。
- `[当前轮次] N/3` 标记保留（现状 [:158](../../src/graphs/javatutor/main_agent.py) 已有同类标记），
  避免丢prompt锚点；重复步骤提示文本一字不改。
- 代价：单轮上下文随轮次线性增长（最多 4 轮）。当前 `context_built` 本身是主要体量，
  多出的三份观察均为已渲染的紧凑文本，**可接受**；不引入截断（截断会重新引入「模型看不到自己上一轮」的问题）。

## 5. 影响面

### 5.1 必须改变的行为（有意为之）

| 行为 | 现状 | 改造后 | 依据 |
|---|---|---|---|
| 未知工具 | 文本提示「不可用」并继续 | `deny` + 可读 reason（含可用工具清单） | P1，原则③ |
| `args` 非 dict / 未知键 | 静默 `{}` / 工具内抛 `TypeError` 被捕获 | `invalid_args` / `deny`，门闩层就拦住 | P2，原则② |
| 轮次耗尽 | 兜底道歉，丢弃全部证据 | 收束轮，保住并交付已得证据 | §4.4，原则⑥ |
| 模型可见的对话 | 每轮仅 `[System, Human(context+轮次)]` | 累积的 `System/Human/AI/Human...` 真轨迹 | §4.8，原则⑦ |
| `decision_trace` | 无 `verification` | 新增 `verification` | §4.7，原则⑤ |
| 图节点数 | 11（无环） | 14（含 1 个环） | §4.2 |
| 显式 `fetch` 失败后的评审 | `fetch_context_failed` 落不进 state → `critic` **照常跑** | `fetch_context_failed` 落进 state → 无 steps 时 `critic_skipped=True` | 本节补记 |

> 最后一行是**执行后补记**（2026-09-11）：本条原列在 §5.2 的回归红线里，由 review 的 P1-1 指出
> 实现把它变成了「必须改变」。核对后确认原红线描述的路径在改造前**不可达**——
> HEAD 的 `_handle_fetch` 失败分支只返回渲染文本，不写任何 state 键，所以
> `critic_node` 的 `fetch_context_failed and not has_steps` 短路自 2026-08-30 工具化以来从未触发过。
> 本次补上失败态写入后该路径**首次真正生效**，语义上正确（没拿到证据就不必让 LLM 评审），
> 故按「先改 spec」补记于此，并把 `critic_skipped` 的上升列为合入窗口的**预期**指标变化。

### 5.2 必须不变的行为（回归红线）

- **工具调用率与重复步骤提示**（评测敏感）：P5 保持 `allow`；`step_facts` 前的自动 `fetch` 前置逻辑**原样保留**
  （[main_agent.py:174-177](../../src/graphs/javatutor/main_agent.py)）。
- **`decision_trace` 既有键**：一个不删、不改语义；`【决策痕迹】`/`【编辑建议】`/`【视角导航】` 的位置与格式不变。
- **结构化块契约**：`【编辑建议】` 的 `kind` 分支、`_split_edit_block`（PR #14）**不动**。
- **`analyze` 短路**：`intent=analyze` 直达 END 的既有路径不变。
- **外壳**：`.coze`、`scripts/`、`src/main.py`、`src/storage/`、`src/utils/` **一个字节都不动**。
- **`build_agent(ctx=None)` 暴露 `.builder` 且不 compile**（[local-dev-convention.md](../local-dev-convention.md) 硬约束）。

### 5.3 已知风险与对策

| 风险 | 对策 |
|---|---|
| 队友 `zzmleslie` 正在同一区域工作（`harness` 分支 / PR #14 已改 `critic.py` 的 `revise_node`） | 合入前先 `git log origin/harness` 对账；改动集中在 `main_agent.py`/`graph.py`/新增 `harness/` 包，与 `revise_node` 的编辑块逻辑不相交 |
| 环 + 默认 `recursion_limit=25` | §4.3 已把最坏路径压到 21，并由「病态模型」用例实证（plan Task 11） |
| 图级测试需驱动完整前缀 | 图级用例全部通过 `configurable.chat_model` 注入路由模型（既有 `DeepModel` 写法），不为测试开后门 |
| HITL 开启但无 checkpointer → `interrupt()` 报错 | HITL **默认关**（`COZE_AGENT_HITL` 未设即关）；开启前置条件写进 §6 与 plan 的「遗留」 |

## 6. 外壳改造请求清单（本次不做，需双人评审 + 单独提交）

以下改动全部落在**禁止修改**的 `src/main.py`（或 `.coze`），因此**不在本 plan 的交付范围**；
本节是给「让 HITL 在线上真正可用」准备的请求单，内核已在本 plan 里离线证明。

1. **编译时挂 checkpointer**：`builder.compile(checkpointer=...)`。当前 `build_agent()` 只返回未编译的 `.builder`，
   平台 lifespan 调 `.compile()` 无参 → `interrupt()` 无法工作（LangGraph 强制要求）。
2. **传 `thread_id`**：至少让每轮问答的 `config` 带稳定 `thread_id`（可用 `run_id` + `user_id`），
   否则恢复时找不到 checkpoint。
3. **新增 `/resume` 端点**：接收 `thread_id` + `interrupt` 的 `id` + 用户选择，构造 `Command(resume=<选择>)`
   继续执行并按既有 SSE 契约流式返回。
4. **`recursion_limit`**：`/async_run` 已有设置（[:315](../../src/main.py)），`/run`、`/stream_run` 用默认 25；
   建议统一显式设 40，并把本 spec §4.3 的预算算术写进注释。
5. **开关**：线上启用 HITL 的配置项（`COZE_AGENT_HITL=1` 或 `config/` 内配置）。
6. **（接口契约升级，另开 spec）** 若前端要渲染「待用户选择」卡片，需要把 `__interrupt__` 事件透传到 SSE
   ——属消息契约变更，按 AGENT.md 应先更新 `docs/spec/2026-08-10-coze-agent-interface.md`。

## 7. 验收标准

- 图结构：`guard`/`run_tools`/`verify` 在 `graph.nodes` 中；存在环边 `("run_tools","main_agent")`；`analyze` 短路不变。
- 病态模型（连续 10 次都提工具调用）跑完整图：**不出现 `GraphRecursionError`**，`tool_rounds == 3`，
  `answer` 非空且**不含**工具 JSON（收束轮兜底生效）。
- 未知工具 / 非法参数：得到 `deny` / `invalid_args` 观察（`step_records` 可查），**不抛异常**，`tool_calls` 不含被拒工具。
- HITL 离线：`MemorySaver` 编译图 → 触发 `needs_decision` → 返回 `__interrupt__`（含可选项）→
  `Command(resume="<文件名>")` 后正常收敛，且恢复后的观察携带用户选择。
- HITL 关闭（默认）：同样场景**降级为 `deny`**，不中断、不报错，模型据 reason 自我修正。
- `verification` 出现在 `decision_trace`；无 steps 时 `applicable=False` 且不判罚；
  `tests/test_grounding.py` 一字不改仍全绿。
- 全量门槛：L1 `uv sync --frozen`、L2 `uv run pytest tests/ -v`、**L2.5 `uv run pytest tests/test_eval_component.py -v`（`pass_rate=1.0`）**、
  L3 离线构建、L4 本地 HTTP 冒烟、L5 外壳回归——全绿。

## 8. 不纳入本 spec

- **真 `/resume` HTTP 通道**：属外壳（§6），本次只交付请求清单。
- **`bind_tools` / 原生 function calling**：D3/D9 明确不做。
- **动态轮次预算**：D3 明确不做（先固定 `MAX_ROUNDS=3`，待有评测依据再谈）。
- **`needs_decision` 的其他治理策略**（预算超限确认、高风险工具二次确认等）：注册表留了扩展点，
  但**线上 Resume 通道就绪前，多开策略只会增加挂起风险**，故不列入。
- **`revise`/`critic` 内部逻辑**：PR #14 刚动过（编辑块保留），不在本次范围。
- **前端 `decisionTrace.js` 对新字段的渲染**：见 §4.7 第 3 条，属 `javatutor` 仓。
