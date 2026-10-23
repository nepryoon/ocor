"""Memory promotion proposals (ADD v1.3 II 2.4/2.11; LLD 2.8.7).

The memory port creates a content-free, immutable proposal in the protected
audit store. It has no canonical writer, security writer or memory writer.
A proposal is never an Approval, Decision, Authority or canonical assertion.
Only a separately wired C6 consumer may turn a reviewed proposal into a
GovernedCanonicalCommitCommand. Consumption revalidates the exact source,
GCS, live retrieval/promotion policy, stop epoch and deadline.

Ports are trusted composition dependencies, never caller-supplied members.
Audit/receipt persistence is an authority boundary: digests detect accidental
corruption, not a malicious audit authority. The final control check and the
external audit/commit cannot be atomic with the current store ports; this is
an open FGM-17 qualification concern, not a runtime conformance claim.
"""
from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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
from .context import ContextReceiptStore, _ExactSearch
from .model import (
    GovernedMemoryItem,
    MarkingDominance,
    MemoryAdmissionError,
    MemoryKind,
    MemoryPolicyDecision,
    MemoryScope,
)
from .retrieval import (
    ENVELOPE_FIELDS,
    MemoryRetrievalPolicy,
    RankingProfile,
    RetrievalAuditSink,
    StopEpochPort,
    _Candidate,
    _Plan,
)
from .stores import MemoryMetadataStore, MemoryStoreCoordinator

REQUEST_FIELDS = ENVELOPE_FIELDS | {
    "memory_version", "target_aggregate_type", "target_aggregate_ref", "proposal_schema_ref",
}
# A profile must be explicitly registered by trusted composition. Security and
# policy mutations are never a memory-promotion target, even with a profile.
FORBIDDEN_TARGETS = frozenset({
    "Authority", "Delegation", "Approval", "Decision", "CapabilityLease",
    "ActionCommand", "Policy", "PolicyBundle", "Capability", "Identity",
})


class MemoryPromotionError(MemoryAdmissionError):
    """Closed memory Problem code plus bounded promotion detail."""


def _error(detail: str, reason: str = "POLICY_DENIED") -> MemoryPromotionError:
    return MemoryPromotionError(reason, detail, "memory promotion refused")


def _reference(value: object) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 256 and not any(ord(c) < 32 for c in value)


@dataclass(frozen=True, slots=True)
class PromotionProfile:
    """One explicitly registered proposal schema and canonical aggregate type."""

    schema_ref: str
    target_aggregate_type: str

    def __post_init__(self) -> None:
        if not _reference(self.schema_ref) or not _reference(self.target_aggregate_type):
            raise ValueError("promotion profiles require bounded named references")
        if self.target_aggregate_type.casefold() in {t.casefold() for t in FORBIDDEN_TARGETS}:
            raise ValueError("memory cannot promote security or policy objects")


class MemoryPromotionPolicy(Protocol):
    def authorize_promotion(
        self, item: GovernedMemoryItem, context: GovernedContext,
        target_aggregate_type: str, target_aggregate_ref: str,
    ) -> MemoryPolicyDecision: ...


@dataclass(frozen=True, slots=True)
class MemoryPromotionProposal:
    """Non-authoritative source refs and target, never executable content."""

    operation_id: str
    source_version_ref: str
    source_item_digest: str
    content_ref: str
    content_digest: str
    evidence_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    classification_marking_ref: str
    taint_labels: tuple[str, ...]
    target_aggregate_type: str
    target_aggregate_ref: str
    proposal_schema_ref: str
    governed_context_digest: str
    stop_epoch: int
    deadline: datetime

    def to_mapping(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "source_version_ref": self.source_version_ref,
            "source_item_digest": self.source_item_digest,
            "content_ref": self.content_ref,
            "content_digest": self.content_digest,
            "evidence_refs": list(self.evidence_refs),
            "provenance_refs": list(self.provenance_refs),
            "classification_marking_ref": self.classification_marking_ref,
            "taint_labels": list(self.taint_labels),
            "target_aggregate_type": self.target_aggregate_type,
            "target_aggregate_ref": self.target_aggregate_ref,
            "proposal_schema_ref": self.proposal_schema_ref,
            "governed_context_digest": self.governed_context_digest,
            "stop_epoch": self.stop_epoch,
            "deadline": format_utc_timestamp(self.deadline),
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


@dataclass(frozen=True, slots=True)
class PromotionReceipt:
    proposal: MemoryPromotionProposal
    audit_ref: str

    def to_mapping(self) -> dict[str, object]:
        # Exactly the public OperationReceipt, never a canonical commit receipt.
        return {
            "operation_id": self.proposal.operation_id,
            "operation_kind": "proposeMemoryPromotion",
            "status": "ACCEPTED",
            "governed_context_digest": self.proposal.governed_context_digest,
            "audit_ref": self.audit_ref,
        }


class MemoryPromotionService:
    """MemoryPromotionPort: record a proposal; revalidate it for C6 consumption."""

    def __init__(
        self, *, coordinator: MemoryStoreCoordinator, metadata: MemoryMetadataStore,
        retrieval_policy: MemoryRetrievalPolicy, promotion_policy: MemoryPromotionPolicy,
        markings: MarkingDominance, stop: StopEpochPort, audit: RetrievalAuditSink,
        receipts: ContextReceiptStore, clock: TrustedClock,
        profiles: tuple[PromotionProfile, ...],
    ) -> None:
        self._search = _ExactSearch(
            coordinator=coordinator, metadata=metadata, policy=retrieval_policy,
            markings=markings, stop=stop, audit=audit, clock=clock,
        )
        self._policy, self._audit, self._receipts, self._clock = promotion_policy, audit, receipts, clock
        keyed = {(p.schema_ref, p.target_aggregate_type): p for p in profiles}
        if not profiles or len(keyed) != len(profiles):
            raise ValueError("non-empty unambiguous promotion profiles required")
        self._profiles = MappingProxyType(keyed)

    def _append(self, event: Mapping[str, object]) -> str:
        audit_ref = canonical_digest(event)
        try:
            self._audit.record(MappingProxyType({**event, "audit_ref": audit_ref}))
        except Exception as exc:  # noqa: BLE001 -- audit is a mandatory authority
            raise _error("AUDIT_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc
        return audit_ref

    def _deny(
        self, action: str, binding: VerifiedGovernedContextBinding | None,
        operation_id: object, error: MemoryAdmissionError,
    ) -> None:
        self._append({
            "action": action + ".denied", "reason_code": error.reason_code,
            "detail_code": error.detail_code,
            "operation_id": operation_id if _reference(operation_id) else None,
            "causation_id": operation_id if _reference(operation_id) else None,
            "correlation_id": binding.expected.correlation_id if binding else None,
            "governed_context_digest": binding.expected.digest() if binding else None,
            "evaluated_at": format_utc_timestamp(self._clock.now()),
        })

    @staticmethod
    def _binding(binding: VerifiedGovernedContextBinding | None) -> VerifiedGovernedContextBinding:
        if not isinstance(binding, VerifiedGovernedContextBinding):
            raise _error("BINDING_MISSING", "AUTHENTICATION_REQUIRED")
        return binding

    def _request(
        self, item_id: str, request: Mapping[str, object], binding: VerifiedGovernedContextBinding,
    ) -> tuple[GovernedContext, str, int, datetime]:
        if not _reference(item_id) or not isinstance(request, Mapping) or set(request) != REQUEST_FIELDS:
            raise _error("REQUEST_INVALID", "MEMORY_SCHEMA_INVALID")
        version = request["memory_version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise _error("REQUEST_INVALID", "MEMORY_SCHEMA_INVALID")
        for name in ("operation_id", "target_aggregate_type", "target_aggregate_ref", "proposal_schema_ref"):
            if not _reference(request[name]):
                raise _error("REQUEST_INVALID", "MEMORY_SCHEMA_INVALID")
        key = (str(request["proposal_schema_ref"]), str(request["target_aggregate_type"]))
        if key not in self._profiles:
            raise _error("PROFILE_NOT_REGISTERED", "UNSUPPORTED_CAPABILITY")
        raw_context, claimed = request["governed_context"], request["governed_context_digest"]
        if not isinstance(raw_context, Mapping) or not isinstance(claimed, str):
            raise _error("GCS_INVALID", "GOVERNED_CONTEXT_MISMATCH")
        try:
            ctx = GovernedContextCodec.from_openapi(raw_context, binding, claimed)
        except GovernedContextError as exc:
            raise _error(exc.code, "GOVERNED_CONTEXT_MISMATCH") from exc
        raw_deadline = request["deadline"]
        try:
            if not isinstance(raw_deadline, str):
                raise ValueError("deadline must be a timestamp")
            deadline = parse_utc_timestamp(raw_deadline)
        except (TimestampError, ValueError) as exc:
            raise _error("ENVELOPE_INVALID", "MEMORY_SCHEMA_INVALID") from exc
        if deadline <= self._clock.now():
            raise _error("DEADLINE_EXCEEDED")
        return ctx, str(request["operation_id"]), version, deadline

    def _plan(self, request: Mapping[str, object], binding: VerifiedGovernedContextBinding) -> _Plan:
        # Reuse 0052 exact-version policy/partition checks without scanning any
        # index or opening content. Promotion is not a top-k search.
        return self._search.exact_plan({
            **{k: request[k] for k in ENVELOPE_FIELDS},
            "query_contract_id": "urn:ocor:memory-query:structured",
            "query_contract_version": "1.0", "retrieval_mode": "STRUCTURED",
            "memory_kinds": [k.value for k in MemoryKind],
            "memory_scopes": [s.value for s in MemoryScope], "parameters": {},
            "top_k": 1, "ranking_profile_ref": RankingProfile().profile_ref,
        }, binding)

    def _source(self, plan: _Plan, item_id: str, version: int) -> _Candidate:
        candidate = self._search.exact(plan, item_id, version)
        if candidate is None:
            # Identical for unknown, invisible, non-head, uncommitted or inactive.
            raise _error("SOURCE_NOT_ELIGIBLE")
        return candidate

    def _authorize(self, candidate: _Candidate, ctx: GovernedContext, request: Mapping[str, object]) -> None:
        try:
            decision = self._policy.authorize_promotion(
                candidate.item, ctx, str(request["target_aggregate_type"]), str(request["target_aggregate_ref"]),
            )
        except MemoryAdmissionError:
            raise
        except Exception as exc:  # noqa: BLE001 -- no unavailable-control fallback
            raise _error("PROMOTION_POLICY_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc
        if (not isinstance(decision, MemoryPolicyDecision) or not isinstance(decision.permitted, bool)
                or not _reference(decision.decision_ref)):
            raise _error("PROMOTION_POLICY_INVALID", "CONTROL_PLANE_UNAVAILABLE")
        if decision.policy_bundle_digest != ctx.policy_bundle_digest:
            raise _error("POLICY_BUNDLE_MISMATCH", "STALE_POLICY")
        if not decision.permitted:
            raise _error("PROMOTION_DENIED")

    def _validate(
        self, item_id: str, request: Mapping[str, object], binding: VerifiedGovernedContextBinding,
        *, expected_epoch: int | None = None,
    ) -> MemoryPromotionProposal:
        ctx, operation, version, deadline = self._request(item_id, request, binding)
        plan = self._plan(request, binding)
        if expected_epoch is not None and plan.stop_epoch != expected_epoch:
            raise _error("STOP_EPOCH_CHANGED", "STOP_EPOCH_MISMATCH")
        candidate = self._source(plan, item_id, version)
        self._authorize(candidate, ctx, request)
        # Policy I/O can change the source or advance the boundary clock. Refresh
        # the plan so expiry/validity use current time, never the initial snapshot.
        fresh = self._plan(request, binding)
        current = self._source(fresh, item_id, version)
        if current.stored.staged.stage_digest != candidate.stored.staged.stage_digest:
            raise _error("CANDIDATE_CHANGED", "REPRESENTATION_NOT_READY")
        if fresh.stop_epoch != plan.stop_epoch:
            raise _error("STOP_EPOCH_CHANGED", "STOP_EPOCH_MISMATCH")
        self._search.require_stop_epoch(fresh)
        if self._clock.now() >= deadline:
            raise _error("DEADLINE_EXCEEDED")
        item = current.item
        return MemoryPromotionProposal(
            operation_id=operation, source_version_ref=item.version_ref,
            source_item_digest=item.digest(), content_ref=item.content_ref, content_digest=item.content_digest,
            evidence_refs=tuple(item.evidence_refs), provenance_refs=tuple(item.provenance_refs),
            classification_marking_ref=item.classification_marking_ref, taint_labels=tuple(sorted(item.taint_labels)),
            target_aggregate_type=str(request["target_aggregate_type"]),
            target_aggregate_ref=str(request["target_aggregate_ref"]),
            proposal_schema_ref=str(request["proposal_schema_ref"]),
            governed_context_digest=ctx.digest(), stop_epoch=fresh.stop_epoch, deadline=deadline,
        )

    def propose(
        self, memory_item_id: str, request: Mapping[str, object], *,
        binding: VerifiedGovernedContextBinding | None,
    ) -> PromotionReceipt:
        operation = request.get("operation_id") if isinstance(request, Mapping) else None
        try:
            verified = self._binding(binding)
            proposal = self._validate(memory_item_id, request, verified)
            ref = self._append({
                "action": "proposeMemoryPromotion.recorded", "proposal": proposal.to_mapping(),
                "proposal_digest": proposal.digest, "memory_item_id": memory_item_id,
                "request": dict(request), "binding_ref": verified.binding_ref,
                "correlation_id": verified.expected.correlation_id,
                "causation_id": proposal.operation_id,
            })
            # Never return a stale proposal merely because the audit call succeeded.
            checked = self._validate(memory_item_id, request, verified, expected_epoch=proposal.stop_epoch)
            if checked != proposal:
                raise _error("CANDIDATE_CHANGED", "REPRESENTATION_NOT_READY")
            return PromotionReceipt(proposal, ref)
        except MemoryAdmissionError as exc:
            self._deny("proposeMemoryPromotion", binding, operation, exc)
            raise
        except Exception as exc:  # noqa: BLE001 -- backend read errors fail closed and audited
            error = _error("PROMOTION_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE")
            self._deny("proposeMemoryPromotion", binding, operation, error)
            raise error from exc

    def load(self, audit_ref: str, *, binding: VerifiedGovernedContextBinding | None) -> MemoryPromotionProposal:
        """Revalidate a recorded proposal for the C6 consumer; never grant control."""
        try:
            verified = self._binding(binding)
            if not _reference(audit_ref):
                raise _error("PROPOSAL_UNRECORDED")
            receipt = self._receipts.receipt(audit_ref)
            if receipt is None:
                raise _error("PROPOSAL_UNRECORDED")
            core = {k: v for k, v in receipt.items() if k != "audit_ref"}
            if (receipt.get("audit_ref") != audit_ref or not hmac.compare_digest(canonical_digest(core), audit_ref)
                    or receipt.get("action") != "proposeMemoryPromotion.recorded"):
                raise _error("PROPOSAL_DIGEST_MISMATCH")
            raw = receipt.get("request")
            item_id = receipt.get("memory_item_id")
            old = receipt.get("proposal")
            if not isinstance(raw, Mapping) or not isinstance(item_id, str) or not isinstance(old, Mapping):
                raise _error("PROPOSAL_DIGEST_MISMATCH")
            epoch = old.get("stop_epoch")
            if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
                raise _error("PROPOSAL_DIGEST_MISMATCH")
            proposal = self._validate(item_id, raw, verified, expected_epoch=epoch)
            if proposal.to_mapping() != old or receipt.get("proposal_digest") != proposal.digest:
                raise _error("PROPOSAL_DIGEST_MISMATCH")
            return proposal
        except MemoryAdmissionError as exc:
            self._deny("consumeMemoryPromotion", binding, None, exc)
            raise
        except Exception as exc:  # noqa: BLE001 -- no unauthenticated/missing-store fallback
            error = _error("PROMOTION_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE")
            self._deny("consumeMemoryPromotion", binding, None, error)
            raise error from exc
