"""OCOR-DEV-0047: Implement C8 tool boundary sandbox budgets and kill
switch.

Proves that every tool call ToolCallRuntime.invoke() makes is
capability-, purpose-, marking-, budget- and stop-bound, with an
immutable receipt on success -- and that none of the three named
negative conditions (escape syntax, over-budget work, revoked
capability) ever lets the real registered tool function run: an
in-memory ``effects`` list, appended to only by the real tool
callable, is asserted to gain exactly one entry across the entire
test, proving zero tool effect on every denial path. Pure, in-memory,
deterministic component (no external service needed, like
OCOR-DEV-0028/0030/0042/0043/0044/0045/0046's own C1/C6/C7/C8 slices).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ocor_runtime.c4_marking import MarkingSchemeDefinition, MarkingSet
from ocor_runtime.c4.marking_resolution import ResolvedMarkingEngine
from ocor_runtime.c6.safety import EmergencyStopController
from ocor_runtime.c6_capabilities import CapabilityAuthority
from ocor_runtime.c8.tool_runtime import ToolCallRuntime, ToolRuntimeError
from ocor_runtime.c8_agent import StrictSandbox, TokenBudget
from ocor_runtime.errors import SandboxViolation, TokenBudgetExceeded
from ocor_runtime.kernel.governed_context import GovernedContext
from c6_safety_fixture import INCIDENT, SAFETY_OFFICER, stop_controller

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
DIGEST_A = "urn:sha256:" + "a" * 64
DIGEST_B = "urn:sha256:" + "b" * 64
DIGEST_C = "urn:sha256:" + "c" * 64


def make_context(*, purpose: str = "incident-response") -> GovernedContext:
    return GovernedContext(
        tenant_id="t1",
        organization_id="o1",
        domain_id="d1",
        compartments=("default",),
        classification_marking_ref=DIGEST_A,
        purpose=purpose,
        effective_principal_id="agent-1",
        actor_chain=("agent-1",),
        ontology_release_digest=DIGEST_B,
        policy_bundle_digest=DIGEST_C,
        correlation_id="urn:ocor:correlation:1",
    )


@pytest.fixture
def effects() -> list[str]:
    return []


@pytest.fixture
def sandbox(effects: list[str]) -> StrictSandbox:
    box = StrictSandbox()

    def restart_service(name: str) -> str:
        effects.append(name)
        return f"restarted {name}"

    box.register_tool("restart_service", restart_service)
    return box


@pytest.fixture
def authority() -> CapabilityAuthority:
    return CapabilityAuthority(issuer="ocor-c8-tool-runtime-authority")


@pytest.fixture
def marking_engine() -> ResolvedMarkingEngine:
    scheme = MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET", "TOP_SECRET"))
    return ResolvedMarkingEngine([scheme])


@pytest.fixture
def stop() -> EmergencyStopController:
    return stop_controller()


@pytest.fixture
def runtime(sandbox: StrictSandbox, authority: CapabilityAuthority, marking_engine: ResolvedMarkingEngine, stop: EmergencyStopController) -> ToolCallRuntime:
    return ToolCallRuntime(sandbox=sandbox, authority=authority, marking_engine=marking_engine, stop=stop)


def grant(authority: CapabilityAuthority, *, tool_name: str = "restart_service"):
    return authority.issue(
        subject="agent-1", capabilities=[f"tool:{tool_name}"], resources=[tool_name], issued_at=NOW, ttl=timedelta(hours=1)
    )


CONTENT_MARKING = MarkingSet({"classification": "SECRET"})
FULL_CLEARANCE = MarkingSet({"classification": "TOP_SECRET"})
INSUFFICIENT_CLEARANCE = MarkingSet({"classification": "UNCLASSIFIED"})


def test_a_fully_bound_call_produces_a_receipt_and_a_real_tool_effect(
    runtime: ToolCallRuntime, authority: CapabilityAuthority, stop: EmergencyStopController, effects: list[str]
) -> None:
    lease = grant(authority)
    budget = TokenBudget(1000)

    receipt = runtime.invoke(
        "restart_service",
        "restart_service(name)",
        bindings={"name": "svc-1"},
        lease=lease,
        context=make_context(),
        content_marking=CONTENT_MARKING,
        clearance=FULL_CLEARANCE,
        budget=budget,
        estimated_tokens=10,
        stop_epoch=stop.epoch,
        at=NOW,
    )

    assert receipt.tool_name == "restart_service"
    assert receipt.lease_id == lease.lease_id
    assert receipt.purpose == "incident-response"
    assert receipt.tokens_spent == 10
    assert receipt.result == "restarted svc-1"
    assert effects == ["svc-1"]


# --- revoked capability produces no tool effect ------------------------------


def test_a_revoked_capability_produces_no_tool_effect(
    runtime: ToolCallRuntime, authority: CapabilityAuthority, stop: EmergencyStopController, effects: list[str]
) -> None:
    lease = grant(authority)
    authority.revoke(lease.lease_id, at=NOW)
    budget = TokenBudget(1000)

    with pytest.raises(ToolRuntimeError) as excinfo:
        runtime.invoke(
            "restart_service",
            "restart_service(name)",
            bindings={"name": "svc-2"},
            lease=lease,
            context=make_context(),
            content_marking=CONTENT_MARKING,
            clearance=FULL_CLEARANCE,
            budget=budget,
            estimated_tokens=10,
            stop_epoch=stop.epoch,
            at=NOW,
        )

    assert excinfo.value.reason_code == "CAPABILITY_REVOKED"
    assert effects == []
    assert budget.used == 0


def test_a_fabricated_lease_never_issued_produces_no_tool_effect(
    runtime: ToolCallRuntime, stop: EmergencyStopController, effects: list[str]
) -> None:
    budget = TokenBudget(1000)
    with pytest.raises(ToolRuntimeError) as excinfo:
        runtime.invoke(
            "restart_service",
            "restart_service(name)",
            bindings={"name": "svc-x"},
            lease="agent-made-this-up",
            context=make_context(),
            content_marking=CONTENT_MARKING,
            clearance=FULL_CLEARANCE,
            budget=budget,
            estimated_tokens=10,
            stop_epoch=stop.epoch,
            at=NOW,
        )
    assert excinfo.value.reason_code == "CAPABILITY_DENIED"
    assert effects == []


# --- escape syntax produces no tool effect -----------------------------------


def test_an_escape_syntax_attempt_produces_no_tool_effect(
    runtime: ToolCallRuntime, authority: CapabilityAuthority, stop: EmergencyStopController, effects: list[str]
) -> None:
    lease = grant(authority)
    budget = TokenBudget(1000)

    with pytest.raises(SandboxViolation):
        runtime.invoke(
            "restart_service",
            "__import__('os').system('echo pwned')",
            bindings={},
            lease=lease,
            context=make_context(),
            content_marking=CONTENT_MARKING,
            clearance=FULL_CLEARANCE,
            budget=budget,
            estimated_tokens=10,
            stop_epoch=stop.epoch,
            at=NOW,
        )

    assert effects == []
    # the budget charge for the attempt itself is real -- the call was
    # authorized, marked, stop-checked and budgeted before the sandbox
    # ever rejected the expression's syntax.
    assert budget.used == 10


def test_a_registered_forbidden_looking_name_never_reaches_the_tool_either(
    runtime: ToolCallRuntime, authority: CapabilityAuthority, stop: EmergencyStopController, effects: list[str]
) -> None:
    lease = grant(authority)
    budget = TokenBudget(1000)

    with pytest.raises(SandboxViolation):
        runtime.invoke(
            "restart_service",
            "restart_service.__class__",
            bindings={},
            lease=lease,
            context=make_context(),
            content_marking=CONTENT_MARKING,
            clearance=FULL_CLEARANCE,
            budget=budget,
            estimated_tokens=10,
            stop_epoch=stop.epoch,
            at=NOW,
        )
    assert effects == []


# --- over-budget work produces no tool effect --------------------------------


def test_over_budget_work_produces_no_tool_effect(
    runtime: ToolCallRuntime, authority: CapabilityAuthority, stop: EmergencyStopController, effects: list[str]
) -> None:
    lease = grant(authority)
    tight_budget = TokenBudget(1)

    with pytest.raises(ToolRuntimeError) as excinfo:
        runtime.invoke(
            "restart_service",
            "restart_service(name)",
            bindings={"name": "svc-3"},
            lease=lease,
            context=make_context(),
            content_marking=CONTENT_MARKING,
            clearance=FULL_CLEARANCE,
            budget=tight_budget,
            estimated_tokens=100,
            stop_epoch=stop.epoch,
            at=NOW,
        )

    assert excinfo.value.reason_code == "BUDGET_EXCEEDED"
    assert effects == []
    assert tight_budget.used == 0


# --- marking-bound ------------------------------------------------------------


def test_insufficient_clearance_produces_no_tool_effect(
    runtime: ToolCallRuntime, authority: CapabilityAuthority, stop: EmergencyStopController, effects: list[str]
) -> None:
    lease = grant(authority)
    budget = TokenBudget(1000)

    with pytest.raises(ToolRuntimeError) as excinfo:
        runtime.invoke(
            "restart_service",
            "restart_service(name)",
            bindings={"name": "svc-4"},
            lease=lease,
            context=make_context(),
            content_marking=CONTENT_MARKING,
            clearance=INSUFFICIENT_CLEARANCE,
            budget=budget,
            estimated_tokens=10,
            stop_epoch=stop.epoch,
            at=NOW,
        )

    assert excinfo.value.reason_code == "POLICY_DENIED"
    assert excinfo.value.marking_outcome == "MARKING_DENIED"
    assert effects == []
    assert budget.used == 0


# --- purpose-bound --------------------------------------------------------------


def test_a_missing_purpose_is_refused_before_construction() -> None:
    """GovernedContext itself already fails closed on an empty
    purpose -- proving purpose-binding starts at the sealed kernel
    boundary, not merely inside this task's own code."""
    from ocor_runtime.kernel.governed_context import GovernedContextError

    with pytest.raises(GovernedContextError):
        make_context(purpose="")


# --- stop-bound -----------------------------------------------------------------


def test_an_active_emergency_stop_produces_no_tool_effect(
    runtime: ToolCallRuntime, authority: CapabilityAuthority, stop: EmergencyStopController, effects: list[str]
) -> None:
    lease = grant(authority)
    budget = TokenBudget(1000)
    stop.activate(activator=SAFETY_OFFICER, incident_ref=INCIDENT, reason="incident-during-tool-call", at=NOW)

    with pytest.raises(ToolRuntimeError) as excinfo:
        runtime.invoke(
            "restart_service",
            "restart_service(name)",
            bindings={"name": "svc-5"},
            lease=lease,
            context=make_context(),
            content_marking=CONTENT_MARKING,
            clearance=FULL_CLEARANCE,
            budget=budget,
            estimated_tokens=10,
            stop_epoch=stop.epoch,
            at=NOW,
        )

    assert excinfo.value.reason_code == "EMERGENCY_STOP_ACTIVE"
    assert effects == []
    assert budget.used == 0


def test_a_call_fenced_to_a_stale_epoch_produces_no_tool_effect(
    runtime: ToolCallRuntime, authority: CapabilityAuthority, stop: EmergencyStopController, effects: list[str]
) -> None:
    lease = grant(authority)
    budget = TokenBudget(1000)
    stale_epoch = stop.epoch
    stop.activate(activator=SAFETY_OFFICER, incident_ref=INCIDENT, reason="incident", at=NOW)
    stop.finish_draining(at=NOW)

    with pytest.raises(ToolRuntimeError) as excinfo:
        runtime.invoke(
            "restart_service",
            "restart_service(name)",
            bindings={"name": "svc-6"},
            lease=lease,
            context=make_context(),
            content_marking=CONTENT_MARKING,
            clearance=FULL_CLEARANCE,
            budget=budget,
            estimated_tokens=10,
            stop_epoch=stale_epoch,
            at=NOW,
        )

    assert excinfo.value.reason_code == "EMERGENCY_STOP_ACTIVE"
    assert effects == []


def test_all_denial_paths_combined_never_produce_more_than_the_one_legitimate_effect(
    runtime: ToolCallRuntime, authority: CapabilityAuthority, stop: EmergencyStopController, effects: list[str]
) -> None:
    """Integration-level proof: run one legitimate call and every
    denial scenario in sequence against the shared effects list,
    proving exactly one real effect ever lands no matter how many
    ways a call is attempted and refused."""
    lease = grant(authority)
    budget = TokenBudget(1000)

    runtime.invoke(
        "restart_service",
        "restart_service(name)",
        bindings={"name": "the-only-real-one"},
        lease=lease,
        context=make_context(),
        content_marking=CONTENT_MARKING,
        clearance=FULL_CLEARANCE,
        budget=budget,
        estimated_tokens=10,
        stop_epoch=stop.epoch,
        at=NOW,
    )

    revoked_lease = grant(authority)
    authority.revoke(revoked_lease.lease_id, at=NOW)
    for bad_lease, bad_clearance, bad_expression, bad_budget in [
        (revoked_lease, FULL_CLEARANCE, "restart_service(name)", budget),
        (grant(authority), INSUFFICIENT_CLEARANCE, "restart_service(name)", budget),
        (grant(authority), FULL_CLEARANCE, "os.system('rm -rf /')", budget),
        (grant(authority), FULL_CLEARANCE, "restart_service(name)", TokenBudget(0)),
    ]:
        with pytest.raises((ToolRuntimeError, SandboxViolation, TokenBudgetExceeded)):
            runtime.invoke(
                "restart_service",
                bad_expression,
                bindings={"name": "should-never-run"},
                lease=bad_lease,
                context=make_context(),
                content_marking=CONTENT_MARKING,
                clearance=bad_clearance,
                budget=bad_budget,
                estimated_tokens=10,
                stop_epoch=stop.epoch,
                at=NOW,
            )

    assert effects == ["the-only-real-one"]
