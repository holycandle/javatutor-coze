"""Task 4: step_facts 工具测试."""

from tools.step_facts import step_facts


STATE = {
    "source_code": "public class A {\n    void f() {\n        int x = 1;\n    }\n}",
    "steps": [
        {"step": 0, "line": 3, "variables": {"x": 1}, "heap": {}, "stackFrames": [], "output": None},
        {"step": 1, "line": 3, "variables": {"x": 2}, "heap": {"h1": {"type": "Object"}}, "stackFrames": [{"method": "f"}], "output": "out"},
    ],
    "current_step_index": 0,
}


def test_step_facts_returns_evidence_and_diff():
    out = step_facts(STATE, step_index=1)
    assert out["error"] == ""
    assert out["evidence"]["variables"]["x"] == 2
    assert out["evidence"]["heap"]["h1"]["type"] == "Object"
    assert out["evidence"]["stackFrames"][0]["method"] == "f"
    assert out["evidence"]["output"] == "out"
    assert out["evidence"]["line_text"] == "int x = 1;"
    assert out["diff"] == [{"key": "x", "before": 1, "after": 2}]


def test_step_facts_out_of_range():
    out = step_facts(STATE, step_index=99)
    assert out["error"]
