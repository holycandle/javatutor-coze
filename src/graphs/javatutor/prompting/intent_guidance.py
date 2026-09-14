"""按意图渲染「本轮问题类型」引导段，注入主 Agent 系统提示。

**为什么需要**：harness 重构（图内真环）之后，意图分类的产物在作答路径上没有任何消费者——
``_main_system_prompt()`` 不收 ``state``、``gather()`` 不注入意图、``build_context_node`` 把
``system_instructions`` 硬编码成 ``build_system_prompt("other")``。于是「意图识别已判定为概念讲解」
这句话在系统里**不产生任何效果**，用户看到概念题被当「当前步」作答。
（实测与穷举见 docs/plan/2026-09-14-fix-concept-intent-and-optimization-loop-plan.md §0.1 D2。）

**为什么不直接改 ``SYSTEM_PROMPT_MAIN_AGENT``**：那段是**所有**意图共用的模板，把概念专属规则
写进去会同时污染 data_query 请求。这里按意图**追加**一段，``data_query`` 与空串返回空串，
既有基线逐字不变（``test_data_query_prompt_unchanged`` 钉住这一点）。
"""

_CONCEPT = """## 本轮问题类型：概念讲解（concept）

- 用户问的是**概念/算法/数据结构本身**（原理、复杂度、定义、区别），不是当前这一步的执行数据。
- 直接讲解概念本身：先给定义或核心结论，再讲核心思想、适用边界与复杂度。
- **不要围绕当前执行位置作答**：避免把回答写成「第 N 步…」「当前行…」的执行解读。
- **默认不要调用 `step_facts`**：概念题不需要单步执行证据。确需引用本项目代码时，
  用 `fetch_execution_context` 取源码即可，不必逐步取变量快照。
- 可以结合本次提交的代码举一两句例子，但回答主体必须是概念讲解。"""

_DEBUG = """## 本轮问题类型：错误诊断（debug）

- 先定位根因，再给可直接运行的修复代码；行号/变量引用仍须取自 `step_facts` 的真实证据。
- 报错与运行模式强相关（如「找不到类 / 没有 main」），判读规则见「运行模式判读」段。"""

_OTHER = """## 本轮问题类型：通用提问（other）

- 意图未归入数据追问 / 概念讲解 / 错误诊断，按问题本身作答即可。
- **不要默认用户问的是当前执行步骤**：只有当提问确实指向某一步/某一行时才引用步骤数据。"""

_BY_INTENT = {"concept": _CONCEPT, "debug": _DEBUG, "other": _OTHER}


def render_intent_guidance(intent: str) -> str:
    """意图 → 引导段。

    ``data_query`` 与空/未知意图**返回空串**：data_query 的引导已由
    ``SYSTEM_PROMPT_MAIN_AGENT`` 的三步式调用示例覆盖，重复注入只会偏移既有基线。
    """
    return _BY_INTENT.get(intent or "", "")
