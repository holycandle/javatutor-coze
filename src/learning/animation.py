"""JavaTutor SVG 动画生成器：从 TraceEngine steps 生成带 SMIL 动画的纯 SVG 文本。"""

import json
import math
from pathlib import Path
from typing import Any

from jinja2 import Template

WIDTH = 600
HEIGHT = 400
MARGIN = 40
STEP_DURATION = 0.6

COLOR_DEFAULT = "#4f8cff"
COLOR_COMPARE = "#ffd166"
COLOR_CURRENT = "#ef476f"
COLOR_VISITED = "#06d6a0"

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "assets" / "svg_templates"
# 模板文件名映射（category 名 → 模板文件名）
TEMPLATE_FILES = {
    "sort": "sort_bars.svg.j2",
    "search": "search_bars.svg.j2",
    "tree": "tree_traversal.svg.j2",
    "graph": "graph_path.svg.j2",
    "dp": "dp_table.svg.j2",
    "linked_list": "linked_list.svg.j2",
    "other": "other.svg.j2",
}

SUPPORTED = tuple(TEMPLATE_FILES.keys())


def _map_tags_to_category(names: list) -> str | None:
    """根据 analyze 算法/数据结构标签名映射动画类别；命中返回类别，未命中返回 None。"""
    text = " ".join(str(n) for n in (names or [])).lower()
    rules = [
        (
            (
                "冒泡", "bubble", "选择", "selection", "插入", "insertion",
                "快速", "快排", "quick", "归并", "merge", "堆", "heap",
                "计数", "counting", "桶", "bucket", "基数", "radix", "希尔", "shell",
            ),
            "sort",
        ),
        (
            ("二分", "binary", "查找", "search", "线性", "linear"),
            "search",
        ),
        (
            ("树", "tree", "遍历", "前序", "preorder", "中序", "inorder",
             "后序", "postorder", "层序", "level", "dfs", "bfs", "二叉"),
            "tree",
        ),
        (
            ("图", "graph", "dijkstra", "最短路径", "prim", "kruskal", "拓扑"),
            "graph",
        ),
        (
            ("动态规划", "动态", "dp", "背包", "knapsack", "最长公共", "子序列"),
            "dp",
        ),
        (
            ("链表", "linked", "listnode", "环形", "cycle"),
            "linked_list",
        ),
    ]
    for kws, cat in rules:
        if any(k in text for k in kws):
            return cat
    return None


def classify_algorithm(source_code: str) -> str:
    code = (source_code or "").lower()
    if any(
        k in code
        for k in (
            "bubble",
            "冒泡",
            "selection",
            "选择",
            "insertion",
            "插入",
            "quick",
            "快排",
            "merge",
            "归并",
            "sort",
        )
    ):
        return "sort"
    if any(k in code for k in ("binary", "二分", "linear", "线性", "search", "查找")):
        return "search"
    if any(
        k in code
        for k in ("dfs", "bfs", "tree", "树", "traversal", "遍历", "前序", "中序", "后序")
    ):
        return "tree"
    if any(k in code for k in ("dijkstra", "prim", "graph", "图", "最短路径")):
        return "graph"
    if any(k in code for k in ("dp", "动态规划", "背包", "knapsack", "最长公共")):
        return "dp"
    if any(k in code for k in ("linkedlist", "linked list", "链表", "listnode")):
        return "linked_list"
    return "other"


def _as_list(value: Any) -> list:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return value if isinstance(value, list) else []


def _number(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _series_from_steps(steps: list[dict]) -> list[list[int]]:
    series = []
    for step in steps:
        variables = step.get("variables") or {}
        for key in ("arr", "array", "nums", "list"):
            values = _as_list(variables.get(key))
            if values:
                series.append([_number(v) for v in values])
                break
    return series


def _bar_layout(values: list[int]) -> list[dict]:
    n = max(1, len(values))
    max_value = max(values) if values else 1
    plot_w = WIDTH - 2 * MARGIN
    plot_h = HEIGHT - 2 * MARGIN
    bar_w = plot_w / n
    bars = []
    for i, value in enumerate(values):
        h = plot_h * value / max_value if max_value else 0
        x = MARGIN + i * bar_w
        y = HEIGHT - MARGIN - h
        bars.append(
            {
                "index": i,
                "value": value,
                "x": round(x, 1),
                "y": round(y, 1),
                "width": round(max(4.0, bar_w - 4), 1),
                "height": round(h, 1),
            }
        )
    return bars


def _load_template(category: str) -> str:
    filename = TEMPLATE_FILES.get(category, "other.svg.j2")
    path = TEMPLATE_DIR / filename
    if not path.exists():
        return (
            "<svg xmlns='http://www.w3.org/2000/svg' width='600' height='400'>"
            "<text x='20' y='40'>暂无模板</text></svg>"
        )
    return path.read_text(encoding="utf-8")


def build_animation_svg(steps: list[dict], algorithm_tag: str = "sort") -> str:
    category = algorithm_tag if algorithm_tag in SUPPORTED else "other"
    if category == "sort":
        data = _render_sort(steps)
    elif category == "search":
        data = _render_search(steps)
    elif category == "tree":
        data = _render_tree(steps)
    elif category == "graph":
        data = _render_graph(steps)
    elif category == "dp":
        data = _render_dp(steps)
    elif category == "linked_list":
        data = _render_linked_list(steps)
    else:
        data = {"message": "暂不支持该算法的动画演示"}
    return Template(_load_template(category)).render(**data)


def _render_sort(steps: list[dict]) -> dict:
    series = _series_from_steps(steps)
    if not series:
        return {"bars": [], "move_groups": {}, "highlight_groups": {}, "message": "暂无执行数据"}
    bars = _bar_layout(series[0])
    move_groups = {i: [] for i in range(len(bars))}
    highlight_groups = {i: [] for i in range(len(bars))}
    bar_w = (WIDTH - 2 * MARGIN) / len(bars)
    for step_i in range(1, len(series)):
        prev, cur = series[step_i - 1], series[step_i]
        begin = round((step_i - 1) * STEP_DURATION, 2)
        for i in range(len(cur)):
            if i < len(prev) and prev[i] != cur[i]:
                highlight_groups[i].append({"begin": begin})
            if i < len(prev) and prev[i] != cur[i] and cur[i] in prev:
                j = prev.index(cur[i])
                if i != j:
                    move_groups[i].append(
                        {
                            "from_x": round(MARGIN + j * bar_w, 1),
                            "to_x": round(MARGIN + i * bar_w, 1),
                            "begin": begin,
                        }
                    )
    return {
        "bars": bars,
        "move_groups": move_groups,
        "highlight_groups": highlight_groups,
        "message": "",
    }


def _render_search(steps: list[dict]) -> dict:
    series = _series_from_steps(steps)
    bars = _bar_layout(series[0]) if series else []
    scans = []
    bar_w = (WIDTH - 2 * MARGIN) / max(1, len(bars))
    for step_i, step in enumerate(steps):
        variables = step.get("variables") or {}
        pos = None
        for key in ("mid", "index", "pos", "position"):
            raw = variables.get(key)
            if raw is not None:
                pos = _number(raw)
                break
        if pos is None and series:
            pos = step_i % max(1, len(series[0]))
        if pos is not None and 0 <= pos < len(bars):
            scans.append(
                {
                    "x": round(MARGIN + pos * bar_w, 1),
                    "begin": round(step_i * STEP_DURATION, 2),
                    "found": bool(variables.get("found")),
                }
            )
    return {"bars": bars, "scans": scans, "message": ""}


def _render_tree(steps: list[dict]) -> dict:
    variables = (steps[0].get("variables") or {}) if steps else {}
    tree = [n for n in _as_list(variables.get("tree")) if isinstance(n, dict) and "id" in n]
    if not tree:
        return {"nodes": [], "edges": [], "highlight_groups": {}, "message": "暂无树数据"}
    node_map = {str(n["id"]): n for n in tree}
    children = {}
    for nid, node in node_map.items():
        left = node.get("left")
        right = node.get("right")
        children[nid] = [
            str(left) if left is not None else "",
            str(right) if right is not None else "",
        ]
    parent_ids = set()
    for kids in children.values():
        for kid in kids:
            if kid:
                parent_ids.add(kid)
    root_id = next((nid for nid in node_map if nid not in parent_ids), next(iter(node_map)))
    depth = {root_id: 0}
    queue = [root_id]
    while queue:
        cur = queue.pop(0)
        for kid in children.get(cur, []):
            if kid and kid in node_map and kid not in depth:
                depth[kid] = depth[cur] + 1
                queue.append(kid)
    ordered = [nid for nid in node_map if nid in depth]
    max_depth = max(depth.values()) if depth else 1
    plot_w = WIDTH - 2 * MARGIN
    plot_h = HEIGHT - 2 * MARGIN
    pos = {}
    for idx, nid in enumerate(ordered):
        x = WIDTH / 2 if len(ordered) == 1 else MARGIN + plot_w * idx / (len(ordered) - 1)
        y = MARGIN + plot_h * depth[nid] / max_depth
        pos[nid] = (x, y)
    nodes = [
        {
            "id": nid,
            "value": node_map[nid].get("value", ""),
            "x": round(pos[nid][0], 1),
            "y": round(pos[nid][1], 1),
        }
        for nid in ordered
    ]
    edges = []
    for nid, kids in children.items():
        if nid not in pos:
            continue
        for kid in kids:
            if kid in pos:
                edges.append(
                    {
                        "x1": round(pos[nid][0], 1),
                        "y1": round(pos[nid][1], 1),
                        "x2": round(pos[kid][0], 1),
                        "y2": round(pos[kid][1], 1),
                    }
                )
    highlight_groups = {nid: [] for nid in ordered}
    for step_i, step in enumerate(steps):
        highlight_nodes = _as_list((step.get("variables") or {}).get("highlight_nodes"))
        begin = round(step_i * STEP_DURATION, 2)
        for nid in highlight_nodes:
            key = str(nid)
            if key in highlight_groups:
                highlight_groups[key].append({"begin": begin})
    return {"nodes": nodes, "edges": edges, "highlight_groups": highlight_groups, "message": ""}


def _render_graph(steps: list[dict]) -> dict:
    variables = (steps[0].get("variables") or {}) if steps else {}
    graph = variables.get("graph") if isinstance(variables.get("graph"), dict) else {}
    nodes_in = [n for n in graph.get("nodes", []) if isinstance(n, dict) and "id" in n]
    edges_in = [e for e in graph.get("edges", []) if isinstance(e, dict) and "from" in e and "to" in e]
    if not nodes_in:
        return {
            "nodes": [],
            "edges": [],
            "node_highlights": {},
            "edge_highlights": {},
            "message": "暂无图数据",
        }
    cx, cy = WIDTH / 2, HEIGHT / 2
    radius = min(WIDTH, HEIGHT) / 2 - 60
    node_pos = {}
    for i, node in enumerate(nodes_in):
        angle = 2 * math.pi * i / len(nodes_in)
        node_pos[str(node["id"])] = (
            round(cx + radius * math.cos(angle), 1),
            round(cy + radius * math.sin(angle), 1),
        )
    nodes = [
        {
            "id": str(n["id"]),
            "value": n.get("value", ""),
            "x": node_pos[str(n["id"])][0],
            "y": node_pos[str(n["id"])][1],
        }
        for n in nodes_in
    ]
    edges = []
    for edge in edges_in:
        src, dst = str(edge["from"]), str(edge["to"])
        if src in node_pos and dst in node_pos:
            edges.append(
                {
                    "id": f"{src}->{dst}",
                    "x1": node_pos[src][0],
                    "y1": node_pos[src][1],
                    "x2": node_pos[dst][0],
                    "y2": node_pos[dst][1],
                }
            )
    node_highlights = {str(n["id"]): [] for n in nodes_in}
    edge_highlights = {e["id"]: [] for e in edges}
    for step_i, step in enumerate(steps):
        variables = step.get("variables") or {}
        begin = round(step_i * STEP_DURATION, 2)
        for nid in _as_list(variables.get("highlight_nodes")):
            key = str(nid)
            if key in node_highlights:
                node_highlights[key].append({"begin": begin})
        for eid in _as_list(variables.get("highlight_edges")):
            if eid in edge_highlights:
                edge_highlights[eid].append({"begin": begin})
    return {
        "nodes": nodes,
        "edges": edges,
        "node_highlights": node_highlights,
        "edge_highlights": edge_highlights,
        "message": "",
    }


def _render_dp(steps: list[dict]) -> dict:
    variables = (steps[0].get("variables") or {}) if steps else {}
    rows = [r for r in _as_list(variables.get("dp")) if isinstance(r, list)]
    if not rows:
        return {"cells": [], "highlight_groups": {}, "message": "暂无 DP 数据"}
    n_rows, n_cols = len(rows), max(len(r) for r in rows)
    plot_w = WIDTH - 2 * MARGIN
    plot_h = HEIGHT - 2 * MARGIN
    cell_w, cell_h = plot_w / n_cols, plot_h / n_rows
    cells = []
    highlight_groups = {}
    for r, row in enumerate(rows):
        for c in range(n_cols):
            key = f"{r}-{c}"
            x = MARGIN + c * cell_w
            y = MARGIN + r * cell_h
            cells.append(
                {
                    "row": r,
                    "col": c,
                    "key": key,
                    "value": row[c] if c < len(row) else "",
                    "x": round(x, 1),
                    "y": round(y, 1),
                    "width": round(cell_w, 1),
                    "height": round(cell_h, 1),
                    "cx": round(x + cell_w / 2, 1),
                    "cy": round(y + cell_h / 2, 1),
                }
            )
            highlight_groups[key] = []
    for step_i, step in enumerate(steps):
        variables = step.get("variables") or {}
        current = variables.get("dp_current")
        begin = round(step_i * STEP_DURATION, 2)
        if isinstance(current, list) and len(current) == 2:
            key = f"{_number(current[0])}-{_number(current[1])}"
            if key in highlight_groups:
                highlight_groups[key].append({"begin": begin})
    return {"cells": cells, "highlight_groups": highlight_groups, "message": ""}


def _render_linked_list(steps: list[dict]) -> dict:
    variables = (steps[0].get("variables") or {}) if steps else {}
    values = _as_list(variables.get("linked_list"))
    if not values:
        return {"nodes": [], "pointer_marks": [], "message": "暂无链表数据"}
    nodes = []
    spacing = 90
    for i, value in enumerate(values):
        x = MARGIN + i * spacing
        nodes.append({"index": i, "x": x, "cx": round(x + 30, 1), "value": value})
    pointer_marks = []
    for step_i, step in enumerate(steps):
        variables = step.get("variables") or {}
        pointer = variables.get("pointer")
        if pointer is not None:
            pointer = _number(pointer)
            if 0 <= pointer < len(nodes):
                pointer_marks.append(
                    {"x": round(nodes[pointer]["cx"], 1), "begin": round(step_i * STEP_DURATION, 2)}
                )
    return {"nodes": nodes, "pointer_marks": pointer_marks, "message": ""}
