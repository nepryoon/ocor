"""OCOR-DEV-0052: Implement structured, full-text, vector and hybrid retrieval.

Acceptance (backlog): policy-first retrieval pins query, representation,
ranking, filters and exact item versions.  Negative: unauthorized items cannot
affect content, existence, rank, count, cache or explanation; a SKIPPED,
UNAVAILABLE, mock-only or NOT_EXECUTED qualifying case is not accepted.

Oracles: ADD v1.3 Part II §§2.3-2.8, 2.10 and 2.12 (named versioned query
contracts; policy before candidate lookup and again before materialisation;
unauthorized items never enter ANN graphs, score normalization, ranking,
diversity, counts, pagination, explanations or shared caches; hybrid factors
kept separately; cross-project/domain/federated retrieval needs explicit
Authority, cross-tenant is deny-by-default; parallel representation versions;
only ACTIVE, unexpired, current versions are retrievable), LLD v1.1
§§2.8.1-2.8.4 and §7.2 (``FGM-04``, ``FGM-05``, ``FGM-06``, ``FGM-07``,
``FGM-10``, ``FGM-16``, ``FGM-17`` oracles, exercised here at component level).

Qualifying cases run on the real, pinned backends of OCOR-DEV-0051: PostgreSQL
16 from ``OCOR_LIVE_POSTGRES_DSN`` (metadata, encrypted content, full-text
index, one schema per world), Qdrant 1.15.1 (vector index, one namespace per
world) and OpenBao 2.6.2 transit, reusing the 0051 adapters.  Records come
from the real OCOR-DEV-0050 admission service and are committed by the real
OCOR-DEV-0051 store coordinator.  Lifecycle versions after admission
(``REVOKED``) are appended through the ledger port the way the lifecycle
coordinator (OCOR-DEV-0055) will, then committed by the real coordinator.  A
missing backend fails, it never skips.  The unit cases at the top use the 0051
in-memory port fixtures only for branch logic; none of them is qualifying.
"""

from __future__ import annotations

import dataclasses
import os
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest
import test_ocor_dev_0051 as base
from ocor_runtime.c4_marking import MarkingSchemeDefinition
from ocor_runtime.kernel.canonical import canonical_digest, format_utc_timestamp
from ocor_runtime.kernel.governance import InMemoryTrustedClock
from ocor_runtime.kernel.governed_context import GovernedContext, VerifiedGovernedContextBinding
from ocor_runtime.memory.model import (
    AdmissionLimits,
    AdmittedMemoryVersion,
    FederationPolicy,
    GovernedMemoryItem,
    InMemoryMemoryVersionLedger,
    LatticeMarkingResolver,
    MemoryAdmissionError,
    MemoryAdmissionService,
    MemoryKind,
    MemoryPolicyDecision,
    MemoryReceipt,
    MemoryScope,
    idempotency_key,
    memory_version_ref,
)
from ocor_runtime.memory.retrieval import (
    DEFAULT_QUERY_CONTRACTS,
    MemoryRetrievalError,
    MemorySearchResponse,
    MemorySearchService,
    RankingProfile,
    RetrievalAuthorization,
    RetrievalLimits,
    RetrievalMode,
    SearchQuery,
)
from ocor_runtime.memory.stores import (
    BoundHit,
    LexicalProfile,
    MemoryPartition,
    MemoryStoreCoordinator,
    StoreLimits,
    VectorProfile,
    vector_digest,
)

NOW = base.NOW
d = base.d
M_UNCLASSIFIED = base.M_UNCLASSIFIED
M_RESTRICTED = base.M_RESTRICTED
M_SECRET = d("marking:SECRET")
POLICY_BUNDLE = base.POLICY_BUNDLE
ONTOLOGY = base.ONTOLOGY
SOURCE_DIGEST = base.SOURCE_DIGEST
DIMENSIONS = base.DIMENSIONS
VECTOR_MODEL = base.VECTOR_MODEL
VECTOR_MODEL_V2 = {
    "embedding_model_ref": "embedding-model:fixture-hash-8:2",
    "embedding_model_digest": d("embedding-model:fixture-hash-8:2"),
    "embedding_dimensions": DIMENSIONS,
    "embedding_normalization_profile": "l2-unit",
}
embed = base.embed
CONTRACTS = {contract.mode: contract for contract in DEFAULT_QUERY_CONTRACTS}
PROFILE = RankingProfile()
ALL_KINDS = frozenset(MemoryKind)
ALL_SCOPES = frozenset(MemoryScope)


def context(
    *,
    tenant: str = "tenant-a",
    organization: str = "org-a",
    domain: str = "domain-ops",
    compartments: Sequence[str] = ("alpha",),
    marking: str = M_RESTRICTED,
    purpose: str = "mission-planning",
    principal: str = "agent-principal-1",
) -> GovernedContext:
    return GovernedContext(
        tenant_id=tenant,
        organization_id=organization,
        domain_id=domain,
        compartments=tuple(compartments),
        classification_marking_ref=marking,
        purpose=purpose,
        effective_principal_id=principal,
        actor_chain=("human-operator-1", principal),
        ontology_release_digest=ONTOLOGY,
        policy_bundle_digest=POLICY_BUNDLE,
        correlation_id=base.CORRELATION,
    )


CALLER = context(compartments=("alpha", "bravo"))


def binding(ctx: GovernedContext = CALLER) -> VerifiedGovernedContextBinding:
    return VerifiedGovernedContextBinding(binding_ref="binding:keycloak-1", expected=ctx)


class Resolver(base.Resolver):
    def federation_policy(self, ref: str, ctx: GovernedContext) -> FederationPolicy | None:
        if ref != "federation:fed-1":
            return None
        return FederationPolicy(
            policy_ref=ref,
            tenant_ids=frozenset({"tenant-a"}),
            purposes=frozenset({"mission-planning"}),
            valid_until=NOW + timedelta(days=30),
        )


# --------------------------------------------------------------------------
# Retrieval policy, stop state and audit test ports
# --------------------------------------------------------------------------


@dataclass
class GrantPolicy:
    """Live retrieval policy double: explicit grants, recorded calls."""

    scope_bindings: dict[str, frozenset[str]] = field(
        default_factory=lambda: {
            "project_id": frozenset({"project-1"}),
            "agent_run_id": frozenset({"run-1"}),
            "task_id": frozenset({"task-1"}),
            "agent_id": frozenset({"agent-1"}),
            "team_id": frozenset({"team-1"}),
            "federation_policy_ref": frozenset(),
        }
    )
    kinds: frozenset[MemoryKind] = ALL_KINDS
    scopes: frozenset[MemoryScope] = ALL_SCOPES
    domains: frozenset[str] = frozenset()
    permitted: bool = True
    bundle: str | None = None
    denied_items: set[str] = field(default_factory=set)
    fail: bool = False
    calls: list[str] = field(default_factory=list)

    def authorize_retrieval(self, request: SearchQuery, ctx: GovernedContext) -> RetrievalAuthorization:
        self.calls.append("retrieval")
        if self.fail:
            raise ConnectionError("opa unavailable")
        return RetrievalAuthorization(
            permitted=self.permitted,
            decision_ref=f"decision:retrieval:{request.digest}",
            policy_bundle_digest=self.bundle or ctx.policy_bundle_digest,
            memory_kinds=self.kinds,
            memory_scopes=self.scopes,
            scope_bindings=dict(self.scope_bindings),
            domains=self.domains,
        )

    def authorize_materialization(self, item: GovernedMemoryItem, ctx: GovernedContext) -> MemoryPolicyDecision:
        self.calls.append(f"materialize:{item.version_ref}")
        return MemoryPolicyDecision(
            permitted=item.memory_item_id not in self.denied_items,
            decision_ref=f"decision:materialize:{item.version_ref}",
            policy_bundle_digest=ctx.policy_bundle_digest,
        )


@dataclass
class StopState:
    epoch: int = 0
    bump_after: int | None = None
    fail: bool = False
    reads: int = 0

    def current_epoch(self, ctx: GovernedContext) -> int:
        self.reads += 1
        if self.fail:
            raise TimeoutError("stop registry unavailable")
        if self.bump_after is not None and self.reads > self.bump_after:
            return self.epoch + 1
        return self.epoch


@dataclass
class Audit:
    events: list[Mapping[str, object]] = field(default_factory=list)
    fail: bool = False

    def record(self, event: Mapping[str, object]) -> None:
        if self.fail:
            raise OSError("audit store unavailable")
        self.events.append(dict(event))


class TracingIndex:
    """Wraps an index port and records every backend call by partition.

    The version 2 methods are declared explicitly: the coordinator recognises
    a version 2 index structurally and fails closed on any other wrapper.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[tuple[str, str, str]] = []

    def __getattr__(self, name: str) -> Any:
        target = getattr(self.inner, name)
        if name not in {"search", "upsert", "read_back", "get", "entries", "remove"}:
            return target

        def traced(partition: MemoryPartition, *args: Any, **kwargs: Any) -> Any:
            version = args[0] if name != "upsert" else args[0].representation_version
            self.calls.append((name, partition.digest, str(version)))
            return target(partition, *args, **kwargs)

        return traced

    def search_eligible(self, partition: MemoryPartition, representation_version: str, query: Any, **kwargs: Any) -> Any:
        self.calls.append(("search_eligible", partition.digest, representation_version))
        return self.inner.search_eligible(partition, representation_version, query, **kwargs)

    def score_entries(self, partition: MemoryPartition, representation_version: str, query: Any, store_refs: Sequence[str]) -> Any:
        self.calls.append(("score_entries", partition.digest, representation_version))
        return self.inner.score_entries(partition, representation_version, query, store_refs)

    def retire(self, partition: MemoryPartition, representation_version: str, memory_item_id: str, below_version: int) -> None:
        self.calls.append(("retire", partition.digest, representation_version))
        self.inner.retire(partition, representation_version, memory_item_id, below_version)


# --------------------------------------------------------------------------
# World: real admission + real coordinator over pluggable store ports
# --------------------------------------------------------------------------


class World:
    def __init__(self, *, metadata: Any, content: Any, lexical: Any, vector: Any, cipher: Any) -> None:
        self.ledger = InMemoryMemoryVersionLedger()
        self.clock = InMemoryTrustedClock(NOW)
        scheme = MarkingSchemeDefinition("ocor-classification", ["UNCLASSIFIED", "RESTRICTED", "SECRET"])
        self.markings = LatticeMarkingResolver(
            scheme, {M_UNCLASSIFIED: "UNCLASSIFIED", M_RESTRICTED: "RESTRICTED", M_SECRET: "SECRET"}
        )
        self.admission = MemoryAdmissionService(
            ledger=self.ledger,
            resolver=Resolver(),
            policy=base.Policy(),
            markings=self.markings,
            clock=self.clock,
            limits=AdmissionLimits(retention_horizons={"retention:standard": timedelta(days=365)}),
        )
        self.metadata = metadata
        self.content = content
        self.lexical = TracingIndex(lexical)
        self.vector = TracingIndex(vector)
        self.cipher = cipher
        self.coordinator = MemoryStoreCoordinator(
            ledger=self.ledger,
            metadata=metadata,
            content=content,
            cipher=cipher,
            lexical=self.lexical,  # type: ignore[arg-type]
            vector=self.vector,  # type: ignore[arg-type]
            clock=self.clock,
            limits=StoreLimits(),
        )
        self.policy = GrantPolicy()
        self.stop = StopState()
        self.audit = Audit()
        self._ops = 0

    def service(self, **overrides: Any) -> MemorySearchService:
        arguments: dict[str, Any] = {
            "coordinator": self.coordinator,
            "metadata": self.metadata,
            "policy": self.policy,
            "markings": self.markings,
            "stop": self.stop,
            "audit": self.audit,
            "clock": self.clock,
        }
        arguments.update(overrides)
        return MemorySearchService(**arguments)

    def admit(
        self,
        item_id: str,
        text: str,
        *,
        ctx: GovernedContext | None = None,
        kind: str = "EPISODIC",
        scope: str = "PROJECT",
        bindings: Mapping[str, str] | None = None,
        version: int = 1,
        vector: bool = True,
        model: Mapping[str, object] = VECTOR_MODEL,
        source_kind: str = "OBSERVATION",
        source_ref: str = "src-telemetry-1",
        taint: Sequence[str] = ("EXTERNAL_DATA",),
        confidence: float = 0.8,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        expires_at: datetime | None = None,
        lifecycle: str = "ACTIVE",
        marking: str | None = None,
        content_schema: str = "urn:ocor:memory-content:episode:1.0",
        commit: bool = True,
    ) -> AdmittedMemoryVersion:
        ctx = ctx if ctx is not None else context()
        payload = text.encode()
        candidate: dict[str, Any] = {
            "memory_item_id": item_id,
            "memory_version": version,
            "memory_kind": kind,
            "memory_scope": scope,
            "owner_principal_id": ctx.effective_principal_id,
            "tenant_id": ctx.tenant_id,
            "organization_id": ctx.organization_id,
            "domain_id": ctx.domain_id,
            "compartments": list(ctx.compartments),
            "classification_marking_ref": marking or ctx.classification_marking_ref,
            "purpose": ctx.purpose,
            "content_schema_ref": content_schema,
            "content_ref": "content:" + d(payload).removeprefix("urn:sha256:"),
            "content_digest": d(payload),
            "source_kind": source_kind,
            "source_ref": source_ref,
            "source_digest": SOURCE_DIGEST,
            "evidence_refs": ["ev-1"],
            "provenance_refs": ["prov-1"],
            "derived_from_refs": [],
            "consolidates_refs": [],
            "created_at": format_utc_timestamp(self.clock.now()),
            "valid_from": format_utc_timestamp(valid_from or NOW - timedelta(minutes=10)),
            "retention_policy_ref": "retention:standard",
            "confidence": confidence,
            "policy_bundle_digest": POLICY_BUNDLE,
            "ontology_release_digest": ONTOLOGY,
            "governed_context_digest": ctx.digest(),
            "instruction_eligible": False,
            "taint_labels": list(taint),
            "representation_kinds": ["STRUCTURED", "FULL_TEXT"],
            "lifecycle_status": lifecycle,
        }
        candidate.update(bindings if bindings is not None else {"project_id": "project-1"})
        for name, value in (("valid_until", valid_until), ("expires_at", expires_at)):
            if value is not None:
                candidate[name] = format_utc_timestamp(value)
        if version > 1:
            candidate["supersedes_ref"] = memory_version_ref(item_id, version - 1)
        embedding = embed(text) if vector else None
        if embedding is not None:
            candidate["representation_kinds"] = ["STRUCTURED", "FULL_TEXT", "VECTOR"]
            candidate.update(model)
            candidate["embedding_ref"] = f"embedding:{item_id}:v{version}"
            candidate["embedding_digest"] = vector_digest(embedding)
        self._ops += 1
        self.admission.admit(
            {
                "operation_id": f"op-{self._ops}",
                "governed_context": ctx.to_mapping(),
                "governed_context_digest": ctx.digest(),
                "deadline": format_utc_timestamp(self.clock.now() + timedelta(seconds=30)),
                "candidate": candidate,
            },
            binding=binding(ctx),
            payload=payload,
        )
        record = self.ledger.get(item_id, version)
        assert record is not None
        if commit:
            self.coordinator.commit(record, payload=payload, embedding=embedding)
        return record

    def lifecycle(self, record: AdmittedMemoryVersion, status: str, text: str) -> AdmittedMemoryVersion:
        """Append and commit version n+1 with ``status``, as the lifecycle coordinator will."""

        mapping = record.item.to_mapping()
        version = record.item.memory_version + 1
        mapping.update(
            memory_version=version,
            supersedes_ref=record.item.version_ref,
            lifecycle_status=status,
            created_at=format_utc_timestamp(self.clock.now()),
        )
        if "embedding_ref" in mapping:
            mapping["embedding_ref"] = f"embedding:{record.item.memory_item_id}:v{version}"
        item = GovernedMemoryItem.from_mapping(mapping)
        audit_event = {"action": "transitionMemoryLifecycle", "item_digest": item.digest(), "to_status": status}
        next_record = AdmittedMemoryVersion(
            item=item,
            item_digest=item.digest(),
            idempotency_key=idempotency_key(item, f"lifecycle-{version}"),
            lifecycle_event={"event_type": "MEMORY_LIFECYCLE", "to_status": status},
            audit_event=audit_event,
            receipt=MemoryReceipt(
                memory_item_id=item.memory_item_id,
                memory_version=version,
                content_digest=item.content_digest,
                lifecycle_status=status,
                governed_context_digest=item.governed_context_digest,
                audit_ref=canonical_digest(audit_event),
            ),
        )
        self.ledger.append(next_record)
        self.coordinator.commit(
            next_record, payload=text.encode(), embedding=embed(text) if item.embedding_digest else None
        )
        return next_record


def unit_world() -> World:
    return World(
        metadata=base.MemMetadata(),
        content=base.MemContent(),
        lexical=base.MemIndex(),
        vector=base.MemIndex(),
        cipher=base.FixtureCipher(),
    )


def request(
    mode: RetrievalMode,
    *,
    ctx: GovernedContext = CALLER,
    text: str | None = None,
    query_vector: Sequence[float] | None = None,
    model: Mapping[str, object] = VECTOR_MODEL,
    kinds: Sequence[str] = ("EPISODIC",),
    scopes: Sequence[str] = ("PROJECT",),
    top_k: int = 10,
    filters: Mapping[str, object] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    if mode in (RetrievalMode.FULL_TEXT, RetrievalMode.HYBRID):
        parameters["text"] = text
    if mode in (RetrievalMode.VECTOR, RetrievalMode.HYBRID):
        parameters["vector"] = list(query_vector if query_vector is not None else embed(text or ""))
        parameters["vector_profile"] = dict(model)
    if filters is not None:
        parameters["filters"] = dict(filters)
    body: dict[str, Any] = {
        "operation_id": "search-1",
        "governed_context": ctx.to_mapping(),
        "governed_context_digest": ctx.digest(),
        "deadline": format_utc_timestamp(NOW + timedelta(seconds=30)),
        "query_contract_id": CONTRACTS[mode].contract_id,
        "query_contract_version": CONTRACTS[mode].version,
        "retrieval_mode": mode.value,
        "memory_kinds": list(kinds),
        "memory_scopes": list(scopes),
        "parameters": parameters,
        "top_k": top_k,
        "ranking_profile_ref": PROFILE.profile_ref,
    }
    body.update(extra)
    return body


def refs(response: MemorySearchResponse) -> list[str]:
    return [memory_version_ref(hit.memory_item_id, hit.memory_version) for hit in response.hits]


def assert_retrieval_error(action: Any, reason: str, detail: str) -> MemoryRetrievalError:
    with pytest.raises(MemoryRetrievalError) as caught:
        action()
    assert (caught.value.reason_code, caught.value.detail_code) == (reason, detail), caught.value
    return caught.value


INDEX_LOOKUPS = frozenset({"search", "search_eligible", "score_entries"})


def searches(world: World) -> list[tuple[str, str, str]]:
    """Every index read that ranks or scores entries (lookups, never writes)."""

    return [call for call in world.lexical.calls + world.vector.calls if call[0] in INDEX_LOOKUPS]


# --------------------------------------------------------------------------
# Unit branch logic (0051 in-memory fixtures; not qualifying evidence)
# --------------------------------------------------------------------------


def _drop(body: dict[str, Any], name: str) -> dict[str, Any]:
    body.pop(name)
    return body


def _params(body: dict[str, Any], **changes: Any) -> dict[str, Any]:
    body["parameters"].update(changes)
    return body


INVALID_REQUESTS = [
    ("extra-field", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", cursor="x"), "MEMORY_SCHEMA_INVALID", "REQUEST_INVALID"),
    ("missing-field", lambda: _drop(request(RetrievalMode.FULL_TEXT, text="alpha"), "ranking_profile_ref"), "MEMORY_SCHEMA_INVALID", "REQUEST_INVALID"),
    ("unknown-contract", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", query_contract_version="9.9"), "MEMORY_SCHEMA_INVALID", "QUERY_CONTRACT_UNKNOWN"),
    ("mode-mismatch", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", retrieval_mode="VECTOR"), "MEMORY_SCHEMA_INVALID", "QUERY_CONTRACT_MODE_MISMATCH"),
    ("unknown-parameter", lambda: _params(request(RetrievalMode.FULL_TEXT, text="alpha"), vector=[1.0]), "MEMORY_SCHEMA_INVALID", "PARAMETERS_INVALID"),
    ("missing-parameter", lambda: request(RetrievalMode.HYBRID, text="alpha") | {"parameters": {"text": "alpha"}}, "MEMORY_SCHEMA_INVALID", "PARAMETERS_INVALID"),
    ("blank-text", lambda: request(RetrievalMode.FULL_TEXT, text="  "), "MEMORY_SCHEMA_INVALID", "QUERY_TEXT_INVALID"),
    ("nul-text", lambda: request(RetrievalMode.FULL_TEXT, text="a\x00b"), "MEMORY_SCHEMA_INVALID", "QUERY_TEXT_INVALID"),
    ("open-filters", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", filters={"owner": "x"}), "MEMORY_SCHEMA_INVALID", "FILTERS_INVALID"),
    ("bad-confidence", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", filters={"min_confidence": 2}), "MEMORY_SCHEMA_INVALID", "FILTERS_INVALID"),
    ("bad-source-kind", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", filters={"source_kinds": ["RUMOUR"]}), "MEMORY_SCHEMA_INVALID", "FILTERS_INVALID"),
    ("top-k-zero", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", top_k=0), "MEMORY_SCHEMA_INVALID", "REQUEST_INVALID"),
    ("top-k-bool", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", top_k=True), "MEMORY_SCHEMA_INVALID", "REQUEST_INVALID"),
    ("top-k-over", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", top_k=101), "MEMORY_SCHEMA_INVALID", "REQUEST_INVALID"),
    ("unknown-profile", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", ranking_profile_ref="urn:x"), "MEMORY_SCHEMA_INVALID", "RANKING_PROFILE_UNKNOWN"),
    ("explanation-type", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", include_explanation="yes"), "MEMORY_SCHEMA_INVALID", "REQUEST_INVALID"),
    ("valid-at-format", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", valid_at="yesterday"), "MEMORY_SCHEMA_INVALID", "REQUEST_INVALID"),
    ("valid-at-future", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", valid_at=format_utc_timestamp(NOW + timedelta(hours=1))), "MEMORY_SCHEMA_INVALID", "VALID_AT_IN_FUTURE"),
    ("unknown-kind", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", kinds=["GOSSIP"]), "MEMORY_SCHEMA_INVALID", "REQUEST_INVALID"),
    ("duplicate-scope", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", scopes=["PROJECT", "PROJECT"]), "MEMORY_SCHEMA_INVALID", "REQUEST_INVALID"),
    ("unsupported-capability", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", kinds=["WORKING"], scopes=["PROJECT"]), "UNSUPPORTED_CAPABILITY", "KIND_SCOPE_UNSUPPORTED"),
    ("vector-profile-open", lambda: _params(request(RetrievalMode.VECTOR, text="alpha"), vector_profile={**VECTOR_MODEL, "x": 1}), "MEMORY_SCHEMA_INVALID", "VECTOR_PROFILE_INVALID"),
    ("vector-profile-digest", lambda: _params(request(RetrievalMode.VECTOR, text="alpha"), vector_profile={**VECTOR_MODEL, "embedding_model_digest": "sha:x"}), "MEMORY_SCHEMA_INVALID", "VECTOR_PROFILE_INVALID"),
    ("vector-dimensions", lambda: request(RetrievalMode.VECTOR, query_vector=[1.0, 0.0]), "MEMORY_SCHEMA_INVALID", "QUERY_VECTOR_INVALID"),
    ("vector-zero", lambda: request(RetrievalMode.VECTOR, query_vector=[0.0] * DIMENSIONS), "MEMORY_SCHEMA_INVALID", "QUERY_VECTOR_INVALID"),
    ("vector-nan", lambda: request(RetrievalMode.VECTOR, query_vector=[float("nan")] * DIMENSIONS), "MEMORY_SCHEMA_INVALID", "REQUEST_INVALID"),
    ("vector-bool", lambda: request(RetrievalMode.VECTOR, query_vector=[True] * DIMENSIONS), "MEMORY_SCHEMA_INVALID", "REQUEST_INVALID"),
    ("deadline-passed", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", deadline=format_utc_timestamp(NOW)), "POLICY_DENIED", "DEADLINE_EXCEEDED"),
    ("gcs-digest", lambda: request(RetrievalMode.FULL_TEXT, text="alpha", governed_context_digest=d("other")), "GOVERNED_CONTEXT_MISMATCH", None),
]


@pytest.mark.parametrize(("label", "build", "reason", "detail"), INVALID_REQUESTS, ids=[c[0] for c in INVALID_REQUESTS])
def test_invalid_requests_fail_before_policy_or_any_index_read(label: str, build: Any, reason: str, detail: str | None) -> None:
    world = unit_world()
    world.admit("item-1", "alpha bravo")
    with pytest.raises(MemoryRetrievalError) as caught:
        world.service().search(build(), binding=binding())
    assert caught.value.reason_code == reason
    if detail is not None:
        assert caught.value.detail_code == detail
    assert caught.value.correlation_id == base.CORRELATION
    assert searches(world) == [] and world.policy.calls == [] and world.audit.events == []


def test_a_valid_request_of_every_mode_is_accepted() -> None:
    world = unit_world()
    world.admit("item-1", "alpha bravo")
    for mode in RetrievalMode:
        response = world.service().search(request(mode, text="alpha bravo"), binding=binding())
        assert refs(response) == ["urn:ocor:memory:item-1:v1"], mode


def test_a_missing_or_foreign_binding_is_refused() -> None:
    world = unit_world()
    assert_retrieval_error(
        lambda: world.service().search(request(RetrievalMode.FULL_TEXT, text="a"), binding=None),
        "AUTHENTICATION_REQUIRED", "BINDING_MISSING",
    )
    foreign = binding(context(principal="agent-principal-2"))
    with pytest.raises(MemoryRetrievalError) as caught:
        world.service().search(request(RetrievalMode.FULL_TEXT, text="a"), binding=foreign)
    assert caught.value.reason_code == "GOVERNED_CONTEXT_MISMATCH"
    assert searches(world) == []


POLICY_FAILURES = [
    ("denied", {"permitted": False}, "POLICY_DENIED", "RETRIEVAL_DENIED"),
    ("stale-bundle", {"bundle": d("policy-bundle:memory:0")}, "STALE_POLICY", "POLICY_BUNDLE_MISMATCH"),
    ("kind-not-authorized", {"kinds": frozenset({MemoryKind.SEMANTIC})}, "AUTHORITY_DENIED", "KIND_OR_SCOPE_NOT_AUTHORIZED"),
    ("scope-not-authorized", {"scopes": frozenset({MemoryScope.RUN})}, "AUTHORITY_DENIED", "KIND_OR_SCOPE_NOT_AUTHORIZED"),
    ("policy-unavailable", {"fail": True}, "CONTROL_PLANE_UNAVAILABLE", "POLICY_UNAVAILABLE"),
]


@pytest.mark.parametrize(("label", "changes", "reason", "detail"), POLICY_FAILURES, ids=[c[0] for c in POLICY_FAILURES])
def test_pre_query_policy_failures_are_audited_and_read_no_candidate(label: str, changes: dict[str, Any], reason: str, detail: str) -> None:
    world = unit_world()
    world.admit("item-1", "alpha bravo")
    world.policy = dataclasses.replace(world.policy, **changes)
    assert_retrieval_error(
        lambda: world.service().search(request(RetrievalMode.HYBRID, text="alpha"), binding=binding()), reason, detail
    )
    assert searches(world) == []
    assert [event["action"] for event in world.audit.events] == ["searchMemory.denied"]
    assert world.audit.events[0]["reason_code"] == reason


def test_unknown_stop_state_and_unaudited_answers_fail_closed() -> None:
    world = unit_world()
    world.admit("item-1", "alpha bravo")
    world.stop.fail = True
    assert_retrieval_error(
        lambda: world.service().search(request(RetrievalMode.FULL_TEXT, text="alpha"), binding=binding()),
        "CONTROL_PLANE_UNAVAILABLE", "STOP_STATE_UNAVAILABLE",
    )
    assert searches(world) == []
    world.stop.fail = False
    world.audit.fail = True
    assert_retrieval_error(
        lambda: world.service().search(request(RetrievalMode.FULL_TEXT, text="alpha"), binding=binding()),
        "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE",
    )


def test_a_materialisation_policy_outage_fails_closed() -> None:
    world = unit_world()
    world.admit("item-1", "alpha bravo")

    class Broken(GrantPolicy):
        def authorize_materialization(self, item: GovernedMemoryItem, ctx: GovernedContext) -> MemoryPolicyDecision:
            raise ConnectionError("opa unavailable")

    world.policy = Broken()
    assert_retrieval_error(
        lambda: world.service().search(request(RetrievalMode.FULL_TEXT, text="alpha"), binding=binding()),
        "CONTROL_PLANE_UNAVAILABLE", "POLICY_UNAVAILABLE",
    )


def test_a_stop_epoch_change_before_materialisation_returns_no_hit() -> None:
    world = unit_world()
    world.admit("item-1", "alpha bravo")
    world.stop.bump_after = 1
    assert_retrieval_error(
        lambda: world.service().search(request(RetrievalMode.FULL_TEXT, text="alpha"), binding=binding()),
        "STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED",
    )
    # OCOR-DEV-REM-0020 F5: the refusal is an audited denial, never a success receipt.
    assert [(e["action"], e["reason_code"]) for e in world.audit.events] == [("searchMemory.denied", "STOP_EPOCH_MISMATCH")]


@pytest.mark.parametrize(
    "changes",
    [{"lexical_weight": -0.1}, {"candidate_pool": 0}, {"candidate_pool": 101}, {"recency_half_life_seconds": 0},
     {"source_quality": (("EVIDENCE", 1.0),)}, {"taint_policy": (("MODEL_GENERATED", 1.5),)}, {"vector_weight": float("inf")}],
    ids=["negative-weight", "pool-zero", "pool-over", "half-life", "quality-not-closed", "taint-over-one", "infinite-weight"],
)
def test_ranking_profiles_are_validated(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RankingProfile(**changes)


def test_ranking_profile_and_query_contract_digests_pin_every_field() -> None:
    assert RankingProfile().digest == PROFILE.digest
    assert RankingProfile(lexical_weight=0.36).digest != PROFILE.digest
    assert RankingProfile(source_quality=tuple((k, 0.5) for k, _ in PROFILE.source_quality)).digest != PROFILE.digest
    digests = {contract.digest for contract in DEFAULT_QUERY_CONTRACTS}
    assert len(digests) == 4
    with pytest.raises(ValueError):
        RetrievalLimits(max_top_k=0)


def test_ineligible_hits_are_skipped_until_the_pool_is_full_then_backpressure() -> None:
    world = unit_world()
    for n in range(6):
        world.admit(f"q-{n}", "shared token quarantined", lifecycle="QUARANTINED")
    world.admit("active-1", "shared item")
    # OCOR-DEV-REM-0020 F1: lifecycle is an index predicate, so quarantined
    # versions never reach the pool and cost nothing against the declared bound.
    tight = world.service(ranking_profiles=(RankingProfile(candidate_pool=1),), limits=RetrievalLimits(max_candidates=4))
    response = tight.search(request(RetrievalMode.FULL_TEXT, text="shared token", top_k=1), binding=binding())
    assert refs(response) == ["urn:ocor:memory:active-1:v1"]
    # Only a post-query drop (here a live policy denial) consumes the bound.
    for n in range(6):
        world.admit(f"denied-{n}", "shared token denied")
        world.policy.denied_items.add(f"denied-{n}")
    service = world.service(ranking_profiles=(RankingProfile(candidate_pool=1),), limits=RetrievalLimits(max_candidates=8))
    response = service.search(request(RetrievalMode.FULL_TEXT, text="shared token", top_k=1), binding=binding())
    assert refs(response) == ["urn:ocor:memory:active-1:v1"]
    assert_retrieval_error(
        lambda: tight.search(request(RetrievalMode.FULL_TEXT, text="shared token", top_k=1), binding=binding()),
        "REPRESENTATION_NOT_READY", "RETRIEVAL_BACKPRESSURE",
    )


def test_a_lexical_hit_of_another_representation_version_fails_closed() -> None:
    world = unit_world()
    world.admit("item-1", "alpha bravo")
    service = world.service(lexical_profile=LexicalProfile(version=2))
    assert_retrieval_error(
        lambda: service.search(request(RetrievalMode.FULL_TEXT, text="alpha"), binding=binding()),
        "REPRESENTATION_NOT_READY", "REPRESENTATION_VERSION_MISMATCH",
    )


def test_hits_whose_item_digest_differs_from_the_metadata_are_dropped() -> None:
    world = unit_world()
    world.admit("item-1", "alpha bravo")
    original = world.coordinator.lexical_candidates

    def forged(partition: MemoryPartition, query: str, *, limit: int) -> tuple[BoundHit, ...]:
        return tuple(dataclasses.replace(hit, item_digest=d("forged")) for hit in original(partition, query, limit=limit))

    world.coordinator.lexical_candidates = forged  # type: ignore[method-assign]
    response = world.service().search(request(RetrievalMode.FULL_TEXT, text="alpha"), binding=binding())
    assert response.hits == ()


def test_metrics_use_a_bounded_label_set() -> None:
    world = unit_world()
    world.admit("item-1", "alpha bravo")
    service = world.service()
    service.search(request(RetrievalMode.FULL_TEXT, text="alpha"), binding=binding())
    with pytest.raises(MemoryRetrievalError):
        service.search(request(RetrievalMode.FULL_TEXT, text="alpha", top_k=0), binding=binding())
    with pytest.raises(MemoryRetrievalError):
        service.search({"retrieval_mode": "x" * 50}, binding=binding())
    assert dict(service.metrics()) == {
        ("FULL_TEXT", "OK"): 1,
        ("FULL_TEXT", "MEMORY_SCHEMA_INVALID"): 1,
        ("UNPARSED", "MEMORY_SCHEMA_INVALID"): 1,
    }


# --------------------------------------------------------------------------
# Real backends (qualifying): PostgreSQL, Qdrant and OpenBao via the 0051 adapters
# --------------------------------------------------------------------------


class OpenBaoHarness(base.OpenBaoHarness):
    PREFIX = "ocor-test-0052-openbao-"


class CompactQdrantVectorIndex(base.QdrantVectorIndex):
    """The 0051 Qdrant adapter with one segment and a 1 MiB WAL per collection.

    One collection per partition and representation version is the isolation
    design; the sealed 0023 harness keeps Qdrant storage on a 256 MiB tmpfs and
    a default collection takes about 7.7 MiB of it (one segment per CPU), so the
    non-interference worlds would exhaust it.  One segment takes about 1.1 MiB;
    search over these small collections is an exact scan either way.
    """

    def _call(self, method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
        name = path.removeprefix("/collections/")
        if method == "PUT" and path.startswith("/collections/") and "/" not in name and isinstance(body, dict):
            body = {
                **body,
                "wal_config": {"wal_capacity_mb": 1, "wal_segments_ahead": 0},
                "optimizers_config": {"default_segment_number": 1},
            }
        return super()._call(method, path, body)


@dataclass
class Backends:
    dsn: str
    qdrant: Any
    bao: OpenBaoHarness
    schemas: list[str] = field(default_factory=list)

    def release(self) -> None:
        """Drop every schema and Qdrant collection created by the current test."""

        try:
            with psycopg.connect(self.dsn, autocommit=True) as conn:
                for schema in self.schemas:
                    conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            for schema in self.schemas:
                index = CompactQdrantVectorIndex(self.qdrant.endpoint, schema)
                for name in index.collections():
                    status, _ = index._call("DELETE", f"/collections/{name}")
                    assert status == 200, (name, status)
            self.schemas.clear()

    def world(self) -> World:
        schema = f"ocor_t0052_{uuid.uuid4().hex[:12]}"
        self.schemas.append(schema)
        postgres = base.PostgresStores(self.dsn, schema)
        return World(
            metadata=postgres,
            content=base.PostgresContentStore(postgres),
            lexical=base.PostgresLexicalIndex(postgres),
            vector=CompactQdrantVectorIndex(self.qdrant.endpoint, schema),
            cipher=base.OpenBaoTransitCipher(self.bao),
        )

    def fresh(self, world: World) -> World:
        """New adapter instances and connections over the same backends (new run)."""

        postgres = base.PostgresStores(self.dsn, world.metadata.schema)
        clone = World(
            metadata=postgres,
            content=base.PostgresContentStore(postgres),
            lexical=base.PostgresLexicalIndex(postgres),
            vector=CompactQdrantVectorIndex(self.qdrant.endpoint, world.metadata.schema),
            cipher=base.OpenBaoTransitCipher(self.bao),
        )
        clone.ledger = world.ledger
        clone.clock = world.clock
        clone.coordinator = MemoryStoreCoordinator(
            ledger=world.ledger, metadata=postgres, content=clone.content, cipher=clone.cipher,
            lexical=clone.lexical, vector=clone.vector, clock=world.clock,  # type: ignore[arg-type]
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
    """Per-test worlds on the shared real backends, released after the test."""

    try:
        yield live_backends
    finally:
        live_backends.release()


def test_qualifying_backends_are_real_and_pinned(backends: Backends) -> None:
    assert base.QDRANT_IMAGE.endswith(base.LOCKED_IMAGES["qdrant"].split("@", 1)[1])
    assert base._docker("inspect", backends.qdrant.container, "--format", "{{.Config.Image}}") == base.QDRANT_IMAGE
    assert base._docker("inspect", backends.bao.container, "--format", "{{.Config.Image}}") == base.LOCKED_IMAGES["openbao"]
    with psycopg.connect(backends.dsn) as conn:
        row = conn.execute("SHOW server_version").fetchone()
    assert row is not None and str(row[0]).startswith("16.")


def test_structured_retrieval_returns_exact_active_versions_with_pinned_filters(backends: Backends) -> None:
    world = backends.world()
    world.admit("obs-1", "radar contact north sector", confidence=0.9)
    world.admit("pref-1", "operator prefers night shifts", kind="PREFERENCE", source_kind="PREFERENCE", taint=("HUMAN_SUPPLIED",), confidence=0.6)
    world.admit("model-1", "model guess about convoy", source_kind="MODEL_OUTPUT", taint=("MODEL_GENERATED",), confidence=0.95)
    world.admit("plan-1", "plan draft", content_schema="urn:ocor:memory-content:plan:1.0", confidence=0.7)
    service = world.service()
    every = service.search(request(RetrievalMode.STRUCTURED, kinds=["EPISODIC", "PREFERENCE"]), binding=binding())
    assert sorted(refs(every)) == sorted(f"urn:ocor:memory:{i}:v1" for i in ("obs-1", "pref-1", "model-1", "plan-1"))
    assert searches(world) == []  # STRUCTURED reads the metadata authority, never an index
    cases = {
        "source": ({"source_kinds": ["OBSERVATION"]}, {"obs-1", "plan-1"}),
        "confidence": ({"min_confidence": 0.85}, {"obs-1", "model-1"}),
        "schema": ({"content_schema_refs": ["urn:ocor:memory-content:plan:1.0"]}, {"plan-1"}),
        "taint": ({"exclude_taint_labels": ["MODEL_GENERATED"]}, {"obs-1", "pref-1", "plan-1"}),
        "kind": (None, {"pref-1"}),
    }
    for label, (filters, expected) in cases.items():
        kinds = ["PREFERENCE"] if label == "kind" else ["EPISODIC", "PREFERENCE"]
        response = service.search(request(RetrievalMode.STRUCTURED, kinds=kinds, filters=filters), binding=binding())
        assert {hit.memory_item_id for hit in response.hits} == expected, label
        if filters is not None:
            pinned = response.receipt["query"]["filters"]  # type: ignore[index]
            for name, value in filters.items():
                assert pinned[name] == (sorted(value) if isinstance(value, list) else value), label
    hit = every.hits[0]
    record = world.ledger.get(hit.memory_item_id, hit.memory_version)
    assert record is not None
    assert (hit.item_digest, hit.content_digest, hit.content_ref) == (record.item_digest, record.item.content_digest, record.item.content_ref)
    assert hit.evidence_refs == ("ev-1",) and hit.provenance_refs == ("prov-1",)
    assert hit.result_marking_ref == M_RESTRICTED
    assert set(hit.to_mapping()) == {
        "memory_item_id", "memory_version", "content_ref", "content_digest", "final_score",
        "score_factors", "evidence_refs", "provenance_refs", "result_marking_ref", "explanation_ref",
    }


def _expected_score(factors: Mapping[str, float]) -> float:
    relevance = (
        PROFILE.lexical_weight * factors["lexical"]
        + PROFILE.vector_weight * factors["vector"]
        + PROFILE.recency_weight * factors["recency"]
        + PROFILE.confidence_weight * factors["confidence"]
        + PROFILE.source_quality_weight * factors["source_quality"]
    )
    return relevance * factors["policy"] * factors["diversity"]


def test_full_text_and_vector_retrieval_rank_by_their_own_representation(backends: Backends) -> None:
    world = backends.world()
    world.admit("a", "convoy convoy convoy bridge")
    world.admit("b", "convoy bridge river crossing")
    world.admit("c", "weather report clear skies")
    service = world.service()
    lexical = service.search(request(RetrievalMode.FULL_TEXT, text="convoy"), binding=binding())
    assert refs(lexical) == ["urn:ocor:memory:a:v1", "urn:ocor:memory:b:v1"]
    assert lexical.hits[0].score_factors["lexical"] == 1.0
    assert 0 < lexical.hits[1].score_factors["lexical"] < 1.0
    assert all(hit.score_factors["vector"] == 0.0 for hit in lexical.hits)
    nearest = service.search(request(RetrievalMode.VECTOR, text="weather report clear skies"), binding=binding())
    assert refs(nearest)[0] == "urn:ocor:memory:c:v1"
    assert nearest.hits[0].score_factors["vector"] == pytest.approx(1.0, abs=1e-5)
    assert all(hit.score_factors["lexical"] == 0.0 for hit in nearest.hits)
    assert len(nearest.hits) == 3  # every eligible vector is a neighbour
    assert nearest.receipt["representation_versions"] == {
        "VECTOR": VectorProfile(**VECTOR_MODEL).representation_version  # type: ignore[arg-type]
    }
    assert lexical.receipt["representation_versions"] == {"FULL_TEXT": LexicalProfile().representation_version}
    for response in (lexical, nearest):
        for hit in response.hits:
            assert hit.final_score == pytest.approx(_expected_score(hit.score_factors))


def test_hybrid_ranking_records_every_factor_separately(backends: Backends) -> None:
    world = backends.world()
    world.admit("ev", "bridge crossing at dawn", source_kind="EVIDENCE", confidence=0.9)
    world.admit("mo", "bridge crossing at dawn predicted", source_kind="MODEL_OUTPUT", taint=("MODEL_GENERATED",), confidence=0.9)
    world.admit("old", "bridge crossing old report", valid_from=NOW - timedelta(days=14))
    world.admit("dup1", "bridge crossing duplicate", source_ref="src-telemetry-1")
    response = world.service().search(request(RetrievalMode.HYBRID, text="bridge crossing at dawn"), binding=binding())
    by_id = {hit.memory_item_id: hit for hit in response.hits}
    assert set(by_id) == {"ev", "mo", "old", "dup1"}
    for hit in response.hits:
        assert set(hit.score_factors) == {"lexical", "vector", "recency", "confidence", "source_quality", "diversity", "policy"}
        assert hit.final_score == pytest.approx(_expected_score(hit.score_factors))
    assert by_id["mo"].score_factors["policy"] == 0.5 and by_id["ev"].score_factors["policy"] == 1.0
    assert by_id["ev"].score_factors["source_quality"] == 1.0 and by_id["mo"].score_factors["source_quality"] == 0.4
    assert by_id["old"].score_factors["recency"] < by_id["ev"].score_factors["recency"]
    assert by_id["old"].score_factors["recency"] == pytest.approx(0.5 ** ((14 * 86400) / PROFILE.recency_half_life_seconds), rel=1e-3)
    # Diversity: every item shares one source; the n-th ranked one is penalised n times.
    diversities = [hit.score_factors["diversity"] for hit in response.hits]
    assert diversities == [1.0 / (1.0 + PROFILE.diversity_penalty * n) for n in range(4)]
    assert [hit.final_score for hit in response.hits] == sorted((hit.final_score for hit in response.hits), reverse=True)
    explanation = response.explanations[response.hits[0].explanation_ref or ""]
    assert explanation["ranking_profile_digest"] == PROFILE.digest
    assert explanation["score_factors"] == dict(response.hits[0].score_factors)
    assert response.receipt["representation_versions"] == {
        "FULL_TEXT": LexicalProfile().representation_version,
        "VECTOR": VectorProfile(**VECTOR_MODEL).representation_version,  # type: ignore[arg-type]
    }


def test_the_receipt_pins_query_representation_ranking_filters_and_exact_versions(backends: Backends) -> None:
    world = backends.world()
    v1 = world.admit("item", "supply depot location alpha")
    service = world.service()
    body = request(RetrievalMode.HYBRID, text="supply depot", filters={"min_confidence": 0.5})
    first = service.search(body, binding=binding())
    assert refs(first) == ["urn:ocor:memory:item:v1"]
    receipt = first.receipt
    assert receipt["query_digest"] == first.query_digest == canonical_digest(receipt["query"])
    assert receipt["query"]["ranking_profile_digest"] == PROFILE.digest  # type: ignore[index]
    assert receipt["query"]["query_contract_digest"] == CONTRACTS[RetrievalMode.HYBRID].digest  # type: ignore[index]
    assert receipt["query"]["vector_digest"] == vector_digest(embed("supply depot"))  # type: ignore[index]
    assert receipt["hits"] == [{
        "memory_version_ref": "urn:ocor:memory:item:v1", "item_digest": v1.item_digest,
        "content_digest": v1.item.content_digest, "final_score": first.hits[0].final_score,
    }]
    assert first.audit_ref == canonical_digest(dict(receipt))
    assert world.audit.events[-1]["audit_ref"] == first.audit_ref
    assert receipt["correlation_id"] == base.CORRELATION and receipt["causation_id"] == "search-1"
    # Same request, same state: identical pins (deterministic replay).
    assert service.search(body, binding=binding()).to_mapping() == first.to_mapping()
    # Every pinned dimension changes the query digest.
    variants = [
        request(RetrievalMode.HYBRID, text="supply depot", filters={"min_confidence": 0.6}),
        request(RetrievalMode.HYBRID, text="supply depots", filters={"min_confidence": 0.5}),
        request(RetrievalMode.HYBRID, text="supply depot", filters={"min_confidence": 0.5}, top_k=9),
        request(RetrievalMode.HYBRID, text="supply depot", filters={"min_confidence": 0.5}, model=VECTOR_MODEL_V2),
        request(RetrievalMode.HYBRID, text="supply depot", filters={"min_confidence": 0.5}, include_explanation=False),
    ]
    digests = {service.search(v, binding=binding()).query_digest for v in variants}
    assert len(digests) == len(variants) and first.query_digest not in digests
    # A new version is a new exact pin; the earlier receipt still names v1 exactly.
    v2 = world.admit("item", "supply depot location bravo", version=2)
    second = service.search(body, binding=binding())
    assert refs(second) == ["urn:ocor:memory:item:v2"]
    assert second.hits[0].item_digest == v2.item_digest != v1.item_digest
    assert receipt["hits"][0]["memory_version_ref"] == "urn:ocor:memory:item:v1"  # type: ignore[index]
    partition = MemoryPartition.for_item(v1.item)
    assert world.coordinator.read_version(partition, "item", 1).item.digest() == v1.item_digest


def _populate_authorized(world: World) -> None:
    world.admit("auth-1", "harbour patrol schedule alpha", confidence=0.9)
    world.admit("auth-2", "harbour patrol schedule bravo", ctx=context(compartments=("bravo",)), source_ref="src-telemetry-1")
    world.admit("auth-3", "harbour inspection unclassified", marking=M_RESTRICTED, ctx=context(compartments=("alpha", "bravo")))
    world.admit("auth-4", "harbour patrol team memory", kind="TEAM_SHARED", scope="TEAM", bindings={"team_id": "team-1"})
    world.admit("auth-5", "harbour patrol run note", scope="RUN", bindings={"agent_run_id": "run-1"})


def _populate_unauthorized(world: World) -> None:
    """Items the caller must never see or be influenced by, each a distinct class."""

    text = "harbour patrol schedule secret leak"
    world.admit("x-compartment", text, ctx=context(compartments=("charlie",)))
    world.admit("x-compartment-mixed", text, ctx=context(compartments=("alpha", "charlie")))
    world.admit("x-tenant", text, ctx=context(tenant="tenant-b"))
    world.admit("x-organization", text, ctx=context(organization="org-b"))
    world.admit("x-marking", text, ctx=context(marking=M_SECRET))
    world.admit("x-purpose", text, ctx=context(purpose="training"))
    world.admit("x-domain", text, ctx=context(domain="domain-intel"))
    world.admit("x-project", text, bindings={"project_id": "project-2"})
    world.admit("x-run", text, scope="RUN", bindings={"agent_run_id": "run-2"})
    world.admit("x-agent", text, scope="AGENT", bindings={"agent_id": "agent-2"})
    world.admit("x-federated", text, scope="FEDERATED", bindings={"federation_policy_ref": "federation:fed-1"})
    world.admit("x-quarantined", text, lifecycle="QUARANTINED")
    world.admit("x-proposed", text, lifecycle="PROPOSED")
    world.admit("x-expired", text, expires_at=NOW + timedelta(minutes=1))
    world.admit("x-not-yet-valid", text, valid_from=NOW + timedelta(minutes=5))
    world.admit("x-validity-elapsed", text, valid_from=NOW - timedelta(days=2), valid_until=NOW + timedelta(seconds=30))
    world.admit("x-pending", text, commit=False)
    revoked = world.admit("x-revoked", text)
    world.lifecycle(revoked, "REVOKED", text)
    world.admit("x-denied", text)
    world.admit("x-other-kind", text, kind="PREFERENCE", source_kind="PREFERENCE", taint=("HUMAN_SUPPLIED",))
    world.admit("x-reclassified", text)
    world.admit("x-reclassified", text, version=2, ctx=context(marking=M_SECRET))


def _searchable_now(world: World) -> None:
    # Expiry and validity are evaluated on the boundary clock, not the request.
    world.clock.advance(timedelta(minutes=2))
    world.policy.denied_items.add("x-denied")


def _responses(world: World) -> dict[str, dict[str, Any]]:
    service = world.service()
    caller_scopes = ["PROJECT", "TEAM", "RUN", "AGENT", "FEDERATED"]
    out: dict[str, dict[str, Any]] = {}
    for mode in RetrievalMode:
        body = request(
            mode, text="harbour patrol schedule secret leak", kinds=["EPISODIC", "TEAM_SHARED"],
            scopes=caller_scopes, deadline=format_utc_timestamp(world.clock.now() + timedelta(seconds=30)),
        )
        response = service.search(body, binding=binding())
        out[mode.value] = {
            "response": response.to_mapping(),
            "explanations": {k: dict(v) for k, v in response.explanations.items()},
            "receipt": dict(response.receipt),
        }
    return out


def test_unauthorized_items_affect_no_content_existence_rank_count_or_explanation(backends: Backends) -> None:
    clean = backends.world()
    _populate_authorized(clean)
    _searchable_now(clean)
    noisy = backends.world()
    _populate_authorized(noisy)
    _populate_unauthorized(noisy)
    _searchable_now(noisy)
    expected = _responses(clean)
    observed = _responses(noisy)
    for mode in RetrievalMode:
        assert observed[mode.value] == expected[mode.value], mode
        ids = {hit["memory_item_id"] for hit in observed[mode.value]["response"]["hits"]}
        assert not any(i.startswith("x-") for i in ids), (mode, ids)
    assert {hit["memory_item_id"] for hit in observed["STRUCTURED"]["response"]["hits"]} == {f"auth-{n}" for n in range(1, 6)}
    # Policy first: indexes were searched only inside authorized partitions.
    authorized = {MemoryPartition.for_item(r.item).digest for r in noisy.ledger.records() if r.item.memory_item_id.startswith("auth-")}
    searched = {partition for _, partition, _ in searches(noisy)}
    assert searched and searched <= authorized
    unauthorized_partitions = {
        MemoryPartition.for_item(r.item).digest for r in noisy.ledger.records()
        if r.item.memory_item_id.startswith("x-")
    } - authorized
    assert unauthorized_partitions and not searched & unauthorized_partitions
    # The noisy indexes really contain the unauthorized vectors and documents.
    assert any(call[0] == "upsert" and call[1] in unauthorized_partitions for call in noisy.lexical.calls)


def test_a_query_matching_only_unauthorized_items_is_indistinguishable_from_no_match(backends: Backends) -> None:
    world = backends.world()
    _populate_authorized(world)
    _populate_unauthorized(world)
    _searchable_now(world)
    service = world.service()

    def shape(text: str) -> dict[str, Any]:
        body = request(RetrievalMode.FULL_TEXT, text=text, deadline=format_utc_timestamp(world.clock.now() + timedelta(seconds=30)))
        mapping = service.search(body, binding=binding()).to_mapping()
        return {k: v for k, v in mapping.items() if k not in {"query_digest", "audit_ref"}}

    assert shape("leak") == shape("nonexistentterm") == {
        "retrieval_mode": "FULL_TEXT", "ranking_profile_ref": PROFILE.profile_ref, "hits": [],
        "governed_context_digest": CALLER.digest(),
    }


def test_explicit_authority_opens_cross_project_domain_and_federated_retrieval(backends: Backends) -> None:
    world = backends.world()
    world.admit("p2", "joint exercise notes", bindings={"project_id": "project-2"})
    world.admit("intel", "joint exercise notes", ctx=context(domain="domain-intel"))
    world.admit("fed", "joint exercise notes", scope="FEDERATED", bindings={"federation_policy_ref": "federation:fed-1"})
    body = request(RetrievalMode.FULL_TEXT, text="joint exercise", scopes=["PROJECT", "FEDERATED"])
    assert world.service().search(body, binding=binding()).hits == ()
    world.policy.scope_bindings["project_id"] = frozenset({"project-1", "project-2"})
    world.policy.scope_bindings["federation_policy_ref"] = frozenset({"federation:fed-1"})
    world.policy.domains = frozenset({"domain-intel"})
    granted = world.service().search(body, binding=binding())
    assert sorted(hit.memory_item_id for hit in granted.hits) == ["fed", "intel", "p2"]
    assert granted.receipt["authorization"]["domains"] == ["domain-intel"]  # type: ignore[index]
    tenant_b = context(tenant="tenant-b", compartments=("alpha", "bravo"))
    assert world.service().search(request(RetrievalMode.FULL_TEXT, text="joint exercise", ctx=tenant_b), binding=binding(tenant_b)).hits == ()


def test_a_parallel_embedding_representation_is_searched_only_under_its_own_pin(backends: Backends) -> None:
    world = backends.world()
    world.admit("m1", "satellite pass window", model=VECTOR_MODEL)
    world.admit("m2", "satellite pass window", model=VECTOR_MODEL_V2)
    service = world.service()
    first = service.search(request(RetrievalMode.VECTOR, text="satellite pass window", model=VECTOR_MODEL), binding=binding())
    second = service.search(request(RetrievalMode.VECTOR, text="satellite pass window", model=VECTOR_MODEL_V2), binding=binding())
    assert refs(first) == ["urn:ocor:memory:m1:v1"] and refs(second) == ["urn:ocor:memory:m2:v1"]
    assert first.receipt["representation_versions"] != second.receipt["representation_versions"]


def test_revocation_expiry_and_reclassification_remove_items_from_every_output(backends: Backends) -> None:
    world = backends.world()
    keep = world.admit("keep", "border checkpoint traffic")
    revoke = world.admit("revoke", "border checkpoint traffic")
    world.admit("expire", "border checkpoint traffic", expires_at=NOW + timedelta(minutes=5))
    world.admit("reclass", "border checkpoint traffic")
    service = world.service()
    body = request(RetrievalMode.HYBRID, text="border checkpoint traffic")
    before = service.search(body, binding=binding())
    assert {hit.memory_item_id for hit in before.hits} == {"keep", "revoke", "expire", "reclass"}
    world.lifecycle(revoke, "REVOKED", "border checkpoint traffic")
    world.admit("reclass", "border checkpoint traffic", version=2, ctx=context(marking=M_SECRET))
    world.clock.advance(timedelta(minutes=6))
    after = service.search(
        request(RetrievalMode.HYBRID, text="border checkpoint traffic", deadline=format_utc_timestamp(world.clock.now() + timedelta(seconds=30))),
        binding=binding(),
    )
    assert refs(after) == [keep.item.version_ref]
    assert len(after.receipt["hits"]) == 1 and len(after.explanations) == 1  # type: ignore[arg-type]
    assert after.hits[0].score_factors["lexical"] == 1.0  # normalised over the eligible pool only
    assert all("revoke" not in str(v) and "expire" not in str(v) for v in after.explanations.values())
    secret = context(compartments=("alpha", "bravo"), marking=M_SECRET)
    cleared = service.search(
        request(RetrievalMode.HYBRID, text="border checkpoint traffic", ctx=secret, deadline=format_utc_timestamp(world.clock.now() + timedelta(seconds=30))),
        binding=binding(secret),
    )
    assert sorted(refs(cleared)) == ["urn:ocor:memory:keep:v1", "urn:ocor:memory:reclass:v2"]


def test_a_delegation_revoked_or_kill_switch_raised_mid_search_leaves_no_influence(backends: Backends) -> None:
    world = backends.world()
    world.admit("item", "artillery position report")
    service = world.service()
    body = request(RetrievalMode.HYBRID, text="artillery position")
    world.stop.bump_after = 1
    assert_retrieval_error(lambda: service.search(body, binding=binding()), "STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED")
    # OCOR-DEV-REM-0020 F5: audited denial, no success receipt and no hit.
    assert [(e["action"], e["reason_code"]) for e in world.audit.events] == [("searchMemory.denied", "STOP_EPOCH_MISMATCH")]

    class RevokedAfterPlan(GrantPolicy):
        def authorize_materialization(self, item: GovernedMemoryItem, ctx: GovernedContext) -> MemoryPolicyDecision:
            decision = super().authorize_materialization(item, ctx)
            revoked = sum(call.startswith("materialize:") for call in self.calls) > 1
            return dataclasses.replace(decision, permitted=decision.permitted and not revoked)

    world.stop = StopState()
    world.policy = RevokedAfterPlan()
    assert_retrieval_error(
        lambda: world.service().search(body, binding=binding()), "REPRESENTATION_NOT_READY", "CANDIDATE_CHANGED"
    )
    assert [(e["action"], e["detail_code"]) for e in world.audit.events[1:]] == [("searchMemory.denied", "CANDIDATE_CHANGED")]


def test_partial_and_drifted_projections_are_never_materialised(backends: Backends) -> None:
    world = backends.world()
    world.admit("good", "river ford depth")
    drift = world.admit("drift", "river ford depth")
    service = world.service()
    original_upsert = world.vector.inner.upsert

    def outage(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("qdrant unavailable")

    world.vector.inner.upsert = outage
    with pytest.raises(MemoryAdmissionError):
        world.admit("partial", "river ford depth")
    world.vector.inner.upsert = original_upsert
    assert world.metadata.get("partial", 1).state.value == "PENDING"
    response = service.search(request(RetrievalMode.HYBRID, text="river ford depth"), binding=binding())
    assert {hit.memory_item_id for hit in response.hits} == {"good", "drift"}
    partition = MemoryPartition.for_item(drift.item)
    table = world.lexical.inner.table(partition, LexicalProfile().representation_version)
    pointer = next(p for p in world.metadata.get("drift", 1).staged.pointers if p.representation_kind.value == "FULL_TEXT")
    with world.metadata.connect() as conn:
        conn.execute(
            f'UPDATE "{world.metadata.schema}"."{table}" SET document = %s WHERE store_ref = %s',
            ("river ford depth tampered", pointer.store_ref),
        )
    audit_before = len(world.audit.events)
    with pytest.raises(Exception) as caught:
        service.search(request(RetrievalMode.FULL_TEXT, text="river ford depth"), binding=binding())
    assert getattr(caught.value, "reason_code", None) == "REPRESENTATION_NOT_READY"
    # OCOR-DEV-REM-0020 F5: one audited denial and no success receipt.
    assert [(e["action"], e["reason_code"]) for e in world.audit.events[audit_before:]] == [
        ("searchMemory.denied", "REPRESENTATION_NOT_READY")
    ]


def test_retrieval_is_durable_across_fresh_adapters(backends: Backends) -> None:
    world = backends.world()
    _populate_authorized(world)
    first = world.service().search(request(RetrievalMode.HYBRID, text="harbour patrol"), binding=binding())
    clone = backends.fresh(world)
    again = clone.service().search(request(RetrievalMode.HYBRID, text="harbour patrol"), binding=binding())
    assert again.to_mapping() == first.to_mapping() and len(first.hits) == 3


def test_unit_index_double_is_not_used_by_qualifying_worlds(backends: Backends) -> None:
    world = backends.world()
    assert isinstance(world.lexical.inner, base.PostgresLexicalIndex)
    assert isinstance(world.vector.inner, base.QdrantVectorIndex)
    assert isinstance(world.cipher, base.OpenBaoTransitCipher)
    assert not isinstance(world.metadata, base.MemMetadata)

