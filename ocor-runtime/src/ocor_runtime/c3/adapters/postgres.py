"""Direct PostgreSQL client adapter for the retained C3 canonical commit
slice.

Every ``psycopg`` reference is confined to this module (AFF-002/AFF-006,
``OCOR_LANGUAGE_POLICY.md`` row 8: direct backend clients are restricted
to an ``adapters/`` subtree). This adapter exposes only plain,
psycopg-free Python types (dataclasses, dicts, primitives) to its caller
(``ocor_runtime.c3.service``), which never imports ``psycopg`` itself.

The real-concurrency locking/atomicity technique (an advisory-lock-guarded
transaction) matches what the sealed spikes already proved for real
(``spikes.c3_atomicity.oracle``, OCOR-DEV-0015; ``spikes.c3_backend``,
OCOR-DEV-0016), reimplemented here against the sealed C3 ports' own field
names rather than the spikes' ad-hoc schema.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from ...kernel.canonical import canonical_digest

SCHEMA = """
CREATE TABLE IF NOT EXISTS c3_writer_fence (
    boundary TEXT PRIMARY KEY,
    writer_epoch BIGINT NOT NULL CHECK (writer_epoch > 0),
    writer_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS c3_aggregate (
    tenant_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_ref TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK (revision >= 0),
    state JSONB NOT NULL,
    state_digest TEXT NOT NULL,
    commit_id TEXT NOT NULL,
    PRIMARY KEY (tenant_id, aggregate_type, aggregate_ref)
);
CREATE TABLE IF NOT EXISTS c3_commit (
    commit_id TEXT PRIMARY KEY,
    command_id TEXT NOT NULL,
    command_digest TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_ref TEXT NOT NULL,
    from_revision BIGINT NOT NULL,
    to_revision BIGINT NOT NULL CHECK (to_revision = from_revision + 1),
    state_digest TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    decision_ref TEXT NOT NULL,
    authority_ref TEXT NOT NULL,
    evidence_refs JSONB NOT NULL,
    governed_context_digest TEXT NOT NULL,
    gate_package_digest TEXT NOT NULL,
    outbox_event_id TEXT NOT NULL,
    outbox_payload JSONB NOT NULL,
    outbox_payload_digest TEXT NOT NULL,
    branch TEXT NOT NULL CHECK (branch = 'main'),
    writer_epoch BIGINT NOT NULL CHECK (writer_epoch > 0),
    committed_at TIMESTAMPTZ NOT NULL,
    UNIQUE (tenant_id, aggregate_type, aggregate_ref, to_revision)
);
CREATE TABLE IF NOT EXISTS c3_source_binding (
    commit_id TEXT NOT NULL REFERENCES c3_commit(commit_id),
    claim_ref TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    PRIMARY KEY (commit_id, claim_ref, source_ref, evidence_ref)
);
CREATE TABLE IF NOT EXISTS c3_idempotency (
    tenant_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    command_digest TEXT NOT NULL,
    commit_id TEXT NOT NULL REFERENCES c3_commit(commit_id),
    PRIMARY KEY (tenant_id, aggregate_type, aggregate_ref, idempotency_key)
);
CREATE TABLE IF NOT EXISTS c3_outbox (
    event_id TEXT PRIMARY KEY,
    commit_id TEXT NOT NULL UNIQUE REFERENCES c3_commit(commit_id),
    aggregate_ref TEXT NOT NULL,
    aggregate_revision BIGINT NOT NULL,
    payload JSONB NOT NULL,
    payload_digest TEXT NOT NULL,
    branch TEXT NOT NULL CHECK (branch = 'main'),
    occurred_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS c3_delivery_attempt (
    event_id TEXT NOT NULL REFERENCES c3_outbox(event_id),
    attempt_no BIGINT NOT NULL CHECK (attempt_no > 0),
    outcome TEXT NOT NULL CHECK (outcome IN ('ACKNOWLEDGED', 'FAILED')),
    writer_epoch BIGINT,
    recorded_at TIMESTAMPTZ NOT NULL,
    detail TEXT NOT NULL,
    PRIMARY KEY (event_id, attempt_no),
    CHECK (outcome <> 'ACKNOWLEDGED' OR writer_epoch IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS c3_delivery_acknowledged_once
    ON c3_delivery_attempt (event_id) WHERE outcome = 'ACKNOWLEDGED';
"""

# Column sets the adapter relies on; a pre-existing table with another shape fails closed.
EXPECTED_COLUMNS: dict[str, frozenset[str]] = {
    "c3_writer_fence": frozenset({"boundary", "writer_epoch", "writer_id"}),
    "c3_aggregate": frozenset(
        {"tenant_id", "aggregate_type", "aggregate_ref", "revision", "state", "state_digest", "commit_id"}
    ),
    "c3_commit": frozenset(
        {
            "commit_id", "command_id", "command_digest", "tenant_id", "aggregate_type", "aggregate_ref",
            "from_revision", "to_revision", "state_digest", "idempotency_key", "decision_ref", "authority_ref",
            "evidence_refs", "governed_context_digest", "gate_package_digest", "outbox_event_id", "outbox_payload",
            "outbox_payload_digest", "branch", "writer_epoch", "committed_at",
        }
    ),
    "c3_source_binding": frozenset({"commit_id", "claim_ref", "source_ref", "evidence_ref"}),
    "c3_idempotency": frozenset(
        {"tenant_id", "aggregate_type", "aggregate_ref", "idempotency_key", "command_digest", "commit_id"}
    ),
    "c3_outbox": frozenset(
        {"event_id", "commit_id", "aggregate_ref", "aggregate_revision", "payload", "payload_digest", "branch", "occurred_at"}
    ),
    "c3_delivery_attempt": frozenset(
        {"event_id", "attempt_no", "outcome", "writer_epoch", "recorded_at", "detail"}
    ),
}

COMMIT_COLUMNS = tuple(sorted(EXPECTED_COLUMNS["c3_commit"]))
OUTBOX_COLUMNS = ("event_id", "commit_id", "aggregate_ref", "aggregate_revision", "payload", "payload_digest", "branch",
                  "occurred_at")
ATTEMPT_COLUMNS = ("event_id", "attempt_no", "outcome", "writer_epoch", "recorded_at")
OUTCOMES = frozenset({"ACKNOWLEDGED", "FAILED"})

TABLES = ("c3_delivery_attempt", "c3_outbox", "c3_idempotency", "c3_source_binding", "c3_commit", "c3_aggregate")
FENCE_BOUNDARY = "c3-canonical"
CLAIM_APPLICATION = "ocor-c3-relay-claim"


class CrashStage(StrEnum):
    AFTER_AGGREGATE_UPSERT = "AFTER_AGGREGATE_UPSERT"
    AFTER_COMMIT_INSERT = "AFTER_COMMIT_INSERT"
    AFTER_IDEMPOTENCY_INSERT = "AFTER_IDEMPOTENCY_INSERT"
    AFTER_OUTBOX_INSERT = "AFTER_OUTBOX_INSERT"
    AFTER_COMMIT_BEFORE_ACK = "AFTER_COMMIT_BEFORE_ACK"


class PostgresAdapterError(RuntimeError):
    """Stable, bounded adapter failure; the caller translates
    ``reason_code`` into the sealed ``C3Error``."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True, slots=True)
class CommitOutcome:
    commit_id: str
    from_revision: int
    to_revision: int
    state_digest: str
    outbox_event_id: str
    outbox_payload_digest: str
    committed_at: datetime
    replayed: bool


@dataclass(frozen=True, slots=True)
class SnapshotRow:
    revision: int
    state: dict[str, Any]
    state_digest: str
    commit_id: str


@dataclass(frozen=True, slots=True)
class OutboxRow:
    event_id: str
    commit_id: str
    aggregate_ref: str
    aggregate_revision: int
    payload: dict[str, Any]
    payload_digest: str
    branch: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class SourceBindingRow:
    claim_ref: str
    source_ref: str
    evidence_ref: str


@dataclass(frozen=True, slots=True)
class DeliveryAttemptRow:
    event_id: str
    attempt_no: int
    outcome: str
    writer_epoch: int | None
    recorded_at: datetime


StateCheck = Callable[[Mapping[str, Any], Mapping[str, Any]], None]
EventPayload = Callable[[str, int, int, Mapping[str, Any], str], dict[str, Any]]


def _merge_delta(current: Mapping[str, Any], delta: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    merged.update(delta)
    return merged


def _positive(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PostgresAdapterError("COMMIT_CONTRACT_INVALID", f"{field} must be a positive integer")
    return value


def _stored_object(field: str, value: object) -> dict[str, Any]:
    """A JSONB column the adapter wrote as an object; any other stored value (array,
    scalar, null) fails closed instead of being coerced."""
    if not isinstance(value, dict):
        raise PostgresAdapterError("BACKEND_ERROR", f"stored {field} is not a JSON object")
    return dict(value)


# Every value read back from PostgreSQL is checked for its type, never converted: a row of
# another shape (missing column, bool or text for an integer, naive instant) fails closed.


def _row(value: object, columns: Sequence[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(name not in value for name in columns):
        raise PostgresAdapterError("BACKEND_ERROR", "a stored row is not of the expected shape")
    return value


def _stored_text(row: Mapping[str, Any], field: str) -> str:
    value = row[field]
    if not isinstance(value, str) or not value:
        raise PostgresAdapterError("BACKEND_ERROR", f"stored {field} is not a non-empty string")
    return value


def _stored_count(row: Mapping[str, Any], field: str, *, minimum: int) -> int:
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PostgresAdapterError("BACKEND_ERROR", f"stored {field} is not an integer >= {minimum}")
    return value


def _stored_instant(row: Mapping[str, Any], field: str) -> datetime:
    value = row[field]
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise PostgresAdapterError("BACKEND_ERROR", f"stored {field} is not a timezone-aware instant")
    return value


def _required_text(field: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise PostgresAdapterError("COMMIT_CONTRACT_INVALID", f"{field} must be a non-empty string")
    return value


def _required_instant(field: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise PostgresAdapterError("COMMIT_CONTRACT_INVALID", f"{field} must be a timezone-aware datetime")
    return value


def _driver_failure(operation: str, exc: psycopg.Error) -> PostgresAdapterError:
    """A driver failure as ``PostgresAdapterError``: an unreachable server is
    ``BACKEND_UNAVAILABLE``, any other refusal ``BACKEND_ERROR``; the server text is never
    echoed."""
    if isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
        return PostgresAdapterError("BACKEND_UNAVAILABLE", f"{operation}: PostgreSQL is unavailable")
    return PostgresAdapterError("BACKEND_ERROR", f"{operation}: PostgreSQL refused the statement ({type(exc).__name__})")


@contextmanager
def _driver(operation: str) -> Iterator[None]:
    """Driver failures leave the adapter only as ``PostgresAdapterError``."""
    try:
        yield
    except psycopg.Error as exc:
        raise _driver_failure(operation, exc) from exc


def _commit_outcome(row: object, *, replayed: bool) -> CommitOutcome:
    commit = _row(row, COMMIT_COLUMNS)
    from_revision = _stored_count(commit, "from_revision", minimum=0)
    to_revision = _stored_count(commit, "to_revision", minimum=1)
    if to_revision != from_revision + 1:
        raise PostgresAdapterError("COMMIT_RECEIPT_MISMATCH", "the stored commit revisions are not consecutive")
    return CommitOutcome(
        commit_id=_stored_text(commit, "commit_id"),
        from_revision=from_revision,
        to_revision=to_revision,
        state_digest=_stored_text(commit, "state_digest"),
        outbox_event_id=_stored_text(commit, "outbox_event_id"),
        outbox_payload_digest=_stored_text(commit, "outbox_payload_digest"),
        committed_at=_stored_instant(commit, "committed_at"),
        replayed=replayed,
    )


def _outbox_row(value: object) -> OutboxRow:
    row = _row(value, OUTBOX_COLUMNS)
    return OutboxRow(
        event_id=_stored_text(row, "event_id"),
        commit_id=_stored_text(row, "commit_id"),
        aggregate_ref=_stored_text(row, "aggregate_ref"),
        aggregate_revision=_stored_count(row, "aggregate_revision", minimum=1),
        payload=_stored_object("payload", row["payload"]),
        payload_digest=_stored_text(row, "payload_digest"),
        branch=_stored_text(row, "branch"),
        occurred_at=_stored_instant(row, "occurred_at"),
    )


def _attempt_row(value: object, event_id: str) -> DeliveryAttemptRow:
    row = _row(value, ATTEMPT_COLUMNS)
    if _stored_text(row, "event_id") != event_id:
        raise PostgresAdapterError("BACKEND_ERROR", "the backend listed an attempt of another event")
    outcome = _stored_text(row, "outcome")
    if outcome not in OUTCOMES:
        raise PostgresAdapterError("BACKEND_ERROR", "stored outcome is not a delivery outcome")
    epoch = None if row["writer_epoch"] is None else _stored_count(row, "writer_epoch", minimum=1)
    if outcome == "ACKNOWLEDGED" and epoch is None:
        raise PostgresAdapterError("BACKEND_ERROR", "a stored acknowledgement has no writer epoch")
    return DeliveryAttemptRow(
        event_id=event_id,
        attempt_no=_stored_count(row, "attempt_no", minimum=1),
        outcome=outcome,
        writer_epoch=epoch,
        recorded_at=_stored_instant(row, "recorded_at"),
    )


class PostgresC3Adapter:
    """The only module in this component that imports ``psycopg``."""

    def __init__(self, dsn: str, *, writer_id: str = "c3-canonical-writer") -> None:
        if not dsn:
            raise ValueError("a PostgreSQL DSN is required")
        if not isinstance(writer_id, str) or not writer_id:
            raise ValueError("a writer_id is required")
        self._dsn = dsn
        self._writer_id = writer_id
        self._epoch: int | None = None
        # The open relay claim: the transaction that holds the claimed outbox rows with
        # FOR UPDATE until each of them has a recorded delivery outcome.
        self._claim: psycopg.Connection[Any] | None = None
        self._claimed: set[str] = set()
        self._claim_lock = threading.RLock()

    def initialize(self) -> None:
        """Creates the schema if absent; a pre-existing C3 table of another shape fails
        closed with ``SCHEMA_MISMATCH`` instead of being used or rewritten."""
        with _driver("initialize"), psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            connection.execute(SCHEMA)
            rows = connection.execute(
                """SELECT table_name, column_name FROM information_schema.columns
                   WHERE table_schema = current_schema() AND table_name = ANY(%s)""",
                (list(EXPECTED_COLUMNS),),
            ).fetchall()
        present: dict[str, set[str]] = {}
        for value in rows:
            row = _row(value, ("table_name", "column_name"))
            present.setdefault(_stored_text(row, "table_name"), set()).add(_stored_text(row, "column_name"))
        divergent = sorted(name for name, columns in EXPECTED_COLUMNS.items() if present.get(name) != set(columns))
        if divergent:
            raise PostgresAdapterError("SCHEMA_MISMATCH", f"C3 tables differ from SCHEMA: {divergent}")

    def reset(self) -> None:
        """Empties canonical state, outbox and delivery records; the writer fence is the
        ownership boundary and is kept, so no fenced writer becomes current again."""
        self.close_claim()
        with _driver("reset"), psycopg.connect(self._dsn) as connection:
            # Relay claims of other instances hold row locks; emptying the store ends them
            # (their entries are gone with it) instead of waiting for their idle timeout.
            connection.execute(
                """SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                   WHERE application_name = %s AND datname = current_database() AND pid <> pg_backend_pid()""",
                (CLAIM_APPLICATION,),
            )
            connection.execute("TRUNCATE " + ", ".join(TABLES))

    @property
    def writer_epoch(self) -> int | None:
        return self._epoch

    def acquire_writer(self) -> int:
        """Advances the epoch of the ownership boundary and becomes its only writer
        (ADD v1.3 §2.2 ``writer_epoch`` fencing); every earlier writer is fenced."""
        with _driver("acquire_writer"), psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                """INSERT INTO c3_writer_fence (boundary, writer_epoch, writer_id) VALUES (%s, 1, %s)
                   ON CONFLICT (boundary) DO UPDATE SET
                       writer_epoch = c3_writer_fence.writer_epoch + 1, writer_id = EXCLUDED.writer_id
                   RETURNING writer_epoch""",
                (FENCE_BOUNDARY, self._writer_id),
            ).fetchone()
        if row is None:
            raise PostgresAdapterError("BACKEND_ERROR", "the writer fence returned no epoch")
        self._epoch = _stored_count(_row(row, ("writer_epoch",)), "writer_epoch", minimum=1)
        return self._epoch

    def join_writer(self, writer_epoch: int) -> None:
        """Adopts an epoch held by the same logical writer; never advances the fence."""
        self._epoch = _positive("writer_epoch", writer_epoch)

    def _hold_fence(self, connection: psycopg.Connection[Any]) -> int:
        """Inside a transaction: share-locks the fence row, so the epoch cannot advance
        before this transaction ends, and requires it to be this writer's own."""
        if self._epoch is None:
            raise PostgresAdapterError("SINGLE_WRITER_VIOLATION", "the writer has not acquired an epoch")
        row = connection.execute(
            "SELECT writer_epoch FROM c3_writer_fence WHERE boundary=%s FOR SHARE", (FENCE_BOUNDARY,)
        ).fetchone()
        stored = _stored_count(_row(row, ("writer_epoch",)), "writer_epoch", minimum=1) if row is not None else 0
        if stored != self._epoch:
            raise PostgresAdapterError(
                "SINGLE_WRITER_VIOLATION", f"stale writer epoch {self._epoch}, boundary epoch is {stored}"
            )
        return self._epoch

    @staticmethod
    def _crash(selected: CrashStage | None, target: CrashStage) -> None:
        if selected is target:
            os._exit(86)

    def commit_transaction(
        self,
        *,
        tenant_id: str,
        aggregate_type: str,
        aggregate_ref: str,
        idempotency_key: str,
        command_id: str,
        command_digest: str,
        expected_revision: int,
        canonical_delta: Mapping[str, Any],
        decision_ref: str,
        authority_ref: str,
        evidence_refs: Sequence[str],
        claim_source_bindings: Sequence[Mapping[str, str]],
        governed_context_digest: str,
        gate_package_digest: str,
        branch: str,
        check_state: StateCheck,
        event_payload: EventPayload,
        crash_after: CrashStage | None = None,
    ) -> CommitOutcome:
        """One transaction, lock order aggregate -> idempotency -> commit -> outbox
        (LLD v1.1 §2.3): writer fence, idempotency, revision, preconditions and
        invariants (``check_state``) are checked on the locked state before anything is
        written; the source bindings, the commit and the outbox entry are written with
        the state or not at all."""
        with _driver("commit"), psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                epoch = self._hold_fence(connection)
                lock_key = "\x1f".join((tenant_id, aggregate_type, aggregate_ref))
                connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))

                current = connection.execute(
                    """SELECT revision, state FROM c3_aggregate
                       WHERE tenant_id=%s AND aggregate_type=%s AND aggregate_ref=%s
                       FOR UPDATE""",
                    (tenant_id, aggregate_type, aggregate_ref),
                ).fetchone()
                existing = connection.execute(
                    """SELECT c.* FROM c3_idempotency i JOIN c3_commit c ON c.commit_id = i.commit_id
                       WHERE i.tenant_id=%s AND i.aggregate_type=%s AND i.aggregate_ref=%s
                         AND i.idempotency_key=%s""",
                    (tenant_id, aggregate_type, aggregate_ref, idempotency_key),
                ).fetchone()
                if existing is not None:
                    replay = _commit_outcome(existing, replayed=True)
                    if _stored_text(_row(existing, COMMIT_COLUMNS), "command_digest") != command_digest:
                        raise PostgresAdapterError(
                            "IDEMPOTENCY_CONFLICT",
                            "idempotency key or scope was rebound to different command content",
                        )
                    return replay

                stored = _row(current, ("revision", "state")) if current is not None else None
                revision = _stored_count(stored, "revision", minimum=0) if stored is not None else 0
                if expected_revision != revision:
                    raise PostgresAdapterError(
                        "REVISION_CONFLICT", f"expected revision {expected_revision}, found {revision}"
                    )
                state = _stored_object("state", stored["state"]) if stored is not None else {}
                new_state = _merge_delta(state, canonical_delta)
                check_state(state, new_state)
                new_state_digest = canonical_digest(new_state)
                to_revision = revision + 1

                commit_id = "urn:ocor:commit:sha256:" + hashlib.sha256(
                    f"{command_digest}:{to_revision}".encode()
                ).hexdigest()
                outbox_event_id = "urn:ocor:event:sha256:" + hashlib.sha256(
                    f"{commit_id}:outbox".encode()
                ).hexdigest()
                outbox_payload = event_payload(commit_id, revision, to_revision, new_state, new_state_digest)
                outbox_payload_digest = canonical_digest(outbox_payload)
                committed_at = datetime.now(UTC)

                connection.execute(
                    """INSERT INTO c3_aggregate
                           (tenant_id, aggregate_type, aggregate_ref, revision, state, state_digest, commit_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (tenant_id, aggregate_type, aggregate_ref) DO UPDATE SET
                           revision=EXCLUDED.revision, state=EXCLUDED.state,
                           state_digest=EXCLUDED.state_digest, commit_id=EXCLUDED.commit_id""",
                    (
                        tenant_id,
                        aggregate_type,
                        aggregate_ref,
                        to_revision,
                        Json(new_state),
                        new_state_digest,
                        commit_id,
                    ),
                )
                self._crash(crash_after, CrashStage.AFTER_AGGREGATE_UPSERT)

                connection.execute(
                    """INSERT INTO c3_commit
                           (commit_id, command_id, command_digest, tenant_id, aggregate_type, aggregate_ref,
                            from_revision, to_revision, state_digest, idempotency_key, decision_ref,
                            authority_ref, evidence_refs, governed_context_digest, gate_package_digest,
                            outbox_event_id, outbox_payload, outbox_payload_digest, branch, writer_epoch,
                            committed_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        commit_id,
                        command_id,
                        command_digest,
                        tenant_id,
                        aggregate_type,
                        aggregate_ref,
                        revision,
                        to_revision,
                        new_state_digest,
                        idempotency_key,
                        decision_ref,
                        authority_ref,
                        Json(list(evidence_refs)),
                        governed_context_digest,
                        gate_package_digest,
                        outbox_event_id,
                        Json(outbox_payload),
                        outbox_payload_digest,
                        branch,
                        epoch,
                        committed_at,
                    ),
                )
                for binding in claim_source_bindings:
                    connection.execute(
                        """INSERT INTO c3_source_binding (commit_id, claim_ref, source_ref, evidence_ref)
                           VALUES (%s, %s, %s, %s)""",
                        (commit_id, binding["claim_ref"], binding["source_ref"], binding["evidence_ref"]),
                    )
                self._crash(crash_after, CrashStage.AFTER_COMMIT_INSERT)

                connection.execute(
                    """INSERT INTO c3_idempotency
                           (tenant_id, aggregate_type, aggregate_ref, idempotency_key, command_digest, commit_id)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (tenant_id, aggregate_type, aggregate_ref, idempotency_key, command_digest, commit_id),
                )
                self._crash(crash_after, CrashStage.AFTER_IDEMPOTENCY_INSERT)

                connection.execute(
                    """INSERT INTO c3_outbox
                           (event_id, commit_id, aggregate_ref, aggregate_revision, payload, payload_digest,
                            branch, occurred_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        outbox_event_id,
                        commit_id,
                        aggregate_ref,
                        to_revision,
                        Json(outbox_payload),
                        outbox_payload_digest,
                        branch,
                        committed_at,
                    ),
                )
                self._crash(crash_after, CrashStage.AFTER_OUTBOX_INSERT)
            self._crash(crash_after, CrashStage.AFTER_COMMIT_BEFORE_ACK)
            return CommitOutcome(
                commit_id=commit_id,
                from_revision=revision,
                to_revision=to_revision,
                state_digest=new_state_digest,
                outbox_event_id=outbox_event_id,
                outbox_payload_digest=outbox_payload_digest,
                committed_at=committed_at,
                replayed=False,
            )

    @staticmethod
    def _scope(tenant_id: object, aggregate_type: object, aggregate_ref: object) -> tuple[str, str, str]:
        return (
            _required_text("tenant_id", tenant_id),
            _required_text("aggregate_type", aggregate_type),
            _required_text("aggregate_ref", aggregate_ref),
        )

    def read_snapshot(self, tenant_id: str, aggregate_type: str, aggregate_ref: str) -> SnapshotRow | None:
        self._scope(tenant_id, aggregate_type, aggregate_ref)
        with _driver("read_snapshot"), psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                """SELECT revision, state, state_digest, commit_id FROM c3_aggregate
                   WHERE tenant_id=%s AND aggregate_type=%s AND aggregate_ref=%s""",
                (tenant_id, aggregate_type, aggregate_ref),
            ).fetchone()
        if row is None:
            return None
        stored = _row(row, ("revision", "state", "state_digest", "commit_id"))
        return SnapshotRow(
            revision=_stored_count(stored, "revision", minimum=0),
            state=_stored_object("state", stored["state"]),
            state_digest=_stored_text(stored, "state_digest"),
            commit_id=_stored_text(stored, "commit_id"),
        )

    def current_revision(self, tenant_id: str, aggregate_type: str, aggregate_ref: str) -> int:
        self._scope(tenant_id, aggregate_type, aggregate_ref)
        with _driver("current_revision"), psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                """SELECT revision FROM c3_aggregate
                   WHERE tenant_id=%s AND aggregate_type=%s AND aggregate_ref=%s""",
                (tenant_id, aggregate_type, aggregate_ref),
            ).fetchone()
        return _stored_count(_row(row, ("revision",)), "revision", minimum=0) if row is not None else 0

    def source_bindings(self, commit_id: str) -> tuple[SourceBindingRow, ...]:
        _required_text("commit_id", commit_id)
        with _driver("source_bindings"), psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                """SELECT claim_ref, source_ref, evidence_ref FROM c3_source_binding WHERE commit_id=%s
                   ORDER BY claim_ref, source_ref, evidence_ref""",
                (commit_id,),
            ).fetchall()
        fields = ("claim_ref", "source_ref", "evidence_ref")
        return tuple(
            SourceBindingRow(*(_stored_text(_row(row, fields), name) for name in fields)) for row in rows
        )

    def close_claim(self) -> None:
        """Ends the open relay claim: recorded outcomes are committed and the rows still
        without an outcome are released, so they are relayed again with the same ID."""
        with self._claim_lock:
            claim, self._claim, self._claimed = self._claim, None, set()
            if claim is None:
                return
            try:
                if not claim.closed:
                    claim.commit()
            except psycopg.OperationalError:
                # The server already ended the claim (idle timeout or termination): its
                # uncommitted outcomes are void and its entries are relayed again with the
                # same ID (at-least-once, LLD v1.1 §2.3).
                claim.close()
                return
            except psycopg.Error as exc:
                claim.close()
                raise _driver_failure("close_claim", exc) from exc
            claim.close()

    def claim_outbox_batch(self, *, limit: int, claim_ttl: timedelta) -> tuple[OutboxRow, ...]:
        """Acquires undelivered ``main`` rows with ``FOR UPDATE SKIP LOCKED`` (LLD v1.1 §2.3):
        a row another relay holds is skipped, never awaited nor shared. The rows stay
        locked by this claim until each has a delivery outcome; a new claim first ends the
        previous one, and the server ends a claim left idle for ``claim_ttl``, so a relay
        that crashed or lost an acknowledgement never keeps an entry from being relayed."""
        _positive("limit", limit)
        if not isinstance(claim_ttl, timedelta) or claim_ttl < timedelta(0):
            raise PostgresAdapterError("COMMIT_CONTRACT_INVALID", "claim_ttl must be a non-negative timedelta")
        idle_ms = max(1000, int(claim_ttl.total_seconds() * 1000))
        with self._claim_lock:
            self.close_claim()
            with _driver("claim_outbox_batch"):
                claim = psycopg.connect(
                    self._dsn,
                    row_factory=dict_row,
                    application_name=CLAIM_APPLICATION,
                    options=f"-c idle_in_transaction_session_timeout={idle_ms}",
                )
            try:
                rows = [_outbox_row(row) for row in claim.execute(
                    """SELECT o.event_id, o.commit_id, o.aggregate_ref, o.aggregate_revision, o.payload,
                              o.payload_digest, o.branch, o.occurred_at
                       FROM c3_outbox o
                       WHERE o.branch = 'main'
                         AND NOT EXISTS (SELECT 1 FROM c3_delivery_attempt d
                                         WHERE d.event_id = o.event_id AND d.outcome = 'ACKNOWLEDGED')
                       ORDER BY o.occurred_at, o.event_id
                       LIMIT %s
                       FOR UPDATE SKIP LOCKED""",
                    (limit,),
                ).fetchall()]
                # The rows are locked now; a fresh snapshot drops any that a concurrent
                # relay acknowledged and committed after this statement's snapshot.
                acknowledged = {
                    _stored_text(_row(item, ("event_id",)), "event_id")
                    for item in claim.execute(
                        "SELECT event_id FROM c3_delivery_attempt WHERE outcome='ACKNOWLEDGED' AND event_id = ANY(%s)",
                        ([row.event_id for row in rows],),
                    ).fetchall()
                }
            except psycopg.Error as exc:
                claim.close()
                raise _driver_failure("claim_outbox_batch", exc) from exc
            except PostgresAdapterError:
                claim.close()
                raise
            rows = [row for row in rows if row.event_id not in acknowledged]
            if rows:
                self._claim, self._claimed = claim, {row.event_id for row in rows}
            else:
                claim.close()
        return tuple(rows)

    @staticmethod
    def _record_attempt(
        connection: psycopg.Connection[Any],
        event_id: str,
        outcome: str,
        writer_epoch: int | None,
        recorded_at: datetime,
        *,
        detail: str,
    ) -> None:
        connection.execute(
            """INSERT INTO c3_delivery_attempt (event_id, attempt_no, outcome, writer_epoch, recorded_at, detail)
               SELECT %s, COALESCE(max(attempt_no), 0) + 1, %s, %s, %s, %s
               FROM c3_delivery_attempt WHERE event_id = %s""",
            (event_id, outcome, writer_epoch, recorded_at, detail, event_id),
        )

    def _outbox_lock(self, connection: psycopg.Connection[Any], event_id: str) -> None:
        row = connection.execute(
            "SELECT branch FROM c3_outbox WHERE event_id=%s FOR UPDATE", (event_id,)
        ).fetchone()
        if row is None or _stored_text(_row(row, ("branch",)), "branch") != "main":
            raise PostgresAdapterError("OUTBOX_ENTRY_NOT_FOUND", f"no main outbox entry {event_id!r}")

    def _record_outcome(self, event_id: str, outcome: str, recorded_at: datetime, *, detail: str, fenced: bool) -> None:
        """Records an outcome in the claim that holds the row, or else in its own
        transaction; ends the claim once every claimed row has an outcome."""
        with self._claim_lock:
            claim = self._claim if event_id in self._claimed else None
            if claim is not None:
                try:
                    epoch = self._hold_fence(claim) if fenced else self._epoch
                    done = claim.execute(
                        "SELECT 1 FROM c3_delivery_attempt WHERE event_id=%s AND outcome='ACKNOWLEDGED'", (event_id,)
                    ).fetchone()
                    if done is None:
                        self._record_attempt(claim, event_id, outcome, epoch, recorded_at, detail=detail)
                except psycopg.OperationalError:
                    # The server ended the claim: record the outcome in its own transaction.
                    self._claim, self._claimed = None, set()
                    claim.close()
                except psycopg.Error as exc:
                    # The claim transaction is no longer usable: it ends, its uncommitted
                    # outcomes are void and its entries are relayed again with the same ID.
                    self._claim, self._claimed = None, set()
                    claim.close()
                    raise _driver_failure("record_outcome", exc) from exc
                else:
                    self._claimed.discard(event_id)
                    if not self._claimed:
                        self.close_claim()
                    return
        with _driver("record_outcome"), psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                epoch = self._hold_fence(connection) if fenced else self._epoch
                self._outbox_lock(connection, event_id)
                done = connection.execute(
                    "SELECT 1 FROM c3_delivery_attempt WHERE event_id=%s AND outcome='ACKNOWLEDGED'", (event_id,)
                ).fetchone()
                if done is None:
                    self._record_attempt(connection, event_id, outcome, epoch, recorded_at, detail=detail)

    def acknowledge_outbox(self, event_id: str, *, acknowledged_at: datetime) -> None:
        """Records the delivery as a separate ``ACKNOWLEDGED`` DeliveryAttempt under the
        current writer epoch (ADD v1.3 §2.3); the outbox entry is never rewritten. A
        second acknowledgement of the same event is a no-op."""
        _required_text("event_id", event_id)
        _required_instant("acknowledged_at", acknowledged_at)
        self._record_outcome(event_id, "ACKNOWLEDGED", acknowledged_at, detail=self._writer_id, fenced=True)

    def record_delivery_failure(self, event_id: str, *, failed_at: datetime, reason: str) -> None:
        """Records a ``FAILED`` DeliveryAttempt; the entry is relayed again."""
        _required_text("event_id", event_id)
        _required_instant("failed_at", failed_at)
        if not isinstance(reason, str) or not reason:
            raise PostgresAdapterError("COMMIT_CONTRACT_INVALID", "a failure reason is required")
        self._record_outcome(event_id, "FAILED", failed_at, detail=reason[:512], fenced=False)

    def delivery_attempts(self, event_id: str) -> tuple[DeliveryAttemptRow, ...]:
        _required_text("event_id", event_id)
        with _driver("delivery_attempts"), psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                """SELECT event_id, attempt_no, outcome, writer_epoch, recorded_at FROM c3_delivery_attempt
                   WHERE event_id=%s ORDER BY attempt_no""",
                (event_id,),
            ).fetchall()
        return tuple(_attempt_row(row, event_id) for row in rows)

    def reconcile(self, *, limit: int) -> int:
        """Real defense-in-depth repair pass: every commit row must have a
        matching idempotency row and a matching outbox row. Under normal
        operation this is always true by transactional atomicity -- a
        crash mid-commit rolls the whole transaction back, leaving nothing
        partial to reconcile. This exists to recover from a genuine crash
        fixture (a simulated corruption: a derived row deleted after the
        fact) by re-deriving the missing row from the commit row's own
        fields, never by fabricating new commit content. Only the current
        writer repairs."""
        _positive("limit", limit)
        repaired = 0
        with _driver("reconcile"), psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                self._hold_fence(connection)
                orphaned_idempotency = connection.execute(
                    """SELECT c.* FROM c3_commit c
                       LEFT JOIN c3_idempotency i ON i.commit_id = c.commit_id
                       WHERE i.commit_id IS NULL LIMIT %s""",
                    (limit,),
                ).fetchall()
                for value in orphaned_idempotency:
                    row = _row(value, COMMIT_COLUMNS)
                    connection.execute(
                        """INSERT INTO c3_idempotency
                               (tenant_id, aggregate_type, aggregate_ref, idempotency_key, command_digest, commit_id)
                           VALUES (%s, %s, %s, %s, %s, %s)
                           ON CONFLICT DO NOTHING""",
                        tuple(
                            _stored_text(row, name)
                            for name in (
                                "tenant_id", "aggregate_type", "aggregate_ref", "idempotency_key", "command_digest",
                                "commit_id",
                            )
                        ),
                    )
                    repaired += 1

                orphaned_outbox = connection.execute(
                    """SELECT c.* FROM c3_commit c
                       LEFT JOIN c3_outbox o ON o.commit_id = c.commit_id
                       WHERE o.commit_id IS NULL LIMIT %s""",
                    (limit,),
                ).fetchall()
                for value in orphaned_outbox:
                    row = _row(value, COMMIT_COLUMNS)
                    commit = _commit_outcome(row, replayed=False)
                    payload = _stored_object("outbox_payload", row["outbox_payload"])
                    try:
                        derived = canonical_digest(payload)
                    except (TypeError, ValueError) as exc:
                        raise PostgresAdapterError("BACKEND_ERROR", "a stored outbox payload is not I-JSON") from exc
                    if derived != commit.outbox_payload_digest:
                        raise PostgresAdapterError(
                            "COMMIT_RECEIPT_MISMATCH", f"commit {commit.commit_id!r} outbox payload digest mismatch"
                        )
                    connection.execute(
                        """INSERT INTO c3_outbox
                               (event_id, commit_id, aggregate_ref, aggregate_revision, payload, payload_digest,
                                branch, occurred_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT DO NOTHING""",
                        (
                            commit.outbox_event_id,
                            commit.commit_id,
                            _stored_text(row, "aggregate_ref"),
                            commit.to_revision,
                            Json(payload),
                            commit.outbox_payload_digest,
                            _stored_text(row, "branch"),
                            commit.committed_at,
                        ),
                    )
                    repaired += 1
        return repaired
