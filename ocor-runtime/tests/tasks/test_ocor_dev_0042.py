"""OCOR-DEV-0042: Implement exact approved 44-transition C6 FSM.

Proves that ocor_runtime.c6.fsm's runtime transition table equals all
44 LLD v1.1 section 3.2 transition tuples exactly (source, event/guard,
durable effect and destination), that any missing, extra, duplicate or
semantically altered transition fails closed, and that applying a
known transition always durably persists a record of its declared
effect via an injected sink -- never silently, never partially. Pure,
in-memory, deterministic component (no external service needed, like
OCOR-DEV-0028/0030's own C1/C6 slices).

Cross-validates the reimplemented parser against OCOR-DEV-0020's
sealed spikes.c6_fsm_fidelity.generator (reused unmodified, imported
only here in the test, per the established spikes/-is-outside-runtime
pythonpath precedent) to prove no transcription drift between the two
independent implementations.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from ocor_runtime.c6.fsm import (
    DEFAULT_LLD_PATH,
    TRANSITIONS,
    FSMTableIntegrityError,
    FSMTransitionError,
    GovernedActionFSM,
    PersistedEffect,
    Transition,
    parse_transition_table,
    transition_digest,
    validate_transition_set,
)
from ocor_runtime.errors import TemporalGuardViolation

from c6_action_fixture import PlacedActionStates, satisfied

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from spikes.c6_fsm_fidelity.generator import (  # noqa: E402
    TRANSITION_TABLE_SHA256 as SEALED_TRANSITION_TABLE_SHA256,
)
from spikes.c6_fsm_fidelity.generator import generate_from_lld  # noqa: E402

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)


class RecordingSink:
    def __init__(self) -> None:
        self.calls: list[PersistedEffect] = []

    def persist_effect(self, record: PersistedEffect) -> None:
        self.calls.append(record)


def test_runtime_table_has_all_44_unique_transition_ids_in_lld_order() -> None:
    assert len(TRANSITIONS) == 44
    assert len({item.transition_id for item in TRANSITIONS}) == 44
    assert TRANSITIONS[0].transition_id == "ACT-T01"
    assert TRANSITIONS[-1].transition_id == "ACT-T31b"


def test_runtime_table_digest_matches_the_sealed_ocor_dev_0020_baseline() -> None:
    assert transition_digest(TRANSITIONS) == SEALED_TRANSITION_TABLE_SHA256


def _as_plain_tuple(item: Any) -> tuple[str, str, str, str, str]:
    return (item.transition_id, item.source, item.guard, item.durable_effect, item.destination)


def test_reimplemented_parser_reproduces_the_sealed_spikes_generator_bit_for_bit() -> None:
    """Two independent parsers of the identical approved LLD document
    must agree exactly, proving this task's own reimplementation is
    not a divergent, drifted copy of OCOR-DEV-0020's sealed one."""
    sealed = generate_from_lld(DEFAULT_LLD_PATH)
    retained = parse_transition_table(DEFAULT_LLD_PATH)
    assert [_as_plain_tuple(item) for item in sealed] == [_as_plain_tuple(item) for item in retained]


@pytest.mark.parametrize("mode", ["missing", "extra", "duplicate"])
def test_missing_extra_or_duplicate_transition_fails_closed(mode: str) -> None:
    if mode == "missing":
        candidate = TRANSITIONS[:-1]
    elif mode == "extra":
        candidate = TRANSITIONS + (Transition("ACT-T99", "A", "guard", "effect", "B"),)
    else:
        candidate = TRANSITIONS[:-1] + (TRANSITIONS[0],)
    with pytest.raises(FSMTableIntegrityError):
        validate_transition_set(candidate)


def test_altered_durable_effect_fails_semantic_equality() -> None:
    changed = list(TRANSITIONS)
    original = changed[11]
    changed[11] = Transition(
        original.transition_id, original.source, original.guard, "a durable effect nobody approved", original.destination
    )
    with pytest.raises(FSMTableIntegrityError, match="semantic digest mismatch"):
        validate_transition_set(changed)


def test_unsealed_or_modified_lld_is_rejected_before_any_parsing(tmp_path: Path) -> None:
    changed = tmp_path / "LLD.md"
    changed.write_text(DEFAULT_LLD_PATH.read_text().replace("ACK correlato", "ACK non correlato"))
    with pytest.raises(FSMTableIntegrityError, match="LLD digest mismatch"):
        parse_transition_table(changed)


def test_applying_a_known_transition_durably_persists_its_declared_effect() -> None:
    fsm = GovernedActionFSM()
    sink = RecordingSink()

    record = fsm.apply(
        "ACT-T01", sink=sink, at=NOW, correlation_id="urn:ocor:correlation:1", guard=satisfied("ACT-T01", "urn:ocor:correlation:1", NOW)
    )

    assert sink.calls == [record]
    assert record.transition_id == "ACT-T01"
    assert record.source == "[*]"
    assert record.destination == "PROPOSAL_RECORDED"
    assert record.durable_effect == "registra proposta, GCS, fingerprint ed Evidence"
    assert record.correlation_id == "urn:ocor:correlation:1"


def test_applying_every_one_of_the_44_transitions_persists_exactly_one_effect_each() -> None:
    """Integration-level proof across the whole table, not just one
    representative transition: every declared effect is reachable and
    persisted, none silently dropped."""
    states = PlacedActionStates()
    fsm = GovernedActionFSM(states=states)
    sink = RecordingSink()

    for transition in TRANSITIONS:
        correlation = f"urn:ocor:correlation:{transition.transition_id}"
        states.place(correlation, transition.source)
        fsm.apply(
            transition.transition_id,
            sink=sink,
            at=NOW,
            correlation_id=correlation,
            guard=satisfied(transition.transition_id, correlation, NOW),
        )

    assert len(sink.calls) == 44
    assert {record.transition_id for record in sink.calls} == {item.transition_id for item in TRANSITIONS}
    assert all(record.durable_effect for record in sink.calls)


def test_unknown_transition_id_is_refused_before_any_sink_call() -> None:
    fsm = GovernedActionFSM()
    sink = RecordingSink()

    with pytest.raises(FSMTransitionError) as excinfo:
        fsm.apply("ACT-T99-DOES-NOT-EXIST", sink=sink, at=NOW, correlation_id="urn:ocor:correlation:x")

    assert excinfo.value.reason_code == "UNKNOWN_TRANSITION"
    assert sink.calls == []


def test_a_naive_timestamp_is_refused_before_any_sink_call() -> None:
    fsm = GovernedActionFSM()
    sink = RecordingSink()

    with pytest.raises(TemporalGuardViolation):
        fsm.apply("ACT-T01", sink=sink, at=datetime(2026, 9, 14, 12, 0, 0), correlation_id="urn:ocor:correlation:1")

    assert sink.calls == []


def test_a_plain_callable_sink_is_accepted_identically_to_a_protocol_object() -> None:
    states = PlacedActionStates()
    fsm = GovernedActionFSM(states=states)
    calls: list[PersistedEffect] = []
    states.place("urn:ocor:correlation:2", "PROPOSAL_RECORDED")

    record = fsm.apply(
        "ACT-T02", sink=calls.append, at=NOW, correlation_id="urn:ocor:correlation:2", guard=satisfied("ACT-T02", "urn:ocor:correlation:2", NOW)
    )

    assert calls == [record]


class _FailingThenRecordingSink:
    """A real fault: the first persist attempt raises (simulating a
    downstream durability failure); a later retry with the same sink
    succeeds. No partial or silently-swallowed effect is ever left
    behind by a failed attempt."""

    def __init__(self) -> None:
        self.calls: list[PersistedEffect] = []
        self._fail_next = True

    def persist_effect(self, record: PersistedEffect) -> None:
        if self._fail_next:
            self._fail_next = False
            raise RuntimeError("simulated downstream persistence outage")
        self.calls.append(record)


def test_a_failing_sink_propagates_and_a_retry_against_the_same_fsm_recovers() -> None:
    fsm = GovernedActionFSM()
    sink = _FailingThenRecordingSink()

    with pytest.raises(RuntimeError, match="simulated downstream persistence outage"):
        fsm.apply(
            "ACT-T01", sink=sink, at=NOW, correlation_id="urn:ocor:correlation:retry", guard=satisfied("ACT-T01", "urn:ocor:correlation:retry", NOW)
        )
    assert sink.calls == []

    record = fsm.apply(
        "ACT-T01", sink=sink, at=NOW, correlation_id="urn:ocor:correlation:retry", guard=satisfied("ACT-T01", "urn:ocor:correlation:retry", NOW)
    )
    assert sink.calls == [record]


def test_context_is_captured_and_immutable_once_persisted() -> None:
    fsm = GovernedActionFSM()
    sink = RecordingSink()
    mutable_context: dict[str, Any] = {"aggregate_id": "urn:ocor:aggregate:1"}

    record = fsm.apply(
        "ACT-T01",
        sink=sink,
        at=NOW,
        correlation_id="urn:ocor:correlation:ctx",
        context=mutable_context,
        guard=satisfied("ACT-T01", "urn:ocor:correlation:ctx", NOW),
    )
    mutable_context["aggregate_id"] = "tampered-after-the-fact"

    assert record.context["aggregate_id"] == "urn:ocor:aggregate:1"
    with pytest.raises(TypeError):
        record.context["aggregate_id"] = "should-not-be-assignable"
