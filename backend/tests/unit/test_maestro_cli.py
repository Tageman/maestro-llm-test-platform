from pathlib import Path

from maestro_app.core.config import Settings
from maestro_app.infrastructure.maestro_cli import MaestroCliRunner
from maestro_app.infrastructure.tool_probe import ProcessResult


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], float]] = []

    def run(self, args, timeout_seconds):
        self.calls.append((list(args), timeout_seconds))
        if "--output" in args:
            report_path = Path(args[args.index("--output") + 1])
            report_path.write_text("<testsuites/>", encoding="utf-8")
        return ProcessResult(0, stdout="OK")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        maestro_command="maestro",
        adb_command="adb",
        emulator_command="emulator",
        app_id="aippt.com.mm",
        runtime_dir=tmp_path / "runtime",
        ir_schema_path=tmp_path / "schema.json",
        cors_origins=("http://127.0.0.1:5173",),
    )


def test_check_syntax_uses_a_shell_free_argument_list(tmp_path: Path) -> None:
    recorder = RecordingRunner()
    flow = tmp_path / "flow.yaml"

    result = MaestroCliRunner(_settings(tmp_path), recorder).check_syntax(flow)

    assert result.succeeded
    assert recorder.calls[0][0] == ["maestro", "check-syntax", str(flow)]


def test_run_flow_creates_paths_and_passes_device_and_report(tmp_path: Path) -> None:
    recorder = RecordingRunner()
    report = tmp_path / "report" / "junit.xml"
    artifacts = tmp_path / "artifacts"

    result = MaestroCliRunner(_settings(tmp_path), recorder).run_flow(
        tmp_path / "flow.yaml",
        device_id="emulator-5554",
        report_path=report,
        artifact_dir=artifacts,
        reinstall_driver=True,
    )

    assert result.passed
    args = recorder.calls[0][0]
    assert args[:4] == ["maestro", "--udid", "emulator-5554", "test"]
    assert "--reinstall-driver" in args
    assert report.is_file()
    assert artifacts.is_dir()
