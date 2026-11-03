"""PostgreSQL Run Ledger of C8 (ADD v1.3 §2.2 :276: "PostgreSQL per Run Ledger").

OCOR-DEV-REM-0050 (NCP-U04, NCR-C3-002). AgentRun state -- assignment, commitment,
handoff and dissent -- is operational run state of C8, appended here; it is never
canonical state, which only C6 produces through C3 (ADD v1.3 §2.5 rule 10 :342). Entries
are append-only: there is no update or delete, so a registered dissent can never be
overwritten (LLD v1.1 §2.8 :183). Every ``psycopg`` reference of C8 is confined to this
adapter (AFF-002/AFF-006); the caller only sees plain Python types.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

SCHEMA = """
CREATE TABLE IF NOT EXISTS c8_run_ledger (
    entry_no BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('TASK_ASSIGNED', 'TASK_COMMITTED', 'TASK_HANDED_OFF', 'DISSENT_REGISTERED')),
    agent_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS c8_run_ledger_task ON c8_run_ledger (task_id, entry_no);
CREATE OR REPLACE FUNCTION c8_run_ledger_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'c8_run_ledger is append-only';
END;
$$;
DROP TRIGGER IF EXISTS c8_run_ledger_no_rewrite ON c8_run_ledger;
CREATE TRIGGER c8_run_ledger_no_rewrite BEFORE UPDATE OR DELETE ON c8_run_ledger
    FOR EACH ROW EXECUTE FUNCTION c8_run_ledger_append_only();
"""

KINDS = frozenset({"TASK_ASSIGNED", "TASK_COMMITTED", "TASK_HANDED_OFF", "DISSENT_REGISTERED"})


class RunLedgerError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True, slots=True)
class RunLedgerEntry:
    entry_no: int
    idempotency_key: str
    task_id: str
    kind: str
    agent_id: str
    payload: dict[str, Any]
    recorded_at: datetime


class PostgresRunLedger:
    """Append-only, idempotent C8 Run Ledger on PostgreSQL."""

    def __init__(self, dsn: str) -> None:
        if not isinstance(dsn, str) or not dsn:
            raise ValueError("a PostgreSQL DSN is required")
        self._dsn = dsn

    def initialize(self) -> None:
        with psycopg.connect(self._dsn) as connection:
            connection.execute("SELECT pg_advisory_lock(hashtextextended('c8_run_ledger_schema', 0))")
            try:
                connection.execute(SCHEMA)
            finally:
                connection.execute("SELECT pg_advisory_unlock(hashtextextended('c8_run_ledger_schema', 0))")

    def append(
        self,
        *,
        idempotency_key: str,
        task_id: str,
        kind: str,
        agent_id: str,
        payload: Mapping[str, Any],
        recorded_at: datetime,
    ) -> RunLedgerEntry:
        """Appends one entry; the same idempotency key with the same content returns the
        original entry, with other content it is ``IDEMPOTENCY_CONFLICT``."""
        for name, value in (("idempotency_key", idempotency_key), ("task_id", task_id), ("agent_id", agent_id)):
            if not isinstance(value, str) or not value:
                raise RunLedgerError("SCHEMA_VIOLATION", f"{name} is required")
        if kind not in KINDS:
            raise RunLedgerError("SCHEMA_VIOLATION", f"unknown run ledger kind {kind!r}")
        if not isinstance(recorded_at, datetime) or recorded_at.utcoffset() is None:
            raise RunLedgerError("SCHEMA_VIOLATION", "recorded_at must be timezone-aware")
        body = dict(payload)
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                """INSERT INTO c8_run_ledger (idempotency_key, task_id, kind, agent_id, payload, recorded_at)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (idempotency_key) DO NOTHING
                   RETURNING *""",
                (idempotency_key, task_id, kind, agent_id, Json(body), recorded_at),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT * FROM c8_run_ledger WHERE idempotency_key=%s", (idempotency_key,)
                ).fetchone()
                if row is None or (row["task_id"], row["kind"], row["agent_id"], dict(row["payload"])) != (
                    task_id, kind, agent_id, body
                ):
                    raise RunLedgerError("IDEMPOTENCY_CONFLICT", "idempotency key rebound to other run ledger content")
        return self._entry(row)

    @staticmethod
    def _entry(row: Mapping[str, Any]) -> RunLedgerEntry:
        return RunLedgerEntry(
            entry_no=int(row["entry_no"]),
            idempotency_key=str(row["idempotency_key"]),
            task_id=str(row["task_id"]),
            kind=str(row["kind"]),
            agent_id=str(row["agent_id"]),
            payload=dict(row["payload"]),
            recorded_at=row["recorded_at"],
        )

    def entries(self, task_id: str) -> tuple[RunLedgerEntry, ...]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                "SELECT * FROM c8_run_ledger WHERE task_id=%s ORDER BY entry_no", (task_id,)
            ).fetchall()
        return tuple(self._entry(row) for row in rows)
