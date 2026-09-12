"""代码优化引导：两步式（先方案后代码）+ kind 闭集 + goal 闭集。

与 ``render_nav_guidance()`` 同期注入 ``_main_system_prompt()``（走 SystemMessage，不被 compress 截断）。
决策依据见 docs/spec/2026-09-10-coze-agent-code-optimization.md（D2/D4/D5/D8/D11）。

要点：
- 复用【编辑建议】块加 ``kind`` 判别（patch/options/replace），不新开块——一份 mark / 一个解析器 / 一套 apply-undo 通道。
- 第一步只给 ``options`` 方案卡（闭集 goal），**不得**同时给代码；用户选定目标后第二步才给 ``replace`` 整份代码。
- ``code`` 必须是完整可独立编译的该文件全文；``target`` 在多文件模式下必填。
"""

# goal 闭集（与前端 utils/editSuggestion.js 的 GOALS 一致，改这里必须同步改前端与 spec §4.4）
# ``comprehensive`` 仅用于第二步 replace 的 goal（用户在方案卡上勾了 ≥2 个方向时），方案卡的
# options 不得产出它——否则「综合」会变成一个既不可执行又无法再拆分的选项。
GOALS = {
    "performance": "性能",
    "readability": "可读性",
    "memory": "内存",
    "style": "规范",
    "correctness": "正确性",
    "comprehensive": "综合",
}

# 方案卡（第一步 options）允许的方向：闭集去掉 comprehensive
CARD_GOALS = {k: v for k, v in GOALS.items() if k != "comprehensive"}


def render_optimization_guidance() -> str:
    """生成主 Agent 的「代码优化」引导段（两步式 + 块形态 + 取值规则 + 方向硬约束）。"""
    card_goals = "、".join(f"{k}({v})" for k, v in CARD_GOALS.items())
    return f"""## 代码优化（两步式，不得一步到位）

当用户要求优化代码，或代码报错需要修正时，**分两步交付**，两步都用【编辑建议】块承载。

**第一步：只给方案，不给代码。**
正文说明有哪些可优化点、各自代价，末尾附（紧邻【决策痕迹】之前）：
【编辑建议】
{{"kind":"options","target":"<文件名；多文件模式必填>","options":[{{"goal":"performance","label":"以性能为先","detail":"用哈希表把嵌套循环降为 O(n)"}},{{"goal":"readability","label":"以可读性为先","detail":"拆分长方法并命名中间变量"}}]}}
- options 取 2–3 项；goal **只能**取：{card_goals}（**不含 comprehensive**，它只用于第二步）。
- 每个 option 必须是**独立可组合**的一个方向：不要在一个 option 里塞进多个方向，
  也不要写成「既提升性能又改善可读性」——组合交给用户在方案卡上勾选。
- detail 写针对这段代码的具体手段（可选）。
- **本步正文与块内都不得出现优化后的代码；options 块不含任何 code 字段。**
- 用户已指明目标（如「优化性能」）时同样先出方案卡（只列该目标一项即可），保持交互一致。

**第二步的方向约束（硬要求）**
用户提问已按固定模板写明白名单（「只做…」）与黑名单（「不要顺带做其他方向的改动（例如：…）」），
那是用户在方案卡上勾选的结果，逐字照做：
- **只做所列方向**；未列入的方向一律不得改造，即使你认为它们也能优化，也不得顺手改（可在正文里提一句「另外还有 X 可优化」，但代码里不许动）。
- 用户列了 **≥2 个方向**时，`goal` 填 `comprehensive`，并在 `rationale` 里**分别**说明每个方向各改了什么。
- 用户只列 **1 个方向**时，`goal` 填该方向，且不得混入其它方向的改动。

**第二步：按上述方向给完整代码。**
【编辑建议】
{{"kind":"replace","target":"<文件名>","goal":"<用户选定的那个 goal>","rationale":"<一到两句：改了什么、为什么>","code":"<该文件完整代码>"}}
- code 必须是**完整、可独立编译**的该文件全文：不得省略、不得用 `...` 占位、不得只给片段或 diff。
- goal 必须等于用户选定的那个目标（保证「点的什么、给的就是什么」）。
- 块之后不要再写任何正文。

**候选返修（上一版代码没过校验时）**
用户提问里带「上一版优化代码没有通过编译/运行校验」并给出【校验错误】与【上一版候选代码】时，
**不要只解释错误、也不要再给方案卡**：直接重新交付一版 `kind:"replace"` 块。
- `goal` 与 `target` 必须与上一版**保持一致**（返修不是重新选方向的机会）。
- 修正范围**仅限**让代码能编译/运行通过；不得顺手改变优化方向或做其它改动。
- `code` 仍是完整、可独立编译的该文件全文。
- 若判断错误无法在不改方向的前提下修好，则只给正文说明原因，**不要**给 replace 块。

**局部修改不适用两步式**：若只需改动少量既有代码（不换写法），仍用既有 patch 形态
（{{"edits":[{{"title":"...","explanation":"...","old_string":"...","new_string":"..."}}]}}），不要用 replace。
**每答最多一个【编辑建议】块**；options 与 replace 不同时出现（一个是提方案、一个是交付）。"""
