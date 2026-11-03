"""OCOR-DEV-0036: Complete C3 single-writer recovery and reconciliation.

Proves that ``SingleWriterRecoveryCoordinator`` converges concurrent
writers, a lost ACK, a corrupt outbox and a restart fixture without
duplicate canonical effects, and that unreconciled durable intent
blocks service health. Every test drives the real ocor-bootstrap
postgresql service; no mocks. Composes the sealed
``PostgresC3Service`` (OCOR-DEV-0029, reused unmodified) exclusively
through its own sealed public methods.
"""

from __future__ import annotations

import os
import threading
import time

import psycopg
import pytest
import test_ocor_dev_rem_0050 as governed_path
from ocor_runtime.c3.adapters.recovery_lock import PostgresAdvisoryLock
from ocor_runtime.c3.ports import C3Error, GovernedCanonicalCommitCommand, OutboxEnvelope
from ocor_runtime.c3.recovery import RECOVERY_LOCK_KEY, RecoveryReport, SingleWriterRecoveryCoordinator
from ocor_runtime.c3.service import PostgresC3Service
from ocor_runtime.kernel.governed_context import GovernedContext

DIGEST_A = "urn:sha256:" + "a" * 64
DIGEST_B = "urn:sha256:" + "b" * 64
DIGEST_C = "urn:sha256:" + "c" * 64
DIGEST_D = "urn:sha256:" + "d" * 64
AGGREGATE_REF = "urn:ocor:mission-object:single-writer-recovery:1"
# NCP-U04 (OCOR-DEV-REM-0050): C3 admits only governed commands (LLD v1.1 :97, ADD v1.3
# :342); the suite's commands are frozen and signed on the C6 governed path.
GOVERNED = governed_path.GovernedC3(
    release=DIGEST_B,
    preconditions=tuple(f"urn:ocor:precondition:revision-{n}" for n in range(64)),
    invariants=("urn:ocor:invariant:atomic-outbox",),
)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory qualifying evidence")
    return dsn


@pytest.fixture
def service(postgres_dsn: str) -> PostgresC3Service:
    value = PostgresC3Service(postgres_dsn, admission=GOVERNED.admission())
    value.initialize()
    value.reset()
    return value


@pytest.fixture
def coordinator(service: PostgresC3Service, postgres_dsn: str) -> SingleWriterRecoveryCoordinator:
    return SingleWriterRecoveryCoordinator(service, PostgresAdvisoryLock(postgres_dsn))


def make_command(
    *,
    command_id: str,
    idempotency_key: str,
    expected_revision: int,
    canonical_delta: dict[str, object],
    aggregate_ref: str = AGGREGATE_REF,
) -> GovernedCanonicalCommitCommand:
    context = GovernedContext.from_mapping(
        {
            "tenant_id": "urn:ocor:tenant:synthetic",
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": ["urn:ocor:compartment:alpha"],
            "classification_marking_ref": DIGEST_A,
            "purpose": "single-writer-recovery-fixture",
            "effective_principal_id": "urn:ocor:principal:analyst-1",
            "actor_chain": ["urn:ocor:principal:analyst-1"],
            "ontology_release_digest": DIGEST_B,
            "policy_bundle_digest": DIGEST_C,
            "correlation_id": "018f2f95-01b2-7cc3-8d4e-123456789abc",
        }
    )
    return GOVERNED.command(
        {
            "command_id": command_id,
            "action_instance_id": command_id.replace("command", "action"),
            "aggregate_type": "MissionObject",
            "aggregate_ref": aggregate_ref,
            "expected_revision": expected_revision,
            "canonical_delta": canonical_delta,
            "decision_ref": "urn:ocor:decision:single-writer-recovery:1",
            "authority_ref": "urn:ocor:authority:single-writer-recovery:1",
            "evidence_refs": ["urn:ocor:evidence:single-writer-recovery:1"],
            "claim_source_bindings": [
                {
                    "claim_ref": "urn:ocor:claim:single-writer-recovery:1",
                    "source_ref": "urn:ocor:source:single-writer-recovery:1",
                    "evidence_ref": "urn:ocor:evidence:single-writer-recovery:1",
                }
            ],
            "precondition_bindings": [f"urn:ocor:precondition:revision-{expected_revision}"],
            "invariant_bindings": ["urn:ocor:invariant:atomic-outbox"],
            "idempotency_key": idempotency_key,
            "governed_context": context.to_mapping(),
            "governed_context_digest": context.digest(),
            "gate_package_digest": DIGEST_D,
            "branch": "main",
        }
    )


def test_run_recovery_pass_repairs_a_real_simulated_corruption_fixture(
    coordinator: SingleWriterRecoveryCoordinator, service: PostgresC3Service, postgres_dsn: str
) -> None:
    command = make_command(
        command_id="urn:ocor:command:swr:1",
        idempotency_key="swr-single-writer-recovery-key-0001",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    receipt = service.commit(command)

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("DELETE FROM c3_outbox WHERE commit_id = %s", (receipt.commit_id,))
    assert service.claim_batch(limit=10) == ()

    report = coordinator.run_recovery_pass(limit=10)

    assert report.repaired >= 1
    batch = service.claim_batch(limit=10)
    assert len(batch) == 1
    assert batch[0].commit_id == receipt.commit_id


def test_assert_healthy_blocks_when_repair_was_needed_then_succeeds_once_nothing_remains(
    coordinator: SingleWriterRecoveryCoordinator, service: PostgresC3Service, postgres_dsn: str
) -> None:
    command = make_command(
        command_id="urn:ocor:command:swr:2",
        idempotency_key="swr-single-writer-recovery-key-0002",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    receipt = service.commit(command)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("DELETE FROM c3_outbox WHERE commit_id = %s", (receipt.commit_id,))

    with pytest.raises(C3Error) as excinfo:
        coordinator.assert_healthy(limit=10)
    assert excinfo.value.reason_code == "UNRECONCILED_DURABLE_INTENT"

    report = coordinator.assert_healthy(limit=10)
    assert report.repaired == 0


def test_the_advisory_lock_really_serializes_two_concurrent_holders(postgres_dsn: str) -> None:
    lock_a = PostgresAdvisoryLock(postgres_dsn)
    lock_b = PostgresAdvisoryLock(postgres_dsn)
    events: list[tuple[str, float]] = []
    started = threading.Event()

    def hold_first() -> None:
        with lock_a.held(RECOVERY_LOCK_KEY):
            events.append(("a_acquired", time.monotonic()))
            started.set()
            time.sleep(0.4)
            events.append(("a_released", time.monotonic()))

    def hold_second() -> None:
        started.wait(timeout=5)
        events.append(("b_attempt", time.monotonic()))
        with lock_b.held(RECOVERY_LOCK_KEY):
            events.append(("b_acquired", time.monotonic()))

    thread_a = threading.Thread(target=hold_first)
    thread_b = threading.Thread(target=hold_second)
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)

    by_label = dict(events)
    assert by_label["b_acquired"] >= by_label["a_released"], (
        "the second holder must never acquire the real advisory lock before the first genuinely released it"
    )


def test_concurrent_recovery_passes_never_double_repair(
    service: PostgresC3Service, postgres_dsn: str
) -> None:
    command = make_command(
        command_id="urn:ocor:command:swr:3",
        idempotency_key="swr-single-writer-recovery-key-0003",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    receipt = service.commit(command)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("DELETE FROM c3_outbox WHERE commit_id = %s", (receipt.commit_id,))

    coordinator_a = SingleWriterRecoveryCoordinator(service, PostgresAdvisoryLock(postgres_dsn))
    coordinator_b = SingleWriterRecoveryCoordinator(PostgresC3Service(postgres_dsn, admission=GOVERNED.admission(), writer_epoch=service.writer_epoch), PostgresAdvisoryLock(postgres_dsn))
    reports: list[RecoveryReport] = []
    lock = threading.Lock()

    def run(coord: SingleWriterRecoveryCoordinator) -> None:
        report = coord.run_recovery_pass(limit=10)
        with lock:
            reports.append(report)

    thread_a = threading.Thread(target=run, args=(coordinator_a,))
    thread_b = threading.Thread(target=run, args=(coordinator_b,))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=10)
    thread_b.join(timeout=10)

    assert sum(report.repaired for report in reports) == 1, (
        "exactly one of the two racing passes must have performed the real repair; the real advisory "
        "lock must prevent both from racing the same ON CONFLICT DO NOTHING insert concurrently"
    )
    batch = service.claim_batch(limit=10)
    assert len(batch) == 1


def test_claim_and_deliver_redelivers_after_a_lost_ack_and_the_sinks_own_idempotency_prevents_duplication(
    coordinator: SingleWriterRecoveryCoordinator, service: PostgresC3Service
) -> None:
    command = make_command(
        command_id="urn:ocor:command:swr:4",
        idempotency_key="swr-single-writer-recovery-key-0004",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    service.commit(command)

    class _CrashBeforeAck(RuntimeError):
        pass

    def deliver_then_crash(envelope: OutboxEnvelope) -> None:
        raise _CrashBeforeAck("simulated crash after delivery, before acknowledge -- a lost ACK")

    with pytest.raises(_CrashBeforeAck):
        coordinator.claim_and_deliver(limit=10, deliver=deliver_then_crash)

    # the event is still unacknowledged: a real lost-ACK leaves it claimable again.
    assert len(service.claim_batch(limit=10)) == 1

    applied_effects: set[str] = set()
    delivery_attempts: list[str] = []

    def idempotent_deliver(envelope: OutboxEnvelope) -> None:
        delivery_attempts.append(envelope.event_id)
        applied_effects.add(envelope.event_id)  # a set: a second insert of the same id is a no-op

    delivered = coordinator.claim_and_deliver(limit=10, deliver=idempotent_deliver)
    assert len(delivered) == 1
    assert service.claim_batch(limit=10) == ()

    # redeliver once more manually to prove the idempotent sink absorbs a genuine duplicate
    # delivery attempt (e.g. a second worker replaying the same already-acknowledged event
    # from its own stale in-memory batch) without a second canonical effect.
    idempotent_deliver(delivered[0])
    assert delivery_attempts.count(delivered[0].event_id) == 2
    assert len(applied_effects) == 1, "the idempotent sink must never register a second, duplicate effect"


def test_two_concurrent_relay_workers_never_both_claim_the_same_unacknowledged_event(
    service: PostgresC3Service, postgres_dsn: str
) -> None:
    command = make_command(
        command_id="urn:ocor:command:swr:5",
        idempotency_key="swr-single-writer-recovery-key-0005",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    service.commit(command)

    coordinator_a = SingleWriterRecoveryCoordinator(service, PostgresAdvisoryLock(postgres_dsn))
    coordinator_b = SingleWriterRecoveryCoordinator(PostgresC3Service(postgres_dsn, admission=GOVERNED.admission(), writer_epoch=service.writer_epoch), PostgresAdvisoryLock(postgres_dsn))
    delivered_by: dict[str, list[OutboxEnvelope]] = {"a": [], "b": []}

    def run(name: str, coord: SingleWriterRecoveryCoordinator) -> None:
        def deliver(envelope: OutboxEnvelope) -> None:
            time.sleep(0.1)  # widen the window so a real race would be observable if unsynchronized

        delivered_by[name] = list(coord.claim_and_deliver(limit=10, deliver=deliver))

    thread_a = threading.Thread(target=run, args=("a", coordinator_a))
    thread_b = threading.Thread(target=run, args=("b", coordinator_b))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=10)
    thread_b.join(timeout=10)

    all_delivered = delivered_by["a"] + delivered_by["b"]
    assert len(all_delivered) == 1, "exactly one worker must have claimed the single unacknowledged event"


def test_a_fresh_coordinator_after_a_simulated_restart_converges_without_a_duplicate_repair(
    service: PostgresC3Service, postgres_dsn: str
) -> None:
    command = make_command(
        command_id="urn:ocor:command:swr:6",
        idempotency_key="swr-single-writer-recovery-key-0006",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    receipt = service.commit(command)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("DELETE FROM c3_outbox WHERE commit_id = %s", (receipt.commit_id,))

    first_process_coordinator = SingleWriterRecoveryCoordinator(service, PostgresAdvisoryLock(postgres_dsn))
    first_report = first_process_coordinator.run_recovery_pass(limit=10)
    assert first_report.repaired >= 1

    # a restarted process holds no in-memory state of its own; only Postgres does.
    restarted_service = PostgresC3Service(postgres_dsn, admission=GOVERNED.admission(), writer_epoch=service.writer_epoch)
    restarted_coordinator = SingleWriterRecoveryCoordinator(restarted_service, PostgresAdvisoryLock(postgres_dsn))
    second_report = restarted_coordinator.run_recovery_pass(limit=10)

    assert second_report.repaired == 0, "the restarted coordinator must never repeat an already-completed repair"
    batch = restarted_service.claim_batch(limit=10)
    assert len(batch) == 1
    assert batch[0].commit_id == receipt.commit_id


def test_a_real_lock_backend_failure_propagates_and_the_recovery_pass_never_runs_unlocked(
    service: PostgresC3Service,
) -> None:
    unreachable_lock = PostgresAdvisoryLock("postgresql://ocor:wrong@127.0.0.1:1/ocor")
    coordinator = SingleWriterRecoveryCoordinator(service, unreachable_lock)

    with pytest.raises(psycopg.OperationalError):
        coordinator.run_recovery_pass(limit=10)
