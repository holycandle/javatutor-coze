# 2026-08-14 — Agent 评估系统（双轨）

## 背景
建立 JavaTutor Coze 智能体的双轨评估体系：组件级确定性指标本地跑（不消耗积分），端到端 LLM-as-Judge 在 Coze 平台跑。每轮结果存档、对比 diff，为后续架构改进与 SFT/LoRA 沉淀数据。

## 完成内容

| 任务 | 文件 | 说明 |
|------|------|------|
| 1. 样本集 | `eval/samples/golden_set.jsonl` | 黄金集 6 条：data_query/concept/debug/other/analyze/edge 六桶，含 expected_facts / expected_sources / judge_priority |
| 1. 组件用例 | `eval/samples/component_cases.jsonl` | 5 条：intent×2、citation、critic、rag |
| 2. 意图规则 | `src/graphs/javatutor/intent_rules.py` | 保守关键词意图（非 LLM）`conservative_intent()` + 硬事实核查 `fact_matches()` |
| 3. 组件指标 | `eval/runner/component_metrics.py` | 意图准确率、引用准确率、Critic 拦截率、RAG hit@3、通过率 |
| 4. Judge | `eval/runner/judge.py` + `eval/judge_prompt.md` | 四维评分（relevance/grounding/pollution/correctness），非法 JSON 标记 judge_parse_error |
| 5. e2e runner | `eval/runner/e2e_runner.py` | Coze 平台跑黄金集完整链路，产出回答 + decision_trace |
| 5. 报告 | `eval/runner/report.py` | summary 汇总（均分/grounding/分布）与轮次 diff |
| 6. 门槛集成 | `docs/local-dev-convention.md` | 新增 L2.5 组件级评估门槛；业务代码允许目录新增 `eval/` |

## 环境与配置调整
- `pyproject.toml`：pytest `pythonpath` 由 `["src"]` 扩为 `["src", "."]`，使仓库根下 `eval/` 包可被测试导入。

## 验证结果
- 全量测试 **111/111 通过**（95 既有 + 16 新增：schema 2 / intent_rules 6 / component 1 / judge 4 / report 3）。
- L1 `uv sync --frozen` ✅；L3 离线构建输出 `ok` ✅；L5 外壳回归无输出 ✅。
- 组件级评估样本用例 `pass_rate = 1.0`，符合 L2.5 门槛。

## 遗留问题
- 端到端 runner 与 Judge 需在 Coze 平台执行并消耗积分，本轮仅在本地完成组件级验证，未产出真实端到端评分。
- 黄金集当前 6 条为起步样本，后续按 spec 扩充至 30-50 条并人工评审。
- `eval/archive/` 目录结构与存档脚本（date/round/summary 编排）尚未落地，随首次端到端运行完善。

## 关键文件
- `eval/samples/golden_set.jsonl`、`eval/samples/component_cases.jsonl`
- `eval/runner/component_metrics.py`、`eval/runner/e2e_runner.py`、`eval/runner/judge.py`、`eval/runner/report.py`
- `eval/judge_prompt.md`
- `src/graphs/javatutor/intent_rules.py`
- `docs/local-dev-convention.md`（L2.5）
