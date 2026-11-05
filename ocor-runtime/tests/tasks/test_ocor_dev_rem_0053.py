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
* NCR-C6-006 -- LLD v1.1 :171 (thirteen distinct immutable records, none an alias of another),
  LLD v1.1 :320 (GatePackage content, immutable, digest recomputed by every consumer), ADD v1.3
  :156 (OutcomeAssessment refers to the ExecutionResult without coinciding with it, admitted
  by new Observation/Evidence), ADD v1.3 :384 (the command carries the GatePackage digest and
  the governed_context digest), Register FR-008 :59, FR-031 :121, FR-033 :123 and FR-076 :208.
* NCR-C6-001 -- ADD v1.3 :2849-2850 (G-APPROVAL: no approver equals the proposer, signatures
  bound to proposal digest, revision, release and expiry; G-DECISION: signed, unexpired,
  bounded to effect, target, parameters and validity window), LLD v1.1 :254, Register FR-003
  :45, NFR-005 :46 (self-approval, expired approval, scope mismatch and replay rejected) and
  FR-111 :259.
* NCR-C6-008 -- ADD v1.3 :3298-3307 (approval obligation by risk class), :3334 (R3 ApprovalSet
  expires ten minutes after the second signature, not renewable), :3338 (Domain Approver and
  National Approver quorum), Register FR-079 :211 and FR-003 :45.
* NCR-C6-002 -- ADD v1.3 :2847 (G-CONTRACT: signed, active ActionType), :3298 (without a valid
  risk classification the mutative request is denied), LLD v1.1 :268 (ACT-T07: NOT_REQUIRED only
  for a gate not required on a non-canonical target), Register FR-079 :211, NFR-029 :212 and
  FR-080 :213. The engine composes G-CONTRACT, G-AUTHORITY, G-APPROVAL and G-DECISION.

The FSM and the gate cases are in-process: the FSM is a pure component whose durable effect sink
and state store are ports. The engine cases commit through the real C3 on PostgreSQL
(``OCOR_LIVE_POSTGRES_DSN``), like the engine suites of OCOR-DEV-0030 and REM-0050.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import inspect
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import ModuleType
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



# --- NCR-C6-006, NCR-C6-001, NCR-C6-008: records, G-APPROVAL and G-DECISION -------------------

RECORD_NAMES = (
    "ActionProposal",
    "PolicyAuthorityDecision",
    "Approval",
    "ApprovalSet",
    "Decision",
    "ActionIntent",
    "GatePackage",
    "ActionCommand",
    "DeliveryAttempt",
    "ExecutionResult",
    "OutcomeAssessment",
    "ConflictScope",
    "IndeterminateEffectAdjudication",
)
GATE_PACKAGE_CONTENT = (
    "proposal_digest",
    "expected_revision",
    "governed_context_digest",
    "policy_bundle_digest",
    "ontology_release_digest",
    "authority_ref",
    "approval_set_digest",
    "adapter_binding_digest",
    "projection_watermark",
    "stop_epoch",
    "valid_from",
    "valid_until",
    "conflict_scope_digest",
    "risk_class",
    "evidence_refs",
    "alternative_refs",
    "dissent_refs",
    "expected_effects",
    "compensation_ref",
    "artifact_digest",
    "canonical_commit_ref",
)
PROPOSER = "urn:ocor:human:proposer"
DOMAIN = "urn:ocor:human:domain-approver"
NATIONAL = "urn:ocor:human:national-approver"
SECOND_DOMAIN = "urn:ocor:human:second-domain-approver"
SUSPENDED = "urn:ocor:human:suspended-approver"
AUTHORITY = "urn:ocor:authority:national-duty"
OTHER_AUTHORITY = "urn:ocor:authority:other"
ACTION = "urn:ocor:action:interagency-1"


def _sha(label: str) -> str:
    return "urn:sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


RELEASE = _sha("release-1")


def _mod(name: str) -> ModuleType:
    return importlib.import_module(f"ocor_runtime.c6.{name}")


def _key(label: str) -> Any:
    from ocor_runtime.c1.signing import Ed25519SigningKey

    return Ed25519SigningKey.from_seed(hashlib.sha256(label.encode("utf-8")).digest())


class Releases:
    def __init__(self) -> None:
        self.digest = RELEASE

    def active_release_digest(self) -> str:
        return self.digest


class GateWorld:
    """A Human Gate, a Decision gate and the signers of one action instance."""

    def __init__(self, *, risk: str = "R3_HIGH_IMPACT", now: datetime = NOW) -> None:
        from ocor_runtime.c2_identity import IdentityRecord, IdentityRegistry
        from ocor_runtime.kernel.governance import InMemoryTrustedClock, RiskClass

        self.records = _mod("records")
        self.gate = _mod("human_gate")
        self.clock = InMemoryTrustedClock(now)
        roles = {
            PROPOSER: ("DOMAIN_APPROVER", "ACTIVE"),
            DOMAIN: ("DOMAIN_APPROVER", "ACTIVE"),
            NATIONAL: ("NATIONAL_APPROVER", "ACTIVE"),
            SECOND_DOMAIN: ("DOMAIN_APPROVER", "ACTIVE"),
            SUSPENDED: ("NATIONAL_APPROVER", "SUSPENDED"),
        }
        self.identities = IdentityRegistry(
            IdentityRecord(
                canonical_id=principal,
                attributes={"principal_kind": "HUMAN", "status": status, "roles": role},
            )
            for principal, (role, status) in roles.items()
        )
        self.approvers = self.gate.InMemorySignerKeyring()
        for principal in roles:
            self.approvers.register(principal, "k1", _key(principal).public_key)
        self.authorities = self.gate.InMemorySignerKeyring()
        for principal in (AUTHORITY, OTHER_AUTHORITY):
            self.authorities.register(principal, "k1", _key(principal).public_key)
        self.releases = Releases()
        self.approval_gate = self.gate.ApprovalGate(
            identities=self.identities,
            approvers=self.approvers,
            releases=self.releases,
            clock=self.clock,
            signing_key=_key("gate"),
            gate_id="urn:ocor:component:c6:human-gate",
            keyid="gate-k1",
        )
        self.decision_gate = self.gate.DecisionGate(
            authorities=self.authorities, approval_gate=self.approval_gate, clock=self.clock
        )
        self.proposal = self.records.ActionProposal(
            action_instance_id=ACTION,
            proposer_id=PROPOSER,
            action_type_ref="urn:ocor:action-type:interagency-tasking",
            action_type_digest=_sha("action-type"),
            effect_class="EXTERNAL_COMMAND",
            risk_class=RiskClass[risk],
            target_ref="urn:ocor:target:site-1",
            parameters={"asset": "urn:ocor:asset:1", "priority": 2},
            governed_context_digest=_sha("gcs"),
            expected_revision=4,
            evidence_refs=("urn:ocor:evidence:e1",),
            proposed_at=now - timedelta(minutes=5),
        )

    def approve(
        self,
        principal: str,
        role: str,
        *,
        signed_at: datetime | None = None,
        expires_at: datetime | None = None,
        proposal: Any = None,
        release: str = RELEASE,
        signer: str | None = None,
        approval_id: str | None = None,
    ) -> Any:
        signed = signed_at or self.clock.now() - timedelta(minutes=1)
        return self.gate.sign_approval(
            _key(signer or principal),
            keyid="k1",
            approval_id=approval_id or f"urn:ocor:approval:{principal}:{signed.isoformat()}",
            proposal=proposal or self.proposal,
            release_digest=release,
            approver_id=principal,
            role=role,
            signed_at=signed,
            expires_at=expires_at or signed + timedelta(hours=1),
        )

    def quorum(self) -> tuple[Any, Any]:
        return (self.approve(DOMAIN, "DOMAIN_APPROVER"), self.approve(NATIONAL, "NATIONAL_APPROVER"))

    def approval_set(self, approvals: Any = None, *, set_id: str = "urn:ocor:approval-set:1") -> Any:
        return self.approval_gate.assemble(
            self.proposal, approvals if approvals is not None else self.quorum(), approval_set_id=set_id
        )

    def conflict_scope(self) -> Any:
        return self.records.ConflictScope(
            scope_id="urn:ocor:conflict-scope:1",
            action_instance_id=ACTION,
            target_refs=("urn:ocor:target:site-1",),
            effect_class="EXTERNAL_COMMAND",
            opened_at=self.clock.now(),
        )

    def package(self, approval_set: Any, **overrides: Any) -> Any:
        now = self.clock.now()
        values: dict[str, Any] = {
            "action_instance_id": ACTION,
            "proposal_digest": self.proposal.digest(),
            "expected_revision": 4,
            "canonical_commit_ref": "urn:ocor:commit:41",
            "governed_context_digest": _sha("gcs"),
            "policy_bundle_digest": _sha("policy"),
            "ontology_release_digest": RELEASE,
            "authority_ref": AUTHORITY,
            "approval_set_digest": approval_set.digest(),
            "adapter_binding_digest": _sha("adapter"),
            "projection_watermark": "urn:ocor:watermark:77",
            "stop_epoch": 3,
            "valid_from": now - timedelta(minutes=2),
            "valid_until": now + timedelta(minutes=30),
            "conflict_scope_digest": self.conflict_scope().digest(),
            "risk_class": self.proposal.risk_class,
            "evidence_refs": ("urn:ocor:evidence:e1",),
            "alternative_refs": ("urn:ocor:alternative:a1",),
            "dissent_refs": (),
            "expected_effects": ("urn:ocor:effect:tasking-issued",),
            "compensation_ref": "urn:ocor:compensation:recall",
            "artifact_digest": _sha("artifact"),
            "frozen_at": now,
        }
        values.update(overrides)
        return self.records.GatePackage(**values)

    def decide(
        self,
        package_digest: str,
        *,
        authority: str = AUTHORITY,
        signer: str | None = None,
        outcome: str = "ACCEPT",
        proposal: Any = None,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        decision_id: str = "urn:ocor:decision:1",
    ) -> Any:
        now = self.clock.now()
        return self.gate.sign_decision(
            _key(signer or authority),
            keyid="k1",
            decision_id=decision_id,
            authority_id=authority,
            proposal=proposal or self.proposal,
            gate_package_digest=package_digest,
            outcome=outcome,
            rationale="within the approved ceiling" if outcome == "ACCEPT" else "outside the approved ceiling",
            valid_from=valid_from or now - timedelta(minutes=1),
            valid_until=valid_until or now + timedelta(minutes=5),
            decided_at=now,
        )

    def admitted(self) -> tuple[Any, Any, Any]:
        approval_set = self.approval_set()
        package = self.package(approval_set)
        decision = self.decide(package.digest())
        admitted = self.decision_gate.admit(
            decision, proposal=self.proposal, package=package, package_digest=package.digest(), approval_set=approval_set
        )
        return approval_set, package, admitted

    def chain(self) -> dict[str, Any]:
        """Every record of one action instance, from proposal to outcome assessment."""
        records = self.records
        approvals = self.quorum()
        approval_set = self.approval_set(approvals)
        package = self.package(approval_set)
        decision = self.decide(package.digest())
        self.decision_gate.admit(
            decision, proposal=self.proposal, package=package, package_digest=package.digest(), approval_set=approval_set
        )
        now = self.clock.now()
        intent = records.ActionIntent.from_decision(
            intent_id="urn:ocor:intent:1", decision=decision, package=package, package_digest=package.digest(), created_at=now
        )
        command = records.ActionCommand.issue(
            command_id="urn:ocor:command:1",
            intent=intent,
            package=package,
            package_digest=package.digest(),
            parameters={"asset": "urn:ocor:asset:1", "priority": 2},
            idempotency_key="c6-action-1",
            deadline=now + timedelta(minutes=1),
        )
        attempt = records.DeliveryAttempt.for_command(
            attempt_id="urn:ocor:attempt:1",
            command=command,
            package=package,
            package_digest=package.digest(),
            emission_attempt=1,
            lease_ref="urn:ocor:lease:1",
            fence_outcome="PASSED",
            attempted_at=now,
        )
        result = records.ExecutionResult.for_attempt(
            result_id="urn:ocor:result:1",
            attempt=attempt,
            adapter_status="COMPLETED",
            adapter_result_digest=_sha("adapter-result"),
            evidence_refs=("urn:ocor:evidence:adapter-1",),
            observed_at=now + timedelta(seconds=1),
        )
        assessment = records.OutcomeAssessment.for_result(
            assessment_id="urn:ocor:assessment:1",
            result=result,
            observation_refs=("urn:ocor:observation:o1",),
            evidence_refs=("urn:ocor:evidence:observed-1",),
            assessment="EFFECT_ACHIEVED",
            assessed_at=now + timedelta(seconds=2),
        )
        policy = records.PolicyAuthorityDecision(
            action_instance_id=ACTION,
            proposal_digest=self.proposal.digest(),
            outcome="PERMIT",
            reason_code="POLICY_PERMIT",
            risk_class=self.proposal.risk_class,
            policy_bundle_digest=_sha("policy"),
            authority_ref=AUTHORITY,
            evaluated_at=now,
        )
        scope = self.conflict_scope()
        adjudication = records.IndeterminateEffectAdjudication(
            adjudication_id="urn:ocor:adjudication:1",
            conflict_scope_digest=scope.digest(),
            command_digest=command.digest(),
            outcome="EFFECT_APPLIED",
            evidence_refs=("urn:ocor:evidence:adjudication-1",),
            adjudicator_id=AUTHORITY,
            adjudicated_at=now,
            valid_until=now + timedelta(minutes=10),
        )
        return {
            "ActionProposal": self.proposal,
            "PolicyAuthorityDecision": policy,
            "Approval": approvals[0],
            "ApprovalSet": approval_set,
            "Decision": decision,
            "ActionIntent": intent,
            "GatePackage": package,
            "ActionCommand": command,
            "DeliveryAttempt": attempt,
            "ExecutionResult": result,
            "OutcomeAssessment": assessment,
            "ConflictScope": scope,
            "IndeterminateEffectAdjudication": adjudication,
        }


def _gate_reason(call: Callable[[], Any]) -> str:
    gate = _mod("human_gate")
    with pytest.raises(gate.ApprovalGateError) as excinfo:
        call()
    return str(excinfo.value.reason_code)


def _record_reason(call: Callable[[], Any]) -> str:
    records = _mod("records")
    with pytest.raises(records.C6RecordError) as excinfo:
        call()
    return str(excinfo.value.reason_code)


def test_ncr_c6_006_conforms() -> None:
    """LLD v1.1 :171 and :320, ADD v1.3 :156 and :384: thirteen distinct immutable records."""
    records = _mod("records")
    classes = [getattr(records, name) for name in RECORD_NAMES]
    assert len(set(classes)) == 13
    for cls in classes:
        assert dataclasses.is_dataclass(cls)
        assert cls.__dataclass_params__.frozen
        assert not any(issubclass(cls, other) for other in classes if other is not cls)
    chain = GateWorld().chain()
    assert set(chain) == set(RECORD_NAMES)
    for name, record in chain.items():
        assert type(record).__name__ == name
        assert record.to_mapping()["record_type"] == name
        first = dataclasses.fields(record)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(record, first, "changed")
    assert len({record.digest() for record in chain.values()}) == 13
    package = chain["GatePackage"]
    assert set(GATE_PACKAGE_CONTENT) <= set(package.to_mapping())
    command = chain["ActionCommand"]
    assert command.gate_package_digest == package.digest()
    assert command.governed_context_digest == package.governed_context_digest
    tampered = dataclasses.replace(package, stop_epoch=package.stop_epoch + 1)
    assert _record_reason(lambda: records.verify_gate_package(tampered, package.digest())) == (
        "GATE_PACKAGE_DIGEST_MISMATCH"
    )
    assessment, result = chain["OutcomeAssessment"], chain["ExecutionResult"]
    assert assessment.execution_result_digest == result.digest()
    assert assessment.digest() != result.digest()
    assert not set(assessment.evidence_refs) & set(result.evidence_refs)


@pytest.mark.parametrize("consumer", ["ActionIntent", "ActionCommand", "DeliveryAttempt", "DecisionGate"])
@pytest.mark.parametrize("tampered", [False, True])
def test_every_consumer_recomputes_the_gate_package_digest(consumer: str, tampered: bool) -> None:
    world = GateWorld()
    records = world.records
    chain = world.chain()
    package, decision, intent, command = (
        chain["GatePackage"],
        chain["Decision"],
        chain["ActionIntent"],
        chain["ActionCommand"],
    )
    claimed = package.digest()
    presented = dataclasses.replace(package, projection_watermark="urn:ocor:watermark:78") if tampered else package
    now = world.clock.now()
    calls: dict[str, Callable[[], Any]] = {
        "ActionIntent": lambda: records.ActionIntent.from_decision(
            intent_id="urn:ocor:intent:2", decision=decision, package=presented, package_digest=claimed, created_at=now
        ),
        "ActionCommand": lambda: records.ActionCommand.issue(
            command_id="urn:ocor:command:2",
            intent=intent,
            package=presented,
            package_digest=claimed,
            parameters={"asset": "urn:ocor:asset:1", "priority": 2},
            idempotency_key="c6-action-2",
            deadline=now + timedelta(minutes=1),
        ),
        "DeliveryAttempt": lambda: records.DeliveryAttempt.for_command(
            attempt_id="urn:ocor:attempt:2",
            command=command,
            package=presented,
            package_digest=claimed,
            emission_attempt=2,
            lease_ref="urn:ocor:lease:2",
            fence_outcome="PASSED",
            attempted_at=now,
        ),
    }
    if consumer == "DecisionGate":
        fresh = GateWorld()
        approval_set = fresh.approval_set()
        good = fresh.package(approval_set)
        shown = dataclasses.replace(good, projection_watermark="urn:ocor:watermark:78") if tampered else good
        call = lambda: fresh.decision_gate.admit(  # noqa: E731
            fresh.decide(good.digest()),
            proposal=fresh.proposal,
            package=shown,
            package_digest=good.digest(),
            approval_set=approval_set,
        )
        if tampered:
            assert _gate_reason(call) == "GATE_PACKAGE_DIGEST_MISMATCH"
        else:
            assert call().gate_package_digest == good.digest()
        return
    if tampered:
        assert _record_reason(calls[consumer]) == "GATE_PACKAGE_DIGEST_MISMATCH"
    else:
        assert calls[consumer]().gate_package_digest == claimed


def test_a_command_carries_only_the_decided_parameters_within_the_package_window() -> None:
    world = GateWorld()
    records = world.records
    chain = world.chain()
    package, intent = chain["GatePackage"], chain["ActionIntent"]
    now = world.clock.now()

    def issue(parameters: dict[str, Any], deadline: datetime) -> Any:
        return records.ActionCommand.issue(
            command_id="urn:ocor:command:3",
            intent=intent,
            package=package,
            package_digest=package.digest(),
            parameters=parameters,
            idempotency_key="c6-action-3",
            deadline=deadline,
        )

    decided = {"asset": "urn:ocor:asset:1", "priority": 2}
    assert issue(decided, now + timedelta(minutes=1)).parameters == decided
    assert _record_reason(lambda: issue({"asset": "urn:ocor:asset:1", "priority": 3}, now)) == "RECORD_INVALID"
    assert _record_reason(lambda: issue(decided, package.valid_until + timedelta(seconds=1))) == "RECORD_INVALID"


def test_an_outcome_assessment_is_admitted_only_by_new_evidence() -> None:
    world = GateWorld()
    records = world.records
    result = world.chain()["ExecutionResult"]

    def assess(evidence: tuple[str, ...], at: datetime) -> Any:
        return records.OutcomeAssessment.for_result(
            assessment_id="urn:ocor:assessment:2",
            result=result,
            observation_refs=("urn:ocor:observation:o2",),
            evidence_refs=evidence,
            assessment="EFFECT_PARTIAL",
            assessed_at=at,
        )

    later = result.observed_at + timedelta(seconds=1)
    assert assess(("urn:ocor:evidence:observed-2",), later).execution_result_digest == result.digest()
    assert _record_reason(lambda: assess(result.evidence_refs, later)) == "RECORD_INVALID"
    assert _record_reason(lambda: assess(("urn:ocor:evidence:observed-2",), result.observed_at)) == "RECORD_INVALID"


@pytest.mark.parametrize("fence_outcome", ["PASSED", "INVALIDATED"])
def test_an_execution_result_requires_an_attempt_that_passed_the_fence(fence_outcome: str) -> None:
    world = GateWorld()
    records = world.records
    chain = world.chain()
    attempt = dataclasses.replace(chain["DeliveryAttempt"], fence_outcome=fence_outcome)

    def result() -> Any:
        return records.ExecutionResult.for_attempt(
            result_id="urn:ocor:result:2",
            attempt=attempt,
            adapter_status="COMPLETED",
            adapter_result_digest=_sha("adapter-result-2"),
            evidence_refs=("urn:ocor:evidence:adapter-2",),
            observed_at=attempt.attempted_at,
        )

    if fence_outcome == "PASSED":
        assert result().attempt_digest == attempt.digest()
    else:
        assert _record_reason(result) == "RECORD_INVALID"


@pytest.mark.parametrize(
    "field,value",
    [
        (None, None),
        ("proposed_at", datetime(2026, 11, 5, 12, 0, 0)),
        ("action_type_digest", "sha256:abc"),
        ("evidence_refs", ()),
        ("evidence_refs", "urn:ocor:evidence:e1"),
        ("expected_revision", True),
        ("expected_revision", -1),
        ("risk_class", 9),
        ("target_ref", " urn:ocor:target:site-1"),
        ("parameters", {"asset": 1.5}),
        ("parameters", {1: "x"}),
    ],
)
def test_a_record_with_a_malformed_field_is_refused(field: str | None, value: Any) -> None:
    world = GateWorld()
    if field is None:
        assert dataclasses.replace(world.proposal).digest() == world.proposal.digest()
        return
    assert _record_reason(lambda: dataclasses.replace(world.proposal, **{field: value})) == "RECORD_INVALID"


def test_ncr_c6_001_conforms() -> None:
    """ADD v1.3 :2849-2850, LLD v1.1 :254, FR-003, NFR-005, FR-111: G-APPROVAL and G-DECISION."""
    world = GateWorld()
    approval_set, package, decision = world.admitted()
    assert approval_set.approver_ids == tuple(sorted((DOMAIN, NATIONAL)))
    assert PROPOSER not in approval_set.approver_ids
    assert decision.gate_package_digest == package.digest()

    world = GateWorld()
    self_approval = (world.approve(PROPOSER, "DOMAIN_APPROVER"), world.approve(NATIONAL, "NATIONAL_APPROVER"))
    assert _gate_reason(lambda: world.approval_set(self_approval)) == "SELF_APPROVAL"
    expired = (
        world.approve(DOMAIN, "DOMAIN_APPROVER", signed_at=NOW - timedelta(hours=2), expires_at=NOW - timedelta(hours=1)),
        world.approve(NATIONAL, "NATIONAL_APPROVER"),
    )
    assert _gate_reason(lambda: world.approval_set(expired)) == "APPROVAL_EXPIRED"
    other = dataclasses.replace(world.proposal, target_ref="urn:ocor:target:site-2")
    mismatch = (world.approve(DOMAIN, "DOMAIN_APPROVER", proposal=other), world.approve(NATIONAL, "NATIONAL_APPROVER"))
    assert _gate_reason(lambda: world.approval_set(mismatch)) == "SCOPE_MISMATCH"
    approvals = world.quorum()
    world.approval_set(approvals)
    assert _gate_reason(lambda: world.approval_set(approvals, set_id="urn:ocor:approval-set:2")) == "APPROVAL_REPLAYED"

    world = GateWorld()
    approval_set, package, decision = world.admitted()
    assert _gate_reason(
        lambda: world.decision_gate.admit(
            decision, proposal=world.proposal, package=package, package_digest=package.digest(), approval_set=approval_set
        )
    ) == "DECISION_REPLAYED"
    world = GateWorld()
    approval_set = world.approval_set()
    package = world.package(approval_set)
    forged = world.decide(package.digest(), signer=OTHER_AUTHORITY)
    assert _gate_reason(
        lambda: world.decision_gate.admit(
            forged, proposal=world.proposal, package=package, package_digest=package.digest(), approval_set=approval_set
        )
    ) == "DECISION_SIGNATURE_INVALID"


APPROVAL_CASES: dict[str, Callable[[GateWorld], tuple[Any, ...]]] = {
    "valid": lambda w: w.quorum(),
    "forged-signature": lambda w: (w.approve(DOMAIN, "DOMAIN_APPROVER", signer=SECOND_DOMAIN), w.quorum()[1]),
    "other-proposal": lambda w: (
        w.approve(DOMAIN, "DOMAIN_APPROVER", proposal=dataclasses.replace(w.proposal, parameters={"asset": "x"})),
        w.quorum()[1],
    ),
    "other-revision": lambda w: (
        w.approve(DOMAIN, "DOMAIN_APPROVER", proposal=dataclasses.replace(w.proposal, expected_revision=5)),
        w.quorum()[1],
    ),
    "other-release": lambda w: (w.approve(DOMAIN, "DOMAIN_APPROVER", release=_sha("release-0")), w.quorum()[1]),
    "self-approval": lambda w: (w.approve(PROPOSER, "DOMAIN_APPROVER"), w.quorum()[1]),
    "suspended-approver": lambda w: (w.quorum()[0], w.approve(SUSPENDED, "NATIONAL_APPROVER")),
    "role-not-held": lambda w: (w.quorum()[0], w.approve(SECOND_DOMAIN, "NATIONAL_APPROVER")),
    "expired": lambda w: (
        w.approve(DOMAIN, "DOMAIN_APPROVER", signed_at=NOW - timedelta(hours=2), expires_at=NOW - timedelta(seconds=1)),
        w.quorum()[1],
    ),
    "not-yet-signed": lambda w: (w.approve(DOMAIN, "DOMAIN_APPROVER", signed_at=NOW + timedelta(seconds=1)), w.quorum()[1]),
    "one-approver": lambda w: (w.quorum()[0],),
    "same-principal-twice": lambda w: (
        w.approve(DOMAIN, "DOMAIN_APPROVER"),
        w.approve(DOMAIN, "DOMAIN_APPROVER", signed_at=NOW - timedelta(seconds=30)),
    ),
    "two-domain-approvers": lambda w: (w.quorum()[0], w.approve(SECOND_DOMAIN, "DOMAIN_APPROVER")),
}
APPROVAL_REASONS = {
    "forged-signature": "SIGNATURE_INVALID",
    "other-proposal": "SCOPE_MISMATCH",
    "other-revision": "SCOPE_MISMATCH",
    "other-release": "SCOPE_MISMATCH",
    "self-approval": "SELF_APPROVAL",
    "suspended-approver": "APPROVER_NOT_AUTHORIZED",
    "role-not-held": "APPROVER_NOT_AUTHORIZED",
    "expired": "APPROVAL_EXPIRED",
    "not-yet-signed": "APPROVAL_EXPIRED",
    "one-approver": "QUORUM_NOT_MET",
    "same-principal-twice": "QUORUM_NOT_MET",
    "two-domain-approvers": "QUORUM_NOT_MET",
}


@pytest.mark.parametrize("case", sorted(APPROVAL_CASES))
def test_g_approval_admits_only_the_signed_bound_quorum_of_distinct_humans(case: str) -> None:
    world = GateWorld()
    approvals = APPROVAL_CASES[case](world)
    if case == "valid":
        approval_set = world.approval_set(approvals)
        assert approval_set.approval_digests == tuple(sorted(item.digest() for item in approvals))
        assert world.approval_gate.verify_set(approval_set, world.proposal) == approval_set
        return
    assert _gate_reason(lambda: world.approval_set(approvals)) == APPROVAL_REASONS[case]


def test_a_release_change_invalidates_the_approvals() -> None:
    world = GateWorld()
    approvals = world.quorum()
    world.releases.digest = _sha("release-2")
    assert _gate_reason(lambda: world.approval_set(approvals)) == "SCOPE_MISMATCH"


DECISION_REASONS = {
    "valid": None,
    "forged-signature": "DECISION_SIGNATURE_INVALID",
    "unknown-authority": "DECISION_SIGNATURE_INVALID",
    "not-competent": "DECISION_NOT_COMPETENT",
    "rejected": "DECISION_REJECTED",
    "other-effect": "DECISION_SCOPE_MISMATCH",
    "other-target": "DECISION_SCOPE_MISMATCH",
    "other-parameters": "DECISION_SCOPE_MISMATCH",
    "beyond-approval-set": "DECISION_SCOPE_MISMATCH",
    "before-package-window": "DECISION_SCOPE_MISMATCH",
    "expired": "DECISION_EXPIRED",
    "not-yet-valid": "DECISION_EXPIRED",
    "other-package": "DECISION_SCOPE_MISMATCH",
    "unsigned-legacy": "DECISION_SIGNATURE_INVALID",
}


@pytest.mark.parametrize("case", sorted(DECISION_REASONS))
def test_g_decision_admits_only_a_signed_unexpired_bounded_decision(case: str) -> None:
    world = GateWorld()
    approval_set = world.approval_set()
    package = world.package(approval_set)
    digest = package.digest()
    now = world.clock.now()
    proposal = world.proposal
    builders: dict[str, Callable[[], Any]] = {
        "valid": lambda: world.decide(digest),
        "forged-signature": lambda: world.decide(digest, signer=OTHER_AUTHORITY),
        "unknown-authority": lambda: world.decide(digest, authority="urn:ocor:authority:unknown"),
        "not-competent": lambda: world.decide(digest, authority=OTHER_AUTHORITY),
        "rejected": lambda: world.decide(digest, outcome="REJECT"),
        "other-effect": lambda: world.decide(digest, proposal=dataclasses.replace(proposal, effect_class="CANONICAL_COMMIT")),
        "other-target": lambda: world.decide(digest, proposal=dataclasses.replace(proposal, target_ref="urn:ocor:target:x")),
        "other-parameters": lambda: world.decide(digest, proposal=dataclasses.replace(proposal, parameters={"asset": "x"})),
        "beyond-approval-set": lambda: world.decide(digest, valid_until=approval_set.expires_at + timedelta(seconds=1)),
        "before-package-window": lambda: world.decide(digest, valid_from=package.valid_from - timedelta(seconds=1)),
        "expired": lambda: world.decide(digest, valid_from=now - timedelta(minutes=2), valid_until=now),
        "not-yet-valid": lambda: world.decide(digest, valid_from=now + timedelta(seconds=1)),
        "other-package": lambda: world.decide(_sha("other-package")),
        "unsigned-legacy": lambda: _mod("engine").Decision(
            action_id=ACTION, decided_by=AUTHORITY, accepted=True, rationale="legacy", decided_at=now
        ),
    }
    decision = builders[case]()

    def admit() -> Any:
        return world.decision_gate.admit(
            decision, proposal=proposal, package=package, package_digest=digest, approval_set=approval_set
        )

    if DECISION_REASONS[case] is None:
        assert admit() == decision
        return
    assert _gate_reason(admit) == DECISION_REASONS[case]


def test_an_approval_set_serves_one_decision_only() -> None:
    world = GateWorld()
    approval_set, package, _ = world.admitted()
    second = world.decide(package.digest(), decision_id="urn:ocor:decision:2")
    assert _gate_reason(
        lambda: world.decision_gate.admit(
            second, proposal=world.proposal, package=package, package_digest=package.digest(), approval_set=approval_set
        )
    ) == "APPROVAL_REPLAYED"


def test_a_tampered_or_foreign_approval_set_is_refused() -> None:
    world = GateWorld()
    approval_set = world.approval_set()
    forged = dataclasses.replace(approval_set, expires_at=approval_set.expires_at + timedelta(minutes=5))
    assert _gate_reason(lambda: world.approval_gate.verify_set(forged, world.proposal)) == "APPROVAL_SET_INVALID"
    other = dataclasses.replace(world.proposal, expected_revision=5)
    assert _gate_reason(lambda: world.approval_gate.verify_set(approval_set, other)) == "APPROVAL_SET_INVALID"
    assert world.approval_gate.verify_set(approval_set, world.proposal) == approval_set


def test_ncr_c6_008_conforms() -> None:
    """ADD v1.3 :3298-3307, :3334, :3338, FR-079, FR-003: risk-derived quorum and R3 expiry."""
    gate = _mod("human_gate")
    from ocor_runtime.kernel.governance import RiskClass

    r3 = gate.approval_requirement(RiskClass.R3_HIGH_IMPACT)
    assert r3.mutation_admitted and r3.quorum == 2
    assert r3.required_roles == frozenset({"DOMAIN_APPROVER", "NATIONAL_APPROVER"})
    assert r3.set_validity_after_last_signature == timedelta(minutes=10)
    r2 = gate.approval_requirement(RiskClass.R2_CONTROLLED)
    assert r2.mutation_admitted and r2.quorum == 1
    for risk in (RiskClass.R0_INFORMATIONAL, RiskClass.R1_LOW):
        assert not gate.approval_requirement(risk).mutation_admitted
    assert set(inspect.signature(gate.ApprovalGate.assemble).parameters) == {"self", "proposal", "approvals", "approval_set_id"}

    world = GateWorld()
    first = world.approve(DOMAIN, "DOMAIN_APPROVER", signed_at=NOW - timedelta(minutes=8))
    second = world.approve(NATIONAL, "NATIONAL_APPROVER", signed_at=NOW - timedelta(minutes=1))
    approval_set = world.approval_set((first, second))
    assert approval_set.completed_at == second.signed_at
    assert approval_set.expires_at == second.signed_at + timedelta(minutes=10)
    world.clock.advance(timedelta(minutes=8, seconds=59))
    assert world.approval_gate.verify_set(approval_set, world.proposal) == approval_set
    world.clock.advance(timedelta(seconds=1))
    assert _gate_reason(lambda: world.approval_gate.verify_set(approval_set, world.proposal)) == "APPROVAL_EXPIRED"
    assert _gate_reason(lambda: world.approval_set((first, second), set_id="urn:ocor:approval-set:renewed")) in {
        "APPROVAL_EXPIRED",
        "APPROVAL_REPLAYED",
    }
    assert _gate_reason(lambda: world.approval_set((first,), set_id="urn:ocor:approval-set:one")) == "QUORUM_NOT_MET"


@pytest.mark.parametrize("risk", ["R0_INFORMATIONAL", "R1_LOW", "R2_CONTROLLED", "R3_HIGH_IMPACT"])
def test_the_approval_obligation_follows_the_risk_class(risk: str) -> None:
    world = GateWorld(risk=risk)
    if risk in {"R0_INFORMATIONAL", "R1_LOW"}:
        assert _gate_reason(lambda: world.approval_set(world.quorum())) == "NO_MUTATION_ADMITTED"
        return
    if risk == "R2_CONTROLLED":
        single = (world.approve(DOMAIN, "DOMAIN_APPROVER"),)
        approval_set = world.approval_set(single)
        assert approval_set.approver_ids == (DOMAIN,)
        assert approval_set.expires_at == single[0].expires_at
        world = GateWorld(risk=risk)
        assert _gate_reason(lambda: world.approval_set((world.approve(PROPOSER, "DOMAIN_APPROVER"),))) == "SELF_APPROVAL"
        return
    assert _gate_reason(lambda: world.approval_set((world.approve(DOMAIN, "DOMAIN_APPROVER"),))) == "QUORUM_NOT_MET"
    assert world.approval_set().risk_class.name == "R3_HIGH_IMPACT"


@pytest.mark.parametrize("value", [None, True, 7, "R3_HIGH_IMPACT"])
def test_without_a_valid_risk_classification_the_mutation_is_denied(value: Any) -> None:
    gate = _mod("human_gate")
    assert _gate_reason(lambda: gate.approval_requirement(value)) == "NO_MUTATION_ADMITTED"


def test_an_r3_approval_set_ends_with_the_earliest_approval_expiry() -> None:
    world = GateWorld()
    first = world.approve(DOMAIN, "DOMAIN_APPROVER", expires_at=NOW + timedelta(minutes=2))
    second = world.approve(NATIONAL, "NATIONAL_APPROVER")
    approval_set = world.approval_set((first, second))
    assert approval_set.expires_at == NOW + timedelta(minutes=2)


# NCR-C6-002 -- ADD v1.3 :2847 (G-CONTRACT: signed, active ActionType declaring effect_class
# and risk_class, typed parameters, reliability fields, marking and provenance), ADD v1.3 :3298
# (without a valid risk classification the mutative request is denied), LLD v1.1 :268 (ACT-T07:
# NOT_REQUIRED only when the gate is not required and the target is not canonical), Register
# FR-079 :211 (approval obligation computed from the risk class and the effect type), NFR-029
# :212 (zero executions without the required Approval) and FR-080 :213 (an ActionType without
# its reliability fields is not published). The engine composes G-CONTRACT, G-AUTHORITY, the
# Human Gate (NCR-C6-001, NCR-C6-008) and G-DECISION before the canonical commit through C3.

ENGINE_NOW = datetime(2026, 11, 5, 15, 0, 0, tzinfo=UTC)
OPERATOR = "spiffe://ocor.test/workload/operator"
TARGET = "urn:ocor:target:rem0053:site-1"


class EffectSink:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def emit(self, event: Any, *, idempotency_key: str) -> dict[str, Any]:
        self.calls.append(event)
        return {"simulated": True, "action_id": event.payload["action_id"]}


class EngineSuite:
    """The engine on the real C3 (PostgreSQL), with the signed ActionTypes of the release."""

    def __init__(self) -> None:
        import os

        import test_ocor_dev_rem_0050 as governed_path
        from c6_action_fixture import ActionWorld
        from ocor_runtime.c3.service import PostgresC3Service
        from ocor_runtime.c6_capabilities import CapabilityAuthority
        from ocor_runtime.c7_emission import EmissionFence

        dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
        if not dsn:
            pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory: the engine commits through the real C3")
        self.engine_module = _mod("engine")
        governed = governed_path.GovernedC3(
            release=governed_path.RELEASE,
            preconditions=("urn:ocor:precondition:governed-action",),
            invariants=("urn:ocor:invariant:governed-action",),
        )
        self.context = governed.governed_context(purpose="rem0053-engine")
        self.c3 = PostgresC3Service(dsn, admission=governed.admission())
        self.c3.initialize()
        self.c3.reset()
        self.store = self.engine_module.C3CanonicalOutboxView(
            self.c3, tenant_id=self.context.tenant_id, aggregate_type="GovernedActionTarget"
        )
        self.world = ActionWorld(now=ENGINE_NOW, release=governed_path.RELEASE)
        self.authority = CapabilityAuthority(issuer="ocor-rem0053-authority")
        path = governed.engine_path(aggregate_type="GovernedActionTarget", governed_context=self.context)
        self.engine = self.world.engine(
            authority=self.authority,
            commit_port=self.c3,
            fence=EmissionFence(store=self.store),  # type: ignore[arg-type]
            canonical_path=path,
            emission_outbox=self.store,
        )
        self.types = {
            risk: self.world.action_type(f"urn:ocor:action-type:rem0053:{risk.lower()}", risk=risk, capability="act:launch")
            for risk in ("R0_INFORMATIONAL", "R1_LOW", "R2_CONTROLLED", "R3_HIGH_IMPACT")
        }
        self.sink = EffectSink()

    def proposal(self, risk: str = "R3_HIGH_IMPACT", **overrides: Any) -> Any:
        return self.world.proposal(
            self.types[risk],
            action_id=f"urn:ocor:action:rem0053:{uuid.uuid4()}",
            proposer=OPERATOR,
            target=TARGET,
            governed_context_digest=self.context.digest(),
            **overrides,
        )

    def lease(self, capability: str = "act:launch") -> Any:
        return self.authority.issue(
            subject=OPERATOR, capabilities=[capability], resources=[TARGET], issued_at=ENGINE_NOW, ttl=timedelta(hours=1)
        )

    def execute(self, proposal: Any, *, approval: Any, decision: Any, lease: Any = None) -> Any:
        return self.engine.execute(
            proposal,
            lease=lease if lease is not None else self.lease(),
            approval=approval,
            decision=decision,
            sink=self.sink,
            at=ENGINE_NOW,
        )

    def denial(self, proposal: Any, *, approval: Any, decision: Any, lease: Any = None) -> tuple[str, str | None]:
        with pytest.raises(self.engine_module.GovernedActionError) as excinfo:
            self.execute(proposal, approval=approval, decision=decision, lease=lease)
        return excinfo.value.reason_code, excinfo.value.cause_code

    def untouched(self) -> bool:
        return self.sink.calls == [] and self.store.get(TARGET) is None


def test_ncr_c6_002_conforms() -> None:
    """ADD v1.3 :2847, :3298, LLD v1.1 :268, FR-079, NFR-029, FR-080: the risk class is the signed
    ActionType's and a canonical target never takes NOT_REQUIRED."""
    records = _mod("records")
    gate = _mod("human_gate")
    engine_module = _mod("engine")
    from ocor_runtime.kernel.governance import RiskClass

    assert engine_module.ActionProposal is records.ActionProposal
    assert "risk_bearing" not in {item.name for item in dataclasses.fields(records.ActionProposal)}
    assert {"contract", "approvals", "decisions"} <= set(inspect.signature(engine_module.GovernedActionEngine).parameters)

    # ACT-T07: NOT_REQUIRED only for a gate not required on a non-canonical target.
    assert gate.gate_disposition(RiskClass.R1_LOW, canonical_target=False) == "NOT_REQUIRED"
    assert _gate_reason(lambda: gate.gate_disposition(RiskClass.R1_LOW, canonical_target=True)) == "NO_MUTATION_ADMITTED"
    assert gate.gate_disposition(RiskClass.R2_CONTROLLED, canonical_target=True) == "REQUIRED"

    suite = EngineSuite()
    # A non-risk-bearing ActionType on the canonical target: denied without execution.
    low = suite.proposal("R1_LOW")
    assert suite.denial(low, approval=None, decision=None) == ("NO_MUTATION_ADMITTED", "NO_MUTATION_ADMITTED")
    assert suite.untouched()
    # The proposer cannot lower the risk class of its signed ActionType.
    lowered = suite.proposal("R3_HIGH_IMPACT", risk_class=RiskClass.R1_LOW)
    assert suite.denial(lowered, approval=None, decision=None) == ("CONTRACT_INVALID", "ACTION_TYPE_MISMATCH")
    # A risk-bearing action without its Approval is denied (NFR-029).
    controlled = suite.proposal("R2_CONTROLLED")
    approval_set = suite.world.approval_set(controlled)
    decision = suite.world.decide(controlled, approval_set)
    assert suite.denial(controlled, approval=None, decision=decision)[0] == "APPROVAL_MISSING"
    assert suite.untouched()
    outcome = suite.execute(controlled, approval=approval_set, decision=decision)
    assert outcome.simulated_effect == {"simulated": True, "action_id": controlled.action_instance_id}
    assert len(suite.sink.calls) == 1


CONTRACT_CASES: dict[str, str | None] = {
    "valid": None,
    "unknown-type": "ACTION_TYPE_UNKNOWN",
    "forged-signature": "ACTION_TYPE_SIGNATURE_INVALID",
    "retired": "ACTION_TYPE_INACTIVE",
    "other-release": "ACTION_TYPE_INACTIVE",
    "other-type-digest": "ACTION_TYPE_MISMATCH",
    "other-effect": "ACTION_TYPE_MISMATCH",
    "other-risk": "ACTION_TYPE_MISMATCH",
    "missing-parameter": "PARAMETERS_INVALID",
    "extra-parameter": "PARAMETERS_INVALID",
    "untyped-parameter": "PARAMETERS_INVALID",
    "boolean-as-integer": "PARAMETERS_INVALID",
    "not-a-proposal": "SCHEMA_INVALID",
}


@pytest.mark.parametrize("case", sorted(CONTRACT_CASES))
def test_g_contract_admits_only_the_signed_active_action_type(case: str) -> None:
    from c6_action_fixture import PUBLISHER, ActionWorld, seeded_key
    from ocor_runtime.kernel.governance import RiskClass

    contract = _mod("contract")
    world = ActionWorld(now=ENGINE_NOW, release=RELEASE)
    schema = {"asset": "string", "priority": "integer", "urgent": "boolean"}
    tasking = world.action_type("urn:ocor:action-type:tasking", risk="R2_CONTROLLED", capability="act:task", parameters=schema)

    def proposal(action_type: Any = tasking, **overrides: Any) -> Any:
        return world.proposal(
            action_type,
            action_id=ACTION,
            proposer=PROPOSER,
            target="urn:ocor:target:site-1",
            governed_context_digest=_sha("gcs"),
            parameters=overrides.pop("parameters", {"asset": "urn:ocor:asset:1", "priority": 2, "urgent": False}),
            **overrides,
        )

    def ghost() -> Any:
        return proposal(world.action_type("urn:ocor:action-type:ghost", risk="R2_CONTROLLED", capability="x", publish=False))

    def forged() -> Any:
        return proposal(world.action_type("urn:ocor:action-type:forged", risk="R2_CONTROLLED", capability="x", signer="rogue"))

    def retired() -> Any:
        world.catalog.retire(tasking.action_type_ref, key=seeded_key(PUBLISHER))
        return proposal()

    def other_release() -> Any:
        stale = proposal()
        world.release.digest = _sha("release-2")
        return stale

    builders: dict[str, Callable[[], Any]] = {
        "valid": proposal,
        "unknown-type": ghost,
        "forged-signature": forged,
        "retired": retired,
        "other-release": other_release,
        "other-type-digest": lambda: proposal(action_type_digest=_sha("other-type")),
        "other-effect": lambda: proposal(effect_class="EXTERNAL_COMMAND"),
        "other-risk": lambda: proposal(risk_class=RiskClass.R3_HIGH_IMPACT),
        "missing-parameter": lambda: proposal(parameters={"asset": "urn:ocor:asset:1", "priority": 2}),
        "extra-parameter": lambda: proposal(
            parameters={"asset": "urn:ocor:asset:1", "priority": 2, "urgent": False, "x": "y"}
        ),
        "untyped-parameter": lambda: proposal(parameters={"asset": 7, "priority": 2, "urgent": False}),
        "boolean-as-integer": lambda: proposal(parameters={"asset": "urn:ocor:asset:1", "priority": True, "urgent": False}),
        "not-a-proposal": lambda: {"action_type_ref": tasking.action_type_ref},
    }
    candidate = builders[case]()
    if CONTRACT_CASES[case] is None:
        assert world.contract.evaluate(candidate) == tasking
        assert world.contract.evaluate(candidate).risk_class is RiskClass.R2_CONTROLLED
        return
    with pytest.raises(contract.ContractGateError) as excinfo:
        world.contract.evaluate(candidate)
    assert excinfo.value.reason_code == CONTRACT_CASES[case]


@pytest.mark.parametrize(
    "field,value",
    [
        (None, None),
        ("timeout_seconds", 0),
        ("max_attempts", 0),
        ("idempotency_scope", ""),
        ("compensable", "yes"),
        ("irreversibility_class", "UNKNOWN"),
        ("marking_ref", "unclassified"),
        ("provenance_ref", " "),
        ("risk_class", 9),
        ("parameters", {"asset": "float"}),
        ("canonical_target", 1),
        ("irreversible-r2", None),
    ],
)
def test_an_action_type_without_its_reliability_fields_is_not_published(field: str | None, value: Any) -> None:
    """FR-080: timeout, retry, idempotency, compensability and irreversibility are declared;
    ADD v1.3 :3303: an irreversible ActionType is R3_HIGH_IMPACT."""
    from c6_action_fixture import ActionWorld

    world = ActionWorld(now=ENGINE_NOW, release=RELEASE)
    if field is None:
        published = world.action_type("urn:ocor:action-type:complete", risk="R2_CONTROLLED", capability="act:x")
        assert world.catalog.action_type("urn:ocor:action-type:complete") == published
        return
    overrides: dict[str, Any] = (
        {"irreversibility_class": "IRREVERSIBLE", "compensable": False} if field == "irreversible-r2" else {field: value}
    )
    assert _record_reason(
        lambda: world.action_type("urn:ocor:action-type:incomplete", risk="R2_CONTROLLED", capability="act:x", **overrides)
    ) == "RECORD_INVALID"
    assert world.catalog.action_type("urn:ocor:action-type:incomplete") is None


@pytest.mark.parametrize("risk", ["R0_INFORMATIONAL", "R1_LOW", "R2_CONTROLLED", "R3_HIGH_IMPACT"])
@pytest.mark.parametrize("canonical_target", [True, False])
def test_the_gate_disposition_follows_the_risk_class_and_the_target(risk: str, canonical_target: bool) -> None:
    gate = _mod("human_gate")
    from ocor_runtime.kernel.governance import RiskClass

    if risk in {"R2_CONTROLLED", "R3_HIGH_IMPACT"}:
        assert gate.gate_disposition(RiskClass[risk], canonical_target=canonical_target) == "REQUIRED"
    elif canonical_target:
        assert _gate_reason(lambda: gate.gate_disposition(RiskClass[risk], canonical_target=True)) == "NO_MUTATION_ADMITTED"
    else:
        assert gate.gate_disposition(RiskClass[risk], canonical_target=False) == "NOT_REQUIRED"


@pytest.mark.parametrize("value", [None, True, 7, "R2_CONTROLLED"])
def test_a_disposition_without_a_valid_risk_classification_is_denied(value: Any) -> None:
    gate = _mod("human_gate")
    assert _gate_reason(lambda: gate.gate_disposition(value, canonical_target=False)) == "NO_MUTATION_ADMITTED"


ENGINE_DENIALS: dict[str, tuple[str, str | None]] = {
    "unpublished-type": ("CONTRACT_INVALID", "ACTION_TYPE_UNKNOWN"),
    "non-canonical-type": ("CONTRACT_INVALID", "TARGET_NOT_CANONICAL"),
    "r0-on-canonical": ("NO_MUTATION_ADMITTED", "NO_MUTATION_ADMITTED"),
    "authority": ("AUTHORITY_DENIED", None),
    "approval-missing": ("APPROVAL_MISSING", None),
    "approval-ungranted": ("APPROVAL_MISSING", "APPROVAL_SET_INVALID"),
    "approval-of-other-proposal": ("APPROVAL_MISSING", "APPROVAL_SET_INVALID"),
    "legacy-unsigned-approval": ("APPROVAL_MISSING", "APPROVAL_SET_INVALID"),
    "decision-missing": ("DECISION_MISSING", None),
    "legacy-unsigned-decision": ("DECISION_MISSING", None),
    "decision-rejected": ("DECISION_REJECTED", "DECISION_REJECTED"),
    "decision-on-other-approval-set": ("DECISION_MISSING", "APPROVAL_SET_INVALID"),
    "package-with-lower-risk": ("DECISION_MISSING", "GATE_PACKAGE_RISK_MISMATCH"),
}


@pytest.mark.parametrize("case", sorted(ENGINE_DENIALS))
def test_the_engine_denies_at_every_gate_before_any_effect(case: str) -> None:
    from ocor_runtime.kernel.governance import RiskClass

    suite = EngineSuite()
    world = suite.world
    proposal = suite.proposal()
    approval_set = world.approval_set(proposal)
    decision = world.decide(proposal, approval_set)
    lease = None
    if case == "unpublished-type":
        ghost = world.action_type("urn:ocor:action-type:rem0053:ghost", risk="R3_HIGH_IMPACT", capability="act:launch",
                                  publish=False)
        proposal = world.proposal(ghost, action_id=proposal.action_instance_id, proposer=OPERATOR, target=TARGET,
                                  governed_context_digest=suite.context.digest())
    elif case == "non-canonical-type":
        note = world.action_type("urn:ocor:action-type:rem0053:note", risk="R2_CONTROLLED", capability="act:launch",
                                 canonical_target=False)
        proposal = world.proposal(note, action_id=proposal.action_instance_id, proposer=OPERATOR, target=TARGET,
                                  governed_context_digest=suite.context.digest())
    elif case == "r0-on-canonical":
        proposal = suite.proposal("R0_INFORMATIONAL")
    elif case == "authority":
        lease = suite.lease("act:read-only")
    elif case == "approval-missing":
        approval_set = None
    elif case == "approval-ungranted":
        approval_set = world.ungranted(approval_set)
    elif case == "approval-of-other-proposal":
        approval_set = world.approval_set(suite.proposal())
    elif case == "legacy-unsigned-approval":
        approval_set = suite.engine_module.Approval(
            action_id=proposal.action_instance_id, approver="urn:ocor:human:approver-1", approved=True, approved_at=ENGINE_NOW
        )
    elif case == "decision-missing":
        decision = None
    elif case == "legacy-unsigned-decision":
        decision = suite.engine_module.Decision(
            action_id=proposal.action_instance_id, decided_by=AUTHORITY, accepted=True, rationale="legacy",
            decided_at=ENGINE_NOW,
        )
    elif case == "decision-rejected":
        decision = world.decide(proposal, approval_set, accepted=False, rationale="risk ceiling exceeded")
    elif case == "decision-on-other-approval-set":
        decision = world.decide(proposal, world.approval_set(proposal))
    elif case == "package-with-lower-risk":
        package = dataclasses.replace(decision.package, risk_class=RiskClass.R2_CONTROLLED)
        signed = world.gate_module.sign_decision(
            _key(AUTHORITY), keyid="k1", decision_id=f"urn:ocor:decision:{uuid.uuid4()}", authority_id=AUTHORITY,
            proposal=proposal, gate_package_digest=package.digest(), outcome="ACCEPT", rationale="lowered",
            valid_from=ENGINE_NOW - timedelta(minutes=1), valid_until=ENGINE_NOW + timedelta(minutes=5),
            decided_at=ENGINE_NOW,
        )
        decision = suite.engine_module.AuthorizedDecision(decision=signed, package=package, package_digest=package.digest())
    reason = suite.denial(proposal, approval=approval_set, decision=decision, lease=lease)
    assert reason == ENGINE_DENIALS[case]
    assert suite.untouched()
    if case == "decision-rejected":
        with pytest.raises(suite.engine_module.GovernedActionError, match="risk ceiling exceeded"):
            suite.execute(proposal, approval=approval_set, decision=world.decide(
                proposal, world.approval_set(proposal), accepted=False, rationale="risk ceiling exceeded"))


def test_a_retry_of_an_admitted_action_replays_its_commit_without_reusing_the_approvals_elsewhere() -> None:
    """FR-008: a retry of the same action instance replays the C3 commit; NFR-005: its ApprovalSet
    and Decision never admit another action instance."""
    suite = EngineSuite()
    world = suite.world
    proposal = suite.proposal()
    approval_set = world.approval_set(proposal)
    decision = world.decide(proposal, approval_set)
    first = suite.execute(proposal, approval=approval_set, decision=decision)
    second = suite.execute(proposal, approval=approval_set, decision=decision)
    assert second.commit_receipt.commit_id == first.commit_receipt.commit_id
    assert second.commit_receipt.replayed is True
    assert suite.c3.current_revision(suite.context.tenant_id, "GovernedActionTarget", TARGET) == 1
    other = dataclasses.replace(proposal, action_instance_id=f"urn:ocor:action:rem0053:{uuid.uuid4()}")
    assert suite.denial(other, approval=approval_set, decision=decision)[0] == "APPROVAL_MISSING"
    late = world.decide(proposal, approval_set)
    assert suite.denial(proposal, approval=approval_set, decision=late) == ("DECISION_MISSING", "IDEMPOTENCY_CONFLICT")


def test_an_admitted_action_is_not_retried_after_its_decision_expired() -> None:
    suite = EngineSuite()
    world = suite.world
    proposal = suite.proposal()
    approval_set = world.approval_set(proposal)
    decision = world.decide(proposal, approval_set)
    suite.execute(proposal, approval=approval_set, decision=decision)
    world.clock.advance(timedelta(minutes=5))
    assert suite.denial(proposal, approval=approval_set, decision=decision) == ("DECISION_MISSING", "DECISION_EXPIRED")
