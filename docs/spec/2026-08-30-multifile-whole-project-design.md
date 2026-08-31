# 多文件 / 整体项目理解（Phase 2）设计

> 一句话：在 Phase 1（`fetch_execution_context` 成为 agent 自由调用的**纯 state 读取工具**）基础上，把「单文件执行上下文」升级为「多文件项目」。前端把项目全部文件随入站消息发给后端 envelope → Coze `state.files`；上下文工程**恒注入轻量「项目结构」概览**；agent 需要跨文件信息时用 `fetch_execution_context(file="...")` **按需读**某个文件。

## 1. 背景与目标

Phase 1 解决了「整体代码由 agent 按需读取、读完先暂存 state、不强制注入 prompt」。但 payload / state 里只有单一 `source_code`，agent 无法感知「项目」这一维度——多个类、文件间关系、跨文件回答都无从谈起。

用户已定的两个决策（原文）：
- **注入策略 = 「概览+按需读(最省)」**——恒注入项目结构概览 + 主入口；**其他文件由 agent 按需读**。
- **时序 = 「现有phase1计划已执行，可直接写新计划」**——Phase 1 已完成，本设计作为 Phase 2 的新计划。

## 2. 信息分层（本次更新后的完整版）

| 数据类别 | 获取方式 | 说明 |
|---|---|---|
| 项目结构概览（文件名 + 类型提示） | 上下文工程预取（`gather`） | **新增**：恒注入，token 极小 |
| 整体代码（主入口/激活文件） | `fetch_execution_context`（默认读主入口） | Phase 1 已实现 |
| 其他文件代码 | `fetch_execution_context(file="...")` 按需读 | **本次激活 `file` 参数** |
| 单步执行证据 | JIT 工具（`step_facts`） | 不变 |
| 知识 / RAG | 上下文工程预取（`retrieve_knowledge`） | 不变 |
| 会话记忆 | 上下文工程预取（`load_session`） | 不变 |

> **明确不做**：把所有文件整段预注入（违背「信息分层」）；不做「自动全量读懂整个项目」；文件读取仍是一次一文件、按需触发。

## 3. 数据模型（payload / state）

前端把全部文件发给后端，后端塞进 envelope，Coze 归一化进 state：

- **前端**（`player.js` `askQuestion`）：请求 body 增加 `files: [{name, code}]`（复用 `this.multiState.files`）。
- **后端**（`ExplainRequest`）：新增 `List<Map<String, String>> files`（`name` / `code`）。
- **后端**（`CozeService.buildAgentPayload`）：`agentPayload.put("files", files)`（runId 分支 + 旧分支均可选带）。
- **Coze state**：新增 `files: dict[str, str]`（`name → code`），由 payload `files` 归一化而来。
- **`source_code` = 主入口**：行号映射的锚点，由 `entry_file`（可选）显式锚定；缺省时回退到当前激活文件（`payload.source_code`）。见 §8。
- **`current_step_file` = 当前步所在文件**：`steps[current_step_index].file`，经 `_parse_json_dict` 透传，供 agent 自证「当前步在哪个文件」（见 §8）。新增 state 字段。

**`_normalize_files` 归一化**（coze 侧，放在 `fetch_execution_context.py` 供 `nodes.py` 复用），兼容三种形态 → `dict[str, str]`：
- `dict`：`{"App.java": "code"}`
- `list[{name, code}]`（前端 `multiState.files` / `askQuestion`）
- `list[{path, code}]`（项目分析接口形态）

## 4. 工具改动（`src/tools/fetch_execution_context.py`）

激活此前预留的 `file` 参数，其余行为沿用 Phase 1（纯 state 读取、失败不抛、暂存 `fetched_context`、同步修复标准字段）：

- **`_resolve_code(state, file)`**：
  - `file` 为空 → 主入口（`state.source_code`）。
  - `file` 命中 `state.files`（支持精确匹配、忽略大小写、按 `Path(name).name` 匹配 basename）→ 返回该文件 code。
  - 未命中 → 返回 `{"error": "文件不存在：<file>（已在项目结构中的文件：[...]）", ...}`。
- **结果字段**：
  - `code` = 本次解析出的文件内容（agent 眼里**唯一**希望看到的内容）。
  - `source_code` = **主入口**（保持行号锚点，不被文件读入改变）。
  - `file` = 本次读取的文件名。
  - `fetched_context` 追加 `project_files`（排序后的文件名单），供概览/排障。
  - `run_context_memory` 追加 `files_count`（**不含**任何文件内容）。

## 5. 上下文工程改动（`src/graphs/javatutor/context_builder.py`）

`gather()` 在 `state.files` 非空时，注入一个轻量「项目结构」概览包：

```python
files = state.get("files") or {}
if files:
    overview_lines = [
        f"- {name} — {_file_type_hint(code)}"
        for name, code in sorted(files.items())
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

- `_file_type_hint(code)`：正则扫首个 `class|interface|record|enum`（或 `@interface`）取名，无则取首行注释/`第 N 行`；纯成本，无 LLM。
- `### 源代码` 仍只注入主入口（`fetched_context.source_code`），**不因文件读入而变更**。
- 概览占 token 极小（一行一文件）。

## 6. Prompt 改动（`src/graphs/javatutor/prompts.py`）

`SYSTEM_PROMPT_MAIN_AGENT` 增加一句多文件提示：

> 这是一个 Java 项目，可能包含多个文件。`### 项目结构` 列出了所有文件及主要类型；回答涉及多个文件、类之间关系、或需要查看非主入口代码的问题，请调用 `fetch_execution_context` 的 `file` 参数读取对应文件，默认读取主入口。

## 7. 边界与已知限制

- **不做**：文件内容全量预注入；新增 `search_knowledge` / `read_code` 等额外工具。
- **行号映射（已解决，见 §8）**：`steps` 引用**入口文件**行号。Phase 2 用显式 `entry_file` 锚定主入口，并用 `current_step_file` 让 agent 对齐「当前步所在文件」，行号不再随激活文件漂移。
- 多文件回答依赖 agent **主动调用工具**；模型未调用时只能依据概览（文件名/类型）做粗略回答。

## 8. 当前步的步级文件定位（Phase 2 补充）

**背景**：多文件项目里 `steps` 每条记录自带 `file`（后端执行时记录，前端 UI 靠它跨文件高亮），但这条元数据在「传给 Coze 的步骤快照」里**被丢弃**（`stepSnapshots` 只 map 了 `step/line/variables/...`）。Coze state 里的「当前步」只有裸行号 `current_line`，**没有文件归属**——agent 无法判断「第 N 行」属于哪个文件。

与此同时前端 `syncToStep` 在播放时**自动把激活文件切到当前步所在文件**，使 `code`（当前激活文件）与 `currentLine`（当前步行号）**在正常播放时恰好重合**。但这只是隐式、不可靠的依赖——一旦提问时用户暂停/手动切过文件，`code` 与 `currentLine` 就分属两个文件，agent 读到的「某文件第 N 行」完全错位。

**三项修复**（与 `entry_file` 一起构成「agent 自证当前步」的保证）：

1. **`stepSnapshots` 补 `file`**（前端一行）：步骤快照透传 `steps[i].file`。
2. **`current_step_file` 状态字段**：`_parse_json_dict` 从 `steps[current_step_index].file` 取值写入 state；`fetch_execution_context` 返回值含 `current_step_file`。
3. **`step_facts` 一律按当前步文件取证据**：涉及「当前这一执行步」时，定位**只认** `steps[current_step_index]` 自带的 file + line，读 `state.files[当前步文件]`。`source_code`（用户当前激活文件）**不参与定位**——用户把代码区切到哪个文件不影响「这一步在哪」。
   > 定位唯一来源 = 当前执行步。这是本设计对「当前步正确性」的硬保证：不依赖前端恰好把激活文件切过来。

**`entry_file` 锚定主入口**：可选字段（前端可传、后端可推断）。存在时 `fetch_execution_context` 无 `file` 参数时默认读 `state.files[entry_file]`，行号锚点固定为入口文件，用于 `step_facts` 跨文件时行号仍有明确归属。

**数据流**：`前端(step.file, entryFile)` → `后端 ExplainRequest(files, entryFile)` → `payload(files, entry_file)` → `_parse_json_dict(state.files, entry_file, current_step_file)` → `fetch_execution_context` / `step_facts` 对齐读取。

## 9. 跨仓库协同

- 前端（`JavaTutor/frontend`）发 `files` → 后端（`CozeService`）塞 `files` → Coze `parse_context` 归一化 `state.files`。
- 后端需重新构建/部署 JavaTutor；Coze 侧需重新发布 agent。
- 前后半段同一改动，建议一起上线；若先后，先后端后 coze。
