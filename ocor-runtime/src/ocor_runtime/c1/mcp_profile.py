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

import json
import math
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Any, cast
from urllib.parse import quote, unquote, urldefrag

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, UnknownType
from referencing import Registry, Resource
from referencing.exceptions import (
    CannotDetermineSpecification,
    PointerToNowhere,
    Unresolvable,
)
from referencing.jsonschema import DRAFT202012

# Library failures on a tampered fixture or schema are profile errors. The caller
# never sees TypeError, UnknownType or CannotDetermineSpecification.
_SCHEMA_LIBRARY_ERRORS = (
    SchemaError,
    UnknownType,
    CannotDetermineSpecification,
    AttributeError,
    TypeError,
    ValueError,
)

OFFICIAL_SCHEMA_URI = "https://modelcontextprotocol.io/schema/2026-07-28/schema.json"
CONTEXT_FIELD = "governed_context_ref"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
ACCEPTED_DIALECTS = frozenset({DRAFT_2020_12, DRAFT_2020_12 + "#"})
MAX_SCHEMA_DEPTH = 32
MAX_SCHEMA_NODES = 4096
def _library_keyword_groups() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """Keyword groups of ``DRAFT202012.subresources_of``.

    The groups are read from the pinned specification so the profile cannot
    grow a second table. ``additionalItems`` is not a JSON Schema 2020-12
    keyword and is not a member. Identification is by a member of each group,
    not by closure order.
    """

    function = DRAFT202012.subresources_of
    groups = [
        frozenset(cell.cell_contents)
        for cell in function.__closure__ or ()
        if isinstance(cell.cell_contents, (set, frozenset))
    ]
    try:
        maps = next(group for group in groups if "properties" in group)
        objects = next(group for group in groups if "items" in group)
        arrays = next(group for group in groups if "allOf" in group)
    except StopIteration as exc:
        raise RuntimeError("pinned draft subresource keywords are not recognisable") from exc
    if "additionalItems" in maps | objects | arrays:
        raise RuntimeError("pinned draft unexpectedly indexes additionalItems")
    return maps, objects, arrays


# Applicator keywords whose values are schemas. Map keys are names, not keywords.
# The sets are the pinned draft's, not a hand-written copy.
_SCHEMA_MAP_KEYWORDS, _SCHEMA_OBJECT_KEYWORDS, _SCHEMA_ARRAY_KEYWORDS = _library_keyword_groups()
# Plain-name anchors indexed by the pinned referencing resolver for draft 2020-12.
_ANCHOR_KEYWORDS = ("$anchor", "$dynamicAnchor")


class McpProfileError(ValueError):
    """The MCP profile rejected a descriptor or an input schema."""

    def __init__(self, message: str) -> None:
        if not isinstance(message, str) or not message or len(message) > 512:
            raise ValueError("MCP profile message must be bounded and non-empty")
        super().__init__(message)


class SchemaCalculationFailure(Exception):
    """Internal failure of the one schema calculation shared by both callers.

    ``validate_mcp_descriptor`` maps it to ``McpProfileError``. ``_mcp`` maps
    it to ``C1Error`` and the ``DiagnosticCode`` that path already uses. The
    message is the public text when both paths share it; ``CRAWL`` is mapped
    by the caller because the two paths use different public sentences.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class UnsupportedJsonMapping(SchemaCalculationFailure):
    """A Python mapping outside the native and frozen JSON object representations."""

    def __init__(self) -> None:
        super().__init__("NOT_JSON", "MCP descriptor contains a value that is not JSON")


def _as_profile(exc: SchemaCalculationFailure) -> McpProfileError:
    if exc.code in {"CRAWL", "NOT_RESOLVABLE"}:
        message = "MCP schema resource index is not resolvable"
    elif exc.code == "INVALID_ID":
        message = "MCP $id is not a valid URI reference"
    else:
        message = exc.message
    return McpProfileError(message)


def json_bounds(document: object) -> None:
    """Reject a document outside the revision's one JSON bound.

    The root counts as one JSON value. Object keys do not count. Depth starts
    at 1. Non-JSON values, lone surrogates and non-finite numbers fail on this
    same walk. Callers map ``SchemaCalculationFailure`` to their public error.
    """

    nodes = [0]

    def visit(node: object, depth: int) -> None:
        nodes[0] += 1
        if nodes[0] > MAX_SCHEMA_NODES or depth > MAX_SCHEMA_DEPTH:
            raise SchemaCalculationFailure("BOUNDS", "MCP schema exceeds the revision bounds")
        if isinstance(node, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in node):
                raise SchemaCalculationFailure(
                    "SURROGATE", "MCP descriptor contains a lone surrogate"
                )
            return
        if isinstance(node, bool) or node is None or isinstance(node, int):
            return
        if isinstance(node, float):
            if not math.isfinite(node):
                raise SchemaCalculationFailure(
                    "NON_FINITE", "MCP descriptor contains a non-finite number"
                )
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                visit(item, depth + 1)
            return
        if not isinstance(node, (dict, MappingProxyType)):
            if isinstance(node, Mapping):
                raise UnsupportedJsonMapping()
            raise SchemaCalculationFailure(
                "NOT_JSON", "MCP descriptor contains a value that is not JSON"
            )
        for key in node:
            if isinstance(key, str):
                if any(0xD800 <= ord(character) <= 0xDFFF for character in key):
                    raise SchemaCalculationFailure(
                        "SURROGATE", "MCP descriptor contains a lone surrogate"
                    )
            else:
                raise SchemaCalculationFailure(
                    "NOT_JSON", "MCP descriptor contains a value that is not JSON"
                )
        for value in node.values():
            visit(value, depth + 1)

    visit(document, 1)


def _fixed_tool_uri(index: int, field: str) -> str:
    return f"urn:ocor:embedded-tool:{index}:{field}"


def _id_identity(value: str) -> str:
    """Identity of a string ``$id``: a trailing empty fragment does not differ."""

    return value.rstrip("#")


def _collect_string_ids(node: object, found: set[str], seen: set[int] | None = None) -> None:
    if seen is None:
        seen = set()
    if isinstance(node, str) or node is None or isinstance(node, (int, float, bool, bytes)):
        return
    identity = id(node)
    if identity in seen:
        return
    seen.add(identity)
    if isinstance(node, Mapping):
        declared = node.get("$id")
        if isinstance(declared, str):
            found.add(declared)
        for value in node.values():
            _collect_string_ids(value, found, seen)
        return
    if isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
        for item in node:
            _collect_string_ids(item, found, seen)


def operational_base(schema: object, *, index: int, field: str) -> str:
    """Base URI of one autonomous tool schema. No suffix.

    Absent, non-string, ``""`` and an identifier whose pre-fragment part is
    empty (``"#"``, ``"###"``) use ``urn:ocor:embedded-tool:{index}:{field}``.
    Every other root ``$id`` uses that pre-fragment part. The schema bytes are
    not rewritten. Collision is checked only for the fixed base, against every
    string ``$id`` in that same schema.
    """

    fixed = _fixed_tool_uri(index, field)
    declared = schema.get("$id") if isinstance(schema, Mapping) else None
    if isinstance(declared, str):
        try:
            base, _ = urldefrag(declared)
        except ValueError as exc:
            raise SchemaCalculationFailure("INVALID_ID", "MCP $id is not a valid URI reference") from exc
        if base:
            return base
    found: set[str] = set()
    _collect_string_ids(schema, found)
    for item in found:
        if item == fixed or _id_identity(item) == fixed:
            raise SchemaCalculationFailure(
                "COLLISION",
                "MCP schema base collides with a declared $id",
            )
    return fixed


def autonomous_registry(
    schema: Mapping[str, Any],
    base_uri: str,
    *,
    registry_factory: Callable[[], Any] = Registry,
    translate_null_applicator: bool = False,
) -> Registry[Any]:
    """Uncached registry pinned only at ``base_uri`` with the original schema.

    ``crawl`` is an error probe. Its result is discarded and the root is never
    re-pinned. The returned registry is the one lookups use. ``registry_factory``
    is the caller's ``Registry`` so a test that replaces ``codegen.Registry``
    still observes ``crawl``.
    """

    _reject_non_string_schema_ids(schema)
    resource = DRAFT202012.create_resource(schema)
    registry = registry_factory().with_resource(base_uri, resource)
    probe = registry_factory().with_resource(base_uri, resource)
    try:
        probe.crawl()
    except Unresolvable as exc:
        raise SchemaCalculationFailure("CRAWL", "crawl") from exc
    except AttributeError as exc:
        text = str(exc)
        if translate_null_applicator and "NoneType" in text and "get" in text:
            raise SchemaCalculationFailure("CRAWL", "crawl") from exc
        if "rstrip" in text or ("NoneType" in text and "values" in text):
            raise SchemaCalculationFailure(
                "NOT_RESOLVABLE",
                "MCP schema resource index is not resolvable",
            ) from exc
        # Other AttributeError values are left to the caller's later schema
        # check. Mapping every one to NOT_RESOLVABLE would replace the
        # existing non-schema diagnostic on a tool schema whose ``$defs``
        # holds a scalar. The generator calls
        # ``assert_walkable_schema_resource`` for that class.
    except TypeError as exc:
        raise SchemaCalculationFailure(
            "NOT_RESOLVABLE",
            "MCP schema resource index is not resolvable",
        ) from exc
    except ValueError as exc:
        raise SchemaCalculationFailure(
            "INVALID_ID",
            "MCP $id is not a valid URI reference",
        ) from exc
    return cast(Registry[Any], registry)


def assert_walkable_schema_resource(
    schema: Mapping[str, Any],
    base_uri: str,
    *,
    registry_factory: Callable[[], Any] = Registry,
) -> None:
    """Refuse a schema the pinned library cannot crawl.

    ``autonomous_registry`` keeps its two crawl mappings: a null applicator
    stays ``CRAWL`` when the caller asks for that translation, and a null
    ``properties`` stays ``NOT_RESOLVABLE``. The ``AttributeError`` values
    left to a later check are a non-schema in a schema position or a
    container of the wrong kind. The generator no longer walks those with
    ``subresources``, so this function is that later check. A boolean schema
    crawls and is not refused here.
    """

    resource = DRAFT202012.create_resource(schema)
    probe = registry_factory().with_resource(base_uri, resource)
    try:
        probe.crawl()
    except AttributeError as exc:
        text = str(exc)
        if "NoneType" in text and "get" in text:
            return
        if "rstrip" in text or ("NoneType" in text and "values" in text):
            return
        raise SchemaCalculationFailure(
            "NOT_RESOLVABLE",
            "MCP schema resource index is not resolvable",
        ) from exc
    except (Unresolvable, TypeError, ValueError):
        return


def _resolver_for_subresource(resolver: Any, resource: Resource[Any]) -> tuple[Any, bool]:
    """Enter one library resource. True when ``in_subresource`` changes the base.

    The resolver is the one ``referencing`` returns for the schema as it is.
    A changed base is not registered again, and a ``PointerToNowhere`` is not
    retried by dropping a URI. A descendant whose ``$id`` rejoins the base
    stays visible to the library crawl. The caller's registry is untouched.
    """

    entered = resolver.in_subresource(resource)
    parent_base = getattr(resolver, "_base_uri", None)
    entered_base = getattr(entered, "_base_uri", None)
    changed = isinstance(entered_base, str) and entered_base != parent_base
    return entered, changed


def enter_subschema(resolver: Any, child: object) -> tuple[Any, bool]:
    """Enter ``child`` with the library resolver. True when the base URI changes.

    A non-mapping is not a schema resource. Library ``ValueError`` and
    ``AttributeError`` propagate so each caller keeps its typed message.
    """

    if not isinstance(child, Mapping):
        return resolver, False
    return _resolver_for_subresource(resolver, DRAFT202012.create_resource(child))


def assert_reference_path_bound(schema: object, resolver: Any) -> None:
    """Refuse a reference path deeper than the revision bound.

    The depth is the profile graph's depth. Static nodes are visited first.
    Each same-document ``$ref`` seeds its target at that static depth plus
    one. A node already entered by a reference is not entered again, so a
    chain of named definitions does not add a generator-only limit. Depth
    is tested before that visit set. Lookup failures stay the caller's
    unresolved-reference diagnostic. JSON value count and JSON depth stay
    in ``json_bounds``. ``_resolve_graph`` calls this function.
    """

    # Two visit sets, as in ``_resolve_graph``: a node already seen on the
    # static walk can still be entered once by a reference. Depth is tested
    # before the visit set, so a seed past the revision bound is refused
    # even when its target was already seen. A later hop to a node already
    # entered by a reference does not add another generator-only limit.
    visited_static: set[tuple[int, str]] = set()
    visited_ref: set[tuple[int, str]] = set()

    def state_of(node: object, res: Any) -> tuple[int, str]:
        base = getattr(res, "_base_uri", "")
        return (id(node), base if isinstance(base, str) else "")

    def enter(res: Any, child: Mapping[str, Any]) -> Any:
        try:
            entered, _changed = enter_subschema(res, child)
        except (ValueError, AttributeError, TypeError):
            return None
        return entered

    def lookup_target(res: Any, ref: object) -> tuple[object, Any] | None:
        if not isinstance(ref, str) or not ref.startswith("#"):
            return None
        try:
            resolved = res.lookup(ref)
        except (Unresolvable, *_SCHEMA_LIBRARY_ERRORS):
            return None
        contents = getattr(resolved, "contents", None)
        if not isinstance(contents, Mapping):
            return None
        return contents, resolved.resolver

    static: list[tuple[object, Any, int]] = [(schema, resolver, 1)]
    seeds: list[tuple[Mapping[str, Any], Any, int]] = []
    while static:
        node, res, depth = static.pop(0)
        if not isinstance(node, Mapping):
            continue
        if depth > MAX_SCHEMA_DEPTH:
            raise SchemaCalculationFailure("BOUNDS", "MCP schema exceeds the revision bounds")
        state = state_of(node, res)
        if state in visited_static:
            continue
        visited_static.add(state)
        if isinstance(node.get("$ref"), str):
            seeds.append((node, res, depth))
        for child in _iter_check_children(node):
            if not isinstance(child, Mapping):
                continue
            entered = enter(res, child)
            if entered is None:
                continue
            static.append((child, entered, depth + 1))

    pending: list[tuple[object, Any, int]] = []
    for node, res, depth in seeds:
        found = lookup_target(res, node.get("$ref"))
        if found is not None:
            pending.append((found[0], found[1], depth + 1))
    while pending:
        node, res, depth = pending.pop(0)
        if not isinstance(node, Mapping):
            continue
        if depth > MAX_SCHEMA_DEPTH:
            raise SchemaCalculationFailure("BOUNDS", "MCP schema exceeds the revision bounds")
        state = state_of(node, res)
        if state in visited_ref:
            continue
        visited_ref.add(state)
        found = lookup_target(res, node.get("$ref"))
        if found is not None:
            pending.append((found[0], found[1], depth + 1))
        for child in _iter_check_children(node):
            if not isinstance(child, Mapping):
                continue
            entered = enter(res, child)
            if entered is None:
                continue
            pending.append((child, entered, depth + 1))


@dataclass(frozen=True)
class _SchemaTree:
    """One autonomous schema tree: one tool schema field.

    ``root`` is the original document object the profile checks. The registry
    pins only this tree's root and is not crawled: a separate crawl is an
    error probe and its result is discarded. No lookup can reach a resource
    of another tree. Static keyword descent keeps the resolver
    ``in_subresource`` returned. ``anchors`` is the only index this tree
    stores; it records every plain-name owner inside one resource.
    """

    root_uri: str
    root: Mapping[str, Any]
    registry: Registry[Any]
    anchors: Mapping[tuple[int, str], tuple[Mapping[str, Any], ...]]


@dataclass(frozen=True)
class _ResolutionContext:
    """The resolver state at one schema node, on its tree.

    ``resolver`` is the library resolver that reached this node: keyword
    descent keeps the resolver ``in_subresource`` returned, and a reference
    keeps the resolver ``lookup`` returned. ``resource_id`` is the identity
    of that resource's root object. Anchor ambiguity is per resource root,
    not a merge of two nodes that happen to claim one URI.
    """

    tree: _SchemaTree
    resolver: Any
    base_uri: str
    resource_uri: str
    resource_id: int

    @property
    def registry(self) -> Registry[Any]:
        registry = getattr(self.resolver, "_registry", None)
        if registry is None:
            return self.tree.registry
        return cast(Registry[Any], registry)

    @property
    def anchors(self) -> Mapping[tuple[int, str], tuple[Mapping[str, Any], ...]]:
        return self.tree.anchors


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


def require_tool_name(value: object) -> str:
    """The name admitted by both generation and delivery."""
    if not isinstance(value, str) or not value:
        raise McpProfileError("MCP tool name must be a non-empty string")
    return value


def validate_mcp_descriptor(
    document: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    expected_revision: str,
) -> None:
    """Fail closed when ``document`` is not a descriptor of ``expected_revision``.

    ``schema`` is the official schema document of that revision. Each tool is checked
    against its ``Tool`` definition. ``inputSchema`` and ``outputSchema`` are JSON
    Schema 2020-12 schemas (``Draft202012Validator.check_schema``) and each is an
    autonomous resource: its ``$ref`` targets resolve only inside that schema,
    never on the descriptor or another tool (MCP-TOOL-SCHEMA-AUTONOMO and
    MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE, 2026-11-15). The schema, dialect,
    keyword and ``$ref`` checks apply only to ``inputSchema`` and
    ``outputSchema``, each on its own; the descriptor is not a schema tree,
    and a descriptor with top-level ``$defs`` is refused. Every ``$ref`` is a
    same-document fragment, resolved entirely by referencing 0.37.0 with
    draft 2020-12 on the current resource and base URI; a fragment that does
    not resolve there is refused: there is no fallback onto the descriptor,
    another tool or an external document. The fragment is percent-decoded as
    UTF-8, then classified. A decoded empty fragment is the empty JSON
    Pointer: it identifies the current resource. A decoded fragment that
    starts with ``/`` is a JSON Pointer. A fragment whose decoded spelling
    differs from the original and is not a pointer is refused: the pinned
    library does not percent-decode anchor names. Any other fragment is a
    plain-name anchor (``$anchor`` or ``$dynamicAnchor``). ``~`` escapes are
    validated before substitution. A trailing empty fragment on ``$id`` is
    stripped before joining, matching referencing 0.37.0 ``Resource.id``; an
    ``$id`` of ``#``, an empty ``$id``, or any ``$id`` that joins to the same
    URI does not start another resource. Two different objects declaring one
    plain name inside one resource are rejected. The value a reference lands
    on must itself be a 2020-12 schema. Each schema node reached by a
    reference is checked with the context of every path that reaches it, and
    every ``$ref`` is resolved in every context that reaches its node, so the
    outcome never depends on member order. Dialect, local-reference and
    resolution rules also apply to a schema reached through instance data
    such as ``const`` or ``default``, whose ``$id`` changes the base URI of
    the references inside it exactly as the pinned library descends. A
    fixture that is not an object, or whose ``$defs`` or ``Tool`` entry is
    not an object, is rejected before the library is called.
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
        names.append(require_tool_name(tool.get("name") if isinstance(tool, Mapping) else None))
    if names != sorted(names) or len(names) != len(set(names)):
        raise McpProfileError("MCP tools are not in deterministic name order")
    if "$defs" in document:
        raise McpProfileError("MCP descriptor must not declare top-level $defs")
    try:
        json_bounds(document)
    except SchemaCalculationFailure as exc:
        raise _as_profile(exc) from exc
    # Every schema-position node is resolved before any keyword check, and
    # every ``$ref`` is resolved in every context that reaches its node, so
    # the outcome never depends on the order of members or visits. A
    # reference path that does not resolve rejects the descriptor here. Each
    # tool schema is checked on its own tree: no state is shared between
    # trees, and the descriptor has no resolution tree.
    for _index, _field, tree in _build_schema_trees(document):
        order, ref_states = _resolve_graph([(tree.root, _root_context(tree))])
        _check_reached_schemas(order, ref_states)
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


@lru_cache(maxsize=1)
def _official_tool_validator(fixture_json: str) -> tuple[dict[str, Any], Any]:
    """Validate a private snapshot. Reusing it depends on every byte of the fixture."""
    fixture = json.loads(fixture_json)
    if fixture.get("$schema") not in ACCEPTED_DIALECTS:
        raise McpProfileError("official MCP schema fixture is not a JSON Schema")
    Draft202012Validator.check_schema(fixture)
    registry = Registry().with_resource(OFFICIAL_SCHEMA_URI, DRAFT202012.create_resource(fixture))
    tool = registry.resolver(OFFICIAL_SCHEMA_URI).lookup("#/$defs/Tool")
    pending = [(tool.contents, tool.resolver)]
    visited: set[tuple[int, str]] = set()
    while pending:
        node, resolver = pending.pop()
        if isinstance(node, bool):
            continue
        if not isinstance(node, dict):
            raise McpProfileError("official MCP schema fixture is not a JSON Schema")
        key = (id(node), resolver._base_uri)
        if key in visited:
            continue
        visited.add(key)
        for keyword in ("$ref", "$dynamicRef"):
            if keyword in node:
                target = resolver.lookup(node[keyword])
                pending.append((target.contents, target.resolver))
        for resource in DRAFT202012.create_resource(node).subresources():
            pending.append((resource.contents, resolver.in_subresource(resource)))
    return fixture, Draft202012Validator({"$ref": OFFICIAL_SCHEMA_URI + "#/$defs/Tool"}, registry=registry)


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
        snapshot, validator = _official_tool_validator(json.dumps(dict(schema), allow_nan=False))
        # JSON encoding coerces tuples and non-string object keys. A fixture
        # must itself have the schema shape that was checked and cached.
        if schema != snapshot:
            raise McpProfileError("official MCP schema fixture is not a JSON Schema")
    except (*_SCHEMA_LIBRARY_ERRORS, Unresolvable, re.error, RecursionError) as exc:
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
        except (*_SCHEMA_LIBRARY_ERRORS, Unresolvable, re.error, RecursionError) as exc:
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
        require_tool_field(tool.get("inputSchema"), index, "inputSchema")
        if "outputSchema" in tool:
            require_tool_field(tool["outputSchema"], index, "outputSchema")


def require_tool_field(schema: object, index: int, field: str) -> None:
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


def contained_subschemas(node: Mapping[str, Any]) -> tuple[object, ...]:
    """Subschemas the pinned draft indexes under ``node``.

    This is the only enumeration of contained subschemas. The profile and the
    generator both call it. ``additionalItems`` is not a member: JSON Schema
    2020-12 does not index it, and a ``$id``, ``$anchor`` or ``$ref`` stored
    there is not a resource boundary. A keyword value that is not the
    container the draft walks contributes nothing, so a string does not
    become a sequence of characters.
    """

    if not isinstance(node, Mapping):
        return ()
    found: list[object] = []
    for key, value in node.items():
        if key in _SCHEMA_MAP_KEYWORDS and isinstance(value, Mapping):
            found.extend(value.values())
            continue
        if key in _SCHEMA_ARRAY_KEYWORDS and isinstance(value, Sequence) and not isinstance(
            value, (str, bytes)
        ):
            found.extend(value)
            continue
        if key in _SCHEMA_OBJECT_KEYWORDS:
            found.append(value)
    return tuple(found)


def _iter_schema_children(node: Mapping[str, Any]) -> Iterator[object]:
    """Yield the shared enumeration. ``additionalItems`` is not included."""

    yield from contained_subschemas(node)


def _iter_check_children(node: Mapping[str, Any]) -> Iterator[object]:
    """Keyword checks use the same enumeration as resource indexing."""

    yield from contained_subschemas(node)


def enforce_emitted_schema_rules(schema: object) -> None:
    """Rule 3 on every schema the shared enumeration reaches.

    Dialect 2020-12, and no ``$dynamicRef`` or ``$recursiveRef``, on the root,
    on a nested schema and on the root of a nested resource. ``additionalItems``
    is not walked. Callers map ``SchemaCalculationFailure`` to their public
    error. The message is the profile sentence.
    """

    seen: set[int] = set()

    def visit(node: object) -> None:
        if not isinstance(node, Mapping):
            return
        identity = id(node)
        if identity in seen:
            return
        seen.add(identity)
        if "$dynamicRef" in node or "$recursiveRef" in node:
            raise SchemaCalculationFailure(
                "KEYWORD",
                "MCP $ref resolution does not follow dynamic references",
            )
        if "$schema" in node:
            dialect = node["$schema"]
            if not isinstance(dialect, str) or dialect not in ACCEPTED_DIALECTS:
                raise SchemaCalculationFailure(
                    "KEYWORD",
                    "MCP schema dialect must be JSON Schema 2020-12",
                )
        if isinstance(node, Mapping):
            for child in contained_subschemas(node):
                visit(child)

    visit(schema)


def _reject_non_string_schema_ids(node: object, *, seen: set[int] | None = None) -> None:
    """A non-string ``$id`` at a schema position is not an absent identifier.

    Instance data (``const``, ``default``, ``examples``, ``enum``) is not a
    schema position. The library crawl rejects a non-string ``$id``; this
    check reports that typed failure without using the crawled registry.
    """

    if not isinstance(node, Mapping):
        return
    if seen is None:
        seen = set()
    identity = id(node)
    if identity in seen:
        return
    seen.add(identity)
    if "$id" in node and not isinstance(node.get("$id"), str):
        raise SchemaCalculationFailure(
            "NOT_RESOLVABLE",
            "MCP schema resource index is not resolvable",
        )
    for child in _iter_schema_children(node):
        _reject_non_string_schema_ids(child, seen=seen)


def _build_schema_trees(
    document: Mapping[str, Any],
) -> tuple[tuple[int, str, _SchemaTree], ...]:
    """Index one autonomous tree per tool schema field.

    Each ``inputSchema`` and ``outputSchema`` is its own registry. The base
    comes from ``operational_base``. No tree shares anchors or resources with
    another, and the descriptor is not a schema tree.
    """

    tool_trees: list[tuple[int, str, _SchemaTree]] = []
    tools = document.get("tools")
    if isinstance(tools, Sequence) and not isinstance(tools, (str, bytes)):
        for index, tool in enumerate(tools):
            if not isinstance(tool, Mapping):
                continue
            for field in ("inputSchema", "outputSchema"):
                schema = tool.get(field)
                if not isinstance(schema, Mapping):
                    continue
                try:
                    root_uri = operational_base(schema, index=index, field=field)
                except SchemaCalculationFailure as exc:
                    raise _as_profile(exc) from exc
                tool_trees.append((index, field, _schema_tree(schema, root_uri)))
    return tuple(tool_trees)


def _schema_tree(root: Mapping[str, Any], root_uri: str) -> _SchemaTree:
    """Pin one uncrawled draft-2020-12 registry and index anchors by resource."""

    try:
        registry = autonomous_registry(root, root_uri)
    except SchemaCalculationFailure as exc:
        raise _as_profile(exc) from exc
    anchors = _collect_anchor_owners(root, registry.resolver(root_uri))
    return _SchemaTree(
        root_uri=root_uri,
        root=root,
        registry=registry,
        anchors=anchors,
    )


def _collect_anchor_owners(
    root: Mapping[str, Any],
    resolver: Any,
) -> dict[tuple[int, str], tuple[Mapping[str, Any], ...]]:
    """Index every plain-name owner of one resource.

    ``referencing`` keeps one anchor when a name repeats. The profile records
    every owner of the same resource root and rejects the reference. A node
    whose ``$id`` changes the base is a different resource. ``additionalItems``
    is not indexed. Instance data is not an anchor position.
    """

    owners: dict[tuple[int, str], list[Mapping[str, Any]]] = {}

    def visit(node: object, res: Any, root_id: int, *, depth: int, seen: set[int]) -> None:
        if depth > MAX_SCHEMA_DEPTH:
            raise McpProfileError("MCP schema exceeds the revision bounds")
        if not isinstance(node, Mapping):
            return
        identity = id(node)
        if identity in seen:
            return
        seen.add(identity)
        names = {
            value
            for keyword in _ANCHOR_KEYWORDS
            for value in (node.get(keyword),)
            if isinstance(value, str)
        }
        for value in names:
            bucket = owners.setdefault((root_id, value), [])
            if not any(existing is node for existing in bucket):
                bucket.append(node)
        for child in _iter_schema_children(node):
            if not isinstance(child, Mapping):
                continue
            try:
                entered, changed = enter_subschema(res, child)
            except ValueError as exc:
                raise McpProfileError("MCP $id is not a valid URI reference") from exc
            except (AttributeError, TypeError) as exc:
                raise McpProfileError("MCP schema resource index is not resolvable") from exc
            if changed:
                visit(child, entered, id(child), depth=depth + 1, seen=seen)
            else:
                visit(child, entered, root_id, depth=depth + 1, seen=seen)

    visit(root, resolver, id(root), depth=1, seen=set())
    return {key: tuple(value) for key, value in owners.items()}


def _root_context(tree: _SchemaTree) -> _ResolutionContext:
    """The resolver state at the root resource of one tree."""

    return _ResolutionContext(
        tree=tree,
        resolver=tree.registry.resolver(tree.root_uri),
        base_uri=tree.root_uri,
        resource_uri=tree.root_uri,
        resource_id=id(tree.root),
    )


def _descend(context: _ResolutionContext, child: object) -> _ResolutionContext:
    """Enter a keyword child with the resolver ``in_subresource`` returns.

    The base URI is the library's. A child that does not change it stays on
    the current resource, and the returned resolver is kept so an anchor
    chain is not rebuilt from the root registry. A child that changes the
    base is that new resource's root.
    """

    if not isinstance(child, Mapping):
        return context
    try:
        entered, changed = enter_subschema(context.resolver, child)
    except ValueError as exc:
        raise McpProfileError("MCP $id is not a valid URI reference") from exc
    except (AttributeError, TypeError) as exc:
        raise McpProfileError("MCP schema resource index is not resolvable") from exc
    if not changed:
        return _ResolutionContext(
            tree=context.tree,
            resolver=entered,
            base_uri=context.base_uri,
            resource_uri=context.resource_uri,
            resource_id=context.resource_id,
        )
    base_uri = getattr(entered, "_base_uri", context.base_uri)
    if not isinstance(base_uri, str):
        base_uri = context.base_uri
    return _ResolutionContext(
        tree=context.tree,
        resolver=entered,
        base_uri=base_uri,
        resource_uri=base_uri,
        resource_id=id(child),
    )


def _ref_target_context(
    context: _ResolutionContext,
    resolver: Any,
    target: object,
) -> _ResolutionContext:
    """Keep the resolver a ``lookup`` returned for the target it reached."""

    base_uri = getattr(resolver, "_base_uri", context.base_uri)
    if not isinstance(base_uri, str):
        base_uri = context.base_uri
    if base_uri == context.base_uri:
        return _ResolutionContext(
            tree=context.tree,
            resolver=resolver,
            base_uri=base_uri,
            resource_uri=context.resource_uri,
            resource_id=context.resource_id,
        )
    try:
        root = resolver.lookup("#").contents
    except (Unresolvable, *_SCHEMA_LIBRARY_ERRORS):
        root = target
    resource_id = id(root) if isinstance(root, Mapping) else id(target)
    return _ResolutionContext(
        tree=context.tree,
        resolver=resolver,
        base_uri=base_uri,
        resource_uri=base_uri,
        resource_id=resource_id,
    )


def _resolve_graph(
    roots: Sequence[tuple[Any, _ResolutionContext]],
) -> tuple[list[tuple[Any, _ResolutionContext]], set[tuple[int, str]]]:
    """Resolve every ``$ref`` path before any keyword is checked.

    ``referencing`` owns every lookup. The static descent records, for each
    schema node, the state the crawl assigns it; a reference path records
    the resolver its lookup returned. A reference that does not resolve
    rejects the descriptor, so the outcome cannot depend on the order of
    members or the order of visits.

    The profile rule that static keyword descent applies only to nodes no
    reference reaches is realized as a fixed point. A static ``$ref`` is
    resolved for every statically reached node, but its failure only
    rejects the descriptor when no reference path reaches that node; the
    set of reference-reached nodes is recomputed until it stops growing,
    because a reference path can reach a node whose own static ``$ref``
    seeds further reference paths. Reference-path resolutions are never
    suppressed and raise at once. Trees never share state: every path
    starts from its tree's root context, the descriptor has no resolution
    tree, and each tool schema is checked on its own, so a node of one tree
    is reached only with contexts of that tree.
    """

    for node, context in roots:
        try:
            assert_reference_path_bound(node, context.resolver)
        except SchemaCalculationFailure as exc:
            raise _as_profile(exc) from exc

    static_order: list[tuple[Any, _ResolutionContext]] = []
    static_refs: list[tuple[Any, _ResolutionContext]] = []
    visited_static: set[tuple[int, str, int]] = set()
    queue: list[tuple[Any, _ResolutionContext]] = list(roots)
    while queue:
        node, context = queue.pop(0)
        if not isinstance(node, Mapping):
            continue
        # Depth belongs to ``assert_reference_path_bound``. This walk does not
        # carry a depth. The visit key keeps the registry identity.
        state = (id(node), context.base_uri, id(context.registry))
        if state in visited_static:
            continue
        visited_static.add(state)
        static_order.append((node, context))
        if "$ref" in node:
            static_refs.append((node, context))
        for child in _iter_check_children(node):
            queue.append((child, _descend(context, child)))

    ref_states: set[tuple[int, str]] = set()
    ref_reached: set[int] = set()
    static_outcomes: dict[tuple[int, str], tuple[object, _ResolutionContext]] = {}

    static_sequence: list[int] = []
    static_failures: dict[tuple[int, str], McpProfileError] = {}
    ref_queue: list[tuple[Any, _ResolutionContext]] = []
    visited_ref: set[tuple[int, str, int]] = set()
    ref_order: list[tuple[Any, _ResolutionContext]] = []

    def seed_static() -> None:
        for node, context in static_refs:
            identity = id(node)
            key = (identity, context.base_uri)
            static_sequence.append(identity)
            try:
                target, target_context = _resolve_reference(
                    node["$ref"], context
                )
            except McpProfileError as exc:
                static_failures[key] = exc
                continue
            static_outcomes[key] = (target, target_context)
        for node, _context in static_refs:
            key = (id(node), _context.base_uri)
            if id(node) in ref_reached:
                continue
            outcome = static_outcomes.get(key)
            if outcome is None:
                continue
            target, target_context = outcome
            if isinstance(target, Mapping):
                ref_queue.append((target, target_context))

    def drain_refs() -> None:
        while ref_queue:
            node, context = ref_queue.pop(0)
            if not isinstance(node, Mapping):
                continue
            state = (id(node), context.base_uri, id(context.registry))
            if state in visited_ref:
                continue
            visited_ref.add(state)
            ref_reached.add(id(node))
            ref_states.add((id(node), context.base_uri))
            ref_order.append((node, context))
            if "$ref" in node:
                target, target_context = _resolve_reference(
                    node["$ref"], context
                )
                if isinstance(target, Mapping):
                    ref_queue.append((target, target_context))
            for child in _iter_check_children(node):
                ref_queue.append((child, _descend(context, child)))

    seed_static()
    drain_refs()
    previous: set[int] | None = None
    iterations = 0
    while previous != ref_reached:
        previous = set(ref_reached)
        seed_static()
        drain_refs()
        iterations += 1
        if iterations > MAX_SCHEMA_NODES:
            raise McpProfileError("MCP schema exceeds the revision bounds")

    for identity in static_sequence:
        if identity in ref_reached:
            continue
        for key, error in static_failures.items():
            if key[0] == identity:
                raise error
    return static_order + ref_order, ref_states


def _check_reached_schemas(
    order: Sequence[tuple[Any, _ResolutionContext]],
    ref_states: set[tuple[int, str]],
) -> None:
    """Check each reached state: static contexts only where no ref lands."""

    ref_reached = {identity for identity, _base in ref_states}
    for node, context in order:
        identity = id(node)
        if identity in ref_reached and (identity, context.base_uri) not in ref_states:
            continue
        _check_schema_keywords(node, context)


def _resolve_reference(
    reference: object,
    context: _ResolutionContext,
) -> tuple[object, _ResolutionContext]:
    """Resolve one same-document fragment with the pinned ``referencing``.

    The lookup runs only on the resolver of the current tree. A fragment
    that does not resolve there is refused: there is no fallback onto the
    descriptor or another tool schema.
    """

    if not isinstance(reference, str) or not reference.startswith("#"):
        raise McpProfileError("MCP $ref must be a same-document fragment")
    fragment = reference[1:]
    # A JSON Pointer the pinned libraries resolve is accepted. The three
    # pre-lookup refusals of ``~`` other than ``~0``/``~1``, of loose
    # percent-encoding and of strict UTF-8 have no source in the contract
    # (REM-0063-CYCLE10-NO-GO option 1, VF-002). Non-canonical array indexes
    # stay a profile refusal. Fragments that do not start with ``/`` keep
    # the encoded-anchor rule.
    if fragment.startswith("/"):
        resolved = _lookup_reference(context.resolver, reference)
        if resolved is not None:
            _reject_noncanonical_array_index(context.resolver, fragment)
            target = resolved.contents
            _require_schema(target)
            return target, _ref_target_context(context, resolved.resolver, target)
    decoded = _decode_uri_fragment(fragment)
    if decoded and not decoded.startswith("/"):
        # The library does not percent-decode anchor names. An encoded anchor
        # is refused, including one whose literal spelling is itself an anchor.
        if reference[1:] != decoded:
            raise McpProfileError("MCP $ref does not resolve in the descriptor")
        _reject_ambiguous_anchor(context.resource_id, decoded, context.anchors)
    elif decoded.startswith("/"):
        raw_tokens = decoded[1:].split("/")
        tokens = [_json_pointer_token(raw_token) for raw_token in raw_tokens]
        _validate_pointer_array_indices(context.resolver, raw_tokens, tokens)
    resolved = _lookup_reference(context.resolver, reference)
    if resolved is None:
        raise McpProfileError("MCP $ref does not resolve in the descriptor")
    target = resolved.contents
    _require_schema(target)
    return target, _ref_target_context(context, resolved.resolver, target)


class _ScalarTarget:
    """A pointer target the draft specification could not enter."""

    def __init__(self, contents: object, resolver: Any) -> None:
        self.contents = contents
        self.resolver = resolver


def _lookup_reference(resolver: Any, reference: str) -> Any | None:
    """Look up the original spelling. A scalar target is recovered for the schema check.

    ``referencing`` raises ``AttributeError`` when a JSON Pointer lands on a
    non-mapping. The profile still has to report that value as a non-schema.
    The recovery reads the pointer on the current resource after the library
    lookup has failed; it does not replace the reference the lookup received.
    An intermediate array is not recovered: the library does not return it.
    ``PointerToNowhere`` is the library result for that spelling. It is not
    retried by removing a URI from the registry.
    """

    try:
        return resolver.lookup(reference)
    except AttributeError:
        recovered = _recover_scalar_target(resolver, reference)
        if recovered is None:
            return None
        return _ScalarTarget(recovered, resolver)
    except (PointerToNowhere, Unresolvable, *_SCHEMA_LIBRARY_ERRORS):
        return None


def _recover_scalar_target(resolver: Any, reference: str) -> object | None:
    if not reference.startswith("#/"):
        return None
    try:
        node = resolver.lookup("#").contents
    except (Unresolvable, *_SCHEMA_LIBRARY_ERRORS):
        return None
    for raw in reference[2:].split("/"):
        if not isinstance(node, Mapping):
            return None
        try:
            token = _json_pointer_token(unquote(raw))
        except McpProfileError:
            return None
        if token not in node:
            return None
        node = node[token]
    if isinstance(node, (Mapping, bool)):
        return None
    if node is None or isinstance(node, (str, int, float, bytes)):
        return node
    return None


def _reject_ambiguous_anchor(
    resource_id: int,
    name: str,
    anchors: Mapping[tuple[int, str], tuple[Mapping[str, Any], ...]],
) -> None:
    if len(anchors.get((resource_id, name), ())) > 1:
        raise McpProfileError("MCP $ref anchor is ambiguous")


def _reject_noncanonical_array_index(resolver: Any, fragment: str) -> None:
    """Apply rule 4 to every array index the library resolved.

    Tokens match ``referencing`` 0.37.0: unquote the pointer, split on ``/``,
    then substitute ``~1`` and ``~0`` when that escape is valid. A segment the
    strict decoder refuses is not an early return. Rule 4 still applies to
    every other token whose parent, resolved by the library, is an array.
    """

    if not fragment.startswith("/"):
        return
    raw_tokens = unquote(fragment[1:]).split("/")
    tokens: list[str] = []
    for raw_token in raw_tokens:
        try:
            tokens.append(_json_pointer_token(raw_token))
        except McpProfileError:
            tokens.append(raw_token)
    _validate_pointer_array_indices(resolver, raw_tokens, tokens)


def _validate_pointer_array_indices(
    resolver: Any,
    raw_tokens: Sequence[str],
    tokens: Sequence[str],
) -> None:
    """Require a canonical index only when the resolved parent is an array.

    Every prefix is resolved by ``referencing``. The profile reads the parent
    container from that result; it never infers an array from the token text.
    Object member names therefore keep RFC 6901 syntax, while ``int()``-style
    array spellings accepted by Python cannot become external input.
    """

    prefix: list[str] = []
    for raw_token, token in zip(raw_tokens, tokens, strict=True):
        parent_reference = "#"
        if prefix:
            parent_reference = "#/" + "/".join(
                quote(part, safe="~") for part in prefix
            )
        parent = _lookup_reference(resolver, parent_reference)
        if parent is not None and isinstance(
            parent.contents, Sequence
        ) and not isinstance(parent.contents, (str, bytes)):
            canonical = token == "0" or (
                bool(token)
                and token.isascii()
                and token.isdigit()
                and token[0] in "123456789"
            )
            if not canonical:
                raise McpProfileError(
                    "MCP $ref fragment is not a valid JSON Pointer"
                )
        prefix.append(raw_token)


def _check_schema_keywords(
    node: object,
    context: _ResolutionContext,
) -> None:
    """Apply dialect and ``$ref`` rules to one reached schema object.

    ``$ref`` resolution already happened in ``_resolve_graph`` with the
    context of each path that reached this node. Reference-path depth is
    ``assert_reference_path_bound``. This pass only reads the node's own
    keywords; children are separate states of the graph.
    """

    if not isinstance(node, Mapping):
        return
    try:
        enforce_emitted_schema_rules(node)
    except SchemaCalculationFailure as exc:
        raise _as_profile(exc) from exc


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
