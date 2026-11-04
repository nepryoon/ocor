"""C3 outbox relay: committed outbox -> C5 backbone -> DeliveryAttempt.

OCOR-DEV-REM-0050 (NCP-U04, NCR-C3-003). The worker reads only committed outbox entries
of ``main``, publishes each as ``canonical-state-committed`` on the event backbone with
a stable event identity, and records the delivery as a separate DeliveryAttempt only
after the broker acknowledged the write (ADD v1.3 §2.3 :293, §6.2 step 3 :3432; LLD v1.1
§2.3 :132). A crash or a failure between publish and acknowledgement leaves the entry
undelivered: it is published again with the same event identity, and the backbone and
every consumer deduplicate on it (at-least-once; no exactly-once claim, ADD v1.3 :273).

OCOR-DEV-REM-0051 (NCP-U06, NCR-C5-001): the relay is a producer of the C5 admission
boundary. Each entry becomes a signed ``canonical-ingestion-envelope:1.2`` (ADD v1.3
:531-840; LLD v1.1 :154) that realises the GovernedContext integrally (ADD v1.3 :845):

- identity: ``event_id`` is a UUID (ADD v1.3 envelope ``format: uuid``), the name-based
  UUID (RFC 9562 v5) of the outbox event ID, so every relay derives the same one;
  ``idempotency_key`` and ``source.source_record_id`` are the outbox event ID itself;
  ``causation_id`` is the v5 UUID of the action instance, kept verbatim in the payload;
- context: the commit context of the payload, with ``effective_principal_id`` set to the
  relay's authenticated transport principal and that principal appended to
  ``actor_chain`` (ADD v1.3 :197 and :844: both are assigned by the trusted ingress
  boundary, never asserted by the source); ``governed_context_digest`` is the digest of
  that record, so the envelope reproduces it. The commit context and its digest stay in
  the payload, where every projector verifies them;
- marking: the inline ``classification_marking`` is the object that the commit's
  ``classification_marking_ref`` names, read through ``MarkingResolver``; a reference
  that does not resolve, or a marking whose digest does not match the object or the
  reference, is refused (ADD v1.3 :408-411: ``DENY``, never a permissive posture);
- change data capture: ``ingest_mode`` ``CDC`` and ``semantic_class`` ``CDC_CHANGE``
  with ``source_transaction_id`` the commit ID and ``source_position`` the aggregate
  revision (ADD v1.3 :846); ``aggregate.expected_revision`` is the revision, so the
  backbone and the projectors keep the per-aggregate order (LLD v1.1 §2.4 :148);
- digests: the internal ``urn:sha256:<hex>`` form maps one to one to the envelope
  ``sha256:<hex>`` form.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from ..c5.backbone import BackboneError, SignedEnvelope
from ..c5.envelope import ENVELOPE_SCHEMA_ID, ProducerSigner, envelope_digest, marking_digest, urn_digest
from ..c5.operations import ResourceClass
from ..c5.schema import SchemaRegistry, schema_digest
from ..kernel.canonical import format_utc_timestamp
from ..kernel.governed_context import GovernedContext, GovernedContextError
from .events import (
    CANONICAL_STATE_COMMITTED,
    CANONICAL_STATE_COMMITTED_EVENT_TYPE,
    CANONICAL_STATE_COMMITTED_SCHEMA,
    CANONICAL_STATE_COMMITTED_SCHEMA_ID,
    CANONICAL_STATE_COMMITTED_SCHEMA_VERSION,
)
from .ports import C3Error, OutboxEnvelope, _thaw

C3_SOURCE = "urn:ocor:source:c3-canonical-state"
C3_RELAY_ADAPTER = "urn:ocor:adapter:c3-outbox-relay"
C3_RELAY_ADAPTER_VERSION = "1.0.0"
AGGREGATE_TYPE_PREFIX = "urn:ocor:aggregate-type:"
WORLD_PREFIX = "urn:ocor:world:"
# RFC 9562 name-based UUID namespace of OCOR event identities (fixed, never reassigned).
EVENT_NAMESPACE = uuid.UUID("5f0c9a52-7a43-5d1e-9c1b-4f2b8e6d3a10")
PAYLOAD_SCHEMA_PIN: dict[str, str] = {
    "schema_id": CANONICAL_STATE_COMMITTED_SCHEMA_ID,
    "schema_version": CANONICAL_STATE_COMMITTED_SCHEMA_VERSION,
    "schema_digest": schema_digest(CANONICAL_STATE_COMMITTED_SCHEMA),
}

__all__ = [
    "C3_SOURCE",
    "CANONICAL_STATE_COMMITTED_EVENT_TYPE",
    "ENVELOPE_SCHEMA_ID",
    "CanonicalEventPublisher",
    "MarkingResolver",
    "OutboxRelayWorker",
    "RelayError",
    "canonical_event",
    "event_uuid",
    "register_canonical_state_committed",
    "relay_context",
]


class RelayError(RuntimeError):
    """A publish was not acknowledged; the entry stays undelivered."""

    def __init__(self, event_id: str, message: str) -> None:
        self.reason_code = "DELIVERY_NOT_ACKNOWLEDGED"
        self.event_id = event_id
        super().__init__(f"{self.reason_code}: {event_id}: {message}")


@runtime_checkable
class CanonicalEventPublisher(Protocol):
    """The Publish operation of the C5 backbone port."""

    def publish(self, signed: SignedEnvelope, *, transport_principal: str) -> object: ...


@runtime_checkable
class MarkingResolver(Protocol):
    """Resolves a ``*_marking_ref`` to its ``marking`` object (ADD v1.3 :409), or raises."""

    def resolve(self, marking_ref: str) -> Mapping[str, Any]: ...


@runtime_checkable
class RelaySource(Protocol):
    def claim_batch(self, *, limit: int, claim_ttl: timedelta) -> tuple[OutboxEnvelope, ...]: ...

    def acknowledge(self, event_id: str, *, acknowledged_at: datetime) -> None: ...

    def record_failure(self, event_id: str, *, failed_at: datetime, reason: str) -> None: ...


def event_uuid(name: str) -> str:
    """The stable RFC 9562 v5 UUID of an OCOR identifier (outbox event or action instance)."""
    if not isinstance(name, str) or not name:
        raise C3Error("COMMIT_RECEIPT_MISMATCH", "an event identity needs a non-empty name")
    return str(uuid.uuid5(EVENT_NAMESPACE, name))


def relay_context(context: GovernedContext, principal: str) -> GovernedContext:
    """The GovernedContext of the relayed event: the commit context with the relay's
    transport principal as effective principal, appended to the actor chain."""
    if not isinstance(context, GovernedContext):
        raise C3Error("COMMIT_RECEIPT_MISMATCH", "a GovernedContext is required")
    chain = context.actor_chain if principal in context.actor_chain else (*context.actor_chain, principal)
    try:
        return replace(context, effective_principal_id=principal, actor_chain=chain)
    except GovernedContextError as error:
        raise C3Error("COMMIT_RECEIPT_MISMATCH", "the relay principal does not form a GovernedContext") from error


def register_canonical_state_committed(registry: SchemaRegistry) -> dict[str, str]:
    """Register the payload schema and the event type in a C5 schema registry; the event
    type is ``CONTROL``: canonical state changes are never starved by batch traffic
    (LLD v1.1 :338)."""
    pin = registry.register_schema(
        CANONICAL_STATE_COMMITTED_SCHEMA_ID, CANONICAL_STATE_COMMITTED_SCHEMA_VERSION, CANONICAL_STATE_COMMITTED_SCHEMA
    )
    registry.register_event_type(
        CANONICAL_STATE_COMMITTED_EVENT_TYPE, payload_schema=pin, resource_class=ResourceClass.CONTROL
    )
    return pin


def _commit_context(entry: OutboxEnvelope, payload: dict[str, Any]) -> GovernedContext:
    """The commit context of the payload, consistent with every field derived from it."""
    try:
        context = GovernedContext.from_mapping(payload.get("governed_context"))  # type: ignore[arg-type]
    except GovernedContextError as error:
        raise C3Error("COMMIT_RECEIPT_MISMATCH", f"outbox entry {entry.event_id!r} has no GovernedContext") from error
    boundary = {
        "tenant_id": context.tenant_id,
        "domain_id": context.domain_id,
        "compartments": list(context.compartments),
        "classification_marking_ref": context.classification_marking_ref,
        "purpose": context.purpose,
    }
    causation = payload.get("causation_id")
    if (
        payload.get("governed_context_digest") != context.digest()
        or payload.get("boundary") != boundary
        or payload.get("tenant_id") != context.tenant_id
        or payload.get("correlation_id") != context.correlation_id
        or payload.get("actor_chain") != list(context.actor_chain)
        or payload.get("ontology_release_digest") != context.ontology_release_digest
        or not isinstance(causation, str)
        or not causation
    ):
        # A committed entry without its correlation, causation, marking or GCS digest is
        # not the event C3 committed: it is refused, never published.
        raise C3Error("COMMIT_RECEIPT_MISMATCH", f"outbox entry {entry.event_id!r} lacks its event context")
    return context


def _marking(markings: MarkingResolver, reference: str) -> dict[str, Any]:
    try:
        resolved = markings.resolve(reference)
    except Exception as error:  # noqa: BLE001 -- an unresolvable marking denies (fail closed)
        raise C3Error("MARKING_UNRESOLVED", "the classification marking does not resolve") from error
    if not isinstance(resolved, Mapping):
        raise C3Error("MARKING_UNRESOLVED", "the classification marking does not resolve to an object")
    marking: dict[str, Any] = _thaw(resolved)
    declared = marking.get("marking_digest")
    try:
        verified = marking_digest(marking) == declared and urn_digest(str(declared)) == reference
    except BackboneError:
        verified = False
    if not verified:
        raise C3Error("MARKING_UNRESOLVED", "the resolved marking does not match its reference")
    return marking


def canonical_event(
    entry: OutboxEnvelope,
    *,
    signer: ProducerSigner,
    principal: str,
    markings: MarkingResolver,
    ingest_time: datetime,
) -> SignedEnvelope:
    """The signed C5 envelope of one committed outbox entry; refuses an entry whose payload
    is not a canonical-state-committed event of ``main`` for that entry."""
    if not isinstance(entry, OutboxEnvelope):
        raise C3Error("COMMIT_CONTRACT_INVALID", "an OutboxEnvelope is required")
    if not isinstance(signer, ProducerSigner) or not isinstance(markings, MarkingResolver):
        raise TypeError("a ProducerSigner and a MarkingResolver are required")
    payload: dict[str, Any] = _thaw(entry.payload)
    from_revision = payload.get("from_revision")
    if (
        payload.get("event_type") != CANONICAL_STATE_COMMITTED
        or payload.get("commit_id") != entry.commit_id
        or payload.get("aggregate_ref") != entry.aggregate_ref
        or payload.get("to_revision") != entry.aggregate_revision
        or payload.get("branch") != entry.branch
        or isinstance(from_revision, bool)
        or not isinstance(from_revision, int)
    ):
        raise C3Error("COMMIT_RECEIPT_MISMATCH", f"outbox entry {entry.event_id!r} is not its committed event")
    context = _commit_context(entry, payload)
    marking = _marking(markings, context.classification_marking_ref)
    event_context = relay_context(context, principal)
    try:
        return signer.sign(_envelope(entry, payload, event_context, marking, from_revision, ingest_time))
    except BackboneError as error:
        raise C3Error("COMMIT_RECEIPT_MISMATCH", f"outbox entry {entry.event_id!r} lacks its event context") from error


def _envelope(
    entry: OutboxEnvelope,
    payload: dict[str, Any],
    context: GovernedContext,
    marking: dict[str, Any],
    from_revision: int,
    ingest_time: datetime,
) -> dict[str, Any]:
    state_digest = payload.get("state_digest")
    return {
        "envelope_version": "1.2",
        "event_id": event_uuid(entry.event_id),
        "tenant_id": context.tenant_id,
        "organization_id": context.organization_id,
        "domain_id": context.domain_id,
        "compartments": list(context.compartments),
        "world_ref": WORLD_PREFIX + entry.branch,
        "ingest_mode": "CDC",
        "semantic_class": "CDC_CHANGE",
        "event_type_id": CANONICAL_STATE_COMMITTED_EVENT_TYPE,
        "event_time": format_utc_timestamp(entry.occurred_at),
        "ingest_time": format_utc_timestamp(ingest_time),
        "ordering_key": entry.aggregate_ref,
        "idempotency_key": entry.event_id,
        "purpose": context.purpose,
        "source": {
            "source_id": C3_SOURCE,
            "source_record_id": entry.event_id,
            "adapter_id": C3_RELAY_ADAPTER,
            "adapter_version": C3_RELAY_ADAPTER_VERSION,
            "source_event_time_quality": "SOURCE_ASSERTED",
        },
        "aggregate": {
            "aggregate_type_id": AGGREGATE_TYPE_PREFIX + str(payload.get("aggregate_type")),
            "aggregate_id": entry.aggregate_ref,
            "expected_revision": entry.aggregate_revision,
        },
        "payload_schema": dict(PAYLOAD_SCHEMA_PIN),
        "payload": payload,
        "classification_marking": marking,
        "provenance_ref": payload.get("gate_package_digest"),
        "integrity": {},
        "effective_principal_id": context.effective_principal_id,
        "actor_chain": list(context.actor_chain),
        "governed_context_digest": envelope_digest(context.digest()),
        "ontology_release_digest": envelope_digest(context.ontology_release_digest),
        "policy_bundle_digest": envelope_digest(context.policy_bundle_digest),
        "correlation_id": context.correlation_id,
        "causation_id": event_uuid(str(payload.get("causation_id"))),
        "transport": {
            "mode": "CDC",
            "operation": "CREATE" if from_revision == 0 else "UPDATE",
            "source_transaction_id": entry.commit_id,
            "source_position": str(entry.aggregate_revision),
            "before_digest": None,
            "after_digest": envelope_digest(str(state_digest)),
        },
    }


class OutboxRelayWorker:
    """Claims committed entries, publishes them, and records each outcome."""

    def __init__(
        self,
        relay: RelaySource,
        backbone: CanonicalEventPublisher,
        *,
        signer: ProducerSigner,
        principal: str,
        markings: MarkingResolver,
        claim_ttl: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not isinstance(relay, RelaySource):
            raise TypeError("relay must implement claim_batch, acknowledge and record_failure")
        if not isinstance(backbone, CanonicalEventPublisher):
            raise TypeError("backbone must implement publish")
        if not isinstance(signer, ProducerSigner):
            raise TypeError("signer must be a ProducerSigner")
        if not isinstance(principal, str) or not principal:
            raise TypeError("principal must be the relay's authenticated transport principal")
        if not isinstance(markings, MarkingResolver):
            raise TypeError("markings must implement MarkingResolver")
        if not isinstance(claim_ttl, timedelta) or claim_ttl < timedelta(0):
            raise TypeError("claim_ttl must be a non-negative timedelta")
        self._relay = relay
        self._backbone = backbone
        self._signer = signer
        self._principal = principal
        self._markings = markings
        self._claim_ttl = claim_ttl
        self._clock = clock

    def relay_once(self, *, limit: int) -> tuple[str, ...]:
        """Relays one batch in outbox order and returns the delivered outbox event IDs. The
        first unacknowledged publish stops the batch with ``RelayError`` after recording the
        failure; later entries of the batch are not published out of order."""
        delivered: list[str] = []
        for entry in self._relay.claim_batch(limit=limit, claim_ttl=self._claim_ttl):
            signed = canonical_event(
                entry, signer=self._signer, principal=self._principal, markings=self._markings,
                ingest_time=self._clock(),
            )
            try:
                self._backbone.publish(signed, transport_principal=self._principal)
            except Exception as error:  # noqa: BLE001 -- any publish failure is a non-delivery
                self._relay.record_failure(entry.event_id, failed_at=self._clock(), reason=type(error).__name__)
                raise RelayError(entry.event_id, "the backbone did not acknowledge the publish") from error
            self._relay.acknowledge(entry.event_id, acknowledged_at=self._clock())
            delivered.append(entry.event_id)
        return tuple(delivered)
