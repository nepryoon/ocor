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
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
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
        stop_epoch: int = 0,
    ) -> Any:
        from ocor_runtime.c6 import engine

        now = self.clock.now()
        action_type = self.catalog.action_type(proposal.action_type_ref)
        package = engine.freeze_gate_package(
            proposal,
            approval_set,
            action_type=action_type,
            authority_ref=AUTHORITY,
            policy_bundle_digest="urn:sha256:" + hashlib.sha256(b"policy-bundle").hexdigest(),
            ontology_release_digest=self.release.digest,
            stop_epoch=stop_epoch,
            canonical_commit_ref=f"urn:ocor:commit:{proposal.target_ref}:{proposal.expected_revision}",
            adapter_binding_digest="urn:sha256:" + hashlib.sha256(b"c3-governed-commit").hexdigest(),
            projection_watermark=f"urn:ocor:watermark:{proposal.expected_revision}",
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

        return engine.GovernedActionEngine(
            contract=self.contract, approvals=self.approval_gate, decisions=self.decision_gate, **components
        )
