from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from maestro_app.infrastructure.tool_probe import CommandRunner, SubprocessCommandRunner


class AndroidTestEnvironmentError(RuntimeError):
    pass


class TemporaryCredentialServicesGuard:
    """Temporarily disable credential UI services on one validated test AVD.

    This guard is intentionally opt-in. It snapshots the exact original values before
    the first mutation and restores them on normal completion and exception paths.
    """

    SETTINGS = (
        "autofill_service",
        "credential_service",
        "credential_service_primary",
    )

    def __init__(
        self,
        *,
        adb_command: str,
        device_id: str,
        expected_avd_name: str,
        evidence_path: Path,
        timeout_seconds: float = 30.0,
        runner: CommandRunner | None = None,
    ) -> None:
        if not device_id.startswith("emulator-"):
            raise AndroidTestEnvironmentError(
                "temporary credential-service changes are restricted to emulator-*"
            )
        self.adb_command = adb_command
        self.device_id = device_id
        self.expected_avd_name = expected_avd_name
        self.evidence_path = evidence_path
        self.timeout_seconds = timeout_seconds
        self.runner = runner or SubprocessCommandRunner()
        self.original_values: dict[str, str] = {}
        self._events: list[dict[str, str]] = []
        self._mutated = False

    def __enter__(self) -> "TemporaryCredentialServicesGuard":
        self._validate_avd()
        self.original_values = {
            key: self._get_setting(key) for key in self.SETTINGS
        }
        self._record("SNAPSHOTTED", "original secure-setting values saved")
        self._write_evidence("SNAPSHOTTED")
        try:
            for key in self.SETTINGS:
                self._run_settings("delete", key)
                self._mutated = True
            disabled_values = {
                key: self._get_setting(key) for key in self.SETTINGS
            }
            if any(value != "null" for value in disabled_values.values()):
                raise AndroidTestEnvironmentError(
                    f"credential services were not disabled: {disabled_values}"
                )
            self._record("DISABLED", "credential services temporarily disabled")
            self._write_evidence("DISABLED", current_values=disabled_values)
            return self
        except BaseException:
            self.restore()
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.restore()
        return False

    def restore(self) -> None:
        if not self.original_values:
            return
        restore_errors: list[str] = []
        for key, value in self.original_values.items():
            try:
                if value == "null":
                    self._run_settings("delete", key)
                else:
                    self._run_settings("put", key, value)
            except AndroidTestEnvironmentError as exc:
                restore_errors.append(f"{key}: {exc}")

        restored_values: dict[str, str] = {}
        for key in self.SETTINGS:
            try:
                restored_values[key] = self._get_setting(key)
            except AndroidTestEnvironmentError as exc:
                restore_errors.append(f"{key} verification: {exc}")

        mismatches = {
            key: {"expected": value, "actual": restored_values.get(key)}
            for key, value in self.original_values.items()
            if restored_values.get(key) != value
        }
        if mismatches:
            restore_errors.append(f"restoration mismatch: {mismatches}")

        if restore_errors:
            self._record("RESTORE_FAILED", "; ".join(restore_errors))
            self._write_evidence(
                "RESTORE_FAILED",
                current_values=restored_values,
                errors=restore_errors,
            )
            raise AndroidTestEnvironmentError(
                "failed to restore Android credential services; see evidence file"
            )

        self._mutated = False
        self._record("RESTORED", "all original secure-setting values restored")
        self._write_evidence("RESTORED", current_values=restored_values)

    def _validate_avd(self) -> None:
        result = self.runner.run(
            [self.adb_command, "-s", self.device_id, "emu", "avd", "name"],
            self.timeout_seconds,
        )
        if not result.succeeded:
            raise AndroidTestEnvironmentError(
                "cannot validate AVD: " + (result.error or result.combined_output)
            )
        actual = next(
            (
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip() and line.strip() != "OK"
            ),
            "",
        )
        if actual != self.expected_avd_name:
            raise AndroidTestEnvironmentError(
                f"AVD mismatch: expected {self.expected_avd_name}, got {actual or '<empty>'}"
            )

    def _get_setting(self, key: str) -> str:
        result = self.runner.run(
            [
                self.adb_command,
                "-s",
                self.device_id,
                "shell",
                "settings",
                "get",
                "secure",
                key,
            ],
            self.timeout_seconds,
        )
        if not result.succeeded:
            raise AndroidTestEnvironmentError(
                f"failed to read {key}: {result.error or result.combined_output}"
            )
        value = result.stdout.strip()
        if not value:
            raise AndroidTestEnvironmentError(f"empty value returned for {key}")
        return value

    def _run_settings(self, operation: str, key: str, value: str | None = None) -> None:
        args = [
            self.adb_command,
            "-s",
            self.device_id,
            "shell",
            "settings",
            operation,
            "secure",
            key,
        ]
        if value is not None:
            args.append(value)
        result = self.runner.run(args, self.timeout_seconds)
        if not result.succeeded:
            raise AndroidTestEnvironmentError(
                f"settings {operation} failed for {key}: "
                + (result.error or result.combined_output)
            )

    def _record(self, state: str, detail: str) -> None:
        self._events.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "state": state,
                "detail": detail,
            }
        )

    def _write_evidence(
        self,
        state: str,
        *,
        current_values: dict[str, str] | None = None,
        errors: list[str] | None = None,
    ) -> None:
        document = {
            "operation": "temporary_android_credential_service_suppression",
            "authorized": True,
            "device_id": self.device_id,
            "expected_avd_name": self.expected_avd_name,
            "state": state,
            "updated_at": datetime.now(UTC).isoformat(),
            "original_values": self.original_values,
            "current_values": current_values,
            "errors": errors or [],
            "events": self._events,
            "recovery_note": (
                "If this process is forcibly killed before RESTORED, apply the exact "
                "original_values with: adb -s <device> shell settings put secure <key> <value>."
            ),
        }
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.evidence_path.with_suffix(self.evidence_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.evidence_path)
