"""C6 -- the EMISSION-FENCE of the action path and its Capability Lease (OCOR-DEV-REM-0053).

``EMISSION-FENCE := G-FRESHNESS and G-DISPATCH`` is evaluated atomically immediately before every
send, first dispatch, retry, compensation and the send to C3 of a canonical commit included; its
evaluation and the record of the ``DeliveryAttempt`` belong to the same local transaction of the
dispatcher, and any material drift gives ``INVALIDATED`` before the send (ADD v1.3 :2851-2854,
LLD v1.1 :256, :302, FR-078, FR-162). An evaluation error never degrades to a retry.

The ``CapabilityLease`` is the closed record of ``kernel.governance`` (ADD v1.3 :3194-3212,
``capability-lease.schema.json``), signed by the capability authority, at most PT5S and single use
per ``(action_instance_id, emission_attempt)``. ``LeaseValidator.consume`` runs in the transaction
of the ``DeliveryAttempt``: signature, schema, time window and revocation; principal, delegation,
action, GCS, GatePackage and stop epoch; the lock on the fencing counter of the action instance;
the consumption not yet recorded; then consumption and ``DeliveryAttempt`` are inserted together
or rolled back entirely (LLD v1.1 :69-81). There is no permissive fallback: the signature is
verified at the boundary with the authority's public key, never taken from the caller.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from ..c1.signing import Ed25519SigningKey, dsse_pae, ed25519_verify
from ..errors import OCORError
from ..kernel.canonical import canonical_bytes
from ..kernel.governance import (
    CapabilityLease,
    GovernanceFault,
    LeaseConsumptionLedger,
    LeaseExpectation,
    LeaseStateDecision,
    LeaseStateOutcome,
    TrustedClock,
)
from . import records as c6_records
from .human_gate import SignerKeyring

LEASE_PAYLOAD_TYPE = "application/vnd.ocor.c6.capability-lease+json"
MAX_LEASE_TTL = timedelta(seconds=5)

LEASE_REASONS = frozenset(
    {
        "LEASE_INVALID",
        "LEASE_EXPIRED",
        "LEASE_REVOKED",
        "LEASE_CONTEXT_MISMATCH",
        "STOP_EPOCH_MISMATCH",
        "FENCING_TOKEN_STALE",
        "LEASE_ALREADY_CONSUMED",
    }
)


class DispatchError(OCORError):
    """The EMISSION-FENCE refused the send: the outcome is ``INVALIDATED`` and ``reason_code`` is
    the guard that refused (a lease reason code of LLD v1.1 :81, ``STALE_<FIELD>`` of
    G-FRESHNESS, a G-DISPATCH condition or ``FENCE_EVALUATION_FAILED``). Nothing was consumed or
    recorded."""

    outcome = "INVALIDATED"

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _require_aware(instant: object, *, field: str) -> datetime:
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return instant


def _stop_epoch(value: object) -> int:
    # The stop epoch is read without conversion: a boolean, text or negative answer is no epoch.
    if type(value) is not int or value < 0:
        raise TypeError("the stop epoch is answered as a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class SignedCapabilityLease:
    """The closed CapabilityLease record with the Ed25519 signature of the capability authority
    over its DSSE pre-authentication encoding; the record itself stays the closed eleven-field
    record of the schema."""

    lease: CapabilityLease
    issuer_id: str
    keyid: str
    signature: str

    def signed_bytes(self) -> bytes:
        return lease_signed_bytes(self.lease)

    def to_mapping(self) -> dict[str, object]:
        return {
            "lease": self.lease.to_mapping(),
            "issuer_id": self.issuer_id,
            "keyid": self.keyid,
            "signature": self.signature,
        }


def lease_signed_bytes(lease: CapabilityLease) -> bytes:
    return dsse_pae(LEASE_PAYLOAD_TYPE, canonical_bytes(lease.to_mapping()))


def sign_capability_lease(
    key: Ed25519SigningKey, *, issuer_id: str, keyid: str, lease: CapabilityLease
) -> SignedCapabilityLease:
    """The capability authority's signature of a CapabilityLease."""

    if not isinstance(key, Ed25519SigningKey):
        raise TypeError("key must be the capability authority's Ed25519 signing key")
    if not isinstance(lease, CapabilityLease):
        raise TypeError("lease must be a kernel.governance.CapabilityLease")
    if not isinstance(issuer_id, str) or not issuer_id or not isinstance(keyid, str) or not keyid:
        raise ValueError("issuer_id and keyid are required")
    signature = base64.b64encode(key.sign(lease_signed_bytes(lease))).decode("ascii")
    return SignedCapabilityLease(lease=lease, issuer_id=issuer_id, keyid=keyid, signature=signature)


class CapabilityLeaseIssuer:
    """The capability authority: issues the signed lease of one emission attempt, now, for at
    most PT5S (ADD v1.3 :3212)."""

    def __init__(
        self,
        *,
        signing_key: Ed25519SigningKey,
        issuer_id: str,
        keyid: str,
        clock: TrustedClock,
        ttl: timedelta = MAX_LEASE_TTL,
    ) -> None:
        if not isinstance(signing_key, Ed25519SigningKey):
            raise TypeError("signing_key must be an Ed25519 signing key")
        if not isinstance(issuer_id, str) or not issuer_id or not isinstance(keyid, str) or not keyid:
            raise ValueError("issuer_id and keyid are required")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock must implement TrustedClock")
        if not isinstance(ttl, timedelta) or ttl <= timedelta(0) or ttl > MAX_LEASE_TTL:
            raise ValueError("a CapabilityLease lasts more than zero and at most five seconds")
        self._key = signing_key
        self._issuer_id = issuer_id
        self._keyid = keyid
        self._clock = clock
        self._ttl = ttl

    def issue(
        self,
        *,
        capability_id: str,
        effective_principal_id: str,
        delegation_ref: str,
        action_instance_id: str,
        governed_context_digest: str,
        gate_package_digest: str,
        stop_epoch: int,
        fencing_token: int,
    ) -> SignedCapabilityLease:
        now = _require_aware(self._clock.now(), field="trusted now")
        lease = CapabilityLease(
            lease_id=f"urn:ocor:lease:{uuid.uuid4()}",
            capability_id=capability_id,
            effective_principal_id=effective_principal_id,
            delegation_ref=delegation_ref,
            action_instance_id=action_instance_id,
            governed_context_digest=governed_context_digest,
            gate_package_digest=gate_package_digest,
            stop_epoch=stop_epoch,
            fencing_token=fencing_token,
            issued_at=now,
            expires_at=now + self._ttl,
        )
        return sign_capability_lease(self._key, issuer_id=self._issuer_id, keyid=self._keyid, lease=lease)


@runtime_checkable
class DelegationPort(Protocol):
    """The verified Delegation of an effective principal (C2), as the lease must bind it."""

    def verified_delegation(self, effective_principal_id: str) -> str | None: ...


class InMemoryDelegationRegistry:
    def __init__(self) -> None:
        self._delegations: dict[str, str] = {}
        self._lock = threading.Lock()

    def register(self, effective_principal_id: str, delegation_ref: str) -> None:
        if not isinstance(effective_principal_id, str) or not effective_principal_id:
            raise ValueError("effective_principal_id is required")
        if not isinstance(delegation_ref, str) or not delegation_ref.startswith("urn:sha256:"):
            raise ValueError("delegation_ref must be a SHA-256 URN")
        with self._lock:
            known = self._delegations.setdefault(effective_principal_id, delegation_ref)
        if known != delegation_ref:
            raise ValueError("the principal is already bound to another Delegation")

    def verified_delegation(self, effective_principal_id: str) -> str | None:
        with self._lock:
            return self._delegations.get(effective_principal_id)


class LeaseValidator:
    """``LeaseValidator`` of LLD v1.1 :71-81 over the capability authorities' keyring and the
    trusted clock; it consumes a lease only inside a dispatch transaction."""

    def __init__(self, *, issuers: SignerKeyring, clock: TrustedClock) -> None:
        if not callable(getattr(issuers, "public_key", None)):
            raise TypeError("issuers must implement SignerKeyring")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock must implement TrustedClock")
        self._issuers = issuers
        self._clock = clock

    @property
    def clock(self) -> TrustedClock:
        return self._clock

    def verify(self, signed: object) -> CapabilityLease:
        """Signature and schema of the lease (step 1 of LLD v1.1 :73, without time and
        revocation): ``LEASE_INVALID`` unless the closed record is signed by a known authority."""

        if not isinstance(signed, SignedCapabilityLease) or not isinstance(signed.lease, CapabilityLease):
            raise DispatchError("LEASE_INVALID", "a signed CapabilityLease is required")
        try:
            # Schema: the closed record of capability-lease.schema.json, rebuilt from its wire form.
            closed = CapabilityLease.from_mapping(signed.lease.to_mapping())
        except GovernanceFault as fault:
            raise DispatchError("LEASE_INVALID", f"the lease is not the closed record: {fault}") from fault
        if closed != signed.lease:
            raise DispatchError("LEASE_INVALID", "the lease does not round-trip through its closed record")
        if not isinstance(signed.issuer_id, str) or not isinstance(signed.keyid, str):
            raise DispatchError("LEASE_INVALID", "the lease issuer is not identified")
        try:
            public_key = self._issuers.public_key(signed.issuer_id, signed.keyid)
        except Exception as error:
            raise DispatchError("LEASE_INVALID", "the capability authority's key is unavailable") from error
        if not isinstance(public_key, bytes) or len(public_key) != 32:
            raise DispatchError("LEASE_INVALID", "the lease is not signed by a known capability authority")
        if not isinstance(signed.signature, str):
            raise DispatchError("LEASE_INVALID", "the lease signature is malformed")
        try:
            raw = base64.b64decode(signed.signature, validate=True)
        except (binascii.Error, ValueError) as error:
            raise DispatchError("LEASE_INVALID", "the lease signature is malformed") from error
        try:
            verified = ed25519_verify(public_key, lease_signed_bytes(closed), raw)
        except Exception as error:
            raise DispatchError("LEASE_INVALID", "the lease is not a canonical signed record") from error
        if not verified:
            raise DispatchError("LEASE_INVALID", "the lease signature is not valid")
        return closed

    def consume(
        self, signed: object, expected: LeaseExpectation, *, state: Any
    ) -> tuple[CapabilityLease, Any]:
        """Steps 1-4 of LLD v1.1 :73-78 on the transaction-scoped ``state``; step 5 is the
        transaction's commit. Returns the lease and the consumption receipt."""

        lease = self.verify(signed)
        try:
            receipt = LeaseConsumptionLedger(clock=self._clock, state=state).consume(
                lease, expected, signature_verified=True
            )
        except GovernanceFault as fault:
            reason = fault.reason_code if fault.reason_code in LEASE_REASONS else "FENCE_EVALUATION_FAILED"
            raise DispatchError(reason, str(fault)) from fault
        return lease, receipt


@runtime_checkable
class DispatchConditions(Protocol):
    """The G-DISPATCH conditions the fence reads inside its transaction (ADD v1.3 :2852): the
    emergency stop and stop epoch (C6), durable audit append, the circuit breaker and the
    conformance of the adapter binding, and the unresolved effects by ConflictScope."""

    def emergency_stop_active(self) -> bool: ...

    def current_stop_epoch(self) -> int: ...

    def audit_append_available(self) -> bool: ...

    def circuit_closed(self, adapter_binding_digest: str) -> bool: ...

    def adapter_conformant(self, adapter_binding_digest: str) -> bool: ...

    def unresolved_conflict(self, conflict_scope_digest: str) -> bool: ...


class InMemoryDispatchConditions:
    """Dispatch conditions over the stop authority (``MutationFencePort``), with controllable
    audit, circuit breaker, adapter conformance and unresolved ConflictScopes."""

    def __init__(self, *, stop: Any) -> None:
        if not callable(getattr(stop, "current_stop_epoch", None)) or not callable(
            getattr(stop, "emergency_stop_active", None)
        ):
            raise TypeError("stop must expose current_stop_epoch and emergency_stop_active")
        self._stop = stop
        self.audit_available = True
        self.open_circuits: set[str] = set()
        self.nonconformant: set[str] = set()
        self.unresolved: set[str] = set()
        self.raise_on_read = False

    def _read(self) -> None:
        if self.raise_on_read:
            raise ConnectionError("dispatch conditions unavailable")

    def emergency_stop_active(self) -> bool:
        self._read()
        active = self._stop.emergency_stop_active()
        if type(active) is not bool:
            raise TypeError("the emergency stop is answered as a boolean")
        return active

    def current_stop_epoch(self) -> int:
        self._read()
        return _stop_epoch(self._stop.current_stop_epoch())

    def audit_append_available(self) -> bool:
        self._read()
        return self.audit_available is True

    def circuit_closed(self, adapter_binding_digest: str) -> bool:
        self._read()
        return adapter_binding_digest not in self.open_circuits

    def adapter_conformant(self, adapter_binding_digest: str) -> bool:
        self._read()
        return adapter_binding_digest not in self.nonconformant

    def unresolved_conflict(self, conflict_scope_digest: str) -> bool:
        self._read()
        return conflict_scope_digest in self.unresolved


@dataclass(frozen=True, slots=True)
class CurrentValues:
    """The current values G-FRESHNESS compares with the frozen GatePackage (ADD v1.3 :2851)."""

    expected_revision: int
    canonical_commit_ref: str
    governed_context_digest: str
    policy_bundle_digest: str
    ontology_release_digest: str
    authority_ref: str
    approval_set_digest: str
    adapter_binding_digest: str
    projection_watermark: str


FRESHNESS_FIELDS = tuple(item.name for item in fields(CurrentValues))


class _DispatchTransaction:
    """The local transaction of one evaluation: the lease state port seen by
    ``LeaseConsumptionLedger`` and the DeliveryAttempt, both buffered until commit."""

    def __init__(self, ledger: InMemoryDispatchLedger, action_instance_id: str) -> None:
        self._ledger = ledger
        self.action_instance_id = action_instance_id
        self.consumption: tuple[str, str, int] | None = None
        self.attempt: c6_records.DeliveryAttempt | None = None
        self.idempotency_key: str | None = None

    @property
    def emission_attempt(self) -> int:
        return len(self._ledger._attempts.get(self.action_instance_id, ())) + 1

    @property
    def fencing_token(self) -> int:
        return self._ledger._fencing.get(self.action_instance_id, 1)

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
        ledger = self._ledger
        try:
            now = _require_aware(clock.now(), field="trusted now")
        except (AttributeError, RuntimeError, TypeError, ValueError, OSError):
            return LeaseStateDecision(LeaseStateOutcome.CONTROL_PLANE_UNAVAILABLE, None)
        if now < issued_at or now >= expires_at:
            return LeaseStateDecision(LeaseStateOutcome.EXPIRED, now)
        if lease_id in ledger._revoked:
            return LeaseStateDecision(LeaseStateOutcome.REVOKED, now)
        try:
            current_epoch = _stop_epoch(ledger._stop_epoch_reader())
        except Exception:
            return LeaseStateDecision(LeaseStateOutcome.CONTROL_PLANE_UNAVAILABLE, None)
        if stop_epoch != current_epoch:
            return LeaseStateDecision(LeaseStateOutcome.STOP_EPOCH_MISMATCH, now)
        if action_instance_id != self.action_instance_id or fencing_token != self.fencing_token:
            return LeaseStateDecision(LeaseStateOutcome.FENCING_TOKEN_STALE, now)
        if lease_id in ledger._consumed or (
            self.consumption is not None and self.consumption[0] == lease_id
        ):
            return LeaseStateDecision(LeaseStateOutcome.ALREADY_CONSUMED, now)
        self.consumption = (lease_id, action_instance_id, emission_attempt)
        return LeaseStateDecision(LeaseStateOutcome.CONSUMED, now)

    def record(self, attempt: c6_records.DeliveryAttempt, *, idempotency_key: str) -> None:
        if self._ledger.fail_next_record:
            self._ledger.fail_next_record = False
            raise OSError("the DeliveryAttempt could not be recorded")
        self.attempt = attempt
        self.idempotency_key = idempotency_key


class InMemoryDispatchLedger:
    """The dispatcher's local transactional store: the fencing counter of each action instance,
    revoked and consumed leases and the DeliveryAttempts, with one lock held for the whole
    evaluation (the lock on the fencing counter, LLD v1.1 :77)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._fencing: dict[str, int] = {}
        self._revoked: set[str] = set()
        self._consumed: dict[str, tuple[str, int]] = {}
        self._attempts: dict[str, tuple[c6_records.DeliveryAttempt, ...]] = {}
        self._keys: dict[str, str] = {}
        self._stop_epoch_reader: Callable[[], int] = lambda: 0
        self.fail_next_record = False

    def fencing_token(self, action_instance_id: str) -> int:
        with self._lock:
            return self._fencing.get(action_instance_id, 1)

    def advance_fencing_token(self, action_instance_id: str) -> int:
        with self._lock:
            token = self._fencing.get(action_instance_id, 1) + 1
            self._fencing[action_instance_id] = token
            return token

    def revoke(self, lease_id: str) -> None:
        if not isinstance(lease_id, str) or not lease_id:
            raise ValueError("lease_id is required")
        with self._lock:
            self._revoked.add(lease_id)

    def consumed(self, lease_id: str) -> tuple[str, int] | None:
        with self._lock:
            return self._consumed.get(lease_id)

    def attempts(self, action_instance_id: str) -> tuple[c6_records.DeliveryAttempt, ...]:
        with self._lock:
            return self._attempts.get(action_instance_id, ())

    def idempotency_key(self, action_instance_id: str) -> str | None:
        with self._lock:
            return self._keys.get(action_instance_id)

    @contextmanager
    def transaction(
        self, action_instance_id: str, *, stop_epoch: Callable[[], int]
    ) -> Iterator[_DispatchTransaction]:
        """Consumption and DeliveryAttempt are inserted together on a clean exit, or neither."""

        with self._lock:
            self._stop_epoch_reader = stop_epoch
            transaction = _DispatchTransaction(self, action_instance_id)
            yield transaction
            if transaction.attempt is None or transaction.consumption is None:
                raise DispatchError("FENCE_EVALUATION_FAILED", "the transaction recorded no consumed attempt")
            lease_id, action, attempt_number = transaction.consumption
            self._consumed[lease_id] = (action, attempt_number)
            self._attempts[action] = (*self._attempts.get(action, ()), transaction.attempt)
            if transaction.idempotency_key is not None:
                self._keys.setdefault(action, transaction.idempotency_key)


class GovernedEmissionFence:
    """``EMISSION-FENCE = G-FRESHNESS and G-DISPATCH`` with the lease consumption and the
    DeliveryAttempt in one local transaction (ADD v1.3 :2851-2854, LLD v1.1 :69-81)."""

    def __init__(
        self,
        *,
        validator: LeaseValidator,
        ledger: InMemoryDispatchLedger,
        conditions: DispatchConditions,
        clock: TrustedClock,
    ) -> None:
        if not isinstance(validator, LeaseValidator):
            raise TypeError("validator must be the LeaseValidator")
        if not isinstance(ledger, InMemoryDispatchLedger):
            raise TypeError("ledger must be the dispatch ledger")
        if not isinstance(conditions, DispatchConditions):
            raise TypeError("conditions must implement DispatchConditions")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock must implement TrustedClock")
        self._validator = validator
        self._ledger = ledger
        self._conditions = conditions
        self._clock = clock

    @property
    def validator(self) -> LeaseValidator:
        return self._validator

    @property
    def ledger(self) -> InMemoryDispatchLedger:
        return self._ledger

    @property
    def conditions(self) -> DispatchConditions:
        return self._conditions

    def evaluate(
        self,
        *,
        package: c6_records.GatePackage,
        package_digest: str,
        command: c6_records.ActionCommand,
        lease: object,
        capability_id: str,
        effective_principal_id: str,
        delegation_ref: str,
        observe: Callable[[], CurrentValues],
    ) -> c6_records.DeliveryAttempt:
        """Evaluate the fence and record the PASSED DeliveryAttempt of the next emission attempt,
        or raise ``DispatchError`` with nothing consumed or recorded."""

        try:
            digest = c6_records.verify_gate_package(package, package_digest)
        except c6_records.C6RecordError as error:
            raise DispatchError("GATE_PACKAGE_DIGEST_MISMATCH", str(error)) from error
        if not isinstance(command, c6_records.ActionCommand):
            raise DispatchError("COMMAND_DIGEST_MISMATCH", "an ActionCommand is required")
        action = package.action_instance_id
        with self._ledger.transaction(action, stop_epoch=self._conditions.current_stop_epoch) as transaction:
            now = self._observe_and_check(package, digest, command, observe)
            expectation = self._expectation(
                package, digest, transaction, capability_id, effective_principal_id, delegation_ref, now
            )
            signed, _receipt = self._validator.consume(lease, expectation, state=transaction)
            attempt = c6_records.DeliveryAttempt.for_command(
                attempt_id=f"urn:ocor:delivery-attempt:{uuid.uuid4()}",
                command=command,
                package=package,
                package_digest=digest,
                emission_attempt=transaction.emission_attempt,
                lease_ref=signed.lease_id,
                fence_outcome="PASSED",
                attempted_at=now,
            )
            try:
                transaction.record(attempt, idempotency_key=command.idempotency_key)
            except Exception as error:
                raise DispatchError("FENCE_EVALUATION_FAILED", "the DeliveryAttempt was not recorded") from error
        return attempt

    def _expectation(
        self,
        package: c6_records.GatePackage,
        digest: str,
        transaction: _DispatchTransaction,
        capability_id: str,
        effective_principal_id: str,
        delegation_ref: str,
        now: datetime,
    ) -> LeaseExpectation:
        try:
            return LeaseExpectation(
                capability_id=capability_id,
                effective_principal_id=effective_principal_id,
                delegation_ref=delegation_ref,
                action_instance_id=package.action_instance_id,
                governed_context_digest=package.governed_context_digest,
                gate_package_digest=digest,
                stop_epoch=self._conditions.current_stop_epoch(),
                fencing_token=transaction.fencing_token,
                emission_attempt=transaction.emission_attempt,
                at=now,
            )
        except GovernanceFault as fault:
            raise DispatchError("LEASE_CONTEXT_MISMATCH", str(fault)) from fault
        except Exception as error:
            raise DispatchError("FENCE_EVALUATION_FAILED", "the lease expectation could not be formed") from error

    def _observe_and_check(
        self,
        package: c6_records.GatePackage,
        digest: str,
        command: c6_records.ActionCommand,
        observe: Callable[[], CurrentValues],
    ) -> datetime:
        conditions = self._conditions
        try:
            now = _require_aware(self._clock.now(), field="trusted now")
            current = observe()
            if not isinstance(current, CurrentValues):
                raise TypeError("the observation is not a CurrentValues")
            stop_active = conditions.emergency_stop_active()
            if type(stop_active) is not bool:
                raise TypeError("the emergency stop is answered as a boolean")
            stop_epoch = _stop_epoch(conditions.current_stop_epoch())
            audit = conditions.audit_append_available()
            closed = conditions.circuit_closed(package.adapter_binding_digest)
            conformant = conditions.adapter_conformant(package.adapter_binding_digest)
            conflict = conditions.unresolved_conflict(package.conflict_scope_digest)
            known_key = self._ledger.idempotency_key(package.action_instance_id)
        except Exception as error:
            # An evaluation error invalidates; it never degrades to a retry (ADD v1.3 :2854).
            raise DispatchError("FENCE_EVALUATION_FAILED", f"the fence could not be evaluated: {error}") from error

        # G-FRESHNESS: every frozen value coincides with the current one.
        for name in FRESHNESS_FIELDS:
            frozen = getattr(package, name)
            if frozen != getattr(current, name) or type(frozen) is not type(getattr(current, name)):
                raise DispatchError(f"STALE_{name.upper()}", f"{name} differs from the frozen GatePackage")
        if not package.valid_from <= now < package.valid_until:
            raise DispatchError("GATE_PACKAGE_WINDOW_CLOSED", "the GatePackage validity window is closed")
        if conflict is not False:
            raise DispatchError("CONFLICT_SCOPE_UNRESOLVED", "an unresolved effect has a conflicting ConflictScope")

        # G-DISPATCH: stop, stop epoch, audit, circuit breaker, adapter, command and key.
        if stop_active is not False:
            raise DispatchError("EMERGENCY_STOP_ACTIVE", "the emergency stop is active")
        if stop_epoch != package.stop_epoch:
            raise DispatchError("STOP_EPOCH_MISMATCH", "the stop epoch moved since the GatePackage was frozen")
        if audit is not True:
            raise DispatchError("AUDIT_UNAVAILABLE", "durable audit append is unavailable")
        if closed is not True:
            raise DispatchError("CIRCUIT_OPEN", "the circuit breaker of the adapter is open")
        if conformant is not True:
            raise DispatchError("ADAPTER_NOT_CONFORMANT", "the adapter binding is not conformant")
        if (
            not hmac.compare_digest(command.gate_package_digest, digest)
            or command.governed_context_digest != package.governed_context_digest
            or command.action_instance_id != package.action_instance_id
        ):
            raise DispatchError("COMMAND_DIGEST_MISMATCH", "the command is not bound to the frozen GatePackage")
        if known_key is not None and known_key != command.idempotency_key:
            raise DispatchError("IDEMPOTENCY_KEY_INVALID", "the action instance was sent with another idempotency key")
        if now >= command.deadline:
            raise DispatchError("COMMAND_DEADLINE_EXPIRED", "the command deadline expired")
        return now


def lease_from_mapping(value: Mapping[str, Any]) -> SignedCapabilityLease:
    """A signed lease from its wire mapping; the signature is verified by ``LeaseValidator``."""

    if not isinstance(value, Mapping) or set(value) != {"lease", "issuer_id", "keyid", "signature"}:
        raise DispatchError("LEASE_INVALID", "a signed lease has exactly lease, issuer_id, keyid and signature")
    lease_value = value["lease"]
    if not isinstance(lease_value, Mapping):
        raise DispatchError("LEASE_INVALID", "the lease record is not a mapping")
    try:
        lease = CapabilityLease.from_mapping(lease_value)
    except GovernanceFault as fault:
        raise DispatchError("LEASE_INVALID", str(fault)) from fault
    issuer_id, keyid, signature = value["issuer_id"], value["keyid"], value["signature"]
    if not all(isinstance(item, str) and item for item in (issuer_id, keyid, signature)):
        raise DispatchError("LEASE_INVALID", "issuer_id, keyid and signature are non-empty strings")
    return SignedCapabilityLease(lease=lease, issuer_id=issuer_id, keyid=keyid, signature=signature)
