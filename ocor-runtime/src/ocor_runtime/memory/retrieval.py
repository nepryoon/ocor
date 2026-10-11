"""C8 governed memory -- policy-first structured, full-text, vector and hybrid retrieval.

Implements the ``MemorySearchPort`` (``searchMemory``) slice of the
``GovernedMemoryService`` (ADD v1.3 Part II §§2.3-2.8, 2.10, 2.12; LLD v1.1
§§2.8.1-2.8.4, 7.2 ``FGM-06``/``FGM-10``/``FGM-16``):

* The request is the closed ``MemorySearchRequest`` of the governed-memory
  OpenAPI contract.  It names a registered, versioned query contract, the mode
  (``STRUCTURED``, ``FULL_TEXT``, ``VECTOR`` or ``HYBRID``), kinds, scopes, the
  mode parameters, an optional ``valid_at``, ``top_k`` and a registered ranking
  profile.  The GCS is rebuilt from the authenticated binding and its digest is
  recalculated before anything else is read.
* Policy is evaluated before candidate lookup.  The live retrieval decision
  (``MemoryRetrievalPolicy``) yields a ``RetrievalAuthorization`` -- kinds,
  scopes, explicit scope-owner bindings, cross-domain and federation Authority,
  compatible purposes, accepted policy bundles and ontology releases -- and the
  authorized partition set is derived from it and from the caller's GCS
  (tenant, organization, domain, compartments, marking dominance) using only
  the partition tuple.  Indexes are queried only inside those partitions, so an
  unauthorized item never enters an ANN graph, a lexical ranking, score
  normalization, a count, a page or an explanation.
* The eligibility predicates -- requested kinds and scopes, the structured
  filters, head version, ``ACTIVE``, validity at ``valid_at`` and expiry on the
  boundary clock -- run inside every index and metadata query (version 2
  ports, ``EligibilityPredicate``), so ineligible versions never occupy a
  candidate slot; the complete re-validation below is kept as defence in
  depth.  Backpressure is raised only by the declared ``max_candidates`` bound
  on candidates dropped after the query (OCOR-DEV-REM-0020).
* Policy is evaluated again for every candidate before materialisation: the
  exact committed version must still be the item's head, ``ACTIVE``, valid at
  ``valid_at``, unexpired on the boundary clock, without deletion epoch, of a
  requested kind/scope present in the capability matrix, dominated by the
  caller's marking, inside the caller's compartments, matching the pinned
  structured filters, and permitted by ``authorize_materialization``.  A
  candidate failing any check is dropped before it can occupy a candidate
  slot, so the pool always holds exactly the best eligible candidates.
  ``STRUCTURED`` re-validates lazily in rank order and returns the
  deterministic top-k of the eligible set, whatever the partition size.
* Ranking keeps lexical, vector, recency, confidence, source-quality,
  diversity and policy factors separately (``score_factors``).  Lexical scores
  are normalised over the eligible candidate pool only; vector scores are the
  cosine similarity of the pinned representation.  In ``HYBRID`` every
  candidate of the union of the two pools is scored by both backends on its
  own committed entries, so no factor is a default; a candidate without the
  pinned representation of one mode is not rankable and is dropped.  Scores
  are retrieval evidence, never confidence in truth or Authority.
* Every response pins the query (``query_digest``), the query contract, the
  representation versions searched, the ranking profile digest, the
  authorization and filters, and every returned item/version with its item and
  content digests, in an audit receipt whose digest is ``audit_ref``.  The
  receipt is written through the audit port before the response is returned.
* There is no result or candidate cache: every request recomputes candidates
  from the metadata authority and the partitioned projections, so no cache can
  carry influence between requesters (ADD v1.3 Part II §2.8).
* The stop epoch read when the plan is made must still hold before
  materialisation, after every materialised hit and right before the receipt
  is written; a kill switch or delegation revocation in between fails the
  request closed with ``STOP_EPOCH_MISMATCH`` and no hit.
* Eligibility is re-validated before and after the content read of every hit
  and once more over every hit right before the receipt is written (exact
  committed head, ``ACTIVE``, no deletion epoch, same stage digest, live
  materialisation policy): a revocation, quarantine, correction or policy
  change committed while content is read fails the request closed with
  ``CANDIDATE_CHANGED`` and no hit (OCOR-DEV-REM-0021).
* Every refusal after planning is recorded as an audited denial
  (``searchMemory.denied``); no success receipt is written for it.

The module is backend-free (``OCOR_LANGUAGE_POLICY.md`` row 8): stores,
indexes, policy, stop state and audit are ports.  Memory retrieval never
creates Authority, Approval, Decision, CapabilityLease or canonical state.
"""

from __future__ import annotations

import hmac
import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from ..kernel.canonical import (
    TimestampError,
    canonical_digest,
    format_utc_timestamp,
    parse_utc_timestamp,
)
from ..kernel.governance import TrustedClock
from ..kernel.governed_context import (
    GovernedContext,
    GovernedContextCodec,
    GovernedContextError,
    VerifiedGovernedContextBinding,
)
from .model import (
    CAPABILITY_MATRIX,
    DIGEST,
    SOURCE_TAINT,
    GovernedMemoryItem,
    LifecycleStatus,
    MarkingDominance,
    MemoryAdmissionError,
    MemoryKind,
    MemoryPolicyDecision,
    MemoryScope,
    RepresentationKind,
    SourceKind,
    memory_version_ref,
    parse_memory_version_ref,
)
from .stores import (
    BoundHit,
    EligibilityMetadataStore,
    EligibilityPredicate,
    LexicalProfile,
    MemoryMetadataStore,
    MemoryPartition,
    MemoryStoreCoordinator,
    RepresentationPointer,
    StoredVersion,
    VectorProfile,
    VersionState,
    eligibility_scope,
    vector_digest,
)

EXPLANATION_PREFIX = "urn:ocor:memory-explanation:"
MAX_TOP_K = 100


class RetrievalMode(StrEnum):
    STRUCTURED = "STRUCTURED"
    FULL_TEXT = "FULL_TEXT"
    VECTOR = "VECTOR"
    HYBRID = "HYBRID"


class MemoryRetrievalError(MemoryAdmissionError):
    """Fail-closed retrieval refusal carrying the closed memory Problem vocabulary."""


def _schema_error(detail: str, message: str) -> MemoryRetrievalError:
    return MemoryRetrievalError("MEMORY_SCHEMA_INVALID", detail, message)


def _hex(digest: str) -> str:
    return digest.removeprefix("urn:sha256:")


# --------------------------------------------------------------------------
# Named query contracts and ranking profiles
# --------------------------------------------------------------------------

ENVELOPE_FIELDS = frozenset(
    {"operation_id", "governed_context", "governed_context_digest", "deadline"}
)
REQUIRED_SEARCH_FIELDS = frozenset(
    {
        "query_contract_id",
        "query_contract_version",
        "retrieval_mode",
        "memory_kinds",
        "memory_scopes",
        "parameters",
        "top_k",
        "ranking_profile_ref",
    }
)
OPTIONAL_SEARCH_FIELDS = frozenset({"valid_at", "include_explanation"})
SEARCH_FIELDS = ENVELOPE_FIELDS | REQUIRED_SEARCH_FIELDS | OPTIONAL_SEARCH_FIELDS

# Closed parameter vocabulary per mode; ``filters`` is optional in every mode.
MODE_PARAMETERS: Mapping[RetrievalMode, frozenset[str]] = MappingProxyType(
    {
        RetrievalMode.STRUCTURED: frozenset(),
        RetrievalMode.FULL_TEXT: frozenset({"text"}),
        RetrievalMode.VECTOR: frozenset({"vector", "vector_profile"}),
        RetrievalMode.HYBRID: frozenset({"text", "vector", "vector_profile"}),
    }
)
FILTER_FIELDS = frozenset(
    {"source_kinds", "content_schema_refs", "min_confidence", "exclude_taint_labels"}
)
VECTOR_PROFILE_FIELDS = frozenset(
    {
        "embedding_model_ref",
        "embedding_model_digest",
        "embedding_dimensions",
        "embedding_normalization_profile",
    }
)
MAX_QUERY_TEXT = 4096


@dataclass(frozen=True, slots=True)
class MemoryQueryContract:
    """A named, versioned query contract bound to exactly one retrieval mode."""

    contract_id: str
    version: str
    mode: RetrievalMode

    def to_mapping(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "version": self.version,
            "mode": self.mode.value,
            "parameters": sorted(MODE_PARAMETERS[self.mode] | {"filters"}),
            "filters": sorted(FILTER_FIELDS),
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


DEFAULT_QUERY_CONTRACTS: tuple[MemoryQueryContract, ...] = tuple(
    MemoryQueryContract(
        f"urn:ocor:memory-query:{mode.value.lower().replace('_', '-')}", "1.0", mode
    )
    for mode in RetrievalMode
)


def _source_quality_default() -> tuple[tuple[str, float], ...]:
    return tuple(
        sorted(
            {
                SourceKind.EVIDENCE.value: 1.0,
                SourceKind.OBSERVATION.value: 0.9,
                SourceKind.TOOL_RESULT.value: 0.8,
                SourceKind.HUMAN_INPUT.value: 0.8,
                SourceKind.PROCEDURE.value: 0.8,
                SourceKind.PREFERENCE.value: 0.7,
                SourceKind.DERIVED_SUMMARY.value: 0.6,
                SourceKind.MEMORY_CONSOLIDATION.value: 0.6,
                SourceKind.MODEL_OUTPUT.value: 0.4,
            }.items()
        )
    )


def _taint_policy_default() -> tuple[tuple[str, float], ...]:
    labels = {label: 1.0 for label in SOURCE_TAINT.values()}
    labels["MODEL_GENERATED"] = 0.5
    return tuple(sorted(labels.items()))


@dataclass(frozen=True, slots=True)
class RankingProfile:
    """Versioned hybrid ranking profile; every factor is recorded separately.

    ``final_score = (Σ weight_f · factor_f) · policy · diversity`` over the
    lexical, vector, recency, confidence and source-quality factors.  ``policy``
    is the smallest taint multiplier of the item's labels; ``diversity`` is
    ``1 / (1 + diversity_penalty · n)`` where ``n`` counts already-ranked hits
    from the same source.
    """

    profile_ref: str = "urn:ocor:memory-ranking:balanced"
    version: int = 1
    lexical_weight: float = 0.35
    vector_weight: float = 0.35
    recency_weight: float = 0.1
    confidence_weight: float = 0.1
    source_quality_weight: float = 0.1
    recency_half_life_seconds: int = 7 * 24 * 3600
    diversity_penalty: float = 0.5
    candidate_pool: int = 16
    source_quality: tuple[tuple[str, float], ...] = field(default_factory=_source_quality_default)
    taint_policy: tuple[tuple[str, float], ...] = field(default_factory=_taint_policy_default)

    def __post_init__(self) -> None:
        weights = (
            self.lexical_weight,
            self.vector_weight,
            self.recency_weight,
            self.confidence_weight,
            self.source_quality_weight,
            self.diversity_penalty,
        )
        if not all(math.isfinite(w) and w >= 0 for w in weights):
            raise ValueError("ranking weights must be finite and non-negative")
        if self.recency_half_life_seconds < 1 or not 1 <= self.candidate_pool <= MAX_TOP_K:
            raise ValueError("ranking profile bounds are invalid")
        if {name for name, _ in self.source_quality} != {kind.value for kind in SourceKind}:
            raise ValueError("source quality must cover every source kind exactly")
        for _, value in self.source_quality + self.taint_policy:
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("quality and taint multipliers must lie in [0, 1]")

    def to_mapping(self) -> dict[str, object]:
        return {
            "profile_ref": self.profile_ref,
            "version": self.version,
            "lexical_weight": self.lexical_weight,
            "vector_weight": self.vector_weight,
            "recency_weight": self.recency_weight,
            "confidence_weight": self.confidence_weight,
            "source_quality_weight": self.source_quality_weight,
            "recency_half_life_seconds": self.recency_half_life_seconds,
            "diversity_penalty": self.diversity_penalty,
            "candidate_pool": self.candidate_pool,
            "source_quality": [[name, value] for name, value in self.source_quality],
            "taint_policy": [[name, value] for name, value in self.taint_policy],
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


# --------------------------------------------------------------------------
# Policy, stop-state and audit ports
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RetrievalAuthorization:
    """Live pre-query decision: what the caller may search, never what exists.

    ``scope_bindings`` maps each scope-owner binding name (``agent_run_id``,
    ``task_id``, ``agent_id``, ``team_id``, ``project_id``,
    ``federation_policy_ref``) to the values the caller holds explicit
    Authority for.  ``domains`` lists additional domains (cross-domain Authority).
    """

    permitted: bool
    decision_ref: str
    policy_bundle_digest: str
    memory_kinds: frozenset[MemoryKind]
    memory_scopes: frozenset[MemoryScope]
    scope_bindings: Mapping[str, frozenset[str]]
    domains: frozenset[str] = frozenset()
    compatible_purposes: frozenset[str] = frozenset()
    policy_bundle_digests: frozenset[str] = frozenset()
    ontology_release_digests: frozenset[str] = frozenset()
    reason: str = ""

    def to_mapping(self) -> dict[str, object]:
        return {
            "permitted": self.permitted,
            "decision_ref": self.decision_ref,
            "policy_bundle_digest": self.policy_bundle_digest,
            "memory_kinds": sorted(kind.value for kind in self.memory_kinds),
            "memory_scopes": sorted(scope.value for scope in self.memory_scopes),
            "scope_bindings": {
                name: sorted(values) for name, values in sorted(self.scope_bindings.items())
            },
            "domains": sorted(self.domains),
            "compatible_purposes": sorted(self.compatible_purposes),
            "policy_bundle_digests": sorted(self.policy_bundle_digests),
            "ontology_release_digests": sorted(self.ontology_release_digests),
        }


class MemoryRetrievalPolicy(Protocol):
    """Policy/Authority port evaluated before lookup and before materialisation."""

    def authorize_retrieval(
        self, request: SearchQuery, context: GovernedContext
    ) -> RetrievalAuthorization:
        """Return the live pre-query decision for this request."""

    def authorize_materialization(
        self, item: GovernedMemoryItem, context: GovernedContext
    ) -> MemoryPolicyDecision:
        """Return the live decision for materialising one exact item version."""


class StopEpochPort(Protocol):
    """Kill-switch / delegation stop epoch of the caller's governed context."""

    def current_epoch(self, context: GovernedContext) -> int:
        """Return the current stop epoch; a change means stop or revocation."""


class RetrievalAuditSink(Protocol):
    """Protected audit authority for access, denial and influence evidence."""

    def record(self, event: Mapping[str, object]) -> None:
        """Durably record one audit event or raise."""


# --------------------------------------------------------------------------
# Parsed request
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchFilters:
    source_kinds: frozenset[SourceKind] | None = None
    content_schema_refs: frozenset[str] | None = None
    min_confidence: float | None = None
    exclude_taint_labels: frozenset[str] = frozenset()

    def to_mapping(self) -> dict[str, object]:
        return {
            "source_kinds": None
            if self.source_kinds is None
            else sorted(kind.value for kind in self.source_kinds),
            "content_schema_refs": None
            if self.content_schema_refs is None
            else sorted(self.content_schema_refs),
            "min_confidence": self.min_confidence,
            "exclude_taint_labels": sorted(self.exclude_taint_labels),
        }

    def accepts(self, item: GovernedMemoryItem) -> bool:
        if self.source_kinds is not None and item.source_kind not in self.source_kinds:
            return False
        if (
            self.content_schema_refs is not None
            and item.content_schema_ref not in self.content_schema_refs
        ):
            return False
        if self.min_confidence is not None and item.confidence < self.min_confidence:
            return False
        return not self.exclude_taint_labels & set(item.taint_labels)


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """The validated, normalised ``MemorySearchRequest`` (envelope excluded)."""

    operation_id: str
    contract: MemoryQueryContract
    mode: RetrievalMode
    memory_kinds: frozenset[MemoryKind]
    memory_scopes: frozenset[MemoryScope]
    text: str | None
    vector: tuple[float, ...] | None
    vector_profile: VectorProfile | None
    filters: SearchFilters
    valid_at: datetime | None
    top_k: int
    ranking_profile: RankingProfile
    include_explanation: bool

    def to_mapping(self) -> dict[str, object]:
        """The pinned query: everything that can change candidates or ranking."""

        return {
            "query_contract_id": self.contract.contract_id,
            "query_contract_version": self.contract.version,
            "query_contract_digest": self.contract.digest,
            "retrieval_mode": self.mode.value,
            "memory_kinds": sorted(kind.value for kind in self.memory_kinds),
            "memory_scopes": sorted(scope.value for scope in self.memory_scopes),
            "text": self.text,
            "vector_digest": None if self.vector is None else vector_digest(self.vector),
            "vector_representation_version": None
            if self.vector_profile is None
            else self.vector_profile.representation_version,
            "filters": self.filters.to_mapping(),
            "valid_at": None if self.valid_at is None else format_utc_timestamp(self.valid_at),
            "top_k": self.top_k,
            "ranking_profile_ref": self.ranking_profile.profile_ref,
            "ranking_profile_digest": self.ranking_profile.digest,
            "include_explanation": self.include_explanation,
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


def _strings(name: str, value: object, *, min_items: int = 1) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) < min_items:
        raise _schema_error("REQUEST_INVALID", f"{name} must be an array of >= {min_items}")
    if not all(isinstance(entry, str) and entry for entry in value):
        raise _schema_error("REQUEST_INVALID", f"{name} items must be non-empty strings")
    if len(set(value)) != len(value):
        raise _schema_error("REQUEST_INVALID", f"{name} items must be unique")
    return tuple(value)


def _number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _schema_error("REQUEST_INVALID", f"{name} must be a number")
    if not math.isfinite(value):
        raise _schema_error("REQUEST_INVALID", f"{name} must be finite")
    return float(value)


def _parse_filters(value: object) -> SearchFilters:
    if not isinstance(value, Mapping) or not set(value) <= FILTER_FIELDS:
        raise _schema_error("FILTERS_INVALID", "filters is not the closed filter record")
    source_kinds: frozenset[SourceKind] | None = None
    if "source_kinds" in value:
        try:
            source_kinds = frozenset(
                SourceKind(kind) for kind in _strings("source_kinds", value["source_kinds"])
            )
        except ValueError as exc:
            raise _schema_error("FILTERS_INVALID", "source_kinds has an unknown kind") from exc
    schemas = (
        frozenset(_strings("content_schema_refs", value["content_schema_refs"]))
        if "content_schema_refs" in value
        else None
    )
    minimum = None
    if "min_confidence" in value:
        minimum = _number("min_confidence", value["min_confidence"])
        if not 0 <= minimum <= 1:
            raise _schema_error("FILTERS_INVALID", "min_confidence must lie in [0, 1]")
    excluded = (
        frozenset(_strings("exclude_taint_labels", value["exclude_taint_labels"]))
        if "exclude_taint_labels" in value
        else frozenset()
    )
    return SearchFilters(source_kinds, schemas, minimum, excluded)


def _parse_vector_profile(value: object) -> VectorProfile:
    if not isinstance(value, Mapping) or set(value) != VECTOR_PROFILE_FIELDS:
        raise _schema_error("VECTOR_PROFILE_INVALID", "vector_profile is not a closed record")
    dimensions = value["embedding_dimensions"]
    if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions < 1:
        raise _schema_error("VECTOR_PROFILE_INVALID", "embedding_dimensions must be >= 1")
    strings: dict[str, str] = {}
    for name in VECTOR_PROFILE_FIELDS - {"embedding_dimensions"}:
        raw = value[name]
        if not isinstance(raw, str) or not raw:
            raise _schema_error("VECTOR_PROFILE_INVALID", f"{name} must be a non-empty string")
        strings[name] = raw
    if DIGEST.fullmatch(strings["embedding_model_digest"]) is None:
        raise _schema_error("VECTOR_PROFILE_INVALID", "embedding_model_digest is not a digest")
    return VectorProfile(
        embedding_model_ref=strings["embedding_model_ref"],
        embedding_model_digest=strings["embedding_model_digest"],
        embedding_dimensions=dimensions,
        embedding_normalization_profile=strings["embedding_normalization_profile"],
    )


def _parse_vector(value: object, profile: VectorProfile) -> tuple[float, ...]:
    if not isinstance(value, list):
        raise _schema_error("QUERY_VECTOR_INVALID", "vector must be an array of numbers")
    values = tuple(_number("vector", entry) for entry in value)
    if len(values) != profile.embedding_dimensions:
        raise _schema_error("QUERY_VECTOR_INVALID", "vector does not fit embedding_dimensions")
    if not any(values):
        raise _schema_error("QUERY_VECTOR_INVALID", "vector must not be the zero vector")
    return values


# --------------------------------------------------------------------------
# Response, receipt and explanation
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MemoryHit:
    memory_item_id: str
    memory_version: int
    item_digest: str
    content_ref: str
    content_digest: str
    final_score: float
    score_factors: Mapping[str, float]
    evidence_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    result_marking_ref: str
    explanation_ref: str | None

    def to_mapping(self) -> dict[str, object]:
        """The closed ``MemoryHit`` of the OpenAPI contract (no raw vectors)."""

        hit: dict[str, object] = {
            "memory_item_id": self.memory_item_id,
            "memory_version": self.memory_version,
            "content_ref": self.content_ref,
            "content_digest": self.content_digest,
            "final_score": self.final_score,
            "score_factors": dict(self.score_factors),
            "evidence_refs": list(self.evidence_refs),
            "provenance_refs": list(self.provenance_refs),
            "result_marking_ref": self.result_marking_ref,
        }
        if self.explanation_ref is not None:
            hit["explanation_ref"] = self.explanation_ref
        return hit


@dataclass(frozen=True, slots=True)
class MemorySearchResponse:
    query_digest: str
    retrieval_mode: RetrievalMode
    ranking_profile_ref: str
    hits: tuple[MemoryHit, ...]
    governed_context_digest: str
    audit_ref: str
    receipt: Mapping[str, object]
    explanations: Mapping[str, Mapping[str, object]]

    def to_mapping(self) -> dict[str, object]:
        """The closed ``MemorySearchResponse`` of the OpenAPI contract."""

        return {
            "query_digest": self.query_digest,
            "retrieval_mode": self.retrieval_mode.value,
            "ranking_profile_ref": self.ranking_profile_ref,
            "hits": [hit.to_mapping() for hit in self.hits],
            "governed_context_digest": self.governed_context_digest,
            "audit_ref": self.audit_ref,
        }


@dataclass(frozen=True, slots=True)
class RetrievalLimits:
    """Boundary configuration of the search service (PoC resource limits)."""

    max_top_k: int = MAX_TOP_K
    max_candidates: int = 128
    max_clock_skew: timedelta = timedelta(seconds=30)

    def __post_init__(self) -> None:
        if not 1 <= self.max_top_k <= MAX_TOP_K or self.max_candidates < 1:
            raise ValueError("retrieval limits are invalid")


@dataclass(frozen=True, slots=True)
class _Plan:
    """Everything fixed before candidate lookup."""

    query: SearchQuery
    context: GovernedContext
    gcs_digest: str
    authorization: RetrievalAuthorization
    partitions: tuple[MemoryPartition, ...]
    now: datetime
    valid_at: datetime
    stop_epoch: int
    binding_ref: str
    predicate: EligibilityPredicate

    @property
    def partition_digests(self) -> frozenset[str]:
        return frozenset(partition.digest for partition in self.partitions)


@dataclass(slots=True)
class _Candidate:
    stored: StoredVersion
    item: GovernedMemoryItem
    partition: MemoryPartition
    lexical: float | None = None
    vector: float | None = None
    # False until the exact version has passed ``_eligible`` (STRUCTURED
    # candidates are re-validated lazily, in rank order).
    validated: bool = True


FACTOR_NAMES = (
    "lexical",
    "vector",
    "recency",
    "confidence",
    "source_quality",
    "diversity",
    "policy",
)


def _pointer(
    candidate: _Candidate, kind: str, representation_version: str
) -> RepresentationPointer | None:
    return next(
        (
            pointer
            for pointer in candidate.stored.staged.pointers
            if pointer.representation_kind.value == kind
            and pointer.representation_version == representation_version
        ),
        None,
    )


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------


class MemorySearchService:
    """``MemorySearchPort.searchMemory``: policy-first, fail-closed retrieval."""

    def __init__(
        self,
        *,
        coordinator: MemoryStoreCoordinator,
        metadata: MemoryMetadataStore,
        policy: MemoryRetrievalPolicy,
        markings: MarkingDominance,
        stop: StopEpochPort,
        audit: RetrievalAuditSink,
        clock: TrustedClock,
        contracts: Iterable[MemoryQueryContract] = DEFAULT_QUERY_CONTRACTS,
        ranking_profiles: Iterable[RankingProfile] = (RankingProfile(),),
        lexical_profile: LexicalProfile | None = None,
        limits: RetrievalLimits | None = None,
    ) -> None:
        self._coordinator = coordinator
        # Must be the coordinator's lexical profile; every lexical hit is checked.
        self._lexical_profile = lexical_profile if lexical_profile is not None else LexicalProfile()
        self._metadata = metadata
        self._policy = policy
        self._markings = markings
        self._stop = stop
        self._audit = audit
        self._clock = clock
        self._contracts = MappingProxyType(
            {(c.contract_id, c.version): c for c in contracts}
        )
        self._profiles = MappingProxyType({p.profile_ref: p for p in ranking_profiles})
        self._limits = limits if limits is not None else RetrievalLimits()
        # Bounded label set: (mode or "UNPARSED", outcome = "OK" or reason code).
        self._metrics: Counter[tuple[str, str]] = Counter()

    def metrics(self) -> Mapping[tuple[str, str], int]:
        return MappingProxyType(dict(self._metrics))

    # -- entry point ---------------------------------------------------------

    def search(
        self,
        request: Mapping[str, object],
        *,
        binding: VerifiedGovernedContextBinding | None,
    ) -> MemorySearchResponse:
        """Answer one search, or raise before anything unauthorized is read."""

        mode_label = "UNPARSED"
        if isinstance(request, Mapping):
            raw_mode = request.get("retrieval_mode")
            if isinstance(raw_mode, str) and raw_mode in RetrievalMode.__members__:
                mode_label = raw_mode
        if not isinstance(binding, VerifiedGovernedContextBinding):
            self._metrics[(mode_label, "AUTHENTICATION_REQUIRED")] += 1
            raise MemoryRetrievalError(
                "AUTHENTICATION_REQUIRED",
                "BINDING_MISSING",
                "retrieval requires an authenticated governed-context binding",
            )
        correlation_id = binding.expected.correlation_id
        try:
            response = self._search(request, binding)
        except MemoryAdmissionError as exc:
            if exc.correlation_id is None:
                exc.correlation_id = correlation_id
            self._metrics[(mode_label, exc.reason_code)] += 1
            raise
        self._metrics[(mode_label, "OK")] += 1
        return response

    def _search(
        self, request: Mapping[str, object], binding: VerifiedGovernedContextBinding
    ) -> MemorySearchResponse:
        now = self._clock.now()
        context, gcs_digest, operation_id, deadline = self._envelope(request, binding, now)
        query = self._parse(request, operation_id, now)
        try:
            plan = self._plan(query, context, gcs_digest, binding.binding_ref, now)
        except MemoryAdmissionError as exc:
            self._record_denial(query, context, gcs_digest, binding.binding_ref, exc, now)
            raise
        try:
            with eligibility_scope(plan.predicate):
                candidates = self._candidates(plan)
            ranked = self._rank(plan, candidates)
            if self._clock.now() >= deadline:
                raise MemoryRetrievalError(
                    "POLICY_DENIED", "DEADLINE_EXCEEDED", "retrieval deadline has passed"
                )
            return self._materialize(plan, ranked)
        except MemoryAdmissionError as exc:
            # Every refusal after planning is a denial of an authorized search.
            self._record_denial(
                query, context, gcs_digest, binding.binding_ref, exc, self._clock.now()
            )
            raise

    # -- request -------------------------------------------------------------

    def _envelope(
        self,
        request: Mapping[str, object],
        binding: VerifiedGovernedContextBinding,
        now: datetime,
    ) -> tuple[GovernedContext, str, str, datetime]:
        if not isinstance(request, Mapping):
            raise _schema_error("REQUEST_INVALID", "search request must be an object")
        keys = set(request)
        if not keys <= SEARCH_FIELDS or not (ENVELOPE_FIELDS | REQUIRED_SEARCH_FIELDS) <= keys:
            raise _schema_error(
                "REQUEST_INVALID", "search request is not the closed MemorySearchRequest"
            )
        operation_id = request["operation_id"]
        claimed = request["governed_context_digest"]
        raw_deadline = request["deadline"]
        if not all(isinstance(v, str) and v for v in (operation_id, claimed, raw_deadline)):
            raise _schema_error("ENVELOPE_INVALID", "envelope members must be non-empty strings")
        assert isinstance(operation_id, str) and isinstance(claimed, str)
        assert isinstance(raw_deadline, str)
        try:
            deadline = parse_utc_timestamp(raw_deadline)
        except TimestampError as exc:
            raise _schema_error("ENVELOPE_INVALID", "deadline must be a UTC timestamp") from exc
        if deadline <= now:
            raise MemoryRetrievalError(
                "POLICY_DENIED", "DEADLINE_EXCEEDED", "retrieval deadline has passed"
            )
        raw_context = request["governed_context"]
        if not isinstance(raw_context, Mapping):
            raise MemoryRetrievalError(
                "GOVERNED_CONTEXT_MISMATCH", "GCS_INVALID", "governed_context must be an object"
            )
        try:
            context = GovernedContextCodec.from_openapi(raw_context, binding, claimed)
        except GovernedContextError as exc:
            raise MemoryRetrievalError("GOVERNED_CONTEXT_MISMATCH", exc.code, str(exc)) from exc
        return context, context.digest(), operation_id, deadline

    def _parse(
        self, request: Mapping[str, object], operation_id: str, now: datetime
    ) -> SearchQuery:
        contract_id = request["query_contract_id"]
        contract_version = request["query_contract_version"]
        if not isinstance(contract_id, str) or not isinstance(contract_version, str):
            raise _schema_error("QUERY_CONTRACT_UNKNOWN", "query contract must be named")
        contract = self._contracts.get((contract_id, contract_version))
        if contract is None:
            raise _schema_error("QUERY_CONTRACT_UNKNOWN", "query contract is not registered")
        try:
            mode = RetrievalMode(str(request["retrieval_mode"]))
        except ValueError as exc:
            raise _schema_error("REQUEST_INVALID", "retrieval_mode is unknown") from exc
        if mode is not contract.mode:
            raise _schema_error(
                "QUERY_CONTRACT_MODE_MISMATCH", "retrieval_mode differs from the query contract"
            )
        try:
            kinds = frozenset(
                MemoryKind(k) for k in _strings("memory_kinds", request["memory_kinds"])
            )
            scopes = frozenset(
                MemoryScope(s) for s in _strings("memory_scopes", request["memory_scopes"])
            )
        except ValueError as exc:
            raise _schema_error("REQUEST_INVALID", "unknown memory kind or scope") from exc
        for kind in kinds:
            if not any(CAPABILITY_MATRIX[(kind, scope)] for scope in scopes):
                raise MemoryRetrievalError(
                    "UNSUPPORTED_CAPABILITY",
                    "KIND_SCOPE_UNSUPPORTED",
                    f"{kind.value} is not supported in any requested scope",
                )
        top_k = request["top_k"]
        if (
            isinstance(top_k, bool)
            or not isinstance(top_k, int)
            or not 1 <= top_k <= self._limits.max_top_k
        ):
            raise _schema_error("REQUEST_INVALID", "top_k is outside the configured bound")
        profile_ref = request["ranking_profile_ref"]
        profile = self._profiles.get(profile_ref) if isinstance(profile_ref, str) else None
        if profile is None:
            raise _schema_error("RANKING_PROFILE_UNKNOWN", "ranking profile is not registered")
        include = request.get("include_explanation", True)
        if not isinstance(include, bool):
            raise _schema_error("REQUEST_INVALID", "include_explanation must be a boolean")
        valid_at: datetime | None = None
        if "valid_at" in request:
            raw_valid_at = request["valid_at"]
            if not isinstance(raw_valid_at, str):
                raise _schema_error("REQUEST_INVALID", "valid_at must be a UTC timestamp")
            try:
                valid_at = parse_utc_timestamp(raw_valid_at)
            except TimestampError as exc:
                raise _schema_error("REQUEST_INVALID", "valid_at must be a UTC timestamp") from exc
            if valid_at > now + self._limits.max_clock_skew:
                raise _schema_error(
                    "VALID_AT_IN_FUTURE", "valid_at lies beyond the boundary clock"
                )
        parameters = request["parameters"]
        expected = MODE_PARAMETERS[mode]
        if not isinstance(parameters, Mapping) or not expected <= set(parameters) <= (
            expected | {"filters"}
        ):
            raise _schema_error(
                "PARAMETERS_INVALID", "parameters do not match the query contract"
            )
        text: str | None = None
        if "text" in expected:
            raw_text = parameters["text"]
            if not isinstance(raw_text, str) or not raw_text.strip():
                raise _schema_error("QUERY_TEXT_INVALID", "text must be a non-empty string")
            if len(raw_text) > MAX_QUERY_TEXT or "\x00" in raw_text:
                raise _schema_error("QUERY_TEXT_INVALID", "text is too long or contains NUL")
            text = raw_text
        vector_profile: VectorProfile | None = None
        vector: tuple[float, ...] | None = None
        if "vector" in expected:
            vector_profile = _parse_vector_profile(parameters["vector_profile"])
            vector = _parse_vector(parameters["vector"], vector_profile)
        filters = _parse_filters(parameters.get("filters", {}))
        return SearchQuery(
            operation_id=operation_id,
            contract=contract,
            mode=mode,
            memory_kinds=kinds,
            memory_scopes=scopes,
            text=text,
            vector=vector,
            vector_profile=vector_profile,
            filters=filters,
            valid_at=valid_at,
            top_k=top_k,
            ranking_profile=profile,
            include_explanation=include,
        )

    # -- policy before lookup -----------------------------------------------

    def _plan(
        self,
        query: SearchQuery,
        context: GovernedContext,
        gcs_digest: str,
        binding_ref: str,
        now: datetime,
    ) -> _Plan:
        valid_at = query.valid_at if query.valid_at is not None else now
        stop_epoch = self._stop_epoch(context)
        authorization = self._authorize(query, context)
        partitions = tuple(
            sorted(
                (
                    partition
                    for partition in self._metadata.partitions()
                    if self._partition_authorized(partition, query, context, authorization)
                ),
                key=lambda partition: partition.digest,
            )
        )
        filters = query.filters
        predicate = EligibilityPredicate(
            memory_kinds=frozenset(kind.value for kind in query.memory_kinds),
            memory_scopes=frozenset(scope.value for scope in query.memory_scopes),
            valid_at=valid_at,
            now=now,
            source_kinds=None
            if filters.source_kinds is None
            else frozenset(kind.value for kind in filters.source_kinds),
            content_schema_refs=filters.content_schema_refs,
            min_confidence=filters.min_confidence,
            exclude_taint_labels=filters.exclude_taint_labels,
        )
        return _Plan(
            query=query,
            context=context,
            gcs_digest=gcs_digest,
            authorization=authorization,
            partitions=partitions,
            now=now,
            valid_at=valid_at,
            stop_epoch=stop_epoch,
            binding_ref=binding_ref,
            predicate=predicate,
        )

    def _stop_epoch(self, context: GovernedContext) -> int:
        try:
            epoch = self._stop.current_epoch(context)
        except Exception as exc:  # noqa: BLE001 -- unknown stop state fails closed
            raise MemoryRetrievalError(
                "CONTROL_PLANE_UNAVAILABLE", "STOP_STATE_UNAVAILABLE", "stop state is unknown"
            ) from exc
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
            raise MemoryRetrievalError(
                "CONTROL_PLANE_UNAVAILABLE", "STOP_STATE_INVALID", "stop epoch is invalid"
            )
        return epoch

    def _authorize(
        self, query: SearchQuery, context: GovernedContext
    ) -> RetrievalAuthorization:
        try:
            authorization = self._policy.authorize_retrieval(query, context)
        except MemoryAdmissionError:
            raise
        except Exception as exc:  # noqa: BLE001 -- unavailable policy fails closed
            raise MemoryRetrievalError(
                "CONTROL_PLANE_UNAVAILABLE",
                "POLICY_UNAVAILABLE",
                "retrieval policy evaluation failed closed",
            ) from exc
        if not isinstance(authorization, RetrievalAuthorization):
            raise MemoryRetrievalError(
                "CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID", "no policy decision"
            )
        if authorization.policy_bundle_digest != context.policy_bundle_digest:
            raise MemoryRetrievalError(
                "STALE_POLICY",
                "POLICY_BUNDLE_MISMATCH",
                "policy decision was not evaluated against the context bundle",
            )
        if not authorization.permitted:
            raise MemoryRetrievalError(
                "POLICY_DENIED", "RETRIEVAL_DENIED", "retrieval policy denied the request"
            )
        if not query.memory_kinds <= authorization.memory_kinds or not (
            query.memory_scopes <= authorization.memory_scopes
        ):
            raise MemoryRetrievalError(
                "AUTHORITY_DENIED",
                "KIND_OR_SCOPE_NOT_AUTHORIZED",
                "a requested kind or scope is outside the caller's Authority",
            )
        return authorization

    def _partition_authorized(
        self,
        partition: MemoryPartition,
        query: SearchQuery,
        context: GovernedContext,
        authorization: RetrievalAuthorization,
    ) -> bool:
        """Decide on the partition tuple alone, before any candidate is read."""

        if (
            partition.tenant_id != context.tenant_id
            or partition.organization_id != context.organization_id
        ):
            return False  # cross-tenant/organization is deny-by-default
        if partition.domain_id != context.domain_id and (
            partition.domain_id not in authorization.domains
        ):
            return False
        if not set(partition.compartments) <= set(context.compartments):
            return False
        if partition.memory_scope not in query.memory_scopes:
            return False
        if partition.purpose != context.purpose and (
            partition.purpose not in authorization.compatible_purposes
        ):
            return False
        bundles = authorization.policy_bundle_digests | {context.policy_bundle_digest}
        releases = authorization.ontology_release_digests | {context.ontology_release_digest}
        if (
            partition.policy_bundle_digest not in bundles
            or partition.ontology_release_digest not in releases
        ):
            return False
        for name, value in partition.scope_bindings:
            if value not in authorization.scope_bindings.get(name, frozenset()):
                return False
        try:
            return self._markings.dominates(
                context.classification_marking_ref, partition.classification_marking_ref
            )
        except MemoryAdmissionError:
            return False  # a marking outside the lattice is never dominated

    # -- policy before materialisation ---------------------------------------

    def _eligible(self, plan: _Plan, memory_item_id: str, memory_version: int) -> _Candidate | None:
        """Re-validate one exact committed version against the plan and live policy."""

        stored = self._metadata.get(memory_item_id, memory_version)
        if stored is None or stored.state is not VersionState.COMMITTED:
            return None
        partition = stored.staged.partition
        if partition.digest not in plan.partition_digests:
            return None
        item = stored.staged.verify()
        query, context = plan.query, plan.context
        if self._metadata.head(item.memory_item_id) != item.memory_version:
            return None  # superseded, corrected or reclassified: never the exact current one
        if item.lifecycle_status is not LifecycleStatus.ACTIVE or item.deletion_epoch is not None:
            return None
        if item.memory_kind not in query.memory_kinds or item.memory_scope not in (
            query.memory_scopes
        ):
            return None
        if not CAPABILITY_MATRIX[(item.memory_kind, item.memory_scope)]:
            return None
        if item.valid_from > plan.valid_at or (
            item.valid_until is not None and item.valid_until <= plan.valid_at
        ):
            return None
        if item.expires_at is not None and item.expires_at <= plan.now:
            return None
        if not set(item.compartments) <= set(context.compartments):
            return None
        try:
            if not self._markings.dominates(
                context.classification_marking_ref, item.classification_marking_ref
            ):
                return None
        except MemoryAdmissionError:
            return None
        if not query.filters.accepts(item):
            return None
        try:
            decision = self._policy.authorize_materialization(item, context)
        except MemoryAdmissionError:
            raise
        except Exception as exc:  # noqa: BLE001 -- unavailable policy fails closed
            raise MemoryRetrievalError(
                "CONTROL_PLANE_UNAVAILABLE",
                "POLICY_UNAVAILABLE",
                "materialisation policy evaluation failed closed",
            ) from exc
        if not isinstance(decision, MemoryPolicyDecision):
            raise MemoryRetrievalError(
                "CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID", "no policy decision"
            )
        if decision.policy_bundle_digest != context.policy_bundle_digest:
            raise MemoryRetrievalError(
                "STALE_POLICY",
                "POLICY_BUNDLE_MISMATCH",
                "materialisation decision was not evaluated against the context bundle",
            )
        if not decision.permitted:
            return None
        return _Candidate(stored=stored, item=item, partition=partition)

    # -- candidates ----------------------------------------------------------

    def _pool(self, plan: _Plan) -> int:
        return max(plan.query.top_k, plan.query.ranking_profile.candidate_pool)

    def _index_pool(
        self,
        plan: _Plan,
        fetch: Callable[[MemoryPartition, int], Sequence[BoundHit]],
        expected_version: str,
    ) -> list[tuple[_Candidate, float]]:
        """The ``pool`` best eligible candidates of every authorized partition.

        The eligibility predicates already run inside the index query; hits
        dropped by the post-query re-validation (live policy, races) are
        skipped before they count, and the page is widened until ``pool``
        eligible candidates are found or the partition is exhausted, so a
        dropped item never displaces an eligible one.  A partition whose
        drops exceed the declared ``max_candidates`` bound fails closed
        (backpressure) instead of returning a silently different ranking.
        """

        pool = self._pool(plan)
        found: list[tuple[_Candidate, float]] = []
        for partition in plan.partitions:
            limit = min(pool, self._limits.max_candidates)
            while True:
                hits = fetch(partition, limit)
                eligible: list[tuple[_Candidate, float]] = []
                seen: set[str] = set()
                for hit in hits:
                    if hit.memory_version_ref in seen:
                        continue
                    seen.add(hit.memory_version_ref)
                    if hit.representation_version != expected_version:
                        raise MemoryRetrievalError(
                            "REPRESENTATION_NOT_READY",
                            "REPRESENTATION_VERSION_MISMATCH",
                            "an index hit is not of the pinned representation version",
                        )
                    item_id, version = parse_memory_version_ref(hit.memory_version_ref)
                    candidate = self._eligible(plan, item_id, version)
                    if candidate is not None and hmac.compare_digest(
                        candidate.stored.staged.item_digest, hit.item_digest
                    ):
                        eligible.append((candidate, hit.score))
                if len(eligible) >= pool or len(hits) < limit:
                    found.extend(eligible[:pool])
                    break
                if limit >= self._limits.max_candidates:
                    raise MemoryRetrievalError(
                        "REPRESENTATION_NOT_READY",
                        "RETRIEVAL_BACKPRESSURE",
                        "candidate pool exceeds the configured bound",
                    )
                limit = min(limit * 2, self._limits.max_candidates)
        found.sort(key=lambda entry: (-entry[1], entry[0].stored.staged.memory_version_ref))
        return found[:pool]

    def _candidates(self, plan: _Plan) -> list[_Candidate]:
        query = plan.query
        if query.mode is RetrievalMode.STRUCTURED:
            return self._structured(plan)
        merged: dict[str, _Candidate] = {}
        if query.mode in (RetrievalMode.FULL_TEXT, RetrievalMode.HYBRID):
            text = query.text
            assert text is not None
            lexical = self._index_pool(
                plan,
                lambda partition, limit: self._coordinator.lexical_candidates(
                    partition, text, limit=limit
                ),
                self._lexical_profile.representation_version,
            )
            for candidate, score in lexical:
                candidate.lexical = score
                merged[candidate.stored.staged.memory_version_ref] = candidate
        if query.mode in (RetrievalMode.VECTOR, RetrievalMode.HYBRID):
            profile, vector = query.vector_profile, query.vector
            assert profile is not None and vector is not None
            nearest = self._index_pool(
                plan,
                lambda partition, limit: self._coordinator.vector_candidates(
                    partition, profile, vector, limit=limit
                ),
                profile.representation_version,
            )
            for candidate, score in nearest:
                ref = candidate.stored.staged.memory_version_ref
                existing = merged.setdefault(ref, candidate)
                existing.vector = max(0.0, min(1.0, score))
        if query.mode is RetrievalMode.HYBRID:
            self._complete_hybrid(plan, merged)
        # Lexical scores are normalised over the eligible candidates only.
        top = max((c.lexical for c in merged.values() if c.lexical is not None), default=0.0)
        for candidate in merged.values():
            if candidate.lexical is not None:
                candidate.lexical = candidate.lexical / top if top > 0 else 0.0
        return list(merged.values())

    def _complete_hybrid(self, plan: _Plan, merged: dict[str, _Candidate]) -> None:
        """Compute the real missing factor of every candidate of the pool union.

        A candidate found by one index only is scored by the other index on
        its own committed entry, so every recorded factor is the backend's
        value and the ranking is the one its real factors give.  A candidate
        without an entry in the pinned representation of the other mode has
        no such value and is not rankable under the hybrid contract: it is
        dropped, never given a fabricated factor.
        """

        query = plan.query
        profile, vector, text = query.vector_profile, query.vector, query.text
        assert profile is not None and vector is not None and text is not None
        lexical_version = self._lexical_profile.representation_version
        missing: dict[tuple[str, str], list[tuple[_Candidate, RepresentationPointer]]] = {}
        partitions: dict[str, MemoryPartition] = {}
        for ref, candidate in sorted(merged.items()):
            wanted: list[tuple[str, RepresentationPointer | None]] = []
            if candidate.lexical is None:
                wanted.append(("FULL_TEXT", _pointer(candidate, "FULL_TEXT", lexical_version)))
            if candidate.vector is None:
                wanted.append(
                    ("VECTOR", _pointer(candidate, "VECTOR", profile.representation_version))
                )
            if any(pointer is None for _, pointer in wanted):
                del merged[ref]
                continue
            partitions[candidate.partition.digest] = candidate.partition
            for kind, pointer in wanted:
                assert pointer is not None
                missing.setdefault((kind, candidate.partition.digest), []).append(
                    (candidate, pointer)
                )
        for (kind, digest), entries in sorted(missing.items()):
            partition = partitions[digest]
            pointers = [pointer for _, pointer in entries]
            if kind == "FULL_TEXT":
                scores = self._coordinator.lexical_scores(partition, text, pointers)
                for candidate, pointer in entries:
                    candidate.lexical = scores[pointer.store_ref]
            else:
                scores = self._coordinator.vector_scores(partition, profile, vector, pointers)
                for candidate, pointer in entries:
                    candidate.vector = max(0.0, min(1.0, scores[pointer.store_ref]))

    def _structured(self, plan: _Plan) -> list[_Candidate]:
        """Every committed head version matching the plan's predicate, in metadata order.

        The predicate runs inside the metadata query; the exact versions are
        re-validated lazily in rank order, so the result is the deterministic
        top-k of the eligible set whatever the partition size.
        """

        metadata = self._metadata
        if not isinstance(metadata, EligibilityMetadataStore):
            raise MemoryRetrievalError(
                "REPRESENTATION_NOT_READY",
                "METADATA_PREDICATES_UNSUPPORTED",
                "the metadata store cannot evaluate eligibility predicates",
            )
        candidates: list[_Candidate] = []
        for partition in plan.partitions:
            for stored in metadata.eligible_versions(partition.digest, plan.predicate):
                staged = stored.staged
                if (
                    stored.state is not VersionState.COMMITTED
                    or staged.partition.digest != partition.digest
                ):
                    continue
                if RepresentationKind.STRUCTURED.value not in {
                    p.representation_kind.value for p in staged.pointers
                }:
                    continue
                candidates.append(
                    _Candidate(
                        stored=stored,
                        item=staged.verify(),
                        partition=partition,
                        validated=False,
                    )
                )
        return candidates

    # -- ranking -------------------------------------------------------------

    def _rank(
        self, plan: _Plan, candidates: list[_Candidate]
    ) -> list[tuple[_Candidate, float, dict[str, float]]]:
        profile = plan.query.ranking_profile
        quality = dict(profile.source_quality)
        taint = dict(profile.taint_policy)
        base: dict[str, tuple[float, dict[str, float]]] = {}
        for candidate in candidates:
            item = candidate.item
            age = max(0.0, (plan.now - item.valid_from).total_seconds())
            factors = {
                "lexical": candidate.lexical if candidate.lexical is not None else 0.0,
                "vector": candidate.vector if candidate.vector is not None else 0.0,
                "recency": 0.5 ** (age / profile.recency_half_life_seconds),
                "confidence": item.confidence,
                "source_quality": quality[item.source_kind.value],
                "policy": min((taint.get(label, 1.0) for label in item.taint_labels), default=1.0),
            }
            relevance = (
                profile.lexical_weight * factors["lexical"]
                + profile.vector_weight * factors["vector"]
                + profile.recency_weight * factors["recency"]
                + profile.confidence_weight * factors["confidence"]
                + profile.source_quality_weight * factors["source_quality"]
            )
            base[candidate.stored.staged.memory_version_ref] = (
                relevance * factors["policy"],
                factors,
            )
        remaining = {c.stored.staged.memory_version_ref: c for c in candidates}
        per_source: Counter[str] = Counter()
        ranked: list[tuple[_Candidate, float, dict[str, float]]] = []
        while remaining and len(ranked) < plan.query.top_k:
            best: tuple[float, str] | None = None
            for ref, candidate in remaining.items():
                repeats = per_source[candidate.item.source_ref]
                diversity = 1.0 / (1.0 + profile.diversity_penalty * repeats)
                score = base[ref][0] * diversity
                key = (-score, ref)
                if best is None or key < (-best[0], best[1]):
                    best = (score, ref)
            assert best is not None
            score, ref = best
            chosen = remaining.pop(ref)
            if not chosen.validated:
                # Dropping an ineligible version before it is chosen leaves the
                # ranking of the eligible ones exactly as if it never existed.
                staged = chosen.stored.staged
                fresh = self._eligible(plan, staged.memory_item_id, staged.memory_version)
                if fresh is None or fresh.stored.staged.stage_digest != staged.stage_digest:
                    continue
                chosen.validated = True
            factors = dict(base[ref][1])
            factors["diversity"] = 1.0 / (
                1.0 + profile.diversity_penalty * per_source[chosen.item.source_ref]
            )
            per_source[chosen.item.source_ref] += 1
            ranked.append((chosen, score, {name: factors[name] for name in FACTOR_NAMES}))
        return ranked

    # -- materialisation -----------------------------------------------------

    def _materialize(
        self, plan: _Plan, ranked: list[tuple[_Candidate, float, dict[str, float]]]
    ) -> MemorySearchResponse:
        self._require_stop_epoch(plan)
        query = plan.query
        hits: list[MemoryHit] = []
        explanations: dict[str, Mapping[str, object]] = {}
        representation_versions = self._representation_versions(query)
        for rank, (candidate, score, factors) in enumerate(ranked, start=1):
            staged = candidate.stored.staged
            # Re-check the exact version right before its content is read.
            self._require_unchanged(plan, candidate)
            materialized = self._coordinator.read_version(
                candidate.partition, staged.memory_item_id, staged.memory_version
            )
            item = materialized.item
            if not hmac.compare_digest(item.digest(), staged.item_digest):
                raise MemoryRetrievalError(
                    "INTERNAL_ERROR", "MATERIALIZED_DIGEST_MISMATCH", "item digest mismatch"
                )
            # A stop or revocation during the read leaves no hit behind.
            self._require_stop_epoch(plan)
            self._require_unchanged(plan, candidate)
            marking = self._markings.join([item.classification_marking_ref])
            explanation_ref: str | None = None
            if query.include_explanation:
                explanation: dict[str, object] = {
                    "query_digest": query.digest,
                    "retrieval_mode": query.mode.value,
                    "memory_version_ref": staged.memory_version_ref,
                    "rank": rank,
                    "final_score": score,
                    "score_factors": dict(factors),
                    "ranking_profile_digest": query.ranking_profile.digest,
                    "representation_versions": representation_versions,
                }
                explanation_ref = EXPLANATION_PREFIX + _hex(canonical_digest(explanation))
                explanations[explanation_ref] = MappingProxyType(explanation)
            hits.append(
                MemoryHit(
                    memory_item_id=item.memory_item_id,
                    memory_version=item.memory_version,
                    item_digest=staged.item_digest,
                    content_ref=item.content_ref,
                    content_digest=item.content_digest,
                    final_score=score,
                    score_factors=MappingProxyType(dict(factors)),
                    evidence_refs=item.evidence_refs,
                    provenance_refs=item.provenance_refs,
                    result_marking_ref=marking,
                    explanation_ref=explanation_ref,
                )
            )
        receipt: dict[str, object] = {
            "action": "searchMemory",
            "operation_id": query.operation_id,
            "causation_id": query.operation_id,
            "correlation_id": plan.context.correlation_id,
            "governed_context_digest": plan.gcs_digest,
            "binding_ref": plan.binding_ref,
            "query": query.to_mapping(),
            "query_digest": query.digest,
            "representation_versions": representation_versions,
            "authorization": plan.authorization.to_mapping(),
            "authorized_partitions_digest": canonical_digest(sorted(plan.partition_digests)),
            "stop_epoch": plan.stop_epoch,
            "valid_at": format_utc_timestamp(plan.valid_at),
            "evaluated_at": format_utc_timestamp(plan.now),
            "hits": [
                {
                    "memory_version_ref": memory_version_ref(
                        hit.memory_item_id, hit.memory_version
                    ),
                    "item_digest": hit.item_digest,
                    "content_digest": hit.content_digest,
                    "final_score": hit.final_score,
                }
                for hit in hits
            ],
        }
        audit_ref = canonical_digest(receipt)
        # A hit changed while a later one was read leaves no hit behind either.
        for candidate, _score, _factors in ranked:
            self._require_unchanged(plan, candidate)
        self._require_stop_epoch(plan)
        try:
            self._audit.record(MappingProxyType({**receipt, "audit_ref": audit_ref}))
        except Exception as exc:  # noqa: BLE001 -- no audit, no answer
            raise MemoryRetrievalError(
                "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE", "retrieval audit failed closed"
            ) from exc
        return MemorySearchResponse(
            query_digest=query.digest,
            retrieval_mode=query.mode,
            ranking_profile_ref=query.ranking_profile.profile_ref,
            hits=tuple(hits),
            governed_context_digest=plan.gcs_digest,
            audit_ref=audit_ref,
            receipt=MappingProxyType(receipt),
            explanations=MappingProxyType(explanations),
        )

    def _require_unchanged(self, plan: _Plan, candidate: _Candidate) -> None:
        """Fail closed unless the exact ranked version is still eligible as staged."""

        staged = candidate.stored.staged
        fresh = self._eligible(plan, staged.memory_item_id, staged.memory_version)
        if fresh is None or fresh.stored.staged.stage_digest != staged.stage_digest:
            raise MemoryRetrievalError(
                "REPRESENTATION_NOT_READY",
                "CANDIDATE_CHANGED",
                "a ranked version changed before its hit was returned",
            )

    def _require_stop_epoch(self, plan: _Plan) -> None:
        if self._stop_epoch(plan.context) != plan.stop_epoch:
            raise MemoryRetrievalError(
                "STOP_EPOCH_MISMATCH",
                "STOP_EPOCH_CHANGED",
                "stop epoch changed after the plan was made",
            )

    def _representation_versions(self, query: SearchQuery) -> dict[str, str]:
        versions: dict[str, str] = {}
        if query.mode is RetrievalMode.STRUCTURED:
            versions["STRUCTURED"] = "urn:ocor:memory-representation:metadata"
        if query.mode in (RetrievalMode.FULL_TEXT, RetrievalMode.HYBRID):
            versions["FULL_TEXT"] = self._lexical_profile.representation_version
        if query.vector_profile is not None:
            versions["VECTOR"] = query.vector_profile.representation_version
        return versions

    def _record_denial(
        self,
        query: SearchQuery,
        context: GovernedContext,
        gcs_digest: str,
        binding_ref: str,
        error: MemoryAdmissionError,
        now: datetime,
    ) -> None:
        event: dict[str, object] = {
            "action": "searchMemory.denied",
            "operation_id": query.operation_id,
            "causation_id": query.operation_id,
            "correlation_id": context.correlation_id,
            "governed_context_digest": gcs_digest,
            "binding_ref": binding_ref,
            "query_digest": query.digest,
            "reason_code": error.reason_code,
            "detail_code": error.detail_code,
            "evaluated_at": format_utc_timestamp(now),
        }
        try:
            self._audit.record(MappingProxyType({**event, "audit_ref": canonical_digest(event)}))
        except Exception as exc:  # noqa: BLE001 -- an unaudited denial still fails closed
            raise MemoryRetrievalError(
                "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE", "retrieval audit failed closed"
            ) from exc


__all__ = [
    "DEFAULT_QUERY_CONTRACTS",
    "MemoryHit",
    "MemoryQueryContract",
    "MemoryRetrievalError",
    "MemoryRetrievalPolicy",
    "MemorySearchResponse",
    "MemorySearchService",
    "RankingProfile",
    "RetrievalAuditSink",
    "RetrievalAuthorization",
    "RetrievalLimits",
    "RetrievalMode",
    "SearchFilters",
    "SearchQuery",
    "StopEpochPort",
]
