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
                text = f"{entry.get('title', '')}\n{entry.get('explanation', '')}"
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


def search_chunks(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
    embedder: Callable = embed_texts,
    fetcher: Callable = _fetch_similar,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    try:
        vector = embedder([query])[0]
        rows = fetcher(vector, top_k)
    except Exception:
        return []
    return [
        {"source": row[0], "chunk_index": row[1], "content": row[2], "score": round(float(row[3]), 4)}
        for row in rows
        if float(row[3]) >= threshold
    ]
