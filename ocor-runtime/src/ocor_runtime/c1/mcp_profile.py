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
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

OFFICIAL_SCHEMA_URI = "https://modelcontextprotocol.io/schema/2026-07-28/schema.json"
CONTEXT_FIELD = "governed_context_ref"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
ACCEPTED_DIALECTS = frozenset({DRAFT_2020_12, DRAFT_2020_12 + "#"})
MAX_SCHEMA_DEPTH = 32
MAX_SCHEMA_NODES = 4096


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
    against its ``Tool`` definition. ``inputSchema`` and ``outputSchema`` stay JSON
    Schema 2020-12, and every ``$ref`` resolves inside ``document``.
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
    _walk(document, document, depth=1, nodes=[0])
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
    if not isinstance(schema, Mapping) or "Tool" not in schema.get("$defs", {}):
        raise McpProfileError("official MCP schema fixture has no Tool definition")
    try:
        validator = Draft202012Validator(
            {"$ref": OFFICIAL_SCHEMA_URI + "#/$defs/Tool"},
            registry=Registry().with_resource(OFFICIAL_SCHEMA_URI, Resource.from_contents(dict(schema))),
        )
    except SchemaError as exc:
        raise McpProfileError("official MCP schema fixture is not a JSON Schema") from exc
    for index, tool in enumerate(tools):
        errors = sorted(validator.iter_errors(tool), key=lambda item: tuple(str(part) for part in item.absolute_path))
        if errors:
            detail = errors[0].message.replace("\n", " ")
            if len(detail) > 240:
                detail = detail[:240]
            raise McpProfileError(f"MCP tool {index} is not a Tool of the pinned revision: {detail}")


def _walk(node: object, document: Mapping[str, Any], *, depth: int, nodes: list[int]) -> None:
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
            _walk(item, document, depth=depth + 1, nodes=nodes)
        return
    if not isinstance(node, Mapping):
        raise McpProfileError("MCP descriptor contains a value that is not JSON")
    for key in node:
        if isinstance(key, str):
            _reject_surrogate(key)
        else:
            raise McpProfileError("MCP descriptor contains a value that is not JSON")
    if "$dynamicRef" in node or "$recursiveRef" in node:
        raise McpProfileError("MCP $ref resolution does not follow dynamic references")
    dialect = node.get("$schema")
    if dialect is not None and dialect not in ACCEPTED_DIALECTS:
        raise McpProfileError("MCP schema dialect must be JSON Schema 2020-12")
    reference = node.get("$ref")
    if reference is not None:
        if not isinstance(reference, str) or not reference.startswith("#"):
            raise McpProfileError("MCP $ref must be a same-document fragment")
        _resolve_pointer(document, reference)
    for value in node.values():
        _walk(value, document, depth=depth + 1, nodes=nodes)


def _resolve_pointer(document: Mapping[str, Any], pointer: str) -> None:
    if pointer == "#":
        return
    if not pointer.startswith("#/"):
        raise McpProfileError("MCP $ref must be a same-document fragment")
    current: object = document
    for raw in pointer[2:].split("/"):
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


def _reject_surrogate(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise McpProfileError("MCP descriptor contains a lone surrogate")


def _array_index(token: str) -> int | None:
    if token == "0" or (len(token) > 1 and token[0] != "0" and token.isascii() and token.isdigit()):
        return int(token)
    return None
