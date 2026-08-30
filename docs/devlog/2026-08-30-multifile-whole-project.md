# 开发日志：多文件 / 整体项目理解 Phase 2（2026-08-30）

> 执行依据：`docs/spec/2026-08-30-multifile-whole-project-design.md` + `docs/plan/2026-08-30-multifile-whole-project-plan.md`。
> 前置：Phase 1（`docs/devlog/2026-08-30-fetch-execution-context-as-tool.md`）已把 `fetch_execution_context` 改为纯 state 读取工具。

## 原因

Phase 1 让 agent 能按需读取整体代码，但 payload / state 只有单一 `source_code`，agent 无法感知「项目」维度——多个类、文件间关系、跨文件回答无从谈起。本次注入策略=「概览 + 按需读(最省)」：**恒注入项目结构概览 + 主入口**，其他文件由 agent 经 `fetch_execution_context(file="...")` 按需读。

## 改动

### Coze 侧（`javatutor-coze` 仓）

| 文件 | 改动 |
|---|---|
| `src/tools/fetch_execution_context.py` | 新增 `normalize_files`（兼容 dict / `{name,code}` / `{path,code}`）；激活 `file` 参数（`_resolve_code` + `_step_file`，支持精确/忽略大小写/basename 匹配）；结果加 `file` / `current_step_file` / `fetched_context.project_files` / `run_context_memory.files_count`。basename 用 `rsplit` 实现，**未 import `os`**（维持 Phase 1「无环境依赖」约定） |
| `src/graphs/javatutor/state.py` | 新增 `files` / `entry_file` / `current_step_file` 字段 |
| `src/graphs/javatutor/nodes.py` | `_parse_json_dict` 经 `normalize_files` 归一化 `files`，解析 `entry_file`，从 `steps[current_step_index].file` 取 `current_step_file` |
| `src/graphs/javatutor/context_builder.py` | `gather()` 在 `state.files` 非空时注入 `### 项目结构` 概览（`_file_type_hint` 提炼类型名/行数，token 极小） |
| `src/graphs/javatutor/prompts.py` | `SYSTEM_PROMPT_MAIN_AGENT` 增加多文件读取提示 |
| `src/tools/step_facts.py` | `_evidence_source` 按当前执行步所在文件（`current_step_file` / `state.files`）取代码，`evidence` 附 `file` |

### JavaTutor 侧（`JavaTutor` 仓，见 `docs/plan/2026-08-30-multifile-envelope-plan.md`）

| 文件 | 改动 |
|---|---|
| `backend/.../model/ExplainRequest.java` | 新增 `files`（`List<Map<String,String>>`）+ `entryFile` + getter/setter |
| `backend/.../service/CozeService.java` | `buildAgentPayload` / `streamExplain` 增加 `files`/`entryFile` 参数并写入 payload（runId + 旧分支）；blocking 重载补 `null, null` |
| `backend/.../controller/CozeAIController.java` | SSE `streamExplain` 调用处传 `request.getFiles()` / `request.getEntryFile()` |
| `backend/.../service/CozeServicePayloadTest.java` | `withRunIdBuildsFullEnvelope` 断言 `files`+`entry_file`；新增 `withNulFilesOmitsKeys` |
| `frontend/src/stores/player.js` | `askQuestion` body 发 `files`/`entryFile`；`stepSnapshots` 补 `file` |

## 验证结果

| 门槛 | 命令 | 结果 |
|---|---|---|
| Coze 全量单测 | `uv run pytest -q` | **171 passed**（新增 12 多文件用例） |
| Coze L3 构建 | `build_flow_graph().compile()` | 成功 |
| JavaTutor 后端全量 | `mvn test` | **108 tests** 全绿（新增 `withNulFilesOmitsKeys`） |
| JavaTutor 前端构建 | `npm run build` | 通过 |
| JavaTutor 前端测试 | `npm test` | 22 文件 **209 tests** 通过 |

## 遗留 / 注意事项

- 前后端 + Coze 需**一起上线**：重新构建/部署 JavaTutor；Coze 平台重新发布 agent（先后端后 coze）。
- `entry_file` 本轮前端发 `multiState.entryFile || ''`（当前 store 未显式维护该值）；`current_step_file` + `step_facts` 按当前步文件取证据是「当前步正确性」的硬保证，行号不再随用户切换的激活文件漂移。
- 未引入 `search_knowledge` / `read_code` 等额外工具；不把文件全量预注入 prompt。
- 前端 `stepSnapshots` 补 `file` 依赖步骤数据自带 `file`（后端执行时已记录），若某步无 `file` 则空串、回退单文件逻辑。
