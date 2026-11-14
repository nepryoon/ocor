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


def _with_ref(ref: str, definitions: Mapping[str, Any], *, field: str = "inputSchema") -> dict[str, Any]:
    """Point a tool schema at ``ref``. Definitions live on the descriptor."""
    document = _bare_descriptor()
    document["$defs"] = dict(definitions)
    schema = document["tools"][0][field]
    if not isinstance(schema, dict):
        raise AssertionError("tool schema is not an object")
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
    """VF-001 and the schema-shaped targets of VF-002. Decode, then resolve."""
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
# The resolver before ``_decode_uri_fragment`` accepts that key. The decoder
# must refuse first, for percent-encoding or UTF-8, not for a missing key.
# Members: truncated escape, non-hex, incomplete UTF-8, bad continuation,
# overlong, surrogate, lone continuation, the same bytes after other text,
# a bad escape after a well-formed encoding, and a bad escape that is not
# the last pointer segment.
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
    """The refusal is the encoding check. The literal key would otherwise resolve."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    document = _with_ref(ref, definitions)
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
    document["$defs"] = {"bad": 7, "a b": {"type": "string"}}
    body = document["tools"][0]["inputSchema"]
    if not isinstance(body, dict):
        raise AssertionError("input schema is not an object")
    body["const"] = {"$ref": "#/$defs/bad"}
    body["default"] = {"$ref": "#/$defs/a%20b"}
    body["enum"] = [{"$ref": "https://example.invalid/%20"}, {"$ref": "#/$defs/%"}]
    _validate(document)


def test_an_unreferenced_non_schema_definition_is_not_a_resolved_target() -> None:
    """Only a target a $ref lands on is checked. An unused definition stays data."""
    document = _bare_descriptor()
    document["$defs"] = {"unused": 7}
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
    """Point one tool schema at ``target`` through ``location`` or ``$defs``."""
    document = _bare_descriptor()
    if location == "const":
        document["$defs"] = {"holder": {"const": target}}
        ref = "#/$defs/holder/const"
    elif location == "default":
        document["$defs"] = {"holder": {"default": target}}
        ref = "#/$defs/holder/default"
    elif location == "enum":
        document["$defs"] = {"holder": {"enum": [target]}}
        ref = "#/$defs/holder/enum/0"
    elif location == "example":
        document["$defs"] = {"holder": {"example": target}}
        ref = "#/$defs/holder/example"
    elif location == "defs":
        document["$defs"] = {"target": target}
        ref = "#/$defs/target"
    else:
        raise AssertionError(location)
    schema = document["tools"][0][field]
    if not isinstance(schema, dict):
        raise AssertionError("tool schema is not an object")
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
    """A reached schema may itself point at a local schema. That hop is checked."""
    document = _cycle3_reached({"$ref": "#/$defs/good"}, location=location)
    document["$defs"]["good"] = {"type": "string"}
    _validate(document)
    nested = _cycle3_reached(
        {"properties": {"name": {"$ref": "#/$defs/good"}}},
        location=location,
    )
    nested["$defs"]["good"] = {"type": "string"}
    _validate(nested)


def test_cycle3_a_self_ref_through_const_stays_inside_the_visited_set() -> None:
    """A cycle through instance data is one visited schema, not an unbounded walk."""
    document = _bare_descriptor()
    document["$defs"] = {"holder": {"const": {"$ref": "#/$defs/holder/const"}}}
    body = document["tools"][0]["inputSchema"]
    if not isinstance(body, dict):
        raise AssertionError("input schema is not an object")
    body["properties"] = {"name": {"$ref": "#/$defs/holder/const"}}
    _validate(document)


def test_cycle3_a_long_data_position_chain_still_hits_the_depth_bound() -> None:
    """The depth limit is unchanged. A short chain passes and a 40-hop chain fails."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")

    def chain(length: int) -> dict[str, Any]:
        document = _bare_descriptor()
        definitions: dict[str, Any] = {}
        for index in range(length):
            nxt = f"#/$defs/h{index + 1}/const" if index + 1 < length else "#/$defs/leaf"
            definitions[f"h{index}"] = {"const": {"$ref": nxt}}
        definitions["leaf"] = {"type": "string"}
        document["$defs"] = definitions
        body = document["tools"][0]["inputSchema"]
        if not isinstance(body, dict):
            raise AssertionError("input schema is not an object")
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
    document["$defs"] = {
        "holder": {"const": target, "default": copy.deepcopy(target), "enum": [copy.deepcopy(target)]}
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
    """VF-002: ``~`` introduces only ``~0`` or ``~1``, even if the literal key exists."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")
    if "/" in token:
        document = _bare_descriptor()
        # Segment ``type`` lands on a schema when the bad escape is treated as a literal key.
        document["$defs"] = {key: {"type": {"type": "string"}}}
        body = document["tools"][0]["inputSchema"]
        if not isinstance(body, dict):
            raise AssertionError("input schema is not an object")
        body["properties"] = {"name": {"$ref": "#/$defs/" + token}}
    else:
        document = _with_ref("#/$defs/" + token, {key: {"type": "string"}})
    with pytest.raises(profile.McpProfileError, match="JSON Pointer"):
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
    """Point one tool schema at ``ref``. ``definitions`` are the descriptor ``$defs``."""
    return _with_ref(ref, definitions, field=field)


def _cycle4_library_contents(document: Mapping[str, Any], ref: str) -> Any:
    """Return the schema the pinned resolver yields for a same-document ``ref``."""
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    resource = Resource.from_contents({"$schema": DRAFT_2020, **dict(document)}, DRAFT202012)
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
        resource = Resource.from_contents({"$schema": DRAFT_2020, **document}, DRAFT202012)
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
    """``#p%61rt`` decodes to ``part``. The slash test is what forces this order."""
    document = _cycle4_anchor_document("#p%61rt", {"part": {"$anchor": "part", "type": "integer"}})
    _validate(document)


def test_cycle4_a_percent_encoded_slash_stays_a_json_pointer() -> None:
    """``#%2F`` decodes to ``/``, so the fragment is a pointer, not an anchor."""
    document = _cycle4_anchor_document(
        "#%2F$defs/part",
        {"part": {"$anchor": "part", "type": "integer"}},
    )
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
    """An anchor that points at itself is one visited schema, not a recursive walk."""
    document = _bare_descriptor()
    document["$defs"] = {"part": {"$anchor": "part", "$ref": "#part"}}
    body = document["tools"][0]["inputSchema"]
    if not isinstance(body, dict):
        raise AssertionError("input schema is not an object")
    body["properties"] = {"name": {"$ref": "#part"}}
    _validate(document)


def test_cycle4_an_anchor_hop_does_not_lift_the_depth_bound() -> None:
    """The last hop is an anchor. Four hops pass and forty still hit the bound."""
    profile = importlib.import_module("ocor_runtime.c1.mcp_profile")

    def chain(length: int) -> dict[str, Any]:
        document = _bare_descriptor()
        definitions: dict[str, Any] = {"leaf": {"$anchor": "leaf", "type": "string"}}
        for index in range(length):
            nxt = f"#/$defs/h{index + 1}/const" if index + 1 < length else "#leaf"
            definitions[f"h{index}"] = {"const": {"$ref": nxt}}
        document["$defs"] = definitions
        body = document["tools"][0]["inputSchema"]
        if not isinstance(body, dict):
            raise AssertionError("input schema is not an object")
        body["properties"] = {"name": {"$ref": "#/$defs/h0/const"}}
        return document

    _validate(chain(4))
    with pytest.raises(profile.McpProfileError, match="bounds"):
        _validate(chain(40))
