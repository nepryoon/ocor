"""OCOR-DEV-0049: PoC deployment profiles — health, metrics, logs, traces,
backup/replay and bounded safe-degraded modes (ADD v1.3 Part I §6, Part II §2.13;
LLD v1.1 §5).

Repair cycle 7 (implementer: Codex; verifier: Claude Code; PO decision
OCOR-DEV-0049-REPAIR-7; cycles 2–6 repaired by Claude Code). Every criterion is proven on behaviour of real
processes on the digest-pinned stack, never on configuration booleans or string
searches:

* the ops agent (single source: `configs.ocor-ops-agent` of
  `deploy/helm/ocor-poc/compose.profiles.yaml`, mounted by the Helm chart from
  the same file) is executed as a real process: it refuses to start on an
  invalid profile, serves `/livez` `/readyz` `/metrics` `/traces` `/posture`
  `/admit`, and probes every mandatory dependency semantically;
* readiness is observed to block on a paused dependency, an untested or
  tampered restore, release drift and an open public egress path; the
  admission decisions of every operation class are observed in the same
  states (scanner failure, unverified restore and open egress admit nothing;
  a passed recovery gate reopens the mutative path only on a human
  authorization bound to that signed receipt);
* every destination/port pair outside the allowlist is refused (one relay per
  destination on Compose, one address/port rule per flow on Helm);
* the recovery gate compares tenant, compartments, marking and GCS binding of
  every restored projection item with the authoritative metadata;
* a restore counts as tested only through a receipt that is signed by the real
  custodian AND coherent (every recovery-gate check strictly passed, step
  statuses, quarantine, materialisation) AND bound, with its recovery point, to
  the running release, profile digest and image pins; a restart or upgrade to
  another release/profile/pin set is denied until its own backup and restore;
* every workload image of both profiles is exactly a governed digest pin: the
  Helm chart renders Deployment, backup and restore images only from
  `ocor.images.pins` (the pins the release binding covers) and refuses tag-only
  pins and any separate image override; an upgrade to other pins runs the new
  artifact but is denied until its own tested restore;
* a PASSED check whose typed detail reports a violation (tenant, compartment,
  GCS, marking, orphan, duplicate, resurrection, drift, count difference) is
  incoherent; signed records are parsed as strict JSON (no NaN/Infinity) and
  every receipt time is finite, past, coherent with its ISO form and unexpired;
* the policy digest in logs and traces is the digest of the COMPLETE OPA
  inventory, read up to an explicit bound; an oversized, truncated or malformed
  inventory yields no digest and an explicit reason code;
* each backup job is correlated with the recovery point it wrote (also when a
  manual run overlaps the scheduled CronJob tick) and the restore drill is
  bound to that recovery point;
* backups are produced from the real PostgreSQL/Kafka/Qdrant/OPA backends,
  encrypted and signed by OpenBao transit, written immutably to a vault outside
  the workload fault domain, restored on an isolated network with tombstone
  replay before retrieval, and rejected when tampered or inconsistent;
* default-deny is observed with allowed and denied connections;
* the Helm chart is installed on a disposable kind cluster (DEC-211) and its
  pod readiness, egress denial and fault behaviour are observed.

A missing mandatory environment or service is an explicit FAILURE, never a
skip (verdict OCOR-DEV-0049-2c5a574a5f3a-1 VF-006). E1=0, E2=0, no Verified
requirement and no G6 qualification are claimed.
"""

from __future__ import annotations

import base64
import calendar
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CHART_DIR = ROOT / "deploy" / "helm" / "ocor-poc"
VALUES = CHART_DIR / "values.yaml"
OVERLAY = CHART_DIR / "compose.profiles.yaml"
OPS_IMAGE = "python:3.11@sha256:c7220863385ee39fb6d822da81f4469d0cd33ff893d92ce94105e5c3f4b95fe2"
# A different, real Python artifact (verdict OCOR-DEV-0049-aefabf91777d-4 VF-001 probe:
# Python 3.11.17, config cc5f2f88..., against 3.11.15 of the governed pin).
OTHER_OPS_IMAGE = "python@sha256:27e044f7e01fea05c1760324d58fc5360a0767b9ef098e74ddaf8c70b8f46d26"
BOOTSTRAP_NETWORK = "ocor-bootstrap_ocor-bootstrap"
BOOTSTRAP_SERVICES = [
    "terminusdb", "typedb", "fuseki", "opa", "keycloak", "openbao",
    "postgresql", "kafka", "qdrant", "spire-server",
]
LOG_FIELDS = ["correlation_id", "component", "operation", "release", "policy_digest", "reason_code"]
RECOVERY_GATE = [
    "revision", "watermark", "orphan_duplicate", "marking", "gcs",
    "deletion_resurrection", "projection_drift_or_stale_deletion_epoch",
    "sample_semantic_digest",
]
EXIT_CONFIG, EXIT_BACKPRESSURE, EXIT_VERIFY, EXIT_GATE = 78, 75, 65, 66
OPERATION_CLASSES = ["read", "exact_consistency_read", "governed_new", "mutative", "high_impact", "dispatch"]
GOVERNED_WRITE_CLASSES = ["governed_new", "mutative", "high_impact", "dispatch"]


# --------------------------------------------------------------------------- sources


def overlay() -> dict:
    return yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))


def agent_source() -> str:
    return overlay()["configs"]["ocor-ops-agent"]["content"]


def helm_profile() -> dict:
    return yaml.safe_load(VALUES.read_text(encoding="utf-8"))["ocor"]


def compose_profile() -> dict:
    # Compose interpolation turns `$$` into `$`; the agent source has no `$`.
    return json.loads(overlay()["configs"]["ocor-poc-profile"]["content"].replace("$$", "$"))


@pytest.fixture(scope="session")
def agent_dir(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("ocor-ops-agent")
    (path / "ocor_ops_agent.py").write_text(agent_source(), encoding="utf-8")
    (path / "profile.json").write_text(json.dumps(helm_profile()), encoding="utf-8")
    return path


def run_agent(agent_dir: Path, *args: str, profile: dict | None = None,
              env: dict | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    prof = agent_dir / "profile.json"
    if profile is not None:
        prof = agent_dir / f"profile-{uuid.uuid4().hex}.json"
        prof.write_text(json.dumps(profile), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(agent_dir / "ocor_ops_agent.py"), args[0], "--profile", str(prof), *args[1:]],
        capture_output=True, text=True, timeout=timeout, env={**os.environ, **(env or {})}, check=False)


def tool(name: str) -> str:
    # DEC-211 tools (helm, kind, kubectl) are acquired with verified checksums into
    # the untracked `.ocor/tools/bin` of the checkout (a worktree walks up to it).
    for parent in (ROOT, *Path(__file__).resolve().parents):
        candidate = parent / ".ocor" / "tools" / "bin" / name
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    if not found:
        pytest.fail(f"mandatory tool {name} is unavailable (DEC-211 provisioning required); not a skip")
    return found


# --------------------------------------------------------------------------- contract


def test_agent_is_a_single_source_shared_by_compose_and_helm():
    rendered = helm_template()
    configmap = next(d for d in rendered if d["kind"] == "ConfigMap")
    assert configmap["data"]["ocor_ops_agent.py"] == agent_source()
    assert json.loads(configmap["data"]["profile.json"]) == helm_profile()
    assert compose_profile() == helm_profile(), "Compose and Helm profile carriers drift"


def test_agent_source_passes_ruff_and_mypy_strict(agent_dir):
    """The embedded program stays under the repository quality gates. mypy belongs to the
    `lint` extra: the declared environment is `uv run --project ocor-runtime --frozen
    --extra test --extra lint`; without it the precondition fails explicitly (no skip)."""
    import importlib.util

    if importlib.util.find_spec("mypy") is None:
        pytest.fail("precondition: mypy is not installed in this interpreter; run the suite in the declared "
                    "environment `uv run --project ocor-runtime --frozen --extra test --extra lint pytest ...`")
    ruff = subprocess.run([tool("ruff"), "check", "--config", str(ROOT / "pyproject.toml"),
                           str(agent_dir / "ocor_ops_agent.py")], capture_output=True, text=True, check=False)
    assert ruff.returncode == 0, ruff.stdout + ruff.stderr
    mypy = subprocess.run([sys.executable, "-m", "mypy", "--strict", "--python-version", "3.11",
                           "--no-incremental", str(agent_dir / "ocor_ops_agent.py")],
                          capture_output=True, text=True, check=False, cwd=agent_dir)
    assert mypy.returncode == 0, mypy.stdout + mypy.stderr


def test_valid_profile_is_accepted_by_the_startup_gate(agent_dir):
    result = run_agent(agent_dir, "validate")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["reason_code"] == "PROFILE_VALID"


def _set(path: str, value):
    def mutate(profile: dict) -> None:
        node = profile
        keys = path.split(".")
        for key in keys[:-1]:
            node = node[int(key)] if isinstance(node, list) else node[key]
        last = keys[-1]
        if isinstance(node, list):
            node[int(last)] = value
        else:
            node[last] = value
    return mutate


def _drop_dependency(name: str):
    def mutate(profile: dict) -> None:
        profile["health"]["dependencies"] = [d for d in profile["health"]["dependencies"] if d["name"] != name]
    return mutate


def _reorder_tombstone(profile: dict) -> None:
    steps = profile["restore"]["steps"]
    steps.remove("replay_memory_deletion_tombstones_before_reopen_retrieval")
    steps.append("replay_memory_deletion_tombstones_before_reopen_retrieval")


NEGATIVE_PROFILES = [
    ("public network dependency", _set("images.publicNetworkDependencyAtRuntime", True), "public-network runtime dependency"),
    ("public egress allowed", _set("isolation.egressPublicNetwork", True), "public egress must be denied"),
    ("no egress probes", _set("isolation.egressDenyProbes", []), "egress deny probes required"),
    ("public allowed flow", _set("isolation.allowedFlows.0", {"host": "registry.npmjs.org", "port": 443}), "allowed flow must be intra-site"),
    ("empty allowed flows", _set("isolation.allowedFlows", []), "allowedFlows must be non-empty"),
    ("image pin by tag", _set("images.pins.ops", "python:3.11"), "image pin ops must be digest-pinned"),
    ("image pin with uppercase digest", _set("images.pins.ops", "python@sha256:" + "A" * 64),
     "image pin ops must be digest-pinned"),
    ("image pin with short digest", _set("images.pins.kafka", "confluentinc/cp-kafka@sha256:" + "a" * 63),
     "image pin kafka must be digest-pinned"),
    ("image pin with digest and suffix", _set("images.pins.qdrant", "qdrant/qdrant@sha256:" + "a" * 64 + ":latest"),
     "image pin qdrant must be digest-pinned"),
    ("no image pins", _set("images.pins", {}), "image pins required"),
    ("namespace not per subsystem", _set("isolation.namespacePerSubsystem", False), "namespacePerSubsystem"),
    ("service account not per subsystem", _set("isolation.serviceAccountPerSubsystem", False), "serviceAccountPerSubsystem"),
    ("one synthetic compartment", _set("isolation.syntheticCompartmentsMin", 1), "two synthetic compartments"),
    ("exporters not local", _set("observability.exportersLocal", False), "exporters must stay local"),
    ("drift scan 0", _set("observability.driftScanIntervalSeconds", 0), "drift scan interval"),
    ("drift scan negative", _set("observability.driftScanIntervalSeconds", -1), "drift scan interval"),
    ("drift scan 61", _set("observability.driftScanIntervalSeconds", 61), "drift scan interval"),
    ("probe interval 61", _set("observability.probeIntervalSeconds", 61), "probe interval"),
    ("metric set incomplete", _set("observability.metrics.set", ["audit_gap"]), "metric set incomplete"),
    ("trace fields incomplete", _set("observability.traces.fields", ["trace_id"]), "trace fields incomplete"),
    ("classified payload logged", _set("observability.logs.excludeClassifiedPayload", False), "classified payload"),
    ("RPO 16", _set("backup.rpoMinutes", 16), "RPO must be in [1, 15]"),
    ("RPO negative", _set("backup.rpoMinutes", -1), "RPO must be in [1, 15]"),
    ("RTO 5", _set("backup.rtoHours", 5), "RTO must be in [1, 4]"),
    ("RTO negative", _set("backup.rtoHours", -1), "RTO must be in [1, 4]"),
    ("backup unencrypted", _set("backup.encrypted", False), "backup.encrypted"),
    ("backup unsigned", _set("backup.signed", False), "backup.signed"),
    ("restore untested", _set("backup.tested", False), "backup.tested"),
    ("same key for encryption and signature", _set("backup.keys.signing", "ocor-poc-backup-enc"), "separate encryption and signing keys"),
    ("authority class missing", _set("backup.authorityClasses", ["canonical"]), "authority classes incomplete"),
    ("memory deletion epochs unbound", _set("backup.memory.deletionEpochs", False), "memory manifest field deletionEpochs"),
    ("tombstone replay out of order", _reorder_tombstone, "restore steps incomplete or out of order"),
    ("replay pins empty", _set("restore.replay.pins", []), "replay pins incomplete"),
    ("recovery gate incomplete", _set("restore.recoveryGate", RECOVERY_GATE[:-1]), "recovery gate incomplete"),
    ("restore not isolated", _set("restore.isolatedNetwork", False), "isolated network"),
    ("resource limit zero", _set("resourceLimits.topK", 0), "resource limit topK"),
    ("semantic downgrade", _set("resourceLimits.quotaBehavior.semanticDowngrade", True), "semantic downgrade"),
    ("emergency stop fault missing", lambda p: p["safeDegraded"].__setitem__("faults", p["safeDegraded"]["faults"][:-1]), "safe-degraded fault table incomplete"),
    ("health dependencies empty", _set("health.dependencies", []), "health.dependencies must be non-empty"),
    ("mandatory dependency missing", _drop_dependency("spire-server"), "cover every mandatory foundation service"),
    ("dependency not mandatory", _set("health.dependencies.0.mandatory", False), "must be mandatory"),
    ("dependency without probe", _set("health.dependencies.0.probe", {}), "health probe missing"),
    ("dependency outside allowlist", _set("health.dependencies.0.port", 7000), "not in allowedFlows"),
]


@pytest.mark.parametrize("description,mutate,expected", NEGATIVE_PROFILES, ids=[c[0] for c in NEGATIVE_PROFILES])
def test_invalid_profile_blocks_startup(agent_dir, description, mutate, expected):
    profile = deepcopy(helm_profile())
    mutate(profile)
    result = run_agent(agent_dir, "validate", profile=profile)
    assert result.returncode == EXIT_CONFIG, (description, result.stdout, result.stderr)
    errors = json.loads(result.stderr)["errors"]
    assert any(expected in e for e in errors), (description, errors)


@pytest.mark.parametrize("path,value", [
    ("backup.rpoMinutes", 15), ("backup.rpoMinutes", 1), ("backup.rtoHours", 4),
    ("observability.driftScanIntervalSeconds", 60), ("observability.driftScanIntervalSeconds", 1),
])
def test_boundary_values_are_accepted(agent_dir, path, value):
    profile = deepcopy(helm_profile())
    _set(path, value)(profile)
    assert run_agent(agent_dir, "validate", profile=profile).returncode == 0


HOST_ALIASES = [{"ip": f"172.30.0.{n + 2}", "hostnames": [name]} for n, name in enumerate(BOOTSTRAP_SERVICES)]


def helm_template(*sets: str, expect_ok: bool = True, host_aliases: list[dict] | None = None) -> list[dict]:
    values = Path(os.environ.get("TMPDIR", "/tmp")) / f"ocor-0049-values-{uuid.uuid4().hex}.yaml"
    values.write_text(yaml.safe_dump({"operational": {
        "hostAliases": HOST_ALIASES if host_aliases is None else host_aliases}}), encoding="utf-8")
    args = [tool("helm"), "template", "ocor-poc", str(CHART_DIR), "-f", str(values),
            "--set", "operational.secretName=ocor-poc-ops", "--set", "operational.vault.existingClaim=ocor-poc-vault",
            "--set", "operational.restoreDrill.enabled=true"]
    for item in sets:
        args += ["--set", item]
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
    finally:
        values.unlink()
    if not expect_ok:
        return [{"returncode": result.returncode, "stderr": result.stderr}]
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def test_helm_chart_renders_operational_workloads():
    docs = {(d["kind"], d["metadata"]["name"]): d for d in helm_template()}
    deployment = docs[("Deployment", "ocor-poc-ops")]["spec"]["template"]["spec"]
    container = deployment["containers"][0]
    assert container["image"] == OPS_IMAGE
    assert container["command"][:3] == ["python3", "/opt/ocor/ocor_ops_agent.py", "serve"]
    assert container["readinessProbe"]["httpGet"] == {"path": "/readyz", "port": "http"}
    assert container["livenessProbe"]["httpGet"] == {"path": "/livez", "port": "http"}
    assert container["ports"] == [{"name": "http", "containerPort": 8080}]
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert deployment["automountServiceAccountToken"] is False
    service = docs[("Service", "ocor-poc-ops")]["spec"]
    assert service["ports"][0]["targetPort"] == "http"
    vault = next(v for v in deployment["volumes"] if v["name"] == "vault")
    assert vault["persistentVolumeClaim"]["claimName"] == "ocor-poc-vault"
    cron = docs[("CronJob", "ocor-poc-backup")]["spec"]
    assert cron["schedule"] == "*/15 * * * *", "RPO <= 15 min requires a 15-minute cadence"
    pod = cron["jobTemplate"]["spec"]["template"]["spec"]
    assert [c["name"] for c in pod["initContainers"]] == ["capture-postgresql", "capture-kafka"]
    assert "seal" in pod["containers"][0]["command"][2]
    assert all(v.get("emptyDir") is None or v["name"] != "vault" for v in pod["volumes"])
    deny = docs[("NetworkPolicy", "ocor-poc-default-deny")]["spec"]
    assert deny == {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}
    allow = docs[("NetworkPolicy", "ocor-poc-intra-site")]["spec"]
    # Exactly one (address, port) pair per allowed flow: no address is admitted on the
    # port of another destination (verdict OCOR-DEV-0049-7fd4f7728801-2 VF-002).
    address = {name: alias["ip"] for alias in HOST_ALIASES for name in alias["hostnames"]}
    pairs = [(rule["to"][0]["ipBlock"]["cidr"], p["port"]) for rule in allow["egress"][1:] for p in rule["ports"]]
    assert all(len(rule["to"]) == 1 and len(rule["ports"]) == 1 for rule in allow["egress"][1:])
    assert sorted(pairs) == sorted((f"{address[f['host']]}/32", f["port"])
                                   for f in helm_profile()["isolation"]["allowedFlows"])
    drill = docs[("Job", "ocor-poc-restore-drill-1")]["spec"]["template"]["spec"]
    assert [c["name"] for c in drill["initContainers"]] == [
        "restore-prepare", "restore-postgresql", "restore-qdrant", "restore-load-postgresql"]
    assert "--recovery-point" not in drill["initContainers"][0]["command"], "default: latest recovery point"
    pinned = {(d["kind"], d["metadata"]["name"]): d for d in helm_template(
        "operational.restoreDrill.recoveryPoint=rp-20261005T194504Z-35d8c606")}
    command = pinned[("Job", "ocor-poc-restore-drill-1")]["spec"]["template"]["spec"]["initContainers"][0]["command"]
    assert command[-2:] == ["--recovery-point", "rp-20261005T194504Z-35d8c606"], "drill bound to one recovery point"


@pytest.mark.parametrize("missing", ["operational.secretName=", "operational.vault.existingClaim="])
def test_helm_chart_refuses_to_render_without_secret_or_external_vault(missing):
    result = helm_template(missing, expect_ok=False)[0]
    assert result["returncode"] != 0
    assert "required" in result["stderr"]


def test_helm_chart_refuses_to_render_a_flow_without_a_pinned_address():
    partial = [alias for alias in HOST_ALIASES if alias["hostnames"] != ["qdrant"]]
    result = helm_template(expect_ok=False, host_aliases=partial)[0]
    assert result["returncode"] != 0
    assert "no intra-site address for allowed flow qdrant:6333" in result["stderr"]


# Verdict OCOR-DEV-0049-aefabf91777d-4 VF-001: the executed artifact of every workload is
# the governed pin of its role, so the release binding covers what actually runs.
HELM_IMAGE_ROLES = {
    "ops": "ops", "seal": "ops", "restore-prepare": "ops", "restore-finalize": "ops",
    "capture-postgresql": "postgresql", "restore-postgresql": "postgresql", "restore-load-postgresql": "postgresql",
    "capture-kafka": "kafka", "restore-qdrant": "qdrant",
}


def workload_images(docs: list[dict]) -> dict[tuple[str, str], str]:
    pod_specs = {"Deployment": lambda d: d["spec"]["template"]["spec"], "Job": lambda d: d["spec"]["template"]["spec"],
                 "CronJob": lambda d: d["spec"]["jobTemplate"]["spec"]["template"]["spec"]}
    out = {}
    for doc in docs:
        if doc["kind"] in pod_specs:
            pod = pod_specs[doc["kind"]](doc)
            for container in pod.get("initContainers", []) + pod["containers"]:
                out[(doc["kind"], container["name"])] = container["image"]
    return out


@pytest.mark.parametrize("override", [None, ("ops", OTHER_OPS_IMAGE),
                                      ("postgresql", "postgres@sha256:" + "1" * 64)], ids=["governed", "ops", "pg"])
def test_helm_workload_images_are_exactly_the_governed_pins(override):
    pins = dict(helm_profile()["images"]["pins"])
    sets = ()
    if override is not None:
        pins[override[0]] = override[1]
        sets = (f"ocor.images.pins.{override[0]}={override[1]}",)
    docs = helm_template(*sets)
    images = workload_images(docs)
    assert sorted(name for _, name in images) == sorted(HELM_IMAGE_ROLES), images
    for (kind, name), image in images.items():
        assert image == pins[HELM_IMAGE_ROLES[name]], (kind, name, image)
    configmap = next(d for d in docs if d["kind"] == "ConfigMap")
    assert json.loads(configmap["data"]["profile.json"])["images"]["pins"] == pins, "binding covers the executed images"


IMAGE_REFUSALS = [
    ("operational.image=python:3.11", "operational.image is not accepted"),
    (f"operational.image={OTHER_OPS_IMAGE}", "operational.image is not accepted"),
    (f"operational.image={OPS_IMAGE}", "operational.image is not accepted"),
    ("operational.postgresImage=postgres:latest", "operational.postgresImage is not accepted"),
    ("operational.kafkaImage=confluentinc/cp-kafka:latest", "operational.kafkaImage is not accepted"),
    ("operational.qdrantImage=qdrant/qdrant:latest", "operational.qdrantImage is not accepted"),
    ("ocor.images.pins.ops=python:3.11", "ocor.images.pins.ops must be digest-pinned"),
    ("ocor.images.pins.postgresql=postgres:latest", "ocor.images.pins.postgresql must be digest-pinned"),
    ("ocor.images.pins.kafka=confluentinc/cp-kafka:latest", "ocor.images.pins.kafka must be digest-pinned"),
    ("ocor.images.pins.qdrant=qdrant/qdrant:latest", "ocor.images.pins.qdrant must be digest-pinned"),
    ("ocor.images.pins.ops=python@sha256:" + "A" * 64, "ocor.images.pins.ops must be digest-pinned"),
    ("ocor.images.pins.extra=busybox:1", "ocor.images.pins.extra must be digest-pinned"),
]


@pytest.mark.parametrize("setting,message", IMAGE_REFUSALS, ids=[s for s, _ in IMAGE_REFUSALS])
def test_helm_refuses_images_outside_the_digest_pins(setting, message):
    result = helm_template(setting, expect_ok=False)[0]
    assert result["returncode"] != 0
    assert message in result["stderr"], result["stderr"]


def compose_image_role(service: str) -> str:
    for role in ("postgresql", "kafka", "qdrant"):
        if service.startswith(("ocor-backup-capture-", "ocor-restore-")) and role in service:
            return role
    return "ops"


def test_compose_workload_images_are_exactly_the_governed_pins():
    pins = compose_profile()["images"]["pins"]
    services = overlay()["services"]
    assert {compose_image_role(name) for name in services} == set(pins)
    for name, service in services.items():
        assert service["image"] == pins[compose_image_role(name)], (name, service["image"])


# --------------------------------------------------------------------------- decision logic


@pytest.fixture(scope="session")
def agent_module(agent_dir):
    import importlib.util

    spec = importlib.util.spec_from_file_location("ocor_ops_agent_under_test", agent_dir / "ocor_ops_agent.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def _healthy_state(agent):
    profile = helm_profile()
    state = agent.State(profile, "digest", Path("/nonexistent"), None, agent.Telemetry("r", "digest"))
    state.dep_up = {d["name"]: True for d in profile["health"]["dependencies"]}
    state.restore_reason, state.receipt_digest = "RESTORE_TESTED", "r1"
    state.reopen = {"receipt_digest": "r1", "authorized_by": "operator"}
    state.last_scan, state.ready, state.ready_reasons = agent.now(), True, ["READY"]
    return state


def test_admission_branches_of_the_posture(agent_module):
    """Every fail-closed condition of the ops plane, with its positive counterpart
    (the same branches are exercised on the live stack below)."""
    agent = agent_module
    state = _healthy_state(agent)
    assert state.faults() == [] and state.posture()["admitted_operation_classes"] == sorted(OPERATION_CLASSES)
    assert state.readiness() == (True, ["READY"])
    cases = {
        "security_scan_unavailable": lambda s: setattr(s, "scanner_error", "ValueError"),
        "restore_not_verified": lambda s: setattr(s, "restore_reason", "RESTORE_UNTESTED"),
        "isolation_breach": lambda s: setattr(s, "egress_violations", ["1.1.1.1:443"]),
    }
    for fault, mutate in cases.items():
        st = _healthy_state(agent)
        mutate(st)
        assert fault in st.faults(), fault
        assert st.posture()["admitted_operation_classes"] == [], fault
    st = _healthy_state(agent)
    st.reopen = {"receipt_digest": "older-receipt", "authorized_by": "operator"}
    assert st.faults() == ["recovery_reopen_pending"]
    assert st.posture()["admitted_operation_classes"] == ["exact_consistency_read", "read"]
    st = _healthy_state(agent)
    st.last_scan = agent.now() - st.max_scan_age - 1  # scanner thread stuck
    assert st.readiness() == (False, ["SCAN_STALE"])
    assert st.faults() == ["security_scan_unavailable"]
    st = _healthy_state(agent)
    st.last_scan = 0.0  # never scanned
    assert "security_scan_unavailable" in st.faults()


def test_relay_serves_exactly_one_declared_flow(agent_module):
    profile = helm_profile()
    assert agent_module.relay_flow(profile, "opa") == {"host": "opa", "port": 8181}
    for bad in ("", "unknown", "opa:8181"):
        with pytest.raises(agent_module.ConfigError):
            agent_module.relay_flow(profile, bad)


def _drill_digest(*parts: str) -> str:
    return "urn:sha256:" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


@pytest.mark.parametrize("field,value,gate,detail", [
    ("tenant_id", "tenant-b", "gcs", "tenant_mismatch"),
    ("compartments", ["c2"], "gcs", "compartment_mismatch"),
    ("compartments", ["c1", "c1"], "gcs", "compartment_mismatch"),
    ("compartments", "c1", "gcs", "compartment_mismatch"),
    ("classification_marking_ref", "SYNTHETIC-UNCLASSIFIED", "marking", "marking_mismatch"),
    ("governed_context_digest", None, "gcs", "gcs_digest_mismatch"),
    ("lifecycle_epoch", 4, "projection_drift_or_stale_deletion_epoch", "version_drift"),
])
def test_scope_comparison_branches(agent_module, field, value, gate, detail):
    meta = {"item_id": "m1", "tenant_id": "tenant-a", "compartments": '["c1"]',
            "classification_marking_ref": _drill_digest("marking", "SYNTHETIC-UNCLASSIFIED"),
            "governed_context_digest": _drill_digest("gcs", "tenant-a", "c1"),
            "representation_version": "2", "lifecycle_epoch": "3"}
    payload = {"item_id": "m1", "tenant_id": "tenant-a", "compartments": ["c1"],
               "classification_marking_ref": meta["classification_marking_ref"],
               "governed_context_digest": meta["governed_context_digest"],
               "representation_version": 2, "lifecycle_epoch": 3}
    assert not any(agent_module.scope_violations(payload, meta).values()), "consistent item passes"
    tampered = dict(payload, **{field: value})
    found = {k for k, v in agent_module.scope_violations(tampered, meta).items() if v}
    expected = {"tenant_mismatch": "tenant", "compartment_mismatch": "compartments", "marking_mismatch": "marking",
                "gcs_digest_mismatch": "gcs", "version_drift": "version"}[detail]
    assert found == {expected}
    # Equal but malformed authoritative values are not a binding: the contract digest is required.
    bad = "gcd-tenant-a-c1"
    assert agent_module.scope_violations(dict(payload, governed_context_digest=bad),
                                         dict(meta, governed_context_digest=bad))["gcs"]
    assert agent_module.scope_violations(dict(payload, classification_marking_ref="SYNTHETIC"),
                                         dict(meta, classification_marking_ref="SYNTHETIC"))["marking"]


def canonical_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def profile_digest(profile: dict) -> str:
    return hashlib.sha256(canonical_bytes(profile)).hexdigest()


def iso_utc(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def coherent_gate() -> dict:
    """Recovery gate of a PASSED drill with a memory store, with the typed details
    restore-finalize writes (counts and watermarks are legitimately non-empty)."""
    return {
        "revision": {"pass": True, "detail": []},
        "watermark": {"pass": True, "detail": {"index_items": 3, "live_metadata_items": 3}},
        "orphan_duplicate": {"pass": True, "detail": {"orphans": [], "dupes": []}},
        "marking": {"pass": True, "detail": {"marking_mismatch": []}},
        "gcs": {"pass": True, "detail": {"tenant_mismatch": [], "compartment_mismatch": [], "gcs_digest_mismatch": []}},
        "deletion_resurrection": {"pass": True, "detail": []},
        "projection_drift_or_stale_deletion_epoch": {
            "pass": True, "detail": {"journal_max": 7, "metadata_max": 7, "missing_live": [], "version_drift": []}},
        "sample_semantic_digest": {"pass": True, "detail": []},
    }


SEALED_STORE_DIGESTS = {"ocor": "d" * 64, "ocor_poc_drill": "e" * 64}


def coherent_receipt(profile: dict) -> dict:
    """The shape restore-finalize writes for a PASSED drill (oracle independent of the agent)."""
    completed = float(int(time.time()) - 60)
    statuses = {0: "EXECUTED", 1: "EXECUTED", 2: "EXECUTED", 3: "EXECUTED", 4: "EXECUTED", 5: "EXECUTED",
                6: "NOT_EXECUTED", 7: "EXECUTED", 8: "NOT_APPLICABLE", 9: "NOT_EXECUTED",
                10: "PENDING_HUMAN_AUTHORIZATION"}
    return {
        "schema": "ocor.poc.restore-receipt/3", "recovery_point": "rp-20261005T000000Z-00000000",
        "manifest_digest": "a" * 64, "outcome": "PASSED",
        "release_binding": {"release": profile["profile"]["release"], "profile_digest": profile_digest(profile),
                            "image_pins_digest": hashlib.sha256(canonical_bytes(profile["images"]["pins"])).hexdigest()},
        "recovery_gate": coherent_gate(),
        "steps": [{"step": s, "status": statuses[i], "detail": ""} for i, s in enumerate(profile["restore"]["steps"])],
        "replayed_event_ids": ["evt-del-m2", "evt-del-m4"], "replay_digest": "b" * 64, "quarantined_items": [],
        "restored_scope_digest": "c" * 64, "restored_store_digests": dict(SEALED_STORE_DIGESTS),
        "retrieval_reopened": False, "materialisation": "ALLOWED_PENDING_HUMAN", "isolated_network": True,
        "completed_at": iso_utc(completed), "completed_at_epoch": completed, "duration_seconds": 1.0,
        "rto_hours_target": 4, "correlation_id": "c",
    }


def _gate_fails(name: str, detail=None):
    def mutate(receipt: dict) -> None:
        receipt["recovery_gate"][name]["pass"] = False
        if detail is not None:
            receipt["recovery_gate"][name]["detail"] = detail
    return mutate


def _gate_detail(name: str, detail):
    """The check still claims pass=true, but its detail reports a violation (VF-002)."""
    def mutate(receipt: dict) -> None:
        receipt["recovery_gate"][name]["detail"] = detail
    return mutate


def _detail_key(name: str, key: str, value):
    def mutate(receipt: dict) -> None:
        receipt["recovery_gate"][name]["detail"][key] = value
    return mutate


def _step_status(index: int, status: str):
    def mutate(receipt: dict) -> None:
        receipt["steps"][index]["status"] = status
    return mutate


VERIFIER_GCS_DETAIL = {"tenant_mismatch": ["m1"], "compartment_mismatch": [], "gcs_digest_mismatch": []}
# Verdict OCOR-DEV-0049-02ac643eb3c7-3 VF-002: receipts signed by the real custodian
# that nevertheless report a failed, missing or malformed check, or an incoherent state.
RECEIPT_MUTATIONS = [
    *[(f"gate_{name}_false", _gate_fails(name), f"gate:{name}") for name in RECOVERY_GATE],
    ("verifier_gcs_tenant_mismatch", _gate_fails("gcs", VERIFIER_GCS_DETAIL), "gate:gcs"),
    ("gate_missing", lambda r: r["recovery_gate"].pop("marking"), "gate:marking"),
    ("gate_pass_string", _set("recovery_gate.revision.pass", "true"), "gate:revision"),
    ("gate_pass_one", _set("recovery_gate.watermark.pass", 1), "gate:watermark"),
    ("gate_entry_not_object", _set("recovery_gate.orphan_duplicate", True), "gate:orphan_duplicate"),
    ("gate_unexpected", _set("recovery_gate.extra", {"pass": True}), "gate:extra:unexpected"),
    ("gate_not_object", _set("recovery_gate", []), "recovery_gate"),
    ("human_step_blocked", _step_status(10, "BLOCKED"), "step:require_human_authorization_to_reopen_mutative"),
    ("canonical_restore_failed", _step_status(4, "FAILED"),
     "step:restore_canonical_event_action_audit_same_cut"),
    ("signature_check_not_executed", _step_status(2, "NOT_EXECUTED"),
     "step:verify_trust_manifest_digest_signatures_dual_control"),
    ("optional_step_failed", _step_status(6, "FAILED"), "step:rebuild_logic_projection_and_w3c_boundary"),
    ("steps_reordered", lambda r: r["steps"].reverse(), "steps"),
    ("quarantined_items", _set("quarantined_items", ["m1"]), "quarantined_items"),
    ("materialisation_blocked", _set("materialisation", "BLOCKED"), "materialisation"),
    ("retrieval_already_reopened", _set("retrieval_reopened", True), "retrieval_reopened"),
    ("not_isolated", _set("isolated_network", False), "isolated_network"),
    ("schema_v1", _set("schema", "ocor.poc.restore-receipt/1"), "schema"),
    ("schema_v2_without_bindings", _set("schema", "ocor.poc.restore-receipt/2"), "schema"),
    ("outcome_missing", lambda r: r.pop("outcome"), "outcome"),
    ("future_dated", _set("completed_at_epoch", 4102444800.0), "completed_at_epoch"),
    ("epoch_not_number", _set("completed_at_epoch", True), "completed_at_epoch"),
    ("manifest_digest_malformed", _set("manifest_digest", "abc"), "manifest_digest"),
    # Verdict OCOR-DEV-0049-aefabf91777d-4 VF-002: pass=true contradicted by its typed detail.
    ("gcs_pass_with_tenant_mismatch", _detail_key("gcs", "tenant_mismatch", ["m1"]), "gate:gcs:detail"),
    ("gcs_pass_with_compartment_mismatch", _detail_key("gcs", "compartment_mismatch", ["m3"]), "gate:gcs:detail"),
    ("gcs_pass_with_gcs_digest_mismatch", _detail_key("gcs", "gcs_digest_mismatch", ["m5"]), "gate:gcs:detail"),
    ("gcs_detail_key_missing", lambda r: r["recovery_gate"]["gcs"]["detail"].pop("tenant_mismatch"),
     "gate:gcs:detail"),
    ("gcs_detail_key_unexpected", _detail_key("gcs", "tenant_override", []), "gate:gcs:detail"),
    ("gcs_detail_not_object", _gate_detail("gcs", "ok"), "gate:gcs:detail"),
    ("gcs_detail_list_not_list", _detail_key("gcs", "tenant_mismatch", "m1"), "gate:gcs:detail"),
    ("marking_pass_with_mismatch", _detail_key("marking", "marking_mismatch", ["m1"]), "gate:marking:detail"),
    ("orphan_pass_with_orphan", _detail_key("orphan_duplicate", "orphans", ["m9"]), "gate:orphan_duplicate:detail"),
    ("orphan_pass_with_duplicate", _detail_key("orphan_duplicate", "dupes", ["m1"]), "gate:orphan_duplicate:detail"),
    ("resurrection_pass_with_item", _gate_detail("deletion_resurrection", ["m2"]),
     "gate:deletion_resurrection:detail"),
    ("drift_pass_with_missing_live", _detail_key("projection_drift_or_stale_deletion_epoch", "missing_live", ["m1"]),
     "gate:projection_drift_or_stale_deletion_epoch:detail"),
    ("drift_pass_with_version_drift", _detail_key("projection_drift_or_stale_deletion_epoch", "version_drift",
                                                  ["m1"]), "gate:projection_drift_or_stale_deletion_epoch:detail"),
    ("drift_pass_with_stale_epoch", _detail_key("projection_drift_or_stale_deletion_epoch", "journal_max", 6),
     "gate:projection_drift_or_stale_deletion_epoch:detail"),
    ("drift_pass_with_boolean_epoch", _detail_key("projection_drift_or_stale_deletion_epoch", "metadata_max", True),
     "gate:projection_drift_or_stale_deletion_epoch:detail"),
    ("watermark_pass_with_count_difference", _detail_key("watermark", "index_items", 2), "gate:watermark:detail"),
    ("watermark_pass_with_negative_count", _gate_detail("watermark", {"index_items": -1, "live_metadata_items": -1}),
     "gate:watermark:detail"),
    ("watermark_pass_with_float_count", _gate_detail("watermark", {"index_items": 3.0, "live_metadata_items": 3.0}),
     "gate:watermark:detail"),
    ("revision_pass_with_row_count_difference", _gate_detail("revision", ["ocor:row_counts_differ"]),
     "gate:revision:detail"),
    ("semantic_digest_pass_with_difference", _gate_detail("sample_semantic_digest", ["ocor:semantic_digest_differs"]),
     "gate:sample_semantic_digest:detail"),
    ("gate_entry_extra_field", _set("recovery_gate.marking.override", True), "gate:marking:detail"),
    ("memory_gate_claims_no_store", _gate_detail("gcs", "no memory store present"), "gate:gcs:detail"),
    ("memory_step_not_executed", _step_status(5, "NOT_EXECUTED"),
     "step:replay_memory_deletion_tombstones_before_reopen_retrieval"),
    ("replay_digest_malformed", _set("replay_digest", "xyz"), "replay_digest"),
    # Cycle 8 receipt-field audit: the bindings to the recovery point must be well formed.
    ("restored_scope_digest_missing", lambda r: r.pop("restored_scope_digest"), "restored_scope_digest"),
    ("restored_scope_digest_malformed", _set("restored_scope_digest", "C" * 64), "restored_scope_digest"),
    ("store_digests_missing", lambda r: r.pop("restored_store_digests"), "restored_store_digests"),
    ("store_digests_empty", _set("restored_store_digests", {}), "restored_store_digests"),
    ("store_digests_not_object", _set("restored_store_digests", ["d" * 64]), "restored_store_digests"),
    ("store_digest_malformed", _set("restored_store_digests.ocor", "d" * 63), "restored_store_digests"),
    ("replayed_ids_not_strings", _set("replayed_event_ids", [1, 2]), "replayed_event_ids"),
    # Verdict OCOR-DEV-0049-aefabf91777d-4 VF-003 (values representable in strict JSON).
    ("epoch_zero", _set("completed_at_epoch", 0), "completed_at_epoch"),
    ("epoch_negative", _set("completed_at_epoch", -60.0), "completed_at_epoch"),
    ("completed_at_incoherent", _set("completed_at", "2026-01-01T00:00:00Z"), "completed_at"),
    ("duration_negative", _set("duration_seconds", -1.0), "duration_seconds"),
]


@pytest.mark.parametrize("case,mutate,expected", RECEIPT_MUTATIONS, ids=[c[0] for c in RECEIPT_MUTATIONS])
def test_receipt_coherence_branches(agent_module, case, mutate, expected):
    profile = helm_profile()
    receipt = coherent_receipt(profile)
    assert agent_module.receipt_inconsistencies(receipt, profile) == [], "coherent PASSED receipt"
    mutate(receipt)
    assert expected in agent_module.receipt_inconsistencies(receipt, profile), case


RECEIPT_POSITIVE_VARIANTS = [
    ("authentic_counts", lambda r: None),
    ("other_consistent_watermark", _gate_detail("watermark", {"index_items": 7, "live_metadata_items": 7})),
    ("journal_ahead_of_metadata", _detail_key("projection_drift_or_stale_deletion_epoch", "journal_max", 9)),
    ("integral_epoch", lambda r: r.__setitem__("completed_at_epoch", int(r["completed_at_epoch"]))),
]


@pytest.mark.parametrize("case,mutate", RECEIPT_POSITIVE_VARIANTS, ids=[c[0] for c in RECEIPT_POSITIVE_VARIANTS])
def test_coherent_receipt_variants_are_accepted(agent_module, case, mutate):
    """Positive side of VF-002/VF-003: legitimately non-empty details are not rejected."""
    receipt = coherent_receipt(helm_profile())
    mutate(receipt)
    assert agent_module.receipt_inconsistencies(receipt, helm_profile()) == [], case


def test_receipt_without_memory_store_is_coherent_only_as_a_whole(agent_module):
    profile = helm_profile()
    receipt = coherent_receipt(profile)
    for name in ("watermark", "orphan_duplicate", "marking", "gcs", "deletion_resurrection",
                 "projection_drift_or_stale_deletion_epoch"):
        receipt["recovery_gate"][name]["detail"] = "no memory store present"
    receipt["steps"][5]["status"] = "NOT_APPLICABLE"
    receipt.update(replayed_event_ids=[], replay_digest=None, restored_scope_digest=None)
    assert agent_module.receipt_inconsistencies(receipt, profile) == []
    mixed = deepcopy(receipt)
    mixed["recovery_gate"]["gcs"]["detail"] = coherent_gate()["gcs"]["detail"]
    assert agent_module.receipt_inconsistencies(mixed, profile) == ["gate:gcs:detail"]
    replayed = dict(receipt, replayed_event_ids=["evt-del-m2"], replay_digest="b" * 64,
                    restored_scope_digest="c" * 64)
    assert agent_module.receipt_inconsistencies(replayed, profile) == [
        "replayed_event_ids", "replay_digest", "restored_scope_digest"]
    unbound = dict(receipt, restored_store_digests={})
    assert agent_module.receipt_inconsistencies(unbound, profile) == ["restored_store_digests"]


@pytest.mark.parametrize("field,value,expected", [
    ("completed_at_epoch", float("nan"), "completed_at_epoch"),
    ("completed_at_epoch", float("inf"), "completed_at_epoch"),
    ("completed_at_epoch", float("-inf"), "completed_at_epoch"),
    ("completed_at_epoch", "1759700000", "completed_at_epoch"),
    ("completed_at_epoch", None, "completed_at_epoch"),
    ("duration_seconds", float("nan"), "duration_seconds"),
    ("duration_seconds", float("inf"), "duration_seconds"),
])
def test_non_finite_receipt_numbers_are_incoherent(agent_module, field, value, expected):
    receipt = coherent_receipt(helm_profile())
    receipt[field] = value
    assert expected in agent_module.receipt_inconsistencies(receipt, helm_profile())


@pytest.mark.parametrize("text", ['{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}', '{"a": 1e400}',
                                  '{"a": -1e999}'])
def test_strict_json_rejects_non_standard_numbers(agent_module, text):
    with pytest.raises(agent_module.NonStandardJSON):
        agent_module.strict_json(text)
    assert agent_module.strict_json('{"a": 1.5e3, "b": -2, "c": 0.0}') == {"a": 1500.0, "b": -2, "c": 0.0}
    with pytest.raises(ValueError):
        agent_module.canonical({"a": float("nan")})


@pytest.mark.parametrize("value", [[], "PASSED", None, 1])
def test_receipt_that_is_not_an_object_is_incoherent(agent_module, value):
    assert agent_module.receipt_inconsistencies(value, helm_profile()) == ["receipt:not_an_object"]


def _epochs(journal_max: int, metadata_max: int):
    def mutate(receipt: dict) -> None:
        detail = receipt["recovery_gate"]["projection_drift_or_stale_deletion_epoch"]["detail"]
        detail.update(journal_max=journal_max, metadata_max=metadata_max)
    return mutate


def sequence_digest(event_ids) -> str:
    """Oracle, independent of the agent: SHA-256 of the canonical JSON array of the ordered ids."""
    return hashlib.sha256(canonical_bytes(list(event_ids))).hexdigest()


def checkpoint_memory(ids=("evt-del-m2", "evt-del-m4"), max_epoch: int = 7, metadata_max: int = 7,
                      live_count: int = 3) -> dict:
    """The memory section the seal signs for the drill fixture (m2@6 and m4@7 tombstoned;
    m1/m3/m5 live, matching the opaque replay and scope digests of coherent_receipt)."""
    ids = list(ids)
    return {"status": "PRESENT",
            "journalCheckpoints": {"entries": len(ids), "max_deletion_epoch": max_epoch,
                                   "last_event_id": ids[-1] if ids else None,
                                   "event_ids_digest": sequence_digest(ids)},
            "deletionEpochs": {"journal_max": max_epoch, "metadata_max": metadata_max},
            "liveItems": {"count": live_count, "ids_digest": "b" * 64, "scope_digest": "c" * 64}}


# Not-executed check of verdict OCOR-DEV-0049-b40aa8a6908b-5: a signed receipt that is
# structurally coherent on its own but does not match the checkpoint of the recovery
# point it restored (tombstones not replayed, deletion epoch below/above the checkpoint).
CHECKPOINT_MUTATIONS = [
    ("tombstone_not_replayed", _set("replayed_event_ids", ["evt-del-m2"]), "memory:tombstones_not_replayed"),
    ("no_tombstone_replayed", _set("replayed_event_ids", []), "memory:tombstones_not_replayed"),
    ("last_tombstone_foreign", _set("replayed_event_ids", ["evt-del-m2", "evt-del-x9"]),
     "memory:tombstones_not_replayed"),
    ("tombstone_replayed_twice", _set("replayed_event_ids", ["evt-del-m4", "evt-del-m4"]),
     "memory:tombstones_not_replayed"),
    ("tombstone_not_in_checkpoint", _set("replayed_event_ids", ["evt-del-m2", "evt-del-m3", "evt-del-m4"]),
     "memory:tombstones_not_replayed"),
    # Verdict OCOR-DEV-0049-9d86abebc762-7 VF-001: the whole signed sequence, not its tail.
    ("nonfinal_tombstone_substituted", _set("replayed_event_ids", ["evt-del-FOREIGN", "evt-del-m4"]),
     "memory:tombstones_not_replayed"),
    ("tombstones_permuted", _set("replayed_event_ids", ["evt-del-m4", "evt-del-m2"]),
     "memory:tombstones_not_replayed"),
    ("tombstone_appended", _set("replayed_event_ids", ["evt-del-m2", "evt-del-m4", "evt-del-x9"]),
     "memory:tombstones_not_replayed"),
    ("tombstone_duplicated", _set("replayed_event_ids", ["evt-del-m2", "evt-del-m2", "evt-del-m4"]),
     "memory:tombstones_not_replayed"),
    # Cycle 8 receipt-field audit: the restored live set and its isolation scope are the sealed ones.
    ("replay_digest_not_sealed_live_set", _set("replay_digest", "f" * 64), "memory:live_items_mismatch"),
    ("watermark_not_sealed_live_count", _gate_detail("watermark", {"index_items": 4, "live_metadata_items": 4}),
     "memory:live_items_mismatch"),
    ("restored_scope_not_sealed_scope", _set("restored_scope_digest", "f" * 64), "memory:restored_scope_mismatch"),
    ("deletion_epoch_below_checkpoint", _epochs(6, 6), "memory:deletion_epoch_checkpoint_mismatch"),
    ("deletion_epoch_above_checkpoint", _epochs(9, 7), "memory:deletion_epoch_checkpoint_mismatch"),
    ("metadata_epoch_below_recovery_point", _epochs(7, 5), "memory:metadata_epoch_mismatch"),
]


def test_receipt_matching_its_checkpoint_is_coherent(agent_module):
    receipt = coherent_receipt(helm_profile())
    assert agent_module.receipt_checkpoint_inconsistencies(receipt, checkpoint_memory()) == []
    empty = deepcopy(receipt)
    empty["replayed_event_ids"] = []
    _epochs(0, 0)(empty)
    assert agent_module.receipt_inconsistencies(empty, helm_profile()) == []
    assert agent_module.receipt_checkpoint_inconsistencies(
        empty, checkpoint_memory(ids=(), max_epoch=0, metadata_max=0)) == [], "empty journal"


@pytest.mark.parametrize("journal_max,metadata_max", [(7, 7), (9, 7)])
def test_tied_epoch_checkpoint_uses_the_replay_order(agent_module, journal_max, metadata_max):
    """Seal and replay share one ordering even when the DB locale orders capitals
    differently. A missing/reordered tombstone stays fail-closed; journal ahead
    of metadata is valid when both belong to this signed recovery point."""
    rows = [{"event_id": "evt-del-a", "item_id": "m2", "deletion_epoch": str(journal_max)},
            {"event_id": "evt-del-B", "item_id": "m4", "deletion_epoch": str(journal_max)}]
    ordered = agent_module.ordered_deletion_journal(rows)
    ids = [r["event_id"] for r in ordered]
    assert ids == ["evt-del-B", "evt-del-a"]
    assert agent_module.ordered_deletion_journal(list(reversed(rows))) == ordered
    earlier = {"event_id": "z", "item_id": "m0", "deletion_epoch": "2"}
    assert agent_module.ordered_deletion_journal([*rows, earlier])[0] == earlier
    receipt = coherent_receipt(helm_profile())
    receipt["replayed_event_ids"] = ids
    _epochs(journal_max, metadata_max)(receipt)
    memory = checkpoint_memory(ids=ids, max_epoch=journal_max, metadata_max=metadata_max)
    assert agent_module.receipt_inconsistencies(receipt, helm_profile()) == []
    assert agent_module.receipt_checkpoint_inconsistencies(receipt, memory) == []
    for broken_ids in (ids[:-1], list(reversed(ids)), [ids[-1], ids[-1]]):
        broken = dict(receipt, replayed_event_ids=broken_ids)
        assert "memory:tombstones_not_replayed" in agent_module.receipt_checkpoint_inconsistencies(broken, memory)
    broken = deepcopy(receipt)
    _epochs(journal_max - 1, metadata_max)(broken)
    assert "memory:deletion_epoch_checkpoint_mismatch" in agent_module.receipt_checkpoint_inconsistencies(
        broken, memory)


@pytest.mark.parametrize("case,mutate,expected", CHECKPOINT_MUTATIONS, ids=[c[0] for c in CHECKPOINT_MUTATIONS])
def test_receipt_checkpoint_branches(agent_module, case, mutate, expected):
    profile = helm_profile()
    receipt = coherent_receipt(profile)
    mutate(receipt)
    assert agent_module.receipt_inconsistencies(receipt, profile) == [], "coherent on its own: only the checkpoint"
    assert expected in agent_module.receipt_checkpoint_inconsistencies(receipt, checkpoint_memory()), case


def _without(section: str, key: str) -> dict:
    memory = checkpoint_memory()
    memory[section].pop(key)
    return memory


@pytest.mark.parametrize("memory,expected", [
    ({"status": "PRESENT"}, ["memory:checkpoint_missing"]),
    (dict(checkpoint_memory(), journalCheckpoints=dict(checkpoint_memory()["journalCheckpoints"], entries=True)),
     ["memory:checkpoint_missing"]),
    (_without("journalCheckpoints", "event_ids_digest"), ["memory:checkpoint_missing"]),
    (dict(checkpoint_memory(), journalCheckpoints=dict(checkpoint_memory()["journalCheckpoints"],
                                                       event_ids_digest="X" * 64)), ["memory:checkpoint_missing"]),
    (_without("liveItems", "scope_digest"), ["memory:live_items_missing"]),
    (dict(checkpoint_memory(), liveItems=None), ["memory:live_items_missing"]),
    (dict(checkpoint_memory(), liveItems={"count": -1, "ids_digest": "b" * 64, "scope_digest": "c" * 64}),
     ["memory:live_items_missing"]),
    (checkpoint_memory(ids=(), max_epoch=0, metadata_max=0),
     ["memory:tombstones_not_replayed", "memory:deletion_epoch_checkpoint_mismatch",
      "memory:metadata_epoch_mismatch"]),
], ids=["checkpoint_absent", "entries_not_a_count", "sequence_digest_absent", "sequence_digest_malformed",
        "live_scope_digest_absent", "live_items_absent", "live_count_negative",
        "receipt_replays_beyond_an_empty_journal"])
def test_receipt_checkpoint_manifest_branches(agent_module, memory, expected):
    receipt = coherent_receipt(helm_profile())
    assert agent_module.receipt_checkpoint_inconsistencies(receipt, memory) == expected


# Verdict OCOR-DEV-0049-9d86abebc762-7 VF-001, class test: three tombstones at the SAME
# deletion epoch whose ids order differently under a locale collation (a < B < c) and under
# codepoints (B < a < c), so the locale permutation keeps the last id of the sealed sequence.
TIED_ROWS = [{"event_id": "evt-del-a", "item_id": "m2", "deletion_epoch": "7"},
             {"event_id": "evt-del-B", "item_id": "m4", "deletion_epoch": "7"},
             {"event_id": "evt-del-c", "item_id": "m5", "deletion_epoch": "7"}]
SEALED_TIED = ["evt-del-B", "evt-del-a", "evt-del-c"]
SEQUENCE_MUTATIONS = [
    ("permutation_keeping_last_id", ["evt-del-a", "evt-del-B", "evt-del-c"]),
    ("rotation", ["evt-del-c", "evt-del-B", "evt-del-a"]),
    ("nonfinal_substitution", ["evt-del-FOREIGN", "evt-del-a", "evt-del-c"]),
    ("middle_substitution", ["evt-del-B", "evt-del-A", "evt-del-c"]),
    ("omission", ["evt-del-B", "evt-del-c"]),
    ("omission_of_last", ["evt-del-B", "evt-del-a"]),
    ("addition", ["evt-del-B", "evt-del-a", "evt-del-x", "evt-del-c"]),
    ("addition_at_end", ["evt-del-B", "evt-del-a", "evt-del-c", "evt-del-d"]),
    ("duplication_same_length", ["evt-del-B", "evt-del-B", "evt-del-c"]),
    ("duplication_added", ["evt-del-B", "evt-del-a", "evt-del-a", "evt-del-c"]),
    ("empty", []),
]


def test_sealed_sequence_digest_is_the_whole_ordered_journal(agent_module):
    """The digest the seal signs is the one of the codepoint-ordered sequence (oracle
    independent of the agent), whatever order the rows were captured in."""
    for rows in (TIED_ROWS, list(reversed(TIED_ROWS)), [TIED_ROWS[1], TIED_ROWS[0], TIED_ROWS[2]]):
        ordered = [r["event_id"] for r in agent_module.ordered_deletion_journal(rows)]
        assert ordered == SEALED_TIED
        assert agent_module.event_ids_digest(ordered) == sequence_digest(SEALED_TIED)
    assert sorted(SEALED_TIED, key=str.lower) == ["evt-del-a", "evt-del-B", "evt-del-c"], "collations diverge"


def test_replayed_sequence_identical_to_the_sealed_one_is_accepted(agent_module):
    receipt = coherent_receipt(helm_profile())
    receipt["replayed_event_ids"] = list(SEALED_TIED)
    memory = checkpoint_memory(ids=SEALED_TIED)
    assert agent_module.receipt_inconsistencies(receipt, helm_profile()) == []
    assert agent_module.receipt_checkpoint_inconsistencies(receipt, memory) == []


@pytest.mark.parametrize("case,replayed", SEQUENCE_MUTATIONS, ids=[c[0] for c in SEQUENCE_MUTATIONS])
def test_replayed_sequence_differing_from_the_sealed_one_is_refused(agent_module, case, replayed):
    receipt = coherent_receipt(helm_profile())
    receipt["replayed_event_ids"] = replayed
    memory = checkpoint_memory(ids=SEALED_TIED)
    assert agent_module.receipt_inconsistencies(receipt, helm_profile()) == [], "coherent on its own"
    assert agent_module.receipt_checkpoint_inconsistencies(receipt, memory) == ["memory:tombstones_not_replayed"]


def test_tail_checks_alone_would_accept_the_verdict_counterexamples(agent_module):
    """Regression oracle for VF-001: these replays pass every pre-cycle-8 check (count,
    uniqueness, last id) and are refused only because of the signed sequence digest."""
    memory = checkpoint_memory(ids=SEALED_TIED)
    for replayed in (["evt-del-a", "evt-del-B", "evt-del-c"], ["evt-del-FOREIGN", "evt-del-a", "evt-del-c"]):
        assert len(replayed) == len(SEALED_TIED) == len(set(replayed)) and replayed[-1] == SEALED_TIED[-1]
        receipt = dict(coherent_receipt(helm_profile()), replayed_event_ids=replayed)
        assert agent_module.receipt_checkpoint_inconsistencies(receipt, memory) == ["memory:tombstones_not_replayed"]
    two = checkpoint_memory(ids=["evt-del-a", "evt-del-c"])
    receipt = dict(coherent_receipt(helm_profile()), replayed_event_ids=["evt-del-FOREIGN", "evt-del-c"])
    assert agent_module.receipt_checkpoint_inconsistencies(receipt, two) == ["memory:tombstones_not_replayed"]


def recovery_point_manifest(receipt: dict, **changes) -> dict:
    manifest = {"created_at_epoch": receipt["completed_at_epoch"] - 120, "store_digests": dict(SEALED_STORE_DIGESTS)}
    manifest.update(changes)
    return manifest


def test_receipt_bound_to_its_recovery_point_is_coherent(agent_module):
    receipt = coherent_receipt(helm_profile())
    assert agent_module.receipt_recovery_point_inconsistencies(receipt, recovery_point_manifest(receipt)) == []
    same_second = recovery_point_manifest(receipt, created_at_epoch=receipt["completed_at_epoch"])
    assert agent_module.receipt_recovery_point_inconsistencies(receipt, same_second) == []


RECOVERY_POINT_MUTATIONS = [
    ("restore_completed_before_seal", lambda r, m: m.update(created_at_epoch=r["completed_at_epoch"] + 1),
     "receipt:completed_before_recovery_point"),
    ("seal_time_missing", lambda r, m: m.pop("created_at_epoch"), "receipt:completed_before_recovery_point"),
    ("seal_time_not_number", lambda r, m: m.update(created_at_epoch="0"), "receipt:completed_before_recovery_point"),
    ("store_digest_differs", lambda r, m: r["restored_store_digests"].update(ocor="0" * 64),
     "receipt:store_digests_mismatch"),
    ("store_not_restored", lambda r, m: r["restored_store_digests"].pop("ocor_poc_drill"),
     "receipt:store_digests_mismatch"),
    ("store_not_sealed", lambda r, m: r["restored_store_digests"].update(extra="0" * 64),
     "receipt:store_digests_mismatch"),
    ("sealed_digests_missing", lambda r, m: m.pop("store_digests"), "receipt:store_digests_mismatch"),
    ("sealed_digests_empty", lambda r, m: m.update(store_digests={}), "receipt:store_digests_mismatch"),
    ("sealed_digest_malformed", lambda r, m: (m.update(store_digests={"ocor": "x"}),
                                             r.update(restored_store_digests={"ocor": "x"})),
     "receipt:store_digests_mismatch"),
]


@pytest.mark.parametrize("case,mutate,expected", RECOVERY_POINT_MUTATIONS,
                         ids=[c[0] for c in RECOVERY_POINT_MUTATIONS])
def test_receipt_unbound_from_its_recovery_point_is_incoherent(agent_module, case, mutate, expected):
    receipt = coherent_receipt(helm_profile())
    manifest = recovery_point_manifest(receipt)
    mutate(receipt, manifest)
    assert agent_module.receipt_recovery_point_inconsistencies(receipt, manifest) == [expected], case


INFORMATIONAL_FIELDS = [
    ("correlation_id", _set("correlation_id", "another-trace")),
    ("rto_hours_target", _set("rto_hours_target", 999)),
    ("duration_seconds", _set("duration_seconds", 12345.5)),
    ("step_detail", _set("steps.1.detail", "free text, not the recovery point")),
    ("release_binding_extra_key", _set("release_binding.note", "x")),
]


@pytest.mark.parametrize("case,mutate", INFORMATIONAL_FIELDS, ids=[c[0] for c in INFORMATIONAL_FIELDS])
def test_informational_receipt_fields_do_not_decide(agent_module, case, mutate):
    """Fields the audit declares not bound to the recovery point are not read by any
    decision: changing them leaves every coherence and binding verdict unchanged."""
    profile = helm_profile()
    receipt = coherent_receipt(profile)
    mutate(receipt)
    assert agent_module.receipt_inconsistencies(receipt, profile) == []
    assert agent_module.receipt_checkpoint_inconsistencies(receipt, checkpoint_memory()) == []
    assert agent_module.receipt_recovery_point_inconsistencies(receipt, recovery_point_manifest(receipt)) == []
    assert agent_module.binding_mismatch(receipt["release_binding"], profile, profile_digest(profile)) is None


# Verdict OCOR-DEV-0049-02ac643eb3c7-3 VF-001: a tested restore belongs to one release,
# profile digest and pin set; any other running configuration is not covered by it.
BINDING_MUTATIONS = [
    ("release", _set("profile.release", "ocor-poc-independent-unrestored-release"), "RELEASE_MISMATCH"),
    ("pins", _set("images.pins.ops", "python@sha256:" + "0" * 64), "PINS_MISMATCH"),
    ("profile", _set("observability.probeIntervalSeconds", 4), "PROFILE_MISMATCH"),
]


@pytest.mark.parametrize("case,mutate,expected", BINDING_MUTATIONS, ids=[c[0] for c in BINDING_MUTATIONS])
def test_release_binding_branches(agent_module, case, mutate, expected):
    profile = helm_profile()
    binding = agent_module.release_binding(profile, profile_digest(profile))
    assert binding == coherent_receipt(profile)["release_binding"], "independent oracle of the binding"
    assert agent_module.binding_mismatch(binding, profile, profile_digest(profile)) is None
    running = deepcopy(profile)
    mutate(running)
    assert agent_module.binding_mismatch(binding, running, profile_digest(running)) == expected
    for missing in (None, {}, {"release": binding["release"]}):
        assert agent_module.binding_mismatch(missing, profile, profile_digest(profile)) is not None


def policy_oracle(inventory: list[dict]) -> str:
    """Independent oracle of the policy digest: SHA-256 of the canonical sorted list of
    [policy id, SHA-256 of its raw source] over the COMPLETE inventory."""
    return hashlib.sha256(canonical_bytes(sorted(
        [p["id"], hashlib.sha256(p["raw"].encode()).hexdigest()] for p in inventory))).hexdigest()


EMPTY_SET_DIGEST = hashlib.sha256(b"[]").hexdigest()


class _InventoryServer:
    """Local HTTP endpoint serving a fixed OPA-like response: covers only the failure
    handling of the response parser (the real OPA is exercised on the live stack)."""

    def __init__(self, status: int, body: bytes, content_length: str | None = "auto") -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # noqa: D401
                return

            def do_GET(self):  # noqa: N802
                self.send_response(outer.status)
                if outer.content_length == "auto":
                    self.send_header("Content-Length", str(len(outer.body)))
                elif outer.content_length is not None:
                    self.send_header("Content-Length", outer.content_length)
                self.end_headers()
                self.wfile.write(outer.body)

        self.status, self.body, self.content_length = status, body, content_length
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _inventory(count: int, raw_size: int) -> list[dict]:
    return [{"id": f"pkg/p{n}.rego", "raw": f"package p{n}\n# " + "x" * raw_size} for n in range(count)]


def _opa_body(inventory) -> bytes:
    return json.dumps({"result": inventory}).encode()


POLICY_INVENTORY_CASES = [
    ("two_policies", 200, _opa_body(_inventory(2, 10)), "auto", "POLICY_DIGEST_OK"),
    ("above_4096_bytes", 200, _opa_body(_inventory(3, 20000)), "auto", "POLICY_DIGEST_OK"),
    ("empty_inventory", 200, _opa_body([]), "auto", "POLICY_DIGEST_OK"),
    ("chunked_no_length", 200, _opa_body(_inventory(2, 9000)), None, "POLICY_DIGEST_OK"),
    ("over_limit", 200, _opa_body(_inventory(2, 40000)), "auto", "POLICY_INVENTORY_TOO_LARGE"),
    ("over_limit_undeclared", 200, _opa_body(_inventory(2, 40000)), None, "POLICY_INVENTORY_TOO_LARGE"),
    ("truncated", 200, _opa_body(_inventory(2, 10))[:-5], "999", "POLICY_INVENTORY_TRUNCATED"),
    ("not_json", 200, b"<html>", "auto", "POLICY_INVENTORY_MALFORMED"),
    ("nan", 200, b'{"result": NaN}', "auto", "POLICY_INVENTORY_MALFORMED"),
    ("result_not_list", 200, b'{"result": {}}', "auto", "POLICY_INVENTORY_MALFORMED"),
    ("no_result", 200, b"{}", "auto", "POLICY_INVENTORY_MALFORMED"),
    ("entry_without_id", 200, _opa_body([{"raw": "package a"}]), "auto", "POLICY_INVENTORY_MALFORMED"),
    ("raw_not_string", 200, _opa_body([{"id": "a", "raw": 1}]), "auto", "POLICY_INVENTORY_MALFORMED"),
    ("duplicate_id", 200, _opa_body([{"id": "a", "raw": "x"}, {"id": "a", "raw": "y"}]), "auto",
     "POLICY_INVENTORY_MALFORMED"),
    ("server_error", 500, b"{}", "auto", "POLICY_INVENTORY_UNAVAILABLE"),
]
POLICY_TEST_LIMIT = 64 * 1024


@pytest.mark.parametrize("case,status,body,length,reason", POLICY_INVENTORY_CASES,
                         ids=[c[0] for c in POLICY_INVENTORY_CASES])
def test_policy_inventory_digest_branches(agent_module, case, status, body, length, reason):
    """Verdict OCOR-DEV-0049-aefabf91777d-4 VF-004: the digest covers the complete
    inventory or is not produced at all (never the digest of a truncated or empty set)."""
    server = _InventoryServer(status, body, length)
    try:
        digest, got = agent_module.policy_inventory_digest("127.0.0.1", server.port, 5.0, limit=POLICY_TEST_LIMIT)
    finally:
        server.close()
    assert got == reason, case
    if reason == "POLICY_DIGEST_OK":
        assert digest == policy_oracle(json.loads(body)["result"])
        assert (digest == EMPTY_SET_DIGEST) is (json.loads(body)["result"] == [])
    else:
        assert digest is None


def test_policy_inventory_digest_on_a_closed_port(agent_module):
    import socket as _socket

    with _socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert agent_module.policy_inventory_digest("127.0.0.1", port, 2.0) == (None, "POLICY_INVENTORY_UNAVAILABLE")
    assert agent_module.POLICY_INVENTORY_MAX_BYTES == 4 * 1024 * 1024


class _SnapshotServer:
    """Local Qdrant-like snapshot endpoint scripted per creation (failure handling of the
    seal's snapshot download only; the real Qdrant race is exercised on the live stack)."""

    def __init__(self, script: list[dict]) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading

        outer = self
        self.script, self.created, self.issued, self.deleted = list(script), 0, 0, []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _reply(self, code: int, body: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802
                step = outer.script[min(outer.created, len(outer.script) - 1)]
                outer.created += 1
                if "post_status" in step:  # creation failed: nothing to download or clean up
                    self._reply(step["post_status"], b'{"status":{"error":"failed to store snapshot archive"}}')
                    return
                outer.issued += 1
                result = {"name": "c-1-2026.snapshot"}
                if step.get("checksum", True):
                    result["checksum"] = hashlib.sha256(step["advertised"]).hexdigest()
                self._reply(200, json.dumps({"result": result}).encode())

            def do_GET(self):  # noqa: N802
                step = outer.script[min(outer.created - 1, len(outer.script) - 1)]
                self._reply(404, b"") if step.get("served") is None else self._reply(200, step["served"])

            def do_DELETE(self):  # noqa: N802
                outer.deleted.append(self.path)
                self._reply(404 if self.path in outer.deleted[:-1] else 200, b"{}")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


SNAPSHOT_CASES = [
    ("own_snapshot", [{"advertised": b"own", "served": b"own"}], b"own", None),
    ("deleted_by_concurrent_seal_then_own", [{"advertised": b"a", "served": None},
                                             {"advertised": b"own", "served": b"own"}], b"own", None),
    ("overwritten_by_concurrent_seal_then_own", [{"advertised": b"a", "served": b"other"},
                                                 {"advertised": b"own", "served": b"own"}], b"own", None),
    ("never_own", [{"advertised": b"a", "served": b"other"}], None, "INDEX_SNAPSHOT_UNSTABLE"),
    ("no_checksum", [{"advertised": b"a", "served": b"a", "checksum": False}], None, "INDEX_SNAPSHOT_UNSTABLE"),
    # Verdict OCOR-DEV-0049-b40aa8a6908b-5 VF-001: the concurrent seal makes the CREATION
    # fail with a 5xx on real Qdrant; retried within the bound, fail-closed once exhausted.
    ("creation_500_then_own", [{"post_status": 500}, {"advertised": b"own", "served": b"own"}], b"own", None),
    ("creation_503_then_own", [{"post_status": 503}, {"advertised": b"own", "served": b"own"}], b"own", None),
    ("creation_500_exhausted", [{"post_status": 500}], None, "INDEX_SNAPSHOT_UNSTABLE"),
    ("creation_500_then_overwritten", [{"post_status": 500}, {"advertised": b"a", "served": b"other"}], None,
     "INDEX_SNAPSHOT_UNSTABLE"),
]


@pytest.mark.parametrize("case,script,expected,error", SNAPSHOT_CASES, ids=[c[0] for c in SNAPSHOT_CASES])
def test_index_snapshot_download_is_bound_to_its_own_creation(agent_module, case, script, expected, error):
    server = _SnapshotServer(script)
    try:
        if error is None:
            assert agent_module.snapshot_index(server.base, "c", attempts=2) == expected
        else:
            with pytest.raises(ValueError, match=error):
                agent_module.snapshot_index(server.base, "c", attempts=2)
    finally:
        server.close()
    assert server.created == (1 if case == "own_snapshot" else 2), "bounded attempts, no retry after success"
    assert len(server.deleted) == server.issued, \
        "every created snapshot name is cleaned up (404 of a concurrent cleanup tolerated)"


@pytest.mark.parametrize("status", [400, 404, 409])
def test_index_snapshot_creation_client_error_is_not_retried(agent_module, status):
    """Negative side of the 5xx retry: a 4xx on creation is a request/config defect, not the
    concurrent-seal collision; it propagates on the first attempt (seal fails closed)."""
    server = _SnapshotServer([{"post_status": status}, {"advertised": b"own", "served": b"own"}])
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            agent_module.snapshot_index(server.base, "c", attempts=2)
    finally:
        server.close()
    assert caught.value.code == status
    assert (server.created, server.issued, server.deleted) == (1, 0, [])


# --------------------------------------------------------------------------- live environment


def _env_file() -> Path | None:
    if os.environ.get("OCOR_BOOTSTRAP_ENV"):
        candidate = Path(os.environ["OCOR_BOOTSTRAP_ENV"])
        return candidate if candidate.exists() else None
    for candidate in (Path.home() / ".ocor-bootstrap-secrets" / "ocor-bootstrap.env", ROOT / ".ocor" / "bootstrap.env"):
        if candidate.exists():
            return candidate
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".ocor" / "bootstrap.env"
        if candidate.exists():
            return candidate
    return None


def require_live_environment() -> dict[str, str]:
    """Mandatory qualifying environment: absence FAILS (never skips)."""
    env_file = _env_file()
    if env_file is None:
        pytest.fail("ocor-bootstrap env file not found: the real stack is mandatory qualifying evidence")
    if shutil.which("docker") is None:
        pytest.fail("docker is unavailable: the real stack is mandatory qualifying evidence")
    missing = []
    for service in BOOTSTRAP_SERVICES:
        result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}} {{.State.Paused}}",
                                 f"ocor-bootstrap-{service}-1"], capture_output=True, text=True, check=False)
        if result.returncode != 0 or result.stdout.strip() != "true false":
            missing.append(service)
    if missing:
        pytest.fail(f"mandatory ocor-bootstrap services are not running: {sorted(missing)}")
    return dict(line.strip().split("=", 1) for line in env_file.read_text().splitlines() if "=" in line)


class Stack:
    """Compose carrier of the PoC profile against the running ocor-bootstrap stack."""

    def __init__(self, env: dict[str, str], vault: Path, work: Path) -> None:
        self.env = env
        self.vault = vault
        self.work = work
        self.operator_token = secrets.token_hex(16)
        self.projects: set[str] = set()

    def compose_env(self, vault: Path | None = None) -> dict[str, str]:
        return {**os.environ, **self.env, "OCOR_OPS_OPERATOR_TOKEN": self.operator_token,
                "OCOR_BACKUP_VAULT_DIR": str(vault or self.vault),
                "OCOR_OPS_UID": str(os.getuid()), "OCOR_OPS_GID": str(os.getgid())}

    def compose(self, project: str, *args: str, vault: Path | None = None, extra_files: tuple[Path, ...] = (),
                timeout: int = 600) -> subprocess.CompletedProcess:
        self.projects.add(project)
        files = ["-f", str(OVERLAY)]
        for f in extra_files:
            files += ["-f", str(f)]
        return subprocess.run(["docker", "compose", "-p", project, *files, *args], capture_output=True, text=True,
                              env=self.compose_env(vault), timeout=timeout, check=False, cwd=ROOT)

    def run_stage(self, project: str, profile: str, service: str, vault: Path | None = None,
                  extra_files: tuple[Path, ...] = ()) -> tuple[int, str]:
        result = self.compose(project, "--profile", profile, "up", "--exit-code-from", service, service,
                              vault=vault, extra_files=extra_files)
        logs = self.compose(project, "--profile", profile, "logs", "--no-color", vault=vault,
                            extra_files=extra_files).stdout
        return result.returncode, result.stdout + result.stderr + logs

    def run_stage_detached(self, project: str, profile: str, service: str, vault: Path | None = None,
                           extra_files: tuple[Path, ...] = ()) -> tuple[int, str]:
        """Like run_stage, but the restored stores stay up for direct observation."""
        result = self.compose(project, "--profile", profile, "up", "-d", service, vault=vault, extra_files=extra_files)
        assert result.returncode == 0, result.stdout + result.stderr
        waited = subprocess.run(["docker", "wait", f"{project}-{service}-1"], capture_output=True, text=True,
                                check=True, timeout=600)
        logs = self.compose(project, "--profile", profile, "logs", "--no-color", vault=vault,
                            extra_files=extra_files).stdout
        return int(waited.stdout.strip()), result.stdout + result.stderr + logs

    def down(self, project: str, profile: str = "full") -> None:
        self.compose(project, "--profile", "full", "--profile", "restore-drill", "down", "-v", "--remove-orphans")


STARTED_CONTAINERS: set[str] = set()  # every standalone container a test starts (stack hygiene)


def _docker_ids(*args: str) -> list[str]:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, check=False, timeout=60)
    return result.stdout.split()


def leftover_resources(projects: set[str], containers: set[str]) -> list[str]:
    """Containers, volumes and networks of this run that still exist (stack hygiene: none may)."""
    found = []
    for project in sorted(projects):
        label = f"label=com.docker.compose.project={project}"
        for kind, ids in (("container", _docker_ids("ps", "-aq", "--filter", label)),
                          ("volume", _docker_ids("volume", "ls", "-q", "--filter", label)),
                          ("network", _docker_ids("network", "ls", "-q", "--filter", label))):
            found += [f"{kind} {i} of project {project}" for i in ids]
    for name in sorted(containers):
        found += [f"container {name}" for _ in _docker_ids("ps", "-aq", "--filter", f"name=^/{name}$")]
    return found


def remove_run_resources(stack: Stack) -> list[str]:
    """Teardown of everything the run created, also after a failure; returns what was
    left behind by the ordinary teardown (removed here, then reported as a defect)."""
    for name in sorted(STARTED_CONTAINERS):
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, check=False)
    for project in sorted(stack.projects):
        stack.down(project)
    leftover = leftover_resources(stack.projects, STARTED_CONTAINERS)
    for project in sorted(stack.projects):
        label = f"label=com.docker.compose.project={project}"
        for ids, remove in ((_docker_ids("ps", "-aq", "--filter", label), ["rm", "-f", "-v"]),
                            (_docker_ids("volume", "ls", "-q", "--filter", label), ["volume", "rm", "-f"]),
                            (_docker_ids("network", "ls", "-q", "--filter", label), ["network", "rm"])):
            if ids:
                subprocess.run(["docker", *remove, *ids], capture_output=True, check=False)
    return leftover


def http_from(container: str, url: str, method: str = "GET", headers: dict | None = None,
              data: dict | None = None) -> tuple[int, str]:
    """Issue an HTTP request from inside a container (the profile networks are internal)."""
    payload = None if data is None else json.dumps(data).encode()
    code = (
        "import json,sys,urllib.request,urllib.error\n"
        f"r=urllib.request.Request({url!r},method={method!r},headers={json.dumps(headers or {})},data={payload!r})\n"
        "try:\n"
        "    resp=urllib.request.urlopen(r,timeout=10); print(resp.status); print(resp.read().decode())\n"
        "except urllib.error.HTTPError as e:\n"
        "    print(e.code); print(e.read().decode())\n"
        "except OSError as e:\n"
        "    print(0); print(json.dumps({'error': type(e).__name__, 'reasons': []}))\n"
    )
    result = subprocess.run(["docker", "exec", container, "python3", "-c", code], capture_output=True, text=True,
                            check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    status, _, body = result.stdout.partition("\n")
    return int(status), body


def connect_from(container: str, host: str, port: int) -> str:
    code = (
        "import socket\n"
        "try:\n"
        f"    socket.create_connection(({host!r}, {port}), 4).close(); print('CONNECTED')\n"
        "except socket.gaierror:\n"
        "    print('DNS_DENIED')\n"
        "except OSError as e:\n"
        "    print('DENIED:' + type(e).__name__)\n"
    )
    result = subprocess.run(["docker", "exec", container, "python3", "-c", code], capture_output=True, text=True,
                            check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def wait_for(predicate, timeout: float, interval: float = 1.0, message: str = ""):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    pytest.fail(f"timed out after {timeout}s: {message} (last={last!r})")


def readyz(container: str) -> tuple[int, dict]:
    status, body = http_from(container, "http://ocor-ops:8080/readyz")
    return status, json.loads(body)


def scanned(result: tuple[int, dict]) -> bool:
    return result[0] in (200, 503) and result[1].get("reasons") not in ([], ["NOT_YET_SCANNED"], None)


def metrics(container: str) -> dict[str, float]:
    status, body = http_from(container, "http://ocor-ops:8080/metrics")
    assert status == 200
    out: dict[str, float] = {}
    for line in filter(None, body.splitlines()):
        name, _, value = line.rpartition(" ")
        out[name] = float(value)  # every exported sample is a real number
    return out


OPS_URL = "http://ocor-ops:8080"


def admit(container: str, operation_class: str, base: str = OPS_URL) -> tuple[int, dict]:
    status, body = http_from(container, f"{base}/admit?class={operation_class}")
    return status, json.loads(body)


def assert_admission(container: str, admitted: list[str], fault: str | None = None, base: str = OPS_URL) -> None:
    """Observe the decision of every operation class: `admitted` must be ADMIT, every
    other class must be DENY and, when given, carry `fault` in its reason code."""
    for operation_class in OPERATION_CLASSES:
        status, body = admit(container, operation_class, base)
        if operation_class in admitted:
            assert (status, body["decision"]) == (200, "ADMIT"), (operation_class, body)
        else:
            assert (status, body["decision"]) == (503, "DENY"), (operation_class, body)
            assert fault is None or fault in body["reason_code"], (operation_class, fault, body)


def posture(container: str, base: str = OPS_URL) -> dict:
    status, body = http_from(container, f"{base}/posture")
    assert status == 200
    return json.loads(body)


def receipt_digest(vault: Path) -> str:
    """Independent oracle: the SHA-256 of the latest signed receipt file."""
    return hashlib.sha256(sorted((vault / "restore-receipts").glob("*.json"))[-1].read_bytes()).hexdigest()


def reopen(container: str, token: str, digest: str | None, human: str | None = "drill-operator",
           base: str = OPS_URL) -> tuple[int, dict]:
    body = {k: v for k, v in (("receipt_digest", digest), ("authorized_by", human)) if v is not None}
    status, text = http_from(container, f"{base}/reopen", "POST",
                             {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, body)
    return status, json.loads(text)


def governed_reopen(stack, container: str, vault: Path, base: str = OPS_URL) -> None:
    """Human reopening of the mutative path bound to the receipt that passed the gate."""
    digest = receipt_digest(vault)
    wait_for(lambda: posture(container, base)["restore"]["receipt_digest"] == digest, 30,
             message="agent must have verified the current receipt")
    status, body = reopen(container, stack.operator_token, digest, base=base)
    assert (status, body["reason_code"]) == (200, "MUTATIVE_PATH_REOPENED_BY_HUMAN"), body


def restored_payloads(project: str) -> dict[str, dict]:
    """Read the restored index directly from the isolated restore network."""
    code = ("import json,urllib.request\n"
            "r=urllib.request.Request('http://ocor-restore-qdrant:6333/collections/ocor_poc_drill_memory/points/scroll',"
            "method='POST',headers={'Content-Type':'application/json'},"
            "data=json.dumps({'limit':256,'with_payload':True}).encode())\n"
            "print(json.dumps([p['payload'] for p in json.load(urllib.request.urlopen(r,timeout=10))['result']['points']]))")
    result = subprocess.run(["docker", "run", "--rm", "--network", f"{project}_restore", OPS_IMAGE, "python3", "-c",
                             code], capture_output=True, text=True, check=False, timeout=120)
    assert result.returncode == 0, result.stderr
    return {p["item_id"]: p for p in json.loads(result.stdout)}


# --------------------------------------------------------------------------- drill fixture


def postgres_dsn(env: dict[str, str], db: str = "ocor") -> str:
    return f"host=127.0.0.1 port=55433 user=ocor password={env['OCOR_LOCAL_POSTGRES_PASSWORD']} dbname={db}"


def qdrant_call(method: str, path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(f"http://127.0.0.1:16333{path}", method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=30).read())
    except urllib.error.HTTPError as exc:
        return {"status_code": exc.code}


def memory_point_id(item_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ocor-memory:{item_id}"))


DRILL_MARKING = _drill_digest("marking", "SYNTHETIC-UNCLASSIFIED")


def drill_scope(n: int) -> tuple[str, str]:
    return ("tenant-a", "c1") if n % 2 else ("tenant-b", "c2")


def drill_gcs(tenant: str, compartment: str) -> str:
    """GCS digest bound at admission (contract `urn:sha256:` form) for a drill item."""
    return _drill_digest("gcs", tenant, compartment, DRILL_MARKING)


def load_drill_fixture(env: dict[str, str], consistent: bool, items: int = 5) -> None:
    """Synthetic memory drill: m2/m4 are deleted in metadata while the index still
    holds them at the cut. `consistent=False` drops the m4 tombstone from the
    journal (stale deletion epoch -> resurrection risk)."""
    import psycopg

    with psycopg.connect(postgres_dsn(env), autocommit=True) as conn:
        conn.execute("drop database if exists ocor_poc_drill with (force)")
        conn.execute("create database ocor_poc_drill")
    with psycopg.connect(postgres_dsn(env, "ocor_poc_drill"), autocommit=True) as conn:
        conn.execute(
            "create table memory_item(item_id text primary key, tenant_id text not null, compartments text not null,"
            " representation_version int not null, lifecycle_epoch int not null, lifecycle_state text not null,"
            " deletion_epoch bigint, content_ref text not null, classification_marking_ref text not null,"
            " governed_context_digest text not null)")
        conn.execute("create table memory_deletion_journal(event_id text primary key, item_id text not null,"
                     " deletion_epoch bigint not null)")
        for n in range(1, items + 1):
            item = f"m{n}"
            deleted = {"m2": 6, "m4": 7}.get(item)
            tenant, compartment = drill_scope(n)
            conn.execute("insert into memory_item values (%s,%s,%s,2,3,%s,%s,%s,%s,%s)",
                         (item, tenant, json.dumps([compartment]), "deleted" if deleted else "active", deleted,
                          f"cas:sha256:{item}", DRILL_MARKING, drill_gcs(tenant, compartment)))
        conn.execute("insert into memory_deletion_journal values ('evt-del-m2','m2',6)")
        if consistent:
            conn.execute("insert into memory_deletion_journal values ('evt-del-m4','m4',7)")
    collection = "/collections/ocor_poc_drill_memory"
    qdrant_call("DELETE", collection)
    assert qdrant_call("PUT", collection, {"vectors": {"size": 4, "distance": "Cosine"}}).get("status") == "ok"
    points = []
    for n in range(1, items + 1):
        tenant, compartment = drill_scope(n)
        points.append({"id": memory_point_id(f"m{n}"), "vector": [0.1 * n, 0.2, 0.3, 0.4],
                       "payload": {"item_id": f"m{n}", "tenant_id": tenant, "compartments": [compartment],
                                   "classification_marking_ref": DRILL_MARKING,
                                   "governed_context_digest": drill_gcs(tenant, compartment),
                                   "representation_version": 2, "lifecycle_epoch": 3}})
    assert qdrant_call("PUT", collection + "/points?wait=true", {"points": points}).get("status") == "ok"


def drop_drill_fixture(env: dict[str, str]) -> None:
    import psycopg

    with psycopg.connect(postgres_dsn(env), autocommit=True) as conn:
        conn.execute("drop database if exists ocor_poc_drill with (force)")
    qdrant_call("DELETE", "/collections/ocor_poc_drill_memory")


def make_writable(path: Path) -> None:
    for p in [path, *path.rglob("*")]:
        if p.is_dir():
            p.chmod(stat.S_IRWXU)
        elif p.exists():
            p.chmod(stat.S_IRUSR | stat.S_IWUSR)


def latest_receipt(vault: Path) -> dict:
    return json.loads(sorted((vault / "restore-receipts").glob("*.json"))[-1].read_bytes())


def profile_override(work: Path, mutate) -> Path:
    profile = deepcopy(helm_profile())
    mutate(profile)
    path = work / f"override-{uuid.uuid4().hex}.yaml"
    content = json.dumps(profile, sort_keys=True).replace("$", "$$")
    path.write_text(yaml.safe_dump({"configs": {"ocor-poc-profile": {"content": content}}}), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- live compose stack


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    env = require_live_environment()
    work = tmp_path_factory.mktemp("ocor-poc")
    vault = work / "vault"
    vault.mkdir()
    st = Stack(env, vault, work)
    st.ops_project = f"ocor-poc-ops-{uuid.uuid4().hex[:6]}"
    st.ops = f"{st.ops_project}-ocor-ops-1"
    load_drill_fixture(env, consistent=True)
    try:
        result = st.compose(st.ops_project, "--profile", "observability", "up", "-d")
        assert result.returncode == 0, result.stderr
        wait_for(lambda: http_from(st.ops, "http://ocor-ops:8080/livez")[0] == 200, 60,
                 message="ops agent did not start listening")
        yield st
    finally:
        leftover = remove_run_resources(st)
        drop_drill_fixture(env)
        make_writable(work)
        assert not leftover, f"teardown left resources behind (stack hygiene defect): {leftover}"
        assert not leftover_resources(st.projects, STARTED_CONTAINERS), "resources survived the forced removal"


def test_ops_process_serves_health_and_blocks_readiness_until_restore_is_tested(stack):
    status, body = http_from(stack.ops, "http://ocor-ops:8080/livez")
    assert (status, json.loads(body)["status"]) == (200, "ALIVE")
    status, ready = wait_for(lambda: scanned(r := readyz(stack.ops)) and r, 30)
    assert status == 503
    assert ready["reasons"] == ["RESTORE_UNTESTED"], "all ten dependencies must be up; only the restore is missing"
    m = metrics(stack.ops)
    for dependency in BOOTSTRAP_SERVICES:
        assert m[f'ocor_dependency_up{{dependency="{dependency}"}}'] == 1.0
        for q in ("0.5", "0.95", "0.99"):
            assert m[f'ocor_dependency_probe_duration_seconds{{dependency="{dependency}",quantile="{q}"}}'] > 0
    assert m["ocor_readiness_ready"] == 0.0
    assert m["ocor_egress_public_reachable"] == 0.0
    # Untested restore: the recovery gate has not passed, so no traffic is admitted
    # (verdict OCOR-DEV-0049-7fd4f7728801-2 VF-001); the posture names the condition.
    assert_admission(stack.ops, admitted=[], fault="restore_not_verified")
    assert "restore_not_verified" in posture(stack.ops)["faults"]
    assert m['ocor_safe_degraded_fault_active{fault="restore_not_verified"}'] == 1.0
    mounted = subprocess.run(["docker", "exec", stack.ops, "cat", "/etc/ocor/profile.json"],
                             capture_output=True, text=True, check=True).stdout
    assert json.loads(mounted) == helm_profile(), "the running process consumes the governed profile"


def drill_live_items(live: list[int]) -> dict:
    """Oracle of the sealed live projection of the drill fixture: count, id set digest and
    per-item isolation scope digest (tenant, compartments, marking, GCS, versions)."""
    rows = []
    for n in live:
        tenant, compartment = drill_scope(n)
        rows.append([f"m{n}", tenant, [compartment], DRILL_MARKING, drill_gcs(tenant, compartment), "2", "3"])
    return {"count": len(live),
            "ids_digest": hashlib.sha256(canonical_bytes(sorted(f"m{n}" for n in live))).hexdigest(),
            "scope_digest": hashlib.sha256(canonical_bytes(sorted(rows, key=canonical_bytes))).hexdigest()}


def test_backup_seals_an_encrypted_signed_immutable_recovery_point(stack):
    project = f"ocor-poc-backup-{uuid.uuid4().hex[:6]}"
    code, logs = stack.run_stage(project, "backup", "ocor-backup-seal")
    assert code == 0, logs
    stack.down(project)  # workload fault domain removed, including its volumes
    points = sorted((stack.vault / "recovery-points").iterdir())
    assert len(points) == 1
    rp = points[0]
    raw = (rp / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    assert manifest["memory"]["status"] == "PRESENT"
    assert manifest["memory"]["journalCheckpoints"] == {
        "entries": 2, "max_deletion_epoch": 7, "last_event_id": "evt-del-m4",
        "event_ids_digest": sequence_digest(["evt-del-m2", "evt-del-m4"])}
    assert manifest["memory"]["liveItems"] == drill_live_items([1, 3, 5])
    assert set(manifest["store_digests"]) == {Path(a["name"]).stem for a in manifest["artifacts"]
                                              if a["name"].endswith(".digest")}
    assert {"ocor", "ocor_poc_drill"} <= set(manifest["store_digests"])
    assert all(re.fullmatch(r"[0-9a-f]{64}", v) for v in manifest["store_digests"].values())
    assert manifest["memory"]["representationVersions"] == [2]
    assert manifest["memory"]["lifecycleEpochs"] == [3]
    assert manifest["memory"]["contentRefs"] == [f"cas:sha256:m{n}" for n in range(1, 6)]
    assert {"canonical", "audit", "event", "governance", "definition", "projection", "key_custody"} <= set(
        manifest["authority_classes_present"])
    assert set(manifest["authority_classes_without_store"]) == {"action", "model_scenario"}
    names = {a["name"] for a in manifest["artifacts"]}
    assert {"postgresql/ocor.dump", "postgresql/ocor_poc_drill.dump", "kafka/offsets.txt",
            "qdrant/ocor_poc_drill_memory.snapshot", "memory/memory-deletion-journal.csv",
            "opa/policies.json"} <= names
    for artifact in manifest["artifacts"]:
        blob_path = rp / "objects" / f"{artifact['ciphertext_sha256']}.enc"
        blob = blob_path.read_bytes()
        assert blob_path.stat().st_mode & 0o777 == 0o444
        assert b"PGDMP" not in blob and b"tenant-a" not in blob and b"evt-del" not in blob
        assert all(c.startswith("vault:v1:") for c in json.loads(blob)["chunks"])
    with pytest.raises(PermissionError):
        (rp / "manifest.json").write_bytes(b"{}")
    signature = (rp / "manifest.sig").read_text()
    assert transit_verify(stack.env, raw, signature) is True
    assert transit_verify(stack.env, raw.replace(b"PRESENT", b"ABSENT_"), signature) is False


def test_capture_fails_explicitly_when_the_database_is_unreachable(stack):
    """The PostgreSQL capture waits a bounded number of attempts for its source and then
    fails explicitly, never producing an empty capture (positive control: same service,
    same bound, reachable database)."""
    project = f"ocor-poc-capture-{uuid.uuid4().hex[:6]}"
    try:
        ok = stack.compose(project, "--profile", "backup", "run", "--rm", "-e", "OCOR_CAPTURE_WAIT_ATTEMPTS=3",
                           "ocor-backup-capture-postgresql")
        assert ok.returncode == 0, ok.stdout + ok.stderr
        assert "ocor.dump" in ok.stdout and "memory-items.csv" in ok.stdout, ok.stdout
        bad = stack.compose(project, "--profile", "backup", "run", "--rm", "-e", "OCOR_CAPTURE_WAIT_ATTEMPTS=3",
                            "-e", "PGHOST=unreachable-postgresql", "ocor-backup-capture-postgresql")
        assert bad.returncode != 0, bad.stdout + bad.stderr
        assert "CAPTURE_SOURCE_UNREACHABLE: postgresql after 3 attempts" in bad.stdout + bad.stderr
    finally:
        stack.down(project)


QDRANT_HOST_URL = "http://127.0.0.1:16333"


def test_concurrent_seals_each_download_their_own_index_snapshot(stack, agent_module):
    """Real Qdrant: snapshots requested in the same second share ONE file name (the race
    that failed the manual backup overlapping the scheduled CronJob run on kind); four
    concurrent seal downloads nevertheless each return a snapshot verified against the
    checksum of their own creation, and no snapshot is left behind."""
    import threading

    collection = helm_profile()["backup"]["memory"]["sources"]["indexCollection"]
    base = f"{QDRANT_HOST_URL}/collections/{collection}/snapshots"

    def concurrently(fn, n: int = 4) -> list:
        barrier, out = threading.Barrier(n), [None] * n

        def run(i: int) -> None:
            barrier.wait()
            try:
                out[i] = fn()
            except Exception as exc:  # recorded and asserted below
                out[i] = exc
        threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
        [th.start() for th in threads]
        [th.join() for th in threads]
        return out

    def naive_name() -> str:
        request = urllib.request.Request(f"{base}?wait=true", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(request, timeout=60).read())["result"]["name"]

    def existing() -> list[str]:
        return sorted(s["name"] for s in json.loads(urllib.request.urlopen(base, timeout=30).read())["result"])

    before = existing()
    names = wait_for(lambda: (n := concurrently(naive_name)) and len(set(n)) < len(n) and n, 60, 1,
                     "precondition: concurrent snapshots share a name")
    for name in set(names):
        urllib.request.urlopen(urllib.request.Request(f"{base}/{name}", method="DELETE"), timeout=30)
    for round_ in range(3):  # repeated: a timing-dependent pass is not a pass (VF-001 cycle 5)
        downloads = concurrently(lambda: agent_module.snapshot_index(QDRANT_HOST_URL, collection))
        assert all(isinstance(d, bytes) and len(d) > 0 for d in downloads), (round_, downloads)
    assert existing() == before, "every snapshot created by the seals is cleaned up"


def transit_verify(env: dict[str, str], data: bytes, signature: str) -> bool:
    request = urllib.request.Request(
        "http://127.0.0.1:8200/v1/ocor-poc-transit/verify/ocor-poc-backup-sign", method="POST",
        data=json.dumps({"input": base64.b64encode(data).decode(), "signature": signature}).encode(),
        headers={"X-Vault-Token": env["OCOR_LOCAL_OPENBAO_TOKEN"]})
    return bool(json.loads(urllib.request.urlopen(request, timeout=10).read())["data"]["valid"])


def test_isolated_restore_replays_tombstones_and_passes_the_recovery_gate(stack):
    project = f"ocor-poc-restore-{uuid.uuid4().hex[:6]}"
    code, logs = stack.run_stage_detached(project, "restore-drill", "ocor-restore-finalize")
    assert code == 0, logs
    # Positive case of the per-item scope oracle: the restored index carries exactly the
    # tenant, compartments, marking and GCS binding of the authoritative metadata.
    restored = restored_payloads(project)
    assert sorted(restored) == ["m1", "m3", "m5"], "tombstoned m2/m4 are not resurrected"
    for item, payload in restored.items():
        tenant, compartment = drill_scope(int(item[1:]))
        assert (payload["tenant_id"], payload["compartments"], payload["classification_marking_ref"],
                payload["governed_context_digest"]) == (tenant, [compartment], DRILL_MARKING,
                                                       drill_gcs(tenant, compartment)), payload
    networks = json.loads(subprocess.run(["docker", "network", "inspect", f"{project}_restore"],
                                         capture_output=True, text=True, check=True).stdout)
    assert networks[0]["Internal"] is True
    attached = json.loads(subprocess.run(
        ["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", f"{project}-ocor-restore-postgresql-1"],
        capture_output=True, text=True, check=True).stdout)
    assert list(attached) == [f"{project}_restore"], "restored stores live only on the isolated network"
    staged = subprocess.run(["docker", "run", "--rm", "-v", f"{project}_restore-staging:/r", OPS_IMAGE,
                             "find", "/r", "-type", "f"], capture_output=True, text=True, check=True).stdout
    assert staged.strip() == "", "decrypted plaintext must be erased after the restore"
    stack.down(project)
    receipt = latest_receipt(stack.vault)
    assert receipt["outcome"] == "PASSED"
    assert receipt["replayed_event_ids"] == ["evt-del-m2", "evt-del-m4"], "original ids, journal order"
    manifest = json.loads((stack.vault / "recovery-points" / receipt["recovery_point"] / "manifest.json").read_bytes())
    assert sequence_digest(receipt["replayed_event_ids"]) == manifest["memory"]["journalCheckpoints"][
        "event_ids_digest"], "the replayed sequence is the signed one"
    assert (receipt["replay_digest"], receipt["restored_scope_digest"]) == (
        drill_live_items([1, 3, 5])["ids_digest"], drill_live_items([1, 3, 5])["scope_digest"])
    assert receipt["restored_store_digests"] == manifest["store_digests"]
    assert receipt["completed_at_epoch"] >= manifest["created_at_epoch"]
    assert all(receipt["recovery_gate"][name]["pass"] for name in RECOVERY_GATE)
    assert receipt["quarantined_items"] == []
    assert receipt["retrieval_reopened"] is False
    assert receipt["isolated_network"] is True
    steps = [s["step"] for s in receipt["steps"]]
    assert steps.index("replay_memory_deletion_tombstones_before_reopen_retrieval") < steps.index(
        "rebuild_logic_projection_and_w3c_boundary")
    stack.replay_digest = receipt["replay_digest"]


def test_readiness_turns_ready_only_with_a_signed_passed_restore_receipt(stack):
    status, ready = wait_for(lambda: (r := readyz(stack.ops))[0] == 200 and r, 30,
                             message="readiness must turn READY after the tested restore")
    assert ready["reasons"] == ["READY"]
    m = metrics(stack.ops)
    assert m["ocor_restore_tested"] == 1.0
    assert m["ocor_recovery_point_within_rpo"] == 1.0
    health = wait_for(lambda: subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", stack.ops],
                                             capture_output=True, text=True).stdout.strip() == "healthy", 30)
    assert health


def test_mutative_path_reopens_only_by_a_human_bound_to_the_passed_receipt(stack):
    """ADD v1.3 §6.5 step 10: after the recovery gate, reads reopen but the mutative
    path stays closed until a named human authorizes it for that exact receipt."""
    assert_admission(stack.ops, admitted=["exact_consistency_read", "read"], fault="recovery_reopen_pending")
    digest = receipt_digest(stack.vault)
    assert posture(stack.ops)["restore"] == {"reason_code": "RESTORE_TESTED", "receipt_digest": digest, "detail": []}
    status, _ = reopen(stack.ops, "wrong-token", digest)
    assert status == 401
    status, body = reopen(stack.ops, stack.operator_token, digest, human=None)
    assert (status, body["reason_code"]) == (400, "REOPEN_REFUSED:HUMAN_AUTHORIZER_REQUIRED")
    status, body = reopen(stack.ops, stack.operator_token, "0" * 64)
    assert (status, body["reason_code"]) == (409, "REOPEN_REFUSED:RECEIPT_MISMATCH")
    assert_admission(stack.ops, admitted=["exact_consistency_read", "read"], fault="recovery_reopen_pending")
    status, body = reopen(stack.ops, stack.operator_token, digest)
    assert (status, body["reason_code"], body["receipt_digest"]) == (200, "MUTATIVE_PATH_REOPENED_BY_HUMAN", digest)
    assert_admission(stack.ops, admitted=OPERATION_CLASSES)
    state = posture(stack.ops)
    assert state["faults"] == [] and state["reopen"]["authorization"]["authorized_by"] == "drill-operator"
    assert metrics(stack.ops)["ocor_recovery_reopen_authorized"] == 1.0


def test_restore_replay_is_deterministic(stack):
    previous = receipt_digest(stack.vault)
    project = f"ocor-poc-restore-{uuid.uuid4().hex[:6]}"
    code, logs = stack.run_stage(project, "restore-drill", "ocor-restore-finalize")
    stack.down(project)
    assert code == 0, logs
    assert latest_receipt(stack.vault)["replay_digest"] == stack.replay_digest
    # A new receipt supersedes the one the human authorized: the mutative path closes
    # again and the old authorization cannot be replayed.
    current = receipt_digest(stack.vault)
    assert current != previous
    wait_for(lambda: posture(stack.ops)["restore"]["receipt_digest"] == current, 30)
    assert_admission(stack.ops, admitted=["exact_consistency_read", "read"], fault="recovery_reopen_pending")
    status, body = reopen(stack.ops, stack.operator_token, previous)
    assert (status, body["reason_code"]) == (409, "REOPEN_REFUSED:RECEIPT_MISMATCH")
    governed_reopen(stack, stack.ops, stack.vault)
    assert_admission(stack.ops, admitted=OPERATION_CLASSES)


def _copy_vault(stack, name: str) -> Path:
    copy = stack.work / name
    shutil.copytree(stack.vault, copy)
    make_writable(copy)
    return copy


@pytest.mark.parametrize("target,expected", [
    ("object", "CIPHERTEXT_DIGEST_MISMATCH"), ("manifest", "SIGNATURE_INVALID")])
def test_tampered_recovery_point_is_rejected_before_restore(stack, target, expected):
    vault = _copy_vault(stack, f"tampered-{target}")
    shutil.rmtree(vault / "restore-receipts")
    rp = next((vault / "recovery-points").iterdir())
    path = sorted((rp / "objects").iterdir())[0] if target == "object" else rp / "manifest.json"
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))
    project = f"ocor-poc-tamper-{uuid.uuid4().hex[:6]}"
    code, logs = stack.run_stage(project, "restore-drill", "ocor-restore-prepare", vault=vault)
    stack.down(project)
    assert code == EXIT_VERIFY, logs
    assert expected in logs
    assert not (vault / "restore-receipts").exists(), "no receipt may be produced from a tampered point"


def _standalone_ops(stack, vault: Path, network: str, profile_path: Path | None = None) -> str:
    name = f"ocor-poc-probe-{uuid.uuid4().hex[:6]}"
    STARTED_CONTAINERS.add(name)
    agent = stack.work / "agent.py"
    agent.write_text(agent_source(), encoding="utf-8")
    profile = profile_path or stack.work / "profile.json"
    if profile_path is None:
        profile.write_text(json.dumps(helm_profile()), encoding="utf-8")
    result = subprocess.run(
        ["docker", "run", "-d", "--name", name, "--network", network, "--user", f"{os.getuid()}:{os.getgid()}",
         "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
         "-e", f"OCOR_OPENBAO_TOKEN={stack.env['OCOR_LOCAL_OPENBAO_TOKEN']}",
         "-e", f"OCOR_OPS_OPERATOR_TOKEN={stack.operator_token}",
         "-v", f"{agent}:/opt/ocor/ocor_ops_agent.py:ro", "-v", f"{profile}:/etc/ocor/profile.json:ro",
         "-v", f"{vault}:/vault:ro", OPS_IMAGE, "python3", "/opt/ocor/ocor_ops_agent.py", "serve",
         "--profile", "/etc/ocor/profile.json", "--vault", "/vault"],
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return name


LOCAL_OPS = "http://127.0.0.1:8080"


def _standalone_readyz(name: str) -> tuple[int, dict]:
    status, body = http_from(name, "http://127.0.0.1:8080/readyz")
    return status, json.loads(body)


def test_tampered_restore_receipt_blocks_readiness(stack):
    vault = _copy_vault(stack, "tampered-receipt")
    receipt = sorted((vault / "restore-receipts").glob("*.json"))[-1]
    receipt.write_bytes(receipt.read_bytes().replace(b'"PASSED"', b'"PASSES"'))
    name = _standalone_ops(stack, vault, f"{stack.ops_project}_site")
    try:
        _, ready = wait_for(lambda: scanned(r := _standalone_readyz(name)) and r, 30)
        assert ready["reasons"] == ["RESTORE_RECEIPT_INVALID"]
        assert_admission(name, admitted=[], fault="restore_not_verified", base=LOCAL_OPS)
        status, body = reopen(name, stack.operator_token, receipt_digest(vault), base=LOCAL_OPS)
        assert (status, body["reason_code"]) == (409, "REOPEN_REFUSED:RESTORE_RECEIPT_INVALID")
        assert_admission(name, admitted=[], fault="restore_not_verified", base=LOCAL_OPS)
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, check=False)


def transit_sign(env: dict[str, str], data: bytes) -> str:
    """Sign with the REAL custodian key (OpenBao transit), exactly as restore-finalize does."""
    request = urllib.request.Request(
        "http://127.0.0.1:8200/v1/ocor-poc-transit/sign/ocor-poc-backup-sign", method="POST",
        data=json.dumps({"input": base64.b64encode(data).decode()}).encode(),
        headers={"X-Vault-Token": env["OCOR_LOCAL_OPENBAO_TOKEN"]})
    return str(json.loads(urllib.request.urlopen(request, timeout=10).read())["data"]["signature"])


def write_signed_receipt(env: dict[str, str], vault: Path, receipt: dict, name: str,
                         raw: bytes | None = None) -> tuple[list[Path], str]:
    """Write `receipt` (or exactly `raw`) as the newest receipt of `vault`, validly signed;
    return its files and digest."""
    raw = canonical_bytes(receipt) if raw is None else raw
    root = vault / "restore-receipts"
    files = [root / f"99991231T235959Z-{name}.json", root / f"99991231T235959Z-{name}.sig"]
    files[0].write_bytes(raw)
    files[1].write_text(transit_sign(env, raw), encoding="utf-8")
    assert transit_verify(env, raw, files[1].read_text()), "precondition: the custodian signature is valid"
    return files, hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def coherence_ops(stack):
    """One running agent on a copy of the tested vault, used to observe the decision on
    validly signed receipts of every coherence branch (VF-002)."""
    vault = _copy_vault(stack, "coherence")
    authentic = latest_receipt(vault)
    name = _standalone_ops(stack, vault, f"{stack.ops_project}_site")
    try:
        wait_for(lambda: _standalone_readyz(name)[0] == 200, 60, message="authentic receipt must be accepted")
        yield {"name": name, "vault": vault, "authentic": authentic,
               "authentic_digest": receipt_digest(vault)}
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, check=False)


def test_custodian_signed_coherent_receipt_is_accepted(stack, coherence_ops):
    """Positive control of VF-002: a receipt signed by the test through the real custodian,
    coherent in every check, is accepted and reopenable (so the negatives below fail for
    their incoherence, not for the signature path)."""
    name, vault = coherence_ops["name"], coherence_ops["vault"]
    receipt = deepcopy(coherence_ops["authentic"])
    receipt["correlation_id"] = "positive-control"
    files, digest = write_signed_receipt(stack.env, vault, receipt, "positive")
    try:
        wait_for(lambda: posture(name, LOCAL_OPS)["restore"]["receipt_digest"] == digest, 30,
                 message="the custodian-signed coherent receipt must be the verified one")
        assert _standalone_readyz(name)[1]["reasons"] == ["READY"]
        status, body = reopen(name, stack.operator_token, digest, base=LOCAL_OPS)
        assert (status, body["reason_code"]) == (200, "MUTATIVE_PATH_REOPENED_BY_HUMAN"), body
        assert_admission(name, admitted=OPERATION_CLASSES, base=LOCAL_OPS)
    finally:
        for f in files:
            f.unlink()
    wait_for(lambda: posture(name, LOCAL_OPS)["restore"]["receipt_digest"] == coherence_ops["authentic_digest"], 30)


@pytest.mark.parametrize("case,mutate,expected", RECEIPT_MUTATIONS, ids=[c[0] for c in RECEIPT_MUTATIONS])
def test_custodian_signed_incoherent_receipt_blocks_readiness_reopen_and_admission(
        stack, coherence_ops, case, mutate, expected):
    """Verdict OCOR-DEV-0049-02ac643eb3c7-3 VF-002 on the live agent: a validly signed
    receipt claiming PASSED with a failed, missing or malformed check denies readiness,
    refuses /reopen and admits nothing; removing it restores the accepted state."""
    name, vault = coherence_ops["name"], coherence_ops["vault"]
    receipt = deepcopy(coherence_ops["authentic"])
    mutate(receipt)
    files, digest = write_signed_receipt(stack.env, vault, receipt, case.replace("_", "-"))
    try:
        state = wait_for(lambda: (p := posture(name, LOCAL_OPS))["restore"]["reason_code"]
                         == "RESTORE_RECEIPT_INCONSISTENT" and p, 30, message=case)
        assert expected in state["restore"]["detail"], state["restore"]
        assert state["restore"]["receipt_digest"] is None
        _, ready = wait_for(lambda: (r := _standalone_readyz(name))[0] == 503 and r, 15)
        assert ready["reasons"] == ["RESTORE_RECEIPT_INCONSISTENT"]
        status, body = reopen(name, stack.operator_token, digest, base=LOCAL_OPS)
        assert (status, body["reason_code"]) == (409, "REOPEN_REFUSED:RESTORE_RECEIPT_INCONSISTENT"), body
        assert_admission(name, admitted=[], fault="restore_not_verified", base=LOCAL_OPS)
    finally:
        for f in files:
            f.unlink()
    # Positive counterpart: the authentic coherent receipt is verified again.
    wait_for(lambda: posture(name, LOCAL_OPS)["restore"]["receipt_digest"] == coherence_ops["authentic_digest"], 30)
    assert wait_for(lambda: _standalone_readyz(name)[0] == 200, 15)


def _observe_refused_receipt(stack, name: str, digest: str, reason: str, detail: str | None) -> None:
    state = wait_for(lambda: (p := posture(name, LOCAL_OPS))["restore"]["reason_code"] == reason and p, 30,
                     message=reason)
    assert detail is None or detail in state["restore"]["detail"], state["restore"]
    assert state["restore"]["receipt_digest"] is None
    _, ready = wait_for(lambda: (r := _standalone_readyz(name))[0] == 503 and r, 15)
    assert ready["reasons"] == [reason]
    status, body = reopen(name, stack.operator_token, digest, base=LOCAL_OPS)
    assert (status, body["reason_code"]) == (409, f"REOPEN_REFUSED:{reason}"), body
    assert_admission(name, admitted=[], fault="restore_not_verified", base=LOCAL_OPS)


# On the live agent a receipt is also bound to the signed checkpoint of its recovery point
# (journal at epoch 7): a journal "ahead" of it was not restored from that point and is the
# `deletion_epoch_above_checkpoint` negative of CHECKPOINT_MUTATIONS, not a positive. Since
# cycle 8 the watermark is bound to the sealed live count (3): another consistent count is
# the `watermark_not_sealed_live_count` negative of CHECKPOINT_MUTATIONS.
RECEIPT_LIVE_POSITIVE_VARIANTS = [v for v in RECEIPT_POSITIVE_VARIANTS
                                  if v[0] not in ("journal_ahead_of_metadata", "other_consistent_watermark")]


@pytest.mark.parametrize("case,mutate", RECEIPT_LIVE_POSITIVE_VARIANTS,
                         ids=[c[0] for c in RECEIPT_LIVE_POSITIVE_VARIANTS])
def test_custodian_signed_receipt_with_coherent_details_is_accepted(stack, coherence_ops, case, mutate):
    """Positive side of VF-002 on the live agent: a validly signed receipt whose details are
    legitimately non-empty (other counts) is READY and reopenable. Journal ahead
    of metadata is tested below against its own sealed recovery point."""
    name, vault = coherence_ops["name"], coherence_ops["vault"]
    receipt = deepcopy(coherence_ops["authentic"])
    mutate(receipt)
    receipt["correlation_id"] = f"positive-{case}"
    files, digest = write_signed_receipt(stack.env, vault, receipt, f"positive-{case.replace('_', '-')}")
    try:
        wait_for(lambda: posture(name, LOCAL_OPS)["restore"]["receipt_digest"] == digest, 30, message=case)
        assert _standalone_readyz(name)[1]["reasons"] == ["READY"]
        status, body = reopen(name, stack.operator_token, digest, base=LOCAL_OPS)
        assert (status, body["reason_code"]) == (200, "MUTATIVE_PATH_REOPENED_BY_HUMAN"), body
        assert_admission(name, admitted=OPERATION_CLASSES, base=LOCAL_OPS)
    finally:
        for f in files:
            f.unlink()
    wait_for(lambda: posture(name, LOCAL_OPS)["restore"]["receipt_digest"] == coherence_ops["authentic_digest"], 30)


EPOCH_TOKEN = 1234567890.25
MAX_AGE_SECONDS = 168 * 3600
# Verdict OCOR-DEV-0049-aefabf91777d-4 VF-003: (case, completed_at_epoch, raw JSON token
# replacing it or None, ISO consistent, expected reason, expected detail).
RECEIPT_TIME_CASES = [
    ("valid_recent", lambda: time.time() - 3600, None, True, "RESTORE_TESTED", None),
    ("nan", lambda: EPOCH_TOKEN, b"NaN", True, "RESTORE_RECEIPT_INCONSISTENT", "receipt:non_standard_json"),
    ("infinity", lambda: EPOCH_TOKEN, b"Infinity", True, "RESTORE_RECEIPT_INCONSISTENT", "receipt:non_standard_json"),
    ("minus_infinity", lambda: EPOCH_TOKEN, b"-Infinity", True, "RESTORE_RECEIPT_INCONSISTENT",
     "receipt:non_standard_json"),
    ("overflow_to_infinity", lambda: EPOCH_TOKEN, b"1e400", True, "RESTORE_RECEIPT_INCONSISTENT",
     "receipt:non_standard_json"),
    ("future", lambda: time.time() + 3600, None, True, "RESTORE_RECEIPT_INCONSISTENT", "completed_at_epoch"),
    ("expired", lambda: time.time() - MAX_AGE_SECONDS - 3600, None, True, "RESTORE_RECEIPT_EXPIRED", None),
    ("within_max_age", lambda: time.time() - MAX_AGE_SECONDS + 3600, None, True, "RESTORE_TESTED", None),
    ("iso_incoherent", lambda: time.time() - 3600, None, False, "RESTORE_RECEIPT_INCONSISTENT", "completed_at"),
]


@pytest.mark.parametrize("case,epoch,token,coherent_iso,reason,detail", RECEIPT_TIME_CASES,
                         ids=[c[0] for c in RECEIPT_TIME_CASES])
def test_custodian_signed_receipt_time_branches(stack, coherence_ops, case, epoch, token, coherent_iso, reason,
                                                detail):
    """Every time branch of a validly signed receipt on the live agent: a finite, past,
    unexpired time coherent with its ISO form is accepted; NaN/Infinity (non-standard JSON),
    a future, expired or ISO-incoherent time denies readiness, /reopen and admission."""
    name, vault = coherence_ops["name"], coherence_ops["vault"]
    receipt = deepcopy(coherence_ops["authentic"])
    value = float(int(epoch()))
    # A backdated restore needs a recovery point sealed before it (cycle 8 binding).
    point = backdated_recovery_point(stack, vault, receipt, value - 60)
    receipt["completed_at_epoch"] = value
    receipt["completed_at"] = iso_utc(value) if coherent_iso else iso_utc(value - 86400)
    raw = canonical_bytes(receipt)
    if token is not None:
        marker = f'"completed_at_epoch":{json.dumps(value)}'.encode()
        assert raw.count(marker) == 1
        raw = raw.replace(marker, b'"completed_at_epoch":' + token)
    files, digest = write_signed_receipt(stack.env, vault, receipt, f"time-{case.replace('_', '-')}", raw=raw)
    try:
        if reason == "RESTORE_TESTED":
            wait_for(lambda: posture(name, LOCAL_OPS)["restore"]["receipt_digest"] == digest, 30, message=case)
            assert _standalone_readyz(name)[1]["reasons"] == ["READY"]
            status, body = reopen(name, stack.operator_token, digest, base=LOCAL_OPS)
            assert (status, body["reason_code"]) == (200, "MUTATIVE_PATH_REOPENED_BY_HUMAN"), body
            assert_admission(name, admitted=OPERATION_CLASSES, base=LOCAL_OPS)
        else:
            _observe_refused_receipt(stack, name, digest, reason, detail)
    finally:
        for f in files:
            f.unlink()
        shutil.rmtree(point)
    wait_for(lambda: posture(name, LOCAL_OPS)["restore"]["receipt_digest"] == coherence_ops["authentic_digest"], 30)
    assert wait_for(lambda: _standalone_readyz(name)[0] == 200, 15)


def backdated_recovery_point(stack, vault: Path, receipt: dict, created: float) -> Path:
    """Custodian-signed copy of the receipt's recovery point sealed at `created`, named to
    sort before every real point (never the latest, so RPO is unaffected); rebinds `receipt`."""
    source = vault / "recovery-points" / receipt["recovery_point"]
    manifest = json.loads((source / "manifest.json").read_bytes())
    rp_id = f"rp-00000000T000000Z-{uuid.uuid4().hex[:8]}"
    manifest.update(recovery_point=rp_id, created_at_epoch=created, created_at=iso_utc(created))
    raw = canonical_bytes(manifest)
    target = vault / "recovery-points" / rp_id
    target.mkdir()
    (target / "manifest.json").write_bytes(raw)
    (target / "manifest.sig").write_text(transit_sign(stack.env, raw), encoding="utf-8")
    receipt.update(recovery_point=rp_id, manifest_digest=hashlib.sha256(raw).hexdigest())
    return target


def _sealed_manifest(vault: Path, receipt: dict) -> dict:
    return json.loads((vault / "recovery-points" / receipt["recovery_point"] / "manifest.json").read_bytes())


def _completed_before_seal(vault: Path, receipt: dict) -> None:
    value = float(int(_sealed_manifest(vault, receipt)["created_at_epoch"]) - 30)
    receipt.update(completed_at_epoch=value, completed_at=iso_utc(value))


# Cycle 8 receipt-field audit, live: the bindings that hold for every recovery point.
RECOVERY_POINT_LIVE_MUTATIONS = [
    ("restore_completed_before_seal", _completed_before_seal, "receipt:completed_before_recovery_point"),
    ("store_digest_differs", lambda v, r: r["restored_store_digests"].update(ocor_poc_drill="0" * 64),
     "receipt:store_digests_mismatch"),
    ("store_not_restored", lambda v, r: r["restored_store_digests"].pop("ocor"), "receipt:store_digests_mismatch"),
    ("store_not_sealed", lambda v, r: r["restored_store_digests"].update(foreign="0" * 64),
     "receipt:store_digests_mismatch"),
]


@pytest.mark.parametrize("case,mutate,expected", RECOVERY_POINT_LIVE_MUTATIONS,
                         ids=[c[0] for c in RECOVERY_POINT_LIVE_MUTATIONS])
def test_custodian_signed_receipt_unbound_from_its_recovery_point_is_refused(stack, coherence_ops, case, mutate,
                                                                            expected):
    """Live agent, real custodian signature: a receipt coherent on its own and with the memory
    checkpoint, whose restore precedes the seal or whose restored store digests are not the
    sealed ones, denies readiness, /reopen and admission (positive control: the authentic one)."""
    name, vault = coherence_ops["name"], coherence_ops["vault"]
    receipt = deepcopy(coherence_ops["authentic"])
    assert receipt["restored_store_digests"] == _sealed_manifest(vault, receipt)["store_digests"], "precondition"
    mutate(vault, receipt)
    files, digest = write_signed_receipt(stack.env, vault, receipt, f"rp-{case.replace('_', '-')}")
    try:
        _observe_refused_receipt(stack, name, digest, "RESTORE_RECEIPT_INCONSISTENT", expected)
    finally:
        for f in files:
            f.unlink()
    wait_for(lambda: posture(name, LOCAL_OPS)["restore"]["receipt_digest"] == coherence_ops["authentic_digest"], 30)
    assert wait_for(lambda: _standalone_readyz(name)[0] == 200, 15)


def test_receipt_memory_branch_must_match_its_recovery_point(stack, coherence_ops, agent_module):
    """A signed receipt that is internally coherent as a no-memory-store drill, for a
    recovery point that DOES carry a memory store, skipped the tombstone replay and the
    per-item gates: refused."""
    name, vault = coherence_ops["name"], coherence_ops["vault"]
    receipt = deepcopy(coherence_ops["authentic"])
    for gate in ("watermark", "orphan_duplicate", "marking", "gcs", "deletion_resurrection",
                 "projection_drift_or_stale_deletion_epoch"):
        receipt["recovery_gate"][gate]["detail"] = "no memory store present"
    receipt["steps"][5]["status"] = "NOT_APPLICABLE"
    receipt.update(replayed_event_ids=[], replay_digest=None, restored_scope_digest=None)
    assert agent_module.receipt_inconsistencies(receipt, helm_profile()) == [], "coherent on its own"
    files, digest = write_signed_receipt(stack.env, vault, receipt, "memory-branch")
    try:
        _observe_refused_receipt(stack, name, digest, "RESTORE_RECEIPT_INCONSISTENT", "memory:manifest_mismatch")
    finally:
        for f in files:
            f.unlink()
    wait_for(lambda: posture(name, LOCAL_OPS)["restore"]["receipt_digest"] == coherence_ops["authentic_digest"], 30)


@pytest.mark.parametrize("case,mutate,expected", CHECKPOINT_MUTATIONS, ids=[c[0] for c in CHECKPOINT_MUTATIONS])
def test_custodian_signed_receipt_incoherent_with_its_checkpoint_is_refused(stack, coherence_ops, case, mutate,
                                                                           expected):
    """Live agent, real custodian signature: a receipt coherent on its own whose replayed
    tombstones or deletion epochs differ from the signed checkpoint of its recovery point
    denies readiness, /reopen and admission; removing it restores the authentic receipt
    (positive control: the authentic receipt matches its checkpoint and is READY)."""
    name, vault = coherence_ops["name"], coherence_ops["vault"]
    receipt = deepcopy(coherence_ops["authentic"])
    assert receipt["replayed_event_ids"] == ["evt-del-m2", "evt-del-m4"], "precondition: authentic replay"
    mutate(receipt)
    files, digest = write_signed_receipt(stack.env, vault, receipt, f"checkpoint-{case.replace('_', '-')}")
    try:
        _observe_refused_receipt(stack, name, digest, "RESTORE_RECEIPT_INCONSISTENT", expected)
    finally:
        for f in files:
            f.unlink()
    wait_for(lambda: posture(name, LOCAL_OPS)["restore"]["receipt_digest"] == coherence_ops["authentic_digest"], 30)
    assert wait_for(lambda: _standalone_readyz(name)[0] == 200, 15)


@pytest.mark.parametrize("case,mutate,expected", BINDING_MUTATIONS, ids=[c[0] for c in BINDING_MUTATIONS])
def test_restart_under_another_release_profile_or_pins_blocks_readiness_reopen_and_admission(
        stack, case, mutate, expected):
    """Verdict OCOR-DEV-0049-02ac643eb3c7-3 VF-001: the agent restarted with a different
    release, pin set or profile keeps the signed receipt and recovery point of the
    previous one; that restore was not tested for it, so readiness, /reopen and every
    governed admission are denied."""
    profile = deepcopy(helm_profile())
    mutate(profile)
    path = stack.work / f"restart-{case}.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    digest = receipt_digest(stack.vault)
    name = _standalone_ops(stack, stack.vault, f"{stack.ops_project}_site", profile_path=path)
    try:
        _, ready = wait_for(lambda: scanned(r := _standalone_readyz(name)) and r, 60)
        assert ready["reasons"] == [f"RESTORE_{expected}"], "dependencies are up; only the release fence blocks"
        state = posture(name, LOCAL_OPS)
        assert state["restore"] == {"reason_code": f"RESTORE_{expected}", "receipt_digest": None,
                                    "detail": ["recovery_point"]}
        status, body = reopen(name, stack.operator_token, digest, base=LOCAL_OPS)
        assert (status, body["reason_code"]) == (409, f"REOPEN_REFUSED:RESTORE_{expected}"), body
        assert_admission(name, admitted=[], fault="restore_not_verified", base=LOCAL_OPS)
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, check=False)


def test_restart_under_the_tested_release_is_ready_and_reopenable(stack):
    """Positive counterpart of VF-001: a restart with exactly the release, profile and pins
    of the tested restore verifies the same receipt and can be reopened."""
    path = stack.work / "restart-same.json"
    path.write_text(json.dumps(helm_profile()), encoding="utf-8")
    name = _standalone_ops(stack, stack.vault, f"{stack.ops_project}_site", profile_path=path)
    try:
        wait_for(lambda: _standalone_readyz(name)[0] == 200, 60, message="same release must be READY")
        assert posture(name, LOCAL_OPS)["restore"] == {"reason_code": "RESTORE_TESTED",
                                                       "receipt_digest": receipt_digest(stack.vault), "detail": []}
        governed_reopen(stack, name, stack.vault, base=LOCAL_OPS)
        assert_admission(name, admitted=OPERATION_CLASSES, base=LOCAL_OPS)
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, check=False)


def test_new_release_is_ready_only_after_its_own_backup_and_tested_restore(stack):
    """Release fence end to end on Compose: under a new release the old receipt is refused,
    the old recovery point is not restored (compatibility before restore), and only a
    backup and recovery-gate pass of the new release make the same process READY."""
    load_drill_fixture(stack.env, consistent=True)
    vault = _copy_vault(stack, "new-release")
    mutate = _set("profile.release", "ocor-poc-0.2.1-drill")
    profile = deepcopy(helm_profile())
    mutate(profile)
    path = stack.work / "new-release.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    override = profile_override(stack.work, mutate)
    receipts_before = sorted((vault / "restore-receipts").glob("*.json"))
    name = _standalone_ops(stack, vault, f"{stack.ops_project}_site", profile_path=path)
    try:
        _, ready = wait_for(lambda: scanned(r := _standalone_readyz(name)) and r, 60)
        assert ready["reasons"] == ["RESTORE_RELEASE_MISMATCH"]
        project = f"ocor-poc-restore-{uuid.uuid4().hex[:6]}"
        code, logs = stack.run_stage(project, "restore-drill", "ocor-restore-prepare", vault=vault,
                                     extra_files=(override,))
        stack.down(project)
        assert code == EXIT_VERIFY and "RELEASE_MISMATCH" in logs, logs
        assert sorted((vault / "restore-receipts").glob("*.json")) == receipts_before, "nothing restored"
        project = f"ocor-poc-backup-{uuid.uuid4().hex[:6]}"
        code, logs = stack.run_stage(project, "backup", "ocor-backup-seal", vault=vault, extra_files=(override,))
        stack.down(project)
        assert code == 0, logs
        project = f"ocor-poc-restore-{uuid.uuid4().hex[:6]}"
        code, logs = stack.run_stage(project, "restore-drill", "ocor-restore-finalize", vault=vault,
                                     extra_files=(override,))
        stack.down(project)
        assert code == 0, logs
        receipt = latest_receipt(vault)
        assert receipt["outcome"] == "PASSED"
        assert receipt["release_binding"] == {
            "release": "ocor-poc-0.2.1-drill", "profile_digest": profile_digest(profile),
            "image_pins_digest": hashlib.sha256(canonical_bytes(profile["images"]["pins"])).hexdigest()}
        manifest = json.loads((vault / "recovery-points" / receipt["recovery_point"] / "manifest.json").read_bytes())
        assert (manifest["release"], manifest["profile_digest"]) == ("ocor-poc-0.2.1-drill", profile_digest(profile))
        wait_for(lambda: _standalone_readyz(name)[0] == 200, 60, message="READY after the new release's own restore")
        governed_reopen(stack, name, vault, base=LOCAL_OPS)
        assert_admission(name, admitted=OPERATION_CLASSES, base=LOCAL_OPS)
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, check=False)


@pytest.fixture(scope="module")
def tuned(stack):
    """A profile with 2 s scan intervals and its OWN tested restore: the release fence
    binds a receipt to the exact profile digest, so a faster-scanning agent needs a
    recovery point and a recovery-gate pass sealed under that profile."""
    def fast_scan(p: dict) -> None:
        p["observability"]["probeIntervalSeconds"] = 2
        p["observability"]["driftScanIntervalSeconds"] = 2

    profile = deepcopy(helm_profile())
    fast_scan(profile)
    override = profile_override(stack.work, fast_scan)
    vault = stack.work / "vault-tuned"
    vault.mkdir()
    load_drill_fixture(stack.env, consistent=True)
    for stage, service in (("backup", "ocor-backup-seal"), ("restore-drill", "ocor-restore-finalize")):
        project = f"ocor-poc-tuned-{uuid.uuid4().hex[:6]}"
        code, logs = stack.run_stage(project, stage, service, vault=vault, extra_files=(override,))
        stack.down(project)
        assert code == 0, logs
    assert latest_receipt(vault)["release_binding"]["profile_digest"] == profile_digest(profile)
    return {"profile": profile, "vault": vault}


def test_inconsistent_deletion_journal_blocks_materialisation_and_readiness(stack):
    """Stale deletion epoch: m4 is deleted in metadata but its tombstone is missing
    from the journal; the restored index would resurrect it."""
    vault = stack.work / "vault-inconsistent"
    vault.mkdir()
    load_drill_fixture(stack.env, consistent=False)
    try:
        project = f"ocor-poc-backup-{uuid.uuid4().hex[:6]}"
        code, logs = stack.run_stage(project, "backup", "ocor-backup-seal", vault=vault)
        stack.down(project)
        assert code == 0, logs
        project = f"ocor-poc-restore-{uuid.uuid4().hex[:6]}"
        code, logs = stack.run_stage(project, "restore-drill", "ocor-restore-finalize", vault=vault)
        stack.down(project)
        assert code == EXIT_GATE, logs
        receipt = latest_receipt(vault)
        assert receipt["outcome"] == "FAILED"
        assert receipt["materialisation"] == "BLOCKED"
        assert receipt["recovery_gate"]["deletion_resurrection"] == {"pass": False, "detail": ["m4"]}
        assert receipt["recovery_gate"]["projection_drift_or_stale_deletion_epoch"]["pass"] is False
        assert receipt["recovery_gate"]["sample_semantic_digest"]["pass"] is True
        name = _standalone_ops(stack, vault, f"{stack.ops_project}_site")
        try:
            _, ready = wait_for(lambda: scanned(r := _standalone_readyz(name)) and r, 30)
            assert ready["reasons"] == ["RESTORE_FAILED"]
            assert_admission(name, admitted=[], fault="restore_not_verified", base=LOCAL_OPS)
        finally:
            subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, check=False)
    finally:
        load_drill_fixture(stack.env, consistent=True)


SCOPE_MUTATIONS = [
    # case id, payload change of item m1 (authoritative metadata: tenant-a / [c1]), failing gate, detail keys
    ("cross_tenant_scope", {"tenant_id": "tenant-b", "compartments": ["c2"],
                            "governed_context_digest": drill_gcs("tenant-b", "c2")},
     "gcs", ["compartment_mismatch", "gcs_digest_mismatch", "tenant_mismatch"]),
    ("compartment_only", {"compartments": ["c2"]}, "gcs", ["compartment_mismatch"]),
    ("marking_only", {"classification_marking_ref": _drill_digest("marking", "OTHER")}, "marking",
     ["marking_mismatch"]),
    ("gcs_binding_only", {"governed_context_digest": drill_gcs("tenant-a", "c9")}, "gcs", ["gcs_digest_mismatch"]),
]


@pytest.mark.parametrize("case,change,gate,details", SCOPE_MUTATIONS, ids=[c[0] for c in SCOPE_MUTATIONS])
def test_restore_scope_mismatch_blocks_materialisation(stack, case, change, gate, details):
    """Verdict OCOR-DEV-0049-7fd4f7728801-2 VF-003: an item of the restored projection
    whose tenant, compartments, marking or GCS binding differs from the authoritative
    metadata fails the recovery gate, blocks materialisation and readiness."""
    vault = stack.work / f"vault-scope-{case}"
    vault.mkdir()
    load_drill_fixture(stack.env, consistent=True)
    try:
        result = qdrant_call("POST", "/collections/ocor_poc_drill_memory/points/payload?wait=true",
                             {"payload": change, "points": [memory_point_id("m1")]})
        assert result.get("status") == "ok", result
        project = f"ocor-poc-backup-{uuid.uuid4().hex[:6]}"
        code, logs = stack.run_stage(project, "backup", "ocor-backup-seal", vault=vault)
        stack.down(project)
        assert code == 0, logs
        project = f"ocor-poc-restore-{uuid.uuid4().hex[:6]}"
        code, logs = stack.run_stage_detached(project, "restore-drill", "ocor-restore-finalize", vault=vault)
        try:
            assert code == EXIT_GATE, logs
            # Observed on the restored service itself: the mismatch is really there, and only on m1.
            restored = restored_payloads(project)
            assert all(restored["m1"][k] == v for k, v in change.items()), restored["m1"]
            for item in ("m3", "m5"):
                tenant, compartment = drill_scope(int(item[1:]))
                assert restored[item]["governed_context_digest"] == drill_gcs(tenant, compartment)
        finally:
            stack.down(project)
        receipt = latest_receipt(vault)
        assert (receipt["outcome"], receipt["materialisation"]) == ("FAILED", "BLOCKED")
        assert receipt["quarantined_items"] == ["m1"]
        assert receipt["recovery_gate"][gate]["pass"] is False
        failing = sorted(k for k, v in receipt["recovery_gate"][gate]["detail"].items() if v)
        assert failing == details and all(receipt["recovery_gate"][gate]["detail"][k] == ["m1"] for k in details)
        others = [name for name in RECOVERY_GATE if name != gate]
        assert all(receipt["recovery_gate"][name]["pass"] for name in others), receipt["recovery_gate"]
        step = next(s for s in receipt["steps"] if s["step"] == "require_human_authorization_to_reopen_mutative")
        assert step["status"] == "BLOCKED"
        name = _standalone_ops(stack, vault, f"{stack.ops_project}_site")
        try:
            _, ready = wait_for(lambda: scanned(r := _standalone_readyz(name)) and r, 30)
            assert ready["reasons"] == ["RESTORE_FAILED"]
            assert_admission(name, admitted=[], fault="restore_not_verified", base=LOCAL_OPS)
        finally:
            subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, check=False)
    finally:
        load_drill_fixture(stack.env, consistent=True)


@pytest.mark.parametrize("limit,value,observed", [("itemCount", 2, 5), ("embeddingDimensions", 3, 4)])
def test_quota_exceeded_backpressures_without_semantic_downgrade(stack, limit, value, observed):
    vault = stack.work / f"vault-quota-{limit}"
    vault.mkdir()
    override = profile_override(stack.work, _set(f"resourceLimits.{limit}", value))
    project = f"ocor-poc-backup-{uuid.uuid4().hex[:6]}"
    code, logs = stack.run_stage(project, "backup", "ocor-backup-seal", vault=vault, extra_files=(override,))
    stack.down(project)
    assert code == EXIT_BACKPRESSURE, logs
    record = next(json.loads(line.split("|", 1)[1]) for line in logs.splitlines()
                  if "QUOTA_BACKPRESSURE" in line and "|" in line)
    assert (record["limit"], record["observed"], record["semantic_downgrade"]) == (limit, observed, False)
    assert not (vault / "recovery-points").exists(), "no partial (downgraded) recovery point is written"


FAULTS = [
    # victim, fault class, operation class that must be denied, operation class still admitted
    ("qdrant", "projection_lag_or_failure", "high_impact", "mutative"),
    ("opa", "idp_or_policy_engine_unavailable", "governed_new", "read"),
    ("postgresql", "audit_append_unavailable", "mutative", "read"),
    ("kafka", "broker_unavailable", None, "mutative"),
    ("spire-server", "idp_or_policy_engine_unavailable", "dispatch", "read"),
]


@pytest.mark.parametrize("victim,fault,denied,admitted", FAULTS, ids=[f[0] for f in FAULTS])
def test_dependency_fault_blocks_readiness_and_degrades_posture(stack, victim, fault, denied, admitted):
    container = f"ocor-bootstrap-{victim}-1"
    wait_for(lambda: readyz(stack.ops)[0] == 200, 60, message="precondition: READY before the fault")
    before = metrics(stack.ops).get(
        f'ocor_dependency_probe_errors_total{{dependency="{victim}",reason_code="DEPENDENCY_DOWN"}}', 0.0)
    subprocess.run(["docker", "pause", container], check=True, capture_output=True)
    try:
        status, ready = wait_for(lambda: (r := readyz(stack.ops))[0] == 503 and r, 30,
                                 message=f"readiness must block while {victim} is paused")
        assert f"DEPENDENCY_DOWN:{victim}" in ready["reasons"]
        _, posture = http_from(stack.ops, "http://ocor-ops:8080/posture")
        posture = json.loads(posture)
        assert fault in posture["faults"]
        if denied:
            code, body = http_from(stack.ops, f"http://ocor-ops:8080/admit?class={denied}")
            assert (code, json.loads(body)["decision"]) == (503, "DENY")
        code, body = http_from(stack.ops, f"http://ocor-ops:8080/admit?class={admitted}")
        assert (code, json.loads(body)["decision"]) == (200, "ADMIT")
        if victim == "kafka":
            assert posture["projection_freshness_claim"] is False
        if victim == "qdrant":
            assert posture["consistency"] == "PROJECTION_NOT_READY"
        m = metrics(stack.ops)
        assert m[f'ocor_dependency_up{{dependency="{victim}"}}'] == 0.0
        assert m[f'ocor_dependency_probe_errors_total{{dependency="{victim}",reason_code="DEPENDENCY_DOWN"}}'] > before
        assert m[f'ocor_safe_degraded_fault_active{{fault="{fault}"}}'] == 1.0
        _, traces = http_from(stack.ops, "http://ocor-ops:8080/traces")
        spans = [s for s in json.loads(traces)["spans"] if s.get("dependency") == victim
                 and s["reason_code"] == "DEPENDENCY_DOWN"]
        assert spans and spans[-1]["fault_class"] == fault and spans[-1]["causation_id"]
    finally:
        subprocess.run(["docker", "unpause", container], check=False, capture_output=True)
    wait_for(lambda: readyz(stack.ops)[0] == 200, 60, message=f"readiness must recover after {victim}")
    _, posture = http_from(stack.ops, "http://ocor-ops:8080/posture")
    assert json.loads(posture)["faults"] == []


def test_emergency_stop_denies_mutative_capabilities_within_10_seconds(stack):
    code, _ = http_from(stack.ops, "http://ocor-ops:8080/emergency-stop", "POST",
                        {"Authorization": "Bearer wrong-token"})
    assert code == 401
    assert http_from(stack.ops, "http://ocor-ops:8080/admit?class=mutative")[0] == 200
    started = time.monotonic()
    code, body = http_from(stack.ops, "http://ocor-ops:8080/emergency-stop", "POST",
                           {"Authorization": f"Bearer {stack.operator_token}"})
    assert code == 200 and json.loads(body)["reason_code"] == "EMERGENCY_STOP_ACTIVE"
    wait_for(lambda: http_from(stack.ops, "http://ocor-ops:8080/admit?class=mutative")[0] == 503, 10, 0.2)
    assert time.monotonic() - started <= 10.0
    assert http_from(stack.ops, "http://ocor-ops:8080/admit?class=read")[0] == 200
    code, body = http_from(stack.ops, "http://ocor-ops:8080/emergency-stop/clear", "POST",
                           {"Authorization": f"Bearer {stack.operator_token}"})
    assert code == 200 and json.loads(body)["reason_code"] == "EMERGENCY_STOP_CLEARED_BY_HUMAN"
    assert http_from(stack.ops, "http://ocor-ops:8080/admit?class=mutative")[0] == 200


def test_release_drift_blocks_readiness_and_mutative_commands(stack, tuned):
    profile = deepcopy(tuned["profile"])
    path = stack.work / "drift-profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    name = _standalone_ops(stack, tuned["vault"], f"{stack.ops_project}_site", profile_path=path)
    try:
        wait_for(lambda: _standalone_readyz(name)[0] == 200, 30, message="standalone ops must be READY")
        governed_reopen(stack, name, tuned["vault"], base=LOCAL_OPS)
        assert_admission(name, admitted=OPERATION_CLASSES, base=LOCAL_OPS)  # positive control
        changed = deepcopy(profile)
        changed["profile"]["release"] = "ocor-poc-unapproved"
        path.write_text(json.dumps(changed), encoding="utf-8")
        _, ready = wait_for(lambda: (r := _standalone_readyz(name))[0] == 503 and r, 10,
                            message="drift must be detected within the scan interval")
        assert ready["reasons"] == ["RELEASE_DRIFT"]
        # Release mismatch blocks mutative commands; authorized reads stay admitted.
        assert_admission(name, admitted=["exact_consistency_read", "governed_new", "read"], fault="release_mismatch",
                         base=LOCAL_OPS)
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, check=False)


def connect_matrix(container: str, pairs: list[tuple[str, int]]) -> dict[str, str]:
    code = (
        "import json,socket\n"
        f"pairs={pairs!r}\nout={{}}\n"
        "for h,p in pairs:\n"
        "    try:\n"
        "        socket.create_connection((h,p),4).close(); out[f'{h}:{p}']='CONNECTED'\n"
        "    except socket.gaierror:\n"
        "        out[f'{h}:{p}']='DNS_DENIED'\n"
        "    except OSError as e:\n"
        "        out[f'{h}:{p}']='DENIED:'+type(e).__name__\n"
        "print(json.dumps(out))\n"
    )
    result = subprocess.run(["docker", "exec", container, "python3", "-c", code], capture_output=True, text=True,
                            check=False, timeout=600)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_default_deny_admits_only_allowlisted_destination_port_pairs(stack):
    """Verdict OCOR-DEV-0049-7fd4f7728801-2 VF-002: every allowed (host, port) pair
    connects and every other combination of the same hosts and ports is refused,
    including postgresql:8181 which previously reached the real OPA."""
    inspect = json.loads(subprocess.run(["docker", "network", "inspect", f"{stack.ops_project}_site"],
                                        capture_output=True, text=True, check=True).stdout)
    assert inspect[0]["Internal"] is True
    flows = [(f["host"], f["port"]) for f in helm_profile()["isolation"]["allowedFlows"]]
    hosts, ports = [h for h, _ in flows], [p for _, p in flows]
    resolved = subprocess.run(["docker", "exec", stack.ops, "python3", "-c",
                               f"import socket,json; print(json.dumps([socket.gethostbyname(h) for h in {hosts!r}]))"],
                              capture_output=True, text=True, check=True).stdout
    assert len(set(json.loads(resolved))) == len(hosts), "every destination has its own address"
    matrix = connect_matrix(stack.ops, [(h, p) for h in hosts for p in ports])
    for host in hosts:
        for port in ports:
            outcome = matrix[f"{host}:{port}"]
            if (host, port) in flows:
                assert outcome == "CONNECTED", (host, port)
            else:
                assert outcome.startswith("DENIED"), (host, port, outcome)
    assert matrix["opa:8181"] == "CONNECTED" and matrix["postgresql:8181"].startswith("DENIED")
    assert matrix["qdrant:5432"].startswith("DENIED") and matrix["postgresql:5432"] == "CONNECTED"
    assert connect_from(stack.ops, "1.1.1.1", 443).startswith("DENIED")
    assert connect_from(stack.ops, "registry.npmjs.org", 443) == "DNS_DENIED"
    assert connect_from(stack.ops, "ocor-bootstrap-postgresql-1", 5432) == "DNS_DENIED"
    assert connect_from(stack.ops, "postgresql", 22).startswith("DENIED"), "port outside the allowlist"
    assert connect_from(stack.ops, "keycloak", 8080).startswith("DENIED"), "admin port outside the allowlist"
    # Positive control: the same probe succeeds where egress is NOT denied, so the
    # denial above is produced by the profile, not by an offline host.
    control = subprocess.run(["docker", "run", "--rm", "--network", BOOTSTRAP_NETWORK, OPS_IMAGE, "python3", "-c",
                              "import socket; socket.create_connection(('1.1.1.1', 443), 5).close(); print('CONNECTED')"],
                             capture_output=True, text=True, check=False)
    assert control.stdout.strip() == "CONNECTED", "positive control failed: host egress unavailable"


def test_open_public_egress_blocks_readiness(stack):
    """The agent placed on a network WITH public egress must refuse readiness."""
    name = _standalone_ops(stack, stack.vault, BOOTSTRAP_NETWORK)
    try:
        _, ready = wait_for(lambda: scanned(r := _standalone_readyz(name)) and r, 30)
        assert ready["reasons"] == ["PUBLIC_EGRESS_OPEN"], "dependencies are up; only egress must block"
        governed_reopen(stack, name, stack.vault, base=LOCAL_OPS)  # even a reopened path stays closed
        assert_admission(name, admitted=[], fault="isolation_breach", base=LOCAL_OPS)
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, check=False)


def test_scanner_failure_denies_every_admission_until_the_scan_recovers(stack, tuned):
    """Verdict OCOR-DEV-0049-7fd4f7728801-2 VF-001: with the security scan failing
    (unreadable profile) no operation class is admitted; admission returns once the
    scan succeeds again."""
    profile = deepcopy(tuned["profile"])
    path = stack.work / "scanner-profile.json"
    original = json.dumps(profile)
    path.write_text(original, encoding="utf-8")
    name = _standalone_ops(stack, tuned["vault"], f"{stack.ops_project}_site", profile_path=path)
    try:
        wait_for(lambda: _standalone_readyz(name)[0] == 200, 30, message="standalone ops must be READY")
        governed_reopen(stack, name, tuned["vault"], base=LOCAL_OPS)
        assert_admission(name, admitted=OPERATION_CLASSES, base=LOCAL_OPS)  # positive control
        path.write_text("{broken", encoding="utf-8")
        _, ready = wait_for(lambda: (r := _standalone_readyz(name))[1]["reasons"] == ["SCANNER_ERROR"] and r, 15,
                            message="scanner failure must be detected")
        assert_admission(name, admitted=[], fault="security_scan_unavailable", base=LOCAL_OPS)
        assert "security_scan_unavailable" in posture(name, LOCAL_OPS)["faults"]
        path.write_text(original, encoding="utf-8")
        wait_for(lambda: _standalone_readyz(name)[0] == 200, 15, message="readiness must recover with the scan")
        assert_admission(name, admitted=OPERATION_CLASSES, base=LOCAL_OPS)
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, check=False)


def test_public_network_dependency_prevents_the_process_from_starting(stack):
    profile = deepcopy(helm_profile())
    profile["images"]["publicNetworkDependencyAtRuntime"] = True
    path = stack.work / "public-dependency.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", f"{stack.ops_project}_site",
         "-v", f"{stack.work / 'agent.py'}:/opt/ocor/ocor_ops_agent.py:ro", "-v", f"{path}:/etc/ocor/profile.json:ro",
         OPS_IMAGE, "python3", "/opt/ocor/ocor_ops_agent.py", "serve", "--profile", "/etc/ocor/profile.json"],
        capture_output=True, text=True, check=False, timeout=60)
    assert result.returncode == EXIT_CONFIG
    assert "public-network runtime dependency blocks startup" in result.stderr


OPA_HOST_URL = "http://127.0.0.1:8181"


def opa_inventory() -> tuple[list[dict], int]:
    raw = urllib.request.urlopen(f"{OPA_HOST_URL}/v1/policies", timeout=60).read()
    return json.loads(raw)["result"], len(raw)


def opa_module(package: str, source: str | None) -> None:
    """Install (or delete) one rule-free module in a package owned by this test: it adds
    no rule, so no authorization decision of the stack changes."""
    request = urllib.request.Request(f"{OPA_HOST_URL}/v1/policies/{package}", method="DELETE" if source is None
                                     else "PUT", data=None if source is None else source.encode(),
                                     headers={"Content-Type": "text/plain"})
    assert urllib.request.urlopen(request, timeout=60).status == 200


def policy_spans(container: str) -> list[dict]:
    logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True, check=True).stdout
    return [r for r in (json.loads(line) for line in logs.splitlines() if line.startswith("{"))
            if r.get("operation") == "span" and r["span"]["operation"] == "policy_inventory"]


def test_policy_digest_in_logs_and_traces_covers_the_complete_opa_inventory(stack):
    """Verdict OCOR-DEV-0049-aefabf91777d-4 VF-004 on the real OPA: the digest carried by
    the log record and the trace span is the exact digest of the COMPLETE inventory, also
    above the former 4096-byte cut; an inventory over the explicit bound yields no digest
    (reason code, metric, span) and never the digest of an empty set."""
    package = f"ocor_test_0049_inventory_{uuid.uuid4().hex[:8]}"
    inventory, _ = opa_inventory()
    base, base_ids = policy_oracle(inventory), {p["id"] for p in inventory}
    assert inventory and base != EMPTY_SET_DIGEST
    wait_for(lambda: posture(stack.ops)["policy"] == {"digest": base, "reason_code": "POLICY_DIGEST_OK"}, 30,
             message="baseline policy digest")
    try:
        opa_module(package, f"package {package}\n" + "# rule-free padding line\n" * 1000)
        inventory, size = opa_inventory()
        grown = policy_oracle(inventory)
        # Precondition relative to the baseline (a freshly bootstrapped stack holds only the
        # governed bootstrap policy): exactly the test module was added, above the former cut.
        assert size > 4096 and {p["id"] for p in inventory} == base_ids | {package}
        assert grown not in (base, EMPTY_SET_DIGEST)
        wait_for(lambda: posture(stack.ops)["policy"] == {"digest": grown, "reason_code": "POLICY_DIGEST_OK"}, 30,
                 message="digest of the grown inventory")
        record = wait_for(lambda: [r for r in policy_spans(stack.ops) if r["policy_digest"] == grown], 30)[-1]
        assert record["span"]["policy_bundle_digest"] == grown and record["reason_code"] == "POLICY_DIGEST_OK"
        status, body = http_from(stack.ops, "http://ocor-ops:8080/traces")
        assert any(s["operation"] == "policy_inventory" and s["policy_bundle_digest"] == grown
                   for s in json.loads(body)["spans"])
        assert metrics(stack.ops)["ocor_policy_digest_available"] == 1.0

        opa_module(package, f"package {package}\n" + ("# " + "x" * 1000 + "\n") * 2500)
        _, size = opa_inventory()
        assert size > 4 * 1024 * 1024, "precondition: inventory above the explicit bound"
        wait_for(lambda: posture(stack.ops)["policy"] == {"digest": None,
                                                          "reason_code": "POLICY_INVENTORY_TOO_LARGE"}, 30,
                 message="oversized inventory yields no digest")
        record = wait_for(lambda: [r for r in policy_spans(stack.ops)
                                   if r["reason_code"] == "POLICY_INVENTORY_TOO_LARGE"], 30)[-1]
        assert record["policy_digest"] is None and record["span"]["policy_bundle_digest"] is None
        assert record["span"]["status"] == "ERROR"
        m = metrics(stack.ops)
        assert m["ocor_policy_digest_available"] == 0.0
        assert m['ocor_policy_digest_errors_total{reason_code="POLICY_INVENTORY_TOO_LARGE"}'] >= 1.0
    finally:
        opa_module(package, None)
    wait_for(lambda: posture(stack.ops)["policy"] == {"digest": base, "reason_code": "POLICY_DIGEST_OK"}, 30,
             message="baseline digest after teardown")
    logs = subprocess.run(["docker", "logs", stack.ops], capture_output=True, text=True, check=True).stdout
    assert EMPTY_SET_DIGEST not in logs, "the digest of an empty inventory is never fabricated"


def test_compose_containers_run_the_governed_pins(stack):
    """VF-001 on Compose: every running workload container of the profile runs the image of
    its governed pin (same image id as the digest-pinned reference)."""
    pins = helm_profile()["images"]["pins"]
    ps = stack.compose(stack.ops_project, "--profile", "observability", "ps", "--format", "json")
    assert ps.returncode == 0, ps.stderr
    rows = [json.loads(line) for line in ps.stdout.splitlines() if line.strip()]
    assert {r["Service"] for r in rows} >= {"ocor-ops", "ocor-relay-opa"}
    for row in rows:
        config_image, image_id = subprocess.run(["docker", "inspect", "-f", "{{.Config.Image}} {{.Image}}",
                                                 row["Name"]], capture_output=True, text=True,
                                                check=True).stdout.split()
        pin = pins[compose_image_role(row["Service"])]
        assert config_image == pin, (row["Service"], config_image)
        assert image_id == subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", pin], capture_output=True,
                                          text=True, check=True).stdout.strip()


def test_logs_and_traces_carry_governed_fields_and_no_secrets(stack):
    logs = subprocess.run(["docker", "logs", stack.ops], capture_output=True, text=True, check=True).stdout
    records = [json.loads(line) for line in logs.splitlines() if line.startswith("{")]
    assert records
    for record in records:
        assert set(LOG_FIELDS) <= set(record), record
        assert record["classification_marking_ref"] == "SYNTHETIC-UNCLASSIFIED"
    assert any(r["reason_code"] == "DEPENDENCY_DOWN" for r in records), "fault telemetry observed"
    assert any(r["reason_code"] == "READY" for r in records), "positive event telemetry observed"
    assert any(r["policy_digest"] for r in records), "policy digest read from the real OPA"
    spans = [r["span"] for r in records if r["operation"] == "span"]
    assert all(s["trace_id"] and s["span_id"] and s["correlation_id"] for s in spans)
    everything = logs
    for project in stack.projects:
        everything += stack.compose(project, "--profile", "full", "--profile", "restore-drill", "logs").stdout
    for secret in (stack.env["OCOR_LOCAL_OPENBAO_TOKEN"], stack.env["OCOR_LOCAL_POSTGRES_PASSWORD"],
                   stack.operator_token):
        assert secret not in everything


# --------------------------------------------------------------------------- Helm on Kubernetes


KIND_CLUSTER = "ocor-poc"
KIND_NODE_IMAGE = ("kindest/node:v1.33.1@sha256:"
                   "050072256b9a903bd914c0b2866828150cb229cea0efe5892e2b644d5dd3b34f")
KIND_VAULT_ROOT = Path.home() / ".ocor-poc" / "kind-vault"


def kubectl(*args: str, check: bool = True, timeout: int = 180) -> subprocess.CompletedProcess:
    result = subprocess.run([tool("kubectl"), "--context", f"kind-{KIND_CLUSTER}", *args], capture_output=True,
                            text=True, check=False, timeout=timeout)
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope="module")
def kind(stack):
    """Disposable Kubernetes (DEC-211): kind node with the vault mounted from the
    host (outside the cluster fault domain) and attached to the bootstrap network."""
    clusters = subprocess.run([tool("kind"), "get", "clusters"], capture_output=True, text=True, check=False)
    created = KIND_CLUSTER not in clusters.stdout.split()
    if created:
        KIND_VAULT_ROOT.mkdir(parents=True, exist_ok=True)
        config = stack.work / "kind.yaml"
        config.write_text(yaml.safe_dump({
            "kind": "Cluster", "apiVersion": "kind.x-k8s.io/v1alpha4",
            "nodes": [{"role": "control-plane", "image": KIND_NODE_IMAGE,
                       "extraMounts": [{"hostPath": str(KIND_VAULT_ROOT), "containerPath": "/ocor-vault"}]}]}))
        result = subprocess.run([tool("kind"), "create", "cluster", "--name", KIND_CLUSTER, "--config", str(config),
                                 "--wait", "180s"], capture_output=True, text=True, check=False, timeout=600)
        assert result.returncode == 0, result.stderr
    node = f"{KIND_CLUSTER}-control-plane"
    subprocess.run(["docker", "network", "connect", BOOTSTRAP_NETWORK, node], capture_output=True, check=False)
    images = set(helm_profile()["images"]["pins"].values()) | {OTHER_OPS_IMAGE}
    for image in sorted(images):
        for attempt in range(3):
            if subprocess.run(["docker", "exec", node, "crictl", "inspecti", image], capture_output=True).returncode == 0:
                break
            subprocess.run(["docker", "exec", node, "crictl", "pull", image], capture_output=True, timeout=900)
            time.sleep(attempt * 5)
        assert subprocess.run(["docker", "exec", node, "crictl", "inspecti", image],
                              capture_output=True).returncode == 0, f"image {image} unavailable in kind"
    run = uuid.uuid4().hex[:6]
    namespace = f"ocor-poc-{run}"
    vault = KIND_VAULT_ROOT / run
    vault.mkdir(parents=True)
    bootstrap = json.loads(subprocess.run(["docker", "network", "inspect", BOOTSTRAP_NETWORK], capture_output=True,
                                          text=True, check=True).stdout)[0]
    aliases = {}
    for container in bootstrap["Containers"].values():
        match = re.fullmatch(r"ocor-bootstrap-(.+)-1", container["Name"])
        if match and match.group(1) in BOOTSTRAP_SERVICES:
            aliases[match.group(1)] = container["IPv4Address"].split("/")[0]
    kubectl("create", "namespace", namespace)
    kubectl("-n", namespace, "create", "secret", "generic", "ocor-poc-ops",
            f"--from-literal=OCOR_OPENBAO_TOKEN={stack.env['OCOR_LOCAL_OPENBAO_TOKEN']}",
            f"--from-literal=OCOR_OPS_OPERATOR_TOKEN={stack.operator_token}",
            f"--from-literal=PGPASSWORD={stack.env['OCOR_LOCAL_POSTGRES_PASSWORD']}")
    storage = stack.work / f"vault-{run}.yaml"
    storage.write_text(yaml.safe_dump_all([
        {"apiVersion": "v1", "kind": "PersistentVolume", "metadata": {"name": namespace},
         "spec": {"capacity": {"storage": "2Gi"}, "accessModes": ["ReadWriteOnce"], "storageClassName": "ocor-vault",
                  "persistentVolumeReclaimPolicy": "Retain", "hostPath": {"path": f"/ocor-vault/{run}"},
                  "claimRef": {"namespace": namespace, "name": "ocor-poc-vault"}}},
        {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": "ocor-poc-vault",
                                                                           "namespace": namespace},
         "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": "ocor-vault", "volumeName": namespace,
                  "resources": {"requests": {"storage": "2Gi"}}}}]))
    kubectl("apply", "-f", str(storage))
    values = stack.work / f"values-{run}.yaml"
    values.write_text(yaml.safe_dump({"operational": {
        "secretName": "ocor-poc-ops", "vault": {"existingClaim": "ocor-poc-vault"},
        "runAsUser": os.getuid(),
        "hostAliases": [{"ip": ip, "hostnames": [name]} for name, ip in sorted(aliases.items())]}}))
    ctx = {"namespace": namespace, "vault": vault, "values": values, "release": "ocor-poc"}
    try:
        result = subprocess.run([tool("helm"), "--kube-context", f"kind-{KIND_CLUSTER}", "install", "ocor-poc",
                                 str(CHART_DIR), "-n", namespace, "-f", str(values)],
                                capture_output=True, text=True, check=False, timeout=300)
        assert result.returncode == 0, result.stderr
        yield ctx
    finally:
        kubectl("delete", "namespace", namespace, "--wait=true", check=False, timeout=300)
        kubectl("delete", "pv", namespace, check=False)
        if created and os.environ.get("OCOR_KEEP_KIND") != "1":
            subprocess.run([tool("kind"), "delete", "cluster", "--name", KIND_CLUSTER], capture_output=True,
                           check=False, timeout=300)
        make_writable(vault)
        shutil.rmtree(vault, ignore_errors=True)


def pod_name(ns: str, component: str) -> str:
    return kubectl("-n", ns, "get", "pod", "-l", f"app.kubernetes.io/component={component}",
                   "-o", "jsonpath={.items[0].metadata.name}").stdout


def pod_ready(ns: str, component: str) -> bool:
    out = kubectl("-n", ns, "get", "pod", "-l", f"app.kubernetes.io/component={component}", "-o",
                  "jsonpath={.items[0].status.conditions[?(@.type=='Ready')].status}", check=False).stdout
    return out == "True"


def pod_python(ns: str, pod: str, code: str) -> str:
    return kubectl("-n", ns, "exec", pod, "--", "python3", "-c", code).stdout.strip()


def run_job(ns: str, args: list[str], name: str, timeout: int = 600) -> tuple[str, str]:
    kubectl("-n", ns, *args)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = kubectl("-n", ns, "get", "job", name, "-o",
                         "jsonpath={.status.succeeded}/{.status.failed}", check=False).stdout
        if status.startswith("1/") or status.endswith("/1"):
            logs = kubectl("-n", ns, "logs", f"job/{name}", "--all-containers=true", check=False).stdout
            return status, logs
        time.sleep(3)
    pytest.fail(f"job {name} did not finish")


def pods(ns: str, component: str) -> list[str]:
    out = kubectl("-n", ns, "get", "pod", "-l", f"app.kubernetes.io/component={component}",
                  "-o", "jsonpath={.items[*].metadata.name}", check=False).stdout
    return out.split()


def named_pod_ready(ns: str, pod: str) -> bool:
    return kubectl("-n", ns, "get", "pod", pod, "-o", "jsonpath={.status.conditions[?(@.type=='Ready')].status}",
                   check=False).stdout == "True"


def pod_http(ns: str, pod: str, path: str, method: str = "GET", headers: dict | None = None,
             data: dict | None = None) -> tuple[int, dict]:
    payload = None if data is None else json.dumps(data).encode()
    out = pod_python(ns, pod, (
        "import json,urllib.request,urllib.error\n"
        f"r=urllib.request.Request('http://127.0.0.1:8080{path}',method={method!r},"
        f"headers={json.dumps(headers or {})},data={payload!r})\n"
        "try:\n    resp=urllib.request.urlopen(r,timeout=5); print(resp.status); print(resp.read().decode())\n"
        "except urllib.error.HTTPError as e:\n    print(e.code); print(e.read().decode())\n"
        "except OSError as e:\n    print(0); print(json.dumps({'error': type(e).__name__, 'reasons': ['UNREACHABLE']}))\n"))
    status, _, body = out.partition("\n")
    return int(status), json.loads(body)


def wait_job(ns: str, name: str, timeout: int = 600) -> tuple[dict, str]:
    def finished():
        result = kubectl("-n", ns, "get", "job", name, "-o", "json", check=False)
        if result.returncode != 0:
            return None
        status = json.loads(result.stdout)["status"]
        return status if status.get("succeeded") == 1 or status.get("failed") == 1 else None
    status = wait_for(finished, timeout, 3, f"job {name} must finish")
    logs = kubectl("-n", ns, "logs", f"job/{name}", "--all-containers=true", check=False).stdout
    if status.get("succeeded") != 1:
        logs += job_diagnostics(ns, name)
    return status, logs


def job_diagnostics(ns: str, name: str) -> str:
    """Per-container state, exit code and output of a failed job's pods, and the namespace
    events (`logs job/x --all-containers` prints nothing when a container never started)."""
    out = []
    listed = kubectl("-n", ns, "get", "pod", "-l", f"job-name={name}", "-o", "json", check=False)
    for pod in json.loads(listed.stdout or "{}").get("items", []):
        pod_name = pod["metadata"]["name"]
        for status in pod["status"].get("initContainerStatuses", []) + pod["status"].get("containerStatuses", []):
            out.append(f"--- {pod_name}/{status['name']}: {json.dumps(status.get('state'), sort_keys=True)}")
            out.append(kubectl("-n", ns, "logs", pod_name, "-c", status["name"], check=False).stdout)
    out.append(kubectl("-n", ns, "get", "events", "--sort-by=.lastTimestamp", check=False).stdout[-4000:])
    return "\n".join(out)


def sealed_point(logs: str) -> dict:
    """The recovery point the seal of THIS job wrote (its own stdout record)."""
    found = [json.loads(line) for line in logs.splitlines() if line.startswith("{")
             and set(json.loads(line)) == {"recovery_point", "manifest_sha256"}]
    assert len(found) == 1, logs
    return found[0]


def k8s_time(value: str) -> float:
    return float(calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")))


def assert_sealed(stack, vault: Path, sealed: dict, profile: dict) -> dict:
    """Correlate a job's recovery point with the external vault: content address of the
    manifest, custodian signature and release binding of the profile it ran with."""
    rp = vault / "recovery-points" / sealed["recovery_point"]
    raw = (rp / "manifest.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sealed["manifest_sha256"]
    assert transit_verify(stack.env, raw, (rp / "manifest.sig").read_text())
    manifest = json.loads(raw)
    assert manifest["recovery_point"] == sealed["recovery_point"]
    assert (manifest["release"], manifest["profile_digest"], manifest["image_pins"]) == (
        profile["profile"]["release"], profile_digest(profile), profile["images"]["pins"])
    return manifest


def helm_upgrade_run(kind, *sets: str) -> subprocess.CompletedProcess:
    args = [tool("helm"), "--kube-context", f"kind-{KIND_CLUSTER}", "upgrade", "ocor-poc", str(CHART_DIR),
            "-n", kind["namespace"], "-f", str(kind["values"])]
    for item in sets:
        args += ["--set", item]
    return subprocess.run(args, capture_output=True, text=True, check=False, timeout=300)


def helm_revision(kind) -> int:
    status = subprocess.run([tool("helm"), "--kube-context", f"kind-{KIND_CLUSTER}", "status", "ocor-poc", "-n",
                             kind["namespace"], "-o", "json"], capture_output=True, text=True, check=True)
    return int(json.loads(status.stdout)["version"])


def helm_upgrade(kind, *sets: str) -> int:
    result = helm_upgrade_run(kind, *sets)
    assert result.returncode == 0, result.stderr
    return helm_revision(kind)


CRON_PERIOD_SECONDS = 15 * 60
MANUAL_LEAD_SECONDS = 3


def test_helm_profile_on_kubernetes_backs_up_restores_and_gates_readiness(kind, stack):
    ns, vault = kind["namespace"], kind["vault"]
    profile = helm_profile()
    ops = wait_for(lambda: pod_name(kind["namespace"], "ops"), 120, 2, "ops pod scheduled")
    wait_for(lambda: kubectl("-n", ns, "get", "pod", ops, "-o", "jsonpath={.status.phase}",
                             check=False).stdout == "Running", 300, 3, "ops pod running")
    def restore_untested_probe() -> str | None:
        code = ("import urllib.request,urllib.error\ntry:\n"
                " r=urllib.request.urlopen('http://127.0.0.1:8080/readyz',timeout=5); "
                "print(r.status, r.read().decode())\n"
                "except urllib.error.HTTPError as e: print(e.code, e.read().decode())\n"
                "except OSError as e: print(type(e).__name__)\n")
        result = kubectl("-n", ns, "exec", ops, "--", "python3", "-c", code, check=False)
        if result.returncode:
            return None  # container startup is bounded by wait_for, never a PASS
        probe = result.stdout.strip()
        assert not probe.startswith("200"), "readiness admitted an untested restore"
        assert not pod_ready(ns, "ops"), "pod became Ready before a tested restore exists"
        return probe if probe.startswith("503") and "RESTORE_UNTESTED" in probe else None

    # REM-0017 verifier VF-001: Running is not a completed scan. Wait for the
    # required denial itself, never treat NOT_YET_SCANNED as the assertion.
    probe = wait_for(restore_untested_probe, 120, 2, "first completed scan denies an untested restore")
    assert probe.startswith("503") and "RESTORE_UNTESTED" in probe, probe
    assert not pod_ready(ns, "ops"), "pod must not be Ready before a tested restore exists"

    # Verdict OCOR-DEV-0049-02ac643eb3c7-3 VF-003: a manual backup launched at the tick of
    # the approved schedule runs concurrently with the scheduled one; each job's recovery
    # point is identified from its own output, never from the catalogue cardinality.
    assert kubectl("-n", ns, "get", "cronjob", "ocor-poc-backup", "-o",
                   "jsonpath={.spec.schedule}").stdout == "*/15 * * * *", "approved schedule unchanged"
    tick = (time.time() // CRON_PERIOD_SECONDS + 1) * CRON_PERIOD_SECONDS
    if tick - time.time() < MANUAL_LEAD_SECONDS + 5:
        tick += CRON_PERIOD_SECONDS
    time.sleep(max(0.0, tick - MANUAL_LEAD_SECONDS - time.time()))
    kubectl("-n", ns, "create", "job", "ocor-poc-backup-manual", "--from=cronjob/ocor-poc-backup")
    scheduled = f"ocor-poc-backup-{int(tick // 60)}"  # CronJob controller naming: scheduled minute
    wait_for(lambda: kubectl("-n", ns, "get", "job", scheduled, check=False).returncode == 0, 180, 2,
             "the CronJob must start its scheduled run at the tick")
    runs = {job: wait_job(ns, job) for job in ("ocor-poc-backup-manual", scheduled)}
    for job, (status, logs) in runs.items():
        if status.get("succeeded") != 1:
            pytest.fail(f"backup job {job} failed: {json.dumps(status, sort_keys=True)}\n{logs}")
    manual_status, scheduled_status = runs["ocor-poc-backup-manual"][0], runs[scheduled][0]
    assert k8s_time(manual_status["startTime"]) <= k8s_time(scheduled_status["completionTime"])
    assert k8s_time(scheduled_status["startTime"]) <= k8s_time(manual_status["completionTime"]), "runs overlap"
    sealed = {job: sealed_point(logs) for job, (_, logs) in runs.items()}
    assert sealed["ocor-poc-backup-manual"]["recovery_point"] != sealed[scheduled]["recovery_point"]
    for job in runs:
        assert_sealed(stack, vault, sealed[job], profile)
    manual = sealed["ocor-poc-backup-manual"]

    # Restore drill bound to the recovery point of the verified (manual) job.
    revision = helm_upgrade(kind, "operational.restoreDrill.enabled=true",
                            f"operational.restoreDrill.recoveryPoint={manual['recovery_point']}")
    status, logs = wait_job(ns, f"ocor-poc-restore-drill-{revision}")
    assert status.get("succeeded") == 1, logs
    receipt = latest_receipt(vault)
    assert receipt["outcome"] == "PASSED" and receipt["replayed_event_ids"] == ["evt-del-m2", "evt-del-m4"]
    assert (receipt["recovery_point"], receipt["manifest_digest"]) == (manual["recovery_point"],
                                                                      manual["manifest_sha256"])
    assert receipt["release_binding"]["release"] == profile["profile"]["release"]
    ops = pod_name(ns, "ops")
    wait_for(lambda: pod_ready(ns, "ops"), 60, 2, "ops pod Ready after a tested restore")
    # Governed reopening on the Helm profile: gate passed, mutative path still closed.
    status, body = pod_http(ns, ops, "/admit?class=mutative")
    assert status == 503 and "recovery_reopen_pending" in body["reason_code"], body

    # VF-002 on Helm: a custodian-signed receipt with a failed gcs check is refused.
    incoherent = deepcopy(receipt)
    _gate_fails("gcs", VERIFIER_GCS_DETAIL)(incoherent)
    files, digest = write_signed_receipt(stack.env, vault, incoherent, "helm-gcs")
    try:
        wait_for(lambda: not pod_ready(ns, "ops"), 60, 2, "incoherent receipt must drop readiness")
        status, body = pod_http(ns, ops, "/readyz")
        assert (status, body["reasons"]) == (503, ["RESTORE_RECEIPT_INCONSISTENT"]), body
        status, body = pod_http(ns, ops, "/reopen", "POST", {"Authorization": f"Bearer {stack.operator_token}",
                                                             "Content-Type": "application/json"},
                                {"receipt_digest": digest, "authorized_by": "drill-operator"})
        assert (status, body["reason_code"]) == (409, "REOPEN_REFUSED:RESTORE_RECEIPT_INCONSISTENT"), body
        status, body = pod_http(ns, ops, "/admit?class=mutative")
        assert status == 503 and "restore_not_verified" in body["reason_code"], body
    finally:
        for f in files:
            f.unlink()
    wait_for(lambda: pod_ready(ns, "ops"), 60, 2, "authentic receipt verified again")

    # Pair enforcement: a decoy on the dependency network listens on an allowlisted port
    # (8181) at an address that is not the one pinned for that port. It must be
    # unreachable from the pod, while the same connection succeeds from the kind node
    # without the NetworkPolicy (positive control) and opa:8181 stays reachable.
    decoy = f"ocor-poc-decoy-{uuid.uuid4().hex[:6]}"
    STARTED_CONTAINERS.add(decoy)
    subprocess.run(["docker", "run", "-d", "--name", decoy, "--network", BOOTSTRAP_NETWORK, OPS_IMAGE, "python3", "-m",
                    "http.server", "8181"], capture_output=True, check=True)
    try:
        decoy_ip = subprocess.run(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                                   decoy], capture_output=True, text=True, check=True).stdout.strip()
        control = wait_for(lambda: subprocess.run(
            ["docker", "exec", f"{KIND_CLUSTER}-control-plane", "bash", "-c",
             f"exec 3<>/dev/tcp/{decoy_ip}/8181 && echo CONNECTED"], capture_output=True, text=True,
            check=False).stdout.strip() == "CONNECTED", 30, 1, "decoy reachable from the node (positive control)")
        assert control
        egress = pod_python(ns, ops, "import socket\nfor t in [('1.1.1.1',443),('postgresql',5432),('opa',8181),"
                            f"('{decoy_ip}',8181),('postgresql',8181),('qdrant',6334)]:\n"
                            "    try: socket.create_connection(t,4).close(); print(t[0],t[1],'CONNECTED')\n"
                            "    except OSError as e: print(t[0],t[1],'DENIED')")
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", decoy], capture_output=True, check=False)
    assert egress.splitlines() == ["1.1.1.1 443 DENIED", "postgresql 5432 CONNECTED", "opa 8181 CONNECTED",
                                   f"{decoy_ip} 8181 DENIED", "postgresql 8181 DENIED", "qdrant 6334 DENIED"], egress
    subprocess.run(["docker", "pause", "ocor-bootstrap-qdrant-1"], check=True, capture_output=True)
    try:
        wait_for(lambda: not pod_ready(ns, "ops"), 60, 2, "pod readiness must drop while qdrant is paused")
    finally:
        subprocess.run(["docker", "unpause", "ocor-bootstrap-qdrant-1"], check=False, capture_output=True)
    wait_for(lambda: pod_ready(ns, "ops"), 90, 2, "pod readiness must recover")

    # VF-001 on Helm, positive: a restarted pod of the SAME release verifies the receipt.
    kubectl("-n", ns, "delete", "pod", ops, "--wait=true", timeout=180)
    ops = wait_for(lambda: [p for p in pods(ns, "ops") if p != ops], 120, 2, "replacement pod")[0]
    wait_for(lambda: named_pod_ready(ns, ops), 120, 2, "restarted pod Ready with the receipt of its release")

    # Verdict OCOR-DEV-0049-aefabf91777d-4 VF-001 on Helm: an image outside the governed
    # pins never reaches the cluster (rendering refused, release and pod unchanged) ...
    def deployed_image() -> str:
        return kubectl("-n", ns, "get", "deployment", "ocor-poc-ops", "-o",
                       "jsonpath={.spec.template.spec.containers[0].image}").stdout
    assert deployed_image() == profile["images"]["pins"]["ops"]
    revision = helm_revision(kind)
    for setting, message in (("operational.image=python:3.11", "operational.image is not accepted"),
                             (f"operational.image={OTHER_OPS_IMAGE}", "operational.image is not accepted"),
                             ("ocor.images.pins.ops=python:3.11", "ocor.images.pins.ops must be digest-pinned"),
                             ("ocor.images.pins.postgresql=postgres:latest",
                              "ocor.images.pins.postgresql must be digest-pinned")):
        result = helm_upgrade_run(kind, setting)
        assert result.returncode != 0 and message in result.stderr, (setting, result.stderr)
    assert helm_revision(kind) == revision and deployed_image() == profile["images"]["pins"]["ops"]
    assert pods(ns, "ops") == [ops] and named_pod_ready(ns, ops)
    # ... and an upgrade to OTHER pins runs exactly that artifact, whose restore was never
    # tested: the pod is not Ready, cannot be reopened and admits no governed work.
    helm_upgrade(kind, f"ocor.images.pins.ops={OTHER_OPS_IMAGE}")
    repinned = wait_for(lambda: [p for p in pods(ns, "ops") if p != ops], 120, 2, "pod of the new pins")[0]
    wait_for(lambda: kubectl("-n", ns, "get", "pod", repinned, "-o", "jsonpath={.status.phase}",
                             check=False).stdout == "Running", 600, 3, "repinned pod running")
    image_id = kubectl("-n", ns, "get", "pod", repinned, "-o",
                       "jsonpath={.status.containerStatuses[0].imageID}").stdout
    assert image_id.endswith(OTHER_OPS_IMAGE.split("@")[1]), image_id
    assert pod_python(ns, repinned, "import json;print(json.load(open('/etc/ocor/profile.json'))['images']"
                      "['pins']['ops'])") == OTHER_OPS_IMAGE, "the binding covers the executed artifact"
    status, body = wait_for(lambda: (r := pod_http(ns, repinned, "/readyz"))[1]["reasons"] == [
        "RESTORE_PINS_MISMATCH"] and r, 120, 2, "pin fence of the repinned pod")
    assert status == 503 and not named_pod_ready(ns, repinned)
    status, body = pod_http(ns, repinned, "/reopen", "POST", {"Authorization": f"Bearer {stack.operator_token}",
                                                              "Content-Type": "application/json"},
                            {"receipt_digest": receipt_digest(vault), "authorized_by": "drill-operator"})
    assert (status, body["reason_code"]) == (409, "REOPEN_REFUSED:RESTORE_PINS_MISMATCH"), body
    for operation_class in OPERATION_CLASSES:
        status, body = pod_http(ns, repinned, f"/admit?class={operation_class}")
        assert status == 503 and "restore_not_verified" in body["reason_code"], (operation_class, body)
    # Positive counterpart: back to the governed pins, the tested pod is the only one, Ready.
    helm_upgrade(kind)
    wait_for(lambda: pods(ns, "ops") == [ops], 180, 2, "repinned pod removed on rollback to the governed pins")
    assert deployed_image() == profile["images"]["pins"]["ops"]
    wait_for(lambda: named_pod_ready(ns, ops), 60, 2, "governed pod Ready")
    status, body = pod_http(ns, ops, "/readyz")
    assert (status, body["reasons"]) == (200, ["READY"]), body

    # VF-001 on Helm, negative: an upgrade to another release keeps the vault of the
    # previous one; the new pod must not become Ready, reopen or admit governed work.
    next_release = "ocor-poc-0.2.1-helm"
    following = deepcopy(profile)
    following["profile"]["release"] = next_release
    previous = set(pods(ns, "ops"))
    helm_upgrade(kind, f"ocor.profile.release={next_release}")
    upgraded = wait_for(lambda: [p for p in pods(ns, "ops") if p not in previous], 120, 2, "pod of the new release")[0]
    wait_for(lambda: kubectl("-n", ns, "get", "pod", upgraded, "-o", "jsonpath={.status.phase}",
                             check=False).stdout == "Running", 300, 3, "new release pod running")
    # kindnet programs the NetworkPolicy for a new pod asynchronously: the agent reports the
    # open-egress window itself (PUBLIC_EGRESS_OPEN, fail-closed) until it converges; the
    # release fence must then remain the only reason the new pod is not Ready.
    status, body = wait_for(lambda: (r := pod_http(ns, upgraded, "/readyz"))[1]["reasons"] == [
        "RESTORE_RELEASE_MISMATCH"] and r, 120, 2, "release fence of the new release pod")
    assert status == 503 and not named_pod_ready(ns, upgraded)
    status, body = pod_http(ns, upgraded, "/reopen", "POST", {"Authorization": f"Bearer {stack.operator_token}",
                                                              "Content-Type": "application/json"},
                            {"receipt_digest": receipt_digest(vault), "authorized_by": "drill-operator"})
    assert (status, body["reason_code"]) == (409, "REOPEN_REFUSED:RESTORE_RELEASE_MISMATCH"), body
    for operation_class in OPERATION_CLASSES:
        status, body = pod_http(ns, upgraded, f"/admit?class={operation_class}")
        assert status == 503 and "restore_not_verified" in body["reason_code"], (operation_class, body)

    # ... and becomes Ready only after a backup and a tested restore of its own release.
    status, logs = run_job(ns, ["create", "job", "ocor-poc-backup-next", "--from=cronjob/ocor-poc-backup"],
                           "ocor-poc-backup-next")
    assert status.startswith("1/"), logs
    sealed_next = sealed_point(logs)
    assert_sealed(stack, vault, sealed_next, following)
    revision = helm_upgrade(kind, f"ocor.profile.release={next_release}", "operational.restoreDrill.enabled=true",
                            f"operational.restoreDrill.recoveryPoint={sealed_next['recovery_point']}")
    status, logs = wait_job(ns, f"ocor-poc-restore-drill-{revision}")
    assert status.get("succeeded") == 1, logs
    receipt = latest_receipt(vault)
    assert (receipt["outcome"], receipt["recovery_point"], receipt["release_binding"]["release"]) == (
        "PASSED", sealed_next["recovery_point"], next_release)
    wait_for(lambda: named_pod_ready(ns, upgraded), 120, 2, "new release Ready after its own tested restore")
    status, body = pod_http(ns, upgraded, "/readyz")
    assert (status, body["reasons"]) == (200, ["READY"]), body


# --------------------------------------------------------------------------- VF-006


def test_missing_environment_fails_instead_of_skipping(tmp_path):
    """A byte-identical copy of this module, run where no bootstrap env exists,
    must FAIL (non-zero, zero skips) rather than silently pass."""
    copy = tmp_path / "isolated" / "test_copy.py"
    copy.parent.mkdir()
    shutil.copy2(Path(__file__), copy)
    env = {k: v for k, v in os.environ.items() if not k.startswith("OCOR_")}
    env.update({"HOME": str(tmp_path), "OCOR_BOOTSTRAP_ENV": str(tmp_path / "absent.env")})
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(copy),
                             "-k", "test_ops_process_serves_health", "--junitxml", str(tmp_path / "r.xml")],
                            capture_output=True, text=True, env=env, cwd=tmp_path, check=False, timeout=300)
    assert result.returncode == 1, result.stdout
    report = (tmp_path / "r.xml").read_text()
    assert 'skipped="0"' in report, report
    assert 'errors="1"' in report or 'failures="1"' in report, report
    assert "ocor-bootstrap env file not found" in result.stdout


@pytest.mark.parametrize("journal_max,metadata_max", [(7, 7), (9, 7)])
def test_seal_and_restore_tied_epoch_tombstones_are_locale_independent(stack, agent_module,
                                                                     journal_max, metadata_max):
    """Live VF-001/VF-002: seal + isolated restore with same-epoch IDs whose
    locale and codepoint orders diverge; the signed checkpoint accepts the real
    replay (also with journal ahead of metadata), and refuses omitted, reordered
    tombstones and a deletion epoch below the checkpoint at the live boundary."""
    import psycopg

    vault = stack.work / f"tied-epoch-{journal_max}"
    vault.mkdir()
    project = f"ocor-poc-tied-{uuid.uuid4().hex[:6]}"
    name = None
    try:
        load_drill_fixture(stack.env, consistent=True)
        with psycopg.connect(postgres_dsn(stack.env, "ocor_poc_drill"), autocommit=True) as conn:
            conn.execute("update memory_item set lifecycle_state='deleted', deletion_epoch=%s"
                         " where item_id in ('m2','m4','m5')", (metadata_max,))
            conn.execute("delete from memory_deletion_journal")
            conn.execute("insert into memory_deletion_journal values (%s,'m2',%s),(%s,'m4',%s),(%s,'m5',%s)",
                         ("evt-del-a", journal_max, "evt-del-B", journal_max, "evt-del-c", journal_max))
            locale_ids = [r[0] for r in conn.execute("select event_id from memory_deletion_journal order by event_id")]
            codepoint_ids = [r[0] for r in conn.execute(
                'select event_id from memory_deletion_journal order by event_id collate "C"')]
            assert locale_ids != codepoint_ids, "fixture must exercise a real DB/Python collation divergence"
            assert codepoint_ids == SEALED_TIED
            # Cycle 8 (VF-001 of OCOR-DEV-0049-9d86abebc762-7): the locale permutation keeps the
            # last id, so only the signed whole-sequence digest can tell it from the sealed one.
            assert locale_ids[-1] == codepoint_ids[-1]
        code, logs = stack.run_stage(project, "backup", "ocor-backup-seal", vault=vault)
        assert code == 0, logs
        points = list((vault / "recovery-points").iterdir())
        assert len(points) == 1, "this vault belongs to only this seal"
        point = points[0]
        sealed = {"recovery_point": point.name,
                  "manifest_sha256": hashlib.sha256((point / "manifest.json").read_bytes()).hexdigest()}
        manifest = assert_sealed(stack, vault, sealed, helm_profile())
        memory = manifest["memory"]
        assert memory["journalCheckpoints"] == {"entries": 3, "max_deletion_epoch": journal_max,
                                               "last_event_id": codepoint_ids[-1],
                                               "event_ids_digest": sequence_digest(codepoint_ids)}
        assert memory["liveItems"] == drill_live_items([1, 3])
        assert memory["deletionEpochs"] == {"journal_max": journal_max, "metadata_max": metadata_max}
        stack.down(project)
        code, logs = stack.run_stage_detached(project, "restore-drill", "ocor-restore-finalize", vault=vault)
        assert code == 0, logs
        assert sorted(restored_payloads(project)) == ["m1", "m3"], "all three tombstones took effect"
        receipt = latest_receipt(vault)
        assert receipt["replayed_event_ids"] == codepoint_ids
        assert receipt["restored_scope_digest"] == drill_live_items([1, 3])["scope_digest"]
        assert agent_module.receipt_checkpoint_inconsistencies(receipt, memory) == []
        name = _standalone_ops(stack, vault, f"{stack.ops_project}_site")
        wait_for(lambda: _standalone_readyz(name)[0] == 200, 60, message="tied-epoch receipt accepted live")
        good_digest = receipt_digest(vault)
        status, body = reopen(name, stack.operator_token, good_digest, base=LOCAL_OPS)
        assert (status, body["reason_code"]) == (200, "MUTATIVE_PATH_REOPENED_BY_HUMAN")
        assert_admission(name, admitted=OPERATION_CLASSES, base=LOCAL_OPS)
        mutations = [*[(case, _set("replayed_event_ids", replayed), "memory:tombstones_not_replayed")
                       for case, replayed in SEQUENCE_MUTATIONS],
                     ("locale_order", _set("replayed_event_ids", locale_ids), "memory:tombstones_not_replayed"),
                     ("below_checkpoint", _epochs(journal_max - 1, min(metadata_max, journal_max - 1)),
                      "memory:deletion_epoch_checkpoint_mismatch")]
        for case, mutate, detail in mutations:
            broken = deepcopy(receipt)
            mutate(broken)
            assert agent_module.receipt_inconsistencies(broken, helm_profile()) == [], case
            assert detail in agent_module.receipt_checkpoint_inconsistencies(broken, memory), case
        for case, mutate, detail in mutations:
            broken = deepcopy(receipt)
            mutate(broken)
            files, digest = write_signed_receipt(stack.env, vault, broken, f"tied-{case}")
            try:
                _observe_refused_receipt(stack, name, digest, "RESTORE_RECEIPT_INCONSISTENT", detail)
            finally:
                for f in files:
                    f.unlink()
            wait_for(lambda: posture(name, LOCAL_OPS)["restore"]["receipt_digest"] == good_digest, 30,
                     message="authentic tied-epoch receipt accepted again")
            assert wait_for(lambda: _standalone_readyz(name)[0] == 200, 15)
    finally:
        if name:
            subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, check=True)
        stack.down(project)
        load_drill_fixture(stack.env, consistent=True)
