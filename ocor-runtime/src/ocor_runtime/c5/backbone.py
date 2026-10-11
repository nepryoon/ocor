"""C5 -- canonical event backbone.

Implements the smallest contract-compliant slice of LLD v1.1 section
2.5's closed ``CanonicalIngestionEnvelope`` over a real, live Kafka
broker: schema-bound events preserve partition order (partitioned by
``aggregate_ref``, Kafka's own key-based partitioner), correlation,
causation, markings and idempotency. An envelope naming an
unregistered schema, missing a required governed-context field, or
landing out of sequence for its own aggregate is quarantined rather
than published or consumed as if valid -- this task's own negative
acceptance criterion, made structural.

No CI workflow provisions a shared Kafka service (only OCOR-DEV-0031's
own mission-thread test self-provisions one), so this backbone
self-provisions its own real, isolated, single-node KRaft broker --
the identical real broker configuration
``spikes.kafka_delivery.oracle.KafkaCli.provision`` (OCOR-DEV-0019)
already proved for real -- reimplemented here rather than importing
the spike, since ``spikes/`` lies outside ocor-runtime's own pythonpath
in production (the same precedent already established by
OCOR-DEV-0037's TypeDB adapter).
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

BOOTSTRAP = "127.0.0.1:29092"
KAFKA_IMAGE = "confluentinc/cp-kafka:7.6.0@sha256:24cdd3a7fa89d2bed150560ebea81ff1943badfa61e51d66bb541a6b0d7fb047"

REGISTERED_SCHEMAS = frozenset({"urn:ocor:schema:canonical-ingestion-envelope:1"})

REQUIRED_FIELDS = (
    "event_id",
    "event_type",
    "event_version",
    "schema_ref",
    "producer_principal",
    "source_ref",
    "aggregate_ref",
    "correlation_id",
    "causation_id",
    "classification_marking_ref",
    "governed_context_digest",
    "idempotency_key",
    "sequence",
    "payload",
)


class BackboneError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


class KafkaBackboneError(RuntimeError):
    """A real Kafka CLI/backend failure, distinct from a governed
    rejection (``BackboneError``)."""


def _run(*args: str, input_text: str | None = None, timeout: int = 45) -> str:
    result = subprocess.run(args, input=input_text, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise KafkaBackboneError(f"command failed ({result.returncode}): {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


@dataclass(frozen=True, slots=True)
class CanonicalIngestionEnvelope:
    """LLD v1.1 section 2.5's closed envelope, the smallest field set
    this task's own acceptance criteria require: partition order
    (``aggregate_ref``/``sequence``), correlation/causation, marking,
    provenance (``source_ref``) and idempotency."""

    event_id: str
    event_type: str
    event_version: str
    schema_ref: str
    producer_principal: str
    source_ref: str
    aggregate_ref: str
    correlation_id: str
    causation_id: str
    classification_marking_ref: str
    governed_context_digest: str
    idempotency_key: str
    sequence: int
    payload: Mapping[str, Any]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_version": self.event_version,
            "schema_ref": self.schema_ref,
            "producer_principal": self.producer_principal,
            "source_ref": self.source_ref,
            "aggregate_ref": self.aggregate_ref,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "classification_marking_ref": self.classification_marking_ref,
            "governed_context_digest": self.governed_context_digest,
            "idempotency_key": self.idempotency_key,
            "sequence": self.sequence,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CanonicalIngestionEnvelope:
        missing = sorted(field for field in REQUIRED_FIELDS if field not in value)
        if missing:
            raise BackboneError("MISSING_CONTEXT", f"missing required field(s): {missing}")
        for field in REQUIRED_FIELDS:
            if field in ("sequence", "payload"):
                continue
            if not isinstance(value[field], str) or not value[field]:
                raise BackboneError("MISSING_CONTEXT", f"{field} must be a non-empty string")
        if isinstance(value["sequence"], bool) or not isinstance(value["sequence"], int) or value["sequence"] < 0:
            raise BackboneError("MISSING_CONTEXT", "sequence must be a non-negative integer")
        if not isinstance(value["payload"], Mapping):
            raise BackboneError("MISSING_CONTEXT", "payload must be an object")
        return cls(
            event_id=value["event_id"],
            event_type=value["event_type"],
            event_version=value["event_version"],
            schema_ref=value["schema_ref"],
            producer_principal=value["producer_principal"],
            source_ref=value["source_ref"],
            aggregate_ref=value["aggregate_ref"],
            correlation_id=value["correlation_id"],
            causation_id=value["causation_id"],
            classification_marking_ref=value["classification_marking_ref"],
            governed_context_digest=value["governed_context_digest"],
            idempotency_key=value["idempotency_key"],
            sequence=value["sequence"],
            payload=dict(value["payload"]),
        )


@dataclass(frozen=True, slots=True)
class QuarantinedEnvelope:
    reason_code: str
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DeliveredRecord:
    partition: int
    offset: int
    envelope: CanonicalIngestionEnvelope


class CanonicalEventBackbone:
    """Publishes and consumes ``CanonicalIngestionEnvelope`` records
    against a real Kafka topic, keyed by ``aggregate_ref`` so Kafka's
    own partitioner preserves per-aggregate order. Quarantine records
    every governed rejection without ever publishing it. Self-
    provisions its own real, isolated, single-node KRaft broker, so it
    never depends on a shared, externally-provisioned Kafka service."""

    def __init__(self, topic: str, *, container: str) -> None:
        self._topic = topic
        self._container = container
        self._last_sequence: dict[str, int] = {}
        self._seen_idempotency_keys: set[str] = set()
        self._quarantine: list[QuarantinedEnvelope] = []

    @classmethod
    def provision(cls, topic: str) -> tuple[CanonicalEventBackbone, str, str]:
        """Provisions a real, isolated, single-node KRaft broker (the
        identical configuration OCOR-DEV-0019's spike already proved
        for real) and its own topic. Returns the backbone plus the
        container and volume names, so a caller can tear both down."""
        suffix = uuid.uuid4().hex[:12]
        container = f"ocor-c5-backbone-{suffix}"
        volume = f"ocor-c5-backbone-data-{suffix}"
        existing_volumes = set(_run("docker", "volume", "ls", "--format", "{{.Name}}").splitlines())
        existing_containers = set(_run("docker", "container", "ls", "--all", "--format", "{{.Names}}").splitlines())
        if volume in existing_volumes or {container, f"{container}-init"} & existing_containers:
            raise KafkaBackboneError("refusing to reuse existing lifecycle resources")
        completed = False
        try:
            _run("docker", "volume", "create", "--label", f"ocor.kafka.lifecycle.owner={container}", volume)
            _run(
                "docker", "run", "--rm", "--name", f"{container}-init",
                "--label", f"ocor.kafka.lifecycle.owner={container}", "--user", "root", "--entrypoint", "chown",
                "--volume", f"{volume}:/var/lib/kafka/data", KAFKA_IMAGE, "-R", "appuser:appuser",
                "/var/lib/kafka/data",
            )
            _run(
                "docker", "run", "--detach", "--label", f"ocor.kafka.lifecycle.owner={container}",
                "--name", container, "--hostname", "kafka",
                "--security-opt", "no-new-privileges:true",
                "--volume", f"{volume}:/var/lib/kafka/data",
                "--env", "CLUSTER_ID=MkU3OEVBNTcwNTJENDM2Qk",
                "--env", "KAFKA_NODE_ID=1",
                "--env", "KAFKA_PROCESS_ROLES=broker,controller",
                "--env", "KAFKA_CONTROLLER_QUORUM_VOTERS=1@kafka:29093",
                "--env", "KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:29092,CONTROLLER://0.0.0.0:29093",
                "--env", "KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka:29092",
                "--env", "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT",
                "--env", "KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER",
                "--env", "KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT",
                "--env", "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1",
                "--env", "KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1",
                "--env", "KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1",
                "--env", "KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS=0",
                KAFKA_IMAGE,
                timeout=60,
            )
            backbone = cls(topic, container=container)
            deadline = time.monotonic() + 90
            last_error: KafkaBackboneError | None = None
            while time.monotonic() < deadline:
                try:
                    backbone._exec("kafka-broker-api-versions", "--bootstrap-server", BOOTSTRAP)
                    backbone.initialize()
                    completed = True
                    return backbone, container, volume
                except KafkaBackboneError as error:
                    last_error = error
                    time.sleep(1)
            raise KafkaBackboneError(f"isolated Kafka did not become ready: {last_error}")
        finally:
            if not completed:
                cls._cleanup_resources(container, volume)

    def destroy(self, volume: str) -> None:
        """Remove this run's resources; missing resources allow bounded retry."""
        self._cleanup_resources(self._container, volume)

    @staticmethod
    def _cleanup_resources(container: str, volume: str) -> None:
        """Verify ownership before mutation, remove anonymous mounts and fail closed.

        The init command can time out after Docker has created it. Both generated
        containers are inspected and removed by immutable ID. Named volumes are
        never pruned; only the matching ownership-labelled data volume is removed.
        """
        prefix = "ocor-c5-backbone-"
        suffix = container.removeprefix(prefix)
        if not container.startswith(prefix) or re.fullmatch(r"[0-9a-f]{12}", suffix) is None:
            raise KafkaBackboneError("refusing to destroy a non-owned container")
        if volume != f"{prefix}data-{suffix}":
            raise KafkaBackboneError("refusing to destroy a mismatched run volume")
        label = "ocor.kafka.lifecycle.owner"
        # Enumerate names rather than treating an inspect failure as 'absent'.
        names = set(_run("docker", "container", "ls", "--all", "--format", "{{.Names}}").splitlines())
        volumes = set(_run("docker", "volume", "ls", "--format", "{{.Name}}").splitlines())
        entries = []
        anonymous = set()
        for name in (f"{container}-init", container):
            if name in names:
                entry = json.loads(_run("docker", "inspect", name))[0]
                if (entry["Config"].get("Labels") or {}).get(label) != container:
                    raise KafkaBackboneError("refusing to destroy a foreign container")
                entries.append(entry)
                for mount in entry["Mounts"]:
                    if mount["Type"] == "volume" and mount["Name"] != volume:
                        anonymous.add(mount["Name"])
        if volume in volumes:
            entry = json.loads(_run("docker", "volume", "inspect", volume))[0]
            if (entry.get("Labels") or {}).get(label) != container:
                raise KafkaBackboneError("refusing to destroy a foreign volume")
        for entry in entries:
            _run("docker", "rm", "--force", "--volumes", entry["Id"])
        if volume in volumes:
            _run("docker", "volume", "rm", volume)
        remaining_containers = set(_run("docker", "container", "ls", "--all", "--format", "{{.Names}}").splitlines())
        remaining_volumes = set(_run("docker", "volume", "ls", "--format", "{{.Name}}").splitlines())
        if {container, f"{container}-init"} & remaining_containers or (anonymous | {volume}) & remaining_volumes:
            raise KafkaBackboneError("owned resources remain after teardown")

    def _exec(self, *args: str, input_text: str | None = None, timeout: int = 45) -> str:
        command = ["docker", "exec"]
        if input_text is not None:
            command.append("-i")
        command.extend((self._container, *args))
        return _run(*command, input_text=input_text, timeout=timeout)

    def initialize(self) -> None:
        self._exec(
            "kafka-topics", "--bootstrap-server", BOOTSTRAP, "--create", "--topic", self._topic,
            "--partitions", "3", "--replication-factor", "1",
        )

    @property
    def quarantine(self) -> tuple[QuarantinedEnvelope, ...]:
        return tuple(self._quarantine)

    def publish_from_mapping(self, raw: Mapping[str, Any]) -> None:
        try:
            envelope = CanonicalIngestionEnvelope.from_mapping(raw)
        except BackboneError as error:
            self._quarantine.append(QuarantinedEnvelope(error.reason_code, dict(raw)))
            raise
        self.publish(envelope)

    def publish(self, envelope: CanonicalIngestionEnvelope) -> None:
        if envelope.schema_ref not in REGISTERED_SCHEMAS:
            self._quarantine.append(QuarantinedEnvelope("UNKNOWN_SCHEMA", envelope.to_mapping()))
            raise BackboneError("UNKNOWN_SCHEMA", f"{envelope.schema_ref!r} is not a registered schema")

        if envelope.idempotency_key in self._seen_idempotency_keys:
            # already durably published once; a safe no-op replay, not
            # a duplicate canonical effect and not a quarantine event.
            return

        last = self._last_sequence.get(envelope.aggregate_ref)
        if last is not None and envelope.sequence <= last:
            self._quarantine.append(QuarantinedEnvelope("OUT_OF_ORDER", envelope.to_mapping()))
            raise BackboneError(
                "OUT_OF_ORDER", f"sequence {envelope.sequence} does not advance past {last} for {envelope.aggregate_ref!r}"
            )

        line = f"{envelope.aggregate_ref}|{json.dumps(envelope.to_mapping(), sort_keys=True, separators=(',', ':'))}"
        self._exec(
            "kafka-console-producer",
            "--bootstrap-server",
            BOOTSTRAP,
            "--topic",
            self._topic,
            "--producer-property",
            "acks=all",
            "--producer-property",
            "enable.idempotence=true",
            "--property",
            "parse.key=true",
            "--property",
            "key.separator=|",
            input_text=line + "\n",
        )
        self._last_sequence[envelope.aggregate_ref] = envelope.sequence
        self._seen_idempotency_keys.add(envelope.idempotency_key)

    def consume(self, count: int) -> tuple[DeliveredRecord, ...]:
        command = [
            "docker",
            "exec",
            self._container,
            "kafka-console-consumer",
            "--bootstrap-server",
            BOOTSTRAP,
            "--topic",
            self._topic,
            "--from-beginning",
            "--max-messages",
            str(count),
            "--timeout-ms",
            "10000",
            "--property",
            "print.key=true",
            "--property",
            "print.partition=true",
            "--property",
            "print.offset=true",
            "--property",
            "key.separator=|",
        ]
        result = subprocess.run(command, text=True, capture_output=True, timeout=30, check=False)
        records: list[DeliveredRecord] = []
        for raw_line in result.stdout.splitlines():
            if not raw_line.startswith("Partition:"):
                continue
            partition_part, offset_part, _key, payload = raw_line.split("|", 3)
            value = json.loads(payload)
            records.append(
                DeliveredRecord(
                    partition=int(partition_part.removeprefix("Partition:")),
                    offset=int(offset_part.removeprefix("Offset:")),
                    envelope=CanonicalIngestionEnvelope.from_mapping(value),
                )
            )
        if len(records) != count:
            raise KafkaBackboneError(
                f"expected {count} records, received {len(records)}; consumer exit={result.returncode}: "
                f"{result.stderr.strip()}"
            )
        return tuple(records)
