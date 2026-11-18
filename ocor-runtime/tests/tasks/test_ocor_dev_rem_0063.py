"""OCOR-DEV-REM-0063: MCP profile for protocol revision 2026-07-28.

FABLE52-POST-POC-PROGRAMME (2026-11-11) point 1. The decision names FR-047
(Requirement Register v1.1 line 143), FR-169 (line 417) and NFR-022 (line 153).
This module does not claim those requirements verified. ADD v1.3 line 382: an MCP
call carries ``governed_context_ref`` of transport origin, the input schema cannot
overwrite it, and a call without it is ``CAPABILITY_DENIED``. The Tool Contract
schema of ADD v1.3 section 3.5 is unchanged.

Required backend: none. The official Tool schema is a pinned test fixture.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import inspect
import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any

import pytest

from ocor_runtime.c1.ports import C1Error, DiagnosticCode

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "ocor-runtime/tests/fixtures/mcp/2026-07-28"
PROFILE = ROOT / "docs/development_plan/OCOR_MCP_2026-07-28_PROFILE.md"
SCHEMA_SHA256 = "edbb197ed0f92e90d658866e23cf76f107df0caac5ce25c2b9e64e1ca9a6314a"
CHANGELOG_SHA256 = "b327e576f4c96b34e92f338f8ffefc35e13d0e953ab76bdb3aab342d104c8e53"
LICENSE_SHA256 = "0382b0057770ca05e9c350a50aa3b1c1fea84da0bc81d723bf00b9aa841be58a"
REVISION = "2026-07-28"
DRAFT_2020 = "https://json-schema.org/draft/2020-12/schema"
CONTEXT_REF = "urn:sha256:" + "ab" * 32


def _fleet() -> ModuleType:
    path = Path(__file__).with_name("test_ocor_dev_rem_0047.py")
    spec = importlib.util.spec_from_file_location("rem0047_fleet_for_rem0063", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the fleet compiler fixture from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _descriptor(documents: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], bytes]:
    fleet = _fleet()
    request = fleet.oac_request(documents=documents) if documents is not None else fleet.oac_request()
    release = fleet.compiler().build(request)
    files = fleet.c1("codegen").IrArtifactGenerator().render(release)
    raw = files["urn:ocor:package:fleet:mcp-descriptor"]
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise AssertionError("generated MCP descriptor is not an object")
    return document, raw


def _contract(
    contract_id: str,
    *,
    input_schema: Mapping[str, Any] | None = None,
    output_schema: Mapping[str, Any] | None = None,
    kind: str = "MCP_TOOL",
) -> dict[str, Any]:
    return {
        "construct": "ContractDefinition",
        "contract_id": contract_id,
        "kind": kind,
        "input_schema": dict(input_schema or {"type": "object", "properties": {"name": {"type": "string"}}}),
        "output_schema": dict(output_schema or {"type": "object"}),
        "error_model": ["CAPABILITY_DENIED"],
        "effect_class": "READ_ONLY",
        "risk_class": "R1",
        "policy_refs": [],
        "approval_refs": [],
        "version": "1.0.0",
    }


def _with_contracts(*contracts: Mapping[str, Any]) -> dict[str, Any]:
    fleet = _fleet()
    documents = copy.deepcopy(fleet.oac_documents())
    documents["module.yaml"]["definitions"].extend(contracts)
    return documents


def _official_schema() -> dict[str, Any]:
    schema = json.loads((FIXTURE / "schema.json").read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise AssertionError("official MCP schema fixture is not an object")
    return schema


def _validate(document: Mapping[str, Any], *, expected_revision: str = REVISION) -> None:
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    profile.validate_mcp_descriptor(document, _official_schema(), expected_revision=expected_revision)


def _reason(excinfo: pytest.ExceptionInfo[BaseException]) -> str:
    return str(getattr(excinfo.value, "reason_code", ""))


def test_fixture_is_the_pinned_2026_07_28_schema() -> None:
    """External dependency policy: exact version, source, licence and sha256."""
    schema_bytes = (FIXTURE / "schema.json").read_bytes()
    changelog = (FIXTURE / "changelog.mdx").read_bytes()
    licence = (FIXTURE / "LICENSE").read_bytes()
    assert hashlib.sha256(schema_bytes).hexdigest() == SCHEMA_SHA256
    assert hashlib.sha256(changelog).hexdigest() == CHANGELOG_SHA256
    assert hashlib.sha256(licence).hexdigest() == LICENSE_SHA256
    record = (FIXTURE / "DEPENDENCY.md").read_text(encoding="utf-8")
    assert REVISION in record
    assert "Apache-2.0" in record
    assert SCHEMA_SHA256 in record
    assert CHANGELOG_SHA256 in record
    assert "https://modelcontextprotocol.io/specification/2026-07-28/changelog" in record


def test_revision_constant_lives_only_in_the_c1_generator() -> None:
    """One constant, in the C1 generator. The descriptor reports it under x-ocor-."""
    codegen = importlib.import_module("ocor_runtime.c1.codegen")
    assert codegen.MCP_PROTOCOL_REVISION == REVISION
    source_root = ROOT / "ocor-runtime/src/ocor_runtime"
    generator = (source_root / "c1/codegen.py").read_text(encoding="utf-8")
    assert generator.count(f'MCP_PROTOCOL_REVISION = "{REVISION}"') == 1
    for path in sorted(source_root.rglob("*.py")):
        if path.name == "codegen.py":
            continue
        assert "MCP_PROTOCOL_REVISION" not in path.read_text(encoding="utf-8")
    document, first = _descriptor()
    _, second = _descriptor()
    assert first == second
    assert document["x-ocor-mcp-protocol-revision"] == REVISION
    assert set(document["x-ocor-release"]) == {
        "ontologyRelease",
        "irDigest",
        "compilerVersion",
        "mappingVersion",
    }


def test_generated_tools_match_the_official_tool_schema_and_resolve_refs() -> None:
    """(a) every generated tool is a Tool of revision 2026-07-28; $ref resolve in-document."""
    document, _ = _descriptor(_with_contracts(_contract("urn:ocor:contract:arrive-vessel")))
    _validate(document)
    names = [tool["name"] for tool in document["tools"]]
    assert names == ["arrive-vessel", "get-vessel"]
    assert names == sorted(names)
    get_vessel = next(tool for tool in document["tools"] if tool["name"] == "get-vessel")
    assert get_vessel["inputSchema"]["type"] == "object"
    assert get_vessel["outputSchema"]["properties"]["vessel"]["$ref"] == "#/$defs/urn.ocor.type.vessel"
    assert "$defs" not in document
    assert "urn.ocor.type.vessel" in get_vessel["outputSchema"]["$defs"]
    assert get_vessel["annotations"]["riskClass"] == "R0"
    assert "governed_context_ref" not in get_vessel["inputSchema"].get("properties", {})


def test_tool_order_is_the_emitted_name_and_a_reversed_list_fails() -> None:
    """(b) tools/list order is deterministic by emitted name, not by source order."""
    document, _ = _descriptor(_with_contracts(_contract("urn:ocor:contract:arrive-vessel")))
    assert [tool["name"] for tool in document["tools"]] == ["arrive-vessel", "get-vessel"]
    reversed_tools = dict(document)
    reversed_tools["tools"] = list(reversed(document["tools"]))
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    with pytest.raises(profile.McpProfileError):
        _validate(reversed_tools)


def test_a_descriptor_with_another_revision_fails() -> None:
    """(d) a descriptor that declares a different revision fails the check."""
    document, _ = _descriptor()
    other = dict(document)
    other["x-ocor-mcp-protocol-revision"] = "2025-11-25"
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    with pytest.raises(profile.McpProfileError):
        _validate(other)
    missing = dict(document)
    missing.pop("x-ocor-mcp-protocol-revision")
    with pytest.raises(profile.McpProfileError):
        _validate(missing)


def test_input_schema_cannot_overwrite_governed_context_ref() -> None:
    """ADD v1.3 line 382: the projected input schema drops a top-level overwrite.

    MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15): the generated descriptor carries a
    cross-tree ``$ref`` and is now rejected, so the profile check runs on a
    bare self-contained descriptor that plants the transport field.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    documents = _with_contracts(
        _contract(
            "urn:ocor:contract:context-overwrite",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "governed_context_ref": {"type": "string"},
                },
                "required": ["name", "governed_context_ref"],
            },
        )
    )
    document, _ = _descriptor(documents)
    tool = next(item for item in document["tools"] if item["name"] == "context-overwrite")
    assert "governed_context_ref" not in tool["inputSchema"].get("properties", {})
    assert tool["inputSchema"].get("required") == ["name"]
    planted = _bare_descriptor()
    planted_body = planted["tools"][0]["inputSchema"]
    planted_body["properties"] = {
        "name": {"type": "string"},
        "governed_context_ref": {"type": "string"},
    }
    planted_body["required"] = ["name", "governed_context_ref"]
    with pytest.raises(profile.McpProfileError, match="cannot overwrite"):
        _validate(planted)
    clean = copy.deepcopy(planted)
    del clean["tools"][0]["inputSchema"]["properties"]["governed_context_ref"]
    clean["tools"][0]["inputSchema"]["required"] = ["name"]
    _validate(clean)


@pytest.mark.parametrize("properties", ["nope", ["name"], True])
def test_projection_rejects_properties_that_are_not_an_object(properties: object) -> None:
    """The generator projection checks the properties type before it removes the transport field."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = {"type": "object", "properties": properties}
    with pytest.raises(profile.McpProfileError):
        profile.without_context_overwrite(schema)


@pytest.mark.parametrize("required", ["name", True, b"name"])
def test_projection_rejects_required_that_is_not_a_list(required: object) -> None:
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": required}
    with pytest.raises(profile.McpProfileError):
        profile.without_context_overwrite(schema)


def test_a_reference_array_index_with_a_leading_zero_fails_closed() -> None:
    """A JSON pointer segment is not an array index when it has a leading zero."""
    document, _ = _descriptor()
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document["tools"][0]["inputSchema"]["properties"]["name"] = {"$ref": "#/tools/01"}
    with pytest.raises(profile.McpProfileError):
        _validate(document)


def test_non_object_input_schema_fails_closed() -> None:
    documents = _with_contracts(_contract("urn:ocor:contract:bare-name", input_schema={"type": "string"}))
    with pytest.raises(C1Error) as excinfo:
        _descriptor(documents)
    assert any(item.code == DiagnosticCode.TYPE_ERROR for item in excinfo.value.diagnostics)


def test_duplicate_tool_names_fail_closed() -> None:
    documents = _with_contracts(_contract("urn:ocor:alias:get-vessel"))
    with pytest.raises(C1Error) as excinfo:
        _descriptor(documents)
    assert any(item.code == DiagnosticCode.TYPE_ERROR for item in excinfo.value.diagnostics)


def test_external_dangling_and_foreign_dialect_refs_fail() -> None:
    document = _bare_descriptor()
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    external = copy.deepcopy(document)
    external["tools"][0]["inputSchema"]["properties"]["name"] = {"$ref": "https://example.invalid/schema.json"}
    dangling = copy.deepcopy(document)
    dangling["tools"][0]["inputSchema"]["properties"]["name"] = {"$ref": "#/$defs/missing"}
    foreign = copy.deepcopy(document)
    foreign["tools"][0]["inputSchema"]["$schema"] = "https://json-schema.org/draft/2019-09/schema"
    for candidate in (external, dangling, foreign):
        with pytest.raises(profile.McpProfileError):
            _validate(candidate)
    accepted = copy.deepcopy(document)
    accepted["tools"][0]["inputSchema"]["$schema"] = DRAFT_2020
    _validate(accepted)
    accepted["tools"][0]["inputSchema"]["$schema"] = DRAFT_2020 + "#"
    _validate(accepted)


def test_schema_bounds_surrogates_and_non_finite_numbers_fail_closed() -> None:
    document, _ = _descriptor()
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    deep = copy.deepcopy(document)
    node = deep["tools"][0]["inputSchema"]
    for _ in range(40):
        node["properties"] = {"child": {"type": "object"}}
        node = node["properties"]["child"]
    wide = copy.deepcopy(document)
    wide["tools"][0]["inputSchema"]["properties"] = {f"p{index}": {"type": "string"} for index in range(5000)}
    surrogate = copy.deepcopy(document)
    surrogate["tools"][0]["description"] = "bad \ud800 name"
    non_finite = copy.deepcopy(document)
    non_finite["x-probe"] = float("nan")
    for candidate in (deep, wide, surrogate, non_finite):
        with pytest.raises(profile.McpProfileError):
            _validate(candidate)


def _registry() -> Any:
    mcp_call = importlib.import_module("ocor_runtime.c8.mcp_call")
    registry = mcp_call.GovernedContextRegistry()
    record = {"tenant_id": "fleet", "nested": {"purpose": "query"}}
    registry.register(CONTEXT_REF, record)
    record["tenant_id"] = "changed-after-register"
    record["nested"]["purpose"] = "changed-after-register"
    return mcp_call, registry


def test_call_carries_its_own_context_and_needs_no_handshake() -> None:
    """(c) the first call succeeds with its own ref and no session or initialize."""
    mcp_call, registry = _registry()
    signature = inspect.signature(mcp_call.call_tool)
    assert "governed_context_ref" in signature.parameters
    assert signature.parameters["governed_context_ref"].default is None
    for forbidden in ("session_id", "handshake", "initialize", "protocol_version"):
        assert forbidden not in signature.parameters
    assert not hasattr(mcp_call, "initialize")
    result = mcp_call.call_tool(
        tool_name="get-vessel",
        arguments={"name": "Aurora"},
        governed_context_ref=CONTEXT_REF,
        registry=registry,
    )
    assert isinstance(result, Mapping)
    assert result["tool_name"] == "get-vessel"
    assert result["governed_context_ref"] == CONTEXT_REF
    assert result["origin"] == "TRANSPORT"
    assert result["governed_context"]["tenant_id"] == "fleet"
    assert result["governed_context"]["nested"]["purpose"] == "query"
    with pytest.raises(TypeError):
        result["tool_name"] = "other"  # type: ignore[index]
    with pytest.raises(TypeError):
        result["arguments"]["name"] = "other"  # type: ignore[index]


def test_c2_boundary_delegates_to_the_same_call() -> None:
    mcp_call, registry = _registry()
    boundary = importlib.import_module("ocor_runtime.c2.mcp_boundary")
    signature = inspect.signature(boundary.admit_mcp_tool_call)
    for forbidden in ("session_id", "handshake", "initialize"):
        assert forbidden not in signature.parameters
    admitted = boundary.admit_mcp_tool_call(
        tool_name="get-vessel",
        arguments={"name": "Aurora"},
        governed_context_ref=CONTEXT_REF,
        registry=registry,
    )
    direct = mcp_call.call_tool(
        tool_name="get-vessel",
        arguments={"name": "Aurora"},
        governed_context_ref=CONTEXT_REF,
        registry=registry,
    )
    assert admitted["governed_context"] == direct["governed_context"]
    assert isinstance(admitted, MappingProxyType)


@pytest.mark.parametrize(
    ("kwargs",),
    [
        ({"governed_context_ref": None},),
        ({},),
        ({"governed_context_ref": ""},),
        ({"governed_context_ref": "urn:sha256:" + "AB" * 32},),
        ({"governed_context_ref": "urn:sha256:" + "c" * 64},),
        ({"governed_context_ref": "urn:sha256:" + "a" * 63},),
        ({"governed_context_ref": "urn:sha256:" + "gg" * 32},),
        ({"governed_context_ref": "urn:sha256:\u00e9" + "ab" * 31},),
        ({"governed_context_ref": CONTEXT_REF, "arguments": {"governed_context_ref": CONTEXT_REF}},),
        ({"governed_context_ref": CONTEXT_REF, "arguments": {"nested": {"governed_context_ref": "x"}}},),
    ],
)
def test_a_call_without_a_usable_context_ref_is_capability_denied(kwargs: Mapping[str, Any]) -> None:
    mcp_call, registry = _registry()
    boundary = importlib.import_module("ocor_runtime.c2.mcp_boundary")
    payload: dict[str, Any] = {"tool_name": "get-vessel", "arguments": {"name": "Aurora"}, "registry": registry}
    payload.update(kwargs)
    for entry in (mcp_call.call_tool, boundary.admit_mcp_tool_call):
        with pytest.raises(Exception) as excinfo:
            entry(**payload)
        assert _reason(excinfo) == "CAPABILITY_DENIED"


def test_registry_rejects_a_second_registration_and_non_json_records() -> None:
    mcp_call = importlib.import_module("ocor_runtime.c8.mcp_call")
    registry = mcp_call.GovernedContextRegistry()
    registry.register(CONTEXT_REF, {"tenant_id": "fleet"})
    with pytest.raises(Exception) as excinfo:
        registry.register(CONTEXT_REF, {"tenant_id": "other"})
    assert _reason(excinfo) == "CAPABILITY_DENIED"
    for bad in ({"value": float("nan")}, {"value": "\ud800"}, {"value": b"bytes"}, ["not-an-object"]):
        fresh = mcp_call.GovernedContextRegistry()
        with pytest.raises(Exception) as excinfo:
            fresh.register(CONTEXT_REF, bad)
        assert _reason(excinfo) == "CAPABILITY_DENIED"


def _bare_descriptor() -> dict[str, Any]:
    return {
        "x-ocor-mcp-protocol-revision": REVISION,
        "tools": [
            {
                "name": "get-vessel",
                "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}},
                "outputSchema": {"type": "object"},
            }
        ],
    }


def test_a_bare_descriptor_matches_the_official_tool_definition() -> None:
    """The negative schema cases below start from a descriptor the Tool definition accepts."""
    _validate(_bare_descriptor())


@pytest.mark.parametrize(
    "schema",
    [
        None,
        [],
        "Tool",
        True,
        {"$defs": 1},
        {"$defs": None},
        {"$defs": "Tool"},
        {"$defs": {"Tool": 1}},
        {"$defs": {"Tool": None}},
        {"$defs": {"Tool": "object"}},
        {"$defs": {"Tool": {"type": "not-a-type"}}},
    ],
)
def test_a_tampered_official_schema_fails_closed(schema: object) -> None:
    """A damaged official fixture is a typed profile error, never a library exception."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    with pytest.raises(profile.McpProfileError):
        profile.validate_mcp_descriptor(_bare_descriptor(), schema, expected_revision=REVISION)


@pytest.mark.parametrize("properties", ["nope", ["name"], True, None])
def test_input_schema_properties_of_the_wrong_type_fail_closed(properties: object) -> None:
    """Point 1(a): inputSchema is a JSON Schema 2020-12 schema, not only a Tool-shaped object."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    document["tools"][0]["inputSchema"] = {"type": "object", "properties": properties}
    with pytest.raises(profile.McpProfileError):
        profile.validate_mcp_descriptor(document, _official_schema(), expected_revision=REVISION)


@pytest.mark.parametrize("properties", ["nope", ["name"], True, None])
def test_output_schema_properties_of_the_wrong_type_fail_closed(properties: object) -> None:
    """Point 1(a) applies to outputSchema as well as inputSchema."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    document["tools"][0]["outputSchema"] = {"type": "object", "properties": properties}
    with pytest.raises(profile.McpProfileError):
        profile.validate_mcp_descriptor(document, _official_schema(), expected_revision=REVISION)


@pytest.mark.parametrize("document", [None, [], "descriptor", True, 1])
def test_a_descriptor_of_the_wrong_type_fails_closed(document: object) -> None:
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    with pytest.raises(profile.McpProfileError):
        profile.validate_mcp_descriptor(document, _official_schema(), expected_revision=REVISION)


@pytest.mark.parametrize("tools", [None, {}, "tools", True, 1])
def test_tools_of_the_wrong_type_fail_closed(tools: object) -> None:
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    document["tools"] = tools
    with pytest.raises(profile.McpProfileError):
        profile.validate_mcp_descriptor(document, _official_schema(), expected_revision=REVISION)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"arguments": None},
        {"arguments": []},
        {"arguments": True},
        {"arguments": "x"},
        {"arguments": b"x"},
        {"arguments": {1: "a"}},
        {"arguments": {"n": float("nan")}},
        {"arguments": {"n": float("inf")}},
        {"arguments": {"n": float("-inf")}},
        {"arguments": {"nested": [{"n": float("nan")}]}},
        {"arguments": {"note": "\ud800"}},
        {"tool_name": None},
        {"tool_name": ""},
        {"tool_name": 1},
        {"tool_name": True},
        {"registry": None},
        {"registry": {}},
        {"registry": object()},
    ],
)
def test_a_malformed_call_is_capability_denied(kwargs: Mapping[str, Any]) -> None:
    """Wrong types, non-finite numbers and a missing registry stay on the typed refusal."""
    mcp_call, registry = _registry()
    boundary = importlib.import_module("ocor_runtime.c2.mcp_boundary")
    payload: dict[str, Any] = {
        "tool_name": "get-vessel",
        "arguments": {"name": "Aurora"},
        "governed_context_ref": CONTEXT_REF,
        "registry": registry,
    }
    payload.update(kwargs)
    for entry in (mcp_call.call_tool, boundary.admit_mcp_tool_call):
        with pytest.raises(mcp_call.McpCallError) as excinfo:
            entry(**payload)
        assert _reason(excinfo) == "CAPABILITY_DENIED"


def _choices_descriptor() -> dict[str, Any]:
    """A tool schema whose anyOf list has indexes 0 through 10."""
    document = _bare_descriptor()
    document["tools"][0]["inputSchema"]["$defs"] = {
        "choices": {"anyOf": [{"type": "string", "const": str(index)} for index in range(11)]}
    }
    return document


@pytest.mark.parametrize("index", ["0", "1", "2", "9", "10"])
def test_json_pointer_resolves_a_single_digit_array_index(index: str) -> None:
    """VF-001: ASCII indexes 0-9 and a two-digit index resolve when the target exists."""
    document = _choices_descriptor()
    document["tools"][0]["inputSchema"]["properties"]["name"] = {
        "$ref": f"#/$defs/choices/anyOf/{index}"
    }
    _validate(document)


@pytest.mark.parametrize("index", ["00", "01", "-1", "11", "\u0661"])
def test_json_pointer_rejects_a_non_canonical_array_index(index: str) -> None:
    """VF-001: leading zeros, a missing index, a sign and a non-ASCII digit stay closed."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _choices_descriptor()
    document["tools"][0]["inputSchema"]["properties"]["name"] = {
        "$ref": f"#/$defs/choices/anyOf/{index}"
    }
    with pytest.raises(profile.McpProfileError):
        _validate(document)


def test_property_names_and_instance_data_are_not_schema_keywords() -> None:
    """VF-002: names and instance data may contain keyword spellings without being keywords."""
    document = _bare_descriptor()
    document["tools"][0]["inputSchema"] = {
        "type": "object",
        "properties": {
            "$ref": {"type": "string"},
            "$schema": {"type": "string"},
            "$dynamicRef": {"type": "string"},
            "$recursiveRef": {"type": "string"},
        },
        "default": {
            "$ref": "https://example.invalid/not-a-keyword",
            "$schema": {"type": "string"},
            "$dynamicRef": "#ignored",
        },
        "const": {"$recursiveRef": "#ignored", "$schema": {}},
        "enum": [{"$ref": "https://example.invalid/also-data"}, {"$schema": []}],
    }
    _validate(document)


@pytest.mark.parametrize("dialect", [[], {}, 1, True, None])
def test_a_malformed_schema_dialect_is_a_profile_error(dialect: object) -> None:
    """VF-002: a dialect that is not the 2020-12 string is a typed refusal, never TypeError."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    document["tools"][0]["inputSchema"]["$schema"] = dialect
    with pytest.raises(profile.McpProfileError):
        _validate(document)


@pytest.mark.parametrize("keyword", ["$dynamicRef", "$recursiveRef"])
def test_a_dynamic_reference_keyword_is_rejected(keyword: str) -> None:
    """VF-002: a real dynamic-reference keyword is still a profile error."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    document["tools"][0]["inputSchema"]["properties"]["name"] = {keyword: "#/$defs/missing"}
    with pytest.raises(profile.McpProfileError):
        _validate(document)


def _nested(depth: int, leaf: object) -> object:
    node = leaf
    for _ in range(depth):
        node = {"x": node}
    return node


def test_deep_decoded_arguments_return_or_refuse_with_capability_denied() -> None:
    """VF-003: depth 1 and 300 return; depth 600 returns or refuses; no generic exception."""
    mcp_call, registry = _registry()
    boundary = importlib.import_module("ocor_runtime.c2.mcp_boundary")
    for depth in (1, 300):
        arguments = _nested(depth, 0)
        for entry in (mcp_call.call_tool, boundary.admit_mcp_tool_call):
            result = entry(
                tool_name="get-vessel",
                arguments=arguments,
                governed_context_ref=CONTEXT_REF,
                registry=registry,
            )
            assert result["tool_name"] == "get-vessel"
            assert result["governed_context_ref"] == CONTEXT_REF
    deep = json.loads('{"x":' * 600 + "0" + "}" * 600)
    for entry in (mcp_call.call_tool, boundary.admit_mcp_tool_call):
        try:
            result = entry(
                tool_name="get-vessel",
                arguments=deep,
                governed_context_ref=CONTEXT_REF,
                registry=registry,
            )
        except mcp_call.McpCallError as exc:
            assert exc.reason_code == "CAPABILITY_DENIED"
        else:
            assert result["tool_name"] == "get-vessel"
    buried = _nested(300, {"governed_context_ref": "x"})
    for entry in (mcp_call.call_tool, boundary.admit_mcp_tool_call):
        with pytest.raises(mcp_call.McpCallError) as excinfo:
            entry(
                tool_name="get-vessel",
                arguments=buried,
                governed_context_ref=CONTEXT_REF,
                registry=registry,
            )
        assert _reason(excinfo) == "CAPABILITY_DENIED"
    over = _nested(4097, 0)
    for entry in (mcp_call.call_tool, boundary.admit_mcp_tool_call):
        with pytest.raises(mcp_call.McpCallError) as excinfo:
            entry(
                tool_name="get-vessel",
                arguments=over,
                governed_context_ref=CONTEXT_REF,
                registry=registry,
            )
        assert _reason(excinfo) == "CAPABILITY_DENIED"
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic
    for entry in (mcp_call.call_tool, boundary.admit_mcp_tool_call):
        with pytest.raises(mcp_call.McpCallError) as excinfo:
            entry(
                tool_name="get-vessel",
                arguments=cyclic,
                governed_context_ref=CONTEXT_REF,
                registry=registry,
            )
        assert _reason(excinfo) == "CAPABILITY_DENIED"


def test_correspondence_table_covers_the_changelog_that_was_read() -> None:
    """One row per changelog entry. The record cites the same URL, date and sha256."""
    text = PROFILE.read_text(encoding="utf-8")
    assert "https://modelcontextprotocol.io/specification/2026-07-28/changelog" in text
    assert "2026-11-13" in text
    assert CHANGELOG_SHA256 in text
    assert SCHEMA_SHA256 in text
    for prefix, count in (("major", 9), ("minor", 12), ("deprecated", 4)):
        for number in range(1, count + 1):
            assert f"| {prefix}-{number} |" in text
    for row in ("other-schema-1", "governance-1", "process-1"):
        assert f"| {row} |" in text
    assert "NON_CONFORMANT" not in text
    assert "docs/development_plan/post_poc/README.md" in text


def _with_ref(ref: str, definitions: Mapping[str, Any], *, field: str = "inputSchema") -> dict[str, Any]:
    """Point one tool schema at ``ref``. Definitions live inside that tool schema."""
    document = _bare_descriptor()
    schema = document["tools"][0][field]
    if not isinstance(schema, dict):
        raise AssertionError("tool schema is not an object")
    schema["$defs"] = dict(definitions)
    schema["properties"] = {"name": {"$ref": ref}}
    return document


# VF-001 class: percent-decode the fragment (UTF-8), then apply JSON Pointer escapes.
# The three verdict positives are space, pi and the encoded dollar. The other rows are
# the same class: hex case, an encoded separator, tilde before and after encoding,
# raw characters, plus, and a single percent-decode.
_ENCODED_POINTERS = (
    ("space", "#/$defs/a%20b", {"a b": {"type": "string"}}),
    ("pi", "#/$defs/%CF%80", {"π": {"type": "string"}}),
    ("pi-lower", "#/$defs/%cf%80", {"π": {"type": "string"}}),
    ("dollar", "#/%24defs/foo", {"foo": {"type": "integer"}}),
    ("encoded-slash", "#%2F$defs/a%20b", {"a b": {"type": "string"}}),
    ("tilde-slash", "#/$defs/a~1b", {"a/b": {"type": "string"}}),
    ("tilde-slash-encoded", "#/$defs/a%7E1b", {"a/b": {"type": "string"}}),
    ("tilde-literal", "#/$defs/a~0b", {"a~b": {"type": "string"}}),
    ("tilde-literal-encoded", "#/$defs/a%7E0b", {"a~b": {"type": "string"}}),
    ("tilde-order", "#/$defs/~01", {"~1": {"type": "string"}}),
    ("raw-space", "#/$defs/a b", {"a b": {"type": "string"}}),
    ("raw-pi", "#/$defs/π", {"π": {"type": "string"}}),
    ("plus-is-not-space", "#/$defs/a+b", {"a+b": {"type": "string"}}),
    ("single-decode", "#/$defs/a%2520b", {"a%20b": {"type": "string"}}),
    ("boolean-true", "#/$defs/flag", {"flag": True}),
    ("boolean-false", "#/$defs/flag", {"flag": False}),
    ("empty-object", "#/$defs/open", {"open": {}}),
    ("integer-schema", "#/$defs/count", {"count": {"type": "integer"}}),
    ("all-of", "#/$defs/bundle", {"bundle": {"allOf": [{"type": "string"}]}}),
)


@pytest.mark.parametrize(
    ("ref", "definitions"),
    [(case[1], case[2]) for case in _ENCODED_POINTERS],
    ids=[case[0] for case in _ENCODED_POINTERS],
)
def test_percent_encoded_fragments_resolve_before_the_pointer(ref: str, definitions: Mapping[str, Any]) -> None:
    """VF-001 and the schema-shaped targets of VF-002.

    REM-0063-CYCLE10-REMAINING-CONTRACT-QUESTIONS A1: case ``encoded-slash``
    (``#%2F$defs/a%20b``) is refused. The other 18 cases stay accepted.
    Old expectation for ``encoded-slash``: the profile accepted the reference.
    ORACLE-CONFLICT A1 does not name this test.
    """
    if ref == "#%2F$defs/a%20b":
        profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
        with pytest.raises(profile.McpProfileError):
            _validate(_with_ref(ref, definitions))
        return
    _validate(_with_ref(ref, definitions))


@pytest.mark.parametrize("field", ["inputSchema", "outputSchema"])
def test_verdict_fragments_resolve_on_input_and_output_schemas(field: str) -> None:
    """The three verdict positives are the same check on both tool schemas."""
    _validate(_with_ref("#/$defs/a%20b", {"a b": {"type": "string"}}, field=field))
    _validate(_with_ref("#/$defs/%CF%80", {"π": {"type": "string"}}, field=field))
    _validate(_with_ref("#/%24defs/foo", {"foo": {"type": "integer"}}, field=field))


def test_an_encoded_fragment_does_not_select_the_literal_percent_key() -> None:
    """``a%20b`` decodes to a space. The literal key is a different pointer."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _with_ref("#/$defs/a%20b", {"a%20b": {"type": "string"}})
    with pytest.raises(profile.McpProfileError):
        _validate(document)


def test_an_encoded_array_index_resolves_and_a_leading_zero_stays_closed() -> None:
    """``%31`` is index 1. ``%30%31`` is ``01`` and is not an index."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    accepted = _choices_descriptor()
    accepted["tools"][0]["inputSchema"]["properties"]["name"] = {"$ref": "#/$defs/choices/anyOf/%31"}
    _validate(accepted)
    rejected = _choices_descriptor()
    rejected["tools"][0]["inputSchema"]["properties"]["name"] = {"$ref": "#/$defs/choices/anyOf/%30%31"}
    with pytest.raises(profile.McpProfileError):
        _validate(rejected)


# Truncated escapes, non-hex escapes, and byte sequences that are not UTF-8.
_MALFORMED_FRAGMENTS = (
    "#/$defs/%",
    "#/$defs/%2",
    "#/$defs/%ZZ",
    "#/$defs/%2G",
    "#/$defs/a%",
    "#/$defs/%C3",
    "#/$defs/%C3%28",
    "#/$defs/%C0%80",
    "#/$defs/%ED%A0%80",
    "#/$defs/%80",
    "#not-a-pointer",
    "#%2e%2e",
)


@pytest.mark.parametrize("ref", _MALFORMED_FRAGMENTS)
def test_malformed_uri_fragments_fail_closed(ref: str) -> None:
    """VF-001: a malformed fragment is a typed refusal, not a literal key.

    These rows do not plant the undecoded token. A resolver that skips
    percent-decoding still refuses them, because the key is absent. The
    planted-key rows below are the members that fail only when the decoder
    is removed.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _with_ref(ref, {"a b": {"type": "string"}, "present": {"type": "string"}})
    with pytest.raises(profile.McpProfileError):
        _validate(document)


# Class: the undecoded token is a real key whose value is a 2020-12 schema.
# referencing 0.37.0 resolves the loose percent spellings below. Those rows
# are accepted. A lookup that is PointerToNowhere stays a typed refusal for
# the recorded percent-encoding or UTF-8 reason.
# Members: truncated escape, non-hex, incomplete UTF-8, bad continuation,
# overlong, surrogate, lone continuation, the same bytes after other text,
# a bad escape after a well-formed encoding, and a bad escape that is not
# the last pointer segment.
# Spellings the probe resolved. The other 9 rows stay refused.
_PLANTED_LIBRARY_ACCEPTS = frozenset(
    {
        "#/$defs/%",
        "#/$defs/%2",
        "#/$defs/%ZZ",
        "#/$defs/%2G",
        "#/$defs/a%",
        "#/$defs/a%ZZb",
        "#/$defs/%ZZ/properties/name",
    }
)
_PLANTED_MALFORMED_FRAGMENTS = (
    ("truncated-percent", "#/$defs/%", {"%": {"type": "string"}}, "percent-encoding"),
    ("truncated-digit", "#/$defs/%2", {"%2": {"type": "string"}}, "percent-encoding"),
    ("non-hex", "#/$defs/%ZZ", {"%ZZ": {"type": "string"}}, "percent-encoding"),
    ("non-hex-digit", "#/$defs/%2G", {"%2G": {"type": "string"}}, "percent-encoding"),
    ("trailing-percent", "#/$defs/a%", {"a%": {"type": "string"}}, "percent-encoding"),
    ("embedded-non-hex", "#/$defs/a%ZZb", {"a%ZZb": {"type": "string"}}, "percent-encoding"),
    ("incomplete-utf8", "#/$defs/%C3", {"%C3": {"type": "string"}}, "UTF-8"),
    ("incomplete-utf8-lower", "#/$defs/%c3", {"%c3": {"type": "string"}}, "UTF-8"),
    ("bad-continuation", "#/$defs/%C3%28", {"%C3%28": {"type": "string"}}, "UTF-8"),
    ("overlong", "#/$defs/%C0%80", {"%C0%80": {"type": "string"}}, "UTF-8"),
    ("surrogate", "#/$defs/%ED%A0%80", {"%ED%A0%80": {"type": "string"}}, "UTF-8"),
    ("surrogate-lower", "#/$defs/%ed%a0%80", {"%ed%a0%80": {"type": "string"}}, "UTF-8"),
    ("lone-continuation", "#/$defs/%80", {"%80": {"type": "string"}}, "UTF-8"),
    ("embedded-continuation", "#/$defs/a%80b", {"a%80b": {"type": "string"}}, "UTF-8"),
    (
        "after-valid-encoding",
        "#/$defs/a%20b/%",
        {"a%20b": {"%": {"type": "string"}}},
        "percent-encoding",
    ),
    (
        "non-final-segment",
        "#/$defs/%ZZ/properties/name",
        {"%ZZ": {"type": "object", "properties": {"name": {"type": "string"}}}},
        "percent-encoding",
    ),
)


@pytest.mark.parametrize(
    ("ref", "definitions", "reason"),
    [case[1:] for case in _PLANTED_MALFORMED_FRAGMENTS],
    ids=[case[0] for case in _PLANTED_MALFORMED_FRAGMENTS],
)
def test_a_planted_literal_key_does_not_admit_a_malformed_fragment(
    ref: str,
    definitions: Mapping[str, Any],
    reason: str,
) -> None:
    """Library-resolved spellings are accepted. The other rows stay refused."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _with_ref(ref, definitions)
    if ref in _PLANTED_LIBRARY_ACCEPTS:
        _validate(document)
        return
    with pytest.raises(profile.McpProfileError, match=reason):
        _validate(document)


def test_a_planted_root_key_does_not_admit_a_malformed_fragment() -> None:
    """A malformed token at the document root is the same encoding refusal."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _with_ref("#/%ZZ", {"unused": {"type": "string"}})
    document["%ZZ"] = {"type": "string"}
    with pytest.raises(profile.McpProfileError, match="percent-encoding"):
        _validate(document)


def test_a_well_formed_encoding_reaches_the_literal_percent_key() -> None:
    """``%25ZZ`` is the key ``%ZZ``. The malformed twin ``%ZZ`` stays refused."""
    _validate(_with_ref("#/$defs/%25ZZ", {"%ZZ": {"type": "string"}}))


def test_an_external_percent_encoded_ref_stays_rejected() -> None:
    """Percent-encoding does not make an external reference same-document."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _with_ref("https://example.invalid/%24defs/foo", {"foo": {"type": "string"}})
    with pytest.raises(profile.McpProfileError):
        _validate(document)


@pytest.mark.parametrize("ref", ["", "#/"])
def test_an_empty_ref_or_an_empty_pointer_token_fails_closed(ref: str) -> None:
    """An empty ref is not a fragment. An empty pointer token does not resolve."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _with_ref(ref, {"present": {"type": "string"}})
    with pytest.raises(profile.McpProfileError):
        _validate(document)


def test_a_whole_document_fragment_is_checked_as_a_schema() -> None:
    """``#`` is the document. A schema-shaped document is accepted."""
    _validate(_with_ref("#", {"present": {"type": "string"}}))


def test_a_whole_document_fragment_rejects_a_non_schema_document() -> None:
    """``#`` lands on the document, so a non-schema ``$defs`` entry is in the target."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _with_ref("#", {"unused": 7})
    with pytest.raises(profile.McpProfileError):
        _validate(document)


# VF-002 class: the resolved target must be a JSON Schema 2020-12 schema.
# Booleans, {}, an integer schema and allOf are accepted above. These are not.
_NON_SCHEMA_TARGETS = (
    ("number", 7),
    ("float", 1.5),
    ("string", "not-a-schema"),
    ("empty-string", ""),
    ("null", None),
    ("empty-array", []),
    ("array", [{"type": "string"}]),
    ("bad-type", {"type": "not-a-json-schema-type"}),
    ("type-number", {"type": 1}),
    ("type-boolean", {"type": True}),
    ("minimum-string", {"minimum": "nope"}),
)


@pytest.mark.parametrize(
    "target",
    [case[1] for case in _NON_SCHEMA_TARGETS],
    ids=[case[0] for case in _NON_SCHEMA_TARGETS],
)
def test_a_resolved_target_that_is_not_a_schema_fails_closed(target: object) -> None:
    """VF-002: number, string, null, array and a non-schema object are refused."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _with_ref("#/$defs/bad", {"bad": target})
    with pytest.raises(profile.McpProfileError):
        _validate(document)


@pytest.mark.parametrize(
    "schema",
    [
        {"allOf": [{"$ref": "#/$defs/bad"}]},
        {"anyOf": [{"$ref": "#/$defs/bad"}]},
        {"oneOf": [{"$ref": "#/$defs/bad"}]},
        {"prefixItems": [{"$ref": "#/$defs/bad"}]},
        {"not": {"$ref": "#/$defs/bad"}},
        {"if": {"$ref": "#/$defs/bad"}},
        {"then": {"$ref": "#/$defs/bad"}},
        {"else": {"$ref": "#/$defs/bad"}},
        {"contains": {"$ref": "#/$defs/bad"}},
        {"items": {"$ref": "#/$defs/bad"}},
        {"additionalProperties": {"$ref": "#/$defs/bad"}},
        {"propertyNames": {"$ref": "#/$defs/bad"}},
        {"unevaluatedProperties": {"$ref": "#/$defs/bad"}},
        {"unevaluatedItems": {"$ref": "#/$defs/bad"}},
        {"contentSchema": {"$ref": "#/$defs/bad"}},
        {"additionalItems": {"$ref": "#/$defs/bad"}},
        {"dependentSchemas": {"name": {"$ref": "#/$defs/bad"}}},
        {"patternProperties": {".*": {"$ref": "#/$defs/bad"}}},
        {"$defs": {"inner": {"$ref": "#/$defs/bad"}}},
    ],
)
def test_every_schema_keyword_validates_its_resolved_target(schema: Mapping[str, Any]) -> None:
    """A non-schema target is refused wherever a schema keyword carries the $ref."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    document["$defs"] = {"bad": 7}
    body = document["tools"][0]["inputSchema"]
    if not isinstance(body, dict):
        raise AssertionError("input schema is not an object")
    body.update(schema)
    with pytest.raises(profile.McpProfileError):
        _validate(document)


def test_instance_data_does_not_validate_a_non_schema_target() -> None:
    """const, enum and default are instance data, not schema keywords."""
    document = _bare_descriptor()
    body = document["tools"][0]["inputSchema"]
    if not isinstance(body, dict):
        raise AssertionError("input schema is not an object")
    body["const"] = {"$ref": "#/$defs/missing"}
    body["default"] = {"$ref": "#/$defs/missing"}
    body["enum"] = [{"$ref": "https://example.invalid/%20"}, {"$ref": "#/$defs/%"}]
    _validate(document)


def test_an_unreferenced_non_schema_definition_is_not_a_resolved_target() -> None:
    """A descriptor with top-level ``$defs`` is refused, even for one unused entry.

    MCP-TOOL-SCHEMA-AUTONOMO: the descriptor is not a schema tree. The old
    expectation (an unused non-schema definition stays data) moved into the
    tool schema, where the whole-schema 2020-12 check refuses it.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    document["$defs"] = {"unused": 7}
    with pytest.raises(profile.McpProfileError, match="top-level \\$defs"):
        _validate(document)


# Cycle 3 of OCOR-DEV-REM-0063, verdict OCOR-DEV-REM-0063-19f63aeec7d1-2.
# REM-0063-CYCLE2-NO-GO (2026-11-14) option 1, and SELF-CHECK-CLASS-COVERAGE.
#
# VF-001 class: a schema a ``$ref`` actually reaches is checked with the dialect,
# local-reference and resolution rules, including a target read from instance data
# (``const``, ``default``, ``enum``, or any other non-keyword). The same rules
# already reject that schema when it sits directly under ``$defs``. Instance data
# that no ``$ref`` reaches stays data. Visited schema objects and the existing
# depth and node limits are unchanged.
# VF-002 class: after percent-decoding, every ``~`` in a JSON Pointer token must
# introduce ``~0`` or ``~1``. An incomplete escape, or any other escape, is
# ``McpProfileError`` before substitution, even when the literal key is planted.
# VF-003 class: an array index that cannot address a bounded document does not
# call an unbounded integer conversion. The refusal is ``McpProfileError``.

_DRAFT_07 = "http://json-schema.org/draft-07/schema#"
_CYCLE3_REACHED_TARGETS = (
    ("external", {"$ref": "https://example.invalid/evil.json"}),
    ("dangling", {"$ref": "#/$defs/missing"}),
    ("foreign-dialect", {"$schema": _DRAFT_07}),
    ("foreign-dialect-without-hash", {"$schema": "http://json-schema.org/draft-07/schema"}),
    ("dynamic-ref", {"$dynamicRef": "https://example.invalid/evil.json"}),
    ("recursive-ref", {"$recursiveRef": "https://example.invalid/evil.json"}),
    ("nested-external", {"properties": {"name": {"$ref": "https://example.invalid/nested.json"}}}),
    ("nested-anyof", {"anyOf": [{"$ref": "https://example.invalid/nested.json"}]}),
    ("dialect-not-a-string", {"$schema": 7}),
)
_CYCLE3_DATA_LOCATIONS = ("const", "default", "enum", "example")


def _cycle3_reached(target: object, *, location: str, field: str = "inputSchema") -> dict[str, Any]:
    """Point one tool schema at ``target`` through ``location`` or its own ``$defs``."""
    document = _bare_descriptor()
    schema = document["tools"][0][field]
    if not isinstance(schema, dict):
        raise AssertionError("tool schema is not an object")
    if location == "const":
        schema["$defs"] = {"holder": {"const": target}}
        ref = "#/$defs/holder/const"
    elif location == "default":
        schema["$defs"] = {"holder": {"default": target}}
        ref = "#/$defs/holder/default"
    elif location == "enum":
        schema["$defs"] = {"holder": {"enum": [target]}}
        ref = "#/$defs/holder/enum/0"
    elif location == "example":
        schema["$defs"] = {"holder": {"example": target}}
        ref = "#/$defs/holder/example"
    elif location == "defs":
        schema["$defs"] = {"target": target}
        ref = "#/$defs/target"
    else:
        raise AssertionError(location)
    schema["properties"] = {"name": {"$ref": ref}}
    return document


@pytest.mark.parametrize(
    ("target", "location"),
    [(case[1], location) for case in _CYCLE3_REACHED_TARGETS for location in _CYCLE3_DATA_LOCATIONS],
    ids=[f"{case[0]}-{location}" for case in _CYCLE3_REACHED_TARGETS for location in _CYCLE3_DATA_LOCATIONS],
)
def test_cycle3_a_schema_reached_through_instance_data_is_checked(target: object, location: str) -> None:
    """VF-001: dialect and resolution apply to a target read from instance data."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    with pytest.raises(profile.McpProfileError):
        _validate(_cycle3_reached(target, location=location))


@pytest.mark.parametrize(
    "target",
    [case[1] for case in _CYCLE3_REACHED_TARGETS],
    ids=[case[0] for case in _CYCLE3_REACHED_TARGETS],
)
def test_cycle3_the_same_target_directly_in_defs_stays_rejected(target: object) -> None:
    """The five verdict targets, and the same class, stay rejected under ``$defs``."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    with pytest.raises(profile.McpProfileError):
        _validate(_cycle3_reached(target, location="defs"))


def test_cycle3_output_schema_reaches_a_data_position_target() -> None:
    """``outputSchema`` is the twin of ``inputSchema`` on the same resolver."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle3_reached(
        {"$ref": "https://example.invalid/evil.json"},
        location="const",
        field="outputSchema",
    )
    with pytest.raises(profile.McpProfileError):
        _validate(document)


@pytest.mark.parametrize("location", ["const", "default"])
@pytest.mark.parametrize(
    "target",
    [True, {}, {"type": "integer"}, {"$schema": DRAFT_2020}],
    ids=["boolean", "empty-object", "integer-schema", "draft-2020-12"],
)
def test_cycle3_a_valid_schema_reached_through_instance_data_is_accepted(
    location: str,
    target: object,
) -> None:
    """Positive: a real schema read from ``const`` or ``default`` is in profile."""
    _validate(_cycle3_reached(target, location=location))


@pytest.mark.parametrize("location", ["const", "default"])
def test_cycle3_a_local_ref_inside_instance_data_resolves(location: str) -> None:
    """A reached schema may itself point at a local schema. That hop is checked.

    MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15): the local schema lives inside the
    tool schema, the only resource the reached ``$ref`` can resolve.
    """
    document = _cycle3_reached({"$ref": "#/$defs/good"}, location=location)
    body = document["tools"][0]["inputSchema"]
    if not isinstance(body, dict) or not isinstance(body["$defs"], dict):
        raise AssertionError("input schema $defs is not an object")
    body["$defs"]["good"] = {"type": "string"}
    _validate(document)
    nested = _cycle3_reached(
        {"properties": {"name": {"$ref": "#/$defs/good"}}},
        location=location,
    )
    nested_body = nested["tools"][0]["inputSchema"]
    if not isinstance(nested_body, dict) or not isinstance(nested_body["$defs"], dict):
        raise AssertionError("input schema $defs is not an object")
    nested_body["$defs"]["good"] = {"type": "string"}
    _validate(nested)


def test_cycle3_a_self_ref_through_const_stays_inside_the_visited_set() -> None:
    """A cycle through instance data is one visited schema, not an unbounded walk.

    MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15): the cycle lives inside the tool
    schema, the only resource the ref can resolve.
    """
    document = _bare_descriptor()
    body = document["tools"][0]["inputSchema"]
    if not isinstance(body, dict):
        raise AssertionError("input schema is not an object")
    body["$defs"] = {"holder": {"const": {"$ref": "#/$defs/holder/const"}}}
    body["properties"] = {"name": {"$ref": "#/$defs/holder/const"}}
    _validate(document)


def test_cycle3_a_long_data_position_chain_still_hits_the_depth_bound() -> None:
    """The depth limit is unchanged. A short chain passes and a 40-hop chain fails."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")

    def chain(length: int) -> dict[str, Any]:
        document = _bare_descriptor()
        body = document["tools"][0]["inputSchema"]
        if not isinstance(body, dict):
            raise AssertionError("input schema is not an object")
        definitions: dict[str, Any] = {}
        for index in range(length):
            nxt = f"#/$defs/h{index + 1}/const" if index + 1 < length else "#/$defs/leaf"
            definitions[f"h{index}"] = {"const": {"$ref": nxt}}
        definitions["leaf"] = {"type": "string"}
        body["$defs"] = definitions
        body["properties"] = {"name": {"$ref": "#/$defs/h0/const"}}
        return document

    _validate(chain(4))
    with pytest.raises(profile.McpProfileError, match="bounds"):
        _validate(chain(40))


@pytest.mark.parametrize(
    "target",
    [case[1] for case in _CYCLE3_REACHED_TARGETS],
    ids=[case[0] for case in _CYCLE3_REACHED_TARGETS],
)
def test_cycle3_unreferenced_instance_data_stays_accepted(target: object) -> None:
    """No ``$ref`` lands on these values, so they are not schemas to resolve."""
    document = _bare_descriptor()
    body = document["tools"][0]["inputSchema"]
    if not isinstance(body, dict):
        raise AssertionError("input schema is not an object")
    body["$defs"] = {
        "holder": {
            "const": target,
            "default": copy.deepcopy(target),
            "enum": [copy.deepcopy(target)],
        }
    }
    _validate(document)


# VF-002. The literal key is planted, so a missing-key refusal would not fire.
_CYCLE3_BAD_POINTERS = (
    ("verdict-tilde-two", "~2", "~2"),
    ("verdict-lone-tilde", "~", "~"),
    ("verdict-embedded", "a~3b", "a~3b"),
    ("tilde-three", "~3", "~3"),
    ("tilde-letter", "~a", "~a"),
    ("double-tilde", "~~", "~~"),
    ("trailing-tilde", "abc~", "abc~"),
    ("after-valid-escape", "~0~2", "~~2"),
    ("encoded-tilde-two", "%7E2", "~2"),
    ("encoded-lone-tilde", "%7E", "~"),
    ("non-final", "~2/type", "~2"),
)
_CYCLE3_GOOD_POINTERS = (
    ("verdict-escaped-two", "~02", "~2"),
    ("verdict-escaped-tilde", "~0", "~"),
    ("verdict-escaped-embedded", "a~03b", "a~3b"),
    ("tilde-then-one", "~01", "~1"),
    ("slash", "~1", "/"),
    ("slash-then-zero", "~10", "/0"),
    ("encoded-escape", "%7E0", "~"),
    ("encoded-slash", "%7E1", "/"),
)


@pytest.mark.parametrize(
    ("token", "key"),
    [case[1:] for case in _CYCLE3_BAD_POINTERS],
    ids=[case[0] for case in _CYCLE3_BAD_POINTERS],
)
def test_cycle3_a_bad_tilde_escape_is_rejected_before_substitution(token: str, key: str) -> None:
    """A literal ``~`` key that referencing resolves is accepted.

    ``~2/type`` still fails: the validator rejects the schema the pointer
    reaches. The 11 tokens and keys are unchanged.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    if "/" in token:
        document = _bare_descriptor()
        # Segment ``type`` lands on a schema when the bad escape is treated as a literal key.
        body = document["tools"][0]["inputSchema"]
        if not isinstance(body, dict):
            raise AssertionError("input schema is not an object")
        body["$defs"] = {key: {"type": {"type": "string"}}}
        body["properties"] = {"name": {"$ref": "#/$defs/" + token}}
    else:
        document = _with_ref("#/$defs/" + token, {key: {"type": "string"}})
    if token == "~2/type":
        with pytest.raises(profile.McpProfileError, match="not a JSON Schema 2020-12 schema"):
            _validate(document)
        return
    _validate(document)


@pytest.mark.parametrize(
    ("token", "key"),
    [case[1:] for case in _CYCLE3_GOOD_POINTERS],
    ids=[case[0] for case in _CYCLE3_GOOD_POINTERS],
)
def test_cycle3_a_well_formed_tilde_escape_resolves_the_planted_key(token: str, key: str) -> None:
    """The three verdict positives and the other legal escapes still resolve."""
    _validate(_with_ref("#/$defs/" + token, {key: {"type": "string"}}))


def test_cycle3_an_impossible_array_index_is_a_profile_error() -> None:
    """VF-003: 5000 digits, the 4300-digit boundary, and any index past the node budget."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    for token in ("9" * 5000, "9" * 4300, "1" + "0" * 4299, "9" * 5, "0" * 5000):
        document = _choices_descriptor()
        body = document["tools"][0]["inputSchema"]
        if not isinstance(body, dict):
            raise AssertionError("input schema is not an object")
        body["properties"] = {"name": {"$ref": "#/$defs/choices/anyOf/" + token}}
        with pytest.raises(profile.McpProfileError):
            _validate(document)


def test_cycle3_a_canonical_array_index_still_resolves() -> None:
    """The bound does not reject a one-digit index that addresses the array."""
    document = _choices_descriptor()
    body = document["tools"][0]["inputSchema"]
    if not isinstance(body, dict):
        raise AssertionError("input schema is not an object")
    body["properties"] = {"name": {"$ref": "#/$defs/choices/anyOf/0"}}
    _validate(document)


# Cycle 4 of OCOR-DEV-REM-0063, verdict OCOR-DEV-REM-0063-660a8c6e129c-3 VF-001.
# REM-0063-CYCLE3-NO-GO (2026-11-14) option 1, and SELF-CHECK-CLASS-COVERAGE.
#
# Class: after percent-decoding, a same-document ``$ref`` fragment is either a
# JSON Pointer (the decoded text starts with ``/``) or a JSON Schema 2020-12
# plain-name anchor. The pinned ``referencing`` resolver indexes ``$anchor``
# and ``$dynamicAnchor``. This profile does too, then fails closed when two
# different schema objects carry the same name (the resolver keeps one).
# Members: an existing anchor resolves to the same schema as its JSON Pointer;
# an absent anchor is rejected; an ambiguous anchor is rejected; a
# percent-encoded fragment is classified only after decoding; an external
# reference stays rejected; a JSON Pointer stays accepted; the value landed on
# is still checked as a 2020-12 schema; the visited set and the depth bound
# stay in force. An anchor written only inside instance data is not a target.


def _cycle4_anchor_document(
    ref: str,
    definitions: Mapping[str, Any],
    *,
    field: str = "inputSchema",
) -> dict[str, Any]:
    """Point one tool schema at ``ref``. ``definitions`` join its own ``$defs``."""
    return _with_ref(ref, definitions, field=field)


def _cycle4_library_contents(
    document: Mapping[str, Any], ref: str, *, field: str = "inputSchema"
) -> Any:
    """Return the schema the pinned resolver yields for a same-document ``ref``."""
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    schema = document["tools"][0][field]
    if not isinstance(schema, Mapping):
        raise AssertionError("tool schema is not an object")
    resource = Resource.from_contents({"$schema": DRAFT_2020, **dict(schema)}, DRAFT202012)
    registry = Registry().with_resource("urn:ocor-rem0063", resource)
    contents = registry.resolver("urn:ocor-rem0063").lookup(ref).contents
    if not isinstance(contents, Mapping):
        raise AssertionError("pinned resolver did not return a schema object")
    return contents


def test_cycle4_an_existing_anchor_matches_the_pinned_resolver_and_the_pointer() -> None:
    """VF-001: ``#part`` and ``#/$defs/part`` are the same integer schema.

    The pinned resolver and ``Draft202012Validator`` accept an integer and
    reject a string. The profile accepts both descriptors.
    """
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    definitions = {"part": {"$anchor": "part", "type": "integer"}}
    for ref in ("#part", "#/$defs/part"):
        document = _cycle4_anchor_document(ref, definitions)
        schema = document["tools"][0]["inputSchema"]
        if not isinstance(schema, Mapping):
            raise AssertionError("tool schema is not an object")
        resource = Resource.from_contents({"$schema": DRAFT_2020, **dict(schema)}, DRAFT202012)
        registry = Registry().with_resource("urn:ocor-rem0063", resource)
        contents = registry.resolver("urn:ocor-rem0063").lookup(ref).contents
        assert isinstance(contents, Mapping)
        assert contents["type"] == "integer"
        validator = Draft202012Validator({"$ref": "urn:ocor-rem0063" + ref}, registry=registry)
        assert list(validator.iter_errors(7)) == []
        assert list(validator.iter_errors("not-an-integer"))
        profile.validate_mcp_descriptor(document, _official_schema(), expected_revision=REVISION)


def test_cycle4_the_same_anchor_is_accepted_on_the_output_schema() -> None:
    """``outputSchema`` is the twin of ``inputSchema`` for a plain-name anchor."""
    document = _cycle4_anchor_document(
        "#part",
        {"part": {"$anchor": "part", "type": "integer"}},
        field="outputSchema",
    )
    _validate(document)


def test_cycle4_a_dynamic_anchor_resolves_when_the_pinned_resolver_does() -> None:
    """``$dynamicAnchor`` is an anchor the pinned resolver indexes by plain name."""
    document = _cycle4_anchor_document("#part", {"part": {"$dynamicAnchor": "part", "type": "integer"}})
    contents = _cycle4_library_contents(document, "#part")
    assert contents["type"] == "integer"
    _validate(document)


def test_cycle4_one_schema_with_both_anchor_keywords_is_a_single_target() -> None:
    """The same object declaring both keywords under one name is not ambiguous."""
    document = _cycle4_anchor_document(
        "#part",
        {"part": {"$anchor": "part", "$dynamicAnchor": "part", "type": "integer"}},
    )
    contents = _cycle4_library_contents(document, "#part")
    assert contents["type"] == "integer"
    _validate(document)


def test_cycle4_an_anchor_under_properties_matches_its_json_pointer() -> None:
    """A plain name and the pointer of that schema object land on one target."""
    definitions = {
        "holder": {
            "type": "object",
            "properties": {"name": {"$anchor": "part", "type": "integer"}},
        }
    }
    _validate(_cycle4_anchor_document("#part", definitions))
    _validate(_cycle4_anchor_document("#/$defs/holder/properties/name", definitions))


def test_cycle4_an_absent_anchor_does_not_resolve() -> None:
    """A plain name with no ``$anchor`` or ``$dynamicAnchor`` is not a pointer."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle4_anchor_document("#missing", {"part": {"$anchor": "part", "type": "integer"}})
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(document)


def test_cycle4_an_ambiguous_anchor_is_rejected() -> None:
    """Two schema objects with the same plain name do not pick a winner."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle4_anchor_document(
        "#part",
        {
            "one": {"$anchor": "part", "type": "integer"},
            "two": {"$anchor": "part", "type": "string"},
        },
    )
    with pytest.raises(profile.McpProfileError, match="ambiguous"):
        _validate(document)


def test_cycle4_an_anchor_shared_by_dynamic_and_plain_keywords_is_ambiguous() -> None:
    """The same name on two objects is ambiguous even across the two keywords."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle4_anchor_document(
        "#part",
        {
            "one": {"$anchor": "part", "type": "integer"},
            "two": {"$dynamicAnchor": "part", "type": "string"},
        },
    )
    with pytest.raises(profile.McpProfileError, match="ambiguous"):
        _validate(document)


def test_cycle4_a_percent_encoded_plain_name_is_decoded_before_classification() -> None:
    """``#p%61rt`` is refused. The library does not decode anchor names.

    REM-0063-CYCLE10-ORACLE-CONFLICT A1. Old expectation: the profile accepted
    ``#p%61rt`` as ``#part``.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle4_anchor_document("#p%61rt", {"part": {"$anchor": "part", "type": "integer"}})
    with pytest.raises(profile.McpProfileError):
        _validate(document)


def test_cycle4_a_percent_encoded_slash_stays_a_json_pointer() -> None:
    """``#%2F$defs/part`` is refused. The library does not treat ``%2F`` as ``/``.

    REM-0063-CYCLE10-ORACLE-CONFLICT A1. Old expectation: the profile accepted
    the reference as a JSON Pointer.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle4_anchor_document(
        "#%2F$defs/part",
        {"part": {"$anchor": "part", "type": "integer"}},
    )
    with pytest.raises(profile.McpProfileError):
        _validate(document)


def test_cycle4_a_decoded_absent_name_does_not_select_the_undecoded_anchor() -> None:
    """``#mis%73ing`` is ``missing``. The planted undecoded anchor is not the target."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle4_anchor_document("#mis%73ing", {"decoy": {"$anchor": "mis%73ing", "type": "string"}})
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(document)


def test_cycle4_an_external_anchor_fragment_stays_rejected() -> None:
    """Percent-encoding and a plain name do not make an external reference local."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle4_anchor_document(
        "https://example.invalid/schema.json#part",
        {"part": {"$anchor": "part", "type": "integer"}},
    )
    with pytest.raises(profile.McpProfileError, match="same-document"):
        _validate(document)


def test_cycle4_an_anchor_target_that_is_not_a_schema_is_rejected() -> None:
    """Landing on the anchor still runs the 2020-12 schema check."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle4_anchor_document(
        "#part",
        {"part": {"$anchor": "part", "type": "not-a-json-schema-type"}},
    )
    with pytest.raises(profile.McpProfileError, match="not a JSON Schema"):
        _validate(document)


def test_cycle4_a_non_string_anchor_keyword_is_not_a_match() -> None:
    """A boolean ``$anchor`` is not the plain name ``part``."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle4_anchor_document("#part", {"part": {"$anchor": True, "type": "integer"}})
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(document)


def test_cycle4_an_anchor_inside_instance_data_is_not_a_plain_name_target() -> None:
    """``const`` is not crawled for anchors. The JSON Pointer to that value still resolves."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    hidden = {"holder": {"const": {"$anchor": "hidden", "type": "integer"}}}
    absent = _cycle4_anchor_document("#hidden", hidden)
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(absent)
    _validate(_cycle4_anchor_document("#/$defs/holder/const", hidden))


def test_cycle4_a_self_anchor_stays_inside_the_visited_set() -> None:
    """An anchor that points at itself is one visited schema, not a recursive walk.

    MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15): the chain lives inside the tool
    schema resource, the only tree the ``$ref`` can resolve in.
    """
    _validate(_with_ref("#part", {"part": {"$anchor": "part", "$ref": "#part"}}))


def test_cycle4_an_anchor_hop_does_not_lift_the_depth_bound() -> None:
    """The last hop is an anchor. Four hops pass and forty still hit the bound.

    MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15): the chain lives inside the tool
    schema resource, the only tree the ``$ref`` can resolve in.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")

    def chain(length: int) -> dict[str, Any]:
        definitions: dict[str, Any] = {"leaf": {"$anchor": "leaf", "type": "string"}}
        for index in range(length):
            nxt = f"#/$defs/h{index + 1}/const" if index + 1 < length else "#leaf"
            definitions[f"h{index}"] = {"const": {"$ref": nxt}}
        body = _bare_descriptor()["tools"][0]["inputSchema"]
        if not isinstance(body, dict):
            raise AssertionError("input schema is not an object")
        body["$defs"] = definitions
        body["properties"] = {"name": {"$ref": "#/$defs/h0/const"}}
        document = _bare_descriptor()
        document["tools"][0]["inputSchema"] = body
        return document

    _validate(chain(4))
    with pytest.raises(profile.McpProfileError, match="bounds"):
        _validate(chain(40))


# Same class, after the cycle-4 review. An embedded tool schema is its own
# JSON Schema tree (MCP-TOOL-SCHEMA-AUTONOMO): a ref inside it sees anchors
# and pointers only in that schema. Two different objects with one plain name
# inside one resource are ambiguous. A nested non-empty ``$id`` is a separate
# resource. ``additionalItems`` is not a JSON Schema 2020-12 anchor applicator.


def _cycle4_embedded_tool(
    schema: Mapping[str, Any],
    *,
    field: str = "inputSchema",
    definitions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Put ``schema`` on one tool. Definitions, when given, join its own ``$defs``.

    MCP-TOOL-SCHEMA-AUTONOMO: every tool schema is its own tree, so the
    descriptor has no ``$defs`` position for these fixtures anymore.
    """
    document = _bare_descriptor()
    placed = dict(schema)
    if definitions:
        own = placed.setdefault("$defs", {})
        if not isinstance(own, dict):
            raise AssertionError("schema $defs is not an object")
        own.update(definitions)
    document["tools"][0][field] = placed
    return document


def _assert_standalone_integer(schema: Mapping[str, Any]) -> None:
    """The pinned metaschema accepts an integer and rejects a string."""
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors({"x": 7})) == []
    assert list(validator.iter_errors({"x": "no"}))


@pytest.mark.parametrize("field", ["inputSchema", "outputSchema"])
def test_cycle4_an_anchor_local_to_the_tool_schema_resolves(field: str) -> None:
    """``#part`` inside the tool schema is the same integer schema as its pointer."""
    schema = {
        "type": "object",
        "$defs": {"part": {"$anchor": "part", "type": "integer"}},
        "properties": {"x": {"$ref": "#part"}},
    }
    document = _cycle4_embedded_tool(schema, field=field)
    standalone = document["tools"][0][field]
    if not isinstance(standalone, Mapping):
        raise AssertionError("tool schema is not an object")
    _assert_standalone_integer(standalone)
    _validate(document)


@pytest.mark.parametrize("field", ["inputSchema", "outputSchema"])
def test_cycle4_an_anchor_under_tool_schema_properties_resolves(field: str) -> None:
    """A plain name on a property schema is in the tool schema's resource."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"$anchor": "part", "type": "integer"},
            "x": {"$ref": "#part"},
        },
    }
    document = _cycle4_embedded_tool(schema, field=field)
    _validate(document)


@pytest.mark.parametrize("field", ["inputSchema", "outputSchema"])
def test_cycle4_an_anchor_on_the_tool_schema_itself_resolves(field: str) -> None:
    """The tool schema object can carry the plain name the ref uses."""
    schema = {"$anchor": "part", "type": "object", "properties": {"x": {"$ref": "#part"}}}
    _validate(_cycle4_embedded_tool(schema, field=field))


@pytest.mark.parametrize("keyword", ["$anchor", "$dynamicAnchor"])
def test_cycle4_a_percent_encoded_tool_schema_anchor_is_decoded(keyword: str) -> None:
    """``#p%61rt`` inside the tool schema is refused for both anchor keywords.

    REM-0063-CYCLE10-ORACLE-CONFLICT A1. Old expectation: acceptance after
    decoding, for ``$anchor`` and ``$dynamicAnchor``.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = {
        "type": "object",
        "$defs": {"part": {keyword: "part", "type": "integer"}},
        "properties": {"x": {"$ref": "#p%61rt"}},
    }
    with pytest.raises(profile.McpProfileError):
        _validate(_cycle4_embedded_tool(schema))


def test_cycle4_an_absent_tool_schema_anchor_does_not_resolve() -> None:
    """A plain name that the tool schema does not declare is not a pointer."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = {
        "type": "object",
        "$defs": {"part": {"$anchor": "part", "type": "integer"}},
        "properties": {"x": {"$ref": "#missing"}},
    }
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(_cycle4_embedded_tool(schema))


@pytest.mark.parametrize("field", ["inputSchema", "outputSchema"])
def test_cycle4_two_anchors_inside_one_tool_schema_are_ambiguous(field: str) -> None:
    """Two objects in the tool schema with one plain name do not pick a winner."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = {
        "type": "object",
        "$defs": {
            "one": {"$anchor": "part", "type": "integer"},
            "two": {"$dynamicAnchor": "part", "type": "string"},
        },
        "properties": {"x": {"$ref": "#part"}},
    }
    with pytest.raises(profile.McpProfileError, match="ambiguous"):
        _validate(_cycle4_embedded_tool(schema, field=field))


@pytest.mark.parametrize("field", ["inputSchema", "outputSchema"])
def test_cycle4_a_local_pointer_in_the_tool_schema_resolves(field: str) -> None:
    """``#/$defs/part`` inside the tool schema is that schema's own definition."""
    schema = {
        "type": "object",
        "$defs": {"part": {"type": "integer"}},
        "properties": {"x": {"$ref": "#/$defs/part"}},
    }
    document = _cycle4_embedded_tool(schema, field=field)
    standalone = document["tools"][0][field]
    if not isinstance(standalone, Mapping):
        raise AssertionError("tool schema is not an object")
    _assert_standalone_integer(standalone)
    _validate(document)


@pytest.mark.parametrize("field", ["inputSchema", "outputSchema"])
def test_cycle4_a_document_pointer_still_resolves_beside_a_local_definition(field: str) -> None:
    """A tool-schema ref to descriptor ``$defs`` is refused: schemas are autonomous.

    MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15): the descriptor has no resolution
    tree and a descriptor that declares top-level ``$defs`` is a typed
    refusal, so the old acceptance is the new refusal.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = {
        "type": "object",
        "$defs": {"other": {"type": "string"}},
        "properties": {"x": {"$ref": "#/$defs/part"}},
    }
    document = _cycle4_embedded_tool(schema, field=field)
    document["$defs"] = {"part": {"type": "integer"}}
    with pytest.raises(profile.McpProfileError, match=r"top-level \$defs"):
        _validate(document)


@pytest.mark.parametrize("field", ["inputSchema", "outputSchema"])
def test_cycle4_a_pointer_in_both_the_tool_schema_and_the_document_is_ambiguous(field: str) -> None:
    """The removed document/tool ambiguity check is superseded by the typed refusal."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = {
        "type": "object",
        "$defs": {"part": {"type": "string"}},
        "properties": {"x": {"$ref": "#/$defs/part"}},
    }
    document = _cycle4_embedded_tool(schema, field=field)
    document["$defs"] = {"part": {"type": "integer"}}
    with pytest.raises(profile.McpProfileError, match=r"top-level \$defs"):
        _validate(document)


@pytest.mark.parametrize("field", ["inputSchema", "outputSchema"])
def test_cycle4_a_tool_schema_anchor_duplicated_on_the_document_is_ambiguous(field: str) -> None:
    """Descriptor ``$defs`` beside a tool anchor are refused as top-level defs."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = {
        "type": "object",
        "$defs": {"two": {"$anchor": "part", "type": "string"}},
        "properties": {"x": {"$ref": "#part"}},
    }
    document = _cycle4_embedded_tool(schema, field=field)
    document["$defs"] = {"one": {"$anchor": "part", "type": "integer"}}
    with pytest.raises(profile.McpProfileError, match=r"top-level \$defs"):
        _validate(document)


def test_cycle4_a_document_ref_does_not_use_a_tool_only_anchor() -> None:
    """A descriptor-side ``$defs`` holder is refused with the typed top-level error."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle4_embedded_tool(
        {
            "type": "object",
            "properties": {"x": {"type": "string"}},
        }
    )
    document["$defs"] = {"holder": {"$ref": "#part"}}
    with pytest.raises(profile.McpProfileError, match=r"top-level \$defs"):
        _validate(document)


def test_cycle4_a_local_pointer_to_a_non_schema_is_rejected() -> None:
    """Landing inside the tool schema still runs the 2020-12 schema check."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = {
        "type": "object",
        "$defs": {"part": 7},
        "properties": {"x": {"$ref": "#/$defs/part"}},
    }
    with pytest.raises(profile.McpProfileError, match="not a JSON Schema"):
        _validate(_cycle4_embedded_tool(schema))


def test_cycle4_a_local_anchor_target_that_is_not_a_schema_is_rejected() -> None:
    """A plain name inside the tool schema is not exempt from the schema check."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = {
        "type": "object",
        "$defs": {"part": {"$anchor": "part", "type": "not-a-json-schema-type"}},
        "properties": {"x": {"$ref": "#part"}},
    }
    with pytest.raises(profile.McpProfileError, match="not a JSON Schema"):
        _validate(_cycle4_embedded_tool(schema))


def test_cycle4_a_self_anchor_inside_the_tool_schema_stays_visited() -> None:
    """An anchor that points at itself inside the tool schema is one visited schema."""
    schema = {
        "type": "object",
        "$defs": {"part": {"$anchor": "part", "$ref": "#part"}},
        "properties": {"x": {"$ref": "#part"}},
    }
    _validate(_cycle4_embedded_tool(schema))


def test_cycle4_an_anchor_behind_an_id_is_not_a_parent_anchor() -> None:
    """A nested ``$id`` keeps its plain name out of the parent resource."""
    from referencing import Registry, Resource
    from referencing.exceptions import NoSuchAnchor
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = {"type": "object", "properties": {"x": {"$ref": "#part"}}}
    document = _cycle4_embedded_tool(
        schema,
        definitions={
            "sub": {
                "$id": "https://example.invalid/sub.json",
                "$anchor": "part",
                "type": "integer",
            }
        },
    )
    resource = Resource.from_contents({"$schema": DRAFT_2020, **dict(schema)}, DRAFT202012)
    registry = Registry().with_resource("urn:ocor-rem0063", resource)
    with pytest.raises(NoSuchAnchor):
        registry.resolver("urn:ocor-rem0063").lookup("#part")
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(document)


def test_cycle4_an_anchor_inside_an_id_resource_resolves_there() -> None:
    """Inside the nested resource, ``#part`` is that resource's own anchor."""
    document = _bare_descriptor()
    document["tools"][0]["inputSchema"] = {
        "type": "object",
        "$defs": {
            "sub": {
            "$id": "https://example.invalid/sub.json",
            "$anchor": "part",
            "type": "object",
            "properties": {"x": {"$ref": "#part"}},
            }
        }
    }
    _validate(document)


@pytest.mark.parametrize("keyword", ["$anchor", "$dynamicAnchor"])
def test_cycle4_an_anchor_under_additional_items_is_not_indexed(keyword: str) -> None:
    """``additionalItems`` is not an applicator in draft 2020-12."""
    from referencing import Registry, Resource
    from referencing.exceptions import NoSuchAnchor
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle4_anchor_document(
        "#part",
        {"holder": {"additionalItems": {keyword: "part", "type": "integer"}}},
    )
    schema = document["tools"][0]["inputSchema"]
    if not isinstance(schema, Mapping):
        raise AssertionError("tool schema is not an object")
    resource = Resource.from_contents({"$schema": DRAFT_2020, **dict(schema)}, DRAFT202012)
    registry = Registry().with_resource("urn:ocor-rem0063", resource)
    with pytest.raises(NoSuchAnchor):
        registry.resolver("urn:ocor-rem0063").lookup("#part")
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(document)


def test_cycle4_an_anchor_under_additional_items_in_the_tool_schema_is_not_indexed() -> None:
    """The tool schema uses the same 2020-12 applicator set."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = {
        "type": "object",
        "additionalItems": {"$anchor": "part", "type": "integer"},
        "properties": {"x": {"$ref": "#part"}},
    }
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(_cycle4_embedded_tool(schema))


# VF-001 repair cycle 5, REM-0063-CYCLE5-NO-GO (2026-11-14).
# Class: the empty fragment ``#`` of a same-document ``$ref`` resolves on the
# current schema resource, the schema that contains the reference, identified
# by its ``$id`` when present, and not on the enclosing document when that
# document is not that resource.
# Members covered here:
# 1. a resource with ``$id`` and ``$ref`` ``#`` is accepted against itself;
# 2. the same resource stays accepted against itself in ``inputSchema``,
#    ``outputSchema``, under ``$defs``, and nested under ``inputSchema``;
# 3. an unreferenced sibling that is not a schema does not become the root;
# 4. a negative ``#/$defs/bad`` distinguishes that root from the descriptor;
# 5. JSON Pointer, plain-name anchor, percent-encoded fragment, external
#    reference and the ambiguous-anchor rule stay on the paths already green.
# Oracle: referencing 0.37.0 on the current resource. Draft202012Validator is
# the acceptance counterproof. A percent-encoded anchor spelling is refused:
# the library does not decode anchor names (ORACLE-CONFLICT A1). It is not
# compared with the decoded plain name.
# SELF-CHECK-CLASS-COVERAGE. SELF-CHECK-ORACOLO.

_CYCLE5_ID = "https://example.invalid/independent.json"
_CYCLE5_EXTERNAL = "https://example.invalid/other.json"
_CYCLE5_LOCATIONS = ("inputSchema", "outputSchema", "$defs", "nested")
_CYCLE5_REFS = (
    "#",
    "#/$defs/part",
    "#/$defs/p%61rt",
    "#part",
    "#p%61rt",
    "#/$defs/a%20b",
)
# referencing 0.37.0 percent-decodes pointer tokens and leaves anchor names raw.
_CYCLE5_ORACLE_FRAGMENT = {
    "#": "#",
    "#/$defs/part": "#/$defs/part",
    "#/$defs/p%61rt": "#/$defs/p%61rt",
    "#part": "#part",
    "#p%61rt": "#p%61rt",
    "#/$defs/a%20b": "#/$defs/a%20b",
    "#/$defs/bad": "#/$defs/bad",
}


def _cycle5_cases() -> list[tuple[str, str, bool, int | None, str]]:
    """Every accepted schema shape in this cycle, plus the closed negatives."""
    cases: list[tuple[str, str, bool, int | None, str]] = []
    for location in _CYCLE5_LOCATIONS:
        for with_id in (False, True):
            for sibling in (None, 7):
                for ref in _CYCLE5_REFS:
                    cases.append(("matrix", location, with_id, sibling, ref))
        cases.append(("external", location, True, None, _CYCLE5_EXTERNAL))
        cases.append(("foreign-root", location, True, None, "#/$defs/bad"))
    cases.append(("ambiguous", "inputSchema", False, None, "#part"))
    return cases


_CYCLE5_CASES = _cycle5_cases()


def _cycle5_case_id(case: tuple[str, str, bool, int | None, str]) -> str:
    kind, location, with_id, sibling, ref = case
    return f"{kind}-{location}-id{int(with_id)}-sib{sibling}-{ref}"


def _cycle5_attach_target(holder: dict[str, Any], ref: str) -> None:
    """Put the object ``ref`` names on ``holder`` and nowhere else."""
    if ref in ("#", _CYCLE5_EXTERNAL):
        return
    definitions = holder.setdefault("$defs", {})
    if not isinstance(definitions, dict):
        raise AssertionError("$defs is not an object")
    if ref in ("#/$defs/part", "#/$defs/p%61rt"):
        definitions["part"] = {"type": "integer"}
    elif ref in ("#part", "#p%61rt"):
        definitions["holder"] = {"$anchor": "part", "type": "integer"}
    elif ref == "#/$defs/a%20b":
        definitions["a b"] = {"type": "integer"}
    elif ref == "#/$defs/bad":
        definitions["bad"] = 7
    else:
        raise AssertionError(ref)


def _cycle5_place(document: dict[str, Any], location: str, schema: dict[str, Any]) -> None:
    """Install ``schema`` at one of the four class positions."""
    if location == "inputSchema":
        document["tools"][0]["inputSchema"] = schema
    elif location == "outputSchema":
        document["tools"][0]["outputSchema"] = schema
    elif location == "$defs":
        document["tools"][0]["inputSchema"] = {
            "type": "object",
            "$defs": {"sub": schema},
        }
    elif location == "nested":
        document["tools"][0]["inputSchema"] = {
            "type": "object",
            "properties": {"inner": schema},
        }
    else:
        raise AssertionError(location)


def _cycle5_placed(document: Mapping[str, Any], location: str) -> dict[str, Any]:
    """Return the schema object installed by :func:`_cycle5_place`."""
    tool = document["tools"][0]
    if not isinstance(tool, dict):
        raise AssertionError("tool is not an object")
    if location == "inputSchema":
        placed = tool["inputSchema"]
    elif location == "outputSchema":
        placed = tool["outputSchema"]
    elif location == "$defs":
        wrapper = tool["inputSchema"]
        if not isinstance(wrapper, dict):
            raise AssertionError("input schema is not an object")
        defs = wrapper["$defs"]
        if not isinstance(defs, dict):
            raise AssertionError("$defs is not an object")
        placed = defs["sub"]
    elif location == "nested":
        body = tool["inputSchema"]
        if not isinstance(body, dict):
            raise AssertionError("input schema is not an object")
        properties = body["properties"]
        if not isinstance(properties, dict):
            raise AssertionError("properties is not an object")
        placed = properties["inner"]
    else:
        raise AssertionError(location)
    if not isinstance(placed, dict):
        raise AssertionError("placed schema is not an object")
    return placed


def _cycle5_document(
    kind: str,
    location: str,
    with_id: bool,
    sibling: int | None,
    ref: str,
) -> dict[str, Any]:
    """Build one generated descriptor. Targets live on the current resource."""
    document = _bare_descriptor()
    if kind == "ambiguous":
        document["tools"][0]["inputSchema"] = {
            "type": "object",
            "$defs": {
                "local": {"$anchor": "part", "type": "integer"},
                "remote": {"$anchor": "part", "type": "string"},
            },
            "properties": {"n": {"$ref": "#part"}},
        }
        return document
    if kind == "foreign-root":
        schema = {
            "$id": _CYCLE5_ID,
            "type": "object",
            "$defs": {"bad": 7},
            "properties": {"n": {"$ref": "#/$defs/bad"}},
        }
        _cycle5_place(document, location, schema)
        return document
    schema = {
        "type": "object",
        "required": ["n"],
        "properties": {
            "n": {"type": "integer"},
            "next": {"$ref": ref},
        },
    }
    if with_id:
        schema["$id"] = _CYCLE5_ID
        _cycle5_attach_target(schema, ref)
    _cycle5_place(document, location, schema)
    root = _cycle5_root(document, location)
    if not with_id:
        _cycle5_attach_target(root, ref)
    if sibling is not None:
        root.setdefault("default", {})["unreferenced"] = sibling
    return document


def _cycle5_root(document: Mapping[str, Any], location: str) -> dict[str, Any]:
    """The autonomous tool schema resource that owns the placed schema."""
    if location in ("inputSchema", "outputSchema"):
        root = document["tools"][0][location]
    else:
        root = document["tools"][0]["inputSchema"]
    if not isinstance(root, dict):
        raise AssertionError("tool schema is not an object")
    return root


def _cycle5_current_resource(
    document: Mapping[str, Any],
    kind: str,
    location: str,
    with_id: bool,
) -> Mapping[str, Any]:
    """The resource referencing must use: the ``$id`` schema, else the tool schema."""
    if kind == "ambiguous" or not with_id:
        return _cycle5_root(document, location)
    return _cycle5_placed(document, location)


def _cycle5_lookup(resource: Mapping[str, Any], ref: str) -> tuple[Any, BaseException | None]:
    """Resolve ``ref`` with referencing 0.37.0. The oracle does not rewrite it."""
    import importlib.metadata
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    if importlib.metadata.version("referencing") != "0.37.0":
        raise AssertionError("cycle-5 oracle is referencing 0.37.0")
    body = dict(resource)
    body.setdefault("$schema", DRAFT_2020)
    uri = body.get("$id")
    if not isinstance(uri, str) or not uri:
        uri = "urn:ocor-rem0063"
    registry = Registry().with_resource(uri, Resource.from_contents(body, DRAFT202012))
    fragment = _CYCLE5_ORACLE_FRAGMENT.get(ref, ref)
    try:
        return registry.resolver(uri).lookup(fragment).contents, None
    except Exception as exc:
        return None, exc


def _cycle5_library_accepts(contents: Any, error: BaseException | None) -> bool:
    """True when the oracle target exists and Draft 2020-12 accepts it as a schema."""
    if error is not None or contents is None:
        return False
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    try:
        Draft202012Validator.check_schema(contents)
    except (SchemaError, TypeError, ValueError):
        return False
    return True


def _cycle5_counterproof(schema: Mapping[str, Any], ref: str) -> None:
    """Draft202012Validator accepts a good instance and rejects a bad one.

    The instance check uses the original reference. REM-0063-CYCLE10-ORACLE-CONFLICT
    A1: the counterproof does not replace ``#p%61rt`` with ``#part``.
    """
    from jsonschema import Draft202012Validator

    body = copy.deepcopy(dict(schema))
    properties = body.get("properties")
    if not isinstance(properties, dict):
        raise AssertionError("counterproof schema has no properties")
    nxt = properties.get("next")
    if not isinstance(nxt, dict):
        raise AssertionError("counterproof schema has no next")
    nxt["$ref"] = _CYCLE5_ORACLE_FRAGMENT.get(ref, ref)
    if ref == "#":
        good: dict[str, Any] = {"n": 1, "next": {"n": 2}}
        bad: dict[str, Any] = {"n": 1, "next": {"n": "bad"}}
    else:
        good = {"n": 1, "next": 2}
        bad = {"n": 1, "next": "bad"}
    validator = Draft202012Validator(body)
    assert list(validator.iter_errors(good)) == []
    assert list(validator.iter_errors(bad))


def _cycle5_expect_target(contents: Any, ref: str, *, with_id: bool) -> None:
    """The oracle object for ``ref`` is the current resource or its definition."""
    if not isinstance(contents, dict):
        raise AssertionError(f"oracle target for {ref} is not an object")
    if ref == "#":
        if with_id:
            assert contents.get("$id") == _CYCLE5_ID
        else:
            assert "$id" not in contents
            assert "properties" in contents or "$defs" in contents
        return
    if ref in ("#part", "#p%61rt"):
        assert contents.get("$anchor") == "part"
        return
    assert contents.get("type") == "integer"


def _cycle5_corrupt(
    document: Mapping[str, Any],
    location: str,
    with_id: bool,
    ref: str,
) -> dict[str, Any]:
    """Replace the oracle target with a non-schema so the profile must reject it."""
    corrupted = copy.deepcopy(document)
    if ref == "#":
        target = (
            _cycle5_placed(corrupted, location)
            if with_id
            else _cycle5_root(corrupted, location)
        )
        definitions = target.get("$defs")
        if isinstance(definitions, dict):
            definitions["bad"] = 7
        else:
            target["$defs"] = {"bad": 7}
        return corrupted
    holder = (
        _cycle5_placed(corrupted, location)
        if with_id
        else _cycle5_root(corrupted, location)
    )
    definitions = holder["$defs"]
    if not isinstance(definitions, dict):
        raise AssertionError("$defs is not an object")
    if ref in ("#/$defs/part", "#/$defs/p%61rt"):
        definitions["part"] = 7
    elif ref in ("#part", "#p%61rt"):
        definitions["holder"] = 7
    elif ref == "#/$defs/a%20b":
        definitions["a b"] = 7
    else:
        raise AssertionError(ref)
    return corrupted


@pytest.mark.parametrize("location", _CYCLE5_LOCATIONS)
def test_cycle5_empty_fragment_on_an_id_resource_ignores_a_non_schema_sibling(
    location: str,
) -> None:
    """``#`` on an ``$id`` resource stays that resource when the descriptor is not a schema.

    RED fingerprint of VF-001 before the empty-pointer repair: the profile
    checks the descriptor, and ``$defs.unreferenced = 7`` makes that check fail.
    referencing 0.37.0 and Draft202012Validator accept the resource itself.
    """
    document = _cycle5_document("matrix", location, True, 7, "#")
    schema = _cycle5_placed(document, location)
    _cycle5_counterproof(schema, "#")
    contents, error = _cycle5_lookup(schema, "#")
    assert error is None
    _cycle5_expect_target(contents, "#", with_id=True)
    _validate(document)


def test_cycle5_generated_case_count_is_stable() -> None:
    """The cycle record cites this count. The oracle package stays pinned."""
    import importlib.metadata

    assert importlib.metadata.version("referencing") == "0.37.0"
    assert len(_CYCLE5_CASES) == 105


@pytest.mark.parametrize(
    ("kind", "location", "with_id", "sibling", "ref"),
    _CYCLE5_CASES,
    ids=[_cycle5_case_id(case) for case in _CYCLE5_CASES],
)
def test_cycle5_ref_targets_match_referencing_on_the_current_resource(
    kind: str,
    location: str,
    with_id: bool,
    sibling: int | None,
    ref: str,
) -> None:
    """Each accepted ``$ref`` lands on the object referencing 0.37.0 returns.

    A profile rejection is allowed when the oracle also rejects the target, or
    when two anchors make the target ambiguous. Corrupting the oracle target
    must make an accepted descriptor fail, including ``#`` on an ``$id`` resource
    whose descriptor holds an unreferenced non-schema sibling.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle5_document(kind, location, with_id, sibling, ref)
    resource = _cycle5_current_resource(document, kind, location, with_id)
    contents, error = _cycle5_lookup(resource, ref)
    library_ok = _cycle5_library_accepts(contents, error)
    try:
        _validate(document)
    except profile.McpProfileError as exc:
        profile_error: profile.McpProfileError | None = exc
    else:
        profile_error = None
    if profile_error is None:
        assert library_ok, (kind, location, with_id, sibling, ref)
        _cycle5_expect_target(contents, ref, with_id=with_id)
        if with_id and kind == "matrix":
            _cycle5_counterproof(_cycle5_placed(document, location), ref)
        corrupted = _cycle5_corrupt(document, location, with_id, ref)
        with pytest.raises(profile.McpProfileError):
            _validate(corrupted)
        return
    if library_ok:
        assert kind == "ambiguous", str(profile_error)
        assert "ambiguous" in str(profile_error)
        return
    assert profile_error is not None


# VF-001 repair cycle 6, REM-0063-CYCLE6-NO-GO (2026-11-15), option 1.
# Class: the current resource is the URI after joining ``$id``, not the
# presence of a lexically non-empty ``$id``. ``#`` stays the empty JSON
# Pointer on that resource. It does not become a branch that always selects
# the whole document. Members: ``$id`` ``#``; an ``$id`` that joins to the
# same URI (the same absolute URI, and ``./root.json``); a non-schema target
# rejected when referencing 0.37.0 names it and Draft202012Validator rejects
# it; an empty ``$id`` and a distinct ``$id`` stay on the paths already green.
# Oracle: referencing 0.37.0. SELF-CHECK-CLASS-COVERAGE. SELF-CHECK-ORACOLO.

_CYCLE6_URI = "https://verifier.invalid/root.json"
_CYCLE6_DISTINCT = "https://example.invalid/independent.json"
_CYCLE6_LOCATIONS = ("inputSchema", "outputSchema", "$defs", "nested")
_CYCLE6_IDENTIFIERS = (
    "#",
    "",
    _CYCLE6_URI,
    "./root.json",
    _CYCLE6_DISTINCT,
    "child.json",
)
_CYCLE6_REFS = ("#", "#/$defs/part", "#/$defs/p%61rt", "#part", "#p%61rt")
_CYCLE6_ORACLE_FRAGMENT = {
    "#": "#",
    "#/$defs/part": "#/$defs/part",
    "#/$defs/p%61rt": "#/$defs/p%61rt",
    "#part": "#part",
    "#p%61rt": "#p%61rt",
}


def _cycle6_same_resource(identifier: str) -> bool:
    """True when ``identifier`` joins to the parent URI on the governed Python."""
    from urllib.parse import urljoin

    if identifier == "":
        return True
    return urljoin(_CYCLE6_URI, identifier) == _CYCLE6_URI


def _cycle6_cases() -> list[tuple[str, str, str, int | None]]:
    """Locations, identifiers, fragments and the non-schema sibling.

    ``sibling`` is ``7`` or absent. It is a ``$defs`` entry of the descriptor,
    beside the schema under test, the same class member as cycle 5.
    """
    return [
        (location, identifier, ref, sibling)
        for sibling in (None, 7)
        for location in _CYCLE6_LOCATIONS
        for identifier in _CYCLE6_IDENTIFIERS
        for ref in _CYCLE6_REFS
    ]


_CYCLE6_CASES = _cycle6_cases()


def _cycle6_case_id(case: tuple[str, str, str, int | None]) -> str:
    location, identifier, ref, sibling = case
    label = identifier if identifier else "empty"
    suffix = "" if sibling is None else "-sibling"
    return f"{location}-{label}-{ref}{suffix}"


def _cycle6_descriptor() -> dict[str, Any]:
    return {
        "x-ocor-mcp-protocol-revision": REVISION,
        "tools": [
            {
                "name": "probe",
                "inputSchema": {"type": "object"},
                "outputSchema": {"type": "object"},
            }
        ],
    }


def _cycle6_attach(owner: dict[str, Any], ref: str) -> None:
    """Put the object ``ref`` names on the resource that owns the reference."""
    if ref == "#":
        return
    definitions = owner.setdefault("$defs", {})
    if not isinstance(definitions, dict):
        raise AssertionError("$defs is not an object")
    if ref in ("#/$defs/part", "#/$defs/p%61rt"):
        definitions["part"] = {"type": "integer"}
    elif ref in ("#part", "#p%61rt"):
        definitions["anchor"] = {"$anchor": "part", "type": "integer"}
    else:
        raise AssertionError(ref)


def _cycle6_place(
    document: dict[str, Any], location: str, parent: dict[str, Any]
) -> None:
    """Install ``parent`` at one class position. ``nested`` sits under properties."""
    if location == "inputSchema":
        document["tools"][0]["inputSchema"] = parent
    elif location == "outputSchema":
        document["tools"][0]["outputSchema"] = parent
    elif location == "$defs":
        document["tools"][0]["inputSchema"] = {
            "type": "object",
            "$defs": {"root": parent},
        }
    elif location == "nested":
        document["tools"][0]["inputSchema"] = {
            "type": "object",
            "properties": {"inner": parent},
        }
    else:
        raise AssertionError(location)


def _cycle6_document(
    location: str,
    identifier: str,
    ref: str,
    sibling: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return the descriptor, the parent resource and the schema that holds ``$ref``.

    ``sibling`` is stored beside the schema, under the descriptor ``$defs``, and
    is not part of the parent resource. A non-schema sibling must not decide a
    reference whose current resource is the parent.
    """
    document = _cycle6_descriptor()
    holder: dict[str, Any] = {
        "type": "object",
        "properties": {"n": {"type": "integer"}, "next": {"$ref": ref}},
    }
    if identifier != "":
        holder["$id"] = identifier
    parent: dict[str, Any] = {
        "$id": _CYCLE6_URI,
        "type": "object",
        "properties": {"holder": holder},
    }
    if _cycle6_same_resource(identifier):
        _cycle6_attach(parent, ref)
    else:
        _cycle6_attach(holder, ref)
    _cycle6_place(document, location, parent)
    if sibling is not None:
        if location in ("inputSchema", "outputSchema"):
            root = parent
        else:
            root = document["tools"][0]["inputSchema"]
            if not isinstance(root, dict):
                raise AssertionError("input schema is not an object")
        root.setdefault("default", {})["not_schema"] = sibling
    return document, parent, holder


def _cycle6_lookup(
    parent: Mapping[str, Any], ref: str
) -> tuple[Any, BaseException | None]:
    """Resolve ``ref`` with referencing 0.37.0 after entering the holder."""
    import importlib.metadata
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    if importlib.metadata.version("referencing") != "0.37.0":
        raise AssertionError("cycle-6 oracle is referencing 0.37.0")
    registry = Registry().with_resource(
        _CYCLE6_URI,
        Resource.from_contents(parent, DRAFT202012),
    )
    holder = registry.resolver(_CYCLE6_URI).lookup("#/properties/holder")
    fragment = _CYCLE6_ORACLE_FRAGMENT.get(ref, ref)
    try:
        return holder.resolver.lookup(fragment).contents, None
    except Exception as exc:
        return None, exc


# REM-0063-CYCLE10-NESTED-RESOURCE-RESOLUTION (2026-11-17), options A1 and B1.
# These identities are the explicit list of the 39 cycle-6 cases whose
# expectation becomes the pinned libraries on the tool schema alone.
_CYCLE6_NESTED_REALIGN_IDS = frozenset({"#", _CYCLE6_URI, "./root.json"})
_CYCLE6_NESTED_REALIGN_REFS = frozenset({"#", "#/$defs/part", "#/$defs/p%61rt"})
_CYCLE6_NESTED_REALIGN_LOCATIONS = frozenset({"$defs", "nested"})


def _cycle6_nested_realignment(location: str, identifier: str, ref: str) -> bool:
    """True for one of the 39 cases A1 names. Inputs stay the same."""
    return (
        location in _CYCLE6_NESTED_REALIGN_LOCATIONS
        and identifier in _CYCLE6_NESTED_REALIGN_IDS
        and ref in _CYCLE6_NESTED_REALIGN_REFS
    )


def _independent_tool_base(schema: object, *, index: int, field: str) -> str:
    """B1 base, computed here. No production import.

    Absent, non-string, ``""`` and an empty pre-fragment use the fixed URI.
    Every other root ``$id`` uses its pre-fragment part. A fixed URI that
    collides with any string ``$id`` in the schema is a lookup failure.
    """

    from urllib.parse import urldefrag

    fixed = f"urn:ocor:embedded-tool:{index}:{field}"
    declared = schema.get("$id") if isinstance(schema, Mapping) else None
    if isinstance(declared, str) and declared != "" and urldefrag(declared)[0] != "":
        return urldefrag(declared)[0]

    found: set[str] = set()
    seen: set[int] = set()

    def walk(node: object) -> None:
        if isinstance(node, (str, bool)) or node is None or isinstance(node, (int, float, bytes)):
            return
        identity = id(node)
        if identity in seen:
            return
        seen.add(identity)
        if isinstance(node, Mapping):
            item = node.get("$id")
            if isinstance(item, str):
                found.add(item)
            for value in node.values():
                walk(value)
            return
        if isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    for item in found:
        if item == fixed or item.rstrip("#") == fixed:
            raise LookupError("MCP schema base collides with a declared $id")
    return fixed


def _cycle6_schema_alone(document: Mapping[str, Any], ref: str) -> tuple[Any, BaseException | None]:
    """Resolve ``ref`` with referencing 0.37.0 on the tool schema alone.

    The registry pins only that schema at the independent B1 base. No nested
    ``with_resource`` and no ``PointerToNowhere`` retry. The object returned
    is the library object for that spelling.
    """
    import importlib.metadata
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    if importlib.metadata.version("referencing") != "0.37.0":
        raise AssertionError("cycle-6 oracle is referencing 0.37.0")
    schema = document["tools"][0]["inputSchema"]
    if not isinstance(schema, dict):
        raise AssertionError("tool schema is not an object")
    base = _independent_tool_base(schema, index=0, field="inputSchema")
    resource = DRAFT202012.create_resource(schema)
    resolver = Registry().with_resource(base, resource).resolver(base)
    queue: list[tuple[Any, Any]] = [(resource, resolver)]
    seen: set[tuple[int, object]] = set()
    while queue:
        current, context = queue.pop(0)
        identity = (id(current.contents), getattr(context, "_base_uri", None))
        if identity in seen:
            continue
        seen.add(identity)
        contents = current.contents
        if isinstance(contents, dict) and contents.get("$ref") == ref:
            try:
                return context.lookup(ref).contents, None
            except Exception as exc:
                return None, exc
        try:
            children = list(current.subresources())
        except (AttributeError, TypeError, ValueError):
            children = []
        for child in children:
            queue.append((child, context.in_subresource(child)))
    return None, LookupError(ref)


def _cycle6_library_accepts(contents: Any, error: BaseException | None) -> bool:
    """True when the oracle target exists and Draft 2020-12 accepts it as a schema."""
    if error is not None or not isinstance(contents, dict):
        return False
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    try:
        Draft202012Validator.check_schema(contents)
    except (SchemaError, TypeError, ValueError):
        return False
    return True


def _cycle6_ruin(contents: dict[str, Any]) -> None:
    """Make this object fail ``check_schema`` without replacing its identity.

    The object stays in place, including a ``$ref`` it contains. Clearing it
    would delete that reference, so a later profile run would no longer land
    on the resource ``#`` names when the resource is not a tool schema.
    """
    contents["type"] = 7


@pytest.mark.parametrize("identifier", ["#", "", _CYCLE6_URI, "./root.json"])
@pytest.mark.parametrize("location", ["inputSchema", "outputSchema", "$defs"])
def test_cycle6_noop_id_empty_fragment_lands_on_the_parent_resource(
    identifier: str,
    location: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``#`` after a no-op ``$id`` is the resource the pinned libraries name.

    On inputSchema and outputSchema, and for an empty ``$id`` under ``$defs``,
    that resource is still the parent. The three ``$defs`` cases whose
    identifier is ``#``, the parent URI or ``./root.json`` are the A1 list:
    the same inputs, and the expectation is referencing 0.37.0 on the tool
    schema alone, which names the holder.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document, parent, holder = _cycle6_document(location, identifier, "#")
    realign = _cycle6_nested_realignment(location, identifier, "#")
    if realign:
        contents, error = _cycle6_schema_alone(document, "#")
        expected = holder
        unexpected = parent
    else:
        contents, error = _cycle6_lookup(parent, "#")
        expected = parent
        unexpected = holder
    assert error is None
    assert contents is expected
    assert holder is not parent
    seen: list[object] = []
    original = profile._require_schema

    def record(target: object) -> None:
        seen.append(target)
        original(target)

    monkeypatch.setattr(profile, "_require_schema", record)
    _validate(document)
    assert expected in seen, (identifier, location)
    assert unexpected not in seen, (identifier, location)


@pytest.mark.parametrize("location", ["inputSchema", "outputSchema", "$defs"])
def test_cycle6_hash_id_does_not_hide_a_non_schema_current_resource(
    location: str,
) -> None:
    """``$id`` ``#`` keeps the tool schema resource; a non-schema on it is refused.

    MCP-TOOL-SCHEMA-AUTONOMO: the descriptor is not a schema tree, so the
    non-schema sibling that used to sit on the descriptor now sits on the tool
    schema root. referencing 0.37.0 resolves ``#`` to that root.
    Draft202012Validator.check_schema rejects it, and so must the profile:
    the ``$id`` of ``#`` does not hide the invalid current resource.
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle6_descriptor()
    child: dict[str, Any] = {
        "$id": "#",
        "type": "object",
        "properties": {"tail": {"$ref": "#"}},
    }
    if location == "$defs":
        document["tools"][0]["inputSchema"] = {
            "type": "object",
            "$defs": {"child": child, "not_schema": 7},
        }
        root = document["tools"][0]["inputSchema"]
    else:
        child["$defs"] = {"not_schema": 7}
        document["tools"][0][location] = child
        root = child
    if not isinstance(root, dict):
        raise AssertionError("tool schema is not an object")
    resource = Resource.from_contents(root, DRAFT202012)
    resolver = Registry().with_resource(_CYCLE6_URI, resource).resolver(_CYCLE6_URI)
    if location == "$defs":
        entered = resolver.lookup("#/$defs/child").resolver
    else:
        entered = resolver.in_subresource(Resource.from_contents(child, DRAFT202012))
    resolved = entered.lookup("#").contents
    assert resolved is root
    with pytest.raises(SchemaError):
        Draft202012Validator.check_schema(resolved)
    with pytest.raises(profile.McpProfileError, match="target is not a JSON Schema"):
        _validate(document)


def test_cycle6_a_distinct_id_stays_inside_its_own_resource() -> None:
    """A different joined URI is still its own resource. An unreferenced sibling is ignored."""
    document = _cycle6_descriptor()
    document["tools"][0]["inputSchema"] = {
        "$id": _CYCLE6_DISTINCT,
        "default": {"not_schema": 7},
        "type": "object",
        "properties": {"tail": {"$ref": "#"}},
    }
    _validate(document)


def test_cycle6_generated_case_count_is_stable() -> None:
    """The cycle record cites this count. The oracle package stays pinned."""
    import importlib.metadata

    assert importlib.metadata.version("referencing") == "0.37.0"
    assert len(_CYCLE6_CASES) == 240


def _cycle6_tool_schema_hides_ruin(location: str) -> bool:
    """True when the oracle object sits inside a tool schema.

    ``inputSchema`` and ``outputSchema`` are checked again at the end of
    ``validate_mcp_descriptor``. Ruining an object inside them makes that check
    fail even when ``$ref`` landed on a different object. ``$defs`` does not.
    """
    return location in ("inputSchema", "outputSchema", "nested")


@pytest.mark.parametrize(
    ("location", "identifier", "ref", "sibling"),
    _CYCLE6_CASES,
    ids=[_cycle6_case_id(case) for case in _CYCLE6_CASES],
)
def test_cycle6_ref_targets_match_referencing_on_the_effective_resource(
    location: str,
    identifier: str,
    ref: str,
    sibling: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each accepted ``$ref`` lands on the object referencing 0.37.0 returns.

    The landed object is the oracle object by identity. Ruining that object
    must make the profile refuse when the ruin is not also the tool schema.
    A no-op ``$id`` keeps the parent resource, except the 36 A1 cases under
    ``$defs`` and ``nested``: those use the libraries on the tool schema
    alone, so a pointer that the library cannot resolve is refused and ``#``
    lands on the holder.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document, parent, holder = _cycle6_document(location, identifier, ref, sibling)
    realign = _cycle6_nested_realignment(location, identifier, ref)
    if realign:
        contents, error = _cycle6_schema_alone(document, ref)
    else:
        contents, error = _cycle6_lookup(parent, ref)
    library_ok = _cycle6_library_accepts(contents, error)
    seen: list[object] = []
    original = profile._require_schema

    def record(target: object) -> None:
        seen.append(target)
        original(target)

    monkeypatch.setattr(profile, "_require_schema", record)
    try:
        _validate(document)
    except profile.McpProfileError as exc:
        profile_error: profile.McpProfileError | None = exc
    else:
        profile_error = None
    if library_ok:
        assert profile_error is None, (
            location,
            identifier,
            ref,
            sibling,
            profile_error,
        )
        assert isinstance(contents, dict)
        assert contents in seen, (location, identifier, ref, sibling)
        if realign and ref == "#":
            assert contents is holder
            assert parent not in seen
        elif ref == "#" and _cycle6_same_resource(identifier):
            assert contents is parent
            assert holder not in seen
        if _cycle6_tool_schema_hides_ruin(location):
            return
        _cycle6_ruin(contents)
        with pytest.raises(profile.McpProfileError):
            _validate(document)
        return
    assert profile_error is not None, (location, identifier, ref, sibling)


# Review repair of OCOR-DEV-REM-0063-2018893ae8f3-pre, findings P1 and P2.
# The resource identifier strips a trailing empty fragment before urljoin,
# matching referencing 0.37.0 Resource.id. A relative identifier is joined
# once, when the resource is entered.

_CYCLE6_P1_ROOTS = (None, "", "urn:ocor:root", "https://verifier.invalid/root.json#")
_CYCLE6_P1_REFS = ("#", "#/$defs/part", "#part")


def _cycle6_p1_children(root_id: str | None) -> tuple[str, ...]:
    """Identifiers that name the same resource as ``root_id`` after the strip."""
    if root_id is None or root_id == "":
        return ("#",)
    if root_id == "urn:ocor:root":
        return ("#", "urn:ocor:root")
    bare = root_id.rstrip("#")
    return ("#", bare, "./root.json")


def _cycle6_p1_cases() -> list[tuple[str | None, str, str, str, bool]]:
    """Root identifier, child identifier, location, fragment, and the sibling poison."""
    cases: list[tuple[str | None, str, str, str, bool]] = []
    for root_id in _CYCLE6_P1_ROOTS:
        for child_id in _cycle6_p1_children(root_id):
            for location in _CYCLE6_LOCATIONS:
                for ref in _CYCLE6_P1_REFS:
                    cases.append((root_id, child_id, location, ref, ref == "#"))
    return cases


_CYCLE6_P1_CASES = _cycle6_p1_cases()


def _cycle6_p1_case_id(case: tuple[str | None, str, str, str, bool]) -> str:
    root_id, child_id, location, ref, poison = case
    root = "absent" if root_id is None else (root_id if root_id else "empty")
    return f"{root}-{child_id}-{location}-{ref}-{poison}"


def _cycle6_p1_document(
    root_id: str | None,
    child_id: str,
    location: str,
    ref: str,
    *,
    poison: bool,
) -> dict[str, Any]:
    """A tool schema whose child ``$id`` must not leave the root resource.

    MCP-TOOL-SCHEMA-AUTONOMO: the descriptor is not a schema tree, so the
    root resource of this class is the tool schema itself. The child that
    used to replace the whole tool schema now sits inside it, keeping the
    ``$id``-join class unchanged.
    """
    document = _cycle6_descriptor()
    root: dict[str, Any] = {"type": "object", "$defs": {}}
    if root_id is not None:
        root["$id"] = root_id
    if poison:
        root["$defs"]["not_schema"] = 7
    if ref in ("#/$defs/part",):
        root["$defs"]["part"] = {"type": "integer"}
    elif ref == "#part":
        root["$defs"]["anchor"] = {"$anchor": "part", "type": "integer"}
    elif ref != "#":
        raise AssertionError(ref)
    child: dict[str, Any] = {
        "type": "object",
        "properties": {"tail": {"$ref": ref}},
    }
    if child_id != "":
        child["$id"] = child_id
    if location == "nested":
        root["properties"] = {"inner": child}
        document["tools"][0]["inputSchema"] = root
    elif location == "outputSchema":
        root["$defs"]["child"] = child
        document["tools"][0]["outputSchema"] = root
    else:
        root["$defs"]["child"] = child
        document["tools"][0]["inputSchema"] = root
    return document


@pytest.mark.parametrize(
    ("root_id", "child_id", "location", "ref", "poison"),
    _CYCLE6_P1_CASES,
    ids=[_cycle6_p1_case_id(case) for case in _CYCLE6_P1_CASES],
)
def test_cycle6_empty_fragment_suffix_stays_on_the_root_resource(
    root_id: str | None,
    child_id: str,
    location: str,
    ref: str,
    poison: bool,
) -> None:
    """An ``$id`` that is ``#``, empty, ``urn:`` or a trailing ``#`` stays put.

    referencing 0.37.0 strips the empty fragment before joining. ``#`` on that
    resource sees a non-schema sibling and is refused. A pointer or anchor on
    the same resource resolves. RED before the strip: the pointer does not
    resolve, or the poisoned ``#`` is accepted.
    """
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle6_p1_document(root_id, child_id, location, ref, poison=poison)
    if location == "outputSchema":
        root = document["tools"][0]["outputSchema"]
    else:
        root = document["tools"][0]["inputSchema"]
    assert isinstance(root, dict)
    body = copy.deepcopy(root)
    body.setdefault("$schema", DRAFT_2020)
    if location == "nested":
        child = body["properties"]["inner"]
    else:
        child = body["$defs"]["child"]
    resource = DRAFT202012.create_resource(body)
    uri = resource.id() or "urn:ocor-rem0063-empty"
    registry = Registry().with_resource(uri, resource)
    entered = registry.resolver(uri).in_subresource(DRAFT202012.create_resource(child))
    try:
        oracle = entered.lookup(ref).contents
        oracle_error: BaseException | None = None
    except Exception as exc:
        oracle = None
        oracle_error = exc
    if poison:
        assert oracle is body, (root_id, child_id, location, oracle_error)
        with pytest.raises(
            profile.McpProfileError, match="target is not a JSON Schema"
        ):
            _validate(document)
        return
    assert oracle_error is None, (root_id, child_id, location, ref, oracle_error)
    assert isinstance(oracle, dict)
    _validate(document)


_CYCLE6_P2_HOLDERS = (
    "sub/child.json",
    "./sub/child.json",
    "../other.json",
    "child.json",
)
_CYCLE6_P2_REFS = ("#/$defs/part", "#part")


def _cycle6_p2_canonical(holder_id: str) -> str:
    from urllib.parse import urljoin

    return urljoin(_CYCLE6_URI, holder_id)


def _cycle6_p2_inner_ids(holder_id: str) -> tuple[str, ...]:
    canonical = _cycle6_p2_canonical(holder_id)
    leaf = canonical.rsplit("/", 1)[-1]
    return ("#", canonical, "./" + leaf)


def _cycle6_p2_document(holder_id: str, inner_id: str, ref: str) -> dict[str, Any]:
    """A pointer reaches a schema that redeclares the holder's canonical URI."""
    part: dict[str, Any]
    if ref == "#part":
        part = {"$anchor": "part", "type": "integer"}
    else:
        part = {"type": "integer"}
    holder: dict[str, Any] = {
        "$id": holder_id,
        "type": "object",
        "$defs": {"part": part},
        "properties": {"probe": {"$ref": "#/const"}},
        "const": {
            "type": "object",
            "properties": {
                "inner": {
                    "$id": inner_id,
                    "type": "object",
                    "properties": {"self": {"$ref": ref}},
                }
            },
        },
    }
    parent: dict[str, Any] = {
        "$id": _CYCLE6_URI,
        "type": "object",
        "properties": {"holder": holder},
    }
    document = _cycle6_descriptor()
    document["tools"][0]["inputSchema"] = parent
    return document


def _cycle6_p2_cases() -> list[tuple[str, str, str]]:
    return [
        (holder_id, inner_id, ref)
        for holder_id in _CYCLE6_P2_HOLDERS
        for inner_id in _cycle6_p2_inner_ids(holder_id)
        for ref in _CYCLE6_P2_REFS
    ]


_CYCLE6_P2_CASES = _cycle6_p2_cases()


@pytest.mark.parametrize(
    ("holder_id", "inner_id", "ref"),
    _CYCLE6_P2_CASES,
    ids=[f"{holder}-{inner}-{ref}" for holder, inner, ref in _CYCLE6_P2_CASES],
)
def test_cycle6_relative_id_is_joined_once_when_a_pointer_reenters_it(
    holder_id: str,
    inner_id: str,
    ref: str,
) -> None:
    """A relative ``$id`` is not joined again for a schema reached by pointer.

    ``#/const`` lands inside the holder. The inner schema redeclares that
    holder's canonical URI. referencing 0.37.0 keeps the holder and resolves
    the fragment there. RED before the single join: ``sub/child.json`` and
    ``./sub/child.json`` raise ``MCP $ref does not resolve``.
    """
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    document = _cycle6_p2_document(holder_id, inner_id, ref)
    parent = document["tools"][0]["inputSchema"]
    assert isinstance(parent, dict)
    resource = DRAFT202012.create_resource(parent)
    registry = Registry().with_resource(resource.id(), resource)
    holder = registry.resolver(resource.id()).lookup("#/properties/holder")
    inner = parent["properties"]["holder"]["const"]["properties"]["inner"]
    entered = holder.resolver.in_subresource(DRAFT202012.create_resource(inner))
    oracle = entered.lookup(ref).contents
    assert oracle == {"type": "integer"} or oracle.get("$anchor") == "part"
    _validate(document)


@pytest.mark.parametrize("holder_id", _CYCLE6_P2_HOLDERS)
def test_cycle6_a_different_inner_id_does_not_see_the_holder_definitions(
    holder_id: str,
) -> None:
    """An inner URI that really differs stays its own resource and fails closed."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle6_p2_document(
        holder_id,
        "https://example.invalid/elsewhere.json",
        "#/$defs/part",
    )
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(document)


# Cycle 7 of OCOR-DEV-REM-0063, verdict OCOR-DEV-REM-0063-d70920ea901f-6 VF-001.
# REM-0063-CYCLE7-NO-GO (2026-11-15) option 1 and SELF-CHECK-ORACOLO.
#
# Class: resolution context, meaning the effective resource and base URI, is
# kept at every JSON Pointer step, including a step that crosses an intermediate
# ``$id``. References inside the reached target inherit that context and not the
# descriptor the pointer started from. The empty fragment remains the empty JSON
# Pointer and selects the effective resource. The class members cover
# ``const``, ``default`` and ``examples``; ``inputSchema`` and ``outputSchema``;
# a definition only in the nested resource and one only outside it; pointers,
# percent-encoded pointers, anchors and ``#``. The generated differential suite
# uses referencing 0.37.0 as the oracle.

_CYCLE7_BASE = "https://independent.invalid/review/root.json"
_CYCLE7_WHERE = ("inputSchema", "outputSchema", "$defs", "nested")
_CYCLE7_IDENTIFIERS = (
    "#",
    "./other/../root.json#",
    "../review/root.json",
    "child/schema.json#",
)
_CYCLE7_SLOTS = ("const", "default", "examples")
_CYCLE7_FRAGMENTS = (
    "#/$defs/only_here",
    "#/%24defs/only_here",
    "#independent_anchor",
)
_CYCLE7_AVAILABILITY = ("outer", "holder")
_CYCLE7_FIELDS = ("inputSchema", "outputSchema")
_CYCLE7_EMPTY_CASES = tuple(
    (where, identifier, poison)
    for where in _CYCLE7_WHERE
    for identifier in _CYCLE7_IDENTIFIERS
    for poison in (False, True)
)
_CYCLE7_DIFFERENTIAL_CASES = tuple(
    (slot, fragment, available_in, where)
    for slot in _CYCLE7_SLOTS
    for fragment in _CYCLE7_FRAGMENTS
    for available_in in _CYCLE7_AVAILABILITY
    for where in _CYCLE7_FIELDS
)


def _cycle7_root(mark: Mapping[str, Any]) -> dict[str, Any]:
    """The autonomous tool schema resource hosting the cycle-7 holder."""
    return {"$id": _CYCLE7_BASE, "type": "object", "$defs": {"root_mark": mark}}


def _cycle7_holder_pointer(slot: str) -> str:
    suffix = "/0" if slot == "examples" else ""
    return f"#/$defs/holder/{slot}{suffix}/target"


def _cycle7_pointer_crossing_document(
    slot: str,
    fragment: str,
    available_in: str,
    where: str,
) -> tuple[dict[str, Any], dict[str, Any], Mapping[str, Any]]:
    """One tool schema whose holder is crossed by the pointer under test.

    MCP-TOOL-SCHEMA-AUTONOMO: the descriptor has no tree, so the holder and
    the outer ``$defs`` live in the tool schema that carries the ``$ref``.
    """
    document = _bare_descriptor()
    target = {
        "type": "object",
        "properties": {"value": {"$ref": fragment}},
    }
    box = {"target": target}
    holder = {
        "$id": "review-child/holder.json",
        "type": "object",
        slot: [box] if slot == "examples" else box,
    }
    entry = {"$anchor": "independent_anchor", "type": "integer"}
    root = {
        "$id": _CYCLE7_BASE,
        "type": "object",
        "$defs": {"holder": holder},
        "$ref": _cycle7_holder_pointer(slot),
    }
    owner = root if available_in == "outer" else holder
    definitions = owner.setdefault("$defs", {})
    if not isinstance(definitions, dict):
        raise AssertionError("$defs is not an object")
    definitions["only_here"] = entry
    document["tools"][0][where] = root
    return document, holder, entry


@pytest.mark.parametrize(
    ("where", "identifier", "poison"),
    _CYCLE7_EMPTY_CASES,
    ids=[f"{where}-{identifier}-{poison}" for where, identifier, poison in _CYCLE7_EMPTY_CASES],
)
def test_cycle7_empty_pointer_uses_the_effective_resource(
    where: str,
    identifier: str,
    poison: bool,
) -> None:
    """``#`` after crossing or declaring an ``$id`` selects its resource.

    MCP-TOOL-SCHEMA-AUTONOMO: the effective root is the tool schema, not the
    descriptor. The poisoned root is refused with the target reason when the
    ``#`` lands on it; when the ``#`` lands on the valid holder the poisoned
    root is still refused by the whole-schema check that autonomy applies to
    every tool schema.
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012
    from urllib.parse import urljoin

    document = _bare_descriptor()
    mark = {"type": "not-a-type"} if poison else {"type": "integer"}
    holder = {
        "$id": identifier,
        "type": "object",
        "additionalProperties": {"$ref": "#"},
    }
    if where == "$defs":
        root = _cycle7_root(mark)
        root["$defs"]["independent_holder"] = holder
        document["tools"][0]["inputSchema"] = root
    elif where == "nested":
        root = _cycle7_root(mark)
        root["allOf"] = [holder]
        document["tools"][0]["inputSchema"] = root
    elif where == "outputSchema":
        root = _cycle7_root(mark)
        root["properties"] = {"independent_holder": holder}
        document["tools"][0]["outputSchema"] = root
    else:
        root = _cycle7_root(mark)
        root["properties"] = {"independent_holder": holder}
        document["tools"][0]["inputSchema"] = root
    resource = DRAFT202012.create_resource(root)
    registry = Registry().with_resource(_CYCLE7_BASE, resource)
    holder_resource = DRAFT202012.create_resource(holder)
    effective = urljoin(_CYCLE7_BASE, holder_resource.id() or "")
    if effective != _CYCLE7_BASE:
        registry = registry.with_resource(effective, holder_resource)
    target = registry.resolver(_CYCLE7_BASE).in_subresource(holder_resource).lookup("#").contents
    try:
        Draft202012Validator.check_schema(target)
    except (SchemaError, TypeError, ValueError):
        profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
        with pytest.raises(profile.McpProfileError, match="target is not a JSON Schema"):
            _validate(document)
        return
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    if poison:
        with pytest.raises(
            profile.McpProfileError,
            match=r"MCP tool \d+ (?:inputSchema|outputSchema) is not a JSON Schema",
        ):
            _validate(document)
    else:
        _validate(document)


@pytest.mark.parametrize(
    ("slot", "fragment", "available_in", "where"),
    _CYCLE7_DIFFERENTIAL_CASES,
    ids=[
        f"{slot}-{fragment}-{available_in}-{where}"
        for slot, fragment, available_in, where in _CYCLE7_DIFFERENTIAL_CASES
    ],
)
def test_cycle7_pointer_crossing_resource_preserves_resolver(
    slot: str,
    fragment: str,
    available_in: str,
    where: str,
) -> None:
    """A target reached through an intermediate ``$id`` keeps that resource."""
    from referencing import Registry
    from referencing.exceptions import Unresolvable
    from referencing.jsonschema import DRAFT202012

    document, _, entry = _cycle7_pointer_crossing_document(
        slot,
        fragment,
        available_in,
        where,
    )
    tool_root = document["tools"][0][where]
    assert isinstance(tool_root, dict)
    resource = DRAFT202012.create_resource(tool_root)
    uri = resource.id() or "urn:ocor-rem0063-crossing"
    resolver = Registry().with_resource(uri, resource).resolver(uri)
    reached = resolver.lookup(_cycle7_holder_pointer(slot))
    if available_in == "holder":
        assert reached.resolver.lookup(fragment).contents is entry
        _validate(document)
    else:
        with pytest.raises(Unresolvable):
            reached.resolver.lookup(fragment)
        profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
        with pytest.raises(profile.McpProfileError, match="does not resolve"):
            _validate(document)


@pytest.mark.parametrize("slot", _CYCLE7_SLOTS)
def test_cycle7_empty_pointer_after_crossing_resource_ignores_outer_poison(
    slot: str,
) -> None:
    """``#`` after a pointer crossing an ``$id`` uses the nested resource.

    MCP-TOOL-SCHEMA-AUTONOMO: the poisoned sibling lives in the same autonomous
    tool schema, so the whole-schema check refuses it. The library oracle still
    shows that the ``#`` after the crossing selects the nested resource.
    """
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    target = {
        "type": "object",
        "properties": {"value": {"$ref": "#"}},
    }
    box = {"target": target}
    holder = {
        "$id": "child.json",
        "type": "object",
        slot: [box] if slot == "examples" else box,
    }
    root = {
        "$id": _CYCLE7_BASE,
        "type": "object",
        "$defs": {
            "holder": holder,
            "outer_poison": {"type": "not-a-type"},
        },
        "$ref": _cycle7_holder_pointer(slot),
    }
    document["tools"][0]["inputSchema"] = root
    resource = DRAFT202012.create_resource(root)
    reached = Registry().with_resource(_CYCLE7_BASE, resource).resolver(_CYCLE7_BASE).lookup(
        _cycle7_holder_pointer(slot)
    )
    assert reached.resolver.lookup("#").contents is holder
    Draft202012Validator.check_schema(holder)
    with pytest.raises(
        profile.McpProfileError,
        match=r"MCP tool \d+ inputSchema is not a JSON Schema",
    ):
        _validate(document)


def test_cycle7_generated_case_count_is_stable() -> None:
    """The cycle record cites the generated case count and the pinned oracle."""
    import importlib.metadata

    assert importlib.metadata.version("referencing") == "0.37.0"
    assert len(_CYCLE7_EMPTY_CASES) == 32
    assert len(_CYCLE7_DIFFERENTIAL_CASES) == 36
    assert len(_CYCLE7_SLOTS) == 3


# Repair of the cycle-7 preventive review, findings P1-P4. The class is the one
# the manual resource index and the lexical pointer filters left open: resource
# roots come from the current library resolver, an ``$id`` that does not change
# the URI stays on the current resource, numeric tokens are filtered only when
# their resolved parent is an array, and malformed schema identifiers are typed
# profile errors. Oracle: referencing 0.37.0 and RFC 6901.

_CYCLE7_REPAIR_ROOT = "https://example.invalid/root.json"
_CYCLE7_REPAIR_CHILD = "https://example.invalid/child.json"
_CYCLE7_REPAIR_BAD_IDS = ("http://[::1", "http://[zz]/x.json", "//[x")


def _cycle7_repair_pointer(*tokens: str) -> str:
    from urllib.parse import quote

    return "#/" + "/".join(quote(token, safe="~") for token in tokens)


def _cycle7_repair_decoy_descriptor(
    *,
    decoy_part: object,
    real_part: object | None,
) -> dict[str, Any]:
    """MCP-TOOL-SCHEMA-AUTONOMO: decoy and real live in the tool schema."""
    document = _bare_descriptor()
    real: dict[str, Any] = {
        "$id": _CYCLE7_REPAIR_CHILD,
        "type": "object",
        "properties": {"n": {"$ref": "#/$defs/part"}},
    }
    if real_part is not None:
        real["$defs"] = {"part": copy.deepcopy(real_part)}
    root = {
        "$id": _CYCLE7_REPAIR_ROOT,
        "type": "object",
        "$defs": {
            "decoy": {
                "const": {
                    "$id": _CYCLE7_REPAIR_CHILD,
                    "$defs": {"part": copy.deepcopy(decoy_part)},
                }
            },
            "real": real,
        },
        "properties": {"value": {"$ref": "#/$defs/real"}},
    }
    document["tools"][0]["inputSchema"] = root
    return document


def test_cycle7_repair_instance_id_does_not_decide_a_schema_resource() -> None:
    """P1: a decoy ``$id`` in ``const`` cannot make a missing definition resolve."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle7_repair_decoy_descriptor(
        decoy_part={"type": "integer"},
        real_part=None,
    )
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(document)


def test_cycle7_repair_instance_id_does_not_hide_the_real_schema_resource() -> None:
    """P1: a non-schema definition in the decoy is not the real target."""
    document = _cycle7_repair_decoy_descriptor(
        decoy_part=7,
        real_part={"type": "integer"},
    )
    _validate(document)


def test_cycle7_repair_duplicate_keyword_id_follows_the_crawled_resource() -> None:
    """P1: a duplicate ``$id`` does not let the first keyword schema win."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import _WrappedReferencingError
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    root = {
        "$id": _CYCLE7_REPAIR_ROOT,
        "type": "object",
        "$defs": {
            "w": {
                "properties": {
                    "a": {
                        "$id": _CYCLE7_REPAIR_CHILD,
                        "type": "object",
                        "$defs": {"x": {"type": "integer"}},
                        "properties": {"n": {"$ref": "#/$defs/x"}},
                    }
                },
                "not": {"$id": _CYCLE7_REPAIR_CHILD, "type": "object"},
            }
        },
        "$ref": "#/$defs/w/properties/a",
    }
    document["tools"][0]["inputSchema"] = root
    registry = Registry().with_resource(
        _CYCLE7_REPAIR_ROOT,
        DRAFT202012.create_resource(root),
    )
    with pytest.raises(_WrappedReferencingError):
        list(
            Draft202012Validator(
                {
                    "$ref": (
                        _CYCLE7_REPAIR_ROOT
                        + "#/$defs/w/properties/a"
                    )
                },
                registry=registry,
            ).iter_errors({"n": 1})
        )
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(document)


def test_cycle7_repair_instance_reached_id_does_not_create_a_resource() -> None:
    """P1: a nested ``$id`` reached through ``const`` is not registered."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import _WrappedReferencingError
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    root = {
        "$id": _CYCLE7_REPAIR_ROOT,
        "type": "object",
        "$defs": {
            "holder": {
                "const": {
                    "target": {
                        "type": "object",
                        "properties": {
                            "p": {
                                "$id": "inner.json",
                                "$ref": "#/$defs/q",
                                "$defs": {"q": {"type": "integer"}},
                            }
                        },
                    }
                }
            }
        },
        "$ref": "#/$defs/holder/const/target",
    }
    document["tools"][0]["inputSchema"] = root
    registry = Registry().with_resource(
        _CYCLE7_REPAIR_ROOT,
        DRAFT202012.create_resource(root),
    )
    with pytest.raises(_WrappedReferencingError):
        list(
            Draft202012Validator(
                {
                    "$ref": (
                        _CYCLE7_REPAIR_ROOT
                        + "#/$defs/holder/const/target"
                    )
                },
                registry=registry,
            ).iter_errors({"p": 1})
        )
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(document)


@pytest.mark.parametrize("identifier", ("", "#", _CYCLE7_REPAIR_ROOT, "./root.json"))
@pytest.mark.parametrize("where", ("tool", "child"))
def test_cycle7_repair_noop_id_keeps_the_embedded_tool_resource(
    identifier: str,
    where: str,
) -> None:
    """P2: an ``$id`` that joins to the current URI does not start a new resource.

    ``""`` and ``#`` join to the tool schema resource and its ``$defs`` stay
    visible. An absolute or differently-joined identifier starts its own
    resource, which has no ``$defs`` and fails closed
    (MCP-TOOL-SCHEMA-AUTONOMO 2026-11-15). For ``where=tool`` the ``$ref``
    resolves inside the tool schema root for every identifier.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    document["$id"] = _CYCLE7_REPAIR_ROOT
    local = {
        "type": "object",
        "$defs": {"part": {"type": "integer"}},
        "properties": {"value": {"$ref": "#/$defs/part"}},
    }
    if where == "tool":
        local["$id"] = identifier
        body = local
    else:
        body = {
            "type": "object",
            "$defs": local["$defs"],
            "properties": {
                "nested": {"type": "object", "$id": identifier, "$ref": "#/$defs/part"}
            },
        }
    document["tools"][0]["inputSchema"] = body
    if where == "child" and identifier not in ("", "#"):
        with pytest.raises(profile.McpProfileError, match="does not resolve"):
            _validate(document)
    else:
        _validate(document)


@pytest.mark.parametrize("identifier", ("", "#", _CYCLE7_REPAIR_ROOT, "./root.json"))
@pytest.mark.parametrize("where", ("tool", "child"))
def test_cycle7_repair_noop_id_keeps_two_resource_ambiguity(
    identifier: str,
    where: str,
) -> None:
    """P2: two plain-name owners in the same resource stay ambiguous.

    The descriptor is no longer a fallback (MCP-TOOL-SCHEMA-AUTONOMO
    2026-11-15): only owners inside the tool schema tree collide. A
    differently-joined identifier that starts its own resource fails closed
    on the missing anchor instead.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    document["$id"] = _CYCLE7_REPAIR_ROOT
    local = {
        "type": "object",
        "$defs": {
            "a": {"$anchor": "part", "type": "integer"},
            "b": {"$anchor": "part", "type": "string"},
        },
        "properties": {"value": {"$ref": "#part"}},
    }
    if where == "tool":
        local["$id"] = identifier
        body = local
        expected = "ambiguous"
    else:
        body = {
            "type": "object",
            "$defs": local["$defs"],
            "properties": {
                "nested": {"type": "object", "$id": identifier, "$ref": "#part"}
            },
        }
        expected = "ambiguous" if identifier in ("", "#") else "does not resolve"
    document["tools"][0]["inputSchema"] = body
    with pytest.raises(profile.McpProfileError, match=expected):
        _validate(document)


@pytest.mark.parametrize("token", ("01", "007", "-1", "+1", "١"))
@pytest.mark.parametrize("parent", ("$defs", "properties"))
def test_cycle7_repair_numeric_object_members_still_resolve(token: str, parent: str) -> None:
    """P3: canonical-index syntax applies to an array parent, not to object names."""
    document = _bare_descriptor()
    tool_root: dict[str, Any] = {"type": "object"}
    if parent == "$defs":
        tool_root["$defs"] = {token: {"type": "integer"}}
        ref = _cycle7_repair_pointer("$defs", token)
    else:
        tool_root["$defs"] = {
            "holder": {"type": "object", "properties": {token: {"type": "integer"}}}
        }
        ref = _cycle7_repair_pointer("$defs", "holder", "properties", token)
    tool_root["properties"] = {"value": {"$ref": ref}}
    document["tools"][0]["inputSchema"] = tool_root
    _validate(document)


@pytest.mark.parametrize("token", (" 1", "1 ", "1_0", "0_1", "+١", "", "00", "-1"))
def test_cycle7_repair_array_index_must_be_canonical(token: str) -> None:
    """P3: an array parent admits only ``0`` or an ASCII decimal without a leading zero."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _choices_descriptor()
    document["tools"][0]["inputSchema"]["properties"]["name"] = {
        "$ref": _cycle7_repair_pointer("$defs", "choices", "anyOf", token)
    }
    with pytest.raises(profile.McpProfileError):
        _validate(document)


@pytest.mark.parametrize("identifier", _CYCLE7_REPAIR_BAD_IDS)
@pytest.mark.parametrize("where", ("root", "keyword"))
def test_cycle7_repair_malformed_schema_id_is_typed(identifier: str, where: str) -> None:
    """P4: a malformed ``$id`` at a schema position raises McpProfileError.

    MCP-TOOL-SCHEMA-AUTONOMO: both the root position and the keyword position
    are inside the autonomous tool schema.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    if where == "root":
        root: dict[str, Any] = {"$id": identifier, "type": "object"}
    else:
        root = {
            "$id": _CYCLE7_REPAIR_ROOT,
            "type": "object",
            "$defs": {"bad": {"$id": identifier, "type": "object"}},
        }
    document["tools"][0]["inputSchema"] = root
    with pytest.raises(profile.McpProfileError):
        _validate(document)


@pytest.mark.parametrize("identifier", _CYCLE7_REPAIR_BAD_IDS)
@pytest.mark.parametrize("slot", _CYCLE7_SLOTS)
def test_cycle7_repair_malformed_id_in_unreferenced_instance_data_is_accepted(
    identifier: str,
    slot: str,
) -> None:
    """P4: instance data is not a schema resource merely because it has ``$id``.

    MCP-TOOL-SCHEMA-AUTONOMO: the holder sits in the tool schema ``$defs`` and
    its instance data is still not part of the schema tree.
    """
    document = _bare_descriptor()
    box = {"$id": identifier}
    document["tools"][0]["inputSchema"] = {
        "type": "object",
        "$defs": {
            "holder": {slot: [box] if slot == "examples" else box},
        },
    }
    _validate(document)


@pytest.mark.parametrize("identifier", _CYCLE7_REPAIR_BAD_IDS)
@pytest.mark.parametrize("slot", _CYCLE7_SLOTS)
def test_cycle7_repair_malformed_id_in_reached_instance_data_is_typed(
    identifier: str,
    slot: str,
) -> None:
    """P4: once a ``$ref`` reaches it, the malformed ``$id`` is a schema error."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    target = {"$id": identifier, "type": "object"}
    box = {"target": target}
    document["$defs"] = {"holder": {slot: [box] if slot == "examples" else box}}
    suffix = "/0" if slot == "examples" else ""
    document["tools"][0]["inputSchema"] = {
        "type": "object",
        "properties": {
            "value": {"$ref": f"#/$defs/holder/{slot}{suffix}/target"}
        },
    }
    with pytest.raises(profile.McpProfileError):
        _validate(document)


# Cycle 8 — MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15). The generator
# emits one autonomous schema per tool field: every type definition it uses,
# transitively and only those, lives in its own ``$defs``; the descriptor has
# no top-level ``$defs``; a definition name clash is a typed generation error;
# two generations of the same release are byte-identical.


def _cycle8_ref_names(schema: Any, names: set[str]) -> None:
    """Collect ``#/$defs/<name>`` targets of one schema, instance data included."""
    if isinstance(schema, Mapping):
        for key, value in schema.items():
            if key == "$ref" and isinstance(value, str):
                if value.startswith("#/$defs/"):
                    names.add(value[len("#/$defs/") :])
            else:
                _cycle8_ref_names(value, names)
    elif isinstance(schema, (list, tuple)):
        for item in schema:
            _cycle8_ref_names(item, names)


_CYCLE8_ANCHOR_IDS = ("", "#", _CYCLE7_REPAIR_ROOT, "./root.json")
_CYCLE8_ANCHOR_FRAGMENTS = ("#/$defs/private", "#/$defs/pri%76ate")
_CYCLE8_REPEAT_URI = "https://example.invalid/h.json"
_CYCLE8_NON_STRING_IDS = (7, True, 1.5, ["child.json"], {"child": "child.json"})
_CYCLE8_BRIDGE_DIRECTIONS = ("descriptor_to_tool", "tool_to_descriptor")
_CYCLE8_BRIDGE_TARGETS = ("node", "root")
_CYCLE8_BRIDGE_FIELDS = ("inputSchema", "outputSchema")
_CYCLE8_URI_COLLISION_FIELDS = ("inputSchema", "outputSchema")
_CYCLE8_URI_COLLISION_MODES = ("resolvable", "missing")
_CYCLE8_DEPTH_POSITIONS = ("root", "properties", "properties_nested", "allOf", "items")
_CYCLE8_DEPTH_ORDERS = ("defs_first", "props_first")
_CYCLE8_DEPTH_IDS = ("", "#", _CYCLE7_REPAIR_ROOT, "./root.json")
_CYCLE8_DEPTH_PLACEMENTS = ("root", "holder", "both")
_CYCLE8_DEPTH_FRAGMENTS = ("#/$defs/private", "#/$defs/pri%76ate")
_CYCLE8_DEPTH_FIELDS = ("inputSchema", "outputSchema")
_CYCLE8_DEPTH_CASES = tuple(
    (position, order, identifier, placement, fragment, field)
    for position in _CYCLE8_DEPTH_POSITIONS
    for order in _CYCLE8_DEPTH_ORDERS
    for identifier in _CYCLE8_DEPTH_IDS
    for placement in _CYCLE8_DEPTH_PLACEMENTS
    for fragment in _CYCLE8_DEPTH_FRAGMENTS
    for field in _CYCLE8_DEPTH_FIELDS
)


def _cycle8_noop_pointer_descriptor(
    *,
    field: str,
    slot: str,
    identifier: str,
    placement: str,
    fragment: str,
) -> dict[str, Any]:
    """Build the cycle-8 matrix descriptor of the cycle-7 verifier.

    A tool schema reaches ``localHolder`` through ``const``, ``default`` or
    ``examples``, and ``localHolder`` declares an ``$id`` that joins to the
    descriptor base. The inner ``$ref`` then targets ``private``, which lives
    only in the tool schema (``local``), only in the descriptor (``outer``),
    in both (``both``) or in neither (``none``).
    """

    target = {"type": "object", "properties": {"n": {"$ref": fragment}}}
    holder: dict[str, Any] = {"$id": identifier, "type": "object"}
    if slot == "examples":
        holder["examples"] = [{"novel": 0}, {"payload": target}]
        pointer = _cycle7_repair_pointer(
            "$defs", "localHolder", "examples", "1", "payload"
        )
    else:
        holder[slot] = {"payload": target}
        pointer = _cycle7_repair_pointer("$defs", "localHolder", slot, "payload")
    body: dict[str, Any] = {
        "$id": _CYCLE7_REPAIR_ROOT,
        "type": "object",
        "$defs": {"localHolder": holder},
        "$ref": pointer,
    }
    if placement in ("local", "both"):
        body["$defs"]["private"] = {"type": "integer"}
    document = _bare_descriptor()
    document["$id"] = _CYCLE7_REPAIR_ROOT
    document["tools"][0][field] = body
    if placement in ("outer", "both"):
        document["$defs"] = {"private": {"type": "string"}}
    return document


def _cycle8_anchor_descriptor(
    *,
    field: str,
    identifier: str,
    placement: str,
    fragment: str,
) -> dict[str, Any]:
    """A tool schema whose root ``$ref`` is the ``#hold`` anchor.

    ``holder`` declares an ``$id`` that joins to the descriptor base and an
    ``$anchor``. Its inner ``$ref`` targets ``private``, which lives only in
    the tool schema root (``root``), only in ``holder`` (``holder``), in both
    (``both``) or in neither (unused by this matrix).
    """
    holder: dict[str, Any] = {
        "$id": identifier,
        "$anchor": "hold",
        "type": "object",
        "properties": {"n": {"$ref": fragment}},
    }
    if placement in ("holder", "both"):
        holder["$defs"] = {"private": {"type": "integer"}}
    body: dict[str, Any] = {
        "$id": _CYCLE7_REPAIR_ROOT,
        "type": "object",
        "$ref": "#hold",
        "$defs": {"holder": holder},
    }
    if placement in ("root", "both"):
        body["$defs"]["private"] = {"type": "integer"}
    document = _bare_descriptor()
    document["$id"] = _CYCLE7_REPAIR_ROOT
    document["tools"][0][field] = body
    return document


def _cycle8_repeated_id_bodies(
    *,
    placement: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Two schema trees that both declare the nested ``$id`` ``h.json``.

    The first tree reaches its ``h`` through a root ``$ref``; the inner ``$ref``
    targets ``t``, which lives only in the first (``first``) or only in the
    second (``second``) tree.
    """
    inner_first: dict[str, Any] = {
        "$id": _CYCLE8_REPEAT_URI,
        "type": "object",
        "properties": {"n": {"$ref": "#/$defs/t"}},
    }
    if placement == "first":
        inner_first["$defs"] = {"t": {"type": "integer"}}
    inner_second: dict[str, Any] = {
        "$id": _CYCLE8_REPEAT_URI,
        "type": "object",
    }
    if placement == "second":
        inner_second["$defs"] = {"t": {"type": "integer"}}
    first: dict[str, Any] = {
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/h"}},
        "$defs": {"h": inner_first},
    }
    second: dict[str, Any] = {
        "type": "object",
        "$defs": {"h": inner_second},
    }
    return first, second


def _cycle8_bridge_document(
    direction: str,
    field: str,
    target: str,
) -> dict[str, Any]:
    """Descriptor and tool schema each own a distinct definition.

    ``descriptor_to_tool``: the descriptor root carries a ``$ref`` whose
    pointer enters ``tools``, the only place the target exists; ``target``
    selects a pointer onto a tool node or onto the tool schema root.
    ``tool_to_descriptor``: the tool schema ``$ref`` points at a definition
    that lives only on the descriptor root.
    """
    document = _bare_descriptor()
    document["$id"] = _CYCLE7_REPAIR_ROOT
    document["type"] = "object"
    body: dict[str, Any] = {
        "type": "object",
        "properties": {"n": {"$ref": "#/$defs/x"}},
    }
    document["tools"][0][field] = body
    # ``x`` lives only on the descriptor root, exactly the bridge of the
    # prereview probe G1/G2/G3: the tool reference resolves only when the
    # descriptor resolver leaks into the tool tree.
    document["$defs"] = {"x": {"type": "integer"}}
    if direction == "descriptor_to_tool":
        pointer = (
            f"#/tools/0/{field}"
            if target == "root"
            else f"#/tools/0/{field}/properties/n"
        )
        document["$defs"]["d"] = {"$ref": pointer}
    return document


def _cycle8_uri_collision_document(field: str, mode: str) -> dict[str, Any]:
    """An ``$id``-less tool schema whose nested ``$id`` spells the synthetic URI."""
    holder: dict[str, Any] = {
        "$id": f"urn:ocor:embedded-tool:0:{field}",
        "type": "object",
        "properties": {"n": {"$ref": "#/$defs/t"}},
    }
    if mode == "resolvable":
        holder["$defs"] = {"t": {"type": "integer"}}
    body: dict[str, Any] = {
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/h"}},
        "$defs": {"h": holder},
    }
    document = _bare_descriptor()
    document["$id"] = _CYCLE7_REPAIR_ROOT
    document["tools"][0][field] = body
    return document


def _cycle8_deep_holder() -> dict[str, Any]:
    """The holder for the deep/lateral anchor matrix."""
    return {
        "$anchor": "deep",
        "type": "object",
        "properties": {"n": {"$ref": "#/$defs/x"}},
    }


def _cycle8_depth_members(
    position: str,
    identifier: str,
    placement: str,
    fragment: str,
) -> tuple[dict[str, Any], dict[str, Any], object]:
    """Build the keyword members, the definitions and the probe instance."""
    holder: dict[str, Any] = {
        "$id": identifier,
        "$anchor": "hold",
        "type": "object",
        "properties": {"n": {"$ref": fragment}},
    }
    if placement in ("holder", "both"):
        holder["$defs"] = {"private": {"type": "integer"}}
    definitions: dict[str, Any] = {"holder": holder}
    if placement in ("root", "both"):
        definitions["private"] = {"type": "integer"}
    if position == "root":
        members = {"properties": {"a": {"$ref": "#hold"}}}
        sample: object = {"a": {"n": 11}}
    elif position == "properties":
        members = {
            "properties": {"w": {"type": "object", "properties": {"a": {"$ref": "#hold"}}}}
        }
        sample = {"w": {"a": {"n": 11}}}
    elif position == "properties_nested":
        members = {
            "properties": {
                "w": {
                    "type": "object",
                    "properties": {
                        "inner": {
                            "type": "object",
                            "properties": {"a": {"$ref": "#hold"}},
                        }
                    },
                }
            }
        }
        sample = {"w": {"inner": {"a": {"n": 11}}}}
    elif position == "allOf":
        members = {"allOf": [{"$ref": "#hold"}]}
        sample = {"n": 11}
    else:
        members = {
            "properties": {"w": {"type": "array", "items": {"$ref": "#hold"}}}
        }
        sample = {"w": [{"n": 11}]}
    return members, definitions, sample


@pytest.mark.parametrize("field", ("inputSchema", "outputSchema"))
@pytest.mark.parametrize("slot", ("const", "default", "examples"))
@pytest.mark.parametrize("identifier", ("", "#", _CYCLE7_REPAIR_ROOT, "./root.json"))
@pytest.mark.parametrize("fragment", ("#/$defs/private", "#/$defs/pri%76ate"))
def test_cycle8_noop_id_local_target_resolves_through_instance_data(
    field: str,
    slot: str,
    identifier: str,
    fragment: str,
) -> None:
    """The inner ``$ref`` resolves the tool schema's own ``private``.

    The no-op ``$id`` does not detach the embedded resource, so the local
    definition wins and the library evaluator selects the integer, accepting
    ``{"n": 11}`` and refusing ``{"n": "bad"}``.
    """
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    document = _cycle8_noop_pointer_descriptor(
        field=field,
        slot=slot,
        identifier=identifier,
        placement="local",
        fragment=fragment,
    )
    body = document["tools"][0][field]
    local_registry = Registry().with_resource(
        _CYCLE7_REPAIR_ROOT,
        DRAFT202012.create_resource(body),
    )
    evaluator = Draft202012Validator(
        body,
        registry=local_registry,
        _resolver=local_registry.resolver(_CYCLE7_REPAIR_ROOT),
    )
    assert evaluator.is_valid({"n": 11})
    assert not evaluator.is_valid({"n": "bad"})
    _validate(document)


@pytest.mark.parametrize("slot", ("const", "default", "examples"))
@pytest.mark.parametrize("identifier", ("", "#", _CYCLE7_REPAIR_ROOT, "./root.json"))
def test_cycle8_noop_id_missing_target_is_rejected_for_the_right_reason(
    slot: str,
    identifier: str,
) -> None:
    """A target present in neither resource fails with the resolution reason."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(
            _cycle8_noop_pointer_descriptor(
                field="inputSchema",
                slot=slot,
                identifier=identifier,
                placement="none",
                fragment="#/$defs/private",
            )
        )


@pytest.mark.parametrize("field", ("inputSchema", "outputSchema"))
@pytest.mark.parametrize("identifier", _CYCLE8_ANCHOR_IDS)
@pytest.mark.parametrize("placement", ("root", "holder", "both"))
@pytest.mark.parametrize("fragment", _CYCLE8_ANCHOR_FRAGMENTS)
def test_cycle8_anchor_ref_follows_the_referencing_crawl(
    field: str,
    identifier: str,
    placement: str,
    fragment: str,
) -> None:
    """The anchor path keeps the crawl the library triggers, pointer included."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import _WrappedReferencingError
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle8_anchor_descriptor(
        field=field,
        identifier=identifier,
        placement=placement,
        fragment=fragment,
    )
    body = document["tools"][0][field]
    registry = Registry().with_resource(
        _CYCLE7_REPAIR_ROOT,
        DRAFT202012.create_resource(body),
    )
    validator = Draft202012Validator(
        body,
        registry=registry,
        _resolver=registry.resolver(_CYCLE7_REPAIR_ROOT),
    )
    if placement == "root":
        with pytest.raises(_WrappedReferencingError):
            validator.is_valid({"n": 11})
        with pytest.raises(profile.McpProfileError, match="does not resolve"):
            _validate(document)
    else:
        assert validator.is_valid({"n": 11})
        assert not validator.is_valid({"n": "bad"})
        _validate(document)


@pytest.mark.parametrize("member_order", ("a_first", "b_first"))
@pytest.mark.parametrize("defs_order", ("defs_first", "props_first"))
def test_cycle8_pointer_and_anchor_paths_are_each_resolved(
    defs_order: str,
    member_order: str,
) -> None:
    """P1: every path a reference reaches resolves, in any member order.

    The same ``$id``-less holder is reached by a JSON Pointer and by an
    anchor. The pointer path keeps the tree registry (the pointer does not
    start a subresource), where ``#/$defs/x`` does not resolve; the anchor
    path keeps the crawl state referencing 0.37.0 returns, where the holder
    owns the base URI and the fragment resolves. The library rejects the
    pointer path (``_WrappedReferencingError``), so the profile must reject
    the descriptor with the typed resolution error, and neither the order
    of the ``$defs`` member nor the order of the two properties may change
    the outcome (the pre-fix profile accepted ``b`` before ``a`` with
    ``$defs`` last, because the first context to reach the holder won).
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import _WrappedReferencingError
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    holder: dict[str, Any] = {
        "$id": "#",
        "$anchor": "hold",
        "type": "object",
        "properties": {"n": {"$ref": "#/$defs/x"}},
        "$defs": {"x": {"type": "integer"}},
    }
    body: dict[str, Any] = {"type": "object"}
    pointer_member = ("a", {"$ref": "#/$defs/h"})
    anchor_member = ("b", {"$ref": "#hold"})
    members = (
        [pointer_member, anchor_member]
        if member_order == "a_first"
        else [anchor_member, pointer_member]
    )
    properties = dict(members)
    if defs_order == "defs_first":
        body["$defs"] = {"h": holder}
        body["properties"] = properties
    else:
        body["properties"] = properties
        body["$defs"] = {"h": holder}
    document = _bare_descriptor()
    document["$id"] = _CYCLE7_REPAIR_ROOT
    document["tools"][0]["inputSchema"] = body
    registry = Registry().with_resource(
        _CYCLE7_REPAIR_ROOT,
        DRAFT202012.create_resource(body),
    )
    validator = Draft202012Validator(
        body,
        registry=registry,
        _resolver=registry.resolver(_CYCLE7_REPAIR_ROOT),
    )
    with pytest.raises(_WrappedReferencingError):
        validator.is_valid({"a": {"n": 1}})
    assert validator.is_valid({"b": {"n": 1}})
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(document)


@pytest.mark.parametrize("arrangement", ("two_tools", "in_out"))
@pytest.mark.parametrize("placement", ("first", "second"))
def test_cycle8_repeated_nested_id_resolves_in_the_current_tree(
    arrangement: str,
    placement: str,
) -> None:
    """Two trees sharing one nested ``$id`` stay separate resources."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import _WrappedReferencingError
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    first, second = _cycle8_repeated_id_bodies(placement=placement)
    document = _bare_descriptor()
    document["$id"] = _CYCLE7_REPAIR_ROOT
    if arrangement == "two_tools":
        document["tools"] = [
            {"name": "t0", "inputSchema": first, "outputSchema": {"type": "object"}},
            {"name": "t1", "inputSchema": second, "outputSchema": {"type": "object"}},
        ]
    else:
        document["tools"] = [
            {"name": "t0", "inputSchema": first, "outputSchema": second},
        ]
    registry = Registry().with_resource(
        _CYCLE7_REPAIR_ROOT,
        DRAFT202012.create_resource(first),
    )
    validator = Draft202012Validator(
        first,
        registry=registry,
        _resolver=registry.resolver(_CYCLE7_REPAIR_ROOT),
    )
    if placement == "first":
        assert validator.is_valid({"a": {"n": 11}})
        assert not validator.is_valid({"a": {"n": "bad"}})
        _validate(document)
    else:
        with pytest.raises(_WrappedReferencingError):
            list(validator.iter_errors({"a": {"n": 11}}))
        with pytest.raises(profile.McpProfileError, match="does not resolve"):
            _validate(document)


@pytest.mark.parametrize("placement", ("first", "second"))
def test_cycle8_repeated_root_id_resolves_in_the_current_tree(
    placement: str,
) -> None:
    """Two tool roots declaring the same ``$id`` stay separate resources."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import _WrappedReferencingError
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    first: dict[str, Any] = {
        "$id": _CYCLE8_REPEAT_URI,
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/t"}},
    }
    second: dict[str, Any] = {
        "$id": _CYCLE8_REPEAT_URI,
        "type": "object",
    }
    if placement == "first":
        first["$defs"] = {"t": {"type": "integer"}}
    else:
        second["$defs"] = {"t": {"type": "integer"}}
    document = _bare_descriptor()
    document["$id"] = _CYCLE7_REPAIR_ROOT
    document["tools"] = [
        {"name": "t0", "inputSchema": first, "outputSchema": {"type": "object"}},
        {"name": "t1", "inputSchema": second, "outputSchema": {"type": "object"}},
    ]
    registry = Registry().with_resource(
        _CYCLE7_REPAIR_ROOT,
        DRAFT202012.create_resource(first),
    )
    validator = Draft202012Validator(
        first,
        registry=registry,
        _resolver=registry.resolver(_CYCLE7_REPAIR_ROOT),
    )
    if placement == "first":
        assert validator.is_valid({"a": 11})
        assert not validator.is_valid({"a": "bad"})
        _validate(document)
    else:
        with pytest.raises(_WrappedReferencingError):
            list(validator.iter_errors({"a": 11}))
        with pytest.raises(profile.McpProfileError, match="does not resolve"):
            _validate(document)


@pytest.mark.parametrize("field", _CYCLE8_URI_COLLISION_FIELDS)
@pytest.mark.parametrize("mode", _CYCLE8_URI_COLLISION_MODES)
def test_cycle8_synthetic_uri_avoids_declared_id_collisions(
    field: str,
    mode: str,
) -> None:
    """Both modes refuse the fixed base before lookup.

    REM-0063-CYCLE10-ORACLE-CONFLICT B1. The name, the field and mode
    parameters and the four cases stay. The fixture is unchanged. Old
    expectation: mode ``resolvable`` was accepted because a suffix avoided
    the collision, and the other mode failed with ``does not resolve``.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle8_uri_collision_document(field=field, mode=mode)
    with pytest.raises(profile.McpProfileError, match=r"collid"):
        _validate(document)


@pytest.mark.parametrize("defs_order", ("wrap_first", "x_first"))
def test_cycle8_deep_lateral_anchor_resolves_in_any_defs_order(
    defs_order: str,
) -> None:
    """A deep anchor target resolves its own pointer in any ``$defs`` order.

    P3 of the prereview: depth and member order do not change the outcome.
    The anchor ``deep`` sits two levels under the root, inside the same
    resource, and the referenced definition ``x`` lives beside the wrapper.
    """
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    holder = _cycle8_deep_holder()
    definitions = {
        "wrap": {"type": "object", "$defs": {"h": holder}},
        "x": {"type": "integer"},
    }
    if defs_order == "x_first":
        definitions = dict(reversed(list(definitions.items())))
    body: dict[str, Any] = {
        "$id": _CYCLE7_REPAIR_ROOT,
        "type": "object",
        "properties": {"a": {"$ref": "#deep"}},
        "$defs": definitions,
    }
    document = _bare_descriptor()
    document["tools"][0]["inputSchema"] = body
    registry = Registry().with_resource(
        _CYCLE7_REPAIR_ROOT,
        DRAFT202012.create_resource(body),
    )
    validator = Draft202012Validator(
        body,
        registry=registry,
        _resolver=registry.resolver(_CYCLE7_REPAIR_ROOT),
    )
    assert validator.is_valid({"a": {"n": 11}})
    assert not validator.is_valid({"a": {"n": "bad"}})
    _validate(document)


@pytest.mark.parametrize("member_order", ("pointer_first", "anchor_first"))
def test_cycle8_deep_pointer_and_anchor_paths_keep_the_library_outcome(
    member_order: str,
) -> None:
    """A deep pointer path and an anchor path reach the same holder.

    The pointer path keeps the tree registry, where ``#/$defs/x`` does not
    resolve; the anchor path would keep the crawl state. The library
    rejects the descriptor because the pointer path exists, and the
    profile must too, in any member order (P3 of the prereview).
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import _WrappedReferencingError
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    holder = _cycle8_deep_holder()
    holder["$id"] = "#"
    holder["$defs"] = {"x": {"type": "integer"}}
    pointer_member = ("p", {"$ref": "#/$defs/wrap/h"})
    anchor_member = ("a", {"$ref": "#deep"})
    members = (
        [pointer_member, anchor_member]
        if member_order == "pointer_first"
        else [anchor_member, pointer_member]
    )
    body: dict[str, Any] = {
        "$id": _CYCLE7_REPAIR_ROOT,
        "type": "object",
        "properties": dict(members),
        "$defs": {"wrap": {"type": "object", "$defs": {"h": holder}}},
    }
    document = _bare_descriptor()
    document["tools"][0]["inputSchema"] = body
    registry = Registry().with_resource(
        _CYCLE7_REPAIR_ROOT,
        DRAFT202012.create_resource(body),
    )
    validator = Draft202012Validator(
        body,
        registry=registry,
        _resolver=registry.resolver(_CYCLE7_REPAIR_ROOT),
    )
    with pytest.raises(_WrappedReferencingError):
        list(validator.iter_errors({"p": {"n": 11}, "a": {"n": 11}}))
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(document)


@pytest.mark.parametrize(
    ("position", "order", "identifier", "placement", "fragment", "field"),
    _CYCLE8_DEPTH_CASES,
    ids=[
        f"{position}-{order}-{identifier}-{placement}-{fragment}-{field}"
        for position, order, identifier, placement, fragment, field in _CYCLE8_DEPTH_CASES
    ],
)
def test_cycle8_depth_and_order_differential_matches_the_library(
    position: str,
    order: str,
    identifier: str,
    placement: str,
    fragment: str,
    field: str,
) -> None:
    """Generated differential: anchor depth and member order never diverge.

    P3 of the prereview OCOR-DEV-REM-0063-d2e922ecb7c3-pre. The ``#hold``
    entry point sits at the root, one level down, two levels down, inside
    ``allOf`` or inside ``items``, with ``$defs`` before or after the
    keyword that carries it; the holder declares each no-op ``$id`` and
    ``private`` lives in the root, in the holder or in both. referencing
    0.37.0 resolves or rejects the schema alone, and the profile must
    follow it in every case. RED on the pre-fix head: 80 cases accepted by
    the library are rejected by the profile.
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import _WrappedReferencingError
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    members, definitions, sample = _cycle8_depth_members(
        position=position,
        identifier=identifier,
        placement=placement,
        fragment=fragment,
    )
    body: dict[str, Any] = {"$id": _CYCLE7_REPAIR_ROOT, "type": "object"}
    if order == "defs_first":
        body["$defs"] = definitions
        body.update(members)
    else:
        body.update(members)
        body["$defs"] = definitions
    document = _bare_descriptor()
    document["tools"][0][field] = body
    registry = Registry().with_resource(
        _CYCLE7_REPAIR_ROOT,
        DRAFT202012.create_resource(body),
    )
    validator = Draft202012Validator(
        body,
        registry=registry,
        _resolver=registry.resolver(_CYCLE7_REPAIR_ROOT),
    )
    try:
        list(validator.iter_errors(sample))
        oracle_resolves = True
    except _WrappedReferencingError:
        oracle_resolves = False
    try:
        _validate(document)
    except profile.McpProfileError as exc:
        assert not oracle_resolves, (
            position,
            order,
            identifier,
            placement,
            fragment,
            field,
            exc,
        )
        assert "does not resolve" in str(exc)
    else:
        assert oracle_resolves, (
            position,
            order,
            identifier,
            placement,
            fragment,
            field,
        )


@pytest.mark.parametrize("bad_id", _CYCLE8_NON_STRING_IDS)
@pytest.mark.parametrize(
    "where",
    ("descriptor_root", "descriptor_defs", "tool_root", "tool_defs"),
)
def test_cycle8_non_string_schema_id_is_typed(
    bad_id: object,
    where: str,
) -> None:
    """P3: a non-string ``$id`` at a schema position is a typed rejection.

    The pinned crawl raises on a non-string ``$id`` and the profile must
    translate it to ``MCP schema resource index is not resolvable``; a raw
    library exception must never escape the module, and the failure must
    not silently treat the identifier as absent. The ``descriptor_defs``
    placement plants the bad ``$id`` under the descriptor ``$defs``:
    MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15) refuses every
    descriptor with top-level ``$defs`` before resolution, so that
    placement now expects the typed top-level refusal (old expectation:
    ``resource index is not resolvable``). The ``descriptor_root``
    placement is no longer a schema position: the descriptor is not a
    schema tree, so its root ``$id`` is not inspected and the descriptor
    is accepted (old expectation: typed ``resource index is not
    resolvable``).
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _bare_descriptor()
    if where == "descriptor_root":
        document["$id"] = bad_id
        _validate(document)
        return
    elif where == "descriptor_defs":
        document["$id"] = _CYCLE7_REPAIR_ROOT
        document["$defs"] = {"bad": {"$id": bad_id, "type": "object"}}
        match = r"top-level \$defs"
    elif where == "tool_root":
        document["tools"][0]["inputSchema"] = {
            "$id": bad_id,
            "type": "object",
        }
        match = "resource index is not resolvable"
    else:
        document["tools"][0]["inputSchema"] = {
            "type": "object",
            "$defs": {"bad": {"$id": bad_id, "type": "object"}},
        }
        match = "resource index is not resolvable"
    with pytest.raises(profile.McpProfileError, match=match):
        _validate(document)


@pytest.mark.parametrize("field", ("inputSchema", "outputSchema"))
@pytest.mark.parametrize("slot", ("const", "default", "examples"))
@pytest.mark.parametrize("identifier", ("", "#", _CYCLE7_REPAIR_ROOT, "./root.json"))
@pytest.mark.parametrize("fragment", ("#/$defs/private", "#/$defs/pri%76ate"))
def test_cycle8_noop_id_outer_target_is_refused_as_top_level_defs(
    field: str,
    slot: str,
    identifier: str,
    fragment: str,
) -> None:
    """The ``outer`` placement is refused as top-level ``$defs``, before any fallback.

    MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15): the descriptor must
    not declare top-level ``$defs``, so the placement where ``private``
    lives only in the descriptor is refused with the typed top-level error
    (old expectation: the resolution reason ``does not resolve``). A miss
    in the tool schema can never leak into another tree.
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    with pytest.raises(profile.McpProfileError, match=r"top-level \$defs"):
        _validate(
            _cycle8_noop_pointer_descriptor(
                field=field,
                slot=slot,
                identifier=identifier,
                placement="outer",
                fragment=fragment,
            )
        )


@pytest.mark.parametrize("field", ("inputSchema", "outputSchema"))
@pytest.mark.parametrize("slot", ("const", "default", "examples"))
@pytest.mark.parametrize("identifier", ("", "#", _CYCLE7_REPAIR_ROOT, "./root.json"))
@pytest.mark.parametrize("fragment", ("#/$defs/private", "#/$defs/pri%76ate"))
def test_cycle8_noop_id_two_targets_are_refused_as_top_level_defs(
    field: str,
    slot: str,
    identifier: str,
    fragment: str,
) -> None:
    """The ``both`` placement is refused as top-level ``$defs``.

    MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15): a descriptor that
    declares top-level ``$defs`` is refused, so the former acceptance —
    the tool schema's own ``private`` winning over the descriptor copy —
    becomes the typed top-level refusal (old expectation: accepted).
    """
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    with pytest.raises(profile.McpProfileError, match=r"top-level \$defs"):
        _validate(
            _cycle8_noop_pointer_descriptor(
                field=field,
                slot=slot,
                identifier=identifier,
                placement="both",
                fragment=fragment,
            )
        )


@pytest.mark.parametrize("placement", ("first", "second"))
def test_cycle8_repeated_nested_descriptor_defs_are_refused_as_top_level_defs(
    placement: str,
) -> None:
    """Descriptor ``$defs`` with the repeated ``$id`` are refused, not ignored.

    MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15): a descriptor with
    top-level ``$defs`` is refused before resolution, so both placements
    now expect the typed top-level refusal (old expectation: acceptance
    for ``first``, ``does not resolve`` for ``second``). The resource
    independence demonstrated by the library oracle is unchanged.
    """
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    first, second = _cycle8_repeated_id_bodies(placement=placement)
    first.pop("properties", None)
    document = _bare_descriptor()
    document["$id"] = _CYCLE7_REPAIR_ROOT
    document["$defs"] = {"h": second["$defs"]["h"]}
    document["tools"] = [
        {"name": "t0", "inputSchema": first, "outputSchema": {"type": "object"}},
    ]
    registry = Registry().with_resource(
        _CYCLE7_REPAIR_ROOT,
        DRAFT202012.create_resource(first),
    )
    entered = registry.resolver(_CYCLE7_REPAIR_ROOT).lookup("#/$defs/h")
    if placement == "first":
        target = entered.resolver.lookup("#/$defs/t").contents
        Draft202012Validator.check_schema(target)
    else:
        with pytest.raises(Exception):
            entered.resolver.lookup("#/$defs/t")
    with pytest.raises(profile.McpProfileError, match=r"top-level \$defs"):
        _validate(document)


@pytest.mark.parametrize("direction", _CYCLE8_BRIDGE_DIRECTIONS)
@pytest.mark.parametrize("target", _CYCLE8_BRIDGE_TARGETS)
@pytest.mark.parametrize("field", _CYCLE8_BRIDGE_FIELDS)
def test_cycle8_descriptor_tool_bridge_is_rejected_in_both_directions(
    direction: str,
    field: str,
    target: str,
) -> None:
    """No ``$ref`` crosses the boundary between descriptor and tool schema.

    MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15): the descriptor and every tool
    schema are autonomous resources; a descriptor ``$ref`` whose pointer
    enters a tool node does not resolve, and a tool ``$ref`` never sees
    descriptor definitions. MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE
    (2026-11-15): the descriptor planted by this test declares top-level
    ``$defs``, so the profile now refuses it with the typed top-level
    error before resolution (old expectation: ``does not resolve``). The
    library oracle still rejects both directions on the resource taken
    alone.
    """
    from referencing import Registry
    from referencing.exceptions import Unresolvable
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _cycle8_bridge_document(
        direction=direction,
        field=field,
        target=target,
    )
    if direction == "descriptor_to_tool":
        pointer = (
            f"#/tools/0/{field}"
            if target == "root"
            else f"#/tools/0/{field}/properties/n"
        )
        pruned = {key: value for key, value in document.items() if key != "tools"}
        registry = Registry().with_resource(
            _CYCLE7_REPAIR_ROOT,
            DRAFT202012.create_resource(pruned),
        )
        with pytest.raises(Unresolvable):
            registry.resolver(_CYCLE7_REPAIR_ROOT).lookup(pointer)
    else:
        body = document["tools"][0][field]
        registry = Registry().with_resource(
            _CYCLE7_REPAIR_ROOT,
            DRAFT202012.create_resource(body),
        )
        with pytest.raises(Unresolvable):
            registry.resolver(_CYCLE7_REPAIR_ROOT).lookup("#/$defs/x")
    with pytest.raises(profile.McpProfileError, match=r"top-level \$defs"):
        _validate(document)


def test_cycle8_generated_descriptor_has_no_top_level_defs_and_passes_the_profile() -> None:
    """The generated descriptor passes the profile and declares no top-level ``$defs``."""
    document, _ = _descriptor()
    assert "$defs" not in document
    _validate(document)


def test_cycle8_each_generated_tool_schema_is_standalone_and_closed() -> None:
    """Every tool schema is valid alone, refs resolve alone, defs are the closure."""
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    document, _ = _descriptor()
    for tool in document["tools"]:
        for field in ("inputSchema", "outputSchema"):
            schema = tool.get(field)
            if not isinstance(schema, Mapping):
                continue
            Draft202012Validator.check_schema(schema)
            names: set[str] = set()
            _cycle8_ref_names(schema, names)
            assert set(schema.get("$defs", {})) == names
            declared = schema.get("$id")
            root_uri = declared if isinstance(declared, str) and declared else "urn:ocor:cycle8:root"
            resource = DRAFT202012.create_resource(schema)
            registry = Registry().with_resource(root_uri, resource)
            resolver = registry.resolver(root_uri)
            for name in sorted(names):
                target = resolver.lookup(f"#/$defs/{name}")
                Draft202012Validator.check_schema(target.contents)


def test_cycle8_two_generations_of_one_release_are_byte_identical() -> None:
    """Two renders of the same release are byte for byte identical."""
    _, first = _descriptor()
    _, second = _descriptor()
    assert first == second
    assert hashlib.sha256(first).digest() == hashlib.sha256(second).digest()


def test_cycle8_a_definition_name_clash_is_a_typed_generation_error() -> None:
    """A contract ``$defs`` clashing with an included type fails with C1Error."""
    documents = _with_contracts(
        _contract(
            "urn:ocor:contract:clash",
            input_schema={
                "type": "object",
                "properties": {"vessel": {"$ref": "urn:ocor:type:vessel"}},
                "$defs": {"urn.ocor.type.vessel": {"type": "string"}},
            },
        )
    )
    fleet = _fleet()
    with pytest.raises(C1Error, match="MCP definition name clash"):
        fleet.c1("codegen").IrArtifactGenerator().render(
            fleet.compiler().build(fleet.oac_request(documents=documents))
        )


def test_cycle8_a_descriptor_with_top_level_defs_is_refused() -> None:
    """A descriptor that declares top-level ``$defs`` is a typed refusal."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document, _ = _descriptor()
    tampered = dict(document)
    tampered["$defs"] = {"anything": {"type": "integer"}}
    with pytest.raises(profile.McpProfileError, match=r"top-level \$defs"):
        _validate(tampered)


# Cycle 9 — VF-001 of OCOR-DEV-REM-0063-875169cae96f-8. Each JSON Schema
# resource receives the closure of the ``#/$defs`` references that resolve
# against that resource. A nested ``$id`` does not see the parent closure,
# and a definition nobody references is not emitted.


_CYCLE9_CHILD = "https://verifier.invalid/child.json"
_CYCLE9_FIELDS = ("inputSchema", "outputSchema")
_CYCLE9_SLOTS = ("properties", "allOf", "anyOf", "oneOf")
_CYCLE9_STATUS = "urn:ocor:type:vessel-status"
_CYCLE9_STATUS_NAME = "urn.ocor.type.vessel-status"
_CYCLE9_VESSEL = "urn:ocor:type:vessel"
_CYCLE9_HULL = "urn:ocor:type:hull"
_CYCLE9_PROPERTY = "urn:ocor:property:vessel-name"


def _cycle9_child(ref: str, *, nested_id: str | None) -> dict[str, Any]:
    child: dict[str, Any] = {
        "type": "object",
        "properties": {"status": {"$ref": ref}},
    }
    if nested_id is not None:
        child["$id"] = nested_id
    return child


def _cycle9_schema(slot: str, ref: str, *, nested_id: str | None) -> dict[str, Any]:
    child = _cycle9_child(ref, nested_id=nested_id)
    if slot == "properties":
        return {"type": "object", "properties": {"nested": child}}
    return {"type": "object", slot: [child]}


def _cycle9_instance(slot: str, status: str, *, nested: bool) -> dict[str, Any]:
    if slot == "properties":
        return {"nested": {"status": status}}
    if nested:
        return {"status": status}
    return {"status": status}


def _cycle9_render(field: str, schema: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if field == "inputSchema":
        contract = _contract("urn:ocor:contract:cycle9-closure", input_schema=schema)
    else:
        contract = _contract(
            "urn:ocor:contract:cycle9-closure",
            input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            output_schema=schema,
        )
    document, first = _descriptor(_with_contracts(contract))
    _, second = _descriptor(_with_contracts(contract))
    assert first == second
    tool = next(item for item in document["tools"] if item["name"] == "cycle9-closure")
    body = tool[field]
    if not isinstance(body, dict):
        raise AssertionError("rendered tool schema is not an object")
    return document, body


def _cycle9_find(schema: Mapping[str, Any], identifier: str) -> dict[str, Any] | None:
    found: dict[str, Any] | None = None

    def visit(node: object) -> None:
        nonlocal found
        if found is not None:
            return
        if isinstance(node, Mapping):
            if node.get("$id") == identifier and isinstance(node, dict):
                found = node
                return
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(schema)
    return found


def _cycle9_enum_oracle(schema: Mapping[str, Any], uri: str, instance: Mapping[str, Any], *, bad: Mapping[str, Any]) -> None:
    """referencing 0.37.0 and Draft202012Validator on one autonomous schema."""
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    resource = DRAFT202012.create_resource(dict(schema))
    registry = Registry().with_resource(uri, resource)
    resolved = registry.resolver(uri).lookup(f"#/$defs/{_CYCLE9_STATUS_NAME}")
    assert resolved.contents["enum"] == ["ACTIVE", "LAID_UP"]
    validator = Draft202012Validator(dict(schema), registry=registry)
    assert validator.is_valid(dict(instance))
    assert not validator.is_valid(dict(bad))


@pytest.mark.parametrize("field", _CYCLE9_FIELDS)
@pytest.mark.parametrize("slot", _CYCLE9_SLOTS)
def test_cycle9_nested_id_closure_is_placed_on_that_resource(field: str, slot: str) -> None:
    """A nested ``$id`` keeps the closure of the references it alone resolves.

    Oracle: referencing 0.37.0 plus Draft202012Validator on the child
    resource. Eight cases (2 fields x 4 slots). The parent resource does
    not receive those definitions. A wrong enum is rejected and the
    governed value is accepted.
    """
    from referencing.exceptions import Unresolvable

    document, body = _cycle9_render(
        field,
        _cycle9_schema(slot, _CYCLE9_STATUS, nested_id=_CYCLE9_CHILD),
    )
    child = _cycle9_find(body, _CYCLE9_CHILD)
    assert child is not None
    assert set(child.get("$defs", {})) == {_CYCLE9_STATUS_NAME}
    assert _CYCLE9_STATUS_NAME not in body.get("$defs", {})
    _validate(document)
    _cycle9_enum_oracle(
        child,
        _CYCLE9_CHILD,
        {"status": "ACTIVE"},
        bad={"status": "WRONG"},
    )
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    root_uri = body["$id"] if isinstance(body.get("$id"), str) and body.get("$id") else "urn:ocor:probe:cycle9"
    root = Registry().with_resource(root_uri, DRAFT202012.create_resource(body))
    with pytest.raises(Unresolvable):
        root.resolver(root_uri).lookup(f"#/$defs/{_CYCLE9_STATUS_NAME}")


@pytest.mark.parametrize("field", _CYCLE9_FIELDS)
@pytest.mark.parametrize("slot", _CYCLE9_SLOTS)
def test_cycle9_plain_twin_keeps_the_closure_on_the_root(field: str, slot: str) -> None:
    """The same schema without a nested ``$id`` keeps the closure on the root.

    Eight twin cases. The profile accepts the descriptor. The wrong enum
    is rejected on the rendered schema and the governed value is accepted.
    """
    schema = _cycle9_schema(slot, _CYCLE9_STATUS, nested_id=None)
    document, body = _cycle9_render(field, schema)
    assert set(body.get("$defs", {})) == {_CYCLE9_STATUS_NAME}
    if slot == "properties":
        assert "$defs" not in body["properties"]["nested"]
    else:
        assert "$defs" not in body[slot][0]
    _validate(document)
    good = _cycle9_instance(slot, "ACTIVE", nested=False)
    bad = _cycle9_instance(slot, "WRONG", nested=False)
    uri = body["$id"] if isinstance(body.get("$id"), str) and body.get("$id") else "urn:ocor:probe:cycle9-plain"
    _cycle9_enum_oracle(body, uri, good, bad=bad)


@pytest.mark.parametrize("field", _CYCLE9_FIELDS)
def test_cycle9_nested_vessel_closure_includes_only_the_reachable_types(field: str) -> None:
    """A vessel reference inside a nested resource carries its own closure."""
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    child_schema = {
        "$id": _CYCLE9_CHILD,
        "type": "object",
        "properties": {"vessel": {"$ref": _CYCLE9_VESSEL}},
    }
    document, body = _cycle9_render(
        field,
        {"type": "object", "properties": {"nested": child_schema}},
    )
    child = _cycle9_find(body, _CYCLE9_CHILD)
    assert child is not None
    names = set(child.get("$defs", {}))
    assert {
        "urn.ocor.type.vessel",
        "urn.ocor.type.vessel-status",
        "urn.ocor.type.hull",
    } <= names
    assert names.isdisjoint(body.get("$defs", {}))
    _validate(document)
    registry = Registry().with_resource(
        _CYCLE9_CHILD,
        DRAFT202012.create_resource(child),
    )
    resolver = registry.resolver(_CYCLE9_CHILD)
    for name in (
        "urn.ocor.type.vessel",
        "urn.ocor.type.vessel-status",
        "urn.ocor.type.hull",
    ):
        target = resolver.lookup(f"#/$defs/{name}")
        assert isinstance(target.contents, dict)


@pytest.mark.parametrize("field", _CYCLE9_FIELDS)
def test_cycle9_root_and_nested_resources_keep_separate_closures(field: str) -> None:
    """A root reference and a nested reference do not share one closure."""
    schema = {
        "type": "object",
        "properties": {
            "status": {"$ref": _CYCLE9_STATUS},
            "nested": {
                "$id": _CYCLE9_CHILD,
                "type": "object",
                "properties": {"hull": {"$ref": _CYCLE9_HULL}},
            },
        },
    }
    document, body = _cycle9_render(field, schema)
    child = _cycle9_find(body, _CYCLE9_CHILD)
    assert child is not None
    assert set(body.get("$defs", {})) == {_CYCLE9_STATUS_NAME}
    assert set(child.get("$defs", {})) == {"urn.ocor.type.hull"}
    _validate(document)


@pytest.mark.parametrize("field", _CYCLE9_FIELDS)
def test_cycle9_an_unreferenced_local_definition_is_not_emitted(field: str) -> None:
    """A local ``$defs`` entry that no reference reaches is left out.

    The twin without that entry renders the same schema. The profile
    accepts the descriptor.
    """
    unused = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "$defs": {"independent-unreachable": {"type": "string"}},
    }
    twin = {"type": "object", "properties": {"n": {"type": "integer"}}}
    document, body = _cycle9_render(field, unused)
    _, plain = _cycle9_render(field, twin)
    assert "independent-unreachable" not in body.get("$defs", {})
    assert "$defs" not in body
    assert body == plain
    _validate(document)


@pytest.mark.parametrize("field", _CYCLE9_FIELDS)
def test_cycle9_a_ref_inside_const_is_closed_on_its_resource(field: str) -> None:
    """A ``$ref`` inside ``const`` is a target of the resource that holds it.

    ``const`` is not a schema applicator. The reference still names a
    definition, and that definition is placed on the nested resource, not
    on the parent. Two cases, one per tool field.
    """
    document, body = _cycle9_render(
        field,
        {
            "type": "object",
            "properties": {
                "nested": {
                    "$id": _CYCLE9_CHILD,
                    "const": {"$ref": _CYCLE9_STATUS},
                }
            },
        },
    )
    child = _cycle9_find(body, _CYCLE9_CHILD)
    assert child is not None
    assert set(child.get("$defs", {})) == {_CYCLE9_STATUS_NAME}
    assert _CYCLE9_STATUS_NAME not in body.get("$defs", {})
    _validate(document)


@pytest.mark.parametrize("field", _CYCLE9_FIELDS)
def test_cycle9_an_id_inside_const_does_not_start_a_resource(field: str) -> None:
    """An ``$id`` inside ``const`` stays instance data.

    referencing 0.37.0 does not crawl ``const``, so both references stay
    on the root resource. Two cases, one per tool field.
    """
    document, body = _cycle9_render(
        field,
        {
            "type": "object",
            "properties": {
                "status": {"$ref": _CYCLE9_STATUS},
                "sample": {"const": {"$id": _CYCLE9_CHILD, "$ref": _CYCLE9_HULL}},
            },
        },
    )
    assert set(body.get("$defs", {})) == {_CYCLE9_STATUS_NAME, "urn.ocor.type.hull"}
    sample = body["properties"]["sample"]["const"]
    assert sample["$id"] == _CYCLE9_CHILD
    assert sample["$ref"] == "#/$defs/urn.ocor.type.hull"
    assert "$defs" not in body["properties"]["sample"]
    _validate(document)


@pytest.mark.parametrize("field", _CYCLE9_FIELDS)
def test_cycle9_an_unresolvable_definition_is_a_typed_generation_error(field: str) -> None:
    """A symbol that is not a type is not emitted as a dangling ``$ref``.

    ``urn:ocor:property:vessel-name`` is in the IR symbol table, so the
    compiler accepts the contract. The generator has no schema for that
    component and fails closed. Two cases, one per tool field.
    """
    schema = {
        "type": "object",
        "properties": {"x": {"$ref": _CYCLE9_PROPERTY}},
    }
    with pytest.raises(C1Error, match="unresolved MCP definition") as caught:
        _cycle9_render(field, schema)
    assert caught.value.diagnostics[0].code == DiagnosticCode.UNRESOLVED_REFERENCE


# Cycle 9 prereview repair. Class: a generated tool schema resolves on its
# own, the same way referencing 0.37.0 resolves it. Members added here, each
# with a positive twin or a typed refusal: repeated resource URI, ``$id``
# that does not change the resource, ``additionalItems``, unreachable nested
# ``$defs``, and the typed refusals of the generator bounds.


_CYCLE9_ROOT = "https://probe.invalid/root.json"
_CYCLE9_SAME = "https://probe.invalid/x.json"
_CYCLE9_NOOP_IDS = ("#", "root.json", _CYCLE9_ROOT)


def _cycle9_noop_schema(identifier: str) -> dict[str, Any]:
    return {
        "$id": _CYCLE9_ROOT,
        "type": "object",
        "properties": {
            "n": {
                "$id": identifier,
                "type": "object",
                "properties": {"status": {"$ref": _CYCLE9_STATUS}},
            }
        },
    }


@pytest.mark.parametrize("field", _CYCLE9_FIELDS)
@pytest.mark.parametrize("identifier", _CYCLE9_NOOP_IDS)
def test_cycle9_an_id_that_joins_the_current_resource_keeps_the_root_closure(
    field: str,
    identifier: str,
) -> None:
    """``#``, a same-URI relative and the root URI do not start a resource.

    The closure stays on the root. referencing 0.37.0 and
    Draft202012Validator accept the governed value and reject a wrong enum.
    Six cases, two fields by three identifiers.
    """
    document, body = _cycle9_render(field, _cycle9_noop_schema(identifier))
    assert set(body.get("$defs", {})) == {_CYCLE9_STATUS_NAME}
    nested = body["properties"]["n"]
    assert "$defs" not in nested
    _validate(document)
    uri = body["$id"] if isinstance(body.get("$id"), str) else _CYCLE9_ROOT
    _cycle9_enum_oracle(body, uri, {"n": {"status": "ACTIVE"}}, bad={"n": {"status": "WRONG"}})


@pytest.mark.parametrize("field", _CYCLE9_FIELDS)
def test_cycle9_a_repeated_resource_uri_is_a_typed_generation_error(field: str) -> None:
    """Two nodes that join to one URI are not emitted with a dangling ref.

    referencing keeps a single resource. The generator fails closed before
    the profile can see the descriptor. The sibling shape and the
    properties/allOf shape are both refused.
    """
    siblings = {
        "type": "object",
        "properties": {
            "a": {
                "$id": _CYCLE9_SAME,
                "type": "object",
                "properties": {"status": {"$ref": _CYCLE9_STATUS}},
            },
            "b": {
                "$id": _CYCLE9_SAME,
                "type": "object",
                "properties": {"hull": {"$ref": _CYCLE9_HULL}},
            },
        },
    }
    mixed = {
        "type": "object",
        "properties": {
            "a": {"$id": _CYCLE9_SAME, "$ref": _CYCLE9_STATUS},
        },
        "allOf": [{"$id": _CYCLE9_SAME, "type": "object"}],
    }
    for schema in (siblings, mixed):
        with pytest.raises(C1Error, match="repeats a resource URI") as caught:
            _cycle9_render(field, schema)
        assert caught.value.diagnostics[0].code == DiagnosticCode.DUPLICATE_RESOURCE


@pytest.mark.parametrize("field", _CYCLE9_FIELDS)
def test_cycle9_additional_items_ref_is_closed_on_the_current_resource(field: str) -> None:
    """A ``$ref`` under ``additionalItems`` receives the root closure.

    The draft does not crawl ``additionalItems``. The profile still resolves
    the reference on the current resource. The wrong enum is rejected.
    """
    document, body = _cycle9_render(
        field,
        {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "additionalItems": {"$ref": _CYCLE9_STATUS},
                }
            },
        },
    )
    assert set(body.get("$defs", {})) == {_CYCLE9_STATUS_NAME}
    assert body["properties"]["rows"]["additionalItems"]["$ref"] == f"#/$defs/{_CYCLE9_STATUS_NAME}"
    _validate(document)
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    uri = body["$id"] if isinstance(body.get("$id"), str) and body.get("$id") else "urn:ocor:probe:cycle9-items"
    registry = Registry().with_resource(uri, DRAFT202012.create_resource(body))
    resolved = registry.resolver(uri).lookup(f"#/$defs/{_CYCLE9_STATUS_NAME}")
    assert resolved.contents["enum"] == ["ACTIVE", "LAID_UP"]


@pytest.mark.parametrize("field", _CYCLE9_FIELDS)
def test_cycle9_an_unreferenced_nested_defs_map_is_not_emitted(field: str) -> None:
    """A ``$defs`` map on a node that is not a resource root is omitted.

    References that occur only inside that map do not enter the root
    closure. The twin without the map renders the same schema.
    """
    unused = {
        "type": "object",
        "properties": {
            "n": {
                "type": "integer",
                "$defs": {"local-unused": {"$ref": _CYCLE9_VESSEL}},
            }
        },
    }
    twin = {"type": "object", "properties": {"n": {"type": "integer"}}}
    document, body = _cycle9_render(field, unused)
    _, plain = _cycle9_render(field, twin)
    assert body == plain
    assert _CYCLE9_VESSEL.split(":")[-1] not in json.dumps(body)
    assert "urn.ocor.type.vessel" not in json.dumps(body)
    _validate(document)


def test_cycle9_a_shadowed_duplicate_id_is_refused_by_the_profile() -> None:
    """The profile does not resolve a shadowed ``$ref`` on the parent resource.

    Two subschemas share one ``$id``. referencing keeps the last body, which
    has no ``$defs``. The shadowed ``$ref`` does not resolve. The same schema
    without the second subschema is refused as well, because the reference
    points at the nested resource rather than the parent.
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import _WrappedReferencingError
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    status = {"type": "string", "enum": ["ACTIVE", "LAID_UP"]}
    schema = {
        "type": "object",
        "$defs": {"S": status},
        "properties": {"a": {"$id": _CYCLE9_SAME, "$ref": "#/$defs/S"}},
        "allOf": [{"$id": _CYCLE9_SAME, "type": "object"}],
    }
    document = _bare_descriptor()
    document["tools"][0]["inputSchema"] = schema
    with pytest.raises(profile.McpProfileError, match="does not resolve"):
        _validate(document)
    registry = Registry().with_resource(
        "urn:ocor:embedded-tool:0:inputSchema",
        DRAFT202012.create_resource(schema),
    )
    with pytest.raises(_WrappedReferencingError):
        Draft202012Validator(schema, registry=registry).validate({"a": "ACTIVE"})


def test_cycle9_an_unresolved_name_does_not_depend_on_hash_seed() -> None:
    """Several missing definitions report the least name, in every process."""
    import os
    import subprocess
    import sys

    script = (
        "from ocor_runtime.c1.codegen import _mcp_attach_definitions\n"
        "from ocor_runtime.c1.ports import C1Error\n"
        "schema = {'type': 'object', 'properties': {\n"
        " 'a': {'$ref': '#/$defs/alpha'},\n"
        " 'b': {'$ref': '#/$defs/beta'},\n"
        " 'c': {'$ref': '#/$defs/gamma'}}}\n"
        "try:\n"
        "    _mcp_attach_definitions(schema, {}, path='p',\n"
        "        base_uri='urn:ocor:embedded-tool:0:inputSchema')\n"
        "except C1Error as exc:\n"
        "    print(exc.diagnostics[0].message)\n"
    )
    src = str(ROOT / "ocor-runtime" / "src")
    messages: set[str] = set()
    for seed in range(4):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = str(seed)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode == 0, completed.stderr
        messages.add(completed.stdout.strip())
    assert messages == {"unresolved MCP definition alpha"}


def _cycle9_attach(schema: object) -> None:
    codegen = importlib.import_module("ocor_runtime.c1.codegen")
    codegen._mcp_attach_definitions(
        schema,
        {},
        path="mcp-descriptor/probe",
        base_uri="urn:ocor:embedded-tool:0:inputSchema",
    )


def test_cycle9_generator_bounds_null_and_bad_defs_fail_closed() -> None:
    """Typed refusals for bounds, a bad ``$defs``, a foreign ref and null.

    These inputs reach ``_mcp_attach_definitions`` from a stored schema.
    Removing the check would accept the schema or raise a raw exception.
    """
    deep: dict[str, Any] = {"type": "string"}
    for _ in range(40):
        deep = {"type": "object", "properties": {"n": deep}}
    with pytest.raises(C1Error, match="exceeds the revision bounds") as caught:
        _cycle9_attach(deep)
    assert caught.value.diagnostics[0].code == DiagnosticCode.TYPE_ERROR

    wide = {
        "type": "object",
        "properties": {f"n{index}": {"type": "string"} for index in range(5000)},
    }
    with pytest.raises(C1Error, match="exceeds the revision bounds") as caught:
        _cycle9_attach(wide)
    assert caught.value.diagnostics[0].code == DiagnosticCode.TYPE_ERROR

    with pytest.raises(C1Error, match=r"\$defs must be an object") as caught:
        _cycle9_attach({"type": "object", "$defs": ["no"]})
    assert caught.value.diagnostics[0].code == DiagnosticCode.TYPE_ERROR

    with pytest.raises(C1Error, match="not a valid URI reference") as caught:
        _cycle9_attach(
            {"type": "object", "properties": {"n": {"$id": "http://[bad", "type": "string"}}}
        )
    assert caught.value.diagnostics[0].code == DiagnosticCode.TYPE_ERROR

    with pytest.raises(C1Error, match="unresolved MCP definition") as caught:
        _cycle9_attach(
            {"type": "object", "properties": {"n": {"$ref": "https://example.invalid/ext.json"}}}
        )
    assert caught.value.diagnostics[0].code == DiagnosticCode.UNRESOLVED_REFERENCE

    with pytest.raises(C1Error, match="not resolvable") as caught:
        _cycle9_attach({"type": "object", "properties": None})
    assert caught.value.diagnostics[0].code == DiagnosticCode.TYPE_ERROR

    # A null schema element is not a raw exception: the crawl fails closed.
    with pytest.raises(C1Error, match="unresolved MCP definition") as caught:
        _cycle9_attach({"allOf": [None], "type": "object"})
    assert caught.value.diagnostics[0].code == DiagnosticCode.UNRESOLVED_REFERENCE


class _Cycle9Mapping(Mapping[str, Any]):
    """A mapping that is not a dict, so the resource-object check can fire."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        self._data = dict(data)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Any:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def test_cycle9_a_resource_that_is_not_a_dict_is_a_typed_error() -> None:
    """A stored schema object that is not a dict fails closed."""
    schema = {
        "type": "object",
        "properties": {
            "n": _Cycle9Mapping({"$id": _CYCLE9_SAME, "type": "string"}),
        },
    }
    with pytest.raises(C1Error, match="resource is not an object") as caught:
        _cycle9_attach(schema)
    assert caught.value.diagnostics[0].code == DiagnosticCode.TYPE_ERROR


def test_cycle9_a_crawl_failure_is_a_typed_unresolved_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """A crawl error from referencing becomes the generator's typed error."""
    from referencing.exceptions import Unresolvable

    codegen = importlib.import_module("ocor_runtime.c1.codegen")

    class _BrokenRegistry:
        def with_resource(self, *_args: object, **_kwargs: object) -> "_BrokenRegistry":
            return self

        def crawl(self) -> object:
            raise Unresolvable("crawl refused the schema")

    monkeypatch.setattr(codegen, "Registry", lambda: _BrokenRegistry())
    with pytest.raises(C1Error, match="unresolved MCP definition") as caught:
        _cycle9_attach({"type": "object"})
    assert caught.value.diagnostics[0].code == DiagnosticCode.UNRESOLVED_REFERENCE


# Cycle 10 phase A. REM-0063-CICLO-10-CONTRATTO (2026-11-16) points 2-3:
# append-only contract tests; no production edit or alteration of earlier tests.
# The oracle consumes the original standalone schema, never a rewritten registry.
_CYCLE10_FIELDS = ("inputSchema", "outputSchema")
_CYCLE10_ROOTS = ("absent", "absolute", "relative")
_CYCLE10_IDS = ("absent", "empty", "fragment", "same-relative", "same-absolute", "relative", "absolute", "duplicate")
_CYCLE10_POSITIONS = ("properties", "$defs", "allOf", "const", "default", "examples")
_CYCLE10_REFS = ("empty", "pointer", "anchor", "percent-pointer", "percent-leading-pointer", "percent-anchor", "resource-uri", "missing", "non-schema")
_CYCLE10_ORIGINS = ("delivered", "generated")
_CYCLE10_ROOT_URI = "https://cycle10.invalid/root.json"
_CYCLE10_CHILD_URI = "https://cycle10.invalid/child.json"
_CYCLE10_STATUS = "urn:ocor:type:vessel-status"
_CYCLE10_TYPE_NAME = "urn.ocor.type.vessel-status"


def _cycle10_base(schema: Mapping[str, Any], field: str, *, index: int = 0) -> str:
    """B1 base. No code under test. Absent, non-string, ``""`` and an empty pre-fragment use the fixed URI.

    Old oracle: ``urldefrag(schema.get("$id") or fixed)[0]``, so ``"#"`` became
    the empty string. New oracle: that identifier uses the fixed URI.
    """
    from urllib.parse import urldefrag

    fixed = f"urn:ocor:embedded-tool:{index}:{field}"
    declared = schema.get("$id")
    if not isinstance(declared, str) or declared == "":
        return fixed
    base = urldefrag(declared)[0]
    if base == "":
        return fixed
    return base


def _cycle10_identifier(kind: str, root: str, field: str) -> str | None:
    if kind == "absent":
        return None
    if kind == "empty":
        return ""
    if kind == "fragment":
        return "#"
    if kind == "same-relative":
        return "#" if root == "absent" else "root.json"
    if kind == "same-absolute":
        # No declared absolute root exists in the other two root modes. A
        # fragment is the no-new-resource representative in those cells.
        return _CYCLE10_ROOT_URI if root == "absolute" else "#"
    if kind == "relative":
        return "sub/branch.json"
    return _CYCLE10_CHILD_URI


def _cycle10_place(holder: dict[str, Any], position: str, target: dict[str, Any]) -> str:
    if position == "examples":
        holder[position] = [{"target": target}]
        return "examples/0/target"
    if position == "allOf":
        holder[position] = [target]
        return "allOf/0"
    if position in ("properties", "$defs"):
        holder.setdefault(position, {})["target"] = target
    else:
        holder[position] = {"target": target}
    return position + "/target"


def _cycle10_schema(field: str, root: str, identifier: str, position: str, ref: str, sibling: bool) -> tuple[dict[str, Any], str]:
    """Build inputs by Cartesian dimensions; lookup is left to referencing."""
    schema: dict[str, Any] = {"type": "object"}
    if root != "absent":
        schema["$id"] = _CYCLE10_ROOT_URI if root == "absolute" else "relative/root.json"
    holder: dict[str, Any] = {
        "type": "object",
        "$defs": {"leaf": {"$anchor": "leaf", "type": "object", "properties": {"ok": {"const": True}}}},
        "x-cycle10-not-schema": 17,
    }
    declared = _cycle10_identifier(identifier, root, field)
    if declared is not None:
        holder["$id"] = declared
    reference = {
        "empty": "#", "pointer": "#/$defs/leaf", "anchor": "#leaf",
        "percent-pointer": "#/%24defs/leaf", "percent-leading-pointer": "#%2F$defs/leaf", "percent-anchor": "#%6Ceaf",
        "resource-uri": _CYCLE10_CHILD_URI + "#/$defs/leaf",
        "missing": "#/$defs/missing", "non-schema": "#/x-cycle10-not-schema",
    }[ref]
    pointer = "#/$defs/holder/" + _cycle10_place(holder, position, {"$ref": reference})
    schema["$defs"] = {"holder": holder}
    if identifier == "duplicate":
        schema["$defs"]["shadow"] = {"$id": _CYCLE10_CHILD_URI, "type": "object"}
    if sibling:
        schema["$defs"]["unused"] = {"type": "object", "properties": {"unrelated": {"type": "integer"}}}
    schema["properties"] = {"entry": {"$ref": pointer}}
    return schema, pointer


def _cycle10_standalone_oracle(schema: Mapping[str, Any], field: str, *, probes: tuple[str, ...] = (), index: int = 0) -> tuple[bool, tuple[str, ...]]:
    """Unmodified DRAFT202012 + Draft202012Validator, without retrieval.

    The library alone follows pointers and changes resolver context. The queue
    just visits schema children via Resource.subresources and resolved targets.
    Explicit probes reach schemas inside instance data, which the draft does
    not crawl. No production helper, pointer parser or $id rewrite is used.
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
    from referencing import Registry
    from referencing.exceptions import Unresolvable
    from referencing.jsonschema import DRAFT202012

    resource = DRAFT202012.create_resource(schema)
    registry = Registry().with_resource(_cycle10_base(schema, field, index=index), resource)
    resolver = registry.resolver(_cycle10_base(schema, field, index=index))
    queue = [(resource, resolver)]
    trace: list[str] = []
    seen: set[tuple[object, ...]] = set()
    try:
        Draft202012Validator.check_schema(schema)
        for pointer in probes:
            selected = resolver.lookup(pointer)
            queue.append((DRAFT202012.create_resource(selected.contents), selected.resolver))
        while queue:
            current, context = queue.pop(0)
            # A lookup can crawl the immutable registry and change its resource
            # winner. The same node/base with that new registry is a new state.
            # This observes library state; it never resolves a URI or pointer.
            identity = (
                id(current.contents), context._base_uri,
                tuple(sorted((uri, id(value.contents)) for uri, value in context._registry._resources.items())),
                tuple(sorted(context._registry._uncrawled)),
                tuple(sorted((str(key), id(value)) for key, value in context._registry._anchors.items())),
            )
            if identity in seen:
                continue
            seen.add(identity)
            Draft202012Validator.check_schema(current.contents)
            if isinstance(current.contents, dict) and "$ref" in current.contents:
                ref = current.contents["$ref"]
                selected = context.lookup(ref)
                trace.append(ref + " -> " + json.dumps(selected.contents, sort_keys=True))
                Draft202012Validator.check_schema(selected.contents)
                queue.append((DRAFT202012.create_resource(selected.contents), selected.resolver))
            for child in current.subresources():
                queue.append((child, context.in_subresource(child)))
        # The instance reaches entry, unlike the former vacuous {} check.
        # Use the same fixed base, without adding/changing a schema $id.
        # Ordinary validation errors are data mismatches, not lookup failures.
        # A recursive schema remains resolvable; no terminating validation is
        # claimed for the unguarded allOf/$ref:'#' cell (contract exclusion V1).
        try:
            errors = list(Draft202012Validator(schema, _resolver=resolver).iter_errors({"entry": {"ok": True}}))
            trace.append("validator reached entry; instance errors=" + str(len(errors)))
        except RecursionError:
            trace.append("recursive instance evaluation: NOT_EXECUTED; resolution checked")
    except (Unresolvable, SchemaError, AttributeError, TypeError, ValueError) as exc:
        return False, (*trace, type(exc).__name__ + ": " + str(exc))
    return True, tuple(trace)


def _cycle10_delivered(schema: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {
        "x-ocor-mcp-protocol-revision": REVISION,
        "tools": [{"name": "cycle10", "inputSchema": {"type": "object"}, "outputSchema": {"type": "object"}, field: dict(schema)}],
    }


def _cycle10_products(*, generated: bool = False) -> list[tuple[str, str, str, str, str, bool]]:
    from itertools import product

    # OaC named-contract $ref accepts symbol-table IDs only. Its generated
    # form is #/$defs/<type>, so the other eight reference forms belong to
    # the delivered-schema product (README: exclusions G1, G2).
    refs = ("pointer",) if generated else _CYCLE10_REFS
    return list(product(_CYCLE10_FIELDS, _CYCLE10_ROOTS, _CYCLE10_IDS, _CYCLE10_POSITIONS, refs, (False, True)))


@pytest.mark.parametrize("field,root,identifier,position,ref,sibling", _cycle10_products())
def test_cycle10_delivered_cartesian_standalone_oracle(field: str, root: str, identifier: str, position: str, ref: str, sibling: bool) -> None:
    """Cycle-10 contract: original standalone library result controls admission."""
    from ocor_runtime.c1.mcp_profile import McpProfileError

    schema, _ = _cycle10_schema(field, root, identifier, position, ref, sibling)
    oracle_accepts, trace = _cycle10_standalone_oracle(schema, field)
    # The governed profile's preexisting fragment-only rule is stricter than
    # JSON Schema URI resolution (module docstring; decision cycle 7 point 2).
    expected = oracle_accepts and ref != "resource-uri"
    try:
        _validate(_cycle10_delivered(schema, field))
    except McpProfileError as exc:
        assert str(exc).startswith("MCP ") and any(
            text in str(exc) for text in ("resolve", "schema", "fragment", "anchor", "URI", "bounds")
        ), "profile refusal must retain its typed diagnostic reason"
        actual = False
    else:
        actual = True
    assert actual == expected, ("standalone oracle disagreement", field, root, identifier, position, ref, sibling, trace)


def _cycle10_generated(field: str, schema: Mapping[str, Any], *, documents: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    """Public compiler().build -> IrArtifactGenerator.render -> profile path."""
    fleet = _fleet()
    source = copy.deepcopy(documents) if documents is not None else copy.deepcopy(fleet.oac_documents())
    contract = _contract("urn:ocor:contract:cycle10", **{"input_schema" if field == "inputSchema" else "output_schema": schema})
    source["module.yaml"]["definitions"].append(contract)
    request = fleet.oac_request(documents=source)
    release = fleet.compiler().build(request)
    generator = fleet.c1("codegen").IrArtifactGenerator()
    first = generator.render(release)["urn:ocor:package:fleet:mcp-descriptor"]
    second = generator.render(release)["urn:ocor:package:fleet:mcp-descriptor"]
    assert first == second
    descriptor = json.loads(first)
    tool = next(item for item in descriptor["tools"] if item["name"] == "cycle10")
    return descriptor, tool[field], first


@pytest.mark.parametrize("field,root,identifier,position,ref,sibling", _cycle10_products(generated=True))
def test_cycle10_generated_cartesian_standalone_oracle(field: str, root: str, identifier: str, position: str, ref: str, sibling: bool) -> None:
    """Every emitted field works alone; typed refusal is required if it cannot.

    All render successes are checked by both libraries on their actual bytes.
    Compiler admission is not bypassed or patched. Duplicate resource roots
    may be rejected by the existing DUPLICATE_RESOURCE rule.
    """
    schema: dict[str, Any] = {"type": "object"}
    if root != "absent":
        schema["$id"] = _CYCLE10_ROOT_URI if root == "absolute" else "relative/root.json"
    holder: dict[str, Any] = {"type": "object"}
    declared = _cycle10_identifier(identifier, root, field)
    if declared is not None:
        holder["$id"] = declared
    relative_pointer = _cycle10_place(holder, position, {"$ref": _CYCLE10_STATUS})
    schema["properties"] = {"nested": holder}
    if identifier == "duplicate":
        schema["properties"]["shadow"] = {"$id": _CYCLE10_CHILD_URI, "type": "object"}
    if sibling:
        # A type absent from the closure: there is no reference to vessel here.
        schema["$defs"] = {"unused": {"type": "string"}}
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    # Independently construct the prescribed one-type closure. The library
    # decides whether the holder starts a resource; no generator helper is
    # imported and the original $id strings are left unchanged.
    expected_body = copy.deepcopy(schema)
    expected_holder = expected_body["properties"]["nested"]
    _cycle10_place(expected_holder, position, {"$ref": "#/$defs/" + _CYCLE10_TYPE_NAME})
    root_resource = DRAFT202012.create_resource(expected_body)
    root_uri = _cycle10_base(expected_body, field)
    root_resolver = Registry().with_resource(root_uri, root_resource).resolver(root_uri)
    holder_resolver = root_resolver.in_subresource(DRAFT202012.create_resource(expected_holder))
    owner = expected_body if holder_resolver._base_uri == root_resolver._base_uri else expected_holder
    if position == "$defs":
        # No OaC local reference selects this definition: it is unreachable,
        # and the generator must omit it (generator decision point 1).
        expected_holder.pop("$defs")
        probes: tuple[str, ...] = ()
    else:
        owner.setdefault("$defs", {})[_CYCLE10_TYPE_NAME] = {
            "title": _CYCLE10_STATUS, "type": "string", "enum": ["ACTIVE", "LAID_UP"],
        }
        probes = ("#/properties/nested/" + relative_pointer,)
    oracle_accepts, oracle_trace = _cycle10_standalone_oracle(expected_body, field, probes=probes)
    if not oracle_accepts or identifier == "duplicate":
        with pytest.raises(C1Error) as caught:
            _cycle10_generated(field, schema)
        expected_code = DiagnosticCode.DUPLICATE_RESOURCE if identifier == "duplicate" else DiagnosticCode.UNRESOLVED_REFERENCE
        assert caught.value.diagnostics[0].code == expected_code, oracle_trace
        return
    descriptor, body, _ = _cycle10_generated(field, schema)
    tools = descriptor["tools"]
    for index, tool in enumerate(tools):
        for current_field in _CYCLE10_FIELDS:
            if current_field not in tool:
                continue
            current_probes = probes if tool["name"] == "cycle10" and current_field == field else ()
            okay, trace = _cycle10_standalone_oracle(tool[current_field], current_field, probes=current_probes, index=index)
            assert okay, ("generator emitted an unresolvable autonomous schema", field, root, identifier, position, ref, sibling, trace)
    assert "$defs" not in descriptor
    _validate(descriptor)
    # Compare the entire closure, including the absence of unused user defs.
    if sibling:
        expected_body.get("$defs", {}).pop("unused", None)
        if not expected_body.get("$defs"):
            expected_body.pop("$defs", None)
    assert body == expected_body


def _cycle10_size(value: object) -> tuple[int, int]:
    """Independent JSON value count/depth, root = one, keys not values."""
    children = list(value.values()) if isinstance(value, dict) else value if isinstance(value, list) else []
    measures = [_cycle10_size(child) for child in children]
    return 1 + sum(n for n, _ in measures), 1 + max((d for _, d in measures), default=0)


@pytest.mark.parametrize("field", _CYCLE10_FIELDS)
@pytest.mark.parametrize("nodes", (4096, 4097))
@pytest.mark.parametrize("origin", _CYCLE10_ORIGINS)
def test_cycle10_final_node_boundary(field: str, nodes: int, origin: str) -> None:
    """VF-002: count the final JSON including definitions added by closure."""
    from ocor_runtime.c1.mcp_profile import McpProfileError

    schema: dict[str, Any] = {"type": "object", "properties": {"status": {"$ref": _CYCLE10_STATUS}}, "examples": []}
    baseline, _, _ = _cycle10_generated(field, schema)
    count, _ = _cycle10_size(baseline)
    schema["examples"] = list(range(nodes - count))
    if origin == "generated":
        if nodes > 4096:
            with pytest.raises(C1Error, match="exceeds the revision bounds"):
                _cycle10_generated(field, schema)
            return
        descriptor, _, _ = _cycle10_generated(field, schema)
    else:
        descriptor = copy.deepcopy(baseline)
        next(tool for tool in descriptor["tools"] if tool["name"] == "cycle10")[field]["examples"] = schema["examples"]
    assert _cycle10_size(descriptor)[0] == nodes
    if nodes == 4096:
        _validate(descriptor)
    else:
        with pytest.raises(McpProfileError, match="exceeds the revision bounds"):
            _validate(descriptor)


@pytest.mark.parametrize("field", _CYCLE10_FIELDS)
@pytest.mark.parametrize("depth", (32, 33))
@pytest.mark.parametrize("origin", _CYCLE10_ORIGINS)
def test_cycle10_final_depth_boundary(field: str, depth: int, origin: str) -> None:
    """Depth is measured on the emitted descriptor, never a pre-closure tree."""
    from ocor_runtime.c1.mcp_profile import McpProfileError

    schema: dict[str, Any] = {"type": "object", "properties": {"status": {"$ref": _CYCLE10_STATUS}}, "default": []}
    # Four JSON values enclose the root schema: descriptor, tools, tool, schema.
    nested: Any = 0
    for _ in range(depth - 5):
        nested = [nested]
    schema["default"] = nested
    if origin == "generated":
        if depth > 32:
            with pytest.raises(C1Error, match="exceeds the revision bounds"):
                _cycle10_generated(field, schema)
            return
        descriptor, _, _ = _cycle10_generated(field, schema)
    else:
        baseline, _, _ = _cycle10_generated(field, {"type": "object"})
        descriptor = copy.deepcopy(baseline)
        next(tool for tool in descriptor["tools"] if tool["name"] == "cycle10")[field] = {"type": "object", "default": nested}
    assert _cycle10_size(descriptor)[1] == depth
    if depth == 32:
        _validate(descriptor)
    else:
        with pytest.raises(McpProfileError, match="exceeds the revision bounds"):
            _validate(descriptor)


@pytest.mark.parametrize("field", _CYCLE10_FIELDS)
@pytest.mark.parametrize("nodes", (4096, 4097))
@pytest.mark.parametrize("type_id", (_CYCLE10_STATUS, "urn:ocor:type:vessel"))
def test_cycle10_node_growth_from_reachable_types(field: str, nodes: int, type_id: str) -> None:
    """Direct and transitive IR type closure count towards the final limit."""
    schema = {"type": "object", "properties": {"value": {"$ref": type_id}}, "examples": []}
    fleet = _fleet()
    documents = copy.deepcopy(fleet.oac_documents())
    definitions = documents["module.yaml"]["definitions"]
    enum = next(item for item in definitions if item.get("type_id") == _CYCLE10_STATUS)
    baseline, _, _ = _cycle10_generated(field, schema, documents=documents)
    base_count = _cycle10_size(baseline)[0]
    original = list(enum["values"])
    enum["values"] = [*original, "CYCLE10_EXTRA"]
    one_more, _, _ = _cycle10_generated(field, schema, documents=documents)
    copies = _cycle10_size(one_more)[0] - base_count
    assert copies > 0
    added, remainder = divmod(nodes - base_count, copies)
    enum["values"] = [*original, *(f"CYCLE10_{index:04d}" for index in range(added))]
    schema["examples"] = list(range(remainder))
    if nodes > 4096:
        with pytest.raises(C1Error, match="exceeds the revision bounds"):
            _cycle10_generated(field, schema, documents=documents)
    else:
        descriptor, _, _ = _cycle10_generated(field, schema, documents=documents)
        assert _cycle10_size(descriptor)[0] == nodes
        _validate(descriptor)


@pytest.mark.parametrize("field", _CYCLE10_FIELDS)
@pytest.mark.parametrize("depth", (32, 33))
def test_cycle10_depth_growth_from_reachable_types(field: str, depth: int) -> None:
    """The deepest resource's newly attached $defs can cross the depth limit."""
    source: dict[str, Any] = {"$id": _CYCLE10_CHILD_URI, "type": "object", "properties": {"status": {"$ref": _CYCLE10_STATUS}}}
    expected: dict[str, Any] = {
        "$id": _CYCLE10_CHILD_URI, "type": "object",
        "properties": {"status": {"$ref": "#/$defs/" + _CYCLE10_TYPE_NAME}},
        "$defs": {_CYCLE10_TYPE_NAME: {"title": _CYCLE10_STATUS, "type": "string", "enum": ["ACTIVE", "LAID_UP"]}},
    }
    while _cycle10_size(expected)[1] + 3 < depth:
        remaining = depth - _cycle10_size(expected)[1] - 3
        if remaining >= 2:
            source = {"type": "object", "properties": {"child": source}}
            expected = {"type": "object", "properties": {"child": expected}}
        else:
            source = {"type": "object", "not": source}
            expected = {"type": "object", "not": expected}
    assert _cycle10_size(expected)[1] + 3 == depth
    if depth > 32:
        with pytest.raises(C1Error, match="exceeds the revision bounds"):
            _cycle10_generated(field, source)
    else:
        descriptor, body, _ = _cycle10_generated(field, source)
        assert body == expected
        assert _cycle10_size(descriptor)[1] == depth
        _validate(descriptor)


@pytest.mark.parametrize("field", _CYCLE10_FIELDS)
def test_cycle10_fixed_base_collision_is_a_typed_refusal(field: str) -> None:
    """Generator decision point 2: the fixed URI cannot match a declared $id.

    Existing cycle-8 suffix-selection assertions are left unchanged in phase
    A. Their conflict with this prescribed refusal is an open contract question.
    """
    from ocor_runtime.c1.mcp_profile import McpProfileError

    schema = {"type": "object", "$defs": {"collision": {"$id": f"urn:ocor:embedded-tool:0:{field}", "type": "integer"}}}
    with pytest.raises(McpProfileError):
        _validate(_cycle10_delivered(schema, field))


_CYCLE10_CRAWL_TYPE_ERRORS = (
    {"type": "object", "$anchor": []},
    {"type": "object", "$anchor": {}},
    {"type": "object", "$dynamicAnchor": []},
    {"type": "object", "allOf": 7},
    {"type": "object", "allOf": None},
    {"type": "object", "anyOf": True},
    {"type": "object", "oneOf": 1.5},
    {"type": "object", "prefixItems": 7},
    {"type": "object", "properties": {"p": {"$anchor": []}}},
    {"type": "object", "$defs": {"d": {"allOf": 7}}},
)


@pytest.mark.parametrize("field", _CYCLE10_FIELDS)
@pytest.mark.parametrize("shape", _CYCLE10_CRAWL_TYPE_ERRORS)
def test_cycle10_crawl_type_error_is_typed(field: str, shape: Mapping[str, Any]) -> None:
    """A library TypeError from crawl is the profile's typed refusal.

    The same shape on the direct generator path is a typed ``C1Error``.
    A null element inside ``allOf`` stays the generator's unresolved
    definition: that branch is the null-applicator translation, not this class.
    """

    from ocor_runtime.c1.mcp_profile import McpProfileError

    with pytest.raises(McpProfileError, match="resource index is not resolvable"):
        _validate(_cycle10_delivered(shape, field))
    with pytest.raises(C1Error, match="not resolvable") as caught:
        _cycle9_attach(shape)
    assert caught.value.diagnostics[0].code == DiagnosticCode.TYPE_ERROR


def test_cycle10_null_applicator_stays_an_unresolved_definition() -> None:
    """``allOf: [null]`` is the existing crawl translation, not a raw TypeError."""

    from ocor_runtime.c1.mcp_profile import McpProfileError

    with pytest.raises(C1Error, match="unresolved MCP definition") as caught:
        _cycle9_attach({"allOf": [None], "type": "object"})
    assert caught.value.diagnostics[0].code == DiagnosticCode.UNRESOLVED_REFERENCE
    with pytest.raises(McpProfileError, match="not a JSON Schema 2020-12 schema"):
        _validate(_cycle10_delivered({"allOf": [None], "type": "object"}, "inputSchema"))


def _cycle10_rejoin_source(inner_id: str | None) -> dict[str, Any]:
    inner: dict[str, Any] = {"type": "object"}
    if inner_id is not None:
        inner["$id"] = inner_id
    return {
        "type": "object",
        "properties": {
            "holder": {
                "type": "object",
                "$id": "https://f.invalid/child.json",
                "properties": {
                    "inner": inner,
                    "probe": {"$ref": _CYCLE10_STATUS},
                },
            }
        },
    }


@pytest.mark.parametrize("field", _CYCLE10_FIELDS)
@pytest.mark.parametrize(
    ("label", "inner_id"),
    (("empty", ""), ("fragment", "#"), ("relative-name", "child.json"), ("no-rejoin", None)),
)
def test_cycle10_rejoined_resource_closure(field: str, label: str, inner_id: str | None) -> None:
    """A type reference on the boundary is closed on the library owner.

    When a descendant rejoins the boundary URI, ``$defs`` are written on
    the object ``lookup("#")`` returns, and the boundary is still scanned.
    Without that descendant the boundary itself owns the closure.
    """

    descriptor, body, _raw = _cycle10_generated(field, _cycle10_rejoin_source(inner_id))
    holder = body["properties"]["holder"]
    inner = holder["properties"]["inner"]
    if label == "no-rejoin":
        assert holder["$defs"][_CYCLE10_TYPE_NAME]["enum"] == ["ACTIVE", "LAID_UP"]
        assert "$defs" not in inner
    else:
        assert inner["$defs"][_CYCLE10_TYPE_NAME]["enum"] == ["ACTIVE", "LAID_UP"]
        assert "$defs" not in holder
    assert holder["properties"]["probe"]["$ref"] == "#/$defs/" + _CYCLE10_TYPE_NAME
    accepted, trace = _cycle10_standalone_oracle(body, field)
    assert accepted, (label, field, trace)
    _validate(descriptor)


def _cycle10_chain_documents(count: int) -> dict[str, Any]:
    documents = copy.deepcopy(_fleet().oac_documents())
    definitions = documents["module.yaml"]["definitions"]
    for index in range(count):
        type_id = f"urn:ocor:type:chain-{index:02d}"
        if index + 1 == count:
            value_ref = "enum:" + _CYCLE10_STATUS
        else:
            value_ref = f"struct:urn:ocor:type:chain-{index + 1:02d}"
        definitions.append({
            "construct": "TypeDefinition",
            "type_id": type_id,
            "kind": "STRUCT",
            "version": "1.0.0",
            "properties": [{
                "property_id": f"urn:ocor:property:chain-{index:02d}",
                "value_type_ref": value_ref,
                "cardinality": "ONE",
                "nullable": False,
                "constraint_refs": [],
            }],
            "keys": [],
            "interfaces": [],
            "security_profile_ref": "urn:ocor:security-profile:restricted",
        })
    return documents


@pytest.mark.parametrize("count", (16, 20))
def test_cycle10_type_chain_bound_matches_profile(count: int) -> None:
    """A chain of named types is not a generator-only depth limit.

    The public renderer emits the chain. The profile accepts that descriptor.
    Static depth past 32 stays refused by the existing depth-boundary tests.
    """

    schema = {"type": "object", "properties": {"first": {"$ref": "urn:ocor:type:chain-00"}}}
    descriptor, body, _raw = _cycle10_generated(
        "outputSchema", schema, documents=_cycle10_chain_documents(count),
    )
    assert len(body["$defs"]) == count + 1
    _validate(descriptor)


def test_cycle10_attached_type_chain_of_forty_matches_profile() -> None:
    """Direct closure of forty sibling definitions stays inside the shared bound."""

    from ocor_runtime.c1.codegen import _mcp_attach_definitions
    from ocor_runtime.c1.mcp_profile import operational_base

    types: dict[str, Any] = {}
    for index in range(39, -1, -1):
        name = f"t{index:02d}"
        if index == 39:
            types[name] = {"type": "string", "title": name}
        else:
            types[name] = {
                "type": "object",
                "title": name,
                "properties": {"next": {"$ref": f"#/$defs/t{index + 1:02d}"}},
            }
    schema = {"type": "object", "properties": {"first": {"$ref": "#/$defs/t00"}}}
    base = operational_base(schema, index=0, field="outputSchema")
    emitted = _mcp_attach_definitions(
        schema, types, path="mcp-descriptor/probe", base_uri=base,
    )
    assert isinstance(emitted, dict)
    assert len(emitted["$defs"]) == 40
    _validate(_cycle10_delivered(emitted, "outputSchema"))


# Second contract review: extend the product, not the production code. These
# additions retain every phase-A cell above; exclusions are listed in README.
_CYCLE10_LAYER_REFS = ("empty", "child-pointer", "child-anchor", "parent-pointer", "parent-anchor", "root-pointer", "root-anchor", "absent-anchor")


def _cycle10_cross(*dimensions: tuple[object, ...]) -> list[tuple[Any, ...]]:
    from itertools import product

    return list(product(*dimensions))


def _cycle10_layers(field: str, root: str, outer_id: str, inner_id: str, position: str, reference: str) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object"}
    if root != "absent":
        schema["$id"] = _CYCLE10_ROOT_URI if root == "absolute" else "relative/root.json"
    outer: dict[str, Any] = {"type": "object", "$defs": {"parent": {"$anchor": "parent", "type": "object"}}}
    inner: dict[str, Any] = {"type": "object", "$defs": {"child": {"$anchor": "child", "type": "object"}}}
    for node, kind in ((outer, outer_id), (inner, inner_id)):
        declared = _cycle10_identifier(kind, root, field)
        if declared is not None:
            node["$id"] = declared
    refs = {
        "empty": "#", "child-pointer": "#/$defs/child", "child-anchor": "#child",
        "parent-pointer": "#/$defs/parent", "parent-anchor": "#parent",
        "root-pointer": "#/$defs/root", "root-anchor": "#root", "absent-anchor": "#absent",
    }
    pointer = "#/$defs/holder/$defs/inner/" + _cycle10_place(inner, position, {"$ref": refs[reference]})
    outer["$defs"]["inner"] = inner
    schema["$defs"] = {"root": {"$anchor": "root", "type": "object"}, "holder": outer}
    schema["properties"] = {"entry": {"$ref": pointer}}
    return schema


def _cycle10_layer_products() -> list[tuple[str, ...]]:
    from itertools import product

    return list(product(_CYCLE10_FIELDS, _CYCLE10_ROOTS, _CYCLE10_IDS, _CYCLE10_IDS, _CYCLE10_POSITIONS, _CYCLE10_LAYER_REFS))


def _cycle10_profile_expectation(schema: Mapping[str, Any], field: str, expected: bool, *, reason: str | None = None) -> None:
    from ocor_runtime.c1.mcp_profile import McpProfileError

    if expected:
        _validate(_cycle10_delivered(schema, field))
    else:
        with pytest.raises(McpProfileError, match=reason or r"MCP (\$ref|schema|input schema)"):
            _validate(_cycle10_delivered(schema, field))


@pytest.mark.parametrize("field,root,outer_id,inner_id,position,reference", _cycle10_layer_products())
def test_cycle10_two_level_resource_product(field: str, root: str, outer_id: str, inner_id: str, position: str, reference: str) -> None:
    """Cross both ID dimensions, including ancestor/no-op and repeated URIs."""
    schema = _cycle10_layers(field, root, outer_id, inner_id, position, reference)
    accepted, trace = _cycle10_standalone_oracle(schema, field)
    try:
        _cycle10_profile_expectation(schema, field, accepted)
    except (AssertionError, ValueError) as exc:
        raise AssertionError(("two-level library outcome", trace)) from exc


@pytest.mark.parametrize("field,root,position,reference,order", _cycle10_cross(
    _CYCLE10_FIELDS, _CYCLE10_ROOTS, _CYCLE10_POSITIONS, ("pointer", "anchor", "missing", "non-schema"), ("holder-first", "shadow-first"),
))
def test_cycle10_duplicate_sibling_orders(field: str, root: str, position: str, reference: str, order: str) -> None:
    """Both library insertion orders are exercised, not just the winning one."""
    schema, _ = _cycle10_schema(field, root, "duplicate", position, reference, False)
    if order == "shadow-first":
        schema["$defs"] = dict(reversed(list(schema["$defs"].items())))
    accepted, _ = _cycle10_standalone_oracle(schema, field)
    _cycle10_profile_expectation(schema, field, accepted)


@pytest.mark.parametrize("field,position,form,state", _cycle10_cross(
    _CYCLE10_FIELDS, _CYCLE10_POSITIONS,
    ("pointer", "anchor", "percent-pointer", "percent-anchor", "percent-leading-pointer", "resource-uri"),
    ("present", "missing", "invalid-schema"),
))
def test_cycle10_reference_form_by_target_state(field: str, position: str, form: str, state: str) -> None:
    """Cross reference spelling and target validity; literals stay unmodified."""
    schema, _ = _cycle10_schema(field, "absolute", "absolute", position, form, False)
    holder = schema["$defs"]["holder"]
    if state == "missing":
        holder["$defs"].pop("leaf")
    elif state == "invalid-schema":
        holder["$defs"]["leaf"]["type"] = 17
    accepted, _ = _cycle10_standalone_oracle(schema, field)
    # The current fragment-only restriction is preserved, pending question Q3.
    _cycle10_profile_expectation(schema, field, accepted and form != "resource-uri")


@pytest.mark.parametrize("field,form,location,position", _cycle10_cross(
    _CYCLE10_FIELDS, ("pointer", "anchor", "percent-pointer"),
    ("other-field", "other-tool", "descriptor"), _CYCLE10_POSITIONS,
))
def test_cycle10_no_cross_schema_fallback(field: str, form: str, location: str, position: str) -> None:
    """A target in another field, tool or descriptor never enters this registry."""
    from ocor_runtime.c1.mcp_profile import McpProfileError

    prefix = "#/x-ocor-foreign/" if location == "descriptor" else "#/"
    reference = {"pointer": prefix + "$defs/foreign", "anchor": "#foreign", "percent-pointer": prefix + "%24defs/foreign"}[form]
    schema: dict[str, Any] = {"type": "object"}
    pointer = "#/" + _cycle10_place(schema, position, {"$ref": reference})
    schema.setdefault("properties", {})["entry"] = {"$ref": pointer}
    descriptor = _cycle10_delivered(schema, field)
    foreign = {"type": "object", "$defs": {"foreign": {"$anchor": "foreign", "type": "object"}}}
    if location == "other-field":
        descriptor["tools"][0]["outputSchema" if field == "inputSchema" else "inputSchema"] = foreign
    elif location == "other-tool":
        descriptor["tools"].append({"name": "foreign", "inputSchema": foreign})
    else:
        descriptor["x-ocor-foreign"] = foreign
    accepted, _ = _cycle10_standalone_oracle(schema, field)
    assert not accepted
    with pytest.raises(McpProfileError, match=r"\$ref does not resolve"):
        _validate(descriptor)


@pytest.mark.parametrize("field,order,form,position", _cycle10_cross(
    _CYCLE10_FIELDS, ("a-first", "b-first"), ("anchor", "percent-anchor"), _CYCLE10_POSITIONS,
))
def test_cycle10_ambiguous_anchor_remains_a_profile_refusal(field: str, order: str, form: str, position: str) -> None:
    """The documented stricter anchor rule is separate from library validity."""
    defs = {"a": {"$anchor": "leaf", "type": "object"}, "b": {"$anchor": "leaf", "type": "object"}}
    schema: dict[str, Any] = {"type": "object", "$defs": defs if order == "a-first" else dict(reversed(list(defs.items())))}
    pointer = "#/" + _cycle10_place(schema, position, {"$ref": "#leaf" if form == "anchor" else "#%6Ceaf"})
    schema.setdefault("properties", {})["entry"] = {"$ref": pointer}
    accepted, _ = _cycle10_standalone_oracle(schema, field)
    assert accepted == (form == "anchor")
    _cycle10_profile_expectation(schema, field, False, reason=r"(anchor is ambiguous|does not resolve)")


@pytest.mark.parametrize("field,position,key,form", _cycle10_cross(
    _CYCLE10_FIELDS, _CYCLE10_POSITIONS, ("a/b", "a~b", "café", "2"),
    ("valid", "missing", "malformed-escape"),
))
def test_cycle10_pointer_token_product(field: str, position: str, key: str, form: str) -> None:
    """Token escaping, non-ASCII percent segments and nonzero array indices."""
    from urllib.parse import quote

    token = quote(key.replace("~", "~0").replace("/", "~1"), safe="~")
    if form == "missing":
        token += "-absent"
    elif form == "malformed-escape":
        token = "bad~2"
    schema: dict[str, Any] = {"type": "object", "$defs": {key: {"type": "object"}}}
    if form == "malformed-escape" and key != "2":
        # A decoy target exists: the negative must be for token syntax,
        # not a failure to find an unrelated absent key.
        schema["$defs"]["bad~2"] = {"type": "object"}
    if key == "2":
        schema["x-cycle10-array"] = [0, 1, {"type": "object"}]
        reference = "#/x-cycle10-array/" + ("2" if form == "valid" else "3" if form == "missing" else "02")
    else:
        reference = "#/$defs/" + token
    pointer = "#/" + _cycle10_place(schema, position, {"$ref": reference})
    schema.setdefault("properties", {})["entry"] = {"$ref": pointer}
    accepted, _ = _cycle10_standalone_oracle(schema, field)
    # Leading-zero array indices are explicitly stricter than referencing.
    # Any other malformed escape follows the library outcome for the planted key.
    if form == "malformed-escape" and key == "2":
        expected = False
        reason: str | None = r"(valid JSON Pointer|array index)"
    elif form == "malformed-escape":
        expected = accepted
        reason = None if accepted else r"(valid JSON Pointer|array index)"
    else:
        expected = accepted and form == "valid"
        reason = None
    _cycle10_profile_expectation(schema, field, expected, reason=reason)


@pytest.mark.parametrize("field,origin", _cycle10_cross(_CYCLE10_FIELDS, _CYCLE10_ORIGINS))
def test_cycle10_fixed_base_collision_for_both_public_origins(field: str, origin: str) -> None:
    """B1 decision: the producer must refuse before returning an invalid tool."""
    schema = {"type": "object", "properties": {"collision": {"$id": f"urn:ocor:embedded-tool:0:{field}", "type": "integer"}}}
    if origin == "generated":
        with pytest.raises(C1Error, match=r"(collision|collides)") as caught:
            _cycle10_generated(field, schema)
        assert caught.value.diagnostics[0].code == DiagnosticCode.TYPE_ERROR
    else:
        _cycle10_profile_expectation(schema, field, False, reason=r"(collision|collides)")


@pytest.mark.parametrize("field,root,noop,order", _cycle10_cross(
    _CYCLE10_FIELDS, ("absent", "absolute-fragment", "empty-fragment"), ("", "#"), ("noop-first", "noop-last"),
))
def test_cycle10_oracle_preserves_lookup_state_and_root_fragment(field: str, root: str, noop: str, order: str) -> None:
    """Library-only control: an anchor lookup changes the registry for a chain."""
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from referencing.exceptions import Unresolvable
    from referencing.jsonschema import DRAFT202012

    definitions = {"a": {"$anchor": "a", "$ref": "#/$defs/b"}, "b": {"type": "object"}, "noop": {"$id": noop, "type": "object"}}
    if order == "noop-first":
        definitions = {"noop": definitions["noop"], "a": definitions["a"], "b": definitions["b"]}
    schema: dict[str, Any] = {"type": "object", "$defs": definitions, "properties": {"entry": {"$ref": "#a"}}}
    if root != "absent":
        schema["$id"] = _CYCLE10_ROOT_URI + "#" if root == "absolute-fragment" else "#"
    base = _cycle10_base(schema, field)
    resolver = Registry().with_resource(base, DRAFT202012.create_resource(schema)).resolver(base)
    with pytest.raises(Unresolvable):
        list(Draft202012Validator(schema, _resolver=resolver).iter_errors({"entry": {}}))
    accepted, trace = _cycle10_standalone_oracle(schema, field)
    assert not accepted, trace


@pytest.mark.parametrize("field,root,reference", _cycle10_cross(
    _CYCLE10_FIELDS, ("absent", "absolute-fragment", "empty-fragment"), ("#leaf", "#/$defs/leaf"),
))
def test_cycle10_oracle_accepts_the_root_fragment_positive_twin(field: str, root: str, reference: str) -> None:
    """Trailing-fragment controls also have terminating accepted instances."""
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    schema: dict[str, Any] = {"type": "object", "$defs": {"leaf": {"$anchor": "leaf", "type": "object"}}, "properties": {"entry": {"$ref": reference}}}
    if root != "absent":
        schema["$id"] = _CYCLE10_ROOT_URI + "#" if root == "absolute-fragment" else "#"
    base = _cycle10_base(schema, field)
    resolver = Registry().with_resource(base, DRAFT202012.create_resource(schema)).resolver(base)
    assert not list(Draft202012Validator(schema, _resolver=resolver).iter_errors({"entry": {}}))
    accepted, trace = _cycle10_standalone_oracle(schema, field)
    assert accepted, trace


@pytest.mark.parametrize("field,root,position,order", _cycle10_cross(
    _CYCLE10_FIELDS, _CYCLE10_ROOTS, _CYCLE10_POSITIONS, ("holder-first", "shadow-first"),
))
def test_cycle10_generated_duplicate_orders_are_typed_refusals(field: str, root: str, position: str, order: str) -> None:
    """The producer's existing duplicate-resource rule covers both orders."""
    holder: dict[str, Any] = {"$id": _CYCLE10_CHILD_URI, "type": "object"}
    _cycle10_place(holder, position, {"$ref": _CYCLE10_STATUS})
    siblings = {"holder": holder, "shadow": {"$id": _CYCLE10_CHILD_URI, "type": "object"}}
    schema: dict[str, Any] = {"type": "object", "properties": siblings if order == "holder-first" else dict(reversed(list(siblings.items())))}
    if root != "absent":
        schema["$id"] = _CYCLE10_ROOT_URI if root == "absolute" else "relative/root.json"
    with pytest.raises(C1Error, match="repeats a resource URI") as caught:
        _cycle10_generated(field, schema)
    assert caught.value.diagnostics[0].code == DiagnosticCode.DUPLICATE_RESOURCE


def _cycle10_generated_layer_products() -> list[tuple[object, ...]]:
    from itertools import product

    return list(product(_CYCLE10_FIELDS, _CYCLE10_ROOTS, _CYCLE10_IDS, _CYCLE10_IDS, _CYCLE10_POSITIONS, ("direct", "transitive")))


def _cycle10_repeated_resource_boundary(schema: Mapping[str, Any], field: str) -> bool:
    """Observe the existing producer duplicate rule with library URI contexts."""
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    resource = DRAFT202012.create_resource(schema)
    base = _cycle10_base(schema, field)
    resolver = Registry().with_resource(base, resource).resolver(base)
    claimed = {base: id(schema)}
    queue = [(resource, resolver)]
    while queue:
        current, context = queue.pop()
        for child in current.subresources():
            next_context = context.in_subresource(child)
            uri = next_context._base_uri
            if uri != context._base_uri:
                if uri in claimed and claimed[uri] != id(child.contents):
                    return True
                claimed[uri] = id(child.contents)
            queue.append((child, next_context))
    return False


@pytest.mark.parametrize("field,root,outer_id,inner_id,position,reach", _cycle10_generated_layer_products())
def test_cycle10_generated_two_level_exact_closure(field: str, root: str, outer_id: str, inner_id: str, position: str, reach: str) -> None:
    """Public producer/consumer agreement, exact closure and instance twins.

    The expected type definitions are a literal encoding of this test's OaC
    enum and one-property struct. Only referencing selects the resource owner.
    The original emitted schema, never a normalised copy, is used by both
    independent libraries and the profile.
    """
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from referencing.exceptions import Unresolvable
    from referencing.jsonschema import DRAFT202012

    enum_definition = {"title": _CYCLE10_STATUS, "type": "string", "enum": ["ACTIVE", "LAID_UP"]}
    wrapper_id = "urn:ocor:type:cycle10-wrapper"
    wrapper_name = "urn.ocor.type.cycle10-wrapper"
    property_id = "urn:ocor:property:cycle10-status"
    wrapper_definition = {
        "title": wrapper_id, "type": "object", "additionalProperties": False,
        "properties": {property_id: {"$ref": "#/$defs/" + _CYCLE10_TYPE_NAME}},
        "required": [property_id],
    }
    documents = copy.deepcopy(_fleet().oac_documents())
    documents["module.yaml"]["definitions"].append({
        "construct": "TypeDefinition", "type_id": wrapper_id, "kind": "STRUCT", "version": "1.0.0",
        "properties": [{"property_id": property_id, "value_type_ref": "enum:" + _CYCLE10_STATUS,
                        "cardinality": "ONE", "nullable": False, "constraint_refs": []}],
        "keys": [], "interfaces": [], "security_profile_ref": "urn:ocor:security-profile:restricted",
    })
    schema: dict[str, Any] = {"type": "object"}
    if root != "absent":
        schema["$id"] = _CYCLE10_ROOT_URI if root == "absolute" else "relative/root.json"
    outer: dict[str, Any] = {"type": "object"}
    inner: dict[str, Any] = {"type": "object"}
    for node, kind in ((outer, outer_id), (inner, inner_id)):
        declared = _cycle10_identifier(kind, root, field)
        if declared is not None:
            node["$id"] = declared
    symbol = _CYCLE10_STATUS if reach == "direct" else wrapper_id
    local_path = _cycle10_place(inner, position, {"$ref": symbol})
    outer["properties"] = {"inner": inner}
    schema["properties"] = {"outer": outer}
    if _cycle10_repeated_resource_boundary(schema, field):
        with pytest.raises(C1Error, match="repeats a resource URI") as caught:
            _cycle10_generated(field, schema, documents=documents)
        assert caught.value.diagnostics[0].code == DiagnosticCode.DUPLICATE_RESOURCE
        return
    expected = copy.deepcopy(schema)
    expected_inner = expected["properties"]["outer"]["properties"]["inner"]
    type_name = _CYCLE10_TYPE_NAME if reach == "direct" else wrapper_name
    _cycle10_place(expected_inner, position, {"$ref": "#/$defs/" + type_name})
    pointer = "#/properties/outer/properties/inner/" + local_path
    if position == "$defs":
        expected_inner.pop("$defs")
    else:
        # No handwritten pointer traversal, base selection, or identity alias.
        base = _cycle10_base(expected, field)
        resolver = Registry().with_resource(base, DRAFT202012.create_resource(expected)).resolver(base)
        try:
            context = resolver.lookup(pointer).resolver
            owner = context.lookup("#").contents
        except Unresolvable:
            with pytest.raises(C1Error) as caught:
                _cycle10_generated(field, schema, documents=documents)
            assert caught.value.diagnostics[0].code == DiagnosticCode.UNRESOLVED_REFERENCE
            return
        assert isinstance(owner, dict)
        owner.setdefault("$defs", {})[_CYCLE10_TYPE_NAME] = copy.deepcopy(enum_definition)
        if reach == "transitive":
            owner["$defs"][wrapper_name] = copy.deepcopy(wrapper_definition)
    probes = () if position == "$defs" else (pointer,)
    accepted, trace = _cycle10_standalone_oracle(expected, field, probes=probes)
    if not accepted:
        with pytest.raises(C1Error) as caught:
            _cycle10_generated(field, schema, documents=documents)
        assert caught.value.diagnostics[0].code == DiagnosticCode.UNRESOLVED_REFERENCE, trace
        return
    descriptor, body, _ = _cycle10_generated(field, schema, documents=documents)
    assert body == expected
    assert "$defs" not in descriptor
    _validate(descriptor)
    for index, tool in enumerate(descriptor["tools"]):
        for emitted_field in _CYCLE10_FIELDS:
            actual = tool[emitted_field]
            okay, actual_trace = _cycle10_standalone_oracle(actual, emitted_field, index=index)
            assert okay, actual_trace
    if position != "$defs":
        base = _cycle10_base(body, field)
        resolver = Registry().with_resource(base, DRAFT202012.create_resource(body)).resolver(base)
        selected = resolver.lookup(pointer)
        validator = Draft202012Validator(selected.contents, _resolver=selected.resolver)
        good: Any = "ACTIVE" if reach == "direct" else {property_id: "ACTIVE"}
        bad: Any = "WRONG" if reach == "direct" else {property_id: "WRONG"}
        assert validator.is_valid(good)
        assert not validator.is_valid(bad)


# Second contract-review dispositions, phase A only. Earlier tests, fixtures and
# oracles remain byte-identical. The six root spellings represent distinct
# behaviour classes of referencing 0.37.0, not interchangeable URI aliases.
_CYCLE10_EDGE_ROOTS = (
    "root.json", "./root.json", "../up/root.json", "relative/root.json",
    "rel/dir/", _CYCLE10_ROOT_URI,
)
_CYCLE10_EDGE_IDS = ("absent", "root-literal", "fragment", "basename", "relative", "absolute")
_CYCLE10_EDGE_POSITIONS = (*_CYCLE10_POSITIONS, "not", "items")
_CYCLE10_EDGE_REFS = (
    "#", "#/$defs/child", "#child", "#/$defs/root", "#root",
    "#/%24defs/child", "#%2F$defs/child", "#/$defs/missing",
)


def _cycle10_edge_place(node: dict[str, Any], position: str, target: dict[str, Any]) -> str:
    if position in ("not", "items"):
        node[position] = target
        return position
    return _cycle10_place(node, position, target)


def _cycle10_edge_schema(root_id: str, outer: str, identifier: str) -> tuple[dict[str, Any], dict[str, Any]]:
    schema: dict[str, Any] = {"$id": root_id, "type": "object"}
    inner: dict[str, Any] = {"type": "object"}
    declared = {
        "absent": None, "root-literal": root_id, "fragment": "#",
        "basename": "root.json", "relative": "sub/branch.json",
        "absolute": _CYCLE10_CHILD_URI,
    }[identifier]
    if declared is not None:
        inner["$id"] = declared
    holder: dict[str, Any] = {"type": "object", "$defs": {"inner": inner}}
    if outer == "new-absolute":
        holder["$id"] = "https://cycle10.invalid/outer.json"
    schema["$defs"] = {"holder": holder, "root": {"$anchor": "root", "type": "object"}}
    return schema, inner


@pytest.mark.parametrize("field,root_id,outer,identifier,position,reference", _cycle10_cross(
    _CYCLE10_FIELDS, _CYCLE10_EDGE_ROOTS, ("same-resource", "new-absolute"),
    _CYCLE10_EDGE_IDS, _CYCLE10_EDGE_POSITIONS, _CYCLE10_EDGE_REFS,
))
def test_cycle10_relative_root_behaviour_classes(
    field: str, root_id: str, outer: str, identifier: str, position: str, reference: str,
) -> None:
    """P1: literal root repetition, stable/dot/directory roots and two levels.

    Targets and outcomes come only from the pinned libraries on the original
    resource. Single-schema keywords supplement map/list and data positions.
    """
    schema, inner = _cycle10_edge_schema(root_id, outer, identifier)
    inner["$defs"] = {"child": {"$anchor": "child", "type": "object"}}
    pointer = "#/$defs/holder/$defs/inner/" + _cycle10_edge_place(inner, position, {"$ref": reference})
    schema["properties"] = {"entry": {"$ref": pointer}}
    accepted, trace = _cycle10_standalone_oracle(schema, field)
    try:
        _cycle10_profile_expectation(schema, field, accepted)
    except (AssertionError, ValueError) as exc:
        raise AssertionError(("root behaviour class", root_id, outer, identifier, position, reference, trace)) from exc


@pytest.mark.parametrize("field,root_id,outer,identifier,position", _cycle10_cross(
    _CYCLE10_FIELDS, _CYCLE10_EDGE_ROOTS, ("same-resource", "new-absolute"),
    _CYCLE10_EDGE_IDS, _CYCLE10_EDGE_POSITIONS,
))
def test_cycle10_generated_relative_root_behaviour_classes(
    field: str, root_id: str, outer: str, identifier: str, position: str,
) -> None:
    """Both public origins cover the same relative-root and nested-ID classes."""
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from referencing.exceptions import Unresolvable
    from referencing.jsonschema import DRAFT202012

    schema, inner = _cycle10_edge_schema(root_id, outer, identifier)
    # The two root definitions here are test scaffolding, with no incoming OaC
    # reference; only the inner path is live in the generated source schema.
    schema["properties"] = {"outer": schema.pop("$defs")["holder"]}
    inner = schema["properties"]["outer"].pop("$defs")["inner"]
    schema["properties"]["outer"]["properties"] = {"inner": inner}
    local = _cycle10_edge_place(inner, position, {"$ref": _CYCLE10_STATUS})
    if _cycle10_repeated_resource_boundary(schema, field):
        with pytest.raises(C1Error) as caught:
            _cycle10_generated(field, schema)
        assert caught.value.diagnostics[0].code == DiagnosticCode.DUPLICATE_RESOURCE
        return
    expected = copy.deepcopy(schema)
    expected_inner = expected["properties"]["outer"]["properties"]["inner"]
    _cycle10_edge_place(expected_inner, position, {"$ref": "#/$defs/" + _CYCLE10_TYPE_NAME})
    pointer = "#/properties/outer/properties/inner/" + local
    if position == "$defs":
        expected_inner.pop("$defs")
        probes: tuple[str, ...] = ()
    else:
        base = _cycle10_base(expected, field)
        resolver = Registry().with_resource(base, DRAFT202012.create_resource(expected)).resolver(base)
        try:
            owner = resolver.lookup(pointer).resolver.lookup("#").contents
        except Unresolvable:
            with pytest.raises(C1Error) as caught:
                _cycle10_generated(field, schema)
            assert caught.value.diagnostics[0].code == DiagnosticCode.UNRESOLVED_REFERENCE
            return
        assert isinstance(owner, dict)
        owner.setdefault("$defs", {})[_CYCLE10_TYPE_NAME] = {
            "title": _CYCLE10_STATUS, "type": "string", "enum": ["ACTIVE", "LAID_UP"],
        }
        probes = (pointer,)
    accepted, trace = _cycle10_standalone_oracle(expected, field, probes=probes)
    if not accepted:
        with pytest.raises(C1Error) as caught:
            _cycle10_generated(field, schema)
        assert caught.value.diagnostics[0].code == DiagnosticCode.UNRESOLVED_REFERENCE, trace
        return
    descriptor, body, _ = _cycle10_generated(field, schema)
    assert body == expected
    _validate(descriptor)
    for index, tool in enumerate(descriptor["tools"]):
        for emitted_field in _CYCLE10_FIELDS:
            okay, actual_trace = _cycle10_standalone_oracle(tool[emitted_field], emitted_field, index=index)
            assert okay, actual_trace
    if position != "$defs":
        base = _cycle10_base(body, field)
        resolver = Registry().with_resource(base, DRAFT202012.create_resource(body)).resolver(base)
        selected = resolver.lookup(pointer)
        validator = Draft202012Validator(selected.contents, _resolver=selected.resolver)
        assert validator.is_valid("ACTIVE")
        assert not validator.is_valid("WRONG")


@pytest.mark.parametrize("field,position,state", _cycle10_cross(
    _CYCLE10_FIELDS, ("const", "default", "examples"), ("valid", "invalid-schema", "non-schema"),
))
def test_cycle10_resolved_data_target_is_checked_as_a_schema(field: str, position: str, state: str) -> None:
    """P4: check_schema(root) alone cannot validate a target under instance data."""
    from jsonschema import Draft202012Validator

    target: Any = {"type": "object"} if state == "valid" else {"type": 17} if state == "invalid-schema" else 17
    schema: dict[str, Any] = {"type": "object"}
    if position == "examples":
        schema[position] = [{"target": target}]
        pointer = "#/examples/0/target"
    else:
        schema[position] = {"target": target}
        pointer = "#/" + position + "/target"
    schema["properties"] = {"entry": {"$ref": pointer}}
    Draft202012Validator.check_schema(schema)
    accepted, trace = _cycle10_standalone_oracle(schema, field)
    assert accepted == (state == "valid"), trace
    _cycle10_profile_expectation(schema, field, accepted)


@pytest.mark.parametrize("field,index,fragment,origin,collision", _cycle10_cross(
    _CYCLE10_FIELDS, (0, 1), ("", "#"), _CYCLE10_ORIGINS, (False, True),
))
def test_cycle10_fixed_base_at_multiple_tool_indices(
    field: str, index: int, fragment: str, origin: str, collision: bool,
) -> None:
    """P5: local collision includes the empty-fragment spelling, at both indices.

    Cross-tree collision scope and root empty-ID semantics remain open questions;
    these rows assert only the already-decided local collision rule B1.
    """
    from ocor_runtime.c1.mcp_profile import McpProfileError

    uri = f"urn:ocor:embedded-tool:{index}:{field}" if collision else "https://cycle10.invalid/non-collision.json"
    schema: dict[str, Any] = {"type": "object", "properties": {"child": {"$id": uri + fragment, "type": "object"}}}
    if origin == "delivered":
        document = _cycle10_delivered(schema, field)
        if index:
            document["tools"].insert(0, {"name": "aaa-prefix", "inputSchema": {"type": "object"}})
        if collision:
            with pytest.raises(McpProfileError, match=r"(colli|URI)"):
                _validate(document)
        else:
            _validate(document)
        return
    documents = copy.deepcopy(_fleet().oac_documents())
    if index:
        documents["module.yaml"]["definitions"].append(_contract("urn:ocor:contract:aaa-prefix"))
    if collision:
        with pytest.raises(C1Error) as caught:
            _cycle10_generated(field, schema, documents=documents)
        assert caught.value.diagnostics[0].code == DiagnosticCode.TYPE_ERROR
    else:
        descriptor, _, _ = _cycle10_generated(field, schema, documents=documents)
        assert descriptor["tools"][index]["name"] == "cycle10"
        _validate(descriptor)


@pytest.mark.parametrize("field,identifier,fragment", _cycle10_cross(
    _CYCLE10_FIELDS, ("", "#", _CYCLE7_REPAIR_ROOT, "./root.json"),
    ("#/$defs/private", "#/$defs/pri%76ate"),
))
def test_cycle10_preserves_existing_anchor_lookup_context(field: str, identifier: str, fragment: str) -> None:
    """P3: the instance-path library oracle preserves the existing crawl state.

    The broad static matrix oracle has a deliberately narrower domain. It must
    not replace the existing public anchor-context tests or their expectations.
    """
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    document = _cycle8_anchor_descriptor(field=field, identifier=identifier, placement="holder", fragment=fragment)
    body = document["tools"][0][field]
    registry = Registry().with_resource(body["$id"], DRAFT202012.create_resource(body))
    resolver = registry.resolver(body["$id"])
    validator = Draft202012Validator(body, _resolver=resolver)
    assert validator.is_valid({"n": 11})
    assert not validator.is_valid({"n": "bad"})
    _validate(document)


# REM-0063-CYCLE10-NESTED-RESOURCE-RESOLUTION (2026-11-17), option C1.
# Nodes reached only by static descent inside a nested resource. The original
# 40180 cells stay. The oracle is referencing 0.37.0 and Draft202012Validator
# on the original schema bytes, never a production helper.

_CYCLE10_STATIC_ROOTS = ("absent", "absolute", "relative")
_CYCLE10_STATIC_SHAPES = ("plain", "empty-descendant", "hash-descendant", "fragment")


def _cycle10_static_descent_schema(root: str, shape: str) -> dict[str, Any]:
    """One nested resource whose probe node is not the target of a reference."""
    if root == "relative":
        root_id: str | None = "rel/root.json"
        child_id = "child.json"
    elif root == "absolute":
        root_id = "https://nested.invalid/root.json"
        child_id = "https://nested.invalid/child.json"
    elif root == "absent":
        root_id = None
        child_id = "https://nested.invalid/child.json"
    else:
        raise AssertionError(root)
    holder_shared: dict[str, Any] = {"type": "integer"}
    inner_shared: dict[str, Any] = {"type": "string"}
    static: dict[str, Any] = {
        "type": "object",
        "properties": {
            "probe": {"$ref": "#" if shape == "fragment" else "#/$defs/shared"},
        },
    }
    if shape == "empty-descendant":
        static["properties"]["inner"] = {"$id": "", "type": "object"}
    elif shape == "hash-descendant":
        static["properties"]["inner"] = {
            "$id": "#",
            "type": "object",
            "$defs": {"shared": inner_shared},
        }
    holder: dict[str, Any] = {
        "$id": child_id,
        "type": "object",
        "$defs": {"shared": holder_shared},
        "properties": {"static_only": static},
    }
    schema: dict[str, Any] = {"type": "object", "properties": {"holder": holder}}
    if root_id is not None:
        schema["$id"] = root_id
    schema["x-cycle10-static"] = {
        "holder": holder,
        "holder_shared": holder_shared,
        "inner_shared": inner_shared,
        "static": static,
    }
    return schema


def _cycle10_static_library(schema: Mapping[str, Any], field: str) -> tuple[Any, BaseException | None]:
    """Lookup the only ``$ref`` with the libraries pinned on this schema alone."""
    import importlib.metadata
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    if importlib.metadata.version("referencing") != "0.37.0":
        raise AssertionError("cycle-10 oracle is referencing 0.37.0")
    if importlib.metadata.version("jsonschema") != "4.26.0":
        raise AssertionError("cycle-10 oracle is jsonschema 4.26.0")
    body = {key: value for key, value in schema.items() if key != "x-cycle10-static"}
    base = _independent_tool_base(body, index=0, field=field)
    resource = DRAFT202012.create_resource(body)
    resolver = Registry().with_resource(base, resource).resolver(base)
    queue: list[tuple[Any, Any]] = [(resource, resolver)]
    seen: set[tuple[int, object]] = set()
    found: tuple[Any, BaseException | None] | None = None
    while queue:
        current, context = queue.pop(0)
        identity = (id(current.contents), getattr(context, "_base_uri", None))
        if identity in seen:
            continue
        seen.add(identity)
        contents = current.contents
        if isinstance(contents, dict) and isinstance(contents.get("$ref"), str):
            ref = contents["$ref"]
            try:
                found = (context.lookup(ref).contents, None)
            except Exception as exc:
                found = (None, exc)
        try:
            children = list(current.subresources())
        except (AttributeError, TypeError, ValueError):
            children = []
        for child in children:
            queue.append((child, context.in_subresource(child)))
    if found is None:
        raise AssertionError("static-descent schema has no reference")
    return found


def test_cycle10_static_descent_extension_keeps_the_original_matrix() -> None:
    """C1 adds cells. It does not remove the original delivered or generated product."""
    assert len(_cycle10_products()) == 5184
    assert len(_cycle10_products(generated=True)) == 576
    assert len(_CYCLE10_STATIC_ROOTS) * len(_CYCLE10_STATIC_SHAPES) * len(_CYCLE10_FIELDS) == 24


@pytest.mark.parametrize("field", _CYCLE10_FIELDS)
@pytest.mark.parametrize("root", _CYCLE10_STATIC_ROOTS)
@pytest.mark.parametrize("shape", _CYCLE10_STATIC_SHAPES)
def test_cycle10_static_descent_inside_a_nested_resource(
    field: str,
    root: str,
    shape: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A statically reached nested node uses the library object for its spelling.

    ``static_only`` is not the target of a reference. ``plain`` has no
    rejoining descendant. ``empty-descendant`` and ``hash-descendant`` add one.
    ``relative`` is a relative root. Equal acceptance is not agreement: the
    profile must check the object the library returns.
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = _cycle10_static_descent_schema(root, shape)
    marked = schema.pop("x-cycle10-static")
    holder = marked["holder"]
    holder_shared = marked["holder_shared"]
    inner_shared = marked["inner_shared"]
    static = marked["static"]
    assert "static_only" not in json.dumps(
        [value for value in _cycle10_ref_spellings(schema)]
    )
    contents, error = _cycle10_static_library(schema, field)
    if error is None and isinstance(contents, dict):
        try:
            Draft202012Validator.check_schema(contents)
        except (SchemaError, TypeError, ValueError) as exc:
            contents, error = None, exc
    library_ok = error is None and isinstance(contents, dict)
    if root == "relative":
        # A relative root and a relative nested ``$id`` do not resolve.
        # referencing 0.37.0 raises Unresolvable for every shape, including
        # the empty fragment. That is the library result on the schema alone.
        assert not library_ok
    elif shape == "plain":
        assert library_ok and contents is holder_shared
    elif shape == "empty-descendant":
        assert not library_ok
    elif shape == "hash-descendant":
        assert library_ok and contents is inner_shared and contents is not holder_shared
    elif shape == "fragment":
        assert library_ok and contents is holder
    else:
        raise AssertionError(shape)
    seen: list[object] = []
    original = profile._require_schema

    def record(target: object) -> None:
        seen.append(target)
        original(target)

    monkeypatch.setattr(profile, "_require_schema", record)
    if library_ok:
        _validate(_cycle10_delivered(schema, field))
        assert contents in seen
        if contents is not holder_shared:
            assert holder_shared not in seen
        assert static is not contents
        return
    with pytest.raises(profile.McpProfileError):
        _validate(_cycle10_delivered(schema, field))


def _cycle10_ref_spellings(node: object) -> list[str]:
    """Reference spellings only. A static node name must not appear here."""
    found: list[str] = []
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            found.append(ref)
        for value in node.values():
            found.extend(_cycle10_ref_spellings(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_cycle10_ref_spellings(value))
    return found


# Cycle 11 RED. REM-0063-CYCLE10-NO-GO (2026-11-18) option 1, step 1.
# These tests fail on 3b4894d181b7 before any edit under ocor-runtime/src.
# The oracle is referencing 0.37.0 and Draft202012Validator on the tool schema
# alone. The base is the fixed URI, computed here, never operational_base.
_CYCLE11_DRAFT07 = "http://json-schema.org/draft-07/schema#"
_CYCLE11_KEYWORD_CASES = (
    "root-dialect",
    "nested-dialect",
    "resource-dialect",
    "dynamic-ref",
    "recursive-ref",
)
_CYCLE11_PLANTED = (
    ("tilde", "#/$defs/x~2y", "x~2y"),
    ("percent-zz", "#/$defs/%ZZ", "%ZZ"),
    ("percent-final", "#/$defs/a%", "a%"),
    ("percent-ff", "#/$defs/%FF", "\ufffd"),
)
_CYCLE11_ADDITIONAL = ("anchor", "non-string-id", "unresolvable-ref", "string-id")
# non-string-id and string-id reach _mcp. anchor and unresolvable-ref are
# rejected by the contract symbol table in ir.py before _mcp. ir.py is not a
# file of this option, so those two contents are RED only on the delivered
# origin. The generated origin covers the two contents that reach _mcp.
_CYCLE11_GENERATED_ADDITIONAL = ("non-string-id", "string-id")
_CYCLE11_CONTAINERS = ("root", "nested-non-resource")
_CYCLE11_SIBLINGS = ("simple", "resource")


def _cycle11_fixed_base(field: str, index: int = 0) -> str:
    """B1 base. No production import. Schemas in this section declare no $id at the root."""
    return f"urn:ocor:embedded-tool:{index}:{field}"


def _cycle11_library_registry(schema: Mapping[str, Any], field: str) -> Any:
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    base = _cycle11_fixed_base(field)
    resource = DRAFT202012.create_resource(schema)
    return Registry().with_resource(base, resource)


def _cycle11_library_accepts(schema: Mapping[str, Any], field: str = "inputSchema") -> Any:
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(schema)
    return _cycle11_library_registry(schema, field)


def _cycle11_keyword_schema(case_id: str) -> tuple[dict[str, Any], str]:
    draft = _CYCLE11_DRAFT07
    dialect = "MCP schema dialect must be JSON Schema 2020-12"
    dynamic = "MCP $ref resolution does not follow dynamic references"
    if case_id == "root-dialect":
        body = {
            "type": "object",
            "$schema": draft,
            "properties": {"n": {"type": "string"}},
        }
        return body, dialect
    if case_id == "nested-dialect":
        body = {
            "type": "object",
            "properties": {"inner": {"$schema": draft, "type": "string"}},
        }
        return body, dialect
    if case_id == "resource-dialect":
        body = {
            "type": "object",
            "properties": {
                "child": {
                    "$id": "https://cycle11.invalid/child.json",
                    "$schema": draft,
                    "type": "object",
                }
            },
        }
        return body, dialect
    if case_id == "dynamic-ref":
        return {"type": "object", "$dynamicRef": "#x"}, dynamic
    if case_id == "recursive-ref":
        return {"type": "object", "$recursiveRef": "#"}, dynamic
    raise AssertionError(case_id)


def _cycle11_additional_schema(content: str) -> dict[str, Any]:
    if content == "anchor":
        return {
            "type": "object",
            "$defs": {"a": {"$anchor": "x", "type": "string"}},
            "additionalItems": {"$anchor": "x", "type": "number"},
            "properties": {"p": {"$ref": "#x"}},
        }
    if content == "non-string-id":
        return {"type": "object", "additionalItems": {"$id": 1, "type": "string"}}
    if content == "unresolvable-ref":
        return {"type": "object", "additionalItems": {"$ref": "#/$defs/missing"}}
    if content == "string-id":
        return {
            "type": "object",
            "additionalItems": {
                "$id": "https://cycle11.invalid/extra.json",
                "type": "string",
            },
        }
    raise AssertionError(content)


def _cycle11_deliver(schema: Mapping[str, Any], field: str) -> dict[str, Any]:
    document = _bare_descriptor()
    document["tools"][0][field] = dict(schema)
    return document


def _cycle11_generate(schema: Mapping[str, Any], field: str) -> dict[str, Any]:
    kwargs = {"input_schema": schema} if field == "inputSchema" else {"output_schema": schema}
    documents = _with_contracts(
        _contract("urn:ocor:contract:cycle11-red", **kwargs)
    )
    document, _raw = _descriptor(documents)
    return document


def _cycle11_def_names(node: object) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        defs = node.get("$defs")
        if isinstance(defs, dict):
            found.update(name for name in defs if isinstance(name, str))
        for value in node.values():
            found.update(_cycle11_def_names(value))
    elif isinstance(node, list):
        for value in node:
            found.update(_cycle11_def_names(value))
    return found


def _cycle11_unreachable_schema(container: str, sibling: str) -> dict[str, Any]:
    if sibling == "simple":
        body: dict[str, Any] = {"type": "integer"}
    elif sibling == "resource":
        body = {"$id": "https://v.invalid/r.json", "type": "string"}
    else:
        raise AssertionError(sibling)
    if container == "root":
        return {
            "type": "object",
            "$defs": {"unused": body},
            "properties": {"p": {"type": "string"}},
        }
    if container == "nested-non-resource":
        return {
            "type": "object",
            "properties": {
                "h": {
                    "type": "object",
                    "$defs": {"unused": body},
                    "properties": {"s": {"type": "string"}},
                }
            },
        }
    raise AssertionError(container)


@pytest.mark.parametrize("field", _CYCLE10_FIELDS)
@pytest.mark.parametrize("case_id", _CYCLE11_KEYWORD_CASES)
def test_cycle11_vf001_generator_refuses_profile_keyword_rules(
    field: str, case_id: str
) -> None:
    """VF-001: an emitted schema must fail the shared profile rule before artifacts return.

    The libraries accept the schema. The delivered twin already fails closed.
    The generator still returns the descriptor. Rule 3 is dialect 2020-12 and
    the refusal of ``$dynamicRef`` and ``$recursiveRef``.
    """
    schema, message = _cycle11_keyword_schema(case_id)
    _cycle11_library_accepts(schema, field)
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    with pytest.raises(profile.McpProfileError) as delivered:
        _validate(_cycle11_deliver(schema, field))
    assert message in str(delivered.value)
    with pytest.raises(C1Error) as generated:
        _cycle11_generate(schema, field)
    assert message in str(generated.value)


@pytest.mark.parametrize("field", _CYCLE10_FIELDS)
@pytest.mark.parametrize(("label", "ref", "key"), _CYCLE11_PLANTED)
def test_cycle11_vf002_planted_pointer_follows_the_libraries(
    field: str, label: str, ref: str, key: str
) -> None:
    """VF-002: a planted literal key follows referencing, including ``~2`` and loose percent forms.

    ``label`` keeps the parameter in the node id. No stricter rule without a
    contract source remains. The generated origin cannot carry these ``$ref``
    spellings: the contract symbol table rejects them before ``_mcp``.
    """
    del label
    from jsonschema import Draft202012Validator

    schema = {
        "type": "object",
        "properties": {"p": {"$ref": ref}},
        "$defs": {key: {"type": "string"}},
    }
    registry = _cycle11_library_accepts(schema, field)
    target = registry.resolver(_cycle11_fixed_base(field)).lookup(ref)
    assert target.contents == {"type": "string"}
    validator = Draft202012Validator(schema, registry=registry)
    assert list(validator.iter_errors({"p": "a"})) == []
    assert list(validator.iter_errors({"p": 1})) != []
    try:
        _validate(_cycle11_deliver(schema, field))
    except Exception as exc:
        profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
        if isinstance(exc, profile.McpProfileError):
            pytest.fail(f"profile refused a reference the libraries resolve: {exc}")
        raise


@pytest.mark.parametrize("field", _CYCLE10_FIELDS)
@pytest.mark.parametrize("content", _CYCLE11_ADDITIONAL)
def test_cycle11_vf003_delivered_additional_items_follow_the_libraries(
    field: str, content: str
) -> None:
    """VF-003: ``additionalItems`` is not a 2020-12 keyword, so the profile does not index it."""
    schema = _cycle11_additional_schema(content)
    registry = _cycle11_library_accepts(schema, field)
    if content == "anchor":
        resolved = registry.resolver(_cycle11_fixed_base(field)).lookup("#x")
        assert resolved.contents == {"$anchor": "x", "type": "string"}
    try:
        _validate(_cycle11_deliver(schema, field))
    except Exception as exc:
        profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
        if isinstance(exc, profile.McpProfileError):
            pytest.fail(
                f"profile indexed additionalItems ({content}) against the libraries: {exc}"
            )
        raise


@pytest.mark.parametrize("field", _CYCLE10_FIELDS)
def test_cycle11_vf003_items_remain_indexed(field: str) -> None:
    """Negative: ``items`` is a real keyword, so an unresolvable ref there stays refused."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    schema = {"type": "array", "items": {"$ref": "#/$defs/missing"}}
    with pytest.raises(profile.McpProfileError):
        _validate(_cycle11_deliver(schema, field))


@pytest.mark.parametrize("field", _CYCLE10_FIELDS)
@pytest.mark.parametrize("content", _CYCLE11_GENERATED_ADDITIONAL)
def test_cycle11_vf003_generated_additional_items_follow_the_libraries(
    field: str, content: str
) -> None:
    """VF-003: the generator uses the same enumeration and emits what the libraries accept."""
    schema = _cycle11_additional_schema(content)
    _cycle11_library_accepts(schema, field)
    try:
        document = _cycle11_generate(schema, field)
    except C1Error as exc:
        pytest.fail(f"generator refused additionalItems {content}: {exc}")
    _validate(document)


def test_cycle11_vf004_oracles_do_not_call_a_production_base() -> None:
    """VF-004: the 63 oracle helpers must not call ``operational_base`` or import the profile."""
    forbidden_import = "from ocor_runtime.c1.mcp_profile import operational_base"
    for helper in (_cycle6_schema_alone, _cycle10_static_library):
        source = inspect.getsource(helper)
        assert forbidden_import not in source
        assert "operational_base(" not in source


@pytest.mark.parametrize("container", _CYCLE11_CONTAINERS)
@pytest.mark.parametrize("sibling", _CYCLE11_SIBLINGS)
def test_cycle11_vf008_unreachable_user_definition_is_omitted(
    container: str, sibling: str
) -> None:
    """VF-008: an unreachable user definition is omitted, including a resource under a non-resource."""
    schema = _cycle11_unreachable_schema(container, sibling)
    document = _cycle11_generate(schema, "inputSchema")
    emitted = document["tools"][0]["inputSchema"]
    assert "unused" not in _cycle11_def_names(emitted)
