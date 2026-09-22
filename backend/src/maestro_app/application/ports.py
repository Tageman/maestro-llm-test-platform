from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from maestro_app.domain.models import (
    Artifact,
    DevicePreparation,
    GeneratedFlowDetail,
    GenerationSummary,
    ProjectConfig,
    Run,
    RunEvent,
    WorkbookSnapshot,
)


@dataclass(frozen=True, slots=True)
class PytestPackage:
    test_file: Path
    config_path: Path
    collection_path: Path
    junit_path: Path
    trace_path: Path
    stdout_path: Path
    node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ManagedProcessResult:
    returncode: int
    stdout_tail: str
    output_path: Path
    timed_out: bool = False
    cancelled: bool = False
    output_truncated: bool = False

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled


class WorkbookRepositoryPort(Protocol):
    def get(self, workbook_id: str) -> WorkbookSnapshot: ...
    def source_path(self, workbook_id: str) -> Path: ...


class GenerationRepositoryPort(Protocol):
    def get_summary(self, generation_id: str) -> GenerationSummary: ...
    def get_flow(self, generation_id: str, flow_id: str) -> GeneratedFlowDetail: ...
    def final_yaml_path(self, generation_id: str, flow_id: str) -> Path: ...


class RunRepositoryPort(Protocol):
    def initialize(self, run_id: str) -> Path: ...
    def save_run(self, run: Run) -> Path: ...
    def get_run(self, run_id: str) -> Run: ...
    def append_event(
        self,
        run: Run,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        state: str | None,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> tuple[Run, RunEvent]: ...
    def list_events(self, run_id: str, after: int = 0) -> list[RunEvent]: ...
    def write_json_atomic(self, run_id: str, relative_path: str, value: Any) -> Path: ...
    def write_text_atomic(self, run_id: str, relative_path: str, value: str) -> Path: ...
    def copy_file(self, run_id: str, relative_path: str, source: Path) -> Path: ...
    def run_dir(self, run_id: str) -> Path: ...
    def register_artifact(
        self,
        run_id: str,
        relative_path: str,
        *,
        kind: str,
        media_type: str,
        case_id: str | None = None,
        attempt_id: str | None = None,
    ) -> Artifact: ...
    def artifact_path(self, run_id: str, artifact_id: str) -> tuple[Artifact, Path]: ...
    def result_workbook_path(self, run_id: str) -> Path: ...


class DeviceManagerPort(Protocol):
    def prepare(self, config: ProjectConfig) -> DevicePreparation: ...


class PytestGeneratorPort(Protocol):
    def generate(
        self,
        *,
        run: Run,
        snapshot: WorkbookSnapshot,
        flow_paths: dict[str, Path],
        source_workbook: Path,
    ) -> PytestPackage: ...

    def configure(
        self,
        package: PytestPackage,
        *,
        config: ProjectConfig,
        device: DevicePreparation,
        run_dir: Path,
        attempt_root: Path | None = None,
    ) -> None: ...


class PytestRunnerPort(Protocol):
    def collect(self, package: PytestPackage) -> ManagedProcessResult: ...
    def run(
        self,
        run_id: str,
        package: PytestPackage,
        *,
        timeout_seconds: float,
        cancel_event: threading.Event,
        on_tick: Callable[[], None] | None = None,
    ) -> ManagedProcessResult: ...
    def cancel(self, run_id: str) -> None: ...
