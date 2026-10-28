from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "deploy/local/compose.yaml"
SERVICES = {"postgres", "kafka", "opa", "keycloak", "opensearch", "qdrant"}
DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
ENVIRONMENT = {
    "OCOR_LOCAL_POSTGRES_PASSWORD": "synthetic-postgres",
    "OCOR_LOCAL_KEYCLOAK_PASSWORD": "synthetic-keycloak",
    "OCOR_LOCAL_OPENSEARCH_PASSWORD": "Synthetic-OpenSearch-Password-1!",
}


def document() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_one_command_contract_names_all_foundation_services():
    compose = document()
    assert compose["name"] == "ocor-local"
    assert compose["x-ocor-contract"]["start-command"] == (
        "docker compose -f deploy/local/compose.yaml up --detach --wait --wait-timeout 240 --remove-orphans"
    )
    assert set(compose["services"]) == SERVICES


def test_every_image_and_health_contract_is_digest_bound_and_fail_closed():
    for name, service in document()["services"].items():
        image = service["image"]
        digest = image.rsplit("@", 1)[1]
        assert DIGEST_IMAGE.fullmatch(image), name
        assert service["pull_policy"] == "never"
        assert service["restart"] == "no"
        assert service["labels"]["org.ocor.image-digest"] == digest
        assert service["labels"]["org.ocor.health-contract"] == "required"
        assert service["healthcheck"]["test"][0] in {"CMD", "CMD-SHELL"}
        assert int(service["healthcheck"]["retries"]) >= 3


def test_network_has_no_public_egress_and_ports_bind_only_loopback():
    compose = document()
    assert compose["networks"] == {"ocor-internal": {"internal": True}}
    for service in compose["services"].values():
        assert service["networks"] == ["ocor-internal"]
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:")


def test_credentials_are_required_interpolation_not_committed_literals():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "synthetic-" not in text
    for variable in ENVIRONMENT:
        assert "${" + variable + ":?" in text


def test_compose_model_resolves_with_ephemeral_credentials():
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "config", "--quiet"],
        env=os.environ | ENVIRONMENT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_credential_fails_before_service_start():
    environment = os.environ | ENVIRONMENT
    environment.pop("OCOR_LOCAL_POSTGRES_PASSWORD")
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "config", "--quiet"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "OCOR_LOCAL_POSTGRES_PASSWORD" in result.stderr


def test_missing_pinned_image_cannot_fall_back_to_public_pull(tmp_path: Path):
    missing = tmp_path / "compose.yaml"
    missing.write_text(
        """services:
  missing:
    image: ocor.invalid/missing@sha256:0000000000000000000000000000000000000000000000000000000000000000
    pull_policy: never
    command: [\"true\"]
""",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            ["docker", "compose", "-p", "ocor-missing-image-negative", "-f", str(missing), "up", "--detach"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "pull access denied" not in (result.stdout + result.stderr).lower()
    finally:
        # REM-0037-0006-NETWORK-RESIDUE-DISPOSITION (2026-10-28): remove the Compose
        # project this test creates (network included), also when the test fails.
        subprocess.run(
            ["docker", "compose", "-p", "ocor-missing-image-negative", "-f", str(missing), "down", "--remove-orphans"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_healthcheck_cannot_be_disabled(service: str):
    healthcheck = document()["services"][service]["healthcheck"]
    assert healthcheck.get("disable", False) is False
    assert healthcheck["interval"]
    assert healthcheck["timeout"]
