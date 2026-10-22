"""Fail-closed validation of the JUnit evidence emitted by a single Flow."""
from pathlib import Path
import xml.etree.ElementTree as ET


def report_error(path: Path) -> str | None:
    """Return a diagnostic, or None only for nonempty successful JUnit evidence."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError, ValueError):
        return "Maestro JUnit is missing, unreadable or malformed"
    if root.tag not in {"testsuites", "testsuite"}:
        return "Maestro JUnit has an invalid root"
    cases = list(root.iter("testcase"))
    if not cases:
        return "Maestro JUnit contains no test cases"
    for node in root.iter():
        if node.tag in {"failure", "error", "skipped"}:
            return "Maestro JUnit contains failed, errored or skipped execution"
        if node.tag in {"testsuites", "testsuite"}:
            for counter in ("tests", "failures", "errors", "skipped", "disabled"):
                raw = node.get(counter)
                if raw is None:
                    continue
                if not raw.isascii() or not raw.isdecimal():
                    return "Maestro JUnit has invalid counters"
                count = int(raw)
                if counter == "tests":
                    if count != len(list(node.iter("testcase"))):
                        return "Maestro JUnit test count does not match its evidence"
                elif count:
                    return "Maestro JUnit reports unsuccessful execution"
    for case in cases:
        if case.get("status", "SUCCESS").upper() not in {"SUCCESS", "PASSED"}:
            return "Maestro JUnit test case status is not successful"
    return None
