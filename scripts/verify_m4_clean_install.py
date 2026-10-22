"""Opt-in clean venv and frontend install/build; preserves existing environments."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, XONSH_HISTORY_BACKEND="dummy", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    env.pop("PYTHONPATH", None)
    frontend = output / "frontend"
    shutil.copytree(ROOT / "frontend", frontend, ignore=shutil.ignore_patterns("node_modules", "dist"))
    python = output / "venv/bin/python"
    steps = [
        ("venv", [sys.executable, "-m", "venv", str(output / "venv")], ROOT),
        ("backend-install", [str(python), "-m", "pip", "install", "-e", ".[dev]"], ROOT),
        ("backend-freeze", [str(python), "-m", "pip", "freeze"], output),
        ("backend-startup", [str(python), "-c", "from maestro_app.core.config import Settings; from maestro_app.main import create_app; settings=Settings.from_environment(); assert settings.ir_schema_path.is_file(); app=create_app(settings); assert app; print('ASGI app and schema ready')"], output),
        ("backend-tests", [str(python), "-m", "pytest", "-q", f"--junitxml={output / 'pytest.xml'}"], ROOT),
        ("frontend-install", ["npm", "ci", "--no-audit", "--no-fund"], frontend),
        ("frontend-build", ["npm", "run", "build"], frontend),
    ]
    evidence = {"status": "RUNNING", "started_at": datetime.now(UTC).isoformat(), "steps": [], "scope": "fresh venv and node_modules on existing host, not fresh OS; no human signoff"}
    for name, command, cwd in steps:
        print(f"START {name}", flush=True)
        with (output / f"{name}.log").open("w") as log:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900, check=False)
        evidence["steps"].append({"name": name, "command": command, "returncode": result.returncode})
        evidence["status"] = "RUNNING" if result.returncode == 0 else "FAIL"
        (output / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
        print(f"{'PASS' if result.returncode == 0 else 'FAIL'} {name}", flush=True)
        if result.returncode:
            return 1
    evidence["status"] = "PASS"
    evidence["finished_at"] = datetime.now(UTC).isoformat()
    evidence["lock_sha256"] = hashlib.sha256((frontend / "package-lock.json").read_bytes()).hexdigest()
    (output / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
