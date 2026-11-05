"""C4 -- the SHACL shapes of the provenance metamodel and the reader of a validation report.

ADD v1.3 §3.6 (:1996-2059) and :357 (BA-04): the Jena boundary validates the shapes of §3.6 with
the SHACL service of Fuseki (PO decision NCP-U05-FUSEKI-SHACL-SERVICE (2026-11-05), option 1).
``SHAPES`` encodes the minimum of :2059:

* Claim with Proposition, Source/asserter, valid and system time and marking;
* Evidence with digest, source, acquisition and chain of custody;
* Evidential Support with stance, assessor/method and validity;
* Reliability Assessment with Source, assessor, scale, value and context;
* Match Evidence with Candidate Match, score semantics and model/rule version;
* Merge/Split Decision with adjudicator, evidence set, rationale, Policy Decision and membership
  delta (a split also names the decision it reverses, §3.6 table);
* Canonical Assertion with ``acceptedFromClaim`` and an explicit acceptance decision, never the
  Claim itself (invariant 1);
* no cluster membership originated by a Candidate Match that no decision adjudicated.

The class and relation names are those of §3.6 in the ``urn:ocor:prov:`` namespace of its Turtle
block. SHACL ``sh:class`` reads the class hierarchy of the data graph, which a published document
does not carry, so a shape that targets a class names its §3.6 subclasses explicitly.

``read_report`` reads the ``sh:ValidationReport`` the service answers; any answer that is not
exactly one report with one boolean ``sh:conforms`` consistent with its results is refused
(fail-closed), never read as a conforming document.
"""

from __future__ import annotations

from dataclasses import dataclass

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

PROV_NS = "urn:ocor:prov:"

# The 17 classes of ADD v1.3 §3.6 (:2001-2017 and the Turtle block :2022-2042).
PROVENANCE_CLASSES = frozenset(PROV_NS + name for name in (
    "Proposition", "Assertion", "Claim", "CanonicalAssertion", "Evidence", "EvidentialSupport", "Source",
    "SourceReliabilityAssessment", "CandidateMatch", "MatchEvidence", "IdentityResolutionDecision",
    "MergeDecision", "SplitDecision", "ClusterMembershipAssertion", "AcquisitionActivity",
    "TransformationActivity", "AdjudicationActivity"))

_SHA256 = "^urn:sha256:[0-9a-f]{64}$"

SHAPES = f"""\
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ocor: <{PROV_NS}> .
@prefix shape: <urn:ocor:shape:> .

shape:Claim a sh:NodeShape ;
    sh:targetClass ocor:Claim ;
    sh:property [ sh:path ocor:claimProposition ; sh:minCount 1 ; sh:class ocor:Proposition ] ;
    sh:property [ sh:path ocor:assertedBy ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
    sh:property [ sh:path ocor:validFrom ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:dateTime ] ;
    sh:property [ sh:path ocor:systemFrom ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:dateTime ] ;
    sh:property [ sh:path ocor:markingRef ; sh:minCount 1 ; sh:maxCount 1 ; sh:pattern "{_SHA256}" ] .

shape:Evidence a sh:NodeShape ;
    sh:targetClass ocor:Evidence, ocor:MatchEvidence ;
    sh:property [ sh:path ocor:contentDigest ; sh:minCount 1 ; sh:maxCount 1 ; sh:pattern "{_SHA256}" ] ;
    sh:property [ sh:path ocor:source ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
    sh:property [ sh:path ocor:acquisition ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
    sh:property [ sh:path ocor:chainOfCustody ; sh:minCount 1 ] .

shape:EvidentialSupport a sh:NodeShape ;
    sh:targetClass ocor:EvidentialSupport ;
    sh:property [ sh:path ocor:stance ; sh:minCount 1 ; sh:maxCount 1 ; sh:in ( "SUPPORTS" "REFUTES" "NEUTRAL" ) ] ;
    sh:property [ sh:path ocor:assessor ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
    sh:property [ sh:path ocor:method ; sh:minCount 1 ] ;
    sh:property [ sh:path ocor:validFrom ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:dateTime ] .

shape:SourceReliabilityAssessment a sh:NodeShape ;
    sh:targetClass ocor:SourceReliabilityAssessment ;
    sh:property [ sh:path ocor:assessedSource ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
    sh:property [ sh:path ocor:assessor ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
    sh:property [ sh:path ocor:reliabilityScale ; sh:minCount 1 ] ;
    sh:property [ sh:path ocor:reliabilityValue ; sh:minCount 1 ] ;
    sh:property [ sh:path ocor:context ; sh:minCount 1 ] .

shape:MatchEvidence a sh:NodeShape ;
    sh:targetClass ocor:MatchEvidence ;
    sh:property [ sh:path ocor:candidateMatch ; sh:minCount 1 ; sh:class ocor:CandidateMatch ] ;
    sh:property [ sh:path ocor:scoreSemantics ; sh:minCount 1 ] ;
    sh:property [ sh:path ocor:modelVersion ; sh:minCount 1 ] .

shape:IdentityResolutionDecision a sh:NodeShape ;
    sh:targetClass ocor:MergeDecision, ocor:SplitDecision ;
    sh:property [ sh:path ocor:adjudicator ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
    sh:property [ sh:path ocor:evidenceSet ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
    sh:property [ sh:path ocor:rationale ; sh:minCount 1 ] ;
    sh:property [ sh:path ocor:policyDecision ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
    sh:property [ sh:path ocor:membershipDelta ; sh:minCount 1 ; sh:class ocor:ClusterMembershipAssertion ] .

shape:SplitDecision a sh:NodeShape ;
    sh:targetClass ocor:SplitDecision ;
    sh:property [ sh:path ocor:reversesDecision ; sh:minCount 1 ; sh:nodeKind sh:IRI ] .

shape:CanonicalAssertion a sh:NodeShape ;
    sh:targetClass ocor:CanonicalAssertion ;
    sh:not [ sh:class ocor:Claim ] ;
    sh:property [ sh:path ocor:acceptedFromClaim ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
    sh:property [ sh:path ocor:acceptedByDecision ; sh:minCount 1 ; sh:nodeKind sh:IRI ] .

shape:ClusterMembershipAssertion a sh:NodeShape ;
    sh:targetClass ocor:ClusterMembershipAssertion ;
    sh:property [ sh:path ocor:generatedByDecision ; sh:minCount 1 ;
        sh:or ( [ sh:class ocor:IdentityResolutionDecision ] [ sh:class ocor:MergeDecision ]
                [ sh:class ocor:SplitDecision ] ) ;
        sh:not [ sh:class ocor:CandidateMatch ] ] .
"""

SH = Namespace("http://www.w3.org/ns/shacl#")


def _malformed(message: str) -> Exception:
    """The typed fail-closed error of a validation answer that is not a well-formed report
    (imported here because ``jena_adapter`` imports this module)."""
    from .jena_adapter import JenaAdapterError

    return JenaAdapterError("CONTROL_PLANE_UNAVAILABLE", message)


@dataclass(frozen=True, slots=True)
class ShaclViolation:
    focus_node: str
    path: str | None
    component: str | None
    message: str | None


def _single(graph: Graph, subject: object, predicate: URIRef) -> object | None:
    values = list(graph.objects(subject, predicate))  # type: ignore[arg-type]
    if len(values) > 1:
        raise _malformed(f"a validation result has more than one {predicate}")
    return values[0] if values else None


def read_report(report: str) -> tuple[ShaclViolation, ...]:
    """The violations of a SHACL validation report, ``()`` when the data conforms. Raises
    the typed ``CONTROL_PLANE_UNAVAILABLE`` for anything that is not exactly one consistent report."""
    try:
        graph = Graph().parse(data=report, format="turtle")
    except Exception as exc:  # rdflib raises several unrelated types for a malformed document
        raise _malformed("the SHACL answer is not Turtle") from exc
    reports = list(graph.subjects(RDF.type, SH.ValidationReport))
    if len(reports) != 1:
        raise _malformed("the SHACL answer is not exactly one validation report")
    [node] = reports
    conforms = list(graph.objects(node, SH.conforms))
    if len(conforms) != 1 or not isinstance(conforms[0], Literal) or conforms[0].datatype != XSD.boolean \
            or conforms[0].value not in (True, False):
        raise _malformed("the validation report has no single boolean sh:conforms")
    violations = []
    for result in graph.objects(node, SH.result):
        severity = _single(graph, result, SH.resultSeverity)
        if severity is None:  # SHACL 1.0 §3.6.2: exactly one sh:resultSeverity per result
            raise _malformed("a validation result has no severity")
        if severity != SH.Violation:
            continue
        focus = _single(graph, result, SH.focusNode)
        if focus is None:
            raise _malformed("a validation result has no focus node")
        path, component, message = (_single(graph, result, name) for name in (
            SH.resultPath, SH.sourceConstraintComponent, SH.resultMessage))
        violations.append(ShaclViolation(
            focus_node=str(focus), path=None if path is None else str(path),
            component=None if component is None else str(component), message=None if message is None else str(message)))
    if conforms[0].value is True and violations:
        raise _malformed("a conforming validation report lists a violation")
    if conforms[0].value is False and not violations:
        raise _malformed("a non-conforming validation report lists no violation")
    return tuple(sorted(violations, key=lambda item: (item.focus_node, item.path or "", item.component or "")))
