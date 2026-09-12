"""工具注册表与参数校验测试：schema 单一事实源 + 门闩层的参数结构校验。"""

from graphs.javatutor.harness.registry import TOOLS, validate_args
from tools import fetch_execution_context, step_facts


def test_registry_covers_exactly_the_two_tools():
    assert set(TOOLS) == {"fetch_execution_context", "step_facts"}


def test_registry_reuses_tool_schema_objects():
    """同一对象引用，证明注册表没有另抄一份 schema（抄一份就会分叉）。"""
    assert TOOLS["step_facts"]["schema"] is step_facts.TOOL_SCHEMA
    assert TOOLS["fetch_execution_context"]["schema"] is fetch_execution_context.TOOL_SCHEMA


def test_registry_holds_only_schema_not_callables():
    """注册表只管「有哪些工具 + 参数长什么样」。

    曾经每个条目还带一个 ``fn``，但派发其实在 ``tools_node``（每个工具的执行后处理
    各不相同），那个字段是死数据，会让人误以为派发走注册表。
    """
    assert all(set(entry) == {"schema"} for entry in TOOLS.values())


def test_dispatch_table_matches_registry():
    """「放行的工具」与「有执行分支的工具」必须同源（``tools_node`` 在 import 期也断言一次）。"""
    from graphs.javatutor.harness import tools_node

    assert tools_node._DISPATCHED == set(TOOLS)


def test_valid_args_pass():
    assert validate_args("step_facts", {"step_index": 1}) == []
    assert validate_args("fetch_execution_context", {"file": "A.java", "start_line": 3}) == []
    assert validate_args("step_facts", {}) == []


def test_unknown_key_is_reported():
    problems = validate_args("step_facts", {"bogus_key": 1})
    assert any("bogus_key" in p for p in problems)


def test_wrong_type_is_reported():
    problems = validate_args("step_facts", {"step_index": "1"})
    assert any("step_index" in p and "integer" in p for p in problems)


def test_bool_is_not_an_integer():
    """`True` 是 int 的子类，但把布尔当 step_index 用一定是模型出错。"""
    problems = validate_args("step_facts", {"step_index": True})
    assert any("step_index" in p for p in problems)


def test_unknown_tool_is_reported():
    assert validate_args("no_such_tool", {}) != []
