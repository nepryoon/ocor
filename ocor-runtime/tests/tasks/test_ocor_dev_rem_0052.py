"""OCOR-DEV-REM-0052 (NCP-U05): C4 projections conform to the closed normative elements.

Unit of NORMATIVE-CONFORMANCE-PLAN (2026-10-30), plan unit NCP-U05, register entries
NCR-C4-001, NCR-C4-003 and NCR-C4-004 (this module; NCR-C4-002 follows in the same unit).

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
* NCR-C4-004 -- ADD v1.3 :356 (BA-03: a disposable sandbox serves EXACT_AT_COMMIT(Cn) on named
  logical queries; benchmark of sandbox creation, resource exhaustion test and negative test
  with the emulation unavailable), ADD v1.3 :1366 (emulation unavailable gives
  UNSUPPORTED_CAPABILITY, never a silent downgrade to AT_LEAST_COMMIT), LLD v1.1 :369 (oracle
  BA-03: TypeDB exact-at-commit or PROJECTION_NOT_READY, never a downgrade), Register FR-057
  :179 (a projection beyond Cn serves at-least but not exact-at-commit(Cn)).

Every positive path runs on the real TypeDB and the real PostgreSQL of the stack; the local
HTTP responder stands in for TypeDB only on the failure paths of NCR-C4-003.
"""

from __future__ import annotations

import hashlib
import http.server
import importlib
import json
import os
import threading
import time
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


# -- NCR-C4-004 ------------------------------------------------------------------------------


def _digest_of(payload: str) -> str:
    return "urn:sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _exact(commit: str, fact_id: str = "fact-1") -> NamedQueryRequest:
    return _request(fact_id=fact_id, mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit=commit)


def _three_commits(adapter: Any) -> None:
    for commit, payload in (("commit-1", "V1"), ("commit-2", "V2"), ("commit-3", "V3")):
        adapter.apply_commit(fact_id="fact-1", commit_id=commit, payload=payload)


def test_ncr_c4_004_conforms(adapter: Any) -> None:
    """ADD v1.3 :356 (BA-03) and FR-057 (Register :179): an EXACT_AT_COMMIT(Cn) named logical
    query for a commit the projection has moved beyond is served from a disposable sandbox at
    Cn -- exactly Cn, never the later commit -- and the sandbox is gone once the answer is
    served; the projection itself stays at its own watermark."""
    _three_commits(adapter)

    response = adapter.read(_exact("commit-2"))

    assert (response.served.canonical_commit, response.served.projection_watermark) == ("commit-2", "commit-2")
    assert response.result_digest == _digest_of("V2")
    assert response.served.ontology_release_digest == RELEASE
    assert adapter.read(_exact("commit-1")).result_digest == _digest_of("V1")
    assert adapter.current_watermark() == "commit-3"
    assert adapter.read(_exact("commit-3")).result_digest == _digest_of("V3")
    assert adapter.sandbox_databases() == []


def test_ncr_c4_004_the_sandbox_answers_as_the_projection_did_at_cn(adapter: Any) -> None:
    """BA-03 (ADD v1.3 :356): the sandbox is the projection as it was at Cn -- a fact that did
    not exist yet at Cn is not disclosed (an absent result is a denial, NFR-006 Register :50),
    and the AT_LEAST_COMMIT(Cn) read keeps serving the later commit it declares (ADD v1.3 :1361)."""
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    adapter.apply_commit(fact_id="fact-2", commit_id="commit-2", payload="W2")

    with pytest.raises(C2Error) as caught:
        adapter.read(_exact("commit-1", fact_id="fact-2"))
    assert caught.value.reason_code == "POLICY_DENIED"
    assert adapter.read(_exact("commit-2", fact_id="fact-2")).result_digest == _digest_of("W2")
    later = adapter.read(_request(fact_id="fact-2", mode=ConsistencyMode.AT_LEAST_COMMIT, required_commit="commit-1"))
    assert later.served.canonical_commit == "commit-2"
    assert adapter.sandbox_databases() == []


def test_ncr_c4_004_emulation_unavailable_is_unsupported_capability_never_a_downgrade(
    ledger: Any, clock: Clock, adapter: Any
) -> None:
    """ADD v1.3 :1366: with the emulation unavailable (no sandbox configured) an EXACT_AT_COMMIT(Cn)
    query for a commit the projection has moved beyond is UNSUPPORTED_CAPABILITY, never served
    by the later commit; a commit not landed yet stays PROJECTION_NOT_READY (LLD v1.1 :369)."""
    _three_commits(adapter)
    unavailable = _module("ocor_runtime.c4.typedb_adapter").TypeDBProjectionAdapter(
        release_digest=RELEASE, ledger=ledger, clock=clock, sandbox=None)

    with pytest.raises(C2Error) as caught:
        unavailable.read(_exact("commit-2"))
    assert caught.value.reason_code == "UNSUPPORTED_CAPABILITY"
    with pytest.raises(C2Error) as not_landed:
        unavailable.read(_exact("commit-4"))
    assert not_landed.value.reason_code == "PROJECTION_NOT_READY"
    assert unavailable.read(_exact("commit-3")).result_digest == _digest_of("V3")


def test_ncr_c4_004_a_commit_without_its_projected_history_is_unsupported_capability(adapter: Any) -> None:
    """ADD v1.3 :1366: a sandbox at Cn is built only from the complete history of the branch up to
    Cn; when that history is incomplete (a commit projected before the history was kept) the
    emulation is unavailable for Cn and the answer is UNSUPPORTED_CAPABILITY, nothing else."""
    _three_commits(adapter)
    typedb_adapter = _module("ocor_runtime.c4.typedb_adapter")
    typedb_adapter._write('match $r isa c4-fact-revision, has c4-commit-id "commit-1"; delete $r;')

    for commit in ("commit-1", "commit-2"):
        with pytest.raises(C2Error) as caught:
            adapter.read(_exact(commit))
        assert caught.value.reason_code == "UNSUPPORTED_CAPABILITY"
    assert adapter.sandbox_databases() == []


def test_ncr_c4_004_resource_exhaustion_is_unsupported_capability_and_leaks_nothing(
    ledger: Any, clock: Clock, adapter: Any
) -> None:
    """BA-03 (ADD v1.3 :356), resource exhaustion test on the real TypeDB: while every sandbox
    slot is held the emulation is unavailable (UNSUPPORTED_CAPABILITY, ADD v1.3 :1366); once the
    slots are released the same query is served again and no sandbox database is left behind."""
    _three_commits(adapter)
    typedb_adapter = _module("ocor_runtime.c4.typedb_adapter")
    sandbox = typedb_adapter.TypeDBCommitSandbox(max_sandboxes=2)
    bounded = typedb_adapter.TypeDBProjectionAdapter(release_digest=RELEASE, ledger=ledger, clock=clock,
                                                     sandbox=sandbox)

    with sandbox.open("commit-1", 1) as first, sandbox.open("commit-2", 2) as second:
        assert sorted(bounded.sandbox_databases()) == sorted([first, second])
        with pytest.raises(typedb_adapter.SandboxUnavailableError):
            with sandbox.open("commit-1", 1):
                pytest.fail("a third sandbox was opened beyond the bound")
        with pytest.raises(C2Error) as caught:
            bounded.read(_exact("commit-2"))
        assert caught.value.reason_code == "UNSUPPORTED_CAPABILITY"
    assert bounded.sandbox_databases() == []
    assert bounded.read(_exact("commit-2")).result_digest == _digest_of("V2")
    assert bounded.sandbox_databases() == []


def test_ncr_c4_004_sandbox_creation_benchmark(adapter: Any, record_property: Any) -> None:
    """BA-03 (ADD v1.3 :356), benchmark of sandbox creation on the real TypeDB: a projection of
    ten commits over five facts; each EXACT_AT_COMMIT read at an earlier commit creates, serves
    and drops one sandbox. The timings are recorded in the JUnit report (no threshold is
    normative); every read is exact and no sandbox is left behind."""
    for index in range(1, 11):
        adapter.apply_commit(fact_id=f"fact-{index % 5}", commit_id=f"commit-{index}", payload=f"V{index}")
    timings: list[float] = []
    for _ in range(10):
        started = time.perf_counter()
        response = adapter.read(_exact("commit-6", fact_id="fact-1"))
        timings.append((time.perf_counter() - started) * 1000)
        assert (response.served.canonical_commit, response.result_digest) == ("commit-6", _digest_of("V6"))
    timings.sort()
    record_property("ba03_sandbox_read_ms", json.dumps({
        "samples": len(timings), "min": round(timings[0], 1), "p50": round(timings[len(timings) // 2], 1),
        "max": round(timings[-1], 1), "commits": 10, "facts": 5, "served_commit": "commit-6"}, sort_keys=True))
    assert adapter.sandbox_databases() == []


class SandboxResponder:
    """A local HTTP responder standing in for TypeDB on the failure paths of the sandbox only. It
    records ``(method, path)`` of every request and answers the history of one commit."""

    HISTORY = {"answers": [{"data": {"f": {"value": "fact-1"}, "c": {"value": "commit-1"}, "s": {"value": 1},
                                     "p": {"value": "V1"}}}]}

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], tuple[int, bytes] | bytes] = {}
        self.calls: list[tuple[str, str]] = []
        self.query: object = self.HISTORY
        responder = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _answer(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                path = self.path.rstrip("/")
                kind = next((name for name in ("signin", "open", "query", "close", "commit")
                             if path.endswith(name)), "sandbox" if "_sbx_" in path else "other")
                responder.calls.append((self.command, kind))
                route = responder.routes.get((self.command, kind), responder.default(kind))
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
            do_DELETE = _answer

            def log_message(self, format: str, *args: Any) -> None:
                return None

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def default(self, kind: str) -> tuple[int, bytes]:
        return {"signin": (200, b'{"token": "t"}'), "open": (200, b'{"transactionId": "tx"}'),
                "query": (200, json.dumps(self.query).encode("utf-8"))}.get(kind, (200, b"{}"))

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def sandbox_responder(monkeypatch: pytest.MonkeyPatch) -> Iterator[SandboxResponder]:
    value = SandboxResponder()
    monkeypatch.setattr("ocor_runtime.c4.typedb_adapter.TYPEDB_URL", value.url)
    try:
        yield value
    finally:
        value.close()


SANDBOX_LIFECYCLE_FAILURES: dict[str, dict[tuple[str, str], tuple[int, bytes] | bytes]] = {
    "create-refused": {("POST", "sandbox"): (500, b"{}")},
    "create-connection-dropped": {("POST", "sandbox"): b""},
    "create-bad-status-line": {("POST", "sandbox"): b"GARBAGE\r\n\r\n"},
    "populate-commit-refused": {("POST", "commit"): (500, b"{}")},
    "populate-connection-dropped": {("POST", "commit"): b""},
}


@pytest.mark.parametrize("case", sorted(SANDBOX_LIFECYCLE_FAILURES))
def test_ncr_c4_004_a_sandbox_that_cannot_be_built_is_unavailable_and_dropped(
    sandbox_responder: SandboxResponder, case: str
) -> None:
    """ADD v1.3 :1366: a sandbox the backend refuses to create or to populate makes the emulation
    unavailable -- the typed ``SandboxUnavailableError`` -- and a created sandbox is dropped on
    every error path, a connection-level error included; the slot is released."""
    typedb_adapter = _module("ocor_runtime.c4.typedb_adapter")
    sandbox = typedb_adapter.TypeDBCommitSandbox(max_sandboxes=1)
    sandbox_responder.routes = dict(SANDBOX_LIFECYCLE_FAILURES[case])
    for _ in range(2):  # the slot of the failed attempt is free again
        with pytest.raises(typedb_adapter.SandboxUnavailableError):
            with sandbox.open("commit-1", 1):
                pytest.fail("a sandbox that cannot be built was served")
    if case.startswith("populate"):
        assert ("DELETE", "sandbox") in sandbox_responder.calls
        assert sandbox_responder.calls[-1] == ("DELETE", "sandbox"), sandbox_responder.calls


MALFORMED_HISTORY: dict[str, object] = {
    "no-answer-list": {"answers": None},
    "row-without-data": {"answers": [{}]},
    "sequence-as-text": {"answers": [{"data": {"f": {"value": "fact-1"}, "c": {"value": "commit-1"},
                                               "s": {"value": "1"}, "p": {"value": "V1"}}}]},
    "sequence-as-bool": {"answers": [{"data": {"f": {"value": "fact-1"}, "c": {"value": "commit-1"},
                                               "s": {"value": True}, "p": {"value": "V1"}}}]},
    "empty-payload": {"answers": [{"data": {"f": {"value": "fact-1"}, "c": {"value": "commit-1"},
                                            "s": {"value": 1}, "p": {"value": ""}}}]},
    "sequence-beyond-cn": {"answers": [{"data": {"f": {"value": "fact-1"}, "c": {"value": "commit-1"},
                                                 "s": {"value": 2}, "p": {"value": "V1"}}}]},
}


@pytest.mark.parametrize("case", sorted(MALFORMED_HISTORY))
def test_ncr_c4_004_a_malformed_history_answer_is_refused_before_any_sandbox(
    sandbox_responder: SandboxResponder, case: str
) -> None:
    """Contract :486-491: the projected history read to build a sandbox is an untrusted answer; a
    malformed one is the typed CONTROL_PLANE_UNAVAILABLE, never converted, and no sandbox
    database is created from it."""
    typedb_adapter = _module("ocor_runtime.c4.typedb_adapter")
    sandbox_responder.query = MALFORMED_HISTORY[case]
    with pytest.raises(C2Error) as caught:
        with typedb_adapter.TypeDBCommitSandbox().open("commit-1", 1):
            pytest.fail("a sandbox was built from a malformed history")
    assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"
    assert ("POST", "sandbox") not in sandbox_responder.calls
