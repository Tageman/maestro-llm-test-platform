import pytest

from maestro_app.domain.enums import RunState
from maestro_app.domain.state_machine import InvalidRunTransition, RunStateMachine


def test_happy_path_can_reach_completed() -> None:
    machine = RunStateMachine(RunState.CREATED)
    for target in (
        RunState.VALIDATING,
        RunState.GENERATING,
        RunState.READY,
        RunState.PREPARING_DEVICE,
        RunState.RUNNING,
        RunState.FINALIZING,
        RunState.COMPLETED,
    ):
        machine = machine.transition_to(target)

    assert machine.is_terminal


def test_terminal_state_cannot_restart() -> None:
    machine = RunStateMachine(RunState.COMPLETED)

    with pytest.raises(InvalidRunTransition):
        machine.transition_to(RunState.RUNNING)


def test_repair_loop_is_explicitly_allowed() -> None:
    machine = RunStateMachine(RunState.RUNNING)
    machine = machine.transition_to(RunState.DIAGNOSING)
    machine = machine.transition_to(RunState.REPAIRING)
    machine = machine.transition_to(RunState.RUNNING)

    assert machine.state == RunState.RUNNING


def test_active_cancellation_must_finalize_cleanup() -> None:
    machine = RunStateMachine(RunState.RUNNING)

    with pytest.raises(InvalidRunTransition):
        machine.transition_to(RunState.CANCELLED)

    machine = machine.transition_to(RunState.FINALIZING)
    machine = machine.transition_to(RunState.CANCELLED)

    assert machine.is_terminal
