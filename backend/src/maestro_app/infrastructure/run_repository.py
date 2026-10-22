from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maestro_app.application.errors import ResourceNotFound
from maestro_app.domain.models import Artifact, Run, RunEvent


class UnsafeRunPath(ValueError):
    """Raised when a requested path escapes the configured runtime directory."""


class RunRepository:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir.resolve()
        self._event_lock = threading.Lock()

    def run_dir(self, run_id: str) -> Path:
        if not run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
            raise UnsafeRunPath("run_id must be a single safe path segment")
        target = (self.runtime_dir / "runs" / run_id).resolve()
        self._assert_within_runtime(target)
        return target

    def initialize(self, run_id: str) -> Path:
        root = self.run_dir(run_id)
        for relative in (
            "source",
            "generated/fixtures",
            "generated/cases",
            "generated/pytest",
            "generated/mappings",
            "reports",
            "artifacts/logs",
            "artifacts/screenshots",
            "artifacts/hierarchy",
            "repairs",
            "result",
            "events",
            "attempts",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)
        return root

    def register_artifact(
        self,
        run_id: str,
        relative_path: str,
        *,
        kind: str,
        media_type: str | None = None,
        case_id: str | None = None,
        attempt_id: str | None = None,
    ) -> Artifact:
        root = self.run_dir(run_id)
        target = (root / relative_path).resolve()
        self._assert_within(root, target)
        if not target.is_file():
            raise FileNotFoundError(target)
        artifact = Artifact(
            artifact_id=f"artifact-{hashlib.sha256(relative_path.encode()).hexdigest()[:16]}",
            kind=kind,
            relative_path=str(target.relative_to(root)),
            media_type=(
                media_type
                or mimetypes.guess_type(target.name)[0]
                or "application/octet-stream"
            ),
            sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            case_id=case_id,
            attempt_id=attempt_id,
        )
        run = self.get_run(run_id)
        retained = [item for item in run.artifacts if item.artifact_id != artifact.artifact_id]
        updated = run.model_copy(
            update={
                "artifacts": [*retained, artifact],
                "updated_at": datetime.now(UTC),
            }
        )
        self.save_run(updated)
        self.write_json_atomic(
            run_id,
            "result/artifacts.json",
            [item.model_dump(mode="json") for item in updated.artifacts],
        )
        return artifact

    def artifact_path(self, run_id: str, artifact_id: str) -> tuple[Artifact, Path]:
        run = self.get_run(run_id)
        artifact = next(
            (item for item in run.artifacts if item.artifact_id == artifact_id),
            None,
        )
        if artifact is None:
            raise ResourceNotFound("artifact", artifact_id)
        root = self.run_dir(run_id)
        target = (root / artifact.relative_path).resolve()
        self._assert_within(root, target)
        if not target.is_file():
            raise ResourceNotFound("artifact", artifact_id)
        return artifact, target

    def result_workbook_path(self, run_id: str) -> Path:
        run = self.get_run(run_id)
        if not run.result_workbook_path:
            raise ResourceNotFound("result workbook", run_id)
        root = self.run_dir(run_id)
        target = (root / run.result_workbook_path).resolve()
        self._assert_within(root, target)
        if not target.is_file():
            raise ResourceNotFound("result workbook", run_id)
        return target

    def save_run(self, run: Run) -> Path:
        return self.write_json_atomic(
            run.run_id,
            "run.json",
            run.model_dump(mode="json"),
        )

    def get_run(self, run_id: str) -> Run:
        path = self.run_dir(run_id) / "run.json"
        if not path.is_file():
            raise ResourceNotFound("run", run_id)
        return Run.model_validate_json(path.read_text(encoding="utf-8"))

    def list_runs(self) -> list[Run]:
        # Fail closed on corrupt records or links rather than silently ignoring
        # a possibly active Run during restart recovery.
        result = []
        for path in sorted((self.runtime_dir / "runs").glob("*/run.json")):
            if path.is_symlink() or path.parent.is_symlink():
                raise UnsafeRunPath("linked Run records cannot be recovered")
            run = self.get_run(path.parent.name)
            if run.run_id != path.parent.name:
                raise UnsafeRunPath("Run identity does not match its directory")
            result.append(run)
        return result

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
    ) -> tuple[Run, RunEvent]:
        with self._event_lock:
            current = self.get_run(run.run_id)
            # A crash may persist an event before updating run.json's cursor.
            # Never replace that event with a recovery event on restart.
            committed = [int(path.stem) for path in (self.run_dir(run.run_id) / "events").glob("*.json")]
            sequence = max([current.events_cursor, *committed]) + 1
            event = RunEvent(
                event_id=f"{run.run_id}-{sequence:06d}",
                run_id=run.run_id,
                sequence=sequence,
                type=event_type,
                occurred_at=datetime.now(UTC),
                entity_type=entity_type,
                entity_id=entity_id,
                state=state,
                message=message,
                data=data or {},
            )
            event_path = (
                self.initialize(run.run_id) / "events" / f"{sequence:06d}.json"
            )
            self._write_json_path_atomic(
                event_path, event.model_dump(mode="json")
            )
            updated = current.model_copy(
                update={
                    "events_cursor": sequence,
                    "updated_at": datetime.now(UTC),
                }
            )
            self.save_run(updated)
            return updated, event

    def list_events(self, run_id: str, after: int = 0) -> list[RunEvent]:
        run_file = self.run_dir(run_id) / "run.json"
        if not run_file.is_file():
            raise ResourceNotFound("run", run_id)
        event_dir = self.run_dir(run_id) / "events"
        if not event_dir.is_dir():
            return []
        events: list[RunEvent] = []
        for path in sorted(event_dir.glob("*.json")):
            if int(path.stem) <= after:
                continue
            events.append(
                RunEvent.model_validate_json(path.read_text(encoding="utf-8"))
            )
        return events

    def write_text_atomic(self, run_id: str, relative_path: str, value: str) -> Path:
        root = self.initialize(run_id)
        target = (root / relative_path).resolve()
        self._assert_within(root, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_bytes_atomic(target, value.encode("utf-8"))
        return target

    def copy_file(self, run_id: str, relative_path: str, source: Path) -> Path:
        root = self.initialize(run_id)
        target = (root / relative_path).resolve()
        self._assert_within(root, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_bytes_atomic(target, source.read_bytes())
        return target

    def write_json_atomic(self, run_id: str, relative_path: str, value: Any) -> Path:
        root = self.initialize(run_id)
        target = (root / relative_path).resolve()
        self._assert_within(root, target)
        target.parent.mkdir(parents=True, exist_ok=True)

        self._write_json_path_atomic(target, value)
        return target

    @staticmethod
    def _write_json_path_atomic(target: Path, value: Any) -> None:
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            text=True,
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as temp_file:
                json.dump(value, temp_file, ensure_ascii=False, indent=2)
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_name, target)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _write_bytes_atomic(target: Path, content: bytes) -> None:
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_name, target)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def read_json(self, run_id: str, relative_path: str) -> Any:
        root = self.run_dir(run_id)
        target = (root / relative_path).resolve()
        self._assert_within(root, target)
        with target.open(encoding="utf-8") as source:
            return json.load(source)

    def _assert_within_runtime(self, path: Path) -> None:
        self._assert_within(self.runtime_dir, path)

    @staticmethod
    def _assert_within(root: Path, path: Path) -> None:
        if path != root and root not in path.parents:
            raise UnsafeRunPath(f"path escapes run repository: {path}")
