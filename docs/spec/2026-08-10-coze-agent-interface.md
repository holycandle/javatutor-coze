# Coze Agent 深化接口契约

> 本文档定义 JavaTutor 后端与 Coze 侧智能体之间的消息契约，以及智能体回答中“决策痕迹”的解析格式。前后端与 Coze 侧实现均以本文档为准。

## 1. Request（JavaTutor 后端 → Coze Chat API）

后端通过 Coze Chat API 发送 JSON 字符串作为消息文本，字段不变，`intent` 可选：

```json
{
  "source_code": "public class BubbleSort { ... }",
  "steps": [
    {"step": 0, "line": 3, "variables": {"arr": [5, 3, 1]}}
  ],
  "current_step_index": 0,
  "current_line": 3,
  "user_question": "为什么 arr[1] 变成了 3？",
  "user_id": "u-001",
  "compile_error": "",
  "intent": "analyze"
}
```

规则：

- `intent` 缺省时由智能体 LLM 分类；显式传值时智能体直接采用。
- `intent` 合法枚举：`data_query`、`concept`、`debug`、`animate`、`animate_guide`、`analyze`、`other`。
- `steps` 允许为空数组；`compile_error` 允许为空字符串；`user_id` 允许缺失。

**`intent` 的下游影响（2026-09-14 增）**

`intent` 不只用于埋点：它**改变上下文与评审口径**。同一份代码 + 同一个问题，标注不同意图会得到不同的产物。

| 影响面 | `concept`（概念题） | 其它意图（尤其 `data_query`/`debug`） |
|---|---|---|
| 系统提示 | 追加以概念讲解为口径的引导段（直接讲概念本身、不围绕当前执行位置） | 追加各自口径的引导段（`data_query` 无额外段） |
| 上下文 packet | **不注入** `### 当前执行位置`（步骤/行号/变量） | 注入（既有行为） |
| 契约 | 用 `concept` 意图契约 | 用该意图契约 |
| 评审口径 | 不得要求「步骤引用/行号」这类本地化证据（概念题没有可引的执行证据） | 按各自口径核对引用 |

**为什么必须分流**：`gather()` 此前对**任何**问题都注入 `### 当前执行位置`（relevance 0.9，全上下文最高），
主 Agent few-shot 里又**没有一条概念类样本**（7 条中 4 条锚定当前步或优化）⇒ 概念题（「迪杰斯特拉算法的原理是什么？」）
也被答成「当前这一步在做什么」。分流 + 补样本是这处缺陷的两条修法。

- 注意：本表只描述**智能体侧**如何用 `intent`。后端 / 前端把哪些提问归到哪个 intent，
  仍在演进（启发式关键词见 coze `intent_rules.py::conservative_intent`，**不保证**与语义完全一致）——
  故智能体不得把 `intent` 当作绝对真理，只在引导与评审口径上采用它。

### 1.1 运行模式字段（可选；仅 chat 路径）

前端在 `/api/ai/chat` 的请求里随**每次**提问携带本次运行的模式事实，后端原样透传（下列两键与 §1 的字段同层，
此处只摘录新增部分）：

```json
{
  "run_mode": "test",
  "test_case_count": 2
}
```

规则：

- **可选**：仅 chat 路径、且客户端支持时出现；其它入口（`analyze`/`uml`/`animate`）不带。
- 两键**同时出现或同时缺失**（后端只按 `run_mode` 非空判定是否携带）。
- `run_mode` 合法值：`"test"` | `"default"`；`test_case_count` 为已保存用例数（`int`，**0 是有意义的值，不得省略**）。
- **缺失 = 模式未知**（旧客户端）：智能体不得注入任何运行模式上下文，也不得臆测模式、
  **不得把缺失等同于 `"default"`**（两种状态在智能体侧是不同的 state 值）。
- 职责切分：**事实**（本次运行是哪种模式）由前端传；**语义**（两种模式各要求什么）只写智能体侧知识与引导，
  前端不在提问文本里写 JavaTutor 内部运行语义。
- 落点见 [2026-09-12 测试模式误诊修复](../devlog/2026-09-12-coze-agent-test-mode-context.md)：
  state `run_mode`/`test_case_count` → `### 运行模式` 上下文 packet + 评审核对 facts 块一行 + 「运行模式判读」引导段。

## 2. Response（Coze 智能体 → 消息文本）

智能体回答正文后，可能追加决策痕迹块：

```text
正文回答...

【决策痕迹】
{"intent":"data_query","confidence":0.9,"sources":[...],"critic_passed":true,"revised":false,"fallback_reason":"","rag_degraded":false,"critic_skipped":false,"revise_skipped":false,"compaction_mode":"none"}
```

约定：

- 决策痕迹块固定以单独一行 `【决策痕迹】` 开头，其后一行是 JSON。
- 正文与痕迹块之间空一行。
- 前端按“最后一个 `【决策痕迹】` 标记之后的内容”提取 JSON，其余全部视为正文。
- 无痕迹时（如 analyze 返回纯 JSON、动画返回 SVG），正文就是完整消息，前端不强制解析。

## 2.1 视角导航块（回答中附带，可选）

主 Agent 在回答末尾（`【决策痕迹】` 之前）可附带一个结构化导航指令块，供前端渲染成可点击卡片，让用户一键跳到
JavaTutor 的对应面板。块协议见 [2026-09-07-coze-agent-view-navigation.md](./2026-09-07-coze-agent-view-navigation.md)。

```text
正文...

【视角导航】
{"views":[{"panel":"tutor","sub":"analysis","label":"分析"}]}
```

约定：

- 固定以单独一行 `【视角导航】` 开头，其后一行是 JSON。
- `views` 最多 3 项；`panel` 为面板白名单 id、`sub` 仅供 `tutor`（`analysis`|`explain`）、`label` 缺省为面板规范名。
- 无可用面板时整块省略；最多一个 `【视角导航】` 块/条回答。
- 前端按“`【决策痕迹】` 之前、`【视角导航】`/`【编辑建议】` 之后的正文”渲染，三个结构化块均不落入 markdown 正文。

## 2.2 编辑建议块（回答中附带，可选）

主 Agent 可在回答末尾（`【视角导航】`/`【决策痕迹】` 之前）附带一个 `【编辑建议】` 块，前端渲染为卡片并经
用户点击后改动编辑器代码。顶层 `kind` 字段区分三种载荷（缺省为 `patch`，**向后兼容**）：

| kind | 用途 | 载荷 |
|---|---|---|
| `patch`（缺省） | 局部替换 | `{"edits":[{"title","explanation","old_string","new_string"}]}` |
| `options` | **方案卡**：候选优化目标（不含代码） | `{"kind":"options","target":"...","options":[{"goal","label","detail"}]}` |
| `replace` | **整文件覆盖** | `{"kind":"replace","target":"...","goal":"...","rationale":"...","code":"<整份新代码>"}` |

```text
正文...

【编辑建议】
{"kind":"options","target":"Solution.java","options":[{"goal":"performance","label":"以性能为先","detail":"用哈希表把嵌套循环降为 O(n)"}]}
```

约定：

- 放置顺序：正文 → `【编辑建议】`（如有）→ `【视角导航】`（如有）→ `【决策痕迹】`；与正文空一行分隔。
- **每答最多一个 `【编辑建议】` 块**；`options` 与 `replace` 不同时出现。
- 代码优化走**两步式**：第一轮只给 `options`（2–3 项，`goal` 取闭集
  `performance|readability|memory|style|correctness|comprehensive`，块内不得含代码，且方案卡**不得**产出 `comprehensive`）；
  用户在方案卡上勾选（可多选）后，前端按模板发新一轮提问（白名单「只做…」+ 黑名单「不要顺带做其他方向的改动（例如：…）」），
  第二轮才给 `replace` 的**完整可编译**整份代码——`goal` 单方向时为该方向、**多方向（勾 ≥2）时为 `comprehensive`**（`rationale` 逐项说明），
  且代码只许改动所选方向。
- **第二步提问以 `【优化第二步】` 起头**，这是智能体判别「这是第二步」的**唯一**依据（不是措辞）。
  原因：chat 请求无状态、工作记忆只留上一答前 200 字，而 `options` 块在回答末尾 ⇒ 服务端读不到「上一轮已给过卡」；
  而第二步提问的形状（「只做「以性能为先」方向的优化」）与「用户已指明目标仍先出方案卡」**同形**，无法靠措辞区分。
  字面量两侧硬编码：前端 `utils/editSuggestion.js::STEP2_MARKER`、coze `prompting/optimization.py::STEP2_MARKER`，
  各配一条跨仓断言（任何一端改字另一端必须红）。
- `goal` 闭集与提问模板详见 [2026-09-10-coze-agent-code-optimization.md](./2026-09-10-coze-agent-code-optimization.md) §4.4。
- `target` 为文件名：多文件模式必填，单文件模式缺省为当前文件。
- 取值非法 / `code` 为空 / `options` 为空 → 整块按正文展示（不静默丢弃、不崩），前端不出卡。
- 完整规格见 [2026-09-10-coze-agent-code-optimization.md](./2026-09-10-coze-agent-code-optimization.md)。

## 3. 决策痕迹 Schema

```json
{
  "intent": "data_query|concept|debug|other|animate_guide",
  "latency_ms": 14203.5,
  "confidence": 0.0,
  "sources": [
    {"source": "知识库: Arrays.sort", "score": 0.82}
  ],
  "critic_passed": true,
  "critic_issues": [
    {"claim": "变量值 8 与数据不符", "answer_span": "arr[1] 变成了 8", "fact": "学生问题：为什么 arr 变了？", "blocking": true}
  ],
  "revised": false,
  "revise_outcome": "skipped",
  "revise_revert_reason": "",
  "fallback_reason": "",
  "rag_degraded": false,
  "critic_skipped": false,
  "revise_skipped": false,
  "compaction_mode": "none|windowed|truncated",
  "tool_calls": [
    {"tool": "step_facts", "args": {"step_index": 1}}
  ],
  "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "estimated": true}
}
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `intent` | string | 最终采用的意图 |
| `latency_ms` | number | 从 `request_started_at`（`parse_context` 写入状态的时间戳）到 `build_final` 输出的图内墙钟耗时，毫秒，保留 1 位小数；用于评测响应速度指标。估算值，与平台 `message_end.time_cost_ms` 不一定一致（后者含网络与平台调度开销） |
| `confidence` | number | LLM 分类置信度，0-1 |
| `sources` | array | 检索命中的知识来源，未命中为空数组 |
| `critic_passed` | boolean | 评审是否通过；评审跳过时为 `true` 且 `critic_skipped=true` |
| `critic_issues` | array | 评审留下的**有效**意见，元素含 `claim` / `answer_span` / `fact` / `blocking`（文本各截 300 字）。**有效 = 出处可核实**：`answer_span` 须是回答子串、`fact` 须是事实块子串，给不出出处的意见会被丢弃（故本键与「评审据以行动的那份意见」同源）；无意见时 `[]` |
| `revised` | boolean | **修订稿是否被采纳**（2026-09-14 语义收窄：此前为「是否执行过修订」）。回退时为 `false`——用户拿到的就是原答；要看「是否触发过修订」用 `revise_outcome` |
| `revise_outcome` | string | `accepted`（采纳）/ `reverted`（过不了验收闸，回退原答）/ `skipped`（未触发 / 调用异常 / advisory 模式） |
| `revise_revert_reason` | string | 回退原因，未回退时 `""`：`similarity` / `nav_block` / `edit_block` / `grounding` / `recheck` |
| `fallback_reason` | string | 降级原因，未降级为空字符串 |
| `rag_degraded` | boolean | 检索降级（跳过 RAG）时为 `true` |
| `critic_skipped` | boolean | 评审调用失败时为 `true` |
| `revise_skipped` | boolean | 修订调用失败时为 `true` |
| `compaction_mode` | string | `none`（≤200 步）、`windowed`（压缩成功）、`truncated`（压缩失败后截断） |
| `tool_calls` | array | 主 Agent 工具循环实际执行的工具调用记录，元素含 `tool` 与 `args`；用于评测工具调用准确率。**2026-09-14 起 `fetch_execution_context` 的记录也带 `result`**（`step_facts` 一直有）：**两条路径都是合法 JSON**（消费方统一 `json.loads`）——成功是自描述摘要（`{"stored": true, "file", "file_source", "code_chars", ...}`，**不含 `code`**），失败是 `{"stored": false, "error": ...}`；决策痕迹里「调了 fetch 却拿不到源码」必须能自证 |
| `token_usage` | object | 本次回答的 token 消耗：`prompt_tokens`、`completion_tokens`、`estimated`（true 表示估算值）；用于评测成本 |

> **2026-09-14（联调修复 Task 1/D2）**：`fetch_execution_context` 的观测
> （`[fetch_execution_context 结果]`，同时进 `step_records[].summary`）新增两个字段：
> `file` 是**这次真正取到的文件**（空串 = 单文件代码/激活文件），
> `file_source` 是解析来源（`explicit` / `entry_file` / `current_step_file` /
> `only_file` / `source_code`），`code_chars` 是取到的字符数。
> 同时**取消「成功但空」**：解析不到源码（含切行后为空）一律返回
> `fetch_context_failed=true` + 带候选文件名的 `error`，不再出现
> `fetch_context_failed=false` 配 `code=""` 的静默成功。
> 前端【执行过程】区把这两个字段渲染进 fetch 卡片
> （标题行 `获取执行上下文`；结果行 `Main.java（主入口），1234 字`，失败为 `失败：<错误>`
> 并标红，长错误截 60 字）。**不能只看 `args`**：自动前置的 fetch（`args` 为空）与模型不传
> `file` 的调用都没有文件名。
> 详见 `2026-08-23-execution-context-fetch-design.md`。

> **2026-09-14（联调反馈②）**：`tool_calls` 每次调用在【执行过程】区渲染成**一张卡片**
> （工具名 + 标量参数一行、`result` 摘要一行、左侧色条按成功/失败标色），不再是一行裸文本。
> 逐字段口径见 `docs/devlog/2026-09-14-fix-fetch-context-and-duplicate-answer.md` §6–§7。

## 4. 正文引用格式

专家回答需要标注知识来源时，使用以下格式：

```text
参考知识库：Arrays.sort
```

或并列多个来源：

```text
参考知识库：Arrays.sort、HashMap
```

前端可把“参考知识库：”后的来源文本渲染为来源标签；评审 Agent 会核查该来源是否真实存在于检索结果中。

## 5. 降级行为

| 场景 | 行为 | trace 标记 |
|---|---|---|
| 意图分类输出非法/低置信度 | 降级 `other` | `fallback_reason` |
| 检索失败 | 跳过 RAG，用原上下文回答 | `rag_degraded=true` |
| 评审失败 | 视为通过 | `critic_skipped=true` |
| 修订失败 | 返回原回答 | `revise_skipped=true` |
| steps > 200 且压缩失败 | 截断注入 | `compaction_mode=truncated` |

## 6. 示例

### 6.1 概念问答（带 RAG）

```text
HashMap 是基于哈希表的键值映射，平均查询复杂度为 O(1)。
参考知识库：HashMap

【决策痕迹】
{"intent":"concept","latency_ms":14203.5,"confidence":0.95,"sources":[{"source":"知识库: HashMap","score":0.86}],"critic_passed":true,"revised":false,"fallback_reason":"","rag_degraded":false,"critic_skipped":false,"revise_skipped":false,"compaction_mode":"none"}
```

### 6.2 评审拦截并修订

```text
根据第 2 步（第 4 行），arr[1] 由 3 变成 5，原因是发生了交换。
参考知识库：无

【决策痕迹】
{"intent":"data_query","latency_ms":13607.2,"confidence":0.88,"sources":[],"critic_passed":false,"revised":true,"fallback_reason":"","rag_degraded":false,"critic_skipped":false,"revise_skipped":false,"compaction_mode":"windowed"}
```

## 7. 前后端约定

- 后端：保持消息透传，不截断、不转义正文；`【决策痕迹】` 属于消息文本的一部分。
- 前端：流式接收时先累积完整消息，收到结束标记后再解析痕迹块并渲染。
- 前端解析规则：全文按 `\n【决策痕迹】\n` 切分，前半为正文，后半为 JSON；JSON 解析失败时整段按正文展示。
