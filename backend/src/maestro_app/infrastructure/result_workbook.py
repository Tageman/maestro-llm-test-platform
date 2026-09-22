from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from openpyxl import load_workbook

from maestro_app.domain.models import Run, WorkbookSnapshot


@dataclass(frozen=True, slots=True)
class ResultWorkbookEvidence:
    path: Path
    source_sha256_before: str
    source_sha256_after: str
    output_sha256: str
    verified_rows: tuple[int, ...]


class ResultWorkbookWriter:
    CASE_RESULT_FIELDS = (
        "生成状态",
        "初始YAML文件",
        "执行状态",
        "执行次数",
        "自动修复次数",
        "失败步骤",
        "失败类型",
        "失败原因",
        "最终YAML文件",
        "报告路径",
        "截图/日志路径",
        "开始时间",
        "结束时间",
        "执行耗时(秒)",
    )

    def write(
        self,
        *,
        source_path: Path,
        result_dir: Path,
        snapshot: WorkbookSnapshot,
        run: Run,
    ) -> ResultWorkbookEvidence:
        before = self._sha(source_path)
        if before != snapshot.source_sha256:
            raise RuntimeError("source workbook hash no longer matches the snapshot")
        workbook = load_workbook(source_path)
        cases_sheet = workbook["Cases"]
        headers = {
            str(cell.value).strip(): cell.column
            for cell in cases_sheet[5]
            if cell.value is not None
        }
        missing = [name for name in self.CASE_RESULT_FIELDS if name not in headers]
        if missing:
            raise RuntimeError(f"Cases result columns are missing: {missing}")

        cases = {case.case_id: case for case in snapshot.cases}
        verified_rows: list[int] = []
        for case_run in run.case_runs:
            source = cases[case_run.case_id]
            latest_failure = next(
                (
                    item
                    for item in reversed(case_run.attempts)
                    if item.failure_type is not None
                ),
                None,
            )
            repairs = [item for item in run.repairs if item.case_id == case_run.case_id]
            evidence = [
                item.relative_path
                for item in run.artifacts
                if item.case_id == case_run.case_id
                and item.kind in {"screenshot", "log", "hierarchy"}
            ]
            report = next(
                (
                    item.relative_path
                    for item in reversed(run.artifacts)
                    if item.case_id == case_run.case_id
                    and item.kind in {"pytest_junit", "maestro_junit"}
                ),
                None,
            )
            values = {
                "生成状态": "已生成",
                "初始YAML文件": f"generated/initial/cases/{case_run.case_id}.yaml",
                "执行状态": case_run.state.value,
                "执行次数": len(case_run.attempts),
                "自动修复次数": len(repairs),
                "失败步骤": latest_failure.failed_step if latest_failure else None,
                "失败类型": (
                    latest_failure.failure_type.value
                    if latest_failure and latest_failure.failure_type
                    else None
                ),
                "失败原因": latest_failure.failure_reason if latest_failure else None,
                "最终YAML文件": f"generated/cases/{case_run.case_id}.yaml",
                "报告路径": report,
                "截图/日志路径": "\n".join(evidence) or None,
                "开始时间": self._excel_datetime(case_run.started_at),
                "结束时间": self._excel_datetime(case_run.ended_at),
                "执行耗时(秒)": case_run.duration_seconds,
            }
            for name, value in values.items():
                cases_sheet.cell(source.source_row, headers[name], value)
            verified_rows.append(source.source_row)

        result_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = result_dir / f"{source_path.stem}_结果_{stamp}.xlsx"
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp.xlsx", dir=result_dir
        )
        os.close(handle)
        temp_path = Path(temp_name)
        try:
            workbook.save(temp_path)
            check = load_workbook(temp_path, data_only=False, read_only=True)
            check_sheet = check["Cases"]
            for case_run in run.case_runs:
                row = cases[case_run.case_id].source_row
                if check_sheet.cell(row, headers["执行状态"]).value != case_run.state.value:
                    raise RuntimeError(f"result workbook verification failed at Cases!{row}")
            check.close()
            os.replace(temp_path, output)
        finally:
            if temp_path.exists():
                temp_path.unlink()
            workbook.close()
        after = self._sha(source_path)
        if before != after:
            raise RuntimeError("source workbook was modified during result writeback")
        return ResultWorkbookEvidence(
            path=output,
            source_sha256_before=before,
            source_sha256_after=after,
            output_sha256=self._sha(output),
            verified_rows=tuple(verified_rows),
        )

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _excel_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.astimezone(UTC).replace(tzinfo=None)
