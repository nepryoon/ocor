#!/usr/bin/env python3
"""Unit contract tests for the Temporal provisioning qualification harness."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from typing import Any


MODULE_PATH = Path(__file__).with_name("qualify.py")
SPEC = importlib.util.spec_from_file_location("temporal_qualify", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
qualify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualify)

SERVER = "temporalio/server@sha256:" + "a" * 64
ADMIN = "temporalio/admin-tools@sha256:" + "b" * 64
POSTGRES = "postgres@sha256:" + "c" * 64


def lock(server: dict[str, Any] | None = None, admin: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "services": [
            {"id": "temporal", "image": SERVER, "version": "1.32.1", "official_source": True,
             "source": "https://hub.docker.com/r/temporalio/server", "license": "MIT", **(server or {})},
            {"id": "temporal-admin-tools", "image": ADMIN, "version": "1.32.1", "official_source": True,
             "source": "https://hub.docker.com/r/temporalio/admin-tools", "license": "MIT", **(admin or {})},
            {"id": "postgresql", "image": POSTGRES, "version": "16", "official_source": True,
             "source": "https://hub.docker.com/_/postgres", "license": "PostgreSQL"},
        ]
    }


def inspection(image: str, ports: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "Config": {"Image": image},
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "NetworkSettings": {"Ports": ports if ports is not None else {}},
    }


SERVER_PORTS = {"7233/tcp": [{"HostIp": "127.0.0.1", "HostPort": "17233"}], "6933/tcp": None}


def observations(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "health_exit": 0,
        "health_output": "SERVING\n",
        "system_exit": 0,
        "system_output": json.dumps({"serverVersion": "1.32.1", "capabilities": {}}),
        "absent_exit": 1,
        "absent_output": "Error: unable to describe namespace x: Namespace x is not found.",
        "expected_version": "1.32.1",
    }
    values.update(overrides)
    return values


class TemporalQualificationContractTests(unittest.TestCase):
    def test_lock_contract_accepts_exact_digests_and_matching_versions(self) -> None:
        entries = qualify.validate_lock(lock())
        self.assertEqual(entries["server"]["version"], "1.32.1")
        self.assertEqual(entries["database"]["image"], POSTGRES)

    def test_lock_contract_rejects_mutable_or_mismatched_artifacts(self) -> None:
        cases = {
            "server image is not digest-pinned": lock(server={"image": "temporalio/server:1.32.1"}),
            "admin-tools image is not digest-pinned": lock(admin={"image": "temporalio/admin-tools:latest"}),
            "license": lock(server={"license": "BUSL-1.1"}),
            "source": lock(admin={"source": "https://example.invalid/admin-tools"}),
            "exact semantic version": lock(server={"version": "1.32"}, admin={"version": "1.32"}),
            "differs from the server version": lock(admin={"version": "1.31.4"}),
            "official source": lock(server={"official_source": False}),
        }
        for message, value in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(qualify.QualificationError, message):
                qualify.validate_lock(value)

    def test_server_runtime_accepts_loopback_frontend_only(self) -> None:
        result = qualify.validate_server_inspection(inspection(SERVER, SERVER_PORTS), SERVER)
        self.assertEqual(result["ports"], {"7233/tcp": "17233"})

    def test_server_runtime_rejects_external_or_extra_publication(self) -> None:
        external = {"7233/tcp": [{"HostIp": "0.0.0.0", "HostPort": "17233"}]}
        with self.assertRaisesRegex(qualify.QualificationError, "loopback-only"):
            qualify.validate_server_inspection(inspection(SERVER, external), SERVER)
        extra = {**SERVER_PORTS, "7243/tcp": [{"HostIp": "127.0.0.1", "HostPort": "7243"}]}
        with self.assertRaisesRegex(qualify.QualificationError, "exactly the frontend"):
            qualify.validate_server_inspection(inspection(SERVER, extra), SERVER)
        moved = {"7233/tcp": [{"HostIp": "127.0.0.1", "HostPort": "7233"}]}
        with self.assertRaisesRegex(qualify.QualificationError, "host port"):
            qualify.validate_server_inspection(inspection(SERVER, moved), SERVER)

    def test_private_runtime_rejects_any_host_publication(self) -> None:
        self.assertEqual(qualify.validate_private_inspection(inspection(POSTGRES), "db", POSTGRES)["ports"], {})
        published = {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5432"}]}
        with self.assertRaisesRegex(qualify.QualificationError, "must not publish"):
            qualify.validate_private_inspection(inspection(POSTGRES, published), "db", POSTGRES)

    def test_runtime_rejects_unhealthy_paused_or_other_image(self) -> None:
        unhealthy = inspection(SERVER, SERVER_PORTS)
        unhealthy["State"]["Health"]["Status"] = "unhealthy"
        with self.assertRaisesRegex(qualify.QualificationError, "not healthy"):
            qualify.validate_server_inspection(unhealthy, SERVER)
        paused = inspection(SERVER, SERVER_PORTS)
        paused["State"]["Paused"] = True
        with self.assertRaisesRegex(qualify.QualificationError, "not running"):
            qualify.validate_server_inspection(paused, SERVER)
        with self.assertRaisesRegex(qualify.QualificationError, "differs"):
            qualify.validate_server_inspection(inspection(SERVER, SERVER_PORTS), ADMIN)

    def test_observations_accept_serving_cluster_and_closed_absent_namespace(self) -> None:
        result = qualify.validate_observations(**observations())
        self.assertEqual(result["cluster_health"], "SERVING")
        self.assertEqual(result["absent_namespace_lookup"], "FAIL_CLOSED")

    def test_observations_reject_every_degraded_branch(self) -> None:
        cases = {
            "not SERVING": {"health_output": "NOT_SERVING"},
            "health": {"health_exit": 1},
            "system information": {"system_exit": 1},
            "invalid system JSON": {"system_output": "not json"},
            "version does not match": {"system_output": json.dumps({"serverVersion": "1.31.4"})},
            "absent Temporal namespace": {"absent_exit": 0, "absent_output": "Namespace found"},
        }
        for message, override in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(qualify.QualificationError, message):
                qualify.validate_observations(**observations(**override))

    def test_fault_recovery_requires_explicit_execute(self) -> None:
        with self.assertRaisesRegex(qualify.QualificationError, "requires explicit --execute"):
            qualify.qualify(qualify.parse_args(["--fault-recovery", "--lock", "/nonexistent/lock.json"]))


if __name__ == "__main__":
    unittest.main()
