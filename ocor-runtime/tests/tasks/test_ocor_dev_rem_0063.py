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


def _contract(contract_id: str, *, input_schema: Mapping[str, Any] | None = None, kind: str = "MCP_TOOL") -> dict[str, Any]:
    return {
        "construct": "ContractDefinition",
        "contract_id": contract_id,
        "kind": kind,
        "input_schema": dict(input_schema or {"type": "object", "properties": {"name": {"type": "string"}}}),
        "output_schema": {"type": "object"},
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
    assert "urn.ocor.type.vessel" in document["$defs"]
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
    """ADD v1.3 line 382: the projected input schema drops a top-level overwrite."""
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
    _validate(document)
    planted = copy.deepcopy(document)
    planted["tools"][0]["inputSchema"]["properties"]["governed_context_ref"] = {"type": "string"}
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    with pytest.raises(profile.McpProfileError):
        _validate(planted)


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
    document, _ = _descriptor()
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
    """A descriptor whose anyOf list has indexes 0 through 10."""
    document = _bare_descriptor()
    document["$defs"] = {
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
