# Prompt Engineering 深度融合设计

## 1. Goal

重构 Coze 侧 JavaTutor 智能体的提示词工程，使回答与 JavaTutor 产品深度融合：基于真实执行数据（steps/heap/stackFrames/output/行号）回答问题，并在后续阶段主动引导用户使用前端面板能力。设计采用“提示词即代码”的结构化方案，prompt 组件可版本化、可测试、可评审。

## 2. Scope

### Phase A（本期）：事实准确性

- 按意图拆分 system / context builder / few-shot / output contract。
- 上下文注入真实执行数据：当前行代码文本、当前步骤完整快照、前后相邻步骤 diff、方法签名、算法标签。
- 评审 Agent 升级为五类引用核查：步骤号、行号、变量值、堆对象 id、输出内容。

### Phase B（下期）：产品体验

- 上下文加入“前端面板可引导项”清单。
- 输出契约允许并鼓励“建议查看右侧 XX 面板”指引。
- 评审 Agent 核查指引面板真实存在。

### Out of Scope

- 动画生成器。
- 跨会话记忆。
- Prompt 外部文件化（方案 B），后续如需再迁移。

## 3. Decisions

- **D-01**：采用方案 A“提示词即代码”，不引入运行时模板文件。
- **D-02**：新增 `src/graphs/javatutor/prompting/` 包，拆分 `glossary.py`、`contexts.py`、`fewshots.py`、`contracts.py`。
- **D-03**：`prompts.py` 重构为组合器：`system = 角色 + 领域词汇 + 输出契约`，`human = 上下文 + few-shot`。
- **D-04**：`nodes.py` 的 `_build_expert_messages` 改为调用按意图的上下文构建器。
- **D-05**：所有 prompt 组件带版本常量（如 `PROMPT_V1`），修改必须升版本。
- **D-06**：上下文数据只允许来自 `JavaTutorState`，禁止凭空构造。
- **D-07**：每个意图最多注入 2 条 few-shot 示例，防止上下文膨胀。
- **D-08**：当前行代码文本提取失败时输出占位 `(行号超出范围)`，不抛异常。
- **D-09**：评审核查五类引用，任一无法对应真实数据即判不通过。
- **D-10**：Phase B 的“前端面板可引导项”清单由静态常量提供，评审核查面板名真实存在。

## 4. Architecture

```text
src/graphs/javatutor/prompting/
├── glossary.py      # 领域词汇表
├── contexts.py      # 按意图的上下文构建器
├── fewshots.py      # 每意图最多 2 条示例
└── contracts.py     # 每意图输出契约

src/graphs/javatutor/prompts.py   # system 组合器
src/graphs/javatutor/nodes.py     # 调用 prompting.contexts
```

### Module Responsibilities

- `glossary.py`：定义 JavaTutor 术语与解释（TraceEngine、steps、变量快照、堆对象、栈帧、高亮行、控制流、单步播放、运行输出、算法标签），注入 system prompt。
- `contexts.py`：按意图构建 human 上下文，输出结构化 Markdown；函数签名 `build_<intent>_context(state) -> str`。
- `fewshots.py`：按意图返回示例列表；函数签名 `get_few_shots(intent) -> list[str]`。
- `contracts.py`：按意图返回输出契约文本；函数签名 `get_contract(intent) -> str`。
- `prompts.py`：组合 `system = role + glossary + contract`；`nodes.py` 组合 `human = context + few_shots`。

## 5. Context Data Contracts

上下文构建器统一接收 `JavaTutorState`，字段来源全部来自 state。

### 5.1 当前行代码文本

由 `source_code` 按 `current_line` 截取；行号超出范围输出 `(行号超出范围)`。

### 5.2 当前步骤快照

```markdown
### 当前步骤（第 N 步，行 M）
- 行代码：`...`
- 变量快照：```json ...```
- 堆对象：```json ...```
- 栈帧：```json ...```
- 输出：`...`
```

数据取自 `steps[current_step_index]`；缺失字段输出占位说明，不抛异常。

### 5.3 相邻步骤对比

取 `current_step_index-1` 与 `current_step_index` 的变量 diff；不足时省略该节。

### 5.4 方法上下文

`methodName`、`methodSignature`、`algorithm_tags`（后端已传时）。

### 5.5 错误上下文

`compile_error` 原文（debug 必须包含）。

### 5.6 知识库参考

`retrieved_chunks`（带来源），评审 Agent 核查引用真实性。

## 6. Few-Shot 与输出契约

### 6.1 Few-Shot 规则

- 每意图最多 2 条示例。
- 示例必须为真实 JavaTutor 数据风格（如冒泡排序第 2 步 `arr[1]` 变化、二分查找 `mid` 变化、`NullPointerException` 修复）。
- 示例开头标注：`（示例，步骤号/行号/变量名必须替换为本次真实数据）`。

### 6.2 输出契约（data_query 示例）

必须回答：

- 在哪一步、哪一行
- 哪个变量、从什么值变成什么值
- 为什么发生这个变化

禁止：

- 出现步骤数据中不存在的行号/变量值
- 凭空构造堆对象 id

长度：3-6 句，可含代码块。

### 6.3 输出契约（debug）

必须包含：错误根因、出错位置（行号）、具体修改建议。禁止直接断言未在 `compile_error` 中出现的错误。

### 6.4 输出契约（concept）

必须先给核心定义/结论，再结合用户源代码或真实步骤数据举例。禁止脱离本次代码空谈教材内容。

### 6.5 输出契约（other）

回答 JavaTutor 工具使用问题时应给出可操作指引；无关问题礼貌说明职责范围。

## 7. Error Handling

- 上下文构建失败（行文本提取、steps 越界、heap/stackFrames 缺失）→ 输出占位说明，不中断回答。
- 评审输出非法 JSON → 视为通过并标记 `critic_skipped`。
- few-shot 渲染失败 → 省略示例，不中断回答。
- 提示词版本常量缺失或重复 → 测试失败，阻止合入。

## 8. Testing & Acceptance

### 测试

- `ContextBuilderTest`：按意图断言包含/不包含指定字段（当前行、前后 diff、堆、栈、输出、方法签名）。
- `FewShotTest`：每意图示例数量 ≤ 2，可渲染进 human 消息，包含替换提示。
- `PromptVersionTest`：所有 prompt 组件带版本常量且不重复。
- `OutputContractTest`：FakeModel 返回样例，归一化后满足该意图契约。
- 全流程回归：分类 → 压缩 → 检索 → 专家 → 评审 → 修订 → trace 不回归。

### 验收场景

1. 问“为什么第 2 步 arr[1] 变了”→ 回答引用第 2 步、行号、变量新值，评审通过。
2. 模型编造堆对象 id → 评审拦截，修订后引用真实 id 或删除虚构引用。
3. 当前行提取失败 → 上下文标注占位，回答不报错。
4. 每个专家回答符合各自输出契约。
5. 现有深化链路（决策痕迹、RAG）不受影响。

## 9. Related Docs

- [Coze 深化设计](./2026-08-10-coze-agent-deepening-design.md)
- [接口契约](./2026-08-10-coze-agent-interface.md)
- [本地开发规约](../local-dev-convention.md)
