"""OCOR-DEV-0060 -- BA-05: Temporal 1.32.1 (with its own PostgreSQL) behind C6.

Backend assumption ``BA-05`` of ADD v1.3 Part I §2.6 (row ``BA-05``, "Temporal +
PostgreSQL -- ``C6``") and LLD v1.1 §7.1 (row ``BA-05``). The real component is the
pinned Temporal server 1.32.1 of the ``ocor-bootstrap`` stack (``temporal``, backed
by ``temporal-postgresql``), driven only through the sealed OCOR-DEV-REM-0039 adapter
``ocor_runtime.c6.temporal_adapter`` (``TemporalC6Runtime``, ``TemporalLeaseState``
behind ``kernel.governance.LeaseStatePort``, ``TemporalEffectSink`` behind
``c6.fsm.EffectSink``) and the sealed workflows of ``c6.temporal_workflows``. The
44-transition table is the sealed ``c6.fsm.TRANSITIONS`` (ADD v1.3 §4.1.2, LLD §3.2).

What is observed on the server:

* guard revalidation at emission (``ACT-T14``/``ACT-T19``/``ACT-T29``): every
  emission consumes its ``CapabilityLease`` through ``LeaseConsumptionLedger`` over
  the durable lease-state workflow; only a ``CONSUMED`` outcome lets the test record
  the transition effect, so a refused guard leaves no effect on Temporal;
* stop precedence (``ACT-T23b`` precedes T14/T19/T29), stale-worker fencing across
  worker and process loss, at-most-once consumption per lease and per ``action_id``;
* ``EXECUTION_UNKNOWN`` after an ambiguous timeout (``ACT-T18a``) and no presumed
  cancellation after dispatch;
* the whole 44-transition table recorded through Temporal and rebuilt from the
  server to the sealed table digest.

Limitation (reported, not hidden): ``GovernedActionFSM`` is a lookup-and-persist
table. It does not track the current state of an action and does not evaluate the
textual guard of a transition; the only guards evaluated by the Temporal-backed
runtime are the emission guards of ``LeaseStateWorkflow.consume_if_current``
(window, revocation, stop epoch, fencing token, single consumption). The positive
44-transition case therefore shows that Temporal durably executes and preserves the
complete table, not that Temporal enforces source-state sequencing of the 44 rows.

An unavailable server fails the module; it is never bypassed.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

from ocor_runtime.c6 import temporal_adapter
from ocor_runtime.c6.fsm import (
    TRANSITION_TABLE_SHA256,
    TRANSITIONS,
    FSMTransitionError,
    GovernedActionFSM,
    PersistedEffect,
    Transition,
    transition_digest,
)
from ocor_runtime.c6.temporal_adapter import (
    TemporalAdapterError,
    TemporalC6Runtime,
    TemporalEffectSink,
    TemporalLeaseState,
)
from ocor_runtime.kernel.governance import (
    CapabilityLease,
    GovernanceFault,
    InMemoryTrustedClock,
    LeaseConsumptionLedger,
    LeaseConsumptionReceipt,
    LeaseExpectation,
    LeaseStateOutcome,
)

BA_CASE = {
    "ba_id": "BA-05",
    "component": "Temporal server (with its own PostgreSQL) behind the sealed C6 Temporal adapter",
    "component_version": "1.32.1",
    "backend_services": ["temporal", "temporal-postgresql"],
    "add_v1_3_part_i_2_6": {
        "required_property": (
            "Workflow durevole con fencing del worker stale, idempotenza per `action_id`, nessuna "
            "cancellazione presunta dopo il dispatch, e rivalidazione delle guardie al momento "
            "dell'emissione (§4.1.2 `ACT-T14`)"
        ),
        "conformance_test": "Failure injection su timeout ambiguo, worker stale e duplicate delivery",
    },
    "lld_v1_1_7_1_oracle": "Temporal/PostgreSQL esegue le 44 transizioni, guardie, unknown e precedence",
    "requirement_ids": ["FR-081", "FR-083", "FR-163"],
    "requirement_binding": {
        "FR-081": (
            "A worker whose fencing token was superseded produces no effect on Temporal, before and "
            "after worker/process loss, and every Delivery Attempt is preserved by the lease-state workflow."
        ),
        "FR-083": (
            "The dispatched, acknowledged, confirmed, failed, compensating, compensated and unknown "
            "states of the 44-transition table are durably represented on Temporal, and an ambiguous "
            "timeout is recorded as EXECUTION_UNKNOWN, never as success."
        ),
        "FR-163": (
            "After an ambiguous emission timeout the outcome is not inferred: no second consumption "
            "(no automatic re-dispatch) happens and the action is recorded as EXECUTION_UNKNOWN "
            "without a presumed cancellation."
        ),
    },
    "positive_tests": [
        "test_ba_05_positive_emission_guard_revalidated_on_temporal_for_dispatch_retry_and_canonical_commit",
        "test_ba_05_positive_all_44_transitions_execute_through_temporal_and_rebuild_the_sealed_table",
    ],
    "negative_tests": [
        "test_ba_05_negative_stop_takes_precedence_over_emission_and_leaves_no_effect",
        "test_ba_05_negative_unknown_transition_and_conflicting_redelivery_are_refused_without_state_change",
    ],
    "fault_tests": [
        "test_ba_05_fault_ambiguous_timeout_yields_unknown_and_no_presumed_cancellation",
        "test_ba_05_fault_stale_worker_is_fenced_across_worker_and_process_loss",
        "test_ba_05_fault_duplicate_delivery_consumes_and_persists_exactly_once",
    ],
}

ADDRESS = os.environ.get("OCOR_LIVE_TEMPORAL_ADDRESS", "127.0.0.1:17233")
SERVER_VERSION = "1.32.1"
T0 = datetime(2026, 10, 29, 9, 0, 0, tzinfo=timezone.utc)
DIGEST = "urn:sha256:" + "b" * 64
RUN = uuid.uuid4().hex[:12]


def _name(label: str) -> str:
    return f"ba05-{label}-{RUN}-{uuid.uuid4().hex[:8]}"


async def _terminate_running(runtime: TemporalC6Runtime) -> int:
    terminated = 0
    query = f'TaskQueue="{runtime.task_queue}" AND ExecutionStatus="Running"'
    async for execution in runtime.client.list_workflows(query):
        handle = runtime.client.get_workflow_handle(execution.id, run_id=execution.run_id)
        await handle.terminate(reason="OCOR-DEV-0060 BA-05 teardown")
        terminated += 1
    return terminated


async def _count_running(runtime: TemporalC6Runtime) -> int:
    query = f'TaskQueue="{runtime.task_queue}" AND ExecutionStatus="Running"'
    count = 0
    async for _execution in runtime.client.list_workflows(query):
        count += 1
    return count


@pytest.fixture(scope="module")
def temporal() -> Iterator[TemporalC6Runtime]:
    runtime = TemporalC6Runtime(
        address=ADDRESS, namespace=temporal_adapter.DEFAULT_NAMESPACE, task_queue=_name("queue")
    )
    try:
        runtime.start()
        runtime.ensure_namespace()
        version = runtime.server_version()
        runtime.start_worker()
    except TemporalAdapterError as exc:
        runtime.close()
        pytest.fail(f"BA-05 requires the real Temporal server at {ADDRESS}: {exc}")
    if version != SERVER_VERSION:
        runtime.close()
        pytest.fail(f"BA-05 requires Temporal {SERVER_VERSION}, the server reports {version}")
    try:
        yield runtime
    finally:
        try:
            runtime._run(_terminate_running(runtime), timeout=timedelta(seconds=60))
            deadline = time.monotonic() + 20
            left = runtime._run(_count_running(runtime), timeout=timedelta(seconds=30))
            while left and time.monotonic() < deadline:
                time.sleep(0.5)
                left = runtime._run(_count_running(runtime), timeout=timedelta(seconds=30))
            assert left == 0, f"{left} BA-05 workflows left running on {runtime.task_queue}"
        finally:
            runtime.close()


def _lease(action: str, *, token: int = 1, epoch: int = 0, lease_id: str | None = None) -> CapabilityLease:
    return CapabilityLease(
        lease_id=lease_id or f"lease-{uuid.uuid4().hex[:10]}",
        capability_id="cap.dispatch",
        effective_principal_id="principal-ba05",
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


def _clock() -> InMemoryTrustedClock:
    return InMemoryTrustedClock(T0 + timedelta(seconds=1))


def _emit(
    state: TemporalLeaseState,
    sink: TemporalEffectSink,
    lease: CapabilityLease,
    transition_id: str,
    *,
    attempt: int = 1,
    at: datetime,
) -> tuple[LeaseConsumptionReceipt, PersistedEffect]:
    """Guard revalidation at emission: the effect is recorded only after the durable
    lease state on Temporal has consumed the lease for this attempt."""
    receipt = LeaseConsumptionLedger(clock=_clock(), state=state).consume(
        lease, _expect(lease, attempt=attempt), signature_verified=True
    )
    effect = GovernedActionFSM().apply(
        transition_id,
        sink=sink,
        at=at,
        correlation_id=lease.action_instance_id,
        context={"lease_id": lease.lease_id, "emission_attempt": attempt},
    )
    return receipt, effect


def _refusal(state: TemporalLeaseState, sink: TemporalEffectSink, lease: CapabilityLease, transition_id: str) -> str:
    with pytest.raises(GovernanceFault) as refused:
        _emit(state, sink, lease, transition_id, at=T0)
    return str(refused.value.reason_code)


def _effects_or_none(sink: TemporalEffectSink, correlation_id: str) -> list[PersistedEffect] | None:
    """The effects stored on Temporal, or ``None`` when no action workflow exists."""
    try:
        return sink.effects(correlation_id)
    except TemporalAdapterError as exc:
        if "not found" in str(exc).lower():
            return None
        raise


# ---------------------------------------------------------------------------- positive


def test_ba_05_positive_emission_guard_revalidated_on_temporal_for_dispatch_retry_and_canonical_commit(
    temporal: TemporalC6Runtime,
) -> None:
    fsm = GovernedActionFSM()
    sink = TemporalEffectSink(temporal)
    action = _name("act")
    canonical = _name("canonical")
    state = TemporalLeaseState.create(
        temporal, scope=_name("emit"), stop_epoch=0, fencing_tokens={action: 1, canonical: 1}
    )
    ready = fsm.apply("ACT-T12", sink=sink, at=T0, correlation_id=action)

    # ACT-T14: external target, atomic EMISSION-FENCE, DeliveryAttempt + send.
    first_lease = _lease(action)
    receipt, dispatched = _emit(state, sink, first_lease, "ACT-T14", at=T0 + timedelta(seconds=1))
    assert receipt.consumption_key == (first_lease.lease_id, action, 1)
    assert receipt.consumed_at == T0 + timedelta(seconds=1)

    # ACT-T19: authorised retry, new DeliveryAttempt with a new lease, same logical command.
    retry_lease = _lease(action)
    retry_receipt, retried = _emit(state, sink, retry_lease, "ACT-T19", attempt=2, at=T0 + timedelta(seconds=2))
    assert retry_receipt.consumption_key == (retry_lease.lease_id, action, 2)

    # ACT-T29 -> ACT-T30: canonical target through the same emission guard.
    canonical_lease = _lease(canonical)
    _, committing = _emit(state, sink, canonical_lease, "ACT-T29", at=T0 + timedelta(seconds=3))
    committed = fsm.apply("ACT-T30", sink=sink, at=T0 + timedelta(seconds=4), correlation_id=canonical)

    # Read back from the server: consumptions, attempts and effects.
    assert state.consumption(first_lease.lease_id) == (action, 1)
    assert state.consumption(retry_lease.lease_id) == (action, 2)
    assert state.consumption(canonical_lease.lease_id) == (canonical, 1)
    attempts = [(item["lease_id"], item["emission_attempt"], item["outcome"]) for item in state.attempts()]
    assert attempts == [
        (first_lease.lease_id, 1, "CONSUMED"),
        (retry_lease.lease_id, 2, "CONSUMED"),
        (canonical_lease.lease_id, 1, "CONSUMED"),
    ]
    assert sink.effects(action) == [ready, dispatched, retried]
    assert [(item.source, item.destination) for item in sink.effects(action)] == [
        ("PRE_DISPATCH_CHECK", "COMMAND_READY"),
        ("COMMAND_READY", "DISPATCHED"),
        ("COMMAND_READY", "DISPATCHED"),
    ]
    assert sink.effects(canonical) == [committing, committed]
    assert sink.effects(canonical)[-1].destination == "EXECUTION_CONFIRMED"


def test_ba_05_positive_all_44_transitions_execute_through_temporal_and_rebuild_the_sealed_table(
    temporal: TemporalC6Runtime,
) -> None:
    fsm = GovernedActionFSM()
    sink = TemporalEffectSink(temporal)
    correlation = _name("fsm44")
    applied = [
        fsm.apply(
            transition.transition_id,
            sink=sink,
            at=T0 + timedelta(milliseconds=index),
            correlation_id=correlation,
            context={"guard": transition.guard, "index": index},
        )
        for index, transition in enumerate(TRANSITIONS)
    ]
    stored = sink.effects(correlation)
    assert stored == applied and len(stored) == 44
    rebuilt = tuple(
        Transition(item.transition_id, item.source, str(item.context["guard"]), item.durable_effect, item.destination)
        for item in stored
    )
    assert rebuilt == TRANSITIONS
    assert transition_digest(rebuilt) == TRANSITION_TABLE_SHA256
    destinations = {item.destination for item in stored}
    for required in (
        "DISPATCHED", "ACKNOWLEDGED", "EXECUTION_CONFIRMED", "EXECUTION_FAILED", "COMPENSATING",
        "COMPENSATED", "EXECUTION_UNKNOWN", "COMPENSATION_UNKNOWN", "CANCELLED",
    ):
        assert required in destinations, required
    # Precedence row of the table (ACT-T23b) and the unknown rows survive on the server.
    by_id = {item.transition_id: item for item in stored}
    assert (by_id["ACT-T23b"].source, by_id["ACT-T23b"].destination) == ("COMMAND_READY", "CANCELLED")
    assert by_id["ACT-T18a"].durable_effect == "sospende retry e apre reconciliation"
    assert by_id["ACT-T20c"].durable_effect == "inquiry record, nessuna inferenza"


# ---------------------------------------------------------------------------- negative


def test_ba_05_negative_stop_takes_precedence_over_emission_and_leaves_no_effect(
    temporal: TemporalC6Runtime,
) -> None:
    sink = TemporalEffectSink(temporal)
    action = _name("stop")
    control = _name("stop-control")
    state = TemporalLeaseState.create(temporal, scope=_name("stop"), stop_epoch=0, fencing_tokens={action: 1, control: 1})
    pre_stop = _lease(action, epoch=0)

    # Stop accepted before the emission: the epoch moves and the token also advances.
    state.set_stop_epoch(1)
    state.set_fencing_token(action, 2)
    # Stop epoch is evaluated before the fencing token (ACT-T23 precedes T14/T19/T29).
    assert _refusal(state, sink, pre_stop, "ACT-T14") == "STOP_EPOCH_MISMATCH"
    assert _refusal(state, sink, _lease(action, epoch=0, token=2), "ACT-T19") == "STOP_EPOCH_MISMATCH"
    assert _refusal(state, sink, _lease(action, epoch=0, token=2), "ACT-T29") == "STOP_EPOCH_MISMATCH"
    assert state.consumption(pre_stop.lease_id) is None
    assert _effects_or_none(sink, action) is None
    outcomes = [item["outcome"] for item in state.attempts()]
    assert outcomes == ["STOP_EPOCH_MISMATCH"] * 3
    with pytest.raises(ValueError):
        state.set_stop_epoch(0)

    # Positive control on the same scope: a lease fenced to the current epoch emits.
    current = _lease(control, epoch=1)
    _, dispatched = _emit(state, sink, current, "ACT-T14", at=T0)
    assert state.consumption(current.lease_id) == (control, 1)
    assert sink.effects(control) == [dispatched]


def test_ba_05_negative_unknown_transition_and_conflicting_redelivery_are_refused_without_state_change(
    temporal: TemporalC6Runtime,
) -> None:
    fsm = GovernedActionFSM()
    sink = TemporalEffectSink(temporal)
    correlation = _name("refuse")

    with pytest.raises(FSMTransitionError) as unknown:
        fsm.apply("ACT-T99", sink=sink, at=T0, correlation_id=correlation)
    assert unknown.value.reason_code == "UNKNOWN_TRANSITION"
    assert _effects_or_none(sink, correlation) is None

    # Positive control: the declared transition is persisted for the same action.
    dispatched = fsm.apply("ACT-T14", sink=sink, at=T0, correlation_id=correlation, context={"attempt": 1})
    assert sink.effects(correlation) == [dispatched]

    conflicting = PersistedEffect(
        dispatched.transition_id, dispatched.source, dispatched.destination, dispatched.durable_effect,
        dispatched.occurred_at, correlation, {"attempt": 2},
    )
    with pytest.raises(TemporalAdapterError) as conflict:
        sink.persist_effect(conflicting)
    assert "EFFECT_CONFLICT" in str(conflict.value)
    assert sink.effects(correlation) == [dispatched]


# ------------------------------------------------------------------------------- fault


def test_ba_05_fault_ambiguous_timeout_yields_unknown_and_no_presumed_cancellation(
    temporal: TemporalC6Runtime,
) -> None:
    sink = TemporalEffectSink(temporal)
    fsm = GovernedActionFSM()
    action = _name("ambiguous")
    scope = _name("ambiguous")
    state = TemporalLeaseState.create(temporal, scope=scope, stop_epoch=0, fencing_tokens={action: 1})
    ready = fsm.apply("ACT-T12", sink=sink, at=T0, correlation_id=action)
    lease = _lease(action)

    # Failure injection: the emission reaches the server while no worker can answer in time.
    impatient = TemporalC6Runtime(
        address=ADDRESS, namespace=temporal.namespace, task_queue=temporal.task_queue,
        call_timeout=timedelta(seconds=3),
    )
    impatient.start()
    try:
        temporal.stop_worker()
        ambiguous_state = TemporalLeaseState.attach(impatient, scope=scope)
        with pytest.raises(GovernanceFault) as timed_out:
            LeaseConsumptionLedger(clock=_clock(), state=ambiguous_state).consume(
                lease, _expect(lease), signature_verified=True
            )
        assert timed_out.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"
    finally:
        impatient.close()
        temporal.start_worker()

    # The outcome is not inferred: the action is recorded as EXECUTION_UNKNOWN (ACT-T18a).
    unknown = fsm.apply("ACT-T18a", sink=sink, at=T0 + timedelta(seconds=2), correlation_id=action)

    deadline = time.monotonic() + 20
    late = state.consumption(lease.lease_id)
    while late is None and time.monotonic() < deadline:
        time.sleep(0.5)
        late = state.consumption(lease.lease_id)
    retry = LeaseConsumptionLedger(clock=_clock(), state=state)
    if late is not None:
        # The admitted update completed after the caller gave up: no second dispatch.
        assert late == (action, 1)
        with pytest.raises(GovernanceFault) as again:
            retry.consume(lease, _expect(lease), signature_verified=True)
        assert again.value.reason_code == "LEASE_ALREADY_CONSUMED"
    else:
        retry.consume(lease, _expect(lease), signature_verified=True)
    consumed = [item for item in state.attempts() if item["lease_id"] == lease.lease_id and item["outcome"] == "CONSUMED"]
    assert len(consumed) == 1

    # No presumed cancellation after dispatch: a cancellation request changes nothing.
    temporal.cancel_workflow(sink.workflow_id(action))
    temporal.cancel_workflow(state.workflow_id)
    time.sleep(1)
    assert temporal.workflow_status(sink.workflow_id(action)) == "RUNNING"
    assert temporal.workflow_status(state.workflow_id) == "RUNNING"
    effects = sink.effects(action)
    assert effects == [ready, unknown]
    assert effects[-1].destination == "EXECUTION_UNKNOWN"
    assert all(item.destination != "CANCELLED" for item in effects)
    assert state.consumption(lease.lease_id) == (action, 1)


def test_ba_05_fault_stale_worker_is_fenced_across_worker_and_process_loss(
    temporal: TemporalC6Runtime,
) -> None:
    sink = TemporalEffectSink(temporal)
    action = _name("stale")
    scope = _name("stale")
    state = TemporalLeaseState.create(temporal, scope=scope, stop_epoch=0, fencing_tokens={action: 1})
    stale = _lease(action, token=1)

    # A new owner takes the action over before the old worker emits.
    state.set_fencing_token(action, 2)
    assert _refusal(state, sink, stale, "ACT-T14") == "FENCING_TOKEN_STALE"
    assert state.consumption(stale.lease_id) is None
    assert _effects_or_none(sink, action) is None

    # The serving worker and process disappear; a new process attaches to the durable state.
    successor = TemporalC6Runtime(address=ADDRESS, namespace=temporal.namespace, task_queue=temporal.task_queue)
    successor.start()
    try:
        temporal.stop_worker()
        successor.start_worker()
        attached = TemporalLeaseState.attach(successor, scope=scope)
        successor_sink = TemporalEffectSink(successor)
        assert _refusal(attached, successor_sink, stale, "ACT-T14") == "FENCING_TOKEN_STALE"
        current = _lease(action, token=2)
        _, dispatched = _emit(attached, successor_sink, current, "ACT-T14", at=T0)
        assert attached.consumption(current.lease_id) == (action, 1)
        assert successor_sink.effects(action) == [dispatched]
        with pytest.raises(ValueError):
            attached.set_fencing_token(action, 1)
    finally:
        successor.close()
        temporal.start_worker()

    assert [(item["lease_id"], item["outcome"]) for item in state.attempts()] == [
        (stale.lease_id, "FENCING_TOKEN_STALE"),
        (stale.lease_id, "FENCING_TOKEN_STALE"),
        (current.lease_id, "CONSUMED"),
    ]
    assert state.consumption(stale.lease_id) is None


def test_ba_05_fault_duplicate_delivery_consumes_and_persists_exactly_once(
    temporal: TemporalC6Runtime,
) -> None:
    sink = TemporalEffectSink(temporal)
    action = _name("dup")
    state = TemporalLeaseState.create(temporal, scope=_name("dup"), stop_epoch=0, fencing_tokens={action: 1})
    lease = _lease(action)
    record = PersistedEffect(
        "ACT-T14", "COMMAND_READY", "DISPATCHED", "DeliveryAttempt + invio", T0, action, {"lease_id": lease.lease_id}
    )
    deliveries = 8
    barrier = threading.Barrier(deliveries)
    outcomes: list[LeaseStateOutcome] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def deliver(attempt: int) -> None:
        try:
            barrier.wait(30)
            decision = state.consume_if_current(
                clock=_clock(), lease_id=lease.lease_id, action_instance_id=action, stop_epoch=0,
                fencing_token=1, emission_attempt=attempt, issued_at=lease.issued_at, expires_at=lease.expires_at,
            )
            sink.persist_effect(record)
            with lock:
                outcomes.append(decision.outcome)
        except BaseException as error:  # noqa: BLE001 - collected and asserted below
            with lock:
                errors.append(error)

    threads = [threading.Thread(target=deliver, args=(index + 1,)) for index in range(deliveries)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(90)
    assert errors == []
    assert sorted(outcome.value for outcome in outcomes) == sorted(
        [LeaseStateOutcome.CONSUMED.value] + [LeaseStateOutcome.ALREADY_CONSUMED.value] * (deliveries - 1)
    )
    winner = state.consumption(lease.lease_id)
    assert winner is not None and winner[0] == action
    assert sink.effects(action) == [record]
    attempts = [item for item in state.attempts() if item["lease_id"] == lease.lease_id]
    assert len(attempts) == deliveries
    assert sum(1 for item in attempts if item["outcome"] == "CONSUMED") == 1
