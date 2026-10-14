#!/usr/bin/env python3
"""Acquire Fuseki bytes by the governed SHA512, within the provisioning budget.

Only Apache sources and this worktree's content-addressed cache are used. Cache
contents are untrusted until rehashed. Check mode never downloads or writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from typing import Any

from ocor_bootstrap_lib import BootstrapError, load_json, root, run

SOURCES = (
    "https://dlcdn.apache.org/jena/binaries/apache-jena-fuseki-6.2.0.tar.gz",
    "https://downloads.apache.org/jena/binaries/apache-jena-fuseki-6.2.0.tar.gz",
    "https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-6.2.0.tar.gz",
)
MAX_BYTES = 512 * 1024 * 1024


def official_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.scheme == "https" and parsed.hostname in {urlparse(source).hostname for source in SOURCES}
            and parsed.port in (None, 443) and parsed.username is None and parsed.password is None)


class OfficialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if not official_url(newurl):
            raise BootstrapError("redirect outside official Apache sources")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urlopen(request: Request, *, timeout: float) -> Any:
    return build_opener(OfficialRedirect()).open(request, timeout=timeout)


def cache_info(repository: Path) -> dict[str, str]:
    service = next(item for item in load_json(repository / "infra/services.lock.json")["services"] if item["id"] == "fuseki")
    digest = service["build"]["source_sha512"]
    if service["version"] != "6.2.0" or service["source"] != SOURCES[-1] or not re.fullmatch(r"[0-9a-f]{128}", digest):
        raise BootstrapError("Fuseki acquisition lock is not the governed version/source/SHA512")
    return {"key": "fuseki-sha512-" + digest, "sha512": digest,
            "path": ".ocor/cache/fuseki/sha512/" + digest}


def remaining(deadline: float) -> float:
    result = deadline - time.monotonic()
    if result <= 0:
        raise BootstrapError("Fuseki provisioning budget exhausted")
    return result


def checked_sha512(path: Path, expected: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise BootstrapError("archive must be a regular file, not a symlink")
    if path.stat().st_size > MAX_BYTES:
        raise BootstrapError("Fuseki archive exceeds bounded size")
    digest = hashlib.sha512()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise BootstrapError("Fuseki SHA512 mismatch; possible supply-chain failure")
    return actual


def acquire(repository: Path, *, timeout: float = 600) -> tuple[Path, dict[str, object]]:
    if not 0 < timeout <= 600:
        raise BootstrapError("provisioning budget must be in (0, 600] seconds")
    deadline = time.monotonic() + timeout
    info = cache_info(repository)
    directory = repository / info["path"]
    for path in [directory, *directory.parents]:
        if path == repository:
            break
        if path.is_symlink():
            raise BootstrapError("cache path contains a symlink")
    target = directory / "apache-jena-fuseki.tar.gz"
    provenance = directory / "provenance.json"
    if provenance.is_symlink():
        raise BootstrapError("cache provenance contains a symlink")
    if target.exists() or target.is_symlink():
        digest = checked_sha512(target, info["sha512"])
        source = load_json(provenance).get("source") if provenance.exists() else None
        # Provenance is informative; it can never authorize archive bytes.
        if source not in SOURCES:
            source = "CONTENT_ADDRESSED_CACHE; original source NOT_EXECUTED"
        remaining(deadline)
        result = {"cache": "HIT", "cache_key": info["key"], "source": source, "verified_sha512": digest}
        print(json.dumps({"operation": "Fuseki archive", **result}), flush=True)
        return target, result
    directory.mkdir(parents=True, exist_ok=True)
    failures = []
    for source in SOURCES:
        budget = remaining(deadline)
        source_deadline = time.monotonic() + min(120, budget)
        partial = directory / "archive.part"
        if partial.is_symlink():
            raise BootstrapError("partial cache file contains a symlink")
        try:
            request = Request(source, headers={"User-Agent": "OCOR-governed-acquisition/1"})
            with urlopen(request, timeout=min(10, remaining(source_deadline))) as response, partial.open("wb") as output:
                if not official_url(response.geturl()):
                    raise BootstrapError("redirect outside official Apache sources")
                size = 0
                while True:
                    if time.monotonic() >= source_deadline:
                        raise TimeoutError("official source deadline exhausted")
                    # read1 performs one receive; read(size) can keep waiting for
                    # a full MiB while a slow source dribbles bytes indefinitely.
                    transport = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                    if transport is not None:
                        transport.settimeout(min(10, remaining(source_deadline)))
                    chunk = response.read1(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise BootstrapError("Fuseki archive exceeds bounded size")
                    output.write(chunk)
            digest = checked_sha512(partial, info["sha512"])
            remaining(deadline)
            partial.replace(target)
            provenance.write_text(json.dumps({"source": source}, indent=2, sort_keys=True) + "\n")
            result = {"cache": "MISS", "cache_key": info["key"], "source": source, "verified_sha512": digest}
            print(json.dumps({"operation": "Fuseki archive", **result}), flush=True)
            return target, result
        except (HTTPError, URLError, TimeoutError, ConnectionError) as exc:
            failures.append({"source": source, "error": str(exc)})
            print(json.dumps({"operation": "Fuseki archive source", **failures[-1], "status": "FAIL"}), flush=True)
        finally:
            partial.unlink(missing_ok=True)
    raise BootstrapError("official sources exhausted: " + json.dumps(failures))


@contextmanager
def build_context(repository: Path, archive: Path) -> Iterator[Path]:
    """Verify every copied archive before Docker can consume it; remove context."""
    digest = cache_info(repository)["sha512"]
    checked_sha512(archive, digest)
    parent = repository / ".ocor"
    if parent.is_symlink():
        raise BootstrapError("build context parent contains a symlink")
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fuseki-build-", dir=parent) as name:
        context = Path(name)
        shutil.copyfile(repository / "infra/fuseki/Dockerfile", context / "Dockerfile")
        copied = context / "apache-jena-fuseki.tar.gz"
        shutil.copyfile(archive, copied)
        checked_sha512(copied, digest)
        yield context


def build_ci_image(repository: Path, *, timeout: float = 600) -> dict[str, object]:
    """Download, verify and build within ONE 600-second budget, without retries."""
    deadline = time.monotonic() + timeout
    archive, provenance = acquire(repository, timeout=timeout)
    with build_context(repository, archive) as context:
        result = run(
            ["docker", "build", "-t", "ocor/jena-fuseki:ci", str(context)],
            cwd=repository, timeout=max(1, int(remaining(deadline))),
        )
    if result.returncode:
        raise BootstrapError(f"verified Fuseki build failed: {result.stderr[-2000:]}")
    remaining(deadline)
    return {"status": "PASS", "image": "ocor/jena-fuseki:ci", **provenance}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--github-output", action="store_true", help="print cache key/path without mutation")
    parser.add_argument("--build-ci-image", action="store_true", help="build CI Fuseki from verified bytes; requires --execute")
    args = parser.parse_args()
    try:
        repository = root()
        if args.github_output:
            info = cache_info(repository)
            print(f"key={info['key']}\npath={info['path']}")
        elif args.execute and args.build_ci_image:
            print(json.dumps(build_ci_image(repository, timeout=args.timeout), sort_keys=True))
        elif args.execute:
            acquire(repository, timeout=args.timeout)
        else:
            print(json.dumps({"mode": "CHECK_ONLY", **cache_info(repository)}, sort_keys=True))
        return 0
    except (BootstrapError, OSError, ValueError, KeyError, StopIteration) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
