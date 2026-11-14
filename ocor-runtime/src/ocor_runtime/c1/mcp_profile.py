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
_SCHEMA_LIBRARY_ERRORS = (
    SchemaError,
    UnknownType,
    CannotDetermineSpecification,
    TypeError,
    ValueError,
)

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
# Plain-name anchors indexed by the pinned referencing resolver for draft 2020-12.
_ANCHOR_KEYWORDS = ("$anchor", "$dynamicAnchor")


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
        projected["properties"] = {
            key: value for key, value in properties.items() if key != CONTEXT_FIELD
        }
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
    a same-document fragment. The fragment is percent-decoded as UTF-8, then
    classified: a decoded fragment that starts with ``/`` is a JSON Pointer, and any
    other decoded fragment is a plain-name anchor (``$anchor`` or ``$dynamicAnchor``).
    ``~`` escapes are validated before substitution. A ref inside an embedded tool
    schema resolves in that schema first and in the descriptor second. Two different
    objects for one pointer or one plain name are rejected. A nested non-empty
    ``$id`` is a separate resource, and ``additionalItems`` is not an anchor
    applicator in draft 2020-12. The value a reference lands on must itself be a
    2020-12 schema. Dialect, local-reference and resolution rules also apply to a
    schema reached through instance data such as ``const`` or ``default``.
    A fixture that is not an object, or whose ``$defs`` or ``Tool`` entry is not an
    object, is rejected before the library is called.
    """

    if not isinstance(document, Mapping):
        raise McpProfileError("MCP descriptor must be an object")
    if not isinstance(expected_revision, str) or not expected_revision:
        raise McpProfileError("MCP revision check needs the expected revision")
    if document.get("x-ocor-mcp-protocol-revision") != expected_revision:
        raise McpProfileError(
            "MCP descriptor revision does not match the governed revision"
        )
    tools = document.get("tools")
    if not isinstance(tools, list):
        raise McpProfileError("MCP descriptor tools must be a list")
    names: list[str] = []
    for tool in tools:
        if (
            not isinstance(tool, Mapping)
            or not isinstance(tool.get("name"), str)
            or not tool["name"]
        ):
            raise McpProfileError("MCP tool name must be a non-empty string")
        names.append(str(tool["name"]))
    if names != sorted(names) or len(names) != len(set(names)):
        raise McpProfileError("MCP tools are not in deterministic name order")
    _walk_json(document, depth=1, nodes=[0])
    # Keyword checks start at schema objects. Property names, const, default and enum
    # are instance data and are not read as keywords. A schema a ``$ref`` actually
    # reaches is checked afterwards, including one stored in that instance data.
    seen: set[int] = set()
    deferred: dict[int, tuple[Any, int, Mapping[str, Any], Mapping[str, Any]]] = {}
    _check_schema_keywords(
        document,
        document,
        pointer_root=document,
        resource_root=document,
        depth=1,
        seen=seen,
        deferred=deferred,
    )
    for tool in tools:
        if isinstance(tool, Mapping):
            for field in ("inputSchema", "outputSchema"):
                if field in tool:
                    tool_schema = tool[field]
                    _check_schema_keywords(
                        tool_schema,
                        document,
                        pointer_root=tool_schema
                        if isinstance(tool_schema, Mapping)
                        else document,
                        resource_root=document,
                        depth=1,
                        seen=seen,
                        deferred=deferred,
                    )
    while deferred:
        identity = min(deferred, key=lambda item: deferred[item][1])
        target, depth, pointer_root, resource_root = deferred.pop(identity)
        if identity in seen:
            continue
        _check_schema_keywords(
            target,
            document,
            pointer_root=pointer_root,
            resource_root=resource_root,
            depth=depth,
            seen=seen,
            deferred=deferred,
        )
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
    if (
        isinstance(required, Sequence)
        and not isinstance(required, str)
        and CONTEXT_FIELD in required
    ):
        raise McpProfileError("MCP input schema cannot overwrite governed_context_ref")


def _validate_tools(tools: list[Any], schema: Mapping[str, Any]) -> None:
    if not isinstance(schema, Mapping):
        raise McpProfileError("official MCP schema fixture has no Tool definition")
    definitions = schema.get("$defs")
    tool_definition = (
        definitions.get("Tool") if isinstance(definitions, Mapping) else None
    )
    if not isinstance(tool_definition, Mapping):
        raise McpProfileError("official MCP schema fixture has no Tool definition")
    try:
        validator = Draft202012Validator(
            {"$ref": OFFICIAL_SCHEMA_URI + "#/$defs/Tool"},
            registry=Registry().with_resource(
                OFFICIAL_SCHEMA_URI, Resource.from_contents(dict(schema))
            ),
        )
    except _SCHEMA_LIBRARY_ERRORS as exc:
        raise McpProfileError(
            "official MCP schema fixture is not a JSON Schema"
        ) from exc
    for index, tool in enumerate(tools):
        if not isinstance(tool, Mapping):
            raise McpProfileError("MCP tool must be an object")
        try:
            errors = sorted(
                validator.iter_errors(tool),
                key=lambda item: tuple(str(part) for part in item.absolute_path),
            )
        except _SCHEMA_LIBRARY_ERRORS as exc:
            raise McpProfileError(
                "official MCP schema fixture is not a JSON Schema"
            ) from exc
        if errors:
            detail = errors[0].message.replace("\n", " ")
            if len(detail) > 240:
                detail = detail[:240]
            raise McpProfileError(
                f"MCP tool {index} is not a Tool of the pinned revision: {detail}"
            )
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
        raise McpProfileError(
            f"MCP tool {index} {field} must be a JSON Schema 2020-12 object"
        )
    try:
        Draft202012Validator.check_schema(schema)
    except _SCHEMA_LIBRARY_ERRORS as exc:
        raise McpProfileError(
            f"MCP tool {index} {field} is not a JSON Schema 2020-12 schema"
        ) from exc


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


def _nonempty_id(node: object) -> bool:
    """A non-empty string ``$id`` starts another JSON Schema 2020-12 resource."""
    if not isinstance(node, Mapping):
        return False
    value = node.get("$id")
    return isinstance(value, str) and bool(value)


def _check_schema_keywords(
    node: object,
    document: Mapping[str, Any],
    *,
    pointer_root: Mapping[str, Any],
    resource_root: Mapping[str, Any],
    depth: int,
    seen: set[int],
    deferred: dict[int, tuple[Any, int, Mapping[str, Any], Mapping[str, Any]]],
) -> None:
    """Apply dialect and ``$ref`` rules only to schema objects, not to instance data."""
    if isinstance(node, Mapping) and _nonempty_id(node) and node is not resource_root:
        pointer_root = node
        resource_root = node
    if depth > MAX_SCHEMA_DEPTH:
        raise McpProfileError("MCP schema exceeds the revision bounds")
    if not isinstance(node, Mapping):
        return
    identity = id(node)
    if identity in seen:
        return
    seen.add(identity)
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
        _resolve_pointer(
            document,
            reference,
            pointer_root=pointer_root,
            resource_root=resource_root,
            depth=depth,
            seen=seen,
            deferred=deferred,
        )

    def enter(child: object) -> None:
        _check_schema_keywords(
            child,
            document,
            pointer_root=pointer_root,
            resource_root=resource_root,
            depth=depth + 1,
            seen=seen,
            deferred=deferred,
        )

    for key, value in node.items():
        if key in _SCHEMA_MAP_KEYWORDS and isinstance(value, Mapping):
            for child in value.values():
                enter(child)
            continue
        if (
            key in _SCHEMA_ARRAY_KEYWORDS
            and isinstance(value, Sequence)
            and not isinstance(value, (str, bytes))
        ):
            for child in value:
                enter(child)
            continue
        if key in _SCHEMA_OBJECT_KEYWORDS:
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                for child in value:
                    enter(child)
            else:
                enter(value)


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
        raise McpProfileError(
            "MCP $ref target is not a JSON Schema 2020-12 schema"
        ) from exc


def _json_pointer_token(raw: str) -> str:
    """Validate JSON Pointer escapes, then unescape.

    RFC 6901: ``~`` introduces ``~0`` or ``~1`` and nothing else. Validation
    happens before substitution, so a planted literal key cannot admit ``~2``.
    ``~1`` is replaced before ``~0``.
    """

    index = 0
    length = len(raw)
    while index < length:
        if raw[index] == "~":
            if index + 1 >= length or raw[index + 1] not in "01":
                raise McpProfileError("MCP $ref fragment is not a valid JSON Pointer")
            index += 2
            continue
        index += 1
    return raw.replace("~1", "/").replace("~0", "~")


_MISSING = object()
# ``additionalItems`` was removed in draft 2020-12. The keyword walk still
# checks a ``$ref`` parked there. Anchor indexing does not treat it as an applicator.
_ANCHOR_OBJECT_KEYWORDS = _SCHEMA_OBJECT_KEYWORDS - {"additionalItems"}


def _note_reached_schema(
    target: object,
    depth: int,
    seen: set[int],
    deferred: dict[int, tuple[Any, int, Mapping[str, Any], Mapping[str, Any]]],
    *,
    pointer_root: Mapping[str, Any],
    resource_root: Mapping[str, Any],
) -> None:
    """Queue a schema object the tree walk does not enter.

    Schemas already visited keep the shallower depth. The numeric limits are
    the same ``MAX_SCHEMA_DEPTH`` and ``MAX_SCHEMA_NODES`` as the tree walk.
    A nested ``$id`` on the target becomes the resource for the refs inside it.
    """

    if not isinstance(target, Mapping):
        return
    if _nonempty_id(target) and target is not resource_root:
        pointer_root = target
        resource_root = target
    identity = id(target)
    if identity in seen:
        return
    current = deferred.get(identity)
    if current is None or depth < current[1]:
        deferred[identity] = (target, depth, pointer_root, resource_root)


def _follow_pointer(root: object, decoded: str) -> object:
    """Walk a decoded JSON Pointer. Return ``_MISSING`` when a step is absent.

    Invalid ``~`` escapes raise before a later root is tried. ``decoded``
    starts with ``/``.
    """

    current: object = root
    for raw in decoded[1:].split("/"):
        token = _json_pointer_token(raw)
        if isinstance(current, Mapping) and token in current:
            current = current[token]
            continue
        if isinstance(current, list):
            index = _array_index(token)
            if index is not None and index < len(current):
                current = current[index]
                continue
        return _MISSING
    return current


def _contains(root: object, node: object, seen: set[int] | None = None) -> bool:
    """Return whether ``node`` is ``root`` or sits inside it. The walk is bounded."""

    if root is node:
        return True
    if seen is None:
        seen = set()
    if not isinstance(root, Mapping) or len(seen) > MAX_SCHEMA_NODES:
        return False
    identity = id(root)
    if identity in seen:
        return False
    seen.add(identity)
    for value in root.values():
        if _contains(value, node, seen):
            return True
        if isinstance(value, list):
            for item in value:
                if _contains(item, node, seen):
                    return True
    return False


def _roots_for_target(
    target: object,
    found_in: Mapping[str, Any],
    document: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Return the pointer root and the resource root that contain ``target``."""

    if isinstance(target, Mapping) and _nonempty_id(target) and target is not document:
        return target, target
    if found_in is document or _nonempty_id(found_in):
        return found_in, found_in
    return found_in, document


def _resolve_pointer(
    document: Mapping[str, Any],
    pointer: str,
    *,
    pointer_root: Mapping[str, Any],
    resource_root: Mapping[str, Any],
    depth: int,
    seen: set[int],
    deferred: dict[int, tuple[Any, int, Mapping[str, Any], Mapping[str, Any]]],
) -> None:
    if not isinstance(pointer, str) or not pointer.startswith("#"):
        raise McpProfileError("MCP $ref must be a same-document fragment")
    if pointer == "#":
        _require_schema(document)
        _note_reached_schema(
            document,
            depth + 1,
            seen,
            deferred,
            pointer_root=document,
            resource_root=document,
        )
        return
    decoded = _decode_uri_fragment(pointer[1:])
    if not decoded.startswith("/"):
        _resolve_anchor(
            document,
            decoded,
            pointer_root=pointer_root,
            resource_root=resource_root,
            depth=depth,
            seen=seen,
            deferred=deferred,
        )
        return
    local: object = _MISSING
    if pointer_root is not document:
        local = _follow_pointer(pointer_root, decoded)
    remote: object = _MISSING
    if pointer_root is document or not _nonempty_id(pointer_root):
        remote = _follow_pointer(document, decoded)
    if local is _MISSING and remote is _MISSING:
        raise McpProfileError("MCP $ref does not resolve in the descriptor")
    if local is not _MISSING and remote is not _MISSING and local is not remote:
        raise McpProfileError("MCP $ref target is ambiguous")
    if local is not _MISSING:
        target = local
        found_in = pointer_root
    else:
        target = remote
        found_in = document
    _require_schema(target)
    next_pointer, next_resource = _roots_for_target(target, found_in, document)
    _note_reached_schema(
        target,
        depth + 1,
        seen,
        deferred,
        pointer_root=next_pointer,
        resource_root=next_resource,
    )


def _resolve_anchor(
    document: Mapping[str, Any],
    name: str,
    *,
    pointer_root: Mapping[str, Any],
    resource_root: Mapping[str, Any],
    depth: int,
    seen: set[int],
    deferred: dict[int, tuple[Any, int, Mapping[str, Any], Mapping[str, Any]]],
) -> None:
    """Resolve a plain-name fragment to one ``$anchor`` or ``$dynamicAnchor``.

    The search follows schema keywords, so a name that exists only inside
    instance data (``const``, ``default``, ``enum``) does not resolve. A
    non-string keyword value is not a name. An embedded tool schema without
    its own ``$id`` is searched together with the document resource, because
    the document walk does not enter ``tools``. A nested ``$id`` is searched
    alone. ``additionalItems`` is not indexed. Two different schema objects
    with the same name are ambiguous: the profile does not pick one. The
    single target is still checked as a 2020-12 schema, then queued at the
    next depth so the visited set and the bounds stay those of the walk.
    """

    if not isinstance(name, str) or not name:
        raise McpProfileError("MCP $ref does not resolve in the descriptor")
    matches: list[Mapping[str, Any]] = []
    visited: set[int] = set()
    if pointer_root is not document and not _nonempty_id(pointer_root):
        _collect_anchors(
            pointer_root, name, matches, depth=1, visited=visited, at_root=True
        )
        _collect_anchors(
            document, name, matches, depth=1, visited=visited, at_root=True
        )
    else:
        root = document if resource_root is document else resource_root
        _collect_anchors(root, name, matches, depth=1, visited=visited, at_root=True)
    if not matches:
        raise McpProfileError("MCP $ref does not resolve in the descriptor")
    if len(matches) > 1:
        raise McpProfileError("MCP $ref anchor is ambiguous")
    target = matches[0]
    _require_schema(target)
    if pointer_root is not document and _contains(pointer_root, target):
        found_in = pointer_root
    elif resource_root is not document:
        found_in = resource_root
    else:
        found_in = document
    next_pointer, next_resource = _roots_for_target(target, found_in, document)
    _note_reached_schema(
        target,
        depth + 1,
        seen,
        deferred,
        pointer_root=next_pointer,
        resource_root=next_resource,
    )


def _collect_anchors(
    node: object,
    name: str,
    matches: list[Mapping[str, Any]],
    *,
    depth: int,
    visited: set[int],
    at_root: bool,
) -> None:
    """Append each schema object in this resource whose plain name equals ``name``."""

    if depth > MAX_SCHEMA_DEPTH or len(visited) > MAX_SCHEMA_NODES:
        raise McpProfileError("MCP schema exceeds the revision bounds")
    if not isinstance(node, Mapping):
        return
    if not at_root and _nonempty_id(node):
        return
    identity = id(node)
    if identity in visited:
        return
    visited.add(identity)
    matched = False
    for keyword in _ANCHOR_KEYWORDS:
        value = node.get(keyword)
        if isinstance(value, str) and value == name:
            matched = True
            break
    if matched:
        matches.append(node)
    for key, value in node.items():
        if key == "additionalItems":
            continue
        if key in _SCHEMA_MAP_KEYWORDS and isinstance(value, Mapping):
            for child in value.values():
                _collect_anchors(
                    child,
                    name,
                    matches,
                    depth=depth + 1,
                    visited=visited,
                    at_root=False,
                )
            continue
        if (
            key in _SCHEMA_ARRAY_KEYWORDS
            and isinstance(value, Sequence)
            and not isinstance(value, (str, bytes))
        ):
            for child in value:
                _collect_anchors(
                    child,
                    name,
                    matches,
                    depth=depth + 1,
                    visited=visited,
                    at_root=False,
                )
            continue
        if key in _ANCHOR_OBJECT_KEYWORDS:
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                for child in value:
                    _collect_anchors(
                        child,
                        name,
                        matches,
                        depth=depth + 1,
                        visited=visited,
                        at_root=False,
                    )
            else:
                _collect_anchors(
                    value,
                    name,
                    matches,
                    depth=depth + 1,
                    visited=visited,
                    at_root=False,
                )


def _reject_surrogate(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise McpProfileError("MCP descriptor contains a lone surrogate")


def _array_index(token: str) -> int | None:
    """Return a canonical JSON Pointer array index.

    One ASCII digit is an index. A longer index cannot have a leading zero.
    A non-ASCII digit is not an index. An index outside the node budget cannot
    address a document the walk accepts, and ``int`` is not called on it.
    """
    if not token.isascii() or not token.isdigit():
        return None
    if len(token) > 1 and token[0] == "0":
        return None
    if len(token) > len(str(MAX_SCHEMA_NODES)):
        return None
    index = int(token)
    if index >= MAX_SCHEMA_NODES:
        return None
    return index
