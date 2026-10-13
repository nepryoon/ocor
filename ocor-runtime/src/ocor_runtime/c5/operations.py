"""C5 -- registry, replay, backpressure, DLQ and quarantine operations.

Implements the smallest contract-compliant slice of LLD v1.1 section
2.5's failure taxonomy and replay contract over the retained
``CanonicalEventBackbone`` (OCOR-DEV-0040, sealed, reused unmodified,
composed exclusively through its own sealed public methods):
``PERMANENT`` failures land in an immutable dead-letter record (no
automatic retry); an event that keeps failing is classified
``POISON`` and quarantined behind an explicit operator gate; a bounded
per-tenant admission quota provides backpressure; and ``replay``
always re-runs the exact same compatibility checks a fresh publish
would -- it can never bypass an unknown schema or a missing/lost
marking -- and never republishes an already-durable canonical effect,
since it delegates to the backbone's own idempotency-key handling.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .backbone import BackboneError, CanonicalEventBackbone, CanonicalIngestionEnvelope

POISON_THRESHOLD = 3


class OperationsError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True, slots=True)
class DeadLetter:
    """An immutable record of a publish failure -- never mutated once
    recorded, matching LLD 2.5's own 'DLQ immutabile' requirement."""

    event_id: str
    envelope_raw: Mapping[str, Any]
    reason_code: str
    failure_class: str
    recorded_at: datetime
    attempts: int


@dataclass(frozen=True, slots=True)
class ReplayReceipt:
    event_id: str
    window_reason: str


class EventOperationsCoordinator:
    """Wraps a ``CanonicalEventBackbone`` with a bounded per-tenant
    admission quota (backpressure), an immutable dead-letter record
    for failed publishes, a ``POISON`` quarantine gated behind
    explicit operator release, and a ``replay`` operation that always
    re-validates rather than trusting a previously-failed envelope."""

    def __init__(self, backbone: CanonicalEventBackbone, *, max_in_flight_per_tenant: int = 50) -> None:
        self._backbone = backbone
        self._max_in_flight_per_tenant = max_in_flight_per_tenant
        self._in_flight_by_tenant: dict[str, int] = {}
        self._dead_letters: list[DeadLetter] = []
        self._poisoned_event_ids: set[str] = set()
        self._operator_released_event_ids: set[str] = set()
        self._attempts_by_event_id: dict[str, int] = {}
        # Guards every read-modify-write of the counters above, so the quota
        # holds under concurrent publish and the in-flight count never goes negative.
        self._lock = threading.Lock()

    @property
    def dead_letters(self) -> tuple[DeadLetter, ...]:
        return tuple(self._dead_letters)

    def is_poisoned(self, event_id: str) -> bool:
        return event_id in self._poisoned_event_ids

    def publish_with_backpressure(self, envelope: CanonicalIngestionEnvelope, *, tenant: str) -> None:
        """Admits at most ``max_in_flight_per_tenant`` concurrent
        publishes per tenant; a tenant already at quota is refused
        before ever touching the real backbone."""
        with self._lock:
            in_flight = self._in_flight_by_tenant.get(tenant, 0)
            if in_flight >= self._max_in_flight_per_tenant:
                raise OperationsError(
                    "BACKPRESSURE_EXCEEDED",
                    f"tenant {tenant!r} is at its bounded in-flight quota of {self._max_in_flight_per_tenant}",
                )
            self._in_flight_by_tenant[tenant] = in_flight + 1
        try:
            self._publish_and_record(envelope)
        finally:
            with self._lock:
                self._in_flight_by_tenant[tenant] -= 1

    def _publish_and_record(self, envelope: CanonicalIngestionEnvelope) -> None:
        with self._lock:
            attempts = self._attempts_by_event_id.get(envelope.event_id, 0) + 1
            self._attempts_by_event_id[envelope.event_id] = attempts
        try:
            self._backbone.publish(envelope)
        except BackboneError as error:
            failure_class = "POISON" if attempts >= POISON_THRESHOLD else "PERMANENT"
            self._dead_letters.append(
                DeadLetter(
                    event_id=envelope.event_id,
                    envelope_raw=envelope.to_mapping(),
                    reason_code=error.reason_code,
                    failure_class=failure_class,
                    recorded_at=datetime.now(UTC),
                    attempts=attempts,
                )
            )
            if failure_class == "POISON":
                self._poisoned_event_ids.add(envelope.event_id)
            raise

    def release_for_operator_replay(self, event_id: str) -> None:
        """The operator gate: a ``POISON`` event may never be replayed
        without this explicit, separate action."""
        if event_id not in self._poisoned_event_ids:
            raise OperationsError("NOT_POISONED", f"{event_id!r} is not in the poison quarantine")
        self._operator_released_event_ids.add(event_id)

    def replay(self, dead_letter: DeadLetter, *, window_reason: str) -> ReplayReceipt:
        """Replays a dead letter, preserving its original ``event_id``.
        Always re-runs the backbone's own compatibility checks (an
        incompatible schema or lost marking is blocked here exactly as
        it would be for a fresh publish); never publishes a duplicate
        canonical effect, since the backbone's own idempotency-key
        handling makes an already-durable replay a safe no-op."""
        if dead_letter.failure_class == "POISON" and dead_letter.event_id not in self._operator_released_event_ids:
            raise OperationsError(
                "OPERATOR_GATE_CLOSED", f"{dead_letter.event_id!r} requires explicit operator release before replay"
            )
        envelope = CanonicalIngestionEnvelope.from_mapping(dead_letter.envelope_raw)
        self._backbone.publish(envelope)
        return ReplayReceipt(event_id=dead_letter.event_id, window_reason=window_reason)
