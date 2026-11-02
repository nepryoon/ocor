"""Registry contract ``ocor.registry.v1``: enums, messages, typed errors and admission checks.

Every message and enum mirrors ``ocor-runtime/docs/governance_dossier/contracts/
ocor_registry.proto`` (:21-199) with the same field names, in field-number order, and the
same enum numbers; LLD v1.1 §0.2 (docs/OCOR_LLD_v1.1.md :29) fixes that file as the
Registry contract. ``google.protobuf.Any`` is ``AnyValue`` (``type_url`` and ``value``
bytes), ``Duration`` is ``timedelta`` and ``Timestamp`` is an aware ``datetime``; a proto3
``optional`` field or an unset message field is ``None``.

The checks here are the admission constraints of ADD v1.3 §3.4
(ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md :1370 and the
constraint list after the proto): exact pins only (no range, no ``latest``),
``EFFECT_CLASS_UNSPECIFIED`` invalid, a ``ModelDescriptor`` is ``MODEL_INFERENCE``, a
``ModelResult`` carries exactly one disposition and a declared output kind. Digests use
the ``urn:sha256:<64 lowercase hex>`` form of LLD v1.1 :36.
"""

from __future__ import annotations

import base64
import binascii
import re
import types
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Any, TypeVar

from ..kernel.canonical import canonical_digest, format_utc_timestamp, parse_utc_timestamp

DIGEST = re.compile(r"urn:sha256:[0-9a-f]{64}")
# Exact Semantic Versioning 2.0.0, as the C1 meta-schema (c1/oac.py SEMVER_PATTERN): a
# range (``^1.0.0``, ``1.x``, ``>=1``) or ``latest`` never matches.
SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)
URN = re.compile(r"urn:[a-z0-9][a-z0-9-]{0,31}:[A-Za-z0-9()+,\-.:=@;$_!*'%/?#]+")
TYPE_URL = re.compile(r"[A-Za-z0-9.-]+(?:/[A-Za-z0-9._-]+)*/[A-Za-z_][A-Za-z0-9_.]*")

# The closed reason codes of the registry boundary, all drawn from the normative
# vocabulary (gateway Problem enum, MCP error model, ACT-T* reason codes).
REASON_CODES = frozenset({
    "BUDGET_EXCEEDED",
    "CONTRACT_DIGEST_MISMATCH",
    "CONTRACT_NOT_FOUND",
    "CONTRACT_REJECTED",
    "CONTROL_PLANE_UNAVAILABLE",
    "EXECUTION_FAILED",
    "GOVERNED_CONTEXT_MISMATCH",
    "IDEMPOTENCY_CONFLICT",
    "RELEASE_MISMATCH",
    "SCHEMA_VIOLATION",
    "UNSUPPORTED_CAPABILITY",
})


class RegistryError(Exception):
    """Typed fail-closed registry error with a closed reason code."""

    def __init__(self, reason_code: str, message: str, *, audit_ref: str = "") -> None:
        if reason_code not in REASON_CODES:
            raise ValueError(f"undeclared registry reason code: {reason_code!r}")
        self.reason_code = reason_code
        self.message = message
        self.audit_ref = audit_ref
        super().__init__(f"{reason_code}: {message}")

    def to_problem(self) -> dict[str, str]:
        return {"reason_code": self.reason_code, "title": self.message[:256], "audit_ref": self.audit_ref}


def violation(message: str) -> RegistryError:
    return RegistryError("SCHEMA_VIOLATION", message)


class EffectClass(IntEnum):
    EFFECT_CLASS_UNSPECIFIED = 0
    PURE = 1
    READ_CANONICAL = 2
    READ_PROJECTION = 3
    READ_EXTERNAL = 4
    PROPOSE_MUTATION = 5
    MODEL_INFERENCE = 6


class ModelOutputKind(IntEnum):
    MODEL_OUTPUT_KIND_UNSPECIFIED = 0
    PREDICTION = 1
    BELIEF = 2
    RECOMMENDATION = 3


@dataclass(frozen=True, slots=True)
class VersionPin:
    resource_id: str
    semantic_version: str
    artifact_digest: str
    contract_digest: str


@dataclass(frozen=True, slots=True)
class SchemaPin:
    schema_id: str
    semantic_version: str
    schema_digest: str
    protobuf_type_url: str


@dataclass(frozen=True, slots=True)
class AnyValue:
    """``google.protobuf.Any``."""

    type_url: str
    value: bytes


@dataclass(frozen=True, slots=True)
class TypedValue:
    schema: SchemaPin | None
    value: AnyValue | None


@dataclass(frozen=True, slots=True)
class InvocationContext:
    request_id: str
    tenant_id: str
    domain_id: str
    compartments: tuple[str, ...]
    purpose: str
    ontology_release_digest: str
    logic_version: str
    branch: str
    scenario_id: str | None
    correlation_id: str
    causation_id: str | None
    delegation_ref: str | None
    classification_marking_ref: str
    organization_id: str
    policy_bundle_digest: str
    governed_context_digest: str


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    timeout: timedelta | None
    cpu_millis: int
    memory_bytes: int
    output_bytes: int


@dataclass(frozen=True, slots=True)
class FunctionDescriptor:
    pin: VersionPin | None
    input_schema: SchemaPin | None
    output_schema: SchemaPin | None
    dependencies: tuple[VersionPin, ...]
    effect_class: EffectClass
    deterministic: bool
    execution_owner: str
    budget: ResourceBudget | None
    policy_refs: tuple[str, ...]
    artifact_signature_ref: str
    provenance_ref: str


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    model_pin: VersionPin | None
    deployment_pin: VersionPin | None
    mapping_pin: VersionPin | None
    input_schema: SchemaPin | None
    output_schema: SchemaPin | None
    effect_class: EffectClass
    validity_envelope_ref: str
    training_lineage_ref: str
    owner_principal_ref: str
    risk_class: str
    approval_status: str
    artifact_signature_ref: str


@dataclass(frozen=True, slots=True)
class PublishFunctionRequest:
    descriptor: FunctionDescriptor | None
    signed_manifest_ref: str
    change_proposal_ref: str


@dataclass(frozen=True, slots=True)
class PublishModelRequest:
    descriptor: ModelDescriptor | None
    signed_manifest_ref: str
    change_proposal_ref: str


@dataclass(frozen=True, slots=True)
class PublishReceipt:
    registry_commit: str
    descriptor_digest: str
    accepted_at: datetime
    audit_ref: str


@dataclass(frozen=True, slots=True)
class ResolveFunctionRequest:
    pin: VersionPin | None
    context: InvocationContext | None


@dataclass(frozen=True, slots=True)
class ResolveModelRequest:
    model_pin: VersionPin | None
    deployment_pin: VersionPin | None
    mapping_pin: VersionPin | None
    context: InvocationContext | None


@dataclass(frozen=True, slots=True)
class InvokeFunctionRequest:
    function_pin: VersionPin | None
    context: InvocationContext | None
    input: TypedValue | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class FunctionResult:
    invocation_id: str
    output: TypedValue | None
    effect_class: EffectClass
    result_digest: str
    provenance_ref: str
    classification_marking_ref: str
    served_commit: str
    watermark: str


@dataclass(frozen=True, slots=True)
class InvokeModelRequest:
    model_pin: VersionPin | None
    deployment_pin: VersionPin | None
    mapping_pin: VersionPin | None
    context: InvocationContext | None
    input: TypedValue | None
    input_digest: str


@dataclass(frozen=True, slots=True)
class ValidityAssessment:
    inside_envelope: bool
    envelope_version: str
    failed_conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UncertaintyDescriptor:
    semantics: str
    value: TypedValue | None
    calibration_ref: str


@dataclass(frozen=True, slots=True)
class Abstention:
    reason_code: str
    explanation_ref: str


@dataclass(frozen=True, slots=True)
class ModelResult:
    """``oneof disposition`` is ``output`` or ``abstention``: see ``admit_model_result``."""

    invocation_id: str
    output_kind: ModelOutputKind
    output: TypedValue | None
    abstention: Abstention | None
    validity: ValidityAssessment | None
    uncertainty: UncertaintyDescriptor | None
    result_digest: str
    provenance_ref: str
    classification_marking_ref: str


MESSAGES: tuple[type, ...] = (
    VersionPin, SchemaPin, TypedValue, InvocationContext, ResourceBudget, FunctionDescriptor,
    ModelDescriptor, PublishFunctionRequest, PublishModelRequest, PublishReceipt, ResolveFunctionRequest,
    ResolveModelRequest, InvokeFunctionRequest, FunctionResult, InvokeModelRequest, ValidityAssessment,
    UncertaintyDescriptor, Abstention, ModelResult,
)


# ------------------------------------------------------------------------------------
# Canonical mapping (RFC 8785 input) and digests
# ------------------------------------------------------------------------------------
def duration_text(value: timedelta) -> str:
    """``google.protobuf.Duration`` JSON form: seconds with up to 9 fractional digits."""
    micros = value // timedelta(microseconds=1)
    seconds, fraction = divmod(micros, 1_000_000)
    return f"{seconds}.{fraction:06d}s" if fraction else f"{seconds}s"


def to_mapping(message: Any) -> Any:
    """The proto3 JSON-like mapping of a message: field names, enum names, base64 bytes."""
    if message is None:
        return None
    if isinstance(message, IntEnum):
        return message.name
    if isinstance(message, bool | int | str):
        return message
    if isinstance(message, bytes):
        return base64.b64encode(message).decode("ascii")
    if isinstance(message, timedelta):
        return duration_text(message)
    if isinstance(message, datetime):
        return format_utc_timestamp(message)
    if isinstance(message, tuple | list):
        return [to_mapping(item) for item in message]
    if isinstance(message, AnyValue):
        return {"type_url": message.type_url, "value": to_mapping(message.value)}
    return {f.name: to_mapping(getattr(message, f.name)) for f in fields(message)}


M = TypeVar("M")
DURATION = re.compile(r"(0|[1-9][0-9]*)(?:\.([0-9]{6}))?s")


def _decode(hint: Any, value: Any, where: str) -> Any:
    origin = typing.get_origin(hint)
    if origin in (types.UnionType, typing.Union):
        options = [option for option in typing.get_args(hint) if option is not type(None)]
        return None if value is None else _decode(options[0], value, where)
    if value is None:
        raise violation(f"{where} is required")
    if origin is tuple:
        if not isinstance(value, list):
            raise violation(f"{where} must be a list")
        item = typing.get_args(hint)[0]
        return tuple(_decode(item, element, f"{where}[]") for element in value)
    if isinstance(hint, type) and issubclass(hint, IntEnum):
        if not isinstance(value, str) or value not in hint.__members__:
            raise violation(f"{where} is not a {hint.__name__}")
        return hint[value]
    if hint is bool or hint is str or hint is int:
        if type(value) is not hint:
            raise violation(f"{where} must be {hint.__name__}")
        return value
    if hint is bytes:
        try:
            return base64.b64decode(value, validate=True)
        except (binascii.Error, TypeError, ValueError) as exc:
            raise violation(f"{where} must be base64") from exc
    if hint is timedelta:
        match = DURATION.fullmatch(value) if isinstance(value, str) else None
        if match is None:
            raise violation(f"{where} must be a Duration")
        return timedelta(seconds=int(match.group(1)), microseconds=int(match.group(2) or 0))
    if hint is datetime:
        try:
            return parse_utc_timestamp(value)
        except ValueError as exc:
            raise violation(f"{where} must be an RFC 3339 UTC timestamp") from exc
    if isinstance(hint, type) and is_dataclass(hint):
        return from_mapping(hint, value, where)
    raise violation(f"{where} has an unsupported type")


def from_mapping(cls: type[M], value: Any, where: str = "message") -> M:
    """Rebuild a message from ``to_mapping`` output; closed: extra or missing fields fail."""
    if not isinstance(value, Mapping):
        raise violation(f"{where} must be an object")
    hints = typing.get_type_hints(cls)
    names = [f.name for f in fields(cls)]  # type: ignore[arg-type]
    if set(value) != set(names):
        raise violation(f"{where} has fields {sorted(value)}, expected {sorted(names)}")
    return cls(**{name: _decode(hints[name], value[name], f"{where}.{name}") for name in names})


def message_digest(message: Any) -> str:
    return canonical_digest(to_mapping(message))


def pin_key(pin: VersionPin) -> str:
    return "\x1f".join((pin.resource_id, pin.semantic_version, pin.artifact_digest, pin.contract_digest))


# ------------------------------------------------------------------------------------
# Admission checks
# ------------------------------------------------------------------------------------
def require_text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or any(ord(c) < 32 for c in value):
        raise violation(f"{where} is required")
    return value


def require_digest(value: object, where: str) -> str:
    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise violation(f"{where} must be urn:sha256:<64 lowercase hex>")
    return value


def require_urn(value: object, where: str) -> str:
    if not isinstance(value, str) or URN.fullmatch(value) is None:
        raise violation(f"{where} must be a URN")
    return value


def require_pin(pin: object, where: str) -> VersionPin:
    """An exact pin (ADD v1.3 §3.4): no version range and no ``latest`` resolution."""
    if not isinstance(pin, VersionPin):
        raise violation(f"{where} is required")
    require_urn(pin.resource_id, f"{where}.resource_id")
    if not isinstance(pin.semantic_version, str) or SEMVER.fullmatch(pin.semantic_version) is None:
        raise violation(f"{where}.semantic_version must be an exact semantic version, never a range or latest")
    require_digest(pin.artifact_digest, f"{where}.artifact_digest")
    require_digest(pin.contract_digest, f"{where}.contract_digest")
    return pin


def require_schema_pin(pin: object, where: str) -> SchemaPin:
    if not isinstance(pin, SchemaPin):
        raise violation(f"{where} is required")
    require_urn(pin.schema_id, f"{where}.schema_id")
    if not isinstance(pin.semantic_version, str) or SEMVER.fullmatch(pin.semantic_version) is None:
        raise violation(f"{where}.semantic_version must be an exact semantic version")
    require_digest(pin.schema_digest, f"{where}.schema_digest")
    if not isinstance(pin.protobuf_type_url, str) or TYPE_URL.fullmatch(pin.protobuf_type_url) is None:
        raise violation(f"{where}.protobuf_type_url must be a type URL")
    return pin


def require_effect_class(value: object, where: str) -> EffectClass:
    if not isinstance(value, EffectClass) or value is EffectClass.EFFECT_CLASS_UNSPECIFIED:
        raise violation(f"{where}: effect_class=UNSPECIFIED is invalid")
    return value


def require_refs(values: object, where: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise violation(f"{where} must be a list")
    refs = tuple(require_urn(value, f"{where}[]") for value in values)
    if list(refs) != sorted(set(refs)):
        raise violation(f"{where} must be sorted and duplicate-free")
    return refs


def require_budget(budget: object, where: str) -> ResourceBudget:
    """NFR-025: timeout and CPU, memory and output quotas are all configured and positive."""
    if not isinstance(budget, ResourceBudget):
        raise violation(f"{where} is required")
    if not isinstance(budget.timeout, timedelta) or budget.timeout <= timedelta(0):
        raise violation(f"{where}.timeout must be positive")
    for name in ("cpu_millis", "memory_bytes", "output_bytes"):
        value = getattr(budget, name)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 < value < 2**64:
            raise violation(f"{where}.{name} must be a positive uint64")
    return budget


def admit_function_descriptor(descriptor: object) -> FunctionDescriptor:
    """FR-058: a Function without its mandatory metadata is never published."""
    if not isinstance(descriptor, FunctionDescriptor):
        raise violation("descriptor is required")
    require_pin(descriptor.pin, "descriptor.pin")
    require_schema_pin(descriptor.input_schema, "descriptor.input_schema")
    require_schema_pin(descriptor.output_schema, "descriptor.output_schema")
    if not isinstance(descriptor.dependencies, tuple):
        raise violation("descriptor.dependencies must be a list")
    keys = [pin_key(require_pin(pin, "descriptor.dependencies[]")) for pin in descriptor.dependencies]
    if keys != sorted(set(keys)):
        raise violation("descriptor.dependencies must be sorted and duplicate-free")
    effect = require_effect_class(descriptor.effect_class, "descriptor")
    if effect is EffectClass.MODEL_INFERENCE:
        raise violation("MODEL_INFERENCE is the effect class of a ModelDescriptor, not of a Function")
    if not isinstance(descriptor.deterministic, bool):
        raise violation("descriptor.deterministic must be declared")
    require_urn(descriptor.execution_owner, "descriptor.execution_owner")
    require_budget(descriptor.budget, "descriptor.budget")
    require_refs(descriptor.policy_refs, "descriptor.policy_refs")
    require_digest(descriptor.artifact_signature_ref, "descriptor.artifact_signature_ref")
    require_urn(descriptor.provenance_ref, "descriptor.provenance_ref")
    return descriptor


def admit_model_descriptor(descriptor: object) -> ModelDescriptor:
    """FR-060: digest, version, deployment, schemas, mapping, envelope and lineage are recorded."""
    if not isinstance(descriptor, ModelDescriptor):
        raise violation("descriptor is required")
    require_pin(descriptor.model_pin, "descriptor.model_pin")
    require_pin(descriptor.deployment_pin, "descriptor.deployment_pin")
    require_pin(descriptor.mapping_pin, "descriptor.mapping_pin")
    require_schema_pin(descriptor.input_schema, "descriptor.input_schema")
    require_schema_pin(descriptor.output_schema, "descriptor.output_schema")
    if require_effect_class(descriptor.effect_class, "descriptor") is not EffectClass.MODEL_INFERENCE:
        raise violation("ModelDescriptor.effect_class must be MODEL_INFERENCE")
    require_digest(descriptor.validity_envelope_ref, "descriptor.validity_envelope_ref")
    require_urn(descriptor.training_lineage_ref, "descriptor.training_lineage_ref")
    require_urn(descriptor.owner_principal_ref, "descriptor.owner_principal_ref")
    if not isinstance(descriptor.risk_class, str) or re.fullmatch(r"R[0-9]", descriptor.risk_class) is None:
        raise violation("descriptor.risk_class must be R0-R9")
    require_text(descriptor.approval_status, "descriptor.approval_status")
    require_digest(descriptor.artifact_signature_ref, "descriptor.artifact_signature_ref")
    return descriptor


def require_typed_value(value: object, expected: SchemaPin, where: str) -> TypedValue:
    """ADD v1.3 §3.4: ``protobuf_type_url`` and digest equal the pinned descriptor schema."""
    if not isinstance(value, TypedValue) or not isinstance(value.value, AnyValue):
        raise violation(f"{where} is required")
    if value.schema != expected:
        raise violation(f"{where}.schema does not match the pinned descriptor schema")
    if value.value.type_url != expected.protobuf_type_url:
        raise violation(f"{where}.value.type_url does not match the pinned protobuf_type_url")
    if not isinstance(value.value.value, bytes):
        raise violation(f"{where}.value.value must be bytes")
    return value


def admit_model_result(result: object) -> ModelResult:
    """ADD v1.3 §3.4: exactly one of ``output`` and ``abstention``; a declared output kind."""
    if not isinstance(result, ModelResult):
        raise violation("ModelResult is required")
    if (result.output is None) == (result.abstention is None):
        raise violation("ModelResult.disposition must hold exactly one of output and abstention")
    if not isinstance(result.output_kind, ModelOutputKind) or (
        result.output_kind is ModelOutputKind.MODEL_OUTPUT_KIND_UNSPECIFIED
    ):
        raise violation("ModelResult.output_kind must be PREDICTION, BELIEF or RECOMMENDATION")
    if not isinstance(result.validity, ValidityAssessment):
        raise violation("ModelResult.validity is required")
    if result.output is not None and not result.validity.inside_envelope:
        raise violation("a Model outside its validity envelope abstains, never returns output")
    if result.abstention is not None:
        require_text(result.abstention.reason_code, "ModelResult.abstention.reason_code")
    require_digest(result.result_digest, "ModelResult.result_digest")
    return result


def json_mapping(value: Mapping[str, Any] | Sequence[Any]) -> Any:
    """A defensive deep copy of plain JSON data."""
    if isinstance(value, Mapping):
        return {str(k): json_mapping(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [json_mapping(v) for v in value]
    return value

