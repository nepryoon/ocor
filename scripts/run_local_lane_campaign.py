#!/usr/bin/env python3
"""Partition and union checks for the local full suite in two parallel lanes (OCOR-DEV-REM-0037).

PO LOCAL-SUITE-SPLIT (2026-10-25) as reactivated by LOCAL-SUITE-SPLIT-REACTIVATION
(2026-10-26). Additive orchestrator: it imports the sealed supervisor
``run_qualifying_campaign.py`` and never rebinds it, so the serial campaign,
the CI parts and the verifier procedure keep their behaviour.

- The partition is deterministic and computed from the per-case times of the
  serial measurement campaign (``WEIGHTS_PATH``). Every module stays whole except
  the cases of ``INDEPENDENT_MODULES`` (0049), which are distributed across the
  lanes; each lane keeps collection order.
- The union of the lanes' JUnit must equal the collection exactly, zero skips.
- Two lanes start only if MemAvailable reaches the measured start threshold;
  otherwise the serial suite runs and the fallback is recorded.
- The governed full-suite limits apply to the whole campaign, not to a lane.
- Each lane runs in an OCOR-labelled sandbox with its own dockerd, network
  namespace, /run, /tmp and HOME, and a self-contained clone of the exact head
  at the same absolute path. The stack keeps its default names and ports
  (ocor-bootstrap, ocor-poc, 127.0.0.1) because daemon and network are private;
  both lanes use a sandbox, so the host daemon's development stack is untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple, Protocol

import bootstrap_ci_environment as bootstrap_ci
import observe_kind_teardown as kind_observer
import run_qualifying_campaign as campaign
from run_qualifying_campaign import CampaignError

LANE_COUNT = 2
FULL_SUITE_LIMIT_SECONDS = campaign.FULL_SUITE_LIMIT_SECONDS
PO_DECISION_THRESHOLD_SECONDS = campaign.PO_DECISION_THRESHOLD_SECONDS
# Measured in the serial campaign at 266cf12 (REM-0037 preimplementation record):
# 2 x conservative single-lane peak occupancy (5670.3 MiB) + the unchanged guard.
TWO_LANE_START_THRESHOLD_MIB = 14340.6
MEMORY_GUARD_MIB = 3000
# Partition weights only; they never select or exclude a case.
MINIMUM_MEASURED_SECONDS = 0.5
DEFAULT_CASE_SECONDS = 0.05
WEIGHTS_PATH = Path(__file__).resolve().parents[1] / "reports/assurance/OCOR-DEV-REM-0037-RCCAD/lane_weights.json"
# Lane sandboxes: every host resource carries the campaign label; the root image
# is imported locally from an empty tree (no registry image is ever pulled).
LANE_LABEL = "org.ocor.local-lane"
SANDBOX_ROOT_IMAGE = "ocor-local-lane-root:empty"
SANDBOX_READY_SECONDS = 60
SANDBOX_POLL_SECONDS = 2
SANDBOX_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
LANE_SYSTEM_PATH = ("/usr/local/bin", "/usr/bin", "/bin")
EMPTY_ROOT_DIRS = ("dev", "etc", "home", "proc", "root", "run", "sys", "tmp", "usr", "var", "var/lib", "var/lib/docker")
USR_MERGED_LINKS = ("bin", "sbin", "lib", "lib64", "lib32", "libx32")
PROVISION_TIMEOUT_SECONDS = 1200
# A docker exec that reaches the sandbox before the delegation lands in its root
# cgroup and makes the subtree_control write fail; the init moves late
# processes and retries, bounded, then refuses to start dockerd.
CGROUP_DELEGATION_ATTEMPTS = 50
CGROUP_DELEGATION_PAUSE_SECONDS = 0.2
REQUIRED_CONTROLLERS = frozenset({"cpu", "cpuset", "io", "memory", "pids"})


def weight_key(nodeid: str) -> str:
    classname, name = campaign.junit_identity(nodeid)
    return f"{classname}::{name}"


def case_weight(nodeid: str, weights: dict[str, float]) -> float:
    return float(weights.get(weight_key(nodeid), DEFAULT_CASE_SECONDS))


def derive_weights(junit: Path) -> dict[str, Any]:
    """Reproducible weights file content from a PASS serial JUnit."""
    root = ET.parse(junit).getroot()
    cases = list(root.iter("testcase"))
    weights = {f"{case.get('classname', '')}::{case.get('name', '')}": round(float(case.get("time", "0")), 3)
               for case in cases}
    return {
        "default_case_seconds": DEFAULT_CASE_SECONDS,
        "minimum_case_seconds": MINIMUM_MEASURED_SECONDS,
        "source": {"cases": len(cases), "junit_sha256": hashlib.sha256(junit.read_bytes()).hexdigest()},
        "weights": {key: value for key, value in sorted(weights.items()) if value >= MINIMUM_MEASURED_SECONDS},
    }


def load_weights(path: Path = WEIGHTS_PATH) -> dict[str, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key: float(value) for key, value in data["weights"].items()}


def lane_partition(nodeids: list[str], weights: dict[str, float], *, lanes: int = LANE_COUNT) -> list[list[str]]:
    """Longest-processing-time assignment of whole units; ties resolve by node ID and lane index."""
    if lanes != LANE_COUNT:
        raise CampaignError(f"the local suite runs in exactly {LANE_COUNT} lanes")
    if not nodeids or len(nodeids) != len(set(nodeids)):
        raise CampaignError(f"cannot partition {len(nodeids)} collected tests with duplicates or none")
    if len({campaign.junit_identity(node) for node in nodeids}) != len(nodeids):
        raise CampaignError("collected node IDs are not uniquely identifiable in JUnit")
    units = campaign.partition_units(nodeids)
    if len(units) < lanes:
        raise CampaignError(f"cannot partition {len(units)} units into {lanes} nonempty lanes")
    loads = [(0.0, index) for index in range(lanes)]
    assigned: list[list[str]] = [[] for _ in range(lanes)]
    for unit in sorted(units, key=lambda item: (-sum(case_weight(node, weights) for node in item), item[0])):
        load, index = heapq.heappop(loads)
        assigned[index].extend(unit)
        heapq.heappush(loads, (load + sum(case_weight(node, weights) for node in unit), index))
    order = {node: position for position, node in enumerate(nodeids)}
    parts = [sorted(part, key=order.__getitem__) for part in assigned]
    if not all(parts):
        raise CampaignError("a lane received no tests")
    return parts


def lane_loads(parts: list[list[str]], weights: dict[str, float]) -> list[float]:
    return [round(sum(case_weight(node, weights) for node in part), 3) for part in parts]


def partition_estimate(nodeids: list[str], weights: dict[str, float]) -> dict[str, Any]:
    parts = lane_partition(nodeids, weights)
    return {"lane_cases": [len(part) for part in parts], "lane_seconds": lane_loads(parts, weights),
            "lower_bound_seconds": max(case_weight(node, weights) for node in nodeids),
            "partition_sha256": campaign.partition_digest(parts)}


def check_exact_union(collected: list[str], junits: list[Path]) -> dict[str, Any]:
    """Accept the lanes only if their JUnit union is exactly the collection, with zero skips."""
    if len(junits) != LANE_COUNT:
        raise CampaignError(f"expected {LANE_COUNT} lane JUnit files, found {len(junits)}")
    executed: list[tuple[str, str]] = []
    per_lane = []
    for path in junits:
        cases = campaign.junit_cases(path)
        per_lane.append(len(cases))
        executed.extend(cases)
    wanted = {campaign.junit_identity(node) for node in collected}
    occurrences = Counter(executed)
    seen = set(occurrences)
    discrepancies = {"missing": sorted("::".join(case) for case in wanted - seen),
                     "duplicated": sorted("::".join(case) for case, times in occurrences.items() if times > 1),
                     "unexpected": sorted("::".join(case) for case in seen - wanted)}
    for key, cases_found in discrepancies.items():
        if cases_found:
            raise CampaignError(f"union of lanes has {key} tests: {cases_found[:20]}")
    return {"collected": len(collected), "executed": len(executed), **discrepancies, "lanes": per_lane}


def memory_admission(meminfo: str) -> dict[str, Any]:
    """TWO_LANE only with a readable MemAvailable at or above the measured threshold."""
    values: dict[str, int] = {}
    for line in meminfo.splitlines():
        key, _, rest = line.partition(":")
        fields = rest.split()
        if fields and fields[0].isdigit():
            values[key.strip()] = int(fields[0])
    available = values.get("MemAvailable")
    decision = {"mem_total_kib": values.get("MemTotal"), "mem_available_kib": available,
                "threshold_mib": TWO_LANE_START_THRESHOLD_MIB, "guard_mib": MEMORY_GUARD_MIB}
    if available is None or values.get("MemTotal") is None:
        return {**decision, "mode": "SERIAL", "reason": "MemTotal or MemAvailable unreadable"}
    if available / 1024 >= TWO_LANE_START_THRESHOLD_MIB:
        return {**decision, "mode": "TWO_LANE", "reason": "MemAvailable at or above the measured threshold"}
    return {**decision, "mode": "SERIAL", "reason": "MemAvailable below the measured threshold"}


def check_campaign_deadline(elapsed: float) -> bool:
    """Whole-campaign clock: the lanes share the governed full-suite limit."""
    return campaign.check_deadline(elapsed, limit=FULL_SUITE_LIMIT_SECONDS, threshold=PO_DECISION_THRESHOLD_SECONDS)


# --- lane lifecycle: provisioning, private-daemon sandbox, teardown -------

class CommandResult(NamedTuple):
    returncode: int
    stdout: str


class Runner(Protocol):
    def __call__(self, argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
                 input: bytes | None = None, timeout: float = 600, check: bool = True) -> CommandResult: ...


def run_command(argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
                input: bytes | None = None, timeout: float = 600, check: bool = True) -> CommandResult:
    try:
        result = subprocess.run([str(item) for item in argv], cwd=cwd, env=env, input=input, capture_output=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CampaignError(f"command could not run: {argv[:4]}: {exc}") from exc
    if check and result.returncode:
        raise CampaignError(f"command failed ({result.returncode}): {argv[:6]}: {result.stderr.decode(errors='replace')[-2000:]}")
    return CommandResult(result.returncode, result.stdout.decode(errors="replace"))


def campaign_id(head: str, started: int) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", head) or started <= 0:
        raise CampaignError("a lane campaign needs the exact 40-character head and a start time")
    return f"{head[:12]}-{started}"


@dataclass(frozen=True)
class Lane:
    index: int
    campaign: str
    root: Path
    home: Path
    uid: int
    gid: int

    def __post_init__(self) -> None:
        if not 1 <= self.index <= LANE_COUNT or not re.fullmatch(r"[0-9a-f]{12}-[0-9]+", self.campaign):
            raise CampaignError(f"invalid lane {self.index} of campaign {self.campaign!r}")

    @property
    def name(self) -> str:
        return f"ocor-lane-{self.campaign}-{self.index}"

    @property
    def volumes(self) -> tuple[str, str]:
        return f"{self.name}-docker", f"{self.name}-home"

    @property
    def repository(self) -> Path:
        return self.root / "repo"

    @property
    def output(self) -> Path:
        return self.root / "out"


def lane_path(lane: Lane, tool_bins: list[Path]) -> str:
    """Locked tools first, then the lane checkout's qualification tools and venv."""
    entries = [*map(str, tool_bins), str(lane.repository / ".ocor/tools/bin"),
               str(lane.repository / "ocor-runtime/.venv/bin"), *LANE_SYSTEM_PATH]
    return ":".join(entries)


def _mount_root(path: Path, home: Path) -> Path | None:
    resolved = path.resolve()
    if resolved == Path("/usr") or Path("/usr") in resolved.parents:
        return None
    try:
        relative = resolved.relative_to(home.resolve())
    except ValueError:
        raise CampaignError(f"locked tool outside HOME and /usr: {path} -> {resolved}") from None
    if len(relative.parts) < 3:
        raise CampaignError(f"locked tool too close to HOME to mount narrowly: {resolved}")
    return home / Path(*relative.parts[:3])


def tool_mounts(paths: list[Path], home: Path) -> list[Path]:
    """Read-only mounts that make the locked tools resolve inside a sandbox."""
    roots: set[Path] = set()
    for path in paths:
        for item in [path, *(sorted(path.iterdir()) if path.is_dir() else [])]:
            if (root := _mount_root(item, home)) is not None:
                roots.add(root)
    return sorted(root for root in roots if not any(other in root.parents for other in roots))


def sandbox_init(lane: Lane) -> str:
    """cgroup v2 nesting with a bounded, verified delegation, then the lane's own dockerd with its socket group."""
    return ("mkdir -p /sys/fs/cgroup/init; "
            f"for attempt in $(seq 1 {CGROUP_DELEGATION_ATTEMPTS}); do "
            "xargs -rn1 < /sys/fs/cgroup/cgroup.procs > /sys/fs/cgroup/init/cgroup.procs 2>/dev/null; "
            'sed -e "s/ / +/g" -e "s/^/+/" < /sys/fs/cgroup/cgroup.controllers > /sys/fs/cgroup/cgroup.subtree_control 2>/dev/null && break; '
            f"sleep {CGROUP_DELEGATION_PAUSE_SECONDS}; done; "
            "grep -qw memory /sys/fs/cgroup/cgroup.subtree_control || exit 97; "
            f"ln -sfn /run /var/run; chown {lane.uid}:{lane.gid} {lane.home}; "
            f"exec /usr/bin/dockerd --host unix:///run/docker.sock --group {lane.gid} --data-root /var/lib/docker")


def sandbox_run_argv(lane: Lane, mounts: list[Path], *, output_root: Path) -> list[str]:
    argv = ["docker", "run", "-d", "--name", lane.name, "--label", f"{LANE_LABEL}={lane.campaign}",
            "--privileged", "--cgroupns=private",
            "-v", "/usr:/usr:ro", "-v", "/etc:/etc:ro",
            "-v", f"{lane.volumes[0]}:/var/lib/docker", "-v", f"{lane.volumes[1]}:{lane.home}"]
    for mount in mounts:
        argv += ["-v", f"{mount}:{mount}:ro"]
    argv += ["-v", f"{lane.root}:{lane.root}", "-v", f"{output_root}:{output_root}",
             "--tmpfs", "/run", "--tmpfs", "/tmp:exec,mode=1777", "--tmpfs", "/root",
             "-e", f"PATH={SANDBOX_PATH}", SANDBOX_ROOT_IMAGE, "/bin/sh", "-c", sandbox_init(lane)]
    return argv


def sandbox_exec_argv(lane: Lane, path: str, argv: list[str], env: dict[str, str]) -> list[str]:
    command = ["docker", "exec", "-u", f"{lane.uid}:{lane.gid}", "-w", str(lane.repository),
               "-e", f"HOME={lane.home}", "-e", f"PATH={path}"]
    for key, value in sorted(env.items()):
        command += ["-e", f"{key}={value}"]
    return [*command, lane.name, *argv]


def host_usr_links() -> dict[str, str]:
    links = {name: os.readlink(f"/{name}") for name in USR_MERGED_LINKS if os.path.islink(f"/{name}")}
    if any(not target.startswith("usr/") for target in links.values()):
        raise CampaignError(f"unexpected top-level link layout: {links}")
    return links


def empty_root_tar(links: dict[str, str]) -> bytes:
    """Deterministic root with mount points and the host's usr-merge links only."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(EMPTY_ROOT_DIRS):
            info = tarfile.TarInfo(name)
            info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o1777 if name == "tmp" else 0o755, 0
            archive.addfile(info)
        for name, target in sorted({**links, "var/run": "/run"}.items()):
            info = tarfile.TarInfo(name)
            info.type, info.linkname, info.mode, info.mtime = tarfile.SYMTYPE, target, 0o777, 0
            archive.addfile(info)
    return buffer.getvalue()


def ensure_root_image(runner: Runner, links: dict[str, str]) -> None:
    if runner(["docker", "image", "inspect", SANDBOX_ROOT_IMAGE], check=False).returncode == 0:
        return
    runner(["docker", "import", "--change", f"LABEL {LANE_LABEL}=root", "-", SANDBOX_ROOT_IMAGE], input=empty_root_tar(links))


def verify_lane_tools(repository: Path) -> None:
    """Copied qualification tools must match infra/qualification_tools.lock.json byte for byte."""
    lock = json.loads((repository / "infra/qualification_tools.lock.json").read_text(encoding="utf-8"))
    for tool in lock["tools"]:
        binary = repository / ".ocor/tools/bin" / tool["id"]
        try:
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        except OSError as exc:
            raise CampaignError(f"qualification tool {tool['id']} absent from the lane") from exc
        if digest != tool["binary_sha256"]:
            raise CampaignError(f"qualification tool {tool['id']} differs from its lock")


def provision_steps(lane: Lane, source: Path, head: str) -> list[tuple[list[str], Path | None]]:
    repository, sdk = lane.repository, lane.repository / "ocor-runtime/sdk/typescript"
    return [
        (["git", "clone", "--no-hardlinks", "--no-checkout", "--quiet", str(source), str(repository)], None),
        (["git", "-C", str(repository), "checkout", "--quiet", "--detach", head], None),
        (["uv", "sync", "--project", str(repository / "ocor-runtime"), "--frozen", "--extra", "test", "--extra", "lint"], repository),
        (["npm", "ci", "--no-audit", "--no-fund"], sdk),
        (["npm", "run", "build"], sdk)]


def _verify_lane_head(lane: Lane, head: str, runner: Runner) -> None:
    found = runner(["git", "-C", str(lane.repository), "rev-parse", "HEAD"]).stdout.strip()
    if found != head:
        raise CampaignError(f"lane {lane.index} HEAD mismatch: {found}")
    if runner(["git", "-C", str(lane.repository), "status", "--porcelain", "--untracked-files=no"]).stdout.strip():
        raise CampaignError(f"lane {lane.index} checkout has tracked changes")


def provision_lane(lane: Lane, source: Path, head: str, runner: Runner, env: dict[str, str]) -> dict[str, Any]:
    """Self-contained clone at the exact head; tools and Fuseki cache copied, credentials never."""
    if lane.root.exists():
        raise CampaignError(f"lane root exists: {lane.root}")
    lane.output.mkdir(parents=True)
    steps = provision_steps(lane, source, head)
    for argv, cwd in steps[:2]:
        runner(argv, cwd=cwd, env=env, timeout=PROVISION_TIMEOUT_SECONDS)
    _verify_lane_head(lane, head, runner)
    shutil.copytree(source / ".ocor/tools", lane.repository / ".ocor/tools")
    if (source / ".ocor/cache/fuseki").is_dir():
        shutil.copytree(source / ".ocor/cache/fuseki", lane.repository / ".ocor/cache/fuseki")
    verify_lane_tools(lane.repository)
    for argv, cwd in steps[2:]:
        runner(argv, cwd=cwd, env=env, timeout=PROVISION_TIMEOUT_SECONDS)
    _verify_lane_head(lane, head, runner)
    return {"lane": lane.index, "head": head, "repository": str(lane.repository)}


def inner_daemon_contents(lane: Lane, runner: Runner) -> dict[str, list[str]]:
    def listed(*argv: str) -> list[str]:
        return runner(["docker", "exec", lane.name, "docker", *argv]).stdout.split()
    return {"containers": listed("ps", "-aq"), "volumes": listed("volume", "ls", "-q"),
            "networks": listed("network", "ls", "-q", "--filter", "type=custom")}


def start_sandbox(lane: Lane, mounts: list[Path], runner: Runner, *, output_root: Path,
                  sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Labelled volumes, the privileged sandbox, then a fail-closed wait for an empty private daemon."""
    for volume in lane.volumes:
        runner(["docker", "volume", "create", "--label", f"{LANE_LABEL}={lane.campaign}", volume])
    runner(sandbox_run_argv(lane, mounts, output_root=output_root))
    waited = 0
    probe = ["docker", "exec", lane.name, "docker", "info", "--format", "{{.ServerVersion}}"]
    while (reply := runner(probe, check=False)).returncode:
        if waited >= SANDBOX_READY_SECONDS:
            raise CampaignError(f"lane {lane.index} private daemon not ready after {waited} s")
        sleep(SANDBOX_POLL_SECONDS)
        waited += SANDBOX_POLL_SECONDS
    contents = inner_daemon_contents(lane, runner)
    if any(contents.values()):
        raise CampaignError(f"lane {lane.index} private daemon is not empty: {contents}")
    delegated = runner(["docker", "exec", lane.name, "cat", "/sys/fs/cgroup/cgroup.subtree_control"]).stdout.split()
    if missing := sorted(REQUIRED_CONTROLLERS - set(delegated)):
        raise CampaignError(f"lane {lane.index} sandbox lacks delegated cgroup controllers: {missing}")
    return {"lane": lane.index, "sandbox": lane.name, "daemon_version": reply.stdout.strip(), "ready_after_seconds": waited,
            "delegated_controllers": delegated}


def teardown_lane(lane: Lane, path: str, runner: Runner) -> dict[str, Any]:
    """Stack, inner residue check, sandbox, volumes and clone; every step runs, then fail closed."""
    errors: list[str] = []
    exists = runner(["docker", "container", "inspect", lane.name], check=False).returncode == 0
    if exists:
        python = str(lane.repository / "ocor-runtime/.venv/bin/python")
        try:
            runner(sandbox_exec_argv(lane, path, [python, "scripts/bootstrap_ci_environment.py", "--teardown", "--execute"], {}),
                   timeout=PROVISION_TIMEOUT_SECONDS)
        except CampaignError as exc:
            errors.append(f"stack teardown failed: {exc}")
        try:
            if any((contents := inner_daemon_contents(lane, runner)).values()):
                errors.append(f"residue inside the private daemon: {contents}")
        except CampaignError as exc:
            errors.append(f"inner residue unreadable: {exc}")
        try:
            runner(["docker", "rm", "-f", lane.name])
        except CampaignError as exc:
            errors.append(f"sandbox removal failed: {exc}")
    present = [volume for volume in lane.volumes if runner(["docker", "volume", "inspect", volume], check=False).returncode == 0]
    if present:
        try:
            runner(["docker", "volume", "rm", *present])
        except CampaignError as exc:
            errors.append(f"volume removal failed: {exc}")
    try:
        if lane.repository.exists():
            shutil.rmtree(lane.repository)
    except OSError as exc:
        errors.append(f"lane checkout removal failed: {exc}")
    if errors:
        raise CampaignError(f"lane {lane.index} teardown incomplete: {'; '.join(errors)}")
    return {"lane": lane.index, "status": "PASS", "sandbox_found": exists}


def remove_root_image(runner: Runner) -> None:
    if runner(["docker", "image", "inspect", SANDBOX_ROOT_IMAGE], check=False).returncode == 0:
        runner(["docker", "image", "rm", SANDBOX_ROOT_IMAGE])


def check_host_residue(campaign: str, runner: Runner) -> dict[str, Any]:
    label = f"label={LANE_LABEL}={campaign}"
    residue: dict[str, Any] = {
        "containers": runner(["docker", "ps", "-aq", "--filter", label]).stdout.split(),
        "volumes": runner(["docker", "volume", "ls", "-q", "--filter", label]).stdout.split(),
        "networks": runner(["docker", "network", "ls", "-q", "--filter", label]).stdout.split(),
        "root_image": runner(["docker", "image", "inspect", SANDBOX_ROOT_IMAGE], check=False).returncode == 0}
    if any(residue.values()):
        raise CampaignError(f"host residue after the lane campaign: {residue}")
    return residue


def lifecycle_check(work: Path, head: str, tool_bins: list[Path], runner: Runner = run_command) -> dict[str, Any]:
    """Non-qualifying: provision both lanes, start their sandboxes, probe them, tear down with zero residue."""
    source = Path(__file__).resolve().parents[1]
    campaign.verify_revision(source, head)
    started = int(time.time())
    lanes = [Lane(index, campaign_id(head, started), work / f"lane-{index}", Path.home(), os.getuid(), os.getgid())
             for index in range(1, LANE_COUNT + 1)]
    report: dict[str, Any] = {"campaign": lanes[0].campaign, "head": head, "memory": memory_admission(Path("/proc/meminfo").read_text()),
                              "lanes": [], "teardown": [], "status": "FAIL"}
    try:
        ensure_root_image(runner, host_usr_links())
        for lane in lanes:
            path = lane_path(lane, tool_bins)
            entry: dict[str, Any] = {"provision": provision_lane(lane, source, head, runner, {"HOME": str(lane.home), "PATH": path})}
            mounts = tool_mounts([*tool_bins, lane.repository / "ocor-runtime/.venv/bin/python"], lane.home)
            entry["mounts"] = [str(mount) for mount in mounts]
            entry["sandbox"] = start_sandbox(lane, mounts, runner, output_root=work)
            probes = {"head": ["git", "rev-parse", "HEAD"], "python": ["python", "-c", "import sys; print(sys.version.split()[0])"],
                      "docker": ["docker", "info", "--format", "{{.ServerVersion}} {{.CgroupVersion}}"], "kind": ["kind", "version"],
                      "node": ["node", "--version"], "uid": ["id", "-u"]}
            entry["probes"] = {key: runner(sandbox_exec_argv(lane, path, argv, {})).stdout.strip() for key, argv in probes.items()}
            if entry["probes"]["head"] != head:
                raise CampaignError(f"lane {lane.index} sandbox sees {entry['probes']['head']}")
            report["lanes"].append(entry)
        report["status"] = "PASS"
    except (CampaignError, OSError, ValueError, KeyError) as exc:
        report["error"] = str(exc)
    finally:
        for lane in lanes:
            try:
                report["teardown"].append(teardown_lane(lane, lane_path(lane, tool_bins), runner))
            except CampaignError as exc:
                report["teardown"].append({"lane": lane.index, "status": "FAIL", "error": str(exc)})
                report["status"] = "FAIL"
        try:
            remove_root_image(runner)
            report["host_residue"] = check_host_residue(lanes[0].campaign, runner)
        except CampaignError as exc:
            report["host_residue"] = {"error": str(exc)}
            report["status"] = "FAIL"
    return report


# --- per-lane runner, executed inside the lane sandbox ----------------------
# Mirrors the sealed supervisor's execution body on the lane's own stack. The
# lane never selects its cases: it runs exactly the orchestrator's node list,
# proven by collection, and shares the whole-campaign clock.

LANE_POLL_SECONDS = 5
LANE_JUNIT = "runtime_junit_post_approval.xml"
LANE_LOGS = ("bootstrap.log", "post_remediation_runtime.log", "kubernetes-diagnostics.log", LANE_JUNIT)
CI_POSTGRES_PORT = 55433
LANE_BOOTSTRAP = (["scripts/bootstrap_ci_environment.py", "--teardown", "--execute"],
                  ["scripts/bootstrap_ci_environment.py", "--execute", "--timeout", "600"])


def load_lane_spec(path: Path) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    selection = spec.get("selection")
    if (not isinstance(spec.get("head"), str) or not re.fullmatch(r"[0-9a-f]{40}", spec["head"])
            or spec.get("lane") not in range(1, LANE_COUNT + 1)
            or not isinstance(selection, list) or not selection or len(selection) != len(set(selection))
            or not all(isinstance(node, str) and "::" in node for node in selection)
            or not isinstance(spec.get("campaign_start"), (int, float)) or spec["campaign_start"] <= 0
            or not isinstance(spec.get("stop_file"), str) or not spec["stop_file"]):
        raise CampaignError(f"incomplete or ambiguous lane spec: {path}")
    return dict(spec)


def lane_service_environment(repository: Path) -> dict[str, str]:
    """The two variables the versioned CI exports after provisioning, for the lane's own stack."""
    env_file = (repository / ".ocor/bootstrap.env").resolve()
    values = dict(line.split("=", 1) for line in env_file.read_text(encoding="utf-8").splitlines() if "=" in line)
    if not values.get("OCOR_LOCAL_POSTGRES_PASSWORD"):
        raise CampaignError("lane bootstrap env has no generated PostgreSQL password")
    return {"OCOR_BOOTSTRAP_ENV": str(env_file),
            "OCOR_LIVE_POSTGRES_DSN": f"postgresql://ocor:{values['OCOR_LOCAL_POSTGRES_PASSWORD']}@127.0.0.1:{CI_POSTGRES_PORT}/ocor"}


def lane_pytest_command(output: Path, selection: list[str]) -> list[str]:
    return [sys.executable, "-m", "pytest", "-v", "--cov=src", "--cov-report=term-missing",
            f"--cov-report=json:{output / 'runtime_coverage_post_approval.json'}", f"--junitxml={output / LANE_JUNIT}", *selection]


def run_lane(spec_path: Path, *, repository: Path | None = None, runner: Runner = run_command) -> int:
    """Run one lane on its own stack; lane_result.json records PASS or the first failure."""
    repository = (repository or Path(__file__).resolve().parents[1]).resolve()
    output, suite = spec_path.parent, repository / "ocor-runtime"
    junit = output / LANE_JUNIT
    process: subprocess.Popen[Any] | None = None
    recorder: Any = None
    sampler: Any = None
    health: subprocess.Popen[Any] | None = None
    decision_required = False
    spec: dict[str, Any] = {}

    def clock() -> bool:
        stop_file = Path(spec["stop_file"])
        if stop_file.exists():
            raise CampaignError(f"lane {spec['lane']} stopped by the orchestrator: {stop_file.read_text(errors='replace')[:200].strip()}")
        return check_campaign_deadline(time.time() - spec["campaign_start"])

    try:
        spec = load_lane_spec(spec_path)
        head, selection = spec["head"], spec["selection"]
        decision_required = clock()
        campaign.verify_revision(repository, head)
        failed: CommandResult | None = None
        with (output / "bootstrap.log").open("w") as log:
            for argv in LANE_BOOTSTRAP:
                reply = runner([sys.executable, *argv], cwd=repository, env=dict(os.environ), timeout=PROVISION_TIMEOUT_SECONDS, check=False)
                log.write(reply.stdout + "\n")
                if reply.returncode:
                    failed = reply
                    break
        if (repository / ".ocor/bootstrap.env").is_file():
            bootstrap_ci.redact_campaign_log(repository, output / "bootstrap.log")
        if failed is not None:
            tail = (output / "bootstrap.log").read_text(errors="replace").strip()[-600:]
            raise CampaignError(f"lane {spec['lane']} bootstrap failed (exit {failed.returncode}): {tail}")
        os.environ.update(lane_service_environment(repository))
        decision_required = clock() or decision_required
        if campaign.collect_nodeids(suite, selection) != selection:
            raise CampaignError(f"lane {spec['lane']} selection does not collect exactly its node IDs")
        initial = campaign.inspect_stack()
        if len(initial) != campaign.MANDATORY_CONTAINERS:
            raise CampaignError(f"expected {campaign.MANDATORY_CONTAINERS} mandatory containers, found {len(initial)}")
        campaign.check_stack(initial, initial)
        recorder = bootstrap_ci.SessionRecorder(repository)
        health = campaign.start_health_observer(output, FULL_SUITE_LIMIT_SECONDS)
        history: dict[str, dict[str, Any]] = {}
        lane_start = time.monotonic()
        with (output / "post_remediation_runtime.log").open("w") as log:
            process = subprocess.Popen(lane_pytest_command(output, selection), cwd=suite, env=campaign.pytest_environment(suite),
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            sampler = kind_observer.start_sampler(process.pid, campaign.qualification_kind_binary(repository))
            while process.poll() is None:
                campaign.check_stack(initial, campaign.inspect_stack())
                current = campaign.inspect_kubernetes_runtimes()
                with (output / "kubernetes-runtime.log").open("a") as runtime_log:
                    runtime_log.write(json.dumps(current, sort_keys=True) + "\n")
                campaign.check_kubernetes_runtimes(history, current)
                decision_required = clock() or decision_required
                time.sleep(LANE_POLL_SECONDS)
            campaign.check_stack(initial, campaign.inspect_stack())
            campaign.check_kubernetes_runtimes(history, campaign.inspect_kubernetes_runtimes())
        decision_required = clock() or decision_required
        if process.returncode:
            raise CampaignError(f"pytest exit code {process.returncode}")
        campaign.verify_revision(repository, head)
        counts = campaign.check_junit(junit, required_modules=[])
        if sorted(campaign.junit_cases(junit)) != sorted(campaign.junit_identity(node) for node in selection):
            raise CampaignError("lane JUnit differs from its selection")
        shutil.copyfile(suite / ".coverage", output / "runtime_coverage.data")
        result: dict[str, Any] = {
            "status": "PASS", "lane": spec["lane"], "candidate_head": head, "counts": counts, "selected": len(selection),
            "selected_sha256": campaign.collection_digest(selection), "lane_duration_seconds": round(time.monotonic() - lane_start, 3),
            "campaign_elapsed_seconds": round(time.time() - spec["campaign_start"], 3), "limit_seconds": FULL_SUITE_LIMIT_SECONDS,
            "po_decision_required": decision_required}
        status = 0
    except (CampaignError, kind_observer.TeardownObservationError, OSError, subprocess.SubprocessError,
            KeyError, ValueError, TypeError) as exc:
        frozen = False
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGSTOP)
                frozen = True
            except ProcessLookupError:
                pass
        try:
            campaign.collect_kubernetes_diagnostics(output / "kubernetes-diagnostics.log")
        finally:
            if process is not None:
                campaign.stop(process, resume=frozen)
        try:
            bootstrap_ci.collect_stack_diagnostics(repository, output / "docker-stats.log")
        except Exception as diagnostics:  # noqa: BLE001 - diagnostics never mask the lane failure
            (output / "docker-stats.log").write_text(f"stack diagnostics incomplete: {diagnostics}\n")
        result = {"status": "FAIL", "lane": spec.get("lane"), "error": str(exc), "po_decision_required": decision_required}
        status = 1
    finally:
        if process is not None:
            campaign.stop(process)
        campaign.finish_health_observer(health, output)
        if sampler is not None:
            kind_observer.stop_sampler(sampler)
            observer = kind_observer
            (output / "kind-teardown-observations.json").write_text(json.dumps({
                "removals": observer.REMOVALS, "rejections": observer.REJECTIONS, "window_seconds": observer.WINDOW_SECONDS,
                "remover_observations": observer.REMOVER_OBSERVATIONS, "probe_observations": observer.PROBE_OBSERVATIONS,
                "bootstrap_recoveries": observer.BOOTSTRAP_RECOVERIES}, indent=2, sort_keys=True) + "\n")
        if recorder is not None:
            try:
                recorder.finish()
            except (OSError, ValueError, subprocess.SubprocessError, RuntimeError, KeyError, TypeError, AttributeError) as exc:
                result, status = {"status": "FAIL", "lane": spec.get("lane"), "error": f"ownership recorder: {exc}",
                                  "po_decision_required": decision_required}, 1
            resources = repository / ".ocor/campaign-resources.json"
            if resources.is_file():
                shutil.copyfile(resources, output / "campaign-resources.json")
        if (repository / ".ocor/bootstrap.env").is_file():
            for name in LANE_LOGS:
                if (output / name).is_file():
                    bootstrap_ci.redact_campaign_log(repository, output / name)
    (output / "lane_result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return status


# --- --execute orchestration on the host ------------------------------------
# Memory admission, exact head, collection and partition on the host checkout;
# both lanes provisioned and started, then launched in parallel with only HOME
# and PATH. The host keeps the whole-campaign clock and stops the other lane on
# the first failure; union, JUnit and coverage are checked on the host, and both
# lanes are always torn down with zero residue.

SUPERVISE_POLL_SECONDS = 5
# A lane observes its STOP file between steps; its longest step that cannot be
# interrupted is a bounded bootstrap command (PROVISION_TIMEOUT_SECONDS).
STOP_GRACE_SECONDS = PROVISION_TIMEOUT_SECONDS + 120
FULL_SUITE_SELECTION = ["tests/"]
FULL_SUITE_REQUIRED_MODULES = ["test_ocor_dev_0048", "test_ocor_dev_0049"]
POWER_SUPPLY_ROOT = Path("/sys/class/power_supply")
SERIAL_COMMAND = "scripts/run_qualifying_campaign.py --execute --output-dir <dir> on the host ocor-bootstrap stack"


class LaneProcess(Protocol):
    def poll(self) -> int | None: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int | None: ...


def write_lane_spec(lane: Lane, head: str, selection: list[str], started: float) -> Path:
    path = lane.output / "lane_spec.json"
    spec = {"campaign_start": started, "head": head, "lane": lane.index, "selection": list(selection),
            "stop_file": str(lane.output / "STOP")}
    path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    load_lane_spec(path)
    return path


def lane_run_argv(lane: Lane, path: str, spec: Path) -> list[str]:
    """The lane runner inside the sandbox: clean shell, only HOME and PATH."""
    python = str(lane.repository / "ocor-runtime/.venv/bin/python")
    return sandbox_exec_argv(lane, path, [python, "scripts/run_local_lane_campaign.py", "--run-lane", str(spec)], {})


def launch_lane(argv: list[str], log: Path) -> LaneProcess:
    with log.open("w") as handle:
        return subprocess.Popen(argv, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)


def supervise_lanes(processes: dict[int, LaneProcess], lanes: list[Lane], started: float, *,
                    clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Wait for both lanes; the first failure or the whole-campaign limit stops the others."""
    by_index = {lane.index: lane for lane in lanes}
    returncodes: dict[int, int | None] = dict.fromkeys(processes)
    first_failure: int | None = None
    stop_reason: str | None = None
    stop_at: float | None = None
    killed: list[int] = []
    decision = False

    def request_stop(reason: str, exclude: int | None = None) -> None:
        nonlocal stop_at
        for index, code in returncodes.items():
            if index != exclude and code is None:
                (by_index[index].output / "STOP").write_text(reason + "\n")
        if stop_at is None:
            stop_at = clock()

    while True:
        for index, process in processes.items():
            if returncodes[index] is None and (code := process.poll()) is not None:
                returncodes[index] = code
                if code and first_failure is None and stop_reason is None:
                    first_failure = index
                    request_stop(f"lane {index} failed (exit {code})", exclude=index)
        running = [index for index, code in returncodes.items() if code is None]
        if not running:
            break
        try:
            decision = check_campaign_deadline(clock() - started) or decision
        except CampaignError as exc:
            if stop_reason is None:
                stop_reason = str(exc)
                request_stop(stop_reason)
        if stop_at is not None and clock() - stop_at >= STOP_GRACE_SECONDS:
            for index in running:
                processes[index].kill()
                processes[index].wait(timeout=60)
                killed.append(index)
        sleep(SUPERVISE_POLL_SECONDS)
    return {"returncodes": returncodes, "first_failure": first_failure, "stop_reason": stop_reason,
            "killed_after_grace": killed, "po_decision_required": decision}


def read_lane_results(lanes: list[Lane], head: str, parts: list[list[str]]) -> list[dict[str, Any]]:
    """Both lane results PASS, for this head, this lane and exactly its selection."""
    results = []
    for lane, part in zip(lanes, parts, strict=True):
        try:
            result = json.loads((lane.output / "lane_result.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CampaignError(f"lane {lane.index} result absent or invalid") from exc
        if result.get("status") != "PASS":
            raise CampaignError(f"lane {lane.index} failed: {result.get('error')}")
        if result.get("candidate_head") != head:
            raise CampaignError(f"lane {lane.index} ran another head: {result.get('candidate_head')}")
        if result.get("lane") != lane.index:
            raise CampaignError(f"lane {lane.index} result names lane {result.get('lane')}")
        if result.get("selected") != len(part) or result.get("selected_sha256") != campaign.collection_digest(part):
            raise CampaignError(f"lane {lane.index} ran another selection")
        results.append(result)
    return results


def merge_lane_junit(lanes: list[Lane], output: Path, *, required_modules: list[str]) -> dict[str, int]:
    merged = ET.Element("testsuites")
    for lane in lanes:
        root = ET.parse(lane.output / LANE_JUNIT).getroot()
        for suite in ([root] if root.tag == "testsuite" else list(root.iter("testsuite"))):
            suite.set("name", f"{suite.get('name', 'pytest')}-lane-{lane.index}")
            merged.append(suite)
    ET.ElementTree(merged).write(output, encoding="utf-8", xml_declaration=True)
    return campaign.check_junit(output, required_modules=required_modules)


def combine_lane_coverage(suite: Path, lanes: list[Lane], output: Path, runner: Runner) -> None:
    """Combine the lanes' data, remapping each lane clone onto the host checkout at the same head."""
    rcfile = output / "lane_coverage.rc"
    sources = [str(suite / "src"), *(str(lane.repository / "ocor-runtime/src") for lane in lanes)]
    rcfile.write_text("[paths]\nsource =\n" + "".join(f"    {source}\n" for source in sources))
    copies = []
    for lane in lanes:
        copies.append(output / f"runtime_coverage.lane-{lane.index}")
        shutil.copyfile(lane.output / "runtime_coverage.data", copies[-1])
    data = output / "runtime_coverage.combined"
    runner([sys.executable, "-m", "coverage", "combine", f"--rcfile={rcfile}", f"--data-file={data}", *map(str, copies)], cwd=suite)
    runner([sys.executable, "-m", "coverage", "json", f"--rcfile={rcfile}", f"--data-file={data}",
            "-o", str(output / "runtime_coverage_post_approval.json")], cwd=suite)


def power_reading(root: Path = POWER_SUPPLY_ROOT) -> dict[str, Any]:
    """Informative only (LOCAL-FULL-SUITE-CAP-90 point 6): mains or battery, never a criterion."""
    supplies: dict[str, dict[str, str]] = {}
    try:
        for entry in sorted(root.iterdir()):
            supplies[entry.name] = {key: (entry / key).read_text().strip()
                                    for key in ("type", "online", "status") if (entry / key).is_file()}
    except OSError:
        supplies = {}
    mains = [values for values in supplies.values() if values.get("type") == "Mains" and "online" in values]
    source = "NOT_EXECUTED" if not mains else ("MAINS" if any(values["online"] == "1" for values in mains) else "BATTERY")
    return {"source": source, "supplies": supplies, "read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def execute_campaign(work: Path, head: str, tool_bins: list[Path], selection: list[str], *, source: Path | None = None,
                     runner: Runner = run_command, launcher: Callable[[list[str], Path], LaneProcess] = launch_lane,
                     meminfo_path: Path = Path("/proc/meminfo"), power_root: Path = POWER_SUPPLY_ROOT) -> dict[str, Any]:
    """Two-lane campaign at the exact head; campaign_result.json records PASS, FAIL or the serial fallback."""
    source = (source or Path(__file__).resolve().parents[1]).resolve()
    suite = source / "ocor-runtime"
    full = selection == FULL_SUITE_SELECTION
    required_modules = list(FULL_SUITE_REQUIRED_MODULES) if full else []
    work.mkdir(parents=True, exist_ok=True)
    started, monotonic_start = time.time(), time.monotonic()
    result: dict[str, Any] = {
        "status": "FAIL", "mode": "TWO_LANE", "head": head, "selection": selection,
        "selection_scope": "FULL_SUITE" if full else "EXPLICIT_NON_QUALIFYING", "qualifying_scope": full,
        "required_modules": required_modules, "limit_seconds": FULL_SUITE_LIMIT_SECONDS,
        "threshold_seconds": PO_DECISION_THRESHOLD_SECONDS, "campaign_start": started,
        "power_start": power_reading(power_root), "lanes": [], "teardown": []}
    try:
        result["memory"] = memory_admission(meminfo_path.read_text())
    except OSError as exc:
        result["memory"] = {"mode": "SERIAL", "reason": f"meminfo unreadable: {exc}"}
    if result["memory"]["mode"] != "TWO_LANE":
        result.update(status="SERIAL_FALLBACK", mode="SERIAL", next_action=f"run the serial suite: {SERIAL_COMMAND}",
                      power_end=power_reading(power_root), total_duration_seconds=round(time.monotonic() - monotonic_start, 3))
        (work / "campaign_result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result
    name = campaign_id(head, int(started))
    result["campaign"] = name
    lanes = [Lane(index, name, work / f"lane-{index}", Path.home(), os.getuid(), os.getgid()) for index in range(1, LANE_COUNT + 1)]
    paths = {lane.index: lane_path(lane, tool_bins) for lane in lanes}
    try:
        campaign.verify_revision(source, head)
        collected = campaign.collect_nodeids(suite, selection)
        weights = load_weights()
        parts = lane_partition(collected, weights)
        result["collection"] = {"collected": len(collected), "collected_sha256": campaign.collection_digest(collected),
                                "partition_sha256": campaign.partition_digest(parts), "lane_cases": [len(part) for part in parts],
                                "lane_estimated_seconds": lane_loads(parts, weights),
                                "lower_bound_seconds": max(case_weight(node, weights) for node in collected)}
        ensure_root_image(runner, host_usr_links())
        specs = {}
        for lane, part in zip(lanes, parts, strict=True):
            provision_start = time.monotonic()
            entry: dict[str, Any] = {"lane": lane.index, "provision": provision_lane(
                lane, source, head, runner, {"HOME": str(lane.home), "PATH": paths[lane.index]})}
            mounts = tool_mounts([*tool_bins, lane.repository / "ocor-runtime/.venv/bin/python"], lane.home)
            entry["mounts"] = [str(mount) for mount in mounts]
            entry["sandbox"] = start_sandbox(lane, mounts, runner, output_root=work)
            entry["provisioning_seconds"] = round(time.monotonic() - provision_start, 3)
            specs[lane.index] = write_lane_spec(lane, head, part, started)
            result["lanes"].append(entry)
        processes = {lane.index: launcher(lane_run_argv(lane, paths[lane.index], specs[lane.index]), lane.output / "lane_runner.log")
                     for lane in lanes}
        result["supervision"] = supervise_lanes(processes, lanes, started)
        try:
            lane_results = read_lane_results(lanes, head, parts)
        finally:
            for entry, lane in zip(result["lanes"], lanes, strict=False):
                if (lane.output / "lane_result.json").is_file():
                    entry["result"] = json.loads((lane.output / "lane_result.json").read_text(encoding="utf-8"))
        if result["supervision"]["stop_reason"]:
            raise CampaignError(result["supervision"]["stop_reason"])
        result["union"] = check_exact_union(collected, [lane.output / LANE_JUNIT for lane in lanes])
        result["counts"] = merge_lane_junit(lanes, work / LANE_JUNIT, required_modules=required_modules)
        combine_lane_coverage(suite, lanes, work, runner)
        campaign.verify_revision(source, head)
        result["po_decision_required"] = (check_campaign_deadline(time.time() - started)
                                          or result["supervision"]["po_decision_required"]
                                          or any(item["po_decision_required"] for item in lane_results))
        result["status"] = "PASS"
    except (CampaignError, OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        result["error"] = str(exc)
    finally:
        for lane in lanes:
            log = lane.output / "lane_runner.log"
            if log.is_file() and (lane.repository / ".ocor/bootstrap.env").is_file():
                bootstrap_ci.redact_campaign_log(lane.repository, log)
            try:
                result["teardown"].append(teardown_lane(lane, paths[lane.index], runner))
            except CampaignError as exc:
                result["teardown"].append({"lane": lane.index, "status": "FAIL", "error": str(exc)})
                result["status"] = "FAIL"
        try:
            remove_root_image(runner)
            result["host_residue"] = check_host_residue(name, runner)
        except CampaignError as exc:
            result["host_residue"] = {"error": str(exc)}
            result["status"] = "FAIL"
        result["power_end"] = power_reading(power_root)
        result["total_duration_seconds"] = round(time.monotonic() - monotonic_start, 3)
        result.setdefault("po_decision_required", result["total_duration_seconds"] > PO_DECISION_THRESHOLD_SECONDS)
        (work / "campaign_result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    # The returned record is the stored one (JSON keys are strings).
    return dict(json.loads((work / "campaign_result.json").read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--derive-weights", type=Path, metavar="JUNIT", help="write the weights file content derived from a serial PASS JUnit")
    parser.add_argument("--plan", action="store_true", help="collect on this checkout and print the memory decision and lane estimate")
    parser.add_argument("--lifecycle-check", type=Path, metavar="WORK_DIR",
                        help="non-qualifying: provision both lane sandboxes at --expected-head, probe them and tear them down")
    parser.add_argument("--expected-head", help="exact head of this checkout, required with --lifecycle-check and --execute")
    parser.add_argument("--tool-bin", type=Path, action="append", default=[], help="directory of locked tool links, first on the lane PATH")
    parser.add_argument("--run-lane", type=Path, metavar="LANE_SPEC", help="inside a lane sandbox: run the spec's exact node list on the lane stack")
    parser.add_argument("--execute", type=Path, metavar="WORK_DIR",
                        help="two-lane campaign at --expected-head (full suite unless --select); serial fallback below the memory threshold")
    parser.add_argument("--select", action="append", default=[], metavar="NODE_ID",
                        help="explicit node IDs for a non-qualifying run of --execute")
    args = parser.parse_args(argv)
    if args.run_lane:
        return run_lane(args.run_lane.resolve())
    if args.execute:
        if not args.expected_head or not args.tool_bin:
            parser.error("--execute requires --expected-head and --tool-bin")
        result = execute_campaign(args.execute.resolve(), args.expected_head, [path.resolve() for path in args.tool_bin],
                                  args.select or list(FULL_SUITE_SELECTION))
        print(json.dumps(result, indent=2, sort_keys=True))
        return {"PASS": 0, "SERIAL_FALLBACK": 3}.get(result["status"], 1)
    if args.lifecycle_check:
        if not args.expected_head or not args.tool_bin:
            parser.error("--lifecycle-check requires --expected-head and --tool-bin")
        report = lifecycle_check(args.lifecycle_check.resolve(), args.expected_head, [path.resolve() for path in args.tool_bin])
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["status"] == "PASS" else 1
    if args.derive_weights:
        print(json.dumps(derive_weights(args.derive_weights), indent=2, sort_keys=True))
        return 0
    if args.plan:
        try:
            collected = campaign.collect_nodeids(Path(__file__).resolve().parents[1] / "ocor-runtime", ["tests/"])
            weights = load_weights()
            plan = {"collected": len(collected), "collected_sha256": campaign.collection_digest(collected),
                    "memory": memory_admission(Path("/proc/meminfo").read_text()), **partition_estimate(collected, weights)}
        except (CampaignError, OSError, ValueError, KeyError) as exc:
            print(json.dumps({"status": "FAIL", "error": str(exc)}))
            return 1
        print(json.dumps({"status": "PASS", **plan}, sort_keys=True))
        return 0
    parser.error("choose --derive-weights, --plan, --lifecycle-check, --run-lane or --execute")
    return 2


if __name__ == "__main__":
    sys.exit(main())
