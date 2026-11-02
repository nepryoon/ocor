"""C4 -- TypeDB object projection read by the six C2 operations (``ObjectProjectionPort``).

Each projected object is one TypeDB entity carrying its identity, type, the canonical
commit that produced it, the digest of its marking object (``marking_ref``, ADD v1.3
:398) and its snapshot document (values, links, provenance, searchable text, valid and
system time). Writes come from the projection pipeline (``project``); reads never take
a query language from a caller: the three read shapes are fixed (by identity, ordered
page, lexical search) and every literal is escaped. The marking join and the post-filter
are applied by C2 on what this port returns (LLD v1.1 :121-122).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ..c2.gateway import ProjectedObject
from ..c2.ports import C2Error
from ..c4_marking import MarkingSet
from ..kernel.canonical import canonical_digest, format_utc_timestamp
from .typedb_adapter import _literal, _read, _require_value, _schema_write, _write

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


def marking_ref(marking: MarkingSet) -> str:
    """``urn:sha256`` of the marking object (ADD v1.3 :398, RFC 8785 + SHA-256)."""
    return canonical_digest({"marking": dict(marking.values)})


class TypeDBObjectProjection:
    """Real TypeDB-backed ``ObjectProjectionPort``."""

    def __init__(self) -> None:
        self.read_count = 0

    def initialize(self) -> None:
        _schema_write(OBJECT_SCHEMA)

    def reset(self) -> None:
        _write("match $o isa c4-object; delete $o;")

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
        if self._rows(f"match $o isa c4-object, has c4-object-id {_literal(object_id)};"):
            statements.append(f"match $o isa c4-object, has c4-object-id {_literal(object_id)}; delete $o;")
        statements.append(
            f"insert $o isa c4-object, has c4-object-id {_literal(object_id)}, "
            f"has c4-object-type {_literal(resource_type_id)}, has c4-object-commit {_literal(commit_id)}, "
            f"has c4-object-marking {_literal(marking_ref(marking))}, has c4-object-document {_literal(document)};"
        )
        _write(*statements)

    @staticmethod
    def _rows(query: str) -> list[dict[str, Any]]:
        return _read(query)

    def _select(self, condition: str = "") -> list[ProjectedObject]:
        self.read_count += 1
        rows = _read(
            f"match $o isa c4-object, has c4-object-id $i, has c4-object-type $t, has c4-object-commit $c, "
            f"has c4-object-marking $m, has c4-object-document $d;{condition}"
        )
        result = []
        for row in rows:
            data = row["data"]
            try:
                document = json.loads(data["d"]["value"])
                result.append(ProjectedObject(
                    resource_type_id=str(data["t"]["value"]), resource_id=str(data["i"]["value"]),
                    commit_id=str(data["c"]["value"]), marking_ref=str(data["m"]["value"]),
                    values=dict(document["values"]), link_ids=tuple(document["link_ids"]),
                    provenance_ids=tuple(document["provenance_ids"]), text=str(document["text"]),
                    valid_from=str(document["valid_from"]), system_from=str(document["system_from"]),
                ))
            except (KeyError, TypeError, ValueError) as exc:
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
