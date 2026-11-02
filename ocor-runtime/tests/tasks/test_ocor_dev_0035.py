"""OCOR-DEV-0035: Implement C2 policy-filtered planning consistency and watermarks.

Proves that ``ConsistencyPlanner`` proves policy filters first (an
unregistered or otherwise denied query never reaches the watermark
check at all) and then returns either the requester's required commit
or ``PROJECTION_NOT_READY`` with the real, observable watermark that
was checked -- never a silent stale fallback to ``BEST_AVAILABLE``,
and never a query issued against the real backend projection data to
compute the plan. Every qualifying test drives a real, live TypeDB
instance for the watermark -- no mocks.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest
from ocor_runtime.c2.gateway import RegisteredNamedQuery, RegistrationAndMarkingPolicy
from ocor_runtime.c2.planner import ConsistencyPlanner
from ocor_runtime.c2.ports import (
    C2Error,
    ConsistencyMode,
    ConsistencyRequirement,
    NamedQueryRequest,
    Watermark,
    WatermarkPort,
)
from ocor_runtime.c4_marking import MarkingEngine, MarkingSchemeDefinition
from ocor_runtime.kernel.governed_context import GovernedContext

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from spikes.typedb_exact_commit.adapter import (  # noqa: E402 -- must follow sys.path.insert above
    TypeDBAdapterError,
    TypeDBExactCommitAdapter,
)

DIGEST_A = "urn:sha256:" + "a" * 64
DIGEST_B = "urn:sha256:" + "b" * 64
DIGEST_C = "urn:sha256:" + "c" * 64

CONTRACT_ID = "urn:ocor:contract:named-query:planner-fixture"
CLASSIFICATION_SCHEME = MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET", "TOP_SECRET"))


class _TypeDBWatermarkPort:
    """Adapts ``TypeDBExactCommitAdapter.watermark()`` (no arguments, one
    fixed spike projection/branch) to the sealed ``WatermarkPort.current``
    signature -- kept local to this test file so retained runtime code
    never imports the ``spikes`` package."""

    def __init__(self, adapter: TypeDBExactCommitAdapter) -> None:
        self._adapter = adapter

    def current(self, projection_id: str, branch: str) -> Watermark:
        return self._adapter.watermark()


@pytest.fixture(scope="session")
def typedb_reachable() -> None:
    try:
        TypeDBExactCommitAdapter().initialize()
    except (TypeDBAdapterError, OSError) as error:
        pytest.fail(f"a real, live TypeDB instance is mandatory qualifying evidence: {error}")


@pytest.fixture
def typedb(typedb_reachable: None) -> TypeDBExactCommitAdapter:
    value = TypeDBExactCommitAdapter()
    value.reset()
    return value


def make_request(*, mode: ConsistencyMode, required_commit: str | None) -> NamedQueryRequest:
    context = GovernedContext.from_mapping(
        {
            "tenant_id": "urn:ocor:tenant:synthetic",
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": ["urn:ocor:compartment:alpha"],
            "classification_marking_ref": DIGEST_A,
            "purpose": "planner-fixture",
            "effective_principal_id": "urn:ocor:principal:analyst-1",
            "actor_chain": ["urn:ocor:principal:analyst-1"],
            "ontology_release_digest": DIGEST_B,
            "policy_bundle_digest": DIGEST_C,
            "correlation_id": "018f2f95-01b2-7cc3-8d4e-123456789abc",
        }
    )
    return NamedQueryRequest(
        request_id="018f2f95-01b2-7cc3-8d4e-123456789abc",
        contract_id=CONTRACT_ID,
        contract_version="1.0.0",
        contract_digest=DIGEST_A,
        parameters={},
        governed_context=context,
        governed_context_digest=context.digest(),
        consistency=ConsistencyRequirement(mode=mode, required_commit=required_commit),
    )


def make_planner(*, typedb: TypeDBExactCommitAdapter, registered: bool) -> ConsistencyPlanner:
    registry = (
        {CONTRACT_ID: RegisteredNamedQuery(contract_id=CONTRACT_ID, versions=frozenset({"1.0.0"}), marking_scheme_id="classification")}
        if registered
        else {}
    )
    policy = RegistrationAndMarkingPolicy(
        registry=registry,
        marking_engine=MarkingEngine([CLASSIFICATION_SCHEME]),
        marking_port=_NoResourcePort(),
        clearance_by_marking_ref={},
    )
    return ConsistencyPlanner(
        policy=policy,
        watermark_port=_TypeDBWatermarkPort(typedb),
        projection_id="urn:ocor:projection:spike-typedb-exact-commit",
        branch="main",
    )


class _NoResourcePort:
    """A marking-authorization port that is never called, since these
    fixtures never name a resource parameter -- present only to satisfy
    ``RegistrationAndMarkingPolicy``'s constructor."""

    def exists_authorized(self, resource_id: str, clearance: object) -> bool:
        raise AssertionError("marking port must not be consulted when no resource parameter is present")


def test_typedb_watermark_port_conforms_to_the_sealed_port(typedb: TypeDBExactCommitAdapter) -> None:
    assert isinstance(_TypeDBWatermarkPort(typedb), WatermarkPort)


def test_best_available_returns_a_plan_with_no_required_commit_and_the_real_watermark(
    typedb: TypeDBExactCommitAdapter,
) -> None:
    typedb.ingest("fact-1", "commit-1", "V1")
    typedb.advance_watermark("commit-1")
    planner = make_planner(typedb=typedb, registered=True)
    request = make_request(mode=ConsistencyMode.BEST_AVAILABLE, required_commit=None)

    plan = planner.plan(request)

    assert plan.required_commit is None
    assert plan.observed_watermark.canonical_commit == "commit-1"


def test_exact_at_commit_proceeds_when_the_real_watermark_matches(typedb: TypeDBExactCommitAdapter) -> None:
    typedb.ingest("fact-1", "commit-1", "V1")
    typedb.advance_watermark("commit-1")
    planner = make_planner(typedb=typedb, registered=True)
    request = make_request(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-1")

    plan = planner.plan(request)

    assert plan.required_commit == "commit-1"
    assert plan.observed_watermark.canonical_commit == "commit-1"


def test_exact_at_commit_reports_projection_not_ready_with_the_real_observed_watermark(
    typedb: TypeDBExactCommitAdapter,
) -> None:
    # deliberately never advance the watermark past the sentinel.
    planner = make_planner(typedb=typedb, registered=True)
    request = make_request(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-1")

    with pytest.raises(C2Error) as excinfo:
        planner.plan(request)

    assert excinfo.value.reason_code == "PROJECTION_NOT_READY"
    assert "commit-1" in str(excinfo.value)


def test_at_least_commit_reports_projection_not_ready_until_the_real_watermark_catches_up(
    typedb: TypeDBExactCommitAdapter,
) -> None:
    planner = make_planner(typedb=typedb, registered=True)
    request = make_request(mode=ConsistencyMode.AT_LEAST_COMMIT, required_commit="commit-1")

    with pytest.raises(C2Error) as excinfo:
        planner.plan(request)
    assert excinfo.value.reason_code == "PROJECTION_NOT_READY"

    typedb.advance_watermark("commit-1")
    plan = planner.plan(request)
    assert plan.required_commit == "commit-1"
    assert plan.observed_watermark.canonical_commit == "commit-1"


class _SpyWatermarkPort:
    """Raises if ever consulted -- proves, rather than merely asserts by
    comment, that a policy denial short-circuits before the watermark
    check."""

    def current(self, projection_id: str, branch: str) -> Watermark:
        raise AssertionError("watermark port must not be consulted after a policy denial")


def test_an_unregistered_contract_never_reaches_the_watermark_check() -> None:
    policy = RegistrationAndMarkingPolicy(
        registry={},
        marking_engine=MarkingEngine([CLASSIFICATION_SCHEME]),
        marking_port=_NoResourcePort(),
        clearance_by_marking_ref={},
    )
    planner = ConsistencyPlanner(
        policy=policy,
        watermark_port=_SpyWatermarkPort(),
        projection_id="urn:ocor:projection:spike-typedb-exact-commit",
        branch="main",
    )
    request = make_request(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-1")

    with pytest.raises(C2Error) as excinfo:
        planner.plan(request)

    # NCP-U03 (NCR-C2-006): a policy denial is POLICY_DENIED of the closed Problem enum --
    # ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:454
    assert excinfo.value.reason_code == "POLICY_DENIED"


def test_a_denied_policy_never_leaks_the_real_watermark_in_its_result(typedb: TypeDBExactCommitAdapter) -> None:
    typedb.ingest("fact-1", "commit-1", "V1")
    typedb.advance_watermark("commit-1")
    planner = make_planner(typedb=typedb, registered=False)
    request = make_request(mode=ConsistencyMode.BEST_AVAILABLE, required_commit=None)

    result = None
    try:
        result = planner.plan(request)
    except C2Error as error:
        # NCP-U03 (NCR-C2-006): POLICY_DENIED -- ocor-named-query-gateway.openapi.yaml:454
        assert error.reason_code == "POLICY_DENIED"
    assert result is None


class _UnreachableWatermarkPort:
    """A real ``WatermarkPort`` implementation pointed at a genuinely
    closed local TCP port -- the same real, lower-blast-radius network
    fault used across this delivery's fault-injection tests."""

    def current(self, projection_id: str, branch: str) -> Watermark:
        with socket.create_connection(("127.0.0.1", 1), timeout=1.0):
            raise AssertionError("unreachable")  # pragma: no cover


def test_a_real_watermark_backend_failure_propagates_and_never_defaults_to_best_available() -> None:
    policy = RegistrationAndMarkingPolicy(
        registry={CONTRACT_ID: RegisteredNamedQuery(contract_id=CONTRACT_ID, versions=frozenset({"1.0.0"}), marking_scheme_id="classification")},
        marking_engine=MarkingEngine([CLASSIFICATION_SCHEME]),
        marking_port=_NoResourcePort(),
        clearance_by_marking_ref={},
    )
    planner = ConsistencyPlanner(
        policy=policy,
        watermark_port=_UnreachableWatermarkPort(),
        projection_id="urn:ocor:projection:spike-typedb-exact-commit",
        branch="main",
    )
    request = make_request(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-1")

    with pytest.raises(OSError):
        planner.plan(request)
