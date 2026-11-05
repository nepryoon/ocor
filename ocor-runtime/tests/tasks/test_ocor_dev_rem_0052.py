"""OCOR-DEV-REM-0052 (NCP-U05): C4 projections conform to the closed normative elements.

Unit of NORMATIVE-CONFORMANCE-PLAN (2026-10-30), plan unit NCP-U05, register entries
NCR-C4-001, NCR-C4-002, NCR-C4-003 and NCR-C4-004 (the SHACL validation of NCR-C4-002 follows
the PO decision NCP-U05-FUSEKI-SHACL-SERVICE (2026-11-05), option 1), and NCR-C4-005 and
NCR-C2-013 (PO decision NCP-U05-ITERATION-LIMIT (2026-11-05), option B1).

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

* NCR-C4-005 and NCR-C2-013 -- ADD v1.3 :3406 (projection down: PROJECTION_NOT_READY) and
  :1364 (a Problem with PROJECTION_NOT_READY carries the served branch, commit, watermark and
  staleness), NFR-024 :180, NFR-077 :403: an unreachable object projection answers
  PROJECTION_NOT_READY, and the Gateway builds it with the served context of the confirmed
  watermark, for the TypeDBUnavailableError of the watermark port too; a malformed answer stays
  CONTROL_PLANE_UNAVAILABLE.

Every positive path runs on the real TypeDB and the real PostgreSQL of the stack; the local
HTTP responder stands in for TypeDB only on the failure paths of NCR-C4-003.
"""

from __future__ import annotations

import hashlib
import http.server
import importlib
import json
import os
import tempfile
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
# has its own section below.

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


# -- NCR-C4-002 (Jena: SHACL validation through the Fuseki SHACL service) -------------------------
#
# PO decision NCP-U05-FUSEKI-SHACL-SERVICE (2026-11-05), option 1: the Fuseki of the stack is
# started from the mounted ``deploy/bootstrap/fuseki/config.ttl`` (in-memory service ``ocor`` with
# the endpoints sparql, query, update, data and shacl; image, Dockerfile and service lock
# unchanged), and the Jena adapter validates the shapes of ADD v1.3 §3.6 :2059 with that endpoint
# before a publication becomes visible. ADD v1.3 :357 (BA-04: SHACL validation of the §3.6
# shapes), LLD v1.1 :148 (Jena exposes RDF/JSON-LD and SHACL with conservative marking) and :370
# (oracle BA-04). A refused document is never visible, moves no watermark and leaves no staging
# graph; a SHACL service that cannot answer refuses the publication (fail-closed).

PROV = "urn:ocor:prov:"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD_DATETIME = "http://www.w3.org/2001/XMLSchema#dateTime"
SH = "http://www.w3.org/ns/shacl#"
N = "urn:ocor:node:rem0052-shacl:"


def _n(name: str) -> str:
    return N + name


def _when(value: str) -> tuple[str, str]:
    return (value, XSD_DATETIME)


def _conforming() -> dict[str, dict[str, list[Any]]]:
    """A provenance document that satisfies every shape of ADD v1.3 §3.6 :2059: node -> predicate
    (local name in ``urn:ocor:prov:``) -> values; an IRI value is a ``str`` starting with ``urn:``,
    a typed literal a ``(lexical, datatype)`` pair, any other ``str`` a plain literal."""
    digest = "urn:sha256:" + "d" * 64
    return {
        _n("proposition"): {"type": [PROV + "Proposition"], "subject": [_n("vessel")], "predicate": ["locatedAt"],
                            "value": ["harbour-1"]},
        _n("claim"): {"type": [PROV + "Claim"], "claimProposition": [_n("proposition")],
                      "assertedBy": [_n("source")], "validFrom": [_when("2026-11-05T00:00:00Z")],
                      "systemFrom": [_when("2026-11-05T00:10:00Z")], "markingRef": [digest]},
        _n("source"): {"type": [PROV + "Source"], "sourceIdentity": ["harbour-registry"]},
        _n("acquisition"): {"type": [PROV + "AcquisitionActivity"], "method": ["feed"]},
        _n("evidence"): {"type": [PROV + "Evidence"], "contentDigest": [digest], "source": [_n("source")],
                         "acquisition": [_n("acquisition")], "chainOfCustody": ["custody-1"]},
        _n("support"): {"type": [PROV + "EvidentialSupport"], "stance": ["SUPPORTS"], "assessor": [_n("analyst")],
                        "method": ["manual-review"], "validFrom": [_when("2026-11-05T00:00:00Z")]},
        _n("reliability"): {"type": [PROV + "SourceReliabilityAssessment"], "assessedSource": [_n("source")],
                            "assessor": [_n("analyst")], "reliabilityScale": ["NATO-A-F"],
                            "reliabilityValue": ["B"], "context": ["maritime"]},
        _n("match"): {"type": [PROV + "CandidateMatch"], "scoreSemantics": ["probability"]},
        _n("match-evidence"): {"type": [PROV + "MatchEvidence"], "contentDigest": [digest],
                               "source": [_n("source")], "acquisition": [_n("acquisition")],
                               "chainOfCustody": ["custody-2"], "candidateMatch": [_n("match")],
                               "scoreSemantics": ["probability"], "modelVersion": ["matcher-1.0.0"]},
        _n("merge"): {"type": [PROV + "MergeDecision"], "adjudicator": [_n("adjudicator")],
                      "evidenceSet": [_n("evidence")], "rationale": ["same hull number"],
                      "policyDecision": [_n("policy-decision")], "membershipDelta": [_n("membership")]},
        _n("membership"): {"type": [PROV + "ClusterMembershipAssertion"], "generatedByDecision": [_n("merge")]},
        _n("split"): {"type": [PROV + "SplitDecision"], "adjudicator": [_n("adjudicator")],
                      "evidenceSet": [_n("evidence")], "rationale": ["distinct owners"],
                      "policyDecision": [_n("policy-decision")], "membershipDelta": [_n("membership-2")],
                      "reversesDecision": [_n("merge")]},
        _n("membership-2"): {"type": [PROV + "ClusterMembershipAssertion"], "generatedByDecision": [_n("split")]},
        _n("canonical"): {"type": [PROV + "CanonicalAssertion"], "acceptedFromClaim": [_n("claim")],
                          "acceptedByDecision": [_n("adjudication")]},
    }


def _turtle(document: dict[str, dict[str, list[Any]]]) -> str:
    lines = []
    for node, properties in sorted(document.items()):
        for name, values in sorted(properties.items()):
            predicate = RDF_TYPE if name == "type" else PROV + name
            for value in values:
                if isinstance(value, tuple):
                    rendered = f'"{value[0]}"^^<{value[1]}>'
                elif value.startswith("urn:"):
                    rendered = f"<{value}>"
                else:
                    rendered = json.dumps(value)
                lines.append(f"<{node}> <{predicate}> {rendered} .")
    return "\n".join(lines) + "\n"


def _mutated(node: str, name: str, values: list[Any] | None) -> dict[str, dict[str, list[Any]]]:
    document = _conforming()
    if values is None:
        del document[_n(node)][name]
    else:
        document[_n(node)][name] = values
    return document


# One case per requirement of ADD v1.3 :2059: the document, the focus node and the predicate the
# violation must name (``None`` for a node-level constraint).
SHACL_VIOLATIONS: dict[str, tuple[dict[str, dict[str, list[Any]]], str, str | None]] = {
    "claim-without-proposition": (_mutated("claim", "claimProposition", None), "claim", "claimProposition"),
    "claim-proposition-not-a-proposition": (_mutated("claim", "claimProposition", [_n("source")]), "claim",
                                            "claimProposition"),
    "claim-without-asserter": (_mutated("claim", "assertedBy", None), "claim", "assertedBy"),
    "claim-without-valid-time": (_mutated("claim", "validFrom", None), "claim", "validFrom"),
    "claim-valid-time-not-a-datetime": (_mutated("claim", "validFrom", ["yesterday"]), "claim", "validFrom"),
    "claim-without-system-time": (_mutated("claim", "systemFrom", None), "claim", "systemFrom"),
    "claim-without-marking": (_mutated("claim", "markingRef", None), "claim", "markingRef"),
    "claim-marking-not-a-digest": (_mutated("claim", "markingRef", ["SECRET"]), "claim", "markingRef"),
    "evidence-without-digest": (_mutated("evidence", "contentDigest", None), "evidence", "contentDigest"),
    "evidence-digest-malformed": (_mutated("evidence", "contentDigest", ["md5:00"]), "evidence", "contentDigest"),
    "evidence-without-source": (_mutated("evidence", "source", None), "evidence", "source"),
    "evidence-without-acquisition": (_mutated("evidence", "acquisition", None), "evidence", "acquisition"),
    "evidence-without-custody": (_mutated("evidence", "chainOfCustody", None), "evidence", "chainOfCustody"),
    "support-without-stance": (_mutated("support", "stance", None), "support", "stance"),
    "support-stance-outside-the-enumeration": (_mutated("support", "stance", ["MAYBE"]), "support", "stance"),
    "support-with-two-stances": (_mutated("support", "stance", ["SUPPORTS", "REFUTES"]), "support", "stance"),
    "support-without-assessor": (_mutated("support", "assessor", None), "support", "assessor"),
    "support-without-method": (_mutated("support", "method", None), "support", "method"),
    "support-without-validity": (_mutated("support", "validFrom", None), "support", "validFrom"),
    "reliability-without-source": (_mutated("reliability", "assessedSource", None), "reliability", "assessedSource"),
    "reliability-without-assessor": (_mutated("reliability", "assessor", None), "reliability", "assessor"),
    "reliability-without-scale": (_mutated("reliability", "reliabilityScale", None), "reliability",
                                  "reliabilityScale"),
    "reliability-without-value": (_mutated("reliability", "reliabilityValue", None), "reliability",
                                  "reliabilityValue"),
    "reliability-without-context": (_mutated("reliability", "context", None), "reliability", "context"),
    "match-evidence-without-match": (_mutated("match-evidence", "candidateMatch", None), "match-evidence",
                                     "candidateMatch"),
    "match-evidence-without-score-semantics": (_mutated("match-evidence", "scoreSemantics", None),
                                               "match-evidence", "scoreSemantics"),
    "match-evidence-without-model-version": (_mutated("match-evidence", "modelVersion", None), "match-evidence",
                                             "modelVersion"),
    "match-evidence-without-digest": (_mutated("match-evidence", "contentDigest", None), "match-evidence",
                                      "contentDigest"),
    "merge-without-adjudicator": (_mutated("merge", "adjudicator", None), "merge", "adjudicator"),
    "merge-without-evidence-set": (_mutated("merge", "evidenceSet", None), "merge", "evidenceSet"),
    "merge-without-rationale": (_mutated("merge", "rationale", None), "merge", "rationale"),
    "merge-without-policy-decision": (_mutated("merge", "policyDecision", None), "merge", "policyDecision"),
    "merge-without-membership-delta": (_mutated("merge", "membershipDelta", None), "merge", "membershipDelta"),
    "split-without-adjudicator": (_mutated("split", "adjudicator", None), "split", "adjudicator"),
    "split-without-membership-delta": (_mutated("split", "membershipDelta", None), "split", "membershipDelta"),
    "split-without-reversed-decision": (_mutated("split", "reversesDecision", None), "split", "reversesDecision"),
    "canonical-without-accepted-from-claim": (_mutated("canonical", "acceptedFromClaim", None), "canonical",
                                              "acceptedFromClaim"),
    "canonical-without-acceptance-decision": (_mutated("canonical", "acceptedByDecision", None), "canonical",
                                              "acceptedByDecision"),
    "canonical-that-is-also-the-claim": (_mutated("canonical", "type", [PROV + "CanonicalAssertion",
                                                                       PROV + "Claim"]), "canonical", None),
    "membership-without-decision": (_mutated("membership", "generatedByDecision", None), "membership",
                                    "generatedByDecision"),
    "membership-from-an-unadjudicated-candidate-match": (_mutated("membership", "generatedByDecision",
                                                                  [_n("match")]), "membership",
                                                         "generatedByDecision"),
}


def _staged_graphs() -> int:
    """The named graphs of the dataset: a staged document must never outlive its validation."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    return len(jena_adapter._query("SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }"))


def test_ncr_c4_002_the_stack_fuseki_exposes_the_shacl_service() -> None:
    """PO decision NCP-U05-FUSEKI-SHACL-SERVICE option 1: the ``fuseki`` service of the governed
    Compose mounts ``deploy/bootstrap/fuseki/config.ttl`` read-only and starts from it; image and
    build are unchanged; the configuration declares the in-memory ``ocor`` service with exactly the
    endpoints sparql, query, update, data and shacl; the running Fuseki answers a SHACL validation
    with a real ``sh:ValidationReport``."""
    import yaml
    from rdflib import Graph, Literal, Namespace, URIRef

    root = _module("pathlib").Path(__file__).resolve().parents[3]
    service = yaml.safe_load((root / "deploy/bootstrap/compose.yaml").read_text(encoding="utf-8"))["services"]["fuseki"]
    assert service["image"] == "ocor/jena-fuseki:6.2.0" and service["build"] == {"context": "../../infra/fuseki"}
    assert service["command"] == ["--config=/etc/ocor-fuseki/config.ttl"]
    assert service["volumes"] == ["./fuseki/config.ttl:/etc/ocor-fuseki/config.ttl:ro"]
    assert (root / "infra/fuseki/Dockerfile").read_text(encoding="utf-8").rstrip().endswith('CMD ["--mem", "/ocor"]')

    fuseki = Namespace("http://jena.apache.org/fuseki#")
    config = Graph().parse(root / "deploy/bootstrap/fuseki/config.ttl", format="turtle")
    [service_node] = list(config.subjects(fuseki.name, Literal("ocor")))
    endpoints = {(str(config.value(endpoint, fuseki.name)), str(config.value(endpoint, fuseki.operation)))
                 for endpoint in config.objects(service_node, fuseki.endpoint)}
    assert endpoints == {("sparql", str(fuseki.query)), ("query", str(fuseki.query)),
                         ("update", str(fuseki.update)), ("data", str(fuseki["gsp-rw"])),
                         ("shacl", str(fuseki.shacl))}
    dataset = config.value(service_node, fuseki.dataset)
    assert (dataset, URIRef(RDF_TYPE), URIRef("http://jena.hpl.hp.com/2005/11/Assembler#MemoryDataset")) in config

    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    shape = (f"@prefix sh: <{SH}> . <urn:ocor:shape:probe> a sh:NodeShape ; sh:targetClass <{PROV}Claim> ; "
             f"sh:property [ sh:path <{PROV}claimProposition> ; sh:minCount 1 ] .")
    status, body = jena_adapter._request(
        "POST", f"{jena_adapter.FUSEKI_URL}/{jena_adapter.DATASET}/shacl?graph=default",
        headers={"Content-Type": "text/turtle", "Accept": "text/turtle"}, body=shape.encode("utf-8"))
    assert status == 200, body
    report = Graph().parse(data=body, format="turtle")
    assert (None, URIRef(RDF_TYPE), URIRef(SH + "ValidationReport")) in report


def test_ncr_c4_002_the_shapes_cover_every_requirement_of_section_3_6() -> None:
    """ADD v1.3 :2059: the shapes the adapter sends to the SHACL service target every class the
    requirement names, and the provenance classes the adapter accepts are exactly those of §3.6."""
    from rdflib import Graph, URIRef

    shacl = _module("ocor_runtime.c4.shacl")
    shapes = Graph().parse(data=shacl.SHAPES, format="turtle")
    targets = {str(value) for value in shapes.objects(None, URIRef(SH + "targetClass"))}
    assert targets == {PROV + name for name in (
        "Claim", "Evidence", "MatchEvidence", "EvidentialSupport", "SourceReliabilityAssessment", "MergeDecision",
        "SplitDecision", "CanonicalAssertion", "ClusterMembershipAssertion")}
    assert shacl.PROVENANCE_CLASSES == frozenset(PROV + name for name in (
        "Proposition", "Assertion", "Claim", "CanonicalAssertion", "Evidence", "EvidentialSupport", "Source",
        "SourceReliabilityAssessment", "CandidateMatch", "MatchEvidence", "IdentityResolutionDecision",
        "MergeDecision", "SplitDecision", "ClusterMembershipAssertion", "AcquisitionActivity",
        "TransformationActivity", "AdjudicationActivity"))


@pytest.mark.parametrize("stance", ["SUPPORTS", "REFUTES", "NEUTRAL"])
def test_ncr_c4_002_a_conforming_provenance_document_is_published(jena: Any, ledger: Any, stance: str) -> None:
    """ADD v1.3 :357 and :2059 (positive branch of every shape, each stance of the enumeration): a
    document that conforms is validated by the Fuseki SHACL service and then published with its
    canonical commit, its canonical marking and the watermark in one update, confirmed in the
    ledger; the staging graph is gone and the nodes are exported with their marking join."""
    document = _mutated("support", "stance", [stance])
    marking = _marking("ALPHA", caveats=("CV-ORCON",))
    assert jena.publish_provenance(_turtle(document), marking=marking, commit_id="commit-p1") is True

    assert jena.current_watermark() == "commit-p1"
    assert ledger.latest(jena.store_id, "main").commit_id == "commit-p1"
    assert _staged_graphs() == 0
    nodes = {row["node"]: row for row in jena.provenance_authorized(_clearance("SECRET"))}
    assert set(nodes) == {_n(name) for name in (
        "proposition", "claim", "source", "acquisition", "evidence", "support", "reliability", "match",
        "match-evidence", "merge", "membership", "split", "membership-2", "canonical")}
    assert (nodes[_n("claim")]["commitId"], nodes[_n("claim")]["markingRef"]) == ("commit-p1", _ref(marking))
    assert jena.provenance_authorized(_clearance("UNCLASSIFIED")) == []

    exported = jena.export([_n("claim"), _n("support")], _clearance("SECRET"))
    assert exported.marking == marking and exported.canonical_commit == "commit-p1"
    stances = [node[PROV + "stance"] for node in exported.document if node.get("@id") == _n("support")]
    assert stances == [[{"@value": stance}]]


def test_ncr_c4_002_a_replayed_provenance_commit_writes_nothing(jena: Any, ledger: Any) -> None:
    """Register FR-064 :188 and LLD v1.1 :148: a provenance commit already ordered is a duplicate;
    nothing is staged, validated or written and the watermark does not move."""
    assert jena.publish_provenance(_turtle(_conforming()), marking=_marking("ALPHA"), commit_id="commit-p1") is True
    jena.publish(R1, _properties(), marking=_marking("ALPHA"), commit_id="commit-p2")
    replayed = _mutated("claim", "markingRef", ["urn:sha256:" + "e" * 64])
    assert jena.publish_provenance(_turtle(replayed), marking=_marking("ALPHA"), commit_id="commit-p1") is False
    assert jena.current_watermark() == "commit-p2"
    assert ledger.latest(jena.store_id, "main").commit_id == "commit-p2"
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    stored = jena_adapter._query(f"SELECT ?m WHERE {{ <{_n('claim')}> <{PROV}markingRef> ?m }}")
    assert [row["m"]["value"] for row in stored] == ["urn:sha256:" + "d" * 64]


@pytest.mark.parametrize("case", sorted(SHACL_VIOLATIONS))
def test_ncr_c4_002_a_document_outside_the_shapes_is_refused_by_the_shacl_service(
        jena: Any, ledger: Any, case: str) -> None:
    """ADD v1.3 :2059 (negative branch of every requirement): the SHACL service of Fuseki reports
    the violation; the adapter refuses with SHAPE_VIOLATION naming the focus node and the path,
    nothing of the document becomes visible, the watermark does not move and the staging graph is
    dropped."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    jena.publish(R1, _properties(), marking=_marking("ALPHA"), commit_id="commit-p0")
    document, node, path = SHACL_VIOLATIONS[case]
    with pytest.raises(jena_adapter.JenaAdapterError) as caught:
        jena.publish_provenance(_turtle(document), marking=_marking("ALPHA"), commit_id="commit-p1")
    assert caught.value.reason_code == "SHAPE_VIOLATION", case
    focus = {(violation.focus_node, violation.path) for violation in caught.value.violations}
    assert (_n(node), None if path is None else PROV + path) in focus, caught.value.violations
    assert jena.provenance_authorized(_clearance("TOP_SECRET")) == []
    assert jena.current_watermark() == "commit-p0"
    assert ledger.latest(jena.store_id, "main").commit_id == "commit-p0"
    assert jena.position("main", "commit-p1") is None
    assert _staged_graphs() == 0


LOCAL_REFUSALS: dict[str, tuple[str, dict[str, Any], str]] = {
    "not-turtle": ("<urn:a> <urn:b> .", {}, "SHAPE_VIOLATION"),
    "empty": ("", {}, "SHAPE_VIOLATION"),
    "no-provenance-node": (f"<{_n('x')}> <{PROV}label> \"x\" .\n", {}, "SHAPE_VIOLATION"),
    "unknown-provenance-class": (f"<{_n('x')}> <{RDF_TYPE}> <{PROV}Rumour> .\n", {}, "SHAPE_VIOLATION"),
    "blank-provenance-node": (f"_:x <{RDF_TYPE}> <{PROV}Source> .\n", {}, "SHAPE_VIOLATION"),
    "adapter-predicate": (_turtle(_conforming()) + f"<{_n('claim')}> <urn:ocor:vocab:commitId> \"forged\" .\n", {},
                          "UNAUTHORIZED_PREDICATE"),
    "sparql-breaking-iri": (f"<urn:ocor:node:a\\u003Ex> <{RDF_TYPE}> <{PROV}Source> .\n", {}, "SHAPE_VIOLATION"),
    "not-a-string": (b"bytes", {}, "SHAPE_VIOLATION"),
    "unresolvable-marking": (_turtle(_conforming()), {"marking": "forged"}, "MARKING_UNRESOLVED"),
    "malformed-commit": (_turtle(_conforming()), {"commit_id": ""}, "SHAPE_VIOLATION"),
}


@pytest.mark.parametrize("case", sorted(LOCAL_REFUSALS))
def test_ncr_c4_002_a_malformed_provenance_publication_is_refused_before_any_write(
        jena: Any, ledger: Any, case: str) -> None:
    """LLD v1.1 :148 and ADD v1.3 §3.0.2 :401: a document that is not RDF, names no §3.6 node, an
    unknown provenance class, a node that cannot be addressed, a predicate reserved to the adapter,
    or comes with an unresolvable marking or commit is refused before anything is staged."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    document, changes, reason = LOCAL_REFUSALS[case]
    arguments: dict[str, Any] = {"marking": _marking("ALPHA"), "commit_id": "commit-p1"}
    arguments.update({key: (_forged_digest(_marking("ALPHA")) if value == "forged" else value)
                      for key, value in changes.items()})
    with pytest.raises(jena_adapter.JenaAdapterError) as caught:
        jena.publish_provenance(document, **arguments)
    assert caught.value.reason_code == reason, case
    assert jena.current_watermark() is None and ledger.latest(jena.store_id, "main") is None
    assert _staged_graphs() == 0


def test_ncr_c4_002_an_unavailable_shacl_service_refuses_the_publication(
        jena: Any, ledger: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-closed (LLD v1.1 :346): when the SHACL service of the real Fuseki does not answer with
    a report (here an endpoint the dataset does not declare), nothing is published, the staging
    graph is dropped and the error is the typed CONTROL_PLANE_UNAVAILABLE."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    monkeypatch.setattr(jena_adapter, "SHACL_SERVICE", "absent-shacl")
    with pytest.raises(jena_adapter.JenaAdapterError) as caught:
        jena.publish_provenance(_turtle(_conforming()), marking=_marking("ALPHA"), commit_id="commit-p1")
    assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"
    assert jena.current_watermark() is None and ledger.latest(jena.store_id, "main") is None
    assert jena.provenance_authorized(_clearance("TOP_SECRET")) == []
    assert _staged_graphs() == 0


MALFORMED_REPORTS: dict[str, str] = {
    "not-turtle": "<html/>",
    "no-report": f"<urn:x> <{RDF_TYPE}> <urn:y> .",
    "no-conforms": f"[] <{RDF_TYPE}> <{SH}ValidationReport> .",
    "two-conforms": f"[] <{RDF_TYPE}> <{SH}ValidationReport> ; <{SH}conforms> true, false .",
    "conforms-not-boolean": f"[] <{RDF_TYPE}> <{SH}ValidationReport> ; <{SH}conforms> \"yes\" .",
    "two-reports": (f"[] <{RDF_TYPE}> <{SH}ValidationReport> ; <{SH}conforms> true . "
                    f"[] <{RDF_TYPE}> <{SH}ValidationReport> ; <{SH}conforms> true ."),
    "violation-without-result": f"[] <{RDF_TYPE}> <{SH}ValidationReport> ; <{SH}conforms> false .",
    "conforming-with-a-violation": (
        f"[] <{RDF_TYPE}> <{SH}ValidationReport> ; <{SH}conforms> true ; <{SH}result> [ <{RDF_TYPE}> "
        f"<{SH}ValidationResult> ; <{SH}focusNode> <urn:x> ; <{SH}resultSeverity> <{SH}Violation> ] ."),
}


@pytest.mark.parametrize("case", sorted(MALFORMED_REPORTS))
def test_ncr_c4_002_a_malformed_validation_report_is_never_read_as_conforming(case: str) -> None:
    """Fail-closed: a validation answer that is not exactly one well-formed ``sh:ValidationReport``
    with one boolean ``sh:conforms`` consistent with its results is CONTROL_PLANE_UNAVAILABLE --
    never a conforming document. (Local failure handling of the report reader only.)"""
    shacl = _module("ocor_runtime.c4.shacl")
    with pytest.raises(_module("ocor_runtime.c4.jena_adapter").JenaAdapterError) as caught:
        shacl.read_report(MALFORMED_REPORTS[case])
    assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"


def test_ncr_c4_002_a_well_formed_validation_report_is_read() -> None:
    """The positive branches of the report reader: a conforming report has no violation; a
    non-conforming one lists each result with its focus node, path and constraint component."""
    shacl = _module("ocor_runtime.c4.shacl")
    assert shacl.read_report(f"[] <{RDF_TYPE}> <{SH}ValidationReport> ; <{SH}conforms> true .") == ()
    [violation] = shacl.read_report(
        f"[] <{RDF_TYPE}> <{SH}ValidationReport> ; <{SH}conforms> false ; <{SH}result> [ <{RDF_TYPE}> "
        f"<{SH}ValidationResult> ; <{SH}focusNode> <urn:x> ; <{SH}resultPath> <urn:p> ; <{SH}resultSeverity> "
        f"<{SH}Violation> ; <{SH}sourceConstraintComponent> <{SH}MinCountConstraintComponent> ] .")
    assert (violation.focus_node, violation.path, violation.component) == (
        "urn:x", "urn:p", SH + "MinCountConstraintComponent")


def test_ncr_c4_002_an_unreachable_fuseki_refuses_a_provenance_publication(
        ledger: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Named Query Gateway contract :486-491 and LLD v1.1 :346: an unreachable Fuseki is the typed
    PROJECTION_NOT_READY for a provenance publication too, never a raw transport exception."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    monkeypatch.setattr(jena_adapter, "FUSEKI_URL", "http://127.0.0.1:1")
    adapter = _jena(_module("c4_projection_fixture").isolated_ledger(), clock)
    with pytest.raises(jena_adapter.JenaAdapterError) as caught:
        adapter.publish_provenance(_turtle(_conforming()), marking=_marking("ALPHA"), commit_id="commit-p1")
    assert caught.value.reason_code == "PROJECTION_NOT_READY"


# --------------------------------------------------------------------------- #
# NCR-C4-005 and NCR-C2-013 -- projection down is PROJECTION_NOT_READY with the served context
# (PO decision NCP-U05-ITERATION-LIMIT (2026-11-05), option B1)
# --------------------------------------------------------------------------- #
UNREACHABLE_TYPEDB = "http://127.0.0.1:1"
GATEWAY_OPERATIONS = ("GetObject", "QueryObjectSet", "Search", "Traverse", "Explain", "GetProvenance")


def _rem_0049() -> Any:
    """The C2 gateway composition of OCOR-DEV-REM-0049 (real TypeDB, Fuseki and PostgreSQL audit)."""
    return importlib.import_module("test_ocor_dev_rem_0049")


def _operation_bodies(rem: Any) -> dict[str, dict[str, Any]]:
    ref = {"resource_type_id": "urn:ocor:type:vessel", "resource_id": rem.V1}
    return {
        "GetObject": rem.get_object_body(),
        "QueryObjectSet": {"context": rem.wire_context(), "object_set_contract": rem.contract_call(), "page_size": 10},
        "Search": {"context": rem.wire_context(), "search_contract": rem.contract_call(), "text": "alpha",
                   "page_size": 10},
        "Traverse": {"context": rem.wire_context(), "start": [ref], "traversal_contract": rem.contract_call()},
        "Explain": {"context": rem.wire_context(), "target": ref, "explanation_contract": rem.contract_call()},
        "GetProvenance": {"context": rem.wire_context(), "target": ref, "direction": "UPSTREAM", "max_depth": 3},
    }


@pytest.fixture
def gateway_backends() -> Iterator[tuple[Any, Any, Any]]:
    """The real TypeDB projection on the shared ledger, the real Fuseki marking join and a
    signed PostgreSQL audit log in a schema of its own, as composed by OCOR-DEV-REM-0049."""
    rem = _rem_0049()
    fixture = _module("c4_projection_fixture")
    typedb = fixture.projection()
    typedb.initialize()
    typedb.reset()
    jena = fixture.ClassificationJena()
    jena.reset()
    audit = _module("ocor_runtime.audit")
    signing = _module("ocor_runtime.c1.signing")
    with tempfile.TemporaryDirectory() as workdir:
        keys = rem.AuditKeys(Path(workdir))
        log = audit.PostgresAuditLog(
            os.environ.get("OCOR_LIVE_POSTGRES_DSN") or rem._dsn(), schema=f"ocor_audit_rem0052_{os.urandom(6).hex()}",
            signer=audit.AuditSigner(key=signing.Ed25519SigningKey.from_seed(keys.seed),
                                     keyid="urn:ocor:key:c2-audit-test"))
        log.initialize()
        try:
            yield typedb, jena, log
        finally:
            log.drop()


class _DownObjects:
    """The real ``TypeDBObjectProjection`` read while TypeDB is unreachable for the object
    projection only: the watermark port of the gateway still reaches TypeDB."""

    def __init__(self, real: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        self._real = real
        self._monkeypatch = monkeypatch

    def _down(self, read: Any) -> Any:
        with self._monkeypatch.context() as patch:
            patch.setattr("ocor_runtime.c4.typedb_adapter.TYPEDB_URL", UNREACHABLE_TYPEDB)
            return read()

    def get(self, resource_ids: tuple[str, ...]) -> Any:
        return self._down(lambda: self._real.get(resource_ids))

    def page(self, *, limit: int, after: str | None) -> Any:
        return self._down(lambda: self._real.page(limit=limit, after=after))

    def search(self, text: str, *, limit: int, after: str | None) -> Any:
        return self._down(lambda: self._real.search(text, limit=limit, after=after))


def _assert_not_ready(reply: Any, operation: str, commit: str) -> None:
    assert (reply.status, reply.body["reason_code"]) == (503, "PROJECTION_NOT_READY"), (operation, reply.body)
    served = reply.body["served"]
    assert (served["branch"], served["served_commit"], served["watermark"]) == ("main", commit, commit), operation
    assert isinstance(served["staleness_ms"], int) and served["staleness_ms"] >= 0, operation
    assert "object" not in reply.body and "objects" not in reply.body, operation


def test_ncr_c4_005_conforms(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADD v1.3 :3406 (projection down: PROJECTION_NOT_READY) and :1364 (the Problem carries the
    served context, built by the Gateway): an unreachable TypeDB is PROJECTION_NOT_READY on each
    read shape of the object projection, never CONTROL_PLANE_UNAVAILABLE."""
    monkeypatch.setattr("ocor_runtime.c4.typedb_adapter.TYPEDB_URL", UNREACHABLE_TYPEDB)
    projection = _module("ocor_runtime.c4.object_projection").TypeDBObjectProjection()
    for read in (lambda: projection.get(("urn:ocor:vessel:1",)), lambda: projection.page(limit=2, after=None),
                 lambda: projection.search("alpha", limit=2, after=None)):
        with pytest.raises(C2Error) as caught:
            read()
        assert caught.value.reason_code == "PROJECTION_NOT_READY"


OBJECT_ANSWER_FAILURES: dict[str, dict[str, tuple[int, bytes] | bytes]] = {
    "query-refused": {"query": (500, b"{}")},
    "query-not-json": {"query": (200, b"{not json")},
    "query-connection-dropped": {"query": b""},
    "query-bad-status-line": {"query": b"GARBAGE\r\n\r\n"},
}


@pytest.mark.parametrize("case", sorted(OBJECT_ANSWER_FAILURES))
def test_ncr_c4_005_a_malformed_object_answer_stays_control_plane_unavailable(
        responder: TypeDBResponder, case: str) -> None:
    """The negative branch: only an unreachable TypeDB is the projection down; a refused, malformed
    or dropped answer stays the typed CONTROL_PLANE_UNAVAILABLE (ADD v1.3 :174)."""
    responder.routes = dict(OBJECT_ANSWER_FAILURES[case])
    projection = _module("ocor_runtime.c4.object_projection").TypeDBObjectProjection()
    with pytest.raises(C2Error) as caught:
        projection.get(("urn:ocor:vessel:1",))
    assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"


def test_ncr_c2_013_conforms(gateway_backends: tuple[Any, Any, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """ADD v1.3 :1364 and :3406, NFR-024 (Register :180), NFR-077 (Register :403): with TypeDB
    unreachable the watermark port raises the typed TypeDBUnavailableError with the watermark C4
    confirmed durably; each of the six operations answers PROJECTION_NOT_READY with the served
    branch, commit, watermark and staleness of that confirmed watermark, and the denial is audited
    with that reason code."""
    rem = _rem_0049()
    typedb, jena, log = gateway_backends
    fixture = rem.Gateway(typedb, jena, log)
    rem.load_fleet(fixture, typedb)
    bodies = _operation_bodies(rem)
    assert set(bodies) == set(GATEWAY_OPERATIONS)
    monkeypatch.setattr("ocor_runtime.c4.typedb_adapter.TYPEDB_URL", UNREACHABLE_TYPEDB)
    for operation, body in bodies.items():
        _assert_not_ready(fixture.invoke(operation, body), operation, "commit-2")
    records = log.records()
    assert [record.record["reason_code"] for record in records] == ["PROJECTION_NOT_READY"] * len(bodies)


def test_ncr_c2_013_an_unreachable_object_projection_serves_the_confirmed_watermark(
        gateway_backends: tuple[Any, Any, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The object projection down while the watermark port answers: the Gateway builds
    PROJECTION_NOT_READY with the served context of the confirmed watermark (ADD v1.3 :1364)."""
    rem = _rem_0049()
    typedb, jena, log = gateway_backends
    real = _module("ocor_runtime.c4.object_projection").TypeDBObjectProjection()
    fixture = rem.Gateway(typedb, jena, log, objects=_DownObjects(real, monkeypatch))
    rem.load_fleet(fixture, typedb)
    for operation, body in _operation_bodies(rem).items():
        _assert_not_ready(fixture.invoke(operation, body), operation, "commit-2")


def test_ncr_c2_013_without_a_confirmed_watermark_the_served_commit_is_the_sentinel(
        gateway_backends: tuple[Any, Any, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """A ledger that has confirmed nothing: PROJECTION_NOT_READY still carries a served context,
    with the no-watermark sentinel and the active release, never a fabricated commit."""
    rem = _rem_0049()
    _, jena, log = gateway_backends
    empty = _module("c4_projection_fixture").isolated_projection()
    empty.reset()
    fixture = rem.Gateway(empty, jena, log)
    monkeypatch.setattr("ocor_runtime.c4.typedb_adapter.TYPEDB_URL", UNREACHABLE_TYPEDB)
    reply = fixture.invoke("GetObject", rem.get_object_body())
    _assert_not_ready(reply, "GetObject", "urn:ocor:commit:none")
    assert reply.body["served"]["ontology_release"] == rem.wire("b")


def test_ncr_c2_013_any_other_port_failure_stays_control_plane_unavailable(
        gateway_backends: tuple[Any, Any, Any]) -> None:
    """The negative branch: a port failure that is not the projection down stays the typed
    fail-closed CONTROL_PLANE_UNAVAILABLE, without a served context (ADD v1.3 :174)."""
    rem = _rem_0049()
    typedb, jena, log = gateway_backends

    class Broken:
        def get(self, resource_ids: tuple[str, ...]) -> Any:
            raise RuntimeError("the object port failed outside its contract")

    fixture = rem.Gateway(typedb, jena, log, objects=Broken())
    rem.load_fleet(fixture, typedb)
    reply = fixture.invoke("GetObject", rem.get_object_body())
    assert (reply.status, reply.body["reason_code"]) == (503, "CONTROL_PLANE_UNAVAILABLE")
    assert "served" not in reply.body


# --------------------------------------------------------------------------- #
# Input robustness of the adapters touched by the unit (PO decision NCP-THROUGHPUT-RULES
# (2026-11-05) point 1, the five points of PRE-REVIEW-INPUT-ROBUSTNESS (2026-10-29), the
# boundary bindings and the closure of every resource on every error path). Every answer or
# stored datum read from outside the process is checked for type and shape without conversion,
# every failure leaves the adapter as its typed error, never as a raw exception, and a tampered
# datum is refused. The local responders stand in for a backend on the failure paths only.
# --------------------------------------------------------------------------- #
DEEP_JSON = b"[" * 100_000
UNREACHABLE_POSTGRES = "postgresql://ocor@127.0.0.1:1/ocor"


@pytest.mark.parametrize("endpoint", ["signin", "open", "query"])
def test_ncr_c4_003_a_deeply_nested_answer_is_the_typed_error(responder: TypeDBResponder, endpoint: str) -> None:
    """Named Query Gateway contract :486-491: an answer nested beyond what the decoder can read
    is a malformed answer -- the typed CONTROL_PLANE_UNAVAILABLE of the read and the adapter's
    typed error of a write -- never a raw RecursionError."""
    adapter_module = _module("ocor_runtime.c4.typedb_adapter")
    responder.routes = {endpoint: (200, DEEP_JSON)}
    with pytest.raises(C2Error) as caught:
        adapter_module.read_rows("match $w isa c4-watermark, has c4-commit-id $c;", ("c",))
    assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"
    if endpoint != "query":
        with pytest.raises(adapter_module.TypeDBAdapterError):
            adapter_module._write("match $f isa c4-fact; delete $f;")


def test_ncr_c4_003_a_deeply_nested_database_listing_is_the_typed_error(responder: TypeDBResponder) -> None:
    adapter_module = _module("ocor_runtime.c4.typedb_adapter")
    responder.routes = {"databases": (200, DEEP_JSON)}
    with pytest.raises(adapter_module.TypeDBAdapterError):
        adapter_module.sandbox_database_names()


def test_ncr_c4_003_typedb_unreachable_at_the_write_is_projection_not_ready(
        adapter: Any, ledger: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """ADD v1.3 :3406 and the PO decision NORMATIVE-CONFORMANCE-PLAN point 5 (NCP-U05 row): TypeDB
    lost between the reads of ``apply_commit`` and its write transaction is the typed
    TypeDBUnavailableError carrying the last confirmed watermark, never a raw URLError; the
    ledger confirms nothing."""
    import urllib.error

    adapter_module = _module("ocor_runtime.c4.typedb_adapter")
    assert adapter.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="p1") is True

    def unreachable(*queries: str, database: str | None = None) -> None:
        raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))

    monkeypatch.setattr(adapter_module, "_write", unreachable)
    with pytest.raises(adapter_module.TypeDBUnavailableError) as caught:
        adapter.apply_commit(fact_id="fact-1", commit_id="commit-2", payload="p2")
    assert caught.value.reason_code == "PROJECTION_NOT_READY"
    assert caught.value.confirmed is not None and caught.value.confirmed.commit_id == "commit-1"
    assert ledger.latest(adapter.store_id, "main").commit_id == "commit-1"


def test_ncr_c4_003_typedb_unreachable_at_initialize_and_reset_is_projection_not_ready(
        ledger: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter_module = _module("ocor_runtime.c4.typedb_adapter")
    monkeypatch.setattr(adapter_module, "TYPEDB_URL", UNREACHABLE_TYPEDB)
    adapter = _adapter(ledger, clock)
    for call in (adapter.initialize, adapter.reset):
        with pytest.raises(adapter_module.TypeDBUnavailableError) as caught:
            call()
        assert caught.value.reason_code == "PROJECTION_NOT_READY"


def _ledger_row(ledger: Any, table: str, row: dict[str, Any]) -> None:
    """An out-of-band write to the ledger schema of the module, outside the adapter."""
    import psycopg
    from psycopg import sql

    columns = sql.SQL(", ").join(sql.Identifier(name) for name in row)
    values = sql.SQL(", ").join(sql.Placeholder() for _ in row)
    with psycopg.connect(os.environ["OCOR_LIVE_POSTGRES_DSN"]) as connection:
        connection.execute(sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
            sql.Identifier(ledger._schema), sql.Identifier(table), columns, values), tuple(row.values()))


@pytest.mark.parametrize("release", ["x", "sha256:" + "b" * 64, "urn:sha256:" + "B" * 64])
def test_ncr_c4_001_a_stored_watermark_of_a_malformed_release_fails_closed(ledger: Any, release: str) -> None:
    """FR-148 (Register :331): the release a stored confirmation declares is a SHA-256 URN; a
    tampered one is the typed CONTROL_PLANE_UNAVAILABLE of the ledger, never served."""
    store = f"urn:ocor:projection-store:typedb:rem0052-tamper-{os.urandom(4).hex()}"
    _ledger_row(ledger, "c4_watermark_confirmed", {
        "store_id": store, "branch": "main", "commit_id": "commit-1", "sequence": 1, "release_digest": release,
        "confirmed_at": T0})
    watermark = _module("ocor_runtime.c4.watermark")
    try:
        with pytest.raises(watermark.WatermarkLedgerError) as caught:
            ledger.latest(store, "main")
        assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"
    finally:
        ledger.clear(store)


@pytest.mark.parametrize("column", ["expected_digest", "served_digest"])
def test_ncr_c4_002_a_stored_quarantine_of_a_malformed_digest_fails_closed(ledger: Any, column: str) -> None:
    store = f"urn:ocor:projection-store:typedb:rem0052-tamper-{os.urandom(4).hex()}"
    row = {"store_id": store, "aggregate_ref": DRIFT_REF, "canonical_commit": "commit-1", "expected_digest": DIGEST_A,
           "served_digest": DIGEST_C, "quarantined_at": T0}
    row[column] = "not-a-digest"
    _ledger_row(ledger, "c4_quarantine", row)
    watermark = _module("ocor_runtime.c4.watermark")
    try:
        with pytest.raises(watermark.WatermarkLedgerError) as caught:
            ledger.active(store, DRIFT_REF)
        assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"
    finally:
        ledger.clear_quarantine(store)


def test_ncr_c4_001_an_unreachable_ledger_is_the_typed_error() -> None:
    watermark = _module("ocor_runtime.c4.watermark")
    down = _module("ocor_runtime.c4.adapters.postgres").PostgresWatermarkLedger(UNREACHABLE_POSTGRES,
                                                                              schema="ocor_c4_rem0052")
    for call in (lambda: down.latest("urn:ocor:projection-store:typedb:x", "main"),
                 lambda: down.active("urn:ocor:projection-store:typedb:x", DRIFT_REF),
                 lambda: down.latest_checkpoint("urn:ocor:projection-store:typedb:x")):
        with pytest.raises(watermark.WatermarkLedgerError) as caught:
            call()
        assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"
        assert "127.0.0.1" not in str(caught.value)


def _object_row(**changes: Any) -> dict[str, Any]:
    document = {"values": {"name": "alpha"}, "link_ids": [], "provenance_ids": [], "text": "alpha",
                "valid_from": "2026-11-04T12:00:00Z", "system_from": "2026-11-04T12:00:00Z"}
    row = {"i": "urn:ocor:vessel:1", "t": "urn:ocor:type:vessel", "c": "commit-1", "m": DIGEST_A,
           "d": json.dumps(document, sort_keys=True)}
    row.update(changes)
    return {"data": {name: {"value": value} for name, value in row.items()}}


def _object_answer(*rows: dict[str, Any]) -> tuple[int, bytes]:
    return 200, json.dumps({"answers": list(rows)}).encode("utf-8")


MALFORMED_OBJECT_DOCUMENTS: dict[str, str] = {
    "value-nan": ('{"link_ids":[],"provenance_ids":[],"system_from":"2026-11-04T12:00:00Z","text":"",'
                  '"valid_from":"2026-11-04T12:00:00Z","values":{"x":NaN}}'),
    "value-infinity": ('{"link_ids":[],"provenance_ids":[],"system_from":"2026-11-04T12:00:00Z","text":"",'
                       '"valid_from":"2026-11-04T12:00:00Z","values":{"x":Infinity}}'),
    "duplicate-key": ('{"link_ids":[],"provenance_ids":[],"system_from":"2026-11-04T12:00:00Z","text":"a",'
                      '"text":"b","valid_from":"2026-11-04T12:00:00Z","values":{}}'),
    "deeply-nested": "[" * 100_000,
}


@pytest.mark.parametrize("case", sorted(MALFORMED_OBJECT_DOCUMENTS))
def test_ncr_c4_005_a_stored_document_that_is_not_i_json_is_refused(responder: TypeDBResponder, case: str) -> None:
    """A stored snapshot document is I-JSON (RFC 7493: no duplicate key, no non-finite number) of
    bounded depth; anything else is the typed CONTROL_PLANE_UNAVAILABLE of the whole read
    (ADD v1.3 :174), never a coerced object nor a raw exception."""
    responder.routes = {"query": _object_answer(_object_row(d=MALFORMED_OBJECT_DOCUMENTS[case]))}
    projection = _module("ocor_runtime.c4.object_projection").TypeDBObjectProjection()
    for read in (lambda: projection.get(("urn:ocor:vessel:1",)), lambda: projection.page(limit=2, after=None)):
        with pytest.raises(C2Error) as caught:
            read()
        assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE", case


def test_ncr_c4_005_a_well_formed_object_answer_is_read(responder: TypeDBResponder) -> None:
    """Positive control of the responder rows above: a well-formed row is read as it is stored."""
    responder.routes = {"query": _object_answer(_object_row())}
    projection = _module("ocor_runtime.c4.object_projection").TypeDBObjectProjection()
    [item] = projection.get(("urn:ocor:vessel:1",))
    assert (item.resource_id, item.commit_id, item.values) == ("urn:ocor:vessel:1", "commit-1", {"name": "alpha"})


def test_ncr_c4_005_a_lookup_by_identity_returns_only_the_identity_asked(responder: TypeDBResponder) -> None:
    """An answer row of another identity is never returned for the identity asked."""
    responder.routes = {"query": _object_answer(_object_row(i="urn:ocor:vessel:2"))}
    projection = _module("ocor_runtime.c4.object_projection").TypeDBObjectProjection()
    assert projection.get(("urn:ocor:vessel:1",)) == ()


def test_ncr_c4_005_an_unreachable_typedb_at_projection_is_projection_not_ready(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """ADD v1.3 :3406: the write path of the object projection reads TypeDB through the raw read too,
    so an unreachable TypeDB is PROJECTION_NOT_READY there as well."""
    monkeypatch.setattr("ocor_runtime.c4.typedb_adapter.TYPEDB_URL", UNREACHABLE_TYPEDB)
    projection = _module("ocor_runtime.c4.object_projection").TypeDBObjectProjection()
    marking = _module("ocor_runtime.c4_marking").MarkingSet({"classification": "SECRET"})
    with pytest.raises(C2Error) as caught:
        projection.project(object_id="urn:ocor:vessel:1", resource_type_id="urn:ocor:type:vessel",
                           commit_id="commit-1", marking=marking, values={"name": "alpha"})
    assert caught.value.reason_code == "PROJECTION_NOT_READY"


JENA_ANSWER_FAILURES: dict[str, bytes] = {
    "not-utf-8": b'{"results": {"bindings": [{"c": {"value": "commit-\xff"}}]}}',
    "deeply-nested": DEEP_JSON,
    "value-not-text": b'{"results": {"bindings": [{"c": {"value": 7}}]}}',
}


@pytest.mark.parametrize("case", sorted(JENA_ANSWER_FAILURES))
def test_ncr_c4_002_a_malformed_jena_answer_is_the_typed_error(case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Named Query Gateway contract :486-491: a SPARQL answer that is not strict UTF-8 JSON of
    bounded depth with text values is the typed CONTROL_PLANE_UNAVAILABLE -- never a value
    rewritten with replacement characters, never a raw exception."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    responder = FusekiResponder((200, JENA_ANSWER_FAILURES[case]))
    monkeypatch.setattr(jena_adapter, "FUSEKI_URL", responder.url)
    try:
        adapter = _jena(_module("c4_projection_fixture").isolated_ledger(), Clock(T0))
        with pytest.raises(jena_adapter.JenaAdapterError) as caught:
            adapter.current_watermark()
        assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE", case
    finally:
        responder.close()


@pytest.mark.parametrize("value", ["²", "١", "-1", "1.0", "", "0x1"])
def test_ncr_c4_002_a_malformed_jena_commit_position_is_the_typed_error(
        value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A commit position is ASCII decimal digits as stored: a Unicode digit, a sign, a fraction or
    an empty value is the typed CONTROL_PLANE_UNAVAILABLE, never converted to another position."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    body = json.dumps({"results": {"bindings": [{"s": {"value": value}}]}}).encode("utf-8")
    responder = FusekiResponder((200, body))
    monkeypatch.setattr(jena_adapter, "FUSEKI_URL", responder.url)
    try:
        adapter = _jena(_module("c4_projection_fixture").isolated_ledger(), Clock(T0))
        with pytest.raises(jena_adapter.JenaAdapterError) as caught:
            adapter.position("main", "commit-j1")
        assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"
    finally:
        responder.close()


def test_ncr_c4_002_a_resource_holding_two_markings_is_withheld(jena: Any) -> None:
    """ADD v1.3 §3.0.2 :401: a resource the adapter published with exactly one marking that is
    found holding a second one -- a tampered projection -- is DENY and withheld, never served
    under the less restrictive marking."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    jena.publish(R1, _properties(), marking=_marking("TOP_SECRET"), commit_id="commit-j1")
    lowered = _marking("UNCLASSIFIED")
    stored = json.dumps(lowered, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    _sparql_update(f"{jena_adapter.PREFIX} INSERT DATA {{ <{R1}> ocor:markingRef {jena_adapter._literal(_ref(lowered))} ; "
                   f"ocor:markingObject {jena_adapter._literal(stored)} }}")
    assert jena.list_authorized(_clearance("SECRET")) == []
    assert jena.exists_authorized(R1, _clearance("TOP_SECRET")) is False


def test_ncr_c4_002_a_deeply_nested_stored_marking_is_withheld(jena: Any) -> None:
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    jena.publish(R1, _properties(), marking=_marking("UNCLASSIFIED"), commit_id="commit-j1")
    _sparql_update(f"{jena_adapter.PREFIX} DELETE {{ <{R1}> ocor:markingObject ?m }} INSERT {{ <{R1}> "
                   f"ocor:markingObject {jena_adapter._literal('[' * 100_000)} }} WHERE {{ <{R1}> ocor:markingObject ?m }}")
    assert jena.list_authorized(_clearance("TOP_SECRET")) == []


def test_ncr_c4_002_a_construct_answer_that_is_not_turtle_is_the_typed_error(
        jena: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The RDF answer of a CONSTRUCT is parsed fail-closed: a body that is not Turtle is the typed
    CONTROL_PLANE_UNAVAILABLE of the serialization and of the export, never a raw parser error."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    jena.publish(R1, _properties(), marking=_marking("UNCLASSIFIED"), commit_id="commit-j1")
    monkeypatch.setattr(jena_adapter, "_construct", lambda query: "<urn:x> <urn:y> \"unterminated .")
    for read in (lambda: jena.to_json_ld(R1, _clearance()), lambda: jena.export([R1], _clearance())):
        with pytest.raises(jena_adapter.JenaAdapterError) as caught:
            read()
        assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"


def test_ncr_c4_002_a_failed_staging_cleanup_never_hides_the_refusal(
        jena: Any, ledger: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A document the SHACL service refuses stays refused with SHAPE_VIOLATION and its violations
    even when dropping the staging graph fails afterwards; nothing becomes visible."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    update = jena_adapter._update

    def failing_drop(sparql_update: str) -> None:
        if sparql_update.startswith("DROP SILENT GRAPH"):
            raise jena_adapter.JenaAdapterError("PROJECTION_NOT_READY", "the Jena projection is unreachable")
        update(sparql_update)

    monkeypatch.setattr(jena_adapter, "_update", failing_drop)
    document = _turtle(_mutated("claim", "claimProposition", None))
    with pytest.raises(jena_adapter.JenaAdapterError) as caught:
        jena.publish_provenance(document, marking=_marking("ALPHA"), commit_id="commit-p1")
    assert caught.value.reason_code == "SHAPE_VIOLATION"
    assert caught.value.violations
    assert jena.current_watermark() is None and ledger.latest(jena.store_id, "main") is None


def test_ncr_c4_002_an_export_of_a_store_confirmed_under_another_release_is_release_mismatch(
        jena: Any, ledger: Any, clock: Clock) -> None:
    """FR-148 (Register :331), as for the TypeDB projection: an export names the release of the
    confirmed watermark only when it is the release the adapter declares; a store confirmed under
    another release is RELEASE_MISMATCH, never exported under the stale release."""
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    _jena(ledger, clock, release=OTHER_RELEASE).publish(R1, _properties(), marking=_marking("UNCLASSIFIED"),
                                                         commit_id="commit-j1")
    for read in (jena.watermark, lambda: jena.export([R1], _clearance())):
        with pytest.raises(jena_adapter.JenaAdapterError) as caught:
            read()
        assert caught.value.reason_code == "RELEASE_MISMATCH"


def test_ncr_c4_002_a_validation_result_without_its_severity_is_never_read_as_conforming() -> None:
    """SHACL 1.0 §3.6.2: every validation result has exactly one sh:resultSeverity; a result
    without one is a malformed report (CONTROL_PLANE_UNAVAILABLE), never skipped."""
    shacl = _module("ocor_runtime.c4.shacl")
    for conforms in ("true", "false"):
        report = (f"[] <{RDF_TYPE}> <{SH}ValidationReport> ; <{SH}conforms> {conforms} ; <{SH}result> [ <{RDF_TYPE}> "
                  f"<{SH}ValidationResult> ; <{SH}focusNode> <urn:x> ] .")
        with pytest.raises(_module("ocor_runtime.c4.jena_adapter").JenaAdapterError) as caught:
            shacl.read_report(report)
        assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"


def test_ncr_c4_002_a_marking_that_cannot_be_canonicalized_is_unresolved(jena: Any) -> None:
    """ADD v1.3 §3.0.2 :401: a marking whose members cannot be canonicalized (a lone surrogate) is
    unresolved: MARKING_UNRESOLVED at the scheme and at every adapter entry, never a raw error."""
    marking_module = _module("ocor_runtime.c4.marking")
    jena_adapter = _module("ocor_runtime.c4.jena_adapter")
    value = {"scheme_id": SCHEME_ID, "labels": ["ALPHA", "\ud800"], "mandatory_markings": [], "caveats": ["\ud800"],
             "dissemination_controls": [], "permitted_purposes": ["logistics"], "handling_instructions": [],
             "marking_digest": "sha256:" + "0" * 64}
    with pytest.raises(marking_module.MarkingUnresolved):
        _scheme().evaluate(value)
    for call in (lambda: jena.publish(R1, _properties(), marking=value, commit_id="commit-j1"),
                 lambda: jena.list_authorized(value)):
        with pytest.raises(jena_adapter.JenaAdapterError) as caught:
            call()
        assert caught.value.reason_code == "MARKING_UNRESOLVED"


@pytest.mark.parametrize("definition", [[], "scheme", None, 7])
def test_ncr_c4_002_a_scheme_definition_that_is_not_an_object_is_refused(definition: Any) -> None:
    marking_module = _module("ocor_runtime.c4.marking")
    with pytest.raises(marking_module.MarkingSchemeError):
        marking_module.CanonicalMarkingScheme(definition)


def _checkpoint_mapping(**changes: Any) -> dict[str, Any]:
    drift = _module("ocor_runtime.c4.drift")
    entry = drift.CheckpointEntry(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=DRIFT_REF,
                                  commit_id="commit-1", sequence=1, payload="p1")
    body = drift.CheckpointBody(store_id="urn:ocor:projection-store:typedb:ocor_default", branch="main",
                                release_digest=RELEASE, watermark="commit-1", sequence=1,
                                created_at="2026-11-04T12:00:00Z", entries=(entry,)).to_mapping()
    body.update(changes)
    return body


def _signed(payload: bytes) -> Any:
    drift = _module("ocor_runtime.c4.drift")
    dsse = _module("ocor_runtime.c4.drift").dsse_pae
    key = _signing_key()
    return drift.SignedProjectionCheckpoint(payload=payload, key_id=CHECKPOINT_KEY_ID,
                                            signature=key.sign(dsse(drift.CHECKPOINT_PAYLOAD_TYPE, payload)))


def _canonical_payload(**changes: Any) -> bytes:
    return bytes(_module("ocor_runtime.kernel.canonical").canonical_bytes(_checkpoint_mapping(**changes)))


SIGNED_MALFORMED_CHECKPOINTS: dict[str, Any] = {
    "non-finite-number": lambda: _canonical_payload().replace(b'"sequence":1,"store_id"', b'"sequence":NaN,"store_id"'),
    "deeply-nested": lambda: DEEP_JSON,
    "not-utf-8": lambda: b'{"branch":"\xff"}',
    "created-at-not-a-timestamp": lambda: _canonical_payload(created_at="yesterday"),
    "created-at-with-an-offset": lambda: _canonical_payload(created_at="2026-11-04T12:00:00+01:00"),
    "sequence-bool": lambda: _canonical_payload(sequence=True),
    "release-not-a-digest": lambda: _canonical_payload(release_digest="x"),
    "no-entries": lambda: _canonical_payload(entries=[]),
    "watermark-not-the-last-entry": lambda: _canonical_payload(watermark="commit-0"),
}


@pytest.mark.parametrize("case", sorted(SIGNED_MALFORMED_CHECKPOINTS))
def test_ncr_c4_002_a_signed_but_malformed_checkpoint_is_refused(case: str) -> None:
    """LLD v1.1 :148: a checkpoint is trusted only as a canonical, well-formed body under a trusted
    signature; a body that is signed but malformed -- a non-finite number, a depth the decoder
    cannot read, non UTF-8, an instant that is not RFC 3339 UTC, a bool sequence, a release that is
    not a SHA-256 URN, no entries, a watermark that is not the last entry -- is CheckpointError,
    never a raw exception."""
    drift = _module("ocor_runtime.c4.drift")
    with pytest.raises(drift.CheckpointError):
        drift.verify_checkpoint(_signed(SIGNED_MALFORMED_CHECKPOINTS[case]()),
                                {CHECKPOINT_KEY_ID: _signing_key().public_key})


def test_ncr_c4_002_a_signed_well_formed_checkpoint_is_read() -> None:
    """Positive control of the signed bodies above."""
    drift = _module("ocor_runtime.c4.drift")
    body = drift.verify_checkpoint(_signed(_canonical_payload()), {CHECKPOINT_KEY_ID: _signing_key().public_key})
    assert (body.watermark, body.sequence, body.created_at) == ("commit-1", 1, "2026-11-04T12:00:00Z")


def test_ncr_c4_002_an_unreachable_canonical_store_is_canonical_unavailable(adapter: Any) -> None:
    """FR-065 (Register :189): the rebuild source cannot be read -- TerminusDB unreachable -- is the
    typed DriftError CANONICAL_UNAVAILABLE of every operation, never a raw adapter error."""
    terminus = _terminus()
    down = _module("ocor_runtime.c3.terminusdb_service").TerminusDBC3Service(
        url="http://127.0.0.1:1", password="unused", database="ocor_c3_rem0052_absent",
        admission=terminus.GOVERNED.admission(), timeout=2.0)
    detector = _detector(down, adapter)
    rebuild = _module("ocor_runtime.c4.rebuild")
    with pytest.raises(rebuild.DriftError) as caught:
        detector.rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=DRIFT_REF)
    assert caught.value.reason_code == "CANONICAL_UNAVAILABLE"
    assert "127.0.0.1" not in str(caught.value)


def test_ncr_c4_002_a_ledger_lost_during_a_rebuild_is_the_typed_error(
        canonical: Any, adapter: Any, ledger: Any, clock: Clock) -> None:
    """A failure of the durable ledger while the rebuild writes is the typed DriftError
    CONTROL_PLANE_UNAVAILABLE, as for every other ledger operation of the detector."""
    rebuild = _module("ocor_runtime.c4.rebuild")
    _commit(canonical, DRIFT_REF, 0, "ACTIVE")
    down = _module("ocor_runtime.c4.adapters.postgres").PostgresWatermarkLedger(UNREACHABLE_POSTGRES,
                                                                              schema="ocor_c4_rem0052")
    lost = _module("ocor_runtime.c4.typedb_adapter").TypeDBProjectionAdapter(
        release_digest=RELEASE, ledger=down, quarantine=ledger, clock=clock)
    with pytest.raises(rebuild.DriftError) as caught:
        _detector(canonical, lost).rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=DRIFT_REF)
    assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"


def test_ncr_c4_002_a_ledger_lost_during_a_checkpoint_rebuild_is_the_typed_error(
        canonical: Any, adapter: Any, ledger: Any, clock: Clock) -> None:
    rebuild = _module("ocor_runtime.c4.rebuild")
    _commit(canonical, DRIFT_REF, 0, "ACTIVE")
    detector = _detector(canonical, adapter)
    detector.rebuild(tenant_id=TENANT, aggregate_type=AGGREGATE_TYPE, aggregate_ref=DRIFT_REF)
    signed = detector.checkpoint(aggregates=[_aggregate(DRIFT_REF)])
    down = _module("ocor_runtime.c4.adapters.postgres").PostgresWatermarkLedger(UNREACHABLE_POSTGRES,
                                                                              schema="ocor_c4_rem0052")
    lost = _module("ocor_runtime.c4.typedb_adapter").TypeDBProjectionAdapter(
        release_digest=RELEASE, ledger=down, quarantine=ledger, clock=clock)
    with pytest.raises(rebuild.DriftError) as caught:
        _detector(canonical, lost).rebuild_projection(checkpoint=signed)
    assert caught.value.reason_code == "CONTROL_PLANE_UNAVAILABLE"


def test_ncr_c4_002_a_checkpoint_of_another_store_or_release_is_refused(canonical: Any, adapter: Any) -> None:
    """The store, branch and release of a verified checkpoint are compared with the projection's,
    never taken from the checkpoint: another store is CHECKPOINT_INVALID, another release
    RELEASE_MISMATCH, both before any write."""
    rebuild = _module("ocor_runtime.c4.rebuild")
    drift = _module("ocor_runtime.c4.drift")
    detector = _detector(canonical, adapter)
    cases = {"CHECKPOINT_INVALID": _canonical_payload(store_id="urn:ocor:projection-store:typedb:other"),
             "RELEASE_MISMATCH": _canonical_payload(release_digest=OTHER_RELEASE)}
    for reason, payload in cases.items():
        signed = drift.SignedProjectionCheckpoint(payload=payload, key_id=CHECKPOINT_KEY_ID,
                                                  signature=_signed(payload).signature)
        with pytest.raises(rebuild.DriftError) as caught:
            detector.rebuild_projection(checkpoint=signed)
        assert caught.value.reason_code == reason


def _rem_0050() -> Any:
    return importlib.import_module("test_ocor_dev_rem_0050")


def test_ncr_c4_001_a_typed_projection_failure_leaves_the_projector_typed() -> None:
    """LLD v1.1 :148: a failure of the projection leaves the projector only as ProjectorError -- a
    typed C2Error of a read as BACKEND_ERROR, an unreachable TypeDB at the write as
    BACKEND_UNAVAILABLE -- never as the raw error of the projection port."""
    rem = _rem_0050()
    projector = _module("ocor_runtime.c4.projector")
    typedb_adapter = _module("ocor_runtime.c4.typedb_adapter")
    cases = [
        ({"failure": C2Error("CONTROL_PLANE_UNAVAILABLE", "malformed"), "at": "position"}, "BACKEND_ERROR"),
        ({"failure": C2Error("CONTROL_PLANE_UNAVAILABLE", "malformed"), "at": "lookup"}, "BACKEND_ERROR"),
        ({"failure": typedb_adapter.TypeDBUnavailableError("unreachable"), "at": "apply"}, "BACKEND_UNAVAILABLE"),
    ]
    for failure, reason in cases:
        double = rem._projection_double(**failure)
        with pytest.raises(projector.ProjectorError) as caught:
            projector.CanonicalStateProjector(double, release_digest=RELEASE).apply(rem._committed_event())
        assert caught.value.reason_code == reason, failure


def test_ncr_c4_001_an_event_without_a_commit_is_refused_before_any_write() -> None:
    """FR-064 (Register :188): the projector deduplicates by commitId, so an event whose payload and
    transport both lack a commit is SCHEMA_VIOLATION before anything is observed or written."""
    rem = _rem_0050()
    projector = _module("ocor_runtime.c4.projector")
    event = rem._committed_event(commit_id=rem.MISSING)
    value = event.to_mapping()
    value["transport"] = {key: item for key, item in value["transport"].items() if key != "source_transaction_id"}
    object.__setattr__(event, "_value", value)
    double = rem._projection_double()
    with pytest.raises(projector.ProjectorError) as caught:
        projector.CanonicalStateProjector(double, release_digest=RELEASE).apply(event)
    assert caught.value.reason_code == "SCHEMA_VIOLATION"
    assert double.applied == []


class _WatermarkFailure:
    """The real TypeDB projection as projection and watermark port, whose watermark answers as
    given once the object projection is down (the first ``current`` of the request admission
    still reads TypeDB)."""

    def __init__(self, real: Any, answer: Any) -> None:
        self._real = real
        self._answer = answer
        self.calls = 0

    def read(self, request: Any) -> Any:
        return self._real.read(request)

    def current(self, projection_id: str, branch: str) -> Any:
        self.calls += 1
        if self.calls == 1:
            return self._real.current(projection_id, branch)
        return self._answer()


def _confirmed(**changes: Any) -> Any:
    watermark = _module("ocor_runtime.c4.watermark")
    value = {"store_id": "urn:ocor:projection-store:typedb:ocor_default", "branch": "main", "commit_id": "commit-2",
             "sequence": 2, "release_digest": RELEASE, "confirmed_at": T0}
    value.update(changes)
    return watermark.ConfirmedWatermark(**value)


def _raise(error: BaseException) -> Any:
    def answer() -> Any:
        raise error
    return answer


def test_ncr_c2_013_a_watermark_that_cannot_form_a_served_context_stays_control_plane_unavailable(
        gateway_backends: tuple[Any, Any, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """ADD v1.3 :174 and :1364: PROJECTION_NOT_READY is built only from a confirmed watermark of
    the requested branch that forms a served context; a watermark port that fails outside its
    contract, a confirmed watermark of another branch or of a release that is not a SHA-256 URN,
    or an observed watermark of another branch is the typed fail-closed CONTROL_PLANE_UNAVAILABLE
    without a served context."""
    rem = _rem_0049()
    typedb, jena, log = gateway_backends
    unavailable = _module("ocor_runtime.c4.typedb_adapter").TypeDBUnavailableError
    ports = _module("ocor_runtime.c2.ports")
    answers = {
        "port-failure": _raise(RuntimeError("the watermark port failed outside its contract")),
        "confirmed-other-branch": _raise(unavailable("down", confirmed=_confirmed(branch="feature"))),
        "confirmed-release-not-a-digest": _raise(unavailable("down", confirmed=_confirmed(release_digest="x"))),
        "confirmed-naive-instant": _raise(unavailable("down", confirmed=_confirmed(confirmed_at=T0.replace(tzinfo=None)))),
        "observed-other-branch": lambda: ports.Watermark(
            projection_id=PROJECTION, branch="feature", ontology_release_digest=RELEASE, canonical_commit="commit-2",
            observed_at=T0),
    }
    real = _module("ocor_runtime.c4.object_projection").TypeDBObjectProjection()
    for case, answer in answers.items():
        projection = _WatermarkFailure(typedb, answer)
        fixture = rem.Gateway(typedb, jena, log, projection=projection, objects=_DownObjects(real, monkeypatch))
        rem.load_fleet(fixture, typedb)
        projection.calls = 0
        reply = fixture.invoke("GetObject", rem.get_object_body())
        assert (reply.status, reply.body["reason_code"]) == (503, "CONTROL_PLANE_UNAVAILABLE"), (case, reply.body)
        assert "served" not in reply.body, case
