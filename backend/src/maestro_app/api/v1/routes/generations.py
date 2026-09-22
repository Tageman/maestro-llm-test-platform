from __future__ import annotations

from fastapi import APIRouter, Request, status

from maestro_app.domain.models import (
    ApprovalRequest,
    CreateGenerationRequest,
    GeneratedFlowDetail,
    GenerationSummary,
)


router = APIRouter()


@router.post(
    "/generations",
    response_model=GenerationSummary,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Generations"],
)
def create_generation(
    request: Request, payload: CreateGenerationRequest
) -> GenerationSummary:
    return request.app.state.generation_service.create(payload)


@router.get(
    "/generations/{generation_id}",
    response_model=GenerationSummary,
    tags=["Generations"],
)
def get_generation(request: Request, generation_id: str) -> GenerationSummary:
    return request.app.state.generation_service.get(generation_id)


@router.get(
    "/generations/{generation_id}/flows/{flow_id}",
    response_model=GeneratedFlowDetail,
    tags=["Generations"],
)
def get_generated_flow(
    request: Request, generation_id: str, flow_id: str
) -> GeneratedFlowDetail:
    return request.app.state.generation_service.get_flow(generation_id, flow_id)


@router.post(
    "/generations/{generation_id}/approval",
    response_model=GenerationSummary,
    tags=["Generations"],
)
def approve_generation(
    request: Request,
    generation_id: str,
    payload: ApprovalRequest,
) -> GenerationSummary:
    return request.app.state.generation_service.approve(generation_id, payload)
