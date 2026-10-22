#!/usr/bin/env python3
"""OCOR-DEV-0082: reset and teardown the disposable ocor-bootstrap environment.

Two distinct, complementary operations:

* ``--reset`` undoes exactly the governed scaffolding OCOR-DEV-0080's
  initialize_services.py creates (the "ocor" Keycloak realm, the
  "ocor_bootstrap" OPA policy, the "ocor" OpenBao KV mount, and the
  "ocor_default" TerminusDB/TypeDB databases), returning the stack to the
  freshly-provisioned-but-uninitialized state OCOR-DEV-0079 leaves it in --
  without stopping a single container. SPIRE trust is deliberately left
  untouched: OCOR-DEV-0080 only ever verifies it, never creates it, so
  there is nothing for reset to undo without breaking every service's
  identity.
* ``--teardown`` (the pre-existing behavior) stops and removes the entire
  disposable Compose project, containers and volumes included.

Both are dry-run by default and require ``--execute`` to actually mutate
anything, and both are idempotent: resetting or tearing down an
already-reset/torn-down environment is a documented no-op, never an error.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast

from ocor_bootstrap_lib import BootstrapError, root, run

TERMINUSDB_URL = "http://127.0.0.1:6363"
TYPEDB_URL = "http://127.0.0.1:8000"
KEYCLOAK_URL = "http://127.0.0.1:8080"
OPA_URL = "http://127.0.0.1:8181"
OPENBAO_URL = "http://127.0.0.1:8200"

OCOR_REALM = "ocor"
OCOR_DATABASE = "ocor_default"
OPA_POLICY_ID = "ocor_bootstrap"
OPENBAO_MOUNT = "ocor"
PROJECT = "ocor-bootstrap"
PROJECT_LABEL = "com.docker.compose.project"
INVENTORY_TIMEOUT = 30


class ResetError(RuntimeError):
    """A reset step failed closed."""


def _request(
    method: str, url: str, *, headers: dict[str, str] | None = None, body: bytes | None = None, timeout: float = 10.0
) -> tuple[int, str]:
    request = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def _keycloak_admin_token(password: str) -> str:
    status, body = _request(
        "POST",
        f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=(
            f"client_id=admin-cli&username=ocor-admin&password={urllib.parse.quote(password)}&grant_type=password"
        ).encode("utf-8"),
    )
    if status != 200:
        raise ResetError(f"cannot obtain a Keycloak admin token: {status} {body}")
    token: str = json.loads(body)["access_token"]
    return token


def reset_keycloak_realm(password: str) -> dict[str, Any]:
    token = _keycloak_admin_token(password)
    status, body = _request("GET", f"{KEYCLOAK_URL}/admin/realms/{OCOR_REALM}", headers={"Authorization": f"Bearer {token}"})
    if status == 404:
        return {"step": "keycloak_realm", "result": "ALREADY_RESET"}
    if status != 200:
        raise ResetError(f"unexpected Keycloak realm lookup status: {status} {body}")
    delete_status, delete_body = _request(
        "DELETE", f"{KEYCLOAK_URL}/admin/realms/{OCOR_REALM}", headers={"Authorization": f"Bearer {token}"}
    )
    if delete_status != 204:
        raise ResetError(f"failed to delete Keycloak realm {OCOR_REALM!r}: {delete_status} {delete_body}")
    return {"step": "keycloak_realm", "result": "RESET"}


def reset_opa_policy() -> dict[str, Any]:
    status, _ = _request("GET", f"{OPA_URL}/v1/policies/{OPA_POLICY_ID}")
    if status == 404:
        return {"step": "opa_policy", "result": "ALREADY_RESET"}
    if status != 200:
        raise ResetError(f"unexpected OPA policy lookup status: {status}")
    delete_status, delete_body = _request("DELETE", f"{OPA_URL}/v1/policies/{OPA_POLICY_ID}")
    if delete_status != 200:
        raise ResetError(f"failed to delete OPA policy {OPA_POLICY_ID!r}: {delete_status} {delete_body}")
    return {"step": "opa_policy", "result": "RESET"}


def reset_openbao_paths(root_token: str) -> dict[str, Any]:
    headers = {"X-Vault-Token": root_token}
    status, body = _request("GET", f"{OPENBAO_URL}/v1/sys/mounts", headers=headers)
    if status != 200:
        raise ResetError(f"cannot list OpenBao mounts: {status} {body}")
    mounts = json.loads(body).get("data", {})
    if f"{OPENBAO_MOUNT}/" not in mounts:
        return {"step": "openbao_paths", "result": "ALREADY_RESET"}
    delete_status, delete_body = _request("DELETE", f"{OPENBAO_URL}/v1/sys/mounts/{OPENBAO_MOUNT}", headers=headers)
    if delete_status != 204:
        raise ResetError(f"failed to unmount OpenBao path {OPENBAO_MOUNT!r}: {delete_status} {delete_body}")
    return {"step": "openbao_paths", "result": "RESET"}


def reset_graph_databases(terminusdb_password: str) -> dict[str, Any]:
    detail: dict[str, str] = {}
    credentials = f"admin:{terminusdb_password}".encode()
    tdb_headers = {"Authorization": f"Basic {base64.b64encode(credentials).decode()}"}
    status, body = _request("GET", f"{TERMINUSDB_URL}/api/db", headers=tdb_headers)
    if status != 200:
        raise ResetError(f"cannot list TerminusDB databases: {status} {body}")
    existing_terminus = {entry["path"].split("/")[-1] for entry in json.loads(body)}
    if OCOR_DATABASE not in existing_terminus:
        detail["terminusdb"] = "ALREADY_RESET"
    else:
        delete_status, delete_body = _request(
            "DELETE", f"{TERMINUSDB_URL}/api/db/admin/{OCOR_DATABASE}", headers=tdb_headers
        )
        if delete_status != 200:
            raise ResetError(f"failed to delete TerminusDB database {OCOR_DATABASE!r}: {delete_status} {delete_body}")
        detail["terminusdb"] = "RESET"

    signin_status, signin_body = _request(
        "POST",
        f"{TYPEDB_URL}/v1/signin",
        headers={"Content-Type": "application/json"},
        body=json.dumps({"username": "admin", "password": "password"}).encode("utf-8"),
    )
    if signin_status != 200:
        raise ResetError(f"cannot sign in to TypeDB: {signin_status} {signin_body}")
    typedb_token = json.loads(signin_body)["token"]
    typedb_headers = {"Authorization": f"Bearer {typedb_token}"}
    list_status, list_body = _request("GET", f"{TYPEDB_URL}/v1/databases", headers=typedb_headers)
    if list_status != 200:
        raise ResetError(f"cannot list TypeDB databases: {list_status} {list_body}")
    existing_typedb = {entry["name"] for entry in json.loads(list_body).get("databases", [])}
    if OCOR_DATABASE not in existing_typedb:
        detail["typedb"] = "ALREADY_RESET"
    else:
        delete_status, delete_body = _request(
            "DELETE", f"{TYPEDB_URL}/v1/databases/{OCOR_DATABASE}", headers=typedb_headers
        )
        if delete_status != 200:
            raise ResetError(f"failed to delete TypeDB database {OCOR_DATABASE!r}: {delete_status} {delete_body}")
        detail["typedb"] = "RESET"

    overall = "RESET" if "RESET" in detail.values() else "ALREADY_RESET"
    return {"step": "graph_databases", "result": overall, "detail": detail}


def reset(*, terminusdb_password: str, keycloak_password: str, openbao_root_token: str) -> list[dict[str, Any]]:
    return [
        reset_keycloak_realm(keycloak_password),
        reset_opa_policy(),
        reset_openbao_paths(openbao_root_token),
        reset_graph_databases(terminusdb_password),
    ]


def teardown_command(repository: Path, env_file: Path | None = None) -> list[str]:
    env_file = env_file if env_file is not None else repository / ".ocor" / "bootstrap.env"
    command = ["docker", "compose"]
    if env_file.exists():
        command.extend(["--env-file", str(env_file)])
    command.extend(["-p", "ocor-bootstrap", "-f", "deploy/bootstrap/compose.yaml", "down", "--volumes", "--remove-orphans"])
    return command


def owned_resources(repository: Path, previous: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Read inventory independently of Compose, validating ownership before mutation.

    Names alone never authorise removal. A reserved project name without the
    exact Compose project label is ambiguous and blocks teardown. Previously
    observed identities remain candidates even if renamed or relabelled.
    Only candidate resources are inspected; only Compose performs deletion.
    """
    deadline = time.monotonic() + INVENTORY_TIMEOUT
    inventory: dict[str, list[dict[str, Any]]] = {}
    mounted_volumes: dict[str, set[str]] = {}

    def query(command: list[str]) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ResetError("owned-resource inventory deadline expired")
        # subprocess accepts float seconds; the shared helper is annotated int.
        result = run(command, cwd=repository, timeout=cast(int, min(10, remaining)))
        if result.returncode:
            raise ResetError("owned-resource inventory unavailable")
        return result.stdout

    for kind, key in (("container", "containers"), ("network", "networks"), ("volume", "volumes")):
        command = ["docker", kind, "ls", "--format", "{{json .}}"]
        if kind == "container":
            command.append("--all")
        if kind in {"container", "network"}:
            command.append("--no-trunc")
        prior_ids = {item["id"] for item in (previous or {}).get(key, [])}
        prior_mounts = {item["id"]: item.get("anonymous_mount_owner_ids", []) for item in (previous or {}).get(key, [])}
        inventory[key] = []
        for line in query(command).splitlines():
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ResetError("malformed owned-resource inventory")
            name = item.get("Names") if kind == "container" else item.get("Name")
            identity = name if kind == "volume" else item.get("ID")
            labels = item.get("Labels")
            if (not isinstance(name, str) or not name or not isinstance(identity, str) or not identity
                    or not isinstance(labels, str)):
                raise ResetError("incomplete owned-resource inventory")
            reserved_name = name.startswith((PROJECT + "_", PROJECT + "-")) or name == PROJECT
            labelled = f"{PROJECT_LABEL}={PROJECT}" in labels.split(",")
            if not (reserved_name or labelled or identity in prior_ids or (kind == "volume" and identity in mounted_volumes)):
                continue
            inspected = json.loads(query(["docker", kind, "inspect", identity]))
            if not isinstance(inspected, list) or len(inspected) != 1 or not isinstance(inspected[0], dict):
                raise ResetError("malformed owned-resource inspection")
            detail = inspected[0]
            actual_labels = detail.get("Config", {}).get("Labels") if kind == "container" else detail.get("Labels")
            actual_name = detail.get("Name")
            actual_id = actual_name if kind == "volume" else detail.get("Id")
            if (actual_id != identity or not isinstance(actual_name, str)
                    or actual_name.removeprefix("/") != name):
                raise ResetError("ambiguous owned-resource identity or ownership")
            mount_owners = sorted(mounted_volumes.get(identity, set()) | set(prior_mounts.get(identity, []))) if kind == "volume" else []
            anonymous = (bool(mount_owners) and re.fullmatch(r"[a-f0-9]{64}", identity) is not None
                         and isinstance(actual_labels, dict) and PROJECT_LABEL not in actual_labels
                         and actual_labels.get("com.docker.volume.anonymous") == "")
            if not isinstance(actual_labels, dict) or (actual_labels.get(PROJECT_LABEL) != PROJECT and not anonymous):
                raise ResetError("ambiguous owned-resource identity or ownership")
            resource: dict[str, Any] = {"id": identity, "name": name}
            if anonymous:
                resource["anonymous_mount_owner_ids"] = mount_owners
            inventory[key].append(resource)
            if kind == "container":
                mounts = detail.get("Mounts", [])
                if not isinstance(mounts, list) or any(not isinstance(mount, dict) for mount in mounts):
                    raise ResetError("malformed owned-container mounts")
                for mount in mounts:
                    if mount.get("Type") == "volume":
                        volume_name = mount.get("Name")
                        if not isinstance(volume_name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", volume_name):
                            raise ResetError("invalid owned-container volume binding")
                        mounted_volumes.setdefault(volume_name, set()).add(identity)
        inventory[key].sort(key=lambda resource: resource["id"])
    if set(mounted_volumes) - {item["id"] for item in inventory["volumes"]}:
        raise ResetError("owned-container volume missing from inventory")
    return inventory


def teardown(repository: Path, command: list[str]) -> tuple[int, dict[str, Any]]:
    before = owned_resources(repository)
    result = run(command, cwd=repository, timeout=180)
    remaining = owned_resources(repository, previous=before)
    passed = result.returncode == 0 and not any(remaining.values())
    return (0 if passed else 1), {
        "status": "PASS" if passed else "FAIL",
        "compose_exit_code": result.returncode,
        "owned_resources_remaining": remaining,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="undo OCOR-DEV-0080's initialization, keep containers")
    parser.add_argument("--env-file", type=Path, help="file with OCOR_LOCAL_* secrets (required with --reset)")
    parser.add_argument("--execute", action="store_true", help="confirm the mutating operation")
    args = parser.parse_args()
    repository = root()

    if args.reset:
        if args.env_file is None:
            print(json.dumps({"status": "ERROR", "error": "--reset requires --env-file"}, sort_keys=True))
            return 2
        env: dict[str, str] = {}
        for line in args.env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                env[key] = value
        if not args.execute:
            print(json.dumps({"status": "PASS", "mode": "DRY_RUN", "operation": "reset"}, indent=2, sort_keys=True))
            return 0
        try:
            steps = reset(
                terminusdb_password=env["OCOR_LOCAL_TERMINUSDB_PASSWORD"],
                keycloak_password=env["OCOR_LOCAL_KEYCLOAK_PASSWORD"],
                openbao_root_token=env["OCOR_LOCAL_OPENBAO_TOKEN"],
            )
            print(json.dumps({"status": "PASS", "steps": steps}, indent=2, sort_keys=True))
            return 0
        except (ResetError, KeyError, OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
            return 1

    command = teardown_command(repository, args.env_file)
    if not args.execute:
        print(json.dumps({"status": "PASS", "mode": "DRY_RUN", "command": command}, indent=2))
        return 0
    try:
        code, report = teardown(repository, command)
    except (BootstrapError, ResetError, OSError, ValueError, TypeError, AttributeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
