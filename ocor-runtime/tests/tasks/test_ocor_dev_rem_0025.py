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
from ocor_runtime.c5.backbone import (
    BOOTSTRAP,
    BackboneError,
    CanonicalEventBackbone,
    CanonicalIngestionEnvelope,
    KafkaBackboneError,
)
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
) -> CanonicalIngestionEnvelope:
    event_id = event_id or f"urn:ocor:event:{uuid.uuid4()}"
    return CanonicalIngestionEnvelope(
        event_id=event_id,
        event_type="MissionEffectRecorded",
        event_version="1.0.0",
        schema_ref=SCHEMA,
        producer_principal="urn:ocor:principal:c6-engine",
        source_ref="urn:ocor:source:rem-0025-fixture",
        aggregate_ref=aggregate_ref,
        correlation_id=str(uuid.uuid4()),
        causation_id=str(uuid.uuid4()),
        classification_marking_ref="urn:sha256:" + "c" * 64,
        governed_context_digest=context,
        idempotency_key=idempotency_key or event_id,
        sequence=sequence,
        payload={"context": str(context)[-1:]},
    )


def topic_record_count(backbone: CanonicalEventBackbone) -> int:
    """Exact number of records on the real topic (sum of partition end offsets)."""
    output = backbone._exec(  # noqa: SLF001 -- read-only observation of the real broker
        "kafka-get-offsets", "--bootstrap-server", BOOTSTRAP, "--topic", backbone._topic, "--time", "-1"  # noqa: SLF001
    )
    lines = [line for line in output.splitlines() if line.count(":") == 2]
    assert lines, f"no partition offsets reported: {output!r}"
    return sum(int(line.rsplit(":", 1)[1]) for line in lines)


def delivered_event_ids(backbone: CanonicalEventBackbone) -> list[str]:
    count = topic_record_count(backbone)
    return [record.envelope.event_id for record in backbone.consume(count)] if count else []


@pytest.fixture
def backbone() -> Iterator[CanonicalEventBackbone]:
    topic = f"ocor-rem0025-fixture-{uuid.uuid4().hex[:12]}"
    try:
        value, _container, volume = CanonicalEventBackbone.provision(topic)
    except KafkaBackboneError as error:
        pytest.fail(f"a real, live, self-provisioned Kafka broker is mandatory qualifying evidence: {error}")
    try:
        yield value
    finally:
        value.destroy(volume)


# P1 -- publish: dedup branch


def test_p1_same_idempotency_key_in_two_contexts_publishes_both_events(backbone: CanonicalEventBackbone) -> None:
    a = envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0025:a1", idempotency_key="shared-key-p1")
    b = envelope(context=CONTEXT_B, aggregate_ref="urn:ocor:mission-object:rem0025:b1", idempotency_key="shared-key-p1")

    backbone.publish(a)
    backbone.publish(b)

    assert backbone.quarantine == ()
    assert sorted(delivered_event_ids(backbone)) == sorted([a.event_id, b.event_id])


def test_same_idempotency_key_in_the_same_context_is_still_a_safe_no_op(backbone: CanonicalEventBackbone) -> None:
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
    backbone: CanonicalEventBackbone,
) -> None:
    a = envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0025:a3", idempotency_key="shared-key-3")
    b = envelope(context=CONTEXT_B, aggregate_ref="urn:ocor:mission-object:rem0025:b3", idempotency_key="shared-key-3")

    for value in (a, b, a, b):
        backbone.publish(value)

    assert backbone.quarantine == ()
    assert sorted(delivered_event_ids(backbone)) == sorted([a.event_id, b.event_id])


# P3 -- publish: per-aggregate sequence branch


def test_p3_same_aggregate_ref_in_two_contexts_is_ordered_per_context(backbone: CanonicalEventBackbone) -> None:
    shared = "urn:ocor:mission-object:rem0025:shared-aggregate"
    a5 = envelope(context=CONTEXT_A, aggregate_ref=shared, sequence=5)
    b1 = envelope(context=CONTEXT_B, aggregate_ref=shared, sequence=1)

    backbone.publish(a5)
    backbone.publish(b1)

    assert backbone.quarantine == ()
    assert sorted(delivered_event_ids(backbone)) == sorted([a5.event_id, b1.event_id])


def test_out_of_order_within_one_context_is_still_quarantined_beside_another_context(
    backbone: CanonicalEventBackbone,
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


def test_p2_operations_path_publishes_both_contexts_for_a_reused_key(backbone: CanonicalEventBackbone) -> None:
    coordinator = EventOperationsCoordinator(backbone)
    a = envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0025:a4", idempotency_key="shared-key-p2")
    b = envelope(context=CONTEXT_B, aggregate_ref="urn:ocor:mission-object:rem0025:b4", idempotency_key="shared-key-p2")

    coordinator.publish_with_backpressure(a, tenant="tenant-a")
    coordinator.publish_with_backpressure(b, tenant="tenant-b")

    assert coordinator.dead_letters == ()
    assert backbone.quarantine == ()
    assert sorted(delivered_event_ids(backbone)) == sorted([a.event_id, b.event_id])


def _letter(value: CanonicalIngestionEnvelope) -> DeadLetter:
    return DeadLetter(
        event_id=value.event_id,
        envelope_raw=value.to_mapping(),
        reason_code="TRANSIENT_RETRY_SIMULATED",
        failure_class="PERMANENT",
        recorded_at=datetime.now(UTC),
        attempts=1,
    )


def test_dlq_replay_of_context_b_is_not_suppressed_by_context_a(backbone: CanonicalEventBackbone) -> None:
    coordinator = EventOperationsCoordinator(backbone)
    a = envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0025:a5", idempotency_key="shared-key-dlq")
    b = envelope(context=CONTEXT_B, aggregate_ref="urn:ocor:mission-object:rem0025:b5", idempotency_key="shared-key-dlq")
    coordinator.publish_with_backpressure(a, tenant="tenant-a")

    receipt = coordinator.replay(_letter(b), window_reason="operator-requested-retry")

    assert receipt.event_id == b.event_id
    assert sorted(delivered_event_ids(backbone)) == sorted([a.event_id, b.event_id])


def test_dlq_replay_of_an_already_durable_same_context_event_is_still_a_no_op(
    backbone: CanonicalEventBackbone,
) -> None:
    coordinator = EventOperationsCoordinator(backbone)
    a = envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0025:a6", idempotency_key="key-dlq-same")
    b = envelope(context=CONTEXT_B, aggregate_ref="urn:ocor:mission-object:rem0025:b6", idempotency_key="key-dlq-same")
    coordinator.publish_with_backpressure(a, tenant="tenant-a")
    coordinator.publish_with_backpressure(b, tenant="tenant-b")

    receipt = coordinator.replay(_letter(b), window_reason="operator-requested-retry")

    assert receipt.event_id == b.event_id
    assert sorted(delivered_event_ids(backbone)) == sorted([a.event_id, b.event_id])


# Fail closed: an envelope whose isolation context cannot be determined


@pytest.mark.parametrize("context", ["", None, 7], ids=["empty", "none", "non-string"])
def test_an_undeterminable_context_fails_closed_and_is_never_published(
    backbone: CanonicalEventBackbone, context: Any
) -> None:
    valid = envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0025:a7", idempotency_key="key-ctx")
    backbone.publish(valid)
    missing = envelope(context=context, aggregate_ref="urn:ocor:mission-object:rem0025:a7", idempotency_key="key-ctx")

    with pytest.raises(BackboneError) as excinfo:
        backbone.publish(missing)

    assert excinfo.value.reason_code == "MISSING_CONTEXT"
    assert [q.reason_code for q in backbone.quarantine] == ["MISSING_CONTEXT"]
    assert backbone.quarantine[0].raw["event_id"] == missing.event_id
    assert delivered_event_ids(backbone) == [valid.event_id]
