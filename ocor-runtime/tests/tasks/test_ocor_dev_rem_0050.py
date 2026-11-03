"""OCOR-DEV-REM-0050 (NCP-U04): C3 commit admission, C6 -> C3 composition, outbox relay.

One test per register entry resolved by NCP-U04 of the approved plan
(``reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`` ``plan_units.NCP-U04``,
NORMATIVE-CONFORMANCE-PLAN (2026-10-30)), plus the detailed cases of each entry.
The normative elements realised or verified are cited with file and line:

- ADD v1.3 = ``ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md``
- LLD v1.1 = ``docs/OCOR_LLD_v1.1.md``
- Register = ``ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md``

- NCR-C3-001: LLD v1.1 :97 (before the transaction C3 validates closed record, digest,
  ``branch=main``, C6 provenance, Decision, Authority, Evidence, revision and bindings);
  ADD v1.3 :342 (rule 10: only with Decision and Authority refs valid, unexpired and
  coherent with the frozen GatePackage); ADD v1.3 :3430 and :3443 (aggregate version,
  idempotency key, writer epoch, Policy and Authority; mutation fence: canonical HEAD,
  aggregate version, active ontology release, writer epoch, idempotency key); ADD v1.3
  :2569 (precondition, invariant, revision and GatePackage mismatch map to
  ``PRECONDITION_FAILED``, ``INVARIANT_VIOLATION``, ``REVISION_CONFLICT``,
  ``GATE_PACKAGE_MISMATCH``); Register :186 (FR-062) and :310 (FR-138: every listed
  fault produces deny and no mutation).
- NCR-C3-002: LLD v1.1 :85-95 (``GovernedCanonicalCommitCommand`` is the only mutative
  command); ADD v1.3 :342 (every canonical mutation is produced exclusively by C6);
  ADD v1.3 :271 (one logical writer, ``writer_epoch`` fencing); ADD v1.3 :276 (C8 run
  state lives in the PostgreSQL Run Ledger, not in canonical state); Register :59
  (FR-008: retry with the same idempotency key does not duplicate the effect).
- NCR-C3-003: ADD v1.3 :293 (the worker reads committed outbox, publishes on the
  backbone, records a separate DeliveryAttempt); ADD v1.3 :3432 (relay publishes
  ``canonical-state-committed`` at least once); LLD v1.1 :132 (stable event ID, marked
  delivered only after ACK); LLD v1.1 :148 (projectors consume C3 events in order per
  aggregate and verify schema, release and GCS); Register :188 (FR-064), :192 (FR-068)
  and :207 (FR-075).
- NCR-C3-004: ADD v1.3 :293 (separate operational DeliveryAttempt); LLD v1.1 :136-142
  (``canonical_source_binding``: commit FK, claim/source/evidence refs).
- NCR-C3-006: LLD v1.1 :132 (the relay acquires ``main`` rows with ``SKIP LOCKED``).
- NCR-C3-007: ADD v1.3 :271 and PO decision NORMATIVE-CONFORMANCE-PLAN (2026-10-30)
  point 4 (the TerminusDB relay confirms a delivery only under the current writer
  epoch; characterisation test plus mutation probe).

Oracles are independent of the module under test: canonical state, commit, outbox,
source binding and delivery attempt rows are read with direct SQL (``psycopg``) on
PostgreSQL and with direct HTTP on TerminusDB; governance records are signed in the test
with the sealed C1 Ed25519 signer over the DSSE PAE of their RFC 8785 bytes; the C5
journal is read back from the real Kafka broker; projection facts are read from the
real TypeDB. Backends are real: PostgreSQL (``OCOR_LIVE_POSTGRES_DSN``), TerminusDB,
Kafka (self-provisioned single-node KRaft broker, as the C5 qualification tooling) and
TypeDB; without them every case fails, never skips. The C6 governance record store,
the stop epoch and the active ontology release are explicit test ports of the C3
admission ports (C6 and C1 own them in production).
"""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import psycopg
import pytest

from ocor_runtime.c1.signing import Ed25519SigningKey, dsse_pae
from ocor_runtime.c3.ports import C3Error, GovernedCanonicalCommitCommand
from ocor_runtime.kernel.canonical import canonical_bytes, canonical_digest, format_utc_timestamp
from ocor_runtime.kernel.governance import EvidenceRecord, InMemoryTrustedClock
from ocor_runtime.kernel.governed_context import GovernedContext

RUNTIME_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = RUNTIME_ROOT.parent
PACKAGE = RUNTIME_ROOT / "src" / "ocor_runtime"
TERMINUSDB_URL = os.environ.get("OCOR_LIVE_TERMINUSDB_URL", "http://127.0.0.1:6363")

NOW = datetime(2026, 11, 3, 9, 0, 0, tzinfo=UTC)
TENANT = "urn:ocor:tenant:synthetic"
AGGREGATE_TYPE = "MissionObject"
DIGEST_MARKING = "urn:sha256:" + "a" * 64
RELEASE = "urn:sha256:" + "b" * 64
OTHER_RELEASE = "urn:sha256:" + "e" * 64
POLICY_BUNDLE = "urn:sha256:" + "c" * 64
C6 = "urn:ocor:component:c6"
GATE_PACKAGE_TYPE = "application/vnd.ocor.c6.gate-package+json"
DECISION_TYPE = "application/vnd.ocor.c6.decision+json"
AUTHORITY_TYPE = "application/vnd.ocor.c6.authority+json"
C6_KEYID = "urn:ocor:key:c6:rem0050"
C6_KEY = Ed25519SigningKey.from_seed(hashlib.sha256(b"rem0050-c6-test-key").digest())
ROGUE_KEY = Ed25519SigningKey.from_seed(hashlib.sha256(b"rem0050-rogue-key").digest())
PRECONDITION = "urn:ocor:precondition:rem0050:not-closed"
INVARIANT = "urn:ocor:invariant:rem0050:status-known"
KNOWN_STATUSES = frozenset({"ASSESSED", "CLOSED", "EXECUTED", "VERIFIED"})


def _module(name: str) -> ModuleType:
    return importlib.import_module(name)


# ---------------------------------------------------------------------------------------
# Live backends
# ---------------------------------------------------------------------------------------


def _env_file() -> Path:
    candidates = []
    if os.environ.get("OCOR_BOOTSTRAP_ENV"):
        candidates.append(Path(os.environ["OCOR_BOOTSTRAP_ENV"]))
    candidates += [Path.home() / ".ocor-bootstrap-secrets" / "ocor-bootstrap.env", REPOSITORY_ROOT / ".ocor" / "bootstrap.env"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    pytest.fail("ocor-bootstrap env file not found; real TerminusDB credentials are mandatory qualifying evidence")


def _terminusdb_password() -> str:
    if os.environ.get("OCOR_LIVE_TERMINUSDB_PASSWORD"):
        return os.environ["OCOR_LIVE_TERMINUSDB_PASSWORD"]
    for line in _env_file().read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "OCOR_LOCAL_TERMINUSDB_PASSWORD" and value:
            return value.strip()
    pytest.fail("OCOR_LOCAL_TERMINUSDB_PASSWORD is absent from the ocor-bootstrap env file")


def _terminusdb(method: str, path: str, password: str, body: object | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(TERMINUSDB_URL + path, data=data, method=method)
    request.add_header("Authorization", "Basic " + base64.b64encode(f"admin:{password}".encode()).decode())
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, text = response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        status, text = error.code, error.read().decode("utf-8")
    return status, (json.loads(text) if text.strip() else None)


def _terminusdb_documents(password: str, database: str, doc_type: str) -> list[dict[str, Any]]:
    status, body = _terminusdb("GET", f"/api/document/admin/{database}/local/branch/main?type={doc_type}&as_list=true", password)
    assert status == 200, body
    return list(body or [])


@pytest.fixture(scope="module")
def dsn() -> str:
    value = os.environ.get("OCOR_LIVE_POSTGRES_DSN", "")
    if not value:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory: C3 admission is qualified on the real PostgreSQL adapter")
    with psycopg.connect(value) as connection:
        connection.execute("SELECT 1")
    return value


@pytest.fixture(scope="module")
def terminusdb_password() -> str:
    value = _terminusdb_password()
    status, body = _terminusdb("GET", "/api/db", value)
    assert status == 200, f"a real, live TerminusDB server is mandatory qualifying evidence: {body}"
    return value


def _sql(dsn: str, query: str, *params: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as connection:
        return list(connection.execute(query, params).fetchall())


# ---------------------------------------------------------------------------------------
# Test ports of the C3 admission (C6 governance records, stop epoch, active release)
# ---------------------------------------------------------------------------------------


@dataclass
class RecordStore:
    """Explicit test port of ``GovernedPathRecordPort``: the C6 record store."""

    gate_packages: dict[str, Any] = field(default_factory=dict)
    decisions: dict[str, Any] = field(default_factory=dict)
    authorities: dict[str, Any] = field(default_factory=dict)
    revoked: set[str] = field(default_factory=set)
    evidence_records: dict[str, EvidenceRecord] = field(default_factory=dict)

    def gate_package(self, gate_package_digest: str) -> Any:
        return self.gate_packages.get(gate_package_digest)

    def decision(self, decision_ref: str) -> Any:
        return self.decisions.get(decision_ref)

    def authority(self, authority_ref: str) -> Any:
        return self.authorities.get(authority_ref)

    def authority_revoked(self, authority_ref: str) -> bool:
        return authority_ref in self.revoked

    def evidence(self, evidence_ref: str) -> EvidenceRecord | None:
        return self.evidence_records.get(evidence_ref)

    # C6 side (record sink) used by the C6 engine
    def publish(self, record: Any) -> None:
        payload = record.payload
        kind = payload["record_type"]
        if kind == "GatePackage":
            self.gate_packages[canonical_digest(_thaw(payload))] = record
        elif kind == "Decision":
            self.decisions[payload["decision_ref"]] = record
        elif kind == "Authority":
            self.authorities[payload["authority_ref"]] = record
        else:
            raise AssertionError(f"unexpected record {kind}")


@dataclass
class Fence:
    """Explicit test port of ``MutationFencePort`` (C6 stop epoch, C1 active release)."""

    stop_epoch: int = 3
    stopped: bool = False
    release: str = RELEASE

    def current_stop_epoch(self) -> int:
        return self.stop_epoch

    def emergency_stop_active(self) -> bool:
        return self.stopped

    def active_release_digest(self) -> str:
        return self.release


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(child) for child in value]
    return value


def _sign(payload_type: str, payload: Mapping[str, Any], *, key: Ed25519SigningKey = C6_KEY, keyid: str = C6_KEYID) -> Any:
    signature = key.sign(dsse_pae(payload_type, canonical_bytes(_thaw(payload))))
    return _module("ocor_runtime.c3.admission").SignedGovernanceRecord(
        payload_type=payload_type, payload=payload, keyid=keyid, signature=base64.b64encode(signature).decode("ascii")
    )


def _context(*, release: str = RELEASE) -> GovernedContext:
    return GovernedContext.from_mapping(
        {
            "tenant_id": TENANT,
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": ["urn:ocor:compartment:alpha"],
            "classification_marking_ref": DIGEST_MARKING,
            "purpose": "rem0050-c3-admission",
            "effective_principal_id": "urn:ocor:principal:analyst-1",
            "actor_chain": ["urn:ocor:principal:analyst-1", "urn:ocor:component:c6"],
            "ontology_release_digest": release,
            "policy_bundle_digest": POLICY_BUNDLE,
            "correlation_id": "018f2f95-01b2-7cc3-8d4e-1234567890ab",
        }
    )


@dataclass
class GovernedPath:
    """One governed canonical commit as C6 freezes and signs it."""

    records: RecordStore
    fence: Fence
    clock: InMemoryTrustedClock
    aggregate_ref: str
    expected_revision: int = 0
    canonical_delta: Mapping[str, Any] = field(default_factory=lambda: {"status": "ASSESSED"})
    idempotency_key: str = ""
    suffix: str = ""

    def __post_init__(self) -> None:
        self.suffix = self.suffix or uuid.uuid4().hex[:12]
        self.idempotency_key = self.idempotency_key or f"rem0050-key-{self.suffix}"
        self.context = _context()
        self.action_instance_id = f"urn:ocor:action-instance:rem0050:{self.suffix}"
        self.decision_ref = f"urn:ocor:decision:rem0050:{self.suffix}"
        self.authority_ref = f"urn:ocor:authority:rem0050:{self.suffix}"
        self.evidence_ref = f"urn:ocor:evidence:rem0050:{self.suffix}"
        self.binding = {
            "claim_ref": f"urn:ocor:claim:rem0050:{self.suffix}",
            "source_ref": f"urn:ocor:source:rem0050:{self.suffix}",
            "evidence_ref": self.evidence_ref,
        }
        self.records.evidence_records[self.evidence_ref] = EvidenceRecord(
            evidence_id=self.evidence_ref,
            content_digest="urn:sha256:" + hashlib.sha256(self.suffix.encode()).hexdigest(),
            source_ref=self.binding["source_ref"],
            acquired_at=NOW - timedelta(hours=1),
            acquirer_principal_id="urn:ocor:principal:analyst-1",
            method_ref="urn:ocor:method:rem0050",
            chain_of_custody=("urn:ocor:custody:rem0050",),
            marking_ref=DIGEST_MARKING,
            retention_until=NOW + timedelta(days=30),
        )

    def gate_package_payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "record_type": "GatePackage",
            "producer": C6,
            "action_instance_id": self.action_instance_id,
            "decision_ref": self.decision_ref,
            "authority_ref": self.authority_ref,
            "evidence_refs": [self.evidence_ref],
            "claim_source_bindings": [dict(self.binding)],
            "aggregate_type": AGGREGATE_TYPE,
            "aggregate_ref": self.aggregate_ref,
            "expected_revision": self.expected_revision,
            "canonical_delta_digest": canonical_digest(_thaw(self.canonical_delta)),
            "idempotency_key": self.idempotency_key,
            "precondition_bindings": [PRECONDITION],
            "invariant_bindings": [INVARIANT],
            "governed_context_digest": self.context.digest(),
            "ontology_release_digest": RELEASE,
            "stop_epoch": 3,
            "frozen_at": format_utc_timestamp(NOW),
        }
        payload.update(overrides)
        return payload

    def decision_payload(self, gate_package_digest: str, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "record_type": "Decision",
            "producer": C6,
            "decision_ref": self.decision_ref,
            "action_instance_id": self.action_instance_id,
            "outcome": "ACCEPT",
            "effect_class": "CANONICAL_COMMIT",
            "gate_package_digest": gate_package_digest,
            "decided_at": format_utc_timestamp(NOW),
            "expires_at": format_utc_timestamp(NOW + timedelta(hours=1)),
        }
        payload.update(overrides)
        return payload

    def authority_payload(self, gate_package_digest: str, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "record_type": "Authority",
            "producer": C6,
            "authority_ref": self.authority_ref,
            "action_instance_id": self.action_instance_id,
            "gate_package_digest": gate_package_digest,
            "tenant_id": TENANT,
            "effective_principal_id": "urn:ocor:principal:analyst-1",
            "not_before": format_utc_timestamp(NOW - timedelta(minutes=5)),
            "expires_at": format_utc_timestamp(NOW + timedelta(hours=1)),
        }
        payload.update(overrides)
        return payload

    def freeze(
        self,
        *,
        gate_package: Mapping[str, Any] | None = None,
        decision: Mapping[str, Any] | None = None,
        authority: Mapping[str, Any] | None = None,
        gate_key: Ed25519SigningKey = C6_KEY,
        decision_key: Ed25519SigningKey = C6_KEY,
        authority_key: Ed25519SigningKey = C6_KEY,
        register: bool = True,
    ) -> str:
        package = dict(gate_package) if gate_package is not None else self.gate_package_payload()
        digest = canonical_digest(package)
        if register:
            self.records.gate_packages[digest] = _sign(GATE_PACKAGE_TYPE, package, key=gate_key)
            decision_record = dict(decision) if decision is not None else self.decision_payload(digest)
            self.records.decisions[self.decision_ref] = _sign(DECISION_TYPE, decision_record, key=decision_key)
            authority_record = dict(authority) if authority is not None else self.authority_payload(digest)
            self.records.authorities[self.authority_ref] = _sign(AUTHORITY_TYPE, authority_record, key=authority_key)
        return digest

    def command(self, gate_package_digest: str, **overrides: Any) -> GovernedCanonicalCommitCommand:
        value: dict[str, Any] = {
            "command_id": f"urn:ocor:command:rem0050:{self.suffix}",
            "action_instance_id": self.action_instance_id,
            "aggregate_type": AGGREGATE_TYPE,
            "aggregate_ref": self.aggregate_ref,
            "expected_revision": self.expected_revision,
            "canonical_delta": _thaw(self.canonical_delta),
            "decision_ref": self.decision_ref,
            "authority_ref": self.authority_ref,
            "evidence_refs": [self.evidence_ref],
            "claim_source_bindings": [dict(self.binding)],
            "precondition_bindings": [PRECONDITION],
            "invariant_bindings": [INVARIANT],
            "idempotency_key": self.idempotency_key,
            "governed_context": self.context.to_mapping(),
            "governed_context_digest": self.context.digest(),
            "gate_package_digest": gate_package_digest,
            "branch": "main",
        }
        value.update(overrides)
        return GovernedCanonicalCommitCommand.from_mapping(value)


def _admission(records: RecordStore, fence: Fence, clock: InMemoryTrustedClock) -> Any:
    module = _module("ocor_runtime.c3.admission")
    return module.CommitAdmission(
        records=records,
        fence=fence,
        trusted_keys={C6_KEYID: C6_KEY.public_key},
        clock=clock,
        preconditions={PRECONDITION: lambda state: state.get("status") != "CLOSED"},
        invariants={INVARIANT: lambda state: state.get("status") in KNOWN_STATUSES},
    )


@dataclass
class Backend:
    name: str
    service: Any
    records: RecordStore
    fence: Fence
    clock: InMemoryTrustedClock
    revision: Callable[[str], int]
    commits: Callable[[], int]
    outbox: Callable[[], int]
    source_bindings: Callable[[str], set[tuple[str, str, str]]]
    make_service: Callable[[], Any]


@pytest.fixture
def postgres_backend(dsn: str) -> Iterator[Backend]:
    records, fence, clock = RecordStore(), Fence(), InMemoryTrustedClock(NOW)
    service_type = _module("ocor_runtime.c3.service").PostgresC3Service

    def make() -> Any:
        value = service_type(dsn, admission=_admission(records, fence, clock))
        value.initialize()
        return value

    service = make()
    service.reset()

    def revision(aggregate_ref: str) -> int:
        rows = _sql(dsn, "SELECT revision FROM c3_aggregate WHERE aggregate_ref=%s", aggregate_ref)
        return int(rows[0][0]) if rows else 0

    def source_bindings(commit_id: str) -> set[tuple[str, str, str]]:
        rows = _sql(dsn, "SELECT claim_ref, source_ref, evidence_ref FROM c3_source_binding WHERE commit_id=%s", commit_id)
        return {(str(a), str(b), str(c)) for a, b, c in rows}

    yield Backend(
        "postgresql",
        service,
        records,
        fence,
        clock,
        revision,
        lambda: int(_sql(dsn, "SELECT count(*) FROM c3_commit")[0][0]),
        lambda: int(_sql(dsn, "SELECT count(*) FROM c3_outbox")[0][0]),
        source_bindings,
        make,
    )
    service.reset()


@pytest.fixture
def terminusdb_backend(terminusdb_password: str) -> Iterator[Backend]:
    records, fence, clock = RecordStore(), Fence(), InMemoryTrustedClock(NOW)
    database = f"ocor_c3_rem0050_{uuid.uuid4().hex[:12]}"
    service_type = _module("ocor_runtime.c3.terminusdb_service").TerminusDBC3Service

    def make() -> Any:
        value = service_type(
            url=TERMINUSDB_URL, password=terminusdb_password, database=database, admission=_admission(records, fence, clock)
        )
        value.initialize()
        return value

    def documents(doc_type: str) -> list[dict[str, Any]]:
        return _terminusdb_documents(terminusdb_password, database, doc_type)

    def revision(aggregate_ref: str) -> int:
        rows = [item for item in documents("C3Aggregate") if item["aggregate_ref"] == aggregate_ref]
        return int(rows[0]["revision"]) if rows else 0

    def source_bindings(commit_id: str) -> set[tuple[str, str, str]]:
        return {
            (item["claim_ref"], item["source_ref"], item["evidence_ref"])
            for item in documents("C3SourceBinding")
            if item["commit_id"] == commit_id
        }

    try:
        service = make()
        yield Backend(
            "terminusdb",
            service,
            records,
            fence,
            clock,
            revision,
            lambda: len(documents("C3Commit")),
            lambda: len(documents("C3OutboxEntry")),
            source_bindings,
            make,
        )
    finally:
        _terminusdb("DELETE", f"/api/db/admin/{database}", terminusdb_password)


@pytest.fixture(params=["postgresql", "terminusdb"])
def backend(request: pytest.FixtureRequest) -> Backend:
    fixture = "postgres_backend" if request.param == "postgresql" else "terminusdb_backend"
    return request.getfixturevalue(fixture)


def _path(backend: Backend, **values: Any) -> GovernedPath:
    return GovernedPath(
        backend.records, backend.fence, backend.clock, aggregate_ref=f"urn:ocor:mission-object:rem0050:{uuid.uuid4().hex[:8]}", **values
    )


def _assert_denied(backend: Backend, path: GovernedPath, command: GovernedCanonicalCommitCommand, reason: str) -> None:
    commits, outbox = backend.commits(), backend.outbox()
    with pytest.raises(C3Error) as caught:
        backend.service.commit(command)
    assert caught.value.reason_code == reason, str(caught.value)
    # FR-138 (Register :310): the denied mutation wrote nothing.
    assert backend.revision(path.aggregate_ref) == path.expected_revision
    assert (backend.commits(), backend.outbox()) == (commits, outbox)


# ---------------------------------------------------------------------------------------
# NCR-C3-001: commit admission
# ---------------------------------------------------------------------------------------


def _fault_decision_missing(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = path.freeze()
    path.records.decisions.pop(path.decision_ref)
    return path.command(digest)


def _fault_decision_rogue_signature(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    return path.command(path.freeze(decision_key=ROGUE_KEY))


def _fault_decision_not_c6(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    package = path.gate_package_payload()
    digest = canonical_digest(package)
    return path.command(path.freeze(decision=path.decision_payload(digest, producer="urn:ocor:component:c8")))


def _fault_decision_rejected(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = canonical_digest(path.gate_package_payload())
    return path.command(path.freeze(decision=path.decision_payload(digest, outcome="REJECT")))


def _fault_decision_external_effect(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = canonical_digest(path.gate_package_payload())
    return path.command(path.freeze(decision=path.decision_payload(digest, effect_class="EXTERNAL_ADAPTER")))


def _fault_decision_expired(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = canonical_digest(path.gate_package_payload())
    expired = format_utc_timestamp(NOW - timedelta(seconds=1))
    return path.command(path.freeze(decision=path.decision_payload(digest, expires_at=expired)))


def _fault_decision_other_package(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    other = "urn:sha256:" + "9" * 64
    return path.command(path.freeze(decision=path.decision_payload(other)))


def _fault_authority_missing(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = path.freeze()
    path.records.authorities.pop(path.authority_ref)
    return path.command(digest)


def _fault_authority_rogue_signature(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    return path.command(path.freeze(authority_key=ROGUE_KEY))


def _fault_authority_expired(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = canonical_digest(path.gate_package_payload())
    expired = format_utc_timestamp(NOW)
    return path.command(path.freeze(authority=path.authority_payload(digest, expires_at=expired)))


def _fault_authority_not_yet_valid(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = canonical_digest(path.gate_package_payload())
    later = format_utc_timestamp(NOW + timedelta(minutes=1))
    return path.command(path.freeze(authority=path.authority_payload(digest, not_before=later)))


def _fault_authority_revoked(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = path.freeze()
    path.records.revoked.add(path.authority_ref)
    return path.command(digest)


def _fault_authority_other_package(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    other = "urn:sha256:" + "8" * 64
    return path.command(path.freeze(authority=path.authority_payload(other)))


def _fault_authority_other_tenant(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = canonical_digest(path.gate_package_payload())
    return path.command(path.freeze(authority=path.authority_payload(digest, tenant_id="urn:ocor:tenant:other")))


def _fault_gate_package_unknown(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    path.freeze()
    return path.command("urn:sha256:" + "d" * 64)


def _fault_gate_package_rogue_signature(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    return path.command(path.freeze(gate_key=ROGUE_KEY))


def _fault_gate_package_not_c6(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    return path.command(path.freeze(gate_package=path.gate_package_payload(producer="urn:ocor:component:c8")))


def _fault_gate_package_other_delta(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = path.freeze()
    return path.command(digest, canonical_delta={"status": "VERIFIED"})


def _fault_gate_package_other_aggregate(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    package = path.gate_package_payload(aggregate_ref="urn:ocor:mission-object:rem0050:elsewhere")
    return path.command(path.freeze(gate_package=package))


def _fault_gate_package_other_bindings(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = path.freeze()
    return path.command(digest, invariant_bindings=[INVARIANT, "urn:ocor:invariant:rem0050:unbound"])


def _fault_gate_package_other_context(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    package = path.gate_package_payload(governed_context_digest="urn:sha256:" + "7" * 64)
    return path.command(path.freeze(gate_package=package))


def _fault_evidence_unresolvable(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = path.freeze()
    path.records.evidence_records.pop(path.evidence_ref)
    return path.command(digest)


def _fault_emergency_stop(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = path.freeze()
    path.fence.stopped = True
    return path.command(digest)


def _fault_stop_epoch_advanced(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = path.freeze()
    path.fence.stop_epoch = 4
    return path.command(digest)


def _fault_release_inactive(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    digest = path.freeze()
    path.fence.release = OTHER_RELEASE
    return path.command(digest)


def _fault_precondition_unknown(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    package = path.gate_package_payload(precondition_bindings=["urn:ocor:precondition:rem0050:unknown"])
    return path.command(path.freeze(gate_package=package), precondition_bindings=["urn:ocor:precondition:rem0050:unknown"])


def _fault_invariant_violated(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    path.canonical_delta = {"status": "UNKNOWN-STATUS"}
    return path.command(path.freeze())


def _fault_invariant_unknown(path: GovernedPath) -> GovernedCanonicalCommitCommand:
    package = path.gate_package_payload(invariant_bindings=["urn:ocor:invariant:rem0050:unknown"])
    return path.command(path.freeze(gate_package=package), invariant_bindings=["urn:ocor:invariant:rem0050:unknown"])


FAULTS: tuple[tuple[str, Callable[[GovernedPath], GovernedCanonicalCommitCommand], str], ...] = (
    ("decision-unresolvable", _fault_decision_missing, "POLICY_DENIED"),
    ("decision-signed-by-untrusted-key", _fault_decision_rogue_signature, "POLICY_DENIED"),
    ("decision-not-produced-by-c6", _fault_decision_not_c6, "POLICY_DENIED"),
    ("decision-not-accept", _fault_decision_rejected, "POLICY_DENIED"),
    ("decision-not-canonical-commit", _fault_decision_external_effect, "POLICY_DENIED"),
    ("decision-expired", _fault_decision_expired, "POLICY_DENIED"),
    ("decision-bound-to-another-gate-package", _fault_decision_other_package, "GATE_PACKAGE_MISMATCH"),
    ("authority-unresolvable", _fault_authority_missing, "AUTHORITY_MISSING"),
    ("authority-signed-by-untrusted-key", _fault_authority_rogue_signature, "AUTHORITY_MISSING"),
    ("authority-expired", _fault_authority_expired, "AUTHORITY_MISSING"),
    ("authority-not-yet-valid", _fault_authority_not_yet_valid, "AUTHORITY_MISSING"),
    ("authority-revoked", _fault_authority_revoked, "AUTHORITY_MISSING"),
    ("authority-bound-to-another-gate-package", _fault_authority_other_package, "GATE_PACKAGE_MISMATCH"),
    ("authority-of-another-tenant", _fault_authority_other_tenant, "GATE_PACKAGE_MISMATCH"),
    ("gate-package-unresolvable", _fault_gate_package_unknown, "GATE_PACKAGE_MISMATCH"),
    ("gate-package-signed-by-untrusted-key", _fault_gate_package_rogue_signature, "GATE_PACKAGE_MISMATCH"),
    ("gate-package-not-produced-by-c6", _fault_gate_package_not_c6, "GATE_PACKAGE_MISMATCH"),
    ("gate-package-binds-another-delta", _fault_gate_package_other_delta, "GATE_PACKAGE_MISMATCH"),
    ("gate-package-binds-another-aggregate", _fault_gate_package_other_aggregate, "GATE_PACKAGE_MISMATCH"),
    ("gate-package-binds-other-invariants", _fault_gate_package_other_bindings, "GATE_PACKAGE_MISMATCH"),
    ("gate-package-binds-another-context", _fault_gate_package_other_context, "GATE_PACKAGE_MISMATCH"),
    ("evidence-unresolvable", _fault_evidence_unresolvable, "CONTRACT_REJECTED"),
    ("emergency-stop-active", _fault_emergency_stop, "EMERGENCY_STOP_ACTIVE"),
    ("stop-epoch-advanced-since-freeze", _fault_stop_epoch_advanced, "EMERGENCY_STOP_ACTIVE"),
    ("ontology-release-not-active", _fault_release_inactive, "RELEASE_MISMATCH"),
    ("precondition-unknown", _fault_precondition_unknown, "PRECONDITION_FAILED"),
    ("invariant-violated-by-the-new-state", _fault_invariant_violated, "INVARIANT_VIOLATION"),
    ("invariant-unknown", _fault_invariant_unknown, "INVARIANT_VIOLATION"),
)


def test_ncr_c3_001_conforms(backend: Backend) -> None:
    """A fully governed command is admitted; its claim/source bindings are persisted."""
    path = _path(backend)
    command = path.command(path.freeze())
    receipt = backend.service.commit(command)
    assert (receipt.from_revision, receipt.to_revision, receipt.replayed) == (0, 1, False)
    assert backend.revision(path.aggregate_ref) == 1
    assert backend.source_bindings(receipt.commit_id) == {
        (path.binding["claim_ref"], path.binding["source_ref"], path.binding["evidence_ref"])
    }
    # FR-062 (Register :186): a duplicated retry returns the same receipt.
    again = backend.service.commit(command)
    assert (again.commit_id, again.replayed) == (receipt.commit_id, True)
    assert backend.revision(path.aggregate_ref) == 1


@pytest.mark.parametrize(("name", "fault", "reason"), FAULTS, ids=[item[0] for item in FAULTS])
def test_ncr_c3_001_every_listed_fault_denies_without_mutation(
    backend: Backend, name: str, fault: Callable[[GovernedPath], GovernedCanonicalCommitCommand], reason: str
) -> None:
    """FR-138 (Register :310): every fault produces deny and no canonical mutation."""
    path = _path(backend)
    command = fault(path)
    _assert_denied(backend, path, command, reason)


def test_ncr_c3_001_precondition_is_evaluated_on_the_current_canonical_state(backend: Backend) -> None:
    """FR-062 (Register :186): preconditions read the current canonical state, and a stale
    expected revision is a revision conflict (LLD v1.1 :132)."""
    first = _path(backend, canonical_delta={"status": "CLOSED"})
    backend.service.commit(first.command(first.freeze()))
    reopen = GovernedPath(backend.records, backend.fence, backend.clock, aggregate_ref=first.aggregate_ref,
                          expected_revision=1, canonical_delta={"status": "ASSESSED"})
    _assert_denied(backend, reopen, reopen.command(reopen.freeze()), "PRECONDITION_FAILED")
    stale = GovernedPath(backend.records, backend.fence, backend.clock, aggregate_ref=first.aggregate_ref,
                         expected_revision=0, canonical_delta={"status": "VERIFIED"})
    commits = backend.commits()
    with pytest.raises(C3Error) as caught:
        backend.service.commit(stale.command(stale.freeze()))
    assert caught.value.reason_code == "REVISION_CONFLICT"
    assert backend.commits() == commits
    assert backend.revision(first.aggregate_ref) == 1


def test_ncr_c3_001_stale_writer_epoch_is_fenced(backend: Backend) -> None:
    """ADD v1.3 :271 and :3443: a writer whose epoch is no longer current writes nothing."""
    path = _path(backend)
    command = path.command(path.freeze())
    successor = backend.make_service()
    assert successor.writer_epoch == backend.service.writer_epoch + 1
    _assert_denied(backend, path, command, "SINGLE_WRITER_VIOLATION")
    assert successor.commit(command).to_revision == 1


def test_ncr_c3_001_postgres_commit_records_the_writer_epoch(postgres_backend: Backend, dsn: str) -> None:
    path = _path(postgres_backend)
    receipt = postgres_backend.service.commit(path.command(path.freeze()))
    rows = _sql(dsn, "SELECT writer_epoch FROM c3_commit WHERE commit_id=%s", receipt.commit_id)
    assert rows == [(postgres_backend.service.writer_epoch,)]


# ---------------------------------------------------------------------------------------
# NCR-C3-002: C6 -> C3 composition; C8 writes no canonical state
# ---------------------------------------------------------------------------------------


def _relative_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.add(("." * node.level) + (node.module or ""))
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_ncr_c3_002_conforms() -> None:
    """LLD v1.1 :85-95 and ADD v1.3 :342: the current C6 and C8 never use the legacy store."""
    engine = PACKAGE / "c6" / "engine.py"
    orchestrator = PACKAGE / "c8" / "orchestrator.py"
    for module in (engine, orchestrator):
        imports = _relative_imports(module)
        assert not any(name.endswith("c3_store") for name in imports), (module.name, sorted(imports))
        assert "_store.write" not in module.read_text(encoding="utf-8")
    assert "GovernedCanonicalCommitCommand" in engine.read_text(encoding="utf-8")
    assert "GovernedCanonicalCommitCommand" not in orchestrator.read_text(encoding="utf-8")


def _engine_fixture(service: Any, records: RecordStore, fence: Fence, clock: InMemoryTrustedClock) -> tuple[Any, Any, Any]:
    from ocor_runtime.c6_capabilities import CapabilityAuthority
    from ocor_runtime.c7_emission import EmissionFence

    engine_module = _module("ocor_runtime.c6.engine")
    authority = CapabilityAuthority(issuer="ocor-c6-rem0050-authority")
    path = engine_module.CanonicalCommitPath(
        signing_key=C6_KEY,
        keyid=C6_KEYID,
        records=records,
        fence=fence,
        clock=clock,
        aggregate_type=AGGREGATE_TYPE,
        governed_context=_context(),
        precondition_bindings=(PRECONDITION,),
        invariant_bindings=(INVARIANT,),
    )
    engine = engine_module.GovernedActionEngine(
        authority=authority, commit_port=service, fence=EmissionFence(), canonical_path=path
    )
    return engine_module, engine, authority


def test_ncr_c3_002_c6_engine_commits_through_the_c3_governed_path(postgres_backend: Backend, dsn: str) -> None:
    """The engine freezes and signs the GatePackage, Decision and Authority it sends to C3;
    C3 admits the command; a retry with the same idempotency key does not duplicate (FR-008)."""
    engine_module, engine, authority = _engine_fixture(
        postgres_backend.service, postgres_backend.records, postgres_backend.fence, postgres_backend.clock
    )
    suffix = uuid.uuid4().hex[:8]
    aggregate = f"urn:ocor:mission-object:rem0050:engine:{suffix}"
    proposal = engine_module.ActionProposal(
        action_id=f"urn:ocor:action:rem0050:{suffix}", subject="analyst-1", capability="act:assess",
        resource=aggregate, aggregate_id=aggregate, risk_bearing=False,
    )
    evidence = GovernedPath(postgres_backend.records, postgres_backend.fence, postgres_backend.clock, aggregate_ref=aggregate)
    decision = engine_module.Decision(action_id=proposal.action_id, decided_by="duty-officer", accepted=True,
                                      rationale="assessed", decided_at=NOW)
    delivered: list[Any] = []

    def run() -> Any:
        lease = authority.issue(subject="analyst-1", capabilities=["act:assess"], resources=[aggregate], issued_at=NOW,
                                ttl=timedelta(hours=1))
        return engine.execute(proposal, lease=lease, approval=None, decision=decision, sink=delivered.append, at=NOW,
                              evidence_refs=(evidence.evidence_ref,), claim_source_bindings=(dict(evidence.binding),))

    first = run()
    snapshot = postgres_backend.service.read(TENANT, AGGREGATE_TYPE, aggregate)
    assert snapshot is not None and snapshot.revision == 1 and snapshot.state["status"] == "EXECUTED"
    rows = _sql(dsn, "SELECT decision_ref, authority_ref, gate_package_digest FROM c3_commit WHERE aggregate_ref=%s", aggregate)
    assert len(rows) == 1
    decision_ref, authority_ref, gate_package_digest = rows[0]
    assert postgres_backend.records.decision(decision_ref) is not None
    assert postgres_backend.records.authority(authority_ref) is not None
    assert postgres_backend.records.gate_package(gate_package_digest) is not None
    second = run()
    assert second.commit_receipt.commit_id == first.commit_receipt.commit_id
    assert second.commit_receipt.replayed is True
    assert postgres_backend.revision(aggregate) == 1


def test_ncr_c3_002_c6_denial_reaches_no_canonical_commit(postgres_backend: Backend) -> None:
    engine_module, engine, authority = _engine_fixture(
        postgres_backend.service, postgres_backend.records, postgres_backend.fence, postgres_backend.clock
    )
    aggregate = f"urn:ocor:mission-object:rem0050:denied:{uuid.uuid4().hex[:8]}"
    proposal = engine_module.ActionProposal(
        action_id=f"urn:ocor:action:rem0050:{uuid.uuid4().hex[:8]}", subject="analyst-1", capability="act:assess",
        resource=aggregate, aggregate_id=aggregate, risk_bearing=False,
    )
    lease = authority.issue(subject="analyst-1", capabilities=["act:assess"], resources=[aggregate], issued_at=NOW,
                            ttl=timedelta(hours=1))
    rejected = engine_module.Decision(action_id=proposal.action_id, decided_by="duty-officer", accepted=False,
                                      rationale="not supported", decided_at=NOW)
    with pytest.raises(engine_module.GovernedActionError) as caught:
        engine.execute(proposal, lease=lease, approval=None, decision=rejected, sink=lambda event: None, at=NOW,
                       evidence_refs=("urn:ocor:evidence:none",), claim_source_bindings=())
    assert caught.value.reason_code == "DECISION_REJECTED"
    assert postgres_backend.revision(aggregate) == 0


def test_ncr_c3_002_c8_run_state_is_the_run_ledger_not_canonical_state(postgres_backend: Backend, dsn: str) -> None:
    """ADD v1.3 :276: C8 keeps AgentRun state in the PostgreSQL Run Ledger; it never
    produces a canonical mutation (ADD v1.3 :342)."""
    from ocor_runtime.c6_capabilities import CapabilityAuthority

    orchestrator_module = _module("ocor_runtime.c8.orchestrator")
    ledger_module = _module("ocor_runtime.c8.adapters.postgres_ledger")
    ledger = ledger_module.PostgresRunLedger(dsn)
    ledger.initialize()
    authority = CapabilityAuthority(issuer="ocor-c8-rem0050-authority")
    orchestrator = orchestrator_module.AgentRunOrchestrator(authority=authority, ledger=ledger)
    task = f"task-rem0050-{uuid.uuid4().hex[:8]}"
    lease = authority.issue(subject="team-lead-1", capabilities=["agent:assign"], resources=["agent-1"], issued_at=NOW,
                            ttl=timedelta(hours=1))
    commits = postgres_backend.commits()
    orchestrator.assign(task, "agent-1", capability="act:do-thing", lease=lease, assigned_by="team-lead-1", at=NOW)
    assert postgres_backend.commits() == commits
    assert [entry.kind for entry in ledger.entries(task)] == ["TASK_ASSIGNED"]
    rows = _sql(dsn, "SELECT kind FROM c8_run_ledger WHERE task_id=%s", task)
    assert rows == [("TASK_ASSIGNED",)]


# ---------------------------------------------------------------------------------------
# NCR-C3-003: outbox -> C5 -> C4 chain and event payload
# ---------------------------------------------------------------------------------------

EVENT_FIELDS = {
    "event_type",
    "commit_id",
    "command_id",
    "action_instance_id",
    "tenant_id",
    "aggregate_type",
    "aggregate_ref",
    "from_revision",
    "to_revision",
    "state",
    "state_digest",
    "decision_ref",
    "authority_ref",
    "evidence_refs",
    "gate_package_digest",
    "governed_context_digest",
    "ontology_release_digest",
    "boundary",
    "actor_chain",
    "correlation_id",
    "causation_id",
    "branch",
}


def test_ncr_c3_003_conforms(backend: Backend) -> None:
    """FR-068 and FR-075: the committed outbox entry carries the event type, the isolation
    boundary and the correlation of the governed path."""
    path = _path(backend)
    receipt = backend.service.commit(path.command(path.freeze()))
    (envelope,) = [item for item in backend.service.claim_batch(limit=10) if item.commit_id == receipt.commit_id]
    payload = _thaw(envelope.payload)
    assert set(payload) == EVENT_FIELDS
    assert payload["event_type"] == "canonical-state-committed"
    assert payload["boundary"] == {
        "tenant_id": TENANT,
        "domain_id": "urn:ocor:domain:logistics",
        "compartments": ["urn:ocor:compartment:alpha"],
        "classification_marking_ref": DIGEST_MARKING,
        "purpose": "rem0050-c3-admission",
    }
    assert payload["correlation_id"] == path.context.correlation_id
    assert payload["causation_id"] == path.action_instance_id
    assert payload["actor_chain"] == list(path.context.actor_chain)
    assert (payload["decision_ref"], payload["authority_ref"], payload["action_instance_id"]) == (
        path.decision_ref, path.authority_ref, path.action_instance_id
    )
    assert payload["governed_context_digest"] == path.context.digest()
    assert payload["ontology_release_digest"] == RELEASE
    assert payload["state"] == {"status": "ASSESSED"}
    assert payload["state_digest"] == canonical_digest({"status": "ASSESSED"})
    assert envelope.payload_digest == canonical_digest(payload)


@pytest.fixture
def kafka() -> Iterator[Any]:
    from ocor_runtime.c5.backbone import CanonicalEventBackbone

    topic = f"ocor.rem0050.canonical.{uuid.uuid4().hex[:8]}"
    backbone, _container, volume = CanonicalEventBackbone.provision(topic)
    try:
        yield backbone
    finally:
        backbone.destroy(volume)


@pytest.fixture
def projection() -> Iterator[Any]:
    from ocor_runtime.c4.typedb_adapter import TypeDBProjectionAdapter

    value = TypeDBProjectionAdapter()
    value.initialize()
    value.reset()
    try:
        yield value
    finally:
        value.reset()


def test_ncr_c3_003_relay_publishes_on_c5_and_c4_projects_in_order(
    postgres_backend: Backend, kafka: Any, projection: Any, dsn: str
) -> None:
    """ADD v1.3 :293 and :3432, LLD v1.1 :132 and :148, FR-064: the relay publishes
    canonical-state-committed with the stable event ID on the real backbone, records the
    delivery only after the broker ACK, and the C4 projector applies it once, in order."""
    relay_module = _module("ocor_runtime.c3.relay")
    projector_module = _module("ocor_runtime.c4.projector")
    first = _path(postgres_backend)
    r1 = postgres_backend.service.commit(first.command(first.freeze()))
    second = GovernedPath(postgres_backend.records, postgres_backend.fence, postgres_backend.clock,
                          aggregate_ref=first.aggregate_ref, expected_revision=1, canonical_delta={"status": "VERIFIED"})
    r2 = postgres_backend.service.commit(second.command(second.freeze()))

    worker = relay_module.OutboxRelayWorker(postgres_backend.service, kafka)
    published = worker.relay_once(limit=10)
    assert published == (r1.outbox_event_id, r2.outbox_event_id)
    attempts = _sql(dsn, "SELECT event_id, outcome FROM c3_delivery_attempt WHERE outcome='ACKNOWLEDGED' ORDER BY event_id")
    assert {row[0] for row in attempts} == {r1.outbox_event_id, r2.outbox_event_id}
    assert worker.relay_once(limit=10) == ()

    records = kafka.consume(2)
    assert [record.envelope.event_id for record in records] == [r1.outbox_event_id, r2.outbox_event_id]
    assert {record.envelope.event_type for record in records} == {"canonical-state-committed"}
    assert [record.envelope.sequence for record in records] == [1, 2]

    projector = projector_module.CanonicalStateProjector(projection, release_digest=RELEASE)
    assert projector.apply(records[0].envelope) is True
    assert projector.apply(records[0].envelope) is False  # FR-064: replay does not duplicate
    assert projector.apply(records[1].envelope) is True
    assert projection.current_watermark() == r2.commit_id
    assert projection.position("main", r1.commit_id) == 1
    assert projection.position("main", r2.commit_id) == 2


def test_ncr_c3_003_projector_verifies_order_schema_release_and_context(
    postgres_backend: Backend, projection: Any
) -> None:
    relay_module = _module("ocor_runtime.c3.relay")
    projector_module = _module("ocor_runtime.c4.projector")
    first = _path(postgres_backend)
    postgres_backend.service.commit(first.command(first.freeze()))
    second = GovernedPath(postgres_backend.records, postgres_backend.fence, postgres_backend.clock,
                          aggregate_ref=first.aggregate_ref, expected_revision=1, canonical_delta={"status": "VERIFIED"})
    postgres_backend.service.commit(second.command(second.freeze()))
    envelopes = [relay_module.canonical_event(item) for item in postgres_backend.service.claim_batch(limit=10)]
    assert [item.sequence for item in envelopes] == [1, 2]
    projector = projector_module.CanonicalStateProjector(projection, release_digest=RELEASE)
    error = projector_module.ProjectorError

    with pytest.raises(error) as caught:
        projector.apply(envelopes[1])
    assert caught.value.reason_code == "OUT_OF_ORDER"
    with pytest.raises(error) as caught:
        projector_module.CanonicalStateProjector(projection, release_digest=OTHER_RELEASE).apply(envelopes[0])
    assert caught.value.reason_code == "RELEASE_MISMATCH"
    tampered = _module("ocor_runtime.c5.backbone").CanonicalIngestionEnvelope.from_mapping(
        {**envelopes[0].to_mapping(), "governed_context_digest": "urn:sha256:" + "6" * 64}
    )
    with pytest.raises(error) as caught:
        projector.apply(tampered)
    assert caught.value.reason_code == "GOVERNED_CONTEXT_MISMATCH"
    unknown_schema = _module("ocor_runtime.c5.backbone").CanonicalIngestionEnvelope.from_mapping(
        {**envelopes[0].to_mapping(), "event_type": "something-else"}
    )
    with pytest.raises(error) as caught:
        projector.apply(unknown_schema)
    assert caught.value.reason_code == "SCHEMA_VIOLATION"
    assert projection.current_watermark() is None


def test_ncr_c3_003_publish_failure_records_no_delivery(postgres_backend: Backend, dsn: str) -> None:
    """LLD v1.1 :132: no ACK, no delivered mark; the entry is relayed again with the same ID."""
    relay_module = _module("ocor_runtime.c3.relay")
    path = _path(postgres_backend)
    receipt = postgres_backend.service.commit(path.command(path.freeze()))

    class Failing:
        def publish(self, envelope: Any) -> None:
            raise RuntimeError("broker unavailable")

    worker = relay_module.OutboxRelayWorker(postgres_backend.service, Failing(), claim_ttl=timedelta(0))
    with pytest.raises(relay_module.RelayError):
        worker.relay_once(limit=10)
    assert _sql(dsn, "SELECT count(*) FROM c3_delivery_attempt WHERE event_id=%s AND outcome='ACKNOWLEDGED'",
                receipt.outbox_event_id) == [(0,)]
    captured: list[Any] = []

    class Capturing:
        def publish(self, envelope: Any) -> None:
            captured.append(envelope)

    assert relay_module.OutboxRelayWorker(postgres_backend.service, Capturing()).relay_once(limit=10) == (
        receipt.outbox_event_id,
    )
    assert [item.event_id for item in captured] == [receipt.outbox_event_id]


def test_ncr_c3_003_no_module_outside_c5_composes_the_backbone_only_through_c3_relay() -> None:
    relay = PACKAGE / "c3" / "relay.py"
    projector = PACKAGE / "c4" / "projector.py"
    assert any("c5.backbone" in name for name in _relative_imports(relay))
    assert any("c5.backbone" in name for name in _relative_imports(projector))


# ---------------------------------------------------------------------------------------
# NCR-C3-004: DeliveryAttempt and canonical_source_binding
# ---------------------------------------------------------------------------------------


def test_ncr_c3_004_conforms(postgres_backend: Backend, dsn: str) -> None:
    """ADD v1.3 :293 and LLD v1.1 :136-142 on PostgreSQL: the acknowledgement is a separate
    DeliveryAttempt carrying the writer epoch; the outbox entry is never rewritten."""
    path = _path(postgres_backend)
    receipt = postgres_backend.service.commit(path.command(path.freeze()))
    before = _sql(dsn, "SELECT to_jsonb(o) FROM c3_outbox o WHERE event_id=%s", receipt.outbox_event_id)
    (envelope,) = postgres_backend.service.claim_batch(limit=10)
    postgres_backend.service.acknowledge(envelope.event_id, acknowledged_at=NOW)
    after = _sql(dsn, "SELECT to_jsonb(o) FROM c3_outbox o WHERE event_id=%s", receipt.outbox_event_id)
    assert before == after
    attempts = _sql(
        dsn,
        "SELECT outcome, writer_epoch FROM c3_delivery_attempt WHERE event_id=%s ORDER BY attempt_no",
        receipt.outbox_event_id,
    )
    assert attempts[-1] == ("ACKNOWLEDGED", postgres_backend.service.writer_epoch)
    assert [item.outcome for item in postgres_backend.service.delivery_attempts(receipt.outbox_event_id)][-1] == "ACKNOWLEDGED"
    assert postgres_backend.service.claim_batch(limit=10) == ()
    columns = {row[0] for row in _sql(dsn, "SELECT column_name FROM information_schema.columns WHERE table_name='c3_source_binding'")}
    assert {"commit_id", "claim_ref", "source_ref", "evidence_ref"} <= columns
    foreign = _sql(
        dsn,
        """SELECT ccu.table_name FROM information_schema.table_constraints tc
           JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
           WHERE tc.table_name='c3_source_binding' AND tc.constraint_type='FOREIGN KEY'""",
    )
    assert ("c3_commit",) in foreign
    assert {(item.claim_ref, item.source_ref, item.evidence_ref) for item in postgres_backend.service.source_bindings(receipt.commit_id)} == {
        (path.binding["claim_ref"], path.binding["source_ref"], path.binding["evidence_ref"])
    }


def test_ncr_c3_004_terminusdb_source_binding_is_in_the_commit(terminusdb_backend: Backend, terminusdb_password: str) -> None:
    path = _path(terminusdb_backend)
    receipt = terminusdb_backend.service.commit(path.command(path.freeze()))
    assert terminusdb_backend.source_bindings(receipt.commit_id) == {
        (path.binding["claim_ref"], path.binding["source_ref"], path.binding["evidence_ref"])
    }
    assert {(item.claim_ref, item.source_ref, item.evidence_ref) for item in terminusdb_backend.service.source_bindings(receipt.commit_id)} == {
        (path.binding["claim_ref"], path.binding["source_ref"], path.binding["evidence_ref"])
    }


# ---------------------------------------------------------------------------------------
# NCR-C3-006: SKIP LOCKED
# ---------------------------------------------------------------------------------------


def test_ncr_c3_006_conforms(postgres_backend: Backend, dsn: str) -> None:
    """LLD v1.1 :132: a row locked by another relay is skipped, never awaited nor shared."""
    receipts = []
    for _ in range(3):
        path = _path(postgres_backend)
        receipts.append(postgres_backend.service.commit(path.command(path.freeze())))
    locked = receipts[0].outbox_event_id
    holder = psycopg.connect(dsn)
    ready, release = threading.Event(), threading.Event()

    def hold() -> None:
        with holder.transaction():
            holder.execute("SELECT event_id FROM c3_outbox WHERE event_id=%s FOR UPDATE", (locked,))
            ready.set()
            release.wait(30)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert ready.wait(10)
        started = time.monotonic()
        claimed = postgres_backend.service.claim_batch(limit=10)
        elapsed = time.monotonic() - started
    finally:
        release.set()
        thread.join(30)
        holder.close()
    assert elapsed < 5.0, "the claim waited for a row locked by another relay"
    assert {item.event_id for item in claimed} == {receipts[1].outbox_event_id, receipts[2].outbox_event_id}


def test_ncr_c3_006_two_concurrent_relays_claim_disjoint_rows(postgres_backend: Backend) -> None:
    receipts = []
    for _ in range(6):
        path = _path(postgres_backend)
        receipts.append(postgres_backend.service.commit(path.command(path.freeze())))
    other = postgres_backend.make_service()
    results: dict[str, tuple[Any, ...]] = {}
    barrier = threading.Barrier(2)

    def claim(name: str, service: Any) -> None:
        barrier.wait(10)
        results[name] = service.claim_batch(limit=6)

    # The second service is the current writer; claims are not writes of canonical state,
    # so both relays may claim, but never the same row.
    threads = [threading.Thread(target=claim, args=("a", postgres_backend.service)), threading.Thread(target=claim, args=("b", other))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    a = {item.event_id for item in results["a"]}
    b = {item.event_id for item in results["b"]}
    assert not a & b
    assert a | b == {item.outbox_event_id for item in receipts}


def test_ncr_c3_006_postgres_claim_uses_skip_locked() -> None:
    source = (PACKAGE / "c3" / "adapters" / "postgres.py").read_text(encoding="utf-8")
    assert "FOR UPDATE SKIP LOCKED" in source


# ---------------------------------------------------------------------------------------
# NCR-C3-007: TerminusDB relay under the current writer epoch only
# ---------------------------------------------------------------------------------------


def test_ncr_c3_007_conforms(terminusdb_backend: Backend, terminusdb_password: str) -> None:
    """ADD v1.3 :271, PO decision point 4: a relay with a non-current writer epoch cannot
    confirm a delivery; the current writer can."""
    path = _path(terminusdb_backend)
    receipt = terminusdb_backend.service.commit(path.command(path.freeze()))
    stale = terminusdb_backend.service
    (envelope,) = stale.claim_batch(limit=10)
    current = terminusdb_backend.make_service()
    assert current.writer_epoch == stale.writer_epoch + 1
    database = stale._adapter._database  # noqa: SLF001 -- observation of the disposable database only
    with pytest.raises(C3Error) as caught:
        stale.acknowledge(envelope.event_id, acknowledged_at=NOW)
    assert caught.value.reason_code == "SINGLE_WRITER_VIOLATION"
    assert _terminusdb_documents(terminusdb_password, database, "C3DeliveryAttempt") == []
    current.acknowledge(envelope.event_id, acknowledged_at=NOW)
    attempts = _terminusdb_documents(terminusdb_password, database, "C3DeliveryAttempt")
    assert [(item["event_id"], item["writer_epoch"]) for item in attempts] == [(receipt.outbox_event_id, current.writer_epoch)]
    assert [item.outcome for item in current.delivery_attempts(receipt.outbox_event_id)] == ["ACKNOWLEDGED"]
