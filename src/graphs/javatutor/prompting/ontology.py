"""JavaTutor 领域本体：结构化产品知识（模块 / 字段映射 / 数据契约规则）。

与 ``glossary``（术语表）互补：glossary 提供词汇级定义，本体提供模块结构、
steps 字段到前端面板的映射、以及回答时的数据契约（含反幻觉）规则。

本体作为单一事实来源存放在 ``assets/knowledge/javatutor_domain_ontology.json``，
由本模块加载并格式化为常驻 prompt 块（必达层）。
"""

import json
from functools import lru_cache
from pathlib import Path


def _repo_root() -> Path:
    """向上定位仓库根（含 pyproject.toml），不依赖 ontology.py 所在目录层级。"""
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    raise FileNotFoundError("未找到仓库根（pyproject.toml）")


ONTOLOGY_PATH = _repo_root() / "assets" / "knowledge" / "javatutor_domain_ontology.json"


@lru_cache(maxsize=1)
def load_ontology() -> dict:
    """读取本体 JSON，结果缓存。"""
    return json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))


def build_ontology_block() -> str:
    """把 modules + field_schema + data_contract_rules 格式化成常驻 prompt 文本块。"""
    data = load_ontology()
    lines: list[str] = []

    lines.append("模块总览：")
    for m in data.get("modules", []):
        field = m.get("data_field") or "（无独立步骤字段）"
        lines.append(f"- {m.get('name', m.get('id', ''))}（{m.get('id')}）：{m.get('function', '')}；数据来源 {field}")
        confusions = m.get("common_confusions") or []
        if confusions:
            lines.append(f"  常见困惑：{'；'.join(confusions)}")

    lines.append("数据字段 → 面板映射：")
    for key, desc in data.get("field_schema", {}).items():
        lines.append(f"- `{key}`：{desc}")

    lines.append("数据契约规则：")
    for rule in data.get("data_contract_rules", []):
        lines.append(f"- {rule}")

    return "\n".join(lines)


def build_judge_grounding_block() -> str:
    """供 Judge 使用的精简本体：字段 schema + 模块白名单，作为 grounding 知识基础。"""
    data = load_ontology()
    fields = "、".join(f"`{k}`" for k in data.get("field_schema", {}))
    modules = "、".join(m.get("name", m.get("id", "")) for m in data.get("modules", []))
    return (
        "JavaTutor 领域本体：\n"
        f"- 合法 steps 字段：{fields}\n"
        f"- 合法产品模块：{modules}"
    )
