"""OCOR-DEV-REM-0052 (NCP-U05): C4 projections conform to the closed normative elements.

Unit of NORMATIVE-CONFORMANCE-PLAN (2026-10-30), plan unit NCP-U05, register entries
NCR-C4-001 and NCR-C4-003 (this module; NCR-C4-002 and NCR-C4-004 follow in the same unit).

* NCR-C4-001 -- LLD v1.1 :355 (C4/C5 per-aggregate ordering, monotonic watermark, durable
  deduplication), LLD v1.1 :148 (projector verifies schema/release/GCS, applies idempotently,
  advances the watermark only in the projection transaction), Register FR-064 :188
  (deduplicate by store, branch and commitId; replay never duplicates facts nor moves the
  watermark ahead of facts), FR-148 :331 (adapter, projector and store declare the same
  release digest), NFR-024 :180 and NFR-077 :403 (every state-dependent response reports the
  branch, the canonical commit and watermark actually served, the ontology release and the
  staleness; branch divergence and projection lag give an explicit state).
* NCR-C4-003 -- Named Query Gateway contract :486-491 (typed fail-closed Problem) and LLD v1.1
  :346 (an unavailable projection blocks exact consistency, observably and with a reason
  code); PO decision NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 5, NCP-U05 row: an
  unreachable projection is the adapter's typed error with reason code PROJECTION_NOT_READY,
  C4 records the last confirmed watermark and commit durably outside the projection store,
  and the served context of PROJECTION_NOT_READY is built from those values with the
  staleness measured from their instant (ADD v1.3 :1364 and :3406). A TypeDB transaction is
  closed on every error path, connection-level errors and a failed commit included.

Every positive path runs on the real TypeDB and the real PostgreSQL of the stack; the local
HTTP responder stands in for TypeDB only on the failure paths of NCR-C4-003.
"""

from __future__ import annotations

import http.server
import importlib
import json
import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ocor_runtime.c2.ports import (
    C2Error,
    ConsistencyMode,
    ConsistencyRequirement,
    NamedQueryRequest,
)
from ocor_runtime.kernel.governed_context import GovernedContext

RELEASE = "urn:sha256:" + "b" * 64
OTHER_RELEASE = "urn:sha256:" + "e" * 64
DIGEST_A = "urn:sha256:" + "a" * 64
DIGEST_C = "urn:sha256:" + "c" * 64
PROJECTION = "urn:ocor:projection:c4-typedb"
T0 = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)


def _module(name: str) -> Any:
    return importlib.import_module(name)


class Clock:
    """A controllable clock: staleness is asserted exactly, never approximately."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, milliseconds: int) -> None:
        self.now = self.now + timedelta(milliseconds=milliseconds)


@pytest.fixture(scope="session")
def dsn() -> str:
    value = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not value:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory qualifying evidence (real PostgreSQL watermark ledger)")
    return value


@pytest.fixture
def ledger(dsn: str) -> Any:
    value = _module("ocor_runtime.c4.adapters.postgres").PostgresWatermarkLedger(dsn, schema="ocor_c4_rem0052")
    value.initialize()
    return value


@pytest.fixture
def clock() -> Clock:
    return Clock(T0)


def _adapter(ledger: Any, clock: Clock, release: str = RELEASE) -> Any:
    return _module("ocor_runtime.c4.typedb_adapter").TypeDBProjectionAdapter(
        release_digest=release, ledger=ledger, clock=clock)


@pytest.fixture
def adapter(ledger: Any, clock: Clock) -> Iterator[Any]:
    value = _adapter(ledger, clock)
    try:
        value.initialize()
    except (_module("ocor_runtime.c4.typedb_adapter").TypeDBAdapterError, OSError) as error:
        pytest.fail(f"a real, live TypeDB instance is mandatory qualifying evidence: {error}")
    value.reset()
    try:
        yield value
    finally:
        value.reset()


def _request(*, fact_id: str = "fact-1", release: str = RELEASE, mode: ConsistencyMode = ConsistencyMode.BEST_AVAILABLE,
             required_commit: str | None = None, branch: str = "main") -> NamedQueryRequest:
    context = GovernedContext.from_mapping({
        "tenant_id": "urn:ocor:tenant:synthetic",
        "organization_id": "urn:ocor:org:synthetic",
        "domain_id": "urn:ocor:domain:logistics",
        "compartments": ["urn:ocor:compartment:alpha"],
        "classification_marking_ref": DIGEST_A,
        "purpose": "rem0052-c4-projection",
        "effective_principal_id": "spiffe://ocor.test/workload/c2",
        "actor_chain": ["urn:ocor:actor:synthetic", "urn:ocor:actor:c2"],
        "ontology_release_digest": release,
        "policy_bundle_digest": DIGEST_C,
        "correlation_id": "018f2f95-01b2-7cc3-8d4e-123456789abc",
    })
    return NamedQueryRequest(
        request_id="018f2f95-01b2-7cc3-8d4e-123456789abc",
        contract_id="urn:ocor:contract:named-query:rem0052-c4",
        contract_version="1.0.0",
        contract_digest=DIGEST_A,
        parameters={"fact_id": fact_id},
        governed_context=context,
        governed_context_digest=context.digest(),
        consistency=ConsistencyRequirement(mode=mode, required_commit=required_commit),
        branch=branch,
    )


# -- NCR-C4-001 ------------------------------------------------------------------------------


def test_ncr_c4_001_conforms(adapter: Any, ledger: Any) -> None:
    """FR-064 (Register :188) and LLD v1.1 :355: deduplication on (store, branch, commit_id) is
    durable and the watermark is monotonic -- replaying an older commit neither re-applies its
    fact nor moves the watermark backwards; the ledger confirms each commit once, in order."""
    assert adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1") is True
    assert adapter.apply_commit(fact_id="fact-1", commit_id="commit-2", payload="V2") is True

    assert adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1") is False

    assert adapter.current_watermark() == "commit-2"
    assert adapter._lookup_fact("fact-1") == ("commit-2", "V2")
    assert (adapter.position("main", "commit-1"), adapter.position("main", "commit-2")) == (1, 2)
    confirmed = ledger.latest(adapter.store_id, "main")
    assert (confirmed.commit_id, confirmed.sequence, confirmed.release_digest) == ("commit-2", 2, RELEASE)


def test_ncr_c4_001_replay_of_every_commit_is_idempotent(adapter: Any) -> None:
    """FR-064 acceptance (Register :188): a multiple replay duplicates no fact and leaves the
    watermark at the latest commit, never ahead of nor behind its fact."""
    for _ in range(3):
        for commit, payload in (("commit-1", "V1"), ("commit-2", "V2"), ("commit-3", "V3")):
            adapter.apply_commit(fact_id="fact-1", commit_id=commit, payload=payload)
    assert adapter.current_watermark() == "commit-3"
    assert adapter._lookup_fact("fact-1") == ("commit-3", "V3")
    assert adapter._next_sequence() == 4


def test_ncr_c4_001_the_watermark_and_the_served_release_are_the_declared_release(adapter: Any) -> None:
    """FR-148 (Register :331), NFR-024 (:180), NFR-077 (:403): the watermark port and the served
    context report the release the projection declares, never a placeholder nor a value copied
    from the request; a request bound to another release is refused with the served context."""
    assert adapter.current(PROJECTION, "main").ontology_release_digest == RELEASE
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    watermark = adapter.current(PROJECTION, "main")
    assert (watermark.ontology_release_digest, watermark.canonical_commit, watermark.branch) == (
        RELEASE, "commit-1", "main")
    assert adapter.read(_request()).served.ontology_release_digest == RELEASE

    with pytest.raises(C2Error) as caught:
        adapter.read(_request(release=OTHER_RELEASE))
    assert caught.value.reason_code == "STALE_CONTEXT"
    assert caught.value.served is not None and caught.value.served.ontology_release_digest == RELEASE


def test_ncr_c4_001_a_branch_the_projection_does_not_serve_is_never_answered_as_main(adapter: Any) -> None:
    """NFR-077 (Register :403): branch divergence gives an explicit state, never main's
    watermark under another branch name (LLD v1.1 :124)."""
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    for read in (lambda: adapter.current(PROJECTION, "scenario-7"), lambda: adapter.read(_request(branch="scenario-7"))):
        with pytest.raises(C2Error) as caught:
            read()
        assert caught.value.reason_code == "UNSUPPORTED_CAPABILITY"


def test_ncr_c4_001_staleness_is_the_lag_behind_the_commits_c4_has_received(adapter: Any, clock: Clock) -> None:
    """NFR-024 (:180) and NFR-077 (:403): staleness is measured, not declared -- zero while the
    projection serves every commit C4 has received; from the instant a received commit is still
    unapplied, the elapsed time; back to zero once it is applied."""
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    assert adapter.read(_request()).served.staleness_ms == 0

    adapter.observe("commit-2")
    clock.advance(1500)
    served = adapter.read(_request()).served
    assert (served.canonical_commit, served.projection_watermark, served.staleness_ms) == ("commit-1", "commit-1", 1500)
    assert adapter.current(PROJECTION, "main").observed_at == T0

    adapter.apply_commit(fact_id="fact-1", commit_id="commit-2", payload="V2")
    served = adapter.read(_request()).served
    assert (served.canonical_commit, served.staleness_ms) == ("commit-2", 0)


def test_ncr_c4_001_a_store_confirmed_under_another_release_is_release_mismatch(
    adapter: Any, ledger: Any, clock: Clock
) -> None:
    """FR-148 (Register :331): the release is active only when adapter, projector and store
    declare the same release; a projection whose store confirms another release is refused
    with RELEASE_MISMATCH and the served context of the store (ADD v1.3 :1364)."""
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    upgraded = _adapter(ledger, clock, release=OTHER_RELEASE)
    with pytest.raises(C2Error) as caught:
        upgraded.read(_request(release=OTHER_RELEASE))
    assert caught.value.reason_code == "RELEASE_MISMATCH"
    assert caught.value.served is not None
    assert (caught.value.served.ontology_release_digest, caught.value.served.canonical_commit) == (RELEASE, "commit-1")

    projector = _module("ocor_runtime.c4.projector")
    with pytest.raises(projector.ProjectorError) as refused:
        projector.CanonicalStateProjector(upgraded, release_digest=RELEASE)
    assert refused.value.reason_code == "RELEASE_MISMATCH"


def test_ncr_c4_001_the_ledger_never_moves_backwards(ledger: Any) -> None:
    """LLD v1.1 :355: the durable watermark is monotonic per branch; a confirmation is
    idempotent for the same commit and refused for an earlier position."""
    store = "urn:ocor:projection-store:rem0052-ledger"
    ledger.clear(store)
    first = ledger.confirm(store, "main", "commit-2", sequence=2, release_digest=RELEASE, at=T0)
    assert ledger.confirm(store, "main", "commit-2", sequence=2, release_digest=RELEASE, at=T0 + timedelta(seconds=9)) == first
    with pytest.raises(_module("ocor_runtime.c4.watermark").WatermarkLedgerError) as caught:
        ledger.confirm(store, "main", "commit-1", sequence=1, release_digest=RELEASE, at=T0)
    assert caught.value.reason_code == "WATERMARK_REGRESSION"
    assert ledger.latest(store, "main") == first
    assert ledger.latest(store, "scenario-7") is None
    ledger.clear(store)


# -- NCR-C4-003 ------------------------------------------------------------------------------


def test_ncr_c4_003_conforms(adapter: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract :486-491, LLD v1.1 :346, PO decision point 5 (NCP-U05): an unreachable TypeDB is
    the typed PROJECTION_NOT_READY, never a raw transport error; the served context is built
    from the last watermark and commit C4 confirmed durably, staleness from their instant."""
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    clock.advance(2000)
    monkeypatch.setattr("ocor_runtime.c4.typedb_adapter.TYPEDB_URL", "http://127.0.0.1:1")
    typed = _module("ocor_runtime.c4.typedb_adapter").TypeDBAdapterError

    for read in (adapter.current_watermark, lambda: adapter.current(PROJECTION, "main")):
        with pytest.raises(typed) as unavailable:
            read()
        assert unavailable.value.reason_code == "PROJECTION_NOT_READY"

    with pytest.raises(C2Error) as caught:
        adapter.read(_request(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit="commit-1"))
    assert caught.value.reason_code == "PROJECTION_NOT_READY"
    served = caught.value.served
    assert served is not None
    assert (served.branch, served.canonical_commit, served.projection_watermark, served.ontology_release_digest,
            served.staleness_ms) == ("main", "commit-1", "commit-1", RELEASE, 2000)


class TypeDBResponder:
    """A local HTTP responder standing in for TypeDB on the failure paths only. It records the
    endpoint of every request, so a test sees whether the opened transaction was closed."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, bytes] | bytes] = {}
        self.calls: list[str] = []
        responder = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _answer(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                key = next((name for name in ("signin", "open", "query", "close", "commit", "databases")
                            if self.path.rstrip("/").endswith(name)), "other")
                responder.calls.append(key)
                route = responder.routes.get(key, responder.default(key))
                self.close_connection = True
                if isinstance(route, bytes):
                    self.wfile.write(route)
                    return
                status, body = route
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_POST = _answer
            do_GET = _answer

            def log_message(self, format: str, *args: Any) -> None:
                return None

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @staticmethod
    def default(key: str) -> tuple[int, bytes]:
        return {"signin": (200, b'{"token": "t"}'), "open": (200, b'{"transactionId": "tx"}'),
                "query": (200, json.dumps({"answers": []}).encode("utf-8"))}.get(key, (200, b"{}"))

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def responder(monkeypatch: pytest.MonkeyPatch) -> Iterator[TypeDBResponder]:
    value = TypeDBResponder()
    monkeypatch.setattr("ocor_runtime.c4.typedb_adapter.TYPEDB_URL", value.url)
    try:
        yield value
    finally:
        value.close()


TRANSACTION_FAILURES: dict[str, dict[str, tuple[int, bytes] | bytes]] = {
    "query-refused": {"query": (500, b"{}")},
    "query-connection-dropped": {"query": b""},
    "query-bad-status-line": {"query": b"GARBAGE\r\n\r\n"},
    "commit-refused": {"commit": (500, b"{}")},
    "commit-connection-dropped": {"commit": b""},
    "commit-bad-status-line": {"commit": b"GARBAGE\r\n\r\n"},
}


@pytest.mark.parametrize("primitive", ["_write", "_schema_write"])
@pytest.mark.parametrize("case", sorted(TRANSACTION_FAILURES))
def test_ncr_c4_003_a_failed_transaction_is_always_closed(responder: TypeDBResponder, primitive: str, case: str) -> None:
    """Decision request OCOR-DEV-0060-BA-RUNTIME-GAPS (criterion of NCR-C4-003 extended by PO
    decision NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 8): the transaction opened by
    ``_write`` or ``_schema_write`` is closed on every error path, a connection-level error and
    a failed commit included, and the failure is the adapter's typed error."""
    adapter_module = _module("ocor_runtime.c4.typedb_adapter")
    responder.routes = dict(TRANSACTION_FAILURES[case])
    with pytest.raises(adapter_module.TypeDBAdapterError):
        getattr(adapter_module, primitive)("match $f isa c4-fact; delete $f;")
    assert "open" in responder.calls
    assert responder.calls[-1] == "close", (case, responder.calls)


def test_ncr_c4_003_a_failed_read_transaction_is_closed(responder: TypeDBResponder) -> None:
    """Positive control of the read primitive: a failed query of a read transaction closes it."""
    adapter_module = _module("ocor_runtime.c4.typedb_adapter")
    responder.routes = {"query": (500, b"{}")}
    with pytest.raises(C2Error):
        adapter_module.read_rows("match $w isa c4-watermark, has c4-commit-id $c;", ("c",))
    assert responder.calls[-1] == "close"
