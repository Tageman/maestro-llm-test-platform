from __future__ import annotations

import fcntl
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from maestro_app.application.errors import StateConflict


CURRENT_LEASE_FD: ContextVar[int | None] = ContextVar("run_execution_lease", default=None)


class ExecutionLease:
    def __init__(self, fd: int) -> None:
        self.fd: int | None = fd
        self._close_lock = threading.Lock()

    @contextmanager
    def activate(self):
        token = CURRENT_LEASE_FD.set(self.fd)
        try:
            yield
        finally:
            CURRENT_LEASE_FD.reset(token)

    def close(self) -> None:
        with self._close_lock:
            if self.fd is not None:
                # Do not LOCK_UN: guardians inherit this open-file description and
                # must retain the lock until their owned process groups are gone.
                os.close(self.fd)
                self.fd = None


class RuntimeExecutionGuard:
    """One OS-level execution lease per runtime, shared by Web and CLI."""

    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir.resolve()

    def acquire(self) -> ExecutionLease:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        path = self.runtime_dir / ".execution.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise StateConflict("RUNTIME_BUSY", "其他服务或残留进程守护仍持有运行锁，请等待清理完成") from exc
        except BaseException:
            os.close(fd)
            raise
        return ExecutionLease(fd)
