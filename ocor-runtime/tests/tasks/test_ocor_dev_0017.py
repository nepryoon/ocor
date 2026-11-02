"""OCOR-DEV-0017: SPIKE TypeDB exact-at-commit semantics.

Proves that a real TypeDB-backed C4 projection, read through the sealed C2
consistency contract (``ocor_runtime.c2.ports``, OCOR-DEV-0012), never
silently serves a fact that is behind or ahead of the watermark it claims:
queries at a required commit either return the exact projection or fail
closed with an observable watermark -- never an older or newer fact
mislabeled as exact. Every test drives a real, live TypeDB instance -- no
mocks.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from ocor_runtime.c2.ports import (
    C2Error,
    ConsistencyMode,
    ConsistencyRequirement,
    NamedQueryRequest,
)
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


@pytest.fixture(scope="session")
def typedb_reachable() -> None:
    try:
        adapter = TypeDBExactCommitAdapter()
        adapter.initialize()
    except (TypeDBAdapterError, OSError) as error:
        pytest.fail(f"a real, live TypeDB instance is mandatory qualifying evidence: {error}")


@pytest.fixture
def adapter(typedb_reachable: None) -> TypeDBExactCommitAdapter:
    value = TypeDBExactCommitAdapter()
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
            "purpose": "typedb-exact-commit-spike",
            "effective_principal_id": "spiffe://ocor.test/workload/c6",
            "actor_chain": ["urn:ocor:actor:synthetic", "urn:ocor:actor:c6"],
            "ontology_release_digest": DIGEST_B,
            "policy_bundle_digest": DIGEST_C,
            "correlation_id": "018f2f95-01b2-7cc3-8d4e-123456789abc",
        }
    )
    return NamedQueryRequest(
        request_id="018f2f95-01b2-7cc3-8d4e-123456789abc",
        contract_id="urn:ocor:contract:named-query:spike-typedb-exact-commit",
        contract_version="1.0.0",
        contract_digest=DIGEST_A,
        parameters={"fact_id": fact_id},
        governed_context=context,
        governed_context_digest=context.digest(),
        consistency=consistency,
    )


def test_exact_at_commit_returns_the_watermarked_fact(adapter: TypeDBExactCommitAdapter):
    adapter.ingest("fact-1", "commit-1", "V1")
    adapter.advance_watermark("commit-1")
    request = make_request(
        fact_id="fact-1",
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-1"),
    )
    response = adapter.read(request)
    assert response.served.canonical_commit == "commit-1"
    assert response.served.projection_watermark == "commit-1"


def test_exact_at_commit_fails_closed_when_the_fact_is_ingested_ahead_of_the_watermark(
    adapter: TypeDBExactCommitAdapter,
):
    adapter.ingest("fact-2", "commit-1", "V1")
    # deliberately never advance the watermark: the row physically exists in
    # TypeDB, but the projection has not yet officially caught up.
    request = make_request(
        fact_id="fact-2",
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-1"),
    )
    with pytest.raises(C2Error) as excinfo:
        adapter.read(request)
    # NCP-U03 (NCR-C2-012): PROJECTION_NOT_READY, never a downgrade -- docs/OCOR_LLD_v1.1.md:369
    assert excinfo.value.reason_code == "PROJECTION_NOT_READY"
    assert adapter.current_watermark() is None, "watermark must remain honestly unset, not falsely advanced"


def test_exact_at_commit_fails_closed_when_the_row_has_moved_ahead_of_the_watermark(
    adapter: TypeDBExactCommitAdapter,
):
    adapter.ingest("fact-3", "commit-1", "V1")
    adapter.advance_watermark("commit-1")
    # a second, later commit updates the row's content before the projection
    # pipeline has advanced the watermark to it.
    adapter.ingest("fact-3", "commit-2", "V2")
    request = make_request(
        fact_id="fact-3",
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-1"),
    )
    with pytest.raises(C2Error) as excinfo:
        adapter.read(request)
    # NCP-U03 (NCR-C2-012): PROJECTION_NOT_READY, never a downgrade -- docs/OCOR_LLD_v1.1.md:369
    assert excinfo.value.reason_code == "PROJECTION_NOT_READY", (
        "the watermark still reads commit-1, but the underlying row has already moved to "
        "commit-2's content; serving it as an exact commit-1 answer would silently return "
        "a newer fact mislabeled as the older, requested one"
    )


def test_at_least_commit_reports_projection_not_ready_with_an_observable_watermark(
    adapter: TypeDBExactCommitAdapter,
):
    adapter.ingest("fact-4", "commit-1", "V1")
    request = make_request(
        fact_id="fact-4",
        consistency=ConsistencyRequirement(mode=ConsistencyMode.AT_LEAST_COMMIT, required_commit="commit-1"),
    )
    with pytest.raises(C2Error) as excinfo:
        adapter.read(request)
    assert excinfo.value.reason_code == "PROJECTION_NOT_READY"
    # the caller can independently observe exactly how far behind the
    # projection is, rather than only learning that it failed.
    assert adapter.current_watermark() is None
    adapter.advance_watermark("commit-1")
    assert adapter.watermark().canonical_commit == "commit-1"
    caught_up = adapter.read(request)
    assert caught_up.served.canonical_commit == "commit-1"


def test_stale_reads_are_never_served_as_exact_across_a_real_commit_progression(
    adapter: TypeDBExactCommitAdapter,
):
    adapter.ingest("fact-5", "commit-1", "V1")
    adapter.advance_watermark("commit-1")
    request_c1 = make_request(
        fact_id="fact-5",
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-1"),
    )
    assert adapter.read(request_c1).served.canonical_commit == "commit-1"

    adapter.ingest("fact-5", "commit-2", "V2")
    # NCP-U03 (NCR-C2-012): PROJECTION_NOT_READY, never a downgrade -- docs/OCOR_LLD_v1.1.md:369
    with pytest.raises(C2Error, match="PROJECTION_NOT_READY"):
        adapter.read(request_c1)

    adapter.advance_watermark("commit-2")
    request_c2 = make_request(
        fact_id="fact-5",
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-2"),
    )
    response = adapter.read(request_c2)
    assert response.served.canonical_commit == "commit-2"

    # commit-1 is now superseded; requesting it exactly must still fail,
    # never fall back to serving commit-2's content as if it were commit-1.
    # NCP-U03 (NCR-C2-012): PROJECTION_NOT_READY, never a downgrade -- docs/OCOR_LLD_v1.1.md:369
    with pytest.raises(C2Error, match="PROJECTION_NOT_READY"):
        adapter.read(request_c1)


def test_exact_at_commit_reports_not_found_only_after_consistency_is_confirmed(
    adapter: TypeDBExactCommitAdapter,
):
    adapter.advance_watermark("commit-1")
    request = make_request(
        fact_id="fact-never-ingested",
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-1"),
    )
    with pytest.raises(C2Error) as excinfo:
        adapter.read(request)
    assert excinfo.value.reason_code == "RESULT_NOT_FOUND", (
        "the watermark honestly matches the required commit, so the adapter must reach the "
        "existence check rather than falsify a consistency failure for an absent fact"
    )
