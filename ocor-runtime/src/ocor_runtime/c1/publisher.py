"""C1 -- immutable release publication.

Realises the end of the LLD v1.1 §2.1 pipeline (docs/OCOR_LLD_v1.1.md :107,
"... signature -> immutable release"): ``ReleasePublisher`` stores only packages that
admission accepts (ADD v1.3 :523); a package version, once published, never changes,
and a stored record whose bytes no longer match its content address is rejected on
read. Records are content-addressed (``urn:sha256`` of their RFC 8785 bytes).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
from pathlib import Path
from typing import Any

from ..kernel.canonical import canonical_bytes, canonical_digest, parse_i_json
from .ir import parse_core, semver_precedence
from .ports import (
    ArtifactManifestEntry,
    C1Diagnostic,
    C1Error,
    CanonicalIrRelease,
    DependencyLockEntry,
    DiagnosticCode,
)
from .signing import ReleaseAdmission, ReleasePackage, SignedRelease

RECORD_FORMAT = "ocor.c1.release-record/1.0"


def _reject(code: DiagnosticCode, path: str, message: str) -> C1Error:
    return C1Error((C1Diagnostic(code, path, message),))


def _key(package_id: str) -> str:
    return hashlib.sha256(package_id.encode("utf-8")).hexdigest()


class FileSystemReleaseStore:
    """Write-once, content-addressed store: ``objects/<sha256>.json`` and a version index."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _object(self, ref: str) -> Path:
        if re.fullmatch(r"urn:sha256:[0-9a-f]{64}", ref) is None:
            raise _reject(DiagnosticCode.RELEASE_REJECTED, "ref", "a release reference is a SHA-256 URN")
        return self._root / "objects" / f"{ref[11:]}.json"

    def _index(self, package_id: str, version: str) -> Path:
        if semver_precedence(version) is None:  # pragma: no cover - semver_precedence raises
            raise _reject(DiagnosticCode.RELEASE_REJECTED, "version", "invalid version")
        return self._root / "index" / _key(package_id) / f"{version}.ref"

    def put(self, data: bytes) -> str:
        ref = "urn:sha256:" + hashlib.sha256(data).hexdigest()
        path = self._object(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return ref
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
        return ref

    def get(self, ref: str) -> bytes:
        path = self._object(ref)
        if not path.is_file():
            raise _reject(DiagnosticCode.RELEASE_REJECTED, "ref", "no release is stored under this reference")
        data = path.read_bytes()
        if "urn:sha256:" + hashlib.sha256(data).hexdigest() != ref:
            raise _reject(DiagnosticCode.RELEASE_REJECTED, "ref", "stored release bytes do not match their address")
        return data

    def bind(self, package_id: str, version: str, ref: str) -> str:
        """Bind ``(package_id, version)`` to ``ref`` once; return the bound reference."""
        path = self._index(package_id, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="ascii") as handle:
                handle.write(ref)
        except FileExistsError:
            bound = self.lookup(package_id, version)
            if bound is None:  # pragma: no cover - the index entry exists by construction
                raise _reject(DiagnosticCode.RELEASE_REJECTED, "index", "unreadable release index") from None
            return bound
        return ref

    def lookup(self, package_id: str, version: str) -> str | None:
        path = self._index(package_id, version)
        if not path.is_file():
            return None
        return path.read_text(encoding="ascii").strip()

    def versions(self, package_id: str) -> list[str]:
        folder = self._root / "index" / _key(package_id)
        if not folder.is_dir():
            return []
        return sorted((p.name.removesuffix(".ref") for p in folder.glob("*.ref")), key=semver_precedence)


def _record(package: ReleasePackage) -> dict[str, Any]:
    release = package.signed.release
    return {
        "format": RECORD_FORMAT,
        "envelope": {k: (list(v) if isinstance(v, tuple) else v) for k, v in package.signed.envelope.items()},
        "artifact_manifest": [{"artifact_id": e.artifact_id, "media_type": e.media_type, "digest": e.digest}
                              for e in release.artifacts],
        "dependency_lock": [{"resource_id": e.resource_id, "version": e.version, "digest": e.digest}
                            for e in package.dependency_lock],
        "artifacts": {key: base64.b64encode(value).decode("ascii") for key, value in package.artifacts.items()},
    }


def _thaw(value: Any) -> Any:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(k): _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


def _package(record: Any) -> ReleasePackage:
    try:
        envelope = record["envelope"]
        core = parse_core(base64.b64decode(envelope["payload"], validate=True))
        release = CanonicalIrRelease.create(
            core=core,
            artifacts=tuple(ArtifactManifestEntry(**entry) for entry in record["artifact_manifest"]),
            signature_envelope_ref=canonical_digest(envelope),
        )
        return ReleasePackage.create(
            signed=SignedRelease(release=release, envelope=envelope),
            dependency_lock=tuple(DependencyLockEntry(**entry) for entry in record["dependency_lock"]),
            artifacts={key: base64.b64decode(value, validate=True) for key, value in record["artifacts"].items()},
        )
    except (KeyError, TypeError, binascii.Error, ValueError) as exc:
        if isinstance(exc, C1Error):
            raise
        raise _reject(DiagnosticCode.RELEASE_REJECTED, "record", "stored release record is malformed") from exc


class ImmutableReleasePublisher:
    """ReleasePublisher: admits, stores and indexes a package version exactly once."""

    def __init__(self, *, admission: ReleaseAdmission, store: FileSystemReleaseStore) -> None:
        self._admission = admission
        self._store = store

    def publish(self, package: ReleasePackage) -> str:
        receipt = self._admission.verify(package)
        existing = self._store.lookup(receipt.package_id, receipt.semantic_version)
        if existing is not None:
            stored = self.read(existing)
            if (stored.signed.release.ir_digest == receipt.ir_digest
                    and stored.signed.release.artifacts == package.signed.release.artifacts
                    and dict(stored.artifacts) == dict(package.artifacts)):
                return existing
            raise _reject(DiagnosticCode.RELEASE_REJECTED, f"{receipt.package_id}@{receipt.semantic_version}",
                          "a published release version is immutable")
        ref = self._store.put(canonical_bytes(_thaw(_record(package))))
        bound = self._store.bind(receipt.package_id, receipt.semantic_version, ref)
        if bound != ref:
            raise _reject(DiagnosticCode.RELEASE_REJECTED, f"{receipt.package_id}@{receipt.semantic_version}",
                          "a published release version is immutable")
        return ref

    def read(self, ref: str) -> ReleasePackage:
        data = self._store.get(ref)
        try:
            record = parse_i_json(data)
        except ValueError as exc:
            raise _reject(DiagnosticCode.RELEASE_REJECTED, "record", "stored release is not I-JSON") from exc
        if not isinstance(record, dict) or record.get("format") != RECORD_FORMAT or canonical_bytes(record) != data:
            raise _reject(DiagnosticCode.RELEASE_REJECTED, "record", "stored release record is not canonical")
        return _package(record)

    def verify(self, ref: str) -> Any:
        return self._admission.verify(self.read(ref))

    def latest(self, package_id: str) -> str | None:
        versions = self._store.versions(package_id)
        return self._store.lookup(package_id, versions[-1]) if versions else None
