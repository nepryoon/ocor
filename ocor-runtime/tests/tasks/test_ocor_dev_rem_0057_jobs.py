"""OCOR-DEV-REM-0057 (NCP-U09): scenario runs, the signed causal model and the C7 job ledger.

Unit of NORMATIVE-CONFORMANCE-PLAN (2026-10-30), plan unit NCP-U09, register entries
NCR-C7-004 and the NFR-030 part of NCR-C7-003.

* NCR-C7-004 -- ADD v1.3 :2949-2961 (``ScenarioRunSpec`` is immutable and carries
  ``scenario_id``, ``parent_scenario_id``, ``run_id``, ``canonical_branch``,
  ``canonical_commit_ref``, ``projection_watermarks``, ``ontology_release_digest``,
  ``logic_bundle_digest``, ``causal_model_digest``, ``policy_bundle_digest``,
  ``assumption_set_ref``, ``input_digest``, ``evidence_refs``, ``seed``, ``time_horizon``,
  ``validity_at``, ``budget`` and ``governed_context``; the baseline is mounted read-only and
  every hypothesis is an append-only overlay delta of ``(scenario_id, run_id, compartments)``),
  ADD v1.3 :3026-3032 (causal workloads are ``L2 asynchronous-compute`` jobs with the lifecycle
  ``queued -> running -> paused | cancelled | completed | failed | expired``; budget, quota,
  progress, cancellation, timeout and backpressure are mandatory; the timeout never makes a
  partial result valid), ADD v1.3 :2927 (a cancelled causal job releases its resources within
  ``PT30S``), LLD v1.1 :177 (``CausalQuery`` includes baseline commit, scenario branch,
  SCM/model/release digest, estimand, treatment, outcome, population, factual evidence set,
  assumptions, seed, validity envelope and resource budget), LLD v1.1 :357 (the C7 job is
  cancellable with resource release and a sealed result; seed and inputs are pinned),
  Register FR-092 :232 (baseline, branch, ontology release, logic, causal model, policy
  snapshot, seed, assumptions, horizon, input and budget of every run are pinned; identical
  runs give equivalent output), FR-103 :244 (cancel and timeout release resources and are
  audited) and FR-161 :402 (a client submits, observes, cancels and retrieves a job; timeout
  and result are audited and bound to the pinned versions).

* NCR-C7-003, NFR-030 -- Register NFR-030 :228 (the causal model is content-addressed and
  signed; an invalid digest or signature blocks the run) and ADD v1.3 :3024 (signature,
  schema, policy or version-pin errors produce ``REJECTED``).

Backends are real: the job ledger runs on PostgreSQL (``OCOR_LIVE_POSTGRES_DSN``), the
hypothesis is read through the TerminusDB ``ScenarioOverlayStore`` of OCOR-DEV-REM-0041 and
results are sealed in its SeaweedFS sealed-result store (OCOR-DEV-REM-0040). The DoWhy
engine runs in the worker process of the job.
"""

from __future__ import annotations

import contextlib
import functools
import importlib
import importlib.util
import os
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import psycopg
import pytest
import test_ocor_dev_rem_0041_overlay as overlay_suite

from ocor_runtime.c1.signing import Ed25519SigningKey
from ocor_runtime.c3.terminusdb_service import TerminusDBC3Service
from ocor_runtime.c7.runtime import CausalOutcome, canonical_digest, outcome_document, verify_reproduction

RUNTIME_ROOT = Path(__file__).resolve().parents[2]
RUN = "ocor_runtime.c7.scenario_run"
JOBS = "ocor_runtime.c7.jobs"
LEDGER = "ocor_runtime.c7.adapters.postgres_jobs"
RELEASE = "urn:sha256:" + "b" * 64
KEY = Ed25519SigningKey.from_seed(bytes(range(32)))
OTHER_KEY = Ed25519SigningKey.from_seed(bytes(range(1, 33)))
KEYID = "urn:ocor:key:c7-model-signing:1"
PRINCIPAL = "urn:ocor:principal:analyst-1"
CLIENT = "urn:ocor:principal:analyst-1"
NONCE = uuid.uuid4().hex[:10]

# The synthetic SCM of the unit module: region confounds expedite and delay_hours; the ATE of
# expedite on delay_hours is -4 under the registered model.
MODEL: dict[str, Any] = {
    "model_id": "rem0057-jobs-scm",
    "version": 1,
    "estimand": "ATE",
    "tolerance": "0.25",
    "samples": 4000,
    "sensitivity_shift": "1",
    "exogenous": {
        "u_region": {"distribution": "bernoulli", "p": "0.5"},
        "u_expedite": {"distribution": "normal", "mean": "0", "sd": "1"},
        "u_delay": {"distribution": "normal", "mean": "0", "sd": "1"},
    },
    "endogenous": {
        "region": {"mechanism": "linear", "intercept": "0", "parents": {"u_region": "1"}},
        "expedite": {"mechanism": "threshold", "intercept": "-0.5", "parents": {"region": "1", "u_expedite": "1"}},
        "delay_hours": {"mechanism": "linear", "intercept": "10", "parents": {"expedite": "-4", "region": "2", "u_delay": "1"}},
    },
    "observed": ["region", "expedite", "delay_hours"],
}
# The same model with a million samples: a worker computation of several seconds, long
# enough to be paused, cancelled or timed out while it runs.
SLOW_MODEL: dict[str, Any] = {**MODEL, "model_id": "rem0057-jobs-scm-slow", "samples": 1_000_000}
ROWS = [
    {"region": "north", "expedite": 0, "delay_hours": "10"},
    {"region": "north", "expedite": 1, "delay_hours": "6"},
    {"region": "south", "expedite": 0, "delay_hours": "12"},
    {"region": "south", "expedite": 1, "delay_hours": "8"},
]
POPULATION = {"domain_id": "urn:ocor:domain:logistics", "unit": "shipment"}


def _run() -> ModuleType:
    return importlib.import_module(RUN)


def _jobs() -> ModuleType:
    return importlib.import_module(JOBS)


def _ledger_module() -> ModuleType:
    return importlib.import_module(LEDGER)


def _query_delta(operation: str = "simulate_intervention", *, values: tuple[int, ...] = (1,), **overrides: Any) -> dict[str, Any]:
    delta = {
        "kind": "causal_query",
        "operation": operation,
        "treatment": "expedite",
        "outcome": "delay_hours",
        "estimand": "ATE",
        "population": POPULATION,
        "interventions": [{"value": value, "valid_envelope": [0, 1]} for value in values],
    }
    delta.update(overrides)
    return delta


def _spec_document(branch: Any, *, model: dict[str, Any] = MODEL, rows: Any = ROWS, **overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "scenario_id": branch.scenario_id,
        "parent_scenario_id": None,
        "run_id": branch.run_id,
        "canonical_branch": "main",
        "canonical_commit_ref": branch.canonical_commit_ref,
        "projection_watermarks": {"c4.mission-object": 42, "c4.graph": 41},
        "ontology_release_digest": RELEASE,
        "logic_bundle_digest": "urn:sha256:" + "c" * 64,
        "causal_model_digest": canonical_digest(model),
        "policy_bundle_digest": "urn:sha256:" + "d" * 64,
        "assumption_set_ref": "urn:ocor:assumption-set:rem0057:1",
        "input_digest": canonical_digest(rows),
        "evidence_refs": ["urn:ocor:evidence:rem0057:factual-set"],
        "seed": 271828,
        "time_horizon": "P7D",
        "validity_at": "2026-11-08T00:00:00+00:00",
        "budget": {"max_runtime_seconds": 120, "max_samples": 1_000_000},
        # The complete, closed GovernedContext v1.2 record of ADD v1.3 §1.4 (:181-199), whose
        # release and policy pins are those of the run (ADD v1.3 :2959).
        "governed_context": {
            "tenant_id": "urn:ocor:tenant:synthetic",
            "organization_id": "urn:ocor:organization:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": sorted(getattr(branch, "compartments", overlay_suite.COMPARTMENTS)),
            "classification_marking_ref": "urn:sha256:" + "a" * 64,
            "purpose": "urn:ocor:purpose:causal-what-if",
            "effective_principal_id": PRINCIPAL,
            "actor_chain": [PRINCIPAL],
            "ontology_release_digest": RELEASE,
            "policy_bundle_digest": "urn:sha256:" + "d" * 64,
            "correlation_id": f"rem0057-jobs-{NONCE}",
        },
    }
    document.update(overrides)
    if "governed_context" not in overrides:
        for pin in ("ontology_release_digest", "policy_bundle_digest"):
            document["governed_context"][pin] = document[pin]
    return document


def _spec(branch: Any, **kwargs: Any) -> Any:
    return _run().ScenarioRunSpec.from_document(_spec_document(branch, **kwargs))


def _trust(**kwargs: Any) -> Any:
    return _run().CausalModelTrustRoot(keys={KEYID: KEY.public_key}, **kwargs)


def _envelope(model: dict[str, Any] = MODEL, *, key: Ed25519SigningKey = KEY, keyid: str = KEYID) -> dict[str, Any]:
    result: dict[str, Any] = _run().sign_causal_model(model, signer=key, keyid=keyid)
    return result


# --- live backends -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dsn() -> str:
    value = os.environ.get("OCOR_LIVE_POSTGRES_DSN", "")
    if not value:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory: the C7 job ledger is qualified on the real PostgreSQL adapter")
    with psycopg.connect(value) as connection:
        connection.execute("SELECT 1")
    return value


@pytest.fixture(scope="module")
def overlay() -> Iterator[Any]:
    """The TerminusDB ScenarioOverlayStore of OCOR-DEV-REM-0041 on a disposable canonical
    database, sealing into the SeaweedFS sealed-result store of OCOR-DEV-REM-0040."""
    suite = overlay_suite
    password = suite._env_value("OCOR_LOCAL_TERMINUSDB_PASSWORD", "OCOR_LIVE_TERMINUSDB_PASSWORD")
    try:
        suite._databases(password)
    except OSError as error:
        pytest.fail(f"a real, live TerminusDB server is mandatory qualifying evidence: {error}")
    status, _, text = suite._qualify().request(
        "PUT",
        f"{suite.SEAWEEDFS_URL}/{suite.LOCKED_BUCKET}",
        credential=(suite.ACCESS_KEY, suite._seaweedfs_secret()),
        body=b"",
        headers={"x-amz-bucket-object-lock-enabled": "true"},
        timeout=30.0,
    )
    assert int(status) == 200 or (int(status) == 409 and "BucketAlreadyOwnedByYou" in str(text)), (status, text)
    sealed = importlib.import_module(suite.SEAWEEDFS).SeaweedFSSealedResultStore(
        endpoint=suite.SEAWEEDFS_URL,
        bucket=suite.LOCKED_BUCKET,
        access_key=suite.ACCESS_KEY,
        secret_key=suite._seaweedfs_secret(),
        retention=suite.TEST_RETENTION,
    )
    sealed.initialize()
    database = f"ocor_c7_rem0057_{uuid.uuid4().hex[:12]}"
    try:
        canonical = TerminusDBC3Service(url=suite.TERMINUSDB_URL, password=password, database=database, admission=suite.GOVERNED.admission())
        canonical.initialize()
        store = suite._store(database, password=password, sealed=sealed)
        store.initialize()
        yield store
    finally:
        overlay_suite._raw("DELETE", f"/api/db/admin/{database}", password)
        assert database not in overlay_suite._databases(password), "disposable canonical database left behind"


@functools.cache
def _run_counter() -> list[int]:
    return [0]


def _fork(overlay: Any, *deltas: dict[str, Any]) -> Any:
    counter = _run_counter()
    counter[0] += 1
    snapshot = overlay.open_snapshot(overlay.current_canonical_commit())
    branch = overlay.fork_scenario(
        snapshot,
        scenario_id=f"urn:ocor:scenario:rem0057:{NONCE}",
        run_id=f"run-{counter[0]}",
        compartments=overlay_suite.COMPARTMENTS,
    )
    for delta in deltas:
        overlay.append_overlay(branch, delta)
    return branch


@pytest.fixture
def ledger(dsn: str) -> Iterator[Any]:
    schema = f"ocor_rem0057_jobs_{uuid.uuid4().hex[:8]}"
    value = _ledger_module().PostgresCausalJobLedger(dsn, schema=schema, max_active_per_principal=2, max_active_total=3)
    value.initialize()
    try:
        yield value
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _schema(ledger: Any) -> str:
    return str(ledger._schema)


def _runner(ledger: Any, overlay: Any, **kwargs: Any) -> Any:
    return _jobs().CausalJobRunner(ledger, overlay=overlay, trust_root=_trust(), expected_release_digest=RELEASE, **kwargs)


def _inputs(branch: Any, *, model: dict[str, Any] = MODEL, revision: int = 1, rows: Any = ROWS) -> Any:
    return _jobs().RunInputs(branch=branch, revision=revision, model_envelope=_envelope(model), factual_rows=rows)


_SIGNED = object()


def _prepare(overlay: Any, branch: Any, spec: Any, *, envelope: Any = _SIGNED, revision: int = 1, rows: Any = ROWS) -> Any:
    return _run().prepare_scenario_run(
        spec,
        overlay=overlay,
        branch=branch,
        revision=revision,
        model_envelope=_envelope() if envelope is _SIGNED else envelope,
        trust_root=_trust(),
        factual_rows=rows,
        expected_release_digest=RELEASE,
    )


def _rejected(outcome: Any, reason: str) -> None:
    assert isinstance(outcome, CausalOutcome), outcome
    assert (outcome.status, outcome.reason_code, outcome.effect, outcome.method) == ("REJECTED", reason, None, None)


def _job_code(call: Callable[[], object]) -> str:
    with pytest.raises(_jobs().CausalJobError) as caught:
        call()
    code: str = caught.value.code
    return code


def _wait(predicate: Callable[[], bool], *, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached in time"
        time.sleep(0.05)


def _alive(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as handle:
            return handle.read().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def _process_state(pid: int) -> str:
    with open(f"/proc/{pid}/stat", encoding="ascii") as handle:
        return handle.read().rsplit(")", 1)[1].split()[0]


def _background(call: Callable[[], Any]) -> tuple[list[Any], Any]:
    import threading

    box: list[Any] = []

    def target() -> None:
        try:
            box.append(call())
        except BaseException as exc:  # noqa: BLE001 - surfaced by the test
            box.append(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return box, thread


# --- NCR-C7-004: the immutable ScenarioRunSpec ---------------------------------------------------


def test_ncr_c7_004_conforms_the_run_spec_has_exactly_the_add_fields_and_is_immutable(overlay: Any) -> None:
    branch = _fork(overlay)
    spec = _spec(branch)
    assert tuple(_run().RUN_SPEC_FIELDS) == tuple(_spec_document(branch))
    assert spec.to_document() == _spec_document(branch)
    with pytest.raises(FrozenInstanceError):
        spec.seed = 1
    with pytest.raises(TypeError):
        spec.budget["max_samples"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        spec.governed_context["actor_chain"] = []  # type: ignore[index]


@pytest.mark.parametrize(
    "mutation",
    [
        {"drop": "budget"},
        {"extra": ("rogue", 1)},
        {"set": ("canonical_branch", "scenario/x")},
        {"set": ("causal_model_digest", "sha256:" + "0" * 64)},
        {"set": ("input_digest", "A" * 64)},
        {"set": ("seed", True)},
        {"set": ("seed", "1")},
        {"set": ("time_horizon", "seven days")},
        {"set": ("validity_at", "2026-11-08T00:00:00")},
        {"set": ("budget", {"max_runtime_seconds": 0, "max_samples": 10})},
        {"set": ("budget", {"max_runtime_seconds": 10})},
        {"set": ("projection_watermarks", {"c4": -1})},
        {"set": ("evidence_refs", ["a", "a"])},
        {"set": ("parent_scenario_id", "")},
        {"context": ("actor_chain", ["urn:ocor:principal:other"])},
        {"context": ("correlation_id", " ")},
        {"context_drop": "classification_marking_ref"},
    ],
)
def test_ncr_c7_004_conforms_an_incomplete_or_malformed_spec_is_refused(overlay: Any, mutation: dict[str, Any]) -> None:
    document = _spec_document(_fork(overlay))
    if "drop" in mutation:
        del document[mutation["drop"]]
    if "extra" in mutation:
        document[mutation["extra"][0]] = mutation["extra"][1]
    if "set" in mutation:
        document[mutation["set"][0]] = mutation["set"][1]
    if "context" in mutation:
        document["governed_context"] = {**document["governed_context"], mutation["context"][0]: mutation["context"][1]}
    if "context_drop" in mutation:
        document["governed_context"] = {k: v for k, v in document["governed_context"].items() if k != mutation["context_drop"]}
    with pytest.raises(_run().ScenarioRunError) as caught:
        _run().ScenarioRunSpec.from_document(document)
    assert caught.value.code == "RUN_SPEC_INVALID"


def test_ncr_c7_004_conforms_the_spec_digest_covers_every_pin_and_no_trace_identifier(overlay: Any) -> None:
    branch = _fork(overlay)
    base = _spec(branch)
    traced = _spec(branch, governed_context={**_spec_document(branch)["governed_context"], "correlation_id": "other"})
    assert traced.digest == base.digest
    for name, value in (
        ("seed", 1),
        ("time_horizon", "P8D"),
        ("logic_bundle_digest", "urn:sha256:" + "e" * 64),
        ("policy_bundle_digest", "urn:sha256:" + "e" * 64),
        ("projection_watermarks", {"c4.mission-object": 43, "c4.graph": 41}),
        ("assumption_set_ref", "urn:ocor:assumption-set:rem0057:2"),
        ("validity_at", "2026-11-09T00:00:00+00:00"),
        ("budget", {"max_runtime_seconds": 121, "max_samples": 1_000_000}),
    ):
        assert _spec(branch, **{name: value}).digest != base.digest, name


# --- NCR-C7-004: the query is built from the spec and the overlay --------------------------------


def test_ncr_c7_004_conforms_the_query_is_built_from_the_spec_and_the_overlay_hypothesis(overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    spec = _spec(branch)
    prepared = _prepare(overlay, branch, spec)
    assert isinstance(prepared, _run().PreparedRun)
    query = prepared.query
    assert (query.baseline_commit, query.scenario_branch) == (spec.canonical_commit_ref, branch.scenario_branch)
    assert (query.model_digest, query.data_digest, query.seed) == (spec.causal_model_digest, spec.input_digest, spec.seed)
    assert query.ontology_release_digest == spec.ontology_release_digest
    assert (query.treatment, query.outcome) == ("expedite", "delay_hours")
    assert query.intervention_digest == canonical_digest({"value": 1, "valid_envelope": [0, 1]})
    outcome = prepared.execute()
    assert outcome.status == "ESTIMATED", outcome
    run = outcome_document(outcome)["lineage"]["run"]
    assert run["run_spec_digest"] == spec.digest and run["overlay_revision"] == 1
    assert (run["estimand"], run["population"]) == ("ATE", POPULATION)
    for name in ("scenario_id", "run_id", "parent_scenario_id", "projection_watermarks", "logic_bundle_digest", "policy_bundle_digest",
                 "assumption_set_ref", "input_digest", "evidence_refs", "time_horizon", "validity_at", "budget"):
        assert run[name] == spec.pins()[name], name
    assert "correlation_id" not in run["governed_context"] and "causation_id" not in run["governed_context"]
    assert run["compartments"] == list(overlay_suite.COMPARTMENTS)


def test_ncr_c7_004_conforms_the_hypothesis_is_read_at_the_pinned_revision(overlay: Any) -> None:
    branch = _fork(overlay, _query_delta(values=(1,)), _query_delta(values=(0,)))
    spec = _spec(branch)
    first, second = _prepare(overlay, branch, spec, revision=1), _prepare(overlay, branch, spec, revision=2)
    assert first.interventions["value"] == 1 and second.interventions["value"] == 0
    assert first.query.run_pins["overlay_revision"] == 1 and second.query.run_pins["overlay_revision"] == 2
    assert first.execute().reproducibility_digest != second.execute().reproducibility_digest


@pytest.mark.parametrize(
    ("deltas", "reason"),
    [
        ((), "INTERVENTION_SCHEMA_INVALID"),
        (({"kind": "note", "text": "no query"},), "INTERVENTION_SCHEMA_INVALID"),
        ((_query_delta(operation="mutate_main"),), "INTERVENTION_SCHEMA_INVALID"),
        ((_query_delta(population={}),), "INTERVENTION_SCHEMA_INVALID"),
        ((_query_delta(operation="compare_interventions", values=(1,)),), "INTERVENTION_SCHEMA_INVALID"),
        ((_query_delta(values=(0, 1)),), "INTERVENTION_SCHEMA_INVALID"),
        ((_query_delta(estimand="ATT"),), "MODEL_SCHEMA_INVALID"),
    ],
)
def test_ncr_c7_004_conforms_a_missing_or_malformed_hypothesis_is_rejected(overlay: Any, deltas: tuple[Any, ...], reason: str) -> None:
    branch = _fork(overlay, *deltas)
    _rejected(_prepare(overlay, branch, _spec(branch), revision=len(deltas)), reason)


def test_ncr_c7_004_conforms_a_branch_of_another_run_or_baseline_is_rejected(overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    other = _fork(overlay, _query_delta())
    _rejected(_prepare(overlay, other, _spec(branch)), "SCENARIO_PIN_MISMATCH")
    _rejected(_prepare(overlay, branch, _spec(branch, canonical_commit_ref="0" * 32)), "SCENARIO_PIN_MISMATCH")


def test_ncr_c7_004_conforms_the_factual_set_and_the_sample_budget_are_pinned(overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    tampered = [*ROWS[:-1], {**ROWS[-1], "delay_hours": "9"}]
    prepared = _prepare(overlay, branch, _spec(branch), rows=tampered)
    _rejected(prepared.execute(), "DATA_PIN_MISMATCH")
    over_budget = _spec(branch, budget={"max_runtime_seconds": 120, "max_samples": 1000})
    _rejected(_prepare(overlay, branch, over_budget), "BUDGET_EXCEEDED")


# --- NFR-030: the signed causal model ------------------------------------------------------------


def _tampered_payload() -> dict[str, Any]:
    envelope = _envelope()
    other = _envelope({**MODEL, "tolerance": "0.5"})
    return {**envelope, "payload": other["payload"]}


@pytest.mark.parametrize(
    "envelope",
    [
        pytest.param(_tampered_payload, id="payload-swapped"),
        pytest.param(lambda: _envelope(key=OTHER_KEY), id="untrusted-key-same-keyid"),
        pytest.param(lambda: _envelope(keyid="urn:ocor:key:unknown"), id="unknown-keyid"),
        pytest.param(lambda: {**_envelope(), "payloadType": "application/json"}, id="payload-type"),
        pytest.param(lambda: {**_envelope(), "signatures": []}, id="no-signature"),
        pytest.param(lambda: {**_envelope(), "signatures": _envelope()["signatures"] * 2}, id="two-signatures"),
        pytest.param(lambda: {**_envelope(), "signatures": [{"keyid": KEYID, "sig": "***"}]}, id="sig-not-base64"),
        pytest.param(lambda: {**_envelope(), "payload": "%%%"}, id="payload-not-base64"),
        pytest.param(lambda: {**_envelope(), "extra": 1}, id="extra-field"),
        pytest.param(lambda: MODEL, id="unsigned-model"),
        pytest.param(lambda: None, id="no-envelope"),
    ],
)
def test_nfr_030_conforms_an_invalid_signature_blocks_the_run(overlay: Any, envelope: Callable[[], Any]) -> None:
    branch = _fork(overlay, _query_delta())
    _rejected(_prepare(overlay, branch, _spec(branch), envelope=envelope()), "MODEL_SIGNATURE_INVALID")


def test_nfr_030_conforms_a_revoked_key_blocks_the_run(overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    outcome = _run().prepare_scenario_run(
        _spec(branch),
        overlay=overlay,
        branch=branch,
        revision=1,
        model_envelope=_envelope(),
        trust_root=_trust(revoked_keyids=frozenset({KEYID})),
        factual_rows=ROWS,
        expected_release_digest=RELEASE,
    )
    _rejected(outcome, "MODEL_SIGNATURE_INVALID")


def test_nfr_030_conforms_a_validly_signed_model_other_than_the_pinned_one_is_rejected(overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    _rejected(_prepare(overlay, branch, _spec(branch), envelope=_envelope(SLOW_MODEL)), "MODEL_PIN_MISMATCH")


def test_nfr_030_conforms_a_non_canonical_signed_payload_is_rejected(overlay: Any) -> None:
    import base64
    import json

    from ocor_runtime.c1.signing import dsse_pae

    branch = _fork(overlay, _query_delta())
    payload = json.dumps(MODEL, indent=1).encode()
    signature = KEY.sign(dsse_pae(_run().CAUSAL_MODEL_PAYLOAD_TYPE, payload))
    envelope = {
        "payloadType": _run().CAUSAL_MODEL_PAYLOAD_TYPE,
        "payload": base64.b64encode(payload).decode(),
        "signatures": [{"keyid": KEYID, "sig": base64.b64encode(signature).decode()}],
    }
    _rejected(_prepare(overlay, branch, _spec(branch), envelope=envelope), "MODEL_SIGNATURE_INVALID")


def test_nfr_030_conforms_a_valid_signature_admits_the_run_and_the_rejection_carries_no_estimate(overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    spec = _spec(branch)
    admitted = _run().run_scenario(
        spec, overlay=overlay, branch=branch, revision=1, model_envelope=_envelope(), trust_root=_trust(), factual_rows=ROWS,
        expected_release_digest=RELEASE,
    )
    assert admitted.status == "ESTIMATED"
    rejected = _prepare(overlay, branch, spec, envelope=_envelope(key=OTHER_KEY))
    assert dict(rejected.details) == {} and rejected.lineage["run"]["run_spec_digest"] == spec.digest


# --- NCR-C7-004: the L2 job lifecycle on PostgreSQL ----------------------------------------------


def test_ncr_c7_004_conforms_a_client_submits_observes_and_retrieves_a_versioned_result(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    spec = _spec(branch)
    job = ledger.submit(spec, actor=CLIENT)
    assert job.job_id.startswith("urn:ocor:c7:job:") and (job.state, job.progress, job.spec_digest) == ("queued", "0", spec.digest)
    assert job.deadline - job.submitted_at == timedelta(seconds=120)
    assert _job_code(lambda: ledger.result(job.job_id)) == "NO_VALID_RESULT"
    finished = _runner(ledger, overlay).run(job.job_id, _inputs(branch))
    assert (finished.state, finished.progress, finished.outcome_status) == ("completed", "1", "ESTIMATED")
    result = ledger.result(job.job_id)
    assert (result.spec_digest, result.result_version) == (spec.digest, 1)
    assert result.outcome.reproducibility_digest == finished.result_digest
    direct = _run().run_scenario(
        spec, overlay=overlay, branch=branch, revision=1, model_envelope=_envelope(), trust_root=_trust(), factual_rows=ROWS,
        expected_release_digest=RELEASE,
    )
    verify_reproduction(direct, result.outcome)
    assert overlay.read_sealed_result(result.outcome.reproducibility_digest) == result.outcome
    assert [(t.from_state, t.to_state) for t in ledger.transitions(job.job_id)] == [
        (None, "queued"), ("queued", "running"), ("running", "completed"), ("completed", "resources_released"),
    ]
    assert all(t.actor for t in ledger.transitions(job.job_id))
    assert {r.resource for r in ledger.resources(job.job_id)} == {"worker_process", "samples"}
    assert all(r.released_at is not None for r in ledger.resources(job.job_id))


def test_ncr_c7_004_conforms_identical_runs_give_equivalent_results(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    spec = _spec(branch)
    digests = []
    for _ in range(2):
        job = ledger.submit(spec, actor=CLIENT)
        _runner(ledger, overlay).run(job.job_id, _inputs(branch))
        digests.append(ledger.result(job.job_id).outcome.reproducibility_digest)
    assert digests[0] == digests[1]


def test_ncr_c7_004_conforms_a_rejected_run_completes_with_its_sealed_rejection(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    job = ledger.submit(_spec(branch), actor=CLIENT)
    inputs = _jobs().RunInputs(branch=branch, revision=1, model_envelope=_envelope(key=OTHER_KEY), factual_rows=ROWS)
    finished = _runner(ledger, overlay).run(job.job_id, inputs)
    assert (finished.state, finished.outcome_status) == ("completed", "REJECTED")
    _rejected(ledger.result(job.job_id).outcome, "MODEL_SIGNATURE_INVALID")


def test_ncr_c7_004_conforms_only_the_add_transitions_are_allowed_and_refusals_change_nothing(ledger: Any, overlay: Any) -> None:
    jobs = _jobs()
    assert tuple(jobs.JOB_STATES) == ("queued", "running", "paused", "cancelled", "completed", "failed", "expired")
    branch = _fork(overlay, _query_delta())
    job = ledger.submit(_spec(branch), actor=CLIENT).job_id
    assert _job_code(lambda: ledger.pause(job, actor=CLIENT, reason="r")) == "INVALID_TRANSITION"
    assert _job_code(lambda: ledger.resume(job, actor=CLIENT, reason="r")) == "INVALID_TRANSITION"
    assert _job_code(lambda: ledger.report_progress(job, "0.5", actor=CLIENT)) == "INVALID_TRANSITION"
    assert _job_code(lambda: ledger.expire(job, actor=CLIENT)) == "NOT_OVERDUE"
    assert _job_code(lambda: ledger.release_resources(job, actor=CLIENT)) == "INVALID_TRANSITION"
    ledger.start(job, actor="runner", resources={"worker_process": 1})
    assert _job_code(lambda: ledger.start(job, actor="runner", resources={"worker_process": 1})) == "INVALID_TRANSITION"
    assert _job_code(lambda: ledger.resume(job, actor=CLIENT, reason="r")) == "INVALID_TRANSITION"
    ledger.report_progress(job, "0.5", actor="runner")
    assert _job_code(lambda: ledger.report_progress(job, "0.4", actor="runner")) == "PROGRESS_REGRESSION"
    for bad in ("1.5", "-0", "abc", "0.50", 0.5):
        assert _job_code(lambda bad=bad: ledger.report_progress(job, bad, actor="runner")) == "SCHEMA_VIOLATION"
    assert ledger.pause(job, actor=CLIENT, reason="operator").state == "paused"
    assert ledger.resume(job, actor=CLIENT, reason="operator").state == "running"
    ledger.fail(job, actor="runner", technical_failure="ENGINE_FAULT", retry_safety="SAFE_TO_RETRY")
    before = ledger.transitions(job)
    for call in (
        lambda: ledger.cancel(job, actor=CLIENT, reason="late"),
        lambda: ledger.resume(job, actor=CLIENT, reason="r"),
        lambda: ledger.start(job, actor="runner", resources={"worker_process": 1}),
    ):
        assert _job_code(call) == "INVALID_TRANSITION"
    assert ledger.transitions(job) == before
    failed = ledger.job(job)
    assert (failed.state, failed.technical_failure, failed.retry_safety, failed.result_digest) == (
        "failed", "ENGINE_FAULT", "SAFE_TO_RETRY", None,
    )
    assert _job_code(lambda: ledger.result(job)) == "NO_VALID_RESULT"
    assert [t.to_state for t in before] == ["queued", "running", "paused", "running", "failed"]


def test_ncr_c7_004_conforms_a_queued_job_is_cancelled_and_audited(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    job = ledger.submit(_spec(branch), actor=CLIENT).job_id
    cancelled = ledger.cancel(job, actor=CLIENT, reason="no longer needed")
    assert cancelled.state == "cancelled"
    last = ledger.transitions(job)[-1]
    assert (last.from_state, last.to_state, last.actor, last.reason) == ("queued", "cancelled", CLIENT, "no longer needed")
    assert _job_code(lambda: _runner(ledger, overlay).run(job, _inputs(branch))) == "INVALID_TRANSITION"


def test_ncr_c7_004_conforms_cancelling_a_running_job_releases_its_resources_within_pt30s(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta(operation="compare_interventions", values=(0, 1)))
    job = ledger.submit(_spec(branch, model=SLOW_MODEL), actor=CLIENT).job_id
    workers: list[int] = []
    box, thread = _background(lambda: _runner(ledger, overlay, on_worker=workers.append).run(job, _inputs(branch, model=SLOW_MODEL)))
    _wait(lambda: bool(workers) and ledger.job(job).state == "running")
    assert _alive(workers[0])
    ledger.cancel(job, actor=CLIENT, reason="operator cancel")
    thread.join(timeout=30)
    assert not thread.is_alive() and not isinstance(box[0], BaseException), box
    assert box[0].state == "cancelled" and not _alive(workers[0])
    cancel = next(t for t in ledger.transitions(job) if t.to_state == "cancelled")
    resources = ledger.resources(job)
    assert resources and all(r.released_at is not None for r in resources)
    assert max(r.released_at for r in resources) - cancel.recorded_at <= _jobs().RESOURCE_RELEASE_DEADLINE
    assert ledger.transitions(job)[-1].to_state == "resources_released"
    assert _job_code(lambda: ledger.result(job)) == "NO_VALID_RESULT"


def test_ncr_c7_004_conforms_a_paused_job_stops_its_worker_until_resumed(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta(operation="compare_interventions", values=(0, 1)))
    job = ledger.submit(_spec(branch, model=SLOW_MODEL), actor=CLIENT).job_id
    workers: list[int] = []
    box, thread = _background(lambda: _runner(ledger, overlay, on_worker=workers.append).run(job, _inputs(branch, model=SLOW_MODEL)))
    _wait(lambda: bool(workers) and ledger.job(job).state == "running")
    ledger.pause(job, actor=CLIENT, reason="operator pause")
    _wait(lambda: _process_state(workers[0]) == "T", timeout=10)
    time.sleep(0.5)
    assert ledger.job(job).state == "paused" and _process_state(workers[0]) == "T"
    ledger.resume(job, actor=CLIENT, reason="operator resume")
    _wait(lambda: _process_state(workers[0]) != "T", timeout=10)
    thread.join(timeout=120)
    assert not thread.is_alive() and box[0].state == "completed", box
    assert ledger.result(job).outcome.status == "ESTIMATED"
    assert [t.to_state for t in ledger.transitions(job)] == ["queued", "running", "paused", "running", "completed", "resources_released"]


def test_ncr_c7_004_conforms_a_timeout_expires_the_job_without_a_partial_result(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta(operation="compare_interventions", values=(0, 1)))
    spec = _spec(branch, model=SLOW_MODEL, budget={"max_runtime_seconds": 3, "max_samples": 1_000_000})
    job = ledger.submit(spec, actor=CLIENT).job_id
    workers: list[int] = []
    finished = _runner(ledger, overlay, on_worker=workers.append).run(job, _inputs(branch, model=SLOW_MODEL))
    assert (finished.state, finished.result_digest, finished.outcome_status) == ("expired", None, None)
    assert not _alive(workers[0])
    assert _job_code(lambda: ledger.result(job)) == "NO_VALID_RESULT"
    expired = next(t for t in ledger.transitions(job) if t.to_state == "expired")
    assert (expired.from_state, expired.reason) == ("running", "TIMEOUT")
    assert all(r.released_at is not None and r.released_at - expired.recorded_at <= timedelta(seconds=30) for r in ledger.resources(job))
    with psycopg.connect(ledger._dsn) as connection:
        assert connection.execute(f"SELECT count(*) FROM {_schema(ledger)}.c7_job_result WHERE job_id = %s", (job,)).fetchone() == (0,)


def test_ncr_c7_004_conforms_a_result_after_the_deadline_is_refused(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    spec = _spec(branch, budget={"max_runtime_seconds": 1, "max_samples": 1_000_000})
    job = ledger.submit(spec, actor=CLIENT).job_id
    ledger.start(job, actor="runner", resources={"worker_process": 1})
    outcome = _prepare(overlay, branch, spec).execute()
    time.sleep(1.2)
    assert _job_code(lambda: ledger.complete(job, outcome, actor="runner")) == "JOB_EXPIRED"
    assert ledger.job(job).state == "expired"
    assert _job_code(lambda: ledger.result(job)) == "NO_VALID_RESULT"


def test_ncr_c7_004_conforms_a_result_bound_to_another_spec_or_tampered_is_refused(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    spec = _spec(branch)
    other = _spec(branch, seed=7)
    job = ledger.submit(spec, actor=CLIENT).job_id
    ledger.start(job, actor="runner", resources={"worker_process": 1})
    assert _job_code(lambda: ledger.complete(job, _prepare(overlay, branch, other).execute(), actor="runner")) == "RESULT_PIN_MISMATCH"
    genuine = _prepare(overlay, branch, spec).execute()
    forged = CausalOutcome(
        status=genuine.status, reason_code=None, method=genuine.method, effect="0", details=genuine.details,
        assumptions=genuine.assumptions, lineage=genuine.lineage, reproducibility_digest=genuine.reproducibility_digest,
    )
    assert _job_code(lambda: ledger.complete(job, forged, actor="runner")) == "RESULT_INVALID"
    assert ledger.job(job).state == "running"
    ledger.complete(job, genuine, actor="runner")
    with psycopg.connect(ledger._dsn) as connection:
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute(f"UPDATE {_schema(ledger)}.c7_job_result SET outcome = outcome || '{{\"effect\": \"0\"}}'::jsonb")
    with psycopg.connect(ledger._dsn) as connection:
        connection.execute(f"ALTER TABLE {_schema(ledger)}.c7_job_result DISABLE TRIGGER c7_job_result_append_only")
        connection.execute(f"UPDATE {_schema(ledger)}.c7_job_result SET outcome = outcome || '{{\"effect\": \"0\"}}'::jsonb")
    assert _job_code(lambda: ledger.result(job)) == "RESULT_TAMPERED"


def test_ncr_c7_004_conforms_the_audit_is_append_only(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    job = ledger.submit(_spec(branch), actor=CLIENT).job_id
    with psycopg.connect(ledger._dsn) as connection:
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute(f"UPDATE {_schema(ledger)}.c7_job_transition SET actor = 'x'")
    with psycopg.connect(ledger._dsn) as connection:
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute(f"DELETE FROM {_schema(ledger)}.c7_job_transition")
    ledger.start(job, actor="runner", resources={"worker_process": 1})
    with psycopg.connect(ledger._dsn) as connection:
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute(f"DELETE FROM {_schema(ledger)}.c7_job_resource")
    ledger.cancel(job, actor=CLIENT, reason="stop")
    ledger.release_resources(job, actor="runner")
    with psycopg.connect(ledger._dsn) as connection:
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute(f"UPDATE {_schema(ledger)}.c7_job_resource SET released_at = clock_timestamp()")


def test_ncr_c7_004_conforms_quota_and_backpressure_refuse_and_audit_submissions(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    spec = _spec(branch)
    first = ledger.submit(spec, actor=CLIENT).job_id
    ledger.submit(spec, actor=CLIENT)
    assert _job_code(lambda: ledger.submit(spec, actor=CLIENT)) == "QUOTA_EXCEEDED"
    other_principal = "urn:ocor:principal:analyst-2"
    other = _spec(
        branch,
        governed_context={**_spec_document(branch)["governed_context"], "effective_principal_id": other_principal, "actor_chain": [other_principal]},
    )
    ledger.submit(other, actor=other_principal)
    assert _job_code(lambda: ledger.submit(other, actor=other_principal)) == "BACKPRESSURE"
    refusals = ledger.refusals(PRINCIPAL) + ledger.refusals(other_principal)
    assert [r.reason.split(":")[0] for r in refusals] == ["QUOTA_EXCEEDED", "BACKPRESSURE"]
    assert all(r.to_state == "refused" and r.job_id is None for r in refusals)
    ledger.cancel(first, actor=CLIENT, reason="free a slot")
    assert ledger.submit(spec, actor=CLIENT).state == "queued"


def test_ncr_c7_004_conforms_a_lost_worker_fails_the_job_with_retry_safety(ledger: Any, overlay: Any) -> None:
    import signal

    branch = _fork(overlay, _query_delta(operation="compare_interventions", values=(0, 1)))
    job = ledger.submit(_spec(branch, model=SLOW_MODEL), actor=CLIENT).job_id
    workers: list[int] = []
    box, thread = _background(lambda: _runner(ledger, overlay, on_worker=workers.append).run(job, _inputs(branch, model=SLOW_MODEL)))
    _wait(lambda: bool(workers) and ledger.job(job).state == "running")
    os.kill(workers[0], signal.SIGKILL)
    thread.join(timeout=30)
    failed = ledger.job(job)
    assert (failed.state, failed.technical_failure, failed.retry_safety) == ("failed", "WORKER_LOST", "SAFE_TO_RETRY")
    assert all(r.released_at is not None for r in ledger.resources(job))


# --- input robustness of the ledger adapter ------------------------------------------------------


def test_ncr_c7_004_conforms_an_unreachable_backend_is_a_typed_error_without_credentials() -> None:
    secret = "rem0057-synthetic-secret"
    closed = _ledger_module().PostgresCausalJobLedger(f"postgresql://ocor:{secret}@127.0.0.1:9/ocor", schema="ocor_rem0057_closed")
    with pytest.raises(_jobs().CausalJobError) as caught:
        closed.job("urn:ocor:c7:job:x")
    assert caught.value.code == "BACKEND_UNAVAILABLE" and secret not in str(caught.value)
    with pytest.raises(ValueError):
        _ledger_module().PostgresCausalJobLedger("postgresql://x", schema="Bad-Name")
    with pytest.raises(ValueError):
        _ledger_module().PostgresCausalJobLedger("postgresql://x", max_active_total=0)


def test_ncr_c7_004_conforms_a_foreign_table_shape_is_a_schema_mismatch(dsn: str) -> None:
    schema = f"ocor_rem0057_foreign_{uuid.uuid4().hex[:8]}"
    try:
        with psycopg.connect(dsn) as connection:
            connection.execute(f"CREATE SCHEMA {schema}")
            connection.execute(f"CREATE TABLE {schema}.c7_job (job_id TEXT PRIMARY KEY)")
        with pytest.raises(_jobs().CausalJobError) as caught:
            _ledger_module().PostgresCausalJobLedger(dsn, schema=schema).initialize()
        assert caught.value.code == "SCHEMA_MISMATCH"
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@pytest.mark.parametrize(
    ("column", "value", "code"),
    [
        ("progress", "'abc'", "BACKEND_ERROR"),
        ("progress", "'0.50'", "BACKEND_ERROR"),
        ("spec_digest", "'not-a-digest'", "BACKEND_ERROR"),
        ("principal", "''", "BACKEND_ERROR"),
        ("retry_safety", "'MAYBE'", "BACKEND_ERROR"),
        ("result_digest", "'" + "f" * 64 + "'", "BACKEND_ERROR"),
        ("spec", "spec || '{\"seed\": 1}'::jsonb", "SPEC_TAMPERED"),
        ("spec", "spec || '{\"seed\": \"1\"}'::jsonb", "BACKEND_ERROR"),
    ],
)
def test_ncr_c7_004_conforms_a_tampered_stored_job_is_refused(ledger: Any, overlay: Any, column: str, value: str, code: str) -> None:
    branch = _fork(overlay, _query_delta())
    job = ledger.submit(_spec(branch), actor=CLIENT).job_id
    with psycopg.connect(ledger._dsn) as connection:
        connection.execute(f"UPDATE {_schema(ledger)}.c7_job SET {column} = {value} WHERE job_id = %s", (job,))
    assert _job_code(lambda: ledger.spec(job)) == code


def test_ncr_c7_004_conforms_a_tampered_audit_or_resource_row_is_refused(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    job = ledger.submit(_spec(branch), actor=CLIENT).job_id
    ledger.start(job, actor="runner", resources={"worker_process": 1})
    schema = _schema(ledger)
    with psycopg.connect(ledger._dsn) as connection:
        connection.execute(f"ALTER TABLE {schema}.c7_job_transition DISABLE TRIGGER c7_job_transition_append_only")
        connection.execute(f"UPDATE {schema}.c7_job_transition SET actor = '' WHERE job_id = %s", (job,))
    assert _job_code(lambda: ledger.transitions(job)) == "BACKEND_ERROR"
    with psycopg.connect(ledger._dsn) as connection:
        connection.execute(f"ALTER TABLE {schema}.c7_job_resource DISABLE TRIGGER c7_job_resource_release_only")
        connection.execute(f"ALTER TABLE {schema}.c7_job_resource DROP CONSTRAINT IF EXISTS c7_job_resource_quantity_check")
        connection.execute(f"UPDATE {schema}.c7_job_resource SET quantity = -1 WHERE job_id = %s", (job,))
    assert _job_code(lambda: ledger.resources(job)) == "BACKEND_ERROR"


@pytest.mark.parametrize(
    ("call", "code"),
    [
        (lambda ledger, job: ledger.start(job, actor="runner", resources={}), "SCHEMA_VIOLATION"),
        (lambda ledger, job: ledger.start(job, actor="runner", resources={"Bad Name": 1}), "SCHEMA_VIOLATION"),
        (lambda ledger, job: ledger.start(job, actor="runner", resources={"worker_process": True}), "SCHEMA_VIOLATION"),
        (lambda ledger, job: ledger.cancel(job, actor="", reason="r"), "SCHEMA_VIOLATION"),
        (lambda ledger, job: ledger.cancel(job, actor="a", reason=""), "SCHEMA_VIOLATION"),
        (lambda ledger, job: ledger.fail(job, actor="a", technical_failure="X", retry_safety="MAYBE"), "SCHEMA_VIOLATION"),
        (lambda ledger, job: ledger.complete(job, "not an outcome", actor="a"), "SCHEMA_VIOLATION"),
        (lambda ledger, job: ledger.submit({"scenario_id": "x"}, actor="a"), "SCHEMA_VIOLATION"),
        (lambda ledger, job: ledger.job("urn:ocor:c7:job:absent"), "JOB_NOT_FOUND"),
        (lambda ledger, job: ledger.job(""), "SCHEMA_VIOLATION"),
    ],
)
def test_ncr_c7_004_conforms_malformed_calls_are_refused_with_typed_errors(
    ledger: Any, overlay: Any, call: Callable[[Any, str], object], code: str
) -> None:
    branch = _fork(overlay, _query_delta())
    job = ledger.submit(_spec(branch), actor=CLIENT).job_id
    assert _job_code(lambda: call(ledger, job)) == code
    assert ledger.job(job).state == "queued"


def test_ncr_c7_004_conforms_overdue_jobs_without_a_runner_expire_and_free_the_quota(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    short = _spec(branch, budget={"max_runtime_seconds": 1, "max_samples": 1_000_000})
    stale = [ledger.submit(short, actor=CLIENT).job_id for _ in range(2)]
    assert _job_code(lambda: ledger.submit(short, actor=CLIENT)) == "QUOTA_EXCEEDED"
    time.sleep(1.2)
    assert ledger.submit(_spec(branch), actor=CLIENT).state == "queued"
    for job in stale:
        assert ledger.job(job).state == "expired"
        last = ledger.transitions(job)[-1]
        assert (last.from_state, last.to_state, last.reason) == ("queued", "expired", "TIMEOUT")
        assert _job_code(lambda job=job: ledger.result(job)) == "NO_VALID_RESULT"


def test_ncr_c7_004_conforms_an_unreadable_hypothesis_fails_the_job_and_releases_its_resources(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    job = ledger.submit(_spec(branch), actor=CLIENT).job_id
    finished = _runner(ledger, overlay).run(job, _inputs(branch, revision=5))
    assert (finished.state, finished.retry_safety, finished.result_digest) == ("failed", "SAFE_TO_RETRY", None)
    assert finished.technical_failure is not None and finished.technical_failure.startswith("OVERLAY_")
    assert all(r.released_at is not None for r in ledger.resources(job))
    assert [t.to_state for t in ledger.transitions(job)] == ["queued", "running", "failed", "resources_released"]


# --- preventive review OCOR-DEV-REM-0057-1a64cb83f153-pre (P1, P3, P4, P5) ---------------------
#
# P1: the governed context of a run is the complete, closed GovernedContext v1.2 record of
# ADD v1.3 §1.4 (:181-199), as ADD v1.3 :2959 requires ("record canonico §1.4 completo").


def test_ncr_c7_004_conforms_the_governed_context_is_the_complete_closed_add_record(overlay: Any) -> None:
    from ocor_runtime.kernel.governed_context import GCS_FIELDS

    branch = _fork(overlay, _query_delta())
    document = _spec_document(branch)
    assert tuple(_run().GOVERNED_CONTEXT_FIELDS) == GCS_FIELDS
    spec = _run().ScenarioRunSpec.from_document(document)
    assert tuple(spec.governed_context) == GCS_FIELDS
    assert spec.to_document() == document
    assert spec.pins()["governed_context"] == {k: v for k, v in document["governed_context"].items() if k != "correlation_id"}


_GC_MUTATIONS = [
    *({"drop": name} for name in ("tenant_id", "organization_id", "compartments", "purpose", "ontology_release_digest", "policy_bundle_digest")),
    {"set": ("causation_id", "urn:ocor:causation:rem0057")},
    {"set": ("classification_marking_ref", "NOT-A-URN-SHA256")},
    {"set": ("classification_marking_ref", "sha256:" + "a" * 64)},
    {"set": ("actor_chain", [PRINCIPAL, PRINCIPAL])},
    {"set": ("compartments", [])},
    {"set": ("compartments", ["urn:ocor:compartment:alpha", "urn:ocor:compartment:alpha"])},
    {"set": ("compartments", "urn:ocor:compartment:alpha")},
    {"set": ("tenant_id", 7)},
    {"set": ("ontology_release_digest", "urn:sha256:" + "e" * 64)},
    {"set": ("policy_bundle_digest", "urn:sha256:" + "e" * 64)},
]


@pytest.mark.parametrize("mutation", _GC_MUTATIONS, ids=[str(i) for i in range(len(_GC_MUTATIONS))])
def test_ncr_c7_004_conforms_a_governed_context_other_than_the_closed_add_record_is_refused(mutation: dict[str, Any]) -> None:
    branch = _offline_branch()
    context = dict(_spec_document(branch)["governed_context"])
    if "drop" in mutation:
        del context[mutation["drop"]]
    else:
        context[mutation["set"][0]] = mutation["set"][1]
    with pytest.raises(_run().ScenarioRunError) as caught:
        _run().ScenarioRunSpec.from_document(_spec_document(branch, governed_context=context))
    assert caught.value.code == "RUN_SPEC_INVALID"


def test_ncr_c7_004_conforms_the_query_trace_is_the_context_correlation_and_the_run(overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    spec = _spec(branch)
    prepared = _prepare(overlay, branch, spec)
    assert isinstance(prepared, _run().PreparedRun)
    assert (prepared.query.correlation_id, prepared.query.causation_id) == (spec.governed_context["correlation_id"], spec.run_id)


def test_ncr_c7_004_conforms_an_overlay_of_other_compartments_is_rejected(overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    context = {**_spec_document(branch)["governed_context"], "compartments": [overlay_suite.COMPARTMENTS[0]]}
    _rejected(_prepare(overlay, branch, _spec(branch, governed_context=context)), "SCENARIO_PIN_MISMATCH")


# P5: the population of the hypothesis is canonical, finite JSON like its interventions; a
# delta that is not is REJECTED{INTERVENTION_SCHEMA_INVALID} (ADD v1.3 :3024), never a raw error.


def _offline_branch() -> Any:
    from ocor_runtime.c7.scenario_overlay import ScenarioBranch

    return ScenarioBranch(
        scenario_id=f"urn:ocor:scenario:rem0057:{NONCE}",
        run_id="run-offline",
        compartments=overlay_suite.COMPARTMENTS,
        canonical_commit_ref="c" * 32,
        scenario_branch="scenario/rem0057-offline",
    )


class _OneViewOverlay:
    """Returns one fixed overlay view: the failure handling of a hypothesis that the real
    store could not hold (non-finite numbers are not representable in its JSON)."""

    def __init__(self, branch: Any, delta: dict[str, Any]) -> None:
        from ocor_runtime.c7.scenario_overlay import OverlayDelta, OverlayView

        self._view = OverlayView(branch=branch, revision=1, deltas=(OverlayDelta(1, delta, "0" * 64, None),))

    def read_at(self, branch: Any, revision: int) -> Any:
        return self._view


@pytest.mark.parametrize(
    "population",
    [{"threshold": float("nan")}, {"threshold": float("inf")}, {"unit": object()}, {"unit": {"nested": float("-inf")}}],
    ids=["nan", "inf", "not-json", "nested-inf"],
)
def test_ncr_c7_004_conforms_a_hypothesis_population_that_is_not_finite_json_is_rejected(population: dict[str, Any]) -> None:
    branch = _offline_branch()
    stub = _OneViewOverlay(branch, _query_delta(population=population))
    _rejected(_prepare(stub, branch, _spec(branch)), "INTERVENTION_SCHEMA_INVALID")
    accepted = _prepare(_OneViewOverlay(branch, _query_delta()), branch, _spec(branch))
    assert isinstance(accepted, _run().PreparedRun)


# P4: once the runner has started a job (resources acquired), every path releases them:
# a cancellation or timeout before the progress report, a worker that cannot be started,
# and a worker that exits before it is stopped or resumed (ADD v1.3 :2927, :3026-3032).


class _CancelledBeforeProgress:
    """The real ledger, cancelled by the client just before the runner reports progress."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def report_progress(self, job_id: str, progress: str, *, actor: str) -> Any:
        self._inner.cancel(job_id, actor=CLIENT, reason="cancelled before the progress report")
        return self._inner.report_progress(job_id, progress, actor=actor)


def test_ncr_c7_004_conforms_a_job_cancelled_before_its_progress_report_releases_its_resources(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    job = ledger.submit(_spec(branch), actor=CLIENT).job_id
    finished = _runner(_CancelledBeforeProgress(ledger), overlay).run(job, _inputs(branch))
    assert (finished.state, finished.result_digest) == ("cancelled", None)
    assert ledger.resources(job) and all(r.released_at is not None for r in ledger.resources(job))
    assert [t.to_state for t in ledger.transitions(job)] == ["queued", "running", "cancelled", "resources_released"]


class _UnstartableContext:
    """A multiprocessing context whose worker cannot be started (the OS refuses it)."""

    def __init__(self) -> None:
        import multiprocessing

        self._real = multiprocessing.get_context("spawn")
        self.receivers: list[Any] = []

    def Pipe(self, duplex: bool = True) -> Any:  # noqa: N802 - the multiprocessing API name
        receiver, sender = self._real.Pipe(duplex=duplex)
        self.receivers.append(receiver)
        return receiver, sender

    def Process(self, **kwargs: Any) -> Any:  # noqa: N802 - the multiprocessing API name
        class _Refused:
            pid = None

            def start(self) -> None:
                raise OSError("synthetic: the worker process cannot be created")

            def is_alive(self) -> bool:
                return False

            def join(self, timeout: float | None = None) -> None:
                return None

        return _Refused()


def test_ncr_c7_004_conforms_a_worker_that_cannot_start_fails_the_job_and_releases_everything(ledger: Any, overlay: Any) -> None:
    branch = _fork(overlay, _query_delta())
    job = ledger.submit(_spec(branch), actor=CLIENT).job_id
    runner = _runner(ledger, overlay)
    context = _UnstartableContext()
    runner._context = context
    finished = runner.run(job, _inputs(branch))
    assert (finished.state, finished.technical_failure, finished.retry_safety) == ("failed", "WORKER_START_FAILED", "SAFE_TO_RETRY")
    assert all(r.released_at is not None for r in ledger.resources(job))
    assert context.receivers and all(receiver.closed for receiver in context.receivers)


def _exited_worker() -> tuple[Any, Any]:
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    process = context.Process(target=os.getpid, daemon=True)
    process.start()
    process.join(30)
    receiver, sender = context.Pipe(duplex=False)
    sender.close()
    return process, receiver


@pytest.mark.parametrize(("then", "state"), [("cancel", "cancelled"), ("resume", "failed")])
def test_ncr_c7_004_conforms_a_worker_gone_before_pause_or_resume_never_escapes_untyped(
    ledger: Any, overlay: Any, then: str, state: str
) -> None:
    branch = _fork(overlay, _query_delta())
    job = ledger.submit(_spec(branch), actor=CLIENT).job_id
    ledger.start(job, actor="runner", resources={"worker_process": 1})
    ledger.pause(job, actor=CLIENT, reason="pause before the signal")
    process, receiver = _exited_worker()
    try:
        box, thread = _background(lambda: _runner(ledger, overlay)._supervise(job, process, receiver))
        time.sleep(0.5)
        assert not box, box
        getattr(ledger, then)(job, actor=CLIENT, reason=f"{then} after the worker exited")
        thread.join(timeout=30)
    finally:
        receiver.close()
    assert box and not isinstance(box[0], BaseException), box
    finished = ledger.job(job)
    assert finished.state == state
    if state == "failed":
        assert (finished.technical_failure, finished.retry_safety) == ("WORKER_LOST", "SAFE_TO_RETRY")
    assert all(r.released_at is not None for r in ledger.resources(job))


# P3: every row returned by the backend is checked for its shape before use; a missing
# column, a coerced value, an incoherent state, a foreign result or a non-finite number is a
# typed error (BACKEND_ERROR or RESULT_TAMPERED), never a raw KeyError or ValueError. The
# rows are scripted: the real PostgreSQL schema cannot return them (missing columns, TEXT
# holding an integer, JSONB holding NaN), so this is the local failure handling only.

_NOW = datetime(2026, 11, 8, tzinfo=UTC)
_JOB = "urn:ocor:c7:job:scripted"


def _job_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "job_id": _JOB, "principal": PRINCIPAL, "spec_digest": "a" * 64, "spec": {}, "state": "queued", "progress": "0",
        "deadline": _NOW, "result_digest": None, "outcome_status": None, "technical_failure": None, "retry_safety": None,
        "submitted_at": _NOW, "updated_at": _NOW, "overdue": False,
    }
    row.update(overrides)
    return row


class _Cursor:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return list(self._rows)


class _ScriptedConnection:
    def __init__(self, script: list[tuple[str, list[Any]]]) -> None:
        self._script = script

    def __enter__(self) -> _ScriptedConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def transaction(self) -> Any:
        return contextlib.nullcontext()

    def execute(self, statement: Any, params: Any = ()) -> _Cursor:
        text = statement.decode() if isinstance(statement, bytes) else str(statement)
        for marker, rows in self._script:
            if marker in text:
                return _Cursor(rows)
        return _Cursor([])


def _scripted(monkeypatch: pytest.MonkeyPatch, *script: tuple[str, list[Any]]) -> Any:
    module = _ledger_module()
    monkeypatch.setattr(module.psycopg, "connect", lambda *args, **kwargs: _ScriptedConnection(list(script)))
    return module.PostgresCausalJobLedger("postgresql://scripted", schema="ocor_rem0057_scripted")


_JOB_SQL = "AS overdue FROM"


def _rejected_document() -> tuple[dict[str, Any], str]:
    from ocor_runtime.c7.runtime import CausalQuery, estimate_counterfactual

    query = CausalQuery(
        baseline_commit="c" * 32, scenario_branch="scenario/rem0057-scripted", model_digest=canonical_digest(MODEL),
        data_digest=canonical_digest(ROWS), intervention_digest=canonical_digest(None), ontology_release_digest=RELEASE,
        expected_release_digest=RELEASE, treatment="expedite", outcome="delay_hours", seed=1, correlation_id="c", causation_id="r",
        run_pins={"run_spec_digest": "a" * 64},
    )
    outcome = estimate_counterfactual(query, model=MODEL, factual_rows=ROWS, intervention={"value": 1, "valid_envelope": [0, 1]}, unit_index=0)
    return outcome_document(outcome), outcome.reproducibility_digest


@pytest.mark.parametrize(
    ("script", "call"),
    [
        # release_resources: a released resource that is not a named text row
        ([(_JOB_SQL, [_job_row(state="cancelled")]), ("RETURNING resource", [{"resource": 123}])], "release"),
        ([(_JOB_SQL, [_job_row(state="cancelled")]), ("RETURNING resource", ["not-a-mapping"])], "release"),
        ([(_JOB_SQL, [_job_row(state="cancelled")]), ("RETURNING resource", [{"name": "worker_process"}])], "release"),
        # the overdue sweep and the admission count with a missing column
        ([("ORDER BY job_id FOR UPDATE", [{"job_id": _JOB, "principal": PRINCIPAL}])], "expire"),
        ([("count(*) FILTER", [{"mine": 0}])], "submit"),
        # a stored job whose outcome status, failure or retry safety contradicts its state
        ([(_JOB_SQL, [_job_row(outcome_status="BOGUS_STATUS")])], "job"),
        ([(_JOB_SQL, [_job_row(state="queued", outcome_status="ESTIMATED")])], "job"),
        ([(_JOB_SQL, [_job_row(state="completed", result_digest="b" * 64, progress="1")])], "job"),
        ([(_JOB_SQL, [_job_row(state="failed")])], "job"),
        ([(_JOB_SQL, [_job_row(state="failed", technical_failure="WORKER_LOST")])], "job"),
        ([(_JOB_SQL, [_job_row(state="queued", technical_failure="WORKER_LOST", retry_safety="SAFE_TO_RETRY")])], "job"),
        ([(_JOB_SQL, [{k: v for k, v in _job_row().items() if k != "overdue"}])], "job"),
    ],
    ids=["release-int", "release-row", "release-missing", "sweep-missing", "count-missing", "status-unknown", "status-not-completed",
         "completed-no-status", "failed-no-failure", "failed-no-retry", "failure-not-failed", "row-missing-column"],
)
def test_ncr_c7_004_conforms_a_backend_row_of_the_wrong_shape_is_a_typed_backend_error(
    monkeypatch: pytest.MonkeyPatch, script: list[tuple[str, list[Any]]], call: str
) -> None:
    ledger = _scripted(monkeypatch, *script)
    calls: dict[str, Callable[[], object]] = {
        "release": lambda: ledger.release_resources(_JOB, actor="runner"),
        "expire": lambda: ledger.expire_overdue(actor="scheduler"),
        "submit": lambda: ledger.submit(_spec(_offline_branch()), actor=CLIENT),
        "job": lambda: ledger.job(_JOB),
    }
    assert _job_code(calls[call]) == "BACKEND_ERROR"


@pytest.mark.parametrize("tamper", ["foreign-job", "bad-recorded-at", "nan-in-outcome"])
def test_ncr_c7_004_conforms_a_stored_result_foreign_or_not_finite_is_refused(monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    document, digest = _rejected_document()
    run_spec_digest = "a" * 64
    result = {
        "job_id": _JOB, "spec_digest": run_spec_digest, "result_version": 1, "outcome": document,
        "reproducibility_digest": digest, "recorded_at": _NOW,
    }
    if tamper == "foreign-job":
        result["job_id"] = "urn:ocor:c7:job:another"
    elif tamper == "bad-recorded-at":
        result["recorded_at"] = "NOT-A-DATETIME"
    else:
        result["outcome"] = {**document, "lineage": {**document["lineage"], "nan_probe": float("nan")}}
    ledger = _scripted(
        monkeypatch,
        (_JOB_SQL, [_job_row(state="completed", progress="1", result_digest=digest, outcome_status="REJECTED")]),
        ("c7_job_result WHERE", [result]),
    )
    assert _job_code(lambda: ledger.result(_JOB)) == ("RESULT_TAMPERED" if tamper == "nan-in-outcome" else "BACKEND_ERROR")


def test_ncr_c7_004_conforms_well_shaped_backend_rows_are_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The positive side of the two tests above: the same scripted rows, well shaped, pass."""
    document, digest = _rejected_document()
    completed = _job_row(state="completed", progress="1", result_digest=digest, outcome_status="REJECTED")
    result = {
        "job_id": _JOB, "spec_digest": "a" * 64, "result_version": 1, "outcome": document, "reproducibility_digest": digest,
        "recorded_at": _NOW,
    }
    ledger = _scripted(monkeypatch, (_JOB_SQL, [completed]), ("c7_job_result WHERE", [result]))
    assert ledger.result(_JOB).outcome.reproducibility_digest == digest
    failed = _job_row(state="failed", technical_failure="WORKER_LOST", retry_safety="SAFE_TO_RETRY")
    assert _scripted(monkeypatch, (_JOB_SQL, [failed])).job(_JOB).technical_failure == "WORKER_LOST"
    ledger = _scripted(
        monkeypatch, (_JOB_SQL, [_job_row(state="cancelled")]), ("RETURNING resource", [{"resource": "worker_process"}])
    )
    assert ledger.release_resources(_JOB, actor="runner") == ()
    swept = _scripted(monkeypatch, ("ORDER BY job_id FOR UPDATE", [{"job_id": _JOB, "principal": PRINCIPAL, "state": "queued"}]))
    assert swept.expire_overdue(actor="scheduler") == (_JOB,)
