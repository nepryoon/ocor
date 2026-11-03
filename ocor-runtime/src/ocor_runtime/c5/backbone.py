"""C5 -- canonical event backbone: ``Publish``, ``Subscribe``, ``Replay``, ``Quarantine``,
``ReprocessAuthorized`` (ADD v1.3 :286).

The admission boundary of ingestion (ADD v1.3 :379) runs, in order, for every publish:

1. the envelope is a closed ``canonical-ingestion-envelope:1.2`` (``envelope``; incomplete ->
   ``REJECTED``, ``SCHEMA_VIOLATION``);
2. ``effective_principal_id`` equals the transport principal; an external mismatch is
   ``QUARANTINED{PRINCIPAL_BINDING_MISMATCH}`` with an Audit Record (ADD v1.3 :199, :379);
3. the producer signature over envelope and payload digest verifies (LLD v1.1 :154);
4. the payload is validated a second time against its content-addressed schema (ADD v1.3
   :529); 3 and 4 failing are ``PERMANENT``: immutable dead letter, no automatic retry, audit
   (LLD v1.1 :161);
5. the policy port allows the publish; otherwise ``POLICY_DENIED``: audit and a
   non-disclosing quarantine -- the caller learns only that the event was not admitted
   (LLD v1.1 :162);
6. admission control per tenant and ``ResourceClass``; ``AUDIT`` is never dropped (LLD v1.1
   :165, :338; Register :406 NFR-079: checks 1-5 always run before it);
7. durable deduplication per ``(governed_context_digest, idempotency_key)`` and, when the
   envelope declares ``aggregate.expected_revision``, a strictly advancing revision per
   aggregate of the same context (``OUT_OF_ORDER`` is ``PERMANENT``);
8. the journal write, keyed by ``ordering_key``; a broker failure is ``TRANSIENT``: bounded
   exponential backoff with jitter inside the retry budget (LLD v1.1 :160). Before each
   retry the state is rebuilt from the journal, so a write whose acknowledgement was lost is
   never written twice.

The topic is the durable journal; the in-process deduplication and revision state is only a
cache of it, rebuilt from the whole topic before the first publish of a process and after
any write whose outcome is unknown. Publishes of different idempotency keys and aggregates
run concurrently; the same key or aggregate is serialised.

``Subscribe`` validates the Event Subscription Contract and delivers by ``subscription_id``
and opaque cursor (ADD v1.3 :2575): deliveries carry no partition or offset, every record is
re-verified (signature and schema), filtered to the contract's event types and governed
context, and authorised per delivery by the policy port (ADD v1.3 :380-381). Each poll writes
an immutable checkpoint binding topic, positions, schema registry digest, release and GCS
(LLD v1.1 :165). An event that a consumer handler keeps failing is ``POISON``: its partition
is quarantined for that subscription behind the operator gate (LLD v1.1 :163). ``Replay``
declares an ingest-time window and a reason, is authorised and audited, re-delivers through
the same per-delivery policy and never appends to the journal (LLD v1.1 :165, Register :202
FR-072).
"""

from __future__ import annotations

import heapq
import json
import re
import threading
from collections.abc import Callable, Hashable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..audit import AuditError, AuditEvent, AuditPort
from .dlq import DeadLetter, PostgresC5Store
from .envelope import (
    BackboneError,
    CanonicalIngestionEnvelope,
    EnvelopeViolation,
    ProducerKeyring,
    SignedEnvelope,
)
from .kafka import JournalRecord, KafkaJournal, KafkaJournalError
from .operations import AdmissionController, ResourceClass
from .policy import C5Policy, permits
from .replay import ReplayRequest, ReprocessRequest
from .retry import FailureClass, RetryPolicy
from .schema import EventTypeRegistration, SchemaRegistry
from .subscription import DeliveredEvent, DeliveryOutcome, SubscriptionBatch, validate_contract

SIGNATURE_HEADER = "ocor-c5-signature"
VERSION_HEADER = "ocor-c5-envelope-version"
C5_AUTHORITY = "urn:ocor:authority:c5-admission-boundary"
POISON_THRESHOLD = 3
REPLAY_WINDOW = re.compile(r"P([0-9]+)D")

__all__ = [
    "BackboneError",
    "CanonicalEventBackbone",
    "CanonicalIngestionEnvelope",
    "KafkaJournalError",
    "PublishReceipt",
    "SignedEnvelope",
]


@dataclass(frozen=True, slots=True)
class PublishReceipt:
    event_id: str
    duplicate: bool


class _KeyedLocks:
    """One lock per key, acquired in a fixed order; entries vanish when unused."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[Hashable, list[Any]] = {}

    @contextmanager
    def hold(self, keys: Sequence[Hashable]) -> Iterator[None]:
        held: list[Hashable] = []
        try:
            for key in sorted(set(keys), key=repr):
                with self._guard:
                    entry = self._locks.setdefault(key, [threading.Lock(), 0])
                    entry[1] += 1
                held.append(key)
                entry[0].acquire()
            yield
        finally:
            for key in reversed(held):
                with self._guard:
                    entry = self._locks[key]
                    if entry[0].locked():
                        entry[0].release()
                    entry[1] -= 1
                    if entry[1] == 0:
                        del self._locks[key]


def _gcs_ref(contract_ref: str) -> str:
    """``urn:sha256:<hex>`` of a contract and ``sha256:<hex>`` of an envelope name one digest."""
    return contract_ref.removeprefix("urn:")


class CanonicalEventBackbone:
    """The C5 backbone of one journal topic."""

    def __init__(
        self,
        *,
        journal: KafkaJournal,
        registry: SchemaRegistry,
        keyring: ProducerKeyring,
        policy: C5Policy,
        audit: AuditPort,
        store: PostgresC5Store,
        retry: RetryPolicy | None = None,
        quotas: Mapping[ResourceClass, int] | None = None,
        poison_threshold: int = POISON_THRESHOLD,
    ) -> None:
        if not isinstance(journal, KafkaJournal):
            raise TypeError("journal must be a KafkaJournal")
        if not isinstance(registry, SchemaRegistry):
            raise TypeError("registry must be a SchemaRegistry")
        if not isinstance(keyring, ProducerKeyring):
            raise TypeError("keyring must be a ProducerKeyring")
        if not isinstance(policy, C5Policy):
            raise TypeError("policy must implement the C5 policy port")
        if not isinstance(audit, AuditPort):
            raise TypeError("audit must implement AuditPort")
        if not isinstance(store, PostgresC5Store):
            raise TypeError("store must be a PostgresC5Store")
        if isinstance(poison_threshold, bool) or not isinstance(poison_threshold, int) or not 1 <= poison_threshold <= 20:
            raise ValueError("poison_threshold must be an integer in [1, 20]")
        self._journal = journal
        self._registry = registry
        self._keyring = keyring
        self._policy = policy
        self._audit_port = audit
        self._store = store
        self._retry = retry if retry is not None else RetryPolicy()
        if not isinstance(self._retry, RetryPolicy):
            raise TypeError("retry must be a RetryPolicy")
        self._admission = AdmissionController(quotas)
        self._poison_threshold = poison_threshold
        self._seen: set[tuple[str, str]] = set()
        self._revisions: dict[tuple[str, str, str, str], int] = {}
        self._recovered = False
        self._state_lock = threading.Lock()
        self._keys = _KeyedLocks()

    def __repr__(self) -> str:
        return f"CanonicalEventBackbone(topic={self._journal.topic!r})"

    @property
    def topic(self) -> str:
        return self._journal.topic

    # -- audit -------------------------------------------------------------------------------

    def _audit(
        self, *, event_type: str, actor: str, resource: str, reason_code: str, outcome: str, correlation_id: str,
        authority_ref: str = C5_AUTHORITY, detail: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            self._audit_port.append(
                AuditEvent(
                    event_type=event_type,
                    actor=actor or "urn:ocor:principal:unauthenticated",
                    occurred_at=datetime.now(UTC),
                    resource=resource,
                    reason_code=reason_code,
                    authority_ref=authority_ref,
                    correlation_id=correlation_id,
                    outcome=outcome,
                    detail=dict(detail or {}),
                )
            )
        except AuditError as exc:
            raise BackboneError("CONTROL_PLANE_UNAVAILABLE", "the audit record could not be written",
                                failure_class=FailureClass.TRANSIENT.value) from exc

    def _event_resource(self, envelope: CanonicalIngestionEnvelope) -> str:
        return f"urn:ocor:c5:{self._journal.topic}:event:{envelope.event_id}"

    # -- Publish -----------------------------------------------------------------------------

    def publish(self, signed: SignedEnvelope, *, transport_principal: str) -> PublishReceipt:
        if not isinstance(signed, SignedEnvelope):
            raise EnvelopeViolation("SCHEMA_VIOLATION", "a signed canonical-ingestion-envelope:1.2 is required")
        envelope = signed.envelope
        principal = transport_principal if isinstance(transport_principal, str) else ""
        correlation = str(envelope["correlation_id"])
        if not principal or principal != envelope.effective_principal_id:
            self._store.quarantine(
                event_id=envelope.event_id, topic=self.topic, failure_class=FailureClass.POLICY_DENIED.value,
                reason_code="PRINCIPAL_BINDING_MISMATCH", envelope=envelope.to_mapping(), signature=signed.signature,
            )
            self._audit(event_type="c5.publish", actor=principal, resource=self._event_resource(envelope),
                        reason_code="PRINCIPAL_BINDING_MISMATCH", outcome="DENIED", correlation_id=correlation)
            raise BackboneError("PRINCIPAL_BINDING_MISMATCH", "the event was quarantined at the admission boundary",
                                failure_class=FailureClass.POLICY_DENIED.value)
        try:
            self._keyring.verify(signed)
            registration = self._registry.validate_payload(envelope)
        except EnvelopeViolation as violation:
            self._dead_letter(signed, violation.reason_code, principal)
            raise
        try:
            decision = self._policy.authorize_publish(principal, envelope)
        except Exception:  # noqa: BLE001 -- a failing policy point denies (fail closed)
            decision = None
        if not permits(decision):
            self._store.quarantine(
                event_id=envelope.event_id, topic=self.topic, failure_class=FailureClass.POLICY_DENIED.value,
                reason_code="POLICY_DENIED", envelope=envelope.to_mapping(), signature=signed.signature,
            )
            self._audit(event_type="c5.publish", actor=principal, resource=self._event_resource(envelope),
                        reason_code="POLICY_DENIED", outcome="DENIED", correlation_id=correlation)
            raise BackboneError("POLICY_DENIED", "the event was not admitted", failure_class=FailureClass.POLICY_DENIED.value)
        if not self._admission.try_admit(envelope.tenant_id, registration.resource_class):
            self._audit(event_type="c5.publish", actor=principal, resource=self._event_resource(envelope),
                        reason_code="BACKPRESSURE_EXCEEDED", outcome="DENIED", correlation_id=correlation,
                        detail={"resource_class": registration.resource_class.value})
            raise BackboneError("BACKPRESSURE_EXCEEDED", "the tenant quota of this resource class is exhausted",
                                failure_class=FailureClass.TRANSIENT.value)
        try:
            return self._write(signed, registration, principal)
        finally:
            self._admission.release(envelope.tenant_id, registration.resource_class)

    def _dead_letter(self, signed: SignedEnvelope, reason_code: str, principal: str) -> DeadLetter:
        envelope = signed.envelope
        letter = self._store.record_dead_letter(
            event_id=envelope.event_id, topic=self.topic, tenant_id=envelope.tenant_id, reason_code=reason_code,
            envelope=envelope.to_mapping(), signature=signed.signature,
        )
        self._audit(event_type="c5.publish", actor=principal, resource=self._event_resource(envelope),
                    reason_code=reason_code, outcome="REJECTED", correlation_id=str(envelope["correlation_id"]),
                    detail={"failure_class": FailureClass.PERMANENT.value, "attempt": letter.attempt})
        if letter.attempt == self._poison_threshold:
            self._store.quarantine(
                event_id=envelope.event_id, topic=self.topic, failure_class=FailureClass.POISON.value,
                reason_code=reason_code, envelope=envelope.to_mapping(), signature=signed.signature,
            )
        return letter

    def _write(self, signed: SignedEnvelope, registration: EventTypeRegistration, principal: str) -> PublishReceipt:
        envelope = signed.envelope
        context = envelope.governed_context_digest
        dedup = (context, envelope.idempotency_key)
        declared = envelope.aggregate.get("expected_revision")
        revision = int(declared) if declared is not None else 0
        aggregate = None
        if declared is not None:
            aggregate = (context, envelope.tenant_id, str(envelope.aggregate["aggregate_type_id"]),
                         str(envelope.aggregate["aggregate_id"]))
        keys: list[Hashable] = [("idempotency", *dedup)] + ([("aggregate", *aggregate)] if aggregate else [])
        with self._keys.hold(keys):
            with self._state_lock:
                if not self._recovered:
                    self._recover()
                if dedup in self._seen:
                    return PublishReceipt(envelope.event_id, duplicate=True)
                last = self._revisions.get(aggregate) if aggregate else None
            if aggregate is not None and last is not None and revision <= last:
                self._dead_letter(signed, "OUT_OF_ORDER", principal)
                raise EnvelopeViolation("OUT_OF_ORDER", f"revision {revision} does not advance past {last}")
            duplicate = self._append_with_retry(signed, dedup, principal)
            with self._state_lock:
                self._seen.add(dedup)
                if aggregate is not None:
                    self._revisions[aggregate] = max(revision, self._revisions.get(aggregate, revision))
            return PublishReceipt(envelope.event_id, duplicate=duplicate)

    def _append_with_retry(self, signed: SignedEnvelope, dedup: tuple[str, str], principal: str) -> bool:
        envelope = signed.envelope
        key = envelope.ordering_key.encode("utf-8")
        value = envelope.canonical_bytes()
        headers = [(SIGNATURE_HEADER, signed.signature), (VERSION_HEADER, b"1.2")]
        timestamp_ms = int(envelope.ingest_time.timestamp() * 1000)
        attempts = self._retry.max_attempts
        for attempt in range(attempts):
            try:
                self._journal.append(key=key, value=value, headers=headers, timestamp_ms=timestamp_ms)
                return False
            except KafkaJournalError:
                with self._state_lock:
                    self._recovered = False
            if attempt + 1 == attempts:
                break
            self._retry.sleep(self._retry.delay(attempt))
            try:
                with self._state_lock:
                    self._recover()
                    if dedup in self._seen:
                        return False  # the lost acknowledgement was a durable write: never twice
            except KafkaJournalError:
                continue
        self._audit(event_type="c5.publish", actor=principal, resource=self._event_resource(envelope),
                    reason_code="RETRY_BUDGET_EXHAUSTED", outcome="FAILED", correlation_id=str(envelope["correlation_id"]),
                    detail={"attempts": attempts})
        raise BackboneError("RETRY_BUDGET_EXHAUSTED", f"the journal did not accept the event in {attempts} attempts",
                            failure_class=FailureClass.TRANSIENT.value)

    def _decode(self, record: JournalRecord) -> SignedEnvelope:
        signature = record.header(SIGNATURE_HEADER)
        if signature is None:
            raise EnvelopeViolation("SIGNATURE_INVALID", "a journal record has no producer signature")
        try:
            value = json.loads(record.value)
        except ValueError as exc:
            raise EnvelopeViolation("SCHEMA_VIOLATION", "a journal record is not JSON") from exc
        return SignedEnvelope(CanonicalIngestionEnvelope.from_mapping(value), signature)

    def _recover(self) -> None:
        """Rebuild deduplication and revisions from every journal record (caller holds the state
        lock); an unreadable record fails closed, never falling back to empty state."""
        marks = self._journal.watermarks()
        records = self._journal.read({p: low for p, (low, _) in marks.items()}, {p: high for p, (_, high) in marks.items()})
        seen: set[tuple[str, str]] = set()
        revisions: dict[tuple[str, str, str, str], int] = {}
        for record in records:
            try:
                envelope = self._decode(record).envelope
            except EnvelopeViolation as exc:
                raise BackboneError("JOURNAL_UNREADABLE", f"the journal holds an unreadable record: {exc.reason_code}",
                                    failure_class=FailureClass.PERMANENT.value) from exc
            context = envelope.governed_context_digest
            seen.add((context, envelope.idempotency_key))
            revision = envelope.aggregate.get("expected_revision")
            if revision is not None:
                key = (context, envelope.tenant_id, str(envelope.aggregate["aggregate_type_id"]),
                       str(envelope.aggregate["aggregate_id"]))
                revisions[key] = max(int(revision), revisions.get(key, int(revision)))
        self._seen = seen
        self._revisions = revisions
        self._recovered = True

    def dead_letters(self) -> tuple[DeadLetter, ...]:
        return self._store.dead_letters(self.topic)

    # -- Subscribe ---------------------------------------------------------------------------

    def subscribe(self, contract: Mapping[str, Any], *, principal: str) -> str:
        validated = validate_contract(contract)
        if not isinstance(principal, str) or not principal:
            raise BackboneError("POLICY_DENIED", "an authenticated subscriber is required",
                                failure_class=FailureClass.POLICY_DENIED.value)
        return self._store.create_subscription(principal=principal, contract=validated, topic=self.topic)

    def poll(self, subscription_id: str, *, cursor: str | None = None, max_records: int = 100,
             timeout_s: float = 10.0) -> SubscriptionBatch:
        events: list[DeliveredEvent] = []
        outcome = self._advance(subscription_id, cursor, max_records, timeout_s, events.append)
        return SubscriptionBatch(events=tuple(events), cursor=outcome.cursor)

    def deliver(self, subscription_id: str, handler: Callable[[DeliveredEvent], object], *, cursor: str | None = None,
                max_records: int = 100, timeout_s: float = 10.0) -> DeliveryOutcome:
        if not callable(handler):
            raise TypeError("handler must be callable")
        return self._advance(subscription_id, cursor, max_records, timeout_s, handler)

    def _subscription(self, subscription_id: str) -> tuple[str, dict[str, Any]]:
        found = self._store.subscription(subscription_id) if isinstance(subscription_id, str) and subscription_id else None
        if found is None or found[2] != self.topic:
            raise BackboneError("SUBSCRIPTION_NOT_FOUND", "no such subscription", failure_class=FailureClass.PERMANENT.value)
        return found[0], found[1]

    def _advance(self, subscription_id: str, cursor: str | None, max_records: int, timeout_s: float,
                 handler: Callable[[DeliveredEvent], object]) -> DeliveryOutcome:
        if isinstance(max_records, bool) or not isinstance(max_records, int) or not 1 <= max_records <= 10_000:
            raise ValueError("max_records must be an integer in [1, 10000]")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, int | float) or not 0 < timeout_s <= 300:
            raise ValueError("timeout_s must be in (0, 300]")
        principal, contract = self._subscription(subscription_id)
        marks = self._journal.watermarks()
        end: Mapping[int, int] | None = None
        window: tuple[datetime, datetime] | None = None
        reason: str | None = None
        release = ""
        if cursor is None:
            positions = {partition: low for partition, (low, _) in marks.items()}
        else:
            checkpoint = self._store.checkpoint(cursor) if isinstance(cursor, str) and cursor else None
            if checkpoint is None or checkpoint.subscription_id != subscription_id or checkpoint.topic != self.topic:
                raise BackboneError("CURSOR_EXPIRED", "the cursor is unknown or expired",
                                    failure_class=FailureClass.PERMANENT.value)
            positions = dict(checkpoint.positions)
            end = checkpoint.end_positions
            if checkpoint.window_start is not None and checkpoint.window_end is not None:
                window = (checkpoint.window_start, checkpoint.window_end)
            release = checkpoint.release_digest
            reason = None if window is None else "replay"
        for partition, (low, _) in marks.items():
            if positions.setdefault(partition, low) < low:
                raise BackboneError("CURSOR_EXPIRED", "the cursor is older than the journal retention",
                                    failure_class=FailureClass.PERMANENT.value)
        held = {
            record.partition for record in self._store.quarantined(self.topic)
            if record.subscription_id == subscription_id and record.failure_class == FailureClass.POISON.value
            and not record.released and record.partition is not None
        }
        targets = {p: min(high, end.get(p, high)) if end is not None else high for p, (_, high) in marks.items()}
        records = self._journal.read({p: positions[p] for p in targets if p not in held},
                                     {p: targets[p] for p in targets if p not in held})
        queues: dict[int, list[JournalRecord]] = {}
        for record in records:
            queues.setdefault(record.partition, []).append(record)
        heap = [(queue[0].timestamp_ms, partition, 0) for partition, queue in queues.items()]
        heapq.heapify(heap)
        event_types = set(contract["event_type_refs"])
        context = _gcs_ref(str(contract["governed_context_ref"]))
        delivered: list[str] = []
        quarantined: list[str] = []
        while heap and len(delivered) + len(quarantined) < max_records:
            _, partition, index = heapq.heappop(heap)
            record = queues[partition][index]
            positions[partition] = record.offset + 1
            if index + 1 < len(queues[partition]):
                heapq.heappush(heap, (queues[partition][index + 1].timestamp_ms, partition, index + 1))
            try:
                signed = self._decode(record)
                self._keyring.verify(signed)
                self._registry.validate_payload(signed.envelope)
            except EnvelopeViolation as violation:
                self._poison(subscription_id, record, None, violation.reason_code, principal)
                quarantined.append(f"urn:ocor:c5:unreadable:{partition}:{record.offset}")
                heap = [item for item in heap if item[1] != partition]
                heapq.heapify(heap)
                continue
            envelope = signed.envelope
            if envelope.event_type_id not in event_types or envelope.governed_context_digest != context:
                continue
            if window is not None and not window[0] <= envelope.ingest_time < window[1]:
                continue
            try:
                decision = self._policy.authorize_delivery(principal, subscription_id, envelope)
            except Exception:  # noqa: BLE001 -- a failing policy point denies (fail closed)
                decision = None
            if not permits(decision):
                self._audit(event_type="c5.deliver", actor=principal, resource=subscription_id,
                            reason_code="POLICY_DENIED", outcome="DENIED", correlation_id=str(envelope["correlation_id"]),
                            detail={"event_id": envelope.event_id})
                continue
            event = DeliveredEvent(subscription_id=subscription_id, envelope=envelope)
            if self._handle(handler, event):
                delivered.append(envelope.event_id)
                release = envelope.ontology_release_digest
                continue
            self._poison(subscription_id, record, signed, "HANDLER_FAILED", principal)
            quarantined.append(envelope.event_id)
            heap = [item for item in heap if item[1] != partition]
            heapq.heapify(heap)
        new_cursor = self._store.save_checkpoint(
            subscription_id=subscription_id, topic=self.topic, positions=positions, end_positions=end,
            window_start=None if window is None else window[0], window_end=None if window is None else window[1],
            replay_reason=reason, schema_registry_digest=self._registry.digest, release_digest=release,
            governed_context_digest=context,
        )
        return DeliveryOutcome(cursor=new_cursor, delivered=tuple(delivered), quarantined=tuple(quarantined))

    def _handle(self, handler: Callable[[DeliveredEvent], object], event: DeliveredEvent) -> bool:
        for _ in range(self._poison_threshold):
            try:
                handler(event)
                return True
            except Exception:  # noqa: BLE001 -- a consumer failure is counted, then quarantined as POISON
                continue
        return False

    def _poison(self, subscription_id: str, record: JournalRecord, signed: SignedEnvelope | None, reason_code: str,
                principal: str) -> None:
        envelope = None if signed is None else signed.envelope
        event_id = envelope.event_id if envelope is not None else f"urn:ocor:c5:unreadable:{record.partition}:{record.offset}"
        self._store.quarantine(
            event_id=event_id, topic=self.topic, failure_class=FailureClass.POISON.value, reason_code=reason_code,
            envelope=None if envelope is None else envelope.to_mapping(),
            signature=None if signed is None else signed.signature,
            subscription_id=subscription_id, partition=record.partition, offset=record.offset,
        )
        self._audit(event_type="c5.deliver", actor=principal, resource=subscription_id, reason_code=reason_code,
                    outcome="FAILED", correlation_id=str(envelope["correlation_id"]) if envelope is not None else event_id,
                    detail={"failure_class": FailureClass.POISON.value, "event_id": event_id})

    # -- Quarantine / ReprocessAuthorized ----------------------------------------------------------

    def quarantined(self) -> tuple[Any, ...]:
        return self._store.quarantined(self.topic)

    def release_quarantine(self, quarantine_id: str, *, operator: str, authority_ref: str,
                           reason: str = "operator release after diagnosis") -> None:
        """The operator gate (LLD v1.1 :163): only an authorised operator releases a quarantine."""
        found = [record for record in self._store.quarantined(self.topic) if record.quarantine_id == quarantine_id]
        if not found:
            raise BackboneError("QUARANTINE_NOT_FOUND", "no such quarantine record", failure_class=FailureClass.PERMANENT.value)
        request = ReprocessRequest(
            quarantine_id=quarantine_id, subscription_id=found[0].subscription_id or "", reason=reason,
            requested_by=operator if isinstance(operator, str) else "", authority_ref=authority_ref,
        )
        try:
            decision = self._policy.authorize_replay(request.requested_by, request)
        except Exception:  # noqa: BLE001 -- a failing policy point denies (fail closed)
            decision = None
        if not isinstance(reason, str) or not reason.strip() or not permits(decision):
            self._audit(event_type="c5.quarantine.release", actor=request.requested_by, resource=quarantine_id,
                        reason_code="OPERATOR_GATE_CLOSED", outcome="DENIED", correlation_id=quarantine_id)
            raise BackboneError("OPERATOR_GATE_CLOSED", "the release is not authorised",
                                failure_class=FailureClass.POISON.value)
        self._store.release(quarantine_id, released_by=request.requested_by, authority_ref=str(authority_ref),
                            reason=reason)
        self._audit(event_type="c5.quarantine.release", actor=request.requested_by, resource=quarantine_id,
                    reason_code="OPERATOR_RELEASE", outcome="PERMITTED", correlation_id=quarantine_id,
                    authority_ref=str(authority_ref))

    # -- Replay ------------------------------------------------------------------------------

    def replay(self, request: ReplayRequest) -> str:
        """Authorise a windowed replay of a subscription; return the cursor that delivers it."""
        actor = request.requested_by if isinstance(request, ReplayRequest) and isinstance(request.requested_by, str) else ""
        subject = request.subscription_id if isinstance(request, ReplayRequest) else ""

        def deny(why: str) -> BackboneError:
            self._audit(event_type="c5.replay", actor=actor, resource=str(subject) or "urn:ocor:c5:replay",
                        reason_code="REPLAY_DENIED", outcome="DENIED", correlation_id=str(subject) or "urn:ocor:c5:replay",
                        detail={"why": why})
            return BackboneError("REPLAY_DENIED", "the replay is not authorised", failure_class=FailureClass.POLICY_DENIED.value)

        if not isinstance(request, ReplayRequest) or not request.well_formed():
            raise deny("the request does not declare a valid window, reason and authority")
        _, contract = self._subscription(request.subscription_id)
        terms = contract["replay"]
        match = REPLAY_WINDOW.fullmatch(str(terms.get("max_replay_window", "")))
        if terms.get("replay_allowed") is not True or match is None:
            raise deny("the subscription contract does not allow replay")
        if request.window_end - request.window_start > timedelta(days=int(match.group(1))):
            raise deny("the window exceeds max_replay_window")
        try:
            decision = self._policy.authorize_replay(request.requested_by, request)
        except Exception:  # noqa: BLE001 -- a failing policy point denies (fail closed)
            decision = None
        if not permits(decision):
            raise deny("the policy does not authorise the replay")
        start = self._journal.offsets_for_time(int(request.window_start.timestamp() * 1000))
        end = self._journal.offsets_for_time(int(request.window_end.timestamp() * 1000))
        cursor = self._store.save_checkpoint(
            subscription_id=request.subscription_id, topic=self.topic, positions=start, end_positions=end,
            window_start=request.window_start, window_end=request.window_end, replay_reason=request.reason,
            schema_registry_digest=self._registry.digest, release_digest="",
            governed_context_digest=_gcs_ref(str(contract["governed_context_ref"])),
        )
        self._audit(event_type="c5.replay", actor=request.requested_by, resource=request.subscription_id,
                    reason_code="REPLAY_AUTHORISED", outcome="PERMITTED", correlation_id=request.subscription_id,
                    authority_ref=request.authority_ref,
                    detail={"reason": request.reason, "window_start": request.window_start.isoformat(),
                            "window_end": request.window_end.isoformat()})
        return cursor
