"""确定性 grounding 核对器（反幻觉结构核对）测试。"""

from eval.runner.grounding import compute_grounding_verify, verify_grounding


def _sample_with_steps():
    return {
        "id": "q01",
        "payload": {
            "source_code": "public class A {\n    void f() {\n        int[] arr = {5,3,1};\n        arr[1] = 3;\n    }\n}",
            "steps": [
                {"step": 1, "line": 3, "variables": {"arr": [5, 3, 1]}},
                {"step": 2, "line": 4, "variables": {"arr": [3, 5, 1]}},
            ],
            "current_step_index": 1,
        },
    }


def test_verify_grounding_no_steps_not_applicable():
    out = verify_grounding({"payload": {"steps": [], "source_code": "int x=1;"}}, "第 2 步")
    assert out["applicable"] is False
    assert out["grounding_ok"] is True


def test_verify_grounding_valid_refs_ok():
    sample = _sample_with_steps()
    answer = "第 2 步（第 4 行）arr[1] 从 5 变成 3。"
    out = verify_grounding(sample, answer)
    assert out["applicable"] is True
    assert out["grounding_ok"] is True
    assert out["step_refs"] == [{"value": 2, "ok": True}]
    assert out["line_refs"] == [{"value": 4, "ok": True}]


def test_verify_grounding_out_of_range_step_and_line():
    sample = _sample_with_steps()
    answer = "第 9 步（第 99 行）发生数组越界。"
    out = verify_grounding(sample, answer)
    assert out["grounding_ok"] is False
    assert out["violations"] == 2
    assert "步骤 9" in out["hallucinated"][0]
    assert "行号 99" in out["hallucinated"][1]


def test_verify_grounding_line_checked_against_step_lines():
    """行号合法性对照 steps 的 line 字段，而非源码物理行数（源码可能单行压缩）。"""
    sample = {
        "payload": {
            "source_code": "public class A { void f() { int[] arr = {5,3,1}; arr[1] = 3; } }",
            "steps": [
                {"step": 1, "line": 3, "variables": {"arr": [5, 3, 1]}},
                {"step": 2, "line": 4, "variables": {"arr": [3, 5, 1]}},
            ],
        }
    }
    # 源码物理只有 1 行，但 steps 的 line 字段含 3 和 4；引用第 4 行应合法
    answer = "第 2 步（第 4 行）arr[1] 从 5 变成 3。"
    out = verify_grounding(sample, answer)
    assert out["grounding_ok"] is True
    assert out["line_refs"] == [{"value": 4, "ok": True}]


def test_verify_grounding_line_not_in_step_lines_flagged():
    sample = _sample_with_steps()
    # steps 的 line 集合为 {3, 4}；引用第 99 行应违规
    out = verify_grounding(sample, "第 1 步（第 99 行）出错。")
    assert out["grounding_ok"] is False
    assert any("行号 99" in h for h in out["hallucinated"])


def test_verify_grounding_heap_id():
    sample = {
        "payload": {
            "source_code": "Object o = new Object();",
            "steps": [{"step": 1, "line": 1, "variables": {}, "heap": {"h1": {"type": "Object"}}}],
        }
    }
    # h1 存在，h2 不存在
    out = verify_grounding(sample, "堆对象 h1 在第 1 步创建，h2 是悬空引用")
    assert out["grounding_ok"] is False
    assert out["heap_refs"] == [
        {"value": "h1", "ok": True},
        {"value": "h2", "ok": False},
    ]
    assert "堆对象 h2" in out["hallucinated"][0]


def test_verify_grounding_heap_id_skipped_when_no_heap():
    sample = _sample_with_steps()
    # 无 heap 数据时 h1 不作为堆引用核对（避免把源码变量误判）
    out = verify_grounding(sample, "变量 h1 是 int")
    assert out["heap_refs"] == []
    assert out["grounding_ok"] is True


def test_compute_grounding_verify_aggregates():
    sample = _sample_with_steps()
    outputs = [
        {"id": "q01", "answer": "第 2 步（第 4 行）"},
        {"id": "q02", "answer": "第 9 步（第 99 行）"},
    ]
    samples = [
        sample,
        {"id": "q02", "payload": {"source_code": "int x=1;", "steps": [{"step": 1, "line": 1, "variables": {}}]}},
    ]
    m = compute_grounding_verify(outputs, samples)
    assert m["grounding_verify_applicable"] == 2
    # q02：步骤 9 越界 + 行号 99 越界 = 2 违规
    assert m["grounding_verify_violations"] == 2
    # 2 个 applicable 样本中 q01 干净、q02 违规 → 1/2
    assert m["grounding_verify_accuracy"] == 0.5


def test_compute_grounding_verify_skips_no_steps():
    outputs = [{"id": "q13", "answer": "HashMap 的 get 是 O(1)"}]
    samples = [{"id": "q13", "payload": {"steps": []}}]
    m = compute_grounding_verify(outputs, samples)
    assert m["grounding_verify_applicable"] == 0
    assert m["grounding_verify_accuracy"] == 0.0
