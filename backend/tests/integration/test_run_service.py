from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maestro_app.application.flow_translator import RuleBasedFlowTranslator
from maestro_app.application.generation_service import GenerationService
from maestro_app.application.ports import ManagedProcessResult, PytestPackage
from maestro_app.application.pytest_generator import GeneratedPytestPackageBuilder
from maestro_app.application.run_service import RunService
from maestro_app.application.syntax_checker import SyntaxCheckResult
from maestro_app.application.workbook_service import WorkbookService
from maestro_app.domain.enums import CaseRunState, RunMode, RunState
from maestro_app.domain.models import (
    ApprovalRequest,
    CreateGenerationRequest,
    CreateRunRequest,
    DevicePreparation,
)
from maestro_app.infrastructure.excel_importer import ExcelWorkbookImporter
from maestro_app.infrastructure.generation_repository import GenerationRepository
from maestro_app.infrastructure.run_repository import RunRepository
from maestro_app.infrastructure.workbook_repository import WorkbookRepository
from m1_helpers import build_sample_workbook


class PassingSyntaxChecker:
    def check(self, flow_path, *, maestro_command, timeout_seconds):
        assert Path(flow_path).is_file()
        return SyntaxCheckResult(valid=True, output="OK", exit_code=0)


class PreparedDevice:
    def prepare(self, config):
        return DevicePreparation(
            device_id="emulator-5554",
            avd_name="Pixel_5",
            app_id=config.app_id,
            app_installed=True,
            boot_completed=True,
            checks=[{"name": "fake_device", "status": "passed"}],
        )


class PassingPytestRunner:
    def collect(self, package: PytestPackage) -> ManagedProcessResult:
        output = "\n".join(package.node_ids) + "\n"
        package.collection_path.parent.mkdir(parents=True, exist_ok=True)
        package.collection_path.write_text(output, encoding="utf-8")
        return ManagedProcessResult(0, output, package.collection_path)

    def run(
        self,
        run_id: str,
        package: PytestPackage,
        *,
        timeout_seconds: float,
        cancel_event: threading.Event,
        on_tick=None,
    ) -> ManagedProcessResult:
        now = datetime.now(UTC).isoformat()
        events = [
            {
                "occurred_at": now,
                "event": "started",
                "entity_type": "case_lifecycle",
                "entity_id": "TC-HOME-001",
                "phase": "lifecycle",
                "case_id": "TC-HOME-001",
            },
            {
                "occurred_at": now,
                "event": "started",
                "entity_type": "case",
                "entity_id": "TC-HOME-001",
                "phase": "case",
                "case_id": "TC-HOME-001",
            },
            {
                "occurred_at": now,
                "event": "finished",
                "entity_type": "case",
                "entity_id": "TC-HOME-001",
                "phase": "case",
                "case_id": "TC-HOME-001",
                "succeeded": True,
                "exit_code": 0,
            },
            {
                "occurred_at": now,
                "event": "finished",
                "entity_type": "case_lifecycle",
                "entity_id": "TC-HOME-001",
                "phase": "lifecycle",
                "case_id": "TC-HOME-001",
                "succeeded": True,
            },
        ]
        package.trace_path.parent.mkdir(parents=True, exist_ok=True)
        package.trace_path.write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )
        package.junit_path.parent.mkdir(parents=True, exist_ok=True)
        package.junit_path.write_text(
            '<testsuite tests="1" failures="0"><testcase name="test_tc_home_001"/></testsuite>',
            encoding="utf-8",
        )
        package.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        package.stdout_path.write_text("1 passed\n", encoding="utf-8")
        if on_tick is not None:
            on_tick()
        return ManagedProcessResult(0, "1 passed", package.stdout_path)

    def cancel(self, run_id: str) -> None:
        return None


@pytest.mark.parametrize("mode", [RunMode.REVIEW, RunMode.UNATTENDED])
def test_ready_generation_runs_through_persisted_state_machine(
    tmp_path: Path, mode: RunMode
) -> None:
    runtime = tmp_path / mode.value
    workbook_repository = WorkbookRepository(runtime)
    generation_repository = GenerationRepository(runtime)
    run_repository = RunRepository(runtime)
    workbook_service = WorkbookService(
        workbook_repository,
        ExcelWorkbookImporter(),
    )
    source = build_sample_workbook(tmp_path / f"{mode.value}.xlsx")
    workbook = workbook_service.import_bytes(source.name, source.read_bytes())
    generation_service = GenerationService(
        workbook_repository,
        generation_repository,
        RuleBasedFlowTranslator(),
        syntax_checker=PassingSyntaxChecker(),
    )
    generation = generation_service.create(
        CreateGenerationRequest(workbook_id=workbook.workbook_id, mode=mode)
    )
    if mode == RunMode.REVIEW:
        generation = generation_service.approve(
            generation.generation_id,
            ApprovalRequest(flow_ids=[flow.flow_id for flow in generation.flows]),
        )

    service = RunService(
        workbook_repository,
        generation_repository,
        run_repository,
        GeneratedPytestPackageBuilder(run_repository),
        PreparedDevice(),
        PassingPytestRunner(),
        background=False,
    )
    summary = service.create(
        CreateRunRequest(generation_id=generation.generation_id)
    )

    assert summary.state == RunState.COMPLETED
    assert summary.mode == mode
    assert summary.device_id == "emulator-5554"
    assert summary.pytest_node_ids == [
        "generated/pytest/test_generated.py::test_tc_home_001"
    ]
    case = service.get_case(summary.run_id, "TC-HOME-001")
    assert case.state == CaseRunState.PASSED
    assert case.fixture_plan == ["FX-APP-RESET", "FX-LOGIN-READY"]
    events = service.events(summary.run_id)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[-1].state == RunState.COMPLETED.value
    assert any(event.type == "execution.finished" for event in events)
    assert (run_repository.run_dir(summary.run_id) / "run.json").is_file()
    assert (
        run_repository.run_dir(summary.run_id)
        / "artifacts"
        / "device-preparation.json"
    ).is_file()
