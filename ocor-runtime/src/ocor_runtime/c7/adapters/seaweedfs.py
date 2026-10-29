"""Direct SeaweedFS S3 client adapter for the C7 sealed-result subset.

OCOR-DEV-REM-0040 (PO OCOR-DEV-0060-BA-SELECTED-COMPONENTS, change set c;
REM-0040-C7-SEALED-RESULT-PORT-DISPOSITION (2026-10-28), option 1): SeaweedFS is the
S3-compatible content-addressed store of ``C7`` (ADD v1.3 Part I §2.6, ``BA-06``),
behind ``ocor_runtime.c7.sealed_results.ScenarioOverlayStoreSealSubset``. Every call
to the server is confined to this module (AFF-002/AFF-006, ``OCOR_LANGUAGE_POLICY.md``
row 8). Requests are signed with AWS Signature Version 4 on the standard library
only, like ``deploy/bootstrap/services/seaweedfs/qualify.py``: no new dependency.

- The object key derives from ``reproducibility_digest``; the object is the exact
  canonical preimage of that digest, checked against ``c7.runtime.canonical_digest``
  before every write and recomputed on every read.
- The bucket must have Object Lock (hence versioning) enabled, otherwise
  ``initialize`` refuses it. Each sealed version is written with a ``COMPLIANCE``
  retention, which no principal can shorten or bypass (a ``GOVERNANCE`` retention
  could be bypassed by a privileged caller), and the applied mode is read back.
- The application path only issues ``GET`` and ``PUT`` (``ALLOWED_METHODS``): there is
  no delete and no retention-bypass header.
- The sealed version is the oldest version of the key. A later version (an
  overwrite) or a delete marker never replaces or hides it; a sealed version whose
  content does not match the digest is rejected, never returned.
- Sealing an identical result again is idempotent and writes no version; a write
  uses ``If-None-Match: *`` so a concurrent identical seal re-reads instead of
  writing twice. A different content under the same digest is rejected.

The adapter never falls back to another store (DEC-201): an unreachable server
raises ``STORE_UNAVAILABLE``. No credential ever appears in a message or ``repr``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from ..runtime import CausalOutcome, canonical_digest
from ..sealed_results import SealedResult, SealedResultError

ALLOWED_METHODS = frozenset({"GET", "PUT"})
RETENTION_MODE = "COMPLIANCE"
KEY_PREFIX = "sealed-results/sha256/"
REGION = "us-east-1"
CONTROL_TIMEOUT = 10.0
# The first object write after a (re)start allocates SeaweedFS volumes (about 12 s
# measured by OCOR-DEV-REM-0038): the write path gets a bounded allowance.
WRITE_TIMEOUT = 30.0
DIGEST = re.compile(r"[0-9a-f]{64}")
BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
ENDPOINT = re.compile(r"https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?")
BODY_FIELDS = frozenset({"status", "reason_code", "method", "effect", "details", "assumptions", "lineage"})
S3_NAMESPACE = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def object_key(reproducibility_digest: str) -> str:
    """The content address of a sealed result."""
    if not isinstance(reproducibility_digest, str) or not DIGEST.fullmatch(reproducibility_digest):
        raise SealedResultError("INVALID_DIGEST", "a reproducibility digest is 64 lowercase hex characters")
    return KEY_PREFIX + reproducibility_digest


def _body(outcome: CausalOutcome) -> dict[str, Any]:
    return {
        "status": outcome.status,
        "reason_code": outcome.reason_code,
        "method": outcome.method,
        "effect": outcome.effect,
        "details": dict(outcome.details),
        "assumptions": list(outcome.assumptions),
        "lineage": dict(outcome.lineage),
    }


def _encode(body: Mapping[str, Any]) -> bytes:
    # The encoding of c7.runtime.canonical_digest; every caller checks the result
    # against that function, so the two can never diverge silently.
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sealed_payload(outcome: CausalOutcome) -> bytes:
    """The bytes sealed for ``outcome``: the canonical preimage of its digest."""
    body = _body(outcome)
    payload = _encode(body)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != canonical_digest(body) or digest != outcome.reproducibility_digest:
        raise SealedResultError("OUTCOME_DIGEST_MISMATCH", "the reproducibility digest is not the digest of the outcome content")
    return payload


def _decode(payload: bytes, reproducibility_digest: str) -> CausalOutcome:
    if hashlib.sha256(payload).hexdigest() != reproducibility_digest:
        raise SealedResultError("SEALED_RESULT_TAMPERED", "the sealed content does not match its digest")
    try:
        body = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SealedResultError("SEALED_RESULT_TAMPERED", "the sealed content is not canonical JSON") from exc
    if not isinstance(body, dict) or set(body) != BODY_FIELDS or _encode(body) != payload:
        raise SealedResultError("SEALED_RESULT_TAMPERED", "the sealed content is not a canonical causal outcome")
    if canonical_digest(body) != reproducibility_digest:
        raise SealedResultError("SEALED_RESULT_TAMPERED", "the sealed content does not match its digest")
    details, assumptions, lineage = body["details"], body["assumptions"], body["lineage"]
    if (
        not isinstance(body["status"], str)
        or not all(body[name] is None or isinstance(body[name], str) for name in ("reason_code", "method", "effect"))
        or not isinstance(details, dict)
        or not all(isinstance(value, str) for value in details.values())
        or not isinstance(assumptions, list)
        or not all(isinstance(value, str) for value in assumptions)
        or not isinstance(lineage, dict)
    ):
        raise SealedResultError("SEALED_RESULT_TAMPERED", "the sealed content does not have the causal outcome types")
    return CausalOutcome(
        status=body["status"],
        reason_code=body["reason_code"],
        method=body["method"],
        effect=body["effect"],
        details=details,
        assumptions=tuple(assumptions),
        lineage=lineage,
        reproducibility_digest=reproducibility_digest,
    )


def _error_code(text: str) -> str:
    match = re.search(r"<Code>([^<]+)</Code>", text)
    return match.group(1) if match else ""


class SeaweedFSSealedResultStore:
    """``ScenarioOverlayStoreSealSubset`` on a SeaweedFS bucket with S3 Object Lock."""

    def __init__(self, *, endpoint: str, bucket: str, access_key: str, secret_key: str, retention: timedelta) -> None:
        if not isinstance(endpoint, str) or not ENDPOINT.fullmatch(endpoint):
            raise SealedResultError("CONFIGURATION_INVALID", "endpoint must be http(s)://host[:port]")
        if not isinstance(bucket, str) or not BUCKET.fullmatch(bucket):
            raise SealedResultError("CONFIGURATION_INVALID", "bucket is not a valid S3 bucket name")
        if not isinstance(access_key, str) or not access_key:
            raise SealedResultError("CONFIGURATION_INVALID", "access_key is required")
        if not isinstance(secret_key, str) or not secret_key:
            raise SealedResultError("CONFIGURATION_INVALID", "secret_key is required")
        if not isinstance(retention, timedelta) or retention <= timedelta(0):
            raise SealedResultError("CONFIGURATION_INVALID", "retention must be a positive duration")
        self._endpoint = endpoint
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._retention = retention
        self._initialized = False

    def __repr__(self) -> str:
        return f"SeaweedFSSealedResultStore(endpoint={self._endpoint!r}, bucket={self._bucket!r})"

    # -- transport -------------------------------------------------------------------

    def _signed_headers(self, method: str, url: str, payload: bytes, headers: Mapping[str, str]) -> dict[str, str]:
        parts = urllib.parse.urlsplit(url)
        now = datetime.now(UTC)
        stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        signed = {name.lower(): str(value).strip() for name, value in headers.items()}
        signed.update({"host": parts.netloc, "x-amz-content-sha256": payload_sha256, "x-amz-date": stamp})
        query = sorted(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        canonical_query = "&".join(
            f"{urllib.parse.quote(name, safe='-_.~')}={urllib.parse.quote(value, safe='-_.~')}" for name, value in query
        )
        names = sorted(signed)
        canonical_request = "\n".join([
            method,
            urllib.parse.quote(parts.path or "/", safe="/-_.~"),
            canonical_query,
            "".join(f"{name}:{signed[name]}\n" for name in names),
            ";".join(names),
            payload_sha256,
        ])
        scope = f"{day}/{REGION}/s3/aws4_request"
        string_to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical_request.encode()).hexdigest()])
        key = ("AWS4" + self._secret_key).encode()
        for part in (day, REGION, "s3", "aws4_request"):
            key = hmac.new(key, part.encode(), hashlib.sha256).digest()
        signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        signed["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self._access_key}/{scope}, SignedHeaders={';'.join(names)}, Signature={signature}"
        )
        signed.pop("host")
        return signed

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: str = "",
        payload: bytes = b"",
        headers: Mapping[str, str] | None = None,
        timeout: float = CONTROL_TIMEOUT,
    ) -> tuple[int, dict[str, str], bytes]:
        if method not in ALLOWED_METHODS:
            raise SealedResultError("METHOD_FORBIDDEN", f"{method} is not on the application path")
        url = f"{self._endpoint}{urllib.parse.quote(path, safe='/-_.~')}" + (f"?{query}" if query else "")
        extra = dict(headers or {})
        if payload:
            extra["Content-MD5"] = base64.b64encode(hashlib.md5(payload, usedforsecurity=False).digest()).decode()
        prepared = urllib.request.Request(
            url,
            data=payload if method == "PUT" else None,
            method=method,
            headers=self._signed_headers(method, url, payload, extra),
        )
        try:
            with urllib.request.urlopen(prepared, timeout=timeout) as response:
                return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise SealedResultError("STORE_UNAVAILABLE", f"SeaweedFS endpoint {self._endpoint} unreachable ({type(exc).__name__})") from exc

    def _denied(self, status: int, text: str) -> SealedResultError | None:
        if status == 403:
            return SealedResultError("ACCESS_DENIED", f"SeaweedFS refused the request ({_error_code(text) or status})")
        return None

    # -- lifecycle -------------------------------------------------------------------

    def initialize(self) -> None:
        """Refuse a bucket that is missing, unreachable, without Object Lock or without
        versioning. Nothing is created: the bucket is provisioned out of band."""
        status, _, raw = self._request("GET", f"/{self._bucket}", query="object-lock=")
        text = raw.decode("utf-8", "replace")
        if (denied := self._denied(status, text)) is not None:
            raise denied
        if status == 404 and _error_code(text) == "NoSuchBucket":
            raise SealedResultError("BUCKET_NOT_FOUND", f"bucket {self._bucket} does not exist")
        if status != 200 or "<ObjectLockEnabled>Enabled</ObjectLockEnabled>" not in text:
            raise SealedResultError("BUCKET_OBJECT_LOCK_DISABLED", f"bucket {self._bucket} has no S3 Object Lock")
        status, _, raw = self._request("GET", f"/{self._bucket}", query="versioning=")
        text = raw.decode("utf-8", "replace")
        if (denied := self._denied(status, text)) is not None:
            raise denied
        if status != 200 or "<Status>Enabled</Status>" not in text:
            raise SealedResultError("BUCKET_VERSIONING_DISABLED", f"bucket {self._bucket} has no enabled versioning")
        self._initialized = True

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise SealedResultError("STORE_NOT_INITIALIZED", "initialize() must verify the bucket first")

    # -- sealed versions -------------------------------------------------------------

    def _sealed_version(self, key: str) -> str | None:
        """The oldest version of ``key`` (S3 lists versions newest first), ignoring
        delete markers; ``None`` when the key was never written."""
        query = "prefix=" + urllib.parse.quote(key, safe="") + "&versions="
        status, _, raw = self._request("GET", f"/{self._bucket}", query=query)
        text = raw.decode("utf-8", "replace")
        if (denied := self._denied(status, text)) is not None:
            raise denied
        if status != 200:
            raise SealedResultError("UNEXPECTED_RESPONSE", f"listing versions returned {status}")
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise SealedResultError("UNEXPECTED_RESPONSE", "listing versions returned invalid XML") from exc
        if (root.findtext(f"{S3_NAMESPACE}IsTruncated") or "false").strip().lower() != "false":
            raise SealedResultError("UNEXPECTED_RESPONSE", "listing versions of one key was truncated")
        versions = [
            element.findtext(f"{S3_NAMESPACE}VersionId") or ""
            for element in root.findall(f"{S3_NAMESPACE}Version")
            if element.findtext(f"{S3_NAMESPACE}Key") == key
        ]
        if not versions:
            return None
        if not versions[-1]:
            raise SealedResultError("UNEXPECTED_RESPONSE", "a listed version has no version id")
        return versions[-1]

    def _sealed_bytes(self, key: str) -> bytes | None:
        version = self._sealed_version(key)
        if version is None:
            return None
        status, _, raw = self._request("GET", f"/{self._bucket}/{key}", query="versionId=" + urllib.parse.quote(version, safe=""))
        if (denied := self._denied(status, raw.decode("utf-8", "replace"))) is not None:
            raise denied
        if status != 200:
            raise SealedResultError("UNEXPECTED_RESPONSE", f"reading the sealed version returned {status}")
        return raw

    def _settle(self, payload: bytes, existing: bytes, digest: str) -> SealedResult:
        if existing != payload:
            raise SealedResultError("SEALED_RESULT_CONFLICT", "a different content is already stored under this digest")
        return SealedResult(reproducibility_digest=digest, newly_sealed=False)

    # -- ScenarioOverlayStoreSealSubset ----------------------------------------------

    def seal_result(self, outcome: CausalOutcome) -> SealedResult:
        self._require_initialized()
        payload = sealed_payload(outcome)
        digest = outcome.reproducibility_digest
        key = object_key(digest)
        existing = self._sealed_bytes(key)
        if existing is not None:
            return self._settle(payload, existing, digest)
        retain_until = (datetime.now(UTC) + self._retention).strftime("%Y-%m-%dT%H:%M:%SZ")
        status, headers, raw = self._request(
            "PUT",
            f"/{self._bucket}/{key}",
            payload=payload,
            headers={
                "Content-Type": "application/json",
                "If-None-Match": "*",
                "x-amz-object-lock-mode": RETENTION_MODE,
                "x-amz-object-lock-retain-until-date": retain_until,
            },
            timeout=WRITE_TIMEOUT,
        )
        text = raw.decode("utf-8", "replace")
        if (denied := self._denied(status, text)) is not None:
            raise denied
        if status == 412:
            existing = self._sealed_bytes(key)
            if existing is None:
                raise SealedResultError("UNEXPECTED_RESPONSE", "conditional write refused but no sealed version exists")
            return self._settle(payload, existing, digest)
        version = headers.get("x-amz-version-id", "")
        if status != 200 or not version:
            raise SealedResultError("UNEXPECTED_RESPONSE", f"sealing returned {status} without a version")
        status, _, raw = self._request(
            "GET", f"/{self._bucket}/{key}", query="retention=&versionId=" + urllib.parse.quote(version, safe="")
        )
        if status != 200 or f"<Mode>{RETENTION_MODE}</Mode>" not in raw.decode("utf-8", "replace"):
            raise SealedResultError("RETENTION_NOT_APPLIED", f"the sealed version has no {RETENTION_MODE} retention")
        return SealedResult(reproducibility_digest=digest, newly_sealed=True)

    def read_sealed_result(self, reproducibility_digest: str) -> CausalOutcome:
        key = object_key(reproducibility_digest)
        self._require_initialized()
        payload = self._sealed_bytes(key)
        if payload is None:
            raise SealedResultError("SEALED_RESULT_NOT_FOUND", "no result is sealed under this digest")
        return _decode(payload, reproducibility_digest)
