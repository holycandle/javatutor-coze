import json

from graphs.javatutor.compaction import compact_steps


def _steps(n):
    return [{"step": i, "variables": {"arr": [i, i + 1]}} for i in range(n)]


def test_small_steps_unchanged():
    out = compact_steps(_steps(5), current_step_index=2)
    assert out["compaction_mode"] == "none"
    assert json.loads(out["steps_json"]) == _steps(5)


def test_large_steps_windowed():
    out = compact_steps(_steps(250), current_step_index=100, threshold=200, window=30)
    assert out["compaction_mode"] == "windowed"
    assert "共 250 步" in out["context_summary"]
    assert len(json.loads(out["steps_json"])) == 30


def test_truncated_on_error():
    out = compact_steps([{"step": i} for i in range(250)], current_step_index=None, threshold=200, window=30)
    assert out["compaction_mode"] in ("windowed", "truncated")
