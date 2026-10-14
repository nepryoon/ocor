"""REM-0019-KIND-TEARDOWN-OBSERVATION (PO 2026-10-12, option 1): deterministic proofs.

Local observation handling only. Docker and /proc are simulated; no mock qualifies
an OCOR backend or a runtime case. A removal is accepted only when bound to the kind
delete process of the running pytest group, the same node UUID and its Docker
destroy event inside the declared bounded window. Crash, OOM, restart, PID change,
live node without intent, expired window and missing event stay fatal.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import run_qualifying_campaign as original
import observe_kind_teardown as adapter

ID = 'c' * 64
PGID = 4242
T0 = 1_800_000_000.0  # simulated wall clock, seconds
NODE = dict(Id=ID, Name='/ocor-poc-control-plane', State=dict(Running=True, OOMKilled=False, Status='running'),
            RestartCount=0, Config=dict(Labels={'io.x-k8s.kind.cluster': 'ocor-poc'}),
            NetworkSettings=dict(Networks={'ocor-bootstrap_ocor-bootstrap': {}}))
REMOVER = dict(pid=777, pgid=PGID, start_ticks=99, command=['/x/kind', 'delete', 'cluster', '--name', 'ocor-poc'])
FATAL = (subprocess.CalledProcessError, original.CampaignError)


class Clock:
    def __init__(self):
        self.t = T0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class Docker:
    """Pending states seen by the adapter after the failed exec, then absence."""

    def __init__(self, clock, pending, events=('destroy',), event_id=ID, cluster='ocor-poc', inspect_error=None):
        self.clock = clock
        self.pending = list(pending)  # node states returned before absence; None means absent
        self.events = events
        self.event_id = event_id
        self.cluster = cluster
        self.inspect_error = inspect_error
        self.first = True
        self.destroy_at = None

    def run(self, cmd, **kwargs):
        code, out, err = 0, '', ''
        if cmd[:2] == ['docker', 'ps']:
            out = '' if self.destroy_at is not None else ID + '\n'
        elif cmd[:2] == ['docker', 'inspect'] and self.first:
            self.first = False
            out = json.dumps([NODE])
        elif cmd[:2] == ['docker', 'inspect']:
            state = self.pending.pop(0) if self.pending else None
            if state is None:
                if self.destroy_at is None:
                    self.destroy_at = self.clock.now() - 0.1
                code, out, err = 1, '[]', self.inspect_error or 'Error: No such object: ' + ID
            else:
                out = json.dumps([state])
        elif cmd[:2] == ['docker', 'exec']:
            code, err = 1, 'Error response from daemon: container is not running'
        elif cmd[:2] == ['docker', 'events']:
            stamp = int(((self.destroy_at or self.clock.now()) * 1e9))
            out = ''.join(json.dumps(dict(Type='container', Action=action, timeNano=stamp,
                                          Actor=dict(ID=self.event_id, Attributes={
                                              'name': 'ocor-poc-control-plane',
                                              'io.x-k8s.kind.cluster': self.cluster}))) + '\n'
                          for action in self.events)
        else:
            raise AssertionError('unexpected command ' + repr(cmd))
        result = subprocess.CompletedProcess(cmd, code, out, err)
        if code and kwargs.get('check'):
            raise subprocess.CalledProcessError(code, cmd, output=out, stderr=err)
        return result


def state(running, oom=False, restarts=0, node_id=ID, name='/ocor-poc-control-plane'):
    return {**NODE, 'Id': node_id, 'Name': name, 'RestartCount': restarts,
            'State': dict(Running=running, OOMKilled=oom, Status='running' if running else 'exited')}


class TeardownObservation(unittest.TestCase):
    def inspect(self, pending, removers=(), **docker):
        clock = Clock()
        scenario = Docker(clock, pending, **docker)
        observations = [dict(r, first_seen=T0 + a, last_seen=T0 + b) for r, a, b in removers]
        with patch.object(subprocess, 'run', scenario.run), \
                patch.object(adapter, 'PYTEST_PGID', PGID, create=True), \
                patch.object(adapter, 'REMOVER_OBSERVATIONS', observations, create=True), \
                patch.object(adapter, 'REJECTIONS', [], create=True) as rejections, \
                patch.object(adapter, 'REMOVALS', []) as removals, \
                patch.object(adapter, '_now', clock.now, create=True), \
                patch.object(adapter, '_sleep', clock.sleep, create=True), \
                patch.object(adapter, 'owned_remover', return_value=dict(REMOVER) if removers else None), \
                patch.object(adapter, 'removal_wait', lambda: clock.sleep(2), create=True):
            try:
                return adapter.inspect_kubernetes_runtimes(original.inspect_kubernetes_runtimes_raw), removals, rejections
            except FATAL:
                self.last_rejections = list(rejections)
                raise

    # ---- positive: intended owned removal is recognised -------------------------------

    def test_removal_in_progress_running_then_stopped_then_absent(self):
        # The order-collection attempt-1 shape: exec fails while docker rm -f is
        # killing the node, inspect still reports Running before the die event.
        current, removals, rejections = self.inspect(
            [state(True), state(False)], removers=[(REMOVER, -1.0, 0.6)])
        self.assertEqual(current, {})
        self.assertEqual(len(removals), 1)
        self.assertEqual(removals[0]['node_id'], ID)
        self.assertEqual(removals[0]['owned_remover']['pid'], 777)
        self.assertEqual(rejections, [])

    def test_already_absent_with_bound_remover(self):
        current, removals, _ = self.inspect([None], removers=[(REMOVER, -0.8, -0.05)])
        self.assertEqual(current, {})
        self.assertEqual(removals[0]['status'], 'OWNED_KIND_TEARDOWN_OBSERVED')

    def test_docker29_absence_message_is_recognised(self):
        # Real Docker CLI 29.x output observed on this host: "error: no such object: <id>".
        current, removals, _ = self.inspect([state(False), None], removers=[(REMOVER, -1, 0.3)],
                                            inspect_error='error: no such object: ' + ID)
        self.assertEqual(current, {})
        self.assertEqual(len(removals), 1)

    # ---- negative: everything else stays fail-closed ----------------------------------

    def test_crash_node_present_without_intent_is_fatal(self):
        with self.assertRaises(FATAL):
            self.inspect([state(False)] * 200)
        self.assertEqual(self.last_rejections[-1]['reason'], 'WINDOW_EXPIRED_NODE_PRESENT')

    def test_live_node_without_intent_is_fatal(self):
        with self.assertRaises(FATAL):
            self.inspect([state(True)] * 200)

    def test_destroy_without_bound_remover_is_fatal(self):
        with self.assertRaises(FATAL):
            self.inspect([state(False), None])
        self.assertEqual(self.last_rejections[-1]['reason'], 'NO_OWNED_REMOVER_IN_PYTEST_GROUP')

    def test_oom_state_or_event_is_fatal(self):
        with self.assertRaises(FATAL):
            self.inspect([state(False, oom=True), None], removers=[(REMOVER, -1, 1)])
        with self.assertRaises(FATAL):
            self.inspect([state(False), None], removers=[(REMOVER, -1, 1)], events=('oom', 'destroy'))

    def test_restart_state_or_event_is_fatal(self):
        with self.assertRaises(FATAL):
            self.inspect([state(True, restarts=1), None], removers=[(REMOVER, -1, 1)])
        with self.assertRaises(FATAL):
            self.inspect([state(False), None], removers=[(REMOVER, -1, 1)], events=('restart', 'destroy'))

    def test_window_expired_with_intent_is_fatal(self):
        with self.assertRaises(FATAL):
            self.inspect([state(False)] * 200, removers=[(REMOVER, -1, 100)])
        self.assertEqual(self.last_rejections[-1]['reason'], 'WINDOW_EXPIRED_NODE_PRESENT')

    def test_missing_foreign_or_unowned_destroy_event_is_fatal(self):
        for docker in (dict(events=()), dict(event_id='d' * 64), dict(cluster='other')):
            with self.subTest(**docker), self.assertRaises(FATAL):
                self.inspect([state(False), None], removers=[(REMOVER, -1, 1)], **docker)

    def test_remover_outside_window_or_after_destroy_is_fatal(self):
        stale = (REMOVER, -400, -300)       # seen long before the failure: not this teardown
        late = (REMOVER, 5, 6)              # first seen after the destroy event
        foreign_group = (dict(REMOVER, pgid=PGID + 1), -1, 1)
        for remover in (stale, late, foreign_group):
            with self.subTest(remover=remover[1:]), self.assertRaises(FATAL):
                self.inspect([state(False), None], removers=[remover])

    def test_daemon_unavailable_or_identity_mismatch_is_fatal(self):
        with self.assertRaises(FATAL):
            self.inspect([None], removers=[(REMOVER, -1, 1)], inspect_error='Cannot connect to the Docker daemon')
        for pending in ([state(False, node_id='e' * 64)], [state(False, name='/foreign')]):
            with self.subTest(pending=pending[0]['Name']), self.assertRaises(FATAL):
                self.inspect(pending, removers=[(REMOVER, -1, 1)])

    def test_pid_change_and_failed_service_remain_fatal(self):
        history = {}
        healthy = {ID + ':containerd': dict(restarts=0, active='active', pid=111, admitted=True)}
        original.check_kubernetes_runtimes(history, healthy)
        with self.assertRaises(original.CampaignError):
            original.check_kubernetes_runtimes(history, {ID + ':containerd': dict(restarts=0, active='active', pid=222,
                                                                                   admitted=True)})
        with self.assertRaises(original.CampaignError):
            original.check_kubernetes_runtimes({}, {ID + ':containerd': dict(restarts=1, active='active', pid=111,
                                                                              admitted=True)})

    def test_sampler_requires_exact_group_binary_and_arguments(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            pid = root / '42'
            pid.mkdir()
            binary = root / 'kind'
            binary.write_text('fixture')
            (pid / 'exe').symlink_to(binary)
            (pid / 'stat').write_text('42 (kind) ' + ' '.join(['S'] + ['0'] * 18 + ['123']))
            (pid / 'cmdline').write_bytes((str(binary) + '\0delete\0cluster\0--name\0ocor-poc\0').encode())
            with patch.object(adapter, 'PROC', root), patch.object(adapter, 'KIND_BINARY', binary.resolve()), \
                    patch.object(adapter, 'PYTEST_PGID', 43), patch.object(os, 'getpgid', return_value=43):
                self.assertEqual(adapter.owned_remover()['pid'], 42)
                with patch.object(os, 'getpgid', return_value=44):
                    self.assertIsNone(adapter.owned_remover())
                (pid / 'cmdline').write_bytes((str(binary) + '\0delete\0cluster\0--name\0foreign\0').encode())
                self.assertIsNone(adapter.owned_remover())
                (pid / 'cmdline').write_bytes((str(binary) + '\0delete\0cluster\0--name\0ocor-poc\0').encode())
                with patch.object(adapter, 'KIND_BINARY', root / 'foreign-kind'):
                    self.assertIsNone(adapter.owned_remover())


if __name__ == '__main__':
    unittest.main()
