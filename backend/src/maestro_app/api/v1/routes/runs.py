from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Header, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse

from maestro_app.domain.models import (
    CaseRunDetail,
    CreateRunRequest,
    RunSummary,
)
from maestro_app.domain.state_machine import TERMINAL_STATES


router = APIRouter()


@router.post(
    "/runs",
    response_model=RunSummary,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Runs"],
)
def create_run(request: Request, payload: CreateRunRequest) -> RunSummary:
    return request.app.state.run_service.create(payload)


@router.get("/runs/{run_id}", response_model=RunSummary, tags=["Runs"])
def get_run(request: Request, run_id: str) -> RunSummary:
    return request.app.state.run_service.get(run_id)


@router.get(
    "/runs/{run_id}/cases/{case_id}", response_model=CaseRunDetail, tags=["Runs"]
)
def get_case_run(request: Request, run_id: str, case_id: str) -> CaseRunDetail:
    return request.app.state.run_service.get_case(run_id, case_id)


@router.post(
    "/runs/{run_id}/cancel", response_model=RunSummary, tags=["Runs"]
)
def cancel_run(request: Request, run_id: str) -> RunSummary:
    return request.app.state.run_service.cancel(run_id)


@router.get("/runs/{run_id}/artifacts/{artifact_id}", tags=["Runs"])
def download_artifact(request: Request, run_id: str, artifact_id: str) -> FileResponse:
    artifact, path = request.app.state.run_service.get_artifact(run_id, artifact_id)
    return FileResponse(
        path,
        media_type=artifact.media_type,
        filename=path.name,
        headers={"X-Artifact-SHA256": artifact.sha256},
    )


@router.get("/runs/{run_id}/result-workbook", tags=["Runs"])
def download_result_workbook(request: Request, run_id: str) -> FileResponse:
    path = request.app.state.run_service.get_result_workbook(run_id)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )


@router.get("/runs/{run_id}/events", tags=["Runs"])
def stream_run_events(
    request: Request,
    run_id: str,
    after: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    if last_event_id:
        try:
            after = max(after, int(last_event_id.rsplit("-", 1)[-1]))
        except ValueError:
            pass
    # Validate the identifier before the streaming response starts.
    request.app.state.run_service.get(run_id)

    async def event_stream():
        cursor = after
        while True:
            events = request.app.state.run_service.events(run_id, cursor)
            for event in events:
                cursor = event.sequence
                payload = event.model_dump(mode="json")
                yield (
                    f"id: {event.event_id}\n"
                    f"event: {event.type}\n"
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                )
            current = request.app.state.run_service.get(run_id)
            if (current.state in TERMINAL_STATES and current.export_status != "pending"
                    and cursor >= current.events_cursor):
                break
            if await request.is_disconnected():
                break
            if not events:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
