"""Retained C1 compiler slice.

Implements the smallest contract-compliant slice of the sealed C1 ports
(OCOR-DEV-0011, ``ocor_runtime.c1.ports``, reused unmodified): a real
YAML/JSON parser, a semantic validator enforcing the DSL's own minimal
shape contract, and a canonical IR builder that assembles one
deterministic core document plus a migration-metadata artifact
summarizing the release's resource/version identity for a future
``MigrationPlanner`` to diff against.

Pre-normative candidate, not releasable (NCP-U01-RETAINED-C1-BUILDERS,
2026-11-01): its output is unsigned and its core is not ``ocor.cir/1.0``,
so ``signing.DsseIrSigner``, ``signing.ReleaseAdmission`` and
``publisher.ImmutableReleasePublisher`` reject it. A signed, admitted and
published C1 release comes only from the conforming pipeline (``oac``,
``ir``, ``signing``, ``codegen``, ``migration``, ``publisher``). Kept
unchanged until NORMATIVE-CONFORMANCE-LEGACY-RETIREMENT.
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
)

REQUIRED_KEYS = frozenset({"id", "fields"})


class RetainedOacParser:
    """Parses a single ``SourceUnit``'s YAML or JSON bytes into a plain,
    real mapping -- no placeholder or synthetic parsing shortcut."""

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


class RetainedSemanticValidator:
    """Enforces the DSL's minimal shape contract: every parsed document
    must declare ``id`` (matching its own ``SourceUnit.resource_id``) and
    a ``fields`` mapping. Cross-source import resolution is already
    enforced by the sealed ``CompilerRequest`` constructor; this validator
    only checks what that constructor cannot see -- the parsed content
    itself."""

    def validate(self, request: CompilerRequest, parsed: Sequence[Mapping[str, Any]]) -> None:
        diagnostics: list[C1Diagnostic] = []
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
            if not isinstance(document["fields"], Mapping):
                diagnostics.append(
                    C1Diagnostic(DiagnosticCode.TYPE_ERROR, source.source_path, "'fields' must be a mapping")
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
        if diagnostics:
            raise C1Error(tuple(diagnostics))


class RetainedCanonicalIrBuilder:
    """Assembles a deterministic canonical IR release: one core document
    keyed by resource_id, plus a migration-metadata artifact.

    Pre-normative candidate, not releasable: admission and the publisher
    reject its output (NCP-U01-RETAINED-C1-BUILDERS, 2026-11-01).
    """

    def __init__(
        self,
        parser: RetainedOacParser | None = None,
        validator: RetainedSemanticValidator | None = None,
    ) -> None:
        self._parser = parser or RetainedOacParser()
        self._validator = validator or RetainedSemanticValidator()

    def build(self, request: CompilerRequest) -> CanonicalIrRelease:
        parsed = [self._parser.parse(source) for source in request.sources]
        self._validator.validate(request, parsed)

        resources = {
            source.resource_id: {
                "version": source.version,
                "content_digest": source.content_digest,
                "fields": document["fields"],
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
