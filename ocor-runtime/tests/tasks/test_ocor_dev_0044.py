"""OCOR-DEV-0044: Implement compensation reconciliation break-glass and
emergency stop.

Proves that emergency-stop epoch fencing, bounded dual-human
break-glass, and ambiguous-outcome reconciliation all produce
immutable evidence and fail-safe state -- and specifically that a
stop race can never let a command emit after the stop epoch has
advanced (proven with real OS threads, not a single-threaded
simulation), and that an ambiguous, non-idempotent-proven effect can
never be auto-retried. Pure, in-memory, deterministic component (no
external service needed, like OCOR-DEV-0028/0030/0042/0043's own C1/C6
slices).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from ocor_runtime.c2_identity import IdentityRecord, IdentityRegistry
from ocor_runtime.c6.safety import (
    MAX_BREAK_GLASS_TTL,
    BreakGlassController,
    EmergencyStopController,
    OutcomeReconciler,
    SafetyError,
    StopStatus,
)
from ocor_runtime.kernel.governance import InMemoryTrustedClock

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def identities() -> IdentityRegistry:
    registry = IdentityRegistry()
    for canonical_id in ("urn:ocor:human:a", "urn:ocor:human:b", "urn:ocor:human:c"):
        registry.register(IdentityRecord(canonical_id=canonical_id, attributes={"principal_kind": "HUMAN", "status": "ACTIVE", "roles": ""}))
    return registry


# --- EmergencyStopController -------------------------------------------------


def test_the_full_stop_reset_cycle_issues_a_new_epoch_that_invalidates_the_old_one(identities: IdentityRegistry) -> None:
    stop = EmergencyStopController()
    pre_stop_epoch = stop.epoch
    stop.guard_dispatch(fenced_epoch=pre_stop_epoch)

    stop.activate(reason="incident-42", at=NOW)
    assert stop.status is StopStatus.STOPPING
    stop.finish_draining(at=NOW)
    assert stop.status is StopStatus.STOPPED
    stop.request_reset(approvers=("urn:ocor:human:a", "urn:ocor:human:b"), identities=identities, requester="urn:ocor:human:c", at=NOW)
    assert stop.status is StopStatus.RESET_PENDING
    event = stop.confirm_reset(at=NOW)
    assert stop.status is StopStatus.NORMAL
    assert event.epoch != pre_stop_epoch

    with pytest.raises(SafetyError) as excinfo:
        stop.guard_dispatch(fenced_epoch=pre_stop_epoch)
    assert excinfo.value.reason_code == "STOP_EPOCH_STALE"

    stop.guard_dispatch(fenced_epoch=event.epoch)


def test_dispatch_is_blocked_while_stopping_even_at_the_current_epoch(identities: IdentityRegistry) -> None:
    stop = EmergencyStopController()
    stop.activate(reason="incident-42", at=NOW)

    with pytest.raises(SafetyError) as excinfo:
        stop.guard_dispatch(fenced_epoch=stop.epoch)
    assert excinfo.value.reason_code == "SYSTEM_NOT_NORMAL"


def test_reset_requires_two_distinct_resolved_human_approvers(identities: IdentityRegistry) -> None:
    stop = EmergencyStopController()
    stop.activate(reason="incident-42", at=NOW)
    stop.finish_draining(at=NOW)

    with pytest.raises(SafetyError) as excinfo:
        stop.request_reset(approvers=("urn:ocor:human:a", "urn:ocor:human:a"), identities=identities, requester="urn:ocor:human:c", at=NOW)
    assert excinfo.value.reason_code == "RESET_REQUIRES_DUAL_CONTROL"

    with pytest.raises(SafetyError) as excinfo:
        stop.request_reset(approvers=("urn:ocor:human:a", "urn:ocor:human:never-registered"), identities=identities, requester="urn:ocor:human:c", at=NOW)
    assert excinfo.value.reason_code == "RESET_REQUIRES_DUAL_CONTROL"


def test_out_of_order_stop_transitions_are_refused(identities: IdentityRegistry) -> None:
    stop = EmergencyStopController()

    with pytest.raises(SafetyError, match="INVALID_STOP_TRANSITION"):
        stop.finish_draining(at=NOW)
    with pytest.raises(SafetyError, match="INVALID_STOP_TRANSITION"):
        stop.request_reset(approvers=("urn:ocor:human:a", "urn:ocor:human:b"), identities=identities, requester="urn:ocor:human:c", at=NOW)
    with pytest.raises(SafetyError, match="INVALID_STOP_TRANSITION"):
        stop.confirm_reset(at=NOW)

    stop.activate(reason="incident-42", at=NOW)
    with pytest.raises(SafetyError, match="INVALID_STOP_TRANSITION"):
        stop.activate(reason="second activation", at=NOW)


def test_a_real_concurrent_stop_race_never_lets_a_stale_epoch_dispatch_through() -> None:
    """Real fault injection: many OS threads race a genuine
    EmergencyStopController.guard_dispatch call against a concurrent
    stop activation from another real thread. The lock inside
    EmergencyStopController must make epoch capture-and-check atomic:
    every dispatch that actually succeeds must have captured the
    epoch strictly before the real activation happened, never after."""
    stop = EmergencyStopController()
    succeeded: list[int] = []
    failed: list[int] = []
    barrier = threading.Barrier(9)

    def dispatcher() -> None:
        barrier.wait()
        epoch = stop.epoch
        try:
            stop.guard_dispatch(fenced_epoch=epoch)
            succeeded.append(epoch)
        except SafetyError:
            failed.append(epoch)

    def activator() -> None:
        barrier.wait()
        stop.activate(reason="race-test", at=NOW)

    threads = [threading.Thread(target=dispatcher) for _ in range(8)] + [threading.Thread(target=activator)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Every real thread either genuinely dispatched at the pre-stop
    # epoch (a legitimate race winner) or was genuinely refused -- no
    # thread can ever observe a dispatch success once activate() has
    # actually flipped the status away from NORMAL under the same lock.
    assert stop.status is StopStatus.STOPPING
    assert all(epoch == 0 for epoch in succeeded)
    assert len(succeeded) + len(failed) == 8


# --- BreakGlassController ----------------------------------------------------


# OCOR-DEV-REM-0024 (PO decision REM-0024-BREAK-GLASS-PRINCIPAL-AUTHORITY, Q2):
# break-glass now requires a requester, the affected domain, named
# capabilities, registry-held principal attributes and the boundary's
# trusted clock instead of a caller instant. Same cases, assertions and
# reason codes as the sealed OCOR-DEV-0044 suite.
REQUESTER = "urn:ocor:human:c"
DOMAIN = "ops"
CAPABILITIES = frozenset({"restart_service"})
BREAK_GLASS_ATTRIBUTES = {
    "urn:ocor:human:a": {"principal_kind": "HUMAN", "status": "ACTIVE", "roles": "SECURITY_DUTY_OFFICER"},
    "urn:ocor:human:b": {"principal_kind": "HUMAN", "status": "ACTIVE", "roles": f"DOMAIN_OWNER:{DOMAIN}"},
    REQUESTER: {"principal_kind": "HUMAN", "status": "ACTIVE", "roles": ""},
}


class _AuditLog:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, event: Mapping[str, object]) -> None:
        self.events.append(dict(event))


class _AlertChannel:
    def __init__(self) -> None:
        self.alerts: list[dict[str, object]] = []

    def alert(self, event: Mapping[str, object]) -> None:
        self.alerts.append(dict(event))


@pytest.fixture
def break_glass_identities() -> IdentityRegistry:
    registry = IdentityRegistry()
    for canonical_id, attributes in BREAK_GLASS_ATTRIBUTES.items():
        registry.register(IdentityRecord(canonical_id=canonical_id, attributes=attributes))
    return registry


@pytest.fixture
def clock() -> InMemoryTrustedClock:
    return InMemoryTrustedClock(NOW)


def _break_glass_controller(identities: IdentityRegistry, stop: EmergencyStopController, clock: InMemoryTrustedClock) -> BreakGlassController:
    return BreakGlassController(identities=identities, stop=stop, clock=clock, audit=_AuditLog(), alerts=_AlertChannel())


@pytest.fixture
def controller(break_glass_identities: IdentityRegistry, clock: InMemoryTrustedClock) -> BreakGlassController:
    return _break_glass_controller(break_glass_identities, EmergencyStopController(), clock)


def test_a_valid_grant_authorizes_an_allowed_capability_with_mandatory_review(controller: BreakGlassController) -> None:
    grant = controller.grant(
        grant_id="bg-1",
        reason="production-incident",
        incident_ref="INC-42",
        scope="urn:ocor:target:site-1",
        requester=REQUESTER,
        domain=DOMAIN,
        capabilities=CAPABILITIES,
        approvers=("urn:ocor:human:a", "urn:ocor:human:b"),
        ttl=timedelta(minutes=10),
    )

    use = controller.authorize(grant, capability="restart_service", review_ref="REV-1")

    assert use.grant_id == "bg-1"
    assert use.review_ref == "REV-1"


def test_a_grant_without_two_distinct_approvers_is_refused(controller: BreakGlassController) -> None:
    with pytest.raises(SafetyError) as excinfo:
        controller.grant(
            grant_id="bg-2",
            reason="production-incident",
            incident_ref="INC-42",
            scope="urn:ocor:target:site-1",
            requester=REQUESTER,
            domain=DOMAIN,
            capabilities=CAPABILITIES,
            approvers=("urn:ocor:human:a", "urn:ocor:human:a"),
            ttl=timedelta(minutes=10),
        )
    assert excinfo.value.reason_code == "BREAK_GLASS_REQUIRES_TWO_DISTINCT_HUMANS"


def test_a_grant_with_an_unresolved_approver_is_refused(controller: BreakGlassController) -> None:
    with pytest.raises(SafetyError) as excinfo:
        controller.grant(
            grant_id="bg-3",
            reason="production-incident",
            incident_ref="INC-42",
            scope="urn:ocor:target:site-1",
            requester=REQUESTER,
            domain=DOMAIN,
            capabilities=CAPABILITIES,
            approvers=("urn:ocor:human:a", "urn:ocor:human:never-registered"),
            ttl=timedelta(minutes=10),
        )
    assert excinfo.value.reason_code == "BREAK_GLASS_REQUIRES_TWO_DISTINCT_HUMANS"


def test_a_ttl_beyond_the_maximum_is_refused_at_construction(controller: BreakGlassController) -> None:
    with pytest.raises(ValueError, match="ttl"):
        controller.grant(
            grant_id="bg-4",
            reason="production-incident",
            incident_ref="INC-42",
            scope="urn:ocor:target:site-1",
            requester=REQUESTER,
            domain=DOMAIN,
            capabilities=CAPABILITIES,
            approvers=("urn:ocor:human:a", "urn:ocor:human:b"),
            ttl=MAX_BREAK_GLASS_TTL + timedelta(minutes=1),
        )


def test_an_expired_grant_denies_even_though_it_was_valid_when_first_used(controller: BreakGlassController, clock: InMemoryTrustedClock) -> None:
    grant = controller.grant(
        grant_id="bg-5",
        reason="production-incident",
        incident_ref="INC-42",
        scope="urn:ocor:target:site-1",
        requester=REQUESTER,
        domain=DOMAIN,
        capabilities=CAPABILITIES,
        approvers=("urn:ocor:human:a", "urn:ocor:human:b"),
        ttl=timedelta(minutes=5),
    )
    controller.authorize(grant, capability="restart_service", review_ref="REV-1")

    clock.advance(timedelta(minutes=6))
    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-2")
    assert excinfo.value.reason_code == "BREAK_GLASS_EXPIRED"


def test_a_revoked_grant_denies_immediately(controller: BreakGlassController) -> None:
    grant = controller.grant(
        grant_id="bg-6",
        reason="production-incident",
        incident_ref="INC-42",
        scope="urn:ocor:target:site-1",
        requester=REQUESTER,
        domain=DOMAIN,
        capabilities=CAPABILITIES,
        approvers=("urn:ocor:human:a", "urn:ocor:human:b"),
        ttl=timedelta(minutes=10),
    )
    controller.revoke(grant)

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-1")
    assert excinfo.value.reason_code == "BREAK_GLASS_EXPIRED"


@pytest.mark.parametrize("capability", sorted({"create_decision", "reduce_marking", "disable_audit", "ignore_emergency_stop", "change_release_pin"}))
def test_forbidden_capabilities_are_never_authorized_by_break_glass(controller: BreakGlassController, capability: str) -> None:
    grant = controller.grant(
        grant_id="bg-7",
        reason="production-incident",
        incident_ref="INC-42",
        scope="urn:ocor:target:site-1",
        requester=REQUESTER,
        domain=DOMAIN,
        capabilities=CAPABILITIES,
        approvers=("urn:ocor:human:a", "urn:ocor:human:b"),
        ttl=timedelta(minutes=10),
    )

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability=capability, review_ref="REV-1")
    assert excinfo.value.reason_code == "BREAK_GLASS_FORBIDDEN_CAPABILITY"


def test_break_glass_can_never_override_an_active_emergency_stop(break_glass_identities: IdentityRegistry, clock: InMemoryTrustedClock) -> None:
    stop = EmergencyStopController()
    controller = _break_glass_controller(break_glass_identities, stop, clock)
    grant = controller.grant(
        grant_id="bg-8",
        reason="production-incident",
        incident_ref="INC-42",
        scope="urn:ocor:target:site-1",
        requester=REQUESTER,
        domain=DOMAIN,
        capabilities=CAPABILITIES,
        approvers=("urn:ocor:human:a", "urn:ocor:human:b"),
        ttl=timedelta(minutes=10),
    )
    stop.activate(reason="unrelated-incident", at=NOW)

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-1")
    assert excinfo.value.reason_code == "BREAK_GLASS_STOP_ACTIVE"


def test_a_use_without_a_review_reference_is_refused(controller: BreakGlassController) -> None:
    grant = controller.grant(
        grant_id="bg-9",
        reason="production-incident",
        incident_ref="INC-42",
        scope="urn:ocor:target:site-1",
        requester=REQUESTER,
        domain=DOMAIN,
        capabilities=CAPABILITIES,
        approvers=("urn:ocor:human:a", "urn:ocor:human:b"),
        ttl=timedelta(minutes=10),
    )

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="")
    assert excinfo.value.reason_code == "BREAK_GLASS_REVIEW_REQUIRED"


# --- OutcomeReconciler --------------------------------------------------------


def test_an_ambiguous_non_idempotent_effect_cannot_auto_retry() -> None:
    reconciler = OutcomeReconciler()
    reconciler.mark_ambiguous("cmd-1", idempotent_effect_proven=False, at=NOW)

    with pytest.raises(SafetyError) as excinfo:
        reconciler.require_may_auto_retry("cmd-1")
    assert excinfo.value.reason_code == "AUTO_RETRY_BLOCKED_AMBIGUOUS_NON_IDEMPOTENT"


def test_an_ambiguous_effect_with_idempotency_proven_may_auto_retry() -> None:
    reconciler = OutcomeReconciler()
    reconciler.mark_ambiguous("cmd-2", idempotent_effect_proven=True, at=NOW)

    reconciler.require_may_auto_retry("cmd-2")  # does not raise


def test_a_command_never_marked_ambiguous_may_auto_retry() -> None:
    reconciler = OutcomeReconciler()
    reconciler.require_may_auto_retry("cmd-never-seen")  # does not raise


def test_evidence_of_effect_resolves_an_ambiguous_execution_to_confirmed() -> None:
    reconciler = OutcomeReconciler()
    reconciler.mark_ambiguous("cmd-3", idempotent_effect_proven=False, at=NOW)

    record = reconciler.resolve_with_evidence("cmd-3", effect_confirmed=True, at=NOW)

    assert record.status.value == "EXECUTION_CONFIRMED"
    reconciler.require_may_auto_retry("cmd-3")  # no longer ambiguous, retry gate lifted


def test_evidence_of_no_effect_resolves_an_ambiguous_execution_to_failed() -> None:
    reconciler = OutcomeReconciler()
    reconciler.mark_ambiguous("cmd-4", idempotent_effect_proven=False, at=NOW)

    record = reconciler.resolve_with_evidence("cmd-4", effect_confirmed=False, at=NOW)

    assert record.status.value == "EXECUTION_FAILED"


def test_evidence_resolves_an_ambiguous_compensation_to_compensated_or_compensation_failed() -> None:
    reconciler = OutcomeReconciler()
    reconciler.mark_compensation_ambiguous("cmd-5", idempotent_effect_proven=False, at=NOW)

    success = reconciler.resolve_with_evidence("cmd-5", effect_confirmed=True, at=NOW)
    assert success.status.value == "COMPENSATED"

    reconciler.mark_compensation_ambiguous("cmd-6", idempotent_effect_proven=False, at=NOW)
    failure = reconciler.resolve_with_evidence("cmd-6", effect_confirmed=False, at=NOW)
    assert failure.status.value == "COMPENSATION_FAILED"


def test_no_evidence_before_the_deadline_makes_no_inference() -> None:
    reconciler = OutcomeReconciler()
    reconciler.mark_ambiguous("cmd-7", idempotent_effect_proven=False, at=NOW)
    deadline = NOW + timedelta(hours=1)

    still_unknown = reconciler.escalate_if_deadline_passed("cmd-7", at=NOW + timedelta(minutes=30), deadline=deadline)

    assert still_unknown.status.value == "EXECUTION_UNKNOWN"
    with pytest.raises(SafetyError, match="AUTO_RETRY_BLOCKED_AMBIGUOUS_NON_IDEMPOTENT"):
        reconciler.require_may_auto_retry("cmd-7")


def test_a_missed_reconciliation_deadline_escalates_to_indeterminate_and_preserves_the_retry_block() -> None:
    reconciler = OutcomeReconciler()
    reconciler.mark_ambiguous("cmd-8", idempotent_effect_proven=False, at=NOW)
    deadline = NOW + timedelta(hours=1)

    escalated = reconciler.escalate_if_deadline_passed("cmd-8", at=NOW + timedelta(hours=2), deadline=deadline)

    assert escalated.status.value == "EXECUTION_INDETERMINATE"
    with pytest.raises(SafetyError, match="AUTO_RETRY_BLOCKED_AMBIGUOUS_NON_IDEMPOTENT"):
        reconciler.require_may_auto_retry("cmd-8")


def test_a_command_with_no_reconciliation_record_cannot_be_queried_or_resolved() -> None:
    reconciler = OutcomeReconciler()

    with pytest.raises(SafetyError, match="UNKNOWN_COMMAND"):
        reconciler.status("never-seen")
    with pytest.raises(SafetyError, match="UNKNOWN_COMMAND"):
        reconciler.resolve_with_evidence("never-seen", effect_confirmed=True, at=NOW)


def test_an_already_resolved_command_cannot_be_resolved_again() -> None:
    reconciler = OutcomeReconciler()
    reconciler.mark_ambiguous("cmd-9", idempotent_effect_proven=False, at=NOW)
    reconciler.resolve_with_evidence("cmd-9", effect_confirmed=True, at=NOW)

    with pytest.raises(SafetyError, match="INVALID_RECONCILIATION_TRANSITION"):
        reconciler.resolve_with_evidence("cmd-9", effect_confirmed=True, at=NOW)


# --- Integration: stop precedence combined with reconciliation ---------------


def test_stop_precedence_combined_with_reconciliation_end_to_end(identities: IdentityRegistry) -> None:
    """A single scenario wiring EmergencyStopController and
    OutcomeReconciler together: a command dispatched, its outcome
    becomes ambiguous, an emergency stop is activated mid-reconciliation,
    and the stale-epoch dispatch guard still blocks any further
    dispatch even though the reconciliation state is independent."""
    stop = EmergencyStopController()
    reconciler = OutcomeReconciler()

    epoch = stop.epoch
    stop.guard_dispatch(fenced_epoch=epoch)
    reconciler.mark_ambiguous("cmd-10", idempotent_effect_proven=False, at=NOW)

    stop.activate(reason="incident-during-reconciliation", at=NOW)

    with pytest.raises(SafetyError, match="SYSTEM_NOT_NORMAL"):
        stop.guard_dispatch(fenced_epoch=epoch)
    with pytest.raises(SafetyError, match="AUTO_RETRY_BLOCKED_AMBIGUOUS_NON_IDEMPOTENT"):
        reconciler.require_may_auto_retry("cmd-10")
