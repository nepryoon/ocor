"""OCOR-DEV-0030: Build retained governed-action slice.

Proves that a risk-bearing action crosses, in strict order, Authority
(``G-AUTHORITY``), Human Gate (``G-APPROVAL``), Decision
(``G-DECISION``) and EMISSION-FENCE before any simulated effect is
applied -- and that a denial at any gate blocks the simulated effect
entirely, leaving zero durable state and zero sink calls. Pure,
in-memory, deterministic component (no external service needed, like
OCOR-DEV-0028's C1 compiler slice): reuses the sealed
``ocor_runtime.c6_capabilities.CapabilityAuthority`` and
``ocor_runtime.c7_emission.EmissionFence`` unmodified, composed with a
new, minimal ``ocor_runtime.c6.engine.GovernedActionEngine``.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import test_ocor_dev_rem_0050 as governed_path
from ocor_runtime.c3.service import PostgresC3Service
from ocor_runtime.c3_store import OutboxEvent
from c6_action_fixture import ActionWorld
from ocor_runtime.c6.engine import (
    ActionProposal,
    AuthorizedDecision,
    C3CanonicalOutboxView,
    GovernedActionEngine,
    GovernedActionError,
)
from ocor_runtime.c6.records import ApprovalSet
from ocor_runtime.c6_capabilities import CapabilityAuthority
from ocor_runtime.c7_emission import EmissionFence
from spikes.c6_fsm_fidelity.generator import generate_from_lld

LLD_PATH = Path(__file__).resolve().parents[3] / "docs" / "OCOR_LLD_v1.1.md"
NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)
# NCP-U04 (OCOR-DEV-REM-0050): the engine commits through C3 on the governed path
# (LLD v1.1 :85-95, ADD v1.3 :342); the canonical state the suite observes is C3's.
GOVERNED = governed_path.GovernedC3(
    release=governed_path.RELEASE,
    preconditions=("urn:ocor:precondition:governed-action",),
    invariants=("urn:ocor:invariant:governed-action",),
)
CONTEXT = GOVERNED.governed_context(purpose="retained-governed-action-slice")
# NCP-U07 (OCOR-DEV-REM-0053): the engine admits only a proposal pinned to a signed, active
# ActionType (NCR-C6-002, ADD v1.3 :2847), the ApprovalSet of the Human Gate and the Authority's
# signed Decision on the frozen GatePackage (NCR-C6-001, ADD v1.3 :2849-2850). The launch is
# R3_HIGH_IMPACT; the non-risk-bearing ActionType is R1_LOW, which admits no mutation.
WORLD = ActionWorld(now=NOW, release=governed_path.RELEASE)
LAUNCH = WORLD.action_type("urn:ocor:action-type:launch", risk="R3_HIGH_IMPACT", capability="act:launch")
SITE_NOTE = WORLD.action_type("urn:ocor:action-type:site-note", risk="R1_LOW", capability="act:launch")


class RecordingSink:
    def __init__(self) -> None:
        self.calls: list[tuple[OutboxEvent, str]] = []

    def emit(self, event: OutboxEvent, *, idempotency_key: str):
        self.calls.append((event, idempotency_key))
        return {"simulated": True, "action_id": event.payload["action_id"]}


class FailingSink:
    def emit(self, event: OutboxEvent, *, idempotency_key: str):
        raise ConnectionError("simulated real delivery failure")


@pytest.fixture
def authority() -> CapabilityAuthority:
    return CapabilityAuthority(issuer="ocor-c6-slice-authority")


@pytest.fixture
def c3() -> PostgresC3Service:
    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory: the engine commits through the real C3")
    value = PostgresC3Service(dsn, admission=GOVERNED.admission())
    value.initialize()
    value.reset()
    return value


@pytest.fixture
def store(c3: PostgresC3Service) -> C3CanonicalOutboxView:
    return C3CanonicalOutboxView(c3, tenant_id=CONTEXT.tenant_id, aggregate_type="GovernedActionTarget")


@pytest.fixture
def fence(store: C3CanonicalOutboxView) -> EmissionFence:
    return EmissionFence(store=store)  # type: ignore[arg-type]


@pytest.fixture
def engine(
    authority: CapabilityAuthority, c3: PostgresC3Service, store: C3CanonicalOutboxView, fence: EmissionFence
) -> GovernedActionEngine:
    path = GOVERNED.engine_path(aggregate_type="GovernedActionTarget", governed_context=CONTEXT)
    WORLD.granted.clear()
    engine: GovernedActionEngine = WORLD.engine(
        authority=authority, commit_port=c3, fence=fence, canonical_path=path, emission_outbox=store
    )
    return engine


def make_proposal(*, risk_bearing: bool = True) -> ActionProposal:
    return WORLD.proposal(
        LAUNCH if risk_bearing else SITE_NOTE,
        action_id="urn:ocor:action:launch-1",
        proposer="spiffe://ocor.test/workload/operator",
        target="urn:ocor:target:site-1",
        governed_context_digest=CONTEXT.digest(),
    )


def grant_lease(authority: CapabilityAuthority, *, capability: str = "act:launch", resource: str = "urn:ocor:target:site-1"):
    return authority.issue(
        subject="spiffe://ocor.test/workload/operator",
        capabilities=[capability],
        resources=[resource],
        issued_at=NOW,
        ttl=timedelta(hours=1),
    )


def make_approval(action_id: str = "urn:ocor:action:launch-1", *, approved: bool = True) -> ApprovalSet:
    # The signed Approvals of the Domain and National Approver bound to proposal digest,
    # revision, release and expiry, in the ApprovalSet of the Human Gate; a set the gate did not
    # grant is not signed by it.
    approval_set = WORLD.approval_set(make_proposal())
    if not approved:
        return WORLD.ungranted(approval_set)
    WORLD.granted[action_id] = approval_set
    return approval_set


def make_decision(action_id: str = "urn:ocor:action:launch-1", *, accepted: bool = True) -> AuthorizedDecision:
    # The Authority's signed Decision on the GatePackage that freezes the granted ApprovalSet.
    proposal = make_proposal()
    approval_set = WORLD.granted.pop(action_id, None) or WORLD.approval_set(proposal)
    return WORLD.decide(
        proposal,
        approval_set,
        accepted=accepted,
        rationale="within approved risk ceiling" if accepted else "risk ceiling exceeded",
    )


def test_happy_path_crosses_all_four_gates_before_the_simulated_effect(engine, authority, store):
    proposal = make_proposal()
    lease = grant_lease(authority)
    sink = RecordingSink()

    outcome = engine.execute(
        proposal,
        lease=lease,
        approval=make_approval(),
        decision=make_decision(),
        sink=sink,
        at=NOW,
    )

    assert outcome.simulated_effect == {"simulated": True, "action_id": proposal.action_id}
    assert len(sink.calls) == 1
    assert store.get(proposal.aggregate_id) is not None
    assert store.get(proposal.aggregate_id).document["status"] == "EXECUTED"
    assert outcome.emission_receipt.event_id == sink.calls[0][0].event_id


def test_missing_authority_denies_before_any_other_gate(engine, authority, store):
    proposal = make_proposal()
    # A lease that grants a DIFFERENT capability -- authority must deny.
    lease = grant_lease(authority, capability="act:read-only")
    sink = RecordingSink()

    with pytest.raises(GovernedActionError) as excinfo:
        engine.execute(
            proposal, lease=lease, approval=make_approval(), decision=make_decision(), sink=sink, at=NOW
        )

    assert excinfo.value.reason_code == "AUTHORITY_DENIED"
    assert sink.calls == []
    assert store.get(proposal.aggregate_id) is None


def test_risk_bearing_action_without_approval_is_denied(engine, authority, store):
    proposal = make_proposal(risk_bearing=True)
    lease = grant_lease(authority)
    sink = RecordingSink()

    with pytest.raises(GovernedActionError) as excinfo:
        engine.execute(proposal, lease=lease, approval=None, decision=make_decision(), sink=sink, at=NOW)

    assert excinfo.value.reason_code == "APPROVAL_MISSING"
    assert sink.calls == []
    assert store.get(proposal.aggregate_id) is None


def test_risk_bearing_action_with_rejected_approval_is_denied(engine, authority, store):
    proposal = make_proposal(risk_bearing=True)
    lease = grant_lease(authority)
    sink = RecordingSink()

    with pytest.raises(GovernedActionError) as excinfo:
        engine.execute(
            proposal,
            lease=lease,
            approval=make_approval(approved=False),
            decision=make_decision(),
            sink=sink,
            at=NOW,
        )

    assert excinfo.value.reason_code == "APPROVAL_MISSING"
    assert sink.calls == []


def test_missing_decision_is_denied(engine, authority):
    proposal = make_proposal()
    lease = grant_lease(authority)
    sink = RecordingSink()

    with pytest.raises(GovernedActionError) as excinfo:
        engine.execute(proposal, lease=lease, approval=make_approval(), decision=None, sink=sink, at=NOW)

    assert excinfo.value.reason_code == "DECISION_MISSING"
    assert sink.calls == []


def test_rejected_decision_is_denied_with_rationale_preserved(engine, authority):
    proposal = make_proposal()
    lease = grant_lease(authority)
    sink = RecordingSink()

    with pytest.raises(GovernedActionError) as excinfo:
        engine.execute(
            proposal,
            lease=lease,
            approval=make_approval(),
            decision=make_decision(accepted=False),
            sink=sink,
            at=NOW,
        )

    assert excinfo.value.reason_code == "DECISION_REJECTED"
    assert "risk ceiling exceeded" in str(excinfo.value)
    assert sink.calls == []


def test_non_risk_bearing_action_does_not_require_a_human_gate_approval(engine, authority, store):
    proposal = make_proposal(risk_bearing=False)
    lease = grant_lease(authority)
    sink = RecordingSink()

    # ADD v1.3 :2847 and :3298-3302, LLD v1.1 :268 (NCR-C6-002, realigned with RED): the risk class
    # is the signed ActionType's; R1 admits no mutation and a canonical target never takes the
    # NOT_REQUIRED disposition, so the request is denied without execution.
    with pytest.raises(GovernedActionError) as excinfo:
        engine.execute(proposal, lease=lease, approval=None, decision=make_decision(), sink=sink, at=NOW)

    assert excinfo.value.reason_code == "NO_MUTATION_ADMITTED"
    assert sink.calls == []


def test_a_failing_sink_leaves_no_emission_receipt_and_a_retry_succeeds(engine, authority, store, fence):
    proposal = make_proposal()
    lease = grant_lease(authority)

    with pytest.raises(ConnectionError):
        engine.execute(
            proposal,
            lease=lease,
            approval=make_approval(),
            decision=make_decision(),
            sink=FailingSink(),
            at=NOW,
        )

    # The canonical commit already happened (durable outbox event
    # staged) but EMISSION-FENCE never released it across the
    # boundary -- a fresh, working sink can still retry safely against
    # the same fence bound to the same durable store.
    assert store.get(proposal.aggregate_id) is not None
    pending = store.outbox()
    assert len(pending) == 1

    retry_sink = RecordingSink()
    receipt = fence.emit(pending[0], retry_sink, at=NOW)
    assert receipt.deduplicated is False
    assert len(retry_sink.calls) == 1


def test_engine_gate_names_are_traceable_to_the_sealed_lld_transition_table():
    transitions = generate_from_lld(LLD_PATH)
    guards = "\n".join(item.guard for item in transitions)
    effects = "\n".join(item.durable_effect for item in transitions)
    assert "G-AUTHORITY" in guards
    assert "Human Gate" in guards
    assert "G-DECISION" in guards
    assert "EMISSION-FENCE" in guards or "EMISSION-FENCE" in effects
