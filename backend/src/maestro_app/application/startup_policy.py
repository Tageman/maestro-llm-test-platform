from __future__ import annotations

from pathlib import Path

import yaml


def explicit_startup_flows(flow_ids: list[str], paths: dict[str, Path]) -> list[str]:
    """Identify explicit launch/reset commands, including generated subflows.

    The system default never overrides user-authored startup behavior. This
    operates on approved YAML, not an LLM's interpretation of natural language.
    """
    seen: set[str] = set()
    found: list[str] = []

    def visit(flow_id: str) -> None:
        if flow_id in seen or flow_id not in paths:
            return
        seen.add(flow_id)
        documents = list(yaml.safe_load_all(paths[flow_id].read_text(encoding="utf-8")))
        commands = documents[1] if len(documents) == 2 else []
        if not isinstance(commands, list):
            return
        for command in commands:
            if command in ("launchApp", "clearState") or (
                isinstance(command, dict) and {"launchApp", "clearState"} & command.keys()
            ):
                found.append(flow_id)
                break
        for command in commands:
            if isinstance(command, dict) and "runFlow" in command:
                nested = command["runFlow"]
                filename = nested if isinstance(nested, str) else (nested.get("file") if isinstance(nested, dict) else None)
                if filename:
                    visit(Path(filename).stem)

    for flow_id in flow_ids:
        visit(flow_id)
    return found
