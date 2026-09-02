"""端到端复现：真实 Coze 转换路径 + step_facts 对单文件 13 步冒泡排序第 7 步。

验证链：agentJson(dict) → to_client_message → to_stream_input(content list)
→ HumanMessage(content=list) → parse_context → state["steps"]
→ step_facts(step_index=6, line=7 / line=0)
"""
import json, sys, os

ROOT = os.path.dirname(os.path.abspath(__file__))
# javatutor-coze/src 与 ../projects/src（真实 Coze 运行时）
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "..", "projects", "src"))
# coze_coding_utils 在 javatutor-coze/.venv site-packages，已在环境里

from langchain_core.messages import HumanMessage
from coze_coding_utils.helper.agent_helper import to_client_message, to_stream_input

from graphs.javatutor.nodes import parse_context, _parse_json_str
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
    return {
        "step": i,            # 0-based（与 fixture sample_payload.json 一致）
        "line": line,
        "variables": variables,
        "heap": {},
        "stackFrames": [{"method": "main", "locals": variables, "args": {}}],
        "output": None,
    }

# 13 步，真实冒泡排序轨迹（arr=[5,3,8]）
steps = [
    step(0, 3, {"arr": "[5, 3, 8]"}),
    step(1, 4, {"arr": "[5, 3, 8]", "n": 3}),
    step(2, 5, {"arr": "[5, 3, 8]", "n": 3, "i": 0}),
    step(3, 6, {"arr": "[5, 3, 8]", "n": 3, "i": 0, "j": 0}),
    step(4, 7, {"arr": "[5, 3, 8]", "n": 3, "i": 0, "j": 0}),
    step(5, 8, {"arr": "[5, 3, 8]", "n": 3, "i": 0, "j": 0, "temp": 5}),
    step(6, 9, {"arr": "[3, 5, 8]", "n": 3, "i": 0, "j": 0, "temp": 5}),   # 第 7 步
    step(7, 10, {"arr": "[3, 5, 8]", "n": 3, "i": 0, "j": 0, "temp": 5}),
    step(8, 6, {"arr": "[3, 5, 8]", "n": 3, "i": 0, "j": 1}),
    step(9, 7, {"arr": "[3, 5, 8]", "n": 3, "i": 0, "j": 1}),
    step(10, 5, {"arr": "[3, 5, 8]", "n": 3, "i": 1}),
    step(11, 6, {"arr": "[3, 5, 8]", "n": 3, "i": 1, "j": 0}),
    step(12, 7, {"arr": "[3, 5, 8]", "n": 3, "i": 1, "j": 0}),
]

agent_json = json.dumps({
    "source_code": SRC,
    "steps": steps,
    "current_step_index": 1,
    "current_line": 5,
    "user_question": "第 7 步在做什么？",
    "compile_error": "",
}, ensure_ascii=False)

# 1) 真实 Coze payload 形状
payload = {
    "type": "query",
    "session_id": "s1",
    "content": {"query": {"prompt": [{"type": "text", "content": {"text": agent_json}}]}},
}
client_msg, _ = to_client_message(payload)
stream_input = to_stream_input(client_msg)
print("=== to_stream_input ===")
print(json.dumps(stream_input, ensure_ascii=False)[:400], "...\n")

# 2) 模拟 LangGraph add_messages：把 messages 转成 HumanMessage，content 是 list
msg_content = stream_input["messages"][0]["content"]
human = HumanMessage(content=msg_content)
print("=== HumanMessage.content type ===", type(msg_content), "len", len(msg_content))

# 3) parse_context（用 _parse_json_str 直接，等价于节点内）
state = parse_context({"messages": [human]})
print("=== parse_context ===")
print("has_steps:", state["has_steps"], "| steps_count:", state["steps_count"],
      "| current_step_index:", state["current_step_index"],
      "| current_step_file:", repr(state["current_step_file"]))
print("steps[6] keys:", list(state["steps"][6].keys()))
print("steps[6]['step']:", state["steps"][6]["step"], "(期望 6 或 7? 数组索引=6)")
print("steps[6]['variables']:", state["steps"][6]["variables"])
print()

# 4) step_facts 查询第 7 步
for q in ({"step_index": 6, "line": 7}, {"step_index": 6, "line": 0}, {"step_index": 6}):
    r = step_facts(state, **q)
    print("=== step_facts", q, "===")
    print("  error:", repr(r["error"]))
    print("  evidence.line_text:", repr(r["evidence"]["line_text"]), "| file:", repr(r["evidence"]["file"]))
    print("  evidence.variables:", r["evidence"]["variables"])
    print("  diff:", r["diff"])
    print()
