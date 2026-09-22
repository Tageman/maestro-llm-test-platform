from __future__ import annotations

from dataclasses import dataclass

from maestro_app.domain.enums import RunState


class InvalidRunTransition(ValueError):
    """Raised when a run attempts a transition outside the frozen state graph."""


ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset({RunState.VALIDATING, RunState.CANCELLED}),
    RunState.VALIDATING: frozenset(
        {RunState.GENERATING, RunState.VALIDATION_FAILED, RunState.CANCELLED}
    ),
    RunState.VALIDATION_FAILED: frozenset(),
    RunState.GENERATING: frozenset(
        {
            RunState.AWAITING_REVIEW,
            RunState.READY,
            RunState.GENERATION_FAILED,
            RunState.CANCELLED,
        }
    ),
    RunState.GENERATION_FAILED: frozenset(),
    RunState.AWAITING_REVIEW: frozenset({RunState.READY, RunState.CANCELLED}),
    RunState.READY: frozenset({RunState.PREPARING_DEVICE, RunState.CANCELLED}),
    RunState.PREPARING_DEVICE: frozenset(
        {RunState.RUNNING, RunState.FAILED, RunState.CANCELLED}
    ),
    RunState.RUNNING: frozenset(
        {
            RunState.DIAGNOSING,
            RunState.FINALIZING,
            RunState.FAILED,
        }
    ),
    RunState.DIAGNOSING: frozenset(
        {RunState.REPAIRING, RunState.RUNNING, RunState.FINALIZING, RunState.FAILED}
    ),
    RunState.REPAIRING: frozenset(
        {RunState.RUNNING, RunState.FINALIZING, RunState.FAILED}
    ),
    RunState.FINALIZING: frozenset(
        {
            RunState.COMPLETED,
            RunState.COMPLETED_WITH_FAILURES,
            RunState.FAILED,
            RunState.CANCELLED,
        }
    ),
    RunState.COMPLETED: frozenset(),
    RunState.COMPLETED_WITH_FAILURES: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
}


TERMINAL_STATES = frozenset(
    {
        RunState.VALIDATION_FAILED,
        RunState.GENERATION_FAILED,
        RunState.COMPLETED,
        RunState.COMPLETED_WITH_FAILURES,
        RunState.FAILED,
        RunState.CANCELLED,
    }
)


@dataclass(frozen=True, slots=True)
class RunStateMachine:
    state: RunState

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def can_transition_to(self, target: RunState) -> bool:
        return target in ALLOWED_TRANSITIONS[self.state]

    def transition_to(self, target: RunState) -> "RunStateMachine":
        if not self.can_transition_to(target):
            raise InvalidRunTransition(
                f"run cannot transition from {self.state.value} to {target.value}"
            )
        return RunStateMachine(target)
