"""C6 -- governed-action engine.

The representative path a single action takes through the normative 44-transition C6 workflow
of LLD v1.1 section 3 (OCOR-DEV-0030, composed with the current C6 gates by OCOR-DEV-REM-0053):
a proposed action crosses, in strict order, ``G-CONTRACT`` (the signed, active ActionType of
the release, whose risk class is the action's, ADD v1.3 :2847, NCR-C6-002), ``G-AUTHORITY``
(``ACT-T04``), the Human Gate disposition of ``CONTROL_CHECK`` (``ACT-T06``/``ACT-T07``: a
canonical target never takes ``NOT_REQUIRED``, LLD v1.1 :268), ``G-APPROVAL`` (the ApprovalSet
of signed Approvals the Human Gate assembled, ADD v1.3 :2849, NCR-C6-001/008), ``G-DECISION``
(the Authority's signed Decision on the frozen GatePackage, ADD v1.3 :2850, ``ACT-T10b``), the
EMISSION-FENCE (``G-FRESHNESS`` and ``G-DISPATCH``, with the consumption of the signed
CapabilityLease of the emission attempt and the DeliveryAttempt in one local transaction, ADD
v1.3 :2851-2854 and :3194-3212, NCR-C6-004/005) immediately before the send to C3 (``ACT-T29``),
the canonical commit through C3 (``ACT-T30``) and the C7 relay of the committed outbox event as
the simulated effect. Any gate failure denies the action before the durable canonical commit or
the simulated effect ever happen.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Protocol, cast, runtime_checkable

from ..c1.signing import Ed25519SigningKey
from ..c3.admission import (
    AUTHORITY_PAYLOAD_TYPE,
    C6_PRODUCER,
    DECISION_PAYLOAD_TYPE,
    GATE_PACKAGE_PAYLOAD_TYPE,
    MutationFencePort,
    SignedGovernanceRecord,
    gate_package_payload,
    issue_governed_command,
    sign_governance_record,
)
from ..c3.ports import CommitReceipt, GovernedCanonicalCommitCommand
from ..c7_emission import EmissionFence, EmissionReceipt, EventSink
from ..errors import EmissionBlocked, OCORError
from ..kernel.canonical import canonical_digest, format_utc_timestamp
from ..kernel.governance import TrustedClock
from ..kernel.governed_context import GovernedContext
from . import records as c6_records
from .contract import ActionType, ContractGate, ContractGateError
from .dispatch import (
    CurrentValues,
    DelegationPort,
    DispatchError,
    GovernedEmissionFence,
    SignedCapabilityLease,
)
from .human_gate import Approval as Approval
from .human_gate import ApprovalGate, ApprovalGateError, DecisionGate, gate_disposition


class GovernedActionError(OCORError):
    """A governed action was denied at one of its gates. ``reason_code`` identifies the gate
    (CONTRACT_INVALID, AUTHORITY_DENIED, NO_MUTATION_ADMITTED, APPROVAL_MISSING,
    DECISION_MISSING, DECISION_REJECTED, EVIDENCE_MISSING or INVALIDATED, the outcome of the
    EMISSION-FENCE); ``cause_code`` is the reason code of the gate that refused, when it has one."""

    def __init__(self, reason_code: str, message: str, *, cause_code: str | None = None) -> None:
        self.reason_code = reason_code
        self.cause_code = cause_code
        super().__init__(f"{reason_code}: {message}")


def _require_aware(instant: datetime, *, field: str) -> datetime:
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return instant


# The proposal of the action path is the C6 record (NCR-C6-002): ActionType, effect and risk
# class, target and typed parameters; it declares no risk of its own choosing.
ActionProposal = c6_records.ActionProposal

# The adapter binding of the send to C3 (the governed canonical commit), as the GatePackage freezes
# it and G-FRESHNESS compares it.
C3_ADAPTER_BINDING_DIGEST = "urn:sha256:" + hashlib.sha256(b"c3-governed-commit").hexdigest()


def canonical_commit_ref(aggregate_ref: str, revision: int) -> str:
    """The C3 canonical commit that produced ``revision`` of an aggregate (G-FRESHNESS)."""

    return f"urn:ocor:commit:{aggregate_ref}:{revision}"


def projection_watermark(revision: int) -> str:
    """The projection watermark of a canonical revision (G-FRESHNESS)."""

    return f"urn:ocor:watermark:{revision}"


@dataclass(frozen=True, slots=True)
class Decision:
    """The unsigned Decision disposition of OCOR-DEV-0030 (``ACT-T10a``/``ACT-T10b``). It is not
    signed by an Authority nor bound to a GatePackage, so ``G-DECISION`` does not admit it
    (ADD v1.3 :2850, NCR-C6-001): the engine admits only an ``AuthorizedDecision``."""

    action_id: str
    decided_by: str
    accepted: bool
    rationale: str
    decided_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.decided_at, field="decided_at")
        if not self.decided_by:
            raise ValueError("a Decision requires a decider")
        if not self.rationale:
            raise ValueError("a Decision requires a rationale")


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    action_id: str
    emission_receipt: EmissionReceipt
    simulated_effect: Any
    commit_receipt: CommitReceipt
    delivery_attempt: c6_records.DeliveryAttempt


@dataclass(frozen=True, slots=True)
class AuthorizedDecision:
    """The Authority's signed Decision with the GatePackage it was taken on, as the Authority
    hands it to the engine (ADD v1.3 :3318-3331: authorized Decision, then recheck and dispatch
    only for the identical digest)."""

    decision: c6_records.Decision
    package: c6_records.GatePackage
    package_digest: str


def freeze_gate_package(
    proposal: c6_records.ActionProposal,
    approval_set: c6_records.ApprovalSet,
    *,
    action_type: ActionType,
    authority_ref: str,
    policy_bundle_digest: str,
    ontology_release_digest: str,
    stop_epoch: int,
    canonical_commit_ref: str,
    adapter_binding_digest: str,
    projection_watermark: str,
    valid_from: datetime,
    valid_until: datetime,
    conflict_scope_digest: str,
    expected_effects: Sequence[str],
    compensation_ref: str,
    artifact_digest: str,
    frozen_at: datetime,
    alternative_refs: Sequence[str] = (),
    dissent_refs: Sequence[str] = (),
) -> c6_records.GatePackage:
    """Freeze the GatePackage of LLD v1.1 :320 and ADD v1.3 :3334 for a proposal and the
    ApprovalSet admitted for it. The risk class frozen is the signed ActionType's (NCR-C6-002)."""

    if not isinstance(proposal, c6_records.ActionProposal) or not isinstance(approval_set, c6_records.ApprovalSet):
        raise c6_records.C6RecordError("RECORD_INVALID", "a GatePackage freezes an ActionProposal and its ApprovalSet")
    if not isinstance(action_type, ActionType) or action_type.digest() != proposal.action_type_digest:
        raise c6_records.C6RecordError("RECORD_INVALID", "the proposal pins another ActionType")
    if (
        approval_set.action_instance_id != proposal.action_instance_id
        or approval_set.proposal_digest != proposal.digest()
    ):
        raise c6_records.C6RecordError("RECORD_INVALID", "the ApprovalSet is bound to another proposal")
    return c6_records.GatePackage(
        action_instance_id=proposal.action_instance_id,
        proposal_digest=proposal.digest(),
        expected_revision=proposal.expected_revision,
        canonical_commit_ref=canonical_commit_ref,
        governed_context_digest=proposal.governed_context_digest,
        policy_bundle_digest=policy_bundle_digest,
        ontology_release_digest=ontology_release_digest,
        authority_ref=authority_ref,
        approval_set_digest=approval_set.digest(),
        adapter_binding_digest=adapter_binding_digest,
        projection_watermark=projection_watermark,
        stop_epoch=stop_epoch,
        valid_from=valid_from,
        valid_until=valid_until,
        conflict_scope_digest=conflict_scope_digest,
        risk_class=action_type.risk_class,
        evidence_refs=proposal.evidence_refs,
        alternative_refs=tuple(alternative_refs),
        dissent_refs=tuple(dissent_refs),
        expected_effects=tuple(expected_effects),
        compensation_ref=compensation_ref,
        artifact_digest=artifact_digest,
        frozen_at=frozen_at,
    )


@runtime_checkable
class GovernanceRecordSink(Protocol):
    """Write side of the C6 governance record store that C3 admission reads."""

    def publish(self, record: SignedGovernanceRecord) -> None: ...


@dataclass(slots=True)
class GovernedCommandIssuer:
    """C6 issuance of a canonical commit decided by a composed C6 consumer (memory
    promotion, ``OCOR-DEV-0058``): freezes the GatePackage of the decided command,
    signs the Decision ``ACCEPT`` and the Authority binding with the C6 key of the
    trusted composition and publishes them where C3 admission reads them (ADD v1.3
    :342). One command per action instance: a retry gets the same command, so C3
    replays it (FR-008); a different command for the same action is refused."""

    signing_key: Ed25519SigningKey
    keyid: str
    records: GovernanceRecordSink
    fence: MutationFencePort
    clock: TrustedClock
    _issued: dict[str, GovernedCanonicalCommitCommand] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.signing_key, Ed25519SigningKey):
            raise TypeError("signing_key must be the C6 Ed25519 signing key")
        if not isinstance(self.records, GovernanceRecordSink):
            raise TypeError("records must implement GovernanceRecordSink")
        if not isinstance(self.fence, MutationFencePort):
            raise TypeError("fence must implement MutationFencePort")
        if not callable(getattr(self.clock, "now", None)):
            raise TypeError("clock must implement TrustedClock")
        if not isinstance(self.keyid, str) or not self.keyid:
            raise ValueError("keyid is required")

    def issue(
        self,
        fields: Mapping[str, Any],
        *,
        decision_expires_at: datetime,
        authority_not_before: datetime,
        authority_expires_at: datetime,
    ) -> GovernedCanonicalCommitCommand:
        values = {key: value for key, value in fields.items() if key != "gate_package_digest"}
        action = values.get("action_instance_id")
        if not isinstance(action, str) or not action:
            raise ValueError("action_instance_id is required")
        with self._lock:
            issued = self._issued.get(action)
            if issued is None:
                # The Decision expires with the decision C6 took; the Authority keeps
                # the window C6 verified.
                now = self.clock.now()
                issued = issue_governed_command(
                    values,
                    key=self.signing_key,
                    keyid=self.keyid,
                    sink=self.records,
                    fence=self.fence,
                    issued_at=now,
                    validity=_require_aware(decision_expires_at, field="decision_expires_at") - now,
                    authority_window=(
                        _require_aware(authority_not_before, field="authority_not_before"),
                        _require_aware(authority_expires_at, field="authority_expires_at"),
                    ),
                )
                self._issued[action] = issued
        requested = GovernedCanonicalCommitCommand.from_mapping(
            {**values, "gate_package_digest": issued.gate_package_digest}
        )
        if requested != issued:
            raise ValueError("another command was already issued for this action instance")
        return issued


@runtime_checkable
class CanonicalCommitTarget(Protocol):
    """The C3 ports the engine composes: ``GovernedCommitPort`` and ``RevisionPort``."""

    def commit(self, command: GovernedCanonicalCommitCommand) -> CommitReceipt: ...

    def current_revision(self, tenant_id: str, aggregate_type: str, aggregate_ref: str) -> int: ...


@dataclass(frozen=True, slots=True)
class CommittedOutboxEvent:
    """The committed C3 outbox event of the commit, as the EMISSION-FENCE reads it."""

    event_id: str
    aggregate_id: str
    aggregate_version: int
    event_type: str
    payload: Mapping[str, Any]
    payload_digest: str
    request_digest: str
    idempotency_key: str
    transaction_id: str
    occurred_at: datetime
    committed: bool = True
    emitted_at: datetime | None = None

    def verify_integrity(self) -> bool:
        return canonical_digest(dict(self.payload)) == self.payload_digest


@dataclass(frozen=True, slots=True)
class CanonicalDocument:
    """The canonical state of one aggregate as read from C3."""

    aggregate_id: str
    document: Mapping[str, Any]
    version: int


class C3CanonicalOutboxView:
    """The committed events of the engine's canonical commits, as the EMISSION-FENCE
    reads its durable outbox (``get_event``, ``outbox``, ``mark_emitted``), and the C3
    canonical state of their aggregates (``get``). The state is always read from C3; the
    view only tracks which committed events have crossed the fence. It is the composition
    of the current EMISSION-FENCE with C3 until NCR-C6-004/005 (NCP-U07)."""

    def __init__(self, reader: Any, *, tenant_id: str, aggregate_type: str) -> None:
        if not callable(getattr(reader, "read", None)):
            raise TypeError("reader must implement the C3 CanonicalReadPort")
        if not tenant_id or not aggregate_type:
            raise ValueError("tenant_id and aggregate_type are required")
        self._reader = reader
        self._tenant_id = tenant_id
        self._aggregate_type = aggregate_type
        self._events: dict[str, CommittedOutboxEvent] = {}
        self._lock = threading.RLock()

    def get(self, aggregate_id: str) -> CanonicalDocument | None:
        snapshot = self._reader.read(self._tenant_id, self._aggregate_type, aggregate_id)
        if snapshot is None:
            return None
        return CanonicalDocument(aggregate_id, snapshot.state, snapshot.revision)

    def record(self, event: CommittedOutboxEvent) -> CommittedOutboxEvent:
        with self._lock:
            existing = self._events.get(event.event_id)
            if existing is not None:
                return existing
            self._events[event.event_id] = event
            return event

    def get_event(self, event_id: str) -> CommittedOutboxEvent | None:
        with self._lock:
            return self._events.get(event_id)

    def outbox(self, *, include_emitted: bool = False) -> tuple[CommittedOutboxEvent, ...]:
        with self._lock:
            events = sorted(self._events.values(), key=lambda item: (item.aggregate_id, item.aggregate_version))
            return tuple(item for item in events if include_emitted or item.emitted_at is None)

    def mark_emitted(self, event_id: str, emitted_at: datetime) -> CommittedOutboxEvent:
        _require_aware(emitted_at, field="emitted_at")
        with self._lock:
            event = self._events.get(event_id)
            if event is None:
                raise EmissionBlocked("event is not present in the durable outbox")
            if event.emitted_at is None:
                event = replace(event, emitted_at=emitted_at)
                self._events[event_id] = event
            return event


Evidence = tuple[tuple[str, ...], tuple[Mapping[str, str], ...]]


@dataclass
class CanonicalCommitPath:
    """C6 side of the governed canonical commit: freezes the GatePackage and signs the
    governance records C3 admits the command with (ADD v1.3 :342, :2557)."""

    signing_key: Ed25519SigningKey
    keyid: str
    records: GovernanceRecordSink
    fence: MutationFencePort
    clock: TrustedClock
    aggregate_type: str
    governed_context: GovernedContext
    precondition_bindings: tuple[str, ...]
    invariant_bindings: tuple[str, ...]
    validity: timedelta = timedelta(hours=1)
    evidence: Callable[[ActionProposal], Evidence] | None = None
    _issued: dict[str, GovernedCanonicalCommitCommand] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.signing_key, Ed25519SigningKey):
            raise TypeError("signing_key must be the C6 Ed25519 signing key")
        if not isinstance(self.records, GovernanceRecordSink):
            raise TypeError("records must implement GovernanceRecordSink")
        if not isinstance(self.fence, MutationFencePort):
            raise TypeError("fence must implement MutationFencePort")
        if not isinstance(self.governed_context, GovernedContext):
            raise TypeError("governed_context must be a GovernedContext")
        if not self.keyid or not self.aggregate_type:
            raise ValueError("keyid and aggregate_type are required")
        if not isinstance(self.validity, timedelta) or self.validity <= timedelta(0):
            raise ValueError("validity must be a positive timedelta")

    def _sign(self, payload_type: str, payload: Mapping[str, Any]) -> SignedGovernanceRecord:
        record = sign_governance_record(payload_type, payload, key=self.signing_key, keyid=self.keyid)
        self.records.publish(record)
        return record

    def command(
        self,
        proposal: c6_records.ActionProposal,
        decision: c6_records.Decision,
        *,
        expected_revision: int,
        canonical_delta: Mapping[str, Any],
        evidence_refs: Sequence[str],
        claim_source_bindings: Sequence[Mapping[str, str]],
    ) -> GovernedCanonicalCommitCommand:
        with self._lock:
            issued = self._issued.get(proposal.action_instance_id)
            if issued is not None:
                return issued
            suffix = hashlib.sha256(proposal.action_instance_id.encode("utf-8")).hexdigest()
            now = self.clock.now()
            context = self.governed_context
            fields: dict[str, Any] = {
                "command_id": f"urn:ocor:command:{suffix}",
                "action_instance_id": proposal.action_instance_id,
                "aggregate_type": self.aggregate_type,
                "aggregate_ref": proposal.target_ref,
                "expected_revision": expected_revision,
                "canonical_delta": dict(canonical_delta),
                "decision_ref": f"urn:ocor:decision:{suffix}",
                "authority_ref": f"urn:ocor:authority:{suffix}",
                "evidence_refs": list(evidence_refs),
                "claim_source_bindings": [dict(item) for item in claim_source_bindings],
                "precondition_bindings": list(self.precondition_bindings),
                "invariant_bindings": list(self.invariant_bindings),
                "idempotency_key": f"c6-action-{suffix}",
                "governed_context": context.to_mapping(),
                "governed_context_digest": context.digest(),
                "branch": "main",
            }
            package = gate_package_payload(
                fields,
                ontology_release_digest=self.fence.active_release_digest(),
                stop_epoch=self.fence.current_stop_epoch(),
                frozen_at=format_utc_timestamp(now),
            )
            gate_package_digest = canonical_digest(package)
            self._sign(GATE_PACKAGE_PAYLOAD_TYPE, package)
            self._sign(
                DECISION_PAYLOAD_TYPE,
                {
                    "record_type": "Decision",
                    "producer": C6_PRODUCER,
                    "decision_ref": fields["decision_ref"],
                    "action_instance_id": proposal.action_instance_id,
                    "outcome": decision.outcome,
                    "effect_class": "CANONICAL_COMMIT",
                    "gate_package_digest": gate_package_digest,
                    "decided_at": format_utc_timestamp(decision.decided_at),
                    "expires_at": format_utc_timestamp(now + self.validity),
                },
            )
            self._sign(
                AUTHORITY_PAYLOAD_TYPE,
                {
                    "record_type": "Authority",
                    "producer": C6_PRODUCER,
                    "authority_ref": fields["authority_ref"],
                    "action_instance_id": proposal.action_instance_id,
                    "gate_package_digest": gate_package_digest,
                    "tenant_id": context.tenant_id,
                    "effective_principal_id": context.effective_principal_id,
                    "not_before": format_utc_timestamp(now),
                    "expires_at": format_utc_timestamp(now + self.validity),
                },
            )
            command = GovernedCanonicalCommitCommand.from_mapping({**fields, "gate_package_digest": gate_package_digest})
            self._issued[proposal.action_instance_id] = command
            return command


@dataclass(frozen=True, slots=True)
class _Admission:
    """The records an action instance was admitted with at G-APPROVAL and G-DECISION."""

    proposal_digest: str
    approval_set_digest: str
    decision_digest: str
    package_digest: str


class GovernedActionEngine:
    """G-CONTRACT -> G-AUTHORITY -> Human Gate disposition -> G-APPROVAL -> G-DECISION ->
    EMISSION-FENCE -> send to C3 -> C7 relay of the committed event as the simulated effect,
    evaluated strictly in that order and fail-closed at every gate. Nothing is sent to C3 and no
    simulated effect is ever applied unless every gate is satisfied and the fence passed.

    ``G-AUTHORITY`` admits the signed CapabilityLease of the emission attempt only for the
    ActionType's capability, the effective principal of the GovernedContext and its verified
    Delegation, the action instance and its validity window; the EMISSION-FENCE consumes it, once,
    in the transaction of the DeliveryAttempt (ADD v1.3 :3194-3212, LLD v1.1 :69-81).

    The Approvals and the Decision of an action instance are single use (NFR-005): they are
    claimed when the action is first admitted. A retry of the same action instance with the
    same ApprovalSet and Decision re-verifies them without a new claim; a confirmed action is
    not sent again (every send crosses the EMISSION-FENCE, ADD v1.3 :2853) and the retry returns
    its confirmed outcome; any other Decision for an admitted action is refused.
    """

    def __init__(
        self,
        *,
        contract: ContractGate,
        approvals: ApprovalGate,
        decisions: DecisionGate,
        delegations: DelegationPort,
        emission_fence: GovernedEmissionFence,
        commit_port: CanonicalCommitTarget,
        relay: EmissionFence,
        canonical_path: CanonicalCommitPath,
        emission_outbox: C3CanonicalOutboxView | None = None,
    ) -> None:
        if not isinstance(contract, ContractGate):
            raise TypeError("contract must be the G-CONTRACT ContractGate")
        if not isinstance(approvals, ApprovalGate):
            raise TypeError("approvals must be the G-APPROVAL ApprovalGate")
        if not isinstance(decisions, DecisionGate):
            raise TypeError("decisions must be the G-DECISION DecisionGate")
        if not isinstance(delegations, DelegationPort):
            raise TypeError("delegations must implement DelegationPort")
        if not isinstance(emission_fence, GovernedEmissionFence):
            raise TypeError("emission_fence must be the GovernedEmissionFence")
        if not isinstance(commit_port, CanonicalCommitTarget):
            raise TypeError("commit_port must implement the C3 GovernedCommitPort and RevisionPort")
        if not isinstance(relay, EmissionFence):
            raise TypeError("relay must be the C7 EmissionFence of the committed outbox")
        if not isinstance(canonical_path, CanonicalCommitPath):
            raise TypeError("canonical_path must be a CanonicalCommitPath")
        self._contract = contract
        self._approvals = approvals
        self._decisions = decisions
        self._delegations = delegations
        self._emission_fence = emission_fence
        self._commit_port = commit_port
        self._relay = relay
        self._path = canonical_path
        self._outbox = emission_outbox
        self._admitted: dict[str, _Admission] = {}
        self._confirmed: dict[str, ActionOutcome] = {}
        self._lock = threading.Lock()

    def _action_type(self, proposal: object) -> ActionType:
        # G-CONTRACT (ACT-T01): the signed, active ActionType gives the effect and risk class.
        try:
            action_type = self._contract.evaluate(proposal)
        except ContractGateError as error:
            raise GovernedActionError("CONTRACT_INVALID", str(error), cause_code=error.reason_code) from error
        if not action_type.canonical_target:
            raise GovernedActionError(
                "CONTRACT_INVALID",
                "the engine commits canonical state: the ActionType declares a non-canonical target",
                cause_code="TARGET_NOT_CANONICAL",
            )
        return action_type

    def _authority(
        self, proposal: c6_records.ActionProposal, action_type: ActionType, lease: object
    ) -> tuple[SignedCapabilityLease, str]:
        # G-AUTHORITY (ACT-T04): the signed lease of the capability authority, for the
        # ActionType's capability, the principal of the GovernedContext with its verified
        # Delegation and this action instance, within its window. Consumed only at the fence.
        context = self._path.governed_context
        if proposal.governed_context_digest != context.digest():
            raise GovernedActionError(
                "AUTHORITY_DENIED",
                "the proposal is bound to another GovernedContext",
                cause_code="GOVERNED_CONTEXT_MISMATCH",
            )
        try:
            verified = self._emission_fence.validator.verify(lease)
            now = _require_aware(self._emission_fence.validator.clock.now(), field="trusted now")
            delegation = self._delegations.verified_delegation(context.effective_principal_id)
        except DispatchError as error:
            raise GovernedActionError("AUTHORITY_DENIED", str(error), cause_code=error.reason_code) from error
        except Exception as error:
            raise GovernedActionError(
                "AUTHORITY_DENIED", "the authority services are unavailable", cause_code="CONTROL_PLANE_UNAVAILABLE"
            ) from error
        if not isinstance(delegation, str) or not delegation:
            raise GovernedActionError(
                "AUTHORITY_DENIED", "the principal has no verified Delegation", cause_code="LEASE_CONTEXT_MISMATCH"
            )
        if (
            verified.capability_id != action_type.capability
            or verified.effective_principal_id != context.effective_principal_id
            or verified.delegation_ref != delegation
            or verified.action_instance_id != proposal.action_instance_id
            or verified.governed_context_digest != proposal.governed_context_digest
        ):
            raise GovernedActionError(
                "AUTHORITY_DENIED",
                "the lease is not bound to the capability, principal, Delegation and action instance",
                cause_code="LEASE_CONTEXT_MISMATCH",
            )
        if not verified.issued_at <= now < verified.expires_at:
            raise GovernedActionError("AUTHORITY_DENIED", "the lease is outside its window", cause_code="LEASE_EXPIRED")
        if not isinstance(lease, SignedCapabilityLease):
            raise GovernedActionError("AUTHORITY_DENIED", "a signed CapabilityLease is required", cause_code="LEASE_INVALID")
        return lease, delegation

    def _approval_set(self, proposal: c6_records.ActionProposal, approval: object) -> c6_records.ApprovalSet:
        # G-APPROVAL (ACT-T08): the ApprovalSet of signed Approvals the Human Gate assembled.
        if approval is None:
            raise GovernedActionError("APPROVAL_MISSING", "a risk-bearing action requires its ApprovalSet")
        try:
            return self._approvals.verify_set(approval, proposal)
        except ApprovalGateError as error:
            raise GovernedActionError("APPROVAL_MISSING", str(error), cause_code=error.reason_code) from error

    def _decision(
        self,
        proposal: c6_records.ActionProposal,
        action_type: ActionType,
        approval_set: c6_records.ApprovalSet,
        decision: object,
    ) -> c6_records.Decision:
        # G-DECISION (ACT-T10b): the Authority's signed Decision on the frozen GatePackage.
        if not isinstance(decision, AuthorizedDecision):
            raise GovernedActionError("DECISION_MISSING", "a governed action requires the Authority's signed Decision")
        if decision.package.risk_class is not action_type.risk_class:
            raise GovernedActionError(
                "DECISION_MISSING",
                "the GatePackage freezes another risk class than the signed ActionType",
                cause_code="GATE_PACKAGE_RISK_MISMATCH",
            )
        admission = _Admission(
            proposal.digest(), approval_set.digest(), decision.decision.digest(), decision.package_digest
        )
        with self._lock:
            prior = self._admitted.get(proposal.action_instance_id)
        if prior is not None and prior != admission:
            raise GovernedActionError(
                "DECISION_MISSING",
                "the action instance was already admitted with another Decision",
                cause_code="IDEMPOTENCY_CONFLICT",
            )
        gate = self._decisions.admit if prior is None else self._decisions.reverify
        try:
            admitted = gate(
                decision.decision,
                proposal=proposal,
                package=decision.package,
                package_digest=decision.package_digest,
                approval_set=approval_set,
            )
        except ApprovalGateError as error:
            reason = "DECISION_REJECTED" if error.reason_code == "DECISION_REJECTED" else "DECISION_MISSING"
            raise GovernedActionError(reason, str(error), cause_code=error.reason_code) from error
        with self._lock:
            self._admitted.setdefault(proposal.action_instance_id, admission)
        return admitted

    def _action_command(
        self, proposal: c6_records.ActionProposal, decision: AuthorizedDecision, admitted: c6_records.Decision
    ) -> c6_records.ActionCommand:
        # ACT-T11/T12: the ActionIntent of the accepted Decision and its ActionCommand, which
        # carries the GatePackage digest and the GovernedContext digest (ADD v1.3 :384).
        suffix = hashlib.sha256(proposal.action_instance_id.encode("utf-8")).hexdigest()
        now = self._emission_fence.validator.clock.now()
        try:
            intent = c6_records.ActionIntent.from_decision(
                intent_id=f"urn:ocor:intent:{suffix}",
                decision=admitted,
                package=decision.package,
                package_digest=decision.package_digest,
                created_at=now,
            )
            return c6_records.ActionCommand.issue(
                command_id=f"urn:ocor:command:{suffix}",
                intent=intent,
                package=decision.package,
                package_digest=decision.package_digest,
                parameters=dict(proposal.parameters),
                idempotency_key=f"c6-action-{suffix}",
                deadline=min(admitted.valid_until, decision.package.valid_until),
            )
        except c6_records.C6RecordError as error:
            raise GovernedActionError("INVALIDATED", str(error), cause_code="COMMAND_DIGEST_MISMATCH") from error

    def _current(
        self, proposal: c6_records.ActionProposal, admitted: c6_records.Decision, approval_set: c6_records.ApprovalSet
    ) -> CurrentValues:
        # G-FRESHNESS reads the current values from C3, the GovernedContext, the active release
        # and the Human Gate, inside the fence's transaction.
        context = self._path.governed_context
        revision = int(
            self._commit_port.current_revision(context.tenant_id, self._path.aggregate_type, proposal.target_ref)
        )
        return CurrentValues(
            expected_revision=revision,
            canonical_commit_ref=canonical_commit_ref(proposal.target_ref, revision),
            governed_context_digest=context.digest(),
            policy_bundle_digest=context.policy_bundle_digest,
            ontology_release_digest=self._path.fence.active_release_digest(),
            authority_ref=admitted.authority_id,
            approval_set_digest=approval_set.digest(),
            adapter_binding_digest=C3_ADAPTER_BINDING_DIGEST,
            projection_watermark=projection_watermark(revision),
        )

    def execute(
        self,
        proposal: c6_records.ActionProposal,
        *,
        lease: SignedCapabilityLease,
        approval: c6_records.ApprovalSet | None,
        decision: AuthorizedDecision | None,
        sink: EventSink | Callable[[Any], Any],
        at: datetime,
        evidence_refs: Sequence[str] | None = None,
        claim_source_bindings: Sequence[Mapping[str, str]] | None = None,
    ) -> ActionOutcome:
        instant = _require_aware(at, field="at")
        action_type = self._action_type(proposal)
        signed_lease, delegation = self._authority(proposal, action_type, lease)

        # CONTROL_CHECK (ACT-T06/ACT-T07): the obligation follows the ActionType's risk class and
        # the canonical target never takes NOT_REQUIRED (LLD v1.1 :268, ADD v1.3 :3298-3303).
        try:
            gate_disposition(action_type.risk_class, canonical_target=True)
        except ApprovalGateError as error:
            raise GovernedActionError("NO_MUTATION_ADMITTED", str(error), cause_code=error.reason_code) from error

        approval_set = self._approval_set(proposal, approval)
        admitted = self._decision(proposal, action_type, approval_set, decision)
        if not isinstance(decision, AuthorizedDecision):
            raise GovernedActionError("DECISION_MISSING", "a governed action requires the Authority's signed Decision")
        action_id = proposal.action_instance_id
        with self._lock:
            confirmed = self._confirmed.get(action_id)
        if confirmed is not None:
            # A confirmed action instance is not sent again: the retry gets its outcome.
            return confirmed

        if evidence_refs is None or claim_source_bindings is None:
            if self._path.evidence is None:
                raise GovernedActionError("EVIDENCE_MISSING", "a canonical commit requires its Evidence and claim/source bindings")
            resolved_refs, resolved_bindings = self._path.evidence(proposal)
            evidence_refs = resolved_refs if evidence_refs is None else evidence_refs
            claim_source_bindings = resolved_bindings if claim_source_bindings is None else claim_source_bindings
        action_command = self._action_command(proposal, decision, admitted)
        command = self._path.command(
            proposal,
            admitted,
            expected_revision=decision.package.expected_revision,
            canonical_delta={"action_id": action_id, "status": "EXECUTED"},
            evidence_refs=evidence_refs,
            claim_source_bindings=claim_source_bindings,
        )
        if (
            command.action_instance_id != action_command.action_instance_id
            or command.aggregate_ref != action_command.target_ref
            or command.idempotency_key != action_command.idempotency_key
            or command.governed_context_digest != action_command.governed_context_digest
            or command.expected_revision != decision.package.expected_revision
        ):
            raise GovernedActionError(
                "INVALIDATED", "the C3 command is not the decided ActionCommand", cause_code="COMMAND_DIGEST_MISMATCH"
            )

        # EMISSION-FENCE (ACT-T29): G-FRESHNESS and G-DISPATCH with the lease consumption and the
        # DeliveryAttempt in one transaction, immediately before the send to C3.
        try:
            attempt = self._emission_fence.evaluate(
                package=decision.package,
                package_digest=decision.package_digest,
                command=action_command,
                lease=signed_lease,
                capability_id=action_type.capability,
                effective_principal_id=self._path.governed_context.effective_principal_id,
                delegation_ref=delegation,
                observe=lambda: self._current(proposal, admitted, approval_set),
            )
        except DispatchError as error:
            raise GovernedActionError("INVALIDATED", str(error), cause_code=error.reason_code) from error

        # Canonical commit (ACT-T30): C3 admits the command only on the signed governed path and
        # commits state and outbox atomically.
        commit_receipt = self._commit_port.commit(command)
        payload = {"action_id": action_id, "commit_id": commit_receipt.commit_id, "status": "EXECUTED"}
        event = CommittedOutboxEvent(
            event_id=commit_receipt.outbox_event_id,
            aggregate_id=proposal.target_ref,
            aggregate_version=commit_receipt.to_revision,
            event_type="governed-action-executed",
            payload=payload,
            payload_digest=canonical_digest(payload),
            request_digest=commit_receipt.command_digest,
            idempotency_key=command.idempotency_key,
            transaction_id=commit_receipt.commit_id,
            occurred_at=instant,
        )
        if self._outbox is not None:
            event = self._outbox.record(event)

        # The committed outbox event crosses the C7 relay (registration, integrity and order)
        # as the simulated effect; the canonical state is already committed.
        receipt = self._relay.emit(cast(Any, event), sink, at=instant)
        outcome = ActionOutcome(action_id, receipt, receipt.sink_result, commit_receipt, attempt)
        with self._lock:
            self._confirmed.setdefault(action_id, outcome)
        return outcome
