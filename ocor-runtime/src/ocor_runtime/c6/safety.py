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
  stop atomically increments a monotonic ``stop_epoch``;
  ``guard_dispatch`` fails closed unless the system is
  ``NORMAL`` *and* the presented fencing epoch is exactly the current
  one -- a command fenced to any other epoch, older or from a prior
  stop/reset cycle, can never dispatch, so a reset never silently
  re-enables a lease issued before it. Reset requires dual control
  (two distinct, resolved human approvers).
  OCOR-DEV-REM-0054 (NCR-C6-010; ADD v1.3 :3343, :3351, :3360, LLD v1.1
  :328, Register NFR-047): only an active human Safety Officer of the
  registry activates the stop, naming the incident; every transition is
  a ``StopEpochRecord`` signed by the Emergency Control Plane and
  appended, compare-and-set, to the durable ``StopEpochPort``
  (``c6.adapters.postgres_stop`` on PostgreSQL); the state is read
  through ``StopEpochReader`` -- by G-DISPATCH, the C8 tool runtime and
  the break-glass -- never from the activating process; the reset also
  needs the ``RecoveryVerification`` of the stop's incident by one of its
  approvers.
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
  immediately, failing closed. OCOR-DEV-REM-0054 (NCR-C6-010; ADD v1.3
  :3347, LLD v1.1 :324, Register FR-139): the grant is a Delegation
  signed by the break-glass authority over every field, verified at
  every use, and its reason (the mandatory purpose) is a typed reason
  code, never free text.
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

import base64
import binascii
import re
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from ..audit import AuditError, AuditEvent, AuditPort, SealedAuditRecord, verify_audit_chain
from ..c1.signing import Ed25519SigningKey, dsse_pae, ed25519_verify
from ..c2_identity import IdentityRecord, IdentityRegistry
from ..c3_store import require_aware
from ..errors import OCORError
from ..kernel.canonical import canonical_bytes, format_utc_timestamp, parse_utc_timestamp
from ..kernel.governance import TrustedClock
from .human_gate import SignerKeyring

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


SAFETY_OFFICER_ROLE = "SAFETY_OFFICER"
STOP_EPOCH_PAYLOAD_TYPE = "application/vnd.ocor.c6.stop-epoch+json"
BREAK_GLASS_PAYLOAD_TYPE = "application/vnd.ocor.c6.break-glass-delegation+json"
_EVIDENCE_DIGEST = re.compile(r"urn:sha256:[0-9a-f]{64}")
_BREAK_GLASS_REASON = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
MAX_BREAK_GLASS_REASON_LENGTH = 64
_GENESIS_REASON = "genesis"


def _text(name: str, value: object, *, empty: bool = False) -> str:
    # Read without conversion: only a string is text.
    if not isinstance(value, str) or (not value and not empty):
        raise ValueError(f"{name} must be a{'' if empty else ' non-empty'} string")
    return value


def _count(name: str, value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class StopEvent:
    """One accepted transition of the emergency stop, as read from the signed stop epoch."""

    epoch: int
    status: StopStatus
    reason: str
    at: datetime
    actor: str = ""
    incident_ref: str = ""

    @property
    def activated_by(self) -> str:
        return self.actor


@dataclass(frozen=True, slots=True)
class StopEpochRecord:
    """The state of the Emergency Control Plane after one transition (ADD v1.3 :3351; LLD v1.1
    :328): a strictly increasing ``sequence`` per transition, the ``stop_epoch``, the FSM state,
    the principal that caused it, the reason and the incident; a reset also carries its two
    approvers and the content-addressed recovery evidence."""

    sequence: int
    epoch: int
    status: StopStatus
    actor: str
    reason: str
    incident_ref: str
    at: datetime
    recovery_evidence: str = ""
    approvers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _count("sequence", self.sequence)
        _count("epoch", self.epoch)
        if not isinstance(self.status, StopStatus):
            raise ValueError("status must be a StopStatus")
        _text("actor", self.actor)
        _text("reason", self.reason)
        _text("incident_ref", self.incident_ref, empty=True)
        require_aware(self.at, field="at")
        # Read without conversion: a falsy value that is not text is never "no evidence".
        evidence = _text("recovery_evidence", self.recovery_evidence, empty=True)
        if evidence and _EVIDENCE_DIGEST.fullmatch(evidence) is None:
            raise ValueError("recovery_evidence must be a urn:sha256 digest")
        if not isinstance(self.approvers, tuple) or any(not isinstance(item, str) or not item for item in self.approvers):
            raise ValueError("approvers must be a tuple of principal identifiers")

    def to_mapping(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "epoch": self.epoch,
            "status": self.status.value,
            "actor": self.actor,
            "reason": self.reason,
            "incident_ref": self.incident_ref,
            "at": format_utc_timestamp(self.at),
            "recovery_evidence": self.recovery_evidence,
            "approvers": list(self.approvers),
        }

    @classmethod
    def from_mapping(cls, value: object) -> StopEpochRecord:
        """A record read back from a store: shape checked without conversion."""

        if not isinstance(value, Mapping) or set(value) != _STOP_RECORD_FIELDS:
            raise ValueError("a stop epoch record has exactly the fields of StopEpochRecord")
        status = value["status"]
        approvers = value["approvers"]
        at = value["at"]
        if not isinstance(status, str) or status not in StopStatus.__members__:
            raise ValueError("unknown stop status")
        if not isinstance(approvers, list) or not isinstance(at, str):
            raise ValueError("malformed stop epoch record")
        return cls(
            sequence=value["sequence"],
            epoch=value["epoch"],
            status=StopStatus(status),
            actor=value["actor"],
            reason=value["reason"],
            incident_ref=value["incident_ref"],
            at=parse_utc_timestamp(at),
            recovery_evidence=value["recovery_evidence"],
            approvers=tuple(approvers),
        )

    def event(self) -> StopEvent:
        return StopEvent(
            epoch=self.epoch, status=self.status, reason=self.reason, at=self.at, actor=self.actor, incident_ref=self.incident_ref
        )


_STOP_RECORD_FIELDS = frozenset(
    {"sequence", "epoch", "status", "actor", "reason", "incident_ref", "at", "recovery_evidence", "approvers"}
)


@dataclass(frozen=True, slots=True)
class SignedStopEpoch:
    """A ``StopEpochRecord`` signed by the Emergency Control Plane (Ed25519 over the DSSE
    pre-authentication encoding of the issuer and the record)."""

    record: StopEpochRecord
    issuer_id: str
    keyid: str
    signature: str

    def __post_init__(self) -> None:
        if not isinstance(self.record, StopEpochRecord):
            raise ValueError("record must be a StopEpochRecord")
        _text("issuer_id", self.issuer_id)
        _text("keyid", self.keyid)
        # Empty only while it is being signed (sign_stop_epoch); verification refuses it.
        _text("signature", self.signature, empty=True)

    def signed_bytes(self) -> bytes:
        return dsse_pae(STOP_EPOCH_PAYLOAD_TYPE, canonical_bytes({"issuer_id": self.issuer_id, "record": self.record.to_mapping()}))

    def to_mapping(self) -> dict[str, object]:
        return {"record": self.record.to_mapping(), "issuer_id": self.issuer_id, "keyid": self.keyid, "signature": self.signature}

    @classmethod
    def from_mapping(cls, value: object) -> SignedStopEpoch:
        if not isinstance(value, Mapping) or set(value) != {"record", "issuer_id", "keyid", "signature"}:
            raise ValueError("a signed stop epoch has exactly record, issuer_id, keyid and signature")
        return cls(
            record=StopEpochRecord.from_mapping(value["record"]),
            issuer_id=_text("issuer_id", value["issuer_id"]),
            keyid=_text("keyid", value["keyid"]),
            signature=_text("signature", value["signature"]),
        )


def sign_stop_epoch(key: Ed25519SigningKey, *, issuer_id: str, keyid: str, record: StopEpochRecord) -> SignedStopEpoch:
    """The Emergency Control Plane's signature of a stop epoch record."""

    if not isinstance(key, Ed25519SigningKey):
        raise TypeError("key must be the Emergency Control Plane's Ed25519 signing key")
    if not isinstance(record, StopEpochRecord):
        raise TypeError("record must be a StopEpochRecord")
    unsigned = SignedStopEpoch(record=record, issuer_id=_text("issuer_id", issuer_id), keyid=_text("keyid", keyid), signature="")
    signature = base64.b64encode(key.sign(unsigned.signed_bytes())).decode("ascii")
    return replace(unsigned, signature=signature)


def _signature_holds(public_key: object, message: bytes, signature: object) -> bool:
    if not isinstance(public_key, bytes) or len(public_key) != 32 or not isinstance(signature, str) or not signature:
        return False
    try:
        raw = base64.b64decode(signature, validate=True)
    except (binascii.Error, ValueError):
        return False
    return ed25519_verify(public_key, message, raw)


def verify_stop_epoch(signed: object, *, keyring: SignerKeyring, issuer_id: str) -> StopEpochRecord:
    """The record of ``signed`` when the Emergency Control Plane ``issuer_id`` signed it under a
    key of ``keyring``; ``STOP_EPOCH_SIGNATURE_INVALID`` otherwise."""

    try:
        valid = (
            isinstance(signed, SignedStopEpoch)
            and isinstance(signed.record, StopEpochRecord)
            and signed.issuer_id == issuer_id
            and isinstance(signed.keyid, str)
            and _signature_holds(keyring.public_key(issuer_id, signed.keyid), signed.signed_bytes(), signed.signature)
        )
    except Exception as error:
        raise SafetyError("STOP_EPOCH_SIGNATURE_INVALID", "the stop epoch could not be verified") from error
    if not valid:
        raise SafetyError("STOP_EPOCH_SIGNATURE_INVALID", "the stop epoch is not signed by the Emergency Control Plane")
    assert isinstance(signed, SignedStopEpoch)
    return signed.record


@runtime_checkable
class StopEpochPort(Protocol):
    """The durable store of the signed stop epoch (NORMATIVE-CONFORMANCE-PLAN point 2 for NCP-U08:
    durable, read through a port, never an attribute of the activating process).

    ``append`` adds ``signed`` only when the latest stored record has ``expected_sequence``
    (``-1`` for an empty store) and ``signed`` is its successor; it returns whether it did, so
    two writers never both advance the same state. Records are never changed or removed."""

    def latest(self) -> SignedStopEpoch | None: ...

    def history(self) -> tuple[SignedStopEpoch, ...]: ...

    def append(self, signed: SignedStopEpoch, *, expected_sequence: int) -> bool: ...


class InMemoryStopEpochStore:
    """``StopEpochPort`` in memory, shared by every reader and controller holding it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[SignedStopEpoch] = []

    def latest(self) -> SignedStopEpoch | None:
        with self._lock:
            return self._records[-1] if self._records else None

    def history(self) -> tuple[SignedStopEpoch, ...]:
        with self._lock:
            return tuple(self._records)

    def append(self, signed: SignedStopEpoch, *, expected_sequence: int) -> bool:
        if not isinstance(signed, SignedStopEpoch):
            raise TypeError("the store keeps signed stop epochs only")
        if type(expected_sequence) is not int:
            raise TypeError("expected_sequence must be an integer")
        with self._lock:
            current = self._records[-1].record.sequence if self._records else -1
            if current != expected_sequence or signed.record.sequence != expected_sequence + 1:
                return False
            self._records.append(signed)
            return True


class StopEpochReader:
    """The signed stop epoch read through its durable port, as G-DISPATCH, the C8 tool runtime
    and the break-glass read it (ADD v1.3 :2852, :3351, :3360). Every read verifies the
    signature of the Emergency Control Plane; an empty, unreadable or unverifiable port is never
    taken for ``NORMAL``: the read fails closed."""

    def __init__(self, *, epochs: StopEpochPort, keyring: SignerKeyring, issuer_id: str) -> None:
        if not isinstance(epochs, StopEpochPort):
            raise TypeError("epochs must implement StopEpochPort")
        if not callable(getattr(keyring, "public_key", None)):
            raise TypeError("keyring must implement SignerKeyring")
        self._epochs = epochs
        self._keyring = keyring
        self._issuer_id = _text("issuer_id", issuer_id)
        self._verified: dict[tuple[str, str, bytes, bytes | None], StopEpochRecord] = {}
        self._cache_lock = threading.Lock()

    @property
    def issuer_id(self) -> str:
        return self._issuer_id

    def _verify(self, signed: object) -> StopEpochRecord:
        if not isinstance(signed, SignedStopEpoch):
            raise SafetyError("STOP_EPOCH_SIGNATURE_INVALID", "the port answered something other than a signed stop epoch")
        try:
            # The cache is bound to the key the keyring holds now: a key it no longer holds never
            # keeps a record verified.
            public_key = self._keyring.public_key(self._issuer_id, signed.keyid)
            key = (signed.keyid, signed.signature, signed.signed_bytes(), public_key)
        except Exception as error:
            raise SafetyError("STOP_EPOCH_SIGNATURE_INVALID", "the stop epoch is malformed") from error
        with self._cache_lock:
            cached = self._verified.get(key) if isinstance(public_key, bytes) else None
        if cached is not None:
            return cached
        record = verify_stop_epoch(signed, keyring=self._keyring, issuer_id=self._issuer_id)
        with self._cache_lock:
            if len(self._verified) > 256:
                self._verified.clear()
            self._verified[key] = record
        return record

    def current_signed(self) -> SignedStopEpoch:
        try:
            signed = self._epochs.latest()
        except SafetyError:
            raise
        except Exception as error:
            raise SafetyError("STOP_EPOCH_UNAVAILABLE", "the stop epoch port cannot be read") from error
        if signed is None:
            raise SafetyError("STOP_EPOCH_UNAVAILABLE", "no signed stop epoch has been published")
        self._verify(signed)
        assert isinstance(signed, SignedStopEpoch)
        return signed

    def current(self) -> StopEpochRecord:
        return self.current_signed().record

    def signed_history(self) -> tuple[SignedStopEpoch, ...]:
        try:
            history = self._epochs.history()
        except SafetyError:
            raise
        except Exception as error:
            raise SafetyError("STOP_EPOCH_UNAVAILABLE", "the stop epoch port cannot be read") from error
        if not isinstance(history, tuple) or not history:
            raise SafetyError("STOP_EPOCH_UNAVAILABLE", "no signed stop epoch has been published")
        for position, signed in enumerate(history):
            if self._verify(signed).sequence != position:
                raise SafetyError("STOP_EPOCH_HISTORY_INVALID", "the stop epoch history is not contiguous")
        return history

    @property
    def history(self) -> tuple[StopEvent, ...]:
        """The accepted transitions, oldest first (the genesis record is not a transition)."""
        return tuple(signed.record.event() for signed in self.signed_history()[1:])

    @property
    def status(self) -> StopStatus:
        return self.current().status

    @property
    def epoch(self) -> int:
        return self.current().epoch

    def current_stop_epoch(self) -> int:
        return self.current().epoch

    def emergency_stop_active(self) -> bool:
        return self.current().status is not StopStatus.NORMAL

    def guard_dispatch(self, *, fenced_epoch: int) -> None:
        record = self.current()
        if record.status is not StopStatus.NORMAL:
            raise SafetyError("SYSTEM_NOT_NORMAL", f"emergency stop is {record.status.value}, dispatch is blocked")
        if type(fenced_epoch) is not int or fenced_epoch != record.epoch:
            raise SafetyError("STOP_EPOCH_STALE", f"command fenced to epoch {fenced_epoch!r}, current epoch is {record.epoch}")


@dataclass(frozen=True, slots=True)
class RecoveryVerification:
    """The verification of incident and recovery a reset requires (LLD v1.1 :328): the incident
    of the stop, the reset approver who verified the recovery and the content-addressed evidence
    of the recovery."""

    incident_ref: str
    verified_by: str
    evidence_digest: str

    def __post_init__(self) -> None:
        _text("incident_ref", self.incident_ref)
        _text("verified_by", self.verified_by)
        if _EVIDENCE_DIGEST.fullmatch(_text("evidence_digest", self.evidence_digest)) is None:
            raise ValueError("evidence_digest must be a urn:sha256 digest of the recovery evidence")


class EmergencyStopController:
    """The Emergency Control Plane (ADD v1.3 :3343, :3351, :3360; LLD v1.1 :328): the approved
    ``NORMAL -> STOPPING -> STOPPED -> RESET_PENDING -> NORMAL`` machine whose every transition is
    a ``StopEpochRecord`` signed by the control plane and appended to the durable
    ``StopEpochPort``. The state is the latest signed record of the port, never an attribute of
    this object: any controller or ``StopEpochReader`` on the same port reads the same epoch, and
    of two concurrent transitions from the same state only one is appended.

    Activation is immediate and needs one authorised Safety Officer (an active human principal
    of the registry holding ``SAFETY_OFFICER``) and the incident; it increments the epoch. The
    reset needs two distinct resolved human approvers independent of the requester and the
    verification of the incident and of the recovery; its confirmation issues a new epoch, so a
    lease fenced to an earlier epoch is never re-enabled."""

    def __init__(
        self,
        *,
        epochs: StopEpochPort,
        identities: PrincipalDirectory,
        signing_key: Ed25519SigningKey,
        issuer_id: str,
        keyid: str,
        keyring: SignerKeyring,
    ) -> None:
        if not isinstance(signing_key, Ed25519SigningKey):
            raise TypeError("signing_key must be the Emergency Control Plane's Ed25519 key")
        if not callable(getattr(identities, "get", None)):
            raise TypeError("identities must be a PrincipalDirectory")
        self._reader = StopEpochReader(epochs=epochs, keyring=keyring, issuer_id=issuer_id)
        if keyring.public_key(issuer_id, _text("keyid", keyid)) != signing_key.public_key:
            raise ValueError("the keyring does not pin the Emergency Control Plane's key under its keyid")
        self._epochs = epochs
        self._identities = identities
        self._key = signing_key
        self._issuer_id = issuer_id
        self._keyid = keyid
        self._lock = threading.RLock()
        if epochs.latest() is None:
            genesis = StopEpochRecord(
                sequence=0, epoch=0, status=StopStatus.NORMAL, actor=issuer_id, reason=_GENESIS_REASON,
                incident_ref="", at=datetime.now(UTC),
            )
            epochs.append(self._sign(genesis), expected_sequence=-1)
        self._reader.current()

    def _sign(self, record: StopEpochRecord) -> SignedStopEpoch:
        return sign_stop_epoch(self._key, issuer_id=self._issuer_id, keyid=self._keyid, record=record)

    @property
    def reader(self) -> StopEpochReader:
        return self._reader

    @property
    def status(self) -> StopStatus:
        return self._reader.status

    @property
    def epoch(self) -> int:
        return self._reader.epoch

    @property
    def history(self) -> tuple[StopEvent, ...]:
        return self._reader.history

    def current_stop_epoch(self) -> int:
        return self._reader.current_stop_epoch()

    def emergency_stop_active(self) -> bool:
        return self._reader.emergency_stop_active()

    def _advance(self, expected: StopStatus, action: str, build: Callable[[StopEpochRecord], StopEpochRecord]) -> StopEvent:
        with self._lock:
            current = self._reader.current()
            if current.status is not expected:
                raise SafetyError("INVALID_STOP_TRANSITION", f"cannot {action} from {current.status.value}")
            record = build(current)
            if not self._epochs.append(self._sign(record), expected_sequence=current.sequence):
                raise SafetyError("INVALID_STOP_TRANSITION", f"cannot {action}: the stop epoch changed concurrently")
            return record.event()

    def _require_safety_officer(self, activator: object) -> str:
        refused = SafetyError("STOP_ACTIVATOR_UNAUTHORIZED", "the stop is activated only by an authorised Safety Officer")
        if not isinstance(activator, str) or not activator:
            raise refused
        try:
            principal = _read_principal(self._identities, activator)
        except SafetyError as error:
            raise refused from error
        if principal is None or principal.kind != "HUMAN" or not principal.active or SAFETY_OFFICER_ROLE not in principal.roles:
            raise refused
        return activator

    def activate(self, *, activator: str, reason: str, incident_ref: str, at: datetime) -> StopEvent:
        instant = require_aware(at, field="at")
        if not isinstance(reason, str) or not reason:
            raise ValueError("an emergency stop requires a reason")
        if not isinstance(incident_ref, str) or not incident_ref:
            raise ValueError("an emergency stop names its incident")
        officer = self._require_safety_officer(activator)
        return self._advance(
            StopStatus.NORMAL,
            "activate stop",
            lambda current: StopEpochRecord(
                sequence=current.sequence + 1, epoch=current.epoch + 1, status=StopStatus.STOPPING, actor=officer,
                reason=reason, incident_ref=incident_ref, at=instant,
            ),
        )

    def finish_draining(self, *, at: datetime) -> StopEvent:
        instant = require_aware(at, field="at")
        return self._advance(
            StopStatus.STOPPING,
            "finish draining",
            lambda current: replace(current, sequence=current.sequence + 1, status=StopStatus.STOPPED, actor=self._issuer_id,
                                    reason="drain complete", at=instant),
        )

    def request_reset(
        self,
        *,
        approvers: tuple[str, str],
        identities: IdentityRegistry,
        requester: str,
        recovery: RecoveryVerification | None,
        at: datetime | None = None,
    ) -> StopEvent:
        # No temporal window is specified for reset; its event timestamp comes
        # from the local boundary UTC clock, never the compatibility ``at``.
        from .human_gate import _active_human_roles

        instant = datetime.now(UTC)
        dual_control = SafetyError("RESET_REQUIRES_DUAL_CONTROL", "reset requires two distinct human approvers, independent of the requester")
        # Read without conversion: a tuple of two principal identifiers and a principal identifier.
        if (
            not isinstance(approvers, tuple)
            or any(not isinstance(item, str) or not item for item in approvers)
            or not isinstance(requester, str)
        ):
            raise dual_control
        distinct = set(approvers)
        if len(approvers) != 2 or len(distinct) != 2 or not requester or requester in distinct:
            raise dual_control
        with self._lock:
            current = self._reader.current()
            if current.status is not StopStatus.STOPPED:
                raise SafetyError("INVALID_STOP_TRANSITION", f"cannot request reset from {current.status.value}")
            # Fresh authority reads immediately before the state transition.
            # Request, signature and grant cannot set registry attributes.
            for principal in sorted(distinct):
                try:
                    roles = _active_human_roles(identities.get(principal))
                except Exception as error:
                    raise SafetyError("RESET_REQUIRES_DUAL_CONTROL", "a reset approver cannot be read from the registry") from error
                if roles is None:
                    raise SafetyError("RESET_REQUIRES_DUAL_CONTROL", "reset approver is not a resolved active human with valid attributes")
            # LLD v1.1 :328: the reset verifies the incident and the recovery.
            if (
                not isinstance(recovery, RecoveryVerification)
                or recovery.incident_ref != current.incident_ref
                or recovery.verified_by not in distinct
            ):
                raise SafetyError(
                    "RESET_RECOVERY_NOT_VERIFIED",
                    "the reset needs the recovery of the stop's incident verified by one of its approvers",
                )
            evidence = recovery.evidence_digest
            return self._advance(
                StopStatus.STOPPED,
                "request reset",
                lambda state: replace(state, sequence=state.sequence + 1, status=StopStatus.RESET_PENDING, actor=requester,
                                      reason="reset requested", at=instant, recovery_evidence=evidence,
                                      approvers=tuple(sorted(distinct))),
            )

    def confirm_reset(self, *, at: datetime) -> StopEvent:
        instant = require_aware(at, field="at")
        # A brand-new epoch: never re-enables a lease or command fenced to the
        # pre-stop epoch, even now that the system is NORMAL again.
        return self._advance(
            StopStatus.RESET_PENDING,
            "confirm reset",
            lambda current: replace(current, sequence=current.sequence + 1, epoch=current.epoch + 1, status=StopStatus.NORMAL,
                                    actor=self._issuer_id, reason="reset confirmed, new epoch issued", at=instant),
        )

    def guard_dispatch(self, *, fenced_epoch: int) -> None:
        self._reader.guard_dispatch(fenced_epoch=fenced_epoch)


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
    issuer_id: str = ""
    keyid: str = ""
    signature: str = ""

    def __post_init__(self) -> None:
        require_aware(self.granted_at, field="granted_at")
        # Read without conversion: text is a string, the capabilities a set of names (a string is
        # never split into characters), the approvers a tuple and the TTL a duration.
        for name in ("grant_id", "requester", "reason", "incident_ref", "scope", "domain", "issuer_id", "keyid", "signature"):
            _text(name, getattr(self, name), empty=True)
        if not isinstance(self.capabilities, (set, frozenset)):
            raise ValueError("the capabilities of a BreakGlassGrant are a set of names")
        if not isinstance(self.approvers, tuple) or any(not isinstance(item, str) for item in self.approvers):
            raise ValueError("the approvers of a BreakGlassGrant are a tuple of principal identifiers")
        if not isinstance(self.ttl, timedelta):
            raise ValueError("the ttl of a BreakGlassGrant is a duration")
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

    def delegation_mapping(self) -> dict[str, object]:
        """The exceptional Delegation the break-glass authority signs (ADD v1.3 :3347): every field
        of the grant and the signer, so any change invalidates the signature."""

        return {
            "grant_id": self.grant_id,
            "requester": self.requester,
            "reason": self.reason,
            "incident_ref": self.incident_ref,
            "scope": self.scope,
            "domain": self.domain,
            "capabilities": sorted(self.capabilities),
            "approvers": list(self.approvers),
            "granted_at": format_utc_timestamp(self.granted_at),
            "ttl_microseconds": self.ttl // timedelta(microseconds=1),
            "issuer_id": self.issuer_id,
            "keyid": self.keyid,
        }

    def signed_bytes(self) -> bytes:
        return dsse_pae(BREAK_GLASS_PAYLOAD_TYPE, canonical_bytes(self.delegation_mapping()))


def sign_break_glass_grant(key: Ed25519SigningKey, *, issuer_id: str, keyid: str, grant: BreakGlassGrant) -> BreakGlassGrant:
    """The break-glass authority's signature of a grant: the signed Delegation of ADD v1.3 :3347."""

    if not isinstance(key, Ed25519SigningKey):
        raise TypeError("key must be the break-glass authority's Ed25519 signing key")
    if not isinstance(grant, BreakGlassGrant):
        raise TypeError("grant must be a BreakGlassGrant")
    unsigned = replace(grant, issuer_id=_text("issuer_id", issuer_id), keyid=_text("keyid", keyid), signature="")
    return replace(unsigned, signature=base64.b64encode(key.sign(unsigned.signed_bytes())).decode("ascii"))


def _grant_signature_holds(grant: object, issuer_id: str, public_key: object) -> bool:
    return (
        isinstance(grant, BreakGlassGrant)
        and grant.issuer_id == issuer_id
        and _signature_holds(public_key, grant.signed_bytes(), grant.signature)
    )


def verify_break_glass_grant(grant: object, *, keyring: SignerKeyring, issuer_id: str) -> None:
    """``BREAK_GLASS_SIGNATURE_INVALID`` unless ``grant`` is a Delegation signed by the break-glass
    authority ``issuer_id`` under a key of ``keyring``."""

    try:
        valid = isinstance(grant, BreakGlassGrant) and _grant_signature_holds(
            grant, issuer_id, keyring.public_key(issuer_id, grant.keyid)
        )
    except Exception as error:
        raise SafetyError("BREAK_GLASS_SIGNATURE_INVALID", "the break-glass delegation could not be verified") from error
    if not valid:
        raise SafetyError("BREAK_GLASS_SIGNATURE_INVALID", "the break-glass delegation is not signed by the break-glass authority")


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
    registry record; absent or malformed attributes fail closed, and so
    do a registry that cannot be read and a record that is not a
    registry record."""

    try:
        record = directory.get(canonical_id)
    except Exception as error:
        raise SafetyError("BREAK_GLASS_PRINCIPAL_ATTRIBUTES_INVALID", f"{canonical_id!r} cannot be read from the registry") from error
    if record is None:
        return None
    if not isinstance(record, IdentityRecord) or not isinstance(record.attributes, Mapping):
        raise SafetyError("BREAK_GLASS_PRINCIPAL_ATTRIBUTES_INVALID", f"{canonical_id!r} is not a registry record")
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
        stop: EmergencyStopController | StopEpochReader,
        clock: TrustedClock,
        audit: BreakGlassAuditSink,
        alerts: BreakGlassAlertSink,
        signing_key: Ed25519SigningKey,
        issuer_id: str,
        keyid: str,
    ) -> None:
        if not isinstance(stop, (EmergencyStopController, StopEpochReader)):
            raise TypeError("stop must be the Emergency Control Plane or a reader of its signed stop epoch")
        if not isinstance(signing_key, Ed25519SigningKey):
            raise TypeError("signing_key must be the break-glass authority's Ed25519 key")
        self._key = signing_key
        self._issuer_id = _text("issuer_id", issuer_id)
        self._keyid = _text("keyid", keyid)
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
        request = {
            "grant_id": grant_id,
            "requester": requester,
            "approvers": list(approvers) if isinstance(approvers, tuple) else approvers,
            "domain": domain,
        }
        with self._lock:
            try:
                # Read without conversion: a string is never split into capabilities or approvers.
                if (
                    any(not isinstance(value, str) for value in (grant_id, requester, incident_ref, scope, domain))
                    or not isinstance(capabilities, (set, frozenset))
                    or any(not isinstance(name, str) or not name for name in capabilities)
                    or not isinstance(approvers, tuple)
                    or any(not isinstance(approver, str) or not approver for approver in approvers)
                ):
                    raise SafetyError(
                        "BREAK_GLASS_GRANT_INVALID",
                        "grant id, requester, incident, scope and domain are strings, capabilities a set of names, "
                        "approvers a tuple of principals",
                    )
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
                self._validate_principals(requester, approvers, domain)
                # LLD v1.1 :324 typed reason, the purpose of ADD v1.3 :3347: a reason code, never free text.
                if (
                    not isinstance(reason, str)
                    or len(reason) > MAX_BREAK_GLASS_REASON_LENGTH
                    or _BREAK_GLASS_REASON.fullmatch(reason) is None
                ):
                    raise SafetyError(
                        "BREAK_GLASS_REASON_UNTYPED", "the break-glass reason is a typed reason code (lower-case, hyphen-separated)"
                    )
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
                issued = sign_break_glass_grant(self._key, issuer_id=self._issuer_id, keyid=self._keyid, grant=issued)
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
        if not isinstance(grant, BreakGlassGrant):
            raise SafetyError("BREAK_GLASS_GRANT_NOT_ISSUED", "only a grant issued by this controller is honoured")
        if self._issued.get(grant.grant_id) != grant:
            raise SafetyError("BREAK_GLASS_GRANT_NOT_ISSUED", f"grant {grant.grant_id!r} was not issued by this controller or was altered")
        if grant.keyid != self._keyid or not _grant_signature_holds(grant, self._issuer_id, self._key.public_key):
            raise SafetyError("BREAK_GLASS_SIGNATURE_INVALID", f"grant {grant.grant_id!r} is not a delegation signed by this authority")

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
                if not isinstance(capability, str) or not capability:
                    raise SafetyError("BREAK_GLASS_CAPABILITY_NOT_GRANTED", "a break-glass use names one capability")
                if capability in FORBIDDEN_BREAK_GLASS_CAPABILITIES:
                    raise SafetyError("BREAK_GLASS_FORBIDDEN_CAPABILITY", f"break-glass can never authorize {capability!r}")
                if capability not in grant.capabilities:
                    raise SafetyError("BREAK_GLASS_CAPABILITY_NOT_GRANTED", f"{capability!r} is not a capability named in grant {grant.grant_id!r}")
                if self._stop.status is not StopStatus.NORMAL:
                    raise SafetyError("BREAK_GLASS_STOP_ACTIVE", "break-glass can never override an active emergency stop")
                if not isinstance(review_ref, str) or not review_ref:
                    raise SafetyError("BREAK_GLASS_REVIEW_REQUIRED", "every break-glass use requires a mandatory review reference")
                self._validate_principals(grant.requester, grant.approvers, grant.domain)
            except SafetyError as error:
                raise self._refuse(
                    "BREAK_GLASS_USE_DENIED", None, instant, error,
                    grant_id=grant.grant_id if isinstance(grant, BreakGlassGrant) else None, capability=capability, review_ref=review_ref,
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
        if not isinstance(command_id, str) or not command_id:
            raise SafetyError("RECONCILIATION_RECORD_INVALID", "command_id must be a non-empty string")
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
        if any(not isinstance(sealed, SealedAuditRecord) or not isinstance(sealed.record, Mapping) for sealed in chain):
            raise SafetyError("RECONCILIATION_AUDIT_INVALID", "the audit chain holds an element that is not a sealed record")
        try:
            verify_audit_chain(chain, public_keys)
        except AuditError as error:
            raise SafetyError("RECONCILIATION_AUDIT_INVALID", f"the audit chain does not verify: {error.reason_code}") from error
        except Exception as error:
            raise SafetyError(
                "RECONCILIATION_AUDIT_INVALID", f"the audit chain does not verify: {type(error).__name__}"
            ) from error
        restored = cls(audit=audit, actor=actor)
        with restored._lock:
            for sealed in chain:
                if sealed.record.get("event_type") != RECONCILIATION_EVENT:
                    continue
                record = _restored_record(sealed, actor=actor)
                previous = restored._records.get(record.command_id)
                if sealed.record["detail"]["previous_status"] != (None if previous is None else previous.status.value):
                    raise SafetyError(
                        "RECONCILIATION_AUDIT_INVALID", f"record {sealed.sequence} does not follow the replayed status"
                    )
                if record.status not in _RECONCILIATION_TRANSITIONS.get(None if previous is None else previous.status, frozenset()):
                    raise SafetyError(
                        "RECONCILIATION_AUDIT_INVALID", f"record {sealed.sequence} is not a reconciliation transition"
                    )
                restored._records[record.command_id] = record
        return restored


def _restored_record(sealed: SealedAuditRecord, *, actor: str) -> ReconciliationRecord:
    def invalid(message: str) -> SafetyError:
        return SafetyError("RECONCILIATION_AUDIT_INVALID", f"record {sealed.sequence}: {message}")

    stored = sealed.record
    if stored.get("actor") != actor:
        raise invalid("the reconciliation record was not written by the reconciler")
    detail = stored.get("detail")
    if not isinstance(detail, Mapping) or set(detail) != _DETAIL_FIELDS:
        raise invalid("the reconciliation detail does not have its fields")
    status_value, command_id = detail["status"], stored.get("resource")
    if stored.get("correlation_id") != command_id or stored.get("outcome") != "PERMITTED":
        raise invalid("the correlation or the outcome is not that of a reconciliation record")
    previous_value = detail["previous_status"]
    if previous_value is not None and (
        not isinstance(previous_value, str) or previous_value not in {item.value for item in OutcomeStatus}
    ):
        raise invalid("the previous status is outside the closed set")
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
