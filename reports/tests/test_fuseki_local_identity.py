"""Acceptance cases for the PO-authorized, local-only Fuseki identity update."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def contract_errors(previous: dict[str, Any], current: dict[str, Any], identity: dict[str, Any], recipe: bytes) -> list[str]:
    errors = []
    old = next(service["build"] for service in previous["services"] if service["id"] == "fuseki")
    new = next(service["build"] for service in current["services"] if service["id"] == "fuseki")
    restored = copy.deepcopy(current)
    next(service["build"] for service in restored["services"] if service["id"] == "fuseki")["output_sha256"] = old["output_sha256"]
    if restored != previous:
        errors.append("UNAUTHORIZED_LOCK_CHANGE")
    if identity.get("previous_output_sha256") != old["output_sha256"] or identity.get("output_sha256") != new["output_sha256"]:
        errors.append("LOCAL_IDENTITY_MISMATCH")
    if identity.get("source_sha512") != old["source_sha512"]:
        errors.append("ARCHIVE_SHA512_MISMATCH")
    if identity.get("base_image") != old["base_image"] or identity.get("base_image_id") != old["base_image"].split("@", 1)[1] or identity.get("base_layers_match") is not True:
        errors.append("BASE_IDENTITY_MISMATCH")
    if hashlib.sha256(recipe).hexdigest() != identity.get("dockerfile_sha256"):
        errors.append("RECIPE_DIGEST_MISMATCH")
    text = recipe.decode()
    if not text.startswith("FROM " + old["base_image"] + "\n") or "ARG FUSEKI_SHA512=" + old["source_sha512"] not in text or "COPY apache-jena-fuseki.tar.gz" not in text or "ADD " in text:
        errors.append("RECIPE_CONTRACT_MISMATCH")
    if not identity.get("host") or not identity.get("acquired_at") or not identity.get("reason"):
        errors.append("PROVENANCE_INCOMPLETE")
    return errors


@pytest.fixture
def acquisition() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes]:
    identity = json.loads((ROOT / "infra/fuseki/local_identity.lock.json").read_text())
    previous = json.loads(subprocess.check_output(["git", "show", identity["main_head"] + ":infra/services.lock.json"], cwd=ROOT, text=True))
    current = json.loads((ROOT / "infra/services.lock.json").read_text())
    recipe = (ROOT / identity["build_recipe_path"]).read_bytes()
    return previous, current, identity, recipe


def test_verified_acquisition_preserves_the_entire_lock_except_local_id(acquisition: tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes]) -> None:
    assert contract_errors(*acquisition) == []


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("previous_output_sha256", "0" * 64, "LOCAL_IDENTITY_MISMATCH"),
    ("output_sha256", "0" * 64, "LOCAL_IDENTITY_MISMATCH"),
    ("source_sha512", "0" * 128, "ARCHIVE_SHA512_MISMATCH"),
    ("base_image", "eclipse-temurin@sha256:" + "0" * 64, "BASE_IDENTITY_MISMATCH"),
    ("base_image_id", "sha256:" + "0" * 64, "BASE_IDENTITY_MISMATCH"),
    ("base_layers_match", False, "BASE_IDENTITY_MISMATCH"),
    ("host", "", "PROVENANCE_INCOMPLETE"),
    ("acquired_at", "", "PROVENANCE_INCOMPLETE"),
    ("reason", "", "PROVENANCE_INCOMPLETE"),
])
def test_inconsistent_or_incomplete_acquisition_is_rejected(acquisition: tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes], field: str, value: object, reason: str) -> None:
    previous, current, identity, recipe = acquisition
    identity[field] = value
    assert reason in contract_errors(previous, current, identity, recipe)


def test_any_other_lock_value_change_is_rejected(acquisition: tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes]) -> None:
    previous, current, identity, recipe = acquisition
    current["services"][1]["version"] = "unauthorized"
    assert contract_errors(previous, current, identity, recipe) == ["UNAUTHORIZED_LOCK_CHANGE"]


def test_recipe_tampering_is_rejected_even_with_recomputed_hash(acquisition: tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes]) -> None:
    previous, current, identity, recipe = acquisition
    changed = recipe.replace(b"COPY apache-jena-fuseki.tar.gz", b"ADD https://example.org/untrusted.tar.gz")
    assert "RECIPE_DIGEST_MISMATCH" in contract_errors(previous, current, identity, changed)
    identity["dockerfile_sha256"] = hashlib.sha256(changed).hexdigest()
    assert contract_errors(previous, current, identity, changed) == ["RECIPE_CONTRACT_MISMATCH"]


def test_recorded_recipe_is_the_exact_published_rem_snapshot(acquisition: tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes]) -> None:
    _, _, identity, recipe = acquisition
    original = subprocess.check_output(["git", "show", identity["source_head"] + ":infra/fuseki/Dockerfile"], cwd=ROOT)
    assert original == recipe


def test_existing_bootstrap_and_lock_validator_are_byte_identical_to_main(acquisition: tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes]) -> None:
    _, _, identity, _ = acquisition
    for relative, key in [("scripts/bootstrap_development_environment.py", "bootstrap_sha256"), ("scripts/ocor_bootstrap_lib.py", "validator_sha256")]:
        before = subprocess.check_output(["git", "show", identity["main_head"] + ":" + relative], cwd=ROOT)
        after = (ROOT / relative).read_bytes()
        assert before == after
        assert hashlib.sha256(after).hexdigest() == identity[key]
