#!/usr/bin/env python3
"""Provision the complete disposable CI stack from the governed build recipes.

The local bootstrap's machine-specific Fuseki image identity check is unchanged.
CI builds the locked Dockerfile (pinned base and SHA-512 source), records its image
identity, and qualifies that image through the existing typed service validator.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, TypedDict

from acquire_fuseki_archive import acquire, build_context
from bootstrap_development_environment import replace_env, write_secret_file
from ocor_bootstrap_lib import BootstrapError, load_json, root, run, validate_locks


def redact(text: str, secrets: list[str]) -> str:
    for value in secrets:
        if value:
            text = text.replace(value, "[REDACTED]")
    return re.sub(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----.*?-----END (?:RSA |EC )?PRIVATE KEY-----", "[REDACTED PRIVATE KEY]", text, flags=re.DOTALL)


def redact_campaign_log(repository: Path, path: Path) -> None:
    env_file = repository / ".ocor/bootstrap.env"
    secrets = [line.split("=", 1)[1] for line in env_file.read_text().splitlines()
               if "=" in line and line.split("=", 1)[0].endswith(("TOKEN", "PASSWORD"))]
    path.write_text(redact(path.read_text(), secrets))


def collect_stack_diagnostics(repository: Path, output: Path) -> None:
    """Capture only this Compose project; redact generated credentials in logs."""
    env_file = repository / ".ocor/bootstrap.env"
    secrets = []
    if env_file.exists():
        secrets = [line.split("=", 1)[1] for line in env_file.read_text().splitlines()
                   if "=" in line and line.split("=", 1)[0].endswith(("TOKEN", "PASSWORD"))]
    ids = run(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=ocor-bootstrap"], cwd=repository, timeout=10).stdout.split()
    with output.open("w") as log:
        if not ids:
            log.write("No ocor-bootstrap containers\n")
            return
        stats = run(["docker", "stats", "--no-stream", *ids], cwd=repository, timeout=20)
        log.write(stats.stdout + stats.stderr)
        for identity in ids:
            result = run(["docker", "logs", "--tail", "100", identity], cwd=repository, timeout=10)
            text = result.stdout + result.stderr
            log.write(f"\nContainer {identity}\n{redact(text, secrets)}")


def execute(repository: Path, command: list[str], label: str, timeout: int) -> str:
    result = run(command, cwd=repository, timeout=timeout)
    print(json.dumps({"operation": label, "exit_code": result.returncode}), flush=True)
    if result.returncode:
        # Commands can contain generated tokens: never print their argument vectors.
        raise BootstrapError(f"{label} failed")
    return result.stdout


def execute_logged(repository: Path, command: list[str], label: str, timeout: int, log_name: str) -> None:
    """Retain build progress even when the process fails or reaches its deadline.

    Used only before credential generation, for the locked Docker recipe.
    """
    log = repository / "reports/tests" / log_name
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as stream:
        try:
            result = subprocess.run(command, cwd=repository, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            print(json.dumps({"operation": label, "exit_code": 124, "log": str(log)}), flush=True)
            raise BootstrapError(f"timeout after {timeout}s: {label}; see {log_name}") from exc
    print(json.dumps({"operation": label, "exit_code": result.returncode, "log": str(log)}), flush=True)
    if result.returncode:
        raise BootstrapError(f"{label} failed; see {log_name}")


def owned_resources(repository: Path) -> dict[str, list[str]]:
    """Inventory every resource kind under the exact disposable Compose label."""
    commands = {
        "containers": ["docker", "ps", "-aq"],
        "volumes": ["docker", "volume", "ls", "-q"],
        "networks": ["docker", "network", "ls", "-q"],
    }
    return {
        kind: execute(repository, command + ["--filter", "label=com.docker.compose.project=ocor-bootstrap"],
                      f"teardown inventory {kind}", 10).split()
        for kind, command in commands.items()
    }


class ResourceInventory(TypedDict):
    containers: dict[str, str]
    volumes: list[str]
    networks: dict[str, str]


def session_inventory(repository: Path) -> ResourceInventory:
    containers = execute(repository, ["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"], "session container inventory", 10)
    return {"containers": {row["ID"]: row["Names"] for line in containers.splitlines() if (row := json.loads(line))},
            "volumes": execute(repository, ["docker", "volume", "ls", "-q"], "session volume inventory", 10).split(),
            "networks": {row["ID"]: row["Name"] for line in execute(repository, ["docker", "network", "ls", "--no-trunc", "--format", "{{json .}}"], "session network inventory", 10).splitlines() if (row := json.loads(line))}}


def owned_test_name(name: str) -> bool:
    return bool(re.fullmatch(r"ocor-(?:spike|poc|c5-backbone)-[A-Za-z0-9_.-]+", name))


def session_resources(events: list[dict[str, Any]]) -> ResourceInventory:
    """Bind anonymous volumes to test containers, even if mount precedes create."""
    containers = {}
    volumes = []
    for event in events:
        actor = event.get("Actor", {})
        if event.get("Type") == "container" and event.get("Action") in ("create", "start"):
            name = actor.get("Attributes", {}).get("name", "")
            if owned_test_name(name):
                containers[actor["ID"]] = name
    for event in events:
        actor = event.get("Actor", {})
        if event.get("Type") == "volume" and event.get("Action") == "mount" and actor.get("Attributes", {}).get("container") in containers:
            volumes.append(actor["ID"])
    networks = {event["Actor"]["ID"]: event["Actor"].get("Attributes", {}).get("name", "")
                for event in events if event.get("Type") == "network" and event.get("Action") == "create"
                and (owned_test_name(event["Actor"].get("Attributes", {}).get("name", ""))
                     or (event["Actor"].get("Attributes", {}).get("name") == "kind"
                         and "ocor-poc-control-plane" in containers.values()))}
    return {"containers": containers, "volumes": sorted(set(volumes)), "networks": networks}


class SessionRecorder:
    """Observe resource ownership; never infer ownership from a global volume delta."""

    def __init__(self, repository: Path):
        self.repository = repository
        self.path = repository / ".ocor/campaign-resources.json"
        self.since = str(int(time.time()))
        self.before = session_inventory(repository)
        self.events: list[dict[str, Any]] = []
        self.errors: list[str] = []
        # Since covers events between the inventory and the listener becoming ready.
        self.process = subprocess.Popen(["docker", "events", "--since", self.since, "--format", "{{json .}}"],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.thread = threading.Thread(target=self.observe, daemon=True)
        self.thread.start()

    def observe(self) -> None:
        try:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                event = json.loads(line)
                actor = event.get("Actor", {})
                attributes = actor.get("Attributes", {})
                if event.get("Type") in ("container", "volume", "network"):
                    if not isinstance(actor.get("ID"), str) or not actor["ID"]:
                        raise ValueError("ownership event has no resource identity")
                    if event.get("Type") == "container" and event.get("Action") in ("create", "start"):
                        if not isinstance(attributes.get("name"), str) or not attributes["name"]:
                            raise ValueError("container ownership event has no name")
                    if event.get("Type") == "volume" and event.get("Action") == "mount":
                        if not isinstance(attributes.get("container"), str) or not attributes["container"]:
                            raise ValueError("volume mount has no container binding")
                # Persist only ownership identifiers; no arbitrary labels or env values.
                if event.get("Type") in ("container", "volume", "network"):
                    self.events.append({"Type": event["Type"], "Action": event.get("Action"),
                                        "Actor": {"ID": actor.get("ID"), "Attributes": {
                                            key: attributes[key] for key in ("name", "container") if key in attributes}}})
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self.errors.append(str(exc))

    def finish(self) -> None:
        if not self.thread.is_alive():
            self.errors.append("Docker ownership observer ended unexpectedly")
        if self.process.poll() is not None:
            self.errors.append("Docker ownership event stream ended unexpectedly")
        else:
            self.process.terminate()
        self.process.wait(timeout=10)
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            self.errors.append("Docker ownership recorder did not stop")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"repository": str(self.repository.resolve()), "before_volumes": self.before["volumes"],
                  "before_containers": list(self.before["containers"]), "before_networks": list(self.before["networks"]),
                  "resources": session_resources(self.events), "errors": self.errors}
        self.path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        if self.errors:
            raise BootstrapError("ownership capture failed; session resources require diagnosis")


def cleanup_session_resources(repository: Path) -> dict[str, list[str]]:
    path = repository / ".ocor/campaign-resources.json"
    if not path.is_file():
        return {"containers": [], "volumes": []}
    record = json.loads(path.read_text())
    if record["repository"] != str(repository.resolve()):
        raise BootstrapError("resource ledger belongs to another worktree")
    resources = record["resources"]
    current = session_inventory(repository)
    containers = {identity: name for identity, name in resources["containers"].items()
                  if identity not in record.get("before_containers", []) and identity in current["containers"]}
    if any(not owned_test_name(name) or current["containers"][identity] != name for identity, name in containers.items()):
        raise BootstrapError("session container ownership mismatch")
    errors = list(record.get("errors", []))
    for identity in containers:
        try:
            execute(repository, ["docker", "rm", "--force", "--volumes", identity], "owned test container teardown", 60)
        except BootstrapError as exc:
            errors.append(str(exc))
    current = session_inventory(repository)
    volumes = set(resources["volumes"]) - set(record["before_volumes"])
    for volume in sorted(volumes & set(current["volumes"])):
        try:
            execute(repository, ["docker", "volume", "rm", volume], "attributed session volume teardown", 30)
        except BootstrapError as exc:
            errors.append(str(exc))
    current = session_inventory(repository)
    networks = {identity: name for identity, name in resources.get("networks", {}).items()
                if identity not in record.get("before_networks", []) and identity in current.get("networks", {})}
    if any(not (owned_test_name(name) or name == "kind") or current["networks"][identity] != name for identity, name in networks.items()):
        raise BootstrapError("session network ownership mismatch")
    for identity in networks:
        try:
            execute(repository, ["docker", "network", "rm", identity], "attributed test network teardown", 30)
        except BootstrapError as exc:
            errors.append(str(exc))
    current = session_inventory(repository)
    residual = {"containers": sorted(set(containers) & set(current["containers"])),
                "volumes": sorted(volumes & set(current["volumes"])),
                "networks": sorted(set(networks) & set(current.get("networks", {})))}
    print(json.dumps({"operation": "session resource residual", "residual": residual,
                      "errors": errors, "status": "FAIL" if errors or any(residual.values()) else "PASS"}), flush=True)
    if errors or any(residual.values()):
        raise BootstrapError("session resources remain or cleanup failed")
    return residual


def teardown(repository: Path) -> dict[str, object]:
    """Always export residue and preserve failures; remove test attachments first."""
    errors = []
    try:
        cleanup_session_resources(repository)
    except (BootstrapError, OSError, ValueError, subprocess.SubprocessError) as exc:
        errors.append(str(exc))
    credentials = (repository / ".ocor/bootstrap.env").is_file()
    if credentials:
        try:
            execute(repository, [sys.executable, "scripts/reset_test_environment.py", "--execute"], "governed teardown", 180)
        except (BootstrapError, OSError, subprocess.SubprocessError) as exc:
            errors.append(str(exc))
    residual = owned_resources(repository)
    failed = bool(errors or any(residual.values()))
    print(json.dumps({"operation": "teardown residual", "residual": residual, "errors": errors,
                      "status": "FAIL" if failed else "PASS"}), flush=True)
    if failed:
        detail = "owned resources remain after teardown" if credentials else "teardown credentials absent but owned resources remain"
        raise BootstrapError(detail + ("; " + "; ".join(errors) if errors else ""))
    return {"status": "PASS", "operation": "teardown", "result": "REMOVED" if credentials else "ALREADY_REMOVED", "residual": residual}


def prepare_ca(repository: Path, env_file: Path) -> None:
    values = dict(line.split("=", 1) for line in env_file.read_text().splitlines() if "=" in line)
    directory = Path(values["OCOR_SPIRE_BOOTSTRAP_DIR"]).resolve()
    if directory != repository / ".ocor/spire":
        raise BootstrapError("CI CA must be owned by this worktree")
    paths = [directory / "ca.key", directory / "ca.crt", directory]
    if any(path.is_symlink() for path in paths) or not all(path.exists() for path in paths):
        raise BootstrapError("invalid CI CA paths")
    # SPIRE's pinned image runs as 1000:1000. Hosted runners can have a different UID.
    # Restrict chown to the generated CA, leaving the runner-owned env file 0600.
    for path in paths:
        if (path.stat().st_uid, path.stat().st_gid) != (1000, 1000):
            execute(repository, ["sudo", "-n", "chown", "1000:1000", str(path)], "CA ownership", 10)
    # Modes were set before chown by write_secret_file; changing them after chown
    # would require an unnecessary second privileged operation on hosted runners.


def ci_resources(repository: Path) -> Path:
    """Constrain Fuseki's default 4 GiB heap within its unchanged 2 GiB cgroup."""
    profile = repository / ".ocor/ci-resources.yaml"
    if profile.is_symlink():
        raise BootstrapError("CI resource profile must not be a symlink")
    # JSON is a YAML subset. Keep the governed Compose, image and Dockerfile intact.
    profile.write_text(json.dumps({"services": {"fuseki": {"environment": {
        "JVM_ARGS": "-Xms128m -Xmx1G"
    }}}}, indent=2, sort_keys=True) + "\n")
    return profile


def running_jvm_args(processes: str) -> list[str]:
    rows = [line.split() for line in processes.splitlines() if line.split()]
    commands = [row[1:] if row[0].isdigit() else row for row in rows]
    jvms = [argv for argv in commands if argv and Path(argv[0]).name == "java"]
    if len(jvms) != 1:
        raise BootstrapError("Fuseki Java process is absent or ambiguous")
    argv = jvms[0]
    heap_args = [arg for arg in argv if arg.startswith(("-Xms", "-Xmx"))]
    if heap_args != ["-Xms128m", "-Xmx1G"] or any(arg.startswith(("-XX:MaxHeapSize", "-XX:InitialHeapSize", "-XX:MaxRAM")) for arg in argv):
        raise BootstrapError("Fuseki running JVM did not consume the CI heap bounds")
    return argv


def provision(repository: Path, timeout: int) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    def budget() -> int:
        seconds = int(deadline - time.monotonic())
        if seconds < 1:
            raise BootstrapError("total provisioning budget exhausted")
        return seconds

    def bounded_retry(command: list[str], *, operation_timeout: int, attempts: int = 5) -> subprocess.CompletedProcess[str]:
        for attempt in range(attempts):
            result = run(command, cwd=repository, timeout=min(operation_timeout, budget()))
            if result.returncode == 0:
                return result
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, budget()))
        return result

    errors = validate_locks(repository)
    if errors:
        raise BootstrapError("; ".join(errors))
    env_file = repository / ".ocor/bootstrap.env"
    if env_file.exists():
        raise BootstrapError("CI provisioning requires a fresh worktree-local credential file")
    present = execute(repository, ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=ocor-bootstrap"], "single stack guard", min(30, budget()))
    if present.strip():
        raise BootstrapError("reset the existing ocor-bootstrap stack before CI provisioning")
    services = load_json(repository / "infra/services.lock.json")["services"]
    for service in services:
        if "image" in service:
            result = bounded_retry(["docker", "pull", service["image"]], operation_timeout=timeout)
            if result.returncode:
                raise BootstrapError(f"pinned pull failed: {service['id']}")
    fuseki = next(service for service in services if service["id"] == "fuseki")["build"]
    dockerfile = (repository / fuseki["dockerfile"]).read_text()
    if f"FROM {fuseki['base_image']}\n" not in dockerfile or fuseki["source_sha512"] not in dockerfile:
        raise BootstrapError("Fuseki recipe differs from the locked base/source")
    archive, acquisition = acquire(repository, timeout=budget())
    with build_context(repository, archive) as context:
        execute_logged(repository, ["docker", "build", "--progress=plain", "--pull", "-t", fuseki["output_image"], str(context)], "Fuseki recipe build", budget(), "ci_fuseki_build.log")
    image_id = execute(repository, ["docker", "image", "inspect", fuseki["output_image"], "--format", "{{.Id}}"], "Fuseki identity capture", min(30, budget())).strip()
    env_file = write_secret_file(repository)
    ca = repository / ".ocor/spire"
    ca.chmod(0o700)
    (ca / "ca.key").chmod(0o600)
    (ca / "ca.crt").chmod(0o600)
    prepare_ca(repository, env_file)
    resources = ci_resources(repository)
    compose = ["docker", "compose", "-p", "ocor-bootstrap", "--env-file", str(env_file), "-f", "deploy/bootstrap/compose.yaml", "-f", str(resources)]
    server_image = next(service for service in services if service["id"] == "spire-server")["image"]
    user = execute(repository, ["docker", "image", "inspect", server_image, "--format", "{{.Config.User}}"], "SPIRE image UID", min(30, budget())).strip()
    if user != "1000:1000":
        raise BootstrapError("unexpected pinned SPIRE image UID")
    execute(repository, compose + ["up", "--detach", "--wait", "--wait-timeout", str(budget()), "spire-server"], "SPIRE server", budget())
    token = execute(repository, compose + ["exec", "-T", "spire-server", "/opt/spire/bin/spire-server", "token", "generate", "-socketPath", "/run/spire/sockets/server.sock"], "SPIRE token", min(30, budget()))
    if "Token:" not in token:
        raise BootstrapError("SPIRE token output invalid")
    replace_env(env_file, "OCOR_SPIRE_JOIN_TOKEN", token.split("Token:", 1)[1].splitlines()[0].strip())
    execute(repository, compose + ["up", "--detach", "--wait", "--wait-timeout", str(budget()), "--no-build"], "complete stack", budget())
    # The pinned image contains a JRE, not jcmd, and PID 1 is Docker's init.
    # Bind the actual Java process to a flag probe in that same runtime.
    processes = execute(repository, ["docker", "top", "ocor-bootstrap-fuseki-1", "-eo", "pid,args"], "Fuseki running JVM arguments", min(30, budget()))
    running_jvm_args(processes)
    flags = execute(repository, ["docker", "exec", "ocor-bootstrap-fuseki-1", "java", "-Xms128m", "-Xmx1G", "-XX:+PrintFlagsFinal", "-version"], "Fuseki JVM heap flag probe", min(30, budget()))
    if not re.search(r"\bMaxHeapSize\s*=\s*1073741824\b", flags):
        raise BootstrapError("Fuseki heap is not bounded to 1 GiB inside its 2 GiB cgroup")
    agent = ["docker", "exec", "ocor-bootstrap-spire-agent-1", "/opt/spire/bin/spire-agent"]
    ready = bounded_retry(agent + ["healthcheck", "-socketPath", "/run/spire/sockets/agent.sock"], operation_timeout=10)
    if ready.returncode:
        raise BootstrapError("SPIRE agent did not become healthy")
    server = ["docker", "exec", "ocor-bootstrap-spire-server-1", "/opt/spire/bin/spire-server"]
    agents = json.loads(execute(repository, server + ["agent", "list", "-socketPath", "/run/spire/sockets/server.sock", "-output", "json"], "SPIRE attested agent", min(30, budget())))["agents"]
    if len(agents) != 1 or agents[0]["id"]["trust_domain"] != "ocor.test":
        raise BootstrapError("unexpected SPIRE attested agent set")
    identity = agents[0]["id"]
    parent = f"spiffe://{identity['trust_domain']}{identity['path']}"
    execute(repository, server + ["entry", "create", "-socketPath", "/run/spire/sockets/server.sock", "-parentID", parent, "-spiffeID", "spiffe://ocor.test/ocor/control-plane", "-selector", "unix:uid:0"], "control-plane workload entry", min(30, budget()))
    material = bounded_retry(agent + ["api", "fetch", "x509", "-socketPath", "/run/spire/sockets/agent.sock", "-output", "json"], operation_timeout=15)
    if material.returncode or not any(item.get("spiffe_id") == "spiffe://ocor.test/ocor/control-plane" for item in json.loads(material.stdout).get("svids", [])):
        raise BootstrapError("control-plane SVID absent")
    print(json.dumps({"operation": "control-plane SVID", "exit_code": 0}), flush=True)
    for script in ("deploy/bootstrap/init/initialize_services.py", "deploy/bootstrap/fixtures/load_fixtures.py"):
        execute(repository, [sys.executable, script, "--env-file", str(env_file)], script, budget())
    health = json.loads(execute(repository, [sys.executable, "scripts/verify_external_services.py", "--execute", "--typed"], "typed service health", budget()))
    return {"status": "PASS", "fuseki_built_image_id": image_id, "fuseki_lock_image_id": fuseki["output_sha256"], "fuseki_max_heap_bytes": 1073741824, "services": health, "fuseki_archive": acquisition, "provisioning_seconds": round(timeout - (deadline - time.monotonic()), 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--teardown", action="store_true", help="remove this disposable CI stack or verify its absence")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 600:
        parser.error("timeout must be between 1 and 600 seconds")
    repository = root()
    if args.teardown:
        if not args.execute:
            print(json.dumps({"mode": "CHECK_ONLY", "operation": "teardown", "status": "PASS"}))
            return 0
        try:
            print(json.dumps(teardown(repository), indent=2, sort_keys=True))
            return 0
        except (BootstrapError, OSError, ValueError, subprocess.SubprocessError) as exc:
            print(json.dumps({"status": "FAIL", "operation": "teardown", "error": str(exc)}))
            return 1
    if not args.execute:
        errors = validate_locks(repository)
        print(json.dumps({"mode": "CHECK_ONLY", "status": "FAIL" if errors else "PASS", "errors": errors}))
        return int(bool(errors))
    try:
        print(json.dumps(provision(repository, args.timeout), indent=2, sort_keys=True))
        return 0
    except (BootstrapError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}))
        collect_stack_diagnostics(repository, repository / "reports/tests/ci_bootstrap_diagnostics.log")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
