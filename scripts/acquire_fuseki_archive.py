#!/usr/bin/env python3
"""Acquire Fuseki bytes by the governed SHA512, within the provisioning budget.

The first source is the immutable governed GitHub release copy. The three
official Apache sources follow, with archive.apache.org last. From the copy,
only HTTPS redirects to release-assets.githubusercontent.com are accepted;
Apache sources still accept only Apache hosts. Downloads are anonymous. Cache
contents are untrusted until rehashed. The lock SHA512 is the only authority.
Check mode never downloads or writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, getproxies
from typing import Any

from ocor_bootstrap_lib import BootstrapError, load_json, root, run

APACHE_SOURCES = (
    "https://dlcdn.apache.org/jena/binaries/apache-jena-fuseki-6.2.0.tar.gz",
    "https://downloads.apache.org/jena/binaries/apache-jena-fuseki-6.2.0.tar.gz",
    "https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-6.2.0.tar.gz",
)
# Acquisition source only. It does not change the lock source, official_source,
# source_sha512, output_sha256, cache key or cache path.
GOVERNED_COPY_URL = (
    "https://github.com/nepryoon/ocor/releases/download/"
    "mirror-apache-jena-fuseki-6.2.0/apache-jena-fuseki-6.2.0.tar.gz"
)
RELEASE_ASSET_HOST = "release-assets.githubusercontent.com"
SOURCES = (GOVERNED_COPY_URL, *APACHE_SOURCES)
MAX_BYTES = 512 * 1024 * 1024


def _https_endpoint(url: str, *, hosts: set[str]) -> bool:
    parsed = urlparse(url)
    return (parsed.scheme == "https" and parsed.hostname in hosts
            and parsed.port in (None, 443) and parsed.username is None and parsed.password is None)


def official_url(url: str) -> bool:
    hosts = {urlparse(source).hostname for source in APACHE_SOURCES}
    return _https_endpoint(url, hosts={host for host in hosts if host is not None})


def release_asset_url(url: str) -> bool:
    return _https_endpoint(url, hosts={RELEASE_ASSET_HOST})


def redirect_allowed(current_url: str, new_url: str) -> bool:
    """Copy hops may land only on the release-asset host; Apache stays Apache."""
    current = urlparse(current_url)
    if current_url == GOVERNED_COPY_URL or current.hostname == RELEASE_ASSET_HOST:
        return release_asset_url(new_url)
    if official_url(current_url):
        return official_url(new_url)
    return False


def final_url_allowed(source: str, url: str) -> bool:
    if source == GOVERNED_COPY_URL:
        return url == GOVERNED_COPY_URL or release_asset_url(url)
    if source in APACHE_SOURCES:
        return official_url(url)
    return False


class OfficialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        current = req.get_full_url()
        if not redirect_allowed(current, newurl):
            raise BootstrapError("redirect outside official Apache sources")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_AUTH_HEADER_NAMES = frozenset({"authorization", "proxy-authorization"})
_PROXY_TYPE = re.compile(r"([^/:]+):(.*)", re.DOTALL)


def _transport_proxy(url: str) -> tuple[str | None, str | None, str | None, str]:
    """Split a proxy the way urllib.request accepts URL and authority forms."""
    match = _PROXY_TYPE.match(url)
    if match is None:
        scheme: str | None = None
        remainder = url
    else:
        scheme = match.group(1).lower()
        remainder = match.group(2)
    if not remainder.startswith("/"):
        scheme = None
        authority = url
    elif not remainder.startswith("//"):
        raise ValueError(f"proxy URL with no authority: {url!r}")
    elif "@" in remainder:
        host_separator = remainder.find("@")
        end = remainder.find("/", host_separator)
        authority = remainder[2:] if end == -1 else remainder[2:end]
    else:
        end = remainder.find("/", 2)
        authority = remainder[2:] if end == -1 else remainder[2:end]
    userinfo, separator, hostport = authority.rpartition("@")
    if separator == "":
        return scheme, None, None, hostport
    user, password_separator, password = userinfo.partition(":")
    return scheme, user, (password if password_separator else None), hostport


def _without_userinfo(url: str) -> str:
    """Drop userinfo from every proxy form the transport accepts.

    urlparse leaves ``user:pass@host:port`` unchanged. urllib.request still
    reads that authority and adds Proxy-Authorization before the tunnel.
    """
    if not isinstance(url, str):
        raise BootstrapError("proxy value is not text")
    try:
        scheme, user, password, hostport = _transport_proxy(url)
    except ValueError:
        return url
    if user is None and password is None:
        return url
    if hostport == "":
        raise BootstrapError("proxy host is absent")
    cleaned = hostport if scheme is None else f"{scheme}://{hostport}"
    try:
        _scheme, again_user, again_password, _hostport = _transport_proxy(cleaned)
    except ValueError as exc:
        raise BootstrapError("proxy credentials were not removed") from exc
    if again_user is not None or again_password is not None:
        raise BootstrapError("proxy credentials were not removed")
    return cleaned


def _anonymous_proxies() -> dict[str, str]:
    proxies: dict[str, str] = {}
    for scheme, url in getproxies().items():
        if not isinstance(url, str):
            continue
        proxies[scheme] = url if scheme == "no" else _without_userinfo(url)
    return proxies


class AnonymousProxyHandler(ProxyHandler):
    """Environment proxy without credentials or authorization headers."""

    def __init__(self) -> None:
        super().__init__(_anonymous_proxies())


def _reject_authorization_headers(request: Request) -> None:
    names = [name.lower() for name, _value in request.header_items()]
    if any(name in _AUTH_HEADER_NAMES for name in names):
        raise BootstrapError("anonymous acquisition rejects an authorization header")


def urlopen(request: Request, *, timeout: float) -> Any:
    _reject_authorization_headers(request)
    return build_opener(AnonymousProxyHandler(), OfficialRedirect()).open(request, timeout=timeout)


def _reject_lone_surrogates(value: object, *, where: str) -> None:
    """Reject decoded JSON text that contains a lone UTF-16 surrogate."""
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise BootstrapError(f"{where}: lone surrogate rejected")
        return
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BootstrapError(f"{where}: non-finite number rejected")
        return
    if isinstance(value, list):
        for item in value:
            _reject_lone_surrogates(item, where=where)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise BootstrapError(f"{where}: non-string key rejected")
            _reject_lone_surrogates(key, where=where)
            _reject_lone_surrogates(item, where=where)
        return
    raise BootstrapError(f"{where}: unexpected JSON type rejected")


def _load_stored_json(path: Path, *, where: str) -> dict[str, Any]:
    """Load one stored JSON object. Decode and parse errors stay typed."""
    try:
        loaded = load_json(path)
    except UnicodeDecodeError as exc:
        raise BootstrapError(f"{where}: {path.name} is not valid UTF-8") from exc
    _reject_lone_surrogates(loaded, where=where)
    return loaded


def cache_info(repository: Path) -> dict[str, str]:
    loaded = _load_stored_json(repository / "infra/services.lock.json", where="Fuseki acquisition lock")
    services = loaded.get("services")
    if not isinstance(services, list) or len(services) == 0:
        raise BootstrapError("Fuseki acquisition lock: services must be a non-empty list")
    service = None
    for index, item in enumerate(services):
        if not isinstance(item, dict) or "id" not in item:
            raise BootstrapError(
                f"Fuseki acquisition lock: services[{index}] must be an object with id")
        if item["id"] == "fuseki":
            service = item
            break
    if not isinstance(service, dict):
        raise BootstrapError("Fuseki acquisition lock: fuseki service is absent")
    build = service.get("build")
    if not isinstance(build, dict) or "source_sha512" not in build:
        raise BootstrapError(
            "Fuseki acquisition lock: fuseki build must be an object naming source_sha512")
    digest = build["source_sha512"]
    # The lock still names the Apache archive. The governed copy is not a lock source.
    if (service.get("version") != "6.2.0" or service.get("source") != APACHE_SOURCES[-1]
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{128}", digest)):
        raise BootstrapError("Fuseki acquisition lock is not the governed version/source/SHA512")
    return {"key": "fuseki-sha512-" + digest, "sha512": digest,
            "path": ".ocor/cache/fuseki/sha512/" + digest}


def remaining(deadline: float) -> float:
    result = deadline - time.monotonic()
    if result <= 0:
        raise BootstrapError("Fuseki provisioning budget exhausted")
    return result


def checked_sha512(path: Path, expected: str) -> str:
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{128}", expected):
        raise BootstrapError("Fuseki SHA512 mismatch; possible supply-chain failure")
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
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or not 0 < timeout <= 600):
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
        source = None
        if provenance.exists():
            loaded = _load_stored_json(provenance, where="Fuseki cache provenance")
            source = loaded.get("source")
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
            if any(name.lower() == "authorization" for name, _value in request.header_items()):
                raise BootstrapError("anonymous acquisition rejects an authorization header")
            with urlopen(request, timeout=min(10, remaining(source_deadline))) as response, partial.open("wb") as output:
                if not final_url_allowed(source, response.geturl()):
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
            try:
                digest = checked_sha512(partial, info["sha512"])
            except BootstrapError as exc:
                # A wrong digest stops acquisition. Later sources are not used.
                raise BootstrapError(f"{source}: {exc}") from exc
            remaining(deadline)
            partial.replace(target)
            provenance.write_text(json.dumps({"source": source}, indent=2, sort_keys=True) + "\n")
            result = {"cache": "MISS", "cache_key": info["key"], "source": source, "verified_sha512": digest}
            print(json.dumps({"operation": "Fuseki archive", **result}), flush=True)
            return target, result
        except (HTTPError, URLError, TimeoutError, ConnectionError, HTTPException) as exc:
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
