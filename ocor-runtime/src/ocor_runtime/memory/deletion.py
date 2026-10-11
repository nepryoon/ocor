"""C8 deletion recovery boundary (implementation in progress)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from .lifecycle import TombstoneEntry

GENESIS = "urn:sha256:" + "0" * 64
T = TypeVar("T")


class DeletionRecoveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DeletionJournalCheckpoint:
    sequence: int
    head: str
    deletion_epoch: int


@dataclass(frozen=True, slots=True)
class DeletionJournalSnapshot:
    checkpoint: DeletionJournalCheckpoint
    entries: tuple[TombstoneEntry, ...]

    @property
    def obligations(self) -> tuple[TombstoneEntry, ...]:
        return ()

    @classmethod
    def capture(cls, path: Path) -> DeletionJournalSnapshot:
        return cls(DeletionJournalCheckpoint(0, GENESIS, 0), ())

    @classmethod
    def read(cls, path: Path, *, expected: DeletionJournalCheckpoint) -> DeletionJournalSnapshot:
        return cls.capture(path)


class DeletionCheckpointAuthority(Protocol):
    def current(self) -> DeletionJournalCheckpoint: ...


class RestoredDeletionParticipant(Protocol):
    name: str

    def purge(self, tombstone: TombstoneEntry) -> None: ...

    def residue(self, tombstone: TombstoneEntry) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class DeletionReconciliationReceipt:
    checkpoint: DeletionJournalCheckpoint
    obligations: int


class DeletionRestoreGate:
    def __init__(
        self, *, journal: Path, authority: DeletionCheckpointAuthority,
        participants: Sequence[RestoredDeletionParticipant],
    ) -> None:
        self._journal = journal
        self._authority = authority
        self._participants = tuple(participants)

    def reconcile(self) -> DeletionReconciliationReceipt:
        return DeletionReconciliationReceipt(self._authority.current(), 0)

    def serve(self, action: Callable[[], T]) -> T:
        return action()
