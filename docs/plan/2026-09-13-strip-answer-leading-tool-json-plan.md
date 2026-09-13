# 实施计划：剥离开头工具调用 JSON（回答正文裸 JSON + 标题不换行）

> 依据：2026-09-13 联调实测。回答正文顶端出现
> `{"tool": "fetch_execution_context", "args": {"file": "Main.java"}}### 当前这一步的执行内容`，
> 且工具 JSON 与紧随其后的 markdown 标题**无分隔换行**，导致 `###` 不被识别为标题。
> 分工：设计侧产出本文档，执行由执行组完成。
> 交付边界：离线全绿（L1–L5）。

## 0. 全局约束（务必遵守）

- **不做任何 git 操作**（不 `git add`/`commit`/`push`/`stash`/`checkout`/`branch`/`merge`）。
  读 `git log`/`git status`/`git diff` 可以。
- **外壳一个字节都不改**：`.coze`、`scripts/`、`src/main.py`、`src/storage/`、`src/utils/`。
- **不引入新依赖**，不改 `pyproject.toml`/`uv.lock`。本计划只用 stdlib `json`。
- **不改既有语义**：`_strip_leaked_json` 既有 4 条规则的行为、`_redact_denied_tools`、
  `_strip_structured_blocks`、`parse_action`、`【视角导航】`/`【编辑建议】` 的透传契约。
  **只新增，不修改、不重排。**
- 基线（改动前先跑一遍记数）：`uv run pytest tests/ -q` 应 **368 passed**（本机 2026-09-13 实测）。
- **红线取证纪律**（见 `docs/reviews/2026-09-13-rag-observability-and-trace-process-review.md` §1.4）：
  涉及「什么会进用户可见产物」的断言，必须以**端到端产物**（`out["answer"]`）取证，
  不得只在函数返回值层下结论。
- 不触碰 `javatutor/frontend/src/backup-20260807/`。本计划**不动前端**。

---

## 1. 问题与根因

### 1.1 现象

一次 data_query 提问的回答，正文首行是裸工具 JSON，且与后面的 markdown 标题连成一行：

```
{"tool": "fetch_execution_context", "args": {"file": "Main.java"}}### 当前这一步的执行内容
```

`}}###` 之间没有换行 → markdown 解析器看不到行首的 `###` → 该行以普通正文渲染。

### 1.2 根因（三段链路，均已实测复现）

1. **上游**：`SYSTEM_PROMPT_MAIN_AGENT`（`src/graphs/javatutor/prompts.py:118-138`）把工具调用格式
   **逐字**示范给模型，含冒号后空格：`{"tool": "fetch_execution_context", "args": {}}`。
   模型在终答轮把该格式当作行首前缀复述出来。
2. **中游**：`parse_action`（`src/graphs/javatutor/harness/contracts.py:58-78`）是**严格**
   `json.loads(整段)`。`{"tool":...}}### 当前这一步...` 不是合法 JSON → 返回 `None`
   → 按契约「非 JSON = 终答」（`harness/propose.py:113-114`）→ **整段原文成为 `state["answer"]`**。
3. **下游**：`_strip_leaked_json`（`src/graphs/javatutor/nodes.py:389-422`）有 4 条规则：
   开头 `{"intent"}`、任意处 `{"pass"}`、结尾 `{"tool"}`
   （`r'\n*\s*\{\s*"tool"\s*:.*?\}\s*$'`，带 `$` 锚定）。**独缺「开头 `{"tool"}`」** → 漏网。

### 1.3 为什么不能照既有风格用正则补一条

既有规则 4 靠 `$` 锚定才成立：惰性 `.*?` 会一直延伸，直到某个 `}` 之后**只剩空白到串尾**。
开头场景没有这个锚，惰性匹配会停在**第一个** `}`：

```
{"tool": "fetch_execution_context", "args": {"file": "Main.java"}}
                                              ^ 停在这里，残留一个 }
```

**已实测**：截断后留下孤立的 `}`。所以修复必须走**平衡解析**。

---

## 2. 设计

在 `_strip_leaked_json` 的规则 1 **之前**新增规则 0，用 stdlib 的
`json.JSONDecoder().raw_decode()`（它天然处理嵌套括号与尾随内容）：

```python
# 0. 移除开头的工具调用 JSON（模型可能把提案与正文连写：
#    {"tool": "fetch_execution_context", "args": {"file": "Main.java"}}### 标题）
#    用 raw_decode 做平衡解析——惰性正则会在 args 的嵌套 {} 处提前截断，留下孤立的 }。
s = text.lstrip()
if s.startswith("{"):
    try:
        obj, end = json.JSONDecoder().raw_decode(s)
    except ValueError:
        obj, end = None, 0
    if isinstance(obj, dict) and obj.get("tool"):
        rest = text[len(text) - len(s) + end:].lstrip(" \t")
        text = ("\n\n" + rest) if rest and not rest.startswith("\n") else rest
```

**两个关键取舍**：

1. **判别条件是 `obj.get("tool")`，不是「开头是 `{` 就删」。**
   `【视角导航】` 块（`{"views":[...]}`）与 `【编辑建议】` 块同样以 `{` 开头，
   且**必须原样透传**（见 `_strip_leaked_json` 的 docstring 与
   `docs/spec/2026-09-07-coze-agent-view-navigation.md` 的契约）。
   用 `tool` 键判别是唯一安全的写法。
2. **剥离后补分隔换行。** 若紧跟的内容不以换行开头（截图里的 `}}###`），
   补 `\n\n` 使 `###` 回到行首、恢复为标题；若已是换行分隔则不动。
   后续规则 3 的 `_re.sub(r'\n{3,}', '\n\n', ...).strip()` 会清掉多余空行，无需额外处理。

---

## 3. 任务

### Task 1：新增剥离规则 + 回归

**先写测试** `tests/test_nodes.py`（**追加**，不改既有用例）：

| # | 输入 | 期望 |
|---|---|---|
| 1 | `'{"tool": "fetch_execution_context", "args": {"file": "Main.java"}}### 当前这一步的执行内容'` | 结果**不含** `"tool"`；以 `### 当前这一步` 开头（`###` 前无残留字符） |
| 2 | `'{"tool": "step_facts", "args": {"step_index": 1, "line": 4}}\n\n正文'` | `'正文'` |
| 3 | `'{"views":[{"panel":"tutor","sub":"analysis"}]}\n\n正文'` | **原样保留**（导航块不回归） |
| 4 | `'正文\n\n【编辑建议】\n{"kind":"patch","target":"Main.java","code":"..."}'` | 块保留（编辑建议不回归） |
| 5 | `'普通正文，没有 JSON'` | 不变 |
| 6 | `'{"intent":"data_query"}\n\n{"tool": "step_facts", "args": {}}\n\n正文'` | 两条规则叠加生效：只剩 `正文` |

**端到端用例（必须，红线取证纪律）**：
用既有 `SpamModel` 桩（见 `tests/test_harness_loop.py` 的用法）让 `propose` 返回
「工具 JSON + 散文」，跑一次**完整图**，断言 `out["answer"]` 的正文段
（`\n\n【决策痕迹】\n` 之前）不含 `"tool"`。
**不得**只测 `_strip_leaked_json` 就下结论——`build_final` 还有 `_redact_denied_tools` 等下游处理，
最终产物才是唯一事实。

**实现** `src/graphs/javatutor/nodes.py::_strip_leaked_json`：按 §2 加规则 0。
- 保留既有 4 条规则的**顺序与文本**不变（规则 0 插在最前）。
- 函数 docstring 的目标模式清单补上「开头的 `{"tool":...}`」，并说明为何用 `raw_decode` 而非正则。

**验证**：
```
uv run pytest tests/test_nodes.py -q
uv run pytest tests/test_harness_loop.py tests/test_harness_termination.py -q   # 红线两条既有守卫不得红
```

---

### Task 2：提示词侧上游约束（防御性，但独立有价值）

**为什么必须做**：规则 0 只是**兜底**。模型走「JSON + 散文」这条路时，`parse_action` 返回 `None`
→ **那一轮的工具根本没有被调用**。本次截图里工具恰好已被 `P0-auto-fetch` 与先前轮次覆盖，
所以只表现为渲染问题；若某次提问的第一轮就走这条路，回答会**缺证据**——那才是更严重的问题。

**实现** `src/graphs/javatutor/prompts.py`：在 `SYSTEM_PROMPT_MAIN_AGENT` 的
`## 调用示例（照此三步…）` 段末补一句约束：

> 工具调用 JSON 必须**独占一条消息**，不得与回答正文写在同一段里；回答正文中不得出现工具调用 JSON。

**先写测试** `tests/test_prompts.py`（追加，或既有提示词用例所在文件）：
断言 `SYSTEM_PROMPT_MAIN_AGENT` 含该约束句的关键片段。

**注意**：不要改动 `## 调用示例` 里既有的 JSON 示例格式——那是模型学会工具协议的依据，
删除示例会让工具调用率下降（见 `docs/devlog/2026-09-08-raise-fetch-tool-call-rate.md`）。
**只加约束句，不删示例。**

**验证**：`uv run pytest tests/ -q` 全绿（基线 368）。

---

## 4. 影响面

| 文件 | 改动性质 |
|---|---|
| `src/graphs/javatutor/nodes.py` | `_strip_leaked_json` 新增规则 0 |
| `src/graphs/javatutor/prompts.py` | 主 Agent 提示词新增一句约束 |
| `tests/test_nodes.py` | 上述 6 条单测 + 1 条端到端 |
| `tests/test_prompts.py` | 约束句断言 |

**不改**：`_redact_denied_tools`、`_strip_structured_blocks`、`build_reasoning`、`_strip_tool_json`、
`parse_action`、`harness/` 下任何文件、前端、外壳。

**文档同步**：本计划为缺陷修复，不改变对外契约（`answer` 里本来就不该有工具 JSON），
无需更新 `docs/agent-collaboration-guide.md`；实现记录见 §5。

---

## 5. 交付物

- 本计划 + 实现记录 `docs/devlog/2026-09-13-strip-answer-leading-tool-json.md`（执行后撰写）。
- 开发日志须记录：改动内容、验证结果（含端到端用例的实测输出）、遗留问题。

## 6. 遗留（明确不在本计划内）

- **不**把 `parse_action` 改成「容忍 JSON + 散文」（自动提取其中的 JSON 当提案）。
  那会改变提案语义：模型写「`{"tool":"step_facts"}` 我打算这么做，但是…」时会被当成真提案执行。
  收益（多救回一轮工具调用）与风险（误执行）需单独评估，另开 spec。
- **不**动 `_strip_tool_json`（`build_reasoning` 用）——它按 `json.loads(整段)` 判别提案轮，
  与本次问题不同源，无回归风险。
- **不**动前端：本次现象全部由 coze 侧产生，前端 `decisionTrace.js` 的解析对本次修复后的文本
  行为不变。
