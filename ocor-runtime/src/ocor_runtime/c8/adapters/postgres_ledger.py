"""PostgreSQL Run Ledger of C8 (ADD v1.3 §2.2 :276: "PostgreSQL per Run Ledger").

OCOR-DEV-REM-0050 (NCP-U04, NCR-C3-002). AgentRun state -- assignment, commitment,
handoff and dissent -- is operational run state of C8, appended here; it is never
canonical state, which only C6 produces through C3 (ADD v1.3 §2.5 rule 10 :342). Entries
are append-only: there is no update or delete, so a registered dissent can never be
overwritten (LLD v1.1 §2.8 :183). Every ``psycopg`` reference of C8 is confined to this
adapter (AFF-002/AFF-006); the caller only sees plain Python types.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

_SCHEMA_TEMPLATE = """
CREATE TABLE IF NOT EXISTS c8_run_ledger (
    entry_no BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL CONSTRAINT c8_run_ledger_kind_check CHECK (kind IN ({kinds})),
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
ALTER TABLE c8_run_ledger DROP CONSTRAINT IF EXISTS c8_run_ledger_kind_check;
ALTER TABLE c8_run_ledger ADD CONSTRAINT c8_run_ledger_kind_check CHECK (kind IN ({kinds}));
"""

# OCOR-DEV-REM-0058 (NCP-U10, NCR-C8-001): every closed C8 record of the AgentRun state (LLD v1.1
# §2.8 :183) has its kind; the set stays closed.
KINDS = frozenset(
    {
        "RUN_STARTED",
        "RUN_TERMINATED",
        "TASK_PROPOSED",
        "TASK_ASSIGNED",
        "TASK_COMMITTED",
        "TASK_HANDED_OFF",
        "HANDOFF_REJECTED",
        "TASK_COMPLETED",
        "TASK_ABSTAINED",
        "TASK_FAILED",
        "TASK_EXPIRED",
        "TASK_CANCELLED",
        "DISSENT_REGISTERED",
        "DISSENT_RESOLVED",
        "DECISION_PROPOSED",
        "TOOL_INVOKED",
        "MESSAGE_SENT",
    }
)
_KIND_LIST = ", ".join(f"'{kind}'" for kind in sorted(KINDS))
# the kind constraint is re-created at every initialisation, so a ledger created with the
# earlier, narrower set admits the closed set above (rows are never rewritten)
SCHEMA = _SCHEMA_TEMPLATE.replace("{kinds}", _KIND_LIST)
COLUMNS = frozenset({"entry_no", "idempotency_key", "task_id", "kind", "agent_id", "payload", "recorded_at"})


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


@contextmanager
def _driver(operation: str) -> Iterator[None]:
    """Driver failures leave the adapter only as ``RunLedgerError``: an unreachable server
    is ``BACKEND_UNAVAILABLE``, any other refusal ``BACKEND_ERROR``; the server text is
    never echoed."""
    try:
        yield
    except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
        raise RunLedgerError("BACKEND_UNAVAILABLE", f"{operation}: PostgreSQL is unavailable") from exc
    except psycopg.Error as exc:
        raise RunLedgerError("BACKEND_ERROR", f"{operation}: PostgreSQL refused the statement ({type(exc).__name__})") from exc


def _stored_text(row: Mapping[str, Any], field: str) -> str:
    value = row[field]
    if not isinstance(value, str) or not value:
        raise RunLedgerError("BACKEND_ERROR", f"stored {field} is not a non-empty string")
    return value


class PostgresRunLedger:
    """Append-only, idempotent C8 Run Ledger on PostgreSQL."""

    def __init__(self, dsn: str) -> None:
        if not isinstance(dsn, str) or not dsn:
            raise ValueError("a PostgreSQL DSN is required")
        self._dsn = dsn

    def initialize(self) -> None:
        """Creates the ledger if absent, under a transaction-scoped advisory lock (released
        with the transaction, also when a statement fails); a pre-existing
        ``c8_run_ledger`` of another shape fails closed with ``SCHEMA_MISMATCH`` before
        any statement touches it."""
        with _driver("initialize"), psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('c8_run_ledger_schema', 0))")
                present = self._columns(connection)
                if present and present != COLUMNS:
                    raise RunLedgerError("SCHEMA_MISMATCH", "c8_run_ledger differs from SCHEMA")
                connection.execute(SCHEMA)
                if self._columns(connection) != COLUMNS:
                    raise RunLedgerError("SCHEMA_MISMATCH", "c8_run_ledger differs from SCHEMA")

    @staticmethod
    def _columns(connection: psycopg.Connection[Any]) -> frozenset[str]:
        rows = connection.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = 'c8_run_ledger'"""
        ).fetchall()
        names = set()
        for row in rows:
            if not isinstance(row, Mapping) or "column_name" not in row:
                raise RunLedgerError("BACKEND_ERROR", "a catalogue row is not of the expected shape")
            names.add(_stored_text(row, "column_name"))
        return frozenset(names)

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
        if not isinstance(payload, Mapping):
            raise RunLedgerError("SCHEMA_VIOLATION", "payload must be an object")
        body = dict(payload)
        with _driver("append"), psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                """INSERT INTO c8_run_ledger (idempotency_key, task_id, kind, agent_id, payload, recorded_at)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (idempotency_key) DO NOTHING
                   RETURNING *""",
                (idempotency_key, task_id, kind, agent_id, Json(body), recorded_at),
            ).fetchone()
            if row is not None:
                return self._entry(row)
            row = connection.execute(
                "SELECT * FROM c8_run_ledger WHERE idempotency_key=%s", (idempotency_key,)
            ).fetchone()
        if row is None:
            raise RunLedgerError("IDEMPOTENCY_CONFLICT", "idempotency key rebound to other run ledger content")
        entry = self._entry(row)
        if (entry.idempotency_key, entry.task_id, entry.kind, entry.agent_id, entry.payload) != (
            idempotency_key, task_id, kind, agent_id, body
        ):
            raise RunLedgerError("IDEMPOTENCY_CONFLICT", "idempotency key rebound to other run ledger content")
        return entry

    @staticmethod
    def _entry(row: object) -> RunLedgerEntry:
        """A stored entry, checked without coercion: any other shape fails closed."""
        if not isinstance(row, Mapping) or not COLUMNS <= set(row):
            raise RunLedgerError("BACKEND_ERROR", "a stored entry is not of the expected shape")
        entry_no = row["entry_no"]
        if isinstance(entry_no, bool) or not isinstance(entry_no, int) or entry_no <= 0:
            raise RunLedgerError("BACKEND_ERROR", "stored entry_no is not a positive integer")
        kind = _stored_text(row, "kind")
        if kind not in KINDS:
            raise RunLedgerError("BACKEND_ERROR", "stored kind is not a run ledger kind")
        payload = row["payload"]
        if not isinstance(payload, dict):
            raise RunLedgerError("BACKEND_ERROR", "stored payload is not a JSON object")
        recorded_at = row["recorded_at"]
        if not isinstance(recorded_at, datetime) or recorded_at.utcoffset() is None:
            raise RunLedgerError("BACKEND_ERROR", "stored recorded_at is not a timezone-aware instant")
        return RunLedgerEntry(
            entry_no=entry_no,
            idempotency_key=_stored_text(row, "idempotency_key"),
            task_id=_stored_text(row, "task_id"),
            kind=kind,
            agent_id=_stored_text(row, "agent_id"),
            payload=dict(payload),
            recorded_at=recorded_at,
        )

    def entries(self, task_id: str) -> tuple[RunLedgerEntry, ...]:
        if not isinstance(task_id, str) or not task_id:
            raise RunLedgerError("SCHEMA_VIOLATION", "task_id is required")
        with _driver("entries"), psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                "SELECT * FROM c8_run_ledger WHERE task_id=%s ORDER BY entry_no", (task_id,)
            ).fetchall()
        entries = tuple(self._entry(row) for row in rows)
        if any(entry.task_id != task_id for entry in entries):
            raise RunLedgerError("BACKEND_ERROR", "the backend listed an entry of another task")
        return entries
