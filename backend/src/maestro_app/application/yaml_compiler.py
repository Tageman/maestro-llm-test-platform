from __future__ import annotations

import re
from typing import Any, Protocol

import yaml

from maestro_app.domain.flow_ir import FlowIR, SelectorIR


class YamlSyntaxRepairer(Protocol):
    def repair(
        self,
        yaml_text: str,
        syntax_output: str,
        *,
        attempt: int,
    ) -> str | None: ...


class DeterministicYamlSyntaxRepairer:
    """Normalize YAML structure without changing IR commands or assertions."""

    def repair(
        self,
        yaml_text: str,
        syntax_output: str,
        *,
        attempt: int,
    ) -> str | None:
        del syntax_output, attempt
        try:
            documents = list(yaml.safe_load_all(yaml_text))
        except yaml.YAMLError:
            return None
        if (
            len(documents) != 2
            or not isinstance(documents[0], dict)
            or not isinstance(documents[1], list)
        ):
            return None
        header_yaml = yaml.safe_dump(
            documents[0],
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        ).rstrip()
        command_yaml = yaml.safe_dump(
            documents[1],
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        ).rstrip()
        repaired = f"{header_yaml}\n---\n{command_yaml}\n"
        return repaired if repaired != yaml_text else None


class FlowYamlCompiler:
    version = "1.1"

    def compile(self, flow: FlowIR) -> str:
        header: dict[str, Any] = {
            "appId": flow.app_id,
            "name": flow.name,
            "tags": flow.tags,
            "properties": flow.properties,
        }
        commands = [self._compile_command(command) for command in flow.commands]
        header_yaml = yaml.safe_dump(
            header,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        ).rstrip()
        command_yaml = yaml.safe_dump(
            commands,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        ).rstrip()
        return f"{header_yaml}\n---\n{command_yaml}\n"

    def _compile_command(self, command) -> Any:
        if command.type == "launch_app":
            return {
                "launchApp": {
                    "clearState": command.clear_state,
                    "stopApp": command.stop_app,
                }
            }
        if command.type == "clear_state":
            return "clearState"
        if command.type == "tap_on":
            return {"tapOn": self._selector(command.selector)}
        if command.type == "input_text":
            return {"inputText": command.text}
        if command.type == "erase_text":
            return (
                {"eraseText": command.characters}
                if command.characters is not None
                else "eraseText"
            )
        if command.type == "assert_visible":
            return {"assertVisible": self._selector(command.selector)}
        if command.type == "assert_not_visible":
            return {"assertNotVisible": self._selector(command.selector)}
        if command.type == "scroll_until_visible":
            body: dict[str, Any] = {
                "element": self._selector(command.selector),
                "direction": command.direction.upper(),
            }
            if command.timeout_ms is not None:
                body["timeout"] = command.timeout_ms
            return {"scrollUntilVisible": body}
        if command.type == "swipe":
            body = {"direction": command.direction.upper()}
            if command.duration_ms is not None:
                body["duration"] = command.duration_ms
            return {"swipe": body}
        if command.type == "back":
            return "back"
        if command.type == "hide_keyboard":
            return "hideKeyboard"
        if command.type == "wait_for_animation":
            return (
                {"waitForAnimationToEnd": {"timeout": command.timeout_ms}}
                if command.timeout_ms is not None
                else "waitForAnimationToEnd"
            )
        if command.type == "run_flow":
            if command.env:
                return {
                    "runFlow": {
                        "file": f"{command.flow_id}.yaml",
                        "env": command.env,
                    }
                }
            return {"runFlow": f"{command.flow_id}.yaml"}
        if command.type == "take_screenshot":
            return {"takeScreenshot": command.name}
        raise ValueError(f"unsupported Flow IR command: {command.type}")

    @staticmethod
    def _selector(selector: SelectorIR) -> str | dict[str, Any]:
        key = {
            "text": "text",
            "resource_id": "id",
            "content_description": "text",
        }[selector.strategy.value]
        # Flow IR V1 selector values are literal user-visible values. Maestro
        # interprets selector strings as regular expressions, so escape regex
        # metacharacters at the compiler boundary rather than requiring Excel
        # authors to know regex syntax.
        literal_value = re.escape(selector.value)
        if selector.index is None and key == "text":
            return literal_value
        result: dict[str, Any] = {key: literal_value}
        if selector.index is not None:
            result["index"] = selector.index
        return result
