"""C6 -- the thirteen distinct immutable records of the action path (NCR-C6-006).

LLD v1.1 :171 names the records of C6: ``ActionProposal``, ``PolicyAuthorityDecision``,
``Approval``, ``ApprovalSet``, ``Decision``, ``ActionIntent``, ``GatePackage``,
``ActionCommand``, ``DeliveryAttempt``, ``ExecutionResult``, ``OutcomeAssessment``,
``ConflictScope`` and ``IndeterminateEffectAdjudication``; none is an alias of another. Each
record here is a frozen class of its own, no record class derives from another, and every
canonical form carries its ``record_type``, so two records never share a digest.

The ``GatePackage`` holds the content of LLD v1.1 :320 and ADD v1.3 :3334 and is immutable;
every consumer recomputes its digest (``verify_gate_package``) instead of trusting the digest a
caller declares: the ``ActionIntent``, the ``ActionCommand`` (which carries the same digest and
the same ``governed_context_digest``, ADD v1.3 :384), the ``DeliveryAttempt`` and the Decision
gate of ``human_gate``. The ``OutcomeAssessment`` refers to the ``ExecutionResult`` without
coinciding with it and is admitted only by new Observation/Evidence (ADD v1.3 :156, FR-076).

The signed records (``Approval``, ``ApprovalSet``, ``Decision``) carry their signature here;
their verification is the Human Gate's (``ocor_runtime.c6.human_gate``).
"""

from __future__ import annotations

import base64
import binascii
import hmac
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import datetime
from types import MappingProxyType
from typing import Any, ClassVar

from ..c1.signing import dsse_pae
from ..errors import OCORError
from ..kernel.canonical import canonical_bytes, canonical_digest, format_utc_timestamp
from ..kernel.governance import RiskClass

_DIGEST = re.compile(r"urn:sha256:[0-9a-f]{64}")
_MAX_TEXT = 1024

APPROVAL_PAYLOAD_TYPE = "application/vnd.ocor.c6.approval+json"
APPROVAL_SET_PAYLOAD_TYPE = "application/vnd.ocor.c6.approval-set+json"
ACTION_DECISION_PAYLOAD_TYPE = "application/vnd.ocor.c6.action-decision+json"

POLICY_OUTCOMES = frozenset({"PERMIT", "DENY"})
DECISION_OUTCOMES = frozenset({"ACCEPT", "REJECT"})
FENCE_OUTCOMES = frozenset({"PASSED", "INVALIDATED"})
ADAPTER_STATUSES = frozenset({"COMPLETED", "FAILED", "REJECTED"})
ASSESSMENTS = frozenset({"EFFECT_ACHIEVED", "EFFECT_NOT_ACHIEVED", "EFFECT_PARTIAL"})
ADJUDICATIONS = frozenset({"EFFECT_APPLIED", "EFFECT_NOT_APPLIED"})


class C6RecordError(OCORError, ValueError):
    """A C6 record is malformed or does not bind to the record it refers to. ``reason_code``
    is ``RECORD_INVALID`` or ``GATE_PACKAGE_DIGEST_MISMATCH``."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _invalid(message: str) -> C6RecordError:
    return C6RecordError("RECORD_INVALID", message)


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT or value != value.strip():
        raise _invalid(f"{name} must be a non-empty trimmed string of at most {_MAX_TEXT} characters")
    return value


def _digest(name: str, value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise _invalid(f"{name} must be a canonical SHA-256 URN")
    return value


def _instant(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _invalid(f"{name} must be a timezone-aware datetime")
    return value


def _count(name: str, value: object, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _invalid(f"{name} must be an integer >= {minimum}")
    return value


def _choice(name: str, value: object, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _invalid(f"{name} must be one of {sorted(allowed)}")
    return value


def _refs(name: str, value: object, *, required: bool) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise _invalid(f"{name} must be a sequence of strings")
    items = tuple(_text(name, item) for item in value)
    if len(set(items)) != len(items):
        raise _invalid(f"{name} must not repeat an item")
    if required and not items:
        raise _invalid(f"{name} must not be empty")
    return tuple(sorted(items))


def _risk(name: str, value: object) -> RiskClass:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(f"{name} must be a RiskClass")
    try:
        return RiskClass(value)
    except ValueError as error:
        raise _invalid(f"{name} must be a RiskClass") from error


def _signature(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid(f"{name} must be a base64 Ed25519 signature")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise _invalid(f"{name} must be a base64 Ed25519 signature") from error
    if len(raw) != 64:
        raise _invalid(f"{name} must be a base64 Ed25519 signature")
    return value


def _freeze(name: str, value: object) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise _invalid(f"{name} keys must be strings")
        return MappingProxyType({key: _freeze(name, child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(name, child) for child in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise _invalid(f"{name} must be a JSON object of strings, integers, booleans and null")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    return value


def _parameters(name: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{name} must be an object")
    frozen = _freeze(name, value)
    try:
        canonical_bytes(_thaw(frozen))
    except Exception as error:
        raise _invalid(f"{name} must be canonical JSON") from error
    return frozen  # type: ignore[no-any-return]


def _wire(value: Any) -> Any:
    if isinstance(value, datetime):
        return format_utc_timestamp(value)
    if isinstance(value, RiskClass):
        return value.name
    return _thaw(value)


def _window(start_name: str, start: datetime, end_name: str, end: datetime) -> None:
    if end <= start:
        raise _invalid(f"{end_name} must be after {start_name}")


class _CanonicalRecord:
    """Canonical form and digest; shared behaviour only, never a record type itself."""

    __slots__ = ()
    RECORD_TYPE: ClassVar[str]

    def to_mapping(self) -> dict[str, Any]:
        body = {item.name: _wire(getattr(self, item.name)) for item in fields(self)}  # type: ignore[arg-type]
        return {"record_type": self.RECORD_TYPE, **body}

    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


class SignedRecord(_CanonicalRecord):
    """Canonical form of a record signed with Ed25519 over its DSSE pre-authentication encoding;
    the signature itself is excluded from the signed bytes."""

    __slots__ = ()
    PAYLOAD_TYPE: ClassVar[str]
    keyid: str
    signature: str

    def unsigned_mapping(self) -> dict[str, Any]:
        body = self.to_mapping()
        body.pop("signature")
        return body

    def signed_bytes(self) -> bytes:
        return dsse_pae(self.PAYLOAD_TYPE, canonical_bytes(self.unsigned_mapping()))


def parameters_digest(parameters: Mapping[str, Any]) -> str:
    return canonical_digest(_thaw(_parameters("parameters", parameters)))


@dataclass(frozen=True, slots=True)
class ActionProposal(_CanonicalRecord):
    """A proposed action: ActionType, effect and risk class, target and typed parameters."""

    RECORD_TYPE: ClassVar[str] = "ActionProposal"

    action_instance_id: str
    proposer_id: str
    action_type_ref: str
    action_type_digest: str
    effect_class: str
    risk_class: RiskClass
    target_ref: str
    parameters: Mapping[str, Any]
    governed_context_digest: str
    expected_revision: int
    evidence_refs: tuple[str, ...]
    proposed_at: datetime

    def __post_init__(self) -> None:
        for name in ("action_instance_id", "proposer_id", "action_type_ref", "effect_class", "target_ref"):
            _text(name, getattr(self, name))
        _digest("action_type_digest", self.action_type_digest)
        _digest("governed_context_digest", self.governed_context_digest)
        object.__setattr__(self, "risk_class", _risk("risk_class", self.risk_class))
        object.__setattr__(self, "parameters", _parameters("parameters", self.parameters))
        _count("expected_revision", self.expected_revision, minimum=0)
        object.__setattr__(self, "evidence_refs", _refs("evidence_refs", self.evidence_refs, required=True))
        _instant("proposed_at", self.proposed_at)

    @property
    def parameters_digest(self) -> str:
        return canonical_digest(_thaw(self.parameters))

    @property
    def action_id(self) -> str:
        """The action instance, under the name the engine's outcome and outbox events use."""

        return self.action_instance_id

    @property
    def aggregate_id(self) -> str:
        """The canonical aggregate a canonical action commits to: its target."""

        return self.target_ref


@dataclass(frozen=True, slots=True)
class PolicyAuthorityDecision(_CanonicalRecord):
    """The policy and authority evaluation of one proposal (G-CONTRACT, G-AUTHORITY)."""

    RECORD_TYPE: ClassVar[str] = "PolicyAuthorityDecision"

    action_instance_id: str
    proposal_digest: str
    outcome: str
    reason_code: str
    risk_class: RiskClass
    policy_bundle_digest: str
    authority_ref: str
    evaluated_at: datetime

    def __post_init__(self) -> None:
        _text("action_instance_id", self.action_instance_id)
        _digest("proposal_digest", self.proposal_digest)
        _choice("outcome", self.outcome, POLICY_OUTCOMES)
        _text("reason_code", self.reason_code)
        object.__setattr__(self, "risk_class", _risk("risk_class", self.risk_class))
        _digest("policy_bundle_digest", self.policy_bundle_digest)
        _text("authority_ref", self.authority_ref)
        _instant("evaluated_at", self.evaluated_at)


@dataclass(frozen=True, slots=True)
class Approval(SignedRecord):
    """One human approver's signed Approval, bound to the proposal digest, the revision, the
    ontology release and its own expiry (ADD v1.3 :2849)."""

    RECORD_TYPE: ClassVar[str] = "Approval"
    PAYLOAD_TYPE: ClassVar[str] = APPROVAL_PAYLOAD_TYPE

    approval_id: str
    action_instance_id: str
    proposal_digest: str
    revision: int
    release_digest: str
    approver_id: str
    role: str
    keyid: str
    signed_at: datetime
    expires_at: datetime
    signature: str

    def __post_init__(self) -> None:
        for name in ("approval_id", "action_instance_id", "approver_id", "role", "keyid"):
            _text(name, getattr(self, name))
        _digest("proposal_digest", self.proposal_digest)
        _count("revision", self.revision, minimum=0)
        _digest("release_digest", self.release_digest)
        _window("signed_at", _instant("signed_at", self.signed_at), "expires_at", _instant("expires_at", self.expires_at))
        _signature("signature", self.signature)


@dataclass(frozen=True, slots=True)
class ApprovalSet(SignedRecord):
    """The quorum of Approvals the Human Gate admitted for one proposal, signed by the gate.
    For ``R3_HIGH_IMPACT`` it expires ten minutes after the second signature (ADD v1.3 :3334)."""

    RECORD_TYPE: ClassVar[str] = "ApprovalSet"
    PAYLOAD_TYPE: ClassVar[str] = APPROVAL_SET_PAYLOAD_TYPE

    approval_set_id: str
    action_instance_id: str
    proposal_digest: str
    risk_class: RiskClass
    approval_digests: tuple[str, ...]
    approver_ids: tuple[str, ...]
    completed_at: datetime
    expires_at: datetime
    keyid: str
    signature: str

    def __post_init__(self) -> None:
        for name in ("approval_set_id", "action_instance_id", "keyid"):
            _text(name, getattr(self, name))
        _digest("proposal_digest", self.proposal_digest)
        object.__setattr__(self, "risk_class", _risk("risk_class", self.risk_class))
        digests = _refs("approval_digests", self.approval_digests, required=True)
        for item in digests:
            _digest("approval_digests", item)
        object.__setattr__(self, "approval_digests", digests)
        object.__setattr__(self, "approver_ids", _refs("approver_ids", self.approver_ids, required=True))
        _window(
            "completed_at", _instant("completed_at", self.completed_at), "expires_at", _instant("expires_at", self.expires_at)
        )
        _signature("signature", self.signature)


@dataclass(frozen=True, slots=True)
class Decision(SignedRecord):
    """The Authority's signed Decision, bounded to effect, target, parameters and validity
    window (ADD v1.3 :2850) and bound to the frozen GatePackage."""

    RECORD_TYPE: ClassVar[str] = "Decision"
    PAYLOAD_TYPE: ClassVar[str] = ACTION_DECISION_PAYLOAD_TYPE

    decision_id: str
    action_instance_id: str
    gate_package_digest: str
    outcome: str
    rationale: str
    effect_class: str
    target_ref: str
    parameters_digest: str
    valid_from: datetime
    valid_until: datetime
    authority_id: str
    keyid: str
    decided_at: datetime
    signature: str

    def __post_init__(self) -> None:
        for name in ("decision_id", "action_instance_id", "rationale", "effect_class", "target_ref", "authority_id", "keyid"):
            _text(name, getattr(self, name))
        _digest("gate_package_digest", self.gate_package_digest)
        _choice("outcome", self.outcome, DECISION_OUTCOMES)
        _digest("parameters_digest", self.parameters_digest)
        _window("valid_from", _instant("valid_from", self.valid_from), "valid_until", _instant("valid_until", self.valid_until))
        _instant("decided_at", self.decided_at)
        _signature("signature", self.signature)


@dataclass(frozen=True, slots=True)
class ConflictScope(_CanonicalRecord):
    """The targets and effect class an unresolved effect of the action may conflict on."""

    RECORD_TYPE: ClassVar[str] = "ConflictScope"

    scope_id: str
    action_instance_id: str
    target_refs: tuple[str, ...]
    effect_class: str
    opened_at: datetime

    def __post_init__(self) -> None:
        for name in ("scope_id", "action_instance_id", "effect_class"):
            _text(name, getattr(self, name))
        object.__setattr__(self, "target_refs", _refs("target_refs", self.target_refs, required=True))
        _instant("opened_at", self.opened_at)


@dataclass(frozen=True, slots=True)
class GatePackage(_CanonicalRecord):
    """The frozen package of LLD v1.1 :320 and ADD v1.3 :3334. Immutable; every consumer
    recomputes its digest with ``verify_gate_package``."""

    RECORD_TYPE: ClassVar[str] = "GatePackage"

    action_instance_id: str
    proposal_digest: str
    expected_revision: int
    canonical_commit_ref: str
    governed_context_digest: str
    policy_bundle_digest: str
    ontology_release_digest: str
    authority_ref: str
    approval_set_digest: str
    adapter_binding_digest: str
    projection_watermark: str
    stop_epoch: int
    valid_from: datetime
    valid_until: datetime
    conflict_scope_digest: str
    risk_class: RiskClass
    evidence_refs: tuple[str, ...]
    alternative_refs: tuple[str, ...]
    dissent_refs: tuple[str, ...]
    expected_effects: tuple[str, ...]
    compensation_ref: str
    artifact_digest: str
    frozen_at: datetime

    def __post_init__(self) -> None:
        for name in ("action_instance_id", "canonical_commit_ref", "authority_ref", "projection_watermark", "compensation_ref"):
            _text(name, getattr(self, name))
        for name in (
            "proposal_digest",
            "governed_context_digest",
            "policy_bundle_digest",
            "ontology_release_digest",
            "approval_set_digest",
            "adapter_binding_digest",
            "conflict_scope_digest",
            "artifact_digest",
        ):
            _digest(name, getattr(self, name))
        _count("expected_revision", self.expected_revision, minimum=0)
        _count("stop_epoch", self.stop_epoch, minimum=0)
        _window("valid_from", _instant("valid_from", self.valid_from), "valid_until", _instant("valid_until", self.valid_until))
        object.__setattr__(self, "risk_class", _risk("risk_class", self.risk_class))
        object.__setattr__(self, "evidence_refs", _refs("evidence_refs", self.evidence_refs, required=True))
        object.__setattr__(self, "alternative_refs", _refs("alternative_refs", self.alternative_refs, required=False))
        object.__setattr__(self, "dissent_refs", _refs("dissent_refs", self.dissent_refs, required=False))
        object.__setattr__(self, "expected_effects", _refs("expected_effects", self.expected_effects, required=True))
        _instant("frozen_at", self.frozen_at)


def verify_gate_package(package: object, claimed_digest: object) -> str:
    """Recompute the digest of the GatePackage and compare it with the claimed one."""

    if not isinstance(package, GatePackage):
        raise C6RecordError("GATE_PACKAGE_DIGEST_MISMATCH", "a GatePackage is required")
    claimed = _digest("gate_package_digest", claimed_digest)
    recomputed = package.digest()
    if not hmac.compare_digest(recomputed, claimed):
        raise C6RecordError("GATE_PACKAGE_DIGEST_MISMATCH", "the recomputed GatePackage digest differs")
    return recomputed


@dataclass(frozen=True, slots=True)
class ActionIntent(_CanonicalRecord):
    """The intent C6 forms from an accepted Decision on a verified GatePackage."""

    RECORD_TYPE: ClassVar[str] = "ActionIntent"

    intent_id: str
    action_instance_id: str
    decision_digest: str
    gate_package_digest: str
    effect_class: str
    target_ref: str
    parameters_digest: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("intent_id", "action_instance_id", "effect_class", "target_ref"):
            _text(name, getattr(self, name))
        for name in ("decision_digest", "gate_package_digest", "parameters_digest"):
            _digest(name, getattr(self, name))
        _instant("created_at", self.created_at)

    @classmethod
    def from_decision(
        cls, *, intent_id: str, decision: Decision, package: GatePackage, package_digest: str, created_at: datetime
    ) -> ActionIntent:
        digest = verify_gate_package(package, package_digest)
        if not isinstance(decision, Decision) or decision.outcome != "ACCEPT":
            raise _invalid("an ActionIntent requires an accepted Decision")
        if decision.gate_package_digest != digest or decision.action_instance_id != package.action_instance_id:
            raise C6RecordError("GATE_PACKAGE_DIGEST_MISMATCH", "the Decision is bound to another GatePackage")
        return cls(
            intent_id=intent_id,
            action_instance_id=package.action_instance_id,
            decision_digest=decision.digest(),
            gate_package_digest=digest,
            effect_class=decision.effect_class,
            target_ref=decision.target_ref,
            parameters_digest=decision.parameters_digest,
            created_at=created_at,
        )


@dataclass(frozen=True, slots=True)
class ActionCommand(_CanonicalRecord):
    """The command of the action instance; it carries the GatePackage digest and the same
    ``governed_context_digest`` (ADD v1.3 :384)."""

    RECORD_TYPE: ClassVar[str] = "ActionCommand"

    command_id: str
    action_instance_id: str
    intent_digest: str
    gate_package_digest: str
    governed_context_digest: str
    effect_class: str
    target_ref: str
    parameters: Mapping[str, Any]
    idempotency_key: str
    deadline: datetime

    def __post_init__(self) -> None:
        for name in ("command_id", "action_instance_id", "effect_class", "target_ref", "idempotency_key"):
            _text(name, getattr(self, name))
        for name in ("intent_digest", "gate_package_digest", "governed_context_digest"):
            _digest(name, getattr(self, name))
        object.__setattr__(self, "parameters", _parameters("parameters", self.parameters))
        _instant("deadline", self.deadline)

    @classmethod
    def issue(
        cls,
        *,
        command_id: str,
        intent: ActionIntent,
        package: GatePackage,
        package_digest: str,
        parameters: Mapping[str, Any],
        idempotency_key: str,
        deadline: datetime,
    ) -> ActionCommand:
        digest = verify_gate_package(package, package_digest)
        if not isinstance(intent, ActionIntent) or intent.gate_package_digest != digest:
            raise C6RecordError("GATE_PACKAGE_DIGEST_MISMATCH", "the ActionIntent is bound to another GatePackage")
        if parameters_digest(parameters) != intent.parameters_digest:
            raise _invalid("the command parameters differ from the decided parameters")
        if _instant("deadline", deadline) > package.valid_until:
            raise _invalid("the command deadline exceeds the GatePackage validity window")
        return cls(
            command_id=command_id,
            action_instance_id=package.action_instance_id,
            intent_digest=intent.digest(),
            gate_package_digest=digest,
            governed_context_digest=package.governed_context_digest,
            effect_class=intent.effect_class,
            target_ref=intent.target_ref,
            parameters=parameters,
            idempotency_key=idempotency_key,
            deadline=deadline,
        )


@dataclass(frozen=True, slots=True)
class DeliveryAttempt(_CanonicalRecord):
    """One emission attempt of a command, with the EMISSION-FENCE outcome."""

    RECORD_TYPE: ClassVar[str] = "DeliveryAttempt"

    attempt_id: str
    command_digest: str
    gate_package_digest: str
    emission_attempt: int
    lease_ref: str
    fence_outcome: str
    attempted_at: datetime

    def __post_init__(self) -> None:
        for name in ("attempt_id", "lease_ref"):
            _text(name, getattr(self, name))
        _digest("command_digest", self.command_digest)
        _digest("gate_package_digest", self.gate_package_digest)
        _count("emission_attempt", self.emission_attempt, minimum=1)
        _choice("fence_outcome", self.fence_outcome, FENCE_OUTCOMES)
        _instant("attempted_at", self.attempted_at)

    @classmethod
    def for_command(
        cls,
        *,
        attempt_id: str,
        command: ActionCommand,
        package: GatePackage,
        package_digest: str,
        emission_attempt: int,
        lease_ref: str,
        fence_outcome: str,
        attempted_at: datetime,
    ) -> DeliveryAttempt:
        digest = verify_gate_package(package, package_digest)
        if not isinstance(command, ActionCommand) or command.gate_package_digest != digest:
            raise C6RecordError("GATE_PACKAGE_DIGEST_MISMATCH", "the command carries another GatePackage digest")
        return cls(
            attempt_id=attempt_id,
            command_digest=command.digest(),
            gate_package_digest=digest,
            emission_attempt=emission_attempt,
            lease_ref=lease_ref,
            fence_outcome=fence_outcome,
            attempted_at=attempted_at,
        )


@dataclass(frozen=True, slots=True)
class ExecutionResult(_CanonicalRecord):
    """What the adapter reported for one delivered attempt; not an acknowledgement and not
    an outcome (FR-076)."""

    RECORD_TYPE: ClassVar[str] = "ExecutionResult"

    result_id: str
    command_digest: str
    attempt_digest: str
    adapter_status: str
    adapter_result_digest: str
    evidence_refs: tuple[str, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        _text("result_id", self.result_id)
        for name in ("command_digest", "attempt_digest", "adapter_result_digest"):
            _digest(name, getattr(self, name))
        _choice("adapter_status", self.adapter_status, ADAPTER_STATUSES)
        object.__setattr__(self, "evidence_refs", _refs("evidence_refs", self.evidence_refs, required=True))
        _instant("observed_at", self.observed_at)

    @classmethod
    def for_attempt(
        cls,
        *,
        result_id: str,
        attempt: DeliveryAttempt,
        adapter_status: str,
        adapter_result_digest: str,
        evidence_refs: Sequence[str],
        observed_at: datetime,
    ) -> ExecutionResult:
        if not isinstance(attempt, DeliveryAttempt) or attempt.fence_outcome != "PASSED":
            raise _invalid("an ExecutionResult requires a DeliveryAttempt that passed the EMISSION-FENCE")
        if _instant("observed_at", observed_at) < attempt.attempted_at:
            raise _invalid("an ExecutionResult cannot precede its DeliveryAttempt")
        return cls(
            result_id=result_id,
            command_digest=attempt.command_digest,
            attempt_digest=attempt.digest(),
            adapter_status=adapter_status,
            adapter_result_digest=adapter_result_digest,
            evidence_refs=tuple(evidence_refs),
            observed_at=observed_at,
        )


@dataclass(frozen=True, slots=True)
class OutcomeAssessment(_CanonicalRecord):
    """The governed assessment of the effect, admitted by new Observation/Evidence; it refers
    to the ExecutionResult without coinciding with it (ADD v1.3 :156)."""

    RECORD_TYPE: ClassVar[str] = "OutcomeAssessment"

    assessment_id: str
    execution_result_digest: str
    observation_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    assessment: str
    assessed_at: datetime

    def __post_init__(self) -> None:
        _text("assessment_id", self.assessment_id)
        _digest("execution_result_digest", self.execution_result_digest)
        object.__setattr__(self, "observation_refs", _refs("observation_refs", self.observation_refs, required=True))
        object.__setattr__(self, "evidence_refs", _refs("evidence_refs", self.evidence_refs, required=True))
        _choice("assessment", self.assessment, ASSESSMENTS)
        _instant("assessed_at", self.assessed_at)

    @classmethod
    def for_result(
        cls,
        *,
        assessment_id: str,
        result: ExecutionResult,
        observation_refs: Sequence[str],
        evidence_refs: Sequence[str],
        assessment: str,
        assessed_at: datetime,
    ) -> OutcomeAssessment:
        if not isinstance(result, ExecutionResult):
            raise _invalid("an OutcomeAssessment refers to an ExecutionResult")
        new_evidence = _refs("evidence_refs", evidence_refs, required=True)
        if set(new_evidence) & set(result.evidence_refs):
            raise _invalid("an OutcomeAssessment is admitted only by new Evidence, not by the ExecutionResult's")
        if _instant("assessed_at", assessed_at) <= result.observed_at:
            raise _invalid("an OutcomeAssessment follows the ExecutionResult")
        return cls(
            assessment_id=assessment_id,
            execution_result_digest=result.digest(),
            observation_refs=tuple(observation_refs),
            evidence_refs=new_evidence,
            assessment=assessment,
            assessed_at=assessed_at,
        )


@dataclass(frozen=True, slots=True)
class IndeterminateEffectAdjudication(_CanonicalRecord):
    """The evidence-based adjudication of an effect left indeterminate in a ConflictScope."""

    RECORD_TYPE: ClassVar[str] = "IndeterminateEffectAdjudication"

    adjudication_id: str
    conflict_scope_digest: str
    command_digest: str
    outcome: str
    evidence_refs: tuple[str, ...]
    adjudicator_id: str
    adjudicated_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for name in ("adjudication_id", "adjudicator_id"):
            _text(name, getattr(self, name))
        _digest("conflict_scope_digest", self.conflict_scope_digest)
        _digest("command_digest", self.command_digest)
        _choice("outcome", self.outcome, ADJUDICATIONS)
        object.__setattr__(self, "evidence_refs", _refs("evidence_refs", self.evidence_refs, required=True))
        _window(
            "adjudicated_at",
            _instant("adjudicated_at", self.adjudicated_at),
            "valid_until",
            _instant("valid_until", self.valid_until),
        )


C6_RECORD_TYPES: tuple[type[_CanonicalRecord], ...] = (
    ActionProposal,
    PolicyAuthorityDecision,
    Approval,
    ApprovalSet,
    Decision,
    ActionIntent,
    GatePackage,
    ActionCommand,
    DeliveryAttempt,
    ExecutionResult,
    OutcomeAssessment,
    ConflictScope,
    IndeterminateEffectAdjudication,
)


# Field validators and the signature placeholder shared with the other signed C6 records
# (``ocor_runtime.c6.contract.ActionType``).
PLACEHOLDER_SIGNATURE = base64.b64encode(bytes(64)).decode("ascii")
text_field = _text
digest_field = _digest
count_field = _count
choice_field = _choice
risk_field = _risk
signature_field = _signature
