"""OCOR-DEV-REM-0055: start-up tolerant typed Temporal check.

Remediation B1 of the decision request NCP-U08-LANE-TEMPORAL-READINESS
(2026-11-06, decided on full delegation of the PO). In the lane sandbox of
``scripts/run_local_lane_campaign.py`` the Temporal frontend answers the CLI
only about 57-59 s after the server starts, while the Compose healthcheck is
TCP-only and the typed check of ``scripts/verify_external_services.py`` probed
it once, about 30-35 s after start. The typed check now reaches the bounded
wait of ``deploy/bootstrap/services/temporal/qualify.py`` (``wait_ready``,
90 s) when it executes, and requires exactly the same outcome: a running,
healthy, loopback-only server, cluster health ``SERVING``, the locked server
version and an absent namespace refused. Other services, test timeouts and
criteria are unchanged.

The backend-free cases replace only Docker and the clock, to reproduce the
early probe deterministically (local failure handling); the live cases run
against the real ``ocor-bootstrap`` stack and fail, never skip, without it.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
QUALIFY_PATH = ROOT / "deploy/bootstrap/services/temporal/qualify.py"
LOCK_PATH = ROOT / "infra/services.lock.json"
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


qualify = _load("temporal_qualify_rem0055", QUALIFY_PATH)
verify = _load("verify_external_services_rem0055", ROOT / "scripts/verify_external_services.py")

LOCK = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
ENTRIES = qualify.validate_lock(LOCK)
SERVER_IMAGE = ENTRIES["server"]["image"]
ADMIN_IMAGE = ENTRIES["admin"]["image"]
DATABASE_IMAGE = ENTRIES["database"]["image"]
VERSION = ENTRIES["server"]["version"]
EXPECTED_PROTOCOL = {
    "frontend_host_tcp": "READY",
    "cluster_health": "SERVING",
    "server_version": VERSION,
    "absent_namespace_lookup": "FAIL_CLOSED",
}
EXPECTED_SERVER_RUNTIME = {"health": "healthy", "ports": {"7233/tcp": str(qualify.HOST_PORT)}}
# Lane reproduction 4 of the decision request: the frontend answered the CLI ~57 s after start,
# the single typed probe ran at ~30-35 s.
# The bounded wait decided in option B1 (wait_ready of qualify.py).
WAIT = 90.0
FRONTEND_READY_AT = 57.0
FIRST_PROBE_AT = 32.0


def _inspection(image: str, *, ports: dict[str, Any] | None = None, running: bool = True,
                paused: bool = False, health: str = "healthy") -> dict[str, Any]:
    return {
        "Config": {"Image": image},
        "State": {"Running": running, "Paused": paused, "Health": {"Status": health}},
        "NetworkSettings": {"Ports": ports if ports is not None else {}},
    }


SERVER_PORTS = {"7233/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(qualify.HOST_PORT)}], "6933/tcp": None}


class FakeTemporal:
    """Docker, TCP and clock doubles: a server that starts at t=0 and answers the CLI from ``ready_at``."""

    def __init__(self, *, ready_at: float, start: float = FIRST_PROBE_AT,
                 server: Callable[[float], dict[str, Any]] | None = None,
                 observe: Callable[[float, tuple[str, ...]], subprocess.CompletedProcess[str] | None] | None = None,
                 tcp_ready_at: float = 0.0) -> None:
        self.now = start
        self.ready_at = ready_at
        self.server = server
        self.observe = observe
        self.tcp_ready_at = tcp_ready_at
        self.calls: list[tuple[float, str]] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds > 0
        self.now += seconds

    def inspect_container(self, container: str) -> dict[str, Any]:
        self.calls.append((self.now, f"inspect {container}"))
        if container == qualify.SERVER_CONTAINER:
            if self.server is not None:
                return self.server(self.now)
            return _inspection(SERVER_IMAGE, ports=SERVER_PORTS)
        if container == qualify.ADMIN_CONTAINER:
            return _inspection(ADMIN_IMAGE)
        if container == qualify.DATABASE_CONTAINER:
            return _inspection(DATABASE_IMAGE)
        raise qualify.QualificationError(f"container not found: {container}")

    @contextmanager
    def create_connection(self, address: tuple[str, int], timeout: float) -> Iterator[None]:
        assert address == (qualify.HOST, qualify.HOST_PORT) and timeout > 0
        self.calls.append((self.now, "tcp"))
        if self.now < self.tcp_ready_at:
            raise ConnectionRefusedError("connection refused")
        yield None

    def cli(self, admin: str, *arguments: str, timeout: float = 20.0) -> subprocess.CompletedProcess[str]:
        assert admin == qualify.ADMIN_CONTAINER
        self.calls.append((self.now, " ".join(arguments)))
        if self.observe is not None:
            forced = self.observe(self.now, arguments)
            if forced is not None:
                return forced
        if self.now < self.ready_at:
            # The CLI's --command-timeout 5s elapses against a frontend that does not answer yet.
            self.now += 5.0
            return subprocess.CompletedProcess(arguments, 1, "", "context deadline exceeded")
        return _healthy_answer(arguments)

    def probes(self, verb: str = "operator cluster health") -> list[float]:
        return [at for at, call in self.calls if call == verb]


def _healthy_answer(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    if tuple(arguments[:3]) == ("operator", "cluster", "health"):
        return subprocess.CompletedProcess(arguments, 0, "SERVING\n", "")
    if tuple(arguments[:3]) == ("operator", "cluster", "system"):
        return subprocess.CompletedProcess(arguments, 0, json.dumps({"serverVersion": VERSION}), "")
    if tuple(arguments[:3]) == ("operator", "namespace", "describe"):
        return subprocess.CompletedProcess(arguments, 1, "", f"Namespace {qualify.ABSENT_NAMESPACE} is not found.")
    raise AssertionError(f"unexpected Temporal CLI call: {arguments}")


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch) -> Callable[[FakeTemporal], FakeTemporal]:
    def _install(fake: FakeTemporal) -> FakeTemporal:
        monkeypatch.setattr(qualify.time, "monotonic", fake.monotonic)
        monkeypatch.setattr(qualify.time, "sleep", fake.sleep)
        monkeypatch.setattr(qualify, "inspect_container", fake.inspect_container)
        monkeypatch.setattr(qualify, "cli", fake.cli)
        monkeypatch.setattr(qualify.socket, "create_connection", fake.create_connection)
        return fake
    return _install


def _execute(*extra: str) -> dict[str, Any]:
    result: dict[str, Any] = qualify.qualify(qualify.parse_args(["--lock", str(LOCK_PATH), *extra]))
    return result


# --- RED: the early probe of the lane bootstrap ------------------------------


def test_executed_typed_probe_waits_for_the_frontend_started_late(install):
    fake = install(FakeTemporal(ready_at=FRONTEND_READY_AT))
    result = _execute("--execute")
    assert result["result"] == "PASS"
    assert result["protocol"] == EXPECTED_PROTOCOL
    assert result["runtime"]["server"] == EXPECTED_SERVER_RUNTIME
    probes = fake.probes()
    assert probes[0] == FIRST_PROBE_AT and len(probes) >= 2
    assert probes[-1] >= FRONTEND_READY_AT
    assert fake.now - FIRST_PROBE_AT <= WAIT


def test_executed_typed_probe_tolerates_the_absent_namespace_start_up_symptom(install):
    # Second symptom of the decision request: during start-up the absent-namespace lookup does not answer "not found".
    def observe(now: float, arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str] | None:
        if arguments[:3] == ("operator", "namespace", "describe") and now < FRONTEND_READY_AT:
            return subprocess.CompletedProcess(arguments, 1, "", "Error: context deadline exceeded")
        return None

    fake = install(FakeTemporal(ready_at=0.0, observe=observe))
    result = _execute("--execute")
    assert result["protocol"] == EXPECTED_PROTOCOL
    assert len(fake.probes("operator namespace describe -n " + qualify.ABSENT_NAMESPACE)) >= 2


def test_executed_typed_probe_waits_for_the_server_container_health(install):
    def server(now: float) -> dict[str, Any]:
        if now < 40.0:
            return _inspection(SERVER_IMAGE, ports=SERVER_PORTS, health="starting")
        return _inspection(SERVER_IMAGE, ports=SERVER_PORTS)

    fake = install(FakeTemporal(ready_at=0.0, server=server))
    result = _execute("--execute")
    assert result["runtime"]["server"] == EXPECTED_SERVER_RUNTIME
    assert result["protocol"] == EXPECTED_PROTOCOL
    assert fake.now >= 40.0


def test_executed_typed_probe_waits_for_the_host_publication(install):
    fake = install(FakeTemporal(ready_at=0.0, tcp_ready_at=45.0))
    assert _execute("--execute")["protocol"] == EXPECTED_PROTOCOL
    assert fake.now >= 45.0


# --- the required outcome is unchanged: persistent failures still fail closed --


def _never(now: float, arguments: tuple[str, ...]) -> None:
    return None


PERSISTENT_FAILURES: dict[str, tuple[dict[str, Any], str]] = {
    "never-serving": ({"ready_at": float("inf")}, "Temporal cluster health is not SERVING"),
    "version-differs": (
        {"observe": lambda now, a: subprocess.CompletedProcess(a, 0, json.dumps({"serverVersion": "0.0.1"}), "")
         if a[:3] == ("operator", "cluster", "system") else None},
        "Temporal server version does not match the lock",
    ),
    "absent-namespace-accepted": (
        {"observe": lambda now, a: subprocess.CompletedProcess(a, 0, "NamespaceInfo.Name ocor-qualify-absent-namespace", "")
         if a[:3] == ("operator", "namespace", "describe") else None},
        "describing an absent Temporal namespace did not fail closed",
    ),
    "system-unavailable": (
        {"observe": lambda now, a: subprocess.CompletedProcess(a, 1, "", "unavailable")
         if a[:3] == ("operator", "cluster", "system") else None},
        "Temporal cluster system information is unavailable",
    ),
    "invalid-system-json": (
        {"observe": lambda now, a: subprocess.CompletedProcess(a, 0, "{not json", "")
         if a[:3] == ("operator", "cluster", "system") else None},
        "Temporal returned invalid system JSON",
    ),
    "host-publication-absent": ({"tcp_ready_at": float("inf")}, "Temporal frontend host publication is unavailable"),
    "server-unhealthy": (
        {"server": lambda now: _inspection(SERVER_IMAGE, ports=SERVER_PORTS, health="unhealthy")},
        "Temporal server container is not healthy",
    ),
    "server-paused": (
        {"server": lambda now: _inspection(SERVER_IMAGE, ports=SERVER_PORTS, paused=True)},
        "Temporal server container is not running",
    ),
    "server-other-image": (
        {"server": lambda now: _inspection("temporalio/server@sha256:" + "0" * 64, ports=SERVER_PORTS)},
        "running Temporal server image differs from the exact service lock",
    ),
    "server-public-binding": (
        {"server": lambda now: _inspection(SERVER_IMAGE, ports={"7233/tcp": [{"HostIp": "0.0.0.0", "HostPort": "17233"}]})},
        "Temporal frontend publication is not loopback-only",
    ),
}


@pytest.mark.parametrize("case", sorted(PERSISTENT_FAILURES))
def test_executed_typed_probe_fails_closed_after_the_bounded_wait(install, case):
    options, reason = PERSISTENT_FAILURES[case]
    fake = install(FakeTemporal(**{"ready_at": 0.0, **options}))
    with pytest.raises(qualify.QualificationError) as raised:
        _execute("--execute")
    message = str(raised.value)
    assert message.startswith(f"Temporal did not recover within {WAIT:.0f}s: ")
    assert reason in message
    elapsed = fake.now - FIRST_PROBE_AT
    assert WAIT <= elapsed <= WAIT + 25.0 + 5.0
    assert len([call for call in fake.calls if call[1] == f"inspect {qualify.SERVER_CONTAINER}"]) >= 2


def test_bounded_wait_is_the_decided_ninety_seconds():
    assert qualify.STARTUP_WAIT_SECONDS == WAIT


@pytest.mark.parametrize("container", [qualify.ADMIN_CONTAINER, qualify.DATABASE_CONTAINER])
def test_private_containers_are_still_checked_once_after_the_wait(install, monkeypatch, container):
    fake = install(FakeTemporal(ready_at=0.0))
    original = fake.inspect_container

    def inspect(name: str) -> dict[str, Any]:
        if name == container:
            fake.calls.append((fake.now, f"inspect {name}"))
            return _inspection(ADMIN_IMAGE if name == qualify.ADMIN_CONTAINER else DATABASE_IMAGE,
                               ports={"7233/tcp": [{"HostIp": "127.0.0.1", "HostPort": "1"}]})
        return original(name)

    monkeypatch.setattr(qualify, "inspect_container", inspect)
    with pytest.raises(qualify.QualificationError, match="must not publish any host port"):
        _execute("--execute")
    assert len([call for call in fake.calls if call[1] == f"inspect {container}"]) == 1


def test_lock_errors_are_not_waited_for(install, tmp_path):
    fake = install(FakeTemporal(ready_at=0.0))
    broken = tmp_path / "lock.json"
    broken.write_text(json.dumps({"services": []}), encoding="utf-8")
    with pytest.raises(qualify.QualificationError, match="exactly one temporal entry"):
        qualify.qualify(qualify.parse_args(["--execute", "--lock", str(broken)]))
    assert fake.calls == [] and fake.now == FIRST_PROBE_AT


def test_unexecuted_probe_stays_a_single_observation(install):
    fake = install(FakeTemporal(ready_at=FRONTEND_READY_AT))
    with pytest.raises(qualify.QualificationError, match="^Temporal cluster health is not SERVING$"):
        _execute()
    assert len(fake.probes()) == 1


def test_fault_recovery_still_requires_execute():
    with pytest.raises(qualify.QualificationError, match="--fault-recovery requires explicit --execute"):
        qualify.qualify(qualify.parse_args(["--fault-recovery", "--lock", "/nonexistent/lock.json"]))


def test_main_reports_the_bounded_failure_as_typed_json(install, capsys):
    install(FakeTemporal(ready_at=float("inf")))
    assert qualify.main(["--execute", "--lock", str(LOCK_PATH)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == "FAIL"
    assert payload["errors"] == ["Temporal did not recover within 90s: Temporal cluster health is not SERVING"]


# --- the typed check of verify_external_services -----------------------------


def test_typed_check_bounds_the_temporal_subprocess_beyond_the_wait(monkeypatch):
    seen: dict[str, float] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen[Path(command[1]).parent.name] = kwargs["timeout"]
        return subprocess.CompletedProcess(command, 0, json.dumps({"result": "PASS"}), "")

    monkeypatch.setattr(verify.subprocess, "run", fake_run)
    for service in ("temporal", "typedb", "openbao", "spire", "seaweedfs"):
        verify._run_qualify_script(ROOT, ROOT / "deploy/bootstrap/services" / service / "qualify.py", ["--execute"])
    assert seen.pop("temporal") > WAIT + 3 * 20.0 + 20.0
    assert seen == {"typedb": 60, "openbao": 60, "spire": 60, "seaweedfs": 60}


def test_typed_check_maps_the_bounded_outcome(monkeypatch):
    calls: list[list[str]] = []
    answers = iter([
        (0, {"result": "PASS", "protocol": EXPECTED_PROTOCOL}, ""),
        (1, {"result": "FAIL", "errors": ["Temporal did not recover within 90s: Temporal cluster health is not SERVING"]}, ""),
        (1, {"result": "FAIL", "errors": ["container not found: ocor-bootstrap-temporal-1"]}, ""),
        (1, None, "Traceback"),
    ])

    def fake(repository: Path, script: Path, extra_args: list[str]) -> tuple[int, dict[str, Any] | None, str]:
        calls.append(extra_args)
        return next(answers)

    monkeypatch.setattr(verify, "_run_qualify_script", fake)
    statuses = [verify.check_temporal(ROOT, execute=True).status for _ in range(4)]
    assert statuses == [verify.ServiceStatus.READY, verify.ServiceStatus.DEGRADED,
                        verify.ServiceStatus.NOT_PROVISIONED, verify.ServiceStatus.UNREACHABLE]
    assert calls == [["--execute"]] * 4


# --- live, real stack --------------------------------------------------------


def _docker(*arguments: str) -> None:
    completed = subprocess.run(["docker", *arguments], capture_output=True, text=True, timeout=60, check=False)
    assert completed.returncode == 0, completed.stderr


@contextmanager
def _paused_server(seconds: float | None) -> Iterator[None]:
    _docker("pause", qualify.SERVER_CONTAINER)
    unpaused = threading.Event()

    def unpause() -> None:
        if not unpaused.is_set():
            unpaused.set()
            subprocess.run(["docker", "unpause", qualify.SERVER_CONTAINER], capture_output=True, text=True,
                           timeout=60, check=False)

    timer = threading.Timer(seconds, unpause) if seconds is not None else None
    if timer is not None:
        timer.start()
    try:
        yield
    finally:
        if timer is not None:
            timer.cancel()
        unpause()
        qualify.wait_ready(qualify.SERVER_CONTAINER, qualify.ADMIN_CONTAINER, SERVER_IMAGE, VERSION)


def test_live_typed_temporal_check_is_ready_with_the_unchanged_outcome():
    health = verify.check_temporal(ROOT, execute=True)
    assert health.status is verify.ServiceStatus.READY, health.to_json()
    assert health.detail["protocol"] == EXPECTED_PROTOCOL
    assert health.detail["runtime"]["server"] == EXPECTED_SERVER_RUNTIME
    assert health.detail["lock"]["version"] == VERSION


def test_live_typed_temporal_check_waits_for_a_frontend_unavailable_at_probe_time():
    # The real early probe: the server does not answer when the typed check starts and answers 12 s later.
    with _paused_server(12.0):
        health = verify.check_temporal(ROOT, execute=True)
    assert health.status is verify.ServiceStatus.READY, health.to_json()
    assert health.detail["protocol"] == EXPECTED_PROTOCOL


def test_live_bounded_wait_fails_closed_when_the_server_never_answers(monkeypatch):
    monkeypatch.setattr(qualify, "STARTUP_WAIT_SECONDS", 6.0)
    with _paused_server(None):
        with pytest.raises(qualify.QualificationError) as raised:
            _execute("--execute")
    assert str(raised.value) == "Temporal did not recover within 6s: Temporal server container is not running"


# --- input robustness of the parsing paths of qualify.py (self-check before the preventive review) --


def _lock_with(**changes: Any) -> Any:
    lock = json.loads(json.dumps(LOCK))
    for key, value in changes.items():
        lock[key] = value
    return lock


MALFORMED_LOCKS: dict[str, Any] = {
    "lock-not-object": [],
    "services-not-list": _lock_with(services={"id": "temporal"}),
    "service-entry-not-object": _lock_with(services=["temporal", *LOCK["services"]]),
}


@pytest.mark.parametrize("case", sorted(MALFORMED_LOCKS))
def test_malformed_lock_is_a_typed_refusal(case):
    with pytest.raises(qualify.QualificationError, match="service lock"):
        qualify.validate_lock(MALFORMED_LOCKS[case])


def _server(**overrides: Any) -> dict[str, Any]:
    inspection = _inspection(SERVER_IMAGE, ports=SERVER_PORTS)
    inspection.update(overrides)
    return inspection


MALFORMED_INSPECTIONS: dict[str, Any] = {
    "inspection-not-object": ["Config"],
    "config-not-object": _server(Config="temporalio/server"),
    "state-not-object": _server(State=["Running"]),
    "health-not-object": _server(State={"Running": True, "Paused": False, "Health": "healthy"}),
    "network-not-object": _server(NetworkSettings="7233/tcp"),
    "ports-not-object": _server(NetworkSettings={"Ports": ["7233/tcp"]}),
    "port-bindings-not-list": _server(NetworkSettings={"Ports": {"7233/tcp": {"HostIp": "127.0.0.1", "HostPort": "17233"}}}),
    "binding-not-object": _server(NetworkSettings={"Ports": {"7233/tcp": ["127.0.0.1:17233"]}}),
    "host-port-not-text": _server(NetworkSettings={"Ports": {"7233/tcp": [{"HostIp": "127.0.0.1", "HostPort": 17233}]}}),
}


@pytest.mark.parametrize("case", sorted(MALFORMED_INSPECTIONS))
def test_malformed_server_inspection_is_a_typed_refusal(case):
    with pytest.raises(qualify.QualificationError):
        qualify.validate_server_inspection(MALFORMED_INSPECTIONS[case], SERVER_IMAGE)


@pytest.mark.parametrize("case", ["inspection-not-object", "config-not-object", "state-not-object", "health-not-object",
                                  "network-not-object", "ports-not-object"])
def test_malformed_private_inspection_is_a_typed_refusal(case):
    inspection = MALFORMED_INSPECTIONS[case]
    if isinstance(inspection, dict) and isinstance(inspection.get("Config"), dict):
        inspection = {**inspection, "Config": {"Image": ADMIN_IMAGE}}
    with pytest.raises(qualify.QualificationError):
        qualify.validate_private_inspection(inspection, "Temporal admin-tools", ADMIN_IMAGE)


def test_well_formed_inspections_are_still_accepted():
    assert qualify.validate_server_inspection(_server(), SERVER_IMAGE) == EXPECTED_SERVER_RUNTIME
    assert qualify.validate_private_inspection(_inspection(ADMIN_IMAGE), "Temporal admin-tools", ADMIN_IMAGE) == {
        "health": "healthy", "ports": {}}
    assert qualify.validate_private_inspection(_inspection(ADMIN_IMAGE, ports={"7233/tcp": None}), "Temporal admin-tools",
                                               ADMIN_IMAGE) == {"health": "healthy", "ports": {}}


def test_malformed_server_inspection_during_start_up_is_waited_for_then_refused_typed(install):
    fake = install(FakeTemporal(ready_at=0.0, server=lambda now: _server(State="starting")))
    with pytest.raises(qualify.QualificationError) as raised:
        _execute("--execute")
    assert str(raised.value).startswith(f"Temporal did not recover within {WAIT:.0f}s: ")
    assert fake.now - FIRST_PROBE_AT >= WAIT


def test_malformed_server_inspection_recovers_when_well_formed_within_the_wait(install):
    install(FakeTemporal(ready_at=0.0, server=lambda now: _server(State="starting") if now < 50.0 else _server()))
    assert _execute("--execute")["protocol"] == EXPECTED_PROTOCOL
