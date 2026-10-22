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


# --------------------------------------------------------------------------
# Authenticated checkpoint bound to the recovery point (no caller authority)
# --------------------------------------------------------------------------

RECOVERY_POINT = "urn:ocor:recovery-point:" + "c" * 64
OTHER_RECOVERY_POINT = "urn:ocor:recovery-point:" + "d" * 64


def authenticated_api():  # type: ignore[no-untyped-def]
    """Imported per test so a missing port fails each case, not collection."""

    from ocor_runtime.memory import deletion

    return deletion.AuthenticatedDeletionCheckpointAuthority, deletion.RecoveryPointCheckpointClaim


class HmacVerifier:
    """Unit attestation port; the live cases use OpenBao transit signatures."""

    def __init__(self, key: bytes = b"k" * 32, *, answer: object = None, unavailable: bool = False) -> None:
        self.key, self.answer, self.unavailable = key, answer, unavailable

    def sign(self, payload: bytes) -> str:
        import hashlib
        import hmac

        return hmac.new(self.key, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, attestation: str) -> bool:
        import hmac

        if self.unavailable:
            raise TimeoutError("attestation service unavailable")
        if self.answer is not None:
            return self.answer  # type: ignore[return-value]
        return hmac.compare_digest(self.sign(payload), attestation)


class IssuedCheckpoints:
    """Deletion-authority side: attests the current journal for one recovery point."""

    def __init__(self, path: Path, signer: HmacVerifier, recovery_point: str = RECOVERY_POINT) -> None:
        self.path, self.signer, self.recovery_point = path, signer, recovery_point
        self.tamper: str | None = None
        self.unavailable = False

    def attested_checkpoint(self) -> tuple[bytes, str]:
        _, claim_type = authenticated_api()
        if self.unavailable:
            raise ConnectionError("deletion authority unreachable")
        claim = claim_type(self.recovery_point, DeletionJournalSnapshot.capture(self.path).checkpoint)
        payload = claim.payload()
        attestation = self.signer.sign(payload)
        if self.tamper == "payload":
            body = parse_i_json(payload)
            body["checkpoint"]["deletion_epoch"] = 1
            return canonical_bytes(body), attestation
        if self.tamper == "attestation":
            return payload, "0" * len(attestation)
        if self.tamper == "empty":
            return payload, ""
        if self.tamper == "type":
            return payload.decode(), attestation  # type: ignore[return-value]
        if self.tamper in {"extra", "noncanonical", "rp-pattern"}:
            body = parse_i_json(payload)
            if self.tamper == "extra":
                body["issued_by"] = "caller"
                forged = canonical_bytes(body)
            elif self.tamper == "noncanonical":
                forged = payload.replace(b"{", b"{ ", 1)
            else:
                body["recovery_point_id"] = "recovery-point-1"
                forged = canonical_bytes(body)
            return forged, self.signer.sign(forged)
        return payload, attestation


def authenticated_gate(tmp_path: Path, **verifier: object):  # type: ignore[no-untyped-def]
    authority_type, _ = authenticated_api()
    authoritative = tmp_path / "authority.jsonl"
    source = journal(authoritative)
    restored = tmp_path / "restored.jsonl"
    restored.write_bytes(authoritative.read_bytes())
    issued = IssuedCheckpoints(authoritative, HmacVerifier())
    check = HmacVerifier(**verifier)  # type: ignore[arg-type]
    authority = authority_type(recovery_point_id=RECOVERY_POINT, source=issued, verifier=check)
    participants = (Participant(), Participant("native-projections"))
    gate = DeletionRestoreGate(journal=restored, authority=authority, participants=participants)
    return gate, issued, authority, source


def test_an_attested_checkpoint_for_the_recovery_point_opens_restore(tmp_path: Path) -> None:
    gate, _, authority, _ = authenticated_gate(tmp_path)
    expected = DeletionJournalSnapshot.capture(tmp_path / "authority.jsonl").checkpoint
    assert authority.current() == expected
    receipt = gate.reconcile()
    assert receipt.checkpoint == expected and receipt.obligations == 2
    assert gate.serve(lambda: "served") == "served"


@pytest.mark.parametrize("tamper", ["payload", "attestation", "empty", "type"])
def test_an_unauthenticated_checkpoint_never_opens_restore(tmp_path: Path, tamper: str) -> None:
    gate, issued, _, _ = authenticated_gate(tmp_path)
    issued.tamper = tamper
    invoked: list[str] = []
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_UNAUTHENTICATED"):
        gate.reconcile()
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        gate.serve(lambda: invoked.append("served"))
    assert invoked == []


@pytest.mark.parametrize("answer", [False, 1, "true", [True]])
def test_only_an_exact_true_verification_authenticates(tmp_path: Path, answer: object) -> None:
    gate, _, _, _ = authenticated_gate(tmp_path, answer=answer)
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_UNAUTHENTICATED"):
        gate.reconcile()


@pytest.mark.parametrize("tamper", ["extra", "noncanonical", "rp-pattern"])
def test_an_attested_but_malformed_claim_is_not_a_checkpoint(tmp_path: Path, tamper: str) -> None:
    gate, issued, _, _ = authenticated_gate(tmp_path)
    issued.tamper = tamper
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_INVALID"):
        gate.reconcile()


def test_a_claim_for_another_recovery_point_is_refused(tmp_path: Path) -> None:
    gate, issued, _, _ = authenticated_gate(tmp_path)
    issued.recovery_point = OTHER_RECOVERY_POINT
    with pytest.raises(DeletionRecoveryError, match="RECOVERY_POINT_MISMATCH"):
        gate.reconcile()


@pytest.mark.parametrize("outage", ["source", "verifier"])
def test_authority_or_verifier_outage_keeps_restore_closed(tmp_path: Path, outage: str) -> None:
    gate, issued, _, _ = authenticated_gate(tmp_path, unavailable=outage == "verifier")
    issued.unavailable = outage == "source"
    with pytest.raises(DeletionRecoveryError, match="DELETION_AUTHORITY_UNAVAILABLE"):
        gate.reconcile()


def test_an_attested_later_deletion_closes_an_open_gate(tmp_path: Path) -> None:
    gate, _, _, source = authenticated_gate(tmp_path)
    gate.reconcile()
    source.append(entry("z", 3, TombstonePhase.STARTED))
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_MISMATCH"):
        gate.serve(lambda: "stale")
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        gate.serve(lambda: "stale")


@pytest.mark.parametrize("value", ["", "recovery-point", "urn:ocor:recovery-point:" + "C" * 64, 7])
def test_the_recovery_point_identity_is_a_closed_urn(tmp_path: Path, value: object) -> None:
    authority_type, claim_type = authenticated_api()
    journal(tmp_path / "j.jsonl")
    checkpoint = DeletionJournalSnapshot.capture(tmp_path / "j.jsonl").checkpoint
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_INVALID"):
        claim_type(value, checkpoint)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        authority_type(recovery_point_id=value, source=object(), verifier=object())  # type: ignore[arg-type]


def test_claim_payload_roundtrips_and_binds_recovery_point_and_checkpoint(tmp_path: Path) -> None:
    _, claim_type = authenticated_api()
    journal(tmp_path / "j.jsonl")
    checkpoint = DeletionJournalSnapshot.capture(tmp_path / "j.jsonl").checkpoint
    claim = claim_type(RECOVERY_POINT, checkpoint)
    assert parse_i_json(claim.payload()) == {"recovery_point_id": RECOVERY_POINT, "checkpoint": checkpoint.to_mapping()}
    assert claim_type.from_payload(claim.payload()) == claim
    assert claim_type(OTHER_RECOVERY_POINT, checkpoint).payload() != claim.payload()


# --------------------------------------------------------------------------
# Qualifying restore drills on the real backends of OCOR-DEV-0051/0053/0055
# --------------------------------------------------------------------------
#
# Real, pinned backends: PostgreSQL 16 from ``OCOR_LIVE_POSTGRES_DSN``
# (metadata, encrypted content, full-text index, representation descriptors),
# Qdrant 1.15.1 (native and parallel vector indexes) and OpenBao 2.6.2
# (content transit key and the ed25519 key attesting deletion checkpoints).
# The recovery point is a real backup: one REPEATABLE READ snapshot copy of
# every table of the source schema plus a Qdrant snapshot of every source
# collection, recovered through the Qdrant snapshot API into a new namespace.
# The memory ledger of the 0052 world fixture is in-process; its records are
# copied unchanged with the backup.  A missing backend fails, it never skips.


def live_modules():  # type: ignore[no-untyped-def]
    import test_ocor_dev_0051 as base
    import test_ocor_dev_0052 as t52
    import test_ocor_dev_0053 as t53
    import test_ocor_dev_0055 as t55
    import test_ocor_dev_rem_0023 as denial

    return base, t52, t53, t55, denial


def _openbao_harness():  # type: ignore[no-untyped-def]
    base, *_ = live_modules()

    class OpenBaoHarness(base.OpenBaoHarness):  # type: ignore[misc,name-defined]
        PREFIX = "ocor-test-0056-openbao-"

    return OpenBaoHarness


class OpenBaoCheckpointAttestation:
    """Deletion-authority attestation: OpenBao transit ed25519 sign/verify."""

    KEY = "deletion-checkpoint"

    def __init__(self, bao) -> None:  # type: ignore[no-untyped-def]
        self._bao = bao
        bao.call("POST", f"/v1/ocor-memory-transit/keys/{self.KEY}", {"type": "ed25519"})

    def sign(self, payload: bytes) -> str:
        import base64

        data = self._bao.call(
            "POST", f"/v1/ocor-memory-transit/sign/{self.KEY}", {"input": base64.b64encode(payload).decode()},
        )
        return str(data["data"]["signature"])

    def verify(self, payload: bytes, attestation: str) -> bool:
        import base64

        base, *_ = live_modules()
        status, data = base._http(
            "POST", f"{self._bao.endpoint}/v1/ocor-memory-transit/verify/{self.KEY}",
            {"input": base64.b64encode(payload).decode(), "signature": attestation},
            headers={"X-Vault-Token": self._bao.token},
        )
        if status == 400:
            return False  # malformed signature: not authenticated
        if status != 200:
            raise RuntimeError(f"OpenBao verify -> {status}")
        return data["data"]["valid"] is True


class AttestedJournal:
    """The deletion authority: attests its current journal for one recovery point."""

    def __init__(self, path: Path, signer: OpenBaoCheckpointAttestation, recovery_point: str) -> None:
        self.path, self.signer, self.recovery_point = path, signer, recovery_point
        self.forge: str | None = None

    def attested_checkpoint(self) -> tuple[bytes, str]:
        _, claim_type = authenticated_api()
        checkpoint = DeletionJournalSnapshot.capture(self.path).checkpoint
        payload = claim_type(self.recovery_point, checkpoint).payload()
        if self.forge == "other-recovery-point":
            payload = claim_type(OTHER_RECOVERY_POINT, checkpoint).payload()
        signature = self.signer.sign(payload)
        if self.forge == "payload":
            body = parse_i_json(payload)
            body["checkpoint"]["sequence"] += 1
            payload = canonical_bytes(body)
        if self.forge == "malformed":
            signature = "vault:v1:" + "A" * 86
        return payload, signature


@pytest.fixture(scope="module")
def live_backends():  # type: ignore[no-untyped-def]
    import os

    base, _, _, t55, _ = live_modules()
    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory qualifying evidence (real PostgreSQL)")
    qdrant = base.QdrantHarness.provision()
    bao = None
    state = None
    try:
        bao = _openbao_harness().provision()
        state = t55.Backends(dsn=dsn, qdrant=qdrant, bao=bao)
        yield state
    finally:
        try:
            if state is not None:
                state.release()
        finally:
            try:
                if bao is not None:
                    bao.destroy()
            finally:
                qdrant.destroy()


@pytest.fixture
def backends(live_backends):  # type: ignore[no-untyped-def]
    try:
        yield live_backends
    finally:
        live_backends.release()


# FK order of the 0051 schema first; every other table follows by name.
TABLE_ORDER = ("partitions", "versions", "pointers")


def backup_and_restore(backends, source, items: dict[str, object]):  # type: ignore[no-untyped-def]
    """Back up ``source`` and restore it into a new namespace; returns (world, recovery point)."""

    import hashlib
    import uuid

    import psycopg

    base, t52, t53, _, denial = live_modules()
    a = source.metadata.schema
    b = f"ocor_t0056_{uuid.uuid4().hex[:12]}"
    backends.schemas.append(b)
    base.PostgresStores(backends.dsn, b)
    t53.PostgresRepresentationStore(backends.dsn, b)
    denial.SchemaPostgresAudit(backends.dsn, b)
    manifest: dict[str, object] = {}
    with psycopg.connect(backends.dsn) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        names = sorted(
            row[0] for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE'", (a,),
            ).fetchall()
        )
        ordered = [n for n in TABLE_ORDER if n in names] + [n for n in names if n not in TABLE_ORDER]
        existing = {
            row[0] for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (b,),
            ).fetchall()
        }
        for name in ordered:
            if name not in existing:
                conn.execute(f'CREATE TABLE "{b}"."{name}" (LIKE "{a}"."{name}" INCLUDING ALL)')
            conn.execute(f'INSERT INTO "{b}"."{name}" SELECT * FROM "{a}"."{name}"')
            row = conn.execute(
                f'SELECT count(*), coalesce(md5(string_agg(t::text, \'|\' ORDER BY t::text)), \'\') FROM "{a}"."{name}" t'
            ).fetchone()
            assert row is not None
            manifest[f"postgres:{name}"] = [row[0], row[1]]
    index = t52.CompactQdrantVectorIndex(backends.qdrant.endpoint, a)
    collections = index.collections()
    assert collections, "the source must hold native vector collections"
    for name in collections:
        status, data = index._call("POST", f"/collections/{name}/snapshots?wait=true")
        assert status == 200, (name, status)
        snapshot = data["result"]
        target = f"ocor_{b}_" + name.removeprefix(f"ocor_{a}_")
        status, _ = index._call(
            "PUT", f"/collections/{target}/snapshots/recover?wait=true",
            {"location": f"file:///qdrant/snapshots/{name}/{snapshot['name']}"},
        )
        assert status == 200, (target, status)
        manifest[f"qdrant:{name.removeprefix(f'ocor_{a}_')}"] = snapshot.get("checksum") or snapshot["name"]
    restored = backends.world(schema=b)
    for item_id in items:
        for version in range(1, source.ledger.latest_version(item_id) + 1):
            restored.ledger.append(source.ledger.get(item_id, version))
    manifest["ledger"] = sorted(
        source.ledger.get(i, v).item_digest for i in items for v in range(1, source.ledger.latest_version(i) + 1)
    )
    # The in-process representation receipt store of the fixture is part of the recovery point.
    restored.rep_audit.events.extend(dict(event) for event in source.rep_audit.events)
    manifest["representation_receipts"] = sorted(canonical_digest(dict(e)) for e in source.rep_audit.events)
    recovery_point = "urn:ocor:recovery-point:" + hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    return restored, recovery_point


@dataclass
class Drill:
    source: object
    restored: object
    recovery_point: str
    authority_journal: Path
    restored_journal: Path
    attestation: OpenBaoCheckpointAttestation
    issuer: AttestedJournal
    items: dict[str, object]

    def gate(self, *extra: object) -> DeletionRestoreGate:
        _, t52, _, t55, _ = live_modules()
        authority_type, _ = authenticated_api()
        authority = authority_type(
            recovery_point_id=self.recovery_point, source=self.issuer, verifier=self.attestation,
        )
        replay = MemoryDeletionMetadataReplay(
            authoritative_metadata=self.source.metadata, authoritative_ledger=self.source.ledger,  # type: ignore[attr-defined]
            restored_metadata=self.restored.metadata, restored_ledger=self.restored.ledger,  # type: ignore[attr-defined]
        )
        adapters = [
            RestoredMemoryParticipant(metadata=self.restored.metadata, participant=p, binding=t52.binding(t55.CALLER))  # type: ignore[attr-defined]
            for p in [*self.restored.participants(), *extra]  # type: ignore[attr-defined]
        ]
        return DeletionRestoreGate(journal=self.restored_journal, authority=authority, participants=[replay, *adapters])

    def deliver_journal(self) -> None:
        """The deletion authority ships its current journal to the restore site."""

        self.restored_journal.write_bytes(self.authority_journal.read_bytes())

    def refs(self) -> dict[str, list[str]]:
        return self.restored.every_mode(v2=True)  # type: ignore[attr-defined,no-any-return]


def drill(backends, tmp_path: Path, *, replica=None, twin: bool = False) -> Drill:  # type: ignore[no-untyped-def]
    _, _, _, t55, _ = live_modules()
    path = tmp_path / "authority.jsonl"
    source = backends.world(tombstones=JournalTombstoneStore(path), replica=replica)
    items = t55.populate(source)
    if twin:
        items["twin"] = source.admit("twin", t55.TEXT + " north")  # shares x's content object
    source.rebuild(items["keep"])  # parallel v2 representation of the partition
    restored, recovery_point = backup_and_restore(backends, source, items)
    attestation = OpenBaoCheckpointAttestation(backends.bao)
    issuer = AttestedJournal(path, attestation, recovery_point)
    return Drill(source, restored, recovery_point, path, tmp_path / "restored.jsonl", attestation, issuer, items)


def mentions(refs: dict[str, list[str]], item: str) -> bool:
    return any(ref.startswith(f"urn:ocor:memory:{item}:") for found in refs.values() for ref in found)


def test_live_qualifying_backends_are_real_and_pinned(backends) -> None:  # type: ignore[no-untyped-def]
    import psycopg

    base, t52, t53, _, _ = live_modules()
    assert base.QDRANT_IMAGE.endswith(base.LOCKED_IMAGES["qdrant"].split("@", 1)[1])
    assert base._docker("inspect", backends.qdrant.container, "--format", "{{.Config.Image}}") == base.QDRANT_IMAGE
    assert base._docker("inspect", backends.bao.container, "--format", "{{.Config.Image}}") == base.LOCKED_IMAGES["openbao"]
    with psycopg.connect(backends.dsn) as conn:
        row = conn.execute("SHOW server_version").fetchone()
    assert row is not None and str(row[0]).startswith("16.")
    world = backends.world()
    assert isinstance(world.metadata, base.PostgresStores) and isinstance(world.representations, t53.PostgresRepresentationStore)
    assert isinstance(world.vector.inner, base.QdrantVectorIndex) and isinstance(world.parallel.inner, base.QdrantVectorIndex)
    signer = OpenBaoCheckpointAttestation(backends.bao)
    assert signer.verify(b"payload", signer.sign(b"payload")) is True
    assert signer.verify(b"other", signer.sign(b"payload")) is False


def test_live_restore_never_resurrects_a_deletion_made_after_the_backup(backends, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _, _, _, t55, _ = live_modules()
    d = drill(backends, tmp_path, twin=True)
    x, twin = d.items["x"], d.items["twin"]
    assert d.source.delete("x", op="forget-x").lifecycle_status == "DELETED"  # type: ignore[attr-defined]
    d.deliver_journal()
    # The restored backup really holds x in every store: the resurrection risk is real.
    before = d.refs()
    assert all("urn:ocor:memory:x:v1" in refs for refs in before.values()), before
    assert t55.native_entries(d.restored, x) == {"lexical": 1, "vector": 1}
    assert t55.parallel_descriptors(d.restored, x) == ["urn:ocor:memory:x:v1"]
    gate = d.gate()
    served: list[str] = []
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        gate.serve(lambda: served.append("before"))
    receipt = gate.reconcile()
    assert receipt.obligations == 1 and receipt.checkpoint == DeletionJournalSnapshot.capture(d.authority_journal).checkpoint
    found = gate.serve(d.refs)
    assert not mentions(found, "x") and served == []
    assert all("urn:ocor:memory:keep:v1" in refs and "urn:ocor:memory:twin:v1" in refs for refs in found.values()), found
    # Every representation of x is gone from the restored stores; the shared object is retained for twin.
    assert d.restored.status("x") == d.source.status("x") == "DELETED"  # type: ignore[attr-defined]
    assert t55.native_entries(d.restored, x) == {"lexical": 0, "vector": 0}
    assert t55.parallel_descriptors(d.restored, x) == []
    assert t55.content_present(d.restored, twin)
    for version in range(1, d.source.ledger.latest_version("x") + 1):  # type: ignore[attr-defined]
        assert d.restored.ledger.get("x", version).to_mapping() == d.source.ledger.get("x", version).to_mapping()  # type: ignore[attr-defined]


def test_live_restart_starts_closed_and_reconciliation_is_idempotent(backends, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    d = drill(backends, tmp_path)
    d.source.delete("x", op="forget-x")  # type: ignore[attr-defined]
    d.deliver_journal()
    d.gate().reconcile()
    versions = d.restored.ledger.latest_version("x")  # type: ignore[attr-defined]
    # Restart: new adapters and connections over the restored backends, durable ledger records copied.
    restarted = backends.world(schema=d.restored.metadata.schema)  # type: ignore[attr-defined]
    restarted.rep_audit.events.extend(d.restored.rep_audit.events)  # type: ignore[attr-defined]
    for item in d.items:
        for version in range(1, d.restored.ledger.latest_version(item) + 1):  # type: ignore[attr-defined]
            restarted.ledger.append(d.restored.ledger.get(item, version))  # type: ignore[attr-defined]
    d.restored = restarted
    gate = d.gate()
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        gate.serve(d.refs)
    assert gate.reconcile().obligations == 1
    assert restarted.ledger.latest_version("x") == versions  # no replacement event
    assert not mentions(gate.serve(d.refs), "x")


@pytest.mark.parametrize("forge", ["payload", "malformed", "other-recovery-point"])
def test_live_unauthenticated_or_unbound_checkpoint_keeps_restore_closed(backends, tmp_path: Path, forge: str) -> None:  # type: ignore[no-untyped-def]
    d = drill(backends, tmp_path)
    d.source.delete("x", op="forget-x")  # type: ignore[attr-defined]
    d.deliver_journal()
    d.issuer.forge = forge
    gate = d.gate()
    code = "RECOVERY_POINT_MISMATCH" if forge == "other-recovery-point" else "CHECKPOINT_UNAUTHENTICATED"
    with pytest.raises(DeletionRecoveryError, match=code):
        gate.reconcile()
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        gate.serve(d.refs)
    assert mentions(d.refs(), "x")  # nothing was purged on an unauthenticated checkpoint


def test_live_a_deletion_after_reopening_closes_the_gate_until_reconciled(backends, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    d = drill(backends, tmp_path)
    d.source.delete("x", op="forget-x")  # type: ignore[attr-defined]
    d.deliver_journal()
    gate = d.gate()
    gate.reconcile()
    assert mentions(gate.serve(d.refs), "y")
    d.source.delete("y", op="forget-y")  # type: ignore[attr-defined]
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_MISMATCH"):
        gate.serve(d.refs)
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        gate.serve(d.refs)
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_MISMATCH"):
        gate.reconcile()  # the restore site still holds the stale journal
    d.deliver_journal()
    assert gate.reconcile().obligations == 2
    found = gate.serve(d.refs)
    assert not mentions(found, "x") and not mentions(found, "y") and mentions(found, "keep")


class RestoredReplica:
    """Restored replica/export copy of the source's replica participant."""

    name = "replica"

    def __init__(self, refs: set[str]) -> None:
        self.present = set(refs)

    def purge(self, target) -> None:  # type: ignore[no-untyped-def]
        self.present -= set(target.version_refs)

    def residue(self, target) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
        return tuple(sorted(self.present & set(target.version_refs)))


def test_live_unfinished_deletion_is_replayed_and_an_omitted_store_keeps_restore_closed(backends, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _, _, _, t55, _ = live_modules()
    replica = t55.FailingParticipant(failures=1)
    d = drill(backends, tmp_path, replica=replica)
    replica.track(d.items["y"])
    assert d.source.delete("y", op="forget-y-1").lifecycle_status == "DELETION_INCOMPLETE"  # type: ignore[attr-defined]
    d.deliver_journal()
    # The restore composition omits the replica the source saga recorded.
    omitted = d.gate()
    with pytest.raises(DeletionRecoveryError, match="DELETION_PARTICIPANT_MISSING"):
        omitted.reconcile()
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        omitted.serve(d.refs)
    restored_replica = RestoredReplica({"urn:ocor:memory:y:v1"})
    gate = d.gate(restored_replica)
    gate.reconcile()
    assert d.restored.status("y") == "DELETION_INCOMPLETE" and restored_replica.present == set()  # type: ignore[attr-defined]
    assert not mentions(gate.serve(d.refs), "y")
    # The authority completes its saga: a new journal entry and new versions to replay.
    assert d.source.delete("y", op="forget-y-2").lifecycle_status == "DELETED"  # type: ignore[attr-defined]
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_MISMATCH"):
        gate.serve(d.refs)
    d.deliver_journal()
    gate.reconcile()
    assert d.restored.status("y") == "DELETED"  # type: ignore[attr-defined]
    assert d.restored.ledger.latest_version("y") == d.source.ledger.latest_version("y")  # type: ignore[attr-defined]
    assert not mentions(gate.serve(d.refs), "y")


@pytest.mark.parametrize("fault", ["purge", "inventory"])
def test_live_backend_fault_during_reconciliation_keeps_restore_closed_then_retry_opens(backends, tmp_path: Path, fault: str) -> None:  # type: ignore[no-untyped-def]
    d = drill(backends, tmp_path)
    d.source.delete("x", op="forget-x")  # type: ignore[attr-defined]
    d.deliver_journal()
    index = d.restored.vector  # type: ignore[attr-defined]
    method = "remove" if fault == "purge" else "read_back"
    original = getattr(index, method)
    calls = {"n": 0}

    def unavailable(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        raise ConnectionError("qdrant unavailable")

    setattr(index, method, unavailable)
    gate = d.gate()
    code = "DELETION_INCOMPLETE" if fault == "purge" else "DELETION_INVENTORY_UNAVAILABLE"
    with pytest.raises(DeletionRecoveryError, match=code):
        gate.reconcile()
    assert calls["n"] >= 1
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        gate.serve(d.refs)
    setattr(index, method, original)
    gate.reconcile()
    assert not mentions(gate.serve(d.refs), "x")


# --------------------------------------------------------------------------
# The restored searchMemory entry point is composed behind the gate
# --------------------------------------------------------------------------


def restored_search_type():  # type: ignore[no-untyped-def]
    from ocor_runtime.memory import deletion

    return deletion.RestoredMemorySearch


class SpySearch:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

    def search(self, request, *, binding):  # type: ignore[no-untyped-def]
        self.calls.append((request, binding))
        return {"hits": []}


def test_restored_search_is_closed_until_reconciled_and_forwards_unchanged(tmp_path: Path) -> None:
    gate, _, _, _ = gate_world(tmp_path)
    spy = SpySearch()
    search = restored_search_type()(service=spy, gate=gate)
    request, binding = {"retrieval_mode": "LEXICAL"}, object()
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        search.search(request, binding=binding)
    assert spy.calls == []
    gate.reconcile()
    assert search.search(request, binding=binding) == {"hits": []}
    assert spy.calls == [(request, binding)]


def test_restored_search_discards_a_response_when_residue_reappears(tmp_path: Path) -> None:
    gate, _, participant, _ = gate_world(tmp_path)
    gate.reconcile()

    class Resurrecting(SpySearch):
        def search(self, request, *, binding):  # type: ignore[no-untyped-def]
            participant.present.add("x")  # e.g. a replica re-synchronised from an old copy
            return super().search(request, binding=binding)

    search = restored_search_type()(service=Resurrecting(), gate=gate)
    with pytest.raises(DeletionRecoveryError, match="DELETION_INCOMPLETE"):
        search.search({}, binding=object())
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        search.search({}, binding=object())


def test_restored_search_requires_a_gate_and_a_search_port(tmp_path: Path) -> None:
    gate, _, _, _ = gate_world(tmp_path)
    search_type = restored_search_type()
    with pytest.raises(ValueError):
        search_type(service=SpySearch(), gate=object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        search_type(service=object(), gate=gate)  # type: ignore[arg-type]


def test_live_restored_search_entry_point_never_serves_a_deleted_item(backends, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ocor_runtime.memory.retrieval import RetrievalMode

    _, t52, _, t55, _ = live_modules()
    d = drill(backends, tmp_path)
    d.source.delete("x", op="forget-x")  # type: ignore[attr-defined]
    d.deliver_journal()
    gate = d.gate()
    search = restored_search_type()(service=d.restored.service(), gate=gate)  # type: ignore[attr-defined]

    def ask(mode: RetrievalMode):  # type: ignore[no-untyped-def]
        body = t52.request(mode, text=t55.TEXT, ctx=t55.CALLER, deadline=d.restored.deadline())  # type: ignore[attr-defined]
        return t52.refs(search.search(body, binding=t52.binding(t55.CALLER)))

    for mode in RetrievalMode:
        with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
            ask(mode)
    gate.reconcile()
    for mode in RetrievalMode:
        refs = ask(mode)
        assert "urn:ocor:memory:keep:v1" in refs and not any(r.startswith("urn:ocor:memory:x:") for r in refs), (mode, refs)
