# 开发日志：提高 fetch_execution_context 调用率（2026-09-08）

> 背景：2026-09-06 round-2 评测显示均分 -0.5172、grounding -0.7808，组长定位为「获取代码工具（fetch_execution_context）调用率太低」。

## 原因

round-2 各工具调用情况：`fetch_execution_context` 期望 16 / 实际调用 4（25%），`step_facts` 期望 16 / 实际调用 15（94%）。

根因链：

1. 方案 A 恢复完整 envelope 后，`source_code` / `steps` 由后端入站 payload 带入，`parse_context` 在流程最开始就写进 state。
2. `step_facts` 直接读 `state.steps`，**不依赖 fetch 先执行**——agent 跳过 fetch 也能拿到单步变量证据，于是"没动力"调 fetch。
3. 跳过 fetch = 模型拿不到源码全文。黄金集里的 `source_code` 是单行压缩版，行号对不上，`step_facts` 返回 `line_text = (行号超出范围)`；模型无源码可交叉核对，就把数组变化错误归因成"TraceEngine 引擎异常/越界"，导致一批 incorrect / partially_correct。

## 改动

- **`src/graphs/javatutor/main_agent.py`（机制保证）**：`main_agent_node` 内新增 `fetched_injected` 标志；在 `step_facts` 分支前，若 `fetched_context` 尚未建立则先确定性执行一次 `fetch_execution_context`（记入 `tool_calls`，`args={}`），把源码读进上下文再查单步证据。agent 主动调用 fetch 的分支同步置位，避免重复。concept / other 样本不调 `step_facts`，不触发 fetch，不会产生"误用"。
- **`src/graphs/javatutor/prompts.py`（提示词强化）**：`SYSTEM_PROMPT_MAIN_AGENT` 把 `fetch_execution_context` 引导提前到 `step_facts` 之前，语气改为"必须先调用 fetch_execution_context 获取源码全文，再调 step_facts"。
- **`AGENT.md`**：修复 60–70 行遗留的 merge 冲突标记（`<<<<<<< HEAD … >>>>>>> feat/fetch-execution-context-as-tool`，两边条目均保留）。
- **`tests/test_main_agent.py`**：更新 2 个受自动前置 fetch 影响的用例（`test_main_agent_calls_step_facts_then_answers`、`test_main_agent_invalid_args_returns_error_not_crash` 的 `tool_calls` 顺序断言）；新增 `test_step_facts_auto_fetches_first`。

## 验证结果

- L1 依赖锁：`uv sync --frozen` 通过（Checked 135 packages）。
- L2 全量单测：`uv run pytest tests/ -q` 全绿（**205 passed**）。
- L2.5 组件评估：`test_eval_component.py` 通过（1 passed）。
- L3 离线构建：`build_agent().builder.compile()` 输出 `ok`（本地无 PG，checkpointer 降级 MemorySaver，不影响编译）。
- L5 外壳回归：无输出（未触碰 `.coze` / `scripts/` / `src/main.py` / `src/storage/` / `src/utils/`）。
- 端到端重测：**待部署后执行**（见遗留）。

## 遗留 / 注意事项

- 本次改动需在 Coze 平台**重新发布 agent** 后，重跑 `e2e + judge + report`，对比 fetch 调用率（预期 4/16 → 16/16）与 `avg_score` / `grounding_avg`；按规约，均分降 >0.3 或 grounding 降 >0.5 禁止合入。
- 本地无 `.env`（COZE_API_URL / JUDGE_API_KEY 等），且 `e2e_remote` 调用的是已部署远程 agent，本地无法直接端到端重测本次改动。
- 本次只改 main_agent 工具循环与主 Agent 提示词，不碰后端 envelope 与外壳。
