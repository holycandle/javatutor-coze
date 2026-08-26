# Execution Context Fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Coze 侧不再依赖入站消息携带完整执行数据，改为按 `run_id` 从 JavaTutor 后端确定性获取代码、steps 和当前执行位置。

**Architecture:** 新增 `fetch_execution_context` 工具函数与同名 graph 节点，放在 `parse_context` 之后、`context_compaction` 之前；主 Agent 工具循环仍只暴露 `step_facts`。执行上下文完整数据只进 state，运行摘要进 `run_context_memory`。

**Tech Stack:** Python 3.12、LangGraph、httpx、pytest。

## Global Constraints

- 只修改业务目录：`src/agents/`、`src/graphs/`、`src/tools/`、`tools/`、`tests/`、`docs/`。
- 不修改 `src/main.py`、`scripts/`、`.coze/`、`src/storage/`、`src/utils/`。
- import 禁止 `src.` 前缀；使用 `from tools.xxx import ...`、`from graphs.javatutor.xxx import ...`。
- API Key / token 只从环境变量读取，禁止硬编码。
- 文件名只允许字母、数字、下划线、短横线。
- 每个任务完成后运行 `uv run pytest <test-path> -q`。
- 不主动 commit / push；每个任务末尾的 commit 步骤仅在执行者被明确授权后执行。

---

### Task 1: 状态 schema 与入站 envelope 解析

**Files:**
- Modify: `src/graphs/javatutor/state.py`
- Modify: `src/graphs/javatutor/nodes.py:85-138`
- Test: `tests/test_parse_context.py`

**Interfaces:**
- Consumes: `JavaTutorState` 现有字段。
- Produces: `run_id`, `user_id`（由 `session_id` 或旧 `user_id` 映射）。

- [ ] **Step 1: Write failing tests**

在 `tests/test_parse_context.py` 末尾追加：

```python
def test_parse_new_envelope_maps_session_id_to_user_id():
    payload = {
        "run_id": "3f8a2c0d-1234-5678-9abc-def012345678",
        "session_id": "session-9",
        "user_question": "请解释当前这一步在做什么",
        "intent": "data_query",
        "compile_error": "",
    }
    state = parse_context(json.dumps(payload))
    assert state["run_id"] == "3f8a2c0d-1234-5678-9abc-def012345678"
    assert state["user_id"] == "session-9"
    assert state["source_code"] == ""
    assert state["steps"] == []
    assert state["steps_count"] == 0
    assert state["has_steps"] is False
    assert state["intent"] == "data_query"


def test_parse_new_envelope_without_intent_derives_conservative_intent():
    payload = {
        "run_id": "run-1",
        "session_id": "session-1",
        "user_question": "为什么 arr 变了？",
        "compile_error": "",
    }
    state = parse_context(json.dumps(payload))
    assert state["intent"] == "data_query"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_parse_context.py -q`
Expected: 新增用例失败，报 `KeyError: 'run_id'` 或断言失败。

- [ ] **Step 3: Add state fields**

在 `src/graphs/javatutor/state.py` 的 `JavaTutorState` 中，`request_started_at` 之后追加：

```python
    run_id: str
    """JavaTutor 后端本次运行生成的 run_id。"""

    fetch_context_failed: bool
    """fetch_execution_context 是否失败。"""

    fetch_context_latency_ms: float
    """fetch_execution_context 请求耗时，单位毫秒。"""

    fetch_context_error: str
    """fetch_execution_context 失败时的可读错误。"""

    run_context_memory: dict
    """本轮运行上下文的紧凑摘要，禁止保存完整 source_code 与 steps。"""
```

- [ ] **Step 4: Parse `run_id` and `session_id`**

在 `src/graphs/javatutor/nodes.py` 的 `_parse_json_dict` 中，将 `user_id = data.get("user_id", "")` 替换为：

```python
    run_id = data.get("run_id", "")
    session_id = data.get("session_id", data.get("user_id", ""))
```

在返回字典中新增：

```python
        "run_id": run_id,
        "user_id": session_id,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_parse_context.py -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/graphs/javatutor/state.py src/graphs/javatutor/nodes.py tests/test_parse_context.py
git commit -m "feat: parse run_id and session_id in agent envelope"
```

---

### Task 2: `fetch_execution_context` 工具函数

**Files:**
- Create: `src/tools/fetch_execution_context.py`
- Test: `tests/test_fetch_execution_context.py`

**Interfaces:**
- Consumes: 环境变量 `JAVATUTOR_EXECUTION_CONTEXT_URL`、`JAVATUTOR_AGENT_TOKEN`。
- Produces: `fetch_execution_context(state, run_id=None) -> dict`，返回可被 LangGraph 合并的 state 更新。

- [ ] **Step 1: Write failing tests**

创建 `tests/test_fetch_execution_context.py`：

```python
from tools.fetch_execution_context import fetch_execution_context


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _success_payload():
    return {
        "run_id": "run-1",
        "source_code": "public class A { int x = 1; }",
        "steps": [
            {"step": 0, "line": 1, "variables": {"x": 1}},
            {"step": 1, "line": 1, "variables": {"x": 2}},
        ],
        "current_step_index": 1,
        "current_line": 1,
        "compile_error": "",
        "algorithm_tags": ["遍历"],
        "expires_at": 1784736000,
    }


def test_fetch_success_populates_state(monkeypatch):
    captured = {}

    def fake_get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse(_success_payload())

    monkeypatch.setattr("tools.fetch_execution_context.httpx.get", fake_get)
    monkeypatch.setenv("JAVATUTOR_EXECUTION_CONTEXT_URL", "http://localhost:8080/api/agent/execution-context")
    monkeypatch.setenv("JAVATUTOR_AGENT_TOKEN", "secret-token")

    out = fetch_execution_context({}, "run-1")

    assert captured["url"] == "http://localhost:8080/api/agent/execution-context/run-1"
    assert captured["headers"]["X-Agent-Token"] == "secret-token"
    assert out["source_code"] == "public class A { int x = 1; }"
    assert out["current_step_index"] == 1
    assert out["current_variables"] == {"x": 2}
    assert out["fetch_context_failed"] is False
    assert out["run_context_memory"]["run_id"] == "run-1"
    assert "source_code" not in out["run_context_memory"]
    assert "steps" not in out["run_context_memory"]


def test_fetch_non_200_returns_failure(monkeypatch):
    class ErrorResponse:
        status_code = 404

        def json(self):
            return {}

    monkeypatch.setattr("tools.fetch_execution_context.httpx.get", lambda url, headers, timeout: ErrorResponse())
    monkeypatch.setenv("JAVATUTOR_EXECUTION_CONTEXT_URL", "http://localhost:8080/api/agent/execution-context")
    monkeypatch.setenv("JAVATUTOR_AGENT_TOKEN", "secret-token")

    out = fetch_execution_context({}, "run-1")
    assert out["fetch_context_failed"] is True
    assert "404" in out["fetch_context_error"]
    assert out["fallback_reason"].startswith("fetch_execution_context failed:")


def test_fetch_missing_required_fields_returns_failure(monkeypatch):
    monkeypatch.setattr(
        "tools.fetch_execution_context.httpx.get",
        lambda url, headers, timeout: FakeResponse({"run_id": "run-1"}),
    )
    monkeypatch.setenv("JAVATUTOR_EXECUTION_CONTEXT_URL", "http://localhost:8080/api/agent/execution-context")
    monkeypatch.setenv("JAVATUTOR_AGENT_TOKEN", "secret-token")

    out = fetch_execution_context({}, "run-1")
    assert out["fetch_context_failed"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetch_execution_context.py -q`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: Implement the tool**

创建 `src/tools/fetch_execution_context.py`：

```python
"""从 JavaTutor 后端按 run_id 获取运行上下文。"""

import hashlib
import json
import os
import time
from typing import Any

import httpx

TOOL_SCHEMA = {
    "name": "fetch_execution_context",
    "description": "从 JavaTutor 后端获取指定 run_id 的源代码、执行步骤和当前执行位置",
    "parameters": {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    },
}


def _current_variables(steps: list[dict], current_step_index: int) -> dict:
    try:
        idx = int(current_step_index)
        if 0 <= idx < len(steps):
            return steps[idx].get("variables", {}) or {}
    except (TypeError, ValueError):
        pass
    return {}


def _failure(error: str, latency_ms: float) -> dict[str, Any]:
    return {
        "fetch_context_failed": True,
        "fetch_context_error": error,
        "fetch_context_latency_ms": latency_ms,
        "fallback_reason": f"fetch_execution_context failed: {error}",
    }


def fetch_execution_context(state: dict, run_id: str | None = None) -> dict[str, Any]:
    """从 JavaTutor 后端获取运行上下文，返回状态更新字典。"""
    started = time.perf_counter()
    resolved_run_id = run_id if run_id is not None else state.get("run_id")
    base_url = os.getenv("JAVATUTOR_EXECUTION_CONTEXT_URL", "").rstrip("/")
    token = os.getenv("JAVATUTOR_AGENT_TOKEN", "")

    if not resolved_run_id:
        return _failure("run_id 为空", 0.0)
    if not base_url:
        return _failure("JAVATUTOR_EXECUTION_CONTEXT_URL 未配置", 0.0)
    if not token:
        return _failure("JAVATUTOR_AGENT_TOKEN 未配置", 0.0)

    headers = {"Accept": "application/json", "X-Agent-Token": token}
    try:
        response = httpx.get(f"{base_url}/{resolved_run_id}", headers=headers, timeout=3.0)
        if response.status_code != 200:
            latency = round((time.perf_counter() - started) * 1000, 1)
            return _failure(f"HTTP {response.status_code}", latency)
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        latency = round((time.perf_counter() - started) * 1000, 1)
        return _failure(type(exc).__name__, latency)

    source_code = data.get("source_code")
    steps = data.get("steps")
    if source_code is None or steps is None:
        latency = round((time.perf_counter() - started) * 1000, 1)
        return _failure("响应缺少 source_code 或 steps", latency)
    if not isinstance(steps, list):
        latency = round((time.perf_counter() - started) * 1000, 1)
        return _failure("steps 不是数组", latency)

    current_step_index = data.get("current_step_index", 0)
    current_line = data.get("current_line", 1)
    current_variables = _current_variables(steps, current_step_index)
    latency = round((time.perf_counter() - started) * 1000, 1)

    return {
        "run_id": resolved_run_id,
        "source_code": source_code,
        "steps": steps,
        "steps_json": json.dumps(steps, ensure_ascii=False),
        "steps_count": len(steps),
        "has_steps": bool(steps),
        "current_step_index": current_step_index,
        "current_line": current_line,
        "current_variables": current_variables,
        "compile_error": data.get("compile_error", ""),
        "has_error": bool((data.get("compile_error") or "").strip()),
        "algorithm_tags": data.get("algorithm_tags") or [],
        "fetch_context_failed": False,
        "fetch_context_error": "",
        "fetch_context_latency_ms": latency,
        "run_context_memory": {
            "run_id": resolved_run_id,
            "code_hash": hashlib.sha256(source_code.encode("utf-8")).hexdigest(),
            "steps_count": len(steps),
            "current_step_index": current_step_index,
            "current_line": current_line,
            "algorithm_tags": data.get("algorithm_tags") or [],
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetch_execution_context.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/tools/fetch_execution_context.py tests/test_fetch_execution_context.py
git commit -m "feat: add deterministic execution context fetch tool"
```

---

### Task 3: `fetch_execution_context_node` 与 graph 装配

**Files:**
- Create: `src/graphs/javatutor/fetch_context.py`
- Modify: `src/graphs/javatutor/graph.py`
- Test: `tests/test_fetch_context_node.py`
- Modify: `tests/test_graph.py`

**Interfaces:**
- Consumes: `tools.fetch_execution_context.fetch_execution_context`。
- Produces: `fetch_execution_context_node(state) -> dict`。

- [ ] **Step 1: Write failing tests**

创建 `tests/test_fetch_context_node.py`：

```python
from graphs.javatutor.fetch_context import fetch_execution_context_node


def test_failed_fetch_with_legacy_steps_keeps_legacy_context(monkeypatch):
    def fake_fetch(state, run_id=None):
        return {
            "fetch_context_failed": True,
            "fetch_context_error": "HTTP 404",
            "fallback_reason": "fetch_execution_context failed: HTTP 404",
        }

    monkeypatch.setattr("graphs.javatutor.fetch_context.fetch_execution_context", fake_fetch)
    state = {
        "run_id": "run-1",
        "source_code": "public class A {}",
        "steps": [{"step": 0, "line": 1, "variables": {}}],
        "has_steps": True,
    }
    out = fetch_execution_context_node(state)
    assert out["fetch_context_failed"] is True
    assert out["fallback_reason"] == ""


def test_failed_fetch_without_legacy_steps_sets_fallback(monkeypatch):
    def fake_fetch(state, run_id=None):
        return {
            "fetch_context_failed": True,
            "fetch_context_error": "HTTP 404",
            "fallback_reason": "fetch_execution_context failed: HTTP 404",
        }

    monkeypatch.setattr("graphs.javatutor.fetch_context.fetch_execution_context", fake_fetch)
    out = fetch_execution_context_node({"run_id": "run-1", "has_steps": False})
    assert out["fallback_reason"].startswith("fetch_execution_context failed:")
```

在 `tests/test_graph.py` 的 `test_build_flow_graph_structure` 中追加：

```python
        assert "fetch_execution_context" in graph.nodes
```

并在类中新增：

```python
    def test_graph_wires_fetch_before_compaction(self):
        graph = build_flow_graph()
        assert ("parse_context", "fetch_execution_context") in graph.edges
        assert ("fetch_execution_context", "context_compaction") in graph.edges
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetch_context_node.py tests/test_graph.py -q`
Expected: FAIL，`ModuleNotFoundError` 或节点/边缺失。

- [ ] **Step 3: Implement node**

创建 `src/graphs/javatutor/fetch_context.py`：

```python
"""fetch_execution_context 确定性 graph 节点。"""

from tools.fetch_execution_context import fetch_execution_context


def fetch_execution_context_node(state: dict) -> dict:
    result = fetch_execution_context(state, state.get("run_id"))
    # 旧 payload 已提供完整执行数据时，fetch 失败也不触发固定降级文案。
    if (
        result.get("fetch_context_failed")
        and state.get("has_steps")
        and (state.get("source_code") or "").strip()
    ):
        result["fallback_reason"] = ""
    return result
```

- [ ] **Step 4: Wire graph**

在 `src/graphs/javatutor/graph.py` 中：

```python
from graphs.javatutor.fetch_context import fetch_execution_context_node
```

在 `build_flow_graph` 中新增节点与边：

```python
    graph.add_node("fetch_execution_context", fetch_execution_context_node)
    graph.add_edge("parse_context", "fetch_execution_context")
    graph.add_edge("fetch_execution_context", "context_compaction")
```

删除原先的：

```python
    graph.add_edge("parse_context", "context_compaction")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetch_context_node.py tests/test_graph.py -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/graphs/javatutor/fetch_context.py src/graphs/javatutor/graph.py tests/test_fetch_context_node.py tests/test_graph.py
git commit -m "feat: wire deterministic execution context fetch node"
```

---

### Task 4: 主 Agent 降级与运行摘要注入上下文

**Files:**
- Modify: `src/graphs/javatutor/main_agent.py`
- Modify: `src/graphs/javatutor/context_builder.py`
- Test: `tests/test_main_agent.py`
- Test: `tests/test_context_builder.py`

**Interfaces:**
- Consumes: `fetch_context_failed`, `has_steps`, `run_context_memory`。
- Produces: 固定降级回答；`run_context_memory` 进入 Memory section。

- [ ] **Step 1: Write failing tests**

在 `tests/test_main_agent.py` 追加：

```python
def test_main_agent_returns_fixed_fallback_when_context_unavailable():
    state = {
        "context_built": "",
        "fetch_context_failed": True,
        "has_steps": False,
    }
    model = SequenceModel(["模型不应被调用"])
    out = main_agent_node(state, model=model)
    assert "请重新运行代码后再提问" in out["answer"]
    assert out["tool_rounds"] == 0
    assert out["tool_calls"] == []
    assert out["step_memories"] == []
```

在 `tests/test_context_builder.py` 追加：

```python
def test_gather_includes_run_context_memory():
    state = {
        **STATE,
        "run_context_memory": {
            "run_id": "run-1",
            "code_hash": "abc123",
            "steps_count": 2,
            "current_step_index": 1,
            "current_line": 4,
            "algorithm_tags": ["遍历"],
        },
    }
    packets = gather(state, history=[], memories=[])
    combined = "\n".join(p.content for p in packets)
    assert "运行上下文摘要" in combined
    assert "code_hash" in combined
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_main_agent.py tests/test_context_builder.py -q`
Expected: FAIL，断言失败。

- [ ] **Step 3: Add fallback in `main_agent_node`**

在 `src/graphs/javatutor/main_agent.py` 顶部常量区添加：

```python
CONTEXT_UNAVAILABLE_ANSWER = "当前暂时无法获取这次代码运行的执行上下文，请重新运行代码后再提问。"
```

在 `main_agent_node` 函数体开头、`rounds = 0` 之前插入：

```python
    if state.get("fetch_context_failed") and not state.get("has_steps"):
        return {
            "answer": CONTEXT_UNAVAILABLE_ANSWER,
            "tool_rounds": 0,
            "tool_calls": [],
            "step_memories": [],
        }
```

- [ ] **Step 4: Inject run memory into context builder**

在 `src/graphs/javatutor/context_builder.py` 的 `gather` 函数中，`analysis` packet 之后插入：

```python
    run_memory = state.get("run_context_memory")
    if run_memory:
        packets.append(
            ContextPacket(
                f"### 运行上下文摘要\n{json.dumps(run_memory, ensure_ascii=False)[:300]}",
                relevance_score=0.85,
                metadata={"section": "Memory"},
            )
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_main_agent.py tests/test_context_builder.py -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/graphs/javatutor/main_agent.py src/graphs/javatutor/context_builder.py tests/test_main_agent.py tests/test_context_builder.py
git commit -m "feat: add context unavailable fallback and run memory"
```

---

### Task 5: 决策痕迹增加 fetch 指标

**Files:**
- Modify: `src/graphs/javatutor/nodes.py:480-520`
- Test: `tests/test_build_final.py`

**Interfaces:**
- Consumes: `run_id`, `fetch_context_failed`, `fetch_context_latency_ms`, `fetch_context_error`。
- Produces: `decision_trace` 中同名字段。

- [ ] **Step 1: Write failing test**

在 `tests/test_build_final.py` 追加：

```python
def test_build_final_trace_includes_fetch_metrics():
    state = {
        "answer": "回答",
        "run_id": "run-1",
        "fetch_context_failed": False,
        "fetch_context_latency_ms": 12.3,
        "fetch_context_error": "",
        "intent": "data_query",
        "retrieved_chunks": [],
        "tool_calls": [],
    }
    out = build_final(state)
    trace = out["decision_trace"]
    assert trace["run_id"] == "run-1"
    assert trace["fetch_context_failed"] is False
    assert trace["fetch_context_latency_ms"] == 12.3
    assert trace["fetch_context_error"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_build_final.py::test_build_final_trace_includes_fetch_metrics -q`
Expected: FAIL，`KeyError: 'run_id'`。

- [ ] **Step 3: Add trace fields**

在 `build_final` 的 `trace` 字典中、`"intent"` 之前插入：

```python
        "run_id": state.get("run_id", ""),
        "fetch_context_failed": state.get("fetch_context_failed", False),
        "fetch_context_latency_ms": state.get("fetch_context_latency_ms", 0.0),
        "fetch_context_error": state.get("fetch_context_error", ""),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_build_final.py::test_build_final_trace_includes_fetch_metrics -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/graphs/javatutor/nodes.py tests/test_build_final.py
git commit -m "feat: expose execution context fetch metrics in trace"
```

---

### Task 6: 图级成功与失败路径

**Files:**
- Modify: `tests/test_graph.py`

**Interfaces:**
- Consumes: Task 1-5 的全部接口。
- Produces: 两个图级回归测试。

- [ ] **Step 1: Write failing tests**

在 `tests/test_graph.py` 追加：

```python
def test_graph_fetches_execution_context_from_new_envelope(monkeypatch):
    def fake_fetch(state, run_id=None):
        return {
            "run_id": "run-1",
            "source_code": "public class A {}",
            "steps": [
                {"step": 0, "line": 1, "variables": {"x": 1}},
                {"step": 1, "line": 1, "variables": {"x": 2}},
            ],
            "steps_json": json.dumps(
                [
                    {"step": 0, "line": 1, "variables": {"x": 1}},
                    {"step": 1, "line": 1, "variables": {"x": 2}},
                ],
                ensure_ascii=False,
            ),
            "steps_count": 2,
            "has_steps": True,
            "current_step_index": 1,
            "current_line": 1,
            "current_variables": {"x": 2},
            "compile_error": "",
            "has_error": False,
            "algorithm_tags": [],
            "fetch_context_failed": False,
            "fetch_context_error": "",
            "fetch_context_latency_ms": 1.0,
            "run_context_memory": {
                "run_id": "run-1",
                "code_hash": "abc",
                "steps_count": 2,
                "current_step_index": 1,
                "current_line": 1,
                "algorithm_tags": [],
            },
        }

    monkeypatch.setattr("graphs.javatutor.fetch_context.fetch_execution_context", fake_fetch)

    class DeepModel:
        def invoke(self, messages):
            content = messages[0].content
            if "算法分析" in content or "源代码" in content:
                return AIMessage(content='{"complexity": {"time": "O(1)"}}')
            if "教学主 Agent" in content:
                return AIMessage(content="x 在第 2 步变成了 2")
            if "回答评审" in content:
                return AIMessage(content='{"pass": true, "issues": []}')
            if "回答修订者" in content:
                return AIMessage(content="x 在第 2 步变成了 2")
            return AIMessage(content="回答")

    payload = {
        "run_id": "run-1",
        "session_id": "session-1",
        "user_question": "x 怎么变了？",
        "intent": "data_query",
        "compile_error": "",
    }
    result = build_agent().builder.compile().invoke(
        {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]},
        config={"configurable": {"chat_model": DeepModel()}},
    )
    assert result.get("source_code") == "public class A {}"
    assert result.get("steps_count") == 2
    assert result.get("decision_trace", {}).get("run_id") == "run-1"


def test_graph_fetch_failure_without_legacy_payload_returns_fixed_fallback(monkeypatch):
    def fake_fetch(state, run_id=None):
        return {
            "fetch_context_failed": True,
            "fetch_context_error": "HTTP 404",
            "fetch_context_latency_ms": 1.0,
            "fallback_reason": "fetch_execution_context failed: HTTP 404",
        }

    monkeypatch.setattr("graphs.javatutor.fetch_context.fetch_execution_context", fake_fetch)

    class DeepModel:
        def invoke(self, messages):
            content = messages[0].content
            if "算法分析" in content or "源代码" in content:
                return AIMessage(content='{"complexity": {"time": "O(1)"}}')
            return AIMessage(content="回答")

    payload = {
        "run_id": "run-1",
        "session_id": "session-1",
        "user_question": "x 怎么变了？",
        "intent": "data_query",
        "compile_error": "",
    }
    result = build_agent().builder.compile().invoke(
        {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]},
        config={"configurable": {"chat_model": DeepModel()}},
    )
    assert "请重新运行代码后再提问" in result.get("answer", "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph.py -q`
Expected: 新增图级用例失败。

- [ ] **Step 3: Fix any integration defects exposed by tests**

预期 Task 1-5 已覆盖实现，此步骤主要处理 fake model 路由差异或图 state 合并问题。修复后重跑：

Run: `uv run pytest tests/test_graph.py -q`

- [ ] **Step 4: Run full Coze test suite**

Run: `uv run pytest -q`
Expected: 全部通过，无回归。

- [ ] **Step 5: Commit**

```bash
git add tests/test_graph.py
git commit -m "test: cover execution context fetch success and fallback paths"
```

---

## Self-Review

- Spec 覆盖：新 envelope 解析、fetch 工具、确定性节点、graph 装配、旧 payload 兼容、失败降级、运行摘要、决策痕迹指标均已落到 Task 1-6。
- 占位扫描：无 `TBD` / `TODO` / “适当处理”等空泛步骤。
- 类型一致性：`fetch_execution_context` 返回字段与 state、`run_context_memory`、`build_final` 中使用的字段名一致。
- 额外风险：Task 6 中 fake fetch 必须在 `graphs.javatutor.fetch_context` 模块路径打 patch，因为 graph 节点导入的是该模块内的函数引用。
