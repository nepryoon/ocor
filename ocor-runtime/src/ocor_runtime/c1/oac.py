"""C1 -- Ontology-as-Code metamodel, meta-schema, parser and normalisation.

Realises ADD v1.3 §3.1.1 (OCOR_ADD_v1.3_APPROVED_BASELINE.md): the authoritative
source is YAML validated by a meta-schema (:415); the construct table of the OaC
metamodel (:417-431); deterministic normalisation step 2 -- Unicode NFC, RFC 3339
UTC timestamps and canonical decimals (:435). The meta-schema is JSON Schema
Draft 2020-12; a violation is a localised diagnostic whose path starts with the
source path of the offending document (FR-026, FR-027).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import jsonschema
import yaml

from ..kernel.canonical import format_utc_timestamp
from .ports import C1Diagnostic, C1Error, DiagnosticCode, SourceSyntax, SourceUnit

URN = r"^urn:[a-z0-9][a-z0-9-]{0,31}:[A-Za-z0-9()+,\-.:=@;$_!*'%/?#]+$"
SHA256_URN = r"^urn:sha256:[0-9a-f]{64}$"
SEMVER_PATTERN = (
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
PRIMITIVES = ("boolean", "bytes", "date", "datetime", "decimal", "integer", "string", "uri")
GEOMETRIES = ("linestring", "point", "polygon")
MEDIA = ("audio", "document", "image", "video")
# The closed value-type grammar of PropertyDefinition.value_type_ref (FR-024): one
# alternative per value-type family. Container element types are re-parsed by
# parse_value_type; an unrecognised type is rejected, never coerced.
VALUE_TYPE_PATTERN = (
    r"^(?:" + "|".join(PRIMITIVES) + r"|(?:list|set|timeseries)<.+>|map<string,.+>"
    r"|struct:urn:.+|enum:urn:.+|ref:urn:.+|sensitive_ref:urn:.+"
    r"|geo:(?:" + "|".join(GEOMETRIES) + r")|media:(?:" + "|".join(MEDIA) + r")"
    r"|quantity:[a-z0-9][a-z0-9_-]*)$"
)
TYPE_KINDS = ("OBJECT", "INTERFACE", "VALUE", "STRUCT", "ENUM", "EVENT", "ACTION", "RELATION", "CAUSAL",
              "AGENT_RESOURCE")
CONSTRAINT_KINDS = ("TYPE", "KEY", "RANGE", "CARDINALITY", "INVARIANT", "COMPLETENESS")
TEMPORAL_MODES = ("ATEMPORAL", "VALID_TIME", "TRANSACTION_TIME", "BITEMPORAL")
CONTRACT_KINDS = ("NAMED_QUERY", "FUNCTION", "MODEL_FUNCTION", "ACTION", "EVENT", "MCP_TOOL")
DISPOSITIONS = ("exact", "emulated", "materialized", "unsupported", "not_applicable_in_role",
                "forbidden_by_design", "deferred_by_scope")
MARKING_FAMILIES = ("mandatory_markings", "caveats", "dissemination_controls", "permitted_purposes",
                    "handling_instructions")
ARTIFACT_TARGETS = ("asyncapi", "json-schema", "mcp-descriptor", "openapi", "protobuf", "sdk-python",
                    "sdk-typescript")
CARDINALITIES = ("ONE", "MANY")


def _ref() -> dict[str, Any]:
    return {"type": "string", "pattern": URN}


def _refs(*, min_items: int = 0) -> dict[str, Any]:
    return {"type": "array", "items": _ref(), "minItems": min_items}


def _text() -> dict[str, Any]:
    return {"type": "string", "minLength": 1}


def _closed(required: Sequence[str], properties: Mapping[str, Any], construct: str | None = None) -> dict[str, Any]:
    props = dict(properties)
    if construct is not None:
        props = {"construct": {"const": construct}, **props}
        required = ("construct", *required)
    return {"type": "object", "additionalProperties": False, "required": list(required), "properties": props}


_TEMPORAL = _closed(
    ("mode", "precision", "timezone_policy"),
    {
        "mode": {"enum": list(TEMPORAL_MODES)},
        "valid_from_field": _text(),
        "valid_to_field": _text(),
        "system_from_field": _text(),
        "system_to_field": _text(),
        "precision": {"enum": ["SECOND", "MILLISECOND", "MICROSECOND"]},
        "timezone_policy": {"const": "UTC"},
    },
)
_PROPERTY = _closed(
    ("property_id", "value_type_ref", "cardinality", "nullable", "constraint_refs"),
    {
        "property_id": _ref(),
        "value_type_ref": {"type": "string", "pattern": VALUE_TYPE_PATTERN},
        "cardinality": {"enum": list(CARDINALITIES)},
        "nullable": {"type": "boolean"},
        "unit_ref": _ref(),
        "default": {"type": ["string", "integer", "boolean"]},
        "constraint_refs": _refs(),
        "temporal_annotation": {"$ref": "#/$defs/TemporalAnnotation"},
        "marking_rule_ref": _ref(),
    },
)
_DEFS: dict[str, Any] = {
    "TemporalAnnotation": _TEMPORAL,
    "PropertyDefinition": _PROPERTY,
    "OntologyPackage": _closed(
        ("package_id", "version", "namespace_refs", "module_refs", "dependency_lock", "owner",
         "classification_marking", "release_profile", "adapter_roles", "artifact_targets"),
        {
            "package_id": _ref(),
            "version": {"type": "string", "pattern": SEMVER_PATTERN},
            "namespace_refs": _refs(min_items=1),
            "module_refs": _refs(min_items=1),
            "dependency_lock": {
                "type": "array",
                "items": _closed(
                    ("resource_id", "version", "sha256"),
                    {"resource_id": _ref(), "version": _text(), "sha256": {"type": "string", "pattern": SHA256_URN}},
                ),
            },
            "owner": _ref(),
            "classification_marking": _text(),
            "release_profile": {"enum": ["poc", "mvp", "production"]},
            "adapter_roles": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": r"^[a-z][a-z0-9-]*$"}},
            "artifact_targets": {"type": "array", "minItems": 1, "items": {"enum": list(ARTIFACT_TARGETS)}},
        },
        "OntologyPackage",
    ),
    "Namespace": _closed(
        ("namespace_id", "uri", "prefix", "ownership_boundary", "default_marking"),
        {
            "namespace_id": _ref(),
            "uri": {"type": "string", "pattern": r"^[a-z][a-z0-9+.-]*:[^\s]+$"},
            "prefix": {"type": "string", "pattern": r"^[A-Za-z_][A-Za-z0-9_-]*$"},
            "ownership_boundary": _ref(),
            "default_marking": _text(),
        },
        "Namespace",
    ),
    "Module": _closed(
        ("module_id", "version", "namespace_ref", "imports", "exports", "definitions", "owner", "steward",
         "reviewer", "status", "review_date"),
        {
            "module_id": _ref(),
            "version": {"type": "string", "pattern": SEMVER_PATTERN},
            "namespace_ref": _ref(),
            "imports": _refs(),
            "exports": _refs(),
            "definitions": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/Definition"}},
            "owner": _ref(),
            "steward": _ref(),
            "reviewer": _ref(),
            "status": {"enum": ["DRAFT", "IN_REVIEW", "APPROVED", "DEPRECATED"]},
            "review_date": {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
        },
        "Module",
    ),
    "TypeDefinition": _closed(
        ("type_id", "kind", "version", "properties", "keys", "interfaces", "security_profile_ref"),
        {
            "type_id": _ref(),
            "kind": {"enum": list(TYPE_KINDS)},
            "version": {"type": "string", "pattern": SEMVER_PATTERN},
            "label": _text(),
            "values": {"type": "array", "items": _text()},
            "properties": {"type": "array", "items": {"$ref": "#/$defs/PropertyDefinition"}},
            "keys": _refs(),
            "interfaces": _refs(),
            "lifecycle_ref": _ref(),
            "temporal_annotation": {"$ref": "#/$defs/TemporalAnnotation"},
            "security_profile_ref": _ref(),
        },
        "TypeDefinition",
    ),
    "LinkDefinition": _closed(
        ("link_id", "roles", "properties", "security_profile_ref"),
        {
            "link_id": _ref(),
            "roles": {
                "type": "array",
                "minItems": 2,
                "items": _closed(
                    ("role", "role_player_type_ref", "cardinality"),
                    {"role": {"type": "string", "pattern": r"^[a-z][a-z0-9_-]*$"}, "role_player_type_ref": _ref(),
                     "cardinality": {"enum": list(CARDINALITIES)}},
                ),
            },
            "properties": {"type": "array", "items": {"$ref": "#/$defs/PropertyDefinition"}},
            "temporal_annotation": {"$ref": "#/$defs/TemporalAnnotation"},
            "security_profile_ref": _ref(),
        },
        "LinkDefinition",
    ),
    "ConstraintDefinition": _closed(
        ("constraint_id", "kind", "scope_ref", "typed_expression", "evaluation_phase", "severity",
         "execution_owner", "validity", "repair_strategy"),
        {
            "constraint_id": _ref(),
            "kind": {"enum": list(CONSTRAINT_KINDS)},
            "scope_ref": _ref(),
            "typed_expression": {"type": "object", "minProperties": 1},
            "evaluation_phase": _text(),
            "severity": _text(),
            "execution_owner": _ref(),
            "validity": _text(),
            "repair_strategy": _text(),
        },
        "ConstraintDefinition",
    ),
    "DerivedDefinition": _closed(
        ("derived_id", "result_type_ref", "typed_ast", "execution_owner", "materialization_policy",
         "dependency_refs"),
        {
            "derived_id": _ref(),
            "result_type_ref": _ref(),
            "typed_ast": {"type": "object", "minProperties": 1},
            "execution_owner": _ref(),
            "materialization_policy": _text(),
            "dependency_refs": _refs(),
        },
        "DerivedDefinition",
    ),
    "ContractDefinition": _closed(
        ("contract_id", "kind", "input_schema", "output_schema", "error_model", "effect_class", "risk_class",
         "policy_refs", "approval_refs", "version"),
        {
            "contract_id": _ref(),
            "kind": {"enum": list(CONTRACT_KINDS)},
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "error_model": {"type": "array", "items": {"type": "string", "pattern": r"^[A-Z][A-Z0-9_]*$"}},
            "effect_class": _text(),
            "risk_class": {"type": "string", "pattern": r"^R[0-9]$"},
            "policy_refs": _refs(),
            "approval_refs": _refs(),
            "version": {"type": "string", "pattern": SEMVER_PATTERN},
        },
        "ContractDefinition",
    ),
    "MarkingSchemeDefinition": _closed(
        ("scheme_id", "version", "levels", "top", "bottom", "dominance_relation", "family_definitions",
         "unknown_value_behavior", "incomparable_behavior", "declassification_authority_ref"),
        {
            "scheme_id": _ref(),
            "version": {"type": "string", "pattern": SEMVER_PATTERN},
            "levels": {"type": "array", "minItems": 1, "items": _text()},
            "top": _text(),
            "bottom": _text(),
            "dominance_relation": {"type": "array", "items": {"type": "array", "minItems": 2, "maxItems": 2,
                                                               "items": _text()}},
            "family_definitions": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": _closed(
                    ("family", "vocabulary", "kind", "join_operator", "meet_operator", "neutral_element"),
                    {"family": {"enum": list(MARKING_FAMILIES)}, "vocabulary": {"type": "array", "items": _text()},
                     "kind": {"enum": ["RESTRICTION", "PERMISSION"]},
                     "join_operator": {"enum": ["UNION", "INTERSECTION"]},
                     "meet_operator": {"enum": ["UNION", "INTERSECTION"]},
                     "neutral_element": {"type": "array", "items": _text()}},
                ),
            },
            "unknown_value_behavior": {"const": "DENY"},
            "incomparable_behavior": {"enum": ["DENY", "MOST_RESTRICTIVE"]},
            "declassification_authority_ref": _ref(),
        },
        "MarkingSchemeDefinition",
    ),
    "SecurityProfileDefinition": _closed(
        ("security_profile_id", "marking_scheme_ref", "default_marking"),
        {"security_profile_id": _ref(), "marking_scheme_ref": _ref(), "default_marking": _text()},
        "SecurityProfileDefinition",
    ),
    "CapabilityDisposition": _closed(
        ("semantic_capability_id", "adapter_role", "disposition", "limitation", "evidence_ref"),
        {
            "semantic_capability_id": {"type": "string", "pattern": r"^[a-z][a-z0-9-]*(:[a-z0-9_-]+)+$"},
            "adapter_role": {"type": "string", "pattern": r"^[a-z][a-z0-9-]*$"},
            "disposition": {"enum": list(DISPOSITIONS)},
            "limitation": {"type": ["string", "null"]},
            "evidence_ref": _ref(),
        },
        "CapabilityDisposition",
    ),
}
DEFINITION_CONSTRUCTS = ("TypeDefinition", "LinkDefinition", "ConstraintDefinition", "DerivedDefinition",
                         "ContractDefinition", "MarkingSchemeDefinition", "SecurityProfileDefinition",
                         "CapabilityDisposition")
DOCUMENT_CONSTRUCTS = ("OntologyPackage", "Namespace", "Module")
_DEFS["Definition"] = {
    "type": "object",
    "required": ["construct"],
    "properties": {"construct": {"enum": list(DEFINITION_CONSTRUCTS)}},
    "allOf": [
        {"if": {"properties": {"construct": {"const": name}}}, "then": {"$ref": f"#/$defs/{name}"}}
        for name in DEFINITION_CONSTRUCTS
    ],
}

OAC_META_SCHEMA: Mapping[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:ocor:schema:oac-document:1.0",
    "title": "OCOR Ontology-as-Code document (ADD v1.3 §3.1.1)",
    "type": "object",
    "required": ["construct"],
    "properties": {"construct": {"enum": list(DOCUMENT_CONSTRUCTS)}},
    "allOf": [
        {"if": {"properties": {"construct": {"const": name}}}, "then": {"$ref": f"#/$defs/{name}"}}
        for name in DOCUMENT_CONSTRUCTS
    ],
    "$defs": _DEFS,
}
_VALIDATOR = jsonschema.Draft202012Validator(OAC_META_SCHEMA)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of overwriting them."""


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", key_node.start_mark)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _diagnostic(code: DiagnosticCode, path: str, message: str) -> C1Diagnostic:
    return C1Diagnostic(code, path, message[:500])


def _plain(value: Any, path: str) -> Any:
    """Return a JSON-compatible, NFC-normalised copy; reject lossy or non-JSON values."""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise C1Error((_diagnostic(DiagnosticCode.TYPE_ERROR, path, "mapping keys must be strings"),))
            normal = unicodedata.normalize("NFC", key)
            if normal in out:
                raise C1Error((_diagnostic(DiagnosticCode.DUPLICATE_RESOURCE, path,
                                           f"key {normal!r} is duplicated after NFC normalisation"),))
            out[normal] = _plain(child, f"{path}/{normal}")
        return out
    if isinstance(value, (list, tuple)):
        return [_plain(child, f"{path}/{index}") for index, child in enumerate(value)]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise C1Error((_diagnostic(DiagnosticCode.TYPE_ERROR, path, "timestamp without offset"),))
        return format_utc_timestamp(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        raise C1Error((_diagnostic(DiagnosticCode.TYPE_ERROR, path,
                                   "binary floating point is lossy; write decimals as strings"),))
    if value is None or isinstance(value, (bool, int)):
        return value
    raise C1Error((_diagnostic(DiagnosticCode.TYPE_ERROR, path, f"unsupported value {type(value).__name__}"),))


class YamlOacParser:
    """OacParser: YAML 1.1 safe subset (JSON is a subset) with duplicate keys rejected."""

    def parse(self, source: SourceUnit) -> Mapping[str, Any]:
        try:
            if source.syntax is SourceSyntax.JSON:
                parsed = json.loads(source.content.decode("utf-8"), object_pairs_hook=_unique_pairs)
            else:
                parsed = yaml.load(source.content, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass
        except (yaml.YAMLError, ValueError) as exc:
            raise C1Error((_diagnostic(DiagnosticCode.SOURCE_INVALID, source.source_path,
                                       f"cannot parse {source.syntax.value}: {exc}"),)) from exc
        if not isinstance(parsed, Mapping):
            raise C1Error((_diagnostic(DiagnosticCode.TYPE_ERROR, source.source_path,
                                       "an OaC document must be a mapping"),))
        result: dict[str, Any] = _plain(parsed, source.source_path)
        return result


def _error_path(source_path: str, error: jsonschema.ValidationError) -> str:
    pointer = "/".join(str(part) for part in error.absolute_path)
    return f"{source_path}/{pointer}" if pointer else source_path


def _leaf_errors(error: jsonschema.ValidationError) -> list[jsonschema.ValidationError]:
    if not error.context:
        return [error]
    return [leaf for child in error.context for leaf in _leaf_errors(child)]


def meta_schema_diagnostics(source_path: str, document: Mapping[str, Any]) -> list[C1Diagnostic]:
    """Validate one OaC document against OAC_META_SCHEMA; return localised diagnostics."""
    diagnostics: list[C1Diagnostic] = []
    for error in _VALIDATOR.iter_errors(document):
        for leaf in _leaf_errors(error):
            code = DiagnosticCode.TYPE_ERROR if leaf.validator == "type" else DiagnosticCode.SOURCE_INVALID
            diagnostics.append(_diagnostic(code, _error_path(source_path, leaf), leaf.message))
    for index, definition in enumerate(document.get("definitions", ()) if document.get("construct") == "Module"
                                       else ()):
        owner = definition.get("execution_owner") if isinstance(definition, Mapping) else None
        if isinstance(owner, list) and len(set(map(str, owner))) > 1:
            diagnostics.append(_diagnostic(DiagnosticCode.MULTIPLE_EXECUTION_OWNERS,
                                           f"{source_path}/definitions/{index}/execution_owner",
                                           "a definition has exactly one execution_owner (ADD v1.3 :427)"))
    return sorted(set(diagnostics))


def canonical_decimal(value: str, path: str) -> str:
    """Canonical decimal string: no exponent, no superfluous zeros, '-0' is '0'."""
    if not isinstance(value, str) or re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", value) is None:
        raise C1Error((_diagnostic(DiagnosticCode.TYPE_ERROR, path, "decimal must be a plain decimal string"),))
    try:
        number = Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - excluded by the pattern above
        raise C1Error((_diagnostic(DiagnosticCode.TYPE_ERROR, path, "invalid decimal"),)) from exc
    if number == 0:
        return "0"
    text = format(number.normalize(), "f")
    return text


def canonical_timestamp(value: str, path: str) -> str:
    """RFC 3339 timestamp with an explicit offset normalised to UTC with the Z suffix."""
    if not isinstance(value, str) or re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})", value
    ) is None:
        raise C1Error((_diagnostic(DiagnosticCode.TYPE_ERROR, path,
                                   "timestamp must be RFC 3339 with an explicit offset"),))
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise C1Error((_diagnostic(DiagnosticCode.TYPE_ERROR, path, "invalid RFC 3339 timestamp"),)) from exc
    return format_utc_timestamp(parsed)


def parse_value_type(ref: str, path: str) -> dict[str, Any]:
    """Parse a value_type_ref into its unambiguous IR representation (FR-024)."""

    def fail(message: str) -> C1Error:
        return C1Error((_diagnostic(DiagnosticCode.TYPE_ERROR, path, message),))

    if ref in PRIMITIVES:
        return {"family": "primitive", "primitive": ref}
    for container in ("list", "set", "timeseries"):
        if ref.startswith(f"{container}<") and ref.endswith(">"):
            element = parse_value_type(ref[len(container) + 1 : -1], path)
            if container == "timeseries":
                return {"family": "timeseries", "value": element}
            return {"family": "container", "container": container, "element": element}
    if ref.startswith("map<string,") and ref.endswith(">"):
        return {"family": "container", "container": "map", "key": {"family": "primitive", "primitive": "string"},
                "element": parse_value_type(ref[len("map<string,") : -1], path)}
    prefixes = {"struct:": ("structured", "type_ref"), "enum:": ("enum", "type_ref"),
                "ref:": ("object_reference", "type_ref"), "sensitive_ref:": ("sensitive_reference", "security_profile_ref")}
    for prefix, (family, field) in prefixes.items():
        if ref.startswith(prefix) and re.fullmatch(URN, ref[len(prefix):]):
            return {"family": family, field: ref[len(prefix):]}
    if ref.startswith("geo:") and ref[4:] in GEOMETRIES:
        return {"family": "geospatial", "geometry": ref[4:]}
    if ref.startswith("media:") and ref[6:] in MEDIA:
        return {"family": "media", "media_kind": ref[6:]}
    if ref.startswith("quantity:") and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", ref[9:]):
        return {"family": "quantity", "dimension": ref[9:]}
    raise fail(f"unknown value type {ref!r}")


def normalise_default(value_type: Mapping[str, Any], value: Any, path: str) -> Any:
    """Normalise a default to the canonical form of its value type; no lossy coercion."""
    primitive = value_type.get("primitive") if value_type.get("family") == "primitive" else None
    expected: dict[str, type | tuple[type, ...]] = {"string": str, "uri": str, "bytes": str, "date": str,
                                                     "boolean": bool, "integer": int}
    if primitive == "decimal":
        return canonical_decimal(value, path)
    if primitive == "datetime":
        return canonical_timestamp(value, path)
    if primitive in expected and isinstance(value, expected[primitive]) and not (
        primitive == "integer" and isinstance(value, bool)
    ):
        return value
    if value_type.get("family") == "enum" and isinstance(value, str):
        return value
    raise C1Error((_diagnostic(DiagnosticCode.TYPE_ERROR, path,
                               f"default is not compatible with value type {value_type.get('family')}"),))
