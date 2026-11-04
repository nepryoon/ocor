"""Construction support of the C4 TypeDB projection for the task test modules (OCOR-DEV-REM-0052).

NCP-U05 (NCR-C4-001): the projection declares the ontology release it projects and confirms
every applied commit in the durable watermark ledger on PostgreSQL. The test modules that
construct the projection build it here, with the release their requests are bound to and the
real ledger of the stack (``OCOR_LIVE_POSTGRES_DSN``); nothing else of their construction
changes (case 3 of NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 5).
"""

from __future__ import annotations

import importlib
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from ocor_runtime.c3.admission import CommitAdmission
from ocor_runtime.c3.terminusdb_service import TerminusDBC3Service
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
