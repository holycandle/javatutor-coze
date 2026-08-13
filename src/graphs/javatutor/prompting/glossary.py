"""JavaTutor 领域词汇表，注入 system prompt，统一产品语言。"""

from graphs.javatutor.prompting.versions import PROMPT_VERSION

GLOSSARY = {
    "TraceEngine": "JavaTutor 后端的逐步执行引擎，产出 steps 执行步骤数据。",
    "steps": "执行步骤数组，每步包含 line、variables、heap、stackFrames、output。",
    "变量快照": "某一步执行后所有局部变量/参数的当前值集合，前端显示为变量卡片。",
    "堆对象": "学生代码中 new 出来的复杂对象，前端在堆面板展示。",
    "栈帧": "方法调用栈中的一层，包含方法名、参数和局部变量。",
    "高亮行": "前端根据当前步骤行号高亮的源代码行。",
    "控制流": "前端流程面板展示的方法级流程图。",
    "单步播放": "前端逐步播放 steps 的能力。",
    "运行输出": "程序执行期间 System.out 捕获的输出，前端显示在控制台。",
    "算法标签": "analyze 专家输出的算法/数据结构分类标签。",
}


def build_glossary_block() -> str:
    lines = [f"- {term}: {desc}" for term, desc in GLOSSARY.items()]
    return "术语表：\n" + "\n".join(lines)
