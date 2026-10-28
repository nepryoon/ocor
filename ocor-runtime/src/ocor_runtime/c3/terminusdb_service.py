"""C3 canonical commit slice on TerminusDB (OCOR-DEV-REM-0041).

Implements the sealed C3 ports (OCOR-DEV-0013, ``ocor_runtime.c3.ports``, reused
unmodified) -- ``GovernedCommitPort``, ``CanonicalReadPort``, ``OutboxRelayPort``,
``RevisionPort`` and ``RecoveryPort`` -- as a thin orchestrator over
``TerminusDBC3Adapter`` (``ocor_runtime.c3.adapters.terminusdb``). It mirrors
``PostgresC3Service`` (OCOR-DEV-0029, unchanged), so the two speak the same sealed
dataclasses; TerminusDB is the canonical ``VersionedAssertedState`` store of ADD v1.3
Part I §2.2/§2.4 and PostgreSQL stays the atomicity verification adapter
(LLD v1.1 §5.2), never an implicit fallback (DEC-201).

This module never imports a direct backend client (AFF-002/AFF-006).

``initialize`` creates the database and schema if absent and acquires a new writer
epoch: the most recently initialized service is the only writer of the ownership
boundary and every earlier instance is fenced (``SINGLE_WRITER_VIOLATION``).
``_crash_after`` on ``commit`` is the test-only fault-injection hook, as in
``PostgresC3Service``; the sealed ``GovernedCommitPort`` only declares
``commit(self, command)``.
"""

from __future__ import annotations

from datetime import datetime

from .adapters.terminusdb import (
    TerminusDBAdapterError,
    TerminusDBC3Adapter,
    TerminusDBCrashStage,
    TerminusDBUnavailable,
)
from .ports import (
    C3Error,
    CanonicalSnapshot,
    CommitReceipt,
    GovernedCanonicalCommitCommand,
    OutboxEnvelope,
)

__all__ = ["TerminusDBC3Service", "TerminusDBCrashStage", "TerminusDBUnavailable"]

# Adapter reason codes that are C3 contract outcomes; every other adapter failure
# (transport, contention, backend error) propagates unchanged and is never mapped to
# a generic contract code.
CONTRACT_REASONS = frozenset(
    {"REVISION_CONFLICT", "IDEMPOTENCY_CONFLICT", "SINGLE_WRITER_VIOLATION", "COMMIT_RECEIPT_MISMATCH"}
)


def _translate(error: TerminusDBAdapterError) -> Exception:
    if error.reason_code in CONTRACT_REASONS:
        return C3Error(error.reason_code, str(error))
    return error


class TerminusDBC3Service:
    """Real TerminusDB-backed implementation of the sealed C3 ports."""

    def __init__(
        self,
        *,
        url: str,
        password: str,
        database: str,
        writer_id: str = "c3-canonical-writer",
        timeout: float = 30.0,
    ) -> None:
        self._adapter = TerminusDBC3Adapter(
            url=url, password=password, database=database, writer_id=writer_id, timeout=timeout
        )

    @property
    def writer_epoch(self) -> int | None:
        return self._adapter.writer_epoch

    def initialize(self) -> None:
        self._adapter.initialize()
        self._adapter.acquire_writer()

    def drop(self) -> None:
        self._adapter.drop()

    def commit(
        self, command: GovernedCanonicalCommitCommand, *, _crash_after: TerminusDBCrashStage | None = None
    ) -> CommitReceipt:
        tenant_id, aggregate_type, aggregate_ref, idempotency_key = command.idempotency_scope
        try:
            outcome = self._adapter.commit_transaction(
                tenant_id=tenant_id,
                aggregate_type=aggregate_type,
                aggregate_ref=aggregate_ref,
                idempotency_key=idempotency_key,
                command_id=command.command_id,
                command_digest=command.command_digest,
                expected_revision=command.expected_revision,
                canonical_delta=command.canonical_delta,
                decision_ref=command.decision_ref,
                authority_ref=command.authority_ref,
                evidence_refs=command.evidence_refs,
                governed_context_digest=command.governed_context_digest,
                gate_package_digest=command.gate_package_digest,
                branch=command.branch,
                crash_after=_crash_after,
            )
        except TerminusDBAdapterError as error:
            raise _translate(error) from error

        return CommitReceipt.from_command(
            command,
            commit_id=outcome.commit_id,
            state_digest=outcome.state_digest,
            outbox_event_id=outcome.outbox_event_id,
            outbox_payload_digest=outcome.outbox_payload_digest,
            committed_at=outcome.committed_at,
            replayed=outcome.replayed,
        )

    def read(self, tenant_id: str, aggregate_type: str, aggregate_ref: str) -> CanonicalSnapshot | None:
        row = self._adapter.read_snapshot(tenant_id, aggregate_type, aggregate_ref)
        if row is None:
            return None
        return CanonicalSnapshot(
            tenant_id=tenant_id,
            aggregate_type=aggregate_type,
            aggregate_ref=aggregate_ref,
            revision=row.revision,
            state=row.state,
            state_digest=row.state_digest,
            commit_id=row.commit_id,
        )

    def current_revision(self, tenant_id: str, aggregate_type: str, aggregate_ref: str) -> int:
        return self._adapter.current_revision(tenant_id, aggregate_type, aggregate_ref)

    def claim_batch(self, *, limit: int) -> tuple[OutboxEnvelope, ...]:
        rows = self._adapter.claim_outbox_batch(limit=limit)
        return tuple(
            OutboxEnvelope(
                event_id=row.event_id,
                commit_id=row.commit_id,
                aggregate_ref=row.aggregate_ref,
                aggregate_revision=row.aggregate_revision,
                payload=row.payload,
                payload_digest=row.payload_digest,
                branch=row.branch,
                occurred_at=row.occurred_at,
            )
            for row in rows
        )

    def acknowledge(self, event_id: str, *, acknowledged_at: datetime) -> None:
        try:
            self._adapter.acknowledge_outbox(event_id, acknowledged_at=acknowledged_at)
        except TerminusDBAdapterError as error:
            raise _translate(error) from error

    def reconcile(self, *, limit: int) -> int:
        try:
            return self._adapter.reconcile(limit=limit)
        except TerminusDBAdapterError as error:
            raise _translate(error) from error
