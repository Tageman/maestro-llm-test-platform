from __future__ import annotations

import os
import json
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from maestro_app.application.ports import ManagedProcessResult, PytestPackage
from maestro_app.core.config import Settings
from maestro_app.infrastructure.owned_process import finish_owned, popen_owned
from maestro_app.infrastructure.shared_process import SharedPytestProcess


class ManagedPytestRunner:
    def __init__(self, settings: Settings, python_command: str | None = None) -> None:
        self.settings = settings
        self.python_command = python_command or sys.executable
        self._active: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()
        self._shared: dict[str, SharedPytestProcess] = {}

    def collect(self, package: PytestPackage) -> ManagedProcessResult:
        args = [
            self.python_command,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            str(package.test_file),
        ]
        if json.loads(package.config_path.read_text()).get("shared_scopes"):
            args[-1:] = list(package.node_ids)
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
        if json.loads(package.config_path.read_text()).get("shared_scopes"):
            worker = self._shared.get(run_id)
            if worker is None:
                worker = SharedPytestProcess(self, run_id, package)
                self._shared[run_id] = worker
            return worker.request(package, command="run", timeout_seconds=timeout_seconds, cancel_event=cancel_event, on_tick=on_tick)
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
        worker = self._shared.get(run_id)
        if worker:
            worker.abort()
        with self._lock:
            process = self._active.get(run_id)
        if process is not None and process.poll() is None:
            self._terminate_group(process)

    def close_run(self, run_id: str):
        worker = self._shared.pop(run_id, None)
        return worker.close() if worker else None

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
            process = popen_owned(
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
                finish_owned(process)
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
        # Generated runs require only built-in pytest and our explicit bridge.
        # Host-installed plugins must not mutate outcomes or fixture lifetimes.
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
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
        if hasattr(process, "_maestro_owner_pipe"):
            # TERM the guardian, which owns and drains the target's group.
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
            return
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
