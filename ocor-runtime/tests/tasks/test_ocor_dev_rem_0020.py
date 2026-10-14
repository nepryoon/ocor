"""OCOR-DEV-REM-0020: remediation of MemorySearchService (PO decision OCOR-DEV-0052-INDEPENDENT-REVIEW).

The independent review of the OCOR-DEV-0052 merge (``ae296eb``, PR #192)
reproduced, on the production code, defects that the governed verification
did not detect.  The OCOR-DEV-0052 GO and seal stay historical; this module
qualifies the remediation with explicit supersession.

* F1 (high) -- eligibility predicates (kind, scope, structured filters, head
  version, ``ACTIVE``, validity window, expiry) run inside the index and
  metadata queries (Qdrant payload filter, PostgreSQL ``WHERE``) while the
  complete post-query re-validation stays; searchable projections are only
  the ``ACTIVE`` head (a commit retires its predecessor, LLD v1.1 §2.8.4);
  ``STRUCTURED`` returns the deterministic top-k; backpressure is raised only
  for the declared bound on post-query drops.
* F3 (medium) -- every ``HYBRID`` factor is the backend's real value for every
  candidate of the union of the two pools.
* F4 (medium) -- the stop epoch is re-checked after every materialised hit and
  right before the audit receipt.
* F5 (low) -- every refusal after planning is an audited denial.
* F6 (low) -- positive and negative cases for the listed reason codes.

Scenarios R2-R6 of the decision were written first and run RED on the
unremediated code (``origin/main`` ``2c110c1``), then GREEN.  F2 (influence of
policy-denied items inside an authorized partition on error and work done)
is out of scope and tracked towards ``FGM-16``; ``test_f2_*`` records that
the F1 correction does not make it worse.

Qualifying cases run on the real pinned backends of OCOR-DEV-0051 through
the OCOR-DEV-0052 worlds: PostgreSQL 16 (``OCOR_LIVE_POSTGRES_DSN``), Qdrant
1.15.1 and OpenBao 2.6.2 transit.  A missing backend fails, it never skips.
Only the policy, stop-state and audit ports are test ports (as in 0052).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

import ocor_runtime.memory.stores as stores
import psycopg
import pytest
import test_ocor_dev_0051 as base
import test_ocor_dev_0052 as t52
from ocor_runtime.kernel.canonical import format_utc_timestamp
from ocor_runtime.kernel.governed_context import GovernedContext
from ocor_runtime.memory.model import GovernedMemoryItem, MemoryPolicyDecision
from ocor_runtime.memory.retrieval import (
    MemoryRetrievalError,
    MemorySearchResponse,
    RankingProfile,
    RetrievalAuthorization,
    RetrievalLimits,
    RetrievalMode,
    SearchQuery,
)
from ocor_runtime.memory.stores import LexicalProfile, MemoryPartition, VectorProfile

NOW = base.NOW
d = base.d
embed = base.embed
binding = t52.binding
context = t52.context
request = t52.request
refs = t52.refs
World = t52.World
PROFILE = RankingProfile()
LOOKUPS = frozenset({"search", "search_eligible", "score_entries"})

# The live worlds of OCOR-DEV-0052: real PostgreSQL, Qdrant and OpenBao.
live_backends = t52.live_backends
backends = t52.backends


def lookups(world: World) -> list[tuple[str, str, str]]:
    return [c for c in world.lexical.calls + world.vector.calls if c[0] in LOOKUPS]


def deadline(world: World, seconds: int = 30) -> str:
    return format_utc_timestamp(world.clock.now() + timedelta(seconds=seconds))


def search(world: World, mode: RetrievalMode, **kwargs: Any) -> MemorySearchResponse:
    kwargs.setdefault("deadline", deadline(world))
    service_kwargs = kwargs.pop("service", {})
    return world.service(**service_kwargs).search(request(mode, **kwargs), binding=binding())


def refused(world: World, mode: RetrievalMode, reason: str, detail: str, **kwargs: Any) -> MemoryRetrievalError:
    with pytest.raises(MemoryRetrievalError) as caught:
        search(world, mode, **kwargs)
    assert (caught.value.reason_code, caught.value.detail_code) == (reason, detail), caught.value
    return caught.value


def denials(world: World) -> list[tuple[str, str]]:
    return [(str(e["reason_code"]), str(e["detail_code"])) for e in world.audit.events if e["action"] == "searchMemory.denied"]


def receipts(world: World) -> list[Mapping[str, object]]:
    return [e for e in world.audit.events if e["action"] == "searchMemory"]


# --------------------------------------------------------------------------
# R2-R6: the decision's scenarios (RED on 2c110c1, GREEN after remediation)
# --------------------------------------------------------------------------


def test_r2_a_selective_kind_search_ignores_other_kinds_in_a_large_partition(backends: t52.Backends) -> None:
    world = backends.world()
    for n in range(3):
        world.admit(f"pref-{n}", "patrol shift preference", kind="PREFERENCE", source_kind="PREFERENCE", taint=("HUMAN_SUPPLIED",))
    for n in range(140):
        world.admit(f"epi-{n:03d}", "patrol report")
    expected = sorted(f"urn:ocor:memory:pref-{n}:v1" for n in range(3))
    for mode in (RetrievalMode.FULL_TEXT, RetrievalMode.VECTOR):
        response = search(world, mode, text="patrol shift preference", kinds=["PREFERENCE"])
        assert sorted(refs(response)) == expected, mode
    assert denials(world) == []


def test_r2b_other_kinds_matching_the_query_never_exhaust_the_declared_bound(backends: t52.Backends) -> None:
    """R2 with the 140 EPISODIC items matching the query in both representations.

    The literal R2 does not reproduce here on the unremediated code: the
    FULL_TEXT query requires every term, so "patrol report" never matches, and
    the Qdrant result window ends before the bound.  With matching documents
    the defect class of F1 (other kinds fill the pool) is reproduced.
    """

    world = backends.world()
    for n in range(3):
        world.admit(f"pref-{n}", "patrol shift preference", kind="PREFERENCE", source_kind="PREFERENCE", taint=("HUMAN_SUPPLIED",))
    for n in range(140):
        world.admit(f"epi-{n:03d}", f"patrol shift preference report {n:03d}")
    expected = sorted(f"urn:ocor:memory:pref-{n}:v1" for n in range(3))
    for mode in (RetrievalMode.FULL_TEXT, RetrievalMode.VECTOR, RetrievalMode.HYBRID):
        response = search(world, mode, text="patrol shift preference", kinds=["PREFERENCE"])
        assert sorted(refs(response)) == expected, mode
    assert denials(world) == []


def test_r3_a_corrected_item_occupies_one_slot_with_its_current_head(backends: t52.Backends) -> None:
    world = backends.world()
    world.admit("hot", "convoy route update 0")
    for n in range(1, 131):
        world.admit("hot", f"convoy route update {n}", version=n + 1)
    world.admit("other", "convoy route")
    response = search(world, RetrievalMode.FULL_TEXT, text="convoy route")
    assert sorted(refs(response)) == ["urn:ocor:memory:hot:v131", "urn:ocor:memory:other:v1"]
    assert denials(world) == []


def _oracle_rank(candidates: Mapping[str, Mapping[str, float]], top_k: int) -> list[str]:
    """Greedy ranking of the profile on given factors (every candidate shares one source)."""

    base_score = {
        ref: (
            PROFILE.lexical_weight * f["lexical"] + PROFILE.vector_weight * f["vector"]
            + PROFILE.recency_weight * f["recency"] + PROFILE.confidence_weight * f["confidence"]
            + PROFILE.source_quality_weight * f["source_quality"]
        ) * f["policy"]
        for ref, f in candidates.items()
    }
    return sorted(base_score, key=lambda ref: (-base_score[ref], ref))[:top_k]


def _real_lexical(world: World, texts: Mapping[str, str], query: str) -> dict[str, float]:
    config = LexicalProfile().text_search_configuration
    with psycopg.connect(world.metadata.dsn) as conn:
        raw = {
            ref: float(conn.execute(
                "SELECT CASE WHEN to_tsvector(%s::regconfig, %s) @@ plainto_tsquery(%s::regconfig, %s) "
                "THEN ts_rank_cd(to_tsvector(%s::regconfig, %s), plainto_tsquery(%s::regconfig, %s)) ELSE 0 END",
                (config, text, config, query, config, text, config, query),
            ).fetchone()[0])  # type: ignore[index]
            for ref, text in texts.items()
        }
    top = max(raw.values())
    return {ref: value / top for ref, value in raw.items()}


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    return dot / math.sqrt(math.fsum(x * x for x in a) * math.fsum(y * y for y in b))


@pytest.mark.parametrize("top_k", [20, 10])
def test_r4_every_hybrid_factor_is_the_real_value_over_the_pool_union(backends: t52.Backends, top_k: int) -> None:
    world = backends.world()
    texts = {"urn:ocor:memory:x:v1": "dawn"}
    world.admit("x", "dawn")
    for n in range(20):
        text = f"bridge crossing at dawn note{n:02d}"
        world.admit(f"note-{n:02d}", text)
        texts[f"urn:ocor:memory:note-{n:02d}:v1"] = text
    query_text, query_vector = "bridge crossing at dawn", embed("dawn")
    response = search(world, RetrievalMode.HYBRID, text=query_text, query_vector=query_vector, top_k=top_k)
    lexical = _real_lexical(world, texts, query_text)
    vector = {ref: max(0.0, min(1.0, _cosine(query_vector, embed(text)))) for ref, text in texts.items()}
    for hit in response.hits:
        ref = f"urn:ocor:memory:{hit.memory_item_id}:v{hit.memory_version}"
        assert hit.score_factors["lexical"] == pytest.approx(lexical[ref], rel=1e-6), ref
        assert hit.score_factors["vector"] == pytest.approx(vector[ref], abs=1e-5), ref
    # The union of the two pools: the lexical pool holds every matching note,
    # the vector pool the ``pool`` nearest items; every member is scored.
    pool = max(top_k, PROFILE.candidate_pool)
    vector_pool = sorted(vector, key=lambda ref: (-vector[ref], ref))[:pool]
    union = {ref for ref in texts if lexical[ref] > 0} | set(vector_pool)
    recency = 0.5 ** (600 / PROFILE.recency_half_life_seconds)
    oracle = {
        ref: {"lexical": lexical[ref], "vector": vector[ref], "recency": recency, "confidence": 0.8,
              "source_quality": 0.9, "policy": 1.0}
        for ref in union
    }
    assert refs(response) == _oracle_rank(oracle, top_k)
    for hit in response.hits:
        assert hit.final_score == pytest.approx(t52._expected_score(hit.score_factors))


def test_r5_a_stop_raised_while_the_first_hit_is_read_returns_no_hit_and_is_audited(backends: t52.Backends) -> None:
    world = backends.world()
    for n in range(3):
        world.admit(f"art-{n}", "artillery position report")
    original = world.coordinator.read_version
    reads: list[str] = []

    def read_and_stop(partition: MemoryPartition, memory_item_id: str, memory_version: int) -> Any:
        materialized = original(partition, memory_item_id, memory_version)
        reads.append(memory_item_id)
        if len(reads) == 1:
            world.stop.epoch += 1  # kill switch raised during the read of the first hit
        return materialized

    world.coordinator.read_version = read_and_stop  # type: ignore[method-assign]
    refused(world, RetrievalMode.FULL_TEXT, "STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED", text="artillery position report")
    assert len(reads) == 1  # no further content was read after the stop
    assert receipts(world) == [] and denials(world) == [("STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED")]


def _structured_oracle(world: World, top_k: int) -> list[str]:
    taint = dict(PROFILE.taint_policy)
    quality = dict(PROFILE.source_quality)
    factors: dict[str, dict[str, float]] = {}
    for record in world.ledger.records():
        item = record.item
        age = max(0.0, (world.clock.now() - item.valid_from).total_seconds())
        factors[item.version_ref] = {
            "lexical": 0.0, "vector": 0.0, "recency": 0.5 ** (age / PROFILE.recency_half_life_seconds),
            "confidence": item.confidence, "source_quality": quality[item.source_kind.value],
            "policy": min((taint.get(label, 1.0) for label in item.taint_labels), default=1.0),
        }
    return _oracle_rank(factors, top_k)


def test_r6_structured_returns_the_deterministic_top_k_of_a_large_eligible_set(backends: t52.Backends) -> None:
    world = backends.world()
    for n in range(130):
        world.admit(f"s-{n:03d}", f"structured record {n}", confidence=round(0.5 + (n % 37) / 100, 2),
                    valid_from=NOW - timedelta(minutes=10 + n % 11))
    first = search(world, RetrievalMode.STRUCTURED, top_k=10)
    assert len(first.hits) == 10
    assert refs(first) == _structured_oracle(world, 10)
    assert search(world, RetrievalMode.STRUCTURED, top_k=10).to_mapping() == first.to_mapping()
    clone = backends.fresh(world)
    again = clone.service().search(request(RetrievalMode.STRUCTURED, top_k=10, deadline=deadline(clone)), binding=binding())
    assert again.to_mapping() == first.to_mapping()
    assert [hit.final_score for hit in first.hits] == sorted((hit.final_score for hit in first.hits), reverse=True)


# --------------------------------------------------------------------------
# F1: predicates inside the backend query; head-only projections
# --------------------------------------------------------------------------


def _predicate(**changes: Any) -> Any:
    values: dict[str, Any] = {
        "memory_kinds": frozenset({"EPISODIC"}), "memory_scopes": frozenset({"PROJECT"}),
        "valid_at": NOW, "now": NOW,
    }
    values.update(changes)
    return stores.EligibilityPredicate(**values)


PREDICATE_CASES: list[tuple[str, dict[str, Any], dict[str, Any], bool]] = [
    # (label, admit kwargs, predicate changes, expected eligible)
    ("baseline", {}, {}, True),
    ("kind-other", {"kind": "PREFERENCE", "source_kind": "PREFERENCE", "taint": ("HUMAN_SUPPLIED",)}, {}, False),
    ("kind-requested", {"kind": "PREFERENCE", "source_kind": "PREFERENCE", "taint": ("HUMAN_SUPPLIED",)},
     {"memory_kinds": frozenset({"PREFERENCE"})}, True),
    ("scope-other", {}, {"memory_scopes": frozenset({"TEAM"})}, False),
    ("quarantined", {"lifecycle": "QUARANTINED"}, {}, False),
    ("proposed", {"lifecycle": "PROPOSED"}, {}, False),
    ("not-yet-valid", {"valid_from": NOW + timedelta(minutes=5)}, {}, False),
    ("valid-until-elapsed", {"valid_until": NOW + timedelta(minutes=1)},
     {"valid_at": NOW + timedelta(minutes=2), "now": NOW + timedelta(minutes=2)}, False),
    ("valid-until-boundary", {"valid_until": NOW + timedelta(minutes=1)}, {"valid_at": NOW + timedelta(minutes=1)}, False),
    ("valid-until-open", {"valid_until": NOW + timedelta(minutes=1)}, {"valid_at": NOW + timedelta(seconds=59)}, True),
    ("valid-from-boundary", {"valid_from": NOW - timedelta(days=2)}, {"valid_at": NOW - timedelta(days=2)}, True),
    ("valid-at-before-valid-from", {"valid_from": NOW - timedelta(days=2)},
     {"valid_at": NOW - timedelta(days=2, microseconds=1)}, False),
    ("expired", {"expires_at": NOW + timedelta(minutes=1)}, {"now": NOW + timedelta(minutes=1)}, False),
    ("unexpired", {"expires_at": NOW + timedelta(minutes=1)}, {"now": NOW + timedelta(seconds=59)}, True),
    ("source-filtered-out", {}, {"source_kinds": frozenset({"EVIDENCE"})}, False),
    ("source-filtered-in", {}, {"source_kinds": frozenset({"OBSERVATION"})}, True),
    ("schema-filtered-out", {}, {"content_schema_refs": frozenset({"urn:ocor:memory-content:plan:1.0"})}, False),
    ("schema-filtered-in", {}, {"content_schema_refs": frozenset({"urn:ocor:memory-content:episode:1.0"})}, True),
    ("confidence-below", {"confidence": 0.6}, {"min_confidence": 0.61}, False),
    ("confidence-equal", {"confidence": 0.6}, {"min_confidence": 0.6}, True),
    ("taint-excluded", {}, {"exclude_taint_labels": frozenset({"EXTERNAL_DATA"})}, False),
    ("taint-other-excluded", {}, {"exclude_taint_labels": frozenset({"MODEL_GENERATED"})}, True),
]


@pytest.mark.parametrize(("label", "admit", "changes", "eligible"), PREDICATE_CASES, ids=[c[0] for c in PREDICATE_CASES])
def test_every_predicate_branch_runs_inside_postgres_and_qdrant(
    backends: t52.Backends, label: str, admit: dict[str, Any], changes: dict[str, Any], eligible: bool
) -> None:
    world = backends.world()
    record = world.admit("probe", "harbour probe entry", **admit)
    where = _predicate(**changes)
    item = record.item
    assert where.accepts(stores.index_attributes(item)) is eligible  # reference semantics
    partition = MemoryPartition.for_item(item)
    lexical_version = LexicalProfile().representation_version
    vector_version = VectorProfile.for_item(item).representation_version
    lexical = world.lexical.inner.search_eligible(partition, lexical_version, "harbour probe", where=where, limit=10, offset=0)
    vector = world.vector.inner.search_eligible(partition, vector_version, embed("harbour probe entry"), where=where, limit=10, offset=0)
    structured = world.metadata.eligible_versions(partition.digest, where)
    assert (len(lexical), len(vector), len(structured)) == ((1, 1, 1) if eligible else (0, 0, 0)), label
    # The unfiltered backend query still sees the entry: the predicate is in the query.
    assert len(world.lexical.inner.search(partition, lexical_version, "harbour probe", limit=10, offset=0)) == 1
    assert len(world.vector.inner.search(partition, vector_version, embed("harbour probe entry"), limit=10, offset=0)) == 1


def test_a_commit_retires_its_predecessor_in_both_indexes_and_metadata(backends: t52.Backends) -> None:
    world = backends.world()
    v1 = world.admit("item", "fuel depot status")
    v2 = world.admit("item", "fuel depot status amended", version=2)
    partition = MemoryPartition.for_item(v1.item)
    lexical_version = LexicalProfile().representation_version
    vector_version = VectorProfile.for_item(v1.item).representation_version
    table = world.lexical.inner.table(partition, lexical_version)
    with world.metadata.connect() as conn:
        rows = dict(conn.execute(
            f'SELECT store_ref, (attributes->>\'superseded\')::boolean FROM "{world.metadata.schema}"."{table}"'
        ).fetchall())
    pointers = {
        v: next(p.store_ref for p in world.metadata.get("item", v).staged.pointers if p.representation_kind.value == "FULL_TEXT")
        for v in (1, 2)
    }
    assert rows == {pointers[1]: True, pointers[2]: False}
    status, data = world.vector.inner._call(
        "POST", f"/collections/{world.vector.inner.collection(partition, vector_version)}/points/scroll",
        {"limit": 100, "with_payload": True},
    )
    assert status == 200
    flags = {p["payload"]["pointer"]["memory_version_ref"]: p["payload"]["eligibility"]["superseded"] for p in data["result"]["points"]}
    assert flags == {v1.item.version_ref: True, v2.item.version_ref: False}
    where = _predicate()
    hits = world.vector.inner.search_eligible(partition, vector_version, embed("fuel depot status"), where=where, limit=10, offset=0)
    assert [h.payload["memory_version_ref"] for h in hits] == [v2.item.version_ref]
    assert [s.staged.memory_version for s in world.metadata.eligible_versions(partition.digest, where)] == [2]
    # The exact superseded version stays materialisable for history and replay.
    assert world.coordinator.read_version(partition, "item", 1).item.digest() == v1.item_digest


def test_a_non_active_head_is_never_searchable(backends: t52.Backends) -> None:
    world = backends.world()
    keep = world.admit("keep", "signal intercept summary")
    revoke = world.admit("revoke", "signal intercept summary")
    world.lifecycle(revoke, "REVOKED", "signal intercept summary")
    for mode in RetrievalMode:
        assert refs(search(world, mode, text="signal intercept summary")) == [keep.item.version_ref], mode


def test_a_reclassified_head_retires_the_predecessor_of_another_partition(backends: t52.Backends) -> None:
    world = backends.world()
    v1 = world.admit("item", "pipeline survey")
    world.admit("item", "pipeline survey", version=2, ctx=context(marking=t52.M_SECRET))
    old = MemoryPartition.for_item(v1.item)
    where = _predicate()
    version = LexicalProfile().representation_version
    assert world.lexical.inner.search_eligible(old, version, "pipeline survey", where=where, limit=5, offset=0) == []
    assert len(world.lexical.inner.search(old, version, "pipeline survey", limit=5, offset=0)) == 1


def test_lookups_inside_a_scope_fail_closed_on_an_index_without_predicates() -> None:
    world = t52.unit_world()
    world.admit("item-1", "alpha bravo")

    class Opaque:
        """A wrapper that forwards everything dynamically: not a declared version 2 index."""

        def __init__(self, inner: Any) -> None:
            self.inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

    world.coordinator._lexical = Opaque(world.coordinator._lexical)  # type: ignore[assignment]
    with pytest.raises(stores.MemoryStoreError) as caught:
        world.service().search(request(RetrievalMode.FULL_TEXT, text="alpha"), binding=binding())
    assert (caught.value.reason_code, caught.value.detail_code) == ("REPRESENTATION_NOT_READY", "INDEX_PREDICATES_UNSUPPORTED")
    assert denials(world) == [("REPRESENTATION_NOT_READY", "INDEX_PREDICATES_UNSUPPORTED")]
    # Outside a search scope the version 1 lookup keeps working (reconciliation, tests of 0051).
    partition = MemoryPartition.for_item(world.ledger.get("item-1", 1).item)  # type: ignore[union-attr]
    assert len(world.coordinator.lexical_candidates(partition, "alpha", limit=1)) == 1


def test_structured_fails_closed_on_a_metadata_store_without_predicates() -> None:
    world = t52.unit_world()
    world.admit("item-1", "alpha bravo")

    class Legacy:
        def __init__(self, inner: Any) -> None:
            self.inner = inner

        def __getattr__(self, name: str) -> Any:
            if name == "eligible_versions":
                raise AttributeError(name)
            return getattr(self.inner, name)

    service = world.service(metadata=Legacy(world.metadata))
    with pytest.raises(MemoryRetrievalError) as caught:
        service.search(request(RetrievalMode.STRUCTURED), binding=binding())
    assert caught.value.detail_code == "METADATA_PREDICATES_UNSUPPORTED"
    assert refs(world.service().search(request(RetrievalMode.STRUCTURED), binding=binding())) == ["urn:ocor:memory:item-1:v1"]


def test_a_lost_retirement_fails_closed_and_a_replayed_commit_repairs_it() -> None:
    world = t52.unit_world()
    world.admit("item", "alpha one")
    inner = world.lexical.inner
    original = inner.retire

    def outage(*args: Any) -> None:
        raise ConnectionError("index unavailable")

    inner.retire = outage
    with pytest.raises(stores.MemoryStoreError) as caught:
        world.admit("item", "alpha two", version=2)
    assert caught.value.detail_code == "PREDECESSOR_NOT_RETIRED"
    assert world.metadata.head("item") == 2  # committed: only the retirement was lost
    # The stale predecessor is still dropped by the post-query head check.
    assert refs(search(world, RetrievalMode.FULL_TEXT, text="alpha")) == ["urn:ocor:memory:item:v2"]
    inner.retire = original
    record = world.ledger.get("item", 2)
    assert record is not None
    world.coordinator.commit(record, payload=b"alpha two", embedding=embed("alpha two"))
    partition = MemoryPartition.for_item(record.item)
    attributes = inner.attributes_by_layout[(partition.digest, LexicalProfile().representation_version)]
    assert sorted((a["memory_version"], a["superseded"]) for a in attributes.values()) == [(1, True), (2, False)]


def test_the_reference_predicate_rejects_superseded_deleted_and_incomplete_attributes() -> None:
    world = t52.unit_world()
    attributes = stores.index_attributes(world.admit("item", "alpha bravo").item)
    where = _predicate()
    assert where.accepts(attributes)
    for change in ({"superseded": True}, {"deleted": True}, {"lifecycle_status": "REVOKED"}, {"memory_kind": "SEMANTIC"},
                   {"memory_scope": "TEAM"}, {"valid_from_us": str(attributes["valid_from_us"])}, {"taint_labels": "EXTERNAL_DATA"}):
        assert not where.accepts({**attributes, **change}), change
    for required in ("superseded", "deleted", "lifecycle_status", "memory_kind", "memory_scope",
                     "valid_from_us", "valid_until_us", "expires_at_us", "taint_labels"):
        assert not where.accepts({k: v for k, v in attributes.items() if k != required}), required


def _crash_metadata_commit(world: World) -> Any:
    original = world.metadata.commit

    def crash(*args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("metadata commit lost")

    world.metadata.commit = crash
    return original


def test_scoring_binds_every_pointer_to_a_committed_entry_of_the_partition() -> None:
    world = t52.unit_world()
    record = world.admit("item", "alpha bravo")
    partition = MemoryPartition.for_item(record.item)
    stored = world.metadata.get("item", 1)
    lexical = next(p for p in stored.staged.pointers if p.representation_kind.value == "FULL_TEXT")
    vector = next(p for p in stored.staged.pointers if p.representation_kind.value == "VECTOR")
    assert world.coordinator.lexical_scores(partition, "alpha", [lexical]) == {lexical.store_ref: 1.0}
    profile = VectorProfile.for_item(record.item)
    assert world.coordinator.vector_scores(partition, profile, embed("alpha bravo"), [vector])[vector.store_ref] == pytest.approx(1.0)
    original = _crash_metadata_commit(world)
    with pytest.raises(stores.MemoryStoreError):
        world.admit("pending", "alpha bravo")
    world.metadata.commit = original
    pending = world.metadata.get("pending", 1)
    assert pending is not None and pending.state.value == "PENDING"
    pending_lexical = next(p for p in pending.staged.pointers if p.representation_kind.value == "FULL_TEXT")
    other = MemoryPartition.for_item(world.admit("other", "alpha", ctx=context(compartments=("bravo",))).item)
    for call in (
        lambda: world.coordinator.lexical_scores(partition, "alpha", [pending_lexical]),  # not committed
        lambda: world.coordinator.lexical_scores(other, "alpha", [lexical]),  # another partition
        lambda: world.coordinator.lexical_scores(partition, "alpha", [vector]),  # another representation
    ):
        with pytest.raises(stores.MemoryStoreError) as caught:
            call()
        assert caught.value.detail_code == "POINTER_UNBOUND"
    world.lexical.inner.remove(partition, LexicalProfile().representation_version, lexical.store_ref)
    with pytest.raises(stores.MemoryStoreError) as caught:
        world.coordinator.lexical_scores(partition, "alpha", [lexical])
    assert caught.value.detail_code == "PROJECTION_DRIFT"


def test_reconciliation_retires_the_predecessor_of_a_rolled_forward_version() -> None:
    world = t52.unit_world()
    world.admit("item", "alpha one")
    original = _crash_metadata_commit(world)
    with pytest.raises(stores.MemoryStoreError):
        world.admit("item", "alpha two", version=2)
    world.metadata.commit = original
    record = world.ledger.get("item", 2)
    assert record is not None
    world.clock.advance(timedelta(minutes=6))
    report = world.coordinator.reconcile()
    assert report.completed == ("urn:ocor:memory:item:v2",)
    partition = MemoryPartition.for_item(record.item)
    attributes = world.lexical.inner.attributes_by_layout[(partition.digest, LexicalProfile().representation_version)]
    assert sorted((a["memory_version"], a["superseded"]) for a in attributes.values()) == [(1, True), (2, False)]


def test_backpressure_is_raised_only_by_the_declared_bound_on_post_query_drops(backends: t52.Backends) -> None:
    world = backends.world()
    for n in range(40):
        world.admit(f"quarantined-{n:02d}", "minefield marker", lifecycle="QUARANTINED")
    world.admit("active", "minefield marker")
    tight = {"limits": RetrievalLimits(max_candidates=2)}
    assert refs(search(world, RetrievalMode.HYBRID, text="minefield marker", service=tight)) == ["urn:ocor:memory:active:v1"]
    for n in range(20):
        world.admit(f"denied-{n:02d}", "minefield marker")
        world.policy.denied_items.add(f"denied-{n:02d}")
    assert refs(search(world, RetrievalMode.FULL_TEXT, text="minefield marker")) == ["urn:ocor:memory:active:v1"]
    refused(world, RetrievalMode.FULL_TEXT, "REPRESENTATION_NOT_READY", "RETRIEVAL_BACKPRESSURE",
            text="minefield marker", service={"limits": RetrievalLimits(max_candidates=16)})
    assert denials(world) == [("REPRESENTATION_NOT_READY", "RETRIEVAL_BACKPRESSURE")]


@pytest.mark.parametrize("denied", [0, 40, 130])
def test_f2_policy_denied_items_cost_no_more_index_work_than_before(backends: t52.Backends, denied: int, record_property: Any) -> None:
    """F2 is tracked towards FGM-16; the F1 correction must not make it worse.

    Baseline measured by the PO review on ``ae296eb``: 0, 40 and 130 denied
    items in an authorized partition cost 1, 6 and 15 index lookups, and 130
    fail with backpressure.
    """

    world = backends.world()
    world.admit("allowed", "ration convoy schedule")
    for n in range(denied):
        world.admit(f"denied-{n:03d}", "ration convoy schedule")
        world.policy.denied_items.add(f"denied-{n:03d}")
    baseline = {0: 1, 40: 6, 130: 15}[denied]
    try:
        response = search(world, RetrievalMode.FULL_TEXT, text="ration convoy schedule")
        outcome = refs(response)
    except MemoryRetrievalError as exc:
        outcome = [exc.detail_code]
    calls = len(lookups(world))
    record_property("f2_index_lookups", calls)
    record_property("f2_outcome", ",".join(outcome))
    assert calls <= baseline, (denied, calls)
    assert outcome == (["RETRIEVAL_BACKPRESSURE"] if denied == 130 else ["urn:ocor:memory:allowed:v1"])


# --------------------------------------------------------------------------
# F3: hybrid factors on the pool union
# --------------------------------------------------------------------------


def test_a_hybrid_candidate_found_by_one_index_is_scored_by_the_other(backends: t52.Backends) -> None:
    world = backends.world()
    world.admit("lex", "ammunition resupply window")
    world.admit("vec", "zzz unrelated words")
    query_vector = embed("zzz unrelated words")
    response = search(world, RetrievalMode.HYBRID, text="ammunition resupply", query_vector=query_vector)
    factors = {hit.memory_item_id: hit.score_factors for hit in response.hits}
    assert set(factors) == {"lex", "vec"}
    assert factors["lex"]["lexical"] == 1.0 and factors["vec"]["lexical"] == 0.0  # real: no lexical match
    assert factors["vec"]["vector"] == pytest.approx(1.0, abs=1e-5)
    assert factors["lex"]["vector"] == pytest.approx(
        max(0.0, _cosine(query_vector, embed("ammunition resupply window"))), abs=1e-5
    )
    scored = [c for c in world.lexical.calls + world.vector.calls if c[0] == "score_entries"]
    assert scored  # the missing factors came from the backends, not from a default


def test_a_hybrid_candidate_without_the_pinned_representation_is_not_ranked(backends: t52.Backends) -> None:
    world = backends.world()
    world.admit("with-vector", "observation post bravo")
    world.admit("no-vector", "observation post bravo", vector=False)
    assert sorted(refs(search(world, RetrievalMode.FULL_TEXT, text="observation post"))) == [
        "urn:ocor:memory:no-vector:v1", "urn:ocor:memory:with-vector:v1"
    ]
    hybrid = search(world, RetrievalMode.HYBRID, text="observation post", query_vector=embed("observation post bravo"))
    assert refs(hybrid) == ["urn:ocor:memory:with-vector:v1"]
    assert hybrid.hits[0].score_factors["vector"] == pytest.approx(1.0, abs=1e-5)


# --------------------------------------------------------------------------
# F4 and F5: stop epoch after the loop; every post-planning refusal is audited
# --------------------------------------------------------------------------


def test_a_stop_after_the_last_hit_or_with_no_hit_is_caught_before_the_receipt(backends: t52.Backends) -> None:
    world = backends.world()
    world.admit("only", "forward observer log")
    # Reads: plan, before the loop, after the hit, before the receipt.
    world.stop.bump_after = 3
    refused(world, RetrievalMode.FULL_TEXT, "STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED", text="forward observer")
    world.stop = t52.StopState(bump_after=2)  # no hit: plan, before the loop, before the receipt
    refused(world, RetrievalMode.FULL_TEXT, "STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED", text="nothingmatches")
    assert receipts(world) == [] and len(denials(world)) == 2
    world.stop = t52.StopState()
    assert refs(search(world, RetrievalMode.FULL_TEXT, text="forward observer")) == ["urn:ocor:memory:only:v1"]
    assert len(receipts(world)) == 1 and world.stop.reads == 4


def test_every_post_planning_refusal_is_an_audited_denial(backends: t52.Backends) -> None:
    world = backends.world()
    world.admit("item", "radio relay site")
    world.admit("other", "radio relay site")
    service = world.service()

    class MaterializationOutage(t52.GrantPolicy):
        def authorize_materialization(self, item: GovernedMemoryItem, ctx: GovernedContext) -> MemoryPolicyDecision:
            raise ConnectionError("opa unavailable")

    world.policy = MaterializationOutage()
    refused(world, RetrievalMode.FULL_TEXT, "CONTROL_PLANE_UNAVAILABLE", "POLICY_UNAVAILABLE", text="radio relay")
    world.policy = t52.GrantPolicy()
    original = world.coordinator.lexical_candidates

    def slow(partition: MemoryPartition, query: str, *, limit: int) -> Any:
        world.clock.advance(timedelta(seconds=31))  # the deadline passes during the lookup
        return original(partition, query, limit=limit)

    world.coordinator.lexical_candidates = slow  # type: ignore[method-assign]
    refused(world, RetrievalMode.FULL_TEXT, "POLICY_DENIED", "DEADLINE_EXCEEDED", text="radio relay")
    world.coordinator.lexical_candidates = original  # type: ignore[method-assign]
    world.audit.fail = True
    refused(world, RetrievalMode.FULL_TEXT, "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE", text="radio relay")
    world.audit.fail = False
    assert denials(world) == [("CONTROL_PLANE_UNAVAILABLE", "POLICY_UNAVAILABLE"), ("POLICY_DENIED", "DEADLINE_EXCEEDED")]
    assert receipts(world) == []
    response = service.search(request(RetrievalMode.FULL_TEXT, text="radio relay", deadline=deadline(world)), binding=binding())
    assert len(response.hits) == 2 and len(receipts(world)) == 1 and len(denials(world)) == 2
    for event in world.audit.events:
        assert event["correlation_id"] == base.CORRELATION and event["causation_id"] == "search-1"


# --------------------------------------------------------------------------
# F6: reason codes with positive and negative cases
# --------------------------------------------------------------------------


def test_f6_envelope_invalid(backends: t52.Backends) -> None:
    world = backends.world()
    world.admit("item", "supply drop zone")
    for changes in ({"operation_id": ""}, {"deadline": "tomorrow"}, {"governed_context_digest": 7}):
        body = request(RetrievalMode.FULL_TEXT, text="supply drop", **changes)
        with pytest.raises(MemoryRetrievalError) as caught:
            world.service().search(body, binding=binding())
        assert (caught.value.reason_code, caught.value.detail_code) == ("MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"), changes
    assert world.audit.events == [] and world.policy.calls == []
    assert refs(search(world, RetrievalMode.FULL_TEXT, text="supply drop")) == ["urn:ocor:memory:item:v1"]


def test_f6_gcs_invalid(backends: t52.Backends) -> None:
    world = backends.world()
    world.admit("item", "supply drop zone")
    body = request(RetrievalMode.FULL_TEXT, text="supply drop", governed_context=["not", "an", "object"])
    with pytest.raises(MemoryRetrievalError) as caught:
        world.service().search(body, binding=binding())
    assert (caught.value.reason_code, caught.value.detail_code) == ("GOVERNED_CONTEXT_MISMATCH", "GCS_INVALID")
    assert lookups(world) == []
    assert refs(search(world, RetrievalMode.FULL_TEXT, text="supply drop")) == ["urn:ocor:memory:item:v1"]


def test_f6_policy_decision_invalid_before_and_after_the_query(backends: t52.Backends) -> None:
    world = backends.world()
    world.admit("item", "supply drop zone")

    class NoRetrievalDecision(t52.GrantPolicy):
        def authorize_retrieval(self, request: SearchQuery, ctx: GovernedContext) -> RetrievalAuthorization:
            return {"permitted": True}  # type: ignore[return-value]

    class NoMaterializationDecision(t52.GrantPolicy):
        def authorize_materialization(self, item: GovernedMemoryItem, ctx: GovernedContext) -> MemoryPolicyDecision:
            return True  # type: ignore[return-value]

    world.policy = NoRetrievalDecision()
    refused(world, RetrievalMode.FULL_TEXT, "CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID", text="supply drop")
    assert lookups(world) == []  # pre-query: nothing was read
    world.policy = NoMaterializationDecision()
    refused(world, RetrievalMode.FULL_TEXT, "CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID", text="supply drop")
    assert lookups(world)  # post-query: refused after the lookup, before any content
    assert denials(world) == [("CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID")] * 2
    world.policy = t52.GrantPolicy()
    assert refs(search(world, RetrievalMode.FULL_TEXT, text="supply drop")) == ["urn:ocor:memory:item:v1"]


@pytest.mark.parametrize("epoch", [-1, True, "0", 1.0])
def test_f6_stop_state_invalid(backends: t52.Backends, epoch: Any) -> None:
    world = backends.world()
    world.admit("item", "supply drop zone")

    class Broken(t52.StopState):
        def current_epoch(self, ctx: GovernedContext) -> int:
            return epoch  # type: ignore[no-any-return]

    world.stop = Broken()
    refused(world, RetrievalMode.FULL_TEXT, "CONTROL_PLANE_UNAVAILABLE", "STOP_STATE_INVALID", text="supply drop")
    assert lookups(world) == []
    world.stop = t52.StopState(epoch=5)
    assert refs(search(world, RetrievalMode.FULL_TEXT, text="supply drop")) == ["urn:ocor:memory:item:v1"]


def test_f6_materialized_digest_mismatch(backends: t52.Backends) -> None:
    world = backends.world()
    world.admit("item", "supply drop zone")
    other = world.admit("other", "another record entirely")
    original = world.coordinator.read_version

    def substituted(partition: MemoryPartition, memory_item_id: str, memory_version: int) -> Any:
        return dataclasses.replace(original(partition, memory_item_id, memory_version), item=other.item)

    world.coordinator.read_version = substituted  # type: ignore[method-assign]
    refused(world, RetrievalMode.FULL_TEXT, "INTERNAL_ERROR", "MATERIALIZED_DIGEST_MISMATCH", text="supply drop")
    assert receipts(world) == [] and denials(world) == [("INTERNAL_ERROR", "MATERIALIZED_DIGEST_MISMATCH")]
    world.coordinator.read_version = original  # type: ignore[method-assign]
    assert refs(search(world, RetrievalMode.FULL_TEXT, text="supply drop")) == ["urn:ocor:memory:item:v1"]


def test_f6_stale_policy_at_materialisation(backends: t52.Backends) -> None:
    world = backends.world()
    world.admit("item", "supply drop zone")

    class StaleAtMaterialisation(t52.GrantPolicy):
        def authorize_materialization(self, item: GovernedMemoryItem, ctx: GovernedContext) -> MemoryPolicyDecision:
            decision = super().authorize_materialization(item, ctx)
            return dataclasses.replace(decision, policy_bundle_digest=d("policy-bundle:memory:0"))

    world.policy = StaleAtMaterialisation()
    refused(world, RetrievalMode.HYBRID, "STALE_POLICY", "POLICY_BUNDLE_MISMATCH", text="supply drop")
    assert denials(world) == [("STALE_POLICY", "POLICY_BUNDLE_MISMATCH")]
    world.policy = t52.GrantPolicy()
    assert refs(search(world, RetrievalMode.HYBRID, text="supply drop")) == ["urn:ocor:memory:item:v1"]


def test_f6_deadline_after_ranking(backends: t52.Backends) -> None:
    world = backends.world()
    world.admit("item", "supply drop zone")
    original = world.coordinator.vector_candidates

    def slow(*args: Any, **kwargs: Any) -> Any:
        world.clock.advance(timedelta(seconds=10))
        return original(*args, **kwargs)

    world.coordinator.vector_candidates = slow  # type: ignore[method-assign]
    refused(world, RetrievalMode.VECTOR, "POLICY_DENIED", "DEADLINE_EXCEEDED", text="supply drop zone", deadline=deadline(world, 5))
    assert receipts(world) == [] and denials(world) == [("POLICY_DENIED", "DEADLINE_EXCEEDED")]
    assert refs(search(world, RetrievalMode.VECTOR, text="supply drop zone", deadline=deadline(world, 30)))[0] == "urn:ocor:memory:item:v1"


def test_f6_a_hit_without_explanation(backends: t52.Backends) -> None:
    world = backends.world()
    world.admit("item", "supply drop zone")
    bare = search(world, RetrievalMode.HYBRID, text="supply drop", include_explanation=False)
    assert refs(bare) == ["urn:ocor:memory:item:v1"]
    assert bare.hits[0].explanation_ref is None and bare.explanations == {}
    assert "explanation_ref" not in bare.hits[0].to_mapping()
    explained = search(world, RetrievalMode.HYBRID, text="supply drop")
    ref = explained.hits[0].explanation_ref
    assert ref is not None and ref in explained.explanations and explained.hits[0].to_mapping()["explanation_ref"] == ref
    assert bare.query_digest != explained.query_digest


def test_f6_a_historical_valid_at_returns_the_version_valid_then(backends: t52.Backends) -> None:
    world = backends.world()
    world.admit("past", "checkpoint roster", valid_from=NOW - timedelta(days=3), valid_until=NOW + timedelta(hours=1))
    world.admit("current", "checkpoint roster", valid_from=NOW + timedelta(minutes=30))
    world.clock.advance(timedelta(hours=2))  # "past" is no longer valid, "current" now is
    historic = format_utc_timestamp(NOW)
    for mode in RetrievalMode:
        assert refs(search(world, mode, text="checkpoint roster", valid_at=historic)) == ["urn:ocor:memory:past:v1"], mode
        assert refs(search(world, mode, text="checkpoint roster")) == ["urn:ocor:memory:current:v1"], mode


def test_qualifying_worlds_use_the_real_version_2_adapters(backends: t52.Backends) -> None:
    world = backends.world()
    assert isinstance(world.lexical.inner, base.PostgresLexicalIndex)
    assert isinstance(world.vector.inner, base.QdrantVectorIndex)
    assert isinstance(world.metadata, base.PostgresStores) and isinstance(world.cipher, base.OpenBaoTransitCipher)
    for port in (world.lexical, world.vector, world.lexical.inner, world.vector.inner):
        assert isinstance(port, stores.EligibilityIndexPort)
    assert isinstance(world.metadata, stores.EligibilityMetadataStore)
