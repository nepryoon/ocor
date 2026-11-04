"""OCOR-DEV-REM-0026: C5 durable, atomic dedup and watermark; atomic tenant quota.

LLD v1.1 section 6 requires for C4/C5 "ordering per aggregate/partition;
watermark monotono; deduplica durable", and section 2.5 requires per-tenant
backpressure quotas and a replay that never publishes a canonical effect twice.
The INFO-C audit (2026-10-12) reproduced on a real broker:

- R1: after a restart (a new backbone on the same broker and topic) a replayed
  ``idempotency_key`` is published a second time;
- R2: after a restart a stale sequence for an aggregate is accepted;
- K1: two concurrent publishes of the same envelope write two records;
- K2: concurrent sequences 5 and 4 for one aggregate are both accepted and the
  recorded watermark regresses to 4;
- Q1: with quota 1 two concurrent publishes are both admitted and the in-flight
  counter ends at -1.

Every test drives a real, self-provisioned Kafka broker -- no mock of the
backbone boundary. Exact topic contents are read through Kafka's own offsets.
Concurrency cases use real threads; the worst interleaving is forced by
observation instruments (a held Kafka write, a held counter read) whenever the
code under test permits it, so the outcome never depends on timing luck. A
held step waits for the competing thread for a bounded time only: code that
serializes the critical section makes that wait expire, code that does not
lets both threads through deterministically.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from c5_backbone_fixture import TENANT, C5Rig, Draft, draft, live_dsn, schema_name
from c5_kafka_qualification import BOOTSTRAP, KafkaBrokerError, QualificationKafkaBroker
from ocor_runtime.c5.adapters.kafka import KafkaJournal
from ocor_runtime.c5.backbone import BackboneError, CanonicalIngestionEnvelope
from ocor_runtime.c5.backbone import KafkaJournalError as KafkaBackboneError
from ocor_runtime.c5.operations import EventOperationsCoordinator, OperationsError, ResourceClass

CONTEXT_A = "urn:sha256:" + "a" * 64
CONTEXT_B = "urn:sha256:" + "b" * 64
SCHEMA = "urn:ocor:schema:canonical-ingestion-envelope:1"
HOLD_SECONDS = 3.0
PRODUCER = "kafka-console-producer"


def envelope(
    *,
    aggregate_ref: str,
    sequence: int = 1,
    idempotency_key: str | None = None,
    event_id: str | None = None,
    context: str = CONTEXT_A,
    schema_ref: str = SCHEMA,
) -> Draft:
    return draft(
        aggregate_ref=aggregate_ref,
        sequence=sequence,
        event_id=event_id,
        idempotency_key=idempotency_key,
        schema_ref=schema_ref,
        context=context,
        causation_id=str(uuid.uuid4()),
        payload={"remediation": "rem-0026"},
    )


def topic_record_count(backbone: C5Rig) -> int:
    """Exact number of records on the real topic (sum of partition end offsets)."""
    offsets = backbone.broker.end_offsets(backbone.topic)  # read-only observation of the real broker
    assert offsets, "no partition offsets reported"
    return sum(offsets.values())


def delivered(backbone: C5Rig) -> list[CanonicalIngestionEnvelope]:
    count = topic_record_count(backbone)
    values = backbone.topic_envelopes() if count else []
    return [CanonicalIngestionEnvelope.from_mapping(value) for value in values]  # partition, offset order


def concurrently(*calls: Callable[[], None]) -> list[str | None]:
    """Run each call on its own real thread, started together; return reason codes (None = success)."""
    barrier = threading.Barrier(len(calls))
    outcomes: list[str | None] = [None] * len(calls)

    def run(index: int, call: Callable[[], None]) -> None:
        barrier.wait(timeout=30)
        try:
            call()
        except Exception as error:  # noqa: BLE001 -- the outcome itself is the asserted value
            outcomes[index] = getattr(error, "reason_code", type(error).__name__)

    threads = [threading.Thread(target=run, args=(index, call)) for index, call in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=300)
        assert not thread.is_alive(), "a publishing thread did not finish"
    return outcomes


class ModuleTopic(str):
    """A test topic of the module broker with the PostgreSQL schema of its C5 stores."""

    schema: str


def journal_with(instrument: Any) -> type[KafkaJournal]:
    """The real in-process journal with ``instrument.on_append`` around every real write."""

    class InstrumentedJournal(KafkaJournal):
        def append(self, **kwargs: Any) -> tuple[int, int]:
            return instrument.on_append(lambda: KafkaJournal.append(self, **kwargs))

    return InstrumentedJournal


class HeldWriteBackbone(C5Rig):
    """Observation instrument over the real backbone: while armed, the first
    real Kafka write is held until a second write starts (possible only when
    check and write are not serialized) or ``HOLD_SECONDS`` elapse. It records
    how many publishes had arrived when the held write was released."""

    def __init__(self, topic: ModuleTopic, *, container: QualificationKafkaBroker) -> None:
        self.armed = False
        self.arrivals = 0
        self.writes_started = 0
        self.arrivals_at_release: list[int] = []
        self.first_write_entered = threading.Event()
        self._condition = threading.Condition()
        super().__init__(container, topic, dsn=live_dsn(), schema=topic.schema, journal_type=journal_with(self))

    def publish(self, value: Any) -> Any:
        with self._condition:
            self.arrivals += 1
            self._condition.notify_all()
        return super().publish(value)

    def on_append(self, write: Callable[[], tuple[int, int]]) -> tuple[int, int]:
        if self.armed:
            with self._condition:
                self.writes_started += 1
                self._condition.notify_all()
                if self.writes_started == 1:
                    self.first_write_entered.set()
                    self._condition.wait_for(lambda: self.writes_started >= 2, timeout=HOLD_SECONDS)
                    self.arrivals_at_release.append(self.arrivals)
        return write()


class FaultyWriteBackbone(C5Rig):
    """Fault-injection instrument over the real backbone: the next real Kafka
    write fails either before reaching the broker or after the broker has
    durably accepted it (a lost acknowledgement)."""

    def __init__(self, topic: ModuleTopic, *, container: QualificationKafkaBroker, **kwargs: Any) -> None:
        self.fail_next: str | None = None
        super().__init__(container, topic, dsn=live_dsn(), schema=topic.schema, journal_type=journal_with(self),
                         **kwargs)

    def on_append(self, write: Callable[[], tuple[int, int]]) -> tuple[int, int]:
        if self.fail_next is not None:
            mode, self.fail_next = self.fail_next, None
            if mode == "before":
                raise KafkaBackboneError("injected: write never reached the broker")
            write()
            raise KafkaBackboneError("injected: acknowledgement lost after a durable write")
        return write()


class HeldReadCounter(dict[Any, int]):
    """Observation instrument for a private counter: the first
    read takes its value and is then held until a second read has also taken
    its value (possible only when read and write are not serialized) or
    ``HOLD_SECONDS`` elapse, so both readers may observe the same value.
    Records every value written."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0
        self.max_written = 0
        self.written: list[int] = []
        self._condition = threading.Condition()

    def get(self, key: Any, default: Any = None) -> Any:
        value = super().get(key, default)
        with self._condition:
            self.reads += 1
            self._condition.notify_all()
            if self.reads == 1:
                self._condition.wait_for(lambda: self.reads >= 2, timeout=HOLD_SECONDS)
        return value

    def __setitem__(self, key: Any, value: int) -> None:
        super().__setitem__(key, value)
        self.written.append(value)
        self.max_written = max(self.max_written, value)


class HeldPublishBackbone(FaultyWriteBackbone):
    """Observation instrument: every admitted publish is held in flight until
    ``expected`` callers have been resolved (admitted to the journal write or
    refused by the admission control), so a refused caller always decided while the
    admitted ones were still in flight. Inherits the write-fault injection."""

    def __init__(self, topic: ModuleTopic, *, container: QualificationKafkaBroker, expected: int, quota: int) -> None:
        self.expected = expected
        self.resolved = 0
        self._held = threading.Condition()
        super().__init__(topic, container=container, quotas={ResourceClass.BATCH: quota})

    def resolve(self) -> None:
        with self._held:
            self.resolved += 1
            self._held.notify_all()

    def on_append(self, write: Callable[[], tuple[int, int]]) -> tuple[int, int]:
        self.resolve()
        with self._held:
            self._held.wait_for(lambda: self.resolved >= self.expected, timeout=30)
        return super().on_append(write)


class HeldAttemptLock:
    """Observation instrument on the real PostgreSQL: the attempt counter of one event's dead
    letters is read and written under a transaction advisory lock of the C5 store. The
    instrument holds that lock until two publishes wait on it (possible only when both reached
    the critical section together) or ``HOLD_SECONDS`` elapse, then releases it."""

    def __init__(self, backbone: C5Rig, event_id: str) -> None:
        self._dsn = backbone.dsn
        self._key = f"{backbone.schema}/dl/{event_id}"
        self.waiters_at_release = -1
        self._thread: threading.Thread | None = None

    def __enter__(self) -> HeldAttemptLock:
        ready = threading.Event()

        def hold() -> None:
            with psycopg.connect(self._dsn, autocommit=True) as connection:
                connection.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (self._key,))
                ready.set()
                deadline = time.monotonic() + HOLD_SECONDS
                waiters = 0
                while time.monotonic() < deadline:
                    row = connection.execute(
                        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
                    ).fetchone()
                    waiters = int(row[0]) if row else 0
                    if waiters >= 2:
                        break
                    time.sleep(0.05)
                self.waiters_at_release = waiters
                connection.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (self._key,))

        self._thread = threading.Thread(target=hold)
        self._thread.start()
        assert ready.wait(timeout=30), "the attempt lock was never taken"
        return self

    def __exit__(self, *exc: object) -> None:
        assert self._thread is not None
        self._thread.join(timeout=60)


@pytest.fixture(scope="module")
def broker() -> Iterator[QualificationKafkaBroker]:
    """One real, isolated, self-provisioned Kafka broker for the module; each test uses its own topic."""
    try:
        value, container, volume = QualificationKafkaBroker.provision(f"ocor-rem0026-bootstrap-{uuid.uuid4().hex[:12]}")
    except KafkaBrokerError as error:
        pytest.fail(f"a real, live, self-provisioned Kafka broker is mandatory qualifying evidence: {error}")
    try:
        yield value
    finally:
        value.destroy(volume)


@pytest.fixture
def topic(broker: QualificationKafkaBroker) -> Iterator[ModuleTopic]:
    name = ModuleTopic(broker.create_topic(f"ocor-rem0026-{uuid.uuid4().hex[:12]}"))
    name.schema = schema_name("ocor_c5_rem0026")
    try:
        yield name
    finally:
        with psycopg.connect(live_dsn(), autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA IF EXISTS "{name.schema}" CASCADE')
            connection.execute(f'DROP SCHEMA IF EXISTS "{name.schema}_audit" CASCADE')


def restarted(topic: ModuleTopic, broker: QualificationKafkaBroker) -> C5Rig:
    """A fresh backbone instance on the same broker and topic: process state is gone, the journal is not."""
    return C5Rig(broker, topic, dsn=live_dsn(), schema=topic.schema)


def assert_out_of_order(backbone: C5Rig, late: Draft) -> None:
    with pytest.raises(BackboneError) as excinfo:
        backbone.publish(late)
    assert excinfo.value.reason_code == "OUT_OF_ORDER"
    assert backbone.quarantine[-1].reason_code == "OUT_OF_ORDER"
    assert backbone.quarantine[-1].raw["event_id"] == late.event_id


# R1 -- durable dedup across a restart


def test_r1_replayed_key_after_restart_is_a_safe_no_op(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    first = restarted(topic, broker)
    original = envelope(aggregate_ref="urn:ocor:mission-object:rem0026:r1", idempotency_key="r1-key")
    first.publish(original)

    second = restarted(topic, broker)
    second.publish(original)

    assert second.quarantine == ()
    assert [e.event_id for e in delivered(second)] == [original.event_id]


def test_r1_positive_first_publish_of_a_new_key_after_restart_is_written(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    first = restarted(topic, broker)
    a = envelope(aggregate_ref="urn:ocor:mission-object:rem0026:r1p", sequence=1, idempotency_key="r1p-a")
    first.publish(a)

    second = restarted(topic, broker)
    b = envelope(aggregate_ref="urn:ocor:mission-object:rem0026:r1p", sequence=2, idempotency_key="r1p-b")
    second.publish(b)
    second.publish(b)  # the recovered instance also deduplicates its own writes

    assert second.quarantine == ()
    assert [e.event_id for e in delivered(second)] == [a.event_id, b.event_id]


# R2 -- monotone per-aggregate watermark across a restart


def test_r2_stale_or_equal_sequence_after_restart_is_out_of_order(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    aggregate = "urn:ocor:mission-object:rem0026:r2"
    first = restarted(topic, broker)
    first.publish(envelope(aggregate_ref=aggregate, sequence=3))
    first.publish(envelope(aggregate_ref=aggregate, sequence=5))

    second = restarted(topic, broker)
    assert_out_of_order(second, envelope(aggregate_ref=aggregate, sequence=4))
    assert_out_of_order(second, envelope(aggregate_ref=aggregate, sequence=5))

    assert len(second.quarantine) == 2
    assert [e.aggregate["expected_revision"] for e in delivered(second)] == [3, 5]


def test_r2_positive_advancing_sequence_after_restart_is_accepted_and_advances(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    aggregate = "urn:ocor:mission-object:rem0026:r2p"
    first = restarted(topic, broker)
    first.publish(envelope(aggregate_ref=aggregate, sequence=5))

    second = restarted(topic, broker)
    second.publish(envelope(aggregate_ref=aggregate, sequence=6))
    assert_out_of_order(second, envelope(aggregate_ref=aggregate, sequence=6))

    third = restarted(topic, broker)
    assert_out_of_order(third, envelope(aggregate_ref=aggregate, sequence=6))
    third.publish(envelope(aggregate_ref=aggregate, sequence=9))
    assert [e.aggregate["expected_revision"] for e in delivered(third)] == [5, 6, 9]


def test_restart_recovery_keeps_the_isolation_scoping_of_rem_0025(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    shared = "urn:ocor:mission-object:rem0026:shared"
    first = restarted(topic, broker)
    a = envelope(context=CONTEXT_A, aggregate_ref=shared, sequence=5, idempotency_key="shared-key")
    first.publish(a)
    first.publish(envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0026:other", sequence=10))

    second = restarted(topic, broker)
    b = envelope(context=CONTEXT_B, aggregate_ref=shared, sequence=1, idempotency_key="shared-key")
    second.publish(b)  # same key and aggregate, another context: neither dropped nor out of order
    second.publish(a)  # same-context replay: still a no-op
    assert_out_of_order(second, envelope(context=CONTEXT_A, aggregate_ref=shared, sequence=3))
    assert_out_of_order(second, envelope(context=CONTEXT_A, aggregate_ref="urn:ocor:mission-object:rem0026:other", sequence=4))

    assert len(second.quarantine) == 2
    assert sorted(e.event_id for e in delivered(second) if e.aggregate["aggregate_id"] == shared) == sorted(
        [a.event_id, b.event_id]
    )
    assert topic_record_count(second) == 3


def test_an_unreadable_journal_fails_closed_and_publishes_nothing(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    first = restarted(topic, broker)
    first.publish(envelope(aggregate_ref="urn:ocor:mission-object:rem0026:j1", sequence=1))
    # a record that is not a canonical envelope lands on the journal out of band
    broker._exec(  # noqa: SLF001 -- raw write to the real topic through the qualification tool, bypassing the backbone
        PRODUCER, "--bootstrap-server", BOOTSTRAP, "--topic", topic,
        "--property", "parse.key=true", "--property", "key.separator=|", input_text="foreign|not-a-canonical-envelope\n",
    )

    second = restarted(topic, broker)
    for _ in range(2):  # an unrecoverable journal stays fail-closed: no fallback to empty state
        with pytest.raises(BackboneError, match="JOURNAL_UNREADABLE"):
            second.publish(envelope(aggregate_ref="urn:ocor:mission-object:rem0026:j2", sequence=1))

    assert second.quarantine == ()
    assert topic_record_count(second) == 2


def test_a_missing_journal_fails_closed(broker: QualificationKafkaBroker) -> None:
    absent = C5Rig(broker, f"ocor-rem0026-absent-{uuid.uuid4().hex[:12]}", dsn=live_dsn(),
                   schema=schema_name("ocor_c5_rem0026"))

    try:
        with pytest.raises(KafkaBackboneError):
            absent.publish(envelope(aggregate_ref="urn:ocor:mission-object:rem0026:absent", sequence=1))

        assert absent.quarantine == ()
    finally:
        absent.drop()


class ForeignOffsetsJournal(KafkaJournal):
    """Local failure-handling instrument (not qualifying for the broker itself):
    the real offsets query runs, but its answer is replaced by one that names
    no partition of this topic -- e.g. another topic's offsets."""

    def watermarks(self) -> dict[int, tuple[int, int]]:
        return {partition + 1000: marks for partition, marks in super().watermarks().items()}


def test_an_offsets_answer_naming_no_partition_of_the_topic_fails_closed(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    backbone = C5Rig(broker, topic, dsn=live_dsn(), schema=topic.schema, journal_type=ForeignOffsetsJournal)

    with pytest.raises(KafkaBackboneError):
        backbone.publish(envelope(aggregate_ref="urn:ocor:mission-object:rem0026:foreign", sequence=1))

    assert backbone.quarantine == ()
    assert topic_record_count(backbone) == 0


# Write failures: an unknown write outcome never yields a duplicate


def test_a_lost_acknowledgement_is_recovered_without_a_duplicate(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    aggregate = "urn:ocor:mission-object:rem0026:ack"
    backbone = FaultyWriteBackbone(topic, container=broker)
    backbone.publish(envelope(aggregate_ref=aggregate, sequence=1))
    second = envelope(aggregate_ref=aggregate, sequence=2, idempotency_key="ack-key")
    backbone.fail_next = "after"

    with pytest.raises(BackboneError, match="RETRY_BUDGET_EXHAUSTED"):
        backbone.publish(second)
    backbone.publish(second)  # producer retry of the same envelope

    assert_out_of_order(backbone, envelope(aggregate_ref=aggregate, sequence=2))
    assert [e.aggregate["expected_revision"] for e in delivered(backbone)] == [1, 2]


def test_a_write_that_never_reached_the_broker_is_published_once_on_retry(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    aggregate = "urn:ocor:mission-object:rem0026:noack"
    backbone = FaultyWriteBackbone(topic, container=broker)
    backbone.publish(envelope(aggregate_ref=aggregate, sequence=1))
    second = envelope(aggregate_ref=aggregate, sequence=2, idempotency_key="noack-key")
    backbone.fail_next = "before"

    with pytest.raises(BackboneError, match="RETRY_BUDGET_EXHAUSTED"):
        backbone.publish(second)
    backbone.publish(second)
    backbone.publish(second)

    assert backbone.quarantine == ()
    assert [e.event_id for e in delivered(backbone)][-1] == second.event_id
    assert topic_record_count(backbone) == 2


# K1/K2 -- dedup and watermark under concurrent publish


def test_k1_concurrent_publish_of_the_same_envelope_writes_exactly_one_record(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    backbone = HeldWriteBackbone(topic, container=broker)
    same = envelope(aggregate_ref="urn:ocor:mission-object:rem0026:k1", idempotency_key="k1-key")
    backbone.armed = True

    outcomes = concurrently(lambda: backbone.publish(same), lambda: backbone.publish(same))

    assert outcomes == [None, None]
    assert backbone.arrivals_at_release == [2], "the second publish must have arrived while the first write was held"
    assert backbone.quarantine == ()
    assert [e.event_id for e in delivered(backbone)] == [same.event_id]


def test_k2_concurrent_sequences_never_regress_the_watermark(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    aggregate = "urn:ocor:mission-object:rem0026:k2"
    backbone = HeldWriteBackbone(topic, container=broker)
    backbone.publish(envelope(aggregate_ref=aggregate, sequence=3))
    five = envelope(aggregate_ref=aggregate, sequence=5)
    four = envelope(aggregate_ref=aggregate, sequence=4)
    backbone.armed = True
    outcomes: dict[int, str | None] = {}

    def attempt(value: Draft) -> None:
        try:
            backbone.publish(value)
            outcomes[value.sequence] = None
        except BackboneError as error:
            outcomes[value.sequence] = error.reason_code

    first = threading.Thread(target=attempt, args=(five,))
    first.start()
    assert backbone.first_write_entered.wait(timeout=60), "sequence 5 never reached its Kafka write"
    second = threading.Thread(target=attempt, args=(four,))
    second.start()
    first.join(timeout=120)
    second.join(timeout=120)
    backbone.armed = False

    assert backbone.arrivals_at_release == [3], "sequence 4 must have arrived while sequence 5 was being written"
    assert outcomes == {5: None, 4: "OUT_OF_ORDER"}
    assert [q.raw["event_id"] for q in backbone.quarantine] == [four.event_id]
    assert [e.aggregate["expected_revision"] for e in delivered(backbone)] == [3, 5]
    # the recorded watermark is 5 in this instance and after a restart
    assert_out_of_order(backbone, envelope(aggregate_ref=aggregate, sequence=5))
    assert_out_of_order(restarted(topic, broker), envelope(aggregate_ref=aggregate, sequence=5))


def test_concurrent_publishes_of_distinct_events_are_all_written(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    backbone = HeldWriteBackbone(topic, container=broker)
    values = [envelope(aggregate_ref=f"urn:ocor:mission-object:rem0026:k3-{n}") for n in range(3)]
    backbone.armed = True

    outcomes = concurrently(*[(lambda v=v: backbone.publish(v)) for v in values])

    assert outcomes == [None, None, None]
    assert backbone.quarantine == ()
    assert sorted(e.event_id for e in delivered(backbone)) == sorted(v.event_id for v in values)


# Q1 -- per-tenant quota under concurrent publish


def coordinator_with_held_counter(
    topic: ModuleTopic, broker: QualificationKafkaBroker, *, quota: int, callers: int
) -> tuple[EventOperationsCoordinator, HeldPublishBackbone, HeldReadCounter]:
    backbone = HeldPublishBackbone(topic, container=broker, expected=callers, quota=quota)
    coordinator = backbone.coordinator()
    counter = HeldReadCounter()
    backbone.backbone._admission._in_flight = counter  # noqa: SLF001 -- observation instrument on the private counter
    return coordinator, backbone, counter


def admit(coordinator: EventOperationsCoordinator, backbone: HeldPublishBackbone, value: Draft) -> None:
    try:
        coordinator.publish_with_backpressure(backbone.sign(value), tenant=TENANT)
    except OperationsError:
        backbone.resolve()
        raise


def test_q1_quota_one_admits_exactly_one_of_two_concurrent_publishes(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    coordinator, backbone, counter = coordinator_with_held_counter(topic, broker, quota=1, callers=2)
    values = [envelope(aggregate_ref=f"urn:ocor:mission-object:rem0026:q1-{n}") for n in range(2)]

    outcomes = concurrently(*[(lambda v=v: admit(coordinator, backbone, v)) for v in values])

    assert sorted(outcomes, key=str) == sorted([None, "BACKPRESSURE_EXCEEDED"], key=str)
    assert counter.max_written <= 1
    assert counter.get((TENANT, ResourceClass.BATCH), 0) == 0
    assert min(counter.written) >= 0
    assert topic_record_count(backbone) == 1


def test_quota_admits_up_to_its_limit_and_refuses_the_next_concurrent_publish(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    coordinator, backbone, counter = coordinator_with_held_counter(topic, broker, quota=2, callers=3)
    values = [envelope(aggregate_ref=f"urn:ocor:mission-object:rem0026:q2-{n}") for n in range(3)]

    outcomes = concurrently(*[(lambda v=v: admit(coordinator, backbone, v)) for v in values])

    assert outcomes.count(None) == 2
    assert outcomes.count("BACKPRESSURE_EXCEEDED") == 1
    assert counter.max_written <= 2
    assert counter.get((TENANT, ResourceClass.BATCH), 0) == 0
    assert topic_record_count(backbone) == 2


def test_the_in_flight_counter_returns_to_zero_after_publish_failures(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    coordinator, backbone, counter = coordinator_with_held_counter(topic, broker, quota=1, callers=2)
    # the payload schema is validated before admission (Register :406), so the failure that a
    # publish suffers while it holds its quota slot is the journal write of the admitted one
    failing = envelope(aggregate_ref="urn:ocor:mission-object:rem0026:qf-1")
    backbone.fail_next = "before"

    outcomes = concurrently(lambda: admit(coordinator, backbone, failing), lambda: admit(coordinator, backbone, failing))
    assert sorted(outcomes, key=str) == sorted(["BACKPRESSURE_EXCEEDED", "RETRY_BUDGET_EXHAUSTED"], key=str)
    assert counter.get((TENANT, ResourceClass.BATCH), 0) == 0

    backbone.expected = 0  # no further hold: sequential publishes from here
    backbone.fail_next = "before"
    with pytest.raises(BackboneError, match="RETRY_BUDGET_EXHAUSTED"):
        coordinator.publish_with_backpressure(
            backbone.sign(envelope(aggregate_ref="urn:ocor:mission-object:rem0026:qf-2")), tenant=TENANT
        )
    assert counter.get((TENANT, ResourceClass.BATCH), 0) == 0

    valid = envelope(aggregate_ref="urn:ocor:mission-object:rem0026:qf-3")
    coordinator.publish_with_backpressure(backbone.sign(valid), tenant=TENANT)  # the quota is not leaked
    assert counter.get((TENANT, ResourceClass.BATCH), 0) == 0
    assert min(counter.written) >= 0
    assert [e.event_id for e in delivered(backbone)] == [valid.event_id]


def test_concurrent_failures_of_one_event_count_every_attempt(topic: ModuleTopic, broker: QualificationKafkaBroker) -> None:
    backbone = C5Rig(broker, topic, dsn=live_dsn(), schema=topic.schema, quotas={ResourceClass.BATCH: 5})
    coordinator = backbone.coordinator()
    unknown = envelope(aggregate_ref="urn:ocor:mission-object:rem0026:qa", schema_ref="urn:ocor:schema:not-registered:1")
    signed = backbone.sign(unknown)

    with HeldAttemptLock(backbone, unknown.event_id):  # observation instrument on the real attempt counter
        outcomes = concurrently(
            lambda: coordinator.publish_with_backpressure(signed, tenant=TENANT),
            lambda: coordinator.publish_with_backpressure(signed, tenant=TENANT),
        )

    assert outcomes == ["UNKNOWN_SCHEMA", "UNKNOWN_SCHEMA"]
    assert sorted(letter.attempts for letter in coordinator.dead_letters) == [1, 2]
    assert topic_record_count(backbone) == 0
