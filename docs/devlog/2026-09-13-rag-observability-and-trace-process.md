# 2026-09-13 RAG 检索可观测性 + 决策痕迹过程化 — 实施记录

> 设计：`docs/spec/2026-09-13-rag-observability-and-trace-process-design.md`
> 计划：`docs/plan/2026-09-13-rag-observability-and-trace-process-plan.md`
> 契约同步：`docs/agent-collaboration-guide.md`（`【决策痕迹】` 段）、`docs/dev-eval-guide.md`（评测 schema 段）

**跨仓**：coze `javatutor-coze` + 前端 `javatutor/frontend`。后端未改动。

交付范围：计划 Task 1–8（离线全绿）。Task 9（重发 agent + 取分数分布）属合入窗口，本件不做。

## 1. 做了什么

两件事，一件是修缺陷、一件是补能力：

1. **让 RAG 的失败可见**。部署侧四轮 `decision_trace.sources == []` 且 `rag_degraded == false`，
   而 `retrieval` 四档指标全 0——但 `summary.json` 里**完全看不到**（指标只在 `retrieval`
   子命令里，不进汇总）。本件给检索层开诊断通道（暴露**全量候选**，含被阈值滤掉的），
   并把四档指标接进 `summary.json`。
2. **决策痕迹过程化**。痕迹从「工具调用流水」升级为「完整过程」：新增 `retrieval`
   （检索全过程）与 `reasoning`（工具之间的 AI 思考），`sources` 增补 `chunk_index` /
   `content_preview`。

## 2. 决策与落点

| # | 落点 | 说明 |
|---|---|---|
| 1 | `search_chunks_debug`（新增） | 不过滤阈值，返回全量候选 + `best_score` / `kept`。既有 `search_chunks` 签名与行为不动 |
| 2 | `_raw_rows`（新增内部函数） | 两条检索路径共用「取原始行」，保证召回阶段完全一致 |
| 3 | `retrieval_debug`（新 state 字段） | 与 `retrieved_chunks` 分开：前者含被滤候选 |
| 4 | `retrieve_knowledge` | 只调**一次** `search_chunks_debug`，越阈值结果由 `candidates` 派生 |
| 5 | `build_reasoning`（新增纯函数） | 从 `agent_messages` 按序取 `AIMessage` |
| 6 | `build_final` 增三键 | `retrieval` / `reasoning` / `reasoning_truncated`；`sources` 增两键 |
| 7 | `eval_cli.py::cmd_report` | 并入 `compute_retrieval_metrics` → 进 `summary.json` |
| 8 | `traceProcess`（前端纯函数）+ 折叠区 | 「思考过程」默认收起 |

## 3. 改动清单

### 3.1 coze

| 文件 | 改动 |
|---|---|
| `src/learning/knowledge.py` | 新增 `_raw_rows` / `search_chunks_debug`；`search_chunks` 改为复用 `_raw_rows`（行为不变） |
| `src/graphs/javatutor/state.py` | 新增 `retrieval_debug: dict` |
| `src/graphs/javatutor/nodes.py` | `retrieve_knowledge` 改写；新增 `build_reasoning` / `_strip_tool_json` / `_build_retrieval` / `_PREVIEW_CHARS`；`build_final` 增三键与 `sources` 两键 |
| `tools/eval_cli.py` | `cmd_report` 并入检索指标 |
| `tests/test_knowledge.py` | +5（全量候选 / 字段 / 空查询 / 等价性守卫 / 异常上抛） |
| `tests/test_graph.py` | +3（debug 写入 / 区分滤掉与未召回 / 失败仍留字段） |
| `tests/test_build_reasoning.py`（新建） | 12 用例 |
| `tests/test_build_final.py` | +8（retrieval / preview 截断 / kept=0 不降级 / reasoning / 截断标志 / 缺省 / sources 增键 / 被拒工具不入 reasoning） |
| `tests/test_eval_report.py` | +2（report 接线 / 指标数值与分母语义） |

### 3.2 前端（`javatutor/frontend`）

| 文件 | 改动 |
|---|---|
| `src/utils/decisionTrace.js` | 新增 `traceProcess(trace)`（缺省容错，老数据不抛错） |
| `src/utils/decisionTrace.test.js` | +7（空 / reasoning / 截断 / retrieval 摘要 / kept=0 保候选 / 畸形容错 / hasContent） |
| `src/components/DecisionTracePanel.vue` | 「执行过程」内新增嵌套折叠「思考过程」（默认收起，`processOpen` 独立 ref） |

### 3.3 文档

- `docs/agent-collaboration-guide.md`：`【决策痕迹】` 段补三键说明 + `retrieval_debug` 字段。
- `docs/dev-eval-guide.md`：`e2e` 段补四档检索指标；`answers.jsonl` / `summary.json` 口径；新增「排查检索为空」小节。

## 4. 与计划的偏差（3 处，第 1 处是红线）

### 偏差 #1（重要）：`reasoning.tool_calls` **不得**记录被拒的工具名

计划 Task 3 写的是「`tool_calls` 复用 `parse_action`；返回 `Action` 时取其 `tool`」——
**照原文落地会踩红线**。全量回归立刻抓到两条失败：

```
FAILED tests/test_harness_loop.py::test_graph_unknown_tool_is_never_leaked_as_answer
FAILED tests/test_harness_termination.py::test_unknown_tool_spam_never_reaches_execution
```

两条都断言 `"no_such_tool" not in out["answer"]`。而 `decision_trace` 是**拼进 answer 的**，
所以「痕迹里出现被拒工具名」等同于「回答里泄露被拒工具名」。

设计 spec §4.7 早已定调：**`tool_calls` 不含被拒工具**。计划把 `reasoning.tool_calls`
当成「模型想调什么」的忠实记录，与这条契约冲突。

**处置**（两层）：

1. `_strip_tool_json`：提案轮的原始 JSON（`{"tool":...,"args":...}`）不进 `content`
   ——`content` 是用户可见痕迹，不能复制工具 JSON 负载；
2. `build_reasoning(..., executed_tools=...)`：只有**真的执行过**的工具名才进
   `tool_calls`，由调用方从 `step_records` 的 `status == "ok"` 派生。被拒（`denied` /
   `invalid_args`）一律归 `[]`，名字既不在 `tool_calls` 也不在 `content`。

语义上这更干净：`reasoning` 的 `tool_calls` 与顶层 `tool_calls` 同口径（都是「实际发生的事」），
而「模型提过但被拒的」本就该由 `step_records` 的 `denied` 记录承载，不该从痕迹侧开一个后门。

**顺带的取舍**：提案轮若整条输出就是 JSON，`content` 剥离后为空串。这让 `reasoning` 对
「纯工具轮」几乎不提供信息量——可接受，因为工具轮的信息量本来就在 `tool_calls` +
`step_records` 里；`reasoning` 的价值在散文轮（模型解释自己为什么这么查）。

### 偏差 #2：多了一个 `_build_retrieval` 辅助函数

计划 Task 4 把 `retrieval` 的构造直接写在 `build_final` 里。实际抽成了 `_build_retrieval(state)`：
`build_final` 已经 20+ 键、行数不少，再加一段逐条 candidates 转换会淹掉主流程；
且「缺 `retrieval_debug` 时返回恒存在的空壳」这条**必须**与「有 debug 时」放在一起读才不会写歪。

### 偏差 #3（是缺陷，已修）：检索分母 **覆盖** 了 e2e 的 `total`

计划 Task 5 写的是「`cmd_report` 里 `extended.update(compute_retrieval_metrics(...))`」。
照原文落地并**不会被任何测试抓到**，但归档重跑时暴露：round-4 的 `summary.json` 里
`"total": 31` 变成了 `"total": 17`。

两个 `total` 同名不同义——e2e 的是判分样本数（`summarize` 里的 `len(parsed)` = 31），
检索的是**声明了 `expected_sources` 的样本数**（= 17）。`eval/runner/report.py:40-67` 先
`e2e["total"] = len(parsed)` 再 `if extended: e2e.update(extended)`，于是检索的
`total` 直接盖掉样本数。而 `_E2E_METRIC_ORDER` 把 `"total"` 列在首位、合入门槛也读 summary
——这是**一等指标被静默改写**，比原缺陷更隐蔽。

**处置**：并入前把检索的分母改名（`compute_retrieval_metrics` 的返回形状不动，`cmd_retrieval`
子命令与既有断言依赖它）：

```python
retrieval = compute_retrieval_metrics(outputs, samples)
retrieval["retrieval_total"] = retrieval.pop("total")
extended.update(retrieval)
```

并补回归 `test_report_does_not_clobber_e2e_total_with_retrieval_denominator`：断言源码层
已改名、且不得再出现直连写法。重跑 round-4 后 `total` 回到 31，四档指标与 `retrieval_total: 17`
并存。

**教训**：`extended.update` 是「盲并」——凡并入者与 e2e 既有键同名就会静默覆盖。
此次是 `total`，下次可能是 `avg_score` 之类。并入前应显式核对键名冲突。

## 5. 验证
| 项 | 命令 | 结果 |
|---|---|---|
| coze 基线（改动前） | `uv run pytest tests/ -q` | **329** passed |
| coze（改动后） | 同上 | **368** passed（+39，含 review 处置新增 7 条） |
| 前端基线（改动前） | `cd javatutor/frontend && npm test` | 29 文件 / **383** 用例通过 |
| 前端（改动后） | 同上 | 29 文件 / **390** 用例通过（+7） |
| 前端构建 | `npm run build` | ✓ built（无模板/编译错误） |
| 指标接线实跑 | `uv run python tools/eval_cli.py --round-dir eval/archive/2026-09-13/round-4 report` | `e2e` 内出现 `mrr`/`hit_at_1`/`hit_at_3`/`hit_at_5`（均 0.0，检索分母另记为 `retrieval_total: 17`）——**四轮 RAG 退化首次在 summary 里可见** |
| 等价性 | 派生 `retrieved_chunks` vs `search_chunks` | 逐条相同（含 `source`/`chunk_index`/`content`/`score`） |
| 核心验收（spec §6.1） | `retrieval.candidates` 在 `kept == 0` 时非空 | ✅ 非空，且 `rag_degraded is False` |

第 4 行是本件的意义所在：round-4 归档重跑后，四档指标写进 `summary.json` 且**值确实是 0**
——缺陷不再需要靠人记得跑 `retrieval` 子命令才能发现。

## 6. 已知局限

- **Task 9 未做**：未重发 agent、未取 `best_score` 分布。**根因仍未定案**（查询稀释 / 阈值过高 /
  embedding 不一致三者未区分）。本件只保证「数据能拿到」。
- **`reasoning` 对纯工具轮信息量低**（偏差 #1 的代价）：提案轮 `content` 多为空串。
- **痕迹体积**：`retrieval.candidates` 上限 = `top_k`（3），候选 `preview` 截 300 字；
  `reasoning` 每条截 1200 字。实测单条 trace 约 763 字节（空检索场景），远低于 spec §2.4 担心的 3–5KB
  ——因为部署侧本来就检索不到东西。**RAG 修好后体积会上升**，届时按需下调 `_PREVIEW_CHARS` / `max_chars`。
- **前端未做流式**（spec §3.5 明确不要求）；折叠区默认收起，版面与改动前一致。
- **`sources` 增键**：`chunk_index` / `content_preview` 是纯增量，`retrieval_metrics.py`
  只读 `source`（已复核），未受影响的既有断言一条未改。

## 7. 手验清单（`npm run dev`；coze 侧需**重新发布 agent**）

1. 提问一个概念题（如「HashMap 的 get 原理」）→ 展开决策痕迹 → 展开「思考过程」。
2. 应能看到「查询「…」 · 阈值 0.3 · 最高分 x · 命中 0」与候选表（各条带分数，未过阈值者标「未过阈值」）。
3. 多轮工具调用的问题（如问「第 3 步变量为什么变了」）→ `reasoning` 应有 ≥1 轮散文；
   纯工具轮显示为空内容但列出工具名（该轮工具须是**执行成功**的）。
4. **回归**：不展开「思考过程」时版面与改动前一致；老数据（无 `retrieval`/`reasoning` 键）
   不渲染该折叠区、不报错。
5. **红线复核**：构造一个未知工具提问（或看 `step_records` 有 `denied` 的轮），
   确认回答正文与痕迹里**都不出现**该工具名。

## 8. Review 处置（`docs/reviews/2026-09-13-rag-observability-and-trace-process-review.md`）

| # | 级别 | 项 | 处置 |
|---|---|---|---|
| P1-1 | P1 | `ParseError` 分支的 `reasoning[].content` 仍含工具名，可经真实图泄露进 answer | **已修**（两层，见下） |
| P3-1 | P3 | `best_score` 依赖 fetcher 排序不变量而不自知 | **已修**：改取 `max(score)`，并补乱序 fetcher 回归 |
| P3-2 | P3 | 「`extended.update` 盲并」教训只在 devlog | **已修**：写进 `dev-eval-guide.md` 新增小节 |

### P1-1：红线修复不完整（本轮最重要）

Review 的判断**成立且我实测复现**：`build_reasoning` 只堵了 `Action` 分支，
`ParseError`（`args` 非对象）分支走 `content = raw`，原文连同工具名进了 content；
而 content 是拼进 answer 的用户可见痕迹。用 `SpamModel('{"tool":"no_such_tool","args":[1,2]}')`
跑真实图，`LEAK: True`，`reasoning[0].content == '{"tool":"no_such_tool","args":[1,2]}'`。

Review 还点出既有测试为何漏掉：`test_graph_invalid_args_denied_before_execution` 的
`{"args": {"bogus_key": 1}}` 里 `args` **是** dict（走 Action 分支，被剥离）；
而 `test_parse_error_yields_empty_tool_calls` 只断言 `tool_calls == []`、且用的是真实工具名——
**该用例的 docstring 甚至写着「原文保留」，把缺陷当成了规格**。已改写为断言 content 也被剥离。

**两层处置**（review 建议的两条都用上）：

1. `build_reasoning`：`ParseError` 同样走 `_strip_tool_json`（与 `Action` 分支同语义）。
2. `build_final`：新增 `_redact_denied_tools` 终局兜底——把 `step_records` 里
   `status != "ok"` 的权威被拒工具名，从 trace JSON 段里替换为占位串，**在拼进 answer 之前**。
   这层不依赖「每条路径都记得剥离」，对将来新增的分支同样成立。
   （只作用于 trace 段，正文里作为普通词的 token 不受影响；`decision_trace` 结构化值保留真值。）

**新增回归**：
- 图级靶子 `test_parse_error_proposal_never_leaks_tool_name_into_answer`——用**合法白名单工具**
  `step_facts` 配非法 `args`（未知工具会先被 P1 拦下，走不到 P2），断言
  `step_records` 全为 `P2`、`"step_facts" not in answer`。此用例在修复前**必红**。
- `build_reasoning` 单测三条：`args` 非对象剥离、`tool` 非字符串剥离、`tool` 为空则归散文保留原文。
- `_redact_denied_tools` 单测两条（替换生效 / 空串不得参与替换）+ `build_final` 端到端一条。

**顺带删掉一处死代码**：初版写的是 `isinstance(parsed, ParseError) and parsed.tool`，
但实测 `parse_action` 对任何假值 `tool`（`""` / `0` / `null`）一律返回 `None`，
`ParseError.tool` 不可能为空——这个守卫永远为真，已去掉，不在 `build_reasoning` 里重复解析器已保证的契约。

### P3-1：`best_score` 不再依赖 fetcher 排序

原实现取 `candidates[0]["score"]`——真实 fetcher 按距离升序，首条恰是最近邻，所以**眼下也对**。
但那把诊断结论偷偷绑在了排序不变量上：换 fetcher 或加次级排序，`best_score` 会静默变成
「第一条」而非「最高分」，据此误判「阈值是否过高」。改为 `max(..., default=0.0)`，
docstring 说明取最高分而非首条，并补乱序 fetcher 回归钉住。

### P3-2：盲并教训进指南

`docs/dev-eval-guide.md` 新增「给 `summary.json` 新增扩展指标时（重要陷阱）」小节：
`extended.update` 是盲并、同名键会静默覆盖、并入前须核对键名冲突、重名者在并入点改名，
并附本次 `total` 事件的实例与回归建议。

### 复核后无异议的遗留

Task 9（重发取数、根因定案）仍属合入窗口；`reasoning` 对纯工具轮信息量低是**期望**方向
（修 P1 后空串更彻底）；trace 体积、前端未流式均维持原判断。
