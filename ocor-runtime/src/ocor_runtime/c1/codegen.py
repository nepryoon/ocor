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

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .ir import ARTIFACT_MEDIA_TYPES, parse_core
from .ports import ArtifactManifestEntry, C1Diagnostic, C1Error, CanonicalIrRelease, DiagnosticCode

DECIMAL_PATTERN = r"^-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$"


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


def _mcp(model: _Model) -> bytes:
    def ref(type_id: str) -> str:
        return f"#/$defs/{component_name(type_id)}"

    tools = []
    for contract in sorted(model.requests(), key=lambda c: str(c["contract_id"])):
        tools.append({
            "name": local_name(contract["contract_id"]),
            "description": f"{contract['kind']} {contract['contract_id']}@{contract['version']}",
            "inputSchema": model.contract_schema(contract["input_schema"], ref),
            "outputSchema": model.contract_schema(contract["output_schema"], ref),
            "annotations": {"readOnlyHint": contract["effect_class"] == "READ_ONLY",
                            "riskClass": contract["risk_class"]},
        })
    return _json({"x-ocor-release": model.ids, "$defs": model.type_schemas(ref), "tools": tools})


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
        if release.artifacts and tuple(release.artifacts) != self.generate(release):
            problems.append(_drift("artifacts", "the artefact manifest differs from the IR"))
        if problems:
            raise C1Error(tuple(problems))
