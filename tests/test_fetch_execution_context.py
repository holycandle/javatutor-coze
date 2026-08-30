from tools.fetch_execution_context import fetch_execution_context, normalize_files


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


def test_file_param_reads_from_state_files():
    state = {
        "source_code": "class Main {}",
        "files": {"A.java": "class A {}", "B.java": "class B {}"},
        "steps": [],
        "run_id": "r1",
    }
    r = fetch_execution_context(state, file="B.java")
    assert r["code"] == "class B {}"
    assert r["file"] == "B.java"
    assert "B.java" in r["fetched_context"]["project_files"]
    assert r["run_context_memory"]["files_count"] == 2


def test_file_param_case_insensitive_basename():
    state = {"source_code": "", "files": {"src/App.java": "class App {}"}, "steps": []}
    r = fetch_execution_context(state, file="app.java")  # 忽略大小写/basename
    assert r["code"] == "class App {}"


def test_file_param_not_found_returns_error():
    state = {"source_code": "", "files": {"A.java": "..."}, "steps": []}
    r = fetch_execution_context(state, file="Nope.java")
    assert r.get("error") and r.get("fetch_context_failed") is True
    assert "Nope.java" in r["error"]


def test_default_reads_main_entry():
    state = {"source_code": "class Main {}", "files": {"A.java": "..."}, "steps": []}
    r = fetch_execution_context(state)
    assert r["code"] == "class Main {}"
    assert r["file"] == ""


def test_default_prefers_entry_file():
    state = {
        "source_code": "class Active {}",
        "entry_file": "App.java",
        "files": {"App.java": "class App {}", "B.java": "..."},
        "steps": [],
    }
    r = fetch_execution_context(state)
    assert r["code"] == "class App {}"
    assert r["file"] == "App.java"  # 默认读 entry_file，而非激活文件


def test_current_step_file_propagated():
    state = {
        "source_code": "class Main {}",
        "steps": [{"step": 0, "file": "Other.java", "variables": {}}],
        "current_step_index": 0,
        "files": {"Other.java": "class Other {}", "Main.java": "..."},
    }
    r = fetch_execution_context(state)
    assert r["current_step_file"] == "Other.java"
    assert r["fetched_context"]["current_step_file"] == "Other.java"


def test_normalize_files_variants():
    assert normalize_files({"A.java": "c"}) == {"A.java": "c"}
    assert normalize_files([{"name": "B.java", "code": "c"}]) == {"B.java": "c"}
    assert normalize_files([{"path": "C.java", "code": "c"}]) == {"C.java": "c"}
    assert normalize_files(None) == {}
    assert normalize_files([{"name": "D.java"}]) == {}


def test_no_http_env_dependency_in_tool_module():
    import tools.fetch_execution_context as mod

    assert not hasattr(mod, "httpx")
    assert not hasattr(mod, "os")  # 维持 Phase 1「无环境依赖」约定（basename 用 rsplit 实现）
