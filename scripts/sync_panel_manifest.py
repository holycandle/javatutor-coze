"""同步/校验 UI 面板 manifest：前端单一事实源 → coze 副本；并校验本体 UI 面板结构一致。

用法：
    uv run python scripts/sync_panel_manifest.py            # 仅校验，存在 drift 则退出非 0
    uv run python scripts/sync_panel_manifest.py --sync      # 用前端 manifest 覆盖 coze 副本

事实源：``../javatutor/frontend/src/constants/ui-panel-manifest.json``。
coze 副本：``assets/knowledge/ui-panel-manifest.json``（此后端读取，供 prompting/panels.py）。
本体结构字段（modules 的 id/name/子页）与 manifest 的对应关系由 ``MODULE_PANELS`` 校验。
"""

import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    raise FileNotFoundError("未找到仓库根（pyproject.toml）")


ROOT = _repo_root()
# 脚本以裸 python 运行（非 pytest），需手动把 src 加入 sys.path 才能 import graphs 包
sys.path.insert(0, str(ROOT / "src"))

from graphs.javatutor.prompting.panels import MODULE_PANELS  # noqa: E402


FRONTEND_MANIFEST = ROOT / ".." / "javatutor" / "frontend" / "src" / "constants" / "ui-panel-manifest.json"
COZE_MANIFEST = ROOT / "assets" / "knowledge" / "ui-panel-manifest.json"
ONTOLOGY = ROOT / "assets" / "knowledge" / "javatutor_domain_ontology.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, data: dict) -> None:
    # 用固定缩进与 ensure_ascii=False 规范化，避免行尾/空白抖动导致误报 drift
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def check_coze_copy(sync: bool) -> int:
    """coze 副本与前端 manifest 一致；--sync 时覆盖。"""
    if not FRONTEND_MANIFEST.exists():
        print(f"[warn] 前端 manifest 不存在：{FRONTEND_MANIFEST}，跳过跨仓比对")
        return 0
    frontend = _load(FRONTEND_MANIFEST)
    coze = _load(COZE_MANIFEST)
    if frontend == coze:
        print("coze 副本与前端 manifest 一致")
        return 0
    if sync:
        _dump(COZE_MANIFEST, frontend)
        print("已用前端 manifest 覆盖 coze 副本")
        return 0
    print("DRIFT: coze 副本与前端 manifest 不一致（可加 --sync 覆盖）")
    return 1


def check_ontology() -> int:
    """本体 modules 的 UI 面板结构须与 manifest / MODULE_PANELS 一致。"""
    if not ONTOLOGY.exists():
        print(f"[warn] 本体不存在：{ONTOLOGY}，跳过本体校验")
        return 0
    ont = _load(ONTOLOGY)
    manifest = _load(COZE_MANIFEST)
    modules = {m.get("id"): m for m in ont.get("modules", [])}
    errs: list[str] = []

    for mod_id, panel_id in MODULE_PANELS.items():
        if panel_id is None:
            continue
        if panel_id not in manifest.get("panels", {}):
            errs.append(f"本体模块 {mod_id} 映射到不存在面板 {panel_id}")

    ai = modules.get("ai_panel", {})
    fn = ai.get("function", "")
    if "三个分页" in fn or ("复杂度" in fn and "算法" in fn and "分析" not in fn):
        errs.append("ai_panel.function 仍是旧「三分页」结构，应为解说/分析两分页")

    for mod_id in ("variable_panel", "heap_panel", "stack_panel"):
        m = modules.get(mod_id, {})
        if "内存状态" not in m.get("function", ""):
            errs.append(f"{mod_id}.function 未标注属「内存状态」面板子区域")

    if errs:
        for e in errs:
            print("DRIFT:", e)
        return 1
    print("本体 UI 面板结构与 manifest 一致")
    return 0


def main() -> int:
    sync = "--sync" in sys.argv
    code = 0
    code |= check_coze_copy(sync)
    code |= check_ontology()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
