"""Qualification tool of the C5 backbone tests: an isolated, pinned, single-node KRaft broker.

NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 2, NCP-U06 (ADD v1.3 :273 and :360): the C5
backbone talks to Kafka in-process, through the confluent-kafka client, behind the
Publish/Subscribe/Replay/Quarantine port. The broker lifecycle -- container, volumes and test
topics -- stays here, in the qualification tools, outside the product path: no ``docker exec``
and no Kafka CLI in the component.

The lifecycle, ownership labels and fail-closed cleanup are the ones OCOR-DEV-0040 and
OCOR-DEV-REM-0022 qualified inside ``ocor_runtime.c5.backbone``, moved here unchanged. The only
addition is an ``EXTERNAL`` listener published on a loopback host port, so the in-process
client reaches the broker; the in-container ``PLAINTEXT`` listener is kept for the Kafka CLI
of this tool.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import time
import uuid

BOOTSTRAP = "127.0.0.1:29092"
EXTERNAL_PORT = "19092/tcp"
KAFKA_IMAGE = "confluentinc/cp-kafka:7.6.0@sha256:24cdd3a7fa89d2bed150560ebea81ff1943badfa61e51d66bb541a6b0d7fb047"
PREFIX = "ocor-c5-backbone-"
LABEL = "ocor.kafka.lifecycle.owner"


class KafkaBrokerError(RuntimeError):
    """A real Docker or Kafka CLI failure of the qualification broker."""


def _run(*args: str, input_text: str | None = None, timeout: int = 45) -> str:
    result = subprocess.run(args, input=input_text, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise KafkaBrokerError(f"command failed ({result.returncode}): {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class QualificationKafkaBroker:
    """One isolated broker of a test run. ``topic`` is the first test topic it creates."""

    def __init__(self, topic: str, *, container: str) -> None:
        self._topic = topic
        self._container = container

    @property
    def container(self) -> str:
        return self._container

    @property
    def topic(self) -> str:
        return self._topic

    @classmethod
    def provision(cls, topic: str) -> tuple[QualificationKafkaBroker, str, str]:
        """Provision the broker and its first topic; return it with the container and volume names."""
        suffix = uuid.uuid4().hex[:12]
        container = f"{PREFIX}{suffix}"
        volume = f"{PREFIX}data-{suffix}"
        existing_volumes = set(_run("docker", "volume", "ls", "--format", "{{.Name}}").splitlines())
        existing_containers = set(_run("docker", "container", "ls", "--all", "--format", "{{.Names}}").splitlines())
        if volume in existing_volumes or {container, f"{container}-init"} & existing_containers:
            raise KafkaBrokerError("refusing to reuse existing lifecycle resources")
        port = _free_loopback_port()
        completed = False
        try:
            _run("docker", "volume", "create", "--label", f"{LABEL}={container}", volume)
            _run(
                "docker", "run", "--rm", "--name", f"{container}-init",
                "--label", f"{LABEL}={container}", "--user", "root", "--entrypoint", "chown",
                "--volume", f"{volume}:/var/lib/kafka/data", KAFKA_IMAGE, "-R", "appuser:appuser",
                "/var/lib/kafka/data",
            )
            _run(
                "docker", "run", "--detach", "--label", f"{LABEL}={container}",
                "--name", container, "--hostname", "kafka",
                "--security-opt", "no-new-privileges:true",
                "--publish", f"127.0.0.1:{port}:19092",
                "--volume", f"{volume}:/var/lib/kafka/data",
                "--env", "CLUSTER_ID=MkU3OEVBNTcwNTJENDM2Qk",
                "--env", "KAFKA_NODE_ID=1",
                "--env", "KAFKA_PROCESS_ROLES=broker,controller",
                "--env", "KAFKA_CONTROLLER_QUORUM_VOTERS=1@kafka:29093",
                "--env", "KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:29092,CONTROLLER://0.0.0.0:29093,EXTERNAL://0.0.0.0:19092",
                "--env", f"KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka:29092,EXTERNAL://127.0.0.1:{port}",
                "--env", "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,EXTERNAL:PLAINTEXT",
                "--env", "KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER",
                "--env", "KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT",
                "--env", "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1",
                "--env", "KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1",
                "--env", "KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1",
                "--env", "KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS=0",
                KAFKA_IMAGE,
                timeout=60,
            )
            broker = cls(topic, container=container)
            deadline = time.monotonic() + 90
            last_error: KafkaBrokerError | None = None
            while time.monotonic() < deadline:
                try:
                    broker._exec("kafka-broker-api-versions", "--bootstrap-server", BOOTSTRAP)
                    broker.initialize()
                    completed = True
                    return broker, container, volume
                except KafkaBrokerError as error:
                    last_error = error
                    time.sleep(1)
            raise KafkaBrokerError(f"isolated Kafka did not become ready: {last_error}")
        finally:
            if not completed:
                cls._cleanup_resources(container, volume)

    @property
    def bootstrap_servers(self) -> str:
        """The loopback ``host:port`` of the EXTERNAL listener, for the in-process client."""
        output = _run("docker", "port", self._container, EXTERNAL_PORT).splitlines()
        for line in output:
            host, _, port = line.strip().rpartition(":")
            if host == "127.0.0.1" and port.isdigit():
                return f"127.0.0.1:{port}"
        raise KafkaBrokerError(f"{self._container} publishes no loopback port for {EXTERNAL_PORT}")

    def initialize(self) -> None:
        """Create this broker's first test topic (three partitions)."""
        self.create_topic(self._topic)

    def create_topic(self, topic: str, *, partitions: int = 3) -> str:
        self._exec(
            "kafka-topics", "--bootstrap-server", BOOTSTRAP, "--create", "--topic", topic,
            "--partitions", str(partitions), "--replication-factor", "1",
        )
        return topic

    def delete_topic(self, topic: str) -> None:
        self._exec("kafka-topics", "--bootstrap-server", BOOTSTRAP, "--delete", "--topic", topic)

    def end_offsets(self, topic: str) -> dict[int, int]:
        """Observation of the real topic: the end offset of every partition."""
        output = self._exec("kafka-get-offsets", "--bootstrap-server", BOOTSTRAP, "--topic", topic, "--time", "-1")
        offsets: dict[int, int] = {}
        for line in output.splitlines():
            parts = line.split(":")
            if len(parts) == 3 and parts[0] == topic:
                offsets[int(parts[1])] = int(parts[2])
        if not offsets:
            raise KafkaBrokerError(f"topic {topic!r} reports no partitions")
        return offsets

    def record_count(self, topic: str) -> int:
        return sum(self.end_offsets(topic).values())

    def stop(self) -> None:
        """Stop the broker container (a broker outage for fault injection); ``start`` resumes it."""
        _run("docker", "stop", "--time", "5", self._container, timeout=60)

    def start(self) -> None:
        _run("docker", "start", self._container, timeout=60)
        deadline = time.monotonic() + 90
        while True:
            try:
                self._exec("kafka-broker-api-versions", "--bootstrap-server", BOOTSTRAP)
                return
            except KafkaBrokerError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)

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
        suffix = container.removeprefix(PREFIX)
        if not container.startswith(PREFIX) or re.fullmatch(r"[0-9a-f]{12}", suffix) is None:
            raise KafkaBrokerError("refusing to destroy a non-owned container")
        if volume != f"{PREFIX}data-{suffix}":
            raise KafkaBrokerError("refusing to destroy a mismatched run volume")
        # Enumerate names rather than treating an inspect failure as 'absent'.
        names = set(_run("docker", "container", "ls", "--all", "--format", "{{.Names}}").splitlines())
        volumes = set(_run("docker", "volume", "ls", "--format", "{{.Name}}").splitlines())
        entries = []
        anonymous = set()
        for name in (f"{container}-init", container):
            if name in names:
                entry = json.loads(_run("docker", "inspect", name))[0]
                if (entry["Config"].get("Labels") or {}).get(LABEL) != container:
                    raise KafkaBrokerError("refusing to destroy a foreign container")
                entries.append(entry)
                for mount in entry["Mounts"]:
                    if mount["Type"] == "volume" and mount["Name"] != volume:
                        anonymous.add(mount["Name"])
        if volume in volumes:
            entry = json.loads(_run("docker", "volume", "inspect", volume))[0]
            if (entry.get("Labels") or {}).get(LABEL) != container:
                raise KafkaBrokerError("refusing to destroy a foreign volume")
        for entry in entries:
            _run("docker", "rm", "--force", "--volumes", entry["Id"])
        if volume in volumes:
            _run("docker", "volume", "rm", volume)
        remaining_containers = set(_run("docker", "container", "ls", "--all", "--format", "{{.Names}}").splitlines())
        remaining_volumes = set(_run("docker", "volume", "ls", "--format", "{{.Name}}").splitlines())
        if {container, f"{container}-init"} & remaining_containers or (anonymous | {volume}) & remaining_volumes:
            raise KafkaBrokerError("owned resources remain after teardown")

    def _exec(self, *args: str, input_text: str | None = None, timeout: int = 45) -> str:
        command = ["docker", "exec"]
        if input_text is not None:
            command.append("-i")
        command.extend((self._container, *args))
        return _run(*command, input_text=input_text, timeout=timeout)
