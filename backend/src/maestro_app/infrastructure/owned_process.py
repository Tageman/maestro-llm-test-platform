from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from maestro_app.infrastructure.execution_guard import CURRENT_LEASE_FD


def popen_owned(args, **kwargs):
    """Popen-compatible stdio; guardian observes parent death without polling PID."""
    reader, writer = os.pipe()
    lease_fd = CURRENT_LEASE_FD.get()
    inherited = (reader,) if lease_fd is None else (reader, lease_fd)
    kwargs.pop("start_new_session", None)
    try:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("process_guardian.py")), str(reader), *args],
            pass_fds=inherited, start_new_session=True, **kwargs,
        )
    except BaseException:
        os.close(writer)
        raise
    finally:
        os.close(reader)
    process._maestro_owner_pipe = writer
    return process


def finish_owned(process) -> None:
    """Request cleanup, wait for guardian, then release this parent's pipe."""
    writer = getattr(process, "_maestro_owner_pipe", None)
    if writer is not None:
        os.close(writer)
        process._maestro_owner_pipe = None
    if process.poll() is None:
        process.terminate()
    # A guardian must finish group cleanup before the Run lease is released.
    # Never kill the guardian itself to make a timeout look successful.
    process.wait(timeout=10)


def run_owned(args, *, timeout: float):
    process = popen_owned(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    finally:
        finish_owned(process)
