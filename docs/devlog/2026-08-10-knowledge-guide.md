# 2026-08-10 — 知识库使用说明

## 背景
为方便后续运维，将 RAG 知识库的操作流程文档化，覆盖从添加资产到灌库验证的完整流程。

## 完成内容
- `tools/seed_knowledge.py` 升级：支持 `--stats` 参数查看统计，幂等去重（同 source 先删后插）
- 三种资产格式：JSON（结构化条目）、Markdown（自然文本）、纯文本
- `docs/rag-knowledge-guide.md`：完整使用指南，含表结构、检索参数、常见问题 Q&A

## 使用方式
```bash
# 全量灌库（自动去重）
uv run python tools/seed_knowledge.py

# 查看统计
uv run python tools/seed_knowledge.py --stats
```

## 关键文件
- `docs/rag-knowledge-guide.md`
- `tools/seed_knowledge.py`