"""OCOR-DEV-0041: Implement C5 registry replay backpressure DLQ and quarantine.

Proves that EventOperationsCoordinator bounds admission with a real
per-tenant backpressure quota, records real publish failures as
immutable dead letters, quarantines a repeatedly-failing event as
POISON behind an explicit operator gate, and replays a dead letter
only by re-running the exact same compatibility checks a fresh publish
would -- an incompatible schema or lost marking is blocked on replay
too, never bypassed. Every test drives a real, live, self-provisioned
Kafka broker -- no mocks.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from c5_backbone_fixture import AUTHORITY, OPERATOR, TENANT, C5Rig, Draft, draft, live_dsn, schema_name
from c5_kafka_qualification import KafkaBrokerError, QualificationKafkaBroker
from ocor_runtime.c5.backbone import BackboneError
from ocor_runtime.c5.operations import DeadLetter, EventOperationsCoordinator, OperationsError, ResourceClass

DIGEST_A = "urn:sha256:" + "a" * 64
SCHEMA = "urn:ocor:schema:canonical-ingestion-envelope:1"


def envelope(
    *,
    aggregate_ref: str,
    sequence: int = 1,
    event_id: str | None = None,
    schema_ref: str = SCHEMA,
    classification_marking_ref: str = DIGEST_A,
) -> Draft:
    value = draft(
        aggregate_ref=aggregate_ref,
        sequence=sequence,
        event_id=event_id,
        schema_ref=schema_ref,
        context=DIGEST_A,
        correlation_id="018f2f95-01b2-7cc3-8d4e-123456789abc",
        causation_id="018f2f95-01b2-7cc3-8d4e-000000000000",
        payload={"status": "ASSESSED"},
    )
    if classification_marking_ref == "":
        # the 1.2 envelope carries the marking object inline (ADD v1.3 :409): a lost
        # marking is an absent marking object
        del value.raw["classification_marking"]
    return value


@pytest.fixture
def backbone() -> Iterator[C5Rig]:
    topic = f"ocor-operations-fixture-{uuid.uuid4().hex[:12]}"
    try:
        broker, container, volume = QualificationKafkaBroker.provision(topic)
    except KafkaBrokerError as error:
        pytest.fail(f"a real, live, self-provisioned Kafka broker is mandatory qualifying evidence: {error}")
    value = None
    try:
        value = C5Rig(
            broker, topic, dsn=live_dsn(), schema=schema_name("ocor_c5_0041"), quotas={ResourceClass.BATCH: 2}
        )
        yield value
    finally:
        if value is not None:
            value.drop()
        broker.destroy(volume)


@pytest.fixture
def coordinator(backbone: C5Rig) -> EventOperationsCoordinator:
    return backbone.coordinator()


def operator_replay(coordinator: EventOperationsCoordinator, letter: DeadLetter, reason: str) -> Any:
    """``ReprocessAuthorized`` of a dead letter, requested by the operator with the replay authority."""
    return coordinator.replay(letter, reason=reason, requested_by=OPERATOR, authority_ref=AUTHORITY)


def synthetic_letter(raw: dict[str, Any], *, reason_code: str, signature: bytes | None) -> DeadLetter:
    return DeadLetter(
        dead_letter_id=str(uuid.uuid4()),
        event_id=raw["event_id"],
        failure_class="PERMANENT",
        reason_code=reason_code,
        envelope=raw,
        attempts=1,
        recorded_at=datetime.now(UTC),
        signature=signature,
    )


def test_a_valid_event_publishes_through_backpressure_and_is_delivered(
    coordinator: EventOperationsCoordinator, backbone: C5Rig
) -> None:
    coordinator.publish_with_backpressure(
        backbone.sign(envelope(aggregate_ref="urn:ocor:mission-object:ops:1")), tenant=TENANT
    )

    delivered = backbone.consume(1)
    assert len(delivered) == 1
    assert coordinator.dead_letters == ()


def test_backpressure_refuses_admission_once_a_tenant_is_at_its_bounded_quota(
    coordinator: EventOperationsCoordinator, backbone: C5Rig
) -> None:
    # exhaust the quota (2) of the tenant's BATCH class with two in-flight admissions,
    # so the publish is not itself rejected for an unrelated reason.
    admission = backbone.backbone._admission  # noqa: SLF001 -- simulates two real in-flight publishes
    for _ in range(2):
        admission.try_admit(TENANT, ResourceClass.BATCH)

    with pytest.raises(OperationsError) as excinfo:
        coordinator.publish_with_backpressure(
            backbone.sign(envelope(aggregate_ref="urn:ocor:mission-object:ops:2")), tenant=TENANT
        )
    assert excinfo.value.reason_code == "BACKPRESSURE_EXCEEDED"


def test_a_failed_publish_is_recorded_as_an_immutable_permanent_dead_letter(
    coordinator: EventOperationsCoordinator, backbone: C5Rig
) -> None:
    bad = envelope(aggregate_ref="urn:ocor:mission-object:ops:3", schema_ref="urn:ocor:schema:not-registered:1")
    signed = backbone.sign(bad)

    with pytest.raises(BackboneError):
        coordinator.publish_with_backpressure(signed, tenant=TENANT)

    assert len(coordinator.dead_letters) == 1
    letter = coordinator.dead_letters[0]
    assert letter.event_id == bad.event_id
    assert letter.failure_class == "PERMANENT"
    assert letter.reason_code == "UNKNOWN_SCHEMA"
    assert letter.attempts == 1


def test_repeated_failures_of_the_same_event_are_classified_poison(
    coordinator: EventOperationsCoordinator, backbone: C5Rig
) -> None:
    bad = envelope(
        aggregate_ref="urn:ocor:mission-object:ops:4",
        event_id="urn:ocor:event:poison-1",
        schema_ref="urn:ocor:schema:not-registered:1",
    )
    signed = backbone.sign(bad)

    for _ in range(3):
        with pytest.raises(BackboneError):
            coordinator.publish_with_backpressure(signed, tenant=TENANT)

    assert coordinator.is_poisoned(bad.event_id)
    assert coordinator.dead_letters[-1].failure_class == "POISON"
    assert coordinator.dead_letters[-1].attempts == 3


def test_a_poisoned_event_cannot_be_replayed_without_explicit_operator_release(
    coordinator: EventOperationsCoordinator, backbone: C5Rig
) -> None:
    bad = envelope(
        aggregate_ref="urn:ocor:mission-object:ops:5",
        event_id="urn:ocor:event:poison-2",
        schema_ref="urn:ocor:schema:not-registered:1",
    )
    signed = backbone.sign(bad)
    for _ in range(3):
        with pytest.raises(BackboneError):
            coordinator.publish_with_backpressure(signed, tenant=TENANT)
    letter = coordinator.dead_letters[-1]

    with pytest.raises(OperationsError) as excinfo:
        operator_replay(coordinator, letter, "operator-requested-retry")
    assert excinfo.value.reason_code == "OPERATOR_GATE_CLOSED"


def test_operator_release_still_cannot_replay_past_an_incompatible_schema(
    coordinator: EventOperationsCoordinator, backbone: C5Rig
) -> None:
    bad = envelope(
        aggregate_ref="urn:ocor:mission-object:ops:6",
        event_id="urn:ocor:event:poison-3",
        schema_ref="urn:ocor:schema:not-registered:1",
    )
    signed = backbone.sign(bad)
    for _ in range(3):
        with pytest.raises(BackboneError):
            coordinator.publish_with_backpressure(signed, tenant=TENANT)
    letter = coordinator.dead_letters[-1]
    coordinator.release_for_operator_replay(bad.event_id, operator=OPERATOR, authority_ref=AUTHORITY)

    with pytest.raises(BackboneError) as excinfo:
        operator_replay(coordinator, letter, "operator-requested-retry")
    assert excinfo.value.reason_code == "UNKNOWN_SCHEMA"


def test_replay_of_lost_marking_is_blocked_exactly_like_a_fresh_publish(
    coordinator: EventOperationsCoordinator,
) -> None:
    lossy_raw = envelope(aggregate_ref="urn:ocor:mission-object:ops:7", classification_marking_ref="").to_mapping()

    letter = synthetic_letter(lossy_raw, reason_code="SCHEMA_VIOLATION", signature=None)

    with pytest.raises(BackboneError) as excinfo:
        operator_replay(coordinator, letter, "operator-requested-retry")
    assert excinfo.value.reason_code == "SCHEMA_VIOLATION"


def test_a_valid_replay_preserves_the_original_event_id_and_never_double_publishes(
    coordinator: EventOperationsCoordinator, backbone: C5Rig
) -> None:
    good = envelope(aggregate_ref="urn:ocor:mission-object:ops:8", event_id="urn:ocor:event:replay-1")
    signed = backbone.sign(good)
    coordinator.publish_with_backpressure(signed, tenant=TENANT)

    # construct a synthetic dead letter for the ALREADY-durable event to
    # prove replay of an already-published idempotency key is a safe
    # no-op, never a duplicate canonical effect.
    letter = synthetic_letter(
        signed.envelope.to_mapping(), reason_code="TRANSIENT_RETRY_SIMULATED", signature=signed.signature
    )

    receipt = operator_replay(coordinator, letter, "operator-requested-retry")
    assert receipt.event_id == good.event_id

    delivered = backbone.consume(1)
    assert len(delivered) == 1, "the replay of an already-durable idempotency key must never create a second record"
