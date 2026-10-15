#!/usr/bin/env python3
"""Validate or provision the pinned OCOR non-production environment."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import time
from pathlib import Path

from acquire_fuseki_archive import acquire, build_context, remaining

from ocor_bootstrap_lib import BootstrapError, load_json, retry, root, run, validate_locks


def write_secret_file(repository: Path) -> Path:
    path = repository / ".ocor" / "bootstrap.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    spire = repository / ".ocor" / "spire"
    spire.mkdir(parents=True, exist_ok=True)
    certificate = spire / "ca.crt"
    key = spire / "ca.key"
    if not certificate.exists() or not key.exists():
        generated = run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:3072", "-nodes",
                "-keyout", str(key), "-out", str(certificate), "-days", "2",
                "-subj", "/C=IT/O=OCOR Test/CN=OCOR SPIRE Test CA",
            ],
            cwd=repository,
            timeout=30,
        )
        if generated.returncode:
            raise BootstrapError("failed to generate disposable SPIRE test CA")
        key.chmod(0o600)
    values = {
        "OCOR_LOCAL_KEYCLOAK_PASSWORD": secrets.token_urlsafe(32),
        "OCOR_LOCAL_OPENBAO_TOKEN": secrets.token_urlsafe(32),
        "OCOR_LOCAL_POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "OCOR_LOCAL_TERMINUSDB_PASSWORD": secrets.token_urlsafe(32),
        "OCOR_SPIRE_BOOTSTRAP_DIR": str(spire),
        "OCOR_SPIRE_JOIN_TOKEN": "bootstrap-pending",
    }
    path.write_text("".join(f"{key}={value}\n" for key, value in sorted(values.items())), encoding="utf-8")
    path.chmod(0o600)
    return path


def replace_env(path: Path, key: str, value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", value):
        raise BootstrapError(f"invalid generated value for {key}")
    entries = dict(
        line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line
    )
    entries[key] = value
    path.write_text("".join(f"{name}={item}\n" for name, item in sorted(entries.items())), encoding="utf-8")
    path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate locks and local availability only")
    parser.add_argument("--execute", action="store_true", help="perform repository-scoped provisioning")
    parser.add_argument("--skip-start", action="store_true", help="acquire/build but do not start services")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    try:
        repository = root()
        errors = validate_locks(repository)
        if errors:
            raise BootstrapError("; ".join(errors))
        services = load_json(repository / "infra/services.lock.json")["services"]
        if not args.execute:
            print(json.dumps({"status": "PASS", "mode": "CHECK_ONLY", "services": [x["id"] for x in services]}, indent=2, sort_keys=True))
            return 0
        sync = retry(["uv", "sync", "--project", "ocor-runtime", "--frozen", "--extra", "test"], cwd=repository, timeout=args.timeout)
        if sync.returncode:
            raise BootstrapError(f"uv sync failed: {sync.stderr[-1000:]}")
        acquired = []
        for service in services:
            if "build" in service:
                continue
            pull = retry(["docker", "pull", service["image"]], cwd=repository, timeout=args.timeout)
            if pull.returncode:
                raise BootstrapError(f"pull failed for {service['id']}: {pull.stderr[-1000:]}")
            acquired.append(service["id"])
        fuseki = next(item for item in services if item["id"] == "fuseki")
        expected_image_id = f"sha256:{fuseki['build']['output_sha256']}"
        present = run(
            ["docker", "image", "inspect", "ocor/jena-fuseki:6.2.0", "--format", "{{.Id}}"],
            cwd=repository,
            timeout=30,
        )
        if present.returncode or present.stdout.strip() != expected_image_id:
            deadline = time.monotonic() + args.timeout
            archive, _ = acquire(repository, timeout=args.timeout)
            with build_context(repository, archive) as context:
                build = run(
                    ["docker", "build", "--no-cache", "-t", "ocor/jena-fuseki:6.2.0", str(context)],
                    cwd=repository,
                    timeout=max(1, int(remaining(deadline))),
                )
            if build.returncode:
                raise BootstrapError(f"Fuseki build failed: {build.stderr[-1000:]}")
            rebuilt = run(
                ["docker", "image", "inspect", "ocor/jena-fuseki:6.2.0", "--format", "{{.Id}}"],
                cwd=repository,
                timeout=30,
            )
            if rebuilt.returncode or rebuilt.stdout.strip() != expected_image_id:
                raise BootstrapError("Fuseki local image identity differs from the governed lock")
        env_file = repository / ".ocor/bootstrap.env"
        if not env_file.exists():
            env_file = write_secret_file(repository)
        if not args.skip_start:
            server = run([
                "docker", "compose", "--env-file", str(env_file), "-f", "deploy/bootstrap/compose.yaml",
                "up", "--detach", "--wait", "--wait-timeout", str(args.timeout), "spire-server",
            ], cwd=repository, timeout=args.timeout + 60)
            if server.returncode:
                raise BootstrapError(f"SPIRE server start failed: {server.stderr[-1500:]}")
            token = run([
                "docker", "compose", "--env-file", str(env_file), "-f", "deploy/bootstrap/compose.yaml",
                "exec", "-T", "spire-server", "/opt/spire/bin/spire-server", "token", "generate",
                "-socketPath", "/run/spire/sockets/server.sock",
            ], cwd=repository, timeout=30)
            if token.returncode or "Token:" not in token.stdout:
                raise BootstrapError("SPIRE join token generation failed")
            token_value = token.stdout.split("Token:", 1)[1].splitlines()[0].strip()
            replace_env(env_file, "OCOR_SPIRE_JOIN_TOKEN", token_value)
            up = run([
                "docker", "compose", "--env-file", str(env_file), "-f", "deploy/bootstrap/compose.yaml",
                "up", "--detach", "--wait", "--wait-timeout", str(args.timeout), "--remove-orphans",
            ], cwd=repository, timeout=args.timeout + 60)
            if up.returncode:
                raise BootstrapError(f"compose start failed: {up.stderr[-1500:]}")
        print(json.dumps({"status": "PASS", "acquired": acquired, "secret_file": str(env_file), "started": not args.skip_start}, indent=2, sort_keys=True))
        return 0
    except (BootstrapError, OSError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
