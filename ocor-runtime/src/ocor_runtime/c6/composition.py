"""C6 -- composition root of the governed action path (OCOR-DEV-REM-0053, NCP-U07, NCR-C6-014).

LLD v1.1 :169-171 names the packages of C6 (proposal, control, approval, decision, dispatch,
reconcile, outcome) and the distinct records of the action path; ADD v1.3 :3318-3331 orders risk,
policy, authority, Human Gate, ApprovalSet, Decision, recheck and dispatch; Register FR-008 :59 and
FR-077 :209 ask for a runtime trace that holds every state and every mandatory record in canonical
order. ``C6ActionPathRoot`` builds those pieces once and composes them into the engine:

* G-CONTRACT (``ContractGate``), the Human Gate (``ApprovalGate``, which assembles and verifies the
  signed ApprovalSet of LLD v1.1 ``ocor.c6.approval``) and G-DECISION (``DecisionGate``);
* the dispatch of LLD v1.1 :69-81: ``LeaseValidator`` over the keyring of the capability
  authority, the dispatch ledger, the dispatch conditions and the ``GovernedEmissionFence``;
* the safety of ADD v1.3 :3360 and :3220: one ``EmergencyStopController`` whose stop epoch and
  emergency stop are the ``MutationFencePort`` of the dispatch conditions, of the canonical path
  and of the C3 admission (``mutation_fence``), and the ``BreakGlassController`` bound to the same
  stop, which never overrides it;
* the reconciliation: one ``OutcomeReconciler`` appending to the signed audit port (FR-163);
* the 44-transition ``GovernedActionFSM`` whose durable effects are appended to the same signed,
  hash-linked audit chain before the state advances (``AuditedTransitionTrace``).

The engine is composed only on a canonical path fenced on the composed emergency stop.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from ..audit import AuditEvent, AuditPort
from ..c1.signing import Ed25519SigningKey
from ..c2_identity import IdentityRegistry
from ..c7_emission import EmissionFence
from ..kernel.governance import TrustedClock
from .contract import ActionTypeCatalog, ContractGate
from .dispatch import (
    DelegationPort,
    GovernedEmissionFence,
    InMemoryDispatchConditions,
    InMemoryDispatchLedger,
    LeaseValidator,
)
from .engine import C3CanonicalOutboxView, CanonicalCommitPath, CanonicalCommitTarget, GovernedActionEngine
from .fsm import ActionStatePort, GovernedActionFSM, InMemoryActionStateStore, PersistedEffect
from .human_gate import ActiveReleasePort, ApprovalGate, DecisionGate, SignerKeyring
from .safety import BreakGlassAlertSink, BreakGlassController, EmergencyStopController, OutcomeReconciler, StopStatus

TRANSITION_EVENT = "C6_ACTION_TRANSITION"
BREAK_GLASS_EVENT = "C6_BREAK_GLASS"
C6_ACTOR = "urn:ocor:component:c6"
_TRANSITION_FIELDS = frozenset({"source", "destination", "durable_effect"})


class EmergencyStopFence:
    """The ``MutationFencePort`` of the composed path: the stop epoch and the emergency stop of the
    C6 ``EmergencyStopController`` (a stop that is not ``NORMAL`` blocks every mutation) and the
    active release of C1."""

    def __init__(self, *, stop: EmergencyStopController, releases: ActiveReleasePort) -> None:
        if not isinstance(stop, EmergencyStopController):
            raise TypeError("stop must be the EmergencyStopController")
        if not callable(getattr(releases, "active_release_digest", None)):
            raise TypeError("releases must implement ActiveReleasePort")
        self._stop = stop
        self._releases = releases

    def current_stop_epoch(self) -> int:
        return self._stop.epoch

    def emergency_stop_active(self) -> bool:
        return self._stop.status is not StopStatus.NORMAL

    def active_release_digest(self) -> str:
        return self._releases.active_release_digest()


class AuditedTransitionTrace:
    """Durable effect sink of the FSM: every transition with the record it persists is appended to
    the signed audit chain; an append that fails leaves the state of the action unchanged."""

    def __init__(self, audit: AuditPort, *, actor: str = C6_ACTOR) -> None:
        if not isinstance(audit, AuditPort):
            raise TypeError("audit must implement the AuditPort")
        if not isinstance(actor, str) or not actor:
            raise ValueError("actor is required")
        self._audit = audit
        self._actor = actor

    def persist_effect(self, record: PersistedEffect) -> None:
        if not isinstance(record, PersistedEffect):
            raise TypeError("the trace persists PersistedEffect records only")
        context = dict(record.context)
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in context.items()):
            raise ValueError("the trace context is text")
        if not _TRANSITION_FIELDS.isdisjoint(context):
            raise ValueError("the trace context never overrides the source, destination or durable effect")
        self._audit.append(
            AuditEvent(
                event_type=TRANSITION_EVENT,
                actor=self._actor,
                occurred_at=record.occurred_at,
                resource=record.correlation_id,
                reason_code=record.transition_id,
                authority_ref=self._actor,
                correlation_id=record.correlation_id,
                outcome="PERMITTED",
                detail={
                    "source": record.source,
                    "destination": record.destination,
                    "durable_effect": record.durable_effect,
                    **context,
                },
            )
        )


class AuditedBreakGlassSink:
    """The break-glass audit sink on the signed audit chain: every grant, use, refusal and
    revocation is one record, appended synchronously."""

    def __init__(self, audit: AuditPort, *, actor: str = C6_ACTOR) -> None:
        if not isinstance(audit, AuditPort):
            raise TypeError("audit must implement the AuditPort")
        self._audit = audit
        self._actor = actor

    def record(self, event: Mapping[str, object]) -> None:
        kind = event.get("event")
        at = event.get("at")
        if not isinstance(kind, str) or not kind or not isinstance(at, str):
            raise ValueError("a break-glass event has a kind and an instant")
        resource = event.get("grant_id")
        self._audit.append(
            AuditEvent(
                event_type=BREAK_GLASS_EVENT,
                actor=self._actor,
                occurred_at=_aware(at),
                resource=resource if isinstance(resource, str) and resource else "urn:ocor:break-glass:request",
                reason_code=kind,
                authority_ref=self._actor,
                correlation_id=resource if isinstance(resource, str) and resource else kind,
                outcome="DENIED" if kind.endswith(("_DENIED", "_WITHDRAWN")) else "PERMITTED",
                detail={key: value for key, value in event.items() if key not in ("event", "at")},
            )
        )


def _aware(value: str) -> datetime:
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("a break-glass instant must be timezone-aware")
    return instant


class C6ActionPathRoot:
    """Builds the C6 action path once and composes the engine on it."""

    def __init__(
        self,
        *,
        clock: TrustedClock,
        releases: ActiveReleasePort,
        identities: IdentityRegistry,
        catalog: ActionTypeCatalog,
        publishers: SignerKeyring,
        approvers: SignerKeyring,
        authorities: SignerKeyring,
        lease_issuers: SignerKeyring,
        delegations: DelegationPort,
        audit: AuditPort,
        alerts: BreakGlassAlertSink,
        gate_signing_key: Ed25519SigningKey,
        gate_id: str,
        gate_keyid: str,
        states: ActionStatePort | None = None,
        ledger: InMemoryDispatchLedger | None = None,
    ) -> None:
        if not isinstance(audit, AuditPort):
            raise TypeError("audit must implement the AuditPort")
        if not isinstance(delegations, DelegationPort):
            raise TypeError("delegations must implement DelegationPort")
        self.clock = clock
        self.delegations = delegations
        # G-CONTRACT, the Human Gate and G-DECISION.
        self.contract = ContractGate(catalog=catalog, publishers=publishers, releases=releases)
        self.approval_gate = ApprovalGate(
            identities=identities,
            approvers=approvers,
            releases=releases,
            clock=clock,
            signing_key=gate_signing_key,
            gate_id=gate_id,
            keyid=gate_keyid,
        )
        self.decision_gate = DecisionGate(authorities=authorities, approval_gate=self.approval_gate, clock=clock)
        # Safety: one emergency stop for dispatch, canonical path and C3, and the break-glass.
        self.stop = EmergencyStopController()
        self.mutation_fence = EmergencyStopFence(stop=self.stop, releases=releases)
        self.break_glass = BreakGlassController(
            identities=identities, stop=self.stop, clock=clock, audit=AuditedBreakGlassSink(audit), alerts=alerts
        )
        # Dispatch: the signed lease, the ledger, the conditions and the EMISSION-FENCE.
        self.validator = LeaseValidator(issuers=lease_issuers, clock=clock)
        self.ledger = ledger if ledger is not None else InMemoryDispatchLedger()
        self.conditions = InMemoryDispatchConditions(stop=self.mutation_fence)
        self.emission_fence = GovernedEmissionFence(
            validator=self.validator, ledger=self.ledger, conditions=self.conditions, clock=clock
        )
        # Reconciliation and the FSM with its audited trace.
        self.reconciler = OutcomeReconciler(audit=audit)
        self.fsm = GovernedActionFSM(states=states if states is not None else InMemoryActionStateStore())
        self.trace = AuditedTransitionTrace(audit)

    def engine(
        self,
        *,
        commit_port: CanonicalCommitTarget,
        relay: EmissionFence,
        canonical_path: CanonicalCommitPath,
        emission_outbox: C3CanonicalOutboxView | None = None,
    ) -> GovernedActionEngine:
        if not isinstance(canonical_path, CanonicalCommitPath):
            raise TypeError("canonical_path must be a CanonicalCommitPath")
        if canonical_path.fence is not self.mutation_fence:
            raise ValueError("the canonical path must fence on the composed emergency stop")
        return GovernedActionEngine(
            contract=self.contract,
            approvals=self.approval_gate,
            decisions=self.decision_gate,
            delegations=self.delegations,
            emission_fence=self.emission_fence,
            commit_port=commit_port,
            relay=relay,
            canonical_path=canonical_path,
            reconciler=self.reconciler,
            fsm=self.fsm,
            trace=self.trace,
            emission_outbox=emission_outbox,
        )


__all__ = [
    "BREAK_GLASS_EVENT",
    "TRANSITION_EVENT",
    "AuditedBreakGlassSink",
    "AuditedTransitionTrace",
    "C6ActionPathRoot",
    "EmergencyStopFence",
]
