import json

from langchain_core.messages import AIMessage

from graphs.javatutor.critic import critic_node, revise_node
from graphs.javatutor.prompting.contexts import build_facts_block


class FakeModel:
    def __init__(self, content):
        self.content = content

    def invoke(self, messages):
        return AIMessage(content=self.content)


BASE = {
    "answer": "根据第 2 步，arr[1] 变成了 8",
    "current_variables": {"arr": [3, 5, 1]},
    "compile_error": "",
    "steps_json": '[{"step": 1, "variables": {"arr": [3, 5, 1]}}]',
    "user_question": "为什么 arr 变了？",
    "retrieved_chunks": [],
}

# 一段「较长且题旨明确」的原正文：用于相似度闸（G1）的用例。
_LONG_ANSWER = (
    "第 2 步（第 4 行）进入内层循环，比较 arr[0]=5 与 arr[1]=3，5 > 3 触发交换，"
    "所以 arr[1] 由 3 变成 5。这个交换在冒泡排序里是最内层的操作，"
    "它保证了每轮结束后较大的元素向右移动一位，直到整个数组有序。"
)
# 另一主题的短文：与原正文相似度极低，等同「题旨漂移」。
_OFF_TOPIC = "哈希表可以把查找降为 O(1)，建议改用 HashMap 重建索引后再比较。"


def test_critic_passes():
    out = critic_node(BASE, FakeModel('{"pass": true, "issues": []}'))
    assert out["critic_passed"] is True


# 一条**给出处**的意见：answer_span 是 BASE["answer"] 的子串，fact 是事实块（学生问题行）的子串。
_VALID_ISSUE = {"claim": "变量值 8 与数据不符", "answer_span": "arr[1] 变成了 8", "fact": "学生问题：为什么 arr 变了？"}


def test_critic_fails_with_issues():
    out = critic_node(BASE, FakeModel(json.dumps({"pass": False, "issues": [_VALID_ISSUE]}, ensure_ascii=False)))
    assert out["critic_passed"] is False
    assert "变量值" in out["critic_feedback"]


def test_critic_string_false_is_not_pass():
    """`"false"` 字符串不得被 `bool()` 误判为通过（`_as_bool` 语义保留）。

    意见必须带出处才有效（CD-3），所以这里给一条可核实的意见——否则该条会被丢弃、
    按「无有效意见 ⇒ 通过」判通过，本用例就测不到 `_as_bool` 了。
    """
    out = critic_node(
        BASE,
        FakeModel(json.dumps({"pass": "false", "issues": [_VALID_ISSUE]}, ensure_ascii=False)),
    )
    assert out["critic_passed"] is False
    assert "变量值" in out["critic_feedback"]


def test_critic_skips_on_bad_output():
    out = critic_node(BASE, FakeModel("not json"))
    assert out["critic_passed"] is True
    assert out["critic_skipped"] is True


# === CD-3 意见必须给出处（quote-or-drop）===


def test_issue_without_span_is_dropped():
    """无出处的意见机械丢弃；丢弃后为空 ⇒ 判通过（方向保守：宁可少拦）。"""
    out = critic_node(
        BASE,
        FakeModel(json.dumps({
            "pass": False,
            "issues": [{"claim": "步骤号错", "answer_span": "这句话不在回答里", "fact": "不在事实块里"}],
        }, ensure_ascii=False)),
    )
    assert out["critic_passed"] is True
    assert out["critic_feedback"] == "[]"


def test_issue_with_valid_span_fails():
    out = critic_node(
        BASE,
        FakeModel(json.dumps({"pass": False, "issues": [_VALID_ISSUE]}, ensure_ascii=False)),
    )
    assert out["critic_passed"] is False
    feedback = json.loads(out["critic_feedback"])
    assert feedback and feedback[0]["claim"] == "变量值 8 与数据不符"


def test_legacy_string_issues_are_dropped():
    """旧格式（字符串数组）没有出处可言 ⇒ 全部丢弃 ⇒ 通过。"""
    out = critic_node(BASE, FakeModel('{"pass": false, "issues": ["变量值 8 与数据不符"]}'))
    assert out["critic_passed"] is True
    assert json.loads(out["critic_feedback"]) == []


def test_partially_valid_issues_keep_only_the_verifiable_one():
    """混合输出：只有给出处的那条留下，模型的 `pass` 仍照 `_as_bool` 读。"""
    bad = {"claim": "行号错", "answer_span": "凭空捏造的一句", "fact": "学生问题：为什么 arr 变了？"}
    out = critic_node(
        BASE,
        FakeModel(json.dumps({"pass": False, "issues": [bad, _VALID_ISSUE]}, ensure_ascii=False)),
    )
    assert out["critic_passed"] is False
    feedback = json.loads(out["critic_feedback"])
    assert [i["claim"] for i in feedback] == ["变量值 8 与数据不符"]



def test_revise_returns_revised():
    out = revise_node(BASE, FakeModel("根据第 2 步，arr[1] 变成了 5"))
    assert out["revised"] is True
    assert out["revised_answer"] == "根据第 2 步，arr[1] 变成了 5"


def test_revise_preserves_edit_suggestion_block():
    state = {
        **BASE,
        "answer": (
            "问题出在循环越界。\n\n"
            "【编辑建议】\n"
            '{"edits":[{"title":"修正循环条件","old_string":"i <= arr.length",'
            '"new_string":"i < arr.length","explanation":"避免越界"}]}'
        ),
        # blocking: true ⇒ 豁免相似度闸（G1）。原正文只有一句、修订稿是另一句，相似度为 0，
        # 没有这条豁免就必然回退——本用例要验的是「编辑建议块被保住」，不是相似度。
        "critic_feedback": json.dumps(
            [{"claim": "循环条件写错", "answer_span": "问题出在循环越界", "fact": "i < arr.length", "blocking": True}],
            ensure_ascii=False,
        ),
    }
    # 修订 LLM 只回正文（“不要 JSON”），不带编辑建议块
    out = revise_node(state, FakeModel("已修正的正文"))
    assert out["revised"] is True
    assert "已修正的正文" in out["revised_answer"]
    assert "【编辑建议】" in out["revised_answer"]
    assert '"edits"' in out["revised_answer"]


def test_revise_without_edit_block_keeps_prose_only():
    # 改成与原答高相似度的文本：默认（非 blocking）路径必须过 G1，否则本用例测的就不是
    # 「无编辑建议块时只保留正文」而是「回退」了。
    out = revise_node(BASE, FakeModel("根据第 2 步，arr[1] 变成了 5"))
    assert out["revised"] is True
    assert out["revised_answer"] == "根据第 2 步，arr[1] 变成了 5"


# === CD-1 修订回滚闸 ===


def test_low_similarity_rewrite_is_reverted():
    """题旨漂移的修订稿必须回退原答（否则评审一次误判 = 一次不可撤销的全文重写）。"""
    state = {**BASE, "answer": _LONG_ANSWER, "critic_feedback": "[]"}
    out = revise_node(state, FakeModel(_OFF_TOPIC))
    assert out["revised"] is False
    assert out["revise_outcome"] == "reverted"
    assert "similarity" in out["revise_revert_reason"]
    assert out["revised_answer"] == _LONG_ANSWER


def test_blocking_issue_exempts_similarity_gate():
    """blocking 意见是「确需大改」的显式通道，不能被相似度闸堵死。"""
    state = {
        **BASE,
        "answer": _LONG_ANSWER,
        "critic_feedback": json.dumps(
            [{"claim": "整段答非所问", "answer_span": "第 2 步", "fact": "arr", "blocking": True}],
            ensure_ascii=False,
        ),
    }
    out = revise_node(state, FakeModel(_OFF_TOPIC))
    assert out["revised"] is True
    assert out["revise_outcome"] == "accepted"


def test_revision_dropping_nav_block_is_reverted():
    """原答含【视角导航】而修订稿没有 ⇒ 回退（此前修订会静默丢掉导航卡）。"""
    answer = f"{_LONG_ANSWER}\n\n【视角导航】\n" '{"views":[{"panel":"variables","label":"内存状态"}]}'
    state = {**BASE, "answer": answer, "critic_feedback": "[]"}
    revised_missing_nav = _LONG_ANSWER.replace("由 3 变成 5", "由 3 变成 5（已核对）")
    out = revise_node(state, FakeModel(revised_missing_nav))
    assert out["revised"] is False
    assert out["revise_outcome"] == "reverted"
    assert "nav" in out["revise_revert_reason"]
    assert out["revised_answer"] == answer


def test_revise_returns_outcome_on_every_path():
    """三条既有 return 分支都要带 revise_outcome（消费方不必区分「键缺失」与「skipped」）。"""
    passed = revise_node({**BASE, "critic_passed": True}, FakeModel("不该被调用"))
    assert passed["revise_outcome"] == "skipped"
    assert passed["revised"] is False

    class Boom:
        def invoke(self, messages):
            raise RuntimeError("模型不可用")

    failed = revise_node({**BASE, "critic_passed": False, "critic_feedback": "[]"}, Boom())
    assert failed["revise_outcome"] == "skipped"
    assert failed["revise_skipped"] is True


def test_model_emitting_its_own_edit_block_is_reverted():
    """模型自己又产出一个【编辑建议】块 ⇒ 两个块冲突 ⇒ 回退（reason=edit_block）。"""
    state = {
        **BASE,
        "answer": f"{_LONG_ANSWER}\n\n【编辑建议】\n" '{"edits":[{"title":"t","old_string":"a","new_string":"b"}]}',
        "critic_feedback": json.dumps([{"claim": "c", "blocking": True}], ensure_ascii=False),
    }
    # blocking=true 已豁免 G1 ⇒ 回退只能来自 edit_block 闸。
    out = revise_node(
        state,
        FakeModel(f"{_LONG_ANSWER}\n\n【编辑建议】\n" '{"edits":[{"title":"模型自产","old_string":"x","new_string":"y"}]}'),
    )
    assert out["revised"] is False
    assert out["revise_revert_reason"] == "edit_block"


def test_structured_markers_match_nodes():
    """两处结构化块元组必须逐字一致（本模块刻意不 import nodes，靠这条守住漂移）。"""
    from graphs.javatutor import critic as critic_mod
    from graphs.javatutor import nodes as nodes_mod

    assert critic_mod._STRUCTURED_MARKERS == nodes_mod._STRUCTURED_MARKERS


# === CD-1 续：G3 引用不劣化 / G4 二次评审 ===


class _TwoPhaseModel:
    """按 system prompt 分流：修订调用回修订稿，评审调用回 `critique`。"""

    def __init__(self, revised, critique):
        self.revised = revised
        self.critique = critique
        self.calls: list[str] = []

    def invoke(self, messages):
        content = messages[0].content
        self.calls.append(content)
        return AIMessage(content=self.revised if "回答修订者" in content else self.critique)


# 3 步样本：合法步骤号 1..3、合法行号 {4}。原答引用的「第 2 步 / 第 4 行」都真实存在。
_THREE_STEPS = {
    "steps": [{"step": i, "line": 4, "variables": {}} for i in range(3)],
    "source_code": "public class A {}",
}


def test_revision_introducing_hallucination_is_reverted():
    """修订稿引用了不存在的「第 99 步」而原答没有 ⇒ 回退（修订不得让引用变差）。"""
    state = {**BASE, **_THREE_STEPS, "answer": _LONG_ANSWER, "critic_feedback": "[]"}
    # 只改一处数字，相似度闸（G1）必然通过——能拦住它的只有 G3。
    out = revise_node(state, FakeModel(_LONG_ANSWER.replace("第 2 步", "第 99 步")))
    assert out["revised"] is False
    assert out["revise_outcome"] == "reverted"
    assert out["revise_revert_reason"] == "grounding"
    assert out["revised_answer"] == _LONG_ANSWER


def test_revision_keeping_grounding_is_accepted():
    """同一样本下不改引用的修订仍被采纳——G3 只拦「变差」，不拦「修订」本身。"""
    state = {**BASE, **_THREE_STEPS, "answer": _LONG_ANSWER, "critic_feedback": "[]"}
    out = revise_node(state, FakeModel(_LONG_ANSWER.replace("由 3 变成 5", "由 3 变成 5。")))
    assert out["revised"] is True
    assert out["revise_outcome"] == "accepted"


def test_revision_failing_recheck_is_reverted():
    """G1–G3 都过，但二次评审仍判失败（带可核实出处）⇒ 回退，reason 含 recheck。"""
    state = {**BASE, "answer": "根据第 2 步，arr[1] 变成了 5", "critic_feedback": "[]"}
    revised = "根据第 2 步，arr[1] 变成了 5，这是交换的结果。"
    issue = {
        "claim": "仍然有误",
        "answer_span": "arr[1] 变成了 5",
        "fact": "学生问题：为什么 arr 变了？",
        "blocking": False,
    }
    model = _TwoPhaseModel(revised, json.dumps({"pass": False, "issues": [issue]}, ensure_ascii=False))
    out = revise_node(state, model)
    assert out["revised"] is False
    assert out["revise_revert_reason"] == "recheck"
    assert out["revise_recheck_passed"] is False
    assert len(model.calls) == 2, "应有「修订 + 二次评审」两次调用"


def test_revision_passing_recheck_is_accepted():
    state = {**BASE, "answer": "根据第 2 步，arr[1] 变成了 5", "critic_feedback": "[]"}
    revised = "根据第 2 步，arr[1] 变成了 5，这是交换的结果。"
    model = _TwoPhaseModel(revised, '{"pass": true, "issues": []}')
    out = revise_node(state, model)
    assert out["revised"] is True
    assert out["revise_recheck_passed"] is True


def _config(monkeypatch, tmp_path, payload):
    """把 critic 的配置读取指向一个临时配置文件（真跑到 `_runtime_flag` 的读盘分支）。"""
    from graphs.javatutor import critic as critic_mod

    cfg = tmp_path / "agent_llm_config.json"
    cfg.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(critic_mod, "_config_path", lambda: cfg)


def test_recheck_disabled_by_config(monkeypatch, tmp_path):
    """配置关闭 G4 ⇒ 第二次评审根本不发生（用调用计数断言）。"""
    _config(monkeypatch, tmp_path, {"config": {"critic_recheck": False}})
    state = {**BASE, "answer": "根据第 2 步，arr[1] 变成了 5", "critic_feedback": "[]"}
    revised = "根据第 2 步，arr[1] 变成了 5，这是交换的结果。"
    issue = {"claim": "仍然有误", "answer_span": "arr[1] 变成了 5", "fact": "学生问题：为什么 arr 变了？"}
    model = _TwoPhaseModel(revised, json.dumps({"pass": False, "issues": [issue]}, ensure_ascii=False))
    out = revise_node(state, model)
    assert len(model.calls) == 1, "配置关闭时不得再调一次评审"
    assert out["revised"] is True
    assert "revise_recheck_passed" not in out, "没跑过的闸不该报告结果"


def test_runtime_flag_falls_back_when_config_unreadable(monkeypatch, tmp_path):
    """配置文件缺失 / JSON 坏 / 键类型不对 ⇒ 一律回落默认值（旧部署不会因此炸）。"""
    from graphs.javatutor import critic as critic_mod

    monkeypatch.setattr(critic_mod, "_config_path", lambda: tmp_path / "nope.json")
    assert critic_mod._runtime_flag("critic_recheck", True) is True
    assert critic_mod._runtime_flag("critic_mode", "enforce") == "enforce"

    cfg = tmp_path / "bad.json"
    cfg.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(critic_mod, "_config_path", lambda: cfg)
    assert critic_mod._runtime_flag("critic_recheck", True) is True

    cfg.write_text(json.dumps({"config": {"critic_recheck": "yes"}}), encoding="utf-8")
    assert critic_mod._runtime_flag("critic_recheck", True) is True, "类型不对当缺失处理"


# === CD-5 advisory 模式 ===


def test_advisory_mode_does_not_revise(monkeypatch, tmp_path):
    """advisory：评审照跑、照记，但不触发修订（「看到问题」与「允许改写」解耦）。"""
    _config(monkeypatch, tmp_path, {"config": {"critic_mode": "advisory"}})
    critique = critic_node(
        BASE, FakeModel(json.dumps({"pass": False, "issues": [_VALID_ISSUE]}, ensure_ascii=False))
    )
    assert critique["critic_passed"] is False, "评审仍在工作，只是不进入修订"

    out = revise_node({**BASE, **critique, "critic_skipped": False}, FakeModel("完全不同的另一段回答"))
    assert out["revised"] is False
    assert out["revise_outcome"] == "skipped"
    assert out["revised_answer"] == BASE["answer"]
    assert "revise_revert_reason" not in out, "没触发过修订就谈不上回退原因"


def test_default_mode_is_enforce(monkeypatch, tmp_path):
    """配置缺失 / 读不到 ⇒ 默认 enforce（向后兼容），且确实会走到修订。"""
    from graphs.javatutor import critic as critic_mod

    monkeypatch.setattr(critic_mod, "_config_path", lambda: tmp_path / "missing.json")
    assert critic_mod._runtime_flag("critic_mode", "enforce") == "enforce"

    out = revise_node({**BASE, "critic_passed": False, "critic_feedback": "[]"}, FakeModel("根据第 2 步，arr[1] 变成了 5"))
    assert out["revise_outcome"] == "accepted"


def test_unrecognised_mode_keeps_enforce(monkeypatch, tmp_path):
    """配置写错（拼错 / 写成别的值）不得静默关掉修订闸。"""
    _config(monkeypatch, tmp_path, {"config": {"critic_mode": "Advisory"}})
    out = revise_node({**BASE, "critic_passed": False, "critic_feedback": "[]"}, FakeModel("根据第 2 步，arr[1] 变成了 5"))
    assert out["revise_outcome"] == "accepted"




# === CD-4 评审提示词：引用条件化 / 格式出局 / 正面回答 / 第二步否决权 / 意图门 ===


def _critic_prompt() -> str:
    from graphs.javatutor.prompts import SYSTEM_PROMPT_CRITIC

    return SYSTEM_PROMPT_CRITIC


def test_critic_prompt_conditions_citation_checks():
    """引用类规则**只在该类引用出现时**核对；不得因「没引用步骤数据」判失败。

    这是误杀的最大来源：概念题（「Math.pow 的功能」）本来就没有步骤可引，
    旧提示词却把「回答里应有步骤级引用」当默认前提（round-4 q17 即此形状）。
    """
    text = _critic_prompt()
    assert "仅当" in text and "出现" in text
    assert "不得因回答未引用步骤数据判失败" in text


def test_critic_prompt_has_answer_relevance_clause():
    """补唯一重要的一条：回答是否正面回答了学生问题（缺陷 D：旧评审表 6 条没有它）。"""
    text = _critic_prompt()
    assert "正面回答" in text
    assert "学生问题" in text
    assert "答非所问" in text or "未触及问题主体" in text


def test_critic_prompt_demotes_format_checks():
    """格式检查（语言标签 / 单字符行 / 与 line_text 一致性）只记轻微问题、不判失败。"""
    text = _critic_prompt()
    assert "轻微问题" in text
    assert "不判失败" in text
    assert "line_text" in text
    # 无对应 step_facts 的代码块（概念题讲解、示例、优化后的新代码）一律豁免
    assert "豁免" in text


def test_critic_prompt_gives_step2_veto():
    """收编优化第二步否决权（原计划 A 的 D6）：第二步出 options / 空 code 判失败。"""
    text = _critic_prompt()
    assert "【优化第二步】" in text
    assert "options" in text
    assert "判失败" in text
    # 原来的「不得因 kind 判失败」被收窄为「非第二步时」
    assert "非第二步" in text


def test_critic_prompt_requires_verifiable_spans():
    """输出契约必须是带出处的对象数组（CD-3）——否则意见会被机械丢弃、评审形同不存在。"""
    text = _critic_prompt()
    assert "answer_span" in text
    assert "fact" in text
    assert "blocking" in text
    assert "子串" in text


def test_revise_prompt_is_a_minimal_edit():
    """CD-2：修订从「自由重写」改为「最小编辑」——机制上不可能改变题旨。"""
    from graphs.javatutor.prompts import SYSTEM_PROMPT_REVISE

    assert "逐字保留" in SYSTEM_PROMPT_REVISE
    assert "不得重写" in SYSTEM_PROMPT_REVISE
    # 只修被指出的、有证据支持的具体错误
    assert "有证据支持" in SYSTEM_PROMPT_REVISE
    assert "原样保留" in SYSTEM_PROMPT_REVISE  # 结构化块契约（既有断言）


def test_concept_answer_with_illustrative_java_block_passes():
    """概念题含示意性 `java` 代码块、且事实依据里没有对应 `step_facts` ⇒ 不因格式判失败。

    对应归档 round-4 `q17`（「Math.pow 功能说明」，Judge 判 correct 4.5、评审判失败）——
    这是「格式规则必然误杀」的最小可复现形状。
    """
    state = {
        "answer": (
            "Math.pow(a, b) 返回 a 的 b 次方，返回 double。\n\n"
            "```java\n"
            "double r = Math.pow(2, 10); // 1024.0\n"
            "```\n"
        ),
        "user_question": "Math.pow 的功能是什么？",
        "compile_error": "",
        "intent": "concept",
        "retrieved_chunks": [],
    }
    # 评审模型照新表判通过（格式问题只记轻微问题；无 step_facts 的代码块一律豁免）
    out = critic_node(state, FakeModel('{"pass": true, "issues": []}'))
    assert out["critic_passed"] is True
    # 且提示词里确实写明了这条豁免——否则上一条断言只是「fake 说通过」
    assert "豁免" in _critic_prompt()




def test_facts_include_heap_stack_output():
    state = {
        **BASE,
        "has_steps": True,
        "steps": [
            {"step": 1, "line": 3, "variables": {"arr": [3, 5, 1]}, "heap": {"h1": {"type": "Object"}}, "stackFrames": [{"method": "main"}], "output": "out"}
        ],
        "current_step_index": 0,
        "current_line": 3,
        "source_code": "public class A {\n    void run() {\n        int x = 1;\n    }\n}",
    }
    facts = build_facts_block(state)
    assert "堆对象" in facts
    assert "栈帧" in facts
    assert "输出" in facts
    assert "int x = 1" in facts
