from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, Sequence

from maestro_app.core.config import Settings
from maestro_app.domain.enums import OverallStatus, ToolStatus
from maestro_app.domain.models import (
    AndroidDevice,
    AppCapability,
    CapabilityReport,
    ToolCapability,
)


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.returncode == 0

    @property
    def combined_output(self) -> str:
        return "\n".join(part for part in (self.stdout, self.stderr) if part).strip()


class CommandRunner(Protocol):
    def run(self, args: Sequence[str], timeout_seconds: float) -> ProcessResult: ...


class SubprocessCommandRunner:
    def run(self, args: Sequence[str], timeout_seconds: float) -> ProcessResult:
        try:
            completed = subprocess.run(
                list(args),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )
            return ProcessResult(
                returncode=completed.returncode,
                stdout=completed.stdout.strip(),
                stderr=completed.stderr.strip(),
            )
        except FileNotFoundError as exc:
            return ProcessResult(returncode=127, error=str(exc))
        except PermissionError as exc:
            return ProcessResult(returncode=126, error=str(exc))
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return ProcessResult(
                returncode=124,
                stdout=stdout,
                stderr=stderr,
                error=f"command timed out after {timeout_seconds:g}s",
            )


class SystemCapabilityService:
    def __init__(
        self,
        settings: Settings,
        runner: CommandRunner | None = None,
    ) -> None:
        self.settings = settings
        self.runner = runner or SubprocessCommandRunner()

    def inspect(self) -> CapabilityReport:
        timeout = self.settings.probe_timeout_seconds

        maestro_result = self.runner.run(
            [self.settings.maestro_command, "--version"], timeout
        )
        maestro = self._capability_from_result(
            "maestro",
            self.settings.maestro_command,
            maestro_result,
            "Maestro CLI is ready",
        )

        maestro_help = self.runner.run(
            [self.settings.maestro_command, "--help"], timeout
        )
        mcp_available = maestro_help.succeeded and "mcp" in maestro_help.combined_output
        mcp = ToolCapability(
            name="maestro_mcp",
            status=ToolStatus.AVAILABLE if mcp_available else ToolStatus.UNAVAILABLE,
            available=mcp_available,
            version=maestro.version,
            command=f"{self.settings.maestro_command} mcp",
            detail=(
                "Maestro MCP command is exposed by the CLI"
                if mcp_available
                else self._failure_detail(maestro_help, "Maestro MCP command not found")
            ),
        )

        adb_result = self.runner.run([self.settings.adb_command, "version"], timeout)
        adb = self._capability_from_result(
            "adb",
            self.settings.adb_command,
            adb_result,
            "Android Debug Bridge is ready",
        )

        devices_result = self.runner.run(
            [self.settings.adb_command, "devices"], timeout
        )
        devices = self.parse_adb_devices(devices_result.stdout)
        selected_device_id = self._select_device(devices)
        devices = [
            device.model_copy(update={"selected": device.device_id == selected_device_id})
            for device in devices
        ]

        emulator_result = self.runner.run(
            [self.settings.emulator_command, "-list-avds"], timeout
        )
        avds = [line.strip() for line in emulator_result.stdout.splitlines() if line.strip()]
        emulator = self._capability_from_result(
            "android_emulator",
            self.settings.emulator_command,
            emulator_result,
            f"{len(avds)} Android Virtual Device(s) discovered",
        )

        app = self._inspect_app(selected_device_id, timeout)
        tools = [maestro, mcp, adb, emulator]
        overall = self._overall_status(tools, devices, avds, app)

        return CapabilityReport(
            overall_status=overall,
            checked_at=datetime.now(UTC),
            tools=tools,
            android_devices=devices,
            avds=avds,
            app=app,
        )

    @staticmethod
    def parse_adb_devices(output: str) -> list[AndroidDevice]:
        devices: list[AndroidDevice] = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("List of devices") or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            devices.append(AndroidDevice(device_id=parts[0], state=parts[1]))
        return devices

    def _select_device(self, devices: list[AndroidDevice]) -> str | None:
        online = [device.device_id for device in devices if device.state == "device"]
        if self.settings.android_device_id:
            return (
                self.settings.android_device_id
                if self.settings.android_device_id in online
                else None
            )
        return online[0] if len(online) == 1 else None

    def _inspect_app(
        self, selected_device_id: str | None, timeout: float
    ) -> AppCapability:
        if not selected_device_id:
            return AppCapability(app_id=self.settings.app_id, installed=False)

        result = self.runner.run(
            [
                self.settings.adb_command,
                "-s",
                selected_device_id,
                "shell",
                "pm",
                "list",
                "packages",
                self.settings.app_id,
            ],
            timeout,
        )
        installed = result.succeeded and f"package:{self.settings.app_id}" in result.stdout
        return AppCapability(
            app_id=self.settings.app_id,
            installed=installed,
            device_id=selected_device_id,
        )

    @staticmethod
    def _overall_status(
        tools: list[ToolCapability],
        devices: list[AndroidDevice],
        avds: list[str],
        app: AppCapability,
    ) -> OverallStatus:
        if not any(tool.name == "maestro" and tool.available for tool in tools):
            return OverallStatus.UNAVAILABLE
        if not any(tool.name == "adb" and tool.available for tool in tools):
            return OverallStatus.UNAVAILABLE

        required_tools_ready = all(tool.available for tool in tools)
        online_device = any(device.state == "device" and device.selected for device in devices)
        if required_tools_ready and online_device and app.installed:
            return OverallStatus.READY
        if required_tools_ready and avds:
            return OverallStatus.DEGRADED
        return OverallStatus.UNAVAILABLE

    def _capability_from_result(
        self,
        name: str,
        command: str,
        result: ProcessResult,
        success_detail: str,
    ) -> ToolCapability:
        version = self._first_output_line(result.combined_output) if result.succeeded else None
        return ToolCapability(
            name=name,
            status=ToolStatus.AVAILABLE if result.succeeded else ToolStatus.UNAVAILABLE,
            available=result.succeeded,
            version=version,
            command=str(Path(command).expanduser()) if "/" in command else command,
            detail=(success_detail if result.succeeded else self._failure_detail(result)),
        )

    @staticmethod
    def _first_output_line(output: str) -> str | None:
        return next((line.strip() for line in output.splitlines() if line.strip()), None)

    @staticmethod
    def _failure_detail(result: ProcessResult, fallback: str = "Command unavailable") -> str:
        if result.error:
            return result.error
        return SystemCapabilityService._first_output_line(result.combined_output) or fallback
