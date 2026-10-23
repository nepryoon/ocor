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
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
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
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,95}")
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


# The following adapter belongs to the C6 side of the port. Its dependencies
# are deliberately absent from MemoryPromotionService. It consumes controls
# issued by a separate C6 authority, it never issues them from memory.

from ..c3.ports import CommitReceipt, GovernedCanonicalCommitCommand, GovernedCommitPort  # noqa: E402
from ..c6.human_gate import (  # noqa: E402
    ApprovalPolicy,
    GateSignature,
    HumanGateCoordinator,
    HumanGateError,
)
from ..kernel.canonical import canonical_bytes, parse_i_json  # noqa: E402
from ..kernel.governance import (  # noqa: E402
    Authority,
    AuthorityRequest,
    GovernanceFault,
    RiskClass,
    VerifiedAuthorityBinding,
    validate_authority,
)


@dataclass(frozen=True, slots=True)
class SignedPromotionGate:
    """Canonical closed C6 gate bytes, signed by an independently trusted signer.

    The signer attests its Authority/delegation validation and the Decision;
    the consumer still rechecks revocation, Authority scope/window, policy,
    Human Gate identity/quorum/TTL and the source immediately before C3.
    A reference or a signature-shaped string alone never passes verification.
    """

    payload: bytes
    signature: str


class PromotionGateVerifier(Protocol):
    def verify(self, payload: bytes, signature: str) -> bool: ...


class PromotionControlStore(Protocol):
    """Protected C6 control authority, separate from the memory audit store.

    gate() never creates a gate. revoked() also covers revocation of an
    ancestor delegation/authority of the addressed control record.
    verified_delegation() returns the SignedDelegation that C6 identity and
    delegation admission verified for the authenticated binding, or None.
    It is the only delegation source: an Authority cannot vouch for itself.
    """

    def gate(self, proposal_audit_ref: str) -> SignedPromotionGate | None: ...

    def verified_delegation(self, binding_ref: str) -> str | None: ...

    def revoked(self, control_ref: str) -> bool: ...


class PromotionCommitPolicy(Protocol):
    def authorize_commit(
        self, proposal: MemoryPromotionProposal, command: GovernedCanonicalCommitCommand,
    ) -> MemoryPolicyDecision: ...


def promotion_gate_digest(body: Mapping[str, object]) -> str:
    """Digest the entire frozen gate, omitting only its two self-references."""
    command, decision = body["command"], body["decision"]
    if not isinstance(command, Mapping) or not isinstance(decision, Mapping):
        raise ValueError("gate must bind a command and a Decision")
    return canonical_digest({
        **body,
        "command": {k: v for k, v in command.items() if k != "gate_package_digest"},
        "decision": {k: v for k, v in decision.items() if k != "gate_package_digest"},
    })


class C6MemoryPromotionConsumer:
    """C6 gates -> governed C3 command -> verified C3 receipt, never a direct write.

    Public callers supply only the recorded proposal reference and an
    authenticated binding. The command, Authority, Decision, approval policy
    and signatures come exclusively from the separately trusted C6 authority.
    Its signature binds every command field and approval to the exact proposal.
    No C3 call occurs for a missing, rejected, stale, revoked or altered gate.
    """

    def __init__(
        self, *, proposals: MemoryPromotionService, controls: PromotionControlStore,
        verifier: PromotionGateVerifier, human_gate: HumanGateCoordinator,
        policy: PromotionCommitPolicy, c3: GovernedCommitPort, clock: TrustedClock,
        audit: RetrievalAuditSink, commit_capability: str,
    ) -> None:
        # The canonical-commit capability is fixed by trusted composition; a
        # signed gate cannot authorize C3 under an unrelated capability.
        if not _reference(commit_capability):
            raise ValueError("a named canonical-commit capability is required")
        self._capability = commit_capability
        self._proposals, self._controls, self._verifier = proposals, controls, verifier
        self._human_gate, self._policy, self._c3 = human_gate, policy, c3
        self._clock, self._audit = clock, audit

    def _record(self, action: str, binding: VerifiedGovernedContextBinding | None, **fields: object) -> None:
        event: dict[str, object] = {
            "action": action, "correlation_id": binding.expected.correlation_id if binding else None,
            "governed_context_digest": binding.expected.digest() if binding else None,
            "evaluated_at": format_utc_timestamp(self._clock.now()), **fields,
        }
        try:
            self._audit.record(MappingProxyType({**event, "audit_ref": canonical_digest(event)}))
        except Exception as exc:  # noqa: BLE001 -- never claim an unaudited success
            raise _error("AUDIT_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc

    def commit(
        self, proposal_audit_ref: str, *, binding: VerifiedGovernedContextBinding | None,
    ) -> CommitReceipt:
        verified = None
        dispatched = False
        try:
            # Audit authentication refusals too, using no caller-asserted GCS.
            # Until this succeeds no proposal/control authority or C3 is read.
            verified = MemoryPromotionService._binding(binding)
            proposal = self._proposals.load(proposal_audit_ref, binding=verified)
            gate = self._controls.gate(proposal_audit_ref)
            if not isinstance(gate, SignedPromotionGate):
                raise _error("C6_GATE_MISSING")
            if (not isinstance(gate.payload, bytes) or len(gate.payload) > 1 << 20
                    or not _reference(gate.signature) or self._verifier.verify(gate.payload, gate.signature) is not True):
                raise _error("C6_GATE_UNSIGNED")
            try:
                body = parse_i_json(gate.payload)
            except ValueError as exc:
                raise _error("C6_GATE_INVALID") from exc
            if (not isinstance(body, Mapping) or canonical_bytes(body) != gate.payload or set(body) != {
                "proposal_audit_ref", "proposal_digest", "command", "authority", "decision",
                "approval_policy", "signatures", "risk_class", "capability_id",
            }):
                raise _error("C6_GATE_INVALID")
            if body["proposal_audit_ref"] != proposal_audit_ref or body["proposal_digest"] != proposal.digest:
                raise _error("C6_PROPOSAL_MISMATCH")
            raw_command = body["command"]
            if not isinstance(raw_command, Mapping):
                raise _error("C6_GATE_INVALID")
            try:
                command = GovernedCanonicalCommitCommand.from_mapping(raw_command)
                digest = promotion_gate_digest(body)
            except ValueError as exc:
                raise _error("C6_GATE_INVALID") from exc
            if command.gate_package_digest != digest:
                raise _error("GATE_PACKAGE_MISMATCH")
            if (command.aggregate_type != proposal.target_aggregate_type
                    or command.aggregate_ref != proposal.target_aggregate_ref
                    or command.governed_context != verified.expected
                    or command.governed_context_digest != proposal.governed_context_digest
                    or command.branch != "main"
                    or not set(proposal.evidence_refs) <= set(command.evidence_refs)
                    or not any(b.source_ref == proposal.source_version_ref
                               and b.evidence_ref in proposal.evidence_refs for b in command.claim_source_bindings)):
                raise _error("C6_COMMAND_BINDING_MISMATCH")
            authority, approval_policy, signatures = self._controls_from_body(body, command, proposal, verified)
            # Audit intent before dispatch; an unavailable audit cannot cause C3
            # to advance. Revalidation below covers changes during the audit I/O.
            self._record("commitMemoryPromotion.intent", verified,
                         proposal_audit_ref=proposal_audit_ref, command_digest=command.command_digest,
                         causation_id=proposal.operation_id, gate_package_digest=digest)
            self._require_live(body, command, proposal, verified, authority, approval_policy, signatures)
            fresh = self._proposals.load(proposal_audit_ref, binding=verified)
            if fresh != proposal:
                raise _error("CANDIDATE_CHANGED")
            # The source load itself may perform policy I/O. Controls are checked
            # again at boundary time. External stop-to-commit atomicity remains
            # an explicit residual of the current C3 port (FGM-17).
            self._require_live(body, command, proposal, verified, authority, approval_policy, signatures)
            if self._clock.now() >= proposal.deadline:
                raise _error("DEADLINE_EXCEEDED")
            dispatched = True
            receipt = self._c3.commit(command)
            if not isinstance(receipt, CommitReceipt):
                raise _error("C3_RECEIPT_INVALID")
            receipt.verify(command)
            self._record("commitMemoryPromotion.completed", verified,
                         proposal_audit_ref=proposal_audit_ref, command_digest=command.command_digest,
                         commit_id=receipt.commit_id, causation_id=proposal.operation_id)
            return receipt
        except Exception as exc:  # noqa: BLE001 -- control/store failures never become success
            detail = "COMMIT_OUTCOME_UNKNOWN" if dispatched else "C6_CONTROL_UNAVAILABLE"
            error = exc if isinstance(exc, MemoryAdmissionError) else _error(detail, "CONTROL_PLANE_UNAVAILABLE")
            self._record("commitMemoryPromotion.indeterminate" if dispatched else "commitMemoryPromotion.denied",
                         verified, proposal_audit_ref=proposal_audit_ref, reason_code=error.reason_code,
                         detail_code=error.detail_code)
            raise error from exc

    def _controls_from_body(
        self, body: Mapping[str, object], command: GovernedCanonicalCommitCommand,
        proposal: MemoryPromotionProposal, binding: VerifiedGovernedContextBinding,
    ) -> tuple[Authority, ApprovalPolicy, tuple[GateSignature, ...]]:
        raw_authority, decision = body["authority"], body["decision"]
        raw_policy, raw_sigs = body["approval_policy"], body["signatures"]
        if (not isinstance(raw_authority, Mapping)
                or set(raw_authority) != {f.name for f in fields(Authority)}
                or not isinstance(decision, Mapping) or set(decision) != {
                    "decision_ref", "action_id", "accepted", "decided_at", "valid_until", "gate_package_digest",
                } or not isinstance(raw_policy, Mapping) or set(raw_policy) != {"required_roles", "minimum_signatories", "ttl_seconds"}
                or not isinstance(raw_sigs, list)):
            raise _error("C6_GATE_INVALID")
        if not raw_sigs:
            raise _error("C6_APPROVAL_INVALID")
        if (decision["decision_ref"] != command.decision_ref
                or decision["action_id"] != command.action_instance_id
                or decision["gate_package_digest"] != command.gate_package_digest
                or decision["accepted"] is not True):
            raise _error("C6_DECISION_REJECTED")
        authority_values = dict(raw_authority)
        try:
            for name in ("not_before", "expires_at"):
                authority_values[name] = parse_utc_timestamp(str(authority_values[name]))
            authority = Authority(**authority_values)
            parse_utc_timestamp(str(decision["decided_at"]))
            parse_utc_timestamp(str(decision["valid_until"]))
        except (TypeError, ValueError) as exc:  # TimestampError is a ValueError
            raise _error("C6_GATE_INVALID") from exc
        if authority.authority_id != command.authority_ref:
            raise _error("C6_AUTHORITY_MISMATCH")
        risk = body["risk_class"]
        if isinstance(risk, bool) or not isinstance(risk, int) or risk not in {int(c) for c in RiskClass}:
            raise _error("C6_GATE_INVALID")
        if not _reference(body["capability_id"]):
            raise _error("C6_GATE_INVALID")
        if body["capability_id"] != self._capability:
            raise _error("C6_CAPABILITY_MISMATCH")
        required_roles = raw_policy["required_roles"]
        count, ttl = raw_policy["minimum_signatories"], raw_policy["ttl_seconds"]
        if (not isinstance(required_roles, list) or not required_roles
                or not all(_reference(r) for r in required_roles) or len(set(required_roles)) != len(required_roles)
                or isinstance(count, bool) or not isinstance(count, int) or count < 2
                or isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= 86400):
            raise _error("C6_APPROVAL_INVALID")
        policy = ApprovalPolicy(frozenset(required_roles), count, timedelta(seconds=ttl))
        signatures = []
        for raw in raw_sigs:
            if not isinstance(raw, Mapping) or set(raw) != {f.name for f in fields(GateSignature)}:
                raise _error("C6_APPROVAL_INVALID")
            entry = dict(raw)
            try:
                entry["signed_at"] = parse_utc_timestamp(str(entry["signed_at"]))
                signatures.append(GateSignature(**entry))
            except (TypeError, ValueError) as exc:
                raise _error("C6_APPROVAL_INVALID") from exc
        return authority, policy, tuple(signatures)

    def _require_live(
        self, body: Mapping[str, object], command: GovernedCanonicalCommitCommand,
        proposal: MemoryPromotionProposal, binding: VerifiedGovernedContextBinding,
        authority: Authority, approval_policy: ApprovalPolicy, signatures: tuple[GateSignature, ...],
    ) -> None:
        decision = body["decision"]
        assert isinstance(decision, Mapping)
        now = self._clock.now()
        start, end = parse_utc_timestamp(str(decision["decided_at"])), parse_utc_timestamp(str(decision["valid_until"]))
        if not start <= now < end or self._controls.revoked(command.decision_ref) is not False:
            raise _error("C6_DECISION_EXPIRED_OR_REVOKED")
        try:
            self._authority_and_approval(body, command, binding, authority, approval_policy, signatures, now)
        except (GovernanceFault, HumanGateError) as exc:
            # A refused control is a denial, never "control plane unavailable".
            raise _error(exc.reason_code if _CODE.fullmatch(exc.reason_code) else "C6_CONTROL_DENIED") from exc
        result = self._policy.authorize_commit(proposal, command)
        if (not isinstance(result, MemoryPolicyDecision) or result.permitted is not True
                or not _reference(result.decision_ref)):
            raise _error("C6_POLICY_DENIED")
        if result.policy_bundle_digest != binding.expected.policy_bundle_digest:
            raise _error("POLICY_BUNDLE_MISMATCH", "STALE_POLICY")
        # The final control-plane I/O cannot make expired controls usable.
        final_now = self._clock.now()
        if (final_now >= end or final_now >= authority.expires_at
                or self._controls.revoked(authority.authority_id) is not False
                or self._controls.revoked(authority.delegation_ref) is not False
                or self._controls.revoked(command.decision_ref) is not False
                or self._controls.verified_delegation(binding.binding_ref) != authority.delegation_ref):
            raise _error("C6_CONTROL_EXPIRED_OR_REVOKED")
        try:
            self._human_gate.validate(
                action_id=command.action_instance_id, proposer_id=binding.expected.effective_principal_id,
                policy=approval_policy, signatures=signatures, scope=command.aggregate_ref,
            )
        except HumanGateError as exc:
            raise _error(exc.reason_code if _CODE.fullmatch(exc.reason_code) else "C6_CONTROL_DENIED") from exc

    def _authority_and_approval(
        self, body: Mapping[str, object], command: GovernedCanonicalCommitCommand,
        binding: VerifiedGovernedContextBinding, authority: Authority,
        approval_policy: ApprovalPolicy, signatures: tuple[GateSignature, ...], now: datetime,
    ) -> None:
        delegation = self._controls.verified_delegation(binding.binding_ref)
        validate_authority(
            authority, AuthorityRequest(
                capability_id=str(body["capability_id"]), resource_scope=command.aggregate_ref,
                risk_class=RiskClass(body["risk_class"]),  # type: ignore[arg-type]
                governed_context=binding.expected, at=now,
            ), signature_verified=True,
            revoked=(self._controls.revoked(authority.authority_id) is not False
                     or self._controls.revoked(authority.delegation_ref) is not False),
            # No verified delegation: an unverifiable binding, never the Authority's own claim.
            verified_binding=None if delegation is None else VerifiedAuthorityBinding(
                binding.binding_ref, delegation, binding.expected),
        )
        self._human_gate.validate(
            action_id=command.action_instance_id, proposer_id=binding.expected.effective_principal_id,
            policy=approval_policy, signatures=signatures, scope=command.aggregate_ref,
        )
