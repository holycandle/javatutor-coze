# Agent 架构改进实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 JavaTutor Coze 智能体重构为“外层教学 Agent + 评审 Agent，内层工具循环”的多工具架构，并集成 GSSC 上下文工程、会话工作记忆、项目知识 RAG；移除 SVG 动画生成模块。

**Architecture:** 新图链路：`parse_context → context_compaction → analyze_code（确定性）→ load_session → build_context（GSSC）→ main_agent（step_facts 工具循环 ≤3 轮）→ critic → revise → save_session → build_final`；显式 `intent=analyze` 直接返回分析 JSON。

**Tech Stack:** Python 3.12、LangGraph 1.x、PostgreSQL + pgvector、pytest、Coze SDK（`llm_complete`）。

---

## Global Constraints

- 不得修改 `.coze`、`scripts/`、`src/main.py`、`src/storage/`、`src/utils/`。
- 新代码只允许放在 `src/agents/`、`src/graphs/javatutor/`、`src/learning/`、`src/tools/`、`assets/`、`config/`、`tests/`、`docs/`。
- 中间 LLM 调用一律使用 `llm_complete()`，避免 `stream_mode=messages` 流式泄露。
- 意图识别 = 保守关键词 + 显式 intent（复用 `intent_rules.py`），不使用 LLM 分类。
- 每个任务 TDD：先写失败测试 → 实现 → 通过 → 提交。

---

## File Structure

| 文件 | 责任 |
|---|---|
| `src/graphs/javatutor/analyze.py` | analyze_code 确定性节点 |
| `src/tools/step_facts.py` | step_facts 工具 |
| `src/learning/memory.py` | 会话工作记忆 |
| `src/graphs/javatutor/context_builder.py` | GSSC 上下文构建器 |
| `src/graphs/javatutor/main_agent.py` | 主 Agent 工具循环 |
| `src/graphs/javatutor/nodes.py` | parse/derive/load/save/build_context 节点（修改） |
| `src/graphs/javatutor/graph.py` | 新链路装配（修改） |
| `src/graphs/javatutor/state.py` | 状态字段调整（修改） |
| `src/graphs/javatutor/prompts.py` | 移除动画、新增主 Agent 提示词（修改） |
| `src/graphs/javatutor/intent_rules.py` | VALID_INTENTS 调整（修改） |
| `assets/knowledge/javatutor_project.json` | 项目知识语料 |
| 删除：`src/learning/animation.py`、`assets/svg_templates/`、动画相关测试 | 移除动画模块 |

---

### Task 1: 移除 SVG 动画模块

**Files:**
- Delete: `src/learning/animation.py`
- Delete: `assets/svg_templates/`
- Delete: `tests/test_animation.py`、`tests/fixtures/animation_data.json`
- Modify: `src/graphs/javatutor/nodes.py`、`prompts.py`、`graph.py`、`state.py`、`intent_rules.py`
- Modify: `tests/test_expert_nodes.py`、`tests/test_graph.py`

**Interfaces:**
- `intent_rules.VALID_INTENTS` 移除 `animate`；图中无 `animate` / `animate_guide` 节点。

- [ ] **Step 1: 写失败测试**

在 `tests/test_graph.py` 追加：

```python
def test_graph_has_no_animation_nodes():
    from graphs.javatutor.graph import build_flow_graph

    graph = build_flow_graph()
    assert "animate" not in graph.nodes
    assert "animate_guide" not in graph.nodes
```

同时在 `tests/test_prompting.py` 或 `tests/test_expert_nodes.py` 追加：

```python
def test_no_animation_prompt_constant():
    import graphs.javatutor.prompts as prompts

    assert not hasattr(prompts, "SYSTEM_PROMPT_ANIMATE")
    assert not hasattr(prompts, "ANIMATE_GUIDE_MESSAGE")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_graph.py tests/test_expert_nodes.py -v`
Expected: FAIL（动画节点仍存在）。

- [ ] **Step 3: 删除动画代码**

1. 删除文件：

```bash
git rm src/learning/animation.py assets/svg_templates tests/test_animation.py tests/fixtures/animation_data.json
```

2. `src/graphs/javatutor/nodes.py`：删除 import 与 `animate_node`、`animate_guide_node` 定义。
3. `src/graphs/javatutor/prompts.py`：删除 `SYSTEM_PROMPT_ANIMATE`、`ANIMATE_GUIDE_MESSAGE`。
4. `src/graphs/javatutor/graph.py`：删除 `animate_node`、`animate_guide_node` import、节点注册与边。
5. `src/graphs/javatutor/state.py`：删除 `svg_text` 字段。
6. `src/graphs/javatutor/intent_rules.py`：`VALID_INTENTS = {"data_query", "concept", "debug", "other"}`。
7. `tests/test_expert_nodes.py`：删除 animate 相关测试与 import。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_graph.py tests/test_expert_nodes.py -v`
Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "refactor: remove SVG animation module"
```

---

### Task 2: 保守意图派生

**Files:**
- Modify: `src/graphs/javatutor/nodes.py`
- Modify: `tests/test_parse_context.py`

**Interfaces:**
- `parse_context` 返回的 `intent`：显式 intent 优先，否则 `conservative_intent(user_question, compile_error)`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_parse_context.py` 追加：

```python
def test_parse_context_derives_conservative_intent():
    from graphs.javatutor.nodes import parse_context
    from langchain_core.messages import HumanMessage
    import json

    payload = {
        "source_code": "public class A {}",
        "steps": [],
        "current_step_index": 0,
        "current_line": 1,
        "user_question": "为什么 arr 变了？",
        "compile_error": "",
    }
    state = {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]}
    out = parse_context(state)
    assert out["intent"] == "data_query"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_parse_context.py -v`
Expected: FAIL（intent 为空）。

- [ ] **Step 3: 实现派生逻辑**

在 `src/graphs/javatutor/nodes.py` 顶部追加 import：

```python
from graphs.javatutor.intent_rules import conservative_intent
```

在 `_parse_json_dict` 的返回中，`intent` 改为：

```python
        "intent": (
            intent
            if intent in ("data_query", "concept", "debug", "analyze", "other")
            else conservative_intent(user_question, compile_error)
        ),
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_parse_context.py -v`
Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add src/graphs/javatutor/nodes.py tests/test_parse_context.py
git commit -m "feat: derive conservative intent in parse_context"
```

---

### Task 3: analyze_code 确定性节点

**Files:**
- Create: `src/graphs/javatutor/analyze.py`
- Modify: `src/graphs/javatutor/state.py`
- Test: `tests/test_analyze_code.py`

**Interfaces:**
- Produces: `analyze_code_node(state, model=None) -> dict`，返回 `analysis_result`；`intent=analyze` 时另返回 `messages`（纯 JSON）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_analyze_code.py`：

```python
from langchain_core.messages import AIMessage

from graphs.javatutor.analyze import analyze_code_node


class FakeModel:
    def __init__(self, content):
        self.content = content

    def invoke(self, messages):
        return AIMessage(content=self.content)


def test_analyze_runs_when_source_code_present():
    state = {"source_code": "public class A {}", "intent": ""}
    out = analyze_code_node(state, model=FakeModel('{"complexity": {"time": "O(1)"}, "algorithms": [], "dataStructures": []}'))
    assert out["analysis_result"]["complexity"]["time"] == "O(1)"


def test_analyze_skips_without_source_code():
    out = analyze_code_node({"source_code": "", "intent": ""})
    assert out["analysis_result"] is None


def test_analyze_explicit_returns_message():
    state = {"source_code": "public class A {}", "intent": "analyze"}
    out = analyze_code_node(state, model=FakeModel('{"complexity": {"time": "O(1)"}}'))
    assert out["messages"][0].content.startswith("{")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_analyze_code.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 实现 analyze 节点**

创建 `src/graphs/javatutor/analyze.py`：

```python
"""analyze_code 确定性前置节点。"""

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from graphs.javatutor.prompts import SYSTEM_PROMPT_ANALYZE


def _parse_analysis(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _invoke(messages, model):
    if model is not None:
        return model.invoke(messages)
    from graphs.javatutor.llm import llm_complete

    raw = llm_complete(messages, temperature=0.1, max_completion_tokens=2000)
    return AIMessage(content=raw)


def analyze_code_node(state, model=None) -> dict[str, Any]:
    source_code = state.get("source_code", "")
    if not source_code:
        return {"analysis_result": None}
    messages = [
        SystemMessage(content=SYSTEM_PROMPT_ANALYZE),
        HumanMessage(content=f"源代码:\n```java\n{source_code}\n```"),
    ]
    parsed = None
    try:
        raw = _invoke(messages, model).content
        parsed = _parse_analysis(raw)
    except Exception:
        parsed = None
    result = parsed or {}
    if state.get("intent") == "analyze":
        return {"analysis_result": result, "messages": [AIMessage(content=json.dumps(result, ensure_ascii=False))]}
    return {"analysis_result": result}
```

在 `src/graphs/javatutor/state.py` 追加：

```python
    analysis_result: dict
    memories: list[dict]
    context_built: str
    tool_rounds: int
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_analyze_code.py -v`
Expected: 3 passed。

- [ ] **Step 5: 提交**

```bash
git add src/graphs/javatutor/analyze.py src/graphs/javatutor/state.py tests/test_analyze_code.py
git commit -m "feat: add deterministic analyze_code node"
```

---

### Task 4: step_facts 工具

**Files:**
- Create: `src/tools/step_facts.py`
- Test: `tests/test_step_facts.py`

**Interfaces:**
- Produces: `step_facts(state, step_index=None, line=None) -> dict`、`TOOL_SCHEMA`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_step_facts.py`：

```python
from tools.step_facts import step_facts


STATE = {
    "source_code": "public class A {\n    void f() {\n        int x = 1;\n    }\n}",
    "steps": [
        {"step": 0, "line": 3, "variables": {"x": 1}, "heap": {}, "stackFrames": [], "output": None},
        {"step": 1, "line": 3, "variables": {"x": 2}, "heap": {"h1": {"type": "Object"}}, "stackFrames": [{"method": "f"}], "output": "out"},
    ],
    "current_step_index": 0,
}


def test_step_facts_returns_evidence_and_diff():
    out = step_facts(STATE, step_index=1)
    assert out["error"] == ""
    assert out["evidence"]["variables"]["x"] == 2
    assert out["evidence"]["heap"]["h1"]["type"] == "Object"
    assert out["evidence"]["stackFrames"][0]["method"] == "f"
    assert out["evidence"]["output"] == "out"
    assert out["evidence"]["line_text"] == "int x = 1;"
    assert out["diff"] == [{"key": "x", "before": 1, "after": 2}]


def test_step_facts_out_of_range():
    out = step_facts(STATE, step_index=99)
    assert out["error"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_step_facts.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 实现工具**

创建 `src/tools/step_facts.py`：

```python
"""step_facts 工具：返回指定步骤/行的原始证据与程序化 diff，不调用 LLM。"""

from typing import Any

TOOL_SCHEMA = {
    "name": "step_facts",
    "description": "查询指定步骤/行的原始执行证据与相邻步骤变化",
    "parameters": {
        "type": "object",
        "properties": {"step_index": {"type": "integer"}, "line": {"type": "integer"}},
    },
}


def _line_text(source: str, line) -> str:
    try:
        idx = int(line) - 1
        lines = source.splitlines()
        if 0 <= idx < len(lines):
            return lines[idx].strip()
    except (TypeError, ValueError):
        pass
    return "(行号超出范围)"


def step_facts(state, step_index=None, line=None) -> dict[str, Any]:
    steps = state.get("steps") or []
    if step_index is None and line is None:
        step_index = state.get("current_step_index", 0)
    try:
        idx = int(step_index)
        step = steps[idx]
    except (IndexError, TypeError, ValueError):
        return {"error": f"step_index {step_index} 不在范围内", "evidence": {}, "diff": []}

    evidence = {
        "variables": step.get("variables", {}),
        "heap": step.get("heap", {}),
        "stackFrames": step.get("stackFrames", []),
        "output": step.get("output"),
        "line_text": _line_text(state.get("source_code", ""), line if line is not None else step.get("line", 1)),
    }
    diff = []
    if idx > 0:
        prev_vars = steps[idx - 1].get("variables", {})
        cur_vars = step.get("variables", {})
        for key in sorted(set(prev_vars) | set(cur_vars)):
            if prev_vars.get(key) != cur_vars.get(key):
                diff.append({"key": key, "before": prev_vars.get(key), "after": cur_vars.get(key)})
    return {"error": "", "evidence": evidence, "diff": diff}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_step_facts.py -v`
Expected: 2 passed。

- [ ] **Step 5: 提交**

```bash
git add src/tools/step_facts.py tests/test_step_facts.py
git commit -m "feat: add step_facts tool"
```

---

### Task 5: 会话工作记忆

**Files:**
- Create: `src/learning/memory.py`
- Modify: `src/graphs/javatutor/nodes.py`（load_session / save_session）
- Test: `tests/test_memory_store.py`

**Interfaces:**
- Produces: `MemoryStore` 抽象、`DictMemoryStore`、`PostgresMemoryStore`、`get_memory_store()`；节点 `load_session(state)` / `save_session(state)`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_memory_store.py`：

```python
import time

from learning.memory import DictMemoryStore


def test_add_search_importance():
    store = DictMemoryStore(ttl_seconds=3600, capacity=50)
    store.add("s1", "上次分析：复杂度 O(n)", importance=0.85)
    store.add("s1", "问答摘要", importance=0.5)
    rows = store.search("s1", limit=5, min_importance=0.6)
    assert len(rows) == 1
    assert rows[0]["importance"] == 0.85


def test_expire_removes_old_memories():
    store = DictMemoryStore(ttl_seconds=1)
    store.add("s1", "old", importance=0.9)
    time.sleep(1.1)
    assert store.search("s1") == []


def test_capacity_evicts_lowest_importance():
    store = DictMemoryStore(ttl_seconds=3600, capacity=2)
    store.add("s1", "a", importance=0.3)
    store.add("s1", "b", importance=0.8)
    store.add("s1", "c", importance=0.9)
    rows = store.search("s1")
    assert len(rows) == 2
    assert rows[0]["importance"] == 0.9
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_memory_store.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 实现工作记忆**

创建 `src/learning/memory.py`：

```python
"""会话工作记忆：Postgres 持久化 + 进程内 Dict 兜底。"""

import time
from typing import Any

DEFAULT_TTL_SECONDS = 3600
DEFAULT_CAPACITY = 50


class MemoryStore:
    def add(self, session_id, content, importance=0.5, memory_type="working", ttl_seconds=DEFAULT_TTL_SECONDS):
        raise NotImplementedError

    def search(self, session_id, limit=10, min_importance=0.0):
        raise NotImplementedError

    def expire(self, session_id=None):
        raise NotImplementedError


class DictMemoryStore(MemoryStore):
    def __init__(self, ttl_seconds=DEFAULT_TTL_SECONDS, capacity=DEFAULT_CAPACITY):
        self._items = []
        self._ttl_seconds = ttl_seconds
        self._capacity = capacity

    def add(self, session_id, content, importance=0.5, memory_type="working", ttl_seconds=DEFAULT_TTL_SECONDS):
        self._items.append(
            {
                "session_id": session_id,
                "content": content,
                "importance": importance,
                "memory_type": memory_type,
                "created_at": time.time(),
                "expires_at": time.time() + ttl_seconds,
            }
        )
        self._items.sort(key=lambda m: m["importance"], reverse=True)
        if len(self._items) > self._capacity:
            self._items = self._items[: self._capacity]

    def search(self, session_id, limit=10, min_importance=0.0):
        self.expire(session_id)
        rows = [
            m
            for m in self._items
            if m["session_id"] == session_id and m["importance"] >= min_importance and m["expires_at"] > time.time()
        ]
        return sorted(rows, key=lambda m: (-m["importance"], -m["created_at"]))[:limit]

    def expire(self, session_id=None):
        now = time.time()
        self._items = [m for m in self._items if m["expires_at"] > now and (session_id is None or m["session_id"] == session_id)]


class PostgresMemoryStore(MemoryStore):
    def __init__(self, url=None):
        self._url = url

    def _connect(self):
        import psycopg

        if self._url:
            return psycopg.connect(self._url)
        from storage.database.db import get_db_url

        return psycopg.connect(get_db_url())

    def ensure_schema(self):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS session_memories ("
                    "id BIGSERIAL PRIMARY KEY, session_id VARCHAR(64) NOT NULL, content TEXT NOT NULL, "
                    "memory_type VARCHAR(16) NOT NULL DEFAULT 'working', "
                    "importance DOUBLE PRECISION NOT NULL DEFAULT 0.5, "
                    "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
                    "expires_at TIMESTAMPTZ NOT NULL)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_session_memories_session "
                    "ON session_memories (session_id, expires_at)"
                )
            conn.commit()

    def add(self, session_id, content, importance=0.5, memory_type="working", ttl_seconds=DEFAULT_TTL_SECONDS):
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO session_memories (session_id, content, memory_type, importance, expires_at) "
                    "VALUES (%s, %s, %s, %s, NOW() + (%s || ' seconds')::interval)",
                    (session_id, content, memory_type, importance, int(ttl_seconds)),
                )
            conn.commit()

    def search(self, session_id, limit=10, min_importance=0.0):
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT content, importance, EXTRACT(EPOCH FROM created_at) "
                    "FROM session_memories WHERE session_id = %s AND expires_at > NOW() "
                    "AND importance >= %s ORDER BY importance DESC, created_at DESC LIMIT %s",
                    (session_id, min_importance, limit),
                )
                return [{"content": r[0], "importance": r[1], "created_at": r[2]} for r in cur.fetchall()]

    def expire(self, session_id=None):
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                if session_id:
                    cur.execute("DELETE FROM session_memories WHERE expires_at <= NOW() AND session_id = %s", (session_id,))
                else:
                    cur.execute("DELETE FROM session_memories WHERE expires_at <= NOW()")
            conn.commit()


_store = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        try:
            _store = PostgresMemoryStore()
        except Exception:
            _store = DictMemoryStore()
    return _store
```

在 `src/graphs/javatutor/nodes.py` 追加 load/save 节点：

```python
def load_session(state: JavaTutorState) -> dict:
    session_id = state.get("user_id", "")
    if not session_id:
        return {"memories": []}
    try:
        from learning.memory import get_memory_store

        return {"memories": get_memory_store().search(session_id, limit=5)}
    except Exception:
        return {"memories": []}


def save_session(state: JavaTutorState) -> dict:
    session_id = state.get("user_id", "")
    answer = state.get("answer") or ""
    if not session_id or not answer:
        return {}
    try:
        from learning.memory import get_memory_store

        store = get_memory_store()
        store.add(session_id, f"问答：{state.get('user_question', '')} → {answer[:200]}", importance=0.5)
        analysis = state.get("analysis_result")
        if analysis:
            import json

            store.add(session_id, "上次分析：" + json.dumps(analysis, ensure_ascii=False)[:500], importance=0.85)
    except Exception:
        pass
    return {}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_memory_store.py -v`
Expected: 3 passed。

- [ ] **Step 5: 提交**

```bash
git add src/learning/memory.py src/graphs/javatutor/nodes.py tests/test_memory_store.py
git commit -m "feat: add session working memory"
```

---

### Task 6: GSSC ContextBuilder

**Files:**
- Create: `src/graphs/javatutor/context_builder.py`
- Test: `tests/test_context_builder.py`

**Interfaces:**
- Produces: `ContextPacket`、`gather(state, history, memories) -> list`、`select(packets, query, max_tokens) -> list`、`structure(chosen, system_instructions) -> str`、`compress(text, max_tokens) -> str`、`build_context(state, history, memories, system_instructions, max_tokens) -> str`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_context_builder.py`：

```python
from graphs.javatutor.context_builder import build_context, gather, select, structure


STATE = {
    "user_question": "HashMap 原理",
    "source_code": "public class A {}",
    "analysis_result": {"complexity": {"time": "O(1)"}},
    "retrieved_chunks": [{"source": "知识库: HashMap", "content": "基于哈希表", "score": 0.9}],
}


def test_gather_includes_all_sources():
    packets = gather(STATE, history=[{"role": "user", "content": "你好"}], memories=[{"content": "上次分析", "importance": 0.85, "created_at": 1}])
    sections = [p.metadata.get("section") for p in packets]
    assert "Task" in sections
    assert "Evidence" in sections
    assert "Memory" in sections
    assert "Context" in sections


def test_select_respects_budget():
    packets = gather(STATE, history=[], memories=[])
    chosen = select(packets, STATE["user_question"], max_tokens=200)
    assert chosen
    assert sum(p.token_count for p in chosen) <= 200 * 0.8 + max(p.token_count for p in chosen)


def test_structure_has_sections():
    packets = gather(STATE, history=[], memories=[])
    text = structure(select(packets, STATE["user_question"]), system_instructions="你是助教")
    assert "[Role & Policies]" in text
    assert "[Evidence]" in text


def test_build_context_returns_compressed_text():
    text = build_context(STATE, history=[], memories=[], system_instructions="你是助教", max_tokens=500)
    assert "HashMap" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_context_builder.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 实现 ContextBuilder**

创建 `src/graphs/javatutor/context_builder.py`：

```python
"""GSSC 上下文工程：Gather-Select-Structure-Compress。"""

import json
import math
import re
import time
from typing import Any

DEFAULT_MAX_TOKENS = 3000
RESERVE_RATIO = 0.2
RELEVANCE_WEIGHT = 0.7
RECENCY_WEIGHT = 0.3
MIN_RELEVANCE = 0.1


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text or "") * 0.75))


def jaccard(a: str, b: str) -> float:
    sa = set(re.findall(r"\w+", (a or "").lower()))
    sb = set(re.findall(r"\w+", (b or "").lower()))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def recency(timestamp: float, now: float | None = None) -> float:
    now = now or time.time()
    age_hours = max(0, (now - timestamp) / 3600)
    return max(0.1, math.exp(-0.1 * age_hours / 24))


class ContextPacket:
    def __init__(self, content, timestamp=None, token_count=None, relevance_score=0.5, metadata=None):
        self.content = content
        self.timestamp = timestamp or time.time()
        self.token_count = token_count or estimate_tokens(content)
        self.relevance_score = relevance_score
        self.metadata = metadata or {}


def gather(state, history=None, memories=None) -> list[ContextPacket]:
    packets = []
    q = state.get("user_question", "")
    packets.append(ContextPacket(f"### 用户问题\n{q}", relevance_score=1.0, metadata={"section": "Task"}))
    packets.append(ContextPacket(f"### 源代码\n```java\n{state.get('source_code', '')}\n```", relevance_score=0.8, metadata={"section": "Evidence"}))
    for chunk in state.get("retrieved_chunks") or []:
        packets.append(
            ContextPacket(f"[{chunk['source']}] {chunk['content'][:300]}", relevance_score=float(chunk.get("score", 0.5)), metadata={"section": "Evidence", "source": chunk["source"]})
        )
    analysis = state.get("analysis_result")
    if analysis:
        packets.append(ContextPacket(f"### 分析结果\n{json.dumps(analysis, ensure_ascii=False)[:500]}", relevance_score=0.9, metadata={"section": "Evidence"}))
    for m in memories or []:
        packets.append(
            ContextPacket(m.get("content", ""), timestamp=float(m.get("created_at", time.time())), relevance_score=0.5 + float(m.get("importance", 0.5)) * 0.4, metadata={"section": "Memory"})
        )
    for msg in (history or [])[-5:]:
        packets.append(
            ContextPacket(f"[{msg.get('role', 'user')}] {msg.get('content', '')[:200]}", timestamp=float(msg.get("timestamp", time.time())), relevance_score=0.4, metadata={"section": "Context"})
        )
    return packets


def select(packets, query, max_tokens=DEFAULT_MAX_TOKENS, reserve_ratio=RESERVE_RATIO) -> list[ContextPacket]:
    budget = max_tokens * (1 - reserve_ratio)
    scored = []
    for p in packets:
        rel = p.relevance_score if p.relevance_score is not None else jaccard(query, p.content)
        combined = RELEVANCE_WEIGHT * rel + RECENCY_WEIGHT * recency(p.timestamp)
        if combined >= MIN_RELEVANCE:
            scored.append((combined, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    chosen, used = [], 0
    for _, p in scored:
        if used + p.token_count > budget and chosen:
            break
        chosen.append(p)
        used += p.token_count
    return chosen


def structure(chosen, system_instructions="") -> str:
    sections = {"Role & Policies": system_instructions, "Task": [], "Evidence": [], "Memory": [], "Context": [], "Output": "遵循输出契约。"}
    for p in chosen:
        key = p.metadata.get("section", "Context")
        sections.setdefault(key, []).append(p.content)
    blocks = []
    for name in ("Role & Policies", "Task", "Evidence", "Memory", "Context", "Output"):
        val = sections.get(name, [])
        if isinstance(val, str):
            if val:
                blocks.append(f"[{name}]\n{val}")
        elif val:
            blocks.append(f"[{name}]\n" + "\n\n".join(val))
    return "\n\n".join(blocks)


def compress(text, max_tokens=DEFAULT_MAX_TOKENS) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    budget = max_tokens * 0.8
    parts, used = [], 0
    for block in text.split("\n\n"):
        if used + estimate_tokens(block) > budget:
            parts.append("[...已压缩...]")
            break
        parts.append(block)
        used += estimate_tokens(block)
    return "\n\n".join(parts)


def build_context(state, history=None, memories=None, system_instructions="", max_tokens=DEFAULT_MAX_TOKENS) -> str:
    packets = gather(state, history=history, memories=memories)
    chosen = select(packets, state.get("user_question", ""), max_tokens=max_tokens)
    return compress(structure(chosen, system_instructions=system_instructions), max_tokens=max_tokens)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_context_builder.py -v`
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add src/graphs/javatutor/context_builder.py tests/test_context_builder.py
git commit -m "feat: add GSSC context builder"
```

---

### Task 7: 主 Agent 工具循环

**Files:**
- Modify: `src/graphs/javatutor/prompts.py`
- Create: `src/graphs/javatutor/main_agent.py`
- Test: `tests/test_main_agent.py`

**Interfaces:**
- Produces: `main_agent_node(state, model=None) -> dict`，返回 `answer` 与 `tool_rounds`；最多 3 轮。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_main_agent.py`：

```python
from langchain_core.messages import AIMessage

from graphs.javatutor.main_agent import main_agent_node


class SequenceModel:
    def __init__(self, responses):
        self.responses = list(responses)

    def invoke(self, messages):
        return AIMessage(content=self.responses.pop(0))


STATE = {
    "context_built": "[Evidence]\n步骤数据",
    "steps": [
        {"step": 0, "line": 3, "variables": {"x": 1}},
        {"step": 1, "line": 3, "variables": {"x": 2}},
    ],
    "current_step_index": 1,
}


def test_main_agent_calls_step_facts_then_answers():
    model = SequenceModel(['{"tool": "step_facts", "args": {"step_index": 1}}', "根据第 2 步，x 变成了 2"])
    out = main_agent_node(STATE, model=model)
    assert out["tool_rounds"] == 2
    assert out["tool_calls"] == [{"tool": "step_facts", "args": {"step_index": 1}}]
    assert "x 变成了 2" in out["answer"]


def test_main_agent_direct_answer():
    out = main_agent_node(STATE, model=SequenceModel(["直接回答"]))
    assert out["tool_rounds"] == 1
    assert out["answer"] == "直接回答"


def test_main_agent_stops_after_three_rounds():
    model = SequenceModel(['{"tool": "step_facts", "args": {}}'] * 5)
    out = main_agent_node(STATE, model=model)
    assert out["tool_rounds"] == 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_main_agent.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 添加主 Agent 提示词**

在 `src/graphs/javatutor/prompts.py` 末尾追加：

```python
SYSTEM_PROMPT_MAIN_AGENT = """你是 JavaTutor 教学主 Agent。
根据上下文回答问题。如需查询指定步骤的原始执行证据，只返回 JSON：
{"tool": "step_facts", "args": {"step_index": 1, "line": 4}}
否则直接输出最终回答。回答必须引用真实步骤/行/变量值，不编造数据。"""
```

- [ ] **Step 4: 实现主 Agent**

创建 `src/graphs/javatutor/main_agent.py`：

```python
"""主 Agent 工具循环：解析式工具调用，最多 3 轮。"""

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from graphs.javatutor.prompts import SYSTEM_PROMPT_MAIN_AGENT
from tools.step_facts import step_facts

MAX_ROUNDS = 3


def _invoke(messages, model):
    if model is not None:
        return model.invoke(messages)
    from graphs.javatutor.llm import llm_complete

    raw = llm_complete(messages, temperature=0.5, max_completion_tokens=2000)
    return AIMessage(content=raw)


def _parse_tool(raw: str) -> dict | None:
    text = (raw or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and data.get("tool") else None


def main_agent_node(state, model=None) -> dict[str, Any]:
    context = state.get("context_built", "")
    rounds = 0
    answer = ""
    tool_calls = []
    while rounds < MAX_ROUNDS:
        rounds += 1
        messages = [
            SystemMessage(content=SYSTEM_PROMPT_MAIN_AGENT),
            HumanMessage(content=f"{context}\n\n[当前轮次] {rounds}"),
        ]
        resp = _invoke(messages, model).content
        tool = _parse_tool(resp)
        if tool is None:
            answer = resp
            break
        if tool["tool"] == "step_facts":
            tool_calls.append({"tool": "step_facts", "args": tool.get("args", {})})
            result = step_facts(state, **tool.get("args", {}))
            context += f"\n\n[step_facts 结果]\n{json.dumps(result, ensure_ascii=False)}"
        else:
            answer = resp
            break
    return {"answer": answer, "tool_rounds": rounds, "tool_calls": tool_calls}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_main_agent.py -v`
Expected: 3 passed。

- [ ] **Step 6: 提交**

```bash
git add src/graphs/javatutor/main_agent.py src/graphs/javatutor/prompts.py tests/test_main_agent.py
git commit -m "feat: add main agent tool loop"
```

---

### Task 8: 图装配与集成

**Files:**
- Modify: `src/graphs/javatutor/graph.py`、`nodes.py`、`state.py`
- Modify: `tests/test_graph.py`

**Interfaces:**
- `build_flow_graph()`：新链路 + `intent=analyze` 直达。

- [ ] **Step 1: 写失败测试**

在 `tests/test_graph.py` 追加：

```python
def test_graph_has_new_pipeline_nodes():
    from graphs.javatutor.graph import build_flow_graph

    graph = build_flow_graph()
    for node in ("analyze_code", "load_session", "build_context", "main_agent", "save_session"):
        assert node in graph.nodes


def test_full_flow_runs_new_pipeline():
    import json
    from langchain_core.messages import AIMessage, HumanMessage
    from agents.agent import build_agent

    class DeepModel:
        def __init__(self):
            self.i = 0

        def invoke(self, messages):
            self.i += 1
            content = messages[0].content
            if "算法分析" in content or "源代码" in content:
                return AIMessage(content='{"complexity": {"time": "O(1)"}}')
            if "教学主 Agent" in content:
                return AIMessage(content="根据第 2 步，x 变成了 2")
            if "回答评审" in content:
                return AIMessage(content='{"pass": true, "issues": []}')
            return AIMessage(content="修订回答")

    payload = {
        "source_code": "public class A {}",
        "steps": [{"step": 0, "variables": {"x": 1}}, {"step": 1, "variables": {"x": 2}}],
        "current_step_index": 1,
        "user_question": "x 怎么变了？",
        "compile_error": "",
    }
    compiled = build_agent().builder.compile()
    result = compiled.invoke({"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]}, config={"configurable": {"chat_model": DeepModel()}})
    assert result.get("analysis_result", {}).get("complexity", {}).get("time") == "O(1)"
    assert result.get("answer")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_graph.py -v`
Expected: FAIL（新节点缺失）。

- [ ] **Step 3: 重构 graph**

将 `src/graphs/javatutor/graph.py` 整体替换为：

```python
"""JavaTutor 图工作流 — 多工具 + 上下文工程版。"""

from langgraph.graph import END, StateGraph

from graphs.javatutor.analyze import analyze_code_node
from graphs.javatutor.critic import critic_node, revise_node
from graphs.javatutor.main_agent import main_agent_node
from graphs.javatutor.nodes import (
    build_context_node,
    build_final,
    context_compaction,
    load_session,
    parse_context,
    save_session,
)
from graphs.javatutor.state import JavaTutorState


def _route_after_analyze(state: JavaTutorState) -> str:
    return "direct" if state.get("intent") == "analyze" else "continue"


def build_flow_graph() -> StateGraph:
    graph = StateGraph(state_schema=JavaTutorState)
    graph.add_node("parse_context", parse_context)
    graph.add_node("context_compaction", context_compaction)
    graph.add_node("analyze_code", analyze_code_node)
    graph.add_node("load_session", load_session)
    graph.add_node("build_context", build_context_node)
    graph.add_node("main_agent", main_agent_node)
    graph.add_node("critic", critic_node)
    graph.add_node("revise", revise_node)
    graph.add_node("save_session", save_session)
    graph.add_node("final", build_final)

    graph.set_entry_point("parse_context")
    graph.add_edge("parse_context", "context_compaction")
    graph.add_edge("context_compaction", "analyze_code")
    graph.add_conditional_edges("analyze_code", _route_after_analyze, {"direct": "final", "continue": "load_session"})
    graph.add_edge("load_session", "build_context")
    graph.add_edge("build_context", "main_agent")
    graph.add_edge("main_agent", "critic")
    graph.add_edge("critic", "revise")
    graph.add_edge("revise", "save_session")
    graph.add_edge("save_session", "final")
    graph.add_edge("final", END)
    return graph
```

在 `src/graphs/javatutor/nodes.py` 追加 `build_context_node`：

```python
def build_context_node(state: JavaTutorState) -> dict:
    from graphs.javatutor.context_builder import build_context
    from graphs.javatutor.prompts import build_system_prompt

    text = build_context(
        state,
        history=[],
        memories=state.get("memories") or [],
        system_instructions=build_system_prompt("other"),
    )
    return {"context_built": text}
```

同步更新 import 列表（删除 animate/animate_guide 相关）。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_graph.py -v`
Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add src/graphs/javatutor/graph.py src/graphs/javatutor/nodes.py tests/test_graph.py
git commit -m "feat: wire multi-tool and context pipeline graph"
```

---

### Task 9: 项目知识语料与全量回归

**Files:**
- Create: `assets/knowledge/javatutor_project.json`
- Modify: `AGENT.md`（更新状态）

**Interfaces:**
- 项目知识 RAG 语料入库；全量测试通过。

- [ ] **Step 1: 创建项目知识语料**

创建 `assets/knowledge/javatutor_project.json`：

```json
{
  "entries": [
    {"title": "JavaTutor 产品能力", "keywords": ["javatutor", "产品", "面板"], "category": "项目知识", "explanation": "JavaTutor 是 Java 算法可视化教学工具，包含编辑、运行、单步播放、变量快照、堆/栈、控制流、控制台、算法可视化与 AI 讲解面板。", "source": "知识库: JavaTutor项目", "retrieved_at": "2026-08-14"},
    {"title": "Agent 能力边界", "keywords": ["agent", "能力", "职责"], "category": "项目知识", "explanation": "Agent 负责基于真实执行数据讲解代码；不直接替学生写完整作业；算法动画由前端算法可视化提供，Agent 不生成 SVG。", "source": "知识库: JavaTutor项目", "retrieved_at": "2026-08-14"},
    {"title": "算法可视化引导", "keywords": ["动画", "可视化", "演示"], "category": "项目知识", "explanation": "学生请求动画/演示时，引导其使用前端「算法可视化」按钮；Agent 不生成动画。", "source": "知识库: JavaTutor项目", "retrieved_at": "2026-08-14"},
    {"title": "复杂度分析", "keywords": ["复杂度", "算法标签", "analyze"], "category": "项目知识", "explanation": "每次运行代码后，Agent 会自动执行复杂度与算法/数据结构标签分析，结果供后续问答复用。", "source": "知识库: JavaTutor项目", "retrieved_at": "2026-08-14"}
  ]
}
```

- [ ] **Step 2: 运行全量测试**

Run: `uv run pytest tests/ -v`
Expected: 全部通过。

- [ ] **Step 3: 更新 AGENT.md**

将 `AGENT.md` 的“当前执行状态”表更新为：架构改进 plan 已写，待执行。

- [ ] **Step 4: 提交**

```bash
git add assets/knowledge/javatutor_project.json AGENT.md
git commit -m "feat: add project knowledge corpus and update agent index"
```

---

## Self-Review

### Spec Coverage

| spec 条目 | 对应任务 |
|---|---|
| 移除动画模块 | Task 1 |
| 保守意图派生 | Task 2 |
| analyze_code 确定性节点 | Task 3 |
| step_facts 工具 | Task 4 |
| 工作记忆 | Task 5 |
| GSSC ContextBuilder | Task 6 |
| 主 Agent 工具循环 | Task 7 |
| 图装配 | Task 8 |
| 项目知识语料 | Task 9 |

### Placeholder Scan

计划无 `TBD`、`TODO`；所有代码块完整。

### Type Consistency

- `conservative_intent(user_question, compile_error)`：Task 2 使用，Task 3+ 依赖。
- `analyze_code_node(state, model=None)`：Task 3 定义，Task 8 使用。
- `step_facts(state, step_index=None, line=None)`：Task 4 定义，Task 7 使用。
- `get_memory_store()`：Task 5 定义，`load_session` / `save_session` 使用。
- `build_context(state, history, memories, system_instructions, max_tokens)`：Task 6 定义，Task 8 使用。
- `main_agent_node(state, model=None)`：Task 7 定义，Task 8 使用。
