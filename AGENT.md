# AGENT.md — 项目协作与规约索引

> 本文件是 `javatutor-coze`（Coze 侧智能体项目）的规约/文档总索引。新增任何规约、spec、plan、devlog 时，必须在本文件登记。

## 仓库定位

- Coze 侧智能体项目，部署时由 Coze 平台拉取远程仓库执行。
- 协作分工：设计由 Codex 产出（spec → plan），执行由 Claude Code 完成；本地仓库为唯一代码事实来源。
- 所有本地开发行为遵守 `docs/local-dev-convention.md`。

## 当前执行状态

| 文档 | 状态 |
|---|---|
| 本地开发规约 v1.2 | 生效 |
| 评估系统 spec | 已执行 |
| 评估系统 plan | 已执行 |
| 架构改进 spec | 已评审 |
| 架构改进 plan | 已执行 |
| 执行上下文拉取 spec | 已执行 |
| 执行上下文拉取 plan | 已执行 |
| 执行上下文作为工具 spec | 已执行 |
| 执行上下文作为工具 plan | 已执行 |
| Harness 工程 spec（图内真环 + 治理门闩 + HITL 内核） | 已定稿 |
| Harness 工程 plan | 已执行 |
| 联调修复 spec 变更（优化候选自动返修 / 测试模式运行上下文） | 已执行（写入既有 spec） |
| 联调修复 plan（自动返修 + 测试模式上下文） | 已执行（含跨仓前端/后端改动） |
| 联调修复 review（自动返修 + 测试模式上下文） | 已处理（1 P2 / 6 P3 全部处置；2 条建议未采纳并附理由，见两份 devlog §8） |
| RAG 可观测性 + 痕迹过程化 spec | 已定稿 |
| RAG 可观测性 + 痕迹过程化 plan | 已执行（Task 1–8 离线全绿；Task 9 重发取数待合入窗口） |
| RAG 可观测性 + 痕迹过程化 review | 已审查（**0 阻断 / 2 P3**；初稿的 P1 系误报，已撤回并附教训：红线类结论须以端到端产物取证） |
| 回答裸 JSON 剥离计划 | 已执行（离线全绿；规则 0 调两次以覆盖「意图 JSON 剥出工具 JSON」的用例） |
| 过程式输出 spec（阶段 + 工具调用实时可见） | 已定稿 |
| 过程式输出计划 | 已执行（Task 1–8 离线全绿；L4 本地冒烟 SKIP，首屏实测待重发联调窗口） |
| 裸 JSON 剥离 + 过程式输出 review | 已审查（**1 P1 / 1 P2 / 2 P3**）：哨兵特性成立且按要求流出；但**剥离未命中报告 bug 的根因**——症状主因是既有「提案 JSON 随 `answer` delta 流出 + 前端纯累加」，剥离作用于 `state["answer"]` 够不到流；连带 spec §5-6 红线验收为**假绿**（全流确含被拒工具名），故 devlog §3.2 #6 须由 ✅ 改 ❌ |
| 联调修复计划（fetch 取不到源码 + 回答重复两遍） | 已执行（Task 1–8 离线全绿：coze 424 / 前端 440；3 处计划偏差 + 1 处计划外改进；**Task 0 现场证据仍待联调侧**；L4 本地冒烟 SKIP，线上未验证） |
| 联调修复计划（概念题被当「当前步」作答 + 优化第二步不出代码） | 已执行（Task 1–4 / 6–7 / 9–10 离线全绿：coze 447（本件完成时）/ 前端 445；与下述评审优化合并后 coze **484**；**Task 5 / Task 8 已按 §6 不再单独执行**——其内容由下述评审优化 spec 的 CD-4 取代、D6 收编进 Plan A Task 3，避免两份计划并行改评审表。**Bug D 根因定位为判别器冲突**（第二步提问形状 = 「已指明目标」形状，同形输入要求走两条分支）⇒ 判别器改为显式 `【优化第二步】` 标记，由前端写进提问、两侧字面量硬编码。**Task 0 现场证据仍待联调侧**；线上未验证） |
| 评审-修订子系统优化 spec | 已执行（联调反馈「评审很鸡肋，总把较正确的答案改得答非所问」；**量化取证**：四轮归档 124 样本中评审拦截 33 条，其中 **11 条 Judge 判 `correct`（误杀 33%）**，`incorrect` 只拦下 10/22（召回 45%），修订请求时延 +48%；6 条决策 CD-1…CD-6：回滚闸 / 最小编辑 / 意见必须给出处 / 评审表分流 + 补「正面回答」条 / advisory 开关 / 可观测性） |
| 评审-修订子系统优化计划 | 已执行（Task 0–7 离线全绿：coze **484 passed**（基线 431）/ 前端 445 / `npm run build` ok / L5 外壳两条命令均无输出；`tools/critic_audit.py eval/archive` 与设计 §1.2 逐格一致。**CD-2 在两份计划里都无对应 Task（计划漏列），已按设计依据补进 Task 3**——只收回滚闸不改提示词会让修订必然回退，见 devlog §4.1。另一处偏差：既有用例的语义变更实为 **6 个**（计划列 4 个走相似度回退分支，另 2 个因 CD-3 的 quote-or-drop 而失效），原意均保留。**Task 8 端到端取证须先重发 agent，未做——线上未验证**） |

## 规约与文档索引

| 类别 | 文件 | 说明 |
|---|---|---|
| 开发规约 | `docs/local-dev-convention.md` | 外壳契约、环境一致性、验证门槛、部署规约 |
| 接口契约 | `docs/spec/2026-08-10-coze-agent-interface.md` | 前后端与 Coze 的消息/决策痕迹契约 |
| 深化设计 | `docs/spec/2026-08-10-coze-agent-deepening-design.md` | 既有深化链路设计 |
| 评估系统设计 | `docs/spec/2026-08-14-agent-eval-system-design.md` | 双轨评估系统设计 |
| 评估系统计划 | `docs/plan/2026-08-14-agent-eval-system-plan.md` | 评估系统 TDD 实施计划 |
| Judge 修复计划 | `docs/plan/2026-08-17-judge-parser-fix-and-round2-plan.md` | Judge 解析修复与 Round-2 评估计划 |
| Judge 结构化输出计划 | `docs/plan/2026-08-18-judge-structured-output-and-fallback-rate-plan.md` | JSON Schema 约束 + 兜底率指标 + 人工复核接入导出 |
| 评估报告 MD 计划 | `docs/plan/2026-08-21-eval-report-md-plan.md` | 每轮生成人读 Markdown 报告 |
| 领域本体计划 | `docs/plan/2026-08-19-javatutor-domain-ontology-plan.md` | JavaTutor 结构化领域本体（模块/字段映射/契约规则） |
| 领域本体 review | `docs/reviews/2026-08-20-javatutor-domain-ontology-review.md` | 领域本体执行审查（1 P2 / 2 P3 已修复） |
| 评估报告 MD review | `docs/reviews/2026-08-21-eval-report-md-review.md` | Markdown 报告生成审查（2 P3） |
| 执行上下文获取设计 | `docs/spec/2026-08-23-execution-context-fetch-design.md` | 入站只带 run_id，Coze 侧确定性获取执行上下文 |
| 执行上下文获取计划 | `docs/plan/2026-08-23-execution-context-fetch-plan.md` | fetch_execution_context 工具 + graph 节点 + 降级 |
| 架构改进设计 | `docs/spec/2026-08-14-agent-architecture-improvement-design.md` | 多工具 + 上下文工程 + 工作记忆设计 |
| 架构改进计划 | `docs/plan/2026-08-14-agent-architecture-improvement-plan.md` | 架构改进 TDD 实施计划 |
| 执行上下文拉取设计 | `docs/spec/2026-08-23-execution-context-fetch-design.md` | 后端快照按 `run_id` 拉取与 Coze 侧 `fetch_execution_context` 设计 |
| 执行上下文拉取计划 | `docs/plan/2026-08-23-execution-context-fetch-plan.md` | 引用式拉取执行上下文 TDD 实施计划 |
| RAG 指南 | `docs/rag-knowledge-guide.md` | 语料格式与灌库说明 |
| 评估指南 | `docs/dev-eval-guide.md` | 开发者如何跑评估、解读结果与导出微调数据 |
| 协作指南 | `docs/agent-collaboration-guide.md` | 新人上手：处理流程图与各阶段职责 |
| 实现记录 | `docs/devlog/YYYY-MM-DD-<topic>.md` | 每次实现变更的流水记录 |
| 评估系统实现 | `docs/devlog/2026-08-14-agent-eval-system.md` | 双轨评估系统实现记录 |
| 评估系统 review | `docs/reviews/2026-08-14-eval-system-review.md` | 评估系统首轮审查 |
| 评估系统 M1.1 review | `docs/reviews/2026-08-14-eval-system-m11-review.md` | remote mode 与扩展指标审查 |
| 架构改进实现 | `docs/devlog/2026-08-15-agent-architecture-improvement.md` | 多工具架构重构实现记录 |
| 架构改进 review | `docs/reviews/2026-08-15-agent-architecture-improve-review.md` | 架构改进首轮审查（2 P1 / 2 P2 / 2 P3 已修复） |
| Judge 修复 review | `docs/reviews/2026-08-17-judge-parser-fix-review.md` | Judge 解析加固 + Round-1 重判（发现空返回主因） |
| Judge 结构化输出实现 | `docs/devlog/2026-08-18-judge-structured-output.md` | JSON Schema 回退 + 兜底率指标 + 人工复核接入导出（121 passed） |
| 领域本体实现 | `docs/devlog/2026-08-19-javatutor-domain-ontology.md` | 结构化本体 + 常驻层/Judge 注入（129 passed） |
| 评估报告 MD 实现 | `docs/devlog/2026-08-21-eval-report-md.md` | report.md 人读报告生成（133 passed） |
| 执行上下文获取实现 | `docs/devlog/2026-08-23-execution-context-fetch.md` | fetch 工具 + 确定性节点 + 降级（148 passed） |
| round-1 diff 修复 | `docs/devlog/2026-08-24-fix-round1-self-diff.md` | 修复首轮 report 与自身对比（137 passed） |
| grounding 核对器 | `docs/devlog/2026-08-24-grounding-verifier.md` | 确定性反幻觉结构核对（147 passed） |
| 执行上下文作为工具设计 | `docs/spec/2026-08-30-fetch-execution-context-as-tool-design.md` | fetch_execution_context 改为 agent 按需调用的纯 state 读取工具 |
| 执行上下文作为工具计划 | `docs/plan/2026-08-30-fetch-execution-context-as-tool-plan.md` | 纯 state 读取工具 TDD 实施计划 |
| 执行上下文作为工具实现 | `docs/devlog/2026-08-30-fetch-execution-context-as-tool.md` | 工具化重构，纯 state 读取（159 passed） |
| 多文件项目理解设计 | `docs/spec/2026-08-30-multifile-whole-project-design.md` | 概览+按需读：恒注入项目结构概览 + 主入口，其他文件按需读 |
| 多文件项目理解计划 | `docs/plan/2026-08-30-multifile-whole-project-plan.md` | 多文件读取 TDD 实施计划 |
| 多文件项目理解实现 | `docs/devlog/2026-08-30-multifile-whole-project.md` | file 参数激活 + 概览注入 + step_facts 按当前步文件（171 passed） |
| 知识库核对 | `docs/devlog/2026-08-25-knowledge-base-correction.md` | 领域本体核对修正 + 项目知识扩充（134 passed） |
| 非当前步证据标签修复 | `docs/devlog/2026-09-02-step-facts-non-current-step-file.md` | 评审核对证据的 0/1-based 标签错配，单文件查非当前步（190 passed） |
| fetch 调用率提升 | `docs/devlog/2026-09-08-raise-fetch-tool-call-rate.md` | step_facts 前置自动 fetch + 提示词强化，修复 round-2 分数下降（205 passed） |
| Harness 工程设计 | `docs/spec/2026-09-11-agent-harness-react-loop-design.md` | 图内真环 propose→guard→tools、统一动作契约、治理门闩（allow/deny/needs_decision）、收束轮、HITL 内核、grounding 接入运行时 |
| Harness 工程计划 | `docs/plan/2026-09-11-agent-harness-react-loop-plan.md` | 上述设计的 TDD 实施计划（含 test_main_agent.py 迁移表、终止性预算、外壳改造请求清单） |
| Harness 工程实现 | `docs/devlog/2026-09-11-agent-harness-react-loop.md` | 图内真环 propose→guard→tools + 治理门闩 P0–P5 + HITL 内核 + grounding 接入运行时（311 passed，4 处计划偏差，review 5 项已修） |
| Harness 工程 review | `docs/reviews/2026-09-11-agent-harness-react-loop-review.md` | 执行审查（1 P1 红线偏离 / 1 P2 HITL 末轮 / 3 P3；L1–L5 已复现）；**5 项全部已修复**，P1-1 采纳「保留行为 + 改 spec §5.1」、P2-1 改为 `P4-resolved` |
| 优化候选自动返修计划 | `docs/plan/2026-09-12-coze-agent-optimization-gate-retry-plan.md` | 2026-09-12 联调：门禁失败后前端自动返修候选（上限 2 次、原地替换卡片、只在最新一条 assistant 消息上、传输失败不返修）；跨前端 + coze |
| 测试模式上下文修复计划 | `docs/plan/2026-09-12-coze-agent-test-mode-context-fix-plan.md` | 2026-09-12 联调：测试模式未激活导致 agent 误诊——前端补运行模式事实（chat body + 报错入口）、后端透传、coze 补本体知识与「运行模式判读」引导；跨前端 + 后端 + coze |
| 优化候选自动返修实现 | `docs/devlog/2026-09-12-coze-agent-optimization-gate-retry.md` | 门禁失败后自动返修（上限 2 次、原地替换卡片、只在最新 assistant 消息、传输失败只重跑门禁）+ coze 返修引导段（前端 383 / coze 327，3 处计划偏差含 `regate` 闩防 fetch 风暴；review 5 项处置见 §8：重跑通知量收到**消息级**、返修状态机补 7 条回归） |
| 测试模式上下文修复实现 | `docs/devlog/2026-09-12-coze-agent-test-mode-context.md` | `run_mode`/`test_case_count` 透传 → state → `### 运行模式` packet + 评审核对 facts 行 + 引导段 + 本体扩充（后端 126 / coze 327，5 处计划偏差含后端基线口径更正 124→123；review 3 项处置见 §8：`user_guides` 只进主 Agent、本体去重） |
| 联调修复 review | `docs/reviews/2026-09-12-coze-agent-optimization-retry-and-test-mode-review.md` | 两件联调修复执行审查（1 P2 / 6 P3，不阻塞合并），**已全部处置**：P2-1 补返修状态机回归网；P3-1 订正计划自身的「本体同时被 Judge 消费」事实性错误（`user_guides` 只进主 Agent）；P3-4 同步 spec §8/§9/§11；P3-6 重跑 nonce 由全局收到消息级（顺带消 P3-3(b)）；P3-2 复核后**前提不成立**（门禁走裸 `fetch`，`httpStatus` 分支可达），改记真实的三条到达路径；另附后端用例计数陷阱（陈旧 surefire 报告会多算 1） |
| RAG 可观测性 + 痕迹过程化设计 | `docs/spec/2026-09-13-rag-observability-and-trace-process-design.md` | 先让静默瘫痪四轮的 RAG 可见（暴露全量候选 + 指标进 summary），再把决策痕迹升级为完整过程（`retrieval` / `reasoning` / `sources` 增强） |
| RAG 可观测性 + 痕迹过程化计划 | `docs/plan/2026-09-13-rag-observability-and-trace-process-plan.md` | 上述设计的 TDD 实施计划（Task 1–8 离线交付，Task 9 重发取数属合入窗口） |
| RAG 可观测性 + 痕迹过程化实现 | `docs/devlog/2026-09-13-rag-observability-and-trace-process.md` | `search_chunks_debug` + `retrieval_debug` + `retrieval`/`reasoning` trace + 检索指标进 summary + 前端「思考过程」（coze 368 / 前端 390，3 处计划偏差含不得泄露红线修正与检索分母覆盖 `total` 的修复；review 1 P1 / 2 P3 处置见 §8：`ParseError` 分支 content 泄露两层堵 + 终局兜底 `_redact_denied_tools`、`best_score` 改取最高分、盲并教训进指南） |
| RAG 可观测性 + 痕迹过程化 review | `docs/reviews/2026-09-13-rag-observability-and-trace-process-review.md` | 执行审查（**0 阻断 / 2 P3**）：红线（不得泄露被拒工具名）经端到端实测四种畸形输入**均不泄露**，三层防御在位；P3-1 `best_score` 依赖 fetcher 排序无断言；P3-2 盲并教训未进指南。**初稿曾把「`ParseError` 分支 content 未剥离」误判为 P1，已撤回**——错因是只做函数级取证未跑图，§1.4 记教训 |
| 裸 JSON 剥离 + 过程式输出 review | `docs/reviews/2026-09-13-process-streaming-and-strip-leading-tool-json-review.md` | 两件执行审查（**1 P1 / 1 P2 / 2 P3**）：P1 系报告 bug 根因未命中——`main_agent` 提案 `AIMessage` 经 SDK 转成 `answer` delta，被前端 `player.js:521` 纯累加后粘在正文前（端到端复现出与截图同形产物），剥离函数在 `nodes.py:685` 只作用于 `state["answer"]`；连带 spec §5-6 红线为假绿。哨兵通道本身红线守住，4 处计划偏差均为改进 |
| 回答裸 JSON 剥离计划 | `docs/plan/2026-09-13-strip-answer-leading-tool-json-plan.md` | 回答正文顶端裸工具 JSON + 标题不换行的修复：`_strip_leaked_json` 增「开头 `{"tool"}`」规则（用 `json.JSONDecoder().raw_decode` 平衡解析，惰性正则会在 `args` 嵌套 `{}` 处提前截断）+ 提示词上游约束；含导航/编辑建议块不回归与端到端红线用例 |
| 过程式输出设计 | `docs/spec/2026-09-13-process-streaming-design.md` | 「流中哨兵」：业务节点把已发生的事实（阶段/工具调用）作为 HTML 注释哨兵放进 `messages`，借既有 `stream_mode="messages"` 通道流出，Java 代理与前端的 `event:chunk` 原样透传——**零外壳、零 Java、零协议变更**；含状态卫生（`RemoveMessage` + 历史过滤）与被拒工具名红线 |
| 过程式输出计划 | `docs/plan/2026-09-13-process-streaming-plan.md` | 上述设计的 TDD 实施计划（coze Task 1–5 / 前端 Task 6–7 / 端到端 Task 8）；明确不流 `reasoning`（恒空串）与 RAG 明细（生产侧恒空），只流真实存在的事实 |
| 回答裸 JSON 剥离实现 | `docs/devlog/2026-09-13-strip-answer-leading-tool-json.md` | `_strip_leading_tool_json`（`raw_decode` 平衡解析）+ 规则 0/1b + `SYSTEM_PROMPT_MAIN_AGENT` 两句约束（coze 407，1 处计划偏差：规则 0 须在规则 1 后再调一次，否则计划自身的用例 #6 必失败）。**review 更正**：本件是**终态产物侧的正确加固**，但**未命中**用户所报症状的根因（见 §7） |
| 过程式输出实现 | `docs/devlog/2026-09-13-process-streaming.md` | 「流中哨兵」`<!--jt:process {json}-->` 借 `stream_mode="messages"` 出流（零外壳/零 Java/零协议变更）；三发射点 + `RemoveMessage`/历史过滤两道卫生防线 + 前端实时进度区（coze 407 / 前端 431，L5 外壳 0 命中；4 处计划偏差含 `renderMarkdown` 实为**丢弃**哨兵、同批 id 重复静默丢事件；L4 SKIP 且首屏 18s 对照为推演非实测）。**review 处置见 §5**：P1 前端 `stripLeadingToolJson` 已实施并端到端取证、红线 #6 改 ❌、P2 未修但已用测试钉住、2 P3 已改 |
| 裸 JSON 剥离 + 过程式输出 review | `docs/reviews/2026-09-13-process-streaming-and-strip-leading-tool-json-review.md` | 执行审查（**1 P1 / 1 P2 / 2 P3**，已全部处置）：独立复跑 coze 407 / 前端 431 与 devlog 吻合，4 处计划偏差**全判为改进**（规则 1b 补的是计划自身代码片段的漏洞）；P1 报告 bug 根因未命中 + 红线 #6 假绿（**既有**违规）→ 前端 `stripLeadingToolJson` 修复；P2 终答下发两次（同根因，用户选定最小修复故未修，已钉住）；P3 节点名 `run_tools` 与 SDK `tools` 过滤器隐式耦合、哨兵不跨 chunk 属假定 → 均已改 |

| 联调修复计划 | `docs/plan/2026-09-14-fix-fetch-context-and-duplicate-answer-plan.md` | 2026-09-14 联调两 bug：**A 回答正文重复两遍**（已用真实图 + SDK 全链路复现，根因 = `propose` 终答轮把终答写进 `agent_messages` 致其随 `answer` delta 流出，与 `build_final` 构成重复）；**B fetch 调了却「没有源码」**（五条各自独立确认的缺陷：前端 `multiState.entryFile` 从未被赋值、`_resolve_code` 静默回落 `source_code` 且 `file` 恒空、`files` 非空+`entry_file` 空时「成功但空」无信号、P4 阈值只覆盖 `len(files) > 1`、`switchMode('single')` 不清 `multiState.files`）；跨 coze + 前端 |
| 联调修复实现 | `docs/devlog/2026-09-14-fix-fetch-context-and-duplicate-answer.md` | 上述两 bug 的实施记录：`propose` 终答/收束轮不入 `agent_messages`（根治重复正文）、`_resolve_code` 六级有序解析 + 自描述回包（`file`/`file_source`/`code_chars`）+ 取消「成功但空」、P4 判据改按 `match_file_key` 匹配不到、前端 `entryFile` 接线（`refreshEntryFile`）+ 按模式裁剪提问体（coze 424 / 前端 440，3 处计划偏差 + 1 处计划外改进；Task 0 现场证据待联调侧，L4 SKIP 线上未验证）。**§6 追加**：联调反馈「执行过程区不再显示 Main.java」——排查为「痕迹只反映模型想读什么（`args`）而非实际读到什么（`result`）」的结构性缺口，前端补 fetch 专用渲染（`→ Main.java（主入口），1234 字` / `→ 失败：…`），前端 444 passed |

| 联调修复计划 | `docs/plan/2026-09-14-fix-concept-intent-and-optimization-loop-plan.md` | 2026-09-14 联调两 bug：**C 概念题被当「当前步」作答/概念回答被评审误杀**（根因：`intent` 在作答路径上**无任何消费者**——`_main_system_prompt` 不收 state、`gather` 不注入意图、`build_context_node` 硬编码 `"other"`；另加「当前执行位置」无条件注入 + 概念 few-shot 为 0 + 评审核对表为 data_query 而写且无意图门）；**D 优化第二步不出代码**（**已线上复现**：两步式**没有判别器**——spec §4.3 要求「用户已指明目标仍先出方案卡」，而第二步提问就是「已指明目标」的形状；评审又被明文禁止因 `kind` 判失败）；修法 = 前端 `【优化第二步】` 标记做判别器 + 意图接进提示与评审；跨 coze + 前端。**评审侧 D5/D6 已移交评审优化计划** |
| 评审-修订优化设计 | `docs/spec/2026-09-14-critic-revise-optimization-design.md` | 评审-修订子系统的优化设计：**修订不可回滚**（`critic→revise` 无条件、`verify` 明文只记录不路由 ⇒ 全链路无环节能发现「改差了」）+ **自由重写**（body 整段丢弃重生成，事实块偏向当前步）+ **意见无需出处**（第 6 条是格式规则，概念题必误杀）+ **评审表缺「是否正面回答学生问题」**；决策 CD-1…CD-6；**取代**深化设计 D-02/D-10，**取代/收编**上表的 D5/D6 |
| 评审-修订优化计划 | `docs/plan/2026-09-14-critic-revise-optimization-plan.md` | 上述设计的 TDD 实施计划（Task 0 审计工具 / Task 1 回滚闸 G1-G2（最高价值）/ Task 2 意见必须给出处 / Task 3 评审表分流 + 正面回答条 / Task 4 G3-G4 / Task 5 advisory 开关 / Task 6 痕迹与指标 / Task 7 文档 / Task 8 端到端取证）；含 **4 个既有用例的语义变更清单** 与 `tools/critic_audit.py` 复跑口径 |
| 评审-修订优化实现 | `docs/devlog/2026-09-14-critic-revise-optimization.md` | 四道验收闸（G1 相似度 / G2 结构化块保全 / G3 引用不劣化 / G4 二次评审）+ 意见须给出处 + 评审表按意图分流 + `critic_mode` advisory 开关 + 痕迹三键与 `critic_agree_with_judge` 指标（coze 484 / 前端 445，L5 无输出；**§4.1 记 CD-2 计划漏列**、§4.2 语义变更用例实为 6 个、§4.3 六项实现选择含 `revise_recheck_passed` 仅在真跑过时出现；**Task 8 端到端取证未做，线上未验证**） |
| 概念题意图 + 优化第二步实现 | `docs/devlog/2026-09-14-concept-intent-and-optimization-loop.md` | `intent` 接入作答路径（`render_intent_guidance` / `_main_system_prompt(intent)` / `gather` 位置包门控 / 契约按意图取）+ 第二步判别器改显式 `【优化第二步】` 标记（跨仓字面量两侧硬编码 + 互读对方文件的断言）+ 概念类 few-shot（coze 447→484 / 前端 445）。**取证不对称必须分开说**：实测 1 复现了「概念回答被误杀」，实测 2 **未**复现「答成当前步」，故 Bug C 的修法按三条结构性缺陷计为**预防而非已确认触发条件的修复**；Bug D 已端到端复现（实测 4，根因判别器冲突） |

## 文档规范

1. 新规约：放 `docs/` 或仓库根，并在本文件登记。
2. 新设计：`docs/spec/YYYY-MM-DD-<topic>-design.md`。
3. 新计划：`docs/plan/YYYY-MM-DD-<topic>-plan.md`，TDD 格式。
4. 实现记录：`docs/devlog/YYYY-MM-DD-<topic>.md`。
5. 文件统一 UTF-8；文件名只允许字母、数字、下划线、短横线。
6. 文档内容不得出现 `TBD` / `TODO` 占位；未定的内容先定方案再写。
7. Review 内容除非过短（少于一条有效结论），必须撰写 review 日志到 `docs/reviews/YYYY-MM-DD-<topic>-review.md`，并在本文件登记。
7. 完成完整新功能或修复重大 bug 后，必须撰写开发日志 `docs/devlog/YYYY-MM-DD-<topic>.md`，记录改动内容、验证结果与遗留问题；开发日志随功能一起提交，并在本文件登记。

## 协作规则（摘要）

- 不修改外壳：`.coze`、`scripts/`、`src/main.py`、`src/storage/`、`src/utils/`。
- 业务代码只允许新增到：`src/agents/`、`src/graphs/`、`src/learning/`、`src/tools/`、`tools/`、`assets/`、`config/`、`tests/`、`docs/`。
- 提交前必须通过本地规约 L1-L5 与评估系统门槛。
- 设计变更先更新对应 spec，再更新 plan，最后执行；所有变更都要在评估系统留档。
