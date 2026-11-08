"""C8 -- AgentRun orchestration of the Governed Agent Kernel: team runs, tasks, handoffs and dissent.

OCOR-DEV-REM-0058 (NCP-U10; register entries NCR-C8-001, 002 and 003) rebuilds the orchestrator of
OCOR-DEV-0046 on the normative C8 elements. Coordination is mediated (ADD v1.3 §4.3 :3042): every
exchange crosses the ``CoordinationKernel``, which authenticates the transport Principal, binds it to
the Governed Context of the call and to the run's version fence, and reads capability, Delegation,
policy, schema, budget, stop epoch and expiry live. There is no peer-to-peer channel, no shared
memory and no datastore other than the C8 Run Ledger (FR-115 :264).

Closed records (LLD v1.1 §2.8 :183): ``AgentRun``, ``Task``, ``Assignment``, ``Commitment``,
``HandoffEnvelope``, ``Dissent`` with its separate ``DissentResolution``, ``DecisionProposal``,
``ToolInvocation`` and ``Message``. They are AgentRun state of C8, appended to the PostgreSQL Run
Ledger (ADD v1.3 §2.2 :276): never canonical state, which only C6 produces through C3 (§2.5 rule 10
:342). A ``Message`` is tainted ``AGENT_MESSAGE``/``UNTRUSTED`` and non-canonical (§2.5 rule 7 :339,
§4.3.1 invariant 3 :3116): it never changes a task, grants a capability or stands in for a lease
(FR-117 :266). C8 holds no canonical commit port.

Roles and typed outputs (ADD v1.3 :3057-3064): ``Fusion/Identity``, ``Hypothesis``, ``Causal``,
``Policy``, ``Challenger`` and ``Coordinator`` each produce only their typed outputs; only the
Coordinator proposes tasks, assigns, cancels, retries and assembles the ``DecisionProposal``, which
is never executable; the Coordinator cannot resolve or suppress a dissent and no member holds a tier
outside the PoC profile (``observe``, ``analyze``, ``simulate``, ``propose``; :3115).

Task lifecycle (ADD v1.3 :3101-3106): ``PROPOSED -> POLICY_AUTHORIZED -> ACCEPTED -> COMPLETED |
ABSTAINED | FAILED | EXPIRED | CANCELLED``. An assignment checks machine identity, capability,
Delegation, autonomy tier, budget and termination condition (LLD v1.1 :183) and the policy decision
that authorises it; ``ACCEPTED`` creates a Commitment; ``COMPLETED`` requires the conforming typed
output, its digest and evidence references. Retries keep the ``logical_task_id`` with a distinct
attempt; dependency cycles, delegation beyond the maximum depth, the task and run timeouts and the
task and attempt limits stop the work (FR-121 :270); an exhausted budget fails the task (FR-010 :62).

Handoff (ADD v1.3 :3068-3098, :388): the sender holding the commitment must be the transport
Principal, with a lease of its own; the payload is validated against the pinned handoff schema and
digested here, never taken from the caller; the marking of the Governed Context of the handoff is
resolved and must be dominated by the clearance of the recipient (``POLICY_DENIED`` otherwise, or
when either cannot be resolved; ADD v1.3 :3042, :3118); the Kernel signs the 28-field
``HandoffEnvelope``. A refused handoff is kept as a ``REJECTED`` envelope in the Run Ledger and written to the signed audit
chain (``CAPABILITY_DENIED`` + audit for a sender that is not the transport Principal).

Dissent (ADD v1.3 :3108-3110): a Critical dissent about identity ambiguity, policy violation, causal
abstention or provenance gap blocks a High-Impact proposal until resolved; every unresolved dissent
accompanies the proposal. A dissent is never overwritten: its resolution is a separate record made by
its author or by the run's escalation target.

Coordination capabilities (``agent:assign``, ``agent:commit``, ``agent:handoff``, ``agent:dissent``)
remain leases of the sealed ``CapabilityAuthority`` composed through its public methods (single-use,
revocable); the Kernel adds the live controls around them.

Atomicity: the Run Ledger entries of one public transition -- several for a run timeout, which
expires every open task -- are written in one ledger transaction at the end of the call, and the
leases the transition consumes are consumed inside that transaction, before it commits. A ledger
that does not record the transition restores the in-memory state of the call and spends no lease
(``LEDGER_UNAVAILABLE``). Residual, declared: a commit that fails after the leases were consumed
leaves them spent with no transition (fail-closed: a use is lost, never granted twice).
"""

from __future__ import annotations

import functools
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar, runtime_checkable

from ..audit import AuditEvent, AuditPort
from ..c1.signing import Ed25519SigningKey, dsse_pae
from ..c6.safety import EmergencyStopController, StopEpochReader, StopStatus
from ..c4.marking import MarkingUnresolved
from ..c4.marking_resolution import ResolvedMarkingEngine
from ..c4_marking import MarkingSet
from ..c6_capabilities import CapabilityAuthority, CapabilityLease
from ..errors import OCORError
from ..kernel.canonical import canonical_bytes, canonical_digest, format_utc_timestamp
from ..kernel.governed_context import GovernedContext
from ..security.ports import AuthenticatedPrincipal, PolicyDecisionPort, PolicyRequest
from .tool_contract import UNTRUSTED_TOOL_OUTPUT_TAINT, SchemaCatalog, SchemaPin, ToolOutput, verified_tool_output
from .tool_runtime import (
    POC_AUTONOMY_TIERS,
    AgentBudgetLedger,
    AgentIdentityBinding,
    GovernanceControlPort,
    ToolCallReceipt,
    ToolRuntimeError,
    verified_decision,
)


def require_aware(instant: datetime, *, field: str) -> datetime:
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise OrchestratorError("SCHEMA_VIOLATION", f"{field} must be a timezone-aware instant")
    return instant


def _deadline(instant: datetime, timeout: timedelta) -> datetime:
    """``instant + timeout``; a timeout beyond the representable instants is refused."""
    try:
        return instant + timeout
    except OverflowError as error:
        raise OrchestratorError("SCHEMA_VIOLATION", "the timeout is beyond the representable instants") from error


_DELEGATION_REF = re.compile(r"^urn:sha256:[0-9a-f]{64}$")
_SIGNATURE_HEX = re.compile(r"^[0-9a-f]{128}$")


_P = ParamSpec("_P")
_R = TypeVar("_R")


def _atomic(method: Callable[Concatenate[AgentRunOrchestrator, _P], _R]) -> Callable[Concatenate[AgentRunOrchestrator, _P], _R]:
    """A public transition of the orchestrator either reaches the Run Ledger or leaves no
    in-memory state. Its entries are written in one ledger transaction when the call ends -- also
    when it ends with a refusal that changed state (a run timeout, an expired task, a rejected
    handoff) -- and the leases it consumes are consumed inside that transaction, only when the call
    succeeded. When the ledger fails, the state of the call is restored, no lease is spent and the
    failure is ``LEDGER_UNAVAILABLE``."""

    def atomic(self: AgentRunOrchestrator, /, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        if self._pending is not None:
            return method(self, *args, **kwargs)
        snapshot = self._snapshot()
        self._pending, self._consumes = [], []
        try:
            try:
                result = method(self, *args, **kwargs)
            except OrchestratorError as refusal:
                # a refused call spends no lease; the state it changed is still recorded
                self._consumes = []
                self._flush(snapshot)
                raise refusal
            self._flush(snapshot)
            return result
        finally:
            self._pending, self._consumes = None, []

    functools.update_wrapper(atomic, method)
    return atomic


@runtime_checkable
class RunLedgerPort(Protocol):
    """Append-only C8 Run Ledger (PostgreSQL in the product)."""

    def append(
        self,
        *,
        idempotency_key: str,
        task_id: str,
        kind: str,
        agent_id: str,
        payload: Mapping[str, Any],
        recorded_at: datetime,
    ) -> Any: ...

    def append_all(self, entries: Sequence[Mapping[str, Any]], *, before_commit: Callable[[], None]) -> Any:
        """Append ``entries`` (each with the arguments of ``append``) in one transaction; call
        ``before_commit`` inside it, after the inserts and before the commit, so that an error it
        raises rolls every entry back."""
        ...

    def entries(self, task_id: str) -> tuple[Any, ...]: ...


class OrchestratorError(OCORError):
    """A C8 AgentRun state transition was refused; ``reason_code`` identifies why."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _refuse(code: str, message: str) -> OrchestratorError:
    return OrchestratorError(code, message)


# --- roles, lifecycle and dissent vocabularies (ADD v1.3 §4.3) -----------------------------------


class AgentRole(Enum):
    FUSION_IDENTITY = "Fusion/Identity"
    HYPOTHESIS = "Hypothesis"
    CAUSAL = "Causal"
    POLICY = "Policy"
    CHALLENGER = "Challenger"
    COORDINATOR = "Coordinator"


# Typed outputs of each role (ADD v1.3 :3057-3064); ABSTAIN is the ABSTAINED lifecycle state.
ROLE_OUTPUTS: Mapping[AgentRole, tuple[str, ...]] = MappingProxyType(
    {
        AgentRole.FUSION_IDENTITY: ("FusionIdentityFinding@1", "CandidateMatchSet@1", "ResolutionProposal@1"),
        AgentRole.HYPOTHESIS: ("HypothesisPortfolio@1",),
        AgentRole.CAUSAL: ("CausalAnalysisResult@1", "SimulationResult@1"),
        AgentRole.POLICY: ("PolicyEvaluationPackage@1",),
        AgentRole.CHALLENGER: ("DissentRecord@1", "CounterEvidence@1", "AssumptionChallenge@1", "ResidualRisk@1"),
        AgentRole.COORDINATOR: ("DecisionProposal@1", "EscalationPackage@1", "TerminationRecord@1"),
    }
)


class TaskState(Enum):
    PROPOSED = "PROPOSED"
    POLICY_AUTHORIZED = "POLICY_AUTHORIZED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    ABSTAINED = "ABSTAINED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = frozenset({TaskState.COMPLETED, TaskState.ABSTAINED, TaskState.FAILED, TaskState.EXPIRED, TaskState.CANCELLED})
RETRYABLE_STATES = frozenset({TaskState.FAILED, TaskState.EXPIRED})


class DissentSeverity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DissentCategory(Enum):
    IDENTITY_AMBIGUITY = "IDENTITY_AMBIGUITY"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    CAUSAL_ABSTENTION = "CAUSAL_ABSTENTION"
    PROVENANCE_GAP = "PROVENANCE_GAP"
    COUNTER_EVIDENCE = "COUNTER_EVIDENCE"
    ASSUMPTION_CHALLENGE = "ASSUMPTION_CHALLENGE"
    RESIDUAL_RISK = "RESIDUAL_RISK"


# A Critical dissent of these categories blocks a High-Impact proposal (ADD v1.3 :3108).
BLOCKING_CATEGORIES = frozenset(
    {DissentCategory.IDENTITY_AMBIGUITY, DissentCategory.POLICY_VIOLATION, DissentCategory.CAUSAL_ABSTENTION, DissentCategory.PROVENANCE_GAP}
)


class ProposalImpact(Enum):
    HIGH_IMPACT = "HIGH_IMPACT"
    STANDARD = "STANDARD"


SPEECH_ACTS = ("INFORM", "REQUEST", "PROPOSE", "CHALLENGE", "ACKNOWLEDGE")
MESSAGE_TAINT: tuple[str, ...] = ("AGENT_MESSAGE", "UNTRUSTED")
BASELINE_REF = "urn:ocor:baseline:ocor-add-v1.3"
HANDOFF_TTL = timedelta(minutes=5)
ENVELOPE_PAYLOAD_TYPE = "application/vnd.ocor.c8.handoff-envelope+json"
_TIER_RANK = MappingProxyType({tier: rank for rank, tier in enumerate(POC_AUTONOMY_TIERS)})
# the C8 coordination actions presented to the policy decision point
ACTIONS = MappingProxyType(
    {
        name: f"urn:ocor:capability:c8:{name}"
        for name in (
            "start-run",
            "propose-task",
            "assign",
            "commit",
            "handoff",
            "complete",
            "abstain",
            "fail",
            "cancel",
            "retry",
            "dissent",
            "resolve-dissent",
            "propose-decision",
            "message",
            "record-tool-invocation",
        )
    }
)
# context fields that make the version fence of a run (ADD v1.3 :3042)
_FENCE_FIELDS = (
    "tenant_id",
    "organization_id",
    "domain_id",
    "compartments",
    "classification_marking_ref",
    "ontology_release_digest",
    "policy_bundle_digest",
)


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 512 or value != value.strip():
        raise _refuse("SCHEMA_VIOLATION", f"{name} must be a non-empty bounded string")
    return value


def _texts(name: str, values: object, *, required: bool = False) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise _refuse("SCHEMA_VIOLATION", f"{name} must be a sequence of strings")
    items = tuple(_text(name, value) for value in values)
    if required and not items:
        raise _refuse("SCHEMA_VIOLATION", f"{name} must not be empty")
    if len(set(items)) != len(items):
        raise _refuse("SCHEMA_VIOLATION", f"{name} must not repeat")
    return items


def _wire(value: Any) -> Any:
    """The JSON form of a record value for the Run Ledger and the envelope signature."""
    if isinstance(value, datetime):
        return format_utc_timestamp(value)
    if isinstance(value, timedelta):
        return int(value.total_seconds() * 1000)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _wire(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_wire(item) for item in value]
    return value


def _frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({key: _wire(item) for key, item in value.items()})


# --- records (LLD v1.1 §2.8 :183) -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TerminationCondition:
    """FR-121 :270: termination condition, maximum delegation depth, timeout and escalation target of a
    run, with its attempt and task limits."""

    max_delegation_depth: int
    timeout: timedelta
    max_attempts: int
    max_tasks: int
    escalation_target: str

    def __post_init__(self) -> None:
        for name, minimum in (("max_delegation_depth", 0), ("max_attempts", 1), ("max_tasks", 1)):
            value = getattr(self, name)
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer of at least {minimum}")
        if not isinstance(self.timeout, timedelta) or self.timeout <= timedelta(0):
            raise ValueError("timeout must be a positive timedelta")
        if not isinstance(self.escalation_target, str) or not self.escalation_target.startswith("urn:"):
            raise ValueError("escalation_target must be a URN")


@dataclass(frozen=True, slots=True)
class TeamMember:
    role: AgentRole
    binding: AgentIdentityBinding


@dataclass(frozen=True, slots=True)
class AgentRun:
    team_run_id: str
    team_id: str
    tenant_id: str
    coordinator: str
    members: tuple[TeamMember, ...]
    termination: TerminationCondition
    governed_context: Mapping[str, Any]
    governed_context_digest: str
    started_at: datetime
    deadline: datetime
    status: str = "RUNNING"
    termination_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    logical_task_id: str
    attempt: int
    team_run_id: str
    role: AgentRole
    output_type: str
    autonomy_tier: str
    dependencies: tuple[str, ...]
    parent_task_id: str | None
    delegation_depth: int
    timeout: timedelta
    deadline: datetime
    proposed_by: str
    proposed_at: datetime
    state: TaskState = TaskState.PROPOSED
    output_digest: str | None = None
    evidence_refs: tuple[str, ...] = ()
    outcome_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Assignment:
    assignment_id: str
    task_id: str
    agent_id: str
    capability: str
    assigned_by: str
    assigned_at: datetime
    agent_run_id: str
    workload_identity: str
    delegation_ref: str
    autonomy_tier: str
    policy_decision_id: str


TaskAssignment = Assignment


@dataclass(frozen=True, slots=True)
class Commitment:
    commitment_id: str
    task_id: str
    agent_id: str
    assignment_id: str
    committed_at: datetime


@dataclass(frozen=True, slots=True)
class HandoffEnvelope:
    """The Kernel-attested handoff of ADD v1.3 :3068-3098, with its accepted/rejected status."""

    handoff_id: str
    team_run_id: str
    task_id: str
    assignment_id: str
    parent_handoff_id: str | None
    asserted_sender_principal: str
    recipient_principal: str
    contract_id: str
    contract_version: str
    speech_act: str
    payload_ref: str
    payload_digest: str
    evidence_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    taint_labels: tuple[str, ...]
    baseline_ref: str
    governed_context: Mapping[str, Any]
    governed_context_digest: str
    ontology_release_digest: str
    model_digest: str | None
    delegation_ref: str
    effective_authority_ref: str
    correlation_id: str
    causation_id: str
    created_at: datetime
    expires_at: datetime
    budget_remaining: Mapping[str, int]
    signature_ref: str
    status: str
    rejection_reason: str | None

    @property
    def from_agent_id(self) -> str:
        return self.asserted_sender_principal

    @property
    def to_agent_id(self) -> str:
        return self.recipient_principal


Handoff = HandoffEnvelope
_SIGNED_FIELDS = tuple(name for name in HandoffEnvelope.__dataclass_fields__ if name not in {"signature_ref", "status", "rejection_reason"})


def envelope_signing_bytes(envelope: HandoffEnvelope) -> bytes:
    """The DSSE pre-authentication encoding of the envelope fields the Kernel signs."""
    return dsse_pae(ENVELOPE_PAYLOAD_TYPE, canonical_bytes({name: _wire(getattr(envelope, name)) for name in _SIGNED_FIELDS}))


def envelope_signature(envelope: HandoffEnvelope) -> bytes:
    """The Ed25519 signature carried by ``signature_ref``."""
    reference = envelope.signature_ref
    signature = reference.rsplit(":", 1)[-1] if isinstance(reference, str) and ":" in reference else ""
    if _SIGNATURE_HEX.fullmatch(signature) is None:
        raise _refuse("SCHEMA_VIOLATION", "signature_ref carries no Ed25519 signature")
    return bytes.fromhex(signature)


@dataclass(frozen=True, slots=True)
class Dissent:
    """An explicit, immutable record of disagreement -- never mutated, removed or retracted once
    registered; its resolution is a separate ``DissentResolution``."""

    dissent_id: str
    team_run_id: str
    task_id: str
    agent_id: str
    reason: str
    severity: DissentSeverity
    category: DissentCategory
    registered_at: datetime


@dataclass(frozen=True, slots=True)
class DissentResolution:
    resolution_id: str
    dissent_id: str
    resolved_by: str
    resolution: str
    resolved_at: datetime


@dataclass(frozen=True, slots=True)
class DecisionProposal:
    """The only artefact that reaches the Human Gate (ADD v1.3 :3123); never executable."""

    proposal_id: str
    team_run_id: str
    impact: ProposalImpact
    alternatives: tuple[str, ...]
    assumptions: tuple[str, ...]
    uncertainty: str
    abstentions: tuple[str, ...]
    dissent_ids: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    proposed_by: str
    proposed_at: datetime
    executable: bool = False

    def __post_init__(self) -> None:
        if self.executable is not False:
            raise ValueError("a DecisionProposal is never executable")


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    invocation_id: str
    team_run_id: str
    task_id: str
    agent_principal_id: str
    agent_run_id: str
    tool_name: str
    lease_id: str
    contract_ids: tuple[str, ...]
    input_digests: tuple[str, ...]
    output_digests: tuple[str, ...]
    policy_decision_ids: tuple[str, ...]
    taint_labels: tuple[str, ...]
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class Message:
    """Agent communication: tainted, non-canonical, never Authority (FR-117 :266)."""

    message_id: str
    team_run_id: str
    sender: str
    recipient: str
    speech_act: str
    payload_digest: str
    sent_at: datetime
    taint_labels: tuple[str, ...] = MESSAGE_TAINT
    canonical: bool = False

    def __post_init__(self) -> None:
        if self.canonical is not False or not set(MESSAGE_TAINT) <= set(self.taint_labels):
            raise ValueError("a Message is always tainted and never canonical")


# --- the Coordination Kernel ----------------------------------------------------------------------


@runtime_checkable
class CoordinationMarkingPort(Protocol):
    """The marking of a Governed Context (by its ``classification_marking_ref``) and the clearance
    of an agent principal, read live at every handoff."""

    def marking(self, marking_ref: str) -> MarkingSet: ...

    def clearance(self, agent_principal_id: str) -> MarkingSet: ...


class InMemoryCoordinationMarkings:
    """``CoordinationMarkingPort`` held in memory: an unknown reference or agent raises."""

    def __init__(self) -> None:
        self._markings: dict[str, MarkingSet] = {}
        self._clearances: dict[str, MarkingSet] = {}

    def define(self, marking_ref: str, marking: MarkingSet) -> None:
        if not isinstance(marking_ref, str) or not isinstance(marking, MarkingSet):
            raise TypeError("a marking is a MarkingSet named by its reference")
        self._markings[marking_ref] = marking

    def set_clearance(self, agent_principal_id: str, clearance: MarkingSet) -> None:
        if not isinstance(agent_principal_id, str) or not isinstance(clearance, MarkingSet):
            raise TypeError("a clearance is a MarkingSet of an agent principal")
        self._clearances[agent_principal_id] = clearance

    def marking(self, marking_ref: str) -> MarkingSet:
        return self._markings[marking_ref]

    def clearance(self, agent_principal_id: str) -> MarkingSet:
        return self._clearances[agent_principal_id]


@dataclass(frozen=True, slots=True)
class OutputContract:
    """A typed output (or the handoff payload) and the pinned schema it validates against."""

    output_type: str
    contract_id: str
    contract_version: str
    schema: SchemaPin


class CoordinationKernel:
    """The live controls of C8 coordination: Delegation (``GovernanceControlPort``), policy
    (``PolicyDecisionPort``, OPA in the product), the signed stop epoch, the multidimensional budget,
    the pinned schemas of typed outputs and handoffs, the markings and clearances of every handoff,
    the signed audit chain and the key that attests every HandoffEnvelope. There is no default for
    any of them."""

    def __init__(
        self,
        *,
        controls: GovernanceControlPort,
        policy: PolicyDecisionPort,
        stop: EmergencyStopController | StopEpochReader,
        budgets: AgentBudgetLedger,
        schemas: SchemaCatalog,
        contracts: Sequence[OutputContract],
        handoff_contract: OutputContract,
        audit: AuditPort,
        signing_key: Ed25519SigningKey,
        keyid: str,
        marking_engine: ResolvedMarkingEngine,
        markings: CoordinationMarkingPort,
    ) -> None:
        if not isinstance(marking_engine, ResolvedMarkingEngine):
            raise TypeError("marking_engine must be the ResolvedMarkingEngine")
        if not isinstance(markings, CoordinationMarkingPort):
            raise TypeError("markings must implement the CoordinationMarkingPort")
        if not isinstance(controls, GovernanceControlPort):
            raise TypeError("controls must implement the GovernanceControlPort")
        if policy is None or not callable(getattr(policy, "evaluate", None)):
            raise TypeError("policy must implement the PolicyDecisionPort")
        if isinstance(stop, EmergencyStopController):
            stop = stop.reader
        if not isinstance(stop, StopEpochReader):
            raise TypeError("stop must be a StopEpochReader of the signed stop epoch")
        if not isinstance(budgets, AgentBudgetLedger):
            raise TypeError("budgets must be the AgentBudgetLedger")
        if not isinstance(schemas, SchemaCatalog):
            raise TypeError("schemas must be a SchemaCatalog")
        if not isinstance(audit, AuditPort):
            raise TypeError("audit must implement the AuditPort of the signed audit chain")
        if not isinstance(signing_key, Ed25519SigningKey):
            raise TypeError("signing_key must be an Ed25519SigningKey")
        if not isinstance(keyid, str) or not keyid.startswith("urn:"):
            raise TypeError("keyid must be a URN")
        if isinstance(contracts, (str, bytes)) or not isinstance(contracts, Sequence):
            raise TypeError("contracts must be a sequence of OutputContract")
        known: dict[str, OutputContract] = {}
        for contract in (*contracts, handoff_contract):
            if not isinstance(contract, OutputContract) or not isinstance(contract.schema, SchemaPin):
                raise TypeError("every contract must be an OutputContract with a SchemaPin")
            schemas.resolve(contract.schema)
            if contract.output_type in known:
                raise ValueError(f"output type {contract.output_type} is bound twice")
            known[contract.output_type] = contract
        self.controls = controls
        self.policy = policy
        self.stop = stop
        self.budgets = budgets
        self.audit = audit
        self.keyid = keyid
        self._schemas = schemas
        self._contracts = MappingProxyType(known)
        self.handoff_contract = handoff_contract
        self._key = signing_key
        self.marking_engine = marking_engine
        self.markings = markings

    def check_marking(self, context: GovernedContext, recipient_id: str) -> None:
        """The marking of the handoff's Governed Context must be dominated by the clearance of the
        recipient (ADD v1.3 :3042, :3118); anything that cannot be resolved is a denial."""
        try:
            content = self.markings.marking(context.classification_marking_ref)
            clearance = self.markings.clearance(recipient_id)
        except Exception as error:  # noqa: BLE001 - an unreadable marking or clearance is never a pass
            raise _refuse("POLICY_DENIED", f"the marking or the clearance of {recipient_id!r} cannot be read") from error
        if not isinstance(content, MarkingSet) or not isinstance(clearance, MarkingSet):
            raise _refuse("POLICY_DENIED", f"the marking or the clearance of {recipient_id!r} is not a MarkingSet")
        try:
            authorized = self.marking_engine.authorized(content, clearance)
        except MarkingUnresolved as error:
            raise _refuse("POLICY_DENIED", f"MARKING_UNRESOLVED: {error}") from error
        except Exception as error:  # noqa: BLE001 - a marking that cannot be evaluated is never a pass
            raise _refuse("POLICY_DENIED", f"MARKING_UNRESOLVED: the marking cannot be evaluated ({type(error).__name__})") from error
        if authorized is not True:
            raise _refuse("POLICY_DENIED", f"MARKING_DENIED: the clearance of {recipient_id!r} does not dominate the handoff marking")

    @property
    def public_key(self) -> bytes:
        return self._key.public_key

    def contract(self, output_type: str) -> OutputContract:
        contract = self._contracts.get(output_type) if isinstance(output_type, str) else None
        if contract is None:
            raise _refuse("SCHEMA_VIOLATION", f"no contract is bound to output type {output_type!r}")
        return contract

    def validated_digest(self, contract: OutputContract, value: object) -> str:
        """Validate ``value`` against the pinned schema of ``contract`` and digest it here."""
        if not isinstance(value, Mapping):
            raise _refuse("SCHEMA_VIOLATION", f"{contract.output_type} payload must be an object")
        try:
            validator = self._schemas.resolve(contract.schema)
            document = dict(value)
            errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
            digest = canonical_digest(document)
        except OrchestratorError:
            raise
        except Exception as error:  # noqa: BLE001 - a payload that cannot be validated or digested is never admitted
            raise _refuse("SCHEMA_VIOLATION", f"{contract.output_type} payload cannot be validated") from error
        if errors:
            raise _refuse("SCHEMA_VIOLATION", f"{contract.output_type}: {errors[0].message}")
        return digest

    def sign(self, envelope: HandoffEnvelope) -> str:
        return f"urn:ocor:c8:handoff-signature:{self.keyid}:{self._key.sign(envelope_signing_bytes(envelope)).hex()}"

    def stop_check(self) -> None:
        try:
            record = self.stop.current()
        except Exception as error:  # noqa: BLE001 - an unreadable stop epoch is never a pass
            raise _refuse("EMERGENCY_STOP_ACTIVE", "the signed stop epoch cannot be read") from error
        if record.status is not StopStatus.NORMAL:
            raise _refuse("EMERGENCY_STOP_ACTIVE", f"emergency stop is {record.status.value}")

    def delegation(self, agent_id: str) -> str:
        try:
            delegation = self.controls.verified_delegation(agent_id)
            revoked = None if delegation is None else self.controls.revoked(delegation)
        except Exception as error:  # noqa: BLE001 - unreadable controls are never a pass
            raise _refuse("CAPABILITY_REVOKED", f"the Delegation of {agent_id!r} cannot be verified") from error
        if not isinstance(delegation, str) or _DELEGATION_REF.fullmatch(delegation) is None or revoked is not False:
            raise _refuse("CAPABILITY_REVOKED", f"the Delegation of {agent_id!r} is withdrawn, revoked or not a verified reference")
        return delegation

    def decide(self, principal: AuthenticatedPrincipal, context: GovernedContext, digest: str, action: str, resource: str, at: datetime) -> str:
        try:
            request = PolicyRequest(
                principal=principal, action=action, resource=resource, governed_context=context, governed_context_digest=digest, at=at
            )
            decision = verified_decision(self.policy, request)
        except Exception as error:  # noqa: BLE001 - an unavailable policy is never a pass
            raise _refuse("POLICY_DENIED", f"no valid policy decision for {action} on {resource}") from error
        try:
            decision.admit()
        except Exception as error:  # noqa: BLE001 - a qualified decision the kernel cannot honour is a denial
            code = "APPROVAL_REQUIRED" if getattr(error, "reason_code", "") == "APPROVAL_REQUIRED" else "POLICY_DENIED"
            raise _refuse(code, f"policy decision {decision.decision_id} ({decision.effect.value}) for {action}") from error
        return decision.decision_id

    def charge(self, binding: AgentIdentityBinding, *, steps: int) -> None:
        try:
            self.budgets.budget(binding).charge(steps=steps)
        except ToolRuntimeError as error:
            raise _refuse("BUDGET_EXCEEDED", str(error)) from error

    def remaining(self, binding: AgentIdentityBinding) -> Mapping[str, int]:
        try:
            return MappingProxyType(self.budgets.remaining(binding))
        except ToolRuntimeError as error:
            raise _refuse("BUDGET_EXCEEDED", str(error)) from error


# --- the orchestrator -----------------------------------------------------------------------------


@dataclass(slots=True)
class _Caller:
    principal: AuthenticatedPrincipal
    context: GovernedContext
    digest: str
    agent_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.agent_id = self.principal.principal_id


class AgentRunOrchestrator:
    def __init__(self, *, authority: CapabilityAuthority, kernel: CoordinationKernel, ledger: RunLedgerPort) -> None:
        if not isinstance(authority, CapabilityAuthority):
            raise TypeError("authority must be the CapabilityAuthority of the coordination leases")
        if not isinstance(kernel, CoordinationKernel):
            raise TypeError("kernel must be the CoordinationKernel")
        if not isinstance(ledger, RunLedgerPort):
            raise TypeError("ledger must implement RunLedgerPort")
        self._authority = authority
        self._kernel = kernel
        self._ledger = ledger
        self._runs: dict[str, AgentRun] = {}
        self._tasks: dict[str, Task] = {}
        self._assignments: dict[str, Assignment] = {}
        self._commitments: dict[str, Commitment] = {}
        self._handoffs: list[HandoffEnvelope] = []
        self._dissents: list[Dissent] = []
        self._resolutions: dict[str, DissentResolution] = {}
        self._proposals: list[DecisionProposal] = []
        self._messages: list[Message] = []
        self._sequence = 0
        # the Run Ledger entries and lease consumptions of the public call in progress (_atomic)
        self._pending: list[dict[str, Any]] | None = None
        self._consumes: list[Callable[[], None]] = []

    # -- read-only views ---------------------------------------------------------------------

    @property
    def handoffs(self) -> tuple[HandoffEnvelope, ...]:
        return tuple(self._handoffs)

    @property
    def dissents(self) -> tuple[Dissent, ...]:
        return tuple(self._dissents)

    @property
    def resolutions(self) -> tuple[DissentResolution, ...]:
        return tuple(self._resolutions.values())

    @property
    def proposals(self) -> tuple[DecisionProposal, ...]:
        return tuple(self._proposals)

    @property
    def messages(self) -> tuple[Message, ...]:
        return tuple(self._messages)

    def run(self, team_run_id: str) -> AgentRun | None:
        return self._runs.get(team_run_id)

    def task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def assignment(self, task_id: str) -> Assignment | None:
        return self._assignments.get(task_id)

    def commitment(self, task_id: str) -> Commitment | None:
        return self._commitments.get(task_id)

    # -- plumbing ------------------------------------------------------------------------------

    def _snapshot(self) -> tuple[Any, ...]:
        return (
            dict(self._runs),
            dict(self._tasks),
            dict(self._assignments),
            dict(self._commitments),
            list(self._handoffs),
            list(self._dissents),
            dict(self._resolutions),
            list(self._proposals),
            list(self._messages),
            self._sequence,
        )

    def _restore(self, snapshot: tuple[Any, ...]) -> None:
        (
            self._runs,
            self._tasks,
            self._assignments,
            self._commitments,
            self._handoffs,
            self._dissents,
            self._resolutions,
            self._proposals,
            self._messages,
            self._sequence,
        ) = snapshot

    def _append(self, run: AgentRun, key: str, kind: str, agent_id: str, payload: Mapping[str, Any], at: datetime) -> None:
        """Queue an entry of the public call in progress; ``_flush`` writes them together."""
        if self._pending is None:
            raise RuntimeError("a Run Ledger entry is written only within a public transition")
        self._sequence += 1
        self._pending.append(
            {
                "idempotency_key": f"{run.team_run_id}:{self._sequence}",
                "task_id": key,
                "kind": kind,
                "agent_id": agent_id,
                "payload": {"team_run_id": run.team_run_id, **{name: _wire(value) for name, value in payload.items()}},
                "recorded_at": at,
            }
        )

    def _flush(self, snapshot: tuple[Any, ...]) -> None:
        """Write the queued entries in one ledger transaction, consuming the queued leases inside it;
        on any failure restore ``snapshot`` and spend nothing."""
        entries, consumes = list(self._pending or ()), list(self._consumes)

        def consume() -> None:
            for step in consumes:
                step()

        try:
            if entries:
                self._ledger.append_all(entries, before_commit=consume)
            else:
                consume()
        except OrchestratorError:
            self._restore(snapshot)
            raise
        except Exception as error:  # noqa: BLE001 - an unrecorded transition never stands
            self._restore(snapshot)
            kinds = ", ".join(entry["kind"] for entry in entries)
            raise OrchestratorError("LEDGER_UNAVAILABLE", f"the Run Ledger did not record the transition ({kinds})") from error

    def _caller(self, principal: object, context: object, at: datetime, run: AgentRun | None) -> _Caller:
        """The transport Principal bound to the Governed Context of the call (ADD v1.3 :388) and,
        within a run, to its version fence."""
        if not isinstance(principal, AuthenticatedPrincipal) or not isinstance(context, GovernedContext):
            raise _refuse("CAPABILITY_DENIED", "a coordination call requires the transport principal and its GovernedContext")
        try:
            principal.require_valid(at=at)
        except Exception as error:  # noqa: BLE001 - an invalid identity is never a pass
            raise _refuse("CAPABILITY_DENIED", f"the transport principal is not valid: {error}") from error
        agent = principal.principal_id
        if not (context.effective_principal_id == agent and context.actor_chain[-1] == agent and principal.actor_chain[-1] == agent):
            raise _refuse("CAPABILITY_DENIED", "the actor chain and the GovernedContext do not end in the transport principal")
        digest = context.digest()
        if run is not None:
            mapping = context.to_mapping()
            if any(mapping[name] != run.governed_context[name] for name in _FENCE_FIELDS):
                raise _refuse("STALE_CONTEXT", "the GovernedContext is outside the version fence of the run")
        return _Caller(principal=principal, context=context, digest=digest)

    def _lease(self, lease: object, capability: str, *, subject: str, resource: str, at: datetime, consume: bool = False) -> str:
        """The lease is checked where the call is admitted; with ``consume`` its use is queued and
        spent inside the Run Ledger transaction of the call (``_flush``), so a refused call, or one
        the ledger does not record, never spends a use of its lease."""
        if not isinstance(lease, (CapabilityLease, str)):
            raise _refuse("CAPABILITY_DENIED", f"{capability} requires a capability lease")

        def authorize(spend: bool) -> None:
            try:
                self._authority.authorize(lease, capability, resource, at=at, subject=subject, consume=spend)
            except Exception as error:  # noqa: BLE001 - a lease the authority does not admit never authorises
                raise _refuse("CAPABILITY_DENIED", str(error)) from error

        authorize(False)
        if consume:
            self._consumes.append(lambda: authorize(True))
        return lease.lease_id if isinstance(lease, CapabilityLease) else lease

    def _run(self, team_run_id: object, at: datetime) -> AgentRun:
        run = self._runs.get(team_run_id) if isinstance(team_run_id, str) else None
        if run is None:
            raise _refuse("UNKNOWN_RUN", f"no team run {team_run_id!r}")
        if run.status != "RUNNING":
            raise _refuse("RUN_TERMINATED", f"team run {run.team_run_id} is {run.status} ({run.termination_reason})")
        if at >= run.deadline:
            self._terminate(run, "TIMEOUT", at)
            raise _refuse("RUN_TERMINATED", f"team run {run.team_run_id} reached its timeout")
        return run

    def _terminate(self, run: AgentRun, reason: str, at: datetime) -> None:
        for task in list(self._tasks.values()):
            if task.team_run_id == run.team_run_id and task.state not in TERMINAL_STATES:
                self._transition(task, TaskState.EXPIRED, at, reason=reason)
        stopped = replace(run, status="TERMINATED", termination_reason=reason)
        self._runs[run.team_run_id] = stopped
        self._append(
            stopped,
            run.team_run_id,
            "RUN_TERMINATED",
            run.coordinator,
            {"reason": reason, "escalation_target": run.termination.escalation_target},
            at,
        )

    def _task(self, task_id: object) -> Task:
        task = self._tasks.get(task_id) if isinstance(task_id, str) else None
        if task is None:
            raise _refuse("UNKNOWN_TASK", f"no task {task_id!r}")
        return task

    def _live_task(self, task_id: object, at: datetime) -> tuple[AgentRun, Task]:
        task = self._task(task_id)
        run = self._run(task.team_run_id, at)
        if task.state not in TERMINAL_STATES and at >= task.deadline:
            self._transition(task, TaskState.EXPIRED, at, reason="TIMEOUT")
            raise _refuse("TASK_EXPIRED", f"task {task.task_id} reached its timeout")
        return run, task

    def _transition(self, task: Task, state: TaskState, at: datetime, *, agent_id: str | None = None, **changes: Any) -> Task:
        allowed = {
            TaskState.PROPOSED: {TaskState.POLICY_AUTHORIZED, TaskState.FAILED, TaskState.EXPIRED, TaskState.CANCELLED},
            TaskState.POLICY_AUTHORIZED: {TaskState.ACCEPTED, TaskState.FAILED, TaskState.EXPIRED, TaskState.CANCELLED},
            TaskState.ACCEPTED: {TaskState.ACCEPTED, *TERMINAL_STATES},
        }.get(task.state, set())
        if state not in allowed:
            raise _refuse("INVALID_TRANSITION", f"task {task.task_id}: {task.state.value} -> {state.value}")
        outcome_reason = changes.pop("reason", None)
        updated = replace(task, state=state, outcome_reason=outcome_reason, **changes)
        self._tasks[task.task_id] = updated
        if state in TERMINAL_STATES:
            run = self._runs[task.team_run_id]
            holder = self._commitments.get(task.task_id)
            actor = agent_id or (holder.agent_id if holder is not None else run.coordinator)
            self._append(
                run,
                task.task_id,
                f"TASK_{state.value}",
                actor,
                {"task_id": task.task_id, "attempt": task.attempt, "reason": outcome_reason, "output_digest": updated.output_digest},
                at,
            )
        return updated

    @staticmethod
    def _member(run: AgentRun, agent_id: str) -> TeamMember:
        for member in run.members:
            if member.binding.agent_principal_id == agent_id:
                return member
        raise _refuse("UNKNOWN_AGENT", f"{agent_id!r} is not a member of team run {run.team_run_id}")

    def _coordinator(self, run: AgentRun, call: _Caller, action: str) -> None:
        if call.agent_id != run.coordinator:
            raise _refuse("ROLE_FORBIDDEN", f"only the Coordinator may {action}")

    def _holder(self, task: Task, call: _Caller) -> Commitment:
        commitment = self._commitments.get(task.task_id)
        if commitment is None or task.state is not TaskState.ACCEPTED:
            raise _refuse("INVALID_TRANSITION", f"task {task.task_id} is {task.state.value}, not committed")
        if call.agent_id != commitment.agent_id:
            raise _refuse("CAPABILITY_DENIED", f"{call.agent_id!r} does not hold the commitment of {task.task_id}")
        return commitment

    def _charge_or_fail(self, task: Task, binding: AgentIdentityBinding, at: datetime) -> None:
        """FR-010 :62: an exhausted budget stops the task."""
        try:
            self._kernel.charge(binding, steps=1)
        except OrchestratorError:
            if task.state not in TERMINAL_STATES:
                self._transition(task, TaskState.FAILED, at, agent_id=binding.agent_principal_id, reason="BUDGET_EXCEEDED")
            raise

    # -- team run --------------------------------------------------------------------------------

    @_atomic
    def start_run(
        self,
        team_run_id: str,
        *,
        team_id: str,
        members: Sequence[TeamMember],
        termination: TerminationCondition,
        principal: AuthenticatedPrincipal,
        context: GovernedContext,
        at: datetime,
    ) -> AgentRun:
        instant = require_aware(at, field="at")
        _text("team_run_id", team_run_id)
        _text("team_id", team_id)
        if team_run_id in self._runs:
            raise _refuse("INVALID_TRANSITION", f"team run {team_run_id} already exists")
        if not isinstance(termination, TerminationCondition):
            raise _refuse("SCHEMA_VIOLATION", "a team run requires its TerminationCondition")
        if isinstance(members, (str, bytes)) or not isinstance(members, Sequence) or not members:
            raise _refuse("SCHEMA_VIOLATION", "a team run requires its members")
        call = self._caller(principal, context, instant, None)
        coordinators = []
        seen: dict[str, set[str]] = {"agent_principal_id": set(), "agent_run_id": set(), "workload_identity": set()}
        for member in members:
            if not isinstance(member, TeamMember) or not isinstance(member.role, AgentRole) or not isinstance(member.binding, AgentIdentityBinding):
                raise _refuse("SCHEMA_VIOLATION", "every member is a TeamMember with a role and an agent identity binding")
            binding = member.binding
            if binding.autonomy_tier not in POC_AUTONOMY_TIERS:
                raise _refuse("POLICY_DENIED", f"autonomy tier {binding.autonomy_tier} of {binding.agent_principal_id} is outside the PoC profile")
            if binding.team_id != team_id or binding.tenant_id != context.tenant_id:
                raise _refuse("CAPABILITY_DENIED", f"{binding.agent_principal_id} is bound to another team or tenant")
            # ADD v1.3 §4.3.1 invariant 1 (:3114): distinct identity per agent, instance and run
            for name, values in seen.items():
                value = getattr(binding, name)
                if value in values:
                    raise _refuse("CAPABILITY_DENIED", f"{name} {value!r} is shared by two members")
                values.add(value)
            if member.role is AgentRole.COORDINATOR:
                coordinators.append(binding.agent_principal_id)
        if len(coordinators) != 1:
            raise _refuse("SCHEMA_VIOLATION", "a team run has exactly one Coordinator")
        if call.agent_id != coordinators[0]:
            raise _refuse("ROLE_FORBIDDEN", "only the Coordinator of the team starts its run")
        self._kernel.stop_check()
        self._kernel.delegation(call.agent_id)
        self._kernel.decide(call.principal, call.context, call.digest, ACTIONS["start-run"], team_run_id, instant)
        run = AgentRun(
            team_run_id=team_run_id,
            team_id=team_id,
            tenant_id=context.tenant_id,
            coordinator=coordinators[0],
            members=tuple(members),
            termination=termination,
            governed_context=_frozen_mapping(context.to_mapping()),
            governed_context_digest=call.digest,
            started_at=instant,
            deadline=_deadline(instant, termination.timeout),
        )
        self._runs[team_run_id] = run
        self._append(
            run,
            team_run_id,
            "RUN_STARTED",
            call.agent_id,
            {
                "team_id": team_id,
                "members": [
                    {"agent_id": member.binding.agent_principal_id, "role": member.role, "agent_run_id": member.binding.agent_run_id,
                     "workload_identity": member.binding.workload_identity, "autonomy_tier": member.binding.autonomy_tier}
                    for member in members
                ],
                "termination": {
                    "max_delegation_depth": termination.max_delegation_depth,
                    "timeout": termination.timeout,
                    "max_attempts": termination.max_attempts,
                    "max_tasks": termination.max_tasks,
                    "escalation_target": termination.escalation_target,
                },
                "governed_context_digest": call.digest,
                "deadline": run.deadline,
            },
            instant,
        )
        return run

    # -- task graph ------------------------------------------------------------------------------

    def _has_cycle(self, run: AgentRun, logical_task_id: str, dependencies: tuple[str, ...]) -> bool:
        edges: dict[str, set[str]] = {}
        for task in self._tasks.values():
            if task.team_run_id == run.team_run_id:
                edges.setdefault(task.logical_task_id, set()).update(task.dependencies)
        edges.setdefault(logical_task_id, set()).update(dependencies)
        stack, seen = list(dependencies), set()
        while stack:
            node = stack.pop()
            if node == logical_task_id:
                return True
            if node not in seen:
                seen.add(node)
                stack.extend(edges.get(node, ()))
        return False

    @_atomic
    def propose_task(
        self,
        team_run_id: str,
        task_id: str,
        *,
        role: AgentRole,
        output_type: str,
        autonomy_tier: str,
        timeout: timedelta,
        principal: AuthenticatedPrincipal,
        context: GovernedContext,
        at: datetime,
        dependencies: Sequence[str] = (),
        parent_task_id: str | None = None,
        logical_task_id: str | None = None,
    ) -> Task:
        instant = require_aware(at, field="at")
        run = self._run(team_run_id, instant)
        call = self._caller(principal, context, instant, run)
        _text("task_id", task_id)
        logical = task_id if logical_task_id is None else _text("logical_task_id", logical_task_id)
        if task_id in self._tasks or any(task.logical_task_id == logical for task in self._tasks.values() if task.team_run_id == run.team_run_id):
            raise _refuse("INVALID_TRANSITION", f"task {task_id} already exists; a new attempt is a retry")
        parent = None if parent_task_id is None else self._task(parent_task_id)
        if parent is None:
            self._coordinator(run, call, "propose a task")
        else:
            holder = self._commitments.get(parent.task_id)
            if parent.team_run_id != run.team_run_id:
                raise _refuse("UNKNOWN_TASK", f"parent task {parent.task_id} belongs to another run")
            if call.agent_id != run.coordinator and (holder is None or holder.agent_id != call.agent_id):
                raise _refuse("ROLE_FORBIDDEN", "only the Coordinator or the holder of the parent task delegates a subtask")
        if not isinstance(role, AgentRole):
            raise _refuse("SCHEMA_VIOLATION", "role must be an AgentRole")
        if output_type not in ROLE_OUTPUTS[role]:
            raise _refuse("ROLE_OUTPUT_FORBIDDEN", f"{output_type!r} is not a typed output of the {role.value} role")
        self._kernel.contract(output_type)
        if autonomy_tier not in POC_AUTONOMY_TIERS:
            raise _refuse("POLICY_DENIED", f"autonomy tier {autonomy_tier!r} is outside the PoC profile")
        if not isinstance(timeout, timedelta) or timeout <= timedelta(0):
            raise _refuse("SCHEMA_VIOLATION", "timeout must be a positive timedelta")
        depends = _texts("dependencies", dependencies)
        tasks = sum(1 for task in self._tasks.values() if task.team_run_id == run.team_run_id)
        if tasks >= run.termination.max_tasks:
            raise _refuse("TERMINATION_CONDITION_MET", f"team run {run.team_run_id} reached its limit of {run.termination.max_tasks} tasks")
        depth = 0 if parent is None else parent.delegation_depth + 1
        if depth > run.termination.max_delegation_depth:
            raise _refuse("DELEGATION_DEPTH_EXCEEDED", f"delegation depth {depth} exceeds {run.termination.max_delegation_depth}")
        if self._has_cycle(run, logical, depends):
            raise _refuse("TASK_CYCLE_DETECTED", f"task {logical} closes a dependency cycle")
        deadline = min(_deadline(instant, timeout), run.deadline)
        self._kernel.stop_check()
        self._kernel.decide(call.principal, call.context, call.digest, ACTIONS["propose-task"], task_id, instant)
        task = Task(
            task_id=task_id,
            logical_task_id=logical,
            attempt=1,
            team_run_id=run.team_run_id,
            role=role,
            output_type=output_type,
            autonomy_tier=autonomy_tier,
            dependencies=depends,
            parent_task_id=None if parent is None else parent.task_id,
            delegation_depth=depth,
            timeout=timeout,
            deadline=deadline,
            proposed_by=call.agent_id,
            proposed_at=instant,
        )
        self._record_proposal(run, task, instant)
        return task

    def _record_proposal(self, run: AgentRun, task: Task, at: datetime) -> None:
        self._tasks[task.task_id] = task
        self._append(
            run,
            run.team_run_id,
            "TASK_PROPOSED",
            task.proposed_by,
            {name: getattr(task, name) for name in ("task_id", "logical_task_id", "attempt", "role", "output_type", "autonomy_tier",
                                                    "dependencies", "parent_task_id", "delegation_depth", "deadline")},
            at,
        )

    @_atomic
    def retry(self, task_id: str, *, principal: AuthenticatedPrincipal, context: GovernedContext, at: datetime) -> Task:
        instant = require_aware(at, field="at")
        task = self._task(task_id)
        run = self._run(task.team_run_id, instant)
        call = self._caller(principal, context, instant, run)
        self._coordinator(run, call, "retry a task")
        latest = max((item for item in self._tasks.values() if item.logical_task_id == task.logical_task_id and item.team_run_id == run.team_run_id),
                     key=lambda item: item.attempt)
        if task.state not in RETRYABLE_STATES or latest.task_id != task.task_id:
            raise _refuse("INVALID_TRANSITION", f"task {task.task_id} is not the failed or expired latest attempt")
        attempt = task.attempt + 1
        if attempt > run.termination.max_attempts:
            raise _refuse("TERMINATION_CONDITION_MET", f"task {task.logical_task_id} reached its limit of {run.termination.max_attempts} attempts")
        if sum(1 for item in self._tasks.values() if item.team_run_id == run.team_run_id) >= run.termination.max_tasks:
            raise _refuse("TERMINATION_CONDITION_MET", f"team run {run.team_run_id} reached its task limit")
        retried_id = f"{task.logical_task_id}#attempt-{attempt}"
        if retried_id in self._tasks:
            raise _refuse("INVALID_TRANSITION", f"task {retried_id} already exists; the retry would overwrite it")
        self._kernel.stop_check()
        self._kernel.decide(call.principal, call.context, call.digest, ACTIONS["retry"], task.task_id, instant)
        retried = replace(
            task,
            task_id=retried_id,
            attempt=attempt,
            state=TaskState.PROPOSED,
            deadline=min(_deadline(instant, task.timeout), run.deadline),
            proposed_by=call.agent_id,
            proposed_at=instant,
            output_digest=None,
            evidence_refs=(),
            outcome_reason=None,
        )
        self._record_proposal(run, retried, instant)
        return retried

    # -- assignment and commitment ---------------------------------------------------------------

    @_atomic
    def assign(
        self,
        task_id: str,
        agent_id: str,
        *,
        capability: str,
        lease: CapabilityLease | str,
        assigned_by: str,
        principal: AuthenticatedPrincipal,
        context: GovernedContext,
        at: datetime,
    ) -> Assignment:
        instant = require_aware(at, field="at")
        run, task = self._live_task(task_id, instant)
        self._kernel.stop_check()
        call = self._caller(principal, context, instant, run)
        if call.agent_id != assigned_by:
            raise _refuse("CAPABILITY_DENIED", "the assigner is not the transport principal")
        _text("capability", capability)
        self._lease(lease, "agent:assign", subject=assigned_by, resource=agent_id, at=instant)
        parent_holder = None if task.parent_task_id is None else self._commitments.get(task.parent_task_id)
        if call.agent_id != run.coordinator and (parent_holder is None or parent_holder.agent_id != call.agent_id):
            raise _refuse("ROLE_FORBIDDEN", "only the Coordinator, or the holder of the parent task, assigns")
        if task.state is not TaskState.PROPOSED:
            raise _refuse("INVALID_TRANSITION", f"task {task.task_id} is {task.state.value}")
        for dependency in task.dependencies:
            if not any(item.logical_task_id == dependency and item.state is TaskState.COMPLETED for item in self._tasks.values()
                       if item.team_run_id == run.team_run_id):
                raise _refuse("DEPENDENCY_PENDING", f"task {task.task_id} depends on {dependency}, not completed")
        member = self._member(run, agent_id)
        if member.role is not task.role:
            raise _refuse("ROLE_MISMATCH", f"{agent_id} is {member.role.value}, task {task.task_id} needs {task.role.value}")
        binding = member.binding
        delegation = self._kernel.delegation(agent_id)
        if _TIER_RANK.get(binding.autonomy_tier, -1) < _TIER_RANK[task.autonomy_tier]:
            raise _refuse("POLICY_DENIED", f"autonomy tier {binding.autonomy_tier} of {agent_id} is below {task.autonomy_tier}")
        decision = self._kernel.decide(call.principal, call.context, call.digest, ACTIONS["assign"], task.task_id, instant)
        self._charge_or_fail(task, binding, instant)
        assignment = Assignment(
            assignment_id=f"urn:ocor:c8:assignment:{uuid.uuid4()}",
            task_id=task.task_id,
            agent_id=agent_id,
            capability=capability,
            assigned_by=assigned_by,
            assigned_at=instant,
            agent_run_id=binding.agent_run_id,
            workload_identity=binding.workload_identity,
            delegation_ref=delegation,
            autonomy_tier=binding.autonomy_tier,
            policy_decision_id=decision,
        )
        self._lease(lease, "agent:assign", subject=assigned_by, resource=agent_id, at=instant, consume=True)
        self._append(run, task.task_id, "TASK_ASSIGNED", agent_id, {name: getattr(assignment, name) for name in Assignment.__dataclass_fields__}, instant)
        self._transition(task, TaskState.POLICY_AUTHORIZED, instant)
        self._assignments[task.task_id] = assignment
        return assignment

    @_atomic
    def commit(self, task_id: str, *, lease: CapabilityLease | str, principal: AuthenticatedPrincipal, context: GovernedContext, at: datetime) -> Commitment:
        instant = require_aware(at, field="at")
        run, task = self._live_task(task_id, instant)
        assignment = self._assignments.get(task.task_id)
        if assignment is None:
            raise _refuse("UNKNOWN_TASK", f"no assignment for {task.task_id!r}")
        if task.state not in (TaskState.POLICY_AUTHORIZED, TaskState.ACCEPTED):
            raise _refuse("INVALID_TRANSITION", f"task {task.task_id} is {task.state.value}")
        self._kernel.stop_check()
        call = self._caller(principal, context, instant, run)
        if call.agent_id != assignment.agent_id:
            raise _refuse("CAPABILITY_DENIED", f"{call.agent_id!r} is not the assignee of {task.task_id}")
        self._lease(lease, "agent:commit", subject=assignment.agent_id, resource=assignment.agent_id, at=instant)
        member = self._member(run, assignment.agent_id)
        self._kernel.delegation(assignment.agent_id)
        self._kernel.decide(call.principal, call.context, call.digest, ACTIONS["commit"], task.task_id, instant)
        self._charge_or_fail(task, member.binding, instant)
        commitment = Commitment(
            commitment_id=f"urn:ocor:c8:commitment:{uuid.uuid4()}",
            task_id=task.task_id,
            agent_id=assignment.agent_id,
            assignment_id=assignment.assignment_id,
            committed_at=instant,
        )
        self._lease(lease, "agent:commit", subject=assignment.agent_id, resource=assignment.agent_id, at=instant, consume=True)
        self._append(run, task.task_id, "TASK_COMMITTED", assignment.agent_id, {name: getattr(commitment, name) for name in Commitment.__dataclass_fields__}, instant)
        self._transition(task, TaskState.ACCEPTED, instant)
        self._commitments[task.task_id] = commitment
        return commitment

    # -- handoff (ADD v1.3 :3068-3098, :388) -------------------------------------------------------

    @_atomic
    def handoff(
        self,
        task_id: str,
        *,
        sender: str,
        to_agent_id: str,
        reason: str,
        payload: Mapping[str, Any],
        lease: CapabilityLease | str,
        principal: AuthenticatedPrincipal,
        context: GovernedContext,
        at: datetime,
        evidence_refs: Sequence[str] = (),
        provenance_refs: Sequence[str] = (),
    ) -> HandoffEnvelope:
        instant = require_aware(at, field="at")
        run, task = self._live_task(task_id, instant)
        handoff_id = f"urn:ocor:c8:handoff:{uuid.uuid4()}"
        try:
            commitment = self._commitments.get(task.task_id)
            if commitment is None or task.state is not TaskState.ACCEPTED:
                raise _refuse("UNKNOWN_TASK", f"no commitment for {task.task_id!r}")
            if not isinstance(reason, str) or not reason:
                raise _refuse("HANDOFF_REASON_REQUIRED", "a handoff requires an explicit reason")
            return self._handoff(run, task, commitment, handoff_id, sender, to_agent_id, reason, payload, lease, principal, context, instant,
                                 evidence_refs, provenance_refs)
        except OrchestratorError as error:
            # every refused handoff is a REJECTED envelope and a DENIED audit record
            self._reject_handoff(run, task, handoff_id, sender, to_agent_id, principal, context, lease, payload, error, instant)
            raise

    def _handoff(
        self,
        run: AgentRun,
        task: Task,
        commitment: Commitment,
        handoff_id: str,
        sender: object,
        to_agent_id: object,
        reason: str,
        payload: object,
        lease: object,
        principal: object,
        context: object,
        instant: datetime,
        evidence_refs: object,
        provenance_refs: object,
    ) -> HandoffEnvelope:
        self._kernel.stop_check()
        if sender != commitment.agent_id:
            raise _refuse("CAPABILITY_DENIED", f"the declared sender {sender!r} does not hold the commitment of {task.task_id}")
        call = self._caller(principal, context, instant, run)
        if call.agent_id != sender:
            raise _refuse("CAPABILITY_DENIED", "the declared handoff sender is not the transport principal")
        recipient_id = _text("to_agent_id", to_agent_id)
        evidence = _texts("evidence_refs", evidence_refs)
        provenance = _texts("provenance_refs", provenance_refs)
        authority_ref = self._lease(lease, "agent:handoff", subject=commitment.agent_id, resource=recipient_id, at=instant)
        recipient = self._member(run, recipient_id)
        if recipient_id == commitment.agent_id:
            raise _refuse("INVALID_TRANSITION", "a handoff moves the commitment to another agent")
        if recipient.role is not task.role:
            raise _refuse("ROLE_MISMATCH", f"{recipient_id} is {recipient.role.value}, task {task.task_id} needs {task.role.value}")
        delegation = self._kernel.delegation(commitment.agent_id)
        self._kernel.delegation(recipient_id)
        self._kernel.check_marking(call.context, recipient_id)
        if _TIER_RANK.get(recipient.binding.autonomy_tier, -1) < _TIER_RANK[task.autonomy_tier]:
            raise _refuse("POLICY_DENIED", f"autonomy tier of {recipient_id} is below {task.autonomy_tier}")
        contract = self._kernel.handoff_contract
        payload_digest = self._kernel.validated_digest(contract, payload)
        expires_at = min(task.deadline, instant + HANDOFF_TTL)
        if expires_at <= instant:
            raise _refuse("TASK_EXPIRED", f"task {task.task_id} expires before the handoff")
        self._kernel.decide(call.principal, call.context, call.digest, ACTIONS["handoff"], task.task_id, instant)
        sender_member = self._member(run, commitment.agent_id)
        self._charge_or_fail(task, recipient.binding, instant)
        previous = next((item for item in reversed(self._handoffs) if item.task_id == task.task_id), None)
        assignment = self._assignments[task.task_id]
        unsigned = HandoffEnvelope(
            handoff_id=handoff_id,
            team_run_id=run.team_run_id,
            task_id=task.task_id,
            assignment_id=assignment.assignment_id,
            parent_handoff_id=None if previous is None else previous.handoff_id,
            asserted_sender_principal=commitment.agent_id,
            recipient_principal=recipient_id,
            contract_id=contract.contract_id,
            contract_version=contract.contract_version,
            speech_act="HANDOFF",
            payload_ref=f"urn:ocor:c8:handoff-payload:{payload_digest.rsplit(':', 1)[1]}",
            payload_digest=payload_digest,
            evidence_refs=evidence,
            provenance_refs=provenance,
            taint_labels=MESSAGE_TAINT,
            baseline_ref=BASELINE_REF,
            governed_context=_frozen_mapping(call.context.to_mapping()),
            governed_context_digest=call.digest,
            ontology_release_digest=call.context.ontology_release_digest,
            model_digest=None,
            delegation_ref=delegation,
            effective_authority_ref=authority_ref,
            correlation_id=call.context.correlation_id,
            causation_id=assignment.assignment_id if previous is None else previous.handoff_id,
            created_at=instant,
            expires_at=expires_at,
            budget_remaining=self._kernel.remaining(sender_member.binding),
            signature_ref="",
            status="ACCEPTED",
            rejection_reason=None,
        )
        envelope = replace(unsigned, signature_ref=self._kernel.sign(unsigned))
        self._lease(lease, "agent:handoff", subject=commitment.agent_id, resource=recipient_id, at=instant, consume=True)
        self._append(
            run,
            task.task_id,
            "TASK_HANDED_OFF",
            recipient_id,
            {**{name: getattr(envelope, name) for name in HandoffEnvelope.__dataclass_fields__}, "reason": reason},
            instant,
        )
        self._handoffs.append(envelope)
        self._assignments[task.task_id] = replace(
            assignment,
            agent_id=recipient_id,
            agent_run_id=recipient.binding.agent_run_id,
            workload_identity=recipient.binding.workload_identity,
            delegation_ref=self._kernel.delegation(recipient_id),
            autonomy_tier=recipient.binding.autonomy_tier,
        )
        self._commitments[task.task_id] = replace(commitment, agent_id=recipient_id, committed_at=instant)
        return envelope

    def _reject_handoff(
        self,
        run: AgentRun,
        task: Task,
        handoff_id: str,
        sender: object,
        to_agent_id: object,
        principal: object,
        context: object,
        lease: object,
        payload: object,
        error: OrchestratorError,
        instant: datetime,
    ) -> None:
        """A refused handoff is a REJECTED envelope in the Run Ledger and a DENIED audit record. It
        keeps what LLD v1.1 :183 requires of a Handoff -- sender, recipient, schema (contract),
        payload reference, Governed Context digest and status -- as far as the refused call carries
        them: a payload that cannot be digested, or a context that is not a GovernedContext, is
        recorded as absent (``None``), never converted."""
        actor = principal.principal_id if isinstance(principal, AuthenticatedPrincipal) else "urn:ocor:c8:unauthenticated"
        gcs = context if isinstance(context, GovernedContext) else None
        try:
            payload_digest: str | None = canonical_digest(dict(payload)) if isinstance(payload, Mapping) else None
        except Exception:  # noqa: BLE001 - a payload that is not I-JSON has no digest to record
            payload_digest = None
        assignment = self._assignments.get(task.task_id)
        contract = self._kernel.handoff_contract
        detail = {
            "team_run_id": run.team_run_id,
            "handoff_id": handoff_id,
            "assignment_id": None if assignment is None else assignment.assignment_id,
            "asserted_sender_principal": sender if isinstance(sender, str) else None,
            "recipient_principal": to_agent_id if isinstance(to_agent_id, str) else None,
            "contract_id": contract.contract_id,
            "contract_version": contract.contract_version,
            "speech_act": "HANDOFF",
            "payload_digest": payload_digest,
            "payload_ref": None if payload_digest is None else f"urn:ocor:c8:handoff-payload:{payload_digest.rsplit(':', 1)[1]}",
            "governed_context_digest": None if gcs is None else gcs.digest(),
            "correlation_id": run.team_run_id if gcs is None else gcs.correlation_id,
            "created_at": format_utc_timestamp(instant),
            "status": "REJECTED",
            "rejection_reason": error.reason_code,
        }
        self._append(run, task.task_id, "HANDOFF_REJECTED", actor, {**detail, "task_id": task.task_id}, instant)
        lease_ref = lease.lease_id if isinstance(lease, CapabilityLease) else lease if isinstance(lease, str) and lease else "urn:ocor:c8:no-lease"
        try:
            self._kernel.audit.append(
                AuditEvent(
                    event_type="C8_HANDOFF_REJECTED",
                    actor=actor,
                    occurred_at=instant,
                    resource=task.task_id,
                    reason_code=error.reason_code,
                    authority_ref=lease_ref,
                    correlation_id=run.team_run_id if gcs is None else gcs.correlation_id,
                    outcome="DENIED",
                    governed_context=None if gcs is None else gcs.to_mapping(),
                    governed_context_digest=None if gcs is None else gcs.digest(),
                    detail=detail,
                )
            )
        except Exception as audit_error:  # noqa: BLE001 - the refusal stands; an unaudited refusal is reported
            raise _refuse("AUDIT_UNAVAILABLE", f"the rejected handoff {handoff_id} could not be audited") from audit_error

    # -- outcomes ------------------------------------------------------------------------------------

    @_atomic
    def complete(
        self,
        task_id: str,
        *,
        output: Mapping[str, Any],
        evidence_refs: Sequence[str],
        principal: AuthenticatedPrincipal,
        context: GovernedContext,
        at: datetime,
    ) -> Task:
        instant = require_aware(at, field="at")
        run, task = self._live_task(task_id, instant)
        self._kernel.stop_check()
        call = self._caller(principal, context, instant, run)
        commitment = self._holder(task, call)
        evidence = _texts("evidence_refs", evidence_refs, required=True)
        digest = self._kernel.validated_digest(self._kernel.contract(task.output_type), output)
        self._kernel.delegation(commitment.agent_id)
        self._kernel.decide(call.principal, call.context, call.digest, ACTIONS["complete"], task.task_id, instant)
        self._charge_or_fail(task, self._member(run, commitment.agent_id).binding, instant)
        return self._transition(task, TaskState.COMPLETED, instant, output_digest=digest, evidence_refs=evidence)

    def _close(self, task_id: str, state: TaskState, action: str, reason: str, principal: object, context: object, at: datetime) -> Task:
        instant = require_aware(at, field="at")
        run, task = self._live_task(task_id, instant)
        call = self._caller(principal, context, instant, run)
        _text("reason", reason)
        if state is TaskState.CANCELLED:
            self._coordinator(run, call, "cancel a task")
            if task.state in TERMINAL_STATES:
                raise _refuse("INVALID_TRANSITION", f"task {task.task_id} is {task.state.value}")
        else:
            self._holder(task, call)
        self._kernel.decide(call.principal, call.context, call.digest, ACTIONS[action], task.task_id, instant)
        return self._transition(task, state, instant, agent_id=call.agent_id, reason=reason)

    @_atomic
    def abstain(self, task_id: str, *, reason: str, principal: AuthenticatedPrincipal, context: GovernedContext, at: datetime) -> Task:
        return self._close(task_id, TaskState.ABSTAINED, "abstain", reason, principal, context, at)

    @_atomic
    def fail(self, task_id: str, *, reason: str, principal: AuthenticatedPrincipal, context: GovernedContext, at: datetime) -> Task:
        return self._close(task_id, TaskState.FAILED, "fail", reason, principal, context, at)

    @_atomic
    def cancel(self, task_id: str, *, reason: str, principal: AuthenticatedPrincipal, context: GovernedContext, at: datetime) -> Task:
        return self._close(task_id, TaskState.CANCELLED, "cancel", reason, principal, context, at)

    # -- dissent and decision proposal -------------------------------------------------------------

    @_atomic
    def register_dissent(
        self,
        task_id: str,
        agent_id: str,
        *,
        reason: str,
        severity: DissentSeverity,
        category: DissentCategory,
        lease: CapabilityLease | str,
        principal: AuthenticatedPrincipal,
        context: GovernedContext,
        at: datetime,
    ) -> Dissent:
        instant = require_aware(at, field="at")
        task = self._task(task_id)
        run = self._run(task.team_run_id, instant)
        if not isinstance(reason, str) or not reason.strip():
            raise _refuse("DISSENT_REASON_REQUIRED", "a dissent requires an explicit reason")
        _text("reason", reason)
        if not isinstance(severity, DissentSeverity) or not isinstance(category, DissentCategory):
            raise _refuse("SCHEMA_VIOLATION", "a dissent carries its severity and category")
        self._kernel.stop_check()
        call = self._caller(principal, context, instant, run)
        if call.agent_id != agent_id:
            raise _refuse("CAPABILITY_DENIED", "the dissenting agent is not the transport principal")
        self._lease(lease, "agent:dissent", subject=agent_id, resource=agent_id, at=instant)
        self._member(run, agent_id)
        self._kernel.decide(call.principal, call.context, call.digest, ACTIONS["dissent"], task.task_id, instant)
        record = Dissent(
            dissent_id=f"urn:ocor:c8:dissent:{uuid.uuid4()}",
            team_run_id=run.team_run_id,
            task_id=task.task_id,
            agent_id=agent_id,
            reason=reason,
            severity=severity,
            category=category,
            registered_at=instant,
        )
        self._lease(lease, "agent:dissent", subject=agent_id, resource=agent_id, at=instant, consume=True)
        self._append(run, task.task_id, "DISSENT_REGISTERED", agent_id, {name: getattr(record, name) for name in Dissent.__dataclass_fields__}, instant)
        self._dissents.append(record)
        return record

    @_atomic
    def resolve_dissent(
        self, dissent_id: str, *, resolution: str, principal: AuthenticatedPrincipal, context: GovernedContext, at: datetime
    ) -> DissentResolution:
        instant = require_aware(at, field="at")
        dissent = next((item for item in self._dissents if item.dissent_id == dissent_id), None)
        if dissent is None:
            raise _refuse("UNKNOWN_DISSENT", f"no dissent {dissent_id!r}")
        run = self._run(dissent.team_run_id, instant)
        call = self._caller(principal, context, instant, run)
        _text("resolution", resolution)
        if dissent.dissent_id in self._resolutions:
            raise _refuse("INVALID_TRANSITION", f"dissent {dissent.dissent_id} is already resolved")
        # the Coordinator never resolves or suppresses a dissent (ADD v1.3 :3064, :3120)
        if call.agent_id not in (dissent.agent_id, run.termination.escalation_target):
            raise _refuse("ROLE_FORBIDDEN", "a dissent is resolved only by its author or the escalation target")
        self._kernel.decide(call.principal, call.context, call.digest, ACTIONS["resolve-dissent"], dissent.dissent_id, instant)
        record = DissentResolution(
            resolution_id=f"urn:ocor:c8:dissent-resolution:{uuid.uuid4()}",
            dissent_id=dissent.dissent_id,
            resolved_by=call.agent_id,
            resolution=resolution,
            resolved_at=instant,
        )
        self._append(run, dissent.task_id, "DISSENT_RESOLVED", call.agent_id, {name: getattr(record, name) for name in DissentResolution.__dataclass_fields__}, instant)
        self._resolutions[dissent.dissent_id] = record
        return record

    @_atomic
    def propose_decision(
        self,
        team_run_id: str,
        *,
        impact: ProposalImpact,
        alternatives: Sequence[str],
        assumptions: Sequence[str],
        uncertainty: str,
        provenance_refs: Sequence[str],
        principal: AuthenticatedPrincipal,
        context: GovernedContext,
        at: datetime,
    ) -> DecisionProposal:
        instant = require_aware(at, field="at")
        run = self._run(team_run_id, instant)
        self._kernel.stop_check()
        call = self._caller(principal, context, instant, run)
        self._coordinator(run, call, "propose a decision")
        if not isinstance(impact, ProposalImpact):
            raise _refuse("SCHEMA_VIOLATION", "impact must be a ProposalImpact")
        options = _texts("alternatives", alternatives, required=True)
        assumed = _texts("assumptions", assumptions)
        provenance = _texts("provenance_refs", provenance_refs, required=True)
        _text("uncertainty", uncertainty)
        unresolved = [item for item in self._dissents if item.team_run_id == run.team_run_id and item.dissent_id not in self._resolutions]
        blocking = [item for item in unresolved if item.severity is DissentSeverity.CRITICAL and item.category in BLOCKING_CATEGORIES]
        if impact is ProposalImpact.HIGH_IMPACT and blocking:
            raise _refuse("CRITICAL_DISSENT_BLOCKS", f"unresolved Critical dissent {blocking[0].dissent_id} blocks a High-Impact proposal")
        decision = self._kernel.decide(call.principal, call.context, call.digest, ACTIONS["propose-decision"], run.team_run_id, instant)
        proposal = DecisionProposal(
            proposal_id=f"urn:ocor:c8:decision-proposal:{uuid.uuid4()}",
            team_run_id=run.team_run_id,
            impact=impact,
            alternatives=options,
            assumptions=assumed,
            uncertainty=uncertainty,
            abstentions=tuple(task.task_id for task in self._tasks.values() if task.team_run_id == run.team_run_id and task.state is TaskState.ABSTAINED),
            dissent_ids=tuple(item.dissent_id for item in unresolved),
            provenance_refs=provenance,
            proposed_by=call.agent_id,
            proposed_at=instant,
        )
        self._append(
            run,
            run.team_run_id,
            "DECISION_PROPOSED",
            call.agent_id,
            {**{name: getattr(proposal, name) for name in DecisionProposal.__dataclass_fields__}, "policy_decision_id": decision},
            instant,
        )
        self._proposals.append(proposal)
        return proposal

    # -- tainted communication and tool invocations ------------------------------------------------

    @_atomic
    def send_message(
        self,
        team_run_id: str,
        *,
        recipient: str,
        speech_act: str,
        payload: Mapping[str, Any],
        principal: AuthenticatedPrincipal,
        context: GovernedContext,
        at: datetime,
    ) -> Message:
        """A tainted message between members, through the Kernel: it is recorded and changes nothing."""
        instant = require_aware(at, field="at")
        run = self._run(team_run_id, instant)
        self._kernel.stop_check()
        call = self._caller(principal, context, instant, run)
        self._member(run, call.agent_id)
        self._member(run, _text("recipient", recipient))
        if speech_act not in SPEECH_ACTS:
            raise _refuse("SCHEMA_VIOLATION", f"speech act must be one of {SPEECH_ACTS}")
        if not isinstance(payload, Mapping):
            raise _refuse("SCHEMA_VIOLATION", "a message payload is an object")
        try:
            digest = canonical_digest(dict(payload))
        except Exception as error:  # noqa: BLE001 - a payload that cannot be digested is never sent
            raise _refuse("SCHEMA_VIOLATION", "a message payload is canonical I-JSON") from error
        self._kernel.decide(call.principal, call.context, call.digest, ACTIONS["message"], run.team_run_id, instant)
        message = Message(
            message_id=f"urn:ocor:c8:message:{uuid.uuid4()}",
            team_run_id=run.team_run_id,
            sender=call.agent_id,
            recipient=recipient,
            speech_act=speech_act,
            payload_digest=digest,
            sent_at=instant,
        )
        self._append(run, run.team_run_id, "MESSAGE_SENT", call.agent_id, {name: getattr(message, name) for name in Message.__dataclass_fields__}, instant)
        self._messages.append(message)
        return message

    @_atomic
    def record_tool_invocation(
        self, task_id: str, receipt: ToolCallReceipt, *, principal: AuthenticatedPrincipal, context: GovernedContext, at: datetime
    ) -> ToolInvocation:
        instant = require_aware(at, field="at")
        run, task = self._live_task(task_id, instant)
        call = self._caller(principal, context, instant, run)
        commitment = self._holder(task, call)
        if not isinstance(receipt, ToolCallReceipt):
            raise _refuse("SCHEMA_VIOLATION", "a tool invocation is recorded from the receipt of the governed tool runtime")
        _text("tool_name", receipt.tool_name)
        _text("lease_id", receipt.lease_id)
        if not isinstance(receipt.invocations, tuple) or not receipt.invocations or any(not isinstance(item, ToolOutput) for item in receipt.invocations):
            raise _refuse("SCHEMA_VIOLATION", "the receipt carries the contract invocations of the governed tool runtime")
        for item in receipt.invocations:
            try:
                verified_tool_output(item)
            except Exception as error:  # noqa: BLE001 - an invocation that is not well formed is never recorded
                raise _refuse("SCHEMA_VIOLATION", f"a contract invocation of the receipt is malformed: {error}") from error
        decisions = receipt.policy_decision_ids
        if not isinstance(decisions, tuple) or not decisions or any(not isinstance(item, str) or not item for item in decisions):
            raise _refuse("SCHEMA_VIOLATION", "the receipt carries the policy decisions of the call")
        binding = self._member(run, commitment.agent_id).binding
        if (receipt.agent_principal_id, receipt.agent_run_id, receipt.workload_identity) != (
            binding.agent_principal_id,
            binding.agent_run_id,
            binding.workload_identity,
        ):
            raise _refuse("CAPABILITY_DENIED", "the receipt belongs to another agent run")
        self._kernel.decide(call.principal, call.context, call.digest, ACTIONS["record-tool-invocation"], task.task_id, instant)
        record = ToolInvocation(
            invocation_id=f"urn:ocor:c8:tool-invocation:{uuid.uuid4()}",
            team_run_id=run.team_run_id,
            task_id=task.task_id,
            agent_principal_id=receipt.agent_principal_id,
            agent_run_id=receipt.agent_run_id,
            tool_name=receipt.tool_name,
            lease_id=receipt.lease_id,
            contract_ids=tuple(item.contract_id for item in receipt.invocations),
            input_digests=tuple(item.input_digest for item in receipt.invocations),
            output_digests=tuple(item.output_digest for item in receipt.invocations),
            policy_decision_ids=tuple(receipt.policy_decision_ids),
            # tool output is always untrusted (ADD v1.3 :339, :3117): the taint is never the caller's
            taint_labels=UNTRUSTED_TOOL_OUTPUT_TAINT,
            recorded_at=instant,
        )
        self._append(run, task.task_id, "TOOL_INVOKED", call.agent_id, {name: getattr(record, name) for name in ToolInvocation.__dataclass_fields__}, instant)
        return record
