"""C8 -- AgentRun task assignment, commitment, handoff and dissent.

A new, retained orchestrator built around the existing,
predating-this-session ``ocor_runtime.c8_agent.AgentKernel`` (a single
agent's own sandboxed-execution/token-budget/identify-or-abstain
kernel, reused unmodified and never touched here) and the sealed
``ocor_runtime.c6_capabilities.CapabilityAuthority`` (reused unmodified,
composed exclusively through its own public methods): every state
transition a team makes on an agent's behalf -- a task offered, a
commitment accepted, a handoff between two agents, or a dissent
registered -- requires a real capability lease independently issued
by the authority before ``AgentRunOrchestrator`` ever authorizes it,
and is durably appended to the C8 Run Ledger.

OCOR-DEV-REM-0050 (NCP-U04, NCR-C3-002): AgentRun state is operational run
state kept in the PostgreSQL Run Ledger (ADD v1.3 §2.2 :276,
``ocor_runtime.c8.adapters.postgres_ledger``), not canonical state: C8 never
produces a canonical mutation, which only C6 issues to C3 (ADD v1.3 §2.5
rule 10 :342). The legacy in-memory store is no longer used.

The three negative claims this task exists to make structural, not
merely tested:

* **An agent cannot self-grant a capability** -- ``authorize()`` here
  delegates entirely to the sealed ``CapabilityAuthority.authorize``,
  which only accepts a lease it (or another authority) already
  issued; an agent has no reference to the authority and no way to
  mint its own lease.
* **An agent cannot mutate canonical state** -- neither the
  orchestrator nor an agent holds any canonical commit port: C8 has
  no path to C3 at all, and its own records go only to the Run Ledger.
* **Dissent can never be suppressed** -- there is no method on this
  class that removes, retracts or overwrites a registered
  ``Dissent``; ``dissents`` is a read-only, append-only tuple.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ..c6_capabilities import CapabilityAuthority, CapabilityLease
from ..errors import AuthorizationError, OCORError


def require_aware(instant: datetime, *, field: str) -> datetime:
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return instant


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

    def entries(self, task_id: str) -> tuple[Any, ...]: ...


class OrchestratorError(OCORError):
    """A C8 AgentRun state transition was refused. ``reason_code``
    identifies why, mirroring the reason-code pattern already
    established by every other retained C1-C8 component this
    session."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True, slots=True)
class TaskAssignment:
    task_id: str
    agent_id: str
    capability: str
    assigned_by: str
    assigned_at: datetime


@dataclass(frozen=True, slots=True)
class Commitment:
    task_id: str
    agent_id: str
    committed_at: datetime


@dataclass(frozen=True, slots=True)
class Handoff:
    task_id: str
    from_agent_id: str
    to_agent_id: str
    reason: str
    handed_off_at: datetime


@dataclass(frozen=True, slots=True)
class Dissent:
    """An explicit, immutable record of disagreement -- never mutated,
    removed or retracted once registered."""

    task_id: str
    agent_id: str
    reason: str
    registered_at: datetime


class AgentRunOrchestrator:
    def __init__(self, *, authority: CapabilityAuthority, ledger: RunLedgerPort) -> None:
        if not isinstance(ledger, RunLedgerPort):
            raise TypeError("ledger must implement RunLedgerPort")
        self._authority = authority
        self._ledger = ledger
        self._assignments: dict[str, TaskAssignment] = {}
        self._commitments: dict[str, Commitment] = {}
        self._handoffs: list[Handoff] = []
        self._dissents: list[Dissent] = []

    @property
    def handoffs(self) -> tuple[Handoff, ...]:
        return tuple(self._handoffs)

    @property
    def dissents(self) -> tuple[Dissent, ...]:
        return tuple(self._dissents)

    def assignment(self, task_id: str) -> TaskAssignment | None:
        return self._assignments.get(task_id)

    def commitment(self, task_id: str) -> Commitment | None:
        return self._commitments.get(task_id)

    def _count(self, task_id: str, kind: str) -> int:
        return sum(1 for entry in self._ledger.entries(task_id) if getattr(entry, "kind", None) == kind)

    def _authorize(self, lease: CapabilityLease | str, capability: str, *, resource: str, subject: str, at: datetime) -> None:
        try:
            self._authority.authorize(lease, capability, resource, at=at, subject=subject, consume=True)
        except AuthorizationError as error:
            raise OrchestratorError("CAPABILITY_DENIED", str(error)) from error

    def assign(
        self,
        task_id: str,
        agent_id: str,
        *,
        capability: str,
        lease: CapabilityLease | str,
        assigned_by: str,
        at: datetime,
    ) -> TaskAssignment:
        instant = require_aware(at, field="at")
        self._authorize(lease, "agent:assign", resource=agent_id, subject=assigned_by, at=instant)
        assignment = TaskAssignment(task_id=task_id, agent_id=agent_id, capability=capability, assigned_by=assigned_by, assigned_at=instant)
        attempt = self._count(task_id, "TASK_ASSIGNED")
        self._ledger.append(
            idempotency_key=f"assign:{task_id}:{attempt}",
            task_id=task_id,
            kind="TASK_ASSIGNED",
            agent_id=agent_id,
            payload={"task_id": task_id, "agent_id": agent_id, "capability": capability, "assigned_by": assigned_by},
            recorded_at=instant,
        )
        self._assignments[task_id] = assignment
        return assignment

    def commit(self, task_id: str, *, lease: CapabilityLease | str, at: datetime) -> Commitment:
        instant = require_aware(at, field="at")
        assignment = self._assignments.get(task_id)
        if assignment is None:
            raise OrchestratorError("UNKNOWN_TASK", f"no assignment for {task_id!r}")
        self._authorize(lease, "agent:commit", resource=assignment.agent_id, subject=assignment.agent_id, at=instant)
        commitment = Commitment(task_id=task_id, agent_id=assignment.agent_id, committed_at=instant)
        attempt = self._count(task_id, "TASK_COMMITTED")
        self._ledger.append(
            idempotency_key=f"commit:{task_id}:{attempt}",
            task_id=task_id,
            kind="TASK_COMMITTED",
            agent_id=assignment.agent_id,
            payload={"task_id": task_id, "agent_id": assignment.agent_id},
            recorded_at=instant,
        )
        self._commitments[task_id] = commitment
        return commitment

    def handoff(self, task_id: str, *, to_agent_id: str, reason: str, lease: CapabilityLease | str, at: datetime) -> Handoff:
        instant = require_aware(at, field="at")
        commitment = self._commitments.get(task_id)
        if commitment is None:
            raise OrchestratorError("UNKNOWN_TASK", f"no commitment for {task_id!r}")
        if not reason:
            raise OrchestratorError("HANDOFF_REASON_REQUIRED", "a handoff requires an explicit reason")
        self._authorize(lease, "agent:handoff", resource=to_agent_id, subject=to_agent_id, at=instant)
        record = Handoff(task_id=task_id, from_agent_id=commitment.agent_id, to_agent_id=to_agent_id, reason=reason, handed_off_at=instant)
        self._ledger.append(
            idempotency_key=f"handoff:{task_id}:{self._count(task_id, 'TASK_HANDED_OFF')}",
            task_id=task_id,
            kind="TASK_HANDED_OFF",
            agent_id=to_agent_id,
            payload={"task_id": task_id, "from_agent_id": commitment.agent_id, "to_agent_id": to_agent_id, "reason": reason},
            recorded_at=instant,
        )
        self._handoffs.append(record)
        assignment = self._assignments[task_id]
        self._assignments[task_id] = replace(assignment, agent_id=to_agent_id)
        self._commitments[task_id] = replace(commitment, agent_id=to_agent_id, committed_at=instant)
        return record

    def register_dissent(self, task_id: str, agent_id: str, *, reason: str, lease: CapabilityLease | str, at: datetime) -> Dissent:
        instant = require_aware(at, field="at")
        if not reason:
            raise OrchestratorError("DISSENT_REASON_REQUIRED", "a dissent requires an explicit reason")
        self._authorize(lease, "agent:dissent", resource=agent_id, subject=agent_id, at=instant)
        record = Dissent(task_id=task_id, agent_id=agent_id, reason=reason, registered_at=instant)
        self._ledger.append(
            idempotency_key=f"dissent:{task_id}:{self._count(task_id, 'DISSENT_REGISTERED')}",
            task_id=task_id,
            kind="DISSENT_REGISTERED",
            agent_id=agent_id,
            payload={"task_id": task_id, "agent_id": agent_id, "reason": reason},
            recorded_at=instant,
        )
        self._dissents.append(record)
        return record
