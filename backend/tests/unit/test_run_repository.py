from pathlib import Path

import pytest

from maestro_app.infrastructure.run_repository import RunRepository, UnsafeRunPath


def test_atomic_json_round_trip(tmp_path: Path) -> None:
    repository = RunRepository(tmp_path)
    target = repository.write_json_atomic("run-001", "run.json", {"state": "CREATED"})

    assert target.exists()
    assert repository.read_json("run-001", "run.json") == {"state": "CREATED"}


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    repository = RunRepository(tmp_path)

    with pytest.raises(UnsafeRunPath):
        repository.write_json_atomic("run-001", "../../escape.json", {})


@pytest.mark.parametrize("operation", ["json", "bytes"])
@pytest.mark.parametrize("stage", ["mkstemp", "fsync", "replace"])
def test_atomic_write_failure_preserves_previous_record(tmp_path, monkeypatch, operation, stage):
    import errno
    repository = RunRepository(tmp_path)
    target = repository.write_json_atomic("run-001", "run.json", {"state": "CREATED"})
    before = target.read_bytes()
    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, "injected persistence failure")
    module = "tempfile" if stage == "mkstemp" else "os"
    monkeypatch.setattr(f"maestro_app.infrastructure.run_repository.{module}.{stage}", fail)
    with pytest.raises(OSError, match="injected persistence failure"):
        if operation == "json":
            repository.write_json_atomic("run-001", "run.json", {"state": "COMPLETED"})
        else:
            repository.write_text_atomic("run-001", "run.json", "replacement")
    assert target.read_bytes() == before
    assert not list(target.parent.glob(".run.json.*.tmp"))


def test_corrupt_run_record_blocks_listing_instead_of_disappearing(tmp_path):
    repository = RunRepository(tmp_path)
    repository.write_text_atomic("run-001", "run.json", "broken JSON")
    with pytest.raises(ValueError):
        repository.list_runs()
