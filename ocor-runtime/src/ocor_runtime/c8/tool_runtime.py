"""C8 -- governed tool runtime: Tool Contracts, live re-evaluation, budgets and kill switch.

OCOR-DEV-REM-0058 (NCP-U10; register entries NCR-C8-004, 005, 007 and 008) rebuilds the runtime of
OCOR-DEV-0047/REM-0027 on the normative C8 elements. A tool call is an expression evaluated by the
legacy ``StrictSandbox`` (unchanged), whose only callables are the allow-listed, contract-bound
tools of a ``ToolRegistry`` (``mcp-tool-contract:1.2``, ADD v1.3 :1589-1985): arguments are bound
and validated against the pinned input schema and the named preconditions before the adapter runs,
egress is confined to the binding allow-list while it runs, and the output is schema-validated,
digested and tainted ``TOOL_OUTPUT``/``UNTRUSTED`` after it (FR-127 :277, ADD v1.3 :3117).

Live re-evaluation (ADD v1.3 Part II §2.12 :3856; §5.2 rule 5 :3220; FR-162 :404). For the call,
for each tool the expression names (before anything is charged) and again immediately before each
dispatch, the runtime reads, as recorded now and whatever instant the caller presents:

* the signed stop epoch (``StopEpochReader``): an active stop, or a grant of another epoch, is
  ``EMERGENCY_STOP_ACTIVE`` -- checked first, so a stop that also revokes stays a stop;
* the C8 tool grant and every grant of its delegation chain (``ToolGrantLedger``, the bounded
  task-claim lease of LLD v1.1 :358): a revocation anywhere in the chain is ``CAPABILITY_REVOKED``
  (OCOR-DEV-REM-0043 correction, FGM-17, NFR-036 :271); a grant of another agent or run, a tool
  outside the grant or an instant outside its window is ``CAPABILITY_DENIED``;
* the verified Delegation of the agent principal (``GovernanceControlPort``): withdrawn or revoked
  is ``CAPABILITY_REVOKED``, another Delegation is ``CAPABILITY_DENIED``;
* the Authority named by the grant, validated with ``kernel.governance.validate_authority`` (signed,
  not revoked, bound to the verified Delegation and Governed Context, capability, scope, purpose and
  risk in scope): no valid Authority is ``AUTHORITY_MISSING``, a revoked one ``CAPABILITY_REVOKED``,
  one that does not contain the request ``CAPABILITY_DENIED``;
* the autonomy tier of the agent binding (ADD v1.3 :3115, FR-110 :258): outside the PoC tiers
  ``OBSERVE``/``ANALYZE``/``SIMULATE``/``PROPOSE`` or the contract's ``allowed_autonomy_tiers`` is
  ``POLICY_DENIED``;
* the memory instruction eligibility of the agent run (``InstructionEligibilityPort``): anything
  but an explicit ``True`` is ``POLICY_DENIED``;
* the policy decision (``security.ports.PolicyDecisionPort``, OPA in the product), verified against
  the request and applied with ``PolicyDecision.admit``: ``DENY`` or an unavailable decision point
  is ``POLICY_DENIED``, ``REQUIRE_APPROVAL`` is ``APPROVAL_REQUIRED``.

Agent identity (ADD v1.3 §5.1 :3140, FR-004 :47): every call presents an ``AgentIdentityBinding``
(agent principal, run, workload identity, owner, autonomy tier, agent version, team, tenant) that
must match the authenticated principal and the Governed Context; the Governed Context digest is
recomputed and must be the one the registry is bound to (``STALE_CONTEXT``). The receipt records
agent, run, version, workload identity, tier, Delegation and delegator, scope, Authority, context
digest, every contract invocation with its input/output digests, every policy decision and the
budget charged, with the taint of the output.

Budget (ADD v1.3 §4.3.1 invariant 6 :3119, FR-120 :269): an ``AgentBudget`` charges tool calls,
steps, tokens, cost, wall time, compute and risk exposure atomically at the agent, run, team and
tenant levels of an ``AgentBudgetLedger``; a level without a quota, or any dimension that would be
exceeded, is ``BUDGET_EXCEEDED`` with nothing charged anywhere. Wall time and compute are measured
per dispatch and charged after it; once exhausted, the next call is refused (no reservation
semantics, ADD v1.3 :3122).

Stop and deadline (OCOR-DEV-REM-0027, kept): each dispatch runs on a supervised worker thread with a
deadline of at most the contract ``timeout_ms`` and the ``<=10 s`` containment target; a stop
accepted while it runs, or the deadline, cancels it cooperatively through
``cancellation_checkpoint`` and preempts it if it does not cooperate. The outcome is then
indeterminate: it is recorded, before the refusal is raised, on the audited C6
``OutcomeReconciler`` (signed audit port, FR-163 :407) -- ``EMERGENCY_STOP_ACTIVE`` for a stop,
``EXECUTION_UNKNOWN`` for the deadline, both with ``execution_unknown`` set -- and a reconciler that
cannot record it fails the call closed with ``EXECUTION_UNKNOWN`` and no reconciliation. The runtime
has no default reconciler and refuses an unaudited one; it has no default registry, grants,
controls, policy or eligibility either (no permissive default). ``authorize_effect`` is the grant
channel for an effect a tool performs: grant chain, Delegation and stop are read live there too.

Every reason code belongs to the closed ``error_codes`` enum of the Tool Contract (ADD v1.3
:1759-1778). The runtime no longer uses the legacy ``ocor_runtime.c6_capabilities`` lease
(PO decision NCP-U07-C8-TOOL-RUNTIME-LEASE, option 2).

Residual limit, declared rather than claimed closed (OCOR-DEV-REM-0027 repair 2): in-process
preemption is best-effort between interpreter steps. A native call already running and the
``finally`` blocks after it are not interruptible; a tool that catches ``BaseException`` is not
stopped. The runtime stays bounded: the call is refused within the target, no new tool is
dispatched, no pre-stop grant is usable on the grant channel and the outcome goes to
reconciliation. An effect on a channel the platform does not govern is a measured residual traced
to FGM-17 and the G6 qualification, never reported as contained.
"""

from __future__ import annotations

import ast
import contextvars
import ctypes
import json
import math
import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from ..c3_store import require_aware
from ..c4.marking import MarkingUnresolved
from ..c4.marking_resolution import ResolvedMarkingEngine
from ..c4_marking import MarkingSet
from ..c6.safety import (
    EmergencyStopController,
    OutcomeReconciler,
    ReconciliationRecord,
    SafetyError,
    StopEpochReader,
    StopStatus,
)
from ..c8_agent import StrictSandbox
from ..errors import OCORError, SandboxViolation
from ..kernel.governance import (
    Authority,
    AuthorityRequest,
    GovernanceFault,
    RiskClass,
    VerifiedAuthorityBinding,
    validate_authority,
)
from ..kernel.governed_context import GovernedContext
from ..security.ports import SPIFFE_ID, AuthenticatedPrincipal, PolicyDecision, PolicyDecisionPort, PolicyRequest
from .tool_contract import TOOL_ERROR_CODES, UNTRUSTED_TOOL_OUTPUT_TAINT, ToolContract, ToolContractError, ToolOutput, ToolRegistry

# Every reason code the runtime raises; all of them belong to the error_codes enum (ADD v1.3 :1759-1778).
TOOL_RUNTIME_REASON_CODES: tuple[str, ...] = (
    "POLICY_DENIED",
    "AUTHORITY_MISSING",
    "CAPABILITY_DENIED",
    "APPROVAL_REQUIRED",
    "CAPABILITY_REVOKED",
    "BUDGET_EXCEEDED",
    "SCHEMA_VIOLATION",
    "STALE_CONTEXT",
    "EMERGENCY_STOP_ACTIVE",
    "EXECUTION_UNKNOWN",
)

AUTONOMY_TIERS: tuple[str, ...] = ("OBSERVE", "ANALYZE", "SIMULATE", "PROPOSE", "EXECUTE_APPROVED")
# ADD v1.3 §4.3.1 invariant 2 (:3115) and the PoC fence (:1992): EXECUTE_APPROVED never from C8.
POC_AUTONOMY_TIERS: tuple[str, ...] = ("OBSERVE", "ANALYZE", "SIMULATE", "PROPOSE")

BUDGET_DIMENSIONS: tuple[str, ...] = ("tool_calls", "steps", "tokens", "cost", "wall_time_ms", "compute_ms", "risk_exposure")
BUDGET_LEVELS: tuple[str, ...] = ("agent", "run", "team", "tenant")

# The Authority request of a tool call takes the more restrictive of the two contract classifications
# in impact order: the effect class (ADD v1.3 :1629-1637) and the risk class (:1638), against the
# risk classes of §5.4 (kernel.governance.RiskClass).
_EFFECT_RISK = MappingProxyType(
    {
        "READ_ONLY": RiskClass.R0_READ,
        "ANALYZE": RiskClass.R1_ANALYZE,
        "SIMULATE": RiskClass.R1_ANALYZE,
        "PROPOSE_ACTION": RiskClass.R1_ANALYZE,
    }
)
_CONTRACT_RISK = MappingProxyType(
    {"LOW": RiskClass.R0_READ, "MEDIUM": RiskClass.R1_ANALYZE, "HIGH": RiskClass.R2_CONTROLLED, "CRITICAL": RiskClass.R3_HIGH_IMPACT}
)
# risk exposure charged per dispatch, by contract risk class
_RISK_EXPOSURE = MappingProxyType({"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4})
_URN = re.compile(r"^urn:[A-Za-z0-9][A-Za-z0-9-]{0,31}:[^\s]{1,240}$")
_SHA256_URN = re.compile(r"^urn:sha256:[0-9a-f]{64}$")


class ToolRuntimeError(OCORError):
    """A tool call was refused. ``reason_code`` belongs to the closed ``error_codes`` enum of the
    Tool Contract (ADD v1.3 :1759-1778); ``execution_unknown`` is set when a dispatched tool may
    still have produced its effect, with ``reconciliation`` the outcome recorded on the audited
    reconciler (None when none could be recorded); ``marking_outcome`` keeps the marking result
    (``MARKING_UNRESOLVED`` or ``MARKING_DENIED``, LLD v1.1 :67) of a ``POLICY_DENIED`` marking
    refusal."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        execution_unknown: bool = False,
        reconciliation: UnknownToolOutcome | None = None,
        marking_outcome: str | None = None,
    ) -> None:
        if reason_code not in TOOL_ERROR_CODES:
            raise ValueError(f"{reason_code!r} is not a Tool Contract error code")
        self.reason_code = reason_code
        self.execution_unknown = execution_unknown
        self.reconciliation = reconciliation
        self.marking_outcome = marking_outcome
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True, slots=True)
class UnknownToolOutcome:
    """An ``execution_unknown`` tool call as recorded on the audited C6 ``OutcomeReconciler``
    (status ``EXECUTION_UNKNOWN``, never idempotent-proven)."""

    command_id: str
    tool_name: str
    lease_id: str
    stop_epoch: int
    reason_code: str
    correlation_id: str
    dispatched_at: datetime
    refused_at: datetime
    reconciliation: ReconciliationRecord


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 256 or value != value.strip():
        raise ValueError(f"{name} must be a non-empty bounded string")
    return value


# --- agent identity (ADD v1.3 §5.1 :3140) -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentIdentityBinding:
    """The binding between workload identity, agent principal, agent run, owner, autonomy tier and
    agent version (ADD v1.3 :3140), with the team and tenant its budget is charged to."""

    agent_principal_id: str
    agent_run_id: str
    workload_identity: str
    owner: str
    autonomy_tier: str
    agent_version: str
    team_id: str
    tenant_id: str

    def __post_init__(self) -> None:
        for name in ("agent_principal_id", "agent_run_id", "owner", "agent_version", "team_id", "tenant_id"):
            _text(name, getattr(self, name))
        if not isinstance(self.workload_identity, str) or SPIFFE_ID.fullmatch(self.workload_identity) is None:
            raise ValueError("workload_identity must be a SPIFFE ID")
        if self.autonomy_tier not in AUTONOMY_TIERS:
            raise ValueError(f"autonomy_tier must be one of {AUTONOMY_TIERS}")


# --- C8 tool grants: the bounded task-claim lease (LLD v1.1 :358; ADD v1.3 :3215-3220) ----------


@dataclass(frozen=True, slots=True)
class ToolGrant:
    """A C8 grant of named tools to one agent run, bound to the stop epoch of its issuance, to a
    Delegation, a scope and the Authority that covers it. ``parent_lease_id`` names the grant it was
    delegated from; ``delegator`` is the delegating agent principal, or the Authority of a root
    grant."""

    lease_id: str
    agent_principal_id: str
    agent_run_id: str
    tool_names: tuple[str, ...]
    scope: str
    delegation_ref: str
    authority_id: str
    stop_epoch: int
    issued_at: datetime
    expires_at: datetime
    parent_lease_id: str | None
    redelegation_allowed: bool
    delegator: str
    revoked_at: datetime | None = None


def _refuse(code: str, message: str) -> ToolRuntimeError:
    return ToolRuntimeError(code, message)


def _current_stop(stop: StopEpochReader) -> int:
    """The current epoch while the system is NORMAL; an active or unreadable stop refuses."""
    try:
        record = stop.current()
    except Exception as error:  # noqa: BLE001 - an unreadable stop epoch is never a pass
        raise _refuse("EMERGENCY_STOP_ACTIVE", "the signed stop epoch cannot be read") from error
    if record.status is not StopStatus.NORMAL:
        raise _refuse("EMERGENCY_STOP_ACTIVE", f"emergency stop is {record.status.value}")
    return record.epoch


class ToolGrantLedger:
    """The C8 grants, read live by the runtime at every authorisation. ``redelegation_allowed`` is
    false by default; a delegate never widens tools, scope or duration; a revocation is recorded
    with its instant and refuses every later use of the grant and of the grants delegated from it."""

    def __init__(self, *, stop: EmergencyStopController | StopEpochReader) -> None:
        if isinstance(stop, EmergencyStopController):
            stop = stop.reader
        if not isinstance(stop, StopEpochReader):
            raise TypeError("stop must be a StopEpochReader of the signed stop epoch")
        self._stop = stop
        self._grants: dict[str, ToolGrant] = {}
        self._uses: dict[str, int] = {}
        self._lock = threading.RLock()

    def issue(
        self,
        *,
        agent: AgentIdentityBinding,
        tools: Sequence[str],
        scope: str,
        delegation_ref: str,
        authority_id: str,
        issued_at: datetime,
        ttl: timedelta,
        redelegation_allowed: bool = False,
    ) -> ToolGrant:
        if not isinstance(delegation_ref, str) or _SHA256_URN.fullmatch(delegation_ref) is None:
            raise ValueError("delegation_ref must be a SHA-256 URN")
        _text("authority_id", authority_id)
        return self._store(
            agent=agent,
            tools=tools,
            scope=scope,
            delegation_ref=delegation_ref,
            authority_id=authority_id,
            issued_at=issued_at,
            ttl=ttl,
            redelegation_allowed=redelegation_allowed,
            parent=None,
        )

    def delegate(
        self,
        parent_lease_id: str,
        *,
        agent: AgentIdentityBinding,
        tools: Sequence[str],
        issued_at: datetime,
        ttl: timedelta,
        redelegation_allowed: bool = False,
    ) -> ToolGrant:
        with self._lock:
            parent = self._grants.get(parent_lease_id) if isinstance(parent_lease_id, str) else None
            if parent is None:
                raise _refuse("CAPABILITY_DENIED", "the delegating grant is unknown")
            if parent.revoked_at is not None:
                raise _refuse("CAPABILITY_REVOKED", "the delegating grant has been revoked")
            if not parent.redelegation_allowed:
                raise _refuse("CAPABILITY_DENIED", "the delegating grant does not allow redelegation")
            return self._store(
                agent=agent,
                tools=tools,
                scope=parent.scope,
                delegation_ref=parent.delegation_ref,
                authority_id=parent.authority_id,
                issued_at=issued_at,
                ttl=ttl,
                redelegation_allowed=redelegation_allowed,
                parent=parent,
            )

    def _store(
        self,
        *,
        agent: AgentIdentityBinding,
        tools: Sequence[str],
        scope: str,
        delegation_ref: str,
        authority_id: str,
        issued_at: datetime,
        ttl: timedelta,
        redelegation_allowed: bool,
        parent: ToolGrant | None,
    ) -> ToolGrant:
        if not isinstance(agent, AgentIdentityBinding):
            raise TypeError("agent must be an AgentIdentityBinding")
        if isinstance(tools, str) or not isinstance(tools, Sequence) or not tools:
            raise ValueError("tools must be a non-empty sequence of tool names")
        names = tuple(_text("tool name", name) for name in tools)
        if len(set(names)) != len(names):
            raise ValueError("tools must not repeat")
        if not isinstance(scope, str) or _URN.fullmatch(scope) is None:
            raise ValueError("scope must be a URN")
        instant = require_aware(issued_at, field="issued_at")
        if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
            raise ValueError("ttl must be a positive timedelta")
        if type(redelegation_allowed) is not bool:
            raise TypeError("redelegation_allowed must be a boolean")
        expires_at = instant + ttl
        if parent is not None:
            if not set(names) <= set(parent.tool_names):
                raise _refuse("CAPABILITY_DENIED", "a delegate cannot widen the tools of its grant")
            if instant < parent.issued_at or expires_at > parent.expires_at:
                raise _refuse("CAPABILITY_DENIED", "a delegate cannot widen the duration of its grant")
        epoch = _current_stop(self._stop)
        if parent is not None and parent.stop_epoch != epoch:
            raise _refuse("EMERGENCY_STOP_ACTIVE", "the delegating grant belongs to another stop epoch")
        grant = ToolGrant(
            lease_id=f"urn:ocor:c8:tool-grant:{uuid.uuid4()}",
            agent_principal_id=agent.agent_principal_id,
            agent_run_id=agent.agent_run_id,
            tool_names=names,
            scope=scope,
            delegation_ref=delegation_ref,
            authority_id=authority_id,
            stop_epoch=epoch,
            issued_at=instant,
            expires_at=expires_at,
            parent_lease_id=None if parent is None else parent.lease_id,
            redelegation_allowed=redelegation_allowed,
            delegator=authority_id if parent is None else parent.agent_principal_id,
        )
        with self._lock:
            self._grants[grant.lease_id] = grant
            self._uses[grant.lease_id] = 0
        return grant

    def revoke(self, lease_id: str, *, at: datetime) -> ToolGrant:
        instant = require_aware(at, field="at")
        with self._lock:
            grant = self._grants.get(lease_id) if isinstance(lease_id, str) else None
            if grant is None:
                raise _refuse("CAPABILITY_DENIED", "the grant is unknown")
            if grant.revoked_at is None:
                grant = ToolGrant(**{**{name: getattr(grant, name) for name in grant.__dataclass_fields__}, "revoked_at": instant})
                self._grants[lease_id] = grant
            return grant

    def get(self, lease_id: str) -> ToolGrant | None:
        """The grant as recorded now (with its revocation, if any)."""
        with self._lock:
            return self._grants.get(lease_id) if isinstance(lease_id, str) else None

    def usage(self, lease_id: str) -> int:
        """How many tool dispatches the grant has authorised."""
        with self._lock:
            return self._uses.get(lease_id, 0)

    def record_use(self, lease_id: str) -> None:
        with self._lock:
            self._uses[lease_id] = self._uses.get(lease_id, 0) + 1

    def chain(self, lease_id: str) -> tuple[ToolGrant, ...]:
        """The grant and the grants it was delegated from, as recorded now; an unknown grant or a
        cycle refuses."""
        with self._lock:
            chain: list[ToolGrant] = []
            seen: set[str] = set()
            current: str | None = lease_id
            while current is not None:
                if current in seen:
                    raise _refuse("CAPABILITY_DENIED", "grant delegation cycle detected")
                seen.add(current)
                grant = self._grants.get(current)
                if grant is None:
                    raise _refuse("CAPABILITY_DENIED", "the grant is unknown to its ledger")
                chain.append(grant)
                current = grant.parent_lease_id
            return tuple(chain)


# --- governance controls: Authority and Delegation (C2), memory instruction eligibility (G5) ----


@runtime_checkable
class GovernanceControlPort(Protocol):
    """The live Authority and Delegation controls the runtime reads at every authorisation."""

    def authority(self, authority_id: str) -> Authority | None: ...

    def signature_verified(self, authority: Authority) -> bool: ...

    def revoked(self, ref: str) -> bool: ...

    def verified_delegation(self, effective_principal_id: str) -> str | None: ...


class InMemoryGovernanceControls:
    """``GovernanceControlPort`` in memory: registered Authorities with their verified signature,
    the verified Delegation of each principal and the revoked references."""

    def __init__(self) -> None:
        self._authorities: dict[str, tuple[Authority, bool]] = {}
        self._delegations: dict[str, str] = {}
        self._revoked: set[str] = set()
        self._lock = threading.Lock()

    def add_authority(self, authority: Authority, *, signature_verified: bool) -> None:
        if not isinstance(authority, Authority):
            raise TypeError("authority must be a kernel Authority")
        if type(signature_verified) is not bool:
            raise TypeError("signature_verified must be a boolean")
        with self._lock:
            self._authorities[authority.authority_id] = (authority, signature_verified)

    def bind_delegation(self, effective_principal_id: str, delegation_ref: str) -> None:
        _text("effective_principal_id", effective_principal_id)
        if not isinstance(delegation_ref, str) or _SHA256_URN.fullmatch(delegation_ref) is None:
            raise ValueError("delegation_ref must be a SHA-256 URN")
        with self._lock:
            known = self._delegations.setdefault(effective_principal_id, delegation_ref)
        if known != delegation_ref:
            raise ValueError("the principal is already bound to another Delegation")

    def rebind_delegation(self, effective_principal_id: str, delegation_ref: str) -> None:
        with self._lock:
            self._delegations.pop(effective_principal_id, None)
        self.bind_delegation(effective_principal_id, delegation_ref)

    def revoke(self, ref: str) -> None:
        _text("ref", ref)
        with self._lock:
            self._revoked.add(ref)

    def authority(self, authority_id: str) -> Authority | None:
        with self._lock:
            entry = self._authorities.get(authority_id)
        return None if entry is None else entry[0]

    def signature_verified(self, authority: Authority) -> bool:
        with self._lock:
            entry = self._authorities.get(authority.authority_id)
        return entry is not None and entry[0] == authority and entry[1]

    def revoked(self, ref: str) -> bool:
        with self._lock:
            return ref in self._revoked

    def verified_delegation(self, effective_principal_id: str) -> str | None:
        with self._lock:
            return self._delegations.get(effective_principal_id)


@runtime_checkable
class InstructionEligibilityPort(Protocol):
    """Whether the memory the agent run uses as instruction is still eligible (G5, DEC-208)."""

    def instruction_eligible(self, *, agent_run_id: str, governed_context_digest: str, at: datetime) -> bool: ...


class InMemoryInstructionEligibility:
    """``InstructionEligibilityPort`` in memory: only an explicitly allowed run is eligible."""

    def __init__(self) -> None:
        self._eligible: set[str] = set()
        self._lock = threading.Lock()

    def allow(self, agent_run_id: str) -> None:
        _text("agent_run_id", agent_run_id)
        with self._lock:
            self._eligible.add(agent_run_id)

    def withdraw(self, agent_run_id: str) -> None:
        with self._lock:
            self._eligible.discard(agent_run_id)

    def instruction_eligible(self, *, agent_run_id: str, governed_context_digest: str, at: datetime) -> bool:
        with self._lock:
            return agent_run_id in self._eligible


# --- multidimensional budget (ADD v1.3 §4.3.1 invariant 6 :3119; FR-120 :269) --------------------


@dataclass(frozen=True, slots=True)
class BudgetQuota:
    tool_calls: int
    steps: int
    tokens: int
    cost: int
    wall_time_ms: int
    compute_ms: int
    risk_exposure: int

    def __post_init__(self) -> None:
        for dimension in BUDGET_DIMENSIONS:
            value = getattr(self, dimension)
            if type(value) is not int or value < 0:
                raise ValueError(f"quota {dimension} must be a non-negative integer")


def _amounts(name: str, values: Mapping[str, int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for dimension, value in values.items():
        if dimension not in BUDGET_DIMENSIONS:
            raise ValueError(f"{name}: unknown budget dimension {dimension!r}")
        if type(value) is not int or value < 0:
            raise ValueError(f"{name}: {dimension} must be a non-negative integer")
        result[dimension] = value
    return result


class AgentBudgetLedger:
    """Quotas and spending per budget level (agent, run, team, tenant)."""

    def __init__(self) -> None:
        self._quotas: dict[tuple[str, str], BudgetQuota] = {}
        self._spent: dict[tuple[str, str], dict[str, int]] = {}
        self._lock = threading.RLock()

    def set_quota(self, level: str, key: str, quota: BudgetQuota) -> None:
        if level not in BUDGET_LEVELS:
            raise ValueError(f"level must be one of {BUDGET_LEVELS}")
        _text("key", key)
        if not isinstance(quota, BudgetQuota):
            raise TypeError("quota must be a BudgetQuota")
        with self._lock:
            self._quotas[(level, key)] = quota

    def budget(self, agent: AgentIdentityBinding) -> AgentBudget:
        if not isinstance(agent, AgentIdentityBinding):
            raise TypeError("agent must be an AgentIdentityBinding")
        return AgentBudget(self, agent)

    @staticmethod
    def _levels(agent: AgentIdentityBinding) -> tuple[tuple[str, str], ...]:
        return (
            ("agent", agent.agent_principal_id),
            ("run", agent.agent_run_id),
            ("team", agent.team_id),
            ("tenant", agent.tenant_id),
        )

    def charge(self, agent: AgentIdentityBinding, amounts: Mapping[str, int], require: Mapping[str, int]) -> None:
        """Charge ``amounts`` at every level, atomically, if they and the headroom in ``require``
        fit every quota; otherwise ``BUDGET_EXCEEDED`` with nothing charged."""
        with self._lock:
            for level in self._levels(agent):
                quota = self._quotas.get(level)
                if quota is None:
                    raise _refuse("BUDGET_EXCEEDED", f"no {level[0]} quota for {level[1]!r}")
                spent = self._spent.get(level, {})
                for dimension in BUDGET_DIMENSIONS:
                    needed = amounts.get(dimension, 0) + require.get(dimension, 0)
                    if needed and spent.get(dimension, 0) + needed > getattr(quota, dimension):
                        raise _refuse("BUDGET_EXCEEDED", f"{level[0]} {dimension} budget of {level[1]!r} is exhausted")
            for level in self._levels(agent):
                spent = self._spent.setdefault(level, {})
                for dimension, value in amounts.items():
                    spent[dimension] = spent.get(dimension, 0) + value

    def record(self, agent: AgentIdentityBinding, amounts: Mapping[str, int]) -> None:
        """Charge a measured consumption (wall time, compute) at every level; an exhausted
        dimension refuses the next charge."""
        with self._lock:
            for level in self._levels(agent):
                spent = self._spent.setdefault(level, {})
                for dimension, value in amounts.items():
                    spent[dimension] = spent.get(dimension, 0) + value

    def spent(self, level: str, key: str, dimension: str) -> int:
        with self._lock:
            return self._spent.get((level, key), {}).get(dimension, 0)


class AgentBudget:
    """The budget of one agent run on a ledger."""

    def __init__(self, ledger: AgentBudgetLedger, agent: AgentIdentityBinding) -> None:
        self._ledger = ledger
        self._agent = agent

    @property
    def agent(self) -> AgentIdentityBinding:
        return self._agent

    def charge(self, *, require: Mapping[str, int] | None = None, **amounts: int) -> dict[str, int]:
        charged = _amounts("charge", amounts)
        self._ledger.charge(self._agent, charged, _amounts("require", require or {}))
        return charged

    def record(self, **amounts: int) -> dict[str, int]:
        measured = _amounts("record", amounts)
        self._ledger.record(self._agent, measured)
        return measured

    def spent(self, dimension: str, *, level: str = "run") -> int:
        if dimension not in BUDGET_DIMENSIONS or level not in BUDGET_LEVELS:
            raise ValueError("unknown budget dimension or level")
        key = dict(AgentBudgetLedger._levels(self._agent))[level]
        return self._ledger.spent(level, key, dimension)

    @property
    def used(self) -> int:
        """Tokens charged at the run level."""
        return self.spent("tokens")


# --- supervised dispatch (OCOR-DEV-REM-0027) -----------------------------------------------------


class ToolCancelled(OCORError):
    """Raised inside a dispatched tool by ``cancellation_checkpoint`` once
    its call has been cancelled by an accepted stop or by the deadline."""


class ToolPreempted(BaseException):
    """Raised asynchronously in the worker thread of a dispatched tool that
    did not stop at its cancellation: a ``BaseException`` so that an
    ordinary ``except Exception`` in the tool cannot swallow it."""


# CPython's PyThreadState_SetAsyncExc, called with the GIL held: one
# prototype schedules an exception in a thread, the other (NULL) clears it.
_set_async_exc = ctypes.PYFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.py_object)(
    ("PyThreadState_SetAsyncExc", ctypes.pythonapi)
)
_clear_async_exc = ctypes.PYFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p)(
    ("PyThreadState_SetAsyncExc", ctypes.pythonapi)
)


class _ToolWorker:
    """The supervised worker thread of one tool dispatch. ``preempt`` and
    ``_retire`` share a lock, so an asynchronous exception is only ever
    scheduled in the worker while the tool call is still running -- never
    in a thread that has retired (whose identifier may be reused)."""

    def __init__(self, name: str, call: Callable[[], Any], dispatched: _DispatchedCall) -> None:
        self._call = call
        self._dispatched = dispatched
        self._lock = threading.Lock()
        self._retired = False
        self._preempted = False
        self.done = threading.Event()
        self.outcome: dict[str, Any] = {}
        self._thread = threading.Thread(
            target=contextvars.copy_context().run, args=(self._run,), name=f"ocor-c8-tool-{name}", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            try:
                _DISPATCHED_CALL.set(self._dispatched)
                started = time.thread_time()
                try:
                    self.outcome["result"] = self._call()
                finally:
                    self.outcome["compute_seconds"] = time.thread_time() - started
            except BaseException as error:  # noqa: BLE001 - re-raised on the calling thread
                self.outcome["error"] = error
        except ToolPreempted as late:
            # preempted after the tool returned, while its outcome was stored
            self.outcome["error"] = late
        finally:
            # retired inline: a pending preemption can only be raised inside
            # this try, and none is scheduled once ``_retired`` is set
            try:
                with self._lock:
                    self._retired = True
                    _clear_async_exc(threading.get_ident(), None)
            except ToolPreempted as late:
                self.outcome.setdefault("error", late)
                with self._lock:
                    self._retired = True
            finally:
                self.done.set()

    def preempt(self) -> bool:
        """Schedule ``ToolPreempted`` once in the running tool. Returns
        whether the tool was still running."""
        with self._lock:
            ident = self._thread.ident
            if self._retired or ident is None:
                return False
            if not self._preempted:
                self._preempted = True
                _set_async_exc(ident, ToolPreempted)
            return True


DEFAULT_TOOL_CALL_DEADLINE = timedelta(seconds=5)
CONTAINMENT_TARGET = timedelta(seconds=10)
_SUPERVISION_INTERVAL_SECONDS = 0.01
# time a cancelled tool has to reach a cancellation checkpoint before it is
# preempted; far below the containment target
_COOPERATIVE_GRACE_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class _DispatchedCall:
    stop: StopEpochReader
    fenced_epoch: int
    cancelled: threading.Event


_DISPATCHED_CALL: contextvars.ContextVar[_DispatchedCall | None] = contextvars.ContextVar(
    "ocor_c8_dispatched_tool_call", default=None
)


def _stop_accepted(stop: StopEpochReader, fenced_epoch: int) -> bool:
    try:
        stop.guard_dispatch(fenced_epoch=fenced_epoch)
    except SafetyError:
        return True
    return False


def cancellation_requested() -> bool:
    """Whether the tool call running on this thread has been cancelled.
    Outside a call dispatched by ``ToolCallRuntime`` it is always False."""
    call = _DISPATCHED_CALL.get()
    if call is None:
        return False
    return call.cancelled.is_set() or _stop_accepted(call.stop, call.fenced_epoch)


def cancellation_checkpoint() -> None:
    """Cooperative cancellation point (LLD v1.1 section 6) for tools: raises
    ``ToolCancelled`` once the current call is cancelled, so a cooperating
    tool stops before producing its effect."""
    if cancellation_requested():
        raise ToolCancelled("tool call cancelled by an accepted emergency stop or by its deadline")


@dataclass(frozen=True, slots=True)
class ToolCallReceipt:
    """The receipt of a completed call (FR-004 :47): the grant, purpose, stop epoch and result, the
    agent identity, Delegation, scope and Authority, the contract invocations with their digests,
    the policy decisions and the budget charged; the result is tainted tool output."""

    tool_name: str
    lease_id: str
    purpose: str
    tokens_spent: int
    stop_epoch: int
    result: Any
    called_at: datetime
    agent_principal_id: str
    agent_run_id: str
    agent_version: str
    workload_identity: str
    autonomy_tier: str
    delegation_ref: str
    delegator: str
    scope: str
    authority_id: str
    governed_context_digest: str
    invocations: tuple[ToolOutput, ...]
    policy_decision_ids: tuple[str, ...]
    budget_charged: Mapping[str, int]
    taint_labels: tuple[str, ...] = UNTRUSTED_TOOL_OUTPUT_TAINT


_INVOCATIONS: contextvars.ContextVar[list[ToolOutput] | None] = contextvars.ContextVar("ocor_c8_tool_invocations", default=None)


@dataclass(slots=True)
class _Call:
    """The bindings of one ``invoke``, shared by its dispatches."""

    agent: AgentIdentityBinding
    principal: AuthenticatedPrincipal
    context: GovernedContext
    context_digest: str
    instant: datetime
    budget: AgentBudget
    decisions: list[str]
    charged: dict[str, int] = field(default_factory=dict)

    def add(self, amounts: Mapping[str, int]) -> None:
        for dimension, value in amounts.items():
            self.charged[dimension] = self.charged.get(dimension, 0) + value


class ToolCallRuntime:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        grants: ToolGrantLedger,
        controls: GovernanceControlPort,
        policy: PolicyDecisionPort,
        eligibility: InstructionEligibilityPort,
        marking_engine: ResolvedMarkingEngine,
        stop: EmergencyStopController | StopEpochReader,
        reconciler: OutcomeReconciler,
        tool_call_deadline: timedelta = DEFAULT_TOOL_CALL_DEADLINE,
    ) -> None:
        if not isinstance(tool_call_deadline, timedelta) or not timedelta(0) < tool_call_deadline <= CONTAINMENT_TARGET:
            raise ValueError(f"tool_call_deadline must be positive and at most {CONTAINMENT_TARGET}")
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be the contract-bound ToolRegistry")
        if not isinstance(grants, ToolGrantLedger):
            raise TypeError("grants must be the C8 ToolGrantLedger")
        if not isinstance(controls, GovernanceControlPort):
            raise TypeError("controls must implement the GovernanceControlPort (Authority and Delegation)")
        if policy is None or not callable(getattr(policy, "evaluate", None)):
            raise TypeError("policy must implement the PolicyDecisionPort")
        if not isinstance(eligibility, InstructionEligibilityPort):
            raise TypeError("eligibility must implement the InstructionEligibilityPort")
        if not isinstance(marking_engine, ResolvedMarkingEngine):
            raise TypeError("marking_engine must be the ResolvedMarkingEngine, not the legacy MarkingEngine")
        if isinstance(stop, EmergencyStopController):
            stop = stop.reader
        if not isinstance(stop, StopEpochReader):
            raise TypeError("stop must be a StopEpochReader of the signed stop epoch")
        # FR-163: every EXECUTION_UNKNOWN outcome goes to the reconciler of the signed audit port
        if not isinstance(reconciler, OutcomeReconciler) or reconciler.audited is not True:
            raise TypeError("reconciler must be an OutcomeReconciler appending to the signed audit port")
        self._registry = registry
        self._grants = grants
        self._controls = controls
        self._policy = policy
        self._eligibility = eligibility
        self._marking_engine = marking_engine
        self._stop = stop
        self._reconciler = reconciler
        self._deadline_seconds = tool_call_deadline.total_seconds()
        self._unknown_outcomes: list[UnknownToolOutcome] = []
        self._outcomes_lock = threading.Lock()
        # the sandbox's only callables are the governed calls of the allow-listed tools
        self._sandbox = StrictSandbox()
        self._sandbox_lock = threading.Lock()
        self._sync_tools()

    @property
    def reconciler(self) -> OutcomeReconciler:
        """The audited C6 reconciler that receives every ``execution_unknown`` outcome."""
        return self._reconciler

    @property
    def unknown_outcomes(self) -> tuple[UnknownToolOutcome, ...]:
        with self._outcomes_lock:
            return tuple(self._unknown_outcomes)

    @property
    def tool_names(self) -> tuple[str, ...]:
        self._sync_tools()
        return self._sandbox.tool_names

    def _sync_tools(self) -> None:
        """Expose to the sandbox every tool the platform has allow-listed in the registry."""
        with self._sandbox_lock:
            known = set(self._sandbox.tool_names)
            for name in self._registry.tool_names:
                if name not in known:
                    self._sandbox.register_tool(name, self._governed(name))

    def _governed(self, name: str) -> Callable[..., Any]:
        registry = self._registry

        def governed(*args: Any, **kwargs: Any) -> Any:
            output = registry.invoke(name, args, kwargs)
            collector = _INVOCATIONS.get()
            if collector is not None:
                collector.append(output)
            return output.value

        return governed

    # -- the grant channel -------------------------------------------------------------------

    def authorize_effect(self, lease: ToolGrant | str, tool_name: str, *, agent: AgentIdentityBinding, at: datetime) -> ToolGrant:
        """The grant channel for an effect of ``tool_name``: stop, grant chain and Delegation are read
        live, so after an accepted stop the effect is ``EMERGENCY_STOP_ACTIVE``, after a revocation
        ``CAPABILITY_REVOKED`` and outside the grant ``CAPABILITY_DENIED``."""
        instant = require_aware(at, field="at")
        if not isinstance(agent, AgentIdentityBinding):
            raise TypeError("agent must be an AgentIdentityBinding")
        epoch = _current_stop(self._stop)
        grant = self._live_grant(lease, tool_name, agent, instant)
        if grant.stop_epoch != epoch:
            raise _refuse("EMERGENCY_STOP_ACTIVE", f"effect of {tool_name!r}: the grant belongs to stop epoch {grant.stop_epoch}")
        self._live_delegation(grant, agent)
        return grant

    # -- invocation --------------------------------------------------------------------------

    def invoke(
        self,
        tool_name: str,
        expression: str,
        *,
        bindings: Mapping[str, Any] | None,
        lease: ToolGrant | str,
        agent: AgentIdentityBinding,
        principal: AuthenticatedPrincipal,
        context: GovernedContext,
        content_marking: MarkingSet,
        clearance: MarkingSet,
        budget: AgentBudget,
        estimated_tokens: int,
        stop_epoch: int,
        at: datetime,
        estimated_cost: int = 0,
    ) -> ToolCallReceipt:
        instant = require_aware(at, field="at")
        call = self._bind(agent, principal, context, budget, instant)
        self._sync_tools()

        grant = self._live(tool_name, lease, call)
        contract = self._contract(tool_name)
        for called in self._called_tools(expression):
            self._live(called, grant.lease_id, call)

        if not context.purpose:
            raise _refuse("POLICY_DENIED", "a tool call requires a non-empty GovernedContext purpose")
        try:
            marking_authorized = self._marking_engine.authorized(content_marking, clearance)
        except MarkingUnresolved as error:
            raise ToolRuntimeError("POLICY_DENIED", str(error), marking_outcome="MARKING_UNRESOLVED") from error
        if not marking_authorized:
            raise ToolRuntimeError("POLICY_DENIED", "clearance does not dominate the content marking", marking_outcome="MARKING_DENIED")

        if type(stop_epoch) is not int or stop_epoch != grant.stop_epoch:
            raise _refuse("EMERGENCY_STOP_ACTIVE", f"presented epoch {stop_epoch!r} differs from the grant's stop epoch {grant.stop_epoch}")
        self._fence(grant.stop_epoch)

        if type(estimated_tokens) is not int or type(estimated_cost) is not int or estimated_tokens < 0 or estimated_cost < 0:
            raise _refuse("BUDGET_EXCEEDED", "estimated tokens and cost are non-negative integers")
        call.add(
            budget.charge(
                require={"tool_calls": 1, "wall_time_ms": 1, "compute_ms": 1, "risk_exposure": _RISK_EXPOSURE[contract.risk_class]},
                steps=1,
                tokens=estimated_tokens,
                cost=estimated_cost,
            )
        )

        def dispatch(name: str, run: Callable[[], Any]) -> Any:
            return self._dispatch(name, run, lease_id=grant.lease_id, call=call)

        invocations: list[ToolOutput] = []
        token = _INVOCATIONS.set(invocations)
        try:
            result = self._sandbox.execute(expression, bindings, dispatch=dispatch)
        finally:
            _INVOCATIONS.reset(token)

        return ToolCallReceipt(
            tool_name=tool_name,
            lease_id=grant.lease_id,
            purpose=context.purpose,
            tokens_spent=estimated_tokens,
            stop_epoch=grant.stop_epoch,
            result=result,
            called_at=instant,
            agent_principal_id=agent.agent_principal_id,
            agent_run_id=agent.agent_run_id,
            agent_version=agent.agent_version,
            workload_identity=agent.workload_identity,
            autonomy_tier=agent.autonomy_tier,
            delegation_ref=grant.delegation_ref,
            delegator=grant.delegator,
            scope=grant.scope,
            authority_id=grant.authority_id,
            governed_context_digest=call.context_digest,
            invocations=tuple(invocations),
            policy_decision_ids=tuple(call.decisions),
            budget_charged=MappingProxyType({dimension: call.charged.get(dimension, 0) for dimension in BUDGET_DIMENSIONS}),
        )

    def _bind(
        self, agent: object, principal: object, context: object, budget: object, instant: datetime
    ) -> _Call:
        """The agent binding (ADD v1.3 :3140): the agent principal is the authenticated principal
        and the effective principal of the Governed Context, in its tenant; the context digest is
        recomputed here and must be the one the registry is bound to."""
        if not isinstance(context, GovernedContext):
            raise TypeError("context must be a GovernedContext")
        if not isinstance(agent, AgentIdentityBinding):
            raise _refuse("CAPABILITY_DENIED", "a tool call requires an agent identity binding")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise _refuse("CAPABILITY_DENIED", "a tool call requires the authenticated agent principal")
        if not isinstance(budget, AgentBudget) or budget.agent != agent:
            raise _refuse("BUDGET_EXCEEDED", "a tool call requires the budget of its agent run")
        digest = context.digest()
        if digest != self._registry.governed_context_ref:
            raise _refuse("STALE_CONTEXT", "the Governed Context is not the one the tool contracts are bound to")
        if not (
            agent.agent_principal_id == principal.principal_id == context.effective_principal_id
            and agent.tenant_id == context.tenant_id
        ):
            raise _refuse("CAPABILITY_DENIED", "the agent binding does not match the authenticated principal and the context")
        try:
            principal.require_valid(at=instant)
        except Exception as error:  # noqa: BLE001 - an invalid identity is never a pass
            raise _refuse("CAPABILITY_DENIED", f"the agent principal is not valid: {error}") from error
        return _Call(agent=agent, principal=principal, context=context, context_digest=digest, instant=instant, budget=budget, decisions=[])

    def _contract(self, name: str) -> ToolContract:
        try:
            return self._registry.contract(name)
        except ToolContractError as error:
            raise _refuse(error.reason_code, str(error)) from error

    def _live(self, name: str, lease: ToolGrant | str, call: _Call) -> ToolGrant:
        """Re-evaluate, as recorded now, everything that authorises ``name`` (ADD v1.3 :3856)."""
        contract = self._contract(name)
        epoch = _current_stop(self._stop)
        grant = self._live_grant(lease, name, call.agent, call.instant)
        if grant.stop_epoch != epoch:
            raise _refuse("EMERGENCY_STOP_ACTIVE", f"tool {name!r}: the grant belongs to stop epoch {grant.stop_epoch}, current is {epoch}")
        delegation = self._live_delegation(grant, call.agent)
        self._live_authority(grant, contract, delegation, call)
        tier = call.agent.autonomy_tier
        if tier not in POC_AUTONOMY_TIERS or tier not in contract.allowed_autonomy_tiers:
            raise _refuse("POLICY_DENIED", f"autonomy tier {tier} is not allowed for {contract.contract_id} in the PoC profile")
        try:
            eligible = self._eligibility.instruction_eligible(
                agent_run_id=call.agent.agent_run_id, governed_context_digest=call.context_digest, at=call.instant
            )
        except Exception as error:  # noqa: BLE001 - an unreadable eligibility is never a pass
            raise _refuse("POLICY_DENIED", "memory instruction eligibility cannot be read") from error
        if eligible is not True:
            raise _refuse("POLICY_DENIED", f"the memory instructions of {call.agent.agent_run_id} are not eligible")
        self._live_policy(contract, call)
        return grant

    def _live_grant(self, lease: ToolGrant | str, name: str, agent: AgentIdentityBinding, instant: datetime) -> ToolGrant:
        lease_id = lease.lease_id if isinstance(lease, ToolGrant) else lease
        if not isinstance(lease_id, str):
            raise _refuse("CAPABILITY_DENIED", "a tool call requires a C8 tool grant")
        chain = self._grants.chain(lease_id)
        grant = chain[0]
        for position, link in enumerate(chain):
            if link.revoked_at is not None:
                kind = "grant" if position == 0 else "delegating grant"
                raise _refuse("CAPABILITY_REVOKED", f"tool {name!r}: the {kind} has been revoked")
            if not link.issued_at <= instant < link.expires_at:
                raise _refuse("CAPABILITY_DENIED", f"tool {name!r}: a grant of the chain is outside its validity window")
        if (grant.agent_principal_id, grant.agent_run_id) != (agent.agent_principal_id, agent.agent_run_id):
            raise _refuse("CAPABILITY_DENIED", f"tool {name!r}: the grant belongs to another agent run")
        if name not in grant.tool_names:
            raise _refuse("CAPABILITY_DENIED", f"tool {name!r} is not covered by the grant")
        return grant

    def _live_delegation(self, grant: ToolGrant, agent: AgentIdentityBinding) -> str:
        try:
            delegation = self._controls.verified_delegation(agent.agent_principal_id)
            revoked = self._controls.revoked(grant.delegation_ref)
        except Exception as error:  # noqa: BLE001 - unreadable controls are never a pass
            raise _refuse("CAPABILITY_REVOKED", "the Delegation cannot be verified") from error
        if delegation is None or revoked is not False:
            raise _refuse("CAPABILITY_REVOKED", "the Delegation of the agent principal is withdrawn or revoked")
        if delegation != grant.delegation_ref:
            raise _refuse("CAPABILITY_DENIED", "the grant is bound to another Delegation")
        return delegation

    def _live_authority(self, grant: ToolGrant, contract: ToolContract, delegation: str, call: _Call) -> None:
        effect_risk = _EFFECT_RISK.get(contract.effect_class)
        if effect_risk is None:
            raise _refuse("POLICY_DENIED", f"effect class {contract.effect_class} is never executed by C8 in the PoC profile")
        risk = max(effect_risk, _CONTRACT_RISK[contract.risk_class])
        try:
            authority = self._controls.authority(grant.authority_id)
            if authority is None:
                raise _refuse("AUTHORITY_MISSING", f"no Authority {grant.authority_id!r}")
            signed = self._controls.signature_verified(authority) is True
            revoked = self._controls.revoked(authority.authority_id) is not False
        except ToolRuntimeError:
            raise
        except Exception as error:  # noqa: BLE001 - unreadable controls are never a pass
            raise _refuse("AUTHORITY_MISSING", "the Authority cannot be read") from error
        # decided here, before validate_authority, so that the reason never depends on the form of
        # the correlation identifier the kernel fault requires
        if revoked:
            raise _refuse("CAPABILITY_REVOKED", f"Authority {grant.authority_id!r} is revoked")
        if not signed or not authority.not_before <= call.instant < authority.expires_at:
            raise _refuse("AUTHORITY_MISSING", f"Authority {grant.authority_id!r} is unsigned or outside its validity window")
        try:
            validate_authority(
                authority,
                AuthorityRequest(
                    capability_id=contract.capability_id,
                    resource_scope=grant.scope,
                    risk_class=risk,
                    governed_context=call.context,
                    at=call.instant,
                ),
                signature_verified=signed,
                revoked=revoked,
                verified_binding=VerifiedAuthorityBinding(grant.lease_id, delegation, call.context),
            )
        except GovernanceFault as fault:
            code = {
                "AUTHORITY_REVOKED": "CAPABILITY_REVOKED",
                "AUTHORITY_SCOPE_MISMATCH": "CAPABILITY_DENIED",
                "AUTHORITY_BINDING_MISMATCH": "CAPABILITY_DENIED",
            }.get(fault.reason_code, "AUTHORITY_MISSING")
            raise _refuse(code, f"Authority {grant.authority_id!r}: {fault.reason_code}") from fault
        except Exception as error:  # noqa: BLE001 - an Authority that cannot be evaluated never authorises
            raise _refuse("CAPABILITY_DENIED", f"Authority {grant.authority_id!r} does not contain the request") from error

    def _live_policy(self, contract: ToolContract, call: _Call) -> None:
        try:
            request = PolicyRequest(
                principal=call.principal,
                action=contract.capability_id,
                resource=contract.contract_id,
                governed_context=call.context,
                governed_context_digest=call.context_digest,
                at=call.instant,
            )
            decision = self._policy.evaluate(request)
            if not isinstance(decision, PolicyDecision):
                raise TypeError("the policy decision point returned no PolicyDecision")
            decision.verify(request, at=call.instant)
        except Exception as error:  # noqa: BLE001 - an unavailable policy is never a pass
            raise _refuse("POLICY_DENIED", f"no valid policy decision for {contract.contract_id}") from error
        call.decisions.append(decision.decision_id)
        try:
            decision.admit()
        except Exception as error:  # noqa: BLE001 - a qualified decision the runtime cannot honour is a denial
            code = "APPROVAL_REQUIRED" if getattr(error, "reason_code", "") == "APPROVAL_REQUIRED" else "POLICY_DENIED"
            raise _refuse(code, f"policy decision {decision.decision_id} ({decision.effect.value}) for {contract.contract_id}") from error

    def _called_tools(self, expression: str) -> tuple[str, ...]:
        """Registered tools the expression can call. Anything the sandbox would refuse anyway
        (non-string, oversized, invalid syntax, unregistered names) is left to its own refusal."""
        if not isinstance(expression, str) or len(expression) > self._sandbox.max_source_characters:
            return ()
        try:
            tree = ast.parse(expression, mode="eval")
        except (SyntaxError, ValueError):
            return ()
        registered = set(self._sandbox.tool_names)
        return tuple(
            sorted(
                {
                    node.func.id
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in registered
                }
            )
        )

    def _fence(self, fenced_epoch: int) -> None:
        try:
            self._stop.guard_dispatch(fenced_epoch=fenced_epoch)
        except SafetyError as error:
            raise _refuse("EMERGENCY_STOP_ACTIVE", str(error)) from error
        except Exception as error:  # noqa: BLE001 - an unreadable stop epoch is never a pass
            raise _refuse("EMERGENCY_STOP_ACTIVE", "the signed stop epoch cannot be read") from error

    def _dispatch(self, name: str, run: Callable[[], Any], *, lease_id: str, call: _Call) -> Any:
        """Run one tool call of the expression: re-evaluated live, fenced and charged immediately
        before dispatch, supervised until it ends, the stop is accepted or the deadline expires."""
        grant = self._live(name, lease_id, call)
        self._fence(grant.stop_epoch)
        contract = self._contract(name)
        call.add(
            call.budget.charge(require={"wall_time_ms": 1, "compute_ms": 1}, tool_calls=1, risk_exposure=_RISK_EXPOSURE[contract.risk_class])
        )
        self._grants.record_use(grant.lease_id)
        fenced_epoch = grant.stop_epoch
        deadline_seconds = min(self._deadline_seconds, contract.timeout_ms / 1000)

        dispatched = _DispatchedCall(stop=self._stop, fenced_epoch=fenced_epoch, cancelled=threading.Event())
        worker = _ToolWorker(name, run, dispatched)
        dispatched_at = datetime.now(UTC)
        started = time.monotonic()

        def measured() -> None:
            compute = worker.outcome.get("compute_seconds", 0.0)
            call.add(
                call.budget.record(
                    wall_time_ms=math.ceil((time.monotonic() - started) * 1000),
                    compute_ms=math.ceil(max(0.0, float(compute)) * 1000),
                )
            )

        def unknown(reason_code: str, message: str) -> ToolRuntimeError:
            measured()
            return self._reconcile(
                reason_code,
                message,
                tool_name=name,
                lease_id=grant.lease_id,
                stop_epoch=fenced_epoch,
                correlation_id=call.context.correlation_id,
                dispatched_at=dispatched_at,
            )

        deadline = started + deadline_seconds
        worker.start()
        while not worker.done.wait(_SUPERVISION_INTERVAL_SECONDS):
            if _stop_accepted(self._stop, fenced_epoch):
                self._cancel(worker, dispatched)
                raise unknown(
                    "EMERGENCY_STOP_ACTIVE",
                    f"emergency stop accepted while tool {name!r} was running: cancelled, or preempted if it "
                    "does not cooperate; its outcome is EXECUTION_UNKNOWN",
                )
            if time.monotonic() >= deadline:
                self._cancel(worker, dispatched)
                raise unknown(
                    "EXECUTION_UNKNOWN",
                    f"tool {name!r} exceeded its {deadline_seconds} s deadline: cancelled, or preempted if it "
                    "does not cooperate; its outcome is EXECUTION_UNKNOWN",
                )
        if _stop_accepted(self._stop, fenced_epoch):
            raise unknown(
                "EMERGENCY_STOP_ACTIVE",
                f"emergency stop accepted while tool {name!r} was running; its outcome is EXECUTION_UNKNOWN",
            )
        measured()
        if "error" in worker.outcome:
            error = worker.outcome["error"]
            cause = error.__cause__ if isinstance(error, SandboxViolation) else None
            if isinstance(cause, ToolContractError):
                raise _refuse(cause.reason_code, str(cause)) from cause
            raise error
        return worker.outcome["result"]

    def _reconcile(
        self,
        reason_code: str,
        message: str,
        *,
        tool_name: str,
        lease_id: str,
        stop_epoch: int,
        correlation_id: str,
        dispatched_at: datetime,
    ) -> ToolRuntimeError:
        """Record an ``execution_unknown`` outcome on the audited reconciler and return the refusal
        carrying it. If it cannot be recorded, the call fails closed with ``EXECUTION_UNKNOWN`` and no
        reconciliation."""
        refused_at = datetime.now(UTC)
        command_id = f"urn:ocor:c8:tool-call:{uuid.uuid4()}"
        note = json.dumps(
            {
                "correlation_id": correlation_id,
                "dispatched_at": dispatched_at.isoformat(),
                "lease_id": lease_id,
                "reason_code": reason_code,
                "refused_at": refused_at.isoformat(),
                "stop_epoch": stop_epoch,
                "tool_name": tool_name,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            record = self._reconciler.mark_ambiguous(command_id, idempotent_effect_proven=False, at=refused_at, note=note)
        except Exception as error:  # noqa: BLE001 - an unrecorded outcome fails the call closed
            raise ToolRuntimeError(
                "EXECUTION_UNKNOWN",
                f"{message}; the audited reconciler could not record the outcome, the call fails closed",
                execution_unknown=True,
            ) from error
        outcome = UnknownToolOutcome(
            command_id=command_id,
            tool_name=tool_name,
            lease_id=lease_id,
            stop_epoch=stop_epoch,
            reason_code=reason_code,
            correlation_id=correlation_id,
            dispatched_at=dispatched_at,
            refused_at=refused_at,
            reconciliation=record,
        )
        with self._outcomes_lock:
            self._unknown_outcomes.append(outcome)
        return ToolRuntimeError(reason_code, message, execution_unknown=True, reconciliation=outcome)

    @staticmethod
    def _cancel(worker: _ToolWorker, dispatched: _DispatchedCall) -> None:
        """Cooperative cancellation first; a tool still running after the cooperative grace is
        preempted."""
        dispatched.cancelled.set()
        if not worker.done.wait(_COOPERATIVE_GRACE_SECONDS):
            worker.preempt()
