from __future__ import annotations

import argparse
import json
import signal
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

from maestro_app.application.pytest_generator import GeneratedPytestPackageBuilder
from maestro_app.application.run_service import RunService
from maestro_app.core.config import Settings
from maestro_app.domain.models import CreateRunRequest
from maestro_app.infrastructure.device_manager import AndroidDeviceManager
from maestro_app.infrastructure.generation_repository import GenerationRepository
from maestro_app.infrastructure.android_test_environment import (
    TemporaryCredentialServicesGuard,
)
from maestro_app.infrastructure.pytest_process import ManagedPytestRunner
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
        background=False,
        maestro_startup_grace_seconds=settings.maestro_startup_grace_seconds,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute the frozen M2 pytest → Maestro emulator acceptance path."
    )
    parser.add_argument("--generation-id", required=True)
    parser.add_argument("--repeat", type=int, default=1, choices=range(1, 4))
    parser.add_argument("--evidence", type=Path)
    parser.add_argument(
        "--temporarily-disable-credential-services",
        action="store_true",
        help=(
            "Opt in to snapshot, temporarily disable, and restore Android autofill "
            "and credential services on the configured emulator."
        ),
    )
    parser.add_argument(
        "--settings-evidence",
        type=Path,
        help="Evidence path for the temporary Android secure-setting transaction.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.from_environment()
    service = build_service(settings)
    summaries = []
    guard = nullcontext()
    if args.temporarily_disable_credential_services:
        if not settings.android_device_id:
            raise SystemExit(
                "ANDROID_DEVICE_ID is required when temporarily disabling services"
            )
        if not settings.avd_name:
            raise SystemExit(
                "AVD_NAME is required when temporarily disabling services"
            )
        if not args.evidence and not args.settings_evidence:
            raise SystemExit(
                "--evidence or --settings-evidence is required for the opt-in setting change"
            )
        settings_evidence = args.settings_evidence or args.evidence.with_name(
            "credential-services.json"
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
            for _ in range(args.repeat):
                summary = service.create(
                    CreateRunRequest(generation_id=args.generation_id)
                )
                summaries.append(summary.model_dump(mode="json"))
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
    evidence = {
        "milestone": "M2",
        "tested_at": datetime.now(UTC).isoformat(),
        "generation_id": args.generation_id,
        "runs": summaries,
    }
    rendered = json.dumps(evidence, ensure_ascii=False, indent=2)
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if all(item["state"] == "COMPLETED" for item in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
