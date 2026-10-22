import json
from pathlib import Path

import pytest

from maestro_app.application.errors import StateConflict
from maestro_app.application.flow_translator import RuleBasedFlowTranslator
from maestro_app.application.generation_service import GenerationService
from maestro_app.application.pytest_generator import GeneratedPytestPackageBuilder
from maestro_app.application.run_service import RunService
from maestro_app.application.workbook_service import WorkbookService
from maestro_app.domain.enums import RunMode, RunState
from maestro_app.domain.models import CreateGenerationRequest, CreateRunRequest
from maestro_app.infrastructure.excel_importer import ExcelWorkbookImporter
from maestro_app.infrastructure.generation_repository import GenerationRepository
from maestro_app.infrastructure.result_workbook import ResultWorkbookWriter
from maestro_app.infrastructure.run_exporter import RunExporter
from maestro_app.infrastructure.run_repository import RunRepository
from maestro_app.infrastructure.workbook_repository import WorkbookRepository
from integration.test_run_service import PassingPytestRunner, PassingSyntaxChecker, PreparedDevice
from m1_helpers import build_sample_workbook


def build_service(tmp_path):
    runtime = tmp_path / "runtime"
    workbooks, generations, runs = WorkbookRepository(runtime), GenerationRepository(runtime), RunRepository(runtime)
    source = build_sample_workbook(tmp_path / "source.xlsx")
    summary = WorkbookService(workbooks, ExcelWorkbookImporter()).import_bytes(source.name, source.read_bytes())
    generation_service = GenerationService(workbooks, generations, RuleBasedFlowTranslator(), syntax_checker=PassingSyntaxChecker())
    generated = generation_service.create(CreateGenerationRequest(workbook_id=summary.workbook_id, mode=RunMode.UNATTENDED))
    service = RunService(
        workbooks, generations, runs, GeneratedPytestPackageBuilder(runs), PreparedDevice(), PassingPytestRunner(),
        result_writer=ResultWorkbookWriter(), exporter=RunExporter(tmp_path), background=False,
    )
    return service, generated


def test_delivery_and_fixture_verification_manifest(tmp_path):
    service, generation = build_service(tmp_path)
    result = service.create(CreateRunRequest(generation_id=generation.generation_id))
    assert result.state == RunState.COMPLETED
    assert result.export_status == "completed"
    root = service.run_repository.run_dir(result.run_id)
    exported = Path(result.export_path)
    assert exported == tmp_path / "outputs" / result.run_id
    assert (exported / "export-manifest.json").is_file()
    manifest = json.loads((root / "result/writeback-manifest.json").read_text())
    assert manifest["verified_fixture_rows"] == [6, 7]
    assert manifest["fixture_execution_counts"] == {"FX-APP-RESET": 0, "FX-LOGIN-READY": 0}
    # The fake runner has no fixture trace; absence must never become PASSED.
    assert result.result_workbook_available
    assert service.events(result.run_id)[-1].type == "run.export_completed"


def test_export_failure_does_not_misreport_delivery_or_destroy_runtime(tmp_path):
    service, generation = build_service(tmp_path)
    (tmp_path / "outputs").write_text("existing user file")
    result = service.create(CreateRunRequest(generation_id=generation.generation_id))
    assert result.state == RunState.COMPLETED  # Test outcome, not delivery outcome.
    assert result.export_status == "failed"
    assert result.export_error
    assert result.export_path is None
    assert (tmp_path / "outputs").read_text() == "existing user file"
    assert service.get_result_workbook(result.run_id).is_file()
    assert service.events(result.run_id)[-1].type == "run.export_failed"


def test_direct_run_creation_cannot_bypass_legacy_warning_review(tmp_path):
    service, generation = build_service(tmp_path)
    repository = service.generation_repository
    detail = repository.get_flow(generation.generation_id, "TC-HOME-001")
    repository.save_flow(generation.generation_id, detail.model_copy(update={"warnings": ["legacy warning"], "approval_method": None}))
    with pytest.raises(StateConflict, match="人工确认"):
        service.create(CreateRunRequest(generation_id=generation.generation_id))
    assert not (tmp_path / "runtime/runs").exists()


def test_attempt_timeout_includes_generated_default_startup(tmp_path, monkeypatch):
    service, generation = build_service(tmp_path)
    reset = service.generation_repository.final_yaml_path(generation.generation_id, "FX-APP-RESET")
    # This synthetic approved plan has no explicit startup command.
    reset.write_text("appId: example.app\n---\n- back\n")
    original_run = service.pytest_runner.run
    observed = []

    def capture(run_id, package, *, timeout_seconds, cancel_event, on_tick=None):
        config = json.loads(package.config_path.read_text())
        assert "SYS-DEFAULT-LAUNCH" in config["flow_paths"]
        observed.append(timeout_seconds)
        return original_run(run_id, package, timeout_seconds=timeout_seconds, cancel_event=cancel_event, on_tick=on_tick)

    monkeypatch.setattr(service.pytest_runner, "run", capture)
    result = service.create(CreateRunRequest(generation_id=generation.generation_id))
    assert result.state == RunState.COMPLETED
    config = service.workbook_repository.get(generation.workbook_id).config
    assert observed == [(config.test_timeout_ms / 1000 + service.maestro_startup_grace_seconds) * (generation.flow_count + 1) + 60]
