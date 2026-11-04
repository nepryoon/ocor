"""OCOR-DEV-0037: Implement C4 TypeDB projection adapter.

Proves that the retained TypeDBProjectionAdapter commits a fact and its
watermark atomically in one real TypeDB transaction, and that
exact-at-commit behavior matches the sealed C2 consistency contract
(ocor_runtime.c2.ports, OCOR-DEV-0012): a stale projection can never
masquerade as exact. Every test drives a real, live TypeDB instance --
no mocks.
"""

from __future__ import annotations

import pytest
import c4_projection_fixture
from ocor_runtime.c2.ports import (
    C2Error,
    ConsistencyMode,
    ConsistencyRequirement,
    NamedQueryRequest,
    ProjectionReadPort,
    WatermarkPort,
)
from ocor_runtime.c4.typedb_adapter import TypeDBAdapterError, TypeDBProjectionAdapter
from ocor_runtime.kernel.governed_context import GovernedContext

DIGEST_A = "urn:sha256:" + "a" * 64
DIGEST_B = "urn:sha256:" + "b" * 64
DIGEST_C = "urn:sha256:" + "c" * 64


@pytest.fixture(scope="session")
def typedb_reachable() -> None:
    try:
        c4_projection_fixture.projection().initialize()
    except (TypeDBAdapterError, OSError) as error:
        pytest.fail(f"a real, live TypeDB instance is mandatory qualifying evidence: {error}")


@pytest.fixture
def adapter(typedb_reachable: None) -> TypeDBProjectionAdapter:
    value = c4_projection_fixture.projection()
    value.reset()
    return value


def make_request(*, fact_id: str, consistency: ConsistencyRequirement) -> NamedQueryRequest:
    context = GovernedContext.from_mapping(
        {
            "tenant_id": "urn:ocor:tenant:synthetic",
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": ["urn:ocor:compartment:alpha"],
            "classification_marking_ref": DIGEST_A,
            "purpose": "c4-typedb-retained-fixture",
            "effective_principal_id": "spiffe://ocor.test/workload/c6",
            "actor_chain": ["urn:ocor:actor:synthetic", "urn:ocor:actor:c6"],
            "ontology_release_digest": DIGEST_B,
            "policy_bundle_digest": DIGEST_C,
            "correlation_id": "018f2f95-01b2-7cc3-8d4e-123456789abc",
        }
    )
    return NamedQueryRequest(
        request_id="018f2f95-01b2-7cc3-8d4e-123456789abc",
        contract_id="urn:ocor:contract:named-query:c4-typedb-retained",
        contract_version="1.0.0",
        contract_digest=DIGEST_A,
        parameters={"fact_id": fact_id},
        governed_context=context,
        governed_context_digest=context.digest(),
        consistency=consistency,
    )


def test_adapter_conforms_to_the_sealed_ports(adapter: TypeDBProjectionAdapter) -> None:
    assert isinstance(adapter, ProjectionReadPort)
    assert isinstance(adapter, WatermarkPort)


def test_apply_commit_advances_fact_and_watermark_together(adapter: TypeDBProjectionAdapter) -> None:
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")

    request = make_request(
        fact_id="fact-1",
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-1"),
    )
    response = adapter.read(request)

    assert response.served.canonical_commit == "commit-1"
    assert response.served.projection_watermark == "commit-1"
    assert adapter.current("urn:ocor:projection:c4-typedb-retained", "main").canonical_commit == "commit-1"


def test_apply_commit_replaces_a_prior_fact_and_watermark_atomically(adapter: TypeDBProjectionAdapter) -> None:
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-2", payload="V2")

    request = make_request(
        fact_id="fact-1",
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-2"),
    )
    response = adapter.read(request)
    assert response.served.canonical_commit == "commit-2"
    assert response.result_digest.startswith("urn:sha256:")


def test_exact_at_commit_never_masquerades_a_stale_projection_as_exact(adapter: TypeDBProjectionAdapter) -> None:
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    # a request pinned to a NEWER commit than what has actually landed.
    request = make_request(
        fact_id="fact-1",
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-2"),
    )

    with pytest.raises(C2Error) as excinfo:
        adapter.read(request)
    # NCP-U03 (NCR-C2-012): PROJECTION_NOT_READY, never a downgrade -- docs/OCOR_LLD_v1.1.md:369
    assert excinfo.value.reason_code == "PROJECTION_NOT_READY"


def test_at_least_commit_reports_projection_not_ready_before_the_commit_lands(
    adapter: TypeDBProjectionAdapter,
) -> None:
    request = make_request(
        fact_id="fact-1",
        consistency=ConsistencyRequirement(mode=ConsistencyMode.AT_LEAST_COMMIT, required_commit="commit-1"),
    )
    with pytest.raises(C2Error) as excinfo:
        adapter.read(request)
    assert excinfo.value.reason_code == "PROJECTION_NOT_READY"

    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    caught_up = adapter.read(request)
    assert caught_up.served.canonical_commit == "commit-1"


def test_best_available_serves_whatever_watermark_is_currently_true(adapter: TypeDBProjectionAdapter) -> None:
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    request = make_request(fact_id="fact-1", consistency=ConsistencyRequirement(mode=ConsistencyMode.BEST_AVAILABLE))

    response = adapter.read(request)
    assert response.served.staleness_ms == 0
    assert response.served.canonical_commit == "commit-1"


def test_result_not_found_is_reached_only_after_consistency_is_confirmed(adapter: TypeDBProjectionAdapter) -> None:
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    # a different, never-ingested fact at the same real, caught-up watermark.
    request = make_request(
        fact_id="fact-never-ingested",
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-1"),
    )

    with pytest.raises(C2Error) as excinfo:
        adapter.read(request)
    # NCP-U03 (NCR-C2-006): an absent result is indistinguishable from a denial (no existence
    # disclosure through errors): POLICY_DENIED --
    # ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md:50,
    # ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:454
    assert excinfo.value.reason_code == "POLICY_DENIED"


def test_a_real_typedb_unreachability_fails_closed_never_serving_a_fabricated_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ocor_runtime.c4.typedb_adapter.TYPEDB_URL", "http://127.0.0.1:1")
    adapter = c4_projection_fixture.projection()

    # NCP-U05 (NCR-C4-003): the adapter's typed error with reason code PROJECTION_NOT_READY, never a
    # raw transport error -- ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:486-491,
    # docs/OCOR_LLD_v1.1.md:346; PO decision NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 5, NCP-U05 row
    with pytest.raises(TypeDBAdapterError) as excinfo:
        adapter.current_watermark()
    assert excinfo.value.reason_code == "PROJECTION_NOT_READY"
