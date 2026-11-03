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
    key: bytes
    value: bytes
    headers: tuple[tuple[str, bytes], ...]
    timestamp_ms: int

    def header(self, name: str) -> bytes | None:
        values = [value for key, value in self.headers if key == name]
        return values[0] if len(values) == 1 else None


def _bytes(value: object) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    raise KafkaJournalError("journal record field is not bytes")


def _headers(value: object) -> tuple[tuple[str, bytes], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise KafkaJournalError("journal record headers are malformed")
    result = []
    for item in value:
        if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], str):
            raise KafkaJournalError("journal record header is malformed")
        result.append((item[0], _bytes(item[1])))
    return tuple(result)


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
        topic = metadata.topics.get(self._topic)
        if topic is None or topic.error is not None or not topic.partitions:
            raise KafkaJournalError(f"journal topic {self._topic!r} does not exist")
        return tuple(sorted(topic.partitions))

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
        return int(message.partition()), int(message.offset())

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
        try:
            return {
                partition: tuple(  # type: ignore[misc]
                    consumer.get_watermark_offsets(TopicPartition(self._topic, partition), timeout=self._timeout)
                )
                for partition in partitions
            }
        except (KafkaException, TypeError) as exc:
            raise KafkaJournalError(f"journal offsets unavailable: {exc}") from exc
        finally:
            consumer.close()

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
        result = {}
        for entry in found:
            if entry.error is not None:
                raise KafkaJournalError(f"journal time index unavailable: {entry.error}")
            result[entry.partition] = entry.offset if entry.offset >= 0 else marks[entry.partition][1]
        return result

    def read(self, start: Mapping[int, int], end: Mapping[int, int]) -> list[JournalRecord]:
        """Every record with ``start[p] <= offset < end[p]``, in order within each partition."""
        wanted = {partition: (start[partition], end[partition]) for partition in end if start.get(partition, 0) < end[partition]}
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
                partition, offset = message.partition(), message.offset()
                if partition is None or offset is None:
                    raise KafkaJournalError("journal read returned a record without a position")
                if error is not None:
                    if error.code() == KafkaError._PARTITION_EOF:
                        if partition in wanted and offset >= wanted[partition][1]:
                            done.add(partition)
                        continue
                    raise KafkaJournalError(f"journal read failed: {error}")
                if partition not in wanted or offset >= wanted[partition][1]:
                    done.add(partition)
                    continue
                records.append(
                    JournalRecord(
                        partition=partition,
                        offset=offset,
                        key=_bytes(message.key()),
                        value=_bytes(message.value()),
                        headers=_headers(message.headers()),
                        timestamp_ms=int(message.timestamp()[1]),
                    )
                )
                if offset + 1 >= wanted[partition][1]:
                    done.add(partition)
        except KafkaException as exc:
            raise KafkaJournalError(f"journal read failed: {exc}") from exc
        finally:
            consumer.close()
        return records
