#!/usr/bin/env python3
"""OCOR-DEV-REM-0032 — CPU-limited relay health scenario (RED/GREEN instrument).

Reproduces the setup of the 0049 case that failed in CI (run 38548656297, part 3):
several PoC Compose projects start their ten `ocor-relay-*` services at the same time
on a runner with 4 vCPU. The CPU limit is declared and repeatable: every container of
the scenario (relays and the optional synthetic load) is pinned with `cpuset` to the
same four host cores (`--cpuset`, default `0-3`); healthcheck execs run inside the
relay cgroup and inherit the pin. The synthetic load (`--load N`) is N single-thread
busy loops, each in its own container (own CFS group, like the separate processes of
the CI runner), pinned to the same cores.

The scenario only reads the Compose file under test; it adds an override that sets
`cpuset` on the relays and nothing else, so healthcheck, command, image, networks and
environment are exactly those of the file under test.

Output (JSON): per-project `up --wait` result, every `health_status` Docker event of
the scenario containers, the Health.Log of each container that became unhealthy
(captured before teardown), the measured CPU cost per probe and the teardown residue.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import yaml

IMAGE = "python:3.11@sha256:c7220863385ee39fb6d822da81f4469d0cd33ff893d92ce94105e5c3f4b95fe2"
LABEL = "ocor.rem0032.scenario"


def relay_services(compose: dict[str, Any]) -> list[str]:
    return sorted(name for name in compose["services"] if name.startswith("ocor-relay-"))


def compose_env(env_file: Path, vault: Path) -> dict[str, str]:
    values = dict(line.strip().split("=", 1) for line in env_file.read_text().splitlines() if "=" in line)
    return {**os.environ, **values, "OCOR_OPS_OPERATOR_TOKEN": "rem0032-scenario-not-a-secret",
            "OCOR_BACKUP_VAULT_DIR": str(vault), "OCOR_OPS_UID": str(os.getuid()), "OCOR_OPS_GID": str(os.getgid())}


def docker(*args: str, timeout: int = 120, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=check)


def cgroup_usage_usec(container_id: str) -> int | None:
    path = Path(f"/sys/fs/cgroup/system.slice/docker-{container_id}.scope/cpu.stat")
    try:
        for line in path.read_text().splitlines():
            if line.startswith("usage_usec "):
                return int(line.split()[1])
    except OSError:
        return None
    return None


def run(args: argparse.Namespace) -> dict[str, Any]:
    compose_path = Path(args.compose).resolve()
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    relays = relay_services(compose)
    work = Path(tempfile.mkdtemp(prefix="rem0032-scenario-"))
    vault = work / "vault"
    vault.mkdir()
    override = work / "cpuset.override.yaml"
    override.write_text(yaml.safe_dump({"services": {r: {"cpuset": args.cpuset} for r in relays}}))
    env = compose_env(Path(args.env_file), vault)
    projects = [f"rem0032-{args.label}-{i}" for i in range(1, args.projects + 1)]
    result: dict[str, Any] = {
        "compose": str(compose_path), "cpuset": args.cpuset, "label": args.label, "load_processes": args.load,
        "observe_seconds": args.observe, "projects": projects, "relays_per_project": len(relays),
        "relay_healthcheck": compose.get("x-relay", {}).get("healthcheck"),
        "started_at": time.time(),
    }

    events_proc = subprocess.Popen(
        ["docker", "events", "--format", "{{json .}}", "--filter", "type=container",
         "--filter", "event=health_status", "--filter", "event=die", "--filter", "event=start"],
        stdout=subprocess.PIPE, text=True)
    events: list[dict[str, Any]] = []

    def collect() -> None:
        assert events_proc.stdout is not None
        for line in events_proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            attrs = ev.get("Actor", {}).get("Attributes", {})
            name = attrs.get("name", "")
            if any(name.startswith(p + "-") for p in projects):
                events.append({"time": ev.get("timeNano", 0) / 1e9, "action": ev.get("Action") or ev.get("status"),
                               "name": name, "exitCode": attrs.get("exitCode")})

    collector = threading.Thread(target=collect, daemon=True)
    collector.start()

    load_names = [f"rem0032-load-{args.label}-{i}" for i in range(args.load)]
    try:
        for name in load_names:
            docker("run", "-d", "--rm", "--name", name, "--label", f"{LABEL}={args.label}", "--cpuset-cpus",
                   args.cpuset, "--network", "none", "--entrypoint", "python3", IMAGE, "-c", "while True: pass",
                   check=True)
        time.sleep(2 if load_names else 0)

        ups: dict[str, dict[str, Any]] = {}

        def up(project: str) -> None:
            start = time.time()
            proc = subprocess.run(
                ["docker", "compose", "-p", project, "-f", str(compose_path), "-f", str(override), "--profile",
                 "observability", "up", "-d", "--wait", "--wait-timeout", str(args.wait_timeout), *relays],
                capture_output=True, text=True, env=env, timeout=args.wait_timeout + 120, check=False)
            ups[project] = {"exit_code": proc.returncode, "seconds": round(time.time() - start, 3),
                            "output_tail": (proc.stdout + proc.stderr)[-1500:]}

        threads = [threading.Thread(target=up, args=(p,)) for p in projects]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        result["up"] = ups

        ids: dict[str, str] = {}
        for p in projects:
            for cid in docker("ps", "-q", "--no-trunc", "--filter", f"label=com.docker.compose.project={p}").stdout.split():
                name = docker("inspect", "-f", "{{.Name}}", cid).stdout.strip().lstrip("/")
                ids[name] = cid
        usage0 = {n: cgroup_usage_usec(c) for n, c in ids.items()}
        t0 = time.time()
        time.sleep(args.observe)
        elapsed = time.time() - t0
        usage1 = {n: cgroup_usage_usec(c) for n, c in ids.items()}
        result["steady_window_seconds"] = round(elapsed, 3)
        cpu = {n: (usage1[n] - usage0[n]) / 1e6 for n in ids if usage0.get(n) is not None and usage1.get(n) is not None}
        result["relay_cpu_seconds_in_window"] = round(sum(cpu.values()), 3)
        result["relay_cpu_cores_in_window"] = round(sum(cpu.values()) / elapsed, 3) if elapsed else None

        states = {}
        for n, c in ids.items():
            st = json.loads(docker("inspect", "-f", "{{json .State}}", c).stdout or "{}")
            health = st.get("Health") or {}
            states[n] = {"status": st.get("Status"), "health": health.get("Status"),
                         "failing_streak": health.get("FailingStreak"), "oom_killed": st.get("OOMKilled"),
                         "log": health.get("Log", []) if health.get("Status") != "healthy" else health.get("Log", [])[-2:]}
        result["final_states"] = states
    finally:
        downs = {}
        for p in projects:
            proc = subprocess.run(["docker", "compose", "-p", p, "-f", str(compose_path), "-f", str(override),
                                   "--profile", "observability", "down", "-v", "--remove-orphans", "-t", "5"],
                                  capture_output=True, text=True, env=env, timeout=300, check=False)
            downs[p] = proc.returncode
        for name in load_names:
            docker("rm", "-f", name)
        time.sleep(1)
        events_proc.terminate()
        result["down"] = downs
        residue = []
        for p in projects:
            for kind, cmd in (("container", ["ps", "-aq"]), ("volume", ["volume", "ls", "-q"]),
                              ("network", ["network", "ls", "-q"])):
                residue += [f"{kind} {i}" for i in docker(*cmd, "--filter", f"label=com.docker.compose.project={p}").stdout.split()]
        residue += [f"container {i}" for i in docker("ps", "-aq", "--filter", f"label={LABEL}={args.label}").stdout.split()]
        result["residue"] = residue

    unhealthy = [e for e in events if e["action"] == "health_status: unhealthy"]
    result["health_events"] = events
    result["unhealthy_events"] = unhealthy
    result["unhealthy_containers"] = sorted({e["name"] for e in unhealthy})
    result["finished_at"] = time.time()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--compose", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--projects", type=int, default=3)
    parser.add_argument("--cpuset", default="0-3")
    parser.add_argument("--load", type=int, default=0)
    parser.add_argument("--observe", type=int, default=90)
    parser.add_argument("--wait-timeout", type=int, default=240)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    result = run(args)
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: result[k] for k in ("label", "unhealthy_containers", "relay_cpu_cores_in_window", "residue")}
                     | {"up": {p: u["exit_code"] for p, u in result.get("up", {}).items()}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
