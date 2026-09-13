# 实施计划：RAG 检索可观测性 + 决策痕迹过程化

> 依据：`docs/spec/2026-09-13-rag-observability-and-trace-process-design.md`（本计划是其 TDD 落地）。
> 分工：设计侧产出本文档，执行由执行组完成。
> 交付边界：到离线全绿为止（L1–L5 + 组件级）；「重新发布 agent + 重跑一轮取 RAG 分数分布」
> 见 §Task 9，由执行组在合入窗口完成。

## 0. 全局约束（务必遵守）

- **不做任何 git 操作**（不 `git add`/`commit`/`push`/`stash`/`checkout`/`branch`/`merge`）。
  读 `git log`/`git status`/`git diff` 可以。
- **外壳一个字节都不改**：`.coze`、`scripts/`、`src/main.py`、`src/storage/`、`src/utils/`。
- 禁止 `from src.xxx import`；业务代码只允许新增到 `src/agents/`、`src/graphs/`、`src/learning/`、
  `src/tools/`、`tools/`、`assets/`、`config/`、`tests/`、`docs/`。
- **不引入新依赖**，不改 `pyproject.toml`/`uv.lock`。
- **不动既有语义**：`search_chunks` 的签名与行为、`retrieved_chunks` 的消费方、`rag_degraded` 语义、
  `tool_calls` 的 `{tool, args, result}` 结构、`sources[*].source`/`score` 键。**只增不改。**
- 基线（改动前先跑一遍记数）：`uv run pytest tests/ -q` 应 **329 passed**（本机实测 2026-09-13）。
- 不触碰 `javatutor/frontend/src/backup-20260807/`。
- 开工前对账队友分支：确认没有新改动落到 `nodes.py::build_final` / `knowledge.py`（本计划的改动面）。

---

## Task 1：检索层暴露全量候选（诊断抓手）

**先写测试** `tests/test_knowledge.py`（追加，不改既有 4 个用例）：

- `search_chunks_debug("查询", threshold=0.5, embedder=fake_embed, fetcher=fake_fetch)`
  （fetcher 返回 `[("知识库: A", 0, "内容A", 0.8), ("知识库: B", 0, "内容B", 0.2)]`）：
  - `result["candidates"]` 长度 **2**（低分的也被带回）；
  - `candidates[0]["kept"] is True`、`candidates[1]["kept"] is False`；
  - `result["kept"] == 1`、`result["best_score"] == 0.8`；
  - `result["threshold"] == 0.5`、`result["query"] == "查询"`。
- 空查询：`search_chunks_debug("")` → `candidates == []`、`best_score == 0.0`、`kept == 0`。
- **等价性守卫**：对同一 fake 依赖，`search_chunks_debug(...)["kept"] == len(search_chunks(...))`，
  且两者被保留的 `source` 集合一致（防止两条路径漂移）。
- 后端失败：`embedder` 抛 `RuntimeError` 时 `search_chunks_debug` **同样向上抛**（不吞）。

**实现** `src/learning/knowledge.py`：新增 `search_chunks_debug`（见 spec §3.1 的签名与返回结构）。
- `candidates[*].content` 与 `preview` 二选一即可，**实现用 `content`**，由 `build_final` 侧做
  `preview` 截断（保持检索层不做表现层决策）。
- **不重构** `search_chunks` 去复用它——两者行为差异（过滤与否）是本质的；
  只共用一个内部的「取原始行」小函数即可，避免重复 `embedder`/`fetcher` 调用逻辑。

**验证**：`uv run pytest tests/test_knowledge.py -v` 全绿。

---

## Task 2：状态字段与图节点接线

**先写测试** `tests/test_graph.py`（追加）：

- 走一次带 `user_question` 的完整图调用（复用既有 fixture/桩的写法），断言
  `out["retrieval_debug"]` 存在且含 `query` / `candidates` / `best_score` / `kept` 四键。
- 断言 `out["retrieved_chunks"]` 的结构与语义**未变**（既有断言不得修改）。
- 检索后端抛异常时：`rag_degraded is True` **且** `retrieval_debug["candidates"] == []`
  （失败时无候选，但字段仍存在，便于区分「失败」与「成功但空」）。

**实现**：
1. `src/graphs/javatutor/state.py`：在 `retrieved_chunks`（:70-71）附近新增
   `retrieval_debug: dict`，docstring 注明「RAG 全量候选与阈值判定，供决策痕迹诊断；
   与 `retrieved_chunks`（越阈值结果）分开，前者含被滤候选」。
2. `src/graphs/javatutor/nodes.py::retrieve_knowledge`（:334-343）：
   - 成功分支改为同时返回 `{"retrieved_chunks": ..., "retrieval_debug": ..., "rag_degraded": False}`。
   - `retrieved_chunks` 仍取 `search_chunks(...)` 的结果（**不改**其来源与语义）；
     `retrieval_debug` 取 `search_chunks_debug(...)`。
   - 为不重复一次 embedding 调用（成本），**优先**用一次 `search_chunks_debug` 的
     `candidates` 派生 `retrieved_chunks`：`[c for c in candidates if c["kept"]]`，
     但**必须**保证与 `search_chunks` 结果等价（Task 1 的等价性守卫覆盖此点）。
     若实现后发现等价性难以保证，退回两次调用（正确性优先，成本可接受）。
   - 失败分支：`{"retrieved_chunks": [], "retrieval_debug": {"candidates": []}, "rag_degraded": True}`。

**验证**：`uv run pytest tests/test_graph.py tests/test_knowledge.py -v` 全绿。

---

## Task 3：`build_reasoning` 纯函数

**先写测试** `tests/test_build_reasoning.py`（新建）：

- 输入 `[SystemMessage(...), HumanMessage(...), AIMessage("想法A"), HumanMessage("观察"), AIMessage("想法B")]`
  → `reasoning` 长度 **2**，`round` 为 `0`/`1`，`content` 分别为 `"想法A"`/`"想法B"`。
- 工具名提取：`AIMessage('{"tool":"step_facts","args":{"step_index":1}}')`
  → 该条 `tool_calls == ["step_facts"]`；纯散文 `AIMessage("直接作答")` → `tool_calls == []`。
- 截断：`max_chars=5` 且 content 为 10 字 → `content` 长度 5 且返回的 `truncated is True`；
  未超长时 `truncated is False`。
- 空输入 `[]` → `([], False)`；无 AI 消息 → `([], False)`。

**实现** `src/graphs/javatutor/nodes.py`：新增 `build_reasoning(messages, max_chars=1200) -> tuple[list, bool]`。
- 只取 `AIMessage`；`round` 为 AI 消息出现序号。
- `tool_calls` 复用 `harness/contracts.py::parse_action`；返回 `Action` 时取其 `tool`，
  否则 `[]`（`ParseError` / `None` 都归 `[]`）。
- **不在此函数里读 state**，只吃 `messages`，保证可单测。

**验证**：`uv run pytest tests/test_build_reasoning.py -v` 全绿。

---

## Task 4：`build_final` 增三键

**先写测试** `tests/test_build_final.py`（追加，不改既有 17 个用例）：

- `state` 含 `retrieval_debug` 时，`trace["retrieval"]` 存在且：
  - 含 `query` / `top_k` / `threshold` / `candidates` / `best_score` / `kept`；
  - `candidates[*]` 含 `source` / `chunk_index` / `score` / `preview` / `kept`，**不含完整 `content`**
    （preview 由 `[:300]` 截断，且超长时该字段标 `truncated`）。
- `state` 含 `agent_messages`（两次 AI 输出）时 `trace["reasoning"]` 长度 2；
  超出 `max_chars` 时顶层 `reasoning_truncated is True`。
- **`sources` 兼容性**：既有断言（`source` / `score`）不改；新增断言
  `sources[0]` 同时含 `chunk_index` 与 `content_preview` 两个**新键**。
- **`rag_degraded` 不被误置**：`retrieval_debug` 有候选但 `kept == 0` 时，
  `trace["rag_degraded"] is False`。
- `state` 无 `retrieval_debug` / 无 `agent_messages` 时，`trace["retrieval"]` 为
  `{"candidates": [], "best_score": 0.0, "kept": 0}`（**恒存在**，便于消费方无条件读）；
  `trace["reasoning"] == []`。

**实现** `src/graphs/javatutor/nodes.py::build_final`（:466-506）：
- `trace["retrieval"]` 由 `state["retrieval_debug"]` 构造（`content` → `preview` 截 300，
  加 `truncated` 标志；`candidates` 逐条转换）。
- `trace["reasoning"], trace["reasoning_truncated"] = build_reasoning(state.get("agent_messages") or [])`。
- `trace["sources"]` 在既有 `{source, score}` 基础上**增** `chunk_index` 与 `content_preview`
  （从 `retrieved_chunks` 取，`content[:300]`）。
- **`rag_degraded` 一行不改**。
- 注意 `trace_json` 用 `separators=(",", ":")`（:504）——保持紧凑，勿改。

**验证**：`uv run pytest tests/test_build_final.py -v` 全绿。

---

## Task 5：评测侧指标接线（P1 防复发）

**先写测试** `tests/test_eval_report.py`（追加）：

- 构造含 `decision_trace.sources` 的 outputs 与含 `expected_sources` 的 samples，
  调 `report` 的路径后断言 `summary["e2e"]` 内出现 `mrr` / `hit_at_1` / `hit_at_3` / `hit_at_5`，
  且数值与 `compute_retrieval_metrics` 直接调用一致。
- 无 `expected_sources` 的样本不计入分母（`total` 语义不变）。

**实现** `tools/eval_cli.py::cmd_report`（:105-144）：
- 在 `extended` 组装处并入 `compute_retrieval_metrics(outputs, samples)`
  （与既有 `compute_grounding_verify` / `compute_per_tool_metrics` 同位置、同风格）。
- **不**删除 `retrieval` 子命令。

**验证**：`uv run pytest tests/test_eval_report.py -v` 全绿；
再用已有归档实跑一次 `uv run python tools/eval_cli.py --round-dir eval/archive/2026-09-13/round-4 report`
（**只读答案数据、会写该目录的 report/summary**，属既有行为）确认 `e2e` 内有四档指标。

---

## Task 6：前端「思考过程」折叠区

**先写测试** `frontend/src/utils/decisionTrace.test.js`（追加）：

- 解析含 `retrieval` / `reasoning` 的 trace：返回结构中两者可读；
- trace **不含**新键（老数据）时：`reasoning` 归 `[]`、`retrieval` 归空对象，**不抛错**。

**实现**：
1. `frontend/src/utils/decisionTrace.js`：`splitDecisionTrace` 的返回增 `reasoning` / `retrieval`
   两个字段（缺省容错），`formatToolCall` **不改**。
2. 在渲染决策痕迹的组件里加**可折叠**区（默认收起），展开显示：
   - `reasoning`：各轮 `round` + `content`（`truncated` 时标「已截断」）；
   - `retrieval`：`query` / `threshold` / `best_score` 摘要 + `candidates` 表
     （`source` / `score` / `kept`）。
3. **不做流式**。改动**仅限**折叠区所需；若需要动 `AiTutorPanel.vue` 的大结构，拆成单独任务。

**验证**：`npm test`（在 `javatutor/frontend`）全绿；手动展开确认读取正确。

---

## Task 7：契约与文档同步

1. `docs/agent-collaboration-guide.md` 的「输入输出」段落（`【决策痕迹】` 那句）补上三个新键
   的说明：`retrieval`（含 `candidates` / `best_score` / `kept`，**明确它含被阈值滤掉的候选**）、
   `reasoning`（工具间思考，超长有 `reasoning_truncated`）、`sources` 新增的
   `chunk_index` / `content_preview`。**必须**——AGENT.md 规约要求图节点输入输出变更同步此文件。
2. `docs/dev-eval-guide.md` 的评测侧 schema 段落补 `e2e` 内新增的四档检索指标与
   `summary.json` 口径说明。

---

## Task 8：全量回归

- `uv run pytest tests/ -q` → 期望 **329 + 新增用例数**，全绿，0 failed。
- `cd javatutor/frontend && npm test` → 全绿。
- 抽查一份新跑的 `answers.jsonl`，人工确认 `retrieval.candidates` 在 `kept == 0` 时**非空**
  （这是本计划的核心验收点，见 spec §6.1）。

---

## Task 9：重发 + 取诊断数据（合入窗口，执行组）

**本 Task 不做任何调参判断**——只取数据。

1. 在 Coze 平台重新发布 agent（`javatutor-coze` 侧改动需重发才生效）。
2. 重跑一轮：`uv run python tools/eval_cli.py --round-dir eval/archive/<date>/round-5 run`（远端采集）
   → `judge` → `report`。
3. 导出 17 条 `expected_sources` 样本的 `decision_trace.retrieval`，汇总 `best_score` 分布。
4. 据分布判定 §1.1 的三个候选根因（查询稀释 / 阈值过高 / embedding 不一致），
   **另开 spec 修订**给结论与改法。**不在本计划内直接改阈值或查询构造。**

---

## 交付清单

| # | 文件 | 类型 |
|---|---|---|
| 1 | `src/learning/knowledge.py` | 新增 `search_chunks_debug` |
| 2 | `src/graphs/javatutor/state.py` | 新增 `retrieval_debug` |
| 3 | `src/graphs/javatutor/nodes.py` | `retrieve_knowledge` 接线；`build_reasoning`；`build_final` 三键 |
| 4 | `tools/eval_cli.py` | `report` 并入检索指标 |
| 5 | `frontend/src/utils/decisionTrace.js` + 折叠区组件 | 思考过程呈现 |
| 6 | `docs/agent-collaboration-guide.md`、`docs/dev-eval-guide.md` | 契约同步 |
| 7 | `tests/`：`test_knowledge.py`、`test_graph.py`、`test_build_reasoning.py`（新建）、`test_build_final.py`、`test_eval_report.py` | TDD 用例 |

## 风险与回退

- **等价性风险**（Task 2）：用一次 `search_chunks_debug` 派生 `retrieved_chunks` 可能破坏等价性。
  回退：改回两次独立调用（正确性优先）；Task 1 的等价性守卫测试即为此设。
- **体积风险**（Task 4）：`reasoning` 放大 trace。已用 `max_chars=1200` + `reasoning_truncated`
  兜底；若实测 trace 超 8KB，下调 `max_chars`（改常量即可，不改结构）。
- **前端风险**（Task 6）：老数据无新键。已用缺省容错覆盖，且折叠区默认收起，版面不变。
