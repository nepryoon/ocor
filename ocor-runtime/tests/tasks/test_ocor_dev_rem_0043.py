"""OCOR-DEV-REM-0043: C8 dispatch-time live revocation.

ADD v1.3 Part II section 2.12: "Tool invocation always re-evaluates live
capability, delegation, policy, memory instruction eligibility and stop
epoch"; LLD v1.1 section 7.2, FGM-17: a race between the kill switch or the
revocation of a delegation and a use leaves "nessuna retrieval o tool
influence successiva". OCOR-DEV-0062 (FGM-17 tool path) reproduced with the
real collaborators that ``ToolCallRuntime`` re-authorizes every dispatch at
the caller's invocation instant ``at``: a lease revoked while the expression
runs is recorded with a later ``revoked_at`` and therefore still dispatches
the next tool. The stop path is unaffected (it is epoch-based), and the
sealed REM-0027 case only passes because it revokes at the same fixed
instant it invokes at.

Every case uses the real ``CapabilityAuthority``, ``MarkingEngine``,
``EmergencyStopController``, ``StrictSandbox`` and ``TokenBudget`` exactly as
OCOR-DEV-0047 and OCOR-DEV-REM-0027 do -- no mock of the authority or of
the stop controller. The invocation instant is the real current instant and
every revocation is recorded at the current instant when it happens, so the
revocation is always strictly later than the presented ``at``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ocor_runtime.c4_marking import MarkingEngine, MarkingSchemeDefinition, MarkingSet
from ocor_runtime.c6.safety import EmergencyStopController
from ocor_runtime.c6_capabilities import CapabilityAuthority, CapabilityLease
from ocor_runtime.c8.tool_runtime import ToolCallRuntime, ToolRuntimeError
from ocor_runtime.c8_agent import StrictSandbox, TokenBudget
from ocor_runtime.kernel.governed_context import GovernedContext

DIGEST = "urn:sha256:"
CONTENT_MARKING = MarkingSet({"classification": "SECRET"})
FULL_CLEARANCE = MarkingSet({"classification": "TOP_SECRET"})


def make_context() -> GovernedContext:
    return GovernedContext(
        tenant_id="t1",
        organization_id="o1",
        domain_id="d1",
        compartments=("default",),
        classification_marking_ref=DIGEST + "a" * 64,
        purpose="incident-response",
        effective_principal_id="agent-1",
        actor_chain=("agent-1",),
        ontology_release_digest=DIGEST + "b" * 64,
        policy_bundle_digest=DIGEST + "c" * 64,
        correlation_id="urn:ocor:correlation:rem-0043",
    )


def later_than(instant: datetime) -> datetime:
    """The current instant, strictly after ``instant`` (a revocation that
    happens while the call runs)."""
    now = datetime.now(UTC)
    return now if now > instant else instant + timedelta(microseconds=1)


class Harness:
    """The real collaborators of OCOR-DEV-0047 plus an effects journal that
    only the registered tool callables append to."""

    def __init__(self, authority: type[CapabilityAuthority] = CapabilityAuthority) -> None:
        self.effects: list[str] = []
        self.sandbox = StrictSandbox()
        self.authority = authority(issuer="rem-0043-authority")
        self.marking = MarkingEngine([MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET", "TOP_SECRET"))])
        self.stop = EmergencyStopController()
        self.runtime = ToolCallRuntime(sandbox=self.sandbox, authority=self.authority, marking_engine=self.marking, stop=self.stop)
        self.invoked_at = datetime.now(UTC)

    def tool(self, name: str, body: Callable[[], None] | None = None) -> None:
        def call(value: str) -> str:
            if body is not None:
                body()
            self.effects.append(name)
            return f"{name} {value}"

        self.sandbox.register_tool(name, call)

    def lease(self, *tools: str, parent: CapabilityLease | None = None, subject: str = "agent-1") -> CapabilityLease:
        return self.authority.issue(
            subject=subject,
            capabilities=[f"tool:{tool}" for tool in tools],
            resources=list(tools),
            issued_at=self.invoked_at - timedelta(minutes=1),
            ttl=timedelta(hours=1),
            parent=parent,
        )

    def revoke_now(self, lease: CapabilityLease) -> None:
        self.authority.revoke(lease.lease_id, at=later_than(self.invoked_at))

    def accept_stop(self) -> None:
        """The external control plane accepts the stop on its own thread."""
        worker = threading.Thread(target=lambda: self.stop.activate(reason="external emergency stop", at=datetime.now(UTC)))
        worker.start()
        worker.join()

    def invoke(self, expression: str, lease: CapabilityLease, *, tool_name: str = "note", budget: TokenBudget | None = None) -> Any:
        return self.runtime.invoke(
            tool_name,
            expression,
            bindings={"name": "svc"},
            lease=lease,
            context=make_context(),
            content_marking=CONTENT_MARKING,
            clearance=FULL_CLEARANCE,
            budget=budget or TokenBudget(1000),
            estimated_tokens=10,
            stop_epoch=self.stop.epoch,
            at=self.invoked_at,
        )

    def refused(self, expression: str, lease: CapabilityLease, reason: str, **kwargs: Any) -> ToolRuntimeError:
        with pytest.raises(ToolRuntimeError) as refused:
            self.invoke(expression, lease, **kwargs)
        assert refused.value.reason_code == reason, str(refused.value)
        return refused.value


# --- positive controls ----------------------------------------------------------------


def test_without_a_revocation_every_tool_of_the_expression_is_dispatched() -> None:
    harness = Harness()
    harness.tool("note")
    harness.tool("restart_service")
    lease = harness.lease("note", "restart_service")

    receipt = harness.invoke("[note(name), restart_service(name)]", lease)

    assert harness.effects == ["note", "restart_service"]
    assert receipt.result == ["note svc", "restart_service svc"]
    assert receipt.lease_id == lease.lease_id
    assert harness.runtime.reconciler.records == ()


def test_a_revocation_after_the_last_tool_changes_nothing_already_dispatched() -> None:
    harness = Harness()
    holder: dict[str, CapabilityLease] = {}
    harness.tool("note")
    harness.tool("restart_service", lambda: harness.revoke_now(holder["lease"]))
    holder["lease"] = harness.lease("note", "restart_service")

    receipt = harness.invoke("[note(name), restart_service(name)]", holder["lease"])

    assert harness.effects == ["note", "restart_service"]
    assert receipt.result == ["note svc", "restart_service svc"]
    # the revocation is live from now on: the next call is refused before any effect
    budget = TokenBudget(1000)
    harness.refused("note(name)", holder["lease"], "CAPABILITY_DENIED", budget=budget)
    assert harness.effects == ["note", "restart_service"] and budget.used == 0


# --- the defect: revocation while the expression runs -------------------------------


def test_a_lease_revoked_at_the_current_instant_during_the_expression_refuses_the_next_tool() -> None:
    harness = Harness()
    holder: dict[str, CapabilityLease] = {}
    harness.tool("note", lambda: harness.revoke_now(holder["lease"]))
    harness.tool("restart_service")
    holder["lease"] = harness.lease("note", "restart_service")

    refused = harness.refused("[note(name), restart_service(name)]", holder["lease"], "CAPABILITY_DENIED")

    revoked = harness.authority.get(holder["lease"].lease_id)
    assert revoked is not None and revoked.revoked_at is not None and revoked.revoked_at > harness.invoked_at
    assert harness.effects == ["note"]
    # refused before the dispatch: nothing ran, so the outcome is not indeterminate
    assert refused.execution_unknown is False and refused.reconciliation is None
    assert harness.runtime.reconciler.records == () and harness.runtime.unknown_outcomes == ()


def test_a_delegation_revoked_during_the_expression_refuses_the_next_tool_of_the_delegate() -> None:
    harness = Harness()
    parent = harness.lease("note", "restart_service", subject="agent-0")
    child = harness.lease("note", "restart_service", parent=parent)
    harness.tool("note", lambda: harness.revoke_now(parent))
    harness.tool("restart_service")

    refused = harness.refused("[note(name), restart_service(name)]", child, "CAPABILITY_DENIED")

    assert harness.effects == ["note"]
    assert refused.execution_unknown is False and harness.runtime.reconciler.records == ()
    # the delegate itself was never revoked: only its delegation is dead
    delegate = harness.authority.get(child.lease_id)
    assert delegate is not None and delegate.revoked_at is None


def test_a_lease_revoked_after_the_presented_instant_is_refused_before_anything_is_charged() -> None:
    harness = Harness()
    harness.tool("note")
    lease = harness.lease("note")
    harness.revoke_now(lease)  # revoked now, later than the instant the caller presents
    budget = TokenBudget(1000)

    harness.refused("note(name)", lease, "CAPABILITY_DENIED", budget=budget)

    assert harness.effects == [] and budget.used == 0
    assert harness.authority.usage(lease.lease_id) == 0


def test_a_revoked_lease_is_refused_on_the_effect_channel_whatever_instant_is_presented() -> None:
    harness = Harness()
    lease = harness.lease("note")
    assert harness.runtime.authorize_effect(lease, "note", subject="agent-1", at=harness.invoked_at).lease_id == lease.lease_id
    harness.revoke_now(lease)

    with pytest.raises(ToolRuntimeError) as refused:
        harness.runtime.authorize_effect(lease, "note", subject="agent-1", at=harness.invoked_at)

    assert refused.value.reason_code == "CAPABILITY_DENIED"


def test_a_delegation_revoked_after_the_presented_instant_is_refused_on_the_effect_channel() -> None:
    harness = Harness()
    parent = harness.lease("note", subject="agent-0")
    child = harness.lease("note", parent=parent)
    harness.revoke_now(parent)

    with pytest.raises(ToolRuntimeError) as refused:
        harness.runtime.authorize_effect(child, "note", subject="agent-1", at=harness.invoked_at)

    assert refused.value.reason_code == "CAPABILITY_DENIED"


# --- precedence: the stop-epoch refusal comes first ---------------------------------


def test_a_stop_and_a_revocation_during_the_expression_refuse_the_next_tool_as_stop_bound() -> None:
    harness = Harness()
    holder: dict[str, CapabilityLease] = {}

    def revoke_and_stop() -> None:
        harness.revoke_now(holder["lease"])
        harness.accept_stop()

    harness.tool("note", revoke_and_stop)
    harness.tool("restart_service")
    holder["lease"] = harness.lease("note", "restart_service")

    harness.refused("[note(name), restart_service(name)]", holder["lease"], "STOP_BOUND_DENIED")

    assert harness.effects == ["note"]


def test_a_stop_accepted_after_the_gates_stays_stop_bound_although_it_revokes_the_lease() -> None:
    harness = Harness()
    harness.tool("note")
    lease = harness.lease("note")

    class StopWhileCharging(TokenBudget):
        def consume(self, tokens: int, *, category: str) -> Any:
            harness.accept_stop()  # after every gate, before the sandbox: the stop revokes the lease
            return super().consume(tokens, category=category)

    harness.refused("note(name)", lease, "STOP_BOUND_DENIED", budget=StopWhileCharging(1000))

    revoked = harness.authority.get(lease.lease_id)
    assert revoked is not None and revoked.revoked_at is not None
    assert harness.effects == []


def test_the_effect_channel_refuses_a_stopped_and_revoked_lease_as_stop_bound() -> None:
    harness = Harness()
    lease = harness.lease("note")
    harness.revoke_now(lease)
    harness.accept_stop()

    with pytest.raises(ToolRuntimeError) as refused:
        harness.runtime.authorize_effect(lease, "note", subject="agent-1", at=harness.invoked_at)

    assert refused.value.reason_code == "STOP_BOUND_DENIED"


def test_a_stop_accepted_between_the_authorization_and_the_live_read_stays_stop_bound() -> None:
    """The stop is accepted at the one instant the authority's own epoch check
    cannot see: after ``authorize`` has passed and before the live lease
    record is read. Accepting it revokes the lease, and the refusal must still
    be the stop's."""
    armed: dict[str, Harness] = {}

    class StopBeforeTheLiveRead(CapabilityAuthority):
        def get(self, lease_id: str) -> CapabilityLease | None:
            harness = armed.pop("harness", None)
            if harness is not None:
                harness.accept_stop()
            return super().get(lease_id)

    harness = Harness(StopBeforeTheLiveRead)
    harness.tool("note")
    lease = harness.lease("note")
    armed["harness"] = harness
    budget = TokenBudget(1000)

    harness.refused("note(name)", lease, "STOP_BOUND_DENIED", budget=budget)

    revoked = harness.authority.get(lease.lease_id)
    assert revoked is not None and revoked.revoked_at is not None and "harness" not in armed
    assert harness.effects == [] and budget.used == 0


def test_a_revocation_racing_the_dispatch_from_another_thread_never_reaches_the_second_tool() -> None:
    harness = Harness()
    holder: dict[str, CapabilityLease] = {}
    revoked = threading.Event()

    def revoke_from_control_plane() -> None:
        worker = threading.Thread(target=lambda: (harness.revoke_now(holder["lease"]), revoked.set()))
        worker.start()
        worker.join()

    harness.tool("note", revoke_from_control_plane)
    harness.tool("restart_service")
    holder["lease"] = harness.lease("note", "restart_service")

    started = time.monotonic()
    harness.refused("[note(name), restart_service(name)]", holder["lease"], "CAPABILITY_DENIED")

    assert revoked.is_set() and harness.effects == ["note"]
    assert time.monotonic() - started < 5.0
