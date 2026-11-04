"""OCOR-DEV-REM-0010 — C4 projection adapter identifier/literal hardening.

Backend-free remediation tests for the review finding RVW-01/-02: the real
TypeDB and Jena C4 projection adapters interpolate identifiers/literals into
TypeQL/SPARQL. These tests pin the intended fail-closed behaviour without a
live backend:

* TypeDB string literals must escape ``\\`` and ``"`` so a payload/identifier
  containing a quote can never terminate the literal and inject TypeQL.
* SPARQL IRI positions must reject identifiers that contain characters
  forbidden in an ``<...>`` IRIREF, before any query reaches the backend.

For canonical URN/digest inputs (the only values the sealed real-backend
callers pass) the generated queries are byte-identical to before, so the real
TypeDB/Fuseki acceptance suites remain unaffected.
"""

from __future__ import annotations

import pytest
import c4_projection_fixture

from ocor_runtime.c4 import jena_adapter, typedb_adapter
from ocor_runtime.c4.jena_adapter import JenaAdapterError, JenaSHACLProjectionAdapter
from ocor_runtime.c4_marking import MarkingEngine, MarkingSchemeDefinition

_INJECTION = 'x"; match $g isa c4-fact; delete $g; #'


def test_typedb_literal_escapes_quote_and_backslash() -> None:
    assert typedb_adapter._literal('a"b') == '"a\\"b"'
    assert typedb_adapter._literal("a\\b") == '"a\\\\b"'
    # a clean URN/digest is quoted exactly as the sealed callers already did
    assert typedb_adapter._literal("urn:ocor:mission-object:x") == '"urn:ocor:mission-object:x"'


def test_typedb_apply_commit_escapes_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr(typedb_adapter, "_read", lambda *_a, **_k: [])
    monkeypatch.setattr(typedb_adapter, "_write", lambda *queries: captured.extend(queries))

    c4_projection_fixture.isolated_projection().apply_commit(
        fact_id="urn:ocor:mission-object:1", commit_id="urn:sha256:" + "0" * 64, payload=_INJECTION
    )

    insert = next(query for query in captured if "insert" in query and "c4-payload" in query)
    # the whole payload stays inside one literal with its quote escaped (\"),
    # so it can never terminate the literal and inject free TypeQL
    assert f"has c4-payload {typedb_adapter._literal(_INJECTION)};" in insert
    assert 'has c4-payload "x\\"; match $g isa c4-fact; delete $g; #";' in insert


def test_jena_require_iri_accepts_urn_and_rejects_forbidden_chars() -> None:
    jena_adapter._require_iri("urn:ocor:mission-object:9")  # must not raise
    for bad in ('urn:x> <y', 'urn:x"y', "urn:x y", "urn:x{y}", "urn:x\\y", "urn:x|y", "urn:x^y"):
        with pytest.raises(JenaAdapterError) as exc:
            jena_adapter._require_iri(bad)
        assert exc.value.reason_code == "RESOURCE_ID_INVALID"


def test_jena_publish_rejects_malformed_resource_id_before_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(jena_adapter, "_update", lambda update: calls.append(update))
    adapter = JenaSHACLProjectionAdapter(MarkingEngine([MarkingSchemeDefinition("classification", ["public"])]))

    with pytest.raises(JenaAdapterError) as exc:
        adapter.publish(
            _INJECTION,
            {
                "label": "l",
                "classification": "public",
                "provenanceRef": "urn:ocor:provenance:1",
            },
        )
    assert exc.value.reason_code == "RESOURCE_ID_INVALID"
    assert calls == []  # nothing was ever sent to the backend
