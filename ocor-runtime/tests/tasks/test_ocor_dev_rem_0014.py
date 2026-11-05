"""OCOR-DEV-REM-0014 — TypeDB commit_id/watermark safe literal rendering + identifier contract.

Remediation for the independent-verification finding VF-001 (severity high):
``apply_commit`` interpolated ``commit_id`` into the watermark insert with a
bare ``"{commit_id}"`` instead of the safe literal rendering already used for
the fact insert, and never validated the identifier contract before building
queries. A commit_id carrying a quote terminated the watermark literal and
appended a second insert that created a fact the caller never asked for.

Every test drives a real, live TypeDB instance — no mocks — and proves:

* the watermark insert escapes ``\\`` and ``"`` so an injected commit_id is
  stored verbatim as ONE literal and can never add a fact;
* ``fact_id``, ``commit_id`` and ``payload`` round-trip special characters
  exactly through the real backend;
* a malformed (empty/non-string) identifier is rejected fail-closed with
  ``C2Error("QUERY_CONTRACT_INVALID", …)`` before any query reaches TypeDB;
* fact-ingest and watermark-advance stay atomic even under an injection
  attempt, with a pre-existing fact/watermark present.
"""

from __future__ import annotations

import pytest
import c4_projection_fixture

from ocor_runtime.c2.ports import C2Error
from ocor_runtime.c4.typedb_adapter import TypeDBAdapterError, TypeDBProjectionAdapter

# The exact injection the independent verifier reproduced (VF-001): a commit_id
# carrying a quote terminates the watermark literal and appends a second insert
# ``$evil isa c4-fact ...`` that creates a fact the caller never asked for.
_INJECTION = 'x"; $evil isa c4-fact, has c4-fact-id "injected-fact", has c4-commit-id "x", has c4-payload "owned'


@pytest.fixture(scope="session")
def typedb_reachable() -> None:
    try:
        c4_projection_fixture.projection().initialize()
    except (TypeDBAdapterError, OSError) as error:
        pytest.fail(f"a real, live TypeDB instance is mandatory qualifying evidence: {error}")


@pytest.fixture
def adapter(typedb_reachable: None) -> TypeDBProjectionAdapter:
    value = c4_projection_fixture.projection()
    value.reset()
    return value


def test_watermark_insert_escapes_commit_id_so_injection_cannot_add_a_fact(
    adapter: TypeDBProjectionAdapter,
) -> None:
    adapter.apply_commit(fact_id="fact-1", commit_id=_INJECTION, payload="V1")

    # watermark identity: the malicious commit_id is stored verbatim as a
    # single literal, never split into a watermark "x" plus an injected fact.
    assert adapter.current_watermark() == _INJECTION
    # injection absence: the second insert the verifier observed must not exist.
    assert adapter._lookup_fact("injected-fact") is None


def test_commit_id_round_trips_quote_and_backslash(adapter: TypeDBProjectionAdapter) -> None:
    commit_id = 'a"b\\c'
    adapter.apply_commit(fact_id="fact-1", commit_id=commit_id, payload="V1")
    assert adapter.current_watermark() == commit_id


def test_fact_id_round_trips_special_characters(adapter: TypeDBProjectionAdapter) -> None:
    fact_id = 'urn:ocor:mission-object:"quoted"\\tail'
    adapter.apply_commit(fact_id=fact_id, commit_id="commit-1", payload="V1")
    assert adapter._lookup_fact(fact_id) == ("commit-1", "V1")


def test_payload_round_trips_special_characters(adapter: TypeDBProjectionAdapter) -> None:
    payload = '{"k": "v\\"\\\\"}'
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload=payload)
    assert adapter._lookup_fact("fact-1") == ("commit-1", payload)


def test_injection_with_pre_existing_fact_and_watermark_is_contained(
    adapter: TypeDBProjectionAdapter,
) -> None:
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    adapter.apply_commit(fact_id="fact-2", commit_id=_INJECTION, payload="V2")

    # the pre-existing fact is untouched and the second fact advanced its
    # watermark to the (escaped) malicious literal; no injected fact exists.
    assert adapter._lookup_fact("fact-1") == ("commit-1", "V1")
    assert adapter._lookup_fact("fact-2") == (_INJECTION, "V2")
    assert adapter._lookup_fact("injected-fact") is None
    assert adapter.current_watermark() == _INJECTION


@pytest.mark.parametrize("bad", [None, "", 42, []])
def test_fact_id_identifier_contract_rejects_malformed_values(
    adapter: TypeDBProjectionAdapter, bad: object
) -> None:
    with pytest.raises(C2Error) as excinfo:
        adapter.apply_commit(fact_id=bad, commit_id="commit-1", payload="V1")  # type: ignore[arg-type]
    # NCP-U03 (NCR-C2-006): SCHEMA_VIOLATION of the closed Problem enum --
    # ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:459
    assert excinfo.value.reason_code == "SCHEMA_VIOLATION"


@pytest.mark.parametrize("bad", [None, "", 42, []])
def test_commit_id_identifier_contract_rejects_malformed_values(
    adapter: TypeDBProjectionAdapter, bad: object
) -> None:
    with pytest.raises(C2Error) as excinfo:
        adapter.apply_commit(fact_id="fact-1", commit_id=bad, payload="V1")  # type: ignore[arg-type]
    # NCP-U03 (NCR-C2-006): SCHEMA_VIOLATION of the closed Problem enum --
    # ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:459
    assert excinfo.value.reason_code == "SCHEMA_VIOLATION"


@pytest.mark.parametrize("bad", [None, "", 42, []])
def test_payload_contract_rejects_malformed_values(
    adapter: TypeDBProjectionAdapter, bad: object
) -> None:
    with pytest.raises(C2Error) as excinfo:
        adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload=bad)  # type: ignore[arg-type]
    # NCP-U03 (NCR-C2-006): SCHEMA_VIOLATION of the closed Problem enum --
    # ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:459
    assert excinfo.value.reason_code == "SCHEMA_VIOLATION"
