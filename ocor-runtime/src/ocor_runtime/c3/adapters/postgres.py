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
from collections.abc import Callable, Mapping, Sequence
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
    outcome TEXT NOT NULL CHECK (outcome IN ('CLAIMED', 'ACKNOWLEDGED', 'FAILED')),
    writer_epoch BIGINT,
    claimed_until TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL,
    detail TEXT NOT NULL,
    PRIMARY KEY (event_id, attempt_no),
    CHECK (outcome <> 'ACKNOWLEDGED' OR writer_epoch IS NOT NULL),
    CHECK (outcome <> 'CLAIMED' OR claimed_until IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS c3_delivery_acknowledged_once
    ON c3_delivery_attempt (event_id) WHERE outcome = 'ACKNOWLEDGED';
"""

# Column sets the adapter relies on; a pre-existing table with another shape fails closed.
EXPECTED_COLUMNS: dict[str, frozenset[str]] = {
    "c3_writer_fence": frozenset({"boundary", "writer_epoch", "writer_id"}),
    "c3_commit": frozenset(
        {
            "commit_id", "command_id", "command_digest", "tenant_id", "aggregate_type", "aggregate_ref",
            "from_revision", "to_revision", "state_digest", "idempotency_key", "decision_ref", "authority_ref",
            "evidence_refs", "governed_context_digest", "gate_package_digest", "outbox_event_id", "outbox_payload",
            "outbox_payload_digest", "branch", "writer_epoch", "committed_at",
        }
    ),
    "c3_source_binding": frozenset({"commit_id", "claim_ref", "source_ref", "evidence_ref"}),
    "c3_outbox": frozenset(
        {"event_id", "commit_id", "aggregate_ref", "aggregate_revision", "payload", "payload_digest", "branch", "occurred_at"}
    ),
    "c3_delivery_attempt": frozenset(
        {"event_id", "attempt_no", "outcome", "writer_epoch", "claimed_until", "recorded_at", "detail"}
    ),
}

TABLES = ("c3_delivery_attempt", "c3_outbox", "c3_idempotency", "c3_source_binding", "c3_commit", "c3_aggregate")
FENCE_BOUNDARY = "c3-canonical"


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

    def initialize(self) -> None:
        """Creates the schema if absent; a pre-existing C3 table of another shape fails
        closed with ``SCHEMA_MISMATCH`` instead of being used or rewritten."""
        with psycopg.connect(self._dsn) as connection:
            connection.execute(SCHEMA)
            rows = connection.execute(
                """SELECT table_name, column_name FROM information_schema.columns
                   WHERE table_schema = current_schema() AND table_name = ANY(%s)""",
                (list(EXPECTED_COLUMNS),),
            ).fetchall()
        present: dict[str, set[str]] = {}
        for table, column in rows:
            present.setdefault(str(table), set()).add(str(column))
        divergent = sorted(name for name, columns in EXPECTED_COLUMNS.items() if present.get(name) != set(columns))
        if divergent:
            raise PostgresAdapterError("SCHEMA_MISMATCH", f"C3 tables differ from SCHEMA: {divergent}")

    def reset(self) -> None:
        """Empties canonical state, outbox and delivery records; the writer fence is the
        ownership boundary and is kept, so no fenced writer becomes current again."""
        with psycopg.connect(self._dsn) as connection:
            connection.execute("TRUNCATE " + ", ".join(TABLES))

    @property
    def writer_epoch(self) -> int | None:
        return self._epoch

    def acquire_writer(self) -> int:
        """Advances the epoch of the ownership boundary and becomes its only writer
        (ADD v1.3 §2.2 ``writer_epoch`` fencing); every earlier writer is fenced."""
        with psycopg.connect(self._dsn) as connection:
            row = connection.execute(
                """INSERT INTO c3_writer_fence (boundary, writer_epoch, writer_id) VALUES (%s, 1, %s)
                   ON CONFLICT (boundary) DO UPDATE SET
                       writer_epoch = c3_writer_fence.writer_epoch + 1, writer_id = EXCLUDED.writer_id
                   RETURNING writer_epoch""",
                (FENCE_BOUNDARY, self._writer_id),
            ).fetchone()
        if row is None:
            raise PostgresAdapterError("BACKEND_ERROR", "the writer fence returned no epoch")
        self._epoch = _positive("writer_epoch", row[0])
        return self._epoch

    def _hold_fence(self, connection: psycopg.Connection[Any]) -> int:
        """Inside a transaction: share-locks the fence row, so the epoch cannot advance
        before this transaction ends, and requires it to be this writer's own."""
        if self._epoch is None:
            raise PostgresAdapterError("SINGLE_WRITER_VIOLATION", "the writer has not acquired an epoch")
        row = connection.execute(
            "SELECT writer_epoch FROM c3_writer_fence WHERE boundary=%s FOR SHARE", (FENCE_BOUNDARY,)
        ).fetchone()
        stored = int(row["writer_epoch"]) if row is not None else 0
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
        connection = psycopg.connect(self._dsn, row_factory=dict_row)
        try:
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
                    if existing["command_digest"] != command_digest:
                        raise PostgresAdapterError(
                            "IDEMPOTENCY_CONFLICT",
                            "idempotency key or scope was rebound to different command content",
                        )
                    return CommitOutcome(
                        commit_id=existing["commit_id"],
                        from_revision=int(existing["from_revision"]),
                        to_revision=int(existing["to_revision"]),
                        state_digest=existing["state_digest"],
                        outbox_event_id=existing["outbox_event_id"],
                        outbox_payload_digest=existing["outbox_payload_digest"],
                        committed_at=existing["committed_at"],
                        replayed=True,
                    )

                revision = int(current["revision"]) if current is not None else 0
                if expected_revision != revision:
                    raise PostgresAdapterError(
                        "REVISION_CONFLICT", f"expected revision {expected_revision}, found {revision}"
                    )
                state = dict(current["state"]) if current is not None else {}
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
        finally:
            connection.close()

    def read_snapshot(self, tenant_id: str, aggregate_type: str, aggregate_ref: str) -> SnapshotRow | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                """SELECT revision, state, state_digest, commit_id FROM c3_aggregate
                   WHERE tenant_id=%s AND aggregate_type=%s AND aggregate_ref=%s""",
                (tenant_id, aggregate_type, aggregate_ref),
            ).fetchone()
        if row is None:
            return None
        return SnapshotRow(
            revision=int(row["revision"]),
            state=dict(row["state"]),
            state_digest=row["state_digest"],
            commit_id=row["commit_id"],
        )

    def current_revision(self, tenant_id: str, aggregate_type: str, aggregate_ref: str) -> int:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                """SELECT revision FROM c3_aggregate
                   WHERE tenant_id=%s AND aggregate_type=%s AND aggregate_ref=%s""",
                (tenant_id, aggregate_type, aggregate_ref),
            ).fetchone()
        return int(row["revision"]) if row is not None else 0

    def source_bindings(self, commit_id: str) -> tuple[SourceBindingRow, ...]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                """SELECT claim_ref, source_ref, evidence_ref FROM c3_source_binding WHERE commit_id=%s
                   ORDER BY claim_ref, source_ref, evidence_ref""",
                (commit_id,),
            ).fetchall()
        return tuple(SourceBindingRow(row["claim_ref"], row["source_ref"], row["evidence_ref"]) for row in rows)

    def claim_outbox_batch(self, *, limit: int, claim_ttl: timedelta) -> tuple[OutboxRow, ...]:
        """Acquires undelivered ``main`` rows with ``FOR UPDATE SKIP LOCKED`` (LLD v1.1 §2.3):
        a row another relay holds is skipped, never awaited nor shared. Each acquired row
        gets a ``CLAIMED`` DeliveryAttempt with a lease, so a concurrent claim after this
        transaction also skips it until the lease ends or a delivery outcome is recorded."""
        _positive("limit", limit)
        if not isinstance(claim_ttl, timedelta) or claim_ttl < timedelta(0):
            raise PostgresAdapterError("COMMIT_CONTRACT_INVALID", "claim_ttl must be a non-negative timedelta")
        now = datetime.now(UTC)
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                rows = connection.execute(
                    """SELECT o.event_id, o.commit_id, o.aggregate_ref, o.aggregate_revision, o.payload,
                              o.payload_digest, o.branch, o.occurred_at
                       FROM c3_outbox o
                       WHERE o.branch = 'main'
                         AND NOT EXISTS (SELECT 1 FROM c3_delivery_attempt d
                                         WHERE d.event_id = o.event_id AND d.outcome = 'ACKNOWLEDGED')
                         AND NOT EXISTS (SELECT 1 FROM c3_delivery_attempt d
                                         WHERE d.event_id = o.event_id AND d.outcome = 'CLAIMED'
                                           AND d.claimed_until > %s
                                           AND d.attempt_no = (SELECT max(attempt_no) FROM c3_delivery_attempt x
                                                               WHERE x.event_id = o.event_id))
                       ORDER BY o.occurred_at, o.event_id
                       LIMIT %s
                       FOR UPDATE OF o SKIP LOCKED""",
                    (now, limit),
                ).fetchall()
                # The candidate rows are now locked by this transaction; a fresh snapshot
                # drops any that a concurrent relay claimed and committed meanwhile.
                still_free = {
                    item["event_id"]
                    for item in connection.execute(
                        """SELECT o.event_id FROM c3_outbox o
                           WHERE o.event_id = ANY(%s)
                             AND NOT EXISTS (SELECT 1 FROM c3_delivery_attempt d
                                             WHERE d.event_id = o.event_id AND d.outcome = 'ACKNOWLEDGED')
                             AND NOT EXISTS (SELECT 1 FROM c3_delivery_attempt d
                                             WHERE d.event_id = o.event_id AND d.outcome = 'CLAIMED'
                                               AND d.claimed_until > %s
                                               AND d.attempt_no = (SELECT max(attempt_no) FROM c3_delivery_attempt x
                                                                   WHERE x.event_id = o.event_id))""",
                        ([row["event_id"] for row in rows], now),
                    ).fetchall()
                }
                rows = [row for row in rows if row["event_id"] in still_free]
                for row in rows:
                    self._record_attempt(
                        connection, row["event_id"], "CLAIMED", None, now, claimed_until=now + claim_ttl, detail=self._writer_id
                    )
        return tuple(
            OutboxRow(
                event_id=row["event_id"],
                commit_id=row["commit_id"],
                aggregate_ref=row["aggregate_ref"],
                aggregate_revision=int(row["aggregate_revision"]),
                payload=dict(row["payload"]),
                payload_digest=row["payload_digest"],
                branch=row["branch"],
                occurred_at=row["occurred_at"],
            )
            for row in rows
        )

    @staticmethod
    def _record_attempt(
        connection: psycopg.Connection[Any],
        event_id: str,
        outcome: str,
        writer_epoch: int | None,
        recorded_at: datetime,
        *,
        claimed_until: datetime | None = None,
        detail: str,
    ) -> None:
        connection.execute(
            """INSERT INTO c3_delivery_attempt
                   (event_id, attempt_no, outcome, writer_epoch, claimed_until, recorded_at, detail)
               SELECT %s, COALESCE(max(attempt_no), 0) + 1, %s, %s, %s, %s, %s
               FROM c3_delivery_attempt WHERE event_id = %s""",
            (event_id, outcome, writer_epoch, claimed_until, recorded_at, detail, event_id),
        )

    def _outbox_lock(self, connection: psycopg.Connection[Any], event_id: str) -> None:
        row = connection.execute(
            "SELECT branch FROM c3_outbox WHERE event_id=%s FOR UPDATE", (event_id,)
        ).fetchone()
        if row is None or row["branch"] != "main":
            raise PostgresAdapterError("OUTBOX_ENTRY_NOT_FOUND", f"no main outbox entry {event_id!r}")

    def acknowledge_outbox(self, event_id: str, *, acknowledged_at: datetime) -> None:
        """Records the delivery as a separate ``ACKNOWLEDGED`` DeliveryAttempt under the
        current writer epoch (ADD v1.3 §2.3); the outbox entry is never rewritten. A
        second acknowledgement of the same event is a no-op."""
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                epoch = self._hold_fence(connection)
                self._outbox_lock(connection, event_id)
                done = connection.execute(
                    "SELECT 1 FROM c3_delivery_attempt WHERE event_id=%s AND outcome='ACKNOWLEDGED'", (event_id,)
                ).fetchone()
                if done is None:
                    self._record_attempt(connection, event_id, "ACKNOWLEDGED", epoch, acknowledged_at, detail=self._writer_id)

    def record_delivery_failure(self, event_id: str, *, failed_at: datetime, reason: str) -> None:
        """Ends a claim with a ``FAILED`` DeliveryAttempt; the entry is relayed again."""
        if not isinstance(reason, str) or not reason:
            raise PostgresAdapterError("COMMIT_CONTRACT_INVALID", "a failure reason is required")
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                self._outbox_lock(connection, event_id)
                self._record_attempt(connection, event_id, "FAILED", self._epoch, failed_at, detail=reason[:512])

    def delivery_attempts(self, event_id: str) -> tuple[DeliveryAttemptRow, ...]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                """SELECT event_id, attempt_no, outcome, writer_epoch, recorded_at FROM c3_delivery_attempt
                   WHERE event_id=%s ORDER BY attempt_no""",
                (event_id,),
            ).fetchall()
        return tuple(
            DeliveryAttemptRow(
                event_id=row["event_id"],
                attempt_no=int(row["attempt_no"]),
                outcome=row["outcome"],
                writer_epoch=None if row["writer_epoch"] is None else int(row["writer_epoch"]),
                recorded_at=row["recorded_at"],
            )
            for row in rows
        )

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
        repaired = 0
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                self._hold_fence(connection)
                orphaned_idempotency = connection.execute(
                    """SELECT c.* FROM c3_commit c
                       LEFT JOIN c3_idempotency i ON i.commit_id = c.commit_id
                       WHERE i.commit_id IS NULL LIMIT %s""",
                    (limit,),
                ).fetchall()
                for row in orphaned_idempotency:
                    connection.execute(
                        """INSERT INTO c3_idempotency
                               (tenant_id, aggregate_type, aggregate_ref, idempotency_key, command_digest, commit_id)
                           VALUES (%s, %s, %s, %s, %s, %s)
                           ON CONFLICT DO NOTHING""",
                        (
                            row["tenant_id"],
                            row["aggregate_type"],
                            row["aggregate_ref"],
                            row["idempotency_key"],
                            row["command_digest"],
                            row["commit_id"],
                        ),
                    )
                    repaired += 1

                orphaned_outbox = connection.execute(
                    """SELECT c.* FROM c3_commit c
                       LEFT JOIN c3_outbox o ON o.commit_id = c.commit_id
                       WHERE o.commit_id IS NULL LIMIT %s""",
                    (limit,),
                ).fetchall()
                for row in orphaned_outbox:
                    payload = dict(row["outbox_payload"])
                    if canonical_digest(payload) != row["outbox_payload_digest"]:
                        raise PostgresAdapterError(
                            "COMMIT_RECEIPT_MISMATCH", f"commit {row['commit_id']!r} outbox payload digest mismatch"
                        )
                    connection.execute(
                        """INSERT INTO c3_outbox
                               (event_id, commit_id, aggregate_ref, aggregate_revision, payload, payload_digest,
                                branch, occurred_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT DO NOTHING""",
                        (
                            row["outbox_event_id"],
                            row["commit_id"],
                            row["aggregate_ref"],
                            int(row["to_revision"]),
                            Json(payload),
                            row["outbox_payload_digest"],
                            row["branch"],
                            row["committed_at"],
                        ),
                    )
                    repaired += 1
        return repaired
