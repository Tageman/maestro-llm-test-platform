"""Run the M4 pure-logic branch gate; real device and human gates are separate."""
from __future__ import annotations

import json
import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = (
    "domain/fixture_graph.py", "domain/state_machine.py", "domain/flow_ir.py",
    "application/yaml_compiler.py", "application/locator_repair.py",
    "application/failure_classifier.py", "application/run_service.py",
    "application/generation_service.py", "application/startup_policy.py",
    "application/run_recovery.py",
    "application/pytest_generator.py",
    "infrastructure/excel_importer.py", "infrastructure/result_workbook.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New evidence directory; existing explicit paths are rejected")
    args = parser.parse_args()
    output = args.output.resolve() if args.output else ROOT / "runtime/acceptance/m4-quality"
    if args.output and output.exists():
        parser.error("--output must be a new directory; historical evidence is not overwritten")
    output.mkdir(parents=True, exist_ok=True)
    gate_path = output / "gate.json"
    gate_path.write_text(json.dumps({"status": "RUNNING", "required_percent": 85}) + "\n")
    env = dict(os.environ, COVERAGE_FILE=str(output / ".coverage"), XONSH_HISTORY_BACKEND="dummy")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT / "backend/src"), str(ROOT / "backend/tests"), env.get("PYTHONPATH")]))
    commands = [
        [sys.executable, "-m", "coverage", "run", "--branch", "--source=maestro_app", "-m", "pytest", "-q", f"--junitxml={output / 'pytest.xml'}"],
        [sys.executable, "-m", "coverage", "json", "-o", str(output / "coverage.json")],
    ]
    codes = []
    for index, command in enumerate(commands):
        with (output / f"step-{index + 1}.log").open("w") as log:
            completed = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
        codes.append(completed.returncode)
    report_path = output / "coverage.json"
    if codes[1] or not report_path.exists():
        gate_path.write_text(json.dumps({"status": "FAIL", "reason": "coverage tooling failed", "exit_codes": codes}) + "\n")
        print(f"Coverage tooling failed; inspect {output}")
        return 1
    report = json.loads(report_path.read_text())
    files = {}
    for path in CORE:
        key = f"backend/src/maestro_app/{path}"
        if key not in report["files"]:
            gate_path.write_text(json.dumps({"status": "FAIL", "reason": f"missing required core module: {key}"}) + "\n")
            raise RuntimeError(f"Missing required core module in coverage: {key}")
        files[key] = report["files"][key]["summary"]
    total = sum(item["num_branches"] for item in files.values())
    covered = sum(item["covered_branches"] for item in files.values())
    percentage = 100 * covered / total if total else 0
    passed = codes[0] == 0 and percentage >= 85
    evidence = {
        "status": "PASS" if passed else "FAIL", "pytest_exit_code": codes[0],
        "metric": "covered_branches / num_branches (not statement or combined coverage)",
        "covered_branches": covered, "num_branches": total,
        "branch_percent": round(percentage, 2), "required_percent": 85, "files": files,
        "scope_note": "Pure-logic gate only. Adapters, clean install, real device and human signoff are separate gates.",
    }
    (output / "gate.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(f"M4 core branch coverage: {covered}/{total} = {percentage:.2f}% (required 85%); {'PASS' if passed else 'FAIL'}")
    print(f"Evidence: {output}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
