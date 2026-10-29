"""OCOR-DEV-0060 BA-07: Kafka behind C5 (replay, dedup, backpressure, DLQ, schema).

BA: ``BA-07`` of ADD v1.3 Part I section 2.6 (row "Kafka/Strimzi -- ``C5``",
required property "Ordering per partizione, retention sufficiente al replay,
DLQ e schema registry"; conformance test "test di replay dalla retention
configurata") and the ``BA-07`` row of LLD v1.1 section 7.1 ("Kafka/Strimzi
replay, dedup, backpressure, DLQ/quarantine e schema compatibility").

Real component: Apache Kafka as shipped by ``confluentinc/cp-kafka`` 7.6.0,
digest-pinned in ``infra/services.lock.json`` (service id ``kafka``), single
KRaft broker. Sealed adapters reused unmodified:
``ocor_runtime.c5.backbone.CanonicalEventBackbone`` (OCOR-DEV-0040, partition
order by ``aggregate_ref``, durable journal-backed dedup and per-aggregate
watermark, schema registry ``REGISTERED_SCHEMAS``, quarantine) and
``ocor_runtime.c5.operations.EventOperationsCoordinator`` (OCOR-DEV-0041,
per-tenant backpressure, immutable DLQ, ``POISON`` quarantine behind an
operator gate, re-validating replay). Every observation of the oracle is
read back from the broker itself (``kafka-get-offsets``, ``kafka-configs``
and a from-beginning consumer), never from in-process state.

Declared limitations accepted by the Product Owner (also in ``BA_CASE``):
the broker is a single node, so no replication, ISR or failover property is
observed; no Strimzi operator is deployed; no external schema registry is
used -- the C5 registry of OCOR-DEV-0041/0040 (``REGISTERED_SCHEMAS``) is the
schema-compatibility authority. The broker is the sealed backbone's own
isolated, self-provisioned container from the same pinned ``kafka`` image
(``CanonicalEventBackbone.provision``), not the shared
``ocor-bootstrap-kafka-1`` instance. The licence/capability inventory part
of the conformance column (``NFR-073``) remains tied to the open ``OI-028``
and is NOT observed or claimed closed here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterator

import pytest
from ocor_runtime.c5.backbone import (
    BOOTSTRAP,
    BackboneError,
    CanonicalEventBackbone,
    CanonicalIngestionEnvelope,
    DeliveredRecord,
    KafkaBackboneError,
)
from ocor_runtime.c5.operations import EventOperationsCoordinator, OperationsError

BA_CASE = {
    "ba_id": "BA-07",
    "component": "Apache Kafka (confluentinc/cp-kafka, single KRaft broker)",
    "component_version": "7.6.0",
    "backend_services": ["kafka"],
    "add_v1_3_part_i_2_6": {
        "required_property": "Ordering per partizione, retention sufficiente al replay, DLQ e schema registry",
        "conformance_test": "test di replay dalla retention configurata",
    },
    "lld_v1_1_7_1_oracle": "Kafka/Strimzi replay, dedup, backpressure, DLQ/quarantine e schema compatibility",
    "requirement_ids": ["FR-071", "FR-072", "FR-074", "NFR-028"],
    "requirement_binding": {
        "FR-071": "Per-aggregate order is preserved on one partition and a replayed or retried idempotency key "
        "is deduplicated against the durable journal, so the topic converges to one record per key.",
        "FR-072": "A restarted consumer replays the whole topic from the configured retention (earliest "
        "offset 0) with the original schema_ref, provenance and a checksum equal to the published one.",
        "FR-074": "A permanent schema failure lands in the immutable DLQ and a repeatedly failing event is "
        "classified POISON and quarantined behind the operator gate, never retried into the topic.",
        "NFR-028": "A tenant at its bounded in-flight quota is refused with BACKPRESSURE_EXCEEDED before "
        "touching the broker while another tenant is still admitted, with no undeclared loss.",
    },
    "positive_tests": [
        "test_ba_07_positive_replay_from_configured_retention_preserves_partition_order_and_dedup",
    ],
    "negative_tests": [
        "test_ba_07_negative_schema_incompatible_event_is_dead_lettered_and_never_published",
        "test_ba_07_negative_poison_event_is_quarantined_behind_the_operator_gate",
        "test_ba_07_negative_backpressure_refuses_a_tenant_at_its_quota",
    ],
    "fault_tests": [
        "test_ba_07_fault_broker_outage_fails_closed_and_retained_journal_rebuilds_dedup",
    ],
    "declared_limitations": [
        "single broker: no replication, ISR or broker failover property is observed",
        "no Strimzi operator: the broker runs as a plain pinned container",
        "no external schema registry: the C5 registry of OCOR-DEV-0041 (REGISTERED_SCHEMAS) is used",
        "the broker is the sealed backbone's isolated self-provisioned container from the pinned kafka image, "
        "not the shared ocor-bootstrap-kafka-1 instance",
        "NFR-073 licence/capability inventory stays open under OI-028 and is not claimed",
    ],
}

SCHEMA = "urn:ocor:schema:canonical-ingestion-envelope:1"
UNREGISTERED_SCHEMA = "urn:ocor:schema:canonical-ingestion-envelope:999"
CONTEXT = "urn:sha256:" + "7" * 64
MARKING = "urn:sha256:" + "8" * 64
RETENTION_MS = "3600000"


# --------------------------------------------------------------------------- #
# Broker read-back helpers (server-side observations, never in-process state)
# --------------------------------------------------------------------------- #


def _docker(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], text=True, capture_output=True, timeout=timeout, check=False)


def _broker(container: str, *args: str, timeout: int = 60) -> str:
    result = _docker("exec", container, *args, timeout=timeout)
    if result.returncode:
        pytest.fail(f"real Kafka broker command failed ({result.returncode}): {args[0]}: {result.stderr.strip()}")
    return result.stdout


def _offsets(container: str, topic: str, time_spec: str) -> dict[int, int]:
    output = _broker(
        container, "kafka-get-offsets", "--bootstrap-server", BOOTSTRAP, "--topic", topic, "--time", time_spec
    )
    offsets: dict[int, int] = {}
    for line in output.splitlines():
        parts = line.split(":")
        if len(parts) == 3 and parts[0] == topic:
            offsets[int(parts[1])] = int(parts[2])
    assert offsets, f"broker reports no partitions for {topic!r}"
    return offsets


def _record_count(container: str, topic: str) -> int:
    latest = _offsets(container, topic, "-1")
    earliest = _offsets(container, topic, "-2")
    return sum(latest[partition] - earliest[partition] for partition in latest)


def _topic_config(container: str, topic: str) -> dict[str, str]:
    output = _broker(
        container, "kafka-configs", "--bootstrap-server", BOOTSTRAP,
        "--entity-type", "topics", "--entity-name", topic, "--describe",
    )
    config: dict[str, str] = {}
    for line in output.splitlines():
        token = line.strip().split(" ", 1)[0]
        if "=" in token:
            key, _, value = token.partition("=")
            config[key] = value
    return config


def _topics(container: str) -> set[str]:
    return set(_broker(container, "kafka-topics", "--bootstrap-server", BOOTSTRAP, "--list").split())


def _wait_broker_ready(container: str, *, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        result = _docker("exec", container, "kafka-broker-api-versions", "--bootstrap-server", BOOTSTRAP, timeout=30)
        if result.returncode == 0:
            return
        last = result.stderr.strip()[-300:]
        time.sleep(1)
    pytest.fail(f"real Kafka broker did not become ready again within {timeout:.0f}s: {last}")


def _envelope(
    *,
    aggregate_ref: str,
    sequence: int,
    event_id: str | None = None,
    schema_ref: str = SCHEMA,
) -> CanonicalIngestionEnvelope:
    event_id = event_id or f"urn:ocor:event:{uuid.uuid4()}"
    return CanonicalIngestionEnvelope(
        event_id=event_id,
        event_type="MissionEffectRecorded",
        event_version="1.0.0",
        schema_ref=schema_ref,
        producer_principal="urn:ocor:principal:c6-engine",
        source_ref="urn:ocor:source:ba-07-campaign",
        aggregate_ref=aggregate_ref,
        correlation_id=str(uuid.uuid4()),
        causation_id=str(uuid.uuid4()),
        classification_marking_ref=MARKING,
        governed_context_digest=CONTEXT,
        idempotency_key=event_id,
        sequence=sequence,
        payload={"status": "ASSESSED", "sequence": sequence},
    )


def _checksum(envelopes: list[CanonicalIngestionEnvelope]) -> str:
    canonical = sorted(json.dumps(item.to_mapping(), sort_keys=True, separators=(",", ":")) for item in envelopes)
    return hashlib.sha256("\n".join(canonical).encode()).hexdigest()


class _HeldBackbone(CanonicalEventBackbone):
    """The sealed backbone with a hold point before one named publish, so a
    publish is deterministically in flight while admission is attempted. The
    held publish itself still goes to the real broker once released."""

    def __init__(self, topic: str, *, container: str, held_event_id: str) -> None:
        super().__init__(topic, container=container)
        self._held_event_id = held_event_id
        self.entered = threading.Event()
        self.release = threading.Event()

    def publish(self, envelope: CanonicalIngestionEnvelope) -> None:
        if envelope.event_id == self._held_event_id:
            self.entered.set()
            if not self.release.wait(60):
                raise KafkaBackboneError("held publish was never released")
        super().publish(envelope)


# --------------------------------------------------------------------------- #
# Fixtures: one real isolated broker per module, one disposable topic per test
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def kafka_broker() -> Iterator[str]:
    seed_topic = f"ocor-ba07-seed-{uuid.uuid4().hex[:12]}"
    try:
        seed, container, volume = CanonicalEventBackbone.provision(seed_topic)
    except KafkaBackboneError as error:
        pytest.fail(f"a real, pinned Kafka broker is mandatory qualifying evidence for BA-07: {error}")
    try:
        yield container
    finally:
        # destroy() verifies ownership and raises if any container or volume remains.
        seed.destroy(volume)


@pytest.fixture
def make_topic(kafka_broker: str) -> Iterator[Callable[..., CanonicalEventBackbone]]:
    created: list[str] = []

    def make(held_event_id: str | None = None) -> CanonicalEventBackbone:
        topic = f"ocor-ba07-{uuid.uuid4().hex[:12]}"
        backbone: CanonicalEventBackbone
        if held_event_id is None:
            backbone = CanonicalEventBackbone(topic, container=kafka_broker)
        else:
            backbone = _HeldBackbone(topic, container=kafka_broker, held_event_id=held_event_id)
        _wait_broker_ready(kafka_broker)
        backbone.initialize()
        created.append(topic)
        _broker(
            kafka_broker, "kafka-configs", "--bootstrap-server", BOOTSTRAP, "--entity-type", "topics",
            "--entity-name", topic, "--alter", "--add-config", f"retention.ms={RETENTION_MS}",
        )
        return backbone

    yield make
    _wait_broker_ready(kafka_broker)
    for topic in created:
        _broker(kafka_broker, "kafka-topics", "--bootstrap-server", BOOTSTRAP, "--delete", "--topic", topic)
    deadline = time.monotonic() + 30
    while set(created) & _topics(kafka_broker) and time.monotonic() < deadline:
        time.sleep(0.5)
    assert not set(created) & _topics(kafka_broker), "disposable BA-07 topics were left behind"


# --------------------------------------------------------------------------- #
# BA-07 cases
# --------------------------------------------------------------------------- #


def test_ba_07_positive_replay_from_configured_retention_preserves_partition_order_and_dedup(
    kafka_broker: str, make_topic: Callable[..., CanonicalEventBackbone]
) -> None:
    producer = make_topic()
    topic = producer._topic  # noqa: SLF001 -- the topic name the sealed backbone created
    assert _topic_config(kafka_broker, topic).get("retention.ms") == RETENTION_MS

    aggregates = [f"urn:ocor:mission-object:ba07:{uuid.uuid4().hex[:8]}:{index}" for index in range(3)]
    sent: list[CanonicalIngestionEnvelope] = []
    for sequence in (1, 2, 3):
        for aggregate in aggregates:  # interleaved across aggregates
            envelope = _envelope(aggregate_ref=aggregate, sequence=sequence)
            producer.publish(envelope)
            sent.append(envelope)

    # Retention covers the replay window: nothing has been deleted from the head.
    assert set(_offsets(kafka_broker, topic, "-2").values()) == {0}
    assert _record_count(kafka_broker, topic) == len(sent)

    # A restarted instance replays from the retained journal, not from memory.
    replayer = CanonicalEventBackbone(topic, container=kafka_broker)
    replayed: tuple[DeliveredRecord, ...] = replayer.consume(len(sent))
    assert _checksum([record.envelope for record in replayed]) == _checksum(sent)
    by_id = {item.event_id: item for item in sent}
    for record in replayed:
        original = by_id[record.envelope.event_id]
        assert record.envelope.schema_ref == original.schema_ref == SCHEMA
        assert record.envelope.source_ref == original.source_ref
        assert record.envelope.correlation_id == original.correlation_id
        assert record.envelope.causation_id == original.causation_id
        assert record.envelope.classification_marking_ref == original.classification_marking_ref
    for aggregate in aggregates:
        records = sorted(
            (record for record in replayed if record.envelope.aggregate_ref == aggregate),
            key=lambda record: record.offset,
        )
        assert len({record.partition for record in records}) == 1, "an aggregate was split across partitions"
        assert [record.envelope.sequence for record in records] == [1, 2, 3]

    # Dedup on replay: re-publishing every retained key through the restarted
    # instance converges -- the broker still holds exactly one record per key.
    for envelope in sent:
        replayer.publish(envelope)
    assert _record_count(kafka_broker, topic) == len(sent)
    assert replayer.quarantine == ()

    # The rebuilt watermark still admits the next in-order effect.
    replayer.publish(_envelope(aggregate_ref=aggregates[0], sequence=4))
    assert _record_count(kafka_broker, topic) == len(sent) + 1


def test_ba_07_negative_schema_incompatible_event_is_dead_lettered_and_never_published(
    kafka_broker: str, make_topic: Callable[..., CanonicalEventBackbone]
) -> None:
    backbone = make_topic()
    topic = backbone._topic  # noqa: SLF001
    coordinator = EventOperationsCoordinator(backbone, max_in_flight_per_tenant=4)
    aggregate = f"urn:ocor:mission-object:ba07-schema:{uuid.uuid4().hex[:8]}"

    # Positive control: a registered schema is admitted and lands on the broker.
    coordinator.publish_with_backpressure(_envelope(aggregate_ref=aggregate, sequence=1), tenant="tenant-a")
    assert _record_count(kafka_broker, topic) == 1
    assert coordinator.dead_letters == ()

    incompatible = _envelope(aggregate_ref=aggregate, sequence=2, schema_ref=UNREGISTERED_SCHEMA)
    with pytest.raises(BackboneError) as excinfo:
        coordinator.publish_with_backpressure(incompatible, tenant="tenant-a")
    assert excinfo.value.reason_code == "UNKNOWN_SCHEMA"

    assert _record_count(kafka_broker, topic) == 1, "an incompatible schema reached the broker"
    assert len(coordinator.dead_letters) == 1
    letter = coordinator.dead_letters[0]
    assert (letter.event_id, letter.reason_code, letter.failure_class) == (
        incompatible.event_id, "UNKNOWN_SCHEMA", "PERMANENT",
    )
    assert [item.reason_code for item in backbone.quarantine] == ["UNKNOWN_SCHEMA"]

    # Replaying the dead letter re-runs the same compatibility check.
    with pytest.raises(BackboneError) as replay_error:
        coordinator.replay(letter, window_reason="ba-07-replay-after-fix-window")
    assert replay_error.value.reason_code == "UNKNOWN_SCHEMA"
    assert _record_count(kafka_broker, topic) == 1


def test_ba_07_negative_poison_event_is_quarantined_behind_the_operator_gate(
    kafka_broker: str, make_topic: Callable[..., CanonicalEventBackbone]
) -> None:
    backbone = make_topic()
    topic = backbone._topic  # noqa: SLF001
    coordinator = EventOperationsCoordinator(backbone, max_in_flight_per_tenant=4)
    aggregate = f"urn:ocor:mission-object:ba07-poison:{uuid.uuid4().hex[:8]}"

    # Positive control: two in-order effects are published.
    coordinator.publish_with_backpressure(_envelope(aggregate_ref=aggregate, sequence=1), tenant="tenant-a")
    coordinator.publish_with_backpressure(_envelope(aggregate_ref=aggregate, sequence=2), tenant="tenant-a")
    assert _record_count(kafka_broker, topic) == 2

    # A stale effect keeps failing: each retry is dead-lettered, the third is POISON.
    poison = _envelope(aggregate_ref=aggregate, sequence=1, event_id=f"urn:ocor:event:poison-{uuid.uuid4()}")
    for _ in range(3):
        with pytest.raises(BackboneError) as excinfo:
            coordinator.publish_with_backpressure(poison, tenant="tenant-a")
        assert excinfo.value.reason_code == "OUT_OF_ORDER"
    assert [letter.failure_class for letter in coordinator.dead_letters] == ["PERMANENT", "PERMANENT", "POISON"]
    assert coordinator.is_poisoned(poison.event_id)
    assert [item.reason_code for item in backbone.quarantine] == ["OUT_OF_ORDER"] * 3

    letter = coordinator.dead_letters[-1]
    with pytest.raises(OperationsError) as gate:
        coordinator.replay(letter, window_reason="ba-07-unreleased-replay")
    assert gate.value.reason_code == "OPERATOR_GATE_CLOSED"

    # Even after explicit operator release the replay is re-validated, not trusted.
    coordinator.release_for_operator_replay(poison.event_id)
    with pytest.raises(BackboneError) as replayed:
        coordinator.replay(letter, window_reason="ba-07-operator-released-replay")
    assert replayed.value.reason_code == "OUT_OF_ORDER"
    assert _record_count(kafka_broker, topic) == 2, "a poison event reached the broker"


def test_ba_07_negative_backpressure_refuses_a_tenant_at_its_quota(
    kafka_broker: str, make_topic: Callable[..., CanonicalEventBackbone]
) -> None:
    held = _envelope(aggregate_ref=f"urn:ocor:mission-object:ba07-bp:{uuid.uuid4().hex[:8]}", sequence=1)
    backbone = make_topic(held_event_id=held.event_id)
    assert isinstance(backbone, _HeldBackbone)
    topic = backbone._topic  # noqa: SLF001
    coordinator = EventOperationsCoordinator(backbone, max_in_flight_per_tenant=1)
    errors: list[BaseException] = []

    def in_flight() -> None:
        try:
            coordinator.publish_with_backpressure(held, tenant="tenant-a")
        except BaseException as error:  # noqa: BLE001 -- surfaced to the test thread below
            errors.append(error)

    worker = threading.Thread(target=in_flight, daemon=True)
    worker.start()
    try:
        assert backbone.entered.wait(30), "the in-flight publish never started"
        refused = _envelope(aggregate_ref=f"urn:ocor:mission-object:ba07-bp:{uuid.uuid4().hex[:8]}", sequence=1)
        with pytest.raises(OperationsError) as excinfo:
            coordinator.publish_with_backpressure(refused, tenant="tenant-a")
        assert excinfo.value.reason_code == "BACKPRESSURE_EXCEEDED"
        # Positive control: another tenant is still admitted while tenant-a is at quota.
        admitted = _envelope(aggregate_ref=f"urn:ocor:mission-object:ba07-bp:{uuid.uuid4().hex[:8]}", sequence=1)
        coordinator.publish_with_backpressure(admitted, tenant="tenant-b")
        assert _record_count(kafka_broker, topic) == 1
    finally:
        backbone.release.set()
        worker.join(60)
    assert not worker.is_alive() and errors == []

    # Only the admitted and the released in-flight records exist; the refused one
    # never touched the broker and was not dead-lettered as if it had failed.
    delivered = {record.envelope.event_id for record in backbone.consume(2)}
    assert delivered == {held.event_id, admitted.event_id}
    assert _record_count(kafka_broker, topic) == 2
    assert coordinator.dead_letters == ()

    # Admission is restored once the in-flight publish completed.
    coordinator.publish_with_backpressure(refused, tenant="tenant-a")
    assert _record_count(kafka_broker, topic) == 3


def test_ba_07_fault_broker_outage_fails_closed_and_retained_journal_rebuilds_dedup(
    kafka_broker: str, make_topic: Callable[..., CanonicalEventBackbone]
) -> None:
    backbone = make_topic()
    topic = backbone._topic  # noqa: SLF001
    aggregate = f"urn:ocor:mission-object:ba07-fault:{uuid.uuid4().hex[:8]}"
    first = _envelope(aggregate_ref=aggregate, sequence=1)
    second = _envelope(aggregate_ref=aggregate, sequence=2)
    backbone.publish(first)
    backbone.publish(second)
    assert _record_count(kafka_broker, topic) == 2

    third = _envelope(aggregate_ref=aggregate, sequence=3)
    stopped = _docker("stop", "--time", "10", kafka_broker, timeout=60)
    assert stopped.returncode == 0, stopped.stderr
    try:
        # Broker down: the publish fails closed, it is never reported as accepted
        # and it is not mistaken for a governed rejection.
        with pytest.raises(KafkaBackboneError):
            backbone.publish(third)
        assert backbone.quarantine == ()
    finally:
        started = _docker("start", kafka_broker, timeout=60)
        assert started.returncode == 0, started.stderr
        _wait_broker_ready(kafka_broker)

    # The retained journal survived the outage on the broker.
    assert set(_offsets(kafka_broker, topic, "-2").values()) == {0}
    assert _record_count(kafka_broker, topic) == 2
    assert [record.envelope.event_id for record in backbone.consume(2)] == [first.event_id, second.event_id]

    # After the unknown-outcome write, dedup and watermark are rebuilt from the
    # journal: a retried key is a no-op and a stale effect is still refused.
    backbone.publish(second)
    assert _record_count(kafka_broker, topic) == 2
    stale = _envelope(aggregate_ref=aggregate, sequence=1)
    with pytest.raises(BackboneError) as excinfo:
        backbone.publish(stale)
    assert excinfo.value.reason_code == "OUT_OF_ORDER"
    assert _record_count(kafka_broker, topic) == 2

    backbone.publish(third)
    assert _record_count(kafka_broker, topic) == 3
