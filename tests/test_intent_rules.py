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


def test_step2_marker_is_not_data_query():
    """第二步提问的黑名单文案必含「变量」（「命名中间变量」/「改进变量命名」），
    而 `DATA_QUERY_KEYWORDS` 含「变量」⇒ 不到标记前置就必然误判。

    判成 data_query 的代价不只是痕迹记错：`build_context_node` 会据此注入 data_query 的
    角色与输出契约（「在哪一步、哪一行、哪个变量，长度 3-6 句」），
    与「交付整份 replace 代码」直接竞争（review 2026-09-14 §3.2）。
    """
    from graphs.javatutor.prompting.optimization import STEP2_MARKER

    q = (
        f"{STEP2_MARKER}只做「以性能为先」方向的优化，具体要求：用哈希表把嵌套循环降为 O(n)。"
        "不要顺带做其他方向的改动（例如：「以可读性为先」：拆分长方法并命名中间变量）。"
        "请给出优化后的完整代码。"
    )
    assert conservative_intent(q) == "other"
    # 线上真实产出的另一条黑名单文案（同属「变量」误命中）
    assert conservative_intent(f"{STEP2_MARKER}只做「以规范为先」方向的优化。不要添加注释并改进变量命名。") == "other"


def test_step2_marker_does_not_override_hard_debug_signals():
    """硬信号优先级不变：带标记但报错/含「报错」字样的提问仍是 debug。"""
    from graphs.javatutor.prompting.optimization import STEP2_MARKER

    assert conservative_intent(f"{STEP2_MARKER}按这个方向改。", "error: ';' expected") == "debug"
    assert conservative_intent(f"{STEP2_MARKER}按这个方向改，但代码报错了。") == "debug"


def test_step2_marker_only_counts_at_the_start():
    """标记在句中（用户只是提到这个标记）不改变分类。"""
    from graphs.javatutor.prompting.optimization import STEP2_MARKER

    assert conservative_intent(f"为什么{STEP2_MARKER}这个标记总是不生效？") == "data_query"
