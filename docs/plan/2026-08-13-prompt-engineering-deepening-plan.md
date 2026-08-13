# Prompt Engineering 深度融合实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Coze 侧 JavaTutor 智能体的提示词重构为“领域词汇 + 按意图上下文 + few-shot + 输出契约”的结构化体系，实现与 JavaTutor 真实执行数据和产品语言的深度融合。

**Architecture:** 新增 `src/graphs/javatutor/prompting/` 包（glossary/contexts/fewshots/contracts/versions），`prompts.py` 改为 system 组合器，`nodes.py` 改为调用按意图上下文构建器，`critic.py` 升级为五类事实核查。

**Tech Stack:** Python 3.12、LangGraph 1.x、pytest、FakeListChatModel。

---

## Global Constraints

- 不得修改 `.coze`、`scripts/`、`src/main.py`、`src/storage/`、`src/utils/`。
- 新代码只允许放在 `src/graphs/javatutor/prompting/`、`src/graphs/javatutor/prompts.py`、`src/graphs/javatutor/nodes.py`、`src/graphs/javatutor/critic.py`、`tests/`。
- 禁止 `from src.xxx import ...`。
- 提示词版本常量统一在 `prompting/versions.py` 定义，所有 prompting 模块引用同一常量。
- 上下文数据只能来自 `JavaTutorState`，禁止凭空构造。
- 每意图 few-shot 最多 2 条，必须带“示例”标记。
- 现有专家回答前缀（`【类别名】`）、决策痕迹、RAG 引用不得回归。
- 每个任务 TDD：先写失败测试 → 实现 → 通过 → 提交。

---

## File Structure

| 文件 | 责任 |
|---|---|
| `src/graphs/javatutor/prompting/__init__.py` | 包标记 |
| `src/graphs/javatutor/prompting/versions.py` | `PROMPT_VERSION` 常量 |
| `src/graphs/javatutor/prompting/glossary.py` | 领域词汇表 |
| `src/graphs/javatutor/prompting/contexts.py` | 按意图上下文构建器 |
| `src/graphs/javatutor/prompting/fewshots.py` | 每意图示例 |
| `src/graphs/javatutor/prompting/contracts.py` | 每意图输出契约 |
| `src/graphs/javatutor/prompts.py` | system 组合器（修改） |
| `src/graphs/javatutor/nodes.py` | `_build_expert_messages` 接入新体系（修改） |
| `src/graphs/javatutor/critic.py` | 五类事实核查（修改） |
| `tests/test_prompting.py` | 词汇/版本/示例/契约测试 |
| `tests/test_contexts.py` | 上下文构建器测试 |
| `tests/test_critic.py` | 评审五类核查测试（修改） |
| `tests/test_expert_nodes.py` | 专家消息结构测试（修改） |

---

### Task 1: 领域词汇与提示词版本

**Files:**
- Create: `src/graphs/javatutor/prompting/__init__.py`
- Create: `src/graphs/javatutor/prompting/versions.py`
- Create: `src/graphs/javatutor/prompting/glossary.py`
- Test: `tests/test_prompting.py`

**Interfaces:**
- Produces: `PROMPT_VERSION`（`prompting/versions.py`）、`build_glossary_block() -> str`（`prompting/glossary.py`）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_prompting.py`：

```python
import importlib

from graphs.javatutor.prompting import versions
from graphs.javatutor.prompting.glossary import build_glossary_block


def test_prompt_version_defined():
    assert versions.PROMPT_VERSION.startswith("2026-08-13")


def test_all_prompting_modules_share_version():
    for name in ("glossary", "contexts", "fewshots", "contracts"):
        module = importlib.import_module(f"graphs.javatutor.prompting.{name}")
        assert module.PROMPT_VERSION == versions.PROMPT_VERSION


def test_glossary_block_contains_domain_terms():
    block = build_glossary_block()
    assert "TraceEngine" in block
    assert "变量快照" in block
    assert "堆对象" in block
    assert "栈帧" in block
    assert "控制流" in block
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_prompting.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 实现包与词汇表**

创建 `src/graphs/javatutor/prompting/__init__.py`（空文件）。

创建 `src/graphs/javatutor/prompting/versions.py`：

```python
"""提示词版本常量。修改任何提示词组件时必须递增此版本。"""

PROMPT_VERSION = "2026-08-13-v1"
```

创建 `src/graphs/javatutor/prompting/glossary.py`：

```python
"""JavaTutor 领域词汇表，注入 system prompt，统一产品语言。"""

from graphs.javatutor.prompting.versions import PROMPT_VERSION

GLOSSARY = {
    "TraceEngine": "JavaTutor 后端的逐步执行引擎，产出 steps 执行步骤数据。",
    "steps": "执行步骤数组，每步包含 line、variables、heap、stackFrames、output。",
    "变量快照": "某一步执行后所有局部变量/参数的当前值集合，前端显示为变量卡片。",
    "堆对象": "学生代码中 new 出来的复杂对象，前端在堆面板展示。",
    "栈帧": "方法调用栈中的一层，包含方法名、参数和局部变量。",
    "高亮行": "前端根据当前步骤行号高亮的源代码行。",
    "控制流": "前端流程面板展示的方法级流程图。",
    "单步播放": "前端逐步播放 steps 的能力。",
    "运行输出": "程序执行期间 System.out 捕获的输出，前端显示在控制台。",
    "算法标签": "analyze 专家输出的算法/数据结构分类标签。",
}


def build_glossary_block() -> str:
    lines = [f"- {term}: {desc}" for term, desc in GLOSSARY.items()]
    return "术语表：\n" + "\n".join(lines)
```

此时 `contexts.py`、`fewshots.py`、`contracts.py` 尚未创建，`test_all_prompting_modules_share_version` 仍会失败；先按后续任务依次创建。

- [ ] **Step 4: 运行测试确认部分通过**

Run: `uv run pytest tests/test_prompting.py -v`
Expected: 至少 `test_prompt_version_defined`、`test_glossary_block_contains_domain_terms` 通过；版本一致性测试因缺模块失败。

- [ ] **Step 5: 提交**

```bash
git add src/graphs/javatutor/prompting tests/test_prompting.py
git commit -m "feat: add prompt versioning and domain glossary"
```

---

### Task 2: 按意图上下文构建器

**Files:**
- Create: `src/graphs/javatutor/prompting/contexts.py`
- Test: `tests/test_contexts.py`

**Interfaces:**
- Produces: `build_data_query_context(state) -> str`、`build_concept_context(state) -> str`、`build_debug_context(state) -> str`、`build_other_context(state) -> str`、`build_facts_block(state) -> str`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_contexts.py`：

```python
import json

from graphs.javatutor.prompting.contexts import (
    build_concept_context,
    build_data_query_context,
    build_debug_context,
    build_facts_block,
    build_other_context,
)


BASE = {
    "source_code": "public class A {\n    void run() {\n        int x = 1;\n    }\n}",
    "steps": [
        {"step": 0, "line": 3, "variables": {"x": 1}, "heap": {}, "stackFrames": [], "output": None},
        {"step": 1, "line": 3, "variables": {"x": 2}, "heap": {"h1": {"type": "Object"}}, "stackFrames": [{"method": "run"}], "output": "hello"},
    ],
    "steps_json": "[]",
    "steps_count": 2,
    "has_steps": True,
    "current_step_index": 1,
    "current_line": 3,
    "current_variables": {"x": 2},
    "user_question": "为什么 x 变了？",
    "compile_error": "",
    "intent": "data_query",
    "algorithm_tags": ["排序"],
    "retrieved_chunks": [],
}


def test_data_query_context_has_line_snapshot_diff():
    ctx = build_data_query_context(BASE)
    assert "int x = 1" in ctx  # 当前行代码
    assert "变量快照" in ctx
    assert "堆对象" in ctx
    assert "栈帧" in ctx
    assert "输出" in ctx
    assert "与上一步对比" in ctx
    assert "x: 1 → 2" in ctx


def test_debug_context_has_compile_error():
    ctx = build_debug_context({**BASE, "compile_error": "error: ';' expected"})
    assert "编译错误" in ctx
    assert "';' expected" in ctx


def test_context_has_method_and_tags():
    ctx = build_concept_context({**BASE, "method_name": "run", "method_signature": "void run()"})
    assert "方法名: run" in ctx
    assert "算法标签: 排序" in ctx


def test_facts_block_contains_real_fields():
    facts = build_facts_block(BASE)
    assert "堆对象" in facts
    assert "栈帧" in facts
    assert "输出" in facts


def test_out_of_range_line_is_placeholder():
    ctx = build_other_context({**BASE, "current_line": 999})
    assert "(行号超出范围)" in ctx
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_contexts.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 实现上下文构建器**

创建 `src/graphs/javatutor/prompting/contexts.py`：

```python
"""按意图构建专家上下文的模块。上下文数据只能来自 state。"""

import json
from typing import Any

from graphs.javatutor.prompting.versions import PROMPT_VERSION


def _current_line_text(state: dict[str, Any]) -> str:
    source = state.get("source_code", "")
    line = state.get("current_line")
    try:
        idx = int(line) - 1
        lines = source.splitlines()
        if 0 <= idx < len(lines):
            return lines[idx].strip()
    except (TypeError, ValueError):
        pass
    return "(行号超出范围)"


def _step_snapshot(state: dict[str, Any]) -> str:
    steps = state.get("steps") or []
    index = state.get("current_step_index", 0)
    try:
        idx = int(index)
        step = steps[idx]
    except (IndexError, TypeError, ValueError):
        return "### 当前步骤\n（该步骤数据不可用）"
    lines = [f"### 当前步骤（第 {idx + 1} 步，行 {step.get('line', '')}）"]
    lines.append(f"- 行代码：`{_current_line_text(state)}`")
    lines.append(f"- 变量快照：```json\n{json.dumps(step.get('variables', {}), ensure_ascii=False, indent=2)}\n```")
    heap = step.get("heap", {})
    lines.append(f"- 堆对象：```json\n{json.dumps(heap, ensure_ascii=False, indent=2) if heap else '（该步骤无堆数据）'}\n```")
    frames = step.get("stackFrames", [])
    lines.append(f"- 栈帧：```json\n{json.dumps(frames, ensure_ascii=False, indent=2) if frames else '（该步骤无栈帧）'}\n```")
    output = step.get("output")
    lines.append(f"- 输出：`{output if output is not None else '（无输出）'}`")
    return "\n".join(lines)


def _adjacent_diff(state: dict[str, Any]) -> str:
    steps = state.get("steps") or []
    index = state.get("current_step_index", 0)
    try:
        idx = int(index)
        prev = steps[idx - 1]
        cur = steps[idx]
    except (IndexError, TypeError, ValueError):
        return ""
    prev_vars = prev.get("variables", {})
    cur_vars = cur.get("variables", {})
    changes = []
    for key in sorted(set(prev_vars) | set(cur_vars)):
        if prev_vars.get(key) != cur_vars.get(key):
            changes.append(
                f"- {key}: {json.dumps(prev_vars.get(key), ensure_ascii=False)} → "
                f"{json.dumps(cur_vars.get(key), ensure_ascii=False)}"
            )
    return "### 与上一步对比\n" + "\n".join(changes) if changes else ""


def _method_context(state: dict[str, Any]) -> str:
    parts = []
    if state.get("method_name"):
        parts.append(f"- 方法名: {state.get('method_name')}")
    if state.get("method_signature"):
        parts.append(f"- 方法签名: {state.get('method_signature')}")
    tags = state.get("algorithm_tags") or []
    if tags:
        parts.append(f"- 算法标签: {', '.join(tags)}")
    return "\n".join(parts)


def _rag_block(state: dict[str, Any]) -> str:
    chunks = state.get("retrieved_chunks") or []
    if not chunks:
        return ""
    refs = "\n".join(f"- {c['source']}: {c['content'][:200]}" for c in chunks)
    return f"### 知识库参考\n{refs}\n回答中如引用知识库内容，必须标注「参考知识库：来源名」。"


def _base_context(state: dict[str, Any]) -> list[str]:
    parts = [
        f"### 用户问题\n{state.get('user_question', '')}",
        f"\n### 源代码\n```java\n{state.get('source_code', '')}\n```",
    ]
    if state.get("has_steps"):
        parts.append("\n" + _step_snapshot(state))
        diff = _adjacent_diff(state)
        if diff:
            parts.append("\n" + diff)
    method = _method_context(state)
    if method:
        parts.append("\n### 方法上下文\n" + method)
    return parts


def _with_rag(parts: list[str], state: dict[str, Any]) -> str:
    rag = _rag_block(state)
    if rag:
        parts.append("\n" + rag)
    return "\n".join(parts)


def build_data_query_context(state: dict[str, Any]) -> str:
    return _with_rag(_base_context(state), state)


def build_concept_context(state: dict[str, Any]) -> str:
    return _with_rag(_base_context(state), state)


def build_debug_context(state: dict[str, Any]) -> str:
    parts = _base_context(state)
    parts.append(f"\n### 编译错误\n{state.get('compile_error', '')}")
    return _with_rag(parts, state)


def build_other_context(state: dict[str, Any]) -> str:
    return _with_rag(_base_context(state), state)


def build_facts_block(state: dict[str, Any]) -> str:
    lines = [
        f"学生问题：{state.get('user_question', '')}",
        f"编译错误：{state.get('compile_error', '')}",
    ]
    if state.get("has_steps"):
        lines.append(_step_snapshot(state))
    method = _method_context(state)
    if method:
        lines.append("\n### 方法上下文\n" + method)
    return _with_rag(lines, state)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_contexts.py -v`
Expected: 5 passed。

- [ ] **Step 5: 提交**

```bash
git add src/graphs/javatutor/prompting/contexts.py tests/test_contexts.py
git commit -m "feat: add per-intent context builders grounded in real execution data"
```

---

### Task 3: Few-Shot 示例

**Files:**
- Create: `src/graphs/javatutor/prompting/fewshots.py`
- Modify: `tests/test_prompting.py`

**Interfaces:**
- Produces: `get_few_shots(intent: str) -> list[str]`，每意图最多 2 条。

- [ ] **Step 1: 写失败测试**

在 `tests/test_prompting.py` 追加：

```python
from graphs.javatutor.prompting.fewshots import get_few_shots


def test_few_shots_max_two_and_marked():
    for intent in ("data_query", "concept", "debug", "other"):
        shots = get_few_shots(intent)
        assert 0 < len(shots) <= 2
        for shot in shots:
            assert "示例" in shot
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_prompting.py::test_few_shots_max_two_and_marked -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 实现 few-shots**

创建 `src/graphs/javatutor/prompting/fewshots.py`：

```python
"""每意图 few-shot 示例。示例中的步骤号/行号/变量名必须替换为本次真实数据。"""

from graphs.javatutor.prompting.versions import PROMPT_VERSION

MARKER = "（示例，步骤号/行号/变量名必须替换为本次真实数据）"

FEW_SHOTS = {
    "data_query": [
        f"{MARKER}\n问：为什么第 2 步 arr[1] 变成了 5？\n"
        "答：第 2 步（第 4 行）进入内层循环，比较 arr[0]=5 与 arr[1]=3，5>3 触发交换，"
        "所以 arr[1] 由 3 变成 5，arr[0] 由 5 变成 3。",
        f"{MARKER}\n问：此时 mid 是多少？\n"
        "答：第 5 步（第 8 行）mid = (low + high) / 2 = (0 + 7) / 2 = 3，当前查找区间是 arr[3..7]。",
    ],
    "concept": [
        f"{MARKER}\n问：冒泡排序原理是什么？\n"
        "答：冒泡排序每轮把未排序区间的最大值“冒泡”到末尾：内层循环相邻比较，逆序则交换。"
        "你的代码第 4-6 行就是比较与交换，外层第 3 行控制轮数。",
        f"{MARKER}\n问：二分查找时间复杂度为什么是 O(log n)？\n"
        "答：每轮把查找区间减半，n 个数最多 log2(n) 轮；你的代码第 7 行每次重新计算 mid。",
    ],
    "debug": [
        f"{MARKER}\n问：编译报错 cannot find symbol 怎么改？\n"
        "答：错误在第 5 行使用变量 total，但前面没有声明；要么补 `int total = 0;`，要么检查拼写。",
        f"{MARKER}\n问：NullPointerException 出现在第 9 行，为什么？\n"
        "答：第 9 行对 null 的 list 调用了 size()；回溯第 3 行初始化，确认 list 是否真的被赋值。",
    ],
    "other": [
        f"{MARKER}\n问：这个工具怎么用？\n"
        "答：先在左侧写代码并点击运行，右侧「变量」看逐步快照，「流程」看控制流，有问题可以继续问我。",
        f"{MARKER}\n问：你是什么？\n"
        "答：我是 JavaTutor 的 AI 助教，负责讲解你的 Java 代码如何执行，以及帮你排查问题。",
    ],
}


def get_few_shots(intent: str) -> list[str]:
    return FEW_SHOTS.get(intent, FEW_SHOTS["other"])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_prompting.py -v`
Expected: 全部通过（含 Task 1 用例）。

- [ ] **Step 5: 提交**

```bash
git add src/graphs/javatutor/prompting/fewshots.py tests/test_prompting.py
git commit -m "feat: add per-intent few-shot examples"
```

---

### Task 4: 输出契约

**Files:**
- Create: `src/graphs/javatutor/prompting/contracts.py`
- Modify: `tests/test_prompting.py`

**Interfaces:**
- Produces: `get_contract(intent: str) -> str`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_prompting.py` 追加：

```python
from graphs.javatutor.prompting.contracts import get_contract


def test_contracts_require_grounding():
    assert "哪一步" in get_contract("data_query")
    assert "行号" in get_contract("debug")
    assert "源代码" in get_contract("concept")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_prompting.py::test_contracts_require_grounding -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 实现契约**

创建 `src/graphs/javatutor/prompting/contracts.py`：

```python
"""按意图的输出契约。"""

from graphs.javatutor.prompting.versions import PROMPT_VERSION

CONTRACTS = {
    "data_query": (
        "## 输出契约\n"
        "- 必须回答：在哪一步、哪一行、哪个变量、从什么值变成什么值、为什么。\n"
        "- 禁止出现步骤数据中不存在的行号/变量值，禁止凭空构造堆对象 id。\n"
        "- 长度 3-6 句，可含代码块。"
    ),
    "concept": (
        "## 输出契约\n"
        "- 先给核心定义或结论，再结合用户源代码或真实步骤数据举例。\n"
        "- 禁止脱离本次代码空谈教材内容。"
    ),
    "debug": (
        "## 输出契约\n"
        "- 必须包含：错误根因、出错位置（行号）、具体修改建议。\n"
        "- 禁止断言 compile_error 中不存在的错误。"
    ),
    "other": (
        "## 输出契约\n"
        "- 回答工具使用问题时给出可操作指引；无关问题礼貌说明职责范围。"
    ),
}


def get_contract(intent: str) -> str:
    return CONTRACTS.get(intent, CONTRACTS["other"])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_prompting.py -v`
Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add src/graphs/javatutor/prompting/contracts.py tests/test_prompting.py
git commit -m "feat: add per-intent output contracts"
```

---

### Task 5: prompts 组合器与 nodes 接入

**Files:**
- Modify: `src/graphs/javatutor/prompts.py`
- Modify: `src/graphs/javatutor/nodes.py`
- Modify: `tests/test_expert_nodes.py`

**Interfaces:**
- Produces: `build_system_prompt(intent: str) -> str`。
- `_build_expert_messages(state, expert)`：system = 组合器，human = 上下文 + few-shot。

- [ ] **Step 1: 写失败测试**

在 `tests/test_expert_nodes.py` 追加：

```python
    def test_system_prompt_contains_glossary_contract_version(self):
        from graphs.javatutor.prompts import build_system_prompt

        prompt = build_system_prompt("data_query")
        assert "术语表" in prompt
        assert "输出契约" in prompt
        assert "提示词版本" in prompt

    def test_expert_message_contains_few_shot_marker(self):
        from graphs.javatutor.nodes import _build_expert_messages

        messages = _build_expert_messages(BASE_STATE, "data_query")
        assert "（示例" in messages[1].content
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_expert_nodes.py -v`
Expected: FAIL，`build_system_prompt` 不存在或消息无示例。

- [ ] **Step 3: 实现组合器**

在 `src/graphs/javatutor/prompts.py` 末尾追加：

```python
from graphs.javatutor.prompting.contracts import get_contract
from graphs.javatutor.prompting.glossary import build_glossary_block
from graphs.javatutor.prompting.versions import PROMPT_VERSION

_ROLES = {
    "data_query": SYSTEM_PROMPT_DATA_QUERY,
    "concept": SYSTEM_PROMPT_CONCEPT,
    "debug": SYSTEM_PROMPT_DEBUG,
    "other": SYSTEM_PROMPT_OTHER,
}


def build_system_prompt(intent: str) -> str:
    role = _ROLES.get(intent, SYSTEM_PROMPT_OTHER)
    return (
        f"{role}\n\n## 领域词汇\n{build_glossary_block()}\n\n"
        f"## 输出契约\n{get_contract(intent)}\n\n## 提示词版本\n{PROMPT_VERSION}"
    )
```

- [ ] **Step 4: 接入 nodes**

将 `src/graphs/javatutor/nodes.py` 顶部 import 追加：

```python
from graphs.javatutor.prompting.contexts import (
    build_concept_context,
    build_data_query_context,
    build_debug_context,
    build_other_context,
)
from graphs.javatutor.prompting.fewshots import get_few_shots
from graphs.javatutor.prompts import build_system_prompt
```

将 `_build_expert_messages` 整体替换为：

```python
def _build_expert_messages(state: JavaTutorState, expert: str) -> list:
    """构建专家消息: system = 角色+词汇+契约; human = 上下文+示例."""
    context_builders = {
        "data_query": build_data_query_context,
        "concept": build_concept_context,
        "debug": build_debug_context,
        "other": build_other_context,
    }
    system_prompt = build_system_prompt(expert)
    context = context_builders.get(expert, build_other_context)(state)
    examples = get_few_shots(expert)
    human = context
    if examples:
        human += "\n\n## 示例\n" + "\n\n".join(examples)
    return [SystemMessage(content=system_prompt), HumanMessage(content=human)]
```

注意：`prompts.py` 中旧的 `SYSTEM_PROMPT_*` 常量继续保留，`test_build_expert_messages_structure` 仍断言 `SYSTEM_PROMPT_DEBUG[:20]` 在 system 中，组合器包含角色文本所以通过。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_expert_nodes.py tests/test_prompting.py -v`
Expected: 全部通过。

- [ ] **Step 6: 提交**

```bash
git add src/graphs/javatutor/prompts.py src/graphs/javatutor/nodes.py tests/test_expert_nodes.py
git commit -m "feat: compose system prompts and wire contexts into expert nodes"
```

---

### Task 6: 评审五类事实核查

**Files:**
- Modify: `src/graphs/javatutor/critic.py`
- Modify: `src/graphs/javatutor/prompts.py`
- Modify: `tests/test_critic.py`

**Interfaces:**
- `critic_node(state, model=None)`：事实依据包含真实步骤快照（堆/栈/输出）。
- `SYSTEM_PROMPT_CRITIC`：核查五类引用。

- [ ] **Step 1: 写失败测试**

在 `tests/test_critic.py` 追加：

```python
from graphs.javatutor.prompting.contexts import build_facts_block


def test_facts_include_heap_stack_output():
    state = {
        **BASE,
        "has_steps": True,
        "steps": [
            {"step": 1, "line": 4, "variables": {"arr": [3, 5, 1]}, "heap": {"h1": {"type": "Object"}}, "stackFrames": [{"method": "main"}], "output": "out"}
        ],
        "current_step_index": 0,
        "current_line": 4,
        "source_code": "public class A {\n    void run() {\n        int x = 1;\n    }\n}",
    }
    facts = build_facts_block(state)
    assert "堆对象" in facts
    assert "栈帧" in facts
    assert "输出" in facts
    assert "int x = 1" in facts
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_critic.py::test_facts_include_heap_stack_output -v`
Expected: 失败或 import 错误。

- [ ] **Step 3: 更新评审提示词**

将 `src/graphs/javatutor/prompts.py` 中 `SYSTEM_PROMPT_CRITIC` 替换为：

```python
SYSTEM_PROMPT_CRITIC = """你是回答评审。对照事实依据核查候选回答，只返回 JSON：
{"pass": true|false, "issues": ["问题1", "问题2"]}
核查五类引用：
1. 步骤号是否存在于步骤数据
2. 行号是否与源代码/步骤数据一致
3. 变量值与变量快照是否一致
4. 堆对象 id 是否真实存在于堆数据
5. 输出内容是否与运行输出一致
同时核查知识库引用来源是否真实存在。
只返回 JSON。"""
```

- [ ] **Step 4: 更新 critic 事实依据**

将 `src/graphs/javatutor/critic.py` 的 `_facts` 替换为：

```python
def _facts(state) -> str:
    from graphs.javatutor.prompting.contexts import build_facts_block

    return build_facts_block(state)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_critic.py -v`
Expected: 全部通过。

- [ ] **Step 6: 提交**

```bash
git add src/graphs/javatutor/critic.py src/graphs/javatutor/prompts.py tests/test_critic.py
git commit -m "feat: upgrade critic to five-type fact checks"
```

---

### Task 7: 全量回归

**Files:**
- Modify: 无（如测试暴露问题则修复对应文件）

**Interfaces:**
- 全量测试通过，深化链路不回归。

- [ ] **Step 1: 运行全量测试**

Run: `uv run pytest tests/ -v`
Expected: 全部通过。

- [ ] **Step 2: 外壳回归**

```bash
git diff --name-only HEAD | grep -E "^(\.coze|scripts/|src/main\.py|src/storage/|src/utils/)"
```

Expected: 无输出。

- [ ] **Step 3: 提交**

```bash
git add .
git commit -m "chore: regression pass for prompt engineering deepening"
```

注意：执行本任务前先确认工作区没有其他未提交改动；如有，仅 `git add` 本计划涉及的文件。

---

## Self-Review

### Spec Coverage

| 设计条目 | 对应任务 |
|---|---|
| 领域词汇表 | Task 1 |
| 提示词版本常量 | Task 1 |
| 按意图上下文构建器 | Task 2 |
| 当前行文本/快照/diff/方法上下文 | Task 2 |
| few-shot ≤2 且带标记 | Task 3 |
| 输出契约 | Task 4 |
| system 组合器 | Task 5 |
| nodes 接入 | Task 5 |
| 评审五类核查 | Task 6 |
| 全量回归 | Task 7 |

### Placeholder Scan

计划无 `TBD`、`TODO`；所有代码块完整。

### Type Consistency

- `PROMPT_VERSION`：Task 1 定义，Task 3/4/5 引用。
- `build_glossary_block()`：Task 1 定义，Task 5 使用。
- `build_<intent>_context(state)`：Task 2 定义，Task 5 使用。
- `build_facts_block(state)`：Task 2 定义，Task 6 使用。
- `get_few_shots(intent)`：Task 3 定义，Task 5 使用。
- `get_contract(intent)`：Task 4 定义，Task 5 使用。
- `build_system_prompt(intent)`：Task 5 定义并测试。
