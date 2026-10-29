"""OCOR-DEV-REM-0041, overlay unit: the complete ``ScenarioOverlayStore`` of C7.

Change set d. of the PO normative decision OCOR-DEV-0060-BA-SELECTED-COMPONENTS
(2026-10-26), with REM-0040-C7-SEALED-RESULT-PORT-DISPOSITION (2026-10-28), points 1,
3 and 9: the overlay operations of the ``ScenarioOverlayStore`` port of ADD v1.3 §4.2
(``openSnapshot``, ``forkScenario``, ``appendOverlay``, ``readAt``, ``discard``) on
TerminusDB scenario branches (ADD v1.3 Part I §2.4, ``VersionedAssertedState`` row),
composing the ``sealResult`` subset of OCOR-DEV-REM-0040 without renaming it or
changing its signatures. The overlay store has no ``main.write`` capability, mounts
the baseline read-only, keeps every hypothesis as an append-only delta isolated per
``(scenario_id, run_id, compartments)``, and never makes a forked ``OutboxEntry``
publishable (§2.5 rule 11).

The live cases run against the real, digest-pinned TerminusDB and SeaweedFS servers
of the ``ocor-bootstrap`` stack. Each TerminusDB case uses its own disposable canonical
database, initialized by the sealed C3 TerminusDB service and deleted at teardown;
sealed results go to the dedicated SeaweedFS bucket that OCOR-DEV-REM-0040 reuses
across runs, under digests unique to this run. An unavailable server fails, it never
skips.
"""

from __future__ import annotations

import ast
import base64
import functools
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ocor_runtime.c3.ports import GovernedCanonicalCommitCommand
from ocor_runtime.c3.terminusdb_service import TerminusDBC3Service
from ocor_runtime.c7.runtime import CausalOutcome, CausalQuery, canonical_digest, estimate_intervention
from ocor_runtime.kernel.governed_context import GovernedContext

RUNTIME_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = RUNTIME_ROOT.parent
PORT = "ocor_runtime.c7.scenario_overlay"
SUBSET = "ocor_runtime.c7.sealed_results"
ADAPTER = "ocor_runtime.c7.adapters.terminusdb_overlay"
SEAWEEDFS = "ocor_runtime.c7.adapters.seaweedfs"
PORT_PATH = RUNTIME_ROOT / "src/ocor_runtime/c7/scenario_overlay.py"
ADAPTER_PATH = RUNTIME_ROOT / "src/ocor_runtime/c7/adapters/terminusdb_overlay.py"
# Sealed inputs this unit composes or relies on and must not change: the sealResult
# subset and SeaweedFS adapter (OCOR-DEV-REM-0040 record inputs), c7/runtime.py
# (OCOR-DEV-0045), the C3 TerminusDB adapter and service (OCOR-DEV-REM-0041 C3 unit).
SEALED_SHA256 = {
    "src/ocor_runtime/c7/sealed_results.py": "ee45cd53f136c7f859a03c004d470be04367c0fab1ed0ffff86e64b2aedeba74",
    "src/ocor_runtime/c7/adapters/seaweedfs.py": "f81a4a0bc5b964be010c1d25f41d319443199eeeef8673b018bb7ece25f7c7dc",
    "src/ocor_runtime/c7/runtime.py": "618296ae3e490cb2170f1f330a7cc1e3a821795791203d5bfc88c194b32ce118",
    "src/ocor_runtime/c3/adapters/terminusdb.py": "d36e5e2e868f4cadf6e58db6669b2d74c095e16e43a450afd64956ff80d919d1",
    "src/ocor_runtime/c3/terminusdb_service.py": "984d29c4aecd224faeceaffdeb22290313de48f52869d113e20f34a663bec7b1",
}
TERMINUSDB_URL = os.environ.get("OCOR_LIVE_TERMINUSDB_URL", "http://127.0.0.1:6363")
SEAWEEDFS_URL = os.environ.get("OCOR_LIVE_SEAWEEDFS_URL", "http://127.0.0.1:18333")
QUALIFY_PATH = REPOSITORY_ROOT / "deploy/bootstrap/services/seaweedfs/qualify.py"
ACCESS_KEY = "ocor-bootstrap-s3"  # deploy/bootstrap/compose.yaml, seaweedfs service
# The dedicated bucket and short COMPLIANCE retention of OCOR-DEV-REM-0040 (its
# disposition point 4), reused here; production retention is not decided here.
TEST_RETENTION = timedelta(minutes=15)
LOCKED_BUCKET = "ocor-c7-sealed-results-test"
CLOSED_ENDPOINT = "http://127.0.0.1:9"
SYNTHETIC_SECRET = "rem0041-overlay-offline-synthetic"  # never sent: the endpoint is closed
TENANT = "urn:ocor:tenant:synthetic"
AGGREGATE_TYPE = "MissionObject"
AGGREGATE_REF = "urn:ocor:mission-object:rem0041-overlay:1"
DIGEST_A = "urn:sha256:" + "a" * 64
DIGEST_B = "urn:sha256:" + "b" * 64
DIGEST_C = "urn:sha256:" + "c" * 64
DIGEST_D = "urn:sha256:" + "d" * 64
COMPARTMENTS = ("urn:ocor:compartment:alpha", "urn:ocor:compartment:bravo")
RUN_NONCE = uuid.uuid4().hex


def _port() -> ModuleType:
    return importlib.import_module(PORT)


def _subset() -> ModuleType:
    return importlib.import_module(SUBSET)


def _adapter() -> ModuleType:
    return importlib.import_module(ADAPTER)


@functools.cache
def _qualify() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rem0041_overlay_seaweedfs_qualify", QUALIFY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _env_value(name: str, override: str) -> str:
    if os.environ.get(override):
        return os.environ[override]
    candidates = []
    if os.environ.get("OCOR_BOOTSTRAP_ENV"):
        candidates.append(Path(os.environ["OCOR_BOOTSTRAP_ENV"]))
    candidates += [
        Path.home() / ".ocor-bootstrap-secrets" / "ocor-bootstrap.env",
        REPOSITORY_ROOT / ".ocor" / "bootstrap.env",
    ]
    for candidate in candidates:
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip() == name and value:
                    return value.strip()
            pytest.fail(f"{name} is absent from the ocor-bootstrap env file")
    pytest.fail("ocor-bootstrap env file not found; real backend credentials are mandatory qualifying evidence")


def _raw(method: str, path: str, password: str, body: object | None = None) -> tuple[int, Any, str]:
    """Direct HTTP to the live TerminusDB server, used only to observe or tamper with
    the store out of band (never through the adapter under test)."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(TERMINUSDB_URL + path, data=data, method=method)
    request.add_header("Authorization", "Basic " + base64.b64encode(f"admin:{password}".encode()).decode())
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, text = response.status, response.read().decode()
            version = response.headers.get("TerminusDB-Data-Version", "")
    except urllib.error.HTTPError as error:
        status, text, version = error.code, error.read().decode(), ""
    try:
        parsed: Any = json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        parsed = [json.loads(line) for line in text.splitlines() if line.strip()]
    return status, parsed, version


def _documents(password: str, database: str, doc_type: str, *, branch: str = "main") -> list[dict[str, Any]]:
    status, body, _ = _raw("GET", f"/api/document/admin/{database}/local/branch/{branch}?type={doc_type}&as_list=true", password)
    assert status == 200, body
    assert isinstance(body, list)
    return body


def _main_log(password: str, database: str) -> list[str]:
    status, body, _ = _raw("GET", f"/api/log/admin/{database}?count=1000", password)
    assert status == 200, body
    return [entry["identifier"] for entry in body]


def _main_state(password: str, database: str) -> dict[str, Any]:
    """Everything a C7 write to ``main`` could change: its log, schema and documents."""
    status, schema, _ = _raw("GET", f"/api/document/admin/{database}?graph_type=schema&as_list=true", password)
    assert status == 200, schema
    status, instance, _ = _raw("GET", f"/api/document/admin/{database}/local/branch/main?as_list=true", password)
    assert status == 200, instance
    return {"log": _main_log(password, database), "schema": schema, "instance": instance}


def _branches(password: str, database: str) -> set[str]:
    status, body, _ = _raw("GET", f"/api/db/admin/{database}?branches=true", password)
    assert status == 200, body
    return set(body["branches"])


def _databases(password: str) -> set[str]:
    status, body, _ = _raw("GET", "/api/db", password)
    assert status == 200, body
    return {entry["path"].split("/")[-1] for entry in body}


@pytest.fixture(scope="module")
def password() -> str:
    value = _env_value("OCOR_LOCAL_TERMINUSDB_PASSWORD", "OCOR_LIVE_TERMINUSDB_PASSWORD")
    try:
        _databases(value)
    except (urllib.error.URLError, OSError) as error:
        pytest.fail(f"a real, live TerminusDB server is mandatory qualifying evidence: {error}")
    return value


@pytest.fixture
def database(password: str) -> Iterator[str]:
    name = f"ocor_c7_rem0041_{uuid.uuid4().hex[:12]}"
    try:
        yield name
    finally:
        _raw("DELETE", f"/api/db/admin/{name}", password)
        assert name not in _databases(password), "disposable canonical database left behind"


@pytest.fixture
def canonical(password: str, database: str) -> TerminusDBC3Service:
    """The sealed C3 TerminusDB service owns ``main`` of the disposable database."""
    value = TerminusDBC3Service(url=TERMINUSDB_URL, password=password, database=database)
    value.initialize()
    return value


@functools.cache
def _seaweedfs_secret() -> str:
    return _env_value("OCOR_LOCAL_SEAWEEDFS_PASSWORD", "OCOR_LIVE_SEAWEEDFS_PASSWORD")


@pytest.fixture(scope="module")
def sealed_results() -> Any:
    status, _, text = _qualify().request(
        "PUT",
        f"{SEAWEEDFS_URL}/{LOCKED_BUCKET}",
        credential=(ACCESS_KEY, _seaweedfs_secret()),
        body=b"",
        headers={"x-amz-bucket-object-lock-enabled": "true"},
        timeout=30.0,
    )
    assert int(status) == 200 or (int(status) == 409 and "BucketAlreadyOwnedByYou" in str(text)), (status, text)
    store = importlib.import_module(SEAWEEDFS).SeaweedFSSealedResultStore(
        endpoint=SEAWEEDFS_URL, bucket=LOCKED_BUCKET, access_key=ACCESS_KEY, secret_key=_seaweedfs_secret(), retention=TEST_RETENTION
    )
    store.initialize()
    return store


class _OfflineSealSubset:
    """A structural ``ScenarioOverlayStoreSealSubset`` for the offline cases, which
    never reach a seal operation."""

    def seal_result(self, outcome: CausalOutcome) -> Any:
        raise AssertionError("not reached")

    def read_sealed_result(self, reproducibility_digest: str) -> CausalOutcome:
        raise AssertionError("not reached")


def _store(database: str, *, password: str | None = None, url: str = TERMINUSDB_URL, sealed: Any = None) -> Any:
    return _adapter().TerminusDBScenarioOverlayStore(
        url=url,
        password=SYNTHETIC_SECRET if password is None else password,
        database=database,
        sealed_results=_OfflineSealSubset() if sealed is None else sealed,
    )


@pytest.fixture
def overlay(password: str, database: str, canonical: TerminusDBC3Service, sealed_results: Any) -> Any:
    store = _store(database, password=password, sealed=sealed_results)
    store.initialize()
    return store


def _command(*, expected_revision: int, delta: dict[str, object], key: str) -> GovernedCanonicalCommitCommand:
    context = GovernedContext.from_mapping(
        {
            "tenant_id": TENANT,
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": list(COMPARTMENTS),
            "classification_marking_ref": DIGEST_A,
            "purpose": "rem0041-scenario-overlay",
            "effective_principal_id": "urn:ocor:principal:analyst-1",
            "actor_chain": ["urn:ocor:principal:analyst-1"],
            "ontology_release_digest": DIGEST_B,
            "policy_bundle_digest": DIGEST_C,
            "correlation_id": "018f2f95-01b2-7cc3-8d4e-1234567890ab",
        }
    )
    command_id = f"urn:ocor:command:rem0041-overlay:{key}"
    return GovernedCanonicalCommitCommand.from_mapping(
        {
            "command_id": command_id,
            "action_instance_id": command_id.replace("command", "action"),
            "aggregate_type": AGGREGATE_TYPE,
            "aggregate_ref": AGGREGATE_REF,
            "expected_revision": expected_revision,
            "canonical_delta": delta,
            "decision_ref": "urn:ocor:decision:rem0041-overlay:1",
            "authority_ref": "urn:ocor:authority:rem0041-overlay:1",
            "evidence_refs": ["urn:ocor:evidence:rem0041-overlay:1"],
            "claim_source_bindings": [
                {
                    "claim_ref": "urn:ocor:claim:rem0041-overlay:1",
                    "source_ref": "urn:ocor:source:rem0041-overlay:1",
                    "evidence_ref": "urn:ocor:evidence:rem0041-overlay:1",
                }
            ],
            "precondition_bindings": [f"urn:ocor:precondition:revision-{expected_revision}"],
            "invariant_bindings": ["urn:ocor:invariant:atomic-outbox"],
            "idempotency_key": f"rem0041-overlay-key-{key}",
            "governed_context": context.to_mapping(),
            "governed_context_digest": context.digest(),
            "gate_package_digest": DIGEST_D,
            "branch": "main",
        }
    )


def _code(raiser: Callable[[], object]) -> str:
    with pytest.raises(_port().ScenarioOverlayError) as caught:
        raiser()
    code: str = caught.value.code
    return code


def _fork(overlay: Any, *, run_id: str = "run-1", compartments: tuple[str, ...] = COMPARTMENTS, ref: str | None = None) -> Any:
    snapshot = overlay.open_snapshot(overlay.current_canonical_commit() if ref is None else ref)
    return overlay.fork_scenario(snapshot, scenario_id="urn:ocor:scenario:rem0041", run_id=run_id, compartments=compartments)


def _terminus_branch(branch: Any) -> str:
    return "scenario_" + str(branch.scenario_branch).removeprefix("scenario/")


def _outcome(branch: Any, label: str) -> CausalOutcome:
    """A real CausalOutcome computed by the sealed c7/runtime.py on the overlay's own
    scenario branch and baseline commit, unique to this run."""
    model = {"graph": "treatment->outcome; stratum->treatment; stratum->outcome", "label": label}
    rows = [
        {"stratum": "a", "treatment": 0, "outcome": 1.0},
        {"stratum": "a", "treatment": 1, "outcome": 3.0},
        {"stratum": "b", "treatment": 0, "outcome": 2.0},
        {"stratum": "b", "treatment": 1, "outcome": 5.0},
    ]
    intervention = {"value": 1, "valid_envelope": [0, 1]}
    query = CausalQuery(
        baseline_commit=branch.canonical_commit_ref,
        scenario_branch=branch.scenario_branch,
        model_digest=canonical_digest(model),
        data_digest=canonical_digest(rows),
        intervention_digest=canonical_digest(intervention),
        ontology_release_digest="release-1",
        expected_release_digest="release-1",
        treatment="treatment",
        outcome="outcome",
        adjustment="stratum",
        seed=7,
        correlation_id=f"rem0041-overlay-{RUN_NONCE}-{label}",
        causation_id=f"rem0041-overlay-{label}",
    )
    return estimate_intervention(query, model=model, factual_rows=rows, intervention=intervention)


# --- port, composition and placement (offline) ----------------------------------------


def test_the_port_composes_the_seal_subset_without_renaming_or_changing_signatures() -> None:
    port, subset = _port(), _subset()
    protocol, sealed = port.ScenarioOverlayStore, subset.ScenarioOverlayStoreSealSubset
    assert getattr(protocol, "_is_protocol", False) is True and issubclass(protocol, sealed)
    doc = inspect.getdoc(protocol) or ""
    assert "ADD v1.3 §4.2" in doc and "OCOR-DEV-REM-0040" in doc
    for name in ("seal_result", "read_sealed_result"):
        # Inherited, the very same functions: neither renamed nor re-declared.
        assert name not in vars(protocol) and getattr(protocol, name) is getattr(sealed, name)
    own = {name for name, value in vars(protocol).items() if callable(value) and not name.startswith("_")}
    assert own == {"open_snapshot", "fork_scenario", "append_overlay", "read_at", "discard"}
    assert list(inspect.signature(protocol.open_snapshot).parameters) == ["self", "canonical_commit_ref"]
    assert list(inspect.signature(protocol.fork_scenario).parameters) == ["self", "snapshot", "scenario_id", "run_id", "compartments"]
    assert list(inspect.signature(protocol.append_overlay).parameters) == ["self", "branch", "delta"]
    assert list(inspect.signature(protocol.read_at).parameters) == ["self", "branch", "revision"]
    assert list(inspect.signature(protocol.discard).parameters) == ["self", "branch"]
    store = _store("ocor_c7_rem0041_offline")
    assert isinstance(store, protocol) and isinstance(store, sealed)
    for name in ("seal_result", "read_sealed_result"):
        assert inspect.signature(getattr(type(store), name)) == inspect.signature(getattr(sealed, name))


def test_the_composed_and_sealed_modules_are_unchanged() -> None:
    for relative, expected in SEALED_SHA256.items():
        assert hashlib.sha256((RUNTIME_ROOT / relative).read_bytes()).hexdigest() == expected, relative


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(("." * node.level) + (node.module or ""))
    return names


def test_direct_backend_access_is_confined_to_the_adapter_and_never_reaches_the_c3_writer() -> None:
    import sys

    port_imports = _imports(PORT_PATH)
    assert not {name for name in port_imports if name.split(".")[0] in {"urllib", "http", "socket", "requests"}}
    adapter_imports = _imports(ADAPTER_PATH)
    assert "urllib.request" in adapter_imports
    absolute = {name.split(".")[0] for name in adapter_imports if not name.startswith(".")}
    assert absolute <= set(sys.stdlib_module_names) | {"__future__"}
    for name in port_imports | adapter_imports:
        assert "c3" not in name.split("."), name  # C7 never imports the C3 writer or its adapter
    lock = (RUNTIME_ROOT / "uv.lock").read_text(encoding="utf-8").lower()
    assert "terminusdb-client" not in lock and "terminusdb_client" not in lock


def test_no_write_path_of_the_adapter_can_name_main() -> None:
    tree = ast.parse(ADAPTER_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "branch/main" not in node.value
    # Every request path that names a branch interpolates the scenario branch name.
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            parts = node.values
            for index, part in enumerate(parts):
                if isinstance(part, ast.Constant) and str(part.value).endswith("/local/branch/"):
                    following = parts[index + 1]
                    assert isinstance(following, ast.FormattedValue)
                    assert isinstance(following.value, ast.Name) and following.value.id == "name"
    store = _store("ocor_c7_rem0041_offline", url=CLOSED_ENDPOINT)
    for name in ("main", "scenario-" + "0" * 64, "scenario_" + "0" * 63, "scenario_" + "G" * 64):
        assert _code(functools.partial(store._transact, name, [], [], "probe")) == "SCENARIO_HANDLE_INVALID"


def test_a_forged_handle_is_rejected_before_any_request() -> None:
    adapter, port = _adapter(), _port()
    store = _store("ocor_c7_rem0041_offline", url=CLOSED_ENDPOINT)
    token = adapter.run_token("urn:ocor:scenario:rem0041", "run-1", COMPARTMENTS)
    genuine = port.ScenarioBranch(
        scenario_id="urn:ocor:scenario:rem0041",
        run_id="run-1",
        compartments=COMPARTMENTS,
        canonical_commit_ref="abc123",
        scenario_branch="scenario/" + token,
    )
    other = adapter.run_token("urn:ocor:scenario:rem0041", "run-2", COMPARTMENTS)
    forged = (
        replace(genuine, scenario_branch="main"),
        replace(genuine, scenario_branch="scenario/" + other),
        replace(genuine, compartments=COMPARTMENTS[:1]),
        replace(genuine, compartments=tuple(reversed(COMPARTMENTS))),
        replace(genuine, run_id="run-2"),
        replace(genuine, canonical_commit_ref="not a commit"),
        replace(genuine, scenario_branch="scenario_" + token),
    )
    for handle in forged:
        assert _code(functools.partial(store.append_overlay, handle, {"x": 1})) == "SCENARIO_HANDLE_INVALID"
        assert _code(functools.partial(store.read_at, handle, 0)) == "SCENARIO_HANDLE_INVALID"
        assert _code(functools.partial(store.discard, handle)) == "SCENARIO_HANDLE_INVALID"
    # Positive control: the genuine handle passes the guard and only then needs the store.
    assert _code(lambda: store.read_at(genuine, 0)) == "STORE_NOT_INITIALIZED"


def test_configuration_is_fail_closed() -> None:
    adapter = _adapter()
    for kwargs, field in (
        ({"url": "ftp://127.0.0.1:6363"}, "url"),
        ({"password": ""}, "password"),
        ({"database": "Not-A-Database"}, "database"),
        ({"database": "ocor_default"}, "database"),
        ({"sealed_results": object()}, "sealed_results"),
    ):
        arguments: dict[str, Any] = {
            "url": TERMINUSDB_URL, "password": SYNTHETIC_SECRET, "database": "ocor_c7_rem0041_offline",
            "sealed_results": _OfflineSealSubset(),
        }
        arguments.update(kwargs)
        with pytest.raises(_port().ScenarioOverlayError) as caught:
            adapter.TerminusDBScenarioOverlayStore(**arguments)
        assert caught.value.code == "CONFIGURATION_INVALID" and field in str(caught.value)
    uninitialized = _store("ocor_c7_rem0041_offline", url=CLOSED_ENDPOINT)
    assert _code(lambda: uninitialized.open_snapshot("abc123")) == "STORE_NOT_INITIALIZED"
    assert _code(uninitialized.current_canonical_commit) == "STORE_NOT_INITIALIZED"
    snapshot = _port().ScenarioSnapshot(canonical_branch="main", canonical_commit_ref="abc123")
    assert _code(
        lambda: uninitialized.fork_scenario(snapshot, scenario_id="s", run_id="r", compartments=COMPARTMENTS)
    ) == "STORE_NOT_INITIALIZED"
    assert SYNTHETIC_SECRET not in repr(uninitialized)


def test_invalid_inputs_are_rejected_before_any_request() -> None:
    port = _port()
    store = _store("ocor_c7_rem0041_offline", url=CLOSED_ENDPOINT)
    for ref in ("", "ABC", "a" * 65, "abc/def", "../x"):
        assert _code(functools.partial(store.open_snapshot, ref)) == "SNAPSHOT_INVALID"
    good = port.ScenarioSnapshot(canonical_branch="main", canonical_commit_ref="abc123")
    for snapshot in (
        port.ScenarioSnapshot(canonical_branch="scenario/x", canonical_commit_ref="abc123"),
        port.ScenarioSnapshot(canonical_branch="main", canonical_commit_ref="bad ref"),
        object(),
    ):
        fork = functools.partial(store.fork_scenario, snapshot, scenario_id="s", run_id="r", compartments=COMPARTMENTS)
        assert _code(fork) == "SNAPSHOT_INVALID"
    arguments: dict[str, Any]
    for arguments in (
        {"scenario_id": "", "run_id": "r", "compartments": COMPARTMENTS},
        {"scenario_id": " s", "run_id": "r", "compartments": COMPARTMENTS},
        {"scenario_id": "s", "run_id": "r" * 513, "compartments": COMPARTMENTS},
        {"scenario_id": "s", "run_id": "r", "compartments": ()},
        {"scenario_id": "s", "run_id": "r", "compartments": ["urn:ocor:compartment:alpha"]},
        {"scenario_id": "s", "run_id": "r", "compartments": ("a", "a")},
        {"scenario_id": "s", "run_id": "r", "compartments": ("a", "")},
    ):
        assert _code(functools.partial(store.fork_scenario, good, **arguments)) == "SCENARIO_INVALID"
    token = _adapter().run_token("s", "r", ("a",))
    branch = port.ScenarioBranch(
        scenario_id="s", run_id="r", compartments=("a",), canonical_commit_ref="abc123", scenario_branch="scenario/" + token
    )
    for delta in ([1, 2], "text", {"x": float("nan")}, {"x": {1, 2}}, {"x": "y" * (1 << 20)}):
        assert _code(functools.partial(store.append_overlay, branch, delta)) == "DELTA_INVALID"
    for revision in (-1, True, 1.0, "1"):
        assert _code(functools.partial(store.read_at, branch, revision)) == "REVISION_INVALID"


def test_an_unreachable_server_fails_closed_without_fallback() -> None:
    store = _store("ocor_c7_rem0041_unreachable", url=CLOSED_ENDPOINT)
    assert _code(store.initialize) == "STORE_UNAVAILABLE"


# --- live cases on TerminusDB (and SeaweedFS for sealed results) -----------------------


def test_initialize_refuses_an_absent_canonical_database_and_creates_nothing(password: str) -> None:
    name = f"ocor_c7_rem0041_absent_{uuid.uuid4().hex[:8]}"
    before = _databases(password)
    assert _code(_store(name, password=password).initialize) == "CANONICAL_STORE_ABSENT"
    assert _databases(password) == before


def test_open_snapshot_pins_commits_of_main_and_refuses_any_other(
    overlay: Any, canonical: TerminusDBC3Service, password: str, database: str
) -> None:
    first = overlay.current_canonical_commit()
    canonical.commit(_command(expected_revision=0, delta={"status": "ASSESSED"}, key="snap-1"))
    head = overlay.current_canonical_commit()
    assert head != first and _main_log(password, database)[0] == head
    for ref in (head, first):
        snapshot = overlay.open_snapshot(ref)
        assert (snapshot.canonical_branch, snapshot.canonical_commit_ref) == ("main", ref)
    assert _code(lambda: overlay.open_snapshot("0" * 31)) == "SNAPSHOT_NOT_IN_MAIN"
    branch = _fork(overlay)
    overlay.append_overlay(branch, {"hypothesis": "scenario commit"})
    status, body, _ = _raw("GET", f"/api/log/admin/{database}/local/branch/{_terminus_branch(branch)}?count=1", password)
    assert status == 200, body
    scenario_commit = body[0]["identifier"]
    assert scenario_commit not in _main_log(password, database)
    assert _code(lambda: overlay.open_snapshot(scenario_commit)) == "SNAPSHOT_NOT_IN_MAIN"
    forged = _port().ScenarioSnapshot(canonical_branch="main", canonical_commit_ref=scenario_commit)
    assert _code(
        lambda: overlay.fork_scenario(forged, scenario_id="urn:ocor:scenario:rem0041", run_id="forged", compartments=COMPARTMENTS)
    ) == "SNAPSHOT_NOT_IN_MAIN"


def test_a_fork_mounts_the_baseline_read_only_at_the_snapshot_commit(
    overlay: Any, canonical: TerminusDBC3Service, password: str, database: str
) -> None:
    canonical.commit(_command(expected_revision=0, delta={"status": "ASSESSED"}, key="cow-1"))
    pinned = overlay.current_canonical_commit()
    canonical.commit(_command(expected_revision=1, delta={"status": "COMMITTED"}, key="cow-2"))
    branch = _fork(overlay, ref=pinned)
    assert branch.canonical_commit_ref == pinned and branch.scenario_branch.startswith("scenario/")
    (scenario_aggregate,) = _documents(password, database, "C3Aggregate", branch=_terminus_branch(branch))
    (main_aggregate,) = _documents(password, database, "C3Aggregate")
    assert (scenario_aggregate["revision"], json.loads(scenario_aggregate["state_json"])) == (1, {"status": "ASSESSED"})
    assert (main_aggregate["revision"], json.loads(main_aggregate["state_json"])) == (2, {"status": "COMMITTED"})
    overlay.append_overlay(branch, {"status": "HYPOTHETICAL"})
    (scenario_aggregate,) = _documents(password, database, "C3Aggregate", branch=_terminus_branch(branch))
    assert scenario_aggregate["revision"] == 1  # the overlay is a delta, the baseline stays as pinned


def test_the_whole_lifecycle_never_writes_main(
    overlay: Any, canonical: TerminusDBC3Service, password: str, database: str
) -> None:
    canonical.commit(_command(expected_revision=0, delta={"status": "ASSESSED"}, key="main-1"))
    before = _main_state(password, database)
    branch = _fork(overlay)
    for index in range(3):
        overlay.append_overlay(branch, {"step": index})
    assert overlay.read_at(branch, 3).revision == 3
    other = _fork(overlay, run_id="run-2")
    overlay.append_overlay(other, {"step": "other"})
    assert overlay.discard(branch) is True
    assert _main_state(password, database) == before
    assert _documents(password, database, "C7OverlayDelta") == [] and _documents(password, database, "C7ScenarioRun") == []
    # The sealed C3 schema check of main still accepts the database: C7 added classes
    # to the scenario branches only.
    TerminusDBC3Service(url=TERMINUSDB_URL, password=password, database=database).initialize()


def test_deltas_are_appended_in_order_chained_and_read_at_each_revision(overlay: Any) -> None:
    branch = _fork(overlay)
    assert overlay.read_at(branch, 0).deltas == ()
    written = [overlay.append_overlay(branch, {"step": index, "note": f"h{index}"}) for index in range(1, 4)]
    assert [delta.revision for delta in written] == [1, 2, 3]
    assert written[0].previous_digest is None
    assert [delta.previous_digest for delta in written[1:]] == [delta.delta_digest for delta in written[:-1]]
    assert len({delta.delta_digest for delta in written}) == 3
    for revision in range(4):
        view = overlay.read_at(branch, revision)
        assert view.branch == branch and view.revision == revision
        assert [dict(delta.delta) for delta in view.deltas] == [{"step": i, "note": f"h{i}"} for i in range(1, revision + 1)]
        assert view.deltas == tuple(written[:revision])
    assert _code(lambda: overlay.read_at(branch, 4)) == "REVISION_NOT_FOUND"


def test_concurrent_appends_get_distinct_gap_free_revisions(overlay: Any) -> None:
    branch = _fork(overlay)
    barrier = threading.Barrier(8)
    revisions: list[int] = []
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=30)
            revisions.append(overlay.append_overlay(branch, {"writer": index}).revision)
        except BaseException as error:  # noqa: BLE001 - collected and asserted below
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert errors == [] and sorted(revisions) == list(range(1, 9))
    view = overlay.read_at(branch, 8)
    assert sorted(int(delta.delta["writer"]) for delta in view.deltas) == list(range(8))


def test_concurrent_forks_of_one_run_create_exactly_one_overlay(overlay: Any, password: str, database: str) -> None:
    snapshot = overlay.open_snapshot(overlay.current_canonical_commit())
    barrier = threading.Barrier(6)
    created: list[Any] = []
    codes: list[str] = []

    def worker() -> None:
        barrier.wait(timeout=30)
        try:
            created.append(
                overlay.fork_scenario(snapshot, scenario_id="urn:ocor:scenario:rem0041", run_id="race", compartments=COMPARTMENTS)
            )
        except _port().ScenarioOverlayError as error:
            codes.append(error.code)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert len(created) == 1 and codes == ["SCENARIO_EXISTS"] * 5
    assert len(_documents(password, database, "C7ScenarioRun", branch=_terminus_branch(created[0]))) == 1
    assert overlay.append_overlay(created[0], {"after": "race"}).revision == 1


def test_an_existing_run_is_never_forked_again_and_a_rebase_is_a_new_run(overlay: Any, canonical: TerminusDBC3Service) -> None:
    branch = _fork(overlay)
    overlay.append_overlay(branch, {"original": True})
    canonical.commit(_command(expected_revision=0, delta={"status": "ASSESSED"}, key="rebase-1"))
    assert _code(lambda: _fork(overlay)) == "SCENARIO_EXISTS"
    rebased = _fork(overlay, run_id="run-1-rebased")
    assert rebased.scenario_branch != branch.scenario_branch and rebased.canonical_commit_ref != branch.canonical_commit_ref
    assert overlay.read_at(rebased, 0).deltas == ()
    assert [dict(delta.delta) for delta in overlay.read_at(branch, 1).deltas] == [{"original": True}]


def test_overlays_are_isolated_per_scenario_run_and_compartments(overlay: Any) -> None:
    alpha = _fork(overlay, compartments=COMPARTMENTS[:1])
    both = _fork(overlay, compartments=COMPARTMENTS)
    assert alpha.scenario_branch != both.scenario_branch
    assert _code(lambda: _fork(overlay, compartments=tuple(reversed(COMPARTMENTS)))) == "SCENARIO_EXISTS"
    assert both.compartments == tuple(sorted(COMPARTMENTS))
    other_scenario = overlay.fork_scenario(
        overlay.open_snapshot(overlay.current_canonical_commit()),
        scenario_id="urn:ocor:scenario:rem0041-other",
        run_id="run-1",
        compartments=COMPARTMENTS,
    )
    overlay.append_overlay(alpha, {"only": "alpha"})
    overlay.append_overlay(both, {"only": "both"})
    assert [dict(d.delta) for d in overlay.read_at(alpha, 1).deltas] == [{"only": "alpha"}]
    assert [dict(d.delta) for d in overlay.read_at(both, 1).deltas] == [{"only": "both"}]
    assert overlay.read_at(other_scenario, 0).deltas == ()
    assert _code(lambda: overlay.read_at(other_scenario, 1)) == "REVISION_NOT_FOUND"


def _tamper(password: str, database: str, branch: Any, document: dict[str, Any]) -> None:
    status, body, _ = _raw(
        "PUT",
        f"/api/document/admin/{database}/local/branch/{_terminus_branch(branch)}?author=tamper&message=tamper",
        password,
        [document],
    )
    assert status == 200, body


def test_a_tampered_delta_is_rejected_by_read_and_append(overlay: Any, password: str, database: str) -> None:
    branch = _fork(overlay)
    overlay.append_overlay(branch, {"step": 1})
    overlay.append_overlay(branch, {"step": 2})
    deltas = {doc["revision"]: doc for doc in _documents(password, database, "C7OverlayDelta", branch=_terminus_branch(branch))}
    tampered = dict(deltas[1])
    tampered["delta_json"] = json.dumps({"step": 99}, separators=(",", ":"))
    _tamper(password, database, branch, tampered)
    assert _code(lambda: overlay.read_at(branch, 2)) == "OVERLAY_TAMPERED"
    assert _code(lambda: overlay.read_at(branch, 0)) == "OVERLAY_TAMPERED"
    assert _code(lambda: overlay.append_overlay(branch, {"step": 3})) == "OVERLAY_TAMPERED"
    # A delta re-digested by the tamperer still breaks the chain to its successor.
    rechained = dict(tampered)
    rechained["delta_digest"] = _adapter()._chain_digest(branch.scenario_branch, 1, None, tampered["delta_json"])
    _tamper(password, database, branch, rechained)
    assert _code(lambda: overlay.read_at(branch, 2)) == "OVERLAY_TAMPERED"
    assert len(_documents(password, database, "C7OverlayDelta", branch=_terminus_branch(branch))) == 2


def test_a_removed_delta_is_rejected(overlay: Any, password: str, database: str) -> None:
    branch = _fork(overlay)
    for index in range(3):
        overlay.append_overlay(branch, {"step": index})
    status, body, _ = _raw(
        "DELETE",
        f"/api/document/admin/{database}/local/branch/{_terminus_branch(branch)}?author=tamper&message=remove"
        f"&id={urllib.parse.quote('C7OverlayDelta/000000000002', safe='')}",
        password,
    )
    assert status in (200, 204), body
    assert _code(lambda: overlay.read_at(branch, 1)) == "OVERLAY_TAMPERED"
    assert _code(lambda: overlay.append_overlay(branch, {"step": "refill"})) == "OVERLAY_TAMPERED"


def _stored_deltas(password: str, database: str, branch: Any) -> dict[int, dict[str, Any]]:
    documents = _documents(password, database, "C7OverlayDelta", branch=_terminus_branch(branch))
    return {int(doc["revision"]): doc for doc in documents}


def test_a_tampered_last_delta_is_rejected(overlay: Any, password: str, database: str) -> None:
    """The newest delta has no successor whose link could expose it: its own digest
    must."""
    branch = _fork(overlay)
    overlay.append_overlay(branch, {"step": 1})
    overlay.append_overlay(branch, {"step": 2})
    assert overlay.read_at(branch, 2).revision == 2  # positive control before the tamper
    tampered = dict(_stored_deltas(password, database, branch)[2])
    tampered["delta_json"] = json.dumps({"step": 99}, separators=(",", ":"))
    _tamper(password, database, branch, tampered)
    assert _code(lambda: overlay.read_at(branch, 2)) == "OVERLAY_TAMPERED"
    assert _code(lambda: overlay.append_overlay(branch, {"step": 3})) == "OVERLAY_TAMPERED"


def test_a_stored_link_that_disagrees_with_the_chain_is_rejected(overlay: Any, password: str, database: str) -> None:
    branch = _fork(overlay)
    first = overlay.append_overlay(branch, {"step": 1})
    overlay.append_overlay(branch, {"step": 2})
    tampered = dict(_stored_deltas(password, database, branch)[2])
    assert tampered["previous_digest"] == first.delta_digest  # positive control: the stored link
    tampered["previous_digest"] = "urn:sha256:" + "e" * 64
    _tamper(password, database, branch, tampered)
    assert _code(lambda: overlay.read_at(branch, 2)) == "OVERLAY_TAMPERED"


def test_a_stored_revision_that_disagrees_with_its_key_is_rejected(overlay: Any, password: str, database: str) -> None:
    branch = _fork(overlay)
    for index in range(3):
        overlay.append_overlay(branch, {"step": index})
    tampered = dict(_stored_deltas(password, database, branch)[3])
    assert tampered["key"] == "000000000003"  # positive control: key and revision agree
    tampered["revision"] = 4
    _tamper(password, database, branch, tampered)
    assert _code(lambda: overlay.read_at(branch, 2)) == "OVERLAY_TAMPERED"


def test_an_append_computed_from_a_superseded_read_writes_nothing(
    overlay: Any, password: str, database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The transaction requires the previous delta it was computed from: if that delta
    disappears between the read and the write, the write is refused and recomputed,
    so the stored chain stays readable."""
    branch = _fork(overlay)
    overlay.append_overlay(branch, {"step": 1})
    overlay.append_overlay(branch, {"step": 2})
    original = overlay._read_overlay
    removed: list[bool] = []

    def read_then_remove_the_head(handle: Any) -> Any:
        result = original(handle)
        if not removed:
            removed.append(True)
            status, body, _ = _raw(
                "DELETE",
                f"/api/document/admin/{database}/local/branch/{_terminus_branch(branch)}?author=tamper&message=remove"
                f"&id={urllib.parse.quote('C7OverlayDelta/000000000002', safe='')}",
                password,
            )
            assert status in (200, 204), body
        return result

    monkeypatch.setattr(overlay, "_read_overlay", read_then_remove_the_head)
    appended = overlay.append_overlay(branch, {"step": 3})
    monkeypatch.undo()
    assert removed == [True] and appended.revision == 2
    view = overlay.read_at(branch, 2)
    assert [dict(delta.delta) for delta in view.deltas] == [{"step": 1}, {"step": 3}]
    assert sorted(_stored_deltas(password, database, branch)) == [1, 2]


def test_a_handle_that_does_not_match_the_run_record_is_rejected(overlay: Any, canonical: TerminusDBC3Service) -> None:
    branch = _fork(overlay)
    canonical.commit(_command(expected_revision=0, delta={"status": "ASSESSED"}, key="handle-1"))
    lying = replace(branch, canonical_commit_ref=overlay.current_canonical_commit())
    assert _code(lambda: overlay.read_at(lying, 0)) == "SCENARIO_HANDLE_INVALID"
    assert _code(lambda: overlay.append_overlay(lying, {"x": 1})) == "SCENARIO_HANDLE_INVALID"
    assert overlay.read_at(branch, 0).revision == 0


def test_an_interrupted_fork_is_refused_until_it_is_discarded(overlay: Any, password: str, database: str) -> None:
    head = overlay.current_canonical_commit()
    token = _adapter().run_token("urn:ocor:scenario:rem0041", "run-1", COMPARTMENTS)
    branch = _port().ScenarioBranch(
        scenario_id="urn:ocor:scenario:rem0041", run_id="run-1", compartments=COMPARTMENTS,
        canonical_commit_ref=head, scenario_branch="scenario/" + token,
    )
    # The branch exists without its run record: a fork interrupted after the branch creation.
    status, body, _ = _raw(
        "POST", f"/api/branch/admin/{database}/local/branch/scenario_{token}", password,
        {"origin": f"admin/{database}/local/commit/{head}"},
    )
    assert status == 200, body
    assert _code(lambda: overlay.read_at(branch, 0)) == "SCENARIO_INCOMPLETE"
    assert _code(lambda: overlay.append_overlay(branch, {"x": 1})) == "SCENARIO_INCOMPLETE"
    assert _code(lambda: _fork(overlay)) == "SCENARIO_EXISTS"
    assert overlay.discard(branch) is True
    forked = _fork(overlay, ref=head)
    assert forked == branch and overlay.append_overlay(forked, {"x": 1}).revision == 1


def test_forked_outbox_entries_never_produce_a_delivery_attempt(
    overlay: Any, canonical: TerminusDBC3Service, password: str, database: str
) -> None:
    receipt = canonical.commit(_command(expected_revision=0, delta={"status": "ASSESSED"}, key="outbox-1"))
    branch = _fork(overlay)
    scenario = _terminus_branch(branch)
    assert [doc["event_id"] for doc in _documents(password, database, "C3OutboxEntry", branch=scenario)] == [receipt.outbox_event_id]
    # A delta shaped like an outbox entry stays opaque scenario data.
    (entry,) = _documents(password, database, "C3OutboxEntry")
    mimic = {key: value for key, value in entry.items() if key != "@id"}
    mimic.update({"event_id": "urn:ocor:event:scenario-mimic", "branch": "main"})
    overlay.append_overlay(branch, mimic)
    claimed = canonical.claim_batch(limit=100)
    assert [envelope.event_id for envelope in claimed] == [receipt.outbox_event_id]
    for envelope in claimed:
        canonical.acknowledge(envelope.event_id, acknowledged_at=datetime.now(UTC))
    assert canonical.reconcile(limit=100) == 0 and canonical.claim_batch(limit=100) == ()
    assert [doc["event_id"] for doc in _documents(password, database, "C3DeliveryAttempt")] == [receipt.outbox_event_id]
    assert _documents(password, database, "C3DeliveryAttempt", branch=scenario) == []
    assert [doc["event_id"] for doc in _documents(password, database, "C3OutboxEntry", branch=scenario)] == [receipt.outbox_event_id]
    assert {doc["event_id"] for doc in _documents(password, database, "C3OutboxEntry")} == {receipt.outbox_event_id}


def test_seal_result_composes_the_seaweedfs_subset_end_to_end(overlay: Any, sealed_results: Any) -> None:
    branch = _fork(overlay)
    overlay.append_overlay(branch, {"intervention": "do(treatment=1)"})
    outcome = _outcome(branch, "end-to-end")
    assert outcome.status == "IDENTIFIED" and outcome.lineage["scenario_branch"] == branch.scenario_branch
    receipt = overlay.seal_result(outcome)
    assert receipt.newly_sealed is True and receipt.reproducibility_digest == outcome.reproducibility_digest
    assert overlay.read_sealed_result(receipt.reproducibility_digest) == outcome
    assert sealed_results.read_sealed_result(receipt.reproducibility_digest) == outcome
    assert overlay.seal_result(outcome).newly_sealed is False
    assert _code_sealed(lambda: overlay.read_sealed_result("A" * 64)) == "INVALID_DIGEST"


def _code_sealed(raiser: Callable[[], object]) -> str:
    with pytest.raises(_subset().SealedResultError) as caught:
        raiser()
    code: str = caught.value.code
    return code


def test_discard_removes_only_the_overlay_and_keeps_sealed_results(
    overlay: Any, password: str, database: str
) -> None:
    branch = _fork(overlay)
    keep = _fork(overlay, run_id="run-kept")
    overlay.append_overlay(branch, {"step": 1})
    overlay.append_overlay(keep, {"step": "kept"})
    receipt = overlay.seal_result(_outcome(branch, "discard"))
    before = _main_state(password, database)
    assert overlay.discard(branch) is True
    assert _terminus_branch(branch) not in _branches(password, database)
    assert _code(lambda: overlay.read_at(branch, 0)) == "SCENARIO_NOT_FOUND"
    assert _code(lambda: overlay.append_overlay(branch, {"step": 2})) == "SCENARIO_NOT_FOUND"
    assert overlay.discard(branch) is False
    assert overlay.read_sealed_result(receipt.reproducibility_digest).lineage["scenario_branch"] == branch.scenario_branch
    assert [dict(d.delta) for d in overlay.read_at(keep, 1).deltas] == [{"step": "kept"}]
    assert _main_state(password, database) == before
    assert "main" in _branches(password, database)
