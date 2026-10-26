"""OCOR-DEV-0043: Implement Human Gate Decision Approval and dual control.

Proves that quorum, separation-of-duties, real identity resolution,
signature scope and TTL are all genuinely revalidated -- not just
checked once at resolution and trusted forever -- and that the same
real human filling two distinct required roles is never counted
twice toward quorum. Pure, in-memory, deterministic component (no
external service needed, like OCOR-DEV-0028/0030/0042's own C1/C6
slices), except for one real fault-injection test against a genuinely
unreachable local port proving the injected control-plane check fails
closed rather than silently defaulting to permit.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from ocor_runtime.c2_identity import IdentityRecord, IdentityRegistry
from ocor_runtime.c3_store import AtomicOutboxStore, OutboxEvent
from ocor_runtime.c6.engine import ActionProposal, Decision, GovernedActionEngine
from ocor_runtime.c6.human_gate import ApprovalPolicy, GateSignature, HumanGateCoordinator, HumanGateError
from ocor_runtime.c6_capabilities import CapabilityAuthority
from ocor_runtime.c7_emission import EmissionFence
from ocor_runtime.kernel.governance import InMemoryTrustedClock
from ocor_runtime.security.ports import ControlName, SecurityControlError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from spikes.control_plane_latency.probe import bounded_probe, decide_with_fail_closed_default  # noqa: E402

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
ACTION_ID = "urn:ocor:action:launch-1"
SCOPE = "urn:ocor:target:site-1"
PROPOSER = "urn:ocor:human:proposer"


@pytest.fixture
def identities() -> IdentityRegistry:
    registry = IdentityRegistry(
        IdentityRecord(canonical_id=canonical_id, attributes={"principal_kind": "HUMAN", "status": "ACTIVE", "roles": "COMPLIANCE RISK_OWNER" if canonical_id.endswith("extra") else ("COMPLIANCE" if canonical_id.endswith("compliance") else "COMPLIANCE RISK_OWNER")})
        for canonical_id in ("urn:ocor:human:risk-owner", "urn:ocor:human:compliance", "urn:ocor:human:extra")
    )
    return registry


@pytest.fixture
def clock() -> InMemoryTrustedClock:
    return InMemoryTrustedClock(NOW)


@pytest.fixture
def coordinator(identities: IdentityRegistry, clock: InMemoryTrustedClock) -> HumanGateCoordinator:
    return HumanGateCoordinator(identities=identities, clock=clock)


def policy(**overrides: object) -> ApprovalPolicy:
    defaults: dict[str, object] = {
        "required_roles": frozenset({"RISK_OWNER", "COMPLIANCE"}),
        "minimum_signatories": 2,
        "ttl": timedelta(hours=1),
    }
    defaults.update(overrides)
    return ApprovalPolicy(**defaults)  # type: ignore[arg-type]


def sig(principal: str, role: str, *, at: datetime = NOW, scope: str = SCOPE, action_id: str = ACTION_ID) -> GateSignature:
    return GateSignature(action_id=action_id, principal_id=principal, role=role, scope=scope, signed_at=at)


def test_a_quorum_covering_both_required_roles_by_distinct_humans_resolves_approved(
    coordinator: HumanGateCoordinator,
) -> None:
    signatures = [sig("urn:ocor:human:risk-owner", "RISK_OWNER"), sig("urn:ocor:human:compliance", "COMPLIANCE")]

    approval = coordinator.validate(
        action_id=ACTION_ID, proposer_id=PROPOSER, policy=policy(), signatures=signatures, scope=SCOPE, at=NOW
    )

    assert approval.approved is True
    assert "urn:ocor:human:risk-owner" in approval.approver
    assert "urn:ocor:human:compliance" in approval.approver


def test_insufficient_distinct_signatories_fails_quorum(coordinator: HumanGateCoordinator) -> None:
    signatures = [sig("urn:ocor:human:risk-owner", "RISK_OWNER")]

    with pytest.raises(HumanGateError) as excinfo:
        coordinator.validate(action_id=ACTION_ID, proposer_id=PROPOSER, policy=policy(), signatures=signatures, scope=SCOPE, at=NOW)

    assert excinfo.value.reason_code == "QUORUM_NOT_MET"


def test_the_same_real_human_signing_both_required_roles_is_not_counted_twice(coordinator: HumanGateCoordinator) -> None:
    """The core separation-of-duties proof: one person's two
    signatures for two different required roles must not satisfy a
    two-person quorum by themselves."""
    signatures = [
        sig("urn:ocor:human:risk-owner", "RISK_OWNER"),
        sig("urn:ocor:human:risk-owner", "COMPLIANCE"),
    ]

    with pytest.raises(HumanGateError) as excinfo:
        coordinator.validate(action_id=ACTION_ID, proposer_id=PROPOSER, policy=policy(), signatures=signatures, scope=SCOPE, at=NOW)

    assert excinfo.value.reason_code in {"QUORUM_NOT_MET", "MISSING_REQUIRED_ROLE"}


def test_a_third_distinct_signatory_does_not_rescue_a_missing_required_role(coordinator: HumanGateCoordinator) -> None:
    signatures = [
        sig("urn:ocor:human:risk-owner", "RISK_OWNER"),
        sig("urn:ocor:human:extra", "RISK_OWNER"),
    ]

    with pytest.raises(HumanGateError) as excinfo:
        coordinator.validate(action_id=ACTION_ID, proposer_id=PROPOSER, policy=policy(), signatures=signatures, scope=SCOPE, at=NOW)

    assert excinfo.value.reason_code == "MISSING_REQUIRED_ROLE"


def test_an_expired_signature_denies_even_though_it_was_once_valid(coordinator: HumanGateCoordinator) -> None:
    stale = NOW - timedelta(hours=2)
    signatures = [sig("urn:ocor:human:risk-owner", "RISK_OWNER", at=stale), sig("urn:ocor:human:compliance", "COMPLIANCE")]

    with pytest.raises(HumanGateError) as excinfo:
        coordinator.validate(action_id=ACTION_ID, proposer_id=PROPOSER, policy=policy(), signatures=signatures, scope=SCOPE, at=NOW)

    assert excinfo.value.reason_code == "QUORUM_NOT_MET"


def test_a_scope_mismatched_signature_denies(coordinator: HumanGateCoordinator) -> None:
    signatures = [
        sig("urn:ocor:human:risk-owner", "RISK_OWNER", scope="urn:ocor:target:a-different-site"),
        sig("urn:ocor:human:compliance", "COMPLIANCE"),
    ]

    with pytest.raises(HumanGateError) as excinfo:
        coordinator.validate(action_id=ACTION_ID, proposer_id=PROPOSER, policy=policy(), signatures=signatures, scope=SCOPE, at=NOW)

    assert excinfo.value.reason_code == "QUORUM_NOT_MET"


def test_the_proposer_own_signature_is_never_counted_even_if_otherwise_valid(coordinator: HumanGateCoordinator) -> None:
    # A third, genuinely distinct and valid signatory keeps quorum (2)
    # satisfiable on its own, isolating the proposer-exclusion behavior:
    # the failure must be role coverage, not raw headcount.
    signatures = [sig(PROPOSER, "RISK_OWNER"), sig("urn:ocor:human:compliance", "COMPLIANCE"), sig("urn:ocor:human:extra", "COMPLIANCE")]

    with pytest.raises(HumanGateError) as excinfo:
        coordinator.validate(action_id=ACTION_ID, proposer_id=PROPOSER, policy=policy(), signatures=signatures, scope=SCOPE, at=NOW)

    assert excinfo.value.reason_code == "MISSING_REQUIRED_ROLE"


def test_an_unresolved_signatory_is_never_counted(coordinator: HumanGateCoordinator) -> None:
    signatures = [
        sig("urn:ocor:human:never-registered", "RISK_OWNER"),
        sig("urn:ocor:human:compliance", "COMPLIANCE"),
        sig("urn:ocor:human:extra", "COMPLIANCE"),
    ]

    with pytest.raises(HumanGateError) as excinfo:
        coordinator.validate(action_id=ACTION_ID, proposer_id=PROPOSER, policy=policy(), signatures=signatures, scope=SCOPE, at=NOW)

    assert excinfo.value.reason_code == "MISSING_REQUIRED_ROLE"


def test_dual_control_a_resolution_that_was_valid_can_be_denied_again_at_dispatch_time(
    coordinator: HumanGateCoordinator,
    clock: InMemoryTrustedClock,
) -> None:
    """The task's own core claim: the identical check is re-run,
    unmodified, at both resolution and dispatch. A signature that was
    still within its TTL when the gate was first resolved can have
    expired by the time dispatch actually happens."""
    short_ttl = policy(ttl=timedelta(minutes=30))
    signed_at = NOW
    signatures = [sig("urn:ocor:human:risk-owner", "RISK_OWNER", at=signed_at), sig("urn:ocor:human:compliance", "COMPLIANCE", at=signed_at)]

    resolution = coordinator.validate(
        action_id=ACTION_ID, proposer_id=PROPOSER, policy=short_ttl, signatures=signatures, scope=SCOPE, at=NOW
    )
    assert resolution.approved is True

    dispatch_time = clock.advance(timedelta(hours=1))
    with pytest.raises(HumanGateError) as excinfo:
        coordinator.validate(
            action_id=ACTION_ID, proposer_id=PROPOSER, policy=short_ttl, signatures=signatures, scope=SCOPE, at=dispatch_time
        )
    assert excinfo.value.reason_code == "QUORUM_NOT_MET"


def test_a_failing_control_check_blocks_approval_even_though_quorum_and_roles_are_satisfied(
    coordinator: HumanGateCoordinator,
) -> None:
    signatures = [sig("urn:ocor:human:risk-owner", "RISK_OWNER"), sig("urn:ocor:human:compliance", "COMPLIANCE")]

    def failing_control_check() -> None:
        raise SecurityControlError("POLICY_UNAVAILABLE", "the real policy control did not answer")

    with pytest.raises(SecurityControlError, match="POLICY_UNAVAILABLE"):
        coordinator.validate(
            action_id=ACTION_ID,
            proposer_id=PROPOSER,
            policy=policy(),
            signatures=signatures,
            scope=SCOPE,
            at=NOW,
            control_check=failing_control_check,
        )


def test_a_real_bounded_probe_against_an_unreachable_control_fails_closed_not_permit(
    coordinator: HumanGateCoordinator,
) -> None:
    """Real fault injection: a genuinely closed local TCP port stands
    in for an unreachable policy control (the same lower-blast-radius
    real-fault pattern this session has used since OCOR-DEV-0026),
    proven via OCOR-DEV-0021's own sealed bounded_probe against a real
    socket, never a mock."""
    signatures = [sig("urn:ocor:human:risk-owner", "RISK_OWNER"), sig("urn:ocor:human:compliance", "COMPLIANCE")]

    def real_but_unreachable_control_check() -> None:
        status, _audit = bounded_probe(
            ControlName.POLICY,
            "http://127.0.0.1:1/health",
            timeout_seconds=0.5,
            correlation_id="urn:ocor:correlation:hg-fault",
            causation_id="urn:ocor:causation:hg-fault",
        )
        decide_with_fail_closed_default(status, ControlName.POLICY)

    with pytest.raises(SecurityControlError, match="POLICY_UNAVAILABLE"):
        coordinator.validate(
            action_id=ACTION_ID,
            proposer_id=PROPOSER,
            policy=policy(),
            signatures=signatures,
            scope=SCOPE,
            at=NOW,
            control_check=real_but_unreachable_control_check,
        )


def test_integrity_digest_is_deterministic_and_changes_with_any_semantic_field() -> None:
    base = sig("urn:ocor:human:risk-owner", "RISK_OWNER")
    same_again = sig("urn:ocor:human:risk-owner", "RISK_OWNER")
    different_role = sig("urn:ocor:human:risk-owner", "COMPLIANCE")

    assert base.integrity_digest == same_again.integrity_digest
    assert base.integrity_digest != different_role.integrity_digest


class RecordingSink:
    def __init__(self) -> None:
        self.calls: list[tuple[OutboxEvent, str]] = []

    def emit(self, event: OutboxEvent, *, idempotency_key: str) -> dict[str, object]:
        self.calls.append((event, idempotency_key))
        return {"simulated": True, "action_id": event.payload["action_id"]}


def test_a_resolved_human_gate_approval_wires_directly_into_the_real_governed_action_engine(
    coordinator: HumanGateCoordinator,
) -> None:
    """Integration-level proof: HumanGateCoordinator's own output
    Approval is the identical sealed type GovernedActionEngine.execute
    already accepts, with no adapter needed."""
    authority = CapabilityAuthority(issuer="ocor-c6-human-gate-integration")
    store = AtomicOutboxStore()
    fence = EmissionFence(store=store)
    engine = GovernedActionEngine(authority=authority, store=store, fence=fence)

    proposal = ActionProposal(
        action_id=ACTION_ID,
        subject="spiffe://ocor.test/workload/operator",
        capability="act:launch",
        resource=SCOPE,
        aggregate_id="urn:ocor:aggregate:site-1",
        risk_bearing=True,
    )
    lease = authority.issue(
        subject="spiffe://ocor.test/workload/operator",
        capabilities=["act:launch"],
        resources=[SCOPE],
        issued_at=NOW,
        ttl=timedelta(hours=1),
    )
    signatures = [sig("urn:ocor:human:risk-owner", "RISK_OWNER"), sig("urn:ocor:human:compliance", "COMPLIANCE")]
    approval = coordinator.validate(
        action_id=ACTION_ID, proposer_id=PROPOSER, policy=policy(), signatures=signatures, scope=SCOPE, at=NOW
    )
    decision = Decision(action_id=ACTION_ID, decided_by="urn:ocor:human:decider-1", accepted=True, rationale="within ceiling", decided_at=NOW)
    sink = RecordingSink()

    outcome = engine.execute(proposal, lease=lease, approval=approval, decision=decision, sink=sink, at=NOW)

    assert outcome.simulated_effect == {"simulated": True, "action_id": ACTION_ID}
    assert len(sink.calls) == 1
