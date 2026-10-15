"""C6 -- compensation reconciliation, break-glass and emergency stop.

The smallest contract-compliant slice of LLD v1.1 sections 4.2/4.3 and
6's normative safety obligations, layered on the sealed 44-transition
table (OCOR-DEV-0042, ``ocor_runtime.c6.fsm``, reused unmodified) and
the sealed Human Gate dual-control coordinator (OCOR-DEV-0043,
``ocor_runtime.c6.human_gate``, reused unmodified only conceptually).
Reads the sealed ``ocor_runtime.c2_identity.IdentityRegistry``
(unmodified) to resolve and re-validate break-glass principals.

Three real safety mechanisms, each producing immutable evidence:

* ``EmergencyStopController`` -- the approved ``NORMAL -> STOPPING ->
  STOPPED -> RESET_PENDING -> NORMAL`` machine (LLD 4.3). Accepting a
  stop atomically increments a monotonic ``stop_epoch`` under a real
  lock; ``guard_dispatch`` fails closed unless the system is
  ``NORMAL`` *and* the presented fencing epoch is exactly the current
  one -- a command fenced to any other epoch, older or from a prior
  stop/reset cycle, can never dispatch, so a reset never silently
  re-enables a lease issued before it. Reset requires dual control
  (two distinct, resolved human approvers).
* ``BreakGlassController`` -- a bounded, dual-human-approved
  exceptional grant (ADD v1.3 sections 5.4-5.5, LLD 4.2, aligned by
  OCOR-DEV-REM-0024): requires a requester, a typed reason, an
  incident reference, a minimal scope, the affected domain, named
  capabilities, and two distinct human approvers who are never the
  requester and together hold ``SECURITY_DUTY_OFFICER`` and
  ``DOMAIN_OWNER:<domain>`` -- kind, status and roles read only from
  the identity registry. TTL is bounded by ``MAX_BREAK_GLASS_TTL`` and
  never renewed. ``authorize`` honours only grants this controller
  issued, re-validates every principal on every use, decides validity
  on the injected trusted clock (never a caller instant), restricts
  use to the named capabilities and never allows one on the fixed
  ``FORBIDDEN_BREAK_GLASS_CAPABILITIES`` denylist (create a Decision,
  reduce marking, disable provenance/audit, ignore emergency stop,
  change the release pin, authorize R3 without quorum, or access
  outside compartment), nor any use while an emergency stop is active.
  Every use requires a non-empty review reference, making the LLD's
  "review obbligatoria" structural; grants, uses, refusals and
  revocations are audited synchronously and grants and uses alerted
  immediately, failing closed.
* ``OutcomeReconciler`` -- LLD ``ACT-T18a``/``T18b``/``T20a``-``c``/
  ``T21``-``T21e``/``T24``/``T25``'s ambiguous-outcome and compensation
  reconciliation path: an ambiguous timeout suspends retry and opens
  reconciliation; real ``Evidence`` resolves it to confirmed/failed
  (or compensated/compensation-failed); no evidence before the
  reconciliation deadline escalates to ``INDETERMINATE`` and opens
  adjudication, never inferring an outcome. ``require_may_auto_retry``
  is the task's own core negative claim made executable: an ambiguous
  outcome whose effect is not proven idempotent can never be
  auto-retried, no matter how long it has been ambiguous.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol

from ..c2_identity import IdentityRecord, IdentityRegistry
from ..c3_store import require_aware
from ..errors import OCORError
from ..kernel.governance import TrustedClock

MAX_BREAK_GLASS_TTL = timedelta(minutes=15)

FORBIDDEN_BREAK_GLASS_CAPABILITIES = frozenset(
    {
        "create_decision",
        "reduce_marking",
        "disable_provenance",
        "disable_audit",
        "ignore_emergency_stop",
        "change_release_pin",
        "authorize_r3_without_quorum",
        "access_outside_compartment",
    }
)


class SafetyError(OCORError):
    """A safety mechanism refused an operation. ``reason_code``
    identifies why, mirroring the reason-code pattern already
    established by every other retained C1-C8 component this
    session."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


class StopStatus(str, Enum):
    NORMAL = "NORMAL"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    RESET_PENDING = "RESET_PENDING"


@dataclass(frozen=True, slots=True)
class StopEvent:
    epoch: int
    status: StopStatus
    reason: str
    at: datetime


class EmergencyStopController:
    """The approved emergency-stop FSM with a real lock around its
    epoch and status, so a concurrent activation and dispatch attempt
    can never race past each other."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._status = StopStatus.NORMAL
        self._epoch = 0
        self._history: list[StopEvent] = []

    @property
    def status(self) -> StopStatus:
        with self._lock:
            return self._status

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    @property
    def history(self) -> tuple[StopEvent, ...]:
        with self._lock:
            return tuple(self._history)

    def activate(self, *, reason: str, at: datetime) -> StopEvent:
        instant = require_aware(at, field="at")
        if not reason:
            raise ValueError("an emergency stop requires a reason")
        with self._lock:
            if self._status is not StopStatus.NORMAL:
                raise SafetyError("INVALID_STOP_TRANSITION", f"cannot activate stop from {self._status.value}")
            self._epoch += 1
            self._status = StopStatus.STOPPING
            event = StopEvent(epoch=self._epoch, status=self._status, reason=reason, at=instant)
            self._history.append(event)
            return event

    def finish_draining(self, *, at: datetime) -> StopEvent:
        instant = require_aware(at, field="at")
        with self._lock:
            if self._status is not StopStatus.STOPPING:
                raise SafetyError("INVALID_STOP_TRANSITION", f"cannot finish draining from {self._status.value}")
            self._status = StopStatus.STOPPED
            event = StopEvent(epoch=self._epoch, status=self._status, reason="drain complete", at=instant)
            self._history.append(event)
            return event

    def request_reset(self, *, approvers: tuple[str, str], identities: IdentityRegistry, at: datetime) -> StopEvent:
        instant = require_aware(at, field="at")
        distinct = set(approvers)
        if len(distinct) != 2:
            raise SafetyError("RESET_REQUIRES_DUAL_CONTROL", "reset requires exactly two distinct human approvers")
        for principal in distinct:
            if identities.get(principal) is None:
                raise SafetyError("RESET_REQUIRES_DUAL_CONTROL", f"unresolved approver: {principal!r}")
        with self._lock:
            if self._status is not StopStatus.STOPPED:
                raise SafetyError("INVALID_STOP_TRANSITION", f"cannot request reset from {self._status.value}")
            self._status = StopStatus.RESET_PENDING
            event = StopEvent(epoch=self._epoch, status=self._status, reason="reset requested", at=instant)
            self._history.append(event)
            return event

    def confirm_reset(self, *, at: datetime) -> StopEvent:
        instant = require_aware(at, field="at")
        with self._lock:
            if self._status is not StopStatus.RESET_PENDING:
                raise SafetyError("INVALID_STOP_TRANSITION", f"cannot confirm reset from {self._status.value}")
            # A brand-new epoch: never re-enables a lease or command
            # fenced to the pre-stop epoch, even now that the system
            # is NORMAL again.
            self._epoch += 1
            self._status = StopStatus.NORMAL
            event = StopEvent(epoch=self._epoch, status=self._status, reason="reset confirmed, new epoch issued", at=instant)
            self._history.append(event)
            return event

    def guard_dispatch(self, *, fenced_epoch: int) -> None:
        with self._lock:
            if self._status is not StopStatus.NORMAL:
                raise SafetyError("SYSTEM_NOT_NORMAL", f"emergency stop is {self._status.value}, dispatch is blocked")
            if fenced_epoch != self._epoch:
                raise SafetyError("STOP_EPOCH_STALE", f"command fenced to epoch {fenced_epoch}, current epoch is {self._epoch}")


@dataclass(frozen=True, slots=True)
class BreakGlassGrant:
    """A break-glass grant as issued by ``BreakGlassController.grant``.

    Constructing one directly yields a well-formed value with no
    authority: ``authorize`` only honours a grant equal to the one the
    controller itself issued and registered."""

    grant_id: str
    requester: str
    reason: str
    incident_ref: str
    scope: str
    domain: str
    capabilities: frozenset[str]
    approvers: tuple[str, str]
    granted_at: datetime
    ttl: timedelta

    def __post_init__(self) -> None:
        require_aware(self.granted_at, field="granted_at")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        if not self.grant_id:
            raise ValueError("a BreakGlassGrant requires a grant_id")
        if not self.requester:
            raise ValueError("a BreakGlassGrant requires a requester")
        if not self.reason:
            raise ValueError("a BreakGlassGrant requires a typed reason")
        if not self.incident_ref:
            raise ValueError("a BreakGlassGrant requires an incident_ref")
        if not self.scope:
            raise ValueError("a BreakGlassGrant requires a minimal scope")
        if not self.domain or any(character.isspace() for character in self.domain):
            raise ValueError("a BreakGlassGrant requires the affected domain")
        if not self.capabilities or not all(isinstance(name, str) and name for name in self.capabilities):
            raise ValueError("a BreakGlassGrant requires at least one named capability")
        if len(self.approvers) != 2 or len(set(self.approvers)) != 2:
            raise ValueError("a BreakGlassGrant requires exactly two distinct human approvers")
        if self.requester in self.approvers:
            raise ValueError("the requester of a BreakGlassGrant can never approve it")
        if self.ttl <= timedelta(0) or self.ttl > MAX_BREAK_GLASS_TTL:
            raise ValueError(f"break-glass ttl must be positive and at most {MAX_BREAK_GLASS_TTL}")

    @property
    def expires_at(self) -> datetime:
        return self.granted_at + self.ttl


@dataclass(frozen=True, slots=True)
class BreakGlassUse:
    """Immutable evidence of one authorized use -- the mandatory
    review reference is captured on the record itself, never
    optional."""

    grant_id: str
    capability: str
    review_ref: str
    used_at: datetime


class PrincipalDirectory(Protocol):
    """Read-only view of the authoritative identity registry
    (``IdentityRegistry`` satisfies it). The controller never writes
    principal records."""

    def get(self, canonical_id: str) -> IdentityRecord | None:
        """Return the canonical record, or ``None`` when unresolved."""


class BreakGlassAuditSink(Protocol):
    def record(self, event: Mapping[str, object]) -> None:
        """Durably append one immutable audit event; raising fails the operation closed."""


class BreakGlassAlertSink(Protocol):
    def alert(self, event: Mapping[str, object]) -> None:
        """Deliver one immediate alert; raising fails the operation closed."""


# PoC convention on the reserved scalar ``attributes`` of identity-record
# v1.2 (PO decision REM-0024-BREAK-GLASS-PRINCIPAL-AUTHORITY, Q1): an
# interpretation, not a contract extension.
PRINCIPAL_KIND_ATTRIBUTE = "principal_kind"
STATUS_ATTRIBUTE = "status"
ROLES_ATTRIBUTE = "roles"
PRINCIPAL_KINDS = frozenset({"HUMAN", "WORKLOAD"})
ACTIVE_STATUS = "ACTIVE"
SECURITY_DUTY_OFFICER_ROLE = "SECURITY_DUTY_OFFICER"
DOMAIN_OWNER_ROLE_PREFIX = "DOMAIN_OWNER:"
_ROLE_TOKEN = re.compile(r"[A-Z][A-Z0-9_]*(?::\S+)?")


@dataclass(frozen=True, slots=True)
class _Principal:
    canonical_id: str
    kind: str
    active: bool
    roles: frozenset[str]


def _read_principal(directory: PrincipalDirectory, canonical_id: str) -> _Principal | None:
    """Principal kind, status and roles read exclusively from the
    registry record; absent or malformed attributes fail closed."""

    record = directory.get(canonical_id)
    if record is None:
        return None
    attributes = record.attributes
    kind = attributes.get(PRINCIPAL_KIND_ATTRIBUTE)
    if kind not in PRINCIPAL_KINDS:
        raise SafetyError("BREAK_GLASS_PRINCIPAL_ATTRIBUTES_INVALID", f"{canonical_id!r} has no valid {PRINCIPAL_KIND_ATTRIBUTE}")
    raw_roles = attributes.get(ROLES_ATTRIBUTE, "")
    if not isinstance(raw_roles, str):
        raise SafetyError("BREAK_GLASS_PRINCIPAL_ATTRIBUTES_INVALID", f"{canonical_id!r} has non-string {ROLES_ATTRIBUTE}")
    tokens = raw_roles.split(" ") if raw_roles else []
    if (
        any(_ROLE_TOKEN.fullmatch(token) is None for token in tokens)
        or tokens != sorted(tokens)
        or len(set(tokens)) != len(tokens)
    ):
        raise SafetyError(
            "BREAK_GLASS_PRINCIPAL_ATTRIBUTES_INVALID",
            f"{canonical_id!r} {ROLES_ATTRIBUTE} must be sorted, unique, single-space separated role tokens",
        )
    return _Principal(
        canonical_id=canonical_id,
        kind=str(kind),
        active=attributes.get(STATUS_ATTRIBUTE) == ACTIVE_STATUS,
        roles=frozenset(tokens),
    )


def _event(kind: str, grant: BreakGlassGrant | None, at: datetime, **fields: object) -> dict[str, object]:
    event: dict[str, object] = {"event": kind, "at": at.isoformat()}
    if grant is not None:
        event.update(
            grant_id=grant.grant_id,
            requester=grant.requester,
            approvers=list(grant.approvers),
            domain=grant.domain,
            scope=grant.scope,
            incident_ref=grant.incident_ref,
            capabilities=sorted(grant.capabilities),
            expires_at=grant.expires_at.isoformat(),
        )
    event.update(fields)
    return event


class BreakGlassController:
    """Issues, authorizes and revokes break-glass grants (ADD v1.3
    sections 5.4-5.5, LLD v1.1 sections 1.1/4.2).

    * Only grants issued by this controller and unaltered since are
      honoured; a grant id is never reissued, so there is no renewal.
    * Time is the boundary's ``TrustedClock``; no operation accepts a
      caller instant. Expiry revokes the grant for good.
    * Requester and approvers are (re)validated against the registry
      at grant time and at every use: approvers resolved, ``HUMAN``,
      ``ACTIVE``, distinct, never the requester, covering
      ``SECURITY_DUTY_OFFICER`` + ``DOMAIN_OWNER:<grant domain>``.
    * Every grant, use, refusal and revocation is appended to the audit
      sink synchronously; grants and uses also raise an immediate
      alert. An audit or alert failure fails the operation closed.
    """

    def __init__(
        self,
        *,
        identities: PrincipalDirectory,
        stop: EmergencyStopController,
        clock: TrustedClock,
        audit: BreakGlassAuditSink,
        alerts: BreakGlassAlertSink,
    ) -> None:
        self._identities = identities
        self._stop = stop
        self._clock = clock
        self._audit = audit
        self._alerts = alerts
        self._lock = threading.RLock()
        self._issued: dict[str, BreakGlassGrant] = {}
        self._revoked_grant_ids: set[str] = set()

    def _now(self) -> datetime:
        return require_aware(self._clock.now(), field="trusted clock")

    def _append(self, event: Mapping[str, object], *, cause: BaseException | None = None) -> None:
        try:
            self._audit.record(event)
        except Exception as exc:
            raise SafetyError("BREAK_GLASS_AUDIT_UNAVAILABLE", f"audit append of {event['event']} failed") from (cause or exc)

    def _refuse(self, kind: str, grant: BreakGlassGrant | None, at: datetime, error: SafetyError, **fields: object) -> SafetyError:
        self._append(_event(kind, grant, at, reason_code=error.reason_code, **fields), cause=error)
        return error

    def _validate_principals(self, requester: str, approvers: tuple[str, ...], domain: str) -> None:
        if len(approvers) != 2 or len(set(approvers)) != 2:
            raise SafetyError("BREAK_GLASS_REQUIRES_TWO_DISTINCT_HUMANS", "break-glass requires exactly two distinct human approvers")
        if requester in approvers:
            raise SafetyError("BREAK_GLASS_REQUESTER_CANNOT_APPROVE", "the requester can never approve its own break-glass")
        requesting = _read_principal(self._identities, requester) if requester else None
        if requesting is None or not requesting.active:
            raise SafetyError("BREAK_GLASS_REQUESTER_INVALID", f"requester {requester!r} is not a resolved active principal")
        principals: list[_Principal] = []
        for approver in approvers:
            principal = _read_principal(self._identities, approver)
            if principal is None:
                raise SafetyError("BREAK_GLASS_REQUIRES_TWO_DISTINCT_HUMANS", f"unresolved approver: {approver!r}")
            if principal.kind != "HUMAN":
                raise SafetyError("BREAK_GLASS_APPROVER_NOT_HUMAN", f"approver {approver!r} is not a human principal")
            if not principal.active:
                raise SafetyError("BREAK_GLASS_APPROVER_INACTIVE", f"approver {approver!r} is not active")
            principals.append(principal)
        owner_role = DOMAIN_OWNER_ROLE_PREFIX + domain
        first, second = principals
        if not (
            (SECURITY_DUTY_OFFICER_ROLE in first.roles and owner_role in second.roles)
            or (SECURITY_DUTY_OFFICER_ROLE in second.roles and owner_role in first.roles)
        ):
            raise SafetyError(
                "BREAK_GLASS_ROLE_QUORUM_UNMET",
                f"break-glass requires a {SECURITY_DUTY_OFFICER_ROLE} and the affected {owner_role}, held by distinct approvers",
            )

    def grant(
        self,
        *,
        grant_id: str,
        requester: str,
        reason: str,
        incident_ref: str,
        scope: str,
        domain: str,
        capabilities: frozenset[str],
        approvers: tuple[str, ...],
        ttl: timedelta,
    ) -> BreakGlassGrant:
        instant = self._now()
        request = {"grant_id": grant_id, "requester": requester, "approvers": list(approvers), "domain": domain}
        with self._lock:
            try:
                if not (grant_id and reason and incident_ref and scope and domain and capabilities):
                    raise SafetyError(
                        "BREAK_GLASS_GRANT_INVALID",
                        "grant id, typed reason, incident, minimal scope, affected domain and named capabilities are mandatory",
                    )
                if grant_id in self._issued:
                    raise SafetyError("BREAK_GLASS_GRANT_ID_REUSED", f"grant {grant_id!r} was already issued; break-glass is never renewed")
                forbidden = sorted(set(capabilities) & FORBIDDEN_BREAK_GLASS_CAPABILITIES)
                if forbidden:
                    raise SafetyError("BREAK_GLASS_FORBIDDEN_CAPABILITY", f"break-glass can never grant {forbidden}")
                self._validate_principals(requester, tuple(approvers), domain)
            except SafetyError as error:
                raise self._refuse("BREAK_GLASS_GRANT_DENIED", None, instant, error, **request) from error
            first, second = sorted(approvers)
            try:
                issued = BreakGlassGrant(
                    grant_id=grant_id,
                    requester=requester,
                    reason=reason,
                    incident_ref=incident_ref,
                    scope=scope,
                    domain=domain,
                    capabilities=frozenset(capabilities),
                    approvers=(first, second),
                    granted_at=instant,
                    ttl=ttl,
                )
            except ValueError as invalid:
                self._append(
                    _event("BREAK_GLASS_GRANT_DENIED", None, instant, reason_code="BREAK_GLASS_GRANT_INVALID", detail=str(invalid), **request),
                    cause=invalid,
                )
                raise
            granted = _event("BREAK_GLASS_GRANTED", issued, instant, reason=reason)
            self._append(granted)
            try:
                self._alerts.alert(granted)
            except Exception as exc:
                alert_error = SafetyError("BREAK_GLASS_ALERT_UNAVAILABLE", f"immediate alert for grant {grant_id!r} failed; grant withdrawn")
                self._append(_event("BREAK_GLASS_GRANT_WITHDRAWN", issued, instant, reason_code=alert_error.reason_code), cause=exc)
                raise alert_error from exc
            self._issued[grant_id] = issued
        return issued

    def _require_issued(self, grant: BreakGlassGrant) -> None:
        if self._issued.get(grant.grant_id) != grant:
            raise SafetyError("BREAK_GLASS_GRANT_NOT_ISSUED", f"grant {grant.grant_id!r} was not issued by this controller or was altered")

    def revoke(self, grant: BreakGlassGrant) -> None:
        instant = self._now()
        with self._lock:
            self._require_issued(grant)
            # The revocation takes effect before, and independently of,
            # its audit append: a failing audit store never keeps a
            # grant usable.
            self._revoked_grant_ids.add(grant.grant_id)
            self._append(_event("BREAK_GLASS_REVOKED", grant, instant))

    def authorize(self, grant: BreakGlassGrant, *, capability: str, review_ref: str) -> BreakGlassUse:
        instant = self._now()
        with self._lock:
            try:
                self._require_issued(grant)
                if grant.grant_id in self._revoked_grant_ids:
                    raise SafetyError("BREAK_GLASS_EXPIRED", f"grant {grant.grant_id!r} was revoked")
                if instant >= grant.expires_at:
                    # Automatic revocation at expiry: a later (or rewound)
                    # trusted instant can never revive the grant.
                    self._revoked_grant_ids.add(grant.grant_id)
                    self._append(_event("BREAK_GLASS_EXPIRED_REVOKED", grant, instant))
                    raise SafetyError("BREAK_GLASS_EXPIRED", f"grant {grant.grant_id!r} expired at {grant.expires_at.isoformat()}")
                if instant < grant.granted_at:
                    raise SafetyError("BREAK_GLASS_NOT_YET_VALID", f"grant {grant.grant_id!r} is valid from {grant.granted_at.isoformat()}")
                if capability in FORBIDDEN_BREAK_GLASS_CAPABILITIES:
                    raise SafetyError("BREAK_GLASS_FORBIDDEN_CAPABILITY", f"break-glass can never authorize {capability!r}")
                if capability not in grant.capabilities:
                    raise SafetyError("BREAK_GLASS_CAPABILITY_NOT_GRANTED", f"{capability!r} is not a capability named in grant {grant.grant_id!r}")
                if self._stop.status is not StopStatus.NORMAL:
                    raise SafetyError("BREAK_GLASS_STOP_ACTIVE", "break-glass can never override an active emergency stop")
                if not review_ref:
                    raise SafetyError("BREAK_GLASS_REVIEW_REQUIRED", "every break-glass use requires a mandatory review reference")
                self._validate_principals(grant.requester, grant.approvers, grant.domain)
            except SafetyError as error:
                raise self._refuse(
                    "BREAK_GLASS_USE_DENIED", None, instant, error, grant_id=grant.grant_id, capability=capability, review_ref=review_ref
                ) from error
            authorized = _event("BREAK_GLASS_USE_AUTHORIZED", grant, instant, capability=capability, review_ref=review_ref)
            self._append(authorized)
            try:
                self._alerts.alert(authorized)
            except Exception as exc:
                alert_error = SafetyError("BREAK_GLASS_ALERT_UNAVAILABLE", f"immediate alert for a use of {grant.grant_id!r} failed; use withdrawn")
                self._append(
                    _event("BREAK_GLASS_USE_WITHDRAWN", grant, instant, capability=capability, review_ref=review_ref, reason_code=alert_error.reason_code),
                    cause=exc,
                )
                raise alert_error from exc
            return BreakGlassUse(grant_id=grant.grant_id, capability=capability, review_ref=review_ref, used_at=instant)


class OutcomeStatus(str, Enum):
    CONFIRMED = "EXECUTION_CONFIRMED"
    FAILED = "EXECUTION_FAILED"
    UNKNOWN = "EXECUTION_UNKNOWN"
    INDETERMINATE = "EXECUTION_INDETERMINATE"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    COMPENSATION_UNKNOWN = "COMPENSATION_UNKNOWN"
    COMPENSATION_INDETERMINATE = "COMPENSATION_INDETERMINATE"


_AMBIGUOUS_STATUSES = frozenset(
    {
        OutcomeStatus.UNKNOWN,
        OutcomeStatus.COMPENSATION_UNKNOWN,
        OutcomeStatus.INDETERMINATE,
        OutcomeStatus.COMPENSATION_INDETERMINATE,
    }
)
_RESOLVABLE_STATUSES = frozenset({OutcomeStatus.UNKNOWN, OutcomeStatus.COMPENSATION_UNKNOWN})


@dataclass(frozen=True, slots=True)
class ReconciliationRecord:
    command_id: str
    status: OutcomeStatus
    idempotent_effect_proven: bool
    recorded_at: datetime
    note: str


class OutcomeReconciler:
    def __init__(self) -> None:
        self._records: dict[str, ReconciliationRecord] = {}

    @property
    def records(self) -> tuple[ReconciliationRecord, ...]:
        return tuple(self._records.values())

    def status(self, command_id: str) -> OutcomeStatus:
        return self._require_record(command_id).status

    def _require_record(self, command_id: str) -> ReconciliationRecord:
        record = self._records.get(command_id)
        if record is None:
            raise SafetyError("UNKNOWN_COMMAND", f"no reconciliation record for {command_id!r}")
        return record

    def mark_ambiguous(
        self, command_id: str, *, idempotent_effect_proven: bool, at: datetime, note: str = "ambiguous timeout"
    ) -> ReconciliationRecord:
        instant = require_aware(at, field="at")
        record = ReconciliationRecord(
            command_id=command_id, status=OutcomeStatus.UNKNOWN, idempotent_effect_proven=idempotent_effect_proven, recorded_at=instant, note=note
        )
        self._records[command_id] = record
        return record

    def mark_compensation_ambiguous(
        self,
        command_id: str,
        *,
        idempotent_effect_proven: bool,
        at: datetime,
        note: str = "compensation ambiguous timeout",
    ) -> ReconciliationRecord:
        instant = require_aware(at, field="at")
        record = ReconciliationRecord(
            command_id=command_id,
            status=OutcomeStatus.COMPENSATION_UNKNOWN,
            idempotent_effect_proven=idempotent_effect_proven,
            recorded_at=instant,
            note=note,
        )
        self._records[command_id] = record
        return record

    def resolve_with_evidence(self, command_id: str, *, effect_confirmed: bool, at: datetime) -> ReconciliationRecord:
        instant = require_aware(at, field="at")
        previous = self._require_record(command_id)
        if previous.status not in _RESOLVABLE_STATUSES:
            raise SafetyError("INVALID_RECONCILIATION_TRANSITION", f"cannot resolve from {previous.status.value}")
        if previous.status is OutcomeStatus.UNKNOWN:
            new_status = OutcomeStatus.CONFIRMED if effect_confirmed else OutcomeStatus.FAILED
        else:
            new_status = OutcomeStatus.COMPENSATED if effect_confirmed else OutcomeStatus.COMPENSATION_FAILED
        record = ReconciliationRecord(
            command_id=command_id,
            status=new_status,
            idempotent_effect_proven=previous.idempotent_effect_proven,
            recorded_at=instant,
            note="resolved by Evidence",
        )
        self._records[command_id] = record
        return record

    def escalate_if_deadline_passed(self, command_id: str, *, at: datetime, deadline: datetime) -> ReconciliationRecord:
        instant = require_aware(at, field="at")
        require_aware(deadline, field="deadline")
        previous = self._require_record(command_id)
        if previous.status not in _RESOLVABLE_STATUSES:
            raise SafetyError("INVALID_RECONCILIATION_TRANSITION", f"cannot escalate from {previous.status.value}")
        if instant < deadline:
            return previous
        new_status = OutcomeStatus.INDETERMINATE if previous.status is OutcomeStatus.UNKNOWN else OutcomeStatus.COMPENSATION_INDETERMINATE
        record = ReconciliationRecord(
            command_id=command_id,
            status=new_status,
            idempotent_effect_proven=previous.idempotent_effect_proven,
            recorded_at=instant,
            note="reconciliation deadline passed; adjudication opened",
        )
        self._records[command_id] = record
        return record

    def require_may_auto_retry(self, command_id: str) -> None:
        record = self._records.get(command_id)
        if record is None:
            return
        if record.status in _AMBIGUOUS_STATUSES and not record.idempotent_effect_proven:
            raise SafetyError(
                "AUTO_RETRY_BLOCKED_AMBIGUOUS_NON_IDEMPOTENT",
                f"{command_id!r} has an ambiguous, non-idempotent-proven outcome and cannot be auto-retried",
            )
