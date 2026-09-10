# Coze Agent 视角导航 健壮性修复（裸 JSON / 算法库细化 / 非面板流程知识）（2026-09-09）

> 一句话：针对 2026-09-09 联调新报的 3 处导航问题（裸 JSON 上屏 / 算法库无法细化 / 测试模式误附导航卡），
> 以「**前端解析健壮性** + **coze 导航边界（闭集）立清** + **算法目录/使用流程知识注入**」为主修复，并补主 Agent 集中式 few-shot 提升契约遵循度。

## 1. 背景

2026-09-08 修复落地后联调（`docs/reviews/2026-09-08-coze-agent-view-navigation-fix-review.md` P1–P3 已过），
但 2026-09-09 又报 3 处：

- **P1**：「后序遍历的知识在哪看」把 `【视角导航】` 的**原始 JSON 渲染进了正文**，卡无效。
- **P2**：算法库定位粒度只到「算法库」，无法落到「算法库-算法知识-树（堆）」等细分类/锚点。
- **P3**：「怎么打开测试模式」agent 称「没有测试模式入口」，并**误加导航卡**（查看内存变量/执行流程）。

执行依据 `docs/plan/2026-09-09-coze-agent-view-navigation-robustness-fix-plan.md`。

## 2. 根因

- **问题 1**：`editSuggestion.js` 的 `extractStructBlocks` 假设结构块是**正文最后一段**；agent 在块后补正文即 `JSON.parse` 失败 →
  `usable=false` → 块未剥离、按正文渲染 → 裸 JSON 上屏。
- **问题 2**：① schema 耦合——agent 把 `sub`/`categoryId`/`anchorId` 放**顶层**而非 `algo:{...}`，前端 `normalizeAlgo(v.algo)`
  见 `v.algo` undefined → 全部定位被丢弃；② 缺目录——agent 不知道合法分类/锚点 id 全集；③ 示例 anchorId `post-order-traversal`
  是错的（真实锚点 id 是中文全称「后序遍历」）；④ manifest 的 `categories` 是不全死数据。
- **问题 3**：**导航边界未立清**——agent 不知道「只能导航固定那 8 块面板、测试模式等主题根本不在可导航集合」，于是从能想到的面板里硬凑；
  且本体缺「运行/测试模式」使用流程知识，agent 断言「没有测试模式入口」。

## 3. 实现

### A. 前端（`javatutor/frontend`）

- **`utils/editSuggestion.js`**：
  - 新增 `parseJsonAt(text, start)`：只取与首字符配对的**平衡 JSON 区间**（`{…}`/`[…]`，处理字符串/转义），与块后正文**解耦**。块后正文原样保留在 body。
  - `extractStructBlocks` 改为：从后往前逐块用 `parseJsonAt` 尝试；成功且产出 ≥1 可用项则移除该段（`markIdx → jsonEnd`），否则保留；
    处理完 `trim` + `collapseBlankLines` 折叠 3 连空行。
  - 新增 `normalizeView(v)`：算法库缺 `algo` 时**回收顶层** `subTab`/`sub`/`categoryId`/`anchorId` 拼回 `algo`（兼容 schema 耦合）。
- **测试**：`editSuggestion.test.js` 增朴「块后跟正文仍剥离并产出 nav」「顶层 sub/categoryId/anchorId 回收为 algo」「编辑+导航+块后正文混排」；
  `decisionTrace.test.js` 增「块后跟正文也剥离」。

### B. coze（`javatutor-coze`）

- **`prompting/panels.py`**：
  - `load_algo_index()`（lru_cache 读 coze 副本 `assets/knowledge/algo-knowledge-index.json`）+ `render_algo_catalog()`：
    产出算法库「算法知识」页的**分类 id + 标题 + 锚点 id 清单**（锚点为中文全称，如「后序遍历」）。
  - `render_usage_guide()`：读本体 `user_guides`，产出「运行/测试模式/查看输出/单步播放/分析页」使用流程，
    并明确「这些操作/流程**不应附导航卡**」。
  - `render_nav_guidance()` 重写为**以边界（闭集）为首要原则**：列明可导航目标只有且仅有那 8 块面板 + algo 细分；
    **「除此之外不存在任何导航目标」**——测试模式、运行代码等操作/流程主题**不可附卡**；追加放置规则「块在回答最末尾、
    紧邻【决策痕迹】之前，块后不要再写正文」。（「流程问题不附卡」只是边界清晰后的自然推论，非独立单例规则。）
- **`prompting/main_fewshots.py`**（新建）：`MAIN_FEW_SHOTS` 集中存放主 Agent 样本（算法模板、测试模式→不附卡、
  后序遍历→algo 定位、变量查看→variables 卡），提升结构契约遵循度与回答准确率（可审查/可迭代）。
- **`main_agent.py` `_main_system_prompt()`**：注入 `render_nav_guidance() + render_algo_catalog() + render_usage_guide() + render_ui_map() + MAIN_FEW_SHOTS`（走 SystemMessage，不被 compress 截断）。
- **本体 `javatutor_domain_ontology.json`**：新增顶层 `user_guides`（运行代码 / 测试模式 / 查看运行输出 / 单步播放 / 复杂度与算法标签）；
  顺带把 `variable_panel.common_confusions` 的「内存监控」改为「内存状态」（P4 补漏）。

### C. 清理死数据

- 前端 `ui-panel-manifest.json` 与 coze 副本删除 `algorithmLibrary.categories`（5 类不全、前端/coze 均未消费），
  改由 B1 的 `algo-knowledge-index.json` 统一维护，避免两面漂移。

### B4 守卫（scripts / 测试）

- **`scripts/sync_panel_manifest.py`**：新增 `check_algo_copy()` 比对/同步算法目录副本（`--sync` 覆盖）。
- **`tests/test_panel_sync.py`**：新增——算法目录副本跨仓一致、`render_algo_catalog` 含全部分类与锚点 id、
  `user_guides` 覆盖「测试模式/运行代码」、`render_nav_guidance` 闭集边界（「不存在任何导航目标」+「不可附卡」+「块后不写正文」）、
  `MAIN_FEW_SHOTS` 含合法 `panel/sub/algo` 形态与「非面板主题不附卡」样例且无裸结构块。

## 4. 测试

- 前端 `vitest`：**23 文件 / 249 全绿**（+4：editSuggestion 3、decisionTrace 1）。
- coze `pytest`：**217 全绿**（+6：test_panel_sync 新增守卫）。
- `scripts/sync_panel_manifest.py`：**无 drift（EXIT=0）**（含算法目录副本比对）。

### 4.1 review 加固（2026-09-09 review 后落地）

按 `docs/reviews/2026-09-09-coze-agent-view-navigation-robustness-fix-review.md` 的 R1–R4 处理（均低危，不阻断发布）：

- **R1 文档同步**：spec §3.1.1 `categoryId` 改「合法全集见 algo-knowledge/index.json」；§9.1 删除已不存在的 `algorithmLibrary.categories`，
  改述「算法知识目录独立成源并同步 coze 副本」；§9.2 补 `render_algo_catalog`/`render_usage_guide`/`MAIN_FEW_SHOTS`；§9.3 增算法目录同步/校验。
- **R2 引导给具体示例**：`render_nav_guidance()` 的 algo 行改为可照抄示例 `{"subTab":"knowledge","categoryId":"tree","anchorId":"后序遍历"}`，
  `subTab` 合法取值另用 `knowledge / template` 说明（不再用易被误读为字面值的泛型占位）。
- **R3 样本标记**：`main_fewshots.py` 沿用旧 `fewshots.MARKER`，`get_main_few_shots()` 给每个样本前置「（示例，步骤号/行号/变量名必须替换为本次真实数据）」。
- **R4 术语统一**：本体 `user_guides` 把「内存状态」面板内控制台统一为「控制台（位于「内存状态」面板）」。

## 5. 待执行 / 注意

- coze 侧改动需**重新发布 agent**（`prompts.py`/`main_agent.py`/`panels.py`/本体/`main_fewshots.py`）+ 前端 `npm run dev` 热载。
- `main_agent.py` 改运行时拼装后，需确认 `test_main_agent.py` 无对系统提示原文的强断言（本次 pytest 全绿已覆盖）。
- 手验：`npm run dev` 跑 P1/P2/P3 三用例（块后正文 / 树（堆）定位 / 测试模式→分步不附卡）。
- 冒泡→「插入排序」误判队友在修，本计划不处理。

## 6. 涉及文件

- 前端：`src/utils/editSuggestion.js` + `editSuggestion.test.js`，`src/utils/decisionTrace.test.js`，`src/constants/ui-panel-manifest.json`
- coze：`src/graphs/javatutor/prompting/panels.py`、`src/graphs/javatutor/main_agent.py`、`src/graphs/javatutor/prompting/main_fewshots.py`（新建）、
  `assets/knowledge/javatutor_domain_ontology.json`、`assets/knowledge/algo-knowledge-index.json`（新建）、`assets/knowledge/ui-panel-manifest.json`、
  `scripts/sync_panel_manifest.py`、`tests/test_panel_sync.py`
- 文档：`docs/plan/2026-09-09-coze-agent-view-navigation-robustness-fix-plan.md`
