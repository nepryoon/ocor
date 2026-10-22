#!/usr/bin/env python3
"""Run the complete runtime suite, stopping on stack failure or the governed 75-minute full-suite limit.

In CI the suite runs as N >= 2 deterministic parts, each on its own runner and
stack (45-minute part limit), and an aggregator proves that the union of the
parts' JUnit equals ``pytest --collect-only`` on the same HEAD
(PO decision REM-0017-CI-CAMPAIGN-DURATION, 2026-10-09).
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import shutil
import os
import re
import select
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

import observe_kind_teardown as kind_observer

from bootstrap_ci_environment import SessionRecorder, collect_stack_diagnostics, redact, redact_campaign_log


FULL_SUITE_LIMIT_SECONDS = 4500
PO_DECISION_THRESHOLD_SECONDS = 3600
PART_LIMIT_SECONDS = 2700
PART_REBALANCE_SECONDS = 1800
PART_ARTIFACTS = ("partition.json", "campaign_result.json", "runtime_junit_post_approval.xml", "runtime_coverage.data")

# PO REM-0017-CI-0049-RELAY-HEALTH: observation only. These limits apply to
# diagnostic work, never to pytest, the campaign clock or the qualifying gate.
HEALTH_DATA_LIMIT = 16 * 1024 * 1024
HEALTH_COMMAND_LIMIT = 256 * 1024
HEALTH_SAMPLE_SECONDS = 5


class HealthJournal:
    """Bounded, immediately redacted diagnostic data shared by observer threads."""

    def __init__(self, output: Path, secrets: list[str], *, max_bytes: int = HEALTH_DATA_LIMIT):
        self.path = output / "health-observer.jsonl"
        self.secrets = secrets
        self.max_bytes = max_bytes
        self.bytes_written = 0
        self.truncated = False
        self.lock = threading.Lock()

    def write(self, record: dict[str, Any]) -> None:
        text = (json.dumps({"observed_unix_ns": time.time_ns(), **record}, sort_keys=True) + "\n")
        data = redact(text, self.secrets).encode()
        with self.lock:
            if self.bytes_written + len(data) > self.max_bytes:
                self.truncated = True
                return
            with self.path.open("ab") as log:
                log.write(data)
            self.bytes_written += len(data)


def health_command(command: list[str], *, timeout: float = 5, max_bytes: int = HEALTH_COMMAND_LIMIT) -> dict[str, Any]:
    """Read-only diagnostics with bounded pipe buffering, output and duration."""
    result: dict[str, Any] = {"command": command, "output": "", "exit_code": None, "truncated": False}
    process: subprocess.Popen[bytes] | None = None
    data = bytearray()
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert process.stdout is not None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result["error"] = "TIMEOUT"
                break
            readable, _, _ = select.select([process.stdout], [], [], min(remaining, 0.1))
            if readable:
                chunk = os.read(process.stdout.fileno(), min(65536, max_bytes - len(data) + 1))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > max_bytes:
                    del data[max_bytes:]
                    result["truncated"] = True
                    break
            elif process.poll() is not None:
                break
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        result["error"] = str(exc)
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=1)
            result["exit_code"] = process.returncode
            if process.stdout is not None:
                process.stdout.close()
    result["output"] = data.decode(errors="replace")
    return result


def observe_health_event(event: dict[str, Any], journal: HealthJournal) -> None:
    actor = event.get("Actor", {})
    attributes = actor.get("Attributes", {})
    name, identity = attributes.get("name", ""), actor.get("ID", "")
    if (event.get("Type") != "container" or event.get("Action") != "health_status: unhealthy"
            or not isinstance(name, str) or not re.fullmatch(r"ocor-poc-[A-Za-z0-9_.-]+", name)
            or not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity)):
        return
    # Persist the event first; inspect by immutable UUID before any slower logs
    # or stats. Do not read Env/configuration, which can contain credentials.
    journal.write({"kind": "unhealthy_event", "identity": identity, "name": name,
                   "docker_time_ns": event.get("timeNano")})
    health_state = health_command([
        "docker", "inspect", "--format", '{{json .State}} {{json .RestartCount}}', identity])
    journal.write({"kind": "docker_diagnostic", **health_state})
    commands = [["docker", "logs", "--timestamps", "--tail", "200", identity]]
    service = attributes.get("com.docker.compose.service", "")
    if isinstance(service, str) and service.startswith("ocor-relay-"):
        upstream = service.removeprefix("ocor-relay-")
        if upstream in {"terminusdb", "typedb", "fuseki", "opa", "keycloak", "openbao", "kafka", "postgresql", "qdrant", "spire-server"}:
            # Fixed PoC recipe uses this dedicated project's service name.
            commands.append(["docker", "inspect", "--format", '{{json .State}} {{json .RestartCount}}', f"ocor-bootstrap-{upstream}-1"])
            commands.append(["docker", "logs", "--timestamps", "--tail", "200", f"ocor-bootstrap-{upstream}-1"])
    stack = health_command(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=ocor-bootstrap"])
    ids = stack["output"].split()
    if stack["exit_code"] == 0 and ids and all(re.fullmatch(r"[0-9a-f]{12,64}", value) for value in ids):
        commands.append(["docker", "stats", "--no-stream", "--format", "{{json .}}", identity, *ids[:11]])
    else:
        journal.write({"kind": "stack_inventory", **stack})
        commands.append(["docker", "stats", "--no-stream", "--format", "{{json .}}", identity])
    # Capture the state immediately, before inventory/stats can delay it.
    relay_logs = {}
    for command in commands:
        diagnostic = health_command(command)
        journal.write({"kind": "docker_diagnostic", **diagnostic})
        if command[:2] == ["docker", "logs"] and command[-1] == identity:
            relay_logs = diagnostic
    journal.write({"kind": "unhealthy_classification", "identity": identity, "name": name,
                   "classification": classify_readiness_gate(name, health_state, relay_logs),
                   "affects_test_outcome": False})


def classify_readiness_gate(name: str, state: dict[str, Any], logs: dict[str, Any]) -> str:
    """PO readiness interpretation: classify only the approved ops /readyz gate.

    The fixed ops healthcheck calls /readyz. Its HTTP 503 Health.Log and the
    same container's structured readiness_scan must corroborate RESTORE_UNTESTED.
    Missing, truncated, malformed or contradictory diagnostics stay UNCLASSIFIED.
    This function is never consumed by a qualifying gate.
    """
    if (not re.fullmatch(r"ocor-poc-.+-ocor-ops-[A-Za-z0-9_.-]+", name)
            or state.get("exit_code") != 0 or logs.get("exit_code") != 0
            or state.get("truncated") or logs.get("truncated")):
        return "UNCLASSIFIED"
    try:
        health, _ = json.JSONDecoder().raw_decode(state["output"])
        entries = health["Health"]["Log"]
        # Only the most recent failed health observation may identify this event.
        latest = entries[-1]
        if latest["ExitCode"] == 0 or "HTTP Error 503:" not in latest["Output"]:
            return "UNCLASSIFIED"
        for line in reversed(logs["output"].splitlines()):
            # Docker --timestamps prefixes an RFC3339 timestamp; keep plain JSON
            # usable for local deterministic diagnostic tests as well.
            payload = line[line.find("{"):]
            try:
                entry = json.loads(payload)
            except ValueError:
                continue
            trace = entry.get("span", {})
            if trace.get("operation") == "readiness_scan":
                if (trace.get("status") == "DENY" and trace.get("reason_code") == "RESTORE_UNTESTED"
                        and trace.get("ready_reasons") == ["RESTORE_UNTESTED"]):
                    return "EXPECTED_READINESS_GATE"
                return "UNCLASSIFIED"
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        pass
    return "UNCLASSIFIED"


def runner_health_sample() -> dict[str, Any]:
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        if key in {"MemTotal", "MemAvailable", "MemFree", "SwapTotal", "SwapFree"}:
            memory[key] = int(value.split()[0])
    return {"kind": "runner_sample", "sample_interval_seconds": HEALTH_SAMPLE_SECONDS,
            "load_average": list(os.getloadavg()), "cpu_count": os.cpu_count(),
            "cpu_ticks": [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]],
            "memory_kib": memory}


def run_health_observer(output: Path, timeout: int, since: int) -> int:
    """Separate process: errors here are diagnostic and never gate decisions."""
    output.mkdir(parents=True, exist_ok=True)
    repository = Path(__file__).resolve().parents[1]
    secrets = []
    env_file = repository / ".ocor/bootstrap.env"
    if env_file.is_file():
        secrets = [line.split("=", 1)[1] for line in env_file.read_text().splitlines()
                   if "=" in line and line.split("=", 1)[0].endswith(("TOKEN", "PASSWORD"))]
    journal = HealthJournal(output, secrets)
    finished = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: finished.set())
    start = time.monotonic()
    deadline = start + timeout

    def sample() -> None:
        while not finished.is_set() and time.monotonic() < deadline:
            try:
                journal.write(runner_health_sample())
            except (OSError, ValueError) as exc:
                journal.write({"kind": "observer_error", "error": str(exc)})
            finished.wait(HEALTH_SAMPLE_SECONDS)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    events: subprocess.Popen[bytes] | None = None
    try:
        # Replay events since launch to cover listener startup, never previous runs.
        events = subprocess.Popen(["docker", "events", "--since", str(since),
                                   "--filter", "type=container", "--filter", "event=health_status: unhealthy",
                                   "--format", "{{json .}}"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert events.stdout is not None
        pending = bytearray()
        while not finished.is_set() and time.monotonic() < deadline:
            ready, _, _ = select.select([events.stdout], [], [], 0.5)
            if ready:
                data = os.read(events.stdout.fileno(), 65536)
                if not data:
                    raise OSError("Docker health event stream ended")
                pending.extend(data)
                while b"\n" in pending:
                    line, _, pending = pending.partition(b"\n")
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            raise ValueError("Docker event must be an object")
                        observe_health_event(event, journal)
                    except (ValueError, TypeError, AttributeError) as exc:
                        journal.write({"kind": "observer_error", "error": str(exc)})
                if len(pending) > HEALTH_COMMAND_LIMIT:
                    raise ValueError("Docker event line exceeds observer byte limit")
        if not finished.is_set():
            journal.write({"kind": "observer_error", "error": "OBSERVER_TIMEOUT"})
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        journal.write({"kind": "observer_error", "error": str(exc)})
    finally:
        finished.set()
        sampler.join(timeout=1)
        if events is not None:
            if events.poll() is None:
                events.kill()
            events.wait(timeout=1)
            if events.stdout is not None:
                events.stdout.close()
        (output / "health-observer-status.json").write_text(json.dumps({
            "status": "DIAGNOSTIC_ONLY", "bytes_written": journal.bytes_written,
            "truncated": journal.truncated, "max_bytes": HEALTH_DATA_LIMIT,
            "command_max_bytes": HEALTH_COMMAND_LIMIT, "command_timeout_seconds": 5,
            "sample_interval_seconds": HEALTH_SAMPLE_SECONDS, "timeout_seconds": timeout,
        }, indent=2, sort_keys=True) + "\n")
    return 0


def start_health_observer(output: Path, limit: int) -> subprocess.Popen[Any] | None:
    try:
        return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--execute", "--observe-health",
                                 "--output-dir", str(output), "--observer-timeout", str(limit + 60),
                                 "--observer-since", str(int(time.time()))],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            (output / "health-observer-status.json").write_text(json.dumps({
                "status": "OBSERVER_START_FAILED_DIAGNOSTIC_ONLY", "error": str(exc)}, indent=2, sort_keys=True) + "\n")
        except OSError:
            print(json.dumps({"health_observer_error": str(exc), "status": "DIAGNOSTIC_ONLY"}), file=sys.stderr)
        return None


def finish_health_observer(process: subprocess.Popen[Any] | None, output: Path) -> None:
    """Never raise into the qualifying gate, including on observer crashes."""
    try:
        if process is not None:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=1)
        artifacts = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in output.glob("health-observer*") if path.is_file() and path.name != "health-observer-manifest.json"}
        (output / "health-observer-manifest.json").write_text(json.dumps({
            "status": "DIAGNOSTIC_ONLY", "observer_exit_code": process.returncode if process is not None else None,
            "artifacts": artifacts, "interpretation": "REM-0017-CI-0049-RELAY-HEALTH (2026-10-14), option 1",
        }, indent=2, sort_keys=True) + "\n")
    except (OSError, subprocess.SubprocessError) as exc:
        # Even inability to write diagnostic output cannot change pytest's result.
        print(json.dumps({"health_observer_error": str(exc), "status": "DIAGNOSTIC_ONLY"}), file=sys.stderr)

# Partition weights only; they never select or exclude a test. Mean seconds per
# case of each test function >= 3 s in the GitHub-runner PASS of candidate
# df444af (run on head f55b210, runtime JUnit SHA-256 4ba26f004afe9541...);
# the Helm case waits for a real */15 CronJob tick, so it carries its worst case.
DEFAULT_TEST_WEIGHT = 0.1
# REM19 independent GO on 90b30fff9819 qualifies isolated 0049 cases.
# PO REM-0017-CI-0049-REMAINDER-CAP (2026-10-10) supersedes whole-module
# assignment for 0049 only. Helm always gets its own runner and pinned cluster.
HELM_NODE = "tests/tasks/test_ocor_dev_0049.py::test_helm_profile_on_kubernetes_backs_up_restores_and_gates_readiness"
INDEPENDENT_MODULES = frozenset({"tests/tasks/test_ocor_dev_0049.py"})
SEPARABLE_NODES = frozenset({HELM_NODE})
MEASURED_WEIGHTS = {
    "tests.mission_thread.test_first_governed_slice::test_a_real_kafka_broker_restart_during_the_event_step_is_detected_and_recovers": 22,
    "tests.mission_thread.test_first_governed_slice::test_causal_receipt_reproduces_identically_with_the_same_pinned_inputs": 11,
    "tests.mission_thread.test_first_governed_slice::test_mission_thread_produces_correlated_receipts_across_all_governed_components": 11,
    "tests.tasks.test_ocor_dev_0019::test_campaign_uses_real_healthy_kafka": 21,
    "tests.tasks.test_ocor_dev_0021::test_paused_opa_is_denied_within_the_bounded_timeout_with_audit_evidence": 3,
    "tests.tasks.test_ocor_dev_0021::test_paused_openbao_is_denied_within_the_bounded_timeout_with_audit_evidence": 3,
    "tests.tasks.test_ocor_dev_0025::test_saga_reports_deletion_incomplete_when_typedb_is_paused_then_recovers": 22,
    "tests.tasks.test_ocor_dev_0040::test_a_registered_schema_event_publishes_and_is_consumed_preserving_all_fields": 10,
    "tests.tasks.test_ocor_dev_0040::test_a_replayed_idempotency_key_is_a_safe_no_op_not_a_duplicate_publish": 10,
    "tests.tasks.test_ocor_dev_0040::test_an_out_of_order_aggregate_effect_is_quarantined_and_never_published": 10,
    "tests.tasks.test_ocor_dev_0040::test_an_unknown_schema_is_quarantined_and_never_published": 7,
    "tests.tasks.test_ocor_dev_0040::test_missing_governed_context_is_quarantined_before_publication": 7,
    "tests.tasks.test_ocor_dev_0040::test_partition_order_is_preserved_for_a_single_aggregate": 14,
    "tests.tasks.test_ocor_dev_0041::test_a_failed_publish_is_recorded_as_an_immutable_permanent_dead_letter": 6,
    "tests.tasks.test_ocor_dev_0041::test_a_poisoned_event_cannot_be_replayed_without_explicit_operator_release": 6,
    "tests.tasks.test_ocor_dev_0041::test_a_valid_event_publishes_through_backpressure_and_is_delivered": 10,
    "tests.tasks.test_ocor_dev_0041::test_a_valid_replay_preserves_the_original_event_id_and_never_double_publishes": 9,
    "tests.tasks.test_ocor_dev_0041::test_backpressure_refuses_admission_once_a_tenant_is_at_its_bounded_quota": 7,
    "tests.tasks.test_ocor_dev_0041::test_operator_release_still_cannot_replay_past_an_incompatible_schema": 7,
    "tests.tasks.test_ocor_dev_0041::test_repeated_failures_of_the_same_event_are_classified_poison": 7,
    "tests.tasks.test_ocor_dev_0041::test_replay_of_lost_marking_is_blocked_exactly_like_a_fresh_publish": 7,
    "tests.tasks.test_ocor_dev_0048::test_client_rejects_peer_with_different_spiffe_id": 6,
    "tests.tasks.test_ocor_dev_0048::test_installed_bundle_expiry_fails_closed_at_decision_time": 3,
    "tests.tasks.test_ocor_dev_0048::test_paused_opa_fails_closed_within_bounded_timeout": 3,
    "tests.tasks.test_ocor_dev_0048::test_repair4_bundle_expiry_during_real_install": 3,
    "tests.tasks.test_ocor_dev_0048::test_repair4_decision_capped_at_canonical_authority": 4,
    "tests.tasks.test_ocor_dev_0048::test_repair4_expiry_during_real_secret_read": 3,
    "tests.tasks.test_ocor_dev_0048::test_repair4_openbao_scheduled_deletion_bounds_lease": 4,
    "tests.tasks.test_ocor_dev_0048::test_repair4_openbao_token_bounds_lease": 5,
    "tests.tasks.test_ocor_dev_0048::test_repair4_queued_delegation_expires": 3,
    "tests.tasks.test_ocor_dev_0048::test_repair4_svid_bounds_identity_and_secret": 19,
    "tests.tasks.test_ocor_dev_0048::test_repair4_svid_bounds_policy_and_rejects_expired_context": 14,
    "tests.tasks.test_ocor_dev_0048::test_repair4_token_expiry_during_real_authentication": 3,
    "tests.tasks.test_ocor_dev_0048::test_repair5_grant_cannot_be_transferred_to_another_workload": 7,
    "tests.tasks.test_ocor_dev_0049::test_backup_seals_an_encrypted_signed_immutable_recovery_point": 11,
    "tests.tasks.test_ocor_dev_0049::test_capture_fails_explicitly_when_the_database_is_unreachable": 13,
    "tests.tasks.test_ocor_dev_0049::test_concurrent_seals_each_download_their_own_index_snapshot": 4,
    "tests.tasks.test_ocor_dev_0049::test_custodian_signed_coherent_receipt_is_accepted": 11,
    "tests.tasks.test_ocor_dev_0049::test_custodian_signed_incoherent_receipt_blocks_readiness_reopen_and_admission": 10,
    "tests.tasks.test_ocor_dev_0049::test_custodian_signed_receipt_incoherent_with_its_checkpoint_is_refused": 10,
    "tests.tasks.test_ocor_dev_0049::test_custodian_signed_receipt_time_branches": 10,
    "tests.tasks.test_ocor_dev_0049::test_custodian_signed_receipt_unbound_from_its_recovery_point_is_refused": 10,
    "tests.tasks.test_ocor_dev_0049::test_custodian_signed_receipt_with_coherent_details_is_accepted": 10,
    "tests.tasks.test_ocor_dev_0049::test_dependency_fault_blocks_readiness_and_degrades_posture": 13,
    "tests.tasks.test_ocor_dev_0049::test_helm_profile_on_kubernetes_backs_up_restores_and_gates_readiness": 1200,
    "tests.tasks.test_ocor_dev_0049::test_inconsistent_deletion_journal_blocks_materialisation_and_readiness": 29,
    "tests.tasks.test_ocor_dev_0049::test_isolated_restore_replays_tombstones_and_passes_the_recovery_gate": 11,
    "tests.tasks.test_ocor_dev_0049::test_mutative_path_reopens_only_by_a_human_bound_to_the_passed_receipt": 6,
    "tests.tasks.test_ocor_dev_0049::test_new_release_is_ready_only_after_its_own_backup_and_tested_restore": 40,
    "tests.tasks.test_ocor_dev_0049::test_open_public_egress_blocks_readiness": 3,
    "tests.tasks.test_ocor_dev_0049::test_ops_process_serves_health_and_blocks_readiness_until_restore_is_tested": 24,
    "tests.tasks.test_ocor_dev_0049::test_policy_digest_in_logs_and_traces_covers_the_complete_opa_inventory": 14,
    "tests.tasks.test_ocor_dev_0049::test_quota_exceeded_backpressures_without_semantic_downgrade": 16,
    "tests.tasks.test_ocor_dev_0049::test_readiness_turns_ready_only_with_a_signed_passed_restore_receipt": 5,
    "tests.tasks.test_ocor_dev_0049::test_receipt_memory_branch_must_match_its_recovery_point": 10,
    "tests.tasks.test_ocor_dev_0049::test_release_drift_blocks_readiness_and_mutative_commands": 30,
    "tests.tasks.test_ocor_dev_0049::test_restart_under_another_release_profile_or_pins_blocks_readiness_reopen_and_admission": 4,
    "tests.tasks.test_ocor_dev_0049::test_restart_under_the_tested_release_is_ready_and_reopenable": 4,
    "tests.tasks.test_ocor_dev_0049::test_restore_replay_is_deterministic": 15,
    "tests.tasks.test_ocor_dev_0049::test_restore_scope_mismatch_blocks_materialisation": 33,
    "tests.tasks.test_ocor_dev_0049::test_scanner_failure_denies_every_admission_until_the_scan_recovers": 10,
    "tests.tasks.test_ocor_dev_0049::test_seal_and_restore_tied_epoch_tombstones_are_locale_independent": 248,
    "tests.tasks.test_ocor_dev_0049::test_tampered_recovery_point_is_rejected_before_restore": 7,
    "tests.tasks.test_ocor_dev_0049::test_tampered_restore_receipt_blocks_readiness": 5,
}


class CampaignError(RuntimeError):
    """The campaign cannot supply qualifying evidence."""



def check_deadline(elapsed: float, *, limit: int = FULL_SUITE_LIMIT_SECONDS, threshold: int = PO_DECISION_THRESHOLD_SECONDS) -> bool:
    if elapsed >= limit:
        raise CampaignError(f"{limit // 60}-minute campaign limit reached")
    return elapsed > threshold


def junit_identity(nodeid: str) -> tuple[str, str]:
    """(classname, name) that pytest's junitxml reports for a node ID."""
    path, bracket, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = names[0].replace("/", ".")
    if names[0].endswith(".py"):
        names[0] = names[0][:-3]
    names[-1] += bracket + params
    return ".".join(names[:-1]), names[-1]


def node_weight(nodeid: str) -> float:
    classname, name = junit_identity(nodeid)
    return MEASURED_WEIGHTS.get(f"{classname}::{name.split('[', 1)[0]}", DEFAULT_TEST_WEIGHT)


def collection_digest(nodeids: list[str]) -> str:
    return hashlib.sha256("\n".join(nodeids).encode()).hexdigest()


def partition_digest(parts: list[list[str]]) -> str:
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def pytest_environment(directory: Path) -> dict[str, str]:
    """Resolve runtime and root packages from the suite's own checkout in every phase."""
    suite = directory.resolve()
    environment = os.environ.copy()
    paths = [str(suite / "src"), str(suite.parent)]
    if inherited := environment.get("PYTHONPATH"):
        paths.append(inherited)
    environment["PYTHONPATH"] = os.pathsep.join(paths)
    return environment


def collect_nodeids(directory: Path, selection: list[str]) -> list[str]:
    """Node IDs pytest collects in ``directory``; any collection error fails closed."""
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *selection],
                            cwd=directory, env=pytest_environment(directory), capture_output=True, text=True, timeout=600, check=False)
    nodeids = [line for line in result.stdout.splitlines() if "::" in line and not line.startswith(" ")]
    if result.returncode or not nodeids or len(nodeids) != len(set(nodeids)):
        raise CampaignError(f"pytest collection failed (exit {result.returncode}): {result.stdout[-2000:]}{result.stderr[-2000:]}")
    return nodeids


def partition_units(nodeids: list[str]) -> list[list[str]]:
    """Keep other modules whole; qualified 0049 cases are independent units."""
    units: dict[str, list[str]] = {}
    for node in nodeids:
        module = node.split("::", 1)[0]
        units.setdefault(node if module in INDEPENDENT_MODULES else module, []).append(node)
    return list(units.values())


def partition(nodeids: list[str], count: int) -> list[list[str]]:
    """Reserve Helm, then balance whole units deterministically across other parts.

    Each part keeps collection order. The exact-union gate still accepts every
    collected node exactly once; only assignment changes.
    """
    if count < 2:
        raise CampaignError("the suite must run in at least 2 parts")
    if len(nodeids) != len(set(nodeids)) or len(nodeids) < count:
        raise CampaignError(f"cannot partition {len(nodeids)} collected tests into {count} nonempty parts")
    if len({junit_identity(node) for node in nodeids}) != len(nodeids):
        raise CampaignError("collected node IDs are not uniquely identifiable in JUnit")
    reserved = [HELM_NODE] if HELM_NODE in nodeids else []
    units = partition_units([node for node in nodeids if node not in reserved])
    first = 1 if reserved else 0
    if len(units) < count - first:
        raise CampaignError(f"cannot partition {len(units) + first} units into {count} nonempty parts")
    loads = [(0.0, index) for index in range(first, count)]
    assigned: list[list[str]] = [[] for _ in range(count)]
    if reserved:
        assigned[0] = reserved
    for unit in sorted(units, key=lambda item: (-sum(map(node_weight, item)), item[0])):
        load, index = heapq.heappop(loads)
        assigned[index].extend(unit)
        heapq.heappush(loads, (load + sum(map(node_weight, unit)), index))
    order = {node: position for position, node in enumerate(nodeids)}
    parts = [sorted(part, key=order.__getitem__) for part in assigned]
    if not all(parts):
        raise CampaignError("a part received no tests")
    return parts


def junit_cases(path: Path) -> list[tuple[str, str]]:
    """Every executed case; a case with failure, error or skip is nonqualifying."""
    check_junit(path)
    cases = []
    for case in ET.parse(path).getroot().iter("testcase"):
        if any(child.tag in ("failure", "error", "skipped") for child in case):
            raise CampaignError(f"nonqualifying JUnit case: {case.get('classname')}::{case.get('name')}")
        cases.append((case.get("classname", ""), case.get("name", "")))
    return cases


def combine_coverage(suite: Path, files: list[Path], output: Path) -> None:
    data = output / "runtime_coverage.combined"
    copies = []
    for index, source in enumerate(files, start=1):
        copies.append(output / f"runtime_coverage.part-{index}")
        shutil.copyfile(source, copies[-1])
    for command in ([sys.executable, "-m", "coverage", "combine", f"--data-file={data}", *map(str, copies)],
                    [sys.executable, "-m", "coverage", "json", f"--data-file={data}", "-o", str(output / "runtime_coverage_post_approval.json")]):
        result = subprocess.run(command, cwd=suite, capture_output=True, text=True, timeout=600, check=False)
        if result.returncode:
            raise CampaignError(f"coverage aggregation failed: {result.stdout[-1000:]}{result.stderr[-1000:]}")


def aggregate(parts_dir: Path, suite_repository: Path, count: int, output: Path, *, required_modules: list[str]) -> dict[str, Any]:
    """Accept the parts only if their union is exactly the suite collected on this HEAD."""
    output.mkdir(parents=True, exist_ok=True)
    try:
        suite = suite_repository / "ocor-runtime"
        collected = collect_nodeids(suite, ["tests/"])
        expected = partition(collected, count)
        found: dict[int, Path] = {}
        for meta_path in sorted(parts_dir.rglob("partition.json")):
            meta = json.loads(meta_path.read_text())
            index = meta.get("shard_index")
            if meta.get("shard_count") != count or not isinstance(index, int) or not 1 <= index <= count or index in found:
                raise CampaignError(f"invalid or repeated shard metadata: {meta_path}")
            found[index] = meta_path.parent
        if sorted(found) != list(range(1, count + 1)):
            raise CampaignError(f"expected parts 1..{count}, found {sorted(found)}")
        executed: list[tuple[str, str]] = []
        parts: list[dict[str, Any]] = []
        durations: list[float] = []
        cases_by_part = []
        for index in range(1, count + 1):
            directory = found[index]
            if missing_files := [name for name in PART_ARTIFACTS if not (directory / name).is_file()]:
                raise CampaignError(f"part {index} lacks {missing_files} (coverage data is mandatory)")
            meta = json.loads((directory / "partition.json").read_text())
            if meta.get("collected_sha256") != collection_digest(collected) or meta.get("collected_count") != len(collected):
                raise CampaignError(f"part {index} ran a different collection than this HEAD")
            if meta.get("selected") != expected[index - 1] or meta.get("partition_sha256") != partition_digest(expected):
                raise CampaignError(f"part {index} selection differs from the deterministic partition")
            result = json.loads((directory / "campaign_result.json").read_text())
            if result.get("status") != "PASS" or result.get("shard_index") != index or result.get("shard_count") != count:
                raise CampaignError(f"part {index} campaign is not PASS for this shard")
            duration = float(result["duration_seconds"])
            check_deadline(duration, limit=PART_LIMIT_SECONDS, threshold=PART_REBALANCE_SECONDS)
            cases = junit_cases(directory / "runtime_junit_post_approval.xml")
            cases_by_part.append(directory / "runtime_junit_post_approval.xml")
            executed.extend(cases)
            durations.append(duration)
            parts.append({"shard_index": index, "tests": len(cases), "duration_seconds": duration,
                          "selected_sha256": hashlib.sha256(json.dumps(expected[index - 1]).encode()).hexdigest()})
        wanted = {junit_identity(node) for node in collected}
        occurrences = Counter(executed)
        seen = set(occurrences)
        duplicated = sorted(case for case, times in occurrences.items() if times > 1)
        discrepancies = {"missing": sorted("::".join(case) for case in wanted - seen),
                         "duplicated": ["::".join(case) for case in duplicated],
                         "unexpected": sorted("::".join(case) for case in seen - wanted)}
        for key, cases_found in discrepancies.items():
            if cases_found:
                raise CampaignError(f"union of parts has {key} tests: {cases_found[:20]}")
        union = {"collected": len(collected), "executed": len(executed), **discrepancies}
        modules = {part for classname, _ in executed for part in classname.split(".")}
        if absent := set(required_modules) - modules:
            raise CampaignError(f"required guard not executed: {sorted(absent)}")
        merged = ET.Element("testsuites")
        for index, path in enumerate(cases_by_part, start=1):
            root = ET.parse(path).getroot()
            for suite_element in ([root] if root.tag == "testsuite" else list(root.iter("testsuite"))):
                suite_element.set("name", f"{suite_element.get('name', 'pytest')}-part-{index}")
                merged.append(suite_element)
        ET.ElementTree(merged).write(output / "runtime_junit_post_approval.xml", encoding="utf-8", xml_declaration=True)
        check_junit(output / "runtime_junit_post_approval.xml", required_modules=required_modules)
        combine_coverage(suite, [found[index] / "runtime_coverage.data" for index in range(1, count + 1)], output)
        longest = max(durations)
        summary = {"status": "PASS", "mode": "AGGREGATE", "shard_count": count, "parts": parts, "union": union,
                   "counts": {"tests": len(executed), "failures": 0, "errors": 0, "skipped": 0},
                   "collected_sha256": collection_digest(collected), "partition_sha256": partition_digest(expected),
                   "required_modules": required_modules, "longest_part_seconds": longest,
                   "rebalance_required": longest > PART_REBALANCE_SECONDS}
        (output / "campaign_result.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        return summary
    except (CampaignError, OSError, ValueError, KeyError, TypeError, ET.ParseError, subprocess.SubprocessError) as exc:
        (output / "campaign_result.json").write_text(json.dumps({"status": "FAIL", "mode": "AGGREGATE", "error": str(exc)}, indent=2, sort_keys=True) + "\n")
        if isinstance(exc, CampaignError):
            raise
        raise CampaignError(str(exc)) from exc


def check_stack(initial: dict[str, Any], current: dict[str, Any]) -> None:
    if not initial or initial.keys() != current.keys():
        raise CampaignError("mandatory stack disappeared")
    for name, before in initial.items():
        after = current[name]
        if (after["Id"] != before["Id"] or after["RestartCount"] != before["RestartCount"]
                or after["State"].get("StartedAt") != before["State"].get("StartedAt")
                or not after["State"]["Running"] or after["State"].get("OOMKilled")):
            raise CampaignError(f"service restarted, stopped or OOM killed: {name}")


def check_junit(path: Path, *, required_modules: list[str] | None = None) -> dict[str, int]:
    try:
        tree = ET.parse(path).getroot()
        suites = [tree] if tree.tag == "testsuite" else list(tree.iter("testsuite"))
        counts = {key: sum(int(suite.get(key, "0")) for suite in suites) for key in ("tests", "failures", "errors", "skipped")}
        if not counts["tests"] or any(counts[key] for key in ("failures", "errors", "skipped")) or list(tree.iter("skipped")):
            raise CampaignError(f"nonqualifying JUnit: {counts}")
        modules = {part for case in tree.iter("testcase") for part in case.get("classname", "").split(".")}
        if missing := set(required_modules or []) - modules:
            raise CampaignError(f"required guard not executed: {sorted(missing)}")
        return counts
    except (OSError, ET.ParseError, ValueError) as exc:
        raise CampaignError("JUnit absent or invalid") from exc


def verify_revision(repository: Path, expected_head: str) -> None:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    if head != expected_head:
        raise CampaignError(f"candidate HEAD mismatch: {head}")
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repository, capture_output=True, text=True, timeout=10, check=True).stdout
    if dirty:
        raise CampaignError("candidate has tracked changes")


def inspect_stack() -> dict[str, Any]:
    ids = subprocess.run(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=ocor-bootstrap"], capture_output=True, text=True, timeout=10, check=True).stdout.split()
    if not ids:
        return {}
    raw = subprocess.run(["docker", "inspect", *ids], capture_output=True, text=True, timeout=10, check=True).stdout
    return {entry["Name"]: entry for entry in json.loads(raw)}


def inspect_kubernetes_runtimes_raw() -> dict[str, dict[str, Any]]:
    """Observe systemd inside only the disposable OCOR kind nodes.

    A containerd restart does not change Docker's container RestartCount.
    Nodes may appear and disappear as the Kubernetes fixture starts and tears down.
    """
    ids = kind_observer.run_probe(["docker", "ps", "-q", "--filter", "label=io.x-k8s.kind.cluster=ocor-poc"],
                         capture_output=True, text=True, timeout=10, check=True).stdout.split()
    if not ids:
        return {}
    raw = kind_observer.run_probe(["docker", "inspect", *ids], capture_output=True, text=True, timeout=10, check=True).stdout
    current = {}
    for node in json.loads(raw):
        if (not node["Name"].startswith("/ocor-poc-")
                or node["Config"]["Labels"].get("io.x-k8s.kind.cluster") != "ocor-poc"):
            raise CampaignError("Kubernetes node outside owned scope")
        for service in ("containerd", "kubelet"):
            result = kind_observer.run_probe(["docker", "exec", node["Id"], "systemctl", "show", service,
                                     "--property=ActiveState,MainPID,NRestarts"],
                                    capture_output=True, text=True, timeout=10, check=True)
            values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            current[node["Id"] + ":" + service] = {
                "restarts": int(values["NRestarts"]), "active": values["ActiveState"], "pid": int(values["MainPID"]),
                # The immutable fixture connects this network only after
                # kind create --wait succeeds, before any workload dispatch.
                "admitted": "ocor-bootstrap_ocor-bootstrap" in node.get("NetworkSettings", {}).get("Networks", {})}
    return current


def inspect_kubernetes_runtimes() -> dict[str, dict[str, Any]]:
    return kind_observer.inspect_kubernetes_runtimes(inspect_kubernetes_runtimes_raw)


def qualification_kind_binary(repository: Path) -> Path:
    for parent in (repository, *repository.parents):
        binary = parent / ".ocor/tools/bin/kind"
        if binary.is_file():
            return binary.resolve()
    found = shutil.which("kind")
    if found:
        return Path(found).resolve()
    # An absent official binary cannot prove intended removal.
    return repository / ".ocor/tools/bin/kind"


def check_kubernetes_runtimes(history: dict[str, dict[str, Any]], current: dict[str, dict[str, Any]]) -> None:
    for identity, after in current.items():
        before = history.get(identity)
        initializing_kubelet = identity.endswith(":kubelet") and not after.get("admitted", True) and before is None
        if (after["restarts"] != 0 or after["active"] == "failed"
                or (after.get("admitted", False) and (after["active"] != "active" or after["pid"] <= 0))
                or (before is not None and (after["active"] != "active" or after["pid"] != before["pid"]))):
            raise CampaignError(f"Kubernetes service restarted or failed: {identity}")
        if not initializing_kubelet and after["active"] == "active" and after["pid"] > 0:
            history[identity] = after

    # Absence in docker ps is not proof of an intended teardown. Every UUID
    # previously observed must have the same v2 remover/destroy proof.
    missing = set(history) - set(current)
    for node in sorted({identity.split(":", 1)[0] for identity in missing}):
        kind_observer.confirm_missing_node(node)
    for identity in missing:
        del history[identity]


def collect_kubernetes_diagnostics(output: Path) -> None:
    """Collect before SIGINT allows the fixture to remove its owned kind node."""
    with output.open("w") as log:
        try:
            current = inspect_kubernetes_runtimes()
            log.write(json.dumps(current, sort_keys=True) + "\n")
            for node in sorted({key.split(":", 1)[0] for key in current}):
                for command in (["docker", "stats", "--no-stream", node],
                                ["docker", "exec", node, "journalctl", "-u", "containerd", "-u", "kubelet", "--no-pager", "-n", "200"]):
                    result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
                    log.write(result.stdout + result.stderr)
        except (OSError, subprocess.SubprocessError, CampaignError, KeyError, ValueError) as exc:
            log.write(f"Kubernetes diagnostics incomplete: {exc}\n")


def stop(process: subprocess.Popen[Any], *, resume: bool = False) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    if resume:
        os.killpg(process.pid, signal.SIGCONT)
    try:
        process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository", type=Path, help="separate, immutable candidate checkout; always runs its FULL suite")
    parser.add_argument("--expected-head", help="exact candidate commit, required with --repository")
    parser.add_argument("--shard-count", type=int, help="number N >= 2 of deterministic CI parts")
    parser.add_argument("--shard-index", type=int, help="1-based part executed on this runner's own stack")
    parser.add_argument("--aggregate", type=Path, metavar="PARTS_DIR", help="verify the parts' union against --collect-only")
    parser.add_argument("--observe-health", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--observer-timeout", type=int, default=FULL_SUITE_LIMIT_SECONDS + 60, help=argparse.SUPPRESS)
    parser.add_argument("--observer-since", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.observe_health:
        if not args.execute or not 1 <= args.observer_timeout <= FULL_SUITE_LIMIT_SECONDS + 60:
            parser.error("health observation requires --execute and a bounded timeout")
        return run_health_observer(args.output_dir.resolve(), args.observer_timeout, args.observer_since or int(time.time()))
    if bool(args.repository) != bool(args.expected_head):
        parser.error("--repository and --expected-head must be supplied together")
    if args.shard_count is not None and args.shard_count < 2:
        parser.error("--shard-count must be at least 2")
    if args.shard_index is not None and (args.shard_count is None or args.aggregate or not 1 <= args.shard_index <= args.shard_count):
        parser.error("--shard-index requires --shard-count and must be within 1..N")
    if args.aggregate and (args.shard_count is None or not args.execute):
        parser.error("--aggregate requires --shard-count and --execute")
    if args.shard_count is not None and args.shard_index is None and not args.aggregate:
        parser.error("--shard-count requires --shard-index or --aggregate")
    repository = Path(__file__).resolve().parents[1]
    suite_repository = args.repository.resolve() if args.repository else repository
    required_modules = ["test_ocor_dev_0048"]
    if args.repository or (suite_repository / "ocor-runtime/tests/tasks/test_ocor_dev_0049.py").is_file():
        required_modules.append("test_ocor_dev_0049")
    if not args.execute:
        if args.expected_head:
            verify_revision(suite_repository, args.expected_head)
        print(json.dumps({"status": "PASS", "mode": "CHECK_ONLY", "repository": str(suite_repository), "suite": "ocor-runtime/tests/", "limit_seconds": FULL_SUITE_LIMIT_SECONDS}))
        return 0
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.aggregate:
        try:
            if args.expected_head:
                verify_revision(suite_repository, args.expected_head)
            summary = aggregate(args.aggregate.resolve(), suite_repository, args.shard_count, output, required_modules=required_modules)
            if args.expected_head:
                verify_revision(suite_repository, args.expected_head)
        except (CampaignError, OSError, subprocess.SubprocessError) as exc:
            (output / "campaign_result.json").write_text(json.dumps({"status": "FAIL", "mode": "AGGREGATE", "error": str(exc)}, indent=2, sort_keys=True) + "\n")
            print(json.dumps({"status": "FAIL", "error": str(exc)}))
            return 1
        print(json.dumps(summary))
        return 0
    junit = output / "runtime_junit_post_approval.xml"
    sharded = args.shard_index is not None
    limit, threshold = (PART_LIMIT_SECONDS, PART_REBALANCE_SECONDS) if sharded else (FULL_SUITE_LIMIT_SECONDS, PO_DECISION_THRESHOLD_SECONDS)
    selection = ["tests/"]
    command = [sys.executable, "-m", "pytest", "-v", "--cov=src", "--cov-report=term-missing", f"--cov-report=json:{output / 'runtime_coverage_post_approval.json'}", f"--junitxml={junit}"]
    process: subprocess.Popen[Any] | None = None
    recorder: SessionRecorder | None = None
    observer_thread = None
    health_observer = None
    decision_required = False
    try:
        if args.expected_head:
            verify_revision(suite_repository, args.expected_head)
        if sharded:
            # Select explicit node IDs (never deselect) and prove pytest collects
            # exactly that selection before any test runs.
            collected = collect_nodeids(suite_repository / "ocor-runtime", ["tests/"])
            parts = partition(collected, args.shard_count)
            selection = parts[args.shard_index - 1]
            if collect_nodeids(suite_repository / "ocor-runtime", selection) != selection:
                raise CampaignError("part selection does not collect exactly its node IDs")
            (output / "partition.json").write_text(json.dumps({
                "collected_count": len(collected), "collected_sha256": collection_digest(collected),
                "partition_sha256": partition_digest(parts), "selected": selection,
                "selected_weight_seconds": sum(node_weight(node) for node in selection),
                "shard_count": args.shard_count, "shard_index": args.shard_index}, indent=2, sort_keys=True) + "\n")
            required_modules = []
        command.extend(selection)
        initial = inspect_stack()
        if len(initial) != 11:
            raise CampaignError(f"expected 11 mandatory containers, found {len(initial)}")
        check_stack(initial, initial)
        recorder = SessionRecorder(repository)
        health_observer = start_health_observer(output, limit)
        kubernetes_history: dict[str, dict[str, Any]] = {}
        start = time.monotonic()
        with (output / "post_remediation_runtime.log").open("w") as log:
            process = subprocess.Popen(command, cwd=suite_repository / "ocor-runtime",
                                       env=pytest_environment(suite_repository / "ocor-runtime"),
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            observer_thread = kind_observer.start_sampler(process.pid, qualification_kind_binary(suite_repository))
            while process.poll() is None:
                check_stack(initial, inspect_stack())
                current = inspect_kubernetes_runtimes()
                with (output / "kubernetes-runtime.log").open("a") as runtime_log:
                    runtime_log.write(json.dumps(current, sort_keys=True) + "\n")
                check_kubernetes_runtimes(kubernetes_history, current)
                decision_required = check_deadline(time.monotonic() - start, limit=limit, threshold=threshold) or decision_required
                time.sleep(5)
            check_stack(initial, inspect_stack())
            check_kubernetes_runtimes(kubernetes_history, inspect_kubernetes_runtimes())
        decision_required = check_deadline(time.monotonic() - start, limit=limit, threshold=threshold) or decision_required
        if process.returncode:
            raise CampaignError(f"pytest exit code {process.returncode}")
        if args.expected_head:
            verify_revision(suite_repository, args.expected_head)
        result = {"status": "PASS", "counts": check_junit(junit, required_modules=required_modules), "duration_seconds": time.monotonic() - start, "candidate_head": args.expected_head, "required_modules": required_modules, "po_decision_required": decision_required}
        if sharded:
            if sorted(junit_cases(junit)) != sorted(junit_identity(node) for node in selection):
                raise CampaignError("part JUnit differs from its selection")
            shutil.copyfile(suite_repository / "ocor-runtime/.coverage", output / "runtime_coverage.data")
            result.update({"shard_index": args.shard_index, "shard_count": args.shard_count, "limit_seconds": limit,
                           "rebalance_required": decision_required, "po_decision_required": False})
        (output / "campaign_result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result))
        return 0
    except (CampaignError, kind_observer.TeardownObservationError, OSError, subprocess.SubprocessError, KeyError, ValueError) as exc:
        # Suspend the owned pytest process group immediately. Preserve the node
        # for diagnostics, then deliver SIGINT before resuming fixture teardown.
        frozen = False
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGSTOP)
                frozen = True
            except ProcessLookupError:
                pass
        try:
            collect_kubernetes_diagnostics(output / "kubernetes-diagnostics.log")
            if (repository / ".ocor/bootstrap.env").exists():
                redact_campaign_log(repository, output / "kubernetes-diagnostics.log")
        finally:
            if process is not None:
                stop(process, resume=frozen)
        collect_stack_diagnostics(repository, output / "docker-stats.log")
        result = {"status": "FAIL", "error": str(exc), "po_decision_required": decision_required}
        (output / "campaign_result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result))
        return 1
    finally:
        if process is not None:
            stop(process)
        finish_health_observer(health_observer, output)
        if observer_thread is not None:
            kind_observer.stop_sampler(observer_thread)
            (output / "kind-teardown-observations.json").write_text(json.dumps({
                "removals": kind_observer.REMOVALS, "rejections": kind_observer.REJECTIONS,
                "window_seconds": kind_observer.WINDOW_SECONDS,
                "remover_observations": kind_observer.REMOVER_OBSERVATIONS,
                "probe_observations": kind_observer.PROBE_OBSERVATIONS,
                "bootstrap_recoveries": kind_observer.BOOTSTRAP_RECOVERIES,
            }, indent=2, sort_keys=True) + "\n")
        recorder_error = None
        if recorder is not None:
            try:
                recorder.finish()
            except (OSError, ValueError, subprocess.SubprocessError, RuntimeError, KeyError, TypeError, AttributeError) as exc:
                recorder_error = str(exc)
                (output / "campaign_result.json").write_text(json.dumps({"status": "FAIL", "error": recorder_error}, indent=2, sort_keys=True) + "\n")
        if process is not None:
            redact_campaign_log(repository, output / "post_remediation_runtime.log")
            if junit.exists():
                redact_campaign_log(repository, junit)
        if recorder_error is not None:
            print(json.dumps({"status": "FAIL", "error": recorder_error}))
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
