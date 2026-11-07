"""Fail-closed Authority, capability lease, evidence and provenance kernel."""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import ClassVar, Protocol

from .canonical import (
    IdentifierError,
    canonical_digest,
    format_utc_timestamp,
    parse_utc_timestamp,
    validate_causation_id,
    validate_correlation_id,
)
from .governed_context import GovernedContext

DIGEST_PREFIX = "urn:sha256:"
# Used only when a malformed record is rejected before it supplies a correlation ID.
CORRELATION_ZERO = "00000000-0000-4000-8000-000000000001"


class FailureClass(StrEnum):
    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"
    POLICY_DENIED = "POLICY_DENIED"
    POISON = "POISON"


_REASON_FAILURE_CLASSES = MappingProxyType(
    {
        "AUTHORITY_BINDING_MISMATCH": FailureClass.POLICY_DENIED,
        "AUTHORITY_EXPIRED": FailureClass.POLICY_DENIED,
        "AUTHORITY_NOT_YET_VALID": FailureClass.POLICY_DENIED,
        "AUTHORITY_REVOKED": FailureClass.POLICY_DENIED,
        "AUTHORITY_SCOPE_MISMATCH": FailureClass.POLICY_DENIED,
        "AUTHORITY_UNSIGNED": FailureClass.PERMANENT,
        "CONTROL_PLANE_UNAVAILABLE": FailureClass.PERMANENT,
        "EVIDENCE_INVALID": FailureClass.PERMANENT,
        "FENCING_TOKEN_STALE": FailureClass.POLICY_DENIED,
        "GOVERNANCE_RECORD_INVALID": FailureClass.PERMANENT,
        "LEASE_ALREADY_CONSUMED": FailureClass.POLICY_DENIED,
        "LEASE_CONTEXT_MISMATCH": FailureClass.POLICY_DENIED,
        "LEASE_EXPIRED": FailureClass.POLICY_DENIED,
        "LEASE_INVALID": FailureClass.PERMANENT,
        "LEASE_REVOKED": FailureClass.POLICY_DENIED,
        "POISON_EVENT": FailureClass.POISON,
        "POLICY_DENIED": FailureClass.POLICY_DENIED,
        "PROJECTION_NOT_READY": FailureClass.TRANSIENT,
        "PROVENANCE_INCOMPLETE": FailureClass.PERMANENT,
        "STALE_CONTEXT": FailureClass.TRANSIENT,
        "STOP_EPOCH_MISMATCH": FailureClass.POLICY_DENIED,
    }
)


class RiskClass(IntEnum):
    """The risk classes of ADD v1.3 §5.4 (:3300-3305) and of the Action Type Contract ``risk_class``
    enum (:2193), in impact order. ADD v1.3 prevails over the LLD v1.1 §4.1 names (LLD v1.1 :16-18,
    OCOR-DEV-REM-0054, NCR-C6-013); no alias of another name exists."""

    R0_READ = 0
    R1_ANALYZE = 1
    R2_CONTROLLED = 2
    R3_HIGH_IMPACT = 3


class GovernanceFault(RuntimeError):
    """Typed boundary failure with bounded, non-secret problem output."""

    def __init__(
        self,
        reason_code: str,
        failure_class: FailureClass,
        correlation_id: str,
        title: str,
        *,
        causation_id: str | None = None,
    ) -> None:
        declared_class = _REASON_FAILURE_CLASSES.get(reason_code)
        if declared_class is None:
            raise ValueError(f"undeclared governance reason: {reason_code!r}")
        try:
            actual_class = FailureClass(failure_class)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid governance failure class") from exc
        if actual_class is not declared_class:
            raise ValueError(
                f"{reason_code} requires failure class {declared_class.value}"
            )
        if (
            not isinstance(title, str)
            or not title
            or len(title.encode("utf-8")) > 256
            or any(ord(character) < 32 for character in title)
        ):
            raise ValueError("a non-control, UTF-8 title of at most 256 bytes is required")
        validate_correlation_id(correlation_id)
        if causation_id is not None:
            validate_causation_id(causation_id)
        self.reason_code = reason_code
        self.failure_class = actual_class
        self.correlation_id = correlation_id
        self.causation_id = causation_id
        self.title = title
        super().__init__(f"{reason_code}: {title}")

    @property
    def retryable(self) -> bool:
        return self.failure_class is FailureClass.TRANSIENT

    def to_problem(self) -> dict[str, object]:
        return {
            "reason_code": self.reason_code,
            "failure_class": self.failure_class.value,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "retryable": self.retryable,
            "title": self.title,
        }


def _fault(
    reason: str,
    correlation_id: str,
    title: str,
    *,
    causation_id: str | None = None,
) -> GovernanceFault:
    failure_class = _REASON_FAILURE_CLASSES.get(reason)
    if failure_class is None:
        raise ValueError(f"undeclared governance reason: {reason!r}")
    return GovernanceFault(
        reason,
        failure_class,
        correlation_id,
        title,
        causation_id=causation_id,
    )


def _string(field: str, value: object, correlation_id: str = CORRELATION_ZERO) -> str:
    if not isinstance(value, str) or not value:
        raise _fault("GOVERNANCE_RECORD_INVALID", correlation_id, f"{field} is required")
    return value


def _digest(field: str, value: object, correlation_id: str = CORRELATION_ZERO) -> str:
    result = _string(field, value, correlation_id)
    if len(result) != 75 or not result.startswith(DIGEST_PREFIX):
        raise _fault(
            "GOVERNANCE_RECORD_INVALID", correlation_id, f"{field} is not a SHA-256 URN"
        )
    suffix = result.removeprefix(DIGEST_PREFIX)
    if any(character not in "0123456789abcdef" for character in suffix):
        raise _fault(
            "GOVERNANCE_RECORD_INVALID", correlation_id, f"{field} is not a SHA-256 URN"
        )
    return result


def _aware(field: str, value: datetime, correlation_id: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _fault("GOVERNANCE_RECORD_INVALID", correlation_id, f"{field} must be aware UTC")
    return value


def _refs(field: str, value: Sequence[str], correlation_id: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)):
        raise _fault("PROVENANCE_INCOMPLETE", correlation_id, f"{field} must be an array")
    items = tuple(value)
    if not items or any(not isinstance(item, str) or not item for item in items):
        raise _fault("PROVENANCE_INCOMPLETE", correlation_id, f"{field} is incomplete")
    if len(items) != len(set(items)):
        raise _fault("PROVENANCE_INCOMPLETE", correlation_id, f"{field} has duplicates")
    return items


@dataclass(frozen=True, slots=True)
class Authority:
    authority_id: str
    effective_principal_id: str
    capability_ids: tuple[str, ...]
    resource_scopes: tuple[str, ...]
    tenant_id: str
    domains: tuple[str, ...]
    compartments: tuple[str, ...]
    permitted_purposes: tuple[str, ...]
    risk_ceiling: RiskClass
    not_before: datetime
    expires_at: datetime
    delegation_ref: str
    policy_bundle_digest: str
    signature_ref: str

    def __post_init__(self) -> None:
        correlation = CORRELATION_ZERO
        for field in (
            "authority_id",
            "effective_principal_id",
            "tenant_id",
            "signature_ref",
        ):
            _string(field, getattr(self, field), correlation)
        for field in (
            "capability_ids",
            "resource_scopes",
            "domains",
            "compartments",
            "permitted_purposes",
        ):
            object.__setattr__(self, field, _refs(field, getattr(self, field), correlation))
        _digest("delegation_ref", self.delegation_ref, correlation)
        _digest("policy_bundle_digest", self.policy_bundle_digest, correlation)
        object.__setattr__(self, "risk_ceiling", RiskClass(self.risk_ceiling))
        _aware("not_before", self.not_before, correlation)
        _aware("expires_at", self.expires_at, correlation)
        if self.not_before >= self.expires_at:
            raise _fault(
                "GOVERNANCE_RECORD_INVALID",
                correlation,
                "Authority validity window is empty",
            )


@dataclass(frozen=True, slots=True)
class AuthorityRequest:
    capability_id: str
    resource_scope: str
    risk_class: RiskClass
    governed_context: GovernedContext
    at: datetime
    causation_id: str | None = None

    def __post_init__(self) -> None:
        correlation = self.governed_context.correlation_id
        _string("capability_id", self.capability_id, correlation)
        _string("resource_scope", self.resource_scope, correlation)
        object.__setattr__(self, "risk_class", RiskClass(self.risk_class))
        _aware("at", self.at, correlation)
        if self.causation_id is not None:
            try:
                validate_causation_id(self.causation_id)
            except IdentifierError as exc:
                raise _fault(
                    "GOVERNANCE_RECORD_INVALID",
                    correlation,
                    f"invalid causation_id: {exc}",
                ) from exc


@dataclass(frozen=True, slots=True)
class VerifiedAuthorityBinding:
    """Trusted identity/delegation admission result for Authority evaluation."""

    binding_ref: str
    delegation_ref: str
    expected_context: GovernedContext

    def __post_init__(self) -> None:
        _string("binding_ref", self.binding_ref)
        _digest("delegation_ref", self.delegation_ref)
        if not isinstance(self.expected_context, GovernedContext):
            raise _fault(
                "GOVERNANCE_RECORD_INVALID",
                CORRELATION_ZERO,
                "verified Authority binding requires a GovernedContext",
            )


@dataclass(frozen=True, slots=True)
class AuthorityDecision:
    authority_id: str
    governed_context_digest: str
    purpose: str
    valid_until: datetime


def validate_authority(
    authority: Authority,
    request: AuthorityRequest,
    *,
    signature_verified: bool,
    revoked: bool,
    verified_binding: VerifiedAuthorityBinding | None = None,
) -> AuthorityDecision:
    """Apply the effective Authority intersection without wildcard widening."""

    correlation = request.governed_context.correlation_id
    causation = request.causation_id
    if not signature_verified or not authority.signature_ref:
        raise _fault(
            "AUTHORITY_UNSIGNED",
            correlation,
            "Authority signature is not verified",
            causation_id=causation,
        )
    if revoked:
        raise _fault(
            "AUTHORITY_REVOKED",
            correlation,
            "Authority is revoked",
            causation_id=causation,
        )
    context = request.governed_context
    if (
        not isinstance(verified_binding, VerifiedAuthorityBinding)
        or authority.delegation_ref != verified_binding.delegation_ref
        or context != verified_binding.expected_context
        or context.actor_chain != verified_binding.expected_context.actor_chain
    ):
        raise _fault(
            "AUTHORITY_BINDING_MISMATCH",
            correlation,
            "Authority delegation or verified GovernedContext binding differs",
            causation_id=causation,
        )
    if request.at < authority.not_before:
        raise _fault(
            "AUTHORITY_NOT_YET_VALID",
            correlation,
            "Authority is not yet valid",
            causation_id=causation,
        )
    if request.at >= authority.expires_at:
        raise _fault(
            "AUTHORITY_EXPIRED",
            correlation,
            "Authority is expired",
            causation_id=causation,
        )
    in_scope = (
        context.effective_principal_id == authority.effective_principal_id
        and request.capability_id in authority.capability_ids
        and request.resource_scope in authority.resource_scopes
        and context.tenant_id == authority.tenant_id
        and context.domain_id in authority.domains
        and set(context.compartments).issubset(authority.compartments)
        and context.purpose in authority.permitted_purposes
        and request.risk_class <= authority.risk_ceiling
        and context.policy_bundle_digest == authority.policy_bundle_digest
    )
    if not in_scope:
        raise _fault(
            "AUTHORITY_SCOPE_MISMATCH",
            correlation,
            "Authority does not contain the requested scope, purpose, risk, or binding",
            causation_id=causation,
        )
    return AuthorityDecision(
        authority_id=authority.authority_id,
        governed_context_digest=context.digest(),
        purpose=context.purpose,
        valid_until=authority.expires_at,
    )


@dataclass(frozen=True, slots=True)
class CapabilityLease:
    lease_id: str
    capability_id: str
    effective_principal_id: str
    delegation_ref: str
    action_instance_id: str
    governed_context_digest: str
    gate_package_digest: str
    stop_epoch: int
    fencing_token: int
    issued_at: datetime
    expires_at: datetime

    fields: ClassVar[tuple[str, ...]] = (
        "lease_id",
        "capability_id",
        "effective_principal_id",
        "delegation_ref",
        "action_instance_id",
        "governed_context_digest",
        "gate_package_digest",
        "stop_epoch",
        "fencing_token",
        "issued_at",
        "expires_at",
    )

    def __post_init__(self) -> None:
        for field in (
            "lease_id",
            "capability_id",
            "effective_principal_id",
            "action_instance_id",
        ):
            _string(field, getattr(self, field))
        for field in (
            "delegation_ref",
            "governed_context_digest",
            "gate_package_digest",
        ):
            _digest(field, getattr(self, field))
        if (
            isinstance(self.stop_epoch, bool)
            or not isinstance(self.stop_epoch, int)
            or self.stop_epoch < 0
        ):
            raise _fault("LEASE_INVALID", CORRELATION_ZERO, "stop_epoch is invalid")
        if (
            isinstance(self.fencing_token, bool)
            or not isinstance(self.fencing_token, int)
            or self.fencing_token < 1
        ):
            raise _fault("LEASE_INVALID", CORRELATION_ZERO, "fencing_token is invalid")
        _aware("issued_at", self.issued_at, CORRELATION_ZERO)
        _aware("expires_at", self.expires_at, CORRELATION_ZERO)
        duration = self.expires_at - self.issued_at
        if duration <= timedelta(0):
            raise _fault("LEASE_INVALID", CORRELATION_ZERO, "lease validity window is empty")
        if duration > timedelta(seconds=5):
            raise _fault("LEASE_INVALID", CORRELATION_ZERO, "lease TTL exceeds five seconds")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CapabilityLease:
        present = frozenset(value)
        required = frozenset(cls.fields)
        missing = sorted(required - present)
        additional = sorted(present - required)
        if missing:
            raise _fault(
                "LEASE_INVALID",
                CORRELATION_ZERO,
                f"missing lease fields: {', '.join(missing)}",
            )
        if additional:
            raise _fault(
                "LEASE_INVALID",
                CORRELATION_ZERO,
                f"additional lease fields: {', '.join(additional)}",
            )
        try:
            issued_at = parse_utc_timestamp(value["issued_at"])  # type: ignore[arg-type]
            expires_at = parse_utc_timestamp(value["expires_at"])  # type: ignore[arg-type]
            return cls(
                lease_id=value["lease_id"],  # type: ignore[arg-type]
                capability_id=value["capability_id"],  # type: ignore[arg-type]
                effective_principal_id=value["effective_principal_id"],  # type: ignore[arg-type]
                delegation_ref=value["delegation_ref"],  # type: ignore[arg-type]
                action_instance_id=value["action_instance_id"],  # type: ignore[arg-type]
                governed_context_digest=value["governed_context_digest"],  # type: ignore[arg-type]
                gate_package_digest=value["gate_package_digest"],  # type: ignore[arg-type]
                stop_epoch=value["stop_epoch"],  # type: ignore[arg-type]
                fencing_token=value["fencing_token"],  # type: ignore[arg-type]
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, GovernanceFault):
                raise
            raise _fault("LEASE_INVALID", CORRELATION_ZERO, f"invalid lease: {exc}") from exc

    def to_mapping(self) -> dict[str, object]:
        return {
            "lease_id": self.lease_id,
            "capability_id": self.capability_id,
            "effective_principal_id": self.effective_principal_id,
            "delegation_ref": self.delegation_ref,
            "action_instance_id": self.action_instance_id,
            "governed_context_digest": self.governed_context_digest,
            "gate_package_digest": self.gate_package_digest,
            "stop_epoch": self.stop_epoch,
            "fencing_token": self.fencing_token,
            "issued_at": format_utc_timestamp(self.issued_at),
            "expires_at": format_utc_timestamp(self.expires_at),
        }


@dataclass(frozen=True, slots=True)
class LeaseExpectation:
    """Expected call binding; ``at`` is observable metadata, never trusted time."""

    capability_id: str
    effective_principal_id: str
    delegation_ref: str
    action_instance_id: str
    governed_context_digest: str
    gate_package_digest: str
    stop_epoch: int
    fencing_token: int
    emission_attempt: int
    at: datetime
    correlation_id: str = CORRELATION_ZERO
    causation_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("capability_id", "effective_principal_id", "action_instance_id"):
            _string(field, getattr(self, field))
        for field in ("delegation_ref", "governed_context_digest", "gate_package_digest"):
            _digest(field, getattr(self, field))
        counters = (self.stop_epoch, self.fencing_token, self.emission_attempt)
        if any(isinstance(counter, bool) or not isinstance(counter, int) for counter in counters) or (
            self.stop_epoch < 0 or self.fencing_token < 1 or self.emission_attempt < 1
        ):
            raise _fault("LEASE_INVALID", CORRELATION_ZERO, "lease expectation counters invalid")
        _aware("at", self.at, CORRELATION_ZERO)
        try:
            validate_correlation_id(self.correlation_id)
            if self.causation_id is not None:
                validate_causation_id(self.causation_id)
        except IdentifierError as exc:
            raise _fault(
                "LEASE_INVALID",
                CORRELATION_ZERO,
                f"lease observability binding invalid: {exc}",
            ) from exc


@dataclass(frozen=True, slots=True)
class LeaseConsumptionReceipt:
    consumption_key: tuple[str, str, int]
    governed_context_digest: str
    consumed_at: datetime


class TrustedClock(Protocol):
    """Clock port whose implementation, rather than the request, owns current time."""

    def now(self) -> datetime:
        """Return the authoritative current instant."""


class InMemoryTrustedClock:
    """Thread-safe controllable clock for bounded runtime and fault tests."""

    def __init__(self, current: datetime) -> None:
        self._current = _aware("current", current, CORRELATION_ZERO)
        self._lock = threading.RLock()

    def now(self) -> datetime:
        with self._lock:
            return self._current

    def advance(self, delta: timedelta) -> datetime:
        if not isinstance(delta, timedelta) or delta < timedelta(0):
            raise ValueError("clock delta must be a non-negative timedelta")
        with self._lock:
            self._current += delta
            return self._current


class LeaseStateOutcome(StrEnum):
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    STOP_EPOCH_MISMATCH = "STOP_EPOCH_MISMATCH"
    FENCING_TOKEN_STALE = "FENCING_TOKEN_STALE"
    ALREADY_CONSUMED = "ALREADY_CONSUMED"
    CONTROL_PLANE_UNAVAILABLE = "CONTROL_PLANE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class LeaseStateDecision:
    """Result of the single atomic validity-and-consumption boundary."""

    outcome: LeaseStateOutcome
    evaluated_at: datetime | None


class LeaseStatePort(Protocol):
    """Atomic authoritative state and consumption port for a mutative call."""

    def consume_if_current(
        self,
        *,
        clock: TrustedClock,
        lease_id: str,
        action_instance_id: str,
        stop_epoch: int,
        fencing_token: int,
        emission_attempt: int,
        issued_at: datetime,
        expires_at: datetime,
    ) -> LeaseStateDecision:
        """Atomically evaluate time/live state and consume the lease at most once."""


class InMemoryLeaseState:
    """Lock-backed authoritative adapter; durable integration remains external."""

    def __init__(
        self,
        *,
        stop_epoch: int,
        fencing_tokens: Mapping[str, int],
        revoked_lease_ids: Sequence[str] = (),
    ) -> None:
        if isinstance(stop_epoch, bool) or not isinstance(stop_epoch, int) or stop_epoch < 0:
            raise ValueError("stop_epoch must be a non-negative integer")
        tokens = dict(fencing_tokens)
        if any(
            not isinstance(action_id, str)
            or not action_id
            or isinstance(token, bool)
            or not isinstance(token, int)
            or token < 1
            for action_id, token in tokens.items()
        ):
            raise ValueError("fencing tokens require action ids and positive integers")
        if isinstance(revoked_lease_ids, (str, bytes, bytearray)) or any(
            not isinstance(lease_id, str) or not lease_id
            for lease_id in revoked_lease_ids
        ):
            raise ValueError("revoked lease ids must be a sequence of non-empty strings")
        self._stop_epoch = stop_epoch
        self._fencing_tokens = tokens
        self._revoked = set(revoked_lease_ids)
        self._consumed: dict[str, tuple[str, int]] = {}
        self._lock = threading.RLock()

    def set_stop_epoch(self, stop_epoch: int) -> None:
        if isinstance(stop_epoch, bool) or not isinstance(stop_epoch, int):
            raise TypeError("stop_epoch must be an integer")
        with self._lock:
            if stop_epoch < self._stop_epoch:
                raise ValueError("stop_epoch cannot move backwards")
            self._stop_epoch = stop_epoch

    def set_fencing_token(self, action_instance_id: str, fencing_token: int) -> None:
        if (
            not isinstance(action_instance_id, str)
            or not action_instance_id
            or isinstance(fencing_token, bool)
            or not isinstance(fencing_token, int)
            or fencing_token < 1
        ):
            raise ValueError("a valid action id and positive fencing token are required")
        with self._lock:
            current = self._fencing_tokens.get(action_instance_id)
            if current is not None and fencing_token < current:
                raise ValueError("fencing token cannot move backwards")
            self._fencing_tokens[action_instance_id] = fencing_token

    def revoke(self, lease_id: str) -> None:
        if not isinstance(lease_id, str) or not lease_id:
            raise ValueError("lease_id must be non-empty")
        with self._lock:
            self._revoked.add(lease_id)

    def consume_if_current(
        self,
        *,
        clock: TrustedClock,
        lease_id: str,
        action_instance_id: str,
        stop_epoch: int,
        fencing_token: int,
        emission_attempt: int,
        issued_at: datetime,
        expires_at: datetime,
    ) -> LeaseStateDecision:
        with self._lock:
            try:
                now = _aware("authoritative now", clock.now(), CORRELATION_ZERO)
            except (
                AttributeError,
                GovernanceFault,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ):
                return LeaseStateDecision(
                    LeaseStateOutcome.CONTROL_PLANE_UNAVAILABLE, None
                )
            if now < issued_at or now >= expires_at:
                return LeaseStateDecision(LeaseStateOutcome.EXPIRED, now)
            if lease_id in self._revoked:
                return LeaseStateDecision(LeaseStateOutcome.REVOKED, now)
            if stop_epoch != self._stop_epoch:
                return LeaseStateDecision(LeaseStateOutcome.STOP_EPOCH_MISMATCH, now)
            if fencing_token != self._fencing_tokens.get(action_instance_id):
                return LeaseStateDecision(LeaseStateOutcome.FENCING_TOKEN_STALE, now)
            if lease_id in self._consumed:
                return LeaseStateDecision(LeaseStateOutcome.ALREADY_CONSUMED, now)
            self._consumed[lease_id] = (action_instance_id, emission_attempt)
            return LeaseStateDecision(LeaseStateOutcome.CONSUMED, now)

    def consumption(self, lease_id: str) -> tuple[str, int] | None:
        with self._lock:
            return self._consumed.get(lease_id)


class LeaseConsumptionLedger:
    """One-shot validator over injected clock and authoritative state ports."""

    def __init__(
        self,
        *,
        clock: TrustedClock | None = None,
        state: LeaseStatePort | None = None,
    ) -> None:
        self._clock = clock
        self._state = state

    def consume(
        self,
        lease: CapabilityLease,
        expected: LeaseExpectation,
        *,
        signature_verified: bool,
        revoked: bool | None = None,
    ) -> LeaseConsumptionReceipt:
        correlation = expected.correlation_id
        causation = expected.causation_id

        def fault(reason: str, title: str) -> GovernanceFault:
            return _fault(
                reason,
                correlation,
                title,
                causation_id=causation,
            )

        if self._clock is None or self._state is None:
            raise fault(
                "CONTROL_PLANE_UNAVAILABLE",
                "trusted clock and authoritative lease state are required",
            )
        if not signature_verified:
            raise fault("LEASE_INVALID", "lease signature is not verified")
        if revoked:
            raise fault("LEASE_REVOKED", "lease is revoked")
        bindings = (
            "capability_id",
            "effective_principal_id",
            "delegation_ref",
            "action_instance_id",
            "governed_context_digest",
            "gate_package_digest",
        )
        if any(getattr(lease, field) != getattr(expected, field) for field in bindings):
            raise fault(
                "LEASE_CONTEXT_MISMATCH",
                "lease principal, scope, action, GCS, delegation, or gate binding differs",
            )
        if lease.stop_epoch != expected.stop_epoch:
            raise fault("STOP_EPOCH_MISMATCH", "lease stop epoch differs")
        if lease.fencing_token != expected.fencing_token:
            raise fault("FENCING_TOKEN_STALE", "lease fencing token is stale")
        try:
            decision = self._state.consume_if_current(
                clock=self._clock,
                lease_id=lease.lease_id,
                action_instance_id=lease.action_instance_id,
                stop_epoch=lease.stop_epoch,
                fencing_token=lease.fencing_token,
                emission_attempt=expected.emission_attempt,
                issued_at=lease.issued_at,
                expires_at=lease.expires_at,
            )
        except Exception as exc:
            raise fault(
                "CONTROL_PLANE_UNAVAILABLE",
                "authoritative lease state is unavailable",
            ) from exc
        if not isinstance(decision, LeaseStateDecision):
            raise fault(
                "CONTROL_PLANE_UNAVAILABLE",
                "authoritative lease state returned an invalid result",
            )
        outcome = decision.outcome
        if outcome is LeaseStateOutcome.CONTROL_PLANE_UNAVAILABLE:
            raise fault("CONTROL_PLANE_UNAVAILABLE", "trusted clock is unavailable")
        if outcome is LeaseStateOutcome.EXPIRED:
            raise fault("LEASE_EXPIRED", "lease is outside its time window")
        if outcome is LeaseStateOutcome.REVOKED:
            raise fault("LEASE_REVOKED", "lease is revoked")
        if outcome is LeaseStateOutcome.STOP_EPOCH_MISMATCH:
            raise fault("STOP_EPOCH_MISMATCH", "lease stop epoch is not current")
        if outcome is LeaseStateOutcome.FENCING_TOKEN_STALE:
            raise fault("FENCING_TOKEN_STALE", "lease fencing token is stale")
        if outcome is LeaseStateOutcome.ALREADY_CONSUMED:
            raise fault("LEASE_ALREADY_CONSUMED", "lease was already consumed")
        if outcome is not LeaseStateOutcome.CONSUMED:
            raise fault(
                "CONTROL_PLANE_UNAVAILABLE",
                "authoritative lease state returned an invalid result",
            )
        key = (lease.lease_id, lease.action_instance_id, expected.emission_attempt)
        if decision.evaluated_at is None:
            raise fault(
                "CONTROL_PLANE_UNAVAILABLE",
                "authoritative lease state omitted its evaluation time",
            )
        try:
            evaluated_at = _aware(
                "authoritative lease evaluation time",
                decision.evaluated_at,
                correlation,
            )
        except (GovernanceFault, TypeError, ValueError) as exc:
            raise fault(
                "CONTROL_PLANE_UNAVAILABLE",
                "authoritative lease state returned an invalid evaluation time",
            ) from exc
        if evaluated_at < lease.issued_at or evaluated_at >= lease.expires_at:
            raise fault(
                "CONTROL_PLANE_UNAVAILABLE",
                "authoritative lease state returned a contradictory evaluation time",
            )
        return LeaseConsumptionReceipt(
            key, lease.governed_context_digest, evaluated_at
        )


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    content_digest: str
    source_ref: str
    acquired_at: datetime
    acquirer_principal_id: str
    method_ref: str
    chain_of_custody: tuple[str, ...]
    marking_ref: str
    retention_until: datetime

    def __post_init__(self) -> None:
        for field in ("evidence_id", "source_ref", "acquirer_principal_id", "method_ref"):
            _string(field, getattr(self, field))
        _digest("content_digest", self.content_digest)
        _digest("marking_ref", self.marking_ref)
        object.__setattr__(
            self,
            "chain_of_custody",
            _refs("chain_of_custody", self.chain_of_custody, CORRELATION_ZERO),
        )
        _aware("acquired_at", self.acquired_at, CORRELATION_ZERO)
        _aware("retention_until", self.retention_until, CORRELATION_ZERO)
        if self.retention_until <= self.acquired_at:
            raise _fault(
                "EVIDENCE_INVALID", CORRELATION_ZERO, "evidence retention has expired"
            )

    def to_mapping(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "content_digest": self.content_digest,
            "source_ref": self.source_ref,
            "acquired_at": format_utc_timestamp(self.acquired_at),
            "acquirer_principal_id": self.acquirer_principal_id,
            "method_ref": self.method_ref,
            "chain_of_custody": list(self.chain_of_custody),
            "marking_ref": self.marking_ref,
            "retention_until": format_utc_timestamp(self.retention_until),
        }

    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    provenance_id: str
    evidence_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    activity_refs: tuple[str, ...]
    actor_refs: tuple[str, ...]
    governed_context_digest: str
    correlation_id: str
    causation_id: str
    created_at: datetime

    fields: ClassVar[tuple[str, ...]] = (
        "provenance_id",
        "evidence_refs",
        "source_refs",
        "activity_refs",
        "actor_refs",
        "governed_context_digest",
        "correlation_id",
        "causation_id",
        "created_at",
    )

    def __post_init__(self) -> None:
        correlation = self.correlation_id if isinstance(self.correlation_id, str) else CORRELATION_ZERO
        try:
            validate_correlation_id(self.correlation_id)
            validate_causation_id(self.causation_id)
        except IdentifierError as exc:
            raise _fault(
                "PROVENANCE_INCOMPLETE", CORRELATION_ZERO, f"causal binding invalid: {exc}"
            ) from exc
        _string("provenance_id", self.provenance_id, correlation)
        for field in ("evidence_refs", "source_refs", "activity_refs", "actor_refs"):
            object.__setattr__(self, field, _refs(field, getattr(self, field), correlation))
        try:
            _digest("governed_context_digest", self.governed_context_digest, correlation)
            _aware("created_at", self.created_at, correlation)
        except GovernanceFault as exc:
            raise _fault("PROVENANCE_INCOMPLETE", correlation, exc.title) from exc

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ProvenanceRecord:
        if not isinstance(value, Mapping):
            raise _fault(
                "PROVENANCE_INCOMPLETE",
                CORRELATION_ZERO,
                "ProvenanceRecord must be an object",
            )
        present = frozenset(value)
        required = frozenset(cls.fields)
        missing = sorted(required - present)
        additional = sorted(present - required)
        if missing:
            raise _fault(
                "PROVENANCE_INCOMPLETE",
                CORRELATION_ZERO,
                f"missing provenance fields: {', '.join(missing)}",
            )
        if additional:
            raise _fault(
                "PROVENANCE_INCOMPLETE",
                CORRELATION_ZERO,
                f"additional provenance fields: {', '.join(additional)}",
            )
        try:
            return cls(
                provenance_id=value["provenance_id"],  # type: ignore[arg-type]
                evidence_refs=value["evidence_refs"],  # type: ignore[arg-type]
                source_refs=value["source_refs"],  # type: ignore[arg-type]
                activity_refs=value["activity_refs"],  # type: ignore[arg-type]
                actor_refs=value["actor_refs"],  # type: ignore[arg-type]
                governed_context_digest=value["governed_context_digest"],  # type: ignore[arg-type]
                correlation_id=value["correlation_id"],  # type: ignore[arg-type]
                causation_id=value["causation_id"],  # type: ignore[arg-type]
                created_at=parse_utc_timestamp(value["created_at"]),  # type: ignore[arg-type]
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, GovernanceFault):
                raise
            raise _fault(
                "PROVENANCE_INCOMPLETE", CORRELATION_ZERO, f"invalid provenance: {exc}"
            ) from exc

    def to_mapping(self) -> dict[str, object]:
        return {
            "provenance_id": self.provenance_id,
            "evidence_refs": list(self.evidence_refs),
            "source_refs": list(self.source_refs),
            "activity_refs": list(self.activity_refs),
            "actor_refs": list(self.actor_refs),
            "governed_context_digest": self.governed_context_digest,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "created_at": format_utc_timestamp(self.created_at),
        }

    def digest(self) -> str:
        return canonical_digest(self.to_mapping())
