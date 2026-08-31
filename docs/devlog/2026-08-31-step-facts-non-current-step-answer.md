# 开发日志：agent 无法回答「非当前步」问题的排查与修复（2026-08-31）

> 关联上下文：
> - 信息分层原则：记忆/知识走上下文工程、单步执行证据走工具（JIT 读取）——见 `docs/devlog/2026-08-29-memory-retrieval-context-engineering.md`。
> - 相关 bug1（单文件代码读取）已在 `2026-08-30-fetch-execution-context-as-tool` 侧修复并确认；本文档记录 **bug2（agent 答不出非当前步）**。

## 现象

用户提问「第七步在做什么」（当前执行步为第 1 步，冒泡排序共 13 步）时，agent 无法正确回答，表现为两种：
1. 三次 `step_facts` 调用后兜底「抱歉，我暂时无法回答这个问题。」
2. 主 Agent 给出回答，但 **「评审未通过，已修订」**，修订版变成「目前没有第七步的完整运行状态信息（变量快照、堆对象、栈帧、执行代码等相关事实数据），暂时无法回答第七步在做什么。」

关键观察：工具调用记录为 `step_facts: 查询第 7 步，行 0`，即 agent 传入的是 `step_index=6`——**0-based 换算正确**（第 7 步 = step_index 6），并非 off-by-one。

## 排查过程与结论

按序排除，最终把问题定位到**评审（critic）只能看到当前步快照，无法核对非当前步引用**：

1. **排除 off-by-one**：`decisionTrace.js` 中「第 N 步」渲染为 `step_index+1`，故 `step_index=6`=第 7 步，符合 13 步数据集语义。agent 传参正确，非换算错误。
2. **排除体积截断**：payload 仅约 3.3KB（4KB 含 coze body），不足以触发截断；前端 `player.js` 全量发送 `steps`，后端 `CozeService` 全量放入 payload。
3. **确认 step_facts 本身正确**：本地用 13 步冒泡排序数据复现 `step_facts(step_index=6, line=0)`，返回 `arr [5,3,8]→[3,5,8]`、`t=5`、`line_text='arr[j + 1] = t;'` 及清晰 diff。**说明 agent 拿得到第七步数据。**
4. **定位到批评者可见性缺陷**：`critic._facts(state)` → `build_facts_block(state)`，其 `_step_snapshot` 只用 `steps[current_step_index]`（当前步）。当主 Agent 回答的是**其它步骤**时，批评者手里只有当前步快照，无法核对该步引用 → 误判「第 N 步不存在」→ 修订节点重写为「不存在第七步」。

### 本次排查中的两个判断失误（如实记录）

- **误判 off-by-one 为根因**：最初改 `SYSTEM_PROMPT_MAIN_AGENT` 强调 0-based。后经 `decisionTrace.js` 渲染逻辑证实 agent 传参本就正确，该方向作废。
- **误判「前端 dist 陈旧」为突破口**：曾以 `dist/assets/*.js` 缺 `已获取证据` 标注推断前端未重新构建。**该判断作废**——用户本地跑的是 `npm run dev`（Vite 热载最新源码），与生产构建 `dist/` 无关。前端始终在跑最新 `decisionTrace.js`。

## 改动

- **`src/graphs/javatutor/prompting/contexts.py`**：`build_facts_block` 新增 `### 已查询的步骤证据（step_facts）` 区块，读取 `state.step_memories`（主 Agent 工具循环查到的单步证据，保留最近 5 条），供批评者核对**非当前步**引用。
- **`src/graphs/javatutor/main_agent.py`**：`step_facts` 调用后把返回值（截断至 300 字符）写入 `tool_calls[].result`，供决策痕迹诊断越界/证据；成功（`error` 空）时写入 `step_memories`（importance 0.8，保留最近 5 条）。
- **`src/tools/step_facts.py`**：越界时返回 `steps_count` 与 `current_step_index`，并在「恰为 1-based 展示序」时给出 `step_index=N-1` 换算建议。
- **`src/graphs/javatutor/prompts.py`**：`SYSTEM_PROMPT_MAIN_AGENT` 澄清 `step_index` 为 0-based（第 1 步 = 0，第 N 步 = N-1），告知「返回 steps_count 说明越界，按可用范围重试或如实告知」。
- **前端 `src/utils/decisionTrace.js`**（javatutor 仓库）：`step_facts` 工具行在 `tool_calls[].result` 存在时追加状态标注——` → 越界（共 N 步）` 或 ` → 已获取证据`，便于诊断。
- **测试**：`tests/test_contexts.py`（`build_facts_block` 含/不含 `step_memories`）、`tests/test_step_facts.py`（越界、1-based 换算提示）、`tests/test_main_agent.py`（tool_calls 改为字段校验 + result 存在性）；前端 `decisionTrace.test.js` 增补状态标注用例。

## 验证结果

- L2 coze 全量单测：`uv run pytest -q` **189 passed**。
- 前端 `decisionTrace.test.js`：**12 passed**。
- 本地复现（13 步冒泡排序）：
  - `step_facts(step_index=6)` 返回正确证据（arr 交换、t、line_text、diff）。
  - `build_facts_block` 在设置 `step_memories` 后确实输出 `### 已查询的步骤证据（step_facts）` 区块，内含第 6 步证据。
- 图连线核对：`graph.py` 为 `main_agent → critic` 直连，`step_memories` 经 state 传递到批评者，链路完整。

## 遗留 / 待确认（问题未解决）

> 结论：**本地代码链路已验证正确，但用户侧「已部署最新版本 + 重启前端」后 bug 仍在，说明部署产物与本地代码存在差异，或存在本地复现未覆盖的真实运行时差异。** 根因尚未最终确证。

待确认项：
1. **coze 部署来源**：agent 是从本 `javatutor-coze` 仓库经构建步骤发布，还是将图代码手动复制进 coze 工作流/插件？这决定 coze 是否真正读到本次修改的 `contexts.py` / `main_agent.py`。
2. **决策痕迹 `result` 字段**：请提供回答末尾原始 `【决策痕迹】JSON`（非渲染界面）。若 `tool_calls[].result` 为空 → coze 侧在跑不含 result 记录的旧 `main_agent.py`；若非空且仍被「评审未通过」→ 重点查 `step_memories` 是否真实传达到 critic。
3. **真实 steps 数据**：本地用合成 13 步数据验证，需确认线上真实 `steps` 结构与行号映射（`source_code` 为行号锚点）与合成数据一致。
4. **前端标注是否出现**：重测时应看到 `调用 step_facts：查询第 7 步，行 0 → 已获取证据`。若未出现标注，说明 `result` 未进入痕迹。

下一步建议（待用户确认部署方式后执行）：
- 从当前 `src/` 明确重新发布 coze agent，确认非缓存快照。
- 用 dev 前端重测，读取原始决策痕迹 JSON，核对 `step_facts` 的 `result` 与批评者 `pass` 字段。
