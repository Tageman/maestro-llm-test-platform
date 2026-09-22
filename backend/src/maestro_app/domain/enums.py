from __future__ import annotations

from enum import StrEnum


class RunMode(StrEnum):
    REVIEW = "review"
    UNATTENDED = "unattended"


class RunState(StrEnum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    GENERATING = "GENERATING"
    GENERATION_FAILED = "GENERATION_FAILED"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    READY = "READY"
    PREPARING_DEVICE = "PREPARING_DEVICE"
    RUNNING = "RUNNING"
    DIAGNOSING = "DIAGNOSING"
    REPAIRING = "REPAIRING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_FAILURES = "COMPLETED_WITH_FAILURES"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CaseRunState(StrEnum):
    PENDING = "PENDING"
    SETTING_UP = "SETTING_UP"
    RUNNING = "RUNNING"
    TEARING_DOWN = "TEARING_DOWN"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    FIXTURE_FAILED = "FIXTURE_FAILED"
    ENV_ERROR = "ENV_ERROR"
    TIMEOUT = "TIMEOUT"


class FailureType(StrEnum):
    YAML_SYNTAX = "YAML_SYNTAX"
    LOCATOR = "LOCATOR"
    ASSERTION = "ASSERTION"
    ENVIRONMENT = "ENVIRONMENT"
    FIXTURE = "FIXTURE"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class EntityType(StrEnum):
    CASE = "case"
    FIXTURE = "fixture"


class SourceField(StrEnum):
    STEPS = "steps"
    EXPECTED_RESULTS = "expected_results"


class FlowKind(StrEnum):
    CASE = "case"
    FIXTURE = "fixture"


class SelectorStrategy(StrEnum):
    TEXT = "text"
    RESOURCE_ID = "resource_id"
    CONTENT_DESCRIPTION = "content_description"


class FixturePhase(StrEnum):
    SETUP = "setup"
    TEARDOWN = "teardown"


class FixtureScope(StrEnum):
    FUNCTION = "function"
    MODULE = "module"
    SESSION = "session"


class ToolStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


class OverallStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class WorkbookStatus(StrEnum):
    IMPORTED = "imported"
    VALID = "valid"
    INVALID = "invalid"


class GenerationStatus(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    AWAITING_REVIEW = "awaiting_review"
    READY = "ready"
    FAILED = "failed"


class FlowGenerationStatus(StrEnum):
    GENERATED = "generated"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    FAILED = "failed"
