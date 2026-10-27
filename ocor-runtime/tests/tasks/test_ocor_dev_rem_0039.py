"""OCOR-DEV-REM-0039: Temporal runtime adapter of C6 behind the existing ports.

Change set b. of the PO normative decision OCOR-DEV-0060-BA-SELECTED-COMPONENTS
(2026-10-26), option 2. The BA-05 candidate of ADD v1.3 Part I §2.6 (Temporal +
PostgreSQL, provisioned by OCOR-DEV-REM-0038) backs two ports that already exist
and stay unchanged:

* ``kernel.governance.LeaseStatePort`` -- the single atomic validity-and-
  consumption boundary evaluated at emission (ACT-T14/T19/T29 guard
  revalidation, stale-worker fencing, stop-epoch precedence, at-most-once
  consumption per lease);
* ``c6.fsm.EffectSink`` -- the durable record of every declared transition
  effect of the 44-transition C6 table.

The live cases run against the real, pinned Temporal server of the
``ocor-bootstrap`` stack: an unavailable server fails, it never skips. The
reference semantics are the in-process ``InMemoryLeaseState``: the differential
case requires outcome-for-outcome identity. The failure-injection cases follow
the BA-05 conformance column: ambiguous timeout, stale worker, duplicate delivery.
"""

from __future__ import annotations

import ast
import importlib
import importlib.metadata
import json
import os
import statistics
import threading
import time
import tomllib
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ocor_runtime.c6.fsm import TRANSITIONS, GovernedActionFSM, PersistedEffect
from ocor_runtime.kernel.governance import (
    CapabilityLease,
    GovernanceFault,
    InMemoryLeaseState,
    InMemoryTrustedClock,
    LeaseConsumptionLedger,
    LeaseExpectation,
    LeaseStateOutcome,
)

RUNTIME_ROOT = Path(__file__).resolve().parents[2]
ADAPTER = "ocor_runtime.c6.temporal_adapter"
WORKFLOWS_PATH = RUNTIME_ROOT / "src/ocor_runtime/c6/temporal_workflows.py"
ADDRESS = os.environ.get("OCOR_LIVE_TEMPORAL_ADDRESS", "127.0.0.1:17233")
T0 = datetime(2026, 10, 28, 9, 0, 0, tzinfo=timezone.utc)
DIGEST = "urn:sha256:" + "a" * 64


def _adapter() -> ModuleType:
    return importlib.import_module(ADAPTER)


def _scope(label: str) -> str:
    return f"rem0039-{label}-{uuid.uuid4().hex[:12]}"


class _BrokenClock:
    def now(self) -> datetime:
        raise RuntimeError("trusted clock unavailable")


@pytest.fixture(scope="module")
def runtime() -> Iterator[Any]:
    module = _adapter()
    instance = module.TemporalC6Runtime(
        address=ADDRESS,
        namespace=module.DEFAULT_NAMESPACE,
        task_queue=_scope("queue"),
    )
    instance.start()
    instance.ensure_namespace()
    instance.start_worker()
    try:
        yield instance
    finally:
        try:
            instance._run(_terminate_open_workflows(instance), timeout=timedelta(seconds=60))
        finally:
            instance.close()


async def _terminate_open_workflows(instance: Any) -> int:
    """Leave the disposable namespace without workflows started by this module."""
    terminated = 0
    query = f'TaskQueue="{instance.task_queue}" AND ExecutionStatus="Running"'
    async for execution in instance.client.list_workflows(query):
        handle = instance.client.get_workflow_handle(execution.id, run_id=execution.run_id)
        await handle.terminate(reason="OCOR-DEV-REM-0039 test teardown")
        terminated += 1
    return terminated


def _lease(action: str, *, token: int = 1, epoch: int = 0, lease_id: str | None = None) -> CapabilityLease:
    return CapabilityLease(
        lease_id=lease_id or f"lease-{uuid.uuid4().hex[:10]}",
        capability_id="cap.dispatch",
        effective_principal_id="principal-1",
        delegation_ref=DIGEST,
        action_instance_id=action,
        governed_context_digest=DIGEST,
        gate_package_digest=DIGEST,
        stop_epoch=epoch,
        fencing_token=token,
        issued_at=T0,
        expires_at=T0 + timedelta(seconds=5),
    )


def _expect(lease: CapabilityLease, *, attempt: int = 1) -> LeaseExpectation:
    return LeaseExpectation(
        capability_id=lease.capability_id,
        effective_principal_id=lease.effective_principal_id,
        delegation_ref=lease.delegation_ref,
        action_instance_id=lease.action_instance_id,
        governed_context_digest=lease.governed_context_digest,
        gate_package_digest=lease.gate_package_digest,
        stop_epoch=lease.stop_epoch,
        fencing_token=lease.fencing_token,
        emission_attempt=attempt,
        at=T0,
    )


def _consume(state: Any, clock: Any, lease_id: str, action: str, *, epoch: int = 0, token: int = 1,
             attempt: int = 1, issued: datetime = T0, expires: datetime | None = None) -> Any:
    return state.consume_if_current(
        clock=clock,
        lease_id=lease_id,
        action_instance_id=action,
        stop_epoch=epoch,
        fencing_token=token,
        emission_attempt=attempt,
        issued_at=issued,
        expires_at=expires or issued + timedelta(seconds=5),
    )


# --------------------------------------------------------------------------- static


def test_dependency_is_pinned_exactly_with_its_licence_and_wheel_identity() -> None:
    project = tomllib.loads((RUNTIME_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "temporalio==1.34.0" in project["project"]["optional-dependencies"]["test"]
    lock = tomllib.loads((RUNTIME_ROOT / "uv.lock").read_text(encoding="utf-8"))
    [package] = [item for item in lock["package"] if item["name"] == "temporalio"]
    assert package["version"] == "1.34.0"
    assert package["source"] == {"registry": "https://pypi.org/simple"}
    hashes = {wheel["url"].rsplit("/", 1)[1]: wheel["hash"] for wheel in package["wheels"]}
    assert hashes["temporalio-1.34.0-cp310-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"] == (
        "sha256:540761f738bdfe5cb5bd7240b659e116a0b5094b94282aef09b8d8c2d66e9c52"
    )
    assert importlib.metadata.version("temporalio") == "1.34.0"
    assert importlib.metadata.metadata("temporalio")["License-Expression"] == "MIT"


def test_workflow_module_imports_only_deterministic_dependencies() -> None:
    tree = ast.parse(WORKFLOWS_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "workflow code may not import repository modules"
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "asyncio", "dataclasses", "typing", "temporalio"}, imported
    forbidden = {"time", "random", "datetime", "uuid", "os", "threading", "socket"}
    assert not imported & forbidden


def test_lease_state_validation_mirrors_the_reference_before_any_network_call() -> None:
    module = _adapter()
    offline = module.TemporalC6Runtime(address="127.0.0.1:1", namespace=module.DEFAULT_NAMESPACE, task_queue="unused")
    invalid: list[dict[str, Any]] = [
        {"stop_epoch": -1, "fencing_tokens": {}},
        {"stop_epoch": True, "fencing_tokens": {}},
        {"stop_epoch": 0, "fencing_tokens": {"": 1}},
        {"stop_epoch": 0, "fencing_tokens": {"a": 0}},
        {"stop_epoch": 0, "fencing_tokens": {"a": True}},
        {"stop_epoch": 0, "fencing_tokens": {}, "revoked_lease_ids": "lease-1"},
        {"stop_epoch": 0, "fencing_tokens": {}, "revoked_lease_ids": [""]},
    ]
    for arguments in invalid:
        with pytest.raises(ValueError):
            InMemoryLeaseState(**arguments)
        with pytest.raises(ValueError):
            module.TemporalLeaseState.create(offline, scope="never-contacted", **arguments)


def test_non_serialisable_effect_context_is_refused_before_any_network_call() -> None:
    module = _adapter()
    offline = module.TemporalC6Runtime(address="127.0.0.1:1", namespace=module.DEFAULT_NAMESPACE, task_queue="unused")
    sink = module.TemporalEffectSink(offline)
    record = PersistedEffect("ACT-T14", "COMMAND_READY", "DISPATCHED", "DeliveryAttempt + invio", T0, "corr-1", {"x": object()})
    with pytest.raises(TypeError):
        sink.persist_effect(record)


def test_unavailable_server_fails_closed() -> None:
    module = _adapter()
    offline = module.TemporalC6Runtime(
        address="127.0.0.1:1", namespace=module.DEFAULT_NAMESPACE, task_queue="unused",
        call_timeout=timedelta(seconds=2),
    )
    with pytest.raises(module.TemporalAdapterError):
        offline.start()
    offline.close()


# ----------------------------------------------------------------------------- live


def test_live_server_is_the_locked_version_and_namespace_registration_is_idempotent(runtime: Any) -> None:
    assert runtime.server_version() == "1.32.1"
    runtime.ensure_namespace()
    assert runtime.namespace == _adapter().DEFAULT_NAMESPACE


def test_live_lease_state_matches_the_in_memory_reference_outcome_for_outcome(runtime: Any) -> None:
    module = _adapter()
    tokens = {"act-a": 1, "act-b": 3}
    reference = InMemoryLeaseState(stop_epoch=2, fencing_tokens=tokens, revoked_lease_ids=["revoked-1"])
    durable = module.TemporalLeaseState.create(
        runtime, scope=_scope("diff"), stop_epoch=2, fencing_tokens=tokens, revoked_lease_ids=["revoked-1"]
    )
    clock = InMemoryTrustedClock(T0 + timedelta(seconds=1))
    cases: list[tuple[Any, dict[str, Any]]] = [
        (clock, {"lease_id": "l-ok", "action": "act-a", "epoch": 2, "token": 1}),
        (clock, {"lease_id": "l-ok", "action": "act-a", "epoch": 2, "token": 1}),
        (clock, {"lease_id": "l-ok", "action": "act-a", "epoch": 2, "token": 1, "attempt": 2}),
        (clock, {"lease_id": "l-early", "action": "act-a", "epoch": 2, "token": 1, "issued": T0 + timedelta(seconds=2)}),
        (clock, {"lease_id": "l-late", "action": "act-a", "epoch": 2, "token": 1,
                 "issued": T0 - timedelta(seconds=4), "expires": T0 + timedelta(seconds=1)}),
        (clock, {"lease_id": "revoked-1", "action": "act-a", "epoch": 2, "token": 1}),
        (clock, {"lease_id": "l-epoch", "action": "act-a", "epoch": 1, "token": 1}),
        (clock, {"lease_id": "l-stale", "action": "act-b", "epoch": 2, "token": 2}),
        (clock, {"lease_id": "l-ahead", "action": "act-b", "epoch": 2, "token": 4}),
        (clock, {"lease_id": "l-unknown", "action": "act-z", "epoch": 2, "token": 1}),
        (clock, {"lease_id": "l-b", "action": "act-b", "epoch": 2, "token": 3}),
        (_BrokenClock(), {"lease_id": "l-clock", "action": "act-a", "epoch": 2, "token": 1}),
        # Revocation is checked before the stop epoch and the stop epoch before the token.
        (clock, {"lease_id": "revoked-1", "action": "act-b", "epoch": 9, "token": 9}),
        (clock, {"lease_id": "l-order", "action": "act-b", "epoch": 9, "token": 9}),
    ]
    observed = []
    for case_clock, case in cases:
        arguments = dict(case)
        lease_id, action = arguments.pop("lease_id"), arguments.pop("action")
        expected = _consume(reference, case_clock, lease_id, action, **arguments)
        actual = _consume(durable, case_clock, lease_id, action, **arguments)
        assert actual == expected, (case, expected, actual)
        observed.append(actual.outcome)
    assert set(observed) == set(LeaseStateOutcome)
    for lease_id in ("l-ok", "l-b", "l-stale", "unknown"):
        assert durable.consumption(lease_id) == reference.consumption(lease_id)


def test_live_ledger_over_temporal_consumes_once_and_maps_every_refusal(runtime: Any) -> None:
    module = _adapter()
    state = module.TemporalLeaseState.create(runtime, scope=_scope("ledger"), stop_epoch=0, fencing_tokens={"act-1": 1})
    ledger = LeaseConsumptionLedger(clock=InMemoryTrustedClock(T0 + timedelta(seconds=1)), state=state)
    lease = _lease("act-1")
    receipt = ledger.consume(lease, _expect(lease), signature_verified=True)
    assert receipt.consumption_key == (lease.lease_id, "act-1", 1)
    assert receipt.consumed_at == T0 + timedelta(seconds=1)
    with pytest.raises(GovernanceFault) as duplicate:
        ledger.consume(lease, _expect(lease), signature_verified=True)
    assert duplicate.value.reason_code == "LEASE_ALREADY_CONSUMED"
    state.revoke("lease-revoked")
    revoked = _lease("act-1", lease_id="lease-revoked")
    with pytest.raises(GovernanceFault) as refused:
        ledger.consume(revoked, _expect(revoked), signature_verified=True)
    assert refused.value.reason_code == "LEASE_REVOKED"
    late = LeaseConsumptionLedger(clock=InMemoryTrustedClock(T0 + timedelta(seconds=5)), state=state)
    expired = _lease("act-1")
    with pytest.raises(GovernanceFault) as window:
        late.consume(expired, _expect(expired), signature_verified=True)
    assert window.value.reason_code == "LEASE_EXPIRED"


def test_live_stale_worker_is_fenced_across_worker_loss_and_a_new_process(runtime: Any) -> None:
    module = _adapter()
    scope = _scope("stale")
    state = module.TemporalLeaseState.create(runtime, scope=scope, stop_epoch=0, fencing_tokens={"act-1": 1})
    clock = InMemoryTrustedClock(T0 + timedelta(seconds=1))
    stale = _lease("act-1", token=1)
    # A new worker takes the action over: the token advances before the old one emits.
    state.set_fencing_token("act-1", 2)
    with pytest.raises(GovernanceFault) as fenced:
        LeaseConsumptionLedger(clock=clock, state=state).consume(stale, _expect(stale), signature_verified=True)
    assert fenced.value.reason_code == "FENCING_TOKEN_STALE"
    assert state.consumption(stale.lease_id) is None

    # The serving worker and process disappear; a new process attaches to the durable state.
    successor = module.TemporalC6Runtime(address=ADDRESS, namespace=runtime.namespace, task_queue=runtime.task_queue)
    successor.start()
    try:
        runtime.stop_worker()
        successor.start_worker()
        attached = module.TemporalLeaseState.attach(successor, scope=scope)
        with pytest.raises(GovernanceFault) as again:
            LeaseConsumptionLedger(clock=clock, state=attached).consume(stale, _expect(stale), signature_verified=True)
        assert again.value.reason_code == "FENCING_TOKEN_STALE"
        current = _lease("act-1", token=2)
        LeaseConsumptionLedger(clock=clock, state=attached).consume(current, _expect(current), signature_verified=True)
        assert attached.consumption(current.lease_id) == ("act-1", 1)
        with pytest.raises(ValueError):
            attached.set_fencing_token("act-1", 1)
    finally:
        successor.close()
        runtime.start_worker()


def test_live_stop_epoch_takes_precedence_at_emission_and_never_moves_backwards(runtime: Any) -> None:
    module = _adapter()
    state = module.TemporalLeaseState.create(runtime, scope=_scope("stop"), stop_epoch=0, fencing_tokens={"act-1": 1})
    lease = _lease("act-1", epoch=0)
    state.set_stop_epoch(1)
    with pytest.raises(GovernanceFault) as stopped:
        LeaseConsumptionLedger(clock=InMemoryTrustedClock(T0), state=state).consume(lease, _expect(lease), signature_verified=True)
    assert stopped.value.reason_code == "STOP_EPOCH_MISMATCH"
    with pytest.raises(ValueError):
        state.set_stop_epoch(0)
    with pytest.raises(TypeError):
        state.set_stop_epoch("2")
    with pytest.raises(ValueError):
        state.set_fencing_token("", 1)
    with pytest.raises(ValueError):
        state.revoke("")


def test_live_ambiguous_timeout_fails_closed_and_never_yields_a_second_consumption(runtime: Any) -> None:
    module = _adapter()
    scope = _scope("ambiguous")
    state = module.TemporalLeaseState.create(runtime, scope=scope, stop_epoch=0, fencing_tokens={"act-1": 1})
    lease = _lease("act-1")
    clock = InMemoryTrustedClock(T0 + timedelta(seconds=1))
    impatient = module.TemporalC6Runtime(
        address=ADDRESS, namespace=runtime.namespace, task_queue=runtime.task_queue,
        call_timeout=timedelta(seconds=3),
    )
    impatient.start()
    try:
        runtime.stop_worker()  # the request reaches the server, no worker completes it in time
        ambiguous = module.TemporalLeaseState.attach(impatient, scope=scope)
        with pytest.raises(GovernanceFault) as unknown:
            LeaseConsumptionLedger(clock=clock, state=ambiguous).consume(lease, _expect(lease), signature_verified=True)
        assert unknown.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"
    finally:
        impatient.close()
        runtime.start_worker()
    deadline = time.monotonic() + 20
    late = state.consumption(lease.lease_id)
    while late is None and time.monotonic() < deadline:
        time.sleep(0.5)
        late = state.consumption(lease.lease_id)
    retry = _consume(state, clock, lease.lease_id, "act-1")
    print(f"AMBIGUOUS_TIMEOUT late_consumption={late!r} retry={retry.outcome.value}")
    if late is not None:
        # The admitted request completed after the caller gave up: the retry may not dispatch again.
        assert late == ("act-1", 1)
        assert retry.outcome is LeaseStateOutcome.ALREADY_CONSUMED
    else:
        assert retry.outcome is LeaseStateOutcome.CONSUMED
    consumed = [item for item in state.attempts() if item["lease_id"] == lease.lease_id and item["outcome"] == "CONSUMED"]
    assert len(consumed) == 1


def test_live_concurrent_duplicate_delivery_consumes_exactly_once(runtime: Any) -> None:
    module = _adapter()
    state = module.TemporalLeaseState.create(runtime, scope=_scope("dup"), stop_epoch=0, fencing_tokens={"act-1": 1})
    clock = InMemoryTrustedClock(T0 + timedelta(seconds=1))
    outcomes: list[LeaseStateOutcome] = []
    lock = threading.Lock()

    def deliver(attempt: int) -> None:
        decision = _consume(state, clock, "lease-dup", "act-1", attempt=attempt)
        with lock:
            outcomes.append(decision.outcome)

    threads = [threading.Thread(target=deliver, args=(index + 1,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(outcomes) == sorted([LeaseStateOutcome.CONSUMED] + [LeaseStateOutcome.ALREADY_CONSUMED] * 7)
    winner = state.consumption("lease-dup")
    assert winner is not None and winner[0] == "act-1"


def test_live_every_delivery_attempt_is_preserved(runtime: Any) -> None:
    module = _adapter()
    state = module.TemporalLeaseState.create(runtime, scope=_scope("attempts"), stop_epoch=0, fencing_tokens={"act-1": 2})
    clock = InMemoryTrustedClock(T0 + timedelta(seconds=1))
    _consume(state, clock, "lease-a", "act-1", token=1)
    _consume(state, clock, "lease-b", "act-1", token=2)
    _consume(state, clock, "lease-b", "act-1", token=2, attempt=2)
    attempts = state.attempts()
    assert [(item["lease_id"], item["emission_attempt"], item["outcome"]) for item in attempts] == [
        ("lease-a", 1, "FENCING_TOKEN_STALE"),
        ("lease-b", 1, "CONSUMED"),
        ("lease-b", 2, "ALREADY_CONSUMED"),
    ]
    assert all(item["evaluated_at"] == "2026-10-28T09:00:01.000000Z" for item in attempts)


def test_live_scope_creation_never_reinitialises_and_attach_requires_a_running_scope(runtime: Any) -> None:
    module = _adapter()
    scope = _scope("create")
    state = module.TemporalLeaseState.create(runtime, scope=scope, stop_epoch=0, fencing_tokens={"act-1": 1})
    _consume(state, InMemoryTrustedClock(T0), "lease-1", "act-1")
    with pytest.raises(module.TemporalAdapterError):
        module.TemporalLeaseState.create(runtime, scope=scope, stop_epoch=0, fencing_tokens={"act-1": 1})
    assert module.TemporalLeaseState.attach(runtime, scope=scope).consumption("lease-1") == ("act-1", 1)
    with pytest.raises(module.TemporalAdapterError):
        module.TemporalLeaseState.attach(runtime, scope=_scope("absent"))


def test_live_effect_sink_durably_records_all_44_transitions_in_order(runtime: Any) -> None:
    module = _adapter()
    sink = module.TemporalEffectSink(runtime)
    fsm = GovernedActionFSM()
    correlation = _scope("fsm44")
    applied = []
    for index, transition in enumerate(TRANSITIONS):
        applied.append(
            fsm.apply(
                transition.transition_id,
                sink=sink,
                at=T0 + timedelta(milliseconds=index),
                correlation_id=correlation,
                context={"index": index, "action_id": correlation},
            )
        )
    stored = sink.effects(correlation)
    assert len(stored) == 44
    assert [item.transition_id for item in stored] == [item.transition_id for item in TRANSITIONS]
    assert stored == applied


def test_live_duplicate_effect_delivery_is_idempotent_and_conflicting_redelivery_is_refused(runtime: Any) -> None:
    module = _adapter()
    sink = module.TemporalEffectSink(runtime)
    correlation = _scope("effect-dup")
    record = PersistedEffect("ACT-T14", "COMMAND_READY", "DISPATCHED", "DeliveryAttempt + invio", T0, correlation, {"attempt": 1})
    assert sink.persist_effect(record) is None
    assert sink.persist_effect(record) is None
    conflicting = PersistedEffect("ACT-T14", "COMMAND_READY", "DISPATCHED", "DeliveryAttempt + invio", T0, correlation, {"attempt": 2})
    with pytest.raises(module.TemporalAdapterError) as conflict:
        sink.persist_effect(conflicting)
    assert "EFFECT_CONFLICT" in str(conflict.value)
    assert sink.effects(correlation) == [record]


def test_live_cancellation_after_dispatch_is_never_presumed(runtime: Any) -> None:
    module = _adapter()
    sink = module.TemporalEffectSink(runtime)
    correlation = _scope("cancel")
    fsm = GovernedActionFSM()
    dispatched = fsm.apply("ACT-T14", sink=sink, at=T0, correlation_id=correlation)
    runtime.cancel_workflow(sink.workflow_id(correlation))
    unknown = fsm.apply("ACT-T18a", sink=sink, at=T0 + timedelta(seconds=1), correlation_id=correlation)
    assert runtime.workflow_status(sink.workflow_id(correlation)) == "RUNNING"
    assert sink.effects(correlation) == [dispatched, unknown]

    scope = _scope("cancel-state")
    state = module.TemporalLeaseState.create(runtime, scope=scope, stop_epoch=0, fencing_tokens={"act-1": 1})
    _consume(state, InMemoryTrustedClock(T0), "lease-1", "act-1")
    runtime.cancel_workflow(state.workflow_id)
    assert _consume(state, InMemoryTrustedClock(T0), "lease-1", "act-1").outcome is LeaseStateOutcome.ALREADY_CONSUMED
    assert runtime.workflow_status(state.workflow_id) == "RUNNING"


def test_live_terminated_state_fails_closed_through_the_ledger(runtime: Any) -> None:
    module = _adapter()
    state = module.TemporalLeaseState.create(runtime, scope=_scope("terminated"), stop_epoch=0, fencing_tokens={"act-1": 1})
    runtime.terminate_workflow(state.workflow_id, reason="rem0039 fault injection")
    lease = _lease("act-1")
    with pytest.raises(GovernanceFault) as unavailable:
        LeaseConsumptionLedger(clock=InMemoryTrustedClock(T0), state=state).consume(lease, _expect(lease), signature_verified=True)
    assert unavailable.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"


def test_live_dep011_benchmark_is_measured_and_recorded(runtime: Any) -> None:
    module = _adapter()
    count = 200
    state = module.TemporalLeaseState.create(runtime, scope=_scope("bench"), stop_epoch=0, fencing_tokens={"act-1": 1})
    clock = InMemoryTrustedClock(T0 + timedelta(seconds=1))
    latencies = []
    started = time.perf_counter()
    for index in range(count):
        begin = time.perf_counter()
        decision = _consume(state, clock, f"bench-{index}", "act-1")
        latencies.append(time.perf_counter() - begin)
        assert decision.outcome is LeaseStateOutcome.CONSUMED
    elapsed = time.perf_counter() - started
    ordered = sorted(latencies)
    result = {
        "benchmark": "DEP-011 Temporal LeaseStatePort consume_if_current, sequential, single scope",
        "server_version": runtime.server_version(),
        "sdk": f"temporalio {importlib.metadata.version('temporalio')}",
        "operations": count,
        "seconds": round(elapsed, 3),
        "throughput_per_second": round(count / elapsed, 1),
        "latency_ms": {
            "p50": round(statistics.median(ordered) * 1000, 2),
            "p95": round(ordered[int(0.95 * count) - 1] * 1000, 2),
            "max": round(ordered[-1] * 1000, 2),
        },
        "threshold": "none declared by DEP-011; measured and recorded only",
    }
    print("DEP011_BENCHMARK " + json.dumps(result, sort_keys=True))
    assert len(state.attempts()) == count
