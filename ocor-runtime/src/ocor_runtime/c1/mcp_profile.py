"""MCP profile checks for the descriptor the C1 generator emits.

FABLE52-POST-POC-PROGRAMME (2026-11-11) point 1. The governed protocol revision is
the constant on the C1 generator; this module does not declare it. Callers pass the
revision they expect. The checks implement the revision's Tool shape and its rules
for JSON Schema 2020-12 ``$ref`` resolution: same-document fragments only, no network
fetch, and a fixed bound on schema depth and node count. ADD v1.3 line 382: a
top-level ``governed_context_ref`` is transport-origin and is not part of the tool
input schema.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, UnknownType
from referencing import Registry, Resource
from referencing.exceptions import CannotDetermineSpecification

# Library failures on a tampered fixture or schema are profile errors. The caller
# never sees TypeError, UnknownType or CannotDetermineSpecification.
_SCHEMA_LIBRARY_ERRORS = (SchemaError, UnknownType, CannotDetermineSpecification, TypeError, ValueError)

OFFICIAL_SCHEMA_URI = "https://modelcontextprotocol.io/schema/2026-07-28/schema.json"
CONTEXT_FIELD = "governed_context_ref"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
ACCEPTED_DIALECTS = frozenset({DRAFT_2020_12, DRAFT_2020_12 + "#"})
MAX_SCHEMA_DEPTH = 32
MAX_SCHEMA_NODES = 4096
# Applicator keywords whose values are schemas. Map keys are names, not keywords.
_SCHEMA_MAP_KEYWORDS = frozenset(
    {"$defs", "definitions", "dependentSchemas", "patternProperties", "properties"}
)
_SCHEMA_OBJECT_KEYWORDS = frozenset(
    {
        "additionalItems",
        "additionalProperties",
        "contains",
        "contentSchema",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)
_SCHEMA_ARRAY_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})


class McpProfileError(ValueError):
    """The MCP profile rejected a descriptor or an input schema."""

    def __init__(self, message: str) -> None:
        if not isinstance(message, str) or not message or len(message) > 512:
            raise ValueError("MCP profile message must be bounded and non-empty")
        super().__init__(message)


def without_context_overwrite(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return an MCP input schema with a top-level transport field removed.

    A schema whose root is not ``type: object`` is rejected. OCOR does not wrap it
    and does not set ``additionalProperties``. Only the top-level property and
    ``required`` entry named ``governed_context_ref`` are removed.
    """

    if not isinstance(schema, Mapping) or schema.get("type") != "object":
        raise McpProfileError("MCP input schema must declare type object")
    projected = dict(schema)
    properties = projected.get("properties")
    if properties is not None and not isinstance(properties, Mapping):
        raise McpProfileError("MCP input schema properties must be an object")
    if isinstance(properties, Mapping) and CONTEXT_FIELD in properties:
        projected["properties"] = {key: value for key, value in properties.items() if key != CONTEXT_FIELD}
    required = projected.get("required")
    if required is not None and not isinstance(required, Sequence):
        raise McpProfileError("MCP input schema required must be a list")
    if isinstance(required, str) or isinstance(required, bytes):
        raise McpProfileError("MCP input schema required must be a list")
    if isinstance(required, Sequence) and CONTEXT_FIELD in required:
        kept = [item for item in required if item != CONTEXT_FIELD]
        if kept:
            projected["required"] = kept
        else:
            projected.pop("required", None)
    return projected


def validate_mcp_descriptor(
    document: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    expected_revision: str,
) -> None:
    """Fail closed when ``document`` is not a descriptor of ``expected_revision``.

    ``schema`` is the official schema document of that revision. Each tool is checked
    against its ``Tool`` definition. ``inputSchema`` and ``outputSchema`` are JSON
    Schema 2020-12 schemas (``Draft202012Validator.check_schema``). Every ``$ref`` is
    a same-document fragment: the fragment is percent-decoded as UTF-8 before JSON
    Pointer resolution, and the value it lands on must itself be a 2020-12 schema.
    A fixture that is not an object, or whose ``$defs`` or ``Tool`` entry is not an
    object, is rejected before the library is called.
    """

    if not isinstance(document, Mapping):
        raise McpProfileError("MCP descriptor must be an object")
    if not isinstance(expected_revision, str) or not expected_revision:
        raise McpProfileError("MCP revision check needs the expected revision")
    if document.get("x-ocor-mcp-protocol-revision") != expected_revision:
        raise McpProfileError("MCP descriptor revision does not match the governed revision")
    tools = document.get("tools")
    if not isinstance(tools, list):
        raise McpProfileError("MCP descriptor tools must be a list")
    names: list[str] = []
    for tool in tools:
        if not isinstance(tool, Mapping) or not isinstance(tool.get("name"), str) or not tool["name"]:
            raise McpProfileError("MCP tool name must be a non-empty string")
        names.append(str(tool["name"]))
    if names != sorted(names) or len(names) != len(set(names)):
        raise McpProfileError("MCP tools are not in deterministic name order")
    _walk_json(document, depth=1, nodes=[0])
    # Keyword checks start at schema objects. Property names, const, default and enum
    # are instance data and are not read as keywords.
    _check_schema_keywords(document, document, depth=1)
    for tool in tools:
        if isinstance(tool, Mapping):
            for field in ("inputSchema", "outputSchema"):
                if field in tool:
                    _check_schema_keywords(tool[field], document, depth=1)
    for tool in tools:
        if not isinstance(tool, Mapping):
            raise McpProfileError("MCP tool must be an object")
        _reject_context_overwrite(tool.get("inputSchema"))
    _validate_tools(tools, schema)


def _reject_context_overwrite(schema: object) -> None:
    if not isinstance(schema, Mapping):
        raise McpProfileError("MCP input schema must be an object")
    properties = schema.get("properties")
    required = schema.get("required")
    if isinstance(properties, Mapping) and CONTEXT_FIELD in properties:
        raise McpProfileError("MCP input schema cannot overwrite governed_context_ref")
    if isinstance(required, Sequence) and not isinstance(required, str) and CONTEXT_FIELD in required:
        raise McpProfileError("MCP input schema cannot overwrite governed_context_ref")


def _validate_tools(tools: list[Any], schema: Mapping[str, Any]) -> None:
    if not isinstance(schema, Mapping):
        raise McpProfileError("official MCP schema fixture has no Tool definition")
    definitions = schema.get("$defs")
    tool_definition = definitions.get("Tool") if isinstance(definitions, Mapping) else None
    if not isinstance(tool_definition, Mapping):
        raise McpProfileError("official MCP schema fixture has no Tool definition")
    try:
        validator = Draft202012Validator(
            {"$ref": OFFICIAL_SCHEMA_URI + "#/$defs/Tool"},
            registry=Registry().with_resource(OFFICIAL_SCHEMA_URI, Resource.from_contents(dict(schema))),
        )
    except _SCHEMA_LIBRARY_ERRORS as exc:
        raise McpProfileError("official MCP schema fixture is not a JSON Schema") from exc
    for index, tool in enumerate(tools):
        if not isinstance(tool, Mapping):
            raise McpProfileError("MCP tool must be an object")
        try:
            errors = sorted(
                validator.iter_errors(tool),
                key=lambda item: tuple(str(part) for part in item.absolute_path),
            )
        except _SCHEMA_LIBRARY_ERRORS as exc:
            raise McpProfileError("official MCP schema fixture is not a JSON Schema") from exc
        if errors:
            detail = errors[0].message.replace("\n", " ")
            if len(detail) > 240:
                detail = detail[:240]
            raise McpProfileError(f"MCP tool {index} is not a Tool of the pinned revision: {detail}")
        _require_draft_2020_12(tool.get("inputSchema"), index, "inputSchema")
        if "outputSchema" in tool:
            _require_draft_2020_12(tool["outputSchema"], index, "outputSchema")


def _require_draft_2020_12(schema: object, index: int, field: str) -> None:
    """Reject a tool schema that is not a JSON Schema 2020-12 object.

    FABLE52-POST-POC-PROGRAMME (2026-11-11) point 1(a) requires each ``inputSchema``
    and ``outputSchema`` to be a 2020-12 schema. Matching the ``Tool`` definition is
    not enough: that definition allows any extra keyword value.
    """

    if not isinstance(schema, Mapping):
        raise McpProfileError(f"MCP tool {index} {field} must be a JSON Schema 2020-12 object")
    try:
        Draft202012Validator.check_schema(schema)
    except _SCHEMA_LIBRARY_ERRORS as exc:
        raise McpProfileError(f"MCP tool {index} {field} is not a JSON Schema 2020-12 schema") from exc


def _walk_json(node: object, *, depth: int, nodes: list[int]) -> None:
    """Reject values that are not bounded JSON. This walk does not read keywords."""
    nodes[0] += 1
    if nodes[0] > MAX_SCHEMA_NODES or depth > MAX_SCHEMA_DEPTH:
        raise McpProfileError("MCP schema exceeds the revision bounds")
    if isinstance(node, str):
        _reject_surrogate(node)
        return
    if isinstance(node, bool) or node is None or isinstance(node, int):
        return
    if isinstance(node, float):
        if not math.isfinite(node):
            raise McpProfileError("MCP descriptor contains a non-finite number")
        return
    if isinstance(node, (bytes, bytearray)):
        raise McpProfileError("MCP descriptor contains a value that is not JSON")
    if isinstance(node, Sequence) and not isinstance(node, str):
        for item in node:
            _walk_json(item, depth=depth + 1, nodes=nodes)
        return
    if not isinstance(node, Mapping):
        raise McpProfileError("MCP descriptor contains a value that is not JSON")
    for key in node:
        if isinstance(key, str):
            _reject_surrogate(key)
        else:
            raise McpProfileError("MCP descriptor contains a value that is not JSON")
    for value in node.values():
        _walk_json(value, depth=depth + 1, nodes=nodes)


def _check_schema_keywords(node: object, document: Mapping[str, Any], *, depth: int) -> None:
    """Apply dialect and ``$ref`` rules only to schema objects, not to instance data."""
    if depth > MAX_SCHEMA_DEPTH:
        raise McpProfileError("MCP schema exceeds the revision bounds")
    if not isinstance(node, Mapping):
        return
    if "$dynamicRef" in node or "$recursiveRef" in node:
        raise McpProfileError("MCP $ref resolution does not follow dynamic references")
    if "$schema" in node:
        dialect = node["$schema"]
        if not isinstance(dialect, str) or dialect not in ACCEPTED_DIALECTS:
            raise McpProfileError("MCP schema dialect must be JSON Schema 2020-12")
    if "$ref" in node:
        reference = node["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#"):
            raise McpProfileError("MCP $ref must be a same-document fragment")
        _resolve_pointer(document, reference)
    for key, value in node.items():
        if key in _SCHEMA_MAP_KEYWORDS and isinstance(value, Mapping):
            for child in value.values():
                _check_schema_keywords(child, document, depth=depth + 1)
            continue
        if key in _SCHEMA_ARRAY_KEYWORDS and isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for child in value:
                _check_schema_keywords(child, document, depth=depth + 1)
            continue
        if key in _SCHEMA_OBJECT_KEYWORDS:
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                for child in value:
                    _check_schema_keywords(child, document, depth=depth + 1)
            else:
                _check_schema_keywords(value, document, depth=depth + 1)


_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _decode_uri_fragment(fragment: str) -> str:
    """Percent-decode a URI fragment as strict UTF-8.

    RFC 6901 section 6 percent-encodes the JSON Pointer. Decoding happens before
    ``/`` splits the pointer and before ``~`` escapes. A truncated escape, a
    non-hex pair, or bytes that are not UTF-8 is a typed profile error. ``+``
    is not a space.
    """

    pending = bytearray()
    parts: list[str] = []

    def flush() -> None:
        if not pending:
            return
        try:
            parts.append(pending.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise McpProfileError("MCP $ref fragment is not valid UTF-8") from exc
        pending.clear()

    index = 0
    length = len(fragment)
    while index < length:
        character = fragment[index]
        if character == "%":
            if index + 2 >= length:
                raise McpProfileError("MCP $ref fragment is not valid percent-encoding")
            first = fragment[index + 1]
            second = fragment[index + 2]
            if first not in _HEX_DIGITS or second not in _HEX_DIGITS:
                raise McpProfileError("MCP $ref fragment is not valid percent-encoding")
            pending.append(int(fragment[index + 1 : index + 3], 16))
            index += 3
            continue
        flush()
        if 0xD800 <= ord(character) <= 0xDFFF:
            raise McpProfileError("MCP $ref fragment is not valid UTF-8")
        parts.append(character)
        index += 1
    flush()
    return "".join(parts)


def _require_schema(target: object) -> None:
    """The value a ``$ref`` lands on must be a JSON Schema 2020-12 schema.

    Boolean schemas are schemas. Numbers, strings, null, arrays and objects the
    metaschema rejects are not. Callers pass only a resolved target, never
    instance data such as ``const``, ``enum`` or ``default``. ``bool`` is a
    subclass of ``int``, so the boolean check comes before any numeric test.
    """

    if isinstance(target, bool):
        Draft202012Validator.check_schema(target)
        return
    if not isinstance(target, Mapping):
        raise McpProfileError("MCP $ref target is not a JSON Schema 2020-12 schema")
    try:
        Draft202012Validator.check_schema(target)
    except _SCHEMA_LIBRARY_ERRORS as exc:
        raise McpProfileError("MCP $ref target is not a JSON Schema 2020-12 schema") from exc


def _resolve_pointer(document: Mapping[str, Any], pointer: str) -> None:
    if not isinstance(pointer, str) or not pointer.startswith("#"):
        raise McpProfileError("MCP $ref must be a same-document fragment")
    if pointer == "#":
        _require_schema(document)
        return
    decoded = _decode_uri_fragment(pointer[1:])
    if not decoded.startswith("/"):
        raise McpProfileError("MCP $ref must be a same-document fragment")
    current: object = document
    for raw in decoded[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and token in current:
            current = current[token]
            continue
        if isinstance(current, list) and _array_index(token) is not None:
            index = _array_index(token)
            assert index is not None
            if index < len(current):
                current = current[index]
                continue
        raise McpProfileError("MCP $ref does not resolve in the descriptor")
    _require_schema(current)


def _reject_surrogate(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise McpProfileError("MCP descriptor contains a lone surrogate")


def _array_index(token: str) -> int | None:
    """Return a canonical JSON Pointer array index.

    One ASCII digit is an index. A longer index cannot have a leading zero.
    A non-ASCII digit is not an index.
    """
    if not token.isascii() or not token.isdigit():
        return None
    if len(token) > 1 and token[0] == "0":
        return None
    return int(token)
