"""OCOR-DEV-REM-0052 (NCP-U05): C4 projections conform to the closed normative elements.

Unit of NORMATIVE-CONFORMANCE-PLAN (2026-10-30), plan unit NCP-U05, register entries
NCR-C4-001, NCR-C4-002, NCR-C4-003 and NCR-C4-004 (the SHACL validation of NCR-C4-002 waits for
the PO decision NCP-U05-FUSEKI-SHACL-SERVICE).

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
        release_digest=release, ledger=ledger, quarantine=ledger, clock=clock)


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
        release_digest=RELEASE, ledger=ledger, quarantine=ledger, clock=clock, sandbox=None)

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
    bounded = typedb_adapter.TypeDBProjectionAdapter(release_digest=RELEASE, ledger=ledger, quarantine=ledger, clock=clock,
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


def test_ncr_c4_004_sandbox_creation_benchmark(adapter: Any, record_testsuite_property: Any) -> None:
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
    record_testsuite_property("ba03_sandbox_read_ms", json.dumps({
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


# -- NCR-C4-002 (drift, quarantine, rebuild) ---------------------------------------------------
#
# LLD v1.1 :148: ``ProjectionDriftDetector`` rebuilds a sample from the canonical commit, compares
# the semantic digest, quarantines the divergent projection and prevents EXACT_AT_COMMIT; rebuild
# uses a signed checkpoint and a bounded replay; no projection is authoritative. Register FR-065
# :189: drift, gap and checksum mismatch are detected and a projection is replayed or rebuilt from
# commit or journal; a deleted projection is rebuilt. The canonical store is TerminusDB (ADD v1.3
# Part I §2.2/§2.4, ``ocor_runtime.c3.terminusdb_service``); PostgreSQL C3 is the atomicity
# verification adapter, never the rebuild source.

TENANT = "urn:ocor:tenant:synthetic"
AGGREGATE_TYPE = "MissionObject"
DRIFT_REF = "urn:ocor:mission-object:rem0052-drift:1"
OTHER_REF = "urn:ocor:mission-object:rem0052-drift:2"
CHECKPOINT_SEED = bytes(range(32))
CHECKPOINT_KEY_ID = "urn:ocor:key:c4-checkpoint:rem0052"


def _terminus() -> Any:
    return _module("test_ocor_dev_rem_0041")


@pytest.fixture
def canonical() -> Iterator[Any]:
    """A real TerminusDB C3 canonical store on a disposable database, on the governed path."""
    terminus = _terminus()
    password = terminus._password()
    name = f"ocor_c3_rem0052_{os.urandom(6).hex()}"
    service = _module("ocor_runtime.c3.terminusdb_service").TerminusDBC3Service(
        url=terminus.URL, password=password, database=name, admission=terminus.GOVERNED.admission())
    try:
        service.initialize()
    except OSError as error:
        pytest.fail(f"a real, live TerminusDB server is mandatory qualifying evidence: {error}")
    try:
        yield service
    finally:
        terminus._raw("DELETE", f"/api/db/admin/{name}", password)


def _commit(canonical: Any, ref: str, revision: int, status: str) -> Any:
    command = _terminus().make_command(
        command_id=f"urn:ocor:command:rem0052:{ref.rsplit(':', 1)[-1]}:{revision}",
        idempotency_key=f"rem0052-drift-{ref.rsplit(':', 1)[-1]}-{revision:04d}",
        expected_revision=revision, canonical_delta={"status": status}, aggregate_ref=ref)
    return canonical.commit(command)


def _signing_key() -> Any:
    return _module("ocor_runtime.c1.signing").Ed25519SigningKey.from_seed(CHECKPOINT_SEED)


def _detector(canonical: Any, adapter: Any, *, replay_bound: int = 8, trusted: dict[str, bytes] | None = None) -> Any:
    key = _signing_key()
    return _module("ocor_runtime.c4.rebuild").ProjectionDriftDetector(
        canonical, adapter, signer=key, key_id=CHECKPOINT_KEY_ID,
        trusted_keys=trusted if trusted is not None else {CHECKPOINT_KEY_ID: key.public_key},
        replay_bound=replay_bound)


def _aggregate(ref: str) -> tuple[str, str, str]:
    return (TENANT, AGGREGATE_TYPE, ref)


def _tamper(adapter: Any, ref: str, commit: str) -> None:
    _module("c4_projection_fixture").overwrite_fact(fact_id=ref, commit_id=commit, payload="tampered-digest")


def test_ncr_c4_002_conforms(canonical: Any, adapter: Any, ledger: Any, clock: Clock) -> None:
    """LLD v1.1 :148: a divergent projection is quarantined durably and the quarantine is enforced
    on the read path of the projection itself -- every state-dependent read of the aggregate,
    EXACT_AT_COMMIT included, is PROJECTION_NOT_READY with the served context of the last confirmed
    watermark -- for a new adapter and a new detector as well (the quarantine is outside the
    process and outside the projection store)."""
    receipt = _commit(canonical, DRIFT_REF, 0, "ASSESSED")
    assert _detector(canonical, adapter).rebuild(
        tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=DRIFT_REF).drift_detected is False
    _tamper(adapter, DRIFT_REF, receipt.commit_id)

    report = _detector(canonical, adapter).rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE,
                                                   aggregate_ref=DRIFT_REF)
    assert (report.drift_detected, report.quarantined) == (True, True)

    restarted = _adapter(ledger, clock)
    assert _detector(canonical, restarted).is_quarantined(DRIFT_REF)
    for request in (_exact(receipt.commit_id, fact_id=DRIFT_REF), _request(fact_id=DRIFT_REF)):
        with pytest.raises(C2Error) as caught:
            restarted.read(request)
        assert caught.value.reason_code == "PROJECTION_NOT_READY"
        assert caught.value.served is not None
        assert caught.value.served.canonical_commit == receipt.commit_id
    record = restarted.quarantine_record(DRIFT_REF)
    assert (record.canonical_commit, record.served_digest) == (receipt.commit_id, _digest_of("tampered-digest"))


def test_ncr_c4_002_a_quarantine_is_released_only_by_a_reconciling_rebuild(
    canonical: Any, adapter: Any, ledger: Any, clock: Clock
) -> None:
    """LLD v1.1 :148 and FR-065 :189: the quarantine holds until a rebuild from the canonical commit
    finds the projection reconciled; then the aggregate is served again, exactly at its commit."""
    receipt = _commit(canonical, DRIFT_REF, 0, "ASSESSED")
    detector = _detector(canonical, adapter)
    detector.rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=DRIFT_REF)
    _tamper(adapter, DRIFT_REF, receipt.commit_id)
    detector.rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=DRIFT_REF)
    _tamper(adapter, DRIFT_REF, receipt.commit_id)
    assert detector.rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE,
                            aggregate_ref=DRIFT_REF).quarantined is True

    snapshot = canonical.read(TENANT, AGGREGATE_TYPE, DRIFT_REF)
    _module("c4_projection_fixture").overwrite_fact(fact_id=DRIFT_REF, commit_id=snapshot.commit_id,
                                                    payload=snapshot.state_digest)
    assert _detector(canonical, _adapter(ledger, clock)).rebuild(
        tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=DRIFT_REF).quarantined is False
    assert adapter.quarantine_record(DRIFT_REF) is None
    response = adapter.read(_exact(receipt.commit_id, fact_id=DRIFT_REF))
    assert response.served.canonical_commit == receipt.commit_id
    assert response.result_digest == _digest_of(snapshot.state_digest)


def test_ncr_c4_002_the_rebuild_source_is_the_canonical_terminusdb_store(adapter: Any, dsn: str) -> None:
    """ADD v1.3 Part I §2.2/§2.4 and DEC-201: the drift detector rebuilds from the canonical
    TerminusDB store; the PostgreSQL C3 service (atomicity verification adapter) is refused."""
    postgres_c3 = _module("ocor_runtime.c3.service").PostgresC3Service(
        dsn, admission=_terminus().GOVERNED.admission())
    with pytest.raises(TypeError):
        _module("ocor_runtime.c4.rebuild").ProjectionDriftDetector(postgres_c3, adapter)


class _UnreadableQuarantine:
    """A quarantine store that cannot be read: the local failure handling of the read path."""

    @staticmethod
    def _fail() -> Any:
        raise _module("ocor_runtime.c4.watermark").WatermarkLedgerError(
            "CONTROL_PLANE_UNAVAILABLE", "quarantine store unreachable")

    def quarantine(self, *args: Any, **kwargs: Any) -> Any:
        return self._fail()

    def release(self, *args: Any, **kwargs: Any) -> Any:
        return self._fail()

    def active(self, *args: Any, **kwargs: Any) -> Any:
        return self._fail()

    def clear_quarantine(self, *args: Any, **kwargs: Any) -> Any:
        return self._fail()


def test_ncr_c4_002_an_unreadable_quarantine_fails_closed(adapter: Any, ledger: Any, clock: Clock) -> None:
    """LLD v1.1 :346 and contract :486-491: when the durable quarantine cannot be consulted the read
    is the typed CONTROL_PLANE_UNAVAILABLE, never served as if the projection were healthy."""
    adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    blind = _module("ocor_runtime.c4.typedb_adapter").TypeDBProjectionAdapter(
        release_digest=RELEASE, ledger=ledger, quarantine=_UnreadableQuarantine(), clock=clock)
    for request in (_request(), _exact("commit-1")):
        with pytest.raises(C2Error) as caught:
            blind.read(request)
        assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"


def test_ncr_c4_002_a_projection_requires_a_durable_quarantine(ledger: Any, clock: Clock) -> None:
    """LLD v1.1 :148: the projection cannot be built without the quarantine it must enforce."""
    with pytest.raises(TypeError):
        _module("ocor_runtime.c4.typedb_adapter").TypeDBProjectionAdapter(release_digest=RELEASE, ledger=ledger,
                                                                          clock=clock)


def _two_aggregates(canonical: Any, detector: Any) -> tuple[Any, Any]:
    first = _commit(canonical, DRIFT_REF, 0, "ASSESSED")
    second = _commit(canonical, OTHER_REF, 0, "ASSESSED")
    for ref in (DRIFT_REF, OTHER_REF):
        detector.rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=ref)
    return first, second


def test_ncr_c4_002_a_deleted_projection_is_rebuilt_from_a_signed_checkpoint_and_a_bounded_replay(
    canonical: Any, adapter: Any, record_testsuite_property: Any
) -> None:
    """LLD v1.1 :148 and FR-065 :189 (acceptance: a deleted projection is rebuilt): the checkpoint is
    signed and kept outside the projection store; after the projection is deleted the rebuild
    restores the checkpoint, replays from the canonical store the commits after it, and serves
    every aggregate exactly at its canonical commit."""
    detector = _detector(canonical, adapter)
    _two_aggregates(canonical, detector)
    checkpoint = detector.checkpoint(aggregates=[_aggregate(DRIFT_REF), _aggregate(OTHER_REF)])
    assert checkpoint.key_id == CHECKPOINT_KEY_ID
    later = _commit(canonical, DRIFT_REF, 1, "ENGAGED")

    adapter.reset()
    started = time.perf_counter()
    report = _detector(canonical, adapter).rebuild_projection()
    elapsed = time.perf_counter() - started
    record_testsuite_property("ncr_c4_002_rebuild_seconds", f"{elapsed:.3f}")

    assert (report.checkpoint_watermark, report.replayed) == (checkpoint.watermark, 1)
    assert report.watermark == later.commit_id == adapter.current_watermark()
    for ref in (DRIFT_REF, OTHER_REF):
        snapshot = canonical.read(TENANT, AGGREGATE_TYPE, ref)
        served = adapter.read(_exact(snapshot.commit_id, fact_id=ref))
        assert served.result_digest == _digest_of(snapshot.state_digest)
        assert adapter.quarantine_record(ref) is None


def test_ncr_c4_002_a_replay_beyond_the_bound_fails_closed_before_any_write(canonical: Any, adapter: Any) -> None:
    """LLD v1.1 :148 (bounded replay): a rebuild that would replay more commits than its bound is
    refused before the projection is touched."""
    detector = _detector(canonical, adapter, replay_bound=1)
    _two_aggregates(canonical, detector)
    detector.checkpoint(aggregates=[_aggregate(DRIFT_REF), _aggregate(OTHER_REF)])
    _commit(canonical, DRIFT_REF, 1, "ENGAGED")
    _commit(canonical, OTHER_REF, 1, "ENGAGED")
    watermark = adapter.current_watermark()

    with pytest.raises(_module("ocor_runtime.c4.rebuild").DriftError) as caught:
        detector.rebuild_projection()
    assert caught.value.reason_code == "REPLAY_BOUND_EXCEEDED"
    assert adapter.current_watermark() == watermark


@pytest.mark.parametrize("case", ["tampered-payload", "tampered-signature", "untrusted-key", "no-trust-root"])
def test_ncr_c4_002_an_unverifiable_checkpoint_is_refused(canonical: Any, adapter: Any, case: str) -> None:
    """LLD v1.1 :148: the rebuild uses only a checkpoint whose signature verifies under a trusted
    key; anything else is CHECKPOINT_INVALID and the projection is not touched."""
    detector = _detector(canonical, adapter)
    _two_aggregates(canonical, detector)
    checkpoint = detector.checkpoint(aggregates=[_aggregate(DRIFT_REF), _aggregate(OTHER_REF)])
    drift = _module("ocor_runtime.c4.drift")
    trusted: dict[str, bytes] = {CHECKPOINT_KEY_ID: _signing_key().public_key}
    if case == "tampered-payload":
        body = json.loads(checkpoint.payload)
        body["entries"][0]["payload"] = "tampered-digest"
        checkpoint = drift.SignedProjectionCheckpoint(
            payload=json.dumps(body).encode("utf-8"), key_id=checkpoint.key_id, signature=checkpoint.signature)
    elif case == "tampered-signature":
        checkpoint = drift.SignedProjectionCheckpoint(
            payload=checkpoint.payload, key_id=checkpoint.key_id, signature=bytes(64))
    elif case == "untrusted-key":
        other = _module("ocor_runtime.c1.signing").Ed25519SigningKey.from_seed(bytes(32))
        trusted = {CHECKPOINT_KEY_ID: other.public_key}
    else:
        trusted = {}
    watermark = adapter.current_watermark()

    with pytest.raises(_module("ocor_runtime.c4.rebuild").DriftError) as caught:
        _detector(canonical, adapter, trusted=trusted).rebuild_projection(checkpoint=checkpoint)
    assert caught.value.reason_code == "CHECKPOINT_INVALID"
    assert adapter.current_watermark() == watermark


def test_ncr_c4_002_a_checkpoint_of_a_divergent_projection_is_refused(canonical: Any, adapter: Any) -> None:
    """LLD v1.1 :148 (no projection is authoritative): a checkpoint is taken only of a projection
    that reconciles with the canonical store; a divergent one is quarantined instead."""
    detector = _detector(canonical, adapter)
    first, _ = _two_aggregates(canonical, detector)
    _tamper(adapter, DRIFT_REF, first.commit_id)

    with pytest.raises(_module("ocor_runtime.c4.rebuild").DriftError) as caught:
        detector.checkpoint(aggregates=[_aggregate(DRIFT_REF), _aggregate(OTHER_REF)])
    assert caught.value.reason_code == "DRIFT_DETECTED"
    assert adapter.quarantine_record(DRIFT_REF) is not None


def test_ncr_c4_002_a_checkpoint_must_cover_the_whole_projection(canonical: Any, adapter: Any) -> None:
    """LLD v1.1 :148 (rebuild uses the checkpoint): a checkpoint that omits a projected aggregate
    could not rebuild it, so it is refused."""
    detector = _detector(canonical, adapter)
    _two_aggregates(canonical, detector)
    with pytest.raises(_module("ocor_runtime.c4.rebuild").DriftError) as caught:
        detector.checkpoint(aggregates=[_aggregate(DRIFT_REF)])
    assert caught.value.reason_code == "CHECKPOINT_INCOMPLETE"


# -- NCR-C4-002 (Jena: watermark, canonical marking, typed errors) -------------------------------
#
# LLD v1.1 :148: Jena exposes RDF/JSON-LD with conservative marking, and every projector advances
# its watermark only in the same transaction as the projection. ADD v1.3 §3.0.2 (:396-401): the
# marking exists in one canonical form, the ``marking`` object of §3.2 ``$defs`` (:741-787),
# governed by the ``MarkingSchemeDefinition`` of §3.1.1 (:429); a ``marking_digest`` that does not
# match the object is DENY. ADD v1.3 §5.3 (:3256-3282): join, dominance and unknown/incomparable
# behaviour per family. LLD v1.1 §1.3 (:67): a missing, incomparable or unresolvable marking is
# ``MARKING_UNRESOLVED``. Register FR-068 (:192) and FR-131 (:298): boundaries and markings
# propagate to projections and exports. The SHACL validation through the Fuseki SHACL service
# waits for the PO decision NCP-U05-FUSEKI-SHACL-SERVICE and is not part of these cases.

SCHEME_ID = "urn:ocor:marking-scheme:rem0052"
LEVEL_PAIRS = (("UNCLASSIFIED", "ALPHA"), ("UNCLASSIFIED", "BRAVO"), ("ALPHA", "SECRET"), ("BRAVO", "SECRET"),
               ("SECRET", "TOP_SECRET"))
LEVELS = ("UNCLASSIFIED", "ALPHA", "BRAVO", "SECRET", "TOP_SECRET")


def _order(pairs: tuple[tuple[str, str], ...], levels: tuple[str, ...]) -> list[list[str]]:
    """The reflexive-transitive closure of ``pairs`` as the declared ``dominance_relation``."""
    closure = {(level, level) for level in levels} | set(pairs)
    while True:
        extra = {(a, d) for a, b in closure for c, d in closure if b == c} - closure
        if not extra:
            return sorted([a, b] for a, b in closure)
        closure |= extra


def _family(name: str, vocabulary: list[str], kind: str = "RESTRICTION") -> dict[str, Any]:
    join, meet = ("UNION", "INTERSECTION") if kind == "RESTRICTION" else ("INTERSECTION", "UNION")
    return {"family": name, "vocabulary": vocabulary, "kind": kind, "join_operator": join, "meet_operator": meet,
            "neutral_element": [] if kind == "RESTRICTION" else list(vocabulary)}


def _scheme_ir(**changes: Any) -> dict[str, Any]:
    """A ``MarkingSchemeDefinition`` of the C1 IR (ADD v1.3 :429; ``ocor_runtime.c1.oac``)."""
    value: dict[str, Any] = {
        "construct": "MarkingSchemeDefinition", "scheme_id": SCHEME_ID, "version": "1.0.0", "levels": list(LEVELS),
        "top": "TOP_SECRET", "bottom": "UNCLASSIFIED", "dominance_relation": _order(LEVEL_PAIRS, LEVELS),
        "family_definitions": [
            _family("mandatory_markings", ["MM-ALPHA", "MM-BRAVO"]),
            _family("caveats", ["CV-EYES-ONLY", "CV-ORCON"]),
            _family("dissemination_controls", ["DC-NOEXPORT", "DC-RELIDO"]),
            _family("permitted_purposes", ["audit", "logistics", "mission-planning"], kind="PERMISSION"),
            _family("handling_instructions", ["HI-ENCRYPT-AT-REST", "HI-TWO-PERSON"]),
        ],
        "unknown_value_behavior": "DENY", "incomparable_behavior": "DENY",
        "declassification_authority_ref": "urn:ocor:authority:declassification:rem0052",
    }
    value.update(changes)
    return value


def _scheme(**changes: Any) -> Any:
    return _module("ocor_runtime.c4.marking").CanonicalMarkingScheme(_scheme_ir(**changes))


def _marking(level: str, *, mandatory: tuple[str, ...] = (), caveats: tuple[str, ...] = (),
             controls: tuple[str, ...] = (), purposes: tuple[str, ...] = ("logistics", "mission-planning"),
             handling: tuple[str, ...] = (), **changes: Any) -> dict[str, Any]:
    """A canonical ``marking`` object of ADD v1.3 §3.2 ``$defs`` with its own digest."""
    value: dict[str, Any] = {
        "scheme_id": SCHEME_ID, "labels": sorted({level, *mandatory, *caveats}),
        "mandatory_markings": sorted(mandatory), "caveats": sorted(caveats),
        "dissemination_controls": sorted(controls), "permitted_purposes": sorted(purposes),
        "handling_instructions": sorted(handling),
    }
    value.update(changes)
    value["marking_digest"] = _module("ocor_runtime.c5.envelope").marking_digest(value)
    return value


def _clearance(level: str = "SECRET", **families: Any) -> dict[str, Any]:
    """The requester's accreditation, evaluated under the same scheme: a level, the restriction
    families the requester holds and the purpose the request is made for."""
    families.setdefault("purposes", ("mission-planning",))
    families.setdefault("mandatory", ("MM-ALPHA", "MM-BRAVO"))
    families.setdefault("caveats", ("CV-EYES-ONLY", "CV-ORCON"))
    families.setdefault("controls", ("DC-NOEXPORT", "DC-RELIDO"))
    families.setdefault("handling", ("HI-ENCRYPT-AT-REST", "HI-TWO-PERSON"))
    return _marking(level, **families)


def _ref(marking: dict[str, Any]) -> str:
    return "urn:" + marking["marking_digest"]


def _properties(label: str = "fixture") -> dict[str, str]:
    return {"label": label, "provenanceRef": "urn:ocor:provenance:rem0052-1"}


def _jena(ledger: Any, clock: Clock, *, release: str = RELEASE, scheme: Any = None) -> Any:
    return _module("ocor_runtime.c4.jena_adapter").JenaSHACLProjectionAdapter(
        marking_scheme=_scheme() if scheme is None else scheme, release_digest=release, ledger=ledger, clock=clock)


@pytest.fixture
def jena(ledger: Any, clock: Clock) -> Iterator[Any]:
    value = _jena(ledger, clock)
    try:
        value.initialize()
        value.reset()
    except (_module("ocor_runtime.c4.jena_adapter").JenaAdapterError, OSError) as error:
        pytest.fail(f"a real, live Fuseki instance is mandatory qualifying evidence: {error}")
    try:
        yield value
    finally:
        value.reset()


def _sparql_update(update: str) -> None:
    """An out-of-band write to the Fuseki dataset of the stack, outside the adapter."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    request = __import__("urllib.request").request.Request(
        f"{jena_adapter.FUSEKI_URL}/{jena_adapter.DATASET}/update", method="POST", data=update.encode("utf-8"),
        headers={"Content-Type": "application/sparql-update"})
    with __import__("urllib.request").request.urlopen(request, timeout=10) as response:
        assert response.status in (200, 204)


R1 = "urn:ocor:resource:rem0052-jena:1"
R2 = "urn:ocor:resource:rem0052-jena:2"
R3 = "urn:ocor:resource:rem0052-jena:3"


def test_ncr_c4_002_jena_conforms(jena: Any, ledger: Any) -> None:
    """LLD v1.1 :148 and ADD v1.3 §3.0.2: each publication advances the Jena watermark to its
    canonical commit in the same update as the triples and is confirmed in the durable ledger;
    the marking persisted with the resource is the canonical object, evaluated with the
    ``MarkingSchemeDefinition``; no legacy one-label-per-scheme engine is used."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    assert "ocor_runtime.c4_marking" not in {getattr(value, "__module__", None) for value in vars(jena_adapter).values()}
    secret = _marking("SECRET", caveats=("CV-ORCON",))
    assert jena.publish(R1, _properties("one"), marking=_marking("UNCLASSIFIED"), commit_id="commit-j1") is True
    assert jena.publish(R2, _properties("two"), marking=secret, commit_id="commit-j2") is True

    assert jena.current_watermark() == "commit-j2"
    confirmed = ledger.latest(jena.store_id, "main")
    assert (confirmed.commit_id, confirmed.sequence, confirmed.release_digest) == ("commit-j2", 2, RELEASE)
    assert jena.watermark() == confirmed
    rows = {row["resource"]: row for row in jena.list_authorized(_clearance("SECRET"))}
    assert set(rows) == {R1, R2}
    assert (rows[R2]["commitId"], rows[R2]["markingRef"]) == ("commit-j2", _ref(secret))
    assert jena.list_authorized(_clearance("ALPHA")) == [rows[R1]]


def test_ncr_c4_002_jena_replay_of_a_commit_is_idempotent(jena: Any, ledger: Any) -> None:
    """LLD v1.1 :148 and Register FR-064 :188: a replayed commit writes nothing and never moves the
    watermark, an earlier commit replayed after a later one included."""
    jena.publish(R1, _properties("one"), marking=_marking("SECRET"), commit_id="commit-j1")
    jena.publish(R2, _properties("two"), marking=_marking("SECRET"), commit_id="commit-j2")
    assert jena.publish(R1, _properties("replayed"), marking=_marking("SECRET"), commit_id="commit-j1") is False
    assert jena.current_watermark() == "commit-j2"
    assert ledger.latest(jena.store_id, "main").commit_id == "commit-j2"
    assert {row["label"] for row in jena.list_authorized(_clearance())} == {"one", "two"}
    assert jena.raw_unfiltered_triple_count() == 2


def test_ncr_c4_002_jena_a_refused_publication_moves_no_watermark(jena: Any, ledger: Any) -> None:
    """LLD v1.1 :148 (the watermark advances only with the projection): a publication refused by
    the shape, the provenance or the marking writes neither triples nor watermark, and the
    watermark predicates are never accepted from the caller."""
    jena.publish(R1, _properties("one"), marking=_marking("SECRET"), commit_id="commit-j1")
    refused = [
        ({"label": "x", "provenanceRef": "urn:ocor:provenance:1", "commitId": "commit-forged"}, _marking("SECRET")),
        ({"label": "x", "provenanceRef": "urn:ocor:provenance:1", "classification": "SECRET"}, _marking("SECRET")),
        ({"label": "x", "provenanceRef": "lossy"}, _marking("SECRET")),
        (_properties("x"), _forged_digest(_marking("SECRET"))),
    ]
    for properties, marking in refused:
        with pytest.raises(_module("ocor_runtime.c4.jena_adapter").JenaAdapterError):
            jena.publish(R2, properties, marking=marking, commit_id="commit-j2")
    assert jena.current_watermark() == "commit-j1"
    assert ledger.latest(jena.store_id, "main").commit_id == "commit-j1"
    assert jena.raw_unfiltered_triple_count() == 1


def _forged_digest(marking: dict[str, Any]) -> dict[str, Any]:
    return {**marking, "marking_digest": "sha256:" + "0" * 64}


UNRESOLVED_MARKINGS: dict[str, Any] = {
    "digest-mismatch": lambda: _forged_digest(_marking("SECRET")),
    "unknown-level": lambda: _marking("COSMIC"),
    "two-levels": lambda: _marking("SECRET", labels=["ALPHA", "SECRET"]),
    "labels-not-partitioned": lambda: _marking("SECRET", caveats=("CV-ORCON",), labels=["SECRET"]),
    "unknown-caveat": lambda: _marking("SECRET", caveats=("CV-UNKNOWN",)),
    "unknown-control": lambda: _marking("SECRET", controls=("DC-UNKNOWN",)),
    "unknown-purpose": lambda: _marking("SECRET", purposes=("marketing",)),
    "no-purpose": lambda: _marking("SECRET", purposes=()),
    "other-scheme": lambda: _marking("SECRET", scheme_id="urn:ocor:marking-scheme:other"),
    "missing-field": lambda: {key: value for key, value in _marking("SECRET").items() if key != "caveats"},
    "extra-field": lambda: _marking("SECRET", classification="SECRET"),
    "not-an-object": lambda: "SECRET",
}


@pytest.mark.parametrize("case", sorted(UNRESOLVED_MARKINGS))
def test_ncr_c4_002_an_unresolvable_marking_is_refused_before_any_write(jena: Any, case: str) -> None:
    """ADD v1.3 §3.0.2 :401 and LLD v1.1 §1.3 :67: a marking that is not the canonical object of the
    active scheme, carries an unknown value or a digest that does not match is MARKING_UNRESOLVED,
    never a permissive posture; nothing is written."""
    with pytest.raises(_module("ocor_runtime.c4.jena_adapter").JenaAdapterError) as caught:
        jena.publish(R1, _properties(), marking=UNRESOLVED_MARKINGS[case](), commit_id="commit-j1")
    assert caught.value.reason_code == "MARKING_UNRESOLVED"
    assert (jena.current_watermark(), jena.raw_unfiltered_triple_count()) == (None, 0)


@pytest.mark.parametrize("case", sorted(UNRESOLVED_MARKINGS))
def test_ncr_c4_002_an_unresolvable_clearance_is_marking_unresolved(jena: Any, case: str) -> None:
    """ADD v1.3 §5.3 :3280: without an active scheme, a known label or a complete context the
    request is denied; no unknown value is discarded."""
    jena.publish(R1, _properties(), marking=_marking("UNCLASSIFIED"), commit_id="commit-j1")
    for read in (lambda c: jena.list_authorized(c), lambda c: jena.exists_authorized(R1, c),
                 lambda c: jena.to_json_ld(R1, c), lambda c: jena.export([R1], c)):
        with pytest.raises(_module("ocor_runtime.c4.jena_adapter").JenaAdapterError) as caught:
            read(UNRESOLVED_MARKINGS[case]())
        assert caught.value.reason_code == "MARKING_UNRESOLVED"


DOMINANCE_CASES: dict[str, tuple[dict[str, Any], dict[str, Any], bool]] = {
    "level-dominates": (_marking("ALPHA"), _clearance("SECRET"), True),
    "level-below": (_marking("TOP_SECRET"), _clearance("SECRET"), False),
    "level-incomparable": (_marking("BRAVO"), _clearance("ALPHA"), False),
    "caveat-held": (_marking("ALPHA", caveats=("CV-ORCON",)), _clearance("SECRET"), True),
    "caveat-not-held": (_marking("ALPHA", caveats=("CV-ORCON",)), _clearance("SECRET", caveats=("CV-EYES-ONLY",)), False),
    "mandatory-not-held": (_marking("ALPHA", mandatory=("MM-BRAVO",)), _clearance("SECRET", mandatory=("MM-ALPHA",)),
                           False),
    "control-not-held": (_marking("ALPHA", controls=("DC-NOEXPORT",)), _clearance("SECRET", controls=()), False),
    "handling-not-held": (_marking("ALPHA", handling=("HI-TWO-PERSON",)), _clearance("SECRET", handling=()), False),
    "purpose-permitted": (_marking("ALPHA", purposes=("logistics", "mission-planning")),
                          _clearance("SECRET", purposes=("logistics",)), True),
    "purpose-not-permitted": (_marking("ALPHA", purposes=("logistics",)), _clearance("SECRET", purposes=("audit",)),
                              False),
}


@pytest.mark.parametrize("case", sorted(DOMINANCE_CASES))
def test_ncr_c4_002_a_read_requires_dominance_on_every_family(jena: Any, case: str) -> None:
    """ADD v1.3 §5.3 :3271-3278: the clearance dominates the content on the level lattice and on
    every family -- superset for the restriction families, subset of the permitted purposes --
    and an incomparable level never dominates; a denied item is absent from list, existence and
    export, and the count never diverges from the authorized list (FR-068 :192)."""
    content, clearance, allowed = DOMINANCE_CASES[case]
    jena.publish(R1, _properties(), marking=content, commit_id="commit-j1")
    assert jena.exists_authorized(R1, clearance) is allowed
    assert [row["resource"] for row in jena.list_authorized(clearance)] == ([R1] if allowed else [])
    if allowed:
        assert jena.to_json_ld(R1, clearance)
    else:
        with pytest.raises(_module("ocor_runtime.c4.jena_adapter").JenaAdapterError) as caught:
            jena.to_json_ld(R1, clearance)
        assert caught.value.reason_code == "MARKING_DENIED"


def test_ncr_c4_002_the_export_carries_the_conservative_join_and_the_watermark(jena: Any) -> None:
    """LLD v1.1 :148 (RDF/JSON-LD with conservative marking), ADD v1.3 §5.3 :3258-3266 and FR-131
    :298: the export of several resources carries the join of their markings -- least upper bound
    of the levels, union of the restriction families, intersection of the permitted purposes --
    and the canonical commit of the watermark it was read at."""
    first = _marking("UNCLASSIFIED", caveats=("CV-ORCON",), purposes=("logistics", "mission-planning"))
    second = _marking("ALPHA", controls=("DC-NOEXPORT",), handling=("HI-ENCRYPT-AT-REST",),
                      purposes=("mission-planning", "audit"))
    jena.publish(R1, _properties("one"), marking=first, commit_id="commit-j1")
    jena.publish(R2, _properties("two"), marking=second, commit_id="commit-j2")

    exported = jena.export([R1, R2], _clearance("SECRET"))
    assert exported.marking == _marking("ALPHA", caveats=("CV-ORCON",), controls=("DC-NOEXPORT",),
                                        handling=("HI-ENCRYPT-AT-REST",), purposes=("mission-planning",))
    assert (exported.canonical_commit, exported.release_digest) == ("commit-j2", RELEASE)
    subjects = {node["@id"] for node in exported.document if "@id" in node}
    assert {R1, R2} <= subjects
    with pytest.raises(_module("ocor_runtime.c4.jena_adapter").JenaAdapterError) as caught:
        jena.export([R1, R2], _clearance("UNCLASSIFIED"))
    assert caught.value.reason_code == "MARKING_DENIED"


def test_ncr_c4_002_the_join_is_conservative_and_fails_closed() -> None:
    """ADD v1.3 §5.3 :3271-3280: the join never yields a marking less restrictive than an input;
    incomparable levels are DENY unless the scheme declares MOST_RESTRICTIVE (then top); an empty
    intersection of the permitted purposes is DENY."""
    marking = _module("ocor_runtime.c4.marking")
    scheme = _scheme()
    inputs = [_marking("UNCLASSIFIED", mandatory=("MM-ALPHA",)), _marking("SECRET", caveats=("CV-ORCON",))]
    joined = scheme.join(*inputs)
    assert all(scheme.dominates(joined, value) for value in inputs)
    assert joined == _marking("SECRET", mandatory=("MM-ALPHA",), caveats=("CV-ORCON",))
    assert scheme.join(joined, joined) == joined
    assert scheme.join(*reversed(inputs)) == joined
    for incomparable in ([_marking("ALPHA"), _marking("BRAVO")],
                         [_marking("ALPHA", purposes=("audit",)), _marking("ALPHA", purposes=("logistics",))]):
        with pytest.raises(marking.MarkingUnresolved):
            scheme.join(*incomparable)
    assert _scheme(incomparable_behavior="MOST_RESTRICTIVE").join(_marking("ALPHA"), _marking("BRAVO")) == \
        _marking("TOP_SECRET")


def _without(name: str) -> list[dict[str, Any]]:
    return [family for family in _scheme_ir()["family_definitions"] if family["family"] != name]


INVALID_SCHEMES: dict[str, dict[str, Any]] = {
    "permission-caveats": {"family_definitions": _without("caveats") + [
        _family("caveats", ["CV-EYES-ONLY", "CV-ORCON"], kind="PERMISSION")]},
    "restriction-purposes": {"family_definitions": _without("permitted_purposes") + [
        _family("permitted_purposes", ["audit"], kind="RESTRICTION")]},
    "four-families": {"family_definitions": _without("handling_instructions")},
    "unknown-allowed": {"unknown_value_behavior": "ALLOW"},
    "incomparable-allowed": {"incomparable_behavior": "PERMIT"},
    "not-a-lattice": {"dominance_relation": _order((("UNCLASSIFIED", "ALPHA"), ("UNCLASSIFIED", "BRAVO"),
                                                     ("ALPHA", "SECRET"), ("BRAVO", "SECRET"), ("ALPHA", "TOP_SECRET"),
                                                     ("BRAVO", "TOP_SECRET")), LEVELS)},
    "not-transitive": {"dominance_relation": sorted([[a, a] for a in LEVELS] + [list(p) for p in LEVEL_PAIRS])},
    "wrong-top": {"top": "SECRET"},
}


@pytest.mark.parametrize("case", sorted(INVALID_SCHEMES))
def test_ncr_c4_002_a_scheme_outside_the_supported_profile_is_refused(case: str) -> None:
    """ADD v1.3 :429 and §5.3 :3268: a scheme with a PERMISSION restriction family, a missing
    family, an implicit default or an order that is not a lattice is refused; no projection is
    built on it."""
    with pytest.raises(_module("ocor_runtime.c4.marking").MarkingSchemeError):
        _scheme(**INVALID_SCHEMES[case])


def test_ncr_c4_002_a_stored_marking_that_no_longer_matches_is_denied(jena: Any) -> None:
    """ADD v1.3 §3.0.2 :401: a marking whose digest no longer matches the object -- a storage
    corruption of the projection that lowers it -- is DENY: the resource is withheld from every
    read, never served under the lowered marking."""
    original = _marking("TOP_SECRET")
    jena.publish(R1, _properties(), marking=original, commit_id="commit-j1")
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    lowered = json.dumps(original).replace("TOP_SECRET", "UNCLASSIFIED")
    _sparql_update(f"{jena_adapter.PREFIX} DELETE {{ <{R1}> ocor:markingObject ?m }} INSERT {{ <{R1}> "
                   f"ocor:markingObject {jena_adapter._literal(lowered)} }} WHERE {{ <{R1}> ocor:markingObject ?m }}")
    assert jena.list_authorized(_clearance("SECRET")) == []
    assert jena.exists_authorized(R1, _clearance("SECRET")) is False
    with pytest.raises(jena_adapter.JenaAdapterError) as caught:
        jena.to_json_ld(R1, _clearance("SECRET"))
    assert caught.value.reason_code == "MARKING_DENIED"


def test_ncr_c4_002_a_watermark_that_disagrees_with_the_ledger_is_projection_not_ready(jena: Any) -> None:
    """LLD v1.1 :148 and NFR-077 :403: the Jena watermark and the confirmed one of the ledger must
    name the same commit; a projection that lost or bypassed it is an explicit
    PROJECTION_NOT_READY, and no export is correlated with a watermark the ledger did not confirm."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    jena.publish(R1, _properties(), marking=_marking("UNCLASSIFIED"), commit_id="commit-j1")
    _sparql_update(f"{jena_adapter.PREFIX} DELETE {{ ?s ocor:watermarkCommit ?c }} INSERT {{ ?s ocor:watermarkCommit "
                   f"\"commit-forged\" }} WHERE {{ ?s ocor:watermarkCommit ?c }}")
    for read in (jena.watermark, lambda: jena.export([R1], _clearance())):
        with pytest.raises(jena_adapter.JenaAdapterError) as caught:
            read()
        assert caught.value.reason_code == "PROJECTION_NOT_READY"


def test_ncr_c4_002_jena_requires_the_declared_release_and_a_ledger(ledger: Any, clock: Clock) -> None:
    """LLD v1.1 :148 and FR-148 :331: the Jena projection declares the release it projects and
    confirms its watermark in a durable ledger; it cannot be built without either."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    for kwargs in ({"release_digest": "not-a-digest", "ledger": ledger}, {"release_digest": RELEASE, "ledger": object()}):
        with pytest.raises(TypeError):
            jena_adapter.JenaSHACLProjectionAdapter(marking_scheme=_scheme(), clock=clock, **kwargs)
    with pytest.raises(TypeError):
        jena_adapter.JenaSHACLProjectionAdapter(marking_scheme=_scheme_ir(), release_digest=RELEASE, ledger=ledger,
                                                clock=clock)


class FusekiResponder:
    """A local HTTP responder standing in for Fuseki on the failure paths only."""

    def __init__(self, route: tuple[int, bytes] | bytes) -> None:
        responder = self
        self.route = route

        class Handler(http.server.BaseHTTPRequestHandler):
            def _answer(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self.close_connection = True
                if isinstance(responder.route, bytes):
                    self.wfile.write(responder.route)
                    return
                status, body = responder.route
                self.send_response(status)
                self.send_header("Content-Type", "application/sparql-results+json")
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

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


JENA_FAILURES: dict[str, tuple[tuple[int, bytes] | bytes | None, str]] = {
    "refused-connection": (None, "PROJECTION_NOT_READY"),
    "http-error": ((500, b"{}"), "CONTROL_PLANE_UNAVAILABLE"),
    "connection-dropped": (b"", "CONTROL_PLANE_UNAVAILABLE"),
    "bad-status-line": (b"GARBAGE\r\n\r\n", "CONTROL_PLANE_UNAVAILABLE"),
    "not-json": ((200, b"<html/>"), "CONTROL_PLANE_UNAVAILABLE"),
    "no-bindings": ((200, b'{"results": {}}'), "CONTROL_PLANE_UNAVAILABLE"),
}


@pytest.mark.parametrize("case", sorted(JENA_FAILURES))
def test_ncr_c4_002_a_jena_failure_is_a_typed_error(case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Named Query Gateway contract :486-491 and LLD v1.1 :346: an unreachable Fuseki is the typed
    PROJECTION_NOT_READY (PO decision NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 5, NCP-U05
    row), any other failure of the answer the typed CONTROL_PLANE_UNAVAILABLE -- never a raw
    transport exception, never an empty answer read as no data."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    route, reason = JENA_FAILURES[case]
    responder = None if route is None else FusekiResponder(route)
    monkeypatch.setattr(jena_adapter, "FUSEKI_URL", "http://127.0.0.1:1" if responder is None else responder.url)
    adapter = _jena(_module("c4_projection_fixture").isolated_ledger(), Clock(T0))
    try:
        for call in (adapter.current_watermark, lambda: adapter.list_authorized(_clearance()),
                     lambda: adapter.publish(R1, _properties(), marking=_marking("SECRET"), commit_id="commit-j1")):
            with pytest.raises(jena_adapter.JenaAdapterError) as caught:
                call()
            assert caught.value.reason_code == reason, case
    finally:
        if responder is not None:
            responder.close()
