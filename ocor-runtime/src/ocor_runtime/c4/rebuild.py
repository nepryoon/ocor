"""C4 -- rebuild and drift reconciliation.

Implements LLD v1.1 section 2.4's ``ProjectionDriftDetector``: rebuilds
a projection fact from the canonical commit and compares its digest
against what the live projection
(``ocor_runtime.c4.typedb_adapter.TypeDBProjectionAdapter``,
OCOR-DEV-0037) currently holds BEFORE ever overwriting it. A mismatch is
real drift: the divergent projection is quarantined rather than
silently repaired, and every subsequent read for that aggregate is
blocked (``PROJECTION_NOT_READY``) until an explicit, successful
rebuild reconciles it: this task's own negative acceptance criterion,
made structural.

OCOR-DEV-REM-0052 (NCP-U05, NCR-C4-002), LLD v1.1 :148 and Register FR-065 :189:

* the rebuild source is the canonical TerminusDB store (``TerminusDBC3Service``, the
  ``VersionedAssertedState`` store of ADD v1.3 Part I §2.2/§2.4); the PostgreSQL C3 service is
  the atomicity verification adapter, never a rebuild source (DEC-201), and is refused;
* the quarantine is durable, outside the process and the projection store
  (``ProjectionQuarantinePort``), and the projection enforces it on its own read path, so a
  quarantined aggregate is never served -- ``EXACT_AT_COMMIT`` included -- by any instance;
* ``checkpoint`` signs (Ed25519, DSSE) a checkpoint of a projection that reconciles with the
  canonical store and keeps it outside the projection store; ``rebuild_projection`` rebuilds a
  deleted or divergent projection from the last checkpoint that verifies under a trusted key,
  replaying from the canonical store at most ``replay_bound`` aggregates whose commit moved
  after it; every refusal happens before the projection is touched. No projection is
  authoritative: after the rebuild each aggregate is reconciled against the canonical store
  again.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from ..c1.signing import Ed25519SigningKey
from ..c2.ports import C2Error, NamedQueryRequest, NamedQueryResponse
from ..c3.ports import C3Error, CanonicalSnapshot
from ..c3.terminusdb_service import TerminusDBC3Service
from ..c4.typedb_adapter import BRANCH, TypeDBProjectionAdapter, TypeDBUnavailableError
from ..kernel.canonical import format_utc_timestamp
from .drift import (
    CheckpointBody,
    CheckpointEntry,
    CheckpointError,
    CheckpointStorePort,
    SignedProjectionCheckpoint,
    sign_checkpoint,
    verify_checkpoint,
)
from .watermark import WatermarkLedgerError

DEFAULT_REPLAY_BOUND = 256


class DriftError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True, slots=True)
class RebuildReport:
    aggregate_ref: str
    canonical_commit: str
    drift_detected: bool
    quarantined: bool


@dataclass(frozen=True, slots=True)
class ProjectionRebuildReport:
    """A projection rebuilt from a verified checkpoint: the checkpoint watermark, the number of
    aggregates replayed from the canonical store after it, the watermark reached, and the
    aggregates still quarantined after the final reconciliation."""

    checkpoint_watermark: str
    replayed: int
    watermark: str | None
    quarantined: tuple[str, ...]


def _digest_of(value: str) -> str:
    return "urn:sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class ProjectionDriftDetector:
    """Rebuilds a sample from the canonical store and reconciles it against the live projection;
    a divergent projection is quarantined durably rather than repaired, and the quarantine blocks
    every read of that aggregate until a fresh rebuild reconciles cleanly."""

    def __init__(
        self,
        source: TerminusDBC3Service,
        projection: TypeDBProjectionAdapter,
        *,
        signer: Ed25519SigningKey | None = None,
        key_id: str | None = None,
        trusted_keys: Mapping[str, bytes] | None = None,
        replay_bound: int = DEFAULT_REPLAY_BOUND,
        checkpoints: CheckpointStorePort | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not isinstance(source, TerminusDBC3Service):
            raise TypeError("the rebuild source is the canonical TerminusDB store (TerminusDBC3Service)")
        if not isinstance(projection, TypeDBProjectionAdapter):
            raise TypeError("a TypeDBProjectionAdapter is required")
        if (signer is None) != (key_id is None) or (signer is not None and not isinstance(signer, Ed25519SigningKey)):
            raise TypeError("a checkpoint signer is an Ed25519SigningKey with its key id")
        if key_id is not None and (not isinstance(key_id, str) or not key_id):
            raise TypeError("key_id must be a non-empty string")
        if isinstance(replay_bound, bool) or not isinstance(replay_bound, int) or replay_bound < 0:
            raise TypeError("replay_bound must be a non-negative integer")
        store = checkpoints if checkpoints is not None else projection.checkpoint_store
        if store is not None and not isinstance(store, CheckpointStorePort):
            raise TypeError("checkpoints must be a CheckpointStorePort")
        self._source = source
        self._projection = projection
        self._signer = signer
        self._key_id = key_id
        self._trusted = dict(trusted_keys or {})
        self._bound = replay_bound
        self._checkpoints = store
        self._clock = clock

    def is_quarantined(self, aggregate_ref: str) -> bool:
        try:
            return self._projection.is_quarantined(aggregate_ref)
        except WatermarkLedgerError as error:
            raise DriftError("CONTROL_PLANE_UNAVAILABLE", str(error)) from error

    def _canonical(self, tenant_id: str, aggregate_type: str, aggregate_ref: str) -> CanonicalSnapshot:
        try:
            canonical = self._source.read(tenant_id, aggregate_type, aggregate_ref)
        except (C3Error, OSError) as error:
            raise DriftError("CANONICAL_UNAVAILABLE", f"the canonical store cannot be read: {error}") from error
        if canonical is None:
            raise DriftError("CANONICAL_NOT_FOUND", f"no canonical commit exists for {aggregate_ref!r}")
        return canonical

    def _held_digest(self, aggregate_ref: str) -> str | None:
        try:
            return self._projection.reconciliation_digest(aggregate_ref)
        except TypeDBUnavailableError as error:
            # an unreachable projection is the typed fail-closed PROJECTION_NOT_READY
            # (NCR-C4-003; contract :486-491; LLD v1.1 :346)
            raise DriftError("PROJECTION_NOT_READY", str(error)) from error
        except C2Error as error:
            raise DriftError("BACKEND_ERROR", str(error)) from error

    def _quarantine(self, aggregate_ref: str, canonical: CanonicalSnapshot, held: str) -> None:
        try:
            self._projection.quarantine_fact(aggregate_ref, canonical_commit=canonical.commit_id,
                                             expected_digest=_digest_of(canonical.state_digest), served_digest=held)
        except WatermarkLedgerError as error:
            raise DriftError("CONTROL_PLANE_UNAVAILABLE", str(error)) from error

    def _release(self, aggregate_ref: str) -> None:
        try:
            self._projection.release_fact(aggregate_ref)
        except WatermarkLedgerError as error:
            raise DriftError("CONTROL_PLANE_UNAVAILABLE", str(error)) from error

    def _reconcile(self, aggregate_ref: str, canonical: CanonicalSnapshot) -> bool:
        """Compares the projection with the canonical commit; ``True`` when it reconciles. A
        divergent aggregate is quarantined; a missing one is projected from the canonical commit."""
        held = self._held_digest(aggregate_ref)
        if held is not None and held != _digest_of(canonical.state_digest):
            self._quarantine(aggregate_ref, canonical, held)
            return False
        self._projection.apply_commit(fact_id=aggregate_ref, commit_id=canonical.commit_id,
                                      payload=canonical.state_digest)
        self._release(aggregate_ref)
        return True

    def rebuild(self, *, tenant_id: str, aggregate_type: str, aggregate_ref: str) -> RebuildReport:
        canonical = self._canonical(tenant_id, aggregate_type, aggregate_ref)
        reconciled = self._reconcile(aggregate_ref, canonical)
        return RebuildReport(aggregate_ref=aggregate_ref, canonical_commit=canonical.commit_id,
                             drift_detected=not reconciled, quarantined=not reconciled)

    def read_if_healthy(self, aggregate_ref: str, request: NamedQueryRequest) -> NamedQueryResponse:
        """A read of the projection: the projection itself refuses a quarantined aggregate
        (``PROJECTION_NOT_READY``, LLD v1.1 :148), whatever the consistency mode."""
        return self._projection.read(request)

    # -- signed checkpoint and bounded rebuild (LLD v1.1 :148, FR-065 :189) ----------------

    def checkpoint(self, *, aggregates: Sequence[tuple[str, str, str]]) -> SignedProjectionCheckpoint:
        """Signs a checkpoint of the whole projection; ``aggregates`` gives the canonical key
        ``(tenant_id, aggregate_type, aggregate_ref)`` of every projected aggregate. The projection
        must reconcile with the canonical store; a divergent aggregate is quarantined instead."""
        if self._signer is None or self._key_id is None or self._checkpoints is None:
            raise DriftError("CHECKPOINT_SIGNER_UNAVAILABLE", "no checkpoint signer or checkpoint store is configured")
        keys = {ref: (tenant, kind) for tenant, kind, ref in aggregates}
        if len(keys) != len(aggregates):
            raise DriftError("CHECKPOINT_INCOMPLETE", "an aggregate is named twice")
        try:
            facts = self._projection.projected_facts()
        except TypeDBUnavailableError as error:
            raise DriftError("PROJECTION_NOT_READY", str(error)) from error
        except C2Error as error:
            raise DriftError("BACKEND_ERROR", str(error)) from error
        if not facts or {fact[0] for fact in facts} != set(keys):
            raise DriftError("CHECKPOINT_INCOMPLETE", "the aggregates do not cover exactly the projected facts")
        entries = []
        for fact_id, commit_id, sequence, payload in facts:
            tenant, kind = keys[fact_id]
            canonical = self._canonical(tenant, kind, fact_id)
            if self.is_quarantined(fact_id):
                raise DriftError("DRIFT_DETECTED", f"{fact_id!r} is quarantined")
            if (canonical.commit_id, canonical.state_digest) != (commit_id, payload):
                self._quarantine(fact_id, canonical, _digest_of(payload))
                raise DriftError("DRIFT_DETECTED", f"{fact_id!r} does not reconcile with the canonical store")
            entries.append(CheckpointEntry(tenant_id=tenant, aggregate_type=kind, aggregate_ref=fact_id,
                                           commit_id=commit_id, sequence=sequence, payload=payload))
        last = entries[-1]
        body = CheckpointBody(store_id=self._projection.store_id, branch=BRANCH,
                              release_digest=self._projection.release_digest, watermark=last.commit_id,
                              sequence=last.sequence, created_at=format_utc_timestamp(self._clock()),
                              entries=tuple(entries))
        signed = sign_checkpoint(body, key=self._signer, key_id=self._key_id)
        try:
            self._checkpoints.save_checkpoint(self._projection.store_id, signed, at=self._clock())
        except WatermarkLedgerError as error:
            raise DriftError("CONTROL_PLANE_UNAVAILABLE", str(error)) from error
        return signed

    def _verified(self, checkpoint: SignedProjectionCheckpoint | None) -> CheckpointBody:
        if checkpoint is None:
            if self._checkpoints is None:
                raise DriftError("CHECKPOINT_NOT_FOUND", "no checkpoint store is configured")
            try:
                checkpoint = self._checkpoints.latest_checkpoint(self._projection.store_id)
            except WatermarkLedgerError as error:
                raise DriftError("CONTROL_PLANE_UNAVAILABLE", str(error)) from error
            if checkpoint is None:
                raise DriftError("CHECKPOINT_NOT_FOUND", "no checkpoint exists for the projection")
        try:
            body = verify_checkpoint(checkpoint, self._trusted)
        except CheckpointError as error:
            raise DriftError("CHECKPOINT_INVALID", str(error)) from error
        if body.store_id != self._projection.store_id or body.branch != BRANCH:
            raise DriftError("CHECKPOINT_INVALID", "the checkpoint is of another projection store or branch")
        if body.release_digest != self._projection.release_digest:
            raise DriftError("RELEASE_MISMATCH", "the checkpoint was taken under another release")
        return body

    def rebuild_projection(
        self,
        *,
        checkpoint: SignedProjectionCheckpoint | None = None,
        aggregates: Sequence[tuple[str, str, str]] = (),
    ) -> ProjectionRebuildReport:
        """Rebuilds the projection from ``checkpoint`` (by default the last one saved) and the
        canonical store. ``aggregates`` adds canonical aggregates created after the checkpoint.
        Refused before any write: an unverifiable checkpoint (``CHECKPOINT_INVALID``), a release
        other than the projection's (``RELEASE_MISMATCH``), a missing canonical aggregate
        (``CANONICAL_NOT_FOUND``), more replays than the bound (``REPLAY_BOUND_EXCEEDED``)."""
        body = self._verified(checkpoint)
        known = {entry.aggregate_ref for entry in body.entries}
        extra = [(tenant, kind, ref) for tenant, kind, ref in aggregates if ref not in known]
        replays: list[CanonicalSnapshot] = []
        for entry in body.entries:
            canonical = self._canonical(entry.tenant_id, entry.aggregate_type, entry.aggregate_ref)
            if canonical.commit_id != entry.commit_id:
                replays.append(canonical)
        replays.extend(self._canonical(tenant, kind, ref) for tenant, kind, ref in extra)
        if len(replays) > self._bound:
            raise DriftError("REPLAY_BOUND_EXCEEDED",
                             f"{len(replays)} aggregates to replay exceed the bound of {self._bound}")

        self._projection.reset()
        for entry in body.entries:
            self._projection.apply_commit(fact_id=entry.aggregate_ref, commit_id=entry.commit_id, payload=entry.payload)
        for canonical in replays:
            self._projection.apply_commit(fact_id=canonical.aggregate_ref, commit_id=canonical.commit_id,
                                          payload=canonical.state_digest)
        quarantined = []
        keys = [(entry.tenant_id, entry.aggregate_type, entry.aggregate_ref) for entry in body.entries] + extra
        for tenant, kind, ref in keys:
            if not self._reconcile(ref, self._canonical(tenant, kind, ref)):
                quarantined.append(ref)
        try:
            watermark = self._projection.current_watermark()
        except TypeDBUnavailableError as error:
            raise DriftError("PROJECTION_NOT_READY", str(error)) from error
        return ProjectionRebuildReport(checkpoint_watermark=body.watermark, replayed=len(replays),
                                       watermark=watermark, quarantined=tuple(sorted(quarantined)))
