"""REM-0036: the restore gate binds every historical per-version audit ref.

VF-002 of OCOR-DEV-0059 (verdict OCOR-DEV-0059-28173a069bee-1-env-recheck):
``MemoryRestoreGate._verify`` compared head, stage digest, version digests and
epochs but never ``entry["audit_refs"]``, so a restored metadata store whose
historical version carried another audit ref still reopened and served.
ADD v1.3 II 2.13 and LLD 2.8.6: the signed manifest binds per-version audit
refs and restore must refuse any divergence with PROJECTION_DRIFT and a denial
audit. Unit ports cover every version slot and both comparison points (open,
serve); live cases tamper the real restored PostgreSQL metadata of the 0056
drill (PostgreSQL, Qdrant, OpenBao transit). Implementer: Claude Code
(Anthropic).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import psycopg
import pytest
import test_ocor_dev_0055 as life
import test_ocor_dev_0057 as receipts
import test_ocor_dev_0059 as t59
from ocor_runtime.kernel.canonical import canonical_bytes, parse_i_json

# Reuse only fixtures. No imported test function is collected twice.
live_backends = life.live_backends
backends = life.backends

FORGED = "urn:sha256:" + "ab" * 32


def two_versions() -> tuple[Any, Any, Any]:
    """a-old at version 2 (legal hold), so version 1 is a historical slot."""
    w = life.unit_world()
    p = t59.seed(w)
    w.holds.place()
    w.move("a-old", "LEGAL_HOLD", hold=life.HOLD, reason="LITIGATION_HOLD")
    assert w.metadata.head("a-old") == 2
    s, _, _ = t59.setup(w)
    signer = t59.Signer()
    return w, signer, t59.capture(t59.backup_service(s, signer=signer), w, p)


def forge(w: Any, version: int, ref: str = FORGED) -> None:
    key = ("a-old", version)
    old = w.metadata.rows[key]
    w.metadata.rows[key] = dataclasses.replace(old, staged=dataclasses.replace(old.staged, audit_ref=ref))


def test_unit_restore_with_intact_historical_audit_refs_opens_and_serves(tmp_path: Path) -> None:
    w, signer, backup = two_versions()
    entry = parse_i_json(backup.payload)["entries"][0]
    assert entry["audit_refs"] == [w.metadata.get("a-old", v).staged.audit_ref for v in (1, 2)]
    restore, participant, audit = t59.unit_restore(w, tmp_path, signer)
    receipt = restore.open(backup.payload, backup.signature)
    assert receipt.verified_items == 1 and receipt.deleted_after_backup == ()
    assert restore.serve(lambda: "materialised") == "materialised"
    assert [e["action"] for e in audit.events][-2:] == ["memoryRestore.opened", "memoryRestore.served"]


@pytest.mark.parametrize("version", [1, 2])
def test_unit_one_altered_audit_ref_is_projection_drift_with_denial_audit(version: int, tmp_path: Path) -> None:
    w, signer, backup = two_versions()
    forge(w, version)
    restore, participant, audit = t59.unit_restore(w, tmp_path, signer)
    t59.refused(lambda: restore.open(backup.payload, backup.signature), "PROJECTION_DRIFT")
    assert participant.calls == ["x", "y"]  # compared only after the tombstone replay
    denial = audit.events[-1]
    assert (denial["action"], denial["outcome"], denial["detail_code"]) == (
        "memoryRestore.open.denied", "DENIED", "PROJECTION_DRIFT")
    assert "memoryRestore.opened" not in [e["action"] for e in audit.events]
    t59.refused(lambda: restore.serve(lambda: "materialised"), "RESTORE_NOT_OPEN")


def test_unit_audit_ref_altered_after_opening_discards_the_response(tmp_path: Path) -> None:
    w, signer, backup = two_versions()
    restore, _, audit = t59.unit_restore(w, tmp_path, signer)
    restore.open(backup.payload, backup.signature)
    served: list[str] = []

    def materialise() -> str:
        forge(w, 1)
        served.append("called")
        return "materialised"
    t59.refused(lambda: restore.serve(materialise), "PROJECTION_DRIFT")
    assert served == ["called"]
    denial = audit.events[-1]
    assert (denial["action"], denial["detail_code"]) == ("memoryRestore.serve.denied", "PROJECTION_DRIFT")
    assert "memoryRestore.served" not in [e["action"] for e in audit.events]
    t59.refused(lambda: restore.serve(lambda: "materialised"), "RESTORE_NOT_OPEN")


MANIFEST_REF_CHANGES = {
    "historical-ref": lambda refs: [FORGED, *refs[1:]],
    "missing-ref": lambda refs: refs[1:],
    "extra-ref": lambda refs: [*refs, FORGED],
    "swapped-refs": lambda refs: list(reversed(refs)),
}


@pytest.mark.parametrize("label", sorted(MANIFEST_REF_CHANGES))
def test_unit_signed_manifest_refs_must_match_the_restored_store(label: str, tmp_path: Path) -> None:
    change = MANIFEST_REF_CHANGES[label]
    w, signer, backup = two_versions()

    def edit(body: dict[str, Any]) -> None:
        body["entries"][0]["audit_refs"] = change(body["entries"][0]["audit_refs"])
    payload, signature = t59.resigned(backup, signer, edit)
    restore, _, audit = t59.unit_restore(w, tmp_path, signer)
    t59.refused(lambda: restore.open(payload, signature), "PROJECTION_DRIFT")
    assert audit.events[-1]["detail_code"] == "PROJECTION_DRIFT"
    t59.refused(lambda: restore.serve(lambda: "materialised"), "RESTORE_NOT_OPEN")


# ---- live: real restored PostgreSQL metadata of the 0056 drill ------------------------------

def forge_live(d: Any, item: str, version: int) -> None:
    """Rewrite only the audit ref of one restored version row (the copy, never the source)."""
    schema = d.restored.metadata.schema
    with psycopg.connect(d.restored.metadata.dsn, autocommit=True) as conn:
        row = conn.execute(f'SELECT body FROM "{schema}".versions WHERE memory_item_id = %s AND memory_version = %s',
                           (item, version)).fetchone()
        assert row is not None
        body = json.loads(row[0])
        assert body["audit_ref"] != FORGED
        body["audit_ref"] = FORGED
        updated = conn.execute(
            f'UPDATE "{schema}".versions SET body = %s WHERE memory_item_id = %s AND memory_version = %s',
            (canonical_bytes(body).decode(), item, version)).rowcount
        assert updated == 1


def denials(backends: life.Backends, d: Any) -> list[tuple[str, str]]:
    schema = d.restored.metadata.schema
    with psycopg.connect(backends.dsn) as conn:
        rows = conn.execute(f'SELECT body FROM "{schema}".memory_audit ORDER BY seq').fetchall()
    events = [json.loads(bytes(row[0])) for row in rows]
    return [(e["action"], e["detail_code"]) for e in events if e["outcome"] == "DENIED"]


def test_live_intact_historical_audit_refs_reopen_the_restore(backends: life.Backends, tmp_path: Path) -> None:
    d = t59.live_drill(backends, tmp_path, hold=True)
    backup, signer, _ = t59.live_capture(d, backends)
    entries = {e["memory_item_id"]: e for e in parse_i_json(backup.payload)["entries"]}
    assert entries["x"]["head_version"] == 2 and len(entries["x"]["audit_refs"]) == 2
    assert entries["x"]["audit_refs"] == [d.restored.metadata.get("x", v).staged.audit_ref for v in (1, 2)]
    d.deliver_journal()
    audit = receipts.PostgresReceiptAudit(backends.dsn, d.restored.metadata.schema)
    restore = t59.live_restore(d, backends, signer, audit=audit)
    assert restore.open(backup.payload, backup.signature).verified_items == 3
    restore.serve(d.refs)
    assert audit.actions()[-2:] == ["memoryRestore.opened", "memoryRestore.served"]
    assert denials(backends, d) == []


def test_live_one_altered_historical_audit_ref_blocks_materialisation(backends: life.Backends, tmp_path: Path) -> None:
    d = t59.live_drill(backends, tmp_path, hold=True)
    backup, signer, _ = t59.live_capture(d, backends)
    head = d.restored.metadata.get("x", 2).staged.stage_digest
    forge_live(d, "x", 1)
    assert d.restored.metadata.get("x", 2).staged.stage_digest == head  # the head slot is untouched
    assert d.restored.metadata.get("x", 1).staged.audit_ref == FORGED
    d.deliver_journal()
    audit = receipts.PostgresReceiptAudit(backends.dsn, d.restored.metadata.schema)
    restore = t59.live_restore(d, backends, signer, audit=audit)
    t59.refused(lambda: restore.open(backup.payload, backup.signature), "PROJECTION_DRIFT")
    assert denials(backends, d) == [("memoryRestore.open.denied", "PROJECTION_DRIFT")]
    assert "memoryRestore.opened" not in audit.actions()
    t59.refused(lambda: restore.serve(d.refs), "RESTORE_NOT_OPEN")
