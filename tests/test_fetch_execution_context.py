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
    """无 entry_file / 无当前步文件 / 项目有**多个**文件 → 兜底到 source_code。

    （单文件项目走 ``only_file``，见 ``test_fetch_uses_only_file_when_single``——
    2026-09-14 D3 新增的兜底顺序把「唯一文件」排在 ``source_code`` 之前。）
    """
    state = {
        "source_code": "class Main {}",
        "files": {"A.java": "...", "B.java": "..."},
        "steps": [],
    }
    r = fetch_execution_context(state)
    assert r["code"] == "class Main {}"
    assert r["file"] == ""
    assert r["file_source"] == "source_code"


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


def test_single_file_file_param_falls_back_to_source_code():
    """单文件（files 为空）时，即便 agent 传 file=Main.java 也应回退 source_code，而非报错。"""
    state = {
        "source_code": "class MaxSubarray {\n  public static void main(String[] a) {}\n}",
        "steps": [],
        "files": {},
    }
    r = fetch_execution_context(state, file="Main.java")
    assert r["code"] == state["source_code"]
    assert not r.get("error")  # 成功回退，未报文件不存在
    assert r["file"] == "Main.java"
    assert r["file_source"] == "source_code"
    assert r["fetch_context_failed"] is False


def test_no_http_env_dependency_in_tool_module():
    import tools.fetch_execution_context as mod

    assert not hasattr(mod, "httpx")
    assert not hasattr(mod, "os")  # 维持 Phase 1「无环境依赖」约定（basename 用 rsplit 实现）


# ── 2026-09-14 联调修复 Task 1：自描述 + 禁止「成功但空」 ────────────────────────


def test_fetch_multi_file_without_entry_does_not_silently_return_empty():
    """多文件 + entry_file 空 + source_code 空：**必须**结构化失败，不得「成功但空」。

    这是报告症状（「决策痕迹显示调用了 fetch，但多轮都说缺少 Main.java 的源码」）里
    最致命的一环：过去这条路径 ``error is None`` / ``fetch_context_failed is False`` /
    ``code == ""``，痕里是绿色调用、模型却什么也没拿到。
    """
    state = {
        "files": {"Main.java": "class Main {}", "Util.java": "class Util {}"},
        "entry_file": "",
        "source_code": "",
        "steps": [],
    }
    r = fetch_execution_context(state)
    assert r["fetch_context_failed"] is True
    assert r["error"]
    # 错误必须点名候选文件，模型才有可执行的下一步
    assert "Main.java" in r["error"] and "Util.java" in r["error"]


def test_fetch_empty_only_file_is_structured_failure():
    """唯一文件解析到了、但内容为空：同样算失败（``code_chars == 0`` 不得配 ``False``）。"""
    state = {"files": {"Main.java": ""}, "entry_file": "", "source_code": "", "steps": []}
    r = fetch_execution_context(state)
    assert r["fetch_context_failed"] is True
    assert "Main.java" in r["error"]


def test_fetch_out_of_range_slice_is_structured_failure():
    """行范围切出空串也算「成功但空」：一并结构化失败，而不是回一份空 code。"""
    state = {"source_code": "line1\nline2", "steps": []}
    r = fetch_execution_context(state, start_line=99, end_line=120)
    assert r["fetch_context_failed"] is True
    assert r["error"]


def test_fetch_reports_file_and_source():
    """单文件 payload：file 为空串（无项目文件），来源如实标注为 source_code。"""
    state = {"source_code": "class Main {}", "files": {}, "steps": []}
    r = fetch_execution_context(state)
    assert r["file"] == ""
    assert r["file_source"] == "source_code"
    assert r["code_chars"] == len(r["code"]) > 0


def test_fetch_reports_entry_file_source():
    state = {
        "source_code": "class Active {}",
        "entry_file": "Main.java",
        "files": {"Main.java": "class Main {}", "Util.java": "class Util {}"},
        "steps": [],
    }
    r = fetch_execution_context(state)
    assert r["file"] == "Main.java"
    assert r["file_source"] == "entry_file"
    assert r["code_chars"] == len("class Main {}")


def test_successful_fetch_always_has_nonempty_code_chars():
    """验收判据（plan §3-2）：``fetch_context_failed is False`` ⇒ ``code_chars > 0``。"""
    states = [
        {"source_code": "class A {}", "steps": []},
        {"source_code": "", "files": {"A.java": "class A {}"}, "steps": []},
        {"source_code": "", "files": {"A.java": "class A {}", "B.java": "class B {}"},
         "entry_file": "B.java", "steps": []},
        {"source_code": "", "files": {"A.java": "class A {}", "B.java": "class B {}"},
         "current_step_file": "B.java", "steps": []},
    ]
    for state in states:
        r = fetch_execution_context(state)
        assert r["fetch_context_failed"] is False, r
        assert r["code_chars"] > 0, r


# ── Task 2：入口解析顺序（D3） ────────────────────────────────────────────────


def test_fetch_falls_back_to_current_step_file():
    state = {
        "files": {"Main.java": "class Main {}", "Util.java": "class Util {}"},
        "entry_file": "",
        "source_code": "class Active {}",
        "steps": [{"step": 0, "file": "Util.java", "variables": {}}],
        "current_step_index": 0,
    }
    r = fetch_execution_context(state)
    assert r["code"] == "class Util {}"
    assert r["file"] == "Util.java"
    assert r["file_source"] == "current_step_file"


def test_fetch_uses_only_file_when_single():
    state = {
        "files": {"Main.java": "class Main {}"},
        "entry_file": "",
        "source_code": "class Empty {}",
        "steps": [],
    }
    r = fetch_execution_context(state)
    assert r["code"] == "class Main {}"
    assert r["file_source"] == "only_file"


def test_fetch_explicit_file_wins():
    state = {
        "files": {"Main.java": "class Main {}", "Util.java": "class Util {}"},
        "entry_file": "Main.java",
        "source_code": "",
        "steps": [],
    }
    r = fetch_execution_context(state, file="Util.java")
    assert r["code"] == "class Util {}"
    assert r["file"] == "Util.java"
    assert r["file_source"] == "explicit"


def test_entry_file_beats_current_step_file():
    """keep 既有契约：默认读主入口，当前步所在文件只是 entry_file 缺失时的兜底。"""
    state = {
        "files": {"Main.java": "class Main {}", "Util.java": "class Util {}"},
        "entry_file": "Main.java",
        "source_code": "",
        "steps": [{"step": 0, "file": "Util.java", "variables": {}}],
        "current_step_index": 0,
    }
    r = fetch_execution_context(state)
    assert r["file"] == "Main.java"
    assert r["file_source"] == "entry_file"


def test_entry_file_matches_by_basename():
    state = {"files": {"src/Main.java": "class Main {}"}, "entry_file": "Main.java", "steps": []}
    r = fetch_execution_context(state)
    assert r["file"] == "src/Main.java"
    assert r["file_source"] == "entry_file"
