"""C3 outbox relay: committed outbox -> C5 backbone -> DeliveryAttempt.

OCOR-DEV-REM-0050 (NCP-U04, NCR-C3-003). The worker reads only committed outbox entries
of ``main``, publishes each as ``canonical-state-committed`` on the event backbone with
the stable outbox event ID, and records the delivery as a separate DeliveryAttempt only
after the broker acknowledged the write (ADD v1.3 §2.3 :293, §6.2 step 3 :3432; LLD v1.1
§2.3 :132). A crash or a failure between publish and acknowledgement leaves the entry
undelivered: it is published again with the same event ID, and the backbone and every
consumer deduplicate on it (at-least-once; no exactly-once claim, ADD v1.3 :273).

The C5 envelope carries the isolation boundary and correlation of the commit (Register
FR-068 :192, FR-075 :207): ``sequence`` is the aggregate revision, so the backbone and the
projectors keep the per-aggregate order (LLD v1.1 §2.4 :148).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from ..c5.backbone import CanonicalIngestionEnvelope
from .events import CANONICAL_STATE_COMMITTED, EVENT_VERSION
from .ports import C3Error, OutboxEnvelope, _thaw

C3_PRODUCER = "urn:ocor:component:c3"
CANONICAL_EVENT_SCHEMA = "urn:ocor:schema:canonical-ingestion-envelope:1"


class RelayError(RuntimeError):
    """A publish was not acknowledged; the entry stays undelivered."""

    def __init__(self, event_id: str, message: str) -> None:
        self.reason_code = "DELIVERY_NOT_ACKNOWLEDGED"
        self.event_id = event_id
        super().__init__(f"{self.reason_code}: {event_id}: {message}")


@runtime_checkable
class CanonicalEventPublisher(Protocol):
    """The Publish operation of the C5 backbone port."""

    def publish(self, envelope: CanonicalIngestionEnvelope) -> None: ...


@runtime_checkable
class RelaySource(Protocol):
    def claim_batch(self, *, limit: int, claim_ttl: timedelta) -> tuple[OutboxEnvelope, ...]: ...

    def acknowledge(self, event_id: str, *, acknowledged_at: datetime) -> None: ...

    def record_failure(self, event_id: str, *, failed_at: datetime, reason: str) -> None: ...


def canonical_event(entry: OutboxEnvelope) -> CanonicalIngestionEnvelope:
    """The C5 envelope of one committed outbox entry; refuses an entry whose payload is
    not a canonical-state-committed event of ``main`` for that entry."""
    if not isinstance(entry, OutboxEnvelope):
        raise C3Error("COMMIT_CONTRACT_INVALID", "an OutboxEnvelope is required")
    payload: dict[str, Any] = _thaw(entry.payload)
    if (
        payload.get("event_type") != CANONICAL_STATE_COMMITTED
        or payload.get("commit_id") != entry.commit_id
        or payload.get("aggregate_ref") != entry.aggregate_ref
        or payload.get("to_revision") != entry.aggregate_revision
        or payload.get("branch") != entry.branch
    ):
        raise C3Error("COMMIT_RECEIPT_MISMATCH", f"outbox entry {entry.event_id!r} is not its committed event")
    boundary = payload.get("boundary")
    if not isinstance(boundary, dict):
        raise C3Error("COMMIT_RECEIPT_MISMATCH", f"outbox entry {entry.event_id!r} has no isolation boundary")
    return CanonicalIngestionEnvelope.from_mapping(
        {
            "event_id": entry.event_id,
            "event_type": CANONICAL_STATE_COMMITTED,
            "event_version": EVENT_VERSION,
            "schema_ref": CANONICAL_EVENT_SCHEMA,
            "producer_principal": C3_PRODUCER,
            "source_ref": entry.commit_id,
            "aggregate_ref": entry.aggregate_ref,
            "correlation_id": payload.get("correlation_id"),
            "causation_id": payload.get("causation_id"),
            "classification_marking_ref": boundary.get("classification_marking_ref"),
            "governed_context_digest": payload.get("governed_context_digest"),
            "idempotency_key": entry.event_id,
            "sequence": entry.aggregate_revision,
            "payload": payload,
        }
    )


class OutboxRelayWorker:
    """Claims committed entries, publishes them, and records each outcome."""

    def __init__(
        self,
        relay: RelaySource,
        backbone: CanonicalEventPublisher,
        *,
        claim_ttl: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not isinstance(relay, RelaySource):
            raise TypeError("relay must implement claim_batch, acknowledge and record_failure")
        if not isinstance(backbone, CanonicalEventPublisher):
            raise TypeError("backbone must implement publish")
        if not isinstance(claim_ttl, timedelta) or claim_ttl < timedelta(0):
            raise TypeError("claim_ttl must be a non-negative timedelta")
        self._relay = relay
        self._backbone = backbone
        self._claim_ttl = claim_ttl
        self._clock = clock

    def relay_once(self, *, limit: int) -> tuple[str, ...]:
        """Relays one batch in outbox order and returns the delivered event IDs. The first
        unacknowledged publish stops the batch with ``RelayError`` after recording the
        failure; later entries of the batch are not published out of order."""
        delivered: list[str] = []
        for entry in self._relay.claim_batch(limit=limit, claim_ttl=self._claim_ttl):
            envelope = canonical_event(entry)
            try:
                self._backbone.publish(envelope)
            except Exception as error:  # noqa: BLE001 -- any publish failure is a non-delivery
                self._relay.record_failure(entry.event_id, failed_at=self._clock(), reason=type(error).__name__)
                raise RelayError(entry.event_id, "the backbone did not acknowledge the publish") from error
            self._relay.acknowledge(entry.event_id, acknowledged_at=self._clock())
            delivered.append(entry.event_id)
        return tuple(delivered)
