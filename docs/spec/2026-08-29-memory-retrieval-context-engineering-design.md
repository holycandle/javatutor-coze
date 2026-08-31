# 记忆检索上下文工程设计（Memory Retrieval as Context Engineering）

## 1. 背景与目标

JavaTutor 教学 agent 的可调用工具偏少，讨论加工具。经分析，真正的问题是**各信息源该走哪条路**：

- 知识检索（RAG）当前已由确定性节点 `retrieve_knowledge` 预取，经 `build_context` 注入主模型上下文。
- 会话记忆当前由 `load_session` 预取，同样经 `build_context` 注入。
- 单步执行证据由 `step_facts` 作为**唯一** LLM 工具按需（JIT）获取。

本设计确认并固化一条原则：**知识 + 记忆走「上下文工程」预取；执行证据走「JIT 工具」按需取。** 在此原则下，发现并修复记忆检索的一个实际缺口——记忆目前只按「重要性 + 新近性」排序，不按「与当前问题的相关性」挑选。

## 2. 决策记录：为什么不是工具

| 备选 | 结论 | 依据 |
|---|---|---|
| 把 `search_knowledge` 暴露成 agent 工具 | **不做** | RAG 是「小且固定」的数据（预取便宜、确定性、可核查、省轮次）。按上下文工程原则应预取，不暴露工具。参见「上下文工程 vs 提示工程」与 JIT/预加载二分。 |
| 把整套 `MemoryTool`（add/search/forget/consolidate + 四类记忆）暴露成工具 | **不做** | 与上述 RAG 选择自相矛盾（记忆与知识共用一套引擎）。四类记忆 + 图谱 + 多模态对该「单轮 Java 教学问答」是过拟合——它不是跨多天的代码库维护 agent；每轮被 `run_id` 的源码 + steps + 当前行完整喂饱。另见「最小可行工具集 MVTS」：臃肿工具集会让模型选不对（「人类工程师都说不准用哪个工具，别指望 Agent 选得更好」）。 |
| `read_code(selector)` 工具 | **不做** | `build_context` 已把 `source_code` 注入上下文（`context_builder.py` `gather()` 的 `### 源代码` 包，relevance=0.8）。对常见短教学代码（十几行）它能进窗口，`read_code` 纯冗余。真正风险是「长代码被 token 预算挤出窗口」——那是**上下文工程**问题（提权/分片），不是加工具；而且已有 JIT 工具 `step_facts`。 |
| 记忆检索升级（本设计范围） | **做** | 让预取的记忆更贴合当前问题，而非只按重要性。 |

## 3. 当前实现与缺口

### 3.1 记忆存储（`src/learning/memory.py`）

`MemoryStore.search(session_id, limit, min_importance)` 的召回逻辑**仅**按：

```python
ORDER BY importance DESC, created_at DESC   # Postgres branch
```

即纯「重要性 + 新近性」。没有语义匹配（无 embedding 相似度、无 keywords/jaccard），记忆从候选池里被挑出的唯一理由是「重要」，而不是「和这题相关」。

### 3.2 上下文选择器（`src/graphs/javatutor/context_builder.py`）

`gather()` 把每条记忆包成 `ContextPacket`：

```python
ContextPacket(m.get("content", ""),
              timestamp=...,            # 来自 created_at
              relevance_score=0.5 + importance * 0.4,   # ← 只反映重要性
              metadata={"section": "Memory"})
```

`select()` 再用 `combined = 0.7*relevance + 0.3*recency` 贪心填充预算（`budget = 0.8 * 3000 = 2400`）挑出进窗口的包。

**缺口**：`relevance_score` 里没有「与当前问题的相关性」项，`select()` 于是只能从「按重要性排出的前 N 条」里选，无法救回「相关但次要」的记忆。学生问「解释这次循环」，但 `load_session` 返回的可能是该会话里最「重要」的 5 条结论，未必匹配当前问题。

## 4. 改动方案

### 4.1 扩大候选池

`src/graphs/javatutor/nodes.py` 的 `load_session` 把 `store.search` 的 `limit` 从 5 提到 **10**：给 `select()` 更多候选，配合下面的相关性打分，让「相关但靠后」的记忆有机会进入预算竞争。

```python
return {"memories": get_memory_store().search(session_id, limit=10)}
```

### 4.2 记忆包加入「与当前问题相关性」

`src/graphs/javatutor/context_builder.py` 的 `gather()` 里，把记忆包的 `relevance_score` 从纯 importance 改成**语义相关性 × 重要性**双因子，复用文件内已有 `jaccard()`（关键词重叠，零新依赖、确定性、便宜）：

```python
q = state.get("user_question", "")        # 已存在

def memory_relevance(content, importance, query, semantic_weight=0.6, importance_weight=0.4):
    semantic = jaccard(query, content)          # 0..1
    floor = 0.5 + float(importance) * 0.5        # 0.5..1.0（importance 调制）
    # semantic_weight 支配，importance 提供地板，避免「重要但不同词」的记忆被彻底过滤
    return semantic_weight * semantic + importance_weight * floor
```

对应包：

```python
ContextPacket(m.get("content", ""),
              timestamp=float(m.get("created_at", time.time())),
              relevance_score=memory_relevance(m.get("content", ""),
                                               float(m.get("importance", 0.5)),
                                               q),
              metadata={"section": "Memory"})
```

- `semantic_weight`（0.6）支配，让「相关记忆」显著领先。
- `importance_weight`（0.4）+ `floor` 保证一条完全不匹配但高重要性的记忆仍得到约 `0.4 × (0.5 + 0.5) = 0.4`，高于 `MIN_RELEVANCE=0.1`，不会被直接丢，只是排在相关记忆之后。
- 与第八章检索打分骨架 `(相关度 × 时间衰减) × (0.8 + 重要性×0.4)` 同构；recency 部分仍由 `select()` 现有 `recency()`（指数衰减）处理，不动。

`select()` 无需改动（小改动面）。权重与语义/重要性配比作为常量暴露，供 A/B 调参（参见衔接项目「上下文工程」章节：关键参数用 A/B 测试）。

## 5. 关键代码变更（diff 摘要）

`src/graphs/javatutor/nodes.py`：
- `load_session`：`limit=5` → `limit=10`。

`src/graphs/javatutor/context_builder.py`：
- 新增 `memory_relevance(content, importance, query, ...)` 纯函数（含 docstring 标注权重含义）。
- `gather()` 记忆包分支改用上述函数计算 `relevance_score`。

## 6. 权衡与边界

- **候选池扩大 10 条**：不会显著挤出 `source_code`/执行位置包（它们 relevance 0.8/0.9，贪心先选）；记忆包本身相关性低，只有相关者才赢。预算竞争仍在 `select()` 内统一裁决。
- **jaccard 对中文粒度偏粗**：`re.findall(r"\w+", ...)` 会把无空格的中文段当成单个 token（整句重叠），是粗粒度的确定性预算比较。可作廉价基线；追求精度时升级为 embedding 相似度或 jieba 分词（见第 8 节升级路径）。
- **行为变化**：先前记忆包一律 ≥0.5 relevance；改为相关性主导后，与本问题无关的历史记忆可能低于 `MIN_RELEVANCE` 被过滤掉——这是**符合预期的改进**（只让相关的记忆占预算）。

## 7. 测试策略

### 单元测试（`tests/`）

- `memory_relevance`：匹配 vs 不匹配 query 的相关性高低；`importance=0` 与 `importance=1` 的边界；query 为空时不炸（语义项为 0 时靠 importance 地板保底）。
- `gather()`：记忆包 `relevance_score` 随 query 匹配度变化；与当前问题相关的历史记忆比无关者获得更高相关性。
- 回归：`load_session` 仍返回可被 `build_context` 消费的结构（content/importance/created_at）。

### 组件/组件级评价

- 给定多轮会话构造若干记忆（有的贴题、有的不贴题、有的高重要但与题无关），断言注入上下文的最终文本优先包含**贴题**记忆。可用现有 `test_build_final` / 上下文构建相关测试扩展。

## 8. 升级路径（本次不实现）

1. **语义相似度**：用轻量 embedding（或复用现有知识库嵌入模型）替代 jaccard，做成 `memory_relevance` 的可选实现；记住第八章两条铁律（入库与查询同模型、向量归一化）。
2. **jieba/BM25**：中文分词后 TF-IDF，提升中文召回。
3. **记忆整合/遗忘**（第八章 consolidate/forget）：超出 10 条候选或重要性超阈值时，才按生命周期做固化到长期记忆、清理低价值记忆。仅当会话跨多轮、历史显著膨胀时再引入。

## 9. 与现有评估系统关系

组件评测新增样本时，可构造多历史记忆场景；评估指标关注「最终回答是否引用了与当前问题相关的记忆」。`memory_relevance` 权重可通过评测做小样本 A/B 校验后固定在代码常量。
