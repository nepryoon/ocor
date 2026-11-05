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

OCOR-DEV-REM-0052 (NCP-U05, NCR-C4-004): TypeDB keeps no history, so ``EXACT_AT_COMMIT(Cn)`` on a
named logical query is emulated (ADD v1.3 :356, BA-03). Every applied commit also appends, in the
same write transaction, the revision of its fact with its position on the branch; a read pinned
to a commit the projection has moved beyond is served from a disposable sandbox database built
from that history at Cn and dropped once the answer is read (``TypeDBCommitSandbox``). When the
emulation is unavailable -- no sandbox configured, every sandbox slot taken, the history up to Cn
incomplete, or the backend refusing the sandbox -- the answer is ``UNSUPPORTED_CAPABILITY``, never
the later commit (ADD v1.3 :1366; LLD v1.1 :369; FR-057, Register :179).

OCOR-DEV-REM-0052 (NCP-U05, NCR-C4-002): the projection cannot be built without the durable drift
quarantine of ``ocor_runtime.c4.drift`` and enforces it on its own read path: a quarantined
aggregate is ``PROJECTION_NOT_READY`` for every consistency mode, ``EXACT_AT_COMMIT`` included,
with the served context of the last confirmed watermark; a quarantine that cannot be consulted is
``CONTROL_PLANE_UNAVAILABLE`` (LLD v1.1 :148 and :346). ``reconciliation_digest`` and
``projected_facts`` are the reads of the drift detector, never a serving path.
"""

from __future__ import annotations

import functools
import hashlib
import http.client
import json
import re
import threading
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from ..c2.ports import C2Error, ConsistencyMode, NamedQueryRequest, NamedQueryResponse, ServedContext, Watermark
from .drift import CheckpointStorePort, ProjectionQuarantinePort, QuarantineRecord
from .watermark import ConfirmedWatermark, WatermarkLedgerError, WatermarkLedgerPort

T = TypeVar("T")
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
    "entity c4-commit-order, owns c4-commit-id @key, owns c4-commit-seq @card(1..1); "
    "entity c4-fact-revision, owns c4-fact-id @card(1..1), owns c4-commit-id @card(1..1), "
    "owns c4-commit-seq @card(1..1), owns c4-payload @card(1..1);"
)
# A sandbox database is named after the projection database, so it is recognised and never
# confused with the projection itself.
SANDBOX_PREFIX = f"{DATABASE}_sbx_"


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
        with exc:
            return exc.code, exc.read()
    except http.client.HTTPException as exc:
        raise TypeDBAdapterError("TypeDB answered outside the HTTP protocol") from exc


def _answer(body: bytes) -> Mapping[str, Any]:
    """A TypeDB answer body is strict UTF-8 JSON holding an object; anything else fails here."""
    try:
        answer = json.loads(body.decode("utf-8"))
    except (ValueError, RecursionError) as exc:  # a depth the decoder cannot read is malformed too
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


def _transaction(kind: str, token: str, database: str | None = None) -> str:
    status, body = _request(
        "POST",
        f"{TYPEDB_URL}/v1/transactions/open",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        body=json.dumps({"databaseName": database or DATABASE, "transactionType": kind}).encode("utf-8"),
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


def _transact(kind: str, queries: tuple[str, ...], database: str | None = None) -> None:
    """Runs every query in ONE real TypeDB transaction of ``kind``, committed together or not
    at all. On every error path -- a refused query, a connection-level error, a failed
    commit -- the transaction is closed before the failure leaves the adapter."""
    token = _token()
    transaction_id = _transaction(kind, token, database)
    try:
        for query in queries:
            status, _ = _query(transaction_id, query, token)
            if status != 200:
                raise TypeDBAdapterError(f"{kind} failed: HTTP {status}")
        _commit(transaction_id, token)
    except BaseException:
        _abandon(transaction_id, token)
        raise


def _write(*queries: str, database: str | None = None) -> None:
    """Runs every query inside ONE real TypeDB write transaction,
    committed together or not at all -- the primitive ``apply_commit``
    relies on to make fact-ingest and watermark-advance atomic."""
    _transact("write", queries, database)


def _schema_write(query: str, database: str | None = None) -> None:
    _transact("schema", (query,), database)


# Every way a TypeDB answer can fail to be a well-formed result: transport (refused,
# protocol, HTTP status), decoding (non UTF-8, non JSON, nested beyond the decoder) and shape.
_ANSWER_FAILURES = (TypeDBAdapterError, OSError, http.client.HTTPException, ValueError, KeyError, TypeError,
                    RecursionError)


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


def _read(query: str, database: str | None = None) -> list[Any]:
    """The adapter's one read primitive: a read transaction whose answer is untrusted. A
    transport failure stays raw (``URLError``/``OSError``); a non-200 status, a body that is
    not UTF-8 JSON or an answer without an answer list fails here, before any row is read."""
    token = _token_value(_field(_strict_request("POST", f"{TYPEDB_URL}/v1/signin",
                                                body={"username": "admin", "password": "password"}), "token"))
    transaction = _transaction_value(_field(_strict_request(
        "POST", f"{TYPEDB_URL}/v1/transactions/open", token=token,
        body={"databaseName": database or DATABASE, "transactionType": "read"}), "transactionId"))
    try:
        result = _strict_request("POST", f"{TYPEDB_URL}/v1/transactions/{transaction}/query", token=token,
                                 body={"query": query})
    finally:
        _close(transaction, token)
    if not isinstance(result, Mapping) or not isinstance(result.get("answers"), list):
        raise TypeDBAdapterError("the TypeDB answer has no answer list")
    return list(result["answers"])


def _rows(query: str, variables: tuple[str, ...], database: str | None = None) -> list[dict[str, object]]:
    """The answer rows of a read query: for each row, the raw ``value`` of each named
    variable -- never converted; a row of any other shape fails here."""
    rows: list[dict[str, object]] = []
    # the projection database is read through the one-argument call of the read seam
    answers = _read(query) if database is None else _read(query, database)
    for answer in answers:
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


def _database_names(token: str) -> set[str]:
    status, body = _request("GET", f"{TYPEDB_URL}/v1/databases", headers={"Authorization": f"Bearer {token}"})
    if status != 200:
        raise TypeDBAdapterError(f"cannot list TypeDB databases: HTTP {status}")
    databases = _answer(body).get("databases")
    if not isinstance(databases, list):
        raise TypeDBAdapterError("the TypeDB database listing has no database list")
    return {_field(entry, "name") for entry in databases}


def _create_database(name: str, token: str) -> None:
    status, _ = _request("POST", f"{TYPEDB_URL}/v1/databases/{name}", headers={"Authorization": f"Bearer {token}"})
    if status != 200:
        raise TypeDBAdapterError(f"failed to create TypeDB database {name!r}: HTTP {status}")


def _drop_database(name: str) -> None:
    token = _token()
    status, _ = _request("DELETE", f"{TYPEDB_URL}/v1/databases/{name}", headers={"Authorization": f"Bearer {token}"})
    if status != 200 and name in _database_names(token):
        raise TypeDBAdapterError(f"failed to drop TypeDB database {name!r}: HTTP {status}")


def _ensure_database() -> None:
    token = _token()
    if DATABASE in _database_names(token):
        return
    _create_database(DATABASE, token)


def sandbox_database_names() -> list[str]:
    """The sandbox databases that exist on the TypeDB server, sorted."""
    return sorted(name for name in _database_names(_token()) if name.startswith(SANDBOX_PREFIX))


class SandboxUnavailableError(RuntimeError):
    """The ``EXACT_AT_COMMIT(Cn)`` emulation is unavailable for this request: every sandbox slot
    is taken, the projected history up to Cn is incomplete, or the backend refused to create or
    populate the sandbox (ADD v1.3 :1366)."""

    reason_code = "UNSUPPORTED_CAPABILITY"


# Every way the backend can fail a step of the sandbox lifecycle.
_LIFECYCLE_FAILURES = (TypeDBAdapterError, OSError, http.client.HTTPException)

HISTORY_VARIABLES = ("f", "c", "s", "p")


@dataclass(frozen=True, slots=True)
class _Revision:
    fact_id: str
    commit_id: str
    sequence: int
    payload: str


def _history(commit_id: str, sequence: int) -> list[_Revision]:
    """The revisions applied on the branch up to position ``sequence`` (where ``commit_id`` must
    sit), read from the projection as an untrusted answer: a malformed row, or a row beyond the
    position asked, is the typed ``CONTROL_PLANE_UNAVAILABLE`` (contract :486-491). A history
    with a gap, a repeated position or another commit at ``sequence`` cannot reproduce Cn: the
    emulation is unavailable."""
    rows = read_rows(
        f"match $r isa c4-fact-revision, has c4-fact-id $f, has c4-commit-id $c, has c4-commit-seq $s, "
        f"has c4-payload $p; $s <= {sequence};",
        HISTORY_VARIABLES,
    )
    history: list[_Revision] = []
    for row in rows:
        revision = _Revision(fact_id=_text_value(row["f"]), commit_id=_text_value(row["c"]),
                             sequence=_position_value(row["s"]), payload=_text_value(row["p"]))
        if revision.sequence > sequence:
            raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the TypeDB projection answered a revision beyond the commit")
        history.append(revision)
    history.sort(key=lambda revision: revision.sequence)
    if [revision.sequence for revision in history] != list(range(1, sequence + 1)):
        raise SandboxUnavailableError("the projected history up to the commit is incomplete")
    if history[-1].commit_id != commit_id:
        raise SandboxUnavailableError("the projected history does not place the commit at its position")
    return history


def _population(history: list[_Revision]) -> tuple[str, ...]:
    """The write queries that make an empty sandbox the projection as it was at the last
    revision of ``history``: the latest fact of each fact id, the watermark at that commit and
    the order of the branch up to it."""
    latest: dict[str, _Revision] = {}
    for revision in history:
        latest[revision.fact_id] = revision
    statements = [
        f"insert $f isa c4-fact, has c4-fact-id {_literal(revision.fact_id)}, "
        f"has c4-commit-id {_literal(revision.commit_id)}, has c4-payload {_literal(revision.payload)};"
        for revision in latest.values()
    ]
    statements.extend(
        f"insert $o isa c4-commit-order, has c4-commit-id {_literal(revision.commit_id)}, "
        f"has c4-commit-seq {revision.sequence};"
        for revision in history
    )
    statements.append(f"insert $w isa c4-watermark, has c4-commit-id {_literal(history[-1].commit_id)};")
    return tuple(statements)


class TypeDBCommitSandbox:
    """The ``EXACT_AT_COMMIT(Cn)`` emulation of BA-03 (ADD v1.3 :356): a disposable TypeDB
    database holding the projection as it was at Cn, built from the projected history, served
    once and dropped. At most ``max_sandboxes`` exist at a time for this process; beyond that,
    or whenever a sandbox cannot be built, the emulation is unavailable
    (``SandboxUnavailableError``). A created sandbox is dropped on every path; a drop that fails
    is retried at the next opening, so no sandbox outlives the failure that left it."""

    def __init__(self, *, max_sandboxes: int = 4) -> None:
        if isinstance(max_sandboxes, bool) or not isinstance(max_sandboxes, int) or max_sandboxes < 1:
            raise TypeError("max_sandboxes must be a positive integer")
        self._slots = threading.BoundedSemaphore(max_sandboxes)
        self._orphans: set[str] = set()
        self._orphans_lock = threading.Lock()

    def _drop(self, name: str) -> None:
        try:
            _drop_database(name)
        except _LIFECYCLE_FAILURES:
            with self._orphans_lock:
                self._orphans.add(name)
            return
        with self._orphans_lock:
            self._orphans.discard(name)

    def _drop_orphans(self) -> None:
        with self._orphans_lock:
            orphans = sorted(self._orphans)
        for name in orphans:
            self._drop(name)

    @contextmanager
    def open(self, commit_id: str, sequence: int) -> Iterator[str]:
        """Yields the name of a sandbox database at ``commit_id``, the commit at position
        ``sequence`` of the branch; the sandbox is dropped when the block exits."""
        if not self._slots.acquire(blocking=False):
            raise SandboxUnavailableError("every sandbox slot is taken")
        try:
            self._drop_orphans()
            history = _history(commit_id, sequence)
            name = f"{SANDBOX_PREFIX}{uuid.uuid4().hex}"
            try:
                try:
                    _create_database(name, _token())
                    _schema_write(SCHEMA_QUERY, database=name)
                    _write(*_population(history), database=name)
                except _LIFECYCLE_FAILURES as exc:
                    raise SandboxUnavailableError("the sandbox could not be built") from exc
                yield name
            finally:
                self._drop(name)
        finally:
            self._slots.release()


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


_DEFAULT_SANDBOX = object()


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
        quarantine: ProjectionQuarantinePort,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sandbox: TypeDBCommitSandbox | None | object = _DEFAULT_SANDBOX,
    ) -> None:
        """``sandbox`` is the ``EXACT_AT_COMMIT(Cn)`` emulation (BA-03): a ``TypeDBCommitSandbox``
        of default bound unless given; ``None`` declares the emulation unavailable."""
        if not isinstance(release_digest, str) or DIGEST.fullmatch(release_digest) is None:
            raise TypeError("release_digest must be a SHA-256 URN")
        if not isinstance(ledger, WatermarkLedgerPort):
            raise TypeError("a WatermarkLedgerPort is required")
        if not isinstance(quarantine, ProjectionQuarantinePort):
            raise TypeError("a durable ProjectionQuarantinePort is required (LLD v1.1 :148)")
        if sandbox is _DEFAULT_SANDBOX:
            sandbox = TypeDBCommitSandbox()
        if sandbox is not None and not isinstance(sandbox, TypeDBCommitSandbox):
            raise TypeError("sandbox must be a TypeDBCommitSandbox or None")
        self._release = release_digest
        self._ledger = ledger
        self._quarantine = quarantine
        self._clock = clock
        self._sandbox: TypeDBCommitSandbox | None = sandbox

    @property
    def release_digest(self) -> str:
        """The ontology release this projection declares (FR-148, Register :331)."""
        return self._release

    @property
    def checkpoint_store(self) -> CheckpointStorePort | None:
        """The store of the signed checkpoints of this projection, outside the projection store:
        the durable quarantine store when it keeps checkpoints too."""
        return self._quarantine if isinstance(self._quarantine, CheckpointStorePort) else None

    @property
    def store_id(self) -> str:
        return f"urn:ocor:projection-store:typedb:{DATABASE}"

    def _unavailable_typed(self, work: Callable[[], T]) -> T:
        """A write of the projection whose unreachable TypeDB is the typed TypeDBUnavailableError
        with the last confirmed watermark (ADD v1.3 :3406), never a raw transport error; a
        malformed answer is the adapter's typed error."""
        try:
            return work()
        except (TypeDBAdapterError, C2Error):
            raise
        except _ANSWER_FAILURES as exc:
            if _unreachable(exc):
                raise TypeDBUnavailableError("the TypeDB projection is unreachable",
                                             confirmed=self._confirmed()) from exc
            raise TypeDBAdapterError("the TypeDB projection did not return a well-formed answer") from exc

    def initialize(self) -> None:
        self._unavailable_typed(_ensure_database)
        self._unavailable_typed(lambda: _schema_write(SCHEMA_QUERY))
        initialize = getattr(self._ledger, "initialize", None)
        if callable(initialize):
            initialize()

    def reset(self) -> None:
        self._unavailable_typed(lambda: _write(
            "match $f isa c4-fact; delete $f;",
            "match $w isa c4-watermark; delete $w;",
            "match $o isa c4-commit-order; delete $o;",
            "match $r isa c4-fact-revision; delete $r;",
        ))
        self.reset_ledger()
        self._quarantine.clear_quarantine(self.store_id)
        for name in self._unavailable_typed(sandbox_database_names):
            self._unavailable_typed(functools.partial(_drop_database, name))

    def sandbox_databases(self) -> list[str]:
        """The sandbox databases of this projection that exist on the TypeDB server."""
        return sandbox_database_names()

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
            # the revision of the fact at this commit: the history a sandbox at an earlier
            # commit is built from (BA-03, ADD v1.3 :356), appended in the same transaction
            statements.append(
                f"insert $r isa c4-fact-revision, has c4-fact-id {_literal(fact_id)}, "
                f"has c4-commit-id {_literal(commit_id)}, has c4-commit-seq {sequence}, "
                f"has c4-payload {_literal(payload)};"
            )
            self._unavailable_typed(lambda: _write(*statements))
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

    def _watermark(self, database: str | None = None) -> str | None:
        """The watermark as stored; an unreachable TypeDB stays the raw transport error here."""
        rows = _rows(WATERMARK_QUERY, ("c",), database)
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

    # -- drift quarantine and reconciliation reads (NCR-C4-002, LLD v1.1 :148) ----------------

    def quarantine_record(self, fact_id: str) -> QuarantineRecord | None:
        """The durable quarantine of an aggregate, or ``None`` when it is not quarantined."""
        return self._quarantine.active(self.store_id, _require_value("fact_id", fact_id))

    def is_quarantined(self, fact_id: str) -> bool:
        return self.quarantine_record(fact_id) is not None

    def quarantine_fact(self, fact_id: str, *, canonical_commit: str, expected_digest: str,
                        served_digest: str) -> QuarantineRecord:
        return self._quarantine.quarantine(
            self.store_id, _require_value("fact_id", fact_id),
            canonical_commit=_require_value("canonical_commit", canonical_commit),
            expected_digest=_require_value("expected_digest", expected_digest),
            served_digest=_require_value("served_digest", served_digest), at=self._clock())

    def release_fact(self, fact_id: str) -> None:
        self._quarantine.release(self.store_id, _require_value("fact_id", fact_id))

    def _reconciliation(self, read: Callable[[], T]) -> T:
        try:
            return read()
        except C2Error:
            raise
        except _ANSWER_FAILURES as exc:
            if _unreachable(exc):
                raise TypeDBUnavailableError("the TypeDB projection is unreachable",
                                             confirmed=self._confirmed()) from exc
            raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the TypeDB projection did not return a well-formed answer") from exc

    def reconciliation_digest(self, fact_id: str) -> str | None:
        """The digest of the payload the projection holds for an aggregate, whether or not it is
        quarantined, or ``None`` when it holds none: the drift detector's comparison, never served."""
        fact_id = _require_value("fact_id", fact_id)
        _, found = self._reconciliation(lambda: self._served_fact(fact_id))
        if found is None:
            return None
        return "urn:sha256:" + hashlib.sha256(found[1].encode("utf-8")).hexdigest()

    def projected_facts(self) -> list[tuple[str, str, int, str]]:
        """Every projected fact as ``(fact_id, commit_id, sequence, payload)`` in commit order: what
        a checkpoint records. A fact whose commit is not ordered on the branch is refused."""
        def read() -> list[tuple[str, str, int, str]]:
            facts = _rows("match $f isa c4-fact, has c4-fact-id $fid, has c4-commit-id $c, has c4-payload $p;",
                          ("fid", "c", "p"))
            order = _rows("match $o isa c4-commit-order, has c4-commit-id $c, has c4-commit-seq $s;", ("c", "s"))
            positions = {_text_value(row["c"]): _position_value(row["s"]) for row in order}
            result = []
            for row in facts:
                commit = _text_value(row["c"])
                if commit not in positions:
                    raise TypeDBAdapterError("a projected fact has a commit that is not ordered on the branch")
                result.append((_text_value(row["fid"]), commit, positions[commit], _text_value(row["p"])))
            return sorted(result, key=lambda fact: fact[2])
        return self._reconciliation(read)

    def _enforce_quarantine(self, request: NamedQueryRequest, fact_id: str) -> None:
        """LLD v1.1 :148: a quarantined aggregate is never served, whatever the consistency mode."""
        try:
            record = self._quarantine.active(self.store_id, fact_id)
        except WatermarkLedgerError as exc:
            raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the C4 drift quarantine is unavailable") from exc
        if record is not None:
            raise self._not_ready(request, "the aggregate is quarantined pending reconciliation")

    def _lookup_fact(self, fact_id: str) -> tuple[str, str] | None:
        rows = read_rows(
            f"match $f isa c4-fact, has c4-fact-id {_literal(fact_id)}, "
            f"has c4-commit-id $c, has c4-payload $p;",
            ("c", "p"),
        )
        if not rows:
            return None
        return _text_value(rows[0]["c"]), _text_value(rows[0]["p"])

    def _served_fact(self, fact_id: str, database: str | None = None) -> tuple[str | None, tuple[str, str] | None]:
        """The watermark and the fact, read with the raw transport failure preserved."""
        watermark = self._watermark(database)
        rows = _rows(f"match $f isa c4-fact, has c4-fact-id {_literal(fact_id)}, "
                     f"has c4-commit-id $c, has c4-payload $p;", ("c", "p"), database)
        found = None if not rows else (_text_value(rows[0]["c"]), _text_value(rows[0]["p"]))
        return watermark, found

    def _overtaken(self, request: NamedQueryRequest, watermark: str | None) -> int | None:
        """The position of the commit an ``EXACT_AT_COMMIT`` request pins, when the projection
        has already moved beyond it on the branch; ``None`` otherwise."""
        consistency = request.consistency
        required = consistency.required_commit
        if consistency.mode is not ConsistencyMode.EXACT_AT_COMMIT or required is None or watermark is None:
            return None
        if required == watermark:
            return None
        required_position = self.position(BRANCH, required)
        current_position = self.position(BRANCH, watermark)
        if required_position is None or current_position is None or required_position >= current_position:
            return None
        return required_position

    def _sandbox_fact(self, request: NamedQueryRequest, fact_id: str, sequence: int) -> tuple[str | None, tuple[str, str] | None]:
        """The watermark and the fact of a sandbox at the pinned commit (BA-03, ADD v1.3 :356).
        An unavailable emulation is ``UNSUPPORTED_CAPABILITY``, never the later commit
        (ADD v1.3 :1366)."""
        required = request.consistency.required_commit
        assert required is not None  # an overtaken request pins a commit
        if self._sandbox is None:
            raise C2Error("UNSUPPORTED_CAPABILITY", "the EXACT_AT_COMMIT emulation is not available")
        try:
            with self._sandbox.open(required, sequence) as database:
                try:
                    return self._served_fact(fact_id, database)
                except C2Error:
                    raise
                except _ANSWER_FAILURES as exc:
                    raise C2Error("CONTROL_PLANE_UNAVAILABLE",
                                  "the TypeDB sandbox did not return a well-formed answer") from exc
        except SandboxUnavailableError as exc:
            raise C2Error("UNSUPPORTED_CAPABILITY", "the EXACT_AT_COMMIT emulation is not available") from exc

    def read(self, request: NamedQueryRequest) -> NamedQueryResponse:
        fact_id = request.parameters.get("fact_id")
        if not isinstance(fact_id, str) or not fact_id:
            raise C2Error("SCHEMA_VIOLATION", "fact_id parameter is required")
        if request.branch != BRANCH or request.scenario_id is not None:
            # a branch or a scenario the projection does not serve is never answered from main
            raise C2Error("UNSUPPORTED_CAPABILITY", "the projection does not serve the requested branch or scenario")
        self._enforce_quarantine(request, fact_id)
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
        sequence = self._overtaken(request, watermark)
        if sequence is not None:
            # EXACT_AT_COMMIT(Cn) behind the projection: answered from a sandbox at Cn
            watermark, found = self._sandbox_fact(request, fact_id, sequence)
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
