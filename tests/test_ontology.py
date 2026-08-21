"""JavaTutor 领域本体：数据文件与加载器测试。"""

from graphs.javatutor.prompting.ontology import (
    build_judge_grounding_block,
    build_ontology_block,
    load_ontology,
)

STEPS_FIELDS = ("step", "line", "variables", "heap", "stackFrames", "output")
MODULE_IDS = (
    "editor",
    "variable_panel",
    "heap_panel",
    "stack_panel",
    "control_flow_panel",
    "console_panel",
    "algo_viz_panel",
    "ai_panel",
    "step_playback",
)


def test_load_ontology_has_required_sections():
    data = load_ontology()
    assert "modules" in data
    assert "field_schema" in data
    assert "data_contract_rules" in data


def test_field_schema_covers_all_steps_fields():
    data = load_ontology()
    for field in STEPS_FIELDS:
        assert field in data["field_schema"], f"field_schema 缺字段 {field}"


def test_field_schema_records_index_convention():
    """P2: field_schema 应记录 0-based 索引约定与展示 +1."""
    schema = load_ontology()["field_schema"]
    assert "current_step_index" in schema
    assert "step_index" in schema
    assert "0-based" in schema["current_step_index"]
    assert "+1" in schema["current_step_index"]


def test_modules_cover_all_panels():
    ids = {m["id"] for m in load_ontology()["modules"]}
    for module_id in MODULE_IDS:
        assert module_id in ids, f"modules 缺模块 {module_id}"


def test_build_ontology_block_contains_module_and_mapping():
    block = build_ontology_block()
    assert "变量卡片" in block
    assert "堆面板" in block
    # field_schema 的字段 → 面板映射文本
    assert "heap" in block and "堆面板" in block


def test_data_contract_rules_anti_hallucination():
    rules = load_ontology()["data_contract_rules"]
    joined = "\n".join(rules)
    assert "禁止编造引擎内部机制" in joined


def test_build_judge_grounding_block_has_fields_and_modules():
    block = build_judge_grounding_block()
    assert "stackFrames" in block
    assert "堆面板" in block
    assert "JavaTutor 领域本体" in block
