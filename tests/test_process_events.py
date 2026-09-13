"""过程哨兵：构造与解析（纯函数，不依赖图）。

哨兵把「已发生的事实」（阶段、工具调用）随节点返回值即时推给前端，绕开
「只有 ``build_final`` 的 ``messages`` 能出流」的限制，且不改外壳、不改 Java 代理。
格式为 HTML 注释，故即使前端未拦截也会渲染为不可见（降级安全）。

本文件与前端 ``src/utils/processEvents.test.js`` **同构**——同一格式两份实现，靠测试对齐。
"""

import json

from graphs.javatutor.process_events import (
    PROCESS_KWARG,
    PROCESS_MARK_PREFIX,
    PROCESS_MARK_SUFFIX,
    build_process_event,
    parse_process_events,
    with_process_events,
)

STAGE = {"kind": "stage", "text": "正在分析问题…"}
TOOL = {
    "kind": "tool",
    "tool": "step_facts",
    "args": {"step_index": 4, "line": 10},
    "status": "ok",
    "latency_ms": 120.5,
}


def test_build_wraps_payload_in_html_comment():
    out = build_process_event(STAGE)
    assert out.startswith(f"\n{PROCESS_MARK_PREFIX}")
    assert out.endswith(f"{PROCESS_MARK_SUFFIX}\n")
    payload = out[len(PROCESS_MARK_PREFIX) + 1 : -len(PROCESS_MARK_SUFFIX) - 1]
    assert json.loads(payload) == STAGE


def test_build_keeps_non_ascii_readable():
    """``ensure_ascii=False``：负载里直接是中文，便于日志与人工排查。"""
    out = build_process_event(STAGE)
    assert "正在" in out
    assert "\\u" not in out


def test_build_payload_never_contains_the_terminator():
    """负载内不得出现 ``-->``，否则解析的正则会提前截断（构造侧保证）。"""
    out = build_process_event({"kind": "stage", "text": "箭头 --> 与 --> 多枚"})
    body = out[len(PROCESS_MARK_PREFIX) + 1 : -len(PROCESS_MARK_SUFFIX) - 1]
    assert "-->" not in body
    # 且转义后仍能还原原文
    assert parse_process_events(out)["events"] == [{"kind": "stage", "text": "箭头 --> 与 --> 多枚"}]


def test_roundtrip_strips_sentinel_completely():
    result = parse_process_events(build_process_event(TOOL))
    assert result["events"] == [TOOL]
    assert result["clean"] == ""


def test_mixed_text_keeps_prose_only():
    text = "正文A" + build_process_event(STAGE) + "正文B" + build_process_event(TOOL)
    result = parse_process_events(text)
    assert result["clean"] == "正文A正文B"
    assert result["events"] == [STAGE, TOOL]


def test_malformed_sentinel_is_dropped_not_left_in_clean():
    """畸形 JSON：不抛错、不进 events，**也不得**留在 clean 里（不能当正文漏出去）。"""
    text = "前" + "\n<!--jt:process {bad json}-->\n" + "后"
    result = parse_process_events(text)
    assert result["events"] == []
    assert result["clean"] == "前后"


def test_non_dict_payload_is_dropped():
    text = "前" + "\n<!--jt:process [1,2]-->\n" + "后"
    result = parse_process_events(text)
    assert result["events"] == []
    assert result["clean"] == "前后"


def test_no_sentinel_returns_text_unchanged():
    result = parse_process_events("普通正文，没有哨兵")
    assert result["clean"] == "普通正文，没有哨兵"
    assert result["events"] == []


def test_empty_input():
    assert parse_process_events("") == {"clean": "", "events": []}


def test_process_kwarg_exported():
    """Task 2/3 用该常量做 ``additional_kwargs`` 标记。"""
    assert PROCESS_KWARG == "jt_process"


# ── 哨兵消息包装（langchain AIMessage + 显式 id）──


def test_process_message_marks_kwarg_and_ids_by_request():
    from graphs.javatutor.process_events import process_message

    msg = process_message(STAGE, {"request_started_at": 123.5}, 0)
    assert msg.id == "jt-proc-123.5-0"
    assert msg.additional_kwargs[PROCESS_KWARG] is True
    assert parse_process_events(msg.content)["events"] == [STAGE]


def test_with_process_events_assigns_unique_ids_per_event():
    """同一次发射的多条事件必须拿到**不同** id。

    否则 ``add_messages`` 认作同一条而只保留最后一条，前面的静默丢失
    （实测踩过：``run_tools`` 一次发 3 条，前端只看到 1 条）。
    """
    out = with_process_events({}, [STAGE, TOOL, {"kind": "stage", "text": "第三条"}])
    ids = [m.id for m in out["messages"]]
    assert len(ids) == len(set(ids)) == 3
    assert out["process_event_ids"] == ids


def test_with_process_events_accumulates_and_continues_seq():
    """``process_event_ids`` 无 reducer：累加旧值，且新序号接着旧长度往下排。"""
    out = with_process_events(
        {"process_event_ids": ["jt-proc-a-0"], "request_started_at": "a"}, [STAGE, TOOL]
    )
    assert [m.id for m in out["messages"]] == ["jt-proc-a-1", "jt-proc-a-2"]
    assert out["process_event_ids"] == ["jt-proc-a-0", "jt-proc-a-1", "jt-proc-a-2"]
