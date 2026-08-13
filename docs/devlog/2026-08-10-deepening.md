# 2026-08-10 — Phase 2: Agent 深化流水线

## 背景
将 JavaTutor 从 "规则路由 + 单次回答" 升级为 "LLM 意图分类 + 上下文压缩 + RAG 检索 + 专家生成 + 评论-修订 + 决策追踪" 的深化流水线。

## 完成内容

| 任务 | 文件 | 说明 |
|------|------|------|
| 1. LLM 意图分类 | `intent.py` | 语义分类取代关键词匹配，5 类意图，低置信度 (<0.6) 回退 other |
| 2. 上下文压缩 | `compaction.py` | 步骤 >200 时滑动窗口 (30 步) 摘要，三模式：none/windowed/truncated |
| 3. RAG 知识检索 | `knowledge.py` | 文本分块 → EmbeddingClient (dim=1024) → pgvector HNSW 检索 |
| 4. State 扩展 | `state.py` | 新增 13 个字段：intent_confidence、retrieved_chunks、context_summary 等 |
| 5. Critic-Revise | `critic.py` | 评论节点评估答案质量，不通过时触发修订节点重写 |
| 6. 节点增强 | `nodes.py` | `_resolve_model()` 统一模型解析、RAG 分块注入、`build_final` 决策追踪 |
| 7. 图重写 | `graph.py` | 新流程：parse→compact→route→[RAG→expert→critic→revise→final] |
| 8. 知识资产 | `assets/knowledge/` | 5 条编译错误 + 5 条标准库条目，种子脚本 `tools/seed_knowledge.py` |

## 环境修复
1. **循环导入**：提取 `llm.py` 独立模块，打破 intent.py ↔ nodes.py 循环依赖
2. **数据库兜底**：`db.py` 添加 SQLite fallback，`PGDATABASE_URL` 未配置时服务仍可启动
3. **类型安全**：修复 `LLMClient` 返回类型注解、`list[str|dict]` 的 strip 检查

## 测试
- 81/81 单元测试通过（34 原有 + 47 新增）
- test_run 端到端验证通过

## 关键文件
- `src/graphs/javatutor/intent.py`
- `src/graphs/javatutor/compaction.py`
- `src/graphs/javatutor/critic.py`
- `src/graphs/javatutor/llm.py`
- `src/learning/knowledge.py`
- `src/graphs/javatutor/state.py`
- `src/graphs/javatutor/nodes.py`
- `src/graphs/javatutor/graph.py`
- `src/graphs/javatutor/prompts.py`