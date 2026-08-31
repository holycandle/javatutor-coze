# Memory Retrieval Context Engineering — Implementation Plan

> **For agentic workers:** 按 Task 顺序逐步实现，使用 checkbox（`- [ ]`）跟踪状态。每个 Task 先写失败测试，再实现让它通过。

**Goal:** 让会话记忆在预取进上下文时**按「与当前问题的相关性」挑选**，而非只按「重要性 + 新近性」。分两处改动：`load_session` 扩大候选池（5→10），`context_builder.gather` 给记忆包加 `memory_relevance` 相关性打分。

**Architecture:** 改动全部落在**上下文工程**链路内，不新增 graph 节点、不暴露任何新 agent 工具。设计文档见 `docs/spec/2026-08-29-memory-retrieval-context-engineering-design.md`（已写好，本 plan 只实现代码）。

**Tech Stack:** Python 3.12、LangGraph、pytest。

## Global Constraints

- 只修改：`src/graphs/javatutor/context_builder.py`、`src/graphs/javatutor/nodes.py`、`tests/test_memory_retrieval.py`。
- 不修改 `src/main.py`、`scripts/`、`.coze/`、`src/storage/`、`src/utils/`、`src/learning/memory.py`。
- import 禁止 `src.` 前缀；使用 `from graphs.javatutor.xxx import ...`、`from learning.xxx import ...`。
- API Key / token 不硬编码；本任务用不到。
- 每个 Task 完成后运行对应 pytest。
- 不主动 commit / push；提交步骤仅在执行者被明确授权后执行。

---

### Task 1: 新增 `memory_relevance` 并接入 `gather`（知识上下文工程）

**Files:**
- Modify: `src/graphs/javatutor/context_builder.py`
- Create: `tests/test_memory_retrieval.py`

**Interfaces:**
- Consumes: `memory_relevance(content, importance, query)`。
- Produces: `gather()` 输出中「Memory」section 的记忆包带相关性打分。

- [ ] **Step 1: Write failing tests**

创建 `tests/test_memory_retrieval.py`：

```python
"""记忆检索上下文工程测试：memory_relevance 与 gather 相关性打分。"""

from graphs.javatutor.context_builder import gather, memory_relevance


def test_memory_relevance_ranks_relevant_higher():
    relevant = memory_relevance("用户想问 HashMap 哈希冲突的处理方式", 0.5, "HashMap 原理")
    irrelevant = memory_relevance("用户上次问冒泡排序的时间复杂度", 0.5, "HashMap 原理")
    assert relevant > irrelevant


def test_memory_relevance_importance_floor_keeps_high_importance():
    low = memory_relevance("完全不相关的句子 ABC", 0.0, "HashMap 原理")
    high = memory_relevance("完全不相关的句子 ABC", 1.0, "HashMap 原理")
    assert high > low


def test_memory_relevance_empty_query_does_not_crash():
    score = memory_relevance("content", 0.5, "")
    assert score >= 0.0


STATE = {
    "user_question": "HashMap 原理",
    "source_code": "public class A {}",
    "has_steps": True,
    "current_step_index": 1,
    "current_line": 4,
    "steps_count": 2,
}


def test_gather_scores_memory_by_query_relevance():
    memories = [
        {"content": "用户问 HashMap 哈希冲突", "importance": 0.4, "created_at": 1},
        {"content": "用户问冒泡排序的时间复杂度", "importance": 0.9, "created_at": 2},
    ]
    packets = gather(STATE, history=[], memories=memories)
    memory_packets = [p for p in packets if p.metadata.get("section") == "Memory"]
    assert len(memory_packets) == 2
    by_content = {p.content: p.relevance_score for p in memory_packets}
    assert by_content["用户问 HashMap 哈希冲突"] > by_content["用户问冒泡排序的时间复杂度"]


def test_gather_memory_packets_still_include_importance_section():
    packets = gather(STATE, history=[], memories=[{"content": "c", "importance": 0.8, "created_at": 1}])
    memory_packets = [p for p in packets if p.metadata.get("section") == "Memory"]
    assert len(memory_packets) == 1
    assert memory_packets[0].content == "c"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_memory_retrieval.py -q`
Expected: FAIL，`ImportError: cannot import name 'memory_relevance'`。

- [ ] **Step 3: Add `memory_relevance` helper**

在 `src/graphs/javatutor/context_builder.py` 的 `jaccard` 函数之后（约第 26 行）追加：

```python
def memory_relevance(content, importance, query, semantic_weight=0.6, importance_weight=0.4) -> float:
    """记忆包相关性：语义匹配（jaccard）与重要性地板的加权。

    semantic_weight 支配（让『与当前问题相关』的记忆领先），importance_weight
    提供地板（semantic_weight, importance_weight 和应为 1.0，权重可 A/B 调整）。
    """
    semantic = jaccard(query or "", content or "")
    floor = 0.5 + float(importance or 0.0) * 0.5
    return semantic_weight * semantic + importance_weight * floor
```

- [ ] **Step 4: Use it in `gather`**

在 `gather()` 中，将现有的记忆包分支（当前是一行）：

```python
    for m in memories or []:
        packets.append(
            ContextPacket(m.get("content", ""), timestamp=float(m.get("created_at", time.time())), relevance_score=0.5 + float(m.get("importance", 0.5)) * 0.4, metadata={"section": "Memory"})
        )
```

替换为（`q` 已在该函数顶部定义，即 `q = state.get("user_question", "")`）：

```python
    for m in memories or []:
        packets.append(
            ContextPacket(
                m.get("content", ""),
                timestamp=float(m.get("created_at", time.time())),
                relevance_score=memory_relevance(m.get("content", ""), float(m.get("importance", 0.5)), q),
                metadata={"section": "Memory"},
            )
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_memory_retrieval.py tests/test_context_builder.py -q`
Expected: PASS（含既有 `test_context_builder.py` 全绿，确认无回归）。

- [ ] **Step 6: Commit**

```bash
git add src/graphs/javatutor/context_builder.py tests/test_memory_retrieval.py
git commit -m "feat(context): score session memory by query relevance in gather"
```

---

### Task 2: `load_session` 扩大记忆候选池

**Files:**
- Modify: `src/graphs/javatutor/nodes.py`
- Modify: `tests/test_memory_retrieval.py`

**Interfaces:**
- Consumes: `learning.memory.get_memory_store()`。
- Produces: `load_session` 返回 `memories`，候选上限由 5 提到 10，供 `gather` 的相关性打分有更多选择。

- [ ] **Step 1: Write failing test**

在 `tests/test_memory_retrieval.py` 末尾追加：

```python
from graphs.javatutor import nodes


def test_load_session_requests_ten_candidates(monkeypatch):
    class FakeStore:
        def search(self, session_id, limit=10, min_importance=0.0):
            self.captured_limit = limit
            return []

    store = FakeStore()
    monkeypatch.setattr("learning.memory.get_memory_store", lambda: store)

    out = nodes.load_session({"user_id": "session-1"})
    assert store.captured_limit == 10
    assert out == {"memories": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_memory_retrieval.py::test_load_session_requests_ten_candidates -q`
Expected: FAIL，断言 `expected 10, captured 5`（当前实现仍是 limit=5）。

- [ ] **Step 3: Change the limit**

在 `src/graphs/javatutor/nodes.py` 的 `load_session` 中：

```python
        return {"memories": get_memory_store().search(session_id, limit=5)}
```

改为：

```python
        return {"memories": get_memory_store().search(session_id, limit=10)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_memory_retrieval.py::test_load_session_requests_ten_candidates -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/graphs/javatutor/nodes.py tests/test_memory_retrieval.py
git commit -m "feat(context): enlarge session memory candidate pool to 10"
```

---

### Task 3: 全量回归

**Files:**
- 无新增改动；仅验证。

- [ ] **Step 1: Run full coze test suite**

Run: `uv run pytest -q`
Expected: 全部通过，无回归（尤其 `test_context_builder.py`、`test_build_final.py`、`test_main_agent.py` 应保持绿）。

- [ ] **Step 2: 核对协作指南**

确认 `docs/agent-collaboration-guide.md` 的「信息分层原则」已存在（本人在 spec/plan 阶段已写入）；若缺失，补上并保持一致。

---

## Self-Review

- Spec 覆盖：设计文档 `docs/spec/2026-08-29-memory-retrieval-context-engineering-design.md` 的 4.1（候选池 5→10）、4.2（memory_relevance）均已落到 Task 1-2。
- 占位扫描：无 `TBD` / `TODO` /「适当处理」等空泛步骤。
- 类型一致性：`memory_relevance(content, importance, query)` 入参类型（str, float, str）与 `gather` 调用处一致；`load_session` 返回值结构（`{"memories": [...]}`）与 `gather` 的 `memories` 参数一致。
- 边界：`jaccard` 对中文整段（无空格）粒度较粗，但作为零依赖基线可接受；已在设计文档第 6 节标注，升级路径（embedding/jieba）不在本 plan 范围。
- 额外风险：`load_session` 内是 `from learning.memory import get_memory_store`（函数内 import），测试必须 patch `learning.memory.get_memory_store` 模块级名字，而非 patch nodes 内的引用。
