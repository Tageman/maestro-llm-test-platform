from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from maestro_app.application.flow_translator import RuleBasedFlowTranslator
from maestro_app.application.generation_service import GenerationService
from maestro_app.application.syntax_checker import SyntaxCheckResult
from maestro_app.application.workbook_service import WorkbookService
from maestro_app.core.config import Settings
from maestro_app.infrastructure.excel_importer import ExcelWorkbookImporter
from maestro_app.infrastructure.generation_repository import GenerationRepository
from maestro_app.infrastructure.workbook_repository import WorkbookRepository
from maestro_app.main import create_app
from m1_helpers import build_sample_workbook


class PassingSyntaxChecker:
    def check(self, flow_path, *, maestro_command, timeout_seconds):
        assert Path(flow_path).is_file()
        return SyntaxCheckResult(valid=True, output="OK", exit_code=0)


def _settings(tmp_path: Path) -> Settings:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    return Settings(
        maestro_command="maestro",
        adb_command="adb",
        emulator_command="emulator",
        app_id="aippt.com.mm",
        runtime_dir=tmp_path / "runtime",
        ir_schema_path=schema,
        cors_origins=("http://127.0.0.1:5173",),
    )


def test_import_generate_preview_and_approve(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workbook_repository = WorkbookRepository(settings.runtime_dir)
    workbook_service = WorkbookService(
        workbook_repository, ExcelWorkbookImporter()
    )
    generation_service = GenerationService(
        workbook_repository,
        GenerationRepository(settings.runtime_dir),
        RuleBasedFlowTranslator(),
        syntax_checker=PassingSyntaxChecker(),
    )
    app = create_app(
        settings,
        workbook_service=workbook_service,
        generation_service=generation_service,
    )
    client = TestClient(app)
    source = build_sample_workbook(tmp_path / "baseline.xlsx")

    with source.open("rb") as source_file:
        imported = client.post(
            "/api/v1/workbooks",
            files={
                "file": (
                    source.name,
                    source_file,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert imported.status_code == 202
    workbook = imported.json()
    assert workbook["status"] == "valid"
    assert workbook["counts"]["enabled_cases"] == 1
    assert workbook["counts"]["enabled_fixtures"] == 2

    validation = client.get(
        f"/api/v1/workbooks/{workbook['workbook_id']}/validation"
    )
    assert validation.json() == {
        "workbook_id": workbook["workbook_id"],
        "valid": True,
        "issues": [],
    }

    generated = client.post(
        "/api/v1/generations",
        json={"workbook_id": workbook["workbook_id"], "mode": "review"},
    )
    assert generated.status_code == 202
    generation = generated.json()
    assert generation["status"] == "awaiting_review"
    assert [flow["flow_id"] for flow in generation["flows"]] == [
        "FX-APP-RESET",
        "FX-LOGIN-READY",
        "TC-HOME-001",
    ]

    detail = client.get(
        f"/api/v1/generations/{generation['generation_id']}/flows/TC-HOME-001"
    ).json()
    assert detail["syntax_valid"] is True
    assert detail["mappings"][-1]["assertion"] is True
    assert "assertVisible" in detail["yaml"]

    approved = client.post(
        f"/api/v1/generations/{generation['generation_id']}/approval",
        json={"flow_ids": [flow["flow_id"] for flow in generation["flows"]]},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "ready"
    assert approved.json()["approved_flow_count"] == 3

    unattended = client.post(
        "/api/v1/generations",
        json={"workbook_id": workbook["workbook_id"], "mode": "unattended"},
    )
    assert unattended.status_code == 202
    assert unattended.json()["status"] == "ready"
    assert unattended.json()["approved_flow_count"] == 3


def test_invalid_workbook_is_visible_but_generation_is_blocked(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workbook_repository = WorkbookRepository(settings.runtime_dir)
    workbook_service = WorkbookService(
        workbook_repository, ExcelWorkbookImporter()
    )
    generation_service = GenerationService(
        workbook_repository,
        GenerationRepository(settings.runtime_dir),
        RuleBasedFlowTranslator(),
        syntax_checker=PassingSyntaxChecker(),
    )
    client = TestClient(
        create_app(
            settings,
            workbook_service=workbook_service,
            generation_service=generation_service,
        )
    )
    source = build_sample_workbook(tmp_path / "invalid.xlsx")
    workbook = load_workbook(source)
    workbook["Fixtures"]["F6"] = "FX-LOGIN-READY"
    workbook.save(source)

    with source.open("rb") as source_file:
        imported = client.post(
            "/api/v1/workbooks",
            files={"file": (source.name, source_file)},
        )

    assert imported.status_code == 202
    workbook_summary = imported.json()
    assert workbook_summary["status"] == "invalid"
    assert workbook_summary["counts"]["errors"] > 0

    generated = client.post(
        "/api/v1/generations",
        json={
            "workbook_id": workbook_summary["workbook_id"],
            "mode": "review",
        },
    )
    assert generated.status_code == 409
    assert generated.json()["code"] == "WORKBOOK_VALIDATION_FAILED"
