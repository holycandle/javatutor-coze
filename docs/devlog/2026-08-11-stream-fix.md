# 2026-08-11 决策痕迹格式修复

## 问题

用户报告回答正文中混入了两类不该出现的 JSON：

1. **正文开头**出现意图分类 JSON：`{"intent":...,"confidence":...}`
2. **正文中间/末尾**出现评审 JSON：`{"pass":true,"issues":[]}`
3. **【决策痕迹】块**缺失或出现太晚

## 根因分析

项目以 `COZE_PROJECT_TYPE=agent` 模式运行，使用 `AgentStreamRunner`，流式输出模式为 `stream_mode="messages"`。

`LLMClient.invoke()` 内部调用 `self.stream()`，后者创建 `ChatOpenAI(streaming=True)` 实例。LangGraph 的 `stream_mode="messages"` 会拦截图中所有 `ChatOpenAI` 调用产生的 token chunk 并转发给客户端。

因此，意图分类（`classify_intent`）、专家回答（`_run_expert`）、评审（`critic_node`）、修订（`revise_node`）中的所有 `client.invoke()` 调用都被流式转发，导致中间 JSON 泄露。

同时，`build_final` 返回 `{"answer": ...}` 而非 `{"messages": [...]}`，精心组装的最终回答（含决策痕迹）反而没有通过消息流输出。

## 修复方案

### 1. 创建 `llm_complete()` — 原始 HTTP LLM 调用

**文件**: `src/graphs/javatutor/llm.py`

新增 `llm_complete()` 函数，使用 `httpx` 直接 POST 到 `/chat/completions` 端点，不创建 `ChatOpenAI` 实例，因此不会被 `stream_mode="messages"` 拦截。

关键实现：
- 使用 `httpx.stream("POST", ...)` 处理 API 始终返回的 SSE 格式
- 显式发送 `thinking: {"type": "disabled"}` 禁用推理模式
- 解析 SSE `data:` 行，提取 `delta.content` 拼接完整文本
- 检测 SSE 错误响应（如 `ErrBalanceOverdue`），抛出 `RuntimeError`

### 2. 替换所有中间 LLM 调用

| 文件 | 函数 | 变更 |
|------|------|------|
| `intent.py` | `classify_intent()` | `client.invoke()` → `llm_complete()` |
| `critic.py` | `_invoke()` | `client.invoke()` → `llm_complete()` + 包装为 `AIMessage` |
| `nodes.py` | `_run_expert()` | `client.invoke()` → `_llm_complete()` + try/except 降级 |
| `nodes.py` | `analyze_node()` | `client.invoke()` → `_llm_complete()` |

### 3. `build_final` 返回 `messages`

**文件**: `src/graphs/javatutor/nodes.py`

- 返回 `{"messages": [AIMessage(content=content)], "answer": content, "decision_trace": trace}`
- 使最终回答（含决策痕迹）成为**唯一**通过消息流输出的内容
- 决策痕迹 JSON 使用 `separators=(",", ":")` 确保单行紧凑格式

### 4. 新增 `_strip_leaked_json()` 清洗函数

移除回答正文中可能残留的：
- 开头的意图 JSON `{"intent":...,"confidence":...}`
- 任意位置的评审 JSON `{"pass":...,"issues":[...]}`
- markdown 代码块包裹的上述 JSON

### 5. 清理无用导入

移除 `nodes.py` 中不再使用的 `LLMClient`、`Config`、`SDKLLMConfig`、`request_context`、`new_context`、`default_headers`、`_get_chat_model`、`os` 等导入。

## 验证

- 81/81 单元测试通过
- `test_run` 端到端验证：回答正文纯净（无 JSON 泄露），决策痕迹在末尾以单行紧凑 JSON 输出
- `_strip_leaked_json` 边界测试：5 个用例全部通过

## 变更文件清单

- `src/graphs/javatutor/llm.py` — 新增 `llm_complete()`、`_load_llm_settings()`、`_messages_to_openai()`
- `src/graphs/javatutor/intent.py` — `classify_intent()` 使用 `llm_complete()`
- `src/graphs/javatutor/critic.py` — `_invoke()` 使用 `llm_complete()`
- `src/graphs/javatutor/nodes.py` — `_run_expert()`/`analyze_node()` 使用 `_llm_complete()`，`build_final` 返回 messages，新增 `_strip_leaked_json()`
