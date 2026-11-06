"""Real service-backed control-plane boundary providers.

OCOR-DEV-0048 (G4, WS-11) wires the four approved control-plane ports to the
local ``ocor-bootstrap`` services so that least privilege (OPA), workload
identity and mTLS trust (SPIFFE/SPIRE), policy bundles (OPA), delegation
(Keycloak) and secret isolation (OpenBao) are enforced by real backends.

Every provider fails closed: an unreachable service, a stale policy bundle, an
unverifiable signature or an unredeemable lease raises a correlated
:class:`SecurityControlError` instead of returning a usable record.  No secret
material ever crosses a port -- only opaque handles and digests do.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import re
import socket
import ssl
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import IO, cast

from ..kernel.canonical import canonical_bytes
from ..kernel.governance import RiskClass
from .ports import (
    DIGEST,
    AuthenticatedPrincipal,
    ControlName,
    ControlStatus,
    IdentityRequest,
    PolicyDecision,
    PolicyEffect,
    PolicyRequest,
    SecretLease,
    SecretRequest,
    SecurityControlError,
    WorkloadIdentity,
)

_RFC3339 = "%Y-%m-%dT%H:%M:%SZ"
# A single safe path segment for OpenBao kv-v2 interpolation: non-empty, no
# slash, no leading/trailing dot and no '..' segment (rejects traversal).
_VAULT_PATH_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_DIGEST_INFO: dict[str, bytes] = {
    "sha256": bytes.fromhex("3031300d060960864801650304020105000420"),
    "sha384": bytes.fromhex("3041300d060960864801650304020205000430"),
    "sha512": bytes.fromhex("3051300d060960864801650304020305000440"),
}

# signatureAlgorithm OIDs -> (key kind, digest name)
_SIGALG: dict[bytes, tuple[str, str]] = {
    bytes.fromhex("2a8648ce3d040302"): ("ecdsa", "sha256"),
    bytes.fromhex("2a8648ce3d040303"): ("ecdsa", "sha384"),
    bytes.fromhex("2a8648ce3d040304"): ("ecdsa", "sha512"),
    bytes.fromhex("2a864886f70d01010b"): ("rsa", "sha256"),
    bytes.fromhex("2a864886f70d01010c"): ("rsa", "sha384"),
    bytes.fromhex("2a864886f70d01010d"): ("rsa", "sha512"),
}
_OID_EC_PUBLIC = bytes.fromhex("2a8648ce3d0201")  # id-ecPublicKey
_OID_RSA = bytes.fromhex("2a864886f70d010101")  # rsaEncryption
_OID_P256 = bytes.fromhex("2a8648ce3d030107")  # secp256r1
_OID_SAN = bytes.fromhex("551d11")  # subjectAltName 2.5.29.17

# NIST P-256 domain parameters
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_utc(dt: datetime) -> datetime:
    """Normalise a timezone-aware instant to UTC whole-second precision.

    Both signing and enforcement must reduce a ``datetime`` to the exact same
    canonical UTC instant; otherwise an offset-only alteration (which leaves
    the signed wall-clock string unchanged) could shift the enforced instant
    and reopen a time window that the authority never granted.
    """
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise SecurityControlError("SECURITY_RECORD_INVALID", "time must be timezone-aware")
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def _certificate_window(certificates: list[dict[str, object]]) -> tuple[datetime, datetime]:
    """Intersect the verified leaf, intermediate and trust-anchor windows."""
    not_before = datetime.fromtimestamp(
        max(cast(int, cert["not_before"]) for cert in certificates), timezone.utc
    )
    expires_at = datetime.fromtimestamp(
        min(cast(int, cert["not_after"]) for cert in certificates), timezone.utc
    )
    if not_before > _now() or _now() >= expires_at:
        raise SecurityControlError("WORKLOAD_IDENTITY_EXPIRED", "SVID chain is outside its window")
    return not_before, expires_at


def _mtls_deadline(context: ssl.SSLContext | None) -> datetime:
    if not isinstance(context, _PeerIdentitySSLContext):
        raise SecurityControlError("MTLS_REQUIRED", "verified SVID validity is required")
    return context.require_current_identity()


def workload_key_thumbprint(context: ssl.SSLContext | None) -> str:
    """Return the confirmation thumbprint of the workload key presented on mTLS.

    It is the SHA-256 URN of the SVID leaf SubjectPublicKeyInfo loaded into a
    SPIRE-built mutual-TLS context; any other context fails closed.
    """
    if not isinstance(context, _PeerIdentitySSLContext):
        raise SecurityControlError("MTLS_REQUIRED", "a verified SPIFFE mTLS context is required")
    return context.workload_key_thumbprint()


def _sha256_urn(data: bytes) -> str:
    return "urn:sha256:" + hashlib.sha256(data).hexdigest()


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding)


def _der_to_pem(der: bytes, label: str) -> str:
    """Encode DER bytes as a single PEM block (used to feed the stdlib ssl
    loaders, which only accept PEM on disk or as a string)."""
    body = base64.b64encode(der).decode("ascii")
    lines = [body[i : i + 64] for i in range(0, len(body), 64)]
    return f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject any HTTP redirect.

    An authenticated control-plane flow must never be silently re-routed to a
    different endpoint or authority, so a 3xx response is treated as a
    transport denial rather than followed."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        raise SecurityControlError(
            "SERVICE_UNAVAILABLE", "correlation_id=none unexpected HTTP redirect"
        )


def _correlation(correlation_id: str | None) -> str:
    """Render a correlation prefix for denial messages (never a secret)."""
    return f"correlation_id={correlation_id}" if correlation_id else "correlation_id=none"


def _request(
    method: str,
    url: str,
    *,
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 3.0,
    correlation_id: str | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> tuple[int, bytes]:
    correlation = _correlation(correlation_id)
    scheme = urllib.parse.urlsplit(url).scheme
    if scheme != "https":
        raise SecurityControlError(
            "MTLS_REQUIRED",
            f"{correlation} authenticated control-plane I/O requires an HTTPS "
            f"URL (got {scheme or 'no scheme'!r})",
        )
    _mtls_deadline(ssl_context)
    req = urllib.request.Request(url, method=method, data=data)
    if headers:
        for key, value in headers.items():
            req.add_header(key, value)
    opener = urllib.request.build_opener(
        _NoRedirectHandler(), urllib.request.HTTPSHandler(context=ssl_context)
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        raise SecurityControlError("SERVICE_UNAVAILABLE", f"{correlation} {exc.reason}") from exc
    except TimeoutError as exc:
        raise SecurityControlError("SERVICE_UNAVAILABLE", f"{correlation} request timed out") from exc
    except (ssl.SSLError, OSError) as exc:
        # A TLS handshake failure (e.g. the peer rejected our SVID, or its
        # certificate is not signed by the pinned trust bundle) is a transport
        # denial, never an exception that escapes the fail-closed boundary.
        raise SecurityControlError(
            "SERVICE_UNAVAILABLE", f"{correlation} mutual-TLS transport failed: {exc}"
        ) from exc


def _require_mtls_context(context: ssl.SSLContext | None) -> ssl.SSLContext:
    """Fail closed unless the caller supplied a real mutual-TLS context that
    both presents a workload certificate and requires/verifies the peer."""
    if context is None:
        raise SecurityControlError(
            "MTLS_REQUIRED",
            "correlation_id=none mutual TLS is mandatory for authenticated "
            "control-plane flows (workload identity + verified trust bundle)",
        )
    if context.verify_mode != ssl.CERT_REQUIRED:
        raise SecurityControlError(
            "MTLS_REQUIRED",
            "correlation_id=none mutual-TLS context must require and verify a "
            "peer certificate against the trust bundle",
        )
    return context


class _PeerIdentitySSLContext(ssl.SSLContext):
    """A mutual-TLS client context that also verifies the peer SPIFFE identity.

    The stdlib hostname matcher only understands DNS/IP subjectAltNames and
    never SPIFFE URI SANs, so ``check_hostname`` cannot express the peer
    identity obligation.  This context keeps ``check_hostname=False`` (the
    chain and validity are still verified through ``CERT_REQUIRED``) and
    instead enforces, on every handshake, that the peer certificate's URI SAN
    carries exactly the expected SPIFFE ID.  A valid SVID from the same trust
    domain belonging to a different service is therefore rejected before any
    request bytes are written.
    """

    def __new__(cls, expected_peer_spiffe_id: str) -> "_PeerIdentitySSLContext":
        return super().__new__(cls, ssl.PROTOCOL_TLS_CLIENT)

    def __init__(self, expected_peer_spiffe_id: str) -> None:
        self._expected_peer_spiffe_id = expected_peer_spiffe_id
        self._identity_window: tuple[datetime, datetime] | None = None
        self._peer_window: tuple[datetime, datetime] | None = None
        # SHA-256 URN of the SubjectPublicKeyInfo of the SVID this context
        # presents: the workload key a DelegationGrant is confirmed to.
        self._identity_key_thumbprint: str | None = None

    def workload_key_thumbprint(self) -> str:
        if self._identity_key_thumbprint is None:
            raise SecurityControlError("MTLS_REQUIRED", "workload key thumbprint is unknown")
        return self._identity_key_thumbprint

    def require_current_identity(self) -> datetime:
        if self._identity_window is None:
            raise SecurityControlError("MTLS_REQUIRED", "verified SVID validity is required")
        windows = [self._identity_window]
        if self._peer_window is not None:
            windows.append(self._peer_window)
        now = _now()
        if any(now < start or now >= end for start, end in windows):
            raise SecurityControlError("WORKLOAD_IDENTITY_EXPIRED", "mTLS authority has expired")
        return min(end for _, end in windows)

    def wrap_socket(
        self,
        sock: socket.socket,
        server_side: bool = False,
        do_handshake_on_connect: bool = True,
        suppress_ragged_eofs: bool = True,
        server_hostname: str | bytes | None = None,
        session: ssl.SSLSession | None = None,
    ) -> ssl.SSLSocket:
        self.require_current_identity()
        tls = super().wrap_socket(
            sock,
            server_side=server_side,
            do_handshake_on_connect=do_handshake_on_connect,
            suppress_ragged_eofs=suppress_ragged_eofs,
            server_hostname=server_hostname,
            session=session,
        )
        self._verify_peer_spiffe_id(tls)
        return tls

    def _verify_peer_spiffe_id(self, tls: ssl.SSLSocket) -> None:
        peer = tls.getpeercert()
        if not peer:
            # A deferred handshake (do_handshake_on_connect=False) has not yet
            # presented the peer certificate; force it now so the identity is
            # verified before any application bytes can be exchanged.
            try:
                tls.do_handshake()
            except (ssl.SSLError, OSError) as exc:
                tls.close()
                raise ssl.SSLError("peer TLS handshake failed") from exc
            peer = tls.getpeercert()
        if not peer:
            tls.close()
            raise ssl.SSLError("peer presented no certificate for SPIFFE identity check")
        uri_sans: list[str] = []
        for entry in peer.get("subjectAltName", []):
            if isinstance(entry, tuple) and len(entry) == 2 and entry[0] == "URI":
                uri_sans.append(str(entry[1]))
        if self._expected_peer_spiffe_id not in uri_sans:
            tls.close()
            raise ssl.SSLError(
                "peer SPIFFE identity mismatch: expected "
                f"{self._expected_peer_spiffe_id!r}, got {uri_sans!r}"
            )
        # OpenSSL has verified this chain. Preserve every authority's window,
        # including a peer intermediate whose expiry precedes the leaf's.
        try:
            ssl_object = getattr(tls, "_sslobj")
            certificates = [
                _parse_certificate(ssl.PEM_cert_to_DER_cert(cert.public_bytes()))
                for cert in ssl_object.get_verified_chain()
            ]
            self._peer_window = _certificate_window(certificates)
        except (AttributeError, ValueError, SecurityControlError):
            tls.close()
            raise


# --------------------------------------------------------------------------- #
# Minimal DER / X.509 parsing (stdlib only; no third-party cryptography).
# --------------------------------------------------------------------------- #


def _tlv(data: bytes, off: int) -> tuple[int, int, int, int]:
    """Return ``(tag, length, content_start, content_end)`` for the TLV at ``off``."""
    tag = data[off]
    off += 1
    length = data[off]
    off += 1
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(data[off : off + count], "big")
        off += count
    return tag, length, off, off + length


def _first_oid(content: bytes) -> bytes:
    _, _, oid_start, oid_end = _tlv(content, 0)
    return content[oid_start:oid_end]


def _parse_time(raw: bytes) -> int:
    text = raw.decode("ascii")
    if len(text) == 13 and text.endswith("Z"):  # UTCTime
        yy = int(text[0:2])
        year = 1900 + yy if yy >= 50 else 2000 + yy
        when = datetime(
            year, int(text[2:4]), int(text[4:6]), int(text[6:8]),
            int(text[8:10]), int(text[10:12]), tzinfo=timezone.utc,
        )
    elif len(text) == 15 and text.endswith("Z"):  # GeneralizedTime
        when = datetime(
            int(text[0:4]), int(text[4:6]), int(text[6:8]), int(text[8:10]),
            int(text[10:12]), int(text[12:14]), tzinfo=timezone.utc,
        )
    else:
        raise SecurityControlError("SVID_CHAIN_INVALID", "unparseable certificate time")
    return int(when.timestamp())


def _parse_validity(content: bytes) -> tuple[int, int]:
    _, _, nb_start, nb_end = _tlv(content, 0)
    _, _, na_start, na_end = _tlv(content, nb_end)
    return _parse_time(content[nb_start:nb_end]), _parse_time(content[na_start:na_end])


def _parse_spki(content: bytes) -> dict[str, bytes]:
    _, _, ai_start, ai_end = _tlv(content, 0)
    oid = _first_oid(content[ai_start:ai_end])
    _, _, pk_start, pk_end = _tlv(content, ai_end)
    key_der = content[pk_start + 1 : pk_end]  # strip the BIT STRING unused-bits byte
    return {"oid": oid, "key_der": key_der}


def _parse_uri_sans(extensions_content: bytes) -> list[str]:
    uris: list[str] = []
    tag, _, seq_start, seq_end = _tlv(extensions_content, 0)
    if tag != 0x30:  # extensions SEQUENCE wrapper
        return uris
    off = seq_start
    while off < seq_end:
        _, _, ext_start, ext_end = _tlv(extensions_content, off)
        ext = extensions_content[ext_start:ext_end]
        _, _, oid_start, oid_end = _tlv(ext, 0)
        oid = ext[oid_start:oid_end]
        pos = oid_end
        if pos < len(ext) and ext[pos] == 0x01:  # optional critical BOOLEAN
            _, _, _, pos = _tlv(ext, pos)
        _, _, value_start, value_end = _tlv(ext, pos)
        if oid == _OID_SAN:
            names_content = ext[value_start:value_end]
            n_tag, _, n_start, n_end = _tlv(names_content, 0)
            if n_tag == 0x30:  # GeneralNames SEQUENCE wrapper
                n_off = n_start
                while n_off < n_end:
                    g_tag = names_content[n_off]
                    _, _, g_start, g_end = _tlv(names_content, n_off)
                    if g_tag == 0x86:  # uniformResourceIdentifier [6]
                        uris.append(names_content[g_start:g_end].decode("ascii"))
                    n_off = g_end
        off = ext_end
    return uris


def _parse_certificate(der: bytes) -> dict[str, object]:
    tag, _, content_start, _ = _tlv(der, 0)
    if tag != 0x30:
        raise SecurityControlError("SVID_CHAIN_INVALID", "certificate is not a SEQUENCE")
    # tbsCertificate
    tbs_tag, _, _, tbs_end = _tlv(der, content_start)
    if tbs_tag != 0x30:
        raise SecurityControlError("SVID_CHAIN_INVALID", "tbsCertificate is not a SEQUENCE")
    tbs_der = der[content_start:tbs_end]
    # signatureAlgorithm
    _, _, sa_start, sa_end = _tlv(der, tbs_end)
    sigalg_oid = _first_oid(der[sa_start:sa_end])
    # signatureValue BIT STRING
    _, _, sig_start, sig_end = _tlv(der, sa_end)
    signature = der[sig_start + 1 : sig_end]

    # walk tbs content: version?, serial, sig, issuer, validity, subject, spki, ext?
    tbs_start = content_start + 2
    _, tbs_len, tbs_body_start, _ = _tlv(der, content_start)
    del tbs_len
    off = tbs_body_start
    if der[off] == 0xA0:  # [0] EXPLICIT version
        _, _, _, off = _tlv(der, off)
    _, _, _, off = _tlv(der, off)  # serialNumber
    _, _, _, off = _tlv(der, off)  # signature (inner)
    _, _, _, off = _tlv(der, off)  # issuer
    _, _, validity_start, validity_end = _tlv(der, off)  # validity
    not_before, not_after = _parse_validity(der[validity_start:validity_end])
    off = validity_end
    _, _, _, off = _tlv(der, off)  # subject
    spki_tlv_start = off
    _, _, spki_start, spki_end = _tlv(der, off)  # subjectPublicKeyInfo
    spki = _parse_spki(der[spki_start:spki_end])
    spki_der = der[spki_tlv_start:spki_end]
    off = spki_end
    uri_sans: list[str] = []
    if off < tbs_end and der[off] == 0xA3:  # [3] EXPLICIT extensions
        _, _, ext_start, ext_end = _tlv(der, off)
        uri_sans = _parse_uri_sans(der[ext_start:ext_end])

    del tbs_start
    return {
        "tbs_der": tbs_der,
        "sigalg_oid": sigalg_oid,
        "signature": signature,
        "not_before": not_before,
        "not_after": not_after,
        "spki_oid": spki["oid"],
        "key_der": spki["key_der"],
        "spki_der": spki_der,
        "uri_sans": uri_sans,
    }


def _parse_rsa_public_key(key_der: bytes) -> tuple[int, int]:
    tag, _, content_start, content_end = _tlv(key_der, 0)
    if tag != 0x30:
        raise SecurityControlError("SVID_CHAIN_INVALID", "RSAPublicKey is not a SEQUENCE")
    _, _, mod_start, mod_end = _tlv(key_der, content_start)
    _, _, exp_start, exp_end = _tlv(key_der, mod_end)
    modulus = int.from_bytes(key_der[mod_start:mod_end], "big")
    exponent = int.from_bytes(key_der[exp_start:exp_end], "big")
    del content_end
    return modulus, exponent


def _parse_ec_point(key_der: bytes) -> tuple[int, int]:
    if not key_der or key_der[0] != 0x04:
        raise SecurityControlError("SVID_CHAIN_INVALID", "EC point is not uncompressed")
    half = (len(key_der) - 1) // 2
    x = int.from_bytes(key_der[1 : 1 + half], "big")
    y = int.from_bytes(key_der[1 + half :], "big")
    return x, y


def _rsa_verify(message: bytes, signature: bytes, n: int, e: int, digest: str) -> bool:
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    em = pow(int.from_bytes(signature, "big"), e, n).to_bytes(k, "big")
    digest_info = _DIGEST_INFO[digest]
    digest_value = hashlib.new(digest, message).digest()
    padding_len = k - 3 - len(digest_info) - len(digest_value)
    if padding_len < 8:
        return False
    expected = b"\x00\x01" + b"\xff" * padding_len + b"\x00" + digest_info + digest_value
    return em == expected


def _ec_point_add(
    p1: tuple[int, int] | None, p2: tuple[int, int] | None
) -> tuple[int, int] | None:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if p1 == p2:
        slope = (3 * x1 * x1 + _A) * pow(2 * y1, -1, _P) % _P
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, _P) % _P
    x3 = (slope * slope - x1 - x2) % _P
    y3 = (slope * (x1 - x3) - y1) % _P
    return x3, y3


def _ec_scalar_mult(k: int, point: tuple[int, int]) -> tuple[int, int] | None:
    result: tuple[int, int] | None = None
    addend: tuple[int, int] | None = point
    while k:
        if k & 1:
            result = _ec_point_add(result, addend)
        addend = _ec_point_add(addend, addend)
        k >>= 1
    return result


def _ecdsa_verify(
    message: bytes, signature_der: bytes, qx: int, qy: int, digest: str
) -> bool:
    tag, _, content_start, content_end = _tlv(signature_der, 0)
    if tag != 0x30:
        return False
    _, _, r_start, r_end = _tlv(signature_der, content_start)
    _, _, s_start, s_end = _tlv(signature_der, r_end)
    if s_end != content_end:
        return False
    r = int.from_bytes(signature_der[r_start:r_end], "big")
    s = int.from_bytes(signature_der[s_start:s_end], "big")
    if not (1 <= r < _N and 1 <= s < _N):
        return False
    digest_value = hashlib.new(digest, message).digest()
    z = int.from_bytes(digest_value, "big")
    z >>= len(digest_value) * 8 - _N.bit_length()
    w = pow(s, -1, _N)
    u1 = (z * w) % _N
    u2 = (r * w) % _N
    point = _ec_point_add(
        _ec_scalar_mult(u1, (_GX, _GY)), _ec_scalar_mult(u2, (qx, qy))
    )
    if point is None:
        return False
    return point[0] % _N == r


def _verify_certificate_signature(
    cert: Mapping[str, object], issuer: Mapping[str, object]
) -> None:
    sigalg_oid = cert["sigalg_oid"]
    if not isinstance(sigalg_oid, bytes) or sigalg_oid not in _SIGALG:
        raise SecurityControlError("SVID_CHAIN_INVALID", "unsupported signature algorithm")
    kind, digest = _SIGALG[sigalg_oid]
    tbs_der = cert["tbs_der"]
    signature = cert["signature"]
    issuer_oid = issuer["spki_oid"]
    issuer_key = issuer["key_der"]
    assert isinstance(tbs_der, bytes)
    assert isinstance(signature, bytes)
    assert isinstance(issuer_key, bytes)
    if kind == "ecdsa":
        if issuer_oid != _OID_EC_PUBLIC:
            raise SecurityControlError(
                "SVID_CHAIN_INVALID", "ECDSA signature but non-EC issuer key"
            )
        qx, qy = _parse_ec_point(issuer_key)
        if not _ecdsa_verify(tbs_der, signature, qx, qy, digest):
            raise SecurityControlError("SVID_CHAIN_INVALID", "ECDSA signature check failed")
    else:
        if issuer_oid != _OID_RSA:
            raise SecurityControlError(
                "SVID_CHAIN_INVALID", "RSA signature but non-RSA issuer key"
            )
        modulus, exponent = _parse_rsa_public_key(issuer_key)
        if not _rsa_verify(tbs_der, signature, modulus, exponent, digest):
            raise SecurityControlError("SVID_CHAIN_INVALID", "RSA signature check failed")


def _split_der_chain(blob: bytes) -> list[bytes]:
    certs: list[bytes] = []
    off = 0
    while off < len(blob):
        _, _, _, end = _tlv(blob, off)
        certs.append(blob[off:end])
        off = end
    return certs


def _rsa_sign(message: bytes, n: int, d: int) -> bytes:
    """RSA PKCS#1 v1.5 SHA-256 signature (private-key operation, stdlib only)."""
    k = (n.bit_length() + 7) // 8
    digest_info = _DIGEST_INFO["sha256"]
    digest_value = hashlib.sha256(message).digest()
    padding_len = k - 3 - len(digest_info) - len(digest_value)
    if padding_len < 8:
        raise SecurityControlError("POLICY_BUNDLE_SIGNATURE_INVALID", "modulus too small to sign")
    encoded = b"\x00\x01" + b"\xff" * padding_len + b"\x00" + digest_info + digest_value
    return pow(int.from_bytes(encoded, "big"), d, n).to_bytes(k, "big")


@dataclass(frozen=True, slots=True)
class SignedPolicyBundle:
    """A governed policy bundle: source text plus a detached signature.

    ``signature`` is the base64-encoded RSA PKCS#1 v1.5 SHA-256 signature over
    :meth:`signing_payload`.  The provider verifies the signature against its
    pinned signer public key and refuses any bundle outside its validity
    window or carrying a mismatched ``policy_id``.
    """

    policy_id: str
    rego_source: str
    signer: str
    not_before: datetime
    expires_at: datetime
    signature: str

    def signing_payload(self) -> bytes:
        if not self.policy_id or not self.rego_source or not self.signer:
            raise SecurityControlError("POLICY_BUNDLE_INVALID", "bundle fields are incomplete")
        if self.not_before.tzinfo is None or self.expires_at.tzinfo is None:
            raise SecurityControlError("POLICY_BUNDLE_INVALID", "bundle validity window is empty")
        not_before = _canonical_utc(self.not_before)
        expires_at = _canonical_utc(self.expires_at)
        if not_before >= expires_at:
            raise SecurityControlError("POLICY_BUNDLE_INVALID", "bundle validity window is empty")
        return json.dumps(
            {
                "policy_id": self.policy_id,
                "rego_source": self.rego_source,
                "signer": self.signer,
                "not_before": not_before.strftime(_RFC3339),
                "expires_at": expires_at.strftime(_RFC3339),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


class OperationClass(IntEnum):
    """Operation classes, ordered by impact: the classes of ADD v1.3 §5.4 (:3300-3305), which
    prevail over the LLD v1.1 §4.1 names (LLD v1.1 :16-18; OCOR-DEV-REM-0054, NCR-C6-013).

    A ``DelegationGrant.effect_ceiling`` is the highest class an invocation
    under the grant may exercise; a higher class is outside the grant.
    """

    R0_READ = 0
    R1_ANALYZE = 1
    R2_CONTROLLED = 2
    R3_HIGH_IMPACT = 3


def _ordered_enum(field: str, value: object, kind: type[IntEnum], reason: str) -> IntEnum:
    # Strict: a bool, a string or an unknown ordinal never becomes a ceiling.
    if isinstance(value, bool) or not isinstance(value, int):
        raise SecurityControlError(reason, f"{field} must be a {kind.__name__}")
    try:
        return kind(value)
    except ValueError as exc:
        raise SecurityControlError(reason, f"{field} is not a {kind.__name__}") from exc


def _grant_string(field: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SecurityControlError("DELEGATION_INVALID", f"grant {field} is incomplete")
    return value


def _grant_digest_field(field: str, value: object) -> str:
    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise SecurityControlError("DELEGATION_INVALID", f"grant {field} is not a SHA-256 URN")
    return value


def _grant_set(field: str, values: object) -> list[str]:
    """A semantic set: non-empty, no duplicates, sorted before signing."""
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise SecurityControlError("DELEGATION_INVALID", f"grant {field} must be an array")
    items = [_grant_string(field, item) for item in values]
    if not items:
        raise SecurityControlError("DELEGATION_INVALID", f"grant {field} is empty")
    if len(set(items)) != len(items):
        raise SecurityControlError("DELEGATION_INVALID", f"grant {field} contains duplicates")
    return sorted(items)


def _grant_instant(field: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SecurityControlError("DELEGATION_INVALID", f"grant {field} must be timezone-aware")
    return _canonical_utc(value)


@dataclass(frozen=True, slots=True)
class CapabilityInvocation:
    """The capability a delegated call exercises (ADD v1.3 §5.1 Authority).

    It is intersected with every grant of the chain: same ``capability_id``
    and ``capability_version``, ``effect_class`` within ``effect_ceiling`` and
    ``risk_class`` within ``risk_ceiling``.  It is also forwarded to the signed
    policy, which binds the requested action to the declared capability.
    """

    capability_id: str
    capability_version: str
    effect_class: OperationClass
    risk_class: RiskClass

    def __post_init__(self) -> None:
        reason = "CAPABILITY_INVOCATION_INVALID"
        for field in ("capability_id", "capability_version"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise SecurityControlError(reason, f"{field} is required")
        object.__setattr__(
            self, "effect_class",
            _ordered_enum("effect_class", self.effect_class, OperationClass, reason),
        )
        object.__setattr__(
            self, "risk_class", _ordered_enum("risk_class", self.risk_class, RiskClass, reason)
        )

    def to_policy_input(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
            "effect_class": self.effect_class.name,
            "risk_class": self.risk_class.name,
        }


@dataclass(frozen=True, slots=True)
class SignedDelegation:
    """A signed, content-addressed ``DelegationGrant`` (ADD v1.3 §5.2).

    ``signature`` is the base64-encoded RSA PKCS#1 v1.5 SHA-256 signature of
    the pinned delegation authority over :meth:`signing_payload` -- the RFC
    8785 canonical bytes of every other field (the ``signature_ref`` of the
    design record).  :meth:`digest` is the content address of the grant and
    is what a child grant's ``parent_grant_digest`` links to.

    ``organization_id`` extends the design record: ADD v1.3 §1.4 requires the
    declared ``tenant_id``, ``organization_id``, ``domain_id`` and
    ``compartments`` to be compared with authorised bindings, so a grant that
    did not bind the organization could be replayed into a foreign one.
    Every field is mandatory; an incomplete grant is ``DELEGATION_INVALID``.
    """

    grant_id: str
    grantor_principal: str
    grantee_principal: str
    capability_id: str
    capability_version: str
    resource_scope: str
    tenant_id: str
    organization_id: str
    domains: tuple[str, ...]
    compartments: tuple[str, ...]
    permitted_purposes: tuple[str, ...]
    effect_ceiling: OperationClass
    risk_ceiling: RiskClass
    not_before: datetime
    expires_at: datetime
    max_chain_depth: int
    policy_bundle_digest: str
    nonce: str
    confirmation_key_thumbprint: str
    signature: str = ""
    redelegation_allowed: bool = False
    parent_grant_digest: str | None = None

    def signing_payload(self) -> bytes:
        record: dict[str, object] = {
            field: _grant_string(field, getattr(self, field))
            for field in (
                "grant_id", "grantor_principal", "grantee_principal", "capability_id",
                "capability_version", "resource_scope", "tenant_id", "organization_id",
            )
        }
        if self.grantor_principal == self.grantee_principal:
            raise SecurityControlError("DELEGATION_INVALID", "grant delegates to its grantor")
        for field in ("domains", "compartments", "permitted_purposes"):
            record[field] = _grant_set(field, getattr(self, field))
        reason = "DELEGATION_INVALID"
        record["effect_ceiling"] = _ordered_enum(
            "effect_ceiling", self.effect_ceiling, OperationClass, reason
        ).name
        record["risk_ceiling"] = _ordered_enum(
            "risk_ceiling", self.risk_ceiling, RiskClass, reason
        ).name
        not_before = _grant_instant("not_before", self.not_before)
        expires_at = _grant_instant("expires_at", self.expires_at)
        if not_before >= expires_at:
            raise SecurityControlError("DELEGATION_INVALID", "delegation validity window is empty")
        record["not_before"] = not_before.strftime(_RFC3339)
        record["expires_at"] = expires_at.strftime(_RFC3339)
        depth = self.max_chain_depth
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
            raise SecurityControlError("DELEGATION_INVALID", "max_chain_depth must be >= 1")
        record["max_chain_depth"] = depth
        if not isinstance(self.redelegation_allowed, bool):
            raise SecurityControlError("DELEGATION_INVALID", "redelegation_allowed must be boolean")
        record["redelegation_allowed"] = self.redelegation_allowed
        record["parent_grant_digest"] = (
            None if self.parent_grant_digest is None
            else _grant_digest_field("parent_grant_digest", self.parent_grant_digest)
        )
        record["policy_bundle_digest"] = _grant_digest_field(
            "policy_bundle_digest", self.policy_bundle_digest
        )
        nonce = _grant_string("nonce", self.nonce)
        if len(nonce) < 16:
            raise SecurityControlError("DELEGATION_INVALID", "grant nonce is too short")
        record["nonce"] = nonce
        record["confirmation_key_thumbprint"] = _grant_digest_field(
            "confirmation_key_thumbprint", self.confirmation_key_thumbprint
        )
        return canonical_bytes(record)

    def digest(self) -> str:
        return _sha256_urn(self.signing_payload())


DelegationGrant = SignedDelegation


def verify_delegation_signature(
    grant: SignedDelegation, signer_public_key: tuple[int, int]
) -> str:
    """Verify the grant's detached signature; return its content address."""

    signer_n, signer_e = signer_public_key
    payload = grant.signing_payload()
    try:
        signature = _b64_decode(grant.signature)
    except (ValueError, TypeError) as exc:
        raise SecurityControlError(
            "DELEGATION_SIGNATURE_INVALID", "delegation signature is malformed"
        ) from exc
    if not _rsa_verify(payload, signature, signer_n, signer_e, "sha256"):
        raise SecurityControlError(
            "DELEGATION_SIGNATURE_INVALID", "delegation signature does not verify"
        )
    return _sha256_urn(payload)


def verify_signed_delegation(
    delegation: SignedDelegation,
    signer_public_key: tuple[int, int],
    *,
    resource_scope: str,
    purpose: str,
    delegator_id: str,
    delegatee_id: str,
    at: datetime | None = None,
    revoked: bool = False,
) -> None:
    """Reject an unsigned, altered, revoked, out-of-window or out-of-scope
    single grant (FR-128: confused-deputy and delegation laundering defence).

    ``at`` is retained for source compatibility only; it never supplies the
    boundary clock.  The policy boundary applies the full chain, capability,
    governed-scope, policy and workload-key checks on top of these.
    """

    verify_delegation_signature(delegation, signer_public_key)
    if revoked:
        raise SecurityControlError("DELEGATION_REVOKED", "delegation is revoked")
    if (delegator_id != delegation.grantor_principal
            or delegatee_id != delegation.grantee_principal):
        raise SecurityControlError(
            "DELEGATION_BINDING_MISMATCH", "delegation does not bind the actor chain"
        )
    instant = _now()
    if (
        instant < _canonical_utc(delegation.not_before)
        or instant >= _canonical_utc(delegation.expires_at)
    ):
        raise SecurityControlError(
            "DELEGATION_EXPIRED", "delegation is outside its validity window"
        )
    if resource_scope != delegation.resource_scope:
        raise SecurityControlError(
            "DELEGATION_SCOPE_MISMATCH", "delegation does not cover the resource scope"
        )
    if purpose not in delegation.permitted_purposes:
        raise SecurityControlError(
            "DELEGATION_PURPOSE_MISMATCH", "delegation does not cover the purpose"
        )


@dataclass(frozen=True, slots=True)
class SignedDelegationRevocation:
    """A signed, content-addressed revocation of one delegation grant.

    ``signature`` is the base64-encoded RSA PKCS#1 v1.5 SHA-256 signature over
    :meth:`signing_payload`, produced by the same authority that signed the
    grant.  A provider honours a revocation only after verifying its signature
    against the pinned delegation authority key, so a forged revocation is
    rejected exactly like a forged grant.
    """

    delegation_id: str
    revoked_at: datetime
    signature: str

    def signing_payload(self) -> bytes:
        if not self.delegation_id:
            raise SecurityControlError(
                "DELEGATION_REVOCATION_INVALID", "revocation fields are incomplete"
            )
        if self.revoked_at.tzinfo is None or self.revoked_at.utcoffset() is None:
            raise SecurityControlError(
                "DELEGATION_REVOCATION_INVALID", "revocation time is not timezone-aware"
            )
        return json.dumps(
            {
                "delegation_id": self.delegation_id,
                "revoked_at": _canonical_utc(self.revoked_at).strftime(_RFC3339),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


def verify_signed_delegation_revocation(
    revocation: SignedDelegationRevocation,
    signer_public_key: tuple[int, int],
) -> None:
    """Reject an unsigned, altered or authority-mismatched revocation."""

    signer_n, signer_e = signer_public_key
    payload = revocation.signing_payload()
    try:
        signature = _b64_decode(revocation.signature)
    except (ValueError, TypeError) as exc:
        raise SecurityControlError(
            "DELEGATION_REVOCATION_INVALID", "revocation signature is malformed"
        ) from exc
    if not _rsa_verify(payload, signature, signer_n, signer_e, "sha256"):
        raise SecurityControlError(
            "DELEGATION_REVOCATION_INVALID", "revocation signature does not verify"
        )


_ABSENT = object()


def _signed_actor_chain(
    actor: object, principal_id: str, correlation_id: str | None
) -> list[str]:
    """Derive the authenticated actor chain from a verified ``act`` claim.

    Actors are expressed only by the signed RFC 8693 ``act`` claim, whose
    nested ``act`` names the prior actor; neither ``azp`` nor
    ``preferred_username`` is ever an actor.  The chain is ordered from the
    earliest actor to the principal.  A present but malformed, empty,
    self-referencing or repeating claim is rejected rather than ignored, so a
    token can never be read as less delegated than it is signed to be.  The
    chain authenticates the actors only: a delegated request still needs the
    complete signed grant chain at the policy boundary.
    """
    chain = [principal_id]
    claims: object = {"act": actor} if actor is not _ABSENT else {}
    while isinstance(claims, dict) and "act" in claims:
        actor = claims["act"]
        actor_id = actor.get("sub") if isinstance(actor, dict) else None
        if not isinstance(actor_id, str) or not actor_id or actor_id in chain:
            raise SecurityControlError(
                "IDENTITY_REJECTED",
                f"{_correlation(correlation_id)} malformed or cyclic actor claim",
            )
        chain.insert(0, actor_id)
        claims = actor
    return chain


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #


class KeycloakIdentityProvider:
    """Authenticates a principal and its delegation chain against real Keycloak."""

    def __init__(
        self,
        base_url: str,
        realm: str,
        client_id: str,
        *,
        password_resolver: Callable[[str], str],
        timeout_seconds: float = 5.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._realm = realm
        self._client_id = client_id
        self._password_resolver = password_resolver
        self._timeout = timeout_seconds
        self._ssl_context = _require_mtls_context(ssl_context)

    def _secure_endpoint(self, url: str) -> str:
        """Confine a discovery-document endpoint to the HTTPS base authority.

        The discovery document is fetched from ``self._base_url`` (already over
        mutual TLS).  It may advertise a token or JWKS endpoint on a plaintext
        backend or on a different authority; the provider must never downgrade
        the authenticated flow to plaintext nor move it to a foreign authority.
        Every endpoint is therefore re-anchored to the ``https`` scheme and to
        ``self._base_url``'s host and port, preserving only the path, query and
        fragment.  A compromised discovery document is thus unable to steer the
        credentialed flow to a different or plaintext endpoint.
        """
        parsed = urllib.parse.urlsplit(url)
        base = urllib.parse.urlsplit(self._base_url)
        return urllib.parse.urlunsplit(
            ("https", base.netloc, parsed.path, parsed.query, parsed.fragment)
        )

    def _oidc_configuration(self, correlation_id: str | None = None) -> dict[str, object]:
        url = f"{self._base_url}/realms/{self._realm}/.well-known/openid-configuration"
        status, body = _request(
            "GET",
            url,
            timeout=self._timeout,
            correlation_id=correlation_id,
            ssl_context=self._ssl_context,
        )
        if status != 200:
            raise SecurityControlError(
                "IDENTITY_UNAVAILABLE",
                f"{_correlation(correlation_id)} OIDC discovery HTTP {status}",
            )
        return cast(dict[str, object], json.loads(body.decode()))

    def _jwks(
        self, jwks_uri: str, correlation_id: str | None = None
    ) -> dict[str, tuple[int, int]]:
        status, body = _request(
            "GET",
            jwks_uri,
            timeout=self._timeout,
            correlation_id=correlation_id,
            ssl_context=self._ssl_context,
        )
        if status != 200:
            raise SecurityControlError(
                "IDENTITY_UNAVAILABLE",
                f"{_correlation(correlation_id)} JWKS HTTP {status}",
            )
        keys = json.loads(body.decode()).get("keys", [])
        result: dict[str, tuple[int, int]] = {}
        for key in keys:
            if key.get("kty") != "RSA":
                continue
            n = int.from_bytes(_b64url_decode(str(key["n"])), "big")
            e = int.from_bytes(_b64url_decode(str(key["e"])), "big")
            result[str(key["kid"])] = (n, e)
        return result

    def _password_grant(
        self,
        token_endpoint: str,
        username: str,
        password: str,
        correlation_id: str | None = None,
    ) -> str:
        form = urllib.parse.urlencode(
            {
                "client_id": self._client_id,
                "username": username,
                "password": password,
                "grant_type": "password",
            }
        ).encode()
        status, body = _request(
            "POST",
            token_endpoint,
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self._timeout,
            correlation_id=correlation_id,
            ssl_context=self._ssl_context,
        )
        if status != 200:
            raise SecurityControlError(
                "IDENTITY_REJECTED",
                f"{_correlation(correlation_id)} token grant HTTP {status}",
            )
        return cast(str, json.loads(body.decode())["access_token"])

    def _verify_access_token(
        self,
        token: str,
        jwks: dict[str, tuple[int, int]],
        issuer: str,
        audience: str,
        correlation_id: str | None = None,
    ) -> dict[str, object]:
        correlation = _correlation(correlation_id)
        try:
            header_b64, payload_b64, signature_b64 = token.split(".")
        except ValueError as exc:
            raise SecurityControlError("IDENTITY_REJECTED", f"{correlation} malformed JWT") from exc
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
        signature = _b64url_decode(signature_b64)
        if header.get("alg") != "RS256":
            raise SecurityControlError("IDENTITY_REJECTED", f"{correlation} unsupported JWT algorithm")
        key = jwks.get(str(header.get("kid")))
        if key is None:
            raise SecurityControlError("IDENTITY_REJECTED", f"{correlation} unknown signing key")
        signing_input = f"{header_b64}.{payload_b64}".encode()
        if not _rsa_verify(signing_input, signature, key[0], key[1], "sha256"):
            raise SecurityControlError("IDENTITY_REJECTED", f"{correlation} JWT signature check failed")
        if payload.get("iss") != issuer:
            raise SecurityControlError("IDENTITY_REJECTED", f"{correlation} issuer mismatch")
        audience_list = payload.get("aud", [])
        if isinstance(audience_list, str):
            audience_list = [audience_list]
        if audience not in audience_list:
            raise SecurityControlError("IDENTITY_REJECTED", f"{correlation} audience mismatch")
        now = _now().timestamp()
        try:
            exp, iat = payload["exp"], payload["iat"]
            nbf = payload.get("nbf", iat)
            if any(isinstance(value, bool) or not isinstance(value, int)
                   for value in (exp, iat, nbf)):
                raise ValueError("invalid NumericDate")
            if int(exp) <= now or int(iat) > now or int(nbf) > now:
                raise ValueError("outside validity window")
        except (KeyError, TypeError, ValueError) as exc:
            raise SecurityControlError(
                "IDENTITY_REJECTED", f"{correlation} access token is outside its validity window"
            ) from exc
        return cast(dict[str, object], payload)

    def authenticate(self, request: IdentityRequest) -> AuthenticatedPrincipal:
        prefix = "urn:ocor:credential-ref:"
        if not request.credential_ref.startswith(prefix):
            raise SecurityControlError("IDENTITY_REJECTED", "unknown credential reference")
        username = request.credential_ref[len(prefix) :]
        if not username:
            raise SecurityControlError("IDENTITY_REJECTED", "empty credential reference")
        password = self._password_resolver(username)

        correlation_id = request.correlation_id
        configuration = self._oidc_configuration(correlation_id)
        issuer = str(configuration["issuer"])
        token_endpoint = self._secure_endpoint(str(configuration["token_endpoint"]))
        jwks_uri = self._secure_endpoint(str(configuration["jwks_uri"]))
        jwks = self._jwks(jwks_uri, correlation_id)
        token = self._password_grant(token_endpoint, username, password, correlation_id)
        claims = self._verify_access_token(
            token, jwks, issuer, request.expected_audience, correlation_id
        )

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise SecurityControlError("IDENTITY_REJECTED", "missing subject claim")
        principal_id = subject
        actor_chain = _signed_actor_chain(
            claims.get("act", _ABSENT), principal_id, correlation_id
        )
        session_id = str(
            claims.get("session_state")
            or claims.get("sid")
            or claims.get("jti")
            or ""
        )
        if not session_id:
            raise SecurityControlError("IDENTITY_REJECTED", "missing session identifier")
        authenticated_at = datetime.fromtimestamp(
            cast(int, claims["iat"]), tz=timezone.utc
        )
        expires_at = datetime.fromtimestamp(
            cast(int, claims["exp"]), tz=timezone.utc
        )
        expires_at = min(expires_at, _mtls_deadline(self._ssl_context))

        jwks_material = b"".join(
            f"{kid}:{key[0]}:{key[1]}".encode() for kid, key in sorted(jwks.items())
        )
        status = ControlStatus.available(
            ControlName.IDENTITY,
            observed_at=_now(),
            source_digest=_sha256_urn(jwks_material),
        )
        principal = AuthenticatedPrincipal(
            principal_id=principal_id,
            actor_chain=tuple(actor_chain),
            session_id=session_id,
            assurance_level="LEVEL_2",
            authenticated_at=authenticated_at,
            expires_at=expires_at,
            status=status,
        )
        return principal.require_valid(at=_now())


_GOVERNED_PACKAGE_PATH = ("data", "ocor", "control_plane")


def _policy_package_path(item: Mapping[str, object]) -> tuple[str, ...]:
    """Return the parsed ``package`` path (e.g. ``("data","ocor","control_plane")``)
    for an OPA ``/v1/policies`` entry, or ``()`` when it cannot be determined."""
    ast = item.get("ast")
    if not isinstance(ast, dict):
        return ()
    package = ast.get("package")
    if not isinstance(package, dict):
        return ()
    path = package.get("path")
    if not isinstance(path, list):
        return ()
    values: list[str] = []
    for node in path:
        if not (isinstance(node, dict) and isinstance(node.get("value"), str)):
            return ()
        values.append(str(node["value"]))
    return tuple(values)


def _strip_locations(node: object) -> object:
    if isinstance(node, dict):
        return {key: _strip_locations(value) for key, value in node.items() if key != "location"}
    if isinstance(node, list):
        return [_strip_locations(value) for value in node]
    return node


def _rule_fingerprint(rule: object) -> str:
    """Canonical, location-free identity of one compiled OPA rule."""
    return json.dumps(_strip_locations(rule), sort_keys=True, separators=(",", ":"))


def _rule_name(rule: object) -> str | None:
    head = rule.get("head") if isinstance(rule, dict) else None
    name = head.get("name") if isinstance(head, dict) else None
    return name if isinstance(name, str) and name else None


def _rule_head_name(rule: object) -> str | None:
    """The name of a compiled rule, also when OPA reports it only in the head reference
    (multi-value ``contains`` rules)."""
    name = _rule_name(rule)
    if name is not None:
        return name
    head = rule.get("head") if isinstance(rule, dict) else None
    ref = head.get("ref") if isinstance(head, dict) else None
    first = ref[0] if isinstance(ref, list) and ref else None
    value = first.get("value") if isinstance(first, dict) else None
    return value if isinstance(value, str) and value else None


# OCOR-DEV-REM-0054 (NCR-C6-011): the set rules of the governed package that qualify a permit.
_QUALIFIERS = {
    "constraints": PolicyEffect.PERMIT_WITH_CONSTRAINTS,
    "approval_requirements": PolicyEffect.REQUIRE_APPROVAL,
    "obligations": PolicyEffect.OBLIGATE,
}


def _data_references(node: object) -> list[list[object]]:
    """Every ``data``-rooted reference (and bare ``data`` variable) in an AST."""
    found: list[list[object]] = []
    if isinstance(node, dict):
        if node.get("type") == "var" and node.get("value") == "data":
            found.append([])
        value = node.get("value")
        if (node.get("type") == "ref" and isinstance(value, list) and value
                and value[0] == {"type": "var", "value": "data"}):
            found.append(value[1:])
            for term in value[1:]:
                found.extend(_data_references(term))
            return found
        for key, child in node.items():
            if key != "location":
                found.extend(_data_references(child))
    elif isinstance(node, list):
        for child in node:
            found.extend(_data_references(child))
    return found


@dataclass(frozen=True, slots=True)
class _VerifiedBundleSnapshot:
    """The immutable, verified policy bundle a decision is bound to.

    ``rules`` are the location-free fingerprints of the compiled rules OPA
    reported for the signed module right after installation.  The decision
    is accepted only if every rule OPA evaluated for it is one of these, so a
    module swapped or injected between the freshness check and the
    evaluation cannot influence a decision that still names this digest.
    """

    policy_id: str
    digest: str
    rules: frozenset[str]
    not_before: datetime
    expires_at: datetime

    def snapshot_digest(self) -> str:
        return _sha256_urn(canonical_bytes({
            "policy_id": self.policy_id,
            "digest": self.digest,
            "rules": sorted(self.rules),
            "not_before": self.not_before.strftime(_RFC3339),
            "expires_at": self.expires_at.strftime(_RFC3339),
        }))


class OpaPolicyDecisionProvider:
    """Installs a signed policy bundle and evaluates it with real OPA.

    A bundle is accepted only if its detached RSA signature verifies against
    the pinned signer public key (the *trust pin*), its ``policy_id`` matches,
    the current instant falls inside its declared validity window and the
    module OPA compiled is self-contained: it lives in the governed package
    and references no ``data`` document other than its own rules, so a
    decision is a function of the signed source and the forwarded input only.

    Every decision is bound to the immutable verified snapshot captured at
    its start: the governed context pin must name it, the live module set is
    checked before and after the evaluation, and the evaluation itself is
    requested with a full trace whose every evaluated rule must belong to the
    snapshot.  A delegated request must present the complete signed grant
    chain, verified against the pinned delegation authority, the live
    revocation set, the workload key on the mTLS channel, the snapshot and
    the governed scope, before and after the policy is consulted.
    """

    _ALLOW_PATH = "/v1/data/ocor/control_plane/allow"
    _PACKAGE_PATH = "/v1/data/ocor/control_plane"

    def __init__(
        self,
        base_url: str,
        policy_id: str,
        *,
        signer_public_key: tuple[int, int],
        timeout_seconds: float = 5.0,
        ssl_context: ssl.SSLContext | None = None,
        delegation_signer_public_key: tuple[int, int] | None = None,
        delegation_revocations: tuple[SignedDelegationRevocation, ...] = (),
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._policy_id = policy_id
        self._timeout = timeout_seconds
        self._ssl_context = _require_mtls_context(ssl_context)
        self._snapshot: _VerifiedBundleSnapshot | None = None
        self._signer_n, self._signer_e = signer_public_key
        if self._signer_n.bit_length() < 2048 or self._signer_e < 3:
            raise SecurityControlError(
                "POLICY_BUNDLE_SIGNATURE_INVALID", "trust pin modulus too small"
            )
        self._signer_pin = _sha256_urn(f"{self._signer_n}:{self._signer_e}".encode())
        self._delegation_signer_key = delegation_signer_public_key
        if delegation_signer_public_key is not None:
            dn, de = delegation_signer_public_key
            if dn.bit_length() < 2048 or de < 3:
                raise SecurityControlError(
                    "DELEGATION_BINDING_MISMATCH", "delegation trust pin modulus too small"
                )
        elif delegation_revocations:
            raise SecurityControlError(
                "DELEGATION_BINDING_MISMATCH", "revocations require a delegation trust pin"
            )
        self._lock = threading.Lock()
        self._delegation_revocations: dict[str, SignedDelegationRevocation] = {}
        # nonce -> content address of the only grant allowed to carry it.
        self._grant_nonces: dict[str, str] = {}
        for revocation in delegation_revocations:
            self.apply_revocation(revocation)

    @property
    def _bundle_digest(self) -> str | None:
        snapshot = self._snapshot
        return None if snapshot is None else snapshot.digest

    def apply_revocation(self, revocation: SignedDelegationRevocation) -> None:
        """Honour a signed revocation from now on (ADD v1.3 §5.2 rule 5).

        Every later decision, and every decision whose policy evaluation is
        still in flight, rejects a chain containing the revoked grant.
        """
        if self._delegation_signer_key is None:
            raise SecurityControlError(
                "DELEGATION_BINDING_MISMATCH", "revocations require a delegation trust pin"
            )
        verify_signed_delegation_revocation(revocation, self._delegation_signer_key)
        with self._lock:
            self._delegation_revocations[revocation.delegation_id] = revocation

    def install_policy(self, bundle: SignedPolicyBundle) -> str:
        if bundle.policy_id != self._policy_id:
            raise SecurityControlError(
                "POLICY_BUNDLE_INVALID",
                f"bundle policy_id {bundle.policy_id!r} does not match {self._policy_id!r}",
            )
        payload = bundle.signing_payload()
        signature = _b64_decode(bundle.signature)
        if not _rsa_verify(payload, signature, self._signer_n, self._signer_e, "sha256"):
            raise SecurityControlError(
                "POLICY_BUNDLE_SIGNATURE_INVALID",
                f"correlation_id=none bundle signature does not verify against trust pin "
                f"{self._signer_pin}",
            )
        now = _now()
        if now < _canonical_utc(bundle.not_before) or now >= _canonical_utc(bundle.expires_at):
            raise SecurityControlError(
                "POLICY_BUNDLE_WINDOW_INVALID",
                "policy bundle is outside its declared validity window",
            )
        digest = _sha256_urn(bundle.rego_source.encode())
        status, _ = _request(
            "PUT",
            f"{self._base_url}/v1/policies/{self._policy_id}",
            data=bundle.rego_source.encode(),
            headers={"Content-Type": "text/plain"},
            timeout=self._timeout,
            ssl_context=self._ssl_context,
        )
        if status != 200:
            raise SecurityControlError("POLICY_UNAVAILABLE", f"policy install HTTP {status}")
        current = self._fetch_policy_source()
        if current != bundle.rego_source:
            raise SecurityControlError("POLICY_UNAVAILABLE", "installed policy did not persist")
        installed = self._installed_module(self._fetch_policy_modules(), digest, "none")
        rules = self._self_contained_rules(installed)
        if _now() >= _canonical_utc(bundle.expires_at):
            raise SecurityControlError("POLICY_BUNDLE_WINDOW_INVALID", "bundle expired during install")
        self._snapshot = _VerifiedBundleSnapshot(
            policy_id=self._policy_id,
            digest=digest,
            rules=rules,
            not_before=_canonical_utc(bundle.not_before),
            expires_at=_canonical_utc(bundle.expires_at),
        )
        return digest

    def _installed_module(
        self, modules: list[dict[str, object]], digest: str, correlation_id: str
    ) -> dict[str, object]:
        for item in modules:
            if str(item.get("id", "")) == self._policy_id:
                raw = item.get("raw")
                if not isinstance(raw, str) or _sha256_urn(raw.encode()) != digest:
                    raise SecurityControlError(
                        "STALE_BUNDLE",
                        f"correlation_id={correlation_id} live policy digest drifted",
                    )
                return item
        raise SecurityControlError(
            "STALE_BUNDLE",
            f"correlation_id={correlation_id} installed module is missing from OPA",
        )

    def _self_contained_rules(self, item: Mapping[str, object]) -> frozenset[str]:
        """Fingerprint the compiled rules of a governed, self-contained module."""
        if _policy_package_path(item) != _GOVERNED_PACKAGE_PATH:
            raise SecurityControlError(
                "POLICY_BUNDLE_INVALID", "signed module is not in the governed package"
            )
        ast = item.get("ast")
        rules = ast.get("rules") if isinstance(ast, dict) else None
        if not isinstance(rules, list) or not rules:
            raise SecurityControlError("POLICY_BUNDLE_INVALID", "signed module has no rules")
        names = {_rule_name(rule) for rule in rules}
        if None in names:
            raise SecurityControlError("POLICY_BUNDLE_INVALID", "signed module rule is unnamed")
        package = [{"type": "string", "value": part} for part in _GOVERNED_PACKAGE_PATH[1:]]
        imports = ast.get("imports") if isinstance(ast, dict) else None
        for reference in _data_references(rules) + _data_references(imports or []):
            # The compiler addresses the module's own rules as
            # data.<package>.<rule>; any other data document (base data,
            # another package, the whole tree) is outside the signed bundle.
            head = reference[len(package)] if len(reference) > len(package) else None
            local = (
                reference[: len(package)] == package
                and isinstance(head, dict)
                and head.get("type") == "string"
                and head.get("value") in names
            )
            if not local:
                raise SecurityControlError(
                    "POLICY_BUNDLE_INVALID",
                    "signed module depends on a data document outside the bundle",
                )
        return frozenset(_rule_fingerprint(rule) for rule in rules)

    def _fetch_policy_source(self, correlation_id: str | None = None) -> str:
        status, body = _request(
            "GET",
            f"{self._base_url}/v1/policies/{self._policy_id}",
            timeout=self._timeout,
            correlation_id=correlation_id,
            ssl_context=self._ssl_context,
        )
        if status != 200:
            raise SecurityControlError("POLICY_UNAVAILABLE", f"policy fetch HTTP {status}")
        try:
            raw = json.loads(body.decode()).get("result", {}).get("raw", "")
        except (ValueError, json.JSONDecodeError):
            raw = body.decode()
        if not isinstance(raw, str):
            raise SecurityControlError("POLICY_UNAVAILABLE", "policy source is not textual")
        return raw

    def _fetch_policy_modules(
        self, correlation_id: str | None = None
    ) -> list[dict[str, object]]:
        """Return every module OPA currently evaluates (id + raw + parsed AST)."""
        status, body = _request(
            "GET",
            f"{self._base_url}/v1/policies",
            timeout=self._timeout,
            correlation_id=correlation_id,
            ssl_context=self._ssl_context,
        )
        if status != 200:
            raise SecurityControlError("POLICY_UNAVAILABLE", f"policy list HTTP {status}")
        try:
            result = json.loads(body.decode()).get("result", [])
        except (ValueError, json.JSONDecodeError) as exc:
            raise SecurityControlError("POLICY_UNAVAILABLE", "malformed policy list") from exc
        if not isinstance(result, list):
            raise SecurityControlError("POLICY_UNAVAILABLE", "policy list is not an array")
        return [item for item in result if isinstance(item, dict)]

    def _require_fresh_bundle(
        self, correlation_id: str, snapshot: _VerifiedBundleSnapshot | None = None
    ) -> _VerifiedBundleSnapshot:
        snapshot = snapshot if snapshot is not None else self._snapshot
        if snapshot is None:
            raise SecurityControlError(
                "POLICY_UNAVAILABLE", f"correlation_id={correlation_id} no policy installed"
            )
        self._require_bundle_window(correlation_id, snapshot)
        # Bind the decision to the *entire* evaluated package, not just the
        # single installed module: an unsigned module dropped into the governed
        # package -- or into an enclosing package, whose rule heads can name
        # data.ocor.control_plane.* -- can silently extend the decision.
        modules = self._fetch_policy_modules(correlation_id)
        installed = self._installed_module(modules, snapshot.digest, correlation_id)
        governed_members: list[str] = []
        for item in modules:
            if item is installed:
                continue
            path = _policy_package_path(item)
            if not path or _GOVERNED_PACKAGE_PATH[: len(path)] == path:
                governed_members.append(str(item.get("id", "")))
        if governed_members:
            raise SecurityControlError(
                "STALE_BUNDLE",
                f"correlation_id={correlation_id} unsolicited modules extend the "
                f"governed package: {sorted(governed_members)}",
            )
        ast = installed.get("ast")
        rules = ast.get("rules") if isinstance(ast, dict) else None
        live = frozenset(_rule_fingerprint(rule) for rule in rules) if isinstance(
            rules, list) else frozenset()
        if live != snapshot.rules:
            raise SecurityControlError(
                "STALE_BUNDLE",
                f"correlation_id={correlation_id} compiled policy differs from the "
                "verified snapshot",
            )
        return snapshot

    def _require_bundle_window(
        self, correlation_id: str, snapshot: _VerifiedBundleSnapshot | None = None
    ) -> datetime:
        snapshot = snapshot if snapshot is not None else self._snapshot
        now = _now()
        if snapshot is None or now < snapshot.not_before or now >= snapshot.expires_at:
            raise SecurityControlError(
                "POLICY_BUNDLE_WINDOW_INVALID",
                f"correlation_id={correlation_id} installed policy bundle is outside its window",
            )
        return snapshot.expires_at

    def _require_evaluation_provenance(
        self, response: Mapping[str, object], snapshot: _VerifiedBundleSnapshot,
        correlation_id: str,
    ) -> None:
        """Bind the decision to the verified snapshot within the same response.

        OPA reports, alongside the result, every rule it entered to produce
        it.  Any rule outside the verified snapshot -- an injected module, a
        swapped module or an enclosing-package rule head -- means the result
        does not belong to the bundle the decision would name.
        """
        trace = response.get("explanation")
        if not isinstance(trace, list):
            raise SecurityControlError(
                "POLICY_DECISION_INVALID",
                f"correlation_id={correlation_id} policy evaluation provenance is missing",
            )
        decided = False
        for event in trace:
            if not isinstance(event, dict) or event.get("type") != "rule":
                continue
            node = event.get("node")
            if _rule_fingerprint(node) not in snapshot.rules:
                raise SecurityControlError(
                    "STALE_BUNDLE",
                    f"correlation_id={correlation_id} evaluated rule is not part of the "
                    "verified policy bundle",
                )
            if event.get("op") == "exit" and _rule_name(node) == "allow":
                decided = True
        if not decided:
            raise SecurityControlError(
                "POLICY_DECISION_INVALID",
                f"correlation_id={correlation_id} decision was not produced by the "
                "verified allow rule",
            )

    def _verify_grant_chain(
        self,
        request: PolicyRequest,
        grants: tuple[SignedDelegation, ...],
        capability: CapabilityInvocation | None,
        snapshot: _VerifiedBundleSnapshot,
        correlation_id: str,
    ) -> tuple[str, datetime]:
        """Verify a complete delegation chain at the boundary instant.

        ``actor_chain = (a0, a1, ..., an)`` with ``an`` the authenticated
        principal is delegated by ``grants = (g1, ..., gn)``: ``gi`` is signed
        by the pinned authority, links ``a(i-1) -> ai`` and its parent's
        content address, may follow ``g(i-1)`` only if that allowed
        redelegation, never widens it, and every grant intersects the
        requested capability, governed scope, purpose and policy bundle.  The
        last grant is confirmed to the workload key presented on mTLS.
        Returns the chain content address and its earliest expiry.
        """
        correlation = f"correlation_id={correlation_id}"
        if self._delegation_signer_key is None:
            raise SecurityControlError(
                "DELEGATION_BINDING_MISMATCH", f"{correlation} delegation authority is not configured"
            )
        if not grants:
            raise SecurityControlError("DELEGATION_INVALID", f"{correlation} grant chain is empty")
        if capability is None:
            raise SecurityControlError(
                "DELEGATION_INVALID", f"{correlation} delegated call declares no capability"
            )
        gcs = request.governed_context
        chain = tuple(gcs.actor_chain)
        principal_id = request.principal.principal_id
        if len(chain) != len(grants) + 1 or chain[-1] != principal_id:
            raise SecurityControlError(
                "DELEGATION_BINDING_MISMATCH",
                f"{correlation} actor_chain is not the delegation chain to the principal",
            )
        if gcs.policy_bundle_digest != snapshot.digest:
            raise SecurityControlError(
                "DELEGATION_POLICY_BINDING_MISMATCH", f"{correlation} policy pin differs"
            )
        key_thumbprint = workload_key_thumbprint(self._ssl_context)
        with self._lock:
            revoked = set(self._delegation_revocations)
        digests: list[str] = []
        instant = _now()
        for index, grant in enumerate(grants):
            if not isinstance(grant, SignedDelegation):
                raise SecurityControlError("DELEGATION_INVALID", f"{correlation} not a grant")
            digest = verify_delegation_signature(grant, self._delegation_signer_key)
            if grant.grant_id in revoked:
                raise SecurityControlError("DELEGATION_REVOKED", f"{correlation} grant is revoked")
            if (grant.grantor_principal, grant.grantee_principal) != (chain[index], chain[index + 1]):
                raise SecurityControlError(
                    "DELEGATION_BINDING_MISMATCH", f"{correlation} grant does not bind the actor chain"
                )
            if index == 0:
                if grant.parent_grant_digest is not None:
                    raise SecurityControlError(
                        "DELEGATION_CHAIN_INVALID", f"{correlation} root grant names a parent"
                    )
            else:
                self._require_narrowing(grants[index - 1], grant, digests[-1], correlation)
            if len(grants) - index > grant.max_chain_depth:
                raise SecurityControlError(
                    "DELEGATION_CHAIN_TOO_DEEP", f"{correlation} chain exceeds max_chain_depth"
                )
            if instant < _canonical_utc(grant.not_before) or instant >= _canonical_utc(
                    grant.expires_at):
                raise SecurityControlError(
                    "DELEGATION_EXPIRED", f"{correlation} delegation is outside its validity window"
                )
            self._require_grant_covers(request, grant, capability, snapshot, correlation)
            digests.append(digest)
        if grants[-1].confirmation_key_thumbprint != key_thumbprint:
            raise SecurityControlError(
                "DELEGATION_KEY_BINDING_MISMATCH",
                f"{correlation} grant is not confirmed to the presenting workload key",
            )
        with self._lock:
            for grant, digest in zip(grants, digests):
                if self._grant_nonces.get(grant.nonce, digest) != digest:
                    raise SecurityControlError(
                        "DELEGATION_REPLAY", f"{correlation} grant nonce was already used"
                    )
            if len({grant.nonce for grant in grants}) != len(grants):
                raise SecurityControlError(
                    "DELEGATION_REPLAY", f"{correlation} grant nonce repeats in the chain"
                )
            for grant, digest in zip(grants, digests):
                self._grant_nonces[grant.nonce] = digest
        expiry = min(_canonical_utc(grant.expires_at) for grant in grants)
        return _sha256_urn(":".join(digests).encode()), expiry

    @staticmethod
    def _require_narrowing(
        parent: SignedDelegation, child: SignedDelegation, parent_digest: str, correlation: str
    ) -> None:
        if child.parent_grant_digest != parent_digest:
            raise SecurityControlError(
                "DELEGATION_CHAIN_INVALID", f"{correlation} parent_grant_digest does not link"
            )
        if parent.redelegation_allowed is not True:
            raise SecurityControlError(
                "DELEGATION_REDELEGATION_FORBIDDEN", f"{correlation} parent forbids redelegation"
            )
        narrowed = (
            child.capability_id == parent.capability_id
            and child.capability_version == parent.capability_version
            and child.resource_scope == parent.resource_scope
            and child.tenant_id == parent.tenant_id
            and child.organization_id == parent.organization_id
            and child.policy_bundle_digest == parent.policy_bundle_digest
            and set(child.domains) <= set(parent.domains)
            and set(child.compartments) <= set(parent.compartments)
            and set(child.permitted_purposes) <= set(parent.permitted_purposes)
            and child.effect_ceiling <= parent.effect_ceiling
            and child.risk_ceiling <= parent.risk_ceiling
            and child.max_chain_depth < parent.max_chain_depth
            and _canonical_utc(child.not_before) >= _canonical_utc(parent.not_before)
            and _canonical_utc(child.expires_at) <= _canonical_utc(parent.expires_at)
        )
        if not narrowed:
            raise SecurityControlError(
                "DELEGATION_AMPLIFICATION", f"{correlation} grant widens its parent"
            )

    @staticmethod
    def _require_grant_covers(
        request: PolicyRequest,
        grant: SignedDelegation,
        capability: CapabilityInvocation,
        snapshot: _VerifiedBundleSnapshot,
        correlation: str,
    ) -> None:
        gcs = request.governed_context
        if (
            request.resource != grant.resource_scope
            or gcs.tenant_id != grant.tenant_id
            or gcs.organization_id != grant.organization_id
            or gcs.domain_id not in grant.domains
            or not set(gcs.compartments) <= set(grant.compartments)
        ):
            raise SecurityControlError(
                "DELEGATION_SCOPE_MISMATCH", f"{correlation} grant does not cover the governed scope"
            )
        if gcs.purpose not in grant.permitted_purposes:
            raise SecurityControlError(
                "DELEGATION_PURPOSE_MISMATCH", f"{correlation} grant does not cover the purpose"
            )
        if (capability.capability_id, capability.capability_version) != (
                grant.capability_id, grant.capability_version):
            raise SecurityControlError(
                "DELEGATION_CAPABILITY_MISMATCH", f"{correlation} grant does not cover the capability"
            )
        if (capability.effect_class > grant.effect_ceiling
                or capability.risk_class > grant.risk_ceiling):
            raise SecurityControlError(
                "DELEGATION_CEILING_EXCEEDED", f"{correlation} call exceeds the grant ceilings"
            )
        if grant.policy_bundle_digest != snapshot.digest:
            raise SecurityControlError(
                "DELEGATION_POLICY_BINDING_MISMATCH",
                f"{correlation} grant is bound to another policy bundle",
            )

    def evaluate(
        self,
        request: PolicyRequest,
        *,
        delegation: SignedDelegation | Sequence[SignedDelegation] | None = None,
        capability: CapabilityInvocation | None = None,
    ) -> PolicyDecision:
        correlation_id = request.governed_context.correlation_id
        # LLD v1.1 §1.1: a received digest is recomputed before policy.
        if request.governed_context.digest() != request.governed_context_digest:
            raise SecurityControlError(
                "GOVERNED_CONTEXT_MISMATCH", f"correlation_id={correlation_id} GCS digest differs"
            )
        request.principal.require_valid(at=_now())
        _mtls_deadline(self._ssl_context)
        # One immutable snapshot for the whole decision: a concurrent install
        # cannot change which bundle this decision is checked against.
        snapshot = self._require_fresh_bundle(correlation_id)
        # Binding 1: the governed context's policy pin must equal the digest of
        # the bundle actually installed and verified, not a caller-declared value.
        if request.governed_context.policy_bundle_digest != snapshot.digest:
            raise SecurityControlError(
                "STALE_BUNDLE",
                f"correlation_id={correlation_id} governed policy pin does not match "
                "the installed bundle",
            )
        # Binding 2: the governed actor_chain is compared exactly, never as a
        # set.  Authenticated actors (a signed OIDC ``act`` claim) prove who
        # acts; they never replace the grant.  Any request with more than one
        # actor -- declared in the governed context or authenticated on the
        # token -- is delegated and is accepted only with the complete signed
        # grant chain, whose tail must be exactly the authenticated actors.
        chain = tuple(request.governed_context.actor_chain)
        authenticated = tuple(request.principal.actor_chain)
        principal_id = request.principal.principal_id
        if request.governed_context.effective_principal_id != principal_id:
            raise SecurityControlError(
                "PRINCIPAL_BINDING_MISMATCH",
                f"correlation_id={correlation_id} authenticated principal differs from GCS",
            )
        grants: tuple[SignedDelegation, ...] = ()
        chain_digest: str | None = None
        if delegation is None:
            if authenticated != (principal_id,):
                raise SecurityControlError(
                    "DELEGATION_REQUIRED",
                    f"correlation_id={correlation_id} authenticated actors require the "
                    "signed delegation grant chain",
                )
            if chain != (principal_id,):
                raise SecurityControlError(
                    "IDENTITY_BINDING_MISMATCH",
                    f"correlation_id={correlation_id} actor_chain is not bound to the "
                    "authenticated principal",
                )
        else:
            if (len(authenticated) > len(chain)
                    or chain[len(chain) - len(authenticated):] != authenticated):
                raise SecurityControlError(
                    "IDENTITY_BINDING_MISMATCH",
                    f"correlation_id={correlation_id} actor_chain omits or reorders the "
                    "authenticated actors",
                )
            grants = (delegation,) if isinstance(delegation, SignedDelegation) else tuple(
                delegation)
            chain_digest, _ = self._verify_grant_chain(
                request, grants, capability, snapshot, correlation_id
            )
        gcs = request.governed_context
        policy_input = {
            "tenant_id": gcs.tenant_id,
            "organization_id": gcs.organization_id,
            "domain_id": gcs.domain_id,
            "compartments": list(gcs.compartments),
            "classification_marking_ref": gcs.classification_marking_ref,
            "purpose": gcs.purpose,
            "effective_principal_id": gcs.effective_principal_id,
            "principal_id": request.principal.principal_id,
            "actor_chain": list(gcs.actor_chain),
            "ontology_release_digest": gcs.ontology_release_digest,
            "policy_bundle_digest": gcs.policy_bundle_digest,
            "correlation_id": correlation_id,
            "action": request.action,
            "resource": request.resource,
            "capability": None if capability is None else capability.to_policy_input(),
            "delegation_grant_ids": [grant.grant_id for grant in grants],
        }
        status, body = _request(
            "POST",
            f"{self._base_url}{self._ALLOW_PATH}?explain=full",
            data=json.dumps({"input": policy_input}).encode(),
            headers={"Content-Type": "application/json"},
            timeout=self._timeout,
            correlation_id=correlation_id,
            ssl_context=self._ssl_context,
        )
        if status != 200:
            raise SecurityControlError(
                "POLICY_UNAVAILABLE",
                f"correlation_id={correlation_id} policy eval HTTP {status}",
            )
        try:
            response = json.loads(body.decode())
        except (ValueError, json.JSONDecodeError) as exc:
            raise SecurityControlError(
                "POLICY_DECISION_INVALID",
                f"correlation_id={correlation_id} malformed policy response",
            ) from exc
        if not isinstance(response, dict):
            raise SecurityControlError(
                "POLICY_DECISION_INVALID",
                f"correlation_id={correlation_id} malformed policy response",
            )
        raw_result = response.get("result")
        # A non-boolean decision (a string, an array, an object) is rejected,
        # never coerced through truthiness into a permit.
        if not isinstance(raw_result, bool):
            raise SecurityControlError(
                "POLICY_DECISION_INVALID",
                f"correlation_id={correlation_id} policy result is not boolean",
            )
        self._require_evaluation_provenance(response, snapshot, correlation_id)
        # Revalidate after backend I/O: a module can drift, a grant can be
        # revoked and an authority can expire while OPA is answering.
        self._require_fresh_bundle(correlation_id, snapshot)
        effect: PolicyEffect = PolicyEffect.DENY
        obligations: tuple[str, ...] = ()
        if raw_result:
            effect, obligations = self._qualify(policy_input, snapshot, correlation_id)
        now = _now()
        request.principal.require_valid(at=now)
        valid_until = min(now + timedelta(seconds=300), request.principal.expires_at,
                          self._require_bundle_window(correlation_id, snapshot),
                          _mtls_deadline(self._ssl_context))
        if grants:
            chain_digest, chain_expiry = self._verify_grant_chain(
                request, grants, capability, snapshot, correlation_id
            )
            valid_until = min(valid_until, chain_expiry)
        status_record = ControlStatus.available(
            ControlName.POLICY,
            observed_at=now,
            source_digest=snapshot.digest,
        )
        decision_id = _sha256_urn(
            f"{snapshot.snapshot_digest()}:{request.governed_context_digest}:"
            f"{chain_digest or '-'}:{request.principal.principal_id}:{request.action}:"
            f"{request.resource}:{now.isoformat()}".encode()
        )
        return PolicyDecision.from_request(
            replace(request, at=now),
            effect=effect,
            decision_id=decision_id,
            valid_until=valid_until,
            obligations=obligations,
            status=status_record,
        )

    def _qualify(
        self, policy_input: Mapping[str, object], snapshot: _VerifiedBundleSnapshot, correlation_id: str
    ) -> tuple[PolicyEffect, tuple[str, ...]]:
        """The effect of a permitted request (ADD v1.3 :3141, Register FR-130; OCOR-DEV-REM-0054,
        NCR-C6-011).

        The signed bundle qualifies a permit through the set rules ``constraints``
        (``PERMIT_WITH_CONSTRAINTS``), ``approval_requirements`` (``REQUIRE_APPROVAL``) and
        ``obligations`` (``OBLIGATE``) of the governed package. A bundle that defines none of them
        permits without qualification. Otherwise the package document is evaluated once more on the
        same input, bound to the same verified snapshot: it must still permit, every qualifier must
        be an array of distinct non-empty strings, and at most one may be non-empty -- the norm
        defines no combination of effects, so an ambiguous qualification is no decision.
        """
        correlation = f"correlation_id={correlation_id}"
        defined = {_rule_head_name(json.loads(rule)) for rule in snapshot.rules}
        if defined.isdisjoint(_QUALIFIERS):
            return PolicyEffect.PERMIT, ()
        status, body = _request(
            "POST",
            f"{self._base_url}{self._PACKAGE_PATH}?explain=full",
            data=json.dumps({"input": policy_input}).encode(),
            headers={"Content-Type": "application/json"},
            timeout=self._timeout,
            correlation_id=correlation_id,
            ssl_context=self._ssl_context,
        )
        if status != 200:
            raise SecurityControlError("POLICY_UNAVAILABLE", f"{correlation} policy qualification HTTP {status}")
        try:
            response = json.loads(body.decode())
        except (ValueError, UnicodeDecodeError) as exc:
            raise SecurityControlError("POLICY_DECISION_INVALID", f"{correlation} malformed policy qualification") from exc
        if not isinstance(response, dict) or not isinstance(response.get("result"), dict):
            raise SecurityControlError("POLICY_DECISION_INVALID", f"{correlation} malformed policy qualification")
        self._require_evaluation_provenance(response, snapshot, correlation_id)
        self._require_fresh_bundle(correlation_id, snapshot)
        document = response["result"]
        if document.get("allow") is not True:
            raise SecurityControlError(
                "POLICY_DECISION_INVALID", f"{correlation} the qualification does not confirm the permit"
            )
        qualified: list[tuple[PolicyEffect, tuple[str, ...]]] = []
        for rule, effect in _QUALIFIERS.items():
            value = document.get(rule, [])
            if (
                not isinstance(value, list)
                or any(not isinstance(item, str) or not item for item in value)
                or len(set(value)) != len(value)
            ):
                raise SecurityControlError(
                    "POLICY_DECISION_INVALID", f"{correlation} {rule} is not a set of non-empty strings"
                )
            if value:
                qualified.append((effect, tuple(sorted(value))))
        if len(qualified) > 1:
            raise SecurityControlError(
                "POLICY_DECISION_INVALID", f"{correlation} the policy qualifies the permit with more than one effect"
            )
        return qualified[0] if qualified else (PolicyEffect.PERMIT, ())


class SpireWorkloadIdentityProvider:
    """Fetches and cryptographically verifies the control-plane SVID from SPIRE."""

    def __init__(
        self,
        *,
        agent_container: str,
        socket_path: str,
        expected_spiffe_id: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._agent_container = agent_container
        self._socket_path = socket_path
        self._expected_spiffe_id = expected_spiffe_id
        self._timeout = timeout_seconds

    def _fetch_svid(self) -> dict[str, object]:
        command = [
            "docker",
            "exec",
            self._agent_container,
            "/opt/spire/bin/spire-agent",
            "api",
            "fetch",
            "x509",
            "-socketPath",
            self._socket_path,
            "-output",
            "json",
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, timeout=self._timeout, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SecurityControlError("WORKLOAD_IDENTITY_UNAVAILABLE", str(exc)) from exc
        if completed.returncode != 0:
            raise SecurityControlError(
                "WORKLOAD_IDENTITY_UNAVAILABLE", "spire-agent api fetch failed"
            )
        data = json.loads(completed.stdout.decode())
        svids = data.get("svids")
        if not isinstance(svids, list) or not svids:
            raise SecurityControlError("WORKLOAD_IDENTITY_UNAVAILABLE", "no SVID returned")
        selected = next((item for item in svids
                         if item.get("spiffe_id") == self._expected_spiffe_id), svids[0])
        return cast(dict[str, object], selected)

    def current(self) -> WorkloadIdentity:
        svid = self._fetch_svid()
        spiffe_id = str(svid.get("spiffe_id", ""))
        if spiffe_id != self._expected_spiffe_id:
            raise SecurityControlError(
                "WORKLOAD_IDENTITY_UNAVAILABLE",
                f"unexpected SPIFFE ID {spiffe_id!r}",
            )
        try:
            chain = _split_der_chain(_b64_decode(str(svid["x509_svid"])))
            bundle = _b64_decode(str(svid["bundle"]))
        except (KeyError, ValueError) as exc:
            raise SecurityControlError("WORKLOAD_IDENTITY_UNAVAILABLE", "malformed SVID") from exc
        if len(chain) < 2:
            raise SecurityControlError("WORKLOAD_IDENTITY_UNAVAILABLE", "incomplete SVID chain")
        leaf_der, intermediate_der = chain[0], chain[1]
        root_der = bundle

        leaf = _parse_certificate(leaf_der)
        intermediate = _parse_certificate(intermediate_der)
        root = _parse_certificate(root_der)
        _verify_certificate_signature(leaf, intermediate)
        _verify_certificate_signature(intermediate, root)

        uri_sans = leaf["uri_sans"]
        assert isinstance(uri_sans, list)
        if spiffe_id not in uri_sans:
            raise SecurityControlError(
                "WORKLOAD_IDENTITY_UNAVAILABLE", "SVID SAN does not carry the SPIFFE ID"
            )
        certificates = [_parse_certificate(der) for der in chain] + [root]
        for child, issuer in zip(certificates, certificates[1:]):
            _verify_certificate_signature(child, issuer)
        not_before, expires_at = _certificate_window(certificates)
        trust_bundle_digest = _sha256_urn(root_der)
        svid_ref = _sha256_urn(leaf_der)
        status = ControlStatus.available(
            ControlName.WORKLOAD_IDENTITY,
            observed_at=_now(),
            source_digest=trust_bundle_digest,
        )
        identity = WorkloadIdentity(
            spiffe_id=spiffe_id,
            svid_ref=svid_ref,
            trust_bundle_digest=trust_bundle_digest,
            attested=True,
            not_before=not_before,
            expires_at=expires_at,
            status=status,
        )
        return identity.require_valid(at=_now())

    def mtls_context(self) -> ssl.SSLContext:
        """Build a mutual-TLS client context from the live SPIRE SVID.

        The context presents the workload SVID as the client certificate and
        verifies the peer against the SPIRE trust bundle (``CERT_REQUIRED``).
        Hostname matching is disabled: SPIFFE peer identity is URI-SAN based and
        is already attested at fetch time; trust is anchored to the pinned
        bundle digest, not to DNS names.
        """
        svid = self._fetch_svid()
        spiffe_id = str(svid.get("spiffe_id", ""))
        if spiffe_id != self._expected_spiffe_id:
            raise SecurityControlError(
                "WORKLOAD_IDENTITY_UNAVAILABLE",
                f"unexpected SPIFFE ID {spiffe_id!r}",
            )
        try:
            chain = _split_der_chain(_b64_decode(str(svid["x509_svid"])))
            key_der = _b64_decode(str(svid["x509_svid_key"]))
            bundle_der = _b64_decode(str(svid["bundle"]))
        except (KeyError, ValueError) as exc:
            raise SecurityControlError(
                "WORKLOAD_IDENTITY_UNAVAILABLE", "malformed SVID material"
            ) from exc
        if len(chain) < 2:
            raise SecurityControlError(
                "WORKLOAD_IDENTITY_UNAVAILABLE", "incomplete SVID chain"
            )
        if not key_der:
            raise SecurityControlError(
                "WORKLOAD_IDENTITY_UNAVAILABLE", "SVID private key is missing"
            )
        certificates = [_parse_certificate(der) for der in chain + [bundle_der]]
        for child, issuer in zip(certificates, certificates[1:]):
            _verify_certificate_signature(child, issuer)
        if spiffe_id not in cast(list[str], certificates[0]["uri_sans"]):
            raise SecurityControlError("WORKLOAD_IDENTITY_UNAVAILABLE", "SVID SAN mismatch")
        window = _certificate_window(certificates)

        cert_pem = "".join(_der_to_pem(der, "CERTIFICATE") for der in chain)
        key_pem = _der_to_pem(key_der, "PRIVATE KEY")
        bundle_pem = _der_to_pem(bundle_der, "CERTIFICATE")

        context = _PeerIdentitySSLContext(self._expected_spiffe_id)
        context._identity_window = window
        context._identity_key_thumbprint = _sha256_urn(
            cast(bytes, certificates[0]["spki_der"])
        )
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = False
        context.load_verify_locations(cadata=bundle_pem)
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, "svid.pem")
            key_path = os.path.join(tmpdir, "svid.key")
            with open(cert_path, "w") as handle:
                handle.write(cert_pem)
            with open(key_path, "w") as handle:
                handle.write(key_pem)
            os.chmod(key_path, 0o600)
            context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        return context


class OpenBaoSecretProvider:
    """Leases principal-scoped secrets from a real OpenBao kv-v2 engine."""

    def __init__(
        self,
        base_url: str,
        token: str,
        mount: str = "ocor",
        *,
        timeout_seconds: float = 5.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._mount = mount
        if not _VAULT_PATH_SEGMENT.fullmatch(self._mount):
            raise SecurityControlError(
                "SECRET_REFERENCE_INVALID", f"invalid mount name {self._mount!r}"
            )
        self._timeout = timeout_seconds
        self._ssl_context = _require_mtls_context(ssl_context)
        self._mount_digest: str | None = None

    def _headers(self) -> dict[str, str]:
        return {"X-Vault-Token": self._token}

    def _token_deadline(self) -> datetime | None:
        status, body = _request(
            "GET", f"{self._base_url}/v1/auth/token/lookup-self",
            headers=self._headers(), timeout=self._timeout, ssl_context=self._ssl_context,
        )
        if status != 200:
            raise SecurityControlError("SECRETS_UNAVAILABLE", f"token lookup HTTP {status}")
        try:
            data = json.loads(body)["data"]
            value = data["expire_time"]
            if value is None and data["ttl"] == 0:
                return None  # backend-confirmed non-expiring bootstrap token
            expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if expiry.tzinfo is None or expiry.utcoffset() is None or _now() >= expiry:
                raise ValueError("expired or invalid token window")
            return expiry
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise SecurityControlError("SECRETS_UNAVAILABLE", "invalid token expiry") from exc

    def _ensure_mount(self) -> str:
        status, body = _request(
            "GET",
            f"{self._base_url}/v1/sys/mounts",
            headers=self._headers(),
            timeout=self._timeout,
            ssl_context=self._ssl_context,
        )
        if status != 200:
            raise SecurityControlError("SECRETS_UNAVAILABLE", f"mount list HTTP {status}")
        mounts = json.loads(body.decode()).get("data", {})
        mount_key = f"{self._mount}/"
        accessor = mounts.get(mount_key, {}).get("accessor") if isinstance(mounts, dict) else None
        if accessor is None:
            status, body = _request(
                "POST",
                f"{self._base_url}/v1/sys/mounts/{self._mount}",
                data=json.dumps({"type": "kv", "options": {"version": "2"}}).encode(),
                headers={**self._headers(), "Content-Type": "application/json"},
                timeout=self._timeout,
                ssl_context=self._ssl_context,
            )
            if status not in (200, 204):
                raise SecurityControlError("SECRETS_UNAVAILABLE", f"mount enable HTTP {status}")
            status, body = _request(
                "GET",
                f"{self._base_url}/v1/sys/mounts",
                headers=self._headers(),
                timeout=self._timeout,
                ssl_context=self._ssl_context,
            )
            mounts = json.loads(body.decode()).get("data", {})
            accessor = mounts.get(mount_key, {}).get("accessor") if isinstance(mounts, dict) else None
        if accessor is None:
            raise SecurityControlError("SECRETS_UNAVAILABLE", "mount accessor not found")
        self._mount_digest = _sha256_urn(str(accessor).encode())
        return self._mount_digest

    def lease(
        self, request: SecretRequest, *, principal: AuthenticatedPrincipal | None = None
    ) -> SecretLease:
        started_at = _now()
        # Secret isolation: the kv-v2 prefix is the authenticated principal's
        # own, never a principal id the caller merely declares.
        if not isinstance(principal, AuthenticatedPrincipal):
            raise SecurityControlError(
                "SECRET_BINDING_MISMATCH", "a secret lease requires the authenticated principal"
            )
        if request.principal_id != principal.principal_id:
            raise SecurityControlError(
                "SECRET_BINDING_MISMATCH", "secret request is not bound to the authenticated principal"
            )
        # A session whose token names other actors is delegated: the lease
        # port carries no grant chain, so a delegated session never leases.
        if tuple(principal.actor_chain) != (principal.principal_id,):
            raise SecurityControlError(
                "DELEGATION_REQUIRED", "a delegated session cannot lease without a verified grant"
            )
        # Transport authority first (an expired SVID is reported as such),
        # then the principal's own window; any other context is refused by
        # the HTTPS/mTLS I/O boundary before a socket is opened.
        if isinstance(self._ssl_context, _PeerIdentitySSLContext):
            self._ssl_context.require_current_identity()
        principal.require_valid(at=started_at)
        mount_digest = self._mount_digest or self._ensure_mount()
        secret_name = request.secret_ref[len("urn:ocor:secret-ref:") :]
        if not secret_name:
            raise SecurityControlError("SECRET_REFERENCE_INVALID", "empty secret reference")
        # ``secret_ref`` and ``principal_id`` are interpolated into an OpenBao
        # kv-v2 path.  Both are restricted to a single path segment (no slash,
        # no dot-prefix, no traversal) so a crafted reference cannot reach
        # outside the principal's scope or a foreign mount.
        if not _VAULT_PATH_SEGMENT.fullmatch(secret_name):
            raise SecurityControlError(
                "SECRET_REFERENCE_INVALID", f"invalid secret reference {request.secret_ref!r}"
            )
        if not _VAULT_PATH_SEGMENT.fullmatch(request.principal_id):
            raise SecurityControlError(
                "SECRET_REFERENCE_INVALID", f"invalid principal id {request.principal_id!r}"
            )
        correlation = f"governed_context_digest={request.governed_context_digest}"
        # Resolve-not-overwrite: a lease is always derived from a secret that
        # already exists under the principal's scope.  The provider never
        # writes material for a lease; an absent reference is an outright
        # denial, never an implicit provisioning.
        path = f"{self._mount}/data/{request.principal_id}/{secret_name}"
        status, body = _request(
            "GET",
            f"{self._base_url}/v1/{path}",
            headers=self._headers(),
            timeout=self._timeout,
            correlation_id=correlation,
            ssl_context=self._ssl_context,
        )
        if status == 404:
            raise SecurityControlError(
                "SECRET_REFERENCE_UNRESOLVED",
                f"{correlation} no secret material at reference {request.secret_ref}",
            )
        if status != 200:
            raise SecurityControlError("SECRETS_UNAVAILABLE", f"secret read HTTP {status}")
        try:
            payload = json.loads(body.decode())
            secret_data = payload["data"]["data"]
            metadata = payload["data"]["metadata"]
            version = str(metadata.get("version", "1"))
        except (ValueError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SecurityControlError(
                "SECRETS_UNAVAILABLE", "malformed secret read response"
            ) from exc
        # The opaque handle is bound to the actual secret content and version,
        # never to caller-supplied material.
        content_digest = _sha256_urn(
            json.dumps(secret_data, sort_keys=True, separators=(",", ":")).encode()
        )
        handle = _sha256_urn(
            f"{request.principal_id}:{secret_name}:{request.purpose}:"
            f"{version}:{content_digest}".encode()
        )
        handle_ref = "urn:ocor:secret-handle:" + handle[len("urn:sha256:") :]
        token_deadline = self._token_deadline()
        now = _now()
        expires_at = min(now + timedelta(seconds=300), _mtls_deadline(self._ssl_context),
                         principal.expires_at)
        if token_deadline is not None:
            expires_at = min(expires_at, token_deadline)
        try:
            duration = payload.get("lease_duration", 0)
            if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
                raise ValueError("invalid backend lease duration")
            if duration:
                expires_at = min(expires_at, started_at + timedelta(seconds=duration))
            deletion_time = metadata.get("deletion_time")
            if deletion_time:
                deletion_at = datetime.fromisoformat(deletion_time.replace("Z", "+00:00"))
                if deletion_at.tzinfo is None or deletion_at.utcoffset() is None:
                    raise ValueError("invalid deletion time")
                expires_at = min(expires_at, deletion_at)
        except (TypeError, AttributeError, ValueError) as exc:
            raise SecurityControlError("SECRETS_UNAVAILABLE", "invalid secret validity") from exc
        principal.require_valid(at=_now())
        if _now() >= expires_at:
            raise SecurityControlError("SECRET_LEASE_EXPIRED", "authority expired during secret read")
        status_record = ControlStatus.available(
            ControlName.SECRETS,
            observed_at=now,
            source_digest=mount_digest,
        )
        return SecretLease.from_request(
            replace(request, requested_at=now),
            handle_ref=handle_ref,
            version=version,
            expires_at=expires_at,
            status=status_record,
        )
