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

## 6. 遗留问题（非本修复范围，需单独处理）

1. **q14（ArrayList）无 KB chunk**：`java_std.json` 没有 ArrayList 条目，`知识库: ArrayList` 永不命中。需向知识库补一个 ArrayList 条目（或改样本）。
2. **round-2 `decision_trace.sources` 全空**：`build_final` 从 `state.retrieved_chunks` 取来源，但 round-2 每条都为空，说明部署链路里 RAG 检索结果没进 state（或未记录到 trace）。在来源未记录前，`expected_sources` 只是标签修复，`compute_retrieval_metrics`（MRR/hit@k）无法在 round-2 上得到有效值。

## 7. 涉及文件

- `eval/samples/golden_set.jsonl`（期望工具调用 + RAG 标签）
- `tests/test_eval_report.py`（新增 `test_per_tool_metrics_fetch_first_sequence_counted`、`test_per_tool_metrics_missing_fetch_surfaces_as_low_accuracy`）
- `eval/archive/2026-09-6/round-2/summary.json`、`report.md`（重新生成）
