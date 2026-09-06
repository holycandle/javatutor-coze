# 开发日志：单文件下非当前步证据的 0/1-based 标签错配（2026-09-02）

> 更正说明：早前一份同日 devlog 曾把根因归于 `step_facts._evidence_source` 按「当前执行步文件」取行号。经端到端复现，**该改动对用户场景（单文件、13 步、查第 7 步）不生效**——单文件下 `files`/`current_step_file` 为空，`_evidence_source` 恒回退 `source_code`，行为与旧版完全一致。故那份结论作废，本文档为修正后的真实记录。

## 现象

用户单文件运行冒泡排序（`arr=[5,3,8]`，共 13 步），问「第 7 步在做什么」。两种失败形态：
1. **评审未通过已修订**：主 Agent 答出（或尝试答出）后，评审给出「未通过」，修订版改写为「目前没有查询到第 7 步的运行信息…」。
2. **兜底**：三次 `step_facts` 调用（`查询第 7 步，行 7 → 行 0 → 行 0`）后无正文答案，落入「抱歉，我暂时无法回答这个问题。」。

用户强调「第 7 步显然没有越界」——`step_index=6` 正确对应第 7 步（0-based），非 off-by-one。

## 排查与结论

按序排除，最终证实**工具链本身正确**，真正的问题是**证据标签的 0-based/1-based 不一致**：

### 1. 排除工具链缺陷（端到端复现证明）

用真实 Coze 转换路径（`to_client_message` → `to_stream_input(content list)` → `HumanMessage(content=list)` → `parse_context`）跑用户代码 + 13 步轨迹，得到：
- `parse_context` 正确解析出 `steps_count:13`、`steps` 13 步、`current_step_file:''`。
- `step_facts(step_index=6)` 三种传参（`line=7`/`line=0`/无 line）都返回**可信证据**：
  - `line_text`：`if (arr[j] > arr[j+1]) {`（line=7）/ `arr[j] = arr[j+1];`（line=0/缺省，落到步自身行 9）
  - `variables`：`{arr:[3,5,8], n:3, i:0, j:0, temp:5}`
  - `diff`：`arr [5,3,8] → [3,5,8]`
- **确认**：部署代码（`../projects`）与源仓库（`javatutor-coze`）针对 `main_agent.py`/`contexts.py`/`prompts.py`/`critic.py`/`context_builder.py`/`fetch_execution_context.py` 内容**完全一致**（忽略 CR 行尾），08-31 的 `step_memories`/`build_facts_block` 修复均在。故部署代码无陈旧，非「部署了旧版本」。

### 2. 定位真实根因：证据块步骤标签 0/1-based 错配

批评者 `build_facts_block(state)` 把 `state.step_memories` 渲染为：

```
### 已查询的步骤证据（step_facts）
- 第 6 步: {"error":"","evidence":{"variables":{...},"line_text":"arr[j] = arr[j+1];"},"diff":[...]}
```

问题：`step_memories[].step_index` 存的是工具参数 `args.step_index`（**0-based**，即 6），`build_facts_block` 原样标成「**第 6 步**」。

而同一函数里的 `_step_snapshot` 用 `idx + 1`（**1-based**，第 2 步）、用户和主 Agent 回答都按「**第 7 步**」（1-based 展示序）。于是：
- 批评者核「步骤号是否存在于步骤数据」时，手里证据标「第 6 步」，回答/问题引用「第 7 步」——两套标签指向同一个东西，但对批评者而言**看起来是不同步骤**。
- `SYSTEM_PROMPT_CRITIC` 未定义「第 N 步」的基准，批评者无法自纠 0/1-based，遂判定「回答引用的第 7 步无证据」→ `pass:false` → 修订节点把正确回答改坏成「没有第 7 步信息」。这正是形态 1 的来源。

形态 2（兜底）更多是模型行为：主 Agent 遇 `[step_facts 结果]` 为冗长原始 JSON 且标签（`step_index=6` 与上下文）不直观时，反复换 `line` 试探，3 轮未给出正文答案落入兜底。标签修正也能缓解。

## 改动

- **`src/graphs/javatutor/prompting/contexts.py`**（`build_facts_block`）：记忆条目标签统一为 1-based 展示序并保留 0-based 提示：
  ```python
  idx = m.get("step_index")
  try:
      display = int(idx) + 1
      hint = f"（step_index={int(idx)}）"
  except (TypeError, ValueError):
      display, hint = "?", ""
  lines.append(f"- 第 {display} 步{hint}: {m.get('content', '')[:600]}")
  ```
  `step_index=6` → 渲染「第 7 步（step_index=6）」，与学生/回答的「第 7 步」对齐，批评者可直接核对该步证据。
- **测试**：`tests/test_contexts.py::test_facts_block_includes_step_memories` 断言更新为 `第 7 步（step_index=6）`。

## 验证结果

- 端到端复现（真实转换路径 + 用户代码 + 13 步）：
  - `parse_context` → `steps_count:13`、`step_facts(step_index=6)` 返回正确证据（arr 交互、temp、line_text、diff）。
  - `build_context`（GSSC）→ 主 Agent 上下文含「当前执行位置：当前步骤索引 1（第 2 步）/总步骤数 13」，模型具备按 0-based 查询非当前步的能力。
  - 修正后 `build_facts_block` 将证据标为「第 7 步（step_index=6）」，与回答引用一致。
- L2 coze 全量单测：`uv run pytest -q` **190 passed**（无回归）。

## 遗留 / 待确认

1. **同款标签错配排查**：`src/tools/fetch_execution_context.py` 的 `_step_file` 只用于报告 `current_step_file`，无逐步标签，未受影响。
2. **`_evidence_source` 多文件改动**（同日早前）：让 `step_facts` 在**多文件**下按被查询步自身 `file` 取行号（而非当前步文件）。对单文件场景无影响（恒回退 `source_code`），属正交的多文件正确性改进，保留；已确认非本 bug 根因。
3. **真实数据格式差异**：本地用合成的 13 步轨迹验证。若线上真正 trace 的 `step` 字段为 1-based（Instrumenter `counter` 从 1 起），或 `variables` 在若干步缺 `arr`，需以线上真实 `【决策痕迹】JSON` 与 `steps` 复核。若仍复现，请提供一次失败回答末尾的原始 `【决策痕迹】JSON`（非渲染界面）以核对 `tool_calls[].result` 的 `line_text`/`diff`。
4. **Coze 侧部署**：本修复需重新发布后生效。本地已用全量测试与端到端复现确证代码正确。

## 追加：兜底形态（「抱歉，我暂时无法回答这个问题。」）的根因与修复（同日后续）

上面 0/1-based 标签修复只解决了「评审未通过已修订」这一形态。用户重新部署后仍复现**兜底形态**（18 步/13 步下问「第七步在做什么」，主 Agent 反复 `step_facts`，仅生成 11 token，落下兜底「抱歉，我暂时无法回答这个问题。」）。

### 定位

- `build_facts_block` 标签修复只影响**批评者可见性**，不影响**主 Agent 自己能不能答出来**。所以它不改变兜底形态。
- 端到端复现已证明 `step_facts(step_index=6)` 返回可信证据；后端 `/chat`（`CozeAIController` → `streamExplain(... request.getSteps() ...)`）**确实传递 steps**；部署代码与源仓库内容一致（忽略 CR）。故非「数据没到模型」，而是**模型拿到证据后不肯作答**。
- 真正的缺口在 [main_agent.py](src/graphs/javatutor/main_agent.py)：把 `step_facts` 返回值以 `json.dumps(result)` 的**原始嵌套 JSON** 追加进 `context`，且**不带步骤标签**（0-based 值、无「第 N 步」字样）。模型既要解析冗长 JSON（`variables` 与 `stackFrames.locals` 重复、`heap`），又要自行推断证据对应「第几步」。弱模型读「必须先调用 step_facts」→ 反复换 `line` 试探（截图为 `行 0 → 行 0 → 行 7`），3 轮未给正文即落兜底。这也解释了「生成 11 token」。

### 改动

- **`src/graphs/javatutor/main_agent.py`** 新增 `_format_step_facts(args, result)`：把证据渲染成可读文本，并带 1-based 展示序 + 0-based 提示的标签（与 `build_facts_block` 修复口径一致）：
  ```
  [step_facts 结果：第 7 步（step_index=6）]
  - 变量：{"arr": [3, 5, 8], "n": 3, "i": 0, "j": 0, "temp": 5}
  - 堆：（无堆数据）
  - 栈帧：[{"method": "main"}]
  - 输出：`（无输出）`
  - 行号 9：`arr[j] = arr[j+1];`
  - 与上一步对比：
    - arr: [5, 3, 8] → [3, 5, 8]
  ```
  模型一眼读出「第 7 步把 arr[0] 与 arr[1] 交换」，不再解析原始 JSON。
- 追加**重复查询提示**：若已为某 step_index 返回过非错误证据，又再次查询**同一步骤**，则追加「这一步的证据已在上文 'step_facts 结果' 中给出，请直接基于该证据回答，不要重复查询同一步骤。」——打断 `行 0 → 行 0` 式重复试探；查询**不同**步骤仍允许（便于模型对照多步）。
- 测试：`tests/test_main_agent.py` 新增 `test_format_step_facts_is_clean_labeled_text` 与 `test_main_agent_repeat_same_step_gets_answer_nudge`。

### 验证结果

- `uv run pytest -q` **192 passed**（无回归）。
- 部署副本 `../projects/src/graphs/javatutor/main_agent.py` 与源仓库内容一致（忽略 CR）。

### 遗留 / 待确认

- 核心不确定点已收敛为「模型行为」：生成 token 极小（11）。若新格式上线后仍复现，需取真实失败回答末尾的原始 `【决策痕迹】JSON` 核对 `tool_calls[].result` 的 `line_text`/`diff`，以及是否仍以同一步骤重复查询。
- `build_facts_block` 的 0/1-based 修复与本次 `_format_step_facts` 属于两个独立形态（评审拒绝 vs 主 Agent 不答），须同时生效。
