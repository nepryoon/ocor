"""Test support of OCOR-DEV-REM-0053 (NCP-U07): preconditions of the C6 action FSM.

Since NCR-C6-003 every transition starts from its source state with its event/guard evaluated
(LLD v1.1 :260-305). ``PlacedActionStates`` is a test ``ActionStatePort`` that places an action
instance in a given source state, and ``satisfied`` builds the evaluation of a transition's
event/guard as satisfied for that action (with the stop observed for ACT-T23a/ACT-T23b), so a
test exercises a transition exactly from its precondition without persisting other effects.
"""

from __future__ import annotations

from datetime import datetime

from ocor_runtime.c6.fsm import (
    INITIAL_STATE,
    GuardEvaluation,
    InMemoryActionStateStore,
    STOP_TRANSITIONS,
)


class PlacedActionStates(InMemoryActionStateStore):
    def place(self, correlation_id: str, state: str) -> None:
        with self.transaction(correlation_id):
            if state == INITIAL_STATE:
                self._states.pop(correlation_id, None)
            else:
                self._states[correlation_id] = state


def satisfied(transition_id: str, correlation_id: str, at: datetime) -> GuardEvaluation:
    return GuardEvaluation(
        transition_id=transition_id,
        correlation_id=correlation_id,
        satisfied=True,
        snapshot_id=f"urn:ocor:snapshot:{correlation_id}:{transition_id}",
        evaluated_at=at,
        stop_requested=transition_id in STOP_TRANSITIONS,
    )
