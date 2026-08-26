"""GSSC 上下文工程：Gather-Select-Structure-Compress。"""

import json
import math
import re
import time
from typing import Any

DEFAULT_MAX_TOKENS = 3000
RESERVE_RATIO = 0.2
RELEVANCE_WEIGHT = 0.7
RECENCY_WEIGHT = 0.3
MIN_RELEVANCE = 0.1


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text or "") * 0.75))


def jaccard(a: str, b: str) -> float:
    sa = set(re.findall(r"\w+", (a or "").lower()))
    sb = set(re.findall(r"\w+", (b or "").lower()))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def recency(timestamp: float, now: float | None = None) -> float:
    now = now or time.time()
    age_hours = max(0, (now - timestamp) / 3600)
    return max(0.1, math.exp(-0.1 * age_hours / 24))


class ContextPacket:
    def __init__(self, content, timestamp=None, token_count=None, relevance_score=0.5, metadata=None):
        self.content = content
        self.timestamp = timestamp or time.time()
        self.token_count = token_count or estimate_tokens(content)
        self.relevance_score = relevance_score
        self.metadata = metadata or {}


def gather(state, history=None, memories=None) -> list[ContextPacket]:
    packets = []
    q = state.get("user_question", "")
    packets.append(ContextPacket(f"### 用户问题\n{q}", relevance_score=1.0, metadata={"section": "Task"}))
    packets.append(ContextPacket(f"### 源代码\n```java\n{state.get('source_code', '')}\n```", relevance_score=0.8, metadata={"section": "Evidence"}))
    for chunk in state.get("retrieved_chunks") or []:
        packets.append(
            ContextPacket(f"[{chunk['source']}] {chunk['content'][:300]}", relevance_score=float(chunk.get("score", 0.5)), metadata={"section": "Evidence", "source": chunk["source"]})
        )
    analysis = state.get("analysis_result")
    if analysis:
        packets.append(ContextPacket(f"### 分析结果\n{json.dumps(analysis, ensure_ascii=False)[:500]}", relevance_score=0.9, metadata={"section": "Evidence"}))
    run_memory = state.get("run_context_memory")
    if run_memory:
        packets.append(
            ContextPacket(
                f"### 运行上下文摘要\n{json.dumps(run_memory, ensure_ascii=False)[:300]}",
                relevance_score=0.85,
                metadata={"section": "Memory"},
            )
        )
    has_position = bool(state.get("has_steps")) or (
        state.get("current_step_index") not in (None, 0)
        or state.get("current_line") not in (None, 0)
    )
    if has_position:
        index = state.get("current_step_index", 0)
        try:
            display_index = int(index) + 1
        except (TypeError, ValueError):
            display_index = index
        total_steps_text = (
            f"- 总步骤数: {state.get('steps_count', 0)}"
            if state.get("has_steps")
            else "- 总步骤数: 未提供（步骤数据缺失）"
        )
        packets.append(
            ContextPacket(
                f"### 当前执行位置\n"
                f"- 当前步骤索引: {index}（展示为第 {display_index} 步）\n"
                f"- 当前行号: {state.get('current_line', '')}\n"
                f"{total_steps_text}",
                relevance_score=0.9,
                metadata={"section": "Evidence"},
            )
        )
    for m in memories or []:
        packets.append(
            ContextPacket(m.get("content", ""), timestamp=float(m.get("created_at", time.time())), relevance_score=0.5 + float(m.get("importance", 0.5)) * 0.4, metadata={"section": "Memory"})
        )
    for msg in (history or [])[-5:]:
        packets.append(
            ContextPacket(f"[{msg.get('role', 'user')}] {msg.get('content', '')[:200]}", timestamp=float(msg.get("timestamp", time.time())), relevance_score=0.4, metadata={"section": "Context"})
        )
    return packets


def select(packets, query, max_tokens=DEFAULT_MAX_TOKENS, reserve_ratio=RESERVE_RATIO) -> list[ContextPacket]:
    budget = max_tokens * (1 - reserve_ratio)
    scored = []
    for p in packets:
        rel = p.relevance_score if p.relevance_score is not None else jaccard(query, p.content)
        combined = RELEVANCE_WEIGHT * rel + RECENCY_WEIGHT * recency(p.timestamp)
        if combined >= MIN_RELEVANCE:
            scored.append((combined, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    chosen, used = [], 0
    for _, p in scored:
        if used + p.token_count > budget and chosen:
            break
        chosen.append(p)
        used += p.token_count
    return chosen


def structure(chosen, system_instructions="") -> str:
    sections = {"Role & Policies": system_instructions, "Task": [], "Evidence": [], "Memory": [], "Context": [], "Output": "遵循输出契约。"}
    for p in chosen:
        key = p.metadata.get("section", "Context")
        sections.setdefault(key, []).append(p.content)
    blocks = []
    for name in ("Role & Policies", "Task", "Evidence", "Memory", "Context", "Output"):
        val = sections.get(name, [])
        if isinstance(val, str):
            if val:
                blocks.append(f"[{name}]\n{val}")
        elif val:
            blocks.append(f"[{name}]\n" + "\n\n".join(val))
    return "\n\n".join(blocks)


def compress(text, max_tokens=DEFAULT_MAX_TOKENS) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    budget = max_tokens * 0.8
    parts, used = [], 0
    for block in text.split("\n\n"):
        if used + estimate_tokens(block) > budget:
            parts.append("[...已压缩...]")
            break
        parts.append(block)
        used += estimate_tokens(block)
    return "\n\n".join(parts)


def build_context(state, history=None, memories=None, system_instructions="", max_tokens=DEFAULT_MAX_TOKENS) -> str:
    packets = gather(state, history=history, memories=memories)
    chosen = select(packets, state.get("user_question", ""), max_tokens=max_tokens)
    return compress(structure(chosen, system_instructions=system_instructions), max_tokens=max_tokens)
