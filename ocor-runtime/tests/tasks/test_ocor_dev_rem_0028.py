"""REM-0028: registry authority, separation and boundary time (Q1/Q3).

Uses the retained real IdentityRegistry, not a substitute identity provider.
It remains an in-memory PoC authority; its unauthenticated first writer is
an open REM-0031 risk, not a property qualified by these tests.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ocor_runtime.c2_identity import IdentityRecord, IdentityRegistry
from ocor_runtime.c6.human_gate import ApprovalPolicy, GateSignature, HumanGateCoordinator, HumanGateError
from ocor_runtime.c6.safety import EmergencyStopController, SafetyError, StopStatus
from ocor_runtime.kernel.governance import InMemoryTrustedClock

NOW = datetime(2026, 10, 15, 9, tzinfo=UTC)
ROLES = frozenset({'DOMAIN_APPROVER', 'NATIONAL_APPROVER'})


def directory(first: dict[str, object] | None = None) -> IdentityRegistry:
    registry = IdentityRegistry()
    for name, roles in [('a', 'DOMAIN_APPROVER'), ('b', 'NATIONAL_APPROVER'), ('requester', '')]:
        attributes = {'principal_kind': 'HUMAN', 'status': 'ACTIVE', 'roles': roles}
        if name == 'a' and first is not None:
            attributes = first
        registry.register(IdentityRecord(canonical_id=name, attributes=attributes))
    return registry


def signatures(at: datetime = NOW) -> list[GateSignature]:
    return [GateSignature(action_id='action', principal_id=p, role=r, scope='scope', signed_at=at)
            for p, r in [('a', 'DOMAIN_APPROVER'), ('b', 'NATIONAL_APPROVER')]]


def approve(registry: IdentityRegistry, *, at: datetime = NOW) -> object:
    gate = HumanGateCoordinator(identities=registry, clock=InMemoryTrustedClock(NOW))
    return gate.validate(action_id='action', proposer_id='requester', policy=ApprovalPolicy(ROLES, 2, timedelta(minutes=10)),
                         signatures=signatures(), scope='scope', at=at)


INVALID = [
    {},
    {'principal_kind': 'WORKLOAD', 'status': 'ACTIVE', 'roles': 'DOMAIN_APPROVER'},
    {'principal_kind': 'HUMAN', 'status': 'REVOKED', 'roles': 'DOMAIN_APPROVER'},
    {'principal_kind': 'HUMAN', 'roles': 'DOMAIN_APPROVER'},
    {'status': 'ACTIVE', 'roles': 'DOMAIN_APPROVER'},
    {'principal_kind': 'HUMAN', 'status': 'ACTIVE'},
    {'principal_kind': 'human', 'status': 'ACTIVE', 'roles': 'DOMAIN_APPROVER'},
    {'principal_kind': 'HUMAN', 'status': 'ACTIVE', 'roles': ['DOMAIN_APPROVER']},
    {'principal_kind': 'HUMAN', 'status': 'ACTIVE', 'roles': 'DOMAIN_APPROVER DOMAIN_APPROVER'},
    {'principal_kind': 'HUMAN', 'status': 'ACTIVE', 'roles': 'NATIONAL_APPROVER DOMAIN_APPROVER'},
    {'principal_kind': 'HUMAN', 'status': 'ACTIVE', 'roles': 'DOMAIN_APPROVER  NATIONAL_APPROVER'},
    {'principal_kind': 'HUMAN', 'status': 'ACTIVE', 'roles': 'DOMAIN_APPROVER\tNATIONAL_APPROVER'},
]


@pytest.mark.parametrize('attributes', INVALID)
def test_invalid_registry_approver_cannot_approve(attributes: dict[str, object]) -> None:
    with pytest.raises(HumanGateError):
        approve(directory(attributes))


def test_claimed_role_is_not_registry_authority() -> None:
    with pytest.raises(HumanGateError):
        approve(directory({'principal_kind': 'HUMAN', 'status': 'ACTIVE', 'roles': 'UNRELATED'}))


def test_valid_registry_quorum_is_accepted() -> None:
    assert approve(directory()).approved is True  # type: ignore[attr-defined]


@pytest.mark.parametrize('attributes', INVALID)
def test_invalid_registry_approver_cannot_reset(attributes: dict[str, object]) -> None:
    stop = EmergencyStopController()
    stop.activate(reason='incident', at=NOW)
    stop.finish_draining(at=NOW)
    with pytest.raises(SafetyError, match='RESET_REQUIRES_DUAL_CONTROL'):
        stop.request_reset(approvers=('a', 'b'), identities=directory(attributes), requester="requester", at=NOW)
    assert stop.status is StopStatus.STOPPED


def test_reset_timestamp_comes_from_boundary_not_request() -> None:
    stop = EmergencyStopController()
    stop.activate(reason='incident', at=NOW)
    stop.finish_draining(at=NOW)
    before = datetime.now(UTC)
    event = stop.request_reset(approvers=('a', 'b'), identities=directory(), requester="requester", at=NOW - timedelta(days=90))
    assert before <= event.at <= datetime.now(UTC)


@pytest.mark.parametrize('delta', [timedelta(microseconds=1), -timedelta(minutes=10), -timedelta(minutes=11)])
def test_signature_window_rejects_future_exact_expiry_and_expired(delta: timedelta) -> None:
    clock = InMemoryTrustedClock(NOW)
    gate = HumanGateCoordinator(identities=directory(), clock=clock)
    with pytest.raises(HumanGateError, match='QUORUM_NOT_MET'):
        gate.validate(action_id='action', proposer_id='requester', policy=ApprovalPolicy(ROLES, 2, timedelta(minutes=10)),
                      signatures=signatures(NOW + delta), scope='scope', at=NOW + delta)


def test_clock_advancement_cannot_be_undone_by_a_caller_timestamp() -> None:
    clock = InMemoryTrustedClock(NOW)
    gate = HumanGateCoordinator(identities=directory(), clock=clock)
    args = dict(action_id='action', proposer_id='requester', policy=ApprovalPolicy(ROLES, 2, timedelta(minutes=10)), signatures=signatures(), scope='scope')
    first = gate.validate(**args, at=NOW - timedelta(days=365))
    assert first.approved and first.approved_at == NOW
    clock.advance(timedelta(minutes=10) - timedelta(microseconds=1))
    assert gate.validate(**args, at=NOW + timedelta(days=365)).approved
    clock.advance(timedelta(microseconds=1))
    with pytest.raises(HumanGateError, match='QUORUM_NOT_MET'):
        gate.validate(**args, at=NOW)


def test_authority_is_reread_after_prior_success() -> None:
    registry = directory()
    clock = InMemoryTrustedClock(NOW)
    gate = HumanGateCoordinator(identities=registry, clock=clock)
    args = dict(action_id='action', proposer_id='requester', policy=ApprovalPolicy(ROLES, 2, timedelta(minutes=10)), signatures=signatures(), scope='scope')
    assert gate.validate(**args).approved
    # Fault injection in the real retained in-memory registry. No new registry
    # mutation API is exposed: authenticated provisioning remains REM-0031.
    with registry._lock:
        registry._records.pop('a')
    with pytest.raises(HumanGateError, match='QUORUM_NOT_MET'):
        gate.validate(**args)


@pytest.mark.parametrize('mutation', ['wrong_action', 'wrong_scope', 'proposer', 'excluded', 'unresolved'])
def test_signature_binding_and_separation_are_required(mutation: str) -> None:
    import dataclasses
    values = signatures()
    policy = ApprovalPolicy(ROLES, 2, timedelta(minutes=10), excluded_principal_id='a' if mutation == 'excluded' else None)
    changes = {'wrong_action': {'action_id': 'other'}, 'wrong_scope': {'scope': 'other'},
               'proposer': {'principal_id': 'requester'}, 'unresolved': {'principal_id': 'missing'}}
    if mutation in changes:
        values[0] = dataclasses.replace(values[0], **changes[mutation])
    with pytest.raises(HumanGateError, match='QUORUM_NOT_MET'):
        HumanGateCoordinator(identities=directory(), clock=InMemoryTrustedClock(NOW)).validate(
            action_id='action', proposer_id='requester', policy=policy, signatures=values, scope='scope')


def test_success_checks_control_and_preserves_registry_records() -> None:
    registry = directory()
    before = registry.all_records()
    called: list[bool] = []
    approval = HumanGateCoordinator(identities=registry, clock=InMemoryTrustedClock(NOW)).validate(
        action_id='action', proposer_id='requester', policy=ApprovalPolicy(ROLES, 2, timedelta(minutes=10)),
        signatures=signatures(), scope='scope', control_check=lambda: called.append(True))
    assert called == [True]
    assert approval.approver == 'a,b'
    assert registry.all_records() == before


@pytest.mark.parametrize('approvers,requester', [(('a', 'a'), 'requester'), (('a', 'b'), 'a'), (('a', 'b'), ''),
                                               (('a', 'b', 'requester'), 'other'), (('a', 'missing'), 'requester')])
def test_reset_rejects_bad_quorum_without_changing_state(approvers: tuple[str, ...], requester: str) -> None:
    stop = EmergencyStopController()
    stop.activate(reason='incident', at=NOW)
    stop.finish_draining(at=NOW)
    before = stop.history
    with pytest.raises(SafetyError, match='RESET_REQUIRES_DUAL_CONTROL'):
        stop.request_reset(approvers=approvers, identities=directory(), requester=requester)
    assert stop.status is StopStatus.STOPPED
    assert stop.history == before


def test_reset_needs_no_invented_fixed_role_and_never_writes_registry() -> None:
    registry = directory({'principal_kind': 'HUMAN', 'status': 'ACTIVE', 'roles': ''})
    before = registry.all_records()
    stop = EmergencyStopController()
    stop.activate(reason='incident', at=NOW)
    stop.finish_draining(at=NOW)
    event = stop.request_reset(approvers=('a', 'b'), identities=registry, requester='requester')
    assert event.status is StopStatus.RESET_PENDING
    assert registry.all_records() == before


def test_requests_cannot_supply_or_set_authority_attributes() -> None:
    registry = directory()
    before = registry.all_records()
    gate = HumanGateCoordinator(identities=registry, clock=InMemoryTrustedClock(NOW))
    with pytest.raises(TypeError):
        gate.validate(action_id='action', proposer_id='requester', policy=ApprovalPolicy(ROLES, 2, timedelta(minutes=10)),
                      signatures=signatures(), scope='scope', principal_kind='HUMAN', roles='DOMAIN_APPROVER')
    stop = EmergencyStopController()
    with pytest.raises(TypeError):
        stop.request_reset(approvers=('a', 'b'), identities=registry, requester='requester', status='ACTIVE')
    assert registry.all_records() == before


def test_invalid_clock_is_fail_closed() -> None:
    class UnavailableClock:
        def now(self) -> datetime:
            raise RuntimeError('trusted clock unavailable')
    gate = HumanGateCoordinator(identities=directory(), clock=UnavailableClock())
    with pytest.raises(RuntimeError, match='trusted clock unavailable'):
        gate.validate(action_id='action', proposer_id='requester', policy=ApprovalPolicy(ROLES, 2, timedelta(minutes=10)), signatures=signatures(), scope='scope')
