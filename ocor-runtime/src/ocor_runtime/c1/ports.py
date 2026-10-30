"""Typed, deterministic ports for the C1 Ontology Compiler and IR pipeline."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from ..kernel.canonical import canonical_bytes, canonical_digest

DIGEST = re.compile(r"urn:sha256:[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
# SemVer 2.0.0 (https://semver.org), the OntologyPackage version of ADD v1.3 :419.
SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)


class SourceSyntax(StrEnum):
    YAML = "YAML"
    JSON = "JSON"


class DiagnosticCode(StrEnum):
    SOURCE_INVALID = "SOURCE_INVALID"
    UNKNOWN_SYNTAX = "UNKNOWN_SYNTAX"
    LOCK_INVALID = "LOCK_INVALID"
    DUPLICATE_RESOURCE = "DUPLICATE_RESOURCE"
    UNRESOLVED_REFERENCE = "UNRESOLVED_REFERENCE"
    TYPE_ERROR = "TYPE_ERROR"
    CONSTRAINT_ERROR = "CONSTRAINT_ERROR"
    MULTIPLE_EXECUTION_OWNERS = "MULTIPLE_EXECUTION_OWNERS"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    NON_DETERMINISTIC_OUTPUT = "NON_DETERMINISTIC_OUTPUT"
    ARTIFACT_DRIFT = "ARTIFACT_DRIFT"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    RELEASE_REJECTED = "RELEASE_REJECTED"


@dataclass(frozen=True, slots=True, order=True)
class C1Diagnostic:
    code: DiagnosticCode
    path: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", DiagnosticCode(self.code))
        if not isinstance(self.path, str) or not self.path:
            raise ValueError("diagnostic path is required")
        if not isinstance(self.message, str) or not self.message or len(self.message) > 512:
            raise ValueError("diagnostic message must be bounded and non-empty")

    def to_mapping(self) -> dict[str, str]:
        return {"code": self.code.value, "path": self.path, "message": self.message}


class C1Error(ValueError):
    """Deterministic, bounded compiler rejection."""

    def __init__(self, diagnostics: Sequence[C1Diagnostic]) -> None:
        ordered = tuple(sorted(diagnostics, key=lambda item: (item.path, item.code.value, item.message)))
        if not ordered:
            raise ValueError("at least one compiler diagnostic is required")
        self.diagnostics = ordered
        super().__init__("; ".join(f"{item.code.value}@{item.path}: {item.message}" for item in ordered))

    def to_result(self) -> dict[str, object]:
        return {
            "status": "RELEASE_REJECTED",
            "diagnostics": [item.to_mapping() for item in self.diagnostics],
        }


def _reject(code: DiagnosticCode, path: str, message: str) -> C1Error:
    return C1Error((C1Diagnostic(code, path, message),))


def _required(field: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _reject(DiagnosticCode.SOURCE_INVALID, field, f"{field} is required")
    return value


def _digest(field: str, value: object, code: DiagnosticCode) -> str:
    result = _required(field, value)
    if DIGEST.fullmatch(result) is None:
        raise _reject(code, field, f"{field} must be a canonical SHA-256 URN")
    return result


def _unique_strings(field: str, values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise _reject(DiagnosticCode.SOURCE_INVALID, field, f"{field} must be an array")
    result = tuple(values)
    if any(not isinstance(item, str) or not item for item in result):
        raise _reject(DiagnosticCode.SOURCE_INVALID, field, f"{field} contains an invalid value")
    if len(result) != len(set(result)):
        raise _reject(DiagnosticCode.DUPLICATE_RESOURCE, field, f"{field} contains duplicates")
    return result


@dataclass(frozen=True, slots=True)
class SourceUnit:
    resource_id: str
    version: str
    syntax: SourceSyntax
    content: bytes
    content_digest: str
    source_path: str
    imports: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        resource_id: str,
        version: str,
        syntax: SourceSyntax | str,
        content: bytes,
        source_path: str,
        imports: Sequence[str] = (),
    ) -> SourceUnit:
        try:
            parsed_syntax = SourceSyntax(syntax)
        except (TypeError, ValueError) as exc:
            raise _reject(
                DiagnosticCode.UNKNOWN_SYNTAX,
                source_path or "$",
                f"unknown source syntax: {syntax}",
            ) from exc
        if not isinstance(content, bytes) or not content:
            raise _reject(DiagnosticCode.SOURCE_INVALID, source_path or "$", "source is empty")
        return cls(
            resource_id=_required("resource_id", resource_id),
            version=_required("version", version),
            syntax=parsed_syntax,
            content=bytes(content),
            content_digest=canonical_digest({"bytes_hex": content.hex()}),
            source_path=_required("source_path", source_path),
            imports=_unique_strings("imports", imports),
        )


@dataclass(frozen=True, slots=True)
class DependencyLockEntry:
    resource_id: str
    version: str
    digest: str

    def __post_init__(self) -> None:
        _required("resource_id", self.resource_id)
        _required("version", self.version)
        _digest("digest", self.digest, DiagnosticCode.LOCK_INVALID)


@dataclass(frozen=True, slots=True)
class CompilerRequest:
    package_id: str
    semantic_version: str
    source_commit: str
    compiler_version: str
    mapping_version: str
    release_profile: str
    sources: tuple[SourceUnit, ...]
    dependency_lock: tuple[DependencyLockEntry, ...]

    def __post_init__(self) -> None:
        for field in (
            "package_id",
            "semantic_version",
            "compiler_version",
            "mapping_version",
            "release_profile",
        ):
            _required(field, getattr(self, field))
        if SEMVER.fullmatch(self.semantic_version) is None:
            raise _reject(
                DiagnosticCode.SOURCE_INVALID,
                "semantic_version",
                "semantic_version must be a SemVer 2.0.0 version (ADD v1.3 :419)",
            )
        if COMMIT.fullmatch(self.source_commit) is None:
            raise _reject(
                DiagnosticCode.SOURCE_INVALID,
                "source_commit",
                "source_commit must be an exact lowercase Git SHA-1",
            )
        sources = tuple(self.sources)
        locks = tuple(self.dependency_lock)
        if not sources:
            raise _reject(DiagnosticCode.SOURCE_INVALID, "sources", "at least one source is required")
        source_keys = [(item.resource_id, item.version) for item in sources]
        if len(source_keys) != len(set(source_keys)):
            raise _reject(
                DiagnosticCode.DUPLICATE_RESOURCE,
                "sources",
                "source resource/version identity is duplicated",
            )
        lock_keys = [(item.resource_id, item.version) for item in locks]
        if len(lock_keys) != len(set(lock_keys)):
            raise _reject(
                DiagnosticCode.DUPLICATE_RESOURCE,
                "dependency_lock",
                "lock resource/version identity is duplicated",
            )
        locked_ids = {item.resource_id for item in locks}
        unresolved = sorted({ref for source in sources for ref in source.imports} - locked_ids)
        if unresolved:
            raise C1Error(
                tuple(
                    C1Diagnostic(
                        DiagnosticCode.UNRESOLVED_REFERENCE,
                        reference,
                        "import is absent from dependency lock",
                    )
                    for reference in unresolved
                )
            )
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "dependency_lock", locks)


@dataclass(frozen=True, slots=True)
class ArtifactManifestEntry:
    artifact_id: str
    media_type: str
    digest: str

    def __post_init__(self) -> None:
        _required("artifact_id", self.artifact_id)
        _required("media_type", self.media_type)
        _digest("digest", self.digest, DiagnosticCode.ARTIFACT_DRIFT)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    if isinstance(value, tuple):
        return tuple(_freeze(child) for child in value)
    return copy.deepcopy(value)


@dataclass(frozen=True, slots=True)
class CanonicalIrRelease:
    core: Mapping[str, Any]
    canonical_bytes: bytes
    ir_digest: str
    artifacts: tuple[ArtifactManifestEntry, ...]
    signature_envelope_ref: str

    @classmethod
    def create(
        cls,
        *,
        core: Mapping[str, Any],
        artifacts: Sequence[ArtifactManifestEntry],
        signature_envelope_ref: str,
    ) -> CanonicalIrRelease:
        if not isinstance(core, Mapping) or not core:
            raise _reject(DiagnosticCode.RELEASE_REJECTED, "core", "Canonical IR core is empty")
        stable_core = copy.deepcopy(dict(core))
        encoded = canonical_bytes(stable_core)
        manifest = tuple(artifacts)
        artifact_ids = [item.artifact_id for item in manifest]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise _reject(
                DiagnosticCode.DUPLICATE_RESOURCE,
                "artifacts",
                "artifact identifier is duplicated",
            )
        return cls(
            core=_freeze(stable_core),
            canonical_bytes=encoded,
            ir_digest=canonical_digest(stable_core),
            artifacts=manifest,
            signature_envelope_ref=_required("signature_envelope_ref", signature_envelope_ref),
        )


def require_resolved_references(
    *, defined: Sequence[str], referenced: Sequence[str]
) -> None:
    defined_set = set(_unique_strings("defined", defined))
    referenced_set = set(_unique_strings("referenced", referenced))
    unresolved = sorted(referenced_set - defined_set)
    if unresolved:
        raise C1Error(
            tuple(
                C1Diagnostic(
                    DiagnosticCode.UNRESOLVED_REFERENCE,
                    reference,
                    "reference does not resolve in the canonical symbol table",
                )
                for reference in unresolved
            )
        )


@runtime_checkable
class OacParser(Protocol):
    def parse(self, source: SourceUnit) -> Mapping[str, Any]: ...


@runtime_checkable
class SemanticValidator(Protocol):
    def validate(self, request: CompilerRequest, parsed: Sequence[Mapping[str, Any]]) -> None: ...


@runtime_checkable
class CanonicalIrBuilder(Protocol):
    def build(self, request: CompilerRequest) -> CanonicalIrRelease: ...


@runtime_checkable
class IrSigner(Protocol):
    def sign(self, release: CanonicalIrRelease) -> str: ...


@runtime_checkable
class ReleasePublisher(Protocol):
    def publish(self, release: CanonicalIrRelease) -> str: ...


@runtime_checkable
class SemanticDiffEngine(Protocol):
    def compare(self, previous: CanonicalIrRelease, candidate: CanonicalIrRelease) -> str: ...


@runtime_checkable
class MigrationPlanner(Protocol):
    def plan(self, previous: CanonicalIrRelease, candidate: CanonicalIrRelease) -> Mapping[str, Any]: ...


@runtime_checkable
class ArtifactGenerator(Protocol):
    def generate(self, release: CanonicalIrRelease) -> Sequence[ArtifactManifestEntry]: ...


@runtime_checkable
class CompatibilityChecker(Protocol):
    def check(self, previous: CanonicalIrRelease, candidate: CanonicalIrRelease) -> str: ...


@runtime_checkable
class ConformanceSuitePort(Protocol):
    def run(self, release: CanonicalIrRelease) -> Mapping[str, object]: ...


def verify_deterministic_build(
    builder: CanonicalIrBuilder, request: CompilerRequest
) -> CanonicalIrRelease:
    first = builder.build(request)
    second = builder.build(request)
    if (
        first.ir_digest != second.ir_digest
        or first.canonical_bytes != second.canonical_bytes
        or first.artifacts != second.artifacts
    ):
        raise _reject(
            DiagnosticCode.NON_DETERMINISTIC_OUTPUT,
            request.package_id,
            "repeated compilation produced different canonical output",
        )
    return first
