#!/usr/bin/env python3
"""Validate service locks, or run typed health checks against the real OCOR
development services (OCOR-DEV-0079).

Each service reports one of a closed set of typed statuses instead of an
untyped ``READY``/``NOT_READY`` string, so a caller can distinguish "checked
and found healthy" from "checked and found broken" from "never provisioned"
-- the previous implementation collapsed all three into the same
``NOT_READY`` value. Four services (TypeDB, OpenBao, SPIFFE/SPIRE, and the
combined OPA+Keycloak pair) already have a dedicated, fail-closed
qualification module under ``deploy/bootstrap/services/``; this script drives
those as subprocesses rather than re-implementing their contracts. The five
services without one (TerminusDB, Fuseki, PostgreSQL, Kafka, Qdrant) get a
typed check defined here: lock validation, a live Docker inspection
(running, healthy, correct pinned image, loopback-only publication), a real
protocol-level positive probe, and -- only under ``--execute``, since they
require a throwaway network client or a wrong-credential attempt -- a real
protocol-level negative probe proving the service fails closed.

OCOR-DEV-REM-0038 added Temporal (server, its own PostgreSQL and admin-tools)
and SeaweedFS, each with a dedicated qualification module under
``deploy/bootstrap/services/``; under ``--execute`` those modules also run
their negative probes (absent Temporal namespace; S3 Object Lock deletes).
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ocor_bootstrap_lib import BootstrapError, load_json, root, validate_locks

PORTS = {
    "terminusdb": 6363,
    "typedb": 1729,
    "fuseki": 3030,
    "opa": 8181,
    "keycloak": 8080,
    "openbao": 8200,
    "postgresql": 55433,
    "kafka": 19092,
    "qdrant-http": 16333,
    "qdrant-grpc": 16334,
    "temporal-grpc": 17233,
    "seaweedfs-s3": 18333,
}
CONTAINERS = {
    "fuseki",
    "kafka",
    "keycloak",
    "opa",
    "openbao",
    "postgresql",
    "qdrant",
    "seaweedfs",
    "spire-agent",
    "spire-server",
    "temporal",
    "temporal-admin-tools",
    "temporal-postgresql",
    "terminusdb",
    "typedb",
}
DIGEST_IMAGE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")


class ServiceStatus(str, Enum):
    """A closed set of typed health outcomes for one governed service."""

    READY = "READY"
    DEGRADED = "DEGRADED"
    UNREACHABLE = "UNREACHABLE"
    NOT_PROVISIONED = "NOT_PROVISIONED"


@dataclass(frozen=True)
class ServiceHealth:
    service: str
    status: ServiceStatus
    detail: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"service": self.service, "status": self.status.value, "detail": self.detail}


def _http_get(url: str, timeout: float = 3.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def docker_inspect(container: str) -> dict[str, Any] | None:
    completed = subprocess.run(
        ["docker", "inspect", container], text=True, capture_output=True, check=False, timeout=10
    )
    if completed.returncode:
        return None
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise BootstrapError(f"docker inspect returned an unexpected container set for {container}")
    result: dict[str, Any] = payload[0]
    return result


def lock_entry(services: list[dict[str, Any]], service_id: str) -> dict[str, Any]:
    matches = [item for item in services if item.get("id") == service_id]
    if len(matches) != 1:
        raise BootstrapError(f"services.lock.json must contain exactly one {service_id} entry")
    return matches[0]


def validate_running_and_pinned(inspection: dict[str, Any] | None, service: str, expected_image: str) -> list[str]:
    if inspection is None:
        return ["container not found"]
    errors: list[str] = []
    state = inspection.get("State", {})
    if state.get("Running") is not True:
        errors.append(f"{service} container is not running")
    if state.get("Paused") is True:
        errors.append(f"{service} container is paused")
    if state.get("Health", {}).get("Status") not in (None, "healthy"):
        errors.append(f"{service} container is not healthy")
    if inspection.get("Config", {}).get("Image") != expected_image:
        errors.append(f"{service} running image differs from the exact services.lock.json entry")
    bindings = inspection.get("NetworkSettings", {}).get("Ports", {}) or {}
    for group in bindings.values():
        for binding in group or []:
            if binding.get("HostIp") not in ("127.0.0.1", "::1"):
                errors.append(f"{service} publishes a non-loopback host binding")
    return errors


def check_terminusdb(repository: Path, services: list[dict[str, Any]], *, execute: bool) -> ServiceHealth:
    entry = lock_entry(services, "terminusdb")
    inspection = docker_inspect("ocor-bootstrap-terminusdb-1")
    errors = validate_running_and_pinned(inspection, "terminusdb", entry["image"])
    if errors:
        status = ServiceStatus.NOT_PROVISIONED if inspection is None else ServiceStatus.DEGRADED
        return ServiceHealth("terminusdb", status, {"errors": errors})
    try:
        ok_status, _ = _http_get("http://127.0.0.1:6363/api/ok")
        info_status, info_body = _http_get("http://127.0.0.1:6363/api/info")
    except (OSError, urllib.error.URLError) as exc:
        return ServiceHealth("terminusdb", ServiceStatus.UNREACHABLE, {"error": str(exc)})
    if ok_status != 200 or info_status != 200:
        return ServiceHealth("terminusdb", ServiceStatus.DEGRADED, {"ok_status": ok_status, "info_status": info_status})
    detail: dict[str, Any] = {"ok_status": ok_status, "info_status": info_status}
    if execute:
        request = urllib.request.Request("http://127.0.0.1:6363/api/db")
        request.add_header("Authorization", "Basic d3Jvbmc6d3Jvbmc=")  # "wrong:wrong", never a real credential
        try:
            urllib.request.urlopen(request, timeout=3.0)
            detail["unauthenticated_access"] = "FAIL_OPEN"
            return ServiceHealth("terminusdb", ServiceStatus.DEGRADED, detail)
        except urllib.error.HTTPError as exc:
            detail["unauthenticated_access"] = "FAIL_CLOSED" if exc.code == 401 else f"UNEXPECTED_{exc.code}"
            if exc.code != 401:
                return ServiceHealth("terminusdb", ServiceStatus.DEGRADED, detail)
    return ServiceHealth("terminusdb", ServiceStatus.READY, detail)


def check_fuseki(repository: Path, services: list[dict[str, Any]], *, execute: bool) -> ServiceHealth:
    entry = lock_entry(services, "fuseki")
    # Fuseki is built locally (services.lock.json declares "build", not
    # "image"); the pinned artifact is the base image and Apache source
    # archive hash (already enforced by validate_locks()), and the expected
    # running image is the build's own output tag, not a content digest --
    # BuildKit's exported manifest digest is not reproducible byte-for-byte
    # across rebuilds of the same Dockerfile/source pair.
    inspection = docker_inspect("ocor-bootstrap-fuseki-1")
    errors = validate_running_and_pinned(inspection, "fuseki", entry["build"]["output_image"])
    if errors:
        status = ServiceStatus.NOT_PROVISIONED if inspection is None else ServiceStatus.DEGRADED
        return ServiceHealth("fuseki", status, {"errors": errors})
    try:
        ping_status, _ = _http_get("http://127.0.0.1:3030/$/ping")
    except (OSError, urllib.error.URLError) as exc:
        return ServiceHealth("fuseki", ServiceStatus.UNREACHABLE, {"error": str(exc)})
    if ping_status != 200:
        return ServiceHealth("fuseki", ServiceStatus.DEGRADED, {"ping_status": ping_status})
    detail: dict[str, Any] = {"ping_status": ping_status}
    if execute:
        absent_status, _ = _http_get("http://127.0.0.1:3030/nonexistent-dataset/sparql?query=SELECT+*+WHERE+%7B%3Fs+%3Fp+%3Fo%7D")
        malformed_status, _ = _http_get("http://127.0.0.1:3030/$/ping?not-a-real-param=%")
        detail["absent_dataset_status"] = absent_status
        detail["malformed_request_status"] = malformed_status
        if absent_status != 404:
            detail["absent_dataset_check"] = "FAIL_OPEN"
            return ServiceHealth("fuseki", ServiceStatus.DEGRADED, detail)
        detail["absent_dataset_check"] = "FAIL_CLOSED"
    return ServiceHealth("fuseki", ServiceStatus.READY, detail)


def check_postgresql(repository: Path, services: list[dict[str, Any]], *, execute: bool) -> ServiceHealth:
    entry = lock_entry(services, "postgresql")
    inspection = docker_inspect("ocor-bootstrap-postgresql-1")
    errors = validate_running_and_pinned(inspection, "postgresql", entry["image"])
    if errors:
        status = ServiceStatus.NOT_PROVISIONED if inspection is None else ServiceStatus.DEGRADED
        return ServiceHealth("postgresql", status, {"errors": errors})
    ready = subprocess.run(
        ["docker", "exec", "ocor-bootstrap-postgresql-1", "pg_isready", "-U", "ocor", "-d", "ocor"],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if ready.returncode != 0:
        return ServiceHealth("postgresql", ServiceStatus.DEGRADED, {"pg_isready": ready.stdout.strip() or ready.stderr.strip()})
    detail: dict[str, Any] = {"pg_isready": ready.stdout.strip()}
    if execute:
        network = f"{subprocess.run(['docker', 'compose', '-p', 'ocor-bootstrap', 'config', '--format', 'json'], cwd=repository / 'deploy/bootstrap', text=True, capture_output=True, check=False, timeout=10).stdout}"
        try:
            network_name = json.loads(network)["networks"]["ocor-bootstrap"].get("name") or "ocor-bootstrap_ocor-bootstrap"
        except (json.JSONDecodeError, KeyError, TypeError):
            network_name = "ocor-bootstrap_ocor-bootstrap"
        probe = subprocess.run(
            [
                "docker", "run", "--rm", "--network", network_name, entry["image"],
                "sh", "-c", "PGPASSWORD=wrong-negative-check-credential psql -h postgresql -U ocor -d ocor -c 'select 1' -tA",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        detail["wrong_password_exit_code"] = probe.returncode
        detail["unauthenticated_access"] = "FAIL_CLOSED" if probe.returncode != 0 else "FAIL_OPEN"
        if probe.returncode == 0:
            return ServiceHealth("postgresql", ServiceStatus.DEGRADED, detail)
    return ServiceHealth("postgresql", ServiceStatus.READY, detail)


def check_kafka(repository: Path, services: list[dict[str, Any]], *, execute: bool) -> ServiceHealth:
    entry = lock_entry(services, "kafka")
    inspection = docker_inspect("ocor-bootstrap-kafka-1")
    errors = validate_running_and_pinned(inspection, "kafka", entry["image"])
    if errors:
        status = ServiceStatus.NOT_PROVISIONED if inspection is None else ServiceStatus.DEGRADED
        return ServiceHealth("kafka", status, {"errors": errors})
    listed = subprocess.run(
        ["docker", "exec", "ocor-bootstrap-kafka-1", "kafka-topics", "--bootstrap-server", "127.0.0.1:29092", "--list"],
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    if listed.returncode != 0:
        return ServiceHealth("kafka", ServiceStatus.DEGRADED, {"list_topics": listed.stderr.strip()})
    detail: dict[str, Any] = {"list_topics_exit_code": listed.returncode}
    if execute:
        described = subprocess.run(
            [
                "docker", "exec", "ocor-bootstrap-kafka-1", "kafka-topics",
                "--bootstrap-server", "127.0.0.1:29092", "--describe", "--topic", "ocor-nonexistent-topic",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
        detail["describe_absent_topic_exit_code"] = described.returncode
        detail["absent_topic_check"] = "FAIL_CLOSED" if described.returncode != 0 else "FAIL_OPEN"
        if described.returncode == 0:
            return ServiceHealth("kafka", ServiceStatus.DEGRADED, detail)
    return ServiceHealth("kafka", ServiceStatus.READY, detail)


def check_qdrant(repository: Path, services: list[dict[str, Any]], *, execute: bool) -> ServiceHealth:
    entry = lock_entry(services, "qdrant")
    inspection = docker_inspect("ocor-bootstrap-qdrant-1")
    errors = validate_running_and_pinned(inspection, "qdrant", entry["image"])
    if errors:
        status = ServiceStatus.NOT_PROVISIONED if inspection is None else ServiceStatus.DEGRADED
        return ServiceHealth("qdrant", status, {"errors": errors})
    try:
        root_status, root_body = _http_get("http://127.0.0.1:16333/")
    except (OSError, urllib.error.URLError) as exc:
        return ServiceHealth("qdrant", ServiceStatus.UNREACHABLE, {"error": str(exc)})
    if root_status != 200:
        return ServiceHealth("qdrant", ServiceStatus.DEGRADED, {"root_status": root_status})
    try:
        version = json.loads(root_body).get("version")
    except json.JSONDecodeError:
        version = None
    if version != entry["version"]:
        return ServiceHealth("qdrant", ServiceStatus.DEGRADED, {"version_mismatch": version})
    detail: dict[str, Any] = {"root_status": root_status, "version": version}
    if execute:
        absent_status, _ = _http_get("http://127.0.0.1:16333/collections/ocor-nonexistent-collection")
        detail["absent_collection_status"] = absent_status
        detail["absent_collection_check"] = "FAIL_CLOSED" if absent_status == 404 else "FAIL_OPEN"
        if absent_status != 404:
            return ServiceHealth("qdrant", ServiceStatus.DEGRADED, detail)
    return ServiceHealth("qdrant", ServiceStatus.READY, detail)


def _run_qualify_script(repository: Path, script: Path, extra_args: list[str]) -> tuple[int, dict[str, Any] | None, str]:
    if not script.is_file():
        return 127, None, f"missing qualification script: {script}"
    completed = subprocess.run(
        [sys.executable, str(script), *extra_args],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    return completed.returncode, payload, completed.stderr


def _status_from_qualify_payload(payload: dict[str, Any] | None, returncode: int) -> ServiceStatus:
    if payload is None:
        return ServiceStatus.UNREACHABLE
    passed = payload.get("result") == "PASS" or payload.get("status") == "PASS"
    if passed and returncode == 0:
        return ServiceStatus.READY
    if any("not found" in str(error).lower() or "not running" in str(error).lower() for error in payload.get("errors", [])):
        return ServiceStatus.NOT_PROVISIONED
    return ServiceStatus.DEGRADED


def check_typedb(repository: Path) -> ServiceHealth:
    script = repository / "deploy/bootstrap/services/typedb/qualify.py"
    returncode, payload, stderr = _run_qualify_script(repository, script, [])
    status = _status_from_qualify_payload(payload, returncode)
    return ServiceHealth("typedb", status, payload or {"stderr": stderr})


def check_openbao(repository: Path) -> ServiceHealth:
    script = repository / "deploy/bootstrap/services/openbao/qualify.py"
    returncode, payload, stderr = _run_qualify_script(repository, script, [])
    status = _status_from_qualify_payload(payload, returncode)
    return ServiceHealth("openbao", status, payload or {"stderr": stderr})


def check_spire(repository: Path) -> ServiceHealth:
    script = repository / "deploy/bootstrap/services/spire/qualify.py"
    returncode, payload, stderr = _run_qualify_script(repository, script, [])
    status = _status_from_qualify_payload(payload, returncode)
    return ServiceHealth("spiffe-spire", status, payload or {"stderr": stderr})


def check_policy_identity(repository: Path) -> ServiceHealth:
    script = repository / "deploy/bootstrap/services/policy-identity/qualify_security_services.py"
    returncode, payload, stderr = _run_qualify_script(repository, script, ["--check"])
    status = _status_from_qualify_payload(payload, returncode)
    return ServiceHealth("opa-keycloak", status, payload or {"stderr": stderr})


def check_temporal(repository: Path, *, execute: bool) -> ServiceHealth:
    script = repository / "deploy/bootstrap/services/temporal/qualify.py"
    returncode, payload, stderr = _run_qualify_script(repository, script, ["--execute"] if execute else [])
    status = _status_from_qualify_payload(payload, returncode)
    return ServiceHealth("temporal", status, payload or {"stderr": stderr})


def check_seaweedfs(repository: Path, *, execute: bool) -> ServiceHealth:
    script = repository / "deploy/bootstrap/services/seaweedfs/qualify.py"
    returncode, payload, stderr = _run_qualify_script(repository, script, ["--execute"] if execute else [])
    status = _status_from_qualify_payload(payload, returncode)
    return ServiceHealth("seaweedfs", status, payload or {"stderr": stderr})


def typed_health_checks(repository: Path, services: list[dict[str, Any]], *, execute: bool) -> list[ServiceHealth]:
    return [
        check_terminusdb(repository, services, execute=execute),
        check_typedb(repository),
        check_fuseki(repository, services, execute=execute),
        check_policy_identity(repository),
        check_openbao(repository),
        check_spire(repository),
        check_postgresql(repository, services, execute=execute),
        check_kafka(repository, services, execute=execute),
        check_qdrant(repository, services, execute=execute),
        check_temporal(repository, execute=execute),
        check_seaweedfs(repository, execute=execute),
    ]


def legacy_port_and_container_scan(repository: Path, timeout: float) -> tuple[dict[str, str], dict[str, str]]:
    results = {}
    for name, port in PORTS.items():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                results[name] = "READY"
        except OSError:
            results[name] = "NOT_READY"
    container_results = {}
    for name in sorted(CONTAINERS):
        inspection = docker_inspect(f"ocor-bootstrap-{name}-1")
        if inspection is None:
            container_results[name] = "NOT_FOUND"
            continue
        state = inspection.get("State", {})
        health = state.get("Health", {}).get("Status")
        container_results[name] = (
            "READY" if state.get("Running") and not state.get("Paused") and health in (None, "healthy")
            else "NOT_READY"
        )
    return results, container_results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--typed", action="store_true", help="run typed per-service health checks (OCOR-DEV-0079)")
    parser.add_argument("--execute", action="store_true", help="also run the real negative/fail-closed probes")
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()
    try:
        repository = root()
        errors = validate_locks(repository)
        services = load_json(repository / "infra/services.lock.json")["services"]
        if errors:
            raise BootstrapError("; ".join(errors))
        if args.manifest_only:
            print(json.dumps({"status": "PASS", "service_count": len(services)}, indent=2, sort_keys=True))
            return 0
        if args.typed:
            health = typed_health_checks(repository, services, execute=args.execute)
            status = "PASS" if all(item.status is ServiceStatus.READY for item in health) else "FAIL"
            print(json.dumps({"status": status, "services": [item.to_json() for item in health]}, indent=2, sort_keys=True))
            return 0 if status == "PASS" else 1
        results, container_results = legacy_port_and_container_scan(repository, args.timeout)
        status = "PASS" if set(results.values()) == {"READY"} and set(container_results.values()) == {"READY"} else "FAIL"
        print(json.dumps({"status": status, "services": results, "containers": container_results}, indent=2, sort_keys=True))
        return 0 if status == "PASS" else 1
    except BootstrapError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
