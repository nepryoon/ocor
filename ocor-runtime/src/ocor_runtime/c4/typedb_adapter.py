"""C4 -- retained TypeDB projection adapter.

Completes the smallest contract-compliant, retained (non-spike)
version of ``spikes.typedb_exact_commit.adapter`` (OCOR-DEV-0017),
implementing the sealed ``ProjectionReadPort``/``WatermarkPort``
(OCOR-DEV-0012, ``ocor_runtime.c2.ports``, reused unmodified) against a
real, live TypeDB instance via its HTTP v1 transaction API -- the same
real API surface OCOR-DEV-0017 already proved for real.

The one genuine behavioral difference from the spike: the spike's
``ingest``/``advance_watermark`` are deliberately TWO separate calls,
so tests can model a lagging, asynchronously-applied projection and
exercise every race between a fact and its watermark. This retained
adapter is the real production path a C5 event consumer uses:
``apply_commit`` ingests the fact AND advances the watermark to that
commit in the SAME real TypeDB write transaction, so a fact can never
become visible ahead of -- or the watermark advance lag behind -- its
own commit in normal operation. ``read``/``watermark`` reuse the exact
same fail-closed consistency verification the spike already proved
(``NamedQueryRequest.verify_served``, sealed, unmodified): a stale
projection can never masquerade as exact.

This module never imports a direct backend client outside this file
would be needed (AFF-002/AFF-006); since ``c4/`` has no adapters/
subtree of its own yet and this is the ONLY file this task adds, the
HTTP client code lives here directly rather than in a separate
sub-package, matching OCOR-DEV-0017's own spike file layout (a single
file, no adapters/ split, since it is itself already the adapter).

OCOR-DEV-REM-0052 (NCP-U05, NCR-C4-001 and NCR-C4-003):

* the adapter declares the ontology release it projects (FR-148, Register :331) and records
  every applied commit in the durable watermark ledger of ``ocor_runtime.c4.watermark``,
  outside the projection store; the watermark port and the served context report that
  release, the branch the projection serves and the measured staleness (NFR-024 :180,
  NFR-077 :403), never a placeholder nor a value copied from the request;
* deduplication on (store, branch, commit_id) is durable and the watermark is monotonic: a
  commit already ordered on the branch is never applied again (FR-064 :188; LLD v1.1 :355);
* an unreachable TypeDB is the typed ``TypeDBUnavailableError`` (reason code
  ``PROJECTION_NOT_READY``); a read answers ``PROJECTION_NOT_READY`` with the served context
  of the last confirmed watermark and the staleness from its instant (PO decision
  NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 5; ADD v1.3 :1364 and :3406; contract
  :486-491); a projection that disagrees with the ledger answers the same explicit state;
* every write or schema transaction is closed on every error path, a connection-level error
  and a failed commit included (decision request OCOR-DEV-0060-BA-RUNTIME-GAPS).
"""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..c2.ports import C2Error, NamedQueryRequest, NamedQueryResponse, ServedContext, Watermark
from .watermark import ConfirmedWatermark, WatermarkLedgerError, WatermarkLedgerPort

TYPEDB_URL = "http://127.0.0.1:8000"
DATABASE = "ocor_default"
BRANCH = "main"
NO_WATERMARK_SENTINEL = "urn:ocor:commit:none"

SCHEMA_QUERY = (
    "define "
    "attribute c4-fact-id, value string; "
    "attribute c4-commit-id, value string; "
    "attribute c4-payload, value string; "
    "entity c4-fact, owns c4-fact-id @key, owns c4-commit-id @card(1..1), "
    "owns c4-payload @card(1..1); "
    "entity c4-watermark, owns c4-commit-id @card(1..1); "
    "attribute c4-commit-seq, value integer; "
    "entity c4-commit-order, owns c4-commit-id @key, owns c4-commit-seq @card(1..1);"
)


class TypeDBAdapterError(RuntimeError):
    """A typed failure of the TypeDB projection: a refused or malformed exchange."""

    reason_code = "CONTROL_PLANE_UNAVAILABLE"


class TypeDBUnavailableError(TypeDBAdapterError):
    """TypeDB cannot be reached: the projection is not ready (ADD v1.3 :3406). ``confirmed``
    is the last watermark C4 confirmed durably, when the ledger could be read."""

    reason_code = "PROJECTION_NOT_READY"

    def __init__(self, message: str, *, confirmed: ConfirmedWatermark | None = None) -> None:
        self.confirmed = confirmed
        super().__init__(message)


def _unreachable(exc: BaseException) -> bool:
    """A transport failure before any answer (refused, unreachable, timed out), as opposed
    to an answer outside the protocol or a refusal by status."""
    if isinstance(exc, (urllib.error.HTTPError, http.client.HTTPException)):
        return False
    return isinstance(exc, OSError)


def _literal(value: str) -> str:
    """Renders ``value`` as a TypeQL string literal, escaping ``\\`` and ``"``
    so an identifier or payload can never terminate the literal and inject
    further TypeQL. A canonical URN/digest (no ``\\`` or ``"``) is quoted
    exactly as before, keeping generated queries byte-identical."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _require_value(field: str, value: object) -> str:
    """Rejects a missing/empty/non-string value before any query is built, so a
    malformed identifier or payload can never reach TypeDB (fail-closed)."""
    if not isinstance(value, str) or not value:
        raise C2Error("SCHEMA_VIOLATION", f"{field} is required")
    return value


def _request(
    method: str, url: str, *, headers: dict[str, str] | None = None, body: bytes | None = None, timeout: float = 10.0
) -> tuple[int, bytes]:
    """One TypeDB HTTP exchange; the answer body stays raw, untrusted bytes. A protocol failure
    (bad status line, truncated answer) is the adapter's typed error; a transport failure
    (refused, unreachable) stays raw ``URLError``/``OSError``."""
    request = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except http.client.HTTPException as exc:
        raise TypeDBAdapterError("TypeDB answered outside the HTTP protocol") from exc


def _answer(body: bytes) -> Mapping[str, Any]:
    """A TypeDB answer body is strict UTF-8 JSON holding an object; anything else fails here."""
    try:
        answer = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise TypeDBAdapterError("the TypeDB answer is not UTF-8 JSON") from exc
    if not isinstance(answer, Mapping):
        raise TypeDBAdapterError("the TypeDB answer is not an object")
    return answer


def _token() -> str:
    status, body = _request(
        "POST",
        f"{TYPEDB_URL}/v1/signin",
        headers={"Content-Type": "application/json"},
        body=json.dumps({"username": "admin", "password": "password"}).encode("utf-8"),
    )
    if status != 200:
        raise TypeDBAdapterError(f"cannot sign in to TypeDB: HTTP {status}")
    return _token_value(_field(_answer(body), "token"))


def _transaction(kind: str, token: str) -> str:
    status, body = _request(
        "POST",
        f"{TYPEDB_URL}/v1/transactions/open",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        body=json.dumps({"databaseName": DATABASE, "transactionType": kind}).encode("utf-8"),
    )
    if status != 200:
        raise TypeDBAdapterError(f"cannot open a TypeDB {kind} transaction: HTTP {status}")
    return _transaction_value(_field(_answer(body), "transactionId"))


def _query(transaction_id: str, query: str, token: str) -> tuple[int, Mapping[str, Any]]:
    """The status of a query and, when it succeeded, its answer object; the body of a failed
    query is never parsed nor returned."""
    status, body = _request(
        "POST",
        f"{TYPEDB_URL}/v1/transactions/{transaction_id}/query",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        body=json.dumps({"query": query}).encode("utf-8"),
    )
    if status != 200:
        return status, {}
    return status, _answer(body)


def _commit(transaction_id: str, token: str) -> None:
    status, _ = _request(
        "POST", f"{TYPEDB_URL}/v1/transactions/{transaction_id}/commit", headers={"Authorization": f"Bearer {token}"}
    )
    if status != 200:
        raise TypeDBAdapterError(f"failed to commit TypeDB transaction: HTTP {status}")


def _close(transaction_id: str, token: str) -> None:
    _request(
        "POST", f"{TYPEDB_URL}/v1/transactions/{transaction_id}/close", headers={"Authorization": f"Bearer {token}"}
    )


def _abandon(transaction_id: str, token: str) -> None:
    """Closes a transaction that failed; a failure of the close itself never hides the
    failure of the transaction."""
    try:
        _close(transaction_id, token)
    except (TypeDBAdapterError, OSError, http.client.HTTPException):
        return


def _transact(kind: str, queries: tuple[str, ...]) -> None:
    """Runs every query in ONE real TypeDB transaction of ``kind``, committed together or not
    at all. On every error path -- a refused query, a connection-level error, a failed
    commit -- the transaction is closed before the failure leaves the adapter."""
    token = _token()
    transaction_id = _transaction(kind, token)
    try:
        for query in queries:
            status, _ = _query(transaction_id, query, token)
            if status != 200:
                raise TypeDBAdapterError(f"{kind} failed: HTTP {status}")
        _commit(transaction_id, token)
    except BaseException:
        _abandon(transaction_id, token)
        raise


def _write(*queries: str) -> None:
    """Runs every query inside ONE real TypeDB write transaction,
    committed together or not at all -- the primitive ``apply_commit``
    relies on to make fact-ingest and watermark-advance atomic."""
    _transact("write", queries)


def _schema_write(query: str) -> None:
    _transact("schema", (query,))


# Every way a TypeDB answer can fail to be a well-formed result: transport (refused,
# protocol, HTTP status), decoding (non UTF-8, non JSON) and shape.
_ANSWER_FAILURES = (TypeDBAdapterError, OSError, http.client.HTTPException, ValueError, KeyError, TypeError)


def _strict_request(method: str, url: str, *, token: str | None = None, body: object = None) -> object:
    """One TypeDB HTTP exchange whose answer is untrusted: a non-200 status, a body that is
    not UTF-8 or not JSON fails here, before any field is read."""
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, method=method, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=10.0) as response:
        if response.status != 200:
            raise TypeDBAdapterError(f"TypeDB answered HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def _field(answer: object, name: str) -> str:
    if not isinstance(answer, Mapping):
        raise TypeDBAdapterError("the TypeDB answer is not an object")
    value = answer.get(name)
    if not isinstance(value, str) or not value:
        raise TypeDBAdapterError(f"the TypeDB answer has no {name}")
    return value


# A session token travels in an HTTP header and a transaction id in the URL path: only values
# that are safe there are accepted (visible ASCII; RFC 3986 unreserved characters).
_TOKEN = re.compile(r"[!-~]+")
_TRANSACTION_ID = re.compile(r"[A-Za-z0-9._~-]+")


def _token_value(value: str) -> str:
    if _TOKEN.fullmatch(value) is None:
        raise TypeDBAdapterError("the TypeDB session token is not header-safe")
    return value


def _transaction_value(value: str) -> str:
    if _TRANSACTION_ID.fullmatch(value) is None or value in {".", ".."}:
        raise TypeDBAdapterError("the TypeDB transaction id is not a path segment")
    return value


def _read(query: str) -> list[Any]:
    """The adapter's one read primitive: a read transaction whose answer is untrusted. A
    transport failure stays raw (``URLError``/``OSError``); a non-200 status, a body that is
    not UTF-8 JSON or an answer without an answer list fails here, before any row is read."""
    token = _token_value(_field(_strict_request("POST", f"{TYPEDB_URL}/v1/signin",
                                                body={"username": "admin", "password": "password"}), "token"))
    transaction = _transaction_value(_field(_strict_request(
        "POST", f"{TYPEDB_URL}/v1/transactions/open", token=token,
        body={"databaseName": DATABASE, "transactionType": "read"}), "transactionId"))
    try:
        result = _strict_request("POST", f"{TYPEDB_URL}/v1/transactions/{transaction}/query", token=token,
                                 body={"query": query})
    finally:
        _close(transaction, token)
    if not isinstance(result, Mapping) or not isinstance(result.get("answers"), list):
        raise TypeDBAdapterError("the TypeDB answer has no answer list")
    return list(result["answers"])


def _rows(query: str, variables: tuple[str, ...]) -> list[dict[str, object]]:
    """The answer rows of a read query: for each row, the raw ``value`` of each named
    variable -- never converted; a row of any other shape fails here."""
    rows: list[dict[str, object]] = []
    for answer in _read(query):
        data = answer.get("data") if isinstance(answer, Mapping) else None
        if not isinstance(data, Mapping):
            raise TypeDBAdapterError("a TypeDB answer row has no data")
        row: dict[str, object] = {}
        for name in variables:
            concept = data.get(name)
            if not isinstance(concept, Mapping) or "value" not in concept:
                raise TypeDBAdapterError(f"a TypeDB answer row has no value for {name}")
            row[name] = concept["value"]
        rows.append(row)
    return rows


def read_rows(query: str, variables: tuple[str, ...]) -> list[dict[str, object]]:
    """Run a read query and return, for each answer row, the raw ``value`` of each named
    variable -- never converted. Every failure, of the transport or of the answer shape,
    is the typed fail-closed ``CONTROL_PLANE_UNAVAILABLE`` (ADD v1.3 :174; Named Query
    Gateway contract :486-491): no raw exception and no partial result leaves the adapter."""

    try:
        return _rows(query, variables)
    except C2Error:
        raise
    except _ANSWER_FAILURES as exc:
        raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the TypeDB projection did not return a well-formed answer") from exc


def _position_value(value: object) -> int:
    """A commit position is a positive integer as stored: no bool, float or text."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the TypeDB projection returned a malformed commit position")
    return value


def _text_value(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the TypeDB projection returned a malformed value")
    return value


def _ensure_database() -> None:
    token = _token()
    status, body = _request("GET", f"{TYPEDB_URL}/v1/databases", headers={"Authorization": f"Bearer {token}"})
    if status != 200:
        raise TypeDBAdapterError(f"cannot list TypeDB databases: HTTP {status}")
    databases = _answer(body).get("databases")
    if not isinstance(databases, list):
        raise TypeDBAdapterError("the TypeDB database listing has no database list")
    existing = {_field(entry, "name") for entry in databases}
    if DATABASE in existing:
        return
    status, _ = _request(
        "POST", f"{TYPEDB_URL}/v1/databases/{DATABASE}", headers={"Authorization": f"Bearer {token}"}
    )
    if status != 200:
        raise TypeDBAdapterError(f"failed to create TypeDB database {DATABASE!r}: HTTP {status}")


WATERMARK_QUERY = "match $w isa c4-watermark, has c4-commit-id $c;"
# One process applies one commit at a time: the watermark replacement below is a
# compare-and-delete of the previous watermark, so the order of the branch stays total.
_APPLY_LOCK = threading.Lock()
DIGEST = re.compile(r"urn:sha256:[0-9a-f]{64}")


def _milliseconds(now: datetime, since: datetime) -> int:
    return max(0, int((now - since) / timedelta(milliseconds=1)))


@dataclass(frozen=True, slots=True)
class _State:
    """What the projection serves for its branch, as C4 knows it durably."""

    release_digest: str
    staleness_ms: int


class _Disagreement(Exception):
    """The projection and the durable ledger name different watermarks."""


class TypeDBProjectionAdapter:
    """Retained C4 projection: real TypeDB-backed ``ProjectionReadPort``/
    ``WatermarkPort`` where every commit's fact and watermark advance
    together, atomically, in one real write transaction, and every applied
    commit is confirmed in the durable watermark ledger (OCOR-DEV-REM-0052)."""

    def __init__(
        self,
        *,
        release_digest: str,
        ledger: WatermarkLedgerPort,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not isinstance(release_digest, str) or DIGEST.fullmatch(release_digest) is None:
            raise TypeError("release_digest must be a SHA-256 URN")
        if not isinstance(ledger, WatermarkLedgerPort):
            raise TypeError("a WatermarkLedgerPort is required")
        self._release = release_digest
        self._ledger = ledger
        self._clock = clock

    @property
    def release_digest(self) -> str:
        """The ontology release this projection declares (FR-148, Register :331)."""
        return self._release

    @property
    def store_id(self) -> str:
        return f"urn:ocor:projection-store:typedb:{DATABASE}"

    def initialize(self) -> None:
        _ensure_database()
        _schema_write(SCHEMA_QUERY)
        initialize = getattr(self._ledger, "initialize", None)
        if callable(initialize):
            initialize()

    def reset(self) -> None:
        _write(
            "match $f isa c4-fact; delete $f;",
            "match $w isa c4-watermark; delete $w;",
            "match $o isa c4-commit-order; delete $o;",
        )
        self.reset_ledger()

    def reset_ledger(self) -> None:
        """Empties the durable ledger of this store: a projection that is reset or rebuilt
        from scratch restarts its order and its confirmations."""
        self._ledger.clear(self.store_id)

    def observe(self, commit_id: str) -> None:
        """Records a commit delivered to the projector and not yet applied: from this
        instant the projection lags behind the commits C4 has received (NFR-077 :403)."""
        self._ledger.observe(self.store_id, BRANCH, _require_value("commit_id", commit_id), at=self._clock())

    def _confirm(self, commit_id: str, sequence: int) -> None:
        self._ledger.confirm(self.store_id, BRANCH, commit_id, sequence=sequence, release_digest=self._release,
                             at=self._clock())

    def apply_commit(self, *, fact_id: str, commit_id: str, payload: str) -> bool:
        """Ingests the fact and advances the watermark to ``commit_id``
        atomically: both statements commit together in one real
        transaction, or neither does. A prior fact with the same
        ``fact_id`` (a fact update) is replaced; the prior watermark is
        replaced with the new commit. A commit already ordered on the branch
        is a duplicate: nothing is written and ``False`` is returned, so a
        replay never moves the watermark backwards (FR-064, Register :188)."""
        fact_id = _require_value("fact_id", fact_id)
        commit_id = _require_value("commit_id", commit_id)
        payload = _require_value("payload", payload)
        with _APPLY_LOCK:
            position = self.position(BRANCH, commit_id)
            if position is not None:
                # durable deduplication on (store, branch, commit_id); the confirmation of a
                # commit applied before a failed confirmation is completed here
                self._confirm(commit_id, position)
                return False
            existing_fact = self._lookup_fact(fact_id)
            previous = self.current_watermark()
            sequence = self._next_sequence()
            statements: list[str] = []
            if existing_fact is not None:
                statements.append(f"match $f isa c4-fact, has c4-fact-id {_literal(fact_id)}; delete $f;")
            statements.append(
                f"insert $f isa c4-fact, has c4-fact-id {_literal(fact_id)}, "
                f"has c4-commit-id {_literal(commit_id)}, has c4-payload {_literal(payload)};"
            )
            if previous is not None:
                statements.append(f"match $w isa c4-watermark, has c4-commit-id {_literal(previous)}; delete $w;")
            statements.append(f"insert $w isa c4-watermark, has c4-commit-id {_literal(commit_id)};")
            # canonical order of the branch, recorded in the same transaction as the
            # watermark advance (FR-057 "branch/commit ordering", Register :179).
            statements.append(
                f"insert $o isa c4-commit-order, has c4-commit-id {_literal(commit_id)}, "
                f"has c4-commit-seq {sequence};"
            )
            _write(*statements)
            self._confirm(commit_id, sequence)
            return True

    def _next_sequence(self) -> int:
        rows = read_rows("match $o isa c4-commit-order, has c4-commit-seq $s;", ("s",))
        return 1 + max((_position_value(row["s"]) for row in rows), default=0)

    def position(self, branch: str, commit: str) -> int | None:
        """``CommitOrderingPort``: the position of ``commit`` among the commits applied
        to ``branch``, or ``None`` when it has not landed (or on another branch)."""
        if branch != BRANCH or not isinstance(commit, str) or not commit:
            return None
        rows = read_rows(f"match $o isa c4-commit-order, has c4-commit-id {_literal(commit)}, has c4-commit-seq $s;",
                         ("s",))
        if not rows:
            return None
        return _position_value(rows[0]["s"])

    def _confirmed(self) -> ConfirmedWatermark | None:
        """The last confirmed watermark for the exception of an unreachable projection, or
        ``None`` when the ledger cannot say."""
        try:
            return self._ledger.latest(self.store_id, BRANCH)
        except WatermarkLedgerError:
            return None

    def _watermark(self) -> str | None:
        """The watermark as stored; an unreachable TypeDB stays the raw transport error here."""
        rows = _rows(WATERMARK_QUERY, ("c",))
        if not rows:
            return None
        if len(rows) > 1:
            raise TypeDBAdapterError("the TypeDB projection holds more than one watermark")
        return _text_value(rows[0]["c"])

    def current_watermark(self) -> str | None:
        """The commit of the projection watermark, a non-empty string read without conversion,
        or ``None`` when no commit has been applied. An unreachable TypeDB is the typed
        ``TypeDBUnavailableError`` (``PROJECTION_NOT_READY``, NCR-C4-003); a malformed answer, or
        any other failure of the answer, is the typed ``CONTROL_PLANE_UNAVAILABLE``."""
        try:
            return self._watermark()
        except C2Error:
            raise
        except _ANSWER_FAILURES as exc:
            if _unreachable(exc):
                raise TypeDBUnavailableError("the TypeDB projection is unreachable",
                                             confirmed=self._confirmed()) from exc
            raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the TypeDB projection did not return a well-formed answer") from exc

    def _state(self, watermark: str | None) -> _State:
        """Release and staleness of what the projection serves. The projection and the
        ledger must name the same watermark; staleness is zero while every commit C4 has
        received is applied, otherwise the time since the earliest unapplied one. A ledger that
        has confirmed nothing yet (a projection that predates it) is no disagreement: the
        release is the declared one and the next applied commit is confirmed."""
        try:
            latest = self._ledger.latest(self.store_id, BRANCH)
            if latest is not None and latest.commit_id != watermark:
                # the projection lost or bypassed a confirmed watermark: an explicit state
                raise _Disagreement
            pending = self._ledger.pending_since(self.store_id, BRANCH)
        except WatermarkLedgerError as exc:
            raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the C4 watermark ledger is unavailable") from exc
        release = self._release if latest is None else latest.release_digest
        staleness = 0 if pending is None else _milliseconds(self._clock(), pending)
        return _State(release_digest=release, staleness_ms=staleness)

    def _not_ready(self, request: NamedQueryRequest, message: str) -> C2Error:
        """``PROJECTION_NOT_READY`` with the served context of the last confirmed watermark and
        the staleness from its instant (PO decision NORMATIVE-CONFORMANCE-PLAN point 5)."""
        try:
            latest = self._ledger.latest(self.store_id, BRANCH)
            pending = None if latest is not None else self._ledger.pending_since(self.store_id, BRANCH)
        except WatermarkLedgerError:
            return C2Error("CONTROL_PLANE_UNAVAILABLE", "the C4 watermark ledger is unavailable")
        now = self._clock()
        if latest is not None:
            commit, release, staleness = latest.commit_id, latest.release_digest, _milliseconds(now, latest.confirmed_at)
        else:
            commit, release = NO_WATERMARK_SENTINEL, self._release
            staleness = 0 if pending is None else _milliseconds(now, pending)
        served = ServedContext(
            branch=BRANCH, ontology_release_digest=release, canonical_commit=commit, projection_watermark=commit,
            staleness_ms=staleness, governed_context_digest=request.governed_context_digest,
            policy_bundle_digest=request.governed_context.policy_bundle_digest)
        return C2Error("PROJECTION_NOT_READY", message, served=served)

    def _lookup_fact(self, fact_id: str) -> tuple[str, str] | None:
        rows = read_rows(
            f"match $f isa c4-fact, has c4-fact-id {_literal(fact_id)}, "
            f"has c4-commit-id $c, has c4-payload $p;",
            ("c", "p"),
        )
        if not rows:
            return None
        return _text_value(rows[0]["c"]), _text_value(rows[0]["p"])

    def _served_fact(self, fact_id: str) -> tuple[str | None, tuple[str, str] | None]:
        """The watermark and the fact, read with the raw transport failure preserved."""
        watermark = self._watermark()
        rows = _rows(f"match $f isa c4-fact, has c4-fact-id {_literal(fact_id)}, "
                     f"has c4-commit-id $c, has c4-payload $p;", ("c", "p"))
        found = None if not rows else (_text_value(rows[0]["c"]), _text_value(rows[0]["p"]))
        return watermark, found

    def read(self, request: NamedQueryRequest) -> NamedQueryResponse:
        fact_id = request.parameters.get("fact_id")
        if not isinstance(fact_id, str) or not fact_id:
            raise C2Error("SCHEMA_VIOLATION", "fact_id parameter is required")
        if request.branch != BRANCH or request.scenario_id is not None:
            # a branch or a scenario the projection does not serve is never answered from main
            raise C2Error("UNSUPPORTED_CAPABILITY", "the projection does not serve the requested branch or scenario")
        try:
            watermark, found = self._served_fact(fact_id)
        except C2Error:
            raise
        except _ANSWER_FAILURES as exc:
            if _unreachable(exc):
                raise self._not_ready(request, "the TypeDB projection is unreachable") from exc
            raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the TypeDB projection did not return a well-formed answer") from exc
        try:
            state = self._state(watermark)
        except _Disagreement:
            raise self._not_ready(request, "the projection disagrees with its confirmed watermark") from None
        # the served commit reflects the row actually read, never the
        # watermark by assumption -- verify_served (below) is what
        # independently proves the two agree before anything is
        # returned as exact.
        canonical_commit = found[0] if found is not None else (watermark or NO_WATERMARK_SENTINEL)
        served = ServedContext(
            branch=BRANCH,
            ontology_release_digest=state.release_digest,
            canonical_commit=canonical_commit,
            projection_watermark=watermark or NO_WATERMARK_SENTINEL,
            staleness_ms=state.staleness_ms,
            governed_context_digest=request.governed_context_digest,
            policy_bundle_digest=request.governed_context.policy_bundle_digest,
        )
        if state.release_digest != self._release:
            # adapter, projector and store must declare the same release (FR-148, Register :331)
            raise C2Error("RELEASE_MISMATCH", "the projection store serves another release", served=served)
        request.verify_served(served, ordering=self)
        if found is None:
            # an absent result is indistinguishable from a denial: errors never disclose
            # existence (NFR-006, Register :50; contract :454).
            raise C2Error("POLICY_DENIED", "no authorised result for the request")
        _, payload = found
        result_digest = "urn:sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return NamedQueryResponse(
            request_id=request.request_id,
            result_ref=f"urn:ocor:c4-fact:{fact_id}",
            result_digest=result_digest,
            served=served,
        )

    def current(self, projection_id: str, branch: str) -> Watermark:
        """The sealed ``WatermarkPort`` method: the watermark of a branch the projection
        serves, with the release it declares durably and ``observed_at`` the instant as of
        which it is known current (``now - staleness``, NFR-024 :180). A branch it does not
        serve is ``UNSUPPORTED_CAPABILITY``, never main's watermark under another name."""
        if branch != BRANCH:
            raise C2Error("UNSUPPORTED_CAPABILITY", "the projection does not serve the requested branch")
        watermark = self.current_watermark()
        try:
            state = self._state(watermark)
        except _Disagreement:
            raise TypeDBUnavailableError("the projection disagrees with its confirmed watermark",
                                         confirmed=self._confirmed()) from None
        return Watermark(
            projection_id=projection_id,
            branch=branch,
            ontology_release_digest=state.release_digest,
            canonical_commit=watermark or NO_WATERMARK_SENTINEL,
            observed_at=self._clock() - timedelta(milliseconds=state.staleness_ms),
        )
