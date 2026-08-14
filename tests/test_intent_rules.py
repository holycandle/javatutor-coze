from graphs.javatutor.intent_rules import conservative_intent, fact_matches


def test_compile_error_short_circuits_debug():
    assert conservative_intent("为什么 arr 变了？", "error: ';' expected") == "debug"


def test_data_query_keywords():
    assert conservative_intent("为什么第 2 步 arr[1] 变了？") == "data_query"


def test_concept_keywords():
    assert conservative_intent("冒泡排序原理是什么？") == "concept"


def test_debug_keywords():
    assert conservative_intent("这个报错怎么改？") == "debug"


def test_fallback_other():
    assert conservative_intent("你好") == "other"


def test_fact_matches_step_line_var():
    answer = "第 2 步（第 4 行）arr[1] 变成了 5"
    assert fact_matches("step=2", answer)
    assert fact_matches("line=4", answer)
    assert fact_matches("arr[1]=5", answer)
