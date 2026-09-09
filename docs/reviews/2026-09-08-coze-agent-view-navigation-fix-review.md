# 视角导航修复 + 面板知识单一事实源同步 Review

> 对应 plan：`docs/plan/2026-09-08-coze-agent-view-navigation-fix-plan.md`
> 审查日期：2026-09-08

## 结论

实现与 plan 一致，**全部测试通过，可合并/发布**。未发现阻断性问题。发现若干低危/一致性问题，建议后续顺手处理。

## 验证（全绿）

| 项 | 结果 |
|---|---|
| 前端 `npm run test` | ✅ 23 文件 / 245 用例 |
| coze `uv run pytest -q` | ✅ 211 通过 |
| `scripts/sync_panel_manifest.py`（check） | ✅ 无 drift（exit=0） |
| coze 副本 == 前端 manifest | ✅ 跨仓比对一致 |
| `test_panel_sync.py`（本体/提示词/引导一致性） | ✅ |

## 与 plan 的一致性（通过）

- **单一事实源**：前端 `ui-panel-manifest.json` 被 `player.js` 白名单（`switchRightTab`/`switchMultiTab`）、两个 shell 分组映射、`NavSuggestionCard` 过滤消费；coze `prompting/panels.py` 读副本生成 `【视角导航】` 引导 + 「UI 面板导航图」。✅
- **`algo` 精确定位**（spec §3.1.1）：`navigateTo(panel, sub, algo)` + 复用 `openTutorial`；前端 `editSuggestion.js` `normalizeAlgo` 解析。✅
- **本体修正**：`ai_panel` 改「解说/分析」两分页；`variable_panel/heap_panel/stack_panel` 标注「内存状态」。✅
- **`tutor` 不作「去哪看 X」导航目标**：引导 + 测试 `test_tutor_not_target_for_content_hints`。✅
- **CRITIC 拦截提升**：非法 panel/sub/algo 按「中等问题」处理（可判失败）。✅
- **韧性修复**：`NavSuggestionCard` 按 `store.mode` 过滤（P2）、`navigateTo` 的 `sub` 白名单（P3）。✅

## 发现的问题（低危 / 一致性）

### P4（低）- 术语不一致：manifest/本体「内存状态」vs UI 面板头「内存监控」
- **位置**：`ui-panel-manifest.json` `variables.name`、本体 `variable_panel/heap_panel/stack_panel.function`；
  UI 面板头实际显示「内存监控」（`MemoryPanel.vue:6`）。
- **影响**：agent/导航卡用「内存状态」，用户看到的面板头是「内存监控」，轻微歧义。
- **建议**：统一为 UI 实际显示的「内存监控」（或相反），并同步 manifest、本体、`test_panel_sync.py` 断言。

### P5（低）- `render_ui_map()` 未区分单/多文件，observe 组含 multi-only 面板
- **位置**：`prompting/panels.py:92-108`。
- **影响**：单文件语境下导航图仍列出 `callgraph/classdiagram/structure`，agent 可能据此提议多文件面板。
  前端 `NavSuggestionCard` 已按 mode 过滤兜底（无死按钮），仅导航建议层面不精准。
- **建议**：导航图按 mode 分组，或标注「多文件专属」。

### P6（极低）- `console_panel` 映射到 `variables` 语义存疑
- **位置**：`panels.py:20` `MODULE_PANELS`。
- **影响**：仅用于校验「映射面板是否存在」，不影响导航；但控制台与内存状态是不同 UI 元素，语义略误导。
- **建议**：可改为 `None` 或加注释说明「控制台非导航目标」。

### P7（极低）- `render_nav_guidance()` 计算 `sub_tabs` 未使用
- **位置**：`panels.py:72`。
- **影响**：死代码；且若改 `algorithmLibrary.subTabs`，该变量不随动（引导里 hardcode `"knowledge|template"`）。
- **建议**：删除，或改为实际引用（用 `sub_tabs` 拼出 `algo.subTab` 合法取值）。

### P8（极低）- `navigateTo` 带 `algo.subTab='template'` 且同时有 `categoryId` 时，`openTutorial` 会把子页重置回 `knowledge`
- **位置**：`player.js` `navigateTo` + `openTutorial`。
- **影响**：仅当 agent 同时发 `template`+`categoryId`（少见）时发生；categoryId 定位本就属于 knowledge 子页，行为可接受。
- **建议**：可加注释说明该顺序，避免后续误改。

## 建议

- **P4/P5 值得顺手处理**（术语对齐、UI 导航图按 mode 分组）；P6/P7/P8 可选。
- 不阻断发布；发布/验证前的关键一步是 `npm run dev` 手验 P1/P2/P3 三个用例（算法模板 / 内存状态 / 树算法知识）。

## 文档登记

- 对应 plan：`docs/plan/2026-09-08-coze-agent-view-navigation-fix-plan.md`。
- 关联 spec：`docs/spec/2026-09-07-coze-agent-view-navigation.md` §3.1.1 / §9。
- 实现 devlog：`docs/devlog/2026-09-08-coze-agent-view-navigation-fix.md`。
