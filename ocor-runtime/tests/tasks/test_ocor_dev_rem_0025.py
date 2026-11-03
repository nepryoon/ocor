"""OCOR-DEV-REM-0025: C5 dedup and sequence state scoped by the isolation context.

ADD v1.3 section 1.4 binds every event to exactly one ``GovernedContext`` and
forbids sharing indexes between incompatible isolation tuples; section 3.2 makes
``idempotency_key`` deduplicate the *logical event* and guarantees ordering only
per ordering key. The PoC ``CanonicalIngestionEnvelope`` carries the context as
``governed_context_digest`` (the digest of the whole ``GovernedContext``, which
includes the isolation tuple), so dedup and per-aggregate sequence state are
keyed by that digest plus ``idempotency_key`` / ``aggregate_ref``.

INFO-A probe observations reproduced here as qualifying tests:

- P1: an event of context B reusing context A's ``idempotency_key`` was dropped
  silently (no error, no quarantine, no record on the topic);
- P2: the same drop through ``EventOperationsCoordinator`` (backpressure and
  DLQ replay path), with no dead letter;
- P3: an event of context B was quarantined ``OUT_OF_ORDER`` because of the
  sequence of context A on the same ``aggregate_ref``.

Same-context replay stays a safe no-op and same-context regression stays
``OUT_OF_ORDER`` (PO decision INFO-A option 1: no same-key/different-payload
conflict detection). An envelope whose context cannot be determined fails closed.
Every test drives a real, self-provisioned Kafka broker -- no mock of the
backbone boundary. Exact topic contents are read through Kafka's own end
offsets, so a dropped or duplicated record cannot hide behind a bounded consume.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from c5_backbone_fixture import AUTHORITY, OPERATOR, C5Rig, Draft, draft, live_dsn, schema_name, tenant
from c5_kafka_qualification import KafkaBrokerError, QualificationKafkaBroker
from ocor_runtime.c5.backbone import BackboneError, SignedEnvelope
from ocor_runtime.c5.operations import DeadLetter, EventOperationsCoordinator

CONTEXT_A = "urn:sha256:" + "a" * 64
CONTEXT_B = "urn:sha256:" + "b" * 64
SCHEMA = "urn:ocor:schema:canonical-ingestion-envelope:1"


def envelope(
    *,
    context: Any,
    aggregate_ref: str,
    sequence: int = 1,
    idempotency_key: str | None = None,
    event_id: str | None = None,
) -> Draft:
    return draft(
        aggregate_ref=aggregate_ref,
        sequence=sequence,
        event_id=event_id,
        idempotency_key=idempotency_key,
        schema_ref=SCHEMA,
        context=context,
        correlation_id=str(uuid.uuid4()),
        causation_id=str(uuid.uuid4()),
        payload={"context": str(context)[-1:]},
    )


def topic_record_count(backbone: C5Rig) -> int:
    """Exact number of records on the real topic (sum of partition end offsets)."""
    offsets = backbone.broker.end_offsets(backbone.topic)  # read-only observation of the real broker
    assert offsets, "no partition offsets reported"
    return sum(offsets.values())


def delivered_event_ids(backbone: C5Rig) -> list[str]:
    count = topic_record_count(backbone)
    return [value["event_id"] for value in backbone.topic_envelopes()] if count else []


@pytest.fixture
def backbone() -> Iterator[C5Rig]:
    topic = f"ocor-rem0025-fixture-{uuid.uuid4().hex[:12]}"
    try:
        broker, _container, volume = QualificationKafkaBroker.provision(topic)
    except KafkaBrokerError as error:
        pytest.fail(f"a real, live, self-provisioned Kafka broker is mandatory qualifying evidence: {error}")
    value = None
    try:
        value = C5Rig(broker, topic, dsn=live_dsn(), schema=schema_name("ocor_c5_rem0025"))
        yield value
    finally:
        if value is not None:
            value.drop()
        broker.destroy(volume)


def publish_as(coordinator: EventOperationsCoordinator, backbone: C5Rig, value: Draft, name: str) -> None:
    """The coordinator publish of a draft of tenant ``name``."""
    value.raw["tenant_id"] = tenant(name)
    coordinator.publish_with_backpressure(backbone.sign(value), tenant=tenant(name))


def operator_replay(coordinator: EventOperationsCoordinator, letter: DeadLetter) -> Any:
    """``ReprocessAuthorized`` of a dead letter, requested by the operator with the replay authority."""
    return coordinator.replay(letter, reason="operator-requested-retry", requested_by=OPERATOR, authority_ref=AUTHORITY)


# P1 -- publish: dedup branch


def test_p1_same_idempotency_key_in_two_contexts_publishes_both_events(backbone: C5Rig) -> None:
    a = envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0025:a1", idempotency_key="shared-key-p1")
    b = envelope(context=CONTEXT_B, aggregate_ref="urn:ocor:mission-object:rem0025:b1", idempotency_key="shared-key-p1")

    backbone.publish(a)
    backbone.publish(b)

    assert backbone.quarantine == ()
    assert sorted(delivered_event_ids(backbone)) == sorted([a.event_id, b.event_id])


def test_same_idempotency_key_in_the_same_context_is_still_a_safe_no_op(backbone: C5Rig) -> None:
    first = envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0025:a2", idempotency_key="same-key")
    replay = envelope(
        context=CONTEXT_A,
        aggregate_ref="urn:ocor:mission-object:rem0025:a2",
        idempotency_key="same-key",
        event_id=first.event_id,
    )

    backbone.publish(first)
    backbone.publish(replay)

    assert backbone.quarantine == ()
    assert delivered_event_ids(backbone) == [first.event_id], "a same-context replay must not add a second record"


def test_each_context_keeps_its_own_replay_no_op_after_a_cross_context_key_reuse(
    backbone: C5Rig,
) -> None:
    a = envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0025:a3", idempotency_key="shared-key-3")
    b = envelope(context=CONTEXT_B, aggregate_ref="urn:ocor:mission-object:rem0025:b3", idempotency_key="shared-key-3")

    for value in (a, b, a, b):
        backbone.publish(value)

    assert backbone.quarantine == ()
    assert sorted(delivered_event_ids(backbone)) == sorted([a.event_id, b.event_id])


# P3 -- publish: per-aggregate sequence branch


def test_p3_same_aggregate_ref_in_two_contexts_is_ordered_per_context(backbone: C5Rig) -> None:
    shared = "urn:ocor:mission-object:rem0025:shared-aggregate"
    a5 = envelope(context=CONTEXT_A, aggregate_ref=shared, sequence=5)
    b1 = envelope(context=CONTEXT_B, aggregate_ref=shared, sequence=1)

    backbone.publish(a5)
    backbone.publish(b1)

    assert backbone.quarantine == ()
    assert sorted(delivered_event_ids(backbone)) == sorted([a5.event_id, b1.event_id])


def test_out_of_order_within_one_context_is_still_quarantined_beside_another_context(
    backbone: C5Rig,
) -> None:
    shared = "urn:ocor:mission-object:rem0025:interleaved"
    a3 = envelope(context=CONTEXT_A, aggregate_ref=shared, sequence=3)
    b10 = envelope(context=CONTEXT_B, aggregate_ref=shared, sequence=10)
    a4 = envelope(context=CONTEXT_A, aggregate_ref=shared, sequence=4)
    backbone.publish(a3)
    backbone.publish(b10)
    backbone.publish(a4)  # advances context A's own watermark, not context B's

    for late in (
        envelope(context=CONTEXT_A, aggregate_ref=shared, sequence=2),
        envelope(context=CONTEXT_A, aggregate_ref=shared, sequence=4),
        envelope(context=CONTEXT_B, aggregate_ref=shared, sequence=5),
    ):
        with pytest.raises(BackboneError) as excinfo:
            backbone.publish(late)
        assert excinfo.value.reason_code == "OUT_OF_ORDER"
        assert backbone.quarantine[-1].reason_code == "OUT_OF_ORDER"
        assert backbone.quarantine[-1].raw["event_id"] == late.event_id

    assert len(backbone.quarantine) == 3
    assert sorted(delivered_event_ids(backbone)) == sorted([a3.event_id, b10.event_id, a4.event_id])


# P2 -- EventOperationsCoordinator: backpressure publish and DLQ replay


def test_p2_operations_path_publishes_both_contexts_for_a_reused_key(backbone: C5Rig) -> None:
    coordinator = backbone.coordinator()
    a = envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0025:a4", idempotency_key="shared-key-p2")
    b = envelope(context=CONTEXT_B, aggregate_ref="urn:ocor:mission-object:rem0025:b4", idempotency_key="shared-key-p2")

    publish_as(coordinator, backbone, a, "tenant-a")
    publish_as(coordinator, backbone, b, "tenant-b")

    assert coordinator.dead_letters == ()
    assert backbone.quarantine == ()
    assert sorted(delivered_event_ids(backbone)) == sorted([a.event_id, b.event_id])


def _letter(value: SignedEnvelope) -> DeadLetter:
    return DeadLetter(
        dead_letter_id=str(uuid.uuid4()),
        event_id=value.envelope.event_id,
        failure_class="PERMANENT",
        reason_code="TRANSIENT_RETRY_SIMULATED",
        envelope=value.envelope.to_mapping(),
        attempts=1,
        recorded_at=datetime.now(UTC),
        signature=value.signature,
    )


def test_dlq_replay_of_context_b_is_not_suppressed_by_context_a(backbone: C5Rig) -> None:
    coordinator = backbone.coordinator()
    a = envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0025:a5", idempotency_key="shared-key-dlq")
    b = envelope(context=CONTEXT_B, aggregate_ref="urn:ocor:mission-object:rem0025:b5", idempotency_key="shared-key-dlq")
    publish_as(coordinator, backbone, a, "tenant-a")

    receipt = operator_replay(coordinator, _letter(backbone.sign(b)))

    assert receipt.event_id == b.event_id
    assert sorted(delivered_event_ids(backbone)) == sorted([a.event_id, b.event_id])


def test_dlq_replay_of_an_already_durable_same_context_event_is_still_a_no_op(
    backbone: C5Rig,
) -> None:
    coordinator = backbone.coordinator()
    a = envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0025:a6", idempotency_key="key-dlq-same")
    b = envelope(context=CONTEXT_B, aggregate_ref="urn:ocor:mission-object:rem0025:b6", idempotency_key="key-dlq-same")
    publish_as(coordinator, backbone, a, "tenant-a")
    publish_as(coordinator, backbone, b, "tenant-b")

    receipt = operator_replay(coordinator, _letter(backbone.sign(b)))

    assert receipt.event_id == b.event_id
    assert sorted(delivered_event_ids(backbone)) == sorted([a.event_id, b.event_id])


# Fail closed: an envelope whose isolation context cannot be determined


@pytest.mark.parametrize("context", ["", None, 7], ids=["empty", "none", "non-string"])
def test_an_undeterminable_context_fails_closed_and_is_never_published(
    backbone: C5Rig, context: Any
) -> None:
    valid = envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0025:a7", idempotency_key="key-ctx")
    backbone.publish(valid)
    missing = envelope(context=context, aggregate_ref="urn:ocor:mission-object:rem0025:a7", idempotency_key="key-ctx")

    with pytest.raises(BackboneError) as excinfo:
        backbone.publish(missing)

    assert excinfo.value.reason_code == "SCHEMA_VIOLATION"
    assert [q.reason_code for q in backbone.quarantine] == []
    assert excinfo.value.failure_class == "PERMANENT"
    assert delivered_event_ids(backbone) == [valid.event_id]
