"""RAG 知识检索：语料分块、embedding、pgvector 检索。

使用 Coze SDK EmbeddingClient（而非 httpx 直调），dimensions=1024。
"""

import json
import os
from pathlib import Path
from typing import Any, Callable

import psycopg

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "knowledge"
EMBEDDING_DIM = 1024
DEFAULT_TOP_K = 3
DEFAULT_THRESHOLD = 0.3


def chunk_text(text: str, source: str, chunk_size: int = 500, overlap: int = 50) -> list[dict[str, Any]]:
    text = (text or "").strip()
    chunks = []
    start = 0
    index = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append({"source": source, "chunk_index": index, "content": text[start:end]})
        index += 1
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def _entry_text(entry: dict[str, Any]) -> str:
    """把 JSON 语料条目转换为可嵌入的文本。"""
    parts = [entry.get("title", "")]
    keywords = entry.get("keywords") or []
    if keywords:
        parts.append("关键词: " + ", ".join(keywords))
    if entry.get("category"):
        parts.append("类别: " + entry["category"])
    parts.append(entry.get("explanation", ""))
    if entry.get("complexity"):
        parts.append("复杂度: " + entry["complexity"])
    if entry.get("example"):
        parts.append("示例: " + entry["example"])
    return "\n".join(parts)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """使用 Coze SDK EmbeddingClient 逐条生成向量，dimensions=1024。"""
    from coze_coding_dev_sdk import EmbeddingClient

    client = EmbeddingClient()
    return [client.embed_text(t, dimensions=EMBEDDING_DIM) for t in texts]


def _db_url() -> str:
    from storage.database.db import get_db_url

    return get_db_url()


def ensure_schema(url: str | None = None) -> None:
    with psycopg.connect(url or _db_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            # 新库需先启用 pgvector 扩展，否则建表时报 type "vector" does not exist
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                "CREATE TABLE IF NOT EXISTS knowledge_chunks ("
                "id BIGSERIAL PRIMARY KEY, source TEXT NOT NULL, chunk_index INT NOT NULL, "
                f"content TEXT NOT NULL, embedding vector({EMBEDDING_DIM}))"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS knowledge_chunks_hnsw_idx "
                "ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)"
            )


def _vector_to_str(vec: list[float]) -> str:
    """将 float 列表转为 pgvector 可识别的字符串格式: [0.1,0.2,...]"""
    return "[" + ",".join(str(v) for v in vec) + "]"


def insert_chunks(chunks: list[dict[str, Any]], url: str | None = None) -> None:
    """插入知识分块，同 source 的旧数据会被先清除（幂等灌库）。"""
    if not chunks:
        return
    sources = sorted({c["source"] for c in chunks})
    vectors = embed_texts([c["content"] for c in chunks])
    with psycopg.connect(url or _db_url()) as conn:
        with conn.cursor() as cur:
            # 清除同 source 旧数据，避免重复灌库产生重复
            cur.execute(
                "DELETE FROM knowledge_chunks WHERE source = ANY(%s)",
                (sources,),
            )
            for chunk, vector in zip(chunks, vectors):
                cur.execute(
                    "INSERT INTO knowledge_chunks (source, chunk_index, content, embedding) "
                    "VALUES (%s, %s, %s, %s::vector)",
                    (chunk["source"], chunk["chunk_index"], chunk["content"], _vector_to_str(vector)),
                )
        conn.commit()


def seed_assets(url: str | None = None) -> int:
    ensure_schema(url)
    chunks: list[dict[str, Any]] = []
    for path in sorted(ASSETS.glob("*")):
        if path.suffix in (".md", ".txt"):
            chunks.extend(chunk_text(path.read_text(encoding="utf-8"), f"知识库: {path.stem}"))
        elif path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            for entry in data.get("entries", []):
                text = _entry_text(entry)
                chunks.extend(chunk_text(text, f"知识库: {entry.get('title', path.stem)}"))
    insert_chunks(chunks, url)
    return len(chunks)


def _fetch_similar(vector: list[float], top_k: int, url: str | None = None) -> list[tuple]:
    vec_str = _vector_to_str(vector)
    with psycopg.connect(url or _db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source, chunk_index, content, 1 - (embedding <=> %s::vector) AS score "
                "FROM knowledge_chunks ORDER BY embedding <=> %s::vector LIMIT %s",
                (vec_str, vec_str, top_k),
            )
            return cur.fetchall()


def _raw_rows(
    query: str,
    top_k: int,
    embedder: Callable,
    fetcher: Callable,
) -> list[tuple]:
    """取原始检索行（未过滤阈值）：embedding + pgvector 查询。

    ``search_chunks`` 与 ``search_chunks_debug`` 共用此函数，保证两条路径的
    「召回」阶段完全一致（差异只在过滤与否）。空查询返回空列表。
    """
    if not query.strip():
        return []
    vector = embedder([query])[0]
    return fetcher(vector, top_k)


def search_chunks(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
    embedder: Callable = embed_texts,
    fetcher: Callable = _fetch_similar,
) -> list[dict[str, Any]]:
    """检索知识分块；embedding / 查询失败时向调用方抛出异常（而非吞掉）。

    之前内部 try/except 吞掉了 Coze EmbeddingClient 与 pgvector 的后端失败并返回 [],
    导致 retrieve_knowledge 的 except 分支（rag_degraded=True）永远不触发，
    RAG 故障被静默掩盖。改为向上抛出，让 graph 节点能正确置降级标志并记录到决策痕迹。
    """
    rows = _raw_rows(query, top_k, embedder, fetcher)
    return [
        {"source": row[0], "chunk_index": row[1], "content": row[2], "score": round(float(row[3]), 4)}
        for row in rows
        if float(row[3]) >= threshold
    ]


def search_chunks_debug(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
    embedder: Callable = embed_texts,
    fetcher: Callable = _fetch_similar,
) -> dict[str, Any]:
    """检索并返回**全量候选**与阈值判定，供决策痕迹诊断。

    与 ``search_chunks`` 的差别：不过滤低分候选，并把 ``best_score`` / ``kept`` 一并带回，
    使「没召回到」与「召回到但被阈值滤掉」在痕迹里可区分。

    阈值过滤原本发生在 ``search_chunks`` 内部，调用方拿不到被滤掉的行——这正是
    部署侧「sources 恒空且 rag_degraded=false」（即检索成功但无一越阈值）无法定案的
    技术原因。本函数是移除该盲区的诊断通道。

    返回 ``{query, top_k, threshold, candidates[{source, chunk_index, score, content, kept}],
    best_score, kept}``；无候选时 ``best_score`` 为 0.0。``best_score`` 取候选**最高分**
    （不取首条——那会把「最近邻」这一事实偷偷绑到 fetcher 的排序不变量上）。失败语义与
    ``search_chunks`` 一致：向上抛出，不吞成空结果。
    """
    rows = _raw_rows(query, top_k, embedder, fetcher)
    candidates = [
        {
            "source": row[0],
            "chunk_index": row[1],
            "content": row[2],
            "score": round(float(row[3]), 4),
            "kept": float(row[3]) >= threshold,
        }
        for row in rows
    ]
    return {
        "query": query,
        "top_k": top_k,
        "threshold": threshold,
        "candidates": candidates,
        "best_score": max((c["score"] for c in candidates), default=0.0),
        "kept": sum(1 for c in candidates if c["kept"]),
    }
