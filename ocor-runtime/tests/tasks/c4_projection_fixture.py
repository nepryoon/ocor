"""Construction support of the C4 projections for the task test modules (OCOR-DEV-REM-0052).

NCP-U05 (NCR-C4-001): the projection declares the ontology release it projects and confirms
every applied commit in the durable watermark ledger on PostgreSQL. The test modules that
construct the projection build it here, with the release their requests are bound to and the
real ledger of the stack (``OCOR_LIVE_POSTGRES_DSN``); nothing else of their construction
changes (case 3 of NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 5).

NCP-U05 (NCR-C4-002): the Jena projection carries the canonical marking object of ADD v1.3 §3.2
``$defs`` evaluated with the active ``MarkingSchemeDefinition`` and confirms its watermark in the
same ledger. The consumer modules express the marking of a resource and the clearance of a reader
as one classification level; ``ClassificationJena`` builds the canonical object of that level
under a scheme whose levels are the classification levels those modules use, and nothing else of
their construction or of their assertions changes.
"""

from __future__ import annotations

import importlib
import os
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import pytest
from ocor_runtime.c3.admission import CommitAdmission
from ocor_runtime.c3.terminusdb_service import TerminusDBC3Service
from ocor_runtime.c4 import typedb_adapter
from ocor_runtime.c4.adapters.postgres import PostgresWatermarkLedger
from ocor_runtime.c4.jena_adapter import JenaSHACLProjectionAdapter
from ocor_runtime.c4.marking import CanonicalMarkingScheme
from ocor_runtime.c4.typedb_adapter import TypeDBProjectionAdapter
from ocor_runtime.c4.watermark import ConfirmedWatermark
from ocor_runtime.c4_marking import MarkingSet
from ocor_runtime.c5.envelope import marking_digest

RELEASE = "urn:sha256:" + "b" * 64


def ledger(*, schema: str = "ocor_c4") -> PostgresWatermarkLedger:
    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory qualifying evidence (real PostgreSQL watermark ledger)")
    value = PostgresWatermarkLedger(dsn, schema=schema)
    value.initialize()
    return value


def projection(release_digest: str = RELEASE) -> TypeDBProjectionAdapter:
    """The C4 TypeDB projection of the task test modules, on the real ledger."""
    store = ledger()
    return TypeDBProjectionAdapter(release_digest=release_digest, ledger=store, quarantine=store)


def isolated_projection(release_digest: str = RELEASE) -> TypeDBProjectionAdapter:
    """The projection of the tests that stand a local responder or a seam in for TypeDB: its
    ledger lives in a schema of its own, emptied at construction, so those tests never read
    or clear the ledger of the projection that the real-backend tests share."""
    store = isolated_ledger()
    value = TypeDBProjectionAdapter(release_digest=release_digest, ledger=store, quarantine=store)
    value.reset_ledger()
    return value


def isolated_ledger() -> PostgresWatermarkLedger:
    """The real ledger in the schema of the responder and seam tests (``isolated_projection``)."""
    return ledger(schema="ocor_c4_isolated")


@contextmanager
def canonical_store(*, admission: CommitAdmission) -> Iterator[TerminusDBC3Service]:
    """NCP-U05 (NCR-C4-002): the canonical TerminusDB C3 store the drift detector rebuilds from
    (LLD v1.1 :148; ADD v1.3 Part I §2.2/§2.4), on a disposable database of the real TerminusDB
    of the stack, dropped afterwards."""
    terminus = importlib.import_module("test_ocor_dev_rem_0041")
    password = terminus._password()
    name = f"ocor_c3_c4drift_{uuid.uuid4().hex[:12]}"
    service = TerminusDBC3Service(url=terminus.URL, password=password, database=name, admission=admission)
    try:
        service.initialize()
    except OSError as error:
        pytest.fail(f"a real, live TerminusDB server is mandatory qualifying evidence: {error}")
    try:
        yield service
    finally:
        terminus._raw("DELETE", f"/api/db/admin/{name}", password)


def overwrite_fact(*, fact_id: str, commit_id: str, payload: str) -> None:
    """Rewrites a projected fact directly in TypeDB, outside the projection adapter: the
    out-of-band storage corruption (or its external repair) of the drift tests. The adapter
    itself never re-applies a commit already ordered on the branch (FR-064, Register :188)."""
    literal = typedb_adapter._literal
    typedb_adapter._write(
        f"match $f isa c4-fact, has c4-fact-id {literal(fact_id)}; delete $f;",
        f"insert $f isa c4-fact, has c4-fact-id {literal(fact_id)}, has c4-commit-id {literal(commit_id)}, "
        f"has c4-payload {literal(payload)};",
    )


CLASSIFICATION_SCHEME_ID = "urn:ocor:marking-scheme:classification"
CLASSIFICATION_LEVELS = ("UNCLASSIFIED", "SECRET", "TOP_SECRET")
CLASSIFICATION_PURPOSE = "urn:ocor:purpose:c4-projection"


def classification_scheme() -> CanonicalMarkingScheme:
    """The ``MarkingSchemeDefinition`` (C1 IR, ADD v1.3 :429) of the classification levels the
    consumer modules use, totally ordered, with empty restriction vocabularies."""
    levels = list(CLASSIFICATION_LEVELS)
    order = [[low, high] for index, low in enumerate(levels) for high in levels[index:]]

    def family(name: str, kind: str, vocabulary: list[str]) -> dict[str, Any]:
        join, meet = ("UNION", "INTERSECTION") if kind == "RESTRICTION" else ("INTERSECTION", "UNION")
        return {"family": name, "vocabulary": vocabulary, "kind": kind, "join_operator": join,
                "meet_operator": meet, "neutral_element": [] if kind == "RESTRICTION" else vocabulary}

    return CanonicalMarkingScheme({
        "construct": "MarkingSchemeDefinition", "scheme_id": CLASSIFICATION_SCHEME_ID, "version": "1.0.0",
        "levels": levels, "top": levels[-1], "bottom": levels[0], "dominance_relation": order,
        "family_definitions": [
            family("mandatory_markings", "RESTRICTION", []), family("caveats", "RESTRICTION", []),
            family("dissemination_controls", "RESTRICTION", []),
            family("permitted_purposes", "PERMISSION", [CLASSIFICATION_PURPOSE]),
            family("handling_instructions", "RESTRICTION", []),
        ],
        "unknown_value_behavior": "DENY", "incomparable_behavior": "DENY",
        "declassification_authority_ref": "urn:ocor:authority:declassification:c4-projection",
    })


def classification_marking(level: str) -> dict[str, Any]:
    """The canonical ``marking`` object (ADD v1.3 §3.2 ``$defs``) of one classification level."""
    value: dict[str, Any] = {
        "scheme_id": CLASSIFICATION_SCHEME_ID, "labels": [level], "mandatory_markings": [], "caveats": [],
        "dissemination_controls": [], "permitted_purposes": [CLASSIFICATION_PURPOSE], "handling_instructions": [],
    }
    value["marking_digest"] = marking_digest(value)
    return value


def jena_projection(release_digest: str = RELEASE) -> JenaSHACLProjectionAdapter:
    """The C4 Jena projection of the task test modules, on the real ledger."""
    return JenaSHACLProjectionAdapter(marking_scheme=classification_scheme(), release_digest=release_digest,
                                      ledger=ledger())


class UnusedLedger:
    """The ledger of a test that never reaches the backend: any use fails the test."""

    def _unused(self, *args: object, **kwargs: object) -> Any:
        pytest.fail("the watermark ledger was used by a test that must never reach the backend")

    def observe(self, store_id: str, branch: str, commit_id: str, *, at: datetime) -> None:
        self._unused()

    def confirm(self, store_id: str, branch: str, commit_id: str, *, sequence: int, release_digest: str,
                at: datetime) -> ConfirmedWatermark:
        return self._unused()

    def latest(self, store_id: str, branch: str) -> ConfirmedWatermark | None:
        return self._unused()

    def pending_since(self, store_id: str, branch: str) -> datetime | None:
        return self._unused()

    def clear(self, store_id: str) -> None:
        self._unused()


class ClassificationJena:
    """The Jena projection as the consumer modules compose it: a resource published with a
    ``classification`` property is published with the canonical marking object of that level at a
    commit of its own, and a ``MarkingSet`` clearance of the C2 marking port (``NCR-C6-012``, unit
    NCP-U08) is read as the canonical clearance of its classification level."""

    def __init__(self, projection: JenaSHACLProjectionAdapter | None = None) -> None:
        self.projection = jena_projection() if projection is None else projection

    @staticmethod
    def clearance(clearance: MarkingSet) -> dict[str, Any]:
        return classification_marking(clearance["classification"])

    def reset(self) -> None:
        self.projection.reset()

    def publish(self, resource_id: str, properties: Mapping[str, str]) -> bool:
        values = dict(properties)
        level = values.pop("classification", "")
        return self.projection.publish(resource_id, values, marking=classification_marking(level),
                                       commit_id=f"urn:ocor:commit:c4-jena:{uuid.uuid4().hex}")

    def list_authorized(self, clearance: MarkingSet) -> list[dict[str, str]]:
        return self.projection.list_authorized(self.clearance(clearance))

    def exists_authorized(self, resource_id: str, clearance: MarkingSet) -> bool:
        return self.projection.exists_authorized(resource_id, self.clearance(clearance))

    def to_json_ld(self, resource_id: str, clearance: MarkingSet) -> Any:
        return self.projection.to_json_ld(resource_id, self.clearance(clearance))

    def raw_unfiltered_triple_count(self) -> int:
        return self.projection.raw_unfiltered_triple_count()
