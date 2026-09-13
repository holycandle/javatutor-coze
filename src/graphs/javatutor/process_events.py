"""过程哨兵：把「已发生的事实」随节点返回值即时推给前端。

## 为什么需要哨兵

.. warning::
   初版此处写「``stream_mode="messages"`` **只转发节点返回值 ``messages`` 键里的消息**，
   聊天路径上只有 ``build_final`` 这么做，所以 propose / guard / run_tools / critic / revise
   的执行过程一个字节都出不到客户端」——**该前提已被实测证伪**（review 2026-09-13 §1.1）：
   该模式会把节点返回值里**所有键**的消息一起转出，``agent_messages`` 走 ``add_messages``
   reducer，故这些节点的产出**本来就在流上**（平台 SDK 只过滤 ``langgraph_node == "tools"``，
   其余非 chunk 的 ``AIMessage`` 一律转成 ``answer``）。代价是它们以**原始形态**
   （提案 JSON / 观察文本）混进用户可见的累加流——这正是用户报告的那个 bug。

   哨兵真正解决的不是「打开一条不存在的通道」，而是**给过程事实一个可渲染的表示**，
   并让前端能在渲染前把非同类的原生产出剥掉。

平台外壳（``src/main.py``，禁止修改）固定用 ``stream_mode="messages"``。

哨兵让**业务节点**把一条 HTML 注释形式的轻量消息放进返回值的 ``messages`` 键：
它作为普通 delta 流出 → Java 代理原样转发为 ``event:chunk`` → 前端在**渲染前**拦下
并转为进度 UI。**零外壳改动、零 Java 改动、零协议变更。**

## 格式

``\\n<!--jt:process {json}-->\\n``

用 HTML 注释是关键取舍：即使前端**未**拦截（老前端 + 新 Agent），也不会在界面上显出乱码
（实测前端 ``renderMarkdown`` 的自定义 renderer ``html()`` 返回空串，即**丢弃**哨兵；
且 marked 的 HTML 块规则会吞掉注释**之后同一行的剩余部分**——故两端 ``\n`` 是承重的）。
**最坏情况是「没有进度条」，而不是「界面上一堆乱码」。**

``kind`` 为**开放集合**（本期 ``stage`` 覆盖式 / ``tool`` 追加式），将来新增
``reasoning`` / ``retrieval`` 不必改协议。

## 边界

本模块**不 import 任何图内模块**（不 import ``state`` / ``nodes`` / ``graph``），
只依赖 stdlib 与 ``langchain_core.messages``，保持可脱离图单测。
"""

import json
import re
from typing import Any, Mapping

from langchain_core.messages import AIMessage

PROCESS_MARK_PREFIX = "<!--jt:process "
PROCESS_MARK_SUFFIX = "-->"

PROCESS_KWARG = "jt_process"
"""哨兵消息的 ``additional_kwargs`` 标记键：供 ``build_context`` 过滤历史、
``build_final`` / 测试判别哨兵。"""

# 连同两侧换行一起吞掉，使剥离后的正文与原文的散文部分**逐字相等**
# （``build_process_event`` 在两侧各加一个 ``\n``，不吞掉就会留下空行）。
_PROCESS_RE = re.compile(r"\n?<!--jt:process (.*?)-->\n?")


def _escape_terminator(payload: str) -> str:
    """把负载里的 ``-->`` 转义，避免解析正则提前截断。

    ``-->`` 只可能出现在 JSON 字符串内部（``-`` 在字符串外不是合法 JSON），
    故全局替换安全；``\\u003e`` 是合法 JSON 转义，解析后还原为 ``>``。
    """
    return payload.replace("-->", "--\\u003e")


def build_process_event(event: dict) -> str:
    """把一个过程事件编成哨兵文本（含两侧换行）。"""
    payload = _escape_terminator(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
    return f"\n{PROCESS_MARK_PREFIX}{payload}{PROCESS_MARK_SUFFIX}\n"


def parse_process_events(text: str) -> dict[str, Any]:
    """抽出所有哨兵，返回 ``{"clean": 剥净文本, "events": 事件列表}``。

    单条 JSON 解析失败或解析结果不是对象，**丢弃该条**：既不进 ``events``，
    也不留在 ``clean`` 里（哨兵是内部通道，任何情况下都不该当正文漏给用户）。
    """
    events: list[dict] = []

    def _take(match: re.Match) -> str:
        try:
            event = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            return ""
        if isinstance(event, dict):
            events.append(event)
        return ""

    clean = _PROCESS_RE.sub(_take, text)
    return {"clean": clean, "events": events}


def process_message(event: dict, state: Mapping[str, Any], seq: int) -> AIMessage:
    """构造一条过程哨兵消息（显式 id，供 ``build_final`` 精确 ``RemoveMessage`` 清理）。

    id 里带 ``request_started_at``：同一请求内靠 ``seq`` 唯一，跨请求靠时间戳唯一
    ——否则 ``add_messages`` 会因 id 相同而**替换**掉前一次的哨兵，而不只是追加。

    ``seq`` 由调用方显式给出而不能内部自增：同一次发射的多条事件若各自用
    ``len(process_event_ids)`` 当序号，会全部算出**同一个** id，``add_messages``
    只留最后一条，前面的静默丢失（实测踩过）。
    """
    request_id = state.get("request_started_at") or state.get("run_id") or "req"
    return AIMessage(
        content=build_process_event(event),
        id=f"jt-proc-{request_id}-{seq}",
        additional_kwargs={PROCESS_KWARG: True},
    )


def with_process_events(state: Mapping[str, Any], events: list[dict]) -> dict:
    """把若干事件包成哨兵消息与累计的 id 列表（返回的 dict 直接并入节点返回值）。

    节点返回值里带 ``messages`` 不代表污染入站契约：哨兵在节点执行期间**流出**，
    随后由 ``build_final`` 清除（见 ``state.py`` 的 ``process_event_ids``）。

    ``process_event_ids`` 无 reducer（返回即替换），故必须自行按旧值累加。
    """
    existing = list(state.get("process_event_ids") or [])
    messages = [process_message(ev, state, len(existing) + i) for i, ev in enumerate(events)]
    return {"messages": messages, "process_event_ids": existing + [m.id for m in messages]}
