"""保守意图识别规则（非 LLM）与硬事实核查，作为评估基准。"""

import re

from graphs.javatutor.prompting.optimization import STEP2_MARKER

VALID_INTENTS = {"data_query", "concept", "debug", "other"}

DEBUG_KEYWORDS = ["报错", "编译", "异常", "错误", "怎么改", "修复", "exception", "nullpointer", "越界"]
DATA_QUERY_KEYWORDS = ["为什么", "怎么变", "变量", "值", "变成", "此时", "当前", "数组", "arr"]
CONCEPT_KEYWORDS = ["原理", "复杂度", "概念", "定义", "是什么", "算法", "o(", "大o", "区别"]

# `arr` 必须按**词边界**匹配：子串匹配会让 ArrayList / arrays.sort / `add(arr)` 之类全部落到
# data_query，把概念题吞掉（实测 `ArrayList 的 get 复杂度是多少？` 曾判成 data_query）。
# 中文关键词无词边界概念，仍走子串匹配；只有 ASCII 标记需要这条约束。
_WORD_BOUNDED = {"arr"}

# 步骤/行号引用必须按**形状**匹配，不能只认「第」「步」两个字：优化第二步的提问里
# 「用哈希表记录每个元素第一次出现的下标」含「第」，曾被误判成 data_query
# （实测见 docs/plan/2026-09-14-fix-concept-intent-and-optimization-loop-plan.md §0.2 D7）。
# 中文数字也接受，避免「第二步」这类既有说法从 data_query 掉出去。
_STEP_LINE_REF = re.compile(r"第\s*[0-9一二三四五六七八九十]+\s*[步行]")


def _hits(text: str, keywords: list[str]) -> bool:
    for k in keywords:
        if k in _WORD_BOUNDED:
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(k)}(?![A-Za-z0-9_])", text):
                return True
        elif k in text:
            return True
    return False


def conservative_intent(user_question: str, compile_error: str = "") -> str:
    if compile_error and compile_error.strip():
        return "debug"
    q = (user_question or "").lower()
    if _hits(q, DEBUG_KEYWORDS):
        return "debug"
    # 优化第二步（提问以 `【优化第二步】` 起头）必须挡在关键词分支**之前**：
    # 提问的黑名单文案由模板拼出，必含「命名中间变量」「改进变量命名」这类字样，
    # 而 DATA_QUERY_KEYWORDS 含「变量」⇒ 必命中。判成 data_query 的代价不只是痕迹记错：
    # build_context_node 会据此注入 data_query 的角色与输出契约（「在哪一步、哪一行、哪个变量，
    # 长度 3-6 句」），与「交付整份 replace 代码」直接竞争。
    # 归 other 而非 concept：本类提问没有专属角色段，other 的引导（「按问题本身作答即可」）无害。
    if (user_question or "").lstrip().startswith(STEP2_MARKER):
        return "other"
    if _hits(q, DATA_QUERY_KEYWORDS) or _STEP_LINE_REF.search(q):
        return "data_query"
    if _hits(q, CONCEPT_KEYWORDS):
        return "concept"
    return "other"


def fact_matches(fact: str, answer: str) -> bool:
    answer = answer or ""
    fact = fact.strip()
    if fact.startswith("step="):
        n = fact.split("=", 1)[1].strip()
        return f"第 {n} 步" in answer or f"第{n} 步" in answer
    if fact.startswith("line="):
        n = fact.split("=", 1)[1].strip()
        return f"第 {n} 行" in answer or f"第{n} 行" in answer
    if "=" in fact:
        var, _, value = fact.partition("=")
        return var.strip() in answer and value.strip() in answer
    return fact in answer
