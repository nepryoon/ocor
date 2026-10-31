"""C1 -- the Ontology Compiler service: the five C1 operations of ADD v1.3 :282.

``ValidatePackage``, ``Compile``, ``SemanticDiff``, ``PackageRelease`` and
``VerifyRelease`` compose the LLD v1.1 §2.1 pipeline (docs/OCOR_LLD_v1.1.md :107):
parse -> schema validation -> semantic validation -> build Canonical IR -> RFC 8785
digest -> generators -> signature -> admission -> immutable release. A new version
of a published package passes the release change gate (FR-045, LLD :107) against
the latest published version.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .codegen import IrArtifactGenerator
from .conformance import IrConformanceSuite
from .ir import OacCompiler
from .migration import IrMigrationPlanner, IrSemanticDiffEngine, ReleaseChangeGate
from .ports import (
    C1Diagnostic,
    C1Error,
    CanonicalIrRelease,
    CompilerRequest,
    DiagnosticCode,
    verify_deterministic_build,
)
from .publisher import ImmutableReleasePublisher
from .signing import AdmissionReceipt, DsseIrSigner, ReleaseAdmission, ReleasePackage


class OntologyCompilerService:
    def __init__(self, *, compiler: OacCompiler, generator: IrArtifactGenerator, signer: DsseIrSigner,
                 admission: ReleaseAdmission, publisher: ImmutableReleasePublisher, conformance: IrConformanceSuite,
                 diff_engine: IrSemanticDiffEngine, planner: IrMigrationPlanner, gate: ReleaseChangeGate) -> None:
        self._compiler = compiler
        self._generator = generator
        self._signer = signer
        self._admission = admission
        self._publisher = publisher
        self._conformance = conformance
        self._diff = diff_engine
        self._planner = planner
        self._gate = gate

    def validate_package(self, request: CompilerRequest) -> tuple[C1Diagnostic, ...]:
        """ValidatePackage: every diagnostic, localised; empty when the package is valid."""
        return self._compiler.validate(request)

    def compile(self, request: CompilerRequest) -> CanonicalIrRelease:
        """Compile: deterministic Canonical IR that passes the conformance suite."""
        release = verify_deterministic_build(self._compiler, request)
        report = self._conformance.run(release)
        if report["status"] != "PASS":
            raise C1Error((C1Diagnostic(DiagnosticCode.RELEASE_REJECTED, request.package_id,
                                        "the compiled IR fails the conformance suite"),))
        return release

    def semantic_diff(self, previous: CanonicalIrRelease, candidate: CanonicalIrRelease) -> dict[str, Any]:
        """SemanticDiff: classification, classified changes and the content-addressed plan."""
        return self._planner.plan(previous, candidate) | {"diff_digest": self._diff.compare(previous, candidate)}

    def package_release(self, request: CompilerRequest, *, plan: Mapping[str, Any] | None = None,
                        approvals: Sequence[str] = ()) -> str:
        """PackageRelease: compile, generate, sign, admit and publish; returns the release reference."""
        release = self.compile(request)
        files = self._generator.render(release)
        release = release.with_artifacts(self._generator.generate(release))
        latest = self._publisher.latest(request.package_id)
        if latest is not None:
            previous = self._publisher.read(latest).signed.release
            published = previous.core["release"]["semantic_version"]
            if published != request.semantic_version:
                self._gate.admit(previous, release, plan=plan, approvals=approvals)
        package = ReleasePackage.create(signed=self._signer.sign_release(release),
                                        dependency_lock=request.dependency_lock, artifacts=files)
        return self._publisher.publish(package)

    def verify_release(self, ref: str) -> AdmissionReceipt:
        """VerifyRelease: re-admit a stored release from its bytes."""
        result: AdmissionReceipt = self._publisher.verify(ref)
        return result
