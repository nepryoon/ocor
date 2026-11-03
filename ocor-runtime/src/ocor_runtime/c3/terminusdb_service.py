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

OCOR-DEV-REM-0050 (NCP-U04): every commit first passes ``CommitAdmission`` (NCR-C3-001)
and its preconditions and invariants are evaluated on the state the commit replaces;
claim/source bindings are ``C3SourceBinding`` documents of the same local commit
(NCR-C3-004); the event payload is fixed in the commit (NCR-C3-003); an acknowledgement
is accepted only under the current writer epoch (NCR-C3-007).

``initialize`` creates the database and schema if absent and acquires a new writer
epoch: the most recently initialized service is the only writer of the ownership
boundary and every earlier instance is fenced (``SINGLE_WRITER_VIOLATION``).
``_crash_after`` on ``commit`` is the test-only fault-injection hook, as in
``PostgresC3Service``; the sealed ``GovernedCommitPort`` only declares
``commit(self, command)``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from .adapters.terminusdb import (
    TerminusDBAdapterError,
    TerminusDBC3Adapter,
    TerminusDBCrashStage,
    TerminusDBUnavailable,
)
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

__all__ = ["TerminusDBC3Service", "TerminusDBCrashStage", "TerminusDBUnavailable"]

# Adapter reason codes that are C3 contract outcomes; every other adapter failure
# (transport, contention, backend error) propagates unchanged and is never mapped to
# a generic contract code.
CONTRACT_REASONS = frozenset(
    {
        "REVISION_CONFLICT",
        "IDEMPOTENCY_CONFLICT",
        "SINGLE_WRITER_VIOLATION",
        "COMMIT_RECEIPT_MISMATCH",
        "PRECONDITION_FAILED",
        "INVARIANT_VIOLATION",
    }
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
        admission: CommitAdmission,
        writer_id: str = "c3-canonical-writer",
        timeout: float = 30.0,
        writer_epoch: int | None = None,
    ) -> None:
        if not isinstance(admission, CommitAdmission):
            raise TypeError("a CommitAdmission is required: C3 admits no command without the governed path")
        self._admission = admission
        self._adapter = TerminusDBC3Adapter(
            url=url, password=password, database=database, writer_id=writer_id, timeout=timeout
        )
        self._joined = writer_epoch is not None
        if writer_epoch is not None:
            self._adapter.join_writer(writer_epoch)

    @property
    def writer_epoch(self) -> int | None:
        return self._adapter.writer_epoch

    def initialize(self) -> None:
        self._adapter.initialize()
        if not self._joined:
            self._adapter.acquire_writer()

    def drop(self) -> None:
        self._adapter.drop()

    def commit(
        self, command: GovernedCanonicalCommitCommand, *, _crash_after: TerminusDBCrashStage | None = None
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

    def source_bindings(self, commit_id: str) -> tuple[ClaimSourceBinding, ...]:
        try:
            rows = self._adapter.source_bindings(commit_id)
        except TerminusDBAdapterError as error:
            raise _translate(error) from error
        return tuple(ClaimSourceBinding(item.claim_ref, item.source_ref, item.evidence_ref) for item in rows)

    def delivery_attempts(self, event_id: str) -> tuple[DeliveryAttempt, ...]:
        try:
            rows = self._adapter.delivery_attempts(event_id)
        except TerminusDBAdapterError as error:
            raise _translate(error) from error
        return tuple(
            DeliveryAttempt(row.event_id, row.attempt_no, row.outcome, row.writer_epoch, row.recorded_at) for row in rows
        )

    def claim_batch(self, *, limit: int, claim_ttl: timedelta = timedelta(seconds=30)) -> tuple[OutboxEnvelope, ...]:
        """The TerminusDB relay has one logical writer per ownership boundary (ADD v1.3
        §2.2): it reads the undelivered ``main`` entries without a claim record, and only
        the writer holding the current epoch can confirm a delivery (NCR-C3-007). The
        lease ``claim_ttl`` of the PostgreSQL relay has no TerminusDB equivalent; it is
        validated and not stored."""
        if not isinstance(claim_ttl, timedelta) or claim_ttl < timedelta(0):
            raise C3Error("COMMIT_CONTRACT_INVALID", "claim_ttl must be a non-negative timedelta")
        try:
            rows = self._adapter.claim_outbox_batch(limit=limit)
        except TerminusDBAdapterError as error:
            raise _translate(error) from error
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

    def record_failure(self, event_id: str, *, failed_at: datetime, reason: str) -> None:
        """A failed publish leaves the entry undelivered; with no claim to release there is
        nothing to write, and the entry is relayed again on the next pass."""
        if not isinstance(reason, str) or not reason:
            raise C3Error("COMMIT_CONTRACT_INVALID", "a failure reason is required")
        if not isinstance(failed_at, datetime) or failed_at.utcoffset() is None:
            raise C3Error("COMMIT_CONTRACT_INVALID", "failed_at must be timezone-aware")

    def reconcile(self, *, limit: int) -> int:
        try:
            return self._adapter.reconcile(limit=limit)
        except TerminusDBAdapterError as error:
            raise _translate(error) from error
