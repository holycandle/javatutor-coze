# 2026-08-19 JavaTutor 领域本体计划

> 执行仓库：`javatutor-coze`
> 执行方式：交给 Claude Code 按本计划逐任务执行（计划于 2026-08-19 执行）。

## 背景

Round-1 的 q01 暴露：Agent 对 JavaTutor 产品的理解停留在「词汇级」。当前领域知识只有两处，且都过浅：

- `src/graphs/javatutor/prompting/glossary.py`：10 条一句话术语，常驻但无模块关系。
- `assets/knowledge/javatutor_project.json`：4 条 explanation，靠 RAG 检索、噪声大。

两者都缺**结构化关系**：不知道 `variables` 属于「变量卡片面板」、`heap` 属于「堆面板」、`stackFrames` 属于「调用栈面板」、`output` 属于「控制台」、`line` 驱动「高亮行」。Agent 遇到 q01 的「数据与源码语义矛盾」时，只能编造 TraceEngine 内部机制圆场。

## 目标

建立**结构化领域本体（ontology）**，作为 JavaTutor 产品知识的单一事实来源，并注入 Agent 与 Judge 的「必达层」：

1. 模块清单 + 功能 + 数据来源 + 常见困惑点。
2. 数据字段 schema 到前端面板的映射。
3. 数据契约规则（含反幻觉：数据与源码冲突时的正确行为）。

同一份本体一鱼三吃：喂 Agent（build_context 常驻层）、喂 Judge（grounding 知识基础）、为未来确定性 grounding 核对器提供白名单。

## 设计原则

- **单一事实来源**：本体数据放在 `javatutor-coze` 仓库 `assets/knowledge/`（JSON，可未来从 JavaTutor 侧同步）；代码侧只做加载与格式化。
- **分层**：必达层（模块总览 + field_schema + 契约规则）常驻 prompt；长尾细节仍走 RAG（`javatutor_project.json`），不在本计划范围。
- **不碰外壳契约**：只改 prompt 组装与知识数据，不改 `.coze`/`scripts/`/`src/main.py`/`src/storage/`/`src/utils/`。

## Task 1: 本体数据文件与加载器

**Files:**
- New: `assets/knowledge/javatutor_domain_ontology.json`
- New: `src/graphs/javatutor/prompting/ontology.py`
- New: `tests/test_ontology.py`

### Step 1: 定义本体 schema

`javatutor_domain_ontology.json` 结构：

```jsonc
{
  "modules": [
    {
      "id": "variable_panel",
      "name": "变量卡片",
      "function": "展示当前步骤所有局部变量/参数的当前值",
      "data_field": "steps[i].variables",
      "ui_behavior": "变量值变化时高亮",
      "common_confusions": ["为什么变量值会跳变", "数组下标与值的对应"]
    }
    // ... 其余面板
  ],
  "field_schema": {
    "step": "步骤序号，从 1 起",
    "line": "该步对应的源码行号 → 高亮行",
    "variables": "该步执行后的变量快照 → 变量卡片面板",
    "heap": "堆对象快照 → 堆面板",
    "stackFrames": "调用栈快照 → 调用栈面板",
    "output": "System.out 输出 → 控制台面板"
  },
  "data_contract_rules": [
    "引用必须基于 steps 数据中真实存在的 step/line/变量值",
    "当步骤数据与源码语义冲突时，指出数据异常并给出基于源码的预期值，禁止编造引擎内部机制（如越界读内存）",
    "intent=analyze 时自动执行复杂度与算法/数据结构标签分析"
  ]
}
```

### Step 2: 填充核心模块

至少覆盖 9 个模块：编辑区、变量卡片、堆面板、调用栈、控制流图、控制台、算法可视化、AI 讲解面板、单步播放/高亮行。每个模块填 function / data_field / ui_behavior / common_confusions（可为空数组）。

### Step 3: 加载器

`ontology.py`：

- `load_ontology() -> dict`：读取 JSON（带 `lru_cache`）。
- `build_ontology_block() -> str`：把 modules + field_schema + data_contract_rules 格式化成 prompt 文本块。

### Step 4: 测试

`test_ontology.py`：

- 本体含 `modules` / `field_schema` / `data_contract_rules` 三个键。
- `field_schema` 覆盖 steps 全部字段（step/line/variables/heap/stackFrames/output）。
- `modules` 覆盖全部 9 个模块 id。
- `build_ontology_block()` 输出含模块名与字段映射（如「变量卡片」「heap → 堆面板」）。
- 契约规则含「禁止编造引擎内部机制」。

Run：`uv run pytest tests/test_ontology.py -q`。

## Task 2: 接入 build_context 常驻层

**Files:**
- Modify: `src/graphs/javatutor/nodes.py`（`build_context_node`）
- Modify: `src/graphs/javatutor/prompting/glossary.py`（或保留为兼容）
- Modify: `tests/test_graph.py`

### Step 1: 注入本体块

`build_context_node` 的 `system_instructions` 从 `build_system_prompt("other")` 改为/追加 `build_ontology_block()`（必达层常驻）。

### Step 2: 测试

集成测试断言 `context_built` 含「变量卡片」「堆面板」等模块名，以及契约规则「禁止编造引擎内部机制」。

## Task 3: Judge 同步消费本体

**Files:**
- Modify: `eval/runner/judge.py`（`build_judge_messages`）
- Modify: `tests/test_judge.py`

### Step 1: 注入 Judge

`build_judge_messages` 的 system prompt 追加本体的 `field_schema` + 模块白名单，让 Judge 的 grounding 判断有「合法术语/字段」知识基础。

### Step 2: 测试

断言 `build_judge_messages` 返回的 system 消息含 `field_schema` 字段名（如 `stackFrames`）与模块名（如「堆面板」）。

## Task 4: 回归与文档

- [ ] `uv run pytest -q` 全绿。
- [ ] 更新 `AGENT.md` 登记本计划与相关 devlog。
- [ ] 不主动提交（遵循用户 git 约束）。

## 验证

| 门槛 | 命令 | 结果 |
|---|---|---|
| L1 依赖锁 | `uv sync --frozen` | 无变化 |
| L2 全量测试 | `uv run pytest tests/ -q` | 全绿 |
| L3 离线构建 | `build_agent().builder.compile()` | 输出 ok |
| L5 外壳回归 | shell 路径 grep | 无外壳文件改动 |

## 后续计划（不在本计划范围）

- **确定性 grounding 核对器**：用本体 `field_schema` + 模块白名单，程序化验证回答引用，替代 Judge 的语义猜 grounding。
- **后端语义字段**：在 steps 上增加 `operation` 字段，让引擎自描述（需 JavaTutor 后端配合，改接口契约）。

## Self-Review

### Spec Coverage

| 需求 | 对应任务 |
|---|---|
| 本体数据 + 加载器 | Task 1 |
| 常驻注入 build_context | Task 2 |
| Judge 同步消费 | Task 3 |
| 回归与文档 | Task 4 |

### Placeholder Scan

计划无 `TBD`、`TODO`；所有代码块完整。
