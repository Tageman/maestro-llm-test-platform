from __future__ import annotations

import re
from dataclasses import dataclass

from maestro_app.domain.enums import FailureType


@dataclass(frozen=True, slots=True)
class FailureEvidence:
    output: str = ""
    phase: str | None = None
    timed_out: bool = False
    environment_failed: bool = False


@dataclass(frozen=True, slots=True)
class FailureClassification:
    failure_type: FailureType
    reason: str
    selector: str | None = None
    failed_step: int | None = None


class FailureClassifier:
    """Deterministic classifier; UNKNOWN is deliberately never repairable."""

    _LOCATOR = (
        re.compile(r"Element not found: Text matching regex:\s*(.+)", re.I),
        re.compile(r"No matching element.*?(?:text|id)[:=]\s*([^\n]+)", re.I),
    )
    _ASSERTION = (
        re.compile(r"Assertion is false", re.I),
        re.compile(r"assert(?:Visible|NotVisible).*failed", re.I),
        re.compile(r"Assert that .+ (?:is|is not) visible FAILED", re.I),
    )
    _SYNTAX = (
        re.compile(r"(?:yaml|flow).*(?:syntax|parse|parsing).*error", re.I | re.S),
        re.compile(r"Malformed command|Unknown command|Invalid flow", re.I),
    )
    _ENVIRONMENT = (
        re.compile(r"(?:no|zero) devices? (?:found|available|connected)", re.I),
        re.compile(r"device .*?(?:offline|not found|unavailable)", re.I),
        re.compile(r"unable to start maestro|adb.*not found|connection refused", re.I),
        re.compile(r"package .*?not (?:installed|found)", re.I),
    )

    def classify(self, evidence: FailureEvidence) -> FailureClassification:
        output = evidence.output or ""
        # Timeout is a structured process/trace fact. Pytest tracebacks include
        # the runtime source line containing the literal "timed out", so using
        # arbitrary output text here would misclassify ordinary Maestro errors.
        if evidence.timed_out:
            return FailureClassification(FailureType.TIMEOUT, "执行达到超时限制")
        if evidence.environment_failed or self._matches(self._ENVIRONMENT, output):
            return FailureClassification(FailureType.ENVIRONMENT, "设备或执行环境不可用")
        if evidence.phase in {"setup", "teardown"}:
            return FailureClassification(FailureType.FIXTURE, "Fixture 生命周期执行失败")
        if self._matches(self._ASSERTION, output):
            return FailureClassification(FailureType.ASSERTION, "业务断言未满足")
        for pattern in self._LOCATOR:
            match = pattern.search(output)
            if match:
                selector = match.group(1).strip().strip('"\'')
                line_start = output.rfind("\n", 0, match.start()) + 1
                line_end = output.find("\n", match.end())
                line = output[line_start : line_end if line_end >= 0 else None]
                # Maestro's one-line summary wraps the underlying error in
                # parentheses: "[Failed] ... (Element not found: ...: X)".
                # Remove only that summary delimiter; never relax selector
                # matching inside the repairer.
                if "[Failed]" in line and selector.endswith(")"):
                    selector = selector[:-1].rstrip()
                return FailureClassification(
                    FailureType.LOCATOR,
                    "Maestro 未找到目标元素",
                    selector=selector,
                    failed_step=self._failed_step(output),
                )
        if self._matches(self._SYNTAX, output):
            return FailureClassification(FailureType.YAML_SYNTAX, "Maestro YAML 语法错误")
        return FailureClassification(FailureType.UNKNOWN, "无法从现有证据稳定分类")

    @staticmethod
    def _matches(patterns: tuple[re.Pattern[str], ...], output: str) -> bool:
        return any(pattern.search(output) for pattern in patterns)

    @staticmethod
    def _failed_step(output: str) -> int | None:
        match = re.search(r"step[-_ ]?(\d+)", output, re.I)
        return int(match.group(1)) if match else None
