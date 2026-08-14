# Agent 评估系统设计

## 1. Goal

为 JavaTutor Coze 智能体建立双轨评估系统：组件级确定性指标本地跑，端到端 LLM-as-Judge 在 Coze 平台跑；每轮评估结果存档并对比，作为后续架构改进与微调（SFT/LoRA）的数据基础。

## 2. Scope

### In Scope

- 黄金集（30-50 条固定考题）与组件用例集。
- 组件级指标：意图准确率、引用准确率、Critic 拦截率、RAG hit@3、通过率。
- 端到端 runner：完整链路跑黄金集，产出回答。
- LLM-as-Judge：四维评分（相关性、Grounding、上下文污染、教学正确性）。
- 存档：`eval/archive/<date>/round-<n>.jsonl` + `summary.json`，含 commit、模型、日期、diff。
- 验证门槛：组件级接入 pytest；端到端改动必须提供 Judge 均分对比。

### Out of Scope

- SFT/LoRA 训练管线（只沉淀数据，训练另立项目）。
- Coze 平台 CI 自动触发（M1 手动执行）。
- 黄金集自动生成（人工编写 + 评审）。

## 3. Decisions

- **D-01**：组件级评估本地跑，端到端评估在 Coze 平台跑。
- **D-02**：黄金集固定，`judge_priority` 字段控制是否必须进端到端。
- **D-03**：Judge 评分四维，每维 1-5，最终分取平均。
- **D-04**：存档 JSONL 每行一条“考题 + Agent 回答 + Judge 结果”。
- **D-05**：每轮 summary 记录 commit、模型、日期、指标与上一轮 diff。
- **D-06**：组件级门槛 = `uv run pytest tests/test_eval_component.py -v` 全过。
- **D-07**：端到端门槛 = 相关改动必须提供本轮均分与上一轮对比；均分下降 > 0.3 或 Grounding 下降 > 0.5 禁止合入。
- **D-08**：bad case 与 correct case 原样存档，作为未来微调数据。
- **D-09**：意图识别采用保守关键词 + 显式 intent（非 LLM），作为上下文优先级信号；intent_accuracy 按此规则评测。
- **D-10**：端到端只在 Coze 平台消耗积分，本地不跑真实 LLM。

## 4. Architecture & Components

```text
eval/
├── samples/
│   ├── golden_set.jsonl
│   └── component_cases.jsonl
├── runner/
│   ├── component_metrics.py
│   ├── e2e_runner.py
│   ├── judge.py
│   └── report.py
├── judge_prompt.md
└── archive/
    └── <date>/
        ├── round-<n>.jsonl
        └── summary.json
```

### Component Responsibilities

- `component_metrics.py`：本地跑组件用例，输出指标；可被 pytest 调用。
- `e2e_runner.py`：Coze 平台执行黄金集完整链路，输出回答 JSONL。
- `judge.py`：按 `judge_prompt.md` 调用 Judge LLM，输出评分 JSONL。
- `report.py`：汇总 summary.json，含与上一轮 diff。
- `judge_prompt.md`：四维评分标准与输出格式约束。

## 5. Data Contracts

### 5.1 golden_set.jsonl

```json
{
  "id": "q01",
  "bucket": "data_query",
  "payload": {"source_code": "...", "steps": [], "current_step_index": 1, "user_question": "...", "compile_error": ""},
  "expected_intent": "data_query",
  "expected_facts": ["step=2", "line=4", "arr[1]=5"],
  "expected_sources": ["知识库: HashMap"],
  "judge_priority": true
}
```

字段：

- `id`：唯一编号。
- `bucket`：`data_query | concept | debug | other | analyze | edge`。
- `payload`：发给 Agent 的完整消息 JSON。
- `expected_intent`：保守关键词分类器的期望意图。
- `expected_facts`：回答必须引用的真实事实（步骤/行/变量/堆 id/输出）。
- `expected_sources`：可选，期望检索来源。
- `judge_priority`：是否进入端到端评测。

### 5.2 component_cases.jsonl

```json
{"type": "intent", "input": {"user_question": "为什么 arr 变了？", "compile_error": ""}, "expected": "data_query"}
{"type": "citation", "input": {...}, "expected_facts": ["step=2", "arr[1]=5"]}
{"type": "critic", "input": {...}, "answer": "根据第 2 步，arr[1] 变成了 8", "expect_fail": true}
{"type": "rag", "input": {"query": "HashMap 原理"}, "expected_sources": ["知识库: HashMap"]}
```

### 5.3 Judge 输出

```json
{"id": "q01", "score": 4.5, "judgement": "correct", "scores": {"relevance": 5, "grounding": 4, "pollution": 5, "correctness": 4}, "reason": "..."}
```

### 5.4 summary.json

```json
{
  "date": "2026-08-14",
  "commit": "abc123",
  "model": "doubao-seed-2-0-lite-260215",
  "round": 1,
  "component": {"intent_accuracy": 0.9, "citation_accuracy": 0.85, "critic_recall": 1.0, "rag_hit_at_3": 0.8, "pass_rate": 0.95},
  "e2e": {"avg_score": 4.2, "grounding_avg": 4.0, "total": 30, "correct": 24, "partially_correct": 4, "incorrect": 2},
  "diff_vs_previous": {}
}
```

## 6. Error Handling

- 单条样本执行失败：记录 `error`，不中断整轮。
- Judge 输出非法 JSON：标记 `judge_parse_error`，该条不计入均分。
- 上一轮缺失：`diff_vs_previous` 为空，不判失败。
- 组件用例注入错误回答时 Critic 未拦截：该条判为失败并计入 `critic_recall`。
- 端到端运行中断：已产出的回答保留，未执行样本标注 `skipped`。

## 7. Testing & Acceptance

### Tests

- `test_eval_component.py`：组件指标可复现、阈值断言、错误样本处理。
- `test_judge_parser.py`：Judge JSON 解析与非法输出兜底。
- `test_report.py`：summary 汇总与 diff 计算。
- 黄金集/组件用例集人工评审后入库。

### Acceptance

1. `uv run pytest tests/test_eval_component.py -v` 全过。
2. 本地跑组件指标可输出 JSON 报告。
3. Coze 平台跑通 `e2e_runner.py`，产出回答 + Judge 评分 + summary。
4. 两次连续运行能看到 diff 对比。
5. bad case / correct case 可从 archive 中抽取为训练数据格式。

## 8. 与验证门槛的集成

- 组件级评估加入本地规约 L2 之后的新门槛：`eval/component` 全过。
- 端到端评估：prompt/上下文/记忆/工具相关改动提交时，PR 说明附本轮与上一轮 Judge 均分对比。
- 均分下降 > 0.3 或 Grounding 下降 > 0.5 时禁止合入。

## 9. Related Docs

- [本地开发规约](../local-dev-convention.md)
- [架构改进设计（待写）](./2026-08-14-agent-architecture-improvement-design.md)
- Hello-Agents 第 8/9 章参考：记忆与检索、上下文工程
