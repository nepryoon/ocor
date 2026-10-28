"""OCOR-DEV-REM-0041: TerminusDB runtime adapter of C3 behind the existing ports.

Change set d. of the PO normative decision OCOR-DEV-0060-BA-SELECTED-COMPONENTS
(2026-10-26), option 2. TerminusDB becomes the canonical ``VersionedAssertedState``
store of ADD v1.3 Part I §2.2/§2.4; the sealed C3 ports of OCOR-DEV-0013
(``GovernedCommitPort``, ``CanonicalReadPort``, ``OutboxRelayPort``,
``RevisionPort``, ``RecoveryPort``) are implemented unchanged. PostgreSQL stays the
atomicity verification adapter (LLD v1.1 §5.2) and is never an implicit fallback
(DEC-201).

BA-01 is qualified with the conformance column of ADD v1.3 Part I §2.6: the five
crash windows of §2.3, the stale writer and the fork without ``DeliveryAttempt``
(§2.5 rule 11). The live cases run against the real, pinned TerminusDB server of
the ``ocor-bootstrap`` stack, each in its own disposable database that is deleted
at teardown: an unavailable server fails, it never skips.
"""

from __future__ import annotations

import ast
import base64
import importlib
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from ocor_runtime.c2.ports import ConsistencyMode, ConsistencyRequirement, NamedQueryRequest
from ocor_runtime.c3.ports import (
    C3Error,
    CanonicalReadPort,
    GovernedCanonicalCommitCommand,
    GovernedCommitPort,
    OutboxEnvelope,
    OutboxRelayPort,
    RecoveryPort,
    RevisionPort,
)
from ocor_runtime.c3.service import PostgresC3Service
from ocor_runtime.c4.rebuild import ProjectionDriftDetector
from ocor_runtime.c4.typedb_adapter import TypeDBAdapterError, TypeDBProjectionAdapter
from ocor_runtime.kernel.governed_context import GovernedContext

RUNTIME_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = RUNTIME_ROOT.parent
SERVICE = "ocor_runtime.c3.terminusdb_service"
ADAPTER = "ocor_runtime.c3.adapters.terminusdb"
SERVICE_PATH = RUNTIME_ROOT / "src/ocor_runtime/c3/terminusdb_service.py"
ADAPTER_PATH = RUNTIME_ROOT / "src/ocor_runtime/c3/adapters/terminusdb.py"
URL = os.environ.get("OCOR_LIVE_TERMINUSDB_URL", "http://127.0.0.1:6363")
TENANT = "urn:ocor:tenant:synthetic"
AGGREGATE_TYPE = "MissionObject"
AGGREGATE_REF = "urn:ocor:mission-object:rem0041:1"
DIGEST_A = "urn:sha256:" + "a" * 64
DIGEST_B = "urn:sha256:" + "b" * 64
DIGEST_C = "urn:sha256:" + "c" * 64
DIGEST_D = "urn:sha256:" + "d" * 64
SYNTHETIC_PASSWORD = "rem0041-offline-synthetic"  # never sent: the endpoint is closed


def _service_module() -> ModuleType:
    return importlib.import_module(SERVICE)


def _adapter_module() -> ModuleType:
    return importlib.import_module(ADAPTER)


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
    """Direct HTTP to the live server, used only to observe or tamper with the store
    out of band (never through the adapter under test)."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(URL + path, data=data, method=method)
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, text, version = response.status, response.read().decode(), response.headers.get(
                "TerminusDB-Data-Version", ""
            )
    except urllib.error.HTTPError as error:
        status, text, version = error.code, error.read().decode(), ""
    try:
        parsed: Any = json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        parsed = [json.loads(line) for line in text.splitlines() if line.strip()]
    return status, parsed, version


def _documents(password: str, database: str, doc_type: str, *, branch: str = "main") -> list[dict[str, Any]]:
    status, body, _ = _raw(
        "GET",
        f"/api/document/admin/{database}/local/branch/{branch}?type={doc_type}&as_list=true",
        password,
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
    name = f"ocor_c3_rem0041_{uuid.uuid4().hex[:12]}"
    try:
        yield name
    finally:
        _raw("DELETE", f"/api/db/admin/{name}", password)
        assert name not in _databases(password), "disposable C3 database left behind"


@pytest.fixture
def service(password: str, database: str) -> Any:
    value = _service_module().TerminusDBC3Service(url=URL, password=password, database=database)
    value.initialize()
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
            "tenant_id": TENANT,
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": ["urn:ocor:compartment:alpha"],
            "classification_marking_ref": DIGEST_A,
            "purpose": "rem0041-terminusdb-c3",
            "effective_principal_id": "urn:ocor:principal:analyst-1",
            "actor_chain": ["urn:ocor:principal:analyst-1"],
            "ontology_release_digest": DIGEST_B,
            "policy_bundle_digest": DIGEST_C,
            "correlation_id": "018f2f95-01b2-7cc3-8d4e-1234567890ab",
        }
    )
    return GovernedCanonicalCommitCommand.from_mapping(
        {
            "command_id": command_id,
            "action_instance_id": command_id.replace("command", "action"),
            "aggregate_type": AGGREGATE_TYPE,
            "aggregate_ref": aggregate_ref,
            "expected_revision": expected_revision,
            "canonical_delta": canonical_delta,
            "decision_ref": "urn:ocor:decision:rem0041:1",
            "authority_ref": "urn:ocor:authority:rem0041:1",
            "evidence_refs": ["urn:ocor:evidence:rem0041:1"],
            "claim_source_bindings": [
                {
                    "claim_ref": "urn:ocor:claim:rem0041:1",
                    "source_ref": "urn:ocor:source:rem0041:1",
                    "evidence_ref": "urn:ocor:evidence:rem0041:1",
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


def _first(**overrides: Any) -> GovernedCanonicalCommitCommand:
    values: dict[str, Any] = {
        "command_id": "urn:ocor:command:rem0041:1",
        "idempotency_key": "rem0041-terminusdb-key-0001",
        "expected_revision": 0,
        "canonical_delta": {"status": "ASSESSED"},
    }
    values.update(overrides)
    return make_command(**values)


def _commit_in_subprocess(password: str, database: str, stage: str, command: GovernedCanonicalCommitCommand) -> int:
    """Runs one commit in a real separate OS process that dies with ``os._exit`` at the
    requested stage, so no in-process cleanup can mask a partial write."""
    code = (
        "import json, sys; "
        f"from {SERVICE} import TerminusDBC3Service, TerminusDBCrashStage; "
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
    context = GovernedContext.from_mapping(
        {
            "tenant_id": TENANT,
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": ["urn:ocor:compartment:alpha"],
            "classification_marking_ref": DIGEST_A,
            "purpose": "rem0041-terminusdb-c3",
            "effective_principal_id": "urn:ocor:principal:analyst-1",
            "actor_chain": ["urn:ocor:principal:analyst-1"],
            "ontology_release_digest": DIGEST_B,
            "policy_bundle_digest": DIGEST_C,
            "correlation_id": "018f2f95-01b2-7cc3-8d4e-1234567890ab",
        }
    )
    return NamedQueryRequest(
        request_id="018f2f95-01b2-7cc3-8d4e-1234567890ab",
        contract_id="urn:ocor:contract:named-query:rem0041-fixture",
        contract_version="1.0.0",
        contract_digest=DIGEST_A,
        parameters={"fact_id": AGGREGATE_REF},
        governed_context=context,
        governed_context_digest=context.digest(),
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit=required_commit),
    )


@pytest.fixture
def projection() -> TypeDBProjectionAdapter:
    value = TypeDBProjectionAdapter()
    try:
        value.initialize()
    except (TypeDBAdapterError, OSError) as error:
        pytest.fail(f"a real, live TypeDB instance is mandatory qualifying evidence: {error}")
    value.reset()
    return value


# --- static and offline cases -------------------------------------------------


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(("." * node.level) + (node.module or ""))
    return names


def test_direct_backend_access_is_confined_to_the_adapters_subtree() -> None:
    service_imports = _imports(SERVICE_PATH)
    assert not {name for name in service_imports if name.split(".")[0] in {"urllib", "http", "socket", "requests"}}
    assert any(name.endswith("adapters.terminusdb") for name in service_imports)
    adapter_imports = _imports(ADAPTER_PATH)
    assert "urllib.request" in adapter_imports


def test_postgresql_is_never_an_implicit_fallback_of_the_terminusdb_service() -> None:
    for path in (SERVICE_PATH, ADAPTER_PATH):
        names = _imports(path)
        assert not {name for name in names if "psycopg" in name or "postgres" in name}, path
    with pytest.raises(_adapter_module().TerminusDBUnavailable):
        _service_module().TerminusDBC3Service(
            url="http://127.0.0.1:1", password=SYNTHETIC_PASSWORD, database="ocor_c3_rem0041_unreachable"
        ).initialize()


def test_service_satisfies_every_sealed_c3_port_without_changing_them() -> None:
    value = _service_module().TerminusDBC3Service(
        url="http://127.0.0.1:1", password=SYNTHETIC_PASSWORD, database="ocor_c3_rem0041_ports"
    )
    for port in (GovernedCommitPort, CanonicalReadPort, OutboxRelayPort, RevisionPort, RecoveryPort):
        assert isinstance(value, port), port
    assert "branch" not in _service_module().TerminusDBC3Service.__init__.__code__.co_varnames


def test_configuration_is_fail_closed() -> None:
    module = _service_module()
    for kwargs in (
        {"url": "", "password": SYNTHETIC_PASSWORD, "database": "ocor_c3_x"},
        {"url": URL, "password": "", "database": "ocor_c3_x"},
        {"url": URL, "password": SYNTHETIC_PASSWORD, "database": ""},
        {"url": URL, "password": SYNTHETIC_PASSWORD, "database": "ocor_default"},
        {"url": URL, "password": SYNTHETIC_PASSWORD, "database": "bad/name"},
    ):
        with pytest.raises(ValueError):
            module.TerminusDBC3Service(**kwargs)


def test_an_uninitialized_writer_cannot_commit() -> None:
    value = _service_module().TerminusDBC3Service(
        url="http://127.0.0.1:1", password=SYNTHETIC_PASSWORD, database="ocor_c3_rem0041_noepoch"
    )
    with pytest.raises(C3Error) as excinfo:
        value.commit(_first())
    assert excinfo.value.reason_code == "SINGLE_WRITER_VIOLATION"


# --- live cases on the real TerminusDB server ----------------------------------


def test_commit_persists_state_revision_commit_idempotency_and_outbox_in_one_terminusdb_commit(
    service: Any, password: str, database: str
) -> None:
    before = _log_length(password, database)
    receipt = service.commit(_first())
    assert _log_length(password, database) == before + 1

    assert receipt.replayed is False
    assert (receipt.from_revision, receipt.to_revision) == (0, 1)
    assert len(_documents(password, database, "C3Aggregate")) == 1
    assert [doc["commit_id"] for doc in _documents(password, database, "C3Commit")] == [receipt.commit_id]
    assert len(_documents(password, database, "C3Idempotency")) == 1
    outbox = _documents(password, database, "C3OutboxEntry")
    assert [doc["event_id"] for doc in outbox] == [receipt.outbox_event_id]
    assert outbox[0]["branch"] == "main"

    snapshot = service.read(TENANT, AGGREGATE_TYPE, AGGREGATE_REF)
    assert snapshot is not None
    assert snapshot.revision == 1
    assert dict(snapshot.state) == {"status": "ASSESSED"}
    assert snapshot.state_digest == receipt.state_digest
    assert snapshot.commit_id == receipt.commit_id
    assert service.current_revision(TENANT, AGGREGATE_TYPE, AGGREGATE_REF) == 1
    assert service.read(TENANT, AGGREGATE_TYPE, "urn:ocor:mission-object:absent") is None
    assert service.current_revision(TENANT, AGGREGATE_TYPE, "urn:ocor:mission-object:absent") == 0


def test_successive_commits_merge_the_delta_and_advance_the_revision(service: Any) -> None:
    service.commit(_first())
    second = service.commit(
        _first(
            command_id="urn:ocor:command:rem0041:2",
            idempotency_key="rem0041-terminusdb-key-0002",
            expected_revision=1,
            canonical_delta={"priority": 2},
        )
    )
    assert (second.from_revision, second.to_revision) == (1, 2)
    snapshot = service.read(TENANT, AGGREGATE_TYPE, AGGREGATE_REF)
    assert dict(snapshot.state) == {"status": "ASSESSED", "priority": 2}
    assert snapshot.state_digest == second.state_digest


def test_a_server_rejected_batch_persists_nothing(service: Any, password: str, database: str) -> None:
    module = _service_module()
    version = _data_version(password, database)
    with pytest.raises(_adapter_module().TerminusDBAdapterError) as excinfo:
        service.commit(_first(), _crash_after=module.TerminusDBCrashStage.REJECTED_BATCH)
    assert excinfo.value.reason_code == "BATCH_REJECTED"
    assert _data_version(password, database) == version
    for doc_type in ("C3Aggregate", "C3Commit", "C3Idempotency", "C3OutboxEntry"):
        assert _documents(password, database, doc_type) == [], doc_type
    assert service.commit(_first()).to_revision == 1


def test_idempotent_replay_returns_the_identical_receipt(service: Any) -> None:
    first = service.commit(_first())
    second = service.commit(_first())
    assert first.replayed is False and second.replayed is True
    for field in ("commit_id", "state_digest", "outbox_event_id", "outbox_payload_digest", "committed_at"):
        assert getattr(second, field) == getattr(first, field), field
    assert service.current_revision(TENANT, AGGREGATE_TYPE, AGGREGATE_REF) == 1


def test_key_reuse_with_different_content_is_rejected(service: Any) -> None:
    service.commit(_first())
    with pytest.raises(C3Error) as excinfo:
        service.commit(_first(command_id="urn:ocor:command:rem0041:9", canonical_delta={"status": "REJECTED"}))
    assert excinfo.value.reason_code == "IDEMPOTENCY_CONFLICT"


def test_revision_conflict_is_rejected_without_writing(service: Any, password: str, database: str) -> None:
    service.commit(_first())
    version = _data_version(password, database)
    with pytest.raises(C3Error) as excinfo:
        service.commit(
            _first(command_id="urn:ocor:command:rem0041:3", idempotency_key="rem0041-terminusdb-key-0003")
        )
    assert excinfo.value.reason_code == "REVISION_CONFLICT"
    assert _data_version(password, database) == version


def test_crash_window_1_before_the_local_commit_leaves_nothing_and_the_retry_commits_once(
    password: str, database: str
) -> None:
    assert _commit_in_subprocess(password, database, "BEFORE_LOCAL_COMMIT", _first()) == 86
    assert _documents(password, database, "C3Aggregate") == []
    assert _documents(password, database, "C3OutboxEntry") == []
    service = _service_module().TerminusDBC3Service(url=URL, password=password, database=database)
    service.initialize()
    receipt = service.commit(_first())
    assert receipt.replayed is False and receipt.to_revision == 1
    assert len(_documents(password, database, "C3OutboxEntry")) == 1


def test_crash_window_2_after_commit_before_publish_republishes_the_same_event_id(
    password: str, database: str
) -> None:
    assert _commit_in_subprocess(password, database, "AFTER_LOCAL_COMMIT", _first()) == 86
    service = _service_module().TerminusDBC3Service(url=URL, password=password, database=database)
    service.initialize()
    assert service.current_revision(TENANT, AGGREGATE_TYPE, AGGREGATE_REF) == 1
    claimed = service.claim_batch(limit=10)
    assert len(claimed) == 1
    replay = service.commit(_first())
    assert replay.replayed is True
    assert claimed[0].event_id == replay.outbox_event_id
    assert claimed[0].payload_digest == replay.outbox_payload_digest
    assert isinstance(claimed[0], OutboxEnvelope) and claimed[0].branch == "main"


def test_crash_window_3_after_publish_before_receipt_redelivers_and_the_consumer_deduplicates(
    service: Any, password: str, database: str
) -> None:
    receipt = service.commit(_first())
    applied: dict[tuple[str, str], int] = {}

    def consume(envelope: OutboxEnvelope) -> None:
        key = (envelope.event_id, "projection:rem0041")
        applied[key] = applied.get(key, 0) + 1

    first = service.claim_batch(limit=10)
    for envelope in first:
        consume(envelope)  # published, then the worker dies before the delivery receipt
    second = service.claim_batch(limit=10)
    assert [e.event_id for e in second] == [e.event_id for e in first] == [receipt.outbox_event_id]
    for envelope in second:
        consume(envelope)
        service.acknowledge(envelope.event_id, acknowledged_at=datetime.now(UTC))
    assert applied == {(receipt.outbox_event_id, "projection:rem0041"): 2}
    assert len(set(applied)) == 1  # deduplicated on (event_id, projection_id)
    assert service.claim_batch(limit=10) == ()
    attempts = _documents(password, database, "C3DeliveryAttempt")
    assert [doc["event_id"] for doc in attempts] == [receipt.outbox_event_id]
    outbox = _documents(password, database, "C3OutboxEntry")
    assert set(outbox[0]) >= {"event_id", "payload_digest"} and "acknowledged_at" not in outbox[0]


def test_crash_window_4_during_projection_leaves_the_canonical_commit_valid_and_replay_projects(
    service: Any, password: str, database: str, projection: TypeDBProjectionAdapter
) -> None:
    receipt = service.commit(_first())
    version = _data_version(password, database)

    def crashing_projector(envelope: OutboxEnvelope) -> None:
        raise RuntimeError("projector crashed before facts + watermark")

    with pytest.raises(RuntimeError):
        for envelope in service.claim_batch(limit=10):
            crashing_projector(envelope)
    assert projection.current_watermark() is None  # projection stale
    assert _data_version(password, database) == version  # canonical commit untouched
    assert service.read(TENANT, AGGREGATE_TYPE, AGGREGATE_REF).commit_id == receipt.commit_id

    for envelope in service.claim_batch(limit=10):  # replay
        snapshot = service.read(TENANT, AGGREGATE_TYPE, envelope.aggregate_ref)
        projection.apply_commit(fact_id=envelope.aggregate_ref, commit_id=envelope.commit_id, payload=snapshot.state_digest)
        service.acknowledge(envelope.event_id, acknowledged_at=datetime.now(UTC))
    assert projection.current_watermark() == receipt.commit_id
    assert service.claim_batch(limit=10) == ()


def test_crash_window_5_checksum_divergence_is_quarantined_and_never_reverse_written(
    service: Any, password: str, database: str, projection: TypeDBProjectionAdapter
) -> None:
    receipt = service.commit(_first())
    detector = ProjectionDriftDetector(cast(PostgresC3Service, service), projection)
    clean = detector.rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=AGGREGATE_REF)
    assert clean.drift_detected is False and clean.canonical_commit == receipt.commit_id
    version = _data_version(password, database)

    projection.apply_commit(fact_id=AGGREGATE_REF, commit_id=receipt.commit_id, payload="tampered-digest")
    drifted = detector.rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=AGGREGATE_REF)
    assert drifted.drift_detected is True and drifted.quarantined is True
    assert _data_version(password, database) == version  # never a reverse write into C3

    canonical = service.read(TENANT, AGGREGATE_TYPE, AGGREGATE_REF)
    projection.apply_commit(fact_id=AGGREGATE_REF, commit_id=canonical.commit_id, payload=canonical.state_digest)
    repaired = detector.rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=AGGREGATE_REF)
    assert repaired.drift_detected is False and not detector.is_quarantined(AGGREGATE_REF)
    served = detector.read_if_healthy(AGGREGATE_REF, _projection_request(receipt.commit_id))
    assert served.served.canonical_commit == receipt.commit_id


def test_a_stale_writer_is_fenced_and_writes_nothing(service: Any, password: str, database: str) -> None:
    service.commit(_first())
    successor = _service_module().TerminusDBC3Service(url=URL, password=password, database=database)
    successor.initialize()
    assert successor.writer_epoch == service.writer_epoch + 1
    version = _data_version(password, database)

    stale = _first(
        command_id="urn:ocor:command:rem0041:4",
        idempotency_key="rem0041-terminusdb-key-0004",
        expected_revision=1,
        canonical_delta={"status": "STALE"},
    )
    attempts: tuple[Callable[[], object], ...] = (
        lambda: service.commit(stale),
        lambda: service.acknowledge(service.claim_batch(limit=1)[0].event_id, acknowledged_at=datetime.now(UTC)),
        lambda: service.reconcile(limit=10),
    )
    for attempt in attempts:
        with pytest.raises(C3Error) as excinfo:
            attempt()
        assert excinfo.value.reason_code == "SINGLE_WRITER_VIOLATION"
    assert _data_version(password, database) == version

    accepted = successor.commit(
        _first(command_id="urn:ocor:command:rem0041:5", idempotency_key="rem0041-terminusdb-key-0005", expected_revision=1, canonical_delta={"status": "CURRENT"})
    )
    assert accepted.to_revision == 2
    assert dict(successor.read(TENANT, AGGREGATE_TYPE, AGGREGATE_REF).state)["status"] == "CURRENT"


def _race(count: int, action: Any) -> list[str]:
    """Starts ``count`` threads at one barrier; every outcome, including an unexpected
    exception, is recorded so that a thread failure can never pass silently."""
    barrier = threading.Barrier(count)
    outcomes: list[str] = []
    lock = threading.Lock()

    def run(index: int) -> None:
        barrier.wait()
        try:
            action(index)
            result = "OK"
        except C3Error as error:
            result = error.reason_code
        except BaseException as error:  # noqa: BLE001 - recorded and asserted by the caller
            result = f"UNEXPECTED {type(error).__name__}: {error}"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert len(outcomes) == count, outcomes
    return sorted(outcomes)


@pytest.mark.parametrize("expected_revision", [0, 1])
def test_two_distinct_commands_racing_the_same_revision_never_both_succeed(
    service: Any, password: str, database: str, expected_revision: int
) -> None:
    if expected_revision:
        service.commit(_first(idempotency_key="rem0041-terminusdb-base-0001"))

    def commit(index: int) -> None:
        service.commit(
            _first(
                command_id=f"urn:ocor:command:rem0041:race-{index}",
                idempotency_key=f"rem0041-terminusdb-race-{index:04d}",
                expected_revision=expected_revision,
                canonical_delta={"winner": index},
            )
        )

    assert _race(8, commit) == ["OK"] + ["REVISION_CONFLICT"] * 7
    snapshot = service.read(TENANT, AGGREGATE_TYPE, AGGREGATE_REF)
    assert snapshot.revision == expected_revision + 1
    commits = _documents(password, database, "C3Commit")
    assert len(commits) == expected_revision + 1
    winner = [doc for doc in commits if doc["to_revision"] == expected_revision + 1]
    assert len(winner) == 1 and winner[0]["commit_id"] == snapshot.commit_id
    assert len(service.claim_batch(limit=100)) == expected_revision + 1


def test_the_same_command_racing_itself_commits_once_and_replays(service: Any) -> None:
    receipts: list[Any] = []
    lock = threading.Lock()

    def commit(index: int) -> None:
        receipt = service.commit(_first())
        with lock:
            receipts.append(receipt)

    assert _race(6, commit) == ["OK"] * 6
    assert sorted(receipt.replayed for receipt in receipts) == [False] + [True] * 5
    assert len({receipt.commit_id for receipt in receipts}) == 1
    assert service.current_revision(TENANT, AGGREGATE_TYPE, AGGREGATE_REF) == 1


def test_concurrent_acknowledgements_record_one_delivery_attempt(service: Any, password: str, database: str) -> None:
    receipt = service.commit(_first())

    def acknowledge(index: int) -> None:
        service.acknowledge(receipt.outbox_event_id, acknowledged_at=datetime.now(UTC))

    assert _race(6, acknowledge) == ["OK"] * 6
    assert [doc["event_id"] for doc in _documents(password, database, "C3DeliveryAttempt")] == [
        receipt.outbox_event_id
    ]
    assert service.claim_batch(limit=10) == ()


def test_concurrent_writer_acquisitions_leave_exactly_one_writer(service: Any, password: str, database: str) -> None:
    contenders = [
        _service_module().TerminusDBC3Service(url=URL, password=password, database=database) for _ in range(5)
    ]
    assert _race(5, lambda index: contenders[index].initialize()) == ["OK"] * 5
    epochs = sorted(contender.writer_epoch for contender in contenders)
    assert epochs == list(range(service.writer_epoch + 1, service.writer_epoch + 6))
    (fence,) = _documents(password, database, "C3WriterFence")
    assert fence["writer_epoch"] == epochs[-1]
    outcomes = []
    for index, contender in enumerate([service, *contenders]):
        try:
            contender.commit(
                _first(command_id=f"urn:ocor:command:rem0041:w-{index}", idempotency_key=f"rem0041-terminusdb-w-{index:04d}")
            )
            outcomes.append(contender.writer_epoch)
        except C3Error as error:
            assert error.reason_code == "SINGLE_WRITER_VIOLATION"
    assert outcomes == [epochs[-1]]


def test_concurrent_commits_on_distinct_aggregates_all_succeed(service: Any) -> None:
    errors: list[BaseException] = []

    def attempt(index: int) -> None:
        try:
            service.commit(
                _first(
                    command_id=f"urn:ocor:command:rem0041:agg-{index}",
                    idempotency_key=f"rem0041-terminusdb-agg-{index:04d}",
                    aggregate_ref=f"urn:ocor:mission-object:rem0041:agg-{index}",
                )
            )
        except BaseException as error:  # noqa: BLE001 - collected and asserted below
            errors.append(error)

    threads = [threading.Thread(target=attempt, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert errors == []
    assert len(service.claim_batch(limit=100)) == 6


def test_a_scenario_fork_never_produces_a_delivery_attempt(service: Any, password: str, database: str) -> None:
    receipt = service.commit(_first())
    status, body, _ = _raw(
        "POST",
        f"/api/branch/admin/{database}/local/branch/scenario-rem0041",
        password,
        {"origin": f"admin/{database}/local/branch/main"},
    )
    assert status == 200, body
    forked = _documents(password, database, "C3OutboxEntry", branch="scenario-rem0041")
    assert [doc["event_id"] for doc in forked] == [receipt.outbox_event_id]
    scenario_entry = dict(forked[0])
    scenario_entry.pop("@id")
    scenario_entry.update(
        {"key": "f" * 64, "event_id": "urn:ocor:event:scenario-only", "commit_id": "urn:ocor:commit:scenario-only"}
    )
    status, body, _ = _raw(
        "POST",
        f"/api/document/admin/{database}/local/branch/scenario-rem0041?author=c7-overlay&message=scenario",
        password,
        [scenario_entry],
    )
    assert status == 200, body

    claimed = service.claim_batch(limit=100)
    assert [e.event_id for e in claimed] == [receipt.outbox_event_id]
    for envelope in claimed:
        service.acknowledge(envelope.event_id, acknowledged_at=datetime.now(UTC))
    assert service.reconcile(limit=100) == 0
    assert service.claim_batch(limit=100) == ()
    assert [doc["event_id"] for doc in _documents(password, database, "C3DeliveryAttempt")] == [
        receipt.outbox_event_id
    ]
    assert _documents(password, database, "C3DeliveryAttempt", branch="scenario-rem0041") == []
    assert {doc["event_id"] for doc in _documents(password, database, "C3OutboxEntry")} == {receipt.outbox_event_id}


def test_an_entry_marked_for_a_scenario_branch_is_never_relayed_from_main(
    service: Any, password: str, database: str
) -> None:
    receipt = service.commit(_first())
    (entry,) = _documents(password, database, "C3OutboxEntry")
    foreign = {key: value for key, value in entry.items() if key != "@id"}
    foreign.update({"key": "e" * 64, "event_id": "urn:ocor:event:foreign-branch", "branch": "scenario-rem0041"})
    status, body, _ = _raw(
        "POST", f"/api/document/admin/{database}?author=tamper&message=foreign-branch-entry", password, [foreign]
    )
    assert status == 200, body
    assert [e.event_id for e in service.claim_batch(limit=100)] == [receipt.outbox_event_id]
    with pytest.raises(_adapter_module().TerminusDBAdapterError) as excinfo:
        service.acknowledge("urn:ocor:event:foreign-branch", acknowledged_at=datetime.now(UTC))
    assert excinfo.value.reason_code == "OUTBOX_ENTRY_NOT_FOUND"
    assert _documents(password, database, "C3DeliveryAttempt") == []


def test_reconcile_repairs_a_simulated_corruption_from_the_commit_record(
    service: Any, password: str, database: str
) -> None:
    receipt = service.commit(_first())
    assert service.reconcile(limit=10) == 0
    for doc_type in ("C3OutboxEntry", "C3Idempotency"):
        (doc,) = _documents(password, database, doc_type)
        status, body, _ = _raw(
            "DELETE",
            f"/api/document/admin/{database}?author=tamper&message=corruption&id={urllib.parse.quote(doc['@id'], safe='')}",
            password,
        )
        assert status in (200, 204), body
    assert service.reconcile(limit=10) == 2
    assert service.reconcile(limit=10) == 0
    (outbox,) = _documents(password, database, "C3OutboxEntry")
    assert outbox["event_id"] == receipt.outbox_event_id
    assert outbox["payload_digest"] == receipt.outbox_payload_digest
    assert service.commit(_first()).replayed is True


def test_acknowledging_an_unknown_event_fails_closed(service: Any) -> None:
    with pytest.raises(_adapter_module().TerminusDBAdapterError) as excinfo:
        service.acknowledge("urn:ocor:event:unknown", acknowledged_at=datetime.now(UTC))
    assert excinfo.value.reason_code == "OUTBOX_ENTRY_NOT_FOUND"


def test_the_initialization_is_idempotent_and_keeps_canonical_state(service: Any, password: str, database: str) -> None:
    receipt = service.commit(_first())
    service.initialize()
    snapshot = service.read(TENANT, AGGREGATE_TYPE, AGGREGATE_REF)
    assert snapshot is not None and snapshot.commit_id == receipt.commit_id
    assert database in _databases(password)


@pytest.mark.parametrize(
    "divergence",
    ["field_type", "extra_field", "missing_field", "key_strategy"],
)
def test_an_existing_schema_with_the_same_classes_but_divergent_definitions_fails_closed(
    password: str, database: str, divergence: str
) -> None:
    """Preventive review OCOR-DEV-REM-0041-63c6d5e8e094-pre, advisory P2: the schema
    check compares every class definition, not only the class names."""
    schema = json.loads(json.dumps(_adapter_module().SCHEMA))
    aggregate = next(item for item in schema if item.get("@id") == "C3Aggregate")
    if divergence == "field_type":
        aggregate["revision"] = "xsd:string"
    elif divergence == "extra_field":
        aggregate["unexpected"] = "xsd:string"
    elif divergence == "missing_field":
        del aggregate["state_digest"]
    else:
        aggregate["@key"] = {"@type": "Random"}
    status, body, _ = _raw("POST", f"/api/db/admin/{database}", password, {"label": database, "comment": "rem0041", "schema": True})
    assert status == 200, body
    status, body, _ = _raw(
        "POST",
        f"/api/document/admin/{database}?graph_type=schema&author=rem0041&message=divergent&full_replace=true",
        password,
        schema,
    )
    assert status == 200, body
    adapter = _adapter_module().TerminusDBC3Adapter(url=URL, password=password, database=database, writer_id="urn:ocor:writer:rem0041")
    with pytest.raises(_adapter_module().TerminusDBAdapterError) as excinfo:
        adapter.initialize()
    assert excinfo.value.reason_code == "SCHEMA_MISMATCH"


def test_an_existing_schema_identical_to_the_canonical_one_is_accepted(password: str, database: str) -> None:
    """Positive branch of the same check: a database created out of band with exactly
    ``SCHEMA`` initializes without rewriting it."""
    status, body, _ = _raw("POST", f"/api/db/admin/{database}", password, {"label": database, "comment": "rem0041", "schema": True})
    assert status == 200, body
    status, body, _ = _raw(
        "POST",
        f"/api/document/admin/{database}?graph_type=schema&author=rem0041&message=canonical&full_replace=true",
        password,
        list(_adapter_module().SCHEMA),
    )
    assert status == 200, body
    before = _log_length(password, database)
    adapter = _adapter_module().TerminusDBC3Adapter(url=URL, password=password, database=database, writer_id="urn:ocor:writer:rem0041")
    adapter.initialize()
    assert _log_length(password, database) == before
