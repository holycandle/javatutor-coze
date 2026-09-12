# 2026-09-12 联调修复执行审查（优化候选自动返修 + 测试模式上下文）

> 审查对象：三仓未提交工作区——`javatutor-coze`（`feat/harness-react-loop`）+ `javatutor/frontend` + `javatutor/backend`
> 对应计划：`docs/plan/2026-09-12-coze-agent-optimization-gate-retry-plan.md`、`docs/plan/2026-09-12-coze-agent-test-mode-context-fix-plan.md`
> 实现记录：`docs/devlog/2026-09-12-coze-agent-optimization-gate-retry.md`、`docs/devlog/2026-09-12-coze-agent-test-mode-context.md`
> 同步规格：`docs/spec/2026-09-10-coze-agent-code-optimization.md`（§5/§6.1/§6.2/§6.3/§7.1/§7.2）、`docs/spec/2026-08-10-coze-agent-interface.md`（§1.1）、`docs/agent-collaboration-guide.md`

## 结论

两件实现与计划一致，职责切分（前端报事实 / coze 给语义）落地干净，**未发现阻断性问题**。

发现 **1 个 P2 / 6 个 P3**。P2 是「防 fetch 风暴闩 + 返修状态机」这条关键路径**无自动化测试**——
而它正是本次实现里唯一一个「先写错、靠实测才发现」的地方（devlog 偏差 #1），目前只靠注释与推理保护。
P3 里 P3-1 是我自己计划里的一个**事实性错误**（「本体同时被 Judge 消费」），已传播进 devlog 与两处代码注释，
建议一并改掉；其余为文档同步与边角健壮性，均不阻塞。

## 复现的验证（独立重跑，非引用 devlog）

| 项 | 命令 | 结果 |
|---|---|---|
| 前端 | `cd javatutor/frontend && npm test` | **376 passed / 29 files**，0 失败（与 devlog 一致） |
| coze | `cd javatutor-coze && uv run pytest tests/ -q` | **327 passed**，0 失败（与 devlog 一致） |
| 后端 | `cd javatutor/backend && mvn test` | **126 tests / 0 failures / 0 errors**（surefire 报告，口径见 §2.1） |
| 前端构建 | `npm run build` | 无模板/编译错误（devlog 记录 ✓ built in 23.48s，本轮未复跑） |

## 2. 用户提示的两点（逐条核实）

### 2.1 后端基线是 123 不是 124 —— 核实成立，且**还有一口计数陷阱**

`grep -c "@Test"` 的宽松计数会把 `ExecutionSnapshotControllerTest.java:20` 的 `@TestPropertySource` 数进来，
与 surefire 严格计数差 1。算术闭合：改动前宽松 124 / 严格 123，改动后宽松 127 / 严格 126，
`CozeServicePayloadTest` 由 3 → 6（`+3`），123 + 3 = 126 ✓；`mvn test` 的 11:04 一轮 0 失败 ✓。
两份 devlog 与 `AGENT.md` 的说法已一致。

**新增陷阱（本次审查实测发现，建议写进计数口径）**：`target/surefire-reports/` 里残留
`com.javatutor.instrumentation.MultiFileDebugSerializationTest.txt`（mtimes `08-24 23:05`，其**源文件已不存在**）。
因此「把 `*.txt` 里的 `Tests run:` 求和」会得到 **127**，比真实值多 1。即：

- 宽松 `grep -c "@Test"` ⇒ 多 1（`@TestPropertySource`）；
- 聚合 surefire `*.txt` ⇒ 多 1（陈旧报告文件，删除已删类的报告前一直如此）。

**唯一可信口径仍只有 `Tests run:` 汇总行**（devlog 偏差 #1 的结论正确，只是诱因不止一种）。建议在
`docs/devlog/2026-09-12-coze-agent-test-mode-context.md` 偏差 #1 补这一句，避免后人换一种方式再数错。

### 2.2 偏差 #5 的引导改写 —— 核实成立，改写正确

原计划 Task 8 的文案把 `[运行环境]`（前端报错入口预填块）当成模式事实的唯一来源，
而权威事实是 coze 侧注入的 `### 运行模式` packet。照原文落地会在自由问答上**误命中**规则 3
（无 `[运行环境]` ⇒ 要求模型「不要臆测模式」），让模型对明明已知的模式改口，正好废掉 F4。

落实版本的处置正确：`panels.py::render_run_mode_guide()` 现在写明**两个来源 + 优先级**
（「以系统注入的 `### 运行模式` 上下文为准」「`[运行环境]` 由报错入口预填、写于点击那一刻，可能已过期」
「**两者都没有**才算模式未知」），三情形判读与两条红线逐字保留
（`**不得**据此断言代码有语法/逻辑错误`、`不要建议用户「补一个 main」`），并新增
`RUN_MODE_HEADER in guide` 守卫（`tests/test_run_mode_context.py`）——一侧改名即红。
规则 1/2/3 的主语已由「运行环境」改为「模式事实」，语义自洽。

## 3. Findings

### P2-1：防 fetch 风暴闩与返修状态机无自动化测试（store 可测，非「无 DOM 环境」）

**位置**：`frontend/src/stores/player.js:397-448`（`requestOptimizationRetry` / `notifyGateOk`）；
可测性对照 `frontend/src/stores/__tests__/player-optimization.test.js`（pinia + fetch mock，已在跑）。

`requestOptimizationRetry` 承载了全部高风险判定：`attempt` 计次、`regate` 闩、抢占 abort、
F5 丢弃、原地重写、`optRev` 触发重跑。四个分支（`retry` / `regate` / `stop` / 返修在飞）**一条用例都没有**——
本次前端新增的 25 条用例全在 `utils/`（纯函数）与 `utils/errorEntry.js` 上。

计划 §0 的约束原文是「本仓**无 DOM 测试环境**，组件逻辑只能手验——请把可抽的判定都抽出来」。
**组件**确实不可测，但 **store 不是组件**：`player-optimization.test.js` 已经用
`setActivePinia(createPinia())` + `globalThis.fetch` mock 测过 `askGoalOptimization` / `runCode` / `applyCandidateRun`
等同样带 fetch 的 action，所以这条约束**不适用于 store action**——判定被抽进 `nextRetry` 之后，
剩下的状态机仍可测而没测。

**为什么单独提 P2**：devlog 偏差 #1 记的是「计划原文会构成无界循环，实测才发现」。
也就是说这类缺陷**已经从这里漏出去过一次**，而现在唯一的防线是 `player.js:418-424` 的注释。
用例最小集（4 条即可锁死）：

1. `kind='transport'` 连续两次上报 → 只 `optRegateNonce += 1` 一次、`optAttempt` 不变（闩生效 ⇒ 终止性有回归网）；
2. `notifyGateOk` 后同一消息可再自动重跑一次（闩按「故障时段」生效而非终生）；
3. `run` 失败两次后第三次 → `action='stop'`、`msg.text` 不被改写；
4. 返修在飞时再次上报 → 直接返回（`optRepair` 不重入）。

**建议**：补这 4 条；顺带把「被用户提问抢占的那一次不退还」也做成断言（当前只在 devlog 明示）。

### P3-1：「本体同时被 Judge 消费」是不成立的前提（**源自本计划 F3，已传播三处**）

**位置与证据链**：

1. `src/graphs/javatutor/prompting/ontology.py:57-66`：`build_judge_grounding_block()` 只读
   `field_schema` + `modules` 两组，**不含** `user_guides`；
   `tests/test_judge.py:18-24` 正是这么断言的（只断言 `stackFrames` / `堆面板` / `JavaTutor 领域本体`）。
2. `user_guides` 的唯一消费者是 `panels.py:145-157::render_usage_guide()`，
   其唯一调用点是 `harness/propose.py:43::_main_system_prompt()` —— **只给主 Agent**。
   （`build_ontology_block()` 走的是另一条路：`prompts.py:157` 的 `build_system_prompt(intent)`，
   同样不含 `user_guides`。）
3. 但下列三处把它写成了「Judge 也读」：
   - `docs/devlog/2026-09-12-coze-agent-test-mode-context.md:31`（F3 行「本体 `user_guides`（知识、Judge 读）」）
     与 `:142`（§6「本体该条目同时被主 Agent 与 Judge 消费」）；
   - `src/graphs/javatutor/prompting/panels.py:165`（`render_run_mode_guide` docstring「本体…同时被 Judge 消费」）；
   - `tests/test_run_mode_context.py:106`（分节注释「5. 本体（知识侧，Judge 也读）」）。
4. 溯源：这条前提出自我写的计划（F3 行「知识，Judge 也读」、Task 8「本体同时被 Judge 消费，启发式规则放进去会污染判定依据」），
   执行侧是照抄，不是新引入。

**影响**：设计与实现**无需改**——把「判读启发式 + 两条红线」留在系统提示、把领域知识放进本体，仍然是对的切分。
错的是理由：本体该条目**只服务主 Agent**，所以「不得写只对一侧成立的表述」这条约束失去依据（保留无害，但别再用它论证）。
真正的风险是反过来：**Judge 侧唯一能看到运行模式事实的通道是 `build_facts_block` 的那一行**
（`prompting/contexts.py:129-141`，本件已正确加上）——若后人相信「Judge 读本体」，就可能误以为去掉 facts 行也无妨，
那才会让评审把「当前是默认模式」判成幻觉。

**建议**：把三处措辞改为「本体 `user_guides` 只经 `render_usage_guide()` 进主 Agent 系统提示；
Judge 的地基只含 `field_schema` + `modules`，故运行模式事实必须靠 `build_facts_block` 那一行走通」，
并在本计划 F3 行加一句订正（计划已执行，按 AGENT.md「执行后补记」处理）。

### P3-2：`classifyGateFailure` 的 `httpStatus` 分支在唯一调用点不可达；spec §6.2 判据表列了观察不到的量

**位置**：`frontend/src/utils/optimization.js::classifyGateFailure`、
`frontend/src/components/OptimizationCard.vue:196-206`、`frontend/src/utils/http.js:37-45`。

`http()` 在 `!response.ok` 时**先抛** `Error('HTTP <status>')`（http.js:37-45），
所以 `runGate` 里能走到 `reportFailure({ httpStatus: res.status })` 的响应必然是 2xx —— `res.status >= 400` **永不成立**，
非 2xx 一律经 `catch` 以 `thrown: true` 落到 'transport'。

**结论：行为正确**（两条路径都归 'transport'，与 F4 意图一致；`httpStatus` 分支作为纯函数契约仍是合理的防御），
但 `docs/spec/2026-09-10-coze-agent-code-optimization.md:210` 的判据表写了「`fetch` 抛异常，**或 `res.status >= 400`**」，
其中第二个量在实现里不可观察——读 spec 的人会以为存在两条独立的可观测判据。建议在表里注明
「非 2xx 由 `http()` 提前抛出，实际以抛异常形态到达；`httpStatus` 分支为防御性保留」。

### P3-3：`watch` 的 `props.repair` 守卫依赖「`finally` 同步清空」的时序，且未排除 `gate==='running'`

**位置**：`frontend/src/components/OptimizationCard.vue:279-282` ↔ `frontend/src/stores/player.js:441-447`。

**(a) 依赖时序（当前不可达，但很脆）**：store 在 `msg.optRev++`（:441）之后**同步**执行
`finally { this.optRepair = null }`（:445），而 watcher 是 pre-flush 队列，回调必然晚于该赋值 ⇒
回调里 `props.repair` 已为 null ⇒ 重跑门禁得以执行。反之若 `optRepair = null` 将来被挪到任何 `await` 之后，
watcher 会静默跳过 ⇒ 卡片显示**新**候选却挂着**旧**的「校验未通过」且「应用」禁用，且不会再有自动重跑。
（即：`props.repair` 这个守卫在重跑通路上其实是多余的——它挡住的情形不该存在。）
建议在 watcher 注释里点明这条依赖，或改为按 `rev` 变化无条件重跑（`applied` / `targetBlocked` 守卫已足够）。

**(b) 未排除 `gate === 'running'`**：`optRegateNonce` 是可被**别的卡**触发的全局量，
若本卡门禁正在飞行中（`gate==='running'`，`applied/repair` 均为假）而另一卡上报传输失败，
本卡会**并发发起第二次门禁**，两个响应都可能写 `gateSnapshot`。因 props.plan 未变、两次结果语义相同，
实际危害仅是一次多余请求与潜在的后写覆盖（无害）。若一并做 P3-6 的按消息 nonce，此问题自然消失。

### P3-4：spec §8/§9/§11 未随实现同步；devlog #1 头部声称「§9 补记」与实际不符

**位置**：`docs/spec/2026-09-10-coze-agent-code-optimization.md:326`（§8 验收标准第 3 条）、
`:336-342`（§9 测试）、`:357`（§11 文档登记）；`docs/devlog/2026-09-12-coze-agent-optimization-gate-retry.md:4`。

§6.1/§6.2/§6.3/§7.1/§7.2 都已同步（含把旧 devlog 对「§6.2 = 应用与撤销」的引用改为 §6.3，跨件回指处理得当），
但：

- §8 第 3 条仍是旧行为「候选跑不通 → 显示错误、「应用」禁用」，未提自动返修（只剩「耗尽后」那半句成立）；
- §9 测试清单未列返修守卫与 `test_run_mode_context.py`，而 devlog #1 头部写的是「§6.1 改写、新增 §6.2、**§7.1/§7.2/§9 补记**」——
  `git diff` 里 §9 一行未动（末个 hunk 落在 §7.2）；
- §11 文档登记未列本次两份 plan/devlog。

**建议**：§8 第 3 条补「（最新一条消息上的候选会自动返修，最多 2 次；耗尽/非最新/传输失败见 §6.2）」；
§9 补两条守卫位置；§11 补登记；devlog 头部改成实际同步的节号（§5/§6.1/§6.2/§6.3/§7.1/§7.2）。

### P3-5：本体条目把「块注释抽取」规则写了两遍

**位置**：`assets/knowledge/javatutor_domain_ontology.json` 测试模式条目 `steps[4]` 与 `note`。

`render_usage_guide()`（panels.py:153-157）既拼 `steps` 又拼 `note`，而两处都写了
「测试模式下会把块注释里的类抽取为额外源文件」。结果同一事实在主 Agent 系统提示里出现两次。
`note` 的定位是「两种模式对比」的总结，重复可接受；若要精简，把 `steps[4]` 收成操作口径、
把「既定行为不是编译错误」这层判断留在 `note`。

### P3-6：`optRegateNonce` 是全局量 —— 一次链路故障会重跑所有已挂载 `replace` 卡的门禁

**位置**：`frontend/src/stores/player.js:30-32`（state）、`:418-424`（bump）、`OptimizationCard.vue:279-282`（watch）。

闩按**消息**加（`msg.optRegate`），而通知量是**全局**的：任一张卡遇到链路故障 ⇒ `optRegateNonce++` ⇒
所有未 `applied`/未返修的 `replace` 卡一起重跑门禁。全链路不可用时，各卡依次加闩并各 bump 一次，
总请求数上界为 `O(N²)`（N = 已挂载的 replace 卡数，实际通常为 1，且每卡至多一次/故障时段 ⇒ **确定终止**，无风暴）。
改为按消息的 nonce（`optRegateFor: {msgIndex, n}` 或 `msg.optRegateNonce`）即可精确到发起卡，同时消掉 P3-3(b)。

## 4. 已核实无误（抽样，供后续变更参考）

- **闩的终止性**：第二次传输失败在 `player.js:421` 命中 `msg.optRegate` 直接返回，不 bump ⇒ watcher 不再触发，无发散。
- **`regate`/`retry` 不会解引用空消息**：二者只在 `isLatest`（要求 `msg` 为真且是最后一条 assistant）时可达。
- **运行模式透传**：`CozeService.addRunMode`（:106-111）在 runId 与 legacy **两个分支**都调用，
  两键同层、同时出现或同时缺失（`null`/`""`/`"   "` 均省略）；`CozeServicePayloadTest` 6 用例覆盖含「0 有意义不得省略」；
  `ExplainRequest` / `CozeAIController` 透传与计划一致；`/api/run` 的 body 未动（回归红线）。
- **coze 落点**：`_parse_json_dict` 解析失败退 0；packet 仅 `run_mode` 非空时注入（缺失零行为变化）、
  `score=0.9`/`section=Evidence`、能穿 `structure()` 进 `[Evidence]` 段；`build_facts_block` 同条件加行。
- **`askQuestion` 抽取后对外行为**：消息条数、`isExplaining` 时序、`explainError`/`explainStage`、abort 语义均保留；
  新增的首部 `optAbortController.abort()` 不会搁浅返修（空提问发不出去：发送按钮已含 `!chatDraft.trim()` 禁用）。
- **「不新增消息/不新增记录点」**：返修只改 `msg.text`，`chatMessages.length` 与 `timeline` 不变（时间线下标语义未被破坏）。
- **跨仓握手**：`buildRetryPrompt` 的两个标记与 coze「候选返修」段互为字面包含，两侧测试各自硬编码（一端改字另一端必红）；
  `FRONTEND_OPTIMIZATION` 路径不存在时 `pytest.skip`——本机存在，比对**实际执行**（非跳过）。
- **旧记录订正**：`docs/devlog/2026-09-10-coze-agent-code-optimization.md:116` 对 §6.2→§6.3 的回指已同步。
- **`EL/projects/` 下的本体副本**：非 git 目录、AGENT.md 落后于 harness 批次、内容为 GBK 乱码，判定为**陈旧快照副本**，
  非活跃消费方，**无需同步**（记录在此以免后人重复排查）。

## 5. 未覆盖

- **浏览器手验**：两份 devlog 的手验清单（共 12 条）**一条都未执行**，包含 devlog #1 手验 #4 那条**行为变更**
  （后端恢复后不会自动重跑门禁，需外部触发）——发布前应按清单实跑。
- **coze 侧重新发布 agent**：两份 devlog 均已注明，未验证。
- **继承自 harness review 的待办**：Task 15 的 e2e Judge 均分对比（含 `critic_skipped` 预期上升）、
  前端对 `decision_trace.verification` 的消费。

## 6. 处理建议（按优先级）

| # | 项 | 建议 |
|---|---|---|
| 1 | P2-1 | 补 `player-optimization.test.js` 4 条 store 用例（闩终止性 / 解闩 / 耗尽 stop / 不重入） |
| 2 | P3-1 | 改三处措辞 + 订正计划 F3 行（本件自曝，非执行方引入） |
| 3 | P3-4 | 同步 spec §8.3 / §9 / §11，订正 devlog #1 头部的节号 |
| 4 | P3-2 / P3-6 | spec §6.2 判据表注明 `httpStatus` 分支不可观察；评估是否把 nonce 收到消息级（顺带消 P3-3(b)） |
| 5 | P3-3 / P3-5 | 补时序注释 / 精简本体重复文案（不阻塞） |

以上均**不阻塞合并**：P2 是测试覆盖缺口（实现经逐步推演确认正确），P3 全部为文档同步与边角健壮性。
