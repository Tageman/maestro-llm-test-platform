import hashlib
import json

import pytest

from maestro_app.application.errors import StateConflict
from maestro_app.application.run_recovery import RunRecovery
from maestro_app.domain.enums import CaseRunState, RunMode, RunState
from maestro_app.domain.models import CaseRun, Run
from maestro_app.domain.state_machine import TERMINAL_STATES
from maestro_app.infrastructure.run_repository import RunRepository, UnsafeRunPath


def stored_run(tmp_path, state, *, ownership="guarded-v1", export=None):
    repository = RunRepository(tmp_path)
    run = Run(
        run_id="run-recover", generation_id="generation-1", workbook_id="workbook-1",
        mode=RunMode.REVIEW, state=state, execution_ownership=ownership,
        export_status=export,
        case_runs=[CaseRun(case_id="done", state=CaseRunState.PASSED), CaseRun(case_id="active"), CaseRun(case_id="pending")],
    )
    repository.initialize(run.run_id)
    repository.save_run(run)
    return repository, run


@pytest.mark.parametrize("state", [state for state in RunState if state not in TERMINAL_STATES])
def test_each_interrupted_stage_is_safely_terminated_without_replay(tmp_path, state):
    repository, run = stored_run(tmp_path, state, export="pending")
    evidence = repository.write_text_atomic(run.run_id, "reports/partial.log", "original evidence")
    before = evidence.read_bytes()
    recovery = RunRecovery(repository)
    assert recovery.recover() == [run.run_id]
    result = repository.get_run(run.run_id)
    assert result.state == recovery._target(state)
    assert result.state not in {RunState.COMPLETED, RunState.COMPLETED_WITH_FAILURES}
    assert result.export_status == "failed"
    assert result.case_runs[0].state == CaseRunState.PASSED
    assert result.case_runs[1].state == CaseRunState.BLOCKED
    assert result.case_runs[1].attempts == []
    assert evidence.read_bytes() == before
    assert len(result.artifacts) == 2
    snapshot, path = repository.artifact_path(run.run_id, result.artifacts[0].artifact_id)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == snapshot.sha256
    assert json.loads(path.read_text())["state"] == state.value
    after = (repository.run_dir(run.run_id) / "run.json").read_bytes()
    assert recovery.recover() == []
    assert (repository.run_dir(run.run_id) / "run.json").read_bytes() == after
    recovery.assert_execution_allowed()


@pytest.mark.parametrize("state", TERMINAL_STATES)
def test_completed_evidence_is_byte_for_byte_unchanged(tmp_path, state):
    repository, run = stored_run(tmp_path, state)
    source = repository.run_dir(run.run_id) / "run.json"
    before = source.read_bytes()
    assert RunRecovery(repository).recover() == []
    assert source.read_bytes() == before


def test_interrupted_attempt_has_unknown_result_not_false_pass_or_cleanup(tmp_path):
    repository, run = stored_run(tmp_path, RunState.RUNNING)
    repository.append_event(run, event_type="attempt.started", entity_type="case", entity_id="active", state="RUNNING", message="start", data={"attempt_id": "active-a1"})
    RunRecovery(repository).recover()
    result = repository.get_run(run.run_id)
    active = result.case_runs[1]
    assert active.state == CaseRunState.FAILED
    assert active.business_result == active.cleanup_result == "unknown"
    assert active.attempts[0].failure_type.value == "UNKNOWN"
    assert active.attempts[0].exit_code is None
    assert result.case_runs[2].attempts == []


def test_shared_scope_recovery_does_not_leave_prior_consumers_false_pass(tmp_path):
    repository, run = stored_run(tmp_path, RunState.RUNNING)
    repository.write_json_atomic(run.run_id, "generated/mappings/pytest.json", {"shared_scopes": True})
    RunRecovery(repository).recover()
    previous = repository.get_run(run.run_id).case_runs[0]
    assert previous.state == CaseRunState.FIXTURE_FAILED
    assert previous.cleanup_result == "unknown"


def test_legacy_run_requires_explicit_operator_acknowledgement(tmp_path):
    repository, run = stored_run(tmp_path, RunState.DIAGNOSING, ownership=None)
    recovery = RunRecovery(repository)
    recovery.recover()
    with pytest.raises(StateConflict, match="人工核查"):
        recovery.assert_execution_allowed()
    recovery.acknowledge_legacy_check(run.run_id)
    recovery.assert_execution_allowed()
    recovery.acknowledge_legacy_check(run.run_id)
    assert sum(event.type == "run.recovery_acknowledged" for event in repository.list_events(run.run_id)) == 1
    report = next(artifact for artifact in repository.get_run(run.run_id).artifacts if artifact.kind == "recovery_report")
    _, path = repository.artifact_path(run.run_id, report.artifact_id)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == report.sha256


def test_delivery_interruption_keeps_terminal_business_outcome(tmp_path):
    repository, run = stored_run(tmp_path, RunState.COMPLETED, export="pending")
    RunRecovery(repository).recover()
    result = repository.get_run(run.run_id)
    assert result.state == RunState.COMPLETED
    assert result.export_status == "failed"
    assert result.case_runs == run.case_runs


def test_recovery_can_resume_after_state_saved_before_event(tmp_path, monkeypatch):
    repository, run = stored_run(tmp_path, RunState.FINALIZING)
    append = repository.append_event
    def unavailable(*args, **kwargs):
        raise OSError("simulated exit during recovery event")
    monkeypatch.setattr(repository, "append_event", unavailable)
    with pytest.raises(OSError):
        RunRecovery(repository).recover()
    monkeypatch.setattr(repository, "append_event", append)
    assert RunRecovery(repository).recover() == [run.run_id]
    assert sum(event.type == "run.recovered" for event in repository.list_events(run.run_id)) == 1
    assert json.loads((repository.run_dir(run.run_id) / "recovery/before-run.json").read_text())["state"] == "FINALIZING"


def test_durable_event_is_not_overwritten_when_cursor_write_was_lost(tmp_path):
    repository, run = stored_run(tmp_path, RunState.RUNNING)
    repository.append_event(run, event_type="attempt.started", entity_type="case", entity_id="active", state="RUNNING", message="start", data={"attempt_id": "active-a1"})
    repository.save_run(run)  # Simulated crash: old cursor survived.
    RunRecovery(repository).recover()
    events = repository.list_events(run.run_id)
    assert [event.sequence for event in events] == [1, 2]
    assert events[0].type == "attempt.started"
    assert repository.get_run(run.run_id).case_runs[1].attempts[0].ordinal == 1


def test_corrupt_or_linked_records_fail_closed(tmp_path):
    repository, run = stored_run(tmp_path, RunState.RUNNING)
    path = repository.run_dir(run.run_id) / "run.json"
    path.write_text("bad json")
    with pytest.raises(ValueError):
        RunRecovery(repository).recover()
    path.unlink()
    other = tmp_path / "other.json"
    other.write_text(run.model_dump_json())
    path.symlink_to(other)
    with pytest.raises(UnsafeRunPath):
        RunRecovery(repository).recover()
