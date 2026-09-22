from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from maestro_app.domain.models import CapabilityReport, HealthResponse


router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["System"])
def get_health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        service=settings.service_name,
        version=settings.service_version,
        api_version=settings.api_version,
    )


@router.get(
    "/system/capabilities",
    response_model=CapabilityReport,
    tags=["System"],
)
def get_system_capabilities(request: Request) -> CapabilityReport:
    return request.app.state.capability_service.inspect()


@router.get("/schema/flow-ir", tags=["System"])
def get_flow_ir_schema(request: Request) -> JSONResponse:
    schema_path = request.app.state.settings.ir_schema_path
    with schema_path.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    return JSONResponse(content=schema, media_type="application/schema+json")
