"""OCOR-DEV-0060 -- BA-06: SeaweedFS 4.51 (S3-compatible, Object Lock + versioning) behind C7.

Backend assumption ``BA-06`` of ADD v1.3 Part I §2.6 (row ``BA-06``, "Storage
S3-compatible + PostgreSQL -- ``C7``") and LLD v1.1 §7.1 (row ``BA-06``). The real
component is the digest-pinned SeaweedFS 4.51 server of the ``ocor-bootstrap`` stack
(service ``seaweedfs``), reached only through the sealed OCOR-DEV-REM-0040 adapter
``ocor_runtime.c7.adapters.seaweedfs.SeaweedFSSealedResultStore`` behind the
``ocor_runtime.c7.sealed_results.ScenarioOverlayStoreSealSubset`` port
(``sealResult`` of ADD v1.3 §4.2). Every sealed value is a real ``CausalOutcome``
computed by the sealed ``ocor_runtime.c7.runtime`` (identify-or-abstain, lineage,
reproducibility digest).

What is observed on the server: the sealed object is the canonical preimage of its
content address, carries a ``COMPLIANCE`` retention in a versioned Object Lock bucket,
cannot be deleted (with or without the bypass header) nor replaced by an overwrite, a
tampered object under a digest key is rejected on read, an identical re-seal is
idempotent and a different content under a sealed digest is rejected; identified and
abstained outcomes keep their lineage and are reproducible from the same pins; a
scenario result never shares an address with a ``main`` (abstained) or a differently
pinned result.

Scope limitation (reported, not hidden): the ``BA-06`` part on the PostgreSQL job
ledger -- budget, progress, cancellation and resource release within the declared
target -- has no implementation in ``ocor-runtime/src`` (no C7 job ledger port, no
scheduler, no cancellation API; ``c7/runtime.py`` is synchronous and stateless). It
is not exercised here and is not claimed by this module.

Fixture rules (REM-0040 disposition): the only retention is ``COMPLIANCE`` for at
most one hour, fixed in ``TEST_RETENTION``; one dedicated bucket is reused across runs
(the REM-0040 C7 sealed-result test bucket, so no additional SeaweedFS volumes are
allocated); every digest derives from a per-run nonce and no case depends on the
absence of objects sealed by earlier runs. The adapter path issues only ``GET`` and
``PUT``; the out-of-band attacks below use the REM-0038 qualification client. Sealed
versions cannot be removed before their retention expires (that is the property under
test); the stack keeps SeaweedFS data on tmpfs. An unavailable server fails.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import os
import urllib.parse
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ocor_runtime.c7.adapters import seaweedfs
from ocor_runtime.c7.adapters.seaweedfs import SeaweedFSSealedResultStore, object_key, sealed_payload
from ocor_runtime.c7.runtime import (
    CausalOutcome,
    CausalQuery,
    canonical_digest,
    estimate_intervention,
    estimate_uncertainty,
    verify_reproduction,
)
from ocor_runtime.c7.sealed_results import ScenarioOverlayStoreSealSubset, SealedResultError

BA_CASE = {
    "ba_id": "BA-06",
    "component": "SeaweedFS S3-compatible store with Object Lock and versioning behind the sealed C7 sealResult adapter",
    "component_version": "4.51",
    "backend_services": ["seaweedfs"],
    "add_v1_3_part_i_2_6": {
        "required_property": "Content-addressing immutabile per `sealResult`",
        "conformance_test": "Test di immutabilità post-`sealResult`",
    },
    "lld_v1_1_7_1_oracle": "S3/PostgreSQL sigilla causal result, lineage, identify-or-abstain e isolation",
    "requirement_ids": ["NFR-030", "NFR-090", "FR-090"],
    "requirement_binding": {
        "NFR-030": (
            "The causal result is stored content-addressed and immutable, and a content whose digest "
            "does not match its address is rejected on read instead of being used."
        ),
        "NFR-090": (
            "The sealed result read back from the server reproduces, digest for digest, the run "
            "recomputed from the same model, data, intervention, release and seed pins."
        ),
        "FR-090": (
            "Both an identified estimate and an abstention (no effect estimate) are sealed and read back "
            "with their status, method or reason code, assumptions and lineage unchanged."
        ),
    },
    "positive_tests": [
        "test_ba_06_positive_identified_result_is_sealed_immutably_with_lineage_and_reproduces",
        "test_ba_06_positive_abstentions_are_sealed_and_isolated_from_scenario_results",
    ],
    "negative_tests": [
        "test_ba_06_negative_delete_and_overwrite_after_seal_never_change_the_sealed_result",
        "test_ba_06_negative_tampered_object_under_a_digest_key_is_rejected_on_read_and_seal",
        "test_ba_06_negative_different_content_under_a_sealed_digest_is_rejected",
    ],
    "fault_tests": [],
}

RUNTIME_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = RUNTIME_ROOT.parent
QUALIFY_PATH = REPOSITORY_ROOT / "deploy/bootstrap/services/seaweedfs/qualify.py"
URL = os.environ.get("OCOR_LIVE_SEAWEEDFS_URL", "http://127.0.0.1:18333")
ACCESS_KEY = "ocor-bootstrap-s3"  # deploy/bootstrap/compose.yaml, seaweedfs service
# The only retention of this module: COMPLIANCE, short, at most one hour.
TEST_RETENTION = timedelta(minutes=15)
# The dedicated C7 sealed-result test bucket of REM-0040, reused across runs.
BUCKET = "ocor-c7-sealed-results-test"
RUN_NONCE = uuid.uuid4().hex


@functools.cache
def _qualify() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ba06_seaweedfs_qualify", QUALIFY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _env_file() -> Path:
    candidates = []
    if os.environ.get("OCOR_BOOTSTRAP_ENV"):
        candidates.append(Path(os.environ["OCOR_BOOTSTRAP_ENV"]))
    candidates += [
        Path.home() / ".ocor-bootstrap-secrets" / "ocor-bootstrap.env",
        REPOSITORY_ROOT / ".ocor" / "bootstrap.env",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    pytest.fail("ocor-bootstrap env file not found; real SeaweedFS credentials are mandatory for BA-06")


def _secret() -> str:
    if os.environ.get("OCOR_LIVE_SEAWEEDFS_PASSWORD"):
        return os.environ["OCOR_LIVE_SEAWEEDFS_PASSWORD"]
    for line in _env_file().read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "OCOR_LOCAL_SEAWEEDFS_PASSWORD" and value:
            return value.strip()
    pytest.fail("OCOR_LOCAL_SEAWEEDFS_PASSWORD is absent from the ocor-bootstrap env file")


def _raw(method: str, path: str, *, body: bytes = b"", headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], str]:
    """Signed S3 request outside the adapter (REM-0038 qualification client): used only
    to provision the bucket and to observe or attack the store out of band."""
    try:
        status, response_headers, text = _qualify().request(
            method, URL + path, credential=(ACCESS_KEY, _secret()), body=body, headers=headers, timeout=30.0
        )
    except OSError as exc:
        pytest.fail(f"BA-06 requires the real SeaweedFS server at {URL} ({type(exc).__name__})")
    return int(status), dict(response_headers), str(text)


@pytest.fixture()
def sealed_store() -> SeaweedFSSealedResultStore:
    status, _, text = _raw("PUT", f"/{BUCKET}", headers={"x-amz-bucket-object-lock-enabled": "true"})
    assert status == 200 or (status == 409 and "BucketAlreadyOwnedByYou" in text), (status, text)
    store = SeaweedFSSealedResultStore(
        endpoint=URL, bucket=BUCKET, access_key=ACCESS_KEY, secret_key=_secret(), retention=TEST_RETENTION
    )
    try:
        store.initialize()
    except SealedResultError as exc:
        pytest.fail(f"BA-06 requires the real SeaweedFS Object Lock bucket: {exc.code}")
    assert isinstance(store, ScenarioOverlayStoreSealSubset)
    return store


def _versions(digest: str) -> list[str]:
    """Version ids of the digest key, newest first, read from the server."""
    key = object_key(digest)
    status, _, text = _raw("GET", f"/{BUCKET}?versions&prefix={urllib.parse.quote(key, safe='')}")
    assert status == 200, text
    return [
        block.split("<VersionId>", 1)[1].split("</VersionId>", 1)[0]
        for block in text.split("<Version>")[1:]
        if f"<Key>{key}</Key>" in block
    ]


def _version_bytes(digest: str, version_id: str) -> bytes:
    path = f"/{BUCKET}/{object_key(digest)}?versionId={urllib.parse.quote(version_id, safe='')}"
    status, _, text = _raw("GET", path)
    assert status == 200, text
    return text.encode("utf-8")


def _retention_mode(digest: str, version_id: str) -> str:
    path = f"/{BUCKET}/{object_key(digest)}?retention&versionId={urllib.parse.quote(version_id, safe='')}"
    status, _, text = _raw("GET", path)
    assert status == 200, text
    return text.split("<Mode>", 1)[1].split("</Mode>", 1)[0]


def _body(outcome: CausalOutcome) -> dict[str, Any]:
    return {
        "status": outcome.status,
        "reason_code": outcome.reason_code,
        "method": outcome.method,
        "effect": outcome.effect,
        "details": dict(outcome.details),
        "assumptions": list(outcome.assumptions),
        "lineage": dict(outcome.lineage),
    }


def _pins(label: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    model = {"graph": "treatment->outcome; stratum->treatment; stratum->outcome", "label": f"ba06-{label}"}
    rows = [
        {"stratum": "a", "treatment": 0, "outcome": 1.0},
        {"stratum": "a", "treatment": 1, "outcome": 3.0},
        {"stratum": "b", "treatment": 0, "outcome": 2.0},
        {"stratum": "b", "treatment": 1, "outcome": 5.0},
    ]
    return model, rows, {"value": 1, "valid_envelope": [0, 1]}


def _query(label: str, *, branch: str = "scenario/ba06", unresolved_confounding: bool = False) -> CausalQuery:
    model, rows, intervention = _pins(label)
    return CausalQuery(
        baseline_commit=f"ba06-baseline-{RUN_NONCE}",
        scenario_branch=branch,
        model_digest=canonical_digest(model),
        data_digest=canonical_digest(rows),
        intervention_digest=canonical_digest(intervention),
        ontology_release_digest="release-ba06",
        expected_release_digest="release-ba06",
        treatment="treatment",
        outcome="outcome",
        adjustment="stratum",
        seed=11,
        correlation_id=f"ba06-{RUN_NONCE}-{label}",
        causation_id=f"ba06-cause-{label}",
        unresolved_confounding=unresolved_confounding,
    )


def _run(
    label: str,
    *,
    branch: str = "scenario/ba06",
    unresolved_confounding: bool = False,
    estimator: Callable[..., CausalOutcome] = estimate_intervention,
) -> CausalOutcome:
    """A real CausalOutcome computed by the sealed c7/runtime.py, unique to this run."""
    model, rows, intervention = _pins(label)
    query = _query(label, branch=branch, unresolved_confounding=unresolved_confounding)
    return estimator(query, model=model, factual_rows=rows, intervention=intervention)


def _code(raiser: Callable[[], object]) -> str:
    with pytest.raises(SealedResultError) as caught:
        raiser()
    return caught.value.code


def _forged(outcome: CausalOutcome) -> bytes:
    return json.dumps({**_body(outcome), "effect": "999"}, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------- positive


def test_ba_06_positive_identified_result_is_sealed_immutably_with_lineage_and_reproduces(
    sealed_store: SeaweedFSSealedResultStore,
) -> None:
    outcome = _run("identified")
    assert outcome.status == "IDENTIFIED" and outcome.method == "STRATIFIED_BACKDOOR_ATE"
    before = datetime.now(UTC)
    receipt = sealed_store.seal_result(outcome)
    assert receipt.reproducibility_digest == outcome.reproducibility_digest and receipt.newly_sealed is True

    # The server holds exactly one version: the canonical preimage of the content address.
    [version] = _versions(outcome.reproducibility_digest)
    stored = _version_bytes(outcome.reproducibility_digest, version)
    assert stored == sealed_payload(outcome)
    assert hashlib.sha256(stored).hexdigest() == outcome.reproducibility_digest
    assert _retention_mode(outcome.reproducibility_digest, version) == "COMPLIANCE"
    path = f"/{BUCKET}/{object_key(outcome.reproducibility_digest)}?retention&versionId={urllib.parse.quote(version, safe='')}"
    until_text = _raw("GET", path)[2].split("<RetainUntilDate>", 1)[1][:19]
    until = datetime.strptime(until_text, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    assert before + TEST_RETENTION - timedelta(seconds=5) <= until <= datetime.now(UTC) + TEST_RETENTION + timedelta(seconds=5)

    # Read back through the port: causal result and lineage pins unchanged.
    read = sealed_store.read_sealed_result(outcome.reproducibility_digest)
    assert read == outcome
    query = _query("identified")
    assert dict(read.lineage) == {
        "baseline_commit": query.baseline_commit,
        "scenario_branch": "scenario/ba06",
        "model_digest": query.model_digest,
        "data_digest": query.data_digest,
        "intervention_digest": query.intervention_digest,
        "ontology_release_digest": "release-ba06",
        "seed": 11,
        "correlation_id": query.correlation_id,
        "causation_id": query.causation_id,
    }
    # Reproducibility: the same pins recompute the sealed result digest for digest.
    verify_reproduction(_run("identified"), read)

    # Idempotent re-seal: no new version is written.
    again = sealed_store.seal_result(outcome)
    assert again.newly_sealed is False and again.reproducibility_digest == outcome.reproducibility_digest
    assert _versions(outcome.reproducibility_digest) == [version]


def test_ba_06_positive_abstentions_are_sealed_and_isolated_from_scenario_results(
    sealed_store: SeaweedFSSealedResultStore,
) -> None:
    identified = _run("isolation")
    uncertainty = _run("isolation", estimator=estimate_uncertainty)
    on_main = _run("isolation", branch="main")
    confounded = _run("isolation", unresolved_confounding=True)
    assert (on_main.status, on_main.reason_code, on_main.effect) == ("ABSTAIN", "MAIN_CONTAMINATED", None)
    assert (confounded.status, confounded.reason_code, confounded.effect) == ("ABSTAIN", "UNRESOLVED_CONFOUNDING", None)
    outcomes = [identified, uncertainty, on_main, confounded]
    digests = [item.reproducibility_digest for item in outcomes]
    assert len(set(digests)) == len(outcomes)

    for outcome in outcomes:
        assert sealed_store.seal_result(outcome).newly_sealed is True
    for outcome in outcomes:
        read = sealed_store.read_sealed_result(outcome.reproducibility_digest)
        assert read == outcome
        assert dict(read.details) == dict(outcome.details) and read.assumptions == outcome.assumptions
        [version] = _versions(outcome.reproducibility_digest)
        assert _version_bytes(outcome.reproducibility_digest, version) == sealed_payload(outcome)
    # A main-branch query is sealed only as an abstention: no method, effect or assumption.
    sealed_main = sealed_store.read_sealed_result(on_main.reproducibility_digest)
    assert (sealed_main.method, sealed_main.assumptions) == (None, ())
    assert sealed_main.lineage["scenario_branch"] == "main"
    assert sealed_store.read_sealed_result(identified.reproducibility_digest).lineage["scenario_branch"] == "scenario/ba06"
    assert sealed_store.read_sealed_result(uncertainty.reproducibility_digest).details["resamples"] == "200"


# ---------------------------------------------------------------------------- negative


def test_ba_06_negative_delete_and_overwrite_after_seal_never_change_the_sealed_result(
    sealed_store: SeaweedFSSealedResultStore,
) -> None:
    outcome = _run("immutable")
    sealed_store.seal_result(outcome)
    [sealed_version] = _versions(outcome.reproducibility_digest)
    assert sealed_store.read_sealed_result(outcome.reproducibility_digest) == outcome  # positive control
    key = object_key(outcome.reproducibility_digest)
    version_path = f"/{BUCKET}/{key}?versionId={urllib.parse.quote(sealed_version, safe='')}"

    # The adapter has no delete on its application path.
    assert "DELETE" not in seaweedfs.ALLOWED_METHODS
    assert _code(lambda: sealed_store._request("DELETE", f"/{BUCKET}/{key}")) == "METHOD_FORBIDDEN"
    # Out of band: the server denies deleting the locked version, with and without bypass.
    assert _raw("DELETE", version_path)[0] == 403
    assert _raw("DELETE", version_path, headers={"x-amz-bypass-governance-retention": "true"})[0] == 403
    assert _versions(outcome.reproducibility_digest) == [sealed_version]

    # Out of band: an overwrite adds a version and a delete marker hides the latest, but
    # neither replaces nor hides the sealed version.
    assert _raw("PUT", f"/{BUCKET}/{key}", body=_forged(outcome))[0] == 200
    status, headers, _ = _raw("DELETE", f"/{BUCKET}/{key}")
    assert status == 204 and headers.get("x-amz-delete-marker") == "true"
    versions = _versions(outcome.reproducibility_digest)
    assert versions[-1] == sealed_version and len(versions) == 2
    assert _version_bytes(outcome.reproducibility_digest, sealed_version) == sealed_payload(outcome)
    assert _retention_mode(outcome.reproducibility_digest, sealed_version) == "COMPLIANCE"
    assert sealed_store.read_sealed_result(outcome.reproducibility_digest) == outcome
    assert sealed_store.seal_result(outcome).newly_sealed is False
    assert _versions(outcome.reproducibility_digest) == versions


def test_ba_06_negative_tampered_object_under_a_digest_key_is_rejected_on_read_and_seal(
    sealed_store: SeaweedFSSealedResultStore,
) -> None:
    control = _run("tamper-control")
    sealed_store.seal_result(control)
    assert sealed_store.read_sealed_result(control.reproducibility_digest) == control  # positive control

    outcome = _run("tampered")
    key = object_key(outcome.reproducibility_digest)
    forged = _forged(outcome)
    assert _raw("PUT", f"/{BUCKET}/{key}", body=forged)[0] == 200
    [forged_version] = _versions(outcome.reproducibility_digest)

    assert _code(lambda: sealed_store.read_sealed_result(outcome.reproducibility_digest)) == "SEALED_RESULT_TAMPERED"
    assert _code(lambda: sealed_store.seal_result(outcome)) == "SEALED_RESULT_CONFLICT"
    # Nothing was written by the refused seal; the forged bytes are untouched.
    assert _versions(outcome.reproducibility_digest) == [forged_version]
    assert _version_bytes(outcome.reproducibility_digest, forged_version) == forged


def test_ba_06_negative_different_content_under_a_sealed_digest_is_rejected(
    sealed_store: SeaweedFSSealedResultStore,
) -> None:
    outcome = _run("reseal")
    assert sealed_store.seal_result(outcome).newly_sealed is True  # positive control
    [version] = _versions(outcome.reproducibility_digest)

    for different in (
        replace(outcome, effect="999"),
        replace(outcome, lineage={**dict(outcome.lineage), "seed": 12}),
        replace(outcome, status="ABSTAIN", reason_code="UNRESOLVED_CONFOUNDING", method=None, effect=None),
    ):
        assert different.reproducibility_digest == outcome.reproducibility_digest
        assert _code(functools.partial(sealed_store.seal_result, different)) == "OUTCOME_DIGEST_MISMATCH"

    assert _versions(outcome.reproducibility_digest) == [version]
    assert _version_bytes(outcome.reproducibility_digest, version) == sealed_payload(outcome)
    assert sealed_store.read_sealed_result(outcome.reproducibility_digest) == outcome
