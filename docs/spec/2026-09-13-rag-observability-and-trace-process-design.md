# 设计规格：RAG 检索可观测性 + 决策痕迹过程化

> 依据：四轮评测归档 `eval/archive/`（round-1..4）的复盘结论。本文档为设计侧产出，执行见
> `docs/plan/2026-09-13-rag-observability-and-trace-process-plan.md`。
> 一句话：**先让 RAG 的失败可见**（它已经静默瘫痪四轮），再把决策痕迹从「工具调用流水」升级为
> 「完整过程记录」（RAG 候选 + 工具间思考片段）。

## 1. 背景：四轮评测暴露的两个问题

### 1.1 RAG 检索在部署环境中恒返回空（P0，事实缺陷）

**现象**：round-4（2026-09-13）全部 31 条样本的 `decision_trace.sources == []`，同时
`rag_degraded == false`。四轮 `retrieval` 指标（`mrr` / `hit_at_1` / `hit_at_3` / `hit_at_5`）
**全部为 0.0**，分母恒为 17（黄金样本中声明 `expected_sources` 的条数）。

**根因判定（已排除项）**：知识库本身健康——`tools/seed_knowledge.py --stats` 显示 80 条分块，
样本期望的 `HashMap.get` / `ArrayList.get` / `Arrays.sort` 等标签**全部存在**。语料不是问题。

`search_chunks`（`src/learning/knowledge.py:134-155`）的行为是：embedding / pgvector 失败时
**向上抛异常**；`retrieve_knowledge`（`src/graphs/javatutor/nodes.py:334-343`）的 `except` 分支
置 `rag_degraded=True`。因此「`sources` 空 **且** `rag_degraded=false`」唯一可能的解释是：

> embedding 调用成功，但**没有任何 chunk 越过 `DEFAULT_THRESHOLD = 0.3`**。

**未定项（本设计不解，留给诊断数据）**：为何无 chunk 越阈值。三个候选：
1. 查询串被 `context_summary` 稀释——`nodes.py:339` 拼的是 `f"{user_question} {context_summary}"`，
   长源码摘要可能把 embedding 拉离所有条目；
2. `DEFAULT_THRESHOLD = 0.3` 对 1024 维余弦相似度过高（中文短查询 vs 长条目常落在 0.2–0.3）；
3. 灌库与查询的 embedding 模型不一致（同走 `EmbeddingClient`，但部署环境可能有差异），
   向量空间错位导致全票落榜。

**本机限制**：本地 `.env` 的 `COZE_API_TOKEN` 已失效（embedding 报 `code=190000007 no permission`），
**无法本地复现**，因此只能靠给部署侧加可观测性来拿数据。这是本设计采用「诊断先行」的直接原因。

### 1.2 指标未进汇总，缺陷得以隐藏四轮（P1，口径缺陷）

`retrieval` 指标只存在于 `tools/eval_cli.py retrieval` 子命令，`rag_hit_at_3` / `citation_accuracy`
只存在于 component 评测（`eval/runner/component_metrics.py`），而：
- component 评测四轮都是 `component: {}`（**从未运行**）；
- `retrieval` 子命令的输出**不写入 `summary.json`**。

结果：**只看 `summary.json` 完全看不到 RAG 退化**。这是「指标烂了四轮无人知」的结构性原因，
比单个 bug 更值得修。

### 1.3 决策痕迹信息量不足（P2，能力缺口）

当前 `build_final`（`nodes.py:466-506`）产出的 `decision_trace` 含 16 个键，其中：
- `sources` 只发 `{source, score}`，**丢掉 `content` / `chunk_index`**，且**不含查询串与被阈值滤掉的候选**；
- 完全没有 AI 的中间思考——`state["agent_messages"]` 里**累积保存了每轮的模型原始输出**（见 §2.1），
  但 `build_final` 从不读取它。

用户诉求：痕迹不仅要有工具调用，还要有 **RAG 查询情况** 与 **工具调用之间的 AI 思考片段**；
不要求流式输出，但要求**完整过程**。

## 2. 现状实现事实（写计划前必须确认的机制）

### 2.1 中间思考已被保留，只是从未被序列化

`harness/propose.py:82-123` 每轮把模型原始输出追加进 `agent_messages`：

```python
out_messages = history + [AIMessage(content=resp)]   # propose.py:104
```

`run_tools_node`（`harness/tools_node.py:160-166`）把观察渲染成**一条** `HumanMessage` 追加，
以维持严格交替：

```
System → Human → AI → Human → AI → ...   （tools_node.py:161-166 的注释明确此不变量）
```

因此 `agent_messages` **已是完整的 ReAct 轨迹**，`reasoning` 只需按序 filter 出 `AIMessage`。
改动面因此很小——这是本设计可行性的关键前提。

### 2.2 `sources` 的现有消费方（改 schema 必须不破坏）

`eval/runner/retrieval_metrics.py:24` 读 `decision_trace.sources[*].source` 算 MRR / hit@k。
**`sources` 的既有键与语义必须保持兼容**（只增键、不改键）。

### 2.3 阈值过滤发生在 `search_chunks` 内部（诊断的障碍）

`knowledge.py:151-155` 在函数内就 `if float(row[3]) >= threshold` 过滤掉了低分候选，
**调用方拿不到被滤掉的行**。所以「检索没召回到」与「召回到了但被阈值滤掉」在现有代码里
**不可区分**——这正是 §1.1 无法直接定案的技术原因。诊断必须先移除这个盲区。

### 2.4 体积与截断

`build_final` 是「唯一流式输出」节点（`nodes.py:469-470` 的 docstring 明确），中间内容不会外泄，
所以「不流式」是天然满足的。

> **2026-09-13 review 更正**：「唯一流式输出」「中间内容不会外泄」**不成立**
> （见 `docs/reviews/2026-09-13-process-streaming-and-strip-leading-tool-json-review.md` §1.1）：
> `stream_mode="messages"` 会转出节点返回值里**所有键**的消息，`agent_messages` 在内，
> 故 `propose` 的提案 JSON 等中间内容**确实会**流到客户端。
> 本节的**结论不受影响**——`reasoning` 只进 `decision_trace`（回答尾部），
> 不需要、也没有被单独流式推送。但 `reasoning` 会显著放大回答尾部（当前 trace 约 600 字符，
加 2–3 轮思考可能到 3–5 KB）。需显式截断并**记录截断标志**，不做静默裁剪。

## 3. 设计方案

### 3.1 检索层：暴露全量候选（诊断的直接抓手）

`search_chunks` 增加「不过滤」的返回通道。为保持既有调用方零改动，**不改 `search_chunks` 的
默认行为**，而是新增一个返回全量候选的函数：

```python
def search_chunks_debug(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
    embedder: Callable = embed_texts,
    fetcher: Callable = _fetch_similar,
) -> dict[str, Any]:
    """检索并返回**全量候选**与阈值判定，供决策痕迹诊断。

    与 ``search_chunks`` 的差别：不过滤低分候选，并把 best_score / kept 一并带回，
    使「没召回到」与「召回到但被阈值滤掉」在痕迹里可区分（见 spec §2.3）。
    """
```

返回：

```python
{
    "query": query,
    "top_k": top_k,
    "threshold": threshold,
    "candidates": [
        {"source": ..., "chunk_index": ..., "score": ..., "content": ..., "kept": bool}
    ],
    "best_score": 0.0,     # 无候选时为 0.0
    "kept": 0,             # 越阈值的条数（= len(search_chunks(...))）
}
```

`retrieve_knowledge` 改为同时写两个 state 字段：既有的 `retrieved_chunks`（越阈值，行为不变）
与新增的 `retrieval_debug`（全量候选）。**既有 `retrieved_chunks` 的语义与消费方一律不变。**

### 3.2 决策痕迹：三个新增键

在 `decision_trace` 中新增：

```jsonc
{
  // 新增：RAG 检索全过程（含被阈值滤掉的候选）
  "retrieval": {
    "query": "HashMap 的 get 原理是什么",
    "top_k": 3,
    "threshold": 0.3,
    "candidates": [
      {"source": "知识库: HashMap.get", "chunk_index": 0, "score": 0.28,
       "preview": "HashMap.get\n关键词: ...", "kept": false}
    ],
    "best_score": 0.28,
    "kept": 0
  },

  // 新增：工具调用之间的 AI 思考片段（按轮次，完整过程）
  "reasoning": [
    {"round": 0, "content": "<模型第 1 轮原始输出>", "tool_calls": ["fetch_execution_context"]},
    {"round": 1, "content": "<模型第 2 轮原始输出>", "tool_calls": ["step_facts"]}
  ],

  // 增强：既有 sources 只增键，不改既有键
  "sources": [{"source": "...", "score": 0.28, "chunk_index": 0,
               "content_preview": "..."}]
}
```

**契约约束**：
- `sources` 的 `source` / `score` 键与类型**不变**（`retrieval_metrics.py` 依赖）。
- `retrieval` 与 `reasoning` 是**新增键**，老解析方（前端 `parseAssistantMessage` 的通用分支、
  `e2e_remote.parse_decision_trace`）遇到未知键应忽略而非报错——已确认二者都是「取所需键」的写法。
- `rag_degraded` 语义不变：仅在后端**失败**时为 `true`。**不因「越阈值 0 条」置位**——
  那是「检索成功但无匹配」，与「检索故障」是两回事，混同会让 P0 的诊断信号失真。

### 3.3 `reasoning` 的构造

在 `build_final` 中新增一个纯函数（便于单测，不依赖图）：

```python
def build_reasoning(messages, max_chars: int = 1200) -> tuple[list[dict], bool]:
    """从 agent_messages 提取 AI 中间思考（按序），返回 (reasoning, truncated)。

    只取 AIMessage；每条 content 按 max_chars 截断，超长置 truncated=True。
    """
```

- `round` 用 AI 消息的出现序号（0-based）。
- `tool_calls` 取该轮之后紧跟的那条 `HumanMessage` 之前，模型输出里解析出的工具名
  （复用 `harness/contracts.py::parse_action`；解析不出则为空列表）。
- **截断必须显式**：`max_chars` 默认 1200，超长在 trace 顶层加 `reasoning_truncated: true`。

> **2026-09-14 口径变化（联调修复 D1/Task 5）**：`propose` 的**终答轮与收束轮不再把
> 模型原文追加进 `agent_messages`**（见 `2026-09-13-process-streaming-design.md` §2.1 的
> 状态更新）。本函数是「按序 filter `AIMessage`」，故 `reasoning` **少一条**——
> 即末尾那次「直接给出终答」的输出不再作为一条思考片段。
> **这是更正确的语义**：终答不是「工具调用之间的思考」，且它此前以 `answer` delta
> 重复流给客户端。既有断言若依赖「末条 = 终答」，须同步改写。

### 3.4 指标接线（P1，防复发的结构性修复）

- `tools/eval_cli.py report` 在算 `extended` 时**并入** `compute_retrieval_metrics`，
  使 `mrr` / `hit_at_1` / `hit_at_3` / `hit_at_5` 进入 `summary.json` 的 `e2e`。
- `retrieval` 子命令保留（独立排查用）。
- component 评测是否随每轮运行，**不在本设计范围**（涉及评测流程约定），仅在 §5 记为遗留。

### 3.5 前端呈现（最小）

`frontend/src/utils/decisionTrace.js` 的 `formatToolCall` 与 `splitDecisionTrace` 不改也能跑
（未知键不渲染）。本次**只加一个「思考过程」折叠区**，默认收起，展开显示 `reasoning` 各轮
content 与 `retrieval` 的候选表。**不做流式**。若前端改动超出折叠区所需，另开任务。

## 4. 影响面

| 层 | 文件 | 改动性质 |
|---|---|---|
| 检索 | `src/learning/knowledge.py` | 新增 `search_chunks_debug`（既有函数不动） |
| 图 | `src/graphs/javatutor/nodes.py` | `retrieve_knowledge` 增写 `retrieval_debug`；`build_final` 增三键；新增 `build_reasoning` |
| 状态 | `src/graphs/javatutor/state.py` | 新增 `retrieval_debug: dict` 字段 |
| 评测 | `tools/eval_cli.py` | `report` 并入 retrieval 指标 |
| 前端 | `frontend/src/utils/decisionTrace.js` + 面板 | 思考过程折叠区 |
| 契约 | `docs/agent-collaboration-guide.md` | `【决策痕迹】` 段落补三键说明（**必须**，见 AGENT.md 规约） |

**不改**：`search_chunks` 既有签名与语义、`retrieved_chunks` 的消费方、`rag_degraded` 语义、
`tool_calls` 的结构（`{tool, args, result}`）、外壳目录。

## 5. 非目标与遗留

- **不**在本设计内决定阈值 / 查询构造的最终改法——那要等 `retrieval.candidates` 的
  真实分数分布（诊断先行）。拿到数据后另开 spec 修订或直接按数据调参。
- **不**让 component 评测随轮运行（流程约定变更，另议）。
- **不**解决 token 翻倍（四轮 1549.8 → ~3000）；round-4 质量/延迟双优，该成本暂判为值得。
- **不**动 q28 的 `expected_tool_calls: []`（已核，符合 `other` 契约）。
- 本设计**不**触碰两仓 git 状态；javatutor 侧未提交改动与本设计无关。

## 6. 验收标准

1. 一次带 `expected_sources` 的 concept 提问，`decision_trace.retrieval` 含
   `query` / `candidates`（**即使 `kept == 0` 也必须有 candidates**）/ `best_score`。
2. `decision_trace.retrieval.candidates[*].kept` 能区分「被阈值滤掉」与「未召回」。
3. 一次触发工具调用的提问，`decision_trace.reasoning` 含 ≥1 条，且各条 `content` 即模型该轮
   原始输出；超长时 `reasoning_truncated == true`。
4. 既有 `sources[*].source` / `score` 不变，`retrieval_metrics` 四档指标仍可算（数值可能从 0 变正）。
5. `rag_degraded` 在「检索成功但 0 条越阈值」时仍为 `false`（不被误置）。
6. `summary.json` 的 `e2e` 内出现 `mrr` / `hit_at_1` / `hit_at_3` / `hit_at_5`。
7. 前端展开「思考过程」可读到 reasoning 各轮与 retrieval 候选；不展开时版面与现状一致。
8. `uv run pytest tests/ -q` 全绿（基线 329 通过）。
