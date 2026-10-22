from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from maestro_app import __version__
from maestro_app.api.v1.router import api_router
from maestro_app.application.errors import ApplicationError
from maestro_app.application.flow_translator import build_flow_translator
from maestro_app.application.generation_service import GenerationService
from maestro_app.application.pytest_generator import GeneratedPytestPackageBuilder
from maestro_app.application.run_service import RunService
from maestro_app.application.syntax_checker import MaestroSyntaxChecker
from maestro_app.application.workbook_service import WorkbookService
from maestro_app.application.yaml_compiler import FlowYamlCompiler
from maestro_app.core.config import Settings, get_settings
from maestro_app.infrastructure.excel_importer import ExcelWorkbookImporter
from maestro_app.infrastructure.execution_guard import RuntimeExecutionGuard
from maestro_app.infrastructure.device_manager import AndroidDeviceManager
from maestro_app.infrastructure.generation_repository import GenerationRepository
from maestro_app.infrastructure.pytest_process import ManagedPytestRunner
from maestro_app.infrastructure.mcp_diagnostics import MaestroMcpDiagnosticService
from maestro_app.infrastructure.result_workbook import ResultWorkbookWriter
from maestro_app.infrastructure.run_repository import RunRepository
from maestro_app.infrastructure.run_exporter import RunExporter
from maestro_app.infrastructure.tool_probe import SystemCapabilityService
from maestro_app.infrastructure.workbook_repository import WorkbookRepository


def create_app(
    settings: Settings | None = None,
    capability_service: SystemCapabilityService | None = None,
    workbook_service: WorkbookService | None = None,
    generation_service: GenerationService | None = None,
    run_service: RunService | None = None,
) -> FastAPI:
    active_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application):
        application.state.run_service.recover_after_restart()
        yield

    app = FastAPI(
        title="Maestro LLM Test Platform API",
        version=__version__,
        description="Local Android automation orchestration API.",
        lifespan=lifespan,
    )
    app.state.settings = active_settings
    app.state.capability_service = capability_service or SystemCapabilityService(
        active_settings
    )
    workbook_repository = WorkbookRepository(active_settings.runtime_dir)
    app.state.workbook_service = workbook_service or WorkbookService(
        workbook_repository,
        ExcelWorkbookImporter(),
    )
    generation_repository = GenerationRepository(active_settings.runtime_dir)
    app.state.generation_service = generation_service or GenerationService(
        workbook_repository,
        generation_repository,
        build_flow_translator(active_settings),
        FlowYamlCompiler(),
    )
    run_repository = RunRepository(active_settings.runtime_dir)
    app.state.run_service = run_service or RunService(
        workbook_repository,
        generation_repository,
        run_repository,
        GeneratedPytestPackageBuilder(
            run_repository, active_settings.maestro_startup_grace_seconds
        ),
        AndroidDeviceManager(active_settings),
        ManagedPytestRunner(active_settings),
        diagnostic_service=MaestroMcpDiagnosticService(
            timeout_seconds=active_settings.mcp_timeout_seconds
        ),
        syntax_checker=MaestroSyntaxChecker(),
        result_writer=ResultWorkbookWriter(),
        exporter=RunExporter(Path(__file__).resolve().parents[3]),
        execution_guard=RuntimeExecutionGuard(active_settings.runtime_dir),
        maestro_startup_grace_seconds=active_settings.maestro_startup_grace_seconds,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(active_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(ApplicationError)
    async def handle_application_error(
        request: Request, exc: ApplicationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "request_id": getattr(request.state, "request_id", "unknown"),
                "details": exc.details,
                "retryable": exc.retryable,
            },
        )

    app.include_router(api_router)
    return app


app = create_app()
