# 执行计划：fetch_execution_context 改为 agent 自由调用的读取工具（纯 state 读取）

> 执行依据：`docs/spec/2026-08-30-fetch-execution-context-as-tool-design.md`。
> **已选定方案 A**：后端恢复完整 envelope，读取工具 **纯 state 读取**（不再发 HTTP，不依赖后端 30 分钟快照）。
> **前置依赖**：后端 `CozeService.java` 恢复完整 envelope（见 `javatutor` 仓 `docs/plan/2026-08-30-execution-context-envelope-token-plan.md`）；本计划只改 `javatutor-coze` 仓。

## 0. 全局约束（务必遵守）

- **不做任何 git 操作**（不 `git add`/`commit`/`push`/`stash`/`checkout`/`branch`）。读 `git status`/`git diff` 可以。
- **只修改下列文件**；不要动 `src/main.py`、`scripts/`、`.coze/`、`src/storage/`、`src/utils/`、`learning/memory.py`、`pyproject.toml`。
- 测试 patch 模块级引用；`fetch_execution_context` 在 `main_agent.py` 顶部 `from tools.fetch_execution_context import fetch_execution_context`。
- 保持现有命名/风格（中文 docstring、`_` 私有函数、`TypedDict` state）。
- 写 devlog 到 `docs/devlog/2026-08-30-fetch-execution-context-as-tool.md`。

## 1. 改动清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `src/graphs/javatutor/state.py` | 新增 `fetched_context: dict` 字段 |
| 2 | `src/tools/fetch_execution_context.py` | 重构为**纯 state 读取**工具：删 HTTP/env 依赖；读取并暂存 `fetched_context`；返回 code + 摘要；失败给结构化错误；schema 加 `file`/`start_line`/`end_line`（预留） |
| 3 | `src/graphs/javatutor/main_agent.py` | dispatch `fetch_execution_context`；写回 state + 追加结果到 context；记录 tool_call |
| 4 | `src/graphs/javatutor/graph.py` | 删除 `fetch_execution_context_node` 节点与边；docstring 对齐 |
| 5 | `src/graphs/javatutor/fetch_context.py` | 删除文件 |
| 6 | `src/graphs/javatutor/context_builder.py` | `gather()` 不再无条件注入 `### 源代码`（改为仅明确需要才注入） |
| 7 | `src/graphs/javatutor/prompts.py` | `SYSTEM_PROMPT_MAIN_AGENT` 增加对 `fetch_execution_context` 的使用引导 |
| 8 | `src/graphs/javatutor/nodes.py` | 移除 `build_final` 手工补录 fetch 工具的逻辑（414-419 行） |
| 9 | `.env.example` | 删除 `JAVATUTOR_EXECUTION_CONTEXT_URL`、`JAVATUTOR_AGENT_TOKEN` 两行 |
| 10 | 测试 | 更新 `test_fetch_execution_context.py`、`test_main_agent.py`、`test_graph.py`、`test_build_final.py`、`test_context_builder.py` |
| 11 | `docs/agent-collaboration-guide.md` | 同步 fetch 工具定位与 main_agent 工具清单 |

---

## Task 1：state 字段（test-first）

`tests/test_state.py`（若不存在则新建）：

```python
def test_state_has_fetched_context_field():
    from graphs.javatutor.state import JavaTutorState
    s: JavaTutorState = {"fetched_context": {"source_code": "x"}}
    assert s["fetched_context"]["source_code"] == "x"
```

`src/graphs/javatutor/state.py` 在 `# === 执行上下文获取（新 envelope）===` 段新增：

```python
fetched_context: dict
"""读取工具暂存的执行上下文快照：run_id / source_code / steps / current_step_index /
current_line / compile_error / algorithm_tags / code_hash / fetched_at / fetch_context_latency_ms."""
```

## Task 2：fetch_execution_context 重构为纯 state 读取（test-first）

改 `src/tools/fetch_execution_context.py`。测试（`tests/test_fetch_execution_context.py`）删除 HTTP 相关（`monkeypatch.setenv`/`delenv`、httpx mock），改为：

```python
def test_fetch_prefers_state_and_stores_fetched_context():
    from tools.fetch_execution_context import fetch_execution_context
    state = {
        "run_id": "r1",
        "source_code": "public class A {}\npublic class B {}",
        "steps": [{"step_index": 0, "variables": {"x": 1}}],
        "current_step_index": 0,
        "current_line": 1,
    }
    out = fetch_execution_context(state)
    assert out["source_code"] == state["source_code"]
    assert out["steps_count"] == 1
    assert out["fetched_context"]["source_code"] == state["source_code"]
    assert out["fetched_context"]["run_id"] == "r1"
    assert out["stored"] is True


def test_fetch_no_source_or_steps_returns_error():
    from tools.fetch_execution_context import fetch_execution_context
    out = fetch_execution_context({"run_id": "", "source_code": "", "steps": []})
    assert out.get("fetch_context_failed") is True
    assert out.get("error")


def test_fetch_schema_has_file_and_line_params():
    from tools.fetch_execution_context import TOOL_SCHEMA
    props = TOOL_SCHEMA["parameters"]["properties"]
    for k in ("run_id", "file", "start_line", "end_line"):
        assert k in props


def test_fetch_slices_code_by_line_range():
    from tools.fetch_execution_context import fetch_execution_context
    state = {"run_id": "r1", "source_code": "line1\nline2\nline3\nline4", "steps": []}
    out = fetch_execution_context(state, start_line=2, end_line=3)
    assert out["code"] == "line2\nline3"


def test_fetch_does_not_import_httpx_or_os():
    import importlib, sys
    sys.modules.pop("tools.fetch_execution_context", None)
    mod = importlib.import_module("tools.fetch_execution_context")
    assert not hasattr(mod, "httpx")


def test_fetch_sets_compact_run_context_memory_without_code_or_steps():
    from tools.fetch_execution_context import fetch_execution_context
    state = {"run_id": "r1", "source_code": "code", "steps": [{}], "current_step_index": 0, "current_line": 1}
    out = fetch_execution_context(state)
    rcm = out["run_context_memory"]
    assert "source_code" not in rcm and "steps" not in rcm
    assert rcm["steps_count"] == 1
```

实现要点（`src/tools/fetch_execution_context.py`）：

- 删除 `import httpx`。保留 `hashlib`、`json`、`time`。`os` 不再需要（无 env 读取）。
- 删除 `_failure` 中对 `JAVATUTOR_EXECUTION_CONTEXT_URL`/`JAVATUTOR_AGENT_TOKEN` 的检查与 HTTP 分支。
- 新增占位（1-based 行切片）：

```python
def _slice(source: str, start_line=None, end_line=None) -> str:
    if start_line is None and end_line is None:
        return source
    lines = source.splitlines()
    s = int(start_line) - 1 if start_line is not None else 0
    e = int(end_line) if end_line is not None else len(lines)
    s = max(0, s)
    e = min(len(lines), e)
    return "\n".join(lines[s:e])
```

- `fetch_execution_context(state, run_id=None, file=None, start_line=None, end_line=None)`：

```python
def fetch_execution_context(state, run_id=None, file=None, start_line=None, end_line=None):
    resolved_run_id = run_id or state.get("run_id", "")
    source_code = state.get("source_code", "")
    steps = state.get("steps") or []
    if not source_code and not steps:
        return {"error": "当前没有可用的执行上下文（源代码/步骤缺失），请重新运行代码后再提问。",
                "fetch_context_failed": True, "fetch_context_latency_ms": 0.0}
    code = _slice(source_code, start_line, end_line)
    current_step_index = state.get("current_step_index", 0)
    current_line = state.get("current_line", 1)
    current_variables = _current_variables(steps, current_step_index)
    latency = 0.0
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
        "compile_error": state.get("compile_error", ""),
        "has_error": bool((state.get("compile_error") or "").strip()),
        "algorithm_tags": state.get("algorithm_tags") or [],
        "fetch_context_failed": False,
        "fetch_context_error": "",
        "fetch_context_latency_ms": latency,
        "stored": True,
        "fetched_from_state": True,
        "code": code,
        "fetched_context": {
            "run_id": resolved_run_id,
            "source_code": source_code,
            "steps": steps,
            "steps_count": len(steps),
            "current_step_index": current_step_index,
            "current_line": current_line,
            "compile_error": state.get("compile_error", ""),
            "algorithm_tags": state.get("algorithm_tags") or [],
            "code_hash": hashlib.sha256(source_code.encode("utf-8")).hexdigest(),
            "fetched_at": time.time(),
            "fetch_context_latency_ms": latency,
        },
        "run_context_memory": {
            "run_id": resolved_run_id,
            "code_hash": hashlib.sha256(source_code.encode("utf-8")).hexdigest(),
            "steps_count": len(steps),
            "current_step_index": current_step_index,
            "current_line": current_line,
            "algorithm_tags": state.get("algorithm_tags") or [],
        },
    }
```

- `TOOL_SCHEMA` 更新（见 spec §4.2），`run_id`/`file`/`start_line`/`end_line` 均标注为可选/预留；`file` 本轮不改读取来源（无多文件结构），仅占位。
- 保留 `_current_variables` 函数。

> 备注：`file` 参数本轮不生效（state 是单 source_code 快照）。多文件会要求后端/模型支持多文件结构，另走后端快照；本次明确不做。

## Task 3：main_agent 工具循环 dispatch（test-first）

`tests/test_main_agent.py` 增加（沿用现有 `FakeModel` 模式）：

```python
def test_main_agent_dispatches_fetch_execution_context():
    from graphs.javatutor import main_agent
    model = FakeModel('{"tool": "fetch_execution_context", "args": {"run_id": "r1"}}')
    state = {"run_id": "r1", "source_code": "public class A {}", "steps": [{"step_index": 0, "variables": {"x": 1}}],
             "current_step_index": 0, "current_line": 1, "context_built": "context"}
    out = main_agent.main_agent_node(state, model=model)
    assert any(tc["tool"] == "fetch_execution_context" for tc in out["tool_calls"])
    assert out["fetched_context"]["run_id"] == "r1"


def test_main_agent_fetch_failure_appends_error_and_continues():
    from graphs.javatutor import main_agent
    model = FakeModel('{"tool": "fetch_execution_context", "args": {}}')
    out = main_agent.main_agent_node({"run_id": "", "source_code": "", "steps": [], "context_built": "c"}, model=model)
    assert out["answer"]
```

实现（`src/graphs/javatutor/main_agent.py`）：

- `from tools.fetch_execution_context import fetch_execution_context`。
- 顶部初始化 `fetched_state_updates = {}`。
- 在 `if tool["tool"] == "step_facts":` 之前新增：

```python
if tool["tool"] == "fetch_execution_context":
    args = tool.get("args") if isinstance(tool.get("args"), dict) else {}
    tool_calls.append({"tool": "fetch_execution_context", "args": args})
    try:
        result = fetch_execution_context(state, **args)
    except TypeError as exc:
        result = {"error": f"fetch_execution_context 参数非法: {exc}", "fetch_context_failed": True}
    if result.get("error"):
        context += f"\n\n[fetch_execution_context 失败]\n{result['error']}"
    else:
        fetched_ctx = result.get("fetched_context") or {}
        updates = {
            "fetched_context": fetched_ctx,
            "run_id": result.get("run_id", state.get("run_id", "")),
            "fetch_context_failed": False,
            "fetch_context_latency_ms": result.get("fetch_context_latency_ms", 0.0),
            "fetch_context_error": "",
            "run_context_memory": result.get("run_context_memory"),
        }
        for k in ("source_code", "steps", "steps_json", "steps_count", "has_steps",
                  "current_step_index", "current_line", "current_variables",
                  "compile_error", "has_error", "algorithm_tags"):
            if k in result:
                updates[k] = result[k]
        fetched_state_updates.update(updates)
        digest = {k: result.get(k) for k in ("file", "steps_count", "current_step_index",
                                              "current_line", "algorithm_tags") if k in result}
        context += f"\n\n[fetch_execution_context 结果]\n{json.dumps({'stored': True, **digest, 'code': result.get('code', '')}, ensure_ascii=False)}"
```

- 最终 `return {"answer": answer, "tool_rounds": rounds, "tool_calls": tool_calls, "step_memories": step_memories, **fetched_state_updates}`。

## Task 4：graph 移除 fetch 节点（test-first）

`tests/test_graph.py`：

```python
def test_graph_has_no_fetch_node():
    from graphs.javatutor.graph import build_flow_graph
    g = build_flow_graph()
    assert "fetch_execution_context" not in set(g.get_nodes().keys())


def test_graph_parse_context_feeds_compaction():
    from graphs.javatutor.graph import build_flow_graph
    g = build_flow_graph()
    edges = {(e.source, e.target) for e in g.get_edges()}
    assert ("parse_context", "context_compaction") in edges
```

`src/graphs/javatutor/graph.py`：删 import、节点、两条边，改为 `parse_context → context_compaction`；docstring 对齐为不含 fetch 节点的链路。删除 `src/graphs/javatutor/fetch_context.py`。

## Task 5：gather 不无条件注入代码（test-first）

`tests/test_context_builder.py`：

```python
def test_gather_does_not_inject_source_code_without_fetched_context():
    from graphs.javatutor.context_builder import gather
    packets = gather({"user_question": "q", "source_code": "public class A {}"}, history=[], memories=[])
    assert not any("### 源代码" in p.content for p in packets)


def test_gather_injects_position_but_not_code():
    from graphs.javatutor.context_builder import gather
    packets = gather({"user_question": "q", "current_step_index": 1, "current_line": 4,
                      "has_steps": True, "steps_count": 5}, history=[], memories=[])
    texts = [p.content for p in packets]
    assert any("### 当前执行位置" in t for t in texts)
```

`src/graphs/javatutor/context_builder.py` `gather()`：第 58 行 `### 源代码` 包改为「仅当 `state.get("fetched_context")` 含非空 `source_code` 时才注入」；`analyze_code_node` 走独立链路不受影响。

## Task 6：系统提示引导

`src/graphs/javatutor/prompts.py` `SYSTEM_PROMPT_MAIN_AGENT` 在 step_facts 说明后增加：

```
需要读取本次运行代码或执行上下文（源代码、步骤、当前位置）时，先调用 fetch_execution_context 工具：
{"tool": "fetch_execution_context", "args": {}}
它会暂存完整执行上下文；随后可用 step_facts 查询单步证据。
```

## Task 7：main_agent 早期降级守卫

`main_agent_node` 开头 `if state.get("fetch_context_failed") and not state.get("has_steps")` 的早退分支**移除**（`fetch_context_failed` 只在工具失败时置位，且工具错误由 agent 自行降级）。同步删除 `tests/test_main_agent.py` 依赖 `CONTEXT_UNAVAILABLE_ANSWER` 的用例。

## Task 8：build_final 移除重复补录

`src/graphs/javatutor/nodes.py` `build_final`（414-419 行）删除 `if run_id: tool_calls = [...]` 段；`tool_calls` 现在由 `main_agent` 真实产生。`tests/test_build_final.py` 改写：

```python
def test_build_final_preserves_tool_calls_without_injecting_fetch():
    from graphs.javatutor.nodes import build_final
    out = build_final({"run_id": "r1", "answer": "hi", "request_started_at": 0,
                       "tool_calls": [{"tool": "step_facts", "args": {"step_index": 0, "line": 1}}]})
    assert out["decision_trace"]["tool_calls"] == [{"tool": "step_facts", "args": {"step_index": 0, "line": 1}}]
```

## Task 9：.env.example 删除变量

`.env.example` 删除第 33、35 行的 `JAVATUTOR_EXECUTION_CONTEXT_URL=`、`JAVATUTOR_AGENT_TOKEN=`（连带 34 行注释若相关）。工具已不再读取这两个变量。

## Task 10：协作指南同步 + devlog

- `docs/agent-collaboration-guide.md`：把 fetch 相关描述改为「主 Agent 提供的 LLM 工具 `fetch_execution_context`（agent 按需调用，读取并暂存执行上下文）」；更新 main_agent 工具清单；`load_session` 保持不变。
- 写 `docs/devlog/2026-08-30-fetch-execution-context-as-tool.md`：原因、改动（含「纯 state 读取、不再依赖后端 HTTP/快照」）、验证结果、遗留问题（多文件 `file` 仅 schema 预留未实现；后端 envelope 如何同步；需重新发布 Coze agent）。

---

## 验证清单（按序执行）

1. L1 依赖锁：`uv sync --frozen` 应无锁文件变化。
2. L2 全量单测：`uv run pytest -q` 全绿；确认上述测试文件无回归、无 HTTP mock 残留。
3. L3 离线构建：`build_flow_graph().compile()` 成功。
4. L5 外壳约束：未改 `main.py`/`scripts/`/`.coze`/`src/storage`/`src/utils`/`learning/memory.py`；未做任何 git 操作；`fetch_execution_context.py` 无 `httpx`/`os` import。

## 遗留/注意事项

- 本次改动后在 Coze 平台**必须重新发布 agent** 才生效；后端需同步恢复完整 envelope（见 javatutor 仓 plan）才让 `source_code`/`steps` 进入 state。
- `file` 多文件读取仅 schema 预留；多文件需后端/模型支持多文件结构后另做。
- 决策痕迹里 `fetch_execution_context` 记录由 `main_agent` 真实产生，前端无需改。
- 坚持「信息分层原则」，本次未引入新工具（不加 search_knowledge/MemoryTool）。
