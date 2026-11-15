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
from dataclasses import dataclass, field
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

    ``Resource.id`` strips a trailing empty fragment, so an ``$id`` of ``#``
    becomes the empty URI reference and joins to the current URI. The crawl of
    referencing 0.37.0 then replaces the current resource for that URI; the
    profile must see the same crawl. The profile's no-op rule stays in
    ``_declared_id`` and ``_resource_uri``, which never change what the library
    crawls.
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
class _ResolutionIndex:
    """Schema-position resources and the profile's anchor ambiguity index."""

    root_uri: str
    resources: Mapping[str, Resource[Any]]
    registry: Registry[Any]
    aliases: Mapping[int, object]
    anchors: Mapping[tuple[str, str], tuple[Mapping[str, Any], ...]]
    local_registries: Mapping[str, Registry[Any]]


@dataclass(frozen=True)
class _ResolutionContext:
    """The resolver and the effective resource URI at one schema node."""

    resolver: Any
    resource_uri: str
    base_uri: str
    document_uri: str
    registry: Registry[Any]
    resources: Mapping[str, Resource[Any]]
    aliases: Mapping[int, object]
    anchors: Mapping[tuple[str, str], tuple[Mapping[str, Any], ...]]
    fallback_resolver: Any | None = None
    fallback_resource_uri: str | None = None
    fallback_registry: Registry[Any] | None = None
    embedded_local_registries: Mapping[str, Registry[Any]] = field(
        default_factory=dict
    )


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
    classified. A decoded empty fragment is the empty JSON Pointer: it identifies
    the current resource. That resource is the URI produced by ``urljoin`` of each
    ``$id`` onto the base URI, the same join referencing 0.37.0 uses on the
    governed Python. A trailing empty fragment on ``$id`` is stripped before
    that join, matching referencing 0.37.0 ``Resource.id``. An ``$id`` of ``#``,
    an empty ``$id``, or any ``$id`` that joins to the same URI does not start
    another resource. A joined URI that
    differs does. The empty fragment is not a plain-name anchor and there is no
    branch that always selects the whole document. A decoded fragment that
    starts with ``/`` is a JSON Pointer, and any other decoded fragment is a
    plain-name anchor (``$anchor`` or ``$dynamicAnchor``). ``~`` escapes are
    validated before substitution. A ref inside an embedded tool schema that
    does not change the resource URI resolves in that schema first and in the
    current resource second. The empty pointer does not use that two-root
    search, so ``#`` stays on the current resource and is not ambiguous. Two
    different objects for one non-empty pointer or one plain name are rejected.
    A nested ``$id`` whose joined URI differs is a separate resource, and
    ``additionalItems`` is not an anchor applicator in draft 2020-12. The value
    a reference lands on must itself be a 2020-12 schema. Dialect,
    local-reference and resolution rules also
    apply to a schema reached through instance data such as ``const`` or ``default``.
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
    deferred: dict[int, tuple[Any, int, _ResolutionContext]] = {}
    resolution = _build_resolution_index(document)
    document_base = resolution.root_uri
    document_context = _ResolutionContext(
        resolver=resolution.registry.resolver(document_base),
        resource_uri=document_base,
        base_uri=document_base,
        document_uri=document_base,
        registry=resolution.registry,
        resources=resolution.resources,
        aliases=resolution.aliases,
        anchors=resolution.anchors,
        embedded_local_registries=resolution.local_registries,
    )
    _check_schema_keywords(
        document,
        document_context,
        depth=1,
        seen=seen,
        deferred=deferred,
    )
    for index, tool in enumerate(tools):
        if isinstance(tool, Mapping):
            for field in ("inputSchema", "outputSchema"):
                if field in tool:
                    tool_schema = tool[field]
                    context = _enter_tool_schema(
                        document_context,
                        tool_schema,
                        index=index,
                        field=field,
                    )
                    _check_schema_keywords(
                        tool_schema,
                        context,
                        depth=1,
                        seen=seen,
                        deferred=deferred,
                    )
    while deferred:
        identity = min(deferred, key=lambda item: deferred[item][1])
        target, depth, context = deferred.pop(identity)
        if identity in seen:
            continue
        _check_schema_keywords(
            target,
            context,
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
    """Yield only values in JSON Schema 2020-12 applicator positions."""

    for key, value in node.items():
        if key == "additionalItems":
            continue
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


def _create_resource(contents: Mapping[str, Any]) -> Resource[Any]:
    """Create one draft-2020-12 resource without copying the document object."""
    return cast(Resource[Any], _PROFILE_SPECIFICATION.create_resource(contents))


def _resource_resolver(uri: str, resource: Resource[Any]) -> Any:
    """Return a resolver whose registry contains only this resource.

    Every fragment accepted by the profile is same-document. Keeping one
    resource in the registry prevents an unrelated non-schema sibling in the
    descriptor, or in another embedded schema, from deciding a lookup on the
    current resource. Nested ``$id`` resources reached by a pointer are still
    discovered by ``referencing`` from the current resource.
    """

    return Registry().with_resource(uri, resource).resolver(uri)


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


def _register_resource_root(
    node: Mapping[str, Any],
    resource_uri: str,
    resources: dict[str, Resource[Any]],
    aliases: dict[int, object],
) -> None:
    """Register one profile-defined root without inventing a second resolution."""

    contents = _canonical_resource_contents(node, resource_uri)
    resources[resource_uri] = _create_resource(contents)
    if contents is not node:
        aliases[id(contents)] = node


def _build_resolution_index(document: Mapping[str, Any]) -> _ResolutionIndex:
    """Index the resources of schema positions, never data inside instance values.

    Each resource root is a shallow copy when its ``$id`` is relative, with the
    root identifier rewritten to the already joined effective URI. This is the
    object ``referencing`` expects in a registry keyed by that URI: its crawl
    would otherwise join the relative identifier a second time. Every child
    remains the document object the profile checks.
    """

    document_uri = _resource_uri(document, "")
    aliases: dict[int, object] = {}
    resources = _crawl_document_resources(document, document_uri, aliases)
    local_registries: dict[str, Registry[Any]] = {}

    tools = document.get("tools")
    if isinstance(tools, Sequence) and not isinstance(tools, (str, bytes)):
        for index, tool in enumerate(tools):
            if not isinstance(tool, Mapping):
                continue
            for field in ("inputSchema", "outputSchema"):
                schema = tool.get(field)
                if not isinstance(schema, Mapping):
                    continue
                embedded_uri = f"urn:ocor:embedded-tool:{index}:{field}"
                candidate = _resource_uri(schema, document_uri)
                if candidate != document_uri:
                    tree = _crawl_document_resources(schema, candidate, aliases)
                    resources.update(tree)
                    local_registries[embedded_uri] = Registry().with_resources(
                        list(tree.items())
                    )
                    continue
                temporary = dict(schema)
                temporary.pop("$id", None)
                discovered = _crawl_document_resources(
                    temporary,
                    document_uri,
                    aliases,
                )
                discovered.pop(document_uri, None)
                resources.update(discovered)
                _register_resource_root(
                    schema,
                    embedded_uri,
                    resources,
                    aliases,
                )
                body = _canonical_resource_contents(schema, document_uri)
                if body is not schema:
                    aliases[id(body)] = schema
                local: dict[str, Resource[Any]] = {
                    document_uri: _create_resource(body)
                }
                local.update(discovered)
                local_registries[embedded_uri] = Registry().with_resources(
                    list(local.items())
                )
    registry = Registry().with_resources(list(resources.items()))
    anchors = _collect_anchor_owners(list(resources.items()))
    return _ResolutionIndex(
        root_uri=document_uri,
        resources=resources,
        registry=registry,
        aliases=aliases,
        anchors=anchors,
        local_registries=local_registries,
    )


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


def _enter_schema_resource(
    context: _ResolutionContext,
    node: object,
) -> _ResolutionContext:
    """Enter one schema resource whose ``$id`` changes the effective URI.

    ``referencing`` owns the lookup of every fragment. The index contains only
    resources discovered by its crawl, plus the profile-defined roots for tool
    schemas. A resource that was not discovered therefore gets only a base URI:
    the next lookup fails instead of creating a resource from instance data.
    """

    if not isinstance(node, Mapping) or "$id" not in node:
        return context
    resource_uri = _resource_uri(node, context.base_uri)
    if resource_uri == context.base_uri or resource_uri == context.resource_uri:
        return context
    if context.fallback_resource_uri == resource_uri:
        return _ResolutionContext(
            resolver=context.fallback_resolver,
            resource_uri=resource_uri,
            base_uri=resource_uri,
            document_uri=context.document_uri,
            registry=context.fallback_registry or context.registry,
            resources=context.resources,
            aliases=context.aliases,
            anchors=context.anchors,
            embedded_local_registries=context.embedded_local_registries,
            fallback_resolver=context.resolver,
            fallback_resource_uri=context.resource_uri,
            fallback_registry=context.registry,
        )
    resolver_registry = getattr(context.resolver, "_registry", None)
    if resolver_registry is None:
        resolver_registry = context.registry
    return _ResolutionContext(
        resolver=resolver_registry.resolver(resource_uri),
        resource_uri=resource_uri,
        base_uri=resource_uri,
        document_uri=context.document_uri,
        registry=context.registry,
        resources=context.resources,
        aliases=context.aliases,
        anchors=context.anchors,
        embedded_local_registries=context.embedded_local_registries,
    )


def _enter_root_schema_resource(
    context: _ResolutionContext,
    node: Mapping[str, Any],
) -> _ResolutionContext:
    """Register a tool schema root whose ``$id`` changes the current resource.

    A tool schema is not a JSON Schema subresource of the descriptor, so the
    schema-position index registers it under its effective URI.
    """

    return _enter_schema_resource(context, node)


def _enter_tool_schema(
    context: _ResolutionContext,
    node: object,
    *,
    index: int,
    field: str,
) -> _ResolutionContext:
    """Enter a tool schema with the profile's embedded-schema fallback.

    A tool schema that declares ``$id`` follows the resource identity of that
    identifier. A schema without the keyword is also checked as a standalone
    embedded schema: local pointers and anchors resolve there first, while a
    miss falls back to the descriptor resource. The empty fragment does not use
    the fallback, so ``#`` remains the enclosing document for such a schema.
    """

    if not isinstance(node, Mapping):
        return context
    resource_uri = f"urn:ocor:embedded-tool:{index}:{field}"
    if "$id" in node:
        candidate = _resource_uri(node, context.base_uri)
        if candidate != context.base_uri:
            local_registry = context.embedded_local_registries.get(resource_uri)
            if local_registry is None:
                raise McpProfileError(
                    "MCP embedded tool schema resource is not indexed"
                )
            return _ResolutionContext(
                resolver=local_registry.resolver(candidate),
                resource_uri=candidate,
                base_uri=candidate,
                document_uri=context.document_uri,
                registry=context.registry,
                resources=context.resources,
                aliases=context.aliases,
                anchors=context.anchors,
                embedded_local_registries=context.embedded_local_registries,
            )
    if resource_uri not in context.resources:
        raise McpProfileError("MCP embedded tool schema resource is not indexed")
    local_registry = context.embedded_local_registries.get(resource_uri)
    if local_registry is None:
        raise McpProfileError("MCP embedded tool schema resource is not indexed")
    return _ResolutionContext(
        resolver=local_registry.resolver(context.base_uri),
        resource_uri=resource_uri,
        base_uri=context.base_uri,
        document_uri=context.document_uri,
        registry=context.registry,
        resources=context.resources,
        aliases=context.aliases,
        anchors=context.anchors,
        embedded_local_registries=context.embedded_local_registries,
        fallback_resolver=context.resolver,
        fallback_resource_uri=context.resource_uri,
        fallback_registry=context.registry,
    )


def _context_after_resolution(
    context: _ResolutionContext,
    resolver: Any,
) -> _ResolutionContext:
    """Keep the resolver returned by ``lookup`` and recover its resource URI.

    The resolver base of an embedded tool schema is the effective base of the
    enclosing resource, so a pointer that crosses an ``$id`` joining to that
    same base keeps the current resource and its document fallback. Only a
    base URI that actually differs starts another resource, which spends the
    fallback.
    """

    resolved_uri = getattr(resolver, "_base_uri", context.base_uri)
    if not isinstance(resolved_uri, str):
        resolved_uri = context.base_uri
    keeps_fallback = resolved_uri == context.base_uri
    return _ResolutionContext(
        resolver=resolver,
        resource_uri=context.resource_uri if keeps_fallback else resolved_uri,
        base_uri=context.base_uri if keeps_fallback else resolved_uri,
        document_uri=context.document_uri,
        registry=context.registry,
        resources=context.resources,
        aliases=context.aliases,
        anchors=context.anchors,
        embedded_local_registries=context.embedded_local_registries,
        fallback_resolver=context.fallback_resolver if keeps_fallback else None,
        fallback_resource_uri=(
            context.fallback_resource_uri if keeps_fallback else None
        ),
        fallback_registry=context.fallback_registry if keeps_fallback else None,
    )


def _resolve_reference(
    reference: object,
    context: _ResolutionContext,
) -> tuple[object, _ResolutionContext]:
    """Resolve one same-document fragment with the pinned ``referencing``."""

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
        if context.fallback_resolver is not None:
            _validate_pointer_array_indices(
                context.fallback_resolver,
                raw_tokens,
                tokens,
            )
        # ``referencing`` percent-decodes a JSON Pointer once. Re-encode the
        # already decoded fragment so a literal ``%`` is not decoded twice,
        # while the leading separator stays visible to ``Resolver.lookup``.
        library_reference = "#" + quote(decoded, safe="/~")
    else:
        library_reference = "#"

    local = _lookup_reference(context.resolver, library_reference)
    if context.fallback_resolver is None:
        if local is None:
            raise McpProfileError("MCP $ref does not resolve in the descriptor")
        target = _resolved_contents(context, local)
        _require_schema(target)
        return target, _context_after_resolution(context, local.resolver)

    fallback_uri = context.fallback_resource_uri
    if fallback_uri is None:
        raise McpProfileError("MCP $ref fallback has no resource")
    if decoded and not decoded.startswith("/"):
        _reject_ambiguous_anchor(fallback_uri, decoded, context.anchors)
    fallback = _lookup_reference(context.fallback_resolver, library_reference)
    empty_uses_fallback = decoded == "" and context.resource_uri != context.base_uri
    if empty_uses_fallback:
        if fallback is None:
            raise McpProfileError("MCP $ref does not resolve in the descriptor")
        fallback_context = _ResolutionContext(
            resolver=context.fallback_resolver,
            resource_uri=fallback_uri,
            base_uri=fallback_uri,
            document_uri=context.document_uri,
            registry=context.fallback_registry or context.registry,
            resources=context.resources,
            aliases=context.aliases,
            anchors=context.anchors,
        )
        target = _resolved_contents(context, fallback)
        _require_schema(target)
        return target, _context_after_resolution(fallback_context, fallback.resolver)
    if decoded == "":
        if local is None:
            raise McpProfileError("MCP $ref does not resolve in the descriptor")
        target = _resolved_contents(context, local)
        _require_schema(target)
        return target, _context_after_resolution(context, local.resolver)
    if local is not None and fallback is not None and local.contents is not fallback.contents:
        raise McpProfileError("MCP $ref target is ambiguous")
    if local is not None:
        target = _resolved_contents(context, local)
        _require_schema(target)
        return target, _context_after_resolution(context, local.resolver)
    if fallback is not None:
        fallback_context = _ResolutionContext(
            resolver=context.fallback_resolver,
            resource_uri=fallback_uri,
            base_uri=fallback_uri,
            document_uri=context.document_uri,
            registry=context.fallback_registry or context.registry,
            resources=context.resources,
            aliases=context.aliases,
            anchors=context.anchors,
        )
        target = _resolved_contents(context, fallback)
        _require_schema(target)
        return target, _context_after_resolution(fallback_context, fallback.resolver)
    raise McpProfileError("MCP $ref does not resolve in the descriptor")


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
def _queue_reached_schema(
    target: object,
    depth: int,
    context: _ResolutionContext,
    seen: set[int],
    deferred: dict[int, tuple[Any, int, _ResolutionContext]],
) -> None:
    """Queue a resolved schema at the next reference depth."""

    if not isinstance(target, Mapping):
        return
    identity = id(target)
    if identity in seen:
        return
    current = deferred.get(identity)
    if current is None or depth < current[1]:
        deferred[identity] = (target, depth, context)


def _check_schema_keywords(
    node: object,
    context: _ResolutionContext,
    *,
    depth: int,
    seen: set[int],
    deferred: dict[int, tuple[Any, int, _ResolutionContext]],
) -> None:
    """Apply dialect and ``$ref`` rules only to schema objects, not instance data."""

    if depth > MAX_SCHEMA_DEPTH:
        raise McpProfileError("MCP schema exceeds the revision bounds")
    if not isinstance(node, Mapping):
        return
    identity = id(node)
    if identity in seen:
        return
    seen.add(identity)
    if "$id" in node:
        _resource_uri(node, context.base_uri)
    if "$dynamicRef" in node or "$recursiveRef" in node:
        raise McpProfileError("MCP $ref resolution does not follow dynamic references")
    if "$schema" in node:
        dialect = node["$schema"]
        if not isinstance(dialect, str) or dialect not in ACCEPTED_DIALECTS:
            raise McpProfileError("MCP schema dialect must be JSON Schema 2020-12")
    if "$ref" in node:
        target, target_context = _resolve_reference(node["$ref"], context)
        _queue_reached_schema(
            target,
            depth + 1,
            target_context,
            seen,
            deferred,
        )

    def enter(child: object) -> None:
        if isinstance(child, Mapping) and id(child) in deferred:
            return
        _check_schema_keywords(
            child,
            _enter_schema_resource(context, child),
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


def _reject_surrogate(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise McpProfileError("MCP descriptor contains a lone surrogate")
