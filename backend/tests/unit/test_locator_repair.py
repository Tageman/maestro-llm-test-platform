from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from maestro_app.application.locator_repair import (
    ControlledYamlSelectorRepairer,
    HierarchySelectorCandidate,
    UnsafeRepair,
)


def test_hierarchy_candidate_requires_one_evidence_backed_match() -> None:
    result = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {"elements": [{"txt": "确认设置(1)"}, {"txt": "返回"}]},
                    ensure_ascii=False,
                ),
            }
        ]
    }

    assert HierarchySelectorCandidate().select(result, "确认设置") == "确认设置(1)"


def test_hierarchy_candidate_rejects_ambiguous_matches() -> None:
    result = {"elements": [{"txt": "确认设置(1)"}, {"txt": "确认设置(2)"}]}

    assert HierarchySelectorCandidate().select(result, "确认设置") is None


def test_controlled_repair_changes_only_one_action_selector(tmp_path: Path) -> None:
    path = tmp_path / "flow.yaml"
    path.write_text(
        "appId: example.app\nname: demo\ntags: []\nproperties: {}\n---\n"
        "- tapOn: 页数\n- tapOn: 确认设置\n- assertVisible: 尽情发挥\n",
        encoding="utf-8",
    )

    patch = ControlledYamlSelectorRepairer().repair(path, "确认设置", "确认设置(1)")
    before = list(yaml.safe_load_all(patch.before_yaml))[1]
    after = list(yaml.safe_load_all(patch.after_yaml))[1]

    assert before[0] == after[0]
    assert before[2] == after[2]
    assert after[1] == {"tapOn": r"确认设置\(1\)"}
    assert "- - assertVisible" not in patch.diff
    assert "+- assertVisible" not in patch.diff
    assert "point" not in patch.after_yaml and "coordinates" not in patch.after_yaml


def test_controlled_repair_never_modifies_assertion(tmp_path: Path) -> None:
    path = tmp_path / "flow.yaml"
    path.write_text(
        "appId: example.app\nname: demo\ntags: []\nproperties: {}\n---\n"
        "- assertVisible: 确认设置\n",
        encoding="utf-8",
    )

    with pytest.raises(UnsafeRepair, match="exactly one"):
        ControlledYamlSelectorRepairer().repair(path, "确认设置", "确认设置(1)")


@pytest.mark.parametrize("command, expected", [
    ({"tapOn": {"text": "确定", "index": 0}}, {"tapOn": {"text": r"确定\(1\)", "index": 0}}),
    ({"scrollUntilVisible": {"element": "确定", "direction": "DOWN"}}, {"scrollUntilVisible": {"element": r"确定\(1\)", "direction": "DOWN"}}),
    ({"scrollUntilVisible": {"element": {"text": "确定"}}}, {"scrollUntilVisible": {"element": {"text": r"确定\(1\)"}}}),
])
def test_repair_supported_selector_shapes_only(tmp_path, command, expected):
    source = tmp_path / "flow.yaml"
    source.write_text(yaml.safe_dump({"appId": "example.app"}) + "---\n" + yaml.safe_dump(["back", command, {"assertVisible": "完成"}]))
    original = source.read_bytes()
    patch = ControlledYamlSelectorRepairer().repair(source, "确定", "确定(1)")
    assert list(yaml.safe_load_all(patch.after_yaml))[1] == ["back", expected, {"assertVisible": "完成"}]
    assert source.read_bytes() == original


@pytest.mark.parametrize("commands", [
    [{"tapOn": "确定"}, {"tapOn": "确定"}],
    [{"tapOn": {"id": "确定"}}],
    [{"scrollUntilVisible": {"element": {"id": "确定"}}}],
    [{"scrollUntilVisible": 1}], [{"tapOn": 1}],
    [{"tapOn": "确定", "inputText": "禁止"}],
])
def test_ambiguous_or_unsupported_repair_targets_rejected(tmp_path, commands):
    source = tmp_path / "flow.yaml"
    source.write_text("appId: example.app\n---\n" + yaml.safe_dump(commands))
    with pytest.raises(UnsafeRepair):
        ControlledYamlSelectorRepairer().repair(source, "确定", "确定(1)")


@pytest.mark.parametrize("content", ["only-one-document", "appId: x\n---\nnot-a-list"])
def test_repair_document_shape_rejected(tmp_path, content):
    source = tmp_path / "flow.yaml"
    source.write_text(content)
    with pytest.raises(UnsafeRepair):
        ControlledYamlSelectorRepairer().repair(source, "确定", "确定(1)")


@pytest.mark.parametrize("after", [
    [{"tapOn": "new"}],
    [{"inputText": "new"}, {"assertVisible": "完成"}],
    [{"tapOn": "new"}, {"assertVisible": "别的"}],
])
def test_patch_invariants_reject_unrelated_changes(after):
    with pytest.raises(UnsafeRepair):
        ControlledYamlSelectorRepairer._assert_safe([{"tapOn": "old"}, {"assertVisible": "完成"}], after, 0, "tapOn")


def test_hierarchy_nested_serializations_and_empty_targets():
    selector = HierarchySelectorCandidate()
    hierarchy = {"nested": json.dumps({"text": json.dumps({"txt": "确定(1)"})}), "ignored": "not json", "text": "123", "blank": {"text": " "}}
    assert selector.select(hierarchy, "确定") == "确定(1)"
    assert selector.select(hierarchy, " ") is None
    assert selector.select({"text": "完全不同"}, "确定") is None
    assert not selector._related("确定", " ")
