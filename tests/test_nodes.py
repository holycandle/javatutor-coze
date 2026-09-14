"""回答正文清洗：``_strip_leaked_json`` 的规则与端到端回归。

``_strip_leaked_json`` 在 ``build_final`` 里作用于**最终回答正文**，是用户可见产物的
最后一道清洗，所以断言落在它的返回文本上；其中「什么会进用户可见产物」的用例
按红线取证纪律以**端到端产物**（``out["answer"]``）取证。

背景：2026-09-13 联调实测，模型在终答轮把 ``SYSTEM_PROMPT_MAIN_AGENT`` 里逐字示范的
工具调用 JSON 当行首前缀复述出来，且与紧随的 markdown 标题**无分隔换行**：
``{"tool": "fetch_execution_context", "args": {"file": "Main.java"}}### 当前这一步的执行内容``
——``}}###`` 之间没有换行，``###`` 不在行首，标题不被识别。
"""

import json

from langchain_core.messages import AIMessage, HumanMessage

from graphs.javatutor.graph import build_flow_graph
from graphs.javatutor.nodes import _strip_leaked_json
from graphs.javatutor.prompts import (
    SYSTEM_PROMPT_ANALYZE,
    SYSTEM_PROMPT_CRITIC,
    SYSTEM_PROMPT_MAIN_AGENT,
    SYSTEM_PROMPT_REVISE,
)

_ANALYSIS_JSON = json.dumps(
    {"complexity": {"time": "O(1)"}, "algorithms": [], "dataStructures": []},
    ensure_ascii=False,
)

STEPS = [
    {"step": 0, "line": 3, "variables": {"x": 1}},
    {"step": 1, "line": 4, "variables": {"x": 2}},
]

# 实测的畸形输出：工具 JSON 与正文标题连写
GLUED = '{"tool": "fetch_execution_context", "args": {"file": "Main.java"}}### 当前这一步的执行内容'


# ── 规则 0：开头的工具调用 JSON ────────────────────────────────────────────────


def test_strips_leading_tool_json_glued_to_heading():
    """嵌套 args 必须被平衡解析——惰性正则会停在第一个 ``}``，留下孤立括号。"""
    out = _strip_leaked_json(GLUED)
    assert '"tool"' not in out
    assert out.startswith("### 当前这一步"), f"标题前有残留: {out[:20]!r}"
    # 剥离处不得残留孤立的 `}`（惰性 `.*?` 会停在 args 的第一个 `}`）
    assert not out.lstrip().startswith("}")


def test_strips_leading_tool_json_before_prose():
    text = '{"tool": "step_facts", "args": {"step_index": 1, "line": 4}}\n\n正文'
    assert _strip_leaked_json(text) == "正文"


def test_strips_leading_tool_json_with_leading_whitespace():
    text = '\n  {"tool": "step_facts", "args": {}}正文'
    out = _strip_leaked_json(text)
    assert "tool" not in out
    assert "正文" in out


# ── 规则 0b/4b：同一段 JSON 裹在 ``` 围栏里（2026-09-14 联调实测形态）──────────
#
# 模型照 ``_MARKDOWN_RULES`` 教的代码块习惯，把工具调用 JSON 裹进 ```json 当回答交出。
# 裸写那套够不到：规则 0 要求首字符是 ``{``（围栏首字符是反引号），规则 4 要求 ``}`` 后面
# 只剩空白再贴 ``$``（收尾围栏把 ``\s*$`` 挡掉）。正文顶端于是原样出现一个两行 JSON 的
# 代码块——用户截图形态。判据与裸写同口径：**对象且有 ``tool`` 键**。

_TOOL_FETCH = '{"tool": "fetch_execution_context", "args": {"file": "Main.java"}}'
_TOOL_STEP = '{"tool": "step_facts", "args": {"step_index": 0, "line": 10}}'
_FENCED = f"```json\n{_TOOL_FETCH}\n{_TOOL_STEP}\n```"


def test_strips_leading_fenced_tool_json_matching_the_reported_shape():
    """联调截图：正文顶端一个只装两行工具 JSON 的代码块，剥完正文为空。"""
    assert _strip_leaked_json(_FENCED) == ""


def test_strips_leading_fenced_tool_json_before_prose():
    assert _strip_leaked_json(f"{_FENCED}\n\n正文") == "正文"


def test_strips_trailing_fenced_tool_json():
    assert _strip_leaked_json(f"### 正文\n\n{_FENCED}") == "### 正文"


def test_strips_fence_without_language_tag():
    assert _strip_leaked_json(f"```\n{_TOOL_FETCH}\n```\n正文") == "正文"


def test_keeps_fenced_code_that_is_not_a_tool_call():
    """正文代码块不得误伤——判据仍然是「对象且有 ``tool`` 键」，不是「有围栏就剥」。"""
    text = "```java\nint x = 1;\n```\n正文"
    assert _strip_leaked_json(text) == text


def test_keeps_fence_that_mixes_tool_json_with_other_text():
    """围栏体混了别的行 → 整块按正文保留（宁可留着，不可误删用户要的代码块）。"""
    text = f"```json\n{_TOOL_FETCH}\n不是 JSON\n```\n正文"
    assert _strip_leaked_json(text) == text


def test_intent_then_tool_json_both_stripped():
    """两条规则叠加：规则 1 剥掉开头的意图 JSON 后，又暴露出开头的工具 JSON。

    规则 4 靠 ``$`` 锚定只管**结尾**，此处不做二次剥离就会漏网。
    """
    text = '{"intent":"data_query"}\n\n{"tool": "step_facts", "args": {}}\n\n正文'
    assert _strip_leaked_json(text) == "正文"


# ── 既有块必须原样透传（不得误伤） ─────────────────────────────────────────────


def test_keeps_leading_view_navigation_block():
    """``{"views":[...]}`` 是受控输出指令，前端依赖原样透传。"""
    text = '{"views":[{"panel":"tutor","sub":"analysis"}]}\n\n正文'
    assert _strip_leaked_json(text) == text


def test_keeps_edit_suggestion_block():
    """【编辑建议】块同样以 ``{`` 开头，不得被当成工具 JSON 删掉。"""
    text = '正文\n\n【编辑建议】\n{"kind":"patch","target":"Main.java","code":"int x=1;"}'
    out = _strip_leaked_json(text)
    assert "【编辑建议】" in out
    assert '"kind":"patch"' in out


def test_plain_text_unchanged():
    assert _strip_leaked_json("普通正文，没有 JSON") == "普通正文，没有 JSON"


# ── 端到端（红线取证纪律：在最终产物上下结论） ────────────────────────────────


class _GluedToolJsonModel:
    """终答轮返回「工具 JSON + 标题」连写的模型（实测行为的桩）。"""

    def __init__(self, scripts):
        self.scripts = list(scripts)

    def invoke(self, messages):
        system = messages[0].content or ""
        if system.startswith(SYSTEM_PROMPT_ANALYZE):
            return AIMessage(content=_ANALYSIS_JSON)
        if system.startswith(SYSTEM_PROMPT_MAIN_AGENT):
            return AIMessage(content=self.scripts.pop(0) if self.scripts else "没有更多脚本了")
        if system.startswith(SYSTEM_PROMPT_CRITIC):
            return AIMessage(content='{"pass": true, "issues": []}')
        if system.startswith(SYSTEM_PROMPT_REVISE):
            return AIMessage(content="修订后的回答")
        raise AssertionError(f"未路由的 system prompt: {system[:40]}")


def _body(answer: str) -> str:
    """取回答正文段（``【决策痕迹】`` 之前）——trace JSON 里本就含 ``"tool"`` 键。"""
    return answer.split("\n\n【决策痕迹】\n")[0]


def test_end_to_end_glued_tool_json_never_reaches_answer_body():
    """完整图跑一次：终答里的裸工具 JSON 不得出现在用户可见正文。

    不在 ``_strip_leaked_json`` 单测层下结论——``build_final`` 还有
    ``_redact_denied_tools`` 等下游处理，最终产物才是唯一事实。
    """
    model = _GluedToolJsonModel(
        [
            '{"tool": "step_facts", "args": {"step_index": 1}}',  # 先真实调用一次工具
            '{"tool": "fetch_execution_context", "args": {"file": "Main.java"}}### 当前这一步的执行内容\n\n正文内容',
        ]
    )
    payload = {
        "source_code": "public class A { void f() { int x = 1; } }",
        "steps": STEPS,
        "current_step_index": 1,
        "current_line": 4,
        "user_question": "x 怎么变了？",
    }
    out = build_flow_graph().compile().invoke(
        {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]},
        config={"configurable": {"chat_model": model}},
    )

    body = _body(out["answer"])
    assert '"tool"' not in body
    assert "fetch_execution_context" not in body
    assert "### 当前这一步的执行内容" in body
    # 【决策痕迹】段仍在，未被清洗规则误伤
    assert "【决策痕迹】" in out["answer"]


def test_end_to_end_fenced_tool_json_never_reaches_answer_body():
    """完整图跑一次：终答里**裹在 ``` 围栏内**的工具 JSON 同样不得进用户可见正文。

    裸写那条由 ``test_end_to_end_glued_tool_json_never_reaches_answer_body`` 守着；
    本用例守围栏那条。**必须在端到端产物上下结论**：前端 ``stripLeadingToolJson`` 只认裸写
    （首字符必须是 ``{``），所以这条通路没有任何下游兜底，只有 ``build_final`` 一道。
    """
    model = _GluedToolJsonModel(
        [
            '{"tool": "step_facts", "args": {"step_index": 1}}',
            f"{_FENCED}\n\n### 当前这一步的执行内容\n\n正文内容",
        ]
    )
    payload = {
        "source_code": "public class A { void f() { int x = 1; } }",
        "steps": STEPS,
        "current_step_index": 1,
        "current_line": 4,
        "user_question": "x 怎么变了？",
    }
    out = build_flow_graph().compile().invoke(
        {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]},
        config={"configurable": {"chat_model": model}},
    )

    body = _body(out["answer"])
    assert '"tool"' not in body
    assert "fetch_execution_context" not in body
    assert "```" not in body, f"围栏残留：{body[:60]!r}"
    assert "### 当前这一步的执行内容" in body
    assert "【决策痕迹】" in out["answer"]
