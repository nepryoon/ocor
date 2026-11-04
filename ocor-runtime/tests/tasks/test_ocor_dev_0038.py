"""OCOR-DEV-0038: Implement C4 Jena RDF SHACL adapter.

Proves that RDF/JSON-LD output published through JenaSHACLProjectionAdapter
passes its closed shape (a required-property, closed-predicate check) and
the real marking join already proven by OCOR-DEV-0018, and that an
unauthorized predicate or lossy provenance blocks publication before any
triple is ever written. Every test drives a real, live Fuseki instance --
no mocks.
"""

from __future__ import annotations


import pytest
from ocor_runtime.c4.jena_adapter import JenaAdapterError, JenaSHACLProjectionAdapter
from ocor_runtime.c4_marking import MarkingEngine, MarkingSchemeDefinition, MarkingSet

CLASSIFICATION_SCHEME = MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET", "TOP_SECRET"))


def clearance(level: str) -> MarkingSet:
    return MarkingSet({"classification": level})


def valid_properties(*, label: str = "fixture", classification: str = "SECRET") -> dict[str, str]:
    return {
        "label": label,
        "classification": classification,
        "provenanceRef": "urn:ocor:provenance:fixture-1",
    }


@pytest.fixture(scope="session")
def fuseki_reachable() -> None:
    try:
        probe = JenaSHACLProjectionAdapter(MarkingEngine([CLASSIFICATION_SCHEME]))
        probe.reset()
    except (JenaAdapterError, OSError) as error:
        pytest.fail(f"a real, live Fuseki instance is mandatory qualifying evidence: {error}")


@pytest.fixture
def adapter(fuseki_reachable: None) -> JenaSHACLProjectionAdapter:
    value = JenaSHACLProjectionAdapter(MarkingEngine([CLASSIFICATION_SCHEME]))
    value.reset()
    return value


def test_a_valid_publication_is_readable_and_serializes_to_real_json_ld(adapter: JenaSHACLProjectionAdapter) -> None:
    adapter.publish("urn:ocor:resource:r1", valid_properties())

    assert adapter.exists_authorized("urn:ocor:resource:r1", clearance("SECRET"))
    document = adapter.to_json_ld("urn:ocor:resource:r1", clearance("SECRET"))

    assert isinstance(document, list)
    entry = document[0]
    assert entry["@id"] == "urn:ocor:resource:r1"


def test_an_unauthorized_predicate_blocks_publication_entirely(adapter: JenaSHACLProjectionAdapter) -> None:
    properties = valid_properties()
    properties["arbitraryPredicate"] = "not in the closed vocabulary"

    with pytest.raises(JenaAdapterError) as excinfo:
        adapter.publish("urn:ocor:resource:r1", properties)
    assert excinfo.value.reason_code == "UNAUTHORIZED_PREDICATE"
    assert adapter.list_authorized(clearance("TOP_SECRET")) == []


def test_a_missing_required_property_blocks_publication_entirely(adapter: JenaSHACLProjectionAdapter) -> None:
    properties = valid_properties()
    del properties["provenanceRef"]

    with pytest.raises(JenaAdapterError) as excinfo:
        adapter.publish("urn:ocor:resource:r1", properties)
    assert excinfo.value.reason_code == "SHAPE_VIOLATION"
    assert adapter.list_authorized(clearance("TOP_SECRET")) == []


def test_lossy_or_empty_provenance_blocks_publication_entirely(adapter: JenaSHACLProjectionAdapter) -> None:
    lossy = valid_properties()
    lossy["provenanceRef"] = ""
    with pytest.raises(JenaAdapterError) as excinfo:
        adapter.publish("urn:ocor:resource:r1", lossy)
    assert excinfo.value.reason_code == "PROVENANCE_INVALID"

    fabricated = valid_properties()
    fabricated["provenanceRef"] = "not-a-real-provenance-urn"
    with pytest.raises(JenaAdapterError) as excinfo:
        adapter.publish("urn:ocor:resource:r1", fabricated)
    assert excinfo.value.reason_code == "PROVENANCE_INVALID"

    assert adapter.list_authorized(clearance("TOP_SECRET")) == []


def test_list_authorized_filters_by_the_real_marking_join(adapter: JenaSHACLProjectionAdapter) -> None:
    adapter.publish("urn:ocor:resource:u1", valid_properties(label="public", classification="UNCLASSIFIED"))
    adapter.publish("urn:ocor:resource:s1", valid_properties(label="secret", classification="SECRET"))
    adapter.publish("urn:ocor:resource:t1", valid_properties(label="top secret", classification="TOP_SECRET"))

    visible = adapter.list_authorized(clearance("SECRET"))
    resources = {row["resource"] for row in visible}
    assert resources == {"urn:ocor:resource:u1", "urn:ocor:resource:s1"}


def test_count_never_diverges_from_the_authorized_list_and_raw_count_would_leak(
    adapter: JenaSHACLProjectionAdapter,
) -> None:
    adapter.publish("urn:ocor:resource:u1", valid_properties(classification="UNCLASSIFIED"))
    adapter.publish("urn:ocor:resource:s1", valid_properties(classification="SECRET"))
    adapter.publish("urn:ocor:resource:t1", valid_properties(classification="TOP_SECRET"))

    low_clearance_count = len(adapter.list_authorized(clearance("UNCLASSIFIED")))
    raw = adapter.raw_unfiltered_triple_count()
    assert low_clearance_count == 1
    assert raw == 3
    assert low_clearance_count != raw


def test_json_ld_serialization_is_denied_for_an_unauthorized_clearance(adapter: JenaSHACLProjectionAdapter) -> None:
    adapter.publish("urn:ocor:resource:t1", valid_properties(classification="TOP_SECRET"))

    with pytest.raises(JenaAdapterError) as excinfo:
        adapter.to_json_ld("urn:ocor:resource:t1", clearance("UNCLASSIFIED"))
    assert excinfo.value.reason_code == "MARKING_DENIED"


def test_a_real_fuseki_unreachability_fails_closed_never_writing_a_partial_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ocor_runtime.c4.jena_adapter.FUSEKI_URL", "http://127.0.0.1:1")
    adapter = JenaSHACLProjectionAdapter(MarkingEngine([CLASSIFICATION_SCHEME]))

    # a genuine connection-refused failure is the typed fail-closed error of the
    # contract with a reason code (OCOR-DEV-REM-0052, NCP-U05, NCR-C4-002: Named Query
    # Gateway contract :486-491, LLD v1.1 :346), never a raw transport exception.
    with pytest.raises(JenaAdapterError) as excinfo:
        adapter.publish("urn:ocor:resource:r1", valid_properties())
    assert excinfo.value.reason_code == "PROJECTION_NOT_READY"
