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
import contextlib
import functools
import hashlib
import http.server
import importlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import psycopg
import pytest
import c4_projection_fixture
import c6_action_fixture

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
# ADD v1.3 :408-411: a ``*_marking_ref`` is ``urn:sha256:<marking_digest>`` of a resolvable
# ``marking`` object; the digest covers the RFC 8785 bytes of the object without its own digest.
MARKING = {
    "scheme_id": "urn:ocor:marking-scheme:rem0050",
    "labels": ["RESTRICTED"],
    "mandatory_markings": [],
    "caveats": [],
    "dissemination_controls": [],
    "permitted_purposes": ["rem0050-c3-admission"],
    "handling_instructions": [],
}
DIGEST_MARKING = "urn:sha256:" + hashlib.sha256(canonical_bytes(MARKING)).hexdigest()
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


ASSESS = "urn:ocor:action-type:rem0050:assess"


@functools.cache
def _engine_world() -> Any:
    """The signed ActionType catalog, Human Gate and Authority of the engine cases, created on
    first use; the assessment is an R2_CONTROLLED canonical mutation."""
    world = c6_action_fixture.ActionWorld(now=NOW, release=RELEASE)
    world.action_type(ASSESS, risk="R2_CONTROLLED", capability="act:assess")
    return world


def _engine_fixture(service: Any, records: RecordStore, fence: Fence, clock: InMemoryTrustedClock) -> tuple[Any, Any, Any]:
    from ocor_runtime.c7_emission import EmissionFence

    engine_module = _module("ocor_runtime.c6.engine")
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
    # NCP-U07 (OCOR-DEV-REM-0053): the engine composes G-CONTRACT, the Human Gate and G-DECISION
    # (NCR-C6-001, NCR-C6-002); _engine_world() signs the ActionType, the Approval and the Decision.
    world = _engine_world()
    engine = world.engine(commit_port=service, relay=EmissionFence(), canonical_path=path)
    # NCR-C6-004: the signed CapabilityLease of each emission attempt, at most PT5S.
    return engine_module, engine, world


def _assessment(action_id: str, aggregate: str) -> Any:
    """The R2_CONTROLLED assessment of an aggregate, pinned to its signed ActionType."""
    world = _engine_world()
    return world.proposal(
        world.catalog.action_type(ASSESS),
        action_id=action_id,
        proposer="analyst-1",
        target=aggregate,
        governed_context_digest=_context().digest(),
    )


def test_ncr_c3_002_c6_engine_commits_through_the_c3_governed_path(postgres_backend: Backend, dsn: str) -> None:
    """The engine freezes and signs the GatePackage, Decision and Authority it sends to C3;
    C3 admits the command; a retry with the same idempotency key does not duplicate (FR-008)."""
    engine_module, engine, authority = _engine_fixture(
        postgres_backend.service, postgres_backend.records, postgres_backend.fence, postgres_backend.clock
    )
    suffix = uuid.uuid4().hex[:8]
    aggregate = f"urn:ocor:mission-object:rem0050:engine:{suffix}"
    proposal = _assessment(f"urn:ocor:action:rem0050:{suffix}", aggregate)
    evidence = GovernedPath(postgres_backend.records, postgres_backend.fence, postgres_backend.clock, aggregate_ref=aggregate)
    approval = _engine_world().approval_set(proposal)
    decision = _engine_world().decide(proposal, approval, rationale="assessed")
    delivered: list[Any] = []

    def run() -> Any:
        lease = authority.lease(proposal, decision)
        return engine.execute(proposal, lease=lease, approval=approval, decision=decision, sink=delivered.append, at=NOW,
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
    # ADD v1.3 :2853 (NCR-C6-005, realigned with RED): every send crosses the EMISSION-FENCE, so a
    # confirmed action instance is not sent to C3 again; the retry returns its confirmed outcome.
    assert second == first
    assert postgres_backend.revision(aggregate) == 1


def test_ncr_c3_002_c6_denial_reaches_no_canonical_commit(postgres_backend: Backend) -> None:
    engine_module, engine, authority = _engine_fixture(
        postgres_backend.service, postgres_backend.records, postgres_backend.fence, postgres_backend.clock
    )
    aggregate = f"urn:ocor:mission-object:rem0050:denied:{uuid.uuid4().hex[:8]}"
    proposal = _assessment(f"urn:ocor:action:rem0050:{uuid.uuid4().hex[:8]}", aggregate)
    lease = authority.lease(proposal)
    approval = _engine_world().approval_set(proposal)
    rejected = _engine_world().decide(proposal, approval, accepted=False, rationale="not supported")
    with pytest.raises(engine_module.GovernedActionError) as caught:
        engine.execute(proposal, lease=lease, approval=approval, decision=rejected, sink=lambda event: None, at=NOW,
                       evidence_refs=("urn:ocor:evidence:none",), claim_source_bindings=())
    assert caught.value.reason_code == "DECISION_REJECTED"
    assert postgres_backend.revision(aggregate) == 0


def test_ncr_c3_002_c8_run_state_is_the_run_ledger_not_canonical_state(postgres_backend: Backend, dsn: str) -> None:
    """ADD v1.3 :276: C8 keeps AgentRun state in the PostgreSQL Run Ledger; it never
    produces a canonical mutation (ADD v1.3 :342)."""
    from ocor_runtime.c6_capabilities import CapabilityAuthority

    _module("ocor_runtime.c8.orchestrator")
    ledger_module = _module("ocor_runtime.c8.adapters.postgres_ledger")
    ledger = ledger_module.PostgresRunLedger(dsn)
    ledger.initialize()
    authority = CapabilityAuthority(issuer="ocor-c8-rem0050-authority")
    # OCOR-DEV-REM-0058 (NCP-U10) case-3 adaptation: the orchestrator is built with the Coordination
    # Kernel of a started team run (LLD v1.1 :183) and the task is proposed before it is assigned;
    # the assertions are unchanged.
    from c8_orchestrator_fixture import NOW as TEAM_NOW
    from c8_orchestrator_fixture import TeamWorld, caller

    team = TeamWorld(dsn, authority=authority, ledger=ledger)
    orchestrator: Any = team.orchestrator
    task = f"task-rem0050-{uuid.uuid4().hex[:8]}"
    team.propose(task)
    lease = authority.issue(subject="team-lead-1", capabilities=["agent:assign"], resources=["agent-1"], issued_at=TEAM_NOW,
                            ttl=timedelta(hours=1))
    commits = postgres_backend.commits()
    orchestrator.assign(task, "agent-1", capability="act:do-thing", lease=lease, assigned_by="team-lead-1", at=TEAM_NOW,
                        **caller("team-lead-1"))
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
    "governed_context",
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
    assert payload["governed_context"] == path.context.to_mapping()
    assert payload["ontology_release_digest"] == RELEASE
    assert payload["state"] == {"status": "ASSESSED"}
    assert payload["state_digest"] == canonical_digest({"status": "ASSESSED"})
    assert envelope.payload_digest == canonical_digest(payload)


RELAY_PRINCIPAL = "urn:ocor:principal:c3-outbox-relay"
RELAY_KEY = Ed25519SigningKey.from_seed(hashlib.sha256(b"rem0050-relay-key").digest())
PROJECTOR_PRINCIPAL = "urn:ocor:principal:c4-projector"
C5_AUDIT_KEY = Ed25519SigningKey.from_seed(hashlib.sha256(b"rem0050-c5-audit-key").digest())
CANONICAL_EVENT_TYPE = "urn:ocor:event-type:canonical-state-committed"


class Markings:
    """Explicit test port of the marking resolution (``GetProvenance`` in production)."""

    def resolve(self, marking_ref: str) -> dict[str, Any]:
        if marking_ref != DIGEST_MARKING:
            raise LookupError("unknown marking")
        return {**MARKING, "marking_digest": DIGEST_MARKING.removeprefix("urn:")}


class PermitAll:
    """Explicit test port of the C5 policy port: every publish, delivery and replay permitted."""

    def _permit(self) -> Any:
        return _module("ocor_runtime.c5.policy").PolicyDecision(allowed=True, reason_code="PERMITTED")

    def authorize_publish(self, principal: str, envelope: Any) -> Any:
        return self._permit()

    def authorize_delivery(self, principal: str, subscription_id: str, envelope: Any) -> Any:
        return self._permit()

    def authorize_replay(self, principal: str, request: Any) -> Any:
        return self._permit()


def _relay_signer() -> Any:
    return _module("ocor_runtime.c5.envelope").ProducerSigner(RELAY_PRINCIPAL, RELAY_KEY)


def _relay_worker(service: Any, publisher: Any, **values: Any) -> Any:
    return _module("ocor_runtime.c3.relay").OutboxRelayWorker(
        service, publisher, signer=_relay_signer(), principal=RELAY_PRINCIPAL, markings=Markings(), **values
    )


def _relayed_context_ref() -> str:
    """The GovernedContext of the relayed events, built here from ADD v1.3 :197 and :844: the
    commit context with the relay's transport principal appended as effective principal."""
    context = _context()
    return dataclass_replace(
        context, effective_principal_id=RELAY_PRINCIPAL, actor_chain=(*context.actor_chain, RELAY_PRINCIPAL)
    ).digest()


@dataclass
class C5Rig:
    """The C5 backbone composed on the real broker of the qualification tool and PostgreSQL."""

    backbone: Any

    def publish(self, signed: Any, *, transport_principal: str) -> Any:
        return self.backbone.publish(signed, transport_principal=transport_principal)

    def consume(self, count: int) -> list[Any]:
        """The first ``count`` relayed events, delivered through the port ``Subscribe``."""
        pin = _module("ocor_runtime.c3.relay").PAYLOAD_SCHEMA_PIN
        contract = {
            "subscription_contract_id": "urn:ocor:subscription-contract:rem0050-projector",
            "version": "1.0.0",
            "contract_digest": "sha256:" + "f" * 64,
            "governed_context_ref": _relayed_context_ref(),
            "event_type_refs": [CANONICAL_EVENT_TYPE],
            "delivery": {"semantics": "AT_LEAST_ONCE", "consumer_must_deduplicate": True, "dedup_key": "event_id"},
            "ordering": {"guarantee": "PER_ORDERING_KEY", "ordering_key_field": "ordering_key"},
            "filter": {"filter_contract_id": "urn:ocor:filter:canonical-state", "arbitrary_predicates_allowed": False},
            "payload_schema": {"schema_id": pin["schema_id"], "version": pin["schema_version"], "digest": pin["schema_digest"]},
            "marking_policy": {"propagate_marking": True, "redact_unauthorized": True, "declare_redactions": True},
            "replay": {"replay_allowed": False, "cursor_opaque": True, "authorization_required": True},
            "error_codes": ["POLICY_DENIED", "REPLAY_DENIED", "CURSOR_EXPIRED", "SCHEMA_VIOLATION"],
        }
        subscription = self.backbone.subscribe(contract, principal=PROJECTOR_PRINCIPAL)
        return list(self.backbone.poll(subscription, cursor=None, max_records=count, timeout_s=20).events)


@pytest.fixture
def kafka(dsn: str) -> Iterator[Any]:
    from c5_kafka_qualification import QualificationKafkaBroker
    from ocor_runtime.audit import AuditSigner, PostgresAuditLog

    topic = f"ocor.rem0050.canonical.{uuid.uuid4().hex[:8]}"
    schema = f"ocor_rem0050_c5_{uuid.uuid4().hex[:8]}"
    broker, _container, volume = QualificationKafkaBroker.provision(topic)
    try:
        registry = _module("ocor_runtime.c5.schema").SchemaRegistry()
        _module("ocor_runtime.c3.relay").register_canonical_state_committed(registry)
        audit = PostgresAuditLog(dsn, schema=f"{schema}_audit", signer=AuditSigner(key=C5_AUDIT_KEY, keyid="c5-audit"))
        audit.initialize()
        store = _module("ocor_runtime.c5.adapters.postgres").PostgresC5Store(dsn, schema=schema)
        store.initialize()
        backbone = _module("ocor_runtime.c5.backbone").CanonicalEventBackbone(
            journal=_module("ocor_runtime.c5.adapters.kafka").KafkaJournal(broker.bootstrap_servers, topic),
            registry=registry,
            keyring=_module("ocor_runtime.c5.envelope").ProducerKeyring({RELAY_PRINCIPAL: RELAY_KEY.public_key}),
            policy=PermitAll(),
            audit=audit,
            store=store,
        )
        yield C5Rig(backbone)
    finally:
        broker.destroy(volume)
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            connection.execute(f'DROP SCHEMA IF EXISTS "{schema}_audit" CASCADE')


@pytest.fixture
def projection() -> Iterator[Any]:
    value = c4_projection_fixture.projection()
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

    worker = relay_module.OutboxRelayWorker(
        postgres_backend.service, kafka, signer=_relay_signer(), principal=RELAY_PRINCIPAL, markings=Markings()
    )
    published = worker.relay_once(limit=10)
    assert published == (r1.outbox_event_id, r2.outbox_event_id)
    attempts = _sql(dsn, "SELECT event_id, outcome FROM c3_delivery_attempt WHERE outcome='ACKNOWLEDGED' ORDER BY event_id")
    assert {row[0] for row in attempts} == {r1.outbox_event_id, r2.outbox_event_id}
    assert worker.relay_once(limit=10) == ()

    records = kafka.consume(2)
    assert [record.envelope["source"]["source_record_id"] for record in records] == [r1.outbox_event_id, r2.outbox_event_id]
    assert {record.envelope.event_type_id for record in records} == {CANONICAL_EVENT_TYPE}
    assert [record.envelope.aggregate["expected_revision"] for record in records] == [1, 2]

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
    envelopes = [
        relay_module.canonical_event(
            item, signer=_relay_signer(), principal=RELAY_PRINCIPAL, markings=Markings(), ingest_time=NOW
        ).envelope
        for item in postgres_backend.service.claim_batch(limit=10)
    ]
    assert [item.aggregate["expected_revision"] for item in envelopes] == [1, 2]
    projector = projector_module.CanonicalStateProjector(projection, release_digest=RELEASE)
    error = projector_module.ProjectorError

    with pytest.raises(error) as caught:
        projector.apply(envelopes[1])
    assert caught.value.reason_code == "OUT_OF_ORDER"
    with pytest.raises(error) as caught:
        projector_module.CanonicalStateProjector(projection, release_digest=OTHER_RELEASE).apply(envelopes[0])
    assert caught.value.reason_code == "RELEASE_MISMATCH"
    tampered = _module("ocor_runtime.c5.backbone").CanonicalIngestionEnvelope.from_mapping(
        {**envelopes[0].to_mapping(), "governed_context_digest": "sha256:" + "6" * 64}
    )
    with pytest.raises(error) as caught:
        projector.apply(tampered)
    assert caught.value.reason_code == "GOVERNED_CONTEXT_MISMATCH"
    unknown_schema = _module("ocor_runtime.c5.backbone").CanonicalIngestionEnvelope.from_mapping(
        {**envelopes[0].to_mapping(), "event_type_id": "urn:ocor:event-type:something-else"}
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
        def publish(self, envelope: Any, *, transport_principal: str) -> None:
            raise RuntimeError("broker unavailable")

    worker = _relay_worker(postgres_backend.service, Failing(), claim_ttl=timedelta(0))
    with pytest.raises(relay_module.RelayError):
        worker.relay_once(limit=10)
    assert _sql(dsn, "SELECT count(*) FROM c3_delivery_attempt WHERE event_id=%s AND outcome='ACKNOWLEDGED'",
                receipt.outbox_event_id) == [(0,)]
    captured: list[Any] = []

    class Capturing:
        def publish(self, envelope: Any, *, transport_principal: str) -> None:
            captured.append(envelope.envelope)

    assert _relay_worker(postgres_backend.service, Capturing()).relay_once(limit=10) == (
        receipt.outbox_event_id,
    )
    assert [item["source"]["source_record_id"] for item in captured] == [receipt.outbox_event_id]


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


# ---------------------------------------------------------------------------------------
# Governed path for the consumer suites (construction adaptations of NCP-U04)
# ---------------------------------------------------------------------------------------

CONSUMER_KEYID = "urn:ocor:key:c6:consumer-suites"
CONSUMER_KEY = Ed25519SigningKey.from_seed(hashlib.sha256(b"ocor-c6-consumer-suite-key").digest())


class GovernedC3:
    """The C6 side of the governed canonical commit for the C3 consumer suites: the
    in-memory governance record store, the mutation fence and the C6 signer. A suite
    builds its commands with ``command`` and its services with ``admission``; the
    precondition and invariant IDs it declares are registered as bindings without a
    state condition (the suites bind them only as identifiers)."""

    def __init__(
        self,
        *,
        release: str,
        preconditions: tuple[str, ...] = (),
        invariants: tuple[str, ...] = (),
        stop_epoch: int = 0,
        now: datetime | None = None,
    ) -> None:
        admission = _module("ocor_runtime.c3.admission")
        self.records = admission.InMemoryGovernanceRecordStore()
        self.fence = admission.InMemoryMutationFence(stop_epoch=stop_epoch, active_release_digest=release)
        self.clock = InMemoryTrustedClock(now or datetime.now(UTC).replace(microsecond=0))
        self.preconditions = tuple(preconditions)
        self.invariants = tuple(invariants)
        self._release = release

    def command(self, fields: Mapping[str, Any]) -> GovernedCanonicalCommitCommand:
        admission = _module("ocor_runtime.c3.admission")
        values = dict(fields)
        values.pop("gate_package_digest", None)
        # A Decision and an Authority bind exactly one GatePackage: refs that the suites
        # reuse across different commands are made unique per command content.
        suffix = canonical_digest(
            _thaw({key: value for key, value in values.items() if key not in ("decision_ref", "authority_ref")})
        )[-16:]
        values["decision_ref"] = f"{values['decision_ref']}:{suffix}"
        values["authority_ref"] = f"{values['authority_ref']}:{suffix}"
        now = self.clock.now()
        for evidence_ref in values["evidence_refs"]:
            self.records.add_evidence(
                EvidenceRecord(
                    evidence_id=evidence_ref,
                    content_digest="urn:sha256:" + hashlib.sha256(evidence_ref.encode()).hexdigest(),
                    source_ref="urn:ocor:source:consumer-suite",
                    acquired_at=now - timedelta(minutes=1),
                    acquirer_principal_id="urn:ocor:principal:consumer-suite",
                    method_ref="urn:ocor:method:consumer-suite",
                    chain_of_custody=("urn:ocor:custody:consumer-suite",),
                    marking_ref=DIGEST_MARKING,
                    retention_until=now + timedelta(days=365),
                )
            )
        return admission.issue_governed_command(
            values,
            key=CONSUMER_KEY,
            keyid=CONSUMER_KEYID,
            sink=self.records,
            fence=self.fence,
            issued_at=now,
            validity=timedelta(hours=12),
        )

    def add_evidence(self, evidence_refs: Any) -> None:
        """Registers an Evidence record for each reference, as C3 admission requires, for
        a suite whose commands C6 issues outside ``command``."""
        now = self.clock.now()
        for evidence_ref in evidence_refs:
            self.records.add_evidence(
                EvidenceRecord(
                    evidence_id=evidence_ref,
                    content_digest="urn:sha256:" + hashlib.sha256(evidence_ref.encode()).hexdigest(),
                    source_ref="urn:ocor:source:consumer-suite",
                    acquired_at=now - timedelta(minutes=1),
                    acquirer_principal_id="urn:ocor:principal:consumer-suite",
                    method_ref="urn:ocor:method:consumer-suite",
                    chain_of_custody=("urn:ocor:custody:consumer-suite",),
                    marking_ref=DIGEST_MARKING,
                    retention_until=now + timedelta(days=365),
                )
            )

    def governed_context(self, *, purpose: str) -> GovernedContext:
        return GovernedContext.from_mapping({**_context(release=self._release).to_mapping(), "purpose": purpose})

    def engine_path(self, *, aggregate_type: str, governed_context: GovernedContext) -> Any:
        """The C6 ``CanonicalCommitPath`` of an engine suite, signing with the suite key;
        every action commits with one registered Evidence and claim/source binding."""
        evidence_ref = "urn:ocor:evidence:consumer-suite:engine"
        binding = {
            "claim_ref": "urn:ocor:claim:consumer-suite:engine",
            "source_ref": "urn:ocor:source:consumer-suite:engine",
            "evidence_ref": evidence_ref,
        }
        now = self.clock.now()
        self.records.add_evidence(
            EvidenceRecord(
                evidence_id=evidence_ref,
                content_digest="urn:sha256:" + hashlib.sha256(evidence_ref.encode()).hexdigest(),
                source_ref=binding["source_ref"],
                acquired_at=now - timedelta(minutes=1),
                acquirer_principal_id="urn:ocor:principal:consumer-suite",
                method_ref="urn:ocor:method:consumer-suite",
                chain_of_custody=("urn:ocor:custody:consumer-suite",),
                marking_ref=DIGEST_MARKING,
                retention_until=now + timedelta(days=365),
            )
        )
        return _module("ocor_runtime.c6.engine").CanonicalCommitPath(
            signing_key=CONSUMER_KEY,
            keyid=CONSUMER_KEYID,
            records=self.records,
            fence=self.fence,
            clock=self.clock,
            aggregate_type=aggregate_type,
            governed_context=governed_context,
            precondition_bindings=self.preconditions,
            invariant_bindings=self.invariants,
            evidence=lambda proposal: ((evidence_ref,), (binding,)),
        )

    def admission(self) -> Any:
        module = _module("ocor_runtime.c3.admission")

        def declared(state: Mapping[str, Any]) -> bool:
            return True

        return module.CommitAdmission(
            records=self.records,
            fence=self.fence,
            trusted_keys={CONSUMER_KEYID: CONSUMER_KEY.public_key},
            clock=self.clock,
            preconditions={item: declared for item in self.preconditions},
            invariants={item: declared for item in self.invariants},
        )

    def export(self) -> dict[str, Any]:
        """Everything a child process of the same writer needs to admit the commands."""
        return {
            "release": self._release,
            "stop_epoch": self.fence.current_stop_epoch(),
            "now": format_utc_timestamp(self.clock.now()),
            "preconditions": list(self.preconditions),
            "invariants": list(self.invariants),
            "records": [
                {"payload_type": r.payload_type, "payload": _thaw(r.payload), "keyid": r.keyid, "signature": r.signature}
                for r in [*self.records._gate_packages.values(), *self.records._decisions.values(),  # noqa: SLF001
                          *self.records._authorities.values()]  # noqa: SLF001
            ],
            "evidence": [item.to_mapping() for item in self.records._evidence.values()],  # noqa: SLF001
        }

    @classmethod
    def from_export(cls, data: Mapping[str, Any]) -> GovernedC3:
        from ocor_runtime.kernel.canonical import parse_utc_timestamp

        admission = _module("ocor_runtime.c3.admission")
        value = cls(
            release=data["release"],
            preconditions=tuple(data["preconditions"]),
            invariants=tuple(data["invariants"]),
            stop_epoch=data["stop_epoch"],
            now=parse_utc_timestamp(data["now"]),
        )
        for item in data["records"]:
            value.records.publish(admission.SignedGovernanceRecord(**item))
        for item in data["evidence"]:
            value.records.add_evidence(
                EvidenceRecord(
                    evidence_id=item["evidence_id"],
                    content_digest=item["content_digest"],
                    source_ref=item["source_ref"],
                    acquired_at=parse_utc_timestamp(item["acquired_at"]),
                    acquirer_principal_id=item["acquirer_principal_id"],
                    method_ref=item["method_ref"],
                    chain_of_custody=tuple(item["chain_of_custody"]),
                    marking_ref=item["marking_ref"],
                    retention_until=parse_utc_timestamp(item["retention_until"]),
                )
            )
        return value


def test_governed_path_for_consumer_suites_is_admitted_and_exportable(dsn: str) -> None:
    """The consumer-suite path is the governed path: C3 admits its commands, refuses the
    same command once the Authority is revoked, and a child of the same writer admits the
    exported records."""
    governed = GovernedC3(release=RELEASE, preconditions=(PRECONDITION,), invariants=(INVARIANT,))
    service = _module("ocor_runtime.c3.service").PostgresC3Service(dsn, admission=governed.admission())
    service.initialize()
    service.reset()
    path = GovernedPath(RecordStore(), Fence(), InMemoryTrustedClock(NOW), aggregate_ref="urn:ocor:mission-object:rem0050:consumer")
    fields = path.command("urn:sha256:" + "0" * 64).to_mapping()
    command = governed.command(fields)
    assert service.commit(command).to_revision == 1
    child = GovernedC3.from_export(json.loads(json.dumps(governed.export())))
    joined = _module("ocor_runtime.c3.service").PostgresC3Service(dsn, admission=child.admission(), writer_epoch=service.writer_epoch)
    assert joined.commit(command).replayed is True
    governed.records.revoke_authority(command.authority_ref)
    with pytest.raises(C3Error) as caught:
        service.commit(command)
    assert caught.value.reason_code == "AUTHORITY_MISSING"
    service.reset()


# ---------------------------------------------------------------------------------------
# Input robustness of the C3 TerminusDB adapter (PRE-REVIEW-INPUT-ROBUSTNESS): every
# parsing path of a server answer. Positive paths run on the real TerminusDB above.
# ---------------------------------------------------------------------------------------
CANARY = "rem0050-canary-server-body-never-echoed"
TDB = "ocor_runtime.c3.adapters.terminusdb"
RESPONDER_REF = "urn:ocor:mission-object:rem0050:responder"
RESPONDER_EVENT = "urn:ocor:event:rem0050:responder"
RESPONDER_COMMIT = "urn:ocor:commit:rem0050:responder"
RESPONDER_VERSION = "branch:" + "f" * 32
Answer = tuple[int, dict[str, str], bytes] | bytes


def _json_answer(body: object, status: int = 200, headers: Mapping[str, str] | None = None) -> Answer:
    return status, dict(headers or {}), json.dumps(body).encode("utf-8")


class TerminusDBResponder:
    """A local HTTP responder standing in for TerminusDB on the failure paths only:
    well-formed answers by default (the documents of ``documents``, the lists of
    ``lists``), and per route a malformed, hostile or failing answer (status, headers and
    body, or raw bytes on the socket)."""

    def __init__(self) -> None:
        self.documents: dict[str, object] = {}
        self.lists: dict[str, object] = {}
        self.overrides: dict[str, Answer] = {}
        responder = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _answer(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self.close_connection = True
                route, answer = responder.route(self.command, self.path)
                answer = responder.overrides.get(route, answer)
                if isinstance(answer, bytes):
                    self.wfile.write(answer)
                    return
                status, headers, body = answer
                self.send_response(status)
                for name, value in {"Content-Type": "application/json", **headers}.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = _answer
            do_POST = _answer
            do_DELETE = _answer

            def log_message(self, format: str, *args: Any) -> None:
                return None

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def route(self, method: str, raw_path: str) -> tuple[str, Answer]:
        path, _, query = raw_path.partition("?")
        params = urllib.parse.parse_qs(query)
        if path.startswith("/api/woql/"):
            return "woql", _json_answer({"bindings": [{}]})
        if "graph_type" in params:
            return "schema", _json_answer(list(_module(TDB).SCHEMA) if method == "GET" else {})
        if path.startswith("/api/db"):
            return "db", _json_answer([{"path": "admin/rem0050_responder"}] if method == "GET" else {})
        if "/local/branch/" in path:
            return "version", _json_answer([], headers={"TerminusDB-Data-Version": RESPONDER_VERSION})
        if "/local/commit/" in path and "id" in params:
            doc_type = params["id"][0].split("/", 1)[0]
            document = self.documents.get(doc_type)
            if document is None:
                return "document", _json_answer({"api:status": "api:not_found"}, status=404)
            return "document", _json_answer(document)
        if "/local/commit/" in path and "type" in params:
            return "list", _json_answer(self.lists.get(params["type"][0], []))
        return "other", _json_answer({}, status=400)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def tdb_responder() -> Iterator[TerminusDBResponder]:
    value = TerminusDBResponder()
    try:
        yield value
    finally:
        value.close()


def _responder_adapter(responder: TerminusDBResponder) -> Any:
    return _module(TDB).TerminusDBC3Adapter(
        url=responder.url, password="rem0050-responder-synthetic", database="rem0050_responder", timeout=5.0
    )


def _fence_document(**values: object) -> dict[str, Any]:
    key = _module(TDB)._key("c3-canonical")
    return {"@type": "C3WriterFence", "key": key, "boundary": "c3-canonical", "writer_epoch": 1, "writer_id": "w", **values}


def _aggregate_document(**values: object) -> dict[str, Any]:
    state = {"status": "ASSESSED"}
    return {
        "@type": "C3Aggregate",
        "key": _module(TDB)._key(TENANT, AGGREGATE_TYPE, RESPONDER_REF),
        "tenant_id": TENANT,
        "aggregate_type": AGGREGATE_TYPE,
        "aggregate_ref": RESPONDER_REF,
        "revision": 1,
        "state_json": canonical_bytes(state).decode("utf-8"),
        "state_digest": canonical_digest(state),
        "commit_id": RESPONDER_COMMIT,
        **values,
    }


def _outbox_entry(**values: object) -> dict[str, Any]:
    payload = {"event": "canonical-state-committed"}
    return {
        "@type": "C3OutboxEntry",
        "key": _module(TDB)._key(RESPONDER_EVENT),
        "event_id": RESPONDER_EVENT,
        "commit_id": RESPONDER_COMMIT,
        "aggregate_ref": RESPONDER_REF,
        "aggregate_revision": 1,
        "payload_json": canonical_bytes(payload).decode("utf-8"),
        "payload_digest": canonical_digest(payload),
        "branch": "main",
        "occurred_at": "2026-11-03T09:00:00Z",
        **values,
    }


def _attempt_document(**values: object) -> dict[str, Any]:
    return {
        "@type": "C3DeliveryAttempt",
        "key": _module(TDB)._key(RESPONDER_EVENT),
        "event_id": RESPONDER_EVENT,
        "outcome": "ACKNOWLEDGED",
        "acknowledged_at": "2026-11-03T09:00:01Z",
        "writer_epoch": 1,
        **values,
    }


def _commit_document(**values: object) -> dict[str, Any]:
    payload = {"event": "canonical-state-committed"}
    return {
        "@type": "C3Commit",
        "key": _module(TDB)._key(RESPONDER_COMMIT),
        "commit_id": RESPONDER_COMMIT,
        "command_id": "urn:ocor:command:rem0050:responder",
        "command_digest": "urn:sha256:" + "1" * 64,
        "tenant_id": TENANT,
        "aggregate_type": AGGREGATE_TYPE,
        "aggregate_ref": RESPONDER_REF,
        "from_revision": 0,
        "to_revision": 1,
        "state_digest": "urn:sha256:" + "2" * 64,
        "idempotency_key": "rem0050-responder",
        "outbox_event_id": RESPONDER_EVENT,
        "outbox_payload_json": canonical_bytes(payload).decode("utf-8"),
        "outbox_payload_digest": canonical_digest(payload),
        "branch": "main",
        "committed_at": "2026-11-03T09:00:00Z",
        "writer_epoch": 1,
        **values,
    }


def _binding_document(**values: object) -> dict[str, Any]:
    return {
        "@type": "C3Idempotency",
        "key": _module(TDB)._key(TENANT, AGGREGATE_TYPE, RESPONDER_REF, "rem0050-responder"),
        "tenant_id": TENANT,
        "aggregate_type": AGGREGATE_TYPE,
        "aggregate_ref": RESPONDER_REF,
        "idempotency_key": "rem0050-responder",
        "command_digest": "urn:sha256:" + "1" * 64,
        "commit_id": RESPONDER_COMMIT,
        **values,
    }


def _replay(adapter: Any) -> Any:
    adapter.join_writer(1)
    return adapter.commit_transaction(
        tenant_id=TENANT,
        aggregate_type=AGGREGATE_TYPE,
        aggregate_ref=RESPONDER_REF,
        idempotency_key="rem0050-responder",
        command_id="urn:ocor:command:rem0050:responder",
        command_digest="urn:sha256:" + "1" * 64,
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
        decision_ref="urn:ocor:decision:rem0050:responder",
        authority_ref="urn:ocor:authority:rem0050:responder",
        evidence_refs=(),
        claim_source_bindings=(),
        governed_context_digest="urn:sha256:" + "3" * 64,
        gate_package_digest="urn:sha256:" + "4" * 64,
        branch="main",
        check_state=lambda current, new: None,
        event_payload=lambda commit_id, before, after, state, digest: {"event": "canonical-state-committed"},
    )


def _joined(call: Callable[[Any], Any]) -> Callable[[Any], Any]:
    def run(adapter: Any) -> Any:
        adapter.join_writer(1)
        return call(adapter)

    return run


OPERATIONS: dict[str, Callable[[Any], Any]] = {
    "snapshot": lambda adapter: adapter.read_snapshot(TENANT, AGGREGATE_TYPE, RESPONDER_REF),
    "claim": lambda adapter: adapter.claim_outbox_batch(limit=10),
    "attempts": lambda adapter: adapter.delivery_attempts(RESPONDER_EVENT),
    "bindings": lambda adapter: adapter.source_bindings(RESPONDER_COMMIT),
    "acquire": lambda adapter: adapter.acquire_writer(),
    "initialize": lambda adapter: adapter.initialize(),
    "drop": lambda adapter: adapter.drop(),
    "replay": _replay,
    "acknowledge": _joined(lambda adapter: adapter.acknowledge_outbox(RESPONDER_EVENT, acknowledged_at=NOW)),
    "reconcile": _joined(lambda adapter: adapter.reconcile(limit=5)),
}
NESTED = ("[" * 100_000 + "]" * 100_000).encode("ascii")
CANARY_BODY = json.dumps({"api:error": {"@type": "api:" + CANARY}, "api:message": CANARY}).encode("utf-8")
# (case, operation, documents, lists, overrides, reason code)
TDB_MALFORMED: list[tuple[str, str, dict[str, object], dict[str, object], dict[str, Answer], str]] = [
    ("bad-status-line", "snapshot", {}, {}, {"version": f"GARBAGE {CANARY}\r\n\r\n".encode()}, "BACKEND_UNAVAILABLE"),
    ("connection-closed", "snapshot", {}, {}, {"version": b""}, "BACKEND_UNAVAILABLE"),
    ("not-utf8", "snapshot", {}, {}, {"version": (200, {}, b"\xff\xfe" + CANARY.encode())}, "BACKEND_ERROR"),
    ("not-json", "snapshot", {}, {}, {"version": (200, {}, b"{" + CANARY.encode())}, "BACKEND_ERROR"),
    ("two-prefix-lines", "snapshot", {}, {}, {"version": (200, {}, b"a\nb\n{}")}, "BACKEND_ERROR"),
    ("nan-constant", "snapshot", {}, {}, {"version": (200, {"TerminusDB-Data-Version": RESPONDER_VERSION}, b"[NaN]")}, "BACKEND_ERROR"),
    ("nesting-beyond-depth", "snapshot", {}, {}, {"version": (200, {}, NESTED)}, "BACKEND_ERROR"),
    ("error-body-echo", "snapshot", {}, {}, {"version": (500, {}, CANARY_BODY)}, "BACKEND_ERROR"),
    ("data-version-missing", "snapshot", {}, {}, {"version": (200, {}, b"[]")}, "BACKEND_ERROR"),
    ("data-version-foreign", "snapshot", {}, {}, {"version": (200, {"TerminusDB-Data-Version": "commit:abc"}, b"[]")}, "BACKEND_ERROR"),
    ("data-version-path", "snapshot", {}, {}, {"version": (200, {"TerminusDB-Data-Version": "branch:../x"}, b"[]")}, "BACKEND_ERROR"),
    ("document-error-echo", "snapshot", {}, {}, {"document": (500, {}, CANARY_BODY)}, "BACKEND_ERROR"),
    ("document-not-object", "snapshot", {}, {}, {"document": _json_answer([CANARY])}, "BACKEND_ERROR"),
    ("document-other-type", "snapshot", {"C3Aggregate": _aggregate_document(**{"@type": "C3Commit"})}, {}, {}, "BACKEND_ERROR"),
    ("document-other-key", "snapshot", {"C3Aggregate": _aggregate_document(key="0" * 64)}, {}, {}, "BACKEND_ERROR"),
    ("revision-text", "snapshot", {"C3Aggregate": _aggregate_document(revision="1")}, {}, {}, "BACKEND_ERROR"),
    ("revision-bool", "snapshot", {"C3Aggregate": _aggregate_document(revision=True)}, {}, {}, "BACKEND_ERROR"),
    ("revision-negative", "snapshot", {"C3Aggregate": _aggregate_document(revision=-1)}, {}, {}, "BACKEND_ERROR"),
    ("revision-missing", "snapshot", {"C3Aggregate": {k: v for k, v in _aggregate_document().items() if k != "revision"}}, {}, {}, "BACKEND_ERROR"),
    ("state-not-json", "snapshot", {"C3Aggregate": _aggregate_document(state_json="{" + CANARY)}, {}, {}, "BACKEND_ERROR"),
    ("state-not-object", "snapshot", {"C3Aggregate": _aggregate_document(state_json="[]")}, {}, {}, "BACKEND_ERROR"),
    ("state-not-text", "snapshot", {"C3Aggregate": _aggregate_document(state_json=7)}, {}, {}, "BACKEND_ERROR"),
    ("state-digest-missing", "snapshot", {"C3Aggregate": _aggregate_document(state_digest=None)}, {}, {}, "BACKEND_ERROR"),
    ("commit-id-empty", "snapshot", {"C3Aggregate": _aggregate_document(commit_id="")}, {}, {}, "BACKEND_ERROR"),
    ("list-error-echo", "claim", {}, {}, {"list": (500, {}, CANARY_BODY)}, "BACKEND_ERROR"),
    ("list-not-array", "claim", {}, {}, {"list": _json_answer({"entries": CANARY})}, "BACKEND_ERROR"),
    ("list-entry-not-object", "claim", {}, {"C3OutboxEntry": [CANARY]}, {}, "BACKEND_ERROR"),
    ("list-entry-other-type", "claim", {}, {"C3OutboxEntry": [_outbox_entry(**{"@type": "C3Commit"})]}, {}, "BACKEND_ERROR"),
    ("entry-branch-not-text", "claim", {}, {"C3OutboxEntry": [_outbox_entry(branch=7)]}, {}, "BACKEND_ERROR"),
    ("entry-revision-zero", "claim", {}, {"C3OutboxEntry": [_outbox_entry(aggregate_revision=0)]}, {}, "BACKEND_ERROR"),
    ("entry-occurred-at-offset", "claim", {}, {"C3OutboxEntry": [_outbox_entry(occurred_at="2026-11-03T09:00:00+01:00")]}, {}, "BACKEND_ERROR"),
    ("entry-payload-missing", "claim", {}, {"C3OutboxEntry": [_outbox_entry(payload_json=None)]}, {}, "BACKEND_ERROR"),
    ("entry-event-id-missing", "claim", {}, {"C3OutboxEntry": [_outbox_entry(event_id=None)]}, {}, "BACKEND_ERROR"),
    ("attempt-event-id-not-text", "claim", {}, {"C3OutboxEntry": [_outbox_entry()], "C3DeliveryAttempt": [_attempt_document(event_id=[])]}, {}, "BACKEND_ERROR"),
    ("attempt-other-event", "attempts", {"C3DeliveryAttempt": _attempt_document(event_id="urn:ocor:event:other")}, {}, {}, "BACKEND_ERROR"),
    ("attempt-other-outcome", "attempts", {"C3DeliveryAttempt": _attempt_document(outcome="FAILED")}, {}, {}, "BACKEND_ERROR"),
    ("attempt-epoch-bool", "attempts", {"C3DeliveryAttempt": _attempt_document(writer_epoch=True)}, {}, {}, "BACKEND_ERROR"),
    ("attempt-epoch-zero", "attempts", {"C3DeliveryAttempt": _attempt_document(writer_epoch=0)}, {}, {}, "BACKEND_ERROR"),
    ("attempt-timestamp-invalid", "attempts", {"C3DeliveryAttempt": _attempt_document(acknowledged_at="2026-13-03T09:00:00Z")}, {}, {}, "BACKEND_ERROR"),
    ("binding-ref-not-text", "bindings", {}, {"C3SourceBinding": [{"@type": "C3SourceBinding", "commit_id": RESPONDER_COMMIT, "claim_ref": 7, "source_ref": "s", "evidence_ref": "e"}]}, {}, "BACKEND_ERROR"),
    ("fence-epoch-text", "acquire", {"C3WriterFence": _fence_document(writer_epoch="1")}, {}, {}, "BACKEND_ERROR"),
    ("fence-epoch-zero", "acquire", {"C3WriterFence": _fence_document(writer_epoch=0)}, {}, {}, "BACKEND_ERROR"),
    ("fence-epoch-bool", "acknowledge", {"C3WriterFence": _fence_document(writer_epoch=True)}, {}, {}, "BACKEND_ERROR"),
    ("woql-without-bindings", "acquire", {}, {}, {"woql": _json_answer({"bindings": CANARY})}, "BACKEND_ERROR"),
    ("woql-error-echo", "acquire", {}, {}, {"woql": (400, {}, CANARY_BODY)}, "BACKEND_ERROR"),
    ("woql-schema-refusal-echo", "acquire", {}, {}, {"woql": _json_answer({"api:error": {"@type": "api:WOQLSchemaCheckFailure"}, "api:message": CANARY}, status=400)}, "BATCH_REJECTED"),
    ("replay-digest-not-text", "replay", {"C3WriterFence": _fence_document(), "C3Idempotency": _binding_document(command_digest=7)}, {}, {}, "BACKEND_ERROR"),
    ("replay-commit-id-missing", "replay", {"C3WriterFence": _fence_document(), "C3Idempotency": _binding_document(commit_id=None)}, {}, {}, "BACKEND_ERROR"),
    ("replay-revisions-not-consecutive", "replay", {"C3WriterFence": _fence_document(), "C3Idempotency": _binding_document(), "C3Commit": _commit_document(to_revision=3)}, {}, {}, "COMMIT_RECEIPT_MISMATCH"),
    ("replay-committed-at-invalid", "replay", {"C3WriterFence": _fence_document(), "C3Idempotency": _binding_document(), "C3Commit": _commit_document(committed_at=CANARY)}, {}, {}, "BACKEND_ERROR"),
    ("aggregate-revision-text", "replay", {"C3WriterFence": _fence_document(), "C3Aggregate": _aggregate_document(revision="0")}, {}, {}, "BACKEND_ERROR"),
    ("ack-entry-branch-not-text", "acknowledge", {"C3WriterFence": _fence_document(), "C3OutboxEntry": _outbox_entry(branch=None)}, {}, {}, "BACKEND_ERROR"),
    ("reconcile-commit-id-missing", "reconcile", {"C3WriterFence": _fence_document()}, {"C3Commit": [_commit_document(commit_id=None)]}, {}, "BACKEND_ERROR"),
    ("reconcile-payload-digest-mismatch", "reconcile", {"C3WriterFence": _fence_document()}, {"C3Commit": [_commit_document(outbox_payload_digest="urn:sha256:" + "9" * 64)]}, {}, "COMMIT_RECEIPT_MISMATCH"),
    ("reconcile-to-revision-text", "reconcile", {"C3WriterFence": _fence_document()}, {"C3Commit": [_commit_document(to_revision="1")]}, {}, "BACKEND_ERROR"),
    ("reconcile-committed-at-invalid", "reconcile", {"C3WriterFence": _fence_document()}, {"C3Commit": [_commit_document(committed_at="yesterday")]}, {}, "BACKEND_ERROR"),
    ("reconcile-binding-commit-not-text", "reconcile", {"C3WriterFence": _fence_document()}, {"C3Commit": [_commit_document()], "C3Idempotency": [_binding_document(commit_id=1)]}, {}, "BACKEND_ERROR"),
    ("databases-error-echo", "initialize", {}, {}, {"db": (500, {}, CANARY_BODY)}, "BACKEND_ERROR"),
    ("databases-entry-not-object", "initialize", {}, {}, {"db": _json_answer([CANARY])}, "BACKEND_ERROR"),
    ("databases-path-not-text", "initialize", {}, {}, {"db": _json_answer([{"path": 7}])}, "BACKEND_ERROR"),
    ("schema-entry-not-object", "initialize", {}, {}, {"schema": _json_answer([CANARY])}, "BACKEND_ERROR"),
    ("schema-foreign-class", "initialize", {}, {}, {"schema": _json_answer([*_module(TDB).SCHEMA, {"@type": "Class", "@id": CANARY}])}, "SCHEMA_MISMATCH"),
    ("drop-error-echo", "drop", {}, {}, {"db": (500, {}, CANARY_BODY)}, "BACKEND_ERROR"),
]


@pytest.mark.parametrize(
    ("case", "operation", "documents", "lists", "overrides", "reason"), TDB_MALFORMED, ids=[item[0] for item in TDB_MALFORMED]
)
def test_terminusdb_adapter_rejects_malformed_or_hostile_answers(
    tdb_responder: TerminusDBResponder,
    case: str,
    operation: str,
    documents: dict[str, object],
    lists: dict[str, object],
    overrides: dict[str, Answer],
    reason: str,
) -> None:
    """Every malformed, hostile or failing server answer is a typed adapter error with a
    stable reason code whose message never echoes the server body."""
    tdb_responder.documents, tdb_responder.lists, tdb_responder.overrides = documents, lists, overrides
    with pytest.raises(_module(TDB).TerminusDBAdapterError) as caught:
        OPERATIONS[operation](_responder_adapter(tdb_responder))
    assert caught.value.reason_code == reason, case
    assert CANARY not in str(caught.value), case


def test_terminusdb_adapter_reads_well_formed_answers(tdb_responder: TerminusDBResponder) -> None:
    """The responder's default answers are well formed, so each negative case above fails
    for its own malformation only (positive controls of the same parsing paths)."""
    adapter = _responder_adapter(tdb_responder)
    assert adapter.read_snapshot(TENANT, AGGREGATE_TYPE, RESPONDER_REF) is None
    tdb_responder.documents = {"C3Aggregate": _aggregate_document()}
    snapshot = adapter.read_snapshot(TENANT, AGGREGATE_TYPE, RESPONDER_REF)
    assert (snapshot.revision, snapshot.state, snapshot.commit_id) == (1, {"status": "ASSESSED"}, RESPONDER_COMMIT)
    tdb_responder.lists = {"C3OutboxEntry": [_outbox_entry(), _outbox_entry(branch="scenario")]}
    (row,) = adapter.claim_outbox_batch(limit=10)
    assert (row.event_id, row.aggregate_revision, row.branch, row.occurred_at) == (
        RESPONDER_EVENT, 1, "main", datetime(2026, 11, 3, 9, 0, 0, tzinfo=UTC)
    )
    tdb_responder.lists["C3DeliveryAttempt"] = [_attempt_document()]
    assert adapter.claim_outbox_batch(limit=10) == ()
    tdb_responder.documents = {"C3DeliveryAttempt": _attempt_document()}
    (attempt,) = adapter.delivery_attempts(RESPONDER_EVENT)
    assert (attempt.outcome, attempt.writer_epoch) == ("ACKNOWLEDGED", 1)
    tdb_responder.lists = {
        "C3SourceBinding": [{"@type": "C3SourceBinding", "commit_id": RESPONDER_COMMIT, "claim_ref": "c", "source_ref": "s", "evidence_ref": "e"}]
    }
    assert [(item.claim_ref, item.source_ref, item.evidence_ref) for item in adapter.source_bindings(RESPONDER_COMMIT)] == [("c", "s", "e")]
    tdb_responder.documents = {"C3WriterFence": _fence_document()}
    assert adapter.acquire_writer() == 2
    tdb_responder.documents = {"C3WriterFence": _fence_document(), "C3Idempotency": _binding_document(), "C3Commit": _commit_document()}
    outcome = _replay(adapter)
    assert (outcome.replayed, outcome.from_revision, outcome.to_revision) == (True, 0, 1)
    tdb_responder.documents = {"C3WriterFence": _fence_document()}
    tdb_responder.lists = {"C3Commit": [_commit_document()]}
    assert adapter.reconcile(limit=5) == 2
    adapter.initialize()
    adapter.drop()
    tdb_responder.overrides = {"version": (200, {"TerminusDB-Data-Version": RESPONDER_VERSION}, b'HTTP/1.1 404\n{"api:status": "api:not_found"}')}
    assert adapter.read_snapshot(TENANT, AGGREGATE_TYPE, RESPONDER_REF) is None


PG_REF = "urn:ocor:mission-object:rem0050:stored-shape"
PG_COMMIT = "urn:ocor:commit:rem0050:stored-shape"
PG_EVENT = "urn:ocor:event:rem0050:stored-shape"


def _pg_store_commit(dsn: str, *, state: str, payload: str, outbox: bool) -> None:
    """Writes a stored aggregate and commit (and its outbox entry) whose JSONB values have
    the given shape, directly with SQL: a corrupted store the adapter never writes."""
    digest = "urn:sha256:" + "5" * 64
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "INSERT INTO c3_aggregate VALUES (%s, %s, %s, 1, %s::jsonb, %s, %s)",
            (TENANT, AGGREGATE_TYPE, PG_REF, state, digest, PG_COMMIT),
        )
        connection.execute(
            """INSERT INTO c3_commit VALUES (%s, 'urn:ocor:command:rem0050:stored-shape', %s, %s, %s, %s, 0, 1, %s,
               'rem0050-stored-shape', 'urn:ocor:decision:x', 'urn:ocor:authority:x', '[]'::jsonb, %s, %s, %s,
               %s::jsonb, %s, 'main', 1, now())""",
            (PG_COMMIT, digest, TENANT, AGGREGATE_TYPE, PG_REF, digest, digest, digest, PG_EVENT, payload, digest),
        )
        if outbox:
            connection.execute(
                "INSERT INTO c3_outbox VALUES (%s, %s, %s, 1, %s::jsonb, %s, 'main', now())",
                (PG_EVENT, PG_COMMIT, PG_REF, payload, digest),
            )


@pytest.mark.parametrize("shape", ["[]", "[1, 2]", "7", '"text"', "null"])
@pytest.mark.parametrize("path", ["snapshot", "commit", "claim", "reconcile"])
def test_postgres_adapter_rejects_stored_json_that_is_not_an_object(dsn: str, shape: str, path: str) -> None:
    """A stored JSONB state or payload that is not an object fails closed with a typed
    adapter error on every read path, never coerced by ``dict()``."""
    adapters = _module("ocor_runtime.c3.adapters.postgres")
    adapter = adapters.PostgresC3Adapter(dsn)
    adapter.initialize()
    adapter.reset()
    try:
        state, payload = (shape, '{"event": "x"}') if path in {"snapshot", "commit"} else ('{"status": "x"}', shape)
        _pg_store_commit(dsn, state=state, payload=payload, outbox=path != "reconcile")
        adapter.acquire_writer()
        operations: dict[str, Callable[[], Any]] = {
            "snapshot": lambda: adapter.read_snapshot(TENANT, AGGREGATE_TYPE, PG_REF),
            "commit": lambda: adapter.commit_transaction(
                tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=PG_REF, idempotency_key="rem0050-next",
                command_id="urn:ocor:command:rem0050:next", command_digest="urn:sha256:" + "6" * 64, expected_revision=1,
                canonical_delta={"status": "ASSESSED"}, decision_ref="urn:ocor:decision:x", authority_ref="urn:ocor:authority:x",
                evidence_refs=(), claim_source_bindings=(), governed_context_digest="urn:sha256:" + "7" * 64,
                gate_package_digest="urn:sha256:" + "8" * 64, branch="main", check_state=lambda current, new: None,
                event_payload=lambda commit_id, before, after, value, digest: {"event": "x"},
            ),
            "claim": lambda: adapter.claim_outbox_batch(limit=10, claim_ttl=timedelta(seconds=5)),
            "reconcile": lambda: adapter.reconcile(limit=5),
        }
        with pytest.raises(adapters.PostgresAdapterError) as caught:
            operations[path]()
        assert caught.value.reason_code == "BACKEND_ERROR"
        assert _sql(dsn, "SELECT count(*) FROM c3_commit")[0][0] == 1
    finally:
        adapter.reset()


def test_postgres_adapter_reads_stored_objects(dsn: str) -> None:
    """Positive control of the same paths: stored objects are read as before."""
    adapters = _module("ocor_runtime.c3.adapters.postgres")
    adapter = adapters.PostgresC3Adapter(dsn)
    adapter.initialize()
    adapter.reset()
    try:
        _pg_store_commit(dsn, state='{"status": "x"}', payload='{"event": "x"}', outbox=True)
        adapter.acquire_writer()
        assert adapter.read_snapshot(TENANT, AGGREGATE_TYPE, PG_REF).state == {"status": "x"}
        (row,) = adapter.claim_outbox_batch(limit=10, claim_ttl=timedelta(seconds=5))
        assert row.payload == {"event": "x"}
        adapter.close_claim()
    finally:
        adapter.reset()


# ---------------------------------------------------------------------------------------
# C6 issuance of the memory promotion commit (PO decision NCP-U04-MEMORY-PROMOTION-GATE-
# PACKAGE, option 1): C6 freezes the C3 GatePackage of the decided command and signs its
# Decision and Authority; C3 admission accepts only that command (ADD v1.3 :342, LLD v1.1
# :97). The live consumer cases reuse the real backends and workflow of OCOR-DEV-0058.
# ---------------------------------------------------------------------------------------
live_backends = _module("test_ocor_dev_0052").live_backends
backends = _module("test_ocor_dev_0052").backends
ISSUANCE_WINDOWS = {
    "decision_expires_at": NOW + timedelta(minutes=5),
    "authority_not_before": NOW - timedelta(minutes=1),
    "authority_expires_at": NOW + timedelta(minutes=10),
}


def _issuer(governed: GovernedC3) -> Any:
    return _module("ocor_runtime.c6.engine").GovernedCommandIssuer(
        signing_key=CONSUMER_KEY, keyid=CONSUMER_KEYID, records=governed.records, fence=governed.fence,
        clock=governed.clock,
    )


def _decided_fields(governed: GovernedC3) -> dict[str, Any]:
    """A decided command (its own gate digest included), with its Evidence registered."""
    path = GovernedPath(RecordStore(), Fence(), InMemoryTrustedClock(NOW), aggregate_ref="urn:ocor:mission-object:rem0050:issuer")
    fields = dict(path.command("urn:sha256:" + "0" * 64).to_mapping())
    governed.add_evidence(fields["evidence_refs"])
    return fields


def test_c6_command_issuer_is_admitted_by_c3_with_the_decided_windows() -> None:
    governed = GovernedC3(release=RELEASE, preconditions=(PRECONDITION,), invariants=(INVARIANT,), now=NOW)
    issuer = _issuer(governed)
    fields = _decided_fields(governed)
    command = issuer.issue(fields, **ISSUANCE_WINDOWS)
    # Every decided field is kept; only the GatePackage digest is C6's.
    assert command.gate_package_digest != fields["gate_package_digest"]
    assert dataclass_replace(command, gate_package_digest=fields["gate_package_digest"]) == (
        GovernedCanonicalCommitCommand.from_mapping(fields)
    )
    admitted = governed.admission().admit(command)
    assert admitted.gate_package_digest == command.gate_package_digest
    decision = governed.records.decision(command.decision_ref)
    authority = governed.records.authority(command.authority_ref)
    assert decision is not None and authority is not None
    assert decision.payload["expires_at"] == format_utc_timestamp(ISSUANCE_WINDOWS["decision_expires_at"])
    assert decision.payload["decided_at"] == format_utc_timestamp(NOW)
    assert (authority.payload["not_before"], authority.payload["expires_at"]) == (
        format_utc_timestamp(ISSUANCE_WINDOWS["authority_not_before"]),
        format_utc_timestamp(ISSUANCE_WINDOWS["authority_expires_at"]),
    )
    # A retry of the same decided command gets the same command (FR-008 replay).
    records = len(governed.export()["records"])
    assert issuer.issue(fields, **ISSUANCE_WINDOWS) is command
    assert len(governed.export()["records"]) == records
    # The Decision expires with the decision C6 took.
    governed.clock.advance(timedelta(minutes=5))
    with pytest.raises(C3Error) as caught:
        governed.admission().admit(command)
    assert caught.value.reason_code == "POLICY_DENIED"


@pytest.mark.parametrize(
    "fault", ["other-command", "no-action", "naive-instant", "decision-expired", "empty-authority-window"]
)
def test_c6_command_issuer_refuses_without_publishing(fault: str) -> None:
    governed = GovernedC3(release=RELEASE, preconditions=(PRECONDITION,), invariants=(INVARIANT,), now=NOW)
    issuer = _issuer(governed)
    fields = _decided_fields(governed)
    windows = dict(ISSUANCE_WINDOWS)
    if fault == "other-command":
        issuer.issue(fields, **windows)
        fields = {**fields, "expected_revision": 1}
    elif fault == "no-action":
        fields.pop("action_instance_id")
    elif fault == "naive-instant":
        windows["decision_expires_at"] = windows["decision_expires_at"].replace(tzinfo=None)
    elif fault == "decision-expired":
        windows["decision_expires_at"] = NOW
    else:
        windows["authority_expires_at"] = windows["authority_not_before"]
    records = len(governed.export()["records"])
    with pytest.raises(ValueError):
        issuer.issue(fields, **windows)
    assert len(governed.export()["records"]) == records


@pytest.mark.parametrize("fault", ["signing-key", "records", "fence", "clock", "keyid"])
def test_c6_command_issuer_requires_its_trusted_composition(fault: str) -> None:
    governed = GovernedC3(release=RELEASE, now=NOW)
    values: dict[str, Any] = {
        "signing_key": CONSUMER_KEY, "keyid": CONSUMER_KEYID, "records": governed.records, "fence": governed.fence,
        "clock": governed.clock,
    }
    values[fault.replace("-", "_")] = "" if fault == "keyid" else object()
    with pytest.raises(TypeError if fault != "keyid" else ValueError):
        _module("ocor_runtime.c6.engine").GovernedCommandIssuer(**values)


class _FaultyIssuer:
    """The C6 issuance port failing or issuing another command than the decided one."""

    def __init__(self, issuer: Any, fault: str) -> None:
        self.issuer, self.fault = issuer, fault

    def issue(self, fields: Mapping[str, Any], **windows: datetime) -> Any:
        if self.fault == "unavailable":
            raise RuntimeError("C6 governance record store unavailable")
        return self.issuer.issue({**fields, "expected_revision": 1}, **windows)


@pytest.mark.parametrize(
    "fault,detail", [("unavailable", "C6_CONTROL_UNAVAILABLE"), ("other-command", "C6_COMMAND_BINDING_MISMATCH")]
)
def test_promotion_issuance_fault_is_denied_before_c3(backends: Any, fault: str, detail: str) -> None:
    promotion = _module("test_ocor_dev_0058")
    memory = _module("test_ocor_dev_0052")
    consumer_type = _module("ocor_runtime.memory.promotion").C6MemoryPromotionConsumer
    human_gate = _module("ocor_runtime.c6.human_gate").HumanGateCoordinator
    with promotion.workflow(backends) as x:
        x.controls.put(x.result.audit_ref, x.body)
        consumer = consumer_type(
            proposals=x.s, controls=x.controls, verifier=x.signer,
            human_gate=human_gate(identities=x.registry, clock=x.w.clock), policy=x.policy, c3=x.c3,
            issuer=_FaultyIssuer(x.issuer, fault), clock=x.w.clock, audit=x.audit, commit_capability="canonical.commit",
            engine=x.engine,
        )
        before = x.w.ledger.records()
        with pytest.raises(memory.MemoryAdmissionError) as caught:
            consumer.commit(x.result.audit_ref, binding=memory.binding(x.ctx))
        assert caught.value.detail_code == detail
        assert x.c3.read(x.ctx.tenant_id, "Situation", x.req["target_aggregate_ref"]) is None
        assert x.w.ledger.records() == before
        assert x.audit.actions()[-2:] == ["commitMemoryPromotion.intent", "commitMemoryPromotion.denied"]


# ---------------------------------------------------------------------------------------
# Input robustness of the PostgreSQL C3 adapter and service, of the C8 PostgreSQL Run
# Ledger, of the C4 projector, of the relay envelope, of the GatePackage instant and of
# the TerminusDB acknowledgement (PRE-REVIEW-INPUT-ROBUSTNESS (2026-10-29)). A local SQL
# responder stands in for the driver connection, so every stored-row shape and driver
# failure is reached without a backend; divergent pre-existing tables are created on the
# real PostgreSQL in a scratch schema.
# ---------------------------------------------------------------------------------------
PG = "ocor_runtime.c3.adapters.postgres"
LEDGER = "ocor_runtime.c8.adapters.postgres_ledger"
PG_DIGEST = "urn:sha256:" + "5" * 64
PG_COMMAND_DIGEST = "urn:sha256:" + "6" * 64
PG_PAYLOAD = {"event": "x"}


class _SQLRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def fetchone(self) -> object:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[object]:
        return list(self._rows)


@dataclass
class SQLResponder:
    """Local stand-in of the PostgreSQL driver connection: each statement is answered
    with the rows, or raises the driver exception, of the first matching fragment."""

    answers: list[tuple[str, object]] = field(default_factory=list)
    statements: list[str] = field(default_factory=list)

    def connect(self, *args: object, **kwargs: object) -> _SQLConnection:
        return _SQLConnection(self)


class _SQLConnection:
    def __init__(self, responder: SQLResponder) -> None:
        self._responder = responder
        self.closed = False

    def __enter__(self) -> _SQLConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed = True

    def execute(self, query: str, params: object = ()) -> _SQLRows:
        self._responder.statements.append(query)
        for fragment, answer in self._responder.answers:
            if fragment in query:
                if isinstance(answer, BaseException):
                    raise answer
                assert isinstance(answer, list)
                return _SQLRows(answer)
        return _SQLRows([])

    @contextlib.contextmanager
    def transaction(self) -> Iterator[_SQLConnection]:
        yield self

    def commit(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def sql_responder(monkeypatch: pytest.MonkeyPatch) -> SQLResponder:
    responder = SQLResponder()
    monkeypatch.setattr(psycopg, "connect", responder.connect)
    return responder


def _pg_aggregate(**values: object) -> dict[str, object]:
    return {"revision": 1, "state": {"status": "ASSESSED"}, "state_digest": PG_DIGEST, "commit_id": PG_COMMIT, **values}


def _pg_commit_row(**values: object) -> dict[str, object]:
    return {
        "commit_id": PG_COMMIT, "command_id": "urn:ocor:command:rem0050:stored-shape", "command_digest": PG_COMMAND_DIGEST,
        "tenant_id": TENANT, "aggregate_type": AGGREGATE_TYPE, "aggregate_ref": PG_REF, "from_revision": 0, "to_revision": 1,
        "state_digest": PG_DIGEST, "idempotency_key": "rem0050-stored-shape", "decision_ref": "urn:ocor:decision:x",
        "authority_ref": "urn:ocor:authority:x", "evidence_refs": [], "governed_context_digest": PG_DIGEST,
        "gate_package_digest": PG_DIGEST, "outbox_event_id": PG_EVENT, "outbox_payload": dict(PG_PAYLOAD),
        "outbox_payload_digest": canonical_digest(PG_PAYLOAD), "branch": "main", "writer_epoch": 1, "committed_at": NOW,
        **values,
    }


def _pg_outbox_row(**values: object) -> dict[str, object]:
    return {
        "event_id": PG_EVENT, "commit_id": PG_COMMIT, "aggregate_ref": PG_REF, "aggregate_revision": 1,
        "payload": dict(PG_PAYLOAD), "payload_digest": PG_DIGEST, "branch": "main", "occurred_at": NOW, **values,
    }


def _pg_attempt_row(**values: object) -> dict[str, object]:
    return {"event_id": PG_EVENT, "attempt_no": 1, "outcome": "ACKNOWLEDGED", "writer_epoch": 1, "recorded_at": NOW, **values}


def _pg_columns(**overrides: frozenset[str]) -> list[object]:
    expected = {**_module(PG).EXPECTED_COLUMNS, **overrides}
    return [{"table_name": table, "column_name": column} for table, columns in expected.items() for column in sorted(columns)]


FENCE_SQL = "FROM c3_writer_fence WHERE boundary"
FENCE_ROW: tuple[str, object] = (FENCE_SQL, [{"writer_epoch": 1}])


def _pg_commit(adapter: Any) -> Any:
    adapter.join_writer(1)
    return adapter.commit_transaction(
        tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=PG_REF, idempotency_key="rem0050-stored-shape",
        command_id="urn:ocor:command:rem0050:stored-shape", command_digest=PG_COMMAND_DIGEST, expected_revision=1,
        canonical_delta={"status": "VERIFIED"}, decision_ref="urn:ocor:decision:x", authority_ref="urn:ocor:authority:x",
        evidence_refs=(), claim_source_bindings=(), governed_context_digest=PG_DIGEST, gate_package_digest=PG_DIGEST,
        branch="main", check_state=lambda current, new: None, event_payload=lambda *args: dict(PG_PAYLOAD),
    )


def _pg_joined(call: Callable[[Any], Any]) -> Callable[[Any], Any]:
    def run(adapter: Any) -> Any:
        adapter.join_writer(1)
        return call(adapter)

    return run


PG_OPERATIONS: dict[str, Callable[[Any], Any]] = {
    "initialize": lambda adapter: adapter.initialize(),
    "reset": lambda adapter: adapter.reset(),
    "acquire": lambda adapter: adapter.acquire_writer(),
    "snapshot": lambda adapter: adapter.read_snapshot(TENANT, AGGREGATE_TYPE, PG_REF),
    "revision": lambda adapter: adapter.current_revision(TENANT, AGGREGATE_TYPE, PG_REF),
    "bindings": lambda adapter: adapter.source_bindings(PG_COMMIT),
    "commit": _pg_commit,
    "claim": lambda adapter: adapter.claim_outbox_batch(limit=10, claim_ttl=timedelta(seconds=5)),
    "attempts": lambda adapter: adapter.delivery_attempts(PG_EVENT),
    "acknowledge": _pg_joined(lambda adapter: adapter.acknowledge_outbox(PG_EVENT, acknowledged_at=NOW)),
    "failure": lambda adapter: adapter.record_delivery_failure(PG_EVENT, failed_at=NOW, reason="broker"),
    "reconcile": _pg_joined(lambda adapter: adapter.reconcile(limit=5)),
}
NAIVE = datetime(2026, 11, 3, 9, 0, 0)
SNAPSHOT_SQL = "SELECT revision, state, state_digest, commit_id FROM c3_aggregate"
CURRENT_SQL = "SELECT revision, state FROM c3_aggregate"
REPLAY_SQL = "FROM c3_idempotency i JOIN c3_commit"
CLAIM_SQL = "FROM c3_outbox o"
ACKED_SQL = "event_id = ANY"
ATTEMPTS_SQL = "ORDER BY attempt_no"
# (case, operation, answers, reason code)
PG_MALFORMED: list[tuple[str, str, list[tuple[str, object]], str]] = [
    *[
        (f"{operation}-driver-unavailable", operation, [("", psycopg.OperationalError(CANARY))], "BACKEND_UNAVAILABLE")
        for operation in PG_OPERATIONS
    ],
    *[
        (f"{operation}-driver-error", operation, [("", psycopg.DatabaseError(CANARY))], "BACKEND_ERROR")
        for operation in PG_OPERATIONS
    ],
    ("columns-table-not-text", "initialize", [("information_schema.columns", [{"table_name": 7, "column_name": "x"}])], "BACKEND_ERROR"),
    ("columns-row-not-object", "initialize", [("information_schema.columns", [("c3_commit", "commit_id")])], "BACKEND_ERROR"),
    ("columns-aggregate-divergent", "initialize", [("information_schema.columns", _pg_columns(c3_aggregate=frozenset({"tenant_id"})))], "SCHEMA_MISMATCH"),
    ("columns-idempotency-divergent", "initialize", [("information_schema.columns", _pg_columns(c3_idempotency=frozenset({"commit_id"})))], "SCHEMA_MISMATCH"),
    ("fence-epoch-missing", "acquire", [], "BACKEND_ERROR"),
    ("fence-epoch-bool", "acquire", [("INSERT INTO c3_writer_fence", [{"writer_epoch": True}])], "BACKEND_ERROR"),
    ("fence-epoch-text", "acquire", [("INSERT INTO c3_writer_fence", [{"writer_epoch": "1"}])], "BACKEND_ERROR"),
    ("fence-row-not-object", "acquire", [("INSERT INTO c3_writer_fence", [[1]])], "BACKEND_ERROR"),
    ("held-fence-epoch-bool", "commit", [(FENCE_SQL, [{"writer_epoch": True}])], "BACKEND_ERROR"),
    ("held-fence-row-without-epoch", "commit", [(FENCE_SQL, [{"epoch": 1}])], "BACKEND_ERROR"),
    ("snapshot-revision-bool", "snapshot", [(SNAPSHOT_SQL, [_pg_aggregate(revision=True)])], "BACKEND_ERROR"),
    ("snapshot-revision-text", "snapshot", [(SNAPSHOT_SQL, [_pg_aggregate(revision="1")])], "BACKEND_ERROR"),
    ("snapshot-revision-negative", "snapshot", [(SNAPSHOT_SQL, [_pg_aggregate(revision=-1)])], "BACKEND_ERROR"),
    ("snapshot-digest-missing", "snapshot", [(SNAPSHOT_SQL, [_pg_aggregate(state_digest=None)])], "BACKEND_ERROR"),
    ("snapshot-commit-empty", "snapshot", [(SNAPSHOT_SQL, [_pg_aggregate(commit_id="")])], "BACKEND_ERROR"),
    ("snapshot-row-not-object", "snapshot", [(SNAPSHOT_SQL, [[1, {}, PG_DIGEST, PG_COMMIT]])], "BACKEND_ERROR"),
    ("snapshot-row-without-state", "snapshot", [(SNAPSHOT_SQL, [{k: v for k, v in _pg_aggregate().items() if k != "state"}])], "BACKEND_ERROR"),
    ("revision-bool", "revision", [("SELECT revision FROM c3_aggregate", [{"revision": True}])], "BACKEND_ERROR"),
    ("revision-text", "revision", [("SELECT revision FROM c3_aggregate", [{"revision": "1"}])], "BACKEND_ERROR"),
    ("binding-ref-not-text", "bindings", [("FROM c3_source_binding", [{"claim_ref": 7, "source_ref": "s", "evidence_ref": "e"}])], "BACKEND_ERROR"),
    ("binding-row-without-source", "bindings", [("FROM c3_source_binding", [{"claim_ref": "c", "evidence_ref": "e"}])], "BACKEND_ERROR"),
    ("current-revision-bool", "commit", [FENCE_ROW, (CURRENT_SQL, [{"revision": True, "state": {}}])], "BACKEND_ERROR"),
    ("current-row-without-state", "commit", [FENCE_ROW, (CURRENT_SQL, [{"revision": 1}])], "BACKEND_ERROR"),
    ("replay-revisions-not-consecutive", "commit", [FENCE_ROW, (REPLAY_SQL, [_pg_commit_row(to_revision=3)])], "COMMIT_RECEIPT_MISMATCH"),
    ("replay-revision-bool", "commit", [FENCE_ROW, (REPLAY_SQL, [_pg_commit_row(from_revision=False, to_revision=True)])], "BACKEND_ERROR"),
    ("replay-committed-at-naive", "commit", [FENCE_ROW, (REPLAY_SQL, [_pg_commit_row(committed_at=NAIVE)])], "BACKEND_ERROR"),
    ("replay-committed-at-text", "commit", [FENCE_ROW, (REPLAY_SQL, [_pg_commit_row(committed_at="2026-11-03T09:00:00Z")])], "BACKEND_ERROR"),
    ("replay-commit-id-missing", "commit", [FENCE_ROW, (REPLAY_SQL, [_pg_commit_row(commit_id=None)])], "BACKEND_ERROR"),
    ("replay-digest-not-text", "commit", [FENCE_ROW, (REPLAY_SQL, [_pg_commit_row(command_digest=7)])], "BACKEND_ERROR"),
    ("claim-event-id-not-text", "claim", [(CLAIM_SQL, [_pg_outbox_row(event_id=[])])], "BACKEND_ERROR"),
    ("claim-revision-bool", "claim", [(CLAIM_SQL, [_pg_outbox_row(aggregate_revision=True)])], "BACKEND_ERROR"),
    ("claim-revision-zero", "claim", [(CLAIM_SQL, [_pg_outbox_row(aggregate_revision=0)])], "BACKEND_ERROR"),
    ("claim-occurred-at-naive", "claim", [(CLAIM_SQL, [_pg_outbox_row(occurred_at=NAIVE)])], "BACKEND_ERROR"),
    ("claim-occurred-at-text", "claim", [(CLAIM_SQL, [_pg_outbox_row(occurred_at="now")])], "BACKEND_ERROR"),
    ("claim-branch-not-text", "claim", [(CLAIM_SQL, [_pg_outbox_row(branch=7)])], "BACKEND_ERROR"),
    ("claim-digest-missing", "claim", [(CLAIM_SQL, [_pg_outbox_row(payload_digest=None)])], "BACKEND_ERROR"),
    ("claim-acknowledged-id-not-text", "claim", [(ACKED_SQL, [{"event_id": 7}]), (CLAIM_SQL, [_pg_outbox_row()])], "BACKEND_ERROR"),
    ("attempt-number-bool", "attempts", [(ATTEMPTS_SQL, [_pg_attempt_row(attempt_no=True)])], "BACKEND_ERROR"),
    ("attempt-number-zero", "attempts", [(ATTEMPTS_SQL, [_pg_attempt_row(attempt_no=0)])], "BACKEND_ERROR"),
    ("attempt-other-outcome", "attempts", [(ATTEMPTS_SQL, [_pg_attempt_row(outcome="LOST")])], "BACKEND_ERROR"),
    ("attempt-other-event", "attempts", [(ATTEMPTS_SQL, [_pg_attempt_row(event_id="urn:ocor:event:other")])], "BACKEND_ERROR"),
    ("attempt-epoch-bool", "attempts", [(ATTEMPTS_SQL, [_pg_attempt_row(writer_epoch=True)])], "BACKEND_ERROR"),
    ("attempt-acknowledged-without-epoch", "attempts", [(ATTEMPTS_SQL, [_pg_attempt_row(writer_epoch=None)])], "BACKEND_ERROR"),
    ("attempt-recorded-at-naive", "attempts", [(ATTEMPTS_SQL, [_pg_attempt_row(recorded_at=NAIVE)])], "BACKEND_ERROR"),
    ("ack-entry-branch-not-text", "acknowledge", [FENCE_ROW, ("SELECT branch FROM c3_outbox", [{"branch": 7}])], "BACKEND_ERROR"),
    ("reconcile-tenant-missing", "reconcile", [FENCE_ROW, ("LEFT JOIN c3_idempotency", [_pg_commit_row(tenant_id=None)])], "BACKEND_ERROR"),
    ("reconcile-to-revision-text", "reconcile", [FENCE_ROW, ("LEFT JOIN c3_outbox", [_pg_commit_row(to_revision="1")])], "BACKEND_ERROR"),
    ("reconcile-committed-at-text", "reconcile", [FENCE_ROW, ("LEFT JOIN c3_outbox", [_pg_commit_row(committed_at="yesterday")])], "BACKEND_ERROR"),
    ("reconcile-payload-digest-mismatch", "reconcile", [FENCE_ROW, ("LEFT JOIN c3_outbox", [_pg_commit_row(outbox_payload_digest=PG_DIGEST)])], "COMMIT_RECEIPT_MISMATCH"),
]


@pytest.mark.parametrize(("case", "operation", "answers", "reason"), PG_MALFORMED, ids=[item[0] for item in PG_MALFORMED])
def test_postgres_adapter_rejects_malformed_rows_and_driver_failures(
    sql_responder: SQLResponder, case: str, operation: str, answers: list[tuple[str, object]], reason: str
) -> None:
    """Every stored row of an unexpected shape and every driver failure is a typed adapter
    error with a stable reason code; nothing is coerced and no driver text is echoed."""
    sql_responder.answers = answers
    with pytest.raises(_module(PG).PostgresAdapterError) as caught:
        PG_OPERATIONS[operation](_module(PG).PostgresC3Adapter("postgresql://responder/ocor"))
    assert caught.value.reason_code == reason, case
    assert CANARY not in str(caught.value), case


PG_INVALID_INPUTS: list[tuple[str, Callable[[Any], Any]]] = [
    ("ack-naive-instant", _pg_joined(lambda adapter: adapter.acknowledge_outbox(PG_EVENT, acknowledged_at=NAIVE))),
    ("ack-instant-text", _pg_joined(lambda adapter: adapter.acknowledge_outbox(PG_EVENT, acknowledged_at="now"))),
    ("ack-event-empty", _pg_joined(lambda adapter: adapter.acknowledge_outbox("", acknowledged_at=NOW))),
    ("failure-naive-instant", lambda adapter: adapter.record_delivery_failure(PG_EVENT, failed_at=NAIVE, reason="x")),
    ("snapshot-tenant-not-text", lambda adapter: adapter.read_snapshot(7, AGGREGATE_TYPE, PG_REF)),
    ("revision-ref-empty", lambda adapter: adapter.current_revision(TENANT, AGGREGATE_TYPE, "")),
    ("bindings-commit-not-text", lambda adapter: adapter.source_bindings(None)),
    ("attempts-event-empty", lambda adapter: adapter.delivery_attempts("")),
    ("reconcile-limit-bool", _pg_joined(lambda adapter: adapter.reconcile(limit=True))),
]


@pytest.mark.parametrize(("case", "call"), PG_INVALID_INPUTS, ids=[item[0] for item in PG_INVALID_INPUTS])
def test_postgres_adapter_rejects_invalid_inputs_before_the_backend(
    sql_responder: SQLResponder, case: str, call: Callable[[Any], Any]
) -> None:
    with pytest.raises(_module(PG).PostgresAdapterError) as caught:
        call(_module(PG).PostgresC3Adapter("postgresql://responder/ocor"))
    assert caught.value.reason_code == "COMMIT_CONTRACT_INVALID", case
    assert sql_responder.statements == [], case


def test_postgres_adapter_reads_well_formed_rows(sql_responder: SQLResponder) -> None:
    """Positive controls of the same parsing paths: well formed rows are read unchanged."""
    adapter = _module(PG).PostgresC3Adapter("postgresql://responder/ocor")
    sql_responder.answers = [("information_schema.columns", _pg_columns())]
    adapter.initialize()
    sql_responder.answers = [("INSERT INTO c3_writer_fence", [{"writer_epoch": 2}])]
    assert adapter.acquire_writer() == 2
    sql_responder.answers = [(SNAPSHOT_SQL, [_pg_aggregate()])]
    snapshot = adapter.read_snapshot(TENANT, AGGREGATE_TYPE, PG_REF)
    assert (snapshot.revision, snapshot.state, snapshot.state_digest, snapshot.commit_id) == (
        1, {"status": "ASSESSED"}, PG_DIGEST, PG_COMMIT
    )
    sql_responder.answers = [("SELECT revision FROM c3_aggregate", [{"revision": 4}])]
    assert adapter.current_revision(TENANT, AGGREGATE_TYPE, PG_REF) == 4
    sql_responder.answers = [("FROM c3_source_binding", [{"claim_ref": "c", "source_ref": "s", "evidence_ref": "e"}])]
    assert [(row.claim_ref, row.source_ref, row.evidence_ref) for row in adapter.source_bindings(PG_COMMIT)] == [("c", "s", "e")]
    sql_responder.answers = [FENCE_ROW, (REPLAY_SQL, [_pg_commit_row()])]
    outcome = _pg_commit(adapter)
    assert (outcome.replayed, outcome.from_revision, outcome.to_revision, outcome.committed_at) == (True, 0, 1, NOW)
    sql_responder.answers = [FENCE_ROW, (CURRENT_SQL, [{"revision": 1, "state": {"status": "ASSESSED"}}])]
    outcome = _pg_commit(adapter)
    assert (outcome.replayed, outcome.from_revision, outcome.to_revision) == (False, 1, 2)
    sql_responder.answers = [(CLAIM_SQL, [_pg_outbox_row()])]
    (row,) = adapter.claim_outbox_batch(limit=10, claim_ttl=timedelta(seconds=5))
    assert (row.event_id, row.aggregate_revision, row.payload, row.branch, row.occurred_at) == (
        PG_EVENT, 1, PG_PAYLOAD, "main", NOW
    )
    sql_responder.answers = [FENCE_ROW]
    adapter.acknowledge_outbox(PG_EVENT, acknowledged_at=NOW)
    sql_responder.answers = [(ATTEMPTS_SQL, [_pg_attempt_row(), _pg_attempt_row(attempt_no=2, outcome="FAILED", writer_epoch=None)])]
    attempts = adapter.delivery_attempts(PG_EVENT)
    assert [(item.attempt_no, item.outcome, item.writer_epoch) for item in attempts] == [(1, "ACKNOWLEDGED", 1), (2, "FAILED", None)]
    sql_responder.answers = [("SELECT branch FROM c3_outbox", [{"branch": "main"}])]
    adapter.record_delivery_failure(PG_EVENT, failed_at=NOW, reason="broker")
    sql_responder.answers = [FENCE_ROW, ("LEFT JOIN c3_idempotency", [_pg_commit_row()]), ("LEFT JOIN c3_outbox", [_pg_commit_row()])]
    assert adapter.reconcile(limit=5) == 2
    adapter.reset()


def test_postgres_adapter_initialize_does_not_mask_a_failed_schema_statement(sql_responder: SQLResponder) -> None:
    sql_responder.answers = [("CREATE TABLE IF NOT EXISTS c3_writer_fence", psycopg.errors.InsufficientPrivilege(CANARY))]
    with pytest.raises(_module(PG).PostgresAdapterError) as caught:
        _module(PG).PostgresC3Adapter("postgresql://responder/ocor").initialize()
    assert caught.value.reason_code == "BACKEND_ERROR"
    assert CANARY not in str(caught.value)


SERVICE_OPERATIONS: dict[str, Callable[[Any], Any]] = {
    "initialize": lambda service: service.initialize(),
    "reset": lambda service: service.reset(),
    "read": lambda service: service.read(TENANT, AGGREGATE_TYPE, PG_REF),
    "current_revision": lambda service: service.current_revision(TENANT, AGGREGATE_TYPE, PG_REF),
    "source_bindings": lambda service: service.source_bindings(PG_COMMIT),
    "claim_batch": lambda service: service.claim_batch(limit=10),
    "acknowledge": lambda service: service.acknowledge(PG_EVENT, acknowledged_at=NOW),
    "record_failure": lambda service: service.record_failure(PG_EVENT, failed_at=NOW, reason="broker"),
    "delivery_attempts": lambda service: service.delivery_attempts(PG_EVENT),
    "reconcile": lambda service: service.reconcile(limit=5),
}


@pytest.mark.parametrize("operation", sorted(SERVICE_OPERATIONS))
def test_postgres_service_translates_every_adapter_failure(sql_responder: SQLResponder, operation: str) -> None:
    """Every port operation of the PostgreSQL C3 service surfaces the sealed ``C3Error``,
    never the adapter error nor a driver exception."""
    service = _module("ocor_runtime.c3.service").PostgresC3Service(
        "postgresql://responder/ocor", admission=_admission(RecordStore(), Fence(), InMemoryTrustedClock(NOW)), writer_epoch=1
    )
    sql_responder.answers = [("", psycopg.OperationalError(CANARY))]
    with pytest.raises(C3Error) as caught:
        SERVICE_OPERATIONS[operation](service)
    assert caught.value.reason_code == "BACKEND_UNAVAILABLE"
    assert CANARY not in str(caught.value)
    sql_responder.answers = [(SNAPSHOT_SQL, [_pg_aggregate(state=["not-an-object"])])]
    with pytest.raises(C3Error) as caught:
        service.read(TENANT, AGGREGATE_TYPE, PG_REF)
    assert caught.value.reason_code == "BACKEND_ERROR"


TDB_SERVICE_OPERATIONS: dict[str, Callable[[Any], Any]] = {
    "initialize": lambda service: service.initialize(),
    "drop": lambda service: service.drop(),
    "read": lambda service: service.read(TENANT, AGGREGATE_TYPE, RESPONDER_REF),
    "current_revision": lambda service: service.current_revision(TENANT, AGGREGATE_TYPE, RESPONDER_REF),
}


@pytest.mark.parametrize("operation", sorted(TDB_SERVICE_OPERATIONS))
def test_terminusdb_service_surfaces_every_adapter_failure_typed(tdb_responder: TerminusDBResponder, operation: str) -> None:
    """The sealed TerminusDB service maps only the C3 contract outcomes to ``C3Error`` and
    lets every other adapter failure propagate unchanged (``CONTRACT_REASONS``, OCOR-DEV-
    REM-0041): on every port operation that failure is the typed adapter error with a
    stable reason code, never a raw transport or parsing exception."""
    service = _module("ocor_runtime.c3.terminusdb_service").TerminusDBC3Service(
        url=tdb_responder.url, password="rem0050-responder-synthetic", database="rem0050_responder",
        admission=_admission(RecordStore(), Fence(), InMemoryTrustedClock(NOW)), timeout=5.0, writer_epoch=1,
    )
    tdb_responder.overrides = {"version": (500, {}, CANARY_BODY), "db": (500, {}, CANARY_BODY)}
    with pytest.raises(_module(TDB).TerminusDBAdapterError) as caught:
        TDB_SERVICE_OPERATIONS[operation](service)
    assert caught.value.reason_code == "BACKEND_ERROR"
    assert CANARY not in str(caught.value)


@pytest.mark.parametrize(
    ("case", "call"),
    [
        ("naive-instant", lambda adapter: adapter.acknowledge_outbox(RESPONDER_EVENT, acknowledged_at=NAIVE)),
        ("instant-text", lambda adapter: adapter.acknowledge_outbox(RESPONDER_EVENT, acknowledged_at="now")),
        ("event-empty", lambda adapter: adapter.acknowledge_outbox("", acknowledged_at=NOW)),
        ("event-not-text", lambda adapter: adapter.acknowledge_outbox(7, acknowledged_at=NOW)),
        ("snapshot-ref-not-text", lambda adapter: adapter.read_snapshot(TENANT, AGGREGATE_TYPE, 7)),
        ("revision-tenant-empty", lambda adapter: adapter.current_revision("", AGGREGATE_TYPE, RESPONDER_REF)),
        ("bindings-commit-empty", lambda adapter: adapter.source_bindings("")),
        ("attempts-event-not-text", lambda adapter: adapter.delivery_attempts(None)),
    ],
    ids=["naive-instant", "instant-text", "event-empty", "event-not-text", "snapshot-ref-not-text",
         "revision-tenant-empty", "bindings-commit-empty", "attempts-event-not-text"],
)
def test_terminusdb_adapter_rejects_invalid_inputs_before_the_backend(
    tdb_responder: TerminusDBResponder, case: str, call: Callable[[Any], Any]
) -> None:
    adapter = _responder_adapter(tdb_responder)
    adapter.join_writer(1)
    tdb_responder.documents = {"C3WriterFence": _fence_document(), "C3OutboxEntry": _outbox_entry()}
    with pytest.raises(_module(TDB).TerminusDBAdapterError) as caught:
        call(adapter)
    assert caught.value.reason_code == "COMMIT_CONTRACT_INVALID", case


# --- C8 PostgreSQL Run Ledger ---------------------------------------------------------

LEDGER_COLUMNS = ("entry_no", "idempotency_key", "task_id", "kind", "agent_id", "payload", "recorded_at")


def _ledger_row(**values: object) -> dict[str, object]:
    return {
        "entry_no": 1, "idempotency_key": "rem0050-ledger", "task_id": "task-rem0050", "kind": "TASK_ASSIGNED",
        "agent_id": "agent-1", "payload": {"capability": "act:do-thing"}, "recorded_at": NOW, **values,
    }


def _ledger_columns(columns: tuple[str, ...] = LEDGER_COLUMNS) -> list[object]:
    return [{"column_name": column} for column in columns]


def _ledger_append(ledger: Any) -> Any:
    return ledger.append(
        idempotency_key="rem0050-ledger", task_id="task-rem0050", kind="TASK_ASSIGNED", agent_id="agent-1",
        payload={"capability": "act:do-thing"}, recorded_at=NOW,
    )


LEDGER_OPERATIONS: dict[str, Callable[[Any], Any]] = {
    "initialize": lambda ledger: ledger.initialize(),
    "append": _ledger_append,
    "entries": lambda ledger: ledger.entries("task-rem0050"),
}
INSERT_SQL = "INSERT INTO c8_run_ledger"
REREAD_SQL = "SELECT * FROM c8_run_ledger WHERE idempotency_key"
ENTRIES_SQL = "ORDER BY entry_no"
LEDGER_MALFORMED: list[tuple[str, str, list[tuple[str, object]], str]] = [
    *[
        (f"{operation}-driver-unavailable", operation, [("", psycopg.OperationalError(CANARY))], "BACKEND_UNAVAILABLE")
        for operation in LEDGER_OPERATIONS
    ],
    *[
        (f"{operation}-driver-error", operation, [("", psycopg.DatabaseError(CANARY))], "BACKEND_ERROR")
        for operation in LEDGER_OPERATIONS
    ],
    ("schema-statement-fails", "initialize", [("CREATE TABLE IF NOT EXISTS c8_run_ledger", psycopg.errors.InsufficientPrivilege(CANARY))], "BACKEND_ERROR"),
    ("columns-divergent", "initialize", [("information_schema.columns", _ledger_columns(LEDGER_COLUMNS[:-1]))], "SCHEMA_MISMATCH"),
    ("columns-name-not-text", "initialize", [("information_schema.columns", [{"column_name": 7}])], "BACKEND_ERROR"),
    ("entry-number-bool", "append", [(INSERT_SQL, [_ledger_row(entry_no=True)])], "BACKEND_ERROR"),
    ("entry-number-zero", "append", [(INSERT_SQL, [_ledger_row(entry_no=0)])], "BACKEND_ERROR"),
    ("entry-key-missing", "append", [(INSERT_SQL, [_ledger_row(idempotency_key=None)])], "BACKEND_ERROR"),
    ("entry-task-not-text", "append", [(INSERT_SQL, [_ledger_row(task_id=123)])], "BACKEND_ERROR"),
    ("entry-kind-unknown", "append", [(INSERT_SQL, [_ledger_row(kind="NOT_A_VALID_KIND")])], "BACKEND_ERROR"),
    ("entry-agent-bool", "append", [(INSERT_SQL, [_ledger_row(agent_id=False)])], "BACKEND_ERROR"),
    ("entry-payload-pairs", "append", [(INSERT_SQL, [_ledger_row(payload=[["coerced_from_array", 1]])])], "BACKEND_ERROR"),
    ("entry-payload-text", "append", [(INSERT_SQL, [_ledger_row(payload="ab")])], "BACKEND_ERROR"),
    ("entry-payload-null", "append", [(INSERT_SQL, [_ledger_row(payload=None)])], "BACKEND_ERROR"),
    ("entry-recorded-at-text", "append", [(INSERT_SQL, [_ledger_row(recorded_at="not-a-datetime")])], "BACKEND_ERROR"),
    ("entry-recorded-at-naive", "append", [(INSERT_SQL, [_ledger_row(recorded_at=NAIVE)])], "BACKEND_ERROR"),
    ("entry-row-not-object", "append", [(INSERT_SQL, [[1, "rem0050-ledger"]])], "BACKEND_ERROR"),
    ("entry-row-without-payload", "append", [(INSERT_SQL, [{k: v for k, v in _ledger_row().items() if k != "payload"}])], "BACKEND_ERROR"),
    ("replayed-payload-pairs", "append", [(REREAD_SQL, [_ledger_row(payload=[["capability", "act:do-thing"]])])], "BACKEND_ERROR"),
    ("replayed-other-content", "append", [(REREAD_SQL, [_ledger_row(agent_id="agent-2")])], "IDEMPOTENCY_CONFLICT"),
    ("listed-payload-pairs", "entries", [(ENTRIES_SQL, [_ledger_row(), _ledger_row(entry_no=2, payload=[["a", 1]])])], "BACKEND_ERROR"),
    ("listed-other-task", "entries", [(ENTRIES_SQL, [_ledger_row(task_id="task-other")])], "BACKEND_ERROR"),
]


@pytest.mark.parametrize(("case", "operation", "answers", "reason"), LEDGER_MALFORMED, ids=[item[0] for item in LEDGER_MALFORMED])
def test_run_ledger_rejects_malformed_rows_and_driver_failures(
    sql_responder: SQLResponder, case: str, operation: str, answers: list[tuple[str, object]], reason: str
) -> None:
    sql_responder.answers = answers
    with pytest.raises(_module(LEDGER).RunLedgerError) as caught:
        LEDGER_OPERATIONS[operation](_module(LEDGER).PostgresRunLedger("postgresql://responder/ocor"))
    assert caught.value.reason_code == reason, case
    assert CANARY not in str(caught.value), case
    assert not any("pg_advisory_unlock" in statement for statement in sql_responder.statements), case


@pytest.mark.parametrize("task_id", ["", 7, None])
def test_run_ledger_rejects_an_invalid_task_before_the_backend(sql_responder: SQLResponder, task_id: object) -> None:
    with pytest.raises(_module(LEDGER).RunLedgerError) as caught:
        _module(LEDGER).PostgresRunLedger("postgresql://responder/ocor").entries(task_id)
    assert caught.value.reason_code == "SCHEMA_VIOLATION"
    assert sql_responder.statements == []


def test_run_ledger_reads_well_formed_rows(sql_responder: SQLResponder) -> None:
    ledger = _module(LEDGER).PostgresRunLedger("postgresql://responder/ocor")
    sql_responder.answers = [("information_schema.columns", _ledger_columns())]
    ledger.initialize()
    sql_responder.answers = [(INSERT_SQL, [_ledger_row()])]
    entry = _ledger_append(ledger)
    assert (entry.entry_no, entry.kind, entry.payload, entry.recorded_at) == (1, "TASK_ASSIGNED", {"capability": "act:do-thing"}, NOW)
    sql_responder.answers = [(REREAD_SQL, [_ledger_row()])]
    assert _ledger_append(ledger) == entry
    sql_responder.answers = [(ENTRIES_SQL, [_ledger_row(), _ledger_row(entry_no=2, kind="TASK_COMMITTED", idempotency_key="k2")])]
    assert [item.entry_no for item in ledger.entries("task-rem0050")] == [1, 2]


@contextlib.contextmanager
def _scratch_schema(dsn: str) -> Iterator[str]:
    """A scratch schema first on the search path of the returned DSN."""
    schema = "rem0050_shape_" + uuid.uuid4().hex[:12]
    with psycopg.connect(dsn) as connection:
        connection.execute(f'CREATE SCHEMA "{schema}"')
    try:
        yield psycopg.conninfo.make_conninfo(dsn, options=f"-c search_path={schema}")
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.mark.parametrize(
    ("table", "ddl"),
    [
        ("c3_aggregate", "CREATE TABLE c3_aggregate (tenant_id TEXT, aggregate_type TEXT, aggregate_ref TEXT, revision BIGINT)"),
        ("c3_idempotency", "CREATE TABLE c3_idempotency (tenant_id TEXT, idempotency_key TEXT, commit_ref TEXT)"),
    ],
)
def test_postgres_adapter_refuses_a_divergent_pre_existing_table(dsn: str, table: str, ddl: str) -> None:
    """Real PostgreSQL: every C3 table of SCHEMA is checked, not only five of seven."""
    with _scratch_schema(dsn) as scoped:
        with psycopg.connect(scoped) as connection:
            connection.execute(ddl)
        with pytest.raises(_module(PG).PostgresAdapterError) as caught:
            _module(PG).PostgresC3Adapter(scoped).initialize()
        assert caught.value.reason_code == "SCHEMA_MISMATCH"
        assert table in str(caught.value)


def test_run_ledger_refuses_a_divergent_pre_existing_table_and_initializes_a_fresh_one(dsn: str) -> None:
    """Real PostgreSQL: a pre-existing c8_run_ledger of another shape fails closed; in an
    empty schema the ledger initializes and appends."""
    ledger_module = _module(LEDGER)
    with _scratch_schema(dsn) as scoped:
        with psycopg.connect(scoped) as connection:
            connection.execute("CREATE TABLE c8_run_ledger (entry_no BIGSERIAL PRIMARY KEY, task_id TEXT, payload JSONB)")
        with pytest.raises(ledger_module.RunLedgerError) as caught:
            ledger_module.PostgresRunLedger(scoped).initialize()
        assert caught.value.reason_code == "SCHEMA_MISMATCH"
    with _scratch_schema(dsn) as scoped:
        ledger = ledger_module.PostgresRunLedger(scoped)
        ledger.initialize()
        ledger.initialize()
        entry = _ledger_append(ledger)
        assert (entry.entry_no, entry.payload) == (1, {"capability": "act:do-thing"})


# --- C4 projector, relay envelope, GatePackage instant ---------------------------------

MISSING = object()
CDC_EVENT_ID = "6f1d2c3b-4a59-5e6f-8a7b-9c0d1e2f3a4b"


def _committed_event(*, sequence: int | None = None, **values: object) -> Any:
    """A relayed ``canonical-ingestion-envelope:1.2`` (ADD v1.3 :531-840) of one commit, built
    here: the commit context in the payload, the relay's transport principal as effective
    principal appended to the actor chain (ADD v1.3 :197, :844), the marking inline."""
    state = {"status": "ASSESSED"}
    context = _context()
    event_context = dataclass_replace(
        context, effective_principal_id=RELAY_PRINCIPAL, actor_chain=(*context.actor_chain, RELAY_PRINCIPAL)
    )
    payload: dict[str, Any] = {
        "event_type": "canonical-state-committed", "commit_id": PG_COMMIT, "aggregate_ref": PG_REF, "from_revision": 0,
        "to_revision": 1, "state": state, "state_digest": canonical_digest(state), "ontology_release_digest": RELEASE,
        "governed_context_digest": context.digest(), "branch": "main", "governed_context": context.to_mapping(),
    }
    payload.update(values)
    payload = {key: value for key, value in payload.items() if value is not MISSING}
    revision = sequence if sequence is not None else payload.get("to_revision", 1)
    value = {
        "envelope_version": "1.2", "event_id": CDC_EVENT_ID, "tenant_id": context.tenant_id,
        "organization_id": context.organization_id, "domain_id": context.domain_id,
        "compartments": list(context.compartments), "world_ref": "urn:ocor:world:main", "ingest_mode": "CDC",
        "semantic_class": "CDC_CHANGE", "event_type_id": CANONICAL_EVENT_TYPE, "event_time": "2026-11-03T09:00:00Z",
        "ingest_time": "2026-11-03T09:00:01Z", "ordering_key": PG_REF, "idempotency_key": PG_EVENT,
        "purpose": context.purpose,
        "source": {"source_id": "urn:ocor:source:c3-canonical-state", "source_record_id": PG_EVENT,
                   "adapter_id": "urn:ocor:adapter:c3-outbox-relay", "adapter_version": "1.0.0"},
        "aggregate": {"aggregate_type_id": "urn:ocor:aggregate-type:MissionObject", "aggregate_id": PG_REF,
                      "expected_revision": revision},
        "payload_schema": {"schema_id": "urn:ocor:schema:canonical-state-committed", "schema_version": "1.0.0",
                           "schema_digest": "sha256:" + "0" * 64},
        "payload": payload, "classification_marking": Markings().resolve(DIGEST_MARKING),
        "provenance_ref": "urn:sha256:" + "9" * 64,
        "integrity": {"payload_digest": "sha256:" + "0" * 64, "source_producer_principal_ref": RELAY_PRINCIPAL},
        "effective_principal_id": RELAY_PRINCIPAL, "actor_chain": list(event_context.actor_chain),
        "governed_context_digest": event_context.digest().removeprefix("urn:"),
        "ontology_release_digest": RELEASE.removeprefix("urn:"), "policy_bundle_digest": POLICY_BUNDLE.removeprefix("urn:"),
        "correlation_id": context.correlation_id, "causation_id": None,
        "transport": {"mode": "CDC", "operation": "CREATE", "source_transaction_id": PG_COMMIT,
                      "source_position": str(revision)},
    }
    envelope_type = _module("ocor_runtime.c5.backbone").CanonicalIngestionEnvelope
    try:
        return envelope_type.from_mapping(value)
    except _module("ocor_runtime.c5.envelope").EnvelopeViolation:
        # C5 admits only I-JSON payloads; the projector's own I-JSON check is reached only by
        # an envelope whose payload is set around the C5 validation.
        built = envelope_type.from_mapping({**value, "payload": {**payload, "state": {}}})
        object.__setattr__(built, "_value", {**built.to_mapping(), "payload": payload})
        return built


def _projection_double(*, fact_revision: int | None = None, failure: BaseException | None = None, at: str = "") -> Any:
    """A C4 projection whose reads and write are local: the stored fact, if any, has
    ``fact_revision``; ``failure`` is raised by the operation named ``at``."""
    base = _module("ocor_runtime.c4.typedb_adapter").TypeDBProjectionAdapter

    class Projection(base):  # type: ignore[misc, valid-type]
        applied: list[tuple[str, str, str]] = []

        def _fail(self, operation: str) -> None:
            if failure is not None and at == operation:
                raise failure

        def position(self, branch: str, commit: str) -> int | None:
            self._fail("position")
            return None

        def _lookup_fact(self, fact_id: str) -> tuple[str, str] | None:
            self._fail("lookup")
            if fact_revision is None:
                return None
            return ("urn:ocor:commit:prior", json.dumps({"commit_id": "urn:ocor:commit:prior", "revision": fact_revision, "state": {}}))

        def apply_commit(self, *, fact_id: str, commit_id: str, payload: str) -> None:
            self._fail("apply")
            self.applied.append((fact_id, commit_id, payload))

    value = Projection(release_digest=RELEASE, ledger=c4_projection_fixture.isolated_ledger(),
                       quarantine=c4_projection_fixture.isolated_ledger())
    value.applied = []
    return value


PROJECTOR_MALFORMED: list[tuple[str, Callable[[], Any], dict[str, Any], str]] = [
    ("from-revision-missing", lambda: _committed_event(from_revision=MISSING), {}, "SCHEMA_VIOLATION"),
    ("from-revision-false", lambda: _committed_event(from_revision=False), {}, "SCHEMA_VIOLATION"),
    ("from-revision-true", lambda: _committed_event(from_revision=True, to_revision=2), {"fact_revision": 1}, "SCHEMA_VIOLATION"),
    ("from-revision-text", lambda: _committed_event(from_revision="0"), {}, "SCHEMA_VIOLATION"),
    ("from-revision-negative", lambda: _committed_event(from_revision=-1, to_revision=0, sequence=0), {}, "SCHEMA_VIOLATION"),
    ("revision-jump", lambda: _committed_event(from_revision=0, to_revision=99), {}, "SCHEMA_VIOLATION"),
    ("state-not-i-json", lambda: _committed_event(state={"x": float("nan")}), {}, "SCHEMA_VIOLATION"),
    ("position-backend-error", lambda: _committed_event(), {"failure": _module("ocor_runtime.c4.typedb_adapter").TypeDBAdapterError(CANARY), "at": "position"}, "BACKEND_ERROR"),
    ("position-unreachable", lambda: _committed_event(), {"failure": urllib.error.URLError(CANARY), "at": "position"}, "BACKEND_UNAVAILABLE"),
    ("lookup-unreachable", lambda: _committed_event(), {"failure": OSError(CANARY), "at": "lookup"}, "BACKEND_UNAVAILABLE"),
    ("apply-backend-error", lambda: _committed_event(), {"failure": _module("ocor_runtime.c4.typedb_adapter").TypeDBAdapterError(CANARY), "at": "apply"}, "BACKEND_ERROR"),
]


@pytest.mark.parametrize(("case", "event", "projection", "reason"), PROJECTOR_MALFORMED, ids=[item[0] for item in PROJECTOR_MALFORMED])
def test_projector_rejects_malformed_events_and_projection_failures(
    case: str, event: Callable[[], Any], projection: dict[str, Any], reason: str
) -> None:
    double = _projection_double(**projection)
    projector = _module("ocor_runtime.c4.projector").CanonicalStateProjector(double, release_digest=RELEASE)
    with pytest.raises(_module("ocor_runtime.c4.projector").ProjectorError) as caught:
        projector.apply(event())
    assert caught.value.reason_code == reason, case
    assert CANARY not in str(caught.value), case
    if case != "apply-backend-error":
        assert double.applied == [], case


def test_projector_applies_well_formed_events() -> None:
    first = _projection_double()
    projector = _module("ocor_runtime.c4.projector").CanonicalStateProjector(first, release_digest=RELEASE)
    assert projector.apply(_committed_event()) is True
    assert [(fact, commit) for fact, commit, _ in first.applied] == [(PG_REF, PG_COMMIT)]
    following = _projection_double(fact_revision=1)
    projector = _module("ocor_runtime.c4.projector").CanonicalStateProjector(following, release_digest=RELEASE)
    assert projector.apply(_committed_event(from_revision=1, to_revision=2)) is True
    assert json.loads(following.applied[0][2])["revision"] == 2


def _outbox_envelope(**payload: object) -> Any:
    context = _context()
    state = {"status": "ASSESSED"}
    body: dict[str, Any] = {
        "event_type": "canonical-state-committed", "commit_id": PG_COMMIT, "aggregate_ref": PG_REF, "to_revision": 1,
        "branch": "main",
        "boundary": {"tenant_id": context.tenant_id, "domain_id": context.domain_id,
                     "compartments": list(context.compartments), "classification_marking_ref": DIGEST_MARKING,
                     "purpose": context.purpose},
        "correlation_id": "018f2f95-01b2-7cc3-8d4e-1234567890ab", "causation_id": "urn:ocor:action-instance:rem0050:x",
        "governed_context_digest": context.digest(), "governed_context": context.to_mapping(),
        "tenant_id": context.tenant_id, "actor_chain": list(context.actor_chain), "ontology_release_digest": RELEASE,
        "from_revision": 0, "aggregate_type": AGGREGATE_TYPE, "state": state, "state_digest": canonical_digest(state),
        "gate_package_digest": "urn:sha256:" + "9" * 64,
    }
    body.update(payload)
    body = {key: value for key, value in body.items() if value is not MISSING}
    return _module("ocor_runtime.c3.ports").OutboxEnvelope(
        event_id=PG_EVENT, commit_id=PG_COMMIT, aggregate_ref=PG_REF, aggregate_revision=1, payload=body,
        payload_digest=canonical_digest(body), branch="main", occurred_at=NOW,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"correlation_id": MISSING},
        {"causation_id": ""},
        {"governed_context_digest": 7},
        {"boundary": {}},
        {"boundary": {"classification_marking_ref": None}},
    ],
    ids=["correlation-missing", "causation-empty", "gcs-not-text", "marking-missing", "marking-null"],
)
def test_relay_refuses_an_outbox_entry_without_its_event_context(payload: dict[str, object]) -> None:
    with pytest.raises(C3Error) as caught:
        _module("ocor_runtime.c3.relay").canonical_event(
            _outbox_envelope(**payload), signer=_relay_signer(), principal=RELAY_PRINCIPAL, markings=Markings(),
            ingest_time=NOW,
        )
    assert caught.value.reason_code == "COMMIT_RECEIPT_MISMATCH"


def test_relay_builds_the_event_of_a_complete_outbox_entry() -> None:
    envelope = _module("ocor_runtime.c3.relay").canonical_event(
        _outbox_envelope(), signer=_relay_signer(), principal=RELAY_PRINCIPAL, markings=Markings(), ingest_time=NOW
    ).envelope
    assert (
        envelope["source"]["source_record_id"],
        envelope.aggregate["expected_revision"],
        "urn:" + envelope["classification_marking"]["marking_digest"],
    ) == (PG_EVENT, 1, DIGEST_MARKING)


@pytest.mark.parametrize("frozen_at", ["yesterday", "2026-11-03T09:00:00+01:00", 7, None])
def test_admission_refuses_a_gate_package_frozen_at_that_is_not_a_utc_instant(frozen_at: object) -> None:
    records, fence, clock = RecordStore(), Fence(), InMemoryTrustedClock(NOW)
    path = GovernedPath(records, fence, clock, aggregate_ref=f"urn:ocor:mission-object:rem0050:{uuid.uuid4().hex[:8]}")
    digest = path.freeze(gate_package=path.gate_package_payload(frozen_at=frozen_at))
    with pytest.raises(C3Error) as caught:
        _admission(records, fence, clock).admit(path.command(digest))
    assert caught.value.reason_code == "GATE_PACKAGE_MISMATCH"


def test_admission_admits_a_gate_package_frozen_at_a_utc_instant() -> None:
    records, fence, clock = RecordStore(), Fence(), InMemoryTrustedClock(NOW)
    path = GovernedPath(records, fence, clock, aggregate_ref=f"urn:ocor:mission-object:rem0050:{uuid.uuid4().hex[:8]}")
    command = path.command(path.freeze())
    assert _admission(records, fence, clock).admit(command).gate_package_digest == command.gate_package_digest
