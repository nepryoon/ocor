"""PostgreSQL job ledger of C7 (the ``CausalJobLedger`` port of ``c7.jobs``).

OCOR-DEV-REM-0057 (NCP-U09, ``NCR-C7-004``). The ledger keeps one row per job with its
state, an append-only audit of every transition and refused submission, the resources
held by a running job with their release instant, and the append-only result of a
completed job bound to the digest of the pinned ``ScenarioRunSpec``. Every state change
is a compare-and-set under a row lock in one transaction; the clock is the database's
(``clock_timestamp()``), so deadlines hold across processes. Admission enforces a quota
per principal and a global capacity (backpressure); a refusal is audited before it is
raised. Every ``psycopg`` reference of C7 jobs is confined to this adapter; the caller
only sees ``c7.jobs`` types and ``CausalJobError``, never server text.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..jobs import (
    ACTIVE_STATES,
    JOB_STATES,
    RETRY_SAFETY,
    TERMINAL_STATES,
    TRANSITIONS,
    CausalJob,
    CausalJobError,
    JobResource,
    JobResult,
    JobTransition,
)
from ..runtime import OUTCOME_STATUSES, CausalOutcome, CausalRuntimeError, outcome_document, outcome_from_document
from ..scenario_run import ScenarioRunError, ScenarioRunSpec

SCHEMA_NAME = re.compile(r"[a-z_][a-z0-9_]{0,48}")
LEDGER_ACTOR = "urn:ocor:c7:job-ledger"
T = TypeVar("T")
AUDIT_STATES = (*JOB_STATES, "refused", "resources_released")
_STATES_SQL = ", ".join(f"'{state}'" for state in JOB_STATES)
_AUDIT_SQL = ", ".join(f"'{state}'" for state in AUDIT_STATES)
_DDL = f"""
CREATE SCHEMA IF NOT EXISTS {{s}};
CREATE TABLE IF NOT EXISTS {{s}}.c7_job (
  job_id TEXT PRIMARY KEY, principal TEXT NOT NULL, spec_digest TEXT NOT NULL, spec JSONB NOT NULL,
  state TEXT NOT NULL CHECK (state IN ({_STATES_SQL})), progress TEXT NOT NULL,
  deadline TIMESTAMPTZ NOT NULL, result_digest TEXT, outcome_status TEXT, technical_failure TEXT,
  retry_safety TEXT, submitted_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
CREATE INDEX IF NOT EXISTS c7_job_principal_state ON {{s}}.c7_job (principal, state);
CREATE TABLE IF NOT EXISTS {{s}}.c7_job_transition (
  seq BIGSERIAL PRIMARY KEY, job_id TEXT, principal TEXT NOT NULL, from_state TEXT,
  to_state TEXT NOT NULL CHECK (to_state IN ({_AUDIT_SQL})), actor TEXT NOT NULL, reason TEXT NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
CREATE TABLE IF NOT EXISTS {{s}}.c7_job_resource (
  job_id TEXT NOT NULL REFERENCES {{s}}.c7_job (job_id), resource TEXT NOT NULL,
  quantity BIGINT NOT NULL CHECK (quantity >= 0), acquired_at TIMESTAMPTZ NOT NULL, released_at TIMESTAMPTZ,
  PRIMARY KEY (job_id, resource));
CREATE TABLE IF NOT EXISTS {{s}}.c7_job_result (
  job_id TEXT PRIMARY KEY REFERENCES {{s}}.c7_job (job_id), spec_digest TEXT NOT NULL,
  result_version INTEGER NOT NULL CHECK (result_version >= 1), outcome JSONB NOT NULL,
  reproducibility_digest TEXT NOT NULL, recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
CREATE OR REPLACE FUNCTION {{s}}.c7_job_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'C7 job audit and results are append-only'; END $$;
CREATE OR REPLACE FUNCTION {{s}}.c7_job_resource_release_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' OR OLD.released_at IS NOT NULL OR NEW.released_at IS NULL
     OR (NEW.job_id, NEW.resource, NEW.quantity, NEW.acquired_at) IS DISTINCT FROM
        (OLD.job_id, OLD.resource, OLD.quantity, OLD.acquired_at) THEN
    RAISE EXCEPTION 'C7 job resources are only released, once';
  END IF;
  RETURN NEW;
END $$;
"""
_TRIGGERS = (
    ("c7_job_transition_append_only", "c7_job_transition", "BEFORE UPDATE OR DELETE", "c7_job_append_only"),
    ("c7_job_result_append_only", "c7_job_result", "BEFORE UPDATE OR DELETE", "c7_job_append_only"),
    ("c7_job_resource_release_only", "c7_job_resource", "BEFORE UPDATE OR DELETE", "c7_job_resource_release_only"),
)
_COLUMNS = {
    "c7_job": frozenset(
        {
            "job_id", "principal", "spec_digest", "spec", "state", "progress", "deadline", "result_digest",
            "outcome_status", "technical_failure", "retry_safety", "submitted_at", "updated_at",
        }
    ),
    "c7_job_transition": frozenset({"seq", "job_id", "principal", "from_state", "to_state", "actor", "reason", "recorded_at"}),
    "c7_job_resource": frozenset({"job_id", "resource", "quantity", "acquired_at", "released_at"}),
    "c7_job_result": frozenset({"job_id", "spec_digest", "result_version", "outcome", "reproducibility_digest", "recorded_at"}),
}
_JOB_SELECT = "SELECT *, clock_timestamp() >= deadline AS overdue FROM {s}.c7_job WHERE job_id = %s"
_UNAVAILABLE = (psycopg.OperationalError, psycopg.InterfaceError)
_HEX64 = re.compile(r"[0-9a-f]{64}")
_RESOURCE = re.compile(r"[a-z][a-z0-9_]{0,62}")
_PROGRESS = re.compile(r"0|1|0\.[0-9]{0,5}[1-9]")


def _backend(message: str) -> CausalJobError:
    return CausalJobError("BACKEND_ERROR", message)


def _actor(value: object, name: str = "actor") -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CausalJobError("SCHEMA_VIOLATION", f"{name} must be a non-empty string")
    return value


def _column(row: object, column: str) -> Any:
    """The value of ``column`` in a row returned by the backend: a row that is not a
    mapping or lacks the column is a ``BACKEND_ERROR``, never a raw ``KeyError``."""
    if not isinstance(row, Mapping) or column not in row:
        raise _backend(f"a stored row has no {column} column")
    return row[column]


def _stored_text(row: Mapping[str, Any], column: str, *, nullable: bool = False) -> Any:
    value = _column(row, column)
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise _backend(f"stored {column} is not a non-empty string")
    return value


def _stored_instant(row: Mapping[str, Any], column: str, *, nullable: bool = False) -> Any:
    value = _column(row, column)
    if value is None and nullable:
        return None
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise _backend(f"stored {column} is not a timezone-aware instant")
    return value


def _stored_count(row: Mapping[str, Any], column: str, *, minimum: int) -> int:
    value = _column(row, column)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _backend(f"stored {column} is not an integer >= {minimum}")
    return value


def _progress(value: object) -> Decimal | None:
    """A progress value: ``0``, ``1`` or a plain decimal fraction without trailing zeros."""
    if not isinstance(value, str) or _PROGRESS.fullmatch(value) is None:
        return None
    return Decimal(value)


class PostgresCausalJobLedger:
    """The C7 job ledger on PostgreSQL; ``schema`` isolates one deployment (or one test)."""

    def __init__(
        self,
        dsn: str,
        *,
        schema: str = "ocor_c7_jobs",
        max_active_per_principal: int = 4,
        max_active_total: int = 64,
        connect_timeout: int = 5,
    ) -> None:
        if not isinstance(dsn, str) or not dsn:
            raise ValueError("a PostgreSQL DSN is required")
        if not isinstance(schema, str) or SCHEMA_NAME.fullmatch(schema) is None:
            raise ValueError("invalid C7 job ledger schema name")
        for name, value in (("max_active_per_principal", max_active_per_principal), ("max_active_total", max_active_total)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self._dsn = dsn
        self._schema = schema
        self._per_principal = max_active_per_principal
        self._total = max_active_total
        self._timeout = connect_timeout

    def __repr__(self) -> str:
        return f"PostgresCausalJobLedger(schema={self._schema!r})"

    def _run(self, operation: str, work: Callable[[psycopg.Connection[dict[str, Any]]], T]) -> T:
        """One transaction on one connection, both closed on every path; driver failures
        leave only as ``CausalJobError`` without server text."""
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row, connect_timeout=self._timeout) as connection:
                with connection.transaction():
                    return work(connection)
        except _UNAVAILABLE as exc:
            raise CausalJobError("BACKEND_UNAVAILABLE", f"{operation}: PostgreSQL is unavailable") from exc
        except psycopg.Error as exc:
            raise _backend(f"{operation}: PostgreSQL refused the statement ({type(exc).__name__})") from exc

    # --- schema --------------------------------------------------------------------------------

    def initialize(self) -> None:
        """Creates the ledger under a transaction-scoped advisory lock; a pre-existing
        table of another shape fails closed with ``SCHEMA_MISMATCH``."""

        def work(connection: psycopg.Connection[dict[str, Any]]) -> None:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (self._schema + "/c7-jobs-ddl",))
            self._check_columns(connection, allow_absent=True)
            connection.execute(_DDL.format(s=self._schema).encode())
            for name, table, timing, function in _TRIGGERS:
                present = connection.execute(
                    "SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE t.tgname = %s AND n.nspname = %s AND c.relname = %s",
                    (name, self._schema, table),
                ).fetchone()
                if present is None:
                    connection.execute(
                        f"CREATE TRIGGER {name} {timing} ON {self._schema}.{table} "
                        f"FOR EACH ROW EXECUTE FUNCTION {self._schema}.{function}()".encode()
                    )
            self._check_columns(connection, allow_absent=False)

        self._run("initialize", work)

    def _check_columns(self, connection: psycopg.Connection[dict[str, Any]], *, allow_absent: bool) -> None:
        for table, expected in _COLUMNS.items():
            rows = connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
                (self._schema, table),
            ).fetchall()
            names = set()
            for row in rows:
                if not isinstance(row, Mapping) or not isinstance(row.get("column_name"), str):
                    raise _backend("a catalogue row is not of the expected shape")
                names.add(row["column_name"])
            if (names or not allow_absent) and names != expected:
                raise CausalJobError("SCHEMA_MISMATCH", f"{table} differs from the C7 job ledger schema")

    # --- reading -------------------------------------------------------------------------------

    def _job_row(self, connection: psycopg.Connection[dict[str, Any]], job_id: str, *, lock: bool = False) -> Mapping[str, Any]:
        statement = _JOB_SELECT.format(s=self._schema) + (" FOR UPDATE" if lock else "")
        row = connection.execute(statement.encode(), (job_id,)).fetchone()
        if row is None:
            raise CausalJobError("JOB_NOT_FOUND", "no job with this identifier")
        if not isinstance(row, Mapping) or not _COLUMNS["c7_job"] | {"overdue"} <= set(row):
            raise _backend("a stored job is not of the expected shape")
        if _column(row, "job_id") != job_id:
            raise _backend("the backend returned another job")
        return row

    @staticmethod
    def _job(row: Mapping[str, Any]) -> CausalJob:
        state = _stored_text(row, "state")
        if state not in JOB_STATES:
            raise _backend("stored state is not a job state")
        progress = _stored_text(row, "progress")
        if _progress(progress) is None:
            raise _backend("stored progress is not a decimal between 0 and 1")
        spec_digest = _stored_text(row, "spec_digest")
        if _HEX64.fullmatch(spec_digest) is None:
            raise _backend("stored spec_digest is not a sha256 digest")
        overdue = _column(row, "overdue")
        if not isinstance(overdue, bool):
            raise _backend("stored deadline comparison is not a boolean")
        retry = _stored_text(row, "retry_safety", nullable=True)
        if retry is not None and retry not in RETRY_SAFETY:
            raise _backend("stored retry_safety is not a retry safety")
        result_digest = _stored_text(row, "result_digest", nullable=True)
        if (result_digest is None) != (state != "completed"):
            raise _backend("stored result reference does not match the state")
        if result_digest is not None and _HEX64.fullmatch(result_digest) is None:
            raise _backend("stored result_digest is not a sha256 digest")
        outcome_status = _stored_text(row, "outcome_status", nullable=True)
        if outcome_status is not None and outcome_status not in OUTCOME_STATUSES:
            raise _backend("stored outcome_status is not an outcome status")
        if (outcome_status is None) != (state != "completed"):
            raise _backend("stored outcome status does not match the state")
        technical_failure = _stored_text(row, "technical_failure", nullable=True)
        if (technical_failure is None) != (state != "failed") or (retry is None) != (state != "failed"):
            raise _backend("stored technical failure and retry safety do not match the state")
        return CausalJob(
            job_id=_stored_text(row, "job_id"),
            principal=_stored_text(row, "principal"),
            spec_digest=spec_digest,
            state=state,
            progress=progress,
            deadline=_stored_instant(row, "deadline"),
            overdue=overdue,
            result_digest=result_digest,
            outcome_status=outcome_status,
            technical_failure=technical_failure,
            retry_safety=retry,
            submitted_at=_stored_instant(row, "submitted_at"),
            updated_at=_stored_instant(row, "updated_at"),
        )

    def job(self, job_id: str) -> CausalJob:
        _actor(job_id, "job_id")
        return self._run("job", lambda connection: self._job(self._job_row(connection, job_id)))

    def spec(self, job_id: str) -> ScenarioRunSpec:
        """The pinned spec, rebuilt and checked against its stored digest."""
        _actor(job_id, "job_id")
        row = self._run("spec", lambda connection: self._job_row(connection, job_id))
        job = self._job(row)
        try:
            spec = ScenarioRunSpec.from_document(_column(row, "spec"))
        except ScenarioRunError as exc:
            raise _backend("the stored spec is not a valid ScenarioRunSpec") from exc
        if spec.digest != job.spec_digest:
            raise CausalJobError("SPEC_TAMPERED", "the stored spec does not match its digest")
        return spec

    def transitions(self, job_id: str) -> tuple[JobTransition, ...]:
        _actor(job_id, "job_id")
        rows = self._run(
            "transitions",
            lambda connection: connection.execute(
                f"SELECT * FROM {self._schema}.c7_job_transition WHERE job_id = %s ORDER BY seq".encode(), (job_id,)
            ).fetchall(),
        )
        transitions = tuple(self._transition(row) for row in rows)
        if any(item.job_id != job_id for item in transitions):
            raise _backend("the backend listed a transition of another job")
        return transitions

    def refusals(self, principal: str) -> tuple[JobTransition, ...]:
        _actor(principal, "principal")
        rows = self._run(
            "refusals",
            lambda connection: connection.execute(
                f"SELECT * FROM {self._schema}.c7_job_transition WHERE principal = %s AND to_state = 'refused' ORDER BY seq".encode(),
                (principal,),
            ).fetchall(),
        )
        return tuple(self._transition(row) for row in rows)

    @staticmethod
    def _transition(row: object) -> JobTransition:
        if not isinstance(row, Mapping) or not _COLUMNS["c7_job_transition"] <= set(row):
            raise _backend("a stored transition is not of the expected shape")
        to_state = _stored_text(row, "to_state")
        from_state = _stored_text(row, "from_state", nullable=True)
        if to_state not in AUDIT_STATES or (from_state is not None and from_state not in JOB_STATES):
            raise _backend("a stored transition names an unknown state")
        return JobTransition(
            seq=_stored_count(row, "seq", minimum=1),
            job_id=_stored_text(row, "job_id", nullable=True),
            from_state=from_state,
            to_state=to_state,
            actor=_stored_text(row, "actor"),
            reason=_stored_text(row, "reason"),
            recorded_at=_stored_instant(row, "recorded_at"),
        )

    def resources(self, job_id: str) -> tuple[JobResource, ...]:
        _actor(job_id, "job_id")
        rows = self._run(
            "resources",
            lambda connection: connection.execute(
                f"SELECT * FROM {self._schema}.c7_job_resource WHERE job_id = %s ORDER BY resource".encode(), (job_id,)
            ).fetchall(),
        )
        return tuple(self._resource(row, job_id) for row in rows)

    @staticmethod
    def _resource(row: object, job_id: str) -> JobResource:
        if not isinstance(row, Mapping) or not _COLUMNS["c7_job_resource"] <= set(row):
            raise _backend("a stored resource is not of the expected shape")
        if _column(row, "job_id") != job_id:
            raise _backend("the backend listed a resource of another job")
        return JobResource(
            job_id=job_id,
            resource=_stored_text(row, "resource"),
            quantity=_stored_count(row, "quantity", minimum=0),
            acquired_at=_stored_instant(row, "acquired_at"),
            released_at=_stored_instant(row, "released_at", nullable=True),
        )

    def result(self, job_id: str) -> JobResult:
        """The result of a completed job, after recomputing its digest and checking that
        it is bound to the job's pinned spec. Any other state has no valid result."""
        _actor(job_id, "job_id")

        def work(connection: psycopg.Connection[dict[str, Any]]) -> tuple[CausalJob, Mapping[str, Any] | None]:
            job = self._job(self._job_row(connection, job_id))
            row = connection.execute(
                f"SELECT * FROM {self._schema}.c7_job_result WHERE job_id = %s".encode(), (job_id,)
            ).fetchone()
            return job, row

        job, row = self._run("result", work)
        if job.state != "completed":
            raise CausalJobError("NO_VALID_RESULT", f"a {job.state} job has no valid result")
        if not isinstance(row, Mapping) or not _COLUMNS["c7_job_result"] <= set(row):
            raise _backend("the stored result is missing or not of the expected shape")
        if _stored_text(row, "job_id") != job_id:
            raise _backend("the backend returned the result of another job")
        _stored_instant(row, "recorded_at")
        version = _stored_count(row, "result_version", minimum=1)
        digest = _stored_text(row, "reproducibility_digest")
        try:
            outcome = outcome_from_document(_column(row, "outcome"), digest)
        except CausalRuntimeError as exc:
            raise CausalJobError("RESULT_TAMPERED", "the stored result does not match its digest or schema") from exc
        if (
            digest != job.result_digest
            or _stored_text(row, "spec_digest") != job.spec_digest
            or _run_spec_digest(outcome) != job.spec_digest
        ):
            raise CausalJobError("RESULT_TAMPERED", "the stored result is not bound to the job's pinned spec")
        return JobResult(
            job_id=job_id,
            spec_digest=job.spec_digest,
            result_version=version,
            outcome=outcome,
        )

    # --- transitions ---------------------------------------------------------------------------

    def _audit(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        job_id: str | None,
        principal: str,
        from_state: str | None,
        to_state: str,
        actor: str,
        reason: str,
    ) -> None:
        connection.execute(
            f"INSERT INTO {self._schema}.c7_job_transition (job_id, principal, from_state, to_state, actor, reason) "
            "VALUES (%s, %s, %s, %s, %s, %s)".encode(),
            (job_id, principal, from_state, to_state, actor, reason),
        )

    def submit(self, spec: ScenarioRunSpec, *, actor: str) -> CausalJob:
        """Admits a job ``queued`` with its deadline from the budget; beyond the quota of
        the principal (``QUOTA_EXCEEDED``) or the global capacity (``BACKPRESSURE``) the
        submission is refused and the refusal audited."""
        if not isinstance(spec, ScenarioRunSpec):
            raise CausalJobError("SCHEMA_VIOLATION", "a ScenarioRunSpec is required")
        _actor(actor)
        verified = ScenarioRunSpec.from_document(spec.to_document())
        job_id = f"urn:ocor:c7:job:{uuid.uuid4()}"

        def work(connection: psycopg.Connection[dict[str, Any]]) -> str | Mapping[str, Any]:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (self._schema + "/c7-jobs-admission",))
            self._sweep(connection)
            counts = connection.execute(
                f"SELECT count(*) FILTER (WHERE principal = %s) AS mine, count(*) AS total FROM {self._schema}.c7_job "
                "WHERE state = ANY(%s)".encode(),
                (verified.principal, sorted(ACTIVE_STATES)),
            ).fetchone()
            if not isinstance(counts, Mapping):
                raise _backend("the admission count is not of the expected shape")
            mine, total = _stored_count(counts, "mine", minimum=0), _stored_count(counts, "total", minimum=0)
            refusal = "QUOTA_EXCEEDED" if mine >= self._per_principal else "BACKPRESSURE" if total >= self._total else None
            if refusal is not None:
                self._audit(
                    connection, job_id=None, principal=verified.principal, from_state=None, to_state="refused", actor=actor,
                    reason=f"{refusal}:{verified.digest}",
                )
                return refusal
            connection.execute(
                f"INSERT INTO {self._schema}.c7_job (job_id, principal, spec_digest, spec, state, progress, deadline, "
                "submitted_at, updated_at) SELECT %s, %s, %s, %s, 'queued', '0', t.now + make_interval(secs => %s), t.now, t.now "
                "FROM (SELECT clock_timestamp() AS now) AS t".encode(),
                (job_id, verified.principal, verified.digest, Jsonb(verified.to_document()), verified.budget["max_runtime_seconds"]),
            )
            self._audit(
                connection, job_id=job_id, principal=verified.principal, from_state=None, to_state="queued", actor=actor, reason="SUBMITTED"
            )
            return self._job_row(connection, job_id)

        outcome = self._run("submit", work)
        if isinstance(outcome, str):
            raise CausalJobError(outcome, "the job was not admitted")
        return self._job(outcome)

    def _sweep(self, connection: psycopg.Connection[dict[str, Any]], actor: str = LEDGER_ACTOR) -> tuple[str, ...]:
        """Expires every active job past its deadline, audited as ``TIMEOUT`` by the
        ledger; resources stay recorded until their holder releases them."""
        rows = connection.execute(
            f"SELECT job_id, principal, state FROM {self._schema}.c7_job WHERE state = ANY(%s) AND clock_timestamp() >= deadline "
            "ORDER BY job_id FOR UPDATE".encode(),
            (sorted(ACTIVE_STATES),),
        ).fetchall()
        expired = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise _backend("an overdue job row is not of the expected shape")
            job_id, principal, state = _stored_text(row, "job_id"), _stored_text(row, "principal"), _stored_text(row, "state")
            if state not in ACTIVE_STATES:
                raise _backend("an overdue job row names an inactive state")
            connection.execute(
                f"UPDATE {self._schema}.c7_job SET state = 'expired', updated_at = clock_timestamp() WHERE job_id = %s AND state = %s".encode(),
                (job_id, state),
            )
            self._audit(connection, job_id=job_id, principal=principal, from_state=state, to_state="expired", actor=actor, reason="TIMEOUT")
            expired.append(job_id)
        return tuple(expired)

    def expire_overdue(self, *, actor: str) -> tuple[str, ...]:
        """Expires every overdue active job (for a scheduler); returns their identifiers."""
        _actor(actor)
        return self._run("expire_overdue", lambda connection: self._sweep(connection, actor))

    def _transit(
        self,
        operation: str,
        job_id: str,
        to_state: str,
        *,
        actor: str,
        reason: str,
        extra: Callable[[psycopg.Connection[dict[str, Any]], CausalJob], str] | None = None,
        sets: str = "",
        params: tuple[Any, ...] = (),
        expire_when_overdue: bool = False,
        from_state: str | None = None,
    ) -> CausalJob:
        _actor(job_id, "job_id")
        _actor(actor)
        _actor(reason, "reason")

        def work(connection: psycopg.Connection[dict[str, Any]]) -> tuple[CausalJob, bool]:
            job = self._job(self._job_row(connection, job_id, lock=True))
            target, why = to_state, reason
            expired = expire_when_overdue and job.overdue and "expired" in TRANSITIONS.get(job.state, frozenset())
            if expired:
                target, why = "expired", "TIMEOUT"
            elif to_state not in TRANSITIONS.get(job.state, frozenset()) or from_state not in {None, job.state}:
                return job, False
            elif extra is not None:
                why = extra(connection, job)
            connection.execute(
                f"UPDATE {self._schema}.c7_job SET state = %s, updated_at = clock_timestamp(){'' if expired else sets} "
                "WHERE job_id = %s AND state = %s".encode(),
                (target, *(() if expired else params), job_id, job.state),
            )
            self._audit(connection, job_id=job_id, principal=job.principal, from_state=job.state, to_state=target, actor=actor, reason=why)
            return self._job(self._job_row(connection, job_id)), not expired

        job, applied = self._run(operation, work)
        if job.state == "expired" and to_state != "expired" and not applied:
            raise CausalJobError("JOB_EXPIRED", "the job reached its timeout; no result is valid")
        if not applied:
            raise CausalJobError("INVALID_TRANSITION", f"{operation} is not allowed for a {job.state} job")
        return job

    def start(self, job_id: str, *, actor: str, resources: Mapping[str, int]) -> CausalJob:
        if not isinstance(resources, Mapping) or not resources:
            raise CausalJobError("SCHEMA_VIOLATION", "resources must name at least one resource")
        for name, quantity in resources.items():
            if not isinstance(name, str) or _RESOURCE.fullmatch(name) is None:
                raise CausalJobError("SCHEMA_VIOLATION", "a resource name must match [a-z][a-z0-9_]*")
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                raise CausalJobError("SCHEMA_VIOLATION", "a resource quantity must be a non-negative integer")
        held = dict(resources)

        def acquire(connection: psycopg.Connection[dict[str, Any]], _job: CausalJob) -> str:
            for name, quantity in sorted(held.items()):
                connection.execute(
                    f"INSERT INTO {self._schema}.c7_job_resource (job_id, resource, quantity, acquired_at) "
                    "VALUES (%s, %s, %s, clock_timestamp())".encode(),
                    (job_id, name, quantity),
                )
            return "STARTED"

        return self._transit(
            "start", job_id, "running", actor=actor, reason="STARTED", extra=acquire, expire_when_overdue=True, from_state="queued"
        )

    def report_progress(self, job_id: str, progress: str, *, actor: str) -> CausalJob:
        """Progress of a running job: a decimal string in [0, 1], never decreasing."""
        _actor(job_id, "job_id")
        _actor(actor)
        value = _progress(progress)
        if value is None:
            raise CausalJobError("SCHEMA_VIOLATION", "progress must be a plain decimal string between 0 and 1")

        def work(connection: psycopg.Connection[dict[str, Any]]) -> tuple[CausalJob, str | None]:
            job = self._job(self._job_row(connection, job_id, lock=True))
            if job.state != "running":
                return job, "INVALID_TRANSITION"
            current = _progress(job.progress)
            if current is None or value < current:
                return job, "PROGRESS_REGRESSION"
            connection.execute(
                f"UPDATE {self._schema}.c7_job SET progress = %s, updated_at = clock_timestamp() WHERE job_id = %s".encode(),
                (progress, job_id),
            )
            return self._job(self._job_row(connection, job_id)), None

        job, refusal = self._run("report_progress", work)
        if refusal is not None:
            raise CausalJobError(refusal, f"progress {progress} refused for a {job.state} job at {job.progress}")
        return job

    def pause(self, job_id: str, *, actor: str, reason: str) -> CausalJob:
        return self._transit("pause", job_id, "paused", actor=actor, reason=reason, expire_when_overdue=True)

    def resume(self, job_id: str, *, actor: str, reason: str) -> CausalJob:
        return self._transit("resume", job_id, "running", actor=actor, reason=reason, expire_when_overdue=True, from_state="paused")

    def cancel(self, job_id: str, *, actor: str, reason: str) -> CausalJob:
        return self._transit("cancel", job_id, "cancelled", actor=actor, reason=reason)

    def expire(self, job_id: str, *, actor: str) -> CausalJob:
        """Expires an overdue job; a job before its deadline is refused."""

        def require_overdue(_connection: psycopg.Connection[dict[str, Any]], job: CausalJob) -> str:
            if not job.overdue:
                raise _NotOverdue()
            return "TIMEOUT"

        try:
            return self._transit("expire", job_id, "expired", actor=actor, reason="TIMEOUT", extra=require_overdue)
        except _NotOverdue:
            raise CausalJobError("NOT_OVERDUE", "the job has not reached its deadline") from None

    def fail(self, job_id: str, *, actor: str, technical_failure: str, retry_safety: str) -> CausalJob:
        _actor(technical_failure, "technical_failure")
        if retry_safety not in RETRY_SAFETY:
            raise CausalJobError("SCHEMA_VIOLATION", "retry_safety must be SAFE_TO_RETRY or NOT_SAFE_TO_RETRY")
        return self._transit(
            "fail",
            job_id,
            "failed",
            actor=actor,
            reason=technical_failure,
            sets=", technical_failure = %s, retry_safety = %s",
            params=(technical_failure, retry_safety),
        )

    def complete(self, job_id: str, outcome: CausalOutcome, *, actor: str) -> CausalJob:
        """Records the result of a running job: its digest is recomputed and it must be
        bound to the job's pinned spec. An overdue job is expired instead and the result
        refused (``JOB_EXPIRED``): a timeout never makes a partial result valid."""
        if not isinstance(outcome, CausalOutcome):
            raise CausalJobError("SCHEMA_VIOLATION", "a CausalOutcome is required")
        document = outcome_document(outcome)
        try:
            verified = outcome_from_document(document, outcome.reproducibility_digest)
        except CausalRuntimeError as exc:
            raise CausalJobError("RESULT_INVALID", "the outcome does not match its digest or schema") from exc
        spec_digest = _run_spec_digest(verified)
        digest = verified.reproducibility_digest

        def record(connection: psycopg.Connection[dict[str, Any]], job: CausalJob) -> str:
            if spec_digest != job.spec_digest:
                raise _PinMismatch()
            connection.execute(
                f"INSERT INTO {self._schema}.c7_job_result (job_id, spec_digest, result_version, outcome, reproducibility_digest) "
                "VALUES (%s, %s, 1, %s, %s)".encode(),
                (job_id, job.spec_digest, Jsonb(document), digest),
            )
            return f"COMPLETED:{verified.status}"

        try:
            return self._transit(
                "complete",
                job_id,
                "completed",
                actor=actor,
                reason="COMPLETED",
                extra=record,
                sets=", progress = '1', result_digest = %s, outcome_status = %s",
                params=(digest, verified.status),
                expire_when_overdue=True,
            )
        except _PinMismatch:
            raise CausalJobError("RESULT_PIN_MISMATCH", "the outcome is not bound to the job's pinned spec") from None

    def release_resources(self, job_id: str, *, actor: str) -> tuple[JobResource, ...]:
        """Releases every resource still held by a terminal job, in one transaction, and
        audits the release; a job that is not terminal keeps its resources."""
        _actor(job_id, "job_id")
        _actor(actor)

        def work(connection: psycopg.Connection[dict[str, Any]]) -> tuple[CausalJob, list[Any]]:
            job = self._job(self._job_row(connection, job_id, lock=True))
            if job.state not in TERMINAL_STATES:
                return job, []
            released = connection.execute(
                f"UPDATE {self._schema}.c7_job_resource SET released_at = clock_timestamp() "
                "WHERE job_id = %s AND released_at IS NULL RETURNING resource".encode(),
                (job_id,),
            ).fetchall()
            names = sorted(_released_name(row) for row in released)
            if names:
                self._audit(
                    connection, job_id=job_id, principal=job.principal, from_state=job.state, to_state="resources_released",
                    actor=actor, reason="RELEASED:" + ",".join(names),
                )
            return job, released

        job, _released = self._run("release_resources", work)
        if job.state not in TERMINAL_STATES:
            raise CausalJobError("INVALID_TRANSITION", f"a {job.state} job keeps its resources")
        return self.resources(job_id)


def _released_name(row: object) -> str:
    name = _stored_text(row, "resource")  # type: ignore[arg-type]
    if _RESOURCE.fullmatch(name) is None:
        raise _backend("a released resource is not a resource name")
    return str(name)


class _NotOverdue(Exception):
    pass


class _PinMismatch(Exception):
    pass


def _run_spec_digest(outcome: CausalOutcome) -> str | None:
    run = outcome.lineage.get("run")
    if not isinstance(run, Mapping):
        return None
    value = run.get("run_spec_digest")
    return value if isinstance(value, str) else None
