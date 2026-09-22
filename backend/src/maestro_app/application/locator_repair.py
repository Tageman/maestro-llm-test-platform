from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml


class UnsafeRepair(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RepairPatch:
    before_selector: str
    after_selector: str
    before_yaml: str
    after_yaml: str
    diff: str


class HierarchySelectorCandidate:
    """Extract a single evidence-backed text candidate from MCP hierarchy output."""

    _TEXT_KEYS = frozenset({"text", "txt", "hintText", "hint", "accessibilityText", "a11y"})

    def select(self, hierarchy_result: dict, failed_selector: str) -> str | None:
        values: set[str] = set()
        self._walk(hierarchy_result, values)
        candidates = sorted(
            value
            for value in values
            if value != failed_selector and self._related(failed_selector, value)
        )
        return candidates[0] if len(candidates) == 1 else None

    def _walk(self, value, collected: set[str]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in self._TEXT_KEYS and isinstance(child, str) and child.strip():
                    try:
                        decoded = json.loads(child)
                    except (json.JSONDecodeError, TypeError):
                        collected.add(child.strip())
                    else:
                        if isinstance(decoded, (dict, list)):
                            self._walk(decoded, collected)
                        else:
                            collected.add(child.strip())
                else:
                    self._walk(child, collected)
        elif isinstance(value, list):
            for child in value:
                self._walk(child, collected)
        elif isinstance(value, str):
            try:
                decoded = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return
            self._walk(decoded, collected)

    @staticmethod
    def _related(failed: str, candidate: str) -> bool:
        normalized_failed = re.sub(r"\s+", "", failed).casefold()
        normalized_candidate = re.sub(r"\s+", "", candidate).casefold()
        if not normalized_failed or not normalized_candidate:
            return False
        return (
            normalized_candidate.startswith(normalized_failed)
            or normalized_failed.startswith(normalized_candidate)
            or difflib.SequenceMatcher(
                None, normalized_failed, normalized_candidate
            ).ratio()
            >= 0.82
        )


class ControlledYamlSelectorRepairer:
    """Replace one non-assertion action selector and prove all invariants."""

    ASSERTION_KEYS = frozenset({"assertVisible", "assertNotVisible"})
    REPAIRABLE_KEYS = frozenset({"tapOn", "scrollUntilVisible"})

    def repair(self, yaml_path: Path, failed_selector: str, candidate: str) -> RepairPatch:
        before = yaml_path.read_text(encoding="utf-8")
        documents = list(yaml.safe_load_all(before))
        if len(documents) != 2 or not isinstance(documents[1], list):
            raise UnsafeRepair("Flow YAML must contain a header and command list")
        commands = documents[1]
        matches: list[tuple[int, str]] = []
        for index, command in enumerate(commands):
            if not isinstance(command, dict) or len(command) != 1:
                continue
            key, body = next(iter(command.items()))
            if key in self.ASSERTION_KEYS or key not in self.REPAIRABLE_KEYS:
                continue
            if self._selector_value(key, body) == failed_selector:
                matches.append((index, key))
        if len(matches) != 1:
            raise UnsafeRepair(
                f"expected exactly one repairable selector, found {len(matches)}"
            )
        command_index, command_key = matches[0]
        repaired_commands = yaml.safe_load(yaml.safe_dump(commands, allow_unicode=True, sort_keys=False))
        repaired_body = repaired_commands[command_index][command_key]
        escaped = re.escape(candidate)
        if isinstance(repaired_body, str):
            repaired_commands[command_index][command_key] = escaped
        elif command_key == "scrollUntilVisible" and isinstance(repaired_body, dict):
            element = repaired_body.get("element")
            if isinstance(element, str):
                repaired_body["element"] = escaped
            elif isinstance(element, dict) and "text" in element:
                element["text"] = escaped
            else:
                raise UnsafeRepair("unsupported scroll selector shape")
        elif isinstance(repaired_body, dict) and "text" in repaired_body:
            repaired_body["text"] = escaped
        else:
            raise UnsafeRepair("unsupported selector shape")

        after = self._dump(documents[0], repaired_commands)
        self._assert_safe(commands, repaired_commands, command_index, command_key)
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile="before.yaml",
                tofile="after.yaml",
            )
        )
        return RepairPatch(failed_selector, candidate, before, after, diff)

    @staticmethod
    def _selector_value(command_key: str, body) -> str | None:
        if isinstance(body, str):
            return body
        if not isinstance(body, dict):
            return None
        selector = body.get("element") if command_key == "scrollUntilVisible" else body
        if isinstance(selector, str):
            return selector
        if isinstance(selector, dict):
            return selector.get("text")
        return None

    @classmethod
    def _assert_safe(cls, before: list, after: list, index: int, key: str) -> None:
        if len(before) != len(after):
            raise UnsafeRepair("repair changed command count")
        for ordinal, (old, new) in enumerate(zip(before, after, strict=True)):
            if ordinal == index:
                if set(old) != {key} or set(new) != {key}:
                    raise UnsafeRepair("repair changed command type")
                continue
            if old != new:
                raise UnsafeRepair("repair changed a non-failing command")
        for old, new in zip(before, after, strict=True):
            if isinstance(old, dict) and set(old) & cls.ASSERTION_KEYS and old != new:
                raise UnsafeRepair("repair changed an assertion")

    @staticmethod
    def _dump(header: dict, commands: list) -> str:
        return (
            yaml.safe_dump(header, allow_unicode=True, sort_keys=False, width=120).rstrip()
            + "\n---\n"
            + yaml.safe_dump(commands, allow_unicode=True, sort_keys=False, width=120).rstrip()
            + "\n"
        )
