from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import yaml

from maestro_app.application.yaml_compiler import DeterministicYamlSyntaxRepairer, FlowYamlCompiler
from maestro_app.domain.flow_ir import FlowIR


@pytest.mark.parametrize("command,expected", [
    ({"type": "launch_app", "clear_state": False}, {"launchApp": {"clearState": False, "stopApp": True}}),
    ({"type": "clear_state"}, "clearState"),
    ({"type": "input_text", "text": "中文"}, {"inputText": "中文"}),
    ({"type": "erase_text"}, "eraseText"),
    ({"type": "erase_text", "characters": 3}, {"eraseText": 3}),
    ({"type": "assert_not_visible", "selector": {"strategy": "text", "value": "错误"}}, {"assertNotVisible": "错误"}),
    ({"type": "scroll_until_visible", "selector": {"strategy": "resource_id", "value": "button"}, "direction": "up"}, {"scrollUntilVisible": {"element": {"id": "button"}, "direction": "UP"}}),
    ({"type": "scroll_until_visible", "selector": {"strategy": "text", "value": "结束"}, "direction": "down", "timeout_ms": 1000}, {"scrollUntilVisible": {"element": "结束", "direction": "DOWN", "timeout": 1000}}),
    ({"type": "swipe", "direction": "left"}, {"swipe": {"direction": "LEFT"}}),
    ({"type": "swipe", "direction": "right", "duration_ms": 500}, {"swipe": {"direction": "RIGHT", "duration": 500}}),
    ({"type": "back"}, "back"),
    ({"type": "hide_keyboard"}, "hideKeyboard"),
    ({"type": "wait_for_animation"}, "waitForAnimationToEnd"),
    ({"type": "wait_for_animation", "timeout_ms": 800}, {"waitForAnimationToEnd": {"timeout": 800}}),
    ({"type": "run_flow", "flow_id": "FX-LOGIN"}, {"runFlow": "FX-LOGIN.yaml"}),
    ({"type": "run_flow", "flow_id": "FX-LOGIN", "env": {"USER": "test"}}, {"runFlow": {"file": "FX-LOGIN.yaml", "env": {"USER": "test"}}}),
    ({"type": "take_screenshot", "name": "result"}, {"takeScreenshot": "result"}),
])
def test_every_supported_command_preserves_its_contract(command, expected):
    flow = FlowIR.model_validate({
        "schema_version": "1.0", "flow_id": "TC-1", "flow_kind": "case", "app_id": "example.app", "name": "contract",
        "commands": [{**command, "source_ref": {"entity_type": "case", "entity_id": "TC-1", "field": "steps", "ordinal": 1, "text": "source"}}],
        "generation_context": {"prompt_version": "test", "model": "test", "generated_at": datetime.now(UTC)},
    })
    compiler = FlowYamlCompiler()
    content = compiler.compile(flow)
    assert content == compiler.compile(flow)
    assert list(yaml.safe_load_all(content))[1] == [expected]


@pytest.mark.parametrize("strategy,key", [("text", "text"), ("resource_id", "id"), ("content_description", "text")])
def test_selector_index_and_regex_escaping(strategy, key):
    from maestro_app.domain.flow_ir import SelectorIR
    actual = FlowYamlCompiler._selector(SelectorIR(strategy=strategy, value="确定(1)", index=0))
    assert actual == {key: r"确定\(1\)", "index": 0}


@pytest.mark.parametrize("content", ["[broken", "appId: example.app", "[]\n---\n[]", "appId: example.app\n---\nx: y"])
def test_syntax_repair_rejects_unsupported_or_broken_shapes(content):
    assert DeterministicYamlSyntaxRepairer().repair(content, "bad", attempt=1) is None


def test_syntax_normalization_is_idempotent_and_semantics_preserving():
    content = 'appId: "example.app"\n---\n- tapOn: "确认"\n'
    repairer = DeterministicYamlSyntaxRepairer()
    repaired = repairer.repair(content, "normalize", attempt=1)
    assert repaired is not None
    assert list(yaml.safe_load_all(repaired)) == list(yaml.safe_load_all(content))
    assert repairer.repair(repaired, "normalize", attempt=2) is None
    with pytest.raises(ValueError, match="unsupported"):
        FlowYamlCompiler()._compile_command(SimpleNamespace(type="shell"))
