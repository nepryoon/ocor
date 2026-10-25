"""Real pinned Qdrant lifecycle: local command faults never qualify cleanup.

The stock image has no VOLUME declarations; an additional anonymous scratch
mount exercises the same lifecycle without changing its backend or storage.
Kafka/C5's corresponding real-backend cases remain in REM-0022 unchanged.
"""
from __future__ import annotations

import json
import subprocess
import types
import uuid

import pytest

from spikes.vector_partition import oracle

LABEL = "ocor.vector.lifecycle.owner"


def docker(*args):
    return subprocess.run(["docker", *args], text=True, capture_output=True, check=True, timeout=60).stdout


def resources():
    return {kind: set(docker(kind, "ls", *( ["--all"] if kind == "container" else []),
                                "--format", "{{.ID}}" if kind == "container" else "{{.Name}}").splitlines())
            for kind in ("container", "volume", "network")}


@pytest.fixture
def lifecycle(monkeypatch):
    original = oracle._command
    owned = {}

    def record(*args, **kwargs):
        # Real Docker creates both the container and the anonymous mount. No
        # successful boundary response is mocked, including on fault paths.
        if args[:2] == ("docker", "run"):
            command = list(args)
            command[-1:-1] = ["--volume", "/ocor-rem0018-scratch"]
            args = tuple(command)
        try:
            return original(*args, **kwargs)
        finally:
            if args[:2] == ("docker", "run"):
                name = args[args.index("--name") + 1]
                probe = subprocess.run(["docker", "inspect", name], text=True, capture_output=True, timeout=15)
                if probe.returncode == 0:
                    entry = json.loads(probe.stdout)[0]
                    owned[name] = entry
                    print("MOUNT_PROVENANCE " + json.dumps({"container": name, "id": entry["Id"],
                                                           "image": entry["Config"]["Image"], "mounts": entry["Mounts"]}, sort_keys=True))

    monkeypatch.setattr(oracle, "_command", record)
    baseline = resources()
    yield {"record": record, "original": original, "owned": owned, "baseline": baseline}
    # Diagnostic cleanup is exact and never masks an assertion failure.
    for name, entry in owned.items():
        if name in docker("container", "ls", "--all", "--format", "{{.Names}}").splitlines():
            docker("rm", "--force", "--volumes", entry["Id"])
        for mount in entry["Mounts"]:
            if mount["Type"] == "volume" and mount["Name"] in resources()["volume"]:
                docker("volume", "rm", mount["Name"])
    assert resources() == baseline, "diagnostic teardown must also leave zero owned resources"


def assert_clean(lifecycle):
    assert lifecycle["owned"], "must observe a real container"
    assert any(m["Type"] == "volume" for e in lifecycle["owned"].values() for m in e["Mounts"])
    assert resources() == lifecycle["baseline"], "owned resources remain after teardown"


def test_success_removes_anonymous_mount_preserves_baseline_and_is_idempotent(lifecycle):
    value = oracle.QdrantHarness.provision()
    assert value.request("GET", "/")["version"] == "1.15.1"
    assert json.loads(docker("inspect", value.container))[0]["Config"]["Image"] == oracle.QDRANT_IMAGE
    value.destroy()
    assert_clean(lifecycle)
    value.destroy()
    assert_clean(lifecycle)


def test_post_creation_command_timeout_cleans_all_real_resources(lifecycle, monkeypatch):
    def interrupted(*args, **kwargs):
        result = lifecycle["record"](*args, **kwargs)
        if args[:2] == ("docker", "run"):
            raise subprocess.TimeoutExpired(args, 60, output=result)
        return result
    monkeypatch.setattr(oracle, "_command", interrupted)
    with pytest.raises(subprocess.TimeoutExpired):
        oracle.QdrantHarness.provision()
    assert_clean(lifecycle)


def test_readiness_timeout_cleans_all_real_resources(lifecycle, monkeypatch):
    ticks = iter([0., 100.])
    monkeypatch.setattr(oracle, "time", types.SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None))
    with pytest.raises(oracle.VectorPartitionError, match="did not expose"):
        oracle.QdrantHarness.provision()
    assert_clean(lifecycle)


def test_removal_failure_is_explicit_and_retry_cleans(lifecycle, monkeypatch):
    value = oracle.QdrantHarness.provision()
    def failed(*args, **kwargs):
        if args[:2] == ("docker", "rm"):
            raise oracle.VectorPartitionError("injected local removal failure")
        return lifecycle["record"](*args, **kwargs)
    monkeypatch.setattr(oracle, "_command", failed)
    with pytest.raises(oracle.VectorPartitionError, match="injected local removal failure"):
        value.destroy()
    assert resources() != lifecycle["baseline"]
    monkeypatch.setattr(oracle, "_command", lifecycle["record"])
    value.destroy()
    assert_clean(lifecycle)


def test_successful_removal_response_with_residue_is_rejected(lifecycle, monkeypatch):
    value = oracle.QdrantHarness.provision()
    # Only local failure handling: simulates a lying CLI; never evidence of a
    # successful backend operation. Real residual container must cause FAIL.
    def lost(*args, **kwargs):
        if args[:2] == ("docker", "rm"):
            return ""
        return lifecycle["record"](*args, **kwargs)
    monkeypatch.setattr(oracle, "_command", lost)
    with pytest.raises(oracle.VectorPartitionError, match="owned resources remain"):
        value.destroy()
    monkeypatch.setattr(oracle, "_command", lifecycle["record"])
    value.destroy()
    assert_clean(lifecycle)


def test_foreign_container_with_spike_name_is_not_removed():
    name = "ocor-spike-0023-" + uuid.uuid4().hex[:12]
    docker("run", "--detach", "--name", name, "--label", LABEL + "=foreign", oracle.QDRANT_IMAGE)
    try:
        value = oracle.QdrantHarness(name, "unused")
        with pytest.raises(oracle.VectorPartitionError, match="refusing.*foreign"):
            value.destroy()
        assert name in docker("container", "ls", "--all", "--format", "{{.Names}}").splitlines()
    finally:
        if name in docker("container", "ls", "--all", "--format", "{{.Names}}").splitlines():
            docker("rm", "--force", "--volumes", name)


@pytest.mark.parametrize("name", ["foreign", "ocor-spike-0023-", "ocor-spike-0023-not-an-id"])
def test_non_owned_names_are_rejected_before_docker(name, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("must validate ownership before calling Docker")
    monkeypatch.setattr(oracle, "_command", forbidden)
    with pytest.raises(oracle.VectorPartitionError, match="refusing"):
        oracle.QdrantHarness(name, "unused").destroy()
