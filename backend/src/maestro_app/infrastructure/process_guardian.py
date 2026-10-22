"""Standalone POSIX guardian. No app imports: also works with sanitized envs.

Owns only the process group it creates. Parent-pipe EOF or TERM triggers group
cleanup; the inherited execution lease is retained through cleanup. It never
uses persisted PIDs or process-name matching to kill unrelated processes.
"""
from __future__ import annotations

import os
import select
import signal
import subprocess
import sys
import time


def group_has_live_members(pgid: int) -> bool:
    """Resolve EPERM without treating an inaccessible live group as gone.

    On macOS a group being reaped can transiently reject signal 0. Inspect
    only PID-group/state metadata; zombies cannot execute further operations.
    Any live member or failed inspection stays an error, never a false drain.
    """
    result = subprocess.run(["/bin/ps", "-axo", "pgid=,stat="], capture_output=True, text=True, timeout=3, check=True)
    for line in result.stdout.splitlines():
        group, status = line.split()
        if int(group) == pgid and not status.startswith("Z"):
            return True
    return False


def main() -> int:
    watch_fd = int(sys.argv[1])
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # Avoid spawning a target after its owner has already disappeared.
    if select.select([watch_fd], [], [], 0)[0] and not os.read(watch_fd, 1):
        return 125
    try:
        child = subprocess.Popen(sys.argv[2:], start_new_session=True, close_fds=True)
    except OSError as exc:
        print(f"Unable to start owned process: {exc}", file=sys.stderr)
        return 127 if isinstance(exc, FileNotFoundError) else 126
    try:
        while child.poll() is None and not stopping:
            if select.select([watch_fd], [], [], 0.05)[0]:
                if not os.read(watch_fd, 1):
                    stopping = True
        result = child.poll()
    finally:
        # Also remove descendants when the group leader exited first.
        try:
            os.killpg(child.pid, signal.SIGTERM)
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                child.poll()  # reap the direct child when possible
                try:
                    os.killpg(child.pid, 0)
                except ProcessLookupError:
                    break
                except PermissionError:
                    if group_has_live_members(child.pid):
                        raise
                    break
                time.sleep(0.05)
            else:
                os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            if group_has_live_members(child.pid):
                raise
        child.wait()
    return 125 if stopping else (result if result is not None and result >= 0 else 1)


if __name__ == "__main__":
    raise SystemExit(main())
