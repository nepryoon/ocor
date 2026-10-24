"""Partition-bound memory operations (ADD v1.3 II 2.6/2.10/2.13).

Quota checks are admission diagnostics, not reservations or tokens of authority.
The caller must still use the admission/retrieval/consolidation boundary. Pressure
uses the existing lifecycle saga; this module never deletes content or a tombstone
directly. Monitoring reads only the authorised full isolation partition. Metrics
have fixed labels and belong to the protected operator plane, never a user response.

``MemoryQuotaWriter`` applies the configured quotas to real admission + store
commits, with demand derived from the actual payload/candidate and a trusted
partition serialization port. ``MemoryBackupService`` captures a signed,
digest-only backup manifest; ``MemoryRestoreGate`` reopens restored memory only
after custodian authentication, a stale-epoch check, the 0056 tombstone replay
and an exact projection comparison. Store snapshots themselves remain the
0049/0056 recovery-point procedure; no RTO/RPO or recovery conformance is claimed.
The final control check and effects at the independent lifecycle/audit stores are
not an atomic transaction; no cross-process admission or timing claim is made.
"""
from __future__ import annotations

import hashlib
import re
import threading
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, TypeVar

from ..kernel.canonical import (
    TimestampError, canonical_bytes, canonical_digest, format_utc_timestamp, parse_i_json, parse_utc_timestamp,
)
from ..kernel.governance import TrustedClock
from ..kernel.governed_context import (
    GovernedContext, GovernedContextCodec, GovernedContextError, VerifiedGovernedContextBinding,
)
from .deletion import (
    RECOVERY_POINT_PATTERN, DeletionCheckpointAuthority, DeletionJournalCheckpoint, DeletionJournalSnapshot,
    DeletionRecoveryError, DeletionRestoreGate,
)
from .lifecycle import MemoryLifecycleCoordinator, TombstoneEntry
from .model import (
    ENVELOPE_FIELDS, AdmittedMemoryVersion, GovernedMemoryItem, LifecycleStatus,
    MemoryAdmissionError, MemoryAdmissionService, MemoryPolicyDecision, MemoryVersionLedger, RepresentationKind,
)
from .retrieval import RetrievalAuditSink, StopEpochPort
from .stores import (
    MemoryMetadataStore, MemoryPartition, MemoryStoreCoordinator, StoreCommitReceipt, StoredVersion,
    VersionState, validate_embedding,
)


class MemoryOperationsError(MemoryAdmissionError):
    """Closed public memory reason and a bounded operational detail code."""


def _error(detail: str, reason: str = "POLICY_DENIED") -> MemoryOperationsError:
    return MemoryOperationsError(reason, detail, "memory operation refused")


def _integer(value: object, *, positive: bool = False) -> bool:
    return type(value) is int and value >= (1 if positive else 0)


@dataclass(frozen=True, slots=True)
class MemoryOperationsLimits:
    """PoC configuration, not a frozen global performance or compliance threshold."""

    max_items: int = 10000
    max_payload_bytes: int = 1024 * 1024
    max_embedding_dimensions: int = 4096
    max_top_k: int = 100
    max_consolidation_concurrency: int = 4
    max_index_entries: int = 30000
    max_pressure_batch: int = 100
    retention_horizons: Mapping[str, timedelta] = field(
        default_factory=lambda: {"retention:standard": timedelta(days=365)}
    )

    def __post_init__(self) -> None:
        for member in fields(self):
            if member.name != "retention_horizons" and not _integer(getattr(self, member.name), positive=True):
                raise ValueError("operation limits must be positive integers")
        horizons = dict(self.retention_horizons)
        if not horizons or any(not isinstance(k, str) or not k or not isinstance(v, timedelta)
                               or v <= timedelta(0) for k, v in horizons.items()):
            raise ValueError("configured positive retention horizons required")
        object.__setattr__(self, "retention_horizons", MappingProxyType(horizons))


@dataclass(frozen=True, slots=True)
class MemoryQuotaDemand:
    """The declared resource demand; this is not a resource reservation."""

    new_items: int = 0
    payload_bytes: int = 0
    embedding_dimensions: int = 0
    top_k: int = 0
    consolidation_concurrency: int = 0
    new_index_entries: int = 0
    retention_seconds: int = 0
    retention_policy_ref: str = "retention:standard"

    def __post_init__(self) -> None:
        if any(not _integer(getattr(self, f.name)) for f in fields(self) if f.name != "retention_policy_ref"):
            raise ValueError("quota demand members must be non-negative integers")
        if not isinstance(self.retention_policy_ref, str) or not self.retention_policy_ref:
            raise ValueError("quota demand requires a retention policy reference")


class MemoryOperationsPolicy(Protocol):
    """Authenticate workload/authority and authorise this exact operation/partition.

    The provider must enforce scope owner bindings as well as the transport GCS;
    the caller cannot provide the policy implementation or an authority decision.
    """

    def authorize_operations(
        self, operation: str, partition: MemoryPartition, context: GovernedContext,
    ) -> MemoryPolicyDecision: ...


@dataclass(frozen=True, slots=True)
class MemoryUsage:
    items: int
    held_items: int
    incomplete_deletions: int
    index_entries: int
    tombstones: int

    def to_mapping(self) -> dict[str, object]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(frozen=True, slots=True)
class QuotaCheck:
    permitted: bool
    usage: MemoryUsage
    audit_ref: str = ""


@dataclass(frozen=True, slots=True)
class MemoryPressureReport:
    deleted: tuple[str, ...]
    incomplete: tuple[str, ...]
    held: tuple[str, ...]
    remaining_items: int
    satisfied: bool
    audit_ref: str = ""


@dataclass(frozen=True, slots=True)
class _Plan:
    context: GovernedContext
    partition: MemoryPartition
    operation_id: str
    deadline: datetime
    stop_epoch: int


@dataclass(frozen=True, slots=True)
class _Head:
    record: AdmittedMemoryVersion
    stored: StoredVersion
    first_created_at: datetime


R = TypeVar("R", MemoryUsage, QuotaCheck, MemoryPressureReport, StoreCommitReceipt, "SignedMemoryBackup")
T = TypeVar("T")
ENVELOPE = frozenset({"operation_id", "governed_context", "governed_context_digest", "partition", "deadline"})


class MemoryOperationsService:
    """Explicit operational port, with authenticated policy-before-inventory."""

    def __init__(
        self, *, metadata: MemoryMetadataStore, ledger: MemoryVersionLedger,
        lifecycle: MemoryLifecycleCoordinator, policy: MemoryOperationsPolicy,
        audit: RetrievalAuditSink, stop: StopEpochPort, clock: TrustedClock,
        limits: MemoryOperationsLimits,
    ) -> None:
        self._metadata, self._ledger, self._lifecycle = metadata, ledger, lifecycle
        self._policy, self._audit, self._stop, self._clock, self._limits = policy, audit, stop, clock, limits
        self._lock = threading.RLock()
        self.metrics: Counter[tuple[str, str, str]] = Counter()

    def _append(self, event: dict[str, object]) -> str:
        ref = canonical_digest(event)
        try:
            self._audit.record(MappingProxyType({**event, "audit_ref": ref}))
        except Exception as exc:  # noqa: BLE001 -- mandatory audit authority
            raise _error("AUDIT_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc
        return ref

    def _epoch(self, context: GovernedContext) -> int:
        try:
            epoch = self._stop.current_epoch(context)
        except Exception as exc:  # noqa: BLE001 -- unavailable control denies
            raise _error("STOP_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc
        if not _integer(epoch):
            raise _error("STOP_STATE_INVALID", "CONTROL_PLANE_UNAVAILABLE")
        return epoch

    def _authorize(self, operation: str, partition: MemoryPartition, ctx: GovernedContext) -> None:
        try:
            decision = self._policy.authorize_operations(operation, partition, ctx)
        except Exception as exc:  # noqa: BLE001 -- unavailable policy denies
            raise _error("POLICY_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc
        if not isinstance(decision, MemoryPolicyDecision) or type(decision.permitted) is not bool or not decision.decision_ref:
            raise _error("POLICY_DECISION_INVALID", "CONTROL_PLANE_UNAVAILABLE")
        if decision.policy_bundle_digest != ctx.policy_bundle_digest:
            raise _error("STALE_POLICY", "STALE_POLICY")
        if not decision.permitted:
            raise _error("OPERATIONS_DENIED")

    def _plan(self, operation: str, request: Mapping[str, object], binding: VerifiedGovernedContextBinding) -> _Plan:
        if not isinstance(request, Mapping) or set(request) != ENVELOPE:
            raise _error("ENVELOPE_INVALID", "MEMORY_SCHEMA_INVALID")
        op, raw, claimed, partition_body, deadline = (request[k] for k in (
            "operation_id", "governed_context", "governed_context_digest", "partition", "deadline"))
        if not isinstance(op, str) or not 1 <= len(op) <= 128 or any(ord(c) < 32 for c in op):
            raise _error("ENVELOPE_INVALID", "MEMORY_SCHEMA_INVALID")
        if not isinstance(raw, Mapping) or not isinstance(claimed, str):
            raise _error("GCS_INVALID", "GOVERNED_CONTEXT_MISMATCH")
        try:
            ctx = GovernedContextCodec.from_openapi(raw, binding, claimed)
        except GovernedContextError as exc:
            raise _error("GCS_INVALID", "GOVERNED_CONTEXT_MISMATCH") from exc
        if not isinstance(partition_body, Mapping):
            raise _error("PARTITION_INVALID", "MEMORY_SCHEMA_INVALID")
        try:
            partition = MemoryPartition.from_mapping(partition_body)
        except MemoryAdmissionError as exc:
            raise _error("PARTITION_INVALID", "MEMORY_SCHEMA_INVALID") from exc
        # The full isolation tuple is matched before any inventory lookup.
        # Scope/owner memberships are checked by the live operations authority.
        for name in ("tenant_id", "organization_id", "domain_id", "compartments", "classification_marking_ref",
                     "purpose", "policy_bundle_digest", "ontology_release_digest"):
            actual, expected = getattr(partition, name), getattr(ctx, name)
            if (tuple(sorted(actual)) if name == "compartments" else actual) != (
                tuple(sorted(expected)) if name == "compartments" else expected
            ):
                raise _error("PARTITION_DENIED")
        try:
            if not isinstance(deadline, str):
                raise ValueError("invalid deadline")
            until = parse_utc_timestamp(deadline)
        except (TimestampError, ValueError) as exc:
            raise _error("ENVELOPE_INVALID", "MEMORY_SCHEMA_INVALID") from exc
        if until <= self._clock.now():
            raise _error("DEADLINE_EXCEEDED")
        self._authorize(operation, partition, ctx)
        return _Plan(ctx, partition, op, until, self._epoch(ctx))

    def _check(self, operation: str, plan: _Plan) -> None:
        if plan.deadline <= self._clock.now():
            raise _error("DEADLINE_EXCEEDED")
        self._authorize(operation, plan.partition, plan.context)
        if self._epoch(plan.context) != plan.stop_epoch:
            raise _error("STOP_EPOCH_MISMATCH", "STOP_EPOCH_MISMATCH")

    def _guard(
        self, operation: str, request: Mapping[str, object], binding: VerifiedGovernedContextBinding | None,
        action: Callable[[_Plan], R], *, mutative: bool = False,
        prepare: Callable[[], Mapping[str, object]] | None = None,
    ) -> R:
        verified = None
        plan = None
        try:
            if not isinstance(binding, VerifiedGovernedContextBinding):
                raise _error("BINDING_MISSING", "AUTHENTICATION_REQUIRED")
            verified = binding
            plan = self._plan(operation, prepare() if prepare is not None else request, binding)
            with self._lock:
                if mutative:
                    self._event(operation, "STARTED", verified, plan)
                result = action(plan)
                self._check(operation, plan)
                outcome = "BACKPRESSURE" if isinstance(result, MemoryPressureReport) and not result.satisfied else "COMPLETED"
                audit_ref = self._event(operation, outcome, verified, plan)
                self.metrics[(operation, outcome, "NONE")] += 1
                if isinstance(result, (QuotaCheck, MemoryPressureReport)):
                    return replace(result, audit_ref=audit_ref)
                return result
        except MemoryAdmissionError as exc:
            error = exc if isinstance(exc, MemoryOperationsError) else _error(exc.detail_code, exc.reason_code)
            self.metrics[(operation, "DENIED", error.reason_code)] += 1
            self._event(operation, "DENIED", verified, plan, error)
            raise error from exc
        except Exception as exc:  # noqa: BLE001 -- inventory/port failure is never zero usage
            error = _error("OPERATIONS_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE")
            self.metrics[(operation, "DENIED", error.reason_code)] += 1
            self._event(operation, "DENIED", verified, plan, error)
            raise error from exc

    def _event(
        self, operation: str, outcome: str, binding: VerifiedGovernedContextBinding | None,
        plan: _Plan | None, error: MemoryOperationsError | None = None,
    ) -> str:
        return self._append({
            "action": operation + (".denied" if error else "." + outcome.lower()),
            "outcome": outcome, "reason_code": error.reason_code if error else "NONE",
            "detail_code": error.detail_code if error else "NONE",
            "operation_id": plan.operation_id if plan else None,
            "causation_id": plan.operation_id if plan else None,
            "correlation_id": binding.expected.correlation_id if binding else None,
            "governed_context_digest": plan.context.digest() if plan else None,
            "partition_digest": plan.partition.digest if plan else None,
            "evaluated_at": format_utc_timestamp(self._clock.now()),
        })

    def _heads(self, partition: MemoryPartition) -> tuple[_Head, ...]:
        heads: dict[str, _Head] = {}
        rows = self._metadata.versions_in(partition.digest)
        for stored in rows:
            item_id = stored.staged.memory_item_id
            if item_id in heads:
                continue
            version = self._metadata.head(item_id)
            if self._ledger.latest_version(item_id) != version:
                raise _error("HEAD_NOT_COMMITTED", "REPRESENTATION_NOT_READY")
            head = self._metadata.get(item_id, version)
            if head is None or head.state is not VersionState.COMMITTED:
                raise _error("HEAD_NOT_COMMITTED", "REPRESENTATION_NOT_READY")
            # A head reclassified into another partition must not be counted here.
            if head.staged.partition.digest != partition.digest:
                continue
            record = self._ledger.get(item_id, version)
            first = self._ledger.get(item_id, 1)
            if record is None or first is None:
                raise _error("LEDGER_DRIFT", "REPRESENTATION_NOT_READY")
            record.verify()
            if head.staged.verify().digest() != record.item_digest:
                raise _error("LEDGER_DRIFT", "REPRESENTATION_NOT_READY")
            heads[item_id] = _Head(record, head, first.item.created_at)
        for item_id, selected in heads.items():
            version = selected.record.item.memory_version
            current = self._metadata.get(item_id, version)
            if (self._metadata.head(item_id) != version or self._ledger.latest_version(item_id) != version
                    or current is None or current.state is not VersionState.COMMITTED
                    or current.staged.stage_digest != selected.stored.staged.stage_digest):
                raise _error("CANDIDATE_CHANGED", "REPRESENTATION_NOT_READY")
        # Re-read the full membership, not just the heads already selected.
        # A concurrent admission/reclassification may add/remove an item without
        # changing any selected head. PENDING and historical rows are not heads.
        observed = {
            stored.staged.memory_item_id: (stored.staged.memory_version, stored.staged.stage_digest)
            for stored in self._metadata.versions_in(partition.digest)
            if stored.state is VersionState.COMMITTED
            and self._metadata.head(stored.staged.memory_item_id) == stored.staged.memory_version
        }
        expected = {item_id: (head.record.item.memory_version, head.stored.staged.stage_digest)
                    for item_id, head in heads.items()}
        if observed != expected:
            raise _error("CANDIDATE_CHANGED", "REPRESENTATION_NOT_READY")
        return tuple(heads[k] for k in sorted(heads))

    @staticmethod
    def _retained(head: _Head) -> bool:
        return head.record.item.lifecycle_status is not LifecycleStatus.DELETED

    def _usage(self, heads: tuple[_Head, ...]) -> MemoryUsage:
        retained = [h for h in heads if self._retained(h)]
        return MemoryUsage(
            items=len(retained),
            held_items=sum(h.record.item.lifecycle_status is LifecycleStatus.LEGAL_HOLD for h in retained),
            incomplete_deletions=sum(h.record.item.lifecycle_status in {
                LifecycleStatus.DELETION_PENDING, LifecycleStatus.DELETION_INCOMPLETE} for h in retained),
            index_entries=sum(len(h.stored.staged.pointers) for h in retained
                              if h.record.item.lifecycle_status is LifecycleStatus.ACTIVE),
            tombstones=sum(h.record.item.deletion_epoch is not None for h in heads),
        )

    def monitor(self, request: Mapping[str, object], *, binding: VerifiedGovernedContextBinding | None) -> MemoryUsage:
        return self._guard("memoryMonitor", request, binding, lambda p: self._usage(self._heads(p.partition)))

    def check_quota(
        self, request: Mapping[str, object], *, binding: VerifiedGovernedContextBinding | None, demand: MemoryQuotaDemand,
    ) -> QuotaCheck:
        def check(plan: _Plan) -> QuotaCheck:
            if not isinstance(demand, MemoryQuotaDemand):
                raise _error("DEMAND_INVALID", "MEMORY_SCHEMA_INVALID")
            usage = self._usage(self._heads(plan.partition))
            self._enforce_quota(usage, demand)
            return QuotaCheck(True, usage)
        return self._guard("memoryQuota", request, binding, check)

    def _enforce_quota(self, usage: MemoryUsage, demand: MemoryQuotaDemand) -> None:
        horizon = self._limits.retention_horizons.get(demand.retention_policy_ref)
        if horizon is None:
            raise _error("RETENTION_UNCONFIGURED", "MEMORY_SCHEMA_INVALID")
        checks = (
            (usage.items + demand.new_items, self._limits.max_items, "ITEM"),
            (demand.payload_bytes, self._limits.max_payload_bytes, "PAYLOAD"),
            (demand.embedding_dimensions, self._limits.max_embedding_dimensions, "EMBEDDING"),
            (demand.top_k, self._limits.max_top_k, "TOP_K"),
            (demand.consolidation_concurrency, self._limits.max_consolidation_concurrency, "CONSOLIDATION"),
            (usage.index_entries + demand.new_index_entries, self._limits.max_index_entries, "INDEX"),
            (demand.retention_seconds, horizon.total_seconds(), "RETENTION"),
        )
        for actual, limit, resource in checks:
            if actual > limit:
                raise _error(resource + "_QUOTA_EXCEEDED")

    def relieve_pressure(
        self, request: Mapping[str, object], *, binding: VerifiedGovernedContextBinding | None,
        target_items: int, limit: int,
    ) -> MemoryPressureReport:
        return self._guard("memoryPressure", request, binding,
                           lambda p: self._pressure(p, binding, target_items, limit, retention=False), mutative=True)

    def enforce_retention(
        self, request: Mapping[str, object], *, binding: VerifiedGovernedContextBinding | None, limit: int,
    ) -> MemoryPressureReport:
        return self._guard("memoryRetention", request, binding,
                           lambda p: self._pressure(p, binding, 0, limit, retention=True), mutative=True)

    def _pressure(
        self, plan: _Plan, binding: VerifiedGovernedContextBinding | None,
        target: int, limit: int, *, retention: bool,
    ) -> MemoryPressureReport:
        if not _integer(target) or not _integer(limit, positive=True) or limit > self._limits.max_pressure_batch:
            raise _error("PRESSURE_LIMIT_INVALID", "MEMORY_SCHEMA_INVALID")
        heads = self._heads(plan.partition)
        retained = [h for h in heads if self._retained(h)]
        eligible: list[_Head] = []
        held: list[str] = []
        for head in retained:
            item = head.record.item
            horizon = self._limits.retention_horizons.get(item.retention_policy_ref)
            if horizon is None:
                raise _error("RETENTION_UNCONFIGURED", "MEMORY_SCHEMA_INVALID")
            due = head.first_created_at + horizon
            if retention and due > self._clock.now():
                continue
            if item.lifecycle_status is LifecycleStatus.LEGAL_HOLD:
                held.append(item.memory_item_id)
            elif item.lifecycle_status in {LifecycleStatus.ACTIVE, LifecycleStatus.QUARANTINED,
                                            LifecycleStatus.SUPERSEDED, LifecycleStatus.REVOKED, LifecycleStatus.EXPIRED}:
                eligible.append(head)
        # Canonical Python string ordering only: the database never orders this selection.
        eligible.sort(key=lambda h: (h.first_created_at + self._limits.retention_horizons[h.record.item.retention_policy_ref],
                                     h.record.item.memory_item_id))
        deleted: list[str] = []
        incomplete: list[str] = []
        remaining = len(retained)
        operation = "memoryRetention" if retention else "memoryPressure"
        for head in eligible:
            if len(deleted) + len(incomplete) >= limit or (not retention and remaining <= target):
                break
            self._check(operation, plan)
            item = head.record.item
            current = self._metadata.get(item.memory_item_id, item.memory_version)
            if self._metadata.head(item.memory_item_id) != item.memory_version or current is None or current.staged.stage_digest != head.stored.staged.stage_digest:
                raise _error("CANDIDATE_CHANGED", "REPRESENTATION_NOT_READY")
            receipt = self._lifecycle.transition(item.memory_item_id, {
                "operation_id": plan.operation_id + ":" + canonical_digest([item.version_ref, operation]).removeprefix("urn:sha256:"),
                "governed_context": plan.context.to_mapping(), "governed_context_digest": plan.context.digest(),
                "deadline": format_utc_timestamp(plan.deadline), "memory_version": item.memory_version,
                "target_status": "DELETION_PENDING", "reason_code": "RETENTION_ELAPSED" if retention else "QUOTA_PRESSURE",
            }, binding=binding)
            if receipt.lifecycle_status == "DELETED":
                deleted.append(item.memory_item_id)
                remaining -= 1
            else:
                incomplete.append(item.memory_item_id)
        latest = self._heads(plan.partition)
        remaining = self._usage(latest).items
        if retention:
            satisfied = not incomplete and not held and all(
                h.first_created_at + self._limits.retention_horizons[h.record.item.retention_policy_ref] > self._clock.now()
                for h in latest if self._retained(h)
            )
        else:
            satisfied = remaining <= target and not incomplete
        return MemoryPressureReport(tuple(deleted), tuple(incomplete), tuple(sorted(held)), remaining, satisfied)


class MemoryQuotaSerialization(Protocol):
    """Trusted composition port, never a caller-provided reservation or lease.

    Every writer sharing a metadata authority must use the same serialization
    domain for the full partition digest. Hold spans inventory, admission and
    store commit. Acquisition must have a bounded wait; loss/exit failure denies.
    Low-level admission/store ports are trusted dependencies, not public routes
    around this boundary. A process-local lock does not qualify cross-worker use.
    """

    def hold(self, partition_digest: str) -> AbstractContextManager[None]: ...


class MemoryQuotaWriter:
    """Internal admission + commit port with demand derived from actual input.

    Preserves the existing admission and store validations. An unsuccessful store
    commit can leave an admitted/PENDING version; it is not acknowledged as success
    and existing reconciliation/retry semantics apply. No ledger entry is erased.
    This port does not make audit, stop state and the stores one transaction: the
    final control/effect window still belongs to FGM-17. Quotas cover committed
    logical heads/native representation slots, not historical journal bytes.
    """

    def __init__(
        self, *, operations: MemoryOperationsService, admission: MemoryAdmissionService,
        store: MemoryStoreCoordinator, serialization: MemoryQuotaSerialization,
    ) -> None:
        self._operations, self._admission, self._store, self._serialization = operations, admission, store, serialization

    def admit_and_commit(
        self, request: Mapping[str, object], *, binding: VerifiedGovernedContextBinding | None,
        payload: bytes, embedding: Sequence[float] | None = None,
    ) -> StoreCommitReceipt:
        item: GovernedMemoryItem | None = None
        vector: tuple[float, ...] | None = None

        def prepare() -> Mapping[str, object]:
            nonlocal item, vector
            if not isinstance(request, Mapping) or set(request) != ENVELOPE_FIELDS:
                raise _error("ENVELOPE_INVALID", "MEMORY_SCHEMA_INVALID")
            candidate = request["candidate"]
            if not isinstance(candidate, Mapping):
                raise _error("NOT_AN_OBJECT", "MEMORY_SCHEMA_INVALID")
            item = GovernedMemoryItem.from_mapping(candidate)
            if not isinstance(payload, bytes) or "urn:sha256:" + hashlib.sha256(payload).hexdigest() != item.content_digest:
                raise _error("CONTENT_DIGEST_MISMATCH", "MEMORY_SCHEMA_INVALID")
            if RepresentationKind.VECTOR in item.representation_kinds:
                if embedding is None:
                    raise _error("EMBEDDING_MISSING", "MEMORY_SCHEMA_INVALID")
                vector = validate_embedding(item, tuple(embedding))
            elif embedding is not None:
                raise _error("UNBOUND_REPRESENTATION", "MEMORY_SCHEMA_INVALID")
            return {**{k: v for k, v in request.items() if k != "candidate"},
                    "partition": MemoryPartition.for_item(item).to_mapping()}

        def commit(plan: _Plan) -> StoreCommitReceipt:
            if item is None:
                raise _error("DEMAND_INVALID", "MEMORY_SCHEMA_INVALID")
            if (item.governed_context_digest != plan.context.digest()
                    or item.owner_principal_id != plan.context.effective_principal_id):
                raise _error("ITEM_NOT_BOUND_TO_GCS", "GOVERNED_CONTEXT_MISMATCH")
            stack = ExitStack()
            try:
                try:
                    stack.enter_context(self._serialization.hold(plan.partition.digest))
                except Exception as exc:  # noqa: BLE001 -- no unlocked quota check or write
                    raise _error("QUOTA_SERIALIZATION_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc
                return self._commit_locked(item, vector, payload, plan, binding)
            finally:
                # close() cannot suppress an exception raised by admission/store.
                stack.close()

        return self._operations._guard("memoryWrite", {}, binding, commit, mutative=True, prepare=prepare)

    def _commit_locked(
        self, item: GovernedMemoryItem, vector: tuple[float, ...] | None, payload: bytes,
        plan: _Plan, binding: VerifiedGovernedContextBinding | None,
    ) -> StoreCommitReceipt:
        service = self._operations
        service._check("memoryWrite", plan)  # also after a bounded wait for the lock
        heads = service._heads(plan.partition)
        previous = next((h for h in heads if h.record.item.memory_item_id == item.memory_item_id), None)
        usage = service._usage(heads)
        existing_slots = 0
        if previous is not None and previous.record.item.lifecycle_status is LifecycleStatus.ACTIVE:
            existing_slots = len(previous.stored.staged.pointers)
        horizon = service._limits.retention_horizons.get(item.retention_policy_ref)
        if horizon is None:
            raise _error("RETENTION_UNCONFIGURED", "MEMORY_SCHEMA_INVALID")
        first_created = previous.first_created_at if previous is not None else item.created_at
        if item.expires_at is not None and item.expires_at > first_created + horizon:
            raise _error("RETENTION_QUOTA_EXCEEDED")
        if previous is not None and item.memory_version == previous.record.item.memory_version:
            if item.digest() != previous.record.item_digest:
                raise _error("IDEMPOTENCY_DIGEST_MISMATCH", "MEMORY_IDEMPOTENCY_CONFLICT")
        elif previous is not None and item.memory_version <= previous.record.item.memory_version:
            raise _error("CANDIDATE_CHANGED", "REPRESENTATION_NOT_READY")
        service._enforce_quota(replace(usage, index_entries=usage.index_entries - existing_slots), MemoryQuotaDemand(
            new_items=int(previous is None or not service._retained(previous)), payload_bytes=len(payload),
            embedding_dimensions=len(vector) if vector is not None else 0,
            new_index_entries=len(item.representation_kinds) if item.lifecycle_status is LifecycleStatus.ACTIVE else 0,
            retention_policy_ref=item.retention_policy_ref,
        ))
        service._check("memoryWrite", plan)
        receipt = self._admission.admit({
            "operation_id": plan.operation_id, "governed_context": plan.context.to_mapping(),
            "governed_context_digest": plan.context.digest(), "deadline": format_utc_timestamp(plan.deadline),
            "candidate": item.to_mapping(),
        }, binding=binding, payload=payload)
        record = service._ledger.get(receipt.memory_item_id, receipt.memory_version)
        if record is None or record.item_digest != item.digest():
            raise _error("LEDGER_DRIFT", "REPRESENTATION_NOT_READY")
        service._check("memoryWrite", plan)
        return self._store.commit(record, payload=payload, embedding=vector)


MANIFEST_SCHEMA = "urn:ocor:schema:memory-backup-manifest:v1"
_MANIFEST_KEYS = frozenset({
    "schema", "recovery_point_id", "operation_id", "partition", "partition_digest", "governed_context_digest",
    "captured_at", "journal_checkpoint", "usage", "entries",
})
_ENTRY_KEYS = frozenset({
    "memory_item_id", "head_version", "lifecycle_status", "deletion_epoch", "content_ref", "content_digest",
    "stage_digest", "item_digests", "audit_refs", "representations",
})


class MemoryBackupSigner(Protocol):
    """Trusted backup custodian (e.g. OpenBao transit); never supplied by a caller.

    ``verify`` must return exactly ``True`` only for a signature it issued over
    these exact bytes; any other answer or failure keeps restore closed.
    """

    def sign(self, payload: bytes) -> str: ...

    def verify(self, payload: bytes, signature: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class SignedMemoryBackup:
    """Canonical manifest bytes plus the custodian signature over them."""

    payload: bytes
    signature: str
    manifest_digest: str


class MemoryBackupService:
    """Partition-bound backup manifest (ADD v1.3 II 2.13, LLD 2.8.6).

    The manifest binds memory metadata, content refs, representation versions,
    lifecycle/deletion epochs, the deletion journal checkpoint and per-version
    audit refs of the authorised partition to one trusted recovery point. It is
    digest-only: no payload, vector or text. Capturing the store bytes themselves
    is the 0049/0056 recovery-point procedure; this manifest is what restore
    verifies before reopening retrieval. The checkpoint must be unchanged across
    the inventory, otherwise a deletion raced the capture and it is refused.
    """

    def __init__(
        self, *, operations: MemoryOperationsService, checkpoints: DeletionCheckpointAuthority,
        signer: MemoryBackupSigner,
    ) -> None:
        self._operations, self._checkpoints, self._signer = operations, checkpoints, signer

    def _checkpoint(self) -> DeletionJournalCheckpoint:
        try:
            checkpoint = self._checkpoints.current()
        except Exception as exc:  # noqa: BLE001 -- unavailable deletion authority denies
            raise _error("CHECKPOINT_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc
        if not isinstance(checkpoint, DeletionJournalCheckpoint):
            raise _error("CHECKPOINT_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE")
        return checkpoint

    def capture(
        self, request: Mapping[str, object], *, binding: VerifiedGovernedContextBinding | None,
        recovery_point_id: str,
    ) -> SignedMemoryBackup:
        def build(plan: _Plan) -> SignedMemoryBackup:
            if not isinstance(recovery_point_id, str) or re.fullmatch(RECOVERY_POINT_PATTERN, recovery_point_id) is None:
                raise _error("RECOVERY_POINT_INVALID", "MEMORY_SCHEMA_INVALID")
            service = self._operations
            checkpoint = self._checkpoint()
            heads = service._heads(plan.partition)
            entries = [self._entry(head) for head in heads]
            if self._checkpoint() != checkpoint:
                raise _error("CHECKPOINT_CHANGED", "REPRESENTATION_NOT_READY")
            service._check("memoryBackup", plan)
            payload = canonical_bytes({
                "schema": MANIFEST_SCHEMA, "recovery_point_id": recovery_point_id,
                "operation_id": plan.operation_id, "partition": plan.partition.to_mapping(),
                "partition_digest": plan.partition.digest, "governed_context_digest": plan.context.digest(),
                "captured_at": format_utc_timestamp(service._clock.now().replace(microsecond=0)),
                "journal_checkpoint": checkpoint.to_mapping(), "usage": service._usage(heads).to_mapping(),
                "entries": entries,
            })
            try:
                signature = self._signer.sign(payload)
            except Exception as exc:  # noqa: BLE001 -- an unsigned manifest is not a backup
                raise _error("SIGNER_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc
            if not isinstance(signature, str) or not signature:
                raise _error("SIGNER_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE")
            return SignedMemoryBackup(payload, signature, "urn:sha256:" + hashlib.sha256(payload).hexdigest())

        return self._operations._guard("memoryBackup", request, binding, build, mutative=True)

    def _entry(self, head: _Head) -> dict[str, object]:
        service = self._operations
        item = head.record.item
        item_id, version = item.memory_item_id, item.memory_version
        digests: list[str] = []
        audit_refs: list[str] = []
        for v in range(1, version + 1):
            record, stored = service._ledger.get(item_id, v), service._metadata.get(item_id, v)
            if record is None or stored is None:
                raise _error("LEDGER_DRIFT", "REPRESENTATION_NOT_READY")
            digests.append(record.item_digest)
            audit_refs.append(stored.staged.audit_ref)
        return {
            "memory_item_id": item_id, "head_version": version, "lifecycle_status": item.lifecycle_status.value,
            "deletion_epoch": item.deletion_epoch, "content_ref": head.stored.staged.content_object_ref,
            "content_digest": item.content_digest, "stage_digest": head.stored.staged.stage_digest,
            "item_digests": digests, "audit_refs": audit_refs,
            "representations": [{
                "representation_kind": p.representation_kind.value, "representation_version": p.representation_version,
                "representation_digest": p.representation_digest, "deletion_epoch": p.deletion_epoch,
            } for p in head.stored.staged.pointers],
        }


@dataclass(frozen=True, slots=True)
class MemoryRestoreReceipt:
    recovery_point_id: str
    manifest_digest: str
    checkpoint: DeletionJournalCheckpoint
    obligations: int
    verified_items: int
    deleted_after_backup: tuple[str, ...]
    audit_ref: str = ""


class MemoryRestoreGate:
    """Restored-memory materialisation boundary, composed over the 0056 gate.

    ``open`` authenticates the manifest with the custodian, refuses a deletion
    authority older than the backup (stale deletion epoch) before any purge,
    replays every tombstone through ``DeletionRestoreGate.reconcile`` and only
    then compares the restored metadata/ledger with the manifest. Items deleted
    after the backup must carry the authoritative tombstone epoch; every other
    item must match head, stage, pointers, epochs and version digests exactly;
    any extra restored item is projection drift. ``serve`` repeats the check
    around the materialising callback, which must not dispatch external effects.
    Any failure closes the boundary until a new ``open``. The checkpoint port
    must be the same trusted authority composed into the deletion gate. The
    composition supplies a verified context and its live stop authority; the
    signed manifest must bind that context. A stop change during opening or
    materialisation discards the result and closes the boundary. The final
    epoch check and delivery are not atomic (residual tracked toward FGM-17).
    """

    def __init__(
        self, *, recovery_point_id: str, verifier: MemoryBackupSigner, gate: DeletionRestoreGate,
        checkpoints: DeletionCheckpointAuthority, journal: Path, metadata: MemoryMetadataStore,
        ledger: MemoryVersionLedger, audit: RetrievalAuditSink,
        stop: StopEpochPort, binding: VerifiedGovernedContextBinding,
    ) -> None:
        if not isinstance(binding, VerifiedGovernedContextBinding):
            raise ValueError("restore requires a verified governed-context binding")
        if not isinstance(gate, DeletionRestoreGate):
            raise ValueError("restore requires the DeletionRestoreGate")
        if not isinstance(recovery_point_id, str) or re.fullmatch(RECOVERY_POINT_PATTERN, recovery_point_id) is None:
            raise ValueError("recovery point identity must be a closed recovery-point URN")
        self._point, self._verifier, self._gate, self._checkpoints = recovery_point_id, verifier, gate, checkpoints
        self._journal, self._metadata, self._ledger, self._audit = journal, metadata, ledger, audit
        self._lock = threading.RLock()
        self._stop, self._context = stop, binding.expected
        self._open: tuple[Mapping[str, object], MemoryRestoreReceipt, int] | None = None

    def _epoch(self) -> int:
        try:
            epoch = self._stop.current_epoch(self._context)
        except Exception as exc:  # noqa: BLE001 -- unavailable trusted stop authority denies
            raise _error("STOP_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc
        if not _integer(epoch):
            raise _error("STOP_STATE_INVALID", "CONTROL_PLANE_UNAVAILABLE")
        return epoch

    def _check_epoch(self, expected: int) -> None:
        if self._epoch() != expected:
            raise _error("STOP_EPOCH_MISMATCH", "STOP_EPOCH_MISMATCH")

    def _record(self, action: str, outcome: str, detail: str, manifest_digest: str | None) -> str:
        event: dict[str, object] = {
            "action": action, "outcome": outcome, "detail_code": detail,
            "recovery_point_digest": canonical_digest(self._point), "manifest_digest": manifest_digest,
        }
        ref = canonical_digest(event)
        try:
            self._audit.record(MappingProxyType({**event, "audit_ref": ref}))
        except Exception as exc:  # noqa: BLE001 -- mandatory audit authority
            raise _error("AUDIT_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc
        return ref

    def _denied(self, action: str, error: BaseException, manifest_digest: str | None) -> None:
        detail = error.reason_code if isinstance(error, DeletionRecoveryError) else (
            error.detail_code if isinstance(error, MemoryAdmissionError) else "RESTORE_INVENTORY_UNAVAILABLE")
        self._record(action + ".denied", "DENIED", detail, manifest_digest)

    @staticmethod
    def _decode(payload: bytes) -> Mapping[str, object]:
        try:
            body = parse_i_json(payload)
            if not isinstance(body, dict) or canonical_bytes(body) != payload:
                raise ValueError("non-canonical manifest")
            if set(body) != _MANIFEST_KEYS or body["schema"] != MANIFEST_SCHEMA:
                raise ValueError("closed manifest schema")
            entries = body["entries"]
            if not isinstance(entries, list) or any(not isinstance(e, dict) or set(e) != _ENTRY_KEYS for e in entries):
                raise ValueError("closed entry schema")
            ids = [e["memory_item_id"] for e in entries]
            if any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
                raise ValueError("entry identity")
            checkpoint = body["journal_checkpoint"]
            if not isinstance(checkpoint, dict) or set(checkpoint) != {"sequence", "head", "deletion_epoch"}:
                raise ValueError("checkpoint")
            DeletionJournalCheckpoint(checkpoint["sequence"], checkpoint["head"], checkpoint["deletion_epoch"])
            if not isinstance(body["partition_digest"], str):
                raise ValueError("partition")
        except Exception as exc:  # noqa: BLE001 -- any malformed manifest is refused alike
            raise _error("BACKUP_MANIFEST_INVALID", "MEMORY_SCHEMA_INVALID") from exc
        return body

    def open(self, payload: bytes, signature: str) -> MemoryRestoreReceipt:
        with self._lock:
            self._open = None
            digest = "urn:sha256:" + hashlib.sha256(payload).hexdigest() if isinstance(payload, bytes) else None
            try:
                epoch = self._epoch()
                try:
                    verified = self._verifier.verify(payload, signature)
                except Exception as exc:  # noqa: BLE001 -- custodian outage is not authentication
                    raise _error("BACKUP_UNAUTHENTICATED", "AUTHENTICATION_REQUIRED") from exc
                if verified is not True or digest is None:
                    raise _error("BACKUP_UNAUTHENTICATED", "AUTHENTICATION_REQUIRED")
                body = self._decode(payload)
                if body["governed_context_digest"] != self._context.digest():
                    raise _error("GCS_INVALID", "GOVERNED_CONTEXT_MISMATCH")
                self._check_epoch(epoch)
                if body["recovery_point_id"] != self._point:
                    raise _error("RECOVERY_POINT_MISMATCH", "AUTHENTICATION_REQUIRED")
                raw = body["journal_checkpoint"]
                assert isinstance(raw, dict)
                recorded = DeletionJournalCheckpoint(raw["sequence"], raw["head"], raw["deletion_epoch"])
                try:
                    current = self._checkpoints.current()
                except Exception as exc:  # noqa: BLE001 -- unavailable authority keeps restore closed
                    raise _error("CHECKPOINT_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc
                if not isinstance(current, DeletionJournalCheckpoint):
                    raise _error("CHECKPOINT_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE")
                if (current.sequence < recorded.sequence or current.deletion_epoch < recorded.deletion_epoch
                        or (current.sequence == recorded.sequence and current != recorded)):
                    raise _error("STALE_DELETION_EPOCH")
                self._check_epoch(epoch)
                reconciled = self._gate.reconcile()  # tombstones replayed before any comparison or reopen
                obligations = {e.memory_item_id: e for e in DeletionJournalSnapshot.read(
                    self._journal, expected=reconciled.checkpoint).obligations}
                self._check_epoch(epoch)
                deleted, verified_items = self._verify(body, obligations)
                self._check_epoch(epoch)
                ref = self._record("memoryRestore.opened", "COMPLETED", "NONE", digest)
                receipt = MemoryRestoreReceipt(self._point, digest, reconciled.checkpoint, reconciled.obligations,
                                               verified_items, deleted, ref)
                self._check_epoch(epoch)
                self._open = (body, receipt, epoch)
                return receipt
            except (MemoryAdmissionError, DeletionRecoveryError) as exc:
                self._denied("memoryRestore.open", exc, digest)
                raise
            except Exception as exc:  # noqa: BLE001 -- unreadable restored stores are not a clean restore
                self._denied("memoryRestore.open", exc, digest)
                raise _error("RESTORE_INVENTORY_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc

    def _verify(self, body: Mapping[str, object], obligations: Mapping[str, TombstoneEntry]) -> tuple[tuple[str, ...], int]:
        entries = body["entries"]
        partition = body["partition_digest"]
        assert isinstance(entries, list) and isinstance(partition, str)
        recorded = {e["memory_item_id"]: e for e in entries}
        restored_ids = {s.staged.memory_item_id for s in self._metadata.versions_in(partition)}
        if not restored_ids <= set(recorded):
            raise _error("PROJECTION_DRIFT", "REPRESENTATION_NOT_READY")
        deleted: list[str] = []
        for item_id in sorted(recorded):
            entry = recorded[item_id]
            tomb = obligations.get(item_id)
            head = self._metadata.head(item_id)
            record = self._ledger.get(item_id, head) if head else None
            stored = self._metadata.get(item_id, head) if head else None
            epoch = entry["deletion_epoch"]
            if tomb is not None and (epoch is None or tomb.deletion_epoch > epoch):
                # Deleted after the backup: the replayed authoritative tombstone version is required.
                if record is None or record.item.deletion_epoch != tomb.deletion_epoch:
                    raise _error("STALE_DELETION_EPOCH")
                deleted.append(item_id)
                continue
            if tomb is not None and epoch is not None and tomb.deletion_epoch < epoch:
                raise _error("STALE_DELETION_EPOCH")
            if record is None or stored is None:
                raise _error("PROJECTION_DRIFT", "REPRESENTATION_NOT_READY")
            representations = entry["representations"]
            if record.item.deletion_epoch != epoch or not isinstance(representations, list) or [
                    p.deletion_epoch for p in stored.staged.pointers] != [x["deletion_epoch"] for x in representations]:
                raise _error("STALE_DELETION_EPOCH")
            digests = [r.item_digest if (r := self._ledger.get(item_id, v)) is not None else None
                       for v in range(1, head + 1)]
            if (head != entry["head_version"] or self._ledger.latest_version(item_id) != head
                    or stored.state is not VersionState.COMMITTED
                    or stored.staged.stage_digest != entry["stage_digest"]
                    or stored.staged.partition.digest != partition
                    or record.item_digest != stored.staged.item_digest
                    or digests != entry["item_digests"]):
                raise _error("PROJECTION_DRIFT", "REPRESENTATION_NOT_READY")
        return tuple(deleted), len(recorded) - len(deleted)

    def serve(self, action: Callable[[], T]) -> T:
        with self._lock:
            opened = self._open
            try:
                if opened is None:
                    raise _error("RESTORE_NOT_OPEN", "REPRESENTATION_NOT_READY")
                body, receipt, epoch = opened
                self._check_epoch(epoch)
                obligations = self._obligations(receipt)

                def materialise() -> T:
                    self._verify(body, obligations)
                    self._check_epoch(epoch)
                    response = action()
                    self._check_epoch(epoch)
                    self._verify(body, obligations)
                    self._check_epoch(epoch)
                    return response
                response = self._gate.serve(materialise)
                self._check_epoch(epoch)
                self._record("memoryRestore.served", "COMPLETED", "NONE", receipt.manifest_digest)
                self._check_epoch(epoch)
                return response
            except BaseException as exc:
                self._open = None
                if isinstance(exc, Exception):
                    self._denied("memoryRestore.serve", exc, opened[1].manifest_digest if opened else None)
                if isinstance(exc, (MemoryAdmissionError, DeletionRecoveryError)) or not isinstance(exc, Exception):
                    raise
                raise _error("RESTORE_INVENTORY_UNAVAILABLE", "CONTROL_PLANE_UNAVAILABLE") from exc

    def _obligations(self, receipt: MemoryRestoreReceipt) -> Mapping[str, TombstoneEntry]:
        return {e.memory_item_id: e for e in DeletionJournalSnapshot.read(
            self._journal, expected=receipt.checkpoint).obligations}
