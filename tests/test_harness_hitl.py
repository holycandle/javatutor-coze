"""HITL（human-in-the-loop）离线自证：``interrupt()`` + ``Command(resume=...)``。

线上没有 resume 通道（spec §6），所以这里必须**离线**证明：开关一旦打开，
门闩的 P4（文件名歧义）能真的挂起，且用户的选择能**被真正用上**——恢复值用来补全
原提案里唯一不可判定的 ``file``，补齐后放行到执行节点（``P4-resolved``）。

用 ``MemorySaver`` 做 checkpointer 才能跨 ``invoke`` 保住 thread 状态。
"""

import json

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from graphs.javatutor.graph import build_flow_graph
from graphs.javatutor.harness.contracts import GuardDecision
from graphs.javatutor.harness.guard import MAX_ROUNDS
from graphs.javatutor.harness.hitl import hitl_brief, hitl_enabled
from graphs.javatutor.prompts import (
    SYSTEM_PROMPT_ANALYZE,
    SYSTEM_PROMPT_CRITIC,
    SYSTEM_PROMPT_MAIN_AGENT,
    SYSTEM_PROMPT_REVISE,
)

FILES = {
    "Main.java": "public class Main { void f() { int x = 1; } }",
    "Helper.java": "public class Helper {}",
}


def test_hitl_is_off_by_default(monkeypatch):
    """默认关是安全边界：线上没有 resume 通道，默认开启会让提问永久挂起。"""
    monkeypatch.delenv("COZE_AGENT_HITL", raising=False)
    assert hitl_enabled() is False


def test_hitl_truthy_values(monkeypatch):
    for value in ("1", "true", "TRUE", "yes", "on", " 1 "):
        monkeypatch.setenv("COZE_AGENT_HITL", value)
        assert hitl_enabled() is True, value


def test_hitl_falsy_values(monkeypatch):
    for value in ("0", "", "no", "false", "off", "2"):
        monkeypatch.setenv("COZE_AGENT_HITL", value)
        assert hitl_enabled() is False, value


def test_hitl_brief_carries_question_and_options():
    decision = GuardDecision(
        verdict="needs_decision",
        policy="P4",
        reason="项目里有多个文件，但找不到 Mian.java。",
        options=["Helper.java", "Main.java"],
    )
    brief = hitl_brief(decision)
    assert brief["question"] == "需要你确认：项目里有多个文件，但找不到 Mian.java。"
    assert brief["options"] == ["Helper.java", "Main.java"]
    # 必须是副本：调用方改 brief 不能反噬裁决
    brief["options"].append("X.java")
    assert decision.options == ["Helper.java", "Main.java"]


class AmbiguousFileModel:
    """先提一个匹配不到的文件名，恢复后用散文作答。"""

    def __init__(self):
        self.main_calls = 0

    def invoke(self, messages):
        system = messages[0].content or ""
        if system.startswith(SYSTEM_PROMPT_ANALYZE):
            return AIMessage(content='{"complexity": {"time": "O(1)"}}')
        if system.startswith(SYSTEM_PROMPT_MAIN_AGENT):
            self.main_calls += 1
            if self.main_calls == 1:
                return AIMessage(
                    content='{"tool": "fetch_execution_context", "args": {"file": "Mian.java"}}'
                )
            return AIMessage(content="Main.java 才是入口文件")
        if system.startswith(SYSTEM_PROMPT_CRITIC):
            return AIMessage(content='{"pass": true, "issues": []}')
        if system.startswith(SYSTEM_PROMPT_REVISE):
            return AIMessage(content="修订后的回答")
        raise AssertionError(f"未路由的 system prompt: {system[:40]}")


class LastRoundAmbiguityModel:
    """前两轮各查一次单步证据，第 3 轮（最后一轮预算）才提出匹配不到的文件名。"""

    def __init__(self):
        self.main_calls = 0

    def invoke(self, messages):
        system = messages[0].content or ""
        if system.startswith(SYSTEM_PROMPT_ANALYZE):
            return AIMessage(content='{"complexity": {"time": "O(1)"}}')
        if system.startswith(SYSTEM_PROMPT_MAIN_AGENT):
            self.main_calls += 1
            if self.main_calls <= 2:
                return AIMessage(content='{"tool": "step_facts", "args": {"step_index": 0}}')
            if self.main_calls == 3:
                return AIMessage(
                    content='{"tool": "fetch_execution_context", "args": {"file": "Mian.java"}}'
                )
            return AIMessage(content="Main.java 才是入口文件")
        if system.startswith(SYSTEM_PROMPT_CRITIC):
            return AIMessage(content='{"pass": true, "issues": []}')
        if system.startswith(SYSTEM_PROMPT_REVISE):
            return AIMessage(content="修订后的回答")
        raise AssertionError(f"未路由的 system prompt: {system[:40]}")


def _payload() -> dict:
    return {
        "source_code": FILES["Main.java"],
        "files": FILES,
        "entry_file": "Main.java",
        "steps": [{"step": 0, "line": 1, "variables": {"x": 1}}],
        "current_step_index": 0,
        "current_line": 1,
        "user_question": "入口在哪？",
        "compile_error": "",
    }


def _compiled():
    return build_flow_graph().compile(checkpointer=MemorySaver())


def _config(thread_id, model):
    return {
        "configurable": {"thread_id": thread_id, "chat_model": model},
        "recursion_limit": 40,
    }


def _start(compiled, model, thread_id):
    return compiled.invoke(
        {"messages": [HumanMessage(content=json.dumps(_payload(), ensure_ascii=False))]},
        _config(thread_id, model),
    )


def test_hitl_pauses_on_ambiguous_file_and_resumes(monkeypatch):
    monkeypatch.setenv("COZE_AGENT_HITL", "1")
    compiled = _compiled()
    model = AmbiguousFileModel()

    first = _start(compiled, model, "t-hitl")
    assert "__interrupt__" in first, "P4 歧义应挂起等待用户选择"
    brief = first["__interrupt__"][0].value
    assert set(brief["options"]) == {"Main.java", "Helper.java"}
    assert "Mian.java" in brief["question"]

    resumed = compiled.invoke(Command(resume="Main.java"), _config("t-hitl", model))

    assert "__interrupt__" not in resumed
    assert "Main.java 才是入口文件" in resumed["answer"]

    # 裁决变 P4-resolved，且恢复值被**真正用上**：执行的 fetch 带的是用户选的文件
    resolved = [r for r in resumed["step_records"] if r["policy"] == "P4-resolved"]
    # 两条：门闩的裁决记录（带 user_choice）+ 执行节点给这次 fetch 打的同策略观察
    assert len(resolved) == 2
    decisions = [r for r in resolved if r["payload"].get("user_choice")]
    assert len(decisions) == 1
    assert decisions[0]["payload"]["user_choice"] == "Main.java"
    fetches = [
        tc for tc in (resumed.get("tool_calls") or []) if tc["tool"] == "fetch_execution_context"
    ]
    assert any(tc["args"].get("file") == "Main.java" for tc in fetches)
    # 错文件名一次都没有被执行
    assert not any(tc["args"].get("file") == "Mian.java" for tc in fetches)


def test_hitl_resolves_ambiguity_on_the_last_budgeted_round(monkeypatch):
    """边界回归：最后一轮预算触发 P4 时，resume 后用户的选择不能被静默丢弃。

    旧实现把恢复值只写成观察、让模型据它重提——但重提时轮次已用尽，
    ``propose`` 进入收束模式、永不产出 Action，用户的选择就白丢了。
    """
    monkeypatch.setenv("COZE_AGENT_HITL", "1")
    compiled = _compiled()
    model = LastRoundAmbiguityModel()

    first = _start(compiled, model, "t-last-round")
    assert "__interrupt__" in first, "第 3 轮（最后一轮预算）的歧义也要挂起"

    resumed = compiled.invoke(Command(resume="Main.java"), _config("t-last-round", model))

    assert "__interrupt__" not in resumed
    assert resumed["tool_rounds"] == MAX_ROUNDS
    fetches = [
        tc for tc in (resumed.get("tool_calls") or []) if tc["tool"] == "fetch_execution_context"
    ]
    assert any(tc["args"].get("file") == "Main.java" for tc in fetches)
    assert not any(tc["args"].get("file") == "Mian.java" for tc in fetches)
    assert resumed["answer"]
    assert "【决策痕迹】" in resumed["answer"]


def test_hitl_off_never_interrupts(monkeypatch):
    """反证：默认关时同一个歧义提案只会被拒，图照常跑完。"""
    monkeypatch.delenv("COZE_AGENT_HITL", raising=False)
    compiled = _compiled()
    model = AmbiguousFileModel()

    first = _start(compiled, model, "t-deny")
    assert "__interrupt__" not in first
    assert first["step_records"][0]["policy"] == "P4"
    assert first["step_records"][0]["status"] == "denied"
    assert first["guard_decision"]["verdict"] == "deny"
    assert not first.get("tool_calls")
    assert first["answer"]
