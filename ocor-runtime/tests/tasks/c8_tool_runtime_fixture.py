"""The real collaborators of the C8 governed tool runtime (OCOR-DEV-REM-0058, NCP-U10), shared by
the tests of OCOR-DEV-0047, OCOR-DEV-REM-0027 and OCOR-DEV-REM-0054 that exercise it.

Each tool is an allow-listed ``mcp-tool-contract:1.2`` of a ``ToolRegistry`` bound to the test's
Governed Context, with an adapter taking one ``name``; the agent run holds a C8 ``ToolGrant``; the
Authority and the verified Delegation are live governance controls; the policy decision point
permits (the tests that deny live in the unit module); the memory instruction eligibility of the
run is granted; every ``EXECUTION_UNKNOWN`` outcome goes to the C6 reconciler appending to the
signed audit chain on the live PostgreSQL (``OCOR_LIVE_POSTGRES_DSN``, Register FR-163).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from ocor_runtime import audit
from ocor_runtime.c4.marking_resolution import ResolvedMarkingEngine
from ocor_runtime.c6.safety import EmergencyStopController, OutcomeReconciler, StopEpochReader
from ocor_runtime.c8 import tool_runtime
from ocor_runtime.c8.tool_contract import SchemaCatalog, ToolBinding, ToolContract, ToolRegistry, wire_digest
from ocor_runtime.kernel.governance import Authority, RiskClass
from ocor_runtime.kernel.governed_context import GovernedContext
from ocor_runtime.security.ports import AuthenticatedPrincipal, ControlName, ControlStatus, PolicyDecision, PolicyEffect

from c6_action_fixture import seeded_key

DELEGATION = "urn:sha256:" + "e" * 64
SCOPE = "urn:ocor:scope:services"
INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["name"],
    "properties": {"name": {"type": "string", "pattern": "^[a-z0-9-]{1,64}$"}},
}
OUTPUT_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "string", "maxLength": 256}
INPUT_PIN = {"schema_id": "urn:ocor:schema:tool:fixture:input", "version": "1.0.0", "digest": wire_digest(INPUT_SCHEMA)}
OUTPUT_PIN = {"schema_id": "urn:ocor:schema:tool:fixture:output", "version": "1.0.0", "digest": wire_digest(OUTPUT_SCHEMA)}


class PermitPolicy:
    """``security.ports.PolicyDecisionPort`` that permits every well-formed request."""

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def evaluate(self, request: Any) -> PolicyDecision:
        self.requests.append(request)
        return PolicyDecision.from_request(
            request,
            effect=PolicyEffect.PERMIT,
            decision_id=f"urn:ocor:policy-decision:fixture:{len(self.requests)}",
            valid_until=request.at + timedelta(hours=1),
            status=ControlStatus.available(
                ControlName.POLICY, observed_at=request.at, source_digest=request.governed_context.policy_bundle_digest
            ),
        )


def audit_log(schema: str = "ocor_audit_c8_tool_runtime") -> audit.PostgresAuditLog:
    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        raise RuntimeError("OCOR_LIVE_POSTGRES_DSN is mandatory: the reconciliation audit is on PostgreSQL")
    log = audit.PostgresAuditLog(
        dsn, schema=schema, signer=audit.AuditSigner(key=seeded_key("c8-tool-runtime-audit"), keyid="c8-tool-runtime-audit")
    )
    log.initialize()
    return log


def audited_reconciler() -> OutcomeReconciler:
    """The C6 reconciler of the signed audit chain on PostgreSQL."""
    return OutcomeReconciler(audit=audit_log())


def contract_document(name: str, context_ref: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "contract_id": f"urn:ocor:tool-contract:{name.replace('_', '-')}",
        "version": "1.0.0",
        "governed_context_ref": context_ref,
        "capability_id": f"urn:ocor:capability:tool:{name}",
        "input_schema": dict(INPUT_PIN),
        "output_schema": dict(OUTPUT_PIN),
        "effect_class": "ANALYZE",
        "risk_class": "LOW",
        "allowed_autonomy_tiers": ["ANALYZE", "SIMULATE"],
        "preconditions": [],
        "policy_refs": ["urn:ocor:policy:c8:tool-call"],
        "approval": {"mode": "NONE", "self_approval_allowed": False, "timeout_action": "DENY"},
        "idempotency": {"scope": "REQUEST", "key_required": True, "duplicate_semantics": "REPLAY_RECEIPT"},
        "timeout_ms": 10000,
        "retry": {"retry_safe": False, "max_attempts": 1},
        "compensation": {"mode": "NOT_APPLICABLE", "irreversibility_class": "REVERSIBLE"},
        "provenance_requirements": {
            "record_input_digest": True,
            "record_output_digest": True,
            "record_policy_decision": True,
            "record_actor_chain": True,
            "record_tool_binding": True,
        },
        "evidence_requirements": {"input_evidence": "OPTIONAL", "output_evidence": "OPTIONAL", "minimum_count": 0},
        "error_codes": ["POLICY_DENIED", "CAPABILITY_DENIED", "SCHEMA_VIOLATION", "EXECUTION_UNKNOWN"],
    }
    body["contract_digest"] = wire_digest(body)
    return body


class ToolRuntimeWorld:
    """A ``ToolCallRuntime`` on its real collaborators for one Governed Context."""

    def __init__(
        self,
        *,
        context: GovernedContext,
        marking_engine: ResolvedMarkingEngine,
        stop: EmergencyStopController | StopEpochReader,
        now: datetime,
        deadline: timedelta | None = None,
        reconciler: OutcomeReconciler | None = None,
    ) -> None:
        self.context = context
        self.now = now
        self.reader = stop.reader if isinstance(stop, EmergencyStopController) else stop
        self.schemas = SchemaCatalog()
        self.schemas.add(INPUT_PIN["schema_id"], INPUT_PIN["version"], INPUT_SCHEMA)
        self.schemas.add(OUTPUT_PIN["schema_id"], OUTPUT_PIN["version"], OUTPUT_SCHEMA)
        self.registry = ToolRegistry(governed_context_ref=context.digest(), schemas=self.schemas)
        self.grants = tool_runtime.ToolGrantLedger(stop=self.reader)
        self.controls = tool_runtime.InMemoryGovernanceControls()
        self.controls.bind_delegation(context.effective_principal_id, DELEGATION)
        self.authority_id = f"urn:ocor:authority:{context.effective_principal_id}"
        self._authorize()
        self.policy = PermitPolicy()
        self.agent = tool_runtime.AgentIdentityBinding(
            agent_principal_id=context.effective_principal_id,
            agent_run_id="urn:ocor:agent-run:fixture",
            workload_identity=f"spiffe://ocor.internal/agent/{context.effective_principal_id}",
            owner="urn:ocor:human:owner-1",
            autonomy_tier="ANALYZE",
            agent_version="1.0.0",
            team_id="team-1",
            tenant_id=context.tenant_id,
        )
        self.eligibility = tool_runtime.InMemoryInstructionEligibility()
        self.eligibility.allow(self.agent.agent_run_id)
        self.principal = AuthenticatedPrincipal(
            principal_id=context.effective_principal_id,
            session_id="urn:ocor:session:fixture",
            actor_chain=(context.effective_principal_id,),
            assurance_level="spiffe-svid",
            authenticated_at=now - timedelta(days=1),
            expires_at=now + timedelta(days=30),
            status=ControlStatus.available(ControlName.IDENTITY, observed_at=now, source_digest="urn:sha256:" + "9" * 64),
        )
        self.reconciler = audited_reconciler() if reconciler is None else reconciler
        options: dict[str, Any] = {} if deadline is None else {"tool_call_deadline": deadline}
        self.runtime = tool_runtime.ToolCallRuntime(
            registry=self.registry,
            grants=self.grants,
            controls=self.controls,
            policy=self.policy,
            eligibility=self.eligibility,
            marking_engine=marking_engine,
            stop=self.reader,
            reconciler=self.reconciler,
            **options,
        )

    def _authorize(self) -> None:
        context = self.context
        self.controls.add_authority(
            Authority(
                authority_id=self.authority_id,
                effective_principal_id=context.effective_principal_id,
                capability_ids=("urn:ocor:capability:tool:none",)
                + tuple(f"urn:ocor:capability:tool:{name}" for name in self.registry.tool_names),
                resource_scopes=(SCOPE,),
                tenant_id=context.tenant_id,
                domains=(context.domain_id,),
                compartments=tuple(context.compartments),
                permitted_purposes=(context.purpose,),
                risk_ceiling=RiskClass.R1_ANALYZE,
                not_before=self.now - timedelta(days=1),
                expires_at=self.now + timedelta(days=30),
                delegation_ref=DELEGATION,
                policy_bundle_digest=context.policy_bundle_digest,
                signature_ref=f"urn:ocor:signature:{context.effective_principal_id}",
            ),
            signature_verified=True,
        )

    def tool(self, name: str, adapter: Callable[[str], Any]) -> None:
        """Allow-list ``adapter`` (one parameter, ``name``) under ``name`` and extend the Authority."""
        contract = ToolContract.from_document(contract_document(name, self.context.digest()), schemas=self.schemas)
        self.registry.register(
            contract,
            ToolBinding(
                tool_name=name,
                binding_id=f"urn:ocor:tool-binding:{name.replace('_', '-')}:fixture",
                contract_id=contract.contract_id,
                contract_version=contract.version,
                contract_digest=contract.contract_digest,
                adapter=adapter,
                egress_destinations=(),
            ),
        )
        self._authorize()

    def grant(self, *tools: str, issued_at: datetime | None = None, ttl: timedelta = timedelta(hours=1), **options: Any) -> Any:
        return self.grants.issue(
            agent=self.agent,
            tools=tools,
            scope=SCOPE,
            delegation_ref=DELEGATION,
            authority_id=self.authority_id,
            issued_at=self.now if issued_at is None else issued_at,
            ttl=ttl,
            **options,
        )

    def budget(self, tokens: int, *, budget_class: type[Any] | None = None) -> Any:
        """A budget of ``tokens`` tokens for the agent run, on its own ledger, generous in every
        other dimension (``budget_class``: an ``AgentBudget`` subclass)."""
        ledger = tool_runtime.AgentBudgetLedger()
        quota = tool_runtime.BudgetQuota(
            tool_calls=1000, steps=1000, tokens=tokens, cost=1000, wall_time_ms=3_600_000, compute_ms=3_600_000, risk_exposure=1000
        )
        for level, key in (
            ("agent", self.agent.agent_principal_id),
            ("run", self.agent.agent_run_id),
            ("team", self.agent.team_id),
            ("tenant", self.agent.tenant_id),
        ):
            ledger.set_quota(level, key, quota)
        return ledger.budget(self.agent) if budget_class is None else budget_class(ledger, self.agent)

    def call_bindings(self) -> dict[str, Any]:
        """The agent bindings every ``invoke`` presents."""
        return {"agent": self.agent, "principal": self.principal}
