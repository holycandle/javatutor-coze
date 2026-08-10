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
    """意图识别结果: data_query | concept | debug | animate | other."""

    algorithm_tags: list
    """analyze 专家返回的算法/数据结构标签列表，用于动画分类优先."""

    # === 专家回答 ===
    answer: str
    """最终回答文本，由专家节点填充."""

    svg_text: str
    """动画分支生成的 SVG 文本，非动画分支为空字符串."""

    # === 深化链路状态 ===
    intent_confidence: float
    """意图分类置信度 0-1."""

    retrieved_chunks: list[dict]
    """RAG 检索到的知识库片段."""

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
