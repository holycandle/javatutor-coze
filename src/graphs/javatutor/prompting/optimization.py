"""代码优化引导：两步式（先方案后代码）+ kind 闭集 + goal 闭集。

与 ``render_nav_guidance()`` 同期注入 ``_main_system_prompt()``（走 SystemMessage，不被 compress 截断）。
决策依据见 docs/spec/2026-09-10-coze-agent-code-optimization.md（D2/D4/D5/D8/D11）。

要点：
- 复用【编辑建议】块加 ``kind`` 判别（patch/options/replace），不新开块——一份 mark / 一个解析器 / 一套 apply-undo 通道。
- 第一步只给 ``options`` 方案卡（闭集 goal），**不得**同时给代码；用户选定目标后第二步才给 ``replace`` 整份代码。
- ``code`` 必须是完整可独立编译的该文件全文；``target`` 在多文件模式下必填。
"""

# goal 闭集（与前端 utils/editSuggestion.js 的 GOALS 一致，改这里必须同步改前端与 spec §4.4）
GOALS = {
    "performance": "性能",
    "readability": "可读性",
    "memory": "内存",
    "style": "规范",
    "correctness": "正确性",
}


def render_optimization_guidance() -> str:
    """生成主 Agent 的「代码优化」引导段（两步式 + 块形态 + 取值规则）。"""
    goals = "、".join(f"{k}({v})" for k, v in GOALS.items())
    return f"""## 代码优化（两步式，不得一步到位）

当用户要求优化代码，或代码报错需要修正时，**分两步交付**，两步都用【编辑建议】块承载。

**第一步：只给方案，不给代码。**
正文说明有哪些可优化点、各自代价，末尾附（紧邻【决策痕迹】之前）：
【编辑建议】
{{"kind":"options","target":"<文件名；多文件模式必填>","options":[{{"goal":"performance","label":"以性能为先","detail":"用哈希表把嵌套循环降为 O(n)"}},{{"goal":"readability","label":"以可读性为先","detail":"拆分长方法并命名中间变量"}}]}}
- options 取 2–3 项；goal **只能**取：{goals}；detail 写针对这段代码的具体手段（可选）。
- **本步正文与块内都不得出现优化后的代码；options 块不含任何 code 字段。**
- 用户已指明目标（如「优化性能」）时同样先出方案卡（只列该目标一项即可），保持交互一致。

**第二步：用户选定目标后才给完整代码。**
【编辑建议】
{{"kind":"replace","target":"<文件名>","goal":"<用户选定的那个 goal>","rationale":"<一到两句：改了什么、为什么>","code":"<该文件完整代码>"}}
- code 必须是**完整、可独立编译**的该文件全文：不得省略、不得用 `...` 占位、不得只给片段或 diff。
- goal 必须等于用户选定的那个目标（保证「点的什么、给的就是什么」）。
- 块之后不要再写任何正文。

**局部修改不适用两步式**：若只需改动少量既有代码（不换写法），仍用既有 patch 形态
（{{"edits":[{{"title":"...","explanation":"...","old_string":"...","new_string":"..."}}]}}），不要用 replace。
**每答最多一个【编辑建议】块**；options 与 replace 不同时出现（一个是提方案、一个是交付）。"""
