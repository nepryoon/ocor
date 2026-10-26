"""OCOR-DEV-REM-0038: provision Temporal and SeaweedFS in the bootstrap stack and CI.

Change set a. of the PO normative decision OCOR-DEV-0060-BA-SELECTED-COMPONENTS
(2026-10-26), option 2: the BA-05 (Temporal with its own PostgreSQL) and BA-06
(SeaweedFS with S3 Object Lock and versioning) candidate components of ADD v1.3
Part I §2.6 become real, digest-pinned services of the disposable
``ocor-bootstrap`` stack with the treatment of the existing services: locked
identity, loopback-only publication, health, typed verification, fail-closed
negative probes, bounded fault recovery and teardown with the project.
TerminusDB (BA-01) is already provisioned by OCOR-DEV-0073 and is unchanged.

The static cases bind the Compose profile, the services lock and the generated
secrets; the live cases run the qualification modules against the real stack
(a missing service fails, it never skips). Adapters are out of scope (REM b-d).
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from ocor_bootstrap_lib import validate_locks  # noqa: E402


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


verify = _load("verify_external_services_rem0038", ROOT / "scripts/verify_external_services.py")
bootstrap = _load("bootstrap_development_environment_rem0038", ROOT / "scripts/bootstrap_development_environment.py")

LOCK = json.loads((ROOT / "infra/services.lock.json").read_text(encoding="utf-8"))
COMPOSE = yaml.safe_load((ROOT / "deploy/bootstrap/compose.yaml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
NEW_SERVICES = ("temporal-postgresql", "temporal-admin-tools", "temporal", "seaweedfs")
EXPECTED_LOCK = {
    "seaweedfs": ("chrislusf/seaweedfs@sha256:f7a49e3f3972ebed5be2ed4befa4a0c68eb7bdddba6e692d42729ceb545134b8",
                  "4.51", "Apache-2.0", "https://hub.docker.com/r/chrislusf/seaweedfs"),
    "temporal": ("temporalio/server@sha256:acecbab5b0b8ae9cf4012b508866ca97feda3709577bf157b537239f40029049",
                 "1.32.1", "MIT", "https://hub.docker.com/r/temporalio/server"),
    "temporal-admin-tools": ("temporalio/admin-tools@sha256:9ef0dc5b063bf4ffd5c1512de72e0e73e225bd2c7006a18ce69bd592a8862a83",
                             "1.32.1", "MIT", "https://hub.docker.com/r/temporalio/admin-tools"),
}
LOCK_FOR_SERVICE = {"temporal-postgresql": "postgresql", "temporal-admin-tools": "temporal-admin-tools",
                    "temporal": "temporal", "seaweedfs": "seaweedfs"}


def lock_image(service_id: str) -> str:
    matches = [item for item in LOCK["services"] if item["id"] == service_id]
    assert len(matches) == 1, service_id
    image: str = matches[0]["image"]
    return image


# --- static profile ----------------------------------------------------------


def test_lock_declares_the_selected_components_exactly():
    assert validate_locks(ROOT) == []
    for service_id, (image, version, license_id, source) in EXPECTED_LOCK.items():
        [entry] = [item for item in LOCK["services"] if item["id"] == service_id]
        assert entry == {"id": service_id, "image": image, "version": version, "license": license_id,
                         "official_source": True, "source": source}


def test_lock_rejects_a_mutable_tag_for_a_new_service(tmp_path):
    mutated = json.loads(json.dumps(LOCK))
    for entry in mutated["services"]:
        if entry["id"] == "seaweedfs":
            entry["image"] = "chrislusf/seaweedfs:4.51"
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra/services.lock.json").write_text(json.dumps(mutated, indent=2, sort_keys=True) + "\n")
    (tmp_path / "infra/toolchain.lock.json").write_text((ROOT / "infra/toolchain.lock.json").read_text())
    assert "service image is not digest-pinned: seaweedfs" in validate_locks(tmp_path)


@pytest.mark.parametrize("name", NEW_SERVICES)
def test_new_services_run_the_locked_image_under_the_shared_policy(name):
    service = SERVICES[name]
    assert service["image"] == lock_image(LOCK_FOR_SERVICE[name])
    assert service["restart"] == "no" and service["init"] is True
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["networks"] == ["ocor-bootstrap"]
    assert "healthcheck" in service and service["healthcheck"]["test"]
    assert re.fullmatch(r"[0-9]+[MG]", service["deploy"]["resources"]["limits"]["memory"])


def test_publications_are_loopback_only_and_private_services_unpublished():
    assert SERVICES["temporal"]["ports"] == ["127.0.0.1:17233:7233"]
    assert SERVICES["seaweedfs"]["ports"] == ["127.0.0.1:18333:8333"]
    assert "ports" not in SERVICES["temporal-postgresql"]
    assert "ports" not in SERVICES["temporal-admin-tools"]
    published = [port for service in SERVICES.values() for port in service.get("ports", [])]
    assert all(port.startswith("127.0.0.1:") for port in published)
    host_ports = [port.split(":")[1] for port in published]
    assert len(host_ports) == len(set(host_ports)), "host port collision in the bootstrap profile"


def test_state_is_disposable_and_secrets_come_only_from_the_env_file():
    assert SERVICES["temporal-postgresql"]["tmpfs"][0].startswith("/var/lib/postgresql/data:")
    assert SERVICES["seaweedfs"]["tmpfs"][0].startswith("/data:")
    secret_fields = {
        ("temporal-postgresql", "POSTGRES_PASSWORD"): "OCOR_LOCAL_TEMPORAL_POSTGRES_PASSWORD",
        ("temporal-admin-tools", "SQL_PASSWORD"): "OCOR_LOCAL_TEMPORAL_POSTGRES_PASSWORD",
        ("temporal", "POSTGRES_PWD"): "OCOR_LOCAL_TEMPORAL_POSTGRES_PASSWORD",
        ("seaweedfs", "AWS_SECRET_ACCESS_KEY"): "OCOR_LOCAL_SEAWEEDFS_PASSWORD",
    }
    for (name, field), key in secret_fields.items():
        assert SERVICES[name]["environment"][field] == "${" + key + ":?required}"


def test_temporal_ordering_schema_and_dynamic_config():
    assert SERVICES["temporal-admin-tools"]["depends_on"] == {"temporal-postgresql": {"condition": "service_healthy"}}
    assert SERVICES["temporal"]["depends_on"] == {"temporal-admin-tools": {"condition": "service_healthy"}}
    script = SERVICES["temporal-admin-tools"]["command"][2]
    assert 'update-schema -d "/etc/temporal/schema/postgresql/v12/$$schema/versioned"' in script
    assert "touch /tmp/ocor-schema-ready" in script
    environment = SERVICES["temporal"]["environment"]
    assert environment["DB"] == "postgres12" and environment["POSTGRES_SEEDS"] == "temporal-postgresql"
    [mount] = SERVICES["temporal"]["volumes"]
    source, target, mode = mount.split(":")
    assert mode == "ro" and target == environment["DYNAMIC_CONFIG_FILE_PATH"]
    assert (ROOT / "deploy/bootstrap" / source).is_file()


def test_seaweedfs_runs_single_node_s3_with_a_generated_admin_identity():
    service = SERVICES["seaweedfs"]
    assert service["command"] == ["mini", "-dir=/data", "-master.volumeSizeLimitMB=8", "-volume.max=64"]
    assert service["environment"]["AWS_ACCESS_KEY_ID"] == "ocor-bootstrap-s3"


def test_generated_secrets_cover_the_new_services_and_stay_redactable():
    keys = set(bootstrap.GENERATED_SECRET_KEYS)
    assert {"OCOR_LOCAL_TEMPORAL_POSTGRES_PASSWORD", "OCOR_LOCAL_SEAWEEDFS_PASSWORD"} <= keys
    assert all(key.endswith(("PASSWORD", "TOKEN")) for key in keys)
    required = set(re.findall(r"\$\{(OCOR_LOCAL_[A-Z_]+):\?required\}", (ROOT / "deploy/bootstrap/compose.yaml").read_text()))
    assert required <= keys


def test_existing_env_file_gains_missing_secrets_without_rewriting_any(tmp_path):
    env_file = tmp_path / "bootstrap.env"
    env_file.write_text("OCOR_LOCAL_POSTGRES_PASSWORD=keep-me\nOCOR_SPIRE_JOIN_TOKEN=abc\n")
    added = bootstrap.ensure_generated_secrets(env_file)
    entries = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
    assert entries["OCOR_LOCAL_POSTGRES_PASSWORD"] == "keep-me" and entries["OCOR_SPIRE_JOIN_TOKEN"] == "abc"
    assert set(added) == set(bootstrap.GENERATED_SECRET_KEYS) - {"OCOR_LOCAL_POSTGRES_PASSWORD"}
    assert all(len(entries[key]) >= 32 for key in added)
    assert env_file.stat().st_mode & 0o777 == 0o600
    before = env_file.read_text()
    assert bootstrap.ensure_generated_secrets(env_file) == []
    assert env_file.read_text() == before


def test_typed_verification_includes_the_new_services(monkeypatch):
    assert {"temporal", "temporal-admin-tools", "temporal-postgresql", "seaweedfs"} <= verify.CONTAINERS
    assert verify.PORTS["temporal-grpc"] == 17233 and verify.PORTS["seaweedfs-s3"] == 18333
    calls: list[tuple[str, list[str]]] = []

    def fake(repository: Path, script: Path, extra_args: list[str]) -> tuple[int, dict[str, Any], str]:
        calls.append((script.parent.name, extra_args))
        return 1, {"result": "FAIL", "errors": ["container not found: x"]}, ""

    monkeypatch.setattr(verify, "_run_qualify_script", fake)
    temporal = verify.check_temporal(ROOT, execute=True)
    seaweedfs = verify.check_seaweedfs(ROOT, execute=False)
    assert calls == [("temporal", ["--execute"]), ("seaweedfs", [])]
    assert temporal.status is verify.ServiceStatus.NOT_PROVISIONED
    assert seaweedfs.status is verify.ServiceStatus.NOT_PROVISIONED


def test_campaign_requires_every_compose_service_as_a_mandatory_container():
    campaign = _load("run_qualifying_campaign_rem0038", ROOT / "scripts/run_qualifying_campaign.py")
    assert campaign.MANDATORY_CONTAINERS == len(SERVICES) == 15


@pytest.mark.parametrize("service", ["temporal", "seaweedfs"])
def test_qualification_contract_suites(service):
    module = _load(f"{service}_test_qualify_rem0038", ROOT / "deploy/bootstrap/services" / service / "test_qualify.py")
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.testsRun >= 9 and result.wasSuccessful() and not result.skipped


# --- live, real stack --------------------------------------------------------


def _qualify(service: str, *arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "deploy/bootstrap/services" / service / "qualify.py"), *arguments],
        cwd=ROOT, capture_output=True, text=True, timeout=300, check=False,
    )
    payload: dict[str, Any] = json.loads(completed.stdout)
    assert completed.returncode == 0, payload
    return payload


# The full-suite campaign fails on any container restart (run_qualifying_campaign
# check_stack), so the suite's fault cycle is pause/unpause; the restart cycle of
# the same modules runs in the provisioning qualification campaign.


def test_live_temporal_is_serving_pinned_and_fails_closed_then_recovers():
    result = _qualify("temporal", "--execute", "--fault-recovery", "--no-restart")
    assert result["result"] == "PASS"
    assert result["protocol"] == {"frontend_host_tcp": "READY", "cluster_health": "SERVING",
                                  "server_version": "1.32.1", "absent_namespace_lookup": "FAIL_CLOSED"}
    assert result["runtime"]["database"]["ports"] == {} and result["runtime"]["admin_tools"]["ports"] == {}
    assert result["fault_recovery"]["paused_service_detected_unavailable"] is True
    assert result["fault_recovery"]["unpause_recovery"] == "PASS"
    assert result["fault_recovery"]["after_unpause"]["cluster_health"] == "SERVING"


def test_live_seaweedfs_enforces_auth_object_lock_and_recovers():
    result = _qualify("seaweedfs", "--execute", "--fault-recovery", "--no-restart")
    assert result["result"] == "PASS"
    assert result["protocol"]["unsigned_access"] == "FAIL_CLOSED"
    assert result["protocol"]["wrong_secret_access"] == "FAIL_CLOSED"
    lock = result["object_lock"]
    assert lock["bucket"] == "ocor-qualify-object-lock"
    assert lock["bucket_versioning"] == "Enabled" and lock["bucket_object_lock"] == "Enabled"
    assert lock["retained_version_delete"] == "FAIL_CLOSED"
    assert lock["retained_version_bypass_delete"] == "FAIL_CLOSED"
    assert lock["retained_version_intact"] is True
    assert result["fault_recovery"]["unpause_recovery"] == "PASS"
    assert result["fault_recovery"]["after_unpause"]["unsigned_access"] == "FAIL_CLOSED"


def test_live_seaweedfs_repeated_object_lock_probes_do_not_exhaust_volume_slots():
    # Regression: one bucket per probe exhausted the 7 default volume slots after
    # 7 runs ("No writable volumes"); 8 consecutive probes must all pass.
    versions = set()
    for _ in range(8):
        result = _qualify("seaweedfs", "--execute")
        assert result["object_lock"]["bucket"] == "ocor-qualify-object-lock"
        assert result["object_lock"]["retained_version_delete"] == "FAIL_CLOSED"
        versions.add(result["object_lock"]["key"])
    assert len(versions) == 8


def test_live_typed_verification_reports_the_new_services_ready():
    services = verify.load_json(ROOT / "infra/services.lock.json")["services"]
    health = {item.service: item for item in verify.typed_health_checks(ROOT, services, execute=True)}
    for name in ("temporal", "seaweedfs"):
        assert health[name].status is verify.ServiceStatus.READY, health[name].to_json()
