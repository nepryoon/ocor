"""C1 -- retained releases: semantic diff, compatibility, migration and
artifact generation.

Completes the remaining sealed C1 ports (OCOR-DEV-0011,
``ocor_runtime.c1.ports``, reused unmodified): ``SemanticDiffEngine``,
``CompatibilityChecker``, ``MigrationPlanner`` and ``ArtifactGenerator``.
Every output this module produces -- the diff digest, the migration
plan and the generated artifacts -- is content-addressed; a candidate
release classified ``BREAKING`` against its predecessor can never
reach artifact generation without an explicit, non-empty governed
migration plan.

Pre-normative candidate, not releasable (NCP-U01-RETAINED-C1-BUILDERS,
2026-11-01): its output is unsigned and its core is not ``ocor.cir/1.0``,
so ``signing.DsseIrSigner``, ``signing.ReleaseAdmission`` and
``publisher.ImmutableReleasePublisher`` reject it. A signed, admitted and
published C1 release comes only from the conforming pipeline (``oac``,
``ir``, ``signing``, ``codegen``, ``migration``, ``publisher``). Kept
unchanged until NORMATIVE-CONFORMANCE-LEGACY-RETIREMENT.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..kernel.canonical import canonical_digest
from .ports import (
    ArtifactManifestEntry,
    C1Diagnostic,
    C1Error,
    CanonicalIrRelease,
    DiagnosticCode,
)

IDENTICAL = "IDENTICAL"
COMPATIBLE = "COMPATIBLE"
BREAKING = "BREAKING"


def _resources(release: CanonicalIrRelease) -> Mapping[str, Any]:
    resources = release.core.get("resources", {})
    if not isinstance(resources, Mapping):
        return {}
    return resources


def _structural_diff(previous: CanonicalIrRelease, candidate: CanonicalIrRelease) -> dict[str, list[str]]:
    before = _resources(previous)
    after = _resources(candidate)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(
        resource_id
        for resource_id in sorted(set(before) & set(after))
        if before[resource_id] != after[resource_id]
    )
    return {"added": added, "removed": removed, "changed": changed}


class RetainedSemanticDiffEngine:
    """Computes a deterministic, content-addressed structural diff
    digest between two canonical IR releases: which resources were
    added, removed or changed."""

    def compare(self, previous: CanonicalIrRelease, candidate: CanonicalIrRelease) -> str:
        return canonical_digest(_structural_diff(previous, candidate))


class RetainedCompatibilityChecker:
    """Classifies a candidate release against its predecessor.

    A resource removal, a field's type declaration being removed, or
    an existing field's declared type changing are all BREAKING; a
    pure addition (a new resource, or a new field with a type on an
    existing resource) is COMPATIBLE; no difference at all is
    IDENTICAL.
    """

    def check(self, previous: CanonicalIrRelease, candidate: CanonicalIrRelease) -> str:
        before = _resources(previous)
        after = _resources(candidate)
        if before == after:
            return IDENTICAL
        if set(before) - set(after):
            return BREAKING
        for resource_id, before_resource in before.items():
            after_resource = after[resource_id]
            before_types = dict(before_resource.get("field_types", {}))
            after_types = dict(after_resource.get("field_types", {}))
            if set(before_types) - set(after_types):
                return BREAKING
            for field_name, before_type in before_types.items():
                if after_types.get(field_name) != before_type:
                    return BREAKING
        return COMPATIBLE


class RetainedMigrationPlanner:
    """Builds a content-addressed migration plan describing exactly
    what changed between two releases and the ordered steps required
    to migrate; every plan carries its own ``plan_digest``, computed
    over the plan body itself."""

    def __init__(
        self,
        diff_engine: RetainedSemanticDiffEngine | None = None,
        checker: RetainedCompatibilityChecker | None = None,
    ) -> None:
        self._diff_engine = diff_engine or RetainedSemanticDiffEngine()
        self._checker = checker or RetainedCompatibilityChecker()

    def plan(self, previous: CanonicalIrRelease, candidate: CanonicalIrRelease) -> Mapping[str, Any]:
        diff = _structural_diff(previous, candidate)
        migration_steps: list[dict[str, str]] = []
        for resource_id in diff["removed"]:
            migration_steps.append({"op": "retire", "resource_id": resource_id})
        for resource_id in diff["changed"]:
            migration_steps.append({"op": "expand-migrate-contract", "resource_id": resource_id})
        for resource_id in diff["added"]:
            migration_steps.append({"op": "introduce", "resource_id": resource_id})

        body = {
            "previous_ir_digest": previous.ir_digest,
            "candidate_ir_digest": candidate.ir_digest,
            "diff_digest": self._diff_engine.compare(previous, candidate),
            "classification": self._checker.check(previous, candidate),
            "migration_steps": migration_steps,
        }
        return {**body, "plan_digest": canonical_digest(body)}


class RetainedArtifactGenerator:
    """Generates a content-addressed release-manifest artifact
    enumerating every resource's identity and digest.

    ``generate`` alone (the sealed ``ArtifactGenerator`` Protocol
    method) never inspects compatibility -- ``generate_governed`` is
    the executable form of this task's negative acceptance criterion:
    a BREAKING candidate can never reach generation without an
    explicit, non-empty governed migration plan.
    """

    def __init__(self, checker: RetainedCompatibilityChecker | None = None) -> None:
        self._checker = checker or RetainedCompatibilityChecker()

    def generate(self, release: CanonicalIrRelease) -> Sequence[ArtifactManifestEntry]:
        resources = _resources(release)
        manifest_body = {
            "resources": sorted(
                (
                    {
                        "resource_id": resource_id,
                        "version": resource["version"],
                        "content_digest": resource["content_digest"],
                    }
                    for resource_id, resource in resources.items()
                ),
                key=lambda item: (item["resource_id"], item["version"]),
            )
        }
        package_id = release.core.get("package_id", "urn:ocor:package:unknown")
        return (
            ArtifactManifestEntry(
                artifact_id=f"{package_id}:release-manifest",
                media_type="application/vnd.ocor.release-manifest+json",
                digest=canonical_digest(manifest_body),
            ),
        )

    def generate_governed(
        self,
        previous: CanonicalIrRelease,
        candidate: CanonicalIrRelease,
        migration_plan: Mapping[str, Any] | None,
    ) -> Sequence[ArtifactManifestEntry]:
        classification = self._checker.check(previous, candidate)
        if classification == BREAKING and not (migration_plan and migration_plan.get("migration_steps")):
            raise C1Error(
                (
                    C1Diagnostic(
                        DiagnosticCode.RELEASE_REJECTED,
                        str(candidate.core.get("package_id", "$")),
                        "a BREAKING change cannot reach generation without a governed migration plan",
                    ),
                )
            )
        return self.generate(candidate)
