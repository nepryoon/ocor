"""The C4 watermark ledger on PostgreSQL (``WatermarkLedgerPort``, ``ocor_runtime.c4.watermark``).

OCOR-DEV-REM-0052 (NCP-U05). Two tables per schema: ``c4_commit_observed`` (a commit delivered
to the projector, once per ``(store, branch, commit)``) and ``c4_watermark_confirmed`` (a
watermark the projection reached, once per ``(store, branch, commit)`` and once per
``(store, branch, sequence)``). Every write of a ``(store, branch)`` runs under one
transaction-scoped advisory lock, so a confirmation is checked against the latest one and
the ledger never moves backwards (LLD v1.1 :355). A connection-level failure, or a row read
back that is not well formed (text non-empty, digests SHA-256 URNs, sequence a positive integer and never ``bool``,
instants timezone-aware), is ``CONTROL_PLANE_UNAVAILABLE``: callers fail closed
(PRE-REVIEW-INPUT-ROBUSTNESS (2026-10-29)).

OCOR-DEV-REM-0052 (NCR-C4-002): the same store keeps, outside the projection store, the durable
drift quarantine (``ProjectionQuarantinePort``, table ``c4_quarantine``, one row per quarantined
aggregate) and the signed projection checkpoints (``CheckpointStorePort``, table
``c4_checkpoint``, append-only) of ``ocor_runtime.c4.drift`` (LLD v1.1 :148).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, TypeVar

import psycopg
from psycopg.rows import dict_row

from ...kernel.canonical import DIGEST
from ..drift import QuarantineRecord, SignedProjectionCheckpoint
from ..watermark import ConfirmedWatermark, WatermarkLedgerError

SCHEMA_NAME = re.compile(r"[a-z_][a-z0-9_]{0,48}")
T = TypeVar("T")

_DDL = """
CREATE SCHEMA IF NOT EXISTS {s};
CREATE TABLE IF NOT EXISTS {s}.c4_commit_observed (
  store_id TEXT NOT NULL, branch TEXT NOT NULL, commit_id TEXT NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (store_id, branch, commit_id));
CREATE TABLE IF NOT EXISTS {s}.c4_watermark_confirmed (
  store_id TEXT NOT NULL, branch TEXT NOT NULL, commit_id TEXT NOT NULL,
  sequence BIGINT NOT NULL CHECK (sequence >= 1), release_digest TEXT NOT NULL,
  confirmed_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (store_id, branch, commit_id),
  UNIQUE (store_id, branch, sequence));
CREATE TABLE IF NOT EXISTS {s}.c4_quarantine (
  store_id TEXT NOT NULL, aggregate_ref TEXT NOT NULL, canonical_commit TEXT NOT NULL,
  expected_digest TEXT NOT NULL, served_digest TEXT NOT NULL, quarantined_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (store_id, aggregate_ref));
CREATE TABLE IF NOT EXISTS {s}.c4_checkpoint (
  checkpoint_no BIGSERIAL PRIMARY KEY, store_id TEXT NOT NULL, key_id TEXT NOT NULL,
  payload BYTEA NOT NULL, signature BYTEA NOT NULL, saved_at TIMESTAMPTZ NOT NULL);
"""
_UNAVAILABLE = (psycopg.OperationalError, psycopg.InterfaceError)


def _unavailable(message: str) -> WatermarkLedgerError:
    return WatermarkLedgerError("CONTROL_PLANE_UNAVAILABLE", message)


def _text(row: Mapping[str, Any], column: str) -> str:
    value = row.get(column)
    if not isinstance(value, str) or not value:
        raise _unavailable(f"a stored C4 ledger row has a malformed {column}")
    return value


def _digest(row: Mapping[str, Any], column: str) -> str:
    """A stored digest is a SHA-256 URN as written (ADD v1.3 :398): a tampered one fails closed."""
    value = _text(row, column)
    if DIGEST.fullmatch(value) is None:
        raise _unavailable(f"a stored C4 ledger row has a malformed {column}")
    return value


def _moment(value: object, what: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _unavailable(f"a stored C4 ledger row has a malformed {what}")
    return value


def _sequence(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _unavailable("a stored C4 ledger row has a malformed sequence")
    return value


def _required(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} is required")
    return value


def _at(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("the instant must be timezone-aware")
    return value


def _confirmed(row: Mapping[str, Any]) -> ConfirmedWatermark:
    return ConfirmedWatermark(
        store_id=_text(row, "store_id"),
        branch=_text(row, "branch"),
        commit_id=_text(row, "commit_id"),
        sequence=_sequence(row.get("sequence")),
        release_digest=_digest(row, "release_digest"),
        confirmed_at=_moment(row.get("confirmed_at"), "confirmed_at"),
    )


def _quarantined(row: Mapping[str, Any]) -> QuarantineRecord:
    return QuarantineRecord(
        store_id=_text(row, "store_id"),
        aggregate_ref=_text(row, "aggregate_ref"),
        canonical_commit=_text(row, "canonical_commit"),
        expected_digest=_digest(row, "expected_digest"),
        served_digest=_digest(row, "served_digest"),
        quarantined_at=_moment(row.get("quarantined_at"), "quarantined_at"),
    )


def _blob(row: Mapping[str, Any], column: str) -> bytes:
    value = row.get(column)
    if isinstance(value, memoryview):
        value = value.tobytes()
    if not isinstance(value, bytes) or not value:
        raise _unavailable(f"a stored C4 checkpoint has a malformed {column}")
    return value


class PostgresWatermarkLedger:
    """The durable C4 watermark ledger, drift quarantine and checkpoint store; ``schema``
    isolates one deployment (or one test)."""

    def __init__(self, dsn: str, *, schema: str = "ocor_c4", connect_timeout: int = 5) -> None:
        if not isinstance(dsn, str) or not dsn:
            raise ValueError("a PostgreSQL DSN is required")
        if not isinstance(schema, str) or SCHEMA_NAME.fullmatch(schema) is None:
            raise ValueError("invalid C4 schema name")
        self._dsn = dsn
        self._schema = schema
        self._timeout = connect_timeout

    def __repr__(self) -> str:
        return f"PostgresWatermarkLedger(schema={self._schema!r})"

    def _run(self, work: Callable[[psycopg.Connection[dict[str, Any]]], T]) -> T:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row, connect_timeout=self._timeout) as connection:
                with connection.transaction():
                    return work(connection)
        except _UNAVAILABLE as exc:
            raise _unavailable(f"C4 ledger unavailable: {type(exc).__name__}") from exc
        except psycopg.Error as exc:
            raise _unavailable(f"C4 ledger operation failed: {type(exc).__name__}") from exc

    def _lock(self, connection: psycopg.Connection[dict[str, Any]], store_id: str, branch: str) -> None:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                           (f"{self._schema}/c4-ledger/{store_id}/{branch}",))

    def initialize(self) -> None:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> None:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (self._schema + "/c4-ddl",))
            connection.execute(_DDL.format(s=self._schema))

        self._run(work)

    def observe(self, store_id: str, branch: str, commit_id: str, *, at: datetime) -> None:
        values = (_required("store_id", store_id), _required("branch", branch), _required("commit_id", commit_id), _at(at))

        def work(connection: psycopg.Connection[dict[str, Any]]) -> None:
            connection.execute(
                f"INSERT INTO {self._schema}.c4_commit_observed (store_id, branch, commit_id, observed_at) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", values)

        self._run(work)

    def confirm(
        self, store_id: str, branch: str, commit_id: str, *, sequence: int, release_digest: str, at: datetime
    ) -> ConfirmedWatermark:
        store_id, branch = _required("store_id", store_id), _required("branch", branch)
        commit_id, release_digest = _required("commit_id", commit_id), _required("release_digest", release_digest)
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("sequence must be a positive integer")
        moment = _at(at)

        def work(connection: psycopg.Connection[dict[str, Any]]) -> ConfirmedWatermark:
            self._lock(connection, store_id, branch)
            existing = connection.execute(
                f"SELECT * FROM {self._schema}.c4_watermark_confirmed WHERE store_id = %s AND branch = %s "
                "AND commit_id = %s", (store_id, branch, commit_id)).fetchone()
            if existing is not None:
                found = _confirmed(existing)
                if (found.sequence, found.release_digest) != (sequence, release_digest):
                    raise WatermarkLedgerError("WATERMARK_REGRESSION", "the commit is confirmed at another position")
                return found
            latest = self._latest(connection, store_id, branch)
            if latest is not None and sequence <= latest.sequence:
                raise WatermarkLedgerError("WATERMARK_REGRESSION", "the confirmation would move the watermark backwards")
            stored = connection.execute(
                f"INSERT INTO {self._schema}.c4_watermark_confirmed (store_id, branch, commit_id, sequence, "
                "release_digest, confirmed_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
                (store_id, branch, commit_id, sequence, release_digest, moment)).fetchone()
            if stored is None:
                raise _unavailable("the C4 ledger did not return the confirmation")
            return _confirmed(stored)

        return self._run(work)

    def _latest(self, connection: psycopg.Connection[dict[str, Any]], store_id: str, branch: str) -> ConfirmedWatermark | None:
        row = connection.execute(
            f"SELECT * FROM {self._schema}.c4_watermark_confirmed WHERE store_id = %s AND branch = %s "
            "ORDER BY sequence DESC LIMIT 1", (store_id, branch)).fetchone()
        return None if row is None else _confirmed(row)

    def latest(self, store_id: str, branch: str) -> ConfirmedWatermark | None:
        store_id, branch = _required("store_id", store_id), _required("branch", branch)
        return self._run(lambda connection: self._latest(connection, store_id, branch))

    def pending_since(self, store_id: str, branch: str) -> datetime | None:
        """The earliest instant of a received commit that the projection has not confirmed."""
        store_id, branch = _required("store_id", store_id), _required("branch", branch)

        def work(connection: psycopg.Connection[dict[str, Any]]) -> datetime | None:
            row = connection.execute(
                f"SELECT min(o.observed_at) AS since FROM {self._schema}.c4_commit_observed o "
                f"WHERE o.store_id = %s AND o.branch = %s AND NOT EXISTS (SELECT 1 FROM "
                f"{self._schema}.c4_watermark_confirmed c WHERE c.store_id = o.store_id AND c.branch = o.branch "
                "AND c.commit_id = o.commit_id)", (store_id, branch)).fetchone()
            since = None if row is None else row.get("since")
            return None if since is None else _moment(since, "observed_at")

        return self._run(work)

    def clear(self, store_id: str) -> None:
        """Removes every row of one store: the ledger of a projection that is reset or rebuilt."""
        store_id = _required("store_id", store_id)

        def work(connection: psycopg.Connection[dict[str, Any]]) -> None:
            connection.execute(f"DELETE FROM {self._schema}.c4_commit_observed WHERE store_id = %s", (store_id,))
            connection.execute(f"DELETE FROM {self._schema}.c4_watermark_confirmed WHERE store_id = %s", (store_id,))

        self._run(work)

    # -- ProjectionQuarantinePort (NCR-C4-002) ---------------------------------------------

    def quarantine(self, store_id: str, aggregate_ref: str, *, canonical_commit: str, expected_digest: str,
                   served_digest: str, at: datetime) -> QuarantineRecord:
        """Quarantines an aggregate; an aggregate already quarantined keeps its first record."""
        values = (_required("store_id", store_id), _required("aggregate_ref", aggregate_ref),
                  _required("canonical_commit", canonical_commit), _required("expected_digest", expected_digest),
                  _required("served_digest", served_digest), _at(at))

        def work(connection: psycopg.Connection[dict[str, Any]]) -> QuarantineRecord:
            connection.execute(
                f"INSERT INTO {self._schema}.c4_quarantine (store_id, aggregate_ref, canonical_commit, "
                "expected_digest, served_digest, quarantined_at) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING", values)
            row = connection.execute(
                f"SELECT * FROM {self._schema}.c4_quarantine WHERE store_id = %s AND aggregate_ref = %s",
                values[:2]).fetchone()
            if row is None:
                raise _unavailable("the C4 quarantine did not return the record")
            return _quarantined(row)

        return self._run(work)

    def release(self, store_id: str, aggregate_ref: str) -> None:
        values = (_required("store_id", store_id), _required("aggregate_ref", aggregate_ref))
        self._run(lambda connection: connection.execute(
            f"DELETE FROM {self._schema}.c4_quarantine WHERE store_id = %s AND aggregate_ref = %s", values))

    def active(self, store_id: str, aggregate_ref: str) -> QuarantineRecord | None:
        values = (_required("store_id", store_id), _required("aggregate_ref", aggregate_ref))

        def work(connection: psycopg.Connection[dict[str, Any]]) -> QuarantineRecord | None:
            row = connection.execute(
                f"SELECT * FROM {self._schema}.c4_quarantine WHERE store_id = %s AND aggregate_ref = %s",
                values).fetchone()
            return None if row is None else _quarantined(row)

        return self._run(work)

    def clear_quarantine(self, store_id: str) -> None:
        """Removes the quarantine of a projection that is reset: its facts are gone."""
        store_id = _required("store_id", store_id)
        self._run(lambda connection: connection.execute(
            f"DELETE FROM {self._schema}.c4_quarantine WHERE store_id = %s", (store_id,)))

    # -- CheckpointStorePort (NCR-C4-002) ---------------------------------------------------

    def save_checkpoint(self, store_id: str, checkpoint: SignedProjectionCheckpoint, *, at: datetime) -> None:
        store_id = _required("store_id", store_id)
        if not isinstance(checkpoint, SignedProjectionCheckpoint):
            raise ValueError("a SignedProjectionCheckpoint is required")
        values = (store_id, _required("key_id", checkpoint.key_id), checkpoint.payload, checkpoint.signature, _at(at))
        self._run(lambda connection: connection.execute(
            f"INSERT INTO {self._schema}.c4_checkpoint (store_id, key_id, payload, signature, saved_at) "
            "VALUES (%s, %s, %s, %s, %s)", values))

    def latest_checkpoint(self, store_id: str) -> SignedProjectionCheckpoint | None:
        """The last checkpoint saved for the store; it is verified by its user, never here."""
        store_id = _required("store_id", store_id)

        def work(connection: psycopg.Connection[dict[str, Any]]) -> SignedProjectionCheckpoint | None:
            row = connection.execute(
                f"SELECT * FROM {self._schema}.c4_checkpoint WHERE store_id = %s ORDER BY checkpoint_no DESC LIMIT 1",
                (store_id,)).fetchone()
            if row is None:
                return None
            return SignedProjectionCheckpoint(payload=_blob(row, "payload"), key_id=_text(row, "key_id"),
                                              signature=_blob(row, "signature"))

        return self._run(work)
