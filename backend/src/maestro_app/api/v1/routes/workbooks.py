from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile, status

from maestro_app.domain.models import (
    ValidationReport,
    WorkbookSummary,
)


router = APIRouter()


@router.post(
    "/workbooks",
    response_model=WorkbookSummary,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Workbooks"],
)
async def upload_workbook(
    request: Request,
    file: UploadFile = File(...),
) -> WorkbookSummary:
    content = await file.read(request.app.state.workbook_service.max_upload_bytes + 1)
    return request.app.state.workbook_service.import_bytes(
        file.filename or "workbook.xlsx", content
    )


@router.get(
    "/workbooks/{workbook_id}",
    response_model=WorkbookSummary,
    tags=["Workbooks"],
)
def get_workbook(request: Request, workbook_id: str) -> WorkbookSummary:
    return request.app.state.workbook_service.get_summary(workbook_id)


@router.get(
    "/workbooks/{workbook_id}/validation",
    response_model=ValidationReport,
    tags=["Workbooks"],
)
def get_workbook_validation(
    request: Request, workbook_id: str
) -> ValidationReport:
    return request.app.state.workbook_service.get_validation(workbook_id)
