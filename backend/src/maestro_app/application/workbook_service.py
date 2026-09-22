from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from maestro_app.application.errors import ApplicationError
from maestro_app.domain.models import (
    ValidationReport,
    WorkbookSnapshot,
    WorkbookSummary,
)
from maestro_app.infrastructure.excel_importer import ExcelWorkbookImporter
from maestro_app.infrastructure.workbook_repository import WorkbookRepository


class WorkbookService:
    max_upload_bytes = 20 * 1024 * 1024

    def __init__(
        self,
        repository: WorkbookRepository,
        importer: ExcelWorkbookImporter | None = None,
    ) -> None:
        self.repository = repository
        self.importer = importer or ExcelWorkbookImporter()

    def import_bytes(self, filename: str, content: bytes) -> WorkbookSummary:
        safe_filename = Path(filename).name
        if not safe_filename.lower().endswith(".xlsx"):
            raise ApplicationError(
                "WORKBOOK_TYPE_UNSUPPORTED",
                "只支持 .xlsx 工作簿",
                status_code=422,
            )
        if not content:
            raise ApplicationError(
                "WORKBOOK_EMPTY", "上传文件为空", status_code=422
            )
        if len(content) > self.max_upload_bytes:
            raise ApplicationError(
                "WORKBOOK_TOO_LARGE",
                "工作簿超过 20 MiB 上限",
                status_code=422,
            )

        workbook_id = uuid4().hex
        source_sha256 = hashlib.sha256(content).hexdigest()
        source_path = self.repository.store_source(workbook_id, content)
        snapshot = self.importer.import_workbook(
            source_path,
            workbook_id=workbook_id,
            source_filename=safe_filename,
            source_sha256=source_sha256,
        )
        self.repository.save_snapshot(snapshot)
        return WorkbookSummary.from_snapshot(snapshot)

    def get_snapshot(self, workbook_id: str) -> WorkbookSnapshot:
        return self.repository.get(workbook_id)

    def get_summary(self, workbook_id: str) -> WorkbookSummary:
        return WorkbookSummary.from_snapshot(self.get_snapshot(workbook_id))

    def get_validation(self, workbook_id: str) -> ValidationReport:
        snapshot = self.get_snapshot(workbook_id)
        return ValidationReport(
            workbook_id=workbook_id,
            valid=snapshot.counts.errors == 0,
            issues=snapshot.validation_issues,
        )
