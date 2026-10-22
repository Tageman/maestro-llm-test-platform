import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from maestro_app.application.errors import StateConflict
from maestro_app.domain.enums import RunState
from maestro_app.domain.models import CreateRunRequest
from maestro_app.infrastructure.execution_guard import RuntimeExecutionGuard
from maestro_app.infrastructure.owned_process import finish_owned, popen_owned, run_owned
from maestro_app.infrastructure.run_repository import RunRepository
from maestro_app.main import create_app
from fastapi.testclient import TestClient
from integration.test_system_api import _settings
from integration.test_m4_delivery import build_service
from unit.test_run_recovery import stored_run


def test_service_recovers_before_new_run_and_releases_lease(tmp_path):
    service, generation = build_service(tmp_path)
    repository, stale = stored_run(tmp_path / "runtime", RunState.REPAIRING)
    service.execution_guard = RuntimeExecutionGuard(tmp_path / "runtime")
    summary = service.create(CreateRunRequest(generation_id=generation.generation_id))
    assert repository.get_run(stale.run_id).state == RunState.FAILED
    assert summary.state == RunState.COMPLETED
    assert repository.get_run(summary.run_id).execution_ownership == "guarded-v1"
    assert service.recover_after_restart() == []


def test_web_startup_recovers_and_exposes_audit_artifact(tmp_path):
    service, _ = build_service(tmp_path)
    repository, stale = stored_run(tmp_path / "runtime", RunState.PREPARING_DEVICE)
    service.execution_guard = RuntimeExecutionGuard(tmp_path / "runtime")
    with TestClient(create_app(_settings(tmp_path), run_service=service)) as client:
        summary = client.get(f"/api/v1/runs/{stale.run_id}").json()
        assert summary["state"] == "FAILED"
        assert summary["recovery_snapshot_artifact_id"]
        response = client.get(f"/api/v1/runs/{stale.run_id}/artifacts/{summary['recovery_report_artifact_id']}")
        assert response.status_code == 200
        assert response.json()["policy"] == "safe-stop-no-replay"


def test_missing_generation_does_not_leak_runtime_lock(tmp_path):
    service, _ = build_service(tmp_path)
    service.execution_guard = RuntimeExecutionGuard(tmp_path / "runtime")
    with pytest.raises(Exception):
        service.create(CreateRunRequest(generation_id="unknown"))
    service.execution_guard.acquire().close()


def test_live_owner_blocks_new_run_and_restart_does_not_touch_it(tmp_path):
    service, generation = build_service(tmp_path)
    repository, run = stored_run(tmp_path / "runtime", RunState.RUNNING)
    guard = RuntimeExecutionGuard(tmp_path / "runtime")
    service.execution_guard = guard
    lease = guard.acquire()
    try:
        assert service.recover_after_restart() == []
        with pytest.raises(StateConflict, match="运行锁"):
            service.create(CreateRunRequest(generation_id=generation.generation_id))
        assert repository.get_run(run.run_id).state == RunState.RUNNING
        assert service.get(run.run_id).state == RunState.RUNNING
    finally:
        lease.close()
    # A normal UI poll must finish recovery after startup had to defer it.
    assert service.get(run.run_id).state == RunState.FAILED


def test_legacy_attention_blocks_new_run_but_not_reading_evidence(tmp_path):
    service, generation = build_service(tmp_path)
    repository, run = stored_run(tmp_path / "runtime", RunState.RUNNING, ownership=None)
    service.execution_guard = RuntimeExecutionGuard(tmp_path / "runtime")
    with pytest.raises(StateConflict, match="人工核查"):
        service.create(CreateRunRequest(generation_id=generation.generation_id))
    assert service.get(run.run_id).state == RunState.FAILED
    assert service.get_case(run.run_id, "pending").attempts == []
    # Failed creation must not leak the runtime lease.
    service.execution_guard.acquire().close()


def wait_for(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition not reached before deadline")


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_backend_sigkill_drains_owned_group_before_lease_can_be_reacquired(tmp_path):
    pids = tmp_path / "owned-pids.json"
    # All subprocesses in this test are synthetic and isolated; no App/ADB.
    grandchild = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
    target = f"import os,sys,subprocess,time,json,signal; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c',{grandchild!r}]); signal.signal(signal.SIGTERM, signal.SIG_IGN); Path({str(pids)!r}).write_text(json.dumps([os.getpid(),p.pid])); time.sleep(30)"
    owner = f"from pathlib import Path; import sys,time; from maestro_app.infrastructure.execution_guard import RuntimeExecutionGuard; from maestro_app.infrastructure.owned_process import popen_owned; lease=RuntimeExecutionGuard(Path({str(tmp_path)!r})).acquire();\nwith lease.activate():\n p=popen_owned([sys.executable,'-c',{target!r}]); time.sleep(30)\n"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    backend = subprocess.Popen([sys.executable, "-c", owner], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    owned = []
    try:
        wait_for(pids.exists)
        owned = json.loads(pids.read_text())
        with pytest.raises(StateConflict):
            RuntimeExecutionGuard(tmp_path).acquire()
        backend.send_signal(signal.SIGKILL)
        backend.wait(timeout=5)
        acquired = []
        def available():
            try:
                acquired.append(RuntimeExecutionGuard(tmp_path).acquire())
                return True
            except StateConflict:
                return False
        wait_for(available)
        try:
            wait_for(lambda: not any(alive(pid) for pid in owned))
        finally:
            acquired[0].close()
    finally:
        if backend.poll() is None:
            backend.kill()
        backend.wait(timeout=5)
        if backend.stderr:
            backend.stderr.close()
        if owned:
            wait_for(lambda: not any(alive(pid) for pid in owned))


def test_owned_stdio_and_timeout_cleanup(tmp_path):
    result = run_owned([sys.executable, "-c", "import sys; print('ok'); print('err',file=sys.stderr)"], timeout=5)
    assert result.returncode == 0 and result.stdout.strip() == "ok" and result.stderr.strip() == "err"
    with pytest.raises(subprocess.TimeoutExpired):
        run_owned([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.2)
    assert run_owned([str(tmp_path / "nonexistent")], timeout=5).returncode == 127


def test_mcp_style_stdin_is_transparent():
    process = popen_owned([sys.executable, "-u", "-c", "import sys; print(sys.stdin.readline().strip())"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        stdout, _ = process.communicate("jsonrpc\n", timeout=5)
        assert stdout == "jsonrpc\n"
    finally:
        finish_owned(process)


def test_guardian_removes_descendants_when_leader_exits_normally(tmp_path):
    pids = tmp_path / "descendant.pid"
    target = f"import subprocess,sys; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); Path({str(pids)!r}).write_text(str(p.pid))"
    result = run_owned([sys.executable, "-c", target], timeout=5)
    assert result.returncode == 0
    wait_for(lambda: not alive(int(pids.read_text())))
