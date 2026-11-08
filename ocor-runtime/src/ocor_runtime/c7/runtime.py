"""C7 -- causal runtime: interventions on a registered structural causal model.

OCOR-DEV-REM-0057 (NCP-U09 of NORMATIVE-CONFORMANCE-PLAN (2026-10-30)) aligns the
runtime with ADD v1.3 §4.2, LLD v1.1 §2.7 and the PO decision on the plan (point 4,
``NCR-C7-002`` and ``NCR-C7-006``):

- the registered model is an SCM ``M=(U,V,F,P(U))`` (``StructuralCausalModel``):
  endogenous variables ``V`` with their mechanisms ``F``, exogenous variables ``U``
  with ``P(U)``, a mandatory reproducibility tolerance (Register NFR-007 :61);
- the engine port (``CausalEnginePort``) keeps identification, abduction, action and
  prediction distinct; ``do(X=x)`` (action) replaces ``F_X`` with the imposed value
  and removes the edges entering ``X`` (ADD v1.3 :2977); the PoC profile uses action
  and prediction only, abduction is the deferred ``ELM-070`` (ADD v1.3 :3036);
- identification comes from the registered SCM, never from the caller: a
  non-identifiable estimand abstains with ``NOT_IDENTIFIED`` and no estimate;
- every outcome is one of ``ESTIMATED``, ``ABSTAIN``, ``REJECTED`` and ``FAILED``
  (ADD v1.3 :2979-3005), with the closed ``ABSTAIN`` set and precedence of ADD v1.3
  :3007-3022; signature, schema, policy and version-pin errors are ``REJECTED`` and
  are evaluated before the abstention conditions (ADD v1.3 :3024);
- every estimate carries identification, uncertainty, sensitivity, diagnostics,
  assumptions and lineage (Register FR-097 :238); the reproducibility digest covers
  content and version pins, never the trace identifiers, and two runs are equivalent
  when their digests match or their numbers differ within the declared tolerance;
- a query built from a ``ScenarioRunSpec`` and its overlay hypothesis
  (``c7.scenario_run``, ``NCR-C7-004``) carries the run pins into the lineage; the signed
  model, scenario and budget checks of that module return ``REJECTED`` with
  ``MODEL_SIGNATURE_INVALID``, ``SCENARIO_PIN_MISMATCH`` or ``BUDGET_EXCEEDED``
  (Register NFR-030 :228, FR-092 :232); jobs run under ``c7.jobs``.

The legacy ``ocor_runtime.c7_emission`` module is a different C7 concern (durable,
ordered effect emission) and is not touched here.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, NoReturn, Protocol, runtime_checkable

import jsonschema

from ..errors import OCORError

OUTCOME_STATUSES = frozenset({"ESTIMATED", "ABSTAIN", "REJECTED", "FAILED"})
# ADD v1.3 :3007-3020: the closed ABSTAIN.reason_code set, most specific first.
ABSTAIN_REASON_PRECEDENCE = (
    "ASSUMPTION_VIOLATION",
    "NOT_IDENTIFIED",
    "OUTSIDE_VALIDITY_ENVELOPE",
    "OUT_OF_DISTRIBUTION",
    "EXTRAPOLATIVE",
    "NOT_TRANSPORTABLE",
    "INSUFFICIENT_EVIDENCE",
    "STALE_CONTEXT",
)
# ADD v1.3 :3024 and the PO mapping of NCR-C7-002: contract, policy, schema and pin errors.
REJECTED_REASONS = frozenset(
    {
        "MODEL_PIN_MISMATCH",
        "DATA_PIN_MISMATCH",
        "INTERVENTION_PIN_MISMATCH",
        "MODEL_SCHEMA_INVALID",
        "MODEL_SIGNATURE_INVALID",
        "SCENARIO_PIN_MISMATCH",
        "BUDGET_EXCEEDED",
        "INTERVENTION_SCHEMA_INVALID",
        "MAIN_CONTAMINATED",
        "RELEASE_MISMATCH",
        "MISSING_FACTUAL_SET",
        "FACTUAL_SCHEMA_INVALID",
        "COUNTERFACTUAL_SCHEMA_INVALID",
        "CAPABILITY_DEFERRED",
    }
)
FAILED_REASONS = frozenset({"ENGINE_FAULT"})
RETRY_SAFETY = ("SAFE_TO_RETRY", "NOT_SAFE_TO_RETRY")
COUNTERFACTUAL_ELEMENT = "ELM-070"
SCENARIO_BRANCH_PREFIX = "scenario/"
BOOTSTRAP_RESAMPLES = 200
UNCERTAINTY_LEVEL = "0.95"
_Z_95 = 1.959963984540054
_ASSUMPTIONS = ("consistency", "conditional_exchangeability", "positivity")
_COMPUTATIONAL_FAULTS = (ArithmeticError, ValueError, RuntimeError, TypeError, KeyError)
_NEXT_STEPS = {
    "ASSUMPTION_VIOLATION": ("COLLECT_EVIDENCE_FOR_MISSING_ARMS", "HUMAN_REVIEW"),
    "NOT_IDENTIFIED": ("REVISE_CAUSAL_MODEL", "COLLECT_ADJUSTMENT_EVIDENCE", "HUMAN_REVIEW"),
    "OUTSIDE_VALIDITY_ENVELOPE": ("REVISE_INTERVENTION_WITHIN_ENVELOPE", "HUMAN_REVIEW"),
    "OUT_OF_DISTRIBUTION": ("COLLECT_EVIDENCE_AT_INTERVENTION_VALUE", "HUMAN_REVIEW"),
}
_EFFECT_KEYS = ("effect", "effect_estimate", "estimate", "interval", "ci_low", "ci_high", "ranking", "prescription")


class CausalRuntimeError(OCORError):
    """An outcome or result document is invalid, or two runs are not reproductions of
    each other. Never raised for a query: a query always produces an outcome."""


class ModelSchemaError(CausalRuntimeError):
    """The registered causal model is not a valid SCM document."""


class CapabilityDeferredError(CausalRuntimeError):
    """A capability deferred in the PoC profile (ADD v1.3 :3036) was invoked."""

    def __init__(self, element: str) -> None:
        super().__init__(f"CAPABILITY_DEFERRED: {element}")
        self.element = element


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _FrozenDict(dict[str, Any]):
    """A JSON-serialisable mapping that refuses every mutation."""

    def _refuse(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        raise TypeError("a causal outcome is immutable")

    __setitem__ = _refuse
    __delitem__ = _refuse
    __ior__ = _refuse
    clear = _refuse
    pop = _refuse
    popitem = _refuse
    setdefault = _refuse
    update = _refuse


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen = _FrozenDict()
        for key, item in value.items():
            dict.__setitem__(frozen, str(key), _freeze(item))
        return frozen
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def _text(value: Decimal) -> str:
    return format(value, "f")


def _decimal(value: float) -> Decimal:
    return Decimal(repr(round(value, 6))).normalize()


# --- the registered structural causal model ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExogenousVariable:
    """An exogenous variable of ``U`` with its distribution in ``P(U)``."""

    distribution: str
    parameters: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))

    def draw(self, rng: random.Random) -> float:
        if self.distribution == "normal":
            return rng.gauss(float(self.parameters["mean"]), float(self.parameters["sd"]))
        return 1.0 if rng.random() < float(self.parameters["p"]) else 0.0


@dataclass(frozen=True, slots=True)
class Mechanism:
    """The structural equation ``F_V`` of an endogenous variable. ``linear`` is
    ``intercept + sum(coefficient * parent)``, ``threshold`` is 1 when that sum is
    positive and 0 otherwise, ``constant`` is the value imposed by ``do``."""

    mechanism: str
    intercept: Decimal
    parents: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parents", MappingProxyType(dict(self.parents)))

    def evaluate(self, values: Mapping[str, float]) -> float:
        if self.mechanism == "constant":
            return float(self.intercept)
        total = float(self.intercept) + math.fsum(float(weight) * values[parent] for parent, weight in sorted(self.parents.items()))
        if self.mechanism == "threshold":
            return 1.0 if total > 0 else 0.0
        return total


def _model_error(message: str) -> ModelSchemaError:
    return ModelSchemaError(f"MODEL_SCHEMA_INVALID: {message}")


def _model_decimal(name: str, value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise _model_error(f"{name} must be a decimal string or an integer")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise _model_error(f"{name} is not a decimal") from exc
    if not parsed.is_finite():
        raise _model_error(f"{name} must be finite")
    return parsed


def _model_mapping(name: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value or not all(isinstance(key, str) and key for key in value):
        raise _model_error(f"{name} must be a non-empty object with named entries")
    return value


_MODEL_KEYS = frozenset(
    {"model_id", "version", "estimand", "tolerance", "samples", "sensitivity_shift", "exogenous", "endogenous", "observed"}
)


@dataclass(frozen=True, slots=True)
class StructuralCausalModel:
    """A registered SCM ``M=(U,V,F,P(U))``. ``endogenous`` is in topological order."""

    model_id: str
    version: int
    estimand: str
    tolerance: Decimal
    samples: int
    sensitivity_shift: Decimal
    exogenous: Mapping[str, ExogenousVariable]
    endogenous: Mapping[str, Mechanism]
    observed: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "exogenous", MappingProxyType(dict(self.exogenous)))
        object.__setattr__(self, "endogenous", MappingProxyType(dict(self.endogenous)))

    @classmethod
    def from_document(cls, document: object) -> StructuralCausalModel:
        if not isinstance(document, Mapping) or set(document) != _MODEL_KEYS:
            raise _model_error(f"the model must have exactly the keys {sorted(_MODEL_KEYS)}")
        model_id, version, estimand, samples = document["model_id"], document["version"], document["estimand"], document["samples"]
        if not isinstance(model_id, str) or not model_id:
            raise _model_error("model_id must be a non-empty string")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise _model_error("version must be a positive integer")
        if estimand != "ATE":
            raise _model_error("the supported estimand is ATE")
        if isinstance(samples, bool) or not isinstance(samples, int) or not 100 <= samples <= 1_000_000:
            raise _model_error("samples must be an integer between 100 and 1000000")
        tolerance = _model_decimal("tolerance", document["tolerance"])
        if tolerance <= 0:
            raise _model_error("the reproducibility tolerance must be positive")
        sensitivity_shift = _model_decimal("sensitivity_shift", document["sensitivity_shift"])
        exogenous: dict[str, ExogenousVariable] = {}
        for name, spec in _model_mapping("exogenous", document["exogenous"]).items():
            if not isinstance(spec, Mapping) or spec.get("distribution") not in {"normal", "bernoulli"}:
                raise _model_error(f"exogenous {name} needs a normal or bernoulli distribution")
            expected = {"distribution", "mean", "sd"} if spec["distribution"] == "normal" else {"distribution", "p"}
            if set(spec) != expected:
                raise _model_error(f"exogenous {name} must have exactly {sorted(expected)}")
            parameters = {key: _model_decimal(f"{name}.{key}", spec[key]) for key in sorted(expected - {"distribution"})}
            if spec["distribution"] == "normal" and parameters["sd"] <= 0:
                raise _model_error(f"exogenous {name} needs a positive sd")
            if spec["distribution"] == "bernoulli" and not 0 <= parameters["p"] <= 1:
                raise _model_error(f"exogenous {name} needs 0 <= p <= 1")
            exogenous[name] = ExogenousVariable(distribution=str(spec["distribution"]), parameters=parameters)
        declared: dict[str, Mechanism] = {}
        for name, spec in _model_mapping("endogenous", document["endogenous"]).items():
            if name in exogenous:
                raise _model_error(f"{name} is both exogenous and endogenous")
            if not isinstance(spec, Mapping) or set(spec) != {"mechanism", "intercept", "parents"}:
                raise _model_error(f"endogenous {name} must have exactly mechanism, intercept and parents")
            if spec["mechanism"] not in {"linear", "threshold"}:
                raise _model_error(f"endogenous {name} needs a linear or threshold mechanism")
            parents = spec["parents"]
            if not isinstance(parents, Mapping) or not all(isinstance(parent, str) for parent in parents):
                raise _model_error(f"endogenous {name} needs an object of parents")
            declared[name] = Mechanism(
                mechanism=str(spec["mechanism"]),
                intercept=_model_decimal(f"{name}.intercept", spec["intercept"]),
                parents={parent: _model_decimal(f"{name}.{parent}", weight) for parent, weight in parents.items()},
            )
        for name, mechanism in declared.items():
            for parent in mechanism.parents:
                if parent == name or (parent not in declared and parent not in exogenous):
                    raise _model_error(f"{name} has an undeclared or self parent {parent}")
        observed = document["observed"]
        if (
            not isinstance(observed, list)
            or not observed
            or len(set(observed)) != len(observed)
            or not all(isinstance(name, str) and name in declared for name in observed)
        ):
            raise _model_error("observed must list distinct endogenous variables")
        return cls(
            model_id=model_id,
            version=version,
            estimand=estimand,
            tolerance=tolerance,
            samples=samples,
            sensitivity_shift=sensitivity_shift,
            exogenous=exogenous,
            endogenous=_topological(declared),
            observed=tuple(observed),
        )

    def edges(self) -> tuple[tuple[str, str], ...]:
        return tuple((parent, child) for child, mechanism in self.endogenous.items() for parent in sorted(mechanism.parents))

    def do(self, assignments: Mapping[str, Decimal]) -> StructuralCausalModel:
        """``M_do(X=x)``: every assigned ``F_X`` becomes the constant ``x`` with no
        parents; every other mechanism and ``P(U)`` are unchanged."""
        for name in assignments:
            if name not in self.endogenous:
                raise _model_error(f"do() targets the undeclared variable {name}")
        endogenous = {
            name: Mechanism(mechanism="constant", intercept=Decimal(assignments[name]), parents={}) if name in assignments else mechanism
            for name, mechanism in self.endogenous.items()
        }
        return StructuralCausalModel(
            model_id=self.model_id,
            version=self.version,
            estimand=self.estimand,
            tolerance=self.tolerance,
            samples=self.samples,
            sensitivity_shift=self.sensitivity_shift,
            exogenous=self.exogenous,
            endogenous=endogenous,
            observed=self.observed,
        )

    def sample(self, *, seed: int, size: int) -> list[dict[str, float]]:
        """``size`` joint draws: ``U`` from ``P(U)``, then ``V`` through ``F`` in
        topological order, from a PRNG seeded with ``seed``."""
        rng = random.Random(seed)
        rows: list[dict[str, float]] = []
        for _ in range(size):
            values = {name: variable.draw(rng) for name, variable in sorted(self.exogenous.items())}
            for name, mechanism in self.endogenous.items():
                values[name] = mechanism.evaluate(values)
            rows.append({name: values[name] for name in self.endogenous})
        return rows


def _topological(declared: Mapping[str, Mechanism]) -> dict[str, Mechanism]:
    ordered: dict[str, Mechanism] = {}
    remaining = dict(declared)
    while remaining:
        ready = sorted(name for name, mechanism in remaining.items() if all(parent not in remaining for parent in mechanism.parents))
        if not ready:
            raise _model_error("the endogenous mechanisms contain a cycle")
        for name in ready:
            ordered[name] = remaining.pop(name)
    return ordered


# --- the engine port ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Identification:
    """The identification result of an estimand under the registered SCM."""

    identified: bool
    method: str | None
    adjustment_set: tuple[str, ...]
    diagnostics: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


@dataclass(frozen=True, slots=True)
class Prediction:
    """The prediction of one outcome variable under a (possibly intervened) model."""

    outcome: str
    mean: Decimal
    standard_deviation: Decimal
    size: int


@runtime_checkable
class CausalEnginePort(Protocol):
    """The C7 engine port. Identification, abduction, action and prediction stay
    distinct; the PoC profile uses action and prediction only (ADD v1.3 :3036)."""

    def identify(self, model: StructuralCausalModel, *, treatment: str, outcome: str) -> Identification: ...

    def abduct(self, model: StructuralCausalModel, factual_rows: Sequence[Mapping[str, Any]]) -> StructuralCausalModel: ...

    def act(self, model: StructuralCausalModel, assignments: Mapping[str, Decimal]) -> StructuralCausalModel: ...

    def predict(self, model: StructuralCausalModel, *, outcome: str, seed: int, size: int) -> Prediction: ...


@functools.cache
def default_engine() -> CausalEnginePort:
    """The DoWhy (PyWhy) engine, the C7 configuration item of ADD v1.3 :275."""
    from .adapters.dowhy_engine import DoWhyCausalEngine

    return DoWhyCausalEngine()


# --- queries and outcomes ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CausalQuery:
    baseline_commit: str
    scenario_branch: str
    model_digest: str
    data_digest: str
    intervention_digest: str
    ontology_release_digest: str
    expected_release_digest: str
    treatment: str
    outcome: str
    seed: int
    correlation_id: str
    causation_id: str
    # The pins of the ScenarioRunSpec and of the overlay hypothesis the query was built
    # from (``c7.scenario_run``); they enter the lineage, never the trace identifiers.
    run_pins: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_pins", MappingProxyType(_freeze(self.run_pins)))


@dataclass(frozen=True, slots=True)
class CausalOutcome:
    """A ``CausalRunOutcome`` (ADD v1.3 :2979-3005). ``reason_code`` is the
    ``ABSTAIN.reason_code``, the ``REJECTED.contract_or_policy_reason`` or the
    ``FAILED.technical_failure``; ``method`` is the ``estimator_ref`` and ``effect``
    the ``effect_estimate`` of ``ESTIMATED``; ``details`` holds the other fields of the
    status. ``trace`` carries the trace identifiers outside the digest."""

    status: str
    reason_code: str | None
    method: str | None
    effect: str | None
    details: Mapping[str, Any]
    assumptions: tuple[str, ...]
    lineage: Mapping[str, Any]
    reproducibility_digest: str
    trace: Mapping[str, str] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(_freeze(self.details)))
        object.__setattr__(self, "lineage", MappingProxyType(_freeze(self.lineage)))
        object.__setattr__(self, "trace", MappingProxyType(dict(self.trace)))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))


def outcome_document(outcome: CausalOutcome) -> dict[str, Any]:
    """The canonical content of ``outcome``: the preimage of its reproducibility digest."""
    return {
        "status": outcome.status,
        "reason_code": outcome.reason_code,
        "method": outcome.method,
        "effect": outcome.effect,
        "details": _thaw(outcome.details),
        "assumptions": list(outcome.assumptions),
        "lineage": _thaw(outcome.lineage),
    }


_DECIMAL_PATTERN = r"^-?[0-9]+(\.[0-9]+)?$"
_NO_EFFECT: dict[str, Any] = {
    "anyOf": [
        {"type": ["string", "number", "boolean", "null"]},
        {"type": "array", "items": {"$ref": "#/$defs/no_effect"}},
        {
            "type": "object",
            "propertyNames": {"not": {"enum": list(_EFFECT_KEYS)}},
            "additionalProperties": {"$ref": "#/$defs/no_effect"},
        },
    ]
}
_LINEAGE: dict[str, Any] = {
    "type": "object",
    "required": [
        "baseline_commit",
        "scenario_branch",
        "model_digest",
        "data_digest",
        "intervention_digest",
        "ontology_release_digest",
        "seed",
    ],
}
_UNCERTAINTY: dict[str, Any] = {
    "type": "object",
    "required": ["method", "level", "interval"],
    "properties": {
        "method": {"type": "string", "minLength": 1},
        "level": {"type": "string", "pattern": _DECIMAL_PATTERN},
        "interval": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "string", "pattern": _DECIMAL_PATTERN}},
    },
}
_SENSITIVITY: dict[str, Any] = {
    "type": "object",
    "required": ["method", "confounding_shift", "shifted_effect", "sign_flipped"],
    "properties": {
        "method": {"type": "string", "minLength": 1},
        "confounding_shift": {"type": "string", "pattern": _DECIMAL_PATTERN},
        "shifted_effect": {"type": "string", "pattern": _DECIMAL_PATTERN},
        "sign_flipped": {"type": "boolean"},
    },
}
OUTCOME_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$defs": {"no_effect": _NO_EFFECT},
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "reason_code", "method", "effect", "details", "assumptions", "lineage"],
    "properties": {
        "status": {"enum": sorted(OUTCOME_STATUSES)},
        "reason_code": {"type": ["string", "null"]},
        "method": {"type": ["string", "null"]},
        "effect": {"type": ["string", "null"]},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "lineage": _LINEAGE,
        "details": {"type": "object"},
    },
    "allOf": [
        {
            "if": {"properties": {"status": {"const": "ESTIMATED"}}},
            "then": {
                "properties": {
                    "reason_code": {"type": "null"},
                    "method": {"type": "string", "minLength": 1},
                    "effect": {"type": "string", "pattern": _DECIMAL_PATTERN},
                    "assumptions": {"minItems": 1},
                    "lineage": {"required": ["tolerance"]},
                    "details": {
                        "required": ["identification_result", "uncertainty", "sensitivity", "diagnostics", "tolerance"],
                        "properties": {
                            "identification_result": {
                                "type": "object",
                                "required": ["status", "method", "adjustment_set"],
                                "properties": {"status": {"const": "IDENTIFIED"}},
                            },
                            "uncertainty": _UNCERTAINTY,
                            "sensitivity": _SENSITIVITY,
                            "diagnostics": {"type": "object", "minProperties": 1},
                        },
                    },
                }
            },
        },
        {
            "if": {"properties": {"status": {"const": "ABSTAIN"}}},
            "then": {
                "properties": {
                    "reason_code": {"enum": list(ABSTAIN_REASON_PRECEDENCE)},
                    "method": {"type": "null"},
                    "effect": {"type": "null"},
                    "details": {
                        "additionalProperties": False,
                        "required": ["diagnostics", "failed_conditions", "evidence_refs", "permissible_next_steps"],
                        "properties": {
                            "diagnostics": {"type": "object", "$ref": "#/$defs/no_effect"},
                            "failed_conditions": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                            "evidence_refs": {"type": "array", "items": {"type": "string"}},
                            "permissible_next_steps": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                        },
                    },
                }
            },
        },
        {
            "if": {"properties": {"status": {"const": "REJECTED"}}},
            "then": {
                "properties": {
                    "reason_code": {"enum": sorted(REJECTED_REASONS)},
                    "method": {"type": "null"},
                    "effect": {"type": "null"},
                    "details": {"additionalProperties": False, "properties": {"element": {"const": COUNTERFACTUAL_ELEMENT}}},
                }
            },
        },
        {
            "if": {"properties": {"status": {"const": "FAILED"}}},
            "then": {
                "properties": {
                    "reason_code": {"enum": sorted(FAILED_REASONS)},
                    "method": {"type": "null"},
                    "effect": {"type": "null"},
                    "details": {
                        "additionalProperties": False,
                        "required": ["retry_safety"],
                        "properties": {"retry_safety": {"enum": list(RETRY_SAFETY)}},
                    },
                }
            },
        },
    ],
}
_OUTCOME_VALIDATOR = jsonschema.Draft202012Validator(OUTCOME_SCHEMA)


def validate_outcome_document(document: object) -> None:
    """Fail closed unless ``document`` is a complete ``CausalRunOutcome`` of its status;
    an ``ABSTAIN`` carries no effect estimate anywhere in its diagnostics."""
    errors = sorted(_OUTCOME_VALIDATOR.iter_errors(document), key=lambda error: list(error.absolute_path))
    if errors:
        raise CausalRuntimeError(f"OUTCOME_SCHEMA_INVALID: {errors[0].message}")


def outcome_from_document(document: object, reproducibility_digest: str) -> CausalOutcome:
    """Rebuild a sealed outcome after validating its schema and recomputing its digest."""
    validate_outcome_document(document)
    if not isinstance(document, Mapping):
        raise CausalRuntimeError("OUTCOME_SCHEMA_INVALID: the content is not an object")
    try:
        digest = canonical_digest(document)
    except (TypeError, ValueError) as exc:
        raise CausalRuntimeError("OUTCOME_SCHEMA_INVALID: the content has no canonical digest (non-JSON or non-finite value)") from exc
    if digest != reproducibility_digest:
        raise CausalRuntimeError("REPRODUCIBILITY_DIGEST_MISMATCH: the content does not match its digest")
    return CausalOutcome(
        status=document["status"],
        reason_code=document["reason_code"],
        method=document["method"],
        effect=document["effect"],
        details=document["details"],
        assumptions=tuple(document["assumptions"]),
        lineage=document["lineage"],
        reproducibility_digest=reproducibility_digest,
    )


def _lineage(query: CausalQuery, model: StructuralCausalModel | None) -> dict[str, Any]:
    lineage: dict[str, Any] = {
        "baseline_commit": query.baseline_commit,
        "scenario_branch": query.scenario_branch,
        "model_digest": query.model_digest,
        "data_digest": query.data_digest,
        "intervention_digest": query.intervention_digest,
        "ontology_release_digest": query.ontology_release_digest,
        "seed": query.seed,
    }
    if query.run_pins:
        lineage["run"] = _thaw(query.run_pins)
    if model is not None:
        lineage.update(model_id=model.model_id, model_version=model.version, tolerance=_text(model.tolerance))
    return lineage


def _seal(
    query: CausalQuery,
    *,
    status: str,
    reason_code: str | None = None,
    method: str | None = None,
    effect: Decimal | None = None,
    details: Mapping[str, Any] | None = None,
    assumptions: tuple[str, ...] = (),
    model: StructuralCausalModel | None = None,
) -> CausalOutcome:
    body = {
        "status": status,
        "reason_code": reason_code,
        "method": method,
        "effect": _text(effect) if effect is not None else None,
        "details": _thaw(details or {}),
        "assumptions": list(assumptions),
        "lineage": _lineage(query, model),
    }
    validate_outcome_document(body)
    return CausalOutcome(
        status=status,
        reason_code=reason_code,
        method=method,
        effect=body["effect"],
        details=body["details"],
        assumptions=assumptions,
        lineage=body["lineage"],
        reproducibility_digest=canonical_digest(body),
        trace={"correlation_id": query.correlation_id, "causation_id": query.causation_id},
    )


class _Rejected(Exception):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code


class _Fault(Exception):
    pass


@dataclass(frozen=True, slots=True)
class _Abstention:
    reason_code: str
    failed_conditions: tuple[str, ...]
    diagnostics: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _Admitted:
    model: StructuralCausalModel
    identification: Identification
    values: tuple[Decimal, ...]
    strata: dict[tuple[str, ...], dict[int, list[Decimal]]]
    support: tuple[str, ...]


def _number(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    return parsed if parsed.is_finite() else None


def _intervention_value(query: CausalQuery, intervention: object) -> tuple[Decimal, Decimal, Decimal]:
    if (
        not isinstance(intervention, Mapping)
        or not {"value", "valid_envelope"} <= set(intervention) <= {"treatment", "value", "valid_envelope"}
        or intervention.get("treatment", query.treatment) != query.treatment
    ):
        raise _Rejected("INTERVENTION_SCHEMA_INVALID")
    envelope = intervention["valid_envelope"]
    value = _number(intervention["value"])
    if value is None or not isinstance(envelope, list) or len(envelope) != 2:
        raise _Rejected("INTERVENTION_SCHEMA_INVALID")
    low, high = _number(envelope[0]), _number(envelope[1])
    if low is None or high is None or low > high:
        raise _Rejected("INTERVENTION_SCHEMA_INVALID")
    return value, low, high


def _pinned(query: CausalQuery, value: object, pin: str, reason: str, schema_reason: str) -> None:
    try:
        digest = canonical_digest(value)
    except (TypeError, ValueError) as exc:
        raise _Rejected(schema_reason) from exc
    if digest != pin:
        raise _Rejected(reason)


def _guarded(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except _COMPUTATIONAL_FAULTS as exc:
        raise _Fault() from exc


def _admit(
    query: CausalQuery,
    *,
    model: object,
    factual_rows: object,
    interventions: object,
    single: bool,
    engine: CausalEnginePort,
) -> _Admitted:
    """Every REJECTED condition (ADD v1.3 :3024), in order, then the abstention
    conditions with the precedence of ADD v1.3 :3020. Raises ``_Rejected``,
    ``_Abstained`` or ``_Fault``; returns the admitted context otherwise."""
    _pinned(query, model, query.model_digest, "MODEL_PIN_MISMATCH", "MODEL_SCHEMA_INVALID")
    _pinned(query, factual_rows, query.data_digest, "DATA_PIN_MISMATCH", "FACTUAL_SCHEMA_INVALID")
    _pinned(query, interventions, query.intervention_digest, "INTERVENTION_PIN_MISMATCH", "INTERVENTION_SCHEMA_INVALID")
    try:
        scm = StructuralCausalModel.from_document(model)
    except ModelSchemaError as exc:
        raise _Rejected("MODEL_SCHEMA_INVALID") from exc
    if query.treatment not in scm.observed or query.outcome not in scm.observed or query.treatment == query.outcome:
        raise _Rejected("MODEL_SCHEMA_INVALID")
    documents = [interventions] if single else interventions
    if not isinstance(documents, list) or len(documents) < (1 if single else 2):
        raise _Rejected("INTERVENTION_SCHEMA_INVALID")
    parsed = [_intervention_value(query, document) for document in documents]
    values = tuple(value for value, _low, _high in parsed)
    if len(set(values)) != len(values):
        raise _Rejected("INTERVENTION_SCHEMA_INVALID")
    if query.scenario_branch == "main" or not query.scenario_branch.startswith(SCENARIO_BRANCH_PREFIX):
        raise _Rejected("MAIN_CONTAMINATED")
    if query.ontology_release_digest != query.expected_release_digest:
        raise _Rejected("RELEASE_MISMATCH")
    if not isinstance(factual_rows, list):
        raise _Rejected("FACTUAL_SCHEMA_INVALID")
    if not factual_rows:
        raise _Rejected("MISSING_FACTUAL_SET")
    identification: Identification = _guarded(lambda: engine.identify(scm, treatment=query.treatment, outcome=query.outcome))
    adjustment = identification.adjustment_set if identification.identified else ()
    strata: dict[tuple[str, ...], dict[int, list[Decimal]]] = {}
    for row in factual_rows:
        if not isinstance(row, Mapping) or any(name not in row for name in (query.treatment, query.outcome, *adjustment)):
            raise _Rejected("FACTUAL_SCHEMA_INVALID")
        treated = row[query.treatment]
        if isinstance(treated, bool) or treated not in (0, 1) or not isinstance(treated, int):
            raise _Rejected("FACTUAL_SCHEMA_INVALID")
        observed = row[query.outcome]
        try:
            outcome = Decimal(str(observed)) if not isinstance(observed, bool) and isinstance(observed, (int, float, str)) else None
        except InvalidOperation:
            outcome = None
        if outcome is None or not outcome.is_finite():
            raise _Rejected("FACTUAL_SCHEMA_INVALID")
        strata.setdefault(tuple(str(row[name]) for name in adjustment), {0: [], 1: []})[treated].append(outcome)
    support = tuple(sorted({str(arm) for cells in strata.values() for arm, observations in cells.items() if observations}))

    abstentions: list[_Abstention] = []
    missing = [key for key, cells in strata.items() if not cells[0] or not cells[1]]
    if missing:
        conditions = tuple(
            "positivity:" + (",".join(f"{name}={value}" for name, value in zip(adjustment, key, strict=True)) or "population")
            for key in missing
        )
        abstentions.append(
            _Abstention("ASSUMPTION_VIOLATION", conditions, {"strata": len(strata), "strata_without_both_arms": len(missing)})
        )
    if not identification.identified:
        abstentions.append(_Abstention("NOT_IDENTIFIED", ("identification:backdoor_criterion",), dict(identification.diagnostics)))
    outside = [value for value, low, high in parsed if value < low or value > high]
    if outside:
        abstentions.append(
            _Abstention(
                "OUTSIDE_VALIDITY_ENVELOPE",
                tuple(f"validity_envelope:{query.treatment}={_text(value)}" for value in outside),
                {"envelope_constraints_satisfied": False},
            )
        )
    else:
        unsupported = [value for value in values if value not in {Decimal(arm) for arm in support}]
        if unsupported:
            abstentions.append(
                _Abstention(
                    "OUT_OF_DISTRIBUTION",
                    tuple(f"empirical_support:{query.treatment}={_text(value)}" for value in unsupported),
                    {"envelope_constraints_satisfied": True, "empirical_support": list(support)},
                )
            )
    if abstentions:
        raise _Abstained(abstentions)
    return _Admitted(model=scm, identification=identification, values=values, strata=strata, support=support)


class _Abstained(Exception):
    def __init__(self, abstentions: list[_Abstention]) -> None:
        self.abstentions = abstentions


def _abstain(query: CausalQuery, abstained: _Abstained, model: object) -> CausalOutcome:
    ordered = sorted(abstained.abstentions, key=lambda item: ABSTAIN_REASON_PRECEDENCE.index(item.reason_code))
    reason = ordered[0].reason_code
    diagnostics: dict[str, Any] = {"conditions": [item.reason_code for item in ordered]}
    for item in ordered:
        diagnostics.update(_thaw(item.diagnostics))
    try:
        scm: StructuralCausalModel | None = StructuralCausalModel.from_document(model)
    except ModelSchemaError:
        scm = None
    return _seal(
        query,
        status="ABSTAIN",
        reason_code=reason,
        details={
            "diagnostics": diagnostics,
            "failed_conditions": [condition for item in ordered for condition in item.failed_conditions],
            "evidence_refs": [f"urn:ocor:factual-set:sha256:{query.data_digest}"],
            "permissible_next_steps": list(_NEXT_STEPS[reason]),
        },
        model=scm,
    )


def _run(
    query: CausalQuery,
    *,
    model: object,
    factual_rows: object,
    interventions: object,
    single: bool,
    engine: CausalEnginePort | None,
    estimate: Callable[[_Admitted, CausalEnginePort], CausalOutcome],
) -> CausalOutcome:
    active = engine if engine is not None else default_engine()
    try:
        admitted = _admit(query, model=model, factual_rows=factual_rows, interventions=interventions, single=single, engine=active)
        return estimate(admitted, active)
    except _Rejected as rejected:
        return _seal(query, status="REJECTED", reason_code=rejected.reason_code)
    except _Abstained as abstained:
        return _abstain(query, abstained, model)
    except _Fault:
        return _seal(query, status="FAILED", reason_code="ENGINE_FAULT", details={"retry_safety": "SAFE_TO_RETRY"})


# --- estimation --------------------------------------------------------------------------------


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal()) / len(values)


def _backdoor_effect(strata: Mapping[tuple[str, ...], Mapping[int, Sequence[Decimal]]], shift: Decimal = Decimal()) -> Decimal:
    effects = [_mean(cells[1]) - _mean([value + shift for value in cells[0]]) for cells in strata.values()]
    return _mean(effects)


def _bootstrap(admitted: _Admitted, seed: int) -> tuple[Decimal, Decimal]:
    rng = random.Random(seed)
    resampled: list[Decimal] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        effects = []
        for cells in admitted.strata.values():
            control = [rng.choice(cells[0]) for _ in cells[0]]
            treated = [rng.choice(cells[1]) for _ in cells[1]]
            effects.append(_mean(treated) - _mean(control))
        resampled.append(_mean(effects))
    ordered = sorted(resampled)
    return ordered[int(0.025 * len(ordered))], ordered[min(len(ordered) - 1, int(0.975 * len(ordered)))]


def _sensitivity(admitted: _Admitted, shift: Decimal) -> dict[str, Any]:
    effect = _backdoor_effect(admitted.strata)
    shifted = _backdoor_effect(admitted.strata, shift)
    return {
        "method": "ADDITIVE_CONFOUNDING_SHIFT",
        "confounding_shift": _text(shift),
        "shifted_effect": _text(shifted),
        "sign_flipped": (effect > 0) != (shifted > 0),
    }


def _identification(admitted: _Admitted) -> dict[str, Any]:
    return {
        "status": "IDENTIFIED",
        "method": admitted.identification.method,
        "adjustment_set": list(admitted.identification.adjustment_set),
        "diagnostics": _thaw(admitted.identification.diagnostics),
    }


def _diagnostics(admitted: _Admitted, **extra: Any) -> dict[str, Any]:
    return {
        "strata": len(admitted.strata),
        "treated": sum(len(cells[1]) for cells in admitted.strata.values()),
        "control": sum(len(cells[0]) for cells in admitted.strata.values()),
        "empirical_support": list(admitted.support),
        **extra,
    }


def _assumptions(admitted: _Admitted) -> tuple[str, ...]:
    return (*_ASSUMPTIONS, *(f"adjustment:{name}" for name in admitted.identification.adjustment_set))


def _intervention(query: CausalQuery, value: Decimal) -> dict[str, str]:
    return {"treatment": query.treatment, "value": _text(value)}


def _estimated(
    query: CausalQuery, admitted: _Admitted, *, method: str, effect: Decimal, uncertainty: dict[str, Any], shift: Decimal, **extra: Any
) -> CausalOutcome:
    details = {
        "identification_result": _identification(admitted),
        "uncertainty": uncertainty,
        "sensitivity": _sensitivity(admitted, shift),
        "diagnostics": _diagnostics(admitted),
        "tolerance": _text(admitted.model.tolerance),
        **extra,
    }
    return _seal(
        query,
        status="ESTIMATED",
        method=method,
        effect=effect,
        details=details,
        assumptions=_assumptions(admitted),
        model=admitted.model,
    )


def _backdoor_outcome(query: CausalQuery, admitted: _Admitted, *, method: str, shift: Decimal, legacy: bool) -> CausalOutcome:
    effect = _backdoor_effect(admitted.strata)
    low, high = _bootstrap(admitted, query.seed)
    uncertainty = {
        "method": "STRATIFIED_BOOTSTRAP_PERCENTILE",
        "level": UNCERTAINTY_LEVEL,
        "interval": [_text(low), _text(high)],
        "resamples": BOOTSTRAP_RESAMPLES,
    }
    extra: dict[str, Any] = {"intervention": _intervention(query, admitted.values[0])}
    if legacy and method == "BOOTSTRAP_CI":
        extra.update(ci_low=_text(low), ci_high=_text(high), resamples=str(BOOTSTRAP_RESAMPLES))
    if legacy and method == "ADDITIVE_CONFOUNDING_SHIFT_SENSITIVITY":
        sensitivity = _sensitivity(admitted, shift)
        extra.update(
            confounding_shift=sensitivity["confounding_shift"],
            shifted_effect=sensitivity["shifted_effect"],
            sign_flipped=str(sensitivity["sign_flipped"]),
        )
    return _estimated(query, admitted, method=method, effect=effect, uncertainty=uncertainty, shift=shift, **extra)


def estimate_intervention(
    query: CausalQuery, *, model: Any, factual_rows: Any, intervention: Any, engine: CausalEnginePort | None = None
) -> CausalOutcome:
    """The identified average treatment effect of the treatment, estimated from the
    factual set by backdoor adjustment over the adjustment set that identification
    derives from the registered SCM."""
    return _run(
        query,
        model=model,
        factual_rows=factual_rows,
        interventions=intervention,
        single=True,
        engine=engine,
        estimate=lambda admitted, _engine: _backdoor_outcome(
            query, admitted, method="STRATIFIED_BACKDOOR_ATE", shift=admitted.model.sensitivity_shift, legacy=False
        ),
    )


def estimate_uncertainty(
    query: CausalQuery, *, model: Any, factual_rows: Any, intervention: Any, engine: CausalEnginePort | None = None
) -> CausalOutcome:
    """The identified effect with its deterministic stratified bootstrap interval,
    seeded with the pinned ``query.seed``."""
    return _run(
        query,
        model=model,
        factual_rows=factual_rows,
        interventions=intervention,
        single=True,
        engine=engine,
        estimate=lambda admitted, _engine: _backdoor_outcome(
            query, admitted, method="BOOTSTRAP_CI", shift=admitted.model.sensitivity_shift, legacy=True
        ),
    )


def estimate_sensitivity(
    query: CausalQuery,
    *,
    model: Any,
    factual_rows: Any,
    intervention: Any,
    confounding_shift: Decimal,
    engine: CausalEnginePort | None = None,
) -> CausalOutcome:
    """The identified effect with an additive confounding shift of the control arm."""
    return _run(
        query,
        model=model,
        factual_rows=factual_rows,
        interventions=intervention,
        single=True,
        engine=engine,
        estimate=lambda admitted, _engine: _backdoor_outcome(
            query, admitted, method="ADDITIVE_CONFOUNDING_SHIFT_SENSITIVITY", shift=confounding_shift, legacy=True
        ),
    )


def _predict(query: CausalQuery, admitted: _Admitted, engine: CausalEnginePort, value: Decimal) -> Prediction:
    def call() -> Prediction:
        intervened = engine.act(admitted.model, {query.treatment: value})
        return engine.predict(intervened, outcome=query.outcome, seed=query.seed, size=admitted.model.samples)

    prediction: Prediction = _guarded(call)
    return prediction


def _half_width(*predictions: Prediction) -> Decimal:
    variance = math.fsum(float(item.standard_deviation) ** 2 / item.size for item in predictions)
    return _decimal(_Z_95 * math.sqrt(variance))


def simulate_intervention(
    query: CausalQuery, *, model: Any, factual_rows: Any, intervention: Any, engine: CausalEnginePort | None = None
) -> CausalOutcome:
    """``SimulateIntervention(do(X=x))``: the expectation of the outcome under the
    intervened model ``M_do(X=x)`` (action, then prediction), after identification
    and the validity envelope."""

    def estimate(admitted: _Admitted, active: CausalEnginePort) -> CausalOutcome:
        prediction = _predict(query, admitted, active, admitted.values[0])
        half = _half_width(prediction)
        uncertainty = {
            "method": "MONTE_CARLO_NORMAL_INTERVAL",
            "level": UNCERTAINTY_LEVEL,
            "interval": [_text(prediction.mean - half), _text(prediction.mean + half)],
            "samples": prediction.size,
        }
        return _estimated(
            query,
            admitted,
            method="SCM_DO_MONTE_CARLO",
            effect=prediction.mean,
            uncertainty=uncertainty,
            shift=admitted.model.sensitivity_shift,
            intervention=_intervention(query, admitted.values[0]),
        )

    return _run(
        query, model=model, factual_rows=factual_rows, interventions=intervention, single=True, engine=engine, estimate=estimate
    )


def compare_interventions(
    query: CausalQuery, *, model: Any, factual_rows: Any, interventions: Any, engine: CausalEnginePort | None = None
) -> CausalOutcome:
    """The comparison of at least two simulated interventions on the same treatment
    (Register FR-009 :60): ``effect`` is the contrast of the second intervention
    against the first, every intervention keeps its expectation and interval."""

    def estimate(admitted: _Admitted, active: CausalEnginePort) -> CausalOutcome:
        predictions = [_predict(query, admitted, active, value) for value in admitted.values]
        reference = predictions[0]
        entries = []
        for value, prediction in zip(admitted.values, predictions, strict=True):
            half = _half_width(prediction)
            entries.append(
                {
                    "value": _text(value),
                    "expectation": _text(prediction.mean),
                    "interval": [_text(prediction.mean - half), _text(prediction.mean + half)],
                }
            )
        contrasts = [
            {"reference": _text(admitted.values[0]), "value": _text(value), "contrast": _text(prediction.mean - reference.mean)}
            for value, prediction in zip(admitted.values[1:], predictions[1:], strict=True)
        ]
        contrast = predictions[1].mean - reference.mean
        half = _half_width(reference, predictions[1])
        uncertainty = {
            "method": "MONTE_CARLO_NORMAL_INTERVAL",
            "level": UNCERTAINTY_LEVEL,
            "interval": [_text(contrast - half), _text(contrast + half)],
            "samples": reference.size,
        }
        return _estimated(
            query,
            admitted,
            method="SCM_DO_CONTRAST",
            effect=contrast,
            uncertainty=uncertainty,
            shift=admitted.model.sensitivity_shift,
            estimand=admitted.model.estimand,
            interventions=entries,
            contrasts=contrasts,
        )

    return _run(
        query, model=model, factual_rows=factual_rows, interventions=interventions, single=False, engine=engine, estimate=estimate
    )


def _counterfactual_well_formed(query: CausalQuery, model: Any, intervention: Any, unit_index: Any) -> bool:
    """The structure of a unit-level counterfactual query, checked before the deferral: a
    registered SCM document, an intervention of the query's treatment with a numeric value
    and validity envelope, and an integer unit index. The factual set is never read."""
    if not isinstance(model, Mapping) or type(unit_index) is not int:
        return False
    try:
        StructuralCausalModel.from_document(model)
        _intervention_value(query, intervention)
    except (ModelSchemaError, _Rejected):
        return False
    return True


def estimate_counterfactual(
    query: CausalQuery, *, model: Any, factual_rows: Any, intervention: Any, unit_index: Any
) -> CausalOutcome:
    """A unit-level counterfactual query. ``ELM-070`` is deferred in the PoC profile
    (ADD v1.3 :3036; PO decision on NCR-C7-006, option A): a structurally valid query
    is ``REJECTED{CAPABILITY_DEFERRED, ELM-070}`` without reading the factual set, on
    any branch and for any unit index; a structurally invalid one is rejected for its
    schema error."""
    if not isinstance(query, CausalQuery):
        raise CausalRuntimeError("COUNTERFACTUAL_SCHEMA_INVALID: the query is not a CausalQuery")
    if not _counterfactual_well_formed(query, model, intervention, unit_index):
        return _seal(query, status="REJECTED", reason_code="COUNTERFACTUAL_SCHEMA_INVALID")
    return _seal(query, status="REJECTED", reason_code="CAPABILITY_DEFERRED", details={"element": COUNTERFACTUAL_ELEMENT})


# --- reproducibility ---------------------------------------------------------------------------


def _as_decimal(value: object) -> Decimal | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _within(first: Any, second: Any, tolerance: Decimal) -> bool:
    if isinstance(first, Mapping) and isinstance(second, Mapping):
        return set(first) == set(second) and all(_within(first[key], second[key], tolerance) for key in first)
    if isinstance(first, (list, tuple)) and isinstance(second, (list, tuple)):
        return len(first) == len(second) and all(_within(a, b, tolerance) for a, b in zip(first, second, strict=True))
    left, right = _as_decimal(first), _as_decimal(second)
    if left is not None and right is not None:
        return abs(left - right) <= tolerance
    return bool(first == second) and type(first) is type(second)


def verify_reproduction(first: CausalOutcome, second: CausalOutcome) -> None:
    """Two runs with identical inputs and artefacts reproduce each other when their
    digests match or, for the numbers of stochastic components, when they differ
    within the tolerance declared by the model (Register NFR-007 :61). A tampered
    outcome, a different input pin or a difference beyond the tolerance is rejected."""
    documents = [outcome_document(first), outcome_document(second)]
    for outcome, document in zip((first, second), documents, strict=True):
        if canonical_digest(document) != outcome.reproducibility_digest:
            raise CausalRuntimeError("REPRODUCIBILITY_DIGEST_MISMATCH: an outcome does not match its digest")
    if first.reproducibility_digest == second.reproducibility_digest:
        return
    left, right = documents
    if left["lineage"] != right["lineage"] or "tolerance" not in left["lineage"]:
        raise CausalRuntimeError("REPRODUCIBILITY_DIGEST_MISMATCH: the runs do not have identical inputs")
    tolerance = Decimal(left["lineage"]["tolerance"])
    if not _within(left, right, tolerance):
        raise CausalRuntimeError("REPRODUCIBILITY_DIGEST_MISMATCH: the runs differ beyond the declared tolerance")


# --- the immutable SimulationResult --------------------------------------------------------------


SIMULATION_RESULT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "output",
        "estimator_ref",
        "uncertainty",
        "sensitivity",
        "violations",
        "validity_status",
        "lineage",
        "reproducibility_digest",
    ],
    "properties": {
        "output": {"type": "string", "pattern": _DECIMAL_PATTERN},
        "estimator_ref": {"type": "string", "minLength": 1},
        "uncertainty": _UNCERTAINTY,
        "sensitivity": _SENSITIVITY,
        "violations": {"type": "array", "items": {"type": "string"}},
        "validity_status": {"enum": ["WITHIN_VALIDITY_ENVELOPE"]},
        "lineage": {**_LINEAGE, "required": [*_LINEAGE["required"], "tolerance"]},
        "reproducibility_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}
_SIMULATION_RESULT_VALIDATOR = jsonschema.Draft202012Validator(SIMULATION_RESULT_SCHEMA)


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """The immutable result of an estimate (ADD v1.3 §4.2; Register FR-093 :233):
    output, uncertainty, violations, validity status, lineage with every version pin."""

    output: str
    estimator_ref: str
    uncertainty: Mapping[str, Any]
    sensitivity: Mapping[str, Any]
    violations: tuple[str, ...]
    validity_status: str
    lineage: Mapping[str, Any]
    reproducibility_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "uncertainty", MappingProxyType(_freeze(self.uncertainty)))
        object.__setattr__(self, "sensitivity", MappingProxyType(_freeze(self.sensitivity)))
        object.__setattr__(self, "lineage", MappingProxyType(_freeze(self.lineage)))
        object.__setattr__(self, "violations", tuple(self.violations))

    @classmethod
    def from_outcome(cls, outcome: CausalOutcome) -> SimulationResult:
        if outcome.status != "ESTIMATED" or outcome.effect is None or outcome.method is None:
            raise CausalRuntimeError("NOT_ESTIMATED: only an ESTIMATED outcome produces a SimulationResult")
        return cls.from_document(
            {
                "output": outcome.effect,
                "estimator_ref": outcome.method,
                "uncertainty": _thaw(outcome.details["uncertainty"]),
                "sensitivity": _thaw(outcome.details["sensitivity"]),
                "violations": [],
                "validity_status": "WITHIN_VALIDITY_ENVELOPE",
                "lineage": _thaw(outcome.lineage),
                "reproducibility_digest": outcome.reproducibility_digest,
            }
        )

    @classmethod
    def from_document(cls, document: object) -> SimulationResult:
        errors = sorted(_SIMULATION_RESULT_VALIDATOR.iter_errors(document), key=lambda error: list(error.absolute_path))
        if errors:
            raise CausalRuntimeError(f"SIMULATION_RESULT_SCHEMA_INVALID: {errors[0].message}")
        if not isinstance(document, Mapping):
            raise CausalRuntimeError("SIMULATION_RESULT_SCHEMA_INVALID: the result is not an object")
        return cls(
            output=document["output"],
            estimator_ref=document["estimator_ref"],
            uncertainty=document["uncertainty"],
            sensitivity=document["sensitivity"],
            violations=tuple(document["violations"]),
            validity_status=document["validity_status"],
            lineage=document["lineage"],
            reproducibility_digest=document["reproducibility_digest"],
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "estimator_ref": self.estimator_ref,
            "uncertainty": _thaw(self.uncertainty),
            "sensitivity": _thaw(self.sensitivity),
            "violations": list(self.violations),
            "validity_status": self.validity_status,
            "lineage": _thaw(self.lineage),
            "reproducibility_digest": self.reproducibility_digest,
        }
