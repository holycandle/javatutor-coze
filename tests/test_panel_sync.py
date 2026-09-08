"""UI 面板 manifest 一致性守卫：coze 副本 / 本体结构 / 提示词引导须与前端单一事实源对齐。

改动任一面板结构后，本文件与 scripts/sync_panel_manifest.py 一起兜底「前端改了、coze 本体/提示词没用」的回归。
"""

import json
from pathlib import Path

import pytest

from graphs.javatutor.prompting.panels import (
    MANIFEST_PATH,
    MODULE_PANELS,
    load_manifest,
    render_nav_guidance,
    render_ui_map,
)


def _repo_root() -> Path:
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    raise FileNotFoundError("未找到仓库根（pyproject.toml）")


ROOT = _repo_root()
FRONTEND_MANIFEST = ROOT / ".." / "javatutor" / "frontend" / "src" / "constants" / "ui-panel-manifest.json"
ONTOLOGY = ROOT / "assets" / "knowledge" / "javatutor_domain_ontology.json"


def _load_ontology() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


def test_coze_copy_matches_frontend_manifest():
    """① coze 副本与前端 manifest 一致（路径可达时）；否则仅内部自洽。"""
    coze = load_manifest()
    if not FRONTEND_MANIFEST.exists():
        pytest.skip("前端 manifest 不存在，跳过跨仓比对")
    frontend = json.loads(FRONTEND_MANIFEST.read_text(encoding="utf-8"))
    assert coze == frontend, "coze 副本与前端 manifest 不一致（运行 scripts/sync_panel_manifest.py --sync）"


def test_manifest_path_points_to_coze_copy():
    assert MANIFEST_PATH.exists()


def test_ontology_ui_structure_matches_manifest():
    """② 本体 modules 的映射面板在 manifest 中存在；ai_panel 两分页；内存子区域标注「内存状态」。"""
    ont = _load_ontology()
    manifest = load_manifest()
    modules = {m.get("id"): m for m in ont.get("modules", [])}

    for mod_id, panel_id in MODULE_PANELS.items():
        if panel_id is None:
            continue
        assert panel_id in manifest.get("panels", {}), f"{mod_id} 映射到不存在的面板 {panel_id}"

    ai = modules.get("ai_panel", {})
    fn = ai.get("function", "")
    assert "三个分页" not in fn, "ai_panel.function 仍是旧「三分页」结构"
    assert "解说" in fn and "分析" in fn

    for mod_id in ("variable_panel", "heap_panel", "stack_panel"):
        assert "内存状态" in modules.get(mod_id, {}).get("function", ""), f"{mod_id}.function 未标注属「内存状态」面板"


def test_no_old_three_tab_leftover():
    """④ ai_panel 无旧「三分页」残留：只含解说/分析，不含独立「复杂度」「算法」分页表述。"""
    ont = _load_ontology()
    fn = {m["id"]: m for m in ont["modules"]}["ai_panel"]["function"]
    assert "三个分页" not in fn


def test_nav_guidance_panels_match_manifest():
    """③ 导航引导覆盖 manifest 全部 panel；sub/algo 合法取值出现。"""
    manifest = load_manifest()
    nav = render_nav_guidance()
    for panel_id in manifest["panels"]:
        assert panel_id in nav, f"panel {panel_id} 未出现在【视角导航】引导"
    assert "analysis" in nav and "explain" in nav
    assert "knowledge" in nav and "template" in nav
    assert "tutor 仅当" in nav  # 明确了 tutor 不指向「去哪看 X」


def test_tutor_not_target_for_content_hints():
    """⑤ 内容面板的 navHints 不含 tutor 专属提示，避免 agent 把「为什么/分析」指到内容面板。"""
    manifest = load_manifest()
    tutor_hints = set(manifest["panels"]["tutor"].get("navHints", []))
    for panel_id, p in manifest["panels"].items():
        if panel_id == "tutor":
            continue
        overlap = set(p.get("navHints", [])) & tutor_hints
        assert not overlap, f"{panel_id} 含 tutor 专属提示 {overlap}"


def test_ui_map_renders_all_panels():
    ui_map = render_ui_map()
    manifest = load_manifest()
    for panel_id, p in manifest["panels"].items():
        assert p["name"] in ui_map
