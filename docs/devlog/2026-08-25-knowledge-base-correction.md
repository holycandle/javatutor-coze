# 2026-08-25 项目知识库核对与扩充

> 涉及仓库：`javatutor-coze`（分支 `fix/knowledge-base-corrections`）
> 状态：已完成

## 背景

领域本体（`javatutor_domain_ontology.json`）为 AI 生成，未经人工核对，存在多处与 JavaTutor 前端真实实现不符的描述；项目知识（`javatutor_project.json`）仅 4 条，过薄。

## 改动内容

### 1. 领域本体核对修正

对照 JavaTutor 前端真实组件逐条核对，修正 6 处：

- 变量卡片：`data_field` 由 `steps[i].variables` 改为 `steps[i].stackFrames[*].locals`（主来源）+ `variables`（回退），并注明非独立面板、位于「内存监控」栈区。
- 堆面板 / 调用栈：补充说明同属「内存监控」面板。
- 堆面板 `ui_behavior`：「刷新」→「字段/槽值变化时荧光高亮」。
- 控制流图：补「点击 call 节点下钻子方法」，「高亮分支」→「按当前行高亮对应节点」。
- 控制台 `ui_behavior`：「追加显示」→「展示当前步骤为止累积输出」。
- AI 讲解面板：补「复杂度」「算法标签」两个分页。

### 2. 项目知识扩充

`javatutor_project.json` 由 4 条扩至 11 条，新增：内存监控面板结构、变量卡片数据来源、单步播放机制、堆对象与对象 id、控制流图、控制台输出、运行与提问工作流。

## 验证结果

| 门槛 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `uv run pytest -q` | 134 passed |

## 遗留问题

- 本体数据依赖人工维护；JavaTutor 后端字段变化时需同步 `field_schema`。
