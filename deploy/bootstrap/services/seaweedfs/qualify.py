#!/usr/bin/env python3
"""Fail-closed qualification for the digest-pinned local SeaweedFS S3 service.

SeaweedFS (OCOR-DEV-REM-0038, BA-06 candidate component) runs in single-node
``mini`` mode with only the S3 gateway published on loopback. Requests are
signed with AWS Signature Version 4 using the disposable credentials Docker
holds for the container; nothing is printed except typed observations.

``--execute`` adds the S3 Object Lock probe: it creates a uniquely named bucket
with Object Lock (which forces versioning), writes one object under a
COMPLIANCE retention and proves that deleting that version fails closed, with
and without the governance-bypass header. The probe never removes the locked
version or bucket: the storage is disposable tmpfs, released by teardown.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_CONTAINER = "ocor-bootstrap-seaweedfs-1"
DEFAULT_URL = "http://127.0.0.1:18333"
HOST = "127.0.0.1"
HOST_PORT = 18333
REGION = "us-east-1"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
DIGEST_IMAGE = re.compile(r"^chrislusf/seaweedfs@sha256:[0-9a-f]{64}$")
VERSION = re.compile(r"[0-9]+\.[0-9]+")
RETENTION_MODE = "COMPLIANCE"
# The first object write after a (re)start allocates volumes on tmpfs, measured
# at about 12 s on the qualification host; write-path requests get a bounded
# allowance instead of the 5 s control-plane timeout.
WRITE_TIMEOUT = 30.0


class QualificationError(RuntimeError):
    """A mandatory SeaweedFS qualification control failed."""


def validate_lock(lock: dict[str, Any]) -> dict[str, Any]:
    matches = [item for item in lock.get("services", []) if item.get("id") == "seaweedfs"]
    if len(matches) != 1:
        raise QualificationError("service lock must contain exactly one seaweedfs entry")
    entry: dict[str, Any] = matches[0]
    if not DIGEST_IMAGE.fullmatch(str(entry.get("image", ""))):
        raise QualificationError("SeaweedFS image is not digest-pinned")
    if entry.get("official_source") is not True:
        raise QualificationError("SeaweedFS artifact is not marked as an official source")
    if entry.get("source") != "https://hub.docker.com/r/chrislusf/seaweedfs":
        raise QualificationError("SeaweedFS source is not the approved official registry")
    if not VERSION.fullmatch(str(entry.get("version", ""))):
        raise QualificationError("SeaweedFS lock has no exact version")
    if entry.get("license") != "Apache-2.0":
        raise QualificationError("SeaweedFS license metadata mismatch")
    return entry


def validate_inspection(inspection: dict[str, Any], expected_image: str) -> dict[str, Any]:
    if inspection.get("Config", {}).get("Image") != expected_image:
        raise QualificationError("running SeaweedFS image differs from the exact service lock")
    state = inspection.get("State", {})
    if state.get("Running") is not True or state.get("Paused") is True:
        raise QualificationError("SeaweedFS container is not running")
    if state.get("Health", {}).get("Status") != "healthy":
        raise QualificationError("SeaweedFS container is not healthy")
    ports = inspection.get("NetworkSettings", {}).get("Ports", {}) or {}
    published = {key: value for key, value in ports.items() if value}
    if set(published) != {"8333/tcp"} or len(published["8333/tcp"]) != 1:
        raise QualificationError("SeaweedFS must publish exactly the S3 gateway port")
    binding = published["8333/tcp"][0]
    if binding.get("HostIp") != HOST:
        raise QualificationError("SeaweedFS S3 publication is not loopback-only")
    if str(binding.get("HostPort")) != str(HOST_PORT):
        raise QualificationError("SeaweedFS S3 host port differs from the approved profile")
    return {"health": "healthy", "ports": {"8333/tcp": str(HOST_PORT)}}


def credentials(inspection: dict[str, Any]) -> tuple[str, str]:
    environment: dict[str, str] = {}
    for item in inspection.get("Config", {}).get("Env", []):
        if isinstance(item, str) and "=" in item:
            key, _, value = item.partition("=")
            environment[key] = value
    access = environment.get("AWS_ACCESS_KEY_ID", "")
    secret = environment.get("AWS_SECRET_ACCESS_KEY", "")
    if not access or len(secret) < 24:
        raise QualificationError("disposable SeaweedFS credentials are absent or malformed")
    return access, secret


def sign(
    method: str,
    url: str,
    access_key: str,
    secret_key: str,
    *,
    now: datetime,
    payload_sha256: str = EMPTY_SHA256,
    headers: Mapping[str, str] | None = None,
    region: str = REGION,
) -> dict[str, str]:
    """Return the request headers carrying an AWS Signature Version 4."""
    parts = urllib.parse.urlsplit(url)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    signed = {key.lower(): str(value).strip() for key, value in (headers or {}).items()}
    signed.update({"host": parts.netloc, "x-amz-content-sha256": payload_sha256, "x-amz-date": stamp})
    query = sorted(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    canonical_query = "&".join(
        f"{urllib.parse.quote(key, safe='-_.~')}={urllib.parse.quote(value, safe='-_.~')}" for key, value in query
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
    scope = f"{day}/{region}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical_request.encode()).hexdigest()
    ])
    key = ("AWS4" + secret_key).encode()
    for part in (day, region, "s3", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    signed["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={';'.join(names)}, Signature={signature}"
    )
    return signed


def request(
    method: str,
    url: str,
    *,
    credential: tuple[str, str] | None,
    body: bytes = b"",
    headers: Mapping[str, str] | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict[str, str], str]:
    extra = dict(headers or {})
    if body:
        extra["Content-MD5"] = base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode()
    if credential is not None:
        extra = sign(
            method, url, credential[0], credential[1], now=datetime.now(UTC),
            payload_sha256=hashlib.sha256(body).hexdigest(), headers=extra,
        )
        extra.pop("host")
    prepared = urllib.request.Request(url, data=body if body or method == "PUT" else None, method=method, headers=extra)
    try:
        with urllib.request.urlopen(prepared, timeout=timeout) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read().decode()


def error_code(body: str) -> str:
    match = re.search(r"<Code>([^<]+)</Code>", body)
    return match.group(1) if match else ""


def validate_observations(
    *,
    health_status: int,
    unsigned_status: int,
    unsigned_body: str,
    wrong_secret_status: int,
    signed_status: int,
    version_output: str,
    expected_version: str,
) -> dict[str, Any]:
    if health_status != 200:
        raise QualificationError(f"SeaweedFS health endpoint returned {health_status}, expected 200")
    if unsigned_status != 403 or error_code(unsigned_body) != "AccessDenied":
        raise QualificationError("unsigned SeaweedFS S3 access did not fail closed")
    if wrong_secret_status != 403:
        raise QualificationError("SeaweedFS S3 access with a wrong secret did not fail closed")
    if signed_status != 200:
        raise QualificationError(f"signed SeaweedFS ListBuckets returned {signed_status}, expected 200")
    if re.search(rf"(?<![0-9.]){re.escape(expected_version)}(?![0-9.])", version_output) is None:
        raise QualificationError("SeaweedFS binary version does not match the lock")
    return {
        "health_status": health_status,
        "version": expected_version,
        "unsigned_access": "FAIL_CLOSED",
        "wrong_secret_access": "FAIL_CLOSED",
        "signed_list_buckets": "PASS",
    }


def validate_object_lock(observed: Mapping[str, Any]) -> dict[str, Any]:
    if observed["create_status"] != 200:
        raise QualificationError("Object Lock bucket creation failed")
    if "<Status>Enabled</Status>" not in observed["versioning_body"]:
        raise QualificationError("Object Lock bucket has no enabled versioning")
    if "<ObjectLockEnabled>Enabled</ObjectLockEnabled>" not in observed["lock_body"]:
        raise QualificationError("bucket Object Lock configuration is not enabled")
    if observed["put_status"] != 200 or not observed["version_id"]:
        raise QualificationError("retained object write returned no version")
    if f"<Mode>{RETENTION_MODE}</Mode>" not in observed["retention_body"]:
        raise QualificationError("object retention mode was not applied")
    if observed["delete_status"] != 403:
        raise QualificationError("deleting a retained object version did not fail closed")
    if observed["bypass_delete_status"] != 403:
        raise QualificationError("governance bypass deleted a COMPLIANCE-retained version")
    if observed["read_status"] != 200 or observed["read_body"] != observed["payload"]:
        raise QualificationError("retained object version is not intact after the denied deletes")
    return {
        "bucket_versioning": "Enabled",
        "bucket_object_lock": "Enabled",
        "retention_mode": RETENTION_MODE,
        "retained_version_delete": "FAIL_CLOSED",
        "retained_version_bypass_delete": "FAIL_CLOSED",
        "retained_version_intact": True,
    }


def object_lock_probe(base_url: str, credential: tuple[str, str]) -> dict[str, Any]:
    bucket = f"ocor-qualify-{uuid.uuid4().hex[:12]}"
    payload = f"ocor-object-lock-probe {bucket}"
    until = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    create_status, _, _ = request(
        "PUT", f"{base_url}/{bucket}", credential=credential,
        headers={"x-amz-bucket-object-lock-enabled": "true"},
    )
    _, _, versioning_body = request("GET", f"{base_url}/{bucket}?versioning", credential=credential)
    _, _, lock_body = request("GET", f"{base_url}/{bucket}?object-lock", credential=credential)
    put_status, put_headers, _ = request(
        "PUT", f"{base_url}/{bucket}/probe", credential=credential, body=payload.encode(),
        headers={"x-amz-object-lock-mode": RETENTION_MODE, "x-amz-object-lock-retain-until-date": until},
        timeout=WRITE_TIMEOUT,
    )
    version_id = put_headers.get("x-amz-version-id", "")
    version = urllib.parse.quote(version_id, safe="")
    _, _, retention_body = request(
        "GET", f"{base_url}/{bucket}/probe?retention&versionId={version}", credential=credential
    )
    delete_status, _, _ = request("DELETE", f"{base_url}/{bucket}/probe?versionId={version}", credential=credential)
    bypass_delete_status, _, _ = request(
        "DELETE", f"{base_url}/{bucket}/probe?versionId={version}", credential=credential,
        headers={"x-amz-bypass-governance-retention": "true"},
    )
    read_status, _, read_body = request("GET", f"{base_url}/{bucket}/probe?versionId={version}", credential=credential)
    result = validate_object_lock({
        "create_status": create_status, "versioning_body": versioning_body, "lock_body": lock_body,
        "put_status": put_status, "version_id": version_id, "retention_body": retention_body,
        "delete_status": delete_status, "bypass_delete_status": bypass_delete_status,
        "read_status": read_status, "read_body": read_body, "payload": payload,
    })
    return {"bucket": bucket, **result}


def run(command: Sequence[str], timeout: float = 20.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(list(command), check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError(f"bounded command failed: {command[0]}") from exc


def inspect_container(container: str) -> dict[str, Any]:
    completed = run(["docker", "inspect", container])
    if completed.returncode:
        raise QualificationError(f"container not found: {container}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError("docker inspect returned invalid JSON") from exc
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise QualificationError("docker inspect returned an unexpected container set")
    result: dict[str, Any] = payload[0]
    return result


def probe(container: str, base_url: str, credential: tuple[str, str], expected_version: str) -> dict[str, Any]:
    try:
        health_status, _, _ = request("GET", f"{base_url}/healthz", credential=None)
        unsigned_status, _, unsigned_body = request("GET", f"{base_url}/", credential=None)
        wrong_status, _, _ = request("GET", f"{base_url}/", credential=(credential[0], "ocor-deliberately-wrong-secret"))
        signed_status, _, _ = request("GET", f"{base_url}/", credential=credential)
    except (OSError, urllib.error.URLError) as exc:
        raise QualificationError(f"SeaweedFS S3 gateway is unavailable: {exc}") from exc
    version = run(["docker", "exec", container, "weed", "version"])
    return validate_observations(
        health_status=health_status, unsigned_status=unsigned_status, unsigned_body=unsigned_body,
        wrong_secret_status=wrong_status, signed_status=signed_status,
        version_output=version.stdout if version.returncode == 0 else "", expected_version=expected_version,
    )


def wait_ready(container: str, base_url: str, expected_image: str, expected_version: str, *, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            inspection = inspect_container(container)
            runtime = validate_inspection(inspection, expected_image)
            return {"runtime": runtime, "protocol": probe(container, base_url, credentials(inspection), expected_version)}
        except QualificationError as exc:
            last_error = str(exc)
            time.sleep(1.0)
    raise QualificationError(f"SeaweedFS did not recover within {timeout:.0f}s: {last_error}")


def fault_and_recover(container: str, base_url: str, expected_image: str, expected_version: str, *, restart: bool = True) -> dict[str, Any]:
    paused = False
    unavailable_observed = False
    try:
        if run(["docker", "pause", container]).returncode:
            raise QualificationError("cannot pause the SeaweedFS container")
        paused = True
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                request("GET", f"{base_url}/healthz", credential=None, timeout=0.5)
            except (OSError, urllib.error.URLError, TimeoutError):
                unavailable_observed = True
                break
            time.sleep(0.25)
        if not unavailable_observed:
            raise QualificationError("paused SeaweedFS was not detected unavailable")
    finally:
        if paused:
            run(["docker", "unpause", container])
    unpaused = wait_ready(container, base_url, expected_image, expected_version)
    if not restart:
        return {
            "paused_service_detected_unavailable": True,
            "unpause_recovery": "PASS",
            "restart_recovery": "NOT_REQUESTED",
            "after_unpause": unpaused["protocol"],
        }
    if run(["docker", "restart", "--time", "10", container], timeout=40.0).returncode:
        raise QualificationError("cannot restart the SeaweedFS container")
    recovered = wait_ready(container, base_url, expected_image, expected_version)
    # A restart discards the tmpfs: the write path and Object Lock enforcement
    # must come back too, not only the gateway's health endpoint.
    inspection = inspect_container(container)
    after_restart = object_lock_probe(base_url, credentials(inspection))
    return {
        "paused_service_detected_unavailable": True,
        "unpause_recovery": "PASS",
        "restart_recovery": "PASS",
        "after_restart": recovered["protocol"],
        "after_restart_object_lock": after_restart,
    }


def qualify(args: argparse.Namespace) -> dict[str, Any]:
    if args.fault_recovery and not args.execute:
        raise QualificationError("--fault-recovery requires explicit --execute")
    entry = validate_lock(json.loads(args.lock.read_text(encoding="utf-8")))
    inspection = inspect_container(args.container)
    runtime = validate_inspection(inspection, entry["image"])
    credential = credentials(inspection)
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "result": "PASS",
        "service": "seaweedfs",
        "lock": {key: entry[key] for key in ("image", "version", "source", "license")},
        "runtime": runtime,
        "protocol": probe(args.container, args.url, credential, entry["version"]),
    }
    if args.execute:
        result["object_lock"] = object_lock_probe(args.url, credential)
    if args.fault_recovery:
        result["fault_recovery"] = fault_and_recover(
            args.container, args.url, entry["image"], entry["version"], restart=not args.no_restart
        )
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path("infra/services.lock.json"))
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--fault-recovery", action="store_true")
    parser.add_argument(
        "--no-restart", action="store_true",
        help="pause/unpause only: the full-suite campaign forbids container restarts",
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        print(json.dumps(qualify(parse_args(argv)), indent=2, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, QualificationError) as exc:
        print(json.dumps({"result": "FAIL", "errors": [str(exc)]}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
