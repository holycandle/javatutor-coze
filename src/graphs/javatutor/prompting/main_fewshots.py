"""主 Agent 集中式 few-shot：注入 _main_system_prompt（走 SystemMessage，永不被 compress 截断）。

与 prompting/fewshots.py 的区别：那是**旧专家节点**（_build_expert_messages）的每意图 few-shot，
当前图（build_context→main_agent→critic→revise）不路由到专家节点、主 Agent 不含可审查 few-shot。
本模块是主 Agent 专用样本，开发者改这里即可稳定主 Agent 的结构契约行为、提升回答准确率。

样本要点：面板/sub/algo 合法形态、`【视角导航】` 放末尾且块后不追加正文、非面板主题（如测试模式）不附卡；
代码优化走两步式（第一轮只给 kind=options 方案卡、第二轮才给 kind=replace 整份代码）。
"""

import json

# 与 prompting/fewshots.py 同名标记：示例中的步骤号/行号/变量名仅示意，必须替换为本次真实数据。
MARKER = "（示例，步骤号/行号/变量名必须替换为本次真实数据）"

# 第二步 replace 的示例代码（仅示意）。用 json.dumps 生成块，保证 \n 等转义与 JSON 合法性。
_REPLACE_SAMPLE = json.dumps(
    {
        "kind": "replace",
        "target": "Solution.java",
        "goal": "performance",
        "rationale": "内层线性查找改为哈希表，整体由 O(n²) 降为 O(n)。",
        "code": (
            "import java.util.*;\n"
            "\n"
            "public class Solution {\n"
            "    public int[] solve(int[] nums) {\n"
            "        Map<Integer, Integer> seen = new HashMap<>();\n"
            "        for (int i = 0; i < nums.length; i++) seen.put(nums[i], i);\n"
            "        return nums;\n"
            "    }\n"
            "}\n"
        ),
    },
    ensure_ascii=False,
    separators=(",", ":"),
)

_OPTIONS_SAMPLE = json.dumps(
    {
        "kind": "options",
        "target": "Solution.java",
        "options": [
            {"goal": "performance", "label": "以性能为先", "detail": "用哈希表把嵌套循环降为 O(n)"},
            {"goal": "readability", "label": "以可读性为先", "detail": "拆分长方法并命名中间变量"},
        ],
    },
    ensure_ascii=False,
    separators=(",", ":"),
)

MAIN_FEW_SHOTS = [
    "【示例】问：算法模板在哪看？\n"
    "答：在「算法库」→「算法模板」。\n"
    "【视角导航】\n"
    '{"views":[{"panel":"algorithm","algo":{"subTab":"template"},"label":"算法模板"}]}',
    "【示例】问：怎么打开测试模式？\n"
    "答：粘贴含 `class Solution` 的代码 → 点「测试」展开用例面板 → 粘贴用例后「保存」激活测试模式 → 点「运行」，"
    "结果在「内存状态」面板的控制台区域查看。（测试模式不属于任何可导航面板，所以不附导航卡。）",
    "【示例】问：后序遍历的知识在哪看？\n"
    "答：在「算法库」→「算法知识」→「树（堆）」的「后序遍历」小节。\n"
    "【视角导航】\n"
    '{"views":[{"panel":"algorithm","algo":{"subTab":"knowledge","categoryId":"tree","anchorId":"后序遍历"},"label":"后序遍历"}]}',
    "【示例】问：为什么第 2 步 arr[1] 变成了 5？\n"
    "答：第 2 步（第 4 行）进入内层循环，比较 arr[0]=5 与 arr[1]=3，5>3 触发交换，所以 arr[1] 由 3 变成 5。"
    "【视角导航】\n"
    '{"views":[{"panel":"variables","label":"内存状态"}]}',
    # 优化第一步：只给方案卡（options），正文与块内都不得出现优化后的代码
    "【示例】问：帮我优化一下这段代码\n"
    "答：这段代码有两处可优化：① 内层线性查找每次都扫全表，可先用哈希表建索引降为 O(1)；"
    "② 变量命名较短、方法偏长，可读性有提升空间。请选择你更看重的方向。\n"
    "【编辑建议】\n"
    f"{_OPTIONS_SAMPLE}",
    # 优化第二步：用户选定目标后才给整份代码（replace）
    "【示例】问：（用户在上一步点选了「以性能为先」）以「性能」为优先优化当前代码，"
    "具体要求：用哈希表把嵌套循环降为 O(n)。请给出优化后的完整代码。\n"
    "答：把内层线性查找换成哈希表，整体由 O(n²) 降为 O(n)。\n"
    "【编辑建议】\n"
    f"{_REPLACE_SAMPLE}",
]


def get_main_few_shots() -> list[str]:
    """返回主 Agent few-shot 列表（每个样本前置「仅示意」标记，避免模型照抄数值）。"""
    return [f"{MARKER}\n{s}" for s in MAIN_FEW_SHOTS]
