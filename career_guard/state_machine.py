from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RunState(str, Enum):
    CREATED = "created"
    VALIDATING_INPUTS = "validating_inputs"
    SNAPSHOTTING_SOURCES = "snapshotting_sources"
    DETECTING_CHANGES = "detecting_changes"
    ALIGNING_EVIDENCE = "aligning_evidence"
    READY_TO_REPORT = "ready_to_report"
    DONE = "done"
    FAILED_SAFE = "failed_safe"


ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.CREATED: {RunState.VALIDATING_INPUTS},
    RunState.VALIDATING_INPUTS: {RunState.SNAPSHOTTING_SOURCES, RunState.FAILED_SAFE},
    RunState.SNAPSHOTTING_SOURCES: {RunState.DETECTING_CHANGES, RunState.FAILED_SAFE},
    RunState.DETECTING_CHANGES: {RunState.ALIGNING_EVIDENCE, RunState.FAILED_SAFE},
    RunState.ALIGNING_EVIDENCE: {RunState.READY_TO_REPORT, RunState.FAILED_SAFE},
    RunState.READY_TO_REPORT: {RunState.DONE, RunState.FAILED_SAFE},
    RunState.DONE: set(),
    RunState.FAILED_SAFE: set(),
}


@dataclass
class StateController:
    state: RunState = RunState.CREATED
    trace: list[dict[str, str]] = field(default_factory=list)

    def transition(self, next_state: RunState, detail: str) -> None:
        allowed = ALLOWED_TRANSITIONS[self.state]
        if next_state not in allowed:
            raise ValueError(f"Illegal state transition: {self.state.value} -> {next_state.value}")
        self.trace.append(
            {
                "from": self.state.value,
                "to": next_state.value,
                "detail": detail,
            }
        )
        self.state = next_state
