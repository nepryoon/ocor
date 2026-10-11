"""OCOR-DEV-0054: Implement consolidation reflection dissent and correction.

Acceptance (backlog): derived memories cite immutable sources and preserve
conflicts/dissent without silent majority merge.  Negative: correction cannot
rewrite source, erase dissent or become authority; a SKIPPED, UNAVAILABLE,
mock-only or NOT_EXECUTED qualifying case is not accepted.

Oracles: ADD v1.3 Part II §2.4 (memory never becomes Authority, Approval,
Decision, CapabilityLease or canonical state; derived knowledge is not
truth), §2.5 (immutable versions; consolidation, reflection and correction
create new versions linked by ``consolidates_refs``, ``derived_from_refs``,
``supersedes_ref`` and ``correction_of_ref``), §2.9 (explicit job with input
query/digest, algorithm/model pins, purpose, budget, target kind/scope and
reviewer policy; new derived item with complete lineage and uncertainty;
sources immutable; contradictions produce conflict/dissent artifacts;
frequency or majority does not erase dissent; reflection tainted and
instruction-ineligible; automatic consolidation only for approved profiles and
never promoting to canonical state or activating procedures) and §2.12
(provenance laundering, dissent suppression, malicious consolidation); LLD
v1.1 §§2.8.1, 2.8.2, 2.8.5 and §7.2 (``FGM-03``, ``FGM-09``, ``FGM-13``).

Qualifying cases run on the real, pinned backends of OCOR-DEV-0051 reused by
OCOR-DEV-0052: PostgreSQL 16 from ``OCOR_LIVE_POSTGRES_DSN`` (metadata,
encrypted content, full-text index, one schema per world), Qdrant 1.15.1
(vector index port, one namespace per world) and OpenBao 2.6.2 transit.  Every
input and derived version goes through the real OCOR-DEV-0050 admission
service and the real OCOR-DEV-0051 store coordinator; content is read back
decrypted from PostgreSQL through the coordinator.  A missing backend fails,
it never skips.  The unit cases use the 0051 in-memory port fixtures only for
envelope, profile and pure-algorithm branch logic; none of them is qualifying.
"""

from __future__ import annotations

import ast
import json
import os
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
import test_ocor_dev_0051 as base
import test_ocor_dev_0052 as r
import yaml
from jsonschema import Draft202012Validator
from ocor_runtime.kernel.canonical import canonical_digest, format_utc_timestamp
from ocor_runtime.kernel.governed_context import GovernedContext
from ocor_runtime.memory.consolidation import (
    CLAIM_MERGE,
    CONSOLIDATION_REQUEST_FIELDS,
    CORRECTION_REQUEST_FIELDS,
    ClaimSource,
    ConsolidationAlgorithm,
    ConsolidationGuardPolicy,
    ConsolidationLedgerCorrupted,
    ConsolidationOutcome,
    ConsolidationProfile,
    ConsolidationProfileRegistry,
    ConsolidationReferenceResolver,
    InMemoryConsolidationJobLedger,
    JournalConsolidationJobLedger,
    MemoryConsolidationError,
    MemoryConsolidationJob,
    MemoryConsolidationService,
    bounded_confidence,
    merge_claims,
    parse_assertions,
)
from ocor_runtime.memory.model import (
    PROBLEM_REASON_CODES,
    AdmissionLimits,
    AdmittedMemoryVersion,
    GovernedMemoryItem,
    LifecycleStatus,
    MemoryAdmissionError,
    MemoryAdmissionService,
    MemoryKind,
    MemoryPolicyDecision,
    memory_version_ref,
    parse_memory_version_ref,
)
from ocor_runtime.memory.stores import MemoryPartition

REPO = Path(__file__).resolve().parents[3]
MODULE = REPO / "ocor-runtime/src/ocor_runtime/memory/consolidation.py"
OPENAPI = yaml.safe_load(
    (REPO / "reports/contracts/ocor-governed-memory.openapi.yaml").read_text(encoding="utf-8")
)
NOW = base.NOW
d = base.d
AUTO = "urn:ocor:memory-reviewer:automatic-approved-profile:1.0"
HUMAN = "urn:ocor:memory-reviewer:human-review:1.0"
QUERY = d("memory-query:convoy-sector-summary:1")
AUTO_PROFILE = ConsolidationProfile(
    profile_ref="urn:ocor:memory-consolidation-profile:claim-merge-automatic:1.0",
    algorithm=CLAIM_MERGE,
    target_kinds=frozenset({MemoryKind.EPISODIC, MemoryKind.SEMANTIC, MemoryKind.REFLECTION}),
    reviewer_policies={AUTO: LifecycleStatus.ACTIVE},
    retention_policy_ref="retention:standard",
    automatic=True,
    max_inputs=8,
    max_input_bytes=4096,
)
REVIEW_PROFILE = ConsolidationProfile(
    profile_ref="urn:ocor:memory-consolidation-profile:claim-merge-reviewed:1.0",
    algorithm=CLAIM_MERGE,
    target_kinds=frozenset({MemoryKind.EPISODIC, MemoryKind.SEMANTIC}),
    reviewer_policies={HUMAN: LifecycleStatus.PROPOSED},
    retention_policy_ref="retention:standard",
)
PROFILES = ConsolidationProfileRegistry([AUTO_PROFILE, REVIEW_PROFILE])
CTX = r.context()
PROJECT = {"project_id": "project-1"}
RUN = {"agent_run_id": "run-1"}


def claims(*triples: tuple[str, str, object]) -> str:
    return json.dumps(
        {"assertions": [{"subject": s, "attribute": a, "value": v} for s, a, v in triples]},
        sort_keys=True,
    )


# --------------------------------------------------------------------------
# Test ports (explicit fixtures, never a mock of the consolidation boundary)
# --------------------------------------------------------------------------


@dataclass
class ConsolidationGrant:
    """Live consolidation policy double: explicit decisions, recorded calls."""

    permitted: bool = True
    correction_permitted: bool = True
    bundle: str | None = None
    fail: bool = False
    invalid: bool = False
    on_call: Any = None
    calls: list[str] = field(default_factory=list)

    def _decision(self, ref: str, ctx: GovernedContext, permitted: bool) -> MemoryPolicyDecision:
        if self.on_call is not None:
            self.on_call()
        if self.fail:
            raise ConnectionError("opa unavailable")
        if self.invalid:
            return {"permitted": True}  # type: ignore[return-value]
        return MemoryPolicyDecision(
            permitted=permitted,
            decision_ref=f"decision:{ref}",
            policy_bundle_digest=self.bundle or ctx.policy_bundle_digest,
        )

    def authorize_consolidation(self, job: MemoryConsolidationJob, ctx: GovernedContext) -> MemoryPolicyDecision:
        self.calls.append(f"consolidate:{job.job_ref}")
        return self._decision(f"consolidation:{job.digest}", ctx, self.permitted)

    def authorize_correction(self, target: GovernedMemoryItem, ctx: GovernedContext) -> MemoryPolicyDecision:
        self.calls.append(f"correct:{target.version_ref}")
        return self._decision(f"correction:{target.version_ref}", ctx, self.correction_permitted)


class CountingContent:
    """Content-store port wrapper that counts reads and can fail selected writes."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.gets = 0
        self.puts = 0
        self.fail_put_numbers: set[int] = set()

    def put(self, object_ref: str, partition_digest: str, sealed: Any) -> None:
        self.puts += 1
        if self.puts in self.fail_put_numbers:
            raise OSError("injected content-store write failure")
        self.inner.put(object_ref, partition_digest, sealed)

    def get(self, object_ref: str) -> Any:
        self.gets += 1
        return self.inner.get(object_ref)

    def delete(self, object_ref: str) -> None:
        self.inner.delete(object_ref)

    def refs(self, partition_digest: str) -> tuple[str, ...]:
        return tuple(self.inner.refs(partition_digest))


class FailingJobs(InMemoryConsolidationJobLedger):
    def __init__(self) -> None:
        super().__init__()
        self.failures = 0

    def append(self, record: Any) -> None:
        if self.failures:
            self.failures -= 1
            raise OSError("injected job-ledger failure")
        super().append(record)


class CWorld(r.World):
    """The 0052 world (real admission + real coordinator) wired for consolidation."""

    def __init__(self, *, content: Any, jobs: Any = None, **ports: Any) -> None:
        self.counting = CountingContent(content)
        super().__init__(content=self.counting, **ports)
        self.references = ConsolidationReferenceResolver(r.Resolver())
        self.guard = ConsolidationGuardPolicy(base.Policy(), ledger=self.ledger)
        self.admission = MemoryAdmissionService(
            ledger=self.ledger,
            resolver=self.references,
            policy=self.guard,
            markings=self.markings,
            clock=self.clock,
            limits=AdmissionLimits(retention_horizons={"retention:standard": timedelta(days=365)}),
        )
        self.grant = ConsolidationGrant()
        self.jobs = jobs if jobs is not None else InMemoryConsolidationJobLedger()
        self.consolidation_audit = r.Audit()

    def consolidator(self, **overrides: Any) -> MemoryConsolidationService:
        arguments: dict[str, Any] = {
            "admission": self.admission,
            "ledger": self.ledger,
            "coordinator": self.coordinator,
            "references": self.references,
            "guard": self.guard,
            "policy": self.grant,
            "markings": self.markings,
            "profiles": PROFILES,
            "jobs": self.jobs,
            "audit": self.consolidation_audit,
            "clock": self.clock,
        }
        arguments.update(overrides)
        return MemoryConsolidationService(**arguments)

    def source(self, item_id: str, *triples: tuple[str, str, object], **kwargs: Any) -> AdmittedMemoryVersion:
        kwargs.setdefault("vector", False)
        kwargs.setdefault("bindings", PROJECT)
        return self.admit(item_id, claims(*triples), **kwargs)

    def snapshot(self, refs: Sequence[str]) -> dict[str, tuple[str, str, int]]:
        """Item digest, stored payload digest and head of each exact version."""

        result: dict[str, tuple[str, str, int]] = {}
        for ref in refs:
            item_id, version = parse_memory_version_ref(ref)
            record = self.ledger.get(item_id, version)
            assert record is not None
            stored = self.coordinator.read_version(MemoryPartition.for_item(record.item), item_id, version)
            result[ref] = (record.item_digest, d(stored.payload), self.ledger.latest_version(item_id))
        return result

    def item(self, ref: str) -> AdmittedMemoryVersion:
        item_id, version = parse_memory_version_ref(ref)
        record = self.ledger.get(item_id, version)
        assert record is not None
        return record

    def payload(self, ref: str) -> dict[str, Any]:
        record = self.item(ref)
        stored = self.coordinator.read_version(
            MemoryPartition.for_item(record.item), record.item.memory_item_id, record.item.memory_version
        )
        value = json.loads(stored.payload)
        assert isinstance(value, dict)
        return value


def consolidation_request(
    refs: Sequence[str],
    *,
    op: str = "op-consolidate-1",
    ctx: GovernedContext = CTX,
    kind: str = "EPISODIC",
    scope: str = "PROJECT",
    reviewer: str = AUTO,
    algorithm: ConsolidationAlgorithm = CLAIM_MERGE,
    deadline: timedelta = timedelta(seconds=30),
    clock_now: Any = NOW,
) -> dict[str, Any]:
    return {
        "operation_id": op,
        "governed_context": ctx.to_mapping(),
        "governed_context_digest": ctx.digest(),
        "deadline": format_utc_timestamp(clock_now + deadline),
        "input_query_digest": QUERY,
        "input_item_refs": list(refs),
        "algorithm_ref": algorithm.algorithm_ref,
        "algorithm_digest": algorithm.algorithm_digest,
        "target_memory_kind": kind,
        "target_memory_scope": scope,
        "reviewer_policy_ref": reviewer,
    }


def correction_request(
    target: str,
    statements: Sequence[Mapping[str, object]],
    *,
    op: str = "op-correct-1",
    ctx: GovernedContext = CTX,
    clock_now: Any = NOW,
) -> dict[str, Any]:
    return {
        "operation_id": op,
        "governed_context": ctx.to_mapping(),
        "governed_context_digest": ctx.digest(),
        "deadline": format_utc_timestamp(clock_now + timedelta(seconds=30)),
        "target_version_ref": target,
        "corrected_statements": [dict(s) for s in statements],
        "correction_reason_ref": "urn:ocor:memory-correction-reason:operator-report:1",
    }


def refused(action: Any, reason: str, detail: str) -> MemoryAdmissionError:
    with pytest.raises(MemoryAdmissionError) as caught:
        action()
    assert (caught.value.reason_code, caught.value.detail_code) == (reason, detail), str(caught.value)
    assert caught.value.reason_code in PROBLEM_REASON_CODES
    return caught.value


def denials(world: CWorld) -> list[Mapping[str, object]]:
    return [e for e in world.consolidation_audit.events if e.get("outcome") == "DENIED"]


def unit_world(**kwargs: Any) -> CWorld:
    return CWorld(
        metadata=base.MemMetadata(),
        content=base.MemContent(),
        lexical=base.MemIndex(),
        vector=base.MemIndex(),
        cipher=base.FixtureCipher(),
        **kwargs,
    )


# --------------------------------------------------------------------------
# Real backends (qualifying): PostgreSQL, Qdrant and OpenBao via the 0051 adapters
# --------------------------------------------------------------------------


class OpenBaoHarness(base.OpenBaoHarness):
    PREFIX = "ocor-test-0054-openbao-"


@dataclass
class Backends:
    dsn: str
    qdrant: Any
    bao: OpenBaoHarness
    schemas: list[str] = field(default_factory=list)

    def release(self) -> None:
        try:
            with psycopg.connect(self.dsn, autocommit=True) as conn:
                for schema in self.schemas:
                    conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            for schema in self.schemas:
                index = r.CompactQdrantVectorIndex(self.qdrant.endpoint, schema)
                for name in index.collections():
                    status, _ = index._call("DELETE", f"/collections/{name}")
                    assert status == 200, (name, status)
            self.schemas.clear()

    def _ports(self, schema: str) -> dict[str, Any]:
        postgres = base.PostgresStores(self.dsn, schema)
        return {
            "metadata": postgres,
            "content": base.PostgresContentStore(postgres),
            "lexical": base.PostgresLexicalIndex(postgres),
            "vector": r.CompactQdrantVectorIndex(self.qdrant.endpoint, schema),
            "cipher": base.OpenBaoTransitCipher(self.bao),
        }

    def world(self, **kwargs: Any) -> CWorld:
        schema = f"ocor_t0054_{uuid.uuid4().hex[:12]}"
        self.schemas.append(schema)
        return CWorld(**self._ports(schema), **kwargs)

    def fresh(self, world: CWorld, **kwargs: Any) -> CWorld:
        """New adapters and connections over the same backends and ledger (a new run)."""

        clone = CWorld(**self._ports(world.metadata.schema), **kwargs)
        clone.ledger = world.ledger
        clone.clock = world.clock
        clone.guard = ConsolidationGuardPolicy(base.Policy(), ledger=world.ledger)
        clone.admission = MemoryAdmissionService(
            ledger=world.ledger,
            resolver=clone.references,
            policy=clone.guard,
            markings=clone.markings,
            clock=world.clock,
            limits=AdmissionLimits(retention_horizons={"retention:standard": timedelta(days=365)}),
        )
        clone.coordinator = r.MemoryStoreCoordinator(
            ledger=world.ledger,
            metadata=clone.metadata,
            content=clone.counting,
            cipher=clone.cipher,
            lexical=clone.lexical,
            vector=clone.vector,
            clock=world.clock,
        )
        return clone


@pytest.fixture(scope="module")
def live_backends() -> Iterator[Backends]:
    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory qualifying evidence (real PostgreSQL)")
    qdrant = base.QdrantHarness.provision()
    bao: OpenBaoHarness | None = None
    state: Backends | None = None
    try:
        bao = OpenBaoHarness.provision()
        state = Backends(dsn=dsn, qdrant=qdrant, bao=bao)
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
def backends(live_backends: Backends) -> Iterator[Backends]:
    try:
        yield live_backends
    finally:
        live_backends.release()


@pytest.fixture
def live(backends: Backends) -> CWorld:
    return backends.world()


def convoy_sources(world: CWorld) -> list[AdmittedMemoryVersion]:
    """Six reports: unanimous on the sector, five 'open' against one 'closed' bridge."""

    records = []
    for n in range(6):
        status = "closed" if n == 5 else "open"
        records.append(
            world.source(
                f"report-{n}",
                ("bridge-7", "sector", "north"),
                ("bridge-7", "status", status),
                confidence=0.6 if n == 2 else 0.9,
            )
        )
    return records


def refs_of(records: Sequence[AdmittedMemoryVersion]) -> list[str]:
    return [record.item.version_ref for record in records]


# --------------------------------------------------------------------------
# Pure algorithm and profiles (unit branch logic)
# --------------------------------------------------------------------------


def _claim_source(ref: str, *triples: tuple[str, str, object], confidence: float = 0.9) -> ClaimSource:
    return ClaimSource(
        version_ref=ref,
        item_digest=d(f"item:{ref}"),
        content_digest=d(f"content:{ref}"),
        confidence=confidence,
        assertions=tuple(triples),
    )


def test_claim_merge_preserves_every_alternative_and_never_votes() -> None:
    sources = [_claim_source(f"urn:ocor:memory:s{n}:v1", ("b", "status", "open")) for n in range(5)]
    sources.append(_claim_source("urn:ocor:memory:s5:v1", ("b", "status", "closed")))
    merged = merge_claims(sources)
    assert merged.statements == ()
    (conflict,) = merged.conflicts
    assert conflict["resolution"] == "UNRESOLVED"
    alternatives = conflict["alternatives"]
    assert [a["value"] for a in alternatives] == ["closed", "open"]  # by value, not by support
    assert [a["support_count"] for a in alternatives] == [1, 5]
    assert alternatives[0]["support_refs"] == ["urn:ocor:memory:s5:v1"]


def test_claim_merge_is_deterministic_under_permutation_and_cites_every_support() -> None:
    sources = [
        _claim_source("urn:ocor:memory:a:v1", ("x", "k", 1), ("y", "k", True)),
        _claim_source("urn:ocor:memory:b:v1", ("x", "k", 1), ("y", "k", False)),
        _claim_source("urn:ocor:memory:c:v1", ("y", "k", None), ("z", "k", "w")),
    ]
    first = merge_claims(sources)
    second = merge_claims(list(reversed(sources)))
    assert first == second
    assert [dict(s) for s in first.statements] == [
        {"subject": "x", "attribute": "k", "value": 1, "support_refs": ["urn:ocor:memory:a:v1", "urn:ocor:memory:b:v1"]},
        {"subject": "z", "attribute": "k", "value": "w", "support_refs": ["urn:ocor:memory:c:v1"]},
    ]
    (conflict,) = first.conflicts
    assert len(conflict["alternatives"]) == 3  # three-way disagreement kept whole


def test_a_self_contradicting_source_is_a_conflict_not_a_statement() -> None:
    merged = merge_claims([_claim_source("urn:ocor:memory:a:v1", ("x", "k", 1), ("x", "k", 2))])
    assert merged.statements == () and len(merged.conflicts) == 1


@pytest.mark.parametrize(
    ("minimum", "statements", "conflicts"),
    [(0.9, 1, 0), (0.6, 1, 1), (0.333333333, 2, 1), (1.0, 0, 3), (0.7, 7, 0)],
)
def test_bounded_confidence_never_exceeds_the_weakest_input(minimum: float, statements: int, conflicts: int) -> None:
    value = bounded_confidence(minimum, statements, conflicts)
    assert 0 <= value <= minimum
    if conflicts:
        assert value < minimum or minimum == 0


@pytest.mark.parametrize(
    "payload",
    [
        b"patrol report at dawn",
        b'{"assertions": []}',
        b'{"assertions": [{"subject": "a", "attribute": "b"}]}',
        b'{"assertions": [{"subject": "a", "attribute": "b", "value": 1, "extra": 2}]}',
        b'{"assertions": [{"subject": "a", "attribute": "b", "value": {"nested": 1}}]}',
        b'{"assertions": [{"subject": "", "attribute": "b", "value": 1}]}',
        b'{"assertions": [], "note": "x"}',
        b'{"assertions": [{"subject": "a", "subject": "b", "attribute": "c", "value": 1}]}',
    ],
)
def test_unparseable_inputs_are_refused(payload: bytes) -> None:
    refused(lambda: parse_assertions(payload), "MEMORY_SCHEMA_INVALID", "CONSOLIDATION_INPUT_UNPARSEABLE")


def test_a_well_formed_input_parses() -> None:
    assert parse_assertions(claims(("a", "b", 1)).encode()) == (("a", "b", 1),)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"target_kinds": frozenset({MemoryKind.PROCEDURAL})}, "targets"),
        ({"target_kinds": frozenset({MemoryKind.WORKING})}, "targets"),
        ({"target_kinds": frozenset({MemoryKind.DISSENT})}, "targets"),
        ({"target_kinds": frozenset()}, "targets"),
        ({"reviewer_policies": {AUTO: LifecycleStatus.ACTIVE}, "automatic": False}, "automatic"),
        ({"reviewer_policies": {AUTO: LifecycleStatus.QUARANTINED}}, "ACTIVE or PROPOSED"),
        ({"reviewer_policies": {}}, "reviewer"),
        ({"algorithm": ConsolidationAlgorithm("urn:ocor:memory-consolidation-algorithm:llm:1.0", {"x": 1})}, "implemented"),
        ({"algorithm": ConsolidationAlgorithm(CLAIM_MERGE.algorithm_ref, {"tampered": True})}, "implemented"),
        ({"max_inputs": 0}, "positive"),
    ],
)
def test_only_approved_profile_shapes_can_be_declared(changes: dict[str, Any], message: str) -> None:
    values: dict[str, Any] = {
        "profile_ref": "urn:ocor:memory-consolidation-profile:test:1.0",
        "algorithm": CLAIM_MERGE,
        "target_kinds": frozenset({MemoryKind.EPISODIC}),
        "reviewer_policies": {HUMAN: LifecycleStatus.PROPOSED},
        "retention_policy_ref": "retention:standard",
    }
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        ConsolidationProfile(**values)


def test_a_reviewer_policy_cannot_be_ambiguous_across_profiles() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        ConsolidationProfileRegistry([AUTO_PROFILE, AUTO_PROFILE])


def test_the_request_and_receipt_follow_the_openapi_contract() -> None:
    schemas = OPENAPI["components"]["schemas"]
    envelope = schemas["GovernedEnvelope"]
    request = schemas["MemoryConsolidationRequest"]["allOf"][1]
    assert schemas["MemoryConsolidationRequest"]["unevaluatedProperties"] is False
    assert CONSOLIDATION_REQUEST_FIELDS == frozenset(envelope["properties"]) | frozenset(request["properties"])
    assert CONSOLIDATION_REQUEST_FIELDS == frozenset(envelope["required"]) | frozenset(request["required"])
    assert OPENAPI["paths"]["/v1/memory/consolidations"]["post"]["operationId"] == "consolidateMemory"
    assert {"operation_id", "governed_context", "governed_context_digest", "deadline"} <= CORRECTION_REQUEST_FIELDS
    receipt_schema = json.loads(
        json.dumps(schemas["OperationReceipt"]).replace("#/components/schemas/Digest", "#/$defs/Digest")
    )
    receipt_schema["$defs"] = {"Digest": schemas["Digest"]}
    world = unit_world()
    records = convoy_sources(world)
    outcome = world.consolidator().consolidate(consolidation_request(refs_of(records)), binding=r.binding(CTX))
    Draft202012Validator(receipt_schema).validate(dict(outcome.receipt))
    assert outcome.receipt["operation_kind"] == "consolidateMemory"
    assert outcome.receipt["status"] == "COMPLETED"
    problem = MemoryConsolidationError("POLICY_DENIED", "X", "y").to_problem()
    assert problem["reason_code"] in schemas["Problem"]["properties"]["reason_code"]["enum"]


# --------------------------------------------------------------------------
# Envelope, profile and policy branches (unit branch logic)
# --------------------------------------------------------------------------


def _without(body: dict[str, Any], name: str) -> dict[str, Any]:
    body = dict(body)
    del body[name]
    return body


ENVELOPE_CASES = [
    ("missing field", lambda b: _without(b, "reviewer_policy_ref"), "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("extra field", lambda b: {**b, "budget": 3}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("empty refs", lambda b: {**b, "input_item_refs": []}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("duplicate refs", lambda b: {**b, "input_item_refs": b["input_item_refs"][:1] * 2}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("refs not array", lambda b: {**b, "input_item_refs": "urn:ocor:memory:x:v1"}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("bad query digest", lambda b: {**b, "input_query_digest": "sha256:abc"}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("bad algorithm digest", lambda b: {**b, "algorithm_digest": "x"}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("unknown kind", lambda b: {**b, "target_memory_kind": "FACT"}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("unknown scope", lambda b: {**b, "target_memory_scope": "GLOBAL"}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("empty operation", lambda b: {**b, "operation_id": ""}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("bad deadline", lambda b: {**b, "deadline": "tomorrow"}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("elapsed deadline", lambda b: {**b, "deadline": format_utc_timestamp(NOW)}, "POLICY_DENIED", "DEADLINE_EXCEEDED"),
    ("gcs not object", lambda b: {**b, "governed_context": "ctx"}, "GOVERNED_CONTEXT_MISMATCH", "GCS_INVALID"),
    ("gcs digest mismatch", lambda b: {**b, "governed_context_digest": d("other")}, "GOVERNED_CONTEXT_MISMATCH", None),
    ("gcs of another principal", lambda b: {**b, "governed_context": r.context(principal="agent-principal-2").to_mapping()}, "GOVERNED_CONTEXT_MISMATCH", None),
    ("procedural target", lambda b: {**b, "target_memory_kind": "PROCEDURAL"}, "UNSUPPORTED_CAPABILITY", "CONSOLIDATION_TARGET_UNSUPPORTED"),
    ("working target", lambda b: {**b, "target_memory_kind": "WORKING"}, "UNSUPPORTED_CAPABILITY", "CONSOLIDATION_TARGET_UNSUPPORTED"),
    ("dissent target", lambda b: {**b, "target_memory_kind": "DISSENT"}, "UNSUPPORTED_CAPABILITY", "CONSOLIDATION_TARGET_UNSUPPORTED"),
    ("unknown algorithm", lambda b: {**b, "algorithm_ref": "urn:ocor:memory-consolidation-algorithm:llm-summary:1.0"}, "UNSUPPORTED_CAPABILITY", "ALGORITHM_NOT_APPROVED"),
    ("algorithm digest drift", lambda b: {**b, "algorithm_digest": d("claim-merge:2")}, "POLICY_DENIED", "ALGORITHM_DIGEST_MISMATCH"),
    ("unknown reviewer", lambda b: {**b, "reviewer_policy_ref": "urn:ocor:memory-reviewer:none"}, "POLICY_DENIED", "REVIEWER_POLICY_NOT_APPROVED"),
    ("kind outside profile", lambda b: {**b, "reviewer_policy_ref": HUMAN, "target_memory_kind": "REFLECTION"}, "UNSUPPORTED_CAPABILITY", "TARGET_KIND_NOT_APPROVED"),
]


@pytest.mark.parametrize(("label", "change", "reason", "detail"), ENVELOPE_CASES, ids=[c[0] for c in ENVELOPE_CASES])
def test_invalid_jobs_are_refused_audited_and_write_nothing(label: str, change: Any, reason: str, detail: str | None) -> None:
    world = unit_world()
    records = convoy_sources(world)
    before = len(world.ledger.records())
    gets = world.counting.gets
    service = world.consolidator()
    body = change(consolidation_request(refs_of(records)))
    with pytest.raises(MemoryAdmissionError) as caught:
        service.consolidate(body, binding=r.binding(CTX))
    assert caught.value.reason_code == reason
    if detail is not None:
        assert caught.value.detail_code == detail
    assert len(world.ledger.records()) == before
    assert world.counting.gets == gets
    assert world.grant.calls == []
    (event,) = denials(world)
    assert event["reason_code"] == reason and event["correlation_id"] == CTX.correlation_id
    assert world.jobs.records() == ()


def test_a_missing_or_foreign_binding_is_refused_and_audited() -> None:
    world = unit_world()
    records = convoy_sources(world)
    body = consolidation_request(refs_of(records))
    refused(lambda: world.consolidator().consolidate(body, binding=None), "AUTHENTICATION_REQUIRED", "BINDING_MISSING")
    refused(lambda: world.consolidator().correct(body, binding=None), "AUTHENTICATION_REQUIRED", "BINDING_MISSING")
    assert [e["reason_code"] for e in denials(world)] == ["AUTHENTICATION_REQUIRED"] * 2


def test_a_correction_envelope_is_closed() -> None:
    world = unit_world()
    body = correction_request("urn:ocor:memory:x:v1", [{"subject": "a", "attribute": "b", "value": 1, "support_refs": ["s"]}])
    service = world.consolidator()
    for changed in (
        _without(body, "correction_reason_ref"),
        {**body, "instruction_eligible": True},
        {**body, "corrected_statements": []},
        {**body, "corrected_statements": [{"subject": "a", "attribute": "b", "value": 1}]},
        {**body, "corrected_statements": [{"subject": "a", "attribute": "b", "value": [1], "support_refs": ["s"]}]},
        {**body, "corrected_statements": body["corrected_statements"] * 2},
        {**body, "corrected_statements": [{"subject": "a", "attribute": "b", "value": 1, "support_refs": []}]},
    ):
        refused(lambda changed=changed: service.correct(changed, binding=r.binding(CTX)), "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID")
    assert len(denials(world)) == 7


@pytest.mark.parametrize(
    ("changes", "reason", "detail"),
    [
        ({"permitted": False}, "POLICY_DENIED", "CONSOLIDATION_DENIED"),
        ({"fail": True}, "CONTROL_PLANE_UNAVAILABLE", "POLICY_UNAVAILABLE"),
        ({"bundle": d("policy-bundle:memory:0")}, "STALE_POLICY", "POLICY_BUNDLE_MISMATCH"),
        ({"invalid": True}, "CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID"),
    ],
)
def test_policy_is_evaluated_before_any_content_read_and_fails_closed(
    live: CWorld, changes: dict[str, Any], reason: str, detail: str
) -> None:
    records = convoy_sources(live)
    for name, value in changes.items():
        setattr(live.grant, name, value)
    before = len(live.ledger.records())
    gets = live.counting.gets
    refused(
        lambda: live.consolidator().consolidate(consolidation_request(refs_of(records)), binding=r.binding(CTX)),
        reason,
        detail,
    )
    assert live.counting.gets == gets
    assert len(live.ledger.records()) == before
    assert len(live.grant.calls) == 1
    assert [e["detail_code"] for e in denials(live)] == [detail]


def test_an_unaudited_denial_fails_closed(live: CWorld) -> None:
    records = convoy_sources(live)
    live.grant.permitted = False
    live.consolidation_audit.fail = True
    refused(
        lambda: live.consolidator().consolidate(consolidation_request(refs_of(records)), binding=r.binding(CTX)),
        "CONTROL_PLANE_UNAVAILABLE",
        "AUDIT_UNAVAILABLE",
    )


# --------------------------------------------------------------------------
# Inputs: visibility, currency, lifecycle, validity and budget (qualifying)
# --------------------------------------------------------------------------


def test_unknown_and_unauthorized_inputs_are_indistinguishable_and_read_nothing(live: CWorld) -> None:
    good = live.source("ok-1", ("bridge-7", "sector", "north"))
    secret_ctx = r.context(marking=r.M_SECRET)
    wide_ctx = r.context(compartments=("alpha", "bravo"))
    outsiders = {
        "other tenant": live.source("x-tenant", ("bridge-7", "sector", "south"), ctx=r.context(tenant="tenant-b")),
        "other organization": live.source("x-org", ("bridge-7", "sector", "south"), ctx=r.context(organization="org-b")),
        "other domain": live.source("x-domain", ("bridge-7", "sector", "south"), ctx=r.context(domain="domain-intel")),
        "other purpose": live.source("x-purpose", ("bridge-7", "sector", "south"), ctx=r.context(purpose="logistics")),
        "compartment": live.source("x-compartment", ("bridge-7", "sector", "south"), ctx=wide_ctx),
        "marking": live.source("x-marking", ("bridge-7", "sector", "south"), ctx=secret_ctx),
    }
    refs = {label: rec.item.version_ref for label, rec in outsiders.items()}
    refs["unknown version"] = memory_version_ref("ok-1", 2)
    refs["unknown item"] = memory_version_ref("never-admitted", 1)
    refs["malformed ref"] = "report-1"
    problems = []
    gets = live.counting.gets
    for n, (label, ref) in enumerate(refs.items()):
        exc = refused(
            lambda ref=ref, n=n: live.consolidator().consolidate(
                consolidation_request([good.item.version_ref, ref], op=f"op-x-{n}"), binding=r.binding(CTX)
            ),
            "MEMORY_VERSION_NOT_FOUND",
            "CONSOLIDATION_INPUT_UNAVAILABLE",
        )
        problems.append(exc.to_problem())
        assert str(exc).endswith("an input does not resolve to a version visible to the caller"), label
    assert all(problem == problems[0] for problem in problems)
    assert live.counting.gets == gets
    assert live.grant.calls == []


def test_inputs_must_be_current_active_valid_heads(live: CWorld) -> None:
    head = live.source("cur-1", ("bridge-7", "sector", "north"))
    replaced = live.source("old-1", ("bridge-7", "sector", "north"))
    revoked = live.lifecycle(replaced, "REVOKED", claims(("bridge-7", "sector", "north")))
    quarantined = live.source("q-1", ("bridge-7", "sector", "north"), lifecycle="QUARANTINED")
    proposed = live.source("p-1", ("bridge-7", "sector", "north"), lifecycle="PROPOSED")
    expiring = live.source("e-1", ("bridge-7", "sector", "north"), valid_until=NOW + timedelta(minutes=1))
    service = live.consolidator()
    cases = [
        (replaced.item.version_ref, "LIFECYCLE_TRANSITION_INVALID", "CONSOLIDATION_INPUT_NOT_CURRENT"),
        (revoked.item.version_ref, "LIFECYCLE_TRANSITION_INVALID", "CONSOLIDATION_INPUT_NOT_ACTIVE"),
        (quarantined.item.version_ref, "MEMORY_TAINTED", "CONSOLIDATION_INPUT_QUARANTINED"),
        (proposed.item.version_ref, "LIFECYCLE_TRANSITION_INVALID", "CONSOLIDATION_INPUT_NOT_ACTIVE"),
    ]
    for n, (ref, reason, detail) in enumerate(cases):
        refused(
            lambda ref=ref, n=n: service.consolidate(
                consolidation_request([head.item.version_ref, ref], op=f"op-l-{n}"), binding=r.binding(CTX)
            ),
            reason,
            detail,
        )
    # Positive: the same expiring input consolidates while valid, then is refused.
    ok = service.consolidate(
        consolidation_request([head.item.version_ref, expiring.item.version_ref], op="op-valid"), binding=r.binding(CTX)
    )
    assert live.item(ok.derived_ref).item.valid_until == NOW + timedelta(minutes=1)
    live.clock.advance(timedelta(minutes=2))
    refused(
        lambda: service.consolidate(
            consolidation_request(
                [head.item.version_ref, expiring.item.version_ref], op="op-expired", clock_now=live.clock.now()
            ),
            binding=r.binding(CTX),
        ),
        "POLICY_DENIED",
        "CONSOLIDATION_INPUT_EXPIRED",
    )
    assert live.grant.calls == [f"consolidate:{_job_ref(live, ok)}"]


def _job_ref(world: CWorld, outcome: ConsolidationOutcome) -> str:
    return outcome.job_ref


def test_an_uncommitted_input_is_never_read(live: CWorld) -> None:
    head = live.source("cur-1", ("bridge-7", "sector", "north"))
    pending = live.source("pend-1", ("bridge-7", "sector", "north"), commit=False)
    refused(
        lambda: live.consolidator().consolidate(
            consolidation_request([head.item.version_ref, pending.item.version_ref]), binding=r.binding(CTX)
        ),
        "MEMORY_VERSION_NOT_FOUND",
        "VERSION_NOT_VISIBLE",
    )
    assert len(live.ledger.records()) == 2


def test_the_profile_budget_bounds_inputs_and_bytes(live: CWorld) -> None:
    many = [live.source(f"m-{n}", ("bridge-7", "sector", "north")) for n in range(9)]
    gets = live.counting.gets
    refused(
        lambda: live.consolidator().consolidate(consolidation_request(refs_of(many), op="op-many"), binding=r.binding(CTX)),
        "POLICY_DENIED",
        "CONSOLIDATION_BUDGET_EXCEEDED",
    )
    assert live.counting.gets == gets
    large = live.source("big-1", *[("bridge-7", f"note-{n:03d}", "x" * 40) for n in range(60)])
    refused(
        lambda: live.consolidator().consolidate(
            consolidation_request([many[0].item.version_ref, large.item.version_ref], op="op-bytes"), binding=r.binding(CTX)
        ),
        "POLICY_DENIED",
        "CONSOLIDATION_BUDGET_EXCEEDED",
    )
    ok = live.consolidator().consolidate(consolidation_request(refs_of(many[:8]), op="op-eight"), binding=r.binding(CTX))
    assert ok.receipt["status"] == "COMPLETED"


def test_an_unparseable_input_is_refused_before_any_write(live: CWorld) -> None:
    head = live.source("cur-1", ("bridge-7", "sector", "north"))
    text = live.admit("text-1", "patrol report at dawn", vector=False, bindings=PROJECT)
    before = len(live.ledger.records())
    refused(
        lambda: live.consolidator().consolidate(
            consolidation_request([head.item.version_ref, text.item.version_ref]), binding=r.binding(CTX)
        ),
        "MEMORY_SCHEMA_INVALID",
        "CONSOLIDATION_INPUT_UNPARSEABLE",
    )
    assert len(live.ledger.records()) == before


def test_the_target_scope_owner_must_be_shared_by_every_input(live: CWorld) -> None:
    a = live.source("a-1", ("bridge-7", "sector", "north"))
    b = live.source("b-1", ("bridge-7", "sector", "north"), bindings={"project_id": "project-2"})
    refused(
        lambda: live.consolidator().consolidate(
            consolidation_request([a.item.version_ref, b.item.version_ref]), binding=r.binding(CTX)
        ),
        "MEMORY_SCHEMA_INVALID",
        "TARGET_SCOPE_BINDING_UNRESOLVED",
    )
    outcome = live.consolidator().consolidate(
        consolidation_request([a.item.version_ref, b.item.version_ref], op="op-domain", scope="DOMAIN"),
        binding=r.binding(CTX),
    )
    assert live.item(outcome.derived_ref).item.memory_scope.value == "DOMAIN"


def test_a_deadline_elapsing_during_the_job_writes_nothing(live: CWorld) -> None:
    records = convoy_sources(live)
    live.grant.on_call = lambda: live.clock.advance(timedelta(seconds=31))
    before = len(live.ledger.records())
    refused(
        lambda: live.consolidator().consolidate(consolidation_request(refs_of(records)), binding=r.binding(CTX)),
        "POLICY_DENIED",
        "DEADLINE_EXCEEDED",
    )
    assert len(live.ledger.records()) == before
    assert live.jobs.records() == ()


# --------------------------------------------------------------------------
# FGM-03 consolidation and FGM-13 conflict/dissent (qualifying)
# --------------------------------------------------------------------------


def test_working_memory_consolidates_into_new_episodic_and_semantic_items(live: CWorld) -> None:
    working = [
        live.source(
            f"wm-{n}",
            ("convoy-3", "route", "R-12"),
            ("convoy-3", f"checkpoint-{n}", "passed"),
            kind="WORKING",
            scope="RUN",
            bindings=RUN,
            expires_at=NOW + timedelta(hours=1),
            taint=("EXTERNAL_DATA", "TOOL_OUTPUT") if n else ("EXTERNAL_DATA",),
        )
        for n in range(3)
    ]
    refs = refs_of(working)
    before = live.snapshot(refs)
    service = live.consolidator()
    for kind in ("EPISODIC", "SEMANTIC"):
        outcome = service.consolidate(
            consolidation_request(refs, op=f"op-{kind}", kind=kind, scope="RUN"), binding=r.binding(CTX)
        )
        derived = live.item(outcome.derived_ref).item
        assert derived.memory_kind.value == kind and derived.memory_version == 1
        assert derived.memory_item_id not in {w.item.memory_item_id for w in working}
        assert derived.source_kind.value == "MEMORY_CONSOLIDATION"
        assert derived.source_ref == outcome.job_ref and derived.source_digest == outcome.job_digest
        assert list(derived.consolidates_refs) == sorted(refs)
        assert set(derived.derived_from_refs) == set(refs)
        assert derived.agent_run_id == "run-1" and derived.lifecycle_status.value == "ACTIVE"
        assert derived.instruction_eligible is False and derived.expires_at is None
        assert set(derived.taint_labels) == {"DERIVED", "EXTERNAL_DATA", "TOOL_OUTPUT"}
        assert derived.uncertainty_ref is not None and derived.confidence <= min(w.item.confidence for w in working)
        payload = live.payload(outcome.derived_ref)
        assert payload["sources"] == [
            {"memory_version_ref": w.item.version_ref, "item_digest": w.item_digest, "content_digest": w.item.content_digest}
            for w in sorted(working, key=lambda w: w.item.version_ref)
        ]
        assert {(s["subject"], s["attribute"], s["value"]) for s in payload["statements"]} == {
            ("convoy-3", "route", "R-12"),
            ("convoy-3", "checkpoint-0", "passed"),
            ("convoy-3", "checkpoint-1", "passed"),
            ("convoy-3", "checkpoint-2", "passed"),
        }
        route = next(s for s in payload["statements"] if s["attribute"] == "route")
        assert route["support_refs"] == sorted(refs)
        assert payload["conflicts"] == [] and outcome.dissent_refs == ()
        assert payload["uncertainty"]["conflict_count"] == 0
        assert "urn:ocor:memory-uncertainty:" + canonical_digest(payload["uncertainty"]).removeprefix("urn:sha256:") == derived.uncertainty_ref
    # Sources are cited, never changed: same item digest, same stored bytes, still head.
    assert live.snapshot(refs) == before
    assert all(v[2] == 1 for v in before.values())


def test_conflicts_preserve_minority_dissent_without_majority_merge(live: CWorld) -> None:
    records = convoy_sources(live)
    refs = refs_of(records)
    before = live.snapshot(refs)
    outcome = live.consolidator().consolidate(consolidation_request(refs, kind="SEMANTIC"), binding=r.binding(CTX))
    payload = live.payload(outcome.derived_ref)
    keys = {(s["subject"], s["attribute"]) for s in payload["statements"]}
    assert keys == {("bridge-7", "sector")}  # the 5-vs-1 status is NOT merged into a statement
    (conflict,) = payload["conflicts"]
    assert conflict["resolution"] == "UNRESOLVED"
    assert [(a["value"], a["support_count"]) for a in conflict["alternatives"]] == [("closed", 1), ("open", 5)]
    assert conflict["alternatives"][0]["support_refs"] == [records[5].item.version_ref]
    (dissent_ref,) = outcome.dissent_refs
    assert conflict["dissent_ref"] == dissent_ref
    dissent = live.item(dissent_ref).item
    assert dissent.memory_kind.value == "DISSENT" and dissent.source_kind.value == "MEMORY_CONSOLIDATION"
    assert list(dissent.consolidates_refs) == sorted(refs)
    assert dissent.lifecycle_status.value == "ACTIVE" and dissent.instruction_eligible is False
    dissent_payload = live.payload(dissent_ref)
    assert dissent_payload["conflict"] == {k: v for k, v in conflict.items() if k != "dissent_ref"}
    assert {s["memory_version_ref"] for s in dissent_payload["sources"]} == set(refs)
    derived = live.item(outcome.derived_ref).item
    assert dissent_ref in derived.derived_from_refs
    assert derived.confidence == bounded_confidence(0.6, 1, 1) == 0.3
    assert payload["uncertainty"] == {
        "method": "claim-merge-agreement:1.0",
        "source_count": 6,
        "statement_count": 1,
        "conflict_count": 1,
        "weakest_source_ref": records[2].item.version_ref,
    }
    assert live.snapshot(refs) == before
    audit = [e for e in live.consolidation_audit.events if e["outcome"] == "COMPLETED"]
    assert audit[0]["dissent_refs"] == [dissent_ref]
    assert canonical_digest(dict(audit[0])) == outcome.receipt["audit_ref"]


def test_a_three_way_and_a_tied_disagreement_keep_every_alternative(live: CWorld) -> None:
    a = live.source("t-a", ("depot", "fuel", "low"), ("gate", "state", "open"))
    b = live.source("t-b", ("depot", "fuel", "medium"), ("gate", "state", "shut"))
    c = live.source("t-c", ("depot", "fuel", "high"))
    outcome = live.consolidator().consolidate(consolidation_request(refs_of([a, b, c])), binding=r.binding(CTX))
    payload = live.payload(outcome.derived_ref)
    assert payload["statements"] == []
    by_attr = {conf["attribute"]: conf for conf in payload["conflicts"]}
    assert [alt["value"] for alt in by_attr["fuel"]["alternatives"]] == ["high", "low", "medium"]
    assert [alt["support_count"] for alt in by_attr["state"]["alternatives"]] == [1, 1]
    assert len(outcome.dissent_refs) == 2
    gate = next(ref for ref in outcome.dissent_refs if live.payload(ref)["conflict"]["attribute"] == "state")
    assert list(live.item(gate).item.consolidates_refs) == sorted(refs_of([a, b]))  # only the conflicting inputs
    assert live.item(outcome.derived_ref).item.confidence == 0.0


def test_derived_marking_is_the_conservative_join_of_its_inputs(live: CWorld) -> None:
    low_ctx = r.context(marking=r.M_UNCLASSIFIED)
    low = live.source("u-1", ("bridge-7", "sector", "north"), ctx=low_ctx)
    high = live.source("u-2", ("bridge-7", "sector", "north"))
    assert low.item.classification_marking_ref == r.M_UNCLASSIFIED
    outcome = live.consolidator().consolidate(consolidation_request(refs_of([low, high])), binding=r.binding(CTX))
    assert live.item(outcome.derived_ref).item.classification_marking_ref == r.M_RESTRICTED
    # An UNCLASSIFIED caller cannot see the RESTRICTED input at all.
    refused(
        lambda: live.consolidator().consolidate(
            consolidation_request(refs_of([low, high]), op="op-low", ctx=low_ctx), binding=r.binding(low_ctx)
        ),
        "MEMORY_VERSION_NOT_FOUND",
        "CONSOLIDATION_INPUT_UNAVAILABLE",
    )
    only_low = live.consolidator().consolidate(
        consolidation_request(refs_of([low]), op="op-low-only", ctx=low_ctx), binding=r.binding(low_ctx)
    )
    assert live.item(only_low.derived_ref).item.classification_marking_ref == r.M_UNCLASSIFIED


def test_reflection_is_tainted_and_never_instruction_eligible(live: CWorld) -> None:
    records = convoy_sources(live)
    outcome = live.consolidator().consolidate(
        consolidation_request(refs_of(records), kind="REFLECTION"), binding=r.binding(CTX)
    )
    reflection = live.item(outcome.derived_ref).item
    assert reflection.memory_kind.value == "REFLECTION"
    assert {"MODEL_GENERATED", "DERIVED"} <= set(reflection.taint_labels)
    assert reflection.instruction_eligible is False and reflection.instruction_approval_ref is None
    assert reflection.content_schema_ref == "urn:ocor:memory-content:reflection:1.0"
    assert "MODEL_GENERATED" not in live.item(outcome.dissent_refs[0]).item.taint_labels


def test_a_reviewed_profile_produces_proposed_outputs_only(live: CWorld) -> None:
    records = convoy_sources(live)
    outcome = live.consolidator().consolidate(
        consolidation_request(refs_of(records), reviewer=HUMAN), binding=r.binding(CTX)
    )
    assert outcome.lifecycle_status == "PROPOSED"
    assert live.item(outcome.derived_ref).item.lifecycle_status.value == "PROPOSED"
    assert all(live.item(ref).item.lifecycle_status.value == "PROPOSED" for ref in outcome.dissent_refs)


def test_consolidation_has_no_authority_canonical_or_procedural_path() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(("." * node.level) + (node.module or ""))
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    forbidden = ("c3", "c6", "canonical_state", "lease", "approval", "action", "promotion", "decision")
    assert not [name for name in imported if any(token in name.lower() for token in forbidden) and name not in {"MemoryPolicyDecision", "InstructionApproval"}]
    source = MODULE.read_text(encoding="utf-8")
    assert '"instruction_eligible": False' in source and "instruction_eligible\": True" not in source


# --------------------------------------------------------------------------
# Correction (FGM-09): new version, sources and dissent untouched (qualifying)
# --------------------------------------------------------------------------


def _consolidated(world: CWorld) -> tuple[list[AdmittedMemoryVersion], ConsolidationOutcome]:
    records = convoy_sources(world)
    return records, world.consolidator().consolidate(consolidation_request(refs_of(records)), binding=r.binding(CTX))


def test_a_correction_is_a_new_version_that_keeps_sources_conflicts_and_dissent(live: CWorld) -> None:
    records, outcome = _consolidated(live)
    refs = refs_of(records)
    watched = [*refs, outcome.derived_ref, *outcome.dissent_refs]
    before = live.snapshot(watched)
    v1_payload = live.payload(outcome.derived_ref)
    support = [refs[0], refs[1]]
    corrected = live.consolidator().correct(
        correction_request(
            outcome.derived_ref,
            [{"subject": "bridge-7", "attribute": "sector", "value": "north-east", "support_refs": support}],
        ),
        binding=r.binding(CTX),
    )
    v2 = live.item(corrected.derived_ref).item
    v1 = live.item(outcome.derived_ref).item
    assert (v2.memory_item_id, v2.memory_version) == (v1.memory_item_id, 2)
    assert v2.supersedes_ref == v1.version_ref and v2.correction_of_ref == v1.version_ref
    assert v2.consolidates_refs == v1.consolidates_refs and v2.derived_from_refs == v1.derived_from_refs
    assert v2.instruction_eligible is False and v2.memory_kind is v1.memory_kind
    assert set(v1.taint_labels) <= set(v2.taint_labels)
    v2_payload = live.payload(corrected.derived_ref)
    assert v2_payload["conflicts"] == v1_payload["conflicts"]
    assert v2_payload["sources"] == v1_payload["sources"]
    (sector,) = v2_payload["statements"]
    assert sector == {"subject": "bridge-7", "attribute": "sector", "value": "north-east", "support_refs": support}
    assert v2_payload["correction"]["correction_of_ref"] == v1.version_ref
    assert corrected.dissent_refs == outcome.dissent_refs
    assert corrected.receipt["operation_kind"] == "correctConsolidatedMemory"
    # The corrected version, its sources and the dissent are byte-identical and
    # still current (the dissent is never re-versioned by the correction).
    after = live.snapshot(watched)
    assert {k: v[:2] for k, v in after.items()} == {k: v[:2] for k, v in before.items()}
    assert all(after[ref][2] == 1 for ref in [*refs, *outcome.dissent_refs])
    assert after[outcome.derived_ref][2] == 2
    assert live.grant.calls[-1] == f"correct:{v1.version_ref}"


def test_a_correction_cannot_erase_dissent_rewrite_sources_or_touch_dissent(live: CWorld) -> None:
    records, outcome = _consolidated(live)
    refs = refs_of(records)
    outsider = live.source("outsider-1", ("bridge-7", "sector", "south"))
    service = live.consolidator()
    before = len(live.ledger.records())
    cases = [
        (outcome.derived_ref, {"subject": "bridge-7", "attribute": "status", "value": "open", "support_refs": refs[:5]}, "POLICY_DENIED", "DISSENT_ERASURE"),
        (outcome.derived_ref, {"subject": "bridge-7", "attribute": "status", "value": "closed", "support_refs": refs[5:]}, "POLICY_DENIED", "DISSENT_ERASURE"),
        (outcome.derived_ref, {"subject": "bridge-7", "attribute": "sector", "value": "south", "support_refs": [outsider.item.version_ref]}, "POLICY_DENIED", "CORRECTION_SOURCE_REWRITE"),
        (outcome.derived_ref, {"subject": "bridge-7", "attribute": "sector", "value": "south", "support_refs": [refs[0], "urn:ocor:memory:invented:v1"]}, "POLICY_DENIED", "CORRECTION_SOURCE_REWRITE"),
        (outcome.dissent_refs[0], {"subject": "bridge-7", "attribute": "status", "value": "open", "support_refs": refs[:1]}, "POLICY_DENIED", "DISSENT_IMMUTABLE"),
        (records[0].item.version_ref, {"subject": "bridge-7", "attribute": "sector", "value": "south", "support_refs": refs[:1]}, "UNSUPPORTED_CAPABILITY", "CORRECTION_TARGET_NOT_CONSOLIDATED"),
        (memory_version_ref("never", 1), {"subject": "a", "attribute": "b", "value": 1, "support_refs": refs[:1]}, "MEMORY_VERSION_NOT_FOUND", "CORRECTION_TARGET_UNAVAILABLE"),
    ]
    for n, (target, statement, reason, detail) in enumerate(cases):
        refused(
            lambda target=target, statement=statement, n=n: service.correct(
                correction_request(target, [statement], op=f"op-bad-{n}"), binding=r.binding(CTX)
            ),
            reason,
            detail,
        )
    assert len(live.ledger.records()) == before
    assert [e["detail_code"] for e in denials(live)] == [c[3] for c in cases]
    # Positive control on the same item after every refusal.
    ok = service.correct(
        correction_request(outcome.derived_ref, [{"subject": "bridge-7", "attribute": "sector", "value": "north", "support_refs": refs[:1]}], op="op-good"),
        binding=r.binding(CTX),
    )
    assert ok.derived_ref == memory_version_ref(live.item(outcome.derived_ref).item.memory_item_id, 2)
    # A superseded version is no longer correctable; a replay still returns its outcome.
    refused(
        lambda: service.correct(
            correction_request(outcome.derived_ref, [{"subject": "bridge-7", "attribute": "sector", "value": "x", "support_refs": refs[:1]}], op="op-stale"),
            binding=r.binding(CTX),
        ),
        "LIFECYCLE_TRANSITION_INVALID",
        "CORRECTION_TARGET_NOT_CURRENT",
    )
    replay = service.correct(
        correction_request(outcome.derived_ref, [{"subject": "bridge-7", "attribute": "sector", "value": "north", "support_refs": refs[:1]}], op="op-good"),
        binding=r.binding(CTX),
    )
    assert replay == ok


def test_correction_policy_and_authorization_fail_closed(live: CWorld) -> None:
    records, outcome = _consolidated(live)
    statement = [{"subject": "bridge-7", "attribute": "sector", "value": "x", "support_refs": refs_of(records)[:1]}]
    live.grant.correction_permitted = False
    refused(lambda: live.consolidator().correct(correction_request(outcome.derived_ref, statement, op="op-c1"), binding=r.binding(CTX)), "POLICY_DENIED", "CONSOLIDATION_DENIED")
    live.grant.correction_permitted = True
    other = r.context(compartments=("bravo",))
    refused(
        lambda: live.consolidator().correct(correction_request(outcome.derived_ref, statement, op="op-c2", ctx=other), binding=r.binding(other)),
        "MEMORY_VERSION_NOT_FOUND",
        "CORRECTION_TARGET_UNAVAILABLE",
    )
    assert live.ledger.latest_version(live.item(outcome.derived_ref).item.memory_item_id) == 1


def _direct(world: CWorld, mapping: dict[str, Any], payload: bytes, op: str) -> None:
    world.admission.admit(
        {
            "operation_id": op,
            "governed_context": CTX.to_mapping(),
            "governed_context_digest": CTX.digest(),
            "deadline": format_utc_timestamp(world.clock.now() + timedelta(seconds=30)),
            "candidate": mapping,
        },
        binding=r.binding(CTX),
        payload=payload,
    )


def test_derived_memory_and_dissent_cannot_be_admitted_or_rewritten_around_the_service(live: CWorld) -> None:
    records, outcome = _consolidated(live)
    summary = live.item(outcome.derived_ref).item
    dissent = live.item(outcome.dissent_refs[0]).item
    forged = b'{"statements": "status open, no conflict"}'

    def next_version(item: GovernedMemoryItem, payload: bytes, **changes: Any) -> dict[str, Any]:
        mapping = item.to_mapping()
        mapping.update(
            memory_version=item.memory_version + 1,
            supersedes_ref=item.version_ref,
            correction_of_ref=item.version_ref,
            content_digest=d(payload),
            created_at=format_utc_timestamp(live.clock.now()),
            governed_context_digest=CTX.digest(),
        )
        mapping.update(changes)
        return mapping

    # A correction of the summary through plain admission (dissent erasure).
    exc = refused(lambda: _direct(live, next_version(summary, forged), forged, "op-direct-1"), "POLICY_DENIED", "ADMISSION_DENIED")
    assert exc.reason_code == "POLICY_DENIED"
    # A content rewrite of a DISSENT item, even under another source kind.
    refused(
        lambda: _direct(
            live,
            next_version(dissent, forged, source_kind="OBSERVATION", source_ref="src-telemetry-1", source_digest=r.SOURCE_DIGEST,
                         consolidates_refs=[], provenance_refs=["prov-1"], evidence_refs=["ev-1"]),
            forged,
            "op-direct-2",
        ),
        "POLICY_DENIED",
        "ADMISSION_DENIED",
    )
    # A fabricated consolidation item claiming a lineage it never ran (laundering).
    fabricated = summary.to_mapping()
    fabricated.update(memory_item_id="consolidated-forged", content_digest=d(forged), created_at=format_utc_timestamp(live.clock.now()))
    refused(lambda: _direct(live, fabricated, forged, "op-direct-3"), "POLICY_DENIED", "ADMISSION_DENIED")
    assert live.ledger.latest_version(summary.memory_item_id) == 1
    assert live.ledger.latest_version(dissent.memory_item_id) == 1
    assert live.ledger.get("consolidated-forged", 1) is None
    # Plain admissions of ordinary memory are still decided by the wrapped policy.
    assert live.source("plain-1", ("bridge-7", "sector", "north")).item.memory_version == 1
    assert records


def test_a_directly_admitted_dissent_cannot_be_rewritten_by_a_new_version(live: CWorld) -> None:
    text = claims(("bridge-7", "status", "closed"))
    dissent = live.admit(
        "challenger-dissent-1", text, vector=False, bindings=PROJECT, kind="DISSENT",
        source_kind="HUMAN_INPUT", taint=("HUMAN_SUPPLIED",), content_schema="urn:ocor:memory-content:dissent:1.0",
    )
    forged = claims(("bridge-7", "status", "open")).encode()

    def next_version(payload: bytes, **changes: Any) -> dict[str, Any]:
        mapping = dissent.item.to_mapping()
        mapping.update(
            memory_version=2,
            supersedes_ref=dissent.item.version_ref,
            content_digest=d(payload),
            created_at=format_utc_timestamp(live.clock.now()),
        )
        mapping.update(changes)
        return mapping

    refused(lambda: _direct(live, next_version(forged), forged, "op-dissent-rewrite"), "POLICY_DENIED", "ADMISSION_DENIED")
    assert live.ledger.latest_version("challenger-dissent-1") == 1
    # A new version that keeps the dissent content (here: a lower confidence) is decided by the wrapped policy.
    _direct(live, next_version(text.encode(), confidence=0.5), text.encode(), "op-dissent-same")
    assert live.ledger.latest_version("challenger-dissent-1") == 2


# --------------------------------------------------------------------------
# Idempotency, cross-run persistence and fault injection (qualifying)
# --------------------------------------------------------------------------


def test_a_replay_returns_the_recorded_outcome_and_a_reused_operation_conflicts(live: CWorld) -> None:
    records = convoy_sources(live)
    service = live.consolidator()
    body = consolidation_request(refs_of(records))
    first = service.consolidate(body, binding=r.binding(CTX))
    count = len(live.ledger.records())
    second = service.consolidate({**body, "deadline": format_utc_timestamp(NOW + timedelta(seconds=20))}, binding=r.binding(CTX))
    assert second == first and len(live.ledger.records()) == count
    # A new correlation id is a new request of the same operation, not a new job.
    recorrelated = r.context()
    recorrelated = GovernedContext(**{**{name: getattr(recorrelated, name) for name in GovernedContext.fields}, "correlation_id": str(uuid.uuid4())})
    third = service.consolidate(
        {**body, "governed_context": recorrelated.to_mapping(), "governed_context_digest": recorrelated.digest()},
        binding=r.binding(recorrelated),
    )
    assert third == first
    refused(
        lambda: service.consolidate({**body, "input_item_refs": refs_of(records)[:3]}, binding=r.binding(CTX)),
        "MEMORY_IDEMPOTENCY_CONFLICT",
        "CONSOLIDATION_OPERATION_REUSED",
    )
    refused(
        lambda: service.correct(
            correction_request(first.derived_ref, [{"subject": "bridge-7", "attribute": "sector", "value": "x", "support_refs": refs_of(records)[:1]}], op=body["operation_id"]),
            binding=r.binding(CTX),
        ),
        "MEMORY_IDEMPOTENCY_CONFLICT",
        "CONSOLIDATION_OPERATION_REUSED",
    )
    other = service.consolidate({**body, "operation_id": "op-consolidate-2"}, binding=r.binding(CTX))
    assert other.derived_ref != first.derived_ref and len(live.ledger.records()) == count + 2
    assert service.metrics[("consolidateMemory", "REPLAYED", "NONE")] == 2


def test_a_replay_survives_superseded_inputs(live: CWorld) -> None:
    records = convoy_sources(live)
    service = live.consolidator()
    body = consolidation_request(refs_of(records))
    first = service.consolidate(body, binding=r.binding(CTX))
    live.lifecycle(records[0], "REVOKED", claims(("bridge-7", "sector", "north"), ("bridge-7", "status", "open")))
    assert service.consolidate(body, binding=r.binding(CTX)) == first
    refused(lambda: service.consolidate({**body, "operation_id": "op-new"}, binding=r.binding(CTX)), "LIFECYCLE_TRANSITION_INVALID", "CONSOLIDATION_INPUT_NOT_CURRENT")


def test_completed_jobs_persist_across_runs_and_the_journal_detects_tampering(backends: Backends, tmp_path: Path) -> None:
    journal = tmp_path / "consolidation-jobs.jsonl"
    world = backends.world(jobs=JournalConsolidationJobLedger(journal))
    records = convoy_sources(world)
    body = consolidation_request(refs_of(records))
    first = world.consolidator().consolidate(body, binding=r.binding(CTX))
    count = len(world.ledger.records())
    rerun = backends.fresh(world, jobs=JournalConsolidationJobLedger(journal))
    assert rerun.consolidator().consolidate(body, binding=r.binding(CTX)) == first
    assert len(rerun.ledger.records()) == count
    assert rerun.payload(first.derived_ref)["conflicts"][0]["dissent_ref"] == first.dissent_refs[0]
    raw = journal.read_bytes()
    journal.write_bytes(raw.replace(b"COMPLETED", b"COMPLETEX", 1))
    with pytest.raises(ConsolidationLedgerCorrupted):
        JournalConsolidationJobLedger(journal)
    journal.write_bytes(raw[:-1])
    with pytest.raises(ConsolidationLedgerCorrupted):
        JournalConsolidationJobLedger(journal)
    journal.write_bytes(raw)
    assert JournalConsolidationJobLedger(journal).get("tenant-a", body["operation_id"]) is not None


def test_a_job_interrupted_by_a_store_failure_is_completed_by_its_retry(live: CWorld) -> None:
    records = convoy_sources(live)
    body = consolidation_request(refs_of(records))
    live.counting.fail_put_numbers = {live.counting.puts + 2}  # dissent stored, summary write fails
    refused(lambda: live.consolidator().consolidate(body, binding=r.binding(CTX)), "REPRESENTATION_NOT_READY", "STORE_COMMIT_INCOMPLETE")
    assert live.jobs.records() == ()
    partial = len(live.ledger.records())
    outcome = live.consolidator().consolidate(body, binding=r.binding(CTX))
    assert len(live.ledger.records()) == partial  # the retry reuses the admitted slots
    for ref in [outcome.derived_ref, *outcome.dissent_refs]:
        item_id, version = parse_memory_version_ref(ref)
        assert version == 1 and live.ledger.latest_version(item_id) == 1
        assert live.payload(ref)
    assert len(live.jobs.records()) == 1


@pytest.mark.parametrize("fault", ["audit", "jobs"])
def test_no_receipt_without_audit_and_completion_record(backends: Backends, fault: str) -> None:
    jobs = FailingJobs()
    world = backends.world(jobs=jobs)
    records = convoy_sources(world)
    body = consolidation_request(refs_of(records))
    if fault == "audit":
        world.consolidation_audit.fail = True
        refused(lambda: world.consolidator().consolidate(body, binding=r.binding(CTX)), "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE")
        world.consolidation_audit.fail = False
    else:
        jobs.failures = 1
        refused(lambda: world.consolidator().consolidate(body, binding=r.binding(CTX)), "CONTROL_PLANE_UNAVAILABLE", "JOB_LEDGER_UNAVAILABLE")
    assert jobs.records() == ()
    outcome = world.consolidator().consolidate(body, binding=r.binding(CTX))
    (record,) = jobs.records()
    assert record.outcome == outcome
    assert canonical_digest(dict(record.audit_event)) == outcome.receipt["audit_ref"]


def test_a_squatted_derived_slot_fails_closed_and_is_never_adopted(live: CWorld) -> None:
    a = live.source("sq-a", ("depot", "fuel", "low"))
    b = live.source("sq-b", ("depot", "fuel", "low"))
    jobs: list[MemoryConsolidationJob] = []
    original = live.grant.authorize_consolidation

    def capture(job: MemoryConsolidationJob, ctx: GovernedContext) -> MemoryPolicyDecision:
        jobs.append(job)
        return original(job, ctx)

    live.grant.authorize_consolidation = capture  # type: ignore[method-assign]
    live.grant.permitted = False
    body = consolidation_request(refs_of([a, b]))
    refused(lambda: live.consolidator().consolidate(body, binding=r.binding(CTX)), "POLICY_DENIED", "CONSOLIDATION_DENIED")
    slot = "consolidated-" + jobs[0].digest.removeprefix("urn:sha256:")[:32]
    squatter = live.source(slot, ("depot", "fuel", "high"))
    live.grant.permitted = True
    refused(lambda: live.consolidator().consolidate(body, binding=r.binding(CTX)), "MEMORY_IDEMPOTENCY_CONFLICT", "DERIVED_SLOT_OCCUPIED")
    assert live.jobs.records() == ()
    assert live.ledger.latest_version(slot) == 1 and live.item(memory_version_ref(slot, 1)) == squatter


def test_the_job_journal_chain_and_entry_digests_are_verified(tmp_path: Path) -> None:
    def record(op: str) -> Any:
        from ocor_runtime.memory.consolidation import ConsolidationJobRecord

        event = {"action": "consolidateMemory", "operation_id": op, "job_digest": d(f"job:{op}")}
        outcome = ConsolidationOutcome(
            receipt={"operation_id": op, "operation_kind": "consolidateMemory", "status": "COMPLETED",
                     "governed_context_digest": CTX.digest(), "audit_ref": canonical_digest(event)},
            operation_kind="consolidateMemory", job_ref=f"urn:ocor:memory-consolidation-job:{op}",
            job_digest=d(f"job:{op}"), derived_ref=memory_version_ref(op, 1), dissent_refs=(), lifecycle_status="ACTIVE",
        )
        return ConsolidationJobRecord(tenant_id="tenant-a", operation_id=op, outcome=outcome, audit_event=event)

    path = tmp_path / "jobs.jsonl"
    ledger = JournalConsolidationJobLedger(path)
    ledger.append(record("op-1"))
    ledger.append(record("op-2"))
    with pytest.raises(MemoryConsolidationError):
        ledger.append(record("op-1"))
    assert JournalConsolidationJobLedger(path).get("tenant-a", "op-2") is not None
    first, second = path.read_bytes().splitlines(keepends=True)
    # Dropping an entry breaks the chain even though every remaining entry is intact.
    path.write_bytes(second)
    with pytest.raises(ConsolidationLedgerCorrupted, match="chain"):
        JournalConsolidationJobLedger(path)
    # An entry whose recorded digest does not bind its body is refused.
    entry = json.loads(first)
    entry["digest"] = d("forged")
    path.write_bytes(json.dumps(entry).encode() + b"\n")
    with pytest.raises(ConsolidationLedgerCorrupted, match="digest"):
        JournalConsolidationJobLedger(path)
    path.write_bytes(first + second)
    assert JournalConsolidationJobLedger(path).get("tenant-a", "op-1") is not None


def test_distinct_jobs_never_share_derived_slots(live: CWorld) -> None:
    records = convoy_sources(live)
    service = live.consolidator()
    outcome = service.consolidate(consolidation_request(refs_of(records)), binding=r.binding(CTX))
    # A different job digest can never reuse the slots of another job: the ids are
    # bound to the job digest, so the second operation writes its own items.
    second = service.consolidate(consolidation_request(refs_of(records), op="op-2", kind="SEMANTIC"), binding=r.binding(CTX))
    assert not {outcome.derived_ref, *outcome.dissent_refs} & {second.derived_ref, *second.dissent_refs}


def test_audit_events_carry_correlation_and_never_payload_content(live: CWorld) -> None:
    records, outcome = _consolidated(live)
    live.grant.permitted = False
    refused(lambda: live.consolidator().consolidate(consolidation_request(refs_of(records), op="op-deny"), binding=r.binding(CTX)), "POLICY_DENIED", "CONSOLIDATION_DENIED")
    text = json.dumps(live.consolidation_audit.events, sort_keys=True)
    assert "bridge-7" not in text and "closed" not in text and "north" not in text
    assert all(e["correlation_id"] == CTX.correlation_id for e in live.consolidation_audit.events)
    assert outcome.receipt["governed_context_digest"] == CTX.digest()


def test_metrics_use_a_bounded_label_set(live: CWorld) -> None:
    records, _ = _consolidated(live)
    service = live.consolidator()
    service.consolidate(consolidation_request(refs_of(records)), binding=r.binding(CTX))
    live.grant.permitted = False
    for n in range(3):
        with pytest.raises(MemoryAdmissionError):
            service.consolidate(consolidation_request(refs_of(records), op=f"op-m-{n}"), binding=r.binding(CTX))
    kinds = {"consolidateMemory", "correctConsolidatedMemory"}
    outcomes = {"COMPLETED", "REPLAYED", "DENIED"}
    for kind, outcome, reason in service.metrics:
        assert kind in kinds and outcome in outcomes and (reason == "NONE" or reason in PROBLEM_REASON_CODES)
    assert service.metrics[("consolidateMemory", "DENIED", "POLICY_DENIED")] == 3


def test_qualifying_backends_are_real_and_pinned(backends: Backends) -> None:
    assert base.QDRANT_IMAGE.endswith(base.LOCKED_IMAGES["qdrant"].split("@", 1)[1])
    assert base._docker("inspect", backends.qdrant.container, "--format", "{{.Config.Image}}") == base.QDRANT_IMAGE
    assert base._docker("inspect", backends.bao.container, "--format", "{{.Config.Image}}") == base.LOCKED_IMAGES["openbao"]
    with psycopg.connect(backends.dsn) as conn:
        row = conn.execute("SHOW server_version").fetchone()
    assert row is not None and str(row[0]).startswith("16.")
    world = backends.world()
    assert isinstance(world.metadata, base.PostgresStores)
    assert isinstance(world.cipher, base.OpenBaoTransitCipher)
    assert isinstance(world.counting.inner, base.PostgresContentStore)
