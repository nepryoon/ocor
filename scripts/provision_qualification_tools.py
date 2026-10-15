#!/usr/bin/env python3
"""Acquire official checksum-pinned qualification tools in the worktree (DEC-211)."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def load_lock(repository: Path) -> list[dict[str, Any]]:
    lock = json.loads((repository / "infra/qualification_tools.lock.json").read_text())
    tools: list[dict[str, Any]] = lock["tools"]
    hosts = {"helm": "get.helm.sh", "kind": "github.com", "kubectl": "dl.k8s.io"}
    if len(tools) != 3 or {item["id"] for item in tools} != set(hosts):
        raise ValueError("qualification tool set differs from the governed scope")
    for item in tools:
        if not re.fullmatch(r"\d+\.\d+\.\d+", item["version"]) or item["architecture"] != "linux-amd64":
            raise ValueError("invalid qualification tool version or architecture")
        for key in ("source_sha256", "binary_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", item[key]):
                raise ValueError("invalid qualification tool digest")
        for key in ("source", "checksum_source"):
            url = urlparse(item[key])
            if url.scheme != "https" or url.hostname != hosts[item["id"]] or url.username or url.password:
                raise ValueError("qualification tool source is not official HTTPS")
        version = item["version"]
        official_paths = {"helm": f"https://get.helm.sh/helm-v{version}-linux-amd64.tar.gz",
                          "kind": f"https://github.com/kubernetes-sigs/kind/releases/download/v{version}/kind-linux-amd64",
                          "kubectl": f"https://dl.k8s.io/release/v{version}/bin/linux/amd64/kubectl"}
        source = official_paths[item["id"]]
        checksum = source + (".sha256" if item["id"] == "kubectl" else ".sha256sum")
        if (item["source"], item["checksum_source"]) != (source, checksum):
            raise ValueError("qualification URL differs from the official release")
        if item["archive_member"] != ("linux-amd64/helm" if item["id"] == "helm" else None):
            raise ValueError("invalid qualification tool archive member")
    return tools


def checked_digest(data: bytes, expected: str) -> None:
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("official qualification tool checksum mismatch")


def fetch(url: str) -> bytes:
    for attempt in range(2):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data: bytes = response.read(100_000_000)
                return data
        except (OSError, urllib.error.URLError):
            if attempt == 1:
                raise
            time.sleep(2)
    raise RuntimeError("unreachable")


def acquire(repository: Path) -> list[dict[str, str]]:
    tools = load_lock(repository)
    directory = repository / ".ocor/tools/bin"
    directory.mkdir(parents=True, exist_ok=True)
    records = []
    for item in tools:
        official = fetch(item["checksum_source"]).decode().split()[0]
        if official != item["source_sha256"]:
            raise ValueError(f"official checksum differs from lock: {item['id']}")
        data = fetch(item["source"])
        checked_digest(data, official)
        if item["archive_member"]:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                member = archive.getmember(item["archive_member"])
                if not member.isfile():
                    raise ValueError("qualification archive member is not a regular file")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("qualification archive member absent")
                data = stream.read()
        checked_digest(data, item["binary_sha256"])
        target = directory / item["id"]
        if target.is_symlink():
            raise ValueError("qualification tool target is a symlink")
        target.write_bytes(data)
        target.chmod(0o755)
        records.append({"id": item["id"], "version": item["version"], "binary_sha256": item["binary_sha256"], "source": item["source"]})
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    try:
        if not args.execute:
            tools = load_lock(repository)
            print(json.dumps({"status": "PASS", "mode": "CHECK_ONLY", "destination": ".ocor/tools/bin", "tools": [item["id"] for item in tools]}))
            return 0
        print(json.dumps({"status": "PASS", "tools": acquire(repository)}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
