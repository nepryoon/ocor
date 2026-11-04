"""OCOR-DEV-0040: Implement C5 canonical event backbone.

Proves that schema-bound events published through CanonicalEventBackbone
preserve partition order, correlation, causation, markings and
idempotency on a real, live, self-provisioned Kafka broker, and that an
unknown schema, missing governed context, or an out-of-order aggregate
effect is quarantined rather than published. Every test drives a real
broker -- no mocks. No CI workflow provisions a shared Kafka service, so
this task self-provisions its own isolated broker per test, the same
real configuration OCOR-DEV-0019's spike already proved.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from c5_backbone_fixture import C5Rig, Draft, draft, live_dsn, schema_name, unreachable_bootstrap
from c5_kafka_qualification import KafkaBrokerError, QualificationKafkaBroker
from ocor_runtime.c5.backbone import BackboneError
from ocor_runtime.c5.backbone import KafkaJournalError as KafkaBackboneError

DIGEST_A = "urn:sha256:" + "a" * 64
SCHEMA = "urn:ocor:schema:canonical-ingestion-envelope:1"


def envelope(
    *,
    aggregate_ref: str,
    sequence: int,
    event_id: str | None = None,
    idempotency_key: str | None = None,
    schema_ref: str = SCHEMA,
) -> Draft:
    return draft(
        aggregate_ref=aggregate_ref,
        sequence=sequence,
        event_id=event_id,
        idempotency_key=idempotency_key,
        schema_ref=schema_ref,
        context=DIGEST_A,
        correlation_id="018f2f95-01b2-7cc3-8d4e-123456789abc",
        causation_id="018f2f95-01b2-7cc3-8d4e-000000000000",
        payload={"status": "ASSESSED"},
    )


@pytest.fixture
def backbone() -> Iterator[C5Rig]:
    topic = f"ocor-backbone-fixture-{uuid.uuid4().hex[:12]}"
    try:
        broker, container, volume = QualificationKafkaBroker.provision(topic)
    except KafkaBrokerError as error:
        pytest.fail(f"a real, live, self-provisioned Kafka broker is mandatory qualifying evidence: {error}")
    value = None
    try:
        value = C5Rig(broker, topic, dsn=live_dsn(), schema=schema_name("ocor_c5_0040"))
        yield value
    finally:
        if value is not None:
            value.drop()
        broker.destroy(volume)


def test_a_registered_schema_event_publishes_and_is_consumed_preserving_all_fields(
    backbone: C5Rig,
) -> None:
    sent = envelope(aggregate_ref="urn:ocor:mission-object:backbone:1", sequence=1)
    backbone.publish(sent)

    delivered = backbone.consume(1)
    assert len(delivered) == 1
    received = delivered[0].envelope
    assert received.event_id == sent.event_id
    assert received.correlation_id == sent.correlation_id
    assert received.causation_id == sent.causation_id
    assert received.to_mapping()["classification_marking"] == sent["classification_marking"]
    assert received.idempotency_key == sent.idempotency_key


def test_partition_order_is_preserved_for_a_single_aggregate(backbone: C5Rig) -> None:
    aggregate_ref = "urn:ocor:mission-object:backbone:2"
    for sequence in range(1, 6):
        backbone.publish(envelope(aggregate_ref=aggregate_ref, sequence=sequence))

    delivered = backbone.consume(5)
    partitions = backbone.partitions_of([record.envelope.event_id for record in delivered])
    assert len(partitions) == 1, "every event for one aggregate must land in the identical real Kafka partition"
    sequences = [record.envelope.aggregate["expected_revision"] for record in delivered]
    assert sequences == sorted(sequences), "within one partition, real Kafka delivery order matches publish order"


def test_an_unknown_schema_is_quarantined_and_never_published(backbone: C5Rig) -> None:
    bad = envelope(
        aggregate_ref="urn:ocor:mission-object:backbone:3", sequence=1, schema_ref="urn:ocor:schema:not-registered:1"
    )
    with pytest.raises(BackboneError) as excinfo:
        backbone.publish(bad)
    assert excinfo.value.reason_code == "UNKNOWN_SCHEMA"
    assert len(backbone.quarantine) == 1
    assert backbone.quarantine[0].reason_code == "UNKNOWN_SCHEMA"


def test_missing_governed_context_is_quarantined_before_publication(backbone: C5Rig) -> None:
    raw = envelope(aggregate_ref="urn:ocor:mission-object:backbone:4", sequence=1).to_mapping()
    del raw["correlation_id"]

    with pytest.raises(BackboneError) as excinfo:
        backbone.publish_from_mapping(raw)
    assert excinfo.value.reason_code == "SCHEMA_VIOLATION"
    assert len(backbone.quarantine) == 0
    assert backbone.topic_records() == 0


def test_an_out_of_order_aggregate_effect_is_quarantined_and_never_published(
    backbone: C5Rig,
) -> None:
    aggregate_ref = "urn:ocor:mission-object:backbone:5"
    backbone.publish(envelope(aggregate_ref=aggregate_ref, sequence=3))

    with pytest.raises(BackboneError) as excinfo:
        backbone.publish(envelope(aggregate_ref=aggregate_ref, sequence=2))
    assert excinfo.value.reason_code == "OUT_OF_ORDER"
    assert backbone.quarantine[-1].reason_code == "OUT_OF_ORDER"

    delivered = backbone.consume(1)
    assert delivered[0].envelope.aggregate["expected_revision"] == 3, (
        "the out-of-order attempt must never have reached the real topic"
    )


def test_a_replayed_idempotency_key_is_a_safe_no_op_not_a_duplicate_publish(
    backbone: C5Rig,
) -> None:
    first = envelope(aggregate_ref="urn:ocor:mission-object:backbone:6", sequence=1, idempotency_key="idem-key-1")
    backbone.publish(first)
    # the same idempotency key, replayed (e.g. a retried producer call) --
    # must not create a second real record on the topic.
    replay = envelope(
        aggregate_ref="urn:ocor:mission-object:backbone:6",
        sequence=1,
        event_id=first.event_id,
        idempotency_key="idem-key-1",
    )
    backbone.publish(replay)

    delivered = backbone.consume(1)
    assert len(delivered) == 1


def test_a_real_kafka_unreachability_fails_closed() -> None:
    # fault point: the in-process client of a backbone whose broker cannot be reached (a
    # loopback port nobody listens on); the real PostgreSQL stores are up.
    backbone = C5Rig(
        None, f"ocor-backbone-unreachable-{uuid.uuid4().hex[:12]}", dsn=live_dsn(), schema=schema_name("ocor_c5_0040"),
        bootstrap_servers=unreachable_bootstrap(), journal_timeout_s=3.0,
    )

    try:
        with pytest.raises(KafkaBackboneError):
            backbone.publish(envelope(aggregate_ref="urn:ocor:mission-object:backbone:7", sequence=1))
    finally:
        backbone.drop()
