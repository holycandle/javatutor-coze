"""Task 5: 会话工作记忆测试."""

import time

from learning.memory import DictMemoryStore


def test_add_search_importance():
    store = DictMemoryStore(ttl_seconds=3600, capacity=50)
    store.add("s1", "上次分析：复杂度 O(n)", importance=0.85)
    store.add("s1", "问答摘要", importance=0.5)
    rows = store.search("s1", limit=5, min_importance=0.6)
    assert len(rows) == 1
    assert rows[0]["importance"] == 0.85


def test_expire_removes_old_memories():
    store = DictMemoryStore(ttl_seconds=1)
    store.add("s1", "old", importance=0.9)
    time.sleep(1.1)
    assert store.search("s1") == []


def test_capacity_evicts_lowest_importance():
    store = DictMemoryStore(ttl_seconds=3600, capacity=2)
    store.add("s1", "a", importance=0.3)
    store.add("s1", "b", importance=0.8)
    store.add("s1", "c", importance=0.9)
    rows = store.search("s1")
    assert len(rows) == 2
    assert rows[0]["importance"] == 0.9
