from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

from maestro_app.application.ports import PytestPackage
from maestro_app.core.config import Settings
from maestro_app.infrastructure.pytest_process import ManagedPytestRunner


def _settings(tmp_path: Path, limit: int = 500) -> Settings:
    return Settings(
        maestro_command="maestro",
        adb_command="adb",
        emulator_command="emulator",
        app_id="example.app",
        runtime_dir=tmp_path,
        ir_schema_path=tmp_path / "schema.json",
        cors_origins=(),
        process_output_limit_chars=limit,
    )


def _package(tmp_path: Path, body: str, test_name: str) -> PytestPackage:
    root = tmp_path / "runs" / "run-process"
    test_file = root / "generated" / "pytest" / "test_generated.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(body, encoding="utf-8")
    config = test_file.parent / "runtime.json"
    config.write_text(json.dumps({"configured": False}), encoding="utf-8")
    return PytestPackage(
        test_file=test_file,
        config_path=config,
        collection_path=root / "reports" / "collection.txt",
        junit_path=root / "reports" / "junit.xml",
        trace_path=root / "reports" / "trace.jsonl",
        stdout_path=root / "artifacts" / "logs" / "pytest.log",
        node_ids=(f"generated/pytest/test_generated.py::{test_name}",),
    )


def test_output_is_complete_on_disk_and_capped_in_memory(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        "def test_loud():\n    print('x' * 10000)\n    assert False\n",
        "test_loud",
    )
    runner = ManagedPytestRunner(_settings(tmp_path, limit=300))

    result = runner.run(
        "run-process",
        package,
        timeout_seconds=10,
        cancel_event=threading.Event(),
    )

    assert result.returncode == 1
    assert result.output_truncated
    assert len(result.stdout_tail) <= 300
    assert package.stdout_path.stat().st_size > len(result.stdout_tail)


def test_timeout_terminates_process_group(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        "import time\ndef test_slow():\n    time.sleep(30)\n",
        "test_slow",
    )
    runner = ManagedPytestRunner(_settings(tmp_path))

    result = runner.run(
        "run-process",
        package,
        timeout_seconds=0.5,
        cancel_event=threading.Event(),
    )

    assert result.timed_out
    assert not result.succeeded


def test_cancel_terminates_process_group(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        "import time\ndef test_slow():\n    time.sleep(30)\n",
        "test_slow",
    )
    runner = ManagedPytestRunner(_settings(tmp_path))
    cancel = threading.Event()

    def request_cancel() -> None:
        time.sleep(0.5)
        cancel.set()

    threading.Thread(target=request_cancel, daemon=True).start()
    result = runner.run(
        "run-process",
        package,
        timeout_seconds=10,
        cancel_event=cancel,
    )

    assert result.cancelled
    assert not result.succeeded


def test_callback_exception_still_terminates_process_group(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        "import time\ndef test_slow():\n    time.sleep(30)\n",
        "test_slow",
    )
    runner = ManagedPytestRunner(_settings(tmp_path))

    def interrupt() -> None:
        raise RuntimeError("simulated parent interruption")

    try:
        runner.run(
            "run-process",
            package,
            timeout_seconds=10,
            cancel_event=threading.Event(),
            on_tick=interrupt,
        )
    except RuntimeError as exc:
        assert str(exc) == "simulated parent interruption"
    else:
        raise AssertionError("expected the callback exception")

    assert runner._active == {}
    completed = subprocess.run(
        ["pgrep", "-f", str(package.test_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
