import json

from graphs.javatutor.prompting.contexts import (
    build_concept_context,
    build_data_query_context,
    build_debug_context,
    build_facts_block,
    build_other_context,
)


BASE = {
    "source_code": "public class A {\n    void run() {\n        int x = 1;\n    }\n}",
    "steps": [
        {"step": 0, "line": 3, "variables": {"x": 1}, "heap": {}, "stackFrames": [], "output": None},
        {"step": 1, "line": 3, "variables": {"x": 2}, "heap": {"h1": {"type": "Object"}}, "stackFrames": [{"method": "run"}], "output": "hello"},
    ],
    "steps_json": "[]",
    "steps_count": 2,
    "has_steps": True,
    "current_step_index": 1,
    "current_line": 3,
    "current_variables": {"x": 2},
    "user_question": "为什么 x 变了？",
    "compile_error": "",
    "intent": "data_query",
    "algorithm_tags": ["排序"],
    "retrieved_chunks": [],
}


def test_data_query_context_has_line_snapshot_diff():
    ctx = build_data_query_context(BASE)
    assert "int x = 1" in ctx  # 当前行代码
    assert "变量快照" in ctx
    assert "堆对象" in ctx
    assert "栈帧" in ctx
    assert "输出" in ctx
    assert "与上一步对比" in ctx
    assert "x: 1 → 2" in ctx


def test_debug_context_has_compile_error():
    ctx = build_debug_context({**BASE, "compile_error": "error: ';' expected"})
    assert "编译错误" in ctx
    assert "';' expected" in ctx


def test_context_has_method_and_tags():
    ctx = build_concept_context({**BASE, "method_name": "run", "method_signature": "void run()"})
    assert "方法名: run" in ctx
    assert "算法标签: 排序" in ctx


def test_facts_block_contains_real_fields():
    facts = build_facts_block(BASE)
    assert "堆对象" in facts
    assert "栈帧" in facts
    assert "输出" in facts


def test_facts_block_includes_step_memories():
    """评审 facts 须包含主 Agent 工具循环查到的 step_facts 证据，才能核对非当前步引用。"""
    facts = build_facts_block(
        {
            **BASE,
            "step_memories": [
                {"step_index": 6, "content": "第 7 步正在交换 arr[0] 和 arr[1]（diff: ...）"},
            ],
        }
    )
    # 当前步快照只在 current_step_index 处，但评审要能核对其余步的证据
    assert "已查询的步骤证据（step_facts）" in facts
    assert "第 6 步: 第 7 步正在交换 arr[0] 和 arr[1]" in facts


def test_facts_block_empty_without_step_memories():
    """无 step_memories 时不输出该块，保持原有行为。"""
    facts = build_facts_block(BASE)
    assert "已查询的步骤证据" not in facts


def test_out_of_range_line_is_placeholder():
    ctx = build_other_context({**BASE, "current_line": 999})
    assert "(行号超出范围)" in ctx
