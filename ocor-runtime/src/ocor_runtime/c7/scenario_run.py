"""C7 scenario runs: the immutable ``ScenarioRunSpec`` and the signed causal model.

OCOR-DEV-REM-0057 (NCP-U09 of NORMATIVE-CONFORMANCE-PLAN (2026-10-30), ``NCR-C7-004`` and
the ``NFR-030`` part of ``NCR-C7-003``):

- every run is described by an immutable ``ScenarioRunSpec`` with exactly the fields of
  ADD v1.3 §4.2 :2949-2961 (Register FR-092 :232: baseline, branch/world, ontology
  release, logic, causal model, policy snapshot, seed, assumptions, horizon, input and
  budget are pinned); its ``digest`` covers every pin and never the trace identifiers;
- the ``CausalQuery`` is built from the spec and from the hypothesis read through the
  ``ScenarioOverlayStore`` at a pinned revision (``read_at`` verifies the delta chain),
  never from caller-declared fields (LLD v1.1 :177: baseline commit, scenario branch,
  model and release digests, estimand, treatment, outcome, population, factual set,
  assumptions, seed, validity envelope and resource budget);
- the causal model is a content-addressed artefact signed in a DSSE envelope with
  Ed25519 (``c1.signing``); an invalid signature, an unknown or revoked key or a payload
  whose digest is not the pinned ``causal_model_digest`` blocks the run with ``REJECTED``
  (Register NFR-030 :228; ADD v1.3 :3024). Every digest is recomputed here, at the
  boundary, and never taken from the caller.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

from ..c1.signing import dsse_pae, ed25519_verify
from ..kernel.governed_context import GCS_FIELDS, GovernedContext, GovernedContextError
from .runtime import (
    CausalOutcome,
    CausalQuery,
    CausalRuntimeError,
    _freeze,
    _seal,
    _thaw,
    canonical_digest,
    compare_interventions,
    estimate_intervention,
    simulate_intervention,
)
from .scenario_overlay import OverlayView, ScenarioBranch

RUN_SPEC_FIELDS = (
    "scenario_id",
    "parent_scenario_id",
    "run_id",
    "canonical_branch",
    "canonical_commit_ref",
    "projection_watermarks",
    "ontology_release_digest",
    "logic_bundle_digest",
    "causal_model_digest",
    "policy_bundle_digest",
    "assumption_set_ref",
    "input_digest",
    "evidence_refs",
    "seed",
    "time_horizon",
    "validity_at",
    "budget",
    "governed_context",
)
# ADD v1.3 :2959: the governed context is the complete canonical record of §1.4
# (:181-199), the closed GovernedContext v1.2, whose release and policy pins are the run's.
GOVERNED_CONTEXT_FIELDS = GCS_FIELDS
TRACE_FIELDS = frozenset({"correlation_id"})
BUDGET_FIELDS = frozenset({"max_runtime_seconds", "max_samples"})
CAUSAL_MODEL_PAYLOAD_TYPE = "application/vnd.ocor.causal-model.v1+json"
QUERY_DELTA_KIND = "causal_query"
QUERY_DELTA_FIELDS = frozenset({"kind", "operation", "treatment", "outcome", "estimand", "population", "interventions"})
OPERATIONS = frozenset({"estimate_intervention", "simulate_intervention", "compare_interventions"})
QUERY_FIELDS = tuple(name for name in CausalQuery.__dataclass_fields__ if name != "run_pins")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_DURATION = re.compile(r"P(?=\d|T\d)(?:\d+D)?(?:T(?=\d)(?:\d+H)?(?:\d+M)?(?:\d+S)?)?")
MAX_RUNTIME_SECONDS = 86_400


class ScenarioRunError(CausalRuntimeError):
    """A scenario run specification or a signed model is not admissible. ``code`` names
    the reason; the message never carries key material or payloads."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _invalid(message: str) -> ScenarioRunError:
    return ScenarioRunError("RUN_SPEC_INVALID", message)


def _text(document: Mapping[str, Any], name: str) -> str:
    value = document[name]
    if not isinstance(value, str) or not value or value != value.strip():
        raise _invalid(f"{name} must be a non-empty string without surrounding blanks")
    return value


def _hex64(document: Mapping[str, Any], name: str) -> str:
    value = _text(document, name)
    if _HEX64.fullmatch(value) is None:
        raise _invalid(f"{name} must be a lowercase sha256 hex digest")
    return value


def _count(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise _invalid(f"{name} must be an integer between {minimum} and {maximum}")
    return value


def _governed_context(document: Mapping[str, Any]) -> dict[str, Any]:
    """The closed GovernedContext v1.2 record of ADD v1.3 §1.4, validated by the kernel
    codec (exact fields, ``urn:sha256`` marking and pins, non-empty arrays without
    duplicates, compartments in canonical order) and bound to the run: its release and
    policy pins are the spec's and its actor chain ends with the effective principal."""
    context = document["governed_context"]
    if not isinstance(context, Mapping):
        raise _invalid("governed_context must be the GovernedContext v1.2 record")
    try:
        record = GovernedContext.from_mapping(context)
    except GovernedContextError as exc:
        raise _invalid(f"governed_context is not the closed GovernedContext v1.2 record ({exc.code})") from exc
    for name in GCS_FIELDS:
        value = context[name]
        if isinstance(value, str) and value != value.strip():
            raise _invalid(f"governed_context.{name} must not carry surrounding blanks")
    if list(record.compartments) != list(context["compartments"]):
        raise _invalid("governed_context.compartments must be in canonical order")
    if (record.ontology_release_digest, record.policy_bundle_digest) != (
        document["ontology_release_digest"],
        document["policy_bundle_digest"],
    ):
        raise _invalid("governed_context release and policy pins must be the pins of the run")
    if record.actor_chain[-1] != record.effective_principal_id:
        raise _invalid("governed_context.actor_chain must end with the effective principal")
    return record.to_mapping()


@dataclass(frozen=True, slots=True)
class ScenarioRunSpec:
    """The immutable run specification of ADD v1.3 §4.2 :2949-2961."""

    scenario_id: str
    parent_scenario_id: str | None
    run_id: str
    canonical_branch: str
    canonical_commit_ref: str
    projection_watermarks: Mapping[str, int]
    ontology_release_digest: str
    logic_bundle_digest: str
    causal_model_digest: str
    policy_bundle_digest: str
    assumption_set_ref: str
    input_digest: str
    evidence_refs: tuple[str, ...]
    seed: int
    time_horizon: str
    validity_at: str
    budget: Mapping[str, int]
    governed_context: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "projection_watermarks", MappingProxyType(dict(self.projection_watermarks)))
        object.__setattr__(self, "budget", MappingProxyType(dict(self.budget)))
        object.__setattr__(self, "governed_context", MappingProxyType(_freeze(self.governed_context)))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))

    @classmethod
    def from_document(cls, document: object) -> ScenarioRunSpec:
        """Fail closed unless ``document`` has exactly the ADD fields with their shapes;
        nothing is coerced."""
        if not isinstance(document, Mapping) or set(document) != set(RUN_SPEC_FIELDS):
            raise _invalid(f"the specification must have exactly the fields {sorted(RUN_SPEC_FIELDS)}")
        parent = document["parent_scenario_id"]
        if parent is not None and (not isinstance(parent, str) or not parent):
            raise _invalid("parent_scenario_id must be null or a non-empty string")
        if _text(document, "canonical_branch") != "main":
            raise _invalid("canonical_branch must be main: the baseline is a commit of the canonical branch")
        watermarks = document["projection_watermarks"]
        if not isinstance(watermarks, Mapping) or not all(isinstance(key, str) and key for key in watermarks):
            raise _invalid("projection_watermarks must be an object of named projections")
        for key, value in watermarks.items():
            _count(value, f"projection_watermarks.{key}", minimum=0, maximum=2**63 - 1)
        evidence = document["evidence_refs"]
        if not isinstance(evidence, list) or not all(isinstance(item, str) and item for item in evidence):
            raise _invalid("evidence_refs must be a list of non-empty strings")
        if len(set(evidence)) != len(evidence):
            raise _invalid("evidence_refs must be distinct")
        horizon = _text(document, "time_horizon")
        if _DURATION.fullmatch(horizon) is None:
            raise _invalid("time_horizon must be an ISO 8601 duration of days, hours, minutes and seconds")
        validity_at = _text(document, "validity_at")
        try:
            instant = datetime.fromisoformat(validity_at)
        except ValueError as exc:
            raise _invalid("validity_at must be an ISO 8601 instant") from exc
        if instant.utcoffset() is None:
            raise _invalid("validity_at must carry a UTC offset")
        budget = document["budget"]
        if not isinstance(budget, Mapping) or set(budget) != BUDGET_FIELDS:
            raise _invalid(f"budget must have exactly {sorted(BUDGET_FIELDS)}")
        _count(budget["max_runtime_seconds"], "budget.max_runtime_seconds", minimum=1, maximum=MAX_RUNTIME_SECONDS)
        _count(budget["max_samples"], "budget.max_samples", minimum=1, maximum=1_000_000)
        context = _governed_context(document)
        return cls(
            scenario_id=_text(document, "scenario_id"),
            parent_scenario_id=parent,
            run_id=_text(document, "run_id"),
            canonical_branch="main",
            canonical_commit_ref=_text(document, "canonical_commit_ref"),
            projection_watermarks=dict(watermarks),
            ontology_release_digest=_text(document, "ontology_release_digest"),
            logic_bundle_digest=_text(document, "logic_bundle_digest"),
            causal_model_digest=_hex64(document, "causal_model_digest"),
            policy_bundle_digest=_text(document, "policy_bundle_digest"),
            assumption_set_ref=_text(document, "assumption_set_ref"),
            input_digest=_hex64(document, "input_digest"),
            evidence_refs=tuple(evidence),
            seed=_count(document["seed"], "seed", minimum=0, maximum=2**63 - 1),
            time_horizon=horizon,
            validity_at=validity_at,
            budget=dict(budget),
            governed_context=context,
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "parent_scenario_id": self.parent_scenario_id,
            "run_id": self.run_id,
            "canonical_branch": self.canonical_branch,
            "canonical_commit_ref": self.canonical_commit_ref,
            "projection_watermarks": dict(self.projection_watermarks),
            "ontology_release_digest": self.ontology_release_digest,
            "logic_bundle_digest": self.logic_bundle_digest,
            "causal_model_digest": self.causal_model_digest,
            "policy_bundle_digest": self.policy_bundle_digest,
            "assumption_set_ref": self.assumption_set_ref,
            "input_digest": self.input_digest,
            "evidence_refs": list(self.evidence_refs),
            "seed": self.seed,
            "time_horizon": self.time_horizon,
            "validity_at": self.validity_at,
            "budget": dict(self.budget),
            "governed_context": _thaw(self.governed_context),
        }

    def pins(self) -> dict[str, Any]:
        """Every version pin of the run: the document without the trace identifiers."""
        document = self.to_document()
        document["governed_context"] = {
            key: value for key, value in document["governed_context"].items() if key not in TRACE_FIELDS
        }
        return document

    @property
    def digest(self) -> str:
        """The content address of the run: every pin, never a trace identifier."""
        return canonical_digest(self.pins())

    @property
    def principal(self) -> str:
        return str(self.governed_context["effective_principal_id"])


# --- the signed causal model (NFR-030) ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CausalModelTrustRoot:
    """The Ed25519 public keys trusted to sign causal models, by key id, and the revoked
    key ids. Configured by the deployment, never by the caller of a run."""

    keys: Mapping[str, bytes]
    revoked_keyids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.keys, Mapping) or not self.keys:
            raise ScenarioRunError("TRUST_ROOT_INVALID", "at least one trusted key is required")
        for keyid, key in self.keys.items():
            if not isinstance(keyid, str) or not keyid or not isinstance(key, bytes) or len(key) != 32:
                raise ScenarioRunError("TRUST_ROOT_INVALID", "keys must map key ids to 32-byte Ed25519 public keys")
        object.__setattr__(self, "keys", MappingProxyType(dict(self.keys)))
        object.__setattr__(self, "revoked_keyids", frozenset(self.revoked_keyids))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sign_causal_model(model: Mapping[str, Any], *, signer: Any, keyid: str) -> dict[str, Any]:
    """The DSSE envelope of the canonical model document, signed by ``signer`` (an
    ``Ed25519SigningKey``)."""
    payload = _canonical_bytes(_thaw(model))
    signature = signer.sign(dsse_pae(CAUSAL_MODEL_PAYLOAD_TYPE, payload))
    return {
        "payloadType": CAUSAL_MODEL_PAYLOAD_TYPE,
        "payload": base64.b64encode(payload).decode("ascii"),
        "signatures": [{"keyid": keyid, "sig": base64.b64encode(signature).decode("ascii")}],
    }


def _signature_invalid(message: str) -> ScenarioRunError:
    return ScenarioRunError("MODEL_SIGNATURE_INVALID", message)


def _b64(value: object, name: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise _signature_invalid(f"{name} must be a non-empty base64 string")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise _signature_invalid(f"{name} is not valid base64") from exc


def verify_causal_model(envelope: object, trust_root: CausalModelTrustRoot, *, expected_digest: str) -> dict[str, Any]:
    """The model document of a DSSE envelope after verifying, here: the payload type,
    exactly one signature by a trusted, non-revoked key over the DSSE PAE, a canonical
    JSON payload, and the recomputed digest equal to ``expected_digest``. Raises
    ``MODEL_SIGNATURE_INVALID`` or ``MODEL_PIN_MISMATCH``."""
    if not isinstance(trust_root, CausalModelTrustRoot):
        raise ScenarioRunError("TRUST_ROOT_INVALID", "a CausalModelTrustRoot is required")
    if not isinstance(envelope, Mapping) or set(envelope) != {"payloadType", "payload", "signatures"}:
        raise _signature_invalid("the envelope must have exactly payloadType, payload and signatures")
    if envelope["payloadType"] != CAUSAL_MODEL_PAYLOAD_TYPE:
        raise _signature_invalid("unexpected payload type")
    payload = _b64(envelope["payload"], "payload")
    signatures = envelope["signatures"]
    if not isinstance(signatures, list) or len(signatures) != 1:
        raise _signature_invalid("exactly one signature is required")
    entry = signatures[0]
    if not isinstance(entry, Mapping) or set(entry) != {"keyid", "sig"} or not isinstance(entry["keyid"], str):
        raise _signature_invalid("a signature must have exactly keyid and sig")
    keyid = entry["keyid"]
    if keyid in trust_root.revoked_keyids:
        raise _signature_invalid("the signing key is revoked")
    public_key = trust_root.keys.get(keyid)
    if public_key is None:
        raise _signature_invalid("the signing key is not trusted")
    if not ed25519_verify(public_key, dsse_pae(CAUSAL_MODEL_PAYLOAD_TYPE, payload), _b64(entry["sig"], "sig")):
        raise _signature_invalid("the signature does not verify")
    try:
        model = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _signature_invalid("the signed payload is not JSON") from exc
    if not isinstance(model, dict) or _canonical_bytes(model) != payload:
        raise _signature_invalid("the signed payload is not a canonical JSON object")
    if canonical_digest(model) != expected_digest:
        raise ScenarioRunError("MODEL_PIN_MISMATCH", "the signed model is not the pinned causal model")
    return model


# --- the query built from the spec and the overlay -----------------------------------------------


@dataclass(frozen=True, slots=True)
class PreparedRun:
    """A run admitted by the spec, the signature and the overlay: the operation, the
    query and the verified inputs. Plain data, so a worker process can execute it."""

    operation: str
    query: CausalQuery
    model: Mapping[str, Any]
    factual_rows: Sequence[Any]
    interventions: Any

    def to_payload(self) -> dict[str, Any]:
        """The run as plain JSON-compatible data (for a worker process)."""
        query = {name: getattr(self.query, name) for name in QUERY_FIELDS}
        query["run_pins"] = _thaw(self.query.run_pins)
        return {
            "operation": self.operation,
            "query": query,
            "model": _thaw(self.model),
            "factual_rows": _thaw(self.factual_rows),
            "interventions": _thaw(self.interventions),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> PreparedRun:
        return cls(
            operation=payload["operation"],
            query=CausalQuery(**payload["query"]),
            model=_freeze(payload["model"]),
            factual_rows=_freeze(payload["factual_rows"]),
            interventions=_freeze(payload["interventions"]),
        )

    def execute(self, engine: Any = None) -> CausalOutcome:
        model, rows, interventions = _thaw(self.model), _thaw(self.factual_rows), _thaw(self.interventions)
        if self.operation == "compare_interventions":
            return compare_interventions(self.query, model=model, factual_rows=rows, interventions=interventions, engine=engine)
        if self.operation == "simulate_intervention":
            return simulate_intervention(self.query, model=model, factual_rows=rows, intervention=interventions, engine=engine)
        if self.operation == "estimate_intervention":
            return estimate_intervention(self.query, model=model, factual_rows=rows, intervention=interventions, engine=engine)
        raise ScenarioRunError("RUN_SPEC_INVALID", "unknown operation")


def _query_delta(view: OverlayView) -> Mapping[str, Any] | None:
    found: Mapping[str, Any] | None = None
    for delta in view.deltas:
        if isinstance(delta.delta, Mapping) and delta.delta.get("kind") == QUERY_DELTA_KIND:
            found = delta.delta
    return found


def _valid_query_delta(delta: Mapping[str, Any] | None) -> bool:
    if delta is None or set(delta) != QUERY_DELTA_FIELDS or delta["operation"] not in OPERATIONS:
        return False
    names_ok = all(isinstance(delta[name], str) and delta[name] for name in ("treatment", "outcome", "estimand"))
    population = delta["population"]
    interventions = delta["interventions"]
    return (
        names_ok
        and isinstance(population, Mapping)
        and bool(population)
        and isinstance(interventions, (list, tuple))
        and len(interventions) >= (2 if delta["operation"] == "compare_interventions" else 1)
        and (delta["operation"] == "compare_interventions" or len(interventions) == 1)
    )


def _query(
    spec: ScenarioRunSpec,
    *,
    branch: ScenarioBranch,
    revision: int,
    treatment: str,
    outcome: str,
    estimand: str,
    population: Mapping[str, Any],
    intervention_digest: str,
    expected_release_digest: str,
) -> CausalQuery:
    pins = spec.pins()
    run_pins = {
        **{key: value for key, value in pins.items() if key not in {"seed", "canonical_commit_ref", "ontology_release_digest"}},
        "run_spec_digest": spec.digest,
        "compartments": list(branch.compartments),
        "overlay_revision": revision,
        "estimand": estimand,
        "population": _thaw(population),
    }
    return CausalQuery(
        baseline_commit=spec.canonical_commit_ref,
        scenario_branch=branch.scenario_branch,
        model_digest=spec.causal_model_digest,
        data_digest=spec.input_digest,
        intervention_digest=intervention_digest,
        ontology_release_digest=spec.ontology_release_digest,
        expected_release_digest=expected_release_digest,
        treatment=treatment,
        outcome=outcome,
        seed=spec.seed,
        correlation_id=str(spec.governed_context["correlation_id"]),
        # GovernedContext v1.2 has no causation: the query is caused by the run of the spec.
        causation_id=spec.run_id,
        run_pins=run_pins,
    )


def _rejected(query: CausalQuery, reason: str) -> CausalOutcome:
    return _seal(query, status="REJECTED", reason_code=reason)


def prepare_scenario_run(
    spec: ScenarioRunSpec,
    *,
    overlay: Any,
    branch: ScenarioBranch,
    revision: int,
    model_envelope: object,
    trust_root: CausalModelTrustRoot,
    factual_rows: object,
    expected_release_digest: str,
) -> PreparedRun | CausalOutcome:
    """Admit a run of ``spec``: the hypothesis is read through ``overlay.read_at`` at
    ``revision`` of ``branch``; the run identity, baseline and model signature are
    verified here. Returns the prepared run or a ``REJECTED`` outcome, in the order:
    scenario pins, model signature and digest, the hypothesis, the budget."""
    if not isinstance(spec, ScenarioRunSpec):
        raise _invalid("a ScenarioRunSpec is required")
    if not isinstance(branch, ScenarioBranch) or isinstance(revision, bool) or not isinstance(revision, int):
        raise _invalid("a ScenarioBranch and an integer overlay revision are required")
    view = overlay.read_at(branch, revision)
    if not isinstance(view, OverlayView) or view.branch != branch or view.revision != revision:
        raise _invalid("the overlay returned another view than the one requested")
    delta = _query_delta(view)
    valid = _valid_query_delta(delta)
    interventions: Any = None
    if delta is not None and valid:
        listed = _thaw(delta["interventions"])
        interventions = listed if delta["operation"] == "compare_interventions" else listed[0]
    try:
        intervention_digest = canonical_digest(interventions)
    except (TypeError, ValueError):
        valid, intervention_digest = False, canonical_digest(None)
    query = _query(
        spec,
        branch=branch,
        revision=revision,
        treatment=str(delta["treatment"]) if valid and delta is not None else "",
        outcome=str(delta["outcome"]) if valid and delta is not None else "",
        estimand=str(delta["estimand"]) if valid and delta is not None else "",
        population=delta["population"] if valid and delta is not None else {},
        intervention_digest=intervention_digest,
        expected_release_digest=expected_release_digest,
    )
    if (branch.scenario_id, branch.run_id, branch.canonical_commit_ref) != (spec.scenario_id, spec.run_id, spec.canonical_commit_ref):
        return _rejected(query, "SCENARIO_PIN_MISMATCH")
    # ADD v1.3 :2961: the overlay is isolated per (scenario_id, run_id, compartments); the
    # compartments of the run are those of its governed context.
    if frozenset(branch.compartments) != frozenset(spec.governed_context["compartments"]):
        return _rejected(query, "SCENARIO_PIN_MISMATCH")
    try:
        model = verify_causal_model(model_envelope, trust_root, expected_digest=spec.causal_model_digest)
    except ScenarioRunError as error:
        if error.code == "TRUST_ROOT_INVALID":
            raise
        return _rejected(query, error.code)
    if not valid or delta is None:
        return _rejected(query, "INTERVENTION_SCHEMA_INVALID")
    if delta["estimand"] != model.get("estimand"):
        return _rejected(query, "MODEL_SCHEMA_INVALID")
    samples = model.get("samples")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples > spec.budget["max_samples"]:
        return _rejected(query, "BUDGET_EXCEEDED")
    return PreparedRun(
        operation=str(delta["operation"]),
        query=query,
        model=_freeze(model),
        factual_rows=_freeze(factual_rows) if isinstance(factual_rows, list) else factual_rows,  # type: ignore[arg-type]
        interventions=_freeze(interventions),
    )


def run_scenario(
    spec: ScenarioRunSpec,
    *,
    overlay: Any,
    branch: ScenarioBranch,
    revision: int,
    model_envelope: object,
    trust_root: CausalModelTrustRoot,
    factual_rows: object,
    expected_release_digest: str,
    engine: Any = None,
) -> CausalOutcome:
    """Prepare and execute one run in the calling process."""
    prepared = prepare_scenario_run(
        spec,
        overlay=overlay,
        branch=branch,
        revision=revision,
        model_envelope=model_envelope,
        trust_root=trust_root,
        factual_rows=factual_rows,
        expected_release_digest=expected_release_digest,
    )
    if isinstance(prepared, CausalOutcome):
        return prepared
    return prepared.execute(engine)
