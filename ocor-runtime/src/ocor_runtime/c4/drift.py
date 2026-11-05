"""C4 drift ports and signed projection checkpoints (LLD v1.1 :146, package ``ocor.c4.drift``).

OCOR-DEV-REM-0052 (NCP-U05, NCR-C4-002). LLD v1.1 :148: ``ProjectionDriftDetector`` rebuilds a
sample from the canonical commit, compares the semantic digest, quarantines the divergent
projection and prevents ``EXACT_AT_COMMIT``; rebuild uses a signed checkpoint and a bounded
replay; no projection is authoritative.

* ``ProjectionQuarantinePort``: the quarantine is durable and kept outside the projection store
  and outside the process, so the projection enforces it on its own read path for every
  instance (a quarantined aggregate is ``PROJECTION_NOT_READY``);
* ``CheckpointStorePort``: signed checkpoints, append-only, outside the projection store, so a
  deleted projection can be rebuilt (Register FR-065 :189);
* ``SignedProjectionCheckpoint``: a DSSE v1 envelope over the RFC 8785 bytes of the checkpoint
  body, signed with Ed25519 (``ocor_runtime.c1.signing``); only a checkpoint that verifies under
  a trusted key and is well formed is ever used (``verify_checkpoint``).

Neither store is authoritative for the projected facts: the canonical TerminusDB store is.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ..c1.signing import Ed25519SigningKey, dsse_pae, ed25519_verify
from ..kernel.canonical import UTC_TIMESTAMP, canonical_bytes, parse_i_json, parse_utc_timestamp

CHECKPOINT_FORMAT = "ocor.c4.projection-checkpoint/1"
CHECKPOINT_PAYLOAD_TYPE = "application/vnd.ocor.c4.projection-checkpoint+json"
DIGEST = re.compile(r"urn:sha256:[0-9a-f]{64}")


class CheckpointError(ValueError):
    """A checkpoint that does not verify or is not well formed (``CHECKPOINT_INVALID``)."""

    reason_code = "CHECKPOINT_INVALID"


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """A projected aggregate whose served digest diverged from the canonical commit."""

    store_id: str
    aggregate_ref: str
    canonical_commit: str
    expected_digest: str
    served_digest: str
    quarantined_at: datetime


@runtime_checkable
class ProjectionQuarantinePort(Protocol):
    def quarantine(self, store_id: str, aggregate_ref: str, *, canonical_commit: str, expected_digest: str,
                   served_digest: str, at: datetime) -> QuarantineRecord: ...

    def release(self, store_id: str, aggregate_ref: str) -> None: ...

    def active(self, store_id: str, aggregate_ref: str) -> QuarantineRecord | None: ...

    def clear_quarantine(self, store_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class CheckpointEntry:
    """One projected aggregate at the checkpoint: its canonical key, its commit and payload, and
    the position of that commit on the branch."""

    tenant_id: str
    aggregate_type: str
    aggregate_ref: str
    commit_id: str
    sequence: int
    payload: str

    def to_mapping(self) -> dict[str, Any]:
        return {"tenant_id": self.tenant_id, "aggregate_type": self.aggregate_type,
                "aggregate_ref": self.aggregate_ref, "commit_id": self.commit_id, "sequence": self.sequence,
                "payload": self.payload}


@dataclass(frozen=True, slots=True)
class CheckpointBody:
    store_id: str
    branch: str
    release_digest: str
    watermark: str
    sequence: int
    created_at: str
    entries: tuple[CheckpointEntry, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {"checkpoint_format": CHECKPOINT_FORMAT, "store_id": self.store_id, "branch": self.branch,
                "release_digest": self.release_digest, "watermark": self.watermark, "sequence": self.sequence,
                "created_at": self.created_at, "entries": [entry.to_mapping() for entry in self.entries]}


@dataclass(frozen=True, slots=True)
class SignedProjectionCheckpoint:
    """The DSSE envelope of a checkpoint: payload bytes, signing key id and Ed25519 signature."""

    payload: bytes
    key_id: str
    signature: bytes

    @property
    def watermark(self) -> str | None:
        """The watermark the payload declares, for reporting only: never trusted unverified."""
        try:
            body = json.loads(self.payload.decode("utf-8"))
        except (ValueError, RecursionError):
            return None
        value = body.get("watermark") if isinstance(body, dict) else None
        return value if isinstance(value, str) else None


@runtime_checkable
class CheckpointStorePort(Protocol):
    def save_checkpoint(self, store_id: str, checkpoint: SignedProjectionCheckpoint, *, at: datetime) -> None: ...

    def latest_checkpoint(self, store_id: str) -> SignedProjectionCheckpoint | None: ...


def sign_checkpoint(body: CheckpointBody, *, key: Ed25519SigningKey, key_id: str) -> SignedProjectionCheckpoint:
    payload = canonical_bytes(body.to_mapping())
    return SignedProjectionCheckpoint(payload=payload, key_id=key_id,
                                      signature=key.sign(dsse_pae(CHECKPOINT_PAYLOAD_TYPE, payload)))


def _text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise CheckpointError(f"the checkpoint has a malformed {what}")
    return value


def _position(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CheckpointError(f"the checkpoint has a malformed {what}")
    return value


def _instant(value: object) -> str:
    """The creation instant in the canonical RFC 3339 UTC form the checkpoint is signed with."""
    if not isinstance(value, str) or UTC_TIMESTAMP.fullmatch(value) is None:
        raise CheckpointError("the checkpoint has a malformed created_at")
    try:
        parse_utc_timestamp(value)
    except ValueError as exc:
        raise CheckpointError("the checkpoint has a malformed created_at") from exc
    return value


def _entry(value: object) -> CheckpointEntry:
    if not isinstance(value, Mapping) or set(value) != {"tenant_id", "aggregate_type", "aggregate_ref", "commit_id",
                                                         "sequence", "payload"}:
        raise CheckpointError("the checkpoint has a malformed entry")
    return CheckpointEntry(
        tenant_id=_text(value["tenant_id"], "tenant_id"), aggregate_type=_text(value["aggregate_type"], "aggregate_type"),
        aggregate_ref=_text(value["aggregate_ref"], "aggregate_ref"), commit_id=_text(value["commit_id"], "commit_id"),
        sequence=_position(value["sequence"], "entry sequence"), payload=_text(value["payload"], "payload"))


def verify_checkpoint(checkpoint: object, trusted_keys: Mapping[str, bytes]) -> CheckpointBody:
    """The body of a checkpoint signed by a trusted key over its exact canonical bytes; anything
    else -- unknown key, bad signature, non-canonical or malformed body -- is ``CheckpointError``."""
    if not isinstance(checkpoint, SignedProjectionCheckpoint):
        raise CheckpointError("not a signed projection checkpoint")
    if not isinstance(checkpoint.payload, bytes) or not isinstance(checkpoint.signature, bytes):
        raise CheckpointError("the checkpoint envelope is malformed")
    public_key = trusted_keys.get(checkpoint.key_id) if isinstance(checkpoint.key_id, str) else None
    if not isinstance(public_key, bytes):
        raise CheckpointError("the checkpoint is not signed by a trusted key")
    if not ed25519_verify(public_key, dsse_pae(CHECKPOINT_PAYLOAD_TYPE, checkpoint.payload), checkpoint.signature):
        raise CheckpointError("the checkpoint signature does not verify")
    try:
        # I-JSON (no duplicate key, no non-finite number) of a depth the decoder can read, whose
        # canonical bytes are exactly the signed ones
        body = parse_i_json(checkpoint.payload.decode("utf-8"))
        canonical = isinstance(body, dict) and canonical_bytes(body) == checkpoint.payload
    except (ValueError, RecursionError) as exc:
        raise CheckpointError("the checkpoint payload is not canonical UTF-8 I-JSON") from exc
    if not canonical:
        raise CheckpointError("the checkpoint payload is not a canonical object")
    if set(body) != {"checkpoint_format", "store_id", "branch", "release_digest", "watermark", "sequence",
                     "created_at", "entries"} or body["checkpoint_format"] != CHECKPOINT_FORMAT:
        raise CheckpointError("the checkpoint payload is not a projection checkpoint")
    release = _text(body["release_digest"], "release_digest")
    if DIGEST.fullmatch(release) is None:
        raise CheckpointError("the checkpoint has a malformed release_digest")
    entries = body["entries"]
    if not isinstance(entries, list) or not entries:
        raise CheckpointError("the checkpoint has no entries")
    parsed = tuple(_entry(entry) for entry in entries)
    if len({entry.aggregate_ref for entry in parsed}) != len(parsed) or len({e.sequence for e in parsed}) != len(parsed):
        raise CheckpointError("the checkpoint entries are not distinct")
    result = CheckpointBody(
        store_id=_text(body["store_id"], "store_id"), branch=_text(body["branch"], "branch"), release_digest=release,
        watermark=_text(body["watermark"], "watermark"), sequence=_position(body["sequence"], "sequence"),
        created_at=_instant(body["created_at"]), entries=parsed)
    last = max(parsed, key=lambda entry: entry.sequence)
    if (last.commit_id, last.sequence) != (result.watermark, result.sequence):
        raise CheckpointError("the checkpoint watermark is not the last of its entries")
    return result
