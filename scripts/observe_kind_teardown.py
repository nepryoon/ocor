"""Observation of an intended owned kind teardown (v2).

PO decision REM-0019-KIND-TEARDOWN-OBSERVATION (2026-10-12, option 1). A failed
probe of an owned kind node is accepted as an intended removal only if it is bound
to the `kind delete cluster --name ocor-poc` process of the running pytest group
(sampled continuously from /proc), to the same node UUID and to that UUID's Docker
`destroy` event, inside the declared bounded window WINDOW_SECONDS. Still fatal:
node present without proven intent, crash, OOM, restart, PID change (unchanged
original checks), timeout/expired window and missing event.

Only observation changes against v1; no runtime, restart, PID, OOM or deadline
check of the borrowed repository implementation is modified, and the pytest
command, its environment and the tests are untouched.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any, NoReturn



WINDOW_SECONDS = 30.0        # declared bound: failure -> node absence and intent binding
POLL_SECONDS = 0.5
SAMPLE_SECONDS = 0.2
REMOVALS: list[dict[str, Any]] = []
REJECTIONS: list[dict[str, Any]] = []
REMOVER_OBSERVATIONS: list[dict[str, Any]] = []
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


def inspect_kubernetes_runtimes(inspector: Callable[[], dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    since = _now()
    try:
        return inspector()
    except subprocess.CalledProcessError as exc:
        command = exc.cmd
        if not isinstance(command, list) or command[:2] not in (['docker', 'exec'], ['docker', 'inspect']):
            raise
        if len(command) < 3 or (command[:2] == ['docker', 'inspect'] and len(command) != 3):
            raise
        node = command[2]
        if len(node) != 64 or any(c not in '0123456789abcdef' for c in node):
            raise
        states = []
        deadline = since + WINDOW_SECONDS
        while True:
            probe = subprocess.run(['docker', 'inspect', node], capture_output=True, text=True, timeout=10, check=False)
            if absent_node(probe, node):
                break
            if probe.returncode != 0:
                _reject(exc, 'AMBIGUOUS_INSPECT', node_id=node, stderr=probe.stderr[-500:])
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
            if _now() >= deadline:
                _reject(exc, 'WINDOW_EXPIRED_NODE_PRESENT', node_id=node, states=states[-5:],
                        window_seconds=WINDOW_SECONDS)
            _sleep(POLL_SECONDS)
        until = _now()
        events = subprocess.run(['docker', 'events', '--since', _iso(since - WINDOW_SECONDS), '--until', _iso(until),
                                 '--filter', 'container=' + node, '--format', '{{json .}}'],
                                capture_output=True, text=True, timeout=10, check=False)
        if events.returncode != 0:
            _reject(exc, 'EVENTS_UNAVAILABLE', node_id=node, stderr=events.stderr[-500:])
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
        # Exactly one fresh snapshot: no recursion or suppressed failure. The
        # original fail-closed service checks consume this result.
        return inspector()


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
            subprocess.run(["docker", "inspect", node], capture_output=True,
                           text=True, timeout=10, check=True)
            raise TeardownObservationError("known node still present without a proven removal: " + node)
        return {}

    inspect_kubernetes_runtimes(probe)
