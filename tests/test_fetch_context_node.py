from graphs.javatutor.fetch_context import fetch_execution_context_node


def test_failed_fetch_with_legacy_steps_keeps_legacy_context(monkeypatch):
    def fake_fetch(state, run_id=None):
        return {
            "fetch_context_failed": True,
            "fetch_context_error": "HTTP 404",
            "fallback_reason": "fetch_execution_context failed: HTTP 404",
        }

    monkeypatch.setattr("graphs.javatutor.fetch_context.fetch_execution_context", fake_fetch)
    state = {
        "run_id": "run-1",
        "source_code": "public class A {}",
        "steps": [{"step": 0, "line": 1, "variables": {}}],
        "has_steps": True,
    }
    out = fetch_execution_context_node(state)
    assert out["fetch_context_failed"] is True
    assert out["fallback_reason"] == ""


def test_failed_fetch_without_legacy_steps_sets_fallback(monkeypatch):
    def fake_fetch(state, run_id=None):
        return {
            "fetch_context_failed": True,
            "fetch_context_error": "HTTP 404",
            "fallback_reason": "fetch_execution_context failed: HTTP 404",
        }

    monkeypatch.setattr("graphs.javatutor.fetch_context.fetch_execution_context", fake_fetch)
    out = fetch_execution_context_node({"run_id": "run-1", "has_steps": False})
    assert out["fallback_reason"].startswith("fetch_execution_context failed:")
