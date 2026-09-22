from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from maestro_app.domain.enums import (
    CaseRunState,
    FailureType,
    FixturePhase,
    FixtureScope,
    FlowGenerationStatus,
    GenerationStatus,
    OverallStatus,
    RunMode,
    RunState,
    Severity,
    ToolStatus,
    WorkbookStatus,
)
from maestro_app.domain.flow_ir import FlowIR


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceStep(DomainModel):
    ordinal: int = Field(ge=1)
    text: str = Field(min_length=1)


class TestCaseDefinition(DomainModel):
    case_id: str = Field(min_length=1)
    module: str = Field(min_length=1)
    title: str = Field(min_length=1)
    pre_fixture_ids: list[str] = Field(default_factory=list)
    post_fixture_ids: list[str] = Field(default_factory=list)
    priority: str = Field(pattern=r"^P[0-3]$")
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    steps: list[SourceStep] = Field(min_length=1)
    expected_results: list[SourceStep] = Field(min_length=1)
    source_row: int = Field(ge=1)
    note: str | None = None

    @field_validator("pre_fixture_ids", "post_fixture_ids", "tags")
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("values must be unique")
        return values


class FixtureDefinition(DomainModel):
    fixture_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    phase: FixturePhase
    scope: FixtureScope
    module: str | None = None
    dependency_ids: list[str] = Field(default_factory=list)
    order: int
    enabled: bool = True
    steps: list[SourceStep] = Field(min_length=1)
    expected_results: list[SourceStep] = Field(min_length=1)
    source_row: int = Field(ge=1)
    note: str | None = None

    @field_validator("dependency_ids")
    @classmethod
    def unique_dependencies(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("fixture dependencies must be unique")
        return values


class ProjectConfig(DomainModel):
    project_name: str = Field(min_length=1)
    app_id: str = Field(min_length=1)
    apk_path: Path | None = None
    android_device_id: str | None = None
    avd_name: str | None = None
    maestro_command: str = Field(min_length=1)
    execution_target: str = Field(pattern=r"^android_emulator$")
    output_dir: Path
    test_timeout_ms: int = Field(gt=0)
    max_syntax_repair: int = Field(ge=0)
    max_locator_repair: int = Field(ge=0)
    max_total_run_attempts: int = Field(ge=1)
    continue_on_failure: bool
    launch_clear_state: bool
    pytest_workers: int = Field(ge=1, le=1)
    result_writeback: bool
    language: str = Field(pattern=r"^zh-CN$")
    fixture_id_separator: str = Field(min_length=1, max_length=1)
    allow_assertion_rewrite: bool = False

    @field_validator("allow_assertion_rewrite")
    @classmethod
    def assertion_rewrite_is_forbidden(cls, value: bool) -> bool:
        if value:
            raise ValueError("assertion rewrite is forbidden in phase one")
        return value


class ValidationIssue(DomainModel):
    code: str = Field(min_length=1)
    severity: Severity
    message: str = Field(min_length=1)
    sheet: str | None = None
    row: int | None = Field(default=None, ge=1)
    column: str | None = None
    entity_id: str | None = None
    field: str | None = None
    suggestion: str | None = None


class ToolCapability(DomainModel):
    name: str
    status: ToolStatus
    available: bool
    version: str | None = None
    command: str | None = None
    detail: str


class AndroidDevice(DomainModel):
    device_id: str
    state: str
    selected: bool = False


class AppCapability(DomainModel):
    app_id: str
    installed: bool
    device_id: str | None = None


class CapabilityReport(DomainModel):
    overall_status: OverallStatus
    checked_at: datetime
    tools: list[ToolCapability]
    android_devices: list[AndroidDevice]
    avds: list[str]
    app: AppCapability


class HealthResponse(DomainModel):
    status: str = "ok"
    service: str
    version: str
    api_version: str
    time: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Attempt(DomainModel):
    attempt_id: str
    ordinal: int = Field(ge=1)
    state: CaseRunState
    failure_type: FailureType | None = None
    failure_reason: str | None = None
    failed_step: int | None = Field(default=None, ge=1)
    failed_selector: str | None = None
    exit_code: int | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    repair_id: str | None = None


class RepairRecord(DomainModel):
    repair_id: str
    case_id: str
    attempt_id: str
    failure_type: FailureType
    evidence_artifact_ids: list[str] = Field(default_factory=list)
    reason: str
    before_selector: str
    after_selector: str
    yaml_diff_path: str
    approved_automatically: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Artifact(DomainModel):
    artifact_id: str
    kind: str
    relative_path: str
    media_type: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    case_id: str | None = None
    attempt_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CaseRun(DomainModel):
    case_id: str
    state: CaseRunState = CaseRunState.PENDING
    fixture_plan: list[str] = Field(default_factory=list)
    attempts: list[Attempt] = Field(default_factory=list)
    business_result: str | None = None
    cleanup_result: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)


class CaseRunDetail(CaseRun):
    repairs: list[RepairRecord] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)


class Run(DomainModel):
    run_id: str
    generation_id: str
    workbook_id: str
    mode: RunMode
    state: RunState = RunState.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    ended_at: datetime | None = None
    selected_case_ids: list[str] = Field(default_factory=list)
    config_snapshot: ProjectConfig | None = None
    device_id: str | None = None
    avd_name: str | None = None
    app_id: str | None = None
    pytest_node_ids: list[str] = Field(default_factory=list)
    case_runs: list[CaseRun] = Field(default_factory=list)
    repairs: list[RepairRecord] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    result_workbook_path: str | None = None
    events_cursor: int = Field(default=0, ge=0)
    cancel_requested: bool = False
    terminal_reason: str | None = None


class RunEvent(DomainModel):
    event_id: str
    run_id: str
    sequence: int = Field(ge=1)
    type: str = Field(min_length=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    entity_type: str
    entity_id: str
    state: str | None = None
    message: str
    data: dict = Field(default_factory=dict)


class DevicePreparation(DomainModel):
    device_id: str
    avd_name: str
    app_id: str
    app_installed: bool
    boot_completed: bool
    checks: list[dict] = Field(default_factory=list)


class WorkbookCounts(DomainModel):
    cases: int = Field(ge=0)
    fixtures: int = Field(ge=0)
    configs: int = Field(ge=0)
    enabled_cases: int = Field(ge=0)
    enabled_fixtures: int = Field(ge=0)
    errors: int = Field(ge=0)
    warnings: int = Field(ge=0)


class WorkbookSnapshot(DomainModel):
    workbook_id: str = Field(min_length=1)
    source_filename: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    imported_at: datetime
    status: WorkbookStatus
    cases: list[TestCaseDefinition] = Field(default_factory=list)
    fixtures: list[FixtureDefinition] = Field(default_factory=list)
    config: ProjectConfig | None = None
    raw_config: dict[str, str | int | bool | None] = Field(default_factory=dict)
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    fixture_plans: dict[str, list[str]] = Field(default_factory=dict)

    @property
    def counts(self) -> WorkbookCounts:
        return WorkbookCounts(
            cases=len(self.cases),
            fixtures=len(self.fixtures),
            configs=len(self.raw_config),
            enabled_cases=sum(case.enabled for case in self.cases),
            enabled_fixtures=sum(fixture.enabled for fixture in self.fixtures),
            errors=sum(issue.severity == Severity.ERROR for issue in self.validation_issues),
            warnings=sum(
                issue.severity == Severity.WARNING for issue in self.validation_issues
            ),
        )


class WorkbookSummary(DomainModel):
    workbook_id: str
    source_filename: str
    source_sha256: str
    imported_at: datetime
    status: WorkbookStatus
    counts: WorkbookCounts
    fixture_plans: dict[str, list[str]] = Field(default_factory=dict)

    @classmethod
    def from_snapshot(cls, snapshot: WorkbookSnapshot) -> "WorkbookSummary":
        return cls(
            workbook_id=snapshot.workbook_id,
            source_filename=snapshot.source_filename,
            source_sha256=snapshot.source_sha256,
            imported_at=snapshot.imported_at,
            status=snapshot.status,
            counts=snapshot.counts,
            fixture_plans=snapshot.fixture_plans,
        )


class ValidationReport(DomainModel):
    workbook_id: str
    valid: bool
    issues: list[ValidationIssue]


class CreateGenerationRequest(DomainModel):
    workbook_id: str = Field(min_length=1)
    mode: RunMode
    case_ids: list[str] | None = None

    @field_validator("case_ids")
    @classmethod
    def unique_case_ids(cls, values: list[str] | None) -> list[str] | None:
        if values is not None and len(values) != len(set(values)):
            raise ValueError("case_ids must be unique")
        return values


class StepMapping(DomainModel):
    source_field: str
    source_ordinal: int = Field(ge=1)
    source_text: str
    command_type: str
    selector_strategy: str | None = None
    selector_value: str | None = None
    assertion: bool = False
    warning: str | None = None


class GeneratedFlowDetail(DomainModel):
    flow_id: str
    flow_kind: str
    name: str
    status: FlowGenerationStatus
    ir: FlowIR
    yaml: str
    mappings: list[StepMapping]
    warnings: list[str] = Field(default_factory=list)
    syntax_valid: bool
    syntax_output: str | None = None
    syntax_attempts: int = Field(default=1, ge=1)
    syntax_repairs: int = Field(default=0, ge=0)
    approved: bool = False


class GenerationFlowSummary(DomainModel):
    flow_id: str
    flow_kind: str
    name: str
    status: FlowGenerationStatus
    warning_count: int = Field(ge=0)
    syntax_valid: bool
    approved: bool


class GenerationSummary(DomainModel):
    generation_id: str
    workbook_id: str
    mode: RunMode
    status: GenerationStatus
    flow_count: int = Field(ge=0)
    approved_flow_count: int = Field(ge=0)
    flows: list[GenerationFlowSummary] = Field(default_factory=list)
    fixture_plans: dict[str, list[str]] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    terminal_reason: str | None = None


class ApprovalRequest(DomainModel):
    flow_ids: list[str] = Field(min_length=1)

    @field_validator("flow_ids")
    @classmethod
    def unique_flow_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("flow_ids must be unique")
        return values


class CreateRunRequest(DomainModel):
    generation_id: str = Field(min_length=1)
    case_ids: list[str] | None = None

    @field_validator("case_ids")
    @classmethod
    def unique_run_case_ids(cls, values: list[str] | None) -> list[str] | None:
        if values is not None and len(values) != len(set(values)):
            raise ValueError("case_ids must be unique")
        return values


class RunSummary(DomainModel):
    run_id: str
    generation_id: str
    workbook_id: str
    state: RunState
    mode: RunMode
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    device_id: str | None = None
    avd_name: str | None = None
    app_id: str | None = None
    selected_case_ids: list[str] = Field(default_factory=list)
    pytest_node_ids: list[str] = Field(default_factory=list)
    case_counts: dict[str, int] = Field(default_factory=dict)
    events_cursor: int = Field(default=0, ge=0)
    cancel_requested: bool = False
    terminal_reason: str | None = None
    repair_count: int = Field(default=0, ge=0)
    result_workbook_available: bool = False
    html_report_artifact_id: str | None = None

    @classmethod
    def from_run(cls, run: Run) -> "RunSummary":
        counts: dict[str, int] = {}
        for case_run in run.case_runs:
            counts[case_run.state.value] = counts.get(case_run.state.value, 0) + 1
        return cls(
            run_id=run.run_id,
            generation_id=run.generation_id,
            workbook_id=run.workbook_id,
            state=run.state,
            mode=run.mode,
            created_at=run.created_at,
            updated_at=run.updated_at,
            started_at=run.started_at,
            ended_at=run.ended_at,
            device_id=run.device_id,
            avd_name=run.avd_name,
            app_id=run.app_id,
            selected_case_ids=run.selected_case_ids,
            pytest_node_ids=run.pytest_node_ids,
            case_counts=counts,
            events_cursor=run.events_cursor,
            cancel_requested=run.cancel_requested,
            terminal_reason=run.terminal_reason,
            repair_count=len(run.repairs),
            result_workbook_available=bool(run.result_workbook_path),
            html_report_artifact_id=next(
                (item.artifact_id for item in run.artifacts if item.kind == "html_report"),
                None,
            ),
        )
