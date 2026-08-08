---
title: Phase 2 — Analyze Expert (复杂度 + 算法/数据结构标签)
version: 2.0
date_created: 2026-08-08
owner: JavaTutor AI 智能体组
status: pending
depends_on: Phase 1 (completed)
replaces: docs/plan/analyze-specialist-plan.md
---

# Phase 2 — Analyze Expert 实现计划

> **背景**: Phase 1 完成了 4 个专家节点 (data_query / concept / debug / other)，全部返回纯文本。
> 现有架构已支持 `state.intent` 字段和 `_route_to_expert` 条件路由，本 Phase 只需增加
> analyze 专家 + 显式 intent 路由。
>
> **输入来源**: 前端点击"复杂度+标签"按钮 → 后端 `POST /api/ai/analyze`
> → `CozeService.blockingExplain(code, intent="analyze")`
> → JSON 负载含 `"intent": "analyze"`
> → 智能体**确定性路由**到 analyze_node（不依赖关键词猜测）。
>
> 自由问答（无 intent 字段）仍走关键词路由，行为不变。

---

## 1. 触发机制（显式 intent）

后端发送的 JSON 负载新增 `intent` 字段：

```json
{
  "source_code": "public class BubbleSort { ... }",
  "steps": [],
  "current_step_index": 0,
  "current_line": 0,
  "user_question": "请分析复杂度",
  "intent": "analyze",
  "user_id": "...",
  "compile_error": ""
}
route_intent 优先检查 state["intent"]，如果存在且在合法枚举中，直接返回该 intent，
跳过所有关键词匹配。
2. 输出格式
analyze_node 返回严格 JSON（不能有 Markdown 包裹，不能有任何其他文字）：
{
  "complexity": {
    "time": "O(n^2)",
    "timeExplanation": "双重for循环导致平方级复杂度",
    "space": "O(1)",
    "spaceExplanation": "仅使用temp临时变量，原地排序"
  },
  "algorithms": [{"name": "冒泡排序", "category": "排序"}],
  "dataStructures": [{"name": "数组", "category": "数组"}]
}
字段约束:
字段	要求
complexity.time	O(n), O(n log n), O(n^2) 等标准大 O 记号
complexity.space	同上
timeExplanation	一句话，引用代码具体结构
spaceExplanation	一句话，说明额外数组/递归栈/哈希表等
algorithms[].category	排序 / 搜索 / 递归 / 动态规划 / 贪心 / 分治 / 遍历 / 其他
dataStructures[].category	数组 / 链表 / 树 / 队列 / 栈 / 图 / 哈希表 / 堆 / 字符串 / 其他
algorithms	至少 1 个元素
dataStructures	至少 1 个元素


3. 实现任务
Task 1: parse_context — 解析 intent 字段
文件: src/graphs/javatutor/nodes.py
位置: _parse_json_dict 方法的返回值字典
def _parse_json_dict(data: dict) -> dict:
    # ... 现有字段提取 ...
    return {
        # ... 现有字段 ...
        "has_error": bool(compile_error and compile_error.strip()),
        "intent": data.get("intent"),    # ← 新增
    }
说明: 如果负载中没有 intent 字段，值为 None。route_intent 会处理这种情况。
Task 2: route_intent — 优先检查显式 intent
文件: src/graphs/javatutor/nodes.py
位置: route_intent 函数开头，在所有现有逻辑之前
def route_intent(state: JavaTutorState) -> dict:
    """意图路由节点。优先使用后端显式指定的 intent。"""

    # 新增: 显式 intent 优先（确定性触发）
    VALID_INTENTS = {"data_query", "concept", "debug", "analyze", "animate", "other"}
    explicit = state.get("intent")
    if explicit and explicit in VALID_INTENTS:
        return {"intent": explicit}

    # 规则 1: compile_error 短路（现有代码不变）
    if _is_compile_error_debug(state):
        return {"intent": "debug"}

    # 规则 2: 关键词匹配（现有代码不变）
    question = state.get("user_question", "").lower()
    data_query_keywords = ["为什么", "怎么", "如何", "arr", "变量", "值", "步骤", "结果", "输出"]
    concept_keywords = ["是什么", "算法", "复杂度", "概念", "原理", "定义", "时间", "空间", "o(", "大o"]

    if any(kw in question for kw in data_query_keywords):
        return {"intent": "data_query"}
    if any(kw in question for kw in concept_keywords):
        return {"intent": "concept"}

    return {"intent": "other"}
注意: 显式 intent 检查必须在 compile_error 检查之前。虽然分析请求不应该有 compile_error，但为了确定性路由的绝对优先，这样排更清晰。
Task 3: prompts.py — 添加 SYSTEM_PROMPT_ANALYZE
文件: src/graphs/javatutor/prompts.py
位置: 末尾
SYSTEM_PROMPT_ANALYZE = """你是一位资深的算法分析专家。分析给定的Java代码并返回严格的JSON。

返回格式（只返回JSON本身，不要Markdown包裹）:
{
  "complexity": {
    "time": "O(...)",
    "timeExplanation": "一句话解释为什么是这个时间复杂度",
    "space": "O(...)",
    "spaceExplanation": "一句话解释为什么是这个空间复杂度"
  },
  "algorithms": [
    {"name": "算法名", "category": "排序|搜索|递归|动态规划|贪心|分治|遍历|其他"}
  ],
  "dataStructures": [
    {"name": "结构名", "category": "数组|链表|树|队列|栈|图|哈希表|堆|字符串|其他"}
  ]
}

规则:
1. time/space 使用标准大O记号，如 O(n), O(n log n), O(n^2)
2. timeExplanation 必须引用代码中的实际结构（如"外层for循环遍历n个元素"）
3. spaceExplanation 说明是否使用了额外数组、递归调用栈、哈希表等
4. algorithms 和 dataStructures 至少各含一个元素
5. category 必须严格从给定选项中选择，不能自编
6. 只返回纯JSON字符串，不要```json```等Markdown包裹
7. 算法名使用中文标准名称（如"冒泡排序"、"二分查找"、"动态规划"）
"""
Task 4: nodes.py — 实现 analyze_node
文件: src/graphs/javatutor/nodes.py
位置: 在 other_node 之后、animate_node 之前
① 更新文件头部 import:
from graphs.javatutor.prompts import (
    SYSTEM_PROMPT_DATA_QUERY,
    SYSTEM_PROMPT_CONCEPT,
    SYSTEM_PROMPT_DEBUG,
    SYSTEM_PROMPT_ANIMATE,
    SYSTEM_PROMPT_OTHER,
    SYSTEM_PROMPT_ANALYZE,      # ← 新增
)
② 新增函数:
def analyze_node(state: JavaTutorState, model: "BaseChatModel | None" = None) -> dict:
    """analyze 专家: 分析复杂度 + 算法/数据结构标签，返回结构化 JSON."""
    source_code = state.get("source_code", "")
    user_question = state.get("user_question", "请分析代码复杂度")

    prompt = (
        f"用户问题: {user_question}\n\n"
        f"Java代码:\n```java\n{source_code}\n```\n\n"
        "请按指定JSON格式返回分析结果。"
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT_ANALYZE),
        HumanMessage(content=prompt)
    ]

    if model is not None:
        # 测试模式
        response = model.invoke(messages)
        raw = response.content
    else:
        # 生产模式
        client, llm_config = _get_chat_model()
        response = client.invoke(
            messages=messages,
            model=llm_config.model,
            temperature=0.3,
            top_p=llm_config.top_p or 0.9,
            max_completion_tokens=llm_config.max_completion_tokens or 4096,
        )
        raw = response.content

    raw = raw.strip()

    # 剥离可能的 Markdown 包裹
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3].strip()

    # 验证 JSON 合法性
    try:
        parsed = json.loads(raw)
        assert "complexity" in parsed
        assert "time" in parsed["complexity"]
        assert "space" in parsed["complexity"]
        assert "algorithms" in parsed and len(parsed["algorithms"]) >= 1
        assert "dataStructures" in parsed and len(parsed["dataStructures"]) >= 1
        answer = raw
    except (json.JSONDecodeError, AssertionError, KeyError) as e:
        # 兜底 JSON
        answer = json.dumps({
            "complexity": {
                "time": "O(?)",
                "timeExplanation": "LLM返回格式异常",
                "space": "O(?)",
                "spaceExplanation": f"解析失败: {str(e)[:80]}"
            },
            "algorithms": [{"name": "未知", "category": "其他"}],
            "dataStructures": [{"name": "未知", "category": "其他"}],
            "_raw": raw[:500]
        }, ensure_ascii=False)

    return {"answer": answer}
要点: temperature=0.3 保证 JSON 输出稳定，max_completion_tokens=4096 足够容纳完整分析。
Task 5: graph.py — 注册 analyze_node
文件: src/graphs/javatutor/graph.py
4 处修改：
① import:
from graphs.javatutor.nodes import (
    analyze_node,        # ← 新增
    animate_node,
    # ...
)
② 注册节点（在 other_node 之后）:
graph.add_node("other", other_node)
graph.add_node("analyze", analyze_node)    # ← 新增
graph.add_node("animate", animate_node)
③ 条件路由映射:
path_map={
    "data_query": "data_query",
    "concept": "concept",
    "debug": "debug",
    "analyze": "analyze",    # ← 新增
    "animate": "animate",
    "other": "other",
},
④ 专家→final 边:
for node in ["data_query", "concept", "debug", "analyze", "animate", "other"]:
    graph.add_edge(node, "final")
Task 6: 测试 — route_intent 显式 intent 测试
文件: tests/test_route_intent.py
追加:
def test_explicit_intent_overrides_keywords(self):
    """后端显式 intent=analyze 优先于所有关键词匹配."""
    state = {
        "intent": "analyze",
        "user_question": "为什么arr的值变了",  # 含 data_query 关键词
        "has_error": False,
        "compile_error": "",
    }
    result = route_intent(state)
    assert result["intent"] == "analyze"

def test_explicit_intent_analyze(self):
    """intent=analyze 确定性触发，不依赖任何关键词."""
    state = {
        "intent": "analyze",
        "user_question": "",
        "has_error": False,
        "compile_error": "",
    }
    result = route_intent(state)
    assert result["intent"] == "analyze"

def test_no_intent_falls_through_to_keywords(self):
    """无 intent 字段时行为不变，走关键词路由."""
    state = {
        "user_question": "时间复杂度是多少",
        "has_error": False,
        "compile_error": "",
    }
    result = route_intent(state)
    assert result["intent"] == "concept"  # "时间"关键词命中 concept
Task 7: 测试 — analyze_node
新建文件: tests/test_analyze_node.py
"""analyze_node 专家节点单元测试."""

import json
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage
from graphs.javatutor.nodes import analyze_node

BUBBLE_SORT = '''public class BubbleSort {
    public static void sort(int[] arr) {
        int n = arr.length;
        for (int i = 0; i < n - 1; i++)
            for (int j = 0; j < n - i - 1; j++)
                if (arr[j] > arr[j + 1]) {
                    int t = arr[j];
                    arr[j] = arr[j + 1];
                    arr[j + 1] = t;
                }
    }
}'''

VALID_RESPONSE = json.dumps({
    "complexity": {
        "time": "O(n^2)",
        "timeExplanation": "双重for循环",
        "space": "O(1)",
        "spaceExplanation": "原地排序"
    },
    "algorithms": [{"name": "冒泡排序", "category": "排序"}],
    "dataStructures": [{"name": "数组", "category": "数组"}]
}, ensure_ascii=False)


def test_analyze_valid_json():
    """analyze_node 正确解析 LLM 返回的合法 JSON."""
    model = MagicMock()
    model.invoke.return_value = AIMessage(content=VALID_RESPONSE)
    state = {"source_code": BUBBLE_SORT, "user_question": "分析复杂度"}
    r = analyze_node(state, model=model)
    p = json.loads(r["answer"])
    assert p["complexity"]["time"] == "O(n^2)"
    assert p["complexity"]["space"] == "O(1)"
    assert len(p["algorithms"]) >= 1
    assert p["algorithms"][0]["category"] in [
        "排序", "搜索", "递归", "动态规划", "贪心", "分治", "遍历", "其他"
    ]
    assert len(p["dataStructures"]) >= 1


def test_analyze_malformed_fallback():
    """LLM 返回非 JSON 时降级到兜底结构."""
    model = MagicMock()
    model.invoke.return_value = AIMessage(content="这不是合法的JSON")
    state = {"source_code": BUBBLE_SORT, "user_question": "分析复杂度"}
    r = analyze_node(state, model=model)
    p = json.loads(r["answer"])
    assert p["complexity"]["time"] == "O(?)"
    assert "_raw" in p
    assert len(p["algorithms"]) == 1
    assert len(p["dataStructures"]) == 1


def test_analyze_markdown_stripping():
    """LLM 返回 ```json``` 包裹时正确剥离."""
    model = MagicMock()
    model.invoke.return_value = AIMessage(content=f"```json\n{VALID_RESPONSE}\n```")
    state = {"source_code": BUBBLE_SORT, "user_question": "分析复杂度"}
    r = analyze_node(state, model=model)
    p = json.loads(r["answer"])
    assert p["complexity"]["time"] == "O(n^2)"
运行: uv run pytest tests/test_analyze_node.py -v → 预期 3 passed
Task 8: 冲烟验证
创建 scripts/smoke_test_analyze.py:
import json
from langchain_core.messages import HumanMessage
from graphs.javatutor.graph import build_flow_graph

# 测试1: 冒泡排序 → O(n^2)
payload = json.dumps({
    "source_code": "public class BubbleSort { static void sort(int[] a){int n=a.length;for(int i=0;i<n-1;i++)for(int j=0;j<n-i-1;j++)if(a[j]>a[j+1]){int t=a[j];a[j]=a[j+1];a[j+1]=t;}} }",
    "steps": [], "current_step_index": 0, "current_line": 0,
    "user_question": "分析复杂度",
    "intent": "analyze",
    "user_id": "test", "compile_error": ""
}, ensure_ascii=False)

graph, _ = build_flow_graph()
result = graph.invoke({"messages": [HumanMessage(content=payload)]})
answer = json.loads(result["messages"][-1].content)

print("Time:", answer["complexity"]["time"])
print("Algorithms:", answer["algorithms"])
assert "O(n^2)" in answer["complexity"]["time"] or "O(n²)" in answer["complexity"]["time"]
print("TEST 1 PASS — BubbleSort → O(n^2)")

# 测试2: 二分查找 → O(log n)
payload2 = json.dumps({
    "source_code": "public class BinarySearch { static int search(int[] a,int t){int l=0,r=a.length-1;while(l<=r){int m=l+(r-l)/2;if(a[m]==t)return m;if(a[m]<t)l=m+1;else r=m-1;}return -1;} }",
    "steps": [], "current_step_index": 0, "current_line": 0,
    "user_question": "分析复杂度",
    "intent": "analyze",
    "user_id": "test", "compile_error": ""
}, ensure_ascii=False)

result2 = graph.invoke({"messages": [HumanMessage(content=payload2)]})
answer2 = json.loads(result2["messages"][-1].content)
print("Time:", answer2["complexity"]["time"])
assert "log" in answer2["complexity"]["time"].lower()
print("TEST 2 PASS — BinarySearch → O(log n)")

print("\nALL SMOKE TESTS PASSED")
运行: python scripts/smoke_test_analyze.py
4. 文件变更清单
文件	操作	内容
src/graphs/javatutor/nodes.py	修改	① _parse_json_dict 加 intent 解析 ② route_intent 加显式检查 ③ 新增 analyze_node()
src/graphs/javatutor/prompts.py	修改	新增 SYSTEM_PROMPT_ANALYZE
src/graphs/javatutor/graph.py	修改	import + 注册节点 + 条件路由映射 + 边
tests/test_route_intent.py	修改	+3 个显式 intent 路由测试
tests/test_analyze_node.py	新建	3 个单元测试
scripts/smoke_test_analyze.py	新建	2 个冲烟验证


5. 验收标准

uv run pytest tests/ 全部通过（含 6 个新增测试）

冲烟 1: 冒泡排序 intent=analyze → O(n^2) + "冒泡排序" + "数组"

冲烟 2: 二分查找 intent=analyze → O(log n) + "二分查找"

冲烟 3: user_question="时间复杂度" 无 intent → 走 concept 专家（自由问答不受影响）

LLM 返回非 JSON 时正确降级到兜底结构

LLM 返回 json 包裹时正确剥离

显式 intent: "analyze" 优先于所有关键词匹配
6. 与后端的完整链路
前端"复杂度+标签"按钮
  → POST /api/ai/analyze
    → CozeService.blockingExplain(code, intent="analyze")
      → POST /stream_run (JSON 含 "intent": "analyze")
        → parse_context 解析 intent → route_intent 直接返回 "analyze"
          → analyze_node → LLM + 结构化 JSON
            → build_final → AIMessage(content=JSON字符串)
              → 后端 CozeAIController JSON.parse → 原样返回前端组件

自由问答（无 intent）
  → 前端"自由问答"输入框
    → POST /api/explain (原有端点)
      → 旧 DeepSeekService 或 Coze 关键词路由
        → 行为完全不变
后端 CozeAIController.analyze() 已就绪，CozeService.blockingExplain() 已支持 intent 参数。
前端切换只需把按钮目标 URL 从 /api/analyze 改为 /api/ai/analyze。