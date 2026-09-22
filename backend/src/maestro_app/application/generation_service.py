from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from maestro_app.application.errors import StateConflict
from maestro_app.application.flow_translator import FlowTranslator, TranslationError
from maestro_app.application.syntax_checker import MaestroSyntaxChecker
from maestro_app.application.yaml_compiler import (
    DeterministicYamlSyntaxRepairer,
    FlowYamlCompiler,
    YamlSyntaxRepairer,
)
from maestro_app.domain.enums import (
    FlowGenerationStatus,
    GenerationStatus,
    RunMode,
    Severity,
)
from maestro_app.domain.fixture_graph import FixtureDependencyResolver
from maestro_app.domain.models import (
    ApprovalRequest,
    CreateGenerationRequest,
    GeneratedFlowDetail,
    GenerationFlowSummary,
    GenerationSummary,
    StepMapping,
)
from maestro_app.infrastructure.generation_repository import GenerationRepository
from maestro_app.infrastructure.workbook_repository import WorkbookRepository


class GenerationService:
    def __init__(
        self,
        workbook_repository: WorkbookRepository,
        generation_repository: GenerationRepository,
        translator: FlowTranslator,
        compiler: FlowYamlCompiler | None = None,
        syntax_checker: MaestroSyntaxChecker | None = None,
        syntax_repairer: YamlSyntaxRepairer | None = None,
    ) -> None:
        self.workbook_repository = workbook_repository
        self.generation_repository = generation_repository
        self.translator = translator
        self.compiler = compiler or FlowYamlCompiler()
        self.syntax_checker = syntax_checker or MaestroSyntaxChecker()
        self.syntax_repairer = syntax_repairer or DeterministicYamlSyntaxRepairer()

    def create(self, request: CreateGenerationRequest) -> GenerationSummary:
        snapshot = self.workbook_repository.get(request.workbook_id)
        errors = [
            issue.model_dump(mode="json")
            for issue in snapshot.validation_issues
            if issue.severity == Severity.ERROR
        ]
        if errors or snapshot.config is None:
            raise StateConflict(
                "WORKBOOK_VALIDATION_FAILED",
                "工作簿包含阻断错误，不能开始生成",
                errors,
            )

        enabled_cases = [case for case in snapshot.cases if case.enabled]
        if request.case_ids is not None:
            available = {case.case_id: case for case in enabled_cases}
            missing = [case_id for case_id in request.case_ids if case_id not in available]
            if missing:
                raise StateConflict(
                    "CASE_SELECTION_INVALID",
                    "选择了不存在或已停用的 Case",
                    [{"case_id": case_id} for case_id in missing],
                )
            enabled_cases = [available[case_id] for case_id in request.case_ids]

        enabled_fixtures = [fixture for fixture in snapshot.fixtures if fixture.enabled]
        resolver = FixtureDependencyResolver(enabled_fixtures)
        fixture_order = resolver.resolve(fixture.fixture_id for fixture in enabled_fixtures)
        fixture_map = {fixture.fixture_id: fixture for fixture in enabled_fixtures}

        now = datetime.now(UTC)
        generation_id = uuid4().hex
        summary = GenerationSummary(
            generation_id=generation_id,
            workbook_id=snapshot.workbook_id,
            mode=request.mode,
            status=GenerationStatus.GENERATING,
            flow_count=0,
            approved_flow_count=0,
            fixture_plans={
                case.case_id: snapshot.fixture_plans.get(case.case_id, [])
                for case in enabled_cases
            },
            created_at=now,
            updated_at=now,
        )
        self.generation_repository.save_summary(summary)

        details: list[GeneratedFlowDetail] = []
        terminal_reason: str | None = None
        entities = [
            *(('fixture', fixture_map[fixture_id]) for fixture_id in fixture_order),
            *(('case', case) for case in enabled_cases),
        ]
        for kind, entity in entities:
            try:
                flow = (
                    self.translator.translate_fixture(entity, snapshot.config)
                    if kind == "fixture"
                    else self.translator.translate_case(entity, snapshot.config)
                )
                yaml_text = self.compiler.compile(flow)
                yaml_path = self.generation_repository.write_yaml(
                    generation_id, flow.flow_id, yaml_text
                )
                syntax = self.syntax_checker.check(
                    yaml_path,
                    maestro_command=snapshot.config.maestro_command,
                    timeout_seconds=max(10, snapshot.config.test_timeout_ms / 1000),
                )
                warnings = list(flow.generation_context.warnings)
                syntax_attempts = 1
                syntax_repairs = 0
                while (
                    not syntax.valid
                    and syntax_repairs < snapshot.config.max_syntax_repair
                ):
                    repaired_yaml = self.syntax_repairer.repair(
                        yaml_text,
                        syntax.output,
                        attempt=syntax_repairs + 1,
                    )
                    if repaired_yaml is None or repaired_yaml == yaml_text:
                        break
                    syntax_repairs += 1
                    yaml_text = repaired_yaml
                    yaml_path = self.generation_repository.write_final_yaml(
                        generation_id, flow.flow_id, yaml_text
                    )
                    syntax = self.syntax_checker.check(
                        yaml_path,
                        maestro_command=snapshot.config.maestro_command,
                        timeout_seconds=max(
                            10, snapshot.config.test_timeout_ms / 1000
                        ),
                    )
                    syntax_attempts += 1
                if syntax_repairs:
                    warnings.append(
                        f"Maestro YAML 语法自动修复 {syntax_repairs} 次，请人工复核"
                    )
                status = (
                    FlowGenerationStatus.NEEDS_REVIEW
                    if warnings
                    else FlowGenerationStatus.GENERATED
                )
                if not syntax.valid:
                    status = FlowGenerationStatus.FAILED
                    warnings.append(
                        f"Maestro 语法检查失败（exit={syntax.exit_code}）：{syntax.output}"
                    )
                detail = GeneratedFlowDetail(
                    flow_id=flow.flow_id,
                    flow_kind=flow.flow_kind.value,
                    name=flow.name,
                    status=status,
                    ir=flow,
                    yaml=yaml_text,
                    mappings=self._mappings(flow),
                    warnings=warnings,
                    syntax_valid=syntax.valid,
                    syntax_output=syntax.output,
                    syntax_attempts=syntax_attempts,
                    syntax_repairs=syntax_repairs,
                    approved=request.mode == RunMode.UNATTENDED and syntax.valid,
                )
                if detail.approved:
                    detail = detail.model_copy(
                        update={"status": FlowGenerationStatus.APPROVED}
                    )
                self.generation_repository.save_flow(generation_id, detail)
                details.append(detail)
                if not syntax.valid:
                    terminal_reason = f"{flow.flow_id} 未通过 Maestro 语法检查"
                    break
            except (TranslationError, ValueError) as exc:
                terminal_reason = str(exc)
                break

        if terminal_reason is not None:
            status = GenerationStatus.FAILED
        elif request.mode == RunMode.REVIEW:
            status = GenerationStatus.AWAITING_REVIEW
        else:
            status = GenerationStatus.READY
        summary = self._summary(
            summary,
            details,
            status=status,
            terminal_reason=terminal_reason,
        )
        self.generation_repository.save_summary(summary)
        return summary

    def get(self, generation_id: str) -> GenerationSummary:
        return self.generation_repository.get_summary(generation_id)

    def get_flow(self, generation_id: str, flow_id: str) -> GeneratedFlowDetail:
        self.get(generation_id)
        return self.generation_repository.get_flow(generation_id, flow_id)

    def approve(
        self, generation_id: str, request: ApprovalRequest
    ) -> GenerationSummary:
        summary = self.get(generation_id)
        if summary.mode != RunMode.REVIEW or summary.status not in {
            GenerationStatus.AWAITING_REVIEW,
            GenerationStatus.READY,
        }:
            raise StateConflict(
                "GENERATION_NOT_REVIEWABLE", "当前生成任务不能进行人工确认"
            )
        known = {flow.flow_id for flow in summary.flows}
        unknown = [flow_id for flow_id in request.flow_ids if flow_id not in known]
        if unknown:
            raise StateConflict(
                "FLOW_SELECTION_INVALID",
                "包含未知 Flow",
                [{"flow_id": flow_id} for flow_id in unknown],
            )
        for flow_id in request.flow_ids:
            detail = self.get_flow(generation_id, flow_id)
            if not detail.syntax_valid or detail.status == FlowGenerationStatus.FAILED:
                raise StateConflict(
                    "FLOW_NOT_APPROVABLE", f"Flow {flow_id} 存在阻断错误"
                )
            detail = detail.model_copy(
                update={
                    "approved": True,
                    "status": FlowGenerationStatus.APPROVED,
                }
            )
            self.generation_repository.save_flow(generation_id, detail)

        details = [
            self.get_flow(generation_id, flow.flow_id) for flow in summary.flows
        ]
        all_approved = all(detail.approved for detail in details)
        updated = self._summary(
            summary,
            details,
            status=(
                GenerationStatus.READY
                if all_approved
                else GenerationStatus.AWAITING_REVIEW
            ),
        )
        self.generation_repository.save_summary(updated)
        return updated

    @staticmethod
    def _mappings(flow) -> list[StepMapping]:
        mappings: list[StepMapping] = []
        for command in flow.commands:
            selector = getattr(command, "selector", None)
            mappings.append(
                StepMapping(
                    source_field=command.source_ref.field.value,
                    source_ordinal=command.source_ref.ordinal,
                    source_text=command.source_ref.text,
                    command_type=command.type,
                    selector_strategy=(
                        selector.strategy.value if selector is not None else None
                    ),
                    selector_value=selector.value if selector is not None else None,
                    assertion=bool(getattr(command, "assertion", False)),
                )
            )
        return mappings

    @staticmethod
    def _summary(
        base: GenerationSummary,
        details: list[GeneratedFlowDetail],
        *,
        status: GenerationStatus,
        terminal_reason: str | None = None,
    ) -> GenerationSummary:
        flows = [
            GenerationFlowSummary(
                flow_id=detail.flow_id,
                flow_kind=detail.flow_kind,
                name=detail.name,
                status=detail.status,
                warning_count=len(detail.warnings),
                syntax_valid=detail.syntax_valid,
                approved=detail.approved,
            )
            for detail in details
        ]
        return base.model_copy(
            update={
                "status": status,
                "flow_count": len(flows),
                "approved_flow_count": sum(flow.approved for flow in flows),
                "flows": flows,
                "updated_at": datetime.now(UTC),
                "terminal_reason": terminal_reason,
            }
        )
