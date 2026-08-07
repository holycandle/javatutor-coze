---
title: JavaTutor Coze 代码模式初始实施计划
version: 2.0
date_created: 2026-08-07
date_completed: 2026-08-08
owner: JavaTutor AI 智能体组
status: completed
tags: plan, implementation, phase-1
---

# JavaTutor Coze 代码模式初始实施计划

> **背景**: JavaTutor 智能体原为 Coze Studio 低代码模式开发，已迁移至 Coze Vibe Coding Python + LangGraph 代码模式。本计划聚焦核心对话流程迁移，动画、知识库、记忆暂不实现，留待后续 Phase 2。
>
> **适用范围**: 本计划覆盖初始迁移阶段（Phase 1），已于 2026-08-08 完成。

---

## 完成摘要

**2026-08-08 完成 Phase 1 全部 5 个 Task，27 个单元测试 + 冒烟测试通过。**

### 实施历程

| 时间 | 事件 |
|---|---|
| 需求对齐 | 10 轮问答确认输入格式、专家职责、路由规则、测试要求 |
| Task 1: 状态解析 | 8 个测试，覆盖 JSON 解析/无 steps/非法 JSON/越界索引 |
| Task 2: 意图路由 | 7 个测试，覆盖 5 种意图 + debug 短路 + 空问题 |
| Task 3: 专家节点 | 7 个测试，FakeModel 注入验证 4 个专家 + animate 占位 |
| Task 4: 全流程装配 | 5 个测试，AgentBundle 结构 + FakeModel 全流程 |
| Task 5: 冒烟验证 | 端到端 LLM 调用，验证解析/路由/回答正确 |

### 修复记录

| 问题 | 修复 |
|---|---|
| `create_agent` 不暴露 `.builder` | 改用 `StateGraph` + `AgentBundle` 包装 |
| `add_messages` reducer 消息重复 | `build_final` 只返回新增 `AIMessage`，不返回 `existing_messages` |
| `LLMClient.invoke()` 参数错误 | 展开 `llm_config` 属性传参，`messages` 用 LangChain 对象 |
| 平台 SSE 兼容 | `LLMClient` 替换 `ChatOpenAI`，统一使用平台 SDK |
| Coze 消息 content 为 list 类型 | `_parse_json_str` 增加 list 兼容处理 |
| `path_map` 参数导致 LangGraph 1.x 异常 | 移除 `path_map`，使用隐式路由 |

---

## 1. 迁移范围

### Phase 1（已完成）

| 模块 | 内容 | 状态 | 测试数 |
|---|---|---|---|
| 状态解析 | `parse_context` 节点：JSON → 统一状态字段 | ✅ 完成 | 8 |
| 意图路由 | `has_error` 短路 + 规则意图识别 → 4个专家 | ✅ 完成 | 7 |
| 专家节点 | data_query / concept / debug / other，每个单次 LLM 调用 | ✅ 完成 | 7 |
| 全流程装配 | StateGraph + build_agent + AgentBundle | ✅ 完成 | 5 |
| HTTP 冒烟验证 | 端到端 LLM 调用验证 | ✅ 完成 | 1 |
| **合计** | | **✅ 全部完成** | **27** |

### 留待 Phase 2

| 模块 | 状态 | 说明 |
|---|---|---|
| 动画生成（`animate` 分支） | ⏳ 待实现 | SVG + SMIL，Phase 1 返回占位文本 |
| 知识检索（`error_quickref`） | ⏳ 待实现 | JSON 资产 + 关键词匹配，Phase 1 debug 完全依赖 LLM |
| 跨会话记忆 | ⏳ 待设计 | 用户画像字段待产品设计，Phase 1 无记忆状态 |

---

## 2. 输入格式确认

后端通过 Coze Chat API 发送 JSON 字符串作为消息文本：

```json
{
  "source_code": "public class BubbleSort { ... }",
  "steps": [
    {
      "step": 0,
      "line": 3,
      "variables": { "arr": [5, 3, 8, 1] },
      "heap": {},
      "stackFrames": [
        {
          "method": "main",
          "locals": { "arr": [5, 3, 8, 1] },
          "args": {}
        }
      ],
      "output": null
    }
  ],
  "current_step_index": 1,
  "current_line": 4,
  "user_question": "为什么 arr[2] 还是 8？",
  "user_id": "a3f2b1c4-5d6e-4f7a-8b9c-0d1e2f3a4b5c",
  "compile_error": ""
}
```

- **仅支持** JSON 在消息 body 内的情况（不支持 JSON 外层放问题）
- `user_id` 可选，缺失时不触发任何错误

---

## 3. 流程设计

```
用户消息 (JSON 字符串)
       │
       ▼
parse_context  ──→ 解析 source_code / steps / compile_error 等
       │
       ▼
has_error 判断
       │
   ┌───┴───┐
   │       │
 true    false
   │       │
   ▼       ▼
 debug   route_intent  ──→ 规则匹配意图
                           │
              ┌────────────┼────────────┬────────────┐
              │            │            │            │
              ▼            ▼            ▼            ▼
         data_query   concept     animate*     other
                                          │
                                     (Phase 1 占位)
```

> `animate` 分支 Phase 1 返回占位文本：`"动画功能正在开发中，敬请期待。"`

---

## 4. 四个专家职责与上下文

| 专家 | 触发条件 | LLM 上下文 |
|---|---|---|
| `data_query` | 追问执行数据（"为什么第N步变量变了"、"此时 arr 是多少"） | user_question + steps 快照 + current_variables + source_code |
| `concept` | 询问算法原理（"冒泡排序是什么"、"时间复杂度"） | user_question + source_code + steps_count |
| `debug` | compile_error 非空 | user_question + compile_error + source_code |
| `other` | 无法归类于以上三类的所有问题 | user_question + source_code |

> **debug 短路规则**: `has_error == true` 时，**跳过**意图路由直接进入 debug 专家。

---

## 5. 文件结构（实际）

```
src/
├── agents/
│   ├── agent.py              # build_agent() → AgentBundle
│   └── agent_bundle.py       # AgentBundle 类
├── graphs/
│   └── javatutor/
│       ├── __init__.py       # 包标记
│       ├── state.py          # JavaTutorState schema（add_messages reducer）
│       ├── prompts.py        # 5 个 SYSTEM_PROMPT（4 个专家 + 1 个 animate 占位）
│       ├── nodes.py          # 所有节点：parse_context / route_intent / 5专家 / build_final
│       └── graph.py          # build_flow_graph() + AgentBundle
├── learning/
│   └── __init__.py          # Phase 2 预留
tests/
├── fixtures/
│   └── sample_payload.json    # 完整测试样例
├── test_parse_context.py     # 8 个测试 ✅
├── test_route_intent.py      # 7 个测试 ✅
├── test_expert_nodes.py      # 7 个测试 ✅
└── test_graph.py             # 5 个测试 ✅
config/
└── agent_llm_config.json     # 已有，保持不变
docs/
└── plan/
    └── initial-work-plan.md  # 本文件
```

---

## 6. 实施任务（已完成）

### Task 1: 状态解析节点

**输入**: `messages[-1].content` = JSON 字符串
**输出**: `JavaTutorState` 字段（`source_code`、`steps`、`steps_json`、`steps_count`、`has_steps`、`current_step_index`、`current_line`、`current_variables`、`user_question`、`user_id`、`compile_error`、`has_error`）

- [x] 创建 `tests/fixtures/sample_payload.json`
- [x] 创建 `tests/test_parse_context.py`（失败测试）
- [x] 运行测试确认失败
- [x] 创建 `src/graphs/javatutor/__init__.py`
- [x] 创建 `src/graphs/javatutor/state.py`（`JavaTutorState` TypedDict + `add_messages`）
- [x] 创建 `src/graphs/javatutor/nodes.py`（`parse_context` 函数）
- [x] 运行测试确认通过（8 passed）
- [x] 提交

### Task 2: 意图路由节点

**输入**: `state["user_question"]`、`state["compile_error"]`、`state["has_steps"]`
**输出**: `{"intent": "data_query" | "concept" | "debug" | "animate" | "other"}`

- [x] 创建 `tests/test_route_intent.py`（失败测试，7 个用例）
- [x] 运行测试确认失败
- [x] 在 `nodes.py` 追加 `route_intent` 函数
  - `compile_error` 非空 → 直接返回 `debug`
  - 关键词命中 → `data_query` / `concept` / `other`
- [x] 运行测试确认通过（7 passed）
- [x] 提交

### Task 3: 专家提示词与节点

**输入**: `state["user_question"]` + 各专家上下文字段
**输出**: `{"answer": str}`

- [x] 创建 `src/graphs/javatutor/prompts.py`（5 个 `SYSTEM_PROMPT`）
- [x] 创建 `tests/test_expert_nodes.py`（FakeModel 注入测试）
- [x] 运行测试确认失败
- [x] 在 `nodes.py` 追加：
  - `_get_chat_model()` — 从 `config/agent_llm_config.json` 读取，创建 `LLMClient`
  - `_build_expert_messages(state, expert)` — 构建 system + user 消息
  - `_run_expert(state, expert, model=None)` — 调用 `LLMClient.invoke()`
  - `data_query_node(state, model=None)`
  - `concept_node(state, model=None)`
  - `debug_node(state, model=None)`
  - `other_node(state, model=None)`
- [x] 在 `nodes.py` 追加 `animate_node`（Phase 1 占位）
- [x] 在 `nodes.py` 追加 `build_final(state)`（返回 `AIMessage`，仅返回新增消息）
- [x] 运行测试确认通过（7 passed）
- [x] 提交

### Task 4: 全流程装配

**输入**: Task 1-3 所有节点
**输出**: `build_agent(ctx=None) -> AgentBundle`

- [x] 创建 `src/graphs/javatutor/graph.py`（`build_flow_graph()`）
  - 节点顺序: `parse_context → route_intent → 5专家分支 → final`
  - `has_error` 短路在 `route_intent` 内处理
- [x] 重写 `src/agents/agent.py`（返回 `AgentBundle`，含 `.builder`）
- [x] 创建 `src/agents/agent_bundle.py`（`AgentBundle` 类）
- [x] 创建 `tests/test_graph.py`（验证 `AgentBundle` 结构 + FakeModel 全流程）
- [x] 运行 `uv run pytest tests/` 确认全部通过（27 passed）
- [x] 提交

### Task 5: HTTP 冒烟验证

- [x] 编译 `StateGraph` 并调用 `compiled.invoke()`
- [x] 验证解析 → 路由 → 专家回答全流程
- [x] 验证 `compile_error` 短路
- [x] 验证 `intent` 路由正确
- [x] 提交

---

## 7. 测试覆盖

| 测试文件 | 覆盖内容 | 测试数 |
|---|---|---|
| `test_parse_context.py` | 完整 JSON 解析、无 steps、非法 JSON、越界索引、空消息 | 8 |
| `test_route_intent.py` | 5 种意图（data_query/concept/other/空） + debug 短路 | 7 |
| `test_expert_nodes.py` | FakeModel 注入、4 个专家回答、消息结构验证、animate 占位 | 7 |
| `test_graph.py` | AgentBundle 结构、全流程 FakeModel 调用、compile_error 短路 | 5 |
| **合计** | | **27** |

---

## 8. 已知限制（Phase 1）

| 限制项 | 说明 | 解决方案（Phase 2） |
|---|---|---|
| 无动画 | `animate` 分支返回占位文本 | 实现 SVG + SMIL 生成器 |
| 无知识检索 | debug 专家完全依赖 LLM | 构建 `error_quickref.json` + 关键词匹配 |
| 无记忆 | 每次对话独立，无跨会话状态 | 设计用户画像字段 + SQLAlchemy 存储 |
| `animate` 路由 | 仍会被关键词命中触发 | Phase 2 接入真实动画生成器 |
| 响应格式唯一 | 所有响应均为 `AIMessage`，无结构化输出 | 后端按 `intent` 字段区分处理 |

---

## 9. 验收标准

- [x] `uv run pytest tests/` 全部通过，无 skip / xfail（27 passed）
- [x] `python -c "from agents.agent import build_agent; b = build_agent(); assert hasattr(b, 'builder')"` 无报错
- [x] 带 `compile_error` 的请求 → 路由至 debug，回答引用错误内容
- [x] 带"为什么"类问题 → 路由至 data_query，回答引用步骤/变量数据
- [x] 无法归类问题 → 路由至 other，返回通用回答

---

## 10. 后续计划预留

以下内容将在 Phase 2 计划中详细定义：

- [ ] **动画生成**: SVG + SMIL 模板，`build_animation_svg()`，`classify_algorithm()`
- [ ] **知识检索**: `assets/knowledge/error_quickref.json`，关键词匹配 `search_error_quickref()`
- [ ] **跨会话记忆**: `src/learning/memory.py`，用户画像字段设计，`make_session_factory()`
- [ ] **长期记忆节点**: `load_memory()` / `write_memory()` 加入 StateGraph
- [ ] **animate 路由完善**: 关键词 + 算法类型双重判断
- [ ] **响应格式扩展**: 根据 `intent` 返回结构化 JSON（如动画数据 `{animation_type, positions}`）