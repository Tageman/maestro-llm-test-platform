"""Operator acknowledgement only; never discovers or kills processes by name."""
from __future__ import annotations

import argparse

from maestro_app.application.run_recovery import RunRecovery
from maestro_app.core.config import Settings
from maestro_app.infrastructure.execution_guard import RuntimeExecutionGuard
from maestro_app.infrastructure.run_repository import RunRepository


def main() -> int:
    parser = argparse.ArgumentParser(description="Acknowledge a legacy Run after manually checking its owned processes")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--confirm-no-owned-processes", action="store_true", required=True)
    args = parser.parse_args()
    runtime = Settings.from_environment().runtime_dir
    lease = RuntimeExecutionGuard(runtime).acquire()
    try:
        recovery = RunRecovery(RunRepository(runtime))
        recovery.recover()
        recovery.acknowledge_legacy_check(args.run_id)
    finally:
        lease.close()
    print(f"Acknowledged {args.run_id}; no execution was replayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
