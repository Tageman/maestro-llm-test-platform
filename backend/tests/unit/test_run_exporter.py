import hashlib
import json
from pathlib import Path

import pytest

from maestro_app.infrastructure.run_exporter import RunExporter


def source_run(tmp_path):
    root = tmp_path / "runtime/runs/run-1"
    root.mkdir(parents=True)
    (root / "run.json").write_text('{"export_status":"pending"}')
    (root / "report.html").write_text("evidence")
    return root


@pytest.mark.parametrize("absolute", [True, False])
def test_export_absolute_and_stable_relative_destination(tmp_path, monkeypatch, absolute):
    root = source_run(tmp_path)
    exporter = RunExporter(tmp_path)
    monkeypatch.chdir(root)
    directory = str(tmp_path / "deliveries") if absolute else "./deliveries"
    target = exporter.export(root, directory, {"export_status": "completed"})
    assert target == tmp_path / "deliveries/run-1"
    assert json.loads((target / "run.json").read_text())["export_status"] == "completed"
    assert json.loads((root / "run.json").read_text())["export_status"] == "pending"
    assert not (target / ".export-incomplete").exists()
    manifest = json.loads((target / "export-manifest.json").read_text())
    for item in manifest["files"]:
        assert hashlib.sha256((target / item["path"]).read_bytes()).hexdigest() == item["sha256"]


def test_existing_export_is_never_overwritten(tmp_path):
    root = source_run(tmp_path)
    exporter = RunExporter(tmp_path)
    target = exporter.export(root, "out", {})
    before = (target / "export-manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        exporter.export(root, "out", {})
    assert (target / "export-manifest.json").read_bytes() == before


@pytest.mark.parametrize("directory", ["", "../escape", "runtime/runs", "runtime/runs/run-1/nested"])
def test_unsafe_or_overlapping_destinations_rejected(tmp_path, directory):
    with pytest.raises(ValueError):
        RunExporter(tmp_path).export(source_run(tmp_path), directory, {})


def test_symlink_sources_and_destinations_rejected(tmp_path):
    root = source_run(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    link = tmp_path / "link"
    link.symlink_to(other, target_is_directory=True)
    exporter = RunExporter(tmp_path)
    with pytest.raises(ValueError, match="symbolic"):
        exporter.export(root, str(link), {})
    (root / "leak").symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        exporter.export(root, "out", {})
    assert not (tmp_path / "out").exists()


def test_copy_failure_leaves_explicit_incomplete_delivery(tmp_path, monkeypatch):
    root = source_run(tmp_path)
    read = Path.read_bytes
    def broken(path):
        if path == root / "report.html":
            raise OSError("injected disk read failure")
        return read(path)
    monkeypatch.setattr(Path, "read_bytes", broken)
    with pytest.raises(OSError):
        RunExporter(tmp_path).export(root, "out", {})
    assert (tmp_path / "out/run-1/.export-incomplete").exists()
    assert not (tmp_path / "out/run-1/export-manifest.json").exists()
    assert (root / "report.html").exists()
