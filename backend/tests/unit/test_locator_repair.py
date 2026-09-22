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
