"""0059 checkpoint: partition-bound operations, quota and deterministic pressure.

ADD v1.3 II 2.6/2.10/2.13, LLD 2.8.6 and 7.2 FGM-19 oracles.
Unit ports exercise boundary branches. Live cases reuse the actual 0055
admission/lifecycle/store stack (PostgreSQL, Qdrant, OpenBao); fixture policy
and hold authorities are explicitly test ports, not end-to-end security proof.
Backup/restore integration and final task qualification are pending at this checkpoint.
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


@pytest.mark.parametrize("tamper", ["scope", "gcs", "demand", "payload", "vector", "retention"])
def test_quota_writer_cannot_bypass_binding_or_actual_demand(tamper: str) -> None:
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
    else:
        body["candidate"]["retention_policy_ref"] = "unknown"
    before = life.ledger_snapshot(w)
    with pytest.raises(MemoryOperationsError):
        wr.admit_and_commit(body, binding=r.binding(r.context()), payload=payload, embedding=embedding)
    assert life.ledger_snapshot(w) == before and w.metadata.head("new") == 0
    assert audit.events[-1]["outcome"] == "DENIED"
    if tamper in {"scope", "gcs", "demand"}:
        assert lock.partitions == []


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
