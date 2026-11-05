"""OCOR-DEV-REM-0053 (NCP-U07): the C6 action path conforms to the closed normative elements.

Unit of NORMATIVE-CONFORMANCE-PLAN (2026-10-30), plan unit NCP-U07, register entries
NCR-C6-001 to NCR-C6-009 and NCR-C6-014.

* NCR-C6-003 -- LLD v1.1 :254-256 (guards and EMISSION-FENCE), LLD v1.1 :260-305 (each of the
  44 transitions has a source state and an event/guard), LLD v1.1 :307 (ACT-T23 precedes T14,
  T19 and T29), ADD v1.3 :2905 (ACT-T23 precedence on a single evaluation snapshot), Register
  FR-077 :209 (a trace with every mandatory record in a valid order) and FR-008 :59 (every
  state in canonical order). The FSM reads the current state of the action instance, refuses a
  transition whose source is not that state, refuses a transition whose event/guard was not
  evaluated as satisfied for that action, and lets a stop observed on the evaluation snapshot
  win over dispatch, retry and canonical commit. A refused transition persists no effect and
  leaves the state unchanged.

Every case is in-process: the FSM is a pure component whose durable effect sink and state
store are ports.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ocor_runtime.c6 import fsm as c6_fsm
from ocor_runtime.c6.fsm import (
    TRANSITIONS,
    FSMTransitionError,
    GovernedActionFSM,
    PersistedEffect,
)

NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=UTC)
BY_ID = {item.transition_id: item for item in TRANSITIONS}
CANONICAL_PATH = (
    "ACT-T01",
    "ACT-T04",
    "ACT-T06",
    "ACT-T08",
    "ACT-T26",
    "ACT-T10b",
    "ACT-T11",
    "ACT-T12",
    "ACT-T29",
    "ACT-T30",
    "ACT-T27",
    "ACT-T22",
)
EXTERNAL_PATH = (
    "ACT-T01",
    "ACT-T04",
    "ACT-T06",
    "ACT-T08",
    "ACT-T26",
    "ACT-T10b",
    "ACT-T11",
    "ACT-T12",
    "ACT-T14",
    "ACT-T15",
    "ACT-T16",
    "ACT-T27",
    "ACT-T28",
)
EMISSIONS = ("ACT-T14", "ACT-T19", "ACT-T29")


class RecordingSink:
    def __init__(self) -> None:
        self.calls: list[PersistedEffect] = []

    def persist_effect(self, record: PersistedEffect) -> None:
        self.calls.append(record)


class FailingOnceSink(RecordingSink):
    def __init__(self) -> None:
        super().__init__()
        self._fail = True

    def persist_effect(self, record: PersistedEffect) -> None:
        if self._fail:
            self._fail = False
            raise RuntimeError("simulated durable effect outage")
        super().persist_effect(record)


def _guard(
    transition_id: str,
    correlation_id: str,
    *,
    satisfied: bool = True,
    stop: bool | None = None,
    at: datetime = NOW,
    snapshot: str = "urn:ocor:snapshot:1",
) -> Any:
    stop_requested = transition_id.startswith("ACT-T23") if stop is None else stop
    return c6_fsm.GuardEvaluation(
        transition_id=transition_id,
        correlation_id=correlation_id,
        satisfied=satisfied,
        snapshot_id=snapshot,
        evaluated_at=at,
        stop_requested=stop_requested,
    )


def _drive(
    fsm: GovernedActionFSM, sink: RecordingSink, correlation: str, path: tuple[str, ...]
) -> list[PersistedEffect]:
    records = []
    for index, transition_id in enumerate(path):
        at = NOW + timedelta(milliseconds=index)
        records.append(
            fsm.apply(
                transition_id,
                sink=sink,
                at=at,
                correlation_id=correlation,
                guard=_guard(transition_id, correlation, at=at),
            )
        )
    return records


def _path_to(state: str) -> tuple[str, ...]:
    """The shortest transition path from [*] to ``state`` in the approved table."""
    frontier: list[tuple[str, tuple[str, ...]]] = [("[*]", ())]
    seen = {"[*]"}
    while frontier:
        current, path = frontier.pop(0)
        if current == state:
            return path
        for item in TRANSITIONS:
            if (
                item.source == current
                and item.destination not in seen
                and not item.transition_id.startswith("ACT-T23")
            ):
                seen.add(item.destination)
                frontier.append((item.destination, path + (item.transition_id,)))
    raise AssertionError(f"no path to {state}")


def _reason(excinfo: pytest.ExceptionInfo[FSMTransitionError]) -> str:
    return str(excinfo.value.reason_code)


def test_ncr_c6_003_conforms() -> None:
    """LLD v1.1 :260-305 and :307: source state, event/guard and ACT-T23 precedence."""
    fsm = GovernedActionFSM()
    sink = RecordingSink()

    with pytest.raises(FSMTransitionError) as fresh:
        fsm.apply(
            "ACT-T30",
            sink=sink,
            at=NOW,
            correlation_id="urn:ocor:action:fresh",
            guard=_guard("ACT-T30", "urn:ocor:action:fresh"),
        )
    assert _reason(fresh) == "INVALID_SOURCE_STATE"
    assert sink.calls == []

    with pytest.raises(FSMTransitionError) as negative:
        fsm.apply(
            "ACT-T01",
            sink=sink,
            at=NOW,
            correlation_id="urn:ocor:action:g",
            guard=_guard("ACT-T01", "urn:ocor:action:g", satisfied=False),
        )
    assert _reason(negative) == "GUARD_NOT_SATISFIED"
    assert sink.calls == []
    assert fsm.current_state("urn:ocor:action:g") is None

    correlation = "urn:ocor:action:stop"
    _drive(fsm, sink, correlation, _path_to("COMMAND_READY"))
    assert fsm.current_state(correlation) == "COMMAND_READY"
    before = list(sink.calls)
    for transition_id in EMISSIONS:
        with pytest.raises(FSMTransitionError) as precedence:
            fsm.apply(
                transition_id,
                sink=sink,
                at=NOW,
                correlation_id=correlation,
                guard=_guard(transition_id, correlation, stop=True),
            )
        assert _reason(precedence) == "STOP_PRECEDENCE"
    assert sink.calls == before
    cancelled = fsm.apply(
        "ACT-T23b",
        sink=sink,
        at=NOW,
        correlation_id=correlation,
        guard=_guard("ACT-T23b", correlation),
    )
    assert cancelled.destination == "CANCELLED"
    assert fsm.current_state(correlation) == "CANCELLED"


def test_a_transition_without_a_guard_evaluation_is_refused_before_any_effect() -> None:
    fsm = GovernedActionFSM()
    sink = RecordingSink()
    with pytest.raises(FSMTransitionError) as excinfo:
        fsm.apply("ACT-T01", sink=sink, at=NOW, correlation_id="urn:ocor:action:none")
    assert _reason(excinfo) == "GUARD_NOT_EVALUATED"
    assert sink.calls == []
    assert fsm.current_state("urn:ocor:action:none") is None


@pytest.mark.parametrize(
    "mismatch",
    [
        "other-transition",
        "other-action",
        "evaluated-after-the-transition",
        "not-a-guard-evaluation",
    ],
)
def test_a_guard_evaluation_not_bound_to_the_transition_and_action_is_refused(
    mismatch: str,
) -> None:
    fsm = GovernedActionFSM()
    sink = RecordingSink()
    correlation = "urn:ocor:action:bound"
    guard: Any
    if mismatch == "other-transition":
        guard = _guard("ACT-T03", correlation)
    elif mismatch == "other-action":
        guard = _guard("ACT-T01", "urn:ocor:action:other")
    elif mismatch == "evaluated-after-the-transition":
        guard = _guard("ACT-T01", correlation, at=NOW + timedelta(seconds=1))
    else:
        guard = {
            "transition_id": "ACT-T01",
            "correlation_id": correlation,
            "satisfied": True,
        }
    with pytest.raises(FSMTransitionError) as excinfo:
        fsm.apply("ACT-T01", sink=sink, at=NOW, correlation_id=correlation, guard=guard)
    assert _reason(excinfo) == "GUARD_MISMATCH"
    assert sink.calls == []
    assert fsm.current_state(correlation) is None


@pytest.mark.parametrize("transition_id", [item.transition_id for item in TRANSITIONS])
def test_every_transition_from_its_source_state_reaches_its_destination(
    transition_id: str,
) -> None:
    fsm = GovernedActionFSM()
    sink = RecordingSink()
    correlation = f"urn:ocor:action:{transition_id}"
    transition = BY_ID[transition_id]
    if transition.source != "[*]":
        _drive(fsm, sink, correlation, _path_to(transition.source))
    assert fsm.current_state(correlation) == (
        None if transition.source == "[*]" else transition.source
    )
    record = fsm.apply(
        transition_id,
        sink=sink,
        at=NOW + timedelta(seconds=1),
        correlation_id=correlation,
        guard=_guard(transition_id, correlation, at=NOW + timedelta(seconds=1)),
    )
    assert record.source == transition.source
    assert record.destination == transition.destination
    assert sink.calls[-1] == record
    assert fsm.current_state(correlation) == transition.destination


@pytest.mark.parametrize("transition_id", [item.transition_id for item in TRANSITIONS])
def test_every_transition_from_a_state_other_than_its_source_is_refused(
    transition_id: str,
) -> None:
    fsm = GovernedActionFSM()
    sink = RecordingSink()
    correlation = f"urn:ocor:action:wrong:{transition_id}"
    transition = BY_ID[transition_id]
    wrong = "DENIED" if transition.source != "DENIED" else "CANCELLED"
    _drive(
        fsm,
        sink,
        correlation,
        _path_to(wrong) if wrong != "CANCELLED" else _path_to("PRE_DISPATCH_CHECK"),
    )
    if wrong == "CANCELLED":
        fsm.apply(
            "ACT-T23a",
            sink=sink,
            at=NOW,
            correlation_id=correlation,
            guard=_guard("ACT-T23a", correlation),
        )
    state = fsm.current_state(correlation)
    assert state != transition.source
    before = list(sink.calls)
    with pytest.raises(FSMTransitionError) as excinfo:
        fsm.apply(
            transition_id,
            sink=sink,
            at=NOW + timedelta(seconds=1),
            correlation_id=correlation,
            guard=_guard(transition_id, correlation, at=NOW + timedelta(seconds=1)),
        )
    assert _reason(excinfo) == "INVALID_SOURCE_STATE"
    assert sink.calls == before
    assert fsm.current_state(correlation) == state


def test_a_cancel_or_stop_transition_requires_the_stop_on_the_snapshot() -> None:
    fsm = GovernedActionFSM()
    sink = RecordingSink()
    correlation = "urn:ocor:action:nostop"
    _drive(fsm, sink, correlation, _path_to("PRE_DISPATCH_CHECK"))
    with pytest.raises(FSMTransitionError) as excinfo:
        fsm.apply(
            "ACT-T23a",
            sink=sink,
            at=NOW,
            correlation_id=correlation,
            guard=_guard("ACT-T23a", correlation, stop=False),
        )
    assert _reason(excinfo) == "GUARD_NOT_SATISFIED"
    assert fsm.current_state(correlation) == "PRE_DISPATCH_CHECK"


def test_without_a_stop_on_the_snapshot_the_emission_proceeds() -> None:
    fsm = GovernedActionFSM()
    sink = RecordingSink()
    correlation = "urn:ocor:action:go"
    _drive(fsm, sink, correlation, _path_to("COMMAND_READY"))
    record = fsm.apply(
        "ACT-T29",
        sink=sink,
        at=NOW,
        correlation_id=correlation,
        guard=_guard("ACT-T29", correlation, stop=False),
    )
    assert record.destination == "CANONICAL_COMMIT_PENDING"


@pytest.mark.parametrize(
    "path", [CANONICAL_PATH, EXTERNAL_PATH], ids=["canonical-target", "external-target"]
)
def test_the_trace_of_a_completed_action_is_in_canonical_order(
    path: tuple[str, ...],
) -> None:
    """FR-077 :209 and FR-008 :59: every mandatory record in a valid order."""
    fsm = GovernedActionFSM()
    sink = RecordingSink()
    correlation = "urn:ocor:action:trace"
    records = _drive(fsm, sink, correlation, path)
    assert [item.transition_id for item in sink.calls] == list(path)
    for previous, following in zip(records, records[1:], strict=False):
        assert previous.destination == following.source
    assert records[0].source == "[*]"
    with pytest.raises(FSMTransitionError):
        fsm.apply(
            path[0],
            sink=sink,
            at=NOW,
            correlation_id=correlation,
            guard=_guard(path[0], correlation),
        )
    assert len(sink.calls) == len(path)


def test_a_failed_effect_persistence_leaves_the_state_unchanged_and_a_retry_recovers() -> (
    None
):
    fsm = GovernedActionFSM()
    sink = FailingOnceSink()
    correlation = "urn:ocor:action:retry"
    with pytest.raises(RuntimeError, match="simulated durable effect outage"):
        fsm.apply(
            "ACT-T01",
            sink=sink,
            at=NOW,
            correlation_id=correlation,
            guard=_guard("ACT-T01", correlation),
        )
    assert fsm.current_state(correlation) is None
    record = fsm.apply(
        "ACT-T01",
        sink=sink,
        at=NOW,
        correlation_id=correlation,
        guard=_guard("ACT-T01", correlation),
    )
    assert sink.calls == [record]
    assert fsm.current_state(correlation) == "PROPOSAL_RECORDED"


def test_two_engines_sharing_the_state_store_never_both_apply_from_the_same_state() -> (
    None
):
    store = c6_fsm.InMemoryActionStateStore()
    first = GovernedActionFSM(states=store)
    second = GovernedActionFSM(states=store)
    sink = RecordingSink()
    correlation = "urn:ocor:action:race"
    _drive(first, sink, correlation, _path_to("COMMAND_READY"))
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def run(engine: GovernedActionFSM, transition_id: str) -> None:
        barrier.wait()
        try:
            engine.apply(
                transition_id,
                sink=sink,
                at=NOW,
                correlation_id=correlation,
                guard=_guard(transition_id, correlation, stop=False),
            )
            outcomes.append("applied")
        except FSMTransitionError as error:
            outcomes.append(str(error.reason_code))

    threads = [
        threading.Thread(target=run, args=(first, "ACT-T14")),
        threading.Thread(target=run, args=(second, "ACT-T29")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["INVALID_SOURCE_STATE", "applied"]
    assert store.current_state(correlation) in {
        "DISPATCHED",
        "CANONICAL_COMMIT_PENDING",
    }
    assert [item.transition_id for item in sink.calls].count("ACT-T14") + [
        item.transition_id for item in sink.calls
    ].count("ACT-T29") == 1
