from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from openpyxl import load_workbook

from maestro_app.domain.enums import CaseRunState, FailureType, RunMode, RunState
from maestro_app.domain.models import Attempt, CaseRun, Run
from maestro_app.infrastructure.excel_importer import ExcelWorkbookImporter
from maestro_app.infrastructure.result_workbook import ResultWorkbookWriter
from m1_helpers import build_sample_workbook


def test_result_writer_preserves_source_and_verifies_written_fields(tmp_path: Path) -> None:
    source = build_sample_workbook(tmp_path / "source.xlsx")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    snapshot = ExcelWorkbookImporter().import_workbook(
        source,
        workbook_id="workbook-1",
        source_filename=source.name,
        source_sha256=source_hash,
    )
    now = datetime.now(UTC)
    run = Run(
        run_id="run-result-1",
        generation_id="generation-1",
        workbook_id=snapshot.workbook_id,
        mode=RunMode.UNATTENDED,
        state=RunState.FINALIZING,
        case_runs=[
            CaseRun(
                case_id="TC-HOME-001",
                state=CaseRunState.FAILED,
                attempts=[
                    Attempt(
                        attempt_id="TC-HOME-001-a1",
                        ordinal=1,
                        state=CaseRunState.FAILED,
                        failure_type=FailureType.ASSERTION,
                        failure_reason="业务断言未满足",
                        exit_code=1,
                    )
                ],
                business_result="failed",
                cleanup_result="passed",
                started_at=now,
                ended_at=now,
                duration_seconds=1.25,
            )
        ],
    )

    evidence = ResultWorkbookWriter().write(
        source_path=source,
        result_dir=tmp_path / "result",
        snapshot=snapshot,
        run=run,
    )

    assert evidence.source_sha256_before == source_hash
    assert evidence.source_sha256_after == source_hash
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    workbook = load_workbook(evidence.path, read_only=True)
    sheet = workbook["Cases"]
    headers = {cell.value: cell.column for cell in sheet[5]}
    assert sheet.cell(6, headers["执行状态"]).value == "FAILED"
    assert sheet.cell(6, headers["执行次数"]).value == 1
    assert sheet.cell(6, headers["失败类型"]).value == "ASSERTION"
    workbook.close()
