"""REM-0023: denial audit at the real admission boundary, PostgreSQL authority.

The admission ledger is the real fsync/flock journal; denial events are written
and read through separate PostgreSQL connections. No boundary is mocked.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import psycopg
import pytest
import test_ocor_dev_0050 as base
from ocor_runtime.kernel.canonical import canonical_bytes, canonical_digest
from ocor_runtime.memory.model import (
    JournalMemoryVersionLedger,
    MemoryAdmissionError,
    MemoryAdmissionService,
)


class PostgresAudit:
    def __init__(self, dsn: str, table: str) -> None:
        self.dsn, self.table = dsn, table
        with psycopg.connect(dsn) as conn:
            conn.execute(
                f'CREATE TABLE "{table}" (seq bigserial PRIMARY KEY, body jsonb NOT NULL)'
            )

    def record(self, event: Mapping[str, object]) -> None:
        with psycopg.connect(self.dsn) as conn:
            conn.execute(
                f'INSERT INTO "{self.table}" (body) VALUES (%s::jsonb)',
                (canonical_bytes(dict(event)).decode(),),
            )

    def events(self) -> list[dict[str, Any]]:
        with psycopg.connect(self.dsn) as conn:
            return [
                row[0]
                for row in conn.execute(f'SELECT body FROM "{self.table}" ORDER BY seq')
            ]


class SchemaPostgresAudit:
    """Live consumer fixture sink; schema lifetime follows the existing world."""

    def __init__(self, dsn: str, schema: str) -> None:
        self.dsn, self.schema = dsn, schema
        with psycopg.connect(dsn) as conn:
            conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{schema}".admission_denials '
                '(seq bigserial PRIMARY KEY, body jsonb NOT NULL)'
            )

    def record(self, event: Mapping[str, object]) -> None:
        with psycopg.connect(self.dsn) as conn:
            conn.execute(
                f'INSERT INTO "{self.schema}".admission_denials (body) VALUES (%s::jsonb)',
                (canonical_bytes(dict(event)).decode(),),
            )


@pytest.fixture
def live(tmp_path: Path) -> Iterator[tuple[Any, PostgresAudit, Path]]:
    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    assert dsn, "REM-0023 requires the pinned real PostgreSQL backend"
    table = "rem0023_audit_" + uuid.uuid4().hex
    audit = PostgresAudit(dsn, table)
    path = tmp_path / "versions.jsonl"
    world = base.make_world(JournalMemoryVersionLedger(path))
    world.service = MemoryAdmissionService(
        ledger=world.ledger,
        resolver=world.resolver,
        policy=world.policy,
        markings=base.markings(),
        clock=world.clock,
        limits=base.AdmissionLimits(
            retention_horizons={"retention:standard": base.timedelta(days=365)}
        ),
        audit=audit,
    )
    try:
        yield world, audit, path
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')


def test_denial_is_durable_without_any_version_append(live: Any) -> None:
    world, audit, path = live
    before = path.read_bytes()
    with pytest.raises(MemoryAdmissionError) as caught:
        world.admit(base.candidate(memory_kind="LONG_TERM"))
    assert caught.value.reason_code == "MEMORY_SCHEMA_INVALID"
    assert path.read_bytes() == before
    assert JournalMemoryVersionLedger(path).get("mem-1", 1) is None
    events = audit.events()
    assert len(events) == 1, (
        "admitMemory denial missing from the durable audit authority"
    )
    event = events[0]
    assert event["outcome"] == "DENIED"
    assert event["reason_code"] == caught.value.reason_code
    assert event["detail_code"] == caught.value.detail_code
    assert event["correlation_id"] == base.CORRELATION
    assert event["governed_context_digest"] == base.GCS.digest()
    assert event["binding_ref"] == world.binding.binding_ref
    assert event["operation_id_digest"] == base.d("op-1")
    assert event["at"] == base.format_utc_timestamp(base.NOW)
    assert "pump" not in json.dumps(event)


# Each family starts with the same valid candidate. The companion positive
# below proves the live path can admit and replay rather than rejecting all.
CASES = [
    ("binding", "AUTHENTICATION_REQUIRED", "BINDING_MISSING"),
    ("envelope", "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("operation", "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("deadline-format", "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("deadline", "POLICY_DENIED", "DEADLINE_EXCEEDED"),
    ("context-object", "GOVERNED_CONTEXT_MISMATCH", "GCS_INVALID"),
    ("context-digest", "GOVERNED_CONTEXT_MISMATCH", "GOVERNED_CONTEXT_MISMATCH"),
    ("candidate-object", "MEMORY_SCHEMA_INVALID", "NOT_AN_OBJECT"),
    ("schema", "MEMORY_SCHEMA_INVALID", "REQUIRED_FIELD_MISSING"),
    ("binding-item", "GOVERNED_CONTEXT_MISMATCH", "ITEM_NOT_BOUND_TO_GCS"),
    ("content-schema", "MEMORY_SCHEMA_INVALID", "CONTENT_SCHEMA_UNKNOWN"),
    ("payload-type", "MEMORY_SCHEMA_INVALID", "PAYLOAD_INVALID"),
    ("payload-digest", "MEMORY_SCHEMA_INVALID", "CONTENT_DIGEST_MISMATCH"),
    ("secret", "POLICY_DENIED", "PROHIBITED_PAYLOAD_CREDENTIAL_ASSIGNMENT"),
    ("created-at", "POLICY_DENIED", "CREATED_AT_OUTSIDE_BOUNDARY_WINDOW"),
    ("expiry", "POLICY_DENIED", "ALREADY_EXPIRED"),
    ("retention", "POLICY_DENIED", "RETENTION_POLICY_UNKNOWN"),
    ("status", "LIFECYCLE_TRANSITION_INVALID", "ADMISSION_STATUS_INVALID"),
    ("semantic", "MEMORY_SCHEMA_INVALID", "SEMANTIC_DERIVATION_MISSING"),
    ("lineage", "MEMORY_VERSION_NOT_FOUND", "LINEAGE_SOURCE_MISSING"),
    ("resolver", "CONTROL_PLANE_UNAVAILABLE", "REFERENCE_RESOLVER_UNAVAILABLE"),
    ("source", "MEMORY_SCHEMA_INVALID", "SOURCE_UNRESOLVED"),
    ("evidence", "MEMORY_SCHEMA_INVALID", "EVIDENCE_UNRESOLVED"),
    ("provenance", "MEMORY_SCHEMA_INVALID", "PROVENANCE_UNRESOLVED"),
    ("marking", "AUTHORITY_DENIED", "INPUT_MARKING_EXCEEDS_CONTEXT"),
    ("taint", "MEMORY_TAINTED", "TAINT_LABEL_MISSING"),
    ("federation", "AUTHORITY_DENIED", "FEDERATION_POLICY_NOT_APPLICABLE"),
    ("instruction", "AUTHORITY_DENIED", "INSTRUCTION_APPROVAL_INVALID"),
    ("policy-deny", "POLICY_DENIED", "ADMISSION_DENIED"),
    ("policy-stale", "STALE_POLICY", "POLICY_BUNDLE_MISMATCH"),
    ("policy-fail", "CONTROL_PLANE_UNAVAILABLE", "POLICY_UNAVAILABLE"),
]


def denied_input(world: Any, case: str) -> tuple[Any, Any, Any]:
    request = base.envelope(base.candidate())
    cand = request["candidate"]
    payload, binding = base.PAYLOAD, world.binding
    if case == "binding":
        binding = None
    elif case == "envelope":
        request["extra"] = "untrusted"
    elif case == "operation":
        request["operation_id"] = None
    elif case == "deadline-format":
        request["deadline"] = "invalid"
    elif case == "deadline":
        request["deadline"] = base.format_utc_timestamp(base.NOW)
    elif case == "context-object":
        request["governed_context"] = []
    elif case == "context-digest":
        request["governed_context_digest"] = base.d("wrong")
    elif case == "candidate-object":
        request["candidate"] = []
    elif case == "schema":
        cand.pop("memory_item_id")
    elif case == "binding-item":
        cand["tenant_id"] = "tenant-b"
    elif case == "content-schema":
        cand["content_schema_ref"] = "urn:ocor:memory-content:unknown:1.0"
    elif case == "payload-type":
        payload = None
    elif case == "payload-digest":
        payload = b"different"
    elif case == "secret":
        payload = b"password = rem0023-synthetic-marker"
        cand["content_digest"] = base.d(payload)
    elif case == "created-at":
        cand["created_at"] = base.format_utc_timestamp(
            base.NOW - base.timedelta(hours=1)
        )
    elif case == "expiry":
        cand["expires_at"] = base.format_utc_timestamp(base.NOW)
    elif case == "retention":
        cand["retention_policy_ref"] = "unknown"
    elif case == "status":
        cand["lifecycle_status"] = "REVOKED"
    elif case == "semantic":
        cand["memory_kind"] = "SEMANTIC"
    elif case == "lineage":
        cand["derived_from_refs"] = ["urn:ocor:memory:missing:v1"]
    elif case == "resolver":
        world.resolver.fail = True
    elif case == "source":
        world.resolver.sources.clear()
    elif case == "evidence":
        world.resolver.evidence_records.clear()
    elif case == "provenance":
        world.resolver.provenance_records.clear()
    elif case == "marking":
        world.resolver.evidence_records["ev-1"] = base.evidence_record(
            marking=base.M_SECRET
        )
    elif case == "taint":
        cand["taint_labels"] = ["UNREVIEWED"]
    elif case == "federation":
        request["candidate"] = base.candidate(scope="FEDERATED")
        world.resolver.federation.clear()
    elif case == "instruction":
        request["candidate"] = base.candidate(
            "PROCEDURAL",
            "AGENT",
            instruction_eligible=True,
            instruction_approval_ref="approval-missing",
        )
    elif case.startswith("policy-"):
        world.policy.mode = case.removeprefix("policy-")
    else:
        raise AssertionError(case)
    return request, binding, payload


@pytest.mark.parametrize(("case", "reason", "detail"), CASES, ids=[c[0] for c in CASES])
def test_each_denial_family_is_audited_on_the_real_backend(
    live: Any, case: str, reason: str, detail: str
) -> None:
    world, audit, path = live
    request, binding, payload = denied_input(world, case)
    before = path.read_bytes()
    with pytest.raises(MemoryAdmissionError) as caught:
        world.service.admit(request, binding=binding, payload=payload)
    assert (caught.value.reason_code, caught.value.detail_code) == (reason, detail)
    assert path.read_bytes() == before
    events = audit.events()
    assert len(events) == 1
    event = events[0]
    assert (event["reason_code"], event["detail_code"]) == (reason, detail)
    assert event["outcome"] == "DENIED"
    assert event["governed_context_digest"] == (
        None if binding is None else base.GCS.digest()
    )
    assert event["correlation_id"] == (None if binding is None else base.CORRELATION)
    assert event["binding_ref"] == (None if binding is None else binding.binding_ref)
    assert "rem0023-synthetic-marker" not in json.dumps(event)


def test_success_and_replay_preserve_the_atomic_success_audit(live: Any) -> None:
    world, audit, path = live
    receipt = world.admit(base.candidate())
    before = path.read_bytes()
    assert world.admit(base.candidate()) == receipt
    assert path.read_bytes() == before
    record = JournalMemoryVersionLedger(path).get("mem-1", 1)
    assert record is not None
    assert canonical_digest(dict(record.audit_event)) == receipt.audit_ref
    assert (
        audit.events() == []
    )  # success already audited atomically in the version journal


@pytest.mark.parametrize("conflict", ["idempotency", "occupied", "replay-payload"])
def test_rejection_after_a_previous_admission_is_audited(
    live: Any, conflict: str
) -> None:
    world, audit, path = live
    receipt = world.admit(base.candidate())
    before = path.read_bytes()
    request = base.envelope(base.candidate())
    payload = base.PAYLOAD
    if conflict == "idempotency":
        request["candidate"]["confidence"] = 0.1
    elif conflict == "occupied":
        request["operation_id"] = "another"
    else:
        payload = b"altered"
    with pytest.raises(MemoryAdmissionError) as caught:
        world.service.admit(request, binding=world.binding, payload=payload)
    assert path.read_bytes() == before
    assert JournalMemoryVersionLedger(path).get("mem-1", 1).receipt == receipt
    assert len(audit.events()) == 1
    assert audit.events()[0]["detail_code"] == caught.value.detail_code


@pytest.mark.parametrize("case", [c[0] for c in CASES])
@pytest.mark.parametrize("missing", [False, True])
def test_audit_unavailable_refuses_without_a_version_or_success_receipt(
    live: Any, missing: bool, case: str
) -> None:
    world, audit, path = live
    # A real database error, not a mocked boundary: the authority table is absent.
    with psycopg.connect(audit.dsn) as conn:
        conn.execute(f'DROP TABLE "{audit.table}"')
    if missing:
        world.service._audit = None
    before = path.read_bytes()
    request, binding, payload = denied_input(world, case)
    with pytest.raises(MemoryAdmissionError) as caught:
        world.service.admit(request, binding=binding, payload=payload)
    assert (caught.value.reason_code, caught.value.detail_code) == (
        "CONTROL_PLANE_UNAVAILABLE",
        "AUDIT_UNAVAILABLE",
    )
    assert caught.value.correlation_id == (
        None if binding is None else base.CORRELATION
    )
    assert path.read_bytes() == before
    assert JournalMemoryVersionLedger(path).get("mem-1", 1) is None


def test_untrusted_request_fields_are_not_disclosed_or_used_as_identity(
    live: Any,
) -> None:
    world, audit, path = live
    request = base.envelope(base.candidate())
    request["operation_id"] = "synthetic-sensitive-operation"
    request["governed_context"]["tenant_id"] = "forged-tenant"
    request["governed_context"]["correlation_id"] = str(uuid.uuid4())
    with pytest.raises(MemoryAdmissionError):
        world.service.admit(
            request, binding=world.binding, payload=b"synthetic-sensitive-payload"
        )
    event = audit.events()[0]
    text = json.dumps(event)
    assert "synthetic-sensitive" not in text and "forged-tenant" not in text
    assert event["governed_context_digest"] == base.GCS.digest()
    assert event["correlation_id"] == base.CORRELATION
    assert path.read_bytes() == b""


@pytest.mark.parametrize("location", ["lookup", "append", "policy"])
def test_unexpected_port_failures_are_also_audited(
    live: Any, monkeypatch: Any, location: str
) -> None:
    world, audit, path = live

    def unavailable(*args: Any) -> Any:
        raise OSError("synthetic-sensitive-backend-diagnostic")

    target, method = (
        (world.policy, "authorize_admission")
        if location == "policy"
        else (world.ledger, "append" if location == "append" else "by_idempotency_key")
    )
    # Only local failure handling is injected; the admission boundary and audit
    # PostgreSQL are real. Acknowledged journal writes are never rolled back.
    monkeypatch.setattr(target, method, unavailable)
    before = path.read_bytes()
    with pytest.raises(MemoryAdmissionError) as caught:
        world.admit(base.candidate())
    event = audit.events()[0]
    assert event["reason_code"] == caught.value.reason_code
    assert event["detail_code"] == caught.value.detail_code
    assert path.read_bytes() == before
    assert "synthetic-sensitive" not in json.dumps(event)


def test_port_error_cannot_replace_the_binding_or_disclose_its_message(
    live: Any, monkeypatch: Any
) -> None:
    world, audit, path = live

    def reject(*args: Any) -> Any:
        raise MemoryAdmissionError(
            "POLICY_DENIED",
            "synthetic-sensitive-detail",
            "synthetic-sensitive-message",
            correlation_id=str(uuid.uuid4()),
        )

    monkeypatch.setattr(world.policy, "authorize_admission", reject)
    with pytest.raises(MemoryAdmissionError) as caught:
        world.admit(base.candidate())
    event = audit.events()[0]
    assert caught.value.correlation_id == event["correlation_id"] == base.CORRELATION
    assert event["detail_code"] == "ADMISSION_REJECTED"
    assert "synthetic-sensitive" not in json.dumps(event)
    assert path.read_bytes() == b""


def test_malformed_unicode_operation_is_fingerprinted_without_losing_denial_audit(
    live: Any,
) -> None:
    world, audit, path = live
    request = base.envelope(
        base.candidate(memory_kind="LONG_TERM"), operation_id="\ud800"
    )
    with pytest.raises(MemoryAdmissionError):
        world.service.admit(request, binding=world.binding, payload=base.PAYLOAD)
    assert audit.events()[0]["operation_id_digest"] == base.d(
        "\ud800".encode("utf-8", errors="surrogatepass")
    )
    assert path.read_bytes() == b""


def test_consumer_fixture_scope_and_durable_sink(tmp_path: Path) -> None:
    import importlib.util

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "rem0023_scope", root / "reports/tests/test_rem0023_consumer_fixture_scope.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    for path in guard.FILES:
        guard.compare(guard.baseline(path), (root / path).read_text())
        with pytest.raises(AssertionError):
            guard.compare(guard.baseline(path), (root / path).read_text() + "\nOUT_OF_SCOPE=True\n")
    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    assert dsn, "real PostgreSQL required"
    schema = "rem0023_sink_" + uuid.uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    try:
        sink = SchemaPostgresAudit(dsn, schema)
        event = {"action": "admitMemory.denied", "outcome": "DENIED"}
        sink.record(event)
        # A fresh sink/connection sees the same durable row, without overwriting.
        SchemaPostgresAudit(dsn, schema)
        with psycopg.connect(dsn) as conn:
            assert conn.execute(f'SELECT body FROM "{schema}".admission_denials').fetchall() == [(event,)]
            conn.execute(f'DROP TABLE "{schema}".admission_denials')
        with pytest.raises(psycopg.errors.UndefinedTable):
            sink.record(event)
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
