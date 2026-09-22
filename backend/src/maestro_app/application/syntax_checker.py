from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from maestro_app.infrastructure.tool_probe import (
    CommandRunner,
    SubprocessCommandRunner,
)


@dataclass(frozen=True, slots=True)
class SyntaxCheckResult:
    valid: bool
    output: str
    exit_code: int


class MaestroSyntaxChecker:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or SubprocessCommandRunner()

    def check(
        self,
        flow_path: Path,
        *,
        maestro_command: str,
        timeout_seconds: float,
    ) -> SyntaxCheckResult:
        result = self.runner.run(
            [maestro_command, "check-syntax", str(flow_path)], timeout_seconds
        )
        return SyntaxCheckResult(
            valid=result.succeeded,
            output=result.combined_output,
            exit_code=result.returncode,
        )
