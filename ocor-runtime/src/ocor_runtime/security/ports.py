"""Fail-closed typed ports for the sovereign security control plane."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ..kernel.canonical import validate_correlation_id
from ..kernel.governed_context import GovernedContext

DIGEST = re.compile(r"urn:sha256:[0-9a-f]{64}")
SPIFFE_ID = re.compile(r"spiffe://[a-z0-9.-]+(?:/[A-Za-z0-9._~-]+)+")
FORBIDDEN_PRINCIPALS = frozenset({"anonymous", "guest", "shared", "unknown"})


class SecurityControlError(RuntimeError):
    """Stable failure that never contains credentials or secret material."""

    def __init__(self, reason_code: str, message: str) -> None:
        if not reason_code or not message or len(message) > 256:
            raise ValueError("bounded reason_code and message are required")
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _required(field: str, value: object, *, reason: str = "SECURITY_RECORD_INVALID") -> str:
    if not isinstance(value, str) or not value:
        raise SecurityControlError(reason, f"{field} is required")
    return value


def _digest(field: str, value: object) -> str:
    result = _required(field, value)
    if DIGEST.fullmatch(result) is None:
        raise SecurityControlError("SECURITY_RECORD_INVALID", f"{field} is not a SHA-256 URN")
    return result


def _aware(field: str, value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise SecurityControlError("SECURITY_RECORD_INVALID", f"{field} must be timezone-aware")
    return value


def _refs(field: str, values: object) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise SecurityControlError("SECURITY_RECORD_INVALID", f"{field} must be an array")
    result = tuple(values)
    if not result or any(not isinstance(item, str) or not item for item in result):
        raise SecurityControlError("SECURITY_RECORD_INVALID", f"{field} is incomplete")
    if len(result) != len(set(result)):
        raise SecurityControlError("SECURITY_RECORD_INVALID", f"{field} contains duplicates")
    return result


class ControlName(StrEnum):
    IDENTITY = "IDENTITY"
    POLICY = "POLICY"
    WORKLOAD_IDENTITY = "WORKLOAD_IDENTITY"
    SECRETS = "SECRETS"
    STOP_EPOCH = "STOP_EPOCH"


@dataclass(frozen=True, slots=True)
class ControlStatus:
    control: ControlName
    is_available: bool
    reason_code: str | None
    observed_at: datetime
    source_digest: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "control", ControlName(self.control))
        except ValueError as exc:
            raise SecurityControlError("CONTROL_STATUS_INVALID", "unknown control") from exc
        if not isinstance(self.is_available, bool):
            raise SecurityControlError("CONTROL_STATUS_INVALID", "is_available must be boolean")
        _aware("observed_at", self.observed_at)
        _digest("source_digest", self.source_digest)
        if self.is_available and self.reason_code is not None:
            raise SecurityControlError(
                "CONTROL_STATUS_INVALID", "available control cannot carry a failure reason"
            )
        if not self.is_available and (
            not isinstance(self.reason_code, str)
            or not self.reason_code
            or len(self.reason_code) > 128
        ):
            raise SecurityControlError(
                "CONTROL_STATUS_INVALID", "unavailable control requires bounded reason_code"
            )

    @classmethod
    def available(
        cls, control: ControlName, *, observed_at: datetime, source_digest: str
    ) -> ControlStatus:
        return cls(control, True, None, observed_at, source_digest)

    @classmethod
    def unavailable(
        cls,
        control: ControlName,
        *,
        reason_code: str,
        observed_at: datetime,
        source_digest: str,
    ) -> ControlStatus:
        return cls(control, False, reason_code, observed_at, source_digest)

    def require_available(self, expected: ControlName | None = None) -> None:
        if expected is not None and self.control is not expected:
            raise SecurityControlError(
                "CONTROL_STATUS_INVALID",
                f"expected {expected.value} status, received {self.control.value}",
            )
        if not self.is_available:
            raise SecurityControlError(
                f"{self.control.value}_UNAVAILABLE",
                f"{self.control.value} control is unavailable ({self.reason_code})",
            )


@dataclass(frozen=True, slots=True)
class IdentityRequest:
    credential_ref: str
    expected_audience: str
    correlation_id: str

    def __post_init__(self) -> None:
        credential = _required("credential_ref", self.credential_ref)
        if not credential.startswith("urn:ocor:credential-ref:"):
            raise SecurityControlError(
                "IDENTITY_REQUEST_INVALID", "only an opaque credential reference is accepted"
            )
        _required("expected_audience", self.expected_audience)
        try:
            validate_correlation_id(self.correlation_id)
        except ValueError as exc:
            raise SecurityControlError("IDENTITY_REQUEST_INVALID", "invalid correlation_id") from exc

    def to_mapping(self) -> dict[str, str]:
        return {
            "credential_ref": self.credential_ref,
            "expected_audience": self.expected_audience,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    principal_id: str
    session_id: str
    actor_chain: tuple[str, ...]
    assurance_level: str
    authenticated_at: datetime
    expires_at: datetime
    status: ControlStatus

    def __post_init__(self) -> None:
        self.status.require_available(ControlName.IDENTITY)
        if (
            not isinstance(self.principal_id, str)
            or not self.principal_id
            or self.principal_id.lower() in FORBIDDEN_PRINCIPALS
        ):
            raise SecurityControlError(
                "ANONYMOUS_IDENTITY_FORBIDDEN", "anonymous, guest or shared identity is forbidden"
            )
        principal = self.principal_id
        _required("session_id", self.session_id)
        object.__setattr__(self, "actor_chain", _refs("actor_chain", self.actor_chain))
        if principal not in self.actor_chain:
            raise SecurityControlError(
                "IDENTITY_BINDING_MISMATCH", "principal must occur in actor_chain"
            )
        _required("assurance_level", self.assurance_level)
        _aware("authenticated_at", self.authenticated_at)
        _aware("expires_at", self.expires_at)
        if self.authenticated_at >= self.expires_at:
            raise SecurityControlError("IDENTITY_EXPIRED", "identity validity window is empty")

    def require_valid(self, *, at: datetime) -> AuthenticatedPrincipal:
        instant = _aware("at", at)
        self.status.require_available(ControlName.IDENTITY)
        if instant < self.authenticated_at or instant >= self.expires_at:
            raise SecurityControlError("IDENTITY_EXPIRED", "identity is outside its validity window")
        return self


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    principal: AuthenticatedPrincipal
    action: str
    resource: str
    governed_context: GovernedContext
    governed_context_digest: str
    at: datetime

    def __post_init__(self) -> None:
        self.principal.require_valid(at=self.at)
        _required("action", self.action)
        _required("resource", self.resource)
        _digest("governed_context_digest", self.governed_context_digest)
        if self.governed_context.digest() != self.governed_context_digest:
            raise SecurityControlError(
                "GOVERNED_CONTEXT_MISMATCH", "GCS digest does not match request"
            )
        if self.governed_context.effective_principal_id != self.principal.principal_id:
            raise SecurityControlError(
                "PRINCIPAL_BINDING_MISMATCH", "authenticated principal differs from GCS"
            )


class PolicyEffect(StrEnum):
    PERMIT = "PERMIT"
    DENY = "DENY"
    PERMIT_WITH_CONSTRAINTS = "PERMIT_WITH_CONSTRAINTS"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    OBLIGATE = "OBLIGATE"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision_id: str
    effect: PolicyEffect
    principal_id: str
    action: str
    resource: str
    purpose: str
    governed_context_digest: str
    policy_bundle_digest: str
    evaluated_at: datetime
    valid_until: datetime
    obligations: tuple[str, ...]
    status: ControlStatus

    def __post_init__(self) -> None:
        self.status.require_available(ControlName.POLICY)
        _required("decision_id", self.decision_id)
        try:
            object.__setattr__(self, "effect", PolicyEffect(self.effect))
        except ValueError as exc:
            raise SecurityControlError("POLICY_DECISION_INVALID", "unknown policy effect") from exc
        for field in ("principal_id", "action", "resource", "purpose"):
            _required(field, getattr(self, field), reason="POLICY_DECISION_INVALID")
        _digest("governed_context_digest", self.governed_context_digest)
        _digest("policy_bundle_digest", self.policy_bundle_digest)
        if self.status.source_digest != self.policy_bundle_digest:
            raise SecurityControlError(
                "POLICY_BINDING_MISMATCH", "control status is not bound to policy bundle"
            )
        _aware("evaluated_at", self.evaluated_at)
        _aware("valid_until", self.valid_until)
        if self.evaluated_at >= self.valid_until:
            raise SecurityControlError("POLICY_DECISION_EXPIRED", "policy validity window is empty")
        obligations = tuple(self.obligations)
        if any(not isinstance(item, str) or not item for item in obligations):
            raise SecurityControlError("POLICY_DECISION_INVALID", "obligations are malformed")
        if len(obligations) != len(set(obligations)):
            raise SecurityControlError("POLICY_DECISION_INVALID", "obligations contain duplicates")
        if self.effect in {
            PolicyEffect.PERMIT_WITH_CONSTRAINTS,
            PolicyEffect.REQUIRE_APPROVAL,
            PolicyEffect.OBLIGATE,
        } and not obligations:
            raise SecurityControlError(
                "POLICY_DECISION_INVALID", "constrained effect requires obligations"
            )
        object.__setattr__(self, "obligations", tuple(sorted(obligations)))

    @classmethod
    def from_request(
        cls,
        request: PolicyRequest,
        *,
        effect: PolicyEffect,
        decision_id: str,
        valid_until: datetime,
        status: ControlStatus,
        obligations: tuple[str, ...] = (),
    ) -> PolicyDecision:
        return cls(
            decision_id=decision_id,
            effect=effect,
            principal_id=request.principal.principal_id,
            action=request.action,
            resource=request.resource,
            purpose=request.governed_context.purpose,
            governed_context_digest=request.governed_context_digest,
            policy_bundle_digest=request.governed_context.policy_bundle_digest,
            evaluated_at=request.at,
            valid_until=valid_until,
            obligations=obligations,
            status=status,
        )

    def verify(self, request: PolicyRequest, *, at: datetime) -> PolicyDecision:
        self.status.require_available(ControlName.POLICY)
        instant = _aware("at", at)
        if instant < self.evaluated_at or instant >= self.valid_until:
            raise SecurityControlError("POLICY_DECISION_EXPIRED", "policy decision is expired")
        expected = (
            request.principal.principal_id,
            request.action,
            request.resource,
            request.governed_context.purpose,
            request.governed_context_digest,
            request.governed_context.policy_bundle_digest,
        )
        actual = (
            self.principal_id,
            self.action,
            self.resource,
            self.purpose,
            self.governed_context_digest,
            self.policy_bundle_digest,
        )
        if actual != expected:
            raise SecurityControlError(
                "POLICY_BINDING_MISMATCH", "policy decision bindings drifted"
            )
        return self

    def admit(
        self,
        *,
        enforced_constraints: frozenset[str] = frozenset(),
        granted_approvals: frozenset[str] = frozenset(),
        fulfilled_obligations: frozenset[str] = frozenset(),
    ) -> PolicyDecision:
        """Apply the decision (ADD v1.3 :3141, Register FR-130; OCOR-DEV-REM-0054, NCR-C6-011).

        ``DENY`` refuses. ``PERMIT_WITH_CONSTRAINTS`` admits only a consumer that enforces every
        constraint, ``REQUIRE_APPROVAL`` only with every required approval granted and
        ``OBLIGATE`` only with every obligation fulfilled; a consumer that cannot honour a
        qualification refuses (default deny). ``PERMIT`` carries no qualification.
        """
        honoured: dict[str, frozenset[str]] = {}
        for name, value in (
            ("enforced_constraints", enforced_constraints),
            ("granted_approvals", granted_approvals),
            ("fulfilled_obligations", fulfilled_obligations),
        ):
            if not isinstance(value, frozenset) or any(not isinstance(item, str) or not item for item in value):
                raise TypeError(f"{name} must be a frozenset of non-empty strings")
            honoured[name] = value
        required = frozenset(self.obligations)
        if self.effect is PolicyEffect.DENY:
            raise SecurityControlError("POLICY_DENIED", "the policy denies the request")
        if self.effect is PolicyEffect.PERMIT:
            if required:
                raise SecurityControlError("POLICY_DECISION_INVALID", "an unqualified permit carries obligations")
            return self
        checks = {
            PolicyEffect.PERMIT_WITH_CONSTRAINTS: ("enforced_constraints", "POLICY_CONSTRAINT_NOT_ENFORCED"),
            PolicyEffect.REQUIRE_APPROVAL: ("granted_approvals", "APPROVAL_REQUIRED"),
            PolicyEffect.OBLIGATE: ("fulfilled_obligations", "POLICY_OBLIGATION_NOT_FULFILLED"),
        }
        field, reason = checks[self.effect]
        missing = sorted(required - honoured[field])
        if missing:
            raise SecurityControlError(reason, f"the {self.effect.value} decision is not honoured: {missing}")
        return self


@dataclass(frozen=True, slots=True)
class WorkloadIdentity:
    spiffe_id: str
    svid_ref: str
    trust_bundle_digest: str
    attested: bool
    not_before: datetime
    expires_at: datetime
    status: ControlStatus

    def __post_init__(self) -> None:
        self.status.require_available(ControlName.WORKLOAD_IDENTITY)
        if not isinstance(self.spiffe_id, str) or SPIFFE_ID.fullmatch(self.spiffe_id) is None:
            raise SecurityControlError(
                "WORKLOAD_IDENTITY_INVALID", "workload identity must be a SPIFFE ID"
            )
        _required("svid_ref", self.svid_ref)
        _digest("trust_bundle_digest", self.trust_bundle_digest)
        if self.status.source_digest != self.trust_bundle_digest:
            raise SecurityControlError(
                "WORKLOAD_IDENTITY_INVALID", "status is not bound to the trust bundle"
            )
        if self.attested is not True:
            raise SecurityControlError(
                "WORKLOAD_IDENTITY_UNATTESTED", "workload identity is not attested"
            )
        _aware("not_before", self.not_before)
        _aware("expires_at", self.expires_at)
        if self.not_before >= self.expires_at:
            raise SecurityControlError(
                "WORKLOAD_IDENTITY_EXPIRED", "SVID validity window is empty"
            )

    def require_valid(self, *, at: datetime) -> WorkloadIdentity:
        self.status.require_available(ControlName.WORKLOAD_IDENTITY)
        instant = _aware("at", at)
        if instant < self.not_before or instant >= self.expires_at:
            raise SecurityControlError("WORKLOAD_IDENTITY_EXPIRED", "SVID is expired")
        return self


@dataclass(frozen=True, slots=True)
class SecretRequest:
    secret_ref: str
    principal_id: str
    purpose: str
    governed_context_digest: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if not _required("secret_ref", self.secret_ref).startswith("urn:ocor:secret-ref:"):
            raise SecurityControlError(
                "SECRET_REFERENCE_INVALID", "only an infrastructure secret reference is accepted"
            )
        _required("principal_id", self.principal_id)
        _required("purpose", self.purpose)
        _digest("governed_context_digest", self.governed_context_digest)
        _aware("requested_at", self.requested_at)


@dataclass(frozen=True, slots=True)
class SecretLease:
    secret_ref: str
    handle_ref: str
    version: str
    principal_id: str
    purpose: str
    governed_context_digest: str
    issued_at: datetime
    expires_at: datetime
    status: ControlStatus

    def __post_init__(self) -> None:
        self.status.require_available(ControlName.SECRETS)
        if not _required("secret_ref", self.secret_ref).startswith("urn:ocor:secret-ref:"):
            raise SecurityControlError("SECRET_REFERENCE_INVALID", "secret_ref is invalid")
        if not _required("handle_ref", self.handle_ref).startswith("urn:ocor:secret-handle:"):
            raise SecurityControlError(
                "SECRET_MATERIAL_FORBIDDEN", "only an opaque secret handle may cross the port"
            )
        for field in ("version", "principal_id", "purpose"):
            _required(field, getattr(self, field))
        _digest("governed_context_digest", self.governed_context_digest)
        _aware("issued_at", self.issued_at)
        _aware("expires_at", self.expires_at)
        if self.issued_at >= self.expires_at:
            raise SecurityControlError("SECRET_LEASE_EXPIRED", "secret lease window is empty")

    @classmethod
    def from_request(
        cls,
        request: SecretRequest,
        *,
        handle_ref: str,
        version: str,
        expires_at: datetime,
        status: ControlStatus,
    ) -> SecretLease:
        return cls(
            secret_ref=request.secret_ref,
            handle_ref=handle_ref,
            version=version,
            principal_id=request.principal_id,
            purpose=request.purpose,
            governed_context_digest=request.governed_context_digest,
            issued_at=request.requested_at,
            expires_at=expires_at,
            status=status,
        )

    def verify(self, request: SecretRequest, *, at: datetime) -> SecretLease:
        self.status.require_available(ControlName.SECRETS)
        instant = _aware("at", at)
        if instant < self.issued_at or instant >= self.expires_at:
            raise SecurityControlError("SECRET_LEASE_EXPIRED", "secret lease is expired")
        if (
            self.secret_ref,
            self.principal_id,
            self.purpose,
            self.governed_context_digest,
        ) != (
            request.secret_ref,
            request.principal_id,
            request.purpose,
            request.governed_context_digest,
        ):
            raise SecurityControlError("SECRET_BINDING_MISMATCH", "secret lease binding drifted")
        return self


@dataclass(frozen=True, slots=True)
class StopEpochSnapshot:
    epoch: int
    stopped: bool
    observed_at: datetime
    status: ControlStatus

    def __post_init__(self) -> None:
        self.status.require_available(ControlName.STOP_EPOCH)
        if isinstance(self.epoch, bool) or not isinstance(self.epoch, int) or self.epoch < 0:
            raise SecurityControlError("STOP_EPOCH_INVALID", "stop epoch must be non-negative")
        if not isinstance(self.stopped, bool):
            raise SecurityControlError("STOP_EPOCH_INVALID", "stopped must be boolean")
        _aware("observed_at", self.observed_at)

    def assert_dispatch_allowed(self, *, expected_epoch: int) -> StopEpochSnapshot:
        self.status.require_available(ControlName.STOP_EPOCH)
        if self.stopped:
            raise SecurityControlError("EMERGENCY_STOP_ACTIVE", "emergency stop is active")
        if expected_epoch != self.epoch:
            raise SecurityControlError("STOP_EPOCH_MISMATCH", "stop epoch changed")
        return self


@runtime_checkable
class IdentityProviderPort(Protocol):
    def authenticate(self, request: IdentityRequest) -> AuthenticatedPrincipal: ...


@runtime_checkable
class PolicyDecisionPort(Protocol):
    def evaluate(self, request: PolicyRequest) -> PolicyDecision: ...


@runtime_checkable
class WorkloadIdentityPort(Protocol):
    def current(self) -> WorkloadIdentity: ...


@runtime_checkable
class SecretProviderPort(Protocol):
    def lease(self, request: SecretRequest) -> SecretLease: ...


@runtime_checkable
class StopEpochPort(Protocol):
    def snapshot(self) -> StopEpochSnapshot: ...
