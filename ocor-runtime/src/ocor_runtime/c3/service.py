"""Retained C3 canonical commit slice on PostgreSQL.

Implements the sealed C3 ports (OCOR-DEV-0013, ``ocor_runtime.c3.ports``) as a thin
orchestrator over ``PostgresC3Adapter`` (``ocor_runtime.c3.adapters.postgres``): state,
revision, evidence, source bindings, idempotency and outbox commit atomically in one
transaction. PostgreSQL is the atomicity verification adapter (LLD v1.1 §5.2) and is
never an implicit fallback of the canonical TerminusDB store (DEC-201).

OCOR-DEV-REM-0050 (NCP-U04): every commit first passes ``CommitAdmission`` (C6
provenance, Decision, Authority, Evidence, GatePackage, stop epoch and active release;
NCR-C3-001), and its preconditions and invariants are evaluated inside the transaction on
the locked state. ``initialize`` acquires a new writer epoch: the most recently
initialized service is the only writer of the ownership boundary and every earlier
instance is fenced (``SINGLE_WRITER_VIOLATION``; ADD v1.3 §2.2 :271). The relay claims
with ``SKIP LOCKED`` and records every delivery outcome as a separate DeliveryAttempt
(NCR-C3-004, NCR-C3-006).

This module never imports a direct backend client (AFF-002/AFF-006).

``_crash_after`` on ``commit`` is a keyword-only, underscore-prefixed test-only
fault-injection hook used exclusively by the C3 regression suites to prove real
process-crash recovery; the sealed ``GovernedCommitPort`` Protocol only declares
``commit(self, command)``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from .adapters.postgres import CrashStage, PostgresAdapterError, PostgresC3Adapter
from .admission import CommitAdmission
from .events import DeliveryAttempt, canonical_event_payload
from .ports import (
    C3Error,
    CanonicalSnapshot,
    ClaimSourceBinding,
    CommitReceipt,
    GovernedCanonicalCommitCommand,
    OutboxEnvelope,
)

__all__ = ["DEFAULT_CLAIM_TTL", "CrashStage", "PostgresC3Service"]

DEFAULT_CLAIM_TTL = timedelta(seconds=30)


def _translated(error: PostgresAdapterError) -> C3Error:
    return C3Error(error.reason_code, str(error))


class PostgresC3Service:
    """Real PostgreSQL-backed implementation of the sealed C3 ports."""

    def __init__(self, dsn: str, *, admission: CommitAdmission, writer_id: str = "c3-canonical-writer") -> None:
        if not isinstance(admission, CommitAdmission):
            raise TypeError("a CommitAdmission is required: C3 admits no command without the governed path")
        self._admission = admission
        self._adapter = PostgresC3Adapter(dsn, writer_id=writer_id)

    @property
    def writer_epoch(self) -> int | None:
        return self._adapter.writer_epoch

    def initialize(self) -> None:
        try:
            self._adapter.initialize()
            self._adapter.acquire_writer()
        except PostgresAdapterError as error:
            raise _translated(error) from error

    def reset(self) -> None:
        self._adapter.reset()

    def commit(
        self, command: GovernedCanonicalCommitCommand, *, _crash_after: CrashStage | None = None
    ) -> CommitReceipt:
        admitted = self._admission.admit(command)
        tenant_id, aggregate_type, aggregate_ref, idempotency_key = command.idempotency_scope

        def check_state(current: Mapping[str, Any], new: Mapping[str, Any]) -> None:
            self._admission.check_state(admitted, current, new)

        def event_payload(commit_id: str, from_revision: int, to_revision: int, state: Mapping[str, Any],
                          state_digest: str) -> dict[str, Any]:
            return canonical_event_payload(
                command, commit_id=commit_id, from_revision=from_revision, to_revision=to_revision, state=state,
                state_digest=state_digest,
            )

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
                claim_source_bindings=[item.to_mapping() for item in command.claim_source_bindings],
                governed_context_digest=command.governed_context_digest,
                gate_package_digest=command.gate_package_digest,
                branch=command.branch,
                check_state=check_state,
                event_payload=event_payload,
                crash_after=_crash_after,
            )
        except PostgresAdapterError as error:
            raise _translated(error) from error

        return CommitReceipt.from_command(
            command,
            commit_id=outcome.commit_id,
            state_digest=outcome.state_digest,
            outbox_event_id=outcome.outbox_event_id,
            outbox_payload_digest=outcome.outbox_payload_digest,
            committed_at=outcome.committed_at,
            replayed=outcome.replayed,
        )

    def read(
        self, tenant_id: str, aggregate_type: str, aggregate_ref: str
    ) -> CanonicalSnapshot | None:
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

    def source_bindings(self, commit_id: str) -> tuple[ClaimSourceBinding, ...]:
        return tuple(
            ClaimSourceBinding(item.claim_ref, item.source_ref, item.evidence_ref)
            for item in self._adapter.source_bindings(commit_id)
        )

    def claim_batch(self, *, limit: int, claim_ttl: timedelta = DEFAULT_CLAIM_TTL) -> tuple[OutboxEnvelope, ...]:
        try:
            rows = self._adapter.claim_outbox_batch(limit=limit, claim_ttl=claim_ttl)
        except PostgresAdapterError as error:
            raise _translated(error) from error
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
        except PostgresAdapterError as error:
            raise _translated(error) from error

    def record_failure(self, event_id: str, *, failed_at: datetime, reason: str) -> None:
        try:
            self._adapter.record_delivery_failure(event_id, failed_at=failed_at, reason=reason)
        except PostgresAdapterError as error:
            raise _translated(error) from error

    def delivery_attempts(self, event_id: str) -> tuple[DeliveryAttempt, ...]:
        return tuple(
            DeliveryAttempt(row.event_id, row.attempt_no, row.outcome, row.writer_epoch, row.recorded_at)
            for row in self._adapter.delivery_attempts(event_id)
        )

    def reconcile(self, *, limit: int) -> int:
        try:
            return self._adapter.reconcile(limit=limit)
        except PostgresAdapterError as error:
            raise _translated(error) from error
