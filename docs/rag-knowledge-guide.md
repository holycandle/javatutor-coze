# RAG 知识库使用指南

## 概述

JavaTutor Agent 使用 pgvector (PostgreSQL 向量扩展) 作为知识库引擎。知识库用于在回答问题时提供额外上下文，帮助 Agent 给出更准确、更具体的回答。

## 知识资产格式

知识库数据存储在 `assets/knowledge/` 目录下，支持三种格式：

### 1. JSON 格式（推荐结构化知识）

适用场景：需要精确检索的条目化知识（如错误码、API 用法、对比表格）

**示例：`assets/knowledge/my_topics.json`**

```json
{
  "entries": [
    {
      "title": "HashSet vs HashMap",
      "explanation": "HashSet 基于 HashMap 实现，存储的是对象；HashMap 存储键值对。"
    },
    {
      "title": "ArrayList 扩容机制",
      "explanation": "默认容量 10，每次扩容为 1.5 倍，不够直接用需求容量。"
    }
  ]
}
```

### 2. Markdown 格式（自然文本）

适用场景：概念说明、使用指南、最佳实践

**示例：`assets/knowledge/recursion.md`**

```markdown
# 递归

递归函数必须有两个要素：
1. 递归终止条件（base case）
2. 递归调用本身

常见错误：忘记写终止条件会导致 StackOverflow。
```

### 3. 纯文本格式

适用场景：简单提示、代码片段

**示例：`assets/knowledge/tips.txt`**

```
Java 中字符串比较必须用 equals() 而不是 ==。
==

算法题中优先考虑边界条件：空数组、单元素、全是负数。
```

## 灌库流程

### 1. 添加/修改知识文件

在 `assets/knowledge/` 目录下创建或编辑文件，支持任意 `.json` / `.md` / `.txt` 文件。

### 2. 执行灌库

```bash
uv run python scripts/seed_knowledge.py
```

### 3. 验证

```bash
# 查看统计
uv run python scripts/seed_knowledge.py --stats

# 手动测试检索
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from learning.knowledge import search_chunks
results = search_chunks('你的测试关键词')
for r in results:
    print(f'  score={r[\"score\"]:.3f}  source={r[\"source\"]}  content={r[\"content\"][:80]}...')
"
```

## 幂等性

灌库脚本是幂等的：
- 按 `source`（文件名）去重，同一 source 的旧数据会先删除再插入
- 多次运行不影响结果，不会产生重复数据

## 表结构

```sql
CREATE TABLE knowledge_chunks (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,          -- 来源文件名
    chunk_index INT NOT NULL,      -- 分块序号
    content TEXT NOT NULL,          -- 文本内容
    embedding VECTOR(1024),        -- 1024 维向量
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source, chunk_index)
);

-- HNSW 索引（余弦距离）
CREATE INDEX idx_knowledge_chunks_embedding 
    ON knowledge_chunks 
    USING hnsw (embedding vector_cosine_ops);
```

## 检索参数

- **维度**: 1024（EmbeddingClient 默认）
- **距离**: 余弦距离（`<=>`）
- **Top-K**: 默认 3
- **阈值**: 默认 0.5（低于此分数的结果会被过滤）
- **索引类型**: HNSW（高效近似最近邻搜索）

## 常见问题

### Q: 灌库后多久生效？
A: 立即生效。灌库脚本完成后，下一次请求就会使用新数据。

### Q: 如何删除知识？
A: 直接删除 `assets/knowledge/` 下对应文件，然后重新灌库即可。

### Q: 数据库在哪？
A: 使用 Coze 平台提供的 Neon PostgreSQL 实例，连接信息在 `.env` 文件中。

### Q: 检索不到想要的内容？
A: 检查：
1. 文件是否在 `assets/knowledge/` 目录下
2. 文件格式是否为 `.json` / `.md` / `.txt`
3. 灌库命令是否成功执行
4. 检索关键词是否与内容语义相关（向量检索基于语义相似度，不一定精确匹配关键词）