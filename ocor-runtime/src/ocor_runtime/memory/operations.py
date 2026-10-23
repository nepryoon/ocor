"""Partition-bound memory operations (ADD v1.3 II 2.6/2.10/2.13).

Quota checks are admission diagnostics, not reservations or tokens of authority.
The caller must still use the admission/retrieval/consolidation boundary. Pressure
uses the existing lifecycle saga; this module never deletes content or a tombstone
directly. Monitoring reads only the authorised full isolation partition. Metrics
have fixed labels and belong to the protected operator plane, never a user response.

This initial checkpoint covers quota, monitoring and retention/pressure. Backup
capture/restore integration and final task qualification are not yet implemented.
The final control check and effects at the independent lifecycle/audit stores are
not an atomic transaction; no cross-process admission or timing claim is made.
"""
from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Protocol, TypeVar

from ..kernel.canonical import (
    TimestampError, canonical_digest, format_utc_timestamp, parse_utc_timestamp,
)
from ..kernel.governance import TrustedClock
from ..kernel.governed_context import (
    GovernedContext, GovernedContextCodec, GovernedContextError, VerifiedGovernedContextBinding,
)
from .lifecycle import MemoryLifecycleCoordinator
from .model import (
    AdmittedMemoryVersion, LifecycleStatus, MemoryAdmissionError, MemoryPolicyDecision, MemoryVersionLedger,
)
from .retrieval import RetrievalAuditSink, StopEpochPort
from .stores import MemoryMetadataStore, MemoryPartition, StoredVersion, VersionState


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


R = TypeVar("R", MemoryUsage, QuotaCheck, MemoryPressureReport)
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
    ) -> R:
        verified = None
        plan = None
        try:
            if not isinstance(binding, VerifiedGovernedContextBinding):
                raise _error("BINDING_MISSING", "AUTHENTICATION_REQUIRED")
            verified = binding
            plan = self._plan(operation, request, binding)
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
            return QuotaCheck(True, usage)
        return self._guard("memoryQuota", request, binding, check)

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
