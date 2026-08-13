"""按意图的输出契约。"""

from graphs.javatutor.prompting.versions import PROMPT_VERSION

CONTRACTS = {
    "data_query": (
        "## 输出契约\n"
        "- 必须回答：在哪一步、哪一行、哪个变量、从什么值变成什么值、为什么。\n"
        "- 禁止出现步骤数据中不存在的行号/变量值，禁止凭空构造堆对象 id。\n"
        "- 长度 3-6 句，可含代码块。"
    ),
    "concept": (
        "## 输出契约\n"
        "- 先给核心定义或结论，再结合用户源代码或真实步骤数据举例。\n"
        "- 禁止脱离本次代码空谈教材内容。"
    ),
    "debug": (
        "## 输出契约\n"
        "- 必须包含：错误根因、出错位置（行号）、具体修改建议。\n"
        "- 禁止断言 compile_error 中不存在的错误。"
    ),
    "other": (
        "## 输出契约\n"
        "- 回答工具使用问题时给出可操作指引；无关问题礼貌说明职责范围。"
    ),
}


def get_contract(intent: str) -> str:
    return CONTRACTS.get(intent, CONTRACTS["other"])
