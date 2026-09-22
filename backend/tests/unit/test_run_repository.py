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
