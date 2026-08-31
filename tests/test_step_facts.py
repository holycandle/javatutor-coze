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
    assert out["steps_count"] == 2  # 越界恒带 steps_count，供 agent 掌握可用范围
    assert "可用范围请以 steps_count 为准" in out["error"]  # 远超时不给无效换算
    assert out["evidence"] == {}


def test_step_facts_out_of_range_off_by_one_hint():
    """越界恰为 1-based 展示序时给出换算建议（第 N 步 = step_index N-1）。"""
    out = step_facts(STATE, step_index=2)  # count=2，用户指第 2 步，step_index=1 合法
    assert out["error"]
    assert out["steps_count"] == 2
    assert "step_index=1" in out["error"]


def test_step_facts_uses_current_step_file():
    """多文件下按当前执行步所在文件取行号码，而非激活文件 source_code。"""
    state = {
        "source_code": "class Main {}",
        "steps": [{"step": 0, "file": "Other.java", "line": 1, "variables": {"x": 1}}],
        "current_step_index": 0,
        "current_step_file": "Other.java",
        "files": {"Other.java": "package other;\nclass Other {"},
    }
    out = step_facts(state, step_index=0)
    assert out["error"] == ""
    assert out["evidence"]["file"] == "Other.java"
    # 行 1 来自 Other.java 的第 1 行，而非 source_code
    assert out["evidence"]["line_text"] == "package other;"


def test_step_facts_without_files_falls_back_to_source_code():
    """无多文件/无 current_step_file 时回退 source_code（单文件行为不变）。"""
    out = step_facts(STATE, step_index=0)
    assert out["error"] == ""
    assert out["evidence"]["file"] == ""
    assert out["evidence"]["line_text"] == "int x = 1;"
