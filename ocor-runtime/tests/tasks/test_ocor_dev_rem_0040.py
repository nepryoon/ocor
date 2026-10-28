"""OCOR-DEV-REM-0040: SeaweedFS runtime adapter of C7 behind the sealResult sub-port.

Change set c. of the PO normative decision OCOR-DEV-0060-BA-SELECTED-COMPONENTS
(2026-10-26), placed by REM-0040-C7-SEALED-RESULT-PORT-DISPOSITION (2026-10-28),
option 1. A vendor-neutral ``Protocol`` reproduces only the ``sealResult`` operation
of the ``ScenarioOverlayStore`` port of ADD v1.3 §4.2 plus the read of a sealed result
by its digest; the overlay operations stay with OCOR-DEV-REM-0041. The SeaweedFS
adapter stores the canonical ``CausalOutcome`` under a key derived from its
``reproducibility_digest``, in a versioned bucket with S3 Object Lock and a
``COMPLIANCE`` retention, verifies the digest on every read and has no delete and no
retention bypass on its application path. ``c7/runtime.py``, ``CausalOutcome``,
contracts, schemas and reason codes are unchanged.

The live cases run against the real, digest-pinned SeaweedFS server of the
``ocor-bootstrap`` stack, in one dedicated bucket reused across runs (a bucket per run
would exhaust the SeaweedFS volume slots); every case derives fresh digests from a
per-run nonce and never depends on the absence of objects sealed by earlier runs. An
unavailable server fails, it never skips.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import threading
import urllib.parse
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ocor_runtime.c7 import runtime as c7_runtime
from ocor_runtime.c7.runtime import CausalOutcome, CausalQuery, canonical_digest, estimate_intervention

RUNTIME_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = RUNTIME_ROOT.parent
PORT = "ocor_runtime.c7.sealed_results"
ADAPTER = "ocor_runtime.c7.adapters.seaweedfs"
PORT_PATH = RUNTIME_ROOT / "src/ocor_runtime/c7/sealed_results.py"
ADAPTER_PATH = RUNTIME_ROOT / "src/ocor_runtime/c7/adapters/seaweedfs.py"
C7_RUNTIME_PATH = RUNTIME_ROOT / "src/ocor_runtime/c7/runtime.py"
# c7/runtime.py as sealed by OCOR-DEV-0045 (REM-0040-C7-SEALED-RESULT-PORT, Fatti).
C7_RUNTIME_SHA256 = "618296ae3e490cb2170f1f330a7cc1e3a821795791203d5bfc88c194b32ce118"
QUALIFY_PATH = REPOSITORY_ROOT / "deploy/bootstrap/services/seaweedfs/qualify.py"
URL = os.environ.get("OCOR_LIVE_SEAWEEDFS_URL", "http://127.0.0.1:18333")
ACCESS_KEY = "ocor-bootstrap-s3"  # deploy/bootstrap/compose.yaml, seaweedfs service
# The only retention of these tests (REM-0040 disposition point 4): COMPLIANCE, short,
# at most one hour like the REM-0038 probe. Production retention is not decided here.
TEST_RETENTION = timedelta(minutes=15)
LOCKED_BUCKET = "ocor-c7-sealed-results-test"
UNLOCKED_BUCKET = "ocor-c7-sealed-results-unlocked-test"
CLOSED_ENDPOINT = "http://127.0.0.1:9"
WRONG_SECRET = "rem0040-deliberately-wrong-secret-value"
RUN_NONCE = uuid.uuid4().hex


def _port_module() -> ModuleType:
    return importlib.import_module(PORT)


def _adapter_module() -> ModuleType:
    return importlib.import_module(ADAPTER)


@functools.cache
def _qualify() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rem0040_seaweedfs_qualify", QUALIFY_PATH)
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
    pytest.fail("ocor-bootstrap env file not found; real SeaweedFS credentials are mandatory qualifying evidence")


def _secret() -> str:
    if os.environ.get("OCOR_LIVE_SEAWEEDFS_PASSWORD"):
        return os.environ["OCOR_LIVE_SEAWEEDFS_PASSWORD"]
    for line in _env_file().read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "OCOR_LOCAL_SEAWEEDFS_PASSWORD" and value:
            return value.strip()
    pytest.fail("OCOR_LOCAL_SEAWEEDFS_PASSWORD is absent from the ocor-bootstrap env file")


def _raw(method: str, path: str, *, body: bytes = b"", headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], str]:
    """Signed S3 request outside the adapter (the REM-0038 qualification client), used
    only to provision the test buckets and to observe or attack the store out of band."""
    status, response_headers, text = _qualify().request(
        method, URL + path, credential=(ACCESS_KEY, _secret()), body=body, headers=headers, timeout=30.0
    )
    return int(status), dict(response_headers), str(text)


def _ensure_bucket(bucket: str, *, object_lock: bool) -> None:
    headers = {"x-amz-bucket-object-lock-enabled": "true"} if object_lock else None
    status, _, text = _raw("PUT", f"/{bucket}", headers=headers)
    assert status == 200 or (status == 409 and "BucketAlreadyOwnedByYou" in text), (status, text)


def _object_key(digest: str) -> str:
    key: str = _adapter_module().object_key(digest)
    return key


def _versions(digest: str) -> list[str]:
    key = _object_key(digest)
    status, _, text = _raw("GET", f"/{LOCKED_BUCKET}?versions&prefix={urllib.parse.quote(key, safe='')}")
    assert status == 200, text
    versions = []
    for block in text.split("<Version>")[1:]:
        if f"<Key>{key}</Key>" in block:
            versions.append(block.split("<VersionId>", 1)[1].split("</VersionId>", 1)[0])
    return versions


def _version_bytes(digest: str, version_id: str) -> bytes:
    path = f"/{LOCKED_BUCKET}/{_object_key(digest)}?versionId={urllib.parse.quote(version_id, safe='')}"
    status, _, text = _raw("GET", path)
    assert status == 200, text
    return text.encode("utf-8")


def _outcome(label: str, *, abstain: bool = False) -> CausalOutcome:
    """A real CausalOutcome computed by the sealed c7/runtime.py, unique to this run."""
    model = {"graph": "treatment->outcome; stratum->treatment; stratum->outcome", "label": label}
    rows = [
        {"stratum": "a", "treatment": 0, "outcome": 1.0},
        {"stratum": "a", "treatment": 1, "outcome": 3.0},
        {"stratum": "b", "treatment": 0, "outcome": 2.0},
        {"stratum": "b", "treatment": 1, "outcome": 5.0},
    ]
    intervention = {"value": 1, "valid_envelope": [0, 1]}
    query = CausalQuery(
        baseline_commit="rem0040-baseline",
        scenario_branch="main" if abstain else "scenario/rem0040",
        model_digest=canonical_digest(model),
        data_digest=canonical_digest(rows),
        intervention_digest=canonical_digest(intervention),
        ontology_release_digest="release-1",
        expected_release_digest="release-1",
        treatment="treatment",
        outcome="outcome",
        adjustment="stratum",
        seed=7,
        correlation_id=f"rem0040-{RUN_NONCE}-{label}",
        causation_id=f"rem0040-{label}",
    )
    return estimate_intervention(query, model=model, factual_rows=rows, intervention=intervention)


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


def _store(*, bucket: str = LOCKED_BUCKET, endpoint: str = URL, access_key: str = ACCESS_KEY, secret: str | None = None) -> Any:
    store = _adapter_module().SeaweedFSSealedResultStore(
        endpoint=endpoint,
        bucket=bucket,
        access_key=access_key,
        secret_key=_secret() if secret is None else secret,
        retention=TEST_RETENTION,
    )
    return store


@pytest.fixture()
def store() -> Any:
    _ensure_bucket(LOCKED_BUCKET, object_lock=True)
    instance = _store()
    instance.initialize()
    return instance


def _code(raiser: Callable[[], object]) -> str:
    with pytest.raises(_port_module().SealedResultError) as caught:
        raiser()
    code: str = caught.value.code
    return code


# --- port and placement -------------------------------------------------------------


def test_the_port_is_the_declared_seal_subset_of_scenario_overlay_store() -> None:
    port = _port_module()
    protocol = port.ScenarioOverlayStoreSealSubset
    assert getattr(protocol, "_is_protocol", False) is True
    doc = inspect.getdoc(protocol) or ""
    assert "subset of ``ScenarioOverlayStore``" in doc and "ADD v1.3 §4.2" in doc and "sealResult" in doc
    assert "OCOR-DEV-REM-0041" in doc
    members = {name for name, value in vars(protocol).items() if callable(value) and not name.startswith("_")}
    assert members == {"seal_result", "read_sealed_result"}
    seal = inspect.signature(protocol.seal_result)
    read = inspect.signature(protocol.read_sealed_result)
    assert list(seal.parameters) == ["self", "outcome"] and seal.return_annotation in {"SealedResult", port.SealedResult}
    assert list(read.parameters) == ["self", "reproducibility_digest"]
    assert read.return_annotation in {"CausalOutcome", CausalOutcome}
    # Composable unchanged into the full ScenarioOverlayStore of REM-0041.
    assert isinstance(_store(), protocol)


def test_c7_runtime_and_causal_outcome_are_unchanged() -> None:
    assert hashlib.sha256(C7_RUNTIME_PATH.read_bytes()).hexdigest() == C7_RUNTIME_SHA256
    assert c7_runtime.CausalOutcome is CausalOutcome


def test_the_application_path_has_no_delete_and_no_retention_bypass() -> None:
    for path in (PORT_PATH, ADAPTER_PATH):
        source = path.read_text(encoding="utf-8")
        lowered = source.lower()
        assert "bypass-governance" not in lowered and "deleteobject" not in lowered
        tree = ast.parse(source)
        strings = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        assert "DELETE" not in strings and "POST" not in strings
    assert _adapter_module().ALLOWED_METHODS == frozenset({"GET", "PUT"})


def test_direct_backend_access_is_confined_to_the_adapters_subtree_and_uses_only_the_standard_library() -> None:
    port_tree = ast.parse(PORT_PATH.read_text(encoding="utf-8"))
    port_imports = {
        alias.name.split(".")[0] for node in ast.walk(port_tree) if isinstance(node, ast.Import) for alias in node.names
    } | {node.module.split(".")[0] for node in ast.walk(port_tree) if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
    assert not port_imports & {"urllib", "http", "socket", "hmac"}
    tree = ast.parse(ADAPTER_PATH.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
    import sys

    assert imported <= set(sys.stdlib_module_names) | {"__future__"}
    lock = (RUNTIME_ROOT / "uv.lock").read_text(encoding="utf-8").lower()
    assert "boto" not in lock and "minio" not in lock and "s3transfer" not in lock


def test_configuration_is_fail_closed() -> None:
    adapter = _adapter_module()
    for kwargs, field in (
        ({"retention": timedelta(0)}, "retention"),
        ({"retention": timedelta(days=-1)}, "retention"),
        ({"bucket": "Not_A_Bucket"}, "bucket"),
        ({"endpoint": "ftp://127.0.0.1:18333"}, "endpoint"),
        ({"access_key": ""}, "access_key"),
        ({"secret_key": ""}, "secret_key"),
    ):
        arguments: dict[str, Any] = {
            "endpoint": URL, "bucket": LOCKED_BUCKET, "access_key": ACCESS_KEY,
            "secret_key": "offline-synthetic-secret", "retention": TEST_RETENTION,
        }
        arguments.update(kwargs)
        with pytest.raises(_port_module().SealedResultError) as caught:
            adapter.SeaweedFSSealedResultStore(**arguments)
        assert caught.value.code == "CONFIGURATION_INVALID" and field in str(caught.value)
    uninitialized = adapter.SeaweedFSSealedResultStore(
        endpoint=URL, bucket=LOCKED_BUCKET, access_key=ACCESS_KEY, secret_key="offline-synthetic-secret", retention=TEST_RETENTION
    )
    assert _code(lambda: uninitialized.seal_result(_outcome("uninitialized"))) == "STORE_NOT_INITIALIZED"
    assert _code(lambda: uninitialized.read_sealed_result("0" * 64)) == "STORE_NOT_INITIALIZED"
    assert "offline-synthetic-secret" not in repr(uninitialized)


def test_a_malformed_digest_is_rejected_before_any_request(store: Any) -> None:
    for digest in ("", "A" * 64, "0" * 63, "urn:sha256:" + "0" * 64, "../" + "0" * 61):
        assert _code(lambda digest=digest: store.read_sealed_result(digest)) == "INVALID_DIGEST"


# --- canonical serialization (disposition point 5) ----------------------------------


def test_the_sealed_bytes_are_the_canonical_preimage_of_the_reproducibility_digest(store: Any) -> None:
    outcome = _outcome("canonical")
    payload = _adapter_module().sealed_payload(outcome)
    assert hashlib.sha256(payload).hexdigest() == outcome.reproducibility_digest == canonical_digest(_body(outcome))
    first = store.seal_result(outcome)
    second = store.seal_result(outcome)
    assert first.reproducibility_digest == second.reproducibility_digest == outcome.reproducibility_digest
    versions = _versions(outcome.reproducibility_digest)
    assert len(versions) == 1
    stored = _version_bytes(outcome.reproducibility_digest, versions[0])
    assert stored == payload == _adapter_module().sealed_payload(outcome)
    read = store.read_sealed_result(outcome.reproducibility_digest)
    assert canonical_digest(_body(read)) == outcome.reproducibility_digest


def test_an_outcome_whose_digest_does_not_match_its_content_is_never_written(store: Any) -> None:
    outcome = _outcome("forged-digest")
    forged = replace(outcome, effect="999")
    assert _code(lambda: store.seal_result(forged)) == "OUTCOME_DIGEST_MISMATCH"
    assert _versions(outcome.reproducibility_digest) == []


# --- live behaviour on the real SeaweedFS -------------------------------------------


def test_seal_and_read_round_trip_an_identified_and_an_abstained_outcome(store: Any) -> None:
    for outcome in (_outcome("round-trip"), _outcome("round-trip-abstain", abstain=True)):
        receipt = store.seal_result(outcome)
        assert receipt.reproducibility_digest == outcome.reproducibility_digest and receipt.newly_sealed is True
        read = store.read_sealed_result(outcome.reproducibility_digest)
        assert read == outcome
        assert dict(read.details) == dict(outcome.details) and dict(read.lineage) == dict(outcome.lineage)
        c7_runtime.verify_reproduction(outcome, read)
    assert store.read_sealed_result(_outcome("round-trip-abstain", abstain=True).reproducibility_digest).reason_code == "MAIN_CONTAMINATED"


def test_the_sealed_version_carries_a_compliance_retention_in_a_versioned_object_lock_bucket(store: Any) -> None:
    outcome = _outcome("retention")
    before = datetime.now(UTC)
    store.seal_result(outcome)
    [version] = _versions(outcome.reproducibility_digest)
    key = _object_key(outcome.reproducibility_digest)
    status, _, text = _raw("GET", f"/{LOCKED_BUCKET}/{key}?retention&versionId={urllib.parse.quote(version, safe='')}")
    assert status == 200 and "<Mode>COMPLIANCE</Mode>" in text, text
    until = datetime.strptime(text.split("<RetainUntilDate>", 1)[1].split("</RetainUntilDate>", 1)[0][:19], "%Y-%m-%dT%H:%M:%S")
    until = until.replace(tzinfo=UTC)
    assert before + TEST_RETENTION - timedelta(seconds=5) <= until <= datetime.now(UTC) + TEST_RETENTION + timedelta(seconds=5)
    assert "<Status>Enabled</Status>" in _raw("GET", f"/{LOCKED_BUCKET}?versioning")[2]
    assert "<ObjectLockEnabled>Enabled</ObjectLockEnabled>" in _raw("GET", f"/{LOCKED_BUCKET}?object-lock")[2]


def test_a_second_seal_of_the_same_result_is_idempotent_and_writes_no_new_version(store: Any) -> None:
    outcome = _outcome("idempotent")
    assert store.seal_result(outcome).newly_sealed is True
    again = store.seal_result(outcome)
    assert again.newly_sealed is False and again.reproducibility_digest == outcome.reproducibility_digest
    assert len(_versions(outcome.reproducibility_digest)) == 1


def test_concurrent_seals_of_the_same_result_all_succeed_with_identical_bytes(store: Any) -> None:
    outcome = _outcome("concurrent")
    results: list[Any] = []
    errors: list[BaseException] = []

    def seal() -> None:
        try:
            results.append(store.seal_result(outcome))
        except BaseException as error:  # noqa: BLE001 - collected and asserted below
            errors.append(error)

    threads = [threading.Thread(target=seal) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert errors == [] and len(results) == 6
    assert sum(1 for result in results if result.newly_sealed) >= 1
    payload = _adapter_module().sealed_payload(outcome)
    versions = _versions(outcome.reproducibility_digest)
    assert versions and all(_version_bytes(outcome.reproducibility_digest, version) == payload for version in versions)
    assert store.read_sealed_result(outcome.reproducibility_digest) == outcome


def test_deleting_the_sealed_version_is_denied_with_and_without_the_bypass_header(store: Any) -> None:
    outcome = _outcome("delete")
    store.seal_result(outcome)
    [version] = _versions(outcome.reproducibility_digest)
    path = f"/{LOCKED_BUCKET}/{_object_key(outcome.reproducibility_digest)}?versionId={urllib.parse.quote(version, safe='')}"
    assert _raw("DELETE", path)[0] == 403
    assert _raw("DELETE", path, headers={"x-amz-bypass-governance-retention": "true"})[0] == 403
    assert _versions(outcome.reproducibility_digest) == [version]
    assert store.read_sealed_result(outcome.reproducibility_digest) == outcome


def test_a_delete_marker_does_not_hide_the_sealed_result(store: Any) -> None:
    outcome = _outcome("delete-marker")
    store.seal_result(outcome)
    status, headers, _ = _raw("DELETE", f"/{LOCKED_BUCKET}/{_object_key(outcome.reproducibility_digest)}")
    assert status == 204 and headers.get("x-amz-delete-marker") == "true"
    assert store.read_sealed_result(outcome.reproducibility_digest) == outcome
    assert store.seal_result(outcome).newly_sealed is False


def test_an_overwrite_never_replaces_the_sealed_version(store: Any) -> None:
    outcome = _outcome("overwrite")
    store.seal_result(outcome)
    [sealed_version] = _versions(outcome.reproducibility_digest)
    key = _object_key(outcome.reproducibility_digest)
    forged = json.dumps({**_body(outcome), "effect": "999"}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert _raw("PUT", f"/{LOCKED_BUCKET}/{key}", body=forged)[0] == 200
    assert _version_bytes(outcome.reproducibility_digest, sealed_version) == _adapter_module().sealed_payload(outcome)
    assert store.read_sealed_result(outcome.reproducibility_digest) == outcome
    assert store.seal_result(outcome).newly_sealed is False


def test_a_tampered_object_under_a_digest_key_is_rejected_on_read_and_on_seal(store: Any) -> None:
    outcome = _outcome("tampered")
    key = _object_key(outcome.reproducibility_digest)
    forged = json.dumps({**_body(outcome), "effect": "999"}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert _raw("PUT", f"/{LOCKED_BUCKET}/{key}", body=forged)[0] == 200
    assert _code(lambda: store.read_sealed_result(outcome.reproducibility_digest)) == "SEALED_RESULT_TAMPERED"
    assert _code(lambda: store.seal_result(outcome)) == "SEALED_RESULT_CONFLICT"


def test_an_unknown_digest_is_not_found(store: Any) -> None:
    digest = hashlib.sha256(f"rem0040-absent-{RUN_NONCE}".encode()).hexdigest()
    assert _code(lambda: store.read_sealed_result(digest)) == "SEALED_RESULT_NOT_FOUND"


def test_a_bucket_without_object_lock_is_refused_at_startup() -> None:
    _ensure_bucket(UNLOCKED_BUCKET, object_lock=False)
    assert _code(lambda: _store(bucket=UNLOCKED_BUCKET).initialize()) == "BUCKET_OBJECT_LOCK_DISABLED"
    assert _code(lambda: _store(bucket=f"ocor-absent-{RUN_NONCE[:12]}").initialize()) == "BUCKET_NOT_FOUND"


def test_a_wrong_secret_and_a_wrong_access_key_are_rejected_by_the_server_without_leaking_credentials() -> None:
    _ensure_bucket(LOCKED_BUCKET, object_lock=True)
    for kwargs in ({"secret": WRONG_SECRET}, {"access_key": f"rem0040-unknown-{RUN_NONCE[:8]}"}):
        candidate = _store(**kwargs)
        with pytest.raises(_port_module().SealedResultError) as caught:
            candidate.initialize()
        assert caught.value.code == "ACCESS_DENIED"
        rendered = f"{caught.value}|{caught.value!r}|{candidate!r}"
        assert WRONG_SECRET not in rendered and _secret() not in rendered


def test_a_corrupted_signature_is_rejected_by_the_server() -> None:
    qualify = _qualify()
    url = f"{URL}/{LOCKED_BUCKET}?versioning"
    headers = qualify.sign("GET", url, ACCESS_KEY, _secret(), now=datetime.now(UTC))
    signature = headers["authorization"].rsplit("Signature=", 1)[1]
    flipped = ("0" if signature[0] != "0" else "1") + signature[1:]
    headers["authorization"] = headers["authorization"].replace(f"Signature={signature}", f"Signature={flipped}")
    headers.pop("host")
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, method="GET", headers=headers)
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=10)
    assert caught.value.code == 403


def test_an_unreachable_store_fails_closed_without_fallback() -> None:
    unreachable = _store(endpoint=CLOSED_ENDPOINT, secret="offline-synthetic-secret")
    with pytest.raises(_port_module().SealedResultError) as caught:
        unreachable.initialize()
    assert caught.value.code == "STORE_UNAVAILABLE" and "offline-synthetic-secret" not in str(caught.value)
