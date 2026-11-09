"""OCOR-DEV-REM-0059 (NCP-U11): governed memory conformance.

Unit NCP-U11 of NORMATIVE-CONFORMANCE-PLAN (2026-10-30) resolves the register
entries NCR-MEMORY-001..005 of ``reports/development/NORMATIVE_CONFORMANCE_REGISTER.json``:

* NCR-MEMORY-001 -- retrieval whose result, scores, work and error are
  independent of policy-denied items: the pre-query policy produces the
  authorised partition down to the item (LLD v1.1 §2.8.3, ``docs/OCOR_LLD_v1.1.md``
  :214), so unauthorised elements never influence content, existence, count,
  rank, score, cache or error (FR-119, Register v1.1 :268; FGM-16, LLD v1.1 :397).
* NCR-MEMORY-002 -- ``admitMemory`` verifies quota before its atomic write
  (LLD v1.1 §2.8.2 :206): the admission service consults the partition quota
  authority of the operations port, under the partition serialization, before
  the single ledger append; a refusal appends nothing and is audited.  The
  consolidation service admits its derived items through the same admission,
  so consolidation output is counted against quota at admission (FGM-19
  quota/retention pressure, LLD v1.1 :400).
* NCR-MEMORY-004 -- the contract operation ``getMemoryItemVersion`` (Governed
  Memory API 1.0.0, ``ocor-governed-memory.openapi.yaml`` :21-29, a materialised
  contract by LLD v1.1 §0.2 :26) is a governed service operation of the
  ``MemoryReadPort`` (ADD v1.3 Part II §2.2 :3761): it binds the authenticated
  GovernedContext and recalculates its digest (§2.5 :3789), evaluates policy,
  marking and lifecycle, and audits the read; an unauthorised item is
  indistinguishable from an absent one (FR-119).
* NCR-MEMORY-003 -- ``requestMemoryDeletion`` executes the four declared
  ``deletion_scope`` values of the contract (``ocor-governed-memory.openapi.yaml``
  :273; UNSUPPORTED_CAPABILITY only for undeclared combinations, LLD v1.1 :421)
  through the deletion saga (ADD v1.3 Part II §2.10 :3836; FR-118 Register v1.1
  :267): ``ALL_VERSIONS`` forgets the item with every version; ``LATEST_VERSION``
  forgets the item and purges its head version only, keeping the earlier
  versions as unreachable history (no resurrection: the item stays
  ``DELETED``); ``PROJECT_SCOPE`` and ``PRINCIPAL_SCOPE`` forget, with every
  version, each item visible to the caller that shares the addressed item's
  ``project_id`` or owner principal, with one saga, tombstone and audit event
  per item and one receipt for the request.
* NCR-MEMORY-005 -- committed full-text and vector projections are rebuildable
  projections (ADD v1.3 Part II §2.2 :3763 and storage table :3797-3799; LLD
  v1.1 §2.8.1 :202): ``MemoryStoreCoordinator.rebuild_projections`` rebuilds a
  lost or drifted projection of one committed version from its metadata record,
  its verified content and the admission journal (the embedding is accepted
  only as the exact one the item digests), and ``rebuild_partition`` does so
  for every committed version of a partition.  A rebuilt superseded version
  stays retired and a deleted item is never resurrected.

Each ``test_ncr_memory_<nnn>_conforms`` was written first and run RED on the
unremediated code (``origin/main`` ``f683aa7``), then GREEN.  Qualifying cases
run on the real pinned backends of OCOR-DEV-0051 through the worlds of
OCOR-DEV-0052: PostgreSQL 16 (``OCOR_LIVE_POSTGRES_DSN``: metadata, encrypted
content objects, full-text index), Qdrant 1.15.1 (vector index) and OpenBao
2.6.2 transit.  A missing backend fails, it never skips.  Only the policy,
stop-state and audit ports are test ports (as in OCOR-DEV-0052).

The SELF-CHECK-CHECKLIST (2026-11-08) section at the end holds one negative
case per parsing, adapter and port-answer path of the touched classes; those
cases are backend-free (unit worlds of OCOR-DEV-0050/0051/0052/0055/0059 and
scripted backend answers) and prove typed refusals, never qualify an entry
on their own.
"""

from __future__ import annotations

import contextlib
import dataclasses
import importlib
import json
import urllib.error
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
import test_ocor_dev_0050 as t50
import test_ocor_dev_0051 as t51
import test_ocor_dev_0052 as t52
import test_ocor_dev_0054 as t54
import test_ocor_dev_0055 as t55
import test_ocor_dev_0059 as t59
import test_ocor_dev_rem_0020 as r20
from ocor_runtime.kernel.governed_context import GovernedContext
from ocor_runtime.memory import adapters as A
from ocor_runtime.memory import lifecycle as L
from ocor_runtime.memory.model import AdmissionLimits, MemoryAdmissionError, MemoryAdmissionService
from ocor_runtime.memory.retrieval import MemoryRetrievalError, RetrievalAuthorization, RetrievalMode
from ocor_runtime.memory.stores import (
    EligibilityPredicate,
    IndexHit,
    MemoryPartition,
    SealedContent,
    VectorProfile,
    index_attributes,
)

# The live worlds of OCOR-DEV-0052: real PostgreSQL, Qdrant and OpenBao.
live_backends = t52.live_backends
backends = t52.backends

TEXT = "ration convoy schedule"
DENIED = 130


def _observe(world: t52.World, mode: RetrievalMode) -> dict[str, Any]:
    """Everything a caller or an observer of the index can see of one search."""

    try:
        response = r20.search(world, mode, text=TEXT)
    except MemoryRetrievalError as exc:
        outcome: Any = (exc.reason_code, exc.detail_code)
        explanations: Any = None
    else:
        outcome = [hit.to_mapping() for hit in response.hits]
        explanations = [dict(response.explanations[ref]) for ref in sorted(response.explanations)]
    return {
        "outcome": outcome,
        "explanations": explanations,
        "lookups": [(op, version) for op, _partition, version in r20.lookups(world)],
    }


@pytest.mark.parametrize("mode", [RetrievalMode.FULL_TEXT, RetrievalMode.VECTOR, RetrievalMode.HYBRID])
def test_ncr_memory_001_conforms(backends: t52.Backends, mode: RetrievalMode) -> None:
    """NCR-MEMORY-001: policy-denied items inside an authorised partition influence nothing.

    FR-119 (Register v1.1 :268): unauthorised elements must not influence
    content, existence, count, rank, score, cache or error.  LLD v1.1 §2.8.3
    (:214): the pre-query policy produces an authorised partition; unauthorised
    items do not influence score normalisation, rank, count, pagination, error
    or timing bucket.  FGM-16 (LLD v1.1 :397).  The same search over the same
    allowed item, without and with 130 policy-denied items matching the query
    in the same partition, returns identical hits, factors and explanations
    after the same ordered index lookups (the timing bucket is observed as the
    index work, not as a wall-clock measurement).
    """

    observed = {}
    for denied in (0, DENIED):
        world = backends.world()
        world.admit("allowed", TEXT)
        for n in range(denied):
            world.admit(f"denied-{n:03d}", TEXT)
            world.policy.denied_items.add(f"denied-{n:03d}")
        observed[denied] = _observe(world, mode)
    assert observed[0]["outcome"] != [], observed[0]
    assert isinstance(observed[0]["outcome"], list) and [h["memory_item_id"] for h in observed[0]["outcome"]] == ["allowed"]
    assert observed[DENIED] == observed[0]


# --------------------------------------------------------------------------
# NCR-MEMORY-004: getMemoryItemVersion
# --------------------------------------------------------------------------


class ReadGrantPolicy(t52.GrantPolicy):
    """The OCOR-DEV-0052 grant policy, also deciding exact-version reads."""

    def authorize_read(self, memory_item_id: str, memory_version: int, ctx: GovernedContext) -> RetrievalAuthorization:
        self.calls.append(f"read:{memory_item_id}:{memory_version}")
        if self.fail:
            raise ConnectionError("opa unavailable")
        return RetrievalAuthorization(
            permitted=self.permitted,
            decision_ref=f"decision:read:{memory_item_id}:{memory_version}",
            policy_bundle_digest=self.bundle or ctx.policy_bundle_digest,
            memory_kinds=self.kinds,
            memory_scopes=self.scopes,
            scope_bindings=dict(self.scope_bindings),
            domains=self.domains,
            denied_memory_item_ids=frozenset(self.denied_items),
        )


def _reader(world: t52.World) -> Any:
    retrieval = importlib.import_module("ocor_runtime.memory.retrieval")
    return retrieval.MemoryItemReadService(
        coordinator=world.coordinator, metadata=world.metadata, policy=world.policy, markings=world.markings,
        stop=world.stop, audit=world.audit, clock=world.clock,
    )


def _read_refused(world: t52.World, item_id: Any, version: Any, binding: Any) -> tuple[str, str]:
    with pytest.raises(MemoryAdmissionError) as caught:
        _reader(world).get_item_version(item_id, version, binding=binding)
    return caught.value.reason_code, caught.value.detail_code


def test_ncr_memory_004_conforms(backends: t52.Backends) -> None:
    """NCR-MEMORY-004: ``getMemoryItemVersion`` is a governed, policy-filtered, audited read.

    Governed Memory API 1.0.0 :21-29 (``getMemoryItemVersion``, response
    "Policy-filtered exact memory version"); LLD v1.1 §0.2 :26; ADD v1.3
    Part II §2.2 :3761 (``MemoryReadPort``) and §2.5 :3789 (the GCS digest is
    recalculated at retrieval); FR-119 (Register v1.1 :268): every retrieval
    is policy-filtered and unauthorised elements do not influence existence.
    """

    world = backends.world()
    world.policy = ReadGrantPolicy()
    first = world.admit("item", "harbour patrol schedule")
    second = world.admit("item", "harbour patrol schedule corrected", version=2)
    world.admit("secret", "harbour patrol schedule", ctx=t52.context(marking=t52.M_SECRET))
    world.admit("denied", "harbour patrol schedule")
    world.policy.denied_items.add("denied")
    caller = t52.binding()

    for record in (first, second):
        read = _reader(world).get_item_version("item", record.item.memory_version, binding=caller)
        assert read.item == record.item
        assert read.to_mapping() == record.item.to_mapping()
    events = [e for e in world.audit.events if e["action"] == "getMemoryItemVersion"]
    assert [e["memory_version_ref"] for e in events] == ["urn:ocor:memory:item:v1", "urn:ocor:memory:item:v2"]
    for event, record in zip(events, (first, second), strict=True):
        assert event["governed_context_digest"] == t52.CALLER.digest() == caller.expected.digest()
        assert event["binding_ref"] == caller.binding_ref
        assert event["item_digest"] == record.item.digest()
        assert event["audit_ref"]
    assert "read:item:1" in world.policy.calls and "materialize:urn:ocor:memory:item:v1" in world.policy.calls

    # An unauthorised item is indistinguishable from an absent one (existence is not leaked).
    absent = _read_refused(world, "absent", 1, caller)
    assert absent[0] == "MEMORY_NOT_FOUND"
    assert _read_refused(world, "denied", 1, caller) == absent
    assert _read_refused(world, "secret", 1, caller) == absent
    # A version beyond the visible item's history.
    assert _read_refused(world, "item", 3, caller)[0] == "MEMORY_VERSION_NOT_FOUND"

    # No authenticated binding, malformed path parameters, unknown stop state, no audit.
    assert _read_refused(world, "item", 1, None)[0] == "AUTHENTICATION_REQUIRED"
    for item_id, version in (("", 1), (7, 1), ("item", 0), ("item", True), ("item", "1"), ("item", 1.0)):
        assert _read_refused(world, item_id, version, caller)[0] == "MEMORY_SCHEMA_INVALID", (item_id, version)
    world.stop.fail = True
    assert _read_refused(world, "item", 1, caller)[0] == "CONTROL_PLANE_UNAVAILABLE"
    world.stop.fail = False
    world.policy.fail = True
    assert _read_refused(world, "item", 1, caller)[0] == "CONTROL_PLANE_UNAVAILABLE"
    world.policy.fail = False
    world.audit.fail = True
    assert _read_refused(world, "item", 1, caller)[0] == "CONTROL_PLANE_UNAVAILABLE"
    world.audit.fail = False

    # Lifecycle: a revoked head is no longer readable at any version.
    world.lifecycle(second, "REVOKED", "harbour patrol schedule corrected")
    assert _read_refused(world, "item", 1, caller) == absent
    assert _read_refused(world, "item", 2, caller) == absent

    # An expired item is not readable.
    world.admit("expiring", "harbour patrol schedule", expires_at=t52.NOW + timedelta(minutes=1))
    assert _reader(world).get_item_version("expiring", 1, binding=caller).item.memory_item_id == "expiring"
    world.clock.advance(timedelta(minutes=2))
    assert _read_refused(world, "expiring", 1, caller) == absent
    denied = [e for e in world.audit.events if e["action"] == "getMemoryItemVersion.denied"]
    assert {e["reason_code"] for e in denied} >= {"MEMORY_NOT_FOUND", "MEMORY_VERSION_NOT_FOUND", "MEMORY_SCHEMA_INVALID"}
    assert all(e["governed_context_digest"] == caller.expected.digest() for e in denied if e["reason_code"] == "MEMORY_NOT_FOUND")


# --------------------------------------------------------------------------
# NCR-MEMORY-003: the four declared deletion scopes
# --------------------------------------------------------------------------

@pytest.fixture
def lifecycle_backends(live_backends: t52.Backends) -> Iterator[t55.Backends]:
    """The OCOR-DEV-0055 lifecycle worlds over the module's live backends."""

    state = t55.Backends(dsn=live_backends.dsn, qdrant=live_backends.qdrant, bao=live_backends.bao)
    try:
        yield state
    finally:
        state.release()


def _deleted(world: t55.World, item_id: str) -> bool:
    head = world.lifecycle.head(item_id)
    return head is not None and head.item.lifecycle_status.value == "DELETED" and head.item.deletion_epoch is not None


def _served(world: t55.World, text: str) -> set[str]:
    return {ref.split(":")[3] for refs in world.every_mode(text).values() for ref in refs}


def test_ncr_memory_003_latest_version_forgets_only_the_head_version(lifecycle_backends: t55.Backends) -> None:
    """NCR-MEMORY-003, ``LATEST_VERSION`` (contract :273; ADD v1.3 :3836; FR-118 Register v1.1 :267)."""

    world = lifecycle_backends.world()
    first = world.admit("x", t55.TEXT + " north")
    second = world.admit("x", t55.TEXT + " north corrected", version=2)
    keep = world.admit("keep", t55.TEXT)
    receipt = world.delete("x", scope="LATEST_VERSION", op="forget-latest")
    assert receipt.to_mapping()["status"] == "COMPLETED" and receipt.lifecycle_status == "DELETED"
    assert receipt.tombstone_digest is not None and _deleted(world, "x")
    # The head version is purged everywhere; the earlier version stays as history only.
    assert not t55.content_present(world, second)
    assert t55.content_present(world, first) and t55.content_present(world, keep)
    tombstone = world.tombstones.entries("x")[-1]
    assert "urn:ocor:memory:x:v2" in tombstone.version_refs and "urn:ocor:memory:x:v1" not in tombstone.version_refs
    # No resurrection: the item is absent from every mode, the other item is served.
    assert "x" not in _served(world, "north") and "keep" in _served(world, t55.TEXT)
    # Replay returns the same receipt.
    assert world.delete("x", scope="LATEST_VERSION", op="forget-latest").to_mapping() == receipt.to_mapping()
    assert t55.denials(world) == []


@pytest.mark.parametrize("scope", ["PROJECT_SCOPE", "PRINCIPAL_SCOPE"])
def test_ncr_memory_003_bulk_scopes_forget_every_visible_item_of_the_scope(lifecycle_backends: t55.Backends, scope: str) -> None:
    """NCR-MEMORY-003, ``PROJECT_SCOPE`` and ``PRINCIPAL_SCOPE`` (contract :273; ADD v1.3 :3836; FR-118)."""

    world = lifecycle_backends.world()
    other_owner = t52.context(principal="agent-principal-2")
    if scope == "PROJECT_SCOPE":
        inside = [world.admit("a", t55.TEXT + " alpha"), world.admit("b", t55.TEXT + " bravo", ctx=other_owner)]
        outside = [world.admit("c", t55.TEXT + " charlie", bindings={"project_id": "project-2"})]
    else:
        inside = [world.admit("a", t55.TEXT + " alpha"), world.admit("b", t55.TEXT + " bravo", bindings={"project_id": "project-2"})]
        outside = [world.admit("c", t55.TEXT + " charlie", ctx=other_owner)]
    receipt = world.delete("a", scope=scope, op="forget-scope")
    assert receipt.to_mapping()["status"] == "COMPLETED" and receipt.lifecycle_status == "DELETED"
    for record in inside:
        assert _deleted(world, record.item.memory_item_id), record.item.memory_item_id
        assert not t55.content_present(world, record)
        assert [e.phase for e in world.tombstones.entries(record.item.memory_item_id)] == ["STARTED", "COMPLETED"]
    for record in outside:
        assert world.status(record.item.memory_item_id) == "ACTIVE"
        assert t55.content_present(world, record)
        assert world.tombstones.entries(record.item.memory_item_id) == ()
    # Nothing of the scope is served; the item outside it is served wherever the caller may search it
    # (the caller holds search Authority for project-1 only).
    assert _served(world, t55.TEXT) == ({"c"} if scope == "PRINCIPAL_SCOPE" else set())
    # Replay of the same request returns the same receipt and deletes nothing more.
    assert world.delete("a", scope=scope, op="forget-scope").to_mapping() == receipt.to_mapping()
    assert world.status("c") == "ACTIVE" and t55.denials(world) == []


# --------------------------------------------------------------------------
# NCR-MEMORY-002: quota at admitMemory and on consolidation
# --------------------------------------------------------------------------

QUOTA: dict[str, Any] = {
    "max_items": 10, "max_payload_bytes": 64, "max_embedding_dimensions": 8, "max_top_k": 10,
    "max_consolidation_concurrency": 2, "max_index_entries": 30,
    "retention_horizons": {"retention:standard": timedelta(days=365)},
}
RETENTION = {"retention:standard": timedelta(days=365)}


class BrokenSerialization:
    def hold(self, partition_digest: str) -> Any:
        raise OSError("serialization authority unavailable")


def _quota(world: Any, dsn: str, serialization: Any = None, **changes: Any) -> Any:
    """The partition quota authority of the operations port, over the world's real metadata store."""

    from ocor_runtime.memory.operations import MemoryAdmissionQuota, MemoryOperationsLimits

    return MemoryAdmissionQuota(
        metadata=world.metadata, ledger=world.ledger, limits=MemoryOperationsLimits(**{**QUOTA, **changes}),
        serialization=serialization if serialization is not None else t59.PostgresSerializedQuota(dsn, world.metadata.schema),
    )


def _quota_world(backends: t52.Backends, serialization: Any = None, **changes: Any) -> tuple[t52.World, t52.Audit]:
    world = backends.world()
    audit = t52.Audit()
    world.admission = MemoryAdmissionService(
        ledger=world.ledger, resolver=t52.Resolver(), policy=t52.base.Policy(), markings=world.markings,
        clock=world.clock, limits=AdmissionLimits(retention_horizons=RETENTION), audit=audit,
        quota=_quota(world, backends.dsn, serialization, **changes),
    )
    return world, audit


def _admission_refused(action: Any) -> tuple[str, str]:
    with pytest.raises(MemoryAdmissionError) as caught:
        action()
    return caught.value.reason_code, caught.value.detail_code


@pytest.mark.parametrize("changes,accepted,refusal", [
    ({"max_items": 2}, 2, ("POLICY_DENIED", "ITEM_QUOTA_EXCEEDED")),
    ({"max_index_entries": 7}, 2, ("POLICY_DENIED", "INDEX_QUOTA_EXCEEDED")),
    ({"max_payload_bytes": 8}, 0, ("POLICY_DENIED", "PAYLOAD_QUOTA_EXCEEDED")),
    ({"max_embedding_dimensions": 2}, 0, ("POLICY_DENIED", "EMBEDDING_QUOTA_EXCEEDED")),
    ({"retention_horizons": {"retention:other": timedelta(days=1)}}, 0, ("MEMORY_SCHEMA_INVALID", "RETENTION_UNCONFIGURED")),
])
def test_ncr_memory_002_admit_memory_verifies_quota_before_the_atomic_write(
    backends: t52.Backends, changes: dict[str, Any], accepted: int, refusal: tuple[str, str],
) -> None:
    """NCR-MEMORY-002: ``admitMemory`` verifies quota and writes atomically (LLD v1.1 §2.8.2 :206).

    The items admitted within quota are committed; the first one over quota is
    refused by the admission itself, appends no version, reaches no store and
    its refusal is audited.  A new version of an admitted item is not a new item.
    """

    world, audit = _quota_world(backends, **changes)
    for n in range(accepted):
        world.admit(f"item-{n}", f"{TEXT} {n}")
    assert _admission_refused(lambda: world.admit("over", f"{TEXT} over")) == refusal
    assert world.ledger.get("over", 1) is None and world.ledger.latest_version("over") == 0
    assert world.metadata.head("over") == 0
    assert [(e["reason_code"], e["detail_code"]) for e in audit.events] == [refusal]
    if accepted:
        corrected = world.admit("item-0", f"{TEXT} 0 corrected", version=2)
        assert corrected.item.memory_version == 2 and world.metadata.head("item-0") == 2


def test_ncr_memory_002_an_unavailable_quota_authority_refuses_and_writes_nothing(backends: t52.Backends) -> None:
    """NCR-MEMORY-002: no admission without the quota check (fail closed)."""

    world, audit = _quota_world(backends, BrokenSerialization())
    refusal = ("CONTROL_PLANE_UNAVAILABLE", "QUOTA_SERIALIZATION_UNAVAILABLE")
    assert _admission_refused(lambda: world.admit("a", TEXT)) == refusal
    assert world.ledger.get("a", 1) is None and world.metadata.head("a") == 0
    assert [(e["reason_code"], e["detail_code"]) for e in audit.events] == [refusal]


@pytest.fixture
def consolidation_backends(live_backends: t52.Backends) -> Iterator[t54.Backends]:
    """The OCOR-DEV-0054 consolidation worlds over the module's live backends."""

    state = t54.Backends(dsn=live_backends.dsn, qdrant=live_backends.qdrant, bao=live_backends.bao)
    try:
        yield state
    finally:
        state.release()


def _consolidation_world(backends: t54.Backends, **changes: Any) -> t54.CWorld:
    world = backends.world()
    world.admission = MemoryAdmissionService(
        ledger=world.ledger, resolver=world.references, policy=world.guard, audit=world.admission_audit,
        markings=world.markings, clock=world.clock, limits=AdmissionLimits(retention_horizons=RETENTION),
        quota=_quota(world, backends.dsn, **{"max_payload_bytes": 64 * 1024, **changes}),
    )
    return world


def _items(world: t54.CWorld, records: list[Any]) -> int:
    partition = MemoryPartition.for_item(records[0].item)
    return len({s.staged.memory_item_id for s in world.metadata.versions_in(partition.digest)})


def test_ncr_memory_002_consolidation_output_is_counted_against_quota_at_admission(
    consolidation_backends: t54.Backends,
) -> None:
    """NCR-MEMORY-002: consolidation admits its derived items through the quota-bearing admission.

    LLD v1.1 §2.8.2 (:206) and FGM-19 (:400): six convoy reports yield one
    dissent and one summary.  With room for six items the first derived item is
    refused at admission and the job writes no memory item; with room for eight
    the job completes and its two derived items count, so a further admission
    in the same partition is refused.
    """

    full = _consolidation_world(consolidation_backends, max_items=6)
    sources = t54.convoy_sources(full)
    refs = t54.refs_of(sources)
    request = t54.consolidation_request(refs)
    assert _admission_refused(
        lambda: full.consolidator().consolidate(request, binding=t52.binding(t54.CTX))
    ) == ("POLICY_DENIED", "ITEM_QUOTA_EXCEEDED")
    assert _items(full, sources) == 6
    assert [e["detail_code"] for e in t54.denials(full)] == ["ITEM_QUOTA_EXCEEDED"]

    room = _consolidation_world(consolidation_backends, max_items=8)
    sources = t54.convoy_sources(room)
    outcome = room.consolidator().consolidate(t54.consolidation_request(t54.refs_of(sources)), binding=t52.binding(t54.CTX))
    assert len(outcome.dissent_refs) == 1 and _items(room, sources) == 8
    assert _admission_refused(
        lambda: room.source("late", ("bridge-7", "sector", "north"))
    ) == ("POLICY_DENIED", "ITEM_QUOTA_EXCEEDED")


# --------------------------------------------------------------------------
# NCR-MEMORY-005: rebuild of committed full-text and vector projections
# --------------------------------------------------------------------------

NOT_VISIBLE = ("MEMORY_VERSION_NOT_FOUND", "VERSION_NOT_VISIBLE")


def _pointers(world: Any, item_id: str, version: int = 1) -> dict[str, Any]:
    stored = world.metadata.get(item_id, version)
    assert stored is not None
    return {p.representation_kind.value: p for p in stored.staged.pointers}


def _drop(world: Any, record: Any, *kinds: str) -> None:
    """Lose the native projections ``kinds`` of one version at the index backends."""

    partition = MemoryPartition.for_item(record.item)
    for kind, pointer in _pointers(world, record.item.memory_item_id, record.item.memory_version).items():
        if kind in kinds:
            index = world.lexical if kind == "FULL_TEXT" else world.vector
            index.inner.remove(partition, pointer.representation_version, pointer.store_ref)


def _store_refused(action: Any) -> tuple[str, str]:
    with pytest.raises(MemoryAdmissionError) as caught:
        action()
    return caught.value.reason_code, caught.value.detail_code


def _hits(world: t52.World, mode: RetrievalMode, text: str) -> list[str]:
    return list(t52.refs(r20.search(world, mode, text=text)))


def _embed(item: Any, payload: bytes) -> list[float]:
    return t52.embed(payload.decode())


def test_ncr_memory_005_a_lost_or_drifted_projection_is_rebuilt_from_metadata_content_and_journal(
    backends: t52.Backends,
) -> None:
    """NCR-MEMORY-005, one version (ADD v1.3 :3763, :3797-3799; LLD v1.1 :202)."""

    world = backends.world()
    record = world.admit("x", TEXT)
    partition = MemoryPartition.for_item(record.item)
    pointers = _pointers(world, "x")
    # Lost full-text projection, drifted vector projection.
    _drop(world, record, "FULL_TEXT")
    world.vector.inner.upsert(partition, VectorProfile.for_item(record.item), pointers["VECTOR"].store_ref,
                              pointers["VECTOR"].to_mapping(), t52.embed("tampered"),
                              attributes=index_attributes(record.item))
    assert _store_refused(lambda: world.coordinator.read_version(partition, "x", 1)) == (
        "REPRESENTATION_NOT_READY", "PROJECTION_DRIFT")
    # The vector body is not derivable from content: only the embedding the item digests is accepted.
    assert _store_refused(lambda: world.coordinator.rebuild_projections(partition, "x", 1)) == (
        "MEMORY_SCHEMA_INVALID", "EMBEDDING_MISSING")
    assert _store_refused(lambda: world.coordinator.rebuild_projections(
        partition, "x", 1, embedding=t52.embed("tampered"))) == ("MEMORY_SCHEMA_INVALID", "EMBEDDING_DIGEST_MISMATCH")
    report = world.coordinator.rebuild_projections(partition, "x", 1, embedding=t52.embed(TEXT))
    assert report.rebuilt == tuple(sorted((pointers["FULL_TEXT"].store_ref, pointers["VECTOR"].store_ref)))
    assert report.verified == ()
    assert world.coordinator.read_version(partition, "x", 1).payload == TEXT.encode()
    for mode in RetrievalMode:
        assert _hits(world, mode, TEXT) == [record.item.version_ref], mode
    # A rebuild of bound projections writes nothing.
    again = world.coordinator.rebuild_projections(partition, "x", 1, embedding=t52.embed(TEXT))
    assert again.rebuilt == () and again.verified == report.rebuilt
    # Unknown and foreign versions are not visible.
    assert _store_refused(lambda: world.coordinator.rebuild_projections(partition, "x", 2)) == NOT_VISIBLE


def test_ncr_memory_005_a_lost_partition_index_is_rebuilt_and_superseded_versions_stay_retired(
    backends: t52.Backends,
) -> None:
    """NCR-MEMORY-005, a partition: every committed version, the journal as replay source."""

    world = backends.world()
    old = world.admit("x", TEXT + " northern ford")
    new = world.admit("x", TEXT + " southern ford", version=2)
    other = world.admit("y", TEXT + " eastern ford")
    for record in (old, new, other):
        _drop(world, record, "FULL_TEXT", "VECTOR")
    partition = MemoryPartition.for_item(new.item)
    report = world.coordinator.rebuild_partition(partition, embed=_embed)
    assert len(report.rebuilt) == 6 and report.verified == ()
    for record in (old, new, other):
        materialized = world.coordinator.read_version(partition, record.item.memory_item_id, record.item.memory_version)
        assert materialized.item.version_ref == record.item.version_ref
    for mode in RetrievalMode:
        assert set(_hits(world, mode, TEXT + " ford")) == {new.item.version_ref, other.item.version_ref}, mode
        assert old.item.version_ref not in _hits(world, mode, "northern ford"), mode


def test_ncr_memory_005_a_deleted_item_is_never_resurrected_by_a_rebuild(lifecycle_backends: t55.Backends) -> None:
    """NCR-MEMORY-005 with the deletion saga (ADD v1.3 :3836): rebuild never resurrects deleted memory."""

    world = lifecycle_backends.world()
    gone = world.admit("gone", t55.TEXT + " alpha")
    keep = world.admit("keep", t55.TEXT)
    world.delete("gone", op="forget")
    partition = MemoryPartition.for_item(keep.item)
    for version in range(1, world.metadata.head("gone") + 1):
        assert _store_refused(lambda: world.coordinator.rebuild_projections(partition, "gone", version)) == NOT_VISIBLE, version
    report = world.coordinator.rebuild_partition(partition, embed=_embed)
    assert report.rebuilt == () and all("gone" not in ref for ref in report.verified)
    assert "gone" not in _served(world, "alpha") and "keep" in _served(world, t55.TEXT)
    assert not t55.content_present(world, gone)


# --------------------------------------------------------------------------
# SELF-CHECK-CHECKLIST (2026-11-08): input robustness of every parsing, adapter
# and port-answer path of the touched classes (backend-free negative cases on
# the unit worlds of OCOR-DEV-0050/0051/0052/0055/0059 and scripted backends).
# Each case is tied to the entry whose class it hardens.
# --------------------------------------------------------------------------

NAN, INF = float("nan"), float("inf")


def _code(action: Any) -> tuple[str, str]:
    """The typed refusal of ``action``; any other exception fails the case."""

    with pytest.raises(MemoryAdmissionError) as caught:
        action()
    return caught.value.reason_code, caught.value.detail_code


class _Twist:
    """Wraps a policy port and rewrites the fields of its answers."""

    def __init__(self, inner: Any, *, retrieval: dict[str, Any] | None = None,
                 materialization: dict[str, Any] | None = None) -> None:
        self.inner, self.retrieval, self.materialization = inner, retrieval or {}, materialization or {}

    def authorize_retrieval(self, request: Any, ctx: Any) -> Any:
        return dataclasses.replace(self.inner.authorize_retrieval(request, ctx), **self.retrieval)

    def authorize_read(self, item_id: str, version: int, ctx: Any) -> Any:
        return dataclasses.replace(self.inner.authorize_read(item_id, version, ctx), **self.retrieval)

    def authorize_materialization(self, item: Any, ctx: Any) -> Any:
        return dataclasses.replace(self.inner.authorize_materialization(item, ctx), **self.materialization)


MALFORMED_AUTHORIZATION = [
    ("permitted str", {"permitted": "no"}), ("permitted int", {"permitted": 1}),
    ("denied list", {"denied_memory_item_ids": ["item-1"]}), ("denied int", {"denied_memory_item_ids": frozenset({1})}),
    ("kinds list", {"memory_kinds": ["EPISODIC"]}), ("kinds str", {"memory_kinds": frozenset({"EPISODIC"})}),
    ("scopes list", {"memory_scopes": ["PROJECT"]}),
    ("bindings list", {"scope_bindings": [("project_id", "project-1")]}),
    ("binding value str", {"scope_bindings": {"project_id": "xxproject-1xx"}}),
    ("bundles list", {"policy_bundle_digests": ["x"]}), ("domains none", {"domains": None}),
    ("purposes str", {"compatible_purposes": "mission-planning"}),
    ("decision int", {"decision_ref": 7}), ("decision nan", {"decision_ref": NAN}), ("decision empty", {"decision_ref": ""}),
]
MALFORMED_DECISION = [
    ("permitted str", {"permitted": "no"}), ("permitted int", {"permitted": 1}),
    ("decision none", {"decision_ref": None}), ("decision inf", {"decision_ref": INF}), ("decision empty", {"decision_ref": ""}),
]
INVALID = ("CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID")


def _search_world() -> t52.World:
    world = t52.unit_world()
    world.admit("item-1", "alpha bravo")
    world.admit("item-2", "alpha charlie")
    return world


def _search(world: t52.World, mode: RetrievalMode = RetrievalMode.FULL_TEXT) -> Any:
    return world.service().search(t52.request(mode, text="alpha bravo"), binding=t52.binding())


def _search_denials(world: t52.World) -> list[tuple[str, str]]:
    return [(str(e["reason_code"]), str(e["detail_code"])) for e in world.audit.events if e["action"] == "searchMemory.denied"]


@pytest.mark.parametrize(("label", "fields"), MALFORMED_AUTHORIZATION, ids=[c[0] for c in MALFORMED_AUTHORIZATION])
def test_ncr_memory_001_a_malformed_retrieval_authorization_fails_closed(label: str, fields: dict[str, Any]) -> None:
    """SELF-CHECK-CHECKLIST point 2 (types before conversions): no field of the live decision is coerced or trusted."""

    world = _search_world()
    world.policy = _Twist(world.policy, retrieval=fields)  # type: ignore[assignment]
    assert _code(lambda: _search(world)) == INVALID
    assert _search_denials(world) == [INVALID]


@pytest.mark.parametrize(("label", "fields"), MALFORMED_DECISION, ids=[c[0] for c in MALFORMED_DECISION])
def test_ncr_memory_001_a_malformed_materialisation_decision_fails_closed(label: str, fields: dict[str, Any]) -> None:
    world = _search_world()
    world.policy = _Twist(world.policy, materialization=fields)  # type: ignore[assignment]
    assert _code(lambda: _search(world)) == INVALID
    assert _search_denials(world) == [INVALID]


@pytest.mark.parametrize("mode", [RetrievalMode.FULL_TEXT, RetrievalMode.VECTOR])
@pytest.mark.parametrize("score", [NAN, INF, -INF, "0.5", True, None], ids=["nan", "inf", "-inf", "str", "bool", "none"])
def test_ncr_memory_001_an_index_hit_score_that_is_not_a_finite_number_fails_closed(mode: RetrievalMode, score: Any) -> None:
    """SELF-CHECK-CHECKLIST point 2 (finite numbers): a NaN score never ranks first or zeroes the others."""

    world = _search_world()
    index = world.lexical if mode is RetrievalMode.FULL_TEXT else world.vector
    inner = index.search_eligible

    def scored(*args: Any, **kwargs: Any) -> list[IndexHit]:
        return [dataclasses.replace(hit, score=score) for hit in inner(*args, **kwargs)]

    index.search_eligible = scored  # type: ignore[method-assign]
    assert _code(lambda: _search(world, mode)) == ("REPRESENTATION_NOT_READY", "PROJECTION_DRIFT")
    assert _search_denials(world) == [("REPRESENTATION_NOT_READY", "PROJECTION_DRIFT")]


def test_ncr_memory_001_unexpected_port_failures_and_answers_are_typed_and_audited() -> None:
    world = _search_world()
    inner_get = world.metadata.get
    world.metadata.get = lambda *a: (_ for _ in ()).throw(RuntimeError("metadata store crashed"))  # type: ignore[method-assign]
    assert _code(lambda: _search(world)) == ("INTERNAL_ERROR", "RETRIEVAL_UNAVAILABLE")
    world.metadata.get = lambda *a: "row"  # type: ignore[method-assign]
    assert _code(lambda: _search(world)) == ("INTERNAL_ERROR", "METADATA_INVALID")
    world.metadata.get = inner_get  # type: ignore[method-assign]
    world.metadata.head = lambda item_id: True  # type: ignore[method-assign]
    assert _code(lambda: _search(world)) == ("INTERNAL_ERROR", "HEAD_INVALID")
    assert _search_denials(world) == [
        ("INTERNAL_ERROR", "RETRIEVAL_UNAVAILABLE"), ("INTERNAL_ERROR", "METADATA_INVALID"), ("INTERNAL_ERROR", "HEAD_INVALID"),
    ]


def _predicate(**changes: Any) -> EligibilityPredicate:
    fields: dict[str, Any] = {"memory_kinds": frozenset({"EPISODIC"}), "memory_scopes": frozenset({"PROJECT"}),
                              "valid_at": t52.NOW, "now": t52.NOW}
    fields.update(changes)
    return EligibilityPredicate(**fields)


@pytest.mark.parametrize("changes", [
    {"min_confidence": NAN}, {"min_confidence": INF}, {"min_confidence": True}, {"min_confidence": "0.5"}, {"min_confidence": 1.5},
    {"memory_kinds": "EPISODIC"}, {"memory_scopes": ["PROJECT"]}, {"source_kinds": ["OBSERVATION"]},
    {"content_schema_refs": frozenset({""})}, {"exclude_taint_labels": ["X"]}, {"excluded_memory_item_ids": frozenset({7})},
], ids=lambda c: next(iter(c)) + ":" + repr(next(iter(c.values()))))
def test_ncr_memory_001_an_eligibility_predicate_is_validated_at_construction(changes: dict[str, Any]) -> None:
    assert _code(lambda: _predicate(**changes)) == ("MEMORY_SCHEMA_INVALID", "QUERY_INVALID")


def test_ncr_memory_001_the_reference_predicate_never_raises_on_a_malformed_attribute_record() -> None:
    world = t52.unit_world()
    record = world.admit("item-1", "alpha bravo")
    good = index_attributes(record.item)
    predicate = _predicate(min_confidence=0.0, excluded_memory_item_ids=frozenset({"other"}))
    assert predicate.accepts(good)
    for name, value in (("memory_item_id", ["a"]), ("memory_kind", {}), ("taint_labels", [["x"]]), ("valid_from_us", False),
                        ("confidence", True), ("confidence", NAN), ("lifecycle_status", None)):
        assert predicate.accepts({**good, name: value}) is False, name
    assert predicate.accepts(None) is False  # type: ignore[arg-type]
    assert predicate.accepts(["not", "a", "mapping"]) is False  # type: ignore[arg-type]


class _Response:
    def __init__(self, status: int, raw: bytes) -> None:
        self.status, self._raw = status, raw

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


@pytest.mark.parametrize(("label", "raw"), [
    ("not json", b"<html>"), ("not utf-8", b"\xff\xfe\xfa"), ("nan token", b'{"x": NaN}'), ("infinity token", b'{"x": Infinity}'),
    ("duplicate key", b'{"x": 1, "x": 2}'),
], ids=lambda v: v if isinstance(v, str) else "")
def test_ncr_memory_001_an_index_answer_that_is_not_strict_i_json_is_typed(monkeypatch: pytest.MonkeyPatch, label: str, raw: bytes) -> None:
    monkeypatch.setattr(A.urllib.request, "urlopen", lambda request, timeout: _Response(200, raw))
    assert _code(lambda: A._http("GET", "http://qdrant/collections")) == ("INTERNAL_ERROR", "INDEX_ANSWER_INVALID")


def test_ncr_memory_001_index_transport_failures_and_non_finite_requests_are_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport failure is the declared ``MemoryBackendUnavailable``, typed by the coordinator at the boundary.

    The commit path keeps STORE_COMMIT_INCOMPLETE for an unreachable index
    (OCOR-DEV-0051 vector outage); the read paths answer STORE_UNAVAILABLE.
    """

    def down(request: Any, timeout: float) -> Any:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(A.urllib.request, "urlopen", down)
    with pytest.raises(A.MemoryBackendUnavailable):
        A._http("GET", "http://qdrant/collections")
    monkeypatch.setattr(A.urllib.request, "urlopen", lambda request, timeout: (_ for _ in ()).throw(TimeoutError("slow")))
    with pytest.raises(A.MemoryBackendUnavailable):
        A._http("GET", "http://qdrant/collections")
    assert _code(lambda: A._http("POST", "http://qdrant/x", {"query": [NAN]})) == ("MEMORY_SCHEMA_INVALID", "QUERY_INVALID")
    world, coordinator, record, part, vector = _store_world()
    world.lexical.search = down  # type: ignore[method-assign]
    assert _code(lambda: coordinator.lexical_candidates(part, "probe fixture", limit=1)) == ("REPRESENTATION_NOT_READY", "STORE_UNAVAILABLE")


def _qdrant(status: int, data: Any) -> A.QdrantVectorIndex:
    index = A.QdrantVectorIndex("http://qdrant", "ns")
    index.collection = lambda partition, version: "c"  # type: ignore[method-assign]
    index._call = lambda *args, **kwargs: (status, data)  # type: ignore[method-assign]
    return index


def test_ncr_memory_001_a_malformed_qdrant_answer_is_typed() -> None:
    index = A.QdrantVectorIndex("http://qdrant", "ns")
    pid = index.point_id("r")
    point = {"id": pid, "payload": {"store_ref": "r", "pointer": {}}, "score": 0.5}
    assert index._hits([point])[0].score == 0.5
    for bad in ({"payload": {"store_ref": "r"}, "score": 0.1}, ["x"], {**point, "score": "abc"}, {**point, "score": True},
                {**point, "score": NAN}, {k: v for k, v in point.items() if k != "score"}, {**point, "payload": [1]},
                {**point, "id": True}):
        assert _code(lambda bad=bad: index._hits([bad])) == ("INTERNAL_ERROR", "INDEX_ANSWER_INVALID"), bad
    part = object.__new__(MemoryPartition)
    corrupt = ("INTERNAL_ERROR", "INDEX_ANSWER_INVALID")
    where = _predicate()
    for data in ({"status": "ok"}, None, {"result": "x"}, {"result": {"points": "x"}}):
        assert _code(lambda data=data: _qdrant(200, data).search_eligible(part, "v", [1.0], where=where, limit=1, offset=0)) == corrupt
    assert _code(lambda: _qdrant(200, {"result": "x"}).score_entries(part, "v", [1.0], ["r"])) == corrupt
    for data in ({"result": {"a": 1}}, {"result": ["x"]}):
        assert _code(lambda data=data: _qdrant(200, data).read_back(part, "v", "r")) == corrupt
    for data in ({"result": {"payload": None}}, {"result": {"payload": {"store_ref": "r"}}}):
        assert _code(lambda data=data: _qdrant(200, data).get(part, "v", "r")) == corrupt
    for count in (True, 3.9, "7", NAN, -1):
        assert _code(lambda count=count: _qdrant(200, {"result": {"count": count}}).count(part, "v")) == corrupt
    assert _code(lambda: _qdrant(200, {"result": {"collections": [{}]}}).collections()) == corrupt
    with pytest.raises(A.MemoryBackendUnavailable):
        _qdrant(500, None).search_eligible(part, "v", [1.0], where=where, limit=1, offset=0)


def test_ncr_memory_001_the_qdrant_entry_scan_follows_every_page() -> None:
    index = A.QdrantVectorIndex("http://qdrant", "ns")
    index.collection = lambda partition, version: "c"  # type: ignore[method-assign]
    pages = {None: (["a", "b"], "next"), "next": (["c"], None)}
    seen: list[Any] = []

    def call(method: str, path: str, body: Any = None) -> tuple[int, Any]:
        seen.append(body.get("offset"))
        refs, following = pages[body.get("offset")]
        points = [{"id": index.point_id(r), "payload": {"store_ref": r, "pointer": {}}} for r in refs]
        return 200, {"result": {"points": points, "next_page_offset": following}}

    index._call = call  # type: ignore[method-assign]
    assert [hit.store_ref for hit in index.entries(object.__new__(MemoryPartition), "v")] == ["a", "b", "c"]
    assert seen == [None, "next"]


class _Cursor:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def fetchone(self) -> Any:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[Any]:
        return self.rows


class _Connection:
    def __init__(self, script: list[list[Any]]) -> None:
        self.script = list(script)

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        return _Cursor(self.script.pop(0) if self.script else [])

    def transaction(self) -> _Connection:
        return self

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _pg(script: list[list[Any]]) -> A.PostgresStores:
    stores = object.__new__(A.PostgresStores)
    stores.dsn, stores.schema = "postgresql://scripted", "s"
    stores.connect = lambda: _Connection(script)  # type: ignore[method-assign]
    return stores


def _lexical(script: list[list[Any]]) -> A.PostgresLexicalIndex:
    index = A.PostgresLexicalIndex(_pg(script))
    index.table = lambda partition, version: "lex_x"  # type: ignore[method-assign]
    return index


def test_ncr_memory_001_a_malformed_lexical_row_is_typed() -> None:
    part = object.__new__(MemoryPartition)
    corrupt = ("INTERNAL_ERROR", "POINTER_INVALID")
    where = _predicate()
    for payload in ("{bad", "[1, 2]", '{"deletion_epoch": NaN}', '{"a": 1, "a": 2}'):
        assert _code(lambda p=payload: _lexical([[("simple",)], [("r", p, 0.5)]]).search(part, "v", "q", limit=1, offset=0)) == corrupt
        assert _code(lambda p=payload: _lexical([[("simple",)], [("r", p, 0.5)]]).search_eligible(
            part, "v", "q", where=where, limit=1, offset=0)) == corrupt
        assert _code(lambda p=payload: _lexical([[("simple",)], [(p, "doc", True)]]).read_back(part, "v", "r")) == corrupt
        assert _code(lambda p=payload: _lexical([[("simple",)], [("r", p)]]).entries(part, "v")) == corrupt
        assert _code(lambda p=payload: _lexical([[("simple",)], [(p,)]]).get(part, "v", "r")) == corrupt
    for score in (NAN, "0.5", True):
        assert _code(lambda s=score: _lexical([[("simple",)], [("r", "{}", s)]]).search(part, "v", "q", limit=1, offset=0)) == corrupt


def test_ncr_memory_001_query_inputs_that_cannot_reach_a_backend_are_refused() -> None:
    world = t51.UnitWorld()
    record, payload, vector = world.admission.admit("mem-p", "probe fixture text")
    coordinator = world.coordinator()
    coordinator.commit(record, payload=payload, embedding=vector)
    part = t51.partition_of(record)
    profile = VectorProfile.for_item(record.item)
    invalid = ("MEMORY_SCHEMA_INVALID", "QUERY_INVALID")
    for query in ("probe\x00fixture", "probe \ud800"):
        assert _code(lambda q=query: coordinator.lexical_candidates(part, q, limit=1)) == invalid
        assert _code(lambda q=query: coordinator.lexical_scores(part, q, [])) == invalid
    assert _code(lambda: coordinator.vector_candidates(part, profile, [True, *vector[1:]], limit=1)) == invalid
    assert _code(lambda: coordinator.vector_candidates(part, profile, [True, *vector], limit=1)) == invalid
    assert _code(lambda: coordinator.vector_scores(part, profile, ["x"] * len(vector), [])) == invalid
    assert _code(lambda: coordinator.vector_scores(part, profile, [True] * len(vector), [])) == invalid
    # A hit whose payload is not an object is never a bound candidate (and never a raw error).
    inner = world.lexical.search
    for bad in ([1, 2], "ab", None):
        world.lexical.search = lambda *a, bad=bad, **k: [IndexHit(h.store_ref, bad, h.score) for h in inner(*a, **k)]  # type: ignore[method-assign]
        assert coordinator.lexical_candidates(part, "probe fixture", limit=1) == ()
    world.lexical.search = lambda *a, **k: [object()]  # type: ignore[method-assign]
    assert coordinator.lexical_candidates(part, "probe fixture", limit=1) == ()


# -- NCR-MEMORY-002: admission ----------------------------------------------


@pytest.mark.parametrize(("label", "fields"), MALFORMED_DECISION, ids=[c[0] for c in MALFORMED_DECISION])
def test_ncr_memory_002_a_malformed_admission_decision_fails_closed_before_any_write(label: str, fields: dict[str, Any]) -> None:
    world = t50.make_world()
    inner = world.policy.authorize_admission
    world.policy.authorize_admission = lambda item, ctx: dataclasses.replace(inner(item, ctx), **fields)  # type: ignore[method-assign]
    assert _code(lambda: world.admit(t50.candidate())) == INVALID
    assert world.ledger.latest_version("mem-1") == 0


def test_ncr_memory_002_a_payload_that_is_not_strict_utf8_is_refused_before_any_write() -> None:
    world = t50.make_world()
    payload = b"observation \xff\xfe log"
    content = t50.candidate(content_ref="content:" + t50.d(payload).removeprefix("urn:sha256:"), content_digest=t50.d(payload))
    assert _code(lambda: world.admit(content, payload=payload)) == ("MEMORY_SCHEMA_INVALID", "PAYLOAD_INVALID")
    assert world.ledger.latest_version("mem-1") == 0


class _Serialization:
    def __init__(self, *, exit_fail: bool = False, suppress: bool = False) -> None:
        self.exit_fail, self.suppress, self.held = exit_fail, suppress, 0

    @contextlib.contextmanager
    def _plain(self) -> Iterator[None]:
        self.held += 1
        try:
            yield
        finally:
            self.held -= 1
            if self.exit_fail:
                raise OSError("lease lost on release")

    def hold(self, partition_digest: str) -> Any:
        if not self.suppress:
            return self._plain()
        owner = self

        class Suppressing:
            def __enter__(self) -> None:
                owner.held += 1

            def __exit__(self, *exc: object) -> bool:
                owner.held -= 1
                return True

        return Suppressing()


def _quota_unit_world(serialization: Any, **limits: Any) -> tuple[t55.World, t52.Audit]:
    from ocor_runtime.memory.operations import MemoryAdmissionQuota, MemoryOperationsLimits

    world = t55.unit_world()
    audit = t52.Audit()
    horizons = {"retention:standard": timedelta(days=365)}
    world.admission = MemoryAdmissionService(
        ledger=world.ledger, resolver=t52.Resolver(), policy=t52.base.Policy(), markings=world.markings, clock=world.clock,
        limits=AdmissionLimits(retention_horizons=horizons), audit=audit,
        quota=MemoryAdmissionQuota(metadata=world.metadata, ledger=world.ledger,
                                   limits=MemoryOperationsLimits(retention_horizons=horizons, **limits), serialization=serialization),
    )
    return world, audit


def test_ncr_memory_002_the_quota_hold_never_turns_a_written_version_into_a_denial_nor_hides_a_failed_write() -> None:
    serialization = _Serialization(exit_fail=True)
    world, audit = _quota_unit_world(serialization)
    assert _code(lambda: world.admit("z", t55.TEXT + " z", commit=False)) == ("CONTROL_PLANE_UNAVAILABLE", "QUOTA_RELEASE_FAILED")
    assert world.ledger.latest_version("z") == 1 and serialization.held == 0
    assert [e for e in audit.events if str(e.get("action", "")).endswith(".denied")] == []
    world, audit = _quota_unit_world(_Serialization(suppress=True))
    world.ledger.append = lambda record: (_ for _ in ()).throw(OSError("ledger down"))  # type: ignore[method-assign]
    assert _code(lambda: world.admit("y", t55.TEXT + " y", commit=False))[0] == "INTERNAL_ERROR"
    assert world.ledger.latest_version("y") == 0


def test_ncr_memory_002_quota_inventory_failure_and_invalid_operations_inputs_are_typed() -> None:
    world, _ = _quota_unit_world(_Serialization())
    world.metadata.versions_in = lambda digest: (_ for _ in ()).throw(ConnectionError("pg down"))  # type: ignore[method-assign]
    assert _code(lambda: world.admit("y", t55.TEXT + " y", commit=False)) == ("CONTROL_PLANE_UNAVAILABLE", "QUOTA_UNAVAILABLE")
    assert world.ledger.latest_version("y") == 0
    # The ledger inventory re-reads the journal: a file error of records() is the same typed refusal.
    world, _ = _quota_unit_world(_Serialization())
    for failure in (OSError("journal unreadable"), PermissionError("journal"), FileNotFoundError("journal")):
        world.ledger.records = lambda f=failure: (_ for _ in ()).throw(f)  # type: ignore[method-assign]
        assert _code(lambda: world.admit("y", t55.TEXT + " y", commit=False)) == ("CONTROL_PLANE_UNAVAILABLE", "QUOTA_UNAVAILABLE")
        assert world.ledger.latest_version("y") == 0
    for kwargs in ({"target_items": True, "limit": 1}, {"target_items": 0, "limit": True}, {"target_items": 0, "limit": NAN},
                   {"target_items": INF, "limit": 1}, {"target_items": 0, "limit": 101}):
        w = t55.unit_world()
        partition = t59.seed(w)
        service, _audit, _policy = t59.setup(w)
        assert _code(lambda: t59.invoke(service, w, partition, "relieve_pressure", **kwargs))[1] == "PRESSURE_LIMIT_INVALID", kwargs
    for demand in (None, {"new_items": 1}):
        w = t55.unit_world()
        partition = t59.seed(w)
        service, _audit, _policy = t59.setup(w)
        assert _code(lambda: t59.invoke(service, w, partition, "check_quota", demand=demand))[1] == "DEMAND_INVALID", demand


# -- NCR-MEMORY-003: lifecycle ------------------------------------------------


class _FaultyTombstones(L.InMemoryTombstoneStore):
    def __init__(self, fail_at: int) -> None:
        super().__init__()
        self.appends, self.fail_at = 0, fail_at

    def append(self, entry: Any) -> Any:
        self.appends += 1
        if self.appends == self.fail_at:
            raise OSError("tombstone journal down")
        return super().append(entry)


def test_ncr_memory_003_a_scoped_deletion_stopped_halfway_names_every_member_left_and_its_replay_completes_it() -> None:
    tombstones = _FaultyTombstones(fail_at=3)
    world = t55.unit_world(tombstones=tombstones)
    for name in "abc":
        world.admit(name, t55.TEXT + " " + name)
    with pytest.raises(MemoryAdmissionError) as caught:
        world.delete("a", scope="PROJECT_SCOPE", op="scope-op")
    error = caught.value
    left = [name for name in "abc" if world.status(name) != "DELETED"]
    assert left and getattr(error, "incomplete_memory_item_ids", None) == tuple(left)
    assert all(name in str(error) for name in left)
    denial = [e for e in world.lc_audit.events if e["action"] == "requestMemoryDeletion.denied"][-1]
    assert denial["incomplete_memory_item_ids"] == list(left)
    tombstones.fail_at = -1
    receipt = world.delete("a", scope="PROJECT_SCOPE", op="scope-op")
    assert receipt.to_mapping()["status"] == "COMPLETED"
    assert {name: world.status(name) for name in "abc"} == dict.fromkeys("abc", "DELETED")


def test_ncr_memory_003_a_bulk_scope_addressed_to_a_forgotten_item_changes_nothing() -> None:
    world = t55.unit_world()
    world.admit("a", t55.TEXT + " a")
    world.admit("b", t55.TEXT + " b")
    world.delete("a")
    assert _code(lambda: world.delete("a", scope="PROJECT_SCOPE", op="again")) == ("LIFECYCLE_TRANSITION_INVALID", "TRANSITION_NOT_DECLARED")
    assert world.status("b") == "ACTIVE"


def test_ncr_memory_003_another_tenant_and_invisible_items_neither_block_nor_bound_a_scoped_deletion(monkeypatch: pytest.MonkeyPatch) -> None:
    foreign = t52.context(compartments=("alpha", "bravo"), tenant="tenant-b")
    world = t55.unit_world()
    world.admit("mine", t55.TEXT)
    world.admit("theirs", t55.TEXT + " b", ctx=foreign)
    world.move("theirs", "REVOKED", ctx=foreign, op="shared-op")
    assert world.delete("mine", scope="PROJECT_SCOPE", op="shared-op").lifecycle_status == "DELETED"
    monkeypatch.setattr(L, "MAX_SCOPE_DELETION_ITEMS", 2)
    world = t55.unit_world()
    world.admit("mine", t55.TEXT)
    world.admit("hidden-1", t55.TEXT + " h1", ctx=t55.OUTSIDER)
    world.admit("hidden-2", t55.TEXT + " h2", ctx=t55.OUTSIDER)
    assert world.delete("mine", scope="PRINCIPAL_SCOPE", op="p").lifecycle_status == "DELETED"
    world = t55.unit_world()
    for name in ("a", "b", "c"):
        world.admit(name, t55.TEXT + " " + name)
    assert _code(lambda: world.delete("a", scope="PROJECT_SCOPE", op="big")) == ("REPRESENTATION_NOT_READY", "DELETION_SCOPE_BACKPRESSURE")
    assert {world.status(name) for name in "abc"} == {"ACTIVE"}


def test_ncr_memory_003_scope_preconditions_refuse_the_whole_request_before_any_write() -> None:
    world = t55.unit_world()
    world.admit("run-item", t55.TEXT, scope="RUN", bindings={"agent_run_id": "run-1"})
    assert _code(lambda: world.delete("run-item", scope="PROJECT_SCOPE")) == ("MEMORY_SCHEMA_INVALID", "DELETION_SCOPE_NOT_APPLICABLE")
    world = t55.unit_world()
    world.admit("a", t55.TEXT + " a")
    world.admit("b", t55.TEXT + " b")
    world.holds.place()
    world.move("b", "LEGAL_HOLD", hold=t55.HOLD, reason="LITIGATION_HOLD")
    epoch = world.tombstones.latest_epoch()
    assert _code(lambda: world.delete("a", scope="PROJECT_SCOPE"))[0] == "LEGAL_HOLD_ACTIVE"
    assert world.status("a") == "ACTIVE" and world.tombstones.latest_epoch() == epoch
    world.holds.lift()
    world.lc_policy.permitted = False
    assert _code(lambda: world.delete("a", scope="PROJECT_SCOPE"))[0] == "POLICY_DENIED"
    assert world.status("a") == "ACTIVE" and world.tombstones.latest_epoch() == epoch


def test_ncr_memory_003_a_resumed_deletion_runs_the_verified_scope_only() -> None:
    world = t55.unit_world()
    world.admit("x", t55.TEXT + " north")
    world.admit("x", t55.TEXT + " north corrected", version=2)
    inner = world.metadata.commit
    state = {"fail": True}

    def commit(*args: Any, **kwargs: Any) -> Any:
        if state["fail"]:
            state["fail"] = False
            raise OSError("metadata down")
        return inner(*args, **kwargs)

    world.metadata.commit = commit  # type: ignore[method-assign]
    with pytest.raises(MemoryAdmissionError):
        world.delete("x", op="del-x")
    slot = ("x", world.ledger.latest_version("x"))
    record = world.ledger._versions[slot]
    for tampered in ("LATEST_VERSION", 7):
        event = {**record.lifecycle_event, "deletion_scope": tampered}
        world.ledger._versions[slot] = dataclasses.replace(record, lifecycle_event=event)
        assert _code(lambda: world.delete("x", op="del-x")) == ("INTERNAL_ERROR", "MEMORY_LEDGER_CORRUPTED"), tampered
    world.ledger._versions[slot] = record
    assert world.delete("x", op="del-x").lifecycle_status == "DELETED"


def test_ncr_memory_003_latest_version_purges_the_head_content_even_when_an_earlier_version_shares_it() -> None:
    world = t55.unit_world()
    first = world.admit("x", t55.TEXT + " north")
    world.move("x", "REVOKED")
    receipt = world.delete("x", scope="LATEST_VERSION", op="forget-latest")
    assert receipt.to_mapping()["status"] == "COMPLETED" and receipt.lifecycle_status == "DELETED"
    assert not t55.content_present(world, first)


def test_ncr_memory_003_malformed_lifecycle_port_answers_are_typed() -> None:
    world = t55.unit_world()
    world.admit("x", t55.TEXT)
    world.holds.place()
    world.move("x", "LEGAL_HOLD", hold=t55.HOLD, reason="LITIGATION_HOLD")
    world.holds.status = lambda ref, ctx: "active"  # type: ignore[method-assign]
    assert _code(lambda: world.move("x", "ACTIVE", reason="HOLD_RELEASED")) == ("CONTROL_PLANE_UNAVAILABLE", "LEGAL_HOLD_REGISTRY_INVALID")
    world = t55.unit_world()
    world.admit("x", t55.TEXT)
    world.holds.place()
    world.move("x", "LEGAL_HOLD", hold=t55.HOLD, reason="LITIGATION_HOLD")
    world.holds.lift()
    for epoch in (True, None, -1):
        world.lc_stop.current_epoch = lambda ctx, epoch=epoch: epoch  # type: ignore[method-assign]
        assert _code(lambda: world.move("x", "ACTIVE", reason="HOLD_RELEASED")) == ("CONTROL_PLANE_UNAVAILABLE", "STOP_STATE_INVALID"), epoch
    world = t55.unit_world()
    for limit in (True, 0, 1.5):
        assert _code(lambda limit=limit: world.lifecycle.enforce_expiry(binding=t52.binding(), operation_id="e", limit=limit))[1] == "LIMIT_INVALID"


# -- NCR-MEMORY-004: getMemoryItemVersion ---------------------------------------


def _read_world() -> t52.World:
    world = t52.unit_world()
    world.admit("item-1", "alpha bravo")
    world.policy = ReadGrantPolicy()
    return world


def _read(world: t52.World) -> Any:
    return _reader(world).get_item_version("item-1", 1, binding=t52.binding())


def _read_denials(world: t52.World) -> list[tuple[str, str]]:
    return [(str(e["reason_code"]), str(e["detail_code"])) for e in world.audit.events if e["action"] == "getMemoryItemVersion.denied"]


@pytest.mark.parametrize(("label", "fields"), MALFORMED_AUTHORIZATION, ids=[c[0] for c in MALFORMED_AUTHORIZATION])
def test_ncr_memory_004_a_malformed_read_authorization_fails_closed(label: str, fields: dict[str, Any]) -> None:
    world = _read_world()
    world.policy = _Twist(world.policy, retrieval=fields)  # type: ignore[assignment]
    assert _code(lambda: _read(world)) == INVALID
    assert _read_denials(world) == [INVALID]


@pytest.mark.parametrize(("label", "fields"), MALFORMED_DECISION, ids=[c[0] for c in MALFORMED_DECISION])
def test_ncr_memory_004_a_malformed_read_materialisation_decision_fails_closed(label: str, fields: dict[str, Any]) -> None:
    world = _read_world()
    world.policy = _Twist(world.policy, materialization=fields)  # type: ignore[assignment]
    assert _code(lambda: _read(world)) == INVALID
    assert _read_denials(world) == [INVALID]


def test_ncr_memory_004_port_failures_stale_policy_and_a_moving_stop_epoch_are_typed_and_audited() -> None:
    world = _read_world()
    world.metadata.get = lambda *a: "row"  # type: ignore[method-assign]
    assert _code(lambda: _read(world)) == ("INTERNAL_ERROR", "METADATA_INVALID")
    world = _read_world()
    world.metadata.get = lambda *a: (_ for _ in ()).throw(RuntimeError("metadata store crashed"))  # type: ignore[method-assign]
    assert _code(lambda: _read(world)) == ("INTERNAL_ERROR", "RETRIEVAL_UNAVAILABLE")
    world = _read_world()
    world.metadata.head = lambda item_id: 1.0  # type: ignore[method-assign]
    assert _code(lambda: _read(world)) == ("INTERNAL_ERROR", "HEAD_INVALID")
    world = _read_world()
    world.policy.bundle = t52.base.d("old-bundle")
    assert _code(lambda: _read(world)) == ("STALE_POLICY", "POLICY_BUNDLE_MISMATCH")
    world = _read_world()
    world.policy = _Twist(world.policy, materialization={"policy_bundle_digest": t52.base.d("old-bundle")})  # type: ignore[assignment]
    assert _code(lambda: _read(world)) == ("STALE_POLICY", "POLICY_BUNDLE_MISMATCH")
    world = _read_world()
    world.stop.bump_after = 1
    assert _code(lambda: _read(world)) == ("STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED")
    assert _read_denials(world) == [("STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED")]


# -- NCR-MEMORY-005: store coordinator and adapters --------------------------------


def _store_world() -> tuple[Any, Any, Any, MemoryPartition, list[float]]:
    world = t51.UnitWorld()
    record, payload, vector = world.admission.admit("mem-p", "probe fixture text")
    coordinator = world.coordinator()
    coordinator.commit(record, payload=payload, embedding=vector)
    return world, coordinator, record, t51.partition_of(record), list(vector)


def test_ncr_memory_005_store_reads_and_rebuilds_validate_their_arguments_and_the_slot_returned() -> None:
    world, coordinator, record, part, vector = _store_world()
    item_id = record.item.memory_item_id
    invalid = ("MEMORY_SCHEMA_INVALID", "QUERY_INVALID")
    for args in ((part, item_id, True), (part, item_id, "1"), (part, item_id, 0), (part, "", 1), (part, None, 1), (None, item_id, 1)):
        assert _code(lambda args=args: coordinator.read_version(*args)) == invalid, args
        assert _code(lambda args=args: coordinator.rebuild_projections(*args, embedding=vector)) == invalid, args
    other, other_payload, other_vector = world.admission.admit("mem-q", "other fixture text")
    coordinator.commit(other, payload=other_payload, embedding=other_vector)
    inner = world.metadata.get
    world.metadata.get = lambda i, v: inner("mem-q", 1)  # type: ignore[method-assign]
    assert _code(lambda: coordinator.read_version(part, item_id, 1)) == ("INTERNAL_ERROR", "METADATA_INVALID")
    assert _code(lambda: coordinator.rebuild_projections(part, item_id, 1, embedding=other_vector)) == ("INTERNAL_ERROR", "METADATA_INVALID")


@pytest.mark.parametrize("port", ["metadata.get", "metadata.head", "metadata.pointer", "lexical.read_back", "content.get", "metadata.versions_in"])
def test_ncr_memory_005_a_store_port_failure_is_a_typed_refusal_on_every_read_and_rebuild_path(port: str) -> None:
    world, coordinator, record, part, vector = _store_world()
    owner, name = port.split(".")
    setattr(getattr(world, owner), name, lambda *a, **k: (_ for _ in ()).throw(ConnectionError("backend down")))
    item_id = record.item.memory_item_id
    unavailable = ("REPRESENTATION_NOT_READY", "STORE_UNAVAILABLE")
    if port == "metadata.versions_in":
        assert _code(lambda: coordinator.rebuild_partition(part, embed=lambda i, p: vector)) == unavailable
        assert _code(lambda: coordinator.reconcile()) == unavailable
        return
    if port != "metadata.head":  # an exact-version read never consults the head pointer
        assert _code(lambda: coordinator.read_version(part, item_id, 1)) == unavailable
    if port in ("metadata.get", "metadata.head"):
        assert _code(lambda: coordinator.rebuild_projections(part, item_id, 1, embedding=vector)) == unavailable
        assert _code(lambda: coordinator.read_latest(part, item_id)) == unavailable


def test_ncr_memory_005_a_malformed_metadata_row_is_typed() -> None:
    world, coordinator, record, part, vector = _store_world()
    stored = world.metadata.get(record.item.memory_item_id, 1)
    body = json.dumps(stored.staged.body())
    staged_at = stored.staged.staged_at
    corrupt = ("INTERNAL_ERROR", "METADATA_INVALID")
    for row in (("{bad", staged_at, "COMMITTED", staged_at), ("[1]", staged_at, "COMMITTED", staged_at),
                (body, staged_at, "WEIRD", staged_at), (body, staged_at, "COMMITTED", None), (body, staged_at, "COMMITTED", "yesterday"),
                (body, "yesterday", "COMMITTED", staged_at), (body, staged_at, "PENDING", staged_at), (body.replace("}", ', "x": NaN}', 1), staged_at, "COMMITTED", staged_at)):
        assert _code(lambda row=row: _pg([[row]]).get("mem-p", 1)) == corrupt, row
    assert _pg([[(body, staged_at, "COMMITTED", staged_at)]]).get("mem-p", 1) is not None
    for row in (("{bad", "COMMITTED"), ('{"a": 1}', "WEIRD")):
        assert _code(lambda row=row: _pg([[row]]).pointer("r")) == ("INTERNAL_ERROR", "POINTER_INVALID")
    assert _code(lambda: _pg([[("nope",)]]).partitions()) == ("INTERNAL_ERROR", "PARTITION_INVALID")
    assert _code(lambda: _pg([[(True,)]]).head("mem-p")) == corrupt


class _Bao:
    def __init__(self, response: Any) -> None:
        self.response = response

    def call(self, method: str, path: str, body: Any = None) -> Any:
        return self.response


def test_ncr_memory_005_a_malformed_transit_answer_or_content_row_is_typed() -> None:
    ctx = {"content_object_ref": "a", "partition_digest": "b", "content_digest": "c"}
    corrupt = ("INTERNAL_ERROR", "CIPHER_ANSWER_INVALID")
    for response in ({}, {"data": {"ciphertext": 5}}, None, {"data": {"ciphertext": "vault:v1:\udc80"}}):
        assert _code(lambda r=response: A.OpenBaoTransitCipher(_Bao(r)).seal(context=ctx, plaintext=b"x")) == corrupt
    key = "urn:ocor:memory-key:transit:memory-content"
    for sealed, response in ((SealedContent(key, b"\xff"), {"data": {"plaintext": "eA=="}}),
                             (SealedContent(key, b"v"), {"data": {"plaintext": "e!A=*="}}),
                             (SealedContent(key, b"v"), {"data": {"plaintext": "e"}}),
                             (SealedContent(key, b"v"), {"data": {}}),
                             (SealedContent("urn:ocor:memory-key:transit:other", b"v"), {"data": {"plaintext": "eA=="}})):
        assert _code(lambda s=sealed, r=response: A.OpenBaoTransitCipher(_Bao(r)).open(context=ctx, sealed=s)) == corrupt
    assert A.OpenBaoTransitCipher(_Bao({"data": {"plaintext": "eA=="}})).open(context=ctx, sealed=SealedContent(key, b"v")) == b"x"
    for row in ((5, b"x"), (key, "not bytes"), ("", b"x")):
        assert _code(lambda row=row: A.PostgresContentStore(_pg([[row]])).get("r")) == ("INTERNAL_ERROR", "CONTENT_INVALID")



# -- Preventive review OCOR-DEV-REM-0059-90e47e872c3e-pre: blocking findings P1-P10 ----------


def test_ncr_memory_002_admitted_versions_not_yet_committed_count_against_the_item_quota() -> None:
    """P1: a new item admitted to the ledger and not yet committed to the stores consumes quota."""

    world, _ = _quota_unit_world(_Serialization(), max_items=1)
    world.admit("p", t55.TEXT + " p", commit=False)
    assert _code(lambda: world.admit("q", t55.TEXT + " q", commit=False)) == ("POLICY_DENIED", "ITEM_QUOTA_EXCEEDED")
    assert _code(lambda: world.admit("r", t55.TEXT + " r", commit=False)) == ("POLICY_DENIED", "ITEM_QUOTA_EXCEEDED")
    assert [world.ledger.latest_version(name) for name in "pqr"] == [1, 0, 0]
    # The same item's own pending version is not a second item, and a committed one still counts once.
    world, _ = _quota_unit_world(_Serialization(), max_items=2)
    world.admit("p", t55.TEXT + " p")
    world.admit("q", t55.TEXT + " q", commit=False)
    assert _code(lambda: world.admit("r", t55.TEXT + " r", commit=False)) == ("POLICY_DENIED", "ITEM_QUOTA_EXCEEDED")
    assert world.ledger.latest_version("r") == 0


def test_ncr_memory_002_pending_admissions_consume_index_entries_and_a_ledger_without_inventory_is_refused() -> None:
    from ocor_runtime.memory.operations import MemoryAdmissionQuota, MemoryOperationsLimits

    world, _ = _quota_unit_world(_Serialization(), max_items=10, max_index_entries=4)
    world.admit("p", t55.TEXT + " p", commit=False)
    assert _code(lambda: world.admit("q", t55.TEXT + " q", commit=False)) == ("POLICY_DENIED", "INDEX_QUOTA_EXCEEDED")

    class NoInventory:
        def get(self, *a: Any) -> None:
            return None

        def latest_version(self, *a: Any) -> int:
            return 0

    with pytest.raises(TypeError):
        MemoryAdmissionQuota(metadata=world.metadata, ledger=NoInventory(),  # type: ignore[arg-type]
                             limits=MemoryOperationsLimits(), serialization=_Serialization())
    world, _ = _quota_unit_world(_Serialization())
    world.ledger.records = lambda: (_ for _ in ()).throw(OSError("journal unreadable"))  # type: ignore[method-assign]
    assert _code(lambda: world.admit("y", t55.TEXT + " y", commit=False)) == ("CONTROL_PLANE_UNAVAILABLE", "QUOTA_UNAVAILABLE")
    assert world.ledger.latest_version("y") == 0


def test_ncr_memory_004_a_metadata_answer_for_another_slot_is_never_served() -> None:
    """P3: the exact-version read binds the stored version to the requested slot."""

    world = _read_world()
    world.admit("other", "charlie delta")
    inner = world.metadata.get
    world.metadata.get = lambda item_id, version: inner("other", version)  # type: ignore[method-assign]
    assert _code(lambda: _read(world)) == ("INTERNAL_ERROR", "METADATA_INVALID")
    assert _read_denials(world) == [("INTERNAL_ERROR", "METADATA_INVALID")]
    assert not [e for e in world.audit.events if e.get("action") == "getMemoryItemVersion"]
    # Historical version: the head is right, the older slot is answered with another item's version.
    world = _read_world()
    world.admit("item-1", "alpha bravo corrected", version=2)
    world.admit("other", "charlie delta")
    inner = world.metadata.get
    world.metadata.get = lambda item_id, version: inner("other", 1) if version == 1 else inner(item_id, version)  # type: ignore[method-assign]
    assert _code(lambda: _reader(world).get_item_version("item-1", 1, binding=t52.binding())) == ("INTERNAL_ERROR", "METADATA_INVALID")


@pytest.mark.parametrize("permitted", ["no", 1, None])
def test_ncr_memory_003_a_malformed_lifecycle_decision_never_authorises_a_deletion(permitted: Any) -> None:
    """P4: ``_decide`` reads only a well-formed decision (the whole lifecycle class)."""

    world = t55.unit_world()
    world.admit("x", t55.TEXT)
    world.lc_policy.permitted = permitted
    assert _code(lambda: world.delete("x", scope="PROJECT_SCOPE", op="bad-decision")) == INVALID
    assert _code(lambda: world.delete("x", op="bad-decision-2")) == INVALID
    assert world.status("x") == "ACTIVE"
    assert t55.denials(world)[-1] == INVALID


@pytest.mark.parametrize("decision_ref", [7, None, "", True])
def test_ncr_memory_002_a_malformed_operations_decision_is_refused(decision_ref: Any) -> None:
    """P4: ``MemoryOperationsService._authorize`` reads only a well-formed decision."""

    w = t55.unit_world()
    partition = t59.seed(w)
    service, _audit, policy = t59.setup(w)
    original = policy.authorize_operations
    policy.authorize_operations = lambda *args: dataclasses.replace(original(*args), decision_ref=decision_ref)  # type: ignore[method-assign]
    assert _code(lambda: t59.invoke(service, w, partition)) == ("CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID")
    service, _audit, policy = t59.setup(w)
    original_bundle = policy.authorize_operations
    policy.authorize_operations = lambda *args: dataclasses.replace(original_bundle(*args), policy_bundle_digest=5)  # type: ignore[method-assign]
    assert _code(lambda: t59.invoke(service, w, partition)) == ("CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID")


@pytest.mark.parametrize(("port", "scope"), [("head", "PROJECT_SCOPE"), ("partitions", "PROJECT_SCOPE"),
                                             ("versions_in", "PROJECT_SCOPE"), ("head", "ALL_VERSIONS")])
def test_ncr_memory_003_a_metadata_failure_before_any_deletion_write_is_typed_and_audited(port: str, scope: str) -> None:
    """P5: metadata reads of the lifecycle resolution are typed refusals, never raw backend errors."""

    world = t55.unit_world()
    world.admit("x", t55.TEXT)
    epoch = world.tombstones.latest_epoch()
    setattr(world.metadata, port, lambda *a: (_ for _ in ()).throw(ConnectionError("postgres down")))
    assert _code(lambda: world.delete("x", scope=scope, op="transport")) == ("REPRESENTATION_NOT_READY", "STORE_UNAVAILABLE")
    assert t55.denials(world) == [("REPRESENTATION_NOT_READY", "STORE_UNAVAILABLE")]
    assert world.tombstones.latest_epoch() == epoch and world.ledger.latest_version("x") == 1


def test_ncr_memory_003_a_scoped_deletion_resumes_whatever_the_position_of_the_addressed_item() -> None:
    """P6: the replay completes every member even when the addressed item was not started."""

    tombstones = _FaultyTombstones(fail_at=3)
    world = t55.unit_world(tombstones=tombstones)
    for name in "abz":
        world.admit(name, t55.TEXT + " " + name)
    with pytest.raises(MemoryAdmissionError) as caught:
        world.delete("z", scope="PROJECT_SCOPE", op="probe-replay")
    left = getattr(caught.value, "incomplete_memory_item_ids", ())
    assert "z" in left and world.status("a") == "DELETED"
    tombstones.fail_at = -1
    receipt = world.delete("z", scope="PROJECT_SCOPE", op="probe-replay")
    assert receipt.to_mapping()["status"] == "COMPLETED"
    assert {name: world.status(name) for name in "abz"} == dict.fromkeys("abz", "DELETED")
    # Another request reusing the operation id is still refused.
    world.admit("c", t55.TEXT + " c")
    assert _code(lambda: world.delete("c", scope="PROJECT_SCOPE", op="probe-replay")) == (
        "MEMORY_IDEMPOTENCY_CONFLICT", "OPERATION_REUSED")
    assert world.status("c") == "ACTIVE"


def test_ncr_memory_003_the_replay_of_a_scoped_deletion_never_widens_its_member_set() -> None:
    """P7: the replay answers for the members of the original request only, with the original receipt."""

    world = t55.unit_world()
    world.admit("a", t55.TEXT + " a")
    first = world.delete("a", scope="PROJECT_SCOPE", op="once")
    world.admit("b", t55.TEXT + " b")
    second = world.delete("a", scope="PROJECT_SCOPE", op="once")
    assert world.status("b") == "ACTIVE"
    assert first.to_mapping() == second.to_mapping()
    # Half-way: a member admitted after the stop is not part of the resumed request either.
    tombstones = _FaultyTombstones(fail_at=3)
    world = t55.unit_world(tombstones=tombstones)
    for name in "abc":
        world.admit(name, t55.TEXT + " " + name)
    with pytest.raises(MemoryAdmissionError):
        world.delete("a", scope="PROJECT_SCOPE", op="half")
    world.admit("d", t55.TEXT + " d")
    tombstones.fail_at = -1
    assert world.delete("a", scope="PROJECT_SCOPE", op="half").to_mapping()["status"] == "COMPLETED"
    assert {name: world.status(name) for name in "abcd"} == {"a": "DELETED", "b": "DELETED", "c": "DELETED", "d": "ACTIVE"}


def test_ncr_memory_003_a_tampered_recorded_member_set_is_refused() -> None:
    tombstones = _FaultyTombstones(fail_at=3)
    world = t55.unit_world(tombstones=tombstones)
    for name in "abc":
        world.admit(name, t55.TEXT + " " + name)
    with pytest.raises(MemoryAdmissionError):
        world.delete("a", scope="PROJECT_SCOPE", op="tamper")
    tombstones.fail_at = -1
    slots = [slot for slot, rec in world.ledger._versions.items()
             if rec.lifecycle_event.get("operation_id") == "tamper" and rec.lifecycle_event.get("phase") == "PENDING"]
    assert slots
    for tampered in (["a"], "abc", [1, 2], ["a", "a", "b", "c"], None):
        saved = {slot: world.ledger._versions[slot] for slot in slots}
        for slot in slots:
            rec = world.ledger._versions[slot]
            event = {**rec.lifecycle_event, "scope_members": tampered}
            world.ledger._versions[slot] = dataclasses.replace(rec, lifecycle_event=event)
        assert _code(lambda: world.delete("a", scope="PROJECT_SCOPE", op="tamper")) == ("INTERNAL_ERROR", "MEMORY_LEDGER_CORRUPTED"), tampered
        world.ledger._versions.update(saved)
    assert world.delete("a", scope="PROJECT_SCOPE", op="tamper").to_mapping()["status"] == "COMPLETED"


def test_ncr_memory_005_a_drifted_full_text_projection_is_repaired_by_the_rebuild(backends: t52.Backends) -> None:
    """P8: the real PostgreSQL full-text row with a divergent body is replaced, not kept (ON CONFLICT DO NOTHING)."""

    world = backends.world()
    record = world.admit("x", TEXT)
    partition = MemoryPartition.for_item(record.item)
    pointer = _pointers(world, "x")["FULL_TEXT"]
    index = world.lexical.inner
    table = index.table(partition, pointer.representation_version)
    with index._s.connect() as conn:
        conn.execute(
            f'UPDATE "{index._s.schema}"."{table}" SET document = %s, tsv = to_tsvector(\'simple\', %s) WHERE store_ref = %s',
            ("tampered full text", "tampered full text", pointer.store_ref),
        )
    assert _store_refused(lambda: world.coordinator.read_version(partition, "x", 1)) == ("REPRESENTATION_NOT_READY", "PROJECTION_DRIFT")
    report = world.coordinator.rebuild_projections(partition, "x", 1, embedding=t52.embed(TEXT))
    assert report.rebuilt == (pointer.store_ref,)
    assert index.read_back(partition, pointer.representation_version, pointer.store_ref).body == world.coordinator.read_version(
        partition, "x", 1).payload.decode()
    assert _hits(world, RetrievalMode.FULL_TEXT, TEXT) == [record.item.version_ref]
    assert _hits(world, RetrievalMode.FULL_TEXT, "tampered") == []


class _TruncatedError:
    """An HTTP error response whose body read is cut short."""

    def __init__(self) -> None:
        self.closed = False

    def __call__(self, request: Any, timeout: float) -> Any:
        import http.client

        owner = self

        class Error(urllib.error.HTTPError):
            def read(self, *a: Any) -> bytes:  # type: ignore[override]
                raise http.client.IncompleteRead(b"{", 99)

            def close(self) -> None:
                owner.closed = True

        raise Error("http://qdrant/x", 500, "boom", {}, None)  # type: ignore[arg-type]


def test_ncr_memory_001_adapter_answers_that_overflow_or_break_mid_read_are_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    """P9: IncompleteRead inside the HTTPError handler, non-ASCII transit plaintext, integers beyond float."""

    truncated = _TruncatedError()
    monkeypatch.setattr(A.urllib.request, "urlopen", truncated)
    with pytest.raises(A.MemoryBackendUnavailable):
        A._http("GET", "http://qdrant/x")
    assert truncated.closed
    key = "urn:ocor:memory-key:transit:memory-content"
    ctx = {"content_object_ref": "a", "partition_digest": "b", "content_digest": "c"}
    for plaintext in ("é", "eéA="):
        assert _code(lambda p=plaintext: A.OpenBaoTransitCipher(_Bao({"data": {"plaintext": p}})).open(
            context=ctx, sealed=SealedContent(key, b"v"))) == ("INTERNAL_ERROR", "CIPHER_ANSWER_INVALID")
    index = A.QdrantVectorIndex("http://qdrant", "ns")
    pid = index.point_id("r")
    for score in (10**400, -(10**400)):
        assert _code(lambda s=score: index._hits([{"id": pid, "payload": {"store_ref": "r"}, "score": s}])) == (
            "INTERNAL_ERROR", "INDEX_ANSWER_INVALID")
    assert index._hits([{"id": pid, "payload": {"store_ref": "r"}, "score": 3}])[0].score == 3.0
    for rank in (10**400, -(10**400)):
        assert _code(lambda r=rank: A._rank(r)) == ("INTERNAL_ERROR", "POINTER_INVALID")
    assert A._rank(2) == 2.0
    part = object.__new__(MemoryPartition)
    assert _code(lambda: _lexical([[("simple",)], [("r", "{}", 10**400)]]).search(part, "v", "q", limit=1, offset=0)) == (
        "INTERNAL_ERROR", "POINTER_INVALID")


def test_ncr_memory_001_postgres_rows_are_type_checked_before_use() -> None:
    """P10: the lexical layout configuration and the content object refs are validated, never coerced."""

    part = object.__new__(MemoryPartition)
    for bad in (7, True, None, "", b"simple"):
        assert _code(lambda b=bad: _lexical([[(b,)]]).get(part, "v", "r")) == ("INTERNAL_ERROR", "POINTER_INVALID"), bad
        assert _code(lambda b=bad: _lexical([[(b,)], [("r", "{}", 0.5)]]).search(part, "v", "q", limit=1, offset=0)) == (
            "INTERNAL_ERROR", "POINTER_INVALID"), bad
    assert _lexical([[("simple",)], [('{"a": 1}',)]]).get(part, "v", "r") == {"a": 1}
    for rows in ([(7,)], [(None,)], [("",)], [("a", "b")], [("a",), (True,)]):
        assert _code(lambda rows=rows: A.PostgresContentStore(_pg([rows])).refs("part")) == ("INTERNAL_ERROR", "CONTENT_INVALID"), rows
    assert A.PostgresContentStore(_pg([[("a",), ("b",)]])).refs("part") == ("a", "b")
    for ref in (None, 7, ""):
        assert _code(lambda r=ref: _lexical([[("simple",)], [(r, "{}", 0.5)]]).search(part, "v", "q", limit=1, offset=0)) == (
            "INTERNAL_ERROR", "POINTER_INVALID"), ref
        assert _code(lambda r=ref: _lexical([[("simple",)], [(r, "{}")]]).entries(part, "v")) == ("INTERNAL_ERROR", "POINTER_INVALID")
        assert _code(lambda r=ref: _lexical([[("simple",)], [(r, 0.5)]]).score_entries(part, "v", "q", ["r"])) == (
            "INTERNAL_ERROR", "POINTER_INVALID")
    assert _code(lambda: _pg([[("{}", "x", "COMMITTED")]]).get("mem-p", 1)) == ("INTERNAL_ERROR", "METADATA_INVALID")


# SELF-CHECK-CLASS-COVERAGE (2026-11-08) point 2: the journal ledger re-reads stored data
# (JournalMemoryVersionLedger._catch_up/_apply, reached by records(), the inventory of
# MemoryAdmissionQuota): decoding, types and finite numbers are checked on every line.


def _journal_entry(path: Any) -> dict[str, Any]:
    from ocor_runtime.kernel.canonical import parse_i_json

    lines = path.read_bytes().splitlines()
    assert len(lines) == 1
    entry = parse_i_json(lines[0])
    assert isinstance(entry, dict)
    return entry


def _write_entry(path: Any, entry: dict[str, Any]) -> None:
    from ocor_runtime.kernel.canonical import canonical_bytes, canonical_digest

    body = {"seq": entry["seq"], "prev": entry["prev"], "record": entry["record"]}
    path.write_bytes(canonical_bytes(dict(body, entry_digest=canonical_digest(body))) + b"\n")


def test_ncr_memory_002_a_journal_entry_whose_chain_fields_have_the_wrong_type_is_refused(tmp_path: Any) -> None:
    """A boolean is never an integer: a re-chained entry with seq true is refused on re-read and by records()."""

    from ocor_runtime.memory.model import JournalMemoryVersionLedger, MemoryLedgerCorrupted

    path = tmp_path / "versions.jsonl"
    ledger = JournalMemoryVersionLedger(path)
    t50.make_world(ledger).admit(t50.candidate())
    entry = _journal_entry(path)
    assert entry["seq"] == 1 and len(ledger.records()) == 1
    for field, value in (("seq", True), ("seq", "1"), ("seq", None), ("prev", 0), ("prev", None), ("record", [])):
        _write_entry(path, dict(entry, **{field: value}))
        with pytest.raises(MemoryLedgerCorrupted):
            JournalMemoryVersionLedger(path)
    for digest in (1, True, None, ["urn:sha256:" + "0" * 64]):
        path.write_bytes(json.dumps(dict(entry, entry_digest=digest), sort_keys=True, separators=(",", ":")).encode() + b"\n")
        with pytest.raises(MemoryLedgerCorrupted):
            JournalMemoryVersionLedger(path)
    # A line appended by another process is checked by records() before the inventory answers.
    _write_entry(path, entry)
    reopened = JournalMemoryVersionLedger(path)
    second = dict(entry, seq=True, prev=entry["entry_digest"])
    from ocor_runtime.kernel.canonical import canonical_bytes, canonical_digest

    body = {"seq": second["seq"], "prev": second["prev"], "record": second["record"]}
    with path.open("ab") as handle:
        handle.write(canonical_bytes(dict(body, entry_digest=canonical_digest(body))) + b"\n")
    with pytest.raises(MemoryLedgerCorrupted):
        reopened.records()


def test_ncr_memory_002_a_journal_line_that_is_not_strict_i_json_is_refused(tmp_path: Any) -> None:
    """Every decoding and parsing error of a re-read journal line, and every non-finite number, is MEMORY_LEDGER_CORRUPTED."""

    from ocor_runtime.memory.model import JournalMemoryVersionLedger, MemoryLedgerCorrupted

    path = tmp_path / "versions.jsonl"
    t50.make_world(JournalMemoryVersionLedger(path)).admit(t50.candidate())
    line = path.read_bytes().rstrip(b"\n")
    assert b'"confidence":0.8' in line
    variants = [
        line.replace(b'"confidence":0.8', b'"confidence":NaN'),
        line.replace(b'"confidence":0.8', b'"confidence":Infinity'),
        line.replace(b'"confidence":0.8', b'"confidence":-Infinity'),
        line.replace(b'"confidence":0.8', b'"confidence":1e400'),
        line.replace(b'"seq":1', b'"seq":1,"seq":1'),
        line.replace(b'"confidence":0.8', b'"confidence":0.8,"confidence":0.8'),
        line[:-1] + b"\xff}",
        line[:-1] + b"\xed\xa0\x80}",
        b"\xef\xbb\xbf" + line,
        line[:-1],
        b"[]",
        b"",
        line.replace(b'"mem-1"', b'"mem-1\\ud800"', 1),
        line.replace(b'"mem-1"', b'"mem-1\\u0000"', 1),
        b"[" * 100_000 + b"]" * 100_000,
        b'{"seq":' + b"[" * 100_000 + b"]" * 100_000 + b"}",
    ]
    for variant in variants:
        path.write_bytes(variant + b"\n")
        with pytest.raises(MemoryLedgerCorrupted) as caught:
            JournalMemoryVersionLedger(path)
        assert (caught.value.reason_code, caught.value.detail_code) == ("INTERNAL_ERROR", "MEMORY_LEDGER_CORRUPTED"), variant


def test_ncr_memory_005_stored_metadata_bytes_and_library_parse_errors_are_typed() -> None:
    """Re-read metadata rows: bytes columns (a SQL_ASCII client), invalid UTF-8, escaped lone surrogates and a
    nesting deeper than the parser's recursion limit are METADATA_INVALID; a valid UTF-8 bytes body is read."""

    world, coordinator, record, part, vector = _store_world()
    stored = world.metadata.get(record.item.memory_item_id, 1)
    body = json.dumps(stored.staged.body())
    staged_at = stored.staged.staged_at
    corrupt = ("INTERNAL_ERROR", "METADATA_INVALID")
    deep = "[" * 100_000 + "]" * 100_000
    for row in ((body.encode()[:-1] + b"\xff}", staged_at, "COMMITTED", staged_at), (body, staged_at, b"COMMITTED", staged_at),
                (body, staged_at.encode(), "COMMITTED", staged_at), (body, staged_at, "COMMITTED", staged_at.encode()),
                (body.replace('"mem-p"', '"mem-p\\ud800"', 1), staged_at, "COMMITTED", staged_at),
                (deep, staged_at, "COMMITTED", staged_at), (deep.encode(), staged_at, "COMMITTED", staged_at)):
        assert _code(lambda row=row: _pg([[row]]).get("mem-p", 1)) == corrupt, row[:2]
    assert _pg([[(body.encode(), staged_at, "COMMITTED", staged_at)]]).get("mem-p", 1) is not None
    for raw in (deep, deep.encode(), "{" + '"a":' * 50_000 + "1" + "}" * 50_000):
        assert _code(lambda raw=raw: A._strict_json(raw, "INDEX_ANSWER_INVALID")) == ("INTERNAL_ERROR", "INDEX_ANSWER_INVALID")


@pytest.mark.parametrize("failure", [
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    json.JSONDecodeError("Expecting value", "{", 1),
    RecursionError("maximum recursion depth exceeded while decoding a JSON object"),
    ValueError("invalid literal"),
    "psycopg.DataError",
])
def test_ncr_memory_005_a_port_decoding_or_parse_error_is_the_typed_store_unavailable_refusal(failure: Any) -> None:
    """Every decoding and parsing error class a store port can raise on a re-read is typed at the coordinator boundary."""

    if failure == "psycopg.DataError":
        import psycopg

        failure = psycopg.errors.CharacterNotInRepertoire('invalid byte sequence for encoding "UTF8": 0xff')
    world, coordinator, record, part, vector = _store_world()
    item_id = record.item.memory_item_id
    unavailable = ("REPRESENTATION_NOT_READY", "STORE_UNAVAILABLE")
    for owner, name in (("metadata", "get"), ("metadata", "head"), ("lexical", "read_back"), ("content", "get")):
        inner = getattr(getattr(world, owner), name)
        setattr(getattr(world, owner), name, lambda *a, f=failure, **k: (_ for _ in ()).throw(f))
        if name != "head":
            assert _code(lambda: coordinator.read_version(part, item_id, 1)) == unavailable, (owner, name)
        if owner == "metadata":
            assert _code(lambda: coordinator.read_latest(part, item_id)) == unavailable, (owner, name)
        setattr(getattr(world, owner), name, inner)
    assert coordinator.read_version(part, item_id, 1) is not None


class _CountingConnection(_Connection):
    """A scripted connection that records every release, and can fail its statements."""

    def __init__(self, script: list[list[Any]], ledger: list[str], fail: BaseException | None) -> None:
        super().__init__(script)
        self.ledger, self.fail = ledger, fail

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        if self.fail is not None:
            raise self.fail
        return super().execute(sql, params)

    def __enter__(self) -> _Connection:
        self.ledger.append("enter")
        return self

    def __exit__(self, *exc: object) -> bool:
        self.ledger.append("exit")
        return False


def test_ncr_memory_001_postgres_connections_are_released_on_every_exit() -> None:
    """PostgreSQL adapters: the connection is released after a malformed row and after a failed statement, never kept open."""

    import psycopg

    part = object.__new__(MemoryPartition)
    for fail in (None, psycopg.OperationalError("server closed the connection"), psycopg.errors.CharacterNotInRepertoire("0xff")):
        calls: list[tuple[str, Any]] = []
        for script, action in (
            ([[("{bad", "x", "COMMITTED", None)]], lambda s: s.get("mem-p", 1)),
            ([[(True,)]], lambda s: s.head("mem-p")),
            ([[("{bad", "COMMITTED")]], lambda s: s.pointer("r")),
            ([[("nope",)]], lambda s: s.partitions()),
            ([[(7, b"x")]], lambda s: A.PostgresContentStore(s).get("o")),
            ([[(7,)]], lambda s: A.PostgresContentStore(s).refs("p")),
        ):
            calls.append((repr(script), action))
            ledger: list[str] = []
            stores = object.__new__(A.PostgresStores)
            stores.dsn, stores.schema = "postgresql://scripted", "s"
            stores.connect = lambda sc=script, lg=ledger, f=fail: _CountingConnection(sc, lg, f)  # type: ignore[method-assign]
            with pytest.raises(Exception):
                action(stores)
            assert ledger and ledger.count("enter") == ledger.count("exit") and ledger[-1] == "exit", (script, fail, ledger)
        ledger = []
        stores = object.__new__(A.PostgresStores)
        stores.dsn, stores.schema = "postgresql://scripted", "s"
        stores.connect = lambda lg=ledger, f=fail: _CountingConnection([[(7,)], [("r", "{}", 0.5)]], lg, f)  # type: ignore[method-assign]
        index = A.PostgresLexicalIndex(stores)
        index.table = lambda partition, version: "lex_x"  # type: ignore[method-assign]
        for action in (lambda: index.search(part, "v", "q", limit=1, offset=0), lambda: index.get(part, "v", "r"),
                       lambda: index.entries(part, "v")):
            with pytest.raises(Exception):
                action()
        assert ledger.count("enter") == ledger.count("exit") and ledger[-1] == "exit", (fail, ledger)
