"""REM-0019-KIND-TEARDOWN-OBSERVATION (PO 2026-10-12, option 1): deterministic proofs.

Local observation handling only. Docker and /proc are simulated; no mock qualifies
an OCOR backend or a runtime case. A removal is accepted only when bound to the kind
delete process of the running pytest group, the same node UUID and its Docker
destroy event inside the declared bounded window. Crash, OOM, restart, PID change,
live node without intent, expired window and missing event stay fatal.
"""
import ast
import hashlib
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


class ProbeTimeoutObservation(unittest.TestCase):
    """PO REM-0017-CI-KIND-INSPECT-TIMEOUT: the probe is not the window."""

    def exercise(self, pending, *, failed_command=None, events=('destroy',), removers=True):
        clock = Clock()
        command = failed_command or ['docker', 'inspect', ID]
        scenario = Docker(clock, [], events=events)
        scenario.first = False
        responses = iter(pending)
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv[:2] == ['docker', 'inspect']:
                row = next(responses, 'TIMEOUT')
                if row == 'TIMEOUT':
                    clock.sleep(10)
                    raise subprocess.TimeoutExpired(argv, 10)
                if row is not None:
                    return subprocess.CompletedProcess(argv, 0, json.dumps([row]), '')
            return scenario.run(argv, **kwargs)

        first = True

        def inspector():
            nonlocal first
            if first:
                first = False
                clock.sleep(10)
                raise subprocess.TimeoutExpired(command, 10)
            return {}

        samples = [dict(REMOVER, first_seen=T0, last_seen=T0 + 20)] if removers else []
        with patch.object(subprocess, 'run', run), patch.object(adapter, '_now', clock.now), \
                patch.object(adapter, '_sleep', clock.sleep), patch.object(adapter, 'PYTEST_PGID', PGID), \
                patch.object(adapter, 'REMOVER_OBSERVATIONS', samples), \
                patch.object(adapter, 'PROBE_OBSERVATIONS', [], create=True) as probes, \
                patch.object(adapter, 'REMOVALS', []) as removals, \
                patch.object(adapter, 'REJECTIONS', []) as rejections:
            try:
                result = adapter.inspect_kubernetes_runtimes(inspector)
                return result, list(removals), list(probes), calls
            finally:
                self.rejections = list(rejections)
                self.elapsed = clock.now() - T0

    def test_inspect_and_exec_timeout_then_proven_absence_accepted(self):
        for command in (['docker', 'inspect', ID], ['docker', 'exec', ID, 'systemctl', 'show', 'containerd']):
            with self.subTest(command=command):
                result, removals, probes, calls = self.exercise(['TIMEOUT', None], failed_command=command)
                self.assertEqual(result, {})
                self.assertEqual(removals[0]['status'], 'OWNED_KIND_TEARDOWN_OBSERVED')
                self.assertEqual(removals[0]['failed_probe'], command)
                self.assertTrue(probes)
                self.assertTrue(all('duration_seconds' in p and 'started_at' in p and 'finished_at' in p for p in probes))
                self.assertTrue(all(options['timeout'] == 10 for _, options in calls))

    def test_timeout_node_present_at_window_expiry_rejected(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.exercise([state(True)] * 100)
        self.assertEqual(self.rejections[-1]['reason'], 'WINDOW_EXPIRED_NODE_PRESENT')
        self.assertIn('observed_at', self.rejections[-1])

    def test_daemon_timeout_expires_without_removal_proof(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.exercise(['TIMEOUT'] * 4)
        self.assertEqual(self.rejections[-1]['reason'], 'WINDOW_EXPIRED_DAEMON_UNAVAILABLE')
        self.assertLessEqual(self.elapsed, adapter.WINDOW_SECONDS + 10)

    def test_timeout_absence_without_destroy_or_remover_rejected(self):
        for kwargs, reason in ((dict(events=()), 'OWNED_DESTROY_EVENT_MISSING'),
                               (dict(removers=False), 'NO_OWNED_REMOVER_IN_PYTEST_GROUP')):
            with self.subTest(reason=reason), self.assertRaises(subprocess.TimeoutExpired):
                self.exercise([None], **kwargs)
            self.assertEqual(self.rejections[-1]['reason'], reason)

    def test_timeout_oom_or_restart_state_and_event_rejected(self):
        for row in (state(False, oom=True), state(True, restarts=1)):
            with self.subTest(row=row), self.assertRaises(subprocess.TimeoutExpired):
                self.exercise([row, None])
            self.assertEqual(self.rejections[-1]['reason'], 'OOM_OR_RESTART_STATE')
        for action in ('oom', 'restart'):
            with self.subTest(action=action), self.assertRaises(subprocess.TimeoutExpired):
                self.exercise([None], events=(action, 'destroy'))
            self.assertEqual(self.rejections[-1]['reason'], 'OOM_OR_RESTART_EVENT')

    def test_foreign_timeout_is_not_suppressed(self):
        for command in (['docker', 'ps'], ['docker', 'inspect', 'unowned-name'], ['other', 'exec', ID]):
            with self.subTest(command=command), self.assertRaises(subprocess.TimeoutExpired):
                self.exercise([None], failed_command=command)
            self.assertEqual(self.rejections, [])

    def test_confirm_missing_node_timeout_enters_same_proof_path(self):
        clock = Clock()
        scenario = Docker(clock, [None])
        scenario.first = False
        original_run = scenario.run
        first = True

        def run(command, **kwargs):
            nonlocal first
            if first:
                first = False
                clock.sleep(10)
                raise subprocess.TimeoutExpired(command, 10)
            return original_run(command, **kwargs)

        with patch.object(subprocess, 'run', run), patch.object(adapter, '_now', clock.now), \
                patch.object(adapter, 'PYTEST_PGID', PGID), patch.object(adapter, 'REMOVALS', []) as removals, \
                patch.object(adapter, 'REMOVER_OBSERVATIONS', [dict(REMOVER, first_seen=T0, last_seen=T0 + 9)]):
            adapter.confirm_missing_node(ID)
            self.assertEqual(removals[0]['node_id'], ID)


BOOT_STDERR = 'System has not been booted with systemd as init system (PID 1). Can\'t operate.\n'


def booting(*, pid=4242, running=True, oom=False, restarts=0, admitted=False):
    networks = {'ocor-bootstrap_ocor-bootstrap': {}} if admitted else {'kind': {}}
    return {**NODE, 'RestartCount': restarts, 'NetworkSettings': dict(Networks=networks),
            'State': dict(Running=running, OOMKilled=oom, Status='running' if running else 'exited', Pid=pid)}


class BootstrapExecProbe(unittest.TestCase):
    """PO CI-0049-KIND-BOOTSTRAP-EXEC-PROBE (2026-10-15, option 1): the failed bootstrap
    `systemctl show` of a present owned node is repeated at each poll inside the same
    30 s window; accepted only when the same probe returns 0 with ActiveState=active
    (and zero NRestarts if the node was admitted). Docker is simulated; nothing here
    qualifies an OCOR backend or a runtime case."""

    def exercise(self, nodes, probes, *, kubelet='ActiveState=active\nMainPID=7\nNRestarts=0\n', env_file=None, disappear_after_recovery=False):
        """nodes: docker inspect <ID> rows during the window (last repeats);
        probes: containerd results in order, (code, stdout, stderr) or 'TIMEOUT' (last repeats)."""
        clock = Clock()
        nodes, probes = list(nodes), list(probes)
        calls = []
        snapshots = 0

        def run(argv, **kwargs):
            nonlocal snapshots
            calls.append((list(argv), dict(kwargs)))
            code, out, err = 0, '', ''
            if argv[:2] == ['docker', 'ps']:
                snapshots += 1
                out = '' if disappear_after_recovery and snapshots > 1 else ID + '\n'
            elif argv[:2] == ['docker', 'inspect']:
                row = nodes.pop(0) if len(nodes) > 1 else nodes[0]
                if row is None:
                    code, out, err = 1, '[]', 'Error: No such object: ' + ID
                else:
                    out = json.dumps([row])
            elif argv[:2] == ['docker', 'exec'] and argv[5] == 'containerd':
                outcome = probes.pop(0) if len(probes) > 1 else probes[0]
                if outcome == 'TIMEOUT':
                    clock.sleep(10)
                    raise subprocess.TimeoutExpired(argv, 10)
                clock.sleep(0.04)
                code, out, err = outcome
            elif argv[:2] == ['docker', 'exec'] and argv[5] == 'kubelet':
                out = kubelet
            elif argv[:2] == ['docker', 'events']:
                out = ''
            else:
                raise AssertionError('unexpected command ' + repr(argv))
            if code and kwargs.get('check'):
                raise subprocess.CalledProcessError(code, argv, output=out, stderr=err)
            return subprocess.CompletedProcess(argv, code, out, err)

        patches = [patch.object(subprocess, 'run', run), patch.object(adapter, '_now', clock.now),
                   patch.object(adapter, '_sleep', clock.sleep), patch.object(adapter, 'PYTEST_PGID', PGID),
                   patch.object(adapter, 'REMOVER_OBSERVATIONS', []), patch.object(adapter, 'REMOVALS', []),
                   patch.object(adapter, 'REJECTIONS', []), patch.object(adapter, 'PROBE_OBSERVATIONS', [])]
        if hasattr(adapter, 'BOOTSTRAP_RECOVERIES'):
            patches.append(patch.object(adapter, 'BOOTSTRAP_RECOVERIES', []))
        if env_file is not None:
            patches.append(patch.object(adapter, 'ENV_FILE', env_file, create=True))
        for p in patches:
            p.start()
        try:
            return adapter.inspect_kubernetes_runtimes(original.inspect_kubernetes_runtimes_raw)
        finally:
            self.rejections = list(adapter.REJECTIONS)
            self.removals = list(adapter.REMOVALS)
            self.probes = list(adapter.PROBE_OBSERVATIONS)
            self.recoveries = list(getattr(adapter, 'BOOTSTRAP_RECOVERIES', []))
            self.elapsed = clock.now() - T0
            self.calls = calls
            for p in reversed(patches):
                p.stop()

    FAIL = (1, '', BOOT_STDERR)
    ACTIVE = (0, 'ActiveState=active\nMainPID=118\nNRestarts=0\n', '')

    # ---- positive -------------------------------------------------------------------------

    def test_failed_bootstrap_probe_then_success_inside_window_is_accepted(self):
        current = self.exercise([booting()], [self.FAIL, self.FAIL, self.FAIL, self.ACTIVE])
        self.assertEqual(current[ID + ':containerd'], dict(restarts=0, active='active', pid=118, admitted=False))
        self.assertEqual(current[ID + ':kubelet']['active'], 'active')
        self.assertEqual(self.rejections, [])
        self.assertEqual(self.removals, [])
        self.assertEqual(len(self.recoveries), 1)
        recovery = self.recoveries[0]
        self.assertEqual(recovery['status'], 'BOOTSTRAP_EXEC_PROBE_RECOVERED')
        self.assertEqual((recovery['node_id'], recovery['service']), (ID, 'containerd'))
        self.assertEqual(recovery['initial_failure']['returncode'], 1)
        self.assertIn('not been booted with systemd', recovery['initial_failure']['stderr'])
        self.assertLessEqual(self.elapsed, adapter.WINDOW_SECONDS)
        # Probe identity unchanged: same argv, ten-second timeout, one retry per poll.
        retried = [c for c in self.calls if c[0][:2] == ['docker', 'exec'] and c[0][5] == 'containerd']
        self.assertTrue(all(c[0] == retried[0][0] and c[1]['timeout'] == 10 for c in retried))
        self.assertEqual(len(retried), 5)  # failed original + 3 retries, then the fresh snapshot

    def test_admitted_node_with_zero_restarts_is_accepted(self):
        current = self.exercise([booting(admitted=True)], [self.FAIL, self.ACTIVE])
        self.assertTrue(current[ID + ':containerd']['admitted'])
        self.assertEqual(self.recoveries[0]['admitted'], True)

    def test_probe_timeout_then_success_inside_window_is_accepted(self):
        self.exercise([booting()], [self.FAIL, 'TIMEOUT', self.ACTIVE])
        self.assertEqual(len(self.recoveries), 1)
        self.assertEqual(self.rejections, [])

    def test_failed_probe_then_intended_removal_keeps_v2_proof_path(self):
        # A node that disappears during the retries still needs destroy + remover proof.
        with self.assertRaises(subprocess.CalledProcessError):
            self.exercise([booting(), None], [self.FAIL])
        self.assertEqual(self.rejections[-1]['reason'], 'OWNED_DESTROY_EVENT_MISSING')
        self.assertEqual(self.recoveries, [])

    # ---- negative -------------------------------------------------------------------------

    def test_disappearance_after_recovery_with_empty_history_is_rejected(self):
        # VF-001: the UUID was seen during recovery, then fresh docker ps is empty.
        # No previous campaign snapshot exists to call confirm_missing_node for it.
        with self.assertRaises(adapter.TeardownObservationError):
            self.exercise([booting()], [self.FAIL, self.ACTIVE], disappear_after_recovery=True)
        self.assertEqual(self.rejections[-1]['reason'], 'RECOVERED_NODE_MISSING_FROM_SNAPSHOT')
        self.assertEqual(self.rejections[-1]['node_id'], ID)
        self.assertEqual(len(self.recoveries), 1)
        self.assertEqual(self.removals, [])
        self.assertLess(self.elapsed, adapter.WINDOW_SECONDS)

    def test_probe_failing_until_window_expiry_is_rejected(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.exercise([booting()], [self.FAIL])
        self.assertEqual(self.rejections[-1]['reason'], 'WINDOW_EXPIRED_NODE_PRESENT')
        self.assertEqual(self.recoveries, [])
        self.assertLessEqual(self.elapsed, adapter.WINDOW_SECONDS + 1)

    def test_probe_never_active_until_window_expiry_is_rejected(self):
        for state_text in ('ActiveState=activating\nMainPID=0\nNRestarts=0\n',
                           'ActiveState=failed\nMainPID=0\nNRestarts=0\n', 'garbage'):
            with self.subTest(state=state_text), self.assertRaises(subprocess.CalledProcessError):
                self.exercise([booting()], [self.FAIL, (0, state_text, '')])
            self.assertEqual(self.rejections[-1]['reason'], 'WINDOW_EXPIRED_NODE_PRESENT')
            self.assertEqual(self.recoveries, [])

    def test_oom_restart_or_pid_change_during_window_is_rejected(self):
        for rows, reason in (([booting(), booting(), booting(oom=True)], 'OOM_OR_RESTART_STATE'),
                             ([booting(), booting(), booting(restarts=1)], 'OOM_OR_RESTART_STATE'),
                             ([booting(pid=4242), booting(pid=4242), booting(pid=4343)], 'CONTAINER_PID_CHANGED')):
            with self.subTest(reason=reason, row=rows[-1]['State']), self.assertRaises(subprocess.CalledProcessError):
                self.exercise(rows, [self.FAIL, self.FAIL, self.ACTIVE])
            self.assertEqual(self.rejections[-1]['reason'], reason)
            self.assertEqual(self.recoveries, [])

    def test_admitted_node_with_service_restarts_is_rejected(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.exercise([booting(admitted=True)], [self.FAIL, (0, 'ActiveState=active\nMainPID=118\nNRestarts=1\n', '')])
        self.assertEqual(self.rejections[-1]['reason'], 'ADMITTED_NODE_SERVICE_RESTARTED')
        self.assertEqual(self.recoveries, [])

    def test_unadmitted_recovered_restart_still_fails_original_checks(self):
        current = self.exercise([booting()], [self.FAIL, (0, 'ActiveState=active\nMainPID=118\nNRestarts=2\n', '')])
        with self.assertRaises(original.CampaignError):
            original.check_kubernetes_runtimes({}, current)

    def test_identity_mismatch_during_window_is_rejected(self):
        for row in (dict(booting(), Id='e' * 64), dict(booting(), Name='/foreign')):
            with self.subTest(row=row['Name']), self.assertRaises(subprocess.CalledProcessError):
                self.exercise([booting(), row], [self.FAIL, self.FAIL, self.ACTIVE])
            self.assertEqual(self.rejections[-1]['reason'], 'NODE_IDENTITY_MISMATCH')

    def test_other_exec_commands_are_not_retried(self):
        # Only the exact runtime probe shape is repeated; any other exec keeps the v2 path.
        for command in (['docker', 'exec', ID, 'systemctl', 'show', 'containerd'],
                        ['docker', 'exec', ID, 'systemctl', 'show', 'sshd', '--property=ActiveState,MainPID,NRestarts'],
                        ['docker', 'exec', ID, 'journalctl', '-u', 'containerd', '--no-pager']):
            first = True

            def inspector():
                nonlocal first
                if first:
                    first = False
                    raise subprocess.CalledProcessError(1, command, output='', stderr=BOOT_STDERR)
                return {}
            clock = Clock()
            with self.subTest(command=command), \
                    patch.object(subprocess, 'run', lambda argv, **k: subprocess.CompletedProcess(argv, 0, json.dumps([booting()]), '')), \
                    patch.object(adapter, '_now', clock.now), patch.object(adapter, '_sleep', clock.sleep), \
                    patch.object(adapter, 'REJECTIONS', []) as rejections, patch.object(adapter, 'PROBE_OBSERVATIONS', []), \
                    self.assertRaises(subprocess.CalledProcessError):
                adapter.inspect_kubernetes_runtimes(inspector)
            self.assertEqual(rejections[-1]['reason'], 'WINDOW_EXPIRED_NODE_PRESENT')

    # ---- diagnostics ----------------------------------------------------------------------

    def test_failed_exec_records_bounded_redacted_stderr_and_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / 'bootstrap.env'
            env.write_text('OCOR_LOCAL_POSTGRES_PASSWORD=s3cr3t-generated\nSPIRE_JOIN_TOKEN=join-abc-123\nOTHER=visible\n')
            noisy = ('x' * 2000 + ' password s3cr3t-generated token join-abc-123 '
                     'OPENBAO_TOKEN=hvs.literal visible\n')
            self.exercise([booting()], [(1, '', noisy), self.ACTIVE], env_file=env)
        failed = [p for p in self.probes if p['command'][:2] == ['docker', 'exec'] and p.get('returncode') == 1]
        self.assertTrue(failed)
        for row in failed:
            self.assertEqual(row['returncode'], 1)
            self.assertLessEqual(len(row['stderr']), 500)
            self.assertNotIn('s3cr3t-generated', row['stderr'])
            self.assertNotIn('join-abc-123', row['stderr'])
            self.assertNotIn('hvs.literal', row['stderr'])
            self.assertIn('[REDACTED]', row['stderr'])
            self.assertIn('visible', row['stderr'])
        dumped = json.dumps(self.recoveries)
        self.assertNotIn('s3cr3t-generated', dumped)
        self.assertNotIn('join-abc-123', dumped)

    def test_successful_probes_carry_no_stderr_field(self):
        self.exercise([booting()], [self.FAIL, self.ACTIVE])
        self.assertTrue(all('stderr' not in p for p in self.probes if p.get('returncode') == 0))


SCOPE_STEP = '      - name: Reject immutable-path and task-ledger regressions\n'
SCOPE_ANCHOR = '      - name: Acquire official checksum-pinned Kubernetes qualification tools\n'


def move_scope_gate_before_provisioning(text):
    """The 0049 integration CI repair: the aggregator's scope step, byte for byte, moves before
    the first worktree writer (qualification tools, SDK build, stack provisioning)."""
    start = text.index(SCOPE_STEP)
    end = text.index('      - name: Validate language policy (DEC-212)\n', start)
    block, rest = text[start:end], text[:start] + text[end:]
    anchors = [i for i in range(len(rest)) if rest.startswith(SCOPE_ANCHOR, i)]
    assert len(anchors) == 2, 'aggregator anchor not unique'
    return rest[:anchors[1]] + block + rest[anchors[1]:]


def normalize_rem0034_secret_scanner(path, before, after):
    """PO 2026-10-15: recognise only the exact REM-0034 secret-scanner delta.

    Preserve the historical invariant for every other byte. The complete added
    block (including the three authority entries and every fail-closed check) is
    digest-bound; arbitrary secret-scanner edits still fail this guard.
    """
    if path != '.github/workflows/ocor-supply-chain.yml' or before == after:
        return after
    marker = '          # This append-only authority'
    if marker not in after:
        return after
    start, end = after.index(marker), after.index('          lock_path =')
    delta = after[start:end]
    assert hashlib.sha256(delta.encode()).hexdigest() == '73da96ea208ca68a1d39d7b7a421b1776b046dea0ce56d7481d970c5a3d39fed'
    old_start, old_end = before.index('          secret_findings: list'), before.index('          lock_path =')
    normalized = after[:start] + before[old_start:old_end] + after[end:]
    summary = '          if suspended_findings:\n              summary["suspended_findings"] = suspended_findings\n'
    assert normalized.count(summary) == 1
    assert normalized.count('      OCOR_SCANNER_VERSION: 1.1.0\n') == 1
    return normalized.replace(summary, '').replace('      OCOR_SCANNER_VERSION: 1.1.0\n', '      OCOR_SCANNER_VERSION: 1.0.0\n')


def retire_integrated_0049_pin(text):
    """Exact PO-authorised delta after 0049 integration; no gate is normalised away.

    CANDIDATE-INTEGRATION-STATE-FREEZE (2026-10-14): both runners qualify
    github.sha with the same harness, partitions, artifact paths and union gate.
    Each old fragment must occur exactly the declared number of times.
    """
    checkout = '''      - name: Checkout immutable TEST-INFRA-006 candidate (independent GO; integration pending)
        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
        with:
          ref: beab1b4cc16d0678ce5554fcebd6495b328f5342
          path: .ocor/candidate-0049
          persist-credentials: false

'''
    candidate_sync = '''      - name: Synchronize complete candidate environment
        working-directory: .ocor/candidate-0049/ocor-runtime
        run: uv sync --frozen --extra test --extra lint

'''
    current_sync = candidate_sync.replace('complete candidate', 'locked runtime').replace('.ocor/candidate-0049/', '')
    changes = [
        (checkout, '', 2),
        (candidate_sync, '', 1),  # part already synchronises the current runtime
        (candidate_sync, current_sync, 1),  # stackless aggregator
        ('    # A passing run exercises the guard; it does not accept the candidate\'s integration.',
         '    # TEST-INFRA-006 remains mandatory; 0049 is integrated and qualified at github.sha.', 1),
        ('working-directory: .ocor/candidate-0049/ocor-runtime/sdk/typescript',
         'working-directory: ocor-runtime/sdk/typescript', 1),
        ('Run this part of the immutable candidate FULL suite with TEST-INFRA-005 and 006',
         'Run this part of the current FULL suite with TEST-INFRA-005 and 006', 1),
        ('.ocor/candidate-0049/ocor-runtime/.venv/bin/python scripts/run_qualifying_campaign.py',
         'ocor-runtime/.venv/bin/python scripts/run_qualifying_campaign.py', 2),
        ('--repository .ocor/candidate-0049 --expected-head beab1b4cc16d0678ce5554fcebd6495b328f5342',
         '--repository . --expected-head "${{ github.sha }}"', 2),
        ('Teardown candidate-owned resources and the disposable stack',
         'Teardown test-owned resources and the disposable stack', 1),
        ('Aggregate candidate parts and prove their union equals pytest --collect-only on the candidate',
         'Aggregate current-revision parts and prove their union equals pytest --collect-only on the same HEAD', 1),
        ('Upload candidate guard execution (not an evidence seal)',
         'Upload current-revision guard execution (not an evidence seal)', 1),
    ]
    for old, new, count in changes:
        # The first synchronization is redundant in the part, the second is
        # retained on the current revision in the stackless aggregator.
        expected = 2 if old == candidate_sync and new == '' else count
        assert text.count(old) == expected, 'Unexpected retirement source: ' + old[:90]
        text = text.replace(old, new, count)
    return text


REM0038_CONSTANT = (
    '# Every service of deploy/bootstrap/compose.yaml: the eleven original containers\n'
    '# plus Temporal, its PostgreSQL, its admin-tools and SeaweedFS (OCOR-DEV-REM-0038).\n'
    'MANDATORY_CONTAINERS = 15\n'
)
REM0038_PLACEHOLDERS = (
    '          OCOR_LOCAL_SEAWEEDFS_PASSWORD=x \\\n'
    '          OCOR_LOCAL_TEMPORAL_POSTGRES_PASSWORD=x \\\n'
)


def normalize_rem0038_campaign(text):
    """PO REM-0038-CAMPAIGN-GUARD-ADMISSION (2026-10-26), option 1: exact delta of REM-0038.

    OCOR-DEV-0060-BA-SELECTED-COMPONENTS (2026-10-26) adds Temporal, its PostgreSQL, its
    admin-tools and SeaweedFS to the bootstrap stack, so the campaign requires 15 mandatory
    containers. Only the constant and its two uses (the inventory check in main and the
    diagnostic stats in observe_health_event) return to the baseline literal 11; each
    fragment must occur exactly once and no other use of the constant may remain.
    """
    changes = [
        (REM0038_CONSTANT, ''),
        ('*ids[:MANDATORY_CONTAINERS]])', '*ids[:11]])'),
        ('        if len(initial) != MANDATORY_CONTAINERS:\n'
         '            raise CampaignError(f"expected {MANDATORY_CONTAINERS} mandatory containers, found {len(initial)}")\n',
         '        if len(initial) != 11:\n'
         '            raise CampaignError(f"expected 11 mandatory containers, found {len(initial)}")\n'),
    ]
    for old, new in changes:
        assert text.count(old) == 1, 'Unexpected REM-0038 source: ' + old[:90]
        text = text.replace(old, new, 1)
    assert 'MANDATORY_CONTAINERS' not in text, 'Unexpected REM-0038 source: MANDATORY_CONTAINERS'
    return text


REM0042_DOCSTRING = (
    '"""Run the complete runtime suite, stopping on stack failure or the governed 90-minute full-suite limit.\n',
    '"""Run the complete runtime suite, stopping on stack failure or the governed 75-minute full-suite limit.\n',
)
REM0042_LIMIT = ('FULL_SUITE_LIMIT_SECONDS = 5400\n', 'FULL_SUITE_LIMIT_SECONDS = 4500\n')


def normalize_rem0042_campaign(text):
    """PO LOCAL-FULL-SUITE-CAP-90 (2026-10-26) as amended by LOCAL-FULL-SUITE-CAP-90-AMENDMENT
    (2026-10-26), point 3, under REM-0038-CAMPAIGN-GUARD-ADMISSION condition a: exact delta of
    OCOR-DEV-REM-0042. Only FULL_SUITE_LIMIT_SECONDS (5400) and the module docstring (90-minute)
    return to the baseline 4500 and 75-minute; each fragment must occur exactly once."""
    for old, new in (REM0042_DOCSTRING, REM0042_LIMIT):
        assert text.count(old) == 1, 'Unexpected REM-0042 source: ' + old[:90]
        text = text.replace(old, new, 1)
    return text


def normalize_rem0038_workflow(path, after):
    """Same decision: only the two Compose-rendering placeholders of the tooling workflow."""
    if path != '.github/workflows/ocor-tooling-bootstrap.yml':
        return after
    assert after.count(REM0038_PLACEHOLDERS) == 1, 'Workflow drift: ' + path
    return after.replace(REM0038_PLACEHOLDERS, '', 1)


REM0037_GUARD_STEP = '      - name: Execute conditional report guards and campaign supervisor tests\n'
REM0037_GUARD_COMMAND = (
    'reports/tests/test_ci_fuseki_archive.py reports/tests/test_local_lane_campaign.py | tee reports/tests/ci_guards.log\n',
    'reports/tests/test_ci_fuseki_archive.py | tee reports/tests/ci_guards.log\n',
)


def normalize_rem0037_workflow(path, after):
    """LOCAL-SUITE-SPLIT-REACTIVATION (2026-10-26), point 6, under REM-0038-CAMPAIGN-GUARD-ADMISSION
    condition a: exact delta of OCOR-DEV-REM-0037. Only the lane guard module appended to the
    validation-closure guard command returns to the baseline command; the module must occur
    exactly once in that workflow and the command fragment exactly once."""
    if path != '.github/workflows/ocor-validation-closure.yml':
        return after
    added, baseline = REM0037_GUARD_COMMAND
    assert after.count(added) == 1, 'Workflow drift: ' + path
    assert after.count('test_local_lane_campaign') == 1, 'Workflow drift: ' + path
    return after.replace(added, baseline, 1)


def assert_governed_workflow(path, before, after):
    """Accept only the PO's exact pin lifecycle/N update and scope-gate reorder."""
    if path == '.github/workflows/ocor-delivery-activation.yml':
        before = move_scope_gate_before_provisioning(before)
    if path == '.github/workflows/ocor-validation-closure.yml':
        prefix, suffix = before.split('  conditional-infrastructure-0049-part:', 1)
        assert suffix.count('a0ee43d4e502f3589cd857cfec4238eab13fe8e7') == 4
        suffix = suffix.replace('a0ee43d4e502f3589cd857cfec4238eab13fe8e7',
                                'beab1b4cc16d0678ce5554fcebd6495b328f5342')
        suffix = suffix.replace('matrix.part }}/4', 'matrix.part }}/5')
        suffix = suffix.replace('part: [1, 2, 3, 4]', 'part: [1, 2, 3, 4, 5]')
        suffix = suffix.replace('--shard-count 4', '--shard-count 5')
        before = prefix + '  conditional-infrastructure-0049-part:' + suffix
        before = retire_integrated_0049_pin(before)
    after = normalize_rem0034_secret_scanner(path, before, normalize_rem0038_workflow(path, normalize_rem0037_workflow(path, after)))
    assert before == after, 'Workflow drift: ' + path


def observation_only_proof(overrides=None):
    """Reproducible AST comparison to the last unqualified CI source.

    Normalisation removes only the three newly exported diagnostic fields and
    unwraps the latency recorder back to subprocess.run; every call argument
    remains in the AST, including the ten-second timeout and check flag.
    """
    root = Path(__file__).resolve().parents[2]
    baseline = '7cd5f7a30e04d1671fe122eff58dfb5f54fb58b0'

    def source(path, old=False):
        if old:
            return subprocess.check_output(['git', '-C', str(root), 'show', baseline + ':' + path], text=True)
        return (overrides or {}).get(path, (root / path).read_text())

    class DiagnosticsOnly(ast.NodeTransformer):
        def visit_Call(self, node):
            self.generic_visit(node)
            if ast.unparse(node.func) == 'kind_observer.run_probe':
                node.func = ast.parse('subprocess.run', mode='eval').body
            return node

        def visit_Dict(self, node):
            self.generic_visit(node)
            if any(isinstance(k, ast.Constant) and k.value == 'removals' for k in node.keys):
                retained = [(k, v) for k, v in zip(node.keys, node.values, strict=True)
                            if not (isinstance(k, ast.Constant) and k.value in {'remover_observations', 'probe_observations', 'bootstrap_recoveries'})]
                node.keys = [k for k, _ in retained]
                node.values = [v for _, v in retained]
            return node

    path = 'scripts/run_qualifying_campaign.py'
    before, after = ast.parse(source(path, True)), ast.parse(normalize_rem0038_campaign(normalize_rem0042_campaign(source(path))))
    before_functions = {n.name: n for n in before.body if isinstance(n, ast.FunctionDef)}
    after_functions = {n.name: n for n in after.body if isinstance(n, ast.FunctionDef)}
    results = {}
    for name, node in before_functions.items():
        if name == 'observe_health_event':
            continue  # diagnostic child only, never consumed by gates
        previous = ast.dump(node, include_attributes=False)
        current = ast.dump(DiagnosticsOnly().visit(after_functions[name]), include_attributes=False)
        assert previous == current, 'Execution-affecting AST drift: ' + name
        results[name] = {'before_sha256': hashlib.sha256(previous.encode()).hexdigest(),
                         'after_sha256': hashlib.sha256(current.encode()).hexdigest(), 'identical': True}
    def assignments(tree):
        return ast.dump(ast.Module(body=[n for n in tree.body if isinstance(n, ast.Assign)], type_ignores=[]), include_attributes=False)
    assert assignments(before) == assignments(after), 'Campaign constants drift'
    for variable in ('WINDOW_SECONDS', 'POLL_SECONDS', 'SAMPLE_SECONDS'):
        def value(old):
            tree = ast.parse(source('scripts/observe_kind_teardown.py', old))
            return next(ast.dump(n.value) for n in tree.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == variable for t in n.targets))
        assert value(True) == value(False), variable + ' drift'
    workflows = {}
    for p in sorted((root / '.github/workflows').glob('*.yml')):
        relative = str(p.relative_to(root))
        assert_governed_workflow(relative, source(relative, True), source(relative))
        workflows[relative] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {'baseline': baseline, 'functions': results, 'workflows_unchanged': workflows,
            'campaign_constants_identical': True, 'window_poll_sample_identical': True,
            'normalisation': 'Only latency wrapper and two diagnostic export fields removed from AST. Workflows require the exact PO-authorised 0049 pin and N=5 delta; all other bytes, timers and gates identical.',
            'authorised_workflow_delta': 'REM-0017-CI-0049-RELAY-PROBE-REMEDIATION (2026-10-14): beab1b4 pin, five deterministic parts; 0049 integration CI repair: delivery-activation scope gate moved byte-identically before the first worktree writer; REM-0038-CAMPAIGN-GUARD-ADMISSION (2026-10-26): two tooling Compose-rendering placeholders; LOCAL-SUITE-SPLIT-REACTIVATION (2026-10-26) point 6: the REM-0037 lane guard module in the validation-closure guard command',
            'authorised_campaign_delta': 'REM-0038-CAMPAIGN-GUARD-ADMISSION (2026-10-26): MANDATORY_CONTAINERS = 15 and its two uses normalised back to 11'}


class ExecutionInvariants(unittest.TestCase):
    def test_integrated_0049_is_qualified_at_the_current_revision(self):
        """PO CANDIDATE-INTEGRATION-STATE-FREEZE: retire the pin, retain the guard."""
        import yaml
        root = Path(__file__).resolve().parents[2]
        text = (root / '.github/workflows/ocor-validation-closure.yml').read_text()
        jobs = yaml.safe_load(text)['jobs']
        for job_id in ('conditional-infrastructure-0049-part', 'conditional-infrastructure-0049'):
            steps = jobs[job_id]['steps']
            checkouts = [s for s in steps if s.get('uses', '').startswith('actions/checkout@')]
            self.assertEqual(len(checkouts), 1, 'An integrated task must use the checked-out PR revision')
            self.assertNotIn('ref', checkouts[0]['with'])
            self.assertNotIn('path', checkouts[0]['with'])
            command = next(s['run'] for s in steps if 'scripts/run_qualifying_campaign.py' in s.get('run', ''))
            self.assertIn('ocor-runtime/.venv/bin/python scripts/run_qualifying_campaign.py', command)
            self.assertIn('--repository . --expected-head "${{ github.sha }}"', command)
            self.assertNotIn('.ocor/candidate-0049', command)
            self.assertIn('--shard-count 5', command)
        self.assertEqual(jobs['conditional-infrastructure-0049-part']['strategy']['matrix']['part'], [1, 2, 3, 4, 5])
        self.assertEqual(jobs['conditional-infrastructure-0049']['needs'], 'conditional-infrastructure-0049-part')
        self.assertIn('conditional-infrastructure-0049', jobs['validation-closure']['needs'])

    def test_workflow_invariant_rejects_every_unapproved_change(self):
        root = Path(__file__).resolve().parents[2]
        path = '.github/workflows/ocor-validation-closure.yml'
        before = subprocess.check_output(['git', '-C', str(root), 'show',
                  '7cd5f7a30e04d1671fe122eff58dfb5f54fb58b0:' + path], text=True)
        current = (root / path).read_text()
        assert_governed_workflow(path, before, current)
        for old, new in [
            ('--expected-head "${{ github.sha }}"', '--expected-head beab1b4cc16d0678ce5554fcebd6495b328f5342'),
            ('--repository . --expected-head', '--repository .ocor/candidate-0049 --expected-head'),
            ('working-directory: ocor-runtime/sdk/typescript', 'working-directory: .ocor/candidate-0049/ocor-runtime/sdk/typescript'),
            ('--shard-count 5', '--shard-count 4'),
            ('part: [1, 2, 3, 4, 5]', 'part: [1, 2, 3, 4]'),
            ('timeout-minutes: 75', 'timeout-minutes: 76'),
            ('--timeout 600', '--timeout 601'),
            ('--aggregate reports/tests/candidate-0049-parts', '--aggregate reports/tests/wrong-parts'),
            ('needs: conditional-infrastructure-0049-part', 'needs: []'),
            ('if: always()', 'if: success()'),
        ]:
            with self.subTest(change=old):
                self.assertIn(old, current)
                with self.assertRaisesRegex(AssertionError, 'Workflow drift'):
                    assert_governed_workflow(path, before, current.replace(old, new, 1))
        # The scope-gate reorder is the only accepted delivery-activation delta.
        path = '.github/workflows/ocor-delivery-activation.yml'
        before = subprocess.check_output(['git', '-C', str(root), 'show',
                  '7cd5f7a30e04d1671fe122eff58dfb5f54fb58b0:' + path], text=True)
        current = (root / path).read_text()
        assert_governed_workflow(path, before, current)
        block_start = current.index(SCOPE_STEP)
        block_end = current.index('\n\n', block_start) + 2
        block = current[block_start:block_end]
        unmoved = current[:block_start] + current[block_end:]
        writer = unmoved.index('      - name: Save verified Fuseki archive in this repository cache\n')
        for label, changed in [
            ('scope gate back after provisioning', unmoved[:writer] + block + unmoved[writer:]),
            ('scope gate removed', unmoved),
            ('scope gate base changed', current.replace("github.event.before || 'origin/main'", "'origin/main'", 1)),
            ('timeout changed', current.replace('timeout-minutes: 110', 'timeout-minutes: 111', 1)),
        ]:
            with self.subTest(change=label):
                self.assertNotEqual(changed, current)
                with self.assertRaisesRegex(AssertionError, 'Workflow drift'):
                    assert_governed_workflow(path, before, changed)
        # No pin/N exception in any other workflow.
        with self.assertRaisesRegex(AssertionError, 'Workflow drift'):
            assert_governed_workflow('.github/workflows/ocor-rccad.yml', 'unchanged', 'changed')

    def test_bootstrap_probe_change_is_observation_only_against_main(self):
        """CI-0049-KIND-BOOTSTRAP-EXEC-PROBE: against the last qualified main (9b4d3be) the
        campaign supervisor differs only by one exported diagnostic key; the observer keeps
        its window, cadence, sampler and ten-second probe timeouts."""
        bootstrap_probe_proof(self)

    def test_execution_ast_and_workflows_are_identical(self):
        proof = observation_only_proof()
        self.assertTrue(proof['functions']['main']['identical'])
        self.assertTrue(proof['functions']['partition']['identical'])
        self.assertTrue(proof['functions']['check_kubernetes_runtimes']['identical'])


def bootstrap_probe_proof(case, overrides=None):
    """Body of the CI-0049-KIND-BOOTSTRAP-EXEC-PROBE proof; ``overrides`` replaces file text
    so that the negative cases of REM-0038-CAMPAIGN-GUARD-ADMISSION run the same checks."""
    root = Path(__file__).resolve().parents[2]

    def read(path):
        return (overrides or {}).get(path, (root / path).read_text())

    baseline = '9b4d3be8ec5bd785b02072a99037dd801b53d9a5'

    def old(path):
        return subprocess.check_output(['git', '-C', str(root), 'show', baseline + ':' + path], text=True)

    class DropExport(ast.NodeTransformer):
        def visit_Dict(self, node):
            self.generic_visit(node)
            keep = [(k, v) for k, v in zip(node.keys, node.values, strict=True)
                    if not (isinstance(k, ast.Constant) and k.value == 'bootstrap_recoveries')]
            node.keys, node.values = [k for k, _ in keep], [v for _, v in keep]
            return node

    path = 'scripts/run_qualifying_campaign.py'
    before = ast.dump(ast.parse(old(path)), include_attributes=False)
    after = ast.dump(DropExport().visit(ast.parse(normalize_rem0038_campaign(normalize_rem0042_campaign(read(path))))), include_attributes=False)
    case.assertEqual(before, after)
    case.assertNotEqual(old(path), read(path))

    def constants(text):
        tree = ast.parse(text)
        return {t.id: ast.dump(n.value) for n in tree.body if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)
                and t.id in {'WINDOW_SECONDS', 'POLL_SECONDS', 'SAMPLE_SECONDS', 'KIND_BINARY'}}
    observer = 'scripts/observe_kind_teardown.py'
    case.assertEqual(constants(old(observer)), constants((root / observer).read_text()))
    timeouts = {ast.unparse(k.value) for n in ast.walk(ast.parse((root / observer).read_text()))
                if isinstance(n, ast.Call) and ast.unparse(n.func) == 'run_probe'
                for k in n.keywords if k.arg == 'timeout'}
    case.assertEqual(timeouts, {'10'})
    for workflow in sorted((root / '.github/workflows').glob('*.yml')):
        path = str(workflow.relative_to(root))
        before = old(path)
        if path == '.github/workflows/ocor-validation-closure.yml':
            before = retire_integrated_0049_pin(before)
        after = normalize_rem0034_secret_scanner(path, before, normalize_rem0038_workflow(path, normalize_rem0037_workflow(path, read(path))))
        case.assertEqual(before, after, workflow.name)



class Rem0038GuardAdmission(unittest.TestCase):
    """PO REM-0038-CAMPAIGN-GUARD-ADMISSION (2026-10-26), option 1: the exact REM-0038 delta is
    admitted; every other difference still fails the invariance proofs."""
    CAMPAIGN = 'scripts/run_qualifying_campaign.py'
    TOOLING = '.github/workflows/ocor-tooling-bootstrap.yml'

    def failing_proofs(self, overrides):
        failed = set()
        for name, proof in (('main-9b4d3be', lambda: bootstrap_probe_proof(self, overrides)),
                            ('ast-7cd5f7a', lambda: observation_only_proof(overrides))):
            try:
                proof()
            except AssertionError:
                failed.add(name)
        return failed

    def test_the_exact_delta_is_admitted_and_normalised_to_the_baseline_literal(self):
        root = Path(__file__).resolve().parents[2]
        campaign = (root / self.CAMPAIGN).read_text()
        self.assertEqual(campaign.count(REM0038_CONSTANT), 1)
        normalised = normalize_rem0038_campaign(normalize_rem0042_campaign(campaign))
        self.assertNotIn('MANDATORY_CONTAINERS', normalised)
        self.assertEqual(normalised.count('*ids[:11]])'), 1)
        self.assertEqual(normalised.count('if len(initial) != 11:'), 1)
        self.assertEqual(self.failing_proofs({}), set())

    def test_every_other_campaign_difference_still_fails(self):
        root = Path(__file__).resolve().parents[2]
        campaign = (root / self.CAMPAIGN).read_text()
        both = {'main-9b4d3be', 'ast-7cd5f7a'}
        stack = '        raise CampaignError("mandatory stack disappeared")\n'
        for label, changed, expected in [
            ('MANDATORY_CONTAINERS 16', campaign.replace('MANDATORY_CONTAINERS = 15', 'MANDATORY_CONTAINERS = 16', 1), both),
            ('another constant', campaign.replace(REM0038_CONSTANT, REM0038_CONSTANT + 'EXTRA_CONTAINERS = 1\n', 1), both),
            ('limit constant', campaign.replace('FULL_SUITE_LIMIT_SECONDS = 5400', 'FULL_SUITE_LIMIT_SECONDS = 6000', 1), both),
            ('another function changed', campaign.replace(stack, stack.replace('disappeared', 'vanished'), 1), both),
            ('another function added', campaign + '\n\ndef extra_gate() -> None:\n    return None\n', {'main-9b4d3be'}),
            ('inventory check weakened', campaign.replace('if len(initial) != MANDATORY_CONTAINERS:', 'if len(initial) < MANDATORY_CONTAINERS:', 1), both),
            ('constant used elsewhere', campaign.replace('PART_LIMIT_SECONDS = 2700', 'PART_LIMIT_SECONDS = 180 * MANDATORY_CONTAINERS', 1), both),
            ('literal 11 kept in main', campaign.replace('if len(initial) != MANDATORY_CONTAINERS:', 'if len(initial) != 11:', 1), both),
        ]:
            with self.subTest(change=label):
                self.assertNotEqual(changed, campaign)
                self.assertEqual(self.failing_proofs({self.CAMPAIGN: changed}), expected)

    def test_every_other_workflow_difference_still_fails(self):
        root = Path(__file__).resolve().parents[2]
        tooling = (root / self.TOOLING).read_text()
        self.assertEqual(tooling.count(REM0038_PLACEHOLDERS), 1)
        both = {'main-9b4d3be', 'ast-7cd5f7a'}
        extra = '          OCOR_LOCAL_EXTRA_PASSWORD=x \\\n'
        rccad = '.github/workflows/ocor-rccad.yml'
        for label, overrides in [
            ('one more placeholder line', {self.TOOLING: tooling.replace(REM0038_PLACEHOLDERS, REM0038_PLACEHOLDERS + extra, 1)}),
            ('placeholder missing', {self.TOOLING: tooling.replace(REM0038_PLACEHOLDERS, REM0038_PLACEHOLDERS.split('\n')[0] + '\n', 1)}),
            ('placeholder duplicated', {self.TOOLING: tooling.replace(REM0038_PLACEHOLDERS, REM0038_PLACEHOLDERS * 2, 1)}),
            ('placeholders in another workflow', {rccad: (root / rccad).read_text() + REM0038_PLACEHOLDERS}),
            ('other tooling line', {self.TOOLING: tooling.replace('docker compose -f deploy/bootstrap/compose.yaml config --quiet',
                                                                  'docker compose -f deploy/bootstrap/compose.yaml config', 1)}),
        ]:
            with self.subTest(change=label):
                self.assertEqual(self.failing_proofs(overrides), both)


class Rem0042GuardAdmission(Rem0038GuardAdmission):
    """LOCAL-FULL-SUITE-CAP-90-AMENDMENT (2026-10-26), point 3: the exact REM-0042 delta (limit
    5400 and the 90-minute docstring) is admitted; every other difference still fails. The
    inherited workflow test proves that REM-0042 admits no workflow difference."""

    def test_the_exact_delta_is_admitted_and_normalised_to_the_baseline_literal(self):
        root = Path(__file__).resolve().parents[2]
        campaign = (root / self.CAMPAIGN).read_text()
        self.assertEqual(campaign.count(REM0042_LIMIT[0]), 1)
        self.assertEqual(campaign.count(REM0042_DOCSTRING[0]), 1)
        normalised = normalize_rem0042_campaign(campaign)
        self.assertEqual(normalised.count(REM0042_LIMIT[1]), 1)
        self.assertEqual(normalised.count(REM0042_DOCSTRING[1]), 1)
        self.assertNotIn('5400', normalised)
        self.assertNotIn('90-minute', normalised)
        self.assertEqual(self.failing_proofs({}), set())

    def test_every_other_campaign_difference_still_fails(self):
        root = Path(__file__).resolve().parents[2]
        campaign = (root / self.CAMPAIGN).read_text()
        both = {'main-9b4d3be', 'ast-7cd5f7a'}
        limit, docstring = REM0042_LIMIT[0], REM0042_DOCSTRING[0]
        for label, changed, expected in [
            ('limit 5401', campaign.replace(limit, 'FULL_SUITE_LIMIT_SECONDS = 5401\n', 1), both),
            ('limit back to 4500 with the 90-minute docstring', campaign.replace(limit, REM0042_LIMIT[1], 1), both),
            ('90-minute docstring missing', campaign.replace(docstring, REM0042_DOCSTRING[1], 1), both),
            ('docstring wording changed', campaign.replace(docstring, docstring.replace('stopping on', 'halting on'), 1), both),
            ('limit duplicated', campaign.replace(limit, limit + limit, 1), both),
            ('limit as an expression', campaign.replace(limit, 'FULL_SUITE_LIMIT_SECONDS = 90 * 60\n', 1), both),
            ('notification threshold', campaign.replace('PO_DECISION_THRESHOLD_SECONDS = 3600', 'PO_DECISION_THRESHOLD_SECONDS = 4500', 1), both),
            ('part limit', campaign.replace('PART_LIMIT_SECONDS = 2700', 'PART_LIMIT_SECONDS = 3240', 1), both),
            ('part rebalance', campaign.replace('PART_REBALANCE_SECONDS = 1800', 'PART_REBALANCE_SECONDS = 2160', 1), both),
            ('observer timeout margin', campaign.replace('default=FULL_SUITE_LIMIT_SECONDS + 60', 'default=FULL_SUITE_LIMIT_SECONDS + 120', 1), both),
            ('deadline message', campaign.replace('f"{limit // 60}-minute campaign limit reached"', 'f"{limit // 60}-minute limit reached"', 1), both),
            ('another constant', campaign.replace(limit, limit + 'EXTRA_LIMIT_SECONDS = 5400\n', 1), both),
        ]:
            with self.subTest(change=label):
                self.assertNotEqual(changed, campaign)
                self.assertEqual(self.failing_proofs({self.CAMPAIGN: changed}), expected)


class Rem0037GuardAdmission(unittest.TestCase):
    """LOCAL-SUITE-SPLIT-REACTIVATION (2026-10-26), point 6, under REM-0038-CAMPAIGN-GUARD-ADMISSION
    condition a: the exact REM-0037 delta (reports/tests/test_local_lane_campaign.py appended to
    the validation-closure guard command) is admitted; every other difference still fails. The
    campaign tests of Rem0038GuardAdmission prove that REM-0037 admits no campaign difference."""
    CLOSURE = '.github/workflows/ocor-validation-closure.yml'
    failing_proofs = Rem0038GuardAdmission.failing_proofs

    def test_the_lane_guard_module_runs_in_the_validation_closure_guard_step(self):
        import yaml
        root = Path(__file__).resolve().parents[2]
        steps = yaml.safe_load((root / self.CLOSURE).read_text())['jobs']['validation-closure']['steps']
        guard = [s for s in steps if s.get('name') == REM0037_GUARD_STEP.split('name: ', 1)[1].strip()]
        self.assertEqual(len(guard), 1)
        command = guard[0]['run'].splitlines()[1]
        self.assertIn('--junitxml=reports/tests/guards_junit.xml', command)
        self.assertEqual(command.split().count('reports/tests/test_local_lane_campaign.py'), 1)
        self.assertIn('check_junit', guard[0]['run'])

    def test_the_exact_delta_is_admitted_and_normalised_to_the_baseline_command(self):
        root = Path(__file__).resolve().parents[2]
        closure = (root / self.CLOSURE).read_text()
        added, baseline = REM0037_GUARD_COMMAND
        self.assertEqual(closure.count(added), 1)
        normalised = normalize_rem0037_workflow(self.CLOSURE, closure)
        self.assertNotIn('test_local_lane_campaign', normalised)
        self.assertEqual(normalised.count(baseline), 1)
        self.assertEqual(self.failing_proofs({}), set())

    def test_every_other_workflow_difference_still_fails(self):
        root = Path(__file__).resolve().parents[2]
        closure = (root / self.CLOSURE).read_text()
        added, baseline = REM0037_GUARD_COMMAND
        both = {'main-9b4d3be', 'ast-7cd5f7a'}
        module = 'reports/tests/test_local_lane_campaign.py'
        rccad = '.github/workflows/ocor-rccad.yml'
        for label, overrides in [
            ('module missing', {self.CLOSURE: closure.replace(added, baseline, 1)}),
            ('module duplicated', {self.CLOSURE: closure.replace(added, added.replace(module, module + ' ' + module), 1)}),
            ('module first', {self.CLOSURE: closure.replace(added, added.replace('reports/tests/test_ci_fuseki_archive.py ' + module, module + ' reports/tests/test_ci_fuseki_archive.py'), 1)}),
            ('another module added', {self.CLOSURE: closure.replace(added, added.replace(module, module + ' reports/tests/test_extra.py'), 1)}),
            ('selection flag added', {self.CLOSURE: closure.replace(added, added.replace(module, module + ' -k not_slow'), 1)}),
            ('tee log changed', {self.CLOSURE: closure.replace(added, added.replace('ci_guards.log', 'ci_guards_lanes.log'), 1)}),
            ('junit path changed', {self.CLOSURE: closure.replace('--junitxml=reports/tests/guards_junit.xml', '--junitxml=reports/tests/lanes_junit.xml', 1)}),
            ('module run in a second step', {self.CLOSURE: closure.replace(REM0037_GUARD_STEP, '      - name: Lane guard\n        run: pytest ' + module + '\n\n' + REM0037_GUARD_STEP, 1)}),
            ('module in another workflow', {rccad: (root / rccad).read_text() + '# ' + module + '\n'}),
        ]:
            with self.subTest(change=label):
                path, text = next(iter(overrides.items()))
                self.assertNotEqual(text, (root / path).read_text())
                self.assertEqual(self.failing_proofs(overrides), both)

if __name__ == '__main__':
    unittest.main()
