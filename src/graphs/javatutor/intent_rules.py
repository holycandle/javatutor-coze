"""保守意图识别规则（非 LLM）与硬事实核查，作为评估基准。"""

VALID_INTENTS = {"data_query", "concept", "debug", "other"}

DEBUG_KEYWORDS = ["报错", "编译", "异常", "错误", "怎么改", "修复", "exception", "nullpointer", "越界"]
DATA_QUERY_KEYWORDS = ["为什么", "怎么变", "第", "步", "变量", "值", "变成", "此时", "当前", "arr", "数组"]
CONCEPT_KEYWORDS = ["原理", "复杂度", "概念", "定义", "是什么", "算法", "o(", "大o", "区别"]


def conservative_intent(user_question: str, compile_error: str = "") -> str:
    if compile_error and compile_error.strip():
        return "debug"
    q = (user_question or "").lower()
    if any(k in q for k in DEBUG_KEYWORDS):
        return "debug"
    if any(k in q for k in DATA_QUERY_KEYWORDS):
        return "data_query"
    if any(k in q for k in CONCEPT_KEYWORDS):
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
