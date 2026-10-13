"""OCOR-DEV-REM-0027: C8 preemptive kill switch at every tool dispatch.

LLD v1.1 section 4.3: "L'accettazione dello stop incrementa atomicamente
``stop_epoch``, revoca lease e impedisce nuovi DeliveryAttempt [...] Reset
richiede dual control [...] nuovo epoch e non riabilita lease precedenti";
section 6: "C8: [...] cancellation cooperativa e kill switch preemptive".
ADD v1.3 section 5.5: the stop "nega nuove tool call mutative" and "revoca
Delegation e capability lease nel boundary locale"; "Ogni mutative call
presenta una capability lease con ``stop_epoch`` corrente [...] target
``<=10 s``". The INFO-C audit (2026-10-12) reproduced with the real
in-process collaborators:

- C8-1: a stop accepted after ``guard_dispatch`` and before the sandbox does
  not prevent the tool effect;
- C8-2: the second tool of one expression produces its effect 10.5 s after
  the stop was accepted (no re-check, no bound on a slow first tool);
- C8-3: a lease issued at epoch 0 is accepted after stop and dual-control
  reset at epoch 2 (the lease carries no epoch, the caller chooses it);
- class check: the lease authorizes ``tool:<tool_name>`` but the expression
  can call any registered tool.

Every case uses the real ``CapabilityAuthority``, ``MarkingEngine``,
``EmergencyStopController``, ``StrictSandbox`` and ``TokenBudget`` exactly as
OCOR-DEV-0047 does -- no mock of the stop controller or of the capability
authority. The stop is always accepted by a separate thread, as an external
Emergency Control Plane would. The moment of the stop is fixed by the tools
themselves (or by the budget charge that runs between the gates and the
sandbox), never by timing luck; every effect is recorded with a monotonic
timestamp by the real registered tool callable.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ocor_runtime.c2_identity import IdentityRecord, IdentityRegistry
from ocor_runtime.c4_marking import MarkingEngine, MarkingSchemeDefinition, MarkingSet
from ocor_runtime.c6.safety import EmergencyStopController
from ocor_runtime.c6_capabilities import CapabilityAuthority, CapabilityLease
from ocor_runtime.c8 import tool_runtime as tool_runtime_module
from ocor_runtime.c8.tool_runtime import ToolCallRuntime, ToolRuntimeError
from ocor_runtime.c8_agent import AgentKernel, StrictSandbox, TokenBudget
from ocor_runtime.errors import AuthorizationError
from ocor_runtime.kernel.governed_context import GovernedContext

NOW = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)
DIGEST = "urn:sha256:"
SLOW_SECONDS = 11.0
STOP_AFTER_SECONDS = 0.5
CONTAINMENT_TARGET_SECONDS = 10.0
CONTENT_MARKING = MarkingSet({"classification": "SECRET"})
FULL_CLEARANCE = MarkingSet({"classification": "TOP_SECRET"})
HUMANS = ("urn:ocor:human:a", "urn:ocor:human:b")


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
        correlation_id="urn:ocor:correlation:rem-0027",
    )


def checkpoint() -> None:
    """Cooperative cancellation point offered by the tool boundary, when the
    code under test offers one (the unremediated module has none)."""
    hook = getattr(tool_runtime_module, "cancellation_checkpoint", None)
    if hook is not None:
        hook()


class Harness:
    """The real collaborators of OCOR-DEV-0047 plus an effects journal that
    only the registered tool callables append to."""

    def __init__(self, *, deadline: timedelta | None = None) -> None:
        self.effects: list[tuple[str, str, float]] = []
        self.settled: dict[str, threading.Event] = {}
        self.swallowed: list[BaseException] = []
        self.cooperative_exits: list[str] = []
        self.stop_accepted_at: float | None = None
        self.finished = threading.Event()
        self.sandbox = StrictSandbox()
        self.authority = CapabilityAuthority(issuer="rem-0027-authority")
        self.marking = MarkingEngine([MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET", "TOP_SECRET"))])
        self.stop = EmergencyStopController()
        self.identities = IdentityRegistry()
        for human in HUMANS:
            self.identities.register(IdentityRecord(canonical_id=human))
        options: dict[str, Any] = {} if deadline is None else {"tool_call_deadline": deadline}
        self.runtime = ToolCallRuntime(
            sandbox=self.sandbox, authority=self.authority, marking_engine=self.marking, stop=self.stop, **options
        )

    def tool(self, name: str, body: Callable[[str], None] | None = None, *, mutative: bool = True) -> None:
        settled = self.settled.setdefault(name, threading.Event())

        def call(value: str) -> str:
            try:
                if body is not None:
                    body(value)
                if mutative:
                    self.effects.append((name, value, time.monotonic()))
                return f"{name} {value}"
            finally:
                settled.set()

        self.sandbox.register_tool(name, call)

    def wait_settled(self, name: str) -> None:
        """Wait until the tool callable has really returned or raised on
        its worker, so that a late effect, if any, is already journalled."""
        assert self.settled[name].wait(SLOW_SECONDS + 5.0), f"tool {name!r} never settled"

    def late_effects(self) -> list[tuple[str, str, float]]:
        """Effects journalled more than the containment target after the
        stop was accepted (ADD v1.3 section 5.5: <=10 s)."""
        assert self.stop_accepted_at is not None
        return [effect for effect in self.effects if effect[2] - self.stop_accepted_at > CONTAINMENT_TARGET_SECONDS]

    def lease(self, *tools: str) -> CapabilityLease:
        return self.authority.issue(
            subject="agent-1",
            capabilities=[f"tool:{tool}" for tool in tools],
            resources=list(tools),
            issued_at=NOW,
            ttl=timedelta(hours=1),
        )

    def accept_stop(self) -> None:
        """The external control plane accepts a stop on its own thread; the
        caller resumes only once the stop has been accepted."""

        def run() -> None:
            self.stop.activate(reason="external emergency stop", at=datetime.now(UTC))
            self.stop_accepted_at = time.monotonic()

        worker = threading.Thread(target=run)
        worker.start()
        worker.join()

    def accept_stop_later(self, delay: float) -> None:
        def run() -> None:
            time.sleep(delay)
            self.accept_stop()

        threading.Thread(target=run, daemon=True).start()

    def reset(self) -> None:
        self.stop.finish_draining(at=NOW)
        self.stop.request_reset(approvers=HUMANS, identities=self.identities, at=NOW)
        self.stop.confirm_reset(at=NOW)

    def invoke(
        self,
        expression: str,
        lease: CapabilityLease,
        *,
        tool_name: str = "restart_service",
        budget: TokenBudget | None = None,
        stop_epoch: int | None = None,
    ) -> Any:
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
            stop_epoch=self.stop.epoch if stop_epoch is None else stop_epoch,
            at=NOW,
        )

    def names(self) -> list[str]:
        return [name for name, _, _ in self.effects]


def slow_non_cooperative(harness: Harness) -> Callable[[str], None]:
    def body(_: str) -> None:
        try:
            time.sleep(SLOW_SECONDS)
        finally:
            harness.finished.set()

    return body


def slow_non_cooperative_swallowing_errors(harness: Harness) -> Callable[[str], None]:
    """A non-cooperative tool with a broad ``except Exception`` (a common
    retry/cleanup idiom): it never calls the cancellation checkpoint and
    swallows every ordinary error raised while it waits."""

    def body(_: str) -> None:
        try:
            deadline = time.monotonic() + SLOW_SECONDS
            while time.monotonic() < deadline:
                try:
                    time.sleep(0.05)
                except Exception as error:  # noqa: BLE001 - the idiom under test
                    harness.swallowed.append(error)
        finally:
            harness.finished.set()

    return body


def slow_cooperative(harness: Harness) -> Callable[[str], None]:
    def body(_: str) -> None:
        try:
            deadline = time.monotonic() + SLOW_SECONDS
            while time.monotonic() < deadline:
                checkpoint()
                time.sleep(0.05)
            checkpoint()
        except BaseException as error:
            # how the tool left: through its own checkpoint (cooperative) or
            # preempted by the runtime
            harness.cooperative_exits.append(type(error).__name__)
            raise
        finally:
            harness.finished.set()

    return body


# --- positive controls -----------------------------------------------------------


def test_without_a_stop_every_authorized_tool_runs_and_the_receipt_carries_the_current_epoch() -> None:
    harness = Harness()
    harness.tool("note")
    harness.tool("restart_service")
    lease = harness.lease("note", "restart_service")

    receipt = harness.invoke("[note(name), restart_service(name)]", lease)

    assert harness.names() == ["note", "restart_service"]
    assert receipt.result == ["note svc", "restart_service svc"]
    assert receipt.stop_epoch == harness.stop.epoch == 0


def test_a_lease_issued_at_the_new_epoch_is_accepted_after_a_dual_control_reset() -> None:
    harness = Harness()
    harness.tool("restart_service")
    harness.accept_stop()
    harness.reset()
    lease = harness.lease("restart_service")

    receipt = harness.invoke("restart_service(name)", lease)

    assert harness.names() == ["restart_service"]
    assert receipt.stop_epoch == harness.stop.epoch == 2


# --- C8-1: no new dispatch once the stop is accepted ----------------------------


def test_a_stop_accepted_after_the_gates_and_before_the_sandbox_produces_no_effect() -> None:
    harness = Harness()
    harness.tool("restart_service")
    lease = harness.lease("restart_service")

    class StopWhileCharging(TokenBudget):
        def consume(self, tokens: int, *, category: str) -> Any:
            harness.accept_stop()  # runs after every gate, before the sandbox
            return super().consume(tokens, category=category)

    with pytest.raises(ToolRuntimeError) as refused:
        harness.invoke("restart_service(name)", lease, budget=StopWhileCharging(1000))

    assert refused.value.reason_code == "STOP_BOUND_DENIED"
    assert harness.stop_accepted_at is not None
    assert harness.effects == []


def test_a_stop_accepted_between_two_tools_of_one_expression_prevents_the_second() -> None:
    harness = Harness()
    harness.tool("note", lambda _: harness.accept_stop())
    harness.tool("restart_service")
    lease = harness.lease("note", "restart_service")

    with pytest.raises(ToolRuntimeError) as refused:
        harness.invoke("[note(name), restart_service(name)]", lease)

    assert refused.value.reason_code == "STOP_BOUND_DENIED"
    assert harness.stop_accepted_at is not None
    assert harness.names() == ["note"]


# --- C8-2: preemptive and bounded --------------------------------------------------


def test_a_stop_during_a_slow_non_cooperative_tool_refuses_the_next_tool_within_the_target() -> None:
    # VF-001 (verdict OCOR-DEV-REM-0027-f48452c64777-0): the slow tool is
    # mutative -- its effect is journalled, with its timestamp, only after
    # the non-cooperative wait, i.e. later than the target after the stop.
    harness = Harness()
    harness.tool("slow_restart", slow_non_cooperative(harness))
    harness.tool("restart_service")
    lease = harness.lease("slow_restart", "restart_service")
    harness.accept_stop_later(STOP_AFTER_SECONDS)

    with pytest.raises(ToolRuntimeError) as refused:
        harness.invoke("[slow_restart(name), restart_service(name)]", lease, tool_name="slow_restart")
    returned_at = time.monotonic()
    assert harness.finished.wait(SLOW_SECONDS + 5.0)
    harness.wait_settled("slow_restart")

    assert refused.value.reason_code == "STOP_BOUND_DENIED"
    assert getattr(refused.value, "execution_unknown", False) is True
    assert harness.stop_accepted_at is not None
    assert returned_at - harness.stop_accepted_at <= CONTAINMENT_TARGET_SECONDS
    assert harness.late_effects() == []
    assert harness.effects == []


def test_a_stop_during_a_non_cooperative_tool_that_swallows_errors_still_prevents_its_late_effect() -> None:
    harness = Harness()
    harness.tool("slow_restart", slow_non_cooperative_swallowing_errors(harness))
    harness.tool("restart_service")
    lease = harness.lease("slow_restart", "restart_service")
    harness.accept_stop_later(STOP_AFTER_SECONDS)

    with pytest.raises(ToolRuntimeError) as refused:
        harness.invoke("[slow_restart(name), restart_service(name)]", lease, tool_name="slow_restart")
    returned_at = time.monotonic()
    assert harness.finished.wait(SLOW_SECONDS + 5.0)
    harness.wait_settled("slow_restart")
    settled_at = time.monotonic()

    assert refused.value.reason_code == "STOP_BOUND_DENIED"
    assert refused.value.execution_unknown is True
    assert harness.stop_accepted_at is not None
    assert returned_at - harness.stop_accepted_at <= CONTAINMENT_TARGET_SECONDS
    # preempted at its next interpreter step, not after its own 11 s wait
    assert settled_at - harness.stop_accepted_at <= CONTAINMENT_TARGET_SECONDS
    assert harness.swallowed == []
    assert harness.late_effects() == []
    assert harness.effects == []


def test_a_fast_non_cooperative_tool_without_any_stop_still_produces_its_effect() -> None:
    harness = Harness(deadline=timedelta(seconds=2))
    harness.tool("short_restart", lambda _: time.sleep(0.3))
    harness.tool("restart_service")
    lease = harness.lease("short_restart", "restart_service")

    receipt = harness.invoke("[short_restart(name), restart_service(name)]", lease, tool_name="short_restart")
    harness.wait_settled("short_restart")

    assert receipt.result == ["short_restart svc", "restart_service svc"]
    assert harness.names() == ["short_restart", "restart_service"]


def test_a_stop_during_a_slow_cooperative_tool_cancels_it_with_no_effect() -> None:
    harness = Harness()
    harness.tool("slow_restart", slow_cooperative(harness))
    harness.tool("restart_service")
    lease = harness.lease("slow_restart", "restart_service")
    harness.accept_stop_later(STOP_AFTER_SECONDS)

    with pytest.raises(ToolRuntimeError) as refused:
        harness.invoke("[slow_restart(name), restart_service(name)]", lease, tool_name="slow_restart")
    returned_at = time.monotonic()
    assert harness.finished.wait(SLOW_SECONDS + 5.0)
    finished_at = time.monotonic()

    assert refused.value.reason_code == "STOP_BOUND_DENIED"
    assert harness.stop_accepted_at is not None
    assert returned_at - harness.stop_accepted_at <= CONTAINMENT_TARGET_SECONDS
    assert finished_at - harness.stop_accepted_at <= CONTAINMENT_TARGET_SECONDS
    assert harness.cooperative_exits == ["ToolCancelled"]
    assert harness.effects == []


def test_a_slow_tool_without_any_stop_is_bounded_by_the_call_deadline() -> None:
    harness = Harness()
    harness.tool("slow_restart", slow_non_cooperative(harness))
    harness.tool("restart_service")
    lease = harness.lease("slow_restart", "restart_service")
    started = time.monotonic()

    with pytest.raises(ToolRuntimeError) as refused:
        harness.invoke("[slow_restart(name), restart_service(name)]", lease, tool_name="slow_restart")
    returned_at = time.monotonic()
    assert harness.finished.wait(SLOW_SECONDS + 5.0)
    harness.wait_settled("slow_restart")

    assert refused.value.reason_code == "TOOL_DEADLINE_EXCEEDED"
    assert getattr(refused.value, "execution_unknown", False) is True
    assert returned_at - started <= CONTAINMENT_TARGET_SECONDS
    # no mutative effect once the call deadline has expired
    assert [effect for effect in harness.effects if effect[2] - started > CONTAINMENT_TARGET_SECONDS] == []
    assert harness.effects == []


def test_a_cooperative_tool_past_the_call_deadline_is_cancelled_with_no_effect() -> None:
    harness = Harness(deadline=timedelta(seconds=1))
    harness.tool("slow_restart", slow_cooperative(harness))
    lease = harness.lease("slow_restart")
    started = time.monotonic()

    with pytest.raises(ToolRuntimeError) as refused:
        harness.invoke("slow_restart(name)", lease, tool_name="slow_restart")
    assert harness.finished.wait(SLOW_SECONDS + 5.0)

    assert refused.value.reason_code == "TOOL_DEADLINE_EXCEEDED"
    assert time.monotonic() - started <= 3.0
    # the deadline reaches the tool through its cooperative checkpoint before
    # any preemption
    assert harness.cooperative_exits == ["ToolCancelled"]
    assert harness.effects == []


@pytest.mark.parametrize("deadline", [timedelta(0), timedelta(seconds=-1), timedelta(seconds=10, microseconds=1)])
def test_the_call_deadline_must_be_positive_and_within_the_containment_target(deadline: timedelta) -> None:
    with pytest.raises(ValueError):
        Harness(deadline=deadline)


# --- C8-3: leases are bound to the trusted stop epoch -----------------------------


def test_a_lease_issued_before_a_stop_is_refused_after_the_dual_control_reset() -> None:
    harness = Harness()
    harness.tool("restart_service")
    lease = harness.lease("restart_service")  # issued at epoch 0
    harness.accept_stop()
    harness.reset()

    with pytest.raises(ToolRuntimeError) as refused:
        harness.invoke("restart_service(name)", lease)  # the caller presents the current epoch 2

    assert refused.value.reason_code == "STOP_BOUND_DENIED"
    assert harness.effects == []


def test_a_lease_records_the_epoch_of_the_trusted_controller() -> None:
    harness = Harness()
    harness.tool("restart_service")
    harness.accept_stop()
    harness.reset()

    lease = harness.lease("restart_service")

    assert getattr(lease, "stop_epoch", None) == harness.stop.epoch == 2


def test_a_bound_authority_issues_no_lease_while_the_stop_is_active() -> None:
    harness = Harness()
    harness.accept_stop()

    with pytest.raises(AuthorizationError):
        harness.lease("restart_service")


def test_a_lease_not_bound_to_a_stop_epoch_is_refused() -> None:
    authority = CapabilityAuthority(issuer="rem-0027-unbound")
    unbound = authority.issue(
        subject="agent-1", capabilities=["tool:restart_service"], resources=["restart_service"], issued_at=NOW, ttl=timedelta(hours=1)
    )
    harness = Harness()
    harness.authority = authority
    harness.runtime = ToolCallRuntime(sandbox=harness.sandbox, authority=authority, marking_engine=harness.marking, stop=harness.stop)
    harness.tool("restart_service")

    with pytest.raises(ToolRuntimeError) as refused:
        harness.invoke("restart_service(name)", unbound)

    assert refused.value.reason_code == "STOP_BOUND_DENIED"
    assert harness.effects == []


def test_an_authority_bound_to_one_controller_cannot_be_rebound_to_another() -> None:
    harness = Harness()

    with pytest.raises(ValueError):
        ToolCallRuntime(sandbox=harness.sandbox, authority=harness.authority, marking_engine=harness.marking, stop=EmergencyStopController())


# --- class check: every tool actually called is covered by the lease ---------------


def test_an_unauthorized_second_tool_is_refused_before_any_effect() -> None:
    harness = Harness()
    harness.tool("restart_service")
    harness.tool("wipe_disk")
    lease = harness.lease("restart_service")
    budget = TokenBudget(1000)

    with pytest.raises(ToolRuntimeError) as refused:
        harness.invoke("[restart_service(name), wipe_disk(name)]", lease, budget=budget)

    assert refused.value.reason_code == "CAPABILITY_DENIED"
    assert harness.effects == []
    assert budget.used == 0


def test_a_lease_revoked_during_the_expression_refuses_the_next_tool() -> None:
    harness = Harness()
    holder: dict[str, CapabilityLease] = {}
    harness.tool("note", lambda _: harness.authority.revoke(holder["lease"].lease_id, at=NOW))
    harness.tool("restart_service")
    holder["lease"] = harness.lease("note", "restart_service")

    with pytest.raises(ToolRuntimeError) as refused:
        harness.invoke("[note(name), restart_service(name)]", holder["lease"], tool_name="note")

    assert refused.value.reason_code == "CAPABILITY_DENIED"
    assert harness.names() == ["note"]


def test_a_lease_issued_before_a_stop_cannot_delegate_after_the_reset() -> None:
    harness = Harness()
    parent = harness.lease("restart_service")  # issued at epoch 0
    harness.accept_stop()
    harness.reset()

    with pytest.raises(AuthorizationError):
        harness.authority.issue(
            subject="agent-2",
            capabilities=["tool:restart_service"],
            resources=["restart_service"],
            issued_at=NOW,
            ttl=timedelta(minutes=5),
            parent=parent,
        )


def test_a_pre_stop_lease_cannot_delegate_with_a_backdated_issuance_after_the_reset() -> None:
    # the child's issuance instant is the caller's: backdated inside the
    # parent's life before the stop, the parent still looks active then, so
    # only the epoch comparison refuses the delegation
    harness = Harness()
    issued_at = datetime.now(UTC) - timedelta(minutes=2)
    parent = harness.authority.issue(
        subject="agent-1",
        capabilities=["tool:restart_service"],
        resources=["restart_service"],
        issued_at=issued_at,
        ttl=timedelta(hours=1),
    )  # epoch 0
    harness.accept_stop()
    harness.reset()

    with pytest.raises(AuthorizationError):
        harness.authority.issue(
            subject="agent-2",
            capabilities=["tool:restart_service"],
            resources=["restart_service"],
            issued_at=issued_at + timedelta(minutes=1),
            ttl=timedelta(minutes=5),
            parent=parent,
        )


def test_a_lease_of_the_current_epoch_still_delegates() -> None:
    harness = Harness()
    harness.accept_stop()
    harness.reset()
    parent = harness.lease("restart_service")

    child = harness.authority.issue(
        subject="agent-2",
        capabilities=["tool:restart_service"],
        resources=["restart_service"],
        issued_at=NOW,
        ttl=timedelta(minutes=5),
        parent=parent,
    )

    assert child.parent_lease_id == parent.lease_id
    assert getattr(child, "stop_epoch", None) == harness.stop.epoch == 2


def test_a_command_fenced_before_the_stop_is_refused_even_with_a_fresh_lease() -> None:
    harness = Harness()
    harness.tool("restart_service")
    command_epoch = harness.stop.epoch  # the command was prepared at epoch 0
    harness.accept_stop()
    harness.reset()
    lease = harness.lease("restart_service")  # a fresh lease of the current epoch 2

    with pytest.raises(ToolRuntimeError) as refused:
        harness.invoke("restart_service(name)", lease, stop_epoch=command_epoch)

    assert refused.value.reason_code == "STOP_BOUND_DENIED"
    assert harness.effects == []


# --- VF-002: a parent bound to no epoch cannot delegate on a bound authority -------


def unbound_parent_and_harness() -> tuple[Harness, CapabilityLease]:
    """A lease issued by the authority before it was bound to the runtime's
    controller (``stop_epoch`` absent), then the authority is bound."""
    authority = CapabilityAuthority(issuer="rem-0027-late-bound")
    parent = authority.issue(
        subject="agent-1", capabilities=["tool:restart_service"], resources=["restart_service"], issued_at=NOW, ttl=timedelta(hours=1)
    )
    harness = Harness()
    harness.authority = authority
    harness.runtime = ToolCallRuntime(sandbox=harness.sandbox, authority=authority, marking_engine=harness.marking, stop=harness.stop)
    harness.tool("restart_service")
    assert parent.stop_epoch is None
    return harness, parent


def delegate(harness: Harness, parent: CapabilityLease, subject: str = "agent-1") -> CapabilityLease:
    return harness.authority.issue(
        subject=subject,
        capabilities=["tool:restart_service"],
        resources=["restart_service"],
        issued_at=NOW,
        ttl=timedelta(minutes=5),
        parent=parent,
    )


def test_a_parent_bound_to_no_epoch_cannot_delegate_after_a_stop_and_reset() -> None:
    harness, parent = unbound_parent_and_harness()
    harness.accept_stop()
    harness.reset()

    with pytest.raises(AuthorizationError):
        delegate(harness, parent)

    assert harness.effects == []


def test_a_parent_bound_to_no_epoch_cannot_delegate_even_without_a_stop() -> None:
    harness, parent = unbound_parent_and_harness()

    with pytest.raises(AuthorizationError):
        delegate(harness, parent)


def test_a_child_of_a_parent_of_the_current_epoch_runs_its_tool() -> None:
    harness = Harness()
    harness.tool("restart_service")
    parent = harness.lease("restart_service")

    child = delegate(harness, parent)
    receipt = harness.invoke("restart_service(name)", child)

    assert child.stop_epoch == parent.stop_epoch == harness.stop.epoch == 0
    assert receipt.stop_epoch == 0
    assert harness.names() == ["restart_service"]


# --- VF-003: the bound authority itself refuses stale leases ------------------------


def test_the_bound_authority_refuses_a_pre_stop_lease_after_the_reset_and_revokes_it_in_its_ledger() -> None:
    harness = Harness()
    issued_at = datetime.now(UTC) - timedelta(minutes=1)
    lease = harness.authority.issue(
        subject="agent-1",
        capabilities=["tool:restart_service"],
        resources=["restart_service"],
        issued_at=issued_at,
        ttl=timedelta(hours=1),
    )  # epoch 0
    harness.accept_stop()
    activation = harness.stop.history[0]
    harness.reset()
    later = activation.at + timedelta(seconds=1)

    with pytest.raises(AuthorizationError):
        harness.authority.authorize(lease, "tool:restart_service", "restart_service", at=later, subject="agent-1")
    recorded = harness.authority.get(lease.lease_id)

    assert lease.stop_epoch == 0
    assert recorded is not None
    # revoked at the accepted stop, not at the reset nor at the later check
    assert activation.at > issued_at
    assert recorded.revoked_at == activation.at
    assert not recorded.is_active(later)


def test_the_bound_authority_refuses_every_lease_while_the_stop_is_active() -> None:
    harness = Harness()
    lease = harness.lease("restart_service")
    harness.accept_stop()

    with pytest.raises(AuthorizationError):
        harness.authority.authorize(lease, "tool:restart_service", "restart_service", at=NOW, subject="agent-1")
    harness.stop.finish_draining(at=NOW)
    with pytest.raises(AuthorizationError):
        harness.authority.authorize(lease, "tool:restart_service", "restart_service", at=NOW, subject="agent-1")


def test_the_bound_authority_refuses_a_lease_bound_to_no_epoch() -> None:
    harness, parent = unbound_parent_and_harness()

    with pytest.raises(AuthorizationError):
        harness.authority.authorize(parent, "tool:restart_service", "restart_service", at=NOW, subject="agent-1")


def test_the_bound_authority_authorizes_a_lease_of_the_current_epoch_after_the_reset() -> None:
    harness = Harness()
    harness.accept_stop()
    harness.reset()
    lease = harness.lease("restart_service")

    authorized = harness.authority.authorize(lease, "tool:restart_service", "restart_service", at=NOW, subject="agent-1")

    assert authorized.stop_epoch == harness.stop.epoch == 2
    assert authorized.revoked_at is None


def test_another_gate_sharing_the_bound_authority_refuses_a_pre_stop_lease() -> None:
    # c8_agent.AgentKernel.execute_sandboxed is one of the other callers of
    # CapabilityAuthority.authorize (with c6/engine.py, c8/orchestrator.py
    # and c7_emission.py): sharing the authority bound by ToolCallRuntime,
    # it inherits the stop binding.
    harness = Harness()
    kernel = AgentKernel(sandbox=harness.sandbox, capability_authority=harness.authority, subject="agent-1")
    stale = harness.authority.issue(
        subject="agent-1", capabilities=["agent:sandbox"], resources=["agent-1"], issued_at=NOW, ttl=timedelta(hours=1)
    )
    assert kernel.execute_sandboxed("1 + 1", lease=stale, at=NOW) == 2
    harness.accept_stop()
    harness.reset()
    fresh = harness.authority.issue(
        subject="agent-1", capabilities=["agent:sandbox"], resources=["agent-1"], issued_at=NOW, ttl=timedelta(hours=1)
    )

    with pytest.raises(AuthorizationError):
        kernel.execute_sandboxed("1 + 1", lease=stale, at=NOW)
    assert kernel.execute_sandboxed("1 + 1", lease=fresh, at=NOW) == 2
