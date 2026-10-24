"""0059 checkpoint: partition-bound operations, quota and deterministic pressure.

ADD v1.3 II 2.6/2.10/2.13, LLD 2.8.6 and 7.2 FGM-19 oracles.
Unit ports exercise boundary branches. Live cases reuse the actual 0055
admission/lifecycle/store stack (PostgreSQL, Qdrant, OpenBao); fixture policy
and hold authorities are explicitly test ports, not end-to-end security proof.
Backup manifest/restore cases reuse the 0056 real backup drill and gate.
"""
from __future__ import annotations

import dataclasses
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
import test_ocor_dev_0052 as r
import test_ocor_dev_0055 as life
import test_ocor_dev_0057 as receipts
from ocor_runtime.kernel.canonical import format_utc_timestamp
from ocor_runtime.memory.model import LifecycleStatus, MemoryPolicyDecision
from ocor_runtime.memory.operations import (
    MemoryOperationsError, MemoryOperationsLimits, MemoryOperationsService, MemoryQuotaDemand,
)
from ocor_runtime.memory.stores import MemoryPartition

# Reuse only fixtures. No imported test function is collected twice.
live_backends = life.live_backends
backends = life.backends


class Policy:
    def __init__(self) -> None:
        self.allow = True
        self.fail = False
        self.bundle: str | None = None
        self.invalid = False
        self.calls: list[tuple[str, str]] = []

    def authorize_operations(self, operation: str, partition: MemoryPartition, ctx: Any) -> Any:
        self.calls.append((operation, partition.digest))
        if self.fail:
            raise TimeoutError("policy unavailable")
        if self.invalid:
            return {"permitted": True}
        return MemoryPolicyDecision(self.allow, "urn:ocor:decision:ops", self.bundle or ctx.policy_bundle_digest)


def setup(w: Any, **changes: Any) -> tuple[MemoryOperationsService, Any, Policy]:
    audit = receipts.ReceiptAudit()
    policy = Policy()
    options = dict(metadata=w.metadata, ledger=w.ledger, lifecycle=w.lifecycle,
                   policy=policy, audit=audit, stop=w.lc_stop, clock=w.clock,
                   limits=MemoryOperationsLimits(max_items=2, max_payload_bytes=64,
                       max_embedding_dimensions=8, max_top_k=10, max_consolidation_concurrency=2,
                       max_index_entries=6, retention_horizons={"retention:standard": timedelta(days=365)}))
    options.update(changes)
    return MemoryOperationsService(**options), audit, policy


def request(w: Any, partition: MemoryPartition, **changes: Any) -> dict[str, Any]:
    return dict(operation_id="ops-1", governed_context=r.context().to_mapping(),
                governed_context_digest=r.context().digest(), partition=partition.to_mapping(),
                deadline=format_utc_timestamp(w.clock.now() + timedelta(seconds=30)), **changes)


def seed(w: Any) -> MemoryPartition:
    record = w.admit("a-old", life.TEXT)
    return MemoryPartition.for_item(record.item)


def invoke(s: MemoryOperationsService, w: Any, partition: MemoryPartition, action: str = "monitor", **kw: Any) -> Any:
    return getattr(s, action)(request(w, partition), binding=r.binding(r.context()), **kw)


def refused(action: Any, detail: str) -> MemoryOperationsError:
    with pytest.raises(MemoryOperationsError) as caught:
        action()
    assert caught.value.detail_code == detail
    return caught.value


@pytest.mark.parametrize("field", ["max_items", "max_payload_bytes", "max_embedding_dimensions", "max_top_k",
                                   "max_consolidation_concurrency", "max_index_entries", "max_pressure_batch"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_configuration_limits_are_positive_integers(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        MemoryOperationsLimits(**{field: value})


def test_configuration_retention_is_mandatory_positive_and_copied() -> None:
    horizons = {"retention:standard": timedelta(days=3)}
    limits = MemoryOperationsLimits(retention_horizons=horizons)
    horizons.clear()
    assert limits.retention_horizons["retention:standard"] == timedelta(days=3)
    for horizons in ({}, {"retention:standard": timedelta(0)}, {"": timedelta(days=1)}):
        with pytest.raises(ValueError):
            MemoryOperationsLimits(retention_horizons=horizons)


@pytest.mark.parametrize("binding", [None, object(), {"expected": "caller-context"}])
def test_unverified_binding_never_reaches_policy_or_inventory(binding: Any) -> None:
    w = life.unit_world()
    p = seed(w)
    s, audit, policy = setup(w)
    refused(lambda: s.monitor(request(w, p), binding=binding), "BINDING_MISSING")
    assert policy.calls == []
    assert audit.events[-1]["governed_context_digest"] is None
    assert audit.events[-1]["correlation_id"] is None


@pytest.mark.parametrize("member,value", [("tenant_id", "tenant-b"), ("organization_id", "org-b"),
    ("domain_id", "domain-b"), ("compartments", ("bravo",)), ("purpose", "other"),
    ("classification_marking_ref", r.M_UNCLASSIFIED), ("policy_bundle_digest", r.d("other-policy")),
    ("ontology_release_digest", r.d("other-release"))])
def test_partition_cannot_escape_the_verified_context(member: str, value: Any) -> None:
    w = life.unit_world()
    p = seed(w)
    s, audit, policy = setup(w)
    other = dataclasses.replace(p, **{member: value})
    refused(lambda: invoke(s, w, other), "PARTITION_DENIED")
    assert policy.calls == []
    assert audit.events[-1]["outcome"] == "DENIED"


@pytest.mark.parametrize("fault,detail", [("deny", "OPERATIONS_DENIED"), ("fail", "POLICY_UNAVAILABLE"),
                                         ("stale", "STALE_POLICY"), ("invalid", "POLICY_DECISION_INVALID")])
def test_policy_failure_is_audited_before_inventory(fault: str, detail: str) -> None:
    w = life.unit_world()
    p = seed(w)
    s, audit, policy = setup(w)
    if fault == "deny":
        policy.allow = False
    elif fault == "stale":
        policy.bundle = r.d("stale")
    else:
        setattr(policy, fault, True)
    w.metadata.versions_in = lambda _: pytest.fail("inventory before authorization")
    refused(lambda: invoke(s, w, p), detail)
    assert audit.events[-1]["outcome"] == "DENIED"


@pytest.mark.parametrize("field,value,detail", [
    ("new_items", 2, "ITEM_QUOTA_EXCEEDED"), ("payload_bytes", 65, "PAYLOAD_QUOTA_EXCEEDED"),
    ("embedding_dimensions", 9, "EMBEDDING_QUOTA_EXCEEDED"), ("top_k", 11, "TOP_K_QUOTA_EXCEEDED"),
    ("consolidation_concurrency", 3, "CONSOLIDATION_QUOTA_EXCEEDED"),
    ("new_index_entries", 4, "INDEX_QUOTA_EXCEEDED"),
    ("retention_seconds", 365 * 86400 + 1, "RETENTION_QUOTA_EXCEEDED"),
])
def test_each_configured_quota_has_a_positive_and_negative(field: str, value: int, detail: str) -> None:
    w = life.unit_world()
    p = seed(w)
    s, audit, _ = setup(w)
    assert invoke(s, w, p, "check_quota", demand=MemoryQuotaDemand()).permitted
    refused(lambda: invoke(s, w, p, "check_quota", demand=MemoryQuotaDemand(**{field: value})), detail)
    assert audit.events[-1]["outcome"] == "DENIED"
    assert w.lifecycle.head("a-old").item.lifecycle_status is LifecycleStatus.ACTIVE


def test_head_versions_count_once_and_deleted_items_do_not_free_tombstones() -> None:
    w = life.unit_world()
    p = seed(w)
    w.admit("a-old", life.TEXT + " correction", version=2)
    s, _, _ = setup(w)
    assert invoke(s, w, p).items == 1
    w.delete("a-old")
    report = invoke(s, w, p)
    assert report.items == 0 and report.tombstones == 1
    assert len(w.tombstones.entries("a-old")) == 2


def test_pressure_selects_deterministically_and_never_deletes_legal_hold() -> None:
    w = life.unit_world()
    p = seed(w)
    w.admit("b-old", life.TEXT + " b")
    w.admit("held", life.TEXT + " held")
    w.holds.place()
    w.move("held", "LEGAL_HOLD", hold=life.HOLD)
    s, audit, _ = setup(w)
    report = invoke(s, w, p, "relieve_pressure", target_items=1, limit=1)
    assert report.deleted == ("a-old",)
    assert report.remaining_items == 2 and report.satisfied is False
    assert w.status("held") == "LEGAL_HOLD"
    assert w.tombstones.entries("held") == ()
    assert audit.events[-1]["outcome"] == "BACKPRESSURE"
    second = invoke(s, w, p, "relieve_pressure", target_items=1, limit=1)
    assert second.deleted == ("b-old",) and second.satisfied
    assert w.status("held") == "LEGAL_HOLD"


def test_retention_uses_first_creation_and_trusted_clock() -> None:
    w = life.unit_world()
    p = seed(w)
    w.clock.advance(timedelta(days=20))
    w.move("a-old", "REVOKED")
    w.clock.advance(timedelta(days=350))
    s, _, _ = setup(w)
    report = invoke(s, w, p, "enforce_retention", limit=1)
    assert report.deleted == ("a-old",) and report.satisfied
    assert w.status("a-old") == "DELETED"


@pytest.mark.parametrize("action", ["monitor", "check_quota", "relieve_pressure", "enforce_retention"])
def test_audit_failure_never_returns_success(action: str) -> None:
    w = life.unit_world()
    p = seed(w)
    s, audit, _ = setup(w)
    audit.fail = True
    kwargs = {"demand": MemoryQuotaDemand()} if action == "check_quota" else (
        {"target_items": 0, "limit": 1} if action == "relieve_pressure" else ({"limit": 1} if action == "enforce_retention" else {}))
    refused(lambda: invoke(s, w, p, action, **kwargs), "AUDIT_UNAVAILABLE")
    assert w.status("a-old") == "ACTIVE"


def test_unauthorized_partition_does_not_influence_count_pressure_or_metric_labels() -> None:
    w = life.unit_world()
    p = seed(w)
    s, audit, _ = setup(w)
    baseline = invoke(s, w, p).to_mapping()
    for i in range(5):
        w.admit(f"hidden-{i}", life.TEXT, ctx=r.context(compartments=("bravo",)))
    assert invoke(s, w, p).to_mapping() == baseline
    assert all("hidden-" not in repr(k) and "alpha" not in repr(k) and "tenant-a" not in repr(k) for k in s.metrics)
    assert audit.events[-1]["partition_digest"] == p.digest


def test_real_partition_pressure_preserves_hold_and_durable_tombstones(backends: life.Backends, tmp_path: Path) -> None:
    journal = tmp_path / "tombstones.jsonl"
    w = backends.world(tombstones=life.JournalTombstoneStore(journal))
    p = seed(w)
    w.admit("b-old", life.TEXT + " b")
    w.admit("held", life.TEXT + " held")
    w.holds.place()
    w.move("held", "LEGAL_HOLD", hold=life.HOLD)
    audit = receipts.PostgresReceiptAudit(backends.dsn, w.metadata.schema)
    s, _, _ = setup(w, audit=audit)
    result = invoke(s, w, p, "relieve_pressure", target_items=1, limit=2)
    assert result.deleted == ("a-old", "b-old") and result.satisfied
    assert w.status("held") == "LEGAL_HOLD" and w.tombstones.entries("held") == ()
    assert w.tombstones.entries("a-old")[-1].phase == "COMPLETED"
    assert w.tombstones.entries("b-old")[-1].phase == "COMPLETED"
    fresh = life.JournalTombstoneStore(journal)
    assert fresh.entries("a-old") == w.tombstones.entries("a-old")
    assert fresh.entries("b-old") == w.tombstones.entries("b-old")
    for item_id in result.deleted:
        record = w.ledger.get(item_id, 1)
        assert not life.content_present(w, record)
    assert life.content_present(w, w.ledger.get("held", 1))
    assert receipts.PostgresReceiptAudit(backends.dsn, w.metadata.schema).receipt(result.audit_ref)["outcome"] == "COMPLETED"


def test_real_unauthorized_partition_cannot_change_quota_decision(backends: life.Backends) -> None:
    w = backends.world()
    p = seed(w)
    s, _, _ = setup(w, audit=receipts.PostgresReceiptAudit(backends.dsn, w.metadata.schema))
    before = invoke(s, w, p, "check_quota", demand=MemoryQuotaDemand(new_items=1)).usage
    for i in range(4):
        w.admit(f"hidden-{i}", life.TEXT, ctx=r.context(compartments=("bravo",)))
    after = invoke(s, w, p, "check_quota", demand=MemoryQuotaDemand(new_items=1)).usage
    assert after == before
    denied = dataclasses.replace(p, tenant_id="tenant-b")
    refused(lambda: invoke(s, w, denied), "PARTITION_DENIED")


@pytest.mark.parametrize("field", ["new_items", "payload_bytes", "embedding_dimensions", "top_k",
    "consolidation_concurrency", "new_index_entries", "retention_seconds"])
@pytest.mark.parametrize("value", [True, -1, 1.5])
def test_invalid_demand_never_silently_coerces_or_releases_quota(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        MemoryQuotaDemand(**{field: value})


@pytest.mark.parametrize("field,value", [("operation_id", ""), ("operation_id", True), ("deadline", "bad"),
    ("deadline", 0), ("governed_context", None), ("governed_context_digest", "forged"), ("partition", None)])
def test_request_envelope_failures_are_audited(field: str, value: Any) -> None:
    w = life.unit_world()
    p = seed(w)
    s, audit, _ = setup(w)
    body = request(w, p)
    body[field] = value
    with pytest.raises(MemoryOperationsError):
        s.monitor(body, binding=r.binding(r.context()))
    assert audit.events[-1]["outcome"] == "DENIED"
    assert w.status("a-old") == "ACTIVE"


@pytest.mark.parametrize("action", ["monitor", "check_quota", "relieve_pressure", "enforce_retention"])
def test_changed_stop_state_cannot_return_success(action: str) -> None:
    w = life.unit_world()
    p = seed(w)
    s, audit, _ = setup(w)
    w.lc_stop.bump_after = 1
    kwargs = {"demand": MemoryQuotaDemand()} if action == "check_quota" else (
        {"target_items": 0, "limit": 1} if action == "relieve_pressure" else ({"limit": 1} if action == "enforce_retention" else {}))
    refused(lambda: invoke(s, w, p, action, **kwargs), "STOP_EPOCH_MISMATCH")
    assert audit.events[-1]["outcome"] == "DENIED"
    assert w.status("a-old") == "ACTIVE"


@pytest.mark.parametrize("state", [True, -1, "0"])
def test_invalid_stop_epoch_is_not_an_admission(state: Any) -> None:
    w = life.unit_world()
    p = seed(w)
    s, _, _ = setup(w)
    w.lc_stop.epoch = state
    refused(lambda: invoke(s, w, p), "STOP_STATE_INVALID")


def test_inventory_unavailable_is_never_zero_usage() -> None:
    w = life.unit_world()
    p = seed(w)
    s, audit, _ = setup(w)
    def missing(_: str) -> Any:
        raise ConnectionError("metadata unavailable")
    w.metadata.versions_in = missing
    refused(lambda: invoke(s, w, p), "OPERATIONS_UNAVAILABLE")
    assert audit.events[-1]["outcome"] == "DENIED"


def test_unknown_retention_policy_is_not_permission_to_forget() -> None:
    w = life.unit_world()
    p = seed(w)
    s, _, _ = setup(w)
    refused(lambda: invoke(s, w, p, "check_quota", demand=MemoryQuotaDemand(retention_policy_ref="unknown")),
            "RETENTION_UNCONFIGURED")
    s, _, _ = setup(w, limits=MemoryOperationsLimits(retention_horizons={"other": timedelta(days=1)}))
    refused(lambda: invoke(s, w, p, "enforce_retention", limit=1), "RETENTION_UNCONFIGURED")
    assert w.status("a-old") == "ACTIVE"


def test_partial_deletion_does_not_release_the_item_quota() -> None:
    replica = life.FailingParticipant(1)
    w = life.unit_world(replica=replica)
    record = w.admit("a-old", life.TEXT)
    replica.track(record)
    p = MemoryPartition.for_item(record.item)
    s, _, _ = setup(w)
    report = invoke(s, w, p, "relieve_pressure", target_items=0, limit=1)
    assert report.incomplete == ("a-old",) and report.deleted == ()
    assert report.remaining_items == 1 and not report.satisfied
    assert invoke(s, w, p).incomplete_deletions == 1
    assert w.status("a-old") == "DELETION_INCOMPLETE"


def test_legal_hold_placed_during_pressure_policy_check_is_not_evicted() -> None:
    w = life.unit_world()
    p = seed(w)
    s, _, policy = setup(w)
    original = policy.authorize_operations
    def raced(operation: str, partition: MemoryPartition, ctx: Any) -> Any:
        if len(policy.calls) == 1:
            w.holds.place()
            w.move("a-old", "LEGAL_HOLD", hold=life.HOLD)
        return original(operation, partition, ctx)
    policy.authorize_operations = raced
    refused(lambda: invoke(s, w, p, "relieve_pressure", target_items=0, limit=1), "CANDIDATE_CHANGED")
    assert w.status("a-old") == "LEGAL_HOLD"
    assert w.tombstones.entries("a-old") == ()


@pytest.mark.parametrize("field,value,detail", [
    ("new_items", 2, "ITEM_QUOTA_EXCEEDED"), ("payload_bytes", 65, "PAYLOAD_QUOTA_EXCEEDED"),
    ("embedding_dimensions", 9, "EMBEDDING_QUOTA_EXCEEDED"), ("top_k", 11, "TOP_K_QUOTA_EXCEEDED"),
    ("consolidation_concurrency", 3, "CONSOLIDATION_QUOTA_EXCEEDED"),
    ("new_index_entries", 4, "INDEX_QUOTA_EXCEEDED"),
    ("retention_seconds", 365 * 86400 + 1, "RETENTION_QUOTA_EXCEEDED"),
])
def test_real_configured_quotas_do_not_delete_existing_content(
    backends: life.Backends, field: str, value: int, detail: str,
) -> None:
    w = backends.world()
    p = seed(w)
    audit = receipts.PostgresReceiptAudit(backends.dsn, w.metadata.schema)
    s, _, _ = setup(w, audit=audit)
    positive = invoke(s, w, p, "check_quota", demand=MemoryQuotaDemand())
    assert positive.permitted and audit.receipt(positive.audit_ref)["outcome"] == "COMPLETED"
    refused(lambda: invoke(s, w, p, "check_quota", demand=MemoryQuotaDemand(**{field: value})), detail)
    assert audit.actions()[-1] == "memoryQuota.denied"
    assert w.status("a-old") == "ACTIVE"
    assert life.content_present(w, w.ledger.get("a-old", 1))


def test_real_audit_unavailable_refuses_pressure_before_deletion(backends: life.Backends) -> None:
    w = backends.world()
    p = seed(w)
    audit = receipts.PostgresReceiptAudit(backends.dsn, w.metadata.schema)
    s, _, _ = setup(w, audit=audit)
    with psycopg.connect(backends.dsn, autocommit=True) as conn:
        conn.execute(f'DROP TABLE "{w.metadata.schema}".memory_audit')
    refused(lambda: invoke(s, w, p, "relieve_pressure", target_items=0, limit=1), "AUDIT_UNAVAILABLE")
    assert w.status("a-old") == "ACTIVE" and w.tombstones.entries("a-old") == ()
    assert life.content_present(w, w.ledger.get("a-old", 1))


def test_real_retention_keeps_new_items_and_holds(backends: life.Backends) -> None:
    w = backends.world()
    p = seed(w)
    w.admit("held", life.TEXT + " hold")
    w.holds.place()
    w.move("held", "LEGAL_HOLD", hold=life.HOLD)
    w.clock.advance(timedelta(days=20))
    w.admit("young", life.TEXT + " young")
    w.clock.advance(timedelta(days=350))
    s, _, _ = setup(w, audit=receipts.PostgresReceiptAudit(backends.dsn, w.metadata.schema))
    report = invoke(s, w, p, "enforce_retention", limit=2)
    assert report.deleted == ("a-old",) and report.held == ("held",) and not report.satisfied
    assert w.status("young") == "ACTIVE" and w.status("held") == "LEGAL_HOLD"


def test_a_head_change_during_inventory_refuses_a_stale_quota_or_monitor_result() -> None:
    w = life.unit_world()
    p = seed(w)
    s, audit, _ = setup(w)
    original = w.metadata.get
    switched = False
    def racing_get(item_id: str, version: int) -> Any:
        nonlocal switched
        result = original(item_id, version)
        if not switched:
            switched = True
            w.move("a-old", "REVOKED")
        return result
    w.metadata.get = racing_get
    refused(lambda: invoke(s, w, p), "CANDIDATE_CHANGED")
    assert audit.events[-1]["outcome"] == "DENIED"
    assert w.status("a-old") == "REVOKED"


class SerializedQuota:
    """Unit composition port; only live PostgreSQL locks qualify contention."""

    def __init__(self) -> None:
        self.mutex = threading.Lock()
        self.fail = False
        self.partitions: list[str] = []

    @contextmanager
    def hold(self, partition_digest: str) -> Any:
        self.partitions.append(partition_digest)
        if self.fail:
            raise ConnectionError("serialization authority unavailable")
        with self.mutex:
            yield


class PostgresSerializedQuota:
    """Test adapter for the trusted serialization port, shared across writers.

    Each test world owns its schema. Writers for that world lock the same
    partition for inventory + ledger admission + store commit, not a quota token.
    The lock has a bounded wait and PostgreSQL releases it on rollback/crash.
    """

    def __init__(self, dsn: str, schema: str) -> None:
        self.dsn, self.schema = dsn, schema

    @contextmanager
    def hold(self, partition_digest: str) -> Any:
        key = int.from_bytes(hashlib.sha256((self.schema + partition_digest).encode()).digest()[:8], signed=True)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("SET LOCAL lock_timeout = '3s'")
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
            yield


def writer(w: Any, s: MemoryOperationsService, serialization: Any = None) -> Any:
    from ocor_runtime.memory.operations import MemoryQuotaWriter
    return MemoryQuotaWriter(operations=s, admission=w.admission, store=w.coordinator,
                             serialization=serialization if serialization is not None else SerializedQuota())


def write_request(w: Any, *, item_id: str = "new", text: str = life.TEXT, version: int = 1) -> tuple[dict[str, Any], bytes, Any]:
    candidate = dict(w.ledger.get("a-old", 1).item.to_mapping())
    payload, embedding = text.encode(), r.embed(text)
    candidate.update(memory_item_id=item_id, memory_version=version,
                     content_ref="content:" + r.d(payload).removeprefix("urn:sha256:"), content_digest=r.d(payload),
                     embedding_ref=f"embedding:{item_id}:v{version}", embedding_digest=r.vector_digest(embedding))
    if version > 1:
        candidate["supersedes_ref"] = r.memory_version_ref(item_id, version - 1)
    body = dict(operation_id=f"write-{item_id}-{version}", governed_context=r.context().to_mapping(),
                governed_context_digest=r.context().digest(), deadline=w.deadline(), candidate=candidate)
    return body, payload, embedding


def write(wr: Any, w: Any, **kw: Any) -> Any:
    body, payload, embedding = write_request(w, **kw)
    return wr.admit_and_commit(body, binding=r.binding(r.context()), payload=payload, embedding=embedding)


@pytest.mark.parametrize("live", [False, True])
def test_quota_writer_rejects_the_actual_third_item_without_appending_or_indexing(
    live: bool, backends: life.Backends,
) -> None:
    w = backends.world() if live else life.unit_world()
    p = seed(w)
    audit = receipts.PostgresReceiptAudit(backends.dsn, w.metadata.schema) if live else receipts.ReceiptAudit()
    s, _, _ = setup(w, audit=audit)
    wr = writer(w, s, PostgresSerializedQuota(backends.dsn, w.metadata.schema) if live else None)
    accepted = write(wr, w)
    assert accepted.state == "COMMITTED" and w.metadata.head("new") == 1
    before = life.ledger_snapshot(w)
    refused(lambda: write(wr, w, item_id="over"), "ITEM_QUOTA_EXCEEDED")
    assert life.ledger_snapshot(w) == before
    assert w.metadata.head("over") == 0
    assert len(w.content.refs(p.digest)) == 1  # identical payloads share one content-addressed object
    if live:
        assert audit.actions()[-1] == "memoryWrite.denied"
    else:
        assert audit.events[-1]["outcome"] == "DENIED"


@pytest.mark.parametrize("field,value,detail", [
    ("max_payload_bytes", 4, "PAYLOAD_QUOTA_EXCEEDED"),
    ("max_embedding_dimensions", 2, "EMBEDDING_QUOTA_EXCEEDED"),
    ("max_index_entries", 5, "INDEX_QUOTA_EXCEEDED"),
])
@pytest.mark.parametrize("live", [False, True])
def test_quota_writer_derives_demand_from_bytes_and_candidate_not_caller_counters(
    field: str, value: int, detail: str, live: bool, backends: life.Backends,
) -> None:
    w = backends.world() if live else life.unit_world()
    seed(w)
    limits = dataclasses.replace(MemoryOperationsLimits(), **{field: value})
    s, audit, _ = setup(w, limits=limits)
    wr = writer(w, s, PostgresSerializedQuota(backends.dsn, w.metadata.schema) if live else None)
    before = life.ledger_snapshot(w)
    refused(lambda: write(wr, w), detail)
    assert life.ledger_snapshot(w) == before and w.metadata.head("new") == 0
    assert audit.events[-1]["outcome"] == "DENIED"
    # Same write at the exact configured boundary is accepted, without dropping a representation.
    s, _, _ = setup(w, limits=dataclasses.replace(limits, **{field: {"max_payload_bytes": len(life.TEXT.encode()),
        "max_embedding_dimensions": len(r.embed(life.TEXT)), "max_index_entries": 6}[field]}))
    result = write(writer(w, s), w)
    assert result.state == "COMMITTED" and len(result.representations) == 3


@pytest.mark.parametrize("live", [False, True])
def test_quota_writer_allows_exact_replay_and_correction_at_capacity(live: bool, backends: life.Backends) -> None:
    w = backends.world() if live else life.unit_world()
    seed(w)
    s, _, _ = setup(w, limits=MemoryOperationsLimits(max_items=1, max_index_entries=3))
    wr = writer(w, s, PostgresSerializedQuota(backends.dsn, w.metadata.schema) if live else None)
    result = write(wr, w, item_id="a-old", text=life.TEXT + " updated", version=2)
    assert result.head_version == 2
    before = life.ledger_snapshot(w)
    replay = write(wr, w, item_id="a-old", text=life.TEXT + " updated", version=2)
    assert replay == result and life.ledger_snapshot(w) == before
    assert invoke(s, w, MemoryPartition.for_item(w.ledger.get("a-old", 2).item)).items == 1


@pytest.mark.parametrize("fault,detail", [("audit", "AUDIT_UNAVAILABLE"), ("policy", "POLICY_UNAVAILABLE"),
    ("serialization", "QUOTA_SERIALIZATION_UNAVAILABLE"), ("stop", "STOP_STATE_INVALID")])
def test_quota_writer_missing_authorities_never_invoke_admission(fault: str, detail: str) -> None:
    w = life.unit_world()
    seed(w)
    s, audit, policy = setup(w)
    lock = SerializedQuota()
    if fault == "audit":
        audit.fail = True
    elif fault == "policy":
        policy.fail = True
    elif fault == "serialization":
        lock.fail = True
    else:
        w.lc_stop.epoch = -1
    before = life.ledger_snapshot(w)
    refused(lambda: write(writer(w, s, lock), w), detail)
    assert life.ledger_snapshot(w) == before and w.metadata.head("new") == 0


@pytest.mark.parametrize("tamper,detail,holds", [
    ("scope", "PARTITION_DENIED", 0), ("gcs", "GCS_INVALID", 0), ("demand", "ENVELOPE_INVALID", 0),
    ("payload", "CONTENT_DIGEST_MISMATCH", 0), ("vector", "EMBEDDING_INVALID", 0), ("retention", "RETENTION_UNCONFIGURED", 1),
    # Claude Code: the candidate itself must be bound to the plan GCS/owner before the serialization hold.
    ("candidate-gcs", "ITEM_NOT_BOUND_TO_GCS", 0), ("owner", "ITEM_NOT_BOUND_TO_GCS", 0),
])
def test_quota_writer_cannot_bypass_binding_or_actual_demand(tamper: str, detail: str, holds: int) -> None:
    w = life.unit_world()
    seed(w)
    s, audit, _ = setup(w)
    lock = SerializedQuota()
    wr = writer(w, s, lock)
    body, payload, embedding = write_request(w)
    if tamper == "scope":
        body["candidate"]["compartments"] = ["bravo"]
    elif tamper == "gcs":
        body["governed_context_digest"] = r.d("other")
    elif tamper == "demand":
        body["demand"] = {"new_items": 0}
    elif tamper == "payload":
        payload = b"different content"
    elif tamper == "vector":
        embedding = [0.0] * len(embedding)
    elif tamper == "retention":
        body["candidate"]["retention_policy_ref"] = "unknown"
    elif tamper == "candidate-gcs":
        body["candidate"]["governed_context_digest"] = r.d("other-gcs")
    else:
        body["candidate"]["owner_principal_id"] = "principal-other"
    before = life.ledger_snapshot(w)
    refused(lambda: wr.admit_and_commit(body, binding=r.binding(r.context()), payload=payload, embedding=embedding), detail)
    assert life.ledger_snapshot(w) == before and w.metadata.head("new") == 0
    assert audit.events[-1]["outcome"] == "DENIED"
    assert len(lock.partitions) == holds  # refused before admission; only the retention bound is checked under the hold


def test_real_two_quota_writers_share_the_same_serialization_boundary(backends: life.Backends) -> None:
    w = backends.world()
    p = seed(w)
    s1, _, _ = setup(w, audit=receipts.PostgresReceiptAudit(backends.dsn, w.metadata.schema))
    s2, _, _ = setup(w, audit=receipts.PostgresReceiptAudit(backends.dsn, w.metadata.schema))
    writers = [writer(w, s, PostgresSerializedQuota(backends.dsn, w.metadata.schema)) for s in (s1, s2)]
    start = threading.Barrier(2)
    def contend(i: int) -> str:
        start.wait(timeout=5)
        try:
            return write(writers[i], w, item_id=f"parallel-{i}").state
        except MemoryOperationsError as error:
            return error.detail_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(contend, range(2)))
    assert sorted(outcomes) == ["COMMITTED", "ITEM_QUOTA_EXCEEDED"]
    assert invoke(s1, w, p).items == 2
    assert sum(w.metadata.head(f"parallel-{i}") == 1 for i in range(2)) == 1


def test_real_serialization_lock_timeout_is_fail_closed(backends: life.Backends) -> None:
    w = backends.world()
    seed(w)
    s, _, _ = setup(w)
    port = PostgresSerializedQuota(backends.dsn, w.metadata.schema)
    p = MemoryPartition.for_item(w.ledger.get("a-old", 1).item)
    with port.hold(p.digest):
        before = life.ledger_snapshot(w)
        refused(lambda: write(writer(w, s, PostgresSerializedQuota(backends.dsn, w.metadata.schema)), w),
                "QUOTA_SERIALIZATION_UNAVAILABLE")
        assert life.ledger_snapshot(w) == before and w.metadata.head("new") == 0
    assert write(writer(w, s, port), w).state == "COMMITTED"


# --------------------------------------------------------------------------
# Backup manifest and restore materialisation (ADD v1.3 II 2.13, LLD 2.8.6,
# FGM-18). Implementer of this slice: Claude Code (Anthropic). Live cases reuse
# the 0056 real backup drill (PostgreSQL snapshot copy, Qdrant snapshot
# recovery, OpenBao transit attestation) and its DeletionRestoreGate.
# --------------------------------------------------------------------------

MANIFEST_KEYS = {"schema", "recovery_point_id", "operation_id", "partition", "partition_digest",
                 "governed_context_digest", "captured_at", "journal_checkpoint", "usage", "entries"}
ENTRY_KEYS = {"memory_item_id", "head_version", "lifecycle_status", "deletion_epoch", "content_ref",
              "content_digest", "stage_digest", "item_digests", "audit_refs", "representations"}
POINT = "urn:ocor:recovery-point:" + "d" * 64


class Checkpoints:
    """Trusted deletion-checkpoint port fixture (journal-backed or fixed)."""

    def __init__(self, path: Path | None = None, *, fixed: Any = None) -> None:
        self.path, self.fixed, self.fail, self.calls, self.after = path, fixed, False, 0, None

    def current(self) -> Any:
        from ocor_runtime.memory.deletion import GENESIS, DeletionJournalCheckpoint, DeletionJournalSnapshot
        self.calls += 1
        if self.fail:
            raise ConnectionError("deletion authority unavailable")
        if self.after is not None and self.calls > 1:
            return self.after
        if self.fixed is not None:
            return self.fixed
        if self.path is None:
            return DeletionJournalCheckpoint(0, GENESIS, 0)
        return DeletionJournalSnapshot.capture(self.path).checkpoint


class Signer:
    """HMAC unit signer; live cases use the OpenBao transit attestation of 0056."""

    def __init__(self) -> None:
        self.fail, self.answer, self.signed = False, None, 0

    def sign(self, payload: bytes) -> str:
        import hmac
        if self.fail:
            raise ConnectionError("signer unavailable")
        self.signed += 1
        return "hmac:" + hmac.new(b"k" * 32, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> Any:
        import hmac
        if self.answer is not None:
            return self.answer
        return hmac.compare_digest(signature, "hmac:" + hmac.new(b"k" * 32, payload, hashlib.sha256).hexdigest())


def backup_service(s: MemoryOperationsService, checkpoints: Any = None, signer: Any = None) -> Any:
    from ocor_runtime.memory.operations import MemoryBackupService
    return MemoryBackupService(operations=s, checkpoints=checkpoints or Checkpoints(), signer=signer or Signer())


def capture(b: Any, w: Any, p: MemoryPartition, point: str = POINT) -> Any:
    return b.capture(request(w, p), binding=r.binding(r.context()), recovery_point_id=point)


def test_backup_manifest_is_complete_canonical_and_signed() -> None:
    from ocor_runtime.kernel.canonical import canonical_bytes, parse_i_json
    w = life.unit_world()
    p = seed(w)
    w.admit("b-del", life.TEXT + " gone")
    w.delete("b-del", op="forget-b")
    s, audit, _ = setup(w)
    signer = Signer()
    backup = capture(backup_service(s, signer=signer), w, p)
    body = parse_i_json(backup.payload)
    assert canonical_bytes(body) == backup.payload and signer.verify(backup.payload, backup.signature) is True
    assert set(body) == MANIFEST_KEYS and body["recovery_point_id"] == POINT
    assert body["partition_digest"] == p.digest and body["governed_context_digest"] == r.context().digest()
    assert body["journal_checkpoint"] == {"sequence": 0, "head": "urn:sha256:" + "0" * 64, "deletion_epoch": 0}
    entries = {e["memory_item_id"]: e for e in body["entries"]}
    assert sorted(entries) == ["a-old", "b-del"] and all(set(e) == ENTRY_KEYS for e in entries.values())
    live = entries["a-old"]
    record = w.ledger.get("a-old", 1)
    stored = w.metadata.get("a-old", 1)
    assert (live["head_version"], live["lifecycle_status"], live["deletion_epoch"]) == (1, "ACTIVE", None)
    assert live["content_ref"] == stored.staged.content_object_ref and live["content_digest"] == record.item.content_digest
    assert live["item_digests"] == [record.item_digest] and live["audit_refs"] == [stored.staged.audit_ref]
    assert live["stage_digest"] == stored.staged.stage_digest
    assert [x["representation_digest"] for x in live["representations"]] == [
        ptr.representation_digest for ptr in stored.staged.pointers]
    gone = entries["b-del"]
    assert gone["lifecycle_status"] == "DELETED" and isinstance(gone["deletion_epoch"], int) and gone["deletion_epoch"] >= 1
    # The tombstone version keeps only its metadata pointer, stamped with the deletion epoch.
    assert [(x["representation_kind"], x["deletion_epoch"]) for x in gone["representations"]] == [
        ("STRUCTURED", gone["deletion_epoch"])]
    assert len(gone["item_digests"]) == gone["head_version"] == len(gone["audit_refs"])
    assert body["usage"] == {"items": 1, "held_items": 0, "incomplete_deletions": 0, "index_entries": 3, "tombstones": 1}
    assert life.TEXT not in backup.payload.decode()  # metadata and refs only, never content
    assert [e["action"] for e in audit.events][-2:] == ["memoryBackup.started", "memoryBackup.completed"]


def test_backup_is_deterministic_for_an_unchanged_partition() -> None:
    w = life.unit_world()
    p = seed(w)
    s, _, _ = setup(w)
    b = backup_service(s)
    assert capture(b, w, p).payload == capture(b, w, p).payload


@pytest.mark.parametrize("fault,detail", [
    ("binding", "BINDING_MISSING"), ("policy", "OPERATIONS_DENIED"), ("checkpoint", "CHECKPOINT_UNAVAILABLE"),
    ("checkpoint-changed", "CHECKPOINT_CHANGED"), ("signer", "SIGNER_UNAVAILABLE"),
    ("point", "RECOVERY_POINT_INVALID"), ("audit", "AUDIT_UNAVAILABLE"),
    ("checkpoint-type", "CHECKPOINT_UNAVAILABLE"), ("signature-empty", "SIGNER_UNAVAILABLE"),
])
def test_backup_capture_fails_closed_without_a_manifest(fault: str, detail: str) -> None:
    from ocor_runtime.memory.deletion import DeletionJournalCheckpoint
    w = life.unit_world()
    p = seed(w)
    s, audit, policy = setup(w)
    checkpoints, signer = Checkpoints(), Signer()
    b = backup_service(s, checkpoints, signer)
    binding: Any = r.binding(r.context())
    point = POINT
    if fault == "binding":
        binding = None
    elif fault == "policy":
        policy.allow = False
    elif fault == "checkpoint":
        checkpoints.fail = True
    elif fault == "checkpoint-changed":
        checkpoints.after = DeletionJournalCheckpoint(1, r.d("journal-head"), 1)
    elif fault == "signer":
        signer.fail = True
    elif fault == "point":
        point = "urn:ocor:recovery-point:not-a-digest"
    elif fault == "checkpoint-type":
        checkpoints.fixed = {"sequence": 0}
    elif fault == "signature-empty":
        signer.sign = lambda payload: ""  # type: ignore[method-assign]
    else:
        audit.fail = True
    refused(lambda: b.capture(request(w, p), binding=binding, recovery_point_id=point), detail)
    if fault in {"binding", "policy", "point"}:
        assert checkpoints.calls == 0
    if fault != "audit":
        assert signer.signed == 0 or fault == "signer"
        assert audit.events[-1]["outcome"] == "DENIED"


def test_backup_never_captures_another_partition() -> None:
    w = life.unit_world()
    p = seed(w)
    s, _, policy = setup(w)
    checkpoints = Checkpoints()
    other = dataclasses.replace(p, compartments=("bravo",))
    refused(lambda: capture(backup_service(s, checkpoints), w, other), "PARTITION_DENIED")
    assert policy.calls == [] and checkpoints.calls == 0


@pytest.mark.parametrize("tamper", ["extra-key", "non-canonical", "schema", "entry-key", "not-json"])
def test_restore_refuses_an_invalid_manifest_even_if_signed(tamper: str, tmp_path: Path) -> None:
    import json

    from ocor_runtime.kernel.canonical import canonical_bytes, parse_i_json
    from ocor_runtime.memory.operations import MemoryRestoreGate
    w = life.unit_world()
    p = seed(w)
    s, _, _ = setup(w)
    signer = Signer()
    backup = capture(backup_service(s, signer=signer), w, p)
    body = parse_i_json(backup.payload)
    if tamper == "extra-key":
        payload = canonical_bytes({**body, "note": "x"})
    elif tamper == "non-canonical":
        payload = json.dumps(body, indent=1).encode()
    elif tamper == "schema":
        payload = canonical_bytes({**body, "schema": "urn:ocor:schema:other:v1"})
    elif tamper == "entry-key":
        payload = canonical_bytes({**body, "entries": [{**body["entries"][0], "extra": 1}]})
    else:
        payload = b"\xff not json"
    gate, _, participant, _ = unit_gate(tmp_path)
    audit = receipts.ReceiptAudit()
    restore = MemoryRestoreGate(recovery_point_id=POINT, verifier=signer, gate=gate, checkpoints=Checkpoints(),
                                journal=tmp_path / "restored.jsonl", metadata=w.metadata, ledger=w.ledger, audit=audit)
    refused(lambda: restore.open(payload, signer.sign(payload)), "BACKUP_MANIFEST_INVALID")
    assert participant.calls == [] and audit.events[-1]["outcome"] == "DENIED"


def unit_gate(tmp_path: Path) -> Any:
    import test_ocor_dev_0056 as t56
    return t56.gate_world(tmp_path)


@pytest.mark.parametrize("answer", [False, None, 1, "true"])  # None: real HMAC check of a wrong signature
def test_restore_requires_an_exact_true_signature_verification(answer: Any, tmp_path: Path) -> None:
    from ocor_runtime.memory.operations import MemoryRestoreGate
    w = life.unit_world()
    p = seed(w)
    s, _, _ = setup(w)
    signer = Signer()
    backup = capture(backup_service(s, signer=signer), w, p)
    gate, _, participant, _ = unit_gate(tmp_path)
    restore = MemoryRestoreGate(recovery_point_id=POINT, verifier=signer, gate=gate, checkpoints=Checkpoints(),
                                journal=tmp_path / "restored.jsonl", metadata=w.metadata, ledger=w.ledger,
                                audit=receipts.ReceiptAudit())
    signer.answer = answer
    signature = "hmac:" + "0" * 64 if answer is None else backup.signature
    refused(lambda: restore.open(backup.payload, signature), "BACKUP_UNAUTHENTICATED")
    assert participant.calls == []
    refused(lambda: restore.serve(lambda: "materialised"), "RESTORE_NOT_OPEN")


def test_restore_components_require_exact_port_types(tmp_path: Path) -> None:
    from ocor_runtime.memory.operations import MemoryRestoreGate
    w = life.unit_world()
    with pytest.raises(ValueError):
        MemoryRestoreGate(recovery_point_id=POINT, verifier=Signer(), gate=object(), checkpoints=Checkpoints(),  # type: ignore[arg-type]
                          journal=tmp_path / "j", metadata=w.metadata, ledger=w.ledger, audit=receipts.ReceiptAudit())
    gate, *_ = unit_gate(tmp_path)
    with pytest.raises(ValueError):
        MemoryRestoreGate(recovery_point_id="urn:ocor:recovery-point:x", verifier=Signer(), gate=gate,
                          checkpoints=Checkpoints(), journal=tmp_path / "j", metadata=w.metadata, ledger=w.ledger,
                          audit=receipts.ReceiptAudit())


def unit_restore(w: Any, tmp_path: Path, signer: Signer, *, checkpoints: Any = None, metadata: Any = None,
                 audit: Any = None) -> tuple[Any, Any, Any]:
    from ocor_runtime.memory.operations import MemoryRestoreGate
    gate, _, participant, journal_path = unit_gate(tmp_path)
    audit = audit if audit is not None else receipts.ReceiptAudit()
    restore = MemoryRestoreGate(recovery_point_id=POINT, verifier=signer, gate=gate,
                                checkpoints=checkpoints or Checkpoints(), journal=journal_path,
                                metadata=metadata or w.metadata, ledger=w.ledger, audit=audit)
    return restore, participant, audit


def resigned(backup: Any, signer: Signer, change: Any) -> tuple[bytes, str]:
    from ocor_runtime.kernel.canonical import canonical_bytes, parse_i_json
    body = parse_i_json(backup.payload)
    change(body)
    payload = canonical_bytes(body)
    return payload, signer.sign(payload)


def test_unit_restore_opens_and_serves_an_unchanged_copy(tmp_path: Path) -> None:
    w = life.unit_world()
    p = seed(w)
    s, _, _ = setup(w)
    signer = Signer()
    backup = capture(backup_service(s, signer=signer), w, p)
    restore, participant, audit = unit_restore(w, tmp_path, signer)
    receipt = restore.open(backup.payload, backup.signature)
    assert participant.calls == ["x", "y"]  # every journal obligation replayed before the comparison
    assert receipt.verified_items == 1 and receipt.deleted_after_backup == () and receipt.manifest_digest == backup.manifest_digest
    assert restore.serve(lambda: "materialised") == "materialised"
    assert [e["action"] for e in audit.events][-2:] == ["memoryRestore.opened", "memoryRestore.served"]


@pytest.mark.parametrize("fault,detail", [
    ("verifier-outage", "BACKUP_UNAUTHENTICATED"), ("checkpoint-outage", "CHECKPOINT_UNAVAILABLE"),
    ("checkpoint-type", "CHECKPOINT_UNAVAILABLE"), ("checkpoint-forked", "STALE_DELETION_EPOCH"),
    ("audit", "AUDIT_UNAVAILABLE"), ("inventory", "RESTORE_INVENTORY_UNAVAILABLE"),
])
def test_unit_restore_faults_keep_materialisation_closed(fault: str, detail: str, tmp_path: Path) -> None:
    from ocor_runtime.memory.deletion import DeletionJournalCheckpoint
    w = life.unit_world()
    p = seed(w)
    s, _, _ = setup(w)
    signer = Signer()
    backup = capture(backup_service(s, signer=signer), w, p)
    checkpoints, metadata, audit = Checkpoints(), None, receipts.ReceiptAudit()
    if fault == "verifier-outage":
        def outage(payload: bytes, signature: str) -> bool:
            raise ConnectionError("custodian unavailable")
        signer.verify = outage  # type: ignore[method-assign]
    elif fault == "checkpoint-outage":
        checkpoints.fail = True
    elif fault == "checkpoint-type":
        checkpoints.fixed = object()
    elif fault == "checkpoint-forked":
        # Same sequence, another head: the authority's history is not the one of the backup.
        backup = capture(backup_service(s, Checkpoints(fixed=DeletionJournalCheckpoint(1, r.d("a"), 1)), signer), w, p)
        checkpoints.fixed = DeletionJournalCheckpoint(1, r.d("b"), 1)
    elif fault == "audit":
        audit.fail = True
    else:
        class Broken:
            def __getattr__(self, name: str) -> Any:
                return getattr(w.metadata, name)

            def versions_in(self, partition_digest: str) -> Any:
                raise ConnectionError("restored metadata unreadable")
        metadata = Broken()
    restore, participant, audit = unit_restore(w, tmp_path, signer, checkpoints=checkpoints, metadata=metadata, audit=audit)
    refused(lambda: restore.open(backup.payload, backup.signature), detail)
    if fault in {"verifier-outage", "checkpoint-outage", "checkpoint-type", "checkpoint-forked"}:
        assert participant.calls == []  # refused before any purge
    if fault != "audit":
        assert audit.events[-1]["detail_code"] == detail and audit.events[-1]["outcome"] == "DENIED"
    audit.fail = False
    refused(lambda: restore.serve(lambda: "materialised"), "RESTORE_NOT_OPEN")


def _add_entry(item: str, epoch: int | None) -> Any:
    def change(body: dict[str, Any]) -> None:
        body["entries"].append({**body["entries"][0], "memory_item_id": item, "deletion_epoch": epoch})
        body["entries"].sort(key=lambda e: e["memory_item_id"])
    return change


def _set(field: str, value: Any) -> Any:
    def change(body: dict[str, Any]) -> None:
        body["entries"][0][field] = value
    return change


@pytest.mark.parametrize("label,change,detail", [
    ("deleted-after-backup-without-replayed-tombstone", _add_entry("y", None), "STALE_DELETION_EPOCH"),
    ("manifest-epoch-newer-than-tombstone", _add_entry("x", 99), "STALE_DELETION_EPOCH"),
    ("item-epoch", _set("deletion_epoch", 5), "STALE_DELETION_EPOCH"),
    ("pointer-epoch", lambda b: b["entries"][0]["representations"][0].update(deletion_epoch=7), "STALE_DELETION_EPOCH"),
    ("stage", _set("stage_digest", "urn:sha256:" + "e" * 64), "PROJECTION_DRIFT"),
    ("version-digests", _set("item_digests", ["urn:sha256:" + "f" * 64]), "PROJECTION_DRIFT"),
    ("head", _set("head_version", 2), "PROJECTION_DRIFT"),
    ("missing-item", lambda b: b.update(entries=[]), "PROJECTION_DRIFT"),
])
def test_unit_restore_comparison_branches(label: str, change: Any, detail: str, tmp_path: Path) -> None:
    w = life.unit_world()
    p = seed(w)
    s, _, _ = setup(w)
    signer = Signer()
    payload, signature = resigned(capture(backup_service(s, signer=signer), w, p), signer, change)
    restore, participant, audit = unit_restore(w, tmp_path, signer)
    refused(lambda: restore.open(payload, signature), detail)
    assert participant.calls == ["x", "y"]  # compared only after the tombstone replay
    refused(lambda: restore.serve(lambda: "materialised"), "RESTORE_NOT_OPEN")


def test_unit_failed_materialisation_closes_the_restore(tmp_path: Path) -> None:
    w = life.unit_world()
    p = seed(w)
    s, _, _ = setup(w)
    signer = Signer()
    backup = capture(backup_service(s, signer=signer), w, p)
    restore, _, audit = unit_restore(w, tmp_path, signer)
    restore.open(backup.payload, backup.signature)

    def broken() -> str:
        raise RuntimeError("materialiser failure")
    refused(lambda: restore.serve(broken), "RESTORE_INVENTORY_UNAVAILABLE")
    assert audit.events[-1]["action"] == "memoryRestore.serve.denied"
    refused(lambda: restore.serve(lambda: "materialised"), "RESTORE_NOT_OPEN")


# ---- live restore drills (real PostgreSQL/Qdrant/OpenBao, 0056 backup copy) --------------------

def live_drill(backends: life.Backends, tmp_path: Path, *, hold: bool = False) -> Any:
    """The 0056 drill, optionally with a legal hold placed before the backup copy."""
    import test_ocor_dev_0056 as t56
    from ocor_runtime.memory.lifecycle import JournalTombstoneStore
    path = tmp_path / "authority.jsonl"
    source = backends.world(tombstones=JournalTombstoneStore(path))
    items = life.populate(source)
    if hold:
        source.holds.place()
        source.move("x", "LEGAL_HOLD", hold=life.HOLD, reason="LITIGATION_HOLD")
    source.rebuild(items["keep"])
    restored, point = t56.backup_and_restore(backends, source, items)
    attestation = t56.OpenBaoCheckpointAttestation(backends.bao)
    issuer = t56.AttestedJournal(path, attestation, point)
    return t56.Drill(source, restored, point, path, tmp_path / "restored.jsonl", attestation, issuer, items)


def live_capture(d: Any, backends: life.Backends, point: str | None = None) -> tuple[Any, Any, Any]:
    import test_ocor_dev_0056 as t56
    s, _, _ = setup(d.source, audit=receipts.PostgresReceiptAudit(backends.dsn, d.source.metadata.schema))
    signer = t56.OpenBaoCheckpointAttestation(backends.bao)
    b = backup_service(s, Checkpoints(d.authority_journal), signer)
    p = MemoryPartition.for_item(d.items["keep"].item)
    return capture(b, d.source, p, point or d.recovery_point), signer, p


def live_restore(d: Any, backends: life.Backends, signer: Any, checkpoints: Any = None, audit: Any = None) -> Any:
    from ocor_runtime.memory.operations import MemoryRestoreGate
    return MemoryRestoreGate(
        recovery_point_id=d.recovery_point, verifier=signer, gate=d.gate(),
        checkpoints=checkpoints or Checkpoints(d.authority_journal), journal=d.restored_journal,
        metadata=d.restored.metadata, ledger=d.restored.ledger,
        audit=audit or receipts.PostgresReceiptAudit(backends.dsn, d.restored.metadata.schema),
    )


def mentions(refs: dict[str, list[str]], item: str) -> bool:
    return any(ref.startswith(f"urn:ocor:memory:{item}:") for found in refs.values() for ref in found)


def test_live_restore_replays_tombstones_then_reopens_with_holds_and_epochs(
    backends: life.Backends, tmp_path: Path,
) -> None:
    from ocor_runtime.kernel.canonical import parse_i_json
    d = live_drill(backends, tmp_path)
    backup, signer, _ = live_capture(d, backends)
    body = parse_i_json(backup.payload)
    assert {e["memory_item_id"] for e in body["entries"]} == {"keep", "x", "y"}
    # A deletion after the backup must never be resurrected by the restore.
    assert d.source.delete("x", op="forget-x").lifecycle_status == "DELETED"
    d.deliver_journal()
    assert mentions(d.refs(), "x")  # the restored copy really still holds x
    audit = receipts.PostgresReceiptAudit(backends.dsn, d.restored.metadata.schema)
    restore = live_restore(d, backends, signer, audit=audit)
    refused(lambda: restore.serve(d.refs), "RESTORE_NOT_OPEN")
    receipt = restore.open(backup.payload, backup.signature)
    assert receipt.obligations == 1 and receipt.manifest_digest == "urn:sha256:" + hashlib.sha256(backup.payload).hexdigest()
    assert receipt.deleted_after_backup == ("x",) and receipt.verified_items == 2
    found = restore.serve(d.refs)
    assert not mentions(found, "x") and mentions(found, "keep") and mentions(found, "y")
    assert d.restored.status("x") == "DELETED"
    assert audit.actions()[-1] == "memoryRestore.served"


def test_live_restore_preserves_a_legal_hold_recorded_in_the_manifest(backends: life.Backends, tmp_path: Path) -> None:
    from ocor_runtime.kernel.canonical import parse_i_json
    d = live_drill(backends, tmp_path, hold=True)
    backup, signer, _ = live_capture(d, backends)
    restore = live_restore(d, backends, signer)
    d.deliver_journal()
    receipt = restore.open(backup.payload, backup.signature)
    assert receipt.obligations == 0 and receipt.deleted_after_backup == () and receipt.verified_items == 3
    entries = {e["memory_item_id"]: e for e in parse_i_json(backup.payload)["entries"]}
    assert {k: e["lifecycle_status"] for k, e in entries.items()} == {"keep": "ACTIVE", "x": "LEGAL_HOLD", "y": "ACTIVE"}
    assert entries["x"]["head_version"] == 2 and entries["x"]["representations"] != []
    assert d.restored.status("x") == "LEGAL_HOLD"
    found = restore.serve(d.refs)
    assert not mentions(found, "x") and mentions(found, "keep")  # held, preserved, never retrievable


@pytest.mark.parametrize("tamper", ["payload", "signature"])
def test_live_unauthenticated_backup_never_purges_or_reopens(backends: life.Backends, tmp_path: Path, tamper: str) -> None:
    d = live_drill(backends, tmp_path)
    backup, signer, _ = live_capture(d, backends)
    d.source.delete("x", op="forget-x")
    d.deliver_journal()
    payload = backup.payload.replace(b'"keep"', b'"kept"') if tamper == "payload" else backup.payload
    signature = backup.signature if tamper == "payload" else "vault:v1:" + "A" * 86
    restore = live_restore(d, backends, signer)
    refused(lambda: restore.open(payload, signature), "BACKUP_UNAUTHENTICATED")
    refused(lambda: restore.serve(d.refs), "RESTORE_NOT_OPEN")
    assert mentions(d.refs(), "x")  # nothing purged without an authenticated manifest


def test_live_manifest_of_another_recovery_point_is_refused(backends: life.Backends, tmp_path: Path) -> None:
    d = live_drill(backends, tmp_path)
    backup, signer, _ = live_capture(d, backends, point=POINT)
    d.deliver_journal()
    refused(lambda: live_restore(d, backends, signer).open(backup.payload, backup.signature), "RECOVERY_POINT_MISMATCH")


def test_live_stale_deletion_epoch_blocks_materialisation_before_any_purge(backends: life.Backends, tmp_path: Path) -> None:
    d = live_drill(backends, tmp_path)
    old_journal = tmp_path / "before-deletion.jsonl"
    old_journal.write_bytes(d.authority_journal.read_bytes())
    d.source.delete("y", op="forget-y")
    backup, signer, _ = live_capture(d, backends)  # the manifest records the newer deletion epoch
    d.deliver_journal()
    # The deletion authority answers with a checkpoint older than the backup: a journal rollback.
    restore = live_restore(d, backends, signer, checkpoints=Checkpoints(old_journal))
    refused(lambda: restore.open(backup.payload, backup.signature), "STALE_DELETION_EPOCH")
    assert mentions(d.refs(), "y")
    refused(lambda: restore.serve(d.refs), "RESTORE_NOT_OPEN")


@pytest.mark.parametrize("drift", ["newer-version", "extra-item"])
def test_live_projection_drift_blocks_materialisation(backends: life.Backends, tmp_path: Path, drift: str) -> None:
    d = live_drill(backends, tmp_path)
    if drift == "newer-version":
        # The source revokes y after the copy: the manifest is newer than the restored projection.
        d.source.move("y", "REVOKED")
    backup, signer, _ = live_capture(d, backends)
    if drift == "extra-item":
        d.restored.admit("extra", life.TEXT + " east")  # present in the restored stores, absent from the manifest
    d.deliver_journal()
    restore = live_restore(d, backends, signer)
    refused(lambda: restore.open(backup.payload, backup.signature), "PROJECTION_DRIFT")
    refused(lambda: restore.serve(d.refs), "RESTORE_NOT_OPEN")


def test_live_drift_after_reopening_discards_the_response_and_closes(backends: life.Backends, tmp_path: Path) -> None:
    d = live_drill(backends, tmp_path)
    backup, signer, _ = live_capture(d, backends)
    d.deliver_journal()
    restore = live_restore(d, backends, signer)
    restore.open(backup.payload, backup.signature)
    served: list[str] = []

    def materialise() -> Any:
        d.restored.admit("late", life.TEXT + " west")
        served.append("called")
        return d.restored.every_mode()  # the late item has no parallel v2 descriptor yet
    refused(lambda: restore.serve(materialise), "PROJECTION_DRIFT")
    assert served == ["called"]
    refused(lambda: restore.serve(d.refs), "RESTORE_NOT_OPEN")


def test_live_missing_journal_keeps_restore_closed(backends: life.Backends, tmp_path: Path) -> None:
    from ocor_runtime.memory.deletion import DeletionRecoveryError
    d = live_drill(backends, tmp_path)
    backup, signer, _ = live_capture(d, backends)
    restore = live_restore(d, backends, signer)  # journal never delivered to the restore site
    with pytest.raises(DeletionRecoveryError):
        restore.open(backup.payload, backup.signature)
    refused(lambda: restore.serve(d.refs), "RESTORE_NOT_OPEN")


# Repair1 (Codex/OpenAI): stop authority at restore and complete partition inventory.
@pytest.mark.parametrize("phase", ["before-serve", "during-materialise", "during-reconcile", "during-open-verify"])
def test_unit_restore_stop_epoch_race_closes_without_a_response(phase: str, tmp_path: Path) -> None:
    w = life.unit_world()
    p = seed(w)
    s, _, _ = setup(w)
    signer = Signer()
    backup = capture(backup_service(s, signer=signer), w, p)
    restore, participant, audit = unit_restore(w, tmp_path, signer)
    if phase == "during-reconcile":
        original = participant.purge
        def purge(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            w.lc_stop.epoch += 1
            return result
        participant.purge = purge
    if phase == "during-open-verify":
        original_verify = signer.verify
        def verify(*args: Any) -> Any:
            w.lc_stop.epoch += 1
            return original_verify(*args)
        signer.verify = verify
    if phase.startswith("during-") and phase != "during-materialise":
        refused(lambda: restore.open(backup.payload, backup.signature), "STOP_EPOCH_MISMATCH")
    else:
        restore.open(backup.payload, backup.signature)
        if phase == "before-serve":
            w.lc_stop.epoch += 1
        def materialise() -> str:
            if phase == "during-materialise":
                w.lc_stop.epoch += 1
            return "must-not-escape"
        refused(lambda: restore.serve(materialise), "STOP_EPOCH_MISMATCH")
    assert audit.events[-1]["outcome"] == "DENIED"
    assert not any(e["action"] == "memoryRestore.served" for e in audit.events)
    refused(lambda: restore.serve(lambda: pytest.fail("closed restore called materialisation")), "RESTORE_NOT_OPEN")


@pytest.mark.parametrize("phase", ["open", "serve"])
@pytest.mark.parametrize("fault,detail", [(None, "STOP_STATE_INVALID"), (True, "STOP_STATE_INVALID"),
    (-1, "STOP_STATE_INVALID"), ("0", "STOP_STATE_INVALID"), ("outage", "STOP_UNAVAILABLE")])
def test_unit_restore_stop_authority_is_mandatory(phase: str, fault: Any, detail: str, tmp_path: Path) -> None:
    w = life.unit_world()
    p = seed(w)
    s, _, _ = setup(w)
    signer = Signer()
    backup = capture(backup_service(s, signer=signer), w, p)
    restore, _, audit = unit_restore(w, tmp_path, signer)
    if phase == "serve":
        restore.open(backup.payload, backup.signature)
    if fault == "outage":
        w.lc_stop.fail = True
    else:
        w.lc_stop.epoch = fault
    refused(lambda: restore.open(backup.payload, backup.signature) if phase == "open" else restore.serve(
        lambda: pytest.fail("invalid stop state materialised")), detail)
    assert audit.events[-1]["outcome"] == "DENIED"
    refused(lambda: restore.serve(lambda: "closed"), "RESTORE_NOT_OPEN")


def inventory_call(s: Any, w: Any, p: MemoryPartition, operation: str, signer: Any) -> Any:
    if operation == "capture":
        return capture(backup_service(s, signer=signer), w, p)
    if operation == "quota":
        return invoke(s, w, p, "check_quota", demand=MemoryQuotaDemand(new_items=1))
    return invoke(s, w, p)


def inventory_race(w: Any, operation: str, audit: Any, monkeypatch: Any) -> None:
    p = seed(w)
    s, _, _ = setup(w, audit=audit)
    original = w.metadata.versions_in
    calls = 0
    def versions_in(partition_digest: str) -> Any:
        nonlocal calls
        snapshot = original(partition_digest)
        calls += 1
        if calls == 1:
            w.admit("racing-new-item", life.TEXT + " late committed")
        return snapshot
    monkeypatch.setattr(w.metadata, "versions_in", versions_in)
    signer = Signer()
    refused(lambda: inventory_call(s, w, p, operation, signer), "CANDIDATE_CHANGED")
    assert audit.events[-1]["outcome"] == "DENIED"
    assert not any(e["outcome"] == "COMPLETED" for e in audit.events)
    assert signer.signed == 0
    # A stable complete inventory must still work (and count the new head).
    monkeypatch.setattr(w.metadata, "versions_in", original)
    result = inventory_call(s, w, p, operation, signer)
    if operation == "monitor":
        assert result.items == 2
    elif operation == "quota":
        assert result.usage.items == 2 and not result.permitted
    else:
        from ocor_runtime.kernel.canonical import parse_i_json
        assert len(parse_i_json(result.payload)["entries"]) == 2 and signer.signed == 1


@pytest.mark.parametrize("operation", ["monitor", "quota", "capture"])
def test_unit_inventory_membership_race_never_completes(operation: str, monkeypatch: Any) -> None:
    inventory_race(life.unit_world(), operation, receipts.ReceiptAudit(), monkeypatch)


@pytest.mark.parametrize("operation", ["monitor", "quota", "capture"])
def test_live_inventory_membership_race_never_completes(
    backends: life.Backends, operation: str, monkeypatch: Any,
) -> None:
    w = backends.world()
    inventory_race(w, operation, receipts.PostgresReceiptAudit(backends.dsn, w.metadata.schema), monkeypatch)


@pytest.mark.parametrize("phase", ["before-serve", "during-materialise", "outage", "invalid", "unchanged"])
def test_live_restore_rechecks_stop_around_materialisation(
    backends: life.Backends, tmp_path: Path, phase: str,
) -> None:
    d = live_drill(backends, tmp_path)
    backup, signer, _ = live_capture(d, backends)
    audit = receipts.PostgresReceiptAudit(backends.dsn, d.restored.metadata.schema)
    restore = live_restore(d, backends, signer, audit=audit)
    restore.open(backup.payload, backup.signature)
    if phase == "before-serve":
        d.restored.lc_stop.epoch += 1
    elif phase == "outage":
        d.restored.lc_stop.fail = True
    elif phase == "invalid":
        d.restored.lc_stop.epoch = None
    def materialise() -> Any:
        result = d.refs()
        if phase == "during-materialise":
            d.restored.lc_stop.epoch += 1
        return result
    if phase == "unchanged":
        assert mentions(restore.serve(materialise), "x")
        assert audit.events[-1]["action"] == "memoryRestore.served"
    else:
        detail = {"outage": "STOP_UNAVAILABLE", "invalid": "STOP_STATE_INVALID"}.get(phase, "STOP_EPOCH_MISMATCH")
        refused(lambda: restore.serve(materialise), detail)
        assert audit.events[-1]["outcome"] == "DENIED"
        assert not any(e["action"] == "memoryRestore.served" for e in audit.events)
        refused(lambda: restore.serve(d.refs), "RESTORE_NOT_OPEN")
