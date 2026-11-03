"""Durable C5 DLQ, quarantine, operator releases, subscriptions and checkpoints on PostgreSQL.

LLD v1.1 :161 (``PERMANENT`` -> immutable DLQ), :162 (``POLICY_DENIED`` -> non-disclosing
quarantine), :163 (``POISON`` -> partition quarantine and operator gate), :165 (the checkpoint
binds topic/partition/offset, schema registry digest, release and GCS); ADD v1.3 :2575 (the
consumer moves by ``subscription_id`` and opaque cursor). Every table is append-only: row
triggers reject ``UPDATE`` and ``DELETE`` and a statement trigger rejects ``TRUNCATE``, so a
dead letter, a quarantine record, a release or a checkpoint never changes once written. A
cursor is a random token naming a checkpoint row; it carries no position. A connection-level
failure is ``CONTROL_PLANE_UNAVAILABLE`` (callers fail closed); rows read back are checked.
"""

from __future__ import annotations

import re
import secrets
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .envelope import BackboneError, _freeze, thaw

SCHEMA_NAME = re.compile(r"[a-z_][a-z0-9_]{0,48}")
T = TypeVar("T")
TABLES = ("c5_dead_letter", "c5_quarantine", "c5_quarantine_release", "c5_subscription", "c5_checkpoint")

_DDL = """
CREATE SCHEMA IF NOT EXISTS {s};
CREATE TABLE IF NOT EXISTS {s}.c5_dead_letter (
  dead_letter_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, topic TEXT NOT NULL, tenant_id TEXT NOT NULL,
  failure_class TEXT NOT NULL CHECK (failure_class = 'PERMANENT'), reason_code TEXT NOT NULL,
  envelope JSONB NOT NULL, signature BYTEA, attempt INTEGER NOT NULL CHECK (attempt >= 1),
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS c5_dead_letter_event ON {s}.c5_dead_letter (event_id);
CREATE TABLE IF NOT EXISTS {s}.c5_quarantine (
  quarantine_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, topic TEXT NOT NULL,
  failure_class TEXT NOT NULL CHECK (failure_class IN ('POLICY_DENIED', 'POISON')), reason_code TEXT NOT NULL,
  subscription_id TEXT, journal_partition INTEGER, journal_offset BIGINT,
  envelope JSONB, signature BYTEA, recorded_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS {s}.c5_quarantine_release (
  quarantine_id TEXT PRIMARY KEY REFERENCES {s}.c5_quarantine (quarantine_id),
  released_by TEXT NOT NULL, authority_ref TEXT NOT NULL, reason TEXT NOT NULL,
  released_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS {s}.c5_subscription (
  subscription_id TEXT PRIMARY KEY, principal TEXT NOT NULL, contract JSONB NOT NULL, topic TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS {s}.c5_checkpoint (
  cursor_id TEXT PRIMARY KEY, subscription_id TEXT NOT NULL REFERENCES {s}.c5_subscription (subscription_id),
  topic TEXT NOT NULL, positions JSONB NOT NULL, end_positions JSONB,
  window_start TIMESTAMPTZ, window_end TIMESTAMPTZ, replay_reason TEXT,
  schema_registry_digest TEXT NOT NULL, release_digest TEXT NOT NULL, governed_context_digest TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE OR REPLACE FUNCTION {s}.c5_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'C5 records are append-only'; END $$;
"""
_UNAVAILABLE = (psycopg.OperationalError, psycopg.InterfaceError)


def _unavailable(message: str) -> BackboneError:
    return BackboneError("CONTROL_PLANE_UNAVAILABLE", message, failure_class="TRANSIENT")


@dataclass(frozen=True, slots=True)
class DeadLetter:
    """An immutable dead letter (LLD v1.1 :161); ``envelope`` is deeply read-only."""

    dead_letter_id: str
    event_id: str
    failure_class: str
    reason_code: str
    envelope: Mapping[str, Any]
    attempt: int
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    quarantine_id: str
    event_id: str
    failure_class: str
    reason_code: str
    subscription_id: str | None
    partition: int | None
    offset: int | None
    released: bool


@dataclass(frozen=True, slots=True)
class Checkpoint:
    cursor_id: str
    subscription_id: str
    topic: str
    positions: Mapping[int, int]
    end_positions: Mapping[int, int] | None
    window_start: datetime | None
    window_end: datetime | None
    schema_registry_digest: str
    release_digest: str
    governed_context_digest: str


def _positions(value: object) -> dict[int, int]:
    if not isinstance(value, dict):
        raise _unavailable("a stored checkpoint position map is malformed")
    result = {}
    for key, offset in value.items():
        if not isinstance(key, str) or not key.isdigit() or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise _unavailable("a stored checkpoint position is malformed")
        result[int(key)] = offset
    return result


def _text(row: Mapping[str, Any], column: str) -> str:
    value = row.get(column)
    if not isinstance(value, str) or not value:
        raise _unavailable(f"a stored C5 record has a malformed {column}")
    return value


class PostgresC5Store:
    """The durable C5 store; ``schema`` isolates one deployment (or one test)."""

    def __init__(self, dsn: str, *, schema: str = "ocor_c5", connect_timeout: int = 5) -> None:
        if not isinstance(dsn, str) or not dsn:
            raise ValueError("a PostgreSQL DSN is required")
        if not isinstance(schema, str) or SCHEMA_NAME.fullmatch(schema) is None:
            raise ValueError("invalid C5 schema name")
        self._dsn = dsn
        self._schema = schema
        self._timeout = connect_timeout

    def __repr__(self) -> str:
        return f"PostgresC5Store(schema={self._schema!r})"

    def _run(self, work: Callable[[psycopg.Connection[dict[str, Any]]], T]) -> T:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row, connect_timeout=self._timeout) as connection:
                with connection.transaction():
                    return work(connection)
        except _UNAVAILABLE as exc:
            raise _unavailable(f"C5 store unavailable: {type(exc).__name__}") from exc
        except psycopg.Error as exc:
            raise _unavailable(f"C5 store operation failed: {type(exc).__name__}") from exc

    def initialize(self) -> None:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> None:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (self._schema + "/c5-ddl",))
            connection.execute(_DDL.format(s=self._schema))
            for table in TABLES:
                for suffix, timing, granularity in (
                    ("no_change", "BEFORE UPDATE OR DELETE", "FOR EACH ROW"),
                    ("no_truncate", "BEFORE TRUNCATE", "FOR EACH STATEMENT"),
                ):
                    name = f"{table}_{suffix}"
                    exists = connection.execute(
                        "SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE t.tgname = %s AND n.nspname = %s AND c.relname = %s",
                        (name, self._schema, table),
                    ).fetchone()
                    if exists is None:
                        connection.execute(
                            f"CREATE TRIGGER {name} {timing} ON {self._schema}.{table} "
                            f"{granularity} EXECUTE FUNCTION {self._schema}.c5_append_only()"
                        )

        self._run(work)

    # -- DLQ and quarantine -------------------------------------------------------------------

    def record_dead_letter(
        self, *, event_id: str, topic: str, tenant_id: str, reason_code: str, envelope: Mapping[str, Any],
        signature: bytes | None,
    ) -> DeadLetter:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> DeadLetter:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (self._schema + "/dl/" + event_id,))
            row = connection.execute(
                f"SELECT count(*) AS n FROM {self._schema}.c5_dead_letter WHERE event_id = %s", (event_id,)
            ).fetchone()
            attempt = int((row or {}).get("n", 0)) + 1
            dead_letter_id = str(uuid.uuid4())
            stored = connection.execute(
                f"INSERT INTO {self._schema}.c5_dead_letter (dead_letter_id, event_id, topic, tenant_id, failure_class, "
                "reason_code, envelope, signature, attempt) VALUES (%s, %s, %s, %s, 'PERMANENT', %s, %s, %s, %s) "
                "RETURNING recorded_at",
                (dead_letter_id, event_id, topic, tenant_id, reason_code, Jsonb(thaw(envelope)), signature, attempt),
            ).fetchone()
            recorded_at = (stored or {}).get("recorded_at")
            if not isinstance(recorded_at, datetime):
                raise _unavailable("the C5 store did not confirm the dead letter")
            return DeadLetter(dead_letter_id, event_id, "PERMANENT", reason_code, _freeze(thaw(envelope)), attempt, recorded_at)

        return self._run(work)

    def dead_letters(self, topic: str) -> tuple[DeadLetter, ...]:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> tuple[DeadLetter, ...]:
            rows = connection.execute(
                f"SELECT * FROM {self._schema}.c5_dead_letter WHERE topic = %s ORDER BY recorded_at, dead_letter_id",
                (topic,),
            ).fetchall()
            result = []
            for row in rows:
                envelope, attempt, recorded_at = row.get("envelope"), row.get("attempt"), row.get("recorded_at")
                if not isinstance(envelope, dict) or isinstance(attempt, bool) or not isinstance(attempt, int):
                    raise _unavailable("a stored dead letter is malformed")
                if not isinstance(recorded_at, datetime):
                    raise _unavailable("a stored dead letter time is malformed")
                result.append(
                    DeadLetter(
                        _text(row, "dead_letter_id"), _text(row, "event_id"), _text(row, "failure_class"),
                        _text(row, "reason_code"), _freeze(envelope), attempt, recorded_at,
                    )
                )
            return tuple(result)

        return self._run(work)

    def quarantine(
        self, *, event_id: str, topic: str, failure_class: str, reason_code: str,
        envelope: Mapping[str, Any] | None, signature: bytes | None,
        subscription_id: str | None = None, partition: int | None = None, offset: int | None = None,
    ) -> str:
        quarantine_id = str(uuid.uuid4())

        def work(connection: psycopg.Connection[dict[str, Any]]) -> str:
            connection.execute(
                f"INSERT INTO {self._schema}.c5_quarantine (quarantine_id, event_id, topic, failure_class, reason_code, "
                "subscription_id, journal_partition, journal_offset, envelope, signature) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    quarantine_id, event_id, topic, failure_class, reason_code, subscription_id, partition, offset,
                    None if envelope is None else Jsonb(thaw(envelope)), signature,
                ),
            )
            return quarantine_id

        return self._run(work)

    def quarantined(self, topic: str) -> tuple[QuarantineRecord, ...]:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> tuple[QuarantineRecord, ...]:
            rows = connection.execute(
                f"SELECT q.*, r.quarantine_id IS NOT NULL AS released FROM {self._schema}.c5_quarantine q "
                f"LEFT JOIN {self._schema}.c5_quarantine_release r USING (quarantine_id) "
                "WHERE q.topic = %s ORDER BY q.recorded_at, q.quarantine_id",
                (topic,),
            ).fetchall()
            result = []
            for row in rows:
                partition, offset = row.get("journal_partition"), row.get("journal_offset")
                for value in (partition, offset):
                    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                        raise _unavailable("a stored quarantine position is malformed")
                subscription = row.get("subscription_id")
                if subscription is not None and not isinstance(subscription, str):
                    raise _unavailable("a stored quarantine subscription is malformed")
                result.append(
                    QuarantineRecord(
                        _text(row, "quarantine_id"), _text(row, "event_id"), _text(row, "failure_class"),
                        _text(row, "reason_code"), subscription, partition, offset, row.get("released") is True,
                    )
                )
            return tuple(result)

        return self._run(work)

    def release(self, quarantine_id: str, *, released_by: str, authority_ref: str, reason: str) -> None:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> None:
            exists = connection.execute(
                f"SELECT failure_class FROM {self._schema}.c5_quarantine WHERE quarantine_id = %s", (quarantine_id,)
            ).fetchone()
            if exists is None:
                raise BackboneError("QUARANTINE_NOT_FOUND", "no such quarantine record", failure_class="PERMANENT")
            connection.execute(
                f"INSERT INTO {self._schema}.c5_quarantine_release (quarantine_id, released_by, authority_ref, reason) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (quarantine_id) DO NOTHING",
                (quarantine_id, released_by, authority_ref, reason),
            )

        self._run(work)

    # -- Subscribe ------------------------------------------------------------------------------

    def create_subscription(self, *, principal: str, contract: Mapping[str, Any], topic: str) -> str:
        subscription_id = "urn:ocor:subscription:" + str(uuid.uuid4())

        def work(connection: psycopg.Connection[dict[str, Any]]) -> str:
            connection.execute(
                f"INSERT INTO {self._schema}.c5_subscription (subscription_id, principal, contract, topic) "
                "VALUES (%s, %s, %s, %s)",
                (subscription_id, principal, Jsonb(thaw(contract)), topic),
            )
            return subscription_id

        return self._run(work)

    def subscription(self, subscription_id: str) -> tuple[str, dict[str, Any], str] | None:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> tuple[str, dict[str, Any], str] | None:
            row = connection.execute(
                f"SELECT principal, contract, topic FROM {self._schema}.c5_subscription WHERE subscription_id = %s",
                (subscription_id,),
            ).fetchone()
            if row is None:
                return None
            contract = row.get("contract")
            if not isinstance(contract, dict):
                raise _unavailable("a stored subscription contract is malformed")
            return _text(row, "principal"), contract, _text(row, "topic")

        return self._run(work)

    def save_checkpoint(
        self, *, subscription_id: str, topic: str, positions: Mapping[int, int], end_positions: Mapping[int, int] | None,
        window_start: datetime | None, window_end: datetime | None, replay_reason: str | None,
        schema_registry_digest: str, release_digest: str, governed_context_digest: str,
    ) -> str:
        cursor_id = secrets.token_urlsafe(32)

        def work(connection: psycopg.Connection[dict[str, Any]]) -> str:
            connection.execute(
                f"INSERT INTO {self._schema}.c5_checkpoint (cursor_id, subscription_id, topic, positions, end_positions, "
                "window_start, window_end, replay_reason, schema_registry_digest, release_digest, governed_context_digest) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    cursor_id, subscription_id, topic, Jsonb({str(k): v for k, v in positions.items()}),
                    None if end_positions is None else Jsonb({str(k): v for k, v in end_positions.items()}),
                    window_start, window_end, replay_reason, schema_registry_digest, release_digest,
                    governed_context_digest,
                ),
            )
            return cursor_id

        return self._run(work)

    def checkpoint(self, cursor_id: str) -> Checkpoint | None:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> Checkpoint | None:
            row = connection.execute(
                f"SELECT * FROM {self._schema}.c5_checkpoint WHERE cursor_id = %s", (cursor_id,)
            ).fetchone()
            if row is None:
                return None
            end = row.get("end_positions")
            window = [row.get("window_start"), row.get("window_end")]
            for moment in window:
                if moment is not None and not isinstance(moment, datetime):
                    raise _unavailable("a stored checkpoint window is malformed")
            release = row.get("release_digest")
            if not isinstance(release, str):
                raise _unavailable("a stored checkpoint release is malformed")
            return Checkpoint(
                _text(row, "cursor_id"), _text(row, "subscription_id"), _text(row, "topic"),
                _positions(row.get("positions")), None if end is None else _positions(end),
                window[0], window[1], _text(row, "schema_registry_digest"), release,
                _text(row, "governed_context_digest"),
            )

        return self._run(work)


def utc_now() -> datetime:
    return datetime.now(UTC)
