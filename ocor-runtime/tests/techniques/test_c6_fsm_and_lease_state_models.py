"""Stateful properties, reference models and bounded model checking (OCOR-DEV-REM-0060, NCP-U12, NCR-TESTS-005).

Technique routing of docs/development_methodology/OCOR_TEST_STRATEGY.md:20-21 ("FSM | all transitions,
invalid transitions, stateful properties"; "Saga/lease/fence/outbox/deletion | reference model,
faults, bounded model checking").

* The C6 FSM (``ocor_runtime.c6.fsm.GovernedActionFSM``) against a reference model built in this module
  from the approved table of LLD v1.1 §3.2 (docs/OCOR_LLD_v1.1.md:258-305): a transition is applied
  only from its source state, with its event/guard satisfied, and ACT-T23 precedes ACT-T14, ACT-T19
  and ACT-T29 when a stop is observed on the same snapshot (:307); a refused transition persists no
  effect and leaves the state unchanged.
* The single-use CapabilityLease (``ocor_runtime.kernel.governance.LeaseConsumptionLedger`` over
  ``InMemoryLeaseState``) against a reference model of LLD v1.1 :71-81 and the lease contract
  (``capability-lease.schema.json``, LLD v1.1 §0.2): consumed at most once, never when expired,
  revoked, issued for a stale stop epoch or for a stale fencing token.

Hypothesis drives the stateful machines (derandomised, no example database); the bounded model checks
enumerate every operation sequence up to the stated bound, each on a fresh instance.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from ocor_runtime.c6.fsm import FSMTransitionError, GovernedActionFSM, GuardEvaluation, PersistedEffect
from ocor_runtime.kernel.governance import (
    CapabilityLease,
    GovernanceFault,
    InMemoryLeaseState,
    InMemoryTrustedClock,
    LeaseConsumptionLedger,
    LeaseExpectation,
)

ROOT = Path(__file__).resolve().parents[3]
LLD = ROOT / "docs/OCOR_LLD_v1.1.md"
T0 = datetime(2026, 11, 10, 9, 0, 0, tzinfo=UTC)
DIGEST = "urn:sha256:" + "c" * 64
INITIAL = "[*]"
STOP_PRECEDED = frozenset({"ACT-T14", "ACT-T19", "ACT-T29"})
STOP = frozenset({"ACT-T23a", "ACT-T23b"})
MACHINE_PROFILE = settings(
    max_examples=60, stateful_step_count=40, derandomize=True, database=None, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


# --- the approved table, read independently of the runtime parser ----------------------------


def _approved_table() -> dict[str, tuple[str, str]]:
    lines = LLD.read_text(encoding="utf-8").split("\n")
    start = lines.index("### 3.2 Tabella completa delle 44 transizioni")
    table: dict[str, tuple[str, str]] = {}
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            break
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) == 5 and re.fullmatch(r"ACT-T\d{2}[a-z]?", cells[0]):
            table[cells[0]] = (cells[1], cells[4])
    return table


TABLE = _approved_table()
TRANSITION_IDS = sorted(TABLE)


def test_the_reference_table_has_the_44_approved_transitions_and_matches_the_runtime():
    assert len(TABLE) == 44
    runtime = {item.transition_id: (item.source, item.destination) for item in GovernedActionFSM().transitions}
    assert runtime == TABLE


@dataclass
class FSMReference:
    """Reference model: the state of each action instance and the effects persisted."""

    states: dict[str, str] = field(default_factory=dict)
    effects: list[tuple[str, str]] = field(default_factory=list)

    def refusals(self, transition_id: str, correlation_id: str, *, satisfied: bool, stop: bool) -> set[str]:
        source, _ = TABLE[transition_id]
        reasons: set[str] = set()
        if transition_id in STOP_PRECEDED and stop:
            reasons.add("STOP_PRECEDENCE")
        if not satisfied or (transition_id in STOP and not stop):
            reasons.add("GUARD_NOT_SATISFIED")
        if self.states.get(correlation_id, INITIAL) != source:
            reasons.add("INVALID_SOURCE_STATE")
        return reasons

    def apply(self, transition_id: str, correlation_id: str) -> None:
        self.states[correlation_id] = TABLE[transition_id][1]
        self.effects.append((correlation_id, transition_id))


def _guard(transition_id: str, correlation_id: str, *, satisfied: bool, stop: bool, at: datetime) -> GuardEvaluation:
    return GuardEvaluation(
        transition_id=transition_id, correlation_id=correlation_id, satisfied=satisfied, snapshot_id="snapshot-1", evaluated_at=at, stop_requested=stop
    )


class GovernedActionFSMMachine(RuleBasedStateMachine):
    """Stateful property: the runtime FSM and the reference model agree on every step."""

    ACTIONS = ("action-a", "action-b")

    def __init__(self) -> None:
        super().__init__()
        self.fsm = GovernedActionFSM()
        self.model = FSMReference()
        self.persisted: list[PersistedEffect] = []
        self.step = 0

    def _next_reachable(self, correlation_id: str) -> list[str]:
        state = self.model.states.get(correlation_id, INITIAL)
        return [identifier for identifier in TRANSITION_IDS if TABLE[identifier][0] == state]

    @rule(action=st.sampled_from(ACTIONS), choice=st.integers(min_value=0, max_value=10**6), satisfied=st.booleans(), stop=st.booleans(), any_transition=st.booleans())
    def apply(self, action: str, choice: int, satisfied: bool, stop: bool, any_transition: bool) -> None:
        candidates = TRANSITION_IDS if any_transition or not self._next_reachable(action) else self._next_reachable(action)
        transition_id = candidates[choice % len(candidates)]
        self.step += 1
        at = T0 + timedelta(seconds=self.step)
        expected = self.model.refusals(transition_id, action, satisfied=satisfied, stop=stop)
        before = self.fsm.current_state(action)
        try:
            record = self.fsm.apply(
                transition_id, sink=self.persisted.append, at=at, correlation_id=action, guard=_guard(transition_id, action, satisfied=satisfied, stop=stop, at=at)
            )
        except FSMTransitionError as error:
            assert expected, f"{transition_id} refused with {error.reason_code}, the model accepts it"
            assert error.reason_code in expected
            assert self.fsm.current_state(action) == before
            return
        assert not expected, f"{transition_id} accepted, the model refuses it for {sorted(expected)}"
        self.model.apply(transition_id, action)
        assert (record.transition_id, record.source, record.destination) == (transition_id, *TABLE[transition_id])

    @invariant()
    def states_agree(self) -> None:
        for action in self.ACTIONS:
            assert (self.fsm.current_state(action) or INITIAL) == self.model.states.get(action, INITIAL)

    @invariant()
    def effects_agree(self) -> None:
        assert [(item.correlation_id, item.transition_id) for item in self.persisted] == self.model.effects


GovernedActionFSMMachine.TestCase.settings = MACHINE_PROFILE
TestGovernedActionFSMStateful = GovernedActionFSMMachine.TestCase


def _paths(depth: int) -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = []
    frontier: list[tuple[tuple[str, ...], str]] = [((), INITIAL)]
    for _ in range(depth):
        following = []
        for path, state in frontier:
            for identifier in TRANSITION_IDS:
                if TABLE[identifier][0] == state:
                    following.append(((*path, identifier), TABLE[identifier][1]))
        paths.extend(path for path, _ in following)
        frontier = following
    return paths


# 12 is the smallest bound whose paths from [*] cover all 44 transitions of the approved table.
FSM_BOUND = 12


def test_c6_fsm_bounded_model_checking_every_path_up_to_the_bound():
    """Every path of length <= FSM_BOUND from ``[*]`` in the approved table is accepted by the runtime
    with its guards satisfied, and at every step every transition from another source is refused
    ``INVALID_SOURCE_STATE`` without changing the state or persisting an effect."""
    paths = _paths(FSM_BOUND)
    assert {identifier for path in paths for identifier in path} == set(TABLE)
    for path in paths:
        fsm = GovernedActionFSM()
        persisted: list[PersistedEffect] = []
        for step, transition_id in enumerate(path, start=1):
            at = T0 + timedelta(seconds=step)
            state = fsm.current_state("bmc") or INITIAL
            for other in TRANSITION_IDS:
                if TABLE[other][0] == state:
                    continue
                with pytest.raises(FSMTransitionError) as excinfo:
                    fsm.apply(other, sink=persisted.append, at=at, correlation_id="bmc", guard=_guard(other, "bmc", satisfied=True, stop=other in STOP, at=at))
                assert excinfo.value.reason_code == "INVALID_SOURCE_STATE"
                assert (fsm.current_state("bmc") or INITIAL) == state
            fsm.apply(transition_id, sink=persisted.append, at=at, correlation_id="bmc", guard=_guard(transition_id, "bmc", satisfied=True, stop=transition_id in STOP, at=at))
        assert fsm.current_state("bmc") == TABLE[path[-1]][1]
        assert [item.transition_id for item in persisted] == list(path)


# --- the single-use CapabilityLease ---------------------------------------------------------


LEASE_IDS = ("lease-1", "lease-2")
ACTION = "urn:ocor:action:lease-model"


def _lease(lease_id: str, *, stop_epoch: int, fencing_token: int) -> CapabilityLease:
    return CapabilityLease(
        lease_id=lease_id,
        capability_id="act:mission",
        effective_principal_id="urn:ocor:principal:operator",
        delegation_ref=DIGEST,
        action_instance_id=ACTION,
        governed_context_digest=DIGEST,
        gate_package_digest=DIGEST,
        stop_epoch=stop_epoch,
        fencing_token=fencing_token,
        issued_at=T0,
        expires_at=T0 + timedelta(seconds=4),
    )


def _expectation(lease: CapabilityLease, attempt: int) -> LeaseExpectation:
    return LeaseExpectation(
        capability_id=lease.capability_id,
        effective_principal_id=lease.effective_principal_id,
        delegation_ref=lease.delegation_ref,
        action_instance_id=lease.action_instance_id,
        governed_context_digest=lease.governed_context_digest,
        gate_package_digest=lease.gate_package_digest,
        stop_epoch=lease.stop_epoch,
        fencing_token=lease.fencing_token,
        emission_attempt=attempt,
        at=T0,
    )


@dataclass
class LeaseReference:
    """Reference model of LLD v1.1 :71-81: the authoritative stop epoch and fencing token, the clock,
    the revoked and the consumed leases. Every lease is issued at T0 for epoch 0 and token 1."""

    now: datetime = T0
    stop_epoch: int = 0
    fencing_token: int = 1
    revoked: set[str] = field(default_factory=set)
    consumed: set[str] = field(default_factory=set)

    def consume(self, lease_id: str) -> str:
        if not (T0 <= self.now < T0 + timedelta(seconds=4)):
            return "LEASE_EXPIRED"
        if lease_id in self.revoked:
            return "LEASE_REVOKED"
        if self.stop_epoch != 0:
            return "STOP_EPOCH_MISMATCH"
        if self.fencing_token != 1:
            return "FENCING_TOKEN_STALE"
        if lease_id in self.consumed:
            return "LEASE_ALREADY_CONSUMED"
        self.consumed.add(lease_id)
        return "CONSUMED"


class LeaseWorld:
    """The runtime under test: the one-shot ledger over the authoritative in-memory state."""

    def __init__(self) -> None:
        self.clock = InMemoryTrustedClock(T0)
        self.state = InMemoryLeaseState(stop_epoch=0, fencing_tokens={ACTION: 1})
        self.ledger = LeaseConsumptionLedger(clock=self.clock, state=self.state)
        self.attempt = 0

    def consume(self, lease_id: str) -> str:
        self.attempt += 1
        lease = _lease(lease_id, stop_epoch=0, fencing_token=1)
        try:
            receipt = self.ledger.consume(lease, _expectation(lease, self.attempt), signature_verified=True)
        except GovernanceFault as fault:
            return fault.reason_code
        assert receipt.consumption_key == (lease_id, ACTION, self.attempt)
        return "CONSUMED"


OPERATIONS = ("consume:lease-1", "consume:lease-2", "revoke:lease-1", "advance-fencing", "advance-stop-epoch", "tick")


def _step(world: LeaseWorld, model: LeaseReference, operation: str) -> tuple[str | None, str | None]:
    kind, _, argument = operation.partition(":")
    if kind == "consume":
        return world.consume(argument), model.consume(argument)
    if kind == "revoke":
        world.state.revoke(argument)
        model.revoked.add(argument)
    elif kind == "advance-fencing":
        model.fencing_token += 1
        world.state.set_fencing_token(ACTION, model.fencing_token)
    elif kind == "advance-stop-epoch":
        model.stop_epoch += 1
        world.state.set_stop_epoch(model.stop_epoch)
    elif kind == "tick":
        world.clock.advance(timedelta(seconds=3))
        model.now += timedelta(seconds=3)
    return None, None


class LeaseLedgerMachine(RuleBasedStateMachine):
    """Stateful property: the lease ledger and the reference model agree on every operation."""

    def __init__(self) -> None:
        super().__init__()
        self.world = LeaseWorld()
        self.model = LeaseReference()

    @rule(operation=st.sampled_from(OPERATIONS))
    def operate(self, operation: str) -> None:
        observed, predicted = _step(self.world, self.model, operation)
        assert observed == predicted, f"{operation}: runtime {observed}, model {predicted}"

    @invariant()
    def consumed_at_most_once(self) -> None:
        for lease_id in LEASE_IDS:
            recorded = self.world.state.consumption(lease_id)
            assert (recorded is not None) == (lease_id in self.model.consumed)


LeaseLedgerMachine.TestCase.settings = MACHINE_PROFILE
TestLeaseLedgerStateful = LeaseLedgerMachine.TestCase

LEASE_BOUND = 5


def test_lease_bounded_model_checking_every_operation_sequence_up_to_the_bound():
    """Every sequence of up to LEASE_BOUND operations over two leases of one action: the runtime
    outcome equals the reference model at every step, and no lease is ever consumed twice or after
    expiry, revocation, a stop epoch change or a fencing token change."""
    sequences = 0
    for length in range(1, LEASE_BOUND + 1):
        for sequence in itertools.product(OPERATIONS, repeat=length):
            world, model = LeaseWorld(), LeaseReference()
            consumed: list[str] = []
            for operation in sequence:
                observed, predicted = _step(world, model, operation)
                assert observed == predicted, f"{sequence}: {operation} runtime {observed}, model {predicted}"
                if observed == "CONSUMED":
                    consumed.append(operation)
            assert len(consumed) == len(set(consumed)), sequence
            sequences += 1
    assert sequences == sum(len(OPERATIONS) ** length for length in range(1, LEASE_BOUND + 1))
