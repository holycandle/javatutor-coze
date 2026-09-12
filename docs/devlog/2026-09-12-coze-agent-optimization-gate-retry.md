# 2026-09-12 优化候选门禁失败后自动返修 — 实施记录

> 计划：`docs/plan/2026-09-12-coze-agent-optimization-gate-retry-plan.md`
> 规格：`docs/spec/2026-09-10-coze-agent-code-optimization.md`（§6.1 改写、新增 §6.2、§7.1/§7.2 补记；review 复核后补 §8/§9/§11）
> 前置实现：`docs/devlog/2026-09-10-coze-agent-code-optimization.md`
> 姊妹件（同批联调）：`docs/plan/2026-09-12-coze-agent-test-mode-context-fix-plan.md`
> review：`docs/reviews/2026-09-12-coze-agent-optimization-retry-and-test-mode-review.md`（处置见 §8）

**跨仓**：前端 `javatutor/frontend` + coze `javatutor-coze`。后端未改动。

## 1. 做了什么

优化卡的编译/运行门禁失败后，前端**自动**把失败候选连同错误原文重新发给 agent，要求它交付修正版；
新候选**原地替换同一张卡片**（不新增气泡、不新增记录点），并自动重跑门禁。上限 2 次（= 最多 3 版候选），
耗尽 / 非最新卡 / 链路失败 → 回到现状：显示错误原文 + 「应用」禁用。

## 2. 决策（计划 §1 F1–F5）

| # | 决策 | 落点 |
|---|---|---|
| F1 | 门禁失败后前端自动重生成，**最多 2 次**（额外生成次数） | `MAX_OPT_RETRY` + `nextRetry` |
| F2 | 新候选**原地替换**卡片，不新增气泡 | `requestOptimizationRetry` 重写 `msg.text` |
| F3 | 只在**最新一条 assistant 消息**上返修 | `nextRetry` 的 `isLatest` |
| F4 | 只对**运行失败**返修，**传输失败**不返修（只重跑门禁） | `classifyGateFailure` + `nextRetry` 的 `transport` 分支 |
| F5 | 返修未产出可用 `replace` 块时**丢弃该次结果**，保留失败卡片 | `hasUsableReplace` |

## 3. 改动清单

### 3.1 前端（`javatutor/frontend`）

| 文件 | 改动 |
|---|---|
| `src/utils/optimization.js` | 新增 `MAX_OPT_RETRY` / `classifyGateFailure` / `nextRetry` / `retryLabel` / `buildRetryPrompt` / `hasUsableReplace`；新增对 `./editSuggestion.js::parseAssistantMessage` 的依赖（无环） |
| `src/utils/optimization.test.js` | 本文件用例 17 → **36**（+19：分类 4 / 返修决策 6 / 文案 1 / 模板 4 / F5 判据 4） |
| `src/stores/player.js` | 抽 `buildChatBody(question)` / `_runChat({question,onChunk,onStage,onError,signal})`；新增 `optRepair` / `optAbortController` / `optRegateNonce` 状态与 `requestOptimizationRetry` / `notifyGateOk`；`askQuestion` 首部追加抢占 abort |
| `src/components/OptimizationCard.vue` | 新增 `msgIndex` / `rev` / `repair` 三个 prop；`runGate` 失败分流上报；返修态文案；`watch([rev, optRegateNonce])` 重跑门禁 |
| `src/components/AiTutorPanel.vue` | 传 `:msg-index` / `:rev` / `:repair` |

### 3.2 coze（`javatutor-coze`）

| 文件 | 改动 |
|---|---|
| `src/graphs/javatutor/prompting/optimization.py` | `render_optimization_guidance()` 第二步之后追加「候选返修」段 |
| `tests/test_optimization_guidance.py` | +4 用例：返修段存在、replace 专用（不回退到第一步）、允许「不给块」、与前端模板标记互为字面包含（跨仓读前端文件） |

## 4. 与计划的偏差（3 处）

### 偏差 #1（重要）：`regate` 通路加了「按消息的闩」——计划原文会形成 fetch 风暴

计划 Task 3 的伪码是：

```js
if (d.action === 'regate') { this.optRegateNonce += 1; return }
```

配合 Task 4 的 `watch(() => [props.rev, store.optRegateNonce], ...)` → `runGate()`，在链路故障时会构成**无界循环**：

1. 卡片门禁失败（transport）→ 上报 → store 把 `optRegateNonce += 1`；
2. `watch` 触发该卡重跑门禁 → 仍然失败 → 再上报 → 非最新卡的 `nextRetry` 返回 `stop`，
   但**最新卡**返回 `regate` → `optRegateNonce += 1` → 回到第 2 步。

后端不通时每次重跑都会失败，而每次失败都会再次加一：立即形成 fetch 风暴（且 `nextRetry` 的 `transport`
分支无条件返回 `regate`，`attempt` 不参与判定，所以不存在自然终止）。

**处置**：把闩放在 store（它是上限的唯一持有者）：

```js
if (msg.optRegate) return
msg.optRegate = true
this.optRegateNonce += 1
```

并新增 `notifyGateOk(msgIndex)`：门禁通过时解闩，使**下一次**链路故障仍能自动重跑一次——
闩按「链路故障时段」生效，而不是按消息终生生效。行为上等价于计划的意图（「传输失败只重跑门禁、不烧返修次数」），
但**保证终止**。

**连带影响（须在验收时知道）**：计划手验 #4 第三条「恢复后端后重跑门禁成功」**不会自动发生**——
后端恢复后需要一次外部触发（用户重新运行 / 刷新页面）才会重跑门禁。自动重跑只有一次，且发生在故障当下。
理由：一次失败的 `fetch` 立刻重试几乎没有成功率，真正有用的是「不再重复烧 token」，而不是自动轮询。

### 偏差 #2：多了一个纯函数 `hasUsableReplace`

计划 §2 的改动清单只列了 5 个导出。F5 的判定（「返修结果里有没有可用的 `replace` 块」）需要复用既有解析器，
而 §0 要求「新增纯函数一律放 `utils/` 并配 vitest 用例」。故把它作为第 6 个导出放进 `utils/optimization.js` 并配 4 条用例，
而不是在 store 里写一个无测试的模块级函数。

### 偏差 #3：`buildRetryPrompt` 的措辞

计划给的模板里写的是「goal 与 target 保持不变」，其 Task 7 又要求 coze 侧断言「保持一致」。
二者是**各自文本内**的措辞，不是同一字符串：coze 引导段用「保持一致」，前端模板用「保持不变」。
跨仓握手靠的是首行两个标记（「上一版优化代码没有通过编译/运行校验」「上一版候选代码」），
它们**逐字一致**且被两侧测试各自硬编码——任一端改字，另一端必红。

## 5. 验证

| 项 | 命令 | 结果 |
|---|---|---|
| 前端基线（改动前） | `cd javatutor/frontend && npm test` | 29 文件 / **351** 用例通过 |
| 前端（改动后） | 同上 | 29 文件 / **370** 用例通过（+19） |
| 前端构建 | `npm run build` | ✓ built in 23.48s（无模板/编译错误） |
| coze 基线（改动前） | `cd javatutor-coze && uv run pytest -q` | **311** passed |
| coze（改动后） | `uv run pytest tests/ -q` | **315** passed |
| 后端 | 未改动 | 基线 `mvn test` = **123** 通过（改动前后一致，本件不追求改动）。※ 更正：本行初记为 124，是 `grep -c "@Test"` 把 `@TestPropertySource` 也数了进去；以 surefire `Tests run:` 为准，见姊妹件 `2026-09-12-coze-agent-test-mode-context.md` 偏差 #1 |

## 6. 已知局限

- **次数语义**：上限按「生成次数」计；被用户提问抢占的那一次**不退还**。若线上反馈额度太紧，
  再考虑「按结果计次」——需先有数据。
- **成本**：每张失败卡最多多消耗 2 次完整 agent 往返（含 RAG）。属有意代价。
- **不覆盖**：「门禁能跑但偷改语义」（spec §6.1 已知局限）仍未解决；未提供手动「再试一次」按钮。
- **`regate` 只自动重跑一次**（偏差 #1）：后端长时间不可用时不轮询（有意）。
- **`notifyGateOk` 是 `optRegate` 闩的唯一解扣点**：若某条消息的门禁从未成功过，其闩终生为真
  （该消息不会再自动重跑门禁）——影响仅限「不会自动重试」，不影响任何用户可见状态。

## 7. 手验清单（`npm run dev`；coze 侧需**重新发布 agent**）

1. 提问「优化这段代码」→ 方案卡 → 勾 1 项提交 → 得到 `replace` 卡。
2. **构造一次失败**：让 agent 产出一版有编译错的候选（例如手改卡片的 `plan.code` 为 `int x; x+1;` 后刷新）。
   - 卡片应显示「校验未通过，正在自动修正 1/2…」→ 随后原地变成新代码并显示「校验通过」，「应用」可用。
   - **对话里不新增气泡**；返修期间发新提问 → 返修被抢占、卡片保留失败态。
3. **耗尽**：连续两版都错 → 第 3 版仍错 → 显示错误原文 + 「应用」禁用（现状行为）。
4. **传输失败**：停掉后端 → 卡片失败 → **不**发起返修提问（`chatMessages.length` 不变）→
   自动重跑门禁一次（仍失败）。恢复后端后需一次外部触发（重新运行 / 刷新）才会重跑成功。
5. **旧卡不返修**：把第 1 步的失败卡变成非最新消息 → 不再自动返修。
6. **回归**：`patch` 卡与方案卡行为一字未变；应用/撤销/时间线记录点全部照旧；
   自由问答的消息条数、`isExplaining` 时序、中途 abort 三条路径与改动前一致（`askQuestion` 抽取的回归红线）。

## 8. review 处理（`docs/reviews/2026-09-12-coze-agent-optimization-retry-and-test-mode-review.md`）

review 共 1 P2 / 6 P3，均标注**不阻塞合并**。属本件的 5 项处置如下：

| # | 结论 | 处置 |
|---|---|---|
| P2-1 | 返修状态机（闩的终止性 / 解闩 / 上限 / 不重入）无回归网——这条路径**正是**偏差 #1 漏出无界循环的地方 | `stores/__tests__/player-optimization.test.js` 增 7 条（16 → **23**）：transport 闩不烧额度、`notifyGateOk` 解闩（nonce→2）、重跑通知量**按消息**、上限耗尽后停、F5 丢弃返修结果、飞行中不重入、被抢占的那一次不退还 |
| P3-6 + P3-3(b) | `optRegateNonce` 原为**全局量**：任一卡的链路故障会唤醒**所有**挂载中的 `replace` 卡一起重跑门禁（总请求上界 O(N²)） | 删掉全局 state，通知量改为 **`chatMessages[i].optRegateNonce`**（闩本来就按消息加），卡片经新增的 `regateNonce` prop 接收 ⇒ 只唤醒发起卡。P3-3(b)（未排除 `gate==='running'`）随之自然消失 |
| P3-3(a) | watcher 的 `props.repair` 守卫依赖「`msg.optRev++` 与 `finally{optRepair=null}` 同一同步段」 | 采纳**前半**（注释点明依赖 + 说明把它挪到任何 `await` 之后会静默跳过重跑）；未采纳后半（删守卫），理由见下 |
| P3-2 | 疑 `classifyGateFailure` 的 `httpStatus` 分支在唯一调用点不可观察，建议 spec §6.2 注明「非 2xx 由 `http()` 提前抛出」 | **前提不成立**（复核）：门禁走**裸 `fetch`**（`OptimizationCard.vue::runGate`，刻意绕开 `runCode` 用的 `http()` 封装），非 2xx 的 JSON body 会正常到达 `res.status` 判据。spec §6.2 改为注明**两条判据都可达**并列出三种到达形态；**未**写入原建议的表述（那会留下一句错话） |
| P3-4 | spec §8.3 / §9 / §11 未随实现同步；devlog 头部节号与 `git diff` 不符 | 已补：§8 第 3 条（本卡自动返修 + 三个兜底分支）、§9（返修状态机用例 + 两条守卫位置）、§11（两件 plan/devlog/review 登记）；本文件头部节号也改为实际同步的 §6.1/§6.2/§7.1/§7.2（+ 本次复核补的 §8/§9/§11） |

### 未采纳的两条建议（附理由）

- **P3-3(a) 后半「改为按 `rev` 变化无条件重跑」**：删掉守卫在今天**行为等价**（互斥情形不可达，`repair` 不在 watch 源里），
  但会把「返修进行中不重跑门禁」这条意图从**显式约束**降为隐式巧合——将来若有人把 `repair` 加进 watch 源，
  缺了它就会在返修进行中并发跑一次门禁。保留 + 注释的代价为零。
- **P3-2 建议的措辞**：它假定门禁经过 `http()` 封装，与实现不符（见上表）。已改写为描述**真实**的三条到达路径
  ——这才是读 spec 的人需要知道的事实。

### 复核后的测试数

| 项 | 命令 | 结果 |
|---|---|---|
| 前端（review 处理前） | `cd javatutor/frontend && npm test` | 29 文件 / **376** 用例通过 |
| 前端（review 处理后） | 同上 | 29 文件 / **383** 用例通过（+7，本次全部为 P2-1 的返修状态机用例） |
| coze（review 处理后） | `uv run pytest tests/ -q` | **327** passed（本次未改 coze 代码） |
| 后端（review 处理后） | `cd javatutor/backend && mvn test` | **126** 通过 / 0 失败（本次未改后端代码） |
