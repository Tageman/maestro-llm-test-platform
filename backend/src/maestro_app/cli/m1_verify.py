from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maestro_app.application.flow_translator import RuleBasedFlowTranslator
from maestro_app.application.generation_service import GenerationService
from maestro_app.application.workbook_service import WorkbookService
from maestro_app.domain.enums import GenerationStatus, RunMode, WorkbookStatus
from maestro_app.domain.models import ApprovalRequest, CreateGenerationRequest
from maestro_app.infrastructure.excel_importer import ExcelWorkbookImporter
from maestro_app.infrastructure.generation_repository import GenerationRepository
from maestro_app.infrastructure.workbook_repository import WorkbookRepository


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the repeatable M1 Excel-to-Maestro acceptance workflow."
    )
    parser.add_argument("--workbook", required=True, type=Path)
    parser.add_argument(
        "--runtime-dir", type=Path, default=Path("runtime/m1-acceptance-runtime")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("runtime/m1-acceptance-evidence")
    )
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in RunMode],
        default=RunMode.REVIEW.value,
        help="Generation mode; review remains the default M1 acceptance path.",
    )
    args = parser.parse_args()

    workbook_path = args.workbook.expanduser().resolve()
    runtime_dir = args.runtime_dir.resolve()
    output_dir = args.output_dir.resolve()
    source_hash_before = _sha256(workbook_path)

    workbook_repository = WorkbookRepository(runtime_dir)
    generation_repository = GenerationRepository(runtime_dir)
    workbook_service = WorkbookService(
        workbook_repository, ExcelWorkbookImporter()
    )
    generation_service = GenerationService(
        workbook_repository,
        generation_repository,
        RuleBasedFlowTranslator(),
    )

    workbook = workbook_service.import_bytes(
        workbook_path.name, workbook_path.read_bytes()
    )
    snapshot = workbook_service.get_snapshot(workbook.workbook_id)
    if workbook.status != WorkbookStatus.VALID:
        raise RuntimeError("baseline workbook is invalid")
    expected_counts = {
        "cases": 1,
        "fixtures": 2,
        "configs": 19,
        "enabled_cases": 1,
        "enabled_fixtures": 2,
        "errors": 0,
        "warnings": 0,
    }
    if workbook.counts.model_dump() != expected_counts:
        raise RuntimeError(
            f"baseline counts changed: {workbook.counts.model_dump()}"
        )
    expected_plan = ["FX-APP-RESET", "FX-LOGIN-READY"]
    if snapshot.fixture_plans.get("TC-HOME-001") != expected_plan:
        raise RuntimeError(
            f"fixture plan changed: {snapshot.fixture_plans.get('TC-HOME-001')}"
        )

    mode = RunMode(args.mode)
    generation = generation_service.create(
        CreateGenerationRequest(
            workbook_id=workbook.workbook_id,
            mode=mode,
        )
    )
    if not generation.flows or not all(flow.syntax_valid for flow in generation.flows):
        raise RuntimeError("one or more generated flows failed Maestro syntax checking")

    flow_ids = [flow.flow_id for flow in generation.flows]
    if mode == RunMode.REVIEW:
        if generation.status != GenerationStatus.AWAITING_REVIEW:
            raise RuntimeError(
                f"generation did not reach review: {generation.status.value}"
            )
        generation = generation_service.approve(
            generation.generation_id,
            ApprovalRequest(flow_ids=flow_ids),
        )
    if generation.status != GenerationStatus.READY:
        raise RuntimeError(
            f"generation did not reach ready: {generation.status.value}"
        )

    source_hash_after = _sha256(workbook_path)
    if source_hash_after != source_hash_before:
        raise RuntimeError("source workbook changed during M1 verification")

    flows: list[dict[str, Any]] = []
    for flow_id in flow_ids:
        detail = generation_service.get_flow(generation.generation_id, flow_id)
        flow_dir = generation_repository.flow_dir(generation.generation_id, flow_id)
        flows.append(
            {
                "flow_id": flow_id,
                "flow_kind": detail.flow_kind,
                "status": detail.status.value,
                "syntax_valid": detail.syntax_valid,
                "syntax_output": detail.syntax_output,
                "syntax_attempts": detail.syntax_attempts,
                "syntax_repairs": detail.syntax_repairs,
                "approved": detail.approved,
                "yaml_sha256": hashlib.sha256(
                    detail.yaml.encode("utf-8")
                ).hexdigest(),
                "ir_path": str(flow_dir / "detail.json"),
                "initial_yaml_path": str(flow_dir / "initial.yaml"),
                "final_yaml_path": str(flow_dir / "final.yaml"),
                "mapping_count": len(detail.mappings),
            }
        )

    report = {
        "milestone": "M1",
        "status": "PASS",
        "tested_at": datetime.now(UTC).isoformat(),
        "translator": "rule-based-v1",
        "mode": mode.value,
        "source_workbook": str(workbook_path),
        "source_sha256_before": source_hash_before,
        "source_sha256_after": source_hash_after,
        "workbook_id": workbook.workbook_id,
        "workbook_status": workbook.status.value,
        "counts": workbook.counts.model_dump(),
        "fixture_plans": snapshot.fixture_plans,
        "generation_id": generation.generation_id,
        "generation_status": generation.status.value,
        "approved_flow_count": generation.approved_flow_count,
        "flows": flows,
        "generation_summary_path": str(
            generation_repository.generation_dir(generation.generation_id)
            / "generation.json"
        ),
    }
    _write_json(output_dir / "summary.json", report)
    print(f"M1 verification passed: {output_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
