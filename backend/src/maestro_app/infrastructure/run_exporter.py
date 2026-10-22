from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


class RunExporter:
    """Export an immutable delivery copy without relocating the authoritative Run.

    Absolute destinations are explicitly supported. Relative destinations are
    anchored to a configured project directory, never the launching shell's cwd.
    Existing Run directories and symbolic links are never overwritten/followed.
    An interrupted copy remains visibly incomplete for manual inspection.
    """

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir.resolve()

    def destination(self, root: Path, output_dir: str | Path) -> Path:
        raw = Path(output_dir).expanduser()
        if not str(output_dir).strip() or ".." in raw.parts:
            raise ValueError("output_dir must be a non-empty path without '..'")
        base = raw if raw.is_absolute() else self.base_dir / raw
        self._reject_links(base)
        base = base.resolve()
        root = root.resolve()
        target = base / root.name
        # A nested export would recursively include itself; a parent could
        # overlap existing evidence. Neither changes the canonical Run layout.
        if target == root or target.is_relative_to(root) or root.is_relative_to(target):
            raise ValueError("export destination overlaps the authoritative Run")
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"export destination already exists: {target}")
        return target

    def export(self, root: Path, output_dir: str | Path, run_snapshot: dict) -> Path:
        root = root.resolve()
        target = self.destination(root, output_dir)
        # Check every source before creating a destination. Never copy a link
        # to an unrelated local file into a report bundle.
        sources = sorted(root.rglob("*"))
        for source in sources:
            if source.is_symlink():
                raise ValueError(f"symlink in Run export: {source.relative_to(root)}")
            if not source.is_dir() and not source.is_file():
                raise ValueError("Run export contains a non-regular file")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._reject_links(target.parent)
        target.mkdir(exist_ok=False)
        incomplete = target / ".export-incomplete"
        incomplete.write_text("Incomplete delivery; do not treat as an accepted report.\n", encoding="utf-8")
        files: list[dict] = []
        for source in sources:
            relative = source.relative_to(root)
            if relative.as_posix() in {"export-manifest.json", ".export-incomplete"}:
                raise ValueError("reserved export filename in source Run")
            destination = target / relative
            if source.is_dir():
                destination.mkdir(exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            content = (
                (json.dumps(run_snapshot, ensure_ascii=False, indent=2) + "\n").encode()
                if relative.as_posix() == "run.json"
                else source.read_bytes()
            )
            with destination.open("xb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            digest = hashlib.sha256(content).hexdigest()
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"export verification failed: {relative}")
            files.append({"path": relative.as_posix(), "sha256": digest, "bytes": len(content)})
        manifest = {
            "schema_version": "1.0", "run_id": root.name,
            "status": "completed", "authoritative_run_dir": str(root),
            "files": files,
        }
        with (target / "export-manifest.json").open("x", encoding="utf-8") as output:
            json.dump(manifest, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        incomplete.unlink()
        return target

    @staticmethod
    def _reject_links(path: Path) -> None:
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("export destination must not contain symbolic links")
