from pathlib import Path

import pytest

from maestro_app.application.errors import ResourceNotFound, StateConflict
from maestro_app.application.ports import ManagedProcessResult
from maestro_app.application.run_service import RunService
from maestro_app.domain.enums import RunMode, RunState
from maestro_app.domain.models import CreateRunRequest, Run
from integration.test_m4_delivery import build_service


@pytest.mark.parametrize("stage, expected", [("collect", RunState.GENERATION_FAILED), ("device", RunState.FAILED)])
def test_early_failure_releases_active_slot_and_exports_failure_evidence(tmp_path, monkeypatch, stage, expected):
    service, generation = build_service(tmp_path)
    if stage == "collect":
        monkeypatch.setattr(service.pytest_runner, "collect", lambda package: ManagedProcessResult(1, "collection failed", package.collection_path))
    else:
        def unavailable(config):
            raise RuntimeError("device disconnected")
        monkeypatch.setattr(service.device_manager, "prepare", unavailable)
    summary = service.create(CreateRunRequest(generation_id=generation.generation_id))
    assert summary.state == expected
    assert summary.export_status == "completed"
    assert service._active_run_id is None
    assert service._cancel_events == {}
    assert service.get(summary.run_id).state == expected
    assert service.cancel(summary.run_id).state == expected


def test_runtime_rejects_unknown_selection_and_invalid_snapshot(tmp_path, monkeypatch):
    service, generation = build_service(tmp_path)
    request = CreateRunRequest(generation_id=generation.generation_id, case_ids=["NO-SUCH-CASE"])
    with pytest.raises(StateConflict, match="选择"):
        service.create(request)
    snapshot = service.workbook_repository.get(generation.workbook_id)
    monkeypatch.setattr(service.workbook_repository, "get", lambda _: snapshot.model_copy(update={"config": None}))
    with pytest.raises(StateConflict, match="阻断"):
        service.create(CreateRunRequest(generation_id=generation.generation_id))


def test_active_run_blocks_second_run_and_stale_pointer_is_released(tmp_path):
    service, generation = build_service(tmp_path)
    active = Run(run_id="run-active", generation_id=generation.generation_id, workbook_id=generation.workbook_id, mode=RunMode.REVIEW, state=RunState.RUNNING)
    service.run_repository.save_run(active)
    service._active_run_id = active.run_id
    with pytest.raises(StateConflict, match="活动 Run"):
        service.create(CreateRunRequest(generation_id=generation.generation_id))
    service._active_run_id = "missing-run"
    assert service.create(CreateRunRequest(generation_id=generation.generation_id)).state == RunState.COMPLETED
    with pytest.raises(ResourceNotFound):
        service.get_case(active.run_id, "unknown")


@pytest.mark.parametrize("state,expected", [
    (RunState.VALIDATING, RunState.VALIDATION_FAILED),
    (RunState.GENERATING, RunState.GENERATION_FAILED),
    (RunState.CREATED, RunState.CANCELLED),
    (RunState.AWAITING_REVIEW, RunState.CANCELLED),
    (RunState.READY, RunState.CANCELLED),
    (RunState.REPAIRING, RunState.FAILED),
])
def test_error_state_mapping_obeys_phase(state, expected):
    assert RunService._failure_state(state) == expected


def test_missing_and_invalid_reports_are_not_success_evidence(tmp_path):
    path = tmp_path / "report.xml"
    assert RunService._read_junit(path) == set()
    assert RunService._read_traces(path) == []
    path.write_text("broken <xml")
    assert RunService._read_junit(path) == set()
    path.write_text('<testsuite><testcase name="not_a_case"/></testsuite>')
    assert RunService._read_junit(path) == set()


@pytest.mark.parametrize("content", ["not-yaml: [broken", "one-document", 'appId: example.app\n---\n- back\n- tapOn: {id: ignored}\n- scrollUntilVisible: {element: target}\n- assertVisible: target\n'])
def test_selector_evidence_guard_handles_shapes(tmp_path, content):
    service, _ = build_service(tmp_path)
    assert service._selector_step("run-shapes", "TC-1", None) is None
    assert service._selector_step("run-shapes", "TC-1", "target") is None
    assert not service._selector_is_assertion("run-shapes", "TC-1", "case", None)
    assert not service._selector_is_assertion("run-shapes", "TC-1", "case", "target")
    service.run_repository.write_text_atomic("run-shapes", "generated/cases/TC-1.yaml", content)
    valid = "scrollUntilVisible" in content
    assert service._selector_step("run-shapes", "TC-1", "target") == (2 if valid else None)
    assert service._selector_is_assertion("run-shapes", "TC-1", "case", "target") is valid
    assert service._selector_step("run-shapes", "TC-1", "missing") is None
