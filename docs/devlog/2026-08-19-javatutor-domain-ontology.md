# 2026-08-19 JavaTutor 领域本体

## 改动内容

执行计划 `docs/plan/2026-08-19-javatutor-domain-ontology-plan.md`，建立结构化领域本体作为产品知识单一事实来源，并注入 Agent 与 Judge 的必达层。

1. **本体数据文件**（新增 `assets/knowledge/javatutor_domain_ontology.json`）
   - `modules`：9 个产品模块（编辑区/变量卡片/堆面板/调用栈/控制流图/控制台/算法可视化/AI 讲解面板/单步播放高亮行），每个含 id/name/function/data_field/ui_behavior/common_confusions。
   - `field_schema`：steps 六字段（step/line/variables/heap/stackFrames/output）到前端面板的映射。
   - `data_contract_rules`：3 条契约，含反幻觉规则「数据与源码冲突时指出异常并给预期值，禁止编造引擎内部机制」。

2. **加载器**（新增 `src/graphs/javatutor/prompting/ontology.py`）
   - `load_ontology()`（lru_cache）、`build_ontology_block()`（常驻层格式化）、`build_judge_grounding_block()`（Judge 精简版：字段 + 模块白名单）。

3. **注入 Agent 常驻层**（改 `src/graphs/javatutor/prompts.py`）
   - `build_system_prompt` 在「领域词汇」之后追加「领域本体」块，所有 intent 的 system prompt 均含本体（真正必达层常驻）。

4. **Judge 同步消费**（改 `eval/runner/judge.py`）
   - `build_judge_messages` 的 system 消息追加 `build_judge_grounding_block()`，为 grounding 判断提供合法字段/模块白名单。

## 验证结果

- 全量测试 `uv run pytest -q` → **129 passed**（新增 6 ontology + 1 graph 集成 + 1 judge）。
- L1 依赖锁 `uv sync --frozen` → 无变化（135 packages）。
- L3 离线构建 `build_agent().builder.compile()` → ok（本地无凭证回退 MemorySaver）。
- 常驻层实测：`build_system_prompt("other")` 2100 字符 / 1575 tokens，含模块名与契约规则。

## 遗留问题

- 本体块与 glossary/契约/版本共处 `Role & Policies`，当整体超过 `context_builder` 的 max_tokens（3000）时会被 `compress` 按块截断；本体块位于 role 之后的靠前位置，通常优先保留，但超长输入下契约/版本可能被截。
- 确定性 grounding 核对器（本体 `field_schema` + 模块白名单的程序化核对）未实现，仍靠 Judge 语义判断——属后续计划。
- 本体数据依赖人工维护；若 JavaTutor 后端字段变化需同步 `field_schema`。
