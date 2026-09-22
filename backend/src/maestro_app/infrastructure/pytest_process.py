from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from maestro_app.application.ports import ManagedProcessResult, PytestPackage
from maestro_app.core.config import Settings


class ManagedPytestRunner:
    def __init__(self, settings: Settings, python_command: str | None = None) -> None:
        self.settings = settings
        self.python_command = python_command or sys.executable
        self._active: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    def collect(self, package: PytestPackage) -> ManagedProcessResult:
        args = [
            self.python_command,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            str(package.test_file),
        ]
        return self._execute(
            args,
            output_path=package.collection_path,
            cwd=package.test_file.parents[2],
            timeout_seconds=60,
            env=self._environment(package),
        )

    def run(
        self,
        run_id: str,
        package: PytestPackage,
        *,
        timeout_seconds: float,
        cancel_event: threading.Event,
        on_tick: Callable[[], None] | None = None,
    ) -> ManagedProcessResult:
        args = [
            self.python_command,
            "-m",
            "pytest",
            "-q",
            f"--junitxml={package.junit_path}",
            *package.node_ids,
        ]
        env = self._environment(package)
        return self._execute(
            args,
            output_path=package.stdout_path,
            cwd=package.test_file.parents[2],
            timeout_seconds=timeout_seconds,
            env=env,
            run_id=run_id,
            cancel_event=cancel_event,
            on_tick=on_tick,
        )

    def cancel(self, run_id: str) -> None:
        with self._lock:
            process = self._active.get(run_id)
        if process is not None and process.poll() is None:
            self._terminate_group(process)

    def _execute(
        self,
        args: Sequence[str],
        *,
        output_path: Path,
        cwd: Path,
        timeout_seconds: float,
        env: dict[str, str] | None = None,
        run_id: str | None = None,
        cancel_event: threading.Event | None = None,
        on_tick: Callable[[], None] | None = None,
    ) -> ManagedProcessResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        timed_out = False
        cancelled = False
        with output_path.open("wb") as output:
            process = subprocess.Popen(
                list(args),
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                shell=False,
            )
            if run_id:
                with self._lock:
                    self._active[run_id] = process
            try:
                while process.poll() is None:
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        self._terminate_group(process)
                        break
                    if time.monotonic() - started >= timeout_seconds:
                        timed_out = True
                        self._terminate_group(process)
                        break
                    if on_tick is not None:
                        on_tick()
                    time.sleep(0.1)
                returncode = process.wait(timeout=10)
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
            finally:
                if process.poll() is None:
                    self._terminate_group(process)
                if run_id:
                    with self._lock:
                        self._active.pop(run_id, None)
                if on_tick is not None:
                    on_tick()
        tail, truncated = self._read_tail(output_path)
        return ManagedProcessResult(
            returncode=returncode,
            stdout_tail=tail,
            output_path=output_path,
            timed_out=timed_out,
            cancelled=cancelled,
            output_truncated=truncated,
        )

    def _environment(self, package: PytestPackage) -> dict[str, str]:
        allowed = (
            "PATH",
            "LANG",
            "LC_ALL",
            "TMPDIR",
            "JAVA_HOME",
            "ANDROID_HOME",
            "ANDROID_SDK_ROOT",
            "MAESTRO_CLI_NO_ANALYTICS",
        )
        env = {key: os.environ[key] for key in allowed if key in os.environ}
        backend_src = Path(__file__).resolve().parents[2]
        env["PYTHONPATH"] = str(backend_src)
        env["MAESTRO_APP_PYTEST_CONFIG"] = str(package.config_path)
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _read_tail(self, path: Path) -> tuple[str, bool]:
        limit = self.settings.process_output_limit_chars
        size = path.stat().st_size
        with path.open("rb") as source:
            source.seek(max(0, size - limit))
            value = source.read().decode("utf-8", errors="replace")
        return value, size > limit

    @staticmethod
    def _terminate_group(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        except ProcessLookupError:
            return
