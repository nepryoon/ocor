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


def assert_governed_workflow(path, before, after):
    """Accept only the PO's exact pin/N update and the scope-gate reorder; every other byte stays checked."""
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
    assert before == after, 'Workflow drift: ' + path


def observation_only_proof():
    """Reproducible AST comparison to the last unqualified CI source.

    Normalisation removes only the three newly exported diagnostic fields and
    unwraps the latency recorder back to subprocess.run; every call argument
    remains in the AST, including the ten-second timeout and check flag.
    """
    root = Path(__file__).resolve().parents[2]
    baseline = '7cd5f7a30e04d1671fe122eff58dfb5f54fb58b0'

    def source(path, old=False):
        return subprocess.check_output(['git', '-C', str(root), 'show', baseline + ':' + path], text=True) if old else (root / path).read_text()

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
    before, after = ast.parse(source(path, True)), ast.parse(source(path))
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
            'authorised_workflow_delta': 'REM-0017-CI-0049-RELAY-PROBE-REMEDIATION (2026-10-14): beab1b4 pin, five deterministic parts; 0049 integration CI repair: delivery-activation scope gate moved byte-identically before the first worktree writer'}


class ExecutionInvariants(unittest.TestCase):
    def test_workflow_invariant_rejects_every_unapproved_change(self):
        root = Path(__file__).resolve().parents[2]
        path = '.github/workflows/ocor-validation-closure.yml'
        before = subprocess.check_output(['git', '-C', str(root), 'show',
                  '7cd5f7a30e04d1671fe122eff58dfb5f54fb58b0:' + path], text=True)
        current = (root / path).read_text()
        assert_governed_workflow(path, before, current)
        for old, new in [
            ('beab1b4cc16d0678ce5554fcebd6495b328f5342', 'a0ee43d4e502f3589cd857cfec4238eab13fe8e7'),
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
        root = Path(__file__).resolve().parents[2]
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
        after = ast.dump(DropExport().visit(ast.parse((root / path).read_text())), include_attributes=False)
        self.assertEqual(before, after)
        self.assertNotEqual(old(path), (root / path).read_text())

        def constants(text):
            tree = ast.parse(text)
            return {t.id: ast.dump(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)
                    and t.id in {'WINDOW_SECONDS', 'POLL_SECONDS', 'SAMPLE_SECONDS', 'KIND_BINARY'}}
        observer = 'scripts/observe_kind_teardown.py'
        self.assertEqual(constants(old(observer)), constants((root / observer).read_text()))
        timeouts = {ast.unparse(k.value) for n in ast.walk(ast.parse((root / observer).read_text()))
                    if isinstance(n, ast.Call) and ast.unparse(n.func) == 'run_probe'
                    for k in n.keywords if k.arg == 'timeout'}
        self.assertEqual(timeouts, {'10'})
        for workflow in sorted((root / '.github/workflows').glob('*.yml')):
            self.assertEqual(old(str(workflow.relative_to(root))), workflow.read_text(), workflow.name)

    def test_execution_ast_and_workflows_are_identical(self):
        proof = observation_only_proof()
        self.assertTrue(proof['functions']['main']['identical'])
        self.assertTrue(proof['functions']['partition']['identical'])
        self.assertTrue(proof['functions']['check_kubernetes_runtimes']['identical'])


if __name__ == '__main__':
    unittest.main()
