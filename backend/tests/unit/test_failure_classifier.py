from __future__ import annotations

import pytest

from maestro_app.application.failure_classifier import FailureClassifier, FailureEvidence
from maestro_app.domain.enums import FailureType


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (FailureEvidence(output="YAML syntax parse error"), FailureType.YAML_SYNTAX),
        (
            FailureEvidence(output="Element not found: Text matching regex: 登录"),
            FailureType.LOCATOR,
        ),
        (FailureEvidence(output="Assertion is false: expected visible"), FailureType.ASSERTION),
        (FailureEvidence(output="device emulator-5554 offline"), FailureType.ENVIRONMENT),
        (FailureEvidence(output="exit=1", phase="setup"), FailureType.FIXTURE),
        (FailureEvidence(output="", timed_out=True), FailureType.TIMEOUT),
        (FailureEvidence(output="unexpected opaque failure"), FailureType.UNKNOWN),
    ],
)
def test_failure_types_are_deterministic(evidence, expected) -> None:
    classifier = FailureClassifier()

    first = classifier.classify(evidence)
    second = classifier.classify(evidence)

    assert first == second
    assert first.failure_type == expected


def test_locator_extracts_selector_without_guessing() -> None:
    result = FailureClassifier().classify(
        FailureEvidence(output='Element not found: Text matching regex: 确认设置')
    )

    assert result.selector == "确认设置"


def test_traceback_source_text_does_not_fake_a_timeout() -> None:
    result = FailureClassifier().classify(
        FailureEvidence(
            output=(
                'reason = f"{timeout_phase} timed out" if timed_out else "exit"\n'
                "Element not found: Text matching regex: 确认设置"
            ),
            timed_out=False,
        )
    )

    assert result.failure_type == FailureType.LOCATOR


def test_maestro_failed_summary_parenthesis_is_not_part_of_selector() -> None:
    result = FailureClassifier().classify(
        FailureEvidence(
            output=(
                "[Failed] TC-HOME-001 (Element not found: "
                "Text matching regex: 确认设置)\n"
            )
        )
    )

    assert result.selector == "确认设置"
