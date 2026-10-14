"""C8 governed memory -- consolidation, reflection, dissent and correction.

Implements the ``MemoryConsolidationPort`` / ``MemoryConsolidationWorker`` slice
of the ``GovernedMemoryService`` (ADD v1.3 Part II §§2.4, 2.5, 2.9, 2.12; LLD
v1.1 §§2.8.1, 2.8.2, 2.8.5; ``FGM-03``, ``FGM-09``, ``FGM-13`` oracles):

* ``MemoryConsolidationService.consolidate`` runs one explicit
  ``MemoryConsolidationJob`` from the closed OpenAPI
  ``MemoryConsolidationRequest``: input query digest, exact input version refs,
  algorithm pin, target kind/scope, reviewer policy, purpose and the budget of
  an approved ``ConsolidationProfile``.  Only approved profiles run; an
  automatic (``ACTIVE``) outcome needs a profile approved for automatic
  consolidation, otherwise the output stays ``PROPOSED`` for review.
* Inputs are cited, never changed: every input must be the current ``ACTIVE``
  head of an item visible to the caller (same tenant, organization, domain and
  purpose, compartments and marking dominated by the context).  Unknown and
  unauthorized inputs are refused with the same problem, before any content is
  read.  Content is read through the store coordinator (committed, projections
  bound, decrypted, digest checked).
* The pinned ``claim-merge`` algorithm groups the assertions of the inputs by
  ``(subject, attribute)``.  Agreement becomes a statement citing every
  supporting version; any disagreement becomes an ``UNRESOLVED`` conflict that
  keeps every alternative with its own supporting versions, ordered by value
  and never by support, plus one separate ``DISSENT`` item per conflict.
  Frequency and majority never select a winner (no silent majority merge).
* The derived item is a new item (``source_kind = MEMORY_CONSOLIDATION``) with
  complete lineage (``consolidates_refs`` = inputs, ``derived_from_refs`` =
  inputs and dissent items), an uncertainty record, a confidence bounded by the
  weakest input and reduced by every conflict, the conservative marking join
  and the union of the input taint.  ``REFLECTION`` output additionally carries
  ``MODEL_GENERATED``.  No output is ever instruction-eligible, procedural or
  canonical: the module has no canonical, approval or capability port at all.
* ``MemoryConsolidationService.correct`` corrects agreed statements of a
  consolidated item by a new immutable version (``supersedes_ref`` and
  ``correction_of_ref``).  A correction cannot rewrite or add sources, cannot
  touch a conflict or a ``DISSENT`` item and cannot raise eligibility: the
  conflicts, the dissent refs and the cited sources are carried unchanged.
* ``ConsolidationGuardPolicy`` wraps the admission policy so that a
  consolidation-derived item, a new version of one, or a content rewrite of a
  ``DISSENT`` item can only enter through this service (no provenance
  laundering, no correction that bypasses the dissent rules).
* Jobs are idempotent per ``(tenant, operation_id)``: a replay returns the
  recorded outcome, another job under the same operation fails with
  ``MEMORY_IDEMPOTENCY_CONFLICT``.  Derived item ids are bound to the job
  digest, so a job interrupted after a partial write is completed by its retry
  without duplicates; the job record is written last, after the audit event.

The module is backend-free (``OCOR_LANGUAGE_POLICY.md`` row 8): admission,
stores, policy, audit and the job ledger are ports.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import math
import os
import threading
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO, Protocol

from ..errors import CanonicalizationError
from ..kernel.canonical import (
    TimestampError,
    canonical_bytes,
    canonical_digest,
    format_utc_timestamp,
    parse_i_json,
    parse_utc_timestamp,
)
from ..kernel.governance import EvidenceRecord, ProvenanceRecord, TrustedClock
from ..kernel.governed_context import (
    GovernedContext,
    GovernedContextCodec,
    GovernedContextError,
    VerifiedGovernedContextBinding,
)
from .model import (
    DIGEST,
    SCOPE_BINDINGS,
    AdmittedMemoryVersion,
    FederationPolicy,
    GovernedMemoryItem,
    InstructionApproval,
    LifecycleStatus,
    MarkingDominance,
    MemoryAdmissionError,
    MemoryAdmissionPolicy,
    MemoryAdmissionService,
    MemoryKind,
    MemoryPolicyDecision,
    MemoryReferenceResolver,
    MemoryScope,
    MemoryVersionLedger,
    SourceKind,
    parse_memory_version_ref,
)
from .stores import MemoryPartition, MemoryStoreCoordinator

CONSOLIDATION_REQUEST_FIELDS = frozenset(
    {
        "operation_id",
        "governed_context",
        "governed_context_digest",
        "deadline",
        "input_query_digest",
        "input_item_refs",
        "algorithm_ref",
        "algorithm_digest",
        "target_memory_kind",
        "target_memory_scope",
        "reviewer_policy_ref",
    }
)
CORRECTION_REQUEST_FIELDS = frozenset(
    {
        "operation_id",
        "governed_context",
        "governed_context_digest",
        "deadline",
        "target_version_ref",
        "corrected_statements",
        "correction_reason_ref",
    }
)
STATEMENT_FIELDS = frozenset({"subject", "attribute", "value", "support_refs"})
ASSERTION_FIELDS = frozenset({"subject", "attribute", "value"})

# Kinds a consolidation job may target (ADD v1.3 Part II §2.9, FGM-03).
# WORKING is never a derived target, PROCEDURAL would activate procedures,
# PREFERENCE is human-supplied, DISSENT is produced only as a conflict
# artifact and TEAM_SHARED needs a team boundary the job does not carry.
CONSOLIDATION_TARGET_KINDS = frozenset(
    {MemoryKind.EPISODIC, MemoryKind.SEMANTIC, MemoryKind.REFLECTION}
)
OUTPUT_STATUSES = frozenset({LifecycleStatus.ACTIVE, LifecycleStatus.PROPOSED})
CORRECTABLE_STATUSES = frozenset({LifecycleStatus.ACTIVE, LifecycleStatus.PROPOSED})

SUMMARY_SCHEMA = "urn:ocor:memory-content:summary:1.0"
REFLECTION_SCHEMA = "urn:ocor:memory-content:reflection:1.0"
DISSENT_SCHEMA = "urn:ocor:memory-content:dissent:1.0"
DERIVED_REPRESENTATIONS = ("FULL_TEXT", "STRUCTURED")
DERIVED_TAINT = "DERIVED"
MODEL_TAINT = "MODEL_GENERATED"
UNRESOLVED = "UNRESOLVED"
CAUSATION_NAMESPACE = uuid.UUID("5d0b2a8e-4c1f-4f2e-9a7d-0c54a1e3b9f2")

OPERATION_CONSOLIDATE = "consolidateMemory"
OPERATION_CORRECT = "correctConsolidatedMemory"
# Bounded metric label set: operation kind x outcome x closed reason code.
METRIC_OUTCOMES = frozenset({"COMPLETED", "REPLAYED", "DENIED"})


class MemoryConsolidationError(MemoryAdmissionError):
    """Fail-closed consolidation refusal carrying the closed memory Problem vocabulary."""


def _schema_error(detail: str, message: str) -> MemoryConsolidationError:
    return MemoryConsolidationError("MEMORY_SCHEMA_INVALID", detail, message)


def _hex(digest: str) -> str:
    return digest.removeprefix("urn:sha256:")


def _sha256(data: bytes) -> str:
    return "urn:sha256:" + hashlib.sha256(data).hexdigest()


def _string(name: str, value: object, detail: str = "ENVELOPE_INVALID") -> str:
    if not isinstance(value, str) or not value:
        raise _schema_error(detail, f"{name} must be a non-empty string")
    return value


def _digest_field(name: str, value: object) -> str:
    result = _string(name, value)
    if DIGEST.fullmatch(result) is None:
        raise _schema_error("ENVELOPE_INVALID", f"{name} must be a canonical SHA-256 URN")
    return result


def _ref_list(name: str, value: object, detail: str = "ENVELOPE_INVALID") -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise _schema_error(detail, f"{name} must be a non-empty array")
    refs = tuple(_string(name, item, detail) for item in value)
    if len(set(refs)) != len(refs):
        raise _schema_error(detail, f"{name} must not contain duplicates")
    return tuple(sorted(refs))


# --------------------------------------------------------------------------
# Algorithm and approved profiles
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConsolidationAlgorithm:
    """A pinned, deterministic consolidation algorithm implemented by this module."""

    algorithm_ref: str
    specification: Mapping[str, object]
    model_ref: str | None = None
    model_digest: str | None = None

    @property
    def algorithm_digest(self) -> str:
        return canonical_digest(dict(self.specification))

    def pins(self) -> dict[str, object]:
        return {
            "algorithm_ref": self.algorithm_ref,
            "algorithm_digest": self.algorithm_digest,
            "model_ref": self.model_ref,
            "model_digest": self.model_digest,
        }


CLAIM_MERGE = ConsolidationAlgorithm(
    algorithm_ref="urn:ocor:memory-consolidation-algorithm:claim-merge:1.0",
    specification=MappingProxyType(
        {
            "name": "claim-merge",
            "version": "1.0",
            "input": "I-JSON object {assertions: [{subject, attribute, value}]}",
            "grouping": "(subject, attribute)",
            "agreement": "one canonical value across every supporting version -> statement",
            "disagreement": "two or more canonical values -> UNRESOLVED conflict and DISSENT item",
            "alternative_order": "canonical value bytes, never support count",
            "confidence": "floor6(min input confidence * statements / (statements + conflicts))",
            "deterministic": True,
        }
    ),
)
IMPLEMENTED_ALGORITHMS: Mapping[str, ConsolidationAlgorithm] = MappingProxyType(
    {CLAIM_MERGE.algorithm_ref: CLAIM_MERGE}
)


@dataclass(frozen=True, slots=True)
class ConsolidationProfile:
    """An approved consolidation profile: algorithm pin, targets, reviewer and budget."""

    profile_ref: str
    algorithm: ConsolidationAlgorithm
    target_kinds: frozenset[MemoryKind]
    reviewer_policies: Mapping[str, LifecycleStatus]
    retention_policy_ref: str
    automatic: bool = False
    max_inputs: int = 32
    max_input_bytes: int = 262_144

    def __post_init__(self) -> None:
        if not self.profile_ref or not self.retention_policy_ref:
            raise ValueError("profile_ref and retention_policy_ref are required")
        implemented = IMPLEMENTED_ALGORITHMS.get(self.algorithm.algorithm_ref)
        if implemented is None or implemented.algorithm_digest != self.algorithm.algorithm_digest:
            raise ValueError("a consolidation profile must pin an implemented algorithm")
        if not self.target_kinds or not self.target_kinds <= CONSOLIDATION_TARGET_KINDS:
            raise ValueError("consolidation targets are limited to EPISODIC, SEMANTIC, REFLECTION")
        if not self.reviewer_policies:
            raise ValueError("a consolidation profile requires a reviewer policy")
        for reviewer, status in self.reviewer_policies.items():
            if not reviewer or status not in OUTPUT_STATUSES:
                raise ValueError("reviewer policies produce ACTIVE or PROPOSED outputs only")
            if status is LifecycleStatus.ACTIVE and not self.automatic:
                raise ValueError("an ACTIVE outcome requires a profile approved as automatic")
        if self.max_inputs < 1 or self.max_input_bytes < 1:
            raise ValueError("consolidation budgets must be positive")
        object.__setattr__(self, "reviewer_policies", MappingProxyType(dict(self.reviewer_policies)))

    def budget(self) -> dict[str, object]:
        return {"max_inputs": self.max_inputs, "max_input_bytes": self.max_input_bytes}


class ConsolidationProfileRegistry:
    """The approved profiles; one reviewer policy belongs to one profile per algorithm."""

    def __init__(self, profiles: Iterable[ConsolidationProfile]) -> None:
        self._profiles = tuple(profiles)
        seen: set[tuple[str, str]] = set()
        for profile in self._profiles:
            for reviewer in profile.reviewer_policies:
                key = (profile.algorithm.algorithm_ref, reviewer)
                if key in seen:
                    raise ValueError("a reviewer policy is ambiguous across profiles")
                seen.add(key)

    def resolve(
        self,
        algorithm_ref: str,
        algorithm_digest: str,
        reviewer_policy_ref: str,
        target_kind: MemoryKind,
    ) -> ConsolidationProfile:
        candidates = [p for p in self._profiles if p.algorithm.algorithm_ref == algorithm_ref]
        if not candidates:
            raise MemoryConsolidationError(
                "UNSUPPORTED_CAPABILITY",
                "ALGORITHM_NOT_APPROVED",
                "the consolidation algorithm is not in an approved profile",
            )
        if any(
            not hmac.compare_digest(p.algorithm.algorithm_digest, algorithm_digest)
            for p in candidates
        ):
            raise MemoryConsolidationError(
                "POLICY_DENIED",
                "ALGORITHM_DIGEST_MISMATCH",
                "algorithm_digest does not match the approved algorithm pin",
            )
        matching = [p for p in candidates if reviewer_policy_ref in p.reviewer_policies]
        if not matching:
            raise MemoryConsolidationError(
                "POLICY_DENIED",
                "REVIEWER_POLICY_NOT_APPROVED",
                "the reviewer policy is not approved for this algorithm",
            )
        profile = matching[0]
        if target_kind not in profile.target_kinds:
            raise MemoryConsolidationError(
                "UNSUPPORTED_CAPABILITY",
                "TARGET_KIND_NOT_APPROVED",
                f"{target_kind.value} is not an approved target of the profile",
            )
        return profile


# --------------------------------------------------------------------------
# Pure claim-merge
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClaimSource:
    """One cited input version and its parsed assertions."""

    version_ref: str
    item_digest: str
    content_digest: str
    confidence: float
    assertions: tuple[tuple[str, str, object], ...]

    def citation(self) -> dict[str, object]:
        return {
            "memory_version_ref": self.version_ref,
            "item_digest": self.item_digest,
            "content_digest": self.content_digest,
        }


@dataclass(frozen=True, slots=True)
class MergeResult:
    statements: tuple[Mapping[str, object], ...]
    conflicts: tuple[Mapping[str, object], ...]


def parse_assertions(payload: bytes) -> tuple[tuple[str, str, object], ...]:
    """Parse a claim-merge input payload (strict I-JSON, closed members)."""

    try:
        document = parse_i_json(bytes(payload))
    except (CanonicalizationError, ValueError, UnicodeDecodeError) as exc:
        raise _schema_error("CONSOLIDATION_INPUT_UNPARSEABLE", "input is not I-JSON") from exc
    if not isinstance(document, dict) or set(document) != {"assertions"}:
        raise _schema_error(
            "CONSOLIDATION_INPUT_UNPARSEABLE", "input must be a closed {assertions} object"
        )
    raw = document["assertions"]
    if not isinstance(raw, list) or not raw:
        raise _schema_error("CONSOLIDATION_INPUT_UNPARSEABLE", "assertions must be non-empty")
    parsed: list[tuple[str, str, object]] = []
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != ASSERTION_FIELDS:
            raise _schema_error(
                "CONSOLIDATION_INPUT_UNPARSEABLE", "assertion must be {subject, attribute, value}"
            )
        subject, attribute, value = entry["subject"], entry["attribute"], entry["value"]
        if not isinstance(subject, str) or not subject or not isinstance(attribute, str) or not attribute:
            raise _schema_error(
                "CONSOLIDATION_INPUT_UNPARSEABLE", "subject and attribute must be strings"
            )
        if isinstance(value, (dict, list)):
            raise _schema_error("CONSOLIDATION_INPUT_UNPARSEABLE", "value must be a scalar")
        parsed.append((subject, attribute, value))
    return tuple(parsed)


def _key_id(subject: str, attribute: str) -> str:
    return canonical_digest({"subject": subject, "attribute": attribute})


def merge_claims(sources: Sequence[ClaimSource]) -> MergeResult:
    """Group assertions by (subject, attribute); disagreement is preserved, never voted."""

    groups: dict[tuple[str, str], dict[bytes, tuple[object, set[str]]]] = {}
    for source in sources:
        for subject, attribute, value in source.assertions:
            values = groups.setdefault((subject, attribute), {})
            canonical = canonical_bytes(value)
            values.setdefault(canonical, (value, set()))[1].add(source.version_ref)
    statements: list[Mapping[str, object]] = []
    conflicts: list[Mapping[str, object]] = []
    for subject, attribute in sorted(groups):
        values = groups[(subject, attribute)]
        if len(values) == 1:
            ((value, support),) = values.values()
            statements.append(
                {
                    "subject": subject,
                    "attribute": attribute,
                    "value": value,
                    "support_refs": sorted(support),
                }
            )
            continue
        alternatives = [
            {"value": value, "support_refs": sorted(support), "support_count": len(support)}
            for _, (value, support) in sorted(values.items())
        ]
        conflicts.append(
            {
                "conflict_id": _key_id(subject, attribute),
                "subject": subject,
                "attribute": attribute,
                "alternatives": alternatives,
                "resolution": UNRESOLVED,
            }
        )
    return MergeResult(statements=tuple(statements), conflicts=tuple(conflicts))


def bounded_confidence(minimum: float, statements: int, conflicts: int) -> float:
    """Never above the weakest input; every unresolved conflict lowers it."""

    total = statements + conflicts
    ratio = statements / total if total else 0.0
    return math.floor(minimum * ratio * 1_000_000) / 1_000_000


def uncertainty_record(
    sources: Sequence[ClaimSource], statements: int, conflicts: int
) -> dict[str, object]:
    return {
        "method": "claim-merge-agreement:1.0",
        "source_count": len(sources),
        "statement_count": statements,
        "conflict_count": conflicts,
        "weakest_source_ref": min(sources, key=lambda s: (s.confidence, s.version_ref)).version_ref,
    }


# --------------------------------------------------------------------------
# Ports
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MemoryConsolidationJob:
    """LLD v1.1 §2.8.5 ``MemoryConsolidationJob``: everything the outcome depends on."""

    operation_id: str
    tenant_id: str
    isolation: Mapping[str, object]
    input_query_digest: str
    input_refs: tuple[str, ...]
    input_item_digests: tuple[str, ...]
    algorithm: Mapping[str, object]
    profile_ref: str
    target_kind: MemoryKind
    target_scope: MemoryScope
    reviewer_policy_ref: str
    budget: Mapping[str, object]

    def to_mapping(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "tenant_id": self.tenant_id,
            "isolation": dict(self.isolation),
            "input_query_digest": self.input_query_digest,
            "input_refs": list(self.input_refs),
            "input_item_digests": list(self.input_item_digests),
            "input_selection_digest": canonical_digest(
                [list(pair) for pair in zip(self.input_refs, self.input_item_digests, strict=True)]
            ),
            "algorithm": dict(self.algorithm),
            "profile_ref": self.profile_ref,
            "target_memory_kind": self.target_kind.value,
            "target_memory_scope": self.target_scope.value,
            "reviewer_policy_ref": self.reviewer_policy_ref,
            "budget": dict(self.budget),
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_mapping())

    @property
    def job_ref(self) -> str:
        return f"urn:ocor:memory-consolidation-job:{_hex(self.digest)}"


class ConsolidationPolicy(Protocol):
    """Live policy/Authority port for consolidation and correction jobs."""

    def authorize_consolidation(
        self, job: MemoryConsolidationJob, context: GovernedContext
    ) -> MemoryPolicyDecision:
        """Return the live decision for this job (evaluated before any content read)."""

    def authorize_correction(
        self, target: GovernedMemoryItem, context: GovernedContext
    ) -> MemoryPolicyDecision:
        """Return the live decision for correcting this consolidated version."""


class ConsolidationAuditSink(Protocol):
    """Protected audit authority for consolidation, correction and denial evidence."""

    def record(self, event: Mapping[str, object]) -> None:
        """Durably record one audit event or raise."""


class ConsolidationReferenceResolver:
    """Admission resolver that also resolves the job and correction sources it registers.

    The derived item cites its job (``source_ref``) and a provenance record that
    covers the job and every evidence ref of the inputs; everything else is
    resolved by the wrapped resolver under the same GCS.
    """

    def __init__(self, base: MemoryReferenceResolver) -> None:
        self._base = base
        self._lock = threading.RLock()
        self._sources: dict[str, str] = {}
        self._provenance: dict[str, ProvenanceRecord] = {}

    def register(self, source_ref: str, source_digest: str, provenance: ProvenanceRecord) -> None:
        with self._lock:
            self._sources[source_ref] = source_digest
            self._provenance[provenance.provenance_id] = provenance

    def source_digest(self, source_ref: str, context: GovernedContext) -> str | None:
        with self._lock:
            registered = self._sources.get(source_ref)
        return registered if registered is not None else self._base.source_digest(source_ref, context)

    def evidence(self, evidence_ref: str, context: GovernedContext) -> EvidenceRecord | None:
        return self._base.evidence(evidence_ref, context)

    def provenance(self, provenance_ref: str, context: GovernedContext) -> ProvenanceRecord | None:
        with self._lock:
            registered = self._provenance.get(provenance_ref)
        if registered is not None:
            return registered if registered.governed_context_digest == context.digest() else None
        return self._base.provenance(provenance_ref, context)

    def instruction_approval(
        self, approval_ref: str, context: GovernedContext
    ) -> InstructionApproval | None:
        return self._base.instruction_approval(approval_ref, context)

    def federation_policy(self, policy_ref: str, context: GovernedContext) -> FederationPolicy | None:
        return self._base.federation_policy(policy_ref, context)


class ConsolidationGuardPolicy:
    """Admission policy wrapper: derived memory enters only through this service.

    Guarded admissions are a ``MEMORY_CONSOLIDATION`` item, any new version of
    a consolidation-derived item and any new version of a ``DISSENT`` item that
    changes its content.  They are permitted only for the exact item digest the
    service registered for the admission in progress; everything else is
    decided by the wrapped policy.
    """

    def __init__(self, inner: MemoryAdmissionPolicy, *, ledger: MemoryVersionLedger) -> None:
        self._inner = inner
        self._ledger = ledger
        self._lock = threading.RLock()
        self._expected: Counter[str] = Counter()

    def expect(self, item_digest: str) -> None:
        with self._lock:
            self._expected[item_digest] += 1

    def release(self, item_digest: str) -> None:
        with self._lock:
            self._expected[item_digest] -= 1
            if self._expected[item_digest] <= 0:
                del self._expected[item_digest]

    def _guarded(self, item: GovernedMemoryItem) -> str | None:
        if item.source_kind is SourceKind.MEMORY_CONSOLIDATION:
            return "CONSOLIDATION_PROVENANCE_UNREGISTERED"
        if item.memory_version > 1:
            predecessor = self._ledger.get(item.memory_item_id, item.memory_version - 1)
            if predecessor is None:
                return None
            if predecessor.item.source_kind is SourceKind.MEMORY_CONSOLIDATION:
                return "CONSOLIDATED_VERSION_UNGUARDED"
            if (
                predecessor.item.memory_kind is MemoryKind.DISSENT
                and predecessor.item.content_digest != item.content_digest
            ):
                return "DISSENT_REWRITE"
        return None

    def authorize_admission(
        self, item: GovernedMemoryItem, context: GovernedContext
    ) -> MemoryPolicyDecision:
        reason = self._guarded(item)
        if reason is not None:
            with self._lock:
                registered = self._expected.get(item.digest(), 0) > 0
            if not registered:
                return MemoryPolicyDecision(
                    permitted=False,
                    decision_ref=f"decision:consolidation-guard:{reason.lower()}",
                    policy_bundle_digest=context.policy_bundle_digest,
                    reason=reason,
                )
        return self._inner.authorize_admission(item, context)


# --------------------------------------------------------------------------
# Job ledger (idempotency and completion marker)
# --------------------------------------------------------------------------


class ConsolidationLedgerCorrupted(MemoryConsolidationError):
    def __init__(self, message: str) -> None:
        super().__init__("INTERNAL_ERROR", "CONSOLIDATION_LEDGER_CORRUPTED", message)


@dataclass(frozen=True, slots=True)
class ConsolidationOutcome:
    """The result of one completed consolidation or correction operation."""

    receipt: Mapping[str, object]
    operation_kind: str
    job_ref: str
    job_digest: str
    derived_ref: str
    dissent_refs: tuple[str, ...]
    lifecycle_status: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "receipt": dict(self.receipt),
            "operation_kind": self.operation_kind,
            "job_ref": self.job_ref,
            "job_digest": self.job_digest,
            "derived_ref": self.derived_ref,
            "dissent_refs": list(self.dissent_refs),
            "lifecycle_status": self.lifecycle_status,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ConsolidationOutcome:
        expected = {
            "receipt",
            "operation_kind",
            "job_ref",
            "job_digest",
            "derived_ref",
            "dissent_refs",
            "lifecycle_status",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ConsolidationLedgerCorrupted("outcome is not a closed outcome record")
        receipt, dissent = value["receipt"], value["dissent_refs"]
        if not isinstance(receipt, Mapping) or not isinstance(dissent, list):
            raise ConsolidationLedgerCorrupted("outcome members have invalid types")
        return cls(
            receipt=MappingProxyType(dict(receipt)),
            operation_kind=str(value["operation_kind"]),
            job_ref=str(value["job_ref"]),
            job_digest=str(value["job_digest"]),
            derived_ref=str(value["derived_ref"]),
            dissent_refs=tuple(str(ref) for ref in dissent),
            lifecycle_status=str(value["lifecycle_status"]),
        )


@dataclass(frozen=True, slots=True)
class ConsolidationJobRecord:
    tenant_id: str
    operation_id: str
    outcome: ConsolidationOutcome
    audit_event: Mapping[str, object]

    def verify(self) -> None:
        if not hmac.compare_digest(
            canonical_digest(dict(self.audit_event)), str(self.outcome.receipt.get("audit_ref"))
        ):
            raise ConsolidationLedgerCorrupted("audit_ref does not bind the audit event")
        if (
            self.audit_event.get("job_digest") != self.outcome.job_digest
            or self.audit_event.get("operation_id") != self.operation_id
            or self.outcome.receipt.get("operation_id") != self.operation_id
        ):
            raise ConsolidationLedgerCorrupted("record does not bind its job and operation")

    def to_mapping(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "operation_id": self.operation_id,
            "outcome": self.outcome.to_mapping(),
            "audit_event": dict(self.audit_event),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ConsolidationJobRecord:
        if not isinstance(value, Mapping) or set(value) != {
            "tenant_id",
            "operation_id",
            "outcome",
            "audit_event",
        }:
            raise ConsolidationLedgerCorrupted("record is not a closed job record")
        outcome, audit_event = value["outcome"], value["audit_event"]
        if not isinstance(outcome, Mapping) or not isinstance(audit_event, Mapping):
            raise ConsolidationLedgerCorrupted("record members have invalid types")
        record = cls(
            tenant_id=str(value["tenant_id"]),
            operation_id=str(value["operation_id"]),
            outcome=ConsolidationOutcome.from_mapping(outcome),
            audit_event=MappingProxyType(dict(audit_event)),
        )
        record.verify()
        return record


class ConsolidationJobLedger(Protocol):
    def get(self, tenant_id: str, operation_id: str) -> ConsolidationJobRecord | None:
        """Return the completed job recorded under ``(tenant_id, operation_id)``."""

    def append(self, record: ConsolidationJobRecord) -> None:
        """Atomically append, refusing an occupied operation slot."""


def _operation_reused() -> MemoryConsolidationError:
    return MemoryConsolidationError(
        "MEMORY_IDEMPOTENCY_CONFLICT",
        "CONSOLIDATION_OPERATION_REUSED",
        "operation_id is already bound to another consolidation outcome",
    )


class InMemoryConsolidationJobLedger:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], ConsolidationJobRecord] = {}

    def get(self, tenant_id: str, operation_id: str) -> ConsolidationJobRecord | None:
        with self._lock:
            return self._records.get((tenant_id, operation_id))

    def append(self, record: ConsolidationJobRecord) -> None:
        record.verify()
        with self._lock:
            key = (record.tenant_id, record.operation_id)
            if key in self._records:
                raise _operation_reused()
            self._records[key] = record

    def records(self) -> tuple[ConsolidationJobRecord, ...]:
        with self._lock:
            return tuple(self._records.values())


GENESIS = "urn:sha256:" + "0" * 64


class JournalConsolidationJobLedger:
    """Durable, hash-chained, append-only JSON-lines job journal (cross-run)."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], ConsolidationJobRecord] = {}
        self._head = GENESIS
        self._offset = 0
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)
        with self._path.open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            try:
                self._catch_up(handle)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @property
    def head(self) -> str:
        with self._lock:
            return self._head

    def _catch_up(self, handle: BinaryIO) -> None:
        handle.seek(self._offset)
        for line in handle:
            if not line.endswith(b"\n"):
                raise ConsolidationLedgerCorrupted("torn journal line")
            self._apply(line)
            self._offset += len(line)

    def _apply(self, line: bytes) -> None:
        try:
            entry = parse_i_json(line.rstrip(b"\n"))
        except (CanonicalizationError, ValueError) as exc:
            raise ConsolidationLedgerCorrupted("journal line is not I-JSON") from exc
        if not isinstance(entry, dict) or set(entry) != {"prev", "record", "digest"}:
            raise ConsolidationLedgerCorrupted("journal line is not a chained entry")
        if entry["prev"] != self._head:
            raise ConsolidationLedgerCorrupted("journal hash chain is broken")
        body = {"prev": entry["prev"], "record": entry["record"]}
        if not hmac.compare_digest(canonical_digest(body), str(entry["digest"])):
            raise ConsolidationLedgerCorrupted("journal entry digest mismatch")
        record_value = entry["record"]
        if not isinstance(record_value, dict):
            raise ConsolidationLedgerCorrupted("journal record is not an object")
        record = ConsolidationJobRecord.from_mapping(record_value)
        key = (record.tenant_id, record.operation_id)
        if key in self._records:
            raise ConsolidationLedgerCorrupted("journal reuses an operation slot")
        self._records[key] = record
        self._head = str(entry["digest"])

    def get(self, tenant_id: str, operation_id: str) -> ConsolidationJobRecord | None:
        with self._lock, self._path.open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            try:
                self._catch_up(handle)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
            return self._records.get((tenant_id, operation_id))

    def append(self, record: ConsolidationJobRecord) -> None:
        record.verify()
        with self._lock, self._path.open("r+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                self._catch_up(handle)
                if (record.tenant_id, record.operation_id) in self._records:
                    raise _operation_reused()
                body = {"prev": self._head, "record": record.to_mapping()}
                line = canonical_bytes({**body, "digest": canonical_digest(body)}) + b"\n"
                handle.seek(0, os.SEEK_END)
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
                handle.seek(self._offset)
                self._catch_up(handle)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Request:
    operation_id: str
    context: GovernedContext
    gcs_digest: str
    deadline: datetime
    body: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _Input:
    record: AdmittedMemoryVersion
    payload: bytes


@dataclass(frozen=True, slots=True)
class _Derived:
    item: GovernedMemoryItem
    payload: bytes
    operation_suffix: str


@dataclass(frozen=True, slots=True)
class _Plan:
    job: MemoryConsolidationJob
    context: GovernedContext
    bindings: Mapping[str, str]
    status: LifecycleStatus
    provenance_id: str
    profile: ConsolidationProfile


@dataclass
class _Failure:
    operation_id: str | None = None
    gcs_digest: str | None = None
    correlation_id: str | None = None
    binding_ref: str | None = None


class MemoryConsolidationService:
    """``MemoryConsolidationPort``: explicit, pinned, lineage-preserving consolidation."""

    def __init__(
        self,
        *,
        admission: MemoryAdmissionService,
        ledger: MemoryVersionLedger,
        coordinator: MemoryStoreCoordinator,
        references: ConsolidationReferenceResolver,
        guard: ConsolidationGuardPolicy,
        policy: ConsolidationPolicy,
        markings: MarkingDominance,
        profiles: ConsolidationProfileRegistry,
        jobs: ConsolidationJobLedger,
        audit: ConsolidationAuditSink,
        clock: TrustedClock,
    ) -> None:
        self._admission = admission
        self._ledger = ledger
        self._coordinator = coordinator
        self._references = references
        self._guard = guard
        self._policy = policy
        self._markings = markings
        self._profiles = profiles
        self._jobs = jobs
        self._audit = audit
        self._clock = clock
        self._lock = threading.RLock()
        self.metrics: Counter[tuple[str, str, str]] = Counter()

    # -- public operations -------------------------------------------------

    def consolidate(
        self, request: Mapping[str, object], *, binding: VerifiedGovernedContextBinding | None
    ) -> ConsolidationOutcome:
        """Run one consolidation job, or raise an audited, fail-closed refusal."""

        return self._guarded_run(OPERATION_CONSOLIDATE, request, binding)

    def correct(
        self, request: Mapping[str, object], *, binding: VerifiedGovernedContextBinding | None
    ) -> ConsolidationOutcome:
        """Correct agreed statements of a consolidated item by a new immutable version."""

        return self._guarded_run(OPERATION_CORRECT, request, binding)

    # -- envelope, audit and idempotency ------------------------------------

    def _guarded_run(
        self,
        kind: str,
        request: Mapping[str, object],
        binding: VerifiedGovernedContextBinding | None,
    ) -> ConsolidationOutcome:
        failure = _Failure()
        try:
            if not isinstance(binding, VerifiedGovernedContextBinding):
                raise MemoryConsolidationError(
                    "AUTHENTICATION_REQUIRED",
                    "BINDING_MISSING",
                    "consolidation requires an authenticated governed-context binding",
                )
            failure.correlation_id = binding.expected.correlation_id
            failure.binding_ref = binding.binding_ref
            fields = (
                CONSOLIDATION_REQUEST_FIELDS
                if kind == OPERATION_CONSOLIDATE
                else CORRECTION_REQUEST_FIELDS
            )
            parsed = self._envelope(request, binding, fields, failure)
            with self._lock:
                if kind == OPERATION_CONSOLIDATE:
                    outcome, replayed = self._consolidate(parsed, binding)
                else:
                    outcome, replayed = self._correct(parsed, binding)
            self.metrics[(kind, "REPLAYED" if replayed else "COMPLETED", "NONE")] += 1
            return outcome
        except MemoryAdmissionError as exc:
            if exc.correlation_id is None:
                exc.correlation_id = failure.correlation_id
            self._record_denial(kind, exc, failure)
            raise

    def _envelope(
        self,
        request: Mapping[str, object],
        binding: VerifiedGovernedContextBinding,
        fields: frozenset[str],
        failure: _Failure,
    ) -> _Request:
        now = self._clock.now()
        if not isinstance(request, Mapping) or set(request) != fields:
            raise _schema_error("ENVELOPE_INVALID", "request is not the closed request envelope")
        operation_id = _string("operation_id", request["operation_id"])
        failure.operation_id = operation_id
        claimed = _string("governed_context_digest", request["governed_context_digest"])
        try:
            deadline = parse_utc_timestamp(_string("deadline", request["deadline"]))
        except TimestampError as exc:
            raise _schema_error("ENVELOPE_INVALID", "deadline must be a UTC timestamp") from exc
        if deadline <= now:
            raise MemoryConsolidationError(
                "POLICY_DENIED", "DEADLINE_EXCEEDED", "the request deadline has passed"
            )
        raw_context = request["governed_context"]
        if not isinstance(raw_context, Mapping):
            raise MemoryConsolidationError(
                "GOVERNED_CONTEXT_MISMATCH", "GCS_INVALID", "governed_context must be an object"
            )
        try:
            context = GovernedContextCodec.from_openapi(raw_context, binding, claimed)
        except GovernedContextError as exc:
            raise MemoryConsolidationError("GOVERNED_CONTEXT_MISMATCH", exc.code, str(exc)) from exc
        failure.gcs_digest = context.digest()
        return _Request(
            operation_id=operation_id,
            context=context,
            gcs_digest=failure.gcs_digest,
            deadline=deadline,
            body=request,
        )

    def _record_denial(self, kind: str, exc: MemoryAdmissionError, failure: _Failure) -> None:
        self.metrics[(kind, "DENIED", exc.reason_code)] += 1
        event = {
            "action": kind,
            "outcome": "DENIED",
            "reason_code": exc.reason_code,
            "detail_code": exc.detail_code,
            "operation_id": failure.operation_id,
            "governed_context_digest": failure.gcs_digest,
            "binding_ref": failure.binding_ref,
            "correlation_id": exc.correlation_id,
            "at": format_utc_timestamp(self._clock.now()),
        }
        try:
            self._audit.record(event)
        except Exception as audit_exc:  # noqa: BLE001 -- an unaudited denial fails closed
            raise MemoryConsolidationError(
                "CONTROL_PLANE_UNAVAILABLE",
                "AUDIT_UNAVAILABLE",
                "the denial could not be audited",
                correlation_id=exc.correlation_id,
            ) from audit_exc

    def _replay(self, request: _Request, job_digest: str) -> ConsolidationOutcome | None:
        previous = self._jobs.get(request.context.tenant_id, request.operation_id)
        if previous is None:
            return None
        # Job and correction digests cover different closed structures, so equal
        # digests also mean the same operation kind.
        if not hmac.compare_digest(previous.outcome.job_digest, job_digest):
            raise _operation_reused()
        return previous.outcome

    # -- consolidation -----------------------------------------------------

    def _consolidate(
        self, request: _Request, binding: VerifiedGovernedContextBinding
    ) -> tuple[ConsolidationOutcome, bool]:
        body = request.body
        context = request.context
        input_query_digest = _digest_field("input_query_digest", body["input_query_digest"])
        input_refs = _ref_list("input_item_refs", body["input_item_refs"])
        algorithm_ref = _string("algorithm_ref", body["algorithm_ref"])
        algorithm_digest = _digest_field("algorithm_digest", body["algorithm_digest"])
        reviewer = _string("reviewer_policy_ref", body["reviewer_policy_ref"])
        try:
            target_kind = MemoryKind(_string("target_memory_kind", body["target_memory_kind"]))
            target_scope = MemoryScope(_string("target_memory_scope", body["target_memory_scope"]))
        except ValueError as exc:
            raise _schema_error("ENVELOPE_INVALID", "target kind/scope is not declared") from exc
        if target_kind not in CONSOLIDATION_TARGET_KINDS:
            raise MemoryConsolidationError(
                "UNSUPPORTED_CAPABILITY",
                "CONSOLIDATION_TARGET_UNSUPPORTED",
                f"{target_kind.value} is never a consolidation target",
            )
        profile = self._profiles.resolve(algorithm_ref, algorithm_digest, reviewer, target_kind)
        if len(input_refs) > profile.max_inputs:
            raise MemoryConsolidationError(
                "POLICY_DENIED",
                "CONSOLIDATION_BUDGET_EXCEEDED",
                "the job exceeds the profile input budget",
            )
        records = [self._visible_input(ref, context) for ref in input_refs]
        bindings = self._target_bindings(target_scope, [r.item for r in records])
        job = MemoryConsolidationJob(
            operation_id=request.operation_id,
            tenant_id=context.tenant_id,
            isolation=_isolation(context),
            input_query_digest=input_query_digest,
            input_refs=input_refs,
            input_item_digests=tuple(r.item_digest for r in records),
            algorithm=profile.algorithm.pins(),
            profile_ref=profile.profile_ref,
            target_kind=target_kind,
            target_scope=target_scope,
            reviewer_policy_ref=reviewer,
            budget=profile.budget(),
        )
        # Replay first: a completed job keeps its outcome even after its inputs
        # were superseded (immutable versions, exact-version replay).
        replayed = self._replay(request, job.digest)
        if replayed is not None:
            return replayed, True
        for record in records:
            self._check_input_current(record)
        decision = self._decide(lambda: self._policy.authorize_consolidation(job, context), context)
        inputs = self._read_inputs(records, profile)
        sources = [
            ClaimSource(
                version_ref=entry.record.item.version_ref,
                item_digest=entry.record.item_digest,
                content_digest=entry.record.item.content_digest,
                confidence=float(entry.record.item.confidence),
                assertions=parse_assertions(entry.payload),
            )
            for entry in inputs
        ]
        merged = merge_claims(sources)
        status = profile.reviewer_policies[reviewer]
        provenance = self._register_job(job, request, [r.item for r in records])
        plan = _Plan(
            job=job,
            context=context,
            bindings=bindings,
            status=status,
            provenance_id=provenance.provenance_id,
            profile=profile,
        )
        by_ref = {source.version_ref: source for source in sources}
        items_by_ref = {r.item.version_ref: r.item for r in records}
        dissents = [
            self._dissent_item(conflict, by_ref, items_by_ref, plan) for conflict in merged.conflicts
        ]
        dissent_refs = tuple(d.item.version_ref for d in dissents)
        summary = self._summary_item(merged, sources, dissent_refs, [r.item for r in records], plan)
        stored = [self._admit_and_commit(d, request, binding) for d in [*dissents, summary]]
        audit_event = {
            "action": OPERATION_CONSOLIDATE,
            "outcome": "COMPLETED",
            "operation_id": request.operation_id,
            "job_ref": job.job_ref,
            "job_digest": job.digest,
            "input_refs": list(job.input_refs),
            "input_item_digests": list(job.input_item_digests),
            "algorithm": dict(job.algorithm),
            "profile_ref": profile.profile_ref,
            "reviewer_policy_ref": reviewer,
            "derived_ref": summary.item.version_ref,
            "dissent_refs": list(dissent_refs),
            "derived_item_digests": [record.item_digest for record in stored],
            "lifecycle_status": status.value,
            "policy_decision_ref": decision.decision_ref,
            "policy_bundle_digest": decision.policy_bundle_digest,
            "governed_context_digest": request.gcs_digest,
            "binding_ref": binding.binding_ref,
            "correlation_id": context.correlation_id,
            "at": format_utc_timestamp(self._clock.now()),
        }
        outcome = self._complete(
            request, OPERATION_CONSOLIDATE, job.job_ref, job.digest, summary.item, dissent_refs, audit_event
        )
        return outcome, False

    def _visible_input(self, ref: str, context: GovernedContext) -> AdmittedMemoryVersion:
        unavailable = MemoryConsolidationError(
            "MEMORY_VERSION_NOT_FOUND",
            "CONSOLIDATION_INPUT_UNAVAILABLE",
            "an input does not resolve to a version visible to the caller",
        )
        try:
            item_id, version = parse_memory_version_ref(ref)
        except MemoryAdmissionError as exc:
            raise unavailable from exc
        record = self._ledger.get(item_id, version)
        if record is None or not self._visible(record.item, context):
            raise unavailable
        return record

    def _check_input_current(self, record: AdmittedMemoryVersion) -> None:
        item = record.item
        if self._ledger.latest_version(item.memory_item_id) != item.memory_version:
            raise MemoryConsolidationError(
                "LIFECYCLE_TRANSITION_INVALID",
                "CONSOLIDATION_INPUT_NOT_CURRENT",
                "an input is not the current version of its item",
            )
        if item.lifecycle_status is LifecycleStatus.QUARANTINED:
            raise MemoryConsolidationError(
                "MEMORY_TAINTED",
                "CONSOLIDATION_INPUT_QUARANTINED",
                "a quarantined version cannot be consolidated",
            )
        if item.lifecycle_status is not LifecycleStatus.ACTIVE:
            raise MemoryConsolidationError(
                "LIFECYCLE_TRANSITION_INVALID",
                "CONSOLIDATION_INPUT_NOT_ACTIVE",
                "only ACTIVE versions are consolidated",
            )
        now = self._clock.now()
        if (
            item.valid_from > now
            or (item.valid_until is not None and item.valid_until <= now)
            or (item.expires_at is not None and item.expires_at <= now)
        ):
            raise MemoryConsolidationError(
                "POLICY_DENIED",
                "CONSOLIDATION_INPUT_EXPIRED",
                "an input is outside its validity or retention window",
            )

    def _visible(self, item: GovernedMemoryItem, context: GovernedContext) -> bool:
        try:
            dominated = self._markings.dominates(
                context.classification_marking_ref, item.classification_marking_ref
            )
        except MemoryAdmissionError:
            return False
        return (
            item.tenant_id == context.tenant_id
            and item.organization_id == context.organization_id
            and item.domain_id == context.domain_id
            and item.purpose == context.purpose
            and set(item.compartments) <= set(context.compartments)
            and dominated
        )

    @staticmethod
    def _target_bindings(
        scope: MemoryScope, items: Sequence[GovernedMemoryItem]
    ) -> dict[str, str]:
        bindings: dict[str, str] = {}
        for name in SCOPE_BINDINGS[scope]:
            values = {getattr(item, name) for item in items}
            if len(values) != 1 or None in values:
                raise _schema_error(
                    "TARGET_SCOPE_BINDING_UNRESOLVED",
                    f"{scope.value} target requires one shared {name} across the inputs",
                )
            (value,) = values
            bindings[name] = str(value)
        return bindings

    def _decide(
        self, evaluate: Callable[[], MemoryPolicyDecision], context: GovernedContext
    ) -> MemoryPolicyDecision:
        try:
            decision = evaluate()
        except MemoryAdmissionError:
            raise
        except Exception as exc:  # noqa: BLE001 -- every policy outage fails closed
            raise MemoryConsolidationError(
                "CONTROL_PLANE_UNAVAILABLE", "POLICY_UNAVAILABLE", "policy evaluation failed closed"
            ) from exc
        if not isinstance(decision, MemoryPolicyDecision):
            raise MemoryConsolidationError(
                "CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID", "no policy decision"
            )
        if decision.policy_bundle_digest != context.policy_bundle_digest:
            raise MemoryConsolidationError(
                "STALE_POLICY",
                "POLICY_BUNDLE_MISMATCH",
                "policy decision was not evaluated against the context bundle",
            )
        if not decision.permitted:
            raise MemoryConsolidationError(
                "POLICY_DENIED", "CONSOLIDATION_DENIED", "policy denied the consolidation"
            )
        return decision

    def _read_inputs(
        self, records: Sequence[AdmittedMemoryVersion], profile: ConsolidationProfile
    ) -> list[_Input]:
        inputs: list[_Input] = []
        total = 0
        for record in records:
            item = record.item
            materialized = self._coordinator.read_version(
                MemoryPartition.for_item(item), item.memory_item_id, item.memory_version
            )
            if not hmac.compare_digest(
                materialized.item.digest(), record.item_digest
            ) or not hmac.compare_digest(_sha256(materialized.payload), item.content_digest):
                raise MemoryConsolidationError(
                    "INTERNAL_ERROR",
                    "CONSOLIDATION_INPUT_DRIFT",
                    "stored input does not bind the admitted version",
                )
            total += len(materialized.payload)
            if total > profile.max_input_bytes:
                raise MemoryConsolidationError(
                    "POLICY_DENIED",
                    "CONSOLIDATION_BUDGET_EXCEEDED",
                    "the job exceeds the profile input byte budget",
                )
            inputs.append(_Input(record=record, payload=materialized.payload))
        return inputs

    def _register_job(
        self, job: MemoryConsolidationJob, request: _Request, items: Sequence[GovernedMemoryItem]
    ) -> ProvenanceRecord:
        return self._register_source(
            source_ref=job.job_ref,
            source_digest=job.digest,
            kind="consolidation",
            activity_refs=(str(job.algorithm["algorithm_ref"]), job.profile_ref),
            request=request,
            items=items,
        )

    def _register_source(
        self,
        *,
        source_ref: str,
        source_digest: str,
        kind: str,
        activity_refs: tuple[str, ...],
        request: _Request,
        items: Sequence[GovernedMemoryItem],
    ) -> ProvenanceRecord:
        context = request.context
        provenance = ProvenanceRecord(
            provenance_id=f"urn:ocor:memory-{kind}-provenance:{_hex(source_digest)}",
            evidence_refs=tuple(sorted({ref for item in items for ref in item.evidence_refs})),
            source_refs=(source_ref,),
            activity_refs=activity_refs,
            actor_refs=(context.effective_principal_id,),
            governed_context_digest=request.gcs_digest,
            correlation_id=context.correlation_id,
            causation_id=str(uuid.uuid5(CAUSATION_NAMESPACE, request.operation_id)),
            created_at=self._clock.now(),
        )
        self._references.register(source_ref, source_digest, provenance)
        return provenance

    def _base_mapping(
        self,
        *,
        item_id: str,
        kind: MemoryKind,
        schema: str,
        payload: bytes,
        sources: Sequence[GovernedMemoryItem],
        source_ref: str,
        source_digest: str,
        provenance_id: str,
        context: GovernedContext,
        bindings: Mapping[str, str],
        scope: MemoryScope,
        status: LifecycleStatus,
        retention: str,
        confidence: float,
        consolidates: Sequence[str],
        derived_from: Sequence[str],
        version: int = 1,
        references: Sequence[GovernedMemoryItem] | None = None,
    ) -> dict[str, object]:
        now = self._clock.now()
        cited = sources if references is None else references
        taint = {DERIVED_TAINT} | {label for item in sources for label in item.taint_labels}
        if kind is MemoryKind.REFLECTION:
            taint.add(MODEL_TAINT)
        marking = self._markings.join(
            [context.classification_marking_ref, *(item.classification_marking_ref for item in sources)]
        )
        content_digest = _sha256(payload)
        mapping: dict[str, object] = {
            "memory_item_id": item_id,
            "memory_version": version,
            "memory_kind": kind.value,
            "memory_scope": scope.value,
            "owner_principal_id": context.effective_principal_id,
            "tenant_id": context.tenant_id,
            "organization_id": context.organization_id,
            "domain_id": context.domain_id,
            "compartments": list(context.compartments),
            "classification_marking_ref": marking,
            "purpose": context.purpose,
            "content_schema_ref": schema,
            "content_ref": f"urn:ocor:memory-content-object:{_hex(content_digest)}",
            "content_digest": content_digest,
            "source_kind": SourceKind.MEMORY_CONSOLIDATION.value,
            "source_ref": source_ref,
            "source_digest": source_digest,
            "evidence_refs": sorted({ref for item in cited for ref in item.evidence_refs}),
            "provenance_refs": sorted(
                {provenance_id} | {ref for item in cited for ref in item.provenance_refs}
            ),
            "derived_from_refs": sorted(set(derived_from)),
            "consolidates_refs": sorted(set(consolidates)),
            "created_at": format_utc_timestamp(now),
            "valid_from": format_utc_timestamp(max(item.valid_from for item in sources)),
            "retention_policy_ref": retention,
            "confidence": confidence,
            "policy_bundle_digest": context.policy_bundle_digest,
            "ontology_release_digest": context.ontology_release_digest,
            "governed_context_digest": context.digest(),
            "instruction_eligible": False,
            "taint_labels": sorted(taint),
            "representation_kinds": list(DERIVED_REPRESENTATIONS),
            "lifecycle_status": status.value,
            "uncertainty_ref": "",
        }
        until = [item.valid_until for item in sources if item.valid_until is not None]
        if until:
            mapping["valid_until"] = format_utc_timestamp(min(until))
        mapping.update(bindings)
        return mapping

    def _dissent_item(
        self,
        conflict: Mapping[str, object],
        by_ref: Mapping[str, ClaimSource],
        items_by_ref: Mapping[str, GovernedMemoryItem],
        plan: _Plan,
    ) -> _Derived:
        job = plan.job
        alternatives = conflict["alternatives"]
        assert isinstance(alternatives, list)
        refs = sorted({ref for alt in alternatives for ref in alt["support_refs"]})
        conflicting = [by_ref[ref] for ref in refs]
        payload = canonical_bytes(
            {
                "content_schema_ref": DISSENT_SCHEMA,
                "job_ref": job.job_ref,
                "conflict": dict(conflict),
                "sources": [source.citation() for source in conflicting],
            }
        )
        item_id = "dissent-" + _hex(
            canonical_digest({"job": job.digest, "conflict_id": conflict["conflict_id"]})
        )[:32]
        mapping = self._base_mapping(
            item_id=item_id,
            kind=MemoryKind.DISSENT,
            schema=DISSENT_SCHEMA,
            payload=payload,
            sources=[items_by_ref[ref] for ref in refs],
            source_ref=job.job_ref,
            source_digest=job.digest,
            provenance_id=plan.provenance_id,
            context=plan.context,
            bindings=plan.bindings,
            scope=job.target_scope,
            status=plan.status,
            retention=plan.profile.retention_policy_ref,
            confidence=min(source.confidence for source in conflicting),
            consolidates=refs,
            derived_from=refs,
        )
        mapping["uncertainty_ref"] = "urn:ocor:memory-uncertainty:" + _hex(
            canonical_digest({"conflict_id": conflict["conflict_id"], "resolution": UNRESOLVED})
        )
        return _Derived(GovernedMemoryItem.from_mapping(mapping), payload, f"dissent:{item_id}")

    def _summary_item(
        self,
        merged: MergeResult,
        sources: Sequence[ClaimSource],
        dissent_refs: Sequence[str],
        items: Sequence[GovernedMemoryItem],
        plan: _Plan,
    ) -> _Derived:
        job = plan.job
        conflicts = [
            {**conflict, "dissent_ref": ref}
            for conflict, ref in zip(merged.conflicts, dissent_refs, strict=True)
        ]
        uncertainty = uncertainty_record(sources, len(merged.statements), len(conflicts))
        schema = REFLECTION_SCHEMA if job.target_kind is MemoryKind.REFLECTION else SUMMARY_SCHEMA
        payload = canonical_bytes(
            {
                "content_schema_ref": schema,
                "job_ref": job.job_ref,
                "algorithm": dict(job.algorithm),
                "sources": [source.citation() for source in sources],
                "statements": [dict(s) for s in merged.statements],
                "conflicts": conflicts,
                "uncertainty": uncertainty,
                "correction": None,
            }
        )
        mapping = self._base_mapping(
            item_id="consolidated-" + _hex(job.digest)[:32],
            kind=job.target_kind,
            schema=schema,
            payload=payload,
            sources=items,
            source_ref=job.job_ref,
            source_digest=job.digest,
            provenance_id=plan.provenance_id,
            context=plan.context,
            bindings=plan.bindings,
            scope=job.target_scope,
            status=plan.status,
            retention=plan.profile.retention_policy_ref,
            confidence=bounded_confidence(
                min(source.confidence for source in sources), len(merged.statements), len(conflicts)
            ),
            consolidates=job.input_refs,
            derived_from=[*job.input_refs, *dissent_refs],
        )
        mapping["uncertainty_ref"] = "urn:ocor:memory-uncertainty:" + _hex(
            canonical_digest(uncertainty)
        )
        return _Derived(GovernedMemoryItem.from_mapping(mapping), payload, "summary")

    def _admit_and_commit(
        self, derived: _Derived, request: _Request, binding: VerifiedGovernedContextBinding
    ) -> AdmittedMemoryVersion:
        item = derived.item
        existing = self._ledger.get(item.memory_item_id, item.memory_version)
        if existing is not None:
            # Completion of a job interrupted after this admission: the slot must
            # hold exactly this derivation (same job, same content).
            if not (
                hmac.compare_digest(existing.item.source_digest, item.source_digest)
                and hmac.compare_digest(existing.item.content_digest, item.content_digest)
                and existing.item.memory_kind is item.memory_kind
            ):
                raise MemoryConsolidationError(
                    "MEMORY_IDEMPOTENCY_CONFLICT",
                    "DERIVED_SLOT_OCCUPIED",
                    f"{item.version_ref} is occupied by another derivation",
                )
            record = existing
        else:
            digest = item.digest()
            self._guard.expect(digest)
            try:
                self._admission.admit(
                    {
                        "operation_id": f"{request.operation_id}:{derived.operation_suffix}",
                        "governed_context": request.context.to_mapping(),
                        "governed_context_digest": request.gcs_digest,
                        "deadline": format_utc_timestamp(request.deadline),
                        "candidate": item.to_mapping(),
                    },
                    binding=binding,
                    payload=derived.payload,
                )
            finally:
                self._guard.release(digest)
            admitted = self._ledger.get(item.memory_item_id, item.memory_version)
            if admitted is None:
                raise MemoryConsolidationError(
                    "INTERNAL_ERROR", "DERIVED_NOT_PERSISTED", "admission did not persist"
                )
            record = admitted
        self._coordinator.commit(record, payload=derived.payload)
        return record

    def _complete(
        self,
        request: _Request,
        kind: str,
        job_ref: str,
        job_digest: str,
        derived: GovernedMemoryItem,
        dissent_refs: tuple[str, ...],
        audit_event: Mapping[str, object],
    ) -> ConsolidationOutcome:
        try:
            self._audit.record(audit_event)
        except Exception as exc:  # noqa: BLE001 -- no receipt without its audit event
            raise MemoryConsolidationError(
                "CONTROL_PLANE_UNAVAILABLE",
                "AUDIT_UNAVAILABLE",
                "the operation could not be audited; retry completes it",
            ) from exc
        receipt = {
            "operation_id": request.operation_id,
            "operation_kind": kind,
            "status": "COMPLETED",
            "governed_context_digest": request.gcs_digest,
            "audit_ref": canonical_digest(dict(audit_event)),
        }
        outcome = ConsolidationOutcome(
            receipt=MappingProxyType(receipt),
            operation_kind=kind,
            job_ref=job_ref,
            job_digest=job_digest,
            derived_ref=derived.version_ref,
            dissent_refs=dissent_refs,
            lifecycle_status=derived.lifecycle_status.value,
        )
        try:
            self._jobs.append(
                ConsolidationJobRecord(
                    tenant_id=request.context.tenant_id,
                    operation_id=request.operation_id,
                    outcome=outcome,
                    audit_event=MappingProxyType(dict(audit_event)),
                )
            )
        except MemoryAdmissionError:
            raise
        except Exception as exc:  # noqa: BLE001 -- an unrecorded completion fails closed
            raise MemoryConsolidationError(
                "CONTROL_PLANE_UNAVAILABLE",
                "JOB_LEDGER_UNAVAILABLE",
                "the completion could not be recorded; retry completes it",
            ) from exc
        return outcome

    # -- correction --------------------------------------------------------

    def _correct(
        self, request: _Request, binding: VerifiedGovernedContextBinding
    ) -> tuple[ConsolidationOutcome, bool]:
        body = request.body
        context = request.context
        target_ref = _string("target_version_ref", body["target_version_ref"])
        reason_ref = _string("correction_reason_ref", body["correction_reason_ref"])
        statements = _corrected_statements(body["corrected_statements"])
        target = self._correction_visible(target_ref, context)
        correction = {
            "operation_id": request.operation_id,
            "tenant_id": context.tenant_id,
            "isolation": _isolation(context),
            "target_version_ref": target.version_ref,
            "target_item_digest": target.digest(),
            "corrected_statements": [dict(s) for s in statements],
            "correction_reason_ref": reason_ref,
        }
        correction_digest = canonical_digest(correction)
        correction_ref = f"urn:ocor:memory-correction:{_hex(correction_digest)}"
        replayed = self._replay(request, correction_digest)
        if replayed is not None:
            return replayed, True
        self._check_correction_target(target)
        payload = self._consolidated_payload(target)
        cited = {str(entry["memory_version_ref"]) for entry in _members(payload, "sources")}
        conflict_keys = {
            (str(c["subject"]), str(c["attribute"])) for c in _members(payload, "conflicts")
        }
        for statement in statements:
            if (str(statement["subject"]), str(statement["attribute"])) in conflict_keys:
                raise MemoryConsolidationError(
                    "POLICY_DENIED",
                    "DISSENT_ERASURE",
                    "a correction cannot resolve or rewrite a preserved conflict",
                )
            support = statement["support_refs"]
            assert isinstance(support, list)
            if not set(support) <= cited:
                raise MemoryConsolidationError(
                    "POLICY_DENIED",
                    "CORRECTION_SOURCE_REWRITE",
                    "a correction can only cite the sources of the corrected version",
                )
        sources = self._cited_sources(payload)
        decision = self._decide(lambda: self._policy.authorize_correction(target, context), context)
        provenance = self._register_source(
            source_ref=correction_ref,
            source_digest=correction_digest,
            kind="correction",
            activity_refs=(reason_ref,),
            request=request,
            items=sources,
        )
        corrected_keys = {(str(s["subject"]), str(s["attribute"])) for s in statements}
        kept = [
            s
            for s in _members(payload, "statements")
            if (str(s["subject"]), str(s["attribute"])) not in corrected_keys
        ]
        new_statements = sorted(
            [*kept, *(dict(s) for s in statements)],
            key=lambda s: (str(s["subject"]), str(s["attribute"])),
        )
        conflicts = _members(payload, "conflicts")
        claim_sources = [
            ClaimSource(
                version_ref=item.version_ref,
                item_digest=item.digest(),
                content_digest=item.content_digest,
                confidence=float(item.confidence),
                assertions=(),
            )
            for item in sources
        ]
        uncertainty = uncertainty_record(claim_sources, len(new_statements), len(conflicts))
        new_payload = canonical_bytes(
            {
                **payload,
                "statements": new_statements,
                "uncertainty": uncertainty,
                "correction": {
                    "correction_ref": correction_ref,
                    "correction_of_ref": target.version_ref,
                    "correction_reason_ref": reason_ref,
                    "corrected_keys": [
                        {"subject": subject, "attribute": attribute}
                        for subject, attribute in sorted(corrected_keys)
                    ],
                },
            }
        )
        version = target.memory_version + 1
        lineage = [
            *sources,
            *(
                record.item
                for ref in target.derived_from_refs
                if (record := self._version(ref)) is not None
            ),
        ]
        mapping = self._base_mapping(
            item_id=target.memory_item_id,
            kind=target.memory_kind,
            schema=target.content_schema_ref,
            payload=new_payload,
            sources=[target, *lineage],
            source_ref=correction_ref,
            source_digest=correction_digest,
            provenance_id=provenance.provenance_id,
            context=context,
            bindings={name: str(getattr(target, name)) for name in SCOPE_BINDINGS[target.memory_scope]},
            scope=target.memory_scope,
            status=target.lifecycle_status,
            retention=target.retention_policy_ref,
            confidence=bounded_confidence(
                min(source.confidence for source in claim_sources), len(new_statements), len(conflicts)
            ),
            consolidates=target.consolidates_refs,
            derived_from=target.derived_from_refs,
            version=version,
            references=sources,
        )
        mapping["supersedes_ref"] = target.version_ref
        mapping["correction_of_ref"] = target.version_ref
        mapping["valid_from"] = format_utc_timestamp(target.valid_from)
        if target.valid_until is not None:
            mapping["valid_until"] = format_utc_timestamp(target.valid_until)
        mapping["uncertainty_ref"] = "urn:ocor:memory-uncertainty:" + _hex(
            canonical_digest(uncertainty)
        )
        derived = _Derived(GovernedMemoryItem.from_mapping(mapping), new_payload, "correction")
        record = self._admit_and_commit(derived, request, binding)
        dissent_refs = tuple(str(c["dissent_ref"]) for c in conflicts)
        audit_event = {
            "action": OPERATION_CORRECT,
            "outcome": "COMPLETED",
            "operation_id": request.operation_id,
            "job_ref": correction_ref,
            "job_digest": correction_digest,
            "correction_of_ref": target.version_ref,
            "correction_reason_ref": reason_ref,
            "derived_ref": record.item.version_ref,
            "derived_item_digests": [record.item_digest],
            "dissent_refs": list(dissent_refs),
            "lifecycle_status": record.item.lifecycle_status.value,
            "policy_decision_ref": decision.decision_ref,
            "policy_bundle_digest": decision.policy_bundle_digest,
            "governed_context_digest": request.gcs_digest,
            "binding_ref": binding.binding_ref,
            "correlation_id": context.correlation_id,
            "at": format_utc_timestamp(self._clock.now()),
        }
        outcome = self._complete(
            request, OPERATION_CORRECT, correction_ref, correction_digest, record.item, dissent_refs, audit_event
        )
        return outcome, False

    def _version(self, ref: str) -> AdmittedMemoryVersion | None:
        item_id, version = parse_memory_version_ref(ref)
        return self._ledger.get(item_id, version)

    def _correction_visible(self, ref: str, context: GovernedContext) -> GovernedMemoryItem:
        unavailable = MemoryConsolidationError(
            "MEMORY_VERSION_NOT_FOUND",
            "CORRECTION_TARGET_UNAVAILABLE",
            "the correction target does not resolve to a version visible to the caller",
        )
        try:
            record = self._version(ref)
        except MemoryAdmissionError as exc:
            raise unavailable from exc
        if record is None or not self._visible(record.item, context):
            raise unavailable
        return record.item

    def _check_correction_target(self, item: GovernedMemoryItem) -> None:
        if item.source_kind is not SourceKind.MEMORY_CONSOLIDATION:
            raise MemoryConsolidationError(
                "UNSUPPORTED_CAPABILITY",
                "CORRECTION_TARGET_NOT_CONSOLIDATED",
                "only consolidation-derived memory is corrected here",
            )
        if item.memory_kind is MemoryKind.DISSENT:
            raise MemoryConsolidationError(
                "POLICY_DENIED",
                "DISSENT_IMMUTABLE",
                "dissent is never overwritten; a resolution is a separate record",
            )
        if self._ledger.latest_version(item.memory_item_id) != item.memory_version:
            raise MemoryConsolidationError(
                "LIFECYCLE_TRANSITION_INVALID",
                "CORRECTION_TARGET_NOT_CURRENT",
                "only the current version is corrected",
            )
        if item.lifecycle_status not in CORRECTABLE_STATUSES:
            raise MemoryConsolidationError(
                "LIFECYCLE_TRANSITION_INVALID",
                "CORRECTION_TARGET_NOT_CORRECTABLE",
                "the target lifecycle status does not admit a correction",
            )

    def _consolidated_payload(self, item: GovernedMemoryItem) -> dict[str, object]:
        materialized = self._coordinator.read_version(
            MemoryPartition.for_item(item), item.memory_item_id, item.memory_version
        )
        if not hmac.compare_digest(_sha256(materialized.payload), item.content_digest):
            raise MemoryConsolidationError(
                "INTERNAL_ERROR", "CONSOLIDATED_PAYLOAD_DRIFT", "stored payload does not bind"
            )
        try:
            document = parse_i_json(materialized.payload)
        except (CanonicalizationError, ValueError) as exc:
            raise MemoryConsolidationError(
                "INTERNAL_ERROR", "CONSOLIDATED_PAYLOAD_INVALID", "payload is not I-JSON"
            ) from exc
        expected = {
            "content_schema_ref",
            "job_ref",
            "algorithm",
            "sources",
            "statements",
            "conflicts",
            "uncertainty",
            "correction",
        }
        if (
            not isinstance(document, dict)
            or set(document) != expected
            or not isinstance(document["sources"], list)
            or not isinstance(document["statements"], list)
            or not isinstance(document["conflicts"], list)
        ):
            raise MemoryConsolidationError(
                "INTERNAL_ERROR",
                "CONSOLIDATED_PAYLOAD_INVALID",
                "payload is not a consolidated summary",
            )
        return document

    def _cited_sources(self, payload: Mapping[str, object]) -> list[GovernedMemoryItem]:
        sources: list[GovernedMemoryItem] = []
        for citation in _members(payload, "sources"):
            record = self._version(str(citation["memory_version_ref"]))
            if record is None or not (
                hmac.compare_digest(record.item_digest, str(citation["item_digest"]))
                and hmac.compare_digest(record.item.content_digest, str(citation["content_digest"]))
            ):
                raise MemoryConsolidationError(
                    "INTERNAL_ERROR",
                    "SOURCE_CITATION_BROKEN",
                    "a cited source no longer binds its citation",
                )
            sources.append(record.item)
        return sources


def _members(payload: Mapping[str, object], name: str) -> list[Mapping[str, object]]:
    raw = payload[name]
    if not isinstance(raw, list) or not all(isinstance(entry, Mapping) for entry in raw):
        raise MemoryConsolidationError(
            "INTERNAL_ERROR", "CONSOLIDATED_PAYLOAD_INVALID", f"{name} is not a list of objects"
        )
    return list(raw)


def _isolation(context: GovernedContext) -> dict[str, object]:
    """The isolation tuple of the caller, without the per-request correlation id."""

    mapping = context.to_mapping()
    mapping.pop("correlation_id", None)
    return mapping


def _corrected_statements(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not value:
        raise _schema_error("ENVELOPE_INVALID", "corrected_statements must be a non-empty array")
    result: list[Mapping[str, object]] = []
    keys: set[tuple[str, str]] = set()
    for entry in value:
        if not isinstance(entry, Mapping) or set(entry) != STATEMENT_FIELDS:
            raise _schema_error(
                "ENVELOPE_INVALID", "statement must be {subject, attribute, value, support_refs}"
            )
        subject = _string("subject", entry["subject"])
        attribute = _string("attribute", entry["attribute"])
        if isinstance(entry["value"], (dict, list)):
            raise _schema_error("ENVELOPE_INVALID", "statement value must be a scalar")
        support = _ref_list("support_refs", entry["support_refs"])
        if (subject, attribute) in keys:
            raise _schema_error("ENVELOPE_INVALID", "a statement key is corrected twice")
        keys.add((subject, attribute))
        result.append(
            {
                "subject": subject,
                "attribute": attribute,
                "value": entry["value"],
                "support_refs": list(support),
            }
        )
    return result


__all__ = [
    "CLAIM_MERGE",
    "CONSOLIDATION_REQUEST_FIELDS",
    "CONSOLIDATION_TARGET_KINDS",
    "CORRECTION_REQUEST_FIELDS",
    "ClaimSource",
    "ConsolidationAlgorithm",
    "ConsolidationAuditSink",
    "ConsolidationGuardPolicy",
    "ConsolidationJobLedger",
    "ConsolidationJobRecord",
    "ConsolidationLedgerCorrupted",
    "ConsolidationOutcome",
    "ConsolidationPolicy",
    "ConsolidationProfile",
    "ConsolidationProfileRegistry",
    "ConsolidationReferenceResolver",
    "InMemoryConsolidationJobLedger",
    "JournalConsolidationJobLedger",
    "MemoryConsolidationError",
    "MemoryConsolidationJob",
    "MemoryConsolidationService",
    "MergeResult",
    "bounded_confidence",
    "merge_claims",
    "parse_assertions",
    "uncertainty_record",
]
