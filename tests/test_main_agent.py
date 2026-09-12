"""纯渲染器测试：``_format_step_facts`` 的文本契约。

**这里只放纯函数用例**。原先的循环行为用例（12 个）已随「循环契约化进图」
迁移到 ``tests/test_harness_loop.py``——``main_agent_node`` 现在只是 ``propose``
的薄包装，不再自己循环，旧的直接调用无法再覆盖循环语义。
"""

from graphs.javatutor.main_agent import _format_step_facts


def test_format_step_facts_is_clean_labeled_text():
    """step_facts 结果应渲染为可读文本并用 1-based 步骤标签，避免模型解析原始 JSON。"""
    result = {
        "error": "",
        "evidence": {
            "variables": {"arr": [3, 5, 8], "n": 3, "i": 0, "j": 0, "temp": 5},
            "heap": {},
            "stackFrames": [{"method": "main"}],
            "output": None,
            "line": 9,
            "line_text": "arr[j] = arr[j+1];",
        },
        "diff": [{"key": "arr", "before": [5, 3, 8], "after": [3, 5, 8]}],
    }
    text = _format_step_facts({"step_index": 6}, result)
    # 关键：带 0-based 提示的 1-based 标签，与用户/回答的「第 7 步」对齐
    assert "第 7 步（step_index=6）" in text
    assert "变量" in text
    assert "[3, 5, 8]" in text
    assert "arr[j] = arr[j+1];" in text
    # 明确给出 diff，模型可直接读「这一步做了什么」，不必再反复试探
    assert "arr" in text and "[5, 3, 8] → [3, 5, 8]" in text
