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


def memory_relevance(content, importance, query, semantic_weight=0.6, importance_weight=0.4) -> float:
    """记忆包相关性：语义匹配（jaccard）与重要性地板的加权。

    semantic_weight 支配（让『与当前问题相关』的记忆领先），importance_weight
    提供地板（semantic_weight, importance_weight 和应为 1.0，权重可 A/B 调整）。
    """
    semantic = jaccard(query or "", content or "")
    floor = 0.5 + float(importance or 0.0) * 0.5
    return semantic_weight * semantic + importance_weight * floor


def recency(timestamp: float, now: float | None = None) -> float:
    now = now or time.time()
    age_hours = max(0, (now - timestamp) / 3600)
    return max(0.1, math.exp(-0.1 * age_hours / 24))


_TYPE_RE = re.compile(r"\b(?:class|interface|record|enum|@interface)\s+([A-Za-z_][\w]*)")


def _file_type_hint(code: str) -> str:
    """从代码里提炼类型提示：首个 class/interface/record/enum 名，无则行数。"""
    m = _TYPE_RE.search(code or "")
    if m:
        return m.group(1)
    lines = (code or "").splitlines()
    return f"{len(lines)} 行"


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
    # 项目结构概览：仅当 files 非空时注入，token 极小；其他文件由 agent 按需读。
    project_files = state.get("files") or {}
    if project_files:
        overview_lines = [
            f"- {name} — {_file_type_hint(code)}"
            for name, code in sorted(project_files.items())
        ]
        packets.append(
            ContextPacket(
                "### 项目结构\n" + "\n".join(overview_lines)
                + "\n\n需要某个文件内容时，用 fetch_execution_context 的 file 参数读取；默认读主入口。",
                relevance_score=0.75,
                metadata={"section": "Evidence"},
            )
        )
    # 源代码仅当读取工具已暂存 fetched_context.source_code 时注入，避免无条件强制填充整段代码。
    # 整体代码由 agent 通过 fetch_execution_context 工具按需读取。
    if (state.get("fetched_context") or {}).get("source_code"):
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
    # 概念题不注入「当前执行位置」：该块对**每一道题**都以 relevance 0.9 落 [Evidence]，
    # 是「概念题被当当前步作答」的直接上下文锚点（计划 2026-09-14 D3）。
    # 概念题可从代码 + 知识作答，不需要「第几步/第几行」；`### 项目结构` 保留，
    # 以便模型仍能按文件名用 `file` 参数取代码。
    has_position = state.get("intent") != "concept" and (
        bool(state.get("has_steps"))
        or state.get("current_step_index") not in (None, 0)
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
        current_step_file = state.get("current_step_file", "")
        packets.append(
            ContextPacket(
                f"### 当前执行位置\n"
                f"- 当前步骤索引: {index}（展示为第 {display_index} 步）\n"
                f"- 当前步所在文件: {current_step_file or '未提供'}\n"
                f"- 当前行号: {state.get('current_line', '')}\n"
                f"{total_steps_text}",
                relevance_score=0.9,
                metadata={"section": "Evidence"},
            )
        )
    # 运行模式：事实由前端随提问送来（后端透传）。缺失（旧客户端）⇒ 不注入，零行为变化。
    # 同一事实只渲染一次：packet 说值，系统提示的「运行模式判读」段说规则，互不重复。
    run_mode = state.get("run_mode") or ""
    if run_mode:
        n = int(state.get("test_case_count") or 0)
        label = (
            f"测试模式（已保存用例 {n} 条）"
            if run_mode == "test"
            else f"默认模式（测试模式未激活：已保存用例 {n} 条）"
        )
        packets.append(
            ContextPacket(
                "### 运行模式\n"
                f"- 本次运行提交给后端的模式：{label}\n"
                "- 「找不到某个类 / 没有 main / 无法执行入口」这类报错与模式强相关，"
                "判读规则见系统提示的「运行模式判读」段。",
                relevance_score=0.9,
                metadata={"section": "Evidence"},
            )
        )
    for m in memories or []:
        packets.append(
            ContextPacket(
                m.get("content", ""),
                timestamp=float(m.get("created_at", time.time())),
                relevance_score=memory_relevance(m.get("content", ""), float(m.get("importance", 0.5)), q),
                metadata={"section": "Memory"},
            )
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
