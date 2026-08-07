---
title: JavaTutor Coze 代码模式初始实施计划
version: 1.0
date_created: 2026-08-07
owner: JavaTutor AI 智能体组
status: draft
tags: plan, implementation, phase-1
---

# JavaTutor Coze 代码模式初始实施计划

> **背景**: JavaTutor 智能体原为 Coze Studio 低代码模式开发，需迁移至 Coze Vibe Coding Python + LangGraph 代码模式。本计划聚焦核心对话流程迁移，动画、知识库、记忆暂不实现，留待后续 Phase 2。
>
> **适用范围**: 本计划覆盖初始迁移阶段（Phase 1），后续功能扩展另起计划。

---

## 1. 迁移范围

### Phase 1（本次实施）

| 模块 | 内容 | Plan 任务 |
|---|---|---|
| 状态解析 | `parse_context` 节点：JSON → 统一状态字段 | Task 1 |
| 意图路由 | `has_error` 短路 + 规则意图识别 → 4个专家 | Task 2 |
| 专家节点 | data_query / concept / debug / other，每个单次 LLM 调用 | Task 3 |
| 全流程装配 | StateGraph + build_agent + AgentBundle | Task 7 |
| 单元测试 | 每个模块对应测试文件 | Task 1/2/3 |
| HTTP 冒烟验证 | 服务启动 + 接口调用 | Task 8 |

### 留待 Phase 2

| 模块 | 负责人 | 说明 |
|---|---|---|
| 动画生成（`animate` 分支） | 待定 | SVG + SMIL，Phase 1 先返回占位文本 |
| 知识检索（`error_quickref`） | 待定 | JSON 资产 + 关键词匹配，Phase 1 debug 完全依赖 LLM |
| 跨会话记忆 | 待定 | 用户画像字段待产品设计，Phase 1 无记忆状态 |

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
| `debug` | compile_error 非空 **或** 问题含"报错/异常/怎么改" | user_question + compile_error + source_code |
| `other` | 无法归类于以上三类的所有问题 | user_question + source_code |

> **debug 短路规则**: `has_error == true` 时，**跳过**意图路由直接进入 debug 专家。

---

## 5. 文件结构

```
src/
├── agents/
│   └── agent.py              # build_agent() 返回 AgentBundle
├── graphs/
│   └── javatutor/
│       ├── __init__.py       # 包标记
│       ├── state.py          # JavaTutorState schema
│       ├── prompts.py        # SYSTEM_PROMPTS（4个专家）
│       ├── nodes.py          # 所有节点：parse_context / route_intent / 4专家 / animate(占位) / final
│       └── graph.py          # build_flow_graph()
├── learning/
│   └── __init__.py          # Phase 2 预留
tests/
├── fixtures/
│   └── sample_payload.json    # 完整测试样例
├── test_parse_context.py     # Task 1
├── test_route_intent.py      # Task 2
└── test_expert_nodes.py      # Task 3
config/
└── agent_llm_config.json     # 已有，保持不变
```

---

## 6. 实施任务

### Task 1: 状态解析节点

**输入**: `messages[-1].content` = JSON 字符串
**输出**: `JavaTutorState` 字段（`source_code`、`steps`、`steps_json`、`steps_count`、`has_steps`、`current_step_index`、`current_line`、`current_variables`、`user_question`、`user_id`、`compile_error`、`has_error`）

- [ ] 创建 `tests/fixtures/sample_payload.json`
- [ ] 创建 `tests/test_parse_context.py`（失败测试）
- [ ] 运行测试确认失败
- [ ] 创建 `src/graphs/javatutor/__init__.py`
- [ ] 创建 `src/graphs/javatutor/state.py`（`JavaTutorState` TypedDict）
- [ ] 创建 `src/graphs/javatutor/nodes.py`（`parse_context` 函数）
- [ ] 运行测试确认通过
- [ ] 提交

### Task 2: 意图路由节点

**输入**: `state["user_question"]`、`state["compile_error"]`、`state["has_steps"]`
**输出**: `{"intent": "data_query" | "concept" | "debug" | "other"}`

- [ ] 创建 `tests/test_route_intent.py`（失败测试，7 个用例）
- [ ] 运行测试确认失败
- [ ] 在 `nodes.py` 追加 `route_intent` 函数
  - `compile_error` 非空 → 直接返回 `debug`
  - 关键词命中 → `animate`（占位）/ `debug` / `data_query` / `concept`
  - 都不匹配 → `other`
- [ ] 运行测试确认通过（7 passed）
- [ ] 提交

### Task 3: 专家提示词与节点

**输入**: `state["user_question"]` + 各专家上下文字段
**输出**: `{"answer": str}`

- [ ] 创建 `src/graphs/javatutor/prompts.py`（4 个 `SYSTEM_PROMPTS`）
- [ ] 创建 `tests/test_expert_nodes.py`（FakeModel 注入测试）
- [ ] 运行测试确认失败
- [ ] 在 `nodes.py` 追加：
  - `_get_chat_model()` — 从 `config/agent_llm_config.json` 读取，每次调用新建实例
  - `_build_expert_messages(state, expert)` — 构建 system + user 消息
  - `_run_expert(state, expert, model=None)` — 调用模型，测试时通过 `configurable.chat_model` 注入 FakeModel
  - `data_query_node(state, model=None)`
  - `concept_node(state, model=None)`
  - `debug_node(state, model=None)`
  - `other_node(state, model=None)`
- [ ] 在 `nodes.py` 追加 `animate_node`（Phase 1 占位：`"动画功能正在开发中，敬请期待。"`）
- [ ] 在 `nodes.py` 追加 `build_final(state)`（返回 `AIMessage`）
- [ ] 运行测试确认通过
- [ ] 提交

### Task 4: 全流程装配

**输入**: Task 1-3 所有节点
**输出**: `build_agent(ctx=None) -> AgentBundle`

- [ ] 创建 `src/graphs/javatutor/graph.py`（`build_flow_graph()`）
  - 节点顺序: `parse_context → route_intent → 4专家分支 → final`
  - `has_error` 短路在 `route_intent` 内处理（debug 分支优先）
- [ ] 重写 `src/agents/agent.py`（返回 `AgentBundle`，含 `.builder`）
- [ ] 创建 `tests/test_graph.py`（验证 `AgentBundle` 结构 + FakeModel 全流程）
- [ ] 运行 `uv run pytest tests/` 确认全部通过
- [ ] 提交

### Task 5: HTTP 冒烟验证

- [ ] 在 Coze 终端启动服务：`bash scripts/http_run.sh -p 5000 &`
- [ ] 验证 `/health` 返回 `status=ok`
- [ ] 验证 `/graph_parameter` 返回非空 JSON
- [ ] 验证 `/v1/chat/completions` 返回 assistant 回答
- [ ] 验证流式接口 `stream:true`
- [ ] 提交

---

## 7. 测试覆盖

| 测试文件 | 覆盖内容 |
|---|---|
| `test_parse_context.py` | 完整 JSON 解析、无 steps、非法 JSON、越界索引 |
| `test_route_intent.py` | 7 个意图用例（data_query / concept / debug / other） |
| `test_expert_nodes.py` | FakeModel 注入、消息结构验证、占位返回 |
| `test_graph.py` | `build_agent()` 返回值结构、全流程 FakeModel 调用 |

---

## 8. 已知限制（Phase 1）

| 限制项 | 说明 | 解决方案（Phase 2） |
|---|---|---|
| 无动画 | `animate` 分支返回占位文本 | 实现 SVG + SMIL 生成器 |
| 无知识检索 | debug 专家完全依赖 LLM | 构建 `error_quickref.json` + 关键词匹配 |
| 无记忆 | 每次对话独立，无跨会话状态 | 设计用户画像字段 + SQLAlchemy 存储 |
| `animate` 路由 | 仍会被关键词命中触发 | Phase 2 接入真实动画生成器 |

---

## 9. 验收标准

- [ ] `uv run pytest tests/` 全部通过，无 skip / xfail
- [ ] `python -c "from agents.agent import build_agent; b = build_agent(); assert hasattr(b, 'builder')"` 无报错
- [ ] `/health` → `status=ok`
- [ ] `/v1/chat/completions` → 返回含 assistant 回答的 JSON
- [ ] 带 `compile_error` 的请求 → 路由至 debug，回答引用错误内容
- [ ] 带"为什么"类问题 → 路由至 data_query，回答引用步骤/变量数据
- [ ] 无法归类问题 → 路由至 other，返回通用回答

---

## 10. 后续计划预留

以下内容将在 Phase 2 计划中详细定义：

- [ ] **动画生成**: SVG + SMIL 模板，`build_animation_svg()`，`classify_algorithm()`
- [ ] **知识检索**: `assets/knowledge/error_quickref.json`，关键词匹配 `search_error_quickref()`
- [ ] **跨会话记忆**: `src/learning/memory.py`，用户画像字段设计，`make_session_factory()`
- [ ] **长期记忆节点**: `load_memory()` / `write_memory()` 加入 StateGraph
- [ ] **animate 路由完善**: 关键词 + 算法类型双重判断
