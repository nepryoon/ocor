"""The C4 watermark ledger on PostgreSQL (``WatermarkLedgerPort``, ``ocor_runtime.c4.watermark``).

OCOR-DEV-REM-0052 (NCP-U05). Two tables per schema: ``c4_commit_observed`` (a commit delivered
to the projector, once per ``(store, branch, commit)``) and ``c4_watermark_confirmed`` (a
watermark the projection reached, once per ``(store, branch, commit)`` and once per
``(store, branch, sequence)``). Every write of a ``(store, branch)`` runs under one
transaction-scoped advisory lock, so a confirmation is checked against the latest one and
the ledger never moves backwards (LLD v1.1 :355). A connection-level failure, or a row read
back that is not well formed (text non-empty, sequence a positive integer and never ``bool``,
instants timezone-aware), is ``CONTROL_PLANE_UNAVAILABLE``: callers fail closed
(PRE-REVIEW-INPUT-ROBUSTNESS (2026-10-29)).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, TypeVar

import psycopg
from psycopg.rows import dict_row

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
"""
_UNAVAILABLE = (psycopg.OperationalError, psycopg.InterfaceError)


def _unavailable(message: str) -> WatermarkLedgerError:
    return WatermarkLedgerError("CONTROL_PLANE_UNAVAILABLE", message)


def _text(row: Mapping[str, Any], column: str) -> str:
    value = row.get(column)
    if not isinstance(value, str) or not value:
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
        release_digest=_text(row, "release_digest"),
        confirmed_at=_moment(row.get("confirmed_at"), "confirmed_at"),
    )


class PostgresWatermarkLedger:
    """The durable C4 watermark ledger; ``schema`` isolates one deployment (or one test)."""

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
