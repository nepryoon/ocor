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
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import quote, urljoin

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, UnknownType
from referencing import Registry, Resource
from referencing.exceptions import CannotDetermineSpecification, Unresolvable
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


def _pointer_maybe_in_subresource(
    segments: Sequence[int | str],
    resolver: Any,
    subresource: Resource[Any],
) -> Any:
    """Keep library pointer context when the target is not a schema object.

    ``referencing`` resolves every pointer segment and then asks the 2020-12
    specification for a subresource. Its specification assumes a mapping and
    raises ``AttributeError`` for a scalar target before returning it. The
    profile still has to inspect that target to report the typed non-schema
    refusal. The wrapper keeps the library traversal and only declines to
    enter a subresource it cannot read.
    """

    try:
        return DRAFT202012.maybe_in_subresource(segments, resolver, subresource)
    except (AttributeError, TypeError):
        contents = subresource.contents
        if isinstance(contents, Sequence) and not isinstance(contents, (str, bytes)):
            raise
        return resolver


def _profile_anchors_in(
    _specification: Any,
    contents: Mapping[str, Any],
) -> Any:
    """Keep the pinned draft's anchor discovery in the profile specification."""

    return DRAFT202012.anchors_in(contents)


def _profile_id_of(contents: Any) -> str | None:
    """Return the raw ``$id``, exactly as the pinned draft's ``id_of`` does.

    The value is not type-checked here: a non-string ``$id`` fails inside the
    library crawl (``Resource.id`` strips the trailing fragment on the raw
    value) and the failure is translated to the typed
    ``MCP schema resource index is not resolvable`` refusal, fail-closed and
    with no raw exception escaping the module. This is the rule for every
    schema position of every tree, descriptor and tool schemas alike.
    """

    if not isinstance(contents, Mapping):
        return None
    return contents.get("$id")


def _profile_subresources_of(
    contents: Mapping[str, Any],
) -> Any:
    """Keep scalar instance values out of the schema-resource crawl.

    The profile checks a reached scalar as a typed non-schema target. An
    unreferenced scalar in a keyword position is not a resource and must not
    make the library's resource identity fail while the index is built.
    """

    return (
        resource
        for resource in DRAFT202012.subresources_of(contents)
        if isinstance(resource, Mapping)
    )


_PROFILE_SPECIFICATION: Any = cast(Any, type(DRAFT202012))(
    name=DRAFT202012.name,
    id_of=_profile_id_of,
    subresources_of=_profile_subresources_of,
    anchors_in=_profile_anchors_in,
    maybe_in_subresource=_pointer_maybe_in_subresource,
)


class McpProfileError(ValueError):
    """The MCP profile rejected a descriptor or an input schema."""

    def __init__(self, message: str) -> None:
        if not isinstance(message, str) or not message or len(message) > 512:
            raise ValueError("MCP profile message must be bounded and non-empty")
        super().__init__(message)


@dataclass(frozen=True)
class _SchemaTree:
    """One autonomous schema tree: the descriptor or one tool schema field.

    ``root`` is the original document object the profile checks. The registry
    contains only this tree's resources, crawled by referencing 0.37.0 with
    the base URI fixed for the tree, so no lookup can reach a resource of
    another tree. ``node_uris`` maps every schema-position node to the
    resource URI the crawl owns it under; static keyword descent uses that
    mapping, never its own join, as the context of a child node.
    """

    root_uri: str
    root: Mapping[str, Any]
    resources: Mapping[str, Resource[Any]]
    registry: Registry[Any]
    aliases: Mapping[int, object]
    anchors: Mapping[tuple[str, str], tuple[Mapping[str, Any], ...]]
    node_uris: Mapping[int, str]


@dataclass(frozen=True)
class _ResolutionContext:
    """The resolver state at one schema node, on its tree.

    ``resolver`` is the resolver of the current resource: the tree registry
    for keyword descent, or the resolver a ``lookup`` returned for a
    reference path. ``base_uri`` is that resolver's base. ``resource_uri``
    is the tree URI that owns the node, used only for the profile's anchor
    ambiguity index.
    """

    tree: _SchemaTree
    resolver: Any
    base_uri: str
    resource_uri: str

    @property
    def registry(self) -> Registry[Any]:
        registry = getattr(self.resolver, "_registry", None)
        if registry is None:
            return self.tree.registry
        return cast(Registry[Any], registry)

    @property
    def resources(self) -> Mapping[str, Resource[Any]]:
        return self.tree.resources

    @property
    def aliases(self) -> Mapping[int, object]:
        return self.tree.aliases

    @property
    def anchors(self) -> Mapping[tuple[str, str], tuple[Mapping[str, Any], ...]]:
        return self.tree.anchors

    @property
    def node_uris(self) -> Mapping[int, str]:
        return self.tree.node_uris


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
    starts with ``/`` is a JSON Pointer, and any other decoded fragment is a
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
        if (
            not isinstance(tool, Mapping)
            or not isinstance(tool.get("name"), str)
            or not tool["name"]
        ):
            raise McpProfileError("MCP tool name must be a non-empty string")
        names.append(str(tool["name"]))
    if names != sorted(names) or len(names) != len(set(names)):
        raise McpProfileError("MCP tools are not in deterministic name order")
    if "$defs" in document:
        raise McpProfileError("MCP descriptor must not declare top-level $defs")
    _walk_json(document, depth=1, nodes=[0])
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


def _declared_id(node: object) -> str | None:
    """Return the resource identifier, or None when the node does not declare one.

    A trailing empty fragment is removed before the join, as referencing
    0.37.0 does in ``Resource.id`` (``rstrip("#")``). ``#`` and ``###`` are
    not identifiers. An empty string stays absent.
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


def _resource_uri(node: object, base_uri: str) -> str:
    """Join a declared ``$id`` onto ``base_uri``.

    ``urljoin`` is the resource identity used by referencing 0.37.0 on the
    governed Python. The identifier has already had a trailing empty fragment
    removed, so ``#`` never reaches ``urljoin`` from here. ``urljoin(base, '#')``
    is not always ``base`` (an empty base and a non-relative scheme both yield
    ``#``). An identifier that joins to ``base_uri`` does not start another
    resource.
    """
    identifier = _declared_id(node)
    if identifier is None:
        return base_uri
    try:
        joined = urljoin(base_uri, identifier)
        if base_uri == "" and joined == identifier:
            urljoin("https://ocor.invalid/", identifier)
        return joined
    except ValueError as exc:
        raise McpProfileError("MCP $id is not a valid URI reference") from exc


def _changes_resource(node: object, base_uri: str) -> bool:
    """True when ``node`` joins to a URI other than ``base_uri``."""
    return _resource_uri(node, base_uri) != base_uri


def _iter_schema_children(node: Mapping[str, Any]) -> Iterator[object]:
    """Yield only values in JSON Schema 2020-12 applicator positions.

    ``additionalItems`` is excluded: the pinned draft's crawl does not index
    it as a subresource and the profile does not index anchors there either.
    """

    for key, value in node.items():
        if key in _SCHEMA_MAP_KEYWORDS and isinstance(value, Mapping):
            yield from value.values()
            continue
        if (
            key in _SCHEMA_ARRAY_KEYWORDS
            and isinstance(value, Sequence)
            and not isinstance(value, (str, bytes))
        ):
            yield from value
            continue
        if key in _SCHEMA_OBJECT_KEYWORDS:
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                yield from value
            else:
                yield value


def _iter_check_children(node: Mapping[str, Any]) -> Iterator[object]:
    """Yield schema children for keyword checks, including ``additionalItems``.

    The pinned draft does not crawl ``additionalItems`` as a subresource, but
    the profile still checks a ``$ref`` stored there: the value is a schema
    position for dialect, local-reference and resolution rules.
    """

    yield from _iter_schema_children(node)
    if "additionalItems" in node:
        yield node["additionalItems"]


def _create_resource(contents: Mapping[str, Any]) -> Resource[Any]:
    """Create one draft-2020-12 resource without copying the document object."""
    return cast(Resource[Any], _PROFILE_SPECIFICATION.create_resource(contents))


def _crawl_document_resources(
    document: Mapping[str, Any],
    document_uri: str,
    aliases: dict[int, object],
) -> dict[str, Resource[Any]]:
    """Use the pinned crawl as the authority for one schema resource tree."""

    contents = _canonical_resource_contents(document, document_uri)
    if contents is not document:
        aliases[id(contents)] = document
    root = _create_resource(contents)
    try:
        crawled = Registry().with_resource(document_uri, root).crawl()
    except McpProfileError:
        raise
    except _SCHEMA_LIBRARY_ERRORS as exc:
        raise McpProfileError("MCP schema resource index is not resolvable") from exc

    ancestors = _same_uri_resource_ancestors(document, document_uri)
    resources: dict[str, Resource[Any]] = {}
    for resource_uri, resource in crawled.items():
        inherited = ancestors.get(id(resource.contents), ())
        original = cast(
            Mapping[str, Any],
            inherited[0]
            if inherited
            else aliases.get(id(resource.contents), resource.contents),
        )
        canonical = _canonical_resource_contents(original, resource_uri)
        resources[resource_uri] = _create_resource(canonical)
        if canonical is not original:
            aliases[id(canonical)] = original
    # A descendant whose ``$id`` joins to the URI already occupied by this
    # crawl root does not replace that root. The library resolver keeps the
    # current resource until an identifier actually changes the base URI.
    resources[document_uri] = root
    return resources


def _same_uri_resource_ancestors(
    root: Mapping[str, Any],
    root_uri: str,
) -> dict[int, tuple[Mapping[str, Any], ...]]:
    """Record resource-root ancestors that already occupy the same URI.

    ``Registry.crawl`` keeps the last resource for a URI. A descendant whose
    ``$id`` joins to the current URI has not started a new resource, so it must
    not replace the resource that owns that URI. Sibling collisions are left to
    the library's last-wins rule.
    """

    ancestors: dict[int, tuple[Mapping[str, Any], ...]] = {}
    active: dict[str, tuple[Mapping[str, Any], ...]] = {}
    nodes = 0

    def visit(
        node: object,
        base_uri: str,
        *,
        root_node: bool,
        depth: int,
    ) -> None:
        nonlocal nodes
        if not isinstance(node, Mapping):
            return
        nodes += 1
        if depth > MAX_SCHEMA_DEPTH or nodes > MAX_SCHEMA_NODES:
            raise McpProfileError("MCP schema exceeds the revision bounds")
        resource_uri = _resource_uri(node, base_uri)
        owners = active.get(resource_uri, ())
        ancestors[id(node)] = owners
        enters_resource = root_node or resource_uri != base_uri
        if enters_resource:
            active[resource_uri] = owners + (node,)
        try:
            for child in _iter_schema_children(node):
                visit(
                    child,
                    resource_uri,
                    root_node=False,
                    depth=depth + 1,
                )
        finally:
            if enters_resource:
                active[resource_uri] = owners

    visit(root, root_uri, root_node=True, depth=1)
    return ancestors


def _collect_declared_ids(document: Mapping[str, Any]) -> set[str]:
    """Collect every string ``$id`` value anywhere in the document.

    The walk is bounded like the JSON bounds walk, which already ran on the
    same document. Values are compared raw: a nested absolute ``$id`` that
    spells a candidate synthetic URI would collide by string equality, and a
    relative ``$id`` cannot spell a ``urn:`` URI.
    """

    declared_ids: set[str] = set()
    nodes = [0]

    def visit(node: object, depth: int) -> None:
        nodes[0] += 1
        if depth > MAX_SCHEMA_DEPTH or nodes[0] > MAX_SCHEMA_NODES:
            raise McpProfileError("MCP schema exceeds the revision bounds")
        if isinstance(node, Mapping):
            declared = node.get("$id")
            if isinstance(declared, str):
                declared_ids.add(declared)
            for value in node.values():
                visit(value, depth + 1)
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
            for item in node:
                visit(item, depth + 1)

    visit(document, 1)
    return declared_ids


def _synthetic_tool_uri(
    index: int,
    field: str,
    declared_ids: set[str],
) -> str:
    """A fixed base URI distinct from every declared ``$id`` of the document."""

    candidate = f"urn:ocor:embedded-tool:{index}:{field}"
    suffix = 2
    while candidate in declared_ids:
        candidate = f"urn:ocor:embedded-tool:{index}:{field}:{suffix}"
        suffix += 1
    return candidate


def _build_schema_trees(
    document: Mapping[str, Any],
) -> tuple[tuple[int, str, _SchemaTree], ...]:
    """Index one autonomous tree per tool schema field.

    MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15): each ``inputSchema`` and each
    ``outputSchema`` is an autonomous JSON Schema 2020-12 resource. Its base
    URI is its ``$id`` when present, otherwise a fixed URI that is distinct
    for every tool and field and coincides with no ``$id`` of the document
    (``_synthetic_tool_uri`` picks the URI after reading every declared
    ``$id``). The descriptor is not a schema tree: no registry or anchor
    index is shared between trees and a lookup can never reach another
    tree's resource or the descriptor.
    """

    declared_ids = _collect_declared_ids(document)
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
                declared = _declared_id(schema)
                if declared is not None:
                    root_uri = declared
                else:
                    root_uri = _synthetic_tool_uri(index, field, declared_ids)
                tool_trees.append((index, field, _schema_tree(schema, root_uri)))
    return tuple(tool_trees)


def _schema_tree(root: Mapping[str, Any], root_uri: str) -> _SchemaTree:
    """Crawl one tree with the pinned library and index its resources."""

    aliases: dict[int, object] = {}
    resources = _crawl_document_resources(root, root_uri, aliases)
    anchors = _collect_anchor_owners(list(resources.items()))
    node_uris = _collect_node_uris(root, root_uri, resources, aliases)
    registry = Registry().with_resources(list(resources.items()))
    return _SchemaTree(
        root_uri=root_uri,
        root=root,
        resources=resources,
        registry=registry,
        aliases=aliases,
        anchors=anchors,
        node_uris=node_uris,
    )


def _collect_node_uris(
    root: Mapping[str, Any],
    root_uri: str,
    resources: Mapping[str, Resource[Any]],
    aliases: Mapping[int, object],
) -> dict[int, str]:
    """Map every schema node to the resource URI the crawl owns it under.

    The mapping is the library crawl's own assignment: the resource roots
    registered per URI, with every other node inheriting the URI of its
    enclosing resource. Keyword descent uses this map as the context of a
    child node instead of joining ``$id`` again, so a no-op ``$id`` chain
    can never diverge from the library.
    """

    owned: dict[int, str] = {}
    for uri, resource in resources.items():
        original = aliases.get(id(resource.contents), resource.contents)
        owned[id(original)] = uri
    node_uris: dict[int, str] = {}
    nodes = [0]

    def visit(node: object, uri: str, *, depth: int) -> None:
        if not isinstance(node, Mapping):
            return
        nodes[0] += 1
        if depth > MAX_SCHEMA_DEPTH or nodes[0] > MAX_SCHEMA_NODES:
            raise McpProfileError("MCP schema exceeds the revision bounds")
        identity = id(node)
        if identity in node_uris:
            return
        owner = owned.get(identity, uri)
        node_uris[identity] = owner
        for child in _iter_schema_children(node):
            visit(child, owner, depth=depth + 1)

    visit(root, root_uri, depth=1)
    return node_uris


def _canonical_resource_contents(
    node: Mapping[str, Any],
    resource_uri: str,
) -> Mapping[str, Any]:
    """Give a resource root its already-joined identity before registration."""

    declared = _declared_id(node)
    if declared is None or resource_uri == declared:
        return node
    canonical = dict(node)
    canonical["$id"] = resource_uri
    return canonical


def _collect_anchor_owners(
    resources: Sequence[tuple[str, Resource[Any]]],
) -> dict[tuple[str, str], tuple[Mapping[str, Any], ...]]:
    """Index anchors per effective resource for the profile's ambiguity rule.

    ``referencing`` keeps one anchor when a resource repeats a plain name. The
    profile is stricter and records every owner, but the owner is used only to
    reject ambiguity; the target itself still comes from ``Resolver.lookup``.
    """

    owners: dict[tuple[str, str], list[Mapping[str, Any]]] = {}

    def visit(
        node: object,
        resource_uri: str,
        *,
        root: bool,
        depth: int,
        visited: set[int],
    ) -> None:
        if depth > MAX_SCHEMA_DEPTH or len(visited) > MAX_SCHEMA_NODES:
            raise McpProfileError("MCP schema exceeds the revision bounds")
        if not isinstance(node, Mapping):
            return
        identity = id(node)
        if identity in visited:
            return
        visited.add(identity)
        if (
            not root
            and _declared_id(node) is not None
            and _changes_resource(node, resource_uri)
        ):
            return

        names = {
            value
            for keyword in _ANCHOR_KEYWORDS
            for value in (node.get(keyword),)
            if isinstance(value, str)
        }
        for name in names:
            owners.setdefault((resource_uri, name), []).append(node)

        for child in _iter_schema_children(node):
            visit(child, resource_uri, root=False, depth=depth + 1, visited=visited)

    for resource_uri, resource in resources:
        visit(
            resource.contents,
            resource_uri,
            root=True,
            depth=1,
            visited=set(),
        )
    return {key: tuple(value) for key, value in owners.items()}


def _root_context(tree: _SchemaTree) -> _ResolutionContext:
    """The resolver state at the root resource of one tree."""

    return _ResolutionContext(
        tree=tree,
        resolver=tree.registry.resolver(tree.root_uri),
        base_uri=tree.root_uri,
        resource_uri=tree.root_uri,
    )


def _descend(context: _ResolutionContext, child: object) -> _ResolutionContext:
    """Enter a keyword child with the resolver the pinned library gives.

    A node no reference reaches is checked with this context; a reference
    path replaces it with the resolver its lookup returned. A child the
    crawl indexed keeps the crawl-assigned resource URI. A child outside
    the crawl map — a schema position such as ``additionalItems``, or a
    schema reached through instance data such as ``const``, ``default`` or
    ``examples`` — enters through ``Resolver.in_subresource`` on the
    current resource, exactly as the jsonschema validator descends: an
    ``$id`` there changes the base URI for the references inside it while
    the registry is unchanged, so a look-up against a URI the crawl never
    registered fails closed.

    When a crawled child stays inside the current resource the resolver
    that reached it is preserved: a lookup across an anchor keeps crawl
    state in the resolver, and rebuilding it from the tree registry would
    drop that state, so pointers inside the reached schema must keep using
    it. Only a child that starts another resource gets a fresh resolver
    rooted at its own URI.
    """

    if not isinstance(child, Mapping):
        return context
    uri = context.node_uris.get(id(child))
    if uri is not None:
        if uri == context.resource_uri:
            return _ResolutionContext(
                tree=context.tree,
                resolver=context.resolver,
                base_uri=context.base_uri,
                resource_uri=context.resource_uri,
            )
        return _ResolutionContext(
            tree=context.tree,
            resolver=context.tree.registry.resolver(uri),
            base_uri=uri,
            resource_uri=uri,
        )
    try:
        entered = context.resolver.in_subresource(_create_resource(child))
    except McpProfileError:
        raise
    except _SCHEMA_LIBRARY_ERRORS as exc:
        raise McpProfileError("MCP $id is not a valid URI reference") from exc
    base_uri = getattr(entered, "_base_uri", context.base_uri)
    if not isinstance(base_uri, str) or not base_uri:
        base_uri = context.base_uri
    resource_uri = (
        context.resource_uri if base_uri == context.base_uri else base_uri
    )
    return _ResolutionContext(
        tree=context.tree,
        resolver=entered,
        base_uri=base_uri,
        resource_uri=resource_uri,
    )


def _ref_target_context(
    context: _ResolutionContext,
    resolver: Any,
    target: object,
) -> _ResolutionContext:
    """Keep the resolver a ``lookup`` returned for the target it reached.

    The base URI is the library's own. The resource URI comes from the crawl
    ownership map, so the profile's anchor ambiguity index stays aligned
    with the tree the target belongs to.
    """

    base_uri = getattr(resolver, "_base_uri", context.base_uri)
    if not isinstance(base_uri, str) or not base_uri:
        base_uri = context.base_uri
    return _ResolutionContext(
        tree=context.tree,
        resolver=resolver,
        base_uri=base_uri,
        resource_uri=context.node_uris.get(id(target), base_uri),
    )


def _resolve_graph(
    roots: Sequence[tuple[Any, _ResolutionContext]],
) -> tuple[list[tuple[Any, _ResolutionContext, int]], set[tuple[int, str]]]:
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

    static_order: list[tuple[Any, _ResolutionContext, int]] = []
    static_refs: list[tuple[Any, _ResolutionContext, int]] = []
    visited_static: set[tuple[int, str, int]] = set()
    queue: list[tuple[Any, _ResolutionContext, int]] = [
        (node, context, 1) for node, context in roots
    ]
    while queue:
        node, context, depth = queue.pop(0)
        if not isinstance(node, Mapping):
            continue
        if depth > MAX_SCHEMA_DEPTH:
            raise McpProfileError("MCP schema exceeds the revision bounds")
        state = (id(node), context.base_uri, id(context.registry))
        if state in visited_static:
            continue
        visited_static.add(state)
        static_order.append((node, context, depth))
        if "$ref" in node:
            static_refs.append((node, context, depth))
        for child in _iter_check_children(node):
            queue.append((child, _descend(context, child), depth + 1))

    ref_states: set[tuple[int, str]] = set()
    ref_reached: set[int] = set()
    static_outcomes: dict[tuple[int, str], tuple[object, _ResolutionContext]] = {}

    static_sequence: list[tuple[int, int]] = []
    static_failures: dict[tuple[int, str], McpProfileError] = {}
    ref_queue: list[tuple[Any, _ResolutionContext, int]] = []
    visited_ref: set[tuple[int, str, int]] = set()
    ref_order: list[tuple[Any, _ResolutionContext, int]] = []

    def seed_static() -> None:
        for node, context, depth in static_refs:
            identity = id(node)
            key = (identity, context.base_uri)
            static_sequence.append((identity, depth))
            try:
                target, target_context = _resolve_reference(
                    node["$ref"], context
                )
            except McpProfileError as exc:
                static_failures[key] = exc
                continue
            static_outcomes[key] = (target, target_context)
        for node, _context, depth in static_refs:
            key = (id(node), _context.base_uri)
            if id(node) in ref_reached:
                continue
            outcome = static_outcomes.get(key)
            if outcome is None:
                continue
            target, target_context = outcome
            if isinstance(target, Mapping):
                ref_queue.append((target, target_context, depth + 1))

    def drain_refs() -> None:
        while ref_queue:
            node, context, depth = ref_queue.pop(0)
            if not isinstance(node, Mapping):
                continue
            if depth > MAX_SCHEMA_DEPTH:
                raise McpProfileError("MCP schema exceeds the revision bounds")
            state = (id(node), context.base_uri, id(context.registry))
            if state in visited_ref:
                continue
            visited_ref.add(state)
            ref_reached.add(id(node))
            ref_states.add((id(node), context.base_uri))
            ref_order.append((node, context, depth))
            if "$ref" in node:
                target, target_context = _resolve_reference(
                    node["$ref"], context
                )
                if isinstance(target, Mapping):
                    ref_queue.append((target, target_context, depth + 1))
            for child in _iter_check_children(node):
                ref_queue.append((child, _descend(context, child), depth + 1))

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

    for identity, _depth in static_sequence:
        if identity in ref_reached:
            continue
        for key, error in static_failures.items():
            if key[0] == identity:
                raise error
    return static_order + ref_order, ref_states


def _check_reached_schemas(
    order: Sequence[tuple[Any, _ResolutionContext, int]],
    ref_states: set[tuple[int, str]],
) -> None:
    """Check each reached state: static contexts only where no ref lands."""

    ref_reached = {identity for identity, _base in ref_states}
    for node, context, depth in order:
        identity = id(node)
        if identity in ref_reached and (identity, context.base_uri) not in ref_states:
            continue
        _check_schema_keywords(node, context, depth=depth)


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
    decoded = _decode_uri_fragment(reference[1:])
    if decoded and not decoded.startswith("/"):
        _reject_ambiguous_anchor(context.resource_uri, decoded, context.anchors)
        library_reference = "#" + decoded
    elif decoded:
        raw_tokens = decoded[1:].split("/")
        tokens = [_json_pointer_token(raw_token) for raw_token in raw_tokens]
        _validate_pointer_array_indices(context.resolver, raw_tokens, tokens)
        # ``referencing`` percent-decodes a JSON Pointer once. Re-encode the
        # already decoded fragment so a literal ``%`` is not decoded twice,
        # while the leading separator stays visible to ``Resolver.lookup``.
        library_reference = "#" + quote(decoded, safe="/~")
    else:
        library_reference = "#"
    resolved = _lookup_reference(context.resolver, library_reference)
    if resolved is None:
        raise McpProfileError("MCP $ref does not resolve in the descriptor")
    target = context.aliases.get(id(resolved.contents), resolved.contents)
    _require_schema(target)
    return target, _ref_target_context(context, resolved.resolver, target)


def _lookup_reference(resolver: Any, reference: str) -> Any | None:
    """Return one library lookup or ``None`` when the fragment does not resolve."""

    try:
        return resolver.lookup(reference)
    except (Unresolvable, *_SCHEMA_LIBRARY_ERRORS):
        return None


def _resolved_contents(context: _ResolutionContext, resolved: Any) -> object:
    """Return the document object behind a canonical registry root."""

    return context.aliases.get(id(resolved.contents), resolved.contents)


def _reject_ambiguous_anchor(
    resource_uri: str,
    name: str,
    anchors: Mapping[tuple[str, str], tuple[Mapping[str, Any], ...]],
) -> None:
    if len(anchors.get((resource_uri, name), ())) > 1:
        raise McpProfileError("MCP $ref anchor is ambiguous")


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
    *,
    depth: int,
) -> None:
    """Apply dialect and ``$ref`` rules to one reached schema object.

    ``$ref`` resolution already happened in ``_resolve_graph`` with the
    context of each path that reached this node. This pass only reads the
    node's own keywords; children are separate states of the graph.
    """

    if depth > MAX_SCHEMA_DEPTH:
        raise McpProfileError("MCP schema exceeds the revision bounds")
    if not isinstance(node, Mapping):
        return
    if "$id" in node:
        _resource_uri(node, context.base_uri)
    if "$dynamicRef" in node or "$recursiveRef" in node:
        raise McpProfileError("MCP $ref resolution does not follow dynamic references")
    if "$schema" in node:
        dialect = node["$schema"]
        if not isinstance(dialect, str) or dialect not in ACCEPTED_DIALECTS:
            raise McpProfileError("MCP schema dialect must be JSON Schema 2020-12")


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


def _reject_surrogate(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise McpProfileError("MCP descriptor contains a lone surrogate")
