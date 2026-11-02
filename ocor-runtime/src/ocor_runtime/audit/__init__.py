"""The single OCOR audit port: append-only, hash-linked and signed audit records.

Realises the Audit control of ADD v1.3 :3143 ("Record append-only, hash-linked e firmato
per accessi, Policy, Delegation, Approval, Decision, Action, break-glass e
amministrazione"): every component that writes audit (C2 since NCP-U03; NCP-U07 and
NCP-U08 by NORMATIVE-CONFORMANCE-PLAN point 2) appends through ``AuditPort``. A record
carries the FR-134 fields (Register :302: actor, time, resource, reason, authority,
correlation) and, when one exists, the ``GovernedContext`` and its digest (ADD v1.3
:393). Each record is linked to its predecessor (``record_hash`` over the previous hash
and the record, RFC 8785 + SHA-256, LLD v1.1 :37) and signed with Ed25519 over the DSSE
pre-authentication encoding of the link. An append that cannot be made durable raises
``AuditUnavailable``: callers fail closed.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ..c1.signing import Ed25519SigningKey, dsse_pae, ed25519_verify
from ..kernel.canonical import UTC_TIMESTAMP, canonical_bytes, canonical_digest, format_utc_timestamp

GENESIS_HASH = "urn:sha256:" + "0" * 64
PAYLOAD_TYPE = "application/vnd.ocor.audit-record+json"
DIGEST = re.compile(r"urn:sha256:[0-9a-f]{64}")
OUTCOMES = frozenset({"DENIED", "REJECTED", "PERMITTED", "FAILED"})
TEXT_FIELDS = ("event_type", "actor", "resource", "reason_code", "authority_ref", "correlation_id")
RECORD_FIELDS = frozenset({*TEXT_FIELDS, "occurred_at", "outcome", "detail"})
CONTEXT_FIELDS = frozenset({"governed_context", "governed_context_digest"})


class AuditError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


class AuditUnavailable(AuditError):
    """The record could not be durably appended (fail-closed for the caller)."""

    def __init__(self, message: str) -> None:
        super().__init__("CONTROL_PLANE_UNAVAILABLE", message)


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise AuditError("AUDIT_RECORD_INVALID", f"{name} is required")
    return value


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An auditable event before sealing (FR-134 catalogue fields)."""

    event_type: str
    actor: str
    occurred_at: datetime
    resource: str
    reason_code: str
    authority_ref: str
    correlation_id: str
    outcome: str
    governed_context: Mapping[str, Any] | None = None
    governed_context_digest: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("event_type", "actor", "resource", "reason_code", "authority_ref", "correlation_id"):
            _text(name, getattr(self, name))
        if self.outcome not in OUTCOMES:
            raise AuditError("AUDIT_RECORD_INVALID", "outcome is outside the closed set")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise AuditError("AUDIT_RECORD_INVALID", "occurred_at must be timezone-aware")
        if (self.governed_context is None) != (self.governed_context_digest is None):
            raise AuditError("AUDIT_RECORD_INVALID", "governed context and its digest go together")
        if self.governed_context_digest is not None:
            if DIGEST.fullmatch(self.governed_context_digest) is None:
                raise AuditError("AUDIT_RECORD_INVALID", "governed_context_digest is not a SHA-256 URN")
            if canonical_digest(dict(self.governed_context or {})) != self.governed_context_digest:
                raise AuditError("AUDIT_RECORD_INVALID", "governed_context_digest does not match the context")

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "event_type": self.event_type,
            "actor": self.actor,
            "occurred_at": format_utc_timestamp(self.occurred_at),
            "resource": self.resource,
            "reason_code": self.reason_code,
            "authority_ref": self.authority_ref,
            "correlation_id": self.correlation_id,
            "outcome": self.outcome,
            "detail": dict(self.detail),
        }
        if self.governed_context is not None:
            record["governed_context"] = dict(self.governed_context)
            record["governed_context_digest"] = self.governed_context_digest
        # the record must be canonicalisable: RFC 8785 rejects what cannot be signed.
        canonical_bytes(record)
        return record


@dataclass(frozen=True, slots=True)
class SealedAuditRecord:
    sequence: int
    record: Mapping[str, Any]
    previous_hash: str
    record_hash: str
    signature: str
    keyid: str


def validate_record(value: object) -> dict[str, Any]:
    """Check a record read back from storage against the shape ``AuditEvent.to_record``
    writes, without conversion; anything else is ``AUDIT_RECORD_INVALID``."""

    if not isinstance(value, dict) or not RECORD_FIELDS <= set(value) <= RECORD_FIELDS | CONTEXT_FIELDS:
        raise AuditError("AUDIT_RECORD_INVALID", "the stored record does not have the audit record fields")
    for name in TEXT_FIELDS:
        _text(name, value[name])
    if value["outcome"] not in OUTCOMES:
        raise AuditError("AUDIT_RECORD_INVALID", "the stored outcome is outside the closed set")
    if not isinstance(value["occurred_at"], str) or UTC_TIMESTAMP.fullmatch(value["occurred_at"]) is None:
        raise AuditError("AUDIT_RECORD_INVALID", "the stored time is not RFC 3339 UTC")
    if not isinstance(value["detail"], dict):
        raise AuditError("AUDIT_RECORD_INVALID", "the stored detail is not an object")
    if CONTEXT_FIELDS & set(value):
        context, digest = value.get("governed_context"), value.get("governed_context_digest")
        if not isinstance(context, dict) or not isinstance(digest, str) or DIGEST.fullmatch(digest) is None:
            raise AuditError("AUDIT_RECORD_INVALID", "the stored governed context is malformed")
        if canonical_digest(context) != digest:
            raise AuditError("AUDIT_RECORD_INVALID", "the stored governed context does not match its digest")
    return value


def link_hash(previous_hash: str, record: Mapping[str, Any]) -> str:
    return canonical_digest({"previous_hash": previous_hash, "record": dict(record)})


def link_payload(previous_hash: str, record: Mapping[str, Any], record_hash: str) -> bytes:
    body = canonical_bytes({"previous_hash": previous_hash, "record": dict(record), "record_hash": record_hash})
    return dsse_pae(PAYLOAD_TYPE, body)


def signing_payload(sealed: SealedAuditRecord) -> bytes:
    """The exact bytes the Ed25519 signature of a sealed record covers."""
    return link_payload(sealed.previous_hash, sealed.record, sealed.record_hash)


class AuditSigner:
    """Ed25519 (RFC 8032) signer of audit links; the key never leaves this object."""

    def __init__(self, *, key: Ed25519SigningKey, keyid: str) -> None:
        self._key = key
        self.keyid = _text("keyid", keyid)

    def __repr__(self) -> str:
        return f"AuditSigner(keyid={self.keyid!r})"

    @property
    def public_key(self) -> bytes:
        return self._key.public_key

    def sign(self, payload: bytes) -> str:
        return base64.b64encode(self._key.sign(payload)).decode("ascii")


def verify_audit_chain(records: Iterable[SealedAuditRecord], public_keys: Mapping[str, bytes]) -> int:
    """Verify links and signatures from genesis; return the number of verified records."""

    previous = GENESIS_HASH
    count = 0
    for sealed in records:
        if sealed.previous_hash != previous:
            raise AuditError("AUDIT_CHAIN_BROKEN", f"record {sealed.sequence} does not link to its predecessor")
        if link_hash(previous, sealed.record) != sealed.record_hash:
            raise AuditError("AUDIT_CHAIN_BROKEN", f"record {sealed.sequence} hash does not match its content")
        key = public_keys.get(sealed.keyid)
        if key is None:
            raise AuditError("AUDIT_SIGNATURE_INVALID", f"record {sealed.sequence} is signed by an unknown key")
        try:
            signature = base64.b64decode(sealed.signature, validate=True)
        except ValueError as exc:
            raise AuditError("AUDIT_SIGNATURE_INVALID", f"record {sealed.sequence} signature is malformed") from exc
        if not ed25519_verify(key, signing_payload(sealed), signature):
            raise AuditError("AUDIT_SIGNATURE_INVALID", f"record {sealed.sequence} signature does not verify")
        previous = sealed.record_hash
        count += 1
    return count


@runtime_checkable
class AuditPort(Protocol):
    def append(self, event: AuditEvent) -> SealedAuditRecord: ...


from .adapters.postgres import PostgresAuditLog  # noqa: E402 -- the adapter depends on the types above

__all__ = [
    "GENESIS_HASH",
    "AuditError",
    "AuditEvent",
    "AuditPort",
    "AuditSigner",
    "AuditUnavailable",
    "PostgresAuditLog",
    "SealedAuditRecord",
    "link_hash",
    "signing_payload",
    "validate_record",
    "verify_audit_chain",
]
