"""Observation of an intended owned kind teardown (v2).

PO decision REM-0019-KIND-TEARDOWN-OBSERVATION (2026-10-12, option 1). A failed
probe of an owned kind node is accepted as an intended removal only if it is bound
to the `kind delete cluster --name ocor-poc` process of the running pytest group
(sampled continuously from /proc), to the same node UUID and to that UUID's Docker
`destroy` event, inside the declared bounded window WINDOW_SECONDS. Still fatal:
node present without proven intent, crash, OOM, restart, PID change (unchanged
original checks), expired window and missing event. Under PO
REM-0017-CI-KIND-INSPECT-TIMEOUT (2026-10-14), a single probe timeout enters
the same proof path; it does not extend the window or the ten-second probe.

Under PO CI-0049-KIND-BOOTSTRAP-EXEC-PROBE (2026-10-15, option 1), a failed
runtime probe `systemctl show <containerd|kubelet>` of an owned node that stays
present, running, without OOM or restart and with the same container PID is
repeated once per poll inside the same window; the node is accepted only when
that probe returns 0 with ActiveState=active (and zero NRestarts if the node was
already admitted). Every failed probe records its exit code and bounded,
redacted stderr. Cadence, probe timeout and window are unchanged.

Only observation changes against v1; no runtime, restart, PID, OOM or deadline
check of the borrowed repository implementation is modified, and the pytest
command, its environment and the tests are untouched.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any, NoReturn

from bootstrap_ci_environment import redact


WINDOW_SECONDS = 30.0        # declared bound: failure -> node absence and intent binding
POLL_SECONDS = 0.5
SAMPLE_SECONDS = 0.2
REMOVALS: list[dict[str, Any]] = []
REJECTIONS: list[dict[str, Any]] = []
REMOVER_OBSERVATIONS: list[dict[str, Any]] = []
PROBE_OBSERVATIONS: list[dict[str, Any]] = []
BOOTSTRAP_RECOVERIES: list[dict[str, Any]] = []
RUNTIME_SERVICES = ('containerd', 'kubelet')
RUNTIME_PROPERTIES = '--property=ActiveState,MainPID,NRestarts'
STDERR_LIMIT = 500
ENV_FILE = Path(__file__).resolve().parents[1] / '.ocor/bootstrap.env'
PROC = Path('/proc')
KIND_BINARY = Path(__file__).resolve().parents[1] / '.ocor/tools/bin/kind'
PYTEST_PGID: int | None = None
_now = time.time
_sleep = time.sleep
_lock = threading.Lock()
_stop = threading.Event()


def owned_remover() -> dict[str, Any] | None:
    """Observe the real kind delete in this exact pytest group; never run it."""
    if PYTEST_PGID is None:
        return None
    for folder in PROC.iterdir():
        if not folder.name.isdecimal():
            continue
        try:
            pid = int(folder.name)
            if os.getpgid(pid) != PYTEST_PGID or (folder / 'exe').resolve(strict=True) != KIND_BINARY:
                continue
            args = (folder / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')
            if args != [str(KIND_BINARY), 'delete', 'cluster', '--name', 'ocor-poc']:
                continue
            stat = (folder / 'stat').read_text().rsplit(')', 1)[1].split()
            return {'pid': pid, 'pgid': PYTEST_PGID, 'start_ticks': int(stat[19]), 'command': args}
        except (OSError, ValueError, UnicodeError):
            continue
    return None


def _sample() -> None:
    while not _stop.wait(SAMPLE_SECONDS):
        found = owned_remover()
        if not found:
            continue
        stamp = _now()
        with _lock:
            for row in REMOVER_OBSERVATIONS:
                if (row['pid'], row['start_ticks'], row['pgid']) == (found['pid'], found['start_ticks'], found['pgid']):
                    row['last_seen'] = stamp
                    break
            else:
                REMOVER_OBSERVATIONS.append(dict(found, first_seen=stamp, last_seen=stamp))


def start_sampler(pgid: int, kind_binary: Path | None = None) -> threading.Thread:
    global PYTEST_PGID, KIND_BINARY
    PYTEST_PGID = pgid
    if kind_binary is not None:
        KIND_BINARY = Path(kind_binary).resolve()
    REMOVER_OBSERVATIONS.clear()
    REMOVALS.clear()
    REJECTIONS.clear()
    PROBE_OBSERVATIONS.clear()
    BOOTSTRAP_RECOVERIES.clear()
    _stop.clear()
    thread = threading.Thread(target=_sample, daemon=True)
    thread.start()
    return thread


def stop_sampler(thread: threading.Thread) -> None:
    _stop.set()
    thread.join(timeout=5)


def absent_node(result: subprocess.CompletedProcess[str], node: str) -> bool:
    # Docker CLI 29 prints "error: no such object: <id>"; older CLIs "Error: No such object: <id>".
    stderr = result.stderr.lower()
    return (result.returncode == 1 and result.stdout.strip() == '[]'
            and ('no such object: ' + node in stderr or 'no such container: ' + node in stderr))


def _iso(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, UTC).isoformat()


def _secrets() -> list[str]:
    try:
        lines = ENV_FILE.read_text().splitlines()
    except OSError:
        return []
    return [line.split('=', 1)[1] for line in lines
            if '=' in line and line.split('=', 1)[0].endswith(('TOKEN', 'PASSWORD'))]


def bounded_stderr(stderr: str | bytes | None) -> str:
    """Redact generated credentials and assignments first, then keep the tail."""
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors='replace')
    text = redact(stderr or '', _secrets())
    text = re.sub(r'(?i)\b([A-Z0-9_]*(?:TOKEN|PASSWORD|SECRET)[A-Z0-9_]*)=\S+', r'\1=[REDACTED]', text)
    return text[-STDERR_LIMIT:]


def probe_failure(exc: subprocess.CalledProcessError | subprocess.TimeoutExpired) -> dict[str, Any]:
    if isinstance(exc, subprocess.CalledProcessError):
        return {'returncode': exc.returncode, 'stderr': bounded_stderr(exc.stderr)}
    return {'returncode': None, 'timeout_seconds': exc.timeout, 'stderr': bounded_stderr(exc.stderr)}


def run_probe(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
    """Observe latency without changing a probe's arguments, cadence or timeout."""
    started = _now()
    monotonic_start = time.monotonic()
    observation: dict[str, Any] = {'command': command, 'started_at': _iso(started)}
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(command, **options)
        observation['returncode'] = result.returncode
        if result.returncode != 0:
            observation['stderr'] = bounded_stderr(result.stderr)
        return result
    except (subprocess.SubprocessError, OSError) as exc:
        observation.update(error_type=type(exc).__name__, error=str(exc))
        if isinstance(exc, (subprocess.CalledProcessError, subprocess.TimeoutExpired)):
            observation.update(probe_failure(exc))
        raise
    finally:
        observation.update(finished_at=_iso(_now()), duration_seconds=time.monotonic() - monotonic_start)
        PROBE_OBSERVATIONS.append(observation)


def _reject(exc: BaseException, reason: str, **facts: Any) -> NoReturn:
    REJECTIONS.append({'reason': reason, 'observed_at': _iso(_now()), 'error': str(exc), **facts})
    raise exc


def _bound_remover(since: float, destroy_at: float) -> dict[str, Any] | None:
    """kind delete of this pytest group alive inside [since - WINDOW, destroy] and seen no later than destroy."""
    with _lock:
        rows = [dict(r) for r in REMOVER_OBSERVATIONS]
    for row in rows:
        if (row.get('pgid') == PYTEST_PGID and row['first_seen'] <= destroy_at
                and row['last_seen'] >= since - WINDOW_SECONDS):
            return row
    return None


def runtime_probe(command: Any) -> bool:
    """The exact `systemctl show` runtime probe of inspect_kubernetes_runtimes_raw."""
    return (isinstance(command, list) and len(command) == 7 and command[:2] == ['docker', 'exec']
            and command[3:5] == ['systemctl', 'show'] and command[5] in RUNTIME_SERVICES
            and command[6] == RUNTIME_PROPERTIES)


def inspect_kubernetes_runtimes(inspector: Callable[[], dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    since = _now()
    container_pids: dict[str, Any] = {}
    while True:
        try:
            return _require_observed_nodes(inspector(), container_pids)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            command = exc.cmd
            if not isinstance(command, list) or command[:2] not in (['docker', 'exec'], ['docker', 'inspect']):
                raise
            if len(command) < 3 or (command[:2] == ['docker', 'inspect'] and len(command) != 3):
                raise
            node = command[2]
            if len(node) != 64 or any(c not in '0123456789abcdef' for c in node):
                raise
            if _observe_failed_probe(exc, command, node, since, container_pids):
                # Same probe returned to 0 and active inside the window: take a
                # fresh snapshot, still bounded by the original deadline.
                continue
            # Exactly one fresh snapshot: no recursion or suppressed failure. The
            # original fail-closed service checks consume this result.
            return _require_observed_nodes(inspector(), container_pids)


def _require_observed_nodes(snapshot: dict[str, dict[str, Any]],
                            container_pids: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """An observed UUID cannot disappear on the fresh snapshot without v2 proof.

    The campaign history may still be empty during bootstrap. Retain the UUIDs
    seen in this inspection, including across successful runtime-probe recovery.
    A missing node is rejected; a recovery observation alone is no removal proof.
    """
    for node in container_pids:
        if any(row['node_id'] == node for row in REMOVALS):
            continue
        if any(node + ':' + service not in snapshot for service in RUNTIME_SERVICES):
            _reject(TeardownObservationError('observed node missing after probe recovery: ' + node),
                    'RECOVERED_NODE_MISSING_FROM_SNAPSHOT', node_id=node)
    return snapshot


def _observe_failed_probe(exc: subprocess.CalledProcessError | subprocess.TimeoutExpired, command: list[str],
                          node: str, since: float, container_pids: dict[str, Any]) -> bool:
    """True: bootstrap probe recovered. False: owned removal proven. Otherwise re-raise exc."""
    retry = runtime_probe(command)
    initial = probe_failure(exc)
    retries: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    deadline = since + WINDOW_SECONDS
    while True:
        if _now() >= deadline:
            reason = ('WINDOW_EXPIRED_NODE_PRESENT' if states and 'running' in states[-1]
                      else 'WINDOW_EXPIRED_DAEMON_UNAVAILABLE')
            _reject(exc, reason, node_id=node, states=states[-5:], window_seconds=WINDOW_SECONDS,
                    failed_probe=command, initial_failure=initial, probe_retries=retries[-5:])
        try:
            probe = run_probe(['docker', 'inspect', node], capture_output=True, text=True, timeout=10, check=False)
        except subprocess.TimeoutExpired:
            states.append({'probe': 'TIMEOUT', 'at': _iso(_now())})
            if _now() >= deadline:
                _reject(exc, 'WINDOW_EXPIRED_DAEMON_UNAVAILABLE', node_id=node, states=states[-5:],
                        window_seconds=WINDOW_SECONDS)
            _sleep(POLL_SECONDS)
            continue
        if absent_node(probe, node):
            if _now() > deadline:
                _reject(exc, 'WINDOW_EXPIRED_ABSENCE', node_id=node, window_seconds=WINDOW_SECONDS)
            break
        if probe.returncode != 0:
            _reject(exc, 'AMBIGUOUS_INSPECT', node_id=node, stderr=bounded_stderr(probe.stderr))
        rows = json.loads(probe.stdout)
        pending = rows[0] if len(rows) == 1 else {}
        fact = {'running': pending.get('State', {}).get('Running'), 'status': pending.get('State', {}).get('Status'),
                'oom': pending.get('State', {}).get('OOMKilled'), 'restarts': pending.get('RestartCount'),
                'at': _iso(_now())}
        states.append(fact)
        if (len(rows) != 1 or pending.get('Id') != node or not pending.get('Name', '').startswith('/ocor-poc-')
                or pending.get('Config', {}).get('Labels', {}).get('io.x-k8s.kind.cluster') != 'ocor-poc'):
            _reject(exc, 'NODE_IDENTITY_MISMATCH', node_id=node, states=states)
        if fact['oom'] is not False or fact['restarts'] != 0:
            _reject(exc, 'OOM_OR_RESTART_STATE', node_id=node, states=states)
        if retry and fact['running'] is True and fact['status'] == 'running':
            pid = pending.get('State', {}).get('Pid')
            fact['pid'] = pid
            if container_pids.setdefault(node, pid) != pid:
                _reject(exc, 'CONTAINER_PID_CHANGED', node_id=node, states=states,
                        container_pid=container_pids[node], failed_probe=command)
            admitted = 'ocor-bootstrap_ocor-bootstrap' in pending.get('NetworkSettings', {}).get('Networks', {})
            attempt: dict[str, Any] = {'at': _iso(_now())}
            retries.append(attempt)
            try:
                again = run_probe(command, capture_output=True, text=True, timeout=10, check=False)
            except subprocess.TimeoutExpired as timeout:
                attempt.update(probe_failure(timeout))
            else:
                values = dict(line.split('=', 1) for line in again.stdout.splitlines() if '=' in line)
                attempt.update(returncode=again.returncode, active=values.get('ActiveState'),
                               restarts=values.get('NRestarts'), main_pid=values.get('MainPID'))
                if again.returncode != 0:
                    attempt['stderr'] = bounded_stderr(again.stderr)
                elif admitted and values.get('NRestarts') != '0':
                    _reject(exc, 'ADMITTED_NODE_SERVICE_RESTARTED', node_id=node, states=states,
                            failed_probe=command, probe_retries=retries)
                elif values.get('ActiveState') == 'active' and _now() < deadline:
                    BOOTSTRAP_RECOVERIES.append({
                        'status': 'BOOTSTRAP_EXEC_PROBE_RECOVERED', 'node_id': node, 'service': command[5],
                        'since': _iso(since), 'recovered_at': _iso(_now()), 'window_seconds': WINDOW_SECONDS,
                        'failed_probe': command, 'initial_failure': initial, 'probe_retries': retries,
                        'states': states, 'admitted': admitted, 'container_pid': pid})
                    return True
        if _now() >= deadline:
            _reject(exc, 'WINDOW_EXPIRED_NODE_PRESENT', node_id=node, states=states[-5:],
                    window_seconds=WINDOW_SECONDS, failed_probe=command, initial_failure=initial,
                    probe_retries=retries[-5:])
        _sleep(POLL_SECONDS)
    until = _now()
    try:
        events = run_probe(['docker', 'events', '--since', _iso(since - WINDOW_SECONDS), '--until', _iso(until),
                            '--filter', 'container=' + node, '--format', '{{json .}}'],
                           capture_output=True, text=True, timeout=10, check=False)
    except subprocess.TimeoutExpired:
        _reject(exc, 'EVENTS_UNAVAILABLE', node_id=node, detail='event probe timeout')
    if events.returncode != 0:
        _reject(exc, 'EVENTS_UNAVAILABLE', node_id=node, stderr=bounded_stderr(events.stderr))
    owned = []
    for line in events.stdout.splitlines():
        event = json.loads(line)
        actor = event.get('Actor', {})
        attrs = actor.get('Attributes', {})
        if event.get('Type') == 'container' and actor.get('ID') == node and event.get('Action') in ('oom', 'restart'):
            _reject(exc, 'OOM_OR_RESTART_EVENT', node_id=node, event=event)
        if (event.get('Type') == 'container' and event.get('Action') == 'destroy' and actor.get('ID') == node
                and attrs.get('name', '').startswith('ocor-poc-') and attrs.get('io.x-k8s.kind.cluster') == 'ocor-poc'):
            owned.append({'node_id': node, 'name': attrs['name'], 'action': 'destroy',
                          'timeNano': event.get('timeNano')})
    if len(owned) != 1 or not isinstance(owned[0]['timeNano'], int):
        _reject(exc, 'OWNED_DESTROY_EVENT_MISSING', node_id=node, states=states, destroy_events=owned)
    destroy_at = int(owned[0]['timeNano']) / 1e9
    if not since - WINDOW_SECONDS <= destroy_at <= until:
        _reject(exc, 'DESTROY_OUTSIDE_WINDOW', node_id=node, destroy_events=owned)
    remover = _bound_remover(since, destroy_at)
    if remover is None:
        _reject(exc, 'NO_OWNED_REMOVER_IN_PYTEST_GROUP', node_id=node, states=states, destroy_events=owned,
                pytest_pgid=PYTEST_PGID)
    REMOVALS.append({'status': 'OWNED_KIND_TEARDOWN_OBSERVED', 'node_id': node, 'since': _iso(since),
                     'until': _iso(until), 'window_seconds': WINDOW_SECONDS, 'states': states,
                     'destroy_events': owned, 'owned_remover': {
                         **remover, 'first_seen': _iso(remover['first_seen']),
                         'last_seen': _iso(remover['last_seen'])}, 'failed_probe': command})
    return False


class TeardownObservationError(RuntimeError):
    """A previously observed node disappeared without complete removal proof."""


def confirm_missing_node(node: str) -> None:
    if any(row["node_id"] == node for row in REMOVALS):
        return  # The same immutable UUID was already proven removed.
    first = True

    def probe() -> dict[str, dict[str, Any]]:
        nonlocal first
        if first:
            first = False
            # Produce a real failed inspect, then consume its actual UUID/error
            # through the same v2 proof path; do not fabricate a failed command.
            run_probe(["docker", "inspect", node], capture_output=True,
                           text=True, timeout=10, check=True)
            raise TeardownObservationError("known node still present without a proven removal: " + node)
        return {}

    inspect_kubernetes_runtimes(probe)
