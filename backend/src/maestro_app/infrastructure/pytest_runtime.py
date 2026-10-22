from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from maestro_app.infrastructure.maestro_report import report_error


class MaestroPytestContext:
    """Runtime used only by generated pytest modules."""

    current: "MaestroPytestContext | None" = None

    def __init__(self, config: dict[str, Any]) -> None:
        if not config.get("configured"):
            raise RuntimeError("pytest runtime has not been configured with a device")
        self.config = config
        self.run_dir = Path(config["run_dir"]).resolve()
        self.attempt_root = Path(config.get("attempt_root", config["run_dir"])).resolve()
        self.trace_path = Path(config["trace_path"]).resolve()
        self._current_case_id: str | None = None
        self._scope_users: dict[tuple[str, str], list[str]] = {}
        self._fixture_failures: set[tuple[str, str]] = set()
        self._bootstrapped = False
        self._fixture_scope: str | None = None
        type(self).current = self

    def refresh(self, config: dict[str, Any]) -> None:
        self.config = config
        self.attempt_root = Path(config.get("attempt_root", config["run_dir"])).resolve()
        self.trace_path = Path(config["trace_path"]).resolve()

    def _scope_key(self, flow_id: str, scope: str) -> tuple[str, str]:
        case = self._current_case_id or "suite"
        module = self.config.get("case_plans", {}).get(case, {}).get("module", case)
        return flow_id, ("session" if scope == "session" else module if scope == "module" else case)

    def execute_fixture(self, flow_id: str, *, phase: str, scope: str) -> None:
        self._fixture_scope = scope
        key = self._scope_key(flow_id, scope)
        try:
            self.execute(flow_id, entity_type="fixture", phase=phase)
        except BaseException:
            if phase == "setup":
                self._fixture_failures.add(key)
            raise
        finally:
            self._fixture_scope = None

    @classmethod
    def from_environment(cls) -> "MaestroPytestContext":
        config_path = os.environ.get("MAESTRO_APP_PYTEST_CONFIG")
        if not config_path:
            raise RuntimeError("MAESTRO_APP_PYTEST_CONFIG is not set")
        with Path(config_path).open(encoding="utf-8") as source:
            return cls(json.load(source))

    def case_started(self, case_id: str) -> None:
        self._current_case_id = case_id
        for flow_id, plan in self.config.get("case_plans", {}).get(case_id, {}).get("fixtures", {}).items():
            key = self._scope_key(flow_id, plan["scope"])
            users = self._scope_users.setdefault(key, [])
            if case_id not in users:
                users.append(case_id)
            if key in self._fixture_failures:
                self._trace(event="dependency_failed", entity_type="fixture", entity_id=flow_id, phase="setup", case_id=case_id, succeeded=False, cached=True)
        self._trace(
            event="started",
            entity_type="case_lifecycle",
            entity_id=case_id,
            phase="lifecycle",
            case_id=case_id,
        )

    def case_finished(self, case_id: str) -> None:
        self._trace(
            event="finished",
            entity_type="case_lifecycle",
            entity_id=case_id,
            phase="lifecycle",
            case_id=case_id,
            succeeded=True,
        )

    def bootstrap(self, case_id: str) -> None:
        plan = self.config.get("startup_plans", {}).get(case_id)
        if plan is None:
            return  # Existing frozen packages retain their original behavior.
        self._trace(
            event="startup_policy", entity_type="system", entity_id=plan["flow_id"],
            phase="setup", case_id=case_id, plan=plan,
        )
        if plan["enabled"] and not (self.config.get("shared_scopes") and self._bootstrapped):
            self.execute(plan["flow_id"], entity_type="fixture", phase="setup", case_id=case_id)
            self._bootstrapped = True

    def execute(
        self,
        flow_id: str,
        *,
        entity_type: str,
        phase: str,
        case_id: str | None = None,
    ) -> None:
        effective_case = case_id or self._current_case_id or "suite"
        flow_path = self.run_dir / self.config["flow_paths"][flow_id]
        safe_case = self._safe_segment(effective_case)
        safe_flow = self._safe_segment(flow_id)
        report_path = (
            self.attempt_root
            / "reports"
            / "maestro"
            / safe_case
            / phase
            / f"{safe_flow}.xml"
        )
        artifact_dir = (
            self.attempt_root
            / "artifacts"
            / "maestro"
            / safe_case
            / phase
            / safe_flow
        )
        log_path = (
            self.attempt_root
            / "artifacts"
            / "logs"
            / safe_case
            / f"{phase}-{safe_flow}.log"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        args = [
            self.config["maestro_command"],
            "--udid",
            self.config["device_id"],
            "test",
            "--format",
            "junit",
            "--output",
            str(report_path),
            "--test-output-dir",
            str(artifact_dir),
            str(flow_path),
        ]
        self._trace(
            event="started",
            entity_type=entity_type,
            entity_id=flow_id,
            phase=phase,
            case_id=effective_case,
            command=args,
        )
        started = time.monotonic()
        returncode, timed_out, timeout_phase, tail = self._run_to_file(
            args,
            log_path,
            artifact_dir,
            float(self.config["timeout_seconds"]),
            float(self.config.get("startup_timeout_seconds", 180)),
        )
        evidence_error = report_error(report_path)
        succeeded = returncode == 0 and evidence_error is None and not timed_out
        self._trace(
            event="finished",
            entity_type=entity_type,
            entity_id=flow_id,
            phase=phase,
            case_id=effective_case,
            succeeded=succeeded,
            exit_code=returncode,
            timed_out=timed_out,
            timeout_phase=timeout_phase,
            report_error=evidence_error,
            duration_seconds=round(time.monotonic() - started, 3),
            report_path=str(report_path.relative_to(self.run_dir)),
            log_path=str(log_path.relative_to(self.run_dir)),
        )
        if not succeeded:
            reason = (
                f"{timeout_phase} timed out" if timed_out else f"exit={returncode}; {evidence_error or 'process failed'}"
            )
            raise AssertionError(
                f"Maestro flow {flow_id} failed ({reason})\n{tail}"
            )

    @staticmethod
    def _run_to_file(
        args: Sequence[str],
        log_path: Path,
        artifact_dir: Path,
        timeout_seconds: float,
        startup_timeout_seconds: float,
    ) -> tuple[int, bool, str | None, str]:
        with log_path.open("wb") as output:
            process = subprocess.Popen(
                list(args),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                shell=False,
            )
            started = time.monotonic()
            execution_started: float | None = None
            timed_out = False
            timeout_phase: str | None = None
            while process.poll() is None:
                output.flush()
                if execution_started is None:
                    for maestro_log in artifact_dir.glob("**/logs/maestro.log"):
                        with maestro_log.open("rb") as progress:
                            progress.seek(max(0, maestro_log.stat().st_size - 4096))
                            if b"CliConsoleListener.onCommandStart" in progress.read():
                                execution_started = time.monotonic()
                                break
                now = time.monotonic()
                if execution_started is None and now - started >= startup_timeout_seconds:
                    timed_out = True
                    timeout_phase = "startup"
                elif execution_started is not None and now - execution_started >= timeout_seconds:
                    timed_out = True
                    timeout_phase = "execution"
                if timed_out:
                    process.terminate()
                    try:
                        returncode = process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        returncode = process.wait(timeout=5)
                    break
                time.sleep(0.1)
            else:
                returncode = process.returncode
        with log_path.open("rb") as source:
            source.seek(max(0, log_path.stat().st_size - 16_384))
            tail = source.read().decode("utf-8", errors="replace")
        return returncode, timed_out, timeout_phase, tail

    def _trace(self, **event: Any) -> None:
        if self._fixture_scope:
            event["fixture_scope"] = self._fixture_scope
            event["affected_case_ids"] = list(self._scope_users.get(self._scope_key(event["entity_id"], self._fixture_scope), []))
        payload = {
            "occurred_at": datetime.now(UTC).isoformat(),
            **event,
        }
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload, ensure_ascii=False) + "\n")
            output.flush()
            os.fsync(output.fileno())

    @staticmethod
    def _safe_segment(value: str) -> str:
        return "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
