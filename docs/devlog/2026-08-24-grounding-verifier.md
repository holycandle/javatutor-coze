# 2026-08-24 确定性 Grounding 核对器

## 改动内容

执行领域本体计划 `docs/plan/2026-08-19-javatutor-domain-ontology-plan.md` 的「后续计划」：确定性 grounding 核对器。用本体 `field_schema` + 模块白名单的「数据契约规则」程序化验证回答的结构引用，与 Judge 的语义 grounding 交叉对照（仅评估侧，不改变线上 Agent 行为）。

1. **`eval/runner/grounding.py`**（新增）：
   - `verify_grounding(sample, answer)` — 反幻觉结构核对：步骤号必须在 `1..len(steps)`；行号必须属于 steps 数据的 `line` 字段集合；堆对象 id `hN` 必须存在于 `steps[i].heap` 的 key（仅当样本确有 heap 数据时核对）。无 steps 的样本 `applicable=False`，不判罚。
   - `compute_grounding_verify(outputs, samples)` — 聚合指标：applicable/checked/violations/accuracy（accuracy = 无违规样本数 / applicable 样本数）。

2. **`tools/eval_cli.py`** — `cmd_report` 把核对指标并入 `extended`，随 `summary.json` 的 `e2e` 输出。

3. **`eval/runner/report.py`** — `_E2E_METRIC_ORDER` 增加 4 个 `grounding_verify_*` 指标，写入 `report.md`。

4. **`tests/test_grounding.py`**（新增 9 个）+ `tests/test_eval_report.py`（新增 1 个指标输出断言）。

## 验证结果

- 全量测试 `uv run pytest -q` → **147 passed**（新增 10）。
- 实跑 `report` 命令（round-1）：17 个 applicable 样本，核对 36 处引用，抓到 1 个真实违规（q02：Agent 称「步骤1（第1行）」，但 steps 的 line 集合为 {3,4}，混用了源码物理行与 TraceEngine 逻辑行号两套坐标）。
- L5 外壳回归：无文件落入外壳路径。

## 遗留问题

- 核对只覆盖「结构引用」反幻觉（步骤号/行号/堆 id 越界），变量值的语义对错（如 arr[1]=3 被解释成 5）仍由 Judge 的语义 grounding 负责，不在本核对器范围。
- 行号合法性对照 steps 的 `line` 字段集合，而非源码物理行数——源码在样本中可能被单行压缩，物理行数不可靠。若未来 steps 不再携带 `line` 字段，行号核对会自动跳过（`legal_lines` 为空时不判罚）。
- 堆对象 id 约定为 `hN`（正则 `\bh(\d+)\b`），依赖 TraceEngine 的 id 命名规范；若未来改为其他命名需同步正则。
