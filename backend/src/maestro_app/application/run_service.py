from __future__ import annotations

import json
import html
import re
import threading
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from maestro_app.application.errors import ResourceNotFound, StateConflict
from maestro_app.application.failure_classifier import (
    FailureClassification,
    FailureClassifier,
    FailureEvidence,
)
from maestro_app.application.locator_repair import ControlledYamlSelectorRepairer
from maestro_app.application.ports import (
    DeviceManagerPort,
    GenerationRepositoryPort,
    PytestGeneratorPort,
    PytestPackage,
    PytestRunnerPort,
    RunRepositoryPort,
    WorkbookRepositoryPort,
)
from maestro_app.domain.enums import (
    CaseRunState,
    FailureType,
    GenerationStatus,
    RunState,
    Severity,
)
from maestro_app.domain.models import (
    Attempt,
    CaseRun,
    CaseRunDetail,
    CreateRunRequest,
    Run,
    RunEvent,
    RepairRecord,
    RunSummary,
)
from maestro_app.domain.state_machine import RunStateMachine, TERMINAL_STATES


class RunService:
    def __init__(
        self,
        workbook_repository: WorkbookRepositoryPort,
        generation_repository: GenerationRepositoryPort,
        run_repository: RunRepositoryPort,
        pytest_generator: PytestGeneratorPort,
        device_manager: DeviceManagerPort,
        pytest_runner: PytestRunnerPort,
        *,
        diagnostic_service: Any | None = None,
        syntax_checker: Any | None = None,
        result_writer: Any | None = None,
        failure_classifier: FailureClassifier | None = None,
        selector_repairer: ControlledYamlSelectorRepairer | None = None,
        background: bool = True,
        maestro_startup_grace_seconds: float = 180.0,
    ) -> None:
        self.workbook_repository = workbook_repository
        self.generation_repository = generation_repository
        self.run_repository = run_repository
        self.pytest_generator = pytest_generator
        self.device_manager = device_manager
        self.pytest_runner = pytest_runner
        self.diagnostic_service = diagnostic_service
        self.syntax_checker = syntax_checker
        self.result_writer = result_writer
        self.failure_classifier = failure_classifier or FailureClassifier()
        self.selector_repairer = selector_repairer or ControlledYamlSelectorRepairer()
        self.background = background
        self.maestro_startup_grace_seconds = maestro_startup_grace_seconds
        self._active_run_id: str | None = None
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def create(self, request: CreateRunRequest) -> RunSummary:
        generation = self.generation_repository.get_summary(request.generation_id)
        if generation.status != GenerationStatus.READY:
            raise StateConflict(
                "GENERATION_NOT_READY",
                "只有 ready Generation 可以创建 Run",
            )
        snapshot = self.workbook_repository.get(generation.workbook_id)
        if snapshot.config is None or any(
            issue.severity == Severity.ERROR for issue in snapshot.validation_issues
        ):
            raise StateConflict(
                "WORKBOOK_VALIDATION_FAILED", "工作簿当前包含阻断错误"
            )
        available = {
            case.case_id: case
            for case in snapshot.cases
            if case.enabled
            and any(flow.flow_id == case.case_id for flow in generation.flows)
        }
        selected = request.case_ids or list(available)
        missing = [case_id for case_id in selected if case_id not in available]
        if missing:
            raise StateConflict(
                "CASE_SELECTION_INVALID",
                "选择了未生成、已停用或不存在的 Case",
                [{"case_id": value} for value in missing],
            )
        if not selected:
            raise StateConflict("CASE_SELECTION_EMPTY", "至少选择一个 Case")

        with self._lock:
            if self._active_run_id is not None:
                try:
                    active = self.run_repository.get_run(self._active_run_id)
                except Exception:
                    active = None
                if active is not None and active.state not in TERMINAL_STATES:
                    raise StateConflict(
                        "RUN_ALREADY_ACTIVE",
                        f"已有活动 Run {active.run_id}",
                    )
                self._active_run_id = None
            run_id = self._new_run_id()
            now = datetime.now(UTC)
            run = Run(
                run_id=run_id,
                generation_id=generation.generation_id,
                workbook_id=snapshot.workbook_id,
                mode=generation.mode,
                created_at=now,
                updated_at=now,
                selected_case_ids=selected,
                config_snapshot=snapshot.config,
                app_id=snapshot.config.app_id,
                case_runs=[
                    CaseRun(
                        case_id=case_id,
                        fixture_plan=snapshot.fixture_plans.get(case_id, []),
                    )
                    for case_id in selected
                ],
            )
            self.run_repository.initialize(run_id)
            self.run_repository.save_run(run)
            run, _ = self.run_repository.append_event(
                run,
                event_type="run.created",
                entity_type="run",
                entity_id=run_id,
                state=RunState.CREATED.value,
                message="Run 已创建",
                data={"generation_id": generation.generation_id},
            )
            cancel_event = threading.Event()
            self._cancel_events[run_id] = cancel_event
            self._active_run_id = run_id

        if self.background:
            worker = threading.Thread(
                target=self._execute_guarded,
                args=(run_id, cancel_event),
                name=f"run-{run_id}",
                daemon=True,
            )
            worker.start()
        else:
            self._execute_guarded(run_id, cancel_event)
        return RunSummary.from_run(self.run_repository.get_run(run_id))

    def get(self, run_id: str) -> RunSummary:
        return RunSummary.from_run(self.run_repository.get_run(run_id))

    def get_case(self, run_id: str, case_id: str) -> CaseRunDetail:
        run = self.run_repository.get_run(run_id)
        for case in run.case_runs:
            if case.case_id == case_id:
                return CaseRunDetail(
                    **case.model_dump(),
                    repairs=[item for item in run.repairs if item.case_id == case_id],
                    artifacts=[item for item in run.artifacts if item.case_id == case_id],
                )
        raise ResourceNotFound("case run", case_id)

    def events(self, run_id: str, after: int = 0) -> list[RunEvent]:
        return self.run_repository.list_events(run_id, after)

    def get_artifact(self, run_id: str, artifact_id: str):
        return self.run_repository.artifact_path(run_id, artifact_id)

    def get_result_workbook(self, run_id: str) -> Path:
        return self.run_repository.result_workbook_path(run_id)

    def cancel(self, run_id: str) -> RunSummary:
        run = self.run_repository.get_run(run_id)
        if run.state in TERMINAL_STATES:
            return RunSummary.from_run(run)
        run = run.model_copy(
            update={"cancel_requested": True, "updated_at": datetime.now(UTC)}
        )
        self.run_repository.save_run(run)
        cancel_event = self._cancel_events.get(run_id)
        if cancel_event is not None:
            cancel_event.set()
        self.pytest_runner.cancel(run_id)
        run, _ = self.run_repository.append_event(
            run,
            event_type="run.cancel_requested",
            entity_type="run",
            entity_id=run_id,
            state=run.state.value,
            message="收到安全终止请求",
        )
        return RunSummary.from_run(run)

    def _execute_guarded(
        self, run_id: str, cancel_event: threading.Event
    ) -> None:
        try:
            self._execute(run_id, cancel_event)
        except Exception as exc:
            run = self.run_repository.get_run(run_id)
            if run.state not in TERMINAL_STATES:
                target = self._failure_state(run.state)
                try:
                    run = self._transition(run, target, f"Run 失败：{exc}")
                except Exception:
                    # Preserve the original error even if persistence is impaired.
                    run = run.model_copy(
                        update={
                            "state": target,
                            "terminal_reason": str(exc),
                            "ended_at": datetime.now(UTC),
                            "updated_at": datetime.now(UTC),
                        }
                    )
                    self.run_repository.save_run(run)
        finally:
            with self._lock:
                if self._active_run_id == run_id:
                    self._active_run_id = None
                self._cancel_events.pop(run_id, None)

    def _execute(self, run_id: str, cancel_event: threading.Event) -> None:
        run = self.run_repository.get_run(run_id)
        run = self._transition(run, RunState.VALIDATING, "校验 Run 输入快照")
        snapshot = self.workbook_repository.get(run.workbook_id)
        config = snapshot.config
        if config is None:
            raise RuntimeError("工作簿缺少有效 Config")
        if cancel_event.is_set():
            self._transition(run, RunState.CANCELLED, "Run 已取消")
            return

        run = self._transition(run, RunState.GENERATING, "生成 pytest 执行包")
        generation = self.generation_repository.get_summary(run.generation_id)
        required_ids = set(run.selected_case_ids)
        for case_id in run.selected_case_ids:
            required_ids.update(snapshot.fixture_plans.get(case_id, []))
        flow_paths = {
            flow_id: self.generation_repository.final_yaml_path(
                run.generation_id, flow_id
            )
            for flow_id in sorted(required_ids)
        }
        package = self.pytest_generator.generate(
            run=run,
            snapshot=snapshot,
            flow_paths=flow_paths,
            source_workbook=self.workbook_repository.source_path(run.workbook_id),
        )
        collection = self.pytest_runner.collect(package)
        if not collection.succeeded:
            raise RuntimeError(
                "pytest 收集失败：" + collection.stdout_tail[-4000:]
            )
        collected = self._collection_node_ids(package, collection.stdout_tail)
        if set(collected) != set(package.node_ids):
            raise RuntimeError(
                f"pytest 收集项与 Case 不一致：expected={package.node_ids}, actual={collected}"
            )
        run = self.run_repository.get_run(run_id).model_copy(
            update={"pytest_node_ids": collected, "updated_at": datetime.now(UTC)}
        )
        self.run_repository.save_run(run)
        run = self._transition(run, RunState.READY, "pytest 执行包已就绪")
        if cancel_event.is_set():
            self._transition(run, RunState.CANCELLED, "Run 已取消")
            return

        run = self._transition(run, RunState.PREPARING_DEVICE, "准备 Android 模拟器")
        device = self.device_manager.prepare(config)
        self.run_repository.write_json_atomic(
            run_id, "artifacts/device-preparation.json", device.model_dump(mode="json")
        )
        run = self.run_repository.get_run(run_id).model_copy(
            update={
                "device_id": device.device_id,
                "avd_name": device.avd_name,
                "app_id": device.app_id,
                "started_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        )
        self.run_repository.save_run(run)
        if cancel_event.is_set():
            self._transition(run, RunState.CANCELLED, "Run 已取消")
            return

        run = self._transition(run, RunState.RUNNING, "pytest 开始执行 Maestro Flow")
        root = self.run_repository.run_dir(run_id)
        whole_run_timeout = (
            (config.test_timeout_ms / 1000 + self.maestro_startup_grace_seconds)
            * max(1, len(flow_paths))
            + 60
        )
        mapping = json.loads(
            (root / "generated/mappings/pytest.json").read_text(encoding="utf-8")
        )
        python_names = mapping["python_names"]
        results: list[dict[str, Any]] = []

        for case_id in run.selected_case_ids:
            node_id = (
                "generated/pytest/test_generated.py::test_"
                + python_names[case_id]
            )
            ordinal = 1
            while ordinal <= config.max_total_run_attempts:
                attempt_package = self._attempt_package(
                    package, root, case_id, ordinal, node_id
                )
                self.pytest_generator.configure(
                    attempt_package,
                    config=config,
                    device=device,
                    run_dir=root,
                    attempt_root=attempt_package.junit_path.parents[1],
                )
                trace_position = 0

                def publish_trace() -> None:
                    nonlocal trace_position
                    trace_position = self._publish_trace(
                        run_id, attempt_package, trace_position
                    )

                current = self.run_repository.get_run(run_id)
                current, _ = self.run_repository.append_event(
                    current,
                    event_type="attempt.started",
                    entity_type="case",
                    entity_id=case_id,
                    state=CaseRunState.RUNNING.value,
                    message=f"{case_id} 第 {ordinal} 次执行",
                    data={"attempt_id": f"{case_id}-a{ordinal}"},
                )
                result = self.pytest_runner.run(
                    run_id,
                    attempt_package,
                    timeout_seconds=whole_run_timeout,
                    cancel_event=cancel_event,
                    on_tick=publish_trace,
                )
                publish_trace()
                run = self.run_repository.get_run(run_id)
                run = self._apply_case_results(
                    run,
                    attempt_package,
                    result,
                    target_case_ids={case_id},
                )
                self.run_repository.save_run(run)
                artifact_ids = self._register_attempt_artifacts(
                    run_id, case_id, ordinal, attempt_package
                )
                run = self._attach_attempt_artifacts(
                    self.run_repository.get_run(run_id),
                    case_id,
                    ordinal,
                    artifact_ids,
                )
                self.run_repository.save_run(run)
                attempt = self._case(run, case_id).attempts[-1]
                run, _ = self.run_repository.append_event(
                    run,
                    event_type="attempt.finished",
                    entity_type="case",
                    entity_id=case_id,
                    state=attempt.state.value,
                    message=f"{case_id} 第 {ordinal} 次执行结束：{attempt.state.value}",
                    data={
                        "attempt_id": attempt.attempt_id,
                        "failure_type": (
                            attempt.failure_type.value if attempt.failure_type else None
                        ),
                        "artifact_ids": artifact_ids,
                    },
                )
                results.append(
                    {
                        "case_id": case_id,
                        "ordinal": ordinal,
                        "returncode": result.returncode,
                        "timed_out": result.timed_out,
                        "cancelled": result.cancelled,
                        "output_truncated": result.output_truncated,
                        "output_path": str(result.output_path.relative_to(root)),
                    }
                )
                if result.cancelled or cancel_event.is_set():
                    break
                if attempt.state == CaseRunState.PASSED:
                    break
                repairs_for_case = sum(
                    item.case_id == case_id
                    for item in self.run_repository.get_run(run_id).repairs
                )
                if (
                    attempt.failure_type != FailureType.LOCATOR
                    or repairs_for_case >= config.max_locator_repair
                    or ordinal >= config.max_total_run_attempts
                ):
                    break
                repaired = self._diagnose_and_repair(
                    run_id=run_id,
                    case_id=case_id,
                    attempt=attempt,
                    config=config,
                    device_id=device.device_id,
                )
                if not repaired:
                    break
                ordinal += 1
            if cancel_event.is_set():
                break

        run = self.run_repository.get_run(run_id)
        run = self._transition(run, RunState.FINALIZING, "聚合 pytest 与 Maestro 结果")
        if config.result_writeback and self.result_writer is not None:
            workbook_evidence = self.result_writer.write(
                source_path=self.workbook_repository.source_path(run.workbook_id),
                result_dir=root / "result",
                snapshot=snapshot,
                run=run,
            )
            relative_result = str(workbook_evidence.path.relative_to(root))
            run = run.model_copy(
                update={
                    "result_workbook_path": relative_result,
                    "updated_at": datetime.now(UTC),
                }
            )
            self.run_repository.save_run(run)
            self.run_repository.write_json_atomic(
                run_id,
                "result/writeback-manifest.json",
                {
                    "source_sha256_before": workbook_evidence.source_sha256_before,
                    "source_sha256_after": workbook_evidence.source_sha256_after,
                    "output_sha256": workbook_evidence.output_sha256,
                    "verified_rows": workbook_evidence.verified_rows,
                    "relative_path": relative_result,
                },
            )
            self.run_repository.register_artifact(
                run_id,
                relative_result,
                kind="result_workbook",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            run = self.run_repository.get_run(run_id)

        if cancel_event.is_set():
            run = self._transition(run, RunState.CANCELLED, "Run 已安全终止")
        elif all(item.state == CaseRunState.PASSED for item in run.case_runs):
            run = self._transition(run, RunState.COMPLETED, "全部 Case 通过")
        else:
            run = self._transition(
                run, RunState.COMPLETED_WITH_FAILURES, "存在失败或阻断 Case"
            )
        report_path = self._write_html_report(run)
        self.run_repository.register_artifact(
            run_id,
            str(report_path.relative_to(root)),
            kind="html_report",
            media_type="text/html",
        )
        run = self.run_repository.get_run(run_id)
        summary_path = self.run_repository.write_json_atomic(
            run_id,
            "result/summary.json",
            {
                "run": run.model_dump(mode="json"),
                "pytest_attempts": results,
            },
        )
        self.run_repository.register_artifact(
            run_id,
            str(summary_path.relative_to(root)),
            kind="summary",
            media_type="application/json",
        )

    def _write_html_report(self, run: Run) -> Path:
        def escaped(value: object | None) -> str:
            return html.escape("—" if value is None else str(value))

        case_sections: list[str] = []
        for case in run.case_runs:
            attempts = "".join(
                "<tr>"
                f"<td>A{attempt.ordinal}</td><td>{escaped(attempt.state.value)}</td>"
                f"<td>{escaped(attempt.failure_type.value if attempt.failure_type else None)}</td>"
                f"<td>{escaped(attempt.failed_step)}</td><td>{escaped(attempt.failed_selector)}</td>"
                f"<td>{escaped(attempt.exit_code)}</td><td>{len(attempt.artifact_ids)}</td>"
                "</tr>"
                for attempt in case.attempts
            )
            repairs = [item for item in run.repairs if item.case_id == case.case_id]
            repair_rows = "".join(
                "<li>"
                f"<code>{escaped(item.before_selector)}</code> → "
                f"<code>{escaped(item.after_selector)}</code> · {escaped(item.reason)}"
                "</li>"
                for item in repairs
            ) or "<li>无自动修复</li>"
            case_sections.append(
                "<section>"
                f"<h2>{escaped(case.case_id)} <span>{escaped(case.state.value)}</span></h2>"
                "<table><thead><tr><th>尝试</th><th>状态</th><th>失败类型</th>"
                "<th>失败步骤</th><th>Selector</th><th>退出码</th><th>证据数</th>"
                f"</tr></thead><tbody>{attempts}</tbody></table>"
                f"<h3>受控修复</h3><ul>{repair_rows}</ul>"
                "</section>"
            )
        artifact_rows = "".join(
            "<tr>"
            f"<td>{escaped(item.kind)}</td><td>{escaped(item.case_id)}</td>"
            f"<td><a href=\"../{escaped(item.relative_path)}\">{escaped(item.relative_path)}</a></td>"
            f"<td><code>{escaped(item.sha256)}</code></td>"
            "</tr>"
            for item in run.artifacts
        )
        document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>M3 Run {escaped(run.run_id)}</title><style>
body{{font:14px/1.55 Inter,system-ui,sans-serif;margin:0;background:#f3f0e8;color:#17211c}}
main{{max-width:1180px;margin:auto;padding:40px}}header{{border-bottom:3px solid #17211c;padding-bottom:20px}}
h1{{font-size:34px;margin:0}}header p{{color:#56615b}}section{{background:#fff;margin:22px 0;padding:22px;border:1px solid #c8cdc9}}
h2{{display:flex;justify-content:space-between;margin-top:0}}h2 span{{font-size:13px;background:#17211c;color:#fff;padding:5px 9px}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;border-bottom:1px solid #d9dedb;padding:8px;vertical-align:top}}
th{{font-size:11px;letter-spacing:.08em;color:#59645e}}code{{font-family:ui-monospace,monospace;word-break:break-all}}
a{{color:#106246}}.meta{{display:flex;gap:24px;flex-wrap:wrap}}.meta b{{display:block}}
</style></head><body><main><header><small>M3 / UNATTENDED EVIDENCE REPORT</small>
<h1>{escaped(run.run_id)}</h1><p>{escaped(run.terminal_reason)}</p>
<div class="meta"><div>状态<b>{escaped(run.state.value)}</b></div><div>设备<b>{escaped(run.device_id)}</b></div>
<div>AVD<b>{escaped(run.avd_name)}</b></div><div>APP<b>{escaped(run.app_id)}</b></div><div>修复数<b>{len(run.repairs)}</b></div></div></header>
{''.join(case_sections)}
<section><h2>产物账本 <span>{len(run.artifacts)} FILES</span></h2><table><thead><tr><th>类型</th><th>Case</th><th>路径</th><th>SHA-256</th></tr></thead><tbody>{artifact_rows}</tbody></table></section>
</main></body></html>"""
        return self.run_repository.write_text_atomic(
            run.run_id, "result/report.html", document
        )

    def _transition(self, run: Run, target: RunState, message: str) -> Run:
        RunStateMachine(run.state).transition_to(target)
        now = datetime.now(UTC)
        update = {"state": target, "updated_at": now}
        if target in TERMINAL_STATES:
            update.update({"ended_at": now, "terminal_reason": message})
        updated = run.model_copy(update=update)
        self.run_repository.save_run(updated)
        updated, _ = self.run_repository.append_event(
            updated,
            event_type="run.state_changed",
            entity_type="run",
            entity_id=run.run_id,
            state=target.value,
            message=message,
        )
        return updated

    @staticmethod
    def _attempt_package(
        package: PytestPackage,
        root: Path,
        case_id: str,
        ordinal: int,
        node_id: str,
    ) -> PytestPackage:
        attempt_root = root / "attempts" / case_id / f"a{ordinal}"
        return replace(
            package,
            junit_path=attempt_root / "reports" / "pytest-junit.xml",
            trace_path=attempt_root / "reports" / "flow-trace.jsonl",
            stdout_path=attempt_root / "artifacts" / "logs" / "pytest.log",
            node_ids=(node_id,),
        )

    def _diagnose_and_repair(
        self,
        *,
        run_id: str,
        case_id: str,
        attempt: Attempt,
        config,
        device_id: str,
    ) -> bool:
        run = self.run_repository.get_run(run_id)
        run = self._transition(run, RunState.DIAGNOSING, f"诊断 {case_id} 定位失败")
        repair_id = f"repair-{case_id.lower()}-{len(run.repairs) + 1}"
        repair_root = self.run_repository.run_dir(run_id) / "repairs" / case_id / repair_id
        repair_root.mkdir(parents=True, exist_ok=True)
        if self.diagnostic_service is None or not attempt.failed_selector:
            self.run_repository.write_text_atomic(
                run_id,
                str((repair_root / "diagnostic-error.txt").relative_to(self.run_repository.run_dir(run_id))),
                "MCP diagnostic service or failed selector is unavailable\n",
            )
            self._transition(run, RunState.RUNNING, "定位证据不足，停止自动修复")
            return False
        try:
            diagnostic = self.diagnostic_service.diagnose(
                maestro_command=config.maestro_command,
                device_id=device_id,
                failed_selector=attempt.failed_selector,
                evidence_dir=repair_root / "evidence",
            )
            evidence_ids: list[str] = []
            for path in diagnostic.evidence_paths:
                kind = (
                    "screenshot"
                    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
                    else "hierarchy" if "hierarchy" in path.name else "mcp_evidence"
                )
                artifact = self.run_repository.register_artifact(
                    run_id,
                    str(path.relative_to(self.run_repository.run_dir(run_id))),
                    kind=kind,
                    media_type=None,
                    case_id=case_id,
                    attempt_id=attempt.attempt_id,
                )
                evidence_ids.append(artifact.artifact_id)
        except Exception as exc:
            error_path = self.run_repository.write_text_atomic(
                run_id,
                str((repair_root / "diagnostic-error.txt").relative_to(self.run_repository.run_dir(run_id))),
                f"{type(exc).__name__}: {exc}\n",
            )
            self.run_repository.register_artifact(
                run_id,
                str(error_path.relative_to(self.run_repository.run_dir(run_id))),
                kind="diagnostic_error",
                media_type="text/plain",
                case_id=case_id,
                attempt_id=attempt.attempt_id,
            )
            run = self.run_repository.get_run(run_id)
            self._transition(run, RunState.RUNNING, "MCP 诊断失败，停止自动修复")
            return False
        if not diagnostic.candidate:
            run = self.run_repository.get_run(run_id)
            self._transition(run, RunState.RUNNING, "没有唯一定位候选，停止自动修复")
            return False

        run = self.run_repository.get_run(run_id)
        run = self._transition(run, RunState.REPAIRING, f"生成 {case_id} 受控 Selector 补丁")
        try:
            yaml_path = self.run_repository.run_dir(run_id) / "generated" / "cases" / f"{case_id}.yaml"
            patch = self.selector_repairer.repair(
                yaml_path, attempt.failed_selector, diagnostic.candidate
            )
            before_path = self.run_repository.write_text_atomic(
                run_id,
                str((repair_root / "before.yaml").relative_to(self.run_repository.run_dir(run_id))),
                patch.before_yaml,
            )
            after_path = self.run_repository.write_text_atomic(
                run_id,
                str((repair_root / "after.yaml").relative_to(self.run_repository.run_dir(run_id))),
                patch.after_yaml,
            )
            diff_path = self.run_repository.write_text_atomic(
                run_id,
                str((repair_root / "selector.diff").relative_to(self.run_repository.run_dir(run_id))),
                patch.diff,
            )
            if self.syntax_checker is None:
                raise RuntimeError("Maestro syntax checker is unavailable")
            syntax = self.syntax_checker.check(
                after_path,
                maestro_command=config.maestro_command,
                timeout_seconds=min(60.0, config.test_timeout_ms / 1000),
            )
            syntax_path = self.run_repository.write_text_atomic(
                run_id,
                str((repair_root / "syntax-check.txt").relative_to(self.run_repository.run_dir(run_id))),
                syntax.output + ("\n" if not syntax.output.endswith("\n") else ""),
            )
            if not syntax.valid:
                raise RuntimeError("repaired YAML did not pass maestro check-syntax")
            self.run_repository.write_text_atomic(
                run_id,
                str(yaml_path.relative_to(self.run_repository.run_dir(run_id))),
                patch.after_yaml,
            )
            repair_artifacts: list[str] = []
            for path, kind, media in (
                (before_path, "repair_before_yaml", "application/yaml"),
                (after_path, "repair_after_yaml", "application/yaml"),
                (diff_path, "repair_diff", "text/x-diff"),
                (syntax_path, "syntax_check", "text/plain"),
            ):
                artifact = self.run_repository.register_artifact(
                    run_id,
                    str(path.relative_to(self.run_repository.run_dir(run_id))),
                    kind=kind,
                    media_type=media,
                    case_id=case_id,
                    attempt_id=attempt.attempt_id,
                )
                repair_artifacts.append(artifact.artifact_id)
            run = self.run_repository.get_run(run_id)
            record = RepairRecord(
                repair_id=repair_id,
                case_id=case_id,
                attempt_id=attempt.attempt_id,
                failure_type=FailureType.LOCATOR,
                evidence_artifact_ids=[*evidence_ids, *repair_artifacts],
                reason=diagnostic.reason,
                before_selector=patch.before_selector,
                after_selector=patch.after_selector,
                yaml_diff_path=str(diff_path.relative_to(self.run_repository.run_dir(run_id))),
            )
            case_runs: list[CaseRun] = []
            for case_run in run.case_runs:
                if case_run.case_id != case_id:
                    case_runs.append(case_run)
                    continue
                attempts = [
                    item.model_copy(update={"repair_id": repair_id})
                    if item.attempt_id == attempt.attempt_id
                    else item
                    for item in case_run.attempts
                ]
                case_runs.append(case_run.model_copy(update={"attempts": attempts}))
            run = run.model_copy(
                update={
                    "repairs": [*run.repairs, record],
                    "case_runs": case_runs,
                    "updated_at": datetime.now(UTC),
                }
            )
            self.run_repository.save_run(run)
            run, _ = self.run_repository.append_event(
                run,
                event_type="repair.created",
                entity_type="case",
                entity_id=case_id,
                state=RunState.REPAIRING.value,
                message=f"{case_id} 定位器修复：{patch.before_selector} → {patch.after_selector}",
                data=record.model_dump(mode="json"),
            )
            self._transition(run, RunState.RUNNING, "受控补丁通过语法检查，开始重试")
            return True
        except Exception as exc:
            error_path = self.run_repository.write_text_atomic(
                run_id,
                str((repair_root / "repair-error.txt").relative_to(self.run_repository.run_dir(run_id))),
                f"{type(exc).__name__}: {exc}\n",
            )
            self.run_repository.register_artifact(
                run_id,
                str(error_path.relative_to(self.run_repository.run_dir(run_id))),
                kind="repair_error",
                media_type="text/plain",
                case_id=case_id,
                attempt_id=attempt.attempt_id,
            )
            run = self.run_repository.get_run(run_id)
            self._transition(run, RunState.RUNNING, "受控补丁失败，停止自动修复")
            return False

    def _register_attempt_artifacts(
        self,
        run_id: str,
        case_id: str,
        ordinal: int,
        package: PytestPackage,
    ) -> list[str]:
        root = self.run_repository.run_dir(run_id)
        attempt_root = root / "attempts" / case_id / f"a{ordinal}"
        ids: list[str] = []
        for path in sorted(item for item in attempt_root.rglob("*") if item.is_file()):
            relative = str(path.relative_to(root))
            if path.name == "pytest-junit.xml":
                kind, media = "pytest_junit", "application/xml"
            elif path.suffix.lower() == ".xml":
                kind, media = "maestro_junit", "application/xml"
            elif path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                kind, media = "screenshot", None
            elif "screen-hierarchy" in path.parts:
                kind, media = "hierarchy", "application/json"
            elif path.suffix.lower() == ".log":
                kind, media = "log", "text/plain"
            elif path.name == "flow-trace.jsonl":
                kind, media = "trace", "application/x-ndjson"
            else:
                kind, media = "maestro_artifact", None
            artifact = self.run_repository.register_artifact(
                run_id,
                relative,
                kind=kind,
                media_type=media,
                case_id=case_id,
                attempt_id=f"{case_id}-a{ordinal}",
            )
            ids.append(artifact.artifact_id)
        return ids

    @staticmethod
    def _case(run: Run, case_id: str) -> CaseRun:
        return next(item for item in run.case_runs if item.case_id == case_id)

    @staticmethod
    def _attach_attempt_artifacts(
        run: Run, case_id: str, ordinal: int, artifact_ids: list[str]
    ) -> Run:
        updated: list[CaseRun] = []
        for case_run in run.case_runs:
            if case_run.case_id != case_id:
                updated.append(case_run)
                continue
            attempts = [
                item.model_copy(update={"artifact_ids": artifact_ids})
                if item.ordinal == ordinal
                else item
                for item in case_run.attempts
            ]
            updated.append(case_run.model_copy(update={"attempts": attempts}))
        return run.model_copy(
            update={"case_runs": updated, "updated_at": datetime.now(UTC)}
        )

    def _publish_trace(
        self, run_id: str, package: PytestPackage, position: int
    ) -> int:
        if not package.trace_path.is_file():
            return position
        with package.trace_path.open(encoding="utf-8") as source:
            source.seek(position)
            lines = source.readlines()
            new_position = source.tell()
        run = self.run_repository.get_run(run_id)
        for line in lines:
            payload = json.loads(line)
            run, _ = self.run_repository.append_event(
                run,
                event_type=f"execution.{payload.get('event', 'event')}",
                entity_type=str(payload.get("entity_type", "flow")),
                entity_id=str(payload.get("entity_id", "unknown")),
                state=None,
                message=(
                    f"{payload.get('phase', 'flow')} {payload.get('event', 'event')}: "
                    f"{payload.get('entity_id', 'unknown')}"
                ),
                data=payload,
            )
        return new_position

    def _apply_case_results(
        self,
        run: Run,
        package: PytestPackage,
        result,
        *,
        target_case_ids: set[str] | None = None,
    ) -> Run:
        traces = self._read_traces(package.trace_path)
        junit = self._read_junit(package.junit_path)
        now = datetime.now(UTC)
        updated_cases: list[CaseRun] = []
        for case in run.case_runs:
            if target_case_ids is not None and case.case_id not in target_case_ids:
                updated_cases.append(case)
                continue
            related = [event for event in traces if event.get("case_id") == case.case_id]
            case_finish = next(
                (
                    event
                    for event in related
                    if event.get("entity_type") == "case"
                    and event.get("event") == "finished"
                ),
                None,
            )
            setup_failure = next(
                (
                    event
                    for event in related
                    if event.get("phase") == "setup"
                    and event.get("event") == "finished"
                    and not event.get("succeeded")
                ),
                None,
            )
            teardown_failures = [
                event
                for event in related
                if event.get("phase") == "teardown"
                and event.get("event") == "finished"
                and not event.get("succeeded")
            ]
            failure_event = next(
                (
                    event
                    for event in reversed(related)
                    if event.get("event") == "finished"
                    and event.get("entity_type") in {"case", "fixture"}
                    and not event.get("succeeded")
                ),
                None,
            )
            failure_output = result.stdout_tail
            if failure_event and failure_event.get("log_path"):
                log_path = (
                    self.run_repository.run_dir(run.run_id)
                    / str(failure_event["log_path"])
                )
                if log_path.is_file():
                    failure_output += "\n" + log_path.read_text(
                        encoding="utf-8", errors="replace"
                    )
            classification = self.failure_classifier.classify(
                FailureEvidence(
                    output=failure_output,
                    phase=(failure_event or {}).get("phase"),
                    timed_out=(
                        result.timed_out
                        or bool((failure_event or {}).get("timed_out"))
                    ),
                )
            )
            if (
                classification.failure_type == FailureType.LOCATOR
                and self._selector_is_assertion(
                    run.run_id,
                    str((failure_event or {}).get("entity_id", case.case_id)),
                    str((failure_event or {}).get("entity_type", "case")),
                    classification.selector,
                )
            ):
                classification = FailureClassification(
                    FailureType.ASSERTION,
                    "业务断言未满足",
                    selector=classification.selector,
                    failed_step=classification.failed_step,
                )
            if result.timed_out or classification.failure_type == FailureType.TIMEOUT:
                state = CaseRunState.TIMEOUT
                failure_type = FailureType.TIMEOUT
            elif setup_failure or teardown_failures:
                state = CaseRunState.FIXTURE_FAILED
                failure_type = FailureType.FIXTURE
            elif case_finish and case_finish.get("succeeded"):
                state = CaseRunState.PASSED
                failure_type = None
            elif case.case_id in junit:
                state = CaseRunState.FAILED
                failure_type = classification.failure_type
            else:
                state = CaseRunState.BLOCKED
                failure_type = classification.failure_type
            if failure_type == FailureType.ENVIRONMENT:
                state = CaseRunState.ENV_ERROR
            exits = [
                event.get("exit_code")
                for event in related
                if event.get("event") == "finished" and event.get("exit_code") is not None
            ]
            started_at = (
                case.started_at
                or (self._event_time(related[0]) if related else run.started_at)
            )
            ended_at = self._event_time(related[-1]) if related else now
            duration = (
                max(0.0, (ended_at - started_at).total_seconds())
                if started_at and ended_at
                else None
            )
            updated_cases.append(
                case.model_copy(
                    update={
                        "state": state,
                        "business_result": (
                            "passed" if state == CaseRunState.PASSED else "failed"
                        ),
                        "cleanup_result": (
                            "failed" if teardown_failures else "passed"
                        ),
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "duration_seconds": duration,
                        "attempts": [
                            *case.attempts,
                            Attempt(
                                attempt_id=f"{case.case_id}-a{len(case.attempts) + 1}",
                                ordinal=len(case.attempts) + 1,
                                state=state,
                                failure_type=failure_type,
                                failure_reason=(
                                    None
                                    if state == CaseRunState.PASSED
                                    else classification.reason
                                ),
                                failed_step=(
                                    classification.failed_step
                                    or self._selector_step(
                                        run.run_id,
                                        case.case_id,
                                        classification.selector,
                                    )
                                ),
                                failed_selector=classification.selector,
                                exit_code=(exits[-1] if exits else result.returncode),
                            )
                        ],
                    }
                )
            )
        return run.model_copy(
            update={"case_runs": updated_cases, "updated_at": datetime.now(UTC)}
        )

    def _selector_step(
        self, run_id: str, case_id: str, selector: str | None
    ) -> int | None:
        if not selector:
            return None
        path = self.run_repository.run_dir(run_id) / "generated" / "cases" / f"{case_id}.yaml"
        if not path.is_file():
            return None
        try:
            documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except yaml.YAMLError:
            return None
        if len(documents) != 2 or not isinstance(documents[1], list):
            return None
        action_ordinal = 0
        for command in documents[1]:
            if not isinstance(command, dict) or len(command) != 1:
                continue
            key, body = next(iter(command.items()))
            if key in {"assertVisible", "assertNotVisible"}:
                continue
            action_ordinal += 1
            value = body if isinstance(body, str) else None
            if isinstance(body, dict):
                value = body.get("text")
                if key == "scrollUntilVisible" and isinstance(body.get("element"), str):
                    value = body["element"]
            if value in {selector, re.escape(selector)}:
                return action_ordinal
        return None

    def _selector_is_assertion(
        self,
        run_id: str,
        flow_id: str,
        entity_type: str,
        selector: str | None,
    ) -> bool:
        if not selector:
            return False
        kind = "fixtures" if entity_type == "fixture" else "cases"
        path = self.run_repository.run_dir(run_id) / "generated" / kind / f"{flow_id}.yaml"
        if not path.is_file():
            return False
        try:
            documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except yaml.YAMLError:
            return False
        if len(documents) != 2 or not isinstance(documents[1], list):
            return False
        expected = {selector, re.escape(selector)}
        for command in documents[1]:
            if not isinstance(command, dict):
                continue
            for key in {"assertVisible", "assertNotVisible"}:
                body = command.get(key)
                value = body if isinstance(body, str) else None
                if isinstance(body, dict):
                    value = body.get("text")
                if value in expected:
                    return True
        return False

    @staticmethod
    def _collection_node_ids(
        package: PytestPackage, output: str
    ) -> list[str]:
        root = package.test_file.parents[2]
        expected_file = str(package.test_file.relative_to(root))
        collected: list[str] = []
        for line in output.splitlines():
            value = line.strip()
            if value.startswith(expected_file + "::"):
                collected.append(value)
        return collected

    @staticmethod
    def _read_traces(path: Path) -> list[dict]:
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    @staticmethod
    def _read_junit(path: Path) -> set[str]:
        if not path.is_file():
            return set()
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            return set()
        result: set[str] = set()
        for testcase in root.iter("testcase"):
            name = testcase.attrib.get("name", "")
            if name.startswith("test_"):
                result.add(name.removeprefix("test_").replace("_", "-").upper())
        return result

    @staticmethod
    def _event_time(event: dict) -> datetime:
        return datetime.fromisoformat(event["occurred_at"])

    @staticmethod
    def _failure_state(state: RunState) -> RunState:
        if state == RunState.VALIDATING:
            return RunState.VALIDATION_FAILED
        if state == RunState.GENERATING:
            return RunState.GENERATION_FAILED
        if state in {RunState.CREATED, RunState.AWAITING_REVIEW, RunState.READY}:
            return RunState.CANCELLED
        return RunState.FAILED

    @staticmethod
    def _new_run_id() -> str:
        return datetime.now(UTC).strftime("run-%Y%m%dT%H%M%S-") + uuid4().hex[:10]
