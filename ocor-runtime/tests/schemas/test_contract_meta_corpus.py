"""Schema/meta tests over the contract surfaces without them (OCOR-DEV-REM-0060, NCP-U12, NCR-TESTS-002).

LLD v1.1 §7.2 (docs/OCOR_LLD_v1.1.md:378): "Schema/meta tests verificano record chiusi, exact field set,
canonical bytes, digest e negative corpus". The three standalone JSON Schemas of LLD v1.1 §0.2 (:20-31)
already have them (reports/tests/test_authoritative_contract_conformance.py); this module covers the rest
of the contract surface:

* the 25 component schemas of ``ocor-named-query-gateway.openapi.yaml`` and the 16 of
  ``ocor-governed-memory.openapi.yaml`` (LLD v1.1 §0.2);
* the 19 messages of ``ocor_registry.proto`` (package ``ocor.registry.v1``, LLD v1.1 §0.2);
* the five JSON Schemas embedded in ADD v1.3 (ocor-runtime/docs/governance_dossier/
  OCOR_ADD_v1.3_APPROVED_BASELINE.md: signed canonical IR :468-521, canonical ingestion envelope
  :531-840, MCP tool contract :1593-1986, ActionType contract :2069-2557, event subscription contract
  :2577-2726).

Every fixture is synthesised from the manifested file itself (LLD v1.1 :31), deterministically: a
positive instance per schema, then the negative corpus derived from it. Canonical bytes are RFC 8785
(ocor_runtime.kernel.canonical) for the JSON surfaces and deterministic Protobuf serialisation for the
registry messages; the digest is ``urn:sha256`` of those bytes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import grpc_tools
import pytest
import yaml
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
from google.protobuf.descriptor import Descriptor, FieldDescriptor
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from ocor_runtime.kernel.canonical import canonical_bytes, canonical_digest

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "ocor-runtime/docs/governance_dossier/contracts"
ADD = ROOT / "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md"
GATEWAY = "ocor-named-query-gateway.openapi.yaml"
MEMORY = "ocor-governed-memory.openapi.yaml"
PROTO = "ocor_registry.proto"

COVERED_SURFACE = {
    "ADD#urn:ocor:schema:action-type-contract:1.1",
    "ADD#urn:ocor:schema:canonical-ingestion-envelope:1.2",
    "ADD#urn:ocor:schema:event-subscription-contract:1.1",
    "ADD#urn:ocor:schema:mcp-tool-contract:1.2",
    "ADD#urn:ocor:schema:signed-canonical-ir:1.0",
    "ocor-governed-memory.openapi.yaml#/components/schemas/Digest",
    "ocor-governed-memory.openapi.yaml#/components/schemas/GovernedContext",
    "ocor-governed-memory.openapi.yaml#/components/schemas/GovernedEnvelope",
    "ocor-governed-memory.openapi.yaml#/components/schemas/MemoryAdmissionRequest",
    "ocor-governed-memory.openapi.yaml#/components/schemas/MemoryConsolidationRequest",
    "ocor-governed-memory.openapi.yaml#/components/schemas/MemoryContextAssembly",
    "ocor-governed-memory.openapi.yaml#/components/schemas/MemoryContextAssemblyRequest",
    "ocor-governed-memory.openapi.yaml#/components/schemas/MemoryDeletionRequest",
    "ocor-governed-memory.openapi.yaml#/components/schemas/MemoryHit",
    "ocor-governed-memory.openapi.yaml#/components/schemas/MemoryLifecycleRequest",
    "ocor-governed-memory.openapi.yaml#/components/schemas/MemoryPromotionRequest",
    "ocor-governed-memory.openapi.yaml#/components/schemas/MemoryReceipt",
    "ocor-governed-memory.openapi.yaml#/components/schemas/MemorySearchRequest",
    "ocor-governed-memory.openapi.yaml#/components/schemas/MemorySearchResponse",
    "ocor-governed-memory.openapi.yaml#/components/schemas/OperationReceipt",
    "ocor-governed-memory.openapi.yaml#/components/schemas/Problem",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/Consistency",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/ContractCall",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/EpistemicStatus",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/ExplainRequest",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/GetObjectRequest",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/GetObjectResponse",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/GraphEdge",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/GraphNode",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/GraphResponse",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/IdentityCandidate",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/ObjectPageResponse",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/ObjectSetRequest",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/ObjectSnapshot",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/Problem",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/ProvenanceRequest",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/QueryContext",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/ResourceRef",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/SchemaPin",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/SearchHit",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/SearchRequest",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/SearchResponse",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/ServedContext",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/TemporalInterval",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/TraverseRequest",
    "ocor-named-query-gateway.openapi.yaml#/components/schemas/Uncertainty",
    "ocor_registry.proto#Abstention",
    "ocor_registry.proto#FunctionDescriptor",
    "ocor_registry.proto#FunctionResult",
    "ocor_registry.proto#InvocationContext",
    "ocor_registry.proto#InvokeFunctionRequest",
    "ocor_registry.proto#InvokeModelRequest",
    "ocor_registry.proto#ModelDescriptor",
    "ocor_registry.proto#ModelResult",
    "ocor_registry.proto#PublishFunctionRequest",
    "ocor_registry.proto#PublishModelRequest",
    "ocor_registry.proto#PublishReceipt",
    "ocor_registry.proto#ResolveFunctionRequest",
    "ocor_registry.proto#ResolveModelRequest",
    "ocor_registry.proto#ResourceBudget",
    "ocor_registry.proto#SchemaPin",
    "ocor_registry.proto#TypedValue",
    "ocor_registry.proto#UncertaintyDescriptor",
    "ocor_registry.proto#ValidityAssessment",
    "ocor_registry.proto#VersionPin",
}

# Surfaces that are not closed records, each for a reason the contract states.
NOT_A_RECORD = {
    # a string schema (pattern), not a record
    f"{MEMORY}#/components/schemas/Digest": "string schema ^urn:sha256:[0-9a-f]{64}$",
    # an allOf fragment: every request that composes it is closed with unevaluatedProperties: false
    f"{MEMORY}#/components/schemas/GovernedEnvelope": "allOf fragment of the closed memory requests",
}
# Object-valued properties the contract leaves open by design (path inside the positive instance).
OPEN_BY_CONTRACT = {
    # ADD v1.3 :646: "payload": {"type": "object"}; the payload is validated against payload_schema
    ("ADD#urn:ocor:schema:canonical-ingestion-envelope:1.2", ("payload",)),
    # gateway contract :193-195: parameters "Closed generated schema selected by contract_id and digest"
    (f"{GATEWAY}#/components/schemas/ContractCall", ("parameters",)),
    (f"{GATEWAY}#/components/schemas/ExplainRequest", ("explanation_contract", "parameters")),
    (f"{GATEWAY}#/components/schemas/GetObjectRequest", ("view_contract", "parameters")),
    (f"{GATEWAY}#/components/schemas/ObjectSetRequest", ("object_set_contract", "parameters")),
    (f"{GATEWAY}#/components/schemas/SearchRequest", ("search_contract", "parameters")),
    (f"{GATEWAY}#/components/schemas/TraverseRequest", ("traversal_contract", "parameters")),
    # gateway contract :343-345: values "Closed object schema generated from Canonical IR"
    (f"{GATEWAY}#/components/schemas/ObjectSnapshot", ("values",)),
    (f"{GATEWAY}#/components/schemas/GetObjectResponse", ("object", "values")),
    (f"{GATEWAY}#/components/schemas/SearchHit", ("object", "values")),
    # memory contract :198 parameters {type: object} and :295 truncation_record {type: object}
    (f"{MEMORY}#/components/schemas/MemorySearchRequest", ("parameters",)),
    (f"{MEMORY}#/components/schemas/MemoryContextAssemblyRequest", ("search_request", "parameters")),
    (f"{MEMORY}#/components/schemas/MemoryContextAssembly", ("truncation_record",)),
}

PATTERN_EXAMPLES = {
    r"^urn:sha256:[0-9a-f]{64}$": "urn:sha256:" + "a" * 64,
    r"^sha256:[0-9a-f]{64}$": "sha256:" + "b" * 64,
    r"^urn:ocor:[A-Za-z0-9._~:/-]+$": "urn:ocor:example:one",
    r"^urn:ocor:[A-Za-z0-9._~:/-]{1,240}$": "urn:ocor:example:two",
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$": "1.0.0",
    r"^(ELM|CAP|FR)-[0-9]{3}$": "ELM-070",
    r"^urn:ocor:crypto-profile:[A-Za-z0-9._-]+:[0-9]+$": "urn:ocor:crypto-profile:ed25519:1",
    r"^PT[0-9]+(\.[0-9]+)?S$": "PT30S",
    r"^PT[0-9]+(\.[0-9]+)?[SMH]$": "PT5M",
    r"^/(?:[^~/]|~[01])+(?:/(?:[^~/]|~[01])+)*$": "/payload/value",
    r"^P[0-9]+D$": "P7D",
}
FORMAT_EXAMPLES = {
    "date-time": "2026-09-01T19:00:00Z",
    "uuid": "00000000-0000-4000-8000-000000000001",
    "uri": "https://example.invalid/ocor",
}
WRONG_KINDS: tuple[Any, ...] = (None, True, 7, 1.5, "x", [], {})


# --- JSON surfaces: loading ------------------------------------------------------------------


@cache
def _contract_resources() -> tuple[tuple[str, Resource], ...]:
    resources = []
    for path in sorted(CONTRACTS.glob("*.schema.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        resources.append((path.resolve().as_uri(), Resource.from_contents(document, default_specification=DRAFT202012)))
    return tuple(resources)


@cache
def _add_schemas() -> tuple[dict[str, Any], ...]:
    lines = ADD.read_text(encoding="utf-8").split("\n")
    schemas = []
    index = 0
    while index < len(lines):
        if lines[index].strip() == "~~~json":
            end = index + 1
            while not lines[end].strip().startswith("~~~"):
                end += 1
            body = "\n".join(lines[index + 1 : end])
            if '"$schema"' in body:
                schemas.append(json.loads(body))
            index = end
        index += 1
    return tuple(schemas)


class Surface:
    """One JSON surface: its validator, its document (for local references) and its node."""

    def __init__(self, surface_id: str, document: dict[str, Any], node: dict[str, Any], uri: str, ref: str) -> None:
        self.surface_id = surface_id
        self.uri = uri
        self.document = document
        self.node = node
        self.registry: Registry = Registry().with_resources([*_contract_resources(), (uri, Resource.from_contents(document, default_specification=DRAFT202012))])
        self.validator = Draft202012Validator({"$ref": ref}, registry=self.registry, format_checker=FormatChecker())

    def errors(self, instance: Any) -> list[str]:
        return [error.message for error in self.validator.iter_errors(instance)]

    def sub(self, node: Any, base: str | None = None) -> Draft202012Validator:
        resolver = self.registry.resolver(base_uri=base or self.uri)
        return Draft202012Validator(node, registry=self.registry, format_checker=FormatChecker(), _resolver=resolver)


@cache
def _json_surfaces() -> dict[str, Surface]:
    surfaces: dict[str, Surface] = {}
    for name in (GATEWAY, MEMORY):
        document = yaml.safe_load((CONTRACTS / name).read_text(encoding="utf-8"))
        uri = (CONTRACTS / name).resolve().as_uri()
        for component, node in document["components"]["schemas"].items():
            surface_id = f"{name}#/components/schemas/{component}"
            surfaces[surface_id] = Surface(surface_id, document, node, uri, f"{uri}#/components/schemas/{component}")
    for schema in _add_schemas():
        surface_id = f"ADD#{schema['$id']}"
        surfaces[surface_id] = Surface(surface_id, schema, schema, schema["$id"], schema["$id"])
    return surfaces


# --- JSON surfaces: deterministic positive instance -----------------------------------------


class _Synthesiser:
    def __init__(self, surface: Surface) -> None:
        self.surface = surface

    def resolve(self, node: Any, document: dict[str, Any], base: str) -> tuple[Any, dict[str, Any], str]:
        while isinstance(node, dict) and "$ref" in node and set(node) <= {"$ref", "description"}:
            reference = node["$ref"]
            if reference.startswith("#"):
                target: Any = document
                for part in reference[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
                node = target
            else:
                node = self.surface.registry.resolver(base_uri=base).lookup(reference).contents
                base = urljoin(base, reference.split("#", 1)[0])
                document = self.surface.registry.contents(base)
        return node, document, base

    def value(self, node: Any, document: dict[str, Any], base: str) -> Any:
        node, document, base = self.resolve(node, document, base)
        if "const" in node:
            return copy.deepcopy(node["const"])
        if "enum" in node:
            return copy.deepcopy(node["enum"][0])
        if "oneOf" in node and "type" not in node:
            return self.value(node["oneOf"][0], document, base)
        kind = node.get("type")
        if isinstance(kind, list):
            kind = next(item for item in kind if item != "null")
        if kind is None and ("properties" in node or "allOf" in node):
            kind = "object"
        if kind == "string":
            if "pattern" in node:
                return PATTERN_EXAMPLES[node["pattern"]]
            if "format" in node:
                return FORMAT_EXAMPLES[node["format"]]
            if node.get("contentEncoding") == "base64":
                return "eA=="
            return "x" * max(1, node.get("minLength", 1))
        if kind == "integer":
            return max(1, node.get("minimum", 0)) if node.get("maximum", 1) >= 1 else node.get("minimum", 0)
        if kind == "number":
            return node.get("minimum", 0)
        if kind == "boolean":
            return False
        if kind == "array":
            count = max(node.get("minItems", 0), 1 if "contains" in node else 0)
            items: list[Any] = []
            for position in range(count):
                item = self.value(node["contains"] if "contains" in node and position == 0 else node.get("items", {"type": "string"}), document, base)
                if isinstance(item, str) and node.get("uniqueItems") and item in items:
                    item = f"{item}{position}"
                items.append(item)
            return items
        if kind == "object":
            return self.record(node, document, base)
        raise AssertionError(f"{self.surface.surface_id}: cannot synthesise {node}")

    def record(self, node: dict[str, Any], document: dict[str, Any], base: str) -> dict[str, Any]:
        record: dict[str, Any] = {}
        parts = [node, *(self.resolve(part, document, base)[0] for part in node.get("allOf", []) if "if" not in part)]
        for part in parts:
            properties = part.get("properties", {})
            for name in part.get("required", []):
                record.setdefault(name, self.value(properties.get(name, {}), document, base))
        for _ in range(8):
            changed = False
            for part in node.get("allOf", []):
                if "if" not in part or not self.surface.sub(part["if"], base).is_valid(record):
                    continue
                then = part["then"]
                for name in then.get("required", []):
                    if name not in record:
                        source = then.get("properties", {}).get(name) or node.get("properties", {}).get(name, {})
                        record[name] = self.value(source, document, base)
                        changed = True
                for name, condition in then.get("properties", {}).items():
                    if name in record and not self.surface.sub(condition, base).is_valid(record[name]):
                        if "contains" in condition and isinstance(record[name], list):
                            record[name] = [*record[name], self.value(condition["contains"], document, base)]
                        else:
                            record[name] = self.value(condition, document, base)
                        changed = True
            if not changed:
                break
        return record


@cache
def _positive(surface_id: str) -> Any:
    surface = _json_surfaces()[surface_id]
    return _Synthesiser(surface).value(surface.node, surface.document, surface.uri)


def _objects(value: Any, path: tuple[Any, ...] = ()) -> Iterator[tuple[tuple[Any, ...], dict[str, Any]]]:
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _objects(child, (*path, key))
    elif isinstance(value, list):
        for position, child in enumerate(value):
            yield from _objects(child, (*path, position))


def _at(instance: Any, path: tuple[Any, ...]) -> Any:
    for part in path:
        instance = instance[part]
    return instance


JSON_IDS = sorted(surface for surface in COVERED_SURFACE if not surface.startswith(PROTO))
RECORD_IDS = [surface for surface in JSON_IDS if surface not in NOT_A_RECORD]


# --- JSON surfaces: tests -------------------------------------------------------------------


def test_covered_surface_is_the_whole_contract_surface():
    proto_messages = {f"{PROTO}#{name}" for name in re.findall(r"^message\s+(\w+)\s*\{", (CONTRACTS / PROTO).read_text(encoding="utf-8"), re.MULTILINE)}
    assert set(_json_surfaces()) | proto_messages == COVERED_SURFACE
    assert len(COVERED_SURFACE) == 25 + 16 + 19 + 5


@pytest.mark.parametrize("surface_id", JSON_IDS)
def test_positive_instance_is_synthesised_from_the_manifested_schema(surface_id: str):
    assert _json_surfaces()[surface_id].errors(_positive(surface_id)) == []


@pytest.mark.parametrize("surface_id", RECORD_IDS)
def test_closed_record_rejects_an_undeclared_property_at_every_nesting_level(surface_id: str):
    surface = _json_surfaces()[surface_id]
    positive = _positive(surface_id)
    assert isinstance(positive, dict)
    checked = 0
    for path, _ in list(_objects(positive)):
        if (surface_id, path) in OPEN_BY_CONTRACT:
            continue
        negative = copy.deepcopy(positive)
        _at(negative, path)["ocor_undeclared_property"] = "x"
        assert surface.errors(negative), f"{surface_id}: the record at {list(path)} accepts an undeclared property"
        checked += 1
    assert checked >= 1


@pytest.mark.parametrize("surface_id", NOT_A_RECORD)
def test_closed_record_exceptions_are_what_the_contract_declares(surface_id: str):
    surface = _json_surfaces()[surface_id]
    if surface.node.get("type") == "string":
        assert surface.errors(_positive(surface_id) + "0")
        return
    document = surface.document
    composers = [
        name
        for name, node in document["components"]["schemas"].items()
        if any(part.get("$ref") == "#/components/schemas/GovernedEnvelope" for part in node.get("allOf", []))
    ]
    assert composers
    for name in composers:
        assert document["components"]["schemas"][name].get("unevaluatedProperties") is False, name


@pytest.mark.parametrize("surface_id", RECORD_IDS)
def test_exact_field_set_every_required_field_is_needed_and_declared(surface_id: str):
    surface = _json_surfaces()[surface_id]
    positive = _positive(surface_id)
    for path, record in list(_objects(positive)):
        if (surface_id, path) in OPEN_BY_CONTRACT or any((surface_id, path[: index]) in OPEN_BY_CONTRACT for index in range(len(path))):
            continue
        for name in list(record):
            negative = copy.deepcopy(positive)
            del _at(negative, path)[name]
            if not surface.errors(negative):
                # optional property: its presence in the minimal instance comes from a conditional branch
                continue
            renamed = copy.deepcopy(positive)
            target = _at(renamed, path)
            target[name.upper() + "_RENAMED"] = target.pop(name)
            assert surface.errors(renamed), f"{surface_id}: {list(path) + [name]} renamed is accepted"


@pytest.mark.parametrize("surface_id", JSON_IDS)
def test_canonical_bytes_are_rfc8785_and_independent_of_member_order(surface_id: str):
    positive = _positive(surface_id)
    reordered = json.loads(json.dumps(positive, sort_keys=True), object_pairs_hook=lambda pairs: dict(reversed(pairs)))
    assert canonical_bytes(reordered) == canonical_bytes(positive)
    assert canonical_bytes(json.loads(canonical_bytes(positive))) == canonical_bytes(positive)
    assert canonical_bytes(positive).decode("utf-8") == json.dumps(positive, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@pytest.mark.parametrize("surface_id", JSON_IDS)
def test_digest_is_urn_sha256_of_the_canonical_bytes_and_binds_every_field(surface_id: str):
    positive = _positive(surface_id)
    digest = canonical_digest(positive)
    assert digest == "urn:sha256:" + hashlib.sha256(canonical_bytes(positive)).hexdigest()
    for path, record in list(_objects(positive)):
        for name in record:
            changed = copy.deepcopy(positive)
            _at(changed, path)[name] = [_at(changed, path)[name]]
            assert canonical_digest(changed) != digest, f"{surface_id}: {list(path) + [name]} is not bound by the digest"


def _wrong_values(surface: Surface, node: Any, value: Any, base: str) -> list[Any]:
    validator = surface.sub(node, base)
    wrong = [candidate for candidate in WRONG_KINDS if not validator.is_valid(candidate) and type(candidate) is not type(value)]
    if isinstance(value, str):
        wrong += [candidate for candidate in ("", value + "é", "\ud800") if not validator.is_valid(candidate)]
    return wrong


@pytest.mark.parametrize("surface_id", JSON_IDS)
def test_negative_corpus_rejects_every_wrong_value_missing_field_and_extra_field(surface_id: str):
    surface = _json_surfaces()[surface_id]
    positive = _positive(surface_id)
    corpus: list[tuple[str, Any]] = []
    if isinstance(positive, dict):
        node, document, base = _Synthesiser(surface).resolve(surface.node, surface.document, surface.uri)
        properties: dict[str, Any] = {}
        for part in [node, *(_Synthesiser(surface).resolve(part, document, base)[0] for part in node.get("allOf", []) if "if" not in part)]:
            properties.update(part.get("properties", {}))
        for name, value in positive.items():
            for wrong in _wrong_values(surface, properties.get(name, {}), value, base):
                negative = copy.deepcopy(positive)
                negative[name] = wrong
                corpus.append((f"{name}={wrong!r}", negative))
            missing = copy.deepcopy(positive)
            del missing[name]
            if surface.errors(missing):
                corpus.append((f"missing {name}", missing))
        if surface_id in RECORD_IDS:
            corpus.append(("extra field", {**positive, "ocor_undeclared_property": 1}))
    else:
        corpus += [(f"value={wrong!r}", wrong) for wrong in _wrong_values(surface, surface.node, positive, surface.uri)]
    assert corpus, f"{surface_id}: empty negative corpus"
    accepted = [label for label, negative in corpus if not surface.errors(negative)]
    assert accepted == [], f"{surface_id}: accepted {accepted}"


# --- registry Proto3 messages ---------------------------------------------------------------


@cache
def _proto_pool() -> descriptor_pool.DescriptorPool:
    include = Path(grpc_tools.__file__).resolve().parent / "_proto"
    with tempfile.TemporaryDirectory(prefix="ocor-meta-proto-") as directory:
        output = Path(directory) / "registry.pb"
        result = subprocess.run(
            [sys.executable, "-m", "grpc_tools.protoc", f"-I{CONTRACTS}", f"-I{include}", f"--descriptor_set_out={output}", "--include_imports", str(CONTRACTS / PROTO)],
            capture_output=True,
            check=False,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="strict")
        file_set = descriptor_pb2.FileDescriptorSet.FromString(output.read_bytes())
    pool = descriptor_pool.DescriptorPool()
    for file in file_set.file:
        pool.Add(file)
    return pool


def _proto_descriptor(name: str) -> Descriptor:
    return _proto_pool().FindMessageTypeByName(f"ocor.registry.v1.{name}")


def _declared_fields(name: str) -> list[str]:
    text = (CONTRACTS / PROTO).read_text(encoding="utf-8")
    body = re.search(r"^message\s+" + name + r"\s*\{(.*?)^\}", text, re.MULTILINE | re.DOTALL)
    assert body is not None
    return re.findall(r"^\s+(?:optional\s+|repeated\s+)?[\w.<>, ]+\s+(\w+)\s*=\s*\d+\s*;", body.group(1), re.MULTILINE)


def _proto_json(descriptor: Descriptor, depth: int = 0) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for field in descriptor.fields:
        if field.containing_oneof is not None and field.containing_oneof.fields[0] is not field:
            continue
        item: Any
        if field.type == FieldDescriptor.TYPE_MESSAGE:
            full_name = field.message_type.full_name
            if full_name == "google.protobuf.Timestamp":
                item = "2026-09-01T19:00:00Z"
            elif full_name == "google.protobuf.Duration":
                item = "30s"
            elif full_name == "google.protobuf.Any":
                item = {"@type": "type.googleapis.com/ocor.registry.v1.VersionPin", "resourceId": "urn:ocor:example:any"}
            elif field.message_type.GetOptions().map_entry:
                item = {"key": "value"}
            else:
                item = _proto_json(field.message_type, depth + 1) if depth < 4 else {}
        elif field.type == FieldDescriptor.TYPE_ENUM:
            item = field.enum_type.values[-1].name
        elif field.type == FieldDescriptor.TYPE_BOOL:
            item = True
        elif field.type in (FieldDescriptor.TYPE_STRING,):
            item = f"urn:ocor:example:{field.name}"
        elif field.type == FieldDescriptor.TYPE_BYTES:
            item = "eA=="
        elif field.type in (FieldDescriptor.TYPE_DOUBLE, FieldDescriptor.TYPE_FLOAT):
            item = 0.5
        else:
            item = 3
        is_repeated = field.is_repeated and not (field.type == FieldDescriptor.TYPE_MESSAGE and field.message_type.GetOptions().map_entry)
        value[field.json_name] = [item] if is_repeated else item
    return value


PROTO_IDS = sorted(surface.split("#", 1)[1] for surface in COVERED_SURFACE if surface.startswith(PROTO))


def _proto_message(name: str) -> Any:
    cls = message_factory.GetMessageClass(_proto_descriptor(name))
    return json_format.ParseDict(_proto_json(_proto_descriptor(name)), cls(), descriptor_pool=_proto_pool())


@pytest.mark.parametrize("name", PROTO_IDS)
def test_proto_exact_field_set_matches_the_contract_text(name: str):
    descriptor = _proto_descriptor(name)
    assert [field.name for field in descriptor.fields] == _declared_fields(name)
    message = _proto_message(name)
    rendered = json_format.MessageToDict(message, preserving_proto_field_name=True, descriptor_pool=_proto_pool())
    expected = {field.name for field in descriptor.fields if field.containing_oneof is None or field.containing_oneof.fields[0] is field}
    assert set(rendered) == expected


@pytest.mark.parametrize("name", PROTO_IDS)
def test_proto_closed_record_rejects_an_unknown_field(name: str):
    cls = message_factory.GetMessageClass(_proto_descriptor(name))
    payload = {**_proto_json(_proto_descriptor(name)), "ocorUndeclaredField": "x"}
    with pytest.raises(json_format.ParseError, match="ocorUndeclaredField"):
        json_format.ParseDict(payload, cls(), descriptor_pool=_proto_pool())


@pytest.mark.parametrize("name", PROTO_IDS)
def test_proto_canonical_bytes_are_deterministic_and_round_trip(name: str):
    message = _proto_message(name)
    encoded = message.SerializeToString(deterministic=True)
    decoded = type(message).FromString(encoded)
    assert decoded.SerializeToString(deterministic=True) == encoded
    assert decoded == message


@pytest.mark.parametrize("name", PROTO_IDS)
def test_proto_digest_binds_every_field(name: str):
    descriptor = _proto_descriptor(name)
    message = _proto_message(name)
    digest = hashlib.sha256(message.SerializeToString(deterministic=True)).hexdigest()
    for field in descriptor.fields:
        changed = type(message)()
        changed.CopyFrom(message)
        changed.ClearField(field.name)
        if changed == message:
            continue
        assert hashlib.sha256(changed.SerializeToString(deterministic=True)).hexdigest() != digest, f"{name}.{field.name}"


@pytest.mark.parametrize("name", PROTO_IDS)
def test_proto_negative_corpus_rejects_wrongly_typed_fields(name: str):
    descriptor = _proto_descriptor(name)
    cls = message_factory.GetMessageClass(descriptor)
    corpus: list[tuple[str, dict[str, Any]]] = []
    base = _proto_json(descriptor)
    for field in descriptor.fields:
        if field.json_name not in base:
            continue
        repeated = field.is_repeated
        if field.type == FieldDescriptor.TYPE_ENUM:
            wrong: Any = "OCOR_NOT_A_MEMBER"
        elif field.type == FieldDescriptor.TYPE_STRING:
            wrong = {"not": "a string"}
        elif field.type == FieldDescriptor.TYPE_MESSAGE:
            wrong = "not a message"
        elif field.type == FieldDescriptor.TYPE_BOOL:
            wrong = "not a bool"
        else:
            wrong = "not a number"
        corpus.append((field.name, {**base, field.json_name: [wrong] if repeated and not (field.type == FieldDescriptor.TYPE_MESSAGE and field.message_type.GetOptions().map_entry) else wrong}))
    assert corpus
    accepted = []
    for label, payload in corpus:
        try:
            json_format.ParseDict(payload, cls(), descriptor_pool=_proto_pool())
        except json_format.ParseError:
            continue
        accepted.append(label)
    assert accepted == [], f"{name}: accepted wrongly typed {accepted}"
