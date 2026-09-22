import json
from pathlib import Path

from fastapi.testclient import TestClient

from maestro_app.core.config import Settings
from maestro_app.domain.enums import OverallStatus, ToolStatus
from maestro_app.domain.models import (
    AndroidDevice,
    AppCapability,
    CapabilityReport,
    ToolCapability,
)
from maestro_app.main import create_app


class StubCapabilityService:
    def inspect(self) -> CapabilityReport:
        from datetime import UTC, datetime

        return CapabilityReport(
            overall_status=OverallStatus.READY,
            checked_at=datetime.now(UTC),
            tools=[
                ToolCapability(
                    name="maestro",
                    status=ToolStatus.AVAILABLE,
                    available=True,
                    version="2.10.0",
                    command="maestro",
                    detail="ready",
                )
            ],
            android_devices=[
                AndroidDevice(
                    device_id="emulator-5554", state="device", selected=True
                )
            ],
            avds=["Pixel_5"],
            app=AppCapability(
                app_id="aippt.com.mm",
                installed=True,
                device_id="emulator-5554",
            ),
        )


def _settings(tmp_path: Path) -> Settings:
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps({"title": "Flow IR"}), encoding="utf-8")
    return Settings(
        maestro_command="maestro",
        adb_command="adb",
        emulator_command="emulator",
        app_id="aippt.com.mm",
        avd_name="Pixel_5",
        runtime_dir=tmp_path / "runtime",
        ir_schema_path=schema_path,
        cors_origins=("http://127.0.0.1:5173",),
    )


def test_health_capability_and_schema_endpoints(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path), StubCapabilityService())
    client = TestClient(app)

    health = client.get("/api/v1/health")
    capabilities = client.get("/api/v1/system/capabilities")
    schema = client.get("/api/v1/schema/flow-ir")

    assert health.status_code == 200
    assert health.json()["api_version"] == "v1"
    assert health.headers["X-Request-ID"]
    assert capabilities.json()["overall_status"] == "ready"
    assert schema.headers["content-type"].startswith("application/schema+json")
    assert schema.json()["title"] == "Flow IR"
