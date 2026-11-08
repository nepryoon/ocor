"""OCOR-DEV-REM-0057 (NCP-U09): the C7 causal runtime conforms to the closed normative elements.

Unit of NORMATIVE-CONFORMANCE-PLAN (2026-10-30), plan unit NCP-U09, register entries
NCR-C7-001 to NCR-C7-006.

* NCR-C7-001 -- ADD v1.3 :2977 (for an SCM ``M=(U,V,F,P(U))``, ``SimulateIntervention(do(X=x))``
  builds ``M_do(X=x)`` by replacing ``F_X`` with the imposed value and removing the edges entering
  ``X``), ADD v1.3 :2965-2972 (§4.2 flow: identification first, ``ABSTAIN: NOT_IDENTIFIED`` when the
  estimand is not identified, then the validity envelope, then ``do(X)`` in an isolated SCM),
  Register FR-094 :235 (the do(X) output matches the interventional ground truth within tolerance)
  and FR-009 :60 (at least two simulated interventions are compared with estimand,
  identification, assumptions, uncertainty and sensitivity; a non-identifiable case returns
  ``NOT_IDENTIFIED`` and no causal estimate). Additional criterion of NORMATIVE-CONFORMANCE-PLAN
  point 2 for NCP-U09 (ADD v1.3 :275, :2977, :3036): the registered model declares endogenous
  ``V``, exogenous ``U`` with ``P(U)`` and mechanisms ``F``; ``do(X)`` replaces ``F_X``; the engine
  port keeps abduction, action and prediction distinct and the PoC profile uses only action and
  prediction.

* NCR-C7-002 -- ADD v1.3 :3007-3022 (closed ``ABSTAIN.reason_code`` set and its precedence), ADD
  v1.3 :3024 (signature, schema, policy or version-pin errors produce ``REJECTED``), LLD v1.1 :177
  (disjoint reason codes without an estimate) and LLD v1.1 :16-18 (§0.1 precedence), Register
  FR-009 :60 and FR-098 :239 (an out-of-envelope fixture produces an abstention), with the mapping
  of PO decision NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 4 for ``NCR-C7-002``.

* NCR-C7-003 -- ADD v1.3 :2979-3005 (``CausalRunOutcome := ESTIMATED | ABSTAIN | REJECTED |
  FAILED`` and their fields), ADD v1.3 :3024 (pin errors produce ``REJECTED``, computational faults
  ``FAILED``), LLD v1.1 :177 (the result includes uncertainty, sensitivity, lineage, inputs, seed
  and reproducibility digest), Register FR-093 :233 (an incomplete SimulationResult fails schema
  validation), FR-097 :238 (no quantitative P0 result without an uncertainty descriptor) and
  NFR-030 :228 (an invalid digest blocks the run).

* NCR-C7-005 -- Register NFR-007 :61 (identical runs give identical digests for deterministic
  outputs or differences within the preregistered tolerance; the tolerance is mandatory in the
  model manifest), FR-092 :232 (equivalent output within the declared tolerance), NFR-015 :133 and
  LLD v1.1 :177 (reproducibility digest). The digest does not depend on trace identifiers.

* NCR-C7-006 -- ADD v1.3 :3036 (``ELM-070`` deferred: the PoC profile returns
  ``REJECTED{reason=CAPABILITY_DEFERRED, element=ELM-070}``) with PO decision
  NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 4 for ``NCR-C7-006`` (option A): every structurally
  valid unit-level counterfactual query is rejected without reading the factual set, also on
  ``main`` or with an out-of-range unit index; a structurally invalid one is rejected for its schema
  error; identical inputs give an identical outcome.

The causal runtime is a pure, in-memory component; the identification runs on the real DoWhy
(PyWhy) configuration item of C7 (ADD v1.3 :275) behind the C7 engine port.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator, Mapping
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from typing import Any

import pytest

from ocor_runtime.c7 import runtime as c7
from ocor_runtime.c7.runtime import (
    CausalOutcome,
    CausalQuery,
    CausalRuntimeError,
    canonical_digest,
    estimate_counterfactual,
    estimate_intervention,
    estimate_sensitivity,
    estimate_uncertainty,
    verify_reproduction,
)

ADD_ABSTAIN_PRECEDENCE = (
    "ASSUMPTION_VIOLATION",
    "NOT_IDENTIFIED",
    "OUTSIDE_VALIDITY_ENVELOPE",
    "OUT_OF_DISTRIBUTION",
    "EXTRAPOLATIVE",
    "NOT_TRANSPORTABLE",
    "INSUFFICIENT_EVIDENCE",
    "STALE_CONTEXT",
)
EFFECT_KEYS = {"effect", "effect_estimate", "estimate", "interval", "ci_low", "ci_high", "ranking", "prescription"}

# A registered synthetic SCM M=(U,V,F,P(U)): region confounds expedite and delay_hours.
# Ground truth: E[delay | do(expedite=1)] = 10 - 4 + 2 * 0.5 = 7; do(expedite=0) = 11; ATE = -4.
MODEL: dict[str, Any] = {
    "model_id": "synthetic-logistics-scm",
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
# The same structure with an unobserved common cause of expedite and delay_hours and no observed
# confounder: the ATE is not identifiable under the registered SCM.
CONFOUNDED_MODEL: dict[str, Any] = {
    **MODEL,
    "model_id": "synthetic-logistics-latent",
    "exogenous": {**MODEL["exogenous"], "u_latent": {"distribution": "normal", "mean": "0", "sd": "1"}},
    "endogenous": {
        "region": MODEL["endogenous"]["region"],
        "expedite": {"mechanism": "threshold", "intercept": "-0.5", "parents": {"u_latent": "1", "u_expedite": "1"}},
        "delay_hours": {"mechanism": "linear", "intercept": "10", "parents": {"expedite": "-4", "u_latent": "2", "u_delay": "1"}},
    },
}
ROWS = [
    {"region": "north", "expedite": 0, "delay_hours": "10"},
    {"region": "north", "expedite": 1, "delay_hours": "6"},
    {"region": "south", "expedite": 0, "delay_hours": "12"},
    {"region": "south", "expedite": 1, "delay_hours": "8"},
]
INTERVENTION = {"treatment": "expedite", "value": 1, "valid_envelope": [0, 1]}
RELEASE = "sha256:" + "a" * 64


def _query(
    *,
    model: Mapping[str, Any] = MODEL,
    rows: Any = ROWS,
    intervention: Any = INTERVENTION,
    branch: str = "scenario/expedite-what-if",
    expected_release: str = RELEASE,
    seed: int = 271828,
    correlation_id: str = "018f2f95-01b2-7cc3-8d4e-123456789abc",
    causation_id: str = "urn:ocor:causation:synthetic:42",
) -> CausalQuery:
    return CausalQuery(
        baseline_commit="urn:ocor:commit:synthetic:42",
        scenario_branch=branch,
        model_digest=canonical_digest(model),
        data_digest=canonical_digest(rows),
        intervention_digest=canonical_digest(intervention),
        ontology_release_digest=RELEASE,
        expected_release_digest=expected_release,
        treatment="expedite",
        outcome="delay_hours",
        seed=seed,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )


def _estimate(
    *, model: dict[str, Any] = MODEL, rows: Any = ROWS, intervention: Any = INTERVENTION, **query: Any
) -> CausalOutcome:
    return estimate_intervention(
        _query(model=model, rows=rows, intervention=intervention, **query), model=model, factual_rows=rows, intervention=intervention
    )


def _simulate(*, model: dict[str, Any] = MODEL, intervention: Any = INTERVENTION, engine: Any = None, **query: Any) -> CausalOutcome:
    kwargs = {} if engine is None else {"engine": engine}
    return c7.simulate_intervention(
        _query(model=model, intervention=intervention, **query), model=model, factual_rows=ROWS, intervention=intervention, **kwargs
    )


def _walk_keys(value: Any) -> Iterator[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _walk_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_keys(item)


class _Unreadable(list[dict[str, Any]]):
    """A factual set that fails the test on any read."""

    def _read(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the factual set was read")

    __iter__ = _read  # type: ignore[assignment]
    __len__ = _read  # type: ignore[assignment]
    __getitem__ = _read  # type: ignore[assignment]
    __bool__ = _read
    __contains__ = _read  # type: ignore[assignment]


# --- NCR-C7-001: do(X) on the registered SCM, identification and comparison -------------------


def test_ncr_c7_001_conforms_the_registered_model_declares_v_u_p_u_and_f() -> None:
    model = c7.StructuralCausalModel.from_document(MODEL)
    assert set(model.endogenous) == {"region", "expedite", "delay_hours"}
    assert set(model.exogenous) == {"u_region", "u_expedite", "u_delay"}
    assert model.exogenous["u_region"].distribution == "bernoulli"
    assert dict(model.endogenous["delay_hours"].parents) == {"expedite": Decimal("-4"), "region": Decimal("2"), "u_delay": Decimal("1")}
    assert model.tolerance == Decimal("0.25")
    for broken in (
        {key: value for key, value in MODEL.items() if key != "exogenous"},
        {**MODEL, "endogenous": {**MODEL["endogenous"], "region": {"mechanism": "linear", "intercept": "0", "parents": {"u_missing": "1"}}}},
        {**MODEL, "endogenous": {**MODEL["endogenous"], "region": {"mechanism": "linear", "intercept": "0", "parents": {"delay_hours": "1"}}}},
    ):
        with pytest.raises(c7.ModelSchemaError):
            c7.StructuralCausalModel.from_document(broken)


def test_ncr_c7_001_conforms_do_replaces_the_target_mechanism_and_removes_its_incoming_edges() -> None:
    model = c7.StructuralCausalModel.from_document(MODEL)
    engine = c7.default_engine()
    intervened = engine.act(model, {"expedite": Decimal("1")})
    assert dict(intervened.endogenous["expedite"].parents) == {}
    assert intervened.endogenous["expedite"].mechanism == "constant"
    assert intervened.endogenous["expedite"].intercept == Decimal("1")
    assert ("region", "expedite") in model.edges() and ("u_expedite", "expedite") in model.edges()
    assert not any(child == "expedite" for _parent, child in intervened.edges())
    # every other mechanism is the registered one; the original model is unchanged
    assert intervened.endogenous["delay_hours"] == model.endogenous["delay_hours"]
    assert intervened.endogenous["region"] == model.endogenous["region"]
    assert model.endogenous["expedite"].mechanism == "threshold"


def test_ncr_c7_001_conforms_simulate_intervention_matches_the_interventional_ground_truth() -> None:
    treated = _simulate()
    control = _simulate(intervention={**INTERVENTION, "value": 0})
    assert treated.status == control.status == "ESTIMATED"
    assert treated.method == "SCM_DO_MONTE_CARLO"
    tolerance = Decimal(MODEL["tolerance"])
    assert abs(Decimal(treated.effect) - Decimal("7")) <= tolerance
    assert abs(Decimal(control.effect) - Decimal("11")) <= tolerance
    # do(X) is not conditioning: the observational mean of delay among expedited units differs
    model = c7.StructuralCausalModel.from_document(MODEL)
    samples = model.sample(seed=271828, size=4000)
    observed = [row["delay_hours"] for row in samples if row["expedite"] == 1]
    assert abs(Decimal(str(sum(observed) / len(observed))) - Decimal("7")) > tolerance


def test_ncr_c7_001_conforms_identification_is_derived_from_the_registered_scm() -> None:
    outcome = _estimate()
    assert outcome.status == "ESTIMATED"
    identification = outcome.details["identification_result"]
    assert identification["status"] == "IDENTIFIED"
    assert identification["method"] == "backdoor"
    assert list(identification["adjustment_set"]) == ["region"]
    assert outcome.effect == "-4"


def test_ncr_c7_001_conforms_a_non_identifiable_query_returns_not_identified_and_no_estimate() -> None:
    for operation in (_estimate, _simulate):
        outcome = operation(model=CONFOUNDED_MODEL)
        assert (outcome.status, outcome.reason_code, outcome.effect) == ("ABSTAIN", "NOT_IDENTIFIED", None)
        assert outcome.details["failed_conditions"]
        assert not EFFECT_KEYS & set(_walk_keys(outcome.details["diagnostics"]))


def test_ncr_c7_001_conforms_at_least_two_interventions_are_compared() -> None:
    interventions = [{**INTERVENTION, "value": 0}, INTERVENTION]
    query = _query(intervention=interventions)
    comparison = c7.compare_interventions(query, model=MODEL, factual_rows=ROWS, interventions=interventions)
    assert comparison.status == "ESTIMATED"
    assert comparison.method == "SCM_DO_CONTRAST"
    assert abs(Decimal(comparison.effect) - Decimal("-4")) <= Decimal(MODEL["tolerance"])
    details = comparison.details
    assert details["estimand"] == "ATE"
    assert details["identification_result"]["status"] == "IDENTIFIED"
    assert [entry["value"] for entry in details["interventions"]] == ["0", "1"]
    for key in ("uncertainty", "sensitivity", "diagnostics"):
        assert details[key]
    assert comparison.assumptions
    single = [INTERVENTION]
    rejected = c7.compare_interventions(_query(intervention=single), model=MODEL, factual_rows=ROWS, interventions=single)
    assert (rejected.status, rejected.reason_code) == ("REJECTED", "INTERVENTION_SCHEMA_INVALID")
    confounded = c7.compare_interventions(
        _query(model=CONFOUNDED_MODEL, intervention=interventions), model=CONFOUNDED_MODEL, factual_rows=ROWS, interventions=interventions
    )
    assert (confounded.status, confounded.reason_code, confounded.effect) == ("ABSTAIN", "NOT_IDENTIFIED", None)


def test_ncr_c7_001_conforms_the_engine_port_keeps_abduction_action_and_prediction_distinct() -> None:
    port = c7.CausalEnginePort
    members = {name for name, value in vars(port).items() if callable(value) and not name.startswith("_")}
    assert {"identify", "abduct", "act", "predict"} <= members
    engine = c7.default_engine()
    assert isinstance(engine, port)
    model = c7.StructuralCausalModel.from_document(MODEL)
    with pytest.raises(c7.CapabilityDeferredError) as caught:
        engine.abduct(model, ROWS)
    assert caught.value.element == "ELM-070"
    prediction = engine.predict(engine.act(model, {"expedite": Decimal("1")}), outcome="delay_hours", seed=1, size=4000)
    assert abs(prediction.mean - Decimal("7")) <= Decimal("0.25")


# --- NCR-C7-002: closed reason sets, mapping and precedence ----------------------------------


def _rejected(outcome: CausalOutcome, reason: str) -> None:
    assert (outcome.status, outcome.reason_code, outcome.effect) == ("REJECTED", reason, None)


def _abstained(outcome: CausalOutcome, reason: str) -> None:
    assert (outcome.status, outcome.reason_code, outcome.effect) == ("ABSTAIN", reason, None)
    assert reason in ADD_ABSTAIN_PRECEDENCE


def test_ncr_c7_002_conforms_release_mismatch_is_rejected() -> None:
    _rejected(_estimate(expected_release="sha256:" + "b" * 64), "RELEASE_MISMATCH")


@pytest.mark.parametrize("branch", ["main", "feature/not-a-scenario"])
def test_ncr_c7_002_conforms_main_contamination_is_rejected(branch: str) -> None:
    _rejected(_estimate(branch=branch), "MAIN_CONTAMINATED")


def test_ncr_c7_002_conforms_a_missing_factual_set_is_rejected() -> None:
    _rejected(_estimate(rows=[]), "MISSING_FACTUAL_SET")


def test_ncr_c7_002_conforms_an_invalid_factual_schema_is_rejected() -> None:
    rows = [{key: value for key, value in row.items() if key != "delay_hours"} for row in ROWS]
    _rejected(_estimate(rows=rows), "FACTUAL_SCHEMA_INVALID")


def test_ncr_c7_002_conforms_a_non_binary_treatment_is_rejected_as_factual_schema_invalid() -> None:
    rows = [*ROWS, {"region": "north", "expedite": 2, "delay_hours": "5"}]
    _rejected(_estimate(rows=rows), "FACTUAL_SCHEMA_INVALID")


@pytest.mark.parametrize(
    "intervention",
    [
        {"treatment": "expedite", "value": 1},
        {"treatment": "expedite", "value": 1, "valid_envelope": [0]},
        {"treatment": "expedite", "value": 1, "valid_envelope": ["0", "1"]},
        {"treatment": "expedite", "value": "1", "valid_envelope": [0, 1]},
        {"treatment": "expedite", "value": True, "valid_envelope": [0, 1]},
    ],
)
def test_ncr_c7_002_conforms_a_missing_or_malformed_envelope_or_a_non_numeric_value_is_rejected(intervention: dict[str, Any]) -> None:
    _rejected(_estimate(intervention=intervention), "INTERVENTION_SCHEMA_INVALID")


def test_ncr_c7_002_conforms_a_value_outside_an_explicit_constraint_abstains_outside_validity_envelope() -> None:
    outcome = _estimate(intervention={**INTERVENTION, "value": 2})
    _abstained(outcome, "OUTSIDE_VALIDITY_ENVELOPE")
    assert outcome.details["failed_conditions"]


def test_ncr_c7_002_conforms_unresolved_confounding_abstains_not_identified() -> None:
    _abstained(_estimate(model=CONFOUNDED_MODEL), "NOT_IDENTIFIED")


def test_ncr_c7_002_conforms_a_stratum_without_an_arm_abstains_assumption_violation() -> None:
    rows = [row for row in ROWS if not (row["region"] == "south" and row["expedite"] == 1)]
    outcome = _estimate(rows=rows)
    _abstained(outcome, "ASSUMPTION_VIOLATION")
    assert any("south" in condition for condition in outcome.details["failed_conditions"])


def test_ncr_c7_002_conforms_out_of_distribution_only_with_empirical_support_diagnostics() -> None:
    outcome = _estimate(intervention={**INTERVENTION, "value": 0.5})
    _abstained(outcome, "OUT_OF_DISTRIBUTION")
    diagnostics = outcome.details["diagnostics"]
    assert diagnostics["envelope_constraints_satisfied"] is True
    assert list(diagnostics["empirical_support"]) == ["0", "1"]


def test_ncr_c7_002_conforms_abstain_precedence_between_two_conditions() -> None:
    # positivity failure and an out-of-envelope value: ASSUMPTION_VIOLATION prevails
    rows = [row for row in ROWS if not (row["region"] == "south" and row["expedite"] == 1)]
    outcome = _estimate(rows=rows, intervention={**INTERVENTION, "value": 2})
    _abstained(outcome, "ASSUMPTION_VIOLATION")
    # non-identifiable and out of the envelope: NOT_IDENTIFIED prevails
    _abstained(_estimate(model=CONFOUNDED_MODEL, intervention={**INTERVENTION, "value": 2}), "NOT_IDENTIFIED")
    # out of the envelope wins over out of distribution: they are disjoint by definition
    _abstained(_estimate(intervention={**INTERVENTION, "value": 1.5}), "OUTSIDE_VALIDITY_ENVELOPE")


def test_ncr_c7_002_conforms_rejected_conditions_are_evaluated_before_abstain_conditions() -> None:
    _rejected(_estimate(expected_release="sha256:" + "b" * 64, model=CONFOUNDED_MODEL), "RELEASE_MISMATCH")
    _rejected(_estimate(branch="main", intervention={**INTERVENTION, "value": 2}), "MAIN_CONTAMINATED")


def test_ncr_c7_002_conforms_only_the_closed_sets_are_produced() -> None:
    assert tuple(c7.ABSTAIN_REASON_PRECEDENCE) == ADD_ABSTAIN_PRECEDENCE
    for legacy in ("MAIN_CONTAMINATED", "RELEASE_MISMATCH", "UNRESOLVED_CONFOUNDING", "OUT_OF_DOMAIN", "POSITIVITY_FAILURE"):
        assert legacy not in c7.ABSTAIN_REASON_PRECEDENCE
    source = inspect.getsource(c7)
    for legacy in ("UNRESOLVED_CONFOUNDING", "OUT_OF_DOMAIN", "POSITIVITY_FAILURE"):
        assert legacy not in source


# --- NCR-C7-003: CausalRunOutcome, pins, uncertainty and the immutable SimulationResult --------


@pytest.mark.parametrize("pin", ["model_digest", "data_digest", "intervention_digest"])
def test_ncr_c7_003_conforms_a_pin_mismatch_is_rejected_not_raised(pin: str) -> None:
    query = replace(_query(), **{pin: "0" * 64})
    outcome = estimate_intervention(query, model=MODEL, factual_rows=ROWS, intervention=INTERVENTION)
    _rejected(outcome, f"{pin.removesuffix('_digest').upper()}_PIN_MISMATCH")


def test_ncr_c7_003_conforms_only_the_four_outcome_statuses_exist() -> None:
    assert c7.OUTCOME_STATUSES == frozenset({"ESTIMATED", "ABSTAIN", "REJECTED", "FAILED"})
    produced = {
        _estimate().status,
        _estimate(model=CONFOUNDED_MODEL).status,
        _estimate(branch="main").status,
        _simulate(engine=_FaultyEngine()).status,
    }
    assert produced == set(c7.OUTCOME_STATUSES)


def test_ncr_c7_003_conforms_every_estimate_carries_the_estimated_fields() -> None:
    for outcome in (
        _estimate(),
        _simulate(),
        estimate_uncertainty(_query(), model=MODEL, factual_rows=ROWS, intervention=INTERVENTION),
        estimate_sensitivity(_query(), model=MODEL, factual_rows=ROWS, intervention=INTERVENTION, confounding_shift=Decimal("1")),
    ):
        assert outcome.status == "ESTIMATED"
        assert outcome.method and outcome.effect is not None and outcome.assumptions
        details = outcome.details
        for key in ("identification_result", "uncertainty", "diagnostics", "sensitivity"):
            assert key in details and details[key]
        uncertainty = details["uncertainty"]
        assert uncertainty["method"] and uncertainty["level"]
        low, high = (Decimal(bound) for bound in uncertainty["interval"])
        assert low <= high
        for pin in ("baseline_commit", "scenario_branch", "model_digest", "data_digest", "intervention_digest", "ontology_release_digest", "seed"):
            assert pin in outcome.lineage


def test_ncr_c7_003_conforms_an_abstention_carries_its_fields_and_no_effect() -> None:
    outcome = _estimate(intervention={**INTERVENTION, "value": 2})
    for key in ("diagnostics", "failed_conditions", "evidence_refs", "permissible_next_steps"):
        assert key in outcome.details
    assert outcome.details["permissible_next_steps"]
    assert not EFFECT_KEYS & set(_walk_keys(outcome.details))


class _FaultyEngine:
    """The default engine with a computational fault in prediction."""

    def __init__(self) -> None:
        self._engine = c7.default_engine()

    def identify(self, model: Any, *, treatment: str, outcome: str) -> Any:
        return self._engine.identify(model, treatment=treatment, outcome=outcome)

    def abduct(self, model: Any, factual_rows: Any) -> Any:
        return self._engine.abduct(model, factual_rows)

    def act(self, model: Any, assignments: Any) -> Any:
        return self._engine.act(model, assignments)

    def predict(self, model: Any, *, outcome: str, seed: int, size: int) -> Any:
        raise ArithmeticError("numerical fault in the sampler")


def test_ncr_c7_003_conforms_a_computational_fault_is_failed_with_retry_safety() -> None:
    outcome = _simulate(engine=_FaultyEngine())
    assert (outcome.status, outcome.reason_code, outcome.effect) == ("FAILED", "ENGINE_FAULT", None)
    assert outcome.details["retry_safety"] == "SAFE_TO_RETRY"


def test_ncr_c7_003_conforms_the_simulation_result_is_immutable_and_schema_validated() -> None:
    outcome = _simulate()
    result = c7.SimulationResult.from_outcome(outcome)
    document = result.to_document()
    for key in ("output", "uncertainty", "violations", "validity_status", "lineage", "reproducibility_digest"):
        assert key in document
    assert c7.SimulationResult.from_document(document) == result
    with pytest.raises(FrozenInstanceError):
        result.output = "0"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.lineage["seed"] = 1  # type: ignore[index]
    for missing in ("uncertainty", "lineage", "validity_status"):
        incomplete = {key: value for key, value in document.items() if key != missing}
        with pytest.raises(CausalRuntimeError, match="SIMULATION_RESULT_SCHEMA_INVALID"):
            c7.SimulationResult.from_document(incomplete)
    with pytest.raises(CausalRuntimeError, match="SIMULATION_RESULT_SCHEMA_INVALID"):
        c7.SimulationResult.from_document({**document, "uncertainty": {}})
    with pytest.raises(CausalRuntimeError, match="NOT_ESTIMATED"):
        c7.SimulationResult.from_outcome(_estimate(branch="main"))


def test_ncr_c7_003_conforms_the_outcome_document_is_schema_validated() -> None:
    for outcome in (_estimate(), _estimate(model=CONFOUNDED_MODEL), _estimate(branch="main"), _simulate(engine=_FaultyEngine())):
        c7.validate_outcome_document(c7.outcome_document(outcome))
    abstained = c7.outcome_document(_estimate(model=CONFOUNDED_MODEL))
    leaked = {**abstained, "details": {**abstained["details"], "diagnostics": {"effect_estimate": "-4"}}}
    with pytest.raises(CausalRuntimeError, match="OUTCOME_SCHEMA_INVALID"):
        c7.validate_outcome_document(leaked)
    estimated = c7.outcome_document(_estimate())
    without_uncertainty = {**estimated, "details": {k: v for k, v in estimated["details"].items() if k != "uncertainty"}}
    with pytest.raises(CausalRuntimeError, match="OUTCOME_SCHEMA_INVALID"):
        c7.validate_outcome_document(without_uncertainty)


# --- NCR-C7-005: tolerance and a digest independent of trace identifiers ------------------------


def test_ncr_c7_005_conforms_the_digest_does_not_depend_on_trace_identifiers() -> None:
    first = _estimate()
    second = _estimate(correlation_id="another-correlation", causation_id="urn:ocor:causation:other")
    assert first.reproducibility_digest == second.reproducibility_digest
    assert first.trace["causation_id"] != second.trace["causation_id"]
    assert "causation_id" not in first.lineage and "correlation_id" not in first.lineage
    verify_reproduction(first, second)
    assert canonical_digest(c7.outcome_document(first)) == first.reproducibility_digest


def test_ncr_c7_005_conforms_the_tolerance_is_mandatory_and_declared() -> None:
    without = {key: value for key, value in MODEL.items() if key != "tolerance"}
    _rejected(_estimate(model=without), "MODEL_SCHEMA_INVALID")
    for invalid in ("0", "-1", "abc"):
        _rejected(_estimate(model={**MODEL, "tolerance": invalid}), "MODEL_SCHEMA_INVALID")
    outcome = _simulate()
    assert outcome.details["tolerance"] == "0.25"
    assert outcome.lineage["tolerance"] == "0.25"


class _ShiftedEngine(_FaultyEngine):
    """The default engine on another platform: the prediction differs by ``shift``."""

    def __init__(self, shift: Decimal) -> None:
        super().__init__()
        self._shift = shift

    def predict(self, model: Any, *, outcome: str, seed: int, size: int) -> Any:
        prediction = self._engine.predict(model, outcome=outcome, seed=seed, size=size)
        return replace(prediction, mean=prediction.mean + self._shift)


def test_ncr_c7_005_conforms_reproduction_accepts_differences_within_the_tolerance_only() -> None:
    first = _simulate()
    second = _simulate()
    assert first.reproducibility_digest == second.reproducibility_digest
    verify_reproduction(first, second)
    within = _simulate(engine=_ShiftedEngine(Decimal("0.01")))
    assert within.reproducibility_digest != first.reproducibility_digest
    verify_reproduction(first, within)
    beyond = _simulate(engine=_ShiftedEngine(Decimal("1")))
    with pytest.raises(CausalRuntimeError, match="REPRODUCIBILITY"):
        verify_reproduction(first, beyond)
    with pytest.raises(CausalRuntimeError, match="REPRODUCIBILITY"):
        verify_reproduction(first, replace(first, effect="7.5"))
    with pytest.raises(CausalRuntimeError, match="REPRODUCIBILITY"):
        verify_reproduction(first, _simulate(seed=1))


# --- NCR-C7-006: counterfactual capability deferred in the PoC profile ---------------------------


@pytest.mark.parametrize(
    "branch,unit_index",
    [("scenario/expedite-what-if", 0), ("main", 0), ("scenario/expedite-what-if", 99), ("scenario/expedite-what-if", -1)],
)
def test_ncr_c7_006_conforms_a_valid_counterfactual_query_is_rejected_capability_deferred(branch: str, unit_index: int) -> None:
    rows = _Unreadable(ROWS)
    query = _query(branch=branch, rows=ROWS)
    first = estimate_counterfactual(query, model=MODEL, factual_rows=rows, intervention=INTERVENTION, unit_index=unit_index)
    second = estimate_counterfactual(query, model=MODEL, factual_rows=rows, intervention=INTERVENTION, unit_index=unit_index)
    _rejected(first, "CAPABILITY_DEFERRED")
    assert first.details["element"] == "ELM-070"
    assert first == second and first.reproducibility_digest == second.reproducibility_digest


@pytest.mark.parametrize("unit_index", ["0", True, 1.0, None])
def test_ncr_c7_006_conforms_a_structurally_invalid_counterfactual_query_is_rejected_for_its_schema(unit_index: Any) -> None:
    outcome = estimate_counterfactual(_query(), model=MODEL, factual_rows=_Unreadable(ROWS), intervention=INTERVENTION, unit_index=unit_index)
    _rejected(outcome, "COUNTERFACTUAL_SCHEMA_INVALID")


# --- preventive review OCOR-DEV-REM-0057-1a64cb83f153-pre (P2, P7, P8) --------------------------
#
# NCR-C7-003: a sealed or stored CausalRunOutcome is re-validated at every boundary. A document
# with a non-finite number has no canonical digest: it is refused with the typed error of the
# boundary, never a raw ValueError (outcome_from_document, the SeaweedFS sealed-result adapter).


def _with_nan(document: Mapping[str, Any]) -> dict[str, Any]:
    return {**document, "lineage": {**document["lineage"], "nan_probe": float("nan")}}


def test_ncr_c7_003_conforms_an_outcome_document_with_a_non_finite_number_is_refused_typed() -> None:
    document = c7.outcome_document(_estimate())
    assert c7.outcome_from_document(document, canonical_digest(document)).status == "ESTIMATED"
    for tampered in (_with_nan(document), {**document, "lineage": {**document["lineage"], "probe": float("inf")}}):
        with pytest.raises(CausalRuntimeError):
            c7.outcome_from_document(tampered, canonical_digest(document))


def test_ncr_c7_003_conforms_the_sensitivity_descriptor_carries_decimal_strings_only() -> None:
    document = c7.outcome_document(_estimate())
    c7.validate_outcome_document(document)
    sensitivity = document["details"]["sensitivity"]
    for name, value in (("confounding_shift", 123), ("shifted_effect", float("nan")), ("shifted_effect", "about -3")):
        tampered = {**document, "details": {**document["details"], "sensitivity": {**sensitivity, name: value}}}
        with pytest.raises(CausalRuntimeError, match="OUTCOME_SCHEMA_INVALID"):
            c7.validate_outcome_document(tampered)


@pytest.mark.parametrize(
    ("model", "intervention"),
    [({}, INTERVENTION), ({"model_id": "x"}, INTERVENTION), (MODEL, {"value": "bad"}), (MODEL, {"treatment": "expedite", "value": 1})],
    ids=["empty-model", "malformed-model", "non-numeric-value", "no-envelope"],
)
def test_ncr_c7_006_conforms_a_malformed_counterfactual_model_or_intervention_is_rejected_for_its_schema(
    model: dict[str, Any], intervention: dict[str, Any]
) -> None:
    outcome = estimate_counterfactual(_query(), model=model, factual_rows=_Unreadable(ROWS), intervention=intervention, unit_index=0)
    assert (outcome.status, outcome.reason_code, outcome.effect) == ("REJECTED", "COUNTERFACTUAL_SCHEMA_INVALID", None)
    valid = estimate_counterfactual(_query(), model=MODEL, factual_rows=_Unreadable(ROWS), intervention=INTERVENTION, unit_index=0)
    assert (valid.reason_code, dict(valid.details)) == ("CAPABILITY_DEFERRED", {"element": "ELM-070"})


# P2: the SeaweedFS sealed-result adapter (touched by this unit) checks the structure of every
# S3 response and translates every transport fault. A local responder plays the server: the
# real SeaweedFS cannot be made to send a malformed status line, a truncated body or XML of
# another shape, so this is the local failure handling only; the live server is exercised by
# test_ocor_dev_rem_0040.py and test_ocor_dev_rem_0041_overlay.py.

_S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"
_LOCK_OK = f'<?xml version="1.0" encoding="UTF-8"?><ObjectLockConfiguration xmlns="{_S3_NS}"><ObjectLockEnabled>Enabled</ObjectLockEnabled></ObjectLockConfiguration>'
_VERSIONING_OK = f'<VersioningConfiguration xmlns="{_S3_NS}"><Status>Enabled</Status></VersioningConfiguration>'
_NO_VERSIONS = f'<ListVersionsResult xmlns="{_S3_NS}"><Name>b</Name><IsTruncated>false</IsTruncated></ListVersionsResult>'
_RETENTION_OK = f'<Retention xmlns="{_S3_NS}"><Mode>COMPLIANCE</Mode><RetainUntilDate>2099-01-01T00:00:00Z</RetainUntilDate></Retention>'


def _listing(key: str) -> str:
    return (
        f'<ListVersionsResult xmlns="{_S3_NS}"><IsTruncated>false</IsTruncated>'
        f"<Version><Key>{key}</Key><VersionId>v1</VersionId></Version></ListVersionsResult>"
    )


class _Responder:
    """A local HTTP server answering by query string: ``routes`` maps the first query key
    (``object-lock``, ``versioning``, ``versions``, ``versionId``, ``retention``, ``PUT``)
    to ``(status, headers, body)`` or to raw bytes sent as the whole response."""

    def __init__(self, routes: dict[str, Any]) -> None:
        import socket
        import threading

        self.routes = routes
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(8)
        self.endpoint = f"http://127.0.0.1:{self._socket.getsockname()[1]}"
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _route(self, request_line: str) -> Any:
        method, target = request_line.split(" ")[:2]
        if method == "PUT":
            return self.routes.get("PUT")
        query = target.partition("?")[2]
        for name in ("retention", "versions", "object-lock", "versioning", "versionId"):
            if name + "=" in query.split("&") or any(part.startswith(name + "=") for part in query.split("&")):
                return self.routes.get(name)
        return None

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return
            with connection:
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                head, _, rest = data.partition(b"\r\n\r\n")
                length = next(
                    (int(line.split(b":", 1)[1]) for line in head.split(b"\r\n") if line.lower().startswith(b"content-length:")), 0
                )
                while len(rest) < length:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    rest += chunk
                route = self._route(head.split(b"\r\n", 1)[0].decode("latin-1"))
                if route is None:
                    route = (404, {}, "<Error><Code>NoSuchKey</Code></Error>")
                if isinstance(route, bytes):
                    connection.sendall(route)
                    continue
                status, headers, body = route
                payload = body if isinstance(body, bytes) else body.encode("utf-8")
                lines = [f"HTTP/1.1 {status} X", f"Content-Length: {len(payload)}", "Connection: close"]
                lines += [f"{name}: {value}" for name, value in headers.items()]
                connection.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + payload)

    def close(self) -> None:
        self._socket.close()


@pytest.fixture
def responder() -> Iterator[Any]:
    created: list[_Responder] = []

    def make(**routes: Any) -> _Responder:
        server = _Responder({"object-lock": (200, {}, _LOCK_OK), "versioning": (200, {}, _VERSIONING_OK), **routes})
        created.append(server)
        return server

    yield make
    for server in created:
        server.close()


def _local_store(server: Any) -> Any:
    from datetime import timedelta

    from ocor_runtime.c7.adapters.seaweedfs import SeaweedFSSealedResultStore

    return SeaweedFSSealedResultStore(
        endpoint=server.endpoint, bucket="ocor-c7-local", access_key="local", secret_key="local-secret", retention=timedelta(minutes=1)
    )


def _sealed_code(call: Any) -> str:
    from ocor_runtime.c7.sealed_results import SealedResultError

    with pytest.raises(SealedResultError) as caught:
        call()
    code: str = caught.value.code
    return code


_TRUNCATED_403 = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 500\r\nConnection: close\r\n\r\n<Error><Code>Access"


@pytest.mark.parametrize(
    ("routes", "code"),
    [
        ({"object-lock": b"NOT_HTTP\r\n"}, "STORE_UNAVAILABLE"),
        ({"object-lock": b"HTTP/1.1 200 OK\r\nContent-Length: 400\r\nConnection: close\r\n\r\n<ObjectLock"}, "STORE_UNAVAILABLE"),
        ({"object-lock": _TRUNCATED_403}, "STORE_UNAVAILABLE"),
        ({"object-lock": (200, {}, "<Wrong><ObjectLockEnabled>Enabled</ObjectLockEnabled></Wrong>")}, "UNEXPECTED_RESPONSE"),
        ({"object-lock": (200, {}, "not xml <ObjectLockEnabled>Enabled</ObjectLockEnabled>")}, "UNEXPECTED_RESPONSE"),
        ({"object-lock": (200, {}, f'<ObjectLockConfiguration xmlns="{_S3_NS}"><ObjectLockEnabled>Disabled</ObjectLockEnabled></ObjectLockConfiguration>')},
         "BUCKET_OBJECT_LOCK_DISABLED"),
        ({"versioning": (200, {}, "<Wrong><Status>Enabled</Status></Wrong>")}, "UNEXPECTED_RESPONSE"),
        ({"versioning": (200, {}, f'<VersioningConfiguration xmlns="{_S3_NS}"><Status>Suspended</Status></VersioningConfiguration>')},
         "BUCKET_VERSIONING_DISABLED"),
    ],
    ids=["bad-status-line", "incomplete-read", "truncated-error-body", "lock-wrong-root", "lock-not-xml", "lock-disabled",
         "versioning-wrong-root", "versioning-suspended"],
)
def test_ncr_c7_003_conforms_the_sealed_store_refuses_a_malformed_bucket_answer_typed(
    responder: Any, routes: dict[str, Any], code: str
) -> None:
    assert _sealed_code(lambda: _local_store(responder(**routes)).initialize()) == code
    _local_store(responder()).initialize()


def _local_sealed_payload(outcome: CausalOutcome) -> tuple[str, bytes]:
    from ocor_runtime.c7.adapters.seaweedfs import object_key, sealed_payload

    return object_key(outcome.reproducibility_digest), sealed_payload(outcome)


def test_ncr_c7_003_conforms_the_sealed_store_refuses_a_malformed_read_answer_typed(responder: Any) -> None:
    import hashlib
    import json

    outcome = _estimate()
    key, payload = _local_sealed_payload(outcome)
    good = _local_store(responder(versions=(200, {}, _listing(key)), versionId=(200, {}, payload)))
    good.initialize()
    assert good.read_sealed_result(outcome.reproducibility_digest) == outcome
    wrong_root = _local_store(responder(versions=(200, {}, f"<Wrong><Version><Key>{key}</Key></Version></Wrong>")))
    wrong_root.initialize()
    assert _sealed_code(lambda: wrong_root.read_sealed_result(outcome.reproducibility_digest)) == "UNEXPECTED_RESPONSE"
    truncated = _local_store(
        responder(versions=(200, {}, _listing(key)), versionId=b"HTTP/1.1 200 OK\r\nContent-Length: 9999\r\nConnection: close\r\n\r\n{")
    )
    truncated.initialize()
    assert _sealed_code(lambda: truncated.read_sealed_result(outcome.reproducibility_digest)) == "STORE_UNAVAILABLE"
    body = _with_nan(c7.outcome_document(outcome))
    nan_payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    nan_digest = hashlib.sha256(nan_payload).hexdigest()
    from ocor_runtime.c7.adapters.seaweedfs import object_key

    nan_store = _local_store(responder(versions=(200, {}, _listing(object_key(nan_digest))), versionId=(200, {}, nan_payload)))
    nan_store.initialize()
    assert _sealed_code(lambda: nan_store.read_sealed_result(nan_digest)) == "SEALED_RESULT_TAMPERED"


def test_ncr_c7_003_conforms_the_sealed_store_checks_the_retention_answer_structurally(responder: Any) -> None:
    outcome = _estimate()
    put = (200, {"x-amz-version-id": "v1"}, "")
    good = _local_store(responder(versions=(200, {}, _NO_VERSIONS), PUT=put, retention=(200, {}, _RETENTION_OK)))
    good.initialize()
    assert good.seal_result(outcome).newly_sealed is True
    for answer in ("<Wrong><Mode>COMPLIANCE</Mode></Wrong>", "garbage <Mode>COMPLIANCE</Mode>",
                   f'<Retention xmlns="{_S3_NS}"><Mode>GOVERNANCE</Mode></Retention>'):
        store = _local_store(responder(versions=(200, {}, _NO_VERSIONS), PUT=put, retention=(200, {}, answer)))
        store.initialize()
        assert _sealed_code(lambda store=store: store.seal_result(outcome)) == "RETENTION_NOT_APPLIED"


def test_ncr_c7_003_conforms_an_outcome_without_a_canonical_digest_is_never_sealed() -> None:
    from ocor_runtime.c7.adapters.seaweedfs import sealed_payload

    outcome = _estimate()
    tampered = replace(outcome, lineage=_with_nan(c7.outcome_document(outcome))["lineage"])
    assert _sealed_code(lambda: sealed_payload(tampered)) == "OUTCOME_DIGEST_MISMATCH"
