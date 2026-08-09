"""Task 4: SVG 动画生成器测试."""

import json
import pytest
from pathlib import Path

from learning.animation import build_animation_svg, classify_algorithm

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name):
    """加载动画测试数据 fixture."""
    if not FIXTURES.exists():
        pytest.skip(f"fixtures directory not found at {FIXTURES}")
    data = json.loads((FIXTURES / "animation_data.json").read_text(encoding="utf-8"))
    return data.get(name, [])


@pytest.mark.parametrize(
    ("source_code", "expected"),
    [
        ("public class BubbleSort {}", "sort"),
        ("int idx = binarySearch(arr, 7);", "search"),
        ("void dfs(TreeNode root)", "tree"),
        ("dijkstra(graph, start)", "graph"),
        ("int[][] dp = new int[n][m];", "dp"),
        ("class ListNode { int val; ListNode next; }", "linked_list"),
        ("public class Main {}", "other"),
    ],
)
def test_classify_algorithm(source_code, expected):
    assert classify_algorithm(source_code) == expected


def test_build_animation_svg_other_fallback():
    """兜底模板渲染: other 类别返回占位 SVG."""
    svg = build_animation_svg([], "unknown")
    assert svg.startswith("<svg")
    assert "暂不支持" in svg or "暂无模板" in svg


def test_sort_svg_has_bars_animate_and_values():
    """sort 动画: 柱状图 + 交换动画."""
    svg = build_animation_svg(_fixture("sort"), "sort")
    assert svg.startswith("<svg")
    assert "<animate" in svg
    assert "5" in svg
    assert "bar-0" in svg


def test_search_svg_has_scanline_and_animate():
    """search 动画: 柱状图 + 扫描线."""
    svg = build_animation_svg(_fixture("search"), "search")
    assert svg.startswith("<svg")
    assert "<animate" in svg
    assert "bar-0" in svg


def test_tree_svg_has_circles_and_animate():
    """tree 动画: 节点圆圈 + 高亮动画."""
    svg = build_animation_svg(_fixture("tree"), "tree")
    assert svg.startswith("<svg")
    assert "<circle" in svg
    assert "<animate" in svg


def test_graph_svg_has_lines_and_animate():
    """graph 动画: 边线 + 边染色动画."""
    svg = build_animation_svg(_fixture("graph"), "graph")
    assert svg.startswith("<svg")
    assert "<line" in svg
    assert "<animate" in svg


def test_dp_svg_has_cells_and_animate():
    """dp 动画: 表格单元格 + 当前格高亮."""
    svg = build_animation_svg(_fixture("dp"), "dp")
    assert svg.startswith("<svg")
    assert "cell-0-0" in svg
    assert "<animate" in svg


def test_linked_list_svg_has_nodes_and_animate():
    """linked_list 动画: 节点方块 + 指针动画."""
    svg = build_animation_svg(_fixture("linked_list"), "linked_list")
    assert svg.startswith("<svg")
    assert "node-0" in svg
    assert "<animate" in svg
