"""C1 -- signed Canonical IR: DSSE envelope, Ed25519 signer and release admission.

Realises ADD v1.3 §3.1.2 (OCOR_ADD_v1.3_APPROVED_BASELINE.md): the
``signed-canonical-ir:1.0`` DSSE envelope (:466-521) over the RFC 8785 bytes of the
CanonicalIRCore, and admission (:523), which verifies trust root, revocation, DSSE
PAE, digest, lock, compiler and artifact manifest before activation (NFR-021,
NFR-051). The algorithm comes from the signing profile of the trusted key, not from
the IR (:523, OI-022): ``ED25519_PROFILE`` is the profile this module implements.

Ed25519 is RFC 8032 §5.1, written with integer arithmetic of the standard library;
it is not constant-time, which is acceptable for verification and for a signer whose
key never leaves the release environment.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import hashlib
import hmac
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

import jsonschema

from ..kernel.canonical import canonical_bytes, canonical_digest, format_utc_timestamp
from .ir import parse_core
from .ports import (
    ArtifactManifestEntry,
    C1Diagnostic,
    C1Error,
    CanonicalIrRelease,
    DependencyLockEntry,
    DiagnosticCode,
)

PAYLOAD_TYPE = "application/vnd.ocor.canonical-ir.v1+json"
ED25519_PROFILE = "urn:ocor:crypto-profile:ed25519-dsse:1"
UNSIGNED_PREFIX = "urn:ocor:unsigned:"
# The schema of ADD v1.3 :466-521, verbatim.
SIGNED_CANONICAL_IR_SCHEMA: Mapping[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:ocor:schema:signed-canonical-ir:1.0",
    "type": "object",
    "additionalProperties": False,
    "required": ["payloadType", "payload", "canonicalization", "digest", "signingProfile", "signatures"],
    "properties": {
        "payloadType": {"const": PAYLOAD_TYPE},
        "payload": {"type": "string", "contentEncoding": "base64"},
        "canonicalization": {"const": "RFC8785"},
        "digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "signingProfile": {"type": "string", "pattern": "^urn:ocor:crypto-profile:[A-Za-z0-9._-]+:[0-9]+$"},
        "signatures": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["keyid", "sig", "certificateChainRef", "signedAt"],
                "properties": {
                    "keyid": {"type": "string", "minLength": 1, "maxLength": 256},
                    "sig": {"type": "string", "contentEncoding": "base64"},
                    "certificateChainRef": {"type": "string", "pattern": "^urn:sha256:[0-9a-f]{64}$"},
                    "signedAt": {"type": "string", "format": "date-time"},
                },
            },
        },
    },
}
_ENVELOPE_VALIDATOR = jsonschema.Draft202012Validator(
    SIGNED_CANONICAL_IR_SCHEMA, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
)


def _reject(code: DiagnosticCode, path: str, message: str) -> C1Error:
    return C1Error((C1Diagnostic(code, path, message),))


# ------------------------------------------------------------------------------------
# Ed25519 (RFC 8032 §5.1)
# ------------------------------------------------------------------------------------
_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)
_Point = tuple[int, int, int, int]


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * pow(5, _P - 2, _P) % _P
_GX = _recover_x(_GY, 0) or 0
_G: _Point = (_GX, _GY, 1, _GX * _GY % _P)
_IDENTITY: _Point = (0, 1, 1, 0)


def _add(p: _Point, q: _Point) -> _Point:
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _multiply(scalar: int, point: _Point) -> _Point:
    result = _IDENTITY
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _equal(p: _Point, q: _Point) -> bool:
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _compress(point: _Point) -> bytes:
    inverse = pow(point[2], _P - 2, _P)
    x, y = point[0] * inverse % _P, point[1] * inverse % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(data: bytes) -> _Point | None:
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _sha512_int(*parts: bytes) -> int:
    return int.from_bytes(hashlib.sha512(b"".join(parts)).digest(), "little")


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 §5.1.7 verification (cofactorless equation, canonical S required)."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a_point = _decompress(public_key)
    r_point = _decompress(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if a_point is None or r_point is None or s >= _L:
        return False
    h = _sha512_int(signature[:32], public_key, message) % _L
    return _equal(_multiply(s, _G), _add(r_point, _multiply(h, a_point)))


@dataclass(frozen=True, slots=True)
class Ed25519SigningKey:
    seed: bytes = dataclasses.field(repr=False)
    public_key: bytes

    @classmethod
    def from_seed(cls, seed: bytes) -> Ed25519SigningKey:
        if not isinstance(seed, bytes) or len(seed) != 32:
            raise ValueError("an Ed25519 seed is 32 bytes")
        digest = hashlib.sha512(seed).digest()
        scalar = int.from_bytes(digest[:32], "little")
        scalar &= (1 << 254) - 8
        scalar |= 1 << 254
        return cls(seed=bytes(seed), public_key=_compress(_multiply(scalar, _G)))

    def sign(self, message: bytes) -> bytes:
        digest = hashlib.sha512(self.seed).digest()
        scalar = int.from_bytes(digest[:32], "little")
        scalar &= (1 << 254) - 8
        scalar |= 1 << 254
        r = _sha512_int(digest[32:], message) % _L
        r_encoded = _compress(_multiply(r, _G))
        h = _sha512_int(r_encoded, self.public_key, message) % _L
        s = (r + h * scalar) % _L
        return r_encoded + int.to_bytes(s, 32, "little")


def dsse_pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE v1 Pre-Authentication Encoding: ``DSSEv1 SP LEN(type) SP type SP LEN(body) SP body``."""
    encoded = payload_type.encode("utf-8")
    return b"DSSEv1 %d %s %d %s" % (len(encoded), encoded, len(payload), payload)


# ------------------------------------------------------------------------------------
# Signed release and release package
# ------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SignedRelease:
    """A Canonical IR release and the DSSE envelope its ``signature_envelope_ref`` names."""

    release: CanonicalIrRelease
    envelope: Mapping[str, Any]

    def __post_init__(self) -> None:
        # A private deep copy: the envelope is plain JSON data, never shared.
        object.__setattr__(self, "envelope", _thaw(self.envelope))


def _frozen_bytes(artifacts: Mapping[str, bytes]) -> Mapping[str, bytes]:
    out: dict[str, bytes] = {}
    for key, value in artifacts.items():
        if not isinstance(key, str) or not isinstance(value, bytes):
            raise _reject(DiagnosticCode.ARTIFACT_DRIFT, "artifacts", "artefacts map identifiers to bytes")
        out[key] = bytes(value)
    return MappingProxyType(dict(sorted(out.items())))


@dataclass(frozen=True, slots=True)
class ReleasePackage:
    """What admission verifies: signed release, resolved lock and artefact bytes."""

    signed: SignedRelease
    dependency_lock: tuple[DependencyLockEntry, ...]
    artifacts: Mapping[str, bytes]

    @classmethod
    def create(cls, *, signed: SignedRelease, dependency_lock: Sequence[DependencyLockEntry],
               artifacts: Mapping[str, bytes]) -> ReleasePackage:
        return cls(signed=signed, dependency_lock=tuple(dependency_lock), artifacts=_frozen_bytes(artifacts))


class DsseIrSigner:
    """IrSigner: signs the RFC 8785 core bytes in a ``signed-canonical-ir:1.0`` envelope."""

    def __init__(self, *, key: Ed25519SigningKey, keyid: str, certificate_chain_ref: str,
                 clock: Callable[[], datetime] | None = None, signing_profile: str = ED25519_PROFILE) -> None:
        if signing_profile != ED25519_PROFILE:
            raise _reject(DiagnosticCode.SIGNATURE_INVALID, "signing_profile", "unsupported signing profile")
        self._key = key
        self._keyid = keyid
        self._chain = certificate_chain_ref
        self._clock = clock or (lambda: datetime.now(UTC))
        self._profile = signing_profile

    def sign_release(self, release: CanonicalIrRelease) -> SignedRelease:
        payload = release.canonical_bytes
        if canonical_bytes(parse_core(payload)) != payload or canonical_digest(parse_core(payload)) != release.ir_digest:
            raise _reject(DiagnosticCode.SIGNATURE_INVALID, "core", "release bytes do not bind its ir_digest")
        signature = self._key.sign(dsse_pae(PAYLOAD_TYPE, payload))
        envelope = {
            "payloadType": PAYLOAD_TYPE,
            "payload": base64.b64encode(payload).decode("ascii"),
            "canonicalization": "RFC8785",
            "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "signingProfile": self._profile,
            "signatures": [{
                "keyid": self._keyid,
                "sig": base64.b64encode(signature).decode("ascii"),
                "certificateChainRef": self._chain,
                "signedAt": format_utc_timestamp(self._clock()),
            }],
        }
        _ENVELOPE_VALIDATOR.validate(envelope)
        signed = dataclasses.replace(release, signature_envelope_ref=canonical_digest(envelope))
        return SignedRelease(release=signed, envelope=envelope)

    def sign(self, release: CanonicalIrRelease) -> str:
        return self.sign_release(release).release.signature_envelope_ref


# ------------------------------------------------------------------------------------
# Admission (VerifyRelease)
# ------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TrustedKey:
    public_key: bytes
    certificate_chain_ref: str
    signing_profile: str


@dataclass(frozen=True, slots=True)
class TrustRoot:
    keys: Mapping[str, TrustedKey]
    revoked_keyids: frozenset[str]


@dataclass(frozen=True, slots=True)
class AdmissionReceipt:
    package_id: str
    semantic_version: str
    ir_digest: str
    envelope_ref: str
    keyid: str
    artifact_manifest_digest: str


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


def manifest_digest(manifest: Sequence[ArtifactManifestEntry]) -> str:
    return canonical_digest([{"artifact_id": e.artifact_id, "digest": e.digest, "media_type": e.media_type}
                             for e in sorted(manifest, key=lambda e: e.artifact_id)])


class ReleaseAdmission:
    """Verifies a ReleasePackage before activation (ADD v1.3 :523); fail-closed."""

    def __init__(self, *, trust_root: TrustRoot, accepted_compiler_versions: Sequence[str],
                 generator: Any | None = None) -> None:
        from .codegen import IrArtifactGenerator

        self._trust = trust_root
        self._compilers = frozenset(accepted_compiler_versions)
        self._generator = generator or IrArtifactGenerator()

    def verify(self, package: ReleasePackage) -> AdmissionReceipt:
        release = package.signed.release
        envelope = _thaw(package.signed.envelope)
        signature = self._verify_envelope(release, envelope)
        core = parse_core(release.canonical_bytes)
        meta = core.get("release")
        if not isinstance(meta, dict):
            raise _reject(DiagnosticCode.RELEASE_REJECTED, "core/release", "the core has no release block")
        if meta.get("compiler_version") not in self._compilers:
            raise _reject(DiagnosticCode.RELEASE_REJECTED, "core/release/compiler_version",
                          "the compiler version is not admitted")
        lock = sorted(({"resource_id": e.resource_id, "sha256": e.digest, "version": e.version}
                       for e in package.dependency_lock), key=lambda e: (e["resource_id"], e["version"]))
        if canonical_digest(lock) != meta.get("lock_digest"):
            raise _reject(DiagnosticCode.LOCK_INVALID, "dependency_lock", "the lock does not match lock_digest")
        self._generator.check_drift(release, dict(package.artifacts))
        return AdmissionReceipt(
            package_id=str(meta["package_id"]), semantic_version=str(meta["semantic_version"]),
            ir_digest=release.ir_digest, envelope_ref=release.signature_envelope_ref, keyid=signature,
            artifact_manifest_digest=manifest_digest(release.artifacts),
        )

    def _verify_envelope(self, release: CanonicalIrRelease, envelope: dict[str, Any]) -> str:
        def invalid(message: str) -> C1Error:
            return _reject(DiagnosticCode.SIGNATURE_INVALID, "signature_envelope", message)

        if release.signature_envelope_ref.startswith(UNSIGNED_PREFIX) or not envelope:
            raise invalid("an unsigned release is never admitted")
        errors = sorted(_ENVELOPE_VALIDATOR.iter_errors(envelope), key=lambda e: e.json_path)
        if errors:
            raise invalid(f"envelope violates signed-canonical-ir:1.0: {errors[0].message}")
        if not hmac.compare_digest(canonical_digest(envelope), release.signature_envelope_ref):
            raise invalid("signature_envelope_ref does not name this envelope")
        try:
            payload = base64.b64decode(envelope["payload"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise invalid("payload is not base64") from exc
        if envelope["digest"] != "sha256:" + hashlib.sha256(payload).hexdigest():
            raise invalid("envelope digest does not bind the payload")
        if payload != release.canonical_bytes or "urn:sha256:" + envelope["digest"][7:] != release.ir_digest:
            raise invalid("payload is not the release core")
        pae = dsse_pae(envelope["payloadType"], payload)
        for item in envelope["signatures"]:
            trusted = self._trust.keys.get(item["keyid"])
            if trusted is None or item["keyid"] in self._trust.revoked_keyids:
                continue
            if trusted.signing_profile != envelope["signingProfile"] or envelope["signingProfile"] != ED25519_PROFILE:
                continue
            if not hmac.compare_digest(trusted.certificate_chain_ref, item["certificateChainRef"]):
                continue
            try:
                raw = base64.b64decode(item["sig"], validate=True)
            except (binascii.Error, ValueError):
                continue
            if ed25519_verify(trusted.public_key, pae, raw):
                return str(item["keyid"])
        raise invalid("no signature verifies under a trusted, unrevoked key and its certificate chain")
