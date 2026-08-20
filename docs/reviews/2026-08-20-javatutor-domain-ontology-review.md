# 2026-08-20 JavaTutor 领域本体执行 Review

> 审查对象：javatutor-coze `feat/robust-eval-system`（未提交工作区）
> 对应计划：`docs/plan/2026-08-19-javatutor-domain-ontology-plan.md`

## 结论

计划主体已执行且符合目标：本体数据、加载器、Agent 常驻注入、Judge 同步消费、测试与文档均到位。全量测试 129 passed。

发现 1 个 P2（索引约定缺失）和 2 个 P3（健壮性/路径脆性），均不阻塞合入。

## Findings

### P2：本体未记录 0-based 索引约定

**位置**：`assets/knowledge/javatutor_domain_ontology.json:field_schema`

`field_schema.step` 写“步骤序号，从 1 起”，但 Agent 实际主用的是 `current_step_index` / `step_facts.step_index`（0-based），TraceEngine 的 `steps[i].step` 才是 1-based。本体作为“单一事实来源”却漏掉这套最关键的索引约定，会让 Agent/Judge 在“第 N 步”上与 `expected_facts` 产生歧义。

建议：`field_schema` 增加 `current_step_index`（0-based）与 `step_index`（0-based）说明，并明确“展示给用户时 +1”的约定。

### P3-1：模块字段读取缺少 get 兜底

**位置**：`src/graphs/javatutor/prompting/ontology.py`

`build_ontology_block()` 与 `build_judge_grounding_block()` 直接 `m['name']` / `m['id']`。本体文件由团队维护，当前无问题；若未来某模块漏填 `name` 会 KeyError。建议改为 `m.get('name', m.get('id', ''))`。

### P3-2：本体路径依赖文件层级

**位置**：`src/graphs/javatutor/prompting/ontology.py:16`

`ONTOLOGY_PATH = Path(__file__).resolve().parents[4] / ...` 依赖文件恰好在四层目录下。若后续移动 `ontology.py`，路径会静默失效。建议像其他工具脚本一样，用 `ROOT = Path(__file__).resolve().parents[2]` 或引入统一根路径解析。

## 验证

- `uv run pytest -q`：129 passed。
- `AGENT.md` 已登记本体计划与 devlog。
- 未提交，符合用户 git 约束。

## 修复记录

- **P2**：`field_schema` 新增 `current_step_index` / `step_index`（0-based）说明及「展示 +1」约定。
- **P3-1**：`build_ontology_block` / `build_judge_grounding_block` 改用 `.get()` 兜底，漏填 `name` 不再 KeyError。
- **P3-2**：`ONTOLOGY_PATH` 改为向上查找 `pyproject.toml` 定位仓库根，不再依赖目录层级。
- 验证：`uv run pytest -q` → 130 passed。

## 遗留

- 确定性 grounding 核对器仍未实现，属后续计划。
- 本体块随 `Role & Policies` 参与压缩，超长时仍有截断风险（devlog 已记录）。
