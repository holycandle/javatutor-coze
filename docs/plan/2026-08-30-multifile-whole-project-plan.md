# 实施计划：多文件 / 整体项目理解（Phase 2）

> 目的：在 Phase 1（`fetch_execution_context` 纯 state 读取工具 + 后端恢复完整 envelope）基础上，让 agent 具备**整体项目理解 + 跨文件回答**能力。
> 注入策略：**概览+按需读(最省)**——恒注入项目结构概览 + 主入口；其他文件由 agent 经 `fetch_execution_context(file="...")` 按需读。
> 本计划只改 **Coze agent 逻辑**（`javatutor-coze` 仓）。前后端 envelope 改动见 `javatutor` 仓 `docs/plan/2026-08-30-multifile-envelope-plan.md`。

## 0. 全局约束

- **不做任何 git 操作**。
- 只在 `src/`、`tests/`、`docs/` 下新增/修改。
- 不新增外部工具（`search_knowledge` / `read_code` 等）；不把文件全量注入 prompt。
- 保持 `fetch_execution_context` **纯 state 读取**：不引入 `httpx` / `os`（Phase 1 约定）。

## 1. 改动清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `src/tools/fetch_execution_context.py` | 新增 `normalize_files`、激活 `file` 参数、`_resolve_code`；结果加 `project_files` / `files_count` |
| 2 | `src/graphs/javatutor/state.py` | 新增 `files: dict[str, str]` 字段 |
| 3 | `src/graphs/javatutor/nodes.py` | `_parse_json_dict` 解析 payload `files` → `state.files` |
| 4 | `src/graphs/javatutor/context_builder.py` | `gather()` 注入 `### 项目结构` 概览 + 新增 `_file_type_hint` |
| 5 | `src/graphs/javatutor/prompts.py` | `SYSTEM_PROMPT_MAIN_AGENT` 加多文件读取提示 |
| 6 | `tests/test_fetch_execution_context.py` | 新增 file 参数 / normalize_files 用例 |
| 7 | `tests/test_context_builder.py` | 新增概览注入用例 |
| 8 | `docs/spec/2026-08-30-multifile-whole-project-design.md` | 已创建（设计） |

---

## Task 1：工具模块（`src/tools/fetch_execution_context.py`）

### 1.1 新增 `normalize_files`

统一归一化 payload 的 `files` → `dict[str, str]`，供 `nodes.py` 与本模块复用：

```python
def normalize_files(raw) -> dict[str, str]:
    """把 payload.files 归一化为 {name: code}。

    兼容三种形态：
    - dict: {"App.java": "code"}
    - list[{name, code}]
    - list[{path, code}]
    """
    result: dict[str, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, str):
                result[str(k)] = v
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("path")
            code = item.get("code")
            if name and isinstance(code, str):
                result[str(name)] = code
    return result
```

### 1.2 激活 `file` 参数

新增 `_resolve_code`，并让 `fetch_execution_context` 用它替代直接读 `state["source_code"]`：

```python
def _resolve_code(state: dict, file=None) -> tuple[str, str, dict]:
    """返回 (code, file_name, error_or_empty)。

    file 为空 -> 主入口：优先 state.entry_file（若在 files 中），否则 state.source_code；
    file 命中 state.files（精确/忽略大小写/basename）-> 该文件 code；
    未命中 -> error。
    """
    files = state.get("files") or {}
    if file:
        key = None
        if file in files:
            key = file
        else:
            lower = str(file).lower()
            for name in files:
                if name.lower() == lower or os.path.basename(name).lower() == lower:
                    key = name
                    break
        if key is None:
            return "", str(file), {
                "error": f"文件不存在：{file}（项目结构中的文件：{sorted(files)}）",
                "fetch_context_failed": True,
                "fetch_context_latency_ms": 0.0,
            }
        return files[key], key, {}
    entry = state.get("entry_file") or ""
    if entry and entry in files:
        return files[entry], entry, {}
    return state.get("source_code", ""), "", {}
```

> 注意：模块引入了 `os.path.basename`。Phase 1 约定「工具模块不 import `httpx` / `os`（确认无 HTTP/环境变量依赖）」——`os.path` 仅用于取 basename，不读环境变量；若想严格维持「不 import os」，可用 `name.rsplit("/", 1)[-1].rsplit("\\\\", 1)[-1]` 代替。本计划采用 `os.path.basename`（无环境变量副作用），并在测试里说明该放宽。

### 1.3 return 结果调整

在 `fetch_execution_context` 主流程中：

```python
code, file_name, err = _resolve_code(state, file)
if err:
    return err
# ... 后续 code 用上面解析出的 code；result 字段：
current_step_file = _step_file(state, state.get("current_step_index", 0))
"file": file_name,
"code": code,
"current_step_file": current_step_file,   # 当前步所在文件（供 step_facts 对齐）
"fetched_context": {
    ...,
    "current_step_file": current_step_file,
    "project_files": sorted((state.get("files") or {}).keys()),
},
"run_context_memory": {
    ...,
    "files_count": len(state.get("files") or {}),
},
```

新增 `_step_file`（从 steps 当前步取 file，供上述对齐）：

```python
def _step_file(state: dict, current_step_index: int) -> str:
    steps = state.get("steps") or []
    try:
        idx = int(current_step_index)
        if 0 <= idx < len(steps):
            return steps[idx].get("file", "") or ""
    except (TypeError, ValueError):
        pass
    return ""
```

保持 `source_code` 仍为 `state.get("source_code", "")`（主入口行号锚点）。

---

## Task 2：状态字段（`src/graphs/javatutor/state.py`）

新增：

```python
files: dict[str, str]
"""项目全部文件：文件名 -> 源码。来自入站 payload 的 files，经 normalize_files 归一化。

source_code 仍是行号映射锚点（由 entry_file 锚定，缺省为激活文件）；files 供 agent 按需读取其他文件。"""

entry_file: str
"""主入口文件名（可选）。存在时 fetch_execution_context 无 file 参数时默认读该文件；行号锚点=该文件。"""

current_step_file: str
"""当前步（steps[current_step_index]）所在文件，来自该 step 的 file 字段。供 agent 自证「当前步在哪个文件」，step_facts 据此对齐。"""
```

---

## Task 3：解析入口（`src/graphs/javatutor/nodes.py`）

`_parse_json_dict` 增加读 files + 归一化，并写回状态更新：

```python
from graphs.javatutor.fetch_execution_context import normalize_files  # 或相对导入

# 在函数开头：
files = normalize_files(data.get("files"))
entry_file = str(data.get("entry_file") or "")
current_step_file = ""
if isinstance(steps, list) and 0 <= current_step_index < len(steps):
    current_step_file = steps[current_step_index].get("file", "") or ""

# return dict 增加：
"files": files,
"entry_file": entry_file,
"current_step_file": current_step_file,
```

> 导入路径以该仓 `src/` 作为根、既有 import 风格为准（Phase 1 已多处 `from tools...` / `from graphs...`）。

---

## Task 4：上下文工程（`src/graphs/javatutor/context_builder.py`）

### 4.1 新增 `_file_type_hint`

```python
_TYPE_RE = re.compile(r"\b(?:class|interface|record|enum|@interface)\s+([A-Za-z_][\w]*)")

def _file_type_hint(code: str) -> str:
    """从代码里提炼类型提示：首个 class/interface/record/enum 名，无则行数。"""
    m = _TYPE_RE.search(code or "")
    if m:
        return m.group(1)
    lines = (code or "").splitlines()
    return f"{len(lines)} 行"
```

### 4.2 `gather()` 注入概览

在 `gather()` 的 `run_memory` 包之后、`source_code` 之前（或 `Evidence` 区开头）插入（仅在 `state.files` 非空时）：

```python
project_files = state.get("files") or {}
if project_files:
    overview_lines = [
        f"- {name} — {_file_type_hint(code)}"
        for name, code in sorted(project_files.items())
    ]
    packets.append(
        ContextPacket(
            "### 项目结构\n" + "\n".join(overview_lines)
            + "\n\n需要某个文件内容时，用 fetch_execution_context 的 file 参数读取；默认读主入口。",
            relevance_score=0.75,
            metadata={"section": "Evidence"},
        )
    )
```

- `### 源代码` 包逻辑保持 Phase 1（仅当 `fetched_context.source_code` 存在时注入），**不要**改成注入某个文件。

---

## Task 5：Prompt（`src/graphs/javatutor/prompts.py`）

`SYSTEM_PROMPT_MAIN_AGENT` 追加：

> 这是一个 Java 项目，可能包含多个文件。`### 项目结构` 列出了所有文件及主要类型；`当前执行位置` 会标注当前步所在文件（`current_step_file`）与行号。回答涉及多个文件、类之间关系、或需要查看非主入口代码的问题，请调用 `fetch_execution_context` 的 `file` 参数读取对应文件；若需查看当前步所在文件且它与默认读取的主入口不同，用 `file` 参数读取那个文件，默认读取主入口。

---

## Task 6：测试（`tests/test_fetch_execution_context.py`）

新增用例：

```python
def test_file_param_reads_from_state_files():
    state = {
        "source_code": "class Main {}",
        "files": {"A.java": "class A {}", "B.java": "class B {}"},
        "steps": [], "run_id": "r1",
    }
    r = fetch_execution_context(state, file="B.java")
    assert r["code"] == "class B {}"
    assert r["file"] == "B.java"
    assert "B.java" in r["fetched_context"]["project_files"]
    assert r["run_context_memory"]["files_count"] == 2

def test_file_param_case_insensitive_basename():
    state = {"source_code": "", "files": {"src/App.java": "class App {}"}, "steps": []}
    r = fetch_execution_context(state, file="app.java")   # 忽略大小写/basename
    assert r["code"] == "class App {}"

def test_file_param_not_found_returns_error():
    state = {"source_code": "", "files": {"A.java": "..."}, "steps": []}
    r = fetch_execution_context(state, file="Nope.java")
    assert r.get("error") and r.get("fetch_context_failed") is True
    assert "Nope.java" in r["error"]

def test_default_reads_main_entry():
    state = {"source_code": "class Main {}", "files": {"A.java": "..."}, "steps": []}
    r = fetch_execution_context(state)
    assert r["code"] == "class Main {}"
    assert r["file"] == ""

def test_default_prefers_entry_file():
    state = {
        "source_code": "class Active {}",
        "entry_file": "App.java",
        "files": {"App.java": "class App {}", "B.java": "..."},
        "steps": [],
    }
    r = fetch_execution_context(state)
    assert r["code"] == "class App {}"
    assert r["file"] == "App.java"          # 默认读 entry_file，而非激活文件

def test_current_step_file_propagated():
    state = {
        "source_code": "class Main {}", "steps": [
            {"step": 0, "file": "Other.java", "variables": {}},
        ],
        "current_step_index": 0, "files": {"Other.java": "class Other {}", "Main.java": "..."},
    }
    r = fetch_execution_context(state)
    assert r["current_step_file"] == "Other.java"
    assert r["fetched_context"]["current_step_file"] == "Other.java"

def test_normalize_files_variants():
    assert normalize_files({"A.java": "c"}) == {"A.java": "c"}
    assert normalize_files([{"name": "B.java", "code": "c"}]) == {"B.java": "c"}
    assert normalize_files([{"path": "C.java", "code": "c"}]) == {"C.java": "c"}
    assert normalize_files(None) == {}
    assert normalize_files([{"name": "D.java"}]) == {}

def test_no_http_env_dependency_in_tool_module():
    import src.tools.fetch_execution_context as mod
    assert not hasattr(mod, "httpx")
    # 仅放宽：允许 os.path.basename；不读环境变量
```

## Task 7：测试（`tests/test_context_builder.py`）

新增用例：

```python
def test_gather_injects_project_overview():
    state = {
        "user_question": "跨文件关系？",
        "files": {"A.java": "class A {}", "B.java": "interface B"},
        "retrieved_chunks": [], "analysis_result": None,
        "run_context_memory": None,
    }
    packets = gather(state)
    overview = [p for p in packets if p.metadata.get("section") == "Evidence"
                and p.content.startswith("### 项目结构")]
    assert overview, "应注入项目结构概览"
    assert "A.java" in overview[0].content and "B.java" in overview[0].content
    assert "_file_type" not in overview[0].content  # 实际类型名而非代码

def test_gather_without_files_no_overview():
    state = {"user_question": "q", "files": {}, "retrieved_chunks": []}
    packets = gather(state)
    assert not any(p.content.startswith("### 项目结构") for p in packets)
```

---

## Task 8：`step_facts` 按当前步文件取证据（`src/tools/step_facts.py`）

**背景**：多文件项目里 `steps[i]` 自带 `file`，当前步的 `source_code` 只锚定入口/激活文件；若当前步位于其它文件，仍用 `source_code` 取行号则错位。故 `step_facts` 应优先按当前步所在文件读取。

在 `step_facts` 取代码/证据处改为：

```python
def _evidence_source(state, args) -> tuple[str, str]:
    """返回 (file_name, code)。定位只认「当前执行步」所在文件；单文件时退回 source_code。

    用户/前端切换到哪个文件（source_code / 激活文件）不参与定位。
    """
    current_file = args.get("file") or state.get("current_step_file") or ""
    files = state.get("files") or {}
    if current_file and current_file in files:
        return current_file, files[current_file]
    return "", state.get("source_code", "")
```

- `step_facts(state, step_index=...)`：用 `_evidence_source` 取代直接用 `state["source_code"]`；同一 step 的行号现在就落在**正确的文件**上。
- 返回 `evidence` 中附 `file`，agent 可明确「这条证据来自哪个文件」。

## Task 9：行为回归

- 未读工具、未传 files 时：行为与 Phase 1 完全一致（不注入概览、`source_code` 仅在 fetched_context 后注入）。
- 决策痕迹 `tool_calls` 记录 `fetch_execution_context`（含 `file` 参数），前端通用分支渲染为 `调用 fetch_execution_context：file=...`，无需改前端。
- 单文件模式：`files` 为空、`entry_file` 为空、`current_step_file` 为空，所有新增分支回退到 Phase 1 逻辑（读 `source_code`），**无回归**。

---

## 验证

```bash
cd javatutor-coze
python -m pytest tests/test_fetch_execution_context.py tests/test_context_builder.py tests/test_step_facts.py -q
```

确认：上述用例通过；既有 Phase 1 用例不回归；`gather` 初始 prompt 不含整段其他文件代码；`step_facts` 多文件下按当前步文件取证据。
