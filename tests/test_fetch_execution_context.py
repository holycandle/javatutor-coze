from tools.fetch_execution_context import fetch_execution_context


def test_fetch_prefers_state_and_stores_fetched_context():
    state = {
        "run_id": "r1",
        "source_code": "public class A {}\npublic class B {}",
        "steps": [{"step_index": 0, "variables": {"x": 1}}],
        "current_step_index": 0,
        "current_line": 1,
    }
    out = fetch_execution_context(state)
    assert out["source_code"] == state["source_code"]
    assert out["steps_count"] == 1
    assert out["fetched_context"]["source_code"] == state["source_code"]
    assert out["fetched_context"]["run_id"] == "r1"
    assert out["stored"] is True


def test_fetch_no_source_or_steps_returns_error():
    out = fetch_execution_context({"run_id": "", "source_code": "", "steps": []})
    assert out.get("fetch_context_failed") is True
    assert out.get("error")


def test_fetch_schema_has_file_and_line_params():
    from tools.fetch_execution_context import TOOL_SCHEMA

    props = TOOL_SCHEMA["parameters"]["properties"]
    for k in ("run_id", "file", "start_line", "end_line"):
        assert k in props


def test_fetch_slices_code_by_line_range():
    state = {"run_id": "r1", "source_code": "line1\nline2\nline3\nline4", "steps": []}
    out = fetch_execution_context(state, start_line=2, end_line=3)
    assert out["code"] == "line2\nline3"


def test_fetch_does_not_import_httpx_or_os():
    import importlib
    import sys

    sys.modules.pop("tools.fetch_execution_context", None)
    mod = importlib.import_module("tools.fetch_execution_context")
    assert not hasattr(mod, "httpx")
    assert not hasattr(mod, "os")


def test_fetch_sets_compact_run_context_memory_without_code_or_steps():
    state = {
        "run_id": "r1",
        "source_code": "code",
        "steps": [{}],
        "current_step_index": 0,
        "current_line": 1,
    }
    out = fetch_execution_context(state)
    rcm = out["run_context_memory"]
    assert "source_code" not in rcm and "steps" not in rcm
    assert rcm["steps_count"] == 1
