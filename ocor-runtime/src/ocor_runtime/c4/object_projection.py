"""C4 -- TypeDB object projection read by the six C2 operations (``ObjectProjectionPort``).

Each projected object is one TypeDB entity carrying its identity, type, the canonical
commit that produced it, the digest of its marking object (``marking_ref``, ADD v1.3
:398) and its snapshot document (values, links, provenance, searchable text, valid and
system time). Writes come from the projection pipeline (``project``); reads never take
a query language from a caller: the three read shapes are fixed (by identity, ordered
page, lexical search) and every literal is escaped. The marking join and the post-filter
are applied by C2 on what this port returns (LLD v1.1 :121-122).

Rows read back are untrusted: each column and the snapshot document are checked for
type, shape and integrity without conversion -- type URN and identifier bounds of the
contract ``ResourceRef``, ``urn:sha256`` marking reference (ADD v1.3 :398), canonical RFC
3339 UTC times -- and any failure of the transport or of a row is the typed fail-closed
``CONTROL_PLANE_UNAVAILABLE`` of the whole read, never a coerced or partial answer. An
unreachable TypeDB is the projection down, ``PROJECTION_NOT_READY`` (ADD v1.3 :3406): the port
has no request, so the Gateway builds the served context of the confirmed watermark that the
Problem carries (ADD v1.3 :1364; NCR-C4-005, PO decision NCP-U05-ITERATION-LIMIT option B1).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, TypeVar

from ..c2.gateway import ProjectedObject
from ..c2.ports import C2Error
from ..c4_marking import MarkingSet
from ..kernel.canonical import DIGEST, UTC_TIMESTAMP, canonical_digest, format_utc_timestamp, parse_utc_timestamp
from .typedb_adapter import (_ANSWER_FAILURES, _literal, _require_value, _rows, _schema_write, _unreachable, _write,
                            read_rows)

OBJECT_SCHEMA = (
    "define "
    "attribute c4-object-id, value string; "
    "attribute c4-object-type, value string; "
    "attribute c4-object-commit, value string; "
    "attribute c4-object-marking, value string; "
    "attribute c4-object-document, value string; "
    "entity c4-object, owns c4-object-id @key, owns c4-object-type @card(1..1), "
    "owns c4-object-commit @card(1..1), owns c4-object-marking @card(1..1), "
    "owns c4-object-document @card(1..1);"
)
MAX_ITEMS = 1000
COLUMNS = ("i", "t", "c", "m", "d")
DOCUMENT_FIELDS = frozenset({"values", "link_ids", "provenance_ids", "text", "valid_from", "system_from"})
TYPE_URN = re.compile(r"urn:ocor:[A-Za-z0-9._~:/-]+")  # contract ResourceRef.resource_type_id
MAX_ID = 512  # contract ResourceRef.resource_id maxLength
T = TypeVar("T")


class _Malformed(ValueError):
    """A row read back from the projection is not a well-formed object snapshot."""


class ObjectProjectionNotReady(C2Error):
    """The object projection is down (ADD v1.3 :3406): ``PROJECTION_NOT_READY`` without a served
    context, which only the Gateway can build from the confirmed watermark (ADD v1.3 :1364). It
    never reaches the wire as it is: the Gateway replaces it before any Problem is written."""

    def __init__(self, message: str) -> None:
        # C2Error requires the served context for PROJECTION_NOT_READY; this port has no request
        self.reason_code = "PROJECTION_NOT_READY"
        self.detail = message
        self.served = None
        self.deferred_element = None
        ValueError.__init__(self, f"PROJECTION_NOT_READY: {message}")


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_ID:
        raise _Malformed("identifier")
    return value


def _identifiers(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _Malformed("identifier list")
    return tuple(_identifier(item) for item in value)


def _time(value: object) -> str:
    if not isinstance(value, str) or UTC_TIMESTAMP.fullmatch(value) is None:
        raise _Malformed("time")
    parse_utc_timestamp(value)
    return value


def _object(row: Mapping[str, object]) -> ProjectedObject:
    resource_type_id, marking, document_text = row["t"], row["m"], row["d"]
    if not isinstance(resource_type_id, str) or TYPE_URN.fullmatch(resource_type_id) is None:
        raise _Malformed("resource type")
    if not isinstance(marking, str) or DIGEST.fullmatch(marking) is None:
        raise _Malformed("marking reference")
    if not isinstance(document_text, str):
        raise _Malformed("document")
    document = json.loads(document_text)
    if not isinstance(document, dict) or set(document) != DOCUMENT_FIELDS:
        raise _Malformed("document fields")
    values, text = document["values"], document["text"]
    if not isinstance(values, dict) or not isinstance(text, str):
        raise _Malformed("document values")
    return ProjectedObject(
        resource_type_id=resource_type_id, resource_id=_identifier(row["i"]), commit_id=_identifier(row["c"]),
        marking_ref=marking, values=values, link_ids=_identifiers(document["link_ids"]),
        provenance_ids=_identifiers(document["provenance_ids"]), text=text,
        valid_from=_time(document["valid_from"]), system_from=_time(document["system_from"]),
    )


def _typed(work: Callable[[], T]) -> T:
    """Translate every failure of the TypeDB exchange into the typed fail-closed answer: an
    unreachable TypeDB is the projection down, any other failure CONTROL_PLANE_UNAVAILABLE."""
    try:
        return work()
    except C2Error:
        raise
    except _ANSWER_FAILURES as exc:
        if _unreachable(exc):
            raise ObjectProjectionNotReady("the object projection is unreachable") from exc
        raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the object projection is unavailable or malformed") from exc


def marking_ref(marking: MarkingSet) -> str:
    """``urn:sha256`` of the marking object (ADD v1.3 :398, RFC 8785 + SHA-256)."""
    return canonical_digest({"marking": dict(marking.values)})


class TypeDBObjectProjection:
    """Real TypeDB-backed ``ObjectProjectionPort``."""

    def __init__(self) -> None:
        self.read_count = 0

    def initialize(self) -> None:
        _typed(lambda: _schema_write(OBJECT_SCHEMA))

    def reset(self) -> None:
        _typed(lambda: _write("match $o isa c4-object; delete $o;"))

    def project(
        self,
        *,
        object_id: str,
        resource_type_id: str,
        commit_id: str,
        marking: MarkingSet,
        values: Mapping[str, Any],
        link_ids: tuple[str, ...] = (),
        provenance_ids: tuple[str, ...] = (),
        text: str = "",
        valid_from: datetime | None = None,
    ) -> None:
        object_id = _require_value("object_id", object_id)
        resource_type_id = _require_value("resource_type_id", resource_type_id)
        commit_id = _require_value("commit_id", commit_id)
        now = format_utc_timestamp(datetime.now(UTC))
        document = json.dumps({
            "values": dict(values), "link_ids": list(link_ids), "provenance_ids": list(provenance_ids),
            "text": text, "valid_from": now if valid_from is None else format_utc_timestamp(valid_from),
            "system_from": now,
        }, sort_keys=True, separators=(",", ":"))
        statements = []
        if read_rows(f"match $o isa c4-object, has c4-object-id {_literal(object_id)};", ()):
            statements.append(f"match $o isa c4-object, has c4-object-id {_literal(object_id)}; delete $o;")
        statements.append(
            f"insert $o isa c4-object, has c4-object-id {_literal(object_id)}, "
            f"has c4-object-type {_literal(resource_type_id)}, has c4-object-commit {_literal(commit_id)}, "
            f"has c4-object-marking {_literal(marking_ref(marking))}, has c4-object-document {_literal(document)};"
        )
        _typed(lambda: _write(*statements))

    def _select(self, condition: str = "") -> list[ProjectedObject]:
        self.read_count += 1
        query = (f"match $o isa c4-object, has c4-object-id $i, has c4-object-type $t, has c4-object-commit $c, "
                 f"has c4-object-marking $m, has c4-object-document $d;{condition}")
        # the raw read, so that an unreachable TypeDB stays distinguishable from a malformed answer
        rows = _typed(lambda: _rows(query, COLUMNS))
        try:
            result = [_object(row) for row in rows]
        except (_Malformed, ValueError) as exc:
            raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the object projection returned a malformed row") from exc
        return sorted(result, key=lambda item: item.resource_id)

    def get(self, resource_ids: tuple[str, ...]) -> tuple[ProjectedObject, ...]:
        if not resource_ids:
            return ()
        wanted = set(resource_ids)
        if len(wanted) == 1:
            (only,) = wanted
            return tuple(self._select(f" $i == {_literal(only)};"))
        return tuple(item for item in self._select() if item.resource_id in wanted)

    def page(self, *, limit: int, after: str | None) -> tuple[ProjectedObject, ...]:
        items = [item for item in self._select() if after is None or item.resource_id > after]
        return tuple(items[: min(limit, MAX_ITEMS + 1)])

    def search(self, text: str, *, limit: int, after: str | None) -> tuple[ProjectedObject, ...]:
        terms = [term for term in text.lower().split() if term]
        items = [item for item in self._select()
                 if (after is None or item.resource_id > after) and any(term in item.text.lower() for term in terms)]
        return tuple(items[: min(limit, MAX_ITEMS + 1)])
