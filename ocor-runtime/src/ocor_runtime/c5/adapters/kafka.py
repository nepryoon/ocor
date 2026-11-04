"""C5 journal on Kafka through the in-process confluent-kafka client.

NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 2 for NCP-U06 (ADD v1.3 :273 and :360): the
backbone talks to Kafka from the process, with the client of point 7, behind the
Publish/Subscribe/Replay/Quarantine port; no ``docker exec`` and no Kafka CLI here. Kafka is
the durable journal, not the world-state master (ADD v1.3 :273): records are keyed by
``ordering_key`` (per-key order, ADD v1.3 :273 "Ordering per ``ordering_key``"), written with
``acks=all`` and the idempotent producer, and carry the producer signature in a header.

The only network peers are the configured brokers: client telemetry push (KIP-714,
``enable.metrics.push``) is disabled, and topics are never auto-created -- a missing journal
topic fails closed. A broker or transport failure is ``KafkaJournalError``, the ``TRANSIENT``
class of LLD v1.1 :160; the caller owns the retry budget. Physical partitions and offsets
stay inside C5: the Subscribe surface exposes only opaque cursors (ADD v1.3 :2575).

Every answer of the client is checked for shape without coercion (PRE-REVIEW-INPUT-ROBUSTNESS
(2026-10-29)): partitions, offsets and timestamps are non-negative integers (never ``bool``),
watermarks are ordered pairs, every partition asked for is answered once; any anomaly is
``KafkaJournalError``. An absent key, value or header value (a tombstone, a null header) stays
absent, never empty bytes: the backbone judges such a record unreadable.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer, TopicPartition

HEADER_NAME = "ocor-c5-"


class KafkaJournalError(RuntimeError):
    """The broker could not confirm or serve a journal operation (``TRANSIENT``)."""


@dataclass(frozen=True, slots=True)
class JournalRecord:
    partition: int
    offset: int
    key: bytes | None
    value: bytes | None
    headers: tuple[tuple[str, bytes | None], ...]
    timestamp_ms: int

    def header(self, name: str) -> bytes | None:
        values = [value for key, value in self.headers if key == name]
        return values[0] if len(values) == 1 else None


def _position(value: object, what: str) -> int:
    """A partition, offset or timestamp of the client: a non-negative ``int``, never ``bool``."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise KafkaJournalError(f"the journal answered a malformed {what}")
    return value


def _optional_bytes(value: object, what: str) -> bytes | None:
    if value is None or isinstance(value, bytes):
        return value
    raise KafkaJournalError(f"journal record {what} is not bytes")


def _headers(value: object) -> tuple[tuple[str, bytes | None], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise KafkaJournalError("journal record headers are malformed")
    result = []
    for item in value:
        if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], str):
            raise KafkaJournalError("journal record header is malformed")
        result.append((item[0], _optional_bytes(item[1], "header value")))
    return tuple(result)


def _timestamp(value: object) -> int:
    """``message.timestamp()`` is ``(type, milliseconds)``."""
    if not isinstance(value, tuple) or len(value) != 2:
        raise KafkaJournalError("the journal answered a malformed record timestamp")
    _position(value[0], "record timestamp type")
    return _position(value[1], "record timestamp")


def _bounds(value: object, what: str) -> dict[int, int]:
    if not isinstance(value, Mapping):
        raise KafkaJournalError(f"journal read {what} positions are malformed")
    return {_position(partition, f"{what} partition"): _position(offset, f"{what} offset")
            for partition, offset in value.items()}


def _common(bootstrap_servers: str, timeout_s: float) -> dict[str, Any]:
    return {
        "bootstrap.servers": bootstrap_servers,
        "client.id": "ocor-c5-backbone",
        "enable.metrics.push": False,
        "socket.timeout.ms": max(1000, int(timeout_s * 1000)),
        "log_level": 3,
    }


class KafkaJournal:
    """The C5 journal of one topic."""

    def __init__(self, bootstrap_servers: str, topic: str, *, timeout_s: float = 10.0) -> None:
        if not isinstance(bootstrap_servers, str) or not bootstrap_servers:
            raise ValueError("bootstrap servers are required")
        if not isinstance(topic, str) or not topic:
            raise ValueError("a journal topic is required")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, int | float) or not 0 < timeout_s <= 300:
            raise ValueError("timeout_s must be in (0, 300]")
        self._servers = bootstrap_servers
        self._topic = topic
        self._timeout = float(timeout_s)
        self._producer: Producer | None = None
        self._topic_checked = False

    def __repr__(self) -> str:
        return f"KafkaJournal(topic={self._topic!r})"

    @property
    def topic(self) -> str:
        return self._topic

    def _producer_instance(self) -> Producer:
        if self._producer is None:
            config = _common(self._servers, self._timeout)
            config.update(
                {
                    "acks": "all",
                    "enable.idempotence": True,
                    "partitioner": "murmur2_random",
                    "message.timeout.ms": max(1000, int(self._timeout * 1000)),
                }
            )
            self._producer = Producer(config)
        return self._producer

    def _consumer(self) -> Consumer:
        config = _common(self._servers, self._timeout)
        config.update(
            {
                "group.id": f"ocor-c5-reader-{uuid.uuid4().hex}",
                "enable.auto.commit": False,
                "enable.auto.offset.store": False,
                "allow.auto.create.topics": False,
                "enable.partition.eof": True,
                "auto.offset.reset": "error",
                "isolation.level": "read_committed",
            }
        )
        return Consumer(config)

    def partitions(self) -> tuple[int, ...]:
        consumer = self._consumer()
        try:
            metadata = consumer.list_topics(timeout=self._timeout)
        except KafkaException as exc:
            raise KafkaJournalError(f"journal metadata unavailable: {exc}") from exc
        finally:
            consumer.close()
        topics = getattr(metadata, "topics", None)
        topic = topics.get(self._topic) if isinstance(topics, Mapping) else None
        if topic is None or topic.error is not None or not isinstance(topic.partitions, Mapping) or not topic.partitions:
            raise KafkaJournalError(f"journal topic {self._topic!r} does not exist")
        return tuple(sorted(_position(partition, "partition") for partition in topic.partitions))

    def append(self, *, key: bytes, value: bytes, headers: Sequence[tuple[str, bytes]], timestamp_ms: int) -> tuple[int, int]:
        """Write one record and wait for the broker acknowledgement; return its position."""
        if not self._topic_checked:
            self.partitions()
            self._topic_checked = True
        producer = self._producer_instance()
        outcome: dict[str, Any] = {}

        def delivered(error: KafkaError | None, message: Any) -> None:
            outcome["error"] = error
            outcome["message"] = message

        try:
            producer.produce(
                self._topic, value=value, key=key, headers=list(headers), timestamp=timestamp_ms, on_delivery=delivered
            )
            pending = producer.flush(self._timeout)
        except (BufferError, KafkaException) as exc:
            self._discard()
            raise KafkaJournalError(f"journal write failed: {exc}") from exc
        if pending or "message" not in outcome:
            self._discard()
            raise KafkaJournalError("journal write not acknowledged within the timeout")
        if outcome["error"] is not None:
            self._discard()
            raise KafkaJournalError(f"journal write refused: {outcome['error']}")
        message = outcome["message"]
        if message is None:
            raise KafkaJournalError("journal write acknowledged without a record")
        return _position(message.partition(), "partition"), _position(message.offset(), "offset")

    def _discard(self) -> None:
        """Drop a producer whose outcome is unknown, so nothing it still holds is sent later."""
        producer, self._producer = self._producer, None
        if producer is not None:
            try:
                producer.purge()
                producer.flush(0)
            except (BufferError, KafkaException):
                return

    def watermarks(self) -> dict[int, tuple[int, int]]:
        """``partition -> (low, high)`` of the journal."""
        partitions = self.partitions()
        consumer = self._consumer()
        marks: dict[int, tuple[int, int]] = {}
        try:
            for partition in partitions:
                answer = consumer.get_watermark_offsets(TopicPartition(self._topic, partition), timeout=self._timeout)
                if not isinstance(answer, tuple | list) or len(answer) != 2:
                    raise KafkaJournalError("the journal answered malformed offsets")
                low, high = _position(answer[0], "low offset"), _position(answer[1], "high offset")
                if low > high:
                    raise KafkaJournalError("the journal answered inverted offsets")
                marks[partition] = (low, high)
        except KafkaException as exc:
            raise KafkaJournalError(f"journal offsets unavailable: {exc}") from exc
        finally:
            consumer.close()
        return marks

    def offsets_for_time(self, timestamp_ms: int) -> dict[int, int]:
        """The first position at or after ``timestamp_ms`` per partition (the end if none)."""
        marks = self.watermarks()
        consumer = self._consumer()
        try:
            found = consumer.offsets_for_times(
                [TopicPartition(self._topic, partition, timestamp_ms) for partition in marks], timeout=self._timeout
            )
        except KafkaException as exc:
            raise KafkaJournalError(f"journal time index unavailable: {exc}") from exc
        finally:
            consumer.close()
        if not isinstance(found, list):
            raise KafkaJournalError("the journal time index answer is malformed")
        result: dict[int, int] = {}
        for entry in found:
            if entry is None:
                raise KafkaJournalError("the journal time index answered a null entry")
            if entry.error is not None:
                raise KafkaJournalError(f"journal time index unavailable: {entry.error}")
            partition, offset = _position(entry.partition, "partition"), entry.offset
            if partition not in marks or partition in result:
                raise KafkaJournalError("the journal time index answered an unexpected partition")
            if isinstance(offset, int) and not isinstance(offset, bool) and offset == -1:
                result[partition] = marks[partition][1]  # no record at or after the time: the end
            else:
                result[partition] = _position(offset, "offset")
        if set(result) != set(marks):
            raise KafkaJournalError("the journal time index did not answer every partition")
        return result

    def read(self, start: Mapping[int, int], end: Mapping[int, int]) -> list[JournalRecord]:
        """Every record with ``start[p] <= offset < end[p]``, in order within each partition."""
        low, high = _bounds(start, "start"), _bounds(end, "end")
        if not set(high) <= set(low):
            raise KafkaJournalError("journal read end positions name a partition without a start position")
        wanted = {partition: (low[partition], high[partition]) for partition in high if low[partition] < high[partition]}
        if not wanted:
            return []
        consumer = self._consumer()
        records: list[JournalRecord] = []
        done: set[int] = set()
        try:
            consumer.assign([TopicPartition(self._topic, partition, low) for partition, (low, _) in wanted.items()])
            misses = 0
            while len(done) < len(wanted):
                message = consumer.poll(self._timeout)
                if message is None:
                    misses += 1
                    if misses > 2:
                        raise KafkaJournalError("journal read timed out")
                    continue
                error = message.error()
                if error is not None and error.code() != KafkaError._PARTITION_EOF:
                    raise KafkaJournalError(f"journal read failed: {error}")
                partition = _position(message.partition(), "partition")
                offset = _position(message.offset(), "offset")
                if error is not None:  # the end of a partition
                    if partition in wanted and offset >= wanted[partition][1]:
                        done.add(partition)
                    continue
                if partition not in wanted or offset >= wanted[partition][1]:
                    done.add(partition)
                    continue
                records.append(
                    JournalRecord(
                        partition=partition,
                        offset=offset,
                        key=_optional_bytes(message.key(), "key"),
                        value=_optional_bytes(message.value(), "value"),
                        headers=_headers(message.headers()),
                        timestamp_ms=_timestamp(message.timestamp()),
                    )
                )
                if offset + 1 >= wanted[partition][1]:
                    done.add(partition)
        except KafkaException as exc:
            raise KafkaJournalError(f"journal read failed: {exc}") from exc
        finally:
            consumer.close()
        return records
