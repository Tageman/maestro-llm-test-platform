from pathlib import Path

from maestro_app.core.config import Settings
from maestro_app.domain.enums import OverallStatus
from maestro_app.infrastructure.tool_probe import ProcessResult, SystemCapabilityService


class FakeRunner:
    def run(self, args, timeout_seconds):
        command = tuple(args)
        responses = {
            ("maestro", "--version"): ProcessResult(0, "2.10.0"),
            ("maestro", "--help"): ProcessResult(0, "Commands:\n  test\n  mcp"),
            ("adb", "version"): ProcessResult(
                0, "Android Debug Bridge version 1.0.41"
            ),
            ("adb", "devices"): ProcessResult(
                0, "List of devices attached\nemulator-5554\tdevice\n"
            ),
            ("emulator", "-list-avds"): ProcessResult(0, "Pixel_5\n"),
            (
                "adb",
                "-s",
                "emulator-5554",
                "shell",
                "pm",
                "list",
                "packages",
                "aippt.com.mm",
            ): ProcessResult(0, "package:aippt.com.mm\n"),
        }
        return responses.get(command, ProcessResult(1, stderr="unexpected command"))


def test_parse_adb_devices_ignores_headers_and_daemon_messages() -> None:
    output = """* daemon started successfully
List of devices attached
emulator-5554\tdevice
emulator-5556\toffline
"""

    devices = SystemCapabilityService.parse_adb_devices(output)

    assert [(device.device_id, device.state) for device in devices] == [
        ("emulator-5554", "device"),
        ("emulator-5556", "offline"),
    ]


def test_full_capability_report_is_ready(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")
    settings = Settings(
        maestro_command="maestro",
        adb_command="adb",
        emulator_command="emulator",
        app_id="aippt.com.mm",
        avd_name="Pixel_5",
        runtime_dir=tmp_path / "runtime",
        ir_schema_path=schema_path,
        cors_origins=("http://127.0.0.1:5173",),
    )

    report = SystemCapabilityService(settings, FakeRunner()).inspect()

    assert report.overall_status == OverallStatus.READY
    assert report.app.installed
    assert report.android_devices[0].selected
