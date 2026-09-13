"""保守意图识别规则（非 LLM）与硬事实核查，作为评估基准。"""

import re

VALID_INTENTS = {"data_query", "concept", "debug", "other"}

DEBUG_KEYWORDS = ["报错", "编译", "异常", "错误", "怎么改", "修复", "exception", "nullpointer", "越界"]
DATA_QUERY_KEYWORDS = ["为什么", "怎么变", "第", "步", "变量", "值", "变成", "此时", "当前", "数组", "arr"]
CONCEPT_KEYWORDS = ["原理", "复杂度", "概念", "定义", "是什么", "算法", "o(", "大o", "区别"]

# `arr` 必须按**词边界**匹配：子串匹配会让 ArrayList / arrays.sort / `add(arr)` 之类全部落到
# data_query，把概念题吞掉（实测 `ArrayList 的 get 复杂度是多少？` 曾判成 data_query）。
# 中文关键词无词边界概念，仍走子串匹配；只有 ASCII 标记需要这条约束。
_WORD_BOUNDED = {"arr"}


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
    if _hits(q, DATA_QUERY_KEYWORDS):
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
