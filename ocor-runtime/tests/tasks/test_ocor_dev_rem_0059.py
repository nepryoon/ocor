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
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
import test_ocor_dev_0052 as t52
import test_ocor_dev_0054 as t54
import test_ocor_dev_0055 as t55
import test_ocor_dev_0059 as t59
import test_ocor_dev_rem_0020 as r20
from ocor_runtime.kernel.governed_context import GovernedContext
from ocor_runtime.memory.model import AdmissionLimits, MemoryAdmissionError, MemoryAdmissionService
from ocor_runtime.memory.retrieval import MemoryRetrievalError, RetrievalAuthorization, RetrievalMode
from ocor_runtime.memory.stores import MemoryPartition, VectorProfile, index_attributes

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
