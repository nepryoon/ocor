"""OCOR-DEV-0029: Build retained C3 canonical commit slice.

Proves that the retained PostgresC3Service commits state, revision,
evidence, idempotency and outbox atomically against real PostgreSQL, and
recovers from crash fixtures -- both a real process crash mid-commit
(zero partial visibility, successful retry afterward) and a real
simulated corruption (a derived row deleted after the fact, repaired by
reconcile()). Every test drives the real ocor-bootstrap postgresql
service; no mocks. Reuses the sealed C3 ports (OCOR-DEV-0013,
ocor_runtime.c3.ports) unmodified.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_ocor_dev_rem_0050 as governed_path
from ocor_runtime.c3.ports import (
    C3Error,
    CanonicalReadPort,
    GovernedCanonicalCommitCommand,
    GovernedCommitPort,
    OutboxRelayPort,
    RecoveryPort,
    RevisionPort,
)
from ocor_runtime.c3.service import CrashStage, PostgresC3Service
from ocor_runtime.kernel.governed_context import GovernedContext

DIGEST_A = "urn:sha256:" + "a" * 64
DIGEST_B = "urn:sha256:" + "b" * 64
DIGEST_C = "urn:sha256:" + "c" * 64
DIGEST_D = "urn:sha256:" + "d" * 64
AGGREGATE_REF = "urn:ocor:mission-object:retained-c3:1"
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
            "purpose": "retained-c3-slice",
            "effective_principal_id": "spiffe://ocor.test/workload/c6",
            "actor_chain": ["urn:ocor:actor:synthetic", "urn:ocor:actor:c6"],
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
            "decision_ref": "urn:ocor:decision:retained-c3:1",
            "authority_ref": "urn:ocor:authority:retained-c3:1",
            "evidence_refs": ["urn:ocor:evidence:retained-c3:1"],
            "claim_source_bindings": [
                {
                    "claim_ref": "urn:ocor:claim:retained-c3:1",
                    "source_ref": "urn:ocor:source:retained-c3:1",
                    "evidence_ref": "urn:ocor:evidence:retained-c3:1",
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


def test_service_satisfies_every_sealed_c3_port(service: PostgresC3Service):
    assert isinstance(service, GovernedCommitPort)
    assert isinstance(service, CanonicalReadPort)
    assert isinstance(service, RevisionPort)
    assert isinstance(service, RecoveryPort)
    assert isinstance(service, OutboxRelayPort)


def test_commit_persists_state_revision_and_outbox_atomically(service: PostgresC3Service):
    command = make_command(
        command_id="urn:ocor:command:retained-c3:1",
        idempotency_key="retained-c3-key-0001",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    receipt = service.commit(command)

    assert receipt.from_revision == 0
    assert receipt.to_revision == 1
    assert receipt.replayed is False

    snapshot = service.read("urn:ocor:tenant:synthetic", "MissionObject", AGGREGATE_REF)
    assert snapshot is not None
    assert snapshot.revision == 1
    assert snapshot.state["status"] == "ASSESSED"
    assert snapshot.state_digest == receipt.state_digest

    assert service.current_revision("urn:ocor:tenant:synthetic", "MissionObject", AGGREGATE_REF) == 1

    batch = service.claim_batch(limit=10)
    assert len(batch) == 1
    assert batch[0].commit_id == receipt.commit_id
    assert batch[0].payload_digest == receipt.outbox_payload_digest


def test_idempotent_replay_returns_the_identical_receipt(service: PostgresC3Service):
    command = make_command(
        command_id="urn:ocor:command:retained-c3:1",
        idempotency_key="retained-c3-key-0001",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    first = service.commit(command)
    second = service.commit(command)

    assert first.replayed is False
    assert second.replayed is True
    assert second.commit_id == first.commit_id
    assert second.state_digest == first.state_digest
    assert service.current_revision("urn:ocor:tenant:synthetic", "MissionObject", AGGREGATE_REF) == 1


def test_key_reuse_with_different_content_is_rejected(service: PostgresC3Service):
    original = make_command(
        command_id="urn:ocor:command:retained-c3:1",
        idempotency_key="retained-c3-key-0001",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    service.commit(original)
    changed = make_command(
        command_id="urn:ocor:command:retained-c3:2",
        idempotency_key="retained-c3-key-0001",
        expected_revision=0,
        canonical_delta={"status": "REJECTED"},
    )
    with pytest.raises(C3Error) as excinfo:
        service.commit(changed)
    assert excinfo.value.reason_code == "IDEMPOTENCY_CONFLICT"


def test_revision_conflict_is_rejected(service: PostgresC3Service):
    command = make_command(
        command_id="urn:ocor:command:retained-c3:1",
        idempotency_key="retained-c3-key-0001",
        expected_revision=5,
        canonical_delta={"status": "ASSESSED"},
    )
    with pytest.raises(C3Error) as excinfo:
        service.commit(command)
    assert excinfo.value.reason_code == "REVISION_CONFLICT"


def test_two_distinct_commands_racing_the_same_revision_never_both_succeed(service: PostgresC3Service):
    import threading

    command_a = make_command(
        command_id="urn:ocor:command:retained-c3:race-a",
        idempotency_key="retained-c3-race-key-a",
        expected_revision=0,
        canonical_delta={"status": "A"},
    )
    command_b = make_command(
        command_id="urn:ocor:command:retained-c3:race-b",
        idempotency_key="retained-c3-race-key-b",
        expected_revision=0,
        canonical_delta={"status": "B"},
    )
    barrier = threading.Barrier(2)
    outcomes: dict[str, object] = {}

    def attempt(key: str, command: GovernedCanonicalCommitCommand) -> None:
        barrier.wait(timeout=5)
        try:
            outcomes[key] = service.commit(command)
        except C3Error as error:
            outcomes[key] = error

    threads = [
        threading.Thread(target=attempt, args=("a", command_a)),
        threading.Thread(target=attempt, args=("b", command_b)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    successes = [v for v in outcomes.values() if not isinstance(v, C3Error)]
    failures = [v for v in outcomes.values() if isinstance(v, C3Error)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].reason_code == "REVISION_CONFLICT"
    assert successes[0].to_revision == 1


def test_real_process_crash_leaves_zero_partial_state_and_recovers_on_retry(
    service: PostgresC3Service, postgres_dsn: str
):
    command = make_command(
        command_id="urn:ocor:command:retained-c3:crash",
        idempotency_key="retained-c3-crash-key",
        expected_revision=0,
        canonical_delta={"status": "CRASHING"},
    )
    script = (
        "import sys, json; "
        "sys.path.insert(0, sys.argv[3]); "
        "sys.path.insert(0, sys.argv[4]); "
        "from ocor_runtime.c3.service import PostgresC3Service, CrashStage; "
        "from ocor_runtime.c3.ports import GovernedCanonicalCommitCommand; "
        "import test_ocor_dev_rem_0050 as governed_path; "
        "body = json.load(sys.stdin); "
        "command = GovernedCanonicalCommitCommand.from_mapping(body['command']); "
        "admission = governed_path.GovernedC3.from_export(body['governed']).admission(); "
        "PostgresC3Service(sys.argv[1], admission=admission, writer_epoch=int(sys.argv[5]))"
        ".commit(command, _crash_after=CrashStage(sys.argv[2]))"
    )
    src_path = str(Path(__file__).resolve().parents[2] / "src")

    result = subprocess.run(
        [sys.executable, "-c", script, postgres_dsn, CrashStage.AFTER_AGGREGATE_UPSERT.value, src_path,
         str(Path(__file__).resolve().parent), str(service.writer_epoch)],
        input=json.dumps({"command": command.to_mapping(), "governed": GOVERNED.export()}),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 86, result.stderr

    snapshot = service.read("urn:ocor:tenant:synthetic", "MissionObject", AGGREGATE_REF)
    assert snapshot is None, "a crashed commit must leave zero visible state, never a partial write"
    assert service.claim_batch(limit=10) == ()

    receipt = service.commit(command)
    assert receipt.to_revision == 1
    assert receipt.replayed is False


def test_reconcile_repairs_a_real_simulated_corruption_fixture(service: PostgresC3Service, postgres_dsn: str):
    import psycopg

    command = make_command(
        command_id="urn:ocor:command:retained-c3:1",
        idempotency_key="retained-c3-key-0001",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    receipt = service.commit(command)

    # Simulate a genuine corruption fixture directly against the database
    # (the retained service itself never exposes a raw connection, per
    # AFF-002/AFF-006: the psycopg client is confined to its adapter).
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("DELETE FROM c3_outbox WHERE commit_id = %s", (receipt.commit_id,))
    assert service.claim_batch(limit=10) == ()

    repaired = service.reconcile(limit=10)
    assert repaired >= 1

    batch = service.claim_batch(limit=10)
    assert len(batch) == 1
    assert batch[0].commit_id == receipt.commit_id
    assert batch[0].payload_digest == receipt.outbox_payload_digest


def test_claim_and_acknowledge_outbox_batch(service: PostgresC3Service):
    import datetime

    command = make_command(
        command_id="urn:ocor:command:retained-c3:1",
        idempotency_key="retained-c3-key-0001",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    service.commit(command)
    batch = service.claim_batch(limit=10)
    assert len(batch) == 1

    service.acknowledge(batch[0].event_id, acknowledged_at=datetime.datetime.now(datetime.UTC))
    assert service.claim_batch(limit=10) == ()
