from graphs.javatutor.state import JavaTutorState


def test_state_has_fetched_context_field():
    s: JavaTutorState = {"fetched_context": {"source_code": "x"}}
    assert s["fetched_context"]["source_code"] == "x"
