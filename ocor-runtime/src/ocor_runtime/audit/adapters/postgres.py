"""PostgreSQL audit store behind ``AuditPort`` (the only audit module importing psycopg).

The table is append-only: row triggers reject ``UPDATE`` and ``DELETE`` and a statement
trigger rejects ``TRUNCATE``. Appends to the chain are serialised with a
transaction-scoped advisory lock, so the chain has one predecessor per record. A
connection-level failure is ``AuditUnavailable``; rows read back are untrusted and are
type-checked before use.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

if TYPE_CHECKING:
    from .. import AuditEvent, AuditSigner, SealedAuditRecord

SCHEMA_NAME = re.compile(r"[a-z_][a-z0-9_]{0,48}")
T = TypeVar("T")

_DDL = """
CREATE SCHEMA IF NOT EXISTS {s};
CREATE TABLE IF NOT EXISTS {s}.audit_record (
  seq BIGSERIAL PRIMARY KEY, record JSONB NOT NULL, previous_hash TEXT NOT NULL,
  record_hash TEXT NOT NULL UNIQUE, signature TEXT NOT NULL, keyid TEXT NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE OR REPLACE FUNCTION {s}.audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit records are append-only'; END $$;
"""
_TRIGGERS = (
    ("audit_record_no_change", "BEFORE UPDATE OR DELETE", "FOR EACH ROW"),
    ("audit_record_no_truncate", "BEFORE TRUNCATE", "FOR EACH STATEMENT"),
)
_UNAVAILABLE = (psycopg.OperationalError, psycopg.InterfaceError)


class PostgresAuditLog:
    """``AuditPort`` on PostgreSQL; ``schema`` isolates one audit log."""

    def __init__(self, dsn: str, *, schema: str = "ocor_audit", signer: AuditSigner, connect_timeout: int = 5) -> None:
        if not isinstance(dsn, str) or not dsn:
            raise ValueError("a PostgreSQL DSN is required")
        if SCHEMA_NAME.fullmatch(schema) is None:
            raise ValueError("invalid audit schema name")
        self._dsn = dsn
        self._schema = schema
        self._signer = signer
        self._timeout = connect_timeout

    def __repr__(self) -> str:
        return f"PostgresAuditLog(schema={self._schema!r})"

    @property
    def schema(self) -> str:
        return self._schema

    def _run(self, work: Callable[[psycopg.Connection[dict[str, Any]]], T]) -> T:
        from .. import AuditUnavailable

        try:
            with psycopg.connect(self._dsn, row_factory=dict_row, connect_timeout=self._timeout) as connection:
                with connection.transaction():
                    return work(connection)
        except _UNAVAILABLE as exc:
            raise AuditUnavailable(f"audit store unavailable: {type(exc).__name__}") from exc
        except psycopg.Error as exc:
            raise AuditUnavailable(f"audit append failed: {type(exc).__name__}") from exc

    def initialize(self) -> None:
        def work(connection: psycopg.Connection[dict[str, Any]]) -> None:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (self._schema + "/ddl",))
            connection.execute(_DDL.format(s=self._schema))
            for name, timing, granularity in _TRIGGERS:
                exists = connection.execute(
                    "SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE t.tgname = %s AND n.nspname = %s AND c.relname = 'audit_record'",
                    (name, self._schema),
                ).fetchone()
                if exists is None:
                    connection.execute(
                        f"CREATE TRIGGER {name} {timing} ON {self._schema}.audit_record "
                        f"{granularity} EXECUTE FUNCTION {self._schema}.audit_append_only()"
                    )

        self._run(work)

    def drop(self) -> None:
        """Remove an isolated test log (schema-level, never row-level)."""
        self._run(lambda connection: connection.execute(f"DROP SCHEMA IF EXISTS {self._schema} CASCADE"))

    def append(self, event: AuditEvent) -> SealedAuditRecord:
        from .. import GENESIS_HASH, SealedAuditRecord, link_hash, link_payload

        record = event.to_record()

        def work(connection: psycopg.Connection[dict[str, Any]]) -> SealedAuditRecord:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (self._schema + "/chain",))
            row = connection.execute(
                f"SELECT record_hash FROM {self._schema}.audit_record ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            previous = GENESIS_HASH if row is None else _hash(row.get("record_hash"))
            record_hash = link_hash(previous, record)
            signature = self._signer.sign(link_payload(previous, record, record_hash))
            inserted = connection.execute(
                f"INSERT INTO {self._schema}.audit_record (record, previous_hash, record_hash, signature, keyid) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING seq",
                (Jsonb(record), previous, record_hash, signature, self._signer.keyid),
            ).fetchone()
            if inserted is None or not isinstance(inserted.get("seq"), int):
                raise psycopg.DataError("the audit insert returned no sequence")
            return SealedAuditRecord(
                sequence=inserted["seq"], record=record, previous_hash=previous, record_hash=record_hash,
                signature=signature, keyid=self._signer.keyid,
            )

        return self._run(work)

    def records(self) -> list[SealedAuditRecord]:
        from .. import SealedAuditRecord

        def work(connection: psycopg.Connection[dict[str, Any]]) -> list[SealedAuditRecord]:
            rows = connection.execute(
                f"SELECT seq, record, previous_hash, record_hash, signature, keyid "
                f"FROM {self._schema}.audit_record ORDER BY seq"
            ).fetchall()
            result = []
            for row in rows:
                if not isinstance(row.get("seq"), int) or not isinstance(row.get("record"), dict):
                    raise psycopg.DataError("malformed audit row")
                for column in ("signature", "keyid"):
                    if not isinstance(row.get(column), str) or not row[column]:
                        raise psycopg.DataError("malformed audit row")
                result.append(SealedAuditRecord(
                    sequence=row["seq"], record=row["record"], previous_hash=_hash(row.get("previous_hash")),
                    record_hash=_hash(row.get("record_hash")), signature=row["signature"], keyid=row["keyid"],
                ))
            return result

        return self._run(work)


def _hash(value: object) -> str:
    from .. import DIGEST

    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise psycopg.DataError("malformed audit hash")
    return value
