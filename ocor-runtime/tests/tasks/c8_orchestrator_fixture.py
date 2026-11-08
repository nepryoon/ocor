"""The real collaborators of the C8 AgentRun orchestrator (OCOR-DEV-REM-0058, NCP-U10), shared by
the unit module and by the tests of OCOR-DEV-0046 and OCOR-DEV-REM-0050 that exercise it.

A team run is started by its Coordinator over the PostgreSQL Run Ledger (``OCOR_LIVE_POSTGRES_DSN``);
the coordination capabilities are leases of the sealed ``CapabilityAuthority``; the Coordination
Kernel reads the verified Delegation of every member, the policy decision point (permitting unless
the test switches it), the signed stop epoch and the multidimensional budget live, validates every
typed output and handoff payload against its pinned schema, signs every HandoffEnvelope and writes
every rejected handoff to the signed audit chain on the same PostgreSQL.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from ocor_runtime import audit
from ocor_runtime.c4.marking_resolution import ResolvedMarkingEngine
from ocor_runtime.c4_marking import MarkingSchemeDefinition, MarkingSet
from ocor_runtime.c6_capabilities import CapabilityAuthority
from ocor_runtime.c8 import orchestrator as orchestration
from ocor_runtime.c8 import tool_runtime
from ocor_runtime.c8.tool_contract import SchemaCatalog, SchemaPin, wire_digest
from ocor_runtime.kernel.governed_context import GovernedContext
from ocor_runtime.security.ports import AuthenticatedPrincipal, ControlName, ControlStatus, PolicyDecision, PolicyEffect

from c6_action_fixture import seeded_key
from c6_safety_fixture import INCIDENT, SAFETY_OFFICER, stop_controller

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
TENANT = "t1"
ESCALATION_TARGET = "urn:ocor:human:mission-owner"
KERNEL_KEYID = "urn:ocor:key:c8-coordination-kernel"
MODEL_PIN = "urn:sha256:" + "1" * 64
INSTRUCTION_PIN = "urn:sha256:" + "2" * 64
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["summary"],
    "properties": {"summary": {"type": "string", "minLength": 1, "maxLength": 256}},
}
HANDOFF_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["state_summary"],
    "properties": {"state_summary": {"type": "string", "minLength": 1, "maxLength": 512}},
}
DEFAULT_MEMBERS: tuple[tuple[str, str], ...] = (
    ("team-lead-1", "COORDINATOR"),
    ("agent-1", "HYPOTHESIS"),
    ("agent-2", "HYPOTHESIS"),
    ("agent-3", "CHALLENGER"),
    ("agent-4", "CAUSAL"),
)


CONTEXT_MARKING_REF = "urn:sha256:" + "a" * 64


def marking_engine() -> ResolvedMarkingEngine:
    return ResolvedMarkingEngine([MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET", "TOP_SECRET"))])


def delegation_of(agent_id: str) -> str:
    return "urn:sha256:" + uuid.uuid5(uuid.NAMESPACE_URL, f"delegation:{agent_id}").hex * 2


def context(agent_id: str, *, purpose: str = "incident-response", tenant: str = TENANT) -> GovernedContext:
    return GovernedContext(
        tenant_id=tenant,
        organization_id="o1",
        domain_id="d1",
        compartments=("default",),
        classification_marking_ref=CONTEXT_MARKING_REF,
        purpose=purpose,
        effective_principal_id=agent_id,
        actor_chain=(agent_id,),
        ontology_release_digest="urn:sha256:" + "b" * 64,
        policy_bundle_digest="urn:sha256:" + "c" * 64,
        correlation_id="urn:ocor:correlation:c8-orchestrator",
    )


def principal(agent_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        principal_id=agent_id,
        session_id=f"urn:ocor:session:{agent_id}",
        actor_chain=(agent_id,),
        assurance_level="spiffe-svid",
        authenticated_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=2),
        status=ControlStatus.available(ControlName.IDENTITY, observed_at=NOW, source_digest="urn:sha256:" + "9" * 64),
    )


def caller(agent_id: str, **context_changes: Any) -> dict[str, Any]:
    """The transport principal and Governed Context of a call made by ``agent_id``."""
    return {"principal": principal(agent_id), "context": context(agent_id, **context_changes)}


class SwitchablePolicy:
    """``security.ports.PolicyDecisionPort``; ``effect`` applies to every request, or ``by_action``
    to the requests of one action; every request is recorded."""

    def __init__(self) -> None:
        self.effect = "PERMIT"
        self.by_action: dict[str, str] = {}
        self.unavailable = False
        self.requests: list[Any] = []

    def evaluate(self, request: Any) -> PolicyDecision:
        self.requests.append(request)
        if self.unavailable:
            raise RuntimeError("policy decision point unreachable")
        effect = PolicyEffect(self.by_action.get(request.action, self.effect))
        obligations = ("urn:ocor:approval:c8-coordination",) if effect is PolicyEffect.REQUIRE_APPROVAL else ()
        return PolicyDecision.from_request(
            request,
            effect=effect,
            decision_id=f"urn:ocor:policy-decision:c8:{len(self.requests)}",
            valid_until=request.at + timedelta(hours=1),
            status=ControlStatus.available(
                ControlName.POLICY, observed_at=request.at, source_digest=request.governed_context.policy_bundle_digest
            ),
            obligations=obligations,
        )


def quota(**changes: int) -> tool_runtime.BudgetQuota:
    values = {
        "tool_calls": 100,
        "steps": 100,
        "tokens": 10_000,
        "cost": 10_000,
        "wall_time_ms": 600_000,
        "compute_ms": 600_000,
        "risk_exposure": 100,
    }
    values.update(changes)
    return tool_runtime.BudgetQuota(**values)


def output_contracts(schemas: SchemaCatalog) -> tuple[orchestration.OutputContract, ...]:
    contracts = []
    for output_type in sorted({name for names in orchestration.ROLE_OUTPUTS.values() for name in names}):
        schema_id = f"urn:ocor:schema:c8:{output_type.split('@', 1)[0]}"
        schemas.add(schema_id, "1.0.0", OUTPUT_SCHEMA)
        contracts.append(
            orchestration.OutputContract(
                output_type=output_type,
                contract_id=f"urn:ocor:contract:c8:{output_type.split('@', 1)[0]}",
                contract_version="1.0.0",
                schema=SchemaPin(schema_id, "1.0.0", wire_digest(OUTPUT_SCHEMA)),
            )
        )
    return tuple(contracts)


def handoff_contract(schemas: SchemaCatalog) -> orchestration.OutputContract:
    schemas.add("urn:ocor:schema:c8:TaskHandoff", "1.0.0", HANDOFF_SCHEMA)
    return orchestration.OutputContract(
        output_type="TaskHandoff@1",
        contract_id="urn:ocor:contract:c8:TaskHandoff",
        contract_version="1.0.0",
        schema=SchemaPin("urn:ocor:schema:c8:TaskHandoff", "1.0.0", wire_digest(HANDOFF_SCHEMA)),
    )


def audit_log(dsn: str, schema: str = "ocor_audit_c8_orchestrator") -> Any:
    log = audit.PostgresAuditLog(
        dsn, schema=schema, signer=audit.AuditSigner(key=seeded_key("c8-orchestrator-audit"), keyid="c8-orchestrator-audit")
    )
    log.initialize()
    return log


def live_dsn() -> str:
    value = os.environ.get("OCOR_LIVE_POSTGRES_DSN", "")
    if not value:
        raise RuntimeError("OCOR_LIVE_POSTGRES_DSN is mandatory: the C8 Run Ledger and the audit chain are on PostgreSQL")
    return value


class TeamWorld:
    """A started team run and every collaborator of its orchestrator."""

    def __init__(
        self,
        dsn: str,
        *,
        authority: CapabilityAuthority | None = None,
        ledger: Any = None,
        members: tuple[tuple[str, str], ...] = DEFAULT_MEMBERS,
        tiers: dict[str, str] | None = None,
        termination: orchestration.TerminationCondition | None = None,
        team_run_id: str | None = None,
    ) -> None:
        from ocor_runtime.c8.adapters.postgres_ledger import PostgresRunLedger

        self.dsn = dsn
        self.authority = authority or CapabilityAuthority(issuer="ocor-c8-orchestrator-authority")
        if ledger is None:
            ledger = PostgresRunLedger(dsn)
            ledger.initialize()
        self.ledger = ledger
        self.audit = audit_log(dsn)
        self.stop = stop_controller()
        self.controls = tool_runtime.InMemoryGovernanceControls()
        self.policy = SwitchablePolicy()
        self.budgets = tool_runtime.AgentBudgetLedger()
        self.schemas = SchemaCatalog()
        self.kernel_key = seeded_key("c8-coordination-kernel")
        # the Governed Context of the team is SECRET; every member is cleared TOP_SECRET
        self.markings = orchestration.InMemoryCoordinationMarkings()
        self.markings.define(CONTEXT_MARKING_REF, MarkingSet({"classification": "SECRET"}))
        self.members = {}
        tiers = tiers or {}
        self.team_run_id = team_run_id or f"urn:ocor:team-run:{uuid.uuid4()}"
        for agent_id, role in members:
            binding = self.binding(agent_id, tier=tiers.get(agent_id, "PROPOSE" if role == "COORDINATOR" else "ANALYZE"))
            self.members[agent_id] = orchestration.TeamMember(role=orchestration.AgentRole[role], binding=binding)
            self.controls.bind_delegation(agent_id, delegation_of(agent_id))
            self.markings.set_clearance(agent_id, MarkingSet({"classification": "TOP_SECRET"}))
            for level, key in (("agent", agent_id), ("run", binding.agent_run_id)):
                self.budgets.set_quota(level, key, quota())
        self.budgets.set_quota("team", "team-1", quota(steps=1000))
        self.budgets.set_quota("tenant", TENANT, quota(steps=1000))
        self.kernel = orchestration.CoordinationKernel(
            controls=self.controls,
            policy=self.policy,
            stop=self.stop.reader,
            budgets=self.budgets,
            schemas=self.schemas,
            contracts=output_contracts(self.schemas),
            handoff_contract=handoff_contract(self.schemas),
            audit=self.audit,
            signing_key=self.kernel_key,
            keyid=KERNEL_KEYID,
            marking_engine=marking_engine(),
            markings=self.markings,
        )
        self.orchestrator = orchestration.AgentRunOrchestrator(authority=self.authority, kernel=self.kernel, ledger=self.ledger)
        self.termination = termination or orchestration.TerminationCondition(
            max_delegation_depth=2, timeout=timedelta(hours=1), max_attempts=3, max_tasks=50, escalation_target=ESCALATION_TARGET
        )
        self.run = self.orchestrator.start_run(
            self.team_run_id,
            team_id="team-1",
            members=tuple(self.members.values()),
            termination=self.termination,
            at=NOW,
            **caller("team-lead-1"),
        )

    def binding(self, agent_id: str, *, tier: str = "ANALYZE") -> tool_runtime.AgentIdentityBinding:
        return tool_runtime.AgentIdentityBinding(
            agent_principal_id=agent_id,
            agent_run_id=f"urn:ocor:agent-run:{agent_id}",
            workload_identity=f"spiffe://ocor.internal/agent/{agent_id}/run/{agent_id}",
            owner="urn:ocor:human:owner-1",
            autonomy_tier=tier,
            agent_version="1.0.0",
            model_pin=MODEL_PIN,
            instruction_pin=INSTRUCTION_PIN,
            team_id="team-1",
            tenant_id=TENANT,
        )

    def grant(self, *, subject: str, capability: str, resource: str, ttl: timedelta = timedelta(hours=1)) -> Any:
        return self.authority.issue(subject=subject, capabilities=[capability], resources=[resource], issued_at=NOW, ttl=ttl)

    def propose(
        self,
        task_id: str,
        *,
        role: str = "HYPOTHESIS",
        output_type: str | None = None,
        dependencies: tuple[str, ...] = (),
        parent_task_id: str | None = None,
        timeout: timedelta = timedelta(minutes=30),
        by: str = "team-lead-1",
        autonomy_tier: str = "ANALYZE",
        logical_task_id: str | None = None,
        at: datetime = NOW,
    ) -> Any:
        output = output_type or orchestration.ROLE_OUTPUTS[orchestration.AgentRole[role]][0]
        return self.orchestrator.propose_task(
            self.team_run_id,
            task_id,
            logical_task_id=logical_task_id,
            role=orchestration.AgentRole[role],
            output_type=output,
            autonomy_tier=autonomy_tier,
            dependencies=dependencies,
            parent_task_id=parent_task_id,
            timeout=timeout,
            at=at,
            **caller(by),
        )

    def assign(self, task_id: str, agent_id: str, *, by: str = "team-lead-1", at: datetime = NOW) -> Any:
        lease = self.grant(subject=by, capability="agent:assign", resource=agent_id)
        return self.orchestrator.assign(task_id, agent_id, capability="act:analyze", lease=lease, assigned_by=by, at=at, **caller(by))

    def commit(self, task_id: str, agent_id: str, *, at: datetime = NOW) -> Any:
        lease = self.grant(subject=agent_id, capability="agent:commit", resource=agent_id)
        return self.orchestrator.commit(task_id, lease=lease, at=at, **caller(agent_id))

    def accepted(self, task_id: str, agent_id: str, **options: Any) -> Any:
        self.propose(task_id, **options)
        self.assign(task_id, agent_id)
        return self.commit(task_id, agent_id)

    def handoff(self, task_id: str, *, sender: str, to: str, transport: str | None = None, payload: Any = None, at: datetime = NOW) -> Any:
        lease = self.grant(subject=sender, capability="agent:handoff", resource=to)
        return self.orchestrator.handoff(
            task_id,
            sender=sender,
            to_agent_id=to,
            reason="rebalancing",
            payload={"state_summary": "partial portfolio"} if payload is None else payload,
            lease=lease,
            at=at,
            **caller(transport or sender),
        )

    def dissent(self, task_id: str, agent_id: str, *, severity: str = "LOW", category: str = "COUNTER_EVIDENCE", reason: str = "objection") -> Any:
        lease = self.grant(subject=agent_id, capability="agent:dissent", resource=agent_id)
        return self.orchestrator.register_dissent(
            task_id,
            agent_id,
            reason=reason,
            severity=orchestration.DissentSeverity[severity],
            category=orchestration.DissentCategory[category],
            lease=lease,
            at=NOW,
            **caller(agent_id),
        )

    def revoke_delegation(self, agent_id: str) -> None:
        self.controls.revoke(delegation_of(agent_id))

    def accept_stop(self) -> None:
        self.stop.activate(activator=SAFETY_OFFICER, incident_ref=INCIDENT, reason="external emergency stop", at=datetime.now(UTC))

    def audited(self) -> list[dict[str, Any]]:
        """Every record of the signed audit chain written by the coordination kernel for this run."""
        return [dict(record.record) for record in self.audit.records() if record.record.get("detail", {}).get("team_run_id") == self.team_run_id]
