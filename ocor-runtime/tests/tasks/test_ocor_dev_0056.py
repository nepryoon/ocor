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
    MemoryDeletionMetadataReplay,
    RestoredMemoryParticipant,
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
    value = "urn:sha256:" + "b" * 64 if field == "head" else (1 if field == "deletion_epoch" else 99)
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

    def __init__(self, name: str = "content") -> None:
        self.name = name
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
    gate = DeletionRestoreGate(
        journal=restored, authority=authority,
        participants=(participant, Participant("native-projections")),
    )
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


def test_omitting_a_recorded_store_cannot_qualify_recovery(tmp_path: Path) -> None:
    _, authority, participant, restored = gate_world(tmp_path)
    gate = DeletionRestoreGate(journal=restored, authority=authority, participants=(participant,))
    with pytest.raises(DeletionRecoveryError, match="DELETION_PARTICIPANT_MISSING"):
        gate.reconcile()
    assert participant.calls == []


def test_new_epoch_during_materialisation_discards_the_response(tmp_path: Path) -> None:
    gate, authority, _, _ = gate_world(tmp_path)
    gate.reconcile()

    def materialise() -> str:
        JournalTombstoneStore(authority.path).append(entry("z", 3, TombstonePhase.STARTED))
        return "must not escape"

    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_MISMATCH"):
        gate.serve(materialise)
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        gate.serve(lambda: "must remain closed")


def test_residue_created_during_materialisation_discards_the_response(tmp_path: Path) -> None:
    gate, _, participant, _ = gate_world(tmp_path)
    gate.reconcile()

    def materialise() -> str:
        participant.present.add("x")
        return "must not escape"

    with pytest.raises(DeletionRecoveryError, match="DELETION_INCOMPLETE"):
        gate.serve(materialise)


def test_a_missing_journal_and_failed_callback_leave_recovery_closed(tmp_path: Path) -> None:
    gate, _, _, restored = gate_world(tmp_path)
    gate.reconcile()

    def failure() -> None:
        raise TimeoutError("query unavailable")

    with pytest.raises(TimeoutError):
        gate.serve(failure)
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        gate.serve(lambda: "closed")
    restored.unlink()
    with pytest.raises(DeletionRecoveryError, match="JOURNAL_UNAVAILABLE"):
        gate.reconcile()


@pytest.mark.parametrize("field,value", [
    ("sequence", True), ("sequence", -1), ("deletion_epoch", True),
    ("deletion_epoch", -1), ("head", "not-a-digest"),
])
def test_malformed_checkpoints_are_not_authority(tmp_path: Path, field: str, value: object) -> None:
    path = tmp_path / "journal.jsonl"
    journal(path)
    checkpoint = DeletionJournalSnapshot.capture(path).checkpoint
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_INVALID"):
        replace(checkpoint, **{field: value})


def test_saga_outcomes_may_extend_version_refs_and_retry_under_the_same_epoch(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    source = JournalTombstoneStore(path)
    source.append(entry("x", 1, TombstonePhase.STARTED))
    source.append(replace(entry("x", 1, TombstonePhase.INCOMPLETE), residue_counts=(("content", 1),)))
    source.append(replace(entry("x", 1, TombstonePhase.STARTED), operation_id="retry-x"))
    source.append(replace(
        entry("x", 1, TombstonePhase.COMPLETED),
        version_refs=("urn:ocor:memory:x:v1", "urn:ocor:memory:x:v2"), operation_id="retry-x",
    ))
    snapshot = DeletionJournalSnapshot.capture(path)
    assert snapshot.checkpoint.sequence == 4 and snapshot.checkpoint.deletion_epoch == 1
    assert snapshot.obligations == (snapshot.entries[-1],)


@pytest.mark.parametrize("attack", [
    "unknown-chain-field", "bool-sequence", "noninteger-sequence", "digest-type", "bad-prev", "blank-line",
    "missing-start", "after-completion", "timestamp", "empty-partitions", "malformed-partition",
    "empty-versions", "zero-version", "empty-participants", "duplicate-partitions", "completed-residue",
])
def test_malformed_hash_chains_and_entries_never_open_restore(tmp_path: Path, attack: str) -> None:
    path = tmp_path / "journal.jsonl"
    journal(path)
    lines = path.read_bytes().splitlines()
    first = parse_i_json(lines[0])
    if attack == "unknown-chain-field":
        first["undeclared"] = "value"
    elif attack == "bool-sequence":
        first["seq"] = True
    elif attack == "noninteger-sequence":
        first["seq"] = 1.0
    elif attack == "digest-type":
        first["entry_digest"] = None
    elif attack == "bad-prev":
        first["prev"] = "urn:sha256:" + "f" * 64
    elif attack == "blank-line":
        path.write_bytes(b"\n" + path.read_bytes())
    else:
        records = [parse_i_json(line)["entry"] for line in lines]
        if attack == "missing-start":
            records = records[1:]
        elif attack == "after-completion":
            records.insert(2, records[0])
        else:
            changes = {
                "timestamp": ("at", "not-a-time"),
                "empty-partitions": ("partition_digests", []),
                "malformed-partition": ("partition_digests", ["not-a-digest"]),
                "duplicate-partitions": ("partition_digests", ["urn:sha256:" + "a" * 64] * 2),
                "empty-versions": ("version_refs", []),
                "zero-version": ("version_refs", ["urn:ocor:memory:x:v0"]),
                "empty-participants": ("participants", []),
                "completed-residue": ("residue_counts", [["content", 1]]),
            }
            field, value = changes[attack]
            records[1 if attack == "completed-residue" else 0][field] = value
        rechain(path, records)
    if attack in {"unknown-chain-field", "bool-sequence", "noninteger-sequence", "digest-type", "bad-prev"}:
        first_line = canonical_bytes(first)
        if attack == "noninteger-sequence":
            # canonical_bytes normalises 1.0 to 1: inject the wire form itself.
            first_line = first_line.replace(b'"seq":1', b'"seq":1.0')
        path.write_bytes(first_line + b"\n" + b"\n".join(lines[1:]) + b"\n")
    with pytest.raises(DeletionRecoveryError, match="JOURNAL_CORRUPTED"):
        DeletionJournalSnapshot.capture(path)


def test_a_purge_failure_is_not_overruled_by_an_empty_inventory(tmp_path: Path) -> None:
    _, authority, participant, restored = gate_world(tmp_path)

    class FailedPurge(Participant):
        def purge(self, tombstone: TombstoneEntry) -> None:
            super().purge(tombstone)
            raise ConnectionError("lost ack")

    gate = DeletionRestoreGate(
        journal=restored, authority=authority,
        participants=(participant, FailedPurge("native-projections")),
    )
    with pytest.raises(DeletionRecoveryError, match="DELETION_INCOMPLETE"):
        gate.reconcile()
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        gate.serve(lambda: "closed")


def test_authority_changed_during_purge_is_rechecked(tmp_path: Path) -> None:
    _, authority, participant, restored = gate_world(tmp_path)

    class ConcurrentDeletion(Participant):
        def purge(self, tombstone: TombstoneEntry) -> None:
            super().purge(tombstone)
            if tombstone.memory_item_id == "x":
                JournalTombstoneStore(authority.path).append(entry("z", 3, TombstonePhase.STARTED))

    gate = DeletionRestoreGate(
        journal=restored, authority=authority,
        participants=(participant, ConcurrentDeletion("native-projections")),
    )
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_MISMATCH"):
        gate.reconcile()


def test_authority_and_inventory_require_exact_port_types(tmp_path: Path) -> None:
    _, authority, participant, restored = gate_world(tmp_path)

    class InvalidInventory(Participant):
        def residue(self, tombstone: TombstoneEntry):  # type: ignore[no-untyped-def]
            return []  # not a verified empty tuple

    gate = DeletionRestoreGate(
        journal=restored, authority=authority,
        participants=(participant, InvalidInventory("native-projections")),
    )
    with pytest.raises(DeletionRecoveryError, match="DELETION_INCOMPLETE"):
        gate.reconcile()

    class InvalidAuthority:
        def current(self):  # type: ignore[no-untyped-def]
            return {"deletion_epoch": 2}

    gate = DeletionRestoreGate(journal=restored, authority=InvalidAuthority(), participants=(participant,))
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_INVALID"):
        gate.reconcile()


def test_checkpoint_digest_is_bound_to_all_three_members(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    journal(path)
    checkpoint = DeletionJournalSnapshot.capture(path).checkpoint
    assert checkpoint.digest == canonical_digest(checkpoint.to_mapping())
    assert replace(checkpoint, sequence=5).digest != checkpoint.digest
    assert replace(checkpoint, deletion_epoch=1).digest != checkpoint.digest
    assert replace(checkpoint, head="urn:sha256:" + "b" * 64).digest != checkpoint.digest


def replay_world(tmp_path: Path):  # type: ignore[no-untyped-def]
    import test_ocor_dev_0055 as t55

    path = tmp_path / "journal.jsonl"
    source = t55.unit_world(tombstones=JournalTombstoneStore(path))
    restored = t55.unit_world()
    source.admit("x", t55.TEXT)
    restored.admit("x", t55.TEXT)
    source.delete("x", op="forget-x")
    tombstone = DeletionJournalSnapshot.capture(path).obligations[0]
    replay = MemoryDeletionMetadataReplay(
        authoritative_metadata=source.metadata, authoritative_ledger=source.ledger,
        restored_metadata=restored.metadata, restored_ledger=restored.ledger,
    )
    return replay, source, restored, tombstone


def test_metadata_replay_preserves_original_versions_epochs_events_and_audit(tmp_path: Path) -> None:
    replay, source, restored, tombstone = replay_world(tmp_path)
    assert restored.metadata.head("x") == restored.ledger.latest_version("x") == 1
    replay.purge(tombstone)
    assert restored.metadata.head("x") == restored.ledger.latest_version("x") == 3
    assert restored.status("x") == "DELETED"
    assert replay.residue(tombstone) == ()
    for version in range(1, 4):
        assert restored.ledger.get("x", version).to_mapping() == source.ledger.get("x", version).to_mapping()
        assert restored.metadata.get("x", version) == source.metadata.get("x", version)
    replay.purge(tombstone)
    assert restored.ledger.latest_version("x") == 3  # idempotent: no replacement events


@pytest.mark.parametrize("attack", ["tenant", "partition", "epoch", "versions", "phase"])
def test_replay_refuses_unbound_metadata_before_writing_anything(tmp_path: Path, attack: str) -> None:
    replay, _, restored, tombstone = replay_world(tmp_path)
    changes = {
        "tenant": {"tenant_id": "tenant-b"},
        "partition": {"partition_digests": ("urn:sha256:" + "b" * 64,)},
        "epoch": {"deletion_epoch": 2},
        "versions": {"version_refs": tombstone.version_refs[:-1]},
        "phase": {"phase": TombstonePhase.INCOMPLETE},
    }
    with pytest.raises(DeletionRecoveryError):
        replay.purge(replace(tombstone, **changes[attack]))
    assert restored.metadata.head("x") == restored.ledger.latest_version("x") == 1
    assert replay.residue(tombstone)


def test_metadata_replay_reports_a_lost_commit_and_resumes_it(tmp_path: Path) -> None:
    replay, _, restored, tombstone = replay_world(tmp_path)
    commit = restored.metadata.commit

    def lost_commit(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ConnectionError("postgres unavailable")

    restored.metadata.commit = lost_commit
    with pytest.raises(ConnectionError):
        replay.purge(tombstone)
    assert replay.residue(tombstone)
    restored.metadata.commit = commit
    replay.purge(tombstone)
    assert restored.status("x") == "DELETED" and replay.residue(tombstone) == ()


def test_the_composed_recovery_gate_replays_then_purges_native_stores(tmp_path: Path) -> None:
    import test_ocor_dev_0052 as t52
    import test_ocor_dev_0055 as t55

    replay, source, restored, tombstone = replay_world(tmp_path)
    restored.admit("keep", t55.TEXT + " south")
    source_path = tmp_path / "journal.jsonl"
    restored_path = tmp_path / "restored.jsonl"
    restored_path.write_bytes(source_path.read_bytes())
    participants = [replay, *[
        RestoredMemoryParticipant(metadata=restored.metadata, participant=p, binding=t52.binding(t55.CALLER))
        for p in restored.participants()
    ]]
    gate = DeletionRestoreGate(journal=restored_path, authority=Authority(source_path), participants=participants)
    before = restored.every_mode()
    assert all("urn:ocor:memory:x:v1" in refs for refs in before.values())
    gate.reconcile()
    found = gate.serve(restored.every_mode)
    assert all(refs == ["urn:ocor:memory:keep:v1"] for refs in found.values())
    assert all(p.residue(tombstone) == () for p in participants)
    assert source.status("x") == restored.status("x") == "DELETED"


def test_restore_participants_validate_tenant_and_scope_before_purge(tmp_path: Path) -> None:
    import test_ocor_dev_0052 as t52
    import test_ocor_dev_0055 as t55

    replay, _, restored, tombstone = replay_world(tmp_path)
    replay.purge(tombstone)
    participant = RestoredMemoryParticipant(
        metadata=restored.metadata, participant=restored.participants()[0], binding=t52.binding(t55.CALLER),
    )
    for bad in [replace(tombstone, tenant_id="tenant-b"), replace(tombstone, partition_digests=("urn:sha256:" + "b" * 64,))]:
        with pytest.raises(DeletionRecoveryError, match="RESTORE_BINDING_MISMATCH"):
            participant.purge(bad)
    assert t55.native_entries(restored, restored.ledger.get("x", 1)) == {"lexical": 1, "vector": 1}
