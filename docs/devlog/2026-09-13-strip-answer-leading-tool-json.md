# 2026-09-13 回答正文顶端裸工具 JSON 剥离 — 实施记录

> 计划：`docs/plan/2026-09-13-strip-answer-leading-tool-json-plan.md`

**单仓**：coze `javatutor-coze`。前端未改动（本件是产物侧的文本清洗 + 上游提示词约束）。

交付范围：计划 Task 1–2（离线全绿）。

## 1. 做了什么

联调实测到一类畸形输出：主 Agent 把系统提示里逐字示范的工具格式当行首前缀**复述**，
且与紧随的正文标题连成一行：

```
{"tool": "fetch_execution_context", "args": {"file": "Main.java"}}### 当前这一步的执行内容
```

两处伤害：① 工具 JSON 漏进用户可见的回答正文；② `###` 因不在行首而**失去标题语义**。
本件做两件事：产物侧（`_strip_leaked_json` 增规则 0）与上游约束（提示词明令工具 JSON 独占一条消息）。

## 2. 决策与落点

| # | 落点 | 说明 |
|---|---|---|
| 1 | `_strip_leading_tool_json`（新增纯函数） | 用 `json.JSONDecoder().raw_decode()` 做**平衡解析**剥掉开头的工具 JSON |
| 2 | `_strip_leaked_json` 规则 0 | 在既有 4 条规则之前调用上者 |
| 3 | `SYSTEM_PROMPT_MAIN_AGENT` 增两句 | 「工具调用 JSON 必须独占一条消息」「回答正文中不得出现工具调用 JSON」 |

**为什么必须用 `raw_decode` 而不是正则**：既有规则 4 靠 `$` 锚定才成立，开头场景没有这个锚。
惰性 `.*?` 会停在 `args` 嵌套 `{}` 的**第一个** `}`，截断后残留一个孤立的 `}`。
`raw_decode` 返回平衡解析的结束位置，一次到位。

**判别条件为什么是 `obj.get("tool")` 而不是「开头是 `{` 就删」**：【视角导航】
（`{"views":[...]}`）与【编辑建议】块同样以 `{` 开头，且**必须原样透传**给前端
（见 `docs/spec/2026-09-07-coze-agent-view-navigation.md`）。判据收在 `tool` 键上，
其他结构化块一律不碰。

**为什么上游约束不是可有可无的**：规则 0 只是兜底。模型走「工具 JSON + 散文」这条路时
`parse_action` 返回 `None`，那一轮的工具**根本没有被调用**——若发生在第一轮，回答会缺证据，
比渲染问题更严重。故约束的落点是 `SYSTEM_PROMPT_MAIN_AGENT`（模型行为），不是清洗函数。

## 3. 改动清单

- `src/graphs/javatutor/nodes.py`：新增 `_strip_leading_tool_json`；`_strip_leaked_json` 增规则 0 与规则 1b。
- `src/graphs/javatutor/prompts.py`：`SYSTEM_PROMPT_MAIN_AGENT` 增两句约束。
- `tests/test_nodes.py`（新建，8 例）：粘连标题 / 前置散文 / 前导空白 / 意图 JSON 后再跟工具 JSON /
  导航块不回归 / 编辑建议块不回归 / 纯文本不变 / 端到端「粘连的工具 JSON 不进 answer 正文」。
- `tests/test_prompting.py`（+2 例）：提示词含约束、且**只加约束不删示例**（示例是模型学会工具协议的依据）。

## 4. 与计划的偏差（1 处）

**规则 0 被调用了两次（规则 1 之后补一次，标为「1b」）。**

计划的文字只写了「插在规则 1 之前」，但计划自己的用例 #6 要求
`{"intent":...}\n\n{"tool":...}\n\n正文` → `正文`。规则 1 剥掉意图 JSON 后会**新暴露出**
一个开头的工具 JSON，而规则 4 靠 `$` 锚定只管结尾——只按字面插一次，用例 #6 必失败。
故在规则 1 之后补了第二次调用，并加注释说明成因。这是**用例优先于措辞**的取舍，
不是额外功能。

## 5. 验证

- `uv run pytest tests/ -q` → **全绿**（本件单独看 `tests/test_nodes.py` + `tests/test_prompting.py` = 16 passed）。
- 端到端用例 `test_end_to_end_glued_tool_json_never_reaches_answer_body` 以**终态产物**取证
  （按 `\n\n【决策痕迹】\n` 切出正文段断言），不只停在函数返回值层。
- 红线未回归：既有 4 条规则的行为、`_redact_denied_tools`、`parse_action`、
  【视角导航】/【编辑建议】的透传契约均未改动（**只新增，不修改、不重排**）。

## 6. 已知局限

- 只处理**开头**的粘连。若模型把工具 JSON 写在正文中间（非开头、非结尾），仍会漏进正文。
  目前没有实测样本；提示词约束是主要防线，规则 0 是兜底。
- 清洗发生在**产物侧**：那一轮的工具调用确实没发生，清洗只是让「缺证据」看起来不那么难看。
  真正的修复是提示词约束（模型这一轮就会正确调用工具）。

## 7. review 处置（`docs/reviews/2026-09-13-process-streaming-and-strip-leading-tool-json-review.md`）

### 7.1 结论：**本件没有达成目标**（review §1，P1）

review 的机制复核**完全正确**，我已复现确认：用户报告症状的**可复现主因不是**模型在终答里
复述工具 JSON（即本件所修的那条路径），**而是既有的「提案 JSON 随 `answer` delta 流出 +
前端纯累加」**。

- `propose` 把模型原始输出放进 `agent_messages`（`propose.py:104`），LangGraph
  `stream_mode="messages"` 把它一并转出；平台 SDK 只过滤 `langgraph_node == "tools"`，
  其余非 chunk 的 `AIMessage` 一律转成 `answer`；
- 前端 `player.js` **纯累加**（`text += t`，不插分隔符、无重置）；
- 故提案 JSON 与紧随的正文粘成 `{"tool": …}}### 当前这一步的执行内容`——
  `}}###` 的粘连**不是**模型少打了换行，是 `+=` 本身不插分隔符。

**为什么本件修不到**：`_strip_leaked_json` 的唯一调用点是 `nodes.py:685`，作用对象是
`state["answer"]`；而上述 JSON **从不进入** `state["answer"]`，它直接走在流上。
规则 0/1b 写得再对，也清不掉客户端实际渲染的那一份。

> **本件的定位需据实修正**：它是一条**终态产物侧的正确加固**
> （`state["answer"]` 确实不该以裸工具 JSON 开头），但**不是**用户所报症状的修复。
> 症状修复落在**前端渲染路径**（见 review §6 处置 1，已实施）。
> §1「做了什么」与 §6「已知局限」的原始叙述默认了「模型把工具 JSON 写进正文」这一前提，
> 该前提**未获实测支持**——保留原文以留痕，真相以本节为准。

### 7.2 红线验收假绿（P1，已更正）

本件 §5 把「红线未回归」记为通过，但 review 指出：spec §5-6 的判据是
「被拒工具名不入**任何**用户可见产物」「最终 SSE 文本流**不含**该工具名」，
而**全链路流里确实含**。See sibling devlog
`2026-09-13-process-streaming.md` §3.2 #6（已由 ✅ 改 ❌）与 §5。

**方法论错误**：把红线用例**收窄**成「只查哨兵 delta」后记为通过——
收窄后的通过**不等于**原判据通过。教训与 review 2026-09-13（RAG 件）同源：
**红线类结论必须以端到端产物取证，且不得擅自收窄判据。**

### 7.3 与 spec / 计划的关系

review 认定本件为「**作用于 `state["answer"]` 的产物侧清洗**」，
与 `docs/plan/2026-09-13-strip-answer-leading-tool-json-plan.md` 的原始意图一致——
计划本身没有写错作用域，是**计划的假设**（症状来源在终答文本）与实测不符。
**建议**：合入窗口重发 agent 时，本件的**提示词约束**（工具 JSON 独占一条消息）仍然有效且必要
（它管的是模型行为，与流无关）；规则 0/1b 作为**终态兜底**保留。
