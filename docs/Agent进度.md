---
date created: 2026-08-25
updated: 2026-08-25
author: okiso
---
## 未做（我目前想到的可能方向）
1. 更多的工具（比如针对多文件的解析等等）
2. Harness工程（HITL等）
3. JavaTutor项目知识库的完善和核对（这块ai生成可能不太好）
4. 利用评估数据做后训练微调（个人觉得可以做）

## 已做（可以完善）
#### 工具(`src\tools\`)
1. step_facts: 获取每步变量快照（Agent自主调用）
2. fetch_execution_code: 调用后端api，获取用户执行代码和当前执行步(**固定节点**，执行即调用)
3. analyze_code: 分析代码的算法标签和复杂度(**固定节点**，执行即调用)
#### 记忆系统
1. 目前只有一种会话内工作记忆：`src\learning\memory.py`
	- 含过期处理、容量限制、重要性排序等
#### RAG
- rag操作指南（含灌库指令）：`docs\rag-knowledge-guide.md`
- 灌库与检索脚本：`src\learning\knowledge.py`
- 知识库：`assets\knowledge`
	1. 常见编译错误集（`error_quickref.json`）
	2. Java常用类集（`java_std.json`）
	3. JavaTutor项目知识（`javatutor_domain_ontology.json`）
#### 上下文工程（`build_context`）
- **Gather**：从 state 收集所有候选数据包——用户问题、源代码、RAG 片段、分析结果、运行上下文摘要、当前执行位置、会话记忆、最近 5 条历史。
- **Select**：按 `0.7*相关性 + 0.3*时间衰减` 打分，在 token 预算内（默认 3000，预留 20%）选包。
- **Structure**：把选中的包按 `Role & Policies / Task / Evidence / Memory / Context / Output` 分区排版。
- **Compress**：超预算时按段落截断。
#### 评审专家（`src\graphs\javatutor\critic.py`）
- 对主Agent的输出结果**事实核查+单轮修订**
#### 评估系统(`eval\`)
- 工作方式：设定好**样本集**，指定问题和答案，本地自己连接Judge大模型，根据**评分标准**，评估agent的回答，输出**评测结果**，包含json和人读报告
- 开发者评估指南：`docs\dev-eval-guide.md`
- 样本集：`samples\`
- 评分标准（给Judge的Prompt）：`judge_prompt.md`
- 评测结果：`archive\`