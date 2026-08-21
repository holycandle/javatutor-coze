# 2026-08-18 Judge 结构化输出 + 兜底率 + 人工复核接入导出

## 改动内容

执行计划 `docs/plan/2026-08-18-judge-structured-output-and-fallback-rate-plan.md`，四项任务：

1. **JSON Schema 约束 + 分数 clamp**（`eval/runner/judge.py`）
   - 新增 `_JUDGE_JSON_SCHEMA`（score/judgement 枚举/scores 各维/reason，全 required，范围 0-5）。
   - `judge_complete` 依次尝试 `json_schema` → `json_object`；`json_schema` 收到 HTTP 400 时记录 warning 并回退。
   - `_coerce_score` clamp [0,5]；`_normalize_parsed` 对各维度分数同样 clamp，字段缺失归一化为 0/incorrect/空 reason，而非判定为解析失败。

2. **兜底率指标 + 字段迁移**（`eval/runner/report.py`）
   - `judge_parse_error` 字段更名为 `judge_fallback`，解析失败确定性地产出 `score=0/judgement=incorrect`。
   - `summarize` 新增 `judge_fallback_rate` 与 `empty_output_rate`（分母 = 全部 judged 样本），显式化解析退化比例。
   - `compute_extended_metrics` 跳过 `judge_fallback` 样本，避免 0 分污染 task_success_rate。

3. **重判 Round-1 并重生成报告**
   - 升级重试策略（3 次 + 退避 + temperature 0.1→0.0）后重判：31 条入库。
   - 见下方验证结果。

4. **人工复核接入导出**（`tools/export_training_data.py`）
   - `export()` 读取 `human_review.jsonl`，`verdict == "reject"` 的样本不进入 SFT/DPO，README 与结果注明过滤数量。

另修复 review 模块显示（`tools/human_review.py` + `tools/eval_cli.py`）：完整打印答案（去除截断）与 Judge 摘要（不再 dump 原始 JSON）；修正 `src/tools` 命名空间遮蔽导致的 `No module named 'tools.human_review'`。

## 验证结果

- 全量测试：`uv run pytest -q` → **121 passed**。
- Round-1 报告重生成：
  - `avg_score` 3.5172 / `grounding_avg` 3.1034（29 条有效评分）
  - `judge_fallback_rate` 0.0645 / `empty_output_rate` 0.0645（2/31，q01/q26 三次空输出兜底）
  - 相对上次重判 diff：`avg_score +0.12`、`grounding_avg +0.31`

## 遗留问题

- DeepSeek 接口不支持 `json_schema`（返回 HTTP 400），实际走 `json_object` 容错路径；schema 约束仅在支持方生效，本地保留双格式降级逻辑。
- q01 / q26 仍为空输出兜底（重试满 3 次仍空），根因在 API 侧随机空返回，非解析问题。
- 知识融合尚未完成：Agent 对 JavaTutor 产品的理解仍停留词汇级，属 `2026-08-19-javatutor-domain-ontology-plan.md`（领域本体）范畴。
