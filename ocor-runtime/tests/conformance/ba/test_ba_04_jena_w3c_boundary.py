"""BA-04 -- Apache Jena/Fuseki ``W3CBoundary``: RDF 1.1 / JSON-LD round trip and marking join.

Backend assumption under test: ADD v1.3 Part I §2.6 row ``BA-04`` ("Round-trip
RDF 1.1 / JSON-LD / SHACL senza perdita nel profilo dichiarato ..."; conformance
column "Round-trip conformance su fixture canoniche; validazione SHACL delle
shape di §3.6") and the LLD v1.1 §7.1 oracle "Jena RDF/JSON-LD/SHACL e marking
join senza leakage".

Real component: Apache Jena Fuseki 6.2.0 (``fuseki`` compose service, image
built from the pinned official tarball in ``infra/services.lock.json``) through
the sealed retained adapter
``ocor_runtime.c4.jena_adapter.JenaSHACLProjectionAdapter`` (``publish`` with
its closed-shape/provenance validation, ``to_json_ld`` via rdflib, and the
marking-joined reads backed by the sealed ``ocor_runtime.c4_marking``).

Declared profile observed here: the adapter's closed vocabulary -- one
``ocor:Resource`` with exactly ``label``, ``classification``, ``provenanceRef``
as plain literals. Round trip = publish (RDF into Fuseki) -> CONSTRUCT read-back
(Turtle) -> JSON-LD export -> JSON-LD parse -> re-import through ``publish`` ->
read-back, compared as RDF graphs (isomorphism) at every hop.

Not covered (no runtime implementation behind the sealed adapter): a real SHACL
processor and the §3.6 PROV-O shapes (Claim/Evidence/...); the adapter's
closed-shape check is the only shape validation exercised. No export watermark
correlated to a canonical commit exists in the adapter. Literals containing
LF/CR are outside the reachable profile (rejected by Fuseki, never converted).

Isolation: the Fuseki in-memory dataset ``/ocor`` is shared and its admin API is
closed, so every resource uses a unique IRI and is deleted at teardown with the
deletion asserted on the server; the sealed adapter's global ``reset`` is never
called.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator

import pytest
from ocor_runtime.c4 import jena_adapter
from ocor_runtime.c4.jena_adapter import JenaAdapterError, JenaSHACLProjectionAdapter
from ocor_runtime.c4_marking import MarkingEngine, MarkingSchemeDefinition, MarkingSet
from rdflib import RDF, Graph, Literal, URIRef
from rdflib.compare import isomorphic

pytestmark = pytest.mark.backend_assumption

BA_CASE = {
    "ba_id": "BA-04",
    "component": "Apache Jena Fuseki (W3CBoundary, C4) via ocor_runtime.c4.jena_adapter.JenaSHACLProjectionAdapter",
    "component_version": "6.2.0",
    "backend_services": ["fuseki"],
    "add_v1_3_part_i_2_6": {
        "required_property": "Round-trip RDF 1.1 / JSON-LD",
        "conformance_test": "Round-trip conformance su fixture canoniche",
    },
    "lld_v1_1_7_1_oracle": "Jena RDF/JSON-LD/SHACL e marking join senza leakage",
    "requirement_ids": ["FR-168", "NFR-056", "NFR-006"],
    "requirement_binding": {
        "FR-168": (
            "Observes RDF 1.1/JSON-LD fixtures round-tripping through the declared profile and out-of-profile input "
            "being rejected, never silently converted."
        ),
        "NFR-056": (
            "Observes that export/import of the portable profile preserves identity, values and provenance "
            "reference with zero graph differences."
        ),
        "NFR-006": (
            "Observes that results, counts and JSON-LD export never reveal content or existence of a resource "
            "whose marking the requester's clearance does not dominate."
        ),
    },
    "positive_tests": [
        "test_ba_04_positive_canonical_fixtures_round_trip_rdf_json_ld_without_loss",
    ],
    "negative_tests": [
        "test_ba_04_negative_out_of_profile_publication_is_rejected_and_nothing_is_written",
        "test_ba_04_negative_marking_join_never_leaks_content_count_or_existence",
    ],
    "fault_tests": [],
}

CLASSIFICATION = MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET", "TOP_SECRET"))
VOCAB = jena_adapter.VOCAB
RESOURCE_TYPE = URIRef(VOCAB + "Resource")


def _clearance(level: str) -> MarkingSet:
    return MarkingSet({"classification": level})


def _resource_triples(iri: str) -> int:
    rows = jena_adapter._query(f"SELECT (COUNT(*) AS ?c) WHERE {{ <{iri}> ?p ?o }}")
    return int(rows[0]["c"]["value"])


def _server_graph(iri: str) -> Graph:
    """The resource's triples read back from the real Fuseki server."""
    turtle = jena_adapter._construct(f"CONSTRUCT {{ <{iri}> ?p ?o }} WHERE {{ <{iri}> ?p ?o }}")
    return Graph().parse(data=turtle, format="turtle")


def _expected_graph(iri: str, properties: dict[str, str]) -> Graph:
    graph = Graph()
    subject = URIRef(iri)
    graph.add((subject, RDF.type, RESOURCE_TYPE))
    for predicate, value in properties.items():
        graph.add((subject, URIRef(VOCAB + predicate), Literal(value)))
    return graph


def _properties_from(graph: Graph, iri: str) -> dict[str, str]:
    """Imports a JSON-LD-derived graph back into the profile's property map;
    any triple outside the profile is kept (with its full IRI) so a lossy or
    widened export cannot pass unnoticed."""
    properties: dict[str, str] = {}
    for subject, predicate, value in graph:
        assert subject == URIRef(iri), f"unexpected subject {subject}"
        if predicate == RDF.type:
            assert value == RESOURCE_TYPE
            continue
        name = str(predicate)
        key = name[len(VOCAB) :] if name.startswith(VOCAB) else name
        assert isinstance(value, Literal) and value.language is None and value.datatype is None
        assert key not in properties
        properties[key] = str(value)
    return properties


@pytest.fixture
def boundary() -> Iterator[tuple[JenaSHACLProjectionAdapter, Callable[[str], str]]]:
    adapter = JenaSHACLProjectionAdapter(MarkingEngine([CLASSIFICATION]))
    try:
        jena_adapter._query("SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }")
    except (JenaAdapterError, OSError) as error:
        pytest.fail(f"a real, live Fuseki instance is mandatory qualifying evidence: {error}")
    run = uuid.uuid4().hex[:12]
    created: list[str] = []

    def iri(name: str) -> str:
        value = f"urn:ocor:resource:ba04:{run}:{name}"
        created.append(value)
        return value

    yield adapter, iri
    for value in created:
        jena_adapter._update(f"DELETE WHERE {{ <{value}> ?p ?o }}")
    assert [value for value in created if _resource_triples(value)] == []


def _ids(document: object) -> list[str]:
    """``to_json_ld`` returns rdflib's expanded JSON-LD: a list of node objects."""
    assert isinstance(document, list)
    return [str(entry["@id"]) for entry in document]


def _mine(rows: list[dict[str, str]], prefix: str) -> dict[str, dict[str, str]]:
    return {row["resource"]: row for row in rows if row["resource"].startswith(prefix)}


# --------------------------------------------------------------------------
# BA-04 cases
# --------------------------------------------------------------------------


def test_ba_04_positive_canonical_fixtures_round_trip_rdf_json_ld_without_loss(
    boundary: tuple[JenaSHACLProjectionAdapter, Callable[[str], str]],
) -> None:
    adapter, iri = boundary
    fixtures = {
        "unicode": {
            "label": 'Ünïcødé — 東京 "quoted" \\ backslash',
            "classification": "SECRET",
            "provenanceRef": "urn:ocor:provenance:ba04:canonical-commit-0001",
        },
        "whitespace": {
            "label": "tab\tseparated  double-space trailing ",
            "classification": "UNCLASSIFIED",
            "provenanceRef": "urn:ocor:provenance:ba04:canonical-commit-0002",
        },
        "astral": {
            "label": "satellite 🛰 and math 𝔸",
            "classification": "TOP_SECRET",
            "provenanceRef": "urn:ocor:provenance:ba04:canonical-commit-0003",
        },
    }
    full = _clearance("TOP_SECRET")
    sources: dict[str, str] = {}
    for name, properties in fixtures.items():
        source = iri(f"{name}:source")
        sources[name] = source
        adapter.publish(source, properties)
        expected = _expected_graph(source, properties)

        # hop 1: RDF 1.1 in Fuseki equals the declared profile triples
        stored = _server_graph(source)
        assert len(stored) == 4
        assert isomorphic(stored, expected)

        # hop 2: JSON-LD export is a lossless serialization of those triples
        document = adapter.to_json_ld(source, full)
        exported = Graph().parse(data=json.dumps(document), format="json-ld")
        assert isomorphic(exported, expected)
        assert _ids(document) == [source]

        # hop 3: import of the exported JSON-LD back through the boundary
        imported = _properties_from(exported, source)
        assert imported == properties
        target = iri(f"{name}:reimported")
        adapter.publish(target, imported)
        assert isomorphic(_server_graph(target), _expected_graph(target, properties))

        # hop 4: the re-imported resource re-exports to the same JSON-LD
        again = adapter.to_json_ld(target, full)
        assert isomorphic(
            Graph().parse(data=json.dumps(again), format="json-ld"), _expected_graph(target, properties)
        )
        assert json.dumps(again, sort_keys=True).replace(target, source) == json.dumps(document, sort_keys=True)

    # the marking-joined listing returns every value verbatim
    prefix = sources["unicode"].split(":unicode:", 1)[0] + ":"
    listed = _mine(adapter.list_authorized(full), prefix)
    assert len(listed) == 2 * len(fixtures)
    for name, properties in fixtures.items():
        row = listed[sources[name]]
        assert {key: row[key] for key in properties} == properties


def test_ba_04_negative_out_of_profile_publication_is_rejected_and_nothing_is_written(
    boundary: tuple[JenaSHACLProjectionAdapter, Callable[[str], str]],
) -> None:
    adapter, iri = boundary
    target = iri("shape")
    valid = {
        "label": "shape fixture",
        "classification": "SECRET",
        "provenanceRef": "urn:ocor:provenance:ba04:shape",
    }
    cases: list[tuple[dict[str, str], str]] = [
        ({**valid, "arbitraryPredicate": "outside the closed vocabulary"}, "UNAUTHORIZED_PREDICATE"),
        ({key: value for key, value in valid.items() if key != "classification"}, "SHAPE_VIOLATION"),
        ({**valid, "provenanceRef": ""}, "PROVENANCE_INVALID"),
        ({**valid, "provenanceRef": "https://example.invalid/provenance"}, "PROVENANCE_INVALID"),
        # out of the reachable profile: a line break inside a literal is
        # refused by the real server -- rejected, never silently converted.
        ({**valid, "label": "line\nbreak"}, "BACKEND_ERROR"),
    ]
    for properties, reason in cases:
        with pytest.raises(JenaAdapterError) as rejected:
            adapter.publish(target, properties)
        assert rejected.value.reason_code == reason
        assert _resource_triples(target) == 0  # all-or-nothing: no partial resource
    assert not adapter.exists_authorized(target, _clearance("TOP_SECRET"))

    # positive control: the same IRI with an in-profile resource is published.
    adapter.publish(target, valid)
    assert isomorphic(_server_graph(target), _expected_graph(target, valid))
    assert adapter.exists_authorized(target, _clearance("TOP_SECRET"))


def test_ba_04_negative_marking_join_never_leaks_content_count_or_existence(
    boundary: tuple[JenaSHACLProjectionAdapter, Callable[[str], str]],
) -> None:
    adapter, iri = boundary
    public, secret, top = iri("public"), iri("secret"), iri("top")
    absent = iri("never-published")
    prefix = public.rsplit(":", 1)[0] + ":"
    for resource, level in ((public, "UNCLASSIFIED"), (secret, "SECRET"), (top, "TOP_SECRET")):
        adapter.publish(
            resource,
            {"label": f"label-of-{level}", "classification": level, "provenanceRef": f"urn:ocor:provenance:{level}"},
        )
    # the restricted resources really exist on the server (non-vacuous)
    assert _resource_triples(secret) == 4 and _resource_triples(top) == 4

    low = _clearance("UNCLASSIFIED")
    visible = _mine(adapter.list_authorized(low), prefix)
    assert set(visible) == {public}
    assert not adapter.exists_authorized(secret, low)
    assert not adapter.exists_authorized(top, low)

    with pytest.raises(JenaAdapterError) as denied:
        adapter.to_json_ld(top, low)
    assert denied.value.reason_code == "MARKING_DENIED"
    with pytest.raises(JenaAdapterError) as missing:
        adapter.to_json_ld(absent, low)
    # a denied resource and a non-existent one are indistinguishable
    assert (missing.value.reason_code, str(missing.value)) == (denied.value.reason_code, str(denied.value))

    exported = json.dumps(adapter.to_json_ld(public, low))
    for leaked in (secret, top, "label-of-SECRET", "label-of-TOP_SECRET", "TOP_SECRET"):
        assert leaked not in exported

    # positive controls: dominating clearances see exactly what they dominate
    assert set(_mine(adapter.list_authorized(_clearance("SECRET")), prefix)) == {public, secret}
    assert set(_mine(adapter.list_authorized(_clearance("TOP_SECRET")), prefix)) == {public, secret, top}
    top_document = adapter.to_json_ld(top, _clearance("TOP_SECRET"))
    assert _ids(top_document) == [top]
