"""OCOR-DEV-REM-0032 — 0049 relay healthcheck load budget.

PO decision REM-0017-CI-0049-RELAY-PROBE-REMEDIATION (2026-10-14). The relay healthcheck
of `deploy/helm/ocor-poc/compose.profiles.yaml` started, every 2 s, an interpreter that
compiled the whole ops agent and re-validated the profile before opening a socket; with
three PoC projects (30 relays) on 4 vCPU the probes saturate the runner and relays go
unhealthy in the setup of 0049 cases.

Static cases (no Docker): the probe is a TCP connect to the relay's own allowed-flow port,
the port matches `isolation.allowedFlows`, the dead-relay bound is <= 30 s, and nothing in
the file other than the relay healthcheck and the per-relay port variable differs from the
0049 task stage `a0ee43d`.

Live cases (real Docker, the digest-pinned image, the Compose file under test):
* negative controls: a relay whose listener dies after `start_period` becomes unhealthy
  within 30 s; a relay probed on a port it does not serve never becomes healthy;
* RED/GREEN: the CPU-limited scenario of `rem0032_relay_scenario.py` (three projects, 4
  pinned cores, 8 single-thread loads) drives relays unhealthy with the a0ee43d probe and
  keeps every relay healthy with the probe under test.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy/helm/ocor-poc/compose.profiles.yaml"
TASK_STAGE = "a0ee43d4e502f3589cd857cfec4238eab13fe8e7"
SCENARIO = ROOT / "reports/tests/rem0032_relay_scenario.py"
IMAGE = "python:3.11@sha256:c7220863385ee39fb6d822da81f4469d0cd33ff893d92ce94105e5c3f4b95fe2"
DEAD_RELAY_BOUND_SECONDS = 30
# sha256 of the canonical JSON of the a0ee43d Compose file without the relay healthcheck
# and without OCOR_RELAY_FLOW_PORT (computed once from `git show a0ee43d:<file>`).
INVARIANT_SHA256 = "2fa3d100995c0cd9f11d84726bfd89e3920991ee0e1f6e159057414bd55c9978"


def load(text: str) -> dict[str, Any]:
    return yaml.safe_load(text)


def compose() -> dict[str, Any]:
    return load(COMPOSE.read_text(encoding="utf-8"))


def relays(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n: s for n, s in doc["services"].items() if n.startswith("ocor-relay-")}


def profile(doc: dict[str, Any]) -> dict[str, Any]:
    return json.loads(doc["configs"]["ocor-poc-profile"]["content"])


def seconds(value: str) -> float:
    total, number = 0.0, ""
    for ch in value:
        if ch.isdigit() or ch == ".":
            number += ch
        else:
            total += float(number) * {"h": 3600, "m": 60, "s": 1}[ch]
            number = ""
    return total


def invariant_digest(doc: dict[str, Any]) -> str:
    doc = copy.deepcopy(doc)
    doc["x-relay"].pop("healthcheck", None)
    for name, svc in doc["services"].items():
        if name.startswith("ocor-relay-"):
            svc.pop("healthcheck", None)
            svc.get("environment", {}).pop("OCOR_RELAY_FLOW_PORT", None)
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# --------------------------------------------------------------------------- static


def test_probe_is_a_tcp_connect_to_the_own_flow_port_without_the_ops_agent():
    check = compose()["x-relay"]["healthcheck"]
    test = check["test"]
    assert test[:3] == ["CMD", "bash", "-c"], test
    assert "ocor_ops_agent" not in " ".join(test) and "python" not in " ".join(test)
    # Compose turns `$$` into `$`: bash expands the per-relay variable, failing if unset.
    assert test[3] == 'exec 3<>"/dev/tcp/127.0.0.1/$${OCOR_RELAY_FLOW_PORT:?}"'
    for name, svc in relays(compose()).items():  # `<<: *relay` merges the anchor into each relay
        assert svc["healthcheck"] == check, f"{name} must use the x-relay healthcheck"


def test_each_relay_probes_exactly_the_port_of_its_allowed_flow():
    doc = compose()
    flows = {f["host"]: f["port"] for f in profile(doc)["isolation"]["allowedFlows"]}
    seen = {}
    for name, svc in relays(doc).items():
        env = svc["environment"]
        assert set(env) == {"OCOR_RELAY_FLOW_HOST", "OCOR_RELAY_FLOW_PORT"}, name
        assert isinstance(env["OCOR_RELAY_FLOW_PORT"], str), name
        seen[env["OCOR_RELAY_FLOW_HOST"]] = int(env["OCOR_RELAY_FLOW_PORT"])
    assert seen == flows


def test_dead_relay_bound_and_startup_grace():
    check = compose()["x-relay"]["healthcheck"]
    interval, timeout, retries = seconds(check["interval"]), seconds(check["timeout"]), int(check["retries"])
    assert seconds(check["start_period"]) > 0
    # Refused connect (dead listener): one failure per interval.
    assert interval * retries <= DEAD_RELAY_BOUND_SECONDS
    # Hung probe: each failing probe lasts up to `timeout` before the next interval.
    assert (interval + timeout) * retries <= DEAD_RELAY_BOUND_SECONDS


def test_everything_else_is_identical_to_the_0049_task_stage():
    assert invariant_digest(compose()) == INVARIANT_SHA256
    staged = subprocess.run(["git", "show", f"{TASK_STAGE}:deploy/helm/ocor-poc/compose.profiles.yaml"],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    if staged.returncode == 0:  # the pinned digest above is authoritative without git history
        old = load(staged.stdout)
        assert invariant_digest(old) == INVARIANT_SHA256
        assert old["configs"] == compose()["configs"], "ops agent and profile must be unchanged"
        assert old["x-relay"]["healthcheck"]["test"][2:4] == ["/opt/ocor/ocor_ops_agent.py", "relay-probe"]


# --------------------------------------------------------------------------- live


def _env_file() -> Path:
    for candidate in (ROOT / ".ocor/bootstrap.env", Path.home() / ".ocor-bootstrap-secrets/ocor-bootstrap.env"):
        if candidate.exists():
            return candidate
    pytest.fail("ocor-bootstrap env file not found: the real stack is mandatory qualifying evidence")


def _require_docker() -> None:
    if subprocess.run(["docker", "info"], capture_output=True, check=False).returncode != 0:
        pytest.fail("docker is unavailable: the live cases are mandatory")
    net = os.environ.get("OCOR_BOOTSTRAP_NETWORK", "ocor-bootstrap_ocor-bootstrap")
    if subprocess.run(["docker", "network", "inspect", net], capture_output=True, check=False).returncode != 0:
        pytest.fail(f"bootstrap network {net} is missing: start the ocor-bootstrap stack")


def _compose_env(vault: Path) -> dict[str, str]:
    values = dict(line.strip().split("=", 1) for line in _env_file().read_text().splitlines() if "=" in line)
    return {**os.environ, **values, "OCOR_OPS_OPERATOR_TOKEN": "rem0032-test-not-a-secret",
            "OCOR_BACKUP_VAULT_DIR": str(vault), "OCOR_OPS_UID": str(os.getuid()), "OCOR_OPS_GID": str(os.getgid())}


def _health(container: str) -> dict[str, Any]:
    out = subprocess.run(["docker", "inspect", "-f", "{{json .State}}", container], capture_output=True, text=True,
                         check=True).stdout
    return json.loads(out)


def test_dead_relay_after_start_period_turns_unhealthy_within_bound(tmp_path):
    """Listener killed after start_period -> unhealthy <= 30 s; a wrong flow port never turns
    healthy (the probe checks the relay's own flow, not any open port); an untouched relay
    stays healthy. Healthcheck, image and environment are those of the file under test;
    the override only wraps the relay command so the container outlives its listener."""
    _require_docker()
    vault = tmp_path / "vault"
    vault.mkdir()
    project = f"rem0032-neg-{os.getpid()}"
    wrapped = ("python3 /opt/ocor/ocor_ops_agent.py relay --profile /etc/ocor/profile.json "
               "--upstream-template x-{host} & echo $! > /tmp/relay.pid; wait; sleep infinity")
    override = tmp_path / "override.yaml"
    override.write_text(yaml.safe_dump({"services": {
        "ocor-relay-opa": {"command": ["bash", "-c", wrapped]},
        "ocor-relay-typedb": {"environment": {"OCOR_RELAY_FLOW_PORT": "18000"}},
    }}))
    files = ["-f", str(COMPOSE), "-f", str(override)]
    env = _compose_env(vault)
    services = ["ocor-relay-opa", "ocor-relay-typedb", "ocor-relay-qdrant"]
    try:
        up = subprocess.run(["docker", "compose", "-p", project, *files, "--profile", "observability", "up", "-d",
                             *services], capture_output=True, text=True, env=env, check=False, timeout=300)
        assert up.returncode == 0, up.stdout + up.stderr
        opa, typedb, qdrant = (f"{project}-{s}-1" for s in services)
        start_period = seconds(compose()["x-relay"]["healthcheck"]["start_period"])
        started = _health(opa)["StartedAt"]
        deadline = time.time() + 120
        while _health(opa).get("Health", {}).get("Status") != "healthy":
            assert time.time() < deadline, _health(opa)
            time.sleep(1)
        # Kill the listener once the start period is over, so failures count.
        while True:
            age = float(subprocess.run(["docker", "exec", opa, "bash", "-c",
                                        "echo $(( $(date +%s) - $(stat -c %Y /tmp/relay.pid) ))"],
                                       capture_output=True, text=True, check=True).stdout)
            if age > start_period + 2:
                break
            time.sleep(1)
        subprocess.run(["docker", "exec", opa, "bash", "-c", "kill $(cat /tmp/relay.pid)"], check=True)
        killed = time.time()
        while _health(opa)["Health"]["Status"] != "unhealthy":
            assert time.time() - killed <= DEAD_RELAY_BOUND_SECONDS + 2, _health(opa)["Health"]
            time.sleep(0.5)
        detected = time.time() - killed
        assert detected <= DEAD_RELAY_BOUND_SECONDS, detected
        assert _health(opa)["Running"] is True and _health(opa)["StartedAt"] == started
        refused = [entry for entry in _health(opa)["Health"]["Log"] if entry["ExitCode"] != 0]
        assert refused and all("Connection refused" in entry["Output"] for entry in refused[-3:]), refused
        wrong = _health(typedb)["Health"]
        assert wrong["Status"] != "healthy" and all(e["ExitCode"] != 0 for e in wrong["Log"]), wrong
        assert _health(qdrant)["Health"]["Status"] == "healthy"
        print(json.dumps({"dead_relay_detected_seconds": round(detected, 3), "start_period": start_period}))
    finally:
        subprocess.run(["docker", "compose", "-p", project, *files, "--profile", "observability", "down", "-v",
                        "--remove-orphans", "-t", "2"], capture_output=True, env=env, check=False, timeout=300)
        left = subprocess.run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"],
                              capture_output=True, text=True, check=False).stdout.split()
        assert not left, left


def _scenario(compose_path: Path, label: str, out: Path) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, str(SCENARIO), "--compose", str(compose_path), "--env-file",
                           str(_env_file()), "--label", label, "--projects", "3", "--cpuset", "0-3", "--load", "8",
                           "--observe", "120", "--out", str(out)], capture_output=True, text=True, check=False,
                          timeout=900)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(out.read_text())
    assert result["residue"] == [], result["residue"]
    return result


def test_red_task_stage_probe_turns_relays_unhealthy_under_cpu_limit(tmp_path):
    _require_docker()
    staged = subprocess.run(["git", "show", f"{TASK_STAGE}:deploy/helm/ocor-poc/compose.profiles.yaml"],
                            cwd=ROOT, capture_output=True, text=True, check=True).stdout
    path = tmp_path / "compose.task-stage.yaml"
    path.write_text(staged)
    out = Path(os.environ.get("REM0032_SCENARIO_OUT", tmp_path)) / "red.json"
    result = _scenario(path, f"red{os.getpid()}", out)
    assert result["unhealthy_containers"], "RED must show at least one unhealthy relay with the old probe"
    assert any(u["exit_code"] != 0 for u in result["up"].values())


def test_green_probe_keeps_every_relay_healthy_under_cpu_limit(tmp_path):
    _require_docker()
    out = Path(os.environ.get("REM0032_SCENARIO_OUT", tmp_path)) / "green.json"
    result = _scenario(COMPOSE, f"green{os.getpid()}", out)
    assert result["unhealthy_containers"] == [], result["unhealthy_events"]
    assert all(u["exit_code"] == 0 for u in result["up"].values()), result["up"]
    assert all(s["health"] == "healthy" for s in result["final_states"].values()), result["final_states"]
