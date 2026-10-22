"""pytest 8 protocol bridge; one session owns all module/session fixture caches.

The only private pytest API usage is isolated here and covered by subprocess
tests. Pin pytest <9 until its rerun/teardown protocol is revalidated.
"""
from __future__ import annotations

import json
import os
import time
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from _pytest.runner import runtestprotocol

from maestro_app.infrastructure.pytest_runtime import MaestroPytestContext


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


@pytest.hookimpl(tryfirst=True)
def pytest_runtestloop(session):
    queue_value = os.environ.get("MAESTRO_APP_SHARED_QUEUE")
    if not queue_value or session.config.option.collectonly:
        return None
    if session.testsfailed:
        raise RuntimeError("Shared pytest collection failed")
    if int(pytest.__version__.split(".")[0]) != 8:
        raise RuntimeError("Shared worker protocol requires validated pytest 8")
    queue = Path(queue_value)
    items = {item.nodeid: item for item in session.items}
    sequence = 1
    while True:
        request_path = queue / f"{sequence:06d}.json"
        while not request_path.exists():
            time.sleep(0.05)
        request = json.loads(request_path.read_text())
        config = json.loads(Path(request["config_path"]).read_text())
        config.update(request["runtime"])
        Path(request["config_path"]).write_text(json.dumps(config), encoding="utf-8")
        if MaestroPytestContext.current:
            MaestroPytestContext.current.refresh(config)
        failure = ""
        reports = []
        try:
            if request["command"] == "close" or request.get("reset_scopes"):
                try:
                    session._setupstate.teardown_exact(None)
                finally:
                    MaestroPytestContext.current = None
            if request["command"] != "close":
                item = items[request["node_id"]]
                nextitem = items.get(request.get("next_node_id"))
                item.ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
                reports = runtestprotocol(item, nextitem=nextitem)
                item.ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
        except Exception:
            failure = traceback.format_exc()
        failed = bool(failure) or any(not report.passed for report in reports)
        detail = failure + "\n".join(str(report.longrepr) for report in reports if not report.passed)
        suite = ET.Element("testsuite", tests="1", failures=str(int(failed)), name="pytest-attempt")
        testcase = ET.SubElement(suite, "testcase", name=(request.get("node_id") or "shared-finalization").rsplit("::", 1)[-1])
        if failed:
            ET.SubElement(testcase, "failure", message="pytest lifecycle failed").text = detail
        junit = Path(request["junit_path"])
        junit.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(suite).write(junit, encoding="utf-8", xml_declaration=True)
        log = Path(request["stdout_path"])
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(detail if failed else "pytest lifecycle passed\n", encoding="utf-8")
        write_json(queue / f"{sequence:06d}.done.json", {"returncode": int(failed), "reports": [{"when": report.when, "outcome": report.outcome} for report in reports]})
        sequence += 1
        if request["command"] == "close":
            return True
