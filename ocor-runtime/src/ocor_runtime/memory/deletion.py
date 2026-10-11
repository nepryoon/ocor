"""C8 deletion journal checkpoint and closed restore boundary.

ADD v1.3 Part II §§2.10/2.13 and LLD v1.1 §§2.8.6/5.4 require tombstone
replay before reopening restored retrieval, including unfinished deletions.
A structurally valid hash chain alone cannot detect a removed suffix.  Reads
therefore require the exact sequence, head and deletion epoch supplied by a
trusted checkpoint authority, independent of the restored file.

``capture`` validates and inventories a journal; it does NOT authenticate it.
The recovery/manifest provider must authenticate the checkpoint and bind it to
the selected recovery point before implementing ``current``.  A caller or the
restored backup itself must never supply that authority.

The gate starts closed, purges and inventories every obligation, rechecks the
authority and journal, and invalidates its receipt on any failure. ``serve``
rechecks both the checkpoint and residue before and after the callback; its
callback must only materialise a response, never dispatch an external effect.
All restored query entry points must go through this gate.  This module does
not implement a runtime composition or declare backend/runtime conformance.
"""

from __future__ import annotations

import fcntl
import hmac
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from ..kernel.canonical import canonical_bytes, canonical_digest, parse_i_json, parse_utc_timestamp
from ..kernel.governed_context import VerifiedGovernedContextBinding
from .lifecycle import DeletionParticipant, DeletionTarget, InMemoryTombstoneStore, TombstoneEntry, TombstonePhase
from .model import AdmittedMemoryVersion, LifecycleStatus, MemoryVersionLedger
from .stores import MemoryMetadataStore, StoredVersion, VersionState

GENESIS = "urn:sha256:" + "0" * 64
T = TypeVar("T")


class DeletionRecoveryError(RuntimeError):
    """Stable recovery code; no content, backend error text or opaque refs."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class DeletionJournalCheckpoint:
    sequence: int
    head: str
    deletion_epoch: int

    def __post_init__(self) -> None:
        if (
            type(self.sequence) is not int or self.sequence < 0
            or type(self.deletion_epoch) is not int or self.deletion_epoch < 0
            or self.deletion_epoch > self.sequence
            or not isinstance(self.head, str)
            or re.fullmatch(r"urn:sha256:[0-9a-f]{64}", self.head) is None
            or (self.sequence == 0 and (self.head != GENESIS or self.deletion_epoch != 0))
            or (self.sequence > 0 and (self.head == GENESIS or self.deletion_epoch == 0))
        ):
            raise DeletionRecoveryError("CHECKPOINT_INVALID")

    def to_mapping(self) -> dict[str, object]:
        return {"sequence": self.sequence, "head": self.head, "deletion_epoch": self.deletion_epoch}

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


@dataclass(frozen=True, slots=True)
class DeletionJournalSnapshot:
    checkpoint: DeletionJournalCheckpoint
    entries: tuple[TombstoneEntry, ...]

    @property
    def obligations(self) -> tuple[TombstoneEntry, ...]:
        latest: dict[str, TombstoneEntry] = {}
        for entry in self.entries:
            latest[entry.memory_item_id] = entry
        return tuple(sorted(latest.values(), key=lambda e: (e.deletion_epoch, e.memory_item_id)))

    @classmethod
    def capture(cls, path: Path) -> DeletionJournalSnapshot:
        try:
            with path.open("rb") as handle:
                fcntl.flock(handle, fcntl.LOCK_SH)
                try:
                    data = handle.read()
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
            return cls._decode(data)
        except DeletionRecoveryError:
            raise
        except Exception as exc:  # noqa: BLE001 -- no unverifiable journal can reopen restore
            raise DeletionRecoveryError("JOURNAL_UNAVAILABLE") from exc

    @classmethod
    def _decode(cls, data: bytes) -> DeletionJournalSnapshot:
        try:
            return cls._decode_checked(data)
        except DeletionRecoveryError:
            raise
        except Exception as exc:  # noqa: BLE001 -- parsing, epoch and schema errors fail closed
            raise DeletionRecoveryError("JOURNAL_CORRUPTED") from exc

    @classmethod
    def _decode_checked(cls, data: bytes) -> DeletionJournalSnapshot:
        if data and not data.endswith(b"\n"):
            raise DeletionRecoveryError("JOURNAL_CORRUPTED")
        entries: list[TombstoneEntry] = []
        previous = GENESIS
        memory = InMemoryTombstoneStore()
        history: dict[str, TombstoneEntry] = {}
        for sequence, line in enumerate(data.splitlines(), start=1):
            chained = parse_i_json(line)
            if not isinstance(chained, Mapping) or set(chained) != {"seq", "prev", "entry", "entry_digest"}:
                raise DeletionRecoveryError("JOURNAL_CORRUPTED")
            if (
                type(chained["seq"]) is not int or chained["seq"] != sequence
                or chained["prev"] != previous or canonical_bytes(chained) != line
                or not isinstance(chained["entry_digest"], str)
            ):
                raise DeletionRecoveryError("JOURNAL_CORRUPTED")
            body = {"seq": sequence, "prev": previous, "entry": chained["entry"]}
            digest = canonical_digest(body)
            if not hmac.compare_digest(digest, chained["entry_digest"]):
                raise DeletionRecoveryError("JOURNAL_CORRUPTED")
            entry = TombstoneEntry.from_mapping(chained["entry"])
            cls._validate_entry(entry, history.get(entry.memory_item_id))
            memory.append(entry)  # same epoch reservation/terminal oracle as the writer
            history[entry.memory_item_id] = entry
            entries.append(entry)
            previous = digest
        checkpoint = DeletionJournalCheckpoint(len(entries), previous, memory.latest_epoch())
        return cls(checkpoint, tuple(entries))

    @staticmethod
    def _validate_entry(entry: TombstoneEntry, prior: TombstoneEntry | None) -> None:
        parse_utc_timestamp(entry.at)
        groups = (entry.partition_digests, entry.version_refs, entry.participants)
        if (
            any(not values or len(set(values)) != len(values) for values in groups)
            or any(re.fullmatch(r"urn:sha256:[0-9a-f]{64}", d) is None for d in entry.partition_digests)
            or any(not ref.startswith(f"urn:ocor:memory:{entry.memory_item_id}:v")
                   or not ref.removeprefix(f"urn:ocor:memory:{entry.memory_item_id}:v").isdigit()
                   or int(ref.removeprefix(f"urn:ocor:memory:{entry.memory_item_id}:v")) < 1
                   for ref in entry.version_refs)
            or any(re.fullmatch(r"[a-z][a-z0-9-]*", name) is None for name in entry.participants)
            or len({n for n, _ in entry.residue_counts}) != len(entry.residue_counts)
            or any(n not in entry.participants for n, _ in entry.residue_counts)
            or (entry.phase == TombstonePhase.COMPLETED and bool(entry.residue_counts))
        ):
            raise DeletionRecoveryError("JOURNAL_CORRUPTED")
        if prior is not None and (
            entry.tenant_id != prior.tenant_id
            or entry.deletion_epoch != prior.deletion_epoch
            or not set(prior.partition_digests) <= set(entry.partition_digests)
            or not set(prior.version_refs) <= set(entry.version_refs)
            or entry.participants != prior.participants
        ):
            raise DeletionRecoveryError("JOURNAL_CORRUPTED")

    @classmethod
    def read(cls, path: Path, *, expected: DeletionJournalCheckpoint) -> DeletionJournalSnapshot:
        if not isinstance(expected, DeletionJournalCheckpoint):
            raise DeletionRecoveryError("CHECKPOINT_INVALID")
        snapshot = cls.capture(path)
        if snapshot.checkpoint != expected:
            raise DeletionRecoveryError("CHECKPOINT_MISMATCH")
        return snapshot


class DeletionCheckpointAuthority(Protocol):
    """Authenticated current checkpoint, independent of the restored journal.

    Provider verifies the signed recovery manifest and the current deletion
    authority (post-backup deletions included), never caller-provided counters.
    """

    def current(self) -> DeletionJournalCheckpoint: ...


class RestoredDeletionParticipant(Protocol):
    """Recovery participant: every version of the item in the full isolation tuple.

    Must check tenant and partition binding, include all its copies, and refuse
    unknown versions or scope. Purge is idempotent. Unreadable inventory raises;
    it must never be represented as an empty inventory.
    """

    name: str

    def purge(self, tombstone: TombstoneEntry) -> None: ...

    def residue(self, tombstone: TombstoneEntry) -> tuple[str, ...]: ...


class MemoryDeletionMetadataReplay:
    """Replay exact original deletion metadata, never mint a replacement event.

    The source ports must belong to the authenticated deletion authority used
    by the checkpoint provider. Only the disposable restored stores are
    mutated. Ledger events and audit refs are copied unchanged; no canonical
    commit, lifecycle request, fresh event id or external dispatch is emitted.
    Configure this participant before indexes/content so eligibility is
    excluded before projection rebuild. Missing source records keep restore
    closed until the source's interrupted deletion has been completed.
    """

    name = "memory-metadata"

    def __init__(
        self, *, authoritative_metadata: MemoryMetadataStore,
        authoritative_ledger: MemoryVersionLedger, restored_metadata: MemoryMetadataStore,
        restored_ledger: MemoryVersionLedger,
    ) -> None:
        self._source = authoritative_metadata
        self._source_ledger = authoritative_ledger
        self._restored = restored_metadata
        self._restored_ledger = restored_ledger

    def purge(self, tombstone: TombstoneEntry) -> None:
        versions = self._source_versions(tombstone)
        limit = len(versions)
        if self._restored.head(tombstone.memory_item_id) > limit or self._restored_ledger.latest_version(tombstone.memory_item_id) > limit:
            raise DeletionRecoveryError("RESTORE_METADATA_CONFLICT")
        # Validate the whole restored prefix before changing any version.
        for record, stored in versions:
            item_id, version = record.item.memory_item_id, record.item.memory_version
            existing_record = self._restored_ledger.get(item_id, version)
            existing_stored = self._restored.get(item_id, version)
            if (
                existing_record is not None and existing_record.to_mapping() != record.to_mapping()
                or existing_stored is not None and existing_stored.staged.stage_digest != stored.staged.stage_digest
            ):
                raise DeletionRecoveryError("RESTORE_METADATA_CONFLICT")
        for record, stored in versions:
            item_id, version = record.item.memory_item_id, record.item.memory_version
            if self._restored_ledger.get(item_id, version) is None:
                self._restored_ledger.append(record)
            existing = self._restored.stage(stored.staged)
            if existing.state is not VersionState.COMMITTED:
                assert stored.committed_at is not None  # checked in _source_versions
                self._restored.commit(
                    item_id, version, stage_digest=stored.staged.stage_digest,
                    committed_at=stored.committed_at,
                )

    def residue(self, tombstone: TombstoneEntry) -> tuple[str, ...]:
        versions = self._source_versions(tombstone)
        item_id = tombstone.memory_item_id
        if self._restored.head(item_id) != len(versions) or self._restored_ledger.latest_version(item_id) != len(versions):
            return (item_id,)
        for record, stored in versions:
            version = record.item.memory_version
            found_record = self._restored_ledger.get(item_id, version)
            found_stored = self._restored.get(item_id, version)
            if (
                found_record is None or found_record.to_mapping() != record.to_mapping()
                or found_stored is None or found_stored.state is not VersionState.COMMITTED
                or found_stored.staged.stage_digest != stored.staged.stage_digest
            ):
                return (item_id,)
        return ()

    def _source_versions(self, tombstone: TombstoneEntry) -> tuple[tuple[AdmittedMemoryVersion, StoredVersion], ...]:
        item_id = tombstone.memory_item_id
        head = self._source.head(item_id)
        if type(head) is not int or head < 1 or self._source_ledger.latest_version(item_id) != head:
            raise DeletionRecoveryError("DELETION_SOURCE_INCOMPLETE")
        if set(tombstone.version_refs) != {f"urn:ocor:memory:{item_id}:v{v}" for v in range(1, head + 1)}:
            raise DeletionRecoveryError("DELETION_SOURCE_MISMATCH")
        versions = []
        for version in range(1, head + 1):
            record = self._source_ledger.get(item_id, version)
            stored = self._source.get(item_id, version)
            if record is None or stored is None or stored.state is not VersionState.COMMITTED or stored.committed_at is None:
                raise DeletionRecoveryError("DELETION_SOURCE_INCOMPLETE")
            record.verify()
            item = stored.staged.verify()
            if (
                item.memory_item_id != item_id or item.memory_version != version
                or item.tenant_id != tombstone.tenant_id
                or stored.staged.partition.digest not in tombstone.partition_digests
                or item.digest() != record.item_digest
            ):
                raise DeletionRecoveryError("DELETION_SOURCE_MISMATCH")
            versions.append((record, stored))
        expected_status = {
            TombstonePhase.STARTED: LifecycleStatus.DELETION_PENDING,
            TombstonePhase.INCOMPLETE: LifecycleStatus.DELETION_INCOMPLETE,
            TombstonePhase.COMPLETED: LifecycleStatus.DELETED,
        }.get(tombstone.phase)
        item = versions[-1][0].item
        if item.lifecycle_status is not expected_status or item.deletion_epoch != tombstone.deletion_epoch:
            raise DeletionRecoveryError("DELETION_SOURCE_MISMATCH")
        return tuple(versions)


class RestoredMemoryParticipant:
    """Adapt an existing 0055 participant to the checkpoint-bound restore saga.

    Configured recovery binding and stores are trusted composition inputs;
    public query callers cannot provide them. Every version is validated
    against the tombstone's tenant, partitions and exact version refs before
    the underlying participant receives a target.
    """

    def __init__(
        self, *, metadata: MemoryMetadataStore, participant: DeletionParticipant,
        binding: VerifiedGovernedContextBinding,
    ) -> None:
        self.name = participant.name
        self._metadata = metadata
        self._participant = participant
        self._binding = binding

    def _target(self, tombstone: TombstoneEntry) -> DeletionTarget:
        if not isinstance(self._binding, VerifiedGovernedContextBinding) or self._binding.expected.tenant_id != tombstone.tenant_id:
            raise DeletionRecoveryError("RESTORE_BINDING_MISMATCH")
        versions = []
        prefix = f"urn:ocor:memory:{tombstone.memory_item_id}:v"
        for ref in tombstone.version_refs:
            if not ref.startswith(prefix) or not ref[len(prefix):].isdigit():
                raise DeletionRecoveryError("DELETION_SOURCE_MISMATCH")
            version = int(ref[len(prefix):])
            stored = self._metadata.get(tombstone.memory_item_id, version)
            if stored is None or stored.state is not VersionState.COMMITTED:
                raise DeletionRecoveryError("DELETION_SOURCE_INCOMPLETE")
            item = stored.staged.verify()
            if (
                item.version_ref != ref or item.tenant_id != tombstone.tenant_id
                or stored.staged.partition.digest not in tombstone.partition_digests
            ):
                raise DeletionRecoveryError("RESTORE_BINDING_MISMATCH")
            versions.append(stored)
        return DeletionTarget(
            memory_item_id=tombstone.memory_item_id, versions=tuple(versions),
            deletion_epoch=tombstone.deletion_epoch, operation_id=tombstone.operation_id,
            binding=self._binding,
        )

    def purge(self, tombstone: TombstoneEntry) -> None:
        self._participant.purge(self._target(tombstone))

    def residue(self, tombstone: TombstoneEntry) -> tuple[str, ...]:
        return self._participant.residue(self._target(tombstone))


@dataclass(frozen=True, slots=True)
class DeletionReconciliationReceipt:
    checkpoint: DeletionJournalCheckpoint
    obligations: int


class DeletionRestoreGate:
    def __init__(
        self, *, journal: Path, authority: DeletionCheckpointAuthority,
        participants: Sequence[RestoredDeletionParticipant],
    ) -> None:
        names = [participant.name for participant in participants]
        if not names or len(set(names)) != len(names) or any(
            not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9-]*", name) is None
            for name in names
        ):
            raise ValueError("restore participants require non-empty unique names")
        self._journal = journal
        self._authority = authority
        self._participants = tuple(participants)
        self._lock = threading.RLock()
        self._snapshot: DeletionJournalSnapshot | None = None

    def _checkpoint(self) -> DeletionJournalCheckpoint:
        try:
            checkpoint = self._authority.current()
        except Exception as exc:  # noqa: BLE001 -- provider authentication/outage fails closed
            raise DeletionRecoveryError("DELETION_AUTHORITY_UNAVAILABLE") from exc
        if not isinstance(checkpoint, DeletionJournalCheckpoint):
            raise DeletionRecoveryError("CHECKPOINT_INVALID")
        return checkpoint

    def _check(self, snapshot: DeletionJournalSnapshot) -> None:
        expected = self._checkpoint()
        if expected != snapshot.checkpoint:
            raise DeletionRecoveryError("CHECKPOINT_MISMATCH")
        DeletionJournalSnapshot.read(self._journal, expected=expected)
        self._validate_participants(snapshot)
        for entry in snapshot.obligations:
            for participant in self._participants:
                try:
                    residue = participant.residue(entry)
                except Exception as exc:  # noqa: BLE001 -- unreadable is not empty
                    raise DeletionRecoveryError("DELETION_INVENTORY_UNAVAILABLE") from exc
                if not isinstance(residue, tuple) or residue:
                    raise DeletionRecoveryError("DELETION_INCOMPLETE")
        # A journal update during inventory cannot leave the old receipt valid.
        if self._checkpoint() != expected:
            raise DeletionRecoveryError("CHECKPOINT_MISMATCH")

    def _validate_participants(self, snapshot: DeletionJournalSnapshot) -> None:
        names = {participant.name for participant in self._participants}
        if any(not set(entry.participants) <= names for entry in snapshot.obligations):
            raise DeletionRecoveryError("DELETION_PARTICIPANT_MISSING")

    def reconcile(self) -> DeletionReconciliationReceipt:
        with self._lock:
            self._snapshot = None
            snapshot = DeletionJournalSnapshot.read(self._journal, expected=self._checkpoint())
            self._validate_participants(snapshot)
            for entry in snapshot.obligations:
                for participant in self._participants:
                    try:
                        participant.purge(entry)
                    except Exception as exc:  # noqa: BLE001 -- failed purge cannot reopen restore
                        raise DeletionRecoveryError("DELETION_INCOMPLETE") from exc
            self._check(snapshot)
            receipt = DeletionReconciliationReceipt(snapshot.checkpoint, len(snapshot.obligations))
            self._snapshot = snapshot
            return receipt

    def serve(self, action: Callable[[], T]) -> T:
        with self._lock:
            snapshot = self._snapshot
            if snapshot is None:
                raise DeletionRecoveryError("RESTORE_NOT_RECONCILED")
            try:
                self._check(snapshot)
                response = action()
                self._check(snapshot)
                return response
            except BaseException:
                self._snapshot = None
                raise
