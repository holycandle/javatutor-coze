# 执行计划：测试模式误诊修复（前端补运行上下文 + coze 补知识）

> 依据：2026-09-12 联调反馈「测试模式下用户没有输入用例时 agent 诊断错误（若输入用例会进入测试模式，后端抽取注释里的 `TreeNode` 类而正常执行），说明 agent 对测试模式的功能还不清楚」+ 同日 `/grilling` 收敛（§1 即决策记录）。
> **跨三处**：前端 `javatutor/frontend` + 后端 `javatutor/backend`（payload 透传）+ coze `javatutor-coze`。
> 关联：`docs/spec/2026-08-10-coze-agent-interface.md`（**必须同步** §1 请求契约，见 Task 10）；
> `docs/spec/2026-09-10-coze-agent-code-optimization.md`（同步 §5 报错入口的预填文本）；
> `docs/plan/2026-09-12-coze-agent-optimization-gate-retry-plan.md`（同批联调的姊妹件；两件共用 `stores/player.js` 的 `buildChatBody` 抽取，见 §0.1）。
> 前置实现：`docs/devlog/2026-08-30-multifile-whole-project.md`、`docs/devlog/2026-09-10-coze-agent-code-optimization.md`。

## 0. 全局约束（务必遵守）

- **不做任何 git 操作**（不 `git add`/`commit`/`push`/`stash`/`checkout`/`branch`）。读 `git status`/`diff` 可以。
- 前端**不触碰** `javatutor/frontend/src/backup-20260807/`（备份副本）。
- **javatutor-coze 不修改外壳**（`.coze`/`scripts/`/`src/main.py`/`src/storage/`/`src/utils/`）——本件改动只落在 `src/graphs/`、`assets/`、`tests/`、`docs/`。
- 基线（改动前先跑一遍确认）：前端 `npm test` = **29 文件 / 351 用例**；coze `uv run pytest -q` = **311 通过**（本机实测 2026-09-12）。后端 `cd javatutor/backend && mvn -q test` **先跑一遍记录通过数**（本件未实测，勿照抄数字）。
- **向后兼容是硬要求**：`run_mode` / `test_case_count` **缺失时行为与现状完全一致**（coze 侧不注入任何运行模式上下文，不报错）。旧前端 / 其它调用方不受影响。
- **职责切分（F2）**：**事实**（本次运行是哪种模式）由前端传；**语义**（两种模式各要求什么）只写 coze 侧知识。前端**不写**任何 JavaTutor 内部语义到提问文本里。
- 新增纯函数一律放 `utils/` 并配 vitest 用例（本仓**无 DOM 测试环境**，组件逻辑只能手验）。
- **不做**：不新增 agent 工具；不改 `bind_tools`/工具协议；不动 `patch`/`options`/`replace` 块形态；不在前端做「测试模式未激活」的运行前拦截（见「遗留」）。

### 0.1 依赖与执行顺序

- 姊妹件（门禁失败自动返修）的 Task 1 从 `askQuestion` 抽出 `buildChatBody()`。本件 Task 1 在**同一个函数**上追加 `mode` / `testCaseCount` 两个字段。
- **先执行者落抽取，后执行者按已抽取形态接续**——不是冲突改动，但必须按此顺序落地。

## 1. 已收敛的决策

| # | 决策 | 说明 |
|---|---|---|
| **F1** | 前端把「本次运行是什么模式」**随每次提问**送出去 | `mode: 'test'\|'default'` + `testCaseCount: <int>`，走 `/api/ai/chat` body → 后端透传 → coze 落 state。**每次**提问都带，不只在报错入口。 |
| **F2** | 报错入口的预填文本增加 `[运行环境]` 事实块；**语义仍留在 coze** | 前端只陈述「默认模式（测试模式未激活：已保存用例 0 条）」这类事实；「默认模式需要 main / 测试模式会抽取注释类」由 coze 知识与引导给出。 |
| **F3** | coze 侧**知识 + 引导**双补 | 本体 `user_guides["测试模式"]` 补激活条件与抽取规则（知识，只经 `render_usage_guide()` 进主 Agent）；新增「运行模式判读」引导段（诊断启发式，**不进本体**）。<br>**订正（review P3-1，执行后补记）**：本行原文作「知识，Judge 也读」，**不成立**——`build_judge_grounding_block()` 只读 `field_schema` + `modules`，不含 `user_guides`；该条目唯一消费者是主 Agent 系统提示。取舍（知识进本体 / 判读启发式留系统提示）不变，理由换成「领域知识 vs 诊断口径」。 |
| **F4** | 运行模式作为**确定性上下文**注入，不靠模型自己去 state 里翻 | 主 Agent 的 `context_built` 增一个 `### 运行模式` packet；评审核对用的 facts 块同增一行。 |

---

## 2. 改动清单

| # | 仓 | 文件 | 改动 |
|---|---|---|---|
| 1 | 前端 | `javatutor/frontend/src/stores/player.js` | `buildChatBody` 增 `mode` / `testCaseCount` |
| 2 | 前端 | `javatutor/frontend/src/utils/errorEntry.js` | `buildFixPrompt(message, ctx)` 增 `[运行环境]` 块 |
| 3 | 前端 | `javatutor/frontend/src/utils/errorEntry.test.js` | 上述用例（**测试先行**） |
| 4 | 前端 | `javatutor/frontend/src/components/GlobalStatus.vue` | `prefillFix()` 传 ctx |
| 5 | 后端 | `javatutor/backend/.../model/ExplainRequest.java` | 新增 `testCaseCount`（`mode` 已有） |
| 6 | 后端 | `javatutor/backend/.../controller/CozeAIController.java` | `chat` 把 `mode` / `testCaseCount` 传给 `streamExplain` |
| 7 | 后端 | `javatutor/backend/.../service/CozeService.java` | `streamExplain` 增 2 参；`buildAgentPayload` 增 `run_mode` / `test_case_count` |
| 8 | 后端 | `javatutor/backend/src/test/.../service/CozeServicePayloadTest.java` | 上述 payload 键用例（**测试先行**） |
| 9 | coze | `src/graphs/javatutor/state.py`、`nodes.py` | `run_mode` / `test_case_count` 落 state |
| 10 | coze | `src/graphs/javatutor/context_builder.py` | `gather()` 增 `### 运行模式` packet |
| 11 | coze | `src/graphs/javatutor/prompting/panels.py` | 新增 `render_run_mode_guide()` |
| 12 | coze | `src/graphs/javatutor/harness/propose.py` | `_main_system_prompt()` 接入该引导 |
| 13 | coze | `src/graphs/javatutor/prompting/contexts.py` | `build_facts_block` 增运行模式一行 |
| 14 | coze | `assets/knowledge/javatutor_domain_ontology.json` | 扩充 `user_guides["测试模式"]` |
| 15 | coze | `tests/test_run_mode_context.py` | **新建**守卫（payload→state→packet→引导→本体） |
| 16 | 两仓 | `docs/devlog/2026-09-12-coze-agent-test-mode-context.md` | **新建**实施记录 |
| 17 | coze | `docs/spec/2026-08-10-coze-agent-interface.md` §1、`docs/spec/2026-09-10-coze-agent-code-optimization.md` §5 | 契约与预填文本同步 |

### 0.1 诊断（为什么这么改；已核实，勿再重开）

**问题「测试模式下 agent 误诊」的成因链：**

| # | 事实 | 位置 |
|---|---|---|
| D1 | 前端 `testMode` 是**派生值**：`saveTestCases(cases)` 时 `testMode = cases.length > 0`。**没有保存用例 ⇒ `testMode === false`**，用户此时仍停留在「测试」面板里，主观上认为自己在测试模式。 | `player.js:610-611` |
| D2 | `runCode` 仅在 `testMode === true` 时才带 `mode:'test'` + `testCases`；否则以默认模式提交。**于是「测试面板打开但没输入用例」= 静默按默认模式运行**。 | `player.js:139-142` |
| D3 | 后端只认 `mode`：`isTestMode = "test".equals(request.getMode())`。测试模式才生成 `Launcher` 入口（`generateLauncherClass`）并**从注释抽取额外源文件**（`extractCommentedClasses(request.getCode())`，仅在 `if (isTestMode)` 内）。 | `RunController.java:514`、`:523-527`、`:540-541`、`:547` |
| D4 | 默认模式入口类 = 用户代码里的类，**必须有可执行的 `main`**；`class Solution` + 注释里的 `TreeNode` 两者都拿不到 → 编译/运行失败。 | `RunController.java:517`、`:547-548` |
| D5 | 抽取器只认块注释里的 `public class X {...}`（`/\*.*?\*/` + 花括号配对），且**只在测试模式**执行。 | `RunController.java:708-730` |
| D6 | `/api/ai/chat` **完全不携带运行模式**：`CozeAIController.chat` 传 `compileError=null`、`intent=null`，**没有** `mode`（`ExplainRequest` 里**已有** `mode` 字段，只是没往下传）。 | `CozeAIController.java:76-100` |
| D7 | 后端 → coze 的 payload 是**显式白名单**，不在名单里的字段到不了 coze。 | `CozeService.buildAgentPayload` |
| D8 | coze 侧 payload→state 的映射同样显式（`_parse_json_dict`），且主 Agent 的 `context_built` 由 `context_builder.gather()` 逐 packet 组装——**没有**任何运行模式的 packet。 | `nodes.py:111-160`、`context_builder.py:66-145` |
| D9 | 报错入口预填的提问**只有错误原文**（`buildFixPrompt`），agent 拿不到任何模式线索——这正是「诊断错误」的直接原因。 | `utils/errorEntry.js::buildFixPrompt` |
| D10 | 本体里 `user_guides` 的「测试模式」条目**只讲操作步骤**，没写「激活条件是用例 ≥1」也没写「注释里的类只在测试模式被抽取」。该条目经 `render_usage_guide()` 注入主 Agent 系统提示。 | `javatutor_domain_ontology.json:115-124`、`panels.py:145-162`、`propose.py:37-44` |

结论：**agent 缺的不是推理能力，是事实**（这次跑的是哪种模式）**和知识**（两种模式的差异）。
只补其中一半都不够——补事实而不知语义，仍会把「没有 main」当成代码错；补语义而不给事实，仍不知道这次是哪一种。

---

# Phase A — 前端：把运行模式送出去

## Task 1：`stores/player.js` — `buildChatBody` 增字段（**测试先行**）

- 若姊妹件已落 `buildChatBody()` 抽取，则只在该函数里加；否则先做抽取（两件共用，实现见姊妹件 Task 2）。
- body 增加：

  ```js
  mode: this.testMode ? 'test' : 'default',
  testCaseCount: this.testCases.length,
  ```

- **缺省即默认模式**：`this.testMode` falsy 时明确送 `'default'`（不是省略），这样 coze 侧能区分「默认模式」与「旧客户端没带」。
- **回归红线**：`/api/run` 的 body **不动**（那里 `mode` 缺省表示默认模式，且 `testCases` 是数据不是计数）。

## Task 2：`utils/errorEntry.js` — `buildFixPrompt(message, ctx)`（**测试先行**）

```js
/**
 * 报错入口要预填的提问文本（只预填、不发送）。
 * ctx 只承载**事实**（F2）：本仓不写任何 JavaTutor 运行语义——语义在 coze 侧知识与引导里。
 * @param {string} message 错误原文
 * @param {{mode?: 'single'|'multi', fileCount?: number, entryFile?: string,
 *          testMode?: boolean, testCaseCount?: number}} [ctx]
 *   缺省时退化为旧行为（只有错误原文 + 旧首行），保证既有调用与既有用例不变。
 */
export function buildFixPrompt(message, ctx) {
  const lines = ['我的代码运行报错了，请帮我看看怎么修正：']
  const env = runEnvLines(ctx)
  if (env.length) lines.push('', '[运行环境]', ...env)
  lines.push('', '[错误原文]', message || '')
  return lines.join('\n')
}

/** 运行环境事实行；ctx 缺失/字段缺失时不产出该行（向后兼容）。 */
export function runEnvLines(ctx) {
  if (!ctx) return []
  const out = []
  if (ctx.mode === 'multi') {
    out.push(`- 文件模式：多文件（${Number(ctx.fileCount) || 0} 个文件，主入口 ${ctx.entryFile || '未指定'}）`)
  } else if (ctx.mode === 'single') {
    out.push('- 文件模式：单文件')
  }
  if (typeof ctx.testMode === 'boolean') {
    const n = Number(ctx.testCaseCount) || 0
    out.push(
      ctx.testMode
        ? `- 运行模式：测试模式（已保存用例 ${n} 条）`
        : `- 运行模式：默认模式（**测试模式未激活：已保存用例 ${n} 条**）`,
    )
  }
  return out
}
```

### 测试（`errorEntry.test.js`，**先写**）

- `buildFixPrompt(msg)`（**旧签名**）→ 仍含首行与错误原文，**含 `[错误原文]` 小节**；无 `[运行环境]`。
- `buildFixPrompt(msg, {mode:'single', testMode:false, testCaseCount:0})` → 含「默认模式」「测试模式未激活」「已保存用例 0 条」。
- `{mode:'multi', fileCount:3, entryFile:'Main.java', testMode:true, testCaseCount:2}` → 含「多文件（3 个文件，主入口 Main.java）」「测试模式（已保存用例 2 条）」。
- ctx 字段部分缺失（只给 `testMode`）→ 只出运行模式行，不抛异常。
- `[[ ]]` 高亮标记：若前端 markdown 不认 `**`，改用纯文本「（测试模式未激活：已保存用例 0 条）」——**以现有 markdown 渲染器为准确认后再定**（`utils/simpleMarkdown.js`）。

## Task 3：`GlobalStatus.vue` — `prefillFix()` 传 ctx

```js
function prefillFix() {
  store.focusChatWithDraft(buildFixPrompt(store.lastRunError?.message, {
    mode: store.mode,
    fileCount: store.multiState.files.length,
    entryFile: store.multiState.entryFile || '',
    testMode: store.testMode,
    testCaseCount: store.testCases.length,
  }))
}
```

（`GlobalStatus.vue:58-60`。其余逻辑一行不动。）

---

# Phase B — 后端：payload 透传

## Task 4：`CozeServicePayloadTest.java`（**测试先行**）

新增断言（沿用该文件既有的构造方式）：

- 传 `runMode="test"`、`testCaseCount=2` → payload 含 `run_mode: "test"` 且 `test_case_count: 2`。
- 传 `runMode="default"`、`testCaseCount=0` → payload 含 `run_mode: "default"` 且 `test_case_count: 0`（**0 是有意义的值，不得省略**）。
- 传 `runMode=null`/空 → payload **不含** `run_mode` 也不含 `test_case_count`（向后兼容，D7）。
- runId 分支与 legacy 分支**都要**覆盖（两条分支各自组装 payload）。

## Task 5：`ExplainRequest.java` + `CozeAIController.chat` + `CozeService`

- `ExplainRequest`：新增 `private int testCaseCount;` + getter/setter（`mode` 已有）。
- `CozeAIController.chat`：在现有 `streamExplain(...)` 调用**末尾追加** `request.getMode(), request.getTestCaseCount()`。
- `CozeService.streamExplain(...)`：签名末尾追加 `String runMode, int testCaseCount`（与既有 14 参风格一致，不引入新 DTO——保持最小 diff）；在 `buildAgentPayload(...)` 调用处透传。
- `CozeService.buildAgentPayload(...)`：签名末尾追加同两名参，在 **runId 分支与 legacy 分支**各加：

  ```java
  if (runMode != null && !runMode.isBlank()) {
      agentPayload.put("run_mode", runMode);
      agentPayload.put("test_case_count", testCaseCount);
  }
  ```

  两个键**同时出现或同时不出现**（D7：coze 侧据此判定「未知」而非「默认」）。
- 另两处 `streamExplain` 调用（`CozeService.java:237`、`:252`，非 chat 路径）传 `null, 0`。

---

# Phase C — coze：事实落 state、知识进本体、引导进提示词

## Task 6：`state.py` + `nodes.py::_parse_json_dict`

- `state.py`：新增 `run_mode: str`（`"test"|"default"|""`，缺失为空串）与 `test_case_count: int`（缺失为 0），各带中文 docstring 说明来源与缺失语义。
- `_parse_json_dict`：读 `data.get("run_mode", "")` 与 `data.get("test_case_count", 0)`，写进返回 dict（**不改任何既有键**）。

## Task 7：`context_builder.py::gather()` — `### 运行模式` packet（F4）

仅当 `state.get("run_mode")` 非空时追加（缺失 ⇒ 零行为变化）：

```python
run_mode = state.get("run_mode") or ""
if run_mode:
    n = int(state.get("test_case_count") or 0)
    label = f"测试模式（已保存用例 {n} 条）" if run_mode == "test" else f"默认模式（测试模式未激活：已保存用例 {n} 条）"
    packets.append(ContextPacket(
        "### 运行模式\n"
        f"- 本次运行提交给后端的模式：{label}\n"
        "- 「找不到某个类 / 没有 main / 无法执行入口」这类报错与模式强相关，"
        "判读规则见系统提示的「运行模式判读」段。",
        relevance_score=0.9, metadata={"section": "Evidence"},
    ))
```

- 位置：紧邻既有 `### 当前执行位置` packet（同属 Evidence、score 0.9）。
- **同一事实只渲染一次**：packet 说值，系统提示说规则，互不重复。

## Task 8：`prompting/panels.py::render_run_mode_guide()` + 接入 `_main_system_prompt()`

新增（**不进本体**——本体是领域知识，判读启发式属诊断口径，混进去会让「哪种模式」的知识带上使用者的判断，见 F3）：

> **订正（review P3-1，执行后补记）**：本行原文的理由写作「本体同时被 Judge 消费，启发式规则放进去会污染判定依据」，
> 该前提**不成立**（Judge 地基不含 `user_guides`）。结论不变，理由已按 F3 订正。

```
## 运行模式判读（判错会直接误诊）

JavaTutor 有两种运行模式，**只有在「运行环境」里写明的那种模式才成立**：

- **默认模式**：直接执行用户代码的入口类，**必须存在可执行的 main**。
  代码里若只有一个 `class Solution`（或把辅助类写在注释里），默认模式下必然报
  「找不到 main / 找不到符号 X」——**这不等于代码写错了**，很可能只是没进测试模式。
- **测试模式**：后端会（1）生成 `Launcher` 作为入口，不需要用户代码有 main；
  （2）把代码**块注释**里的 `public class X { ... }`（如 `TreeNode`）抽取成额外源文件。
  因此「注释里定义的类在测试模式下可用、默认模式下不可用」是既定行为，不是编译错误。

规则：
- 看到「运行环境」写着**默认模式（测试模式未激活）**时，**不得**据此断言代码有语法/逻辑错误；
  应先说明「当前以默认模式执行，测试模式未激活」，并指出激活办法（在「测试」面板输入用例后点「保存」）。
- 看到**测试模式**时，不要建议用户「补一个 main」。
- 「运行环境」缺失（旧客户端）时，**不要臆测模式**；按错误原文本身判断，必要时问用户当时用的是哪种模式。
```

在 `propose.py::_main_system_prompt()` 的 `render_optimization_guidance()` 之后插入 `render_run_mode_guide()`。

## Task 9：`contexts.py::build_facts_block` — 增运行模式一行（F4）

在既有 `编译错误：...` 一行之后、`has_steps` 判断之前插入（缺失时跳过）：

```python
if state.get("run_mode"):
    n = int(state.get("test_case_count") or 0)
    lines.append("运行模式：" + (f"测试模式（用例 {n} 条）" if state["run_mode"] == "test"
                               else f"默认模式（测试模式未激活，用例 {n} 条）"))
```

理由与既有 `编译错误` 行相同：评审核对回答里的断言时，必须能看到该断言所依赖的事实，否则会误判为幻觉（本文件的既有注释即为此教训）。

## Task 10：本体 `user_guides["测试模式"]` 扩充（F3）

在 `javatutor_domain_ontology.json:115-124` 的该条目上改（**只动这一条**）：

- `steps` 第 3 步改为：`"输入用例后「保存」，激活测试模式（**必须≥1 条用例**：0 条时 testMode 仍为假，点「运行」会以默认模式执行）"`
- `steps` 追加一条：`"若辅助类（如 `TreeNode`）写在注释里：测试模式下会被自动抽取，默认模式下不会"`
- `note` 改为：`"测试模式用于验证多组输入输出，激活后 runCode 以 mode:'test' 提交。两种模式对代码的要求不同：默认模式需要入口类/main；测试模式由后端生成 Launcher 入口，并会把代码块注释中的 public class 抽取为额外源文件。"`

> **订正（review P3-5，执行后补记）**：末句「并会把代码块注释中的 public class 抽取为额外源文件」与 `steps` 新增的那条说了同一件事，
> 而 `render_usage_guide()` 把 `steps` 与 `note` 都拼进系统提示 ⇒ 同一事实出现两次。
> 落地版把**机制**留在 `steps`（操作口径）、`note` 只留**判断口径**（两模式要求对比 + 「这是既定行为，不是编译错误」）。

该条目经 `render_usage_guide()`（`panels.py:145-162`）进入**主 Agent** 系统提示——**改文案即改 agent 的行为口径**。

> **订正（review P3-1，执行后补记）**：本行原文作「并被 Judge 的地基注入复用……不得写只对一方成立的表述」，
> 前半句**不成立**：`build_judge_grounding_block()` 只含 `field_schema` + `modules`，不含 `user_guides`。
> 真正需要留意的是反向推论——**Judge 侧唯一能看到运行模式事实的通道是 `contexts.build_facts_block()` 的那一行**，
> 删掉它评审就会把「当前是默认模式」判成幻觉。

## Task 11：`tests/test_run_mode_context.py`（**新建**）

| 用例 | 断言 |
|---|---|
| payload → state | `_parse_json_dict({"run_mode":"test","test_case_count":2, ...})` → state 两字段正确；缺失 → `""` / `0` |
| packet 出现 | `gather({"run_mode":"test","test_case_count":2})` 产出文本含 `### 运行模式` 且含「测试模式（已保存用例 2 条）」 |
| packet 缺失 | `gather({})` 产出文本**不含** `### 运行模式`（向后兼容） |
| packet 默认模式文案 | `run_mode="default"`、`0` → 含「测试模式未激活」「已保存用例 0 条」 |
| facts 块 | `build_facts_block` 在带 `run_mode` 时含「运行模式：」；不带时**不含** |
| 引导段 | `render_run_mode_guide()` 含三种模式判读 + 「不得据此断言代码有语法/逻辑错误」+ 「不要臆测模式」 |
| 本体 | 该 `user_guides` 条目的 `steps` 含「必须≥1 条用例」、`note` 含「默认模式需要入口类/main」与「public class」 |
| 注入 | `_main_system_prompt()` 含 `render_run_mode_guide()` 的首行（防止接线漏掉） |

---

# Phase D — 验证

## Task 12：跑测试 + devlog

- 前端：`cd javatutor/frontend && npm test`（期望 351 + 新增，0 失败）。
- 后端：`cd javatutor/backend && mvn -q test`（期望改动前记录数 + 新增，0 失败）。
- coze：`cd javatutor-coze && uv run pytest tests/ -q`（期望 311 + 新增，0 失败）。
- devlog：`docs/devlog/2026-09-12-coze-agent-test-mode-context.md`（改动清单、决策 F1–F4、偏差、三仓测试数、已知局限、手验清单）。

## Task 13：契约与 spec 同步（**必须**）

- `docs/spec/2026-08-10-coze-agent-interface.md` §1：请求 JSON 增 `run_mode` / `test_case_count` 两字段，
  并写明「**可选**：仅 chat 路径且客户端支持时出现；两者同时出现或同时缺失；缺失表示模式未知，不得默认按默认模式解释」。
- `docs/spec/2026-09-10-coze-agent-code-optimization.md` §5：预填文本由「首行 + 错误原文」更新为
  「首行 + `[运行环境]` 事实块 + `[错误原文]`」，并注明事实块只含模式/文件信息、语义在 coze 侧。
- `AGENT.md`：登记本计划与 devlog（见「登记」）。

## 手验清单（`npm run dev`；coze 侧需**重新发布 agent**）

1. **复现原 bug**：单文件粘贴 `class Solution` + 注释里的 `public class TreeNode { ... }`，**不输入任何用例**，点「运行」→ 失败。
2. 点全局红色弹窗的报错入口 → 草稿应含 `[运行环境]` + 「默认模式（测试模式未激活：已保存用例 0 条）」→ 发送。
3. agent 回答应**指出「当前是默认模式、测试模式未激活」并给出激活办法**（在「测试」面板输入用例 → 保存），
   **不得**断言代码有语法/逻辑错误，**不得**建议「补一个 main」之外地乱猜。
4. 同一份代码在「测试」面板输入 1 条用例并保存 → 再点「运行」→ 成功（后端抽取注释类）。
   再走一次报错入口（若此时仍有错）→ 草稿应显示「测试模式（已保存用例 1 条）」。
5. **多文件**：多文件模式报错 → 草稿含「多文件（N 个文件，主入口 X）」。
6. **回归**：不带模式的自由问答（非报错入口）行为与现状一致（coze 侧「运行环境」缺失 → 不臆测模式）。

## 遗留 / 注意事项

- **根因的另一半未修**：用户**在测试面板里但没保存用例**时，前端**静默**按默认模式运行——本件只是让 agent 能正确解释，
  没有阻止这次「用户以为在测试模式、实际不是」的落差。可选后续（**本件不做**）：运行前若测试面板已展开但用例为 0，给出明确提示。
- **模式事实只在提问那一刻取值**：用户改了用例再提问，模式随之变化（符合预期）；但历史对话里的旧提问仍带旧模式，属正常。
- **`extractCommentedClasses` 只认块注释**：行注释（`// public class TreeNode`）不抽取——本体文案已按「块注释」表述，不要写成「注释里的类都会抽取」。
- **姊妹件**：`docs/plan/2026-09-12-coze-agent-optimization-gate-retry-plan.md`（门禁失败自动返修），
  两件在 `stores/player.js` 的 `buildChatBody` 上有顺序依赖（§0.1）。

## 登记

- `AGENT.md` 新增两行索引（本件 + 姊妹件），并在「当前执行状态」表补「联调修复（自动返修 / 测试模式上下文）| 计划已出，待执行」。
