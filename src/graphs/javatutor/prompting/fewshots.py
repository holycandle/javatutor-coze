"""每意图 few-shot 示例。示例中的步骤号/行号/变量名必须替换为本次真实数据。"""

from graphs.javatutor.prompting.versions import PROMPT_VERSION

MARKER = "（示例，步骤号/行号/变量名必须替换为本次真实数据）"

FEW_SHOTS = {
    "data_query": [
        f"{MARKER}\n问：为什么第 2 步 arr[1] 变成了 5？\n"
        "答：第 2 步（第 4 行）进入内层循环，比较 arr[0]=5 与 arr[1]=3，5>3 触发交换，"
        "所以 arr[1] 由 3 变成 5，arr[0] 由 5 变成 3。",
        f"{MARKER}\n问：此时 mid 是多少？\n"
        "答：第 5 步（第 8 行）mid = (low + high) / 2 = (0 + 7) / 2 = 3，当前查找区间是 arr[3..7]。",
    ],
    "concept": [
        f"{MARKER}\n问：冒泡排序原理是什么？\n"
        "答：冒泡排序每轮把未排序区间的最大值“冒泡”到末尾：内层循环相邻比较，逆序则交换。"
        "你的代码第 4-6 行就是比较与交换，外层第 3 行控制轮数。",
        f"{MARKER}\n问：二分查找时间复杂度为什么是 O(log n)？\n"
        "答：每轮把查找区间减半，n 个数最多 log2(n) 轮；你的代码第 7 行每次重新计算 mid。",
    ],
    "debug": [
        f"{MARKER}\n问：编译报错 cannot find symbol 怎么改？\n"
        "答：错误在第 5 行使用变量 total，但前面没有声明；要么补 `int total = 0;`，要么检查拼写。",
        f"{MARKER}\n问：NullPointerException 出现在第 9 行，为什么？\n"
        "答：第 9 行对 null 的 list 调用了 size()；回溯第 3 行初始化，确认 list 是否真的被赋值。",
    ],
    "other": [
        f"{MARKER}\n问：这个工具怎么用？\n"
        "答：先在左侧写代码并点击运行，右侧「变量」看逐步快照，「流程」看控制流，有问题可以继续问我。",
        f"{MARKER}\n问：你是什么？\n"
        "答：我是 JavaTutor 的 AI 助教，负责讲解你的 Java 代码如何执行，以及帮你排查问题。",
    ],
}


def get_few_shots(intent: str) -> list[str]:
    return FEW_SHOTS.get(intent, FEW_SHOTS["other"])
