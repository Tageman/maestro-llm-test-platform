import hashlib
from pathlib import Path

from openpyxl import load_workbook

from maestro_app.domain.enums import WorkbookStatus
from maestro_app.infrastructure.excel_importer import ExcelWorkbookImporter
from m1_helpers import build_sample_workbook


def _import(path: Path):
    return ExcelWorkbookImporter().import_workbook(
        path,
        workbook_id="wb-test",
        source_filename=path.name,
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def test_baseline_workbook_parses_all_entities_and_dependency_plan(tmp_path: Path) -> None:
    path = build_sample_workbook(tmp_path / "baseline.xlsx")

    snapshot = _import(path)

    assert snapshot.status == WorkbookStatus.VALID
    assert snapshot.counts.model_dump() == {
        "cases": 1,
        "fixtures": 2,
        "configs": 19,
        "enabled_cases": 1,
        "enabled_fixtures": 2,
        "errors": 0,
        "warnings": 0,
    }
    assert snapshot.fixture_plans["TC-HOME-001"] == [
        "FX-APP-RESET",
        "FX-LOGIN-READY",
    ]


def test_invalid_separator_and_unobservable_expectation_are_located(tmp_path: Path) -> None:
    path = build_sample_workbook(tmp_path / "invalid.xlsx")
    workbook = load_workbook(path)
    workbook["Cases"]["D6"] = "FX-LOGIN-READY；FX-APP-RESET"
    workbook["Cases"]["J6"] = "1. 页面正常"
    workbook.save(path)

    snapshot = _import(path)

    codes = {issue.code for issue in snapshot.validation_issues}
    assert snapshot.status == WorkbookStatus.INVALID
    assert {"LIST_SEPARATOR_INVALID", "EXPECTATION_NOT_OBSERVABLE"} <= codes
    expectation = next(
        issue
        for issue in snapshot.validation_issues
        if issue.code == "EXPECTATION_NOT_OBSERVABLE"
    )
    assert (expectation.sheet, expectation.row, expectation.column) == (
        "Cases",
        6,
        "J",
    )


def test_fixture_cycle_is_blocking(tmp_path: Path) -> None:
    path = build_sample_workbook(tmp_path / "cycle.xlsx")
    workbook = load_workbook(path)
    workbook["Fixtures"]["F6"] = "FX-LOGIN-READY"
    workbook.save(path)

    snapshot = _import(path)

    assert any(
        issue.code == "FIXTURE_DEPENDENCY_CYCLE"
        for issue in snapshot.validation_issues
    )


def test_required_and_enum_errors_have_exact_cells(tmp_path: Path) -> None:
    required_path = build_sample_workbook(tmp_path / "required-error.xlsx")
    workbook = load_workbook(required_path)
    workbook["Cases"]["C6"] = None
    workbook.save(required_path)
    required_snapshot = _import(required_path)

    enum_path = build_sample_workbook(tmp_path / "enum-error.xlsx")
    workbook = load_workbook(enum_path)
    workbook["Cases"]["F6"] = "P9"
    workbook.save(enum_path)
    enum_snapshot = _import(enum_path)

    required = next(
        issue
        for issue in required_snapshot.validation_issues
        if issue.code == "FIELD_REQUIRED"
    )
    enum = next(
        issue
        for issue in enum_snapshot.validation_issues
        if issue.code == "CASE_VALUE_INVALID" and issue.field == "priority"
    )
    assert (required.sheet, required.row, required.column, required.field) == (
        "Cases",
        6,
        "C",
        "title",
    )
    assert (enum.sheet, enum.row, enum.column, enum.field) == (
        "Cases",
        6,
        "F",
        "priority",
    )


def test_duplicate_id_and_config_constraint_are_blocking(tmp_path: Path) -> None:
    path = build_sample_workbook(tmp_path / "business-errors.xlsx")
    workbook = load_workbook(path)
    cases = workbook["Cases"]
    for column in range(1, cases.max_column + 1):
        cases.cell(7, column, cases.cell(6, column).value)
    config = workbook["Config"]
    pytest_workers_row = next(
        row
        for row in range(6, config.max_row + 1)
        if config.cell(row, 1).value == "pytest_workers"
    )
    config.cell(pytest_workers_row, 2, 2)
    workbook.save(path)

    snapshot = _import(path)

    duplicate = next(
        issue for issue in snapshot.validation_issues if issue.code == "ID_DUPLICATE"
    )
    conflict = next(
        issue
        for issue in snapshot.validation_issues
        if issue.code == "CONFIG_VALUE_INVALID"
        and issue.field == "pytest_workers"
    )
    assert (duplicate.sheet, duplicate.row, duplicate.column) == ("Cases", 7, "A")
    assert (conflict.sheet, conflict.row, conflict.column) == (
        "Config",
        pytest_workers_row,
        "B",
    )


def test_missing_fixture_dependency_is_located(tmp_path: Path) -> None:
    path = build_sample_workbook(tmp_path / "missing-dependency.xlsx")
    workbook = load_workbook(path)
    workbook["Fixtures"]["F7"] = "FX-NOT-FOUND"
    workbook.save(path)

    snapshot = _import(path)

    missing = next(
        issue
        for issue in snapshot.validation_issues
        if issue.code == "FIXTURE_DEPENDENCY_MISSING"
    )
    assert (missing.sheet, missing.row, missing.column) == ("Fixtures", 7, "F")
