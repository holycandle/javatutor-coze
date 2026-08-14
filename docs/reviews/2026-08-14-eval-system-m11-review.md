# 评估系统 M1.1 Review 日志

> 审查对象：remote mode 与扩展指标（M1.1 新增）
> 审查日期：2026-08-14
> 分支：feat/eval-system

## 结论

M1.1 实现与 spec/plan Task 7 一致，评估相关测试 18 项全部通过。可以进入架构改进阶段；工具准确率与 token 指标的真实取值依赖架构改进落地后 Agent 输出 `tool_calls` / `token_usage`。

## 验证结果

```text
uv run pytest tests/test_eval_remote.py tests/test_eval_report.py tests/test_eval_component.py tests/test_judge.py tests/test_samples_schema.py tests/test_intent_rules.py -v
=> 18 passed
```

覆盖：remote 决策痕迹解析、扩展指标计算、组件指标、Judge、样本 schema、意图规则。

## 发现

### P2：chat_remote 的 SSE 解析缺少测试

- 目前只测了 `parse_decision_trace`，`chat_remote` 的 SSE `message/answer` 分片解析没有测试。
- 建议：用 mock 的 httpx stream 补充一条“SSE 多分片拼接 + [DONE] 终止”的用例。

### P2：扩展指标样本覆盖不足

- `golden_set.jsonl` 中只有 q01 带 `expected_tool_calls`，端到端 `tool_call_accuracy` 分母为 1，统计意义有限。
- 建议：端到端基线前把带工具用例扩到 10+ 条。

### P3：summarize 未自动合并扩展指标

- `compute_extended_metrics` 需要调用方手动 `summary["e2e"].update(...)`。
- 建议：给 `summarize` 增加可选参数 `extended`，内部自动合并，减少漏合并风险。

### P3：token_usage 统计口径

- `avg_token_usage` 只对“决策痕迹含 token_usage”的样本取平均；缺失样本会被静默忽略，可能高估或低估。
- 建议：在 summary 中同时输出 `token_usage_sample_count`。

### P3：remote payload 需以真实 Coze API 校验

- `chat_remote` 的请求体参照了 JavaTutor CozeService 的 v3/chat 形态，实际部署接口字段需在 Coze 平台实测确认。

## 与架构改进的依赖

- `tool_call_accuracy` / `avg_token_usage` 依赖决策痕迹中的 `tool_calls` / `token_usage`，当前旧架构不会输出，指标暂为 0 或缺失。
- 架构改进落地后需重跑端到端，才能产出有效值；这是预期顺序，不算缺陷。

## 后续行动

- 补 `chat_remote` SSE mock 测试。
- 扩充含 `expected_tool_calls` 的黄金样本。
- `summarize` 支持自动合并 `extended`。
- 架构改进实现后跑首轮端到端基线。
