"""0056 — deletion journal checkpoints and the closed restore boundary.

ADD v1.3 Part II §§2.10/2.13, LLD v1.1 §§2.8.6/5.4/7.2:
restored backups cannot reopen retrieval before deletion reconciliation.
These deterministic cases exercise journal integrity, not backend qualification.
Live deletion of every representation and recovery qualification remain required.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from ocor_runtime.kernel.canonical import canonical_bytes, canonical_digest, parse_i_json
from ocor_runtime.memory.deletion import (
    DeletionJournalSnapshot,
    DeletionRecoveryError,
    DeletionRestoreGate,
)
from ocor_runtime.memory.lifecycle import JournalTombstoneStore, TombstoneEntry, TombstonePhase


def entry(item: str, epoch: int, phase: str) -> TombstoneEntry:
    return TombstoneEntry(
        memory_item_id=item,
        tenant_id="tenant-a",
        partition_digests=("urn:sha256:" + "a" * 64,),
        version_refs=(f"urn:ocor:memory:{item}:v1",),
        deletion_epoch=epoch,
        phase=phase,
        reason_code="AUTHORIZED_REQUEST",
        operation_id=f"delete-{item}",
        participants=("content", "native-projections"),
        residue_counts=(),
        retained_shared_objects=0,
        at="2026-10-11T06:30:00.000000Z",
    )


def journal(path: Path) -> JournalTombstoneStore:
    source = JournalTombstoneStore(path)
    source.append(entry("x", 1, TombstonePhase.STARTED))
    source.append(entry("x", 1, TombstonePhase.COMPLETED))
    source.append(entry("y", 2, TombstonePhase.STARTED))
    source.append(entry("y", 2, TombstonePhase.INCOMPLETE))
    return source


def test_complete_journal_roundtrips_exact_order_and_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    journal(path)
    captured = DeletionJournalSnapshot.capture(path)
    read = DeletionJournalSnapshot.read(path, expected=captured.checkpoint)
    assert read == captured
    assert read.checkpoint.sequence == 4 and read.checkpoint.deletion_epoch == 2
    assert [(e.memory_item_id, e.phase) for e in read.entries] == [
        ("x", "STARTED"), ("x", "COMPLETED"), ("y", "STARTED"), ("y", "INCOMPLETE"),
    ]
    assert [e.memory_item_id for e in read.obligations] == ["x", "y"]
    assert read.obligations[1].phase == "INCOMPLETE"  # incomplete sagas also forbid resurrection


def test_empty_journal_needs_an_explicit_empty_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    JournalTombstoneStore(path)
    captured = DeletionJournalSnapshot.capture(path)
    assert captured.checkpoint.sequence == captured.checkpoint.deletion_epoch == 0
    assert captured.obligations == ()
    assert DeletionJournalSnapshot.read(path, expected=captured.checkpoint) == captured


@pytest.mark.parametrize("attack", ["valid-prefix", "empty", "permutation", "torn", "body", "noncanonical", "duplicate"])
def test_changed_journal_cannot_match_the_authority_checkpoint(tmp_path: Path, attack: str) -> None:
    path = tmp_path / "journal.jsonl"
    journal(path)
    checkpoint = DeletionJournalSnapshot.capture(path).checkpoint
    lines = path.read_bytes().splitlines(keepends=True)
    if attack == "valid-prefix":
        altered = b"".join(lines[:2])
    elif attack == "empty":
        altered = b""
    elif attack == "permutation":
        altered = b"".join([lines[0], lines[2], lines[1], lines[3]])
    elif attack == "torn":
        altered = b"".join(lines)[:-2]
    elif attack == "body":
        altered = b"".join(lines).replace(b'"tenant-a"', b'"tenant-b"')
    elif attack == "noncanonical":
        altered = b"".join(lines).replace(b'{"', b'{ "', 1)
    else:
        altered = b"".join([*lines, lines[-1]])
    path.write_bytes(altered)
    with pytest.raises(DeletionRecoveryError):
        DeletionJournalSnapshot.read(path, expected=checkpoint)


def test_an_entirely_rehashed_replacement_still_fails_the_pinned_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    journal(path)
    checkpoint = DeletionJournalSnapshot.capture(path).checkpoint
    replacement = tmp_path / "replacement.jsonl"
    source = JournalTombstoneStore(replacement)
    source.append(entry("z", 1, TombstonePhase.STARTED))
    source.append(entry("z", 1, TombstonePhase.COMPLETED))
    source.append(entry("y", 2, TombstonePhase.STARTED))
    source.append(entry("y", 2, TombstonePhase.INCOMPLETE))
    path.write_bytes(replacement.read_bytes())
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_MISMATCH"):
        DeletionJournalSnapshot.read(path, expected=checkpoint)


@pytest.mark.parametrize("field", ["sequence", "deletion_epoch", "head"])
def test_each_checkpoint_member_is_checked(tmp_path: Path, field: str) -> None:
    path = tmp_path / "journal.jsonl"
    journal(path)
    checkpoint = DeletionJournalSnapshot.capture(path).checkpoint
    value = "urn:sha256:" + "b" * 64 if field == "head" else 99
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_MISMATCH"):
        DeletionJournalSnapshot.read(path, expected=replace(checkpoint, **{field: value}))


def rechain(path: Path, changed: list[dict[str, object]]) -> None:
    previous = "urn:sha256:" + "0" * 64
    output = []
    for sequence, record in enumerate(changed, start=1):
        body = {"seq": sequence, "prev": previous, "entry": record}
        previous = canonical_digest(body)
        output.append(canonical_bytes(dict(body, entry_digest=previous)) + b"\n")
    path.write_bytes(b"".join(output))


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "tenant-b"),
    ("partition_digests", ["urn:sha256:" + "b" * 64]),
    ("version_refs", ["urn:ocor:memory:other:v1"]),
    ("deletion_epoch", True),
    ("participants", ["content", "content"]),
    ("residue_counts", [["unknown", 1]]),
])
def test_invalid_saga_history_is_rejected_even_if_hash_chain_is_valid(
    tmp_path: Path, field: str, value: object,
) -> None:
    path = tmp_path / "journal.jsonl"
    journal(path)
    records = [parse_i_json(line)["entry"] for line in path.read_bytes().splitlines()]
    records[1][field] = value
    rechain(path, records)
    with pytest.raises(DeletionRecoveryError):
        DeletionJournalSnapshot.capture(path)


@dataclass
class Authority:
    """Trusted-checkpoint port fixture; authentication is the provider's obligation."""

    path: Path
    unavailable: bool = False

    def current(self):  # type: ignore[no-untyped-def]
        if self.unavailable:
            raise ConnectionError("authority unavailable")
        return DeletionJournalSnapshot.capture(self.path).checkpoint


class Participant:
    name = "content"

    def __init__(self) -> None:
        self.present = {"x", "y"}
        self.unavailable = False
        self.omit_y = False
        self.calls: list[str] = []

    def purge(self, tombstone: TombstoneEntry) -> None:
        self.calls.append(tombstone.memory_item_id)
        if not (self.omit_y and tombstone.memory_item_id == "y"):
            self.present.discard(tombstone.memory_item_id)

    def residue(self, tombstone: TombstoneEntry) -> tuple[str, ...]:
        if self.unavailable:
            raise ConnectionError("inventory unavailable")
        return (tombstone.memory_item_id,) if tombstone.memory_item_id in self.present else ()


def gate_world(tmp_path: Path):  # type: ignore[no-untyped-def]
    authoritative = tmp_path / "authority.jsonl"
    journal(authoritative)
    restored = tmp_path / "restored.jsonl"
    restored.write_bytes(authoritative.read_bytes())
    participant = Participant()
    authority = Authority(authoritative)
    gate = DeletionRestoreGate(journal=restored, authority=authority, participants=(participant,))
    return gate, authority, participant, restored


def test_restored_service_starts_closed_and_only_opens_after_all_obligations(tmp_path: Path) -> None:
    gate, _, participant, _ = gate_world(tmp_path)
    invoked: list[str] = []
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        gate.serve(lambda: invoked.append("query"))
    assert invoked == []
    receipt = gate.reconcile()
    assert participant.present == set() and participant.calls == ["x", "y"]
    assert receipt.checkpoint.sequence == 4 and receipt.obligations == 2
    assert gate.serve(lambda: "result") == "result"


@pytest.mark.parametrize("fault", ["residue", "inventory-unavailable", "authority-unavailable", "journal-prefix"])
def test_failed_recovery_does_not_call_the_restored_service(tmp_path: Path, fault: str) -> None:
    gate, authority, participant, restored = gate_world(tmp_path)
    if fault == "residue":
        participant.omit_y = True
    elif fault == "inventory-unavailable":
        participant.unavailable = True
    elif fault == "authority-unavailable":
        authority.unavailable = True
    else:
        restored.write_bytes(b"".join(restored.read_bytes().splitlines(keepends=True)[:2]))
    with pytest.raises(DeletionRecoveryError):
        gate.reconcile()
    with pytest.raises(DeletionRecoveryError):
        gate.serve(lambda: pytest.fail("closed recovery executed a query"))


def test_retry_reconciles_residue_but_never_reopens_on_a_prior_receipt(tmp_path: Path) -> None:
    gate, _, participant, _ = gate_world(tmp_path)
    participant.omit_y = True
    with pytest.raises(DeletionRecoveryError, match="DELETION_INCOMPLETE"):
        gate.reconcile()
    participant.omit_y = False
    receipt = gate.reconcile()
    assert gate.serve(lambda: receipt.obligations) == 2
    participant.present.add("x")
    with pytest.raises(DeletionRecoveryError, match="DELETION_INCOMPLETE"):
        gate.serve(lambda: pytest.fail("resurrected representation was served"))


def test_a_new_authoritative_epoch_invalidates_an_already_open_gate(tmp_path: Path) -> None:
    gate, authority, _, _ = gate_world(tmp_path)
    gate.reconcile()
    JournalTombstoneStore(authority.path).append(entry("z", 3, TombstonePhase.STARTED))
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_MISMATCH"):
        gate.serve(lambda: pytest.fail("stale deletion epoch was served"))


def test_missing_duplicate_or_unnamed_participants_are_configuration_errors(tmp_path: Path) -> None:
    _, authority, participant, restored = gate_world(tmp_path)
    for participants in [(), (participant, participant)]:
        with pytest.raises(ValueError):
            DeletionRestoreGate(journal=restored, authority=authority, participants=participants)

