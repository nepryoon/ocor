"""C1 -- retained parser, type-checker and semantic validation frontend.

Completes OCOR-DEV-0028's minimal C1 slice with a real grammar/type/
semantic front-end: every field must declare and satisfy a type, a
resource declaring more than one distinct execution owner is rejected
as ambiguous, and cross-resource semantic references (distinct from
``CompilerRequest``'s own external dependency-lock imports) must
resolve within the same compile unit and never form a cycle -- so
ambiguous, cyclic or invalid models can never reach generation.

This is a new, parallel, more complete implementation of the same
sealed ``OacParser``/``SemanticValidator``/``CanonicalIrBuilder``
protocols (OCOR-DEV-0011, ``ocor_runtime.c1.ports``, reused
unmodified, including the sealed ``require_resolved_references``
helper); OCOR-DEV-0028's ``RetainedOacParser``/
``RetainedCanonicalIrBuilder`` are left completely untouched, since
their content digest is pinned in their own sealed evidence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import yaml

from ..kernel.canonical import canonical_digest
from .ports import (
    ArtifactManifestEntry,
    C1Diagnostic,
    C1Error,
    CanonicalIrRelease,
    CompilerRequest,
    DiagnosticCode,
    SourceSyntax,
    SourceUnit,
    require_resolved_references,
)

REQUIRED_KEYS = frozenset({"id", "fields", "field_types"})

# A deliberately small, closed type grammar -- adding a type means
# adding it here, never accepting an unrecognized type name silently.
_SUPPORTED_TYPES: Mapping[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "list": list,
}


def _satisfies_type(value: Any, type_name: str) -> bool:
    if type_name == "integer" and isinstance(value, bool):
        return False  # bool is a subclass of int but not a real integer here
    if type_name == "number" and isinstance(value, bool):
        return False
    return isinstance(value, _SUPPORTED_TYPES[type_name])


class FrontendOacParser:
    """Parses a single ``SourceUnit``'s YAML or JSON bytes into a plain
    mapping -- byte-for-byte the same parsing behavior as OCOR-DEV-0028's
    sealed ``RetainedOacParser``; only the downstream validation is more
    complete."""

    def parse(self, source: SourceUnit) -> Mapping[str, Any]:
        try:
            if source.syntax is SourceSyntax.YAML:
                parsed = yaml.safe_load(source.content)
            else:
                parsed = json.loads(source.content)
        except (yaml.YAMLError, json.JSONDecodeError) as exc:
            raise C1Error(
                (
                    C1Diagnostic(
                        DiagnosticCode.SOURCE_INVALID,
                        source.source_path,
                        f"cannot parse {source.syntax.value}: {exc}",
                    ),
                )
            ) from exc
        if not isinstance(parsed, Mapping):
            raise C1Error(
                (C1Diagnostic(DiagnosticCode.TYPE_ERROR, source.source_path, "parsed source must be a mapping"),)
            )
        return parsed


def _find_cycle(graph: Mapping[str, Sequence[str]]) -> tuple[str, ...] | None:
    """DFS three-color cycle detection over the semantic reference graph."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(graph, WHITE)
    path: list[str] = []

    def visit(node: str) -> tuple[str, ...] | None:
        color[node] = GRAY
        path.append(node)
        for neighbor in graph.get(node, ()):
            if neighbor not in color:
                continue
            if color[neighbor] == GRAY:
                start = path.index(neighbor)
                return tuple(path[start:]) + (neighbor,)
            if color[neighbor] == WHITE:
                found = visit(neighbor)
                if found is not None:
                    return found
        path.pop()
        color[node] = BLACK
        return None

    for node in sorted(graph):
        if color[node] == WHITE:
            found = visit(node)
            if found is not None:
                return found
    return None


class FrontendTypeAndSemanticValidator:
    """Grammar, type and semantic validation completing OCOR-DEV-0028's
    minimal shape contract: every field must declare and satisfy a
    type from the closed type grammar; a resource may declare at most
    one execution owner; cross-resource semantic references must
    resolve within the same compile unit and never form a cycle.
    """

    def validate(self, request: CompilerRequest, parsed: Sequence[Mapping[str, Any]]) -> None:
        diagnostics: list[C1Diagnostic] = []
        by_id: dict[str, Mapping[str, Any]] = {}

        for source, document in zip(request.sources, parsed, strict=True):
            missing = REQUIRED_KEYS - set(document)
            if missing:
                diagnostics.append(
                    C1Diagnostic(
                        DiagnosticCode.TYPE_ERROR,
                        source.source_path,
                        f"missing required keys: {sorted(missing)}",
                    )
                )
                continue

            fields = document["fields"]
            field_types = document["field_types"]
            if not isinstance(fields, Mapping) or not isinstance(field_types, Mapping):
                diagnostics.append(
                    C1Diagnostic(
                        DiagnosticCode.TYPE_ERROR, source.source_path, "'fields' and 'field_types' must be mappings"
                    )
                )
                continue

            if document["id"] != source.resource_id:
                diagnostics.append(
                    C1Diagnostic(
                        DiagnosticCode.CONSTRAINT_ERROR,
                        source.source_path,
                        f"declared id {document['id']!r} does not match resource_id {source.resource_id!r}",
                    )
                )
                continue

            undeclared = set(fields) - set(field_types)
            if undeclared:
                diagnostics.append(
                    C1Diagnostic(
                        DiagnosticCode.TYPE_ERROR,
                        source.source_path,
                        f"fields without a declared type: {sorted(undeclared)}",
                    )
                )
                continue

            type_failed = False
            for field_name, type_name in sorted(field_types.items()):
                if type_name not in _SUPPORTED_TYPES:
                    diagnostics.append(
                        C1Diagnostic(
                            DiagnosticCode.UNSUPPORTED_CAPABILITY,
                            source.source_path,
                            f"field {field_name!r} declares unsupported type {type_name!r}",
                        )
                    )
                    type_failed = True
                    continue
                if field_name in fields and not _satisfies_type(fields[field_name], type_name):
                    diagnostics.append(
                        C1Diagnostic(
                            DiagnosticCode.TYPE_ERROR,
                            source.source_path,
                            f"field {field_name!r} does not satisfy declared type {type_name!r}",
                        )
                    )
                    type_failed = True
            if type_failed:
                continue

            owners = document.get("execution_owner")
            if owners is not None:
                if isinstance(owners, str):
                    owner_set = {owners}
                elif (
                    isinstance(owners, Sequence)
                    and not isinstance(owners, (str, bytes))
                    and all(isinstance(owner, str) for owner in owners)
                ):
                    owner_set = set(owners)
                else:
                    diagnostics.append(
                        C1Diagnostic(
                            DiagnosticCode.TYPE_ERROR,
                            source.source_path,
                            "execution_owner must be a string or a list of strings",
                        )
                    )
                    continue
                if len(owner_set) > 1:
                    diagnostics.append(
                        C1Diagnostic(
                            DiagnosticCode.MULTIPLE_EXECUTION_OWNERS,
                            source.source_path,
                            f"resource declares ambiguous execution owners: {sorted(owner_set)}",
                        )
                    )
                    continue

            references = document.get("references", [])
            if not isinstance(references, list) or not all(isinstance(ref, str) and ref for ref in references):
                diagnostics.append(
                    C1Diagnostic(
                        DiagnosticCode.TYPE_ERROR, source.source_path, "'references' must be a list of identifiers"
                    )
                )
                continue
            # LLD v1.1 :39 -- a set-like array rejects duplicates and is sorted before the digest.
            if len(references) != len(set(references)):
                diagnostics.append(
                    C1Diagnostic(
                        DiagnosticCode.DUPLICATE_RESOURCE,
                        source.source_path,
                        f"'references' contains duplicates: {sorted(references)}",
                    )
                )
                continue

            by_id[source.resource_id] = document

        if diagnostics:
            raise C1Error(tuple(diagnostics))

        # Semantic cross-resource references, distinct from
        # CompilerRequest's own external dependency-lock import
        # resolution: every reference named in a resource's own
        # "references" list must resolve to another resource compiled
        # in THIS SAME request.
        # require_resolved_references' own sealed _unique_strings helper
        # rejects duplicate entries in "referenced" -- but a shared target
        # referenced by more than one resource (a diamond reference graph)
        # is legitimate, so only the distinct set of referenced targets is
        # checked for resolution, never how many times each is referenced.
        defined = list(by_id)
        referenced = sorted({ref for document in by_id.values() for ref in document.get("references", [])})
        require_resolved_references(defined=defined, referenced=referenced)

        cycle = _find_cycle({resource_id: document.get("references", []) for resource_id, document in by_id.items()})
        if cycle is not None:
            raise C1Error(
                (C1Diagnostic(DiagnosticCode.CONSTRAINT_ERROR, cycle[0], f"cyclic reference: {' -> '.join(cycle)}"),)
            )


class FrontendCanonicalIrBuilder:
    """Assembles the canonical IR release exactly like OCOR-DEV-0028's
    sealed builder, additionally carrying the validated
    field_types/references/execution_owner metadata into each
    resource's core entry."""

    def __init__(
        self,
        parser: FrontendOacParser | None = None,
        validator: FrontendTypeAndSemanticValidator | None = None,
    ) -> None:
        self._parser = parser or FrontendOacParser()
        self._validator = validator or FrontendTypeAndSemanticValidator()

    def build(self, request: CompilerRequest) -> CanonicalIrRelease:
        parsed = [self._parser.parse(source) for source in request.sources]
        self._validator.validate(request, parsed)

        resources = {
            source.resource_id: {
                "version": source.version,
                "content_digest": source.content_digest,
                "fields": document["fields"],
                "field_types": document["field_types"],
                "references": sorted(document.get("references", ())),
                "execution_owner": document.get("execution_owner"),
            }
            for source, document in zip(request.sources, parsed, strict=True)
        }
        core = {
            "package_id": request.package_id,
            "semantic_version": request.semantic_version,
            "source_commit": request.source_commit,
            "compiler_version": request.compiler_version,
            "mapping_version": request.mapping_version,
            "release_profile": request.release_profile,
            "resources": resources,
        }

        migration_metadata = {
            "package_id": request.package_id,
            "semantic_version": request.semantic_version,
            "resource_identity": sorted(
                (
                    {"resource_id": source.resource_id, "version": source.version}
                    for source in request.sources
                ),
                key=lambda item: (item["resource_id"], item["version"]),
            ),
        }
        migration_artifact = ArtifactManifestEntry(
            artifact_id=f"{request.package_id}:migration-metadata",
            media_type="application/vnd.ocor.migration-metadata+json",
            digest=canonical_digest(migration_metadata),
        )

        core_digest = canonical_digest(core)
        return CanonicalIrRelease.create(
            core=core,
            artifacts=(migration_artifact,),
            signature_envelope_ref=f"urn:ocor:unsigned:{core_digest}",
        )
