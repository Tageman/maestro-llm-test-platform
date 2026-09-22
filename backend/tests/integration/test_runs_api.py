from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from maestro_app.application.errors import ResourceNotFound
from maestro_app.core.config import Settings
from maestro_app.domain.enums import CaseRunState, RunMode, RunState
from maestro_app.domain.models import (
    Artifact,
    CaseRun,
    CreateRunRequest,
    RunEvent,
    RunSummary,
)
from maestro_app.main import create_app


class FakeRunService:
    def __init__(self, tmp_path: Path) -> None:
        now = datetime.now(UTC)
        self.summary = RunSummary(
            run_id="run-api-001",
            generation_id="generation-ready-001",
            workbook_id="workbook-001",
            state=RunState.COMPLETED,
            mode=RunMode.REVIEW,
            created_at=now,
            updated_at=now,
            started_at=now,
            ended_at=now,
            device_id="emulator-5554",
            avd_name="Pixel_5",
            app_id="example.app",
            pytest_node_ids=["generated/pytest/test_generated.py::test_case_001"],
            case_counts={CaseRunState.PASSED.value: 1},
            events_cursor=2,
            terminal_reason="全部 Case 通过",
        )
        self.case = CaseRun(
            case_id="CASE-001",
            state=CaseRunState.PASSED,
            fixture_plan=["FX-RESET"],
            business_result="passed",
            cleanup_result="passed",
            started_at=now,
            ended_at=now,
            duration_seconds=1.0,
        )
        self.run_events = [
            RunEvent(
                event_id="run-api-001-1",
                run_id="run-api-001",
                sequence=1,
                type="run.created",
                entity_type="run",
                entity_id="run-api-001",
                state=RunState.CREATED.value,
                message="Run created",
            ),
            RunEvent(
                event_id="run-api-001-2",
                run_id="run-api-001",
                sequence=2,
                type="run.state_changed",
                entity_type="run",
                entity_id="run-api-001",
                state=RunState.COMPLETED.value,
                message="Run completed",
            ),
        ]
        self.created_request: CreateRunRequest | None = None
        self.artifact_path = tmp_path / "failure.log"
        self.artifact_path.write_text("failure evidence\n", encoding="utf-8")
        self.result_path = tmp_path / "result.xlsx"
        self.result_path.write_bytes(b"xlsx")
        self.artifact = Artifact(
            artifact_id="artifact-001",
            kind="log",
            relative_path="artifacts/failure.log",
            media_type="text/plain",
            sha256="0" * 64,
            case_id="CASE-001",
            attempt_id="CASE-001-a1",
        )

    def create(self, request: CreateRunRequest) -> RunSummary:
        self.created_request = request
        return self.summary

    def get(self, run_id: str) -> RunSummary:
        assert run_id == self.summary.run_id
        return self.summary

    def get_case(self, run_id: str, case_id: str) -> CaseRun:
        assert run_id == self.summary.run_id
        assert case_id == self.case.case_id
        return self.case

    def cancel(self, run_id: str) -> RunSummary:
        assert run_id == self.summary.run_id
        return self.summary

    def events(self, run_id: str, after: int = 0) -> list[RunEvent]:
        assert run_id == self.summary.run_id
        return [event for event in self.run_events if event.sequence > after]

    def get_artifact(self, run_id: str, artifact_id: str):
        assert run_id == self.summary.run_id
        if artifact_id != self.artifact.artifact_id:
            raise ResourceNotFound("artifact", artifact_id)
        return self.artifact, self.artifact_path

    def get_result_workbook(self, run_id: str) -> Path:
        assert run_id == self.summary.run_id
        return self.result_path


def _settings(tmp_path: Path) -> Settings:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    return Settings(
        maestro_command="maestro",
        adb_command="adb",
        emulator_command="emulator",
        app_id="example.app",
        runtime_dir=tmp_path / "runtime",
        ir_schema_path=schema,
        cors_origins=("http://127.0.0.1:5173",),
    )


def test_run_endpoints_and_sse_resume(tmp_path: Path) -> None:
    service = FakeRunService(tmp_path)
    client = TestClient(create_app(_settings(tmp_path), run_service=service))

    created = client.post(
        "/api/v1/runs",
        json={
            "generation_id": "generation-ready-001",
            "case_ids": ["CASE-001"],
        },
    )
    assert created.status_code == 202
    assert created.json()["state"] == RunState.COMPLETED.value
    assert service.created_request == CreateRunRequest(
        generation_id="generation-ready-001", case_ids=["CASE-001"]
    )

    detail = client.get("/api/v1/runs/run-api-001")
    assert detail.status_code == 200
    assert detail.json()["events_cursor"] == 2

    case = client.get("/api/v1/runs/run-api-001/cases/CASE-001")
    assert case.status_code == 200
    assert case.json()["state"] == CaseRunState.PASSED.value

    events = client.get("/api/v1/runs/run-api-001/events")
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert "id: run-api-001-1" in events.text
    assert "id: run-api-001-2" in events.text

    resumed = client.get(
        "/api/v1/runs/run-api-001/events",
        headers={"Last-Event-ID": "run-api-001-1"},
    )
    assert resumed.status_code == 200
    assert "id: run-api-001-1" not in resumed.text
    assert "id: run-api-001-2" in resumed.text

    cancelled = client.post("/api/v1/runs/run-api-001/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == RunState.COMPLETED.value

    artifact = client.get("/api/v1/runs/run-api-001/artifacts/artifact-001")
    assert artifact.status_code == 200
    assert artifact.text == "failure evidence\n"
    assert artifact.headers["x-artifact-sha256"] == "0" * 64

    workbook = client.get("/api/v1/runs/run-api-001/result-workbook")
    assert workbook.status_code == 200
    assert workbook.content == b"xlsx"

    unknown = client.get("/api/v1/runs/run-api-001/artifacts/unknown")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "RESOURCE_NOT_FOUND"

    traversal = client.get("/api/v1/runs/run-api-001/artifacts/..%2Funknown")
    assert traversal.status_code in {400, 404}
