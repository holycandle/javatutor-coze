"""端到端复现 2：build_context + main_agent(脚本) + critic 事实依据。

目标：确认模型第 3 轮手上有无「可读一致的第 7 步证据」，以及批评者 build_facts_block
给的事实依据是否足以核对一条关于第 7 步的正确回答。
"""
import json, sys, os

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "..", "projects", "src"))

from langchain_core.messages import AIMessage
from coze_coding_utils.helper.agent_helper import to_client_message, to_stream_input

from graphs.javatutor.nodes import parse_context
from graphs.javatutor.context_builder import build_context
from graphs.javatutor.main_agent import main_agent_node
from graphs.javatutor.prompting.contexts import build_facts_block
from tools.step_facts import step_facts

SRC = (
    "public class UserCode {\n"
    "  public static void main(String[] args) {\n"
    "    int[] arr = {5, 3, 8};\n"
    "    int n = arr.length;\n"
    "    for (int i = 0; i < n-1; i++) {\n"
    "      for (int j = 0; j < n-i-1; j++) {\n"
    "        if (arr[j] > arr[j+1]) {\n"
    "          int temp = arr[j];\n"
    "          arr[j] = arr[j+1];\n"
    "          arr[j+1] = temp;\n"
    "        }\n"
    "      }\n"
    "    }\n"
    "  }\n"
    "}\n"
)

def step(i, line, variables):
    return {"step": i, "line": line, "variables": variables, "heap": {},
            "stackFrames": [{"method": "main", "locals": variables, "args": {}}], "output": None}

steps = [
    step(0, 3, {"arr": "[5, 3, 8]"}),
    step(1, 4, {"arr": "[5, 3, 8]", "n": 3}),
    step(2, 5, {"arr": "[5, 3, 8]", "n": 3, "i": 0}),
    step(3, 6, {"arr": "[5, 3, 8]", "n": 3, "i": 0, "j": 0}),
    step(4, 7, {"arr": "[5, 3, 8]", "n": 3, "i": 0, "j": 0}),
    step(5, 8, {"arr": "[5, 3, 8]", "n": 3, "i": 0, "j": 0, "temp": 5}),
    step(6, 9, {"arr": "[3, 5, 8]", "n": 3, "i": 0, "j": 0, "temp": 5}),
    step(7, 10, {"arr": "[3, 5, 8]", "n": 3, "i": 0, "j": 0, "temp": 5}),
    step(8, 6, {"arr": "[3, 5, 8]", "n": 3, "i": 0, "j": 1}),
    step(9, 7, {"arr": "[3, 5, 8]", "n": 3, "i": 0, "j": 1}),
    step(10, 5, {"arr": "[3, 5, 8]", "n": 3, "i": 1}),
    step(11, 6, {"arr": "[3, 5, 8]", "n": 3, "i": 1, "j": 0}),
    step(12, 7, {"arr": "[3, 5, 8]", "n": 3, "i": 1, "j": 0}),
]

agent_json = json.dumps({
    "source_code": SRC, "steps": steps, "current_step_index": 1, "current_line": 5,
    "user_question": "第 7 步在做什么？", "compile_error": "",
}, ensure_ascii=False)

payload = {"type": "query", "session_id": "s1",
           "content": {"query": {"prompt": [{"type": "text", "content": {"text": agent_json}}]}}}
client_msg, _ = to_client_message(payload)
stream_input = to_stream_input(client_msg)
from langchain_core.messages import HumanMessage
state = parse_context({"messages": [HumanMessage(content=stream_input["messages"][0]["content"])]})

# 补默认值供 analyze 等依赖（这里 main_agent 只依赖 context_built）
state["intent"] = "data_query"
state["run_id"] = "r1"

# 1) build_context（GSSC）——模型第一轮看到什么
context_built = build_context(state, system_instructions="", max_tokens=3000)
state["context_built"] = context_built
print("=== context_built（模型第一轮上下文） ===")
print(context_built)
print("\n" + "=" * 70 + "\n")

# 2) main_agent_node：脚本化模型复现 6,7 → 6,0 → 回答
class Seq:
    def __init__(self, rs): self.rs = list(rs)
    def invoke(self, messages): return AIMessage(content=self.rs.pop(0))

answer_txt = ("第 7 步（step_index=6）是冒泡排序的一次交换：`arr[0]` 和 `arr[1]` 交换，"
              "`arr` 从 [5,3,8] 变成 [3,5,8]，`temp=5`。执行代码行 `arr[j] = arr[j+1];`。")
model = Seq([
    '{"tool":"step_facts","args":{"step_index":6,"line":7}}',
    '{"tool":"step_facts","args":{"step_index":6,"line":0}}',
    answer_txt,
])
main_out = main_agent_node(state, model=model)
print("=== main_agent 输出 ===")
print("tool_rounds:", main_out["tool_rounds"], "| tool_calls:", [(t["tool"], t["args"]) for t in main_out["tool_calls"]])
print("answer:", main_out["answer"])
print("step_memories count:", len(main_out["step_memories"]))
print()

# 3) 批评者事实依据（step_memories 已写入 state）
merged_state = dict(state)
merged_state["step_memories"] = main_out["step_memories"]
merged_state["answer"] = main_out["answer"]
facts = build_facts_block(merged_state)
print("=== 批评者 build_facts_block（事实依据） ===")
print(facts)
print("\n" + "=" * 70 + "\n")

# 4) 关键判断：事实依据里是否含「第 7 步 / step_index 6」的干净证据
print("提示：检查输出里是否出现 '<<< 第 6 步 >>>' 标签与 line_text 'arr[j] = arr[j+1];'。")
