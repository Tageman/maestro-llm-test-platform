from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _terminate(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    for process in processes:
        remaining = max(0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)


def main() -> int:
    commands = [
        (
            [
                sys.executable,
                "-m",
                "uvicorn",
                "maestro_app.main:app",
                "--app-dir",
                "backend/src",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            PROJECT_ROOT,
        ),
        (["npm", "run", "dev"], PROJECT_ROOT / "frontend"),
    ]
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for command, cwd in commands:
            processes.append(
                subprocess.Popen(command, cwd=cwd, start_new_session=True)
            )
        while all(process.poll() is None for process in processes):
            time.sleep(0.25)
        return next(
            (process.returncode or 0 for process in processes if process.poll() is not None),
            0,
        )
    except KeyboardInterrupt:
        return 130
    finally:
        _terminate(processes)


if __name__ == "__main__":
    raise SystemExit(main())
