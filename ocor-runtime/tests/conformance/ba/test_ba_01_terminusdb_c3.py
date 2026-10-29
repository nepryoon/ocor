"""OCOR-DEV-0060, BA-01: TerminusDB ``VersionedAssertedState`` behind the sealed C3 ports.

Selected real component (PO normative decision OCOR-DEV-0060-BA-SELECTED-COMPONENTS
(2026-10-26), option 2): TerminusDB 12.0.7 (``terminusdb/terminusdb-server``, pinned by
digest in ``infra/services.lock.json``), reached only through the sealed runtime adapter
``ocor_runtime.c3.terminusdb_service.TerminusDBC3Service`` of OCOR-DEV-REM-0041.
PostgreSQL stays the atomicity verification adapter (LLD v1.1 §5.2) and is never an
implicit fallback (DEC-201): no case of this module touches it.

ADD v1.3 Part I §2.6 row ``BA-01`` and LLD v1.1 §7.1 row ``BA-01``: one local commit
carries state, revision, commit, idempotency record and outbox under the five crash
windows of §2.3, the stale writer is fenced, and a scenario fork never produces a
``DeliveryAttempt``. Every case runs on the live server in its own disposable database,
deleted at teardown; an unavailable server fails, it never skips. The crash windows
that end a process use a real separate OS process killed with ``os._exit``.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from ocor_runtime.c2.ports import ConsistencyMode, ConsistencyRequirement, NamedQueryRequest
from ocor_runtime.c3.ports import C3Error, GovernedCanonicalCommitCommand, OutboxEnvelope
from ocor_runtime.c3.service import PostgresC3Service
from ocor_runtime.c3.terminusdb_service import TerminusDBC3Service
from ocor_runtime.c4.rebuild import ProjectionDriftDetector
from ocor_runtime.c4.typedb_adapter import TypeDBAdapterError, TypeDBProjectionAdapter
from ocor_runtime.kernel.governed_context import GovernedContext

BA_CASE = {
    "ba_id": "BA-01",
    "component": "TerminusDB",
    "component_version": "12.0.7-noroot",
    "backend_services": ["terminusdb", "typedb"],
    "add_v1_3_part_i_2_6": {
        "required_property": (
            "Commit locale atomico che includa in un'unica unità `aggregate_delta`, "
            "`aggregate_revision+1`, `canonical_commit_id` e `OutboxEntry[]`, con concorrenza "
            "ottimistica su `aggregate_revision` e fencing del writer"
        ),
        "conformance_test": (
            "Crash-window test sulle cinque finestre di §2.3; test di concorrenza su writer stale; "
            "verifica che un fork non produca `DeliveryAttempt`"
        ),
    },
    "lld_v1_1_7_1_oracle": "C3 selezionato: state+revision+commit+idempotency+outbox atomici sotto crash windows",
    "requirement_ids": ["FR-062", "FR-032", "FR-065"],
    "requirement_binding": {
        "FR-062": (
            "expected revision and idempotency key are validated before every canonical commit: a "
            "stale revision, a reused key with different content and a fenced writer write nothing"
        ),
        "FR-032": (
            "the Transactional Outbox and the Delivery Attempt are persisted records: the outbox entry "
            "is in the same commit as the state, and exactly one Delivery Attempt follows a relay"
        ),
        "FR-065": (
            "a projection checksum mismatch is detected and quarantined, and replay from the canonical "
            "commit repairs it without a reverse write into C3"
        ),
    },
    "positive_tests": [
        "test_ba_01_positive_one_terminusdb_commit_carries_state_revision_commit_idempotency_and_outbox",
    ],
    "negative_tests": [
        "test_ba_01_negative_revision_conflict_key_reuse_and_stale_writer_write_nothing",
        "test_ba_01_negative_a_scenario_fork_never_produces_a_delivery_attempt",
    ],
    "fault_tests": [
        "test_ba_01_fault_crash_window_1_before_the_local_commit_leaves_nothing",
        "test_ba_01_fault_crash_window_2_after_the_commit_republishes_the_same_event",
        "test_ba_01_fault_crash_window_3_redelivery_after_publish_is_deduplicated",
        "test_ba_01_fault_crash_window_4_projection_crash_keeps_the_commit_and_replay_projects",
        "test_ba_01_fault_crash_window_5_checksum_divergence_is_quarantined_without_reverse_write",
    ],
}

RUNTIME_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = RUNTIME_ROOT.parent
URL = os.environ.get("OCOR_LIVE_TERMINUSDB_URL", "http://127.0.0.1:6363")
TENANT = "urn:ocor:tenant:synthetic"
AGGREGATE_TYPE = "MissionObject"
AGGREGATE_REF = "urn:ocor:mission-object:ba01:1"
DIGEST_A = "urn:sha256:" + "a" * 64
DIGEST_B = "urn:sha256:" + "b" * 64
DIGEST_C = "urn:sha256:" + "c" * 64
DIGEST_D = "urn:sha256:" + "d" * 64
CRASH_EXIT_CODE = 86


def _env_file() -> Path:
    candidates = []
    if os.environ.get("OCOR_BOOTSTRAP_ENV"):
        candidates.append(Path(os.environ["OCOR_BOOTSTRAP_ENV"]))
    candidates += [
        Path.home() / ".ocor-bootstrap-secrets" / "ocor-bootstrap.env",
        REPOSITORY_ROOT / ".ocor" / "bootstrap.env",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    pytest.fail("ocor-bootstrap env file not found; real TerminusDB credentials are mandatory qualifying evidence")


def _password() -> str:
    if os.environ.get("OCOR_LIVE_TERMINUSDB_PASSWORD"):
        return os.environ["OCOR_LIVE_TERMINUSDB_PASSWORD"]
    for line in _env_file().read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "OCOR_LOCAL_TERMINUSDB_PASSWORD" and value:
            return value.strip()
    pytest.fail("OCOR_LOCAL_TERMINUSDB_PASSWORD is absent from the ocor-bootstrap env file")


def _raw(method: str, path: str, password: str, body: object | None = None) -> tuple[int, Any, str]:
    """Direct HTTP to the live server, used only to observe or fork the store out of band,
    never to perform the operation under test."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(URL + path, data=data, method=method)
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            text = response.read().decode()
            version = response.headers.get("TerminusDB-Data-Version", "")
    except urllib.error.HTTPError as error:
        status, text, version = error.code, error.read().decode(), ""
    try:
        parsed: Any = json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        parsed = [json.loads(line) for line in text.splitlines() if line.strip()]
    return status, parsed, version


def _documents(password: str, database: str, doc_type: str, *, branch: str = "main") -> list[dict[str, Any]]:
    status, body, _ = _raw(
        "GET", f"/api/document/admin/{database}/local/branch/{branch}?type={doc_type}&as_list=true", password
    )
    assert status == 200, body
    return list(body or [])


def _data_version(password: str, database: str) -> str:
    status, body, version = _raw(
        "GET", f"/api/document/admin/{database}/local/branch/main?type=C3Aggregate&as_list=true", password
    )
    assert status == 200 and version, body
    return version


def _log_length(password: str, database: str) -> int:
    status, body, _ = _raw("GET", f"/api/log/admin/{database}?count=1000", password)
    assert status == 200, body
    return len(body)


def _databases(password: str) -> set[str]:
    status, body, _ = _raw("GET", "/api/db", password)
    assert status == 200, body
    return {entry["path"].split("/")[-1] for entry in body}


@pytest.fixture(scope="module")
def password() -> str:
    value = _password()
    try:
        _databases(value)
    except (urllib.error.URLError, OSError) as error:
        pytest.fail(f"a real, live TerminusDB server is mandatory qualifying evidence: {error}")
    return value


@pytest.fixture
def database(password: str) -> Iterator[str]:
    name = f"ocor_c3_ba01_{uuid.uuid4().hex[:12]}"
    try:
        yield name
    finally:
        _raw("DELETE", f"/api/db/admin/{name}", password)
        assert name not in _databases(password), "disposable BA-01 database left behind"


@pytest.fixture
def service(password: str, database: str) -> TerminusDBC3Service:
    value = TerminusDBC3Service(url=URL, password=password, database=database)
    value.initialize()
    return value


@pytest.fixture
def projection() -> TypeDBProjectionAdapter:
    value = TypeDBProjectionAdapter()
    try:
        value.initialize()
    except (TypeDBAdapterError, OSError) as error:
        pytest.fail(f"a real, live TypeDB instance is mandatory qualifying evidence: {error}")
    value.reset()
    return value


def _context() -> GovernedContext:
    return GovernedContext.from_mapping(
        {
            "tenant_id": TENANT,
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": ["urn:ocor:compartment:alpha"],
            "classification_marking_ref": DIGEST_A,
            "purpose": "ocor-dev-0060-ba-01",
            "effective_principal_id": "urn:ocor:principal:analyst-1",
            "actor_chain": ["urn:ocor:principal:analyst-1"],
            "ontology_release_digest": DIGEST_B,
            "policy_bundle_digest": DIGEST_C,
            "correlation_id": "018f2f95-01b2-7cc3-8d4e-0060ba010001",
        }
    )


def _command(
    *,
    command_id: str = "urn:ocor:command:ba01:1",
    idempotency_key: str = "ba01-terminusdb-key-0001",
    expected_revision: int = 0,
    canonical_delta: dict[str, object] | None = None,
) -> GovernedCanonicalCommitCommand:
    context = _context()
    return GovernedCanonicalCommitCommand.from_mapping(
        {
            "command_id": command_id,
            "action_instance_id": command_id.replace("command", "action"),
            "aggregate_type": AGGREGATE_TYPE,
            "aggregate_ref": AGGREGATE_REF,
            "expected_revision": expected_revision,
            "canonical_delta": canonical_delta if canonical_delta is not None else {"status": "ASSESSED"},
            "decision_ref": "urn:ocor:decision:ba01:1",
            "authority_ref": "urn:ocor:authority:ba01:1",
            "evidence_refs": ["urn:ocor:evidence:ba01:1"],
            "claim_source_bindings": [
                {
                    "claim_ref": "urn:ocor:claim:ba01:1",
                    "source_ref": "urn:ocor:source:ba01:1",
                    "evidence_ref": "urn:ocor:evidence:ba01:1",
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


def _commit_in_killed_process(
    password: str, database: str, stage: str, command: GovernedCanonicalCommitCommand
) -> int:
    """Runs one commit in a separate OS process that dies with ``os._exit`` at ``stage``,
    so no in-process cleanup can mask a partial write."""
    code = (
        "import json, sys; "
        "from ocor_runtime.c3.terminusdb_service import TerminusDBC3Service, TerminusDBCrashStage; "
        "from ocor_runtime.c3.ports import GovernedCanonicalCommitCommand; "
        "command = GovernedCanonicalCommitCommand.from_mapping(json.loads(sys.argv[4])); "
        "service = TerminusDBC3Service(url=sys.argv[1], password=sys.argv[2], database=sys.argv[3]); "
        "service.initialize(); "
        "service.commit(command, _crash_after=TerminusDBCrashStage(sys.argv[5]))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, URL, password, database, json.dumps(command.to_mapping()), stage],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return completed.returncode


def _projection_request(required_commit: str) -> NamedQueryRequest:
    context = _context()
    return NamedQueryRequest(
        request_id="018f2f95-01b2-7cc3-8d4e-0060ba010002",
        contract_id="urn:ocor:contract:named-query:ba01-fixture",
        contract_version="1.0.0",
        contract_digest=DIGEST_A,
        parameters={"fact_id": AGGREGATE_REF},
        governed_context=context,
        governed_context_digest=context.digest(),
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit=required_commit),
    )


def test_ba_01_positive_one_terminusdb_commit_carries_state_revision_commit_idempotency_and_outbox(
    service: TerminusDBC3Service, password: str, database: str
) -> None:
    before = _log_length(password, database)
    receipt = service.commit(_command())
    assert _log_length(password, database) == before + 1  # one TerminusDB commit for the whole unit

    assert receipt.replayed is False
    assert (receipt.from_revision, receipt.to_revision) == (0, 1)
    (aggregate,) = _documents(password, database, "C3Aggregate")
    assert aggregate["revision"] == 1
    assert [doc["commit_id"] for doc in _documents(password, database, "C3Commit")] == [receipt.commit_id]
    assert len(_documents(password, database, "C3Idempotency")) == 1
    (entry,) = _documents(password, database, "C3OutboxEntry")
    assert entry["event_id"] == receipt.outbox_event_id
    assert entry["commit_id"] == receipt.commit_id and entry["branch"] == "main"

    snapshot = service.read(TENANT, AGGREGATE_TYPE, AGGREGATE_REF)
    assert snapshot is not None
    assert snapshot.revision == 1 and dict(snapshot.state) == {"status": "ASSESSED"}
    assert snapshot.state_digest == receipt.state_digest and snapshot.commit_id == receipt.commit_id

    replay = service.commit(_command())  # same key and content: the stored receipt, no new commit
    assert replay.replayed is True
    for field in ("commit_id", "state_digest", "outbox_event_id", "outbox_payload_digest", "committed_at"):
        assert getattr(replay, field) == getattr(receipt, field), field
    assert _log_length(password, database) == before + 1

    second = service.commit(
        _command(
            command_id="urn:ocor:command:ba01:2",
            idempotency_key="ba01-terminusdb-key-0002",
            expected_revision=1,
            canonical_delta={"priority": 2},
        )
    )
    assert (second.from_revision, second.to_revision) == (1, 2)
    assert _log_length(password, database) == before + 2
    assert len(_documents(password, database, "C3OutboxEntry")) == 2
    current = service.read(TENANT, AGGREGATE_TYPE, AGGREGATE_REF)
    assert current is not None and dict(current.state) == {"status": "ASSESSED", "priority": 2}


def test_ba_01_negative_revision_conflict_key_reuse_and_stale_writer_write_nothing(
    service: TerminusDBC3Service, password: str, database: str
) -> None:
    accepted = service.commit(_command())  # positive control: the writer and the database are healthy
    assert accepted.to_revision == 1
    version = _data_version(password, database)

    with pytest.raises(C3Error) as conflict:
        service.commit(_command(command_id="urn:ocor:command:ba01:3", idempotency_key="ba01-terminusdb-key-0003"))
    assert conflict.value.reason_code == "REVISION_CONFLICT"
    with pytest.raises(C3Error) as reuse:
        service.commit(_command(command_id="urn:ocor:command:ba01:4", canonical_delta={"status": "REJECTED"}))
    assert reuse.value.reason_code == "IDEMPOTENCY_CONFLICT"
    assert _data_version(password, database) == version

    successor = TerminusDBC3Service(url=URL, password=password, database=database)
    successor.initialize()
    assert successor.writer_epoch is not None and service.writer_epoch is not None
    assert successor.writer_epoch == service.writer_epoch + 1
    version = _data_version(password, database)
    stale = _command(
        command_id="urn:ocor:command:ba01:5",
        idempotency_key="ba01-terminusdb-key-0005",
        expected_revision=1,
        canonical_delta={"status": "STALE"},
    )
    with pytest.raises(C3Error) as fenced:
        service.commit(stale)
    assert fenced.value.reason_code == "SINGLE_WRITER_VIOLATION"
    with pytest.raises(C3Error) as fenced_relay:
        service.reconcile(limit=10)
    assert fenced_relay.value.reason_code == "SINGLE_WRITER_VIOLATION"
    assert _data_version(password, database) == version

    current = successor.commit(
        _command(
            command_id="urn:ocor:command:ba01:6",
            idempotency_key="ba01-terminusdb-key-0006",
            expected_revision=1,
            canonical_delta={"status": "CURRENT"},
        )
    )
    assert current.to_revision == 2
    snapshot = successor.read(TENANT, AGGREGATE_TYPE, AGGREGATE_REF)
    assert snapshot is not None and dict(snapshot.state)["status"] == "CURRENT"


def test_ba_01_negative_a_scenario_fork_never_produces_a_delivery_attempt(
    service: TerminusDBC3Service, password: str, database: str
) -> None:
    receipt = service.commit(_command())
    status, body, _ = _raw(
        "POST",
        f"/api/branch/admin/{database}/local/branch/scenario-ba01",
        password,
        {"origin": f"admin/{database}/local/branch/main"},
    )
    assert status == 200, body
    forked = _documents(password, database, "C3OutboxEntry", branch="scenario-ba01")
    assert [doc["event_id"] for doc in forked] == [receipt.outbox_event_id]
    scenario_entry = dict(forked[0])
    scenario_entry.pop("@id")
    scenario_entry.update(
        {"key": "f" * 64, "event_id": "urn:ocor:event:ba01-scenario-only", "commit_id": "urn:ocor:commit:ba01-scenario"}
    )
    status, body, _ = _raw(
        "POST",
        f"/api/document/admin/{database}/local/branch/scenario-ba01?author=c7-overlay&message=scenario",
        password,
        [scenario_entry],
    )
    assert status == 200, body

    claimed = service.claim_batch(limit=100)
    assert [envelope.event_id for envelope in claimed] == [receipt.outbox_event_id]  # positive control: main relays
    for envelope in claimed:
        service.acknowledge(envelope.event_id, acknowledged_at=datetime.now(UTC))
    assert service.reconcile(limit=100) == 0
    assert service.claim_batch(limit=100) == ()
    assert [doc["event_id"] for doc in _documents(password, database, "C3DeliveryAttempt")] == [
        receipt.outbox_event_id
    ]
    assert _documents(password, database, "C3DeliveryAttempt", branch="scenario-ba01") == []
    assert {doc["event_id"] for doc in _documents(password, database, "C3OutboxEntry")} == {receipt.outbox_event_id}


def test_ba_01_fault_crash_window_1_before_the_local_commit_leaves_nothing(password: str, database: str) -> None:
    assert _commit_in_killed_process(password, database, "BEFORE_LOCAL_COMMIT", _command()) == CRASH_EXIT_CODE
    assert _documents(password, database, "C3Aggregate") == []
    assert _documents(password, database, "C3Commit") == []
    assert _documents(password, database, "C3Idempotency") == []
    assert _documents(password, database, "C3OutboxEntry") == []

    service = TerminusDBC3Service(url=URL, password=password, database=database)
    service.initialize()
    receipt = service.commit(_command())  # the retry commits exactly once
    assert receipt.replayed is False and receipt.to_revision == 1
    assert len(_documents(password, database, "C3OutboxEntry")) == 1


def test_ba_01_fault_crash_window_2_after_the_commit_republishes_the_same_event(
    password: str, database: str
) -> None:
    assert _commit_in_killed_process(password, database, "AFTER_LOCAL_COMMIT", _command()) == CRASH_EXIT_CODE
    service = TerminusDBC3Service(url=URL, password=password, database=database)
    service.initialize()
    assert service.current_revision(TENANT, AGGREGATE_TYPE, AGGREGATE_REF) == 1
    (claimed,) = service.claim_batch(limit=10)
    replay = service.commit(_command())
    assert replay.replayed is True
    assert isinstance(claimed, OutboxEnvelope) and claimed.branch == "main"
    assert claimed.event_id == replay.outbox_event_id
    assert claimed.payload_digest == replay.outbox_payload_digest
    assert len(_documents(password, database, "C3OutboxEntry")) == 1


def test_ba_01_fault_crash_window_3_redelivery_after_publish_is_deduplicated(
    service: TerminusDBC3Service, password: str, database: str
) -> None:
    receipt = service.commit(_command())
    applied: dict[tuple[str, str], int] = {}

    def consume(envelope: OutboxEnvelope) -> None:
        key = (envelope.event_id, "projection:ba01")
        applied[key] = applied.get(key, 0) + 1

    first = service.claim_batch(limit=10)
    for envelope in first:
        consume(envelope)  # published, then the relay dies before the delivery receipt
    second = service.claim_batch(limit=10)
    assert [e.event_id for e in second] == [e.event_id for e in first] == [receipt.outbox_event_id]
    for envelope in second:
        consume(envelope)
        service.acknowledge(envelope.event_id, acknowledged_at=datetime.now(UTC))
    assert applied == {(receipt.outbox_event_id, "projection:ba01"): 2}
    assert len(set(applied)) == 1  # the consumer deduplicates on (event_id, projection_id)
    assert service.claim_batch(limit=10) == ()
    attempts = _documents(password, database, "C3DeliveryAttempt")
    assert [doc["event_id"] for doc in attempts] == [receipt.outbox_event_id]


def test_ba_01_fault_crash_window_4_projection_crash_keeps_the_commit_and_replay_projects(
    service: TerminusDBC3Service, password: str, database: str, projection: TypeDBProjectionAdapter
) -> None:
    receipt = service.commit(_command())
    version = _data_version(password, database)

    def crashing_projector(envelope: OutboxEnvelope) -> None:
        raise RuntimeError(f"projector crashed before facts + watermark of {envelope.event_id}")

    with pytest.raises(RuntimeError):
        for envelope in service.claim_batch(limit=10):
            crashing_projector(envelope)
    assert projection.current_watermark() is None  # the projection is stale, never half-written
    assert _data_version(password, database) == version  # the canonical commit is untouched
    snapshot = service.read(TENANT, AGGREGATE_TYPE, AGGREGATE_REF)
    assert snapshot is not None and snapshot.commit_id == receipt.commit_id

    for envelope in service.claim_batch(limit=10):  # replay from the outbox
        current = service.read(TENANT, AGGREGATE_TYPE, envelope.aggregate_ref)
        assert current is not None
        projection.apply_commit(fact_id=envelope.aggregate_ref, commit_id=envelope.commit_id, payload=current.state_digest)
        service.acknowledge(envelope.event_id, acknowledged_at=datetime.now(UTC))
    assert projection.current_watermark() == receipt.commit_id
    assert service.claim_batch(limit=10) == ()


def test_ba_01_fault_crash_window_5_checksum_divergence_is_quarantined_without_reverse_write(
    service: TerminusDBC3Service, password: str, database: str, projection: TypeDBProjectionAdapter
) -> None:
    receipt = service.commit(_command())
    detector = ProjectionDriftDetector(cast(PostgresC3Service, service), projection)
    clean = detector.rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=AGGREGATE_REF)
    assert clean.drift_detected is False and clean.canonical_commit == receipt.commit_id
    version = _data_version(password, database)

    projection.apply_commit(fact_id=AGGREGATE_REF, commit_id=receipt.commit_id, payload="tampered-digest")
    drifted = detector.rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=AGGREGATE_REF)
    assert drifted.drift_detected is True and drifted.quarantined is True
    assert _data_version(password, database) == version  # never a reverse write into C3

    canonical = service.read(TENANT, AGGREGATE_TYPE, AGGREGATE_REF)
    assert canonical is not None
    projection.apply_commit(fact_id=AGGREGATE_REF, commit_id=canonical.commit_id, payload=canonical.state_digest)
    repaired = detector.rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=AGGREGATE_REF)
    assert repaired.drift_detected is False and not detector.is_quarantined(AGGREGATE_REF)
    served = detector.read_if_healthy(AGGREGATE_REF, _projection_request(receipt.commit_id))
    assert served.served.canonical_commit == receipt.commit_id
