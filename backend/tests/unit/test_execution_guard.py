import pytest

from maestro_app.application.errors import StateConflict
from maestro_app.infrastructure.execution_guard import CURRENT_LEASE_FD, RuntimeExecutionGuard


def test_runtime_lease_is_exclusive_and_released_on_close(tmp_path):
    guard = RuntimeExecutionGuard(tmp_path)
    first = guard.acquire()
    with pytest.raises(StateConflict):
        RuntimeExecutionGuard(tmp_path).acquire()
    with first.activate():
        assert CURRENT_LEASE_FD.get() == first.fd
    assert CURRENT_LEASE_FD.get() is None
    first.close()
    first.close()
    second = guard.acquire()
    second.close()


def test_symlink_lock_is_not_followed(tmp_path):
    target = tmp_path / "unrelated"
    target.write_text("preserve")
    (tmp_path / ".execution.lock").symlink_to(target)
    with pytest.raises(OSError):
        RuntimeExecutionGuard(tmp_path).acquire()
    assert target.read_text() == "preserve"
