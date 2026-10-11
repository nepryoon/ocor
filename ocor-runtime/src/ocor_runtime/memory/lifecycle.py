"""C8 governed memory -- retention, expiry, revocation, forgetting and legal hold.

Implements the ``MemoryLifecycleCoordinator`` slice of the
``GovernedMemoryService`` (ADD v1.3 Part II §§2.5, 2.6, 2.8, 2.10, 2.12, 2.13;
LLD v1.1 §§2.8.1, 2.8.4, 2.8.6 and §7.2 ``FGM-10``/``FGM-11``/``FGM-12``/
``FGM-19``):

* The lifecycle FSM is exactly the one of ADD v1.3 Part II §2.10.  A transition
  is a new immutable version of the item (``supersedes_ref`` = the head) whose
  ``lifecycle_status`` is the target; the content, the provenance and every
  isolation attribute are carried unchanged, so the version stays in the same
  partition.  The version is appended to the memory version ledger with its
  lifecycle and audit events and committed through the store coordinator, which
  retires the projections of the predecessor.  Retrieval, embedding rebuild and
  consolidation only ever serve an ``ACTIVE`` head, and the version 2 index and
  metadata ports evaluate that inside the backend query, so a revoked, expired,
  held, quarantined or forgotten item leaves results, ranks, counts,
  normalisation, explanations and candidate pools at once.  Retrieval keeps no
  result or candidate cache; parallel embedding representations of the
  partition are invalidated by the same transition.
* ``transition`` serves the closed ``MemoryLifecycleRequest``
  (``transitionMemoryLifecycle``): compare-and-set on the head version, the
  caller must see the item (tenant, organization, domain, purpose,
  compartments and marking dominance; an invisible item is indistinguishable
  from an unknown one), the live lifecycle policy must permit it against the
  context policy bundle, and the reason code is a bounded code, never free
  text.  ``DELETED`` and ``DELETION_INCOMPLETE`` are reachable only through the
  deletion saga.  A transition back to ``ACTIVE`` additionally requires a
  readable, unchanged stop epoch; an exclusion never waits on the stop state.
* Legal hold: ``LEGAL_HOLD`` requires a ``legal_hold_ref`` that the
  ``LegalHoldRegistry`` reports as an active hold of the item's tenant, and
  records the prior disposition.  While the item is held, deletion, forgetting
  and retention are refused with ``LEGAL_HOLD_ACTIVE``; the hold can be left
  only once the registry reports it released, and only to the recorded prior
  disposition or into deletion.  An unreadable registry fails closed.
* Forgetting (``requestMemoryDeletion``, a transition to ``DELETION_PENDING``
  or the retention sweep) runs a deletion saga: a deletion epoch is reserved in
  the tombstone journal, a content-free ``DELETION_PENDING`` version is
  committed in the metadata store (retrieval fails closed from that instant),
  the native projections of every version are retired and then every deletion
  participant -- native lexical and vector entries, parallel embedding
  representations, encrypted content objects and any configured cache, replica
  or export participant -- purges and re-reads its residue.  Only a saga
  without residue commits ``DELETED`` and writes a tombstone; otherwise the
  item stays ``DELETION_INCOMPLETE`` (fail closed) and a retry resumes it under
  the same epoch.  A content object still referenced by a version of another,
  undeleted item (for instance one under legal hold) is retained.
* ``enforce_expiry`` transitions every visible ``ACTIVE`` head whose
  ``expires_at`` has elapsed on the boundary clock to ``EXPIRED``;
  ``enforce_retention`` forgets every visible item whose retention horizon has
  elapsed.  Both select deterministically (due instant, then item id), are
  bounded by an optional limit and report held items as protected.
* ``LifecycleGuardPolicy`` wraps the admission policy so that a new version
  can be admitted only on top of a ``PROPOSED``, ``ACTIVE`` or ``QUARANTINED``
  head: admission cannot re-open a revoked, expired, held or forgotten item.
* Every operation is idempotent per ``operation_id`` (a replay returns the
  recorded receipt and completes an interrupted commit or saga; another request
  under the same operation fails with ``MEMORY_IDEMPOTENCY_CONFLICT``) and
  every refusal is an audited denial.  Audit events carry codes, refs and
  digests only, never content.

The module is backend-free (``OCOR_LANGUAGE_POLICY.md`` row 8): ledgers,
stores, indexes, policy, legal holds, stop state, audit and deletion
participants are ports.  Memory lifecycle never creates Authority, Approval,
Decision, CapabilityLease or canonical state.
"""

from __future__ import annotations

import fcntl
import hmac
import os
import re
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO, Protocol

from ..errors import CanonicalizationError
from ..kernel.canonical import (
    TimestampError,
    canonical_bytes,
    canonical_digest,
    format_utc_timestamp,
    parse_i_json,
    parse_utc_timestamp,
)
from ..kernel.governance import TrustedClock
from ..kernel.governed_context import (
    GovernedContext,
    GovernedContextCodec,
    GovernedContextError,
    VerifiedGovernedContextBinding,
)
from .embeddings import (
    EmbeddingLifecycleCoordinator,
    EmbeddingModelRegistry,
    EmbeddingRepresentationStore,
    ParallelLayout,
    RepresentationIndexPort,
    RepresentationState,
)
from .model import (
    DELETION_STATUSES,
    VECTOR_FIELDS,
    AdmittedMemoryVersion,
    GovernedMemoryItem,
    LifecycleStatus,
    MarkingDominance,
    MemoryAdmissionError,
    MemoryAdmissionPolicy,
    MemoryPolicyDecision,
    MemoryReceipt,
    MemoryVersionLedger,
    RepresentationKind,
    idempotency_key,
)
from .retrieval import StopEpochPort
from .stores import (
    EligibilityIndexPort,
    MemoryContentStore,
    MemoryLexicalIndexPort,
    MemoryMetadataStore,
    MemoryPartition,
    MemoryStoreCoordinator,
    MemoryVectorIndexPort,
    RepresentationPointer,
    StagedVersion,
    StoredVersion,
    VectorProfile,
    VersionState,
    content_object_ref,
    lexical_document,
    structured_representation_version,
    vector_digest,
)

OPERATION_TRANSITION = "transitionMemoryLifecycle"
OPERATION_DELETE = "requestMemoryDeletion"
OPERATION_EXPIRY = "enforceMemoryExpiry"
OPERATION_RETENTION = "enforceMemoryRetention"

ENVELOPE_FIELDS = frozenset({"operation_id", "governed_context", "governed_context_digest", "deadline"})
TRANSITION_REQUIRED = ENVELOPE_FIELDS | {"memory_version", "target_status", "reason_code"}
TRANSITION_OPTIONAL = frozenset({"legal_hold_ref"})
DELETION_FIELDS = ENVELOPE_FIELDS | {"reason_code", "deletion_scope"}
DELETION_SCOPES = frozenset({"LATEST_VERSION", "ALL_VERSIONS", "PROJECT_SCOPE", "PRINCIPAL_SCOPE"})
# The PoC deletes an item with every version; narrower and bulk scopes fail closed.
SUPPORTED_DELETION_SCOPES = frozenset({"ALL_VERSIONS"})

S = LifecycleStatus
# ADD v1.3 Part II §2.10, verbatim.  LEGAL_HOLD leaves only to the recorded
# prior disposition or into deletion (checked separately).
TRANSITIONS: Mapping[LifecycleStatus, frozenset[LifecycleStatus]] = MappingProxyType(
    {
        S.PROPOSED: frozenset({S.ACTIVE, S.QUARANTINED}),
        S.ACTIVE: frozenset({S.SUPERSEDED, S.REVOKED, S.EXPIRED, S.LEGAL_HOLD, S.DELETION_PENDING}),
        S.QUARANTINED: frozenset({S.ACTIVE, S.REVOKED, S.DELETION_PENDING}),
        S.SUPERSEDED: frozenset({S.LEGAL_HOLD, S.DELETION_PENDING}),
        S.REVOKED: frozenset({S.LEGAL_HOLD, S.DELETION_PENDING}),
        S.EXPIRED: frozenset({S.LEGAL_HOLD, S.DELETION_PENDING}),
        S.LEGAL_HOLD: frozenset({S.ACTIVE, S.SUPERSEDED, S.REVOKED, S.EXPIRED, S.DELETION_PENDING}),
        S.DELETION_PENDING: frozenset({S.DELETED, S.DELETION_INCOMPLETE}),
        S.DELETION_INCOMPLETE: frozenset({S.DELETION_PENDING}),
        S.DELETED: frozenset(),
    }
)
SAGA_ONLY = frozenset({S.DELETED, S.DELETION_INCOMPLETE})
# Heads on which a new version may be admitted (``LifecycleGuardPolicy``).
ADMITTABLE_HEADS = frozenset({S.PROPOSED, S.ACTIVE, S.QUARANTINED})
# ADD v1.3 Part II §2.10: the triggers of forgetting.
FORGETTING_TRIGGERS = frozenset(
    {
        "EXPIRY",
        "PURPOSE_COMPLETION",
        "REVOCATION",
        "SUPERSESSION",
        "CONFIDENCE_DECAY",
        "QUOTA_PRESSURE",
        "AUTHORIZED_REQUEST",
        "RETENTION_ELAPSED",
    }
)
REASON_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
GENESIS = "urn:sha256:" + "0" * 64
METRIC_OUTCOMES = frozenset({"COMPLETED", "REPLAYED", "DENIED", "INCOMPLETE"})


class MemoryLifecycleError(MemoryAdmissionError):
    """Fail-closed lifecycle refusal with an OpenAPI ``Problem`` reason code."""


def _schema_error(detail: str, message: str) -> MemoryLifecycleError:
    return MemoryLifecycleError("MEMORY_SCHEMA_INVALID", detail, message)


def _invalid(detail: str, message: str) -> MemoryLifecycleError:
    return MemoryLifecycleError("LIFECYCLE_TRANSITION_INVALID", detail, message)


def _not_found() -> MemoryLifecycleError:
    # Unknown and invisible items are refused identically (no existence leak).
    return MemoryLifecycleError(
        "MEMORY_NOT_FOUND", "ITEM_NOT_VISIBLE", "no visible memory item has this id"
    )


def _string(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _schema_error("ENVELOPE_INVALID", f"{name} must be a non-empty string")
    return value


def _reason(value: object) -> str:
    reason = _string("reason_code", value)
    if not REASON_CODE.fullmatch(reason):
        raise _schema_error("REASON_CODE_INVALID", "reason_code must be a bounded upper-case code")
    return reason


# --------------------------------------------------------------------------
# Ports
# --------------------------------------------------------------------------


class LifecyclePolicy(Protocol):
    """Live lifecycle decision for one item and one target status."""

    def authorize_lifecycle(
        self,
        action: str,
        item: GovernedMemoryItem,
        target: LifecycleStatus,
        context: GovernedContext,
    ) -> MemoryPolicyDecision:
        """Decide whether ``context`` may move ``item`` to ``target``."""


@dataclass(frozen=True, slots=True)
class LegalHoldStatus:
    legal_hold_ref: str
    tenant_id: str
    active: bool


class LegalHoldRegistry(Protocol):
    """Authority on legal holds (outside memory); memory only reads it."""

    def status(self, legal_hold_ref: str, context: GovernedContext) -> LegalHoldStatus | None:
        """The hold, or ``None`` when it is unknown to the caller; raising fails closed."""


class LifecycleAuditSink(Protocol):
    def record(self, event: Mapping[str, object]) -> None:
        """Append one audit event; raising fails the operation closed."""


@dataclass(frozen=True, slots=True)
class DeletionTarget:
    """Every committed version of one item being forgotten."""

    memory_item_id: str
    versions: tuple[StoredVersion, ...]
    deletion_epoch: int
    operation_id: str
    binding: VerifiedGovernedContextBinding

    @property
    def version_refs(self) -> frozenset[str]:
        return frozenset(stored.staged.memory_version_ref for stored in self.versions)

    def partitions(self) -> tuple[MemoryPartition, ...]:
        seen: dict[str, MemoryPartition] = {}
        for stored in self.versions:
            seen.setdefault(stored.staged.partition.digest, stored.staged.partition)
        return tuple(seen[digest] for digest in sorted(seen))


class DeletionParticipant(Protocol):
    """One store, index, cache, replica or export the deletion saga must empty."""

    name: str

    def purge(self, target: DeletionTarget) -> None:
        """Remove every trace of ``target``; raising leaves residue for the check."""

    def residue(self, target: DeletionTarget) -> tuple[str, ...]:
        """Opaque refs of ``target`` still present (empty when purged)."""


# --------------------------------------------------------------------------
# Deletion participants of the stores of OCOR-DEV-0051/0053
# --------------------------------------------------------------------------


def _projection_pointers(
    target: DeletionTarget,
) -> list[tuple[MemoryPartition, RepresentationPointer]]:
    pointers = []
    for stored in target.versions:
        for pointer in stored.staged.pointers:
            if pointer.representation_kind is not RepresentationKind.STRUCTURED:
                pointers.append((stored.staged.partition, pointer))
    return pointers


class NativeProjectionParticipant:
    """Lexical (full-text) and native vector entries of every version."""

    name = "native-projections"

    def __init__(self, lexical: MemoryLexicalIndexPort, vector: MemoryVectorIndexPort) -> None:
        self._lexical = lexical
        self._vector = vector

    def _index(self, pointer: RepresentationPointer) -> MemoryLexicalIndexPort | MemoryVectorIndexPort:
        if pointer.representation_kind is RepresentationKind.FULL_TEXT:
            return self._lexical
        return self._vector

    def purge(self, target: DeletionTarget) -> None:
        for partition, pointer in _projection_pointers(target):
            self._index(pointer).remove(partition, pointer.representation_version, pointer.store_ref)

    def residue(self, target: DeletionTarget) -> tuple[str, ...]:
        return tuple(
            pointer.store_ref
            for partition, pointer in _projection_pointers(target)
            if self._index(pointer).read_back(
                partition, pointer.representation_version, pointer.store_ref
            )
            is not None
        )


class ContentParticipant:
    """Encrypted content objects; an object shared with an undeleted item is retained."""

    name = "content"

    def __init__(self, content: MemoryContentStore, metadata: MemoryMetadataStore) -> None:
        self._content = content
        self._metadata = metadata

    def _objects(self, target: DeletionTarget) -> tuple[list[str], list[str]]:
        mine = sorted({stored.staged.content_object_ref for stored in target.versions})
        shared: set[str] = set()
        for partition in target.partitions():
            for stored in self._metadata.versions_in(partition.digest):
                staged = stored.staged
                if staged.memory_item_id == target.memory_item_id:
                    continue
                if staged.content_object_ref not in mine:
                    continue
                head = self._metadata.head(staged.memory_item_id)
                head_version = self._metadata.get(staged.memory_item_id, head) if head else None
                status = (
                    None
                    if head_version is None
                    else head_version.staged.item.get("lifecycle_status")
                )
                if status != S.DELETED.value:
                    shared.add(staged.content_object_ref)
        return [ref for ref in mine if ref not in shared], sorted(shared)

    def retained(self, target: DeletionTarget) -> tuple[str, ...]:
        return tuple(self._objects(target)[1])

    def purge(self, target: DeletionTarget) -> None:
        for ref in self._objects(target)[0]:
            self._content.delete(ref)

    def residue(self, target: DeletionTarget) -> tuple[str, ...]:
        return tuple(ref for ref in self._objects(target)[0] if self._content.get(ref) is not None)


class RepresentationParticipant:
    """Parallel embedding representations (descriptors and their index entries)."""

    name = "embedding-representations"

    def __init__(
        self,
        coordinator: EmbeddingLifecycleCoordinator,
        *,
        models: EmbeddingModelRegistry,
        representations: EmbeddingRepresentationStore,
        index: RepresentationIndexPort,
    ) -> None:
        self._coordinator = coordinator
        self._models = models
        self._representations = representations
        self._index = index

    def purge(self, target: DeletionTarget) -> None:
        invalidate_all(
            self._coordinator,
            self._models,
            self._representations,
            target.partitions(),
            target.binding,
            f"{target.operation_id}:purge-representations",
        )

    def residue(self, target: DeletionTarget) -> tuple[str, ...]:
        refs = target.version_refs
        found: list[str] = []
        for partition in target.partitions():
            for pin in self._models.pins():
                layout = ParallelLayout.of(pin)
                for descriptor in self._representations.descriptors(
                    partition.digest, pin.representation_version
                ):
                    if descriptor.memory_version_ref in refs:
                        found.append(descriptor.store_ref)
                for hit in self._index.entries(partition, layout.representation_version):
                    if hit.payload.get("memory_version_ref") in refs:
                        found.append(hit.store_ref)
        return tuple(sorted(set(found)))


def invalidate_all(
    coordinator: EmbeddingLifecycleCoordinator,
    models: EmbeddingModelRegistry,
    representations: EmbeddingRepresentationStore,
    partitions: Sequence[MemoryPartition],
    binding: VerifiedGovernedContextBinding,
    operation_id: str,
) -> int:
    """Invalidate every ``ACTIVE`` parallel representation of ``partitions``."""

    count = 0
    for partition in partitions:
        for pin in sorted(models.pins(), key=lambda p: p.representation_version):
            record = representations.record(partition.digest, pin.representation_version)
            if record is None or record.state is not RepresentationState.ACTIVE:
                continue
            coordinator.invalidate(
                partition.ref,
                pin.vector_profile,
                binding=binding,
                operation_id=f"{operation_id}:{count}",
            )
            count += 1
    return count


# --------------------------------------------------------------------------
# Tombstone journal (deletion epochs and non-content tombstones)
# --------------------------------------------------------------------------


class TombstonePhase:
    STARTED = "STARTED"
    INCOMPLETE = "INCOMPLETE"
    COMPLETED = "COMPLETED"


PHASES = frozenset({TombstonePhase.STARTED, TombstonePhase.INCOMPLETE, TombstonePhase.COMPLETED})
TOMBSTONE_FIELDS = frozenset(
    {
        "memory_item_id",
        "tenant_id",
        "partition_digests",
        "version_refs",
        "deletion_epoch",
        "phase",
        "reason_code",
        "operation_id",
        "participants",
        "residue_counts",
        "retained_shared_objects",
        "at",
    }
)


class TombstoneCorrupted(MemoryLifecycleError):
    def __init__(self, message: str) -> None:
        super().__init__("INTERNAL_ERROR", "TOMBSTONE_JOURNAL_CORRUPTED", message)


@dataclass(frozen=True, slots=True)
class TombstoneEntry:
    """One saga event; ``COMPLETED`` is the non-content tombstone of the item."""

    memory_item_id: str
    tenant_id: str
    partition_digests: tuple[str, ...]
    version_refs: tuple[str, ...]
    deletion_epoch: int
    phase: str
    reason_code: str
    operation_id: str
    participants: tuple[str, ...]
    residue_counts: tuple[tuple[str, int], ...]
    retained_shared_objects: int
    at: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "memory_item_id": self.memory_item_id,
            "tenant_id": self.tenant_id,
            "partition_digests": list(self.partition_digests),
            "version_refs": list(self.version_refs),
            "deletion_epoch": self.deletion_epoch,
            "phase": self.phase,
            "reason_code": self.reason_code,
            "operation_id": self.operation_id,
            "participants": list(self.participants),
            "residue_counts": [[name, count] for name, count in self.residue_counts],
            "retained_shared_objects": self.retained_shared_objects,
            "at": self.at,
        }

    @classmethod
    def from_mapping(cls, value: object) -> TombstoneEntry:
        if not isinstance(value, Mapping) or set(value) != TOMBSTONE_FIELDS:
            raise TombstoneCorrupted("tombstone entry is not a closed record")
        try:
            entry = cls(
                memory_item_id=_string("memory_item_id", value["memory_item_id"]),
                tenant_id=_string("tenant_id", value["tenant_id"]),
                partition_digests=tuple(str(v) for v in value["partition_digests"]),
                version_refs=tuple(str(v) for v in value["version_refs"]),
                deletion_epoch=value["deletion_epoch"],
                phase=_string("phase", value["phase"]),
                reason_code=_string("reason_code", value["reason_code"]),
                operation_id=_string("operation_id", value["operation_id"]),
                participants=tuple(str(v) for v in value["participants"]),
                residue_counts=tuple((str(n), c) for n, c in value["residue_counts"]),
                retained_shared_objects=value["retained_shared_objects"],
                at=_string("at", value["at"]),
            )
        except (MemoryAdmissionError, TypeError, ValueError) as exc:
            raise TombstoneCorrupted(f"tombstone entry does not re-validate: {exc}") from exc
        if entry.to_mapping() != dict(value) or entry.phase not in PHASES:
            raise TombstoneCorrupted("tombstone entry has invalid members")
        if (
            isinstance(entry.deletion_epoch, bool)
            or not isinstance(entry.deletion_epoch, int)
            or entry.deletion_epoch < 1
            or isinstance(entry.retained_shared_objects, bool)
            or not isinstance(entry.retained_shared_objects, int)
            or entry.retained_shared_objects < 0
            or any(isinstance(c, bool) or not isinstance(c, int) or c < 1 for _, c in entry.residue_counts)
        ):
            raise TombstoneCorrupted("tombstone counters are invalid")
        return entry

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


class MemoryTombstoneStore(Protocol):
    """Append-only authority on deletion epochs and tombstones."""

    def entries(self, memory_item_id: str) -> tuple[TombstoneEntry, ...]:
        """Every saga event of one item, in append order."""

    def latest_epoch(self) -> int:
        """The highest deletion epoch ever reserved, or 0."""

    def append(self, entry: TombstoneEntry) -> None:
        """Append; a ``STARTED`` entry must reserve exactly ``latest_epoch() + 1``."""


def _epoch_conflict(entry: TombstoneEntry, latest: int, items: Mapping[str, list[TombstoneEntry]]) -> str | None:
    history = items.get(entry.memory_item_id, [])
    if entry.phase == TombstonePhase.STARTED and entry.deletion_epoch != latest + 1:
        open_saga = [e for e in history if e.deletion_epoch == entry.deletion_epoch]
        if not open_saga:
            return "a new saga must reserve the next deletion epoch"
    if entry.phase != TombstonePhase.STARTED and not any(
        e.deletion_epoch == entry.deletion_epoch and e.phase == TombstonePhase.STARTED
        for e in history
    ):
        return "a saga outcome needs its STARTED entry"
    if any(e.phase == TombstonePhase.COMPLETED for e in history):
        return "a completed tombstone is terminal"
    return None


class InMemoryTombstoneStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, list[TombstoneEntry]] = {}
        self._latest = 0

    def entries(self, memory_item_id: str) -> tuple[TombstoneEntry, ...]:
        with self._lock:
            return tuple(self._items.get(memory_item_id, ()))

    def latest_epoch(self) -> int:
        with self._lock:
            return self._latest

    def append(self, entry: TombstoneEntry) -> None:
        with self._lock:
            conflict = _epoch_conflict(entry, self._latest, self._items)
            if conflict is not None:
                raise MemoryLifecycleError(
                    "MEMORY_IDEMPOTENCY_CONFLICT", "DELETION_EPOCH_CONFLICT", conflict
                )
            self._items.setdefault(entry.memory_item_id, []).append(entry)
            self._latest = max(self._latest, entry.deletion_epoch)


class JournalTombstoneStore:
    """Durable, hash-chained, append-only JSON-lines tombstone journal.

    The chain entry is ``{"seq", "prev", "entry", "entry_digest"}`` in canonical
    bytes; any rewrite, removal, reordering or torn write is detected on
    (re)open and the store refuses to serve.  Appends take an exclusive
    ``flock``, catch up with other writers and ``fsync`` before acknowledging.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._memory = InMemoryTombstoneStore()
        self._offset = 0
        self._seq = 0
        self._head = GENESIS
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)
        with self._lock, self._path.open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            try:
                self._catch_up(handle)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @property
    def head(self) -> str:
        with self._lock:
            return self._head

    def _catch_up(self, handle: BinaryIO) -> None:
        handle.seek(self._offset)
        data = handle.read()
        if not data:
            return
        if not data.endswith(b"\n"):
            raise TombstoneCorrupted("journal ends with a torn, unacknowledged write")
        for line in data.splitlines():
            self._apply(line)
            self._offset += len(line) + 1

    def _apply(self, line: bytes) -> None:
        try:
            chained = parse_i_json(line)
        except (CanonicalizationError, UnicodeError, ValueError) as exc:
            raise TombstoneCorrupted(f"journal entry is not I-JSON: {exc}") from exc
        if not isinstance(chained, Mapping) or set(chained) != {
            "seq",
            "prev",
            "entry",
            "entry_digest",
        }:
            raise TombstoneCorrupted("journal entry is not a closed chain entry")
        if canonical_bytes(chained) != line:
            raise TombstoneCorrupted("journal entry is not in canonical form")
        body = {"seq": chained["seq"], "prev": chained["prev"], "entry": chained["entry"]}
        if chained["seq"] != self._seq + 1 or chained["prev"] != self._head:
            raise TombstoneCorrupted("journal chain is broken or reordered")
        if not hmac.compare_digest(canonical_digest(body), str(chained["entry_digest"])):
            raise TombstoneCorrupted("journal entry digest mismatch")
        entry = TombstoneEntry.from_mapping(chained["entry"])
        try:
            self._memory.append(entry)
        except MemoryAdmissionError as exc:
            raise TombstoneCorrupted(f"journal violates the epoch order: {exc}") from exc
        self._seq += 1
        self._head = str(chained["entry_digest"])

    def entries(self, memory_item_id: str) -> tuple[TombstoneEntry, ...]:
        with self._lock, self._path.open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            try:
                self._catch_up(handle)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
            return self._memory.entries(memory_item_id)

    def latest_epoch(self) -> int:
        with self._lock:
            return self._memory.latest_epoch()

    def append(self, entry: TombstoneEntry) -> None:
        with self._lock, self._path.open("r+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                self._catch_up(handle)
                conflict = _epoch_conflict(
                    entry,
                    self._memory.latest_epoch(),
                    {entry.memory_item_id: list(self._memory.entries(entry.memory_item_id))},
                )
                if conflict is not None:
                    raise MemoryLifecycleError(
                        "MEMORY_IDEMPOTENCY_CONFLICT", "DELETION_EPOCH_CONFLICT", conflict
                    )
                body = {"seq": self._seq + 1, "prev": self._head, "entry": entry.to_mapping()}
                line = canonical_bytes(dict(body, entry_digest=canonical_digest(body))) + b"\n"
                handle.seek(0, os.SEEK_END)
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
                self._apply(line[:-1])
                self._offset += len(line)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


# --------------------------------------------------------------------------
# Admission guard
# --------------------------------------------------------------------------


class LifecycleGuardPolicy:
    """Admission policy wrapper: a new version only on an admittable head.

    A revoked, expired, superseded, held or forgotten item cannot be re-opened
    by admitting a new version on top of it; only this module moves it.
    """

    def __init__(self, inner: MemoryAdmissionPolicy, *, ledger: MemoryVersionLedger) -> None:
        self._inner = inner
        self._ledger = ledger

    def authorize_admission(
        self, item: GovernedMemoryItem, context: GovernedContext
    ) -> MemoryPolicyDecision:
        if item.memory_version > 1:
            head = self._ledger.get(item.memory_item_id, item.memory_version - 1)
            if head is not None and head.item.lifecycle_status not in ADMITTABLE_HEADS:
                return MemoryPolicyDecision(
                    permitted=False,
                    decision_ref="decision:lifecycle-guard:head-not-admittable",
                    policy_bundle_digest=context.policy_bundle_digest,
                    reason="LIFECYCLE_HEAD_NOT_ADMITTABLE",
                )
        return self._inner.authorize_admission(item, context)


# --------------------------------------------------------------------------
# Receipts
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LifecycleReceipt:
    """The OpenAPI ``OperationReceipt`` plus the resulting head (not on the wire)."""

    receipt: Mapping[str, object]
    memory_version_ref: str
    lifecycle_status: str
    deletion_epoch: int | None = None
    tombstone_digest: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return dict(self.receipt)


@dataclass(frozen=True, slots=True)
class SweepReport:
    operation_id: str
    operation_kind: str
    processed: tuple[str, ...]
    held: tuple[str, ...]
    incomplete: tuple[str, ...]
    unresolved: tuple[str, ...]
    deferred: tuple[str, ...]
    audit_ref: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "operation_kind": self.operation_kind,
            "processed": list(self.processed),
            "held": list(self.held),
            "incomplete": list(self.incomplete),
            "unresolved": list(self.unresolved),
            "deferred": list(self.deferred),
            "audit_ref": self.audit_ref,
        }


@dataclass
class _Failure:
    operation_id: str | None = None
    gcs_digest: str | None = None
    correlation_id: str | None = None
    binding_ref: str | None = None
    memory_item_id: str | None = None


@dataclass(frozen=True, slots=True)
class _Request:
    operation_id: str
    context: GovernedContext
    gcs_digest: str
    deadline: datetime
    body: Mapping[str, object]
    binding: VerifiedGovernedContextBinding


@dataclass(frozen=True, slots=True)
class _Plan:
    """One resolved transition of one item."""

    action: str
    request: _Request
    head: AdmittedMemoryVersion
    target: LifecycleStatus
    reason_code: str
    request_digest: str
    legal_hold_ref: str | None = None
    stop_epoch: int | None = None


# --------------------------------------------------------------------------
# Coordinator
# --------------------------------------------------------------------------


class MemoryLifecycleCoordinator:
    """``MemoryLifecycleCoordinator``: FSM, holds, forgetting and the deletion saga."""

    def __init__(
        self,
        *,
        ledger: MemoryVersionLedger,
        metadata: MemoryMetadataStore,
        store: MemoryStoreCoordinator,
        lexical: MemoryLexicalIndexPort,
        vector: MemoryVectorIndexPort,
        policy: LifecyclePolicy,
        markings: MarkingDominance,
        legal_holds: LegalHoldRegistry,
        stop: StopEpochPort,
        audit: LifecycleAuditSink,
        tombstones: MemoryTombstoneStore,
        clock: TrustedClock,
        participants: Sequence[DeletionParticipant],
        retention_horizons: Mapping[str, timedelta] | None = None,
        representations: tuple[EmbeddingModelRegistry, EmbeddingRepresentationStore] | None = None,
    ) -> None:
        names = [participant.name for participant in participants]
        if not names or len(set(names)) != len(names):
            raise ValueError("deletion participants must be non-empty with unique names")
        self._ledger = ledger
        self._metadata = metadata
        self._store = store
        self._lexical = lexical
        self._vector = vector
        self._policy = policy
        self._markings = markings
        self._holds = legal_holds
        self._stop = stop
        self._audit = audit
        self._tombstones = tombstones
        self._clock = clock
        self._participants = tuple(participants)
        self._horizons: Mapping[str, timedelta] = MappingProxyType(dict(retention_horizons or {}))
        self._representations = representations
        self._lock = threading.RLock()
        # Bounded label set: (operation, outcome, reason code or "NONE").
        self.metrics: Counter[tuple[str, str, str]] = Counter()

    # -- public operations -------------------------------------------------

    def transition(
        self,
        memory_item_id: str,
        request: Mapping[str, object],
        *,
        binding: VerifiedGovernedContextBinding | None,
    ) -> LifecycleReceipt:
        """``transitionMemoryLifecycle``: move the head of one item along the FSM."""

        return self._guarded(OPERATION_TRANSITION, memory_item_id, request, binding)

    def request_deletion(
        self,
        memory_item_id: str,
        request: Mapping[str, object],
        *,
        binding: VerifiedGovernedContextBinding | None,
    ) -> LifecycleReceipt:
        """``requestMemoryDeletion``: forget one item through the deletion saga."""

        return self._guarded(OPERATION_DELETE, memory_item_id, request, binding)

    def enforce_expiry(
        self,
        *,
        binding: VerifiedGovernedContextBinding | None,
        operation_id: str,
        limit: int | None = None,
    ) -> SweepReport:
        """Expire every visible ``ACTIVE`` head whose ``expires_at`` has elapsed."""

        return self._sweep(OPERATION_EXPIRY, binding, operation_id, limit)

    def enforce_retention(
        self,
        *,
        binding: VerifiedGovernedContextBinding | None,
        operation_id: str,
        limit: int | None = None,
    ) -> SweepReport:
        """Forget every visible item whose retention horizon has elapsed."""

        return self._sweep(OPERATION_RETENTION, binding, operation_id, limit)

    def head(self, memory_item_id: str) -> AdmittedMemoryVersion | None:
        """The committed head record of one item (lifecycle state), or ``None``."""

        version = self._metadata.head(memory_item_id)
        return None if version < 1 else self._ledger.get(memory_item_id, version)

    # -- guarded execution ---------------------------------------------------

    def _guarded(
        self,
        kind: str,
        memory_item_id: str,
        request: Mapping[str, object],
        binding: VerifiedGovernedContextBinding | None,
    ) -> LifecycleReceipt:
        failure = _Failure(memory_item_id=memory_item_id if isinstance(memory_item_id, str) else None)
        try:
            parsed = self._envelope(kind, request, binding, failure)
            item_id = _string("memory_item_id", memory_item_id)
            with self._lock:
                if kind == OPERATION_TRANSITION:
                    receipt, replayed = self._transition_request(item_id, parsed)
                else:
                    receipt, replayed = self._deletion_request(item_id, parsed)
            outcome = (
                "REPLAYED"
                if replayed
                else ("INCOMPLETE" if receipt.lifecycle_status == S.DELETION_INCOMPLETE.value else "COMPLETED")
            )
            self.metrics[(kind, outcome, "NONE")] += 1
            return receipt
        except MemoryAdmissionError as exc:
            if exc.correlation_id is None:
                exc.correlation_id = failure.correlation_id
            self._record_denial(kind, exc, failure)
            raise

    def _envelope(
        self,
        kind: str,
        request: Mapping[str, object],
        binding: VerifiedGovernedContextBinding | None,
        failure: _Failure,
    ) -> _Request:
        if not isinstance(binding, VerifiedGovernedContextBinding):
            raise MemoryLifecycleError(
                "AUTHENTICATION_REQUIRED",
                "BINDING_MISSING",
                "lifecycle operations require an authenticated governed-context binding",
            )
        failure.correlation_id = binding.expected.correlation_id
        failure.binding_ref = binding.binding_ref
        if not isinstance(request, Mapping):
            raise _schema_error("ENVELOPE_INVALID", "request is not the closed request envelope")
        keys = set(request)
        if kind == OPERATION_TRANSITION:
            closed = TRANSITION_REQUIRED <= keys <= TRANSITION_REQUIRED | TRANSITION_OPTIONAL
        else:
            closed = keys == DELETION_FIELDS
        if not closed:
            raise _schema_error("ENVELOPE_INVALID", "request is not the closed request envelope")
        operation_id = _string("operation_id", request["operation_id"])
        failure.operation_id = operation_id
        claimed = _string("governed_context_digest", request["governed_context_digest"])
        try:
            deadline = parse_utc_timestamp(_string("deadline", request["deadline"]))
        except TimestampError as exc:
            raise _schema_error("ENVELOPE_INVALID", "deadline must be a UTC timestamp") from exc
        if deadline <= self._clock.now():
            raise MemoryLifecycleError(
                "POLICY_DENIED", "DEADLINE_EXCEEDED", "the request deadline has passed"
            )
        raw_context = request["governed_context"]
        if not isinstance(raw_context, Mapping):
            raise MemoryLifecycleError(
                "GOVERNED_CONTEXT_MISMATCH", "GCS_INVALID", "governed_context must be an object"
            )
        try:
            context = GovernedContextCodec.from_openapi(raw_context, binding, claimed)
        except GovernedContextError as exc:
            raise MemoryLifecycleError("GOVERNED_CONTEXT_MISMATCH", exc.code, str(exc)) from exc
        failure.gcs_digest = context.digest()
        return _Request(
            operation_id=operation_id,
            context=context,
            gcs_digest=failure.gcs_digest,
            deadline=deadline,
            body=request,
            binding=binding,
        )

    def _record_denial(self, kind: str, exc: MemoryAdmissionError, failure: _Failure) -> None:
        self.metrics[(kind, "DENIED", exc.reason_code)] += 1
        event = {
            "action": f"{kind}.denied",
            "outcome": "DENIED",
            "reason_code": exc.reason_code,
            "detail_code": exc.detail_code,
            "operation_id": failure.operation_id,
            "memory_item_id": failure.memory_item_id,
            "governed_context_digest": failure.gcs_digest,
            "binding_ref": failure.binding_ref,
            "correlation_id": exc.correlation_id,
            "at": format_utc_timestamp(self._clock.now()),
        }
        try:
            self._audit.record(event)
        except Exception as audit_exc:  # noqa: BLE001 -- an unaudited denial fails closed
            raise MemoryLifecycleError(
                "CONTROL_PLANE_UNAVAILABLE",
                "AUDIT_UNAVAILABLE",
                "the denial could not be audited",
                correlation_id=exc.correlation_id,
            ) from audit_exc

    # -- resolution ----------------------------------------------------------

    def _visible(self, item: GovernedMemoryItem, context: GovernedContext) -> bool:
        try:
            dominated = self._markings.dominates(
                context.classification_marking_ref, item.classification_marking_ref
            )
        except MemoryAdmissionError:
            return False
        return (
            item.tenant_id == context.tenant_id
            and item.organization_id == context.organization_id
            and item.domain_id == context.domain_id
            and item.purpose == context.purpose
            and set(item.compartments) <= set(context.compartments)
            and dominated
        )

    def _committed_head(self, memory_item_id: str, context: GovernedContext) -> AdmittedMemoryVersion:
        latest = self._ledger.latest_version(memory_item_id)
        record = self._ledger.get(memory_item_id, latest) if latest else None
        if record is None or not self._visible(record.item, context):
            raise _not_found()
        if self._metadata.head(memory_item_id) != latest:
            raise MemoryLifecycleError(
                "REPRESENTATION_NOT_READY",
                "HEAD_NOT_COMMITTED",
                "the latest version of the item is not committed yet",
            )
        return record

    def _decide(
        self, action: str, item: GovernedMemoryItem, target: LifecycleStatus, context: GovernedContext
    ) -> MemoryPolicyDecision:
        try:
            decision = self._policy.authorize_lifecycle(action, item, target, context)
        except MemoryAdmissionError:
            raise
        except Exception as exc:  # noqa: BLE001 -- every policy outage fails closed
            raise MemoryLifecycleError(
                "CONTROL_PLANE_UNAVAILABLE", "POLICY_UNAVAILABLE", "policy evaluation failed closed"
            ) from exc
        if not isinstance(decision, MemoryPolicyDecision):
            raise MemoryLifecycleError(
                "CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID", "no policy decision"
            )
        if decision.policy_bundle_digest != context.policy_bundle_digest:
            raise MemoryLifecycleError(
                "STALE_POLICY",
                "POLICY_BUNDLE_MISMATCH",
                "policy decision was not evaluated against the context bundle",
            )
        if not decision.permitted:
            raise MemoryLifecycleError(
                "POLICY_DENIED", "LIFECYCLE_DENIED", "policy denied the lifecycle operation"
            )
        return decision

    def _hold(self, legal_hold_ref: str, context: GovernedContext) -> LegalHoldStatus | None:
        try:
            status = self._holds.status(legal_hold_ref, context)
        except Exception as exc:  # noqa: BLE001 -- an unreadable registry fails closed
            raise MemoryLifecycleError(
                "CONTROL_PLANE_UNAVAILABLE",
                "LEGAL_HOLD_REGISTRY_UNAVAILABLE",
                "the legal hold registry could not be read",
            ) from exc
        if status is not None and (
            not isinstance(status, LegalHoldStatus)
            or status.legal_hold_ref != legal_hold_ref
            or not isinstance(status.active, bool)
        ):
            raise MemoryLifecycleError(
                "CONTROL_PLANE_UNAVAILABLE",
                "LEGAL_HOLD_REGISTRY_INVALID",
                "the legal hold registry returned an invalid status",
            )
        return status

    def _require_released(self, head: GovernedMemoryItem, context: GovernedContext) -> None:
        assert head.legal_hold_ref is not None
        status = self._hold(head.legal_hold_ref, context)
        if status is None or status.active:
            raise MemoryLifecycleError(
                "LEGAL_HOLD_ACTIVE",
                "LEGAL_HOLD_NOT_RELEASED",
                "the item is under a legal hold that has not been released",
            )

    def _stop_epoch(self, context: GovernedContext) -> int:
        try:
            epoch = self._stop.current_epoch(context)
        except Exception as exc:  # noqa: BLE001 -- unknown stop state fails closed
            raise MemoryLifecycleError(
                "CONTROL_PLANE_UNAVAILABLE", "STOP_STATE_UNKNOWN", "stop state is unavailable"
            ) from exc
        if isinstance(epoch, bool) or not isinstance(epoch, int):
            raise MemoryLifecycleError(
                "CONTROL_PLANE_UNAVAILABLE", "STOP_STATE_INVALID", "stop state is invalid"
            )
        return epoch

    def _require_stop_epoch(self, context: GovernedContext, expected: int | None) -> None:
        if expected is not None and self._stop_epoch(context) != expected:
            raise MemoryLifecycleError(
                "STOP_EPOCH_MISMATCH",
                "STOP_EPOCH_CHANGED",
                "the stop epoch changed before the item could be re-opened",
            )

    def _check_fsm(
        self,
        head: GovernedMemoryItem,
        target: LifecycleStatus,
        context: GovernedContext,
        legal_hold_ref: str | None,
    ) -> None:
        source = head.lifecycle_status
        if target in SAGA_ONLY:
            raise _invalid("SAGA_OWNED_STATUS", f"{target.value} is reached only by the deletion saga")
        if target not in TRANSITIONS[source]:
            raise _invalid(
                "TRANSITION_NOT_DECLARED",
                f"{source.value} -> {target.value} is not a lifecycle transition",
            )
        if target is S.LEGAL_HOLD:
            if legal_hold_ref is None:
                raise _schema_error("LEGAL_HOLD_REF_MISSING", "LEGAL_HOLD requires legal_hold_ref")
            status = self._hold(legal_hold_ref, context)
            if status is None or status.tenant_id != head.tenant_id or not status.active:
                raise MemoryLifecycleError(
                    "POLICY_DENIED",
                    "LEGAL_HOLD_NOT_ACTIVE",
                    "legal_hold_ref is not an active hold of the item's tenant",
                )
        elif legal_hold_ref is not None:
            raise _schema_error("LEGAL_HOLD_REF_UNEXPECTED", "legal_hold_ref is only for LEGAL_HOLD")
        if source is S.LEGAL_HOLD:
            self._require_released(head, context)
            if target is not S.DELETION_PENDING and target is not head.prior_lifecycle_status:
                raise _invalid(
                    "PRIOR_DISPOSITION_REQUIRED",
                    "leaving LEGAL_HOLD restores exactly the recorded prior disposition",
                )

    # -- transition ----------------------------------------------------------

    def _transition_request(
        self, memory_item_id: str, request: _Request
    ) -> tuple[LifecycleReceipt, bool]:
        body = request.body
        version = body["memory_version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise _schema_error("ENVELOPE_INVALID", "memory_version must be a positive integer")
        try:
            target = LifecycleStatus(_string("target_status", body["target_status"]))
        except ValueError as exc:
            raise _schema_error("TARGET_STATUS_INVALID", "target_status is not declared") from exc
        reason = _reason(body["reason_code"])
        hold_ref = body.get("legal_hold_ref")
        if hold_ref is not None:
            hold_ref = _string("legal_hold_ref", hold_ref)
        if target is S.DELETION_PENDING and reason not in FORGETTING_TRIGGERS:
            raise _schema_error("FORGETTING_TRIGGER_INVALID", "forgetting needs a declared trigger")
        request_digest = canonical_digest(
            {
                "operation": OPERATION_TRANSITION,
                "memory_item_id": memory_item_id,
                "memory_version": version,
                "target_status": target.value,
                "reason_code": reason,
                "legal_hold_ref": hold_ref,
                "governed_context_digest": request.gcs_digest,
            }
        )
        replayed = self._replay(memory_item_id, request, request_digest)
        if replayed is not None:
            return replayed, True
        head = self._committed_head(memory_item_id, request.context)
        if head.item.memory_version != version:
            raise _invalid("STALE_VERSION", "memory_version is not the current head")
        self._check_fsm(head.item, target, request.context, hold_ref)
        plan = _Plan(
            action=OPERATION_TRANSITION,
            request=request,
            head=head,
            target=target,
            reason_code=reason,
            request_digest=request_digest,
            legal_hold_ref=hold_ref,
        )
        if target is S.DELETION_PENDING:
            return self._forget(plan), False
        return self._apply(plan), False

    def _apply(self, plan: _Plan) -> LifecycleReceipt:
        context = plan.request.context
        decision = self._decide(plan.action, plan.head.item, plan.target, context)
        stop_epoch = self._stop_epoch(context) if plan.target is S.ACTIVE else None
        record = self._version(plan, decision, deletion_epoch=None)
        # Content and embedding are re-derived and verified before any write.
        content = self._content_of(record)
        # Re-opening re-reads the stop epoch after the content I/O, right before the append.
        # The stop epoch comes from an external control plane, so this check and
        # the append are not atomic: the residual window is tracked towards FGM-17.
        self._require_stop_epoch(context, stop_epoch)
        self._append(record)
        self._commit_content_version(record, plan.request.binding, content)
        return self._receipt(record, plan.request, record)

    def _content_of(
        self, record: AdmittedMemoryVersion
    ) -> tuple[bytes, tuple[float, ...] | None]:
        """The verified content of the predecessor and the re-derived embedding."""

        item = record.item
        previous = self._ledger.get(item.memory_item_id, item.memory_version - 1)
        assert previous is not None
        source = previous.item
        materialized = self._store.read_version(
            MemoryPartition.for_item(source), source.memory_item_id, source.memory_version
        )
        return materialized.payload, self._embedding(item, materialized.payload)

    def _commit_content_version(
        self,
        record: AdmittedMemoryVersion,
        binding: VerifiedGovernedContextBinding,
        content: tuple[bytes, tuple[float, ...] | None] | None = None,
    ) -> None:
        """Commit a lifecycle version with the (unchanged) content of its predecessor."""

        item = record.item
        stored = self._metadata.get(item.memory_item_id, item.memory_version)
        if stored is None or stored.state is not VersionState.COMMITTED:
            payload, embedding = content if content is not None else self._content_of(record)
            self._store.commit(record, payload=payload, embedding=embedding)
        self._invalidate_representations(record, binding)

    def _embedding(self, item: GovernedMemoryItem, payload: bytes) -> tuple[float, ...] | None:
        if RepresentationKind.VECTOR not in item.representation_kinds:
            return None
        if not isinstance(self._store, EmbeddingLifecycleCoordinator):
            raise MemoryLifecycleError(
                "REPRESENTATION_NOT_READY",
                "EMBEDDING_SOURCE_UNAVAILABLE",
                "no pinned embedding model can rebuild the vector of the new version",
            )
        values = self._store.embed_query(VectorProfile.for_item(item), lexical_document(payload))
        if item.embedding_digest is None or not hmac.compare_digest(
            vector_digest(values), item.embedding_digest
        ):
            raise MemoryLifecycleError(
                "REPRESENTATION_NOT_READY",
                "EMBEDDING_NOT_REPRODUCIBLE",
                "the pinned model does not reproduce the admitted embedding",
            )
        return values

    def _invalidate_representations(
        self, record: AdmittedMemoryVersion, binding: VerifiedGovernedContextBinding
    ) -> None:
        if record.item.lifecycle_status is S.ACTIVE or self._representations is None:
            return
        if not isinstance(self._store, EmbeddingLifecycleCoordinator):
            return
        models, representations = self._representations
        try:
            invalidate_all(
                self._store,
                models,
                representations,
                (MemoryPartition.for_item(record.item),),
                binding,
                f"lifecycle:{record.item.version_ref}",
            )
        except MemoryAdmissionError as exc:
            raise MemoryLifecycleError(
                "REPRESENTATION_NOT_READY",
                "REPRESENTATION_NOT_INVALIDATED",
                "parallel representations were not invalidated; a replay completes it",
            ) from exc

    # -- versions, ledger and receipts ----------------------------------------

    def _version(
        self,
        plan: _Plan,
        decision: MemoryPolicyDecision,
        *,
        deletion_epoch: int | None,
        target: LifecycleStatus | None = None,
        suffix: str = "",
        predecessor: AdmittedMemoryVersion | None = None,
    ) -> AdmittedMemoryVersion:
        """The next immutable version of the item carrying the lifecycle change."""

        head = predecessor if predecessor is not None else plan.head
        status = target if target is not None else plan.target
        now = self._clock.now()
        mapping = head.item.to_mapping()
        for name in ("correction_of_ref", "legal_hold_ref", "prior_lifecycle_status", "deletion_epoch"):
            mapping.pop(name, None)
        version = head.item.memory_version + 1
        mapping.update(
            memory_version=version,
            supersedes_ref=head.item.version_ref,
            lifecycle_status=status.value,
            created_at=format_utc_timestamp(now),
        )
        if status is S.LEGAL_HOLD:
            assert plan.legal_hold_ref is not None
            mapping["legal_hold_ref"] = plan.legal_hold_ref
            mapping["prior_lifecycle_status"] = head.item.lifecycle_status.value
        if status in DELETION_STATUSES:
            assert deletion_epoch is not None
            mapping["deletion_epoch"] = deletion_epoch
            # Deletion versions carry no projection: structured metadata only.
            mapping["representation_kinds"] = [RepresentationKind.STRUCTURED.value]
            for name in VECTOR_FIELDS:
                mapping.pop(name, None)
        item = GovernedMemoryItem.from_mapping(mapping)
        item_digest = item.digest()
        lifecycle_event = {
            "event_type": "MEMORY_LIFECYCLE",
            "operation": plan.action,
            "operation_id": plan.request.operation_id,
            "request_digest": plan.request_digest,
            "from_status": head.item.lifecycle_status.value,
            "to_status": status.value,
            "reason_code": plan.reason_code,
            "legal_hold_ref": plan.legal_hold_ref if status is S.LEGAL_HOLD else None,
            "deletion_epoch": deletion_epoch,
            "phase": suffix or "TRANSITION",
        }
        audit_event = {
            "action": plan.action,
            "outcome": "COMPLETED",
            "operation_id": plan.request.operation_id,
            "memory_version_ref": item.version_ref,
            "item_digest": item_digest,
            "from_status": head.item.lifecycle_status.value,
            "to_status": status.value,
            "reason_code": plan.reason_code,
            "request_digest": plan.request_digest,
            "policy_decision_ref": decision.decision_ref,
            "policy_bundle_digest": decision.policy_bundle_digest,
            "governed_context_digest": plan.request.gcs_digest,
            "binding_ref": plan.request.binding.binding_ref,
            "correlation_id": plan.request.context.correlation_id,
            "deletion_epoch": deletion_epoch,
            "at": format_utc_timestamp(now),
        }
        return AdmittedMemoryVersion(
            item=item,
            item_digest=item_digest,
            idempotency_key=idempotency_key(
                item, f"lifecycle:{plan.request.operation_id}{':' + suffix if suffix else ''}"
            ),
            lifecycle_event=MappingProxyType(lifecycle_event),
            audit_event=MappingProxyType(audit_event),
            receipt=MemoryReceipt(
                memory_item_id=item.memory_item_id,
                memory_version=version,
                content_digest=item.content_digest,
                lifecycle_status=status.value,
                governed_context_digest=item.governed_context_digest,
                audit_ref=canonical_digest(audit_event),
            ),
        )

    def _append(self, record: AdmittedMemoryVersion) -> None:
        try:
            self._ledger.append(record)
        except MemoryAdmissionError as exc:
            if exc.reason_code == "MEMORY_IDEMPOTENCY_CONFLICT":
                raise _invalid(
                    "CONCURRENT_TRANSITION", "another version was written concurrently"
                ) from exc
            raise

    def _key(self, memory_item_id: str, operation_id: str, suffix: str = "") -> tuple[str, str, str, str, str] | None:
        latest = self._ledger.latest_version(memory_item_id)
        record = self._ledger.get(memory_item_id, latest) if latest else None
        if record is None:
            return None
        return idempotency_key(record.item, f"lifecycle:{operation_id}{':' + suffix if suffix else ''}")

    def _recorded(self, memory_item_id: str, operation_id: str, suffix: str = "") -> AdmittedMemoryVersion | None:
        key = self._key(memory_item_id, operation_id, suffix)
        return None if key is None else self._ledger.by_idempotency_key(key)

    def _replay(
        self, memory_item_id: str, request: _Request, request_digest: str
    ) -> LifecycleReceipt | None:
        first = self._recorded(memory_item_id, request.operation_id) or self._recorded(
            memory_item_id, request.operation_id, "PENDING"
        )
        if first is None:
            return None
        if first.item.memory_item_id != memory_item_id or not hmac.compare_digest(
            str(first.lifecycle_event.get("request_digest")), request_digest
        ):
            raise MemoryLifecycleError(
                "MEMORY_IDEMPOTENCY_CONFLICT",
                "OPERATION_REUSED",
                "operation_id is bound to another lifecycle request",
            )
        if first.item.lifecycle_status is S.DELETION_PENDING:
            return self._resume_saga(first, request)
        self._commit_content_version(first, request.binding)
        return self._receipt(first, request, first)

    def _receipt(
        self,
        record: AdmittedMemoryVersion,
        request: _Request,
        audited: AdmittedMemoryVersion,
        *,
        status: str = "COMPLETED",
        tombstone: TombstoneEntry | None = None,
    ) -> LifecycleReceipt:
        event = dict(audited.audit_event)
        try:
            self._audit.record(event)
        except Exception as exc:  # noqa: BLE001 -- no receipt without its audit event
            raise MemoryLifecycleError(
                "CONTROL_PLANE_UNAVAILABLE",
                "AUDIT_UNAVAILABLE",
                "the operation could not be audited; a replay completes it",
            ) from exc
        receipt = {
            "operation_id": request.operation_id,
            "operation_kind": str(record.lifecycle_event.get("operation")),
            "status": status,
            "governed_context_digest": str(event["governed_context_digest"]),
            "audit_ref": audited.receipt.audit_ref,
        }
        return LifecycleReceipt(
            receipt=MappingProxyType(receipt),
            memory_version_ref=record.item.version_ref,
            lifecycle_status=record.item.lifecycle_status.value,
            deletion_epoch=record.item.deletion_epoch,
            tombstone_digest=None if tombstone is None else tombstone.digest,
        )

    # -- forgetting and the deletion saga ------------------------------------

    def _deletion_request(
        self, memory_item_id: str, request: _Request
    ) -> tuple[LifecycleReceipt, bool]:
        body = request.body
        reason = _reason(body["reason_code"])
        if reason not in FORGETTING_TRIGGERS:
            raise _schema_error("FORGETTING_TRIGGER_INVALID", "reason_code is not a forgetting trigger")
        scope = _string("deletion_scope", body["deletion_scope"])
        if scope not in DELETION_SCOPES:
            raise _schema_error("DELETION_SCOPE_INVALID", "deletion_scope is not declared")
        request_digest = canonical_digest(
            {
                "operation": OPERATION_DELETE,
                "memory_item_id": memory_item_id,
                "reason_code": reason,
                "deletion_scope": scope,
                "governed_context_digest": request.gcs_digest,
            }
        )
        replayed = self._replay(memory_item_id, request, request_digest)
        if replayed is not None:
            return replayed, True
        if scope not in SUPPORTED_DELETION_SCOPES:
            raise MemoryLifecycleError(
                "UNSUPPORTED_CAPABILITY",
                "DELETION_SCOPE_UNSUPPORTED",
                f"{scope} deletion is not supported; delete the item with ALL_VERSIONS",
            )
        head = self._committed_head(memory_item_id, request.context)
        plan = _Plan(
            action=OPERATION_DELETE,
            request=request,
            head=head,
            target=S.DELETION_PENDING,
            reason_code=reason,
            request_digest=request_digest,
        )
        return self._forget(plan), False

    def _check_forgettable(self, head: GovernedMemoryItem, context: GovernedContext) -> None:
        source = head.lifecycle_status
        if source is S.LEGAL_HOLD:
            self._require_released(head, context)
        elif S.DELETION_PENDING not in TRANSITIONS[source]:
            raise _invalid(
                "TRANSITION_NOT_DECLARED",
                f"{source.value} cannot enter deletion",
            )

    def _forget(self, plan: _Plan) -> LifecycleReceipt:
        context = plan.request.context
        head = plan.head.item
        if head.lifecycle_status is S.DELETION_PENDING:
            raise _invalid("DELETION_IN_PROGRESS", "the item is already being deleted")
        self._check_forgettable(head, context)
        decision = self._decide(plan.action, head, S.DELETION_PENDING, context)
        epoch = (
            head.deletion_epoch
            if head.lifecycle_status is S.DELETION_INCOMPLETE and head.deletion_epoch is not None
            else self._tombstones.latest_epoch() + 1
        )
        pending = self._version(plan, decision, deletion_epoch=epoch, suffix="PENDING")
        self._tombstone(pending, plan, TombstonePhase.STARTED, epoch)
        self._append(pending)
        self._commit_metadata_version(pending)
        return self._run_saga(pending, plan, decision)

    def _resume_saga(self, pending: AdmittedMemoryVersion, request: _Request) -> LifecycleReceipt:
        item_id = pending.item.memory_item_id
        done = self._recorded(item_id, request.operation_id, "OUTCOME")
        event = pending.lifecycle_event
        plan = _Plan(
            action=str(event.get("operation")),
            request=request,
            head=pending,
            target=S.DELETION_PENDING,
            reason_code=str(event.get("reason_code")),
            request_digest=str(event.get("request_digest")),
        )
        if done is not None:
            tombstone = self._last_tombstone(item_id)
            return self._receipt(
                done,
                request,
                done,
                status="COMPLETED" if done.item.lifecycle_status is S.DELETED else "FAILED",
                tombstone=tombstone if done.item.lifecycle_status is S.DELETED else None,
            )
        self._commit_metadata_version(pending)
        decision = MemoryPolicyDecision(
            permitted=True,
            decision_ref=str(pending.audit_event.get("policy_decision_ref")),
            policy_bundle_digest=str(pending.audit_event.get("policy_bundle_digest")),
        )
        return self._run_saga(pending, plan, decision)

    def _last_tombstone(self, memory_item_id: str) -> TombstoneEntry | None:
        entries = self._tombstones.entries(memory_item_id)
        return entries[-1] if entries else None

    def _commit_metadata_version(self, record: AdmittedMemoryVersion) -> None:
        """Commit a content-free deletion version in the metadata store only."""

        item = record.item
        existing = self._metadata.get(item.memory_item_id, item.memory_version)
        if existing is not None and existing.state is VersionState.COMMITTED:
            if not hmac.compare_digest(existing.staged.item_digest, record.item_digest):
                raise MemoryLifecycleError(
                    "INTERNAL_ERROR", "METADATA_SLOT_MISMATCH", "metadata holds another version"
                )
            return
        partition = MemoryPartition.for_item(item)
        pointer = RepresentationPointer(
            memory_version_ref=item.version_ref,
            item_digest=record.item_digest,
            content_digest=item.content_digest,
            representation_kind=RepresentationKind.STRUCTURED,
            representation_version=structured_representation_version(item),
            representation_digest=record.item_digest,
            partition_digest=partition.digest,
            classification_marking_ref=item.classification_marking_ref,
            policy_bundle_digest=item.policy_bundle_digest,
            memory_scope=item.memory_scope,
            deletion_epoch=item.deletion_epoch if item.deletion_epoch is not None else 0,
        )
        staged = StagedVersion(
            memory_item_id=item.memory_item_id,
            memory_version=item.memory_version,
            item=MappingProxyType(item.to_mapping()),
            item_digest=record.item_digest,
            audit_ref=record.receipt.audit_ref,
            partition=partition,
            content_object_ref=content_object_ref(partition, item.content_digest),
            pointers=(pointer,),
            staged_at=format_utc_timestamp(self._clock.now()),
        )
        try:
            stored = self._metadata.stage(staged)
            if stored.state is not VersionState.COMMITTED:
                committed = self._metadata.commit(
                    item.memory_item_id,
                    item.memory_version,
                    stage_digest=staged.stage_digest,
                    committed_at=format_utc_timestamp(self._clock.now()),
                )
                if committed.state is not VersionState.COMMITTED:
                    raise MemoryLifecycleError(
                        "INTERNAL_ERROR", "METADATA_COMMIT_NOT_APPLIED", "metadata commit was not applied"
                    )
        except MemoryAdmissionError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a lost metadata commit fails closed
            raise MemoryLifecycleError(
                "REPRESENTATION_NOT_READY",
                "LIFECYCLE_COMMIT_INCOMPLETE",
                f"{item.version_ref} is not committed; a replay completes it: {type(exc).__name__}",
            ) from exc
        self._retire(item.memory_item_id, item.memory_version)

    def _versions(self, memory_item_id: str, upto: int) -> tuple[StoredVersion, ...]:
        found = []
        for version in range(1, upto + 1):
            stored = self._metadata.get(memory_item_id, version)
            if stored is not None and stored.state is VersionState.COMMITTED:
                found.append(stored)
        return tuple(found)

    def _retire(self, memory_item_id: str, below_version: int) -> None:
        """Mark every earlier projection of the item superseded (out of every query)."""

        layouts: set[tuple[str, MemoryPartition, RepresentationKind, str]] = set()
        for stored in self._versions(memory_item_id, below_version - 1):
            for pointer in stored.staged.pointers:
                if pointer.representation_kind is not RepresentationKind.STRUCTURED:
                    layouts.add(
                        (
                            stored.staged.partition.digest,
                            stored.staged.partition,
                            pointer.representation_kind,
                            pointer.representation_version,
                        )
                    )
        try:
            for _, partition, kind, version in sorted(layouts, key=lambda x: (x[0], x[2].value, x[3])):
                index = self._lexical if kind is RepresentationKind.FULL_TEXT else self._vector
                if isinstance(index, EligibilityIndexPort):
                    index.retire(partition, version, memory_item_id, below_version)
        except Exception as exc:  # noqa: BLE001 -- the saga removes them anyway; fail closed
            raise MemoryLifecycleError(
                "REPRESENTATION_NOT_READY",
                "PREDECESSOR_NOT_RETIRED",
                "earlier projections were not retired; a replay completes it",
            ) from exc

    def _tombstone(
        self,
        record: AdmittedMemoryVersion,
        plan: _Plan,
        phase: str,
        epoch: int,
        *,
        residue: Mapping[str, int] | None = None,
        retained: int = 0,
    ) -> TombstoneEntry:
        item = record.item
        versions = self._versions(item.memory_item_id, item.memory_version - 1)
        refs = sorted({s.staged.memory_version_ref for s in versions} | {item.version_ref})
        partitions = sorted(
            {s.staged.partition.digest for s in versions} | {MemoryPartition.for_item(item).digest}
        )
        entry = TombstoneEntry(
            memory_item_id=item.memory_item_id,
            tenant_id=item.tenant_id,
            partition_digests=tuple(partitions),
            version_refs=tuple(refs),
            deletion_epoch=epoch,
            phase=phase,
            reason_code=plan.reason_code,
            operation_id=plan.request.operation_id,
            participants=tuple(p.name for p in self._participants),
            residue_counts=tuple(sorted((residue or {}).items())),
            retained_shared_objects=retained,
            at=format_utc_timestamp(self._clock.now()),
        )
        try:
            self._tombstones.append(entry)
        except MemoryAdmissionError:
            raise
        except Exception as exc:  # noqa: BLE001 -- no saga step without its journal entry
            raise MemoryLifecycleError(
                "CONTROL_PLANE_UNAVAILABLE",
                "TOMBSTONE_JOURNAL_UNAVAILABLE",
                "the deletion journal could not be written",
            ) from exc
        return entry

    def _run_saga(
        self, pending: AdmittedMemoryVersion, plan: _Plan, decision: MemoryPolicyDecision
    ) -> LifecycleReceipt:
        item = pending.item
        epoch = item.deletion_epoch
        assert epoch is not None
        target = DeletionTarget(
            memory_item_id=item.memory_item_id,
            versions=self._versions(item.memory_item_id, item.memory_version - 1),
            deletion_epoch=epoch,
            operation_id=plan.request.operation_id,
            binding=plan.request.binding,
        )
        residue: dict[str, int] = {}
        retained = 0
        for participant in self._participants:
            try:
                participant.purge(target)
            except Exception:  # noqa: BLE001 -- a failed purge shows up as residue
                self.metrics[("deletionParticipant", "INCOMPLETE", participant.name)] += 1
            try:
                left = participant.residue(target)
            except Exception:  # noqa: BLE001 -- an unreadable participant is residue
                left = ("UNVERIFIABLE",)
            if left:
                residue[participant.name] = len(left)
            if isinstance(participant, ContentParticipant):
                retained = len(participant.retained(target))
        final = S.DELETED if not residue else S.DELETION_INCOMPLETE
        outcome = self._version(
            plan,
            decision,
            deletion_epoch=epoch,
            target=final,
            suffix="OUTCOME",
            predecessor=pending,
        )
        tombstone = self._tombstone(
            outcome,
            plan,
            TombstonePhase.COMPLETED if final is S.DELETED else TombstonePhase.INCOMPLETE,
            epoch,
            residue=residue,
            retained=retained,
        )
        self._append(outcome)
        self._commit_metadata_version(outcome)
        return self._receipt(
            outcome,
            plan.request,
            outcome,
            status="COMPLETED" if final is S.DELETED else "FAILED",
            tombstone=tombstone if final is S.DELETED else None,
        )

    # -- sweeps ----------------------------------------------------------------

    def _sweep(
        self,
        kind: str,
        binding: VerifiedGovernedContextBinding | None,
        operation_id: str,
        limit: int | None,
    ) -> SweepReport:
        failure = _Failure(operation_id=operation_id if isinstance(operation_id, str) else None)
        try:
            if not isinstance(binding, VerifiedGovernedContextBinding):
                raise MemoryLifecycleError(
                    "AUTHENTICATION_REQUIRED",
                    "BINDING_MISSING",
                    "lifecycle sweeps require an authenticated governed-context binding",
                )
            failure.correlation_id = binding.expected.correlation_id
            failure.binding_ref = binding.binding_ref
            failure.gcs_digest = binding.expected.digest()
            op = _string("operation_id", operation_id)
            if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
                raise _schema_error("LIMIT_INVALID", "limit must be a positive integer")
            with self._lock:
                report = self._run_sweep(kind, binding, op, limit)
            self.metrics[(kind, "COMPLETED", "NONE")] += 1
            return report
        except MemoryAdmissionError as exc:
            if exc.correlation_id is None:
                exc.correlation_id = failure.correlation_id
            self._record_denial(kind, exc, failure)
            raise

    def _due(self, kind: str, item: GovernedMemoryItem) -> datetime | None:
        if kind == OPERATION_EXPIRY:
            if item.lifecycle_status is not S.ACTIVE or item.expires_at is None:
                return None
            return item.expires_at
        if item.lifecycle_status in (S.DELETED, S.DELETION_PENDING):
            return None
        # Retention runs from the admission of the item, not of its latest version.
        first = self._ledger.get(item.memory_item_id, 1)
        horizon = self._horizons.get(item.retention_policy_ref)
        if first is None or horizon is None:
            return None
        return first.item.created_at + horizon

    def _run_sweep(
        self,
        kind: str,
        binding: VerifiedGovernedContextBinding,
        operation_id: str,
        limit: int | None,
    ) -> SweepReport:
        context = binding.expected
        now = self._clock.now()
        candidates: list[tuple[datetime, str, AdmittedMemoryVersion]] = []
        unresolved: list[str] = []
        seen: set[str] = set()
        for partition in sorted(self._metadata.partitions(), key=lambda p: p.digest):
            for stored in self._metadata.versions_in(partition.digest):
                item_id = stored.staged.memory_item_id
                if item_id in seen:
                    continue
                seen.add(item_id)
                head = self.head(item_id)
                if head is None or not self._visible(head.item, context):
                    continue
                if kind == OPERATION_RETENTION and (
                    head.item.retention_policy_ref not in self._horizons
                    and head.item.lifecycle_status not in (S.DELETED, S.DELETION_PENDING)
                ):
                    unresolved.append(head.item.version_ref)
                    continue
                due = self._due(kind, head.item)
                if due is not None and due <= now:
                    candidates.append((due, item_id, head))
        candidates.sort(key=lambda entry: (entry[0], entry[1]))
        processed: list[str] = []
        held: list[str] = []
        incomplete: list[str] = []
        deferred: list[str] = []
        for _, item_id, head in candidates:
            if head.item.lifecycle_status is S.LEGAL_HOLD:
                held.append(head.item.version_ref)
                continue
            target = S.EXPIRED if kind == OPERATION_EXPIRY else S.DELETION_PENDING
            if target not in TRANSITIONS[head.item.lifecycle_status]:
                unresolved.append(head.item.version_ref)
                continue
            if limit is not None and len(processed) + len(incomplete) >= limit:
                deferred.append(head.item.version_ref)
                continue
            reason = "EXPIRY" if kind == OPERATION_EXPIRY else "RETENTION_ELAPSED"
            item_op = f"{operation_id}:{item_id}"
            request = _Request(
                operation_id=item_op,
                context=context,
                gcs_digest=context.digest(),
                deadline=now,
                body=MappingProxyType({}),
                binding=binding,
            )
            request_digest = canonical_digest(
                {"operation": kind, "memory_item_id": item_id, "version": head.item.memory_version}
            )
            plan = _Plan(
                action=kind,
                request=request,
                head=head,
                target=target,
                reason_code=reason,
                request_digest=request_digest,
            )
            receipt = self._forget(plan) if target is S.DELETION_PENDING else self._apply(plan)
            if receipt.lifecycle_status == S.DELETION_INCOMPLETE.value:
                incomplete.append(receipt.memory_version_ref)
            else:
                processed.append(receipt.memory_version_ref)
        event = {
            "action": kind,
            "outcome": "COMPLETED",
            "operation_id": operation_id,
            "processed": processed,
            "held": held,
            "incomplete": incomplete,
            "unresolved": sorted(unresolved),
            "deferred": deferred,
            "governed_context_digest": context.digest(),
            "binding_ref": binding.binding_ref,
            "correlation_id": context.correlation_id,
            "at": format_utc_timestamp(now),
        }
        try:
            self._audit.record(event)
        except Exception as exc:  # noqa: BLE001 -- no report without its audit event
            raise MemoryLifecycleError(
                "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE", "the sweep could not be audited"
            ) from exc
        return SweepReport(
            operation_id=operation_id,
            operation_kind=kind,
            processed=tuple(processed),
            held=tuple(held),
            incomplete=tuple(incomplete),
            unresolved=tuple(sorted(unresolved)),
            deferred=tuple(deferred),
            audit_ref=canonical_digest(event),
        )


__all__ = [
    "ContentParticipant",
    "DeletionParticipant",
    "DeletionTarget",
    "FORGETTING_TRIGGERS",
    "InMemoryTombstoneStore",
    "JournalTombstoneStore",
    "LegalHoldRegistry",
    "LegalHoldStatus",
    "LifecycleAuditSink",
    "LifecycleGuardPolicy",
    "LifecyclePolicy",
    "LifecycleReceipt",
    "MemoryLifecycleCoordinator",
    "MemoryLifecycleError",
    "MemoryTombstoneStore",
    "NativeProjectionParticipant",
    "RepresentationParticipant",
    "SweepReport",
    "TRANSITIONS",
    "TombstoneEntry",
    "TombstonePhase",
    "invalidate_all",
]
