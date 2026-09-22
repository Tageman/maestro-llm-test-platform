from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from maestro_app.domain.flow_ir import FlowIR


def _base_flow(command: dict) -> dict:
    return {
        "schema_version": "1.0",
        "flow_id": "TC-HOME-001",
        "flow_kind": "case",
        "app_id": "aippt.com.mm",
        "name": "页数设置",
        "tags": ["smoke", "home"],
        "properties": {"testCaseId": "TC-HOME-001"},
        "commands": [command],
        "generation_context": {
            "prompt_version": "v1",
            "model": "test-model",
            "generated_at": datetime.now(UTC).isoformat(),
            "warnings": [],
        },
    }


def _source(field: str = "steps") -> dict:
    return {
        "entity_type": "case",
        "entity_id": "TC-HOME-001",
        "field": field,
        "ordinal": 1,
        "text": "点击【页数】",
    }


def test_text_selector_is_accepted() -> None:
    flow = FlowIR.model_validate(
        _base_flow(
            {
                "type": "tap_on",
                "source_ref": _source(),
                "selector": {"strategy": "text", "value": "页数"},
            }
        )
    )

    assert flow.commands[0].type == "tap_on"


def test_coordinates_are_structurally_rejected() -> None:
    with pytest.raises(ValidationError):
        FlowIR.model_validate(
            _base_flow(
                {
                    "type": "tap_on",
                    "source_ref": _source(),
                    "selector": {
                        "strategy": "text",
                        "value": "页数",
                        "x": 100,
                        "y": 200,
                    },
                }
            )
        )


def test_expected_result_cannot_generate_action() -> None:
    with pytest.raises(ValidationError, match="expected_results"):
        FlowIR.model_validate(
            _base_flow(
                {
                    "type": "tap_on",
                    "source_ref": _source("expected_results"),
                    "selector": {"strategy": "text", "value": "尽情发挥"},
                }
            )
        )
