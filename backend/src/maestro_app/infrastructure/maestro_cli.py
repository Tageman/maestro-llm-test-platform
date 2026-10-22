from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from maestro_app.core.config import Settings
from maestro_app.infrastructure.maestro_report import report_error
from maestro_app.infrastructure.tool_probe import (
    CommandRunner,
    ProcessResult,
    SubprocessCommandRunner,
)


@dataclass(frozen=True, slots=True)
class MaestroFlowResult:
    process: ProcessResult
    report_path: Path
    artifact_dir: Path

    @property
    def passed(self) -> bool:
        return self.process.succeeded and report_error(self.report_path) is None


class MaestroCliRunner:
    """Typed, shell-free boundary around the Maestro CLI."""

    def __init__(
        self,
        settings: Settings,
        runner: CommandRunner | None = None,
    ) -> None:
        self.settings = settings
        self.runner = runner or SubprocessCommandRunner()

    def check_syntax(
        self,
        flow_path: Path,
        *,
        timeout_seconds: float | None = None,
    ) -> ProcessResult:
        return self.runner.run(
            [self.settings.maestro_command, "check-syntax", str(flow_path)],
            timeout_seconds or self.settings.probe_timeout_seconds,
        )

    def run_flow(
        self,
        flow_path: Path,
        *,
        device_id: str,
        report_path: Path,
        artifact_dir: Path,
        timeout_seconds: float = 180.0,
        reinstall_driver: bool = False,
    ) -> MaestroFlowResult:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        args = [
            self.settings.maestro_command,
            "--udid",
            device_id,
            "test",
        ]
        if reinstall_driver:
            args.append("--reinstall-driver")
        args.extend(
            [
                "--format",
                "junit",
                "--output",
                str(report_path),
                "--test-output-dir",
                str(artifact_dir),
                str(flow_path),
            ]
        )

        process = self.runner.run(args, timeout_seconds)
        return MaestroFlowResult(
            process=process,
            report_path=report_path,
            artifact_dir=artifact_dir,
        )
