"""REM-0022: real pinned Kafka lifecycle, ownership and fail-closed cleanup.

Faults wrap the real Docker call; no broker response is mocked. Only local
command failure/clock handling is injected. Every mount is observed before
removal, and diagnostic cleanup never converts a failed assertion into PASS.
"""
from __future__ import annotations

import json
import subprocess
import types
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from ocor_runtime.c5 import backbone

from spikes.kafka_delivery import oracle

LABEL = "ocor.kafka.lifecycle.owner"


def docker(*args: str) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    return result.stdout


def exists(kind: str, name: str) -> bool:
    command = ["docker", kind, "inspect", name]
    return subprocess.run(command, capture_output=True, timeout=15).returncode == 0


@pytest.fixture(params=["spike", "backbone"])
def lifecycle(request: pytest.FixtureRequest) -> Iterator[dict[str, Any]]:
    module = oracle if request.param == "spike" else backbone
    cls = oracle.KafkaCli if request.param == "spike" else backbone.CanonicalEventBackbone
    prefix = "ocor-spike-0019-" if request.param == "spike" else "ocor-c5-backbone-"
    observed: dict[str, Any] = {"module": module, "cls": cls, "prefix": prefix, "mounts": {}, "containers": set()}
    original = module._run

    def record(*args: str, **kwargs: Any) -> str:
        try:
            return original(*args, **kwargs)
        finally:
            if args[:2] == ("docker", "run") and "--name" in args:
                name = args[args.index("--name") + 1]
                observed["containers"].add(name)
                if exists("container", name):
                    entry = json.loads(docker("inspect", name))[0]
                    for mount in entry["Mounts"]:
                        if mount["Type"] == "volume":
                            observed["mounts"][mount["Name"]] = {"container": name, "destination": mount["Destination"], "image": entry["Image"]}
                    print("MOUNT_PROVENANCE " + json.dumps(observed["mounts"], sort_keys=True))
    observed["record"] = record
    observed["original"] = original
    try:
        yield observed
    finally:
        # Exact names/mount provenance captured by this test, never a global prune.
        for name in observed["containers"]:
            if exists("container", name):
                docker("rm", "--force", "--volumes", name)
        for name in observed["mounts"]:
            if exists("volume", name):
                docker("volume", "rm", name)


def provision(lifecycle: dict[str, Any]) -> tuple[Any, str]:
    if lifecycle["module"] is oracle:
        return lifecycle["cls"].provision()
    value, _, volume = lifecycle["cls"].provision("ocor-rem0022-" + uuid.uuid4().hex[:12])
    return value, volume


def assert_absent(lifecycle: dict[str, Any]) -> None:
    assert lifecycle["mounts"], "must observe real image-declared anonymous mount"
    assert any(m["destination"] == "/etc/kafka/secrets" for m in lifecycle["mounts"].values())
    remaining = [n for n in lifecycle["containers"] if exists("container", n)]
    remaining += [n for n in lifecycle["mounts"] if exists("volume", n)]
    assert remaining == [], f"owned resources remain after teardown: {remaining}"


def test_success_removes_named_and_anonymous_mounts_and_preserves_unrelated(lifecycle, monkeypatch):
    sentinel = "ocor-rem0022-unrelated-" + uuid.uuid4().hex[:12]
    docker("volume", "create", sentinel)
    try:
        monkeypatch.setattr(lifecycle["module"], "_run", lifecycle["record"])
        value, volume = provision(lifecycle)
        if lifecycle["module"] is oracle:
            image, broker_id = value.assert_real_broker()
            assert "@sha256:24cdd3a7" in image and "id: 1" in broker_id
        else:
            assert "id: 1" in value._exec("kafka-broker-api-versions", "--bootstrap-server", backbone.BOOTSTRAP)
        value.destroy(volume)
        assert_absent(lifecycle)
        value.destroy(volume)  # retry after success must be idempotent
        assert exists("volume", sentinel)
    finally:
        docker("volume", "rm", sentinel)


def test_partial_detached_start_failure_cleans_real_resources(lifecycle, monkeypatch):
    def interrupted(*args, **kwargs):
        result = lifecycle["record"](*args, **kwargs)
        if args[:2] == ("docker", "run") and "--detach" in args:
            raise subprocess.TimeoutExpired(args, 60, output=result)
        return result
    monkeypatch.setattr(lifecycle["module"], "_run", interrupted)
    with pytest.raises(subprocess.TimeoutExpired):
        provision(lifecycle)
    assert_absent(lifecycle)


def test_readiness_timeout_cleans_real_resources(lifecycle, monkeypatch):
    monkeypatch.setattr(lifecycle["module"], "_run", lifecycle["record"])
    # Only the boundary's local polling budget changes. Real Docker and Kafka CLI
    # are still invoked; none of their responses is replaced by a fake success.
    ticks = iter([0.0, 1.0, 100.0])
    monkeypatch.setattr(lifecycle["module"], "time", types.SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None))
    lifecycle["error"] = oracle.KafkaSpikeError if lifecycle["module"] is oracle else backbone.KafkaBackboneError
    if lifecycle["module"] is oracle:
        original = oracle.KafkaCli.assert_real_broker
        def fail(self):
            original(self)
            raise oracle.KafkaSpikeError("injected local readiness failure")
        monkeypatch.setattr(oracle.KafkaCli, "assert_real_broker", fail)
    else:
        original = backbone.CanonicalEventBackbone._exec
        def fail(self, *args, **kwargs):
            original(self, *args, **kwargs)
            raise backbone.KafkaBackboneError("injected local readiness failure")
        monkeypatch.setattr(backbone.CanonicalEventBackbone, "_exec", fail)
    with pytest.raises(lifecycle["error"], match="did not become ready"):
        provision(lifecycle)
    assert_absent(lifecycle)


def test_teardown_command_failure_is_reported_and_retry_cleans(lifecycle, monkeypatch):
    monkeypatch.setattr(lifecycle["module"], "_run", lifecycle["record"])
    value, volume = provision(lifecycle)
    error = oracle.KafkaSpikeError if lifecycle["module"] is oracle else backbone.KafkaBackboneError
    def fail(*args, **kwargs):
        if args[:2] == ("docker", "rm"):
            raise error("injected removal failure")
        return lifecycle["record"](*args, **kwargs)
    monkeypatch.setattr(lifecycle["module"], "_run", fail)
    with pytest.raises(error, match="injected removal failure"):
        value.destroy(volume)
    assert any(exists("container", n) for n in lifecycle["containers"])
    monkeypatch.setattr(lifecycle["module"], "_run", lifecycle["record"])
    value.destroy(volume)
    assert_absent(lifecycle)


def test_mismatched_run_volume_and_foreign_labels_are_refused(lifecycle, monkeypatch):
    monkeypatch.setattr(lifecycle["module"], "_run", lifecycle["record"])
    value, volume = provision(lifecycle)
    error = oracle.KafkaSpikeError if lifecycle["module"] is oracle else backbone.KafkaBackboneError
    foreign = lifecycle["prefix"] + "data-" + uuid.uuid4().hex[:12]
    docker("volume", "create", foreign)
    try:
        with pytest.raises(error, match="refusing"):
            value.destroy(foreign)
        assert exists("volume", foreign)
        assert exists("volume", volume)
        # Same generated name but a foreign volume must still be refused.
        name = lifecycle["prefix"] + uuid.uuid4().hex[:12]
        unlabeled = lifecycle["prefix"] + "data-" + name.removeprefix(lifecycle["prefix"])
        docker("volume", "create", unlabeled)
        try:
            other = lifecycle["cls"](name) if lifecycle["module"] is oracle else lifecycle["cls"]("unused", container=name)
            with pytest.raises(error, match="refusing"):
                other.destroy(unlabeled)
            assert exists("volume", unlabeled)
        finally:
            docker("volume", "rm", unlabeled)
        value.destroy(volume)
        assert_absent(lifecycle)
    finally:
        docker("volume", "rm", foreign)


def test_interrupted_initializer_is_removed_with_all_mounts(lifecycle, monkeypatch):
    error = subprocess.TimeoutExpired
    def interrupted(*args, **kwargs):
        if args[:2] == ("docker", "run") and "--rm" in args:
            command = list(args)
            command[command.index("--rm")] = "--detach"
            command[command.index("--entrypoint") + 1] = "sleep"
            index = next(i for i, arg in enumerate(command) if arg.startswith("confluentinc/cp-kafka:"))
            command = command[:index + 1] + ["60"]
            lifecycle["record"](*command, **kwargs)
            raise error(command, 45)
        return lifecycle["record"](*args, **kwargs)
    monkeypatch.setattr(lifecycle["module"], "_run", interrupted)
    with pytest.raises(error):
        provision(lifecycle)
    assert_absent(lifecycle)


def test_foreign_container_label_is_rejected_before_any_removal(lifecycle, monkeypatch):
    suffix = uuid.uuid4().hex[:12]
    name = lifecycle["prefix"] + suffix
    volume = lifecycle["prefix"] + "data-" + suffix
    docker("volume", "create", "--label", f"{LABEL}={name}", volume)
    lifecycle["mounts"][volume] = {"container": name, "destination": "/var/lib/kafka/data", "image": backbone.KAFKA_IMAGE}
    command = ["docker", "run", "--detach", "--name", name, "--label", f"{LABEL}=foreign", "--volume", f"{volume}:/var/lib/kafka/data", "--entrypoint", "sleep", backbone.KAFKA_IMAGE, "60"]
    lifecycle["record"](*command)
    monkeypatch.setattr(lifecycle["module"], "_run", lifecycle["record"])
    value = lifecycle["cls"](name) if lifecycle["module"] is oracle else lifecycle["cls"]("unused", container=name)
    error = oracle.KafkaSpikeError if lifecycle["module"] is oracle else backbone.KafkaBackboneError
    with pytest.raises(error, match="refusing.*foreign container"):
        value.destroy(volume)
    assert exists("container", name) and exists("volume", volume)


def test_non_owned_container_name_is_refused(lifecycle):
    value = lifecycle["cls"]("foreign") if lifecycle["module"] is oracle else lifecycle["cls"]("unused", container="foreign")
    error = oracle.KafkaSpikeError if lifecycle["module"] is oracle else backbone.KafkaBackboneError
    with pytest.raises(error, match="refusing"):
        value.destroy("foreign")


def test_preexisting_volume_is_never_reused_or_deleted(lifecycle, monkeypatch):
    ident = uuid.uuid4()
    volume = lifecycle["prefix"] + "data-" + ident.hex[:12]
    docker("volume", "create", volume)
    monkeypatch.setattr(lifecycle["module"], "uuid", types.SimpleNamespace(uuid4=lambda: ident))
    error = oracle.KafkaSpikeError if lifecycle["module"] is oracle else backbone.KafkaBackboneError
    try:
        with pytest.raises(error, match="refusing.*existing lifecycle"):
            provision(lifecycle)
        assert exists("volume", volume)
        assert not exists("container", lifecycle["prefix"] + ident.hex[:12])
    finally:
        docker("volume", "rm", volume)


def test_named_volume_removal_failure_can_be_retried(lifecycle, monkeypatch):
    monkeypatch.setattr(lifecycle["module"], "_run", lifecycle["record"])
    value, volume = provision(lifecycle)
    error = oracle.KafkaSpikeError if lifecycle["module"] is oracle else backbone.KafkaBackboneError
    def fail(*args, **kwargs):
        if args[:3] == ("docker", "volume", "rm"):
            raise error("injected data-volume removal failure")
        return lifecycle["record"](*args, **kwargs)
    monkeypatch.setattr(lifecycle["module"], "_run", fail)
    with pytest.raises(error, match="injected data-volume removal failure"):
        value.destroy(volume)
    assert exists("volume", volume)
    assert not any(exists("container", n) for n in lifecycle["containers"])
    monkeypatch.setattr(lifecycle["module"], "_run", lifecycle["record"])
    value.destroy(volume)
    assert_absent(lifecycle)


def test_residual_anonymous_mount_is_detected_even_after_command_success(lifecycle, monkeypatch):
    monkeypatch.setattr(lifecycle["module"], "_run", lifecycle["record"])
    value, volume = provision(lifecycle)
    error = oracle.KafkaSpikeError if lifecycle["module"] is oracle else backbone.KafkaBackboneError
    def omit_volumes(*args, **kwargs):
        if args[:2] == ("docker", "rm"):
            args = tuple(a for a in args if a != "--volumes")
        return lifecycle["record"](*args, **kwargs)
    monkeypatch.setattr(lifecycle["module"], "_run", omit_volumes)
    with pytest.raises(error, match="owned resources remain after teardown"):
        value.destroy(volume)
    assert any(exists("volume", n) for n, m in lifecycle["mounts"].items() if m["destination"] == "/etc/kafka/secrets")
    # Fixture diagnostic cleanup is limited to this test's observed mounts.
