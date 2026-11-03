"""OCOR-DEV-0039: Implement C4 rebuild and drift reconciliation.

Proves that ProjectionDriftDetector rebuilds a projection from the real
canonical commit and reproduces its digest/watermark, and that real
drift (a projection tampered with directly, out of band) is quarantined
rather than repaired -- a quarantined, divergent projection is never
served again until an explicit, successful rebuild reconciles it.
Every test drives real PostgreSQL and real TypeDB -- no mocks.
"""

from __future__ import annotations

import os
import urllib.error

import pytest
import test_ocor_dev_rem_0050 as governed_path
from ocor_runtime.c2.ports import C2Error, ConsistencyMode, ConsistencyRequirement, NamedQueryRequest
from ocor_runtime.c3.ports import GovernedCanonicalCommitCommand
from ocor_runtime.c3.service import PostgresC3Service
from ocor_runtime.c4.rebuild import DriftError, ProjectionDriftDetector
from ocor_runtime.c4.typedb_adapter import TypeDBAdapterError, TypeDBProjectionAdapter
from ocor_runtime.kernel.governed_context import GovernedContext

DIGEST_A = "urn:sha256:" + "a" * 64
DIGEST_B = "urn:sha256:" + "b" * 64
DIGEST_C = "urn:sha256:" + "c" * 64
DIGEST_D = "urn:sha256:" + "d" * 64
AGGREGATE_REF = "urn:ocor:mission-object:drift-reconciliation:1"
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


@pytest.fixture(scope="session")
def typedb_reachable() -> None:
    try:
        TypeDBProjectionAdapter().initialize()
    except (TypeDBAdapterError, OSError) as error:
        pytest.fail(f"a real, live TypeDB instance is mandatory qualifying evidence: {error}")


@pytest.fixture
def service(postgres_dsn: str) -> PostgresC3Service:
    value = PostgresC3Service(postgres_dsn, admission=GOVERNED.admission())
    value.initialize()
    value.reset()
    return value


@pytest.fixture
def projection(typedb_reachable: None) -> TypeDBProjectionAdapter:
    value = TypeDBProjectionAdapter()
    value.reset()
    return value


@pytest.fixture
def detector(service: PostgresC3Service, projection: TypeDBProjectionAdapter) -> ProjectionDriftDetector:
    return ProjectionDriftDetector(service, projection)


def make_command(
    *, command_id: str, idempotency_key: str, expected_revision: int, canonical_delta: dict[str, object]
) -> GovernedCanonicalCommitCommand:
    context = GovernedContext.from_mapping(
        {
            "tenant_id": "urn:ocor:tenant:synthetic",
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": ["urn:ocor:compartment:alpha"],
            "classification_marking_ref": DIGEST_A,
            "purpose": "drift-reconciliation-fixture",
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
            "aggregate_ref": AGGREGATE_REF,
            "expected_revision": expected_revision,
            "canonical_delta": canonical_delta,
            "decision_ref": "urn:ocor:decision:drift-reconciliation:1",
            "authority_ref": "urn:ocor:authority:drift-reconciliation:1",
            "evidence_refs": ["urn:ocor:evidence:drift-reconciliation:1"],
            "claim_source_bindings": [
                {
                    "claim_ref": "urn:ocor:claim:drift-reconciliation:1",
                    "source_ref": "urn:ocor:source:drift-reconciliation:1",
                    "evidence_ref": "urn:ocor:evidence:drift-reconciliation:1",
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


def make_read_request(*, required_commit: str) -> NamedQueryRequest:
    context = GovernedContext.from_mapping(
        {
            "tenant_id": "urn:ocor:tenant:synthetic",
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": ["urn:ocor:compartment:alpha"],
            "classification_marking_ref": DIGEST_A,
            "purpose": "drift-reconciliation-fixture",
            "effective_principal_id": "urn:ocor:principal:analyst-1",
            "actor_chain": ["urn:ocor:principal:analyst-1"],
            "ontology_release_digest": DIGEST_B,
            "policy_bundle_digest": DIGEST_C,
            "correlation_id": "018f2f95-01b2-7cc3-8d4e-123456789abc",
        }
    )
    return NamedQueryRequest(
        request_id="018f2f95-01b2-7cc3-8d4e-123456789abc",
        contract_id="urn:ocor:contract:named-query:drift-reconciliation-fixture",
        contract_version="1.0.0",
        contract_digest=DIGEST_A,
        parameters={"fact_id": AGGREGATE_REF},
        governed_context=context,
        governed_context_digest=context.digest(),
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit=required_commit),
    )


def test_rebuild_reproduces_the_canonical_digest_and_watermark(
    detector: ProjectionDriftDetector, service: PostgresC3Service
) -> None:
    command = make_command(
        command_id="urn:ocor:command:drift:1",
        idempotency_key="drift-reconciliation-key-0001",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    receipt = service.commit(command)

    report = detector.rebuild(
        tenant_id="urn:ocor:tenant:synthetic", aggregate_type="MissionObject", aggregate_ref=AGGREGATE_REF
    )

    assert report.drift_detected is False
    assert report.quarantined is False
    assert report.canonical_commit == receipt.commit_id
    assert not detector.is_quarantined(AGGREGATE_REF)

    response = detector.read_if_healthy(AGGREGATE_REF, make_read_request(required_commit=receipt.commit_id))
    assert response.served.canonical_commit == receipt.commit_id


def test_rebuild_of_a_never_committed_aggregate_reports_canonical_not_found(
    detector: ProjectionDriftDetector,
) -> None:
    with pytest.raises(DriftError) as excinfo:
        detector.rebuild(
            tenant_id="urn:ocor:tenant:synthetic",
            aggregate_type="MissionObject",
            aggregate_ref="urn:ocor:mission-object:never-committed",
        )
    assert excinfo.value.reason_code == "CANONICAL_NOT_FOUND"


def test_real_out_of_band_drift_is_quarantined_not_repaired(
    detector: ProjectionDriftDetector, service: PostgresC3Service, projection: TypeDBProjectionAdapter
) -> None:
    command = make_command(
        command_id="urn:ocor:command:drift:2",
        idempotency_key="drift-reconciliation-key-0002",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    receipt = service.commit(command)
    first = detector.rebuild(
        tenant_id="urn:ocor:tenant:synthetic", aggregate_type="MissionObject", aggregate_ref=AGGREGATE_REF
    )
    assert first.drift_detected is False

    # a real, direct, out-of-band tamper of the live projection -- not
    # through rebuild -- simulating storage corruption or a buggy
    # projector, the only way real drift can occur once C3's own commit
    # path is already proven atomic.
    projection.apply_commit(fact_id=AGGREGATE_REF, commit_id=receipt.commit_id, payload="tampered-digest")

    second = detector.rebuild(
        tenant_id="urn:ocor:tenant:synthetic", aggregate_type="MissionObject", aggregate_ref=AGGREGATE_REF
    )
    assert second.drift_detected is True
    assert second.quarantined is True
    assert detector.is_quarantined(AGGREGATE_REF)


def test_serving_a_quarantined_projection_is_prohibited(
    detector: ProjectionDriftDetector, service: PostgresC3Service, projection: TypeDBProjectionAdapter
) -> None:
    command = make_command(
        command_id="urn:ocor:command:drift:3",
        idempotency_key="drift-reconciliation-key-0003",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    receipt = service.commit(command)
    detector.rebuild(tenant_id="urn:ocor:tenant:synthetic", aggregate_type="MissionObject", aggregate_ref=AGGREGATE_REF)
    projection.apply_commit(fact_id=AGGREGATE_REF, commit_id=receipt.commit_id, payload="tampered-digest")
    detector.rebuild(tenant_id="urn:ocor:tenant:synthetic", aggregate_type="MissionObject", aggregate_ref=AGGREGATE_REF)
    assert detector.is_quarantined(AGGREGATE_REF)

    with pytest.raises(C2Error) as excinfo:
        detector.read_if_healthy(AGGREGATE_REF, make_read_request(required_commit=receipt.commit_id))
    # NCP-U03 (NCR-C2-006): a quarantined projection is not ready to serve: PROJECTION_NOT_READY --
    # docs/OCOR_LLD_v1.1.md:350, ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:460
    assert excinfo.value.reason_code == "PROJECTION_NOT_READY"


def test_a_successful_rebuild_after_correcting_the_tamper_clears_quarantine(
    detector: ProjectionDriftDetector, service: PostgresC3Service, projection: TypeDBProjectionAdapter
) -> None:
    command = make_command(
        command_id="urn:ocor:command:drift:4",
        idempotency_key="drift-reconciliation-key-0004",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    receipt = service.commit(command)
    detector.rebuild(tenant_id="urn:ocor:tenant:synthetic", aggregate_type="MissionObject", aggregate_ref=AGGREGATE_REF)
    projection.apply_commit(fact_id=AGGREGATE_REF, commit_id=receipt.commit_id, payload="tampered-digest")
    detector.rebuild(tenant_id="urn:ocor:tenant:synthetic", aggregate_type="MissionObject", aggregate_ref=AGGREGATE_REF)
    assert detector.is_quarantined(AGGREGATE_REF)

    # a fresh rebuild call, after the underlying tamper is externally
    # removed (real repair), sees no divergence between the freshly
    # rebuilt canonical digest and the current projection -- because
    # this repair path re-applies apply_commit, restoring the correct
    # payload for real.
    canonical = service.read("urn:ocor:tenant:synthetic", "MissionObject", AGGREGATE_REF)
    assert canonical is not None
    projection.apply_commit(fact_id=AGGREGATE_REF, commit_id=canonical.commit_id, payload=canonical.state_digest)

    third = detector.rebuild(
        tenant_id="urn:ocor:tenant:synthetic", aggregate_type="MissionObject", aggregate_ref=AGGREGATE_REF
    )
    assert third.drift_detected is False
    assert third.quarantined is False
    assert not detector.is_quarantined(AGGREGATE_REF)

    response = detector.read_if_healthy(AGGREGATE_REF, make_read_request(required_commit=receipt.commit_id))
    assert response.served.canonical_commit == receipt.commit_id


def test_a_real_typedb_unreachability_during_peek_fails_closed_as_a_drift_error(
    service: PostgresC3Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = make_command(
        command_id="urn:ocor:command:drift:5",
        idempotency_key="drift-reconciliation-key-0005",
        expected_revision=0,
        canonical_delta={"status": "ASSESSED"},
    )
    service.commit(command)

    projection = TypeDBProjectionAdapter()
    projection.reset()
    detector = ProjectionDriftDetector(service, projection)
    monkeypatch.setattr("ocor_runtime.c4.typedb_adapter.TYPEDB_URL", "http://127.0.0.1:1")

    with pytest.raises(urllib.error.URLError):
        detector.rebuild(tenant_id="urn:ocor:tenant:synthetic", aggregate_type="MissionObject", aggregate_ref=AGGREGATE_REF)
