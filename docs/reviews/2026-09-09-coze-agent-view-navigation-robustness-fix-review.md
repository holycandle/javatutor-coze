# 视角导航 健壮性修复 Review（裸 JSON / 算法库细化 / 测试模式边界）

> 对应 plan：`docs/plan/2026-09-09-coze-agent-view-navigation-robustness-fix-plan.md`
> 审查日期：2026-09-09

## 结论

实现与 plan 一致，**三处 bug 均已修复，双端全绿，可合并/发布**。未发现阻断性问题。主要遗留一项文档一致性：spec §9 未随实现同步（描述 manifest `algorithmLibrary.categories`，但实现已删除该字段）。另有一处低危引导泛型。

## 验证（全绿）

| 项 | 结果 |
|---|---|
| 前端 `npx vitest run` | ✅ 23 文件 / 249 用例（原 245 +4） |
| coze `uv run pytest -q` | ✅ 217 通过（原 211 +6） |
| `scripts/sync_panel_manifest.py` | ✅ 无 drift（exit=0，三行「一致」） |
| coze 算法目录副本 == 前端 `algo-knowledge/index.json` | ✅ |
| 双端 manifest（`algorithmLibrary.categories` 均已删除） | ✅ 一致 |

## 与 plan 的一致性（通过）

- **问题 1（裸 JSON）**：`editSuggestion.js` `extractStructBlocks` 改用 `parseJsonAt` 平衡提取，块后正文保留，不再因块后有文字而把整个结构块当正文。✅（含 `【编辑建议】` 同款隐患一并修复）
- **问题 2（算法库细化）**：`normalizeView` 宽容回收顶层 `sub/subTab/categoryId/anchorId` → `algo`；coze `render_algo_catalog()` 注入全量分类+锚点 id；few-shot 给具体 `algo` 样例。✅
- **问题 3（测试模式）**：`render_nav_guidance()` 以**导航边界=闭集**为首要原则（「只有且仅有」「除上述之外不存在任何导航目标」「不可附卡」）；本体增 `user_guides`；`render_usage_guide()` 注入；few-shot 含「测试模式→不附卡」样例。✅（未再用「流程问题不附卡」这一对单例过拟合的独立规则，核心理念正确）
- **B5 few-shot**：`main_fewshots.py` + `_main_system_prompt()` 注入（SystemMessage，不再被 compress 截断）。✅
- **C 清理**：双端 manifest 删除 `algorithmLibrary.categories` 死数据。✅

## 发现的问题（低危 / 一致性）

### R1（低）- spec §9 未随实现同步：仍描述 manifest `algorithmLibrary.categories`、未提 algo 目录单一源
- **位置**：`docs/spec/2026-09-07-coze-agent-view-navigation.md` §9.1(188)/§9.2/§9.3。
- **现状**：§9.1/§9.2 说 manifest 定义 `algorithmLibrary.categories`；§9.3 只讲同步 manifest 与本体。但实现**已删除** manifest 的 `categories`，改为以
  `frontend/src/assets/algo-knowledge/index.json` 为单一源，同步到 coze `assets/knowledge/algo-knowledge-index.json`，并由 `render_algo_catalog()` 消费。
- **影响**：spec 是契约文档，仍会引导开发者认为「算法目录在 manifest」，与实现脱节；且 §3.1.1 的 categoryId 列表只列 5 类（缺 fundamentals/dp），同样过期。
- **建议**：spec §9 改为：`algorithmLibrary` 只含 subTabs；算法目录单一源 = `algo-knowledge/index.json`（新增 §9.5 或并入）；§9.3 增 algo 目录的同步/校验；§3.1.1 的 categoryId 清单改为「见算法知识目录」。

### R2（低）- `render_nav_guidance()` 的 algo 示例是泛型占位，非具体可照抄示例
- **位置**：`panels.py render_nav_guidance()` 边界行。
- **现状**：示例为 `{"subTab":"knowledge|template","categoryId":"<分类id>","anchorId":"<锚点id>"}`——subTab 显示成「knowledge|template」、categoryId/anchorId 是 `<...>` 占位，非 plan 想要的 `{"subTab":"knowledge","categoryId":"tree","anchorId":"后序遍历"}` 这类可直接照抄的值。
- **影响**：功能不受影响（`render_algo_catalog` + few-shot 已给具体值），但引导本身没有「能直接抄的范例」；泛型 `knowledge|template` 有被误读为字面值的风险。
- **建议**：给一个具体示例（如 `tree`/`后序遍历`），或删除该泛型行、把具体值统一放 `render_algo_catalog`。

### R3（极低）- `main_fewshots.py` 样本缺「仅示意」标记
- **位置**：`main_fewshots.py`。
- **影响**：样本含具体数值（如「arr[1] 由 3 变成 5」）但无旧 `fewshots.py` 的「（示例，步骤号/行号/变量名必须替换为本次真实数据）」标记，模型照抄有轻微幻觉风险（靠 critic/revise 兜底）。
- **建议**：给样本加统一「仅示意，需替换为真实数据」前置说明，或沿用旧 fewshots 的 MARKER 风格。

### R4（极低）- `render_usage_guide()` 把「控制台」归入「内存状态」面板，与 `console_panel` 术语张力
- **位置**：本体 `user_guides`（查看运行输出 / 测试模式）。
- **影响**：不影响导航/正确性（控制台并非独立导航目标），但本体既有 `console_panel`（「控制台面板」）与 usage guide 的「『内存状态』面板内控制台区域」表述略有出入，术语未完全统一。
- **建议**：统一为「控制台（位于「内存状态」面板）」，或明确 console 仍是独立内容区。

## 建议

- **R1 值得处理**（spec 是契约文档，过期会持续误导）；R2 顺手；R3/R4 可选。
- 不阻断发布。发布/验证前关键一步：`npm run dev` 手验 P1/P2/P3 三用例（算法模板 / 树算法知识 / 测试模式不附卡）。

## 文档登记

- 对应 plan：`docs/plan/2026-09-09-coze-agent-view-navigation-robustness-fix-plan.md`。
- 实现 devlog：`docs/devlog/2026-09-09-coze-agent-view-navigation-robustness-fix.md`。
- 前置 review：`docs/reviews/2026-09-08-coze-agent-view-navigation-fix-review.md`。
