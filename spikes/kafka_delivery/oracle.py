"""Fault-injection oracle for Kafka aggregate delivery.

The harness intentionally drives the pinned Kafka container through the vendor
CLI bundled in that image.  No in-memory broker or mock participates in the
qualifying campaign.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Any


class KafkaSpikeError(RuntimeError):
    """Stable base error for the spike harness."""


class PoisonEvent(KafkaSpikeError):
    """A record cannot be admitted to the delivery stream."""


class ConflictingDuplicate(KafkaSpikeError):
    """The same event identity was reused with different content."""


@dataclass(frozen=True)
class KafkaRecord:
    partition: int
    offset: int
    key: str
    value: dict[str, Any]

    @property
    def canonical_digest(self) -> str:
        encoded = json.dumps(self.value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CampaignResult:
    topic: str
    image: str
    broker_id: str
    records_before_restart: tuple[KafkaRecord, ...]
    records_after_restart: tuple[KafkaRecord, ...]
    deduplicated_after_consumer_crash: tuple[KafkaRecord, ...]


def _run(*args: str, input_text: str | None = None, timeout: int = 45) -> str:
    result = subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise KafkaSpikeError(
            f"command failed ({result.returncode}): {' '.join(args)}: "
            f"{result.stderr.strip()}"
        )
    return result.stdout


class KafkaCli:
    """Narrow driver for the already-approved local Kafka container."""

    def __init__(self, container: str = "ocor-local-kafka-1") -> None:
        self.container = container
        self.bootstrap = "127.0.0.1:29092"

    @classmethod
    def provision(cls) -> tuple[KafkaCli, str]:
        """Provision an isolated broker with durable storage for restart tests."""

        suffix = uuid.uuid4().hex[:12]
        container = f"ocor-spike-0019-{suffix}"
        volume = f"ocor-spike-0019-data-{suffix}"
        image = (
            "confluentinc/cp-kafka:7.6.0@"
            "sha256:24cdd3a7fa89d2bed150560ebea81ff1943badfa61e51d66bb541a6b0d7fb047"
        )
        existing_volumes = set(_run("docker", "volume", "ls", "--format", "{{.Name}}").splitlines())
        existing_containers = set(_run("docker", "container", "ls", "--all", "--format", "{{.Names}}").splitlines())
        if volume in existing_volumes or {container, f"{container}-init"} & existing_containers:
            raise KafkaSpikeError("refusing to reuse existing lifecycle resources")
        completed = False
        try:
            _run("docker", "volume", "create", "--label", f"ocor.kafka.lifecycle.owner={container}", volume)
            _run(
                "docker",
                "run",
                "--rm",
                "--name", f"{container}-init",
                "--label", f"ocor.kafka.lifecycle.owner={container}",
                "--user",
                "root",
                "--entrypoint",
                "chown",
                "--volume",
                f"{volume}:/var/lib/kafka/data",
                image,
                "-R",
                "appuser:appuser",
                "/var/lib/kafka/data",
            )
            _run(
                "docker",
                "run",
                "--detach",
                "--label", f"ocor.kafka.lifecycle.owner={container}",
                "--name",
                container,
                "--hostname",
                "kafka",
                "--security-opt",
                "no-new-privileges:true",
                "--volume",
                f"{volume}:/var/lib/kafka/data",
                "--env",
                "CLUSTER_ID=MkU3OEVBNTcwNTJENDM2Qk",
                "--env",
                "KAFKA_NODE_ID=1",
                "--env",
                "KAFKA_PROCESS_ROLES=broker,controller",
                "--env",
                "KAFKA_CONTROLLER_QUORUM_VOTERS=1@kafka:29093",
                "--env",
                "KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:29092,CONTROLLER://0.0.0.0:29093",
                "--env",
                "KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka:29092",
                "--env",
                "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT",
                "--env",
                "KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER",
                "--env",
                "KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT",
                "--env",
                "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1",
                "--env",
                "KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1",
                "--env",
                "KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1",
                "--env",
                "KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS=0",
                image,
                timeout=60,
            )
            kafka = cls(container)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    kafka.assert_real_broker()
                    completed = True
                    return kafka, volume
                except KafkaSpikeError:
                    time.sleep(1)
            raise KafkaSpikeError("isolated Kafka did not become ready")
        finally:
            if not completed:
                cls._cleanup_resources(container, volume)

    def destroy(self, volume: str) -> None:
        """Remove this run's resources; missing resources allow bounded retry."""
        self._cleanup_resources(self.container, volume)

    @staticmethod
    def _cleanup_resources(container: str, volume: str) -> None:
        """Verify ownership before mutation, remove anonymous mounts and fail closed.

        The init command can time out after Docker has created it. Both generated
        containers are inspected and removed by immutable ID. Named volumes are
        never pruned; only the matching ownership-labelled data volume is removed.
        """
        prefix = "ocor-spike-0019-"
        suffix = container.removeprefix(prefix)
        if not container.startswith(prefix) or re.fullmatch(r"[0-9a-f]{12}", suffix) is None:
            raise KafkaSpikeError("refusing to destroy a non-owned container")
        if volume != f"{prefix}data-{suffix}":
            raise KafkaSpikeError("refusing to destroy a mismatched run volume")
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
                    raise KafkaSpikeError("refusing to destroy a foreign container")
                entries.append(entry)
                for mount in entry["Mounts"]:
                    if mount["Type"] == "volume" and mount["Name"] != volume:
                        anonymous.add(mount["Name"])
        if volume in volumes:
            entry = json.loads(_run("docker", "volume", "inspect", volume))[0]
            if (entry.get("Labels") or {}).get(label) != container:
                raise KafkaSpikeError("refusing to destroy a foreign volume")
        for entry in entries:
            _run("docker", "rm", "--force", "--volumes", entry["Id"])
        if volume in volumes:
            _run("docker", "volume", "rm", volume)
        remaining_containers = set(_run("docker", "container", "ls", "--all", "--format", "{{.Names}}").splitlines())
        remaining_volumes = set(_run("docker", "volume", "ls", "--format", "{{.Name}}").splitlines())
        if {container, f"{container}-init"} & remaining_containers or (anonymous | {volume}) & remaining_volumes:
            raise KafkaSpikeError("owned resources remain after teardown")

    def _exec(self, *args: str, input_text: str | None = None, timeout: int = 45) -> str:
        command = ["docker", "exec"]
        if input_text is not None:
            command.append("-i")
        command.extend((self.container, *args))
        return _run(*command, input_text=input_text, timeout=timeout)

    def assert_real_broker(self) -> tuple[str, str]:
        inspect = _run(
            "docker",
            "inspect",
            self.container,
            "--format",
            "{{.Config.Image}}|{{.State.Status}}|"
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
        ).strip()
        image, state, health = inspect.split("|", 2)
        health_ok = health in {"healthy", "none"}
        if state != "running" or not health_ok or "kafka" not in image.lower():
            raise KafkaSpikeError(f"non-qualifying broker: {inspect}")
        versions = self._exec(
            "kafka-broker-api-versions", "--bootstrap-server", self.bootstrap
        )
        first = versions.splitlines()[0]
        if "id:" not in first:
            raise KafkaSpikeError("broker metadata did not expose a real broker id")
        return image, first

    def create_topic(self, topic: str, partitions: int = 3) -> None:
        self._exec(
            "kafka-topics",
            "--bootstrap-server",
            self.bootstrap,
            "--create",
            "--topic",
            topic,
            "--partitions",
            str(partitions),
            "--replication-factor",
            "1",
        )

    def delete_topic(self, topic: str) -> None:
        self._exec(
            "kafka-topics",
            "--bootstrap-server",
            self.bootstrap,
            "--delete",
            "--topic",
            topic,
        )

    def produce(self, topic: str, events: list[dict[str, Any]]) -> None:
        lines = []
        for event in events:
            key = event.get("aggregate_id")
            if not isinstance(key, str) or not key:
                raise PoisonEvent("aggregate_id must be a non-empty string")
            lines.append(
                f"{key}|{json.dumps(event, sort_keys=True, separators=(',', ':'))}"
            )
        self._exec(
            "kafka-console-producer",
            "--bootstrap-server",
            self.bootstrap,
            "--topic",
            topic,
            "--producer-property",
            "acks=all",
            "--producer-property",
            "enable.idempotence=true",
            "--property",
            "parse.key=true",
            "--property",
            "key.separator=|",
            input_text="\n".join(lines) + "\n",
        )

    def consume(self, topic: str, count: int) -> tuple[KafkaRecord, ...]:
        command = (
            "docker",
            "exec",
            self.container,
            "kafka-console-consumer",
            "--bootstrap-server",
            self.bootstrap,
            "--topic",
            topic,
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
        )
        # ConsoleConsumer can wait for another fetch cycle after it has printed
        # the requested records, especially immediately after a KRaft restart.
        # Its bounded idle timeout is therefore part of the command contract;
        # qualification depends on the exact record count, not its noisy exit code.
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        records = self._parse_records(result.stdout)
        if len(records) != count:
            raise KafkaSpikeError(
                f"expected {count} records, received {len(records)}; "
                f"consumer exit={result.returncode}: {result.stderr.strip()}"
            )
        return records

    @staticmethod
    def _parse_records(output: str) -> tuple[KafkaRecord, ...]:
        records = []
        for line in output.splitlines():
            if not line.startswith("Partition:"):
                continue
            partition_part, offset_part, key, payload = line.split("|", 3)
            try:
                value = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise PoisonEvent("Kafka record is not valid JSON") from exc
            records.append(
                KafkaRecord(
                    partition=int(partition_part.removeprefix("Partition:")),
                    offset=int(offset_part.removeprefix("Offset:")),
                    key=key,
                    value=value,
                )
            )
        return tuple(records)

    def consume_then_crash(self, topic: str, after_records: int) -> tuple[KafkaRecord, ...]:
        """Kill a real console-consumer process after a durable-effect prefix."""

        command = (
            "docker",
            "exec",
            self.container,
            "kafka-console-consumer",
            "--bootstrap-server",
            self.bootstrap,
            "--topic",
            topic,
            "--from-beginning",
            "--property",
            "print.key=true",
            "--property",
            "print.partition=true",
            "--property",
            "print.offset=true",
            "--property",
            "key.separator=|",
        )
        process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        lines: list[str] = []
        deadline = time.monotonic() + 30
        try:
            assert process.stdout is not None
            while len(lines) < after_records and time.monotonic() < deadline:
                line = process.stdout.readline()
                if line.startswith("Partition:"):
                    lines.append(line)
            if len(lines) != after_records:
                raise KafkaSpikeError(
                    f"consumer crash point not reached: {len(lines)}/{after_records}"
                )
        finally:
            process.kill()
            process.wait(timeout=10)
            # The docker client is the local parent; explicitly kill the isolated
            # container's Java consumer so the injected failure is unambiguous.
            subprocess.run(
                (
                    "docker",
                    "exec",
                    self.container,
                    "pkill",
                    "-f",
                    "kafka.tools.ConsoleConsumer",
                ),
                capture_output=True,
                check=False,
                timeout=10,
            )
        return self._parse_records("".join(lines))

    def restart_broker(self) -> None:
        _run("docker", "restart", self.container, timeout=60)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                self.assert_real_broker()
                return
            except KafkaSpikeError:
                time.sleep(1)
        raise KafkaSpikeError("Kafka did not become healthy after broker restart")


def deduplicate(records: tuple[KafkaRecord, ...]) -> tuple[KafkaRecord, ...]:
    """Deduplicate replayed deliveries and reject identity/content conflicts."""

    accepted: list[KafkaRecord] = []
    digests: dict[str, str] = {}
    for record in records:
        event_id = record.value.get("event_id")
        sequence = record.value.get("sequence")
        aggregate_id = record.value.get("aggregate_id")
        if (
            not isinstance(event_id, str)
            or not event_id
            or not isinstance(sequence, int)
            or sequence < 1
            or aggregate_id != record.key
        ):
            raise PoisonEvent("record violates the governed event envelope")
        prior = digests.get(event_id)
        if prior is None:
            digests[event_id] = record.canonical_digest
            accepted.append(record)
        elif prior != record.canonical_digest:
            raise ConflictingDuplicate(f"event identity {event_id} was reused")
    return tuple(accepted)


def run_campaign(container: str | None = None) -> CampaignResult:
    """Run broker-restart and consumer-crash experiments against real Kafka."""

    owned_volume: str | None = None
    if container is None:
        kafka, owned_volume = KafkaCli.provision()
    else:
        kafka = KafkaCli(container)
    image, broker_id = kafka.assert_real_broker()
    topic = f"ocor-spike-0019-{uuid.uuid4().hex[:12]}"
    events = [
        {
            "aggregate_id": "aggregate-alpha",
            "causation_id": "command-alpha",
            "correlation_id": "campaign-0019",
            "event_id": f"event-{sequence:02d}",
            "sequence": sequence,
        }
        for sequence in range(1, 9)
    ]
    kafka.create_topic(topic)
    try:
        kafka.produce(topic, events[:4])
        kafka.restart_broker()
        kafka.produce(topic, events[4:])
        first_replay = kafka.consume(topic, len(events))
        second_replay = kafka.consume(topic, len(events))

        # A consumer processes a prefix and crashes before its progress is durable.
        # Restarting from the earlier offset redelivers that prefix; event identities
        # make the externally visible effect exactly once.
        crash_prefix = kafka.consume_then_crash(topic, after_records=3)
        recovered = deduplicate(crash_prefix + second_replay)
        return CampaignResult(
            topic=topic,
            image=image,
            broker_id=broker_id,
            records_before_restart=first_replay,
            records_after_restart=second_replay,
            deduplicated_after_consumer_crash=recovered,
        )
    finally:
        kafka.delete_topic(topic)
        if owned_volume is not None:
            kafka.destroy(owned_volume)
