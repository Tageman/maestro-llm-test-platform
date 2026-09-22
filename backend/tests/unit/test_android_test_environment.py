from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import pytest

from maestro_app.infrastructure.android_test_environment import (
    AndroidTestEnvironmentError,
    TemporaryCredentialServicesGuard,
)
from maestro_app.infrastructure.tool_probe import ProcessResult


ORIGINAL = {
    "autofill_service": "example/.Autofill",
    "credential_service": "example/.Credential",
    "credential_service_primary": "example/.Credential",
}


class FakeRunner:
    def __init__(self, avd_name: str = "Pixel_5") -> None:
        self.avd_name = avd_name
        self.settings = ORIGINAL.copy()
        self.mutations: list[tuple[str, str, str | None]] = []

    def run(self, args: Sequence[str], timeout_seconds: float) -> ProcessResult:
        if list(args[-3:]) == ["emu", "avd", "name"]:
            return ProcessResult(0, f"{self.avd_name}\nOK")
        operation = args[-3]
        key = args[-1]
        if operation == "get":
            return ProcessResult(0, self.settings.get(key, "null"))
        if operation == "delete":
            self.settings.pop(key, None)
            self.mutations.append(("delete", key, None))
            return ProcessResult(0, "Deleted 1 rows")
        if args[-4] == "put":
            key = args[-2]
            value = args[-1]
            self.settings[key] = value
            self.mutations.append(("put", key, value))
            return ProcessResult(0, "")
        return ProcessResult(1, stderr=f"unexpected command: {args}")


def _guard(tmp_path: Path, runner: FakeRunner) -> TemporaryCredentialServicesGuard:
    return TemporaryCredentialServicesGuard(
        adb_command="adb",
        device_id="emulator-5554",
        expected_avd_name="Pixel_5",
        evidence_path=tmp_path / "credential-services.json",
        runner=runner,
    )


def test_guard_disables_then_restores_exact_values(tmp_path: Path) -> None:
    runner = FakeRunner()

    with _guard(tmp_path, runner):
        assert runner.settings == {}
        evidence = json.loads(
            (tmp_path / "credential-services.json").read_text(encoding="utf-8")
        )
        assert evidence["state"] == "DISABLED"
        assert evidence["original_values"] == ORIGINAL

    assert runner.settings == ORIGINAL
    evidence = json.loads(
        (tmp_path / "credential-services.json").read_text(encoding="utf-8")
    )
    assert evidence["state"] == "RESTORED"
    assert evidence["current_values"] == ORIGINAL


def test_guard_restores_when_body_raises(tmp_path: Path) -> None:
    runner = FakeRunner()

    with pytest.raises(RuntimeError, match="acceptance failed"):
        with _guard(tmp_path, runner):
            raise RuntimeError("acceptance failed")

    assert runner.settings == ORIGINAL
    evidence = json.loads(
        (tmp_path / "credential-services.json").read_text(encoding="utf-8")
    )
    assert evidence["state"] == "RESTORED"


def test_guard_refuses_unexpected_avd_without_mutating(tmp_path: Path) -> None:
    runner = FakeRunner(avd_name="Another_AVD")

    with pytest.raises(AndroidTestEnvironmentError, match="AVD mismatch"):
        with _guard(tmp_path, runner):
            pass

    assert runner.settings == ORIGINAL
    assert runner.mutations == []
