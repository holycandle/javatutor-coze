"""JavaTutor 智能体 — 状态 schema."""

from typing import Annotated, Any, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class JavaTutorState(TypedDict, total=False):
    """JavaTutor 对话流程的统一状态 schema."""

    # === 原始输入 ===
    # 使用 add_messages reducer：每步追加新消息而非替换
    messages: Annotated[list[AnyMessage], add_messages]
    """LangGraph 消息历史，parse_context 读取最后一条消息的 JSON."""

    # === 解析后的执行数据 ===
    source_code: str
    """用户提交的 Java 源代码全文."""

    steps: list[dict]
    """执行步骤列表，每个元素为 step dict."""

    steps_json: str
    """steps 的 JSON 字符串，供 LLM 上下文使用."""

    steps_count: int
    """总步骤数."""

    has_steps: bool
    """是否有执行步骤数据（steps 非空）."""

    current_step_index: int
    """用户当前所在的步骤索引."""

    current_line: int
    """用户当前所在的源代码行号."""

    current_variables: dict
    """当前步骤的变量快照，键值对."""

    # === 用户信息 ===
    user_question: str
    """用户的自然语言问题."""

    user_id: str
    """用户唯一标识，缺失时为空字符串."""

    # === 错误信息 ===
    compile_error: str
    """Java 编译/运行时错误信息，缺失时为空字符串."""

    has_error: bool
    """compile_error 非空时为 True，用于短路 debug 分支."""

    # === 意图路由 ===
    intent: str
    """意图识别结果: data_query | concept | debug | analyze | other."""

    algorithm_tags: list
    """analyze 专家返回的算法/数据结构标签列表."""

    # === 专家回答 ===
    answer: str
    """最终回答文本，由专家节点填充."""

    # === 深化链路状态 ===
    intent_confidence: float
    """意图分类置信度 0-1."""

    retrieved_chunks: list[dict]
    """RAG 检索到的知识库片段（**只含越阈值者**，消费方语义不变）."""

    retrieval_debug: dict
    """RAG 全量候选与阈值判定，供决策痕迹诊断。

    与 ``retrieved_chunks``（越阈值结果）分开：前者含**被阈值滤掉的候选**，
    使「没召回到」与「召回到但被阈值滤掉」在 trace 里可区分。检索失败时仍存在
    （``candidates == []``），以区别「失败」与「成功但无匹配」。
    """

    context_summary: str
    """上下文压缩摘要."""

    critic_feedback: str
    """评审反馈."""

    revised_answer: str
    """修订后的回答."""

    decision_trace: dict
    """决策痕迹，用于输出给前端."""

    rag_degraded: bool
    """RAG 检索是否降级（失败时 True）."""

    critic_skipped: bool
    """评审是否跳过（异常时 True）."""

    revise_skipped: bool
    """修订是否跳过（异常时 True）."""

    compaction_mode: str
    """压缩模式: none | windowed | truncated."""

    fallback_reason: str
    """降级原因."""

    critic_passed: bool
    """评审是否通过."""

    revised: bool
    """是否已修订."""

    # === 新架构字段 ===
    analysis_result: dict
    """analyze_code 确定性节点产生的复杂度/算法/数据结构分析结果."""

    memories: list[dict]
    """会话工作记忆中检索到的历史记忆."""

    context_built: str
    """GSSC 构建后的最终上下文文本."""

    tool_rounds: int
    """主 Agent 工具循环执行的轮数."""

    tool_calls: list
    """主 Agent 工具循环实际执行的工具调用记录（含 tool 与 args），用于评测工具调用准确率."""

    token_usage: dict
    """本次回答的 token 消耗：prompt_tokens / completion_tokens / estimated."""

    request_started_at: float
    """本次请求进入图的时间戳（time.time()，由 parse_context 写入），用于计算 latency_ms."""

    step_memories: list
    """step_facts 成功查询后写入工作记忆的单步证据记录（importance 0.8，最多保留 5 条）."""

    # === 执行上下文获取（新 envelope） ===
    run_id: str
    """JavaTutor 后端本次运行生成的 run_id."""

    fetch_context_failed: bool
    """fetch_execution_context 是否失败."""

    fetch_context_latency_ms: float
    """fetch_execution_context 请求耗时，单位毫秒."""

    fetch_context_error: str
    """fetch_execution_context 失败时的可读错误."""

    run_context_memory: dict
    """本轮运行上下文的紧凑摘要，禁止保存完整 source_code 与 steps."""

    fetched_context: dict
    """读取工具暂存的执行上下文快照：run_id / source_code / steps / current_step_index /
    current_line / compile_error / algorithm_tags / code_hash / fetched_at / fetch_context_latency_ms."""

    files: dict[str, str]
    """项目全部文件：文件名 -> 源码。来自入站 payload 的 files，经 normalize_files 归一化。

    source_code 仍是行号映射锚点（由 entry_file 锚定，缺省为激活文件）；files 供 agent 按需读取其他文件。"""

    entry_file: str
    """主入口文件名（可选）。存在时 fetch_execution_context 无 file 参数时默认读该文件；行号锚点=该文件。"""

    run_mode: str
    """本次运行后端采用的模式：``"test"`` | ``"default"`` | ``""``（缺失，即旧客户端）。

    **事实**由前端随每次提问送来（后端透传），语义（两种模式各要求什么）只写在本仓知识与引导里。
    缺失（``""``）表示**模式未知**，不得默认按 ``"default"`` 解释。"""

    test_case_count: int
    """本次运行已保存的测试用例数；``run_mode`` 缺失时为 0。"""

    current_step_file: str
    """当前步（steps[current_step_index]）所在文件，来自该 step 的 file 字段。供 agent 自证「当前步在哪个文件」，step_facts 据此对齐。"""

    # === Harness：图内真环（提案 / 治理 / 执行 / 客观核对）===
    agent_messages: list[AnyMessage]
    """主 Agent 循环的**累积**消息序列（System/Human/AI/Human...），构成真 ReAct 轨迹。

    与 ``messages`` 分开：``messages`` 是入站契约（parse_context 读其最后一条，
    平台 stream_mode="messages" 与它耦合），不能被循环过程污染。"""

    proposed_action: dict
    """propose 节点产出的提案（Action 的 dict 形态：tool / args / raw，或 parse_error）。

    存 dict 而非 dataclass：状态要能进 checkpointer 的 checkpoint。"""

    guard_decision: dict
    """最近一次门闩裁决（verdict / policy / reason / options）。"""

    step_records: list
    """逐动作的 Observation 记录（原则⑦的 StepRecord），供决策痕迹、评测与 B 端可观测。"""

    served_step_indices: list
    """本请求内已成功查询过的 step_index（0-based），供门闩 P5 判重复查询。"""

    fetched_injected: bool
    """本请求是否已把执行上下文读进 state（自动前置 fetch 或模型显式 fetch 都会置位）。"""

    verification: dict
    """verify 节点的确定性 grounding 核对结果：applicable / checked / violations / hallucinated 等。"""
