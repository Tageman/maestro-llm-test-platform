import io
import json
from pathlib import Path

import pytest

from maestro_app.application.errors import StateConflict
from maestro_app.application.flow_translator import (
    OpenAICompatibleFlowTranslator,
    RuleBasedFlowTranslator,
)
from maestro_app.application.generation_service import GenerationService
from maestro_app.application.syntax_checker import SyntaxCheckResult
from maestro_app.application.workbook_service import WorkbookService
from maestro_app.domain.enums import FlowGenerationStatus, GenerationStatus, RunMode
from maestro_app.domain.models import ApprovalRequest, CreateGenerationRequest
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


class WarningRuleTranslator(RuleBasedFlowTranslator):
    def translate_case(self, case, config):
        flow = super().translate_case(case, config)
        return flow.model_copy(
            update={
                "generation_context": flow.generation_context.model_copy(
                    update={"warnings": ["定位器需要人工复核"]}
                )
            }
        )


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


@pytest.mark.parametrize("mode", [RunMode.REVIEW, RunMode.UNATTENDED])
def test_syntax_repair_preserves_initial_and_records_attempt(
    tmp_path: Path, mode: RunMode
) -> None:
    checker = SequenceSyntaxChecker([False, True, True, True])
    repairer = CommentRepairer()
    workbook, _, repository, service = _service(tmp_path, checker, repairer)

    generation = service.create(
        CreateGenerationRequest(workbook_id=workbook.workbook_id, mode=mode)
    )
    detail = service.get_flow(generation.generation_id, "FX-APP-RESET")
    flow_dir = repository.flow_dir(generation.generation_id, "FX-APP-RESET")

    assert generation.status == GenerationStatus.AWAITING_REVIEW
    assert detail.status == FlowGenerationStatus.NEEDS_REVIEW
    assert detail.syntax_valid is True
    assert detail.syntax_attempts == 2
    assert detail.syntax_repairs == 1
    assert detail.approved is False
    assert "请人工复核" in detail.warnings[0]
    assert (flow_dir / "initial.yaml").read_text() != (
        flow_dir / "final.yaml"
    ).read_text()
    approved = service.approve(
        generation.generation_id,
        ApprovalRequest(flow_ids=[flow.flow_id for flow in generation.flows]),
    )
    assert approved.status == GenerationStatus.READY
    assert approved.mode == mode
    assert approved.approved_flow_count == approved.flow_count == 3


@pytest.mark.parametrize("provider", ["rules", "llm"])
def test_unattended_translator_warning_requires_manual_review(
    tmp_path: Path, monkeypatch, provider: str
) -> None:
    workbook, workbook_repository, repository, service = _service(
        tmp_path, SequenceSyntaxChecker([True]), CommentRepairer()
    )
    if provider == "rules":
        service.translator = WarningRuleTranslator()
    else:
        snapshot = workbook_repository.get(workbook.workbook_id)
        assert snapshot.config is not None
        translator = WarningRuleTranslator()
        candidates = {
            fixture.fixture_id: translator.translate_fixture(fixture, snapshot.config)
            for fixture in snapshot.fixtures
        }
        candidates.update(
            {
                case.case_id: translator.translate_case(case, snapshot.config)
                for case in snapshot.cases
            }
        )

        def fake_urlopen(request, timeout):
            payload = json.loads(request.data)
            source = json.loads(payload["messages"][1]["content"])
            candidate = candidates[source["entity_id"]]
            return io.BytesIO(
                json.dumps(
                    {"choices": [{"message": {"content": candidate.model_dump_json()}}]}
                ).encode("utf-8")
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        service.translator = OpenAICompatibleFlowTranslator(
            base_url="https://llm.example/v1",
            model="test-warning-model",
            api_key=None,
            schema={"type": "object"},
            timeout_seconds=1,
        )

    created = service.create(
        CreateGenerationRequest(workbook_id=workbook.workbook_id, mode=RunMode.UNATTENDED)
    )
    generation = repository.get_summary(created.generation_id)
    detail = repository.get_flow(created.generation_id, "TC-HOME-001")

    assert generation.status == GenerationStatus.AWAITING_REVIEW
    assert generation.mode == RunMode.UNATTENDED
    assert generation.approved_flow_count == 2
    assert detail.status == FlowGenerationStatus.NEEDS_REVIEW
    assert detail.approved is False
    assert detail.syntax_valid is True
    assert detail.warnings == ["定位器需要人工复核"]
    assert detail.ir.generation_context.model == (
        "rule-based-v1" if provider == "rules" else "test-warning-model"
    )

    approved = service.approve(
        generation.generation_id, ApprovalRequest(flow_ids=["TC-HOME-001"])
    )
    assert approved.status == GenerationStatus.READY
    assert approved.approved_flow_count == 3
    approved_detail = repository.get_flow(generation.generation_id, "TC-HOME-001")
    assert approved_detail.status == FlowGenerationStatus.APPROVED
    assert approved_detail.approved is True
    assert approved_detail.warnings == detail.warnings


def test_partial_warning_approval_does_not_release_unattended_generation(
    tmp_path: Path,
) -> None:
    workbook, _, _, service = _service(
        tmp_path, SequenceSyntaxChecker([False, True]), CommentRepairer()
    )
    service.translator = WarningRuleTranslator()
    generation = service.create(
        CreateGenerationRequest(workbook_id=workbook.workbook_id, mode=RunMode.UNATTENDED)
    )
    assert generation.approved_flow_count == 1

    partial = service.approve(
        generation.generation_id, ApprovalRequest(flow_ids=["TC-HOME-001"])
    )
    assert partial.status == GenerationStatus.AWAITING_REVIEW
    assert partial.approved_flow_count == 2
    assert service.get_flow(generation.generation_id, "FX-APP-RESET").approved is False

    complete = service.approve(
        generation.generation_id, ApprovalRequest(flow_ids=["FX-APP-RESET"])
    )
    assert complete.status == GenerationStatus.READY
    assert complete.approved_flow_count == 3


def test_unattended_without_warning_is_automatically_ready(tmp_path: Path) -> None:
    workbook, _, _, service = _service(
        tmp_path, SequenceSyntaxChecker([True]), CommentRepairer()
    )

    generation = service.create(
        CreateGenerationRequest(workbook_id=workbook.workbook_id, mode=RunMode.UNATTENDED)
    )

    assert generation.status == GenerationStatus.READY
    assert generation.approved_flow_count == generation.flow_count == 3
    assert all(flow.approved and flow.warning_count == 0 for flow in generation.flows)


def test_legacy_warning_approval_requires_new_manual_evidence(tmp_path):
    workbook, _, repository, service = _service(
        tmp_path, SequenceSyntaxChecker([True]), CommentRepairer()
    )
    generation = service.create(CreateGenerationRequest(workbook_id=workbook.workbook_id, mode=RunMode.UNATTENDED))
    detail = repository.get_flow(generation.generation_id, "TC-HOME-001")
    repository.save_flow(generation.generation_id, detail.model_copy(update={
        "warnings": ["legacy warning"], "approval_method": None,
    }))
    with pytest.raises(StateConflict):
        service.validate_for_execution(generation.generation_id)
    assert service.get(generation.generation_id).status == GenerationStatus.AWAITING_REVIEW
    assert not repository.get_flow(generation.generation_id, detail.flow_id).approved
    service.approve(generation.generation_id, ApprovalRequest(flow_ids=[detail.flow_id]))
    assert service.validate_for_execution(generation.generation_id).status == GenerationStatus.READY
    reviewed = repository.get_flow(generation.generation_id, detail.flow_id)
    assert reviewed.approval_method == "manual"
    assert reviewed.warnings == ["legacy warning"]


@pytest.mark.parametrize("mode", [RunMode.REVIEW, RunMode.UNATTENDED])
def test_syntax_repair_stops_at_configured_limit(
    tmp_path: Path, mode: RunMode
) -> None:
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
        CreateGenerationRequest(workbook_id=workbook.workbook_id, mode=mode)
    )
    detail = service.get_flow(generation.generation_id, "FX-APP-RESET")

    assert generation.status == GenerationStatus.FAILED
    assert detail.status == FlowGenerationStatus.FAILED
    assert detail.syntax_valid is False
    assert detail.syntax_attempts == 3
    assert detail.syntax_repairs == 2
    assert checker.calls == 3
    assert repairer.calls == 2
    assert detail.approved is False
    with pytest.raises(StateConflict, match="不能进行人工确认"):
        service.approve(
            generation.generation_id, ApprovalRequest(flow_ids=["FX-APP-RESET"])
        )
