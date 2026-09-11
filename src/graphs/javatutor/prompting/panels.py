"""UI 面板导航：从单一事实源 ui-panel-manifest.json 生成主 Agent 的视角导航引导与面板导航图。

与 ``ontology``（本体）互补：本体描述模块结构/字段映射，本模块描述「网页右侧 INSPECT 区有哪些面板、
用户问什么时该导航到哪」，供主 Agent 输出 ``【视角导航】`` 结构化块定位到对应面板。

事实源：``assets/knowledge/ui-panel-manifest.json``（由前端 ``javatutor/frontend/src/constants/ui-panel-manifest.json``
经 ``scripts/sync_panel_manifest.py`` 同步而来）。改面板结构必先改前端 manifest，勿在本文件硬编码面板清单。
"""

import json
from functools import lru_cache
from pathlib import Path

from graphs.javatutor.prompting.ontology import load_ontology

# 本体模块 id → 导航面板 id；None 表示该模块不是独立导航目标（不参与导航/校验）。
MODULE_PANELS = {
    "editor": None,
    "variable_panel": "variables",
    "heap_panel": "variables",
    "stack_panel": "variables",
    "control_flow_panel": "flow",
    "console_panel": None,  # 控制台随「内存状态」面板展示，但非独立导航目标
    "algo_viz_panel": "datastructure",
    "ai_panel": "tutor",
    "step_playback": None,
}


def _repo_root() -> Path:
    """向上定位仓库根（含 pyproject.toml），不依赖本模块所在目录层级。"""
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    raise FileNotFoundError("未找到仓库根（pyproject.toml）")


MANIFEST_PATH = _repo_root() / "assets" / "knowledge" / "ui-panel-manifest.json"


@lru_cache(maxsize=1)
def load_manifest() -> dict:
    """读取 UI 面板 manifest（coze 副本），结果缓存。"""
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


ALGO_INDEX_PATH = _repo_root() / "assets" / "knowledge" / "algo-knowledge-index.json"


@lru_cache(maxsize=1)
def load_algo_index() -> dict:
    """读取算法知识目录（coze 副本，源自 frontend/src/assets/algo-knowledge/index.json）。"""
    return json.loads(ALGO_INDEX_PATH.read_text(encoding="utf-8"))


def _single_panels(manifest: dict) -> list[dict]:
    """单文件模式可用的面板（排除 mode=multi）。"""
    return [
        {"id": pid, **p}
        for pid, p in manifest["panels"].items()
        if p.get("mode") != "multi"
    ]


def _multi_only_panels(manifest: dict) -> list[dict]:
    """多文件模式额外可用、单文件不可用的面板（mode=multi）。"""
    return [
        {"id": pid, **p}
        for pid, p in manifest["panels"].items()
        if p.get("mode") == "multi"
    ]


def _format_panel(p: dict) -> str:
    return f"{p['id']}({p['name']})"


def render_nav_guidance() -> str:
    """生成 SYSTEM_PROMPT_MAIN_AGENT 的【视角导航】指引段，**以导航边界（闭集）为首要原则**。

    边界不立清楚，agent 会从能想到的面板里硬凑（如在「测试模式」这类非面板主题上附无关卡）。
    故把「可导航集合 = 固定闭集 + 非面板主题不可附卡」写成显式规则；「流程问题不附卡」只是其自然推论。
    """
    manifest = load_manifest()
    single = "、".join(_format_panel(p) for p in _single_panels(manifest))
    multi = "、".join(_format_panel(p) for p in _multi_only_panels(manifest))
    sub_tabs = " / ".join(manifest["algorithmLibrary"]["subTabs"])
    return (
        "可导航目标**只有且仅有**这些面板（闭集）：\n"
        f"- 单文件：{single}；\n"
        f"- 多文件额外支持：{multi}；\n"
        '- 算法库可通过 algo 细分，示例：{"subTab":"knowledge","categoryId":"tree","anchorId":"后序遍历"}（定位「树（堆）→后序遍历」）；subTab 合法取值：'
        f'{sub_tabs}；algo 仅用于 panel=algorithm。\n'
        "- **除上述之外不存在任何导航目标**：测试模式、运行代码、输入用例、文件管理、设置等「操作/流程」主题对应不到任何面板，**不可附卡**，直接给操作步骤（见「使用流程指南」）。\n"
        "- 只有当用户想**直接看某个面板里已有的分析/可视化**时才值得附 1 张卡；不要为了导航而导航、不要用无关面板硬凑。\n\n"
        "当回答有助于用户定位到某个面板时，可在回答末尾追加「视角导航块」，前端会渲染成可点击卡片：\n"
        "【视角导航】\n"
        '{"views":[{"panel":"tutor","sub":"analysis","label":"分析"}]}\n\n'
        "放置与取值规则：\n"
        "- 【视角导航】追加在回答**最末尾**，紧邻【决策痕迹】之前；**块之后不要再写任何正文**。\n"
        "- 每个回答最多一个【视角导航】块；没有合适面板时整块省略，不要发空壳块；导航要融入回答。\n"
        "- sub 仅当 panel 为 tutor 时使用：analysis(分析)/explain(解说)；其他 panel 不要带 sub。\n"
        "- tutor 仅当想让用户看 agent 的解说/分析时用；「去哪看 X」应指向内容面板（variables/flow/datastructure/algorithm/…），不要指向 tutor（用户已在 agent 面板）。"
    )


def render_ui_map() -> str:
    """生成「UI 面板导航图」——按顶层组列出各面板展示什么，以及用户问什么时该导航到哪。"""
    manifest = load_manifest()
    lines: list[str] = ["UI 面板导航图（用户在网页右侧 INSPECT 区看到的模块，按顶层组）："]
    for group, panel_ids in manifest["groups"].items():
        items = []
        for pid in panel_ids:
            p = manifest["panels"].get(pid)
            if not p:
                continue
            suffix = "（多文件专属）" if p.get("mode") == "multi" else ""
            items.append(f"{p['name']}{suffix}（{pid}，{p['content']}）")
        if items:
            lines.append(f"- {group}：{'；'.join(items)}")
    lines.append("")
    lines.append("导航提示（用户问以下内容时，应导航到对应面板）：")
    for pid, p in manifest["panels"].items():
        hints = p.get("navHints") or []
        if hints:
            lines.append(f"- 「{'/'.join(hints)}」→ {p['name']}（{pid}）")
    return "\n".join(lines)


def render_algo_catalog() -> str:
    """生成「算法知识目录」——分类 id + 标题 + 锚点 id 清单，供 algo 精确定位落到分类/锚点。

    事实源：assets/knowledge/algo-knowledge-index.json（源自 frontend/src/assets/algo-knowledge/index.json）。
    锚点 id 为中文全称（如「后序遍历」），不要用英文缩写生成 anchorId。不存在的 categoryId/anchorId 前端会回退默认、不崩。
    """
    data = load_algo_index()
    lines: list[str] = ["算法知识目录（算法库「算法知识」子页的合法分类与锚点 id）："]
    for cat in data.get("categories", []):
        anchors = "、".join(f"{a.get('title')}（{a.get('id')}）" for a in cat.get("anchors", []))
        lines.append(f"- {cat.get('title')}（categoryId={cat.get('id')}）；锚点：{anchors}")
    return "\n".join(lines)


def render_usage_guide() -> str:
    """生成「使用流程指南」——运行/测试模式/查看输出/单步播放/分析页等操作流程。

    事实源：本体 assets/knowledge/javatutor_domain_ontology.json 的 user_guides。
    用于让 agent 知道测试模式等「操作/流程」主题**存在且如何用**，从而正确给步骤而非附导航卡。
    """
    ont = load_ontology()
    guides = ont.get("user_guides") or []
    lines: list[str] = ["使用流程指南（用户询问这些操作/流程时回答实际步骤，**不应附导航卡**）："]
    for g in guides:
        steps = "；".join(g.get("steps", []))
        lines.append(f"- {g.get('topic')}：{steps}")
        if g.get("note"):
            lines.append(f"  - 说明：{g['note']}")
    return "\n".join(lines)
