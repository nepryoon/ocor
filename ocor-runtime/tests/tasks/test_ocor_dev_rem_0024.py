"""OCOR-DEV-REM-0024: break-glass conformance to ADD v1.3 sections 5.4-5.5
and LLD v1.1 sections 1.1/4.2 (PO decisions RVW-03 of 2026-10-05 and
REM-0024-BREAK-GLASS-PRINCIPAL-AUTHORITY of 2026-10-13).

Every conditional branch of ``BreakGlassController.grant``,
``authorize`` and ``revoke`` has a positive and a negative executable
case. The RVW-03 probe observations are reproduced as tests:

* P1 -- a grant built outside ``grant()`` (or altered after issuance)
  never authorizes;
* P2 -- approvers are re-validated against the identity registry at
  grant time and at every use: resolved, ``HUMAN``, ``ACTIVE``,
  distinct, never the requester, and covering the quorum
  ``SECURITY_DUTY_OFFICER`` + ``DOMAIN_OWNER:<grant domain>``;
* P3 -- validity is decided by the boundary's trusted clock only; no
  operation accepts a caller-supplied instant;
* X1 -- ``authorize`` is restricted to the capabilities named in the
  grant.

Principal kind, status and roles follow the PO's PoC convention on the
reserved scalar ``attributes`` of ``identity-record`` v1.2
(``principal_kind``, ``status``, ``roles``) and are read only from the
registry, never from the grant request. Pure, in-memory component like
OCOR-DEV-0044: no external service is needed.
"""

from __future__ import annotations

import dataclasses
import inspect
import threading
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from ocor_runtime.c2_identity import IdentityRecord, IdentityRegistry
from ocor_runtime.c6.safety import (
    FORBIDDEN_BREAK_GLASS_CAPABILITIES,
    MAX_BREAK_GLASS_TTL,
    BreakGlassController,
    BreakGlassGrant,
    EmergencyStopController,
    SafetyError,
)
from ocor_runtime.errors import IdentityConflictError, TemporalGuardViolation
from ocor_runtime.kernel.governance import InMemoryTrustedClock

NOW = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)

REQUESTER = "urn:ocor:human:requester"
SDO = "urn:ocor:human:sdo"
OWNER = "urn:ocor:human:owner"
OTHER_OWNER = "urn:ocor:human:other-owner"
SECOND_SDO = "urn:ocor:human:second-sdo"
BOTH_ROLES = "urn:ocor:human:both-roles"
WORKLOAD = "urn:ocor:workload:svc"
SUSPENDED = "urn:ocor:human:suspended"
NO_STATUS = "urn:ocor:human:no-status"
NO_KIND = "urn:ocor:human:no-kind"
BAD_KIND = "urn:ocor:human:bad-kind"
UNSORTED_ROLES = "urn:ocor:human:unsorted-roles"
DUPLICATE_ROLES = "urn:ocor:human:duplicate-roles"
NON_STRING_ROLES = "urn:ocor:human:non-string-roles"
EMPTY_TOKEN_ROLES = "urn:ocor:human:empty-token-roles"
INACTIVE_REQUESTER = "urn:ocor:human:inactive-requester"
WORKLOAD_REQUESTER = "urn:ocor:workload:requester"

DOMAIN = "ops"


def _human(*roles: str, status: object = "ACTIVE") -> dict[str, object]:
    return {"principal_kind": "HUMAN", "status": status, "roles": " ".join(sorted(roles))}


RECORDS: dict[str, dict[str, object]] = {
    REQUESTER: _human(),
    SDO: _human("SECURITY_DUTY_OFFICER"),
    OWNER: _human(f"DOMAIN_OWNER:{DOMAIN}"),
    OTHER_OWNER: _human("DOMAIN_OWNER:logistics"),
    SECOND_SDO: _human("SECURITY_DUTY_OFFICER"),
    BOTH_ROLES: _human(f"DOMAIN_OWNER:{DOMAIN}", "SECURITY_DUTY_OFFICER"),
    WORKLOAD: {"principal_kind": "WORKLOAD", "status": "ACTIVE", "roles": "SECURITY_DUTY_OFFICER"},
    SUSPENDED: _human("SECURITY_DUTY_OFFICER", status="SUSPENDED"),
    NO_STATUS: {"principal_kind": "HUMAN", "roles": "SECURITY_DUTY_OFFICER"},
    NO_KIND: {"status": "ACTIVE", "roles": "SECURITY_DUTY_OFFICER"},
    BAD_KIND: {"principal_kind": "human", "status": "ACTIVE", "roles": "SECURITY_DUTY_OFFICER"},
    UNSORTED_ROLES: {"principal_kind": "HUMAN", "status": "ACTIVE", "roles": f"SECURITY_DUTY_OFFICER DOMAIN_OWNER:{DOMAIN}"},
    DUPLICATE_ROLES: {"principal_kind": "HUMAN", "status": "ACTIVE", "roles": "SECURITY_DUTY_OFFICER SECURITY_DUTY_OFFICER"},
    NON_STRING_ROLES: {"principal_kind": "HUMAN", "status": "ACTIVE", "roles": 7},
    EMPTY_TOKEN_ROLES: {"principal_kind": "HUMAN", "status": "ACTIVE", "roles": f"DOMAIN_OWNER:{DOMAIN}  SECURITY_DUTY_OFFICER"},
    INACTIVE_REQUESTER: _human(status="REVOKED"),
    WORKLOAD_REQUESTER: {"principal_kind": "WORKLOAD", "status": "ACTIVE", "roles": ""},
}


class RecordingAuditSink:
    """Synchronous append-only audit double; ``fail`` makes the next appends raise."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.fail = False

    def record(self, event: Mapping[str, object]) -> None:
        if self.fail:
            raise RuntimeError("audit store unavailable")
        self.events.append(dict(event))

    def kinds(self) -> list[object]:
        return [event["event"] for event in self.events]


class RecordingAlertSink:
    def __init__(self) -> None:
        self.alerts: list[dict[str, object]] = []
        self.fail = False

    def alert(self, event: Mapping[str, object]) -> None:
        if self.fail:
            raise RuntimeError("alert channel unavailable")
        self.alerts.append(dict(event))


class MutableDirectory:
    """An authoritative principal directory whose records can change over
    time (deactivation, role removal, deletion) -- the change that use-time
    re-validation must observe. Same read surface as IdentityRegistry."""

    def __init__(self, records: Mapping[str, Mapping[str, object]]) -> None:
        self._records = {cid: IdentityRecord(canonical_id=cid, attributes=attrs) for cid, attrs in records.items()}
        self._lock = threading.Lock()

    def get(self, canonical_id: str) -> IdentityRecord | None:
        with self._lock:
            return self._records.get(canonical_id)

    def replace(self, canonical_id: str, attributes: Mapping[str, object]) -> None:
        with self._lock:
            self._records[canonical_id] = IdentityRecord(canonical_id=canonical_id, attributes=attributes)

    def remove(self, canonical_id: str) -> None:
        with self._lock:
            del self._records[canonical_id]


class SettableClock:
    """Trusted clock double that can also move backwards, to prove that a
    rewound clock never revives an expired grant."""

    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


@pytest.fixture
def registry() -> IdentityRegistry:
    registry = IdentityRegistry(
        IdentityRecord(canonical_id=canonical_id, attributes=attributes)
        for canonical_id, attributes in RECORDS.items()
    )
    return registry


@pytest.fixture
def clock() -> InMemoryTrustedClock:
    return InMemoryTrustedClock(NOW)


@pytest.fixture
def audit() -> RecordingAuditSink:
    return RecordingAuditSink()


@pytest.fixture
def alerts() -> RecordingAlertSink:
    return RecordingAlertSink()


@pytest.fixture
def stop() -> EmergencyStopController:
    return EmergencyStopController()


@pytest.fixture
def controller(
    registry: IdentityRegistry, stop: EmergencyStopController, clock: InMemoryTrustedClock, audit: RecordingAuditSink, alerts: RecordingAlertSink
) -> BreakGlassController:
    return BreakGlassController(identities=registry, stop=stop, clock=clock, audit=audit, alerts=alerts)


def _grant(controller: BreakGlassController, **overrides: object) -> BreakGlassGrant:
    arguments: dict[str, object] = {
        "grant_id": "bg-1",
        "requester": REQUESTER,
        "reason": "production-incident",
        "incident_ref": "INC-42",
        "scope": "urn:ocor:target:site-1",
        "domain": DOMAIN,
        "capabilities": frozenset({"restart_service", "read_diagnostics"}),
        "approvers": (SDO, OWNER),
        "ttl": timedelta(minutes=10),
    }
    arguments.update(overrides)
    return controller.grant(**arguments)  # type: ignore[arg-type]


def _reason(excinfo: pytest.ExceptionInfo[SafetyError]) -> str:
    return excinfo.value.reason_code


# --- grant: positive paths -------------------------------------------------------


def test_a_valid_grant_is_issued_on_the_trusted_clock_audited_and_alerted(
    controller: BreakGlassController, audit: RecordingAuditSink, alerts: RecordingAlertSink
) -> None:
    grant = _grant(controller)

    assert grant.granted_at == NOW
    assert grant.expires_at == NOW + timedelta(minutes=10)
    assert grant.requester == REQUESTER
    assert grant.domain == DOMAIN
    assert grant.capabilities == frozenset({"restart_service", "read_diagnostics"})
    assert audit.kinds() == ["BREAK_GLASS_GRANTED"]
    assert audit.events[0]["grant_id"] == "bg-1"
    assert audit.events[0]["at"] == NOW.isoformat()
    assert [alert["event"] for alert in alerts.alerts] == ["BREAK_GLASS_GRANTED"]


def test_the_role_quorum_is_satisfied_in_either_approver_order(controller: BreakGlassController) -> None:
    first = _grant(controller, grant_id="bg-order-1", approvers=(SDO, OWNER))
    second = _grant(controller, grant_id="bg-order-2", approvers=(OWNER, SDO))

    assert first.approvers == second.approvers


def test_an_approver_holding_both_roles_may_cover_one_of_them(controller: BreakGlassController) -> None:
    grant = _grant(controller, approvers=(BOTH_ROLES, OWNER))

    assert set(grant.approvers) == {BOTH_ROLES, OWNER}


def test_a_ttl_of_exactly_fifteen_minutes_is_accepted(controller: BreakGlassController) -> None:
    grant = _grant(controller, ttl=MAX_BREAK_GLASS_TTL)

    assert grant.expires_at == NOW + MAX_BREAK_GLASS_TTL


# --- grant: P3, no caller instant ------------------------------------------------


def test_grant_accepts_no_caller_supplied_instant(controller: BreakGlassController) -> None:
    assert "at" not in inspect.signature(BreakGlassController.grant).parameters
    with pytest.raises(TypeError):
        _grant(controller, at=NOW + timedelta(days=365))


def test_the_grant_window_follows_the_trusted_clock(controller: BreakGlassController, clock: InMemoryTrustedClock) -> None:
    clock.advance(timedelta(hours=3))

    grant = _grant(controller)

    assert grant.granted_at == NOW + timedelta(hours=3)


# --- grant: requester ------------------------------------------------------------


@pytest.mark.parametrize("approvers", [(REQUESTER, OWNER), (SDO, REQUESTER)])
def test_the_requester_can_never_approve_its_own_break_glass(controller: BreakGlassController, approvers: tuple[str, str]) -> None:
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, approvers=approvers)
    assert _reason(excinfo) == "BREAK_GLASS_REQUESTER_CANNOT_APPROVE"


@pytest.mark.parametrize("requester", ["urn:ocor:human:never-registered", INACTIVE_REQUESTER, ""])
def test_an_unresolved_inactive_or_missing_requester_is_refused(controller: BreakGlassController, requester: str) -> None:
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, requester=requester)
    assert _reason(excinfo) == "BREAK_GLASS_REQUESTER_INVALID"


def test_an_active_workload_may_request_but_never_approve(controller: BreakGlassController) -> None:
    grant = _grant(controller, requester=WORKLOAD_REQUESTER)

    assert grant.requester == WORKLOAD_REQUESTER


# --- grant: approvers (P2) -------------------------------------------------------


def test_two_distinct_approvers_are_required(controller: BreakGlassController) -> None:
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, approvers=(SDO, SDO))
    assert _reason(excinfo) == "BREAK_GLASS_REQUIRES_TWO_DISTINCT_HUMANS"


def test_exactly_two_approvers_are_required(controller: BreakGlassController) -> None:
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, approvers=(SDO, OWNER, BOTH_ROLES))
    assert _reason(excinfo) == "BREAK_GLASS_REQUIRES_TWO_DISTINCT_HUMANS"


def test_an_unresolved_approver_is_refused(controller: BreakGlassController) -> None:
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, approvers=(SDO, "urn:ocor:human:never-registered"))
    assert _reason(excinfo) == "BREAK_GLASS_REQUIRES_TWO_DISTINCT_HUMANS"


def test_a_workload_principal_can_never_approve(controller: BreakGlassController) -> None:
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, approvers=(WORKLOAD, OWNER))
    assert _reason(excinfo) == "BREAK_GLASS_APPROVER_NOT_HUMAN"


@pytest.mark.parametrize("approver", [SUSPENDED, NO_STATUS])
def test_an_approver_whose_status_is_not_active_is_refused(controller: BreakGlassController, approver: str) -> None:
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, approvers=(approver, OWNER))
    assert _reason(excinfo) == "BREAK_GLASS_APPROVER_INACTIVE"


@pytest.mark.parametrize("approver", [NO_KIND, BAD_KIND, UNSORTED_ROLES, DUPLICATE_ROLES, NON_STRING_ROLES, EMPTY_TOKEN_ROLES])
def test_missing_or_malformed_principal_attributes_fail_closed(controller: BreakGlassController, approver: str) -> None:
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, approvers=(approver, OWNER))
    assert _reason(excinfo) == "BREAK_GLASS_PRINCIPAL_ATTRIBUTES_INVALID"


@pytest.mark.parametrize(
    "approvers",
    [(SDO, SECOND_SDO), (SDO, OTHER_OWNER), (OWNER, OTHER_OWNER)],
    ids=["two-security-duty-officers", "owner-of-another-domain", "no-security-duty-officer"],
)
def test_the_security_duty_officer_plus_affected_domain_owner_quorum_is_enforced(
    controller: BreakGlassController, approvers: tuple[str, str]
) -> None:
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, approvers=approvers)
    assert _reason(excinfo) == "BREAK_GLASS_ROLE_QUORUM_UNMET"


def test_one_approver_holding_both_roles_cannot_satisfy_the_quorum_alone(controller: BreakGlassController) -> None:
    # BOTH_ROLES covers either role, OTHER_OWNER covers neither for this domain.
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, approvers=(BOTH_ROLES, OTHER_OWNER))
    assert _reason(excinfo) == "BREAK_GLASS_ROLE_QUORUM_UNMET"

    grant = _grant(controller, grant_id="bg-both-sdo", approvers=(BOTH_ROLES, SECOND_SDO))
    assert set(grant.approvers) == {BOTH_ROLES, SECOND_SDO}


def test_the_affected_domain_is_taken_from_the_grant(controller: BreakGlassController) -> None:
    grant = _grant(controller, domain="logistics", approvers=(SDO, OTHER_OWNER))

    assert grant.domain == "logistics"
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, grant_id="bg-wrong-domain", domain="logistics", approvers=(SDO, OWNER))
    assert _reason(excinfo) == "BREAK_GLASS_ROLE_QUORUM_UNMET"


# --- grant: Q1 PO condition, attributes only from the registry -------------------


@pytest.mark.parametrize(
    "declared",
    [
        {"approver_roles": {SDO: "SECURITY_DUTY_OFFICER", OTHER_OWNER: f"DOMAIN_OWNER:{DOMAIN}"}},
        {"approver_attributes": {OTHER_OWNER: {"roles": f"DOMAIN_OWNER:{DOMAIN}"}}},
        {"principal_kind": "HUMAN"},
        {"roles": f"DOMAIN_OWNER:{DOMAIN} SECURITY_DUTY_OFFICER"},
    ],
)
def test_principal_attributes_declared_in_the_request_are_never_accepted(controller: BreakGlassController, declared: dict[str, object]) -> None:
    with pytest.raises(TypeError):
        _grant(controller, approvers=(SDO, OTHER_OWNER), **declared)


def test_role_tokens_smuggled_into_request_text_fields_are_ignored(controller: BreakGlassController) -> None:
    smuggled = f"DOMAIN_OWNER:{DOMAIN} SECURITY_DUTY_OFFICER"
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, approvers=(SDO, OTHER_OWNER), reason=smuggled, scope=smuggled, incident_ref=smuggled)
    assert _reason(excinfo) == "BREAK_GLASS_ROLE_QUORUM_UNMET"


def test_a_requester_cannot_update_its_record_into_an_approver(controller: BreakGlassController, registry: IdentityRegistry) -> None:
    with pytest.raises(IdentityConflictError):
        registry.register(IdentityRecord(canonical_id=REQUESTER, attributes=_human("SECURITY_DUTY_OFFICER")))
    with pytest.raises(IdentityConflictError):
        registry.register(IdentityRecord(canonical_id=OTHER_OWNER, attributes=_human(f"DOMAIN_OWNER:{DOMAIN}")))

    assert registry.get(REQUESTER) is not None
    assert registry.get(REQUESTER).attributes["roles"] == ""  # type: ignore[union-attr]
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, approvers=(SDO, OTHER_OWNER))
    assert _reason(excinfo) == "BREAK_GLASS_ROLE_QUORUM_UNMET"


def test_the_controller_never_writes_principal_records(controller: BreakGlassController, registry: IdentityRegistry) -> None:
    before = {cid: registry.get(cid) for cid in RECORDS}
    grant = _grant(controller)
    controller.authorize(grant, capability="restart_service", review_ref="REV-1")
    controller.revoke(grant)

    assert {cid: registry.get(cid) for cid in RECORDS} == before
    assert registry.get(grant.grant_id) is None


# --- grant: capabilities, scope and TTL ------------------------------------------


def test_a_grant_without_named_capabilities_is_refused(controller: BreakGlassController) -> None:
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, capabilities=frozenset())
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_INVALID"


@pytest.mark.parametrize("capability", sorted(FORBIDDEN_BREAK_GLASS_CAPABILITIES))
def test_a_forbidden_capability_can_never_be_named_in_a_grant(controller: BreakGlassController, capability: str) -> None:
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, capabilities=frozenset({"restart_service", capability}))
    assert _reason(excinfo) == "BREAK_GLASS_FORBIDDEN_CAPABILITY"


@pytest.mark.parametrize("field", ["reason", "incident_ref", "scope", "domain"])
def test_missing_mandatory_grant_fields_are_refused(controller: BreakGlassController, field: str) -> None:
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, **{field: ""})
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_INVALID"


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1), MAX_BREAK_GLASS_TTL + timedelta(seconds=1)])
def test_a_ttl_outside_the_bound_is_refused(controller: BreakGlassController, audit: RecordingAuditSink, ttl: timedelta) -> None:
    with pytest.raises(ValueError, match="ttl"):
        _grant(controller, ttl=ttl)
    assert audit.kinds() == ["BREAK_GLASS_GRANT_DENIED"]
    assert audit.events[0]["reason_code"] == "BREAK_GLASS_GRANT_INVALID"


def test_a_grant_id_can_never_be_reissued(controller: BreakGlassController, clock: InMemoryTrustedClock) -> None:
    _grant(controller, ttl=timedelta(minutes=1))
    clock.advance(timedelta(minutes=2))

    with pytest.raises(SafetyError) as excinfo:
        _grant(controller)
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_ID_REUSED"


def test_there_is_no_renewal_path(controller: BreakGlassController) -> None:
    names = {name for name in dir(controller) if not name.startswith("_")}

    assert names == {"grant", "authorize", "revoke"}
    assert not any(token in name for name in dir(BreakGlassGrant) for token in ("renew", "extend"))


# --- grant: synchronous audit and immediate alert, fail-closed --------------------


def test_a_grant_whose_audit_append_fails_is_never_issued(controller: BreakGlassController, audit: RecordingAuditSink, alerts: RecordingAlertSink) -> None:
    audit.fail = True
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller)
    assert _reason(excinfo) == "BREAK_GLASS_AUDIT_UNAVAILABLE"
    assert alerts.alerts == []

    audit.fail = False
    forged = _hand_built(granted_at=NOW)
    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(forged, capability="restart_service", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_NOT_ISSUED"


def test_a_grant_whose_alert_fails_is_withdrawn_and_never_issued(controller: BreakGlassController, audit: RecordingAuditSink, alerts: RecordingAlertSink) -> None:
    alerts.fail = True
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller)
    assert _reason(excinfo) == "BREAK_GLASS_ALERT_UNAVAILABLE"
    assert audit.kinds() == ["BREAK_GLASS_GRANTED", "BREAK_GLASS_GRANT_WITHDRAWN"]

    alerts.fail = False
    forged = _hand_built(granted_at=NOW)
    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(forged, capability="restart_service", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_NOT_ISSUED"


def test_a_refused_grant_is_audited_with_its_reason(controller: BreakGlassController, audit: RecordingAuditSink) -> None:
    with pytest.raises(SafetyError):
        _grant(controller, approvers=(WORKLOAD, OWNER))

    assert audit.kinds() == ["BREAK_GLASS_GRANT_DENIED"]
    assert audit.events[0]["reason_code"] == "BREAK_GLASS_APPROVER_NOT_HUMAN"


def test_a_refused_grant_whose_audit_fails_is_still_refused(controller: BreakGlassController, audit: RecordingAuditSink) -> None:
    audit.fail = True
    with pytest.raises(SafetyError) as excinfo:
        _grant(controller, approvers=(WORKLOAD, OWNER))
    assert _reason(excinfo) == "BREAK_GLASS_AUDIT_UNAVAILABLE"


# --- authorize: P1, only issued and unaltered grants ------------------------------


def _hand_built(**overrides: object) -> BreakGlassGrant:
    fields: dict[str, object] = {
        "grant_id": "bg-1",
        "requester": REQUESTER,
        "reason": "production-incident",
        "incident_ref": "INC-42",
        "scope": "urn:ocor:target:site-1",
        "domain": DOMAIN,
        "capabilities": frozenset({"restart_service", "read_diagnostics"}),
        "approvers": (OWNER, SDO),
        "granted_at": NOW,
        "ttl": timedelta(minutes=10),
    }
    fields.update(overrides)
    return BreakGlassGrant(**fields)  # type: ignore[arg-type]


def test_a_grant_built_outside_the_controller_never_authorizes(controller: BreakGlassController) -> None:
    forged = _hand_built(approvers=("urn:ghost:1", "urn:ghost:2"))

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(forged, capability="restart_service", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_NOT_ISSUED"


def test_a_well_formed_copy_of_valid_fields_is_still_not_issued(controller: BreakGlassController) -> None:
    forged = _hand_built()

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(forged, capability="restart_service", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_NOT_ISSUED"


@pytest.mark.parametrize(
    "change",
    [
        {"capabilities": frozenset({"restart_service", "read_diagnostics", "delete_canonical_state"})},
        {"ttl": MAX_BREAK_GLASS_TTL},
        {"granted_at": NOW + timedelta(minutes=5)},
        {"scope": "urn:ocor:target:everything"},
        {"domain": "logistics"},
        {"requester": SECOND_SDO},
    ],
    ids=["capabilities", "ttl", "granted_at", "scope", "domain", "requester"],
)
def test_an_issued_grant_altered_after_issuance_never_authorizes(controller: BreakGlassController, change: dict[str, object]) -> None:
    grant = _grant(controller)
    altered = dataclasses.replace(grant, **change)  # type: ignore[arg-type]

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(altered, capability="restart_service", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_NOT_ISSUED"
    controller.authorize(grant, capability="restart_service", review_ref="REV-1")


def test_a_grant_issued_by_another_controller_never_authorizes(
    controller: BreakGlassController, registry: IdentityRegistry, stop: EmergencyStopController, clock: InMemoryTrustedClock
) -> None:
    other = BreakGlassController(identities=registry, stop=stop, clock=clock, audit=RecordingAuditSink(), alerts=RecordingAlertSink())
    foreign = _grant(other)

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(foreign, capability="restart_service", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_NOT_ISSUED"


# --- authorize: positive path, audit and alert ------------------------------------


def test_an_issued_grant_authorizes_a_named_capability_with_audit_and_alert(
    controller: BreakGlassController, clock: InMemoryTrustedClock, audit: RecordingAuditSink, alerts: RecordingAlertSink
) -> None:
    grant = _grant(controller)
    clock.advance(timedelta(minutes=3))

    use = controller.authorize(grant, capability="read_diagnostics", review_ref="REV-7")

    assert (use.grant_id, use.capability, use.review_ref, use.used_at) == ("bg-1", "read_diagnostics", "REV-7", NOW + timedelta(minutes=3))
    assert audit.kinds() == ["BREAK_GLASS_GRANTED", "BREAK_GLASS_USE_AUTHORIZED"]
    assert audit.events[1]["capability"] == "read_diagnostics"
    assert audit.events[1]["review_ref"] == "REV-7"
    assert [alert["event"] for alert in alerts.alerts] == ["BREAK_GLASS_GRANTED", "BREAK_GLASS_USE_AUTHORIZED"]


def test_authorize_accepts_no_caller_supplied_instant(controller: BreakGlassController, clock: InMemoryTrustedClock) -> None:
    grant = _grant(controller, ttl=timedelta(minutes=1))
    clock.advance(timedelta(minutes=2))

    assert "at" not in inspect.signature(BreakGlassController.authorize).parameters
    with pytest.raises(TypeError):
        controller.authorize(grant, capability="restart_service", review_ref="REV-1", at=NOW)  # type: ignore[call-arg]
    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_EXPIRED"


# --- authorize: X1, named capabilities --------------------------------------------


def test_a_capability_not_named_in_the_grant_is_refused(controller: BreakGlassController) -> None:
    grant = _grant(controller, capabilities=frozenset({"restart_service"}))

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="delete_canonical_state", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_CAPABILITY_NOT_GRANTED"
    controller.authorize(grant, capability="restart_service", review_ref="REV-1")


@pytest.mark.parametrize("capability", sorted(FORBIDDEN_BREAK_GLASS_CAPABILITIES))
def test_a_forbidden_capability_is_refused_at_use(controller: BreakGlassController, capability: str) -> None:
    grant = _grant(controller)

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability=capability, review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_FORBIDDEN_CAPABILITY"


# --- authorize: trusted-time window, expiry and revocation ------------------------


def test_the_window_closes_exactly_at_expiry_on_the_trusted_clock(controller: BreakGlassController, clock: InMemoryTrustedClock) -> None:
    grant = _grant(controller, ttl=timedelta(minutes=5))
    clock.advance(timedelta(minutes=5) - timedelta(microseconds=1))
    controller.authorize(grant, capability="restart_service", review_ref="REV-1")

    clock.advance(timedelta(microseconds=1))
    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-2")
    assert _reason(excinfo) == "BREAK_GLASS_EXPIRED"


def test_expiry_revokes_automatically_and_a_rewound_clock_never_revives_the_grant(
    registry: IdentityRegistry, stop: EmergencyStopController, audit: RecordingAuditSink, alerts: RecordingAlertSink
) -> None:
    clock = SettableClock(NOW)
    controller = BreakGlassController(identities=registry, stop=stop, clock=clock, audit=audit, alerts=alerts)
    grant = _grant(controller, ttl=timedelta(minutes=5))
    clock.current = NOW + timedelta(minutes=5)
    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_EXPIRED"
    assert "BREAK_GLASS_EXPIRED_REVOKED" in audit.kinds()

    clock.current = NOW + timedelta(minutes=1)
    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-2")
    assert _reason(excinfo) == "BREAK_GLASS_EXPIRED"


def test_a_trusted_instant_before_issuance_is_refused(
    registry: IdentityRegistry, stop: EmergencyStopController, audit: RecordingAuditSink, alerts: RecordingAlertSink
) -> None:
    clock = SettableClock(NOW)
    controller = BreakGlassController(identities=registry, stop=stop, clock=clock, audit=audit, alerts=alerts)
    grant = _grant(controller)
    clock.current = NOW - timedelta(seconds=1)

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_NOT_YET_VALID"

    clock.current = NOW
    controller.authorize(grant, capability="restart_service", review_ref="REV-1")


def test_a_naive_trusted_instant_fails_closed(
    registry: IdentityRegistry, stop: EmergencyStopController, audit: RecordingAuditSink, alerts: RecordingAlertSink
) -> None:
    clock = SettableClock(NOW.replace(tzinfo=None))
    controller = BreakGlassController(identities=registry, stop=stop, clock=clock, audit=audit, alerts=alerts)

    with pytest.raises(TemporalGuardViolation):
        _grant(controller)


def test_a_revoked_grant_denies_immediately_and_the_revocation_is_audited(controller: BreakGlassController, audit: RecordingAuditSink) -> None:
    grant = _grant(controller)
    controller.authorize(grant, capability="restart_service", review_ref="REV-1")
    controller.revoke(grant)

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-2")
    assert _reason(excinfo) == "BREAK_GLASS_EXPIRED"
    assert "BREAK_GLASS_REVOKED" in audit.kinds()


def test_revoking_a_grant_that_was_never_issued_is_refused(controller: BreakGlassController) -> None:
    with pytest.raises(SafetyError) as excinfo:
        controller.revoke(_hand_built())
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_NOT_ISSUED"


def test_a_revocation_holds_even_when_its_audit_append_fails(controller: BreakGlassController, audit: RecordingAuditSink) -> None:
    grant = _grant(controller)
    audit.fail = True

    with pytest.raises(SafetyError) as excinfo:
        controller.revoke(grant)
    assert _reason(excinfo) == "BREAK_GLASS_AUDIT_UNAVAILABLE"

    audit.fail = False
    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_EXPIRED"


# --- authorize: emergency stop and mandatory review -------------------------------


def test_break_glass_never_overrides_an_active_emergency_stop(controller: BreakGlassController, stop: EmergencyStopController) -> None:
    grant = _grant(controller)
    controller.authorize(grant, capability="restart_service", review_ref="REV-1")
    stop.activate(reason="unrelated-incident", at=NOW)

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-2")
    assert _reason(excinfo) == "BREAK_GLASS_STOP_ACTIVE"


def test_every_use_requires_a_review_reference(controller: BreakGlassController) -> None:
    grant = _grant(controller)

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="")
    assert _reason(excinfo) == "BREAK_GLASS_REVIEW_REQUIRED"


# --- authorize: P2, re-validation of principals at every use ----------------------


def _directory_controller(
    stop: EmergencyStopController, clock: InMemoryTrustedClock, audit: RecordingAuditSink, alerts: RecordingAlertSink
) -> tuple[BreakGlassController, MutableDirectory]:
    directory = MutableDirectory(RECORDS)
    return BreakGlassController(identities=directory, stop=stop, clock=clock, audit=audit, alerts=alerts), directory


@pytest.mark.parametrize(
    ("principal", "change", "reason"),
    [
        (SDO, None, "BREAK_GLASS_REQUIRES_TWO_DISTINCT_HUMANS"),
        (SDO, _human("SECURITY_DUTY_OFFICER", status="SUSPENDED"), "BREAK_GLASS_APPROVER_INACTIVE"),
        (OWNER, {"principal_kind": "WORKLOAD", "status": "ACTIVE", "roles": f"DOMAIN_OWNER:{DOMAIN}"}, "BREAK_GLASS_APPROVER_NOT_HUMAN"),
        (OWNER, _human(), "BREAK_GLASS_ROLE_QUORUM_UNMET"),
        (SDO, {"principal_kind": "HUMAN", "status": "ACTIVE", "roles": ["SECURITY_DUTY_OFFICER"]}, "BREAK_GLASS_PRINCIPAL_ATTRIBUTES_INVALID"),
        (REQUESTER, _human(status="DISABLED"), "BREAK_GLASS_REQUESTER_INVALID"),
        (REQUESTER, None, "BREAK_GLASS_REQUESTER_INVALID"),
    ],
    ids=["approver-removed", "approver-suspended", "approver-became-workload", "owner-role-removed", "roles-malformed", "requester-disabled", "requester-removed"],
)
def test_principals_are_revalidated_against_the_registry_at_every_use(
    stop: EmergencyStopController,
    clock: InMemoryTrustedClock,
    audit: RecordingAuditSink,
    alerts: RecordingAlertSink,
    principal: str,
    change: dict[str, object] | None,
    reason: str,
) -> None:
    controller, directory = _directory_controller(stop, clock, audit, alerts)
    grant = _grant(controller)
    controller.authorize(grant, capability="restart_service", review_ref="REV-1")

    if change is None:
        directory.remove(principal)
    else:
        directory.replace(principal, change)

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-2")
    assert _reason(excinfo) == reason


def test_unchanged_principals_keep_authorizing_on_a_changing_directory(
    stop: EmergencyStopController, clock: InMemoryTrustedClock, audit: RecordingAuditSink, alerts: RecordingAlertSink
) -> None:
    controller, directory = _directory_controller(stop, clock, audit, alerts)
    grant = _grant(controller)
    directory.replace(OTHER_OWNER, _human())

    controller.authorize(grant, capability="restart_service", review_ref="REV-1")
    controller.authorize(grant, capability="read_diagnostics", review_ref="REV-2")


# --- authorize: synchronous audit and immediate alert, fail-closed ----------------


def test_a_use_whose_audit_append_fails_is_refused(controller: BreakGlassController, audit: RecordingAuditSink, alerts: RecordingAlertSink) -> None:
    grant = _grant(controller)
    audit.fail = True

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_AUDIT_UNAVAILABLE"
    assert [alert["event"] for alert in alerts.alerts] == ["BREAK_GLASS_GRANTED"]


def test_a_use_whose_alert_fails_is_withdrawn_and_refused(controller: BreakGlassController, audit: RecordingAuditSink, alerts: RecordingAlertSink) -> None:
    grant = _grant(controller)
    alerts.fail = True

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_ALERT_UNAVAILABLE"
    assert audit.kinds() == ["BREAK_GLASS_GRANTED", "BREAK_GLASS_USE_AUTHORIZED", "BREAK_GLASS_USE_WITHDRAWN"]


def test_a_refused_use_is_audited_with_its_reason(controller: BreakGlassController, audit: RecordingAuditSink) -> None:
    grant = _grant(controller, capabilities=frozenset({"restart_service"}))

    with pytest.raises(SafetyError):
        controller.authorize(grant, capability="read_diagnostics", review_ref="REV-1")

    assert audit.kinds() == ["BREAK_GLASS_GRANTED", "BREAK_GLASS_USE_DENIED"]
    assert audit.events[1]["reason_code"] == "BREAK_GLASS_CAPABILITY_NOT_GRANTED"


def test_a_refused_use_whose_audit_fails_is_still_refused(controller: BreakGlassController, audit: RecordingAuditSink) -> None:
    grant = _grant(controller, capabilities=frozenset({"restart_service"}))
    audit.fail = True

    with pytest.raises(SafetyError) as excinfo:
        controller.authorize(grant, capability="read_diagnostics", review_ref="REV-1")
    assert _reason(excinfo) == "BREAK_GLASS_AUDIT_UNAVAILABLE"
