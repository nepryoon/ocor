"""Test support of OCOR-DEV-REM-0053 (NCP-U07): preconditions of the C6 action FSM.

Since NCR-C6-003 every transition starts from its source state with its event/guard evaluated
(LLD v1.1 :260-305). ``PlacedActionStates`` is a test ``ActionStatePort`` that places an action
instance in a given source state, and ``satisfied`` builds the evaluation of a transition's
event/guard as satisfied for that action (with the stop observed for ACT-T23a/ACT-T23b), so a
test exercises a transition exactly from its precondition without persisting other effects.

Since NCR-C6-001, NCR-C6-002 and NCR-C6-008 the engine admits only a proposal pinned to a signed,
active ActionType (ADD v1.3 :2847), the ApprovalSet of the Human Gate and the Authority's signed
Decision on the frozen GatePackage (ADD v1.3 :2849-2850). ``ActionWorld`` builds them for the
engine suites.

Since NCR-C6-004 and NCR-C6-005 every send of the engine crosses the EMISSION-FENCE, which
consumes the signed CapabilityLease of the emission attempt (at most PT5S, bound to principal,
delegation, action, GCS, GatePackage, stop epoch and fencing token) in the transaction of the
DeliveryAttempt (ADD v1.3 :2851-2854, :3194-3212; LLD v1.1 :69-81). ``ActionWorld.lease`` signs
that lease with the capability authority of the suite, and ``ActionWorld.engine`` composes the
fence with the dispatch ledger and the dispatch conditions of the suite.

Since NCR-C6-007 the engine reconciles an ambiguous send through an ``OutcomeReconciler`` that
appends every record to the signed audit port (Register FR-163); ``ActionWorld.engine`` composes
one on the audit log of the suite, on the PostgreSQL of ``OCOR_LIVE_POSTGRES_DSN``, unless the
suite passes its own.

Since NCR-C6-009 a memory promotion commits through the same C6 path (ADD v1.3 :2789, LLD v1.1
:238): ``promotion_engine`` composes the engine of a promotion suite on its C3, and
``promotion_action`` builds the signed C6 records of one promotion (ActionProposal pinned to the
promotion ActionType, ApprovalSet, Decision and CapabilityLease) that the C6 control authority
holds for the recorded proposal.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any

from ocor_runtime.c6.fsm import (
    INITIAL_STATE,
    GuardEvaluation,
    InMemoryActionStateStore,
    STOP_TRANSITIONS,
)


class PlacedActionStates(InMemoryActionStateStore):
    def place(self, correlation_id: str, state: str) -> None:
        with self.transaction(correlation_id):
            if state == INITIAL_STATE:
                self._states.pop(correlation_id, None)
            else:
                self._states[correlation_id] = state


def satisfied(transition_id: str, correlation_id: str, at: datetime) -> GuardEvaluation:
    return GuardEvaluation(
        transition_id=transition_id,
        correlation_id=correlation_id,
        satisfied=True,
        snapshot_id=f"urn:ocor:snapshot:{correlation_id}:{transition_id}",
        evaluated_at=at,
        stop_requested=transition_id in STOP_TRANSITIONS,
    )


# NCR-C6-002 and the engine composition (iteration 3): the signed ActionType of the release,
# the Human Gate and the Authority of one engine suite.

PUBLISHER = "urn:ocor:principal:c1-release-publisher"
AUTHORITY = "urn:ocor:authority:national-duty"
LEASE_AUTHORITY = "urn:ocor:authority:c6-capability"
DOMAIN = "urn:ocor:human:domain-approver"
NATIONAL = "urn:ocor:human:national-approver"
MARKING = "urn:sha256:" + hashlib.sha256(b"marking:unclassified").hexdigest()


def seeded_key(label: str) -> Any:
    from ocor_runtime.c1.signing import Ed25519SigningKey

    return Ed25519SigningKey.from_seed(hashlib.sha256(label.encode("utf-8")).digest())


class _Release:
    def __init__(self, digest: str) -> None:
        self.digest = digest

    def active_release_digest(self) -> str:
        return self.digest


class RecordingTrace:
    """The durable effect sink of a suite's FSM: every persisted transition, in order."""

    def __init__(self) -> None:
        self.effects: list[Any] = []
        self._lock = threading.Lock()

    def persist_effect(self, record: Any) -> None:
        with self._lock:
            self.effects.append(record)


class ActionWorld:
    """The ActionType catalog, Human Gate, Decision gate and signers of an engine suite: the
    publisher signs the ActionTypes of the release, two human approvers (Domain and National
    Approver) sign the Approvals and the Authority signs the Decision on the frozen package."""

    def __init__(self, *, now: datetime, release: str) -> None:
        from ocor_runtime.c2_identity import IdentityRecord, IdentityRegistry
        from ocor_runtime.c6 import contract, human_gate
        from ocor_runtime.kernel.governance import InMemoryTrustedClock

        self.contract_module = contract
        self.gate_module = human_gate
        self.clock = InMemoryTrustedClock(now)
        self.release = _Release(release)
        self.identities = IdentityRegistry(
            IdentityRecord(
                canonical_id=principal,
                attributes={"principal_kind": "HUMAN", "status": "ACTIVE", "roles": role},
            )
            for principal, role in ((DOMAIN, "DOMAIN_APPROVER"), (NATIONAL, "NATIONAL_APPROVER"))
        )
        self.publishers = human_gate.InMemorySignerKeyring()
        self.publishers.register(PUBLISHER, "k1", seeded_key(PUBLISHER).public_key)
        self.approvers = human_gate.InMemorySignerKeyring()
        for principal in (DOMAIN, NATIONAL):
            self.approvers.register(principal, "k1", seeded_key(principal).public_key)
        self.authorities = human_gate.InMemorySignerKeyring()
        self.authorities.register(AUTHORITY, "k1", seeded_key(AUTHORITY).public_key)
        self.catalog = contract.InMemoryActionTypeCatalog()
        self.contract = contract.ContractGate(catalog=self.catalog, publishers=self.publishers, releases=self.release)
        self.approval_gate = human_gate.ApprovalGate(
            identities=self.identities,
            approvers=self.approvers,
            releases=self.release,
            clock=self.clock,
            signing_key=seeded_key("c6-human-gate"),
            gate_id="urn:ocor:component:c6:human-gate",
            keyid="gate-k1",
        )
        self.decision_gate = human_gate.DecisionGate(
            authorities=self.authorities, approval_gate=self.approval_gate, clock=self.clock
        )
        self.granted: dict[str, Any] = {}
        # NCR-C6-004/005: the capability authority signs the leases; the engine's EMISSION-FENCE
        # verifies them with its keyring and consumes them in the dispatch ledger (composed by
        # ``engine``).
        self.lease_issuers = human_gate.InMemorySignerKeyring()
        self.lease_issuers.register(LEASE_AUTHORITY, "k1", seeded_key(LEASE_AUTHORITY).public_key)
        self.delegation_ref = "urn:sha256:" + hashlib.sha256(b"delegation:c6-engine-suite").hexdigest()
        self.dispatch_module: Any = None
        self.validator: Any = None
        self.delegations: Any = None
        self.context: Any = None
        self.ledger: Any = None
        self.conditions: Any = None
        self.emission_fence: Any = None
        self.reconciler: Any = None
        self.fsm: Any = None
        self.trace: RecordingTrace | None = None
        self._path: Any = None

    def action_type(
        self,
        action_type_ref: str,
        *,
        risk: str,
        capability: str,
        canonical_target: bool = True,
        parameters: dict[str, str] | None = None,
        publish: bool = True,
        **overrides: Any,
    ) -> Any:
        from ocor_runtime.kernel.governance import RiskClass

        risk_class = RiskClass[risk]
        values: dict[str, Any] = {
            "action_type_ref": action_type_ref,
            "version": 1,
            "status": "ACTIVE",
            "effect_class": "CANONICAL_COMMIT",
            "risk_class": risk_class,
            "capability": capability,
            "canonical_target": canonical_target,
            "parameters": parameters or {},
            "timeout_seconds": 30,
            "max_attempts": 3,
            "idempotency_scope": "ACTION_INSTANCE",
            "compensable": True,
            "compensation_ref": f"{action_type_ref}:compensation",
            "irreversibility_class": "COMPENSABLE",
            "marking_ref": MARKING,
            "provenance_ref": f"{action_type_ref}:provenance",
            "release_digest": self.release.digest,
            "publisher_id": PUBLISHER,
            "keyid": "k1",
        }
        signer = overrides.pop("signer", PUBLISHER)
        values.update(overrides)
        action_type = self.contract_module.sign_action_type(seeded_key(signer), **values)
        if publish:
            self.catalog.publish(action_type)
        return action_type

    def proposal(
        self,
        action_type: Any,
        *,
        action_id: str,
        proposer: str,
        target: str,
        governed_context_digest: str,
        parameters: dict[str, Any] | None = None,
        evidence_refs: tuple[str, ...] = ("urn:ocor:evidence:consumer-suite:engine",),
        **overrides: Any,
    ) -> Any:
        proposal = self.contract_module.proposal_for(
            action_type,
            action_instance_id=action_id,
            proposer_id=proposer,
            target_ref=target,
            parameters=parameters or {},
            governed_context_digest=governed_context_digest,
            expected_revision=0,
            evidence_refs=evidence_refs,
            proposed_at=self.clock.now() - timedelta(minutes=5),
        )
        return dataclasses.replace(proposal, **overrides) if overrides else proposal

    def approvals(self, proposal: Any) -> tuple[Any, ...]:
        signed_at = self.clock.now() - timedelta(minutes=1)
        approvers = ((DOMAIN, "DOMAIN_APPROVER"), (NATIONAL, "NATIONAL_APPROVER"))
        if proposal.risk_class.name != "R3_HIGH_IMPACT":
            approvers = approvers[:1]
        return tuple(
            self.gate_module.sign_approval(
                seeded_key(principal),
                keyid="k1",
                approval_id=f"urn:ocor:approval:{uuid.uuid4()}",
                proposal=proposal,
                release_digest=self.release.digest,
                approver_id=principal,
                role=role,
                signed_at=signed_at,
                expires_at=signed_at + timedelta(hours=1),
            )
            for principal, role in approvers
        )

    def approval_set(self, proposal: Any) -> Any:
        return self.approval_gate.assemble(
            proposal, self.approvals(proposal), approval_set_id=f"urn:ocor:approval-set:{uuid.uuid4()}"
        )

    def ungranted(self, approval_set: Any) -> Any:
        """An ApprovalSet the Human Gate did not grant: the gate's signature is absent."""

        return dataclasses.replace(approval_set, signature=base64.b64encode(bytes(64)).decode("ascii"))

    def decide(
        self,
        proposal: Any,
        approval_set: Any,
        *,
        accepted: bool = True,
        rationale: str = "within the approved risk ceiling",
        stop_epoch: int | None = None,
    ) -> Any:
        from ocor_runtime.c6 import engine

        now = self.clock.now()
        action_type = self.catalog.action_type(proposal.action_type_ref)
        # The values the EMISSION-FENCE compares at the send (G-FRESHNESS): the policy bundle of
        # the engine's GovernedContext, the C3 commit and watermark of the expected revision and
        # the C3 governed-commit adapter.
        policy = (
            self.context.policy_bundle_digest
            if self.context is not None
            else "urn:sha256:" + hashlib.sha256(b"policy-bundle").hexdigest()
        )
        if stop_epoch is None:
            # The stop epoch current when the package is frozen (G-DISPATCH compares it).
            stop_epoch = self.conditions.current_stop_epoch() if self.conditions is not None else 0
        package = engine.freeze_gate_package(
            proposal,
            approval_set,
            action_type=action_type,
            authority_ref=AUTHORITY,
            policy_bundle_digest=policy,
            ontology_release_digest=self.release.digest,
            stop_epoch=stop_epoch,
            canonical_commit_ref=engine.canonical_commit_ref(proposal.target_ref, proposal.expected_revision),
            adapter_binding_digest=engine.C3_ADAPTER_BINDING_DIGEST,
            projection_watermark=engine.projection_watermark(proposal.expected_revision),
            valid_from=now - timedelta(minutes=2),
            valid_until=now + timedelta(minutes=30),
            conflict_scope_digest="urn:sha256:" + hashlib.sha256(proposal.target_ref.encode("utf-8")).hexdigest(),
            expected_effects=(f"{proposal.action_type_ref}:effect",),
            compensation_ref=action_type.compensation_ref,
            artifact_digest=proposal.digest(),
            frozen_at=now,
        )
        decision = self.gate_module.sign_decision(
            seeded_key(AUTHORITY),
            keyid="k1",
            decision_id=f"urn:ocor:decision:{uuid.uuid4()}",
            authority_id=AUTHORITY,
            proposal=proposal,
            gate_package_digest=package.digest(),
            outcome="ACCEPT" if accepted else "REJECT",
            rationale=rationale,
            valid_from=now - timedelta(minutes=1),
            valid_until=now + timedelta(minutes=5),
            decided_at=now,
        )
        return engine.AuthorizedDecision(decision=decision, package=package, package_digest=package.digest())

    def engine(self, **components: Any) -> Any:
        from ocor_runtime.c6 import engine

        from ocor_runtime.c6 import dispatch

        path = components["canonical_path"]
        if self.dispatch_module is None:
            self.dispatch_module = dispatch
            self.validator = dispatch.LeaseValidator(issuers=self.lease_issuers, clock=self.clock)
            self.delegations = dispatch.InMemoryDelegationRegistry()
        if path is not self._path:
            # One dispatch ledger and fence per canonical path (C3 and its mutation fence).
            self._path = path
            self.context = path.governed_context
            self.delegations.register(self.context.effective_principal_id, self.delegation_ref)
            self.conditions = dispatch.InMemoryDispatchConditions(stop=path.fence)
            self.ledger = dispatch.InMemoryDispatchLedger()
            self.emission_fence = dispatch.GovernedEmissionFence(
                validator=self.validator, ledger=self.ledger, conditions=self.conditions, clock=self.clock
            )
        if "reconciler" not in components:
            components["reconciler"] = self.audited_reconciler()
        # NCR-C6-014: every engine drives its own FSM and records its durable effects in order.
        if "fsm" not in components:
            from ocor_runtime.c6.fsm import GovernedActionFSM

            self.fsm = GovernedActionFSM()
            self.trace = RecordingTrace()
            components["fsm"] = self.fsm
            components["trace"] = self.trace
        return engine.GovernedActionEngine(
            contract=self.contract,
            approvals=self.approval_gate,
            decisions=self.decision_gate,
            delegations=self.delegations,
            emission_fence=self.emission_fence,
            **components,
        )

    def transitions(self, correlation_id: str) -> list[str]:
        """The transitions the last engine persisted for ``correlation_id``, in order."""
        if self.trace is None:
            return []
        return [item.transition_id for item in self.trace.effects if item.correlation_id == correlation_id]

    def audited_reconciler(self) -> Any:
        """The C6 reconciler of the suite, appending to the audit log of the suite on PostgreSQL."""
        if self.reconciler is None:
            import os

            from ocor_runtime import audit
            from ocor_runtime.c6.safety import OutcomeReconciler

            dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
            if not dsn:
                raise RuntimeError("OCOR_LIVE_POSTGRES_DSN is mandatory: the reconciliation audit is on PostgreSQL")
            log = audit.PostgresAuditLog(
                dsn,
                schema="ocor_audit_c6_action_world",
                signer=audit.AuditSigner(key=seeded_key("c6-action-world-audit"), keyid="c6-action-world-audit"),
            )
            log.initialize()
            self.reconciler = OutcomeReconciler(audit=log)
        return self.reconciler

    def lease(self, proposal: Any, decision: Any = None, *, signer: str = LEASE_AUTHORITY, **fields: Any) -> Any:
        """The signed CapabilityLease of the next emission attempt of ``proposal``, issued now for
        at most PT5S by the capability authority and bound to the GatePackage of ``decision``."""
        from ocor_runtime.kernel.governance import CapabilityLease

        dispatch = self.dispatch_module
        issuer_id = fields.pop("issuer_id", LEASE_AUTHORITY)
        now = self.clock.now()
        action_type = self.catalog.action_type(proposal.action_type_ref)
        package_digest = getattr(decision, "package_digest", None) or (
            "urn:sha256:" + hashlib.sha256(b"no-gate-package").hexdigest()
        )
        values: dict[str, Any] = {
            "lease_id": f"urn:ocor:lease:{uuid.uuid4()}",
            "capability_id": action_type.capability if action_type is not None else "act:unknown",
            "effective_principal_id": self.context.effective_principal_id,
            "delegation_ref": self.delegation_ref,
            "action_instance_id": proposal.action_instance_id,
            "governed_context_digest": proposal.governed_context_digest,
            "gate_package_digest": package_digest,
            "stop_epoch": self.conditions.current_stop_epoch(),
            "fencing_token": self.ledger.fencing_token(proposal.action_instance_id),
            "issued_at": now,
            "expires_at": now + dispatch.MAX_LEASE_TTL,
        }
        values.update(fields)
        return dispatch.sign_capability_lease(
            seeded_key(signer), issuer_id=issuer_id, keyid="k1", lease=CapabilityLease(**values)
        )


# NCR-C6-009: the C6 records of a memory promotion, on the same path as every canonical mutation.

PROMOTION_PARAMETERS = {"proposal_audit_ref": "string", "proposal_digest": "string"}


def promotion_engine(world: ActionWorld, *, governed: Any, c3: Any, context: Any, aggregate_type: str = "Situation") -> Any:
    """The engine of a promotion suite: the canonical path of ``context`` on the suite's C3."""
    from ocor_runtime.c6 import engine
    from ocor_runtime.c7_emission import EmissionFence

    store = engine.C3CanonicalOutboxView(c3, tenant_id=context.tenant_id, aggregate_type=aggregate_type)
    return world.engine(
        commit_port=c3,
        relay=EmissionFence(store=store),  # type: ignore[arg-type]
        canonical_path=governed.engine_path(aggregate_type=aggregate_type, governed_context=context),
        emission_outbox=store,
    )


def promotion_action(
    world: ActionWorld,
    *,
    proposal_audit_ref: str,
    proposal: Any,
    command: Any,
    risk: str = "R2_CONTROLLED",
    capability: str = "canonical.commit",
    accepted: bool = True,
    lease_fields: dict[str, Any] | None = None,
    **overrides: Any,
) -> Any:
    """The signed C6 records of the promotion of ``proposal`` by the gate ``command``: the
    ActionProposal of the promotion ActionType (risk class and capability of the type), the
    ApprovalSet of the Human Gate, the Authority's Decision on the frozen GatePackage and the
    CapabilityLease of the emission attempt. R0 and R1 admit no Approval and no Decision."""
    from ocor_runtime.memory.promotion import PromotionAction, promotion_parameters

    reference = f"urn:ocor:action-type:memory-promotion:{risk.lower()}:{capability}"
    action_type = world.catalog.action_type(reference) or world.action_type(
        reference, risk=risk, capability=capability, parameters=dict(PROMOTION_PARAMETERS)
    )
    values: dict[str, Any] = {
        "action_id": command["action_instance_id"],
        "proposer": world.context.effective_principal_id,
        "target": command["aggregate_ref"],
        "governed_context_digest": command["governed_context_digest"],
        "parameters": promotion_parameters(proposal_audit_ref, proposal),
        "evidence_refs": tuple(command["evidence_refs"]),
    }
    values.update(overrides)
    action_proposal = world.proposal(action_type, **values)
    if risk in ("R0_INFORMATIONAL", "R1_LOW"):
        return PromotionAction(proposal=action_proposal, approval=None, decision=None,
                               lease=world.lease(action_proposal, None, **(lease_fields or {})))
    approval_set = world.approval_set(action_proposal)
    decision = world.decide(action_proposal, approval_set, accepted=accepted)
    return PromotionAction(
        proposal=action_proposal,
        approval=approval_set,
        decision=decision,
        lease=world.lease(action_proposal, decision, **(lease_fields or {})),
    )
