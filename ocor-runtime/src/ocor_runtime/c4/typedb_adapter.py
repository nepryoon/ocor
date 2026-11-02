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
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from ..c2.ports import C2Error, NamedQueryRequest, NamedQueryResponse, ServedContext, Watermark

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
    pass


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
) -> tuple[int, str]:
    request = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def _token() -> str:
    status, body = _request(
        "POST",
        f"{TYPEDB_URL}/v1/signin",
        headers={"Content-Type": "application/json"},
        body=json.dumps({"username": "admin", "password": "password"}).encode("utf-8"),
    )
    if status != 200:
        raise TypeDBAdapterError(f"cannot sign in to TypeDB: {status} {body}")
    token: str = json.loads(body)["token"]
    return token


def _transaction(kind: str, token: str) -> str:
    status, body = _request(
        "POST",
        f"{TYPEDB_URL}/v1/transactions/open",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        body=json.dumps({"databaseName": DATABASE, "transactionType": kind}).encode("utf-8"),
    )
    if status != 200:
        raise TypeDBAdapterError(f"cannot open a TypeDB {kind} transaction: {status} {body}")
    transaction_id: str = json.loads(body)["transactionId"]
    return transaction_id


def _query(transaction_id: str, query: str, token: str) -> tuple[int, dict[str, Any]]:
    status, body = _request(
        "POST",
        f"{TYPEDB_URL}/v1/transactions/{transaction_id}/query",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        body=json.dumps({"query": query}).encode("utf-8"),
    )
    parsed: dict[str, Any] = json.loads(body) if body else {}
    return status, parsed


def _commit(transaction_id: str, token: str) -> None:
    status, body = _request(
        "POST", f"{TYPEDB_URL}/v1/transactions/{transaction_id}/commit", headers={"Authorization": f"Bearer {token}"}
    )
    if status != 200:
        raise TypeDBAdapterError(f"failed to commit TypeDB transaction: {status} {body}")


def _close(transaction_id: str, token: str) -> None:
    _request(
        "POST", f"{TYPEDB_URL}/v1/transactions/{transaction_id}/close", headers={"Authorization": f"Bearer {token}"}
    )


def _write(*queries: str) -> None:
    """Runs every query inside ONE real TypeDB write transaction,
    committed together or not at all -- the primitive ``apply_commit``
    relies on to make fact-ingest and watermark-advance atomic."""
    token = _token()
    transaction_id = _transaction("write", token)
    for query in queries:
        status, result = _query(transaction_id, query, token)
        if status != 200:
            _close(transaction_id, token)
            raise TypeDBAdapterError(f"write failed: {status} {result}")
    _commit(transaction_id, token)


def _schema_write(query: str) -> None:
    token = _token()
    transaction_id = _transaction("schema", token)
    status, result = _query(transaction_id, query, token)
    if status != 200:
        _close(transaction_id, token)
        raise TypeDBAdapterError(f"schema write failed: {status} {result}")
    _commit(transaction_id, token)


def _read(query: str) -> list[dict[str, Any]]:
    token = _token()
    transaction_id = _transaction("read", token)
    status, result = _query(transaction_id, query, token)
    _close(transaction_id, token)
    if status != 200:
        raise TypeDBAdapterError(f"read failed: {status} {result}")
    answers = result.get("answers") or []
    return list(answers)


def _ensure_database() -> None:
    token = _token()
    status, body = _request("GET", f"{TYPEDB_URL}/v1/databases", headers={"Authorization": f"Bearer {token}"})
    if status != 200:
        raise TypeDBAdapterError(f"cannot list TypeDB databases: {status} {body}")
    existing = {entry["name"] for entry in json.loads(body).get("databases", [])}
    if DATABASE in existing:
        return
    status, body = _request(
        "POST", f"{TYPEDB_URL}/v1/databases/{DATABASE}", headers={"Authorization": f"Bearer {token}"}
    )
    if status != 200:
        raise TypeDBAdapterError(f"failed to create TypeDB database {DATABASE!r}: {status} {body}")


class TypeDBProjectionAdapter:
    """Retained C4 projection: real TypeDB-backed ``ProjectionReadPort``/
    ``WatermarkPort`` where every commit's fact and watermark advance
    together, atomically, in one real write transaction."""

    def initialize(self) -> None:
        _ensure_database()
        _schema_write(SCHEMA_QUERY)

    def reset(self) -> None:
        _write(
            "match $f isa c4-fact; delete $f;",
            "match $w isa c4-watermark; delete $w;",
            "match $o isa c4-commit-order; delete $o;",
        )

    def apply_commit(self, *, fact_id: str, commit_id: str, payload: str) -> None:
        """Ingests the fact and advances the watermark to ``commit_id``
        atomically: both statements commit together in one real
        transaction, or neither does. A prior fact with the same
        ``fact_id`` (a fact update) is replaced; a prior watermark is
        replaced with the new commit."""
        fact_id = _require_value("fact_id", fact_id)
        commit_id = _require_value("commit_id", commit_id)
        payload = _require_value("payload", payload)
        existing_fact = self._lookup_fact(fact_id)
        statements: list[str] = []
        if existing_fact is not None:
            statements.append(f"match $f isa c4-fact, has c4-fact-id {_literal(fact_id)}; delete $f;")
        statements.append(
            f"insert $f isa c4-fact, has c4-fact-id {_literal(fact_id)}, "
            f"has c4-commit-id {_literal(commit_id)}, has c4-payload {_literal(payload)};"
        )
        if self.current_watermark() is not None:
            statements.append("match $w isa c4-watermark; delete $w;")
        statements.append(f"insert $w isa c4-watermark, has c4-commit-id {_literal(commit_id)};")
        if self.position(BRANCH, commit_id) is None:
            # canonical order of the branch, recorded in the same transaction as the
            # watermark advance (FR-057 "branch/commit ordering", Register :179).
            statements.append(
                f"insert $o isa c4-commit-order, has c4-commit-id {_literal(commit_id)}, "
                f"has c4-commit-seq {self._next_sequence()};"
            )
        _write(*statements)

    def _next_sequence(self) -> int:
        rows = _read("match $o isa c4-commit-order, has c4-commit-seq $s;")
        return 1 + max((int(row["data"]["s"]["value"]) for row in rows), default=0)

    def position(self, branch: str, commit: str) -> int | None:
        """``CommitOrderingPort``: the position of ``commit`` among the commits applied
        to ``branch``, or ``None`` when it has not landed (or on another branch)."""
        if branch != BRANCH or not isinstance(commit, str) or not commit:
            return None
        rows = _read(f"match $o isa c4-commit-order, has c4-commit-id {_literal(commit)}, has c4-commit-seq $s;")
        if not rows:
            return None
        return int(rows[0]["data"]["s"]["value"])

    def current_watermark(self) -> str | None:
        rows = _read("match $w isa c4-watermark, has c4-commit-id $c;")
        if not rows:
            return None
        return str(rows[0]["data"]["c"]["value"])

    def _lookup_fact(self, fact_id: str) -> tuple[str, str] | None:
        rows = _read(
            f"match $f isa c4-fact, has c4-fact-id {_literal(fact_id)}, "
            f"has c4-commit-id $c, has c4-payload $p;"
        )
        if not rows:
            return None
        row = rows[0]["data"]
        return str(row["c"]["value"]), str(row["p"]["value"])

    def read(self, request: NamedQueryRequest) -> NamedQueryResponse:
        fact_id = request.parameters.get("fact_id")
        if not isinstance(fact_id, str) or not fact_id:
            raise C2Error("SCHEMA_VIOLATION", "fact_id parameter is required")
        watermark = self.current_watermark()
        found = self._lookup_fact(fact_id)
        # the served commit reflects the row actually read, never the
        # watermark by assumption -- verify_served (below) is what
        # independently proves the two agree before anything is
        # returned as exact.
        canonical_commit = found[0] if found is not None else (watermark or NO_WATERMARK_SENTINEL)
        served = ServedContext(
            branch=BRANCH,
            ontology_release_digest=request.governed_context.ontology_release_digest,
            canonical_commit=canonical_commit,
            projection_watermark=watermark or NO_WATERMARK_SENTINEL,
            staleness_ms=0,
            governed_context_digest=request.governed_context_digest,
            policy_bundle_digest=request.governed_context.policy_bundle_digest,
        )
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
        """The sealed ``WatermarkPort`` method -- unlike the spike's own
        convenience ``watermark()`` (which took no arguments and never
        actually satisfied the sealed Protocol's signature), this
        retained adapter conforms to ``WatermarkPort`` directly."""
        commit = self.current_watermark() or NO_WATERMARK_SENTINEL
        return Watermark(
            projection_id=projection_id,
            branch=branch,
            ontology_release_digest="urn:sha256:" + "0" * 64,
            canonical_commit=commit,
            observed_at=datetime.now(UTC),
        )
