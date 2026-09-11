"""治理门闩测试：逐条钉住 P1–P5（见 spec §4.5 策略表）。"""

from graphs.javatutor.harness.contracts import Action
from graphs.javatutor.harness.guard import decide


def act(tool, args=None):
    return Action(tool=tool, args=args or {}, raw="")


FILES = {"Main.java": "class Main {}", "Helper.java": "class Helper {}"}
ONE_FILE = {"Main.java": "class Main {}"}


class TestP1Whitelist:
    def test_unknown_tool_denied_with_available_list(self):
        d = decide(act("no_such_tool"), {})
        assert d.verdict == "deny"
        assert d.policy == "P1"
        assert "step_facts" in d.reason
        assert "fetch_execution_context" in d.reason


class TestP2Args:
    def test_unknown_key_denied(self):
        d = decide(act("step_facts", {"bogus_key": 1}), {})
        assert d.verdict == "deny"
        assert d.policy == "P2"
        assert "bogus_key" in d.reason

    def test_wrong_type_denied(self):
        d = decide(act("step_facts", {"step_index": "1"}), {})
        assert d.verdict == "deny"
        assert d.policy == "P2"

    def test_valid_args_pass(self):
        d = decide(act("step_facts", {"step_index": 1}), {})
        assert d.verdict == "allow"


class TestP3Budget:
    def test_budget_exhausted_denies_otherwise_valid_action(self):
        d = decide(act("step_facts", {"step_index": 1}), {"tool_rounds": 3})
        assert d.verdict == "deny"
        assert d.policy == "P3"

    def test_budget_is_checked_before_whitelist(self):
        """预算兜底在 P1 之前——先给出「别再调工具了」这个更有用的结论。"""
        d = decide(act("no_such_tool"), {"tool_rounds": 3})
        assert d.policy == "P3"


class TestP4FileAmbiguity:
    def test_multi_file_miss_needs_decision_with_options(self):
        d = decide(act("fetch_execution_context", {"file": "Mian.java"}), {"files": FILES})
        assert d.verdict == "needs_decision"
        assert d.policy == "P4"
        assert "Main.java" in d.reason
        assert "Helper.java" in d.reason
        assert d.options == ["Helper.java", "Main.java"]

    def test_single_file_never_ambiguous(self):
        """单文件下错文件名不算歧义：工具会回退到 source_code（既有语义）。"""
        d = decide(act("fetch_execution_context", {"file": "Mian.java"}), {"files": ONE_FILE})
        assert d.verdict == "allow"

    def test_case_insensitive_hit_is_allowed(self):
        d = decide(act("fetch_execution_context", {"file": "main.java"}), {"files": ONE_FILE})
        assert d.verdict == "allow"

    def test_basename_hit_is_allowed(self):
        d = decide(act("fetch_execution_context", {"file": "src/Main.java"}), {"files": ONE_FILE})
        assert d.verdict == "allow"

    def test_missing_file_arg_is_not_checked(self):
        d = decide(act("fetch_execution_context", {}), {"files": FILES})
        assert d.verdict == "allow"


class TestP5RepeatStep:
    def test_repeat_step_is_allowed_but_marked(self):
        """刻意保持 allow：改成 deny 会动 2026-09-08 抢回评测分数的基线。"""
        d = decide(act("step_facts", {"step_index": 1}), {"served_step_indices": [1]})
        assert d.verdict == "allow"
        assert d.policy == "P5"
        assert "不要重复查询同一步骤" in d.reason

    def test_first_time_step_is_plain_allow(self):
        d = decide(act("step_facts", {"step_index": 2}), {"served_step_indices": [1]})
        assert d.verdict == "allow"
        assert d.policy == "P0"


class TestPlainAllow:
    def test_normal_fetch_is_p0(self):
        d = decide(act("fetch_execution_context", {"file": "Main.java"}), {"files": FILES})
        assert d.verdict == "allow"
        assert d.policy == "P0"
        assert d.options == []

    def test_empty_state_does_not_raise(self):
        d = decide(act("step_facts", {}), {})
        assert d.verdict == "allow"
