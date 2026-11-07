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


# --- preventive review OCOR-DEV-REM-0055-193559ef56e2-pre: the whole input-robustness class -----------
# Every parsing path of qualify.py and of the typed Temporal check refuses a malformed or undecodable
# input with the typed error of its contract; the local responders are real child processes.


@pytest.mark.parametrize("ports", [[], False, 0, ""], ids=["empty-list", "false", "zero", "empty-text"])
@pytest.mark.parametrize("kind", ["server", "private"])
def test_falsy_non_object_ports_are_a_typed_refusal(kind, ports):
    if kind == "server":
        with pytest.raises(qualify.QualificationError, match="Ports is not an object"):
            qualify.validate_server_inspection(_server(NetworkSettings={"Ports": ports}), SERVER_IMAGE)
    else:
        with pytest.raises(qualify.QualificationError, match="Ports is not an object"):
            qualify.validate_private_inspection(_inspection(ADMIN_IMAGE, ports={}) | {"NetworkSettings": {"Ports": ports}},
                                                "Temporal admin-tools", ADMIN_IMAGE)


@pytest.mark.parametrize("network", [{"Ports": None}, {}], ids=["ports-null", "ports-absent"])
def test_absent_ports_of_a_private_container_are_no_publication(network):
    inspection = _inspection(ADMIN_IMAGE) | {"NetworkSettings": network}
    assert qualify.validate_private_inspection(inspection, "Temporal admin-tools", ADMIN_IMAGE) == {
        "health": "healthy", "ports": {}}


@pytest.mark.parametrize("bindings", [[None], [{"HostIp": "127.0.0.1", "HostPort": "17233"}, None]],
                         ids=["null-binding", "null-after-binding"])
def test_null_port_binding_is_a_typed_refusal(bindings):
    with pytest.raises(qualify.QualificationError, match="list of objects"):
        qualify.validate_server_inspection(_server(NetworkSettings={"Ports": {"7233/tcp": bindings}}), SERVER_IMAGE)
    with pytest.raises(qualify.QualificationError, match="list of objects"):
        qualify.validate_private_inspection(_inspection(ADMIN_IMAGE, ports={"7233/tcp": bindings}),
                                            "Temporal admin-tools", ADMIN_IMAGE)


def test_empty_inspection_is_a_typed_refusal():
    with pytest.raises(qualify.QualificationError, match="image differs"):
        qualify.validate_server_inspection({}, SERVER_IMAGE)
    with pytest.raises(qualify.QualificationError, match="image differs"):
        qualify.validate_private_inspection({}, "Temporal admin-tools", ADMIN_IMAGE)


@pytest.mark.parametrize("paused", ["true", "false", 1, 0, [], {}, None],
                         ids=["text-true", "text-false", "one", "zero", "list", "object", "null"])
def test_non_boolean_paused_state_is_a_typed_refusal(paused):
    def with_paused(image: str, ports: dict[str, Any]) -> dict[str, Any]:
        inspection = _inspection(image, ports=ports)
        inspection["State"]["Paused"] = paused
        return inspection

    with pytest.raises(qualify.QualificationError, match="State Paused is not a boolean"):
        qualify.validate_server_inspection(with_paused(SERVER_IMAGE, SERVER_PORTS), SERVER_IMAGE)
    with pytest.raises(qualify.QualificationError, match="State Paused is not a boolean"):
        qualify.validate_private_inspection(with_paused(ADMIN_IMAGE, {}), "Temporal admin-tools", ADMIN_IMAGE)


def test_absent_paused_state_is_not_paused():
    inspection = _inspection(SERVER_IMAGE, ports=SERVER_PORTS)
    del inspection["State"]["Paused"]
    assert qualify.validate_server_inspection(inspection, SERVER_IMAGE) == EXPECTED_SERVER_RUNTIME


def _service(service_id: str, **changes: Any) -> Any:
    lock = json.loads(json.dumps(LOCK))
    for entry in lock["services"]:
        if entry["id"] == service_id:
            entry.update(changes)
    return lock


LEAF_TYPES = {"int": 1, "bool": True, "null": None, "list": ["x"], "object": {"image": "x"}}
MALFORMED_LEAVES: dict[str, tuple[Any, str]] = {
    **{f"server-image-{name}": (_service("temporal", image=value), "server image is not digest-pinned")
       for name, value in LEAF_TYPES.items()},
    **{f"admin-image-{name}": (_service("temporal-admin-tools", image=value), "admin-tools image is not digest-pinned")
       for name, value in LEAF_TYPES.items()},
    **{f"database-image-{name}": (_service("postgresql", image=value), "PostgreSQL image is not digest-pinned")
       for name, value in LEAF_TYPES.items()},
    **{f"server-version-{name}": (_service("temporal", version=value), "no exact semantic version")
       for name, value in LEAF_TYPES.items()},
    "lock-empty-object": ({}, "exactly one temporal entry"),
    "services-null-entry": (_lock_with(services=[None, *LOCK["services"]]), "list of objects"),
    "services-null": (_lock_with(services=None), "list of objects"),
}


@pytest.mark.parametrize("case", sorted(MALFORMED_LEAVES))
def test_malformed_lock_leaf_is_a_typed_refusal(case):
    lock, reason = MALFORMED_LEAVES[case]
    with pytest.raises(qualify.QualificationError, match=reason):
        qualify.validate_lock(lock)


def test_lock_fields_are_never_converted_to_text():
    import ast
    import inspect as source_inspect

    tree = ast.parse(source_inspect.getsource(qualify))
    coercions = [node.lineno for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str"
                 and node.args and isinstance(node.args[0], ast.Call)
                 and isinstance(node.args[0].func, ast.Attribute) and node.args[0].func.attr == "get"]
    assert coercions == []


LOCK_FILES: dict[str, bytes] = {
    "not-utf8": b"\xff\xfe{}",
    "not-json": b"{not json",
    "empty": b"",
}


@pytest.mark.parametrize("case", sorted(LOCK_FILES))
def test_unreadable_lock_file_is_a_typed_refusal(install, tmp_path, case):
    fake = install(FakeTemporal(ready_at=0.0))
    path = tmp_path / "lock.json"
    path.write_bytes(LOCK_FILES[case])
    with pytest.raises(qualify.QualificationError, match="service lock is unreadable"):
        qualify.qualify(qualify.parse_args(["--execute", "--lock", str(path)]))
    assert fake.calls == []


def test_missing_lock_file_is_a_typed_refusal(tmp_path):
    with pytest.raises(qualify.QualificationError, match="service lock is unreadable"):
        qualify.qualify(qualify.parse_args(["--lock", str(tmp_path / "absent.json")]))


@pytest.mark.parametrize("case", sorted(LOCK_FILES))
def test_main_reports_an_unreadable_lock_as_typed_json(tmp_path, capsys, case):
    path = tmp_path / "lock.json"
    path.write_bytes(LOCK_FILES[case])
    assert qualify.main(["--lock", str(path)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == "FAIL"
    assert payload["errors"][0].startswith("service lock is unreadable")


SYSTEM_OUTPUTS = {"list": "[]", "null": "null", "empty-object": "{}", "version-null": '{"serverVersion": null}',
                  "version-int": '{"serverVersion": 1321}', "version-list": '{"serverVersion": ["1.32.1"]}'}


@pytest.mark.parametrize("case", sorted(SYSTEM_OUTPUTS))
def test_malformed_system_information_is_a_typed_refusal(case):
    with pytest.raises(qualify.QualificationError, match="server version does not match the lock"):
        qualify.validate_observations(health_exit=0, health_output="SERVING\n", system_exit=0,
                                      system_output=SYSTEM_OUTPUTS[case], absent_exit=1,
                                      absent_output="Namespace x is not found.", expected_version=VERSION)


# Local responders: a ``docker`` executable on PATH that writes fixed bytes, so run(), inspect_container()
# and cli() parse a real child process output.


def _responder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: bytes, *, stderr: bytes = b"",
               code: int = 0, sleep: float = 0.0) -> None:
    directory = tmp_path / "bin"
    directory.mkdir(exist_ok=True)
    script = directory / "docker"
    script.write_text(
        "#!" + sys.executable + "\nimport sys, time\n"
        f"time.sleep({sleep!r})\nsys.stdout.buffer.write({stdout!r})\nsys.stderr.buffer.write({stderr!r})\n"
        f"sys.exit({code})\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{directory}:/usr/bin:/bin")


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_undecodable_command_output_is_a_typed_refusal(tmp_path, monkeypatch, stream):
    _responder(tmp_path, monkeypatch, b"\xff\xfe" if stream == "stdout" else b"[]",
               stderr=b"\xff\xfe" if stream == "stderr" else b"")
    with pytest.raises(qualify.QualificationError, match="bounded command failed: docker"):
        qualify.run(["docker", "inspect", qualify.SERVER_CONTAINER])


def test_command_timeout_and_start_failure_are_typed_refusals(tmp_path, monkeypatch):
    _responder(tmp_path, monkeypatch, b"[]", sleep=5.0)
    with pytest.raises(qualify.QualificationError, match="bounded command failed: docker"):
        qualify.run(["docker", "inspect", qualify.SERVER_CONTAINER], timeout=0.5)
    with pytest.raises(qualify.QualificationError, match="bounded command failed"):
        qualify.run([str(tmp_path / "absent-docker")])


INSPECT_OUTPUTS: dict[str, tuple[bytes, int, str]] = {
    "not-utf8": (b"\xff\xfe", 0, "bounded command failed: docker"),
    "not-json": (b"[{not json", 0, "docker inspect returned invalid JSON"),
    "empty-list": (b"[]", 0, "unexpected container set"),
    "null-element": (b"[null]", 0, "unexpected container set"),
    "object-not-list": (b"{}", 0, "unexpected container set"),
    "two-containers": (b"[{}, {}]", 0, "unexpected container set"),
    "not-found": (b"[]", 1, "container not found"),
}


@pytest.mark.parametrize("case", sorted(INSPECT_OUTPUTS))
def test_malformed_docker_inspect_output_is_a_typed_refusal(tmp_path, monkeypatch, case):
    stdout, code, reason = INSPECT_OUTPUTS[case]
    _responder(tmp_path, monkeypatch, stdout, code=code)
    with pytest.raises(qualify.QualificationError, match=reason):
        qualify.inspect_container(qualify.SERVER_CONTAINER)


def test_well_formed_docker_inspect_output_is_parsed(tmp_path, monkeypatch):
    _responder(tmp_path, monkeypatch, json.dumps([_server()]).encode())
    assert qualify.inspect_container(qualify.SERVER_CONTAINER) == _server()


def test_undecodable_cli_output_is_a_typed_refusal(tmp_path, monkeypatch):
    _responder(tmp_path, monkeypatch, b"SERVING\xff\n")
    with pytest.raises(qualify.QualificationError, match="bounded command failed: docker"):
        qualify.cli(qualify.ADMIN_CONTAINER, "operator", "cluster", "health")


def test_undecodable_output_during_start_up_is_waited_for_then_refused_typed(tmp_path, monkeypatch):
    _responder(tmp_path, monkeypatch, b"\xff\xfe")
    clock = FakeTemporal(ready_at=0.0)
    monkeypatch.setattr(qualify.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(qualify.time, "sleep", clock.sleep)
    with pytest.raises(qualify.QualificationError) as raised:
        qualify.wait_ready(qualify.SERVER_CONTAINER, qualify.ADMIN_CONTAINER, SERVER_IMAGE, VERSION, timeout=5.0)
    assert str(raised.value) == "Temporal did not recover within 5s: bounded command failed: docker"
    assert clock.now - FIRST_PROBE_AT >= 5.0


# The typed check of verify_external_services: malformed qualification output, a subprocess beyond its
# bound or undecodable output is a typed UNREACHABLE outcome of check_temporal, never a raw exception.

MALFORMED_PAYLOADS: dict[str, tuple[int, Any]] = {
    "list": (1, []),
    "text": (1, "FAIL"),
    "number": (1, 1),
    "true-with-zero-exit": (0, True),
    "empty-object": (1, {}),
    "result-not-text": (0, {"result": ["PASS"]}),
    "errors-null": (1, {"result": "FAIL", "errors": None}),
    "errors-number": (1, {"result": "FAIL", "errors": 1}),
    "errors-text": (1, {"result": "FAIL", "errors": "container not found"}),
    "errors-null-element": (1, {"result": "FAIL", "errors": [None]}),
    "errors-number-element": (1, {"result": "FAIL", "errors": [404]}),
}


@pytest.mark.parametrize("case", sorted(MALFORMED_PAYLOADS))
def test_typed_check_refuses_a_malformed_qualification_payload(monkeypatch, case):
    returncode, payload = MALFORMED_PAYLOADS[case]
    monkeypatch.setattr(verify, "_run_qualify_script", lambda repository, script, extra_args: (returncode, payload, "err"))
    health = verify.check_temporal(ROOT, execute=True)
    assert health.status is verify.ServiceStatus.UNREACHABLE
    assert health.detail == {"error": "Temporal qualification output is not a well-formed result object",
                             "stderr": "err"}


def _temporal_script(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "deploy/bootstrap/services/temporal/qualify.py"
    script.parent.mkdir(parents=True)
    script.write_text("import sys, time\n" + body + "\n", encoding="utf-8")
    return tmp_path


RESPONDER_SCRIPTS: dict[str, tuple[str, str]] = {
    "stdout-not-utf8": ("sys.stdout.buffer.write(b'\\xff\\xfe')", "Temporal qualification output is not decodable"),
    "stderr-not-utf8": ("sys.stderr.buffer.write(b'\\xff\\xfe'); sys.exit(1)",
                        "Temporal qualification output is not decodable"),
    "beyond-the-bound": ("time.sleep(10)", "Temporal qualification exceeded its subprocess bound"),
    "non-object-json": ("print('[]'); sys.exit(1)", "Temporal qualification output is not a well-formed result object"),
    "errors-null": ("print('{\"result\": \"FAIL\", \"errors\": null}'); sys.exit(1)",
                    "Temporal qualification output is not a well-formed result object"),
}


@pytest.mark.parametrize("case", sorted(RESPONDER_SCRIPTS))
def test_typed_check_refuses_a_misbehaving_qualification_process(tmp_path, monkeypatch, case):
    body, error = RESPONDER_SCRIPTS[case]
    monkeypatch.setitem(verify.QUALIFY_SCRIPT_TIMEOUT_SECONDS, "temporal", 1)
    health = verify.check_temporal(_temporal_script(tmp_path, body), execute=True)
    assert health.status is verify.ServiceStatus.UNREACHABLE
    assert health.detail["error"] == error


def test_typed_check_refuses_a_qualification_process_that_cannot_start(monkeypatch):
    def unstartable(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise PermissionError("not executable")

    monkeypatch.setattr(verify.subprocess, "run", unstartable)
    health = verify.check_temporal(ROOT, execute=True)
    assert health.status is verify.ServiceStatus.UNREACHABLE
    assert health.detail["error"] == "Temporal qualification process could not start"


def test_typed_check_keeps_well_formed_payloads_unchanged(tmp_path):
    passed = verify.check_temporal(_temporal_script(tmp_path, "print('{\"result\": \"PASS\", \"protocol\": {}}')"),
                                   execute=True)
    assert passed.status is verify.ServiceStatus.READY and passed.detail == {"result": "PASS", "protocol": {}}
    missing = verify.check_temporal(tmp_path / "absent", execute=True)
    assert missing.status is verify.ServiceStatus.UNREACHABLE and missing.detail["stderr"].startswith(
        "missing qualification script")
