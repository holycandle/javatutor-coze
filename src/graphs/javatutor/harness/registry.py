"""工具注册表与参数校验。

注册表由各工具模块的 ``TOOL_SCHEMA`` **引用**构建（不另写一份，避免与
``tools/`` 分叉）；``validate_args`` 用 schema 做「未知键 + 类型名」校验，
让非法参数在**门闩层**就被拦下，而不是进工具后抛 ``TypeError``。

注册表只管「有哪些工具 + 参数长什么样」（治理侧 P1/P2 用），**不持有可调用引用**：
真正的派发在 ``harness/tools_node.py``（每个工具的执行后处理各不相同），
那里用 ``_DISPATCHED`` 与本表的键做同源断言。

不引入 ``jsonschema``：当前两个工具只用到 ``integer`` / ``string`` 两种类型，
也没有 ``required`` / 数值范围约束。等真出现这些语义再加依赖。
"""

from tools.fetch_execution_context import TOOL_SCHEMA as _FETCH_SCHEMA
from tools.step_facts import TOOL_SCHEMA as _STEP_FACTS_SCHEMA

TOOLS = {
    "fetch_execution_context": {"schema": _FETCH_SCHEMA},
    "step_facts": {"schema": _STEP_FACTS_SCHEMA},
}

# type-name → 谓词。bool 是 int 的子类，必须显式排除，否则 True 会被当成合法 step_index。
_TYPE_CHECKS = {
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
}

_TYPE_LABELS = {int: "integer", str: "string", bool: "boolean", float: "number"}


def validate_args(tool: str, args: dict) -> list[str]:
    """校验参数，返回问题列表（空列表 == 通过）。"""
    entry = TOOLS.get(tool)
    if entry is None:
        return [f"工具 {tool} 不在注册表中"]

    props = entry["schema"].get("parameters", {}).get("properties", {})
    problems: list[str] = []

    for key in args:
        if key not in props:
            allowed = " / ".join(sorted(props)) or "（无参数）"
            problems.append(f"未知参数 {key}；{tool} 接受：{allowed}")

    for key, value in args.items():
        spec = props.get(key)
        if not spec:
            continue
        expected = spec.get("type")
        check = _TYPE_CHECKS.get(expected)
        if check is None or check(value):
            continue
        got = _TYPE_LABELS.get(type(value), type(value).__name__)
        problems.append(f"参数 {key} 应为 {expected}，实际是 {got}")

    return problems
