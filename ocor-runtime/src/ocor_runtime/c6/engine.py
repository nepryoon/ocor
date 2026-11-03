"""C6 — retained governed-action slice.

The smallest contract-compliant slice of LLD v1.1 section 3's
normative 44-transition C6 workflow (OCOR-DEV-0020's sealed
``spikes.c6_fsm_fidelity.generator`` proves the full transition table's
fidelity to the approved LLD; this task builds retained, executable
code for the representative path a single risk-bearing action takes
through it, not the full FSM): a proposed action must cross, in strict
order, Authority (``G-AUTHORITY``, via the sealed
``ocor_runtime.c6_capabilities.CapabilityAuthority``), Human Gate
(``G-APPROVAL`` / "Human Gate richiesto", ``ACT-T06``/``ACT-T08``),
Decision (``G-DECISION``, ``ACT-T10b``) and EMISSION-FENCE (via the
sealed ``ocor_runtime.c7_emission.EmissionFence``, ``ACT-T12``/
``ACT-T29``) before any simulated external effect is applied. Any gate
failure denies the action before the durable canonical commit or the
simulated effect ever happen.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
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
    sign_governance_record,
)
from ..c3.ports import CommitReceipt, GovernedCanonicalCommitCommand
from ..c6_capabilities import CapabilityAuthority, CapabilityLease
from ..c7_emission import EmissionFence, EmissionReceipt, EventSink
from ..errors import AuthorizationError, EmissionBlocked, OCORError
from ..kernel.canonical import canonical_digest, format_utc_timestamp
from ..kernel.governance import TrustedClock
from ..kernel.governed_context import GovernedContext


class GovernedActionError(OCORError):
    """A governed action was denied at one of its four gates. ``reason_code``
    identifies which gate (AUTHORITY_DENIED, APPROVAL_MISSING,
    DECISION_MISSING or DECISION_REJECTED), mirroring the reason-code
    pattern already established by the retained C3 adapter."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _require_aware(instant: datetime, *, field: str) -> datetime:
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return instant


@dataclass(frozen=True, slots=True)
class ActionProposal:
    action_id: str
    subject: str
    capability: str
    resource: str
    aggregate_id: str
    risk_bearing: bool


@dataclass(frozen=True, slots=True)
class Approval:
    """The Human Gate disposition (``ACT-T08``/``ACT-T09a``/``ACT-T09b``)."""

    action_id: str
    approver: str
    approved: bool
    approved_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.approved_at, field="approved_at")
        if not self.approver:
            raise ValueError("an Approval requires an approver")


@dataclass(frozen=True, slots=True)
class Decision:
    """The Decision gate disposition (``ACT-T10a``/``ACT-T10b``)."""

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


@runtime_checkable
class GovernanceRecordSink(Protocol):
    """Write side of the C6 governance record store that C3 admission reads."""

    def publish(self, record: SignedGovernanceRecord) -> None: ...


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
        proposal: ActionProposal,
        decision: Decision,
        *,
        expected_revision: int,
        canonical_delta: Mapping[str, Any],
        evidence_refs: Sequence[str],
        claim_source_bindings: Sequence[Mapping[str, str]],
    ) -> GovernedCanonicalCommitCommand:
        with self._lock:
            issued = self._issued.get(proposal.action_id)
            if issued is not None:
                return issued
            suffix = hashlib.sha256(proposal.action_id.encode("utf-8")).hexdigest()
            now = self.clock.now()
            context = self.governed_context
            fields: dict[str, Any] = {
                "command_id": f"urn:ocor:command:{suffix}",
                "action_instance_id": proposal.action_id,
                "aggregate_type": self.aggregate_type,
                "aggregate_ref": proposal.aggregate_id,
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
                    "action_instance_id": proposal.action_id,
                    "outcome": "ACCEPT" if decision.accepted else "REJECT",
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
                    "action_instance_id": proposal.action_id,
                    "gate_package_digest": gate_package_digest,
                    "tenant_id": context.tenant_id,
                    "effective_principal_id": context.effective_principal_id,
                    "not_before": format_utc_timestamp(now),
                    "expires_at": format_utc_timestamp(now + self.validity),
                },
            )
            command = GovernedCanonicalCommitCommand.from_mapping({**fields, "gate_package_digest": gate_package_digest})
            self._issued[proposal.action_id] = command
            return command


class GovernedActionEngine:
    """Authority -> Human Gate -> Decision -> canonical commit through C3 ->
    EMISSION-FENCE -> simulated effect, evaluated strictly in that order and
    fail-closed at every gate. No simulated effect is ever applied unless all
    four gates are satisfied and C3 admitted the commit.
    """

    def __init__(
        self,
        *,
        authority: CapabilityAuthority,
        commit_port: CanonicalCommitTarget,
        fence: EmissionFence,
        canonical_path: CanonicalCommitPath,
    ) -> None:
        if not isinstance(commit_port, CanonicalCommitTarget):
            raise TypeError("commit_port must implement the C3 GovernedCommitPort and RevisionPort")
        if not isinstance(canonical_path, CanonicalCommitPath):
            raise TypeError("canonical_path must be a CanonicalCommitPath")
        self._authority = authority
        self._commit_port = commit_port
        self._fence = fence
        self._path = canonical_path

    def execute(
        self,
        proposal: ActionProposal,
        *,
        lease: CapabilityLease | str,
        approval: Approval | None,
        decision: Decision | None,
        sink: EventSink | Callable[[Any], Any],
        at: datetime,
        evidence_refs: Sequence[str],
        claim_source_bindings: Sequence[Mapping[str, str]],
    ) -> ActionOutcome:
        instant = _require_aware(at, field="at")

        # G-AUTHORITY (ACT-T04): principal, capability and resource scope.
        try:
            self._authority.authorize(
                lease,
                proposal.capability,
                proposal.resource,
                at=instant,
                subject=proposal.subject,
                consume=True,
            )
        except AuthorizationError as error:
            raise GovernedActionError("AUTHORITY_DENIED", str(error)) from error

        # Human Gate (ACT-T06/ACT-T07/ACT-T08/ACT-T09a/ACT-T09b): only
        # risk-bearing actions require a resolved approval; a
        # non-risk-bearing action's gate disposition is NOT_REQUIRED.
        if proposal.risk_bearing:
            if approval is None or approval.action_id != proposal.action_id:
                raise GovernedActionError(
                    "APPROVAL_MISSING", "a risk-bearing action requires a resolved Human Gate approval"
                )
            if not approval.approved:
                raise GovernedActionError("APPROVAL_MISSING", "Human Gate approval was not granted")

        # G-DECISION (ACT-T10a/ACT-T10b): a signed Decision is always required.
        if decision is None or decision.action_id != proposal.action_id:
            raise GovernedActionError("DECISION_MISSING", "a governed action requires a signed Decision")
        if not decision.accepted:
            raise GovernedActionError("DECISION_REJECTED", decision.rationale)

        # Canonical commit (ACT-T29/T30): C6 sends the governed command to C3, which
        # admits it only on the signed governed path and commits state and outbox atomically.
        context = self._path.governed_context
        command = self._path.command(
            proposal,
            decision,
            expected_revision=self._commit_port.current_revision(
                context.tenant_id, self._path.aggregate_type, proposal.aggregate_id
            ),
            canonical_delta={"action_id": proposal.action_id, "status": "EXECUTED"},
            evidence_refs=evidence_refs,
            claim_source_bindings=claim_source_bindings,
        )
        commit_receipt = self._commit_port.commit(command)
        event = CommittedOutboxEvent(
            event_id=commit_receipt.outbox_event_id,
            aggregate_id=proposal.aggregate_id,
            aggregate_version=commit_receipt.to_revision,
            event_type="governed-action-executed",
            payload={"action_id": proposal.action_id, "commit_id": commit_receipt.commit_id, "status": "EXECUTED"},
            payload_digest=canonical_digest(
                {"action_id": proposal.action_id, "commit_id": commit_receipt.commit_id, "status": "EXECUTED"}
            ),
            request_digest=commit_receipt.command_digest,
            idempotency_key=command.idempotency_key,
            transaction_id=commit_receipt.commit_id,
            occurred_at=instant,
        )

        # EMISSION-FENCE (ACT-T12/ACT-T14): the final atomic gate
        # immediately before the simulated effect; blocks on
        # uncommitted/tampered/out-of-order events.
        try:
            receipt = self._fence.emit(cast(Any, event), sink, at=instant)
        except EmissionBlocked:
            raise

        return ActionOutcome(proposal.action_id, receipt, receipt.sink_result, commit_receipt)
