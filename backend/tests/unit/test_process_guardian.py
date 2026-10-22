import subprocess

import pytest

from maestro_app.infrastructure.process_guardian import group_has_live_members


@pytest.mark.parametrize("listing, expected", [("42 Z\n99 S\n", False), ("42 S\n", True), ("99 S\n", False), ("42 Z\n42 R+\n", True)])
def test_permission_fallback_distinguishes_live_groups_from_reaped_zombies(monkeypatch, listing, expected):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=listing))
    assert group_has_live_members(42) is expected


def test_permission_fallback_fails_closed_if_process_listing_unavailable(monkeypatch):
    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])
    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(subprocess.CalledProcessError):
        group_has_live_members(42)
