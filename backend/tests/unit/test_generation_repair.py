from pathlib import Path

from maestro_app.application.flow_translator import RuleBasedFlowTranslator
from maestro_app.application.generation_service import GenerationService
from maestro_app.application.syntax_checker import SyntaxCheckResult
from maestro_app.application.workbook_service import WorkbookService
from maestro_app.domain.enums import FlowGenerationStatus, GenerationStatus, RunMode
from maestro_app.domain.models import CreateGenerationRequest
from maestro_app.infrastructure.excel_importer import ExcelWorkbookImporter
from maestro_app.infrastructure.generation_repository import GenerationRepository
from maestro_app.infrastructure.workbook_repository import WorkbookRepository
from m1_helpers import build_sample_workbook


class SequenceSyntaxChecker:
    def __init__(self, validity: list[bool]) -> None:
        self.validity = validity
        self.calls = 0

    def check(self, flow_path, *, maestro_command, timeout_seconds):
        valid = self.validity[min(self.calls, len(self.validity) - 1)]
        self.calls += 1
        return SyntaxCheckResult(
            valid=valid,
            output="OK" if valid else f"syntax error {self.calls}",
            exit_code=0 if valid else 1,
        )


class CommentRepairer:
    def __init__(self) -> None:
        self.calls = 0

    def repair(self, yaml_text, syntax_output, *, attempt):
        self.calls += 1
        return f"{yaml_text.rstrip()}\n# syntax-repair-{attempt}\n"


def _service(tmp_path: Path, checker, repairer):
    source = build_sample_workbook(tmp_path / "baseline.xlsx")
    workbook_repository = WorkbookRepository(tmp_path / "runtime")
    workbook_service = WorkbookService(
        workbook_repository, ExcelWorkbookImporter()
    )
    workbook = workbook_service.import_bytes(source.name, source.read_bytes())
    generation_repository = GenerationRepository(tmp_path / "runtime")
    service = GenerationService(
        workbook_repository,
        generation_repository,
        RuleBasedFlowTranslator(),
        syntax_checker=checker,
        syntax_repairer=repairer,
    )
    return workbook, workbook_repository, generation_repository, service


def test_syntax_repair_preserves_initial_and_records_attempt(tmp_path: Path) -> None:
    checker = SequenceSyntaxChecker([False, True, True, True])
    repairer = CommentRepairer()
    workbook, _, repository, service = _service(tmp_path, checker, repairer)

    generation = service.create(
        CreateGenerationRequest(workbook_id=workbook.workbook_id, mode=RunMode.REVIEW)
    )
    detail = service.get_flow(generation.generation_id, "FX-APP-RESET")
    flow_dir = repository.flow_dir(generation.generation_id, "FX-APP-RESET")

    assert generation.status == GenerationStatus.AWAITING_REVIEW
    assert detail.status == FlowGenerationStatus.NEEDS_REVIEW
    assert detail.syntax_valid is True
    assert detail.syntax_attempts == 2
    assert detail.syntax_repairs == 1
    assert "请人工复核" in detail.warnings[0]
    assert (flow_dir / "initial.yaml").read_text() != (
        flow_dir / "final.yaml"
    ).read_text()


def test_syntax_repair_stops_at_configured_limit(tmp_path: Path) -> None:
    checker = SequenceSyntaxChecker([False])
    repairer = CommentRepairer()
    workbook, workbook_repository, _, service = _service(
        tmp_path, checker, repairer
    )
    snapshot = workbook_repository.get(workbook.workbook_id)
    assert snapshot.config is not None
    workbook_repository.save_snapshot(
        snapshot.model_copy(
            update={
                "config": snapshot.config.model_copy(
                    update={"max_syntax_repair": 2}
                )
            }
        )
    )

    generation = service.create(
        CreateGenerationRequest(workbook_id=workbook.workbook_id, mode=RunMode.REVIEW)
    )
    detail = service.get_flow(generation.generation_id, "FX-APP-RESET")

    assert generation.status == GenerationStatus.FAILED
    assert detail.status == FlowGenerationStatus.FAILED
    assert detail.syntax_valid is False
    assert detail.syntax_attempts == 3
    assert detail.syntax_repairs == 2
    assert checker.calls == 3
    assert repairer.calls == 2
