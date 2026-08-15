"""会话工作记忆：Postgres 持久化 + 进程内 Dict 兜底。"""

import time
from typing import Any

DEFAULT_TTL_SECONDS = 3600
DEFAULT_CAPACITY = 50


class MemoryStore:
    def add(self, session_id, content, importance=0.5, memory_type="working", ttl_seconds=DEFAULT_TTL_SECONDS):
        raise NotImplementedError

    def search(self, session_id, limit=10, min_importance=0.0):
        raise NotImplementedError

    def expire(self, session_id=None):
        raise NotImplementedError


class DictMemoryStore(MemoryStore):
    def __init__(self, ttl_seconds=DEFAULT_TTL_SECONDS, capacity=DEFAULT_CAPACITY):
        self._items = []
        self._ttl_seconds = ttl_seconds
        self._capacity = capacity

    def add(self, session_id, content, importance=0.5, memory_type="working", ttl_seconds=None):
        # 未显式指定 TTL 时，使用 store 级配置的默认 TTL
        if ttl_seconds is None:
            ttl_seconds = self._ttl_seconds
        self._items.append(
            {
                "session_id": session_id,
                "content": content,
                "importance": importance,
                "memory_type": memory_type,
                "created_at": time.time(),
                "expires_at": time.time() + ttl_seconds,
            }
        )
        self._items.sort(key=lambda m: m["importance"], reverse=True)
        if len(self._items) > self._capacity:
            self._items = self._items[: self._capacity]

    def search(self, session_id, limit=10, min_importance=0.0):
        self.expire(session_id)
        rows = [
            m
            for m in self._items
            if m["session_id"] == session_id and m["importance"] >= min_importance and m["expires_at"] > time.time()
        ]
        return sorted(rows, key=lambda m: (-m["importance"], -m["created_at"]))[:limit]

    def expire(self, session_id=None):
        now = time.time()
        self._items = [m for m in self._items if m["expires_at"] > now and (session_id is None or m["session_id"] == session_id)]


class PostgresMemoryStore(MemoryStore):
    def __init__(self, url=None):
        self._url = url

    def _connect(self):
        import psycopg

        if self._url:
            return psycopg.connect(self._url)
        from storage.database.db import get_db_url

        return psycopg.connect(get_db_url())

    def ensure_schema(self):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS session_memories ("
                    "id BIGSERIAL PRIMARY KEY, session_id VARCHAR(64) NOT NULL, content TEXT NOT NULL, "
                    "memory_type VARCHAR(16) NOT NULL DEFAULT 'working', "
                    "importance DOUBLE PRECISION NOT NULL DEFAULT 0.5, "
                    "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
                    "expires_at TIMESTAMPTZ NOT NULL)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_session_memories_session "
                    "ON session_memories (session_id, expires_at)"
                )
            conn.commit()

    def add(self, session_id, content, importance=0.5, memory_type="working", ttl_seconds=DEFAULT_TTL_SECONDS):
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO session_memories (session_id, content, memory_type, importance, expires_at) "
                    "VALUES (%s, %s, %s, %s, NOW() + (%s || ' seconds')::interval)",
                    (session_id, content, memory_type, importance, int(ttl_seconds)),
                )
            conn.commit()

    def search(self, session_id, limit=10, min_importance=0.0):
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT content, importance, EXTRACT(EPOCH FROM created_at) "
                    "FROM session_memories WHERE session_id = %s AND expires_at > NOW() "
                    "AND importance >= %s ORDER BY importance DESC, created_at DESC LIMIT %s",
                    (session_id, min_importance, limit),
                )
                return [{"content": r[0], "importance": r[1], "created_at": r[2]} for r in cur.fetchall()]

    def expire(self, session_id=None):
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                if session_id:
                    cur.execute("DELETE FROM session_memories WHERE expires_at <= NOW() AND session_id = %s", (session_id,))
                else:
                    cur.execute("DELETE FROM session_memories WHERE expires_at <= NOW()")
            conn.commit()


_store = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        try:
            _store = PostgresMemoryStore()
        except Exception:
            _store = DictMemoryStore()
    return _store
