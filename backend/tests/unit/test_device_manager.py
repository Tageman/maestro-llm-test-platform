from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from maestro_app.core.config import Settings
from maestro_app.domain.models import ProjectConfig
from maestro_app.infrastructure.device_manager import (
    AndroidDeviceManager,
    DevicePreparationError,
)
from maestro_app.infrastructure.tool_probe import ProcessResult


class FakeRunner:
    def __init__(self, devices: str) -> None:
        self.devices = devices

    def run(self, args: Sequence[str], timeout_seconds: float) -> ProcessResult:
        joined = " ".join(args)
        if joined.endswith("--version") or joined.endswith("version"):
            return ProcessResult(0, "ready")
        if joined.endswith("devices"):
            return ProcessResult(0, self.devices)
        if "getprop sys.boot_completed" in joined:
            return ProcessResult(0, "1")
        if "emu avd name" in joined:
            return ProcessResult(0, "Pixel_5\nOK")
        if "shell pm path" in joined:
            return ProcessResult(0, "package:/data/app/example.app/base.apk")
        if "dumpsys input_method" in joined:
            return ProcessResult(
                0,
                "currentEntry=hwn{languageTag=en-US, variant=qwerty}",
            )
        if "settings get secure autofill_service" in joined:
            return ProcessResult(0, "null")
        return ProcessResult(0, "")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        maestro_command="maestro",
        adb_command="adb",
        emulator_command="emulator",
        app_id="example.app",
        runtime_dir=tmp_path,
        ir_schema_path=tmp_path / "schema.json",
        cors_origins=(),
    )


def _config(device_id: str | None = None) -> ProjectConfig:
    return ProjectConfig(
        project_name="device-test",
        app_id="example.app",
        android_device_id=device_id,
        avd_name="Pixel_5",
        maestro_command="maestro",
        execution_target="android_emulator",
        output_dir=Path("./outputs"),
        test_timeout_ms=1000,
        max_syntax_repair=0,
        max_locator_repair=0,
        max_total_run_attempts=1,
        continue_on_failure=True,
        launch_clear_state=False,
        pytest_workers=1,
        result_writeback=False,
        language="zh-CN",
        fixture_id_separator=";",
    )


def test_unique_emulator_is_prepared(tmp_path: Path) -> None:
    manager = AndroidDeviceManager(
        _settings(tmp_path), FakeRunner("emulator-5554\tdevice\n")
    )

    result = manager.prepare(_config())

    assert result.device_id == "emulator-5554"
    assert result.avd_name == "Pixel_5"
    assert result.app_installed
    input_method = next(
        check for check in result.checks if check["name"] == "input_method"
    )
    assert input_method["active_locale"] == "en-US"
    autofill = next(
        check for check in result.checks if check["name"] == "autofill_service"
    )
    assert autofill["enabled"] is False


def test_multiple_emulators_block_without_explicit_selection(tmp_path: Path) -> None:
    manager = AndroidDeviceManager(
        _settings(tmp_path),
        FakeRunner("emulator-5554\tdevice\nemulator-5556\tdevice\n"),
    )

    with pytest.raises(DevicePreparationError) as caught:
        manager.prepare(_config())

    assert caught.value.code == "MULTIPLE_EMULATORS"


def test_physical_device_configuration_is_rejected(tmp_path: Path) -> None:
    manager = AndroidDeviceManager(
        _settings(tmp_path), FakeRunner("R58M123\tdevice\n")
    )

    with pytest.raises(DevicePreparationError) as caught:
        manager.prepare(_config("R58M123"))

    assert caught.value.code == "PHYSICAL_DEVICE_UNSUPPORTED"
