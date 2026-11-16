"""C1 -- contract and artefact generators from one Canonical IR, with the drift check.

Realises LLD v1.1 §2.1 (docs/OCOR_LLD_v1.1.md :107): JSON Schema, OpenAPI, AsyncAPI,
Proto, MCP descriptor and Python/TypeScript SDK are produced from the same IR, and
drift between a generated artefact and the IR blocks the release. FR-043/FR-044
(Requirement Register v1.1 :139-140): every declared target is produced and traced
to the same ``irDigest``, with no backend dialect or physical schema exposed.
NFR-020 (:151): every artefact carries ``ontologyRelease``, ``irDigest``,
``compilerVersion`` and ``mappingVersion``. Output is deterministic bit for bit
(NFR-051): sorted inputs, sorted JSON keys, no clock and no randomness.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urljoin

from referencing import Registry
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from .ir import ARTIFACT_MEDIA_TYPES, malformed_core_rejected, parse_core, require_core_shape
from .mcp_profile import McpProfileError, without_context_overwrite
from .ports import ArtifactManifestEntry, C1Diagnostic, C1Error, CanonicalIrRelease, DiagnosticCode

DECIMAL_PATTERN = r"^-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$"
# FABLE52-POST-POC-PROGRAMME (2026-11-11) point 1: the only declaration of the
# MCP revision the generated descriptor reports.
MCP_PROTOCOL_REVISION = "2026-07-28"


def _drift(path: str, message: str) -> C1Diagnostic:
    return C1Diagnostic(DiagnosticCode.ARTIFACT_DRIFT, path, message)


def local_name(urn: str) -> str:
    return urn.rsplit(":", 1)[-1]


def component_name(urn: str) -> str:
    """An OpenAPI/JSON Schema component key for an IR type: ``[A-Za-z0-9._-]`` only."""
    return re.sub(r"[^A-Za-z0-9._-]", ".", urn)


def pascal(urn: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", local_name(urn)) if part)


def snake(urn: str) -> str:
    return "_".join(part.lower() for part in re.split(r"[^A-Za-z0-9]+", local_name(urn)) if part)


def _json(document: Any) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


class _Model:
    """Read-only view of the IR used by every generator."""

    def __init__(self, core: Mapping[str, Any], ir_digest: str) -> None:
        self.core = core
        release = core["release"]
        self.package_id = str(release["package_id"])
        self.ids = {
            "ontologyRelease": f"{release['package_id']}@{release['semantic_version']}",
            "irDigest": ir_digest,
            "compilerVersion": str(release["compiler_version"]),
            "mappingVersion": str(release["mapping_version"]),
        }
        self.types = {t["type_id"]: t for t in core["types"]}
        self.contracts = list(core["named_contracts"])

    # -- JSON Schema of IR value types ------------------------------------------------
    def value_schema(self, value_type: Mapping[str, Any], ref: Callable[[str], str]) -> dict[str, Any]:
        family = value_type["family"]
        if family == "primitive":
            primitive = value_type["primitive"]
            return {
                "boolean": {"type": "boolean"},
                "bytes": {"type": "string", "contentEncoding": "base64"},
                "date": {"type": "string", "format": "date"},
                "datetime": {"type": "string", "format": "date-time"},
                "decimal": {"type": "string", "pattern": DECIMAL_PATTERN},
                "integer": {"type": "integer"},
                "string": {"type": "string"},
                "uri": {"type": "string", "format": "uri"},
            }[primitive]
        if family == "container":
            element = self.value_schema(value_type["element"], ref)
            if value_type["container"] == "map":
                return {"type": "object", "additionalProperties": element}
            schema: dict[str, Any] = {"type": "array", "items": element}
            if value_type["container"] == "set":
                schema["uniqueItems"] = True
            return schema
        if family == "timeseries":
            return {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["at", "value"],
                "properties": {"at": {"type": "string", "format": "date-time"},
                               "value": self.value_schema(value_type["value"], ref)}}}
        if family == "geospatial":
            return {"type": "object", "additionalProperties": False, "required": ["geometry", "coordinates"],
                    "properties": {"geometry": {"const": value_type["geometry"]},
                                   "coordinates": {"type": "array", "items": {"type": "number"}}}}
        if family == "media":
            return {"type": "object", "additionalProperties": False, "required": ["media_kind", "uri", "digest"],
                    "properties": {"media_kind": {"const": value_type["media_kind"]},
                                   "uri": {"type": "string", "format": "uri"},
                                   "digest": {"type": "string", "pattern": "^urn:sha256:[0-9a-f]{64}$"}}}
        if family == "quantity":
            return {"type": "object", "additionalProperties": False, "required": ["value", "unit"],
                    "properties": {"value": {"type": "string", "pattern": DECIMAL_PATTERN},
                                   "unit": {"type": "string"}}}
        if family == "sensitive_reference":
            return {"type": "string", "format": "uri",
                    "description": "reference to a protected value under " + value_type["security_profile_ref"]}
        if family in {"structured", "enum"}:
            return {"$ref": ref(value_type["type_ref"])}
        if family == "object_reference":
            return {"type": "string", "description": "Stable Resource ID of " + value_type["type_ref"]}
        raise C1Error((C1Diagnostic(DiagnosticCode.TYPE_ERROR, "value_type", f"no schema for {family!r}"),))

    def type_schemas(self, ref: Callable[[str], str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for type_id, type_ir in sorted(self.types.items()):
            if type_ir["kind"] == "ENUM":
                out[component_name(type_id)] = {"title": type_id, "type": "string", "enum": list(type_ir["values"])}
                continue
            properties: dict[str, Any] = {}
            required: list[str] = []
            for prop in type_ir["properties"]:
                schema = self.value_schema(prop["value_type"], ref)
                if prop["cardinality"] == "MANY":
                    schema = {"type": "array", "items": schema}
                if prop["nullable"]:
                    schema = {"anyOf": [schema, {"type": "null"}]}
                else:
                    required.append(prop["property_id"])
                if "default" in prop:
                    schema = {**schema, "default": prop["default"]}
                properties[prop["property_id"]] = schema
            entry: dict[str, Any] = {"title": type_id, "type": "object", "additionalProperties": False,
                                     "properties": properties}
            if required:
                entry["required"] = sorted(required)
            out[component_name(type_id)] = entry
        return out

    def contract_schema(self, schema: Any, ref: Callable[[str], str]) -> Any:
        if isinstance(schema, Mapping):
            return {k: (ref(v) if k == "$ref" and isinstance(v, str) else self.contract_schema(v, ref))
                    for k, v in schema.items()}
        if isinstance(schema, (list, tuple)):
            return [self.contract_schema(v, ref) for v in schema]
        return schema

    def requests(self) -> list[Mapping[str, Any]]:
        return [c for c in self.contracts if c["kind"] != "EVENT"]

    def events(self) -> list[Mapping[str, Any]]:
        return [c for c in self.contracts if c["kind"] == "EVENT"]


def _json_schema(model: _Model) -> bytes:
    def ref(type_id: str) -> str:
        return f"#/$defs/{component_name(type_id)}"

    return _json({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{model.package_id}:json-schema",
        "title": model.ids["ontologyRelease"],
        "x-ocor-release": model.ids,
        "$defs": model.type_schemas(ref),
    })


def _openapi(model: _Model) -> bytes:
    def ref(type_id: str) -> str:
        return f"#/components/schemas/{component_name(type_id)}"

    paths: dict[str, Any] = {}
    for contract in sorted(model.requests(), key=lambda c: str(c["contract_id"])):
        name = local_name(contract["contract_id"])
        paths[f"/contracts/{name}"] = {"post": {
            "operationId": name.replace("-", "_"),
            "summary": f"{contract['kind']} {contract['contract_id']}",
            "x-ocor-contract": {"contract_id": contract["contract_id"], "version": contract["version"],
                                "effect_class": contract["effect_class"], "risk_class": contract["risk_class"]},
            "requestBody": {"required": True, "content": {"application/json": {
                "schema": model.contract_schema(contract["input_schema"], ref)}}},
            "responses": {
                "200": {"description": "result", "content": {"application/json": {
                    "schema": model.contract_schema(contract["output_schema"], ref)}}},
                "default": {"description": "typed error", "content": {"application/json": {
                    "schema": {"type": "object", "required": ["code"], "properties": {
                        "code": {"type": "string", "enum": list(contract["error_model"]) or ["INTERNAL"]}}}}}},
            },
        }}
    return _json({
        "openapi": "3.1.0",
        "info": {"title": model.ids["ontologyRelease"], "version": model.core["release"]["semantic_version"],
                 "x-ocor-release": model.ids},
        "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema",
        "paths": paths,
        "components": {"schemas": model.type_schemas(ref)},
    })


def _asyncapi(model: _Model) -> bytes:
    def ref(type_id: str) -> str:
        return f"#/components/schemas/{component_name(type_id)}"

    channels: dict[str, Any] = {}
    operations: dict[str, Any] = {}
    for contract in sorted(model.events(), key=lambda c: str(c["contract_id"])):
        name = local_name(contract["contract_id"])
        channels[name] = {"address": f"{model.package_id}/{name}", "messages": {name: {
            "name": name, "contentType": "application/json",
            "payload": model.contract_schema(contract["input_schema"], ref)}}}
        operations[f"publish-{name}"] = {"action": "send", "channel": {"$ref": f"#/channels/{name}"},
                                         "messages": [{"$ref": f"#/channels/{name}/messages/{name}"}]}
    return _json({
        "asyncapi": "3.0.0",
        "info": {"title": model.ids["ontologyRelease"], "version": model.core["release"]["semantic_version"],
                 "x-ocor-release": model.ids},
        "channels": channels,
        "operations": operations,
        "components": {"schemas": model.type_schemas(ref)},
    })


def _mcp_ref(type_id: str) -> str:
    return f"#/$defs/{component_name(type_id)}"


# The profile refuses a schema past these bounds. The generator fails closed
# at the same limits so render cannot emit a descriptor the profile rejects
# only for size.
_MCP_MAX_SCHEMA_DEPTH = 32
_MCP_MAX_SCHEMA_NODES = 4096
_MCP_DEFS_PREFIX = "#/$defs/"
_MCP_INSTANCE_KEYS = ("const", "default", "examples", "enum")


def _mcp_error(code: DiagnosticCode, path: str, message: str) -> C1Error:
    text = " ".join(message.split())
    if len(text) > 500:
        text = text[:500]
    if not text:
        text = "MCP generation failed"
    return C1Error((C1Diagnostic(code, path, text),))


def _mcp_bounds(path: str, depth: int, nodes: int) -> None:
    if depth > _MCP_MAX_SCHEMA_DEPTH or nodes > _MCP_MAX_SCHEMA_NODES:
        raise _mcp_error(DiagnosticCode.TYPE_ERROR, path, "MCP schema exceeds the revision bounds")


def _mcp_declared_id(node: object) -> str | None:
    """Identifier of a schema object, using the profile's ``$id`` rule.

    A trailing empty fragment is removed before the join, as referencing
    0.37.0 does. ``#`` and an empty string are not identifiers. A non-string
    ``$id`` is ignored here; the library crawl rejects it in the post-check.
    """

    if not isinstance(node, Mapping):
        return None
    value = node.get("$id")
    if not isinstance(value, str) or not value:
        return None
    stripped = value.rstrip("#")
    if not stripped:
        return None
    return stripped


def _mcp_resource_uri(node: object, base_uri: str, path: str) -> str:
    identifier = _mcp_declared_id(node)
    if identifier is None:
        return base_uri
    try:
        return urljoin(base_uri, identifier)
    except ValueError as exc:
        raise _mcp_error(DiagnosticCode.TYPE_ERROR, path, "MCP $id is not a valid URI reference") from exc


def _mcp_changes_resource(node: object, base_uri: str, path: str) -> bool:
    return _mcp_resource_uri(node, base_uri, path) != base_uri


def _mcp_children(node: Mapping[str, Any], path: str) -> list[Any]:
    try:
        return list(DRAFT202012.subresources_of(node))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _mcp_error(DiagnosticCode.TYPE_ERROR, path, "MCP schema resource is not resolvable") from exc


def _mcp_defs_name(ref: str) -> str | None:
    """Return the ``#/$defs/<name>`` component, never a deeper pointer."""

    if not ref.startswith(_MCP_DEFS_PREFIX):
        return None
    name = ref[len(_MCP_DEFS_PREFIX):]
    if not name or "/" in name:
        return None
    return name


def _mcp_take_ref(node: Mapping[str, Any], names: set[str], raw: set[str]) -> None:
    ref = node.get("$ref")
    if not isinstance(ref, str):
        return
    raw.add(ref)
    parsed = _mcp_defs_name(ref)
    if parsed is not None:
        names.add(parsed)


def _mcp_walk_json_refs(value: object, names: set[str], raw: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                raw.add(item)
                parsed = _mcp_defs_name(item)
                if parsed is not None:
                    names.add(parsed)
            else:
                _mcp_walk_json_refs(item, names, raw)
        return
    if isinstance(value, list):
        for item in value:
            _mcp_walk_json_refs(item, names, raw)


def _mcp_take_instance(node: Mapping[str, Any], names: set[str], raw: set[str]) -> None:
    for key in _MCP_INSTANCE_KEYS:
        if key in node:
            _mcp_walk_json_refs(node[key], names, raw)


def _mcp_fragment_refs(
    node: object,
    resource_uri: str,
    path: str,
    names: set[str],
    raw: set[str],
    *,
    nodes: list[int],
    depth: int,
) -> None:
    """Collect references that resolve in ``resource_uri``.

    Descent follows referencing 0.37.0 subresources and stops where an
    ``$id`` joins to a different URI. ``const``, ``default``, ``examples``
    and ``enum`` stay on this resource: the generator rewrites every
    ``$ref``, including those in instance data.
    """

    if not isinstance(node, Mapping):
        return
    nodes[0] += 1
    _mcp_bounds(path, depth, nodes[0])
    _mcp_take_ref(node, names, raw)
    _mcp_take_instance(node, names, raw)
    for child in _mcp_children(node, path):
        if isinstance(child, Mapping) and _mcp_changes_resource(child, resource_uri, path):
            continue
        _mcp_fragment_refs(child, resource_uri, path, names, raw, nodes=nodes, depth=depth + 1)


def _mcp_seed_refs(
    node: Mapping[str, Any],
    resource_uri: str,
    path: str,
    names: set[str],
    raw: set[str],
    *,
    nodes: list[int],
    depth: int,
) -> None:
    """References of one resource, excluding that resource's own ``$defs``.

    A local definition, and a reference that appears only inside it, is not
    reachable until some other node of the resource selects its name.
    """

    nodes[0] += 1
    _mcp_bounds(path, depth, nodes[0])
    defs = node.get("$defs")
    if defs is not None and not isinstance(defs, Mapping):
        raise _mcp_error(DiagnosticCode.TYPE_ERROR, path, "MCP $defs must be an object")
    _mcp_take_ref(node, names, raw)
    _mcp_take_instance(node, names, raw)
    skip = {id(value) for value in defs.values()} if isinstance(defs, Mapping) else set()
    for child in _mcp_children(node, path):
        if id(child) in skip or not isinstance(child, Mapping):
            continue
        if _mcp_changes_resource(child, resource_uri, path):
            continue
        _mcp_fragment_refs(child, resource_uri, path, names, raw, nodes=nodes, depth=depth + 1)


def _mcp_iter_resources(
    root: Mapping[str, Any],
    base_uri: str,
    path: str,
) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    nodes = 0

    def visit(node: object, uri: str, depth: int, *, is_root: bool) -> None:
        nonlocal nodes
        if not isinstance(node, Mapping):
            return
        nodes += 1
        _mcp_bounds(path, depth, nodes)
        current = uri
        if is_root or _mcp_changes_resource(node, uri, path):
            current = uri if is_root else _mcp_resource_uri(node, uri, path)
            if not isinstance(node, dict):
                raise _mcp_error(DiagnosticCode.TYPE_ERROR, path, "MCP schema resource is not an object")
            found.append((current, node))
        for child in _mcp_children(node, path):
            visit(child, current, depth + 1, is_root=False)

    visit(root, base_uri, 1, is_root=True)
    return found


def _mcp_record_user_defs(root: Mapping[str, Any], path: str) -> dict[int, dict[str, Any]]:
    """Snapshot each resource's ``$defs`` before the closure replaces them."""

    recorded: dict[int, dict[str, Any]] = {}
    nodes = 0

    def visit(node: object, depth: int) -> None:
        nonlocal nodes
        if not isinstance(node, Mapping):
            return
        nodes += 1
        _mcp_bounds(path, depth, nodes)
        defs = node.get("$defs")
        if isinstance(defs, Mapping) and isinstance(node, dict):
            recorded[id(node)] = dict(defs)
        for child in _mcp_children(node, path):
            visit(child, depth + 1)

    visit(root, 1)
    return recorded


def _mcp_select_body(
    resource: dict[str, Any],
    name: str,
    user_defs: Mapping[str, Any],
    type_schemas: Mapping[str, Any],
    placed: dict[tuple[int, str], Any],
    path: str,
) -> Any:
    key = (id(resource), name)
    if key in placed:
        return placed[key]
    user_body = user_defs[name] if name in user_defs else None
    typed = type_schemas[name] if name in type_schemas else None
    if user_body is not None and typed is not None and user_body != typed:
        raise _mcp_error(DiagnosticCode.TYPE_ERROR, path, f"MCP definition name clash for {name}")
    if user_body is not None:
        source: Any = user_body
    elif typed is not None:
        source = typed
    else:
        current = resource.get("$defs")
        if isinstance(current, Mapping) and name in current:
            source = current[name]
        else:
            raise _mcp_error(DiagnosticCode.UNRESOLVED_REFERENCE, path, f"unresolved MCP definition {name}")
    body = copy.deepcopy(source)
    placed[key] = body
    return body


def _mcp_close_resource(
    resource: dict[str, Any],
    resource_uri: str,
    user_defs: Mapping[str, Any],
    type_schemas: Mapping[str, Any],
    placed: dict[tuple[int, str], Any],
    path: str,
) -> bool:
    names: set[str] = set()
    raw: set[str] = set()
    nodes = [0]
    _mcp_seed_refs(resource, resource_uri, path, names, raw, nodes=nodes, depth=1)
    resolved: dict[str, Any] = {}
    pending = set(names)
    while pending:
        _mcp_bounds(path, 1, len(resolved) + len(pending))
        name = pending.pop()
        if name in resolved:
            continue
        body = _mcp_select_body(resource, name, user_defs, type_schemas, placed, path)
        resolved[name] = body
        if isinstance(body, Mapping) and not _mcp_changes_resource(body, resource_uri, path):
            inner_names: set[str] = set()
            inner_raw: set[str] = set()
            _mcp_fragment_refs(body, resource_uri, path, inner_names, inner_raw, nodes=nodes, depth=1)
            pending.update(name for name in inner_names if name not in resolved)
    if not resolved:
        if "$defs" in resource:
            resource.pop("$defs")
            return True
        return False
    new_defs = {name: resolved[name] for name in sorted(resolved)}
    if resource.get("$defs") != new_defs:
        resource["$defs"] = new_defs
        return True
    return False


def _mcp_post_check(tree: Mapping[str, Any], base_uri: str, path: str) -> None:
    """Reject a schema whose ``$ref`` does not resolve in referencing 0.37.0."""

    try:
        registry = Registry().with_resource(base_uri, DRAFT202012.create_resource(tree)).crawl()
    except (Unresolvable, AttributeError, TypeError, ValueError) as exc:
        raise _mcp_error(DiagnosticCode.UNRESOLVED_REFERENCE, path, "unresolved MCP definition") from exc
    for uri, resource in registry.items():
        contents = resource.contents
        if not isinstance(contents, Mapping):
            continue
        names: set[str] = set()
        raw: set[str] = set()
        _mcp_fragment_refs(contents, uri, path, names, raw, nodes=[0], depth=1)
        resolver = registry.resolver(uri)
        for ref in sorted(raw):
            if not isinstance(ref, str) or not ref.startswith("#"):
                raise _mcp_error(DiagnosticCode.UNRESOLVED_REFERENCE, path, "unresolved MCP definition")
            try:
                resolver.lookup(ref)
            except Unresolvable as exc:
                detail = ref if len(ref) <= 420 else ref[:420]
                raise _mcp_error(
                    DiagnosticCode.UNRESOLVED_REFERENCE,
                    path,
                    f"unresolved MCP definition {detail}",
                ) from exc


def _mcp_attach_definitions(
    schema: Any,
    type_schemas: Mapping[str, Any],
    *,
    path: str,
    base_uri: str,
) -> Any:
    """Place each reachable ``#/$defs`` closure on the resource that uses it.

    MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15), repaired for the
    per-resource class in VF-001 of cycle 8. A nested ``$id`` that joins to
    a new URI is its own JSON Schema resource and receives only the closure
    of the references that resolve there. Unreferenced local definitions are
    omitted. A definition body that does not change the URI contributes its
    references to the enclosing resource. The descriptor still has no
    top-level ``$defs``. A name that clashes with a different type schema,
    or a reference with no definition, is a typed generation error. The
    emitted schema is checked with referencing 0.37.0 before it is returned.
    """

    if not isinstance(schema, Mapping):
        return schema
    copied = copy.deepcopy(schema)
    if not isinstance(copied, dict):
        raise _mcp_error(DiagnosticCode.TYPE_ERROR, path, "MCP schema resource is not an object")
    user_defs = _mcp_record_user_defs(copied, path)
    placed: dict[tuple[int, str], Any] = {}
    for _pass in range(_MCP_MAX_SCHEMA_NODES):
        changed = False
        for uri, resource in _mcp_iter_resources(copied, base_uri, path):
            if _mcp_close_resource(
                resource,
                uri,
                user_defs.get(id(resource), {}),
                type_schemas,
                placed,
                path,
            ):
                changed = True
        if not changed:
            _mcp_post_check(copied, base_uri, path)
            return copied
    raise _mcp_error(DiagnosticCode.TYPE_ERROR, path, "MCP schema exceeds the revision bounds")


def _mcp_collect_ids(node: object, found: set[str], path: str, depth: int, nodes: list[int]) -> None:
    nodes[0] += 1
    _mcp_bounds(path, depth, nodes[0])
    if isinstance(node, Mapping):
        declared = node.get("$id")
        if isinstance(declared, str):
            found.add(declared)
        for value in node.values():
            _mcp_collect_ids(value, found, path, depth + 1, nodes)
        return
    if isinstance(node, list):
        for item in node:
            _mcp_collect_ids(item, found, path, depth + 1, nodes)


def _mcp_synthetic_uri(index: int, field: str, declared_ids: set[str]) -> str:
    """Match the profile's embedded base, skipping any declared ``$id``."""

    candidate = f"urn:ocor:embedded-tool:{index}:{field}"
    suffix = 2
    while candidate in declared_ids:
        candidate = f"urn:ocor:embedded-tool:{index}:{field}:{suffix}"
        suffix += 1
        if suffix > _MCP_MAX_SCHEMA_NODES:
            raise _mcp_error(
                DiagnosticCode.TYPE_ERROR,
                "mcp-descriptor",
                "MCP schema exceeds the revision bounds",
            )
    return candidate


def _mcp_base_uri(schema: object, index: int, field: str, declared_ids: set[str]) -> str:
    """The profile's base: a root ``$id`` when present, otherwise a synthetic URI."""

    declared = _mcp_declared_id(schema)
    if declared is not None:
        return declared
    return _mcp_synthetic_uri(index, field, declared_ids)


def _mcp(model: _Model) -> bytes:
    type_schemas = model.type_schemas(_mcp_ref)

    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    ordered = sorted(model.requests(), key=lambda c: (local_name(str(c["contract_id"])), str(c["contract_id"])))
    for contract in ordered:
        name = local_name(str(contract["contract_id"]))
        if name in seen:
            raise C1Error((C1Diagnostic(
                DiagnosticCode.TYPE_ERROR, "mcp-descriptor", f"duplicate MCP tool name {name}",
            ),))
        seen.add(name)
        path = f"mcp-descriptor/{name}"
        try:
            projected = without_context_overwrite(
                model.contract_schema(contract["input_schema"], _mcp_ref)
            )
        except McpProfileError as exc:
            raise C1Error((C1Diagnostic(DiagnosticCode.TYPE_ERROR, path, str(exc)),)) from exc
        prepared.append({
            "name": name,
            "description": f"{contract['kind']} {contract['contract_id']}@{contract['version']}",
            "inputSchema": projected,
            "outputSchema": model.contract_schema(contract["output_schema"], _mcp_ref),
            "annotations": {
                "readOnlyHint": contract["effect_class"] == "READ_ONLY",
                "riskClass": contract["risk_class"],
            },
            "_path": path,
        })
    declared_ids: set[str] = set()
    id_nodes = [0]
    for tool in prepared:
        _mcp_collect_ids(tool["inputSchema"], declared_ids, "mcp-descriptor", 1, id_nodes)
        _mcp_collect_ids(tool["outputSchema"], declared_ids, "mcp-descriptor", 1, id_nodes)
    tools = []
    for index, tool in enumerate(prepared):
        path = str(tool.pop("_path"))
        for field in ("inputSchema", "outputSchema"):
            tool[field] = _mcp_attach_definitions(
                tool[field],
                type_schemas,
                path=path,
                base_uri=_mcp_base_uri(tool[field], index, field, declared_ids),
            )
        tools.append(tool)
    return _json({
        "x-ocor-mcp-protocol-revision": MCP_PROTOCOL_REVISION,
        "x-ocor-release": model.ids,
        "tools": tools,
    })


class _Proto:
    """proto3 rendering of the IR types plus one gRPC service over the request contracts."""

    SCALARS = {"boolean": "bool", "bytes": "bytes", "date": "string", "datetime": "string", "decimal": "string",
               "integer": "int64", "string": "string", "uri": "string"}

    def __init__(self, model: _Model) -> None:
        self.model = model
        self.extra: dict[str, list[str]] = {}

    def wrapper(self, name: str, fields: Sequence[str]) -> str:
        if name in self.extra and self.extra[name] != list(fields):
            raise C1Error((C1Diagnostic(DiagnosticCode.TYPE_ERROR, "protobuf", f"message name clash {name}"),))
        self.extra[name] = list(fields)
        return name

    def field_type(self, value_type: Mapping[str, Any], hint: str) -> tuple[str, bool]:
        """(proto type, repeated) for an IR value type; nested containers get wrappers."""
        family = value_type["family"]
        if family == "primitive":
            return self.SCALARS[value_type["primitive"]], False
        if family in {"structured", "enum"}:
            return pascal(value_type["type_ref"]), False
        if family in {"object_reference", "sensitive_reference"}:
            return "string", False
        if family == "geospatial":
            return self.wrapper("OcorGeometry", ["string geometry = 1;", "repeated double coordinates = 2;"]), False
        if family == "media":
            return self.wrapper("OcorMediaRef", ["string media_kind = 1;", "string uri = 2;", "string digest = 3;"]), False
        if family == "quantity":
            return self.wrapper("OcorQuantity", ["string value = 1;", "string unit = 2;"]), False
        if family == "timeseries":
            inner, repeated = self.field_type(value_type["value"], hint + "Value")
            prefix = "repeated " if repeated else ""
            return self.wrapper(hint + "Point", ["string at = 1;", f"{prefix}{inner} value = 2;"]), True
        if family == "container":
            inner, repeated = self.field_type(value_type["element"], hint + "Item")
            if repeated:
                inner = self.wrapper(hint + "Item", [f"repeated {inner} values = 1;"])
            if value_type["container"] == "map":
                return f"map<string, {inner}>", False
            return inner, True
        raise C1Error((C1Diagnostic(DiagnosticCode.TYPE_ERROR, "protobuf", f"no proto type for {family!r}"),))

    def render(self) -> bytes:
        model = self.model
        lines = ['syntax = "proto3";', ""]
        lines += [f"// {name}: {value}" for name, value in model.ids.items()]
        lines += ["", f"package ocor.{snake(model.package_id)}.v{model.core['release']['semantic_version'].split('.')[0]};",
                  ""]
        names = [pascal(type_id) for type_id in model.types]
        if len(names) != len(set(names)):
            raise C1Error((C1Diagnostic(DiagnosticCode.TYPE_ERROR, "protobuf", "type names collide in proto"),))
        body: list[str] = []
        for type_id, type_ir in sorted(model.types.items()):
            name = pascal(type_id)
            if type_ir["kind"] == "ENUM":
                upper = re.sub(r"[^A-Z0-9]+", "_", local_name(type_id).upper())
                body.append(f"// {type_id}")
                body.append(f"enum {name} {{")
                body.append(f"  {upper}_UNSPECIFIED = 0;")
                body += [f"  {upper}_{re.sub(r'[^A-Z0-9]+', '_', value.upper())} = {i};"
                         for i, value in enumerate(type_ir["values"], start=1)]
                body += ["}", ""]
                continue
            body.append(f"// {type_id}")
            body.append(f"message {name} {{")
            for number, prop in enumerate(type_ir["properties"], start=1):
                field = snake(prop["property_id"])
                proto_type, repeated = self.field_type(prop["value_type"], name + pascal(prop["property_id"]))
                if prop["cardinality"] == "MANY" and not repeated and not proto_type.startswith("map<"):
                    repeated = True
                elif prop["cardinality"] == "MANY":
                    proto_type = self.wrapper(name + pascal(prop["property_id"]) + "Values",
                                              [f"{'repeated ' if repeated else ''}{proto_type} values = 1;"])
                    repeated = True
                label = "repeated " if repeated else ("optional " if prop["nullable"] and not proto_type.startswith("map<")
                                                      else "")
                body.append(f"  {label}{proto_type} {field} = {number}; // {prop['property_id']}")
            body += ["}", ""]
        for name, fields in sorted(self.extra.items()):
            body.append(f"message {name} {{")
            body += [f"  {field}" for field in fields]
            body += ["}", ""]
        requests = sorted(model.requests(), key=lambda c: str(c["contract_id"]))
        if requests:
            body.append("// Request contracts; payloads are the JSON documents of the generated JSON Schema.")
            for contract in requests:
                rpc = pascal(contract["contract_id"])
                body += [f"message {rpc}Request {{", "  string payload_json = 1;", "}", "",
                         f"message {rpc}Response {{", "  string payload_json = 1;", "}", ""]
            body.append(f"service {pascal(model.package_id)}Contracts {{")
            body += [f"  rpc {pascal(c['contract_id'])}({pascal(c['contract_id'])}Request) returns "
                     f"({pascal(c['contract_id'])}Response); // {c['contract_id']}@{c['version']}" for c in requests]
            body += ["}", ""]
        return ("\n".join(lines + body).rstrip("\n") + "\n").encode("utf-8")


def _python_sdk(model: _Model) -> bytes:
    lines = [
        f'"""Generated OCOR SDK for {model.ids["ontologyRelease"]}. Do not edit: regenerate from the IR."""',
        "",
        "from __future__ import annotations",
        "",
        "from collections.abc import Callable, Mapping",
        "from typing import Any, Literal, TypedDict",
        "",
        "RELEASE: Mapping[str, str] = {",
    ]
    lines += [f"    {json.dumps(name)}: {json.dumps(value)}," for name, value in model.ids.items()]
    lines += ["}", ""]
    for type_id, type_ir in sorted(model.types.items()):
        name = pascal(type_id)
        if type_ir["kind"] == "ENUM":
            lines.append(f"{name} = Literal[{', '.join(json.dumps(v) for v in type_ir['values'])}]")
            lines.append("")
            continue
        lines.append(f"{name} = TypedDict({json.dumps(name)}, {{")
        lines += [f"    {json.dumps(prop['property_id'])}: Any," for prop in type_ir["properties"]]
        lines += ["}, total=False)", ""]
    lines.append("CONTRACTS: Mapping[str, Mapping[str, str]] = {")
    lines += [f"    {json.dumps(c['contract_id'])}: {{\"kind\": {json.dumps(c['kind'])}, "
              f"\"version\": {json.dumps(c['version'])}}}," for c in sorted(model.contracts,
                                                                         key=lambda c: str(c["contract_id"]))]
    lines += ["}", "", "",
              "class Client:",
              '    """Calls named contracts through a caller-supplied transport (the OCOR gateway)."""',
              "",
              "    def __init__(self, transport: Callable[[str, str, Mapping[str, Any]], Mapping[str, Any]]) -> None:",
              "        self._transport = transport",
              ""]
    for contract in sorted(model.requests(), key=lambda c: str(c["contract_id"])):
        lines += [f"    def {snake(contract['contract_id'])}(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:",
                  f"        return self._transport({json.dumps(contract['contract_id'])}, "
                  f"RELEASE[\"ontologyRelease\"], payload)", ""]
    return ("\n".join(lines).rstrip("\n") + "\n").encode("utf-8")


def _typescript_sdk(model: _Model) -> bytes:
    lines = [f"// Generated OCOR SDK for {model.ids['ontologyRelease']}. Do not edit: regenerate from the IR.", "",
             "export const RELEASE = {"]
    lines += [f"  {name}: {json.dumps(value)}," for name, value in model.ids.items()]
    lines += ["} as const;", ""]
    for type_id, type_ir in sorted(model.types.items()):
        name = pascal(type_id)
        if type_ir["kind"] == "ENUM":
            lines += [f"export type {name} = {' | '.join(json.dumps(v) for v in type_ir['values'])};", ""]
            continue
        lines.append(f"export interface {name} {{")
        lines += [f"  {json.dumps(prop['property_id'])}?: unknown;" for prop in type_ir["properties"]]
        lines += ["}", ""]
    lines += ["export type Transport = (contractId: string, release: string, payload: unknown) => Promise<unknown>;",
              "", "export class Client {", "  constructor(private readonly transport: Transport) {}", ""]
    for contract in sorted(model.requests(), key=lambda c: str(c["contract_id"])):
        method = snake(contract["contract_id"])
        method = method.split("_")[0] + "".join(p.capitalize() for p in method.split("_")[1:])
        lines += [f"  {method}(payload: unknown): Promise<unknown> {{",
                  f"    return this.transport({json.dumps(contract['contract_id'])}, RELEASE.ontologyRelease, payload);",
                  "  }", ""]
    lines += ["}"]
    return ("\n".join(lines) + "\n").encode("utf-8")


_RENDERERS: Mapping[str, Callable[[_Model], bytes]] = {
    "asyncapi": _asyncapi,
    "json-schema": _json_schema,
    "mcp-descriptor": _mcp,
    "openapi": _openapi,
    "protobuf": lambda model: _Proto(model).render(),
    "sdk-python": _python_sdk,
    "sdk-typescript": _typescript_sdk,
}


class IrArtifactGenerator:
    """ArtifactGenerator: renders the IR artifact_plan and checks drift against it."""

    def render(self, release: CanonicalIrRelease) -> dict[str, bytes]:
        core = parse_core(release.canonical_bytes)
        require_core_shape(core)
        with malformed_core_rejected():
            model = _Model(core, release.ir_digest)
            files: dict[str, bytes] = {}
            for entry in core["artifact_plan"]:
                renderer = _RENDERERS.get(entry["artifact_kind"])
                if renderer is None or ARTIFACT_MEDIA_TYPES.get(entry["artifact_kind"]) != entry["media_type"]:
                    raise C1Error((_drift(entry["artifact_id"], "artifact kind has no generator"),))
                files[entry["artifact_id"]] = renderer(model)
        return dict(sorted(files.items()))

    def generate(self, release: CanonicalIrRelease) -> tuple[ArtifactManifestEntry, ...]:
        files = self.render(release)
        plan = {entry["artifact_id"]: entry["media_type"] for entry in parse_core(release.canonical_bytes)["artifact_plan"]}
        return tuple(ArtifactManifestEntry(artifact_id=artifact_id, media_type=plan[artifact_id],
                                           digest="urn:sha256:" + hashlib.sha256(content).hexdigest())
                     for artifact_id, content in files.items())

    def check_drift(self, release: CanonicalIrRelease, files: Mapping[str, bytes]) -> None:
        """Raise ARTIFACT_DRIFT when files or the attached manifest differ from the IR."""
        expected = self.render(release)
        problems = [_drift(key, "artefact is missing") for key in sorted(set(expected) - set(files))]
        problems += [_drift(key, "artefact is not in the artifact plan") for key in sorted(set(files) - set(expected))]
        problems += [_drift(key, "artefact differs from the IR") for key in sorted(set(expected) & set(files))
                     if bytes(files[key]) != expected[key]]
        # Admission verifies the artifact manifest (ADD v1.3 :523): a missing or partial
        # manifest is drift from the artifact_plan, never a manifest left unchecked.
        if tuple(release.artifacts) != self.generate(release):
            problems.append(_drift("artifacts", "the artefact manifest is missing, incomplete or differs from the IR"))
        if problems:
            raise C1Error(tuple(problems))
