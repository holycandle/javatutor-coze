# 2026-09-13 RAG 可观测性 + 决策痕迹过程化 — 执行审查

> 审查对象：`javatutor-coze` 工作区（`eval/round-4` 分支）+ `javatutor/frontend` 工作区；后端未改动
> 对应计划：`docs/plan/2026-09-13-rag-observability-and-trace-process-plan.md`
> 对应设计：`docs/spec/2026-09-13-rag-observability-and-trace-process-design.md`
> 实现记录：`docs/devlog/2026-09-13-rag-observability-and-trace-process.md`

## 结论

实现与计划一致，三处计划偏差的**自主发现与处置**记录质量高（其中两处是照计划原文落地会引入的真问题——
一处红线、一处一等指标被静默改写）。离线交付（Task 1–8）全部到位，验证数字**独立复跑全部吻合**。

**但红线修复不完整**：`reasoning.tool_calls` 侧的泄露已堵住，`reasoning[].content` 侧仍有一条
**可经真实图触发的泄露路径**（`parse_action` 返回 `ParseError` 时原文含工具名，直接进 answer）。
这是本次审查唯一阻断级发现（**P1**），其余为 **1 个 P3**。

## 独立复现的验证（非引用 devlog）

| 项 | 命令 | 结果 |
|---|---|---|
| coze | `uv run pytest tests/ -q` | **361 passed / 0 failed**（与 devlog 一致） |
| 前端 | `cd javatutor/frontend && npx vitest run` | **390 passed / 29 files**（与 devlog 一致） |
| 红线两条既有守卫 | `pytest test_harness_loop.py::test_graph_unknown_tool_is_never_leaked_as_answer test_harness_termination.py::test_unknown_tool_spam_never_reaches_execution` | **2 passed** |
| 归档接线实跑 | 读 `eval/archive/2026-09-13/round-4/summary.json` | `total=31`、`retrieval_total=17`、`mrr/hit_at_1/3/5` 均 `0.0`（与 devlog §5 一致） |
| 诚实性核对 | `git diff` 逐文件 | 13 文件 589 增 17 删；`rag_degraded` 值未改（仅注释） |

## 1. 偏差 #1 的处置 —— 手段正确，但**未覆盖全部分支**（P1）

### 1.1 计划原文确实会踩红线（核实成立）

计划 Task 3 写「`tool_calls` 复用 `parse_action`；返回 `Action` 时取其 `tool`」。而 `decision_trace`
是**拼进 answer 的**（`build_final` 把 trace JSON 追加到回答尾部），所以「痕迹里出现被拒工具名」
等价于「回答里泄露被拒工具名」。两条既有守卫（`test_harness_loop.py:495`、`test_harness_termination.py:120`）
断言 `"no_such_tool" not in out["answer"]`，照原文落地必红。**执行组的判断与两层处置都正确。**

### 1.2 remaining 漏洞：`ParseError` 分支的 `content` 未剥离

`_strip_tool_json` 只处理「`json.loads` 成功且 `data["tool"]` 为真」的情形；`build_reasoning` 只在
`parse_action` 返回 **`Action`** 时调用它。但 `parse_action`（`harness/contracts.py:71-78`）对
**`args` 不是 dict** 的输入返回 **`ParseError`**（而非 `Action`），此时：

```python
else:
    content = raw          # ← 原文，含 {"tool":"no_such_tool","args":[...]}
    tool_calls = []
```

`tool_calls` 正确地归 `[]`（`executed_tools` 不含它），**但 `raw` 原样进了 `content`**，而 `content`
是用户可见痕迹、且被拼进 answer。**实测经真实图触发确认**（`SpamModel` 吐
`{"tool":"no_such_tool","args":[1,2]}`）：

```
LEAK: True
tool_calls: []
reasoning[0].content == '{"tool":"no_such_tool","args":[1,2]}'
snippet: ..."reasoning":[{"round":0,"content":"{\"tool\":\"no_such_tool\",\"args\":[1,2]}"...
```

即：**`tool_calls` 堵住了，`content` 没堵住**。同一份 answer 里 `no_such_tool` 仍然出现。

- **可达性**：`args` 非 dict 是模型真实的畸形输出（这正是 P2「参数结构校验」存在的理由）；
  `propose.py:112-117` 专门为 `ParseError` 保留 `action.tool` / `action.raw`，
  `guard.py:53` 也专门处理 `ParseError` → 说明这是**设计内的常见路径**，不是理论边角。
- **既有测试为何没抓到**：`test_graph_invalid_args_denied_before_execution`
  （`test_harness_loop.py:478`）用的是 `{"args": {"bogus_key": 1}}`——`args` **是** dict，
  走 `Action` 分支，被 `_strip_tool_json` 清空。测试用例恰好避开了 `ParseError` 路径。
  我在 `tests/test_build_reasoning.py::test_parse_error_yields_empty_tool_calls`
  里看到的输入 `{"tool":"step_facts","args":"oops"}` **确实会保留原文**，但该用例
  （a）只断言 `tool_calls == []`、未断言 content 不含工具名；（b）用的是真实工具名 `step_facts`，
  不是被拒工具名，所以没人注意到它会拼进 answer。

**处置建议**（改动很小，二选一或并用）：

1. `build_reasoning`：`parse_action` 返回 `ParseError` 且 `parsed.tool` 非空时，同样走
   `_strip_tool_json`（或直接置 `content = ""`）。语义与 `Action` 分支一致：tool 名已由
   `step_records` 的 `denied`/`invalid_args` 承载，痕迹侧不留后门。
2. `build_final`：在把 `trace_json` 拼进 answer 前，做一次**最终出口过滤**——
   对 `executed_tools` 之外、任何出现过的被拒工具名（`step_records` 里 `status != "ok"` 的 `tool`）
   做兜底剔除。这条更稳：它不依赖「每条路径都记得剥离」，对未来的新分支也成立。
   （注意别误伤：工具名可能作为**普通词**出现在正文，剔除只应作用于 trace JSON 段。）

**验收**：新增图级回归——`SpamModel('{"tool":"no_such_tool","args":[1,2]}')` 跑完整图后
断言 `"no_such_tool" not in out["answer"]`。这条用例当前**必红**，是本次修复的靶子。

## 2. 偏差 #3（检索分母覆盖 e2e `total`）—— 处置正确（核实成立）

`compute_retrieval_metrics` 的 `total`（声明 `expected_sources` 的条数 = 17）与 `summarize` 的
`total`（判分样本数 = 31）同名不同义。`report.py:40-67` 是 `e2e["total"]=len(parsed)` 后
`e2e.update(extended)`，直接并会把一等指标 `total` 静默改写成 17。执行组的改名处置
（`retrieval["retrieval_total"] = retrieval.pop("total")`）正确，并补了源码级回归。

**核实**：归档实测 `total=31` ✓、`retrieval_total=17` ✓。回归
`test_report_does_not_clobber_e2e_total_with_retrieval_denominator` 是**源码字符串断言**
（`assert 'retrieval["retrieval_total"] = retrieval.pop("total")' in src`）——能防「改回去」，
但防不住「换个写法继续覆盖」（例如 `extended["total"] = retrieval["total"]`）。属可接受的廉价守卫。

**教训认可**：`extended.update` 盲并——并入前须显式核对键名冲突。建议把这条写进
`dev-eval-guide.md` 的「新增扩展指标」小节（现仅在 devlog 里）。

## 3. 其余核实（均通过）

| # | 项 | 结论 |
|---|---|---|
| 3.1 | `sources` 只增键 | `source`/`score` 键与语义未改，新增 `chunk_index`/`content_preview`；`retrieval_metrics.py` 只读 `source`，未受影响 ✓ |
| 3.2 | `rag_degraded` 语义 | 仅注释与两处 return 值（未变）；「成功但 kept=0」不置位，`test_retrieval_kept_zero_does_not_degrade` 钉住 ✓ |
| 3.3 | 一次检索派生 `retrieved_chunks` | `retrieve_knowledge` 只调一次 `search_chunks_debug`，越阈值结果由 `candidates` 派生；派生 dict 形状与 `search_chunks` 一致（`round(...,4)` 同）；等价性守卫 `test_search_chunks_debug_equivalence_with_search_chunks` 在位 ✓ |
| 3.4 | `retrieval` 恒存在 | 缺 `retrieval_debug` 时返回 `{candidates:[], best_score:0.0, kept:0}`，消费方可无条件读 ✓ |
| 3.5 | 显式截断 | `_PREVIEW_CHARS=300` / `max_chars=1200` 均带 `truncated` 标志，不静默裁剪 ✓ |
| 3.6 | 前端缺省容错 | `traceProcess` 对缺键/类型不符一律归空不抛错；老数据不渲染折叠区；`processOpen` 独立 ref、默认收起 ✓ |
| 3.7 | 外壳与依赖 | 未碰 `.coze`/`scripts/`/`src/main.py`/`src/storage/`/`src/utils/`；无新依赖；`tools/eval_cli.py` 属允许目录 ✓ |
| 3.8 | 文档同步 | `agent-collaboration-guide.md` 补三键 + `retrieval_debug`（AGENT.md 规约要求，已做）；`dev-eval-guide.md` 补四档指标 + `retrieval_total` 口径 + 「排查检索为空」小节 ✓ |

### P3-1：`best_score` 依赖 fetcher 的排序不变量

`search_chunks_debug` 用 `candidates[0]["score"]` 当 `best_score`。这**当前正确**——`_fetch_similar`
的 SQL 是 `ORDER BY embedding <=> %s::vector LIMIT %s`（升序距离 = 降序相似度），row[0] 即最近邻。
但这一耦合**未写进 docstring**，也未断言。若未来换 fetcher（或加 `ORDER BY chunk_index` 之类），
`best_score` 会静默变成「第一条」而非「最高分」，而诊断结论会据此误判。建议在
`search_chunks_debug` docstring 补一句「`best_score` 取候选首条，依赖 fetcher 按距离升序返回」，
或直接 `max(c["score"] for c in candidates)`（不依赖顺序，成本可忽略）。

## 4. 遗留（与 devlog §6 一致，确认无异议）

- **Task 9 未做**：未重发 agent、未取 `best_score` 分布，**根因未定案**。本件只保证「数据能拿到」，
  符合 spec §5「诊断先行」的边界，**不构成本次交付缺口**（计划已声明属合入窗口）。
- **`reasoning` 对纯工具轮信息量低**：提案轮 content 多为空串。可接受（信息量在 `tool_calls`+
  `step_records`）。注意：修 P1 后空串会更彻底——这是**期望**方向。
- **trace 体积**：实测 ~763 字节（空检索场景）。RAG 修好后会上升，届时下调常量即可。
- **前端未流式**：spec §3.5 明确不要求。

## 5. 处置清单

| # | 级别 | 项 | 状态 |
|---|---|---|---|
| P1-1 | P1 | `ParseError` 分支的 `content` 未剥离工具名，可经真实图泄露进 answer | 待修（含图级回归靶子） |
| P3-1 | P3 | `best_score` 依赖 fetcher 排序不变量但无断言/说明 | 待定 |
| P3-2 | P3 | 「`extended.update` 盲并」教训只在 devlog，建议进 `dev-eval-guide.md` | 待定 |
