"""PostgreSQL store of the signed stop epoch behind ``StopEpochPort`` (OCOR-DEV-REM-0054,
NCP-U08, NCR-C6-010).

The Emergency Control Plane appends one signed ``StopEpochRecord`` per transition (ADD v1.3
:3351, LLD v1.1 :328); readers on any process read the latest one (NORMATIVE-CONFORMANCE-PLAN
point 2 for NCP-U08: the stop epoch is durable and read through a port). The table is
append-only: row triggers reject ``UPDATE`` and ``DELETE`` and a statement trigger rejects
``TRUNCATE``. An append is a compare-and-set on the latest sequence under a transaction-scoped
advisory lock, and the sequence is the primary key, so two writers never both advance the same
state. A connection failure is ``STOP_EPOCH_UNAVAILABLE``; a row read back is untrusted and a
malformed one is ``STOP_EPOCH_SIGNATURE_INVALID``, never an empty store.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..safety import SafetyError, SignedStopEpoch

SCHEMA_NAME = re.compile(r"[a-z_][a-z0-9_]{0,48}")
T = TypeVar("T")

_DDL = """
CREATE SCHEMA IF NOT EXISTS {s};
CREATE TABLE IF NOT EXISTS {s}.stop_epoch (
  sequence BIGINT PRIMARY KEY CHECK (sequence >= 0), epoch BIGINT NOT NULL CHECK (epoch >= 0),
  signed JSONB NOT NULL, recorded_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE OR REPLACE FUNCTION {s}.stop_epoch_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'stop epoch records are append-only'; END $$;
"""
_TRIGGERS = (
    ("stop_epoch_no_change", "BEFORE UPDATE OR DELETE", "FOR EACH ROW"),
    ("stop_epoch_no_truncate", "BEFORE TRUNCATE", "FOR EACH STATEMENT"),
)
_UNAVAILABLE = (psycopg.OperationalError, psycopg.InterfaceError)


class StopEpochStoreError(SafetyError):
    """The stop epoch store cannot be reached or refused the operation: ``STOP_EPOCH_UNAVAILABLE``."""

    def __init__(self, message: str) -> None:
        super().__init__("STOP_EPOCH_UNAVAILABLE", message)


def _invalid(message: str) -> SafetyError:
    return SafetyError("STOP_EPOCH_SIGNATURE_INVALID", message)


class PostgresStopEpochStore:
    """``StopEpochPort`` on PostgreSQL; ``schema`` isolates one Emergency Control Plane."""

    def __init__(self, dsn: str, *, schema: str = "ocor_c6_stop", connect_timeout: int = 5) -> None:
        if not isinstance(dsn, str) or not dsn:
            raise ValueError("a PostgreSQL DSN is required")
        if not isinstance(schema, str) or SCHEMA_NAME.fullmatch(schema) is None:
            raise ValueError("invalid stop epoch schema name")
        if type(connect_timeout) is not int or connect_timeout <= 0:
            raise ValueError("connect_timeout must be a positive integer")
        self._dsn = dsn
        self._schema = schema
        self._timeout = connect_timeout

    def __repr__(self) -> str:
        return f"PostgresStopEpochStore(schema={self._schema!r})"

    @property
    def schema(self) -> str:
        return self._schema

    def _run(self, work: Callable[[psycopg.Connection[dict[str, Any]]], T]) -> T:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row, connect_timeout=self._timeout) as connection:
                with connection.transaction():
                    return work(connection)
        except _UNAVAILABLE as exc:
            raise StopEpochStoreError(f"stop epoch store unavailable: {type(exc).__name__}") from exc
        except psycopg.Error as exc:
            raise StopEpochStoreError(f"stop epoch store operation failed: {type(exc).__name__}") from exc

    def initialize(self) -> None:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> None:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (self._schema + "/ddl",))
            connection.execute(_DDL.format(s=self._schema))
            for name, timing, granularity in _TRIGGERS:
                exists = connection.execute(
                    "SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE t.tgname = %s AND n.nspname = %s AND c.relname = 'stop_epoch'",
                    (name, self._schema),
                ).fetchone()
                if exists is None:
                    connection.execute(
                        f"CREATE TRIGGER {name} {timing} ON {self._schema}.stop_epoch "
                        f"{granularity} EXECUTE FUNCTION {self._schema}.stop_epoch_append_only()"
                    )

        self._run(work)

    def drop(self) -> None:
        """Remove an isolated test store (schema-level, never row-level)."""
        self._run(lambda connection: connection.execute(f"DROP SCHEMA IF EXISTS {self._schema} CASCADE"))

    def latest(self) -> SignedStopEpoch | None:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> SignedStopEpoch | None:
            row = connection.execute(
                f"SELECT sequence, epoch, signed FROM {self._schema}.stop_epoch ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            return None if row is None else _signed(row)

        return self._run(work)

    def history(self) -> tuple[SignedStopEpoch, ...]:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> tuple[SignedStopEpoch, ...]:
            rows = connection.execute(
                f"SELECT sequence, epoch, signed FROM {self._schema}.stop_epoch ORDER BY sequence"
            ).fetchall()
            if not isinstance(rows, list):
                raise _invalid("the stop epoch store returned no row list")
            return tuple(_signed(row) for row in rows)

        return self._run(work)

    def append(self, signed: SignedStopEpoch, *, expected_sequence: int) -> bool:
        if not isinstance(signed, SignedStopEpoch):
            raise TypeError("the store keeps signed stop epochs only")
        if type(expected_sequence) is not int:
            raise TypeError("expected_sequence must be an integer")
        record = signed.record
        if record.sequence != expected_sequence + 1:
            return False
        document = signed.to_mapping()

        def work(connection: psycopg.Connection[dict[str, Any]]) -> bool:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (self._schema + "/append",))
            row = connection.execute(f"SELECT max(sequence) AS latest FROM {self._schema}.stop_epoch").fetchone()
            latest = _row(row).get("latest")
            current = -1 if latest is None else latest
            if type(current) is not int:
                raise _invalid("the stop epoch store returned a malformed sequence")
            if current != expected_sequence:
                return False
            connection.execute(
                f"INSERT INTO {self._schema}.stop_epoch (sequence, epoch, signed) VALUES (%s, %s, %s)",
                (record.sequence, record.epoch, Jsonb(document)),
            )
            return True

        return self._run(work)


def _row(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("the stop epoch store returned a malformed row")
    return value


def _signed(value: object) -> SignedStopEpoch:
    row = _row(value)
    try:
        signed = SignedStopEpoch.from_mapping(row.get("signed"))
    except (TypeError, ValueError) as error:
        raise _invalid("a stored stop epoch is malformed") from error
    if type(row.get("sequence")) is not int or type(row.get("epoch")) is not int:
        raise _invalid("a stored stop epoch has a malformed sequence or epoch")
    if (row["sequence"], row["epoch"]) != (signed.record.sequence, signed.record.epoch):
        raise _invalid("a stored stop epoch does not match its row")
    return signed
