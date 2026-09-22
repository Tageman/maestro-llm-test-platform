from __future__ import annotations

import argparse
import json
import signal
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

from maestro_app.application.pytest_generator import GeneratedPytestPackageBuilder
from maestro_app.application.run_service import RunService
from maestro_app.application.syntax_checker import MaestroSyntaxChecker
from maestro_app.core.config import Settings
from maestro_app.domain.models import CreateRunRequest
from maestro_app.infrastructure.android_test_environment import (
    TemporaryCredentialServicesGuard,
)
from maestro_app.infrastructure.device_manager import AndroidDeviceManager
from maestro_app.infrastructure.generation_repository import GenerationRepository
from maestro_app.infrastructure.mcp_diagnostics import MaestroMcpDiagnosticService
from maestro_app.infrastructure.pytest_process import ManagedPytestRunner
from maestro_app.infrastructure.result_workbook import ResultWorkbookWriter
from maestro_app.infrastructure.run_repository import RunRepository
from maestro_app.infrastructure.workbook_repository import WorkbookRepository


def build_service(settings: Settings) -> RunService:
    run_repository = RunRepository(settings.runtime_dir)
    return RunService(
        WorkbookRepository(settings.runtime_dir),
        GenerationRepository(settings.runtime_dir),
        run_repository,
        GeneratedPytestPackageBuilder(
            run_repository, settings.maestro_startup_grace_seconds
        ),
        AndroidDeviceManager(settings),
        ManagedPytestRunner(settings),
        diagnostic_service=MaestroMcpDiagnosticService(
            timeout_seconds=settings.mcp_timeout_seconds
        ),
        syntax_checker=MaestroSyntaxChecker(),
        result_writer=ResultWorkbookWriter(),
        background=False,
        maestro_startup_grace_seconds=settings.maestro_startup_grace_seconds,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute the M3 pytest → MCP repair → result workbook acceptance path."
    )
    parser.add_argument("--generation-id", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument(
        "--temporarily-disable-credential-services", action="store_true"
    )
    parser.add_argument("--settings-evidence", type=Path)
    parser.add_argument(
        "--expected-outcome",
        choices=("repaired-pass", "assertion-failure"),
        default="repaired-pass",
        help="Acceptance branch to verify; repaired-pass remains the default.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.from_environment()
    service = build_service(settings)
    guard = nullcontext()
    if args.temporarily_disable_credential_services:
        if not settings.android_device_id or not settings.avd_name:
            raise SystemExit(
                "ANDROID_DEVICE_ID and AVD_NAME are required for the setting guard"
            )
        settings_evidence = args.settings_evidence or args.evidence.with_name(
            "m3-credential-services.json"
        )
        guard = TemporaryCredentialServicesGuard(
            adb_command=settings.adb_command,
            device_id=settings.android_device_id,
            expected_avd_name=settings.avd_name,
            evidence_path=settings_evidence,
            timeout_seconds=settings.probe_timeout_seconds,
        )

    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def handle_sigterm(signum, frame) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, handle_sigterm)
    try:
        with guard:
            summary = service.create(
                CreateRunRequest(generation_id=args.generation_id)
            )
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
    run = service.run_repository.get_run(summary.run_id)
    payload = {
        "milestone": "M3",
        "tested_at": datetime.now(UTC).isoformat(),
        "generation_id": args.generation_id,
        "expected_outcome": args.expected_outcome,
        "run": run.model_dump(mode="json"),
        "acceptance": {
            "terminal_state": summary.state.value,
            "repair_count": len(run.repairs),
            "attempt_count": sum(len(item.attempts) for item in run.case_runs),
            "result_workbook": run.result_workbook_path,
        },
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.expected_outcome == "assertion-failure":
        attempts = [attempt for case in run.case_runs for attempt in case.attempts]
        accepted = (
            summary.state.value == "COMPLETED_WITH_FAILURES"
            and not run.repairs
            and len(attempts) == 1
            and attempts[0].failure_type is not None
            and attempts[0].failure_type.value == "ASSERTION"
        )
    else:
        accepted = summary.state.value == "COMPLETED" and bool(run.repairs)
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
