"""Golden data, metamorphic and reproducibility tests of the causal runtime (OCOR-DEV-REM-0060, NCP-U12, NCR-TESTS-005).

Technique routing of docs/development_methodology/OCOR_TEST_STRATEGY.md:23 ("Causal/analytical logic |
golden data, metamorphic and reproducibility tests") over ``ocor_runtime.c7.runtime``:

* golden data: ``golden/causal_logistics_scm.json`` (sha256 pinned below) holds a registered SCM, a
  factual set, an intervention and the expected outcomes derived analytically, not captured from the
  runtime (the derivation is in the file): the stratified backdoor ATE is -4 and the interventional
  expectations of ``SimulateIntervention`` are 7 and 11 within the model tolerance (Register v1.1 FR-009
  and NFR-007; ADD v1.3 §4.2, ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:2977-3024);
* metamorphic relations of the backdoor estimate: an outcome shift leaves the ATE unchanged, an outcome
  scale multiplies it, a row permutation or duplication leaves it unchanged and swapping the treatment
  arms negates it; of the do-simulation: an intercept shift of the outcome mechanism shifts both
  interventional expectations by the same amount;
* reproducibility: identical pinned inputs reproduce the same digest and ``verify_reproduction`` accepts
  them; a different seed stays within the declared tolerance.
"""

from __future__ import annotations

import copy
import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ocor_runtime.c7 import runtime as c7
from ocor_runtime.c7.runtime import CausalOutcome, CausalQuery, canonical_digest, estimate_intervention, verify_reproduction
from ocor_runtime.kernel.canonical import parse_i_json

GOLDEN = Path(__file__).resolve().parent / "golden/causal_logistics_scm.json"
GOLDEN_SHA256 = "9d951dcb046ceee7928685d186ad83fdeca00da0ce57b8162e2a8f13fafb20e7"
RELEASE = "sha256:" + "a" * 64


def _golden() -> dict[str, Any]:
    raw = GOLDEN.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == GOLDEN_SHA256, "the golden dataset changed"
    return parse_i_json(raw.decode("utf-8"))


def _query(model: Any, rows: Any, intervention: Any, *, seed: int) -> CausalQuery:
    return CausalQuery(
        baseline_commit="urn:ocor:commit:golden:1",
        scenario_branch="scenario/golden-logistics",
        model_digest=canonical_digest(model),
        data_digest=canonical_digest(rows),
        intervention_digest=canonical_digest(intervention),
        ontology_release_digest=RELEASE,
        expected_release_digest=RELEASE,
        treatment="expedite",
        outcome="delay_hours",
        seed=seed,
        correlation_id="018f2f95-01b2-7cc3-8d4e-0000000000aa",
        causation_id="urn:ocor:causation:golden:1",
    )


def _estimate(rows: list[dict[str, Any]], *, model: Any = None) -> CausalOutcome:
    golden = _golden()
    model = golden["model"] if model is None else model
    return estimate_intervention(_query(model, rows, golden["intervention"], seed=golden["seed"]), model=model, factual_rows=rows, intervention=golden["intervention"])


def _simulate(value: int, *, model: Any = None, seed: int | None = None) -> CausalOutcome:
    golden = _golden()
    model = golden["model"] if model is None else model
    intervention = {**golden["intervention"], "value": value}
    query = _query(model, golden["factual_rows"], intervention, seed=golden["seed"] if seed is None else seed)
    return c7.simulate_intervention(query, model=model, factual_rows=golden["factual_rows"], intervention=intervention)


def _effect(outcome: CausalOutcome) -> Decimal:
    assert outcome.status == "ESTIMATED", (outcome.status, outcome.reason_code)
    return Decimal(outcome.effect)


# --- golden data ------------------------------------------------------------------------------


def test_golden_backdoor_estimate_matches_the_analytical_value():
    golden = _golden()
    outcome = _estimate(golden["factual_rows"])
    expected = golden["expected"]["estimate_intervention"]
    assert (outcome.status, outcome.method) == (expected["status"], expected["method"])
    assert _effect(outcome) == Decimal(expected["effect"])


def test_golden_do_simulation_matches_the_analytical_expectations_within_tolerance():
    golden = _golden()
    expected = golden["expected"]["simulate_intervention"]
    tolerance = Decimal(golden["model"]["tolerance"])
    treated, control = _simulate(1), _simulate(0)
    assert treated.method == control.method == expected["method"]
    assert abs(_effect(treated) - Decimal(expected["do_1"])) <= tolerance
    assert abs(_effect(control) - Decimal(expected["do_0"])) <= tolerance


# --- metamorphic relations --------------------------------------------------------------------


def _with_outcome(rows: list[dict[str, Any]], transform: Any) -> list[dict[str, Any]]:
    return [{**row, "delay_hours": str(transform(Decimal(row["delay_hours"])))} for row in rows]


@pytest.mark.parametrize("shift", ["-5", "3", "100.5"])
def test_metamorphic_outcome_shift_leaves_the_backdoor_ate_unchanged(shift: str):
    rows = _golden()["factual_rows"]
    assert _effect(_estimate(_with_outcome(rows, lambda value: value + Decimal(shift)))) == _effect(_estimate(rows))


@pytest.mark.parametrize("scale", ["2", "0.5", "-3"])
def test_metamorphic_outcome_scale_multiplies_the_backdoor_ate(scale: str):
    rows = _golden()["factual_rows"]
    assert _effect(_estimate(_with_outcome(rows, lambda value: value * Decimal(scale)))) == _effect(_estimate(rows)) * Decimal(scale)


def test_metamorphic_row_permutation_and_duplication_leave_the_backdoor_ate_unchanged():
    rows = _golden()["factual_rows"]
    baseline = _effect(_estimate(rows))
    assert _effect(_estimate(list(reversed(rows)))) == baseline
    assert _effect(_estimate(rows[1::2] + rows[0::2])) == baseline
    assert _effect(_estimate(rows + copy.deepcopy(rows))) == baseline


def test_metamorphic_swapping_the_treatment_arms_negates_the_backdoor_ate():
    rows = _golden()["factual_rows"]
    swapped = [{**row, "expedite": 1 - row["expedite"]} for row in rows]
    assert _effect(_estimate(swapped)) == -_effect(_estimate(rows))


@pytest.mark.parametrize("shift", ["5", "-2"])
def test_metamorphic_outcome_intercept_shift_shifts_both_interventional_expectations(shift: str):
    golden = _golden()
    model = copy.deepcopy(golden["model"])
    mechanism = model["endogenous"]["delay_hours"]
    mechanism["intercept"] = str(Decimal(mechanism["intercept"]) + Decimal(shift))
    tolerance = Decimal(golden["model"]["tolerance"])
    for value in (0, 1):
        assert abs(_effect(_simulate(value, model=model)) - _effect(_simulate(value)) - Decimal(shift)) <= tolerance


# --- reproducibility ----------------------------------------------------------------------------


def test_identical_pinned_inputs_reproduce_the_same_outcome_digest():
    first, second = _simulate(1), _simulate(1)
    assert first.reproducibility_digest == second.reproducibility_digest
    verify_reproduction(first, second)
    rows = _golden()["factual_rows"]
    verify_reproduction(_estimate(rows), _estimate(rows))


def test_a_different_seed_stays_within_the_declared_tolerance():
    golden = _golden()
    tolerance = Decimal(golden["model"]["tolerance"])
    assert abs(_effect(_simulate(1, seed=314159)) - _effect(_simulate(1))) <= tolerance
