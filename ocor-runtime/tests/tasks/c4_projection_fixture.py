"""Construction support of the C4 TypeDB projection for the task test modules (OCOR-DEV-REM-0052).

NCP-U05 (NCR-C4-001): the projection declares the ontology release it projects and confirms
every applied commit in the durable watermark ledger on PostgreSQL. The test modules that
construct the projection build it here, with the release their requests are bound to and the
real ledger of the stack (``OCOR_LIVE_POSTGRES_DSN``); nothing else of their construction
changes (case 3 of NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 5).
"""

from __future__ import annotations

import os

import pytest
from ocor_runtime.c4 import typedb_adapter
from ocor_runtime.c4.adapters.postgres import PostgresWatermarkLedger
from ocor_runtime.c4.typedb_adapter import TypeDBProjectionAdapter

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
    return TypeDBProjectionAdapter(release_digest=release_digest, ledger=ledger())


def isolated_projection(release_digest: str = RELEASE) -> TypeDBProjectionAdapter:
    """The projection of the tests that stand a local responder or a seam in for TypeDB: its
    ledger lives in a schema of its own, emptied at construction, so those tests never read
    or clear the ledger of the projection that the real-backend tests share."""
    value = TypeDBProjectionAdapter(release_digest=release_digest, ledger=isolated_ledger())
    value.reset_ledger()
    return value


def isolated_ledger() -> PostgresWatermarkLedger:
    """The real ledger in the schema of the responder and seam tests (``isolated_projection``)."""
    return ledger(schema="ocor_c4_isolated")


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
