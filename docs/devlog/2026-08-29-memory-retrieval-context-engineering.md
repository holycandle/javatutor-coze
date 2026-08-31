# 2026-08-29 Memory Retrieval Context Engineering

## 改动内容

执行计划 `docs/plan/2026-08-29-memory-retrieval-context-engineering-plan.md`，实现设计文档 `docs/spec/2026-08-29-memory-retrieval-context-engineering-design.md`。让会话记忆在**预取进上下文**时按「与当前问题的相关性」挑选，而非只按「重要性 + 新近性」。

1. **记忆包相关性打分**（`src/graphs/javatutor/context_builder.py`）
   - 新增纯函数 `memory_relevance(content, importance, query, semantic_weight=0.6, importance_weight=0.4)`：语义匹配（jaccard）× 重要性地板双因子，`semantic_weight` 主导让相关记忆领先，`importance_weight` 提供地板防高重要性记忆被彻底过滤。
   - `gather()` 的记忆包分支改用该函数计算 `relevance_score`；`select()` 无需改动（小改动面）。权重作为常量暴露，供 A/B 调参。

2. **扩大记忆候选池**（`src/graphs/javatutor/nodes.py`）
   - `load_session` 中 `store.search(session_id, limit=5)` → `limit=10`，给相关性打分更多候选。

3. **测试**（新增 `tests/test_memory_retrieval.py`）
   - `memory_relevance`：相关 vs 不相关排序、importance 地板边界、空 query 不炸。
   - `gather`：记忆包相关性随 query 匹配度变化、结构仍含 importance 字段。
   - `load_session`：候选数被传递为 10。

4. **协作指南**（`docs/agent-collaboration-guide.md`，工作区已有未提交改动）
   - 新增「信息分层原则」小节：知识/RAG + 会话记忆走上下文工程预取；单步执行证据走 JIT 工具；明确不做暴露 MemoryTool/read_code。
   - `load_session` 描述改为「按『与当前问题的相关性』挑选（候选 10 条）」。
   - 本改动在本次实现前已存在于工作区，与计划/设计对齐，未额外修改。

## 验证结果

- L1 依赖锁 `uv sync --frozen` → ok（135 packages，无锁文件变化）。
- L2 全量测试 `uv run pytest -q` → **156 passed**（原 154 + 新增 `test_memory_retrieval.py` 6 例；`test_context_builder.py`、`test_build_final.py`、`test_main_agent.py` 均绿，无回归）。
- L3 离线构建 `build_agent().builder.compile()` → `ok`。
- L5 外壳回归：改动仅 `src/graphs/`、`tests/`、`docs/`，未碰 `src/main.py`/`scripts/`/`.coze`/`src/storage/`/`src/utils/`。

## 遗留问题

- `memory_relevance` 用 `jaccard`（`re.findall(r"\w+", ...)`）对**无空格中文整段**粒度偏粗，作为零依赖廉价基线可接受；升级路径为轻量 embedding 或 jieba 分词（spec 第 8 节），本次不实现。
- 端到端评估（Judge 均分对比）未执行——本轮只改了记忆预取相关性，未触及 prompt/上下文主链路结构；如需正式合入仍应按规约补端到端均分对比。
- 改动**未 commit / push**（执行者未被授权）；合并前需按规约第 5 节全量门槛确认、补 L4 HTTP 冒烟（本次 SKIP，需本地模型端点）。
