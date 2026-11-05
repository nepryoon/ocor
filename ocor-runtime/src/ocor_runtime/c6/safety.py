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
  OCOR-DEV-REM-0053 (NCR-C6-007; LLD v1.1 :282-293 and :307, ADD v1.3
  :2841, Register FR-163): a record is opened once and changes only
  from an ambiguous state, so a terminal outcome is never overwritten;
  resolution takes positive ``ReconciliationEvidence`` of the same
  command, never a flag; with the single ``AuditPort`` every record is
  appended to the signed, hash-linked chain before it takes effect and
  ``restore`` rebuilds the state from the verified chain.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Protocol

from ..audit import AuditError, AuditEvent, AuditPort, SealedAuditRecord, verify_audit_chain
from ..c2_identity import IdentityRecord, IdentityRegistry
from ..c3_store import require_aware
from ..errors import OCORError
from ..kernel.canonical import parse_utc_timestamp
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

    def request_reset(
        self, *, approvers: tuple[str, str], identities: IdentityRegistry, requester: str, at: datetime | None = None
    ) -> StopEvent:
        # No temporal window is specified for reset; its event timestamp comes
        # from the local boundary UTC clock, never the compatibility ``at``.
        from datetime import UTC

        from .human_gate import _active_human_roles

        instant = datetime.now(UTC)
        distinct = set(approvers)
        if len(approvers) != 2 or len(distinct) != 2 or not requester or requester in distinct:
            raise SafetyError("RESET_REQUIRES_DUAL_CONTROL", "reset requires two distinct human approvers, independent of the requester")
        with self._lock:
            if self._status is not StopStatus.STOPPED:
                raise SafetyError("INVALID_STOP_TRANSITION", f"cannot request reset from {self._status.value}")
            # Fresh authority reads immediately before the state transition.
            # Request, signature and grant cannot set registry attributes.
            for principal in distinct:
                if _active_human_roles(identities.get(principal)) is None:
                    raise SafetyError("RESET_REQUIRES_DUAL_CONTROL", "reset approver is not a resolved active human with valid attributes")
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
# The reconciliation transitions (LLD v1.1 :282-293, :296-297): a record is opened once, by an
# ambiguous timeout, and moves only from an ambiguous state; every other state is terminal.
_RECONCILIATION_TRANSITIONS: Mapping[OutcomeStatus | None, frozenset[OutcomeStatus]] = {
    None: frozenset({OutcomeStatus.UNKNOWN, OutcomeStatus.COMPENSATION_UNKNOWN}),
    OutcomeStatus.UNKNOWN: frozenset({OutcomeStatus.CONFIRMED, OutcomeStatus.FAILED, OutcomeStatus.INDETERMINATE}),
    OutcomeStatus.COMPENSATION_UNKNOWN: frozenset(
        {OutcomeStatus.COMPENSATED, OutcomeStatus.COMPENSATION_FAILED, OutcomeStatus.COMPENSATION_INDETERMINATE}
    ),
}
_RESOLUTIONS: Mapping[tuple[OutcomeStatus, str], OutcomeStatus] = {
    (OutcomeStatus.UNKNOWN, "EFFECT_OBSERVED"): OutcomeStatus.CONFIRMED,
    (OutcomeStatus.UNKNOWN, "NO_EFFECT_OBSERVED"): OutcomeStatus.FAILED,
    (OutcomeStatus.COMPENSATION_UNKNOWN, "EFFECT_OBSERVED"): OutcomeStatus.COMPENSATED,
    (OutcomeStatus.COMPENSATION_UNKNOWN, "NO_EFFECT_OBSERVED"): OutcomeStatus.COMPENSATION_FAILED,
}
EVIDENCE_FINDINGS = frozenset({"EFFECT_OBSERVED", "NO_EFFECT_OBSERVED"})
RECONCILIATION_EVENT = "C6_RECONCILIATION"
RECONCILIATION_ACTOR = "urn:ocor:c6:outcome-reconciler"
_NO_EVIDENCE_AUTHORITY = "urn:ocor:c6:reconciliation"
_SHA256_URN = re.compile(r"urn:sha256:[0-9a-f]{64}")
_DETAIL_FIELDS = frozenset({"status", "previous_status", "idempotent_effect_proven", "note", "evidence_ref", "evidence_digest"})


def _evidence_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SafetyError("EVIDENCE_INVALID", f"evidence {name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class ReconciliationEvidence:
    """Positive Evidence observed for one command: of its effect (``EFFECT_OBSERVED``) or of
    no effect/failure (``NO_EFFECT_OBSERVED``), LLD v1.1 :285-286 and :291-292. The only
    input that resolves an ambiguous outcome: the absence of a response is never Evidence
    (ADD v1.3 :2841)."""

    evidence_ref: str
    command_id: str
    finding: str
    observed_at: datetime
    content_digest: str

    def __post_init__(self) -> None:
        _evidence_text("evidence_ref", self.evidence_ref)
        _evidence_text("command_id", self.command_id)
        if not isinstance(self.finding, str) or self.finding not in EVIDENCE_FINDINGS:
            raise SafetyError("EVIDENCE_INVALID", "the evidence finding is outside the closed set")
        if not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise SafetyError("EVIDENCE_INVALID", "the evidence observation time must be timezone-aware")
        if not isinstance(self.content_digest, str) or _SHA256_URN.fullmatch(self.content_digest) is None:
            raise SafetyError("EVIDENCE_INVALID", "the evidence content digest is not a SHA-256 URN")


@dataclass(frozen=True, slots=True)
class ReconciliationRecord:
    command_id: str
    status: OutcomeStatus
    idempotent_effect_proven: bool
    recorded_at: datetime
    note: str
    evidence_ref: str | None = None
    evidence_digest: str | None = None


class OutcomeReconciler:
    """The reconciliation of ambiguous outcomes (LLD v1.1 ``ACT-T18a``/``T18b``/``T20a``-``c``,
    ``T21c``-``T21e``, ``T24``, ``T25``; Register FR-163 :407).

    A record is opened once, by an ambiguous timeout, and changes only from an ambiguous state:
    a terminal outcome is never overwritten and an open reconciliation is never reopened
    (``INVALID_RECONCILIATION_TRANSITION``). Resolution takes positive ``ReconciliationEvidence``
    of the same command, never a flag. With an ``AuditPort`` every record is appended to the
    single signed, hash-linked audit chain before it takes effect -- an append that fails leaves
    the state unchanged (``RECONCILIATION_UNAVAILABLE``) -- and ``restore`` rebuilds the state
    from the verified chain."""

    def __init__(self, *, audit: AuditPort | None = None, actor: str = RECONCILIATION_ACTOR) -> None:
        if audit is not None and not isinstance(audit, AuditPort):
            raise TypeError("audit must implement the AuditPort")
        if not isinstance(actor, str) or not actor:
            raise TypeError("actor must be a non-empty string")
        self._audit = audit
        self._actor = actor
        self._records: dict[str, ReconciliationRecord] = {}
        self._lock = threading.RLock()

    @property
    def audited(self) -> bool:
        """Whether every record is appended to the audit port before it takes effect."""
        return self._audit is not None

    @property
    def records(self) -> tuple[ReconciliationRecord, ...]:
        with self._lock:
            return tuple(self._records.values())

    def status(self, command_id: str) -> OutcomeStatus:
        return self._require_record(command_id).status

    def record(self, command_id: str) -> ReconciliationRecord | None:
        """The current reconciliation record of ``command_id``, if one was opened."""
        with self._lock:
            return self._records.get(command_id)

    def _require_record(self, command_id: str) -> ReconciliationRecord:
        with self._lock:
            record = self._records.get(command_id)
        if record is None:
            raise SafetyError("UNKNOWN_COMMAND", f"no reconciliation record for {command_id!r}")
        return record

    def _commit(self, record: ReconciliationRecord, previous: ReconciliationRecord | None) -> ReconciliationRecord:
        """Append ``record`` to the audit chain, then make it current (caller holds the lock)."""
        if record.status not in _RECONCILIATION_TRANSITIONS.get(None if previous is None else previous.status, frozenset()):
            source = "no record" if previous is None else previous.status.value
            raise SafetyError(
                "INVALID_RECONCILIATION_TRANSITION",
                f"{record.command_id!r}: {source} -> {record.status.value} is not a reconciliation transition",
            )
        if self._audit is not None:
            detail: dict[str, Any] = {
                "status": record.status.value,
                "previous_status": None if previous is None else previous.status.value,
                "idempotent_effect_proven": record.idempotent_effect_proven,
                "note": record.note,
                "evidence_ref": record.evidence_ref,
                "evidence_digest": record.evidence_digest,
            }
            try:
                self._audit.append(
                    AuditEvent(
                        event_type=RECONCILIATION_EVENT,
                        actor=self._actor,
                        occurred_at=record.recorded_at,
                        resource=record.command_id,
                        reason_code=record.status.value,
                        authority_ref=record.evidence_ref or _NO_EVIDENCE_AUTHORITY,
                        correlation_id=record.command_id,
                        outcome="PERMITTED",
                        detail=detail,
                    )
                )
            except AuditError as error:
                raise SafetyError(
                    "RECONCILIATION_UNAVAILABLE",
                    f"the reconciliation record of {record.command_id!r} could not be audited: {error.reason_code}",
                ) from error
            except Exception as error:
                raise SafetyError(
                    "RECONCILIATION_UNAVAILABLE",
                    f"the reconciliation record of {record.command_id!r} could not be audited: {type(error).__name__}",
                ) from error
        self._records[record.command_id] = record
        return record

    def _open(
        self, command_id: str, status: OutcomeStatus, *, idempotent_effect_proven: bool, at: datetime, note: str
    ) -> ReconciliationRecord:
        instant = require_aware(at, field="at")
        if not isinstance(command_id, str) or not command_id:
            raise SafetyError("RECONCILIATION_RECORD_INVALID", "command_id must be a non-empty string")
        if not isinstance(idempotent_effect_proven, bool):
            raise SafetyError("RECONCILIATION_RECORD_INVALID", "idempotent_effect_proven must be a boolean")
        if not isinstance(note, str):
            raise SafetyError("RECONCILIATION_RECORD_INVALID", "note must be a string")
        record = ReconciliationRecord(
            command_id=command_id,
            status=status,
            idempotent_effect_proven=idempotent_effect_proven,
            recorded_at=instant,
            note=note,
        )
        with self._lock:
            return self._commit(record, self._records.get(command_id))

    def mark_ambiguous(
        self, command_id: str, *, idempotent_effect_proven: bool, at: datetime, note: str = "ambiguous timeout"
    ) -> ReconciliationRecord:
        """``ACT-T18a``/``T18b``: an ambiguous timeout gives ``EXECUTION_UNKNOWN``."""
        return self._open(
            command_id, OutcomeStatus.UNKNOWN, idempotent_effect_proven=idempotent_effect_proven, at=at, note=note
        )

    def mark_compensation_ambiguous(
        self,
        command_id: str,
        *,
        idempotent_effect_proven: bool,
        at: datetime,
        note: str = "compensation ambiguous timeout",
    ) -> ReconciliationRecord:
        """``ACT-T21c``: an ambiguous compensation timeout gives ``COMPENSATION_UNKNOWN``."""
        return self._open(
            command_id,
            OutcomeStatus.COMPENSATION_UNKNOWN,
            idempotent_effect_proven=idempotent_effect_proven,
            at=at,
            note=note,
        )

    def resolve_with_evidence(
        self, command_id: str, *, evidence: ReconciliationEvidence, at: datetime
    ) -> ReconciliationRecord:
        """``ACT-T20a``/``T20b``/``T21d``/``T21e``: positive Evidence of the same command resolves
        an ambiguous outcome to confirmed/failed (compensated/compensation failed)."""
        instant = require_aware(at, field="at")
        with self._lock:
            previous = self._require_record(command_id)
            if previous.status not in _RESOLVABLE_STATUSES:
                raise SafetyError("INVALID_RECONCILIATION_TRANSITION", f"cannot resolve from {previous.status.value}")
            if not isinstance(evidence, ReconciliationEvidence):
                raise SafetyError("EVIDENCE_REQUIRED", "only positive Evidence of the command resolves an ambiguous outcome")
            if evidence.command_id != command_id:
                raise SafetyError("EVIDENCE_MISMATCH", f"the evidence is about {evidence.command_id!r}, not {command_id!r}")
            if evidence.observed_at > instant:
                raise SafetyError("EVIDENCE_INVALID", "the evidence was observed after the resolution time")
            record = ReconciliationRecord(
                command_id=command_id,
                status=_RESOLUTIONS[(previous.status, evidence.finding)],
                idempotent_effect_proven=previous.idempotent_effect_proven,
                recorded_at=instant,
                note="resolved by Evidence",
                evidence_ref=evidence.evidence_ref,
                evidence_digest=evidence.content_digest,
            )
            return self._commit(record, previous)

    def escalate_if_deadline_passed(self, command_id: str, *, at: datetime, deadline: datetime) -> ReconciliationRecord:
        """``ACT-T20c``/``T24``/``T25``: before the deadline nothing is inferred; after it the
        outcome is escalated to adjudication, never resolved."""
        instant = require_aware(at, field="at")
        require_aware(deadline, field="deadline")
        with self._lock:
            previous = self._require_record(command_id)
            if previous.status not in _RESOLVABLE_STATUSES:
                raise SafetyError("INVALID_RECONCILIATION_TRANSITION", f"cannot escalate from {previous.status.value}")
            if instant < deadline:
                return previous
            new_status = (
                OutcomeStatus.INDETERMINATE if previous.status is OutcomeStatus.UNKNOWN else OutcomeStatus.COMPENSATION_INDETERMINATE
            )
            record = ReconciliationRecord(
                command_id=command_id,
                status=new_status,
                idempotent_effect_proven=previous.idempotent_effect_proven,
                recorded_at=instant,
                note="reconciliation deadline passed; adjudication opened",
            )
            return self._commit(record, previous)

    def require_may_auto_retry(self, command_id: str) -> None:
        with self._lock:
            record = self._records.get(command_id)
        if record is None:
            return
        if record.status in _AMBIGUOUS_STATUSES and not record.idempotent_effect_proven:
            raise SafetyError(
                "AUTO_RETRY_BLOCKED_AMBIGUOUS_NON_IDEMPOTENT",
                f"{command_id!r} has an ambiguous, non-idempotent-proven outcome and cannot be auto-retried",
            )

    @classmethod
    def restore(
        cls,
        records: Iterable[SealedAuditRecord],
        *,
        audit: AuditPort,
        public_keys: Mapping[str, bytes],
        actor: str = RECONCILIATION_ACTOR,
    ) -> OutcomeReconciler:
        """Rebuild the reconciliation state from the audit chain read back from storage: the
        chain is verified from genesis (links and signatures), every reconciliation record is
        checked without conversion and replayed through the same transitions. Anything else is
        ``RECONCILIATION_AUDIT_INVALID``."""
        chain = list(records)
        try:
            verify_audit_chain(chain, public_keys)
        except AuditError as error:
            raise SafetyError("RECONCILIATION_AUDIT_INVALID", f"the audit chain does not verify: {error.reason_code}") from error
        restored = cls(audit=audit, actor=actor)
        with restored._lock:
            for sealed in chain:
                if sealed.record.get("event_type") != RECONCILIATION_EVENT:
                    continue
                record = _restored_record(sealed)
                previous = restored._records.get(record.command_id)
                if record.status not in _RECONCILIATION_TRANSITIONS.get(None if previous is None else previous.status, frozenset()):
                    raise SafetyError(
                        "RECONCILIATION_AUDIT_INVALID", f"record {sealed.sequence} is not a reconciliation transition"
                    )
                restored._records[record.command_id] = record
        return restored


def _restored_record(sealed: SealedAuditRecord) -> ReconciliationRecord:
    def invalid(message: str) -> SafetyError:
        return SafetyError("RECONCILIATION_AUDIT_INVALID", f"record {sealed.sequence}: {message}")

    stored = sealed.record
    detail = stored.get("detail")
    if not isinstance(detail, Mapping) or set(detail) != _DETAIL_FIELDS:
        raise invalid("the reconciliation detail does not have its fields")
    status_value, command_id = detail["status"], stored.get("resource")
    if not isinstance(status_value, str) or status_value not in {item.value for item in OutcomeStatus}:
        raise invalid("the status is outside the closed set")
    if stored.get("reason_code") != status_value or not isinstance(command_id, str) or not command_id:
        raise invalid("the status or the command does not match the record")
    if not isinstance(detail["idempotent_effect_proven"], bool) or not isinstance(detail["note"], str):
        raise invalid("the idempotency proof or the note is malformed")
    status = OutcomeStatus(status_value)
    evidence_ref, evidence_digest = detail["evidence_ref"], detail["evidence_digest"]
    resolved = status in {OutcomeStatus.CONFIRMED, OutcomeStatus.FAILED, OutcomeStatus.COMPENSATED, OutcomeStatus.COMPENSATION_FAILED}
    if resolved:
        if not isinstance(evidence_ref, str) or not evidence_ref or stored.get("authority_ref") != evidence_ref:
            raise invalid("a resolution without its Evidence reference")
        if not isinstance(evidence_digest, str) or _SHA256_URN.fullmatch(evidence_digest) is None:
            raise invalid("a resolution without its Evidence digest")
    elif evidence_ref is not None or evidence_digest is not None:
        raise invalid("Evidence on a record that is not a resolution")
    occurred_at = stored.get("occurred_at")
    if not isinstance(occurred_at, str):
        raise invalid("the record time is malformed")
    try:
        recorded_at = parse_utc_timestamp(occurred_at)
    except Exception as error:
        raise invalid("the record time is malformed") from error
    return ReconciliationRecord(
        command_id=command_id,
        status=status,
        idempotent_effect_proven=detail["idempotent_effect_proven"],
        recorded_at=recorded_at,
        note=detail["note"],
        evidence_ref=evidence_ref,
        evidence_digest=evidence_digest,
    )
