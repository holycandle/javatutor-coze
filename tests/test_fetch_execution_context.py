from tools.fetch_execution_context import fetch_execution_context


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _success_payload():
    return {
        "run_id": "run-1",
        "source_code": "public class A { int x = 1; }",
        "steps": [
            {"step": 0, "line": 1, "variables": {"x": 1}},
            {"step": 1, "line": 1, "variables": {"x": 2}},
        ],
        "current_step_index": 1,
        "current_line": 1,
        "compile_error": "",
        "algorithm_tags": ["遍历"],
        "expires_at": 1784736000,
    }


def test_fetch_success_populates_state(monkeypatch):
    captured = {}

    def fake_get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse(_success_payload())

    monkeypatch.setattr("tools.fetch_execution_context.httpx.get", fake_get)
    monkeypatch.setenv("JAVATUTOR_EXECUTION_CONTEXT_URL", "http://localhost:8080/api/agent/execution-context")
    monkeypatch.setenv("JAVATUTOR_AGENT_TOKEN", "secret-token")

    out = fetch_execution_context({}, "run-1")

    assert captured["url"] == "http://localhost:8080/api/agent/execution-context/run-1"
    assert captured["headers"]["X-Agent-Token"] == "secret-token"
    assert out["source_code"] == "public class A { int x = 1; }"
    assert out["current_step_index"] == 1
    assert out["current_variables"] == {"x": 2}
    assert out["fetch_context_failed"] is False
    assert out["run_context_memory"]["run_id"] == "run-1"
    assert "source_code" not in out["run_context_memory"]
    assert "steps" not in out["run_context_memory"]


def test_fetch_non_200_returns_failure(monkeypatch):
    class ErrorResponse:
        status_code = 404

        def json(self):
            return {}

    monkeypatch.setattr("tools.fetch_execution_context.httpx.get", lambda url, headers, timeout: ErrorResponse())
    monkeypatch.setenv("JAVATUTOR_EXECUTION_CONTEXT_URL", "http://localhost:8080/api/agent/execution-context")
    monkeypatch.setenv("JAVATUTOR_AGENT_TOKEN", "secret-token")

    out = fetch_execution_context({}, "run-1")
    assert out["fetch_context_failed"] is True
    assert "404" in out["fetch_context_error"]
    assert out["fallback_reason"].startswith("fetch_execution_context failed:")


def test_fetch_missing_required_fields_returns_failure(monkeypatch):
    monkeypatch.setattr(
        "tools.fetch_execution_context.httpx.get",
        lambda url, headers, timeout: FakeResponse({"run_id": "run-1"}),
    )
    monkeypatch.setenv("JAVATUTOR_EXECUTION_CONTEXT_URL", "http://localhost:8080/api/agent/execution-context")
    monkeypatch.setenv("JAVATUTOR_AGENT_TOKEN", "secret-token")

    out = fetch_execution_context({}, "run-1")
    assert out["fetch_context_failed"] is True


def test_fetch_missing_env_config_returns_failure(monkeypatch):
    """URL 或 token 未配置时返回失败，而非抛异常."""
    monkeypatch.delenv("JAVATUTOR_EXECUTION_CONTEXT_URL", raising=False)
    monkeypatch.delenv("JAVATUTOR_AGENT_TOKEN", raising=False)
    out = fetch_execution_context({}, "run-1")
    assert out["fetch_context_failed"] is True
