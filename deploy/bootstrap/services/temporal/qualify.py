#!/usr/bin/env python3
"""Fail-closed qualification for the digest-pinned local Temporal service.

Temporal (OCOR-DEV-REM-0038, BA-05 candidate component) runs as three
containers of the ``ocor-bootstrap`` project: the server, its own PostgreSQL
(never published on the host) and the admin-tools container that applies the
schema and carries the official ``temporal`` CLI. The frontend speaks gRPC
only, so protocol probes run the pinned CLI inside the admin-tools container
against the project network; the loopback host publication is checked by TCP.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any


SERVER_CONTAINER = "ocor-bootstrap-temporal-1"
ADMIN_CONTAINER = "ocor-bootstrap-temporal-admin-tools-1"
DATABASE_CONTAINER = "ocor-bootstrap-temporal-postgresql-1"
FRONTEND_ADDRESS = "temporal:7233"
HOST = "127.0.0.1"
HOST_PORT = 17233
ABSENT_NAMESPACE = "ocor-qualify-absent-namespace"
SERVER_IMAGE = re.compile(r"^temporalio/server@sha256:[0-9a-f]{64}$")
ADMIN_IMAGE = re.compile(r"^temporalio/admin-tools@sha256:[0-9a-f]{64}$")
POSTGRES_IMAGE = re.compile(r"^postgres@sha256:[0-9a-f]{64}$")
SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class QualificationError(RuntimeError):
    """A mandatory Temporal qualification control failed."""


def _entry(lock: dict[str, Any], service_id: str) -> dict[str, Any]:
    matches = [item for item in lock.get("services", []) if item.get("id") == service_id]
    if len(matches) != 1:
        raise QualificationError(f"service lock must contain exactly one {service_id} entry")
    entry: dict[str, Any] = matches[0]
    if entry.get("official_source") is not True:
        raise QualificationError(f"{service_id} artifact is not marked as an official source")
    return entry


def validate_lock(lock: dict[str, Any]) -> dict[str, dict[str, Any]]:
    server = _entry(lock, "temporal")
    admin = _entry(lock, "temporal-admin-tools")
    database = _entry(lock, "postgresql")
    if not SERVER_IMAGE.fullmatch(str(server.get("image", ""))):
        raise QualificationError("Temporal server image is not digest-pinned")
    if not ADMIN_IMAGE.fullmatch(str(admin.get("image", ""))):
        raise QualificationError("Temporal admin-tools image is not digest-pinned")
    if not POSTGRES_IMAGE.fullmatch(str(database.get("image", ""))):
        raise QualificationError("Temporal PostgreSQL image is not digest-pinned")
    if server.get("source") != "https://hub.docker.com/r/temporalio/server":
        raise QualificationError("Temporal server source is not the approved official registry")
    if admin.get("source") != "https://hub.docker.com/r/temporalio/admin-tools":
        raise QualificationError("Temporal admin-tools source is not the approved official registry")
    if server.get("license") != "MIT" or admin.get("license") != "MIT":
        raise QualificationError("Temporal license metadata mismatch")
    if not SEMVER.fullmatch(str(server.get("version", ""))):
        raise QualificationError("Temporal lock has no exact semantic version")
    if admin.get("version") != server.get("version"):
        raise QualificationError("Temporal admin-tools version differs from the server version")
    return {"server": server, "admin": admin, "database": database}


def _require_running_healthy(inspection: dict[str, Any], label: str, expected_image: str) -> None:
    if inspection.get("Config", {}).get("Image") != expected_image:
        raise QualificationError(f"running {label} image differs from the exact service lock")
    state = inspection.get("State", {})
    if state.get("Running") is not True or state.get("Paused") is True:
        raise QualificationError(f"{label} container is not running")
    if state.get("Health", {}).get("Status") != "healthy":
        raise QualificationError(f"{label} container is not healthy")


def _bindings(inspection: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    ports = inspection.get("NetworkSettings", {}).get("Ports", {}) or {}
    return {key: value for key, value in ports.items() if value}


def validate_server_inspection(inspection: dict[str, Any], expected_image: str) -> dict[str, Any]:
    _require_running_healthy(inspection, "Temporal server", expected_image)
    published = _bindings(inspection)
    if set(published) != {"7233/tcp"} or len(published["7233/tcp"]) != 1:
        raise QualificationError("Temporal server must publish exactly the frontend gRPC port")
    binding = published["7233/tcp"][0]
    if binding.get("HostIp") != HOST:
        raise QualificationError("Temporal frontend publication is not loopback-only")
    if str(binding.get("HostPort")) != str(HOST_PORT):
        raise QualificationError("Temporal frontend host port differs from the approved profile")
    return {"health": "healthy", "ports": {"7233/tcp": str(HOST_PORT)}}


def validate_private_inspection(inspection: dict[str, Any], label: str, expected_image: str) -> dict[str, Any]:
    _require_running_healthy(inspection, label, expected_image)
    if _bindings(inspection):
        raise QualificationError(f"{label} must not publish any host port")
    return {"health": "healthy", "ports": {}}


def validate_observations(
    *,
    health_exit: int,
    health_output: str,
    system_exit: int,
    system_output: str,
    absent_exit: int,
    absent_output: str,
    expected_version: str,
) -> dict[str, Any]:
    if health_exit != 0 or health_output.strip() != "SERVING":
        raise QualificationError("Temporal cluster health is not SERVING")
    if system_exit != 0:
        raise QualificationError("Temporal cluster system information is unavailable")
    try:
        system = json.loads(system_output)
    except json.JSONDecodeError as exc:
        raise QualificationError(f"Temporal returned invalid system JSON: {exc}") from exc
    if not isinstance(system, dict) or system.get("serverVersion") != expected_version:
        raise QualificationError("Temporal server version does not match the lock")
    if absent_exit == 0 or "not found" not in absent_output.lower():
        raise QualificationError("describing an absent Temporal namespace did not fail closed")
    return {
        "cluster_health": "SERVING",
        "server_version": expected_version,
        "absent_namespace_lookup": "FAIL_CLOSED",
    }


def run(command: Sequence[str], timeout: float = 20.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(list(command), check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError(f"bounded command failed: {command[0]}") from exc


def inspect_container(container: str) -> dict[str, Any]:
    completed = run(["docker", "inspect", container])
    if completed.returncode:
        raise QualificationError(f"container not found: {container}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError("docker inspect returned invalid JSON") from exc
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise QualificationError("docker inspect returned an unexpected container set")
    result: dict[str, Any] = payload[0]
    return result


def cli(admin_container: str, *arguments: str, timeout: float = 20.0) -> subprocess.CompletedProcess[str]:
    return run(
        ["docker", "exec", admin_container, "temporal", *arguments,
         "--address", FRONTEND_ADDRESS, "--command-timeout", "5s"],
        timeout=timeout,
    )


def probe(admin_container: str, expected_version: str) -> dict[str, Any]:
    try:
        with socket.create_connection((HOST, HOST_PORT), timeout=3.0):
            pass
    except OSError as exc:
        raise QualificationError(f"Temporal frontend host publication is unavailable: {exc}") from exc
    health = cli(admin_container, "operator", "cluster", "health")
    system = cli(admin_container, "operator", "cluster", "system", "-o", "json")
    absent = cli(admin_container, "operator", "namespace", "describe", "-n", ABSENT_NAMESPACE)
    return {
        "frontend_host_tcp": "READY",
        **validate_observations(
            health_exit=health.returncode,
            health_output=health.stdout,
            system_exit=system.returncode,
            system_output=system.stdout,
            absent_exit=absent.returncode,
            absent_output=absent.stdout + absent.stderr,
            expected_version=expected_version,
        ),
    }


def wait_ready(server: str, admin: str, expected_image: str, expected_version: str, *, timeout: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            runtime = validate_server_inspection(inspect_container(server), expected_image)
            return {"runtime": runtime, "protocol": probe(admin, expected_version)}
        except QualificationError as exc:
            last_error = str(exc)
            time.sleep(1.0)
    raise QualificationError(f"Temporal did not recover within {timeout:.0f}s: {last_error}")


def fault_and_recover(server: str, admin: str, expected_image: str, expected_version: str, *, restart: bool = True) -> dict[str, Any]:
    paused = False
    unavailable_observed = False
    try:
        if run(["docker", "pause", server]).returncode:
            raise QualificationError("cannot pause the Temporal server container")
        paused = True
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            if cli(admin, "operator", "cluster", "health", timeout=15.0).returncode != 0:
                unavailable_observed = True
                break
            time.sleep(0.5)
        if not unavailable_observed:
            raise QualificationError("paused Temporal server was not detected unavailable")
    finally:
        if paused:
            run(["docker", "unpause", server])
    unpaused = wait_ready(server, admin, expected_image, expected_version)
    if not restart:
        return {
            "paused_service_detected_unavailable": True,
            "unpause_recovery": "PASS",
            "restart_recovery": "NOT_REQUESTED",
            "after_unpause": unpaused["protocol"],
        }
    if run(["docker", "restart", "--time", "10", server], timeout=40.0).returncode:
        raise QualificationError("cannot restart the Temporal server container")
    recovered = wait_ready(server, admin, expected_image, expected_version)
    return {
        "paused_service_detected_unavailable": True,
        "unpause_recovery": "PASS",
        "restart_recovery": "PASS",
        "after_restart": recovered["protocol"],
    }


def qualify(args: argparse.Namespace) -> dict[str, Any]:
    if args.fault_recovery and not args.execute:
        raise QualificationError("--fault-recovery requires explicit --execute")
    entries = validate_lock(json.loads(args.lock.read_text(encoding="utf-8")))
    server_image = entries["server"]["image"]
    version = entries["server"]["version"]
    runtime = {
        "server": validate_server_inspection(inspect_container(args.server_container), server_image),
        "admin_tools": validate_private_inspection(
            inspect_container(args.admin_container), "Temporal admin-tools", entries["admin"]["image"]
        ),
        "database": validate_private_inspection(
            inspect_container(args.database_container), "Temporal PostgreSQL", entries["database"]["image"]
        ),
    }
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "result": "PASS",
        "service": "temporal",
        "lock": {
            "server_image": server_image,
            "admin_tools_image": entries["admin"]["image"],
            "database_image": entries["database"]["image"],
            "version": version,
            "license": entries["server"]["license"],
        },
        "runtime": runtime,
        "protocol": probe(args.admin_container, version),
    }
    if args.fault_recovery:
        result["fault_recovery"] = fault_and_recover(
            args.server_container, args.admin_container, server_image, version, restart=not args.no_restart
        )
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path("infra/services.lock.json"))
    parser.add_argument("--server-container", default=SERVER_CONTAINER)
    parser.add_argument("--admin-container", default=ADMIN_CONTAINER)
    parser.add_argument("--database-container", default=DATABASE_CONTAINER)
    parser.add_argument("--fault-recovery", action="store_true")
    parser.add_argument(
        "--no-restart", action="store_true",
        help="pause/unpause only: the full-suite campaign forbids container restarts",
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        print(json.dumps(qualify(parse_args(argv)), indent=2, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, QualificationError) as exc:
        print(json.dumps({"result": "FAIL", "errors": [str(exc)]}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
