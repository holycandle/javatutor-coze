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

    # === 专家回答 ===
    answer: str
    """最终回答文本，由专家节点填充."""
