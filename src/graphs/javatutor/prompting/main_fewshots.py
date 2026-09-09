"""主 Agent 集中式 few-shot：注入 _main_system_prompt（走 SystemMessage，永不被 compress 截断）。

与 prompting/fewshots.py 的区别：那是**旧专家节点**（_build_expert_messages）的每意图 few-shot，
当前图（build_context→main_agent→critic→revise）不路由到专家节点、主 Agent 不含可审查 few-shot。
本模块是主 Agent 专用样本，开发者改这里即可稳定主 Agent 的结构契约行为、提升回答准确率。

样本要点：面板/sub/algo 合法形态、`【视角导航】` 放末尾且块后不追加正文、非面板主题（如测试模式）不附卡。
"""

# 与 prompting/fewshots.py 同名标记：示例中的步骤号/行号/变量名仅示意，必须替换为本次真实数据。
MARKER = "（示例，步骤号/行号/变量名必须替换为本次真实数据）"

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
]


def get_main_few_shots() -> list[str]:
    """返回主 Agent few-shot 列表（每个样本前置「仅示意」标记，避免模型照抄数值）。"""
    return [f"{MARKER}\n{s}" for s in MAIN_FEW_SHOTS]
