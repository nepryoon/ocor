"""Fail-closed regression controls for the real-stack campaign supervisor."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
SPEC = importlib.util.spec_from_file_location('ocor_campaign_guard', Path(__file__).resolve().parents[2] / 'scripts/run_qualifying_campaign.py')
assert SPEC is not None and SPEC.loader is not None
GUARD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GUARD
SPEC.loader.exec_module(GUARD)


def state(*, running=True, oom=False, restarts=0, identity='abc'):
    return {'Id': identity, 'RestartCount': restarts, 'State': {'Running': running, 'OOMKilled': oom}}


def health_event(name='ocor-poc-tested-123-ocor-relay-fuseki-1', action='health_status: unhealthy'):
    return {'Type': 'container', 'Action': action, 'Actor': {'ID': 'a' * 64,
            'Attributes': {'name': name, 'com.docker.compose.service': 'ocor-relay-fuseki'}}}


def test_health_observer_records_event_before_container_can_be_destroyed(tmp_path, monkeypatch):
    import json
    calls = []
    writer = GUARD.HealthJournal(tmp_path, ['generated-secret'])

    def command(argv):
        # Snapshot the journal before any potentially racing Docker read.
        calls.append((argv, writer.path.read_text()))
        return {'command': argv, 'exit_code': 0, 'output': 'Health.Log generated-secret', 'truncated': False}

    monkeypatch.setattr(GUARD, 'health_command', command)
    GUARD.observe_health_event(health_event(), writer)
    records = [json.loads(line) for line in writer.path.read_text().splitlines()]
    assert records[0]['kind'] == 'unhealthy_event'
    assert all('unhealthy_event' in contents for _, contents in calls)
    assert calls[0][0][:2] == ['docker', 'inspect']
    assert any(c[:2] == ['docker', 'logs'] and c[-1] == 'a' * 64 for c, _ in calls)
    assert any(c[:2] == ['docker', 'logs'] and c[-1] == 'ocor-bootstrap-fuseki-1' for c, _ in calls)
    assert any(c[:2] == ['docker', 'stats'] for c, _ in calls)
    assert 'generated-secret' not in writer.path.read_text()
    assert '[REDACTED]' in writer.path.read_text()


@pytest.mark.parametrize('name,http,reason,classification', [
    ('ocor-poc-tested-123-ocor-ops-1', 503, 'RESTORE_UNTESTED', 'EXPECTED_READINESS_GATE'),
    ('ocor-poc-tested-123-ocor-relay-fuseki-1', 503, 'RESTORE_UNTESTED', 'UNCLASSIFIED'),
    ('ocor-poc-tested-123-ocor-ops-1', 500, 'RESTORE_UNTESTED', 'UNCLASSIFIED'),
    ('ocor-poc-tested-123-ocor-ops-1', 503, 'POLICY_UNAVAILABLE', 'UNCLASSIFIED'),
    ('ocor-poc-tested-123-ocor-ops-1', 503, None, 'UNCLASSIFIED'),
])
def test_readiness_classification_is_diagnostic_and_requires_restore_gate(tmp_path, monkeypatch, name, http, reason, classification):
    import json
    writer = GUARD.HealthJournal(tmp_path, [])

    def command(argv):
        if argv[:2] == ['docker', 'inspect']:
            state = {'Health': {'Log': [{'ExitCode': 1, 'Output': f'HTTP Error {http}: Service Unavailable'}]}}
            output = json.dumps(state) + ' 0'
        elif argv[:2] == ['docker', 'logs']:
            output = json.dumps({'operation': 'span', 'span': {'operation': 'readiness_scan',
                               'reason_code': reason, 'ready_reasons': [reason], 'status': 'DENY'}})
        else:
            output = ''
        return {'command': argv, 'exit_code': 0, 'output': output, 'truncated': False}

    monkeypatch.setattr(GUARD, 'health_command', command)
    GUARD.observe_health_event(health_event(name), writer)
    rows = [json.loads(line) for line in writer.path.read_text().splitlines()]
    classified = [r for r in rows if r['kind'] == 'unhealthy_classification']
    assert len(classified) == 1
    assert classified[0]['classification'] == classification
    assert classified[0]['affects_test_outcome'] is False
    GUARD.check_stack({'service': state()}, {'service': state()})


@pytest.mark.parametrize('event', [health_event('open-webui'), health_event(action='die'),
                                  {'Type': 'network'}, health_event(name='ocor-poc-fake;other')])
def test_health_observer_ignores_unrelated_or_malformed_events(tmp_path, monkeypatch, event):
    writer = GUARD.HealthJournal(tmp_path, [])
    monkeypatch.setattr(GUARD, 'health_command', lambda _: pytest.fail('unrelated Docker read'))
    GUARD.observe_health_event(event, writer)
    assert not writer.path.exists()


def test_health_observer_records_missing_container_and_upstream_without_changing_gate(tmp_path, monkeypatch):
    writer = GUARD.HealthJournal(tmp_path, [])
    monkeypatch.setattr(GUARD, 'health_command', lambda argv: {
        'command': argv, 'exit_code': 1, 'output': 'No such container', 'truncated': False})
    GUARD.observe_health_event(health_event(), writer)
    assert 'No such container' in writer.path.read_text()
    GUARD.check_stack({'service': state()}, {'service': state()})
    with pytest.raises(GUARD.CampaignError):
        GUARD.check_stack({'service': state()}, {})


@pytest.mark.parametrize('service', ['terminusdb', 'typedb', 'fuseki', 'opa', 'keycloak',
                                   'openbao', 'postgresql', 'kafka', 'qdrant', 'spire-server'])
def test_health_observer_captures_every_actual_poc_relay_upstream(tmp_path, monkeypatch, service):
    writer = GUARD.HealthJournal(tmp_path, [])
    calls = []
    def command(argv):
        calls.append(argv)
        return {'command': argv, 'exit_code': 0, 'output': '', 'truncated': False}
    monkeypatch.setattr(GUARD, 'health_command', command)
    event = health_event()
    event['Actor']['Attributes']['com.docker.compose.service'] = 'ocor-relay-' + service
    GUARD.observe_health_event(event, writer)
    assert ['docker', 'logs', '--timestamps', '--tail', '200', 'ocor-bootstrap-' + service + '-1'] in calls


def test_health_observer_has_a_total_byte_budget(tmp_path):
    writer = GUARD.HealthJournal(tmp_path, [], max_bytes=1000)
    for _ in range(100):
        writer.write({'kind': 'runner_sample', 'data': 'x' * 200})
    assert writer.path.stat().st_size <= 1000
    assert writer.truncated


def test_health_command_times_out_and_limits_untrusted_output():
    result = GUARD.health_command([sys.executable, '-c', 'import time; time.sleep(5)'], timeout=0.1)
    assert result['error'] == 'TIMEOUT'
    result = GUARD.health_command([sys.executable, '-c', "print('x' * 100000)"], max_bytes=1000)
    assert len(result['output'].encode()) <= 1000
    assert result['truncated']


def test_health_observer_start_failure_is_diagnostic_only(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError('observer unavailable')
    monkeypatch.setattr(GUARD.subprocess, 'Popen', unavailable)
    assert GUARD.start_health_observer(tmp_path, 2700) is None
    assert 'observer unavailable' in (tmp_path / 'health-observer-status.json').read_text()


def test_health_observer_runner_sample_includes_cpu_load_and_memory():
    sample = GUARD.runner_health_sample()
    assert sample['sample_interval_seconds'] == 5
    assert len(sample['load_average']) == 3
    assert len(sample['cpu_ticks']) >= 4
    assert sample['memory_kib']['MemTotal'] > 0
    assert sample['memory_kib']['MemAvailable'] >= 0


def test_health_observer_artifact_manifest_binds_raw_digest(tmp_path):
    import hashlib
    import json
    writer = GUARD.HealthJournal(tmp_path, [])
    writer.write({'kind': 'unhealthy_event', 'identity': 'a' * 64})
    GUARD.finish_health_observer(None, tmp_path)
    manifest = json.loads((tmp_path / 'health-observer-manifest.json').read_text())
    assert manifest['artifacts'][writer.path.name] == hashlib.sha256(writer.path.read_bytes()).hexdigest()


def test_failed_health_observer_does_not_change_successful_pytest(tmp_path, monkeypatch):
    output, json = stub_completed_campaign(tmp_path, monkeypatch, seconds=1)
    class FailedObserver:
        returncode = 2
        def poll(self):
            return 2
        def wait(self, **kwargs):
            return 2
    monkeypatch.setattr(GUARD, 'start_health_observer', lambda *args: FailedObserver())
    assert GUARD.main() == 0
    assert json.loads((output / 'campaign_result.json').read_text())['status'] == 'PASS'
    assert json.loads((output / 'health-observer-manifest.json').read_text())['observer_exit_code'] == 2


def test_kind_diagnostics_export_remover_probe_latency_and_rejection_times(tmp_path, monkeypatch):
    output, json = stub_completed_campaign(tmp_path, monkeypatch, seconds=1)
    monkeypatch.setattr(GUARD.kind_observer, 'start_sampler', lambda *args: object())
    monkeypatch.setattr(GUARD.kind_observer, 'stop_sampler', lambda *args: None)
    monkeypatch.setattr(GUARD.kind_observer, 'REMOVER_OBSERVATIONS', [{'pid': 41, 'pgid': 42, 'first_seen': 100}])
    monkeypatch.setattr(GUARD.kind_observer, 'PROBE_OBSERVATIONS', [{'duration_seconds': 10, 'started_at': 'start', 'finished_at': 'end'}])
    monkeypatch.setattr(GUARD.kind_observer, 'REJECTIONS', [{'reason': 'EVENTS_UNAVAILABLE', 'observed_at': 'rejection'}])
    assert GUARD.main() == 0
    report = json.loads((output / 'kind-teardown-observations.json').read_text())
    assert report['remover_observations'][0]['pid'] == 41
    assert report['probe_observations'][0]['duration_seconds'] == 10
    assert report['rejections'][0]['observed_at'] == 'rejection'


def test_running_same_incarnation_is_accepted():
    GUARD.check_stack({'service': state()}, {'service': state()})


@pytest.mark.parametrize('current', [{}, {'service': state(running=False)}, {'service': state(oom=True)}, {'service': state(restarts=1)}, {'service': state(identity='other')}])
def test_loss_oom_restart_or_replacement_is_rejected(current):
    with pytest.raises(GUARD.CampaignError):
        GUARD.check_stack({'service': state()}, current)


def test_empty_stack_is_not_qualifying():
    with pytest.raises(GUARD.CampaignError):
        GUARD.check_stack({}, {})


def test_zero_skip_junit_is_accepted(tmp_path):
    path = tmp_path / 'run.xml'
    path.write_text('<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase name="positive"/></testsuite></testsuites>')
    assert GUARD.check_junit(path)['skipped'] == 0


@pytest.mark.parametrize('xml', ['<testsuites/>', '<testsuite tests="1" failures="1"/>', '<testsuite tests="1" skipped="1"/>', '<testsuite tests="1"><testcase><skipped/></testcase></testsuite>', 'invalid'])
def test_nonqualifying_junit_is_rejected(tmp_path, xml):
    path = tmp_path / 'run.xml'
    path.write_text(xml)
    with pytest.raises(GUARD.CampaignError):
        GUARD.check_junit(path)


def test_missing_junit_is_rejected(tmp_path):
    with pytest.raises(GUARD.CampaignError):
        GUARD.check_junit(tmp_path / 'missing.xml')


def test_manual_restart_is_rejected_even_without_restart_counter_change():
    before = state()
    before['State']['StartedAt'] = '2026-10-07T02:00:00Z'
    after = state()
    after['State']['StartedAt'] = '2026-10-07T02:00:05Z'
    with pytest.raises(GUARD.CampaignError):
        GUARD.check_stack({'service': before}, {'service': after})


def test_credential_redaction_preserves_failure_and_counts():
    from bootstrap_ci_environment import redact
    assert redact('FAIL: secret-token; 1 failed, 0 skipped', ['secret-token']) == 'FAIL: [REDACTED]; 1 failed, 0 skipped'


def test_pem_redaction_removes_key_material():
    from bootstrap_ci_environment import redact
    begin = '-'.join(['-----BEGIN PRIVATE KEY', '----'])
    end = '-'.join(['-----END PRIVATE KEY', '----'])
    assert 'private-data' not in redact(begin + '\nprivate-data\n' + end, [])


def test_required_guard_is_executed(tmp_path):
    path = tmp_path / 'run.xml'
    path.write_text('<testsuite tests="1"><testcase classname="tests.tasks.test_ocor_dev_0049" name="live"/></testsuite>')
    assert GUARD.check_junit(path, required_modules=['test_ocor_dev_0049'])['tests'] == 1


def test_missing_guard_cannot_be_hidden_by_other_passing_tests(tmp_path):
    path = tmp_path / 'run.xml'
    path.write_text('<testsuite tests="1"><testcase classname="tests.tasks.test_ocor_dev_0048" name="live"/></testsuite>')
    with pytest.raises(GUARD.CampaignError, match='required guard'):
        GUARD.check_junit(path, required_modules=['test_ocor_dev_0049'])


def test_candidate_head_is_bound_before_execution(tmp_path):
    import subprocess
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'test'], check=True)
    head = subprocess.check_output(['git', '-C', str(tmp_path), 'rev-parse', 'HEAD'], text=True).strip()
    GUARD.verify_revision(tmp_path, head)
    with pytest.raises(GUARD.CampaignError, match='HEAD'):
        GUARD.verify_revision(tmp_path, '0' * 40)


def test_candidate_tracked_changes_are_rejected(tmp_path):
    import subprocess
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    file = tmp_path / 'file'
    file.write_text('original')
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'file'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'test'], check=True)
    head = subprocess.check_output(['git', '-C', str(tmp_path), 'rev-parse', 'HEAD'], text=True).strip()
    file.write_text('changed')
    with pytest.raises(GUARD.CampaignError, match='tracked'):
        GUARD.verify_revision(tmp_path, head)


def test_download_digest_matches_and_mismatch_fails_closed():
    import hashlib
    from provision_qualification_tools import checked_digest
    data = b'qualification-tool'
    checked_digest(data, hashlib.sha256(data).hexdigest())
    with pytest.raises(ValueError, match='checksum mismatch'):
        checked_digest(data + b'tampered', hashlib.sha256(data).hexdigest())


def test_qualification_lock_checks_are_non_mutating_and_fail_closed(tmp_path):
    import json
    from copy import deepcopy
    from provision_qualification_tools import load_lock
    lock = json.loads((Path(__file__).resolve().parents[2] / 'infra/qualification_tools.lock.json').read_text())
    (tmp_path / 'infra').mkdir()
    path = tmp_path / 'infra/qualification_tools.lock.json'
    path.write_text(json.dumps(lock))
    assert len(load_lock(tmp_path)) == 3
    assert not (tmp_path / '.ocor').exists()
    for field, value in [('source_sha256', 'wrong'), ('source', 'http://untrusted.invalid/tool'), ('archive_member', '../helm')]:
        damaged = deepcopy(lock)
        damaged['tools'][0][field] = value
        path.write_text(json.dumps(damaged))
        with pytest.raises(ValueError):
            load_lock(tmp_path)
    path.unlink()
    with pytest.raises(OSError):
        load_lock(tmp_path)


def test_fuseki_resource_validation_uses_java_not_init():
    from bootstrap_ci_environment import running_jvm_args
    assert running_jvm_args('PID COMMAND\n1 /sbin/docker-init -- /opt/fuseki/fuseki-server\n41 /opt/java/bin/java -Xms128m -Xmx1G -jar server.jar\n')[:3] == ['/opt/java/bin/java', '-Xms128m', '-Xmx1G']


@pytest.mark.parametrize('processes', [
    'COMMAND\n/sbin/docker-init -- server\n',
    'COMMAND\njava -Xms128m -Xmx4G -jar server.jar\n',
    'COMMAND\njava -Xms128m -Xmx1G -Xmx4G -jar server.jar\n',
    'COMMAND\njava -Xms128m -Xmx1G -XX:MaxHeapSize=4G -jar server.jar\n',
    'COMMAND\njava -Xms128m -Xmx1G\njava -Xms128m -Xmx1G\n',
])
def test_fuseki_unbounded_absent_or_ambiguous_jvm_fails_closed(processes):
    from bootstrap_ci_environment import running_jvm_args
    from ocor_bootstrap_lib import BootstrapError
    with pytest.raises(BootstrapError):
        running_jvm_args(processes)


@pytest.mark.parametrize("resource_kind", ["containers", "volumes", "networks"])
def test_ci_teardown_missing_credentials_with_resources_fails_closed(tmp_path, monkeypatch, resource_kind):
    import bootstrap_ci_environment as ci
    from ocor_bootstrap_lib import BootstrapError
    resources = {kind: [] for kind in ("containers", "volumes", "networks")}
    resources[resource_kind] = ["owned-resource"]
    monkeypatch.setattr(ci, "owned_resources", lambda repository: resources, raising=False)
    monkeypatch.setattr(ci, "execute", lambda *args: pytest.fail("must not mutate without credentials"))
    with pytest.raises(BootstrapError, match="credentials absent.*resources remain"):
        ci.teardown(tmp_path)


def test_ci_teardown_absent_credentials_and_no_resources_is_verified_noop(tmp_path, monkeypatch):
    import bootstrap_ci_environment as ci
    monkeypatch.setattr(ci, "owned_resources", lambda repository: {
        "containers": [], "volumes": [], "networks": []
    }, raising=False)
    monkeypatch.setattr(ci, "execute", lambda *args: pytest.fail("empty stack must not call Compose"))
    assert ci.teardown(tmp_path) == {"status": "PASS", "operation": "teardown", "result": "ALREADY_REMOVED",
                                    "residual": {"containers": [], "volumes": [], "networks": []}}


def test_ci_teardown_inventory_failure_is_not_an_empty_stack(tmp_path, monkeypatch):
    import bootstrap_ci_environment as ci
    from ocor_bootstrap_lib import BootstrapError
    def fail(*args):
        raise BootstrapError("docker inventory failed")
    monkeypatch.setattr(ci, "execute", fail)
    with pytest.raises(BootstrapError, match="docker inventory failed"):
        ci.teardown(tmp_path)


def test_ci_teardown_existing_credentials_runs_governed_reset_and_checks_residue(tmp_path, monkeypatch):
    import bootstrap_ci_environment as ci
    (tmp_path / ".ocor").mkdir()
    (tmp_path / ".ocor/bootstrap.env").touch()
    calls = []
    monkeypatch.setattr(ci, "execute", lambda *args: calls.append(args) or "")
    monkeypatch.setattr(ci, "owned_resources", lambda repository: {
        "containers": [], "volumes": [], "networks": []
    }, raising=False)
    assert ci.teardown(tmp_path)["result"] == "REMOVED"
    assert calls[0][1] == [sys.executable, "scripts/reset_test_environment.py", "--execute"]
    assert calls[0][3] == 180


def test_ci_teardown_residual_resources_are_a_failure(tmp_path, monkeypatch):
    import bootstrap_ci_environment as ci
    from ocor_bootstrap_lib import BootstrapError
    (tmp_path / ".ocor").mkdir()
    (tmp_path / ".ocor/bootstrap.env").touch()
    monkeypatch.setattr(ci, "execute", lambda *args: "")
    monkeypatch.setattr(ci, "owned_resources", lambda repository: {
        "containers": [], "volumes": ["residue"], "networks": []
    }, raising=False)
    with pytest.raises(BootstrapError, match="resources remain after teardown"):
        ci.teardown(tmp_path)


@pytest.mark.parametrize("exit_code", [0, 4])
def test_build_log_survives_success_and_nonzero_exit(tmp_path, exit_code):
    import bootstrap_ci_environment as ci
    from ocor_bootstrap_lib import BootstrapError
    (tmp_path / "reports/tests").mkdir(parents=True)
    command = [sys.executable, "-c", f"import sys; print('locked recipe step', flush=True); sys.exit({exit_code})"]
    if exit_code:
        with pytest.raises(BootstrapError, match="build failed"):
            ci.execute_logged(tmp_path, command, "build", 5, "ci_fuseki_build.log")
    else:
        ci.execute_logged(tmp_path, command, "build", 5, "ci_fuseki_build.log")
    assert (tmp_path / "reports/tests/ci_fuseki_build.log").read_text() == "locked recipe step\n"


def test_build_timeout_retains_last_step_and_fails_closed(tmp_path):
    import bootstrap_ci_environment as ci
    from ocor_bootstrap_lib import BootstrapError
    (tmp_path / "reports/tests").mkdir(parents=True)
    command = [sys.executable, "-c", "import time; print('downloading pinned archive', flush=True); time.sleep(10)"]
    with pytest.raises(BootstrapError, match="timeout after 1s.*build"):
        ci.execute_logged(tmp_path, command, "build", 1, "ci_fuseki_build.log")
    assert "downloading pinned archive" in (tmp_path / "reports/tests/ci_fuseki_build.log").read_text()


def test_full_suite_budget_is_90_minutes_and_60_minutes_requires_decision():
    assert GUARD.check_deadline(3599) is False
    assert GUARD.check_deadline(3601) is True
    assert GUARD.check_deadline(5399) is True
    with pytest.raises(GUARD.CampaignError, match="90-minute"):
        GUARD.check_deadline(5400)


def test_teardown_exports_exact_residue_even_when_reset_fails(tmp_path, monkeypatch, capsys):
    import json
    import bootstrap_ci_environment as ci
    from ocor_bootstrap_lib import BootstrapError
    (tmp_path / ".ocor").mkdir()
    (tmp_path / ".ocor/bootstrap.env").touch()
    residue = {"containers": [], "volumes": ["owned-volume"], "networks": ["owned-network"]}
    monkeypatch.setattr(ci, "owned_resources", lambda repository: residue)
    def fail(*args):
        raise BootstrapError("governed reset failed")
    monkeypatch.setattr(ci, "execute", fail)
    with pytest.raises(BootstrapError):
        ci.teardown(tmp_path)
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[-1]["residual"] == residue
    assert records[-1]["status"] == "FAIL"


def test_session_volume_attribution_does_not_depend_on_event_order():
    import bootstrap_ci_environment as ci
    events = [
        {"Type": "volume", "Action": "mount", "Actor": {"ID": "owned-volume", "Attributes": {"container": "test-id"}}},
        {"Type": "volume", "Action": "mount", "Actor": {"ID": "foreign-volume", "Attributes": {"container": "foreign-id"}}},
        {"Type": "container", "Action": "create", "Actor": {"ID": "test-id", "Attributes": {"name": "ocor-spike-0023-session"}}},
        {"Type": "container", "Action": "create", "Actor": {"ID": "foreign-id", "Attributes": {"name": "open-webui"}}},
    ]
    assert ci.session_resources(events) == {"containers": {"test-id": "ocor-spike-0023-session"}, "volumes": ["owned-volume"], "networks": {}}
    assert ci.session_resources(list(reversed(events))) == ci.session_resources(events)


def test_preexisting_volume_is_not_deleted_by_session_cleanup(tmp_path, monkeypatch):
    import bootstrap_ci_environment as ci
    (tmp_path / ".ocor").mkdir()
    import json
    record = {"repository": str(tmp_path.resolve()), "before_volumes": ["preexisting"],
              "resources": {"containers": {}, "volumes": ["preexisting", "created"]}}
    (tmp_path / ".ocor/campaign-resources.json").write_text(json.dumps(record))
    calls = []
    monkeypatch.setattr(ci, "execute", lambda repo, cmd, label, timeout: calls.append(cmd) or "")
    monkeypatch.setattr(ci, "session_inventory", lambda repository: {"containers": {}, "volumes": ["preexisting", "created"]} if not calls else {"containers": {}, "volumes": ["preexisting"]})
    ci.cleanup_session_resources(tmp_path)
    assert calls == [["docker", "volume", "rm", "created"]]


def test_failed_session_volume_removal_preserves_error(tmp_path, monkeypatch):
    import bootstrap_ci_environment as ci
    from ocor_bootstrap_lib import BootstrapError
    import json
    (tmp_path / ".ocor").mkdir()
    (tmp_path / ".ocor/campaign-resources.json").write_text(json.dumps({
        "repository": str(tmp_path.resolve()), "before_volumes": [],
        "resources": {"containers": {}, "volumes": ["created"]}}))
    monkeypatch.setattr(ci, "session_inventory", lambda repository: {"containers": {}, "volumes": ["created"]})
    monkeypatch.setattr(ci, "execute", lambda *args: "")
    with pytest.raises(BootstrapError, match="session resources remain"):
        ci.cleanup_session_resources(tmp_path)


def stub_completed_campaign(tmp_path, monkeypatch, *, seconds, recorder_error=False):
    import json
    import bootstrap_ci_environment as ci
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".ocor").mkdir()
    (tmp_path / ".ocor/bootstrap.env").write_text("OCOR_LOCAL_POSTGRES_PASSWORD=unit-private-value\n")
    output = tmp_path / "run"
    monkeypatch.setattr(GUARD, "__file__", str(tmp_path / "scripts/campaign.py"))
    monkeypatch.setattr(sys, "argv", ["campaign.py", "--execute", "--output-dir", str(output)])
    snapshot = {str(n): state() for n in range(GUARD.MANDATORY_CONTAINERS)}
    monkeypatch.setattr(GUARD, "inspect_stack", lambda: snapshot)
    monkeypatch.setattr(GUARD, "inspect_kubernetes_runtimes", lambda: {})
    monkeypatch.setattr(GUARD, "collect_kubernetes_diagnostics", lambda path: path.write_text("no nodes\n"))
    ticks = iter([0, seconds, seconds, seconds])
    monkeypatch.setattr(GUARD.time, "monotonic", lambda: next(ticks))
    class Recorder:
        def __init__(self, repository):
            pass
        def finish(self):
            if recorder_error:
                raise ci.BootstrapError("event capture failed")
    monkeypatch.setattr(GUARD.kind_observer, "start_sampler", lambda *args: None)
    # Separate diagnostic port; existing supervisor assertions stay identical.
    monkeypatch.setattr(GUARD, "start_health_observer", lambda *args: None)
    class Process:
        pid = 99999
        returncode = 0
        def poll(self):
            return 0
    def launch(*args, stdout, **kwargs):
        stdout.write("unit-private-value; 1 passed\n")
        (output / "runtime_junit_post_approval.xml").write_text('<testsuite tests="1"><testcase classname="tests.tasks.test_ocor_dev_0048"/></testsuite>')
        return Process()
    monkeypatch.setattr(GUARD, "SessionRecorder", Recorder)
    monkeypatch.setattr(GUARD.subprocess, "Popen", launch)
    monkeypatch.setattr(GUARD, "collect_stack_diagnostics", lambda *args: None)
    return output, json


def test_completed_process_after_deadline_is_still_rejected(tmp_path, monkeypatch):
    output, json = stub_completed_campaign(tmp_path, monkeypatch, seconds=5401)
    assert GUARD.main() == 1
    assert "90-minute" in json.loads((output / "campaign_result.json").read_text())["error"]


def test_event_capture_failure_is_fail_closed_and_logs_are_still_redacted(tmp_path, monkeypatch):
    output, json = stub_completed_campaign(tmp_path, monkeypatch, seconds=1, recorder_error=True)
    assert GUARD.main() == 1
    assert json.loads((output / "campaign_result.json").read_text())["status"] == "FAIL"
    assert "unit-private-value" not in (output / "post_remediation_runtime.log").read_text()


@pytest.mark.parametrize("event", [
    {"Type": "container", "Action": "create", "Actor": None},
    {"Type": "container", "Action": "create", "Actor": {"ID": "id", "Attributes": {"name": None}}},
    {"Type": "volume", "Action": "mount", "Actor": {"ID": "volume", "Attributes": {}}},
])
def test_malformed_ownership_event_cannot_silently_lose_attribution(event):
    import json
    from types import SimpleNamespace
    import bootstrap_ci_environment as ci
    recorder = ci.SessionRecorder.__new__(ci.SessionRecorder)
    recorder.process = SimpleNamespace(stdout=iter([json.dumps(event) + "\n"]))
    recorder.events = []
    recorder.errors = []
    recorder.observe()
    assert recorder.errors


def test_kubernetes_runtime_initial_start_and_proven_shutdown_are_allowed(monkeypatch):
    history = {}
    GUARD.check_kubernetes_runtimes(history, {'node:containerd': {'restarts': 0, 'active': 'activating', 'pid': 0}})
    GUARD.check_kubernetes_runtimes(history, {'node:containerd': {'restarts': 0, 'active': 'active', 'pid': 111}})
    GUARD.check_kubernetes_runtimes(history, {'node:containerd': {'restarts': 0, 'active': 'active', 'pid': 111}})
    seen = []
    monkeypatch.setattr(GUARD.kind_observer, 'confirm_missing_node', seen.append)
    GUARD.check_kubernetes_runtimes(history, {})
    assert seen == ['node'] and history == {}


@pytest.mark.parametrize('current', [
    {'restarts': 1, 'active': 'active', 'pid': 6825},
    {'restarts': 0, 'active': 'active', 'pid': 6825},
    {'restarts': 0, 'active': 'failed', 'pid': 0},
    {'restarts': 0, 'active': 'inactive', 'pid': 0},
])
def test_kubernetes_internal_restart_or_failure_cannot_qualify(current):
    history = {}
    GUARD.check_kubernetes_runtimes(history, {'node:containerd': {'restarts': 0, 'active': 'active', 'pid': 111}})
    with pytest.raises(GUARD.CampaignError, match='Kubernetes service'):
        GUARD.check_kubernetes_runtimes(history, {'node:containerd': current})


def test_kubernetes_first_observation_already_restarted_fails_closed():
    with pytest.raises(GUARD.CampaignError, match='Kubernetes service'):
        GUARD.check_kubernetes_runtimes({}, {'node:kubelet': {'restarts': 1, 'active': 'active', 'pid': 50}})


def test_kubernetes_runtime_inventory_is_confined_to_owned_cluster(monkeypatch):
    from types import SimpleNamespace
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[:2] == ['docker', 'ps']:
            return SimpleNamespace(returncode=0, stdout='node-id\n')
        if command[:2] == ['docker', 'inspect']:
            return SimpleNamespace(returncode=0, stdout='[{"Id":"node-id","Name":"/ocor-poc-control-plane","State":{"Running":true},"Config":{"Labels":{"io.x-k8s.kind.cluster":"ocor-poc"}}}]')
        return SimpleNamespace(returncode=0, stdout='ActiveState=active\nMainPID=111\nNRestarts=0\n')
    monkeypatch.setattr(GUARD.subprocess, 'run', run)
    assert len(GUARD.inspect_kubernetes_runtimes()) == 2
    assert calls[0][-1] == 'label=io.x-k8s.kind.cluster=ocor-poc'
    assert all(c[2] == 'node-id' for c in calls if c[:2] == ['docker', 'exec'])


def test_kubernetes_runtime_inventory_rejects_foreign_name(monkeypatch):
    from types import SimpleNamespace
    def run(command, **kwargs):
        if command[:2] == ['docker', 'ps']:
            return SimpleNamespace(returncode=0, stdout='foreign-id\n')
        if command[:2] == ['docker', 'inspect']:
            return SimpleNamespace(returncode=0, stdout='[{"Id":"foreign-id","Name":"/open-webui","State":{"Running":true},"Config":{"Labels":{"io.x-k8s.kind.cluster":"ocor-poc"}}}]')
        pytest.fail('foreign container must never be entered')
    monkeypatch.setattr(GUARD.subprocess, 'run', run)
    with pytest.raises(GUARD.CampaignError, match='scope'):
        GUARD.inspect_kubernetes_runtimes()


def test_full_campaign_rejects_an_internal_runtime_restart(tmp_path, monkeypatch):
    output, json = stub_completed_campaign(tmp_path, monkeypatch, seconds=10)
    monkeypatch.setattr(GUARD, 'inspect_kubernetes_runtimes', lambda: {
        'owned-node:containerd': {'restarts': 1, 'active': 'active', 'pid': 6825}})
    assert GUARD.main() == 1
    result = json.loads((output / 'campaign_result.json').read_text())
    assert result['status'] == 'FAIL'
    assert 'Kubernetes service restarted' in result['error']
    assert (output / 'kubernetes-diagnostics.log').exists()


def test_kubelet_bootstrap_pid_change_before_admission_is_allowed():
    history = {}
    for pid in (241, 749):
        GUARD.check_kubernetes_runtimes(history, {'node:kubelet': {
            'restarts': 0, 'active': 'active', 'pid': pid, 'admitted': False}})
    GUARD.check_kubernetes_runtimes(history, {'node:kubelet': {
        'restarts': 0, 'active': 'active', 'pid': 749, 'admitted': True}})
    assert history['node:kubelet']['pid'] == 749
    with pytest.raises(GUARD.CampaignError):
        GUARD.check_kubernetes_runtimes(history, {'node:kubelet': {
            'restarts': 0, 'active': 'active', 'pid': 800, 'admitted': True}})


@pytest.mark.parametrize('service', ['containerd', 'kubelet'])
def test_genuine_auto_restart_is_rejected_even_during_node_bootstrap(service):
    with pytest.raises(GUARD.CampaignError):
        GUARD.check_kubernetes_runtimes({}, {'node:' + service: {
            'restarts': 1, 'active': 'active', 'pid': 800, 'admitted': False}})


def test_stop_interrupts_the_owned_suspended_process_group():
    import os
    import signal
    import subprocess
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        os.killpg(process.pid, signal.SIGSTOP)
        GUARD.stop(process, resume=True)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGCONT)
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


@pytest.mark.parametrize('active,pid', [('inactive', 0), ('activating', 0), ('active', 0)])
def test_admitted_node_must_have_running_kubelet_on_first_observation(active, pid):
    with pytest.raises(GUARD.CampaignError):
        GUARD.check_kubernetes_runtimes({}, {'node:kubelet': {
            'restarts': 0, 'active': active, 'pid': pid, 'admitted': True}})


# --- Parallel CI parts (PO decision REM-0017-CI-CAMPAIGN-DURATION, 2026-10-09) ---

HELM = 'tests/tasks/test_ocor_dev_0049.py::test_helm_profile_on_kubernetes_backs_up_restores_and_gates_readiness'
NODEIDS = [HELM] + [f'tests/tasks/test_ocor_dev_00{n:02d}.py::test_case[{k}]' for n in range(10, 20) for k in range(7)] + [
    'tests/runtime/test_surface.py::TestSandbox::test_rejects[sum(*[1, 2])]',
    'tests/tasks/test_ocor_dev_0048.py::test_repair4_svid_bounds_identity_and_secret',
    'tests/tasks/test_ocor_dev_0049.py::test_restore_replay_is_deterministic',
    'tests/tasks/test_ocor_dev_0049.py::test_custodian_signed_receipt_time_branches[future]',
]


def module_of(node):
    return node.split('::', 1)[0]


def test_modules_are_never_split_except_qualified_0049():
    # PO 2026-10-10 supersedes the indivisible 0049 constraint after REM19 GO.
    for count in (2, 3, 4):
        parts = GUARD.partition(NODEIDS, count)
        owner = {}
        for index, part in enumerate(parts):
            for node in part:
                if module_of(node) == "tests/tasks/test_ocor_dev_0049.py":
                    continue
                assert owner.setdefault(module_of(node), index) == index, node
        assert next(part for part in parts if HELM in part) == [HELM]


def test_qualified_0049_cases_split_and_helm_has_its_own_part():
    nodes = [HELM] + [f"tests/tasks/test_ocor_dev_0049.py::test_case[{k}]" for k in range(389)]
    parts = GUARD.partition(nodes, 4)
    assert next(part for part in parts if HELM in part) == [HELM]
    assert sorted(node for part in parts for node in part) == sorted(nodes)
    assert sum(bool(part) for part in parts) == 4
    assert max(len(part) for part in parts if HELM not in part) == 130


def test_helm_is_reserved_even_if_other_tests_are_heavier(monkeypatch):
    monkeypatch.setattr(GUARD, "node_weight", lambda node: 1 if node == HELM else 10000)
    nodes = [HELM, "one.py::test_one", "two.py::test_two", "three.py::test_three"]
    parts = GUARD.partition(nodes, 3)
    assert next(part for part in parts if HELM in part) == [HELM]
    assert sorted(node for part in parts for node in part) == sorted(nodes)


def test_partition_requires_more_units_than_parts():
    with pytest.raises(GUARD.CampaignError, match='units'):
        GUARD.partition(['a.py::t1', 'a.py::t2', 'a.py::t3'], 2)


def test_partition_is_deterministic_complete_disjoint_and_balanced():
    parts = GUARD.partition(NODEIDS, 3)
    assert parts == GUARD.partition(list(NODEIDS), 3)
    assert GUARD.partition_digest(parts) == GUARD.partition_digest(GUARD.partition(NODEIDS, 3))
    assert len(parts) == 3 and all(parts)
    flat = [node for part in parts for node in part]
    assert sorted(flat) == sorted(NODEIDS) and len(flat) == len(set(flat))
    order = {node: index for index, node in enumerate(NODEIDS)}
    assert all(part == sorted(part, key=order.__getitem__) for part in parts)
    loads = [sum(GUARD.node_weight(node) for node in part) for part in parts]
    units = GUARD.partition_units(NODEIDS)
    assert max(loads) - min(loads) <= max(sum(GUARD.node_weight(node) for node in unit) for unit in units)
    assert GUARD.node_weight(HELM) > GUARD.DEFAULT_TEST_WEIGHT


@pytest.mark.parametrize('count', [0, 1])
def test_partition_requires_at_least_two_parts(count):
    with pytest.raises(GUARD.CampaignError, match='at least 2'):
        GUARD.partition(NODEIDS, count)


@pytest.mark.parametrize('nodeids', [[], ['a.py::t', 'a.py::t'], ['a.py::t'], ['a.py::t', 'a.py::u']])
def test_partition_rejects_empty_duplicate_or_too_small_collections(nodeids):
    with pytest.raises(GUARD.CampaignError):
        GUARD.partition(nodeids, 2)


def test_junit_identity_matches_real_pytest_junit(tmp_path):
    import subprocess
    import xml.etree.ElementTree as ET
    package = tmp_path / 'tests/tasks'
    package.mkdir(parents=True)
    (package / 'test_sample.py').write_text(
        'import pytest\n'
        'def test_plain():\n    pass\n'
        'class TestGroup:\n    @pytest.mark.parametrize("v", ["sum(*[1, 2])", "a::b", "x/y"])\n'
        '    def test_param(self, v):\n        pass\n')
    junit = tmp_path / 'run.xml'
    collected = GUARD.collect_nodeids(tmp_path, ['tests/'])
    assert len(collected) == 4
    subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', f'--junitxml={junit}', *collected],
                   cwd=tmp_path, check=True, capture_output=True)
    reported = sorted((case.get('classname'), case.get('name')) for case in ET.parse(junit).getroot().iter('testcase'))
    assert reported == sorted(GUARD.junit_identity(node) for node in collected)


def test_collection_failure_is_not_an_empty_selection(tmp_path):
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/test_broken.py').write_text('raise RuntimeError("import failure")\n')
    with pytest.raises(GUARD.CampaignError, match='collection'):
        GUARD.collect_nodeids(tmp_path, ['tests/'])


@pytest.mark.parametrize('selection', [['tests/'], ['tests/test_imports.py::test_repository_imports']])
def test_collection_and_execution_resolve_the_selected_repository(tmp_path, monkeypatch, selection):
    """Explicit parts must import root packages without another module's side effects."""
    import subprocess
    repository = tmp_path / 'candidate'
    suite = repository / 'ocor-runtime'
    (suite / 'tests').mkdir(parents=True)
    (suite / 'src').mkdir()
    (repository / 'spikes').mkdir()
    (repository / 'spikes/__init__.py').write_text('SOURCE = "candidate"\n')
    (suite / 'src/local_runtime.py').write_text('SOURCE = "candidate-runtime"\n')
    (suite / 'tests/test_imports.py').write_text(
        'import spikes\nimport local_runtime\n'
        'def test_repository_imports():\n'
        '    assert spikes.SOURCE == "candidate"\n'
        '    assert local_runtime.SOURCE == "candidate-runtime"\n')
    # Model an inherited implementer checkout; the candidate must take precedence.
    inherited = tmp_path / 'implementer'
    (inherited / 'spikes').mkdir(parents=True)
    (inherited / 'spikes/__init__.py').write_text('raise RuntimeError("foreign checkout")\n')
    monkeypatch.setenv('PYTHONPATH', str(inherited))
    collected = GUARD.collect_nodeids(suite, selection)
    assert collected == ['tests/test_imports.py::test_repository_imports']
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *collected],
        cwd=suite, env=GUARD.pytest_environment(suite), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '1 passed' in result.stdout


def test_explicit_collection_imports_root_without_inherited_pythonpath(tmp_path, monkeypatch):
    suite = tmp_path / 'ocor-runtime'
    (suite / 'tests').mkdir(parents=True)
    (tmp_path / 'root_module.py').write_text('VALUE = 42\n')
    (suite / 'tests/test_root.py').write_text(
        'from root_module import VALUE\ndef test_value():\n    assert VALUE == 42\n')
    monkeypatch.delenv('PYTHONPATH', raising=False)
    assert GUARD.collect_nodeids(suite, ['tests/test_root.py::test_value']) == [
        'tests/test_root.py::test_value']


def test_repository_path_does_not_mask_a_real_collection_failure(tmp_path, monkeypatch):
    suite = tmp_path / 'ocor-runtime'
    (suite / 'tests').mkdir(parents=True)
    (tmp_path / 'root_module.py').write_text('raise RuntimeError("real root import failure")\n')
    (suite / 'tests/test_root.py').write_text('import root_module\ndef test_value():\n    pass\n')
    monkeypatch.delenv('PYTHONPATH', raising=False)
    with pytest.raises(GUARD.CampaignError, match='real root import failure'):
        GUARD.collect_nodeids(suite, ['tests/test_root.py::test_value'])


def test_part_budget_is_45_minutes_and_30_minutes_requires_rebalancing():
    assert GUARD.check_deadline(1799, limit=GUARD.PART_LIMIT_SECONDS, threshold=GUARD.PART_REBALANCE_SECONDS) is False
    assert GUARD.check_deadline(1801, limit=GUARD.PART_LIMIT_SECONDS, threshold=GUARD.PART_REBALANCE_SECONDS) is True
    with pytest.raises(GUARD.CampaignError, match='45-minute'):
        GUARD.check_deadline(2700, limit=GUARD.PART_LIMIT_SECONDS, threshold=GUARD.PART_REBALANCE_SECONDS)


def junit_xml(nodes, *, outcome=None):
    cases = []
    for node in nodes:
        classname, name = GUARD.junit_identity(node)
        body = f'<{outcome} message="x"/>' if outcome else ''
        cases.append(f'<testcase classname="{classname}" name="{name}" time="1.0">{body}</testcase>')
    counts = {key: (len(nodes) if outcome == key[:-1] or (outcome == 'skipped' and key == 'skipped') else 0) for key in ('failures', 'errors', 'skipped')}
    attrs = ' '.join(f'{key}="{value}"' for key, value in counts.items())
    return f'<testsuites><testsuite name="pytest" tests="{len(nodes)}" {attrs}>{"".join(cases)}</testsuite></testsuites>'


def write_parts(root, nodeids, count, *, mutate=None):
    import json
    from xml.sax.saxutils import quoteattr
    parts = GUARD.partition(nodeids, count)
    collected = GUARD.collection_digest(nodeids)
    for index, selected in enumerate(parts, start=1):
        part = root / f'ocor-full-part-{index}-sha' / f'part-{index}'
        part.mkdir(parents=True)
        executed = list(selected)
        meta = {'collected_count': len(nodeids), 'collected_sha256': collected, 'partition_sha256': GUARD.partition_digest(parts),
                'selected': selected, 'shard_count': count, 'shard_index': index}
        result = {'status': 'PASS', 'duration_seconds': 600.0 + index, 'shard_index': index, 'shard_count': count}
        outcome = None
        if mutate:
            executed, meta, result, outcome = mutate(index, executed, meta, result)
        (part / 'partition.json').write_text(json.dumps(meta))
        (part / 'campaign_result.json').write_text(json.dumps(result))
        (part / 'runtime_junit_post_approval.xml').write_text(junit_xml(executed, outcome=outcome).replace('name="test_rejects[sum(*[1, 2])]"', 'name=' + quoteattr('test_rejects[sum(*[1, 2])]')))
        (part / 'runtime_coverage.data').write_text('coverage')
    return parts


def stub_aggregation(tmp_path, monkeypatch):
    monkeypatch.setattr(GUARD, 'collect_nodeids', lambda directory, selection: list(NODEIDS))
    monkeypatch.setattr(GUARD, 'combine_coverage', lambda suite, files, output: (output / 'runtime_coverage_post_approval.json').write_text('{"totals": {}}'))
    return tmp_path / 'parts', tmp_path / 'aggregate'


def test_aggregate_accepts_exact_union_and_merges_junit(tmp_path, monkeypatch):
    import json
    parts_dir, output = stub_aggregation(tmp_path, monkeypatch)
    write_parts(parts_dir, NODEIDS, 3)
    result = GUARD.aggregate(parts_dir, tmp_path, 3, output, required_modules=['test_ocor_dev_0048', 'test_ocor_dev_0049'])
    assert result['status'] == 'PASS'
    assert result['union'] == {'collected': len(NODEIDS), 'executed': len(NODEIDS), 'missing': [], 'duplicated': [], 'unexpected': []}
    assert [part['shard_index'] for part in result['parts']] == [1, 2, 3]
    assert GUARD.check_junit(output / 'runtime_junit_post_approval.xml')['tests'] == len(NODEIDS)
    assert json.loads((output / 'campaign_result.json').read_text())['status'] == 'PASS'


def drop_first(index, executed, meta, result):
    # Parts 1 and 2 hold one heavy case each; drop from the part with many cases.
    return (executed[1:] if index == 3 else executed), meta, result, None


def duplicate_into_two(index, executed, meta, result):
    return (executed + [HELM] if HELM not in executed else executed), meta, result, None


def add_unexpected(index, executed, meta, result):
    return (executed + ['tests/tasks/test_extra.py::test_unknown'] if index == 2 else executed), meta, result, None


def skipped_part(index, executed, meta, result):
    return executed, meta, result, ('skipped' if index == 3 else None)


def failed_part(index, executed, meta, result):
    return executed, meta, result, ('failure' if index == 1 else None)


def foreign_collection(index, executed, meta, result):
    return executed, {**meta, 'collected_sha256': '0' * 64} if index == 2 else meta, result, None


def changed_selection(index, executed, meta, result):
    return executed, {**meta, 'selected': meta['selected'][1:]} if index == 1 else meta, result, None


def failed_campaign(index, executed, meta, result):
    return executed, meta, ({**result, 'status': 'FAIL'} if index == 2 else result), None


def overlong_part(index, executed, meta, result):
    return executed, meta, ({**result, 'duration_seconds': 2700.0} if index == 3 else result), None


def wrong_count(index, executed, meta, result):
    return executed, {**meta, 'shard_count': 2} if index == 1 else meta, result, None


@pytest.mark.parametrize('mutate,reason', [
    (drop_first, 'missing'), (duplicate_into_two, 'duplicated'), (add_unexpected, 'unexpected'),
    (skipped_part, 'nonqualifying JUnit'), (failed_part, 'nonqualifying JUnit'), (foreign_collection, 'collection'),
    (changed_selection, 'partition'), (failed_campaign, 'not PASS'), (overlong_part, '45-minute'), (wrong_count, 'shard'),
])
def test_aggregate_rejects_every_nonqualifying_union(tmp_path, monkeypatch, mutate, reason):
    import json
    parts_dir, output = stub_aggregation(tmp_path, monkeypatch)
    write_parts(parts_dir, NODEIDS, 3, mutate=mutate)
    with pytest.raises(GUARD.CampaignError, match=reason):
        GUARD.aggregate(parts_dir, tmp_path, 3, output, required_modules=['test_ocor_dev_0048'])
    assert json.loads((output / 'campaign_result.json').read_text())['status'] == 'FAIL'


def test_aggregate_rejects_a_missing_part(tmp_path, monkeypatch):
    import shutil
    parts_dir, output = stub_aggregation(tmp_path, monkeypatch)
    write_parts(parts_dir, NODEIDS, 3)
    shutil.rmtree(parts_dir / 'ocor-full-part-2-sha')
    with pytest.raises(GUARD.CampaignError, match='parts'):
        GUARD.aggregate(parts_dir, tmp_path, 3, output, required_modules=[])


def test_aggregate_rejects_missing_required_module(tmp_path, monkeypatch):
    parts_dir, output = stub_aggregation(tmp_path, monkeypatch)
    write_parts(parts_dir, NODEIDS, 3)
    with pytest.raises(GUARD.CampaignError, match='required guard'):
        GUARD.aggregate(parts_dir, tmp_path, 3, output, required_modules=['test_ocor_dev_0099'])


def test_aggregate_rejects_missing_coverage_data(tmp_path, monkeypatch):
    parts_dir, output = stub_aggregation(tmp_path, monkeypatch)
    write_parts(parts_dir, NODEIDS, 3)
    (parts_dir / 'ocor-full-part-1-sha/part-1/runtime_coverage.data').unlink()
    with pytest.raises(GUARD.CampaignError, match='coverage'):
        GUARD.aggregate(parts_dir, tmp_path, 3, output, required_modules=[])


def test_aggregate_flags_rebalancing_above_30_minutes(tmp_path, monkeypatch):
    parts_dir, output = stub_aggregation(tmp_path, monkeypatch)
    write_parts(parts_dir, NODEIDS, 3, mutate=lambda i, e, m, r: (e, m, {**r, 'duration_seconds': 1900.0} if i == 1 else r, None))
    assert GUARD.aggregate(parts_dir, tmp_path, 3, output, required_modules=[])['rebalance_required'] is True


def test_part_runs_only_its_verified_selection(tmp_path, monkeypatch):
    output, json = stub_completed_campaign(tmp_path, monkeypatch, seconds=10)
    monkeypatch.setattr(sys, 'argv', ['campaign.py', '--execute', '--output-dir', str(output), '--shard-index', '2', '--shard-count', '3'])
    selected = GUARD.partition(NODEIDS, 3)[1]
    calls = []
    def collect(directory, selection):
        calls.append(list(selection))
        return list(NODEIDS) if selection == ['tests/'] else list(selection)
    monkeypatch.setattr(GUARD, 'collect_nodeids', collect)
    launched = []
    def launch(command, *, stdout, **kwargs):
        launched.append(command)
        assert kwargs['env'] == GUARD.pytest_environment(Path(kwargs['cwd']))
        stdout.write('ok\n')
        (output / 'runtime_junit_post_approval.xml').write_text(junit_xml(selected))
        (Path(kwargs['cwd']) / '.coverage').write_text('data')
        class Process:
            pid = 99999
            returncode = 0
            def poll(self):
                return 0
        return Process()
    monkeypatch.setattr(GUARD.subprocess, 'Popen', launch)
    (tmp_path / 'ocor-runtime').mkdir()
    assert GUARD.main() == 0
    assert calls == [['tests/'], selected]
    assert launched[0][-len(selected):] == selected and 'tests/' not in launched[0]
    meta = json.loads((output / 'partition.json').read_text())
    assert meta['shard_index'] == 2 and meta['selected'] == selected
    result = json.loads((output / 'campaign_result.json').read_text())
    assert result['status'] == 'PASS' and result['shard_index'] == 2 and result['counts']['tests'] == len(selected)
    assert (output / 'runtime_coverage.data').read_text() == 'data'


def test_part_whose_selection_collects_differently_fails_before_execution(tmp_path, monkeypatch):
    output, json = stub_completed_campaign(tmp_path, monkeypatch, seconds=10)
    monkeypatch.setattr(sys, 'argv', ['campaign.py', '--execute', '--output-dir', str(output), '--shard-index', '1', '--shard-count', '3'])
    monkeypatch.setattr(GUARD, 'collect_nodeids', lambda directory, selection: list(NODEIDS) if selection == ['tests/'] else list(selection)[1:])
    monkeypatch.setattr(GUARD.subprocess, 'Popen', lambda *a, **k: pytest.fail('a divergent selection must never execute'))
    (tmp_path / 'ocor-runtime').mkdir()
    assert GUARD.main() == 1
    assert 'selection' in json.loads((output / 'campaign_result.json').read_text())['error']


def test_known_node_disappearance_cannot_qualify_without_removal_proof(monkeypatch):
    history = {"node:containerd": {"restarts": 0, "active": "active", "pid": 111}}
    def reject(node):
        raise GUARD.kind_observer.TeardownObservationError("no removal proof")
    monkeypatch.setattr(GUARD.kind_observer, "confirm_missing_node", reject)
    with pytest.raises(GUARD.kind_observer.TeardownObservationError, match="proof"):
        GUARD.check_kubernetes_runtimes(history, {})
    assert "node:containerd" in history


# REM-0019 cycle 3, VF-001 of OCOR-DEV-REM-0019-712fc2b79977-2: the verifier ran the
# campaign from a worktree whose .ocor/tools/bin/kind is a symlink to the official
# binary. The 0049 fixture launched `kind delete` through that link, so argv[0] never
# equalled the resolved KIND_BINARY and the v2 sampler saw no remover. Real kind
# binary, real /proc, real sampler and the real 0049 tool() lookup; kind is held alive
# by a fake `docker` on its own PATH only, so no Docker object is touched.
KIND_TAIL = ['delete', 'cluster', '--name', 'ocor-poc']
LEADER = '''import json, subprocess, sys
argv, path, new_session = json.loads(sys.argv[1])
subprocess.run(argv, env={"PATH": path}, capture_output=True, start_new_session=new_session)
'''


def official_kind():
    binary = GUARD.qualification_kind_binary(Path(__file__).resolve().parents[2])
    if not binary.is_file():
        pytest.fail('official kind binary unavailable (DEC-211 provisioning required); not a skip')
    return binary


def verifier_layout(tmp_path, target):
    """The verifier worktree: no checkout tools, only a symlinked .ocor/tools/bin/kind."""
    worktree = tmp_path / 'wt'
    tools = worktree / '.ocor/tools/bin'
    tools.mkdir(parents=True)
    (tools / 'kind').symlink_to(target)
    return worktree


def fixture_kind(monkeypatch, worktree):
    """argv[0] exactly as test_ocor_dev_0049.tool('kind') returns it for this worktree."""
    path = Path(__file__).resolve().parents[2] / 'ocor-runtime/tests/tasks/test_ocor_dev_0049.py'
    spec = importlib.util.spec_from_file_location('ocor_rem0019_fixture_0049', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', worktree)
    return module.tool('kind')


def observe_remover(tmp_path, kind_binary, argv, *, path='', new_session=False):
    """Run a pytest-like session leader that launches argv; return sampler rows and liveness."""
    import json
    import os
    import subprocess
    import time
    fakebin = tmp_path / 'fakebin'
    fakebin.mkdir(exist_ok=True)
    (fakebin / 'docker').write_text('#!/bin/sh\nsleep 2\nexit 1\n')
    (fakebin / 'docker').chmod(0o755)
    observer = GUARD.kind_observer
    leader = subprocess.Popen([sys.executable, '-I', '-c', LEADER,
                               json.dumps([argv, ':'.join(filter(None, [path, str(fakebin), '/usr/bin:/bin'])),
                                           new_session])], start_new_session=True)
    thread = observer.start_sampler(leader.pid, kind_binary)
    alive = 0
    try:
        while leader.poll() is None:
            for entry in Path('/proc').iterdir():
                try:
                    if (entry.name.isdecimal() and int(entry.name) != leader.pid
                            and (entry / 'cmdline').read_bytes().split(b'\0')[1:4] == [b'delete', b'cluster', b'--name']):
                        alive += 1
                except (OSError, IndexError):
                    continue
            time.sleep(observer.SAMPLE_SECONDS)
    finally:
        observer.stop_sampler(thread)
        if leader.poll() is None:
            os.killpg(leader.pid, 9)
    # The remover really lived for many sampling periods: a rejection is never a missed sample.
    assert alive >= 5, alive
    return [dict(row) for row in observer.REMOVER_OBSERVATIONS], leader.pid


def test_remover_launched_through_verifier_symlink_is_observed_in_the_pytest_group(tmp_path, monkeypatch):
    official = official_kind()
    worktree = verifier_layout(tmp_path, official)
    kind_binary = GUARD.qualification_kind_binary(worktree)
    assert kind_binary == official
    rows, leader = observe_remover(tmp_path, kind_binary, [fixture_kind(monkeypatch, worktree), *KIND_TAIL])
    assert len(rows) == 1, rows
    assert rows[0]['pgid'] == leader and rows[0]['command'][1:] == KIND_TAIL
    assert Path(rows[0]['command'][0]).resolve() == kind_binary


def test_remover_launched_through_the_checkout_binary_is_observed_in_the_pytest_group(tmp_path):
    """Control: the local layout (argv[0] is the real file) is observed by the same instrument."""
    official = official_kind()
    rows, leader = observe_remover(tmp_path, official, [str(official), *KIND_TAIL])
    assert len(rows) == 1, rows
    assert rows[0]['pgid'] == leader and rows[0]['command'] == [str(official), *KIND_TAIL]


def test_symlink_to_a_different_binary_is_never_the_owned_remover(tmp_path, monkeypatch):
    import shutil
    official = official_kind()
    foreign = tmp_path / 'foreign' / 'kind'
    foreign.parent.mkdir()
    shutil.copy2(official, foreign)
    worktree = verifier_layout(tmp_path, foreign)
    rows, _ = observe_remover(tmp_path, official, [fixture_kind(monkeypatch, worktree), *KIND_TAIL])
    assert rows == []


def test_relative_argv0_is_never_the_owned_remover(tmp_path):
    official = official_kind()
    rows, _ = observe_remover(tmp_path, official, ['kind', *KIND_TAIL], path=str(official.parent))
    assert rows == []


def test_remover_of_a_different_cluster_is_never_the_owned_remover(tmp_path, monkeypatch):
    official = official_kind()
    worktree = verifier_layout(tmp_path, official)
    argv = [fixture_kind(monkeypatch, worktree), *KIND_TAIL[:-1], 'foreign']
    rows, _ = observe_remover(tmp_path, official, argv)
    assert rows == []


def test_remover_outside_the_pytest_process_group_is_never_the_owned_remover(tmp_path, monkeypatch):
    official = official_kind()
    worktree = verifier_layout(tmp_path, official)
    rows, _ = observe_remover(tmp_path, official, [fixture_kind(monkeypatch, worktree), *KIND_TAIL],
                              new_session=True)
    assert rows == []


# Non-weakening proofs for the cycle 3 observer change (PO, 2026-10-20, variant B).
CYCLE3_BASE = '712fc2b799774281321c04209bfb6910b91f0941'
OBSERVER = 'scripts/observe_kind_teardown.py'


def observer_at_base(tmp_path):
    import subprocess
    root = Path(__file__).resolve().parents[2]
    source = tmp_path / 'observe_kind_teardown_base.py'
    source.write_text(subprocess.check_output(['git', '-C', str(root), 'show', f'{CYCLE3_BASE}:{OBSERVER}'], text=True))
    spec = importlib.util.spec_from_file_location('ocor_observer_cycle3_base', source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_remover_predicate_accepts_a_superset_only_by_absolute_alias_of_the_same_binary(tmp_path, monkeypatch):
    import itertools
    import os
    old, new = observer_at_base(tmp_path), GUARD.kind_observer
    kind = tmp_path / 'bin/kind'
    foreign = tmp_path / 'other/kind'
    for binary in (kind, foreign):
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text('binary')
    alias = tmp_path / 'wt/.ocor/tools/bin/kind'
    alias.parent.mkdir(parents=True)
    alias.symlink_to(kind)
    foreign_alias = tmp_path / 'wt/foreign-kind'
    foreign_alias.symlink_to(foreign)
    kind_binary = kind.resolve()
    # Relative names would resolve to the official file from this cwd: they must still be refused.
    monkeypatch.chdir(tmp_path)
    argv0s = [str(kind), str(alias), str(tmp_path / 'bin/../bin/kind'), str(foreign), str(foreign_alias),
              str(tmp_path / 'missing/kind'), 'kind', 'bin/kind', './kind', '']
    tails = [KIND_TAIL, KIND_TAIL[:-1], [*KIND_TAIL, '--verbosity', '1'], [*KIND_TAIL[:-1], 'foreign'],
             ['delete', 'cluster', '--name=ocor-poc'], ['create', 'cluster', '--name', 'ocor-poc'], []]
    exes = {'official': kind, 'alias': alias, 'foreign': foreign}
    proc = tmp_path / 'proc'
    differences, compared = [], 0
    for (exe_name, exe), argv0, tail, pgid in itertools.product(exes.items(), argv0s, tails, (43, 44)):
        pid_dir = proc / '42'
        if pid_dir.exists():
            for child in pid_dir.iterdir():
                child.unlink()
        pid_dir.mkdir(parents=True, exist_ok=True)
        (pid_dir / 'exe').symlink_to(exe)
        (pid_dir / 'stat').write_text('42 (kind) ' + ' '.join(['S'] + ['0'] * 18 + ['123']))
        (pid_dir / 'cmdline').write_bytes(('\0'.join([argv0, *tail]) + '\0').encode())
        verdicts = []
        for module in (old, new):
            monkeypatch.setattr(module, 'PROC', proc)
            monkeypatch.setattr(module, 'KIND_BINARY', kind_binary)
            monkeypatch.setattr(module, 'PYTEST_PGID', 43)
            monkeypatch.setattr(os, 'getpgid', lambda pid, pgid=pgid: pgid)
            verdicts.append(module.owned_remover() is not None)
        compared += 1
        assert not (verdicts[0] and not verdicts[1]), ('accepted before, rejected now', exe_name, argv0, tail, pgid)
        if verdicts[1] and not verdicts[0]:
            differences.append((exe_name, argv0, tuple(tail), pgid))
    assert compared == 3 * len(argv0s) * len(tails) * 2
    # The only admitted difference: same pgid, exact tail, exe of the official file and an
    # absolute argv[0] other than the literal resolved path whose realpath is that file.
    assert differences and all(
        pgid == 43 and list(tail) == KIND_TAIL and Path(exes[exe_name]).resolve() == kind_binary
        and os.path.isabs(argv0) and argv0 != str(kind_binary) and Path(os.path.realpath(argv0)) == kind_binary
        for exe_name, argv0, tail, pgid in differences), differences
    assert {argv0 for _, argv0, _, _ in differences} == {str(alias), str(tmp_path / 'bin/../bin/kind')} - {str(kind_binary)}


def test_observer_change_is_limited_to_the_argv_comparison_after_the_unchanged_exe_check():
    import difflib
    import subprocess
    root = Path(__file__).resolve().parents[2]
    before = subprocess.check_output(['git', '-C', str(root), 'show', f'{CYCLE3_BASE}:{OBSERVER}'], text=True).splitlines()
    after = (root / OBSERVER).read_text().splitlines()
    removed = [line[1:] for line in difflib.unified_diff(before, after, lineterm='', n=0)
               if line.startswith('-') and not line.startswith('---')]
    added = [line[1:] for line in difflib.unified_diff(before, after, lineterm='', n=0)
             if line.startswith('+') and not line.startswith('+++')]
    assert removed == ["            if args != [str(KIND_BINARY), 'delete', 'cluster', '--name', 'ocor-poc']:"]
    assert added == [
        "            # Identity is /proc/<pid>/exe above; argv[0] is caller-chosen. Accept only an",
        "            # absolute alias of the same file (verifier symlink), never a relative name.",
        "            if (args[1:] != ['delete', 'cluster', '--name', 'ocor-poc'] or not os.path.isabs(args[0])",
        "                    or Path(os.path.realpath(args[0])) != KIND_BINARY):",
    ]
    exe_check = ("            if os.getpgid(pid) != PYTEST_PGID or (folder / 'exe').resolve(strict=True) != KIND_BINARY:")
    assert before.count(exe_check) == after.count(exe_check) == 1
    assert after.index(exe_check) < after.index(added[2])
    assert before[:before.index(exe_check) + 1] == after[:after.index(exe_check) + 1]


def test_kind_binary_compared_by_the_sampler_is_always_a_resolved_path(tmp_path):
    import os
    official = official_kind()
    assert official == Path(os.path.realpath(official))
    worktree = verifier_layout(tmp_path, official)
    assert GUARD.qualification_kind_binary(worktree) == Path(os.path.realpath(official))
    thread = GUARD.kind_observer.start_sampler(os.getpid(), worktree / '.ocor/tools/bin/kind')
    try:
        assert GUARD.kind_observer.KIND_BINARY == Path(os.path.realpath(official))
    finally:
        GUARD.kind_observer.stop_sampler(thread)
