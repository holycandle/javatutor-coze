"""UI 面板导航：从单一事实源 ui-panel-manifest.json 生成主 Agent 的视角导航引导与面板导航图。

与 ``ontology``（本体）互补：本体描述模块结构/字段映射，本模块描述「网页右侧 INSPECT 区有哪些面板、
用户问什么时该导航到哪」，供主 Agent 输出 ``【视角导航】`` 结构化块定位到对应面板。

事实源：``assets/knowledge/ui-panel-manifest.json``（由前端 ``javatutor/frontend/src/constants/ui-panel-manifest.json``
经 ``scripts/sync_panel_manifest.py`` 同步而来）。改面板结构必先改前端 manifest，勿在本文件硬编码面板清单。
"""

import json
from functools import lru_cache
from pathlib import Path

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
    """生成 SYSTEM_PROMPT_MAIN_AGENT 的【视角导航】指引段（替换原先硬编码在 prompts.py 的块）。"""
    manifest = load_manifest()
    single = "、".join(_format_panel(p) for p in _single_panels(manifest))
    multi = "、".join(_format_panel(p) for p in _multi_only_panels(manifest))
    sub_tabs = "|".join(manifest["algorithmLibrary"]["subTabs"])
    return (
        "当回答有助于用户定位到某个面板时，可在回答末尾（【决策痕迹】之前）追加一个「视角导航块」，前端会渲染成可点击卡片：\n"
        "【视角导航】\n"
        '{"views":[{"panel":"tutor","sub":"analysis","label":"分析"}]}\n\n'
        "规则：\n"
        f"- panel 取值（单文件）：{single}；\n"
        f"- 多文件项目额外支持：{multi}；\n"
        "- sub 仅当 panel 为 tutor 时使用：analysis(分析)/explain(解说)；其他 panel 不要带 sub；\n"
        f'- algo 仅当 panel 为 algorithm 时使用（精确定位算法库子页）：{{"subTab":"{sub_tabs}","categoryId":"tree","anchorId":"..."}}；\n'
        "- 仅当某面板能帮用户直接看到相关分析时才附卡，通常 1 个、最多 3 个；\n"
        "- 每个回答最多一个【视角导航】块；没有合适面板时整个省略，不要发空壳块；\n"
        "- 导航要融入回答，不要为了导航而发消息；\n"
        f"- tutor 仅当想让用户看 agent 的解说/分析时用；「去哪看 X」应指向内容面板（variables/flow/datastructure/algorithm/…），不要指向 tutor（用户已在 agent 面板）。"
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
