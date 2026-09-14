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


def test_first_occurrence_is_not_a_step_reference():
    """「第一次出现」不是步骤引用——优化第二步的提问形状曾被误判成 data_query。

    实测见 docs/plan/2026-09-14-fix-concept-intent-and-optimization-loop-plan.md §0.2。
    """
    q = "只做「以性能为先」方向的优化，具体要求：用哈希表记录每个元素第一次出现的下标。"
    assert conservative_intent(q) != "data_query"


def test_step_shapes_still_hit_data_query():
    """改形状匹配不能把合法的步骤/行号引用一起丢掉（含中文数字）。"""
    assert conservative_intent("第 2 步 arr[1] 变了") == "data_query"
    assert conservative_intent("第二步 arr[1] 变了") == "data_query"
    assert conservative_intent("第2行这里走了几次") == "data_query"
