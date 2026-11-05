"""C4 -- retained Jena RDF SHACL adapter.

Completes the smallest contract-compliant, retained (non-spike)
extension of ``spikes.jena_marking.adapter`` (OCOR-DEV-0018) against a
real, live Fuseki instance: a real ``publish`` operation that produces
RDF/JSON-LD output, enforced by an explicit closed shape (a
required-property and closed-predicate check, expressed directly; the
SHACL validation through the Fuseki SHACL service waits for the PO
decision NCP-U05-FUSEKI-SHACL-SERVICE).

Two negative acceptance criteria are enforced BEFORE any triple is
ever written: an unauthorized (non-allow-listed) predicate blocks
publication (``UNAUTHORIZED_PREDICATE``), and a missing or lossy
provenance reference blocks it too (``PROVENANCE_INVALID``) --
publication is all-or-nothing, so a rejected resource is never
partially visible.

OCOR-DEV-REM-0052 (NCP-U05, NCR-C4-002):

* every publication carries its canonical commit; the triples, the
  commit order and the watermark of the projection advance together in
  one SPARQL update request, which Fuseki applies as one transaction,
  and the watermark is then confirmed in the durable ledger
  (LLD v1.1 :148; a replayed commit writes nothing, Register FR-064 :188);
* the marking persisted with a resource is the canonical ``marking``
  object of ADD v1.3 §3.2 ``$defs``, evaluated with the active
  ``MarkingSchemeDefinition`` (§3.0.2 :396-401, ``ocor_runtime.c4.marking``):
  a marking that does not resolve is ``MARKING_UNRESOLVED`` before any
  write, a stored marking that no longer matches its digest is DENY, a
  read requires the clearance to dominate the content on every family,
  and an export carries the conservative join of what it discloses with
  the watermark it was read at (FR-068 :192, FR-131 :298);
* an unreachable Fuseki is the typed ``PROJECTION_NOT_READY`` and any
  other failure of the answer the typed ``CONTROL_PLANE_UNAVAILABLE``
  (Named Query Gateway contract :486-491, LLD v1.1 :346), never a raw
  transport exception.

``to_json_ld`` and ``export`` serialize with ``rdflib`` (already a
project dependency), a real JSON-LD serializer, not a hand-rolled one.
"""

from __future__ import annotations

import http.client
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from rdflib import Graph

from .marking import CanonicalMarkingScheme, EvaluatedMarking, MarkingUnresolved
from .watermark import ConfirmedWatermark, WatermarkLedgerError, WatermarkLedgerPort

FUSEKI_URL = "http://127.0.0.1:3030"
DATASET = "ocor"
VOCAB = "urn:ocor:vocab:"
PREFIX = f"PREFIX ocor: <{VOCAB}>"
BRANCH = "main"
DIGEST = re.compile(r"urn:sha256:[0-9a-f]{64}")

# The closed predicate vocabulary a caller may publish. A triple naming
# any other predicate is unauthorized and blocks the whole publication --
# this task's own first negative acceptance criterion, made structural
# rather than merely documented. The commit, the marking and the
# watermark predicates are written by the adapter only.
ALLOWED_PREDICATES = frozenset({"label", "provenanceRef"})

REQUIRED_PROPERTIES = frozenset({"label", "provenanceRef"})

_PUBLISH_LOCK = threading.Lock()


class JenaAdapterError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


# Transport failures: unreachable (refused, unroutable, timed out) or an answer outside the
# protocol (a dropped connection, a malformed status line).
_ANSWER_FAILURES = (OSError, http.client.HTTPException)


def _unreachable(exc: BaseException) -> bool:
    """A transport failure before any answer (refused, unreachable, timed out), as opposed
    to an answer outside the protocol or a refusal by status (as ``typedb_adapter``)."""
    if isinstance(exc, (urllib.error.HTTPError, http.client.HTTPException)):
        return False
    return isinstance(exc, OSError)


def _request(
    method: str, url: str, *, headers: dict[str, str] | None = None, body: bytes | None = None, timeout: float = 10.0
) -> tuple[int, str]:
    request = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")
    except _ANSWER_FAILURES as exc:
        if _unreachable(exc):
            raise JenaAdapterError("PROJECTION_NOT_READY", "the Jena projection is unreachable") from exc
        raise JenaAdapterError("CONTROL_PLANE_UNAVAILABLE", "the Jena projection did not answer") from exc


def _update(sparql_update: str) -> None:
    status, _ = _request(
        "POST",
        f"{FUSEKI_URL}/{DATASET}/update",
        headers={"Content-Type": "application/sparql-update"},
        body=sparql_update.encode("utf-8"),
    )
    if status not in (200, 204):
        raise JenaAdapterError("CONTROL_PLANE_UNAVAILABLE", f"SPARQL update failed: {status}")


def _query(sparql_query: str) -> list[dict[str, Any]]:
    encoded = urllib.parse.urlencode({"query": sparql_query})
    status, body = _request(
        "GET",
        f"{FUSEKI_URL}/{DATASET}/sparql?{encoded}",
        headers={"Accept": "application/sparql-results+json"},
    )
    if status != 200:
        raise JenaAdapterError("CONTROL_PLANE_UNAVAILABLE", f"SPARQL query failed: {status}")
    try:
        bindings = json.loads(body)["results"]["bindings"]
        if not isinstance(bindings, list) or any(not isinstance(row, dict) for row in bindings):
            raise TypeError("bindings is not a list of rows")
    except (ValueError, KeyError, TypeError) as exc:
        raise JenaAdapterError("CONTROL_PLANE_UNAVAILABLE", "the SPARQL answer is malformed") from exc
    return bindings


def _value(row: Mapping[str, Any], name: str) -> str:
    try:
        value = row[name]["value"]
    except (KeyError, TypeError) as exc:
        raise JenaAdapterError("CONTROL_PLANE_UNAVAILABLE", f"the SPARQL answer has no {name}") from exc
    if not isinstance(value, str):
        raise JenaAdapterError("CONTROL_PLANE_UNAVAILABLE", f"the SPARQL answer has a malformed {name}")
    return value


def _construct(sparql_construct: str) -> str:
    encoded = urllib.parse.urlencode({"query": sparql_construct})
    status, body = _request(
        "GET",
        f"{FUSEKI_URL}/{DATASET}/sparql?{encoded}",
        headers={"Accept": "text/turtle"},
    )
    if status != 200:
        raise JenaAdapterError("CONTROL_PLANE_UNAVAILABLE", f"SPARQL construct failed: {status}")
    return body


def _literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    return f'"{escaped}"'


# Characters an IRI reference can never contain inside SPARQL ``<...>``
# (SPARQL 1.1 IRIREF production): control chars plus < > " { } | ^ ` \ and
# space. Since C4 resource identifiers are URNs they always pass; a malformed
# identifier is rejected fail-closed before any triple is read or written,
# so it can never break out of the IRI and inject SPARQL.
_IRI_FORBIDDEN = frozenset('<>"{}|^`\\ ')


def _require_iri(resource_id: str) -> str:
    if not isinstance(resource_id, str) or not resource_id or any(
            char in _IRI_FORBIDDEN or ord(char) <= 0x20 for char in resource_id):
        raise JenaAdapterError(
            "RESOURCE_ID_INVALID",
            "resource_id must be a well-formed IRI with no SPARQL-breaking characters",
        )
    return resource_id


def _require_commit(commit_id: object) -> str:
    if not isinstance(commit_id, str) or not commit_id or any(ord(char) < 0x20 for char in commit_id):
        raise JenaAdapterError("SHAPE_VIOLATION", "commit_id must be a non-empty string")
    return commit_id


@dataclass(frozen=True, slots=True)
class JenaExport:
    """An RDF/JSON-LD export: the document, the conservative join of the markings it discloses
    and the watermark (canonical commit and release) it was read at."""

    document: list[dict[str, Any]]
    marking: Mapping[str, Any]
    canonical_commit: str
    release_digest: str


@dataclass(frozen=True, slots=True)
class _Row:
    resource: str
    label: str
    provenance_ref: str
    commit_id: str
    marking: EvaluatedMarking

    def public(self) -> dict[str, str]:
        return {"resource": self.resource, "label": self.label, "provenanceRef": self.provenance_ref,
                "commitId": self.commit_id, "markingRef": self.marking.marking_ref}


class JenaSHACLProjectionAdapter:
    """Retained C4 projection: a real Fuseki-backed publish/read path enforcing a closed
    predicate shape and mandatory non-lossy provenance, with a watermark correlated to the
    canonical commit and the canonical marking object of the active scheme."""

    def __init__(
        self,
        *,
        marking_scheme: CanonicalMarkingScheme,
        release_digest: str,
        ledger: WatermarkLedgerPort,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not isinstance(marking_scheme, CanonicalMarkingScheme):
            raise TypeError("the active MarkingSchemeDefinition (CanonicalMarkingScheme) is required")
        if not isinstance(release_digest, str) or DIGEST.fullmatch(release_digest) is None:
            raise TypeError("release_digest must be a SHA-256 URN")
        if not isinstance(ledger, WatermarkLedgerPort):
            raise TypeError("a WatermarkLedgerPort is required")
        self._scheme = marking_scheme
        self._release = release_digest
        self._ledger = ledger
        self._clock = clock

    @property
    def release_digest(self) -> str:
        return self._release

    @property
    def store_id(self) -> str:
        return f"urn:ocor:projection-store:jena:{DATASET}"

    def initialize(self) -> None:
        initialize = getattr(self._ledger, "initialize", None)
        if callable(initialize):
            initialize()

    def reset(self) -> None:
        _update("DELETE WHERE { ?s ?p ?o }")
        self._ledger.clear(self.store_id)

    def _clearance(self, clearance: object) -> EvaluatedMarking:
        try:
            return self._scheme.evaluate(clearance)
        except MarkingUnresolved as exc:
            raise JenaAdapterError("MARKING_UNRESOLVED", str(exc)) from exc

    def observe(self, commit_id: str) -> None:
        """Records a commit delivered to the projector and not yet published (NFR-077 :403)."""
        self._ledger.observe(self.store_id, BRANCH, _require_commit(commit_id), at=self._clock())

    def _confirm(self, commit_id: str, sequence: int) -> None:
        try:
            self._ledger.confirm(self.store_id, BRANCH, commit_id, sequence=sequence, release_digest=self._release,
                                 at=self._clock())
        except WatermarkLedgerError as exc:
            raise JenaAdapterError(exc.reason_code, str(exc)) from exc

    def publish(self, resource_id: str, properties: dict[str, str], *, marking: Mapping[str, Any],
                commit_id: str) -> bool:
        """Validates the closed shape, non-lossy provenance and the canonical marking BEFORE
        writing anything; then writes the resource, its commit, its marking, the commit order
        and the watermark in one update request and confirms the watermark in the ledger. A
        commit already ordered is a duplicate: nothing is written and ``False`` is returned."""
        _require_iri(resource_id)
        commit_id = _require_commit(commit_id)
        if not isinstance(properties, Mapping) or any(
                not isinstance(name, str) or not isinstance(value, str) for name, value in properties.items()):
            raise JenaAdapterError("SHAPE_VIOLATION", "properties must map predicate names to strings")
        unauthorized = sorted(set(properties) - ALLOWED_PREDICATES)
        if unauthorized:
            raise JenaAdapterError(
                "UNAUTHORIZED_PREDICATE", f"predicate(s) outside the closed vocabulary: {unauthorized}"
            )
        missing = sorted(REQUIRED_PROPERTIES - set(properties))
        if missing:
            raise JenaAdapterError("SHAPE_VIOLATION", f"missing required propert(y/ies): {missing}")
        provenance = properties["provenanceRef"]
        if not provenance or not provenance.startswith("urn:ocor:provenance:"):
            raise JenaAdapterError(
                "PROVENANCE_INVALID", "provenanceRef must be a real, non-empty urn:ocor:provenance: reference"
            )
        try:
            evaluated = self._scheme.evaluate(marking)
        except MarkingUnresolved as exc:
            raise JenaAdapterError("MARKING_UNRESOLVED", str(exc)) from exc
        stored = json.dumps(dict(marking), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

        with _PUBLISH_LOCK:
            position = self.position(BRANCH, commit_id)
            if position is not None:
                # durable deduplication on (store, branch, commit_id); a confirmation that
                # failed after the update is completed here
                self._confirm(commit_id, position)
                return False
            sequence = self._next_sequence()
            triples = " ".join(
                f"ocor:{predicate} {_literal(value)} ;" for predicate, value in sorted(properties.items())
            )
            store = f"<{self.store_id}>"
            _update(
                f"{PREFIX} DELETE WHERE {{ <{resource_id}> ?p ?o }} ; "
                f"{PREFIX} DELETE WHERE {{ {store} ocor:watermarkCommit ?c }} ; "
                f"{PREFIX} INSERT DATA {{ <{resource_id}> a ocor:Resource ; {triples} "
                f"ocor:commitId {_literal(commit_id)} ; ocor:markingRef {_literal(evaluated.marking_ref)} ; "
                f"ocor:markingObject {_literal(stored)} . "
                f"{store} ocor:watermarkCommit {_literal(commit_id)} . "
                f"[] a ocor:CommitOrder ; ocor:orderCommitId {_literal(commit_id)} ; ocor:orderSeq {sequence} . }}"
            )
            self._confirm(commit_id, sequence)
            return True

    def _next_sequence(self) -> int:
        rows = _query(f"{PREFIX} SELECT (MAX(?s) AS ?m) WHERE {{ ?o a ocor:CommitOrder ; ocor:orderSeq ?s }}")
        if not rows or "m" not in rows[0]:
            return 1
        return 1 + self._position(_value(rows[0], "m"))

    @staticmethod
    def _position(value: str) -> int:
        if not value.isdigit():
            raise JenaAdapterError("CONTROL_PLANE_UNAVAILABLE", "the Jena commit order is malformed")
        return int(value)

    def position(self, branch: str, commit: str) -> int | None:
        """The position of ``commit`` among the commits published to ``branch``, or ``None``."""
        if branch != BRANCH or not isinstance(commit, str) or not commit:
            return None
        rows = _query(f"{PREFIX} SELECT ?s WHERE {{ ?o a ocor:CommitOrder ; ocor:orderCommitId {_literal(commit)} ; "
                      f"ocor:orderSeq ?s }}")
        if not rows:
            return None
        if len(rows) > 1:
            raise JenaAdapterError("CONTROL_PLANE_UNAVAILABLE", "the Jena commit order names a commit twice")
        return self._position(_value(rows[0], "s"))

    def current_watermark(self) -> str | None:
        """The canonical commit of the Jena watermark, or ``None`` before any publication."""
        rows = _query(f"{PREFIX} SELECT ?c WHERE {{ <{self.store_id}> ocor:watermarkCommit ?c }}")
        if not rows:
            return None
        if len(rows) > 1:
            raise JenaAdapterError("CONTROL_PLANE_UNAVAILABLE", "the Jena projection holds more than one watermark")
        return _value(rows[0], "c")

    def watermark(self) -> ConfirmedWatermark | None:
        """The confirmed watermark the projection serves: the ledger and the projection must name
        the same commit, otherwise the state is an explicit ``PROJECTION_NOT_READY``."""
        stored = self.current_watermark()
        try:
            confirmed = self._ledger.latest(self.store_id, BRANCH)
        except WatermarkLedgerError as exc:
            raise JenaAdapterError("CONTROL_PLANE_UNAVAILABLE", "the C4 watermark ledger is unavailable") from exc
        if (None if confirmed is None else confirmed.commit_id) != stored:
            raise JenaAdapterError("PROJECTION_NOT_READY",
                                   "the Jena watermark disagrees with the confirmed watermark of the ledger")
        return confirmed

    def _rows(self) -> list[_Row]:
        """Every published resource whose stored marking still resolves; a stored marking that no
        longer matches its reference or its digest is DENY, so the resource is withheld."""
        rows = _query(
            f"{PREFIX} SELECT ?resource ?label ?provenanceRef ?commitId ?markingRef ?markingObject WHERE {{ "
            f"?resource a ocor:Resource ; ocor:label ?label ; ocor:provenanceRef ?provenanceRef ; "
            f"ocor:commitId ?commitId ; ocor:markingRef ?markingRef ; ocor:markingObject ?markingObject . }}"
        )
        result: list[_Row] = []
        for row in rows:
            try:
                evaluated = self._scheme.evaluate(json.loads(_value(row, "markingObject")))
            except (MarkingUnresolved, ValueError):
                continue
            if evaluated.marking_ref != _value(row, "markingRef"):
                continue
            result.append(_Row(resource=_value(row, "resource"), label=_value(row, "label"),
                               provenance_ref=_value(row, "provenanceRef"), commit_id=_value(row, "commitId"),
                               marking=evaluated))
        return sorted(result, key=lambda item: item.resource)

    def _authorized(self, clearance: object) -> list[_Row]:
        granted = self._clearance(clearance)
        return [row for row in self._rows() if self._scheme.authorized(row.marking, granted)]

    def list_authorized(self, clearance: Mapping[str, Any]) -> list[dict[str, str]]:
        return [row.public() for row in self._authorized(clearance)]

    def exists_authorized(self, resource_id: str, clearance: Mapping[str, Any]) -> bool:
        return any(row.resource == resource_id for row in self._authorized(clearance))

    def _document(self, resource_ids: Sequence[str]) -> list[dict[str, Any]]:
        graph = Graph()
        for resource_id in resource_ids:
            turtle = _construct(f"{PREFIX} CONSTRUCT {{ <{resource_id}> ?p ?o }} WHERE {{ <{resource_id}> ?p ?o }}")
            graph.parse(data=turtle, format="turtle")
        document = json.loads(graph.serialize(format="json-ld"))
        if not isinstance(document, list):
            raise JenaAdapterError("CONTROL_PLANE_UNAVAILABLE", "the JSON-LD serialization is malformed")
        return document

    def to_json_ld(self, resource_id: str, clearance: Mapping[str, Any]) -> dict[str, Any] | list[Any]:
        """Serializes an authorized resource's triples to real JSON-LD via rdflib -- never for a
        resource the clearance does not authorize (``MARKING_DENIED``), structurally identical to
        the marking-safe read path (``_authorized`` is the same filtered source)."""
        _require_iri(resource_id)
        if not any(row.resource == resource_id for row in self._authorized(clearance)):
            raise JenaAdapterError("MARKING_DENIED", "resource is not authorized for the requester's clearance")
        turtle = _construct(f"{PREFIX} CONSTRUCT {{ <{resource_id}> ?p ?o }} WHERE {{ <{resource_id}> ?p ?o }}")
        graph = Graph()
        graph.parse(data=turtle, format="turtle")
        result: dict[str, Any] | list[Any] = json.loads(graph.serialize(format="json-ld"))
        return result

    def export(self, resource_ids: Sequence[str], clearance: Mapping[str, Any]) -> JenaExport:
        """The RDF/JSON-LD export of ``resource_ids``: every one must be authorized, the export
        marking is the conservative join of theirs and the export names the confirmed watermark
        it was read at (LLD v1.1 :148; FR-131 :298)."""
        if isinstance(resource_ids, str) or not resource_ids:
            raise JenaAdapterError("SHAPE_VIOLATION", "an export names one or more resources")
        wanted = [_require_iri(resource_id) for resource_id in resource_ids]
        authorized = {row.resource: row for row in self._authorized(clearance)}
        if any(resource_id not in authorized for resource_id in wanted):
            raise JenaAdapterError("MARKING_DENIED", "a resource is not authorized for the requester's clearance")
        confirmed = self.watermark()
        if confirmed is None:
            raise JenaAdapterError("PROJECTION_NOT_READY", "the Jena projection has no confirmed watermark")
        try:
            marking = self._scheme.join(*(authorized[resource_id].marking for resource_id in wanted))
        except MarkingUnresolved as exc:
            raise JenaAdapterError("MARKING_UNRESOLVED", str(exc)) from exc
        document = self._document(wanted)
        if self.current_watermark() != confirmed.commit_id:
            raise JenaAdapterError("PROJECTION_NOT_READY", "the Jena watermark moved during the export")
        return JenaExport(document=document, marking=marking, canonical_commit=confirmed.commit_id,
                          release_digest=confirmed.release_digest)

    def raw_unfiltered_triple_count(self) -> int:
        """The naive SPARQL COUNT ignoring marking entirely -- exposed
        only so tests can demonstrate why a naive count would leak;
        never used by the authorized read operations above."""
        rows = _query(f"{PREFIX} SELECT (COUNT(?resource) AS ?c) WHERE {{ ?resource a ocor:Resource . }}")
        return self._position(_value(rows[0], "c")) if rows else 0
