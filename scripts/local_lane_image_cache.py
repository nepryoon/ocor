"""Transfer locked images from the host daemon into lane sandboxes.

Every pin is a service image in infra/services.lock.json, plus the Fuseki
build base image. Images already present are saved and loaded. An image the
host daemon does not have is a cold miss. This module never pulls or builds,
and a tag or a local id never replaces the locked digest.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from run_qualifying_campaign import CampaignError

SCHEMA = "ocor-local-lane-image-cache/v1"
MANIFEST_NAME = "manifest.json"
MANIFEST_KEYS = frozenset({"images", "lock_sha256", "schema"})
PRESENT_KEYS = frozenset({
    "archive", "archive_sha256", "image_id", "pinned_reference", "role", "service_id", "status"})
MISS_KEYS = frozenset({"pinned_reference", "role", "service_id", "status"})
ROLES = frozenset({"pinned_pull", "fuseki_base"})
PINNED_REFERENCE = re.compile(
    r"(?:[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*)@sha256:[0-9a-f]{64}",
    re.ASCII)
SERVICE_ID = re.compile(r"[a-z0-9][a-z0-9-]*", re.ASCII)
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}", re.ASCII)
SHA256_HEX = re.compile(r"[0-9a-f]{64}", re.ASCII)
ARCHIVE_NAME = re.compile(r"[a-z0-9][a-z0-9-]*-(?:pinned_pull|fuseki_base)\.tar", re.ASCII)

Timeout = float | Callable[[], float]


class DuplicateKey(ValueError):
    """A JSON object repeated a key. Distinct from a malformed document."""


def _command_result(runner: Any, argv: list[str], *, timeout: float, check: bool = True) -> tuple[int, str]:
    """Return code and UTF-8 stdout. Bool is not a code, and any other shape fails closed."""
    result = runner(argv, timeout=timeout, check=check)
    returncode = getattr(result, "returncode", None)
    stdout = getattr(result, "stdout", None)
    if isinstance(returncode, bool) or not isinstance(returncode, int) or not isinstance(stdout, str):
        raise CampaignError("image cache command result is malformed")
    return returncode, stdout


def command_text(runner: Any, argv: list[str], *, timeout: float) -> str:
    """Stdout of one cache command after the result shape has been checked."""
    _returncode, stdout = _command_result(runner, argv, timeout=timeout)
    return stdout


def _refuse_constant(name: str) -> object:
    raise ValueError(f"non-finite JSON number {name}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise DuplicateKey(str(key))
        document[key] = value
    return document


def _reject_lone_surrogates(value: object) -> None:
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, list):
        for item in value:
            _reject_lone_surrogates(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_lone_surrogates(key)
            _reject_lone_surrogates(item)


def decode_json(text: str, what: str) -> object:
    """JSON without duplicate keys, NaN, Infinity, or a lone surrogate."""
    try:
        value: object = json.loads(text, parse_constant=_refuse_constant, object_pairs_hook=_reject_duplicate_keys)
    except DuplicateKey as exc:
        raise CampaignError(f"{what} contains a duplicate key") from exc
    except ValueError as exc:
        raise CampaignError(f"{what} is not valid JSON: {exc}") from exc
    try:
        _reject_lone_surrogates(value)
    except UnicodeEncodeError as exc:
        raise CampaignError(f"{what} contains a lone surrogate") from exc
    return value


def _timeout_seconds(timeout: Timeout) -> float:
    value = timeout() if callable(timeout) else timeout
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise CampaignError("image cache command timeout is not a positive finite number")
    return float(value)


def _as_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    copied: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            return None
        copied[key] = item
    return copied


def _pin(service_id: str, role: str, reference: object) -> dict[str, str]:
    if not isinstance(reference, str) or PINNED_REFERENCE.fullmatch(reference) is None:
        raise CampaignError("malformed pinned reference")
    return {"pinned_reference": reference, "role": role, "service_id": service_id}


def locked_image_pins(document: object) -> list[dict[str, str]]:
    """Pinned pulls in lock order, then the Fuseki base image when that service is present."""
    services_document = _as_dict(document)
    services = services_document.get("services") if services_document is not None else None
    if not isinstance(services, list) or not services:
        raise CampaignError("services lock is malformed")
    pins: list[dict[str, str]] = []
    seen: set[str] = set()
    for service in services:
        fields = _as_dict(service)
        service_id = fields.get("id") if fields is not None else None
        if fields is None or not isinstance(service_id, str) or SERVICE_ID.fullmatch(service_id) is None or service_id in seen:
            raise CampaignError("services lock is malformed")
        seen.add(service_id)
        produced = False
        if "image" in fields:
            pins.append(_pin(service_id, "pinned_pull", fields.get("image")))
            produced = True
        if service_id == "fuseki":
            build = _as_dict(fields.get("build"))
            if build is None or "base_image" not in build:
                raise CampaignError("Fuseki base image is missing")
            pins.append(_pin(service_id, "fuseki_base", build.get("base_image")))
            produced = True
        if not produced:
            raise CampaignError(f"service {service_id} has neither a pinned image nor a Fuseki base image")
    return pins


def read_lock(path: Path) -> tuple[bytes, object]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CampaignError(f"services lock unreadable: {path}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CampaignError(f"services lock is not UTF-8: {path}: {exc}") from exc
    return raw, decode_json(text, "services lock")


def _digest_of(reference: str) -> str:
    return "sha256:" + reference.rsplit(":", 1)[1]


def _require_image_id(document: dict[str, object]) -> str:
    if "Id" not in document:
        raise CampaignError("image id is missing")
    image_id = document["Id"]
    if isinstance(image_id, bool) or not isinstance(image_id, str):
        raise CampaignError("image id is not a string")
    if IMAGE_ID.fullmatch(image_id) is None:
        raise CampaignError("image id is not a digest")
    return image_id


def _require_repo_digests(document: dict[str, object]) -> list[str]:
    value = document.get("RepoDigests")
    if not isinstance(value, list):
        raise CampaignError("RepoDigests is not a list of strings")
    digests: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise CampaignError("RepoDigests is not a list of strings")
        digests.append(item)
    return digests


def _inspect_object(text: str, what: str) -> dict[str, object]:
    document = decode_json(text, what)
    if not isinstance(document, list) or len(document) != 1:
        raise CampaignError(f"{what} is not a one-element list")
    element = document[0]
    if element is None:
        raise CampaignError(f"{what} element is null")
    fields = _as_dict(element)
    if fields is None:
        raise CampaignError(f"{what} element is not an object")
    return fields


def parse_host_inspect(text: str, pinned_reference: str) -> str:
    """Image id of a host inspect whose RepoDigests contain the exact locked reference."""
    if not isinstance(pinned_reference, str) or PINNED_REFERENCE.fullmatch(pinned_reference) is None:
        raise CampaignError("malformed pinned reference")
    document = _inspect_object(text, "image inspect")
    image_id = _require_image_id(document)
    if pinned_reference not in _require_repo_digests(document):
        raise CampaignError("pinned reference is absent from RepoDigests")
    if image_id != _digest_of(pinned_reference):
        raise CampaignError("image id does not match the locked digest")
    return image_id


def parse_loaded_inspect(text: str, image_id: str) -> None:
    """The loaded image id matches the cache. RepoDigests may be absent or empty after load."""
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise CampaignError("image id is not a digest")
    document = _inspect_object(text, "image inspect")
    found = _require_image_id(document)
    if "RepoDigests" in document:
        _require_repo_digests(document)
    if found != image_id:
        raise CampaignError("loaded image id does not match the cache")


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                hasher.update(chunk)
    except OSError as exc:
        raise CampaignError(f"image cache archive is unreadable: {exc}") from exc
    return hasher.hexdigest()


def archive_image_id_matches(archive: Path, image_id: str) -> None:
    """The OCI index manifest digest is the image id and that blob is in the archive.

    The classic manifest.json Config blob is not an image id.
    """
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise CampaignError("image id is not a digest")
    blob = f"blobs/sha256/{image_id.removeprefix('sha256:')}"
    try:
        with tarfile.open(archive, "r") as tar:
            names = set(tar.getnames())
            if "index.json" not in names:
                raise CampaignError("image archive has no OCI index")
            member = tar.extractfile("index.json")
            raw = b"" if member is None else member.read()
    except CampaignError:
        raise
    except (tarfile.TarError, OSError, KeyError) as exc:
        raise CampaignError(f"image archive is unreadable: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CampaignError(f"OCI index is not UTF-8: {exc}") from exc
    index = _as_dict(decode_json(text, "OCI index"))
    manifests = index.get("manifests") if index is not None else None
    digests: list[str] = []
    if isinstance(manifests, list):
        for item in manifests:
            fields = _as_dict(item)
            digest = fields.get("digest") if fields is not None else None
            if isinstance(digest, str):
                digests.append(digest)
    if image_id not in digests or blob not in names:
        raise CampaignError("image cache archive image id does not match")


def _entry(value: object) -> dict[str, str]:
    fields = _as_dict(value)
    if fields is None or not isinstance(fields.get("status"), str):
        raise CampaignError("image cache manifest is malformed")
    status = cast(str, fields["status"])
    allowed = PRESENT_KEYS if status == "PRESENT" else MISS_KEYS if status == "MISS" else None
    if allowed is None or set(fields) != allowed:
        raise CampaignError("image cache manifest is malformed")
    result: dict[str, str] = {}
    for key in allowed:
        item = fields[key]
        if not isinstance(item, str):
            raise CampaignError("image cache manifest is malformed")
        result[key] = item
    if SERVICE_ID.fullmatch(result["service_id"]) is None or result["role"] not in ROLES:
        raise CampaignError("image cache manifest is malformed")
    if PINNED_REFERENCE.fullmatch(result["pinned_reference"]) is None:
        raise CampaignError("malformed pinned reference")
    if status == "PRESENT" and (
            result["archive"] != f"{result['service_id']}-{result['role']}.tar"
            or ARCHIVE_NAME.fullmatch(result["archive"]) is None
            or SHA256_HEX.fullmatch(result["archive_sha256"]) is None):
        raise CampaignError("image cache manifest is malformed")
    if status == "PRESENT":
        if IMAGE_ID.fullmatch(result["image_id"]) is None:
            raise CampaignError("image id is not a digest")
        if result["image_id"] != _digest_of(result["pinned_reference"]):
            raise CampaignError("image id does not match the locked digest")
    return result


def _manifest_document(cache_dir: Path) -> dict[str, object]:
    path = cache_dir / MANIFEST_NAME
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CampaignError(f"image cache manifest unreadable: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CampaignError(f"image cache manifest is not UTF-8: {exc}") from exc
    document = _as_dict(decode_json(text, "image cache manifest"))
    if document is None or set(document) != MANIFEST_KEYS or document.get("schema") != SCHEMA:
        raise CampaignError("image cache manifest is malformed")
    return document


def verify_image_cache(cache_dir: Path, lock_path: Path) -> dict[str, object]:
    """Check every archive before any load. A hash, pin, or identity mismatch fails closed."""
    raw, lock_document = read_lock(lock_path)
    pins = locked_image_pins(lock_document)
    manifest = _manifest_document(cache_dir)
    recorded_hash = manifest.get("lock_sha256")
    if not isinstance(recorded_hash, str) or SHA256_HEX.fullmatch(recorded_hash) is None:
        raise CampaignError("image cache lock hash is malformed")
    if recorded_hash != hashlib.sha256(raw).hexdigest():
        raise CampaignError("image cache lock hash does not match")
    images = manifest.get("images")
    if not isinstance(images, list):
        raise CampaignError("image cache manifest is malformed")
    entries = [_entry(item) for item in images]
    if [(item["service_id"], item["role"], item["pinned_reference"]) for item in entries] != [
            (pin["service_id"], pin["role"], pin["pinned_reference"]) for pin in pins]:
        raise CampaignError("image cache pin list does not match the lock")
    expected = {MANIFEST_NAME}
    for entry in entries:
        if entry["status"] != "PRESENT":
            continue
        archive = cache_dir / entry["archive"]
        if not archive.is_file():
            raise CampaignError("image cache archive is missing")
        if _file_sha256(archive) != entry["archive_sha256"]:
            raise CampaignError("image cache archive is altered")
        archive_image_id_matches(archive, entry["image_id"])
        expected.add(entry["archive"])
    try:
        found = {item.name for item in cache_dir.iterdir()}
    except OSError as exc:
        raise CampaignError(f"image cache is unreadable: {exc}") from exc
    if found != expected:
        raise CampaignError("image cache contents do not match the manifest")
    return {"images": entries, "lock_sha256": recorded_hash, "schema": SCHEMA}


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _capture(pin: dict[str, str], destination: Path, runner: Any, timeout: Timeout) -> dict[str, str]:
    reference = pin["pinned_reference"]
    returncode, stdout = _command_result(
        runner, ["docker", "image", "inspect", reference], timeout=_timeout_seconds(timeout), check=False)
    if returncode != 0:
        return {"pinned_reference": reference, "role": pin["role"], "service_id": pin["service_id"], "status": "MISS"}
    image_id = parse_host_inspect(stdout, reference)
    archive_name = f"{pin['service_id']}-{pin['role']}.tar"
    archive = destination / archive_name
    _command_result(runner, ["docker", "image", "save", "-o", str(archive), reference], timeout=_timeout_seconds(timeout))
    archive_image_id_matches(archive, image_id)
    return {
        "archive": archive_name, "archive_sha256": _file_sha256(archive), "image_id": image_id,
        "pinned_reference": reference, "role": pin["role"], "service_id": pin["service_id"], "status": "PRESENT"}


def prepare_image_cache(lock_path: Path, destination: Path, runner: Any, *, timeout: Timeout) -> dict[str, object]:
    """Save host images that match the lock. Create the cache only when the destination is absent."""
    if destination.exists():
        raise CampaignError("image cache destination exists")
    raw, document = read_lock(lock_path)
    pins = locked_image_pins(document)
    created = False
    ok = False
    try:
        destination.mkdir(parents=True)
        created = True
        images = [_capture(pin, destination, runner, timeout) for pin in pins]
        _write_manifest(destination / MANIFEST_NAME, {
            "images": images, "lock_sha256": hashlib.sha256(raw).hexdigest(), "schema": SCHEMA})
        verified = verify_image_cache(destination, lock_path)
        ok = True
        return verified
    finally:
        if created and not ok:
            shutil.rmtree(destination, ignore_errors=True)
