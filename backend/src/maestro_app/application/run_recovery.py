from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from maestro_app.application.errors import StateConflict
from maestro_app.domain.enums import CaseRunState, FailureType, RunState
from maestro_app.domain.models import Attempt
from maestro_app.domain.state_machine import RunStateMachine, TERMINAL_STATES


class RunRecovery:
    """Called only while holding the runtime's exclusive execution lease.

    Recovery never executes an external command, replays a Flow, writes Excel,
    repairs YAML, or automatically retries an incomplete directory delivery.
    """

    def __init__(self, repository) -> None:
        self.repository = repository

    def recover(self) -> list[str]:
        recovered = []
        for run in self.repository.list_runs():
            root = self.repository.run_dir(run.run_id)
            report_path = root / "recovery/report.json"
            if report_path.is_symlink() or report_path.parent.is_symlink():
                raise RuntimeError("Recovery refuses linked reports")
            report = json.loads(report_path.read_text()) if report_path.exists() else None
            if report and report["status"] == "completed":
                # Finish artifact registration if a prior process exited just
                # after committing the report, without rewriting the report.
                for relative, kind in [("recovery/before-run.json", "recovery_snapshot"), ("recovery/report.json", "recovery_report")]:
                    if not any(item.relative_path == relative for item in run.artifacts):
                        self.repository.register_artifact(run.run_id, relative, kind=kind, media_type="application/json")
                continue
            if run.state in TERMINAL_STATES and run.export_status != "pending" and report is None:
                continue
            if report is None:
                # Preserve raw input evidence before any recovery mutation.
                self.repository.write_text_atomic(run.run_id, "recovery/before-run.json", (root / "run.json").read_text())
                evidence = []
                for path in sorted(root.rglob("*")):
                    if path.is_symlink():
                        raise RuntimeError("Recovery refuses linked evidence")
                    if path.is_file() and path.relative_to(root).parts[0] != "recovery":
                        with path.open("rb") as source:
                            digest = hashlib.file_digest(source, "sha256").hexdigest()
                        evidence.append({"path": str(path.relative_to(root)), "sha256": digest})
                report = {
                    "schema_version": "1.0", "status": "prepared",
                    "run_id": run.run_id, "previous_state": run.state.value,
                    "recovered_at": datetime.now(UTC).isoformat(),
                    "policy": "safe-stop-no-replay",
                    "requires_manual_process_check": run.execution_ownership != "guarded-v1",
                    "process_cleanup": "guardians_drained" if run.execution_ownership == "guarded-v1" else "legacy_ownership_unverified",
                    "evidence_before": evidence,
                }
                self.repository.write_json_atomic(run.run_id, "recovery/report.json", report)

            events = self.repository.list_events(run.run_id)
            if run.state not in TERMINAL_STATES:
                now = datetime.now(UTC)
                mapping_path = root / "generated/mappings/pytest.json"
                shared = mapping_path.is_file() and json.loads(mapping_path.read_text()).get("shared_scopes", False)
                unfinished = {}
                for event in events:
                    if event.type == "attempt.started":
                        unfinished[event.entity_id] = event
                    elif event.type == "attempt.finished":
                        unfinished.pop(event.entity_id, None)
                cases = []
                active_states = {CaseRunState.SETTING_UP, CaseRunState.RUNNING, CaseRunState.TEARING_DOWN}
                for case in run.case_runs:
                    active = unfinished.get(case.case_id)
                    if active or case.state in active_states:
                        attempts = list(case.attempts)
                        if active:
                            attempt_id = active.data.get("attempt_id", f"{case.case_id}-a{len(attempts) + 1}")
                            interrupted = Attempt(
                                attempt_id=attempt_id,
                                ordinal=int(attempt_id.rsplit("-a", 1)[1]), state=CaseRunState.FAILED,
                                failure_type=FailureType.UNKNOWN,
                                failure_reason="后端退出导致 Attempt 中断；结果与清理均不能确认",
                            )
                            if not any(item.attempt_id == attempt_id for item in attempts):
                                attempts.append(interrupted)
                        case = case.model_copy(update={
                            "state": CaseRunState.FAILED, "attempts": attempts,
                            "business_result": "unknown", "cleanup_result": "unknown", "ended_at": now,
                        })
                    elif case.state == CaseRunState.PENDING:
                        case = case.model_copy(update={
                            "state": CaseRunState.BLOCKED, "business_result": "not_run",
                            "cleanup_result": "not_required", "ended_at": now,
                        })
                    elif shared and case.state == CaseRunState.PASSED and run.state != RunState.FINALIZING:
                        # A prior Case body may have passed while its shared
                        # teardown was still owned by the interrupted worker.
                        case = case.model_copy(update={
                            "state": CaseRunState.FIXTURE_FAILED,
                            "cleanup_result": "unknown", "ended_at": now,
                            "attempts": [*case.attempts[:-1], case.attempts[-1].model_copy(update={
                                "state": CaseRunState.FIXTURE_FAILED, "failure_type": FailureType.FIXTURE,
                                "failure_reason": "后端退出，共享清理无法确认",
                            })] if case.attempts else [],
                        })
                    cases.append(case)
                target = self._target(run.state)
                RunStateMachine(run.state).transition_to(target)
                reason = "后端重启恢复检查：旧 Run 安全终止，未重放外部操作；请创建新 Run"
                if report["requires_manual_process_check"]:
                    reason += "；旧版进程所有权无法验证，需人工核查后解锁执行"
                run = run.model_copy(update={
                    "state": target, "case_runs": cases, "updated_at": now,
                    "ended_at": now, "terminal_reason": reason,
                })
            if run.export_status == "pending":
                run = run.model_copy(update={
                    "export_status": "failed", "export_error": "后端退出中断交付，未自动重试或覆盖导出目录",
                })
            self.repository.save_run(run)
            if not any(event.type == "run.recovered" for event in events):
                run, _ = self.repository.append_event(
                    run, event_type="run.recovered", entity_type="run", entity_id=run.run_id,
                    state=run.state.value, message="恢复检查完成；不自动重放执行或交付",
                    data={key: report[key] for key in ("previous_state", "policy", "process_cleanup", "requires_manual_process_check")},
                )
            report["status"] = "completed"
            report["final_state"] = run.state.value
            self.repository.write_json_atomic(run.run_id, "recovery/report.json", report)
            for relative, kind in [("recovery/before-run.json", "recovery_snapshot"), ("recovery/report.json", "recovery_report")]:
                self.repository.register_artifact(run.run_id, relative, kind=kind, media_type="application/json")
            recovered.append(run.run_id)
        return recovered

    def assert_execution_allowed(self) -> None:
        for run in self.repository.list_runs():
            path = self.repository.run_dir(run.run_id) / "recovery/report.json"
            if path.exists() and json.loads(path.read_text())["requires_manual_process_check"]:
                raise StateConflict("LEGACY_PROCESS_CHECK_REQUIRED", f"旧 Run {run.run_id} 的进程所有权不明，须人工核查并确认恢复记录后才能执行")

    def acknowledge_legacy_check(self, run_id: str) -> None:
        run = self.repository.get_run(run_id)
        path = self.repository.run_dir(run_id) / "recovery/report.json"
        if not path.is_file():
            raise StateConflict("RECOVERY_NOT_FOUND", "没有需要确认的恢复记录")
        report = json.loads(path.read_text())
        if not report["requires_manual_process_check"]:
            return
        report.update({"requires_manual_process_check": False, "manual_process_check_at": datetime.now(UTC).isoformat()})
        self.repository.append_event(
            run, event_type="run.recovery_acknowledged", entity_type="run", entity_id=run_id,
            state=run.state.value, message="操作人员明确确认旧版执行进程已清理；没有重放旧 Run",
        )
        self.repository.write_json_atomic(run_id, "recovery/report.json", report)
        self.repository.register_artifact(run_id, "recovery/report.json", kind="recovery_report", media_type="application/json")

    @staticmethod
    def _target(state: RunState) -> RunState:
        if state == RunState.VALIDATING:
            return RunState.VALIDATION_FAILED
        if state == RunState.GENERATING:
            return RunState.GENERATION_FAILED
        if state in {RunState.CREATED, RunState.AWAITING_REVIEW, RunState.READY}:
            return RunState.CANCELLED
        return RunState.FAILED
