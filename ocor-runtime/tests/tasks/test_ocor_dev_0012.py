from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest
from ocor_runtime.c2.ports import (
    AuthorityResolutionPort,
    C2Error,
    ConsistencyMode,
    ConsistencyRequirement,
    EvidenceReadPort,
    NamedQueryPort,
    NamedQueryRequest,
    NamedQueryResponse,
    PolicyDecisionPort,
    ProjectionReadPort,
    ServedContext,
    Watermark,
    WatermarkPort,
)
from ocor_runtime.kernel.governed_context import GovernedContext

DIGEST_A = "urn:sha256:" + "a" * 64
DIGEST_B = "urn:sha256:" + "b" * 64
DIGEST_C = "urn:sha256:" + "c" * 64
NOW = datetime(2026, 9, 2, 4, 0, tzinfo=UTC)


@pytest.fixture
def context() -> GovernedContext:
    return GovernedContext.from_mapping(
        {
            "tenant_id": "urn:ocor:tenant:synthetic",
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": ["urn:ocor:compartment:alpha"],
            "classification_marking_ref": DIGEST_A,
            "purpose": "synthetic-query",
            "effective_principal_id": "spiffe://ocor.test/workload/query-gateway",
            "actor_chain": ["urn:ocor:actor:analyst", "urn:ocor:actor:gateway"],
            "ontology_release_digest": DIGEST_B,
            "policy_bundle_digest": DIGEST_C,
            "correlation_id": "018f2f95-01b2-7cc3-8d4e-123456789abc",
        }
    )


@pytest.fixture
def query_request(context: GovernedContext) -> NamedQueryRequest:
    return NamedQueryRequest.from_mapping(
        {
            "request_id": "018f2f95-01b2-7cc3-8d4e-123456789abd",
            "contract_id": "urn:ocor:contract:named-query:objects-by-status",
            "contract_version": "1.0.0",
            "contract_digest": DIGEST_A,
            "parameters": {"status": "ACTIVE"},
            "governed_context": context.to_mapping(),
            "governed_context_digest": context.digest(),
            "consistency": {"mode": "AT_LEAST_COMMIT", "required_commit": "commit-42", "wait_timeout_ms": 5000},
        }
    )


def served(context: GovernedContext, *, commit: str = "commit-42") -> ServedContext:
    return ServedContext(
        branch="main",
        ontology_release_digest=context.ontology_release_digest,
        canonical_commit=commit,
        projection_watermark=commit,
        staleness_ms=0,
        governed_context_digest=context.digest(),
        policy_bundle_digest=context.policy_bundle_digest,
    )


def test_named_query_request_binds_identity_purpose_policy_and_consistency(
    query_request: NamedQueryRequest, context: GovernedContext
):
    assert query_request.governed_context.effective_principal_id == context.effective_principal_id
    assert query_request.governed_context.purpose == "synthetic-query"
    assert query_request.governed_context.policy_bundle_digest == DIGEST_C
    assert query_request.consistency.required_commit == "commit-42"
    assert query_request.isolation_key == context.isolation_key()


def test_request_is_deeply_immutable(query_request: NamedQueryRequest):
    with pytest.raises(FrozenInstanceError):
        query_request.contract_version = "2.0.0"  # type: ignore[misc]
    with pytest.raises(TypeError):
        query_request.parameters["status"] = "CHANGED"  # type: ignore[index]


@pytest.mark.parametrize("extra", ["query", "query_text", "sparql", "sql", "typeql"])
def test_arbitrary_query_text_is_rejected(query_request: NamedQueryRequest, extra: str):
    value = query_request.to_mapping()
    value[extra] = "SELECT *"
    with pytest.raises(C2Error) as exc_info:
        NamedQueryRequest.from_mapping(value)
    # NCP-U03 (NCR-C2-006): closed request schema, SCHEMA_VIOLATION of the closed Problem enum --
    # ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:459
    assert exc_info.value.reason_code == "SCHEMA_VIOLATION"


def test_empty_purpose_is_rejected_before_routing(query_request: NamedQueryRequest):
    value = query_request.to_mapping()
    value["governed_context"]["purpose"] = ""  # type: ignore[index]
    with pytest.raises(C2Error) as exc_info:
        NamedQueryRequest.from_mapping(value)
    # NCP-U03 (NCR-C2-006): Query surface, absent GCS field -> DENY without lookup --
    # ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:380
    assert exc_info.value.reason_code == "POLICY_DENIED"


def test_mismatched_gcs_digest_is_rejected(query_request: NamedQueryRequest):
    value = query_request.to_mapping()
    value["governed_context_digest"] = DIGEST_A
    with pytest.raises(C2Error) as exc_info:
        NamedQueryRequest.from_mapping(value)
    # NCP-U03 (NCR-C2-006): Query surface, GCS mismatch -> DENY without lookup --
    # ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:380
    assert exc_info.value.reason_code == "POLICY_DENIED"


@pytest.mark.parametrize(
    "value",
    [
        {"mode": "AT_LEAST_COMMIT"},
        {"mode": "EXACT_AT_COMMIT"},
        # NCP-U03 (NCR-C2-009): BEST_AVAILABLE may declare required_commit (contract :126-141);
        # the case keeps its shape with a contract-invalid empty required_commit (minLength 1, :133)
        {"mode": "BEST_AVAILABLE", "required_commit": ""},
        {"mode": "AT_LEAST_COMMIT", "required_commit": "commit-42", "wait_timeout_ms": 30001},
    ],
)
def test_invalid_consistency_contract_is_rejected(value: dict[str, object]):
    with pytest.raises(C2Error) as exc_info:
        ConsistencyRequirement.from_mapping(value)
    # NCP-U03 (NCR-C2-006): SCHEMA_VIOLATION of the closed Problem enum --
    # ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:459
    assert exc_info.value.reason_code == "SCHEMA_VIOLATION"


def test_exact_consistency_cannot_silently_downgrade(context: GovernedContext):
    requirement = ConsistencyRequirement(ConsistencyMode.EXACT_AT_COMMIT, "commit-42", 0)
    with pytest.raises(C2Error) as exc_info:
        requirement.verify_served(served(context, commit="commit-41"))
    # NCP-U03 (NCR-C2-012): PROJECTION_NOT_READY, never a downgrade -- docs/OCOR_LLD_v1.1.md:369
    assert exc_info.value.reason_code == "PROJECTION_NOT_READY"


def test_at_least_commit_requires_ready_watermark(context: GovernedContext):
    requirement = ConsistencyRequirement(ConsistencyMode.AT_LEAST_COMMIT, "commit-42", 5000)
    with pytest.raises(C2Error) as exc_info:
        requirement.verify_served(served(context, commit="commit-41"))
    assert exc_info.value.reason_code == "PROJECTION_NOT_READY"


def test_best_available_declares_staleness(context: GovernedContext):
    requirement = ConsistencyRequirement(ConsistencyMode.BEST_AVAILABLE)
    stale = replace(served(context), staleness_ms=2300)
    assert requirement.verify_served(stale) == stale
    assert stale.staleness_ms == 2300


def test_served_context_rejects_policy_or_gcs_drift(
    query_request: NamedQueryRequest, context: GovernedContext
):
    for change in ({"policy_bundle_digest": DIGEST_A}, {"governed_context_digest": DIGEST_A}):
        with pytest.raises(C2Error) as exc_info:
            query_request.verify_served(replace(served(context), **change))
        assert exc_info.value.reason_code == "STALE_CONTEXT"


def test_named_query_response_preserves_served_watermark(
    query_request: NamedQueryRequest, context: GovernedContext
):
    response = NamedQueryResponse(
        request_id=query_request.request_id,
        result_ref="urn:ocor:result:query:1",
        result_digest=DIGEST_A,
        served=served(context),
    )
    assert response.served.projection_watermark == "commit-42"
    assert response.served.branch == "main"


def test_watermark_is_version_and_branch_bound(context: GovernedContext):
    watermark = Watermark(
        projection_id="urn:ocor:projection:logic",
        branch="main",
        ontology_release_digest=context.ontology_release_digest,
        canonical_commit="commit-42",
        observed_at=NOW,
    )
    assert watermark.canonical_commit == "commit-42"
    with pytest.raises(FrozenInstanceError):
        watermark.branch = "scenario"  # type: ignore[misc]


class QueryHandler:
    def execute(self, request: NamedQueryRequest) -> NamedQueryResponse:
        return NamedQueryResponse(request.request_id, "urn:ocor:result:1", DIGEST_A, served(request.governed_context))


def test_all_c2_ports_are_runtime_checkable():
    assert isinstance(QueryHandler(), NamedQueryPort)
    assert not isinstance(object(), ProjectionReadPort)
    assert not isinstance(object(), PolicyDecisionPort)
    assert not isinstance(object(), AuthorityResolutionPort)
    assert not isinstance(object(), EvidenceReadPort)
    assert not isinstance(object(), WatermarkPort)
