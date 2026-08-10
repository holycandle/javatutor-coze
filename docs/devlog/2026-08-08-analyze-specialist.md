# 2026-08-08 — Analyze 专家节点

## 背景
为 JavaTutor Agent 增加代码分析能力，自动分析用户提交代码的复杂度与潜在问题。

## 完成内容
- 新增 `analyze` 专家节点，提供代码复杂度分析
- 输出结构化 JSON：`{time_complexity, space_complexity, suggestions, ...}`
- 分析维度：时间复杂度、空间复杂度、算法类型、优化建议、常见错误
- 测试覆盖：正常分析、异常 JSON 回退、Prompt 结构验证

## 关键文件
- `src/graphs/javatutor/nodes.py`（analyze_node）
- `src/graphs/javatutor/prompts.py`（SYSTEM_PROMPT_ANALYZE）