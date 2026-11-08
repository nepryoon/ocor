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

import functools
import importlib
import importlib.util
import os
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import FrozenInstanceError
from datetime import timedelta
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
        "governed_context": {
            "domain_id": "urn:ocor:domain:logistics",
            "classification_marking_ref": "urn:sha256:" + "a" * 64,
            "effective_principal_id": PRINCIPAL,
            "actor_chain": [PRINCIPAL],
            "correlation_id": f"rem0057-jobs-{NONCE}",
            "causation_id": "urn:ocor:causation:rem0057-jobs",
        },
    }
    document.update(overrides)
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
    traced = _spec(branch, governed_context={**_spec_document(branch)["governed_context"], "correlation_id": "other", "causation_id": "x"})
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
