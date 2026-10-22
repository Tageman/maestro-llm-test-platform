from __future__ import annotations

import json
import stat
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maestro_app.application.pytest_generator import GeneratedPytestPackageBuilder
from maestro_app.core.config import Settings
from maestro_app.domain.enums import (
    FixturePhase,
    FixtureScope,
    RunMode,
    WorkbookStatus,
)
from maestro_app.domain.models import (
    DevicePreparation,
    FixtureDefinition,
    ProjectConfig,
    Run,
    SourceStep,
    TestCaseDefinition as CaseDefinition,
    WorkbookSnapshot,
)
from maestro_app.infrastructure.pytest_process import ManagedPytestRunner
from maestro_app.infrastructure.run_repository import RunRepository


def _step(text: str) -> list[SourceStep]:
    return [SourceStep(ordinal=1, text=text)]


def _fixture(
    fixture_id: str,
    phase: FixturePhase,
    order: int,
    dependencies: list[str] | None = None,
) -> FixtureDefinition:
    return FixtureDefinition(
        fixture_id=fixture_id,
        title=fixture_id,
        phase=phase,
        scope=FixtureScope.FUNCTION,
        dependency_ids=dependencies or [],
        order=order,
        steps=_step("点击【按钮】"),
        expected_results=_step("页面显示【完成】"),
        source_row=order,
    )


def _config(maestro: Path) -> ProjectConfig:
    return ProjectConfig(
        project_name="lifecycle",
        app_id="example.app",
        avd_name="Pixel_5",
        maestro_command=str(maestro),
        execution_target="android_emulator",
        output_dir=Path("./outputs"),
        test_timeout_ms=5000,
        max_syntax_repair=0,
        max_locator_repair=0,
        max_total_run_attempts=1,
        continue_on_failure=True,
        launch_clear_state=False,
        pytest_workers=1,
        result_writeback=False,
        language="zh-CN",
        fixture_id_separator=";",
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        maestro_command="maestro",
        adb_command="adb",
        emulator_command="emulator",
        app_id="example.app",
        runtime_dir=tmp_path,
        ir_schema_path=tmp_path / "schema.json",
        cors_origins=(),
        process_output_limit_chars=2000,
    )


def _fake_maestro(path: Path) -> Path:
    path.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

args = sys.argv[1:]
report = pathlib.Path(args[args.index('--output') + 1])
flow = pathlib.Path(args[-1])
report.parent.mkdir(parents=True, exist_ok=True)
report.write_text('<testsuite tests="1" failures="0"><testcase status="SUCCESS"/></testsuite>', encoding='utf-8')
if 'FAIL' in flow.read_text(encoding='utf-8'):
    print('injected failure for', flow.name)
    raise SystemExit(7)
print('passed', flow.name)
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _package(tmp_path: Path, failing_flow: str | None, *, clear_state=False, explicit_startup=False):
    maestro = _fake_maestro(tmp_path / "fake-maestro")
    config = _config(maestro).model_copy(update={"launch_clear_state": clear_state})
    fixtures = [
        _fixture("FX-RESET", FixturePhase.SETUP, 10),
        _fixture("FX-LOGIN", FixturePhase.SETUP, 20, ["FX-RESET"]),
        _fixture("FX-POST-A", FixturePhase.TEARDOWN, 30),
        _fixture("FX-POST-B", FixturePhase.TEARDOWN, 40, ["FX-POST-A"]),
    ]
    case = CaseDefinition(
        case_id="TC-HOME-001",
        module="home",
        title="home",
        pre_fixture_ids=["FX-LOGIN"],
        post_fixture_ids=["FX-POST-B"],
        priority="P0",
        steps=_step("点击【登录】按钮"),
        expected_results=_step("页面显示【首页】"),
        source_row=6,
    )
    snapshot = WorkbookSnapshot(
        workbook_id="wb-1",
        source_filename="source.xlsx",
        source_sha256="a" * 64,
        imported_at=datetime.now(UTC),
        status=WorkbookStatus.VALID,
        fixtures=fixtures,
        cases=[case],
        config=config,
        fixture_plans={
            case.case_id: [
                "FX-RESET",
                "FX-LOGIN",
                "FX-POST-B",
                "FX-POST-A",
            ]
        },
    )
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"immutable workbook")
    flow_paths: dict[str, Path] = {}
    for flow_id in [fixture.fixture_id for fixture in fixtures] + [case.case_id]:
        path = tmp_path / f"{flow_id}.yaml"
        path.write_text("FAIL" if flow_id == failing_flow else "PASS", encoding="utf-8")
        if explicit_startup and flow_id == "FX-RESET":
            path.write_text("appId: example.app\n---\n- launchApp:\n    clearState: false\n")
        flow_paths[flow_id] = path
    run = Run(
        run_id=f"run-{failing_flow or 'success'}",
        generation_id="gen-1",
        workbook_id=snapshot.workbook_id,
        mode=RunMode.UNATTENDED,
        selected_case_ids=[case.case_id],
        config_snapshot=config,
    )
    repository = RunRepository(tmp_path)
    package = GeneratedPytestPackageBuilder(repository).generate(
        run=run,
        snapshot=snapshot,
        flow_paths=flow_paths,
        source_workbook=source,
    )
    GeneratedPytestPackageBuilder(repository).configure(
        package,
        config=config,
        device=DevicePreparation(
            device_id="emulator-5554",
            avd_name="Pixel_5",
            app_id=config.app_id,
            app_installed=True,
            boot_completed=True,
        ),
        run_dir=repository.run_dir(run.run_id),
    )
    return package


def _finished(package) -> list[str]:
    events = [
        json.loads(line)
        for line in package.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    return [
        event["entity_id"]
        for event in events
        if event["event"] == "finished" and event["entity_type"] in {"fixture", "case"}
    ]


@pytest.mark.parametrize(
    ("failing_flow", "expected", "returncode"),
    [
        (
            None,
            ["FX-RESET", "FX-LOGIN", "TC-HOME-001", "FX-POST-B", "FX-POST-A"],
            0,
        ),
        (
            "TC-HOME-001",
            ["FX-RESET", "FX-LOGIN", "TC-HOME-001", "FX-POST-B", "FX-POST-A"],
            1,
        ),
        (
            "FX-LOGIN",
            ["FX-RESET", "FX-LOGIN", "FX-POST-B", "FX-POST-A"],
            1,
        ),
    ],
)
def test_generated_pytest_lifecycle(
    tmp_path: Path,
    failing_flow: str | None,
    expected: list[str],
    returncode: int,
) -> None:
    package = _package(tmp_path, failing_flow)
    runner = ManagedPytestRunner(_settings(tmp_path))

    collection = runner.collect(package)
    result = runner.run(
        package.test_file.parents[2].name,
        package,
        timeout_seconds=30,
        cancel_event=threading.Event(),
    )

    assert collection.succeeded
    assert package.node_ids[0] in collection.stdout_tail
    assert result.returncode == returncode
    assert _finished(package) == ["SYS-DEFAULT-LAUNCH", *expected]


@pytest.mark.parametrize("clear_state", [True, False])
@pytest.mark.parametrize("explicit_startup", [True, False])
def test_global_startup_policy_preserves_explicit_fixture(tmp_path, clear_state, explicit_startup):
    import yaml
    package = _package(tmp_path, None, clear_state=clear_state, explicit_startup=explicit_startup)
    config = json.loads(package.config_path.read_text())
    plan = config["startup_plans"]["TC-HOME-001"]
    assert plan["enabled"] is not explicit_startup
    assert plan["clear_state"] is clear_state
    root = package.test_file.parents[2]
    if explicit_startup:
        assert plan["explicit_flow_ids"] == ["FX-RESET"]
        assert not (root / "generated/system/default-launch.yaml").exists()
        explicit = list(yaml.safe_load_all((root / "generated/fixtures/FX-RESET.yaml").read_text()))
        assert explicit[1][0]["launchApp"]["clearState"] is False
    else:
        generated = list(yaml.safe_load_all((root / "generated/system/default-launch.yaml").read_text()))
        assert generated[1][0]["launchApp"]["clearState"] is clear_state
    result = ManagedPytestRunner(_settings(tmp_path)).run(
        root.name, package, timeout_seconds=30, cancel_event=threading.Event(),
    )
    assert result.succeeded
    assert _finished(package).count("SYS-DEFAULT-LAUNCH") == (0 if explicit_startup else 1)


def test_global_startup_failure_still_runs_registered_cleanup(tmp_path):
    package = _package(tmp_path, None)
    (package.test_file.parents[2] / "generated/system/default-launch.yaml").write_text("FAIL")
    result = ManagedPytestRunner(_settings(tmp_path)).run(
        "run-success", package, timeout_seconds=30, cancel_event=threading.Event(),
    )
    assert not result.succeeded
    assert _finished(package) == ["SYS-DEFAULT-LAUNCH", "FX-POST-B", "FX-POST-A"]
