"""verify 节点测试：确定性 grounding 核对接进运行时，且只记录不判罚。"""

from graphs.javatutor.nodes import _strip_structured_blocks, build_final, verify_node


STEPS = [
    {"step": 0, "line": 3, "variables": {"x": 1}, "heap": {"h2": {"id": 2}}},
    {"step": 1, "line": 4, "variables": {"x": 2}, "heap": {"h2": {"id": 2}}},
]


def test_hallucinated_step_is_recorded_not_fatal():
    out = verify_node({"steps": STEPS, "answer": "在第 99 步，变量 x 变成了 2"})
    v = out["verification"]
    assert v["applicable"] is True
    assert v["violations"] >= 1
    assert v["hallucinated"]
    assert v["grounding_ok"] is False


def test_no_steps_is_not_punished():
    """无 steps（纯概念问题）时明确不判罚——与离线口径一致。"""
    out = verify_node({"steps": [], "answer": "第 99 步纯属编造"})
    v = out["verification"]
    assert v["applicable"] is False
    assert v["grounding_ok"] is True
    assert v["violations"] == 0


def test_grounded_answer_passes():
    out = verify_node({"steps": STEPS, "answer": "第 2 步（line 4）里 x 变成了 2"})
    v = out["verification"]
    assert v["applicable"] is True
    assert v["grounding_ok"] is True


def test_edit_block_is_stripped_before_checking():
    """【编辑建议】的 JSON 里有代码，不剥会给堆对象核对造假阳性。"""
    answer = '正文说明。\n\n【编辑建议】\n{"kind":"replace","code":"Object h1 = null; int x = 3;"}'
    out = verify_node({"steps": STEPS, "answer": answer})
    assert out["verification"]["violations"] == 0


def test_edit_block_heap_ref_would_be_a_false_positive_without_stripping():
    """反证：不剥就是误报（钉住剥离这一步确实在起作用）。"""
    from graphs.javatutor.verification import verify_grounding

    payload = {"payload": {"steps": STEPS, "source_code": ""}}
    raw = '正文。\n\n【编辑建议】\n{"code":"Object h1 = null;"}'
    assert verify_grounding(payload, raw)["violations"] >= 1
    assert verify_grounding(payload, _strip_structured_blocks(raw))["violations"] == 0


def test_revised_answer_wins_over_answer():
    """核对的是**最终交付文本**：有修订就看修订。"""
    out = verify_node({"steps": STEPS, "answer": "第 99 步胡编", "revised_answer": "第 1 步没问题"})
    assert out["verification"]["grounding_ok"] is True


def test_verification_lands_in_decision_trace_without_touching_existing_keys():
    state = {
        "answer": "第 1 步没问题",
        "revised_answer": "第 1 步没问题",
        "steps": STEPS,
        "verification": verify_node({"steps": STEPS, "answer": "第 1 步没问题"})["verification"],
    }
    trace = build_final(state)["decision_trace"]

    assert "verification" in trace
    assert trace["verification"]["applicable"] is True
    # 既有键一个不动（评测 M1.1 与前端依赖它们的**存在性**）
    for key in ("intent", "critic_passed", "tool_calls", "token_usage", "latency_ms", "run_id"):
        assert key in trace


def test_decision_trace_verification_defaults_to_empty_dict():
    trace = build_final({"answer": "无核实数据"})["decision_trace"]
    assert trace["verification"] == {}


def test_strip_structured_blocks_cuts_at_earliest_marker():
    text = '正文。\n\n【编辑建议】\n{"a":1}\n\n【视角导航】\n{"views":[]}\n\n【决策痕迹】\n{"b":2}'
    assert _strip_structured_blocks(text) == "正文。"


def test_strip_structured_blocks_without_blocks_is_identity():
    assert _strip_structured_blocks("就是正文") == "就是正文"
    assert _strip_structured_blocks("") == ""
