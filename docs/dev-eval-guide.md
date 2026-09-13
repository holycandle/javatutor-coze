# 开发者评估指南（javatutor-coze）

> 本文档只描述 Coze 智能体的评估体系与命令；JavaTutor 前后端调试请回 JavaTutor 仓库。

## 1. 评估分层

| 层 | 命令 | 作用 | 是否依赖外部 |
|---|---|---|---|
| 组件级 | `component` | intent / citation / critic / rag 组件用例，毫秒级回归 | 否（RAG 用 mock） |
| 端到端 | `e2e` | 调已部署 Coze API 跑黄金集，产出 answers | 是（Coze 流量积分） |
| Judge | `judge` | DeepSeek LLM-as-Judge 四维评分 | 是（DeepSeek） |
| 汇总 | `report` | summary.json + 与上一轮 diff | 否 |
| 检索指标 | `retrieval` | MRR / hit@k（基于 decision_trace） | 否 |
| A/B | `winrate` | 两轮回答谁更优 | 是（DeepSeek） |
| 人工复核 | `review` | 逐条 approve/reject/revision | 交互式 |
| 导出 | `export` | SFT / DPO 训练数据 | 否 |

## 2. 前置配置

`javatutor-coze/.env`（已 gitignore）需要：

```text
COZE_API_URL
COZE_API_TOKEN
COZE_PROJECT_ID
JUDGE_API_URL
JUDGE_API_KEY
JUDGE_MODEL
```

也可用 `--coze-properties <JavaTutor/backend/src/main/resources/coze-local.properties>` 让 CLI 读取 Coze 密钥。CLI 不会输出或写入任何密钥。

## 3. 命令速查

注意：全局参数 `--round-dir` 必须放在子命令之前。

```bash
# 组件级（本地，无外部依赖）
uv run python tools/eval_cli.py component

# 端到端（远程 Coze）
uv run python tools/eval_cli.py --round-dir eval/archive/2026-08-17/round-1 e2e

# Judge（重判已有 answers，不重跑 Coze）
uv run python tools/eval_cli.py --round-dir eval/archive/2026-08-17/round-1 judge

# 汇总
uv run python tools/eval_cli.py --round-dir eval/archive/2026-08-17/round-1 report

# 检索指标
uv run python tools/eval_cli.py --round-dir eval/archive/2026-08-17/round-1 retrieval

# A/B 胜率
uv run python tools/eval_cli.py --a-dir eval/archive/2026-08-17/round-1 --b-dir eval/archive/2026-08-17/round-2 winrate

# 人工复核
uv run python tools/eval_cli.py --round-dir eval/archive/2026-08-17/round-1 review

# 导出微调数据
uv run python tools/eval_cli.py --round-dir eval/archive/2026-08-17/round-1 export --out-dir training
```

## 4. 结果文件

每轮目录 `eval/archive/<date>/round-<n>/`：

- `answers.jsonl`：`id`、`answer`、`latency`、`decision_trace`（含 `tool_calls`、`token_usage`、`sources`、`latency_ms`、`retrieval`、`reasoning`）。
- `judged.jsonl`：`id`、`score`、`judgement`、`scores.{relevance,grounding,pollution,correctness}`、`reason`、`raw_judge_output`、`attempts`、`judge_fallback`、`empty_output`、`error`。
- `summary.json`：`e2e` 汇总（含四档检索指标与 `retrieval_total`）与 `diff_vs_previous`。
- `human_review.jsonl`：执行 `review` 后生成。

## 5. 怎么看 `raw_judge_output`

`raw_judge_output` 是 DeepSeek 最终一次返回的原文，排查 Judge 解析失败最直接。用 Python 读 `judged.jsonl`：

```bash
uv run python -c "import json;from pathlib import Path;p=Path('eval/archive/2026-08-17/round-1/judged.jsonl');rows=[json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()];[print(json.dumps({'id':r.get('id'),'score':r.get('score'),'judgement':r.get('judgement'),'judge_fallback':r.get('judge_fallback'),'empty_output':r.get('empty_output'),'reason':r.get('reason'),'raw':r.get('raw_judge_output')}, ensure_ascii=False)) for r in rows]"
```

只筛兜底样本：

```bash
uv run python -c "import json;from pathlib import Path;p=Path('eval/archive/2026-08-17/round-1/judged.jsonl');rows=[json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()];[print(json.dumps({'id':r.get('id'),'raw':r.get('raw_judge_output')}, ensure_ascii=False)) for r in rows if r.get('judge_fallback')]"
```

`judge_fallback=true` 表示重试后仍无法解析，被保守记为 `score=0`；`empty_output=true` 表示模型返回空串。常见原因是 DeepSeek 返回纯中文说明、空内容或 JSON 不完整。

## 6. 指标解释

### 组件级

- `intent_accuracy`：保守关键词意图分类准确率。
- `citation_accuracy`：回答是否命中所有期望事实（`expected_facts`）。
- `critic_recall`：critic 对事实错误样本的拦截率。
- `rag_hit_at_3`：RAG 检索命中率；本地组件用 mock 空检索，恒为 0，真实值看 e2e/retrieval。
- `pass_rate`：全部组件用例通过率。

### 端到端

- `avg_score` / `grounding_avg`：Judge 四维均分 / grounding 维均分。
- `tool_call_accuracy`：实际 `tool_calls` 与黄金集 `expected_tool_calls` 一致率。
- `task_success_rate`：Judge correct 且命中 `expected_facts` 的比例。
- `avg_latency`：远程端到端平均耗时。
- `avg_token_usage`：prompt+completion 平均 token。
- `grounding_verify_applicable` / `checked` / `violations` / `accuracy`：确定性 grounding 核对（不依赖 LLM）。基于本体数据契约规则，程序化验证回答的步骤号/行号/堆对象 id 是否在 steps 数据中真实存在；accuracy = 无违规样本数 / applicable 样本数，仅统计含非空 steps 的样本，可与 Judge 的 `grounding_avg` 交叉对照。
- `mrr` / `hit_at_1` / `hit_at_3` / `hit_at_5`：RAG 检索四档指标。**`report` 已并入**（2026-09-13 起），与 `tool_call_by_tool` 同层写入 `summary.json` 的 `e2e`。此前这四档只存在于 `retrieval` 子命令、不进 summary，导致「RAG 静默退化」在 `summary.json` 里完全不可见——这是接线而非新增指标，`retrieval` 子命令保留（独立排查用）。
- `retrieval_total`：**检索侧的分母**——黄金集中声明 `expected_sources` 的条数。注意它与 `e2e.total`（判分样本数）**同名不同义**，故并入 summary 时改名为 `retrieval_total`；`retrieval` 子命令输出的仍叫 `total`（那是一个独立指标集，无歧义）。

### 给 `summary.json` 新增扩展指标时（重要陷阱）

`cmd_report` 的组装是 `extended.update(compute_xxx(...))`——这是**盲并**：任何与 `e2e` 既有键
同名的返回键会**静默覆盖**既有指标，且不会有任何报错。实际发生过一次：`compute_retrieval_metrics`
返回的 `total`（`expected_sources` 条数）覆盖了 `e2e.total`（判分样本数 31 → 17），
而 `total` 是 `_E2E_METRIC_ORDER` 首位指标、合入门槛也读 summary。

**规则**：并入前显式核对键名冲突；重名的指标在并入点改名（保留函数自身返回形状，别去改它）。
回归建议：断言 `summary["e2e"]["total"]` 等于判分样本数，同时新指标确实落进了 `e2e`。

### 检索

- `retrieval`：MRR、hit@k，基于 `decision_trace.sources` 与 `expected_sources`。
  `report` 内的同名指标与之一致（同一函数 `compute_retrieval_metrics`）。
- **排查「检索为空」**：看 `decision_trace.retrieval`（新增键），它含**被阈值滤掉的候选**与 `best_score`。
  `retrieval.candidates` 非空而 `kept == 0` ⇒ 检索成功但无一越阈值（候选分数分布问题）；
  `candidates == []` 且 `rag_degraded == true` ⇒ 检索链路真的失败。两者不可混为一谈。

## 7. 什么时候跑评估

- 每次提交前：`component`。
- 影响 Agent 行为时：`e2e + judge + report`。触发项包括 prompt、意图/路由、critic/revise、RAG/知识库、工具 schema、上下文工程、模型或温度。
- 发版/比赛提交/微调前后：`e2e + judge + report + retrieval + export`。
- 纯前端样式、后端非 AI 逻辑、文档/依赖锁：不需要跑 e2e。

## 8. 微调数据

`export` 从评测存档生成：

- SFT：`score >= 4.5` 且 `judgement == correct` 且 `grounding >= 4` 的好回答。
- DPO：同一题同时存在 good/bad 回答的偏好对。

输出到 `--out-dir`（默认 `training/`）。数据量不足时先扩充黄金集、修复 Judge、多跑几轮再导出。

## 9. 常见问题

- `rag_hit_at_3` 组件恒 0：本地 mock 空检索，属预期；真实语义命中看 `retrieval` 或 e2e 的 `sources`。
- q32 不进入 e2e：黄金集里 `judge_priority=false` 的样本按设计跳过。
- `judge_fallback=true`：保守 0 分，需看 `raw_judge_output` 归因。
- `latency_ms=0`：Coze 部署版本缺少 `request_started_at` 状态字段修复，重新部署后生效。
- 成本：e2e 31 条约数分钟并消耗 Coze 流量积分；Judge 消耗 DeepSeek token。
