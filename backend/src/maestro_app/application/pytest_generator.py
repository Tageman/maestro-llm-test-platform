from __future__ import annotations

import json
import re
import yaml
from pathlib import Path

from maestro_app.application.ports import PytestPackage, RunRepositoryPort
from maestro_app.application.startup_policy import explicit_startup_flows
from maestro_app.domain.enums import FixturePhase
from maestro_app.domain.fixture_graph import FixtureDependencyResolver
from maestro_app.domain.models import (
    DevicePreparation,
    ProjectConfig,
    Run,
    WorkbookSnapshot,
)


class GeneratedPytestPackageBuilder:
    """Builds a deterministic pytest package for one immutable Run."""

    def __init__(
        self,
        repository: RunRepositoryPort,
        maestro_startup_grace_seconds: float = 180.0,
    ) -> None:
        self.repository = repository
        self.maestro_startup_grace_seconds = maestro_startup_grace_seconds

    def generate(
        self,
        *,
        run: Run,
        snapshot: WorkbookSnapshot,
        flow_paths: dict[str, Path],
        source_workbook: Path,
    ) -> PytestPackage:
        root = self.repository.initialize(run.run_id)
        self.repository.copy_file(
            run.run_id,
            f"source/{snapshot.source_filename}",
            source_workbook,
        )

        fixtures = {item.fixture_id: item for item in snapshot.fixtures if item.enabled}
        cases = {
            item.case_id: item
            for item in snapshot.cases
            if item.enabled and item.case_id in run.selected_case_ids
        }
        resolver = FixtureDependencyResolver(fixtures.values())
        if resolver.validate():
            raise ValueError("Fixture dependency graph/scope is invalid")
        shared = any(fixtures[key].scope.value != "function" for key in flow_paths if key in fixtures)

        copied_paths: dict[str, Path] = {}
        for flow_id, source in sorted(flow_paths.items()):
            if flow_id not in fixtures and flow_id not in cases:
                continue
            kind = "fixtures" if flow_id in fixtures else "cases"
            copied_paths[flow_id] = self.repository.copy_file(
                run.run_id,
                f"generated/{kind}/{flow_id}.yaml",
                source,
            )
            self.repository.copy_file(
                run.run_id,
                f"generated/initial/{kind}/{flow_id}.yaml",
                source,
            )

        names = self._python_names([*fixtures, *cases])
        lines = [
            "from __future__ import annotations",
            "",
            "import pytest",
            "",
            "from maestro_app.infrastructure.pytest_runtime import MaestroPytestContext",
            "",
            "",
            '@pytest.fixture(scope="session")',
            "def maestro_context() -> MaestroPytestContext:",
            "    return MaestroPytestContext.from_environment()",
            "",
        ]

        for fixture_id, fixture in sorted(
            fixtures.items(), key=lambda item: (item[1].order, item[0])
        ):
            phase = "setup" if fixture.phase == FixturePhase.SETUP else "teardown"
            lines.extend(
                [
                    "",
                    f'@pytest.fixture(scope="{fixture.scope.value}")',
                    f"def {names[fixture_id]}(maestro_context: MaestroPytestContext):",
                ]
            )
            if phase == "setup":
                lines.extend(
                    [
                        f'    maestro_context.execute_fixture("{fixture_id}", phase="setup", scope="{fixture.scope.value}")',
                        f'    yield "{fixture_id}"',
                    ]
                )
            else:
                lines.extend(
                    [
                        f'    yield "{fixture_id}"',
                        f'    maestro_context.execute_fixture("{fixture_id}", phase="teardown", scope="{fixture.scope.value}")',
                    ]
                )

        fixture_lines = list(lines)
        module_lines: dict[str, list[str]] = {}
        module_files: dict[str, str] = {}
        case_node_ids: dict[str, str] = {}
        plans: dict[str, dict] = {}
        node_ids: list[str] = []
        startup_plans: dict[str, dict] = {}
        system_flow_id = "SYS-DEFAULT-LAUNCH"
        while system_flow_id in copied_paths:
            system_flow_id += "-SYSTEM"
        for case_id in run.selected_case_ids:
            case = cases[case_id]
            if shared:
                module_files.setdefault(case.module, f"test_module_{len(module_files):03d}.py")
                lines = module_lines.setdefault(case.module, ["import pytest", "from maestro_app.infrastructure.pytest_runtime import MaestroPytestContext"])
            setup_plan = resolver.resolve(
                case.pre_fixture_ids, phase=FixturePhase.SETUP
            )
            teardown_plan = resolver.resolve(
                case.post_fixture_ids, phase=FixturePhase.TEARDOWN
            )
            explicit = explicit_startup_flows([*setup_plan, case_id], copied_paths)
            if shared:
                for flow_id in explicit:
                    scope = fixtures[flow_id].scope.value if flow_id in fixtures else "function"
                    if scope == "function" or (scope == "module" and any(fixtures[key].scope.value == "session" for key in flow_paths if key in fixtures)):
                        raise ValueError("共享作用域不能被 Case/短作用域启动或清状态步骤重置；请将启动夹具提升至最宽作用域")
            plans[case_id] = {"module": case.module, "fixtures": {key: {"scope": fixtures[key].scope.value, "phase": fixtures[key].phase.value} for key in [*setup_plan, *teardown_plan]}}
            startup_plans[case_id] = {
                "origin": "Config.launch_clear_state", "policy": "per_shared_epoch_explicit_startup_wins" if shared else "per_attempt_explicit_startup_wins",
                "enabled": not explicit, "explicit_flow_ids": explicit,
                "flow_id": system_flow_id, "clear_state": snapshot.config.launch_clear_state,
            }
            lifecycle_name = f"lifecycle_{names[case_id]}"
            lines.extend(
                [
                    "",
                    "",
                    '@pytest.fixture(scope="function")',
                    f"def {lifecycle_name}(request, maestro_context: MaestroPytestContext):",
                    f'    maestro_context.case_started("{case_id}")',
                    f'    request.addfinalizer(lambda: maestro_context.case_finished("{case_id}"))',
                ]
            )
            # Register teardown fixtures before setup starts. pytest will finalize
            # them even when a later setup fixture fails, in reverse request order.
            for fixture_id in teardown_plan:
                lines.append(f'    request.getfixturevalue("{names[fixture_id]}")')
            lines.append(f'    maestro_context.bootstrap("{case_id}")')
            for fixture_id in setup_plan:
                lines.append(f'    request.getfixturevalue("{names[fixture_id]}")')
            lines.extend(
                [
                    "    yield",
                    "",
                    f'@pytest.mark.case_id("{case_id}")',
                    f"def test_{names[case_id]}({lifecycle_name}, maestro_context: MaestroPytestContext):",
                    f'    maestro_context.execute("{case_id}", entity_type="case", phase="case", case_id="{case_id}")',
                ]
            )
            filename = module_files[case.module] if shared else "test_generated.py"
            case_node_ids[case_id] = f"generated/pytest/{filename}::test_{names[case_id]}"
            node_ids.append(case_node_ids[case_id])

        if shared and len({tuple(plan["explicit_flow_ids"]) for plan in startup_plans.values()}) > 1:
            raise ValueError("共享 Run 的所有 Case 必须引用一致的最宽作用域启动夹具，避免中途重启破坏共享状态")
        if any(plan["enabled"] for plan in startup_plans.values()):
            header = yaml.safe_dump({"appId": snapshot.config.app_id, "name": system_flow_id}, sort_keys=False)
            commands = yaml.safe_dump([{"launchApp": {"clearState": snapshot.config.launch_clear_state, "stopApp": True}}], sort_keys=False)
            copied_paths[system_flow_id] = self.repository.write_text_atomic(
                run.run_id, "generated/system/default-launch.yaml", header + "---\n" + commands,
            )
        if shared:
            self.repository.write_text_atomic(run.run_id, "generated/pytest/conftest.py", "\n".join(fixture_lines) + "\n")
            for module, contents in module_lines.items():
                self.repository.write_text_atomic(run.run_id, "generated/pytest/" + module_files[module], "\n".join(contents) + "\n")
            lines = ["# Shared-scope cases live in per-module files; see mappings/pytest.json."]
        test_file = self.repository.write_text_atomic(
            run.run_id,
            "generated/pytest/test_generated.py",
            "\n".join(lines) + "\n",
        )
        self.repository.write_text_atomic(
            run.run_id,
            "pytest.ini",
            "[pytest]\nmarkers =\n    case_id(value): stable Excel Case ID\n",
        )
        mapping = {
            "schema_version": "1.0",
            "run_id": run.run_id,
            "source_sha256": snapshot.source_sha256,
            "node_ids": node_ids,
            "python_names": names,
            "startup_plans": startup_plans,
            "shared_scopes": shared,
            "case_node_ids": case_node_ids,
            "case_plans": plans,
            "flow_paths": {
                key: str(path.relative_to(root)) for key, path in copied_paths.items()
            },
        }
        self.repository.write_json_atomic(
            run.run_id, "generated/mappings/pytest.json", mapping
        )
        config_path = self.repository.write_json_atomic(
            run.run_id,
            "generated/pytest/runtime.json",
            {"configured": False, "flow_paths": mapping["flow_paths"], "startup_plans": startup_plans, "shared_scopes": shared, "case_plans": plans},
        )
        return PytestPackage(
            test_file=test_file,
            config_path=config_path,
            collection_path=root / "reports" / "pytest-collection.txt",
            junit_path=root / "reports" / "pytest-junit.xml",
            trace_path=root / "reports" / "flow-trace.jsonl",
            stdout_path=root / "artifacts" / "logs" / "pytest.log",
            node_ids=tuple(node_ids),
        )

    def configure(
        self,
        package: PytestPackage,
        *,
        config: ProjectConfig,
        device: DevicePreparation,
        run_dir: Path,
        attempt_root: Path | None = None,
    ) -> None:
        mapping = json.loads(package.config_path.read_text(encoding="utf-8"))
        mapping.update(
            {
                "configured": True,
                "maestro_command": config.maestro_command,
                "device_id": device.device_id,
                "timeout_seconds": config.test_timeout_ms / 1000,
                "startup_timeout_seconds": self.maestro_startup_grace_seconds,
                "run_dir": str(run_dir),
                "attempt_root": str(attempt_root or run_dir),
                "trace_path": str(package.trace_path),
            }
        )
        self.repository.write_json_atomic(
            run_dir.name,
            str(package.config_path.relative_to(run_dir)),
            mapping,
        )

    @staticmethod
    def _python_names(ids: list[str]) -> dict[str, str]:
        used: set[str] = set()
        result: dict[str, str] = {}
        for original in ids:
            base = re.sub(r"[^a-zA-Z0-9_]", "_", original).lower()
            if not base or base[0].isdigit():
                base = f"id_{base}"
            candidate = base
            ordinal = 2
            while candidate in used:
                candidate = f"{base}_{ordinal}"
                ordinal += 1
            used.add(candidate)
            result[original] = candidate
        return result
