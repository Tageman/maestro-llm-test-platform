import json
from pathlib import Path

import pytest

from maestro_app.infrastructure.maestro_cli import MaestroFlowResult
from maestro_app.infrastructure.maestro_report import report_error
from maestro_app.infrastructure.pytest_runtime import MaestroPytestContext
from maestro_app.infrastructure.tool_probe import ProcessResult


@pytest.mark.parametrize("xml, valid", [
    (None, False),
    ("broken <xml", False),
    ("<html/>", False),
    ("<testsuites/>", False),
    ('<testsuite tests="1"/>', False),
    ('<testsuite><testcase><failure/></testcase></testsuite>', False),
    ('<testsuite><testcase><error/></testcase></testsuite>', False),
    ('<testsuite><testcase><skipped/></testcase></testsuite>', False),
    ('<testsuite failures="1"><testcase/></testsuite>', False),
    ('<testsuite errors="1"><testcase/></testsuite>', False),
    ('<testsuite skipped="1"><testcase/></testsuite>', False),
    ('<testsuite disabled="1"><testcase/></testsuite>', False),
    ('<testsuite tests="2"><testcase/></testsuite>', False),
    ('<testsuite failures="NaN"><testcase/></testsuite>', False),
    ('<testsuite failures="-1"><testcase/></testsuite>', False),
    ('<testsuite><testcase status="FAILED"/></testsuite>', False),
    ('<testsuite><testcase status="SKIPPED"/></testsuite>', False),
    ('<testsuite tests="1" failures="0"><testcase/></testsuite>', True),
    ('<testsuites><testsuite tests="1" failures="0"><testcase status="SUCCESS"/></testsuite></testsuites>', True),
])
def test_cli_and_pytest_require_valid_successful_report(tmp_path, monkeypatch, xml, valid):
    config = {
        "configured": True, "run_dir": str(tmp_path),
        "trace_path": str(tmp_path / "trace.jsonl"),
        "flow_paths": {"C": "flow.yaml"}, "maestro_command": "unused",
        "device_id": "emulator-synthetic", "timeout_seconds": 1,
    }
    # No subprocess or device: inject the precise external adapter response.
    def run(args, *unused):
        report = Path(args[args.index("--output") + 1])
        if xml is not None:
            report.write_text(xml, encoding="utf-8")
        return 0, False, None, ""

    monkeypatch.setattr(MaestroPytestContext, "current", None)
    context = MaestroPytestContext(config)
    monkeypatch.setattr(context, "_run_to_file", run)
    if valid:
        context.execute("C", entity_type="case", phase="case", case_id="C")
    else:
        with pytest.raises(AssertionError, match="Maestro JUnit"):
            context.execute("C", entity_type="case", phase="case", case_id="C")
    event = json.loads(context.trace_path.read_text().splitlines()[-1])
    assert event["succeeded"] is valid
    assert (event["report_error"] is None) is valid
    report = tmp_path / event["report_path"]
    assert MaestroFlowResult(ProcessResult(0), report, tmp_path).passed is valid
    assert not MaestroFlowResult(ProcessResult(1), report, tmp_path).passed


def test_unreadable_report_fails_closed(tmp_path):
    assert report_error(tmp_path) is not None
