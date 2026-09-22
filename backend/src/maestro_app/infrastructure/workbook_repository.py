from __future__ import annotations

import os
import tempfile
from pathlib import Path

from maestro_app.application.errors import ResourceNotFound
from maestro_app.domain.models import WorkbookSnapshot


class WorkbookRepository:
    def __init__(self, runtime_dir: Path) -> None:
        self.root = (runtime_dir / "workbooks").resolve()

    def workbook_dir(self, workbook_id: str) -> Path:
        self._validate_segment(workbook_id)
        path = (self.root / workbook_id).resolve()
        if self.root not in path.parents:
            raise ValueError("workbook path escapes repository")
        return path

    def store_source(self, workbook_id: str, content: bytes) -> Path:
        root = self.workbook_dir(workbook_id)
        root.mkdir(parents=True, exist_ok=True)
        target = root / "source.xlsx"
        self._write_bytes_atomic(target, content)
        return target

    def save_snapshot(self, snapshot: WorkbookSnapshot) -> Path:
        root = self.workbook_dir(snapshot.workbook_id)
        root.mkdir(parents=True, exist_ok=True)
        target = root / "snapshot.json"
        self._write_bytes_atomic(
            target,
            (snapshot.model_dump_json(indent=2) + "\n").encode("utf-8"),
        )
        return target

    def get(self, workbook_id: str) -> WorkbookSnapshot:
        path = self.workbook_dir(workbook_id) / "snapshot.json"
        if not path.is_file():
            raise ResourceNotFound("workbook", workbook_id)
        return WorkbookSnapshot.model_validate_json(path.read_text(encoding="utf-8"))

    def source_path(self, workbook_id: str) -> Path:
        path = self.workbook_dir(workbook_id) / "source.xlsx"
        if not path.is_file():
            raise ResourceNotFound("workbook source", workbook_id)
        return path

    @staticmethod
    def _validate_segment(value: str) -> None:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("identifier must be a safe path segment")

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
