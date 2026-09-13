# Execution Context Fetch 设计

## 1. 背景与目标

当前 JavaTutor 后端在每次自由问答时，把 `source_code`、`steps`、`current_step_index`、`current_line`、`compile_error` 等执行数据直接写入发给 Coze 的消息 JSON。Coze 侧 `parse_context` 只做解析，主 Agent 唯一可调用的证据工具是 `step_facts`。

本设计将执行数据从 Coze 入站消息中移除，改为 Coze 侧确定性获取运行上下文：

- 入站消息只保留 `run_id`、`session_id`、`user_question`、`intent` 等控制信息。
- Coze 侧新增 `fetch_execution_context`，从 JavaTutor 后端获取代码、steps、当前执行位置。
- 获取后的完整执行数据进入 graph state，不直接塞给主模型。
- 记忆系统只保存本轮运行上下文的紧凑摘要，不保存完整代码与 steps。
- `step_facts` 继续作为主 Agent 唯一按需调用的单步证据工具。

## 2. 设计原则

1. 执行上下文是事实基础，不交给 LLM 决定是否获取；`fetch_execution_context` 由 graph 确定性调用。
2. 单步证据是模型按需使用的数据，`step_facts` 保留为 LLM 工具。
3. 后端快照是唯一事实来源，Coze 记忆只是缓存索引，不能替代实时上下文。
4. 兼容旧 payload，`fetch_execution_context` 失败时可降级，不破坏现有部署。

## 3. 入站消息契约

新消息 JSON：

```json
{
  "run_id": "3f8a2c0d-...",
  "session_id": "session-123",
  "user_question": "请解释当前这一步在做什么",
  "intent": "data_query",
  "compile_error": ""
}
```

字段规则：

- `run_id`：非空字符串，JavaTutor 本次运行生成。
- `session_id`：非空字符串，对应现有 `user_id` 语义。
- `user_question`：字符串，允许为空。
- `intent`：`data_query | concept | debug | analyze | other`，允许为空，为空时由现有保守关键词规则推断。
- `compile_error`：字符串，允许为空。

兼容性：

- 若消息仍包含旧字段 `source_code`、`steps`、`current_step_index`、`current_line`，`parse_context` 继续按旧逻辑解析。
- 新图优先使用 `run_id` 走 `fetch_execution_context`；没有 `run_id` 时直接沿用旧 payload。

## 4. 状态新增字段

在 `JavaTutorState` 增加：

- `run_id: str`
- `fetch_context_failed: bool`
- `fetch_context_latency_ms: float`
- `fetch_context_error: str`
- `run_context_memory: dict | None`

新增 `run_context_memory` 只存紧凑摘要：

```json
{
  "run_id": "3f8a2c0d-...",
  "code_hash": "sha256:...",
  "steps_count": 12,
  "current_step_index": 2,
  "current_line": 5,
  "algorithm_tags": ["冒泡排序"],
  "compaction_mode": "none"
}
```

不把 `source_code` 和完整 `steps` 放入该记忆记录。

## 5. fetch_execution_context

### 5.1 文件

- Create：`src/tools/fetch_execution_context.py`

对外接口：

```python
def fetch_execution_context(state: dict, run_id: str | None = None) -> dict:
    """从 JavaTutor 后端获取运行上下文，返回状态更新字典。"""
```

工具 schema 仅为可观测与评测使用：

```python
TOOL_SCHEMA = {
    "name": "fetch_execution_context",
    "description": "从 JavaTutor 后端获取指定 run_id 的源代码、执行步骤和当前执行位置",
    "parameters": {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    },
}
```

### 5.2 环境变量

- `JAVATUTOR_EXECUTION_CONTEXT_URL`：后端接口完整 URL，例如 `http://localhost:8080/api/agent/execution-context`。
- `JAVATUTOR_AGENT_TOKEN`：访问后端内部接口的共享 token。

禁止硬编码 token。

### 5.3 请求

```http
GET {JAVATUTOR_EXECUTION_CONTEXT_URL}/{run_id}
X-Agent-Token: {JAVATUTOR_AGENT_TOKEN}
Accept: application/json
```

超时设为 3 秒。

### 5.4 响应

```json
{
  "run_id": "3f8a2c0d-...",
  "source_code": "public class UserCode { ... }",
  "steps": [],
  "current_step_index": 2,
  "current_line": 5,
  "compile_error": "",
  "algorithm_tags": ["冒泡排序"],
  "expires_at": 1784736000
}
```

成功时返回状态更新：

```python
{
    "run_id": run_id,
    "source_code": data["source_code"],
    "steps": data.get("steps") or [],
    "steps_json": json.dumps(data.get("steps") or [], ensure_ascii=False),
    "steps_count": len(data.get("steps") or []),
    "has_steps": bool(data.get("steps")),
    "current_step_index": data.get("current_step_index", 0),
    "current_line": data.get("current_line", 1),
    "current_variables": current_variables,
    "compile_error": data.get("compile_error", ""),
    "has_error": bool((data.get("compile_error") or "").strip()),
    "algorithm_tags": data.get("algorithm_tags") or [],
    "fetch_context_failed": False,
    "fetch_context_error": "",
    "run_context_memory": {
        "run_id": run_id,
        "code_hash": sha256(source_code),
        "steps_count": len(steps),
        "current_step_index": data.get("current_step_index", 0),
        "current_line": data.get("current_line", 1),
        "algorithm_tags": data.get("algorithm_tags") or [],
    },
}
```

其中 `current_variables` 按当前步骤索引从 steps 中提取，越界时为空字典。

### 5.5 失败降级

以下任一情况视为失败：

- `run_id` 为空
- 网络异常或超时
- HTTP 状态非 200
- JSON 解析失败
- 响应缺少 `source_code` 或 `steps`

失败时：

```python
{
    "fetch_context_failed": True,
    "fetch_context_error": "<可读错误>",
    "fallback_reason": "fetch_execution_context failed: <error>",
}
```

如果旧 payload 已提供完整执行数据，则继续使用旧字段；否则主 Agent 必须输出固定降级文案：

```text
当前暂时无法获取这次代码运行的执行上下文，请重新运行代码后再提问。
```

### 5.6 纯 state 读取的入口解析顺序（2026-09-14 联调修复 D2/D3）

Phase 2 起 `fetch_execution_context` 是**纯 state 读取工具**（不发 HTTP，见
`2026-08-30-fetch-execution-context-as-tool-design.md`），"取哪个文件的代码" 由
`_resolve_code` 决定。2026-09-14 联调报告「决策痕迹显示调用了 fetch，但多轮都说缺少
Main.java 的源码」，定位到该函数在 `entry_file` 为空时**静默回落到 `source_code`
并把 `file` 置为空串**——多文件下 `source_code` 是**当前活动文件**，
模型既不知道自己拿到了什么，也无法自证拿到了 Main.java，而痕迹里那是一次**绿色**调用。

**解析顺序（第一条命中即停）**：

| # | 来源 | `file_source` |
|---|---|---|
| 1 | 显式 `file` 参数（精确 / 忽略大小写 / basename） | `explicit` |
| 2 | `entry_file`（主入口，同样按上述三种口径匹配） | `entry_file` |
| 3 | `current_step_file`（当前执行步所在文件） | `current_step_file` |
| 4 | `files` **唯一项** | `only_file` |
| 5 | `source_code`（单文件 / 激活文件） | `source_code` |
| 6 | 以上皆不成立 | 结构化失败 |

- 契约**向后兼容**：仍以「显式 `file` → 主入口」为先；第 3、4 条是**新增兜底**，
  把过去「解析不到就静默返回 source_code」换成**有序兜底 + 明示来源**。
- 特例保留：`files` 为空（单文件 payload）而模型传了 `file` 时，仍回退 `source_code`
  并标 `file_source="source_code"`，不报「文件不存在」（既有用例钉住）。

**成功回包必须自描述**：新增 `file`（这次真正取到的文件）与 `file_source`（上表来源）、
`code_chars`（取到的字符数）。渲染进观测的摘要（`harness/render.py::_handle_fetch`）
同样带这两个字段，并记进 `tool_calls[].result`。

**取消「成功但空」**：任何解析不到源码的路径（含 `start_line`/`end_line` 切出空串）
一律返回 `fetch_context_failed=true`，`error` 里点名候选文件：

```python
{
    "error": "未能取到源码（解析来源：<source>；候选文件：['A.java', 'B.java']）。请用 file 参数指定要读的文件名。",
    "fetch_context_failed": True,
    "fetch_context_latency_ms": 0.0,
}
```

不变式（验收判据）：**`fetch_context_failed == False` ⇒ `code_chars > 0`。**

> ⚠ 该改动**收紧**了既有行为：过去「有 steps 无 code」算成功，现在算失败。
> 全量回归已确认无既有用例依赖该「静默成功」。

## 6. Graph 变更

当前链路：

```text
parse_context → context_compaction → analyze_code
```

改为：

```text
parse_context → fetch_execution_context → context_compaction → analyze_code
```

新增 graph 节点 `fetch_execution_context_node`，确定性调用 `fetch_execution_context`，不在主 Agent 工具循环中暴露为模型可选工具。

`main_agent_node` 的工具循环保持只有 `step_facts`。

## 7. 上下文工程

`build_context` 使用 fetch 后的 state：

- `Task`：用户问题
- `Evidence`：源代码、当前执行位置、分析结果、RAG chunks
- `Memory`：会话历史、`run_context_memory` 摘要、最近 step facts

不把完整 `steps_json` 注入主模型上下文。需要单步证据时由主 Agent 调用 `step_facts`。

## 8. 决策痕迹

`build_final` 的 trace 增加：

```json
{
  "run_id": "3f8a2c0d-...",
  "fetch_context_failed": false,
  "fetch_context_latency_ms": 12.3,
  "fetch_context_error": ""
}
```

## 9. 测试策略

### 单元测试

- `fetch_execution_context` 成功响应解析。
- `fetch_execution_context` 非 200、超时、非法 JSON、缺字段时的失败结构。
- `parse_context` 兼容新 envelope 与旧 payload。
- `run_context_memory` 不包含完整 source_code 和 steps。

### 图级测试

- 新 envelope + mock 后端成功响应后，state 中 `source_code`、`steps`、`current_step_index` 正确填充。
- mock 后端失败且无旧 payload 时，最终回答包含固定降级文案。
- 旧 payload + 无 run_id 时，原链路行为不回退。

### 端到端测试

- JavaTutor 本地运行代码后提问，Coze 侧通过 `fetch_execution_context` 获取上下文并正确回答。
- 决策痕迹中 `run_id` 与 JavaTutor 返回的 runId 一致。

## 10. 与现有评估系统关系

评估系统新增样本时，`payload` 允许使用新 envelope；远程模式需提供 `JAVATUTOR_EXECUTION_CONTEXT_URL` 与 `JAVATUTOR_AGENT_TOKEN`。

组件评测中保留 `fetch_context_failed` 作为可观测指标，但不作为普通问答正确性的必要条件。
