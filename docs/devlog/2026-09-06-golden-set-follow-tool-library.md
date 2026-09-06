# 评测黄金样本未跟随新工具库 / RAG 的修复（2026-09-06）

> 一句话：`golden_set.jsonl` 的 `expected_tool_calls` 停留在 `fetch_execution_context` 工具化之前，只期望单步 `step_facts`；RAG 侧 `expected_sources` 的标签也早已与 `assets/knowledge/` 实际 chunk 源不对齐。本次按设计契约与实证结果校准样本，使各工具调用率与检索命中率能真实反映当前 Agent 行为。

## 1. 现象

对 `2026-9-6/round-2` 跑 `report` 后，各工具调用情况里出现两个可疑信号：

| 工具 | 期望 | 实际 | 正确 | 准确率 | 误用 |
|---|---|---|---|---|---|
| `fetch_execution_context` | 0 | 4 | 0 | - | 4 |
| `step_facts` | 16 | 15 | 10 | 0.625 | 0 |

- `fetch_execution_context`（新工具）在 `expected`=0 却被调用 → 全部判为「误用」。这与需求相反：该工具本就是 `2026-08-30` 设计中被 agent 自由调用的读取工具（见 `docs/spec/2026-08-30-fetch-execution-context-as-tool-design.md`）。
- `step_facts` 准确率偏低，因为模型按 prompt 典例传了 `{"step_index": 1, "line": 4}`（含 `line`），而 gold 只期望 `{"step_index": 1}`，导致 args 精确匹配失败。

## 2. 根因

1. **gold 早于工具化**：`expected_tool_calls` 仍只列 `step_facts`，与 08-30 设计「回答需要代码或执行证据的问题前应先调用 `fetch_execution_context`」的契约不符。
2. **契约典例含 `line`**：`prompts.py` 的 `SYSTEM_PROMPT_MAIN_AGENT` 给出的调用典例是 `{"tool": "step_facts", "args": {"step_index": 1, "line": 4}}`，模型照做了，gold 却没含 `line`。
3. **RAG 标签过时**：`expected_sources` 用 `知识库: HashMap`、`知识库: JavaTutor项目` 等，但 `src/learning/knowledge.py::seed_assets` 实际给 `.json` chunk 打的是 `知识库: {entry.title}`（如 `知识库: HashMap.get`、`知识库: JavaTutor 产品能力`）。这些标签要么不完整、要么根本不存在，永远命中不了。

## 3. 实证依据（为何 fetch 应被期望）

直接看 round-2 的 judge 结果与工具序列：

| 样例 | 工具序列 | 评分 | 判定 |
|---|---|---|---|
| q06 | step_facts → **fetch** | 3.5 | partially_correct |
| q07 | step_facts → **fetch** | 4.25 | **correct** |
| q24 | step_facts → **fetch** | 3.5 | partially_correct |
| q01–q05 q08–q12 | step_facts（无 fetch） | 1.5–3.0 | incorrect / partially_correct |

结论：只调 `step_facts` 时大概率答错（缺整段代码上下文，解释不了「为什么」）；`step_facts` + `fetch` 明显更好。因此把 `fetch_execution_context` 作为需要执行证据样本（data_query、运行时 debug）的**期望首调**是正确标准，不是过度收紧。

## 4. 修复

### 4.1 工具调用（`eval/samples/golden_set.jsonl`）

对每条「已期望 `step_facts`」的样本（data_query q01–q12、运行时 debug q22–q25），改为：

```json
[
  {"tool": "fetch_execution_context", "args": {}},
  {"tool": "step_facts", "args": {"step_index": <0-based>, "line": <该步行号>}}
]
```

`step_index` 沿用原值，`line` 取自 payload 中该步的 `line`。改动 16 条。

未加 `fetch` 的类别（有理由）：编译错误 debug（q19–q21、q26）与 concept/other/analyze，本就无需执行证据，round-2 这些样本未调用工具也能答对（评分 3.0–4.0），保持一致不加。

### 4.2 RAG 来源（`eval/samples/golden_set.jsonl`）

按 `assets/knowledge/` 实际 chunk 源修正标签（4 条）：

| 样本 | 旧 | 新 |
|---|---|---|
| q13 | `知识库: HashMap` | `知识库: HashMap.get` |
| q27 | `知识库: JavaTutor项目` | `知识库: 运行与提问工作流` |
| q28 | `知识库: JavaTutor项目` | `知识库: 算法可视化引导` |
| q29 | `知识库: JavaTutor项目` | `知识库: JavaTutor 产品能力` |

q27–q29 取的是最贴近语义的现有 chunk，属 best-effort，可按实际检索结果再精调。

## 5. 修复后的各工具调用率（round-2）

```
fetch_execution_context   expected=16  called=4  correct=4  accuracy=0.25  unexpected=0
step_facts                expected=16  called=15 correct=15 accuracy=0.9375 unexpected=0
```

- 「误用」信号消失（unexpected=0）。
- `step_facts` 准确率回到 0.94。
- **暴露真实缺口**：`fetch_execution_context` 准确率仅 0.25 —— 16 个需读上下文的样本里模型只调了 4 次。这正是需要优化的行为：模型没先 `fetch` 就读执行证据。

`report` 已用新 gold 重新生成：`eval/archive/2026-09-6/round-2/summary.json`、`report.md`。

## 6. 补充知识库条目（q14 ArrayList）

`java_std.json` 原本没有 ArrayList 条目，导致 q14 的 `知识库: ArrayList` 永不命中。已在 `PriorityQueue` 之后补 3 个条目：

- `ArrayList.get`（O(1) 随机访问，直接对应 q14「ArrayList 的 get 复杂度」）
- `ArrayList.add`（摊还 O(1)）
- `ArrayList.set`（O(1)）

并把 q14 的 `expected_sources` 修正为 `知识库: ArrayList.get`（与 `seed_assets` 的 `知识库: {title}` 标签规则一致）。校验后所有 `expected_sources` 均为合法 chunk 标签。

## 7. round-2 `sources` 全空的根因分析与修复

### 现象
- 每条 `decision_trace.sources = []`，但 `rag_degraded = False`。
- 矛盾点：RAG 正常但无相关结果 ≠ 有降级标志，二者都对不上。

### 根因（已确认）
1. `retrieve_knowledge`（[nodes.py](../../src/graphs/javatutor/nodes.py#L325-L334)）只在 `search_chunks` **抛异常**时置 `rag_degraded=True`。
2. 但 `search_chunks`（[knowledge.py](../../src/learning/knowledge.py#L132-L151)）自己用 `try/except` **吞掉了 Coze EmbeddingClient 与 pgvector 的所有异常并返回 `[]`**，从不向外抛。
3. 因此 `retrieve_knowledge` 的 except（降级）是**死代码**——`rag_degraded` 永远 False，真实失败被静默掩盖。
4. 本机验证：`.env` 无 `PGDATABASE_URL`，`search_chunks("...")` 返回 0 条且不抛；`retrieve_knowledge` 输出 `rag_degraded=False`。

即：**RAG 后端（Coze embedding + pgvector 数据库）在部署链路里不可达/未配置，`search_chunks` 返回空，但降级标志从未触发，故 `sources` 全空且 `rag_degraded=False`。**

> 另：q13 的 `intent` 被判为 `data_query`（实为概念题），可能把概念样本引向 step_facts/fetch 而非 RAG，属独立的意图分类偏差，叠加干扰了 RAG 可见性。

### 修复
让 `search_chunks` 在 embedding/查询后端失败时**向上抛**，交给 `retrieve_knowledge` 的 except 置 `rag_degraded=True`，失败即写进决策痕迹（`rag_degraded`），不再静默。改动 `src/learning/knowledge.py`，并加测试 `test_search_chunks_propagates_backend_error`。

本机验证（无 DB）：`retrieve_knowledge` 现在输出 `rag_degraded=True, retrieved_chunks=[]`。

> 运行时仍需在部署环境配置 `PGDATABASE_URL`（或保证 Coze EmbeddingClient 可用），否则 RAG 依然拿不到数据——但至少现在会明确降级，而不是无声返回空。

## 8. 涉及文件

- `eval/samples/golden_set.jsonl`（期望工具调用 + RAG 标签 + q14 标签）
- `assets/knowledge/java_std.json`（补 ArrayList.get/add/set 3 条目）
- `src/learning/knowledge.py`（`search_chunks` 失败向上抛，让降级信号可见）
- `tests/test_eval_report.py`、`tests/test_knowledge.py`（新增测试）
- `eval/archive/2026-09-6/round-2/summary.json`、`report.md`（重新生成）
